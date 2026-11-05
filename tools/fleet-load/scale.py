"""Scale assertions and aggregate report over FA3's observed recording trace."""
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import platform
import shutil

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / 'tools/scale-50'
spec = importlib.util.spec_from_file_location('scale_report', TOOLS / 'report.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
spec = importlib.util.spec_from_file_location('fa3_verifier', ROOT / 'tools/fleet-load/load.py')
fa3 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fa3)


def identity(fleet, installed):
    raw = (TOOLS / 'fixtures/workload-v1.json').read_text()
    definition = api.decode(raw)
    workload = {k: definition[k] for k in ('id', 'tickets', 'specs', 'arrival', 'role_policy')}
    workload['sha256'] = hashlib.sha256(raw.encode()).hexdigest()
    folder = Path(__file__).resolve().parent
    # The candidate may change; the measuring code must remain identical.
    model_paths = list(folder.glob('*.py')) + [ROOT / relative for relative in (
        'skills/launch-fleet/scripts/fixtures/gh.py',
        'skills/launch-fleet/scripts/fixtures/revision.sh',
        'tests/fleet/b5_fake.rs',
        'tests/fixture-entrypoints/cli.rs',
        'tests/fixture-entrypoints/fixture.rs',
        'tools/scale-50/report.py',
    )]
    model_files = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in sorted(model_paths)}
    measurement_model = dict(files=model_files, sha256=api.model_digest(model_files))
    tools = 'Python ' + platform.python_version() + '; ' + '; '.join(
        name + ':sha256=' + hashlib.sha256(Path(shutil.which(name)).read_bytes()).hexdigest()
        for name in ('sh', 'jq'))
    settings = (ROOT / 'docs/agents/fleet.md').read_bytes() + (ROOT / 'skills/launch-fleet/scripts/fixtures/check.json').read_bytes()
    return dict(definition=definition, workload_bytes=raw, workload=workload, measurement_model=measurement_model,
                candidate=dict(revision=hashlib.sha256(Path(fleet).read_bytes()).hexdigest() + '; installed-cli-sha256=' + installed['binary_sha256'],
                               tools=tools,
                               config=hashlib.sha256(raw.encode() + settings).hexdigest()))


def definition(trace):
    metadata = trace['identity']
    assert api.decode(metadata['workload_bytes']) == metadata['definition'], 'S6 workload definition mismatch'
    assert hashlib.sha256(metadata['workload_bytes'].encode()).hexdigest() == metadata['workload']['sha256'], 'S6 workload identity mismatch'
    assert metadata['candidate']['config'] == trace['config'] and metadata['candidate']['revision'] == trace['candidate'], 'S6 candidate identity mismatch'
    if 'measurement_model' in metadata:
        api.validate_model(metadata['measurement_model'])
    return metadata['definition']


def distribution(values):
    assert values, 'S6 missing timing observations'
    values = sorted(values)
    return dict(p50=values[math.ceil(len(values) * .50) - 1],
                p95=values[math.ceil(len(values) * .95) - 1], samples=len(values))


def begins(event):
    return (event['kind'] == 'spawn' and event['execution'] == 'running'
            or event['kind'] == 'execution-start'
            or event['kind'] == 'tell' and event.get('began', False))


def intervals(trace):
    active, result = {}, []
    events = trace['events']
    end = trace['ticks'][0]['now'] + definition(trace)['bounds']['virtual_duration_s']
    times = sorted({e['now'] for e in events} | {end})
    for now, end in zip(times, times[1:]):
        for e in (e for e in events if e['now'] == now):
            if begins(e):
                assert e['thread'] not in active, 'S5 duplicate execution interval'
                active[e['thread']] = e['role']
            elif e['kind'] == 'execution-end':
                assert e['thread'] in active, 'S5 execution ended without starting'
                active.pop(e['thread'])
            elif e['kind'] == 'archive':
                assert e['thread'] not in active, 'S5 archive during execution'
        roles = Counter(active.values())
        result.append(dict(start_s=now, end_s=end, builders=roles['builder'], reviewers=roles['reviewer']))
    return result


def measurements(trace):
    events = trace['events']
    readies, reviews, rechecks, merges, ci = {}, [], [], [], []
    backlog, rebacklog, peak, repeak = set(), set(), 0, 0
    waiting_ci = {}
    ready_merge = {}
    for e in events:
        key, now = e.get('ticket'), e['now']
        if e['kind'] == 'transition':
            action = e['action']
            if action == 'open' and key % 10 == 5:
                waiting_ci[key] = now
            elif action in ('open', 'ci', 'fix'):
                readies[key] = now
                (rebacklog if action == 'fix' else backlog).add(key)
                if action == 'ci':
                    ci.append(now - waiting_ci.pop(key))
            elif action == 'verdict' and e['verdict'] == 'APPROVE':
                ready_merge[key] = now
        elif begins(e) and e['role'] == 'reviewer':
            if key in rebacklog:
                rechecks.append(now - readies.pop(key)); rebacklog.remove(key)
            elif key in backlog:
                reviews.append(now - readies.pop(key)); backlog.remove(key)
        elif e['kind'] == 'merge-readback':
            assert e['merged'], 'S6 unverified merge'
            delay = now - ready_merge.pop(key)
            assert 0 <= delay <= definition(trace)['bounds']['merge_s'], 'S6 merge starvation'
            merges.append(delay)
        peak, repeak = max(peak, len(backlog)), max(repeak, len(rebacklog))
    assert not backlog and not rebacklog and not ready_merge and not waiting_ci, 'S6 undrained backlog'
    return reviews, rechecks, merges, ci, peak, repeak


def verify(trace):
    workload = definition(trace)
    start = trace['ticks'][0]['now']
    end = start + workload['bounds']['virtual_duration_s']
    assert all(start <= e['now'] < end for e in trace['events']), 'S6 event outside observation window'
    holds = [e for e in trace['events'] if e['kind'] == 'hold']
    assert [(e['now'] - start, e['ticket'], e['held']) for e in holds] == [(0, 1004, True), (600, 1004, False)], 'S6 held workload missing'
    assert all(e['now'] >= start + 600 for e in trace['events'] if e['kind'] == 'spawn' and e['ticket'] == 1004), 'S6 started held work'
    shared = [e for e in trace['events'] if e['tool'] == 'shared']
    expected_times = list(range(start, start + workload['bounds']['virtual_duration_s'], 600))
    assert [e['now'] for e in shared] == expected_times, 'S6 shared consumer omission'
    assert all(e['http'] == [dict(api='rest', page=1, cost=0, rows=1), dict(api='graphql', page=1, cost=2, rows=1)] for e in shared), 'S6 shared consumer accounting'
    wakes = trace['wakes']
    assert len(wakes) == 2 and all(len(w['intervals']) == 2 for w in wakes), 'S6 missing concurrent wakes'
    assert all(max(i['start'] for i in w['intervals']) < min(i['end'] for i in w['intervals']) for w in wakes), 'S6 wakes did not overlap'
    requests = []
    for e in trace['events']:
        if e['tool'] not in ('gh', 'shared'):
            continue
        assert e['http'] and len(e['http']) == e['http_expected'], 'S6 omitted HTTP page'
        # Internal CLI pagination must keep its complete response sequence.
        if len(e['http']) > 1 and len({h['api'] for h in e['http']}) == 1 and e.get('paginated'):
            assert [h['page'] for h in e['http']] == list(range(1, e['http_expected'] + 1)), 'S6 omitted HTTP page'
        for h in e['http']:
            assert h['api'] in ('rest', 'graphql') and type(h['cost']) is int and h['cost'] >= 0, 'S6 invalid transport'
            requests.append(dict(h, now=e['now'], shared=e['tool'] == 'shared'))
    assert any(e.get('paginated') and len(e.get('http', [])) > 1 for e in trace['events']), 'S6 pagination not exercised'
    budgets = {}
    for kind in ('rest', 'graphql'):
        rows = [r for r in requests if r['api'] == kind]
        assert rows, 'S6 missing budget'
        buckets = Counter()
        for row in rows:
            buckets[row['now'] // 3600] += 1 if kind == 'rest' else row['cost']
        limit = workload['bounds'][kind + '_limit']
        assert max(buckets.values()) <= limit, 'S6 HTTP budget overrun: ' + kind
        last = max(e['now'] for e in trace['events']) // 3600
        b = dict(requests=len(rows), limit=limit, remaining=limit - buckets[last], reset_s=(last + 1) * 3600)
        if kind == 'rest':
            b['shared_requests'] = sum(r['shared'] for r in rows)
        else:
            b.update(cost=sum(r['cost'] for r in rows), shared_cost=sum(r['cost'] for r in rows if r['shared']))
        budgets[kind] = b
    overlap = intervals(trace)
    assert max(i['builders'] + i['reviewers'] for i in overlap) == 50, 'S5 active peak must be 50'
    assert any(i['builders'] + i['reviewers'] == 50 and i['builders'] and i['reviewers'] and i['end_s'] > i['start_s'] for i in overlap), 'S5 missing both-role interval'
    measurements(trace)
    merges = {e['ticket']: e['head'] for e in trace['events'] if e['kind'] == 'merge'}
    readbacks = {e['ticket']: e['head'] for e in trace['events'] if e['kind'] == 'merge-readback' and e['merged']}
    assert merges == readbacks and len(readbacks) == 100, 'S6 unverified merge'
    return budgets, overlap


def report(trace):
    fa3.verify(trace)
    budgets, overlap = verify(trace)
    workload = definition(trace)
    reviews, rechecks, merges, ci, peak, repeak = measurements(trace)
    events = trace['events']
    starts = sum(e['kind'] == 'spawn' for e in events)
    end = trace['ticks'][0]['now'] + workload['bounds']['virtual_duration_s']
    duration = end - trace['ticks'][0]['now']
    requests = budgets['rest']['requests'] + budgets['graphql']['requests']
    merged_at = {e['ticket']: e['now'] for e in events if e['kind'] == 'merge-readback'}
    start_delays, seen_builders = [], set()
    for e in events:
        if begins(e) and e['role'] == 'builder' and e['ticket'] not in seen_builders:
            seen_builders.add(e['ticket'])
            ready = merged_at[e['ticket'] - 1] if e['ticket'] % 20 == 0 else trace['ticks'][0]['now'] + (600 if e['ticket'] == 1004 else 0)
            start_delays.append(e['now'] - ready)
    tick_http = {'rest_requests': [], 'graphql_requests': [], 'graphql_cost': []}
    for tick in trace['ticks']:
        rows = [h for e in events if e.get('fleet') == f'thr_synfleet{tick["spec"]}' and e['now'] == tick['now']
                for h in e.get('http', [])]
        tick_http['rest_requests'].append(sum(h['api'] == 'rest' for h in rows))
        tick_http['graphql_requests'].append(sum(h['api'] == 'graphql' for h in rows))
        tick_http['graphql_cost'].append(sum(h['cost'] for h in rows if h['api'] == 'graphql'))
    model = trace['identity'].get('measurement_model')
    result = dict(schema=api.SCHEMA, evidence_class='fixture', state='complete' if model else 'partial', measurement_model=model,
        workload=trace['identity']['workload'], candidate=trace['identity']['candidate'],
        bounds=workload['bounds'],
        coverage=[dict(route='launch-fleet/scripts/fleet.sh spec', mode='active recording follower', tickets=100,
                       gaps=['Follower models agent judgment; no LLM execution', 'Concurrent read-only event wakes defer owned work to the timer; claim elections remain outside coverage']),
                  dict(route='installed fleet tick --dry-run --json', mode='production dispatch with recording fixtures', tickets=trace['installed']['tickets'],
                       gaps=['Frontier only; not installed write/lifecycle parity', 'Installed internal HTTP traffic not measured']),
                  dict(route='launch-fleet/scripts/fleet.sh wake', mode='concurrent recording readers', tickets=1, gaps=['No overlapping write/claim election proof'])],
        window=dict(start_s=trace['ticks'][0]['now'], end_s=end, active_intervals=overlap),
        metrics=dict(tick_ms=distribution([t['wall_ms'] for t in trace['ticks']]),
                     starts=dict(attempted=starts, accepted=starts, uncertain=0, refused=0),
                     accepted_starts_per_minute=starts * 60 / duration,
                     http_per_tick={k: distribution(v) for k, v in tick_http.items()},
                     event_action_s=distribution(start_delays + reviews + rechecks + merges),
                     review_queue_s=distribution(reviews), recheck_delay_s=distribution(rechecks),
                     merge_delay_s=distribution(merges), ci_wait_s=distribution(ci),
                     review_backlog_peak=peak, recheck_backlog_peak=repeak, verified_merges=len(merges),
                     merges_per_hour=len(merges) * 3600 / duration, completed=len(merges),
                     requests_per_ticket=requests / len(merges), graphql_cost_per_ticket=budgets['graphql']['cost'] / len(merges)),
        budgets=dict(budgets, live_limits='unknown'),
        gaps=['All allowances, costs, active states and lifecycle times are synthetic; no live capacity claim',
              'Real gh internal requests, live credential scope, primary/secondary limits and host capacity unknown',
              'Refused/uncertain starts are not exercised by this workload; existing start proofs own recovery',
              'Installed tick wall time and traffic excluded from launch-fleet distributions'])
    if model is None:
        result['gaps'].append('Legacy trace lacks measurement-model fingerprints; comparison identity is unknown')
    api.validate(result)
    return result
