#!/usr/bin/env python3
"""Select pinned local existing artifacts. No collection, subprocess reads or API."""
import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile

import suite

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {'kind', 'slot', 'path', 'sha256', 'observed_at', 'evidence'}
KINDS = {'projected', 'ci_bench', 'factory_metrics', 'journey', 'skills_eval',
         'credits', 'claude_usage', 'board_graph', 'board_history', 'decisions'}
SLOTS = {'ci_bench': 'ci_bench', 'factory_metrics': 'factory_metrics',
         'journey': 'journey', 'skills_eval': 'skills_eval', 'credits': 'credits',
         'claude_usage': 'claude_usage', 'board_graph': 'board', 'board_history': 'board', 'decisions': 'decisions'}
POINT_PREREQUISITE = ('Native point observation has no nonempty native window; numeric projection '
                      'requires an admitted suite point-window representation. Approved partial/null observation only.')
LINK = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/'
                  r'(?:issues/[1-9][0-9]*(?:#issuecomment-[1-9][0-9]*)?'
                  r'|pull/[1-9][0-9]*(?:#(?:issuecomment-|discussion_r)[1-9][0-9]*)?'
                  r'|actions/runs/[1-9][0-9]*(?:/attempts/[1-9][0-9]*)?'
                  r'|commit/[0-9a-f]{40})')

# The retained-history credential and thread-id forms safe_record refuses in every string of a
# record. weekly.py applies the same pattern to recorded changes (#2718).
CREDENTIAL = re.compile(r'(?i)(?:\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}'
                        r'|authorization\s*:|bearer\s+|-----BEGIN .*PRIVATE KEY'
                        r'|\bthr_[A-Za-z0-9_-]+)')


@lru_cache(maxsize=None)
def native(path):
    """Load an existing offline reader only. Never invoke its CLI/collector."""
    file = ROOT / path
    spec = importlib.util.spec_from_file_location('war_room_' + file.stem, file)
    module = importlib.util.module_from_spec(spec)
    # Some existing readers import their sibling modules. Keep the search path
    # local to loading, and leave source modules' own behavior unchanged.
    before = sys.path[:]
    try:
        sys.path.insert(0, str(file.parent))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


def safe_record(record):
    """Validate the envelope, link allowlist and existing privacy text rules.

    Native projections below use fixed labels and selected numeric fields; no
    upstream prose/keys is copied. Projected providers must already be sanitized
    by their owner, as the suite contract requires. This guard is additional.
    """
    suite.validate(record)
    checker_module = native('tools/privacy-check/check.py')
    class Quiet(checker_module.Checker):
        def refuse(self, *args, **kwargs):
            self.findings += 1
    checker = Quiet()
    def strings(value):
        if isinstance(value, str):
            checker.text(value, 'record')
            suite.require(not CREDENTIAL.search(value), 'private payload refused')
        elif isinstance(value, dict):
            for key, item in value.items():
                strings(key)
                strings(item)
        elif isinstance(value, list):
            for item in value:
                strings(item)
    strings(record)
    suite.require(checker.findings == 0, 'private payload refused')
    for provider in record['providers']:
        for metric in provider['metrics']:
            suite.require(all(LINK.fullmatch(url) for url in metric['evidence']), 'unsupported evidence link')


def window(since, until, timezone='UTC'):
    suite.require(suite._time(since) < suite._time(until), 'invalid native window')
    return {'since': since, 'until': until, 'timezone': timezone}


def day_window(day):
    a = suite._time(day + 'T00:00:00Z')
    return window(a.strftime('%Y-%m-%dT%H:%M:%SZ'),
                  (a + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))


def metric(selection, schema, id, group, label, value, unit, span, *,
           state='known', prerequisites=(), identities=(), statistic='total', ticket=None):
    observed = selection['observed_at']
    if isinstance(value, Decimal):
        value = int(value) if value == value.to_integral_value() else float(value)
    # Missing native validity bounds stay unknown. A new tick is never a new
    # source observation or an invented five-minute validity guarantee.
    return {'id': id, 'group': group, 'label': label, 'state': state, 'value': value,
            'unit': unit, 'native_unit': unit, 'statistic': statistic, 'window': span,
            'observed_at': observed, 'fresh_until': None, 'freshness': 'unknown',
            'source': {'path': selection['path'], 'schema': schema, 'sha256': selection['sha256']},
            'evidence': selection['evidence'][:],
            'sample': {'observed': len(identities), 'expected': len(identities) if state == 'known' else None,
                       'identities': list(identities), 'numerator': None, 'denominator': None},
            'dimensions': {'direction': None, 'pool': None, 'stage': None, 'ticket': ticket, 'cohort': id},
            'interval': None, 'prerequisites': list(prerequisites)}


def provider(slot, metrics, prerequisites=()):
    if metrics and all(m['state'] == 'known' for m in metrics) and not prerequisites:
        state = 'known'
    elif any(m['state'] != 'unavailable' for m in metrics):
        state = 'partial'
    else:
        state = 'unavailable'
    return {'slot': slot, 'state': state, 'metrics': metrics,
            'prerequisites': list(prerequisites) if state != 'known' else []}


def _pinned_file(raw, filename, read):
    # Existing path-based validators see exactly the hash-checked bytes, not a
    # second read of a potentially replaced selected source.
    with tempfile.TemporaryDirectory(prefix='war-room-') as directory:
        path = Path(directory) / filename
        path.write_bytes(raw)
        return read(path)


def ci_bench(s, raw):
    B = native('tools/ci-bench/bench.py')
    p = _pinned_file(raw, 'point.json', lambda path: B.read_point(path.parent))
    span = window(p['since'], p['until'], 'PST-fixed-UTC-08:00'
                  if p['hours'] == 24 and p['since'][11:] == p['until'][11:] == '08:00:00Z' else 'UTC')
    items = [metric(s, p['schema'], 'merged', 'ci',
                    'Merged PRs, completed window, unclassified direction', p['merged_prs'], 'count', span,
                    statistic='count'),
             metric(s, p['schema'], 'merged-per-hour', 'ci',
                    'Merged PRs/hour, completed window, unclassified direction', p['merged_per_hour'], 'prs_per_hour', span)]
    c = p['code_runs']
    if c is not None:
        ids = [f'code-run-{i}' for i in range(1, c['runs'] + 1)]
        items.extend([metric(s, p['schema'], 'capacity', 'ci',
                             'CI capacity assumption, completed window; not merged throughput', c['prs_per_hour'], 'prs_per_hour', span, identities=ids),
                      metric(s, p['schema'], 'robot-minutes', 'ci',
                             'Robot minutes per successful code run', c['robot_minutes_per_run'], 'robot_minutes_per_code_run', span, identities=ids)])
        # The producer's queued_to_done values are native minutes.
        for stat in ('median', 'p90'):
            items.append(metric(s, p['schema'], 'queued-to-done-' + stat, 'ci',
                                'Completed CI queued to done (' + p.get('latency_basis', 'first job created to last job completed') + ')',
                                c['queued_to_done'][stat], 'minutes', span, identities=ids, statistic=stat))
    if p.get('cost'):
        cost = p['cost']
        gap = [] if cost['window_usd'] is not None else ['One or more CI job prices/timings are unknown; no total estimate is available.']
        items.append(metric(s, p['schema'], 'list-cost', 'ci',
                            'Completed-window CI list-rate estimate, not invoice or cost today',
                            cost['window_usd'], 'usd', span, state='partial' if gap else 'known', prerequisites=gap))
    return provider('ci_bench', items, [] if all(m['state'] == 'known' for m in items)
                    else ['Incomplete CI price/timing evidence; complete cost remains Unknown.'])


def factory_metrics(s, raw):
    M = native('tools/factory-metrics/metrics.py')
    p = M.load(raw.decode('utf-8'))
    M.exact(p, ('schema', 'date', 'merged_prs', 'merged_per_hour', 'hours', 'idle_minutes',
                'biggest_stall', 'stalls', 'historical_completeness', 'edited_fleet_comments',
                'clock_skew_comments', 'costs'))
    M.require(p['schema'] == 'closedwiz.factory-metrics.v1', 'wrong factory artifact')
    M.require(p['historical_completeness'] == 'unknown: edited/deleted records have no recoverable history in this read', 'unknown history semantics')
    for key in ('edited_fleet_comments', 'clock_skew_comments'):
        M.require(type(p[key]) is int and p[key] >= 0, 'invalid history count')
    stalls = M.array(p['stalls'])
    for stall in stalls:
        M.exact(stall, ('tickets', 'pull_request', 'kind', 'from', 'until', 'minutes', 'open_at_midnight'))
        tickets = M.array(stall['tickets'])
        M.require(len(set(tickets)) == len(tickets), 'duplicate stall ticket')
        for ticket in tickets:
            M.integer(ticket)
        if stall['pull_request'] is not None:
            M.integer(stall['pull_request'])
        M.require(stall['kind'] in ('findings sent', 'CI failure sent', 'merge blocked', 'review started'), 'unknown stall kind')
        M.require(M.timestamp(stall['from']) < M.timestamp(stall['until']), 'reversed stall')
        M.numeric(stall['minutes'])
        M.require(type(stall['open_at_midnight']) is bool, 'invalid stall state')
    M.require(p['biggest_stall'] == (stalls[0] if stalls else None), 'stall summary conflict')
    span = day_window(p['date'])
    M.require(type(p['merged_prs']) is int and p['merged_prs'] >= 0, 'invalid merge count')
    rows = M.array(p['hours'])
    M.require(len(rows) == 24, 'incomplete hourly inventory')
    for i, row in enumerate(rows):
        M.exact(row, ('hour', 'merged_prs', 'idle_minutes'))
        M.require(type(row['hour']) is int and row['hour'] == i, 'wrong hour')
        M.require(type(row['merged_prs']) is int and row['merged_prs'] >= 0, 'invalid hourly merge count')
        M.numeric(row['idle_minutes'])
    M.require(sum(r['merged_prs'] for r in rows) == p['merged_prs'], 'daily/hourly count conflict')
    M.require(p['merged_per_hour'] == round(p['merged_prs'] / 24, 6), 'wrong daily ratio')
    items = [metric(s, p['schema'], 'merged-day', 'throughput',
                    'Merged PRs, completed UTC day, all base branches, direction unclassified',
                    p['merged_prs'], 'count', span, statistic='count')]
    for row in rows:
        a = suite._time(span['since']) + timedelta(hours=row['hour'])
        part = window(a.strftime('%Y-%m-%dT%H:%M:%SZ'), (a + timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))
        items.append(metric(s, p['schema'], 'merged-hour-' + str(row['hour']), 'throughput',
                            'Merged PRs, completed UTC hour, all base branches, direction unclassified',
                            row['merged_prs'], 'count', part, statistic='count'))
    M.numeric(p['idle_minutes'])
    items.append(metric(s, p['schema'], 'recorded-idle', 'usage',
                        'Recorded idle agent-minutes; edited/deleted history incomplete',
                        p['idle_minutes'], 'minutes', span, state='partial',
                        prerequisites=['Surviving fleet records cannot establish complete historical idleness.']))
    costs = M.obj(p['costs'])
    M.exact(costs, ('claude', 'gpt', 'sandbox', 'actions', 'total_usd'))
    M.exact(costs['total_usd'], ('total', 'per_merged_pr'))
    for value in costs['total_usd'].values():
        if value is not None:
            M.numeric(value)
    for source, units in {'claude': ('tokens', 'credits', 'usd'),
                          'gpt': ('tokens', 'credits', 'usd'),
                          'sandbox': ('hours', 'usd'), 'actions': ('minutes', 'usd')}.items():
        amounts = M.obj(costs[source])
        M.exact(amounts, units + ('reason',) + (('threads',) if 'threads' in amounts and source in ('claude', 'gpt') else ()))
        M.require(type(amounts['reason']) is str, 'invalid usage reason')
        if 'threads' in amounts:
            for row in M.array(amounts['threads']):
                M.exact(row, ('thread',) + units)
                M.require(type(row['thread']) is str and row['thread'], 'invalid anonymous row')
                for unit in units:
                    if row[unit] is not None:
                        M.numeric(row[unit])
        for unit in units:
            amount = amounts[unit]
            M.exact(amount, ('total', 'per_merged_pr'))
            if amount['per_merged_pr'] is not None:
                M.numeric(amount['per_merged_pr'])
            value = amount['total']
            if value is not None:
                M.numeric(value)
                if unit == 'tokens':
                    M.require(float(value).is_integer(), 'fractional tokens')
                    value = int(value)
            gap = [] if value is not None else ['This provider/unit is unreported in the saved UTC-day report.']
            items.append(metric(s, p['schema'], source + '-' + unit, 'usage',
                                source.capitalize() + ' UTC-day usage, ' + unit + '; not attributed per-PR cost',
                                value, unit, span, state='partial' if gap else 'known', prerequisites=gap,
                                statistic='count' if unit == 'tokens' else 'total'))
    return provider('factory_metrics', items, ['Historical edited/deleted fleet records and merge direction are unavailable.'])


def journey(s, raw):
    J = native('tools/factory-metrics/journey.py')
    doc = J.M.load(raw.decode('utf-8'))
    J.validate(doc)
    bench = J.bench(doc)
    items = []
    for t in bench['tickets']:
        # Native ready/merge bounds, not an invented collection window.
        ticket = next(r for r in doc['tickets'] if r['ticket'] == t['ticket'])
        ready = next((e['at'] for e in ticket['events'] if e['kind'] == 'ready'), None)
        merges = [e['at'] for p in doc['pull_requests'] if p['number'] in ticket['pull_requests']
                  for e in p['events'] if e['kind'] == 'merge']
        end = min(merges) if merges else None
        if t['ready_to_merged_hours'] is not None and ready is not None and end is not None and ready < end:
            items.append(metric(s, doc['schema'], 'ready-to-merge-' + str(t['ticket']), 'stage_waits',
                                'Recorded ticket ready to first closing merge; historical coverage unknown',
                                t['ready_to_merged_hours'], 'hours', window(ready, end), state='partial',
                                prerequisites=['Journey historical completeness is unknown.'],
                                identities=['ticket-' + str(t['ticket'])], ticket=t['ticket']))
    return provider('journey', items, ['Selected validated journeys only; edited/deleted historical coverage remains unknown.'])


def skills_eval(s, raw):
    T = native('tools/ci-bench/trends.py')
    result = _pinned_file(raw, 'score.json', lambda path: T.cf4_results([path]))[0]
    # A score/manifest has no run-time window. Do not invent it from revision or
    # file timestamps; keep recorded result readiness separate from measurements.
    note = 'Validated recorded CF4 score (' + result['status'] + '); native result window and complete manifest/coverage binding required for numeric projection. No eval run by WR2.'
    item = metric(s, 'openwiz.skills-eval.score.v1', 'recorded-score-readiness', 'board',
                  note, None, 'count', None, state='partial', prerequisites=[note], statistic='count')
    return provider('skills_eval', [item], [note])


def point(s, schema, id, group, label, observed_at, *, ticket=None, evidence=None):
    suite.require(suite._time(observed_at) <= suite._time(s['observed_at']), 'point after selected observation')
    item = metric(s, schema, id, group, label, None, 'count', None, state='partial',
                  prerequisites=[POINT_PREREQUISITE], statistic='observation', ticket=ticket)
    item['observed_at'] = observed_at
    if evidence is not None:
        item['evidence'] = evidence
    return item


def board_graph(s, raw):
    B = native('private/orchestration/board/board.py')
    graph = suite._decode(raw.decode('utf-8'))
    # The existing --graph checker is finite and offline, not a GitHub read.
    report = B.render.check_links(graph)
    B.measures(graph, report)  # Reuse the source's definitions; never copy bodies/titles.
    suite._time(graph['read_at'])
    items = [point(s, graph['schema'], 'graph-readiness', 'board',
                   'Validated board graph; point counts remain Unknown', graph['read_at'])]
    for ticket in B.render.open_approved(graph):
        link = f'https://github.com/{graph["repo"]}/issues/{ticket["number"]}'
        items.append(point(s, graph['schema'], 'ticket-' + str(ticket['number']), 'board',
                           'Board ticket state: ' + B.render.state(ticket), graph['read_at'],
                           ticket=ticket['number'], evidence=[link]))
    return provider('board', items, [POINT_PREREQUISITE])


def board_history(s, raw):
    B = native('private/orchestration/board/board.py')
    rows = [B.strict(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    suite.require(bool(rows), 'empty board history')
    for i, row in enumerate(rows):
        suite._finite(row)
        # A selected run row/fragment uses the same native run-row validator;
        # complete legacy histories may also retain their original baseline.
        suite.require(B.valid_row(row, i == 0 and row.get('sample') == 'baseline'), 'invalid board history row')
    row = max(enumerate(rows), key=lambda pair: (pair[1]['at'], pair[0]))[1]
    items = [point(s, row['schema'], key, 'board', 'Board point: ' + key.replace('_', ' '), row['at'])
             for key in B.MEASURE_KEYS]
    return provider('board', items, [POINT_PREREQUISITE])


def decisions(s, raw):
    R = native('tools/skills-eval/records.py')
    doc = R.strict_json(raw.decode('utf-8'))
    schema = suite._decode((ROOT / 'contracts/decisions.v1.schema.json').read_text(encoding='utf-8'))
    suite.require(not R.schema_errors(doc, schema, schema) and doc['kind'] == 'response', 'invalid decisions response')
    stamp = doc['freshness']['snapshot_at'].get('known')
    if stamp is None or stamp % 1000:
        return provider('decisions', [], [POINT_PREREQUISITE,
                        'Oldest decisions source timestamp is unknown or not representable exactly in suite UTC seconds.'])
    observed_at = datetime.fromtimestamp(stamp // 1000, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    suite.require(stamp <= doc['snapshot_at'], 'decision source after response')
    seen, items = set(), []
    for item in doc['items']:
        subject = item['subject']
        identity = (subject['repository'].casefold(), subject['kind'], subject['number'], item['comment_id'])
        suite.require(identity not in seen, 'duplicate decision item')
        suite.require(item['created_at'] <= item['updated_at'] <= doc['snapshot_at'], 'decision after response')
        seen.add(identity)
        kind = 'issues' if subject['kind'] == 'issue' else 'pull'
        link = f'https://github.com/{subject["repository"]}/{kind}/{subject["number"]}#issuecomment-{item["comment_id"]}'
        id = 'decision-' + hashlib.sha256(link.encode()).hexdigest()
        current = item['current'].get('known')
        current_label = 'current' if current is True else 'changed' if current is False else 'currentness unknown'
        label = 'Pending ' + item['request']['kind'] + '; ' + current_label + '; read only'
        items.append(point(s, 'openwiz.decisions.v1', id, 'decisions', label, observed_at, evidence=[link]))
    if not items:
        items = [point(s, 'openwiz.decisions.v1', 'discovery-readiness', 'decisions',
                       'Selected decision discovery has empty items; coverage ' + doc['coverage']['state'], observed_at)]
    return provider('decisions', items, [POINT_PREREQUISITE,
                    'Selected discovery coverage: ' + doc['coverage']['state'] + '; source freshness: ' + doc['freshness']['state'] + '.'])


def credits(s, raw):
    B = native('private/orchestration/board/board.py')
    samples = B.read_credits(raw.decode('utf-8'))
    items = []
    for a, b in zip(samples, samples[1:]):
        span = window(a['at'], b['at'], 'PST-fixed-UTC-08:00')
        suite.require(b['at'] <= s['observed_at'], 'credit sample after observation')
        basis = 'extra-only' if 'only' in a or 'only' in b else 'full-balance'
        interval_key = '|'.join((a['at'], b['at'], basis))
        identity = hashlib.sha256(interval_key.encode('ascii')).hexdigest()
        items.append(metric(s, 'board.credits.jsonl', 'sampled-drop-' + identity, 'usage',
                            'Approximate sampled credit drop; rises count zero; extra-only seed spans stay extra-only',
                            B.spent(a, b), 'credits', span, state='partial',
                            prerequisites=['Sampled balance drops are approximate, not complete daily usage or a billing total.'],
                            identities=['credit-span-' + identity]))
    return provider('credits', items, ['Consecutive sampled balance spans only; no daily billing endpoint is assumed.'])


def claude_usage(s, raw):
    M = native('tools/factory-metrics/metrics.py')
    data = _pinned_file(raw, 'usage.json', lambda path: M.read_usage(path))
    span = day_window(data['date'])
    items = []
    for unit in ('tokens', 'credits', 'usd'):
        rows = data['claude']
        known = all(r[unit] is not None for r in rows)
        value = sum(r[unit] for r in rows) if known else None
        items.append(metric(s, 'factory.daily-usage-export', 'claude-' + unit, 'usage',
                            'Claude owner-supplied complete UTC-day export, ' + unit,
                            value, unit, span, state='known' if known else 'partial',
                            prerequisites=[] if known else ['This unit is unreported on one or more usage rows.'],
                            identities=['claude-row-' + str(i) for i in range(1, len(rows) + 1)],
                            statistic='count' if unit == 'tokens' else 'total'))
    return provider('claude_usage', items, [] if all(m['state'] == 'known' for m in items)
                    else ['Unreported provider units stay Unknown; units are never converted.'])


def _failed(slot, previous, at):
    reason = 'Selected source unavailable, malformed or hash/time binding refused; restore the pinned validated artifact. Last good source evidence is retained without a new observation.'
    old = next((p for p in (previous or {}).get('providers', []) if p['slot'] == slot), None)
    if old and any(m['state'] != 'unavailable' for m in old['metrics']):
        p = copy.deepcopy(old)
        p['state'] = 'partial'
        p['prerequisites'] = list(dict.fromkeys(p['prerequisites'] + [reason]))
        for m in p['metrics']:
            if m['state'] != 'unavailable':
                m['state'] = 'partial'
                m['sample']['expected'] = None
                m['prerequisites'] = list(dict.fromkeys(m['prerequisites'] + [reason]))
            m['freshness'] = 'unknown' if m['fresh_until'] is None else 'stale' if at > m['fresh_until'] else 'fresh'
        return p
    return provider(slot, [], [reason])


def select(root, selections, at, previous=None):
    """Finite per-source failures are explicit; unknown selection config refuses.

    Metadata pins local bytes, actual observation time and source links; it is
    an operator selection/binding, not a new native artifact or collector.
    """
    suite._time(at)
    suite.require(type(selections) is list, 'source selection must be an array')
    seen = set()
    for s in selections:
        suite.require(type(s) is dict and set(s) == REQUIRED, 'invalid selection fields')
        suite.require(type(s['kind']) is str and type(s['slot']) is str and
                      s['kind'] in KINDS and s['slot'] in {p['slot'] for p in suite.PROVIDERS}, 'unsupported source')
        suite.require(s['slot'] not in seen, 'duplicate selected slot')
        suite.require(s['kind'] == 'projected' or SLOTS[s['kind']] == s['slot'], 'source slot mismatch')
        suite.require(type(s['path']) is str and re.fullmatch(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*', s['path'])
                      and not any(x in ('.', '..') for x in s['path'].split('/')), 'invalid source path')
        suite.require(type(s['sha256']) is str and re.fullmatch('[0-9a-f]{64}', s['sha256']), 'invalid source hash')
        suite.require(type(s['evidence']) is list and s['evidence'] and all(type(url) is str and LINK.fullmatch(url) for url in s['evidence']), 'invalid source links')
        suite._time(s['observed_at'])
        seen.add(s['slot'])
    results = []
    for s in selections:
        try:
            suite.require(s['observed_at'] <= at, 'source observation after tick')
            base = Path(root).resolve()
            path = (base / s['path']).resolve()
            suite.require(path.is_relative_to(base), 'source escapes selection root')
            raw = path.read_bytes()
            suite.require(hashlib.sha256(raw).hexdigest() == s['sha256'], 'artifact hash mismatch')
            if s['kind'] == 'projected':
                p = suite._decode(raw.decode('utf-8'))
                suite.require(p['slot'] == s['slot'], 'projected slot mismatch')
                for m in p['metrics']:
                    suite.require(m['observed_at'] is None or m['observed_at'] <= s['observed_at'], 'projected observation after read')
                    m['freshness'] = 'unknown' if m['fresh_until'] is None else 'stale' if at > m['fresh_until'] else 'fresh'
            else:
                p = globals()[s['kind']](s, raw)
            sample = suite._time(at).replace(minute=suite._time(at).minute // 5 * 5, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')
            safe_record(suite.compose(sample, [p], assembled_at=at))
            results.append(p)
        except (OSError, ValueError, UnicodeError, KeyError, TypeError, RecursionError):
            results.append(_failed(s['slot'], previous, at))
        except Exception as error:
            # Native readers have their own Fail/ReadError types. Never retain
            # their text, source paths, comments or credentials in error output.
            if type(error).__name__ not in ('Fail', 'ReadError'):
                raise
            results.append(_failed(s['slot'], previous, at))
    for old in (previous or {}).get('providers', []):
        if old['slot'] not in seen and old['metrics']:
            results.append(_failed(old['slot'], previous, at))
    return results
