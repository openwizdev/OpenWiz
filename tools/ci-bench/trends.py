#!/usr/bin/env python3
"""EB2: shared journeys to sanitized daily aggregates; no second review parser."""
import argparse
from collections import Counter
from datetime import timedelta
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('journey_for_bench', HERE.parent/'factory-metrics/journey.py')
J = importlib.util.module_from_spec(spec)
spec.loader.exec_module(J)
SCHEMA = 'closedwiz.journey.trends.v1'


def load(path):
    return J.M.load(Path(path).read_text())


def event(pr, kind):
    return next((e['at'] for e in pr['events'] if e['kind'] == kind), None)


def cohort(prs):
    rounds = [[e for e in p['events'] if J.rounds_of(e)] for p in prs]
    reviewed = [r for r in rounds if r]
    first = sum(r[0]['verdict'] == 'APPROVE' for r in reviewed)
    total = sum(map(len, reviewed))
    return {'prs': len(prs), 'reviewed': len(reviewed), 'unreviewed': len(prs)-len(reviewed),
            'first_approve': first, 'rounds': total,
            'approval_share': round(first/len(reviewed), 6) if reviewed else None,
            'rounds_per_pr': round(total/len(reviewed), 6) if reviewed else None}


def cf4_results(paths):
    """Read recorded CF4 scores only; never run or claim a paid eval."""
    results = []
    for path in paths:
        raw = Path(path).read_text()
        s = J.M.load(raw)
        keys = ('schema', 'settings_hash', 'cases_hash', 'revision', 'code_hash', 'schema_hash',
                'suite_pass', 'runs', 'passed', 'cost_usd', 'rows')
        J.M.exact(s, keys)
        J.require(s['schema'] == 'openwiz.skills-eval.score.v1', 'not a CF4 score')
        for k in ('settings_hash', 'cases_hash', 'code_hash', 'schema_hash'):
            J.require(type(s[k]) is str and J.re.fullmatch('[0-9a-f]{64}', s[k]), 'invalid CF4 hash')
        J.M.exact(s['revision'], ('commit', 'tree'))
        for v in s['revision'].values(): J.commit(v)
        J.require(type(s['suite_pass']) is bool, 'invalid CF4 outcome')
        J.count(s['runs'], 0); J.count(s['passed'], 0)
        J.require(s['passed'] <= s['runs'] and s['runs'] == len(J.array(s['rows'])), 'invalid CF4 counts')
        identities, repetitions = set(), {}
        for r in s['rows']:
            J.obj(r)
            required = ('case', 'repeat', 'pass', 'reasons', 'details')
            incomplete = set(r) == set(required)
            J.M.exact(r, required if incomplete else required + ('cost_usd', 'stop'))
            J.require(type(r['case']) is str and J.re.fullmatch('[a-z0-9][a-z0-9-]*', r['case']), 'invalid CF4 case')
            J.count(r['repeat'])
            key = (r['case'], r['repeat'])
            J.require(key not in identities, 'duplicate CF4 case/repeat')
            identities.add(key)
            repetitions.setdefault(r['case'], set()).add(r['repeat'])
            J.require(type(r['pass']) is bool, 'invalid CF4 row outcome')
            for k in ('reasons', 'details'):
                J.require(all(type(v) is str for v in J.array(r[k])), 'invalid CF4 reason/details')
            J.require(r['pass'] == (r['reasons'] == []), 'CF4 reasons disagree with outcome')
            if incomplete:
                J.require(not r['pass'] and r['reasons'] == ['incomplete'], 'invalid incomplete CF4 row')
            else:
                J.require(r['stop'] is None or type(r['stop']) is str, 'invalid CF4 stop')
                if r['cost_usd'] is not None: J.amount(r['cost_usd'])
                J.require(not r['pass'] or r['stop'] == 'end_turn', 'passing CF4 row did not finish')
        repeat_sets = list(repetitions.values())
        J.require(not repeat_sets or all(len(v) == len(repeat_sets[0]) and
                                        sorted(v) == list(range(1, len(v)+1)) for v in repeat_sets),
                  'CF4 cases have missing or inconsistent repeats')
        J.amount(s['cost_usd'])
        unfinished = any(r.get('stop') != 'end_turn' or 'incomplete' in r['reasons'] for r in s['rows'])
        J.require(sum(r.get('pass', False) for r in s['rows']) == s['passed'], 'CF4 pass count differs')
        J.require(s['suite_pass'] == bool(s['runs'] and s['passed'] == s['runs']), 'CF4 suite outcome disagrees')
        if s['suite_pass']:
            J.require(s['runs'] > 0 and s['passed'] == s['runs'] and not unfinished, 'inconsistent CF4 pass')
        results.append({'cf4': {k: s[k] for k in ('settings_hash', 'cases_hash', 'code_hash')} |
                        {'revision': s['revision']['commit']},
                        'schema_hash': s['schema_hash'], 'result_hash': hashlib.sha256(raw.encode()).hexdigest(),
                        'status': 'unfinished' if unfinished or not s['runs'] else 'passing' if s['suite_pass'] else 'failed'})
    return results


def histogram_summary(histogram, unknown=0):
    histogram = sorted(histogram.items())
    n = sum(count for _,count in histogram)
    mean = math.fsum(value*count for value,count in histogram)/n if n else None
    def rank(k):
        seen=0
        for value,count in histogram:
            seen+=count
            if seen>=k: return value
    median = ((rank((n+1)//2)+rank(n//2+1))/2) if n else None
    variance = math.fsum(count*(value-mean)**2 for value,count in histogram)/(n-1) if n>1 else None
    return {'n':n,'unknown':unknown,'mean':round(mean,6) if mean is not None else None,
            'median':round(median,6) if median is not None else None,
            'p90':round(rank(math.ceil(.9*n)),6) if n else None,
            'sample_sd':round(math.sqrt(variance),6) if variance is not None else None,
            'histogram':[{'value':v,'count':count} for v,count in histogram]}


def distribution(values, unknown=0):
    """Exact aggregate histogram; pooled quantiles never average daily medians."""
    return histogram_summary(Counter(values), unknown)


def outcome_cohort(doc, export, prs):
    rows = {r['pr']:r for r in J.outcome_rows(doc, export)}
    samples, starts, rounds = [], [], []
    g = dict.fromkeys(('mature','unmatured','unknown_followup','unknown_attribution',
                       'known_mature_prs','affected_mature_prs','attributable_events','unattributed_events'),0)
    for p in prs:
        r = rows[p['number']]
        if r['first_push_to_merged_hours'] is not None: samples.append(r['first_push_to_merged_hours'])
        if r['independent_rounds'] is not None: rounds.append(r['independent_rounds'])
        if r['builder_start_to_merged_hours'] is not None: starts.append(r['builder_start_to_merged_hours'])
        status = r['defect_followup']
        g['unknown_followup' if status == 'unknown' else status] += 1
        unknown = r['defects']['unknown'] > 0
        g['unknown_attribution'] += unknown
        g['attributable_events'] += r['defects']['attributable']
        g['unattributed_events'] += r['defects']['unattributed']
        if status == 'mature' and not unknown:
            g['known_mature_prs'] += 1
            g['affected_mature_prs'] += r['defects']['attributable'] > 0
    g['rate'] = round(g['affected_mature_prs']/g['known_mature_prs'],6) if g['known_mature_prs'] else None
    return {'prs':len(prs), 'first_push_to_merged_hours':distribution(samples,len(prs)-len(samples)),
            'builder_start_to_merged_hours':distribution(starts,len(prs)-len(starts)),
            'independent_rounds':distribution(rounds,len(prs)-len(rounds)), 'defects':g}


def outcome_report(doc, export, merged, experiment=None):
    J.validate_outcome_export(export, doc)
    all_prs = doc['pull_requests']
    result = {name:outcome_cohort(doc, export, prs) for name,prs in (
        ('all',all_prs), ('merged',merged), ('open',[p for p in all_prs if p['state']=='open']),
        ('closed',[p for p in all_prs if p['state']=='closed']))}
    result['tickets'] = {'total':len(doc['tickets']), **{s:sum(t['state']==s for t in doc['tickets'])
                          for s in ('merged','open','closed')},
                         'without_pr':sum(not t['pull_requests'] for t in doc['tickets'])}
    result['defect_policy'] = export['defect_policy']
    result['assigned'] = None
    if experiment is not None:
        E = J.outcome_contract()
        try: E.validate(json.loads(json.dumps(experiment,default=float)), json.loads(json.dumps(doc,default=float)))
        except ValueError as e: raise J.ReadError(str(e))
        J.require(experiment['journey'] == export['journey'] and
                  all(experiment['sources'].get(k)==v for k,v in export['sources'].items()) and
                  experiment['experiment']['defect_policy']==export['defect_policy'],
                  'experiment/outcome source or policy mismatch')
        result['assigned'] = {}
        for arm in ('old','candidate'):
            assigned = {a['ticket'] for a in experiment['assignments'] if a['arm']==arm}
            ts = [t for t in doc['tickets'] if t['ticket'] in assigned]
            ps = [p for p in all_prs if any(n in assigned for n in p['tickets'])]
            result['assigned'][arm] = {'tickets':len(ts), **{s:sum(t['state']==s for t in ts)
                                      for s in ('merged','open','closed')},
                                      'without_pr':sum(not t['pull_requests'] for t in ts),
                                      'outcomes':outcome_cohort(doc, export, ps)}
    return result


def validate_outcome_cohort(c):
    J.M.exact(c, ('prs','first_push_to_merged_hours','builder_start_to_merged_hours','independent_rounds','defects'))
    J.count(c['prs'],0)
    for key in ('first_push_to_merged_hours','builder_start_to_merged_hours','independent_rounds'):
        d = c[key]
        J.M.exact(d, ('n','unknown','mean','median','p90','sample_sd','histogram'))
        J.count(d['n'],0); J.count(d['unknown'],0)
        J.require(d['n']+d['unknown']==c['prs'], 'timing/round denominator differs')
        histogram={}; last=None
        for row in J.array(d['histogram']):
            J.M.exact(row, ('value','count')); J.amount(row['value']); J.count(row['count'])
            J.require(last is None or row['value']>last, 'unordered/repeated histogram value')
            last=row['value']
            histogram[float(row['value'])]=row['count']
        expected=histogram_summary(histogram,d['unknown'])
        J.require(json.loads(json.dumps(d,default=float))==expected, 'outcome statistics disagree with histogram')
    g=c['defects']
    J.M.exact(g, ('mature','unmatured','unknown_followup','unknown_attribution','known_mature_prs',
                  'affected_mature_prs','attributable_events','unattributed_events','rate'))
    for k in g:
        if k!='rate': J.count(g[k],0)
    J.require(g['mature']+g['unmatured']+g['unknown_followup']==c['prs'] and
              g['known_mature_prs']+g['unknown_attribution']<=c['prs'] and
              g['known_mature_prs']<=g['mature'] and
              g['affected_mature_prs']<=g['known_mature_prs'] and
              g['affected_mature_prs']<=g['attributable_events'], 'invalid defect denominators')
    J.require(g['rate']==(round(g['affected_mature_prs']/g['known_mature_prs'],6) if g['known_mature_prs'] else None),
              'defect rate differs from mature known denominator')


def validate_outcome_report(o):
    J.M.exact(o, ('all','merged','open','closed','tickets','defect_policy','assigned'))
    for key in ('all','merged','open','closed'): validate_outcome_cohort(o[key])
    J.require(o['merged']['prs']+o['open']['prs']+o['closed']['prs']<=o['all']['prs'],
              'outcome cohorts exceed collected PRs')
    t=o['tickets']; J.M.exact(t, ('total','merged','open','closed','without_pr'))
    for v in t.values(): J.count(v,0)
    J.require(t['total']==t['merged']+t['open']+t['closed'] and t['without_pr']<=t['total'], 'invalid ticket coverage')
    policy=o['defect_policy']
    if policy is not None:
        J.M.exact(policy, ('rule','followup_hours','deduplication','unknown_attribution'))
        J.require(policy['rule']=='explicit-causal-fix-link-v1' and policy['deduplication']=='root-cause-per-merge' and
                  policy['unknown_attribution']=='retain-unknown', 'unknown defect policy')
        J.amount(policy['followup_hours']); J.require(policy['followup_hours']>0, 'invalid follow-up')
    else:
        J.require(all(o[k]['defects']['unknown_followup']==o[k]['prs'] and
                      o[k]['defects']['attributable_events']==o[k]['defects']['unattributed_events']==0 and
                      o[k]['defects']['unknown_attribution']==0 for k in ('all','merged','open','closed')),
                  'defect comparison needs a policy')
    if o['assigned'] is not None:
        J.M.exact(o['assigned'], ('old','candidate'))
        for arm in o['assigned'].values():
            J.M.exact(arm, ('tickets','merged','open','closed','without_pr','outcomes'))
            for k in ('tickets','merged','open','closed','without_pr'): J.count(arm[k],0)
            J.require(arm['tickets']==arm['merged']+arm['open']+arm['closed'] and
                      arm['without_pr']<=arm['tickets'], 'invalid assignment coverage')
            validate_outcome_cohort(arm['outcomes'])


def report(doc, since, until, scores=(), merged_prs=None, outcomes=None, experiment=None):
    J.validate(doc)
    a, b = J.M.timestamp(since), J.M.timestamp(until)
    J.require(a < b, 'until must be after since')
    def inside(t): return t is not None and a <= J.M.timestamp(t) < b
    merged = [p for p in doc['pull_requests'] if inside(event(p, 'merge')) and
              (merged_prs is None or p['number'] in merged_prs)]
    # A document records current PR state, not a historical open/closed timeline.
    opened = [p for p in doc['pull_requests'] if p['state'] == 'open']
    selected = {p['number']: p for p in merged + opened}
    reviewed = [p for p in selected.values() if any(J.rounds_of(e) for e in p['events'])]
    tickets = {t['ticket']: t for t in doc['tickets']}
    first_by_ticket = {}
    for candidate in doc['pull_requests']:
        at = event(candidate, 'merge')
        if at is None: continue
        key = (at, candidate['number'])
        for n in candidate['tickets']:
            if n not in first_by_ticket or key < first_by_ticket[n]:
                first_by_ticket[n] = key
    owners, latency, missing = {}, [], 0
    for p in sorted(merged, key=lambda p: (event(p, 'merge'), p['number'])):
        for n in p['tickets']:
            owners.setdefault(n, p)
    for n, p in owners.items():
        # Only the first closing merge in the whole document owns a ticket.
        if first_by_ticket[n][1] != p['number']: continue
        ready = event(tickets[n], 'ready') if n in tickets else None
        if ready is None or ready > event(p, 'merge'): missing += 1
        else: latency.append((J.M.timestamp(event(p, 'merge')) - J.M.timestamp(ready)).total_seconds()/3600)
    findings = {k: 0 for k in J.KINDS}
    for p in selected.values():
        for f in p['findings']: findings[f['kind']] += 1
    credits = {}
    for provider in ('claude', 'gpt'):
        known, unknown, total = 0, 0, 0
        for n in owners:
            if n not in tickets:
                unknown += 1
                continue
            t = tickets[n]
            u = next(u for u in t['usage'] if (u['provider'], u['unit']) == (provider, 'credits'))
            # A ticket's credits cannot be allocated between its several PRs.
            sole = len(t['pull_requests']) == 1
            if u['status'] == 'known' and sole:
                known += 1; total += u['value']
                if u['missing_days']: unknown += 1
            else: unknown += 1
        credits[provider] = {'known_ticket_lower_bound': J.number(total) if known else None,
                             'known_tickets': known, 'unknown_tickets': unknown,
                             'per_merged_pr': J.number(total/len(merged)) if merged and not unknown and
                             len(owners) > 0 and all(p['tickets'] and all(n in tickets for n in p['tickets'])
                                                     for p in merged) else None}
    experiments = []
    for p in selected.values():
        if p['experiment'] is None: continue
        e = p['experiment']
        matching = [s for s in scores if s['cf4'] == e['cf4']]
        J.require(len(matching) <= 1, 'ambiguous CF4 scores')
        s = matching[0] if matching else {}
        baselines = [s for s in scores if s['cf4']['revision'] == p['revisions']['base']]
        experiments.append({'tag': e['tag'], 'revisions': p['revisions'], 'merged_at': event(p, 'merge'),
                            'cf4': e['cf4'], 'cf4_status': s.get('status', 'not recorded'),
                            'result_hash': s.get('result_hash'), 'schema_hash': s.get('schema_hash'),
                            'baselines': baselines})
    daily = []
    for d in doc['daily_usage']:
        if d['date'] is not None and a.date().isoformat() <= d['date'] <= (b-timedelta(seconds=1)).date().isoformat():
            daily.append({'date': d['date'], 'merged_prs': d['merged_prs'],
                          'credits': {p: d['totals'][p]['credits'] for p in ('claude', 'gpt')}})
    events = [e for p in selected.values() for e in p['events']]
    result = {'schema': SCHEMA, 'since': since, 'until': until,
            'cohorts': {'merged': cohort(merged), 'reviewed': cohort(reviewed), 'open': cohort(opened)},
            'ready_to_merged_hours': {'tickets': len(latency), 'unknown': missing,
                                     'median': round(statistics.median(latency), 6) if latency else None,
                                     'p90': round(sorted(latency)[math.ceil(.9*len(latency))-1], 6) if latency else None},
            'findings': findings, 'attributed_credits': credits, 'daily_usage_ratios': daily,
            'experiments': experiments,
            'coverage': {'history': 'unknown', 'open_basis': 'current linked open PR snapshot; never a historical census',
                         'selected_prs': len(selected), 'merged_prs': len(merged),
                         'unlinked_open_tickets': sum(t['state'] == 'open' and not t['pull_requests'] for t in tickets.values()),
                         'edited_events': sum(e['completeness'] == 'edited' for e in events),
                         'unknown_events': sum(e['completeness'] == 'unknown' for e in events),
                         'duplicates_dropped': doc['duplicates']}}
    if outcomes is not None:
        result['outcomes'] = outcome_report(doc, outcomes, merged, experiment)
    return result


def validate(r):
    """Strict allowlist at the publication boundary; no raw journey fields."""
    J.M.exact(r, ('schema', 'since', 'until', 'cohorts', 'ready_to_merged_hours', 'findings',
                  'attributed_credits', 'daily_usage_ratios', 'experiments', 'coverage') +
                  (('outcomes',) if 'outcomes' in r else ()))
    if 'outcomes' in r:
        validate_outcome_report(r['outcomes'])
        J.require(r['outcomes']['merged']['prs']==r['cohorts']['merged']['prs'],
                  'outcome/legacy merged cohorts differ')
    J.require(r['schema'] == SCHEMA, 'unknown trend schema')
    J.require(J.M.timestamp(r['since']) < J.M.timestamp(r['until']), 'invalid trend window')
    def counts(d, keys):
        J.M.exact(d, keys)
        for v in d.values(): J.count(v, 0)
    def num(v):
        if v is not None: J.amount(v)
    J.M.exact(r['cohorts'], ('merged', 'reviewed', 'open'))
    for c in r['cohorts'].values():
        J.M.exact(c, ('prs', 'reviewed', 'unreviewed', 'first_approve', 'rounds', 'approval_share', 'rounds_per_pr'))
        for k in ('prs', 'reviewed', 'unreviewed', 'first_approve', 'rounds'): J.count(c[k], 0)
        J.require(c['prs'] == c['reviewed'] + c['unreviewed'] and c['first_approve'] <= c['reviewed'], 'invalid cohort counts')
        for k in ('approval_share', 'rounds_per_pr'): num(c[k])
        J.require(c['approval_share'] == (round(c['first_approve']/c['reviewed'], 6) if c['reviewed'] else None) and
                  c['rounds_per_pr'] == (round(c['rounds']/c['reviewed'], 6) if c['reviewed'] else None), 'invalid cohort ratios')
    t = r['ready_to_merged_hours']; J.M.exact(t, ('tickets', 'unknown', 'median', 'p90'))
    J.count(t['tickets'], 0); J.count(t['unknown'], 0); num(t['median']); num(t['p90'])
    counts(r['findings'], J.KINDS)
    J.M.exact(r['attributed_credits'], ('claude', 'gpt'))
    for c in r['attributed_credits'].values():
        J.M.exact(c, ('known_ticket_lower_bound', 'known_tickets', 'unknown_tickets', 'per_merged_pr'))
        J.count(c['known_tickets'], 0); J.count(c['unknown_tickets'], 0)
        num(c['known_ticket_lower_bound']); num(c['per_merged_pr'])
    for d in J.array(r['daily_usage_ratios']):
        J.M.exact(d, ('date', 'merged_prs', 'credits')); J.day(d['date']); J.count(d['merged_prs'], 0)
        J.M.exact(d['credits'], ('claude', 'gpt'))
        for u in d['credits'].values():
            J.M.exact(u, ('total', 'per_merged_pr')); num(u['total']); num(u['per_merged_pr'])
    for e in J.array(r['experiments']):
        J.M.exact(e, ('tag', 'revisions', 'merged_at', 'cf4', 'cf4_status', 'result_hash', 'schema_hash', 'baselines'))
        J.require(type(e['tag']) is str and J.TAG.fullmatch('Experiment: '+e['tag']), 'invalid experiment tag')
        J.M.exact(e['revisions'], ('base', 'head', 'merge'))
        for v in e['revisions'].values(): J.maybe_commit(v)
        J.when(e['merged_at'], null=True)
        if e['cf4'] is not None:
            J.M.exact(e['cf4'], ('settings_hash', 'cases_hash', 'code_hash', 'revision'))
            J.commit(e['cf4']['revision'])
            for k in ('settings_hash', 'cases_hash', 'code_hash'):
                J.require(type(e['cf4'][k]) is str and J.re.fullmatch('[0-9a-f]{64}', e['cf4'][k]), 'invalid CF4 hash')
        J.require(e['cf4_status'] in ('not recorded', 'passing', 'failed', 'unfinished'), 'invalid CF4 state')
        for k in ('result_hash', 'schema_hash'):
            J.require(e[k] is None or (type(e[k]) is str and J.re.fullmatch('[0-9a-f]{64}', e[k])), 'invalid result hash')
        J.require((e['cf4_status'] == 'not recorded') == (e['result_hash'] is None), 'CF4 state needs evidence')
        J.require(e['cf4_status'] == 'not recorded' or (e['cf4'] is not None and e['schema_hash'] is not None), 'CF4 outcome needs hashes')
        for s in J.array(e['baselines']):
            J.M.exact(s, ('cf4', 'schema_hash', 'result_hash', 'status'))
            J.M.exact(s['cf4'], ('settings_hash', 'cases_hash', 'code_hash', 'revision'))
            J.require(s['cf4']['revision'] == e['revisions']['base'], 'baseline must name base revision')
            J.commit(s['cf4']['revision'])
            for v in [s['schema_hash'], s['result_hash']] + [s['cf4'][k] for k in ('settings_hash', 'cases_hash', 'code_hash')]:
                J.require(type(v) is str and J.re.fullmatch('[0-9a-f]{64}', v), 'invalid baseline hash')
            J.require(s['status'] in ('passing', 'failed', 'unfinished'), 'invalid baseline outcome')
    c = r['coverage']
    J.M.exact(c, ('history', 'open_basis', 'selected_prs', 'merged_prs', 'unlinked_open_tickets',
                  'edited_events', 'unknown_events', 'duplicates_dropped'))
    J.require(c['history'] == 'unknown' and c['open_basis'] == 'current linked open PR snapshot; never a historical census', 'invalid coverage')
    for k in ('selected_prs', 'merged_prs', 'unlinked_open_tickets', 'edited_events', 'unknown_events', 'duplicates_dropped'):
        J.count(c[k], 0)


def collect(repo, directory, usage, policy=None, previous=None):
    """Use EB1's collector and inventory. The day chooses tickets, EB1 parses."""
    directory = Path(directory)
    f = J.obj(load(directory/'factory.json'))
    since, until = J.when(J.field(f, 'since')), J.when(J.field(f, 'until'))
    spec = importlib.util.spec_from_file_location('bench_factory_reader', HERE/'bench.py')
    B = importlib.util.module_from_spec(spec); spec.loader.exec_module(B)
    try: f = B.read_factory(directory, since, until)
    except B.Fail as e: raise J.ReadError(str(e))
    inventory = J.M.collect_prs(repo)
    wanted = set()
    for p in f['prs']:
        J.require(p['number'] in inventory, 'factory PR absent from complete inventory')
        wanted.update(inventory[p['number']]['tickets'])
    wanted.update(t for p in inventory.values() if p['merged'] is None and p['closed'] is None for t in p['tickets'])
    if previous is not None:
        wanted.update(t['ticket'] for t in previous[0]['tickets'])
    outcomes = {}
    doc = J.collect(repo, sorted(wanted), usage, outcomes, policy, previous)
    J.validate(doc)
    by_number = {p['number']: p for p in doc['pull_requests']}
    for p in f['prs']:
        if p['tickets']:
            J.require(p['number'] in by_number and event(by_number[p['number']], 'merge') == p['merged_at'],
                      'journeys and factory merged PRs differ')
    output = report(doc, since, until, merged_prs={p['number'] for p in f['prs']}, outcomes=outcomes)
    validate(output)
    # Commit no intermediate report on failure. Raw sanitized facts remain local.
    (directory/'outcomes.json').write_text(json.dumps(outcomes, indent=2, default=float)+'\n')
    (directory/'journeys.json').write_text(json.dumps(doc, indent=2, default=float)+'\n')
    (directory/'journey-report.json').write_text(json.dumps(output, indent=2, default=float)+'\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect'); c.add_argument('--repo', type=J.M.repo_arg)
    c.add_argument('directory', type=Path); c.add_argument('--usage', action='append', default=[], type=Path)
    r = sub.add_parser('report'); r.add_argument('file', type=Path)
    r.add_argument('--since', required=True); r.add_argument('--until', required=True); r.add_argument('--out', type=Path, required=True)
    r.add_argument('--cf4-score', action='append', default=[], type=Path)
    r.add_argument('--outcomes', type=Path); r.add_argument('--experiment', type=Path)
    c.add_argument('--defect-policy', type=Path); c.add_argument('--previous', type=Path)
    args = p.parse_args()
    try:
        if args.command == 'collect':
            repo = args.repo
            if repo is None:
                info = J.M.gh('repo', 'view', '--json', 'nameWithOwner')
                J.M.exact(info, ('nameWithOwner',))
                repo = J.M.repo_arg(info['nameWithOwner'])
            policy = load(args.defect_policy) if args.defect_policy else None
            previous = ((load(args.previous/'journeys.json'),load(args.previous/'outcomes.json')) if args.previous else None)
            collect(repo, args.directory, args.usage, policy, previous)
        else:
            J.require(not args.experiment or args.outcomes, 'experiment reporting needs outcomes')
            result = report(load(args.file), args.since, args.until, cf4_results(args.cf4_score),
                            outcomes=load(args.outcomes) if args.outcomes else None,
                            experiment=load(args.experiment) if args.experiment else None)
            validate(result)
            args.out.write_text(json.dumps(result, indent=2, default=float)+'\n')
    except (J.ReadError, OSError, ValueError) as e:
        print(f'trends: {e}', file=sys.stderr); return 1
    return 0



# Dashboard consumer. Kept callable for EB4's weekly report; takes aggregate points.
def period(points, start, end):
    rows = [p for p in points if start <= p['since'] and p['until'] <= end and 'journey' in p]
    counts = {k: sum(p['journey']['cohorts']['merged'][k] for p in rows)
              for k in ('prs', 'reviewed', 'unreviewed', 'first_approve', 'rounds')}
    n = counts['reviewed']
    result = {'since': start, 'until': end, 'days': len(rows), 'expected_days': 7, **counts,
              'approval_share': round(counts['first_approve']/n, 6) if n else None,
              'rounds_per_pr': round(counts['rounds']/n, 6) if n else None}
    measured = [p['journey']['outcomes']['merged'] for p in rows if 'outcomes' in p['journey']]
    if measured:
        policies = [p['journey']['outcomes']['defect_policy'] for p in rows if 'outcomes' in p['journey']]
        pooled = {'prs':sum(c['prs'] for c in measured)}
        for key in ('first_push_to_merged_hours','builder_start_to_merged_hours','independent_rounds'):
            histogram=Counter()
            for c in measured:
                histogram.update({float(h['value']):h['count'] for h in c[key]['histogram']})
            pooled[key]=histogram_summary(histogram,sum(c[key]['unknown'] for c in measured))
        g={k:sum(c['defects'][k] for c in measured) for k in measured[0]['defects'] if k!='rate'}
        g['rate']=(round(g['affected_mature_prs']/g['known_mature_prs'],6) if g['known_mature_prs'] else None)
        # Different windows/policies cannot form a comparable defect rate.
        if any(p != policies[0] for p in policies): g['rate']=None
        pooled['defects']=g
        result['outcomes']={'merged':pooled,'days':len(measured),'policy_compatible':all(p==policies[0] for p in policies)}
    return result


def comparisons(points, at):
    end = J.M.timestamp(at)
    return [period(points, J.M.iso(end-timedelta(days=14)), J.M.iso(end-timedelta(days=7))),
            period(points, J.M.iso(end-timedelta(days=7)), J.M.iso(end))]


def write_dashboard(B, points, out, windows=None):
    windows = points if windows is None else windows
    def cell(value): return B.md_cell(B.esc(value))
    def show(value): return 'unknown' if value is None else f'{value:g}'
    def cohort_cells(c):
        return (f"{c['first_approve']}/{c['reviewed']} ({show(c['approval_share'])}) | "
                f"{show(c['rounds_per_pr'])} (rounds={c['rounds']}, n={c['reviewed']}) | "
                f"{c['unreviewed']}")
    def row(label, c):
        return (f"| {label} | {c['since']} – {c['until']} | {c['days']}/7 | {c['prs']} | "
                f"{cohort_cells(c)} |")
    header = ['| Period | UTC bounds, fixed PST days | Coverage days | Merged PRs | First approvals/reviewed (share) | Rounds/reviewed PR | Unreviewed |',
              '| --- | --- | ---: | ---: | --- | --- | ---: |']
    def outcome_lines(label, o):
        c=o['merged']
        cells=[cell(label),str(c['prs'])]
        for key in ('first_push_to_merged_hours','builder_start_to_merged_hours','independent_rounds'):
            d=c[key]
            cells.append(f"{show(d['mean'])}; {show(d['median'])}; {show(d['sample_sd'])}; {d['n']}/{c['prs']}; unknown {d['unknown']}")
        g=c['defects']
        cells += [f"{g['affected_mature_prs']}/{g['known_mature_prs']} ({show(g['rate'])})",
                  f"{g['mature']}; {g['unmatured']}; {g['unknown_followup']}; {g['unknown_attribution']}"]
        return '| '+' | '.join(cells)+' |'
    outcome_header=['| Window | Merged PRs | First push → verified merge hours: mean; median; SD; n/PRs; unknown | Builder start → merge hours: mean; median; SD; n/PRs; unknown | Independent rounds: mean; median; SD; n/PRs; unknown | Defects: affected/known mature PRs (rate) | Follow-up mature; immature; unknown; unknown attribution PRs |',
                    '| --- | ---: | --- | --- | --- | --- | --- |']
    md = ['# Journey trends and experiments', '',
          'Shared EB1 journeys; aggregate observations, not causation. Historical completeness is unknown. '
          'The original four factory benches remain alongside these stricter independent-review cohorts.', '',
          '**Dated context — grill snapshot, 2026-11-06:** 65/89 reviewed (73%); '
          '64/75 merged since Nov 3 (85%); 1/14 open. Average 1.3 rounds, worst 5. '
          'This is context, not a recomputed baseline or evidence of improvement.', '',
          '![Journey reviews](journey-reviews.svg)', '', '![Journey findings](journey-findings.svg)', '',
          '## Daily cohorts and checkpoints', '',
          'Merged = closing PRs merged within the labelled window (full PST day or checkpoint); '
          'open = current linked open PR snapshot at collection, '
          'not historical open counts. Reviewed = reviewed PRs in the union of those two cohorts. '
          'Open snapshots overlap: never sum them across days. Unlinked PRs are outside journey coverage. '
          'Only independent, nonduplicate verdicts count; helpers never add rounds. '
          'Missing verdicts are unreviewed, not failed approvals. Every ratio uses reviewed PRs as its denominator.', '',
          '| Window | Cohort | PRs | First approvals/reviewed (share) | Rounds/reviewed PR | Unreviewed |',
          '| --- | --- | ---: | --- | --- | ---: |']
    for p in windows:
        r = p.get('journey')
        if r is None:
            md.append(f"| {cell(p['label'])} | unknown | unknown | unknown | unknown | unknown |")
            continue
        for name, c in r['cohorts'].items():
            md.append(f"| {cell(p['label'])} | {name} | {c['prs']} | {cohort_cells(c)} |")
    md += ['', '## Ready to merged and coverage', '',
           '| Window | Median hours | p90 hours | Tickets | Unknown ready | Selected PRs | Linked merged PRs | All factory merges | Open tickets without PRs | Edited PR events | Unknown PR events | Dropped duplicates |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for p in windows:
        r = p.get('journey')
        if r is None: continue
        t, c = r['ready_to_merged_hours'], r['coverage']
        md.append(f"| {cell(p['label'])} | {show(t['median'])} | {show(t['p90'])} | {t['tickets']} | {t['unknown']} | "
                  f"{c['selected_prs']} | {c['merged_prs']} | {p['merged_prs']} | {c['unlinked_open_tickets']} | {c['edited_events']} | "
                  f"{c['unknown_events']} | {c['duplicates_dropped']} |")
    md += ['', '## First push to verified merge and defect guards', '',
           'Primary timing uses sourced first-successful-push receipts and verified merges only. '
           'SD is sample standard deviation (unknown below two timed PRs). Unknowns never become zero. '
           'Builder-start and ready-time measures keep separate labels. Defect rates use only mature '
           'PRs with resolved attribution; observed attributable events are lower bounds. Selector '
           'escapes remain a different bench and supply no skill attribution. These observations do not prove causation.', '']+outcome_header
    for p in windows:
        o=p.get('journey',{}).get('outcomes')
        if o is None:
            md.append('| '+cell(p['label'])+' | unknown | unknown | unknown | unknown | unknown | unknown |')
            continue
        md.append(outcome_lines(p['label'],o))
        t=o['tickets']
        md += ['', f"{cell(p['label'])}: tickets total {t['total']}; merged {t['merged']}; open {t['open']}; "
               f"closed-unmerged {t['closed']}; without PR {t['without_pr']}. "
               f"Current PR snapshot: all {o['all']['prs']}; open {o['open']['prs']}; closed-unmerged {o['closed']['prs']}. "
               'Open/closed snapshots overlap across days; never sum them as assignments.']
        policy=o['defect_policy']
        md += ['Defect policy: '+('unknown (follow-up not asserted).' if policy is None else
               f"{cell(policy['rule'])}; frozen follow-up {show(policy['followup_hours'])} hours; root-cause-per-merge.")]
        md += ['Assigned experiment coverage: '+('not supplied; no assignment inferred.' if o['assigned'] is None else
               '; '.join(f"{arm}: assigned {a['tickets']}, merged {a['merged']}, open {a['open']}, "
                         f"closed {a['closed']}, without PR {a['without_pr']}" for arm,a in o['assigned'].items())),'']
    md += ['', '## Findings by kind', '',
           'One finding per PR/id across selected merged and current open PRs; unknown kind stays unknown. '
           'A recurring open finding can appear in several daily snapshots: these rows are not additive weekly incidents.', '',
           '| Window | ' + ' | '.join(J.KINDS) + ' |', '| --- | ' + ' | '.join(['---:']*len(J.KINDS)) + ' |']
    for p in windows:
        r = p.get('journey')
        md.append('| '+cell(p['label'])+' | '+' | '.join(str(r['findings'][k]) if r else 'unknown' for k in J.KINDS)+' |')
    md += ['', '## Credits per merged PR', '',
           'Attributed ticket credits are lower bounds for recorded threads. Shared parent work is excluded. '
           'A ticket linked to multiple PRs is unknown for per-PR attribution. Incomplete attribution or days '
           'makes the ratio unknown; provider units stay separate. No billing source is added.', '',
           '| Window | Provider | Known ticket credits (lower bound) | Known tickets | Unknown/incomplete tickets | Attributed credits/merged PR (lower bound) |',
           '| --- | --- | ---: | ---: | ---: | ---: |']
    for p in windows:
        for provider, c in p.get('journey', {}).get('attributed_credits', {}).items():
            md.append(f"| {cell(p['label'])} | {provider} | {show(c['known_ticket_lower_bound'])} | "
                      f"{c['known_tickets']} | {c['unknown_tickets']} | {show(c['per_merged_pr'])} |")
    md += ['', 'Daily usage/merges below is a **UTC daily ratio, never ticket cost or a PST-day cost**. '
           'Includes shared/unattributed usage; no merges means unknown. Latest recorded value per UTC day.', '',
           '| UTC day | Provider | Daily credits | Daily merged PRs | Daily credits/merges |',
           '| --- | --- | ---: | ---: | ---: |']
    usage = {d['date']: d for p in windows for d in p.get('journey', {}).get('daily_usage_ratios', [])}
    for day, d in sorted(usage.items()):
        for provider, v in d['credits'].items():
            md.append(f"| {day} | {provider} | {show(v['total'])} | {d['merged_prs']} | {show(v['per_merged_pr'])} |")
    if not usage: md += ['| unknown | unknown | unknown | unknown | unknown |']
    md += ['', '## Week over week', '',
           'Merged cohorts only, latest full PST day ending the seven-day window. Missing days stay missing; '
           'ratios describe observed samples, not complete coverage. Revisions are recorded per experiment below.', ''] + header
    if points:
        md += [row(name, c) for name, c in zip(('Previous week', 'Latest week'), comparisons(points, points[-1]['until']))]
        md += ['', 'Outcome coverage uses only days with sidecars; missing days remain missing.']+outcome_header
        for name,c in zip(('Previous week','Latest week'),comparisons(points,points[-1]['until'])):
            if 'outcomes' in c:
                md += [outcome_lines(name+' outcomes',c['outcomes']), f"Outcome days: {c['outcomes']['days']}/7; compatible defect policies: {c['outcomes']['policy_compatible']}."]
    else: md += ['No daily observations.']
    md += ['', '## Before/after tagged experiments', '',
           'Seven full PST days before and after the merge day; the merge day is excluded. '
           'Open experiments have no rollout yet. Future/missing after days are unknown, never a zero-rate result. '
           'These observational comparisons include concurrent changes; they do not establish causation. '
           'CF4 markers record hashes, not a passing or paid result. No supplied result means not recorded, '
           'and the paid baseline remains not run/unverified. Changed cases/settings/code/schema require a fresh baseline.', '']
    experiments = {}
    for p in windows:
        for e in p.get('journey', {}).get('experiments', []):
            experiments[(e['tag'], e['revisions']['head'])] = e
    for e in experiments.values():
        md += [f"### {cell(e['tag'])}", '',
               f"Revisions: base `{e['revisions']['base']}`, head `{e['revisions']['head']}`, merge `{e['revisions']['merge']}`.", '',
               f"CF4 result: **{e['cf4_status']}**; result hash `{e['result_hash']}`; schema `{e['schema_hash']}`."]
        if e['cf4']:
            md += ['CF4: '+ '; '.join(f'{k} `{v}`' for k, v in e['cf4'].items())+'.']
        else: md += ['CF4 settings/cases/code/revision: unknown.']
        for s in e['baselines']:
            md += [f"Baseline revision `{s['cf4']['revision']}`: **{s['status']}**; "
                   f"result `{s['result_hash']}`; schema `{s['schema_hash']}`; "+
                   '; '.join(f"{k} `{s['cf4'][k]}`" for k in ('settings_hash', 'cases_hash', 'code_hash'))+'.']
        compatible = [s for s in e['baselines'] if e['cf4'] and e['result_hash'] and
                      s['schema_hash'] == e['schema_hash'] and
                      all(s['cf4'][k] == e['cf4'][k] for k in ('settings_hash', 'cases_hash', 'code_hash'))]
        md += ['Compatible CF4 baseline: '+('recorded (outcomes listed above).' if compatible else
                'unknown; absent results or changed cases/settings/code/schema need a fresh baseline.'), '']
        if e['merged_at']:
            day = (J.M.timestamp(e['merged_at'])-timedelta(hours=8)).date()
            boundary = J.M.timestamp(f'{day}T08:00:00Z')
            before = period(points, J.M.iso(boundary-timedelta(days=7)), J.M.iso(boundary))
            after = period(points, J.M.iso(boundary+timedelta(days=1)), J.M.iso(boundary+timedelta(days=8)))
            md += header + [row('Before', before), row('After', after), '']
            md += outcome_header
            for name,c in (('Before',before),('After',after)):
                if 'outcomes' in c:
                    md += [outcome_lines(name+' outcomes',c['outcomes']),f"Outcome days: {c['outcomes']['days']}/7; compatible defect policies: {c['outcomes']['policy_compatible']}."]
                else: md += [f'| {name} outcomes | unknown | unknown | unknown | unknown | unknown | unknown |']
        else: md += ['Before/after: unknown (experiment has not merged).', '']
    if not experiments: md += ['No tagged experiments recorded in these windows.']
    B.write(Path(out)/'journey-trends.md', '\n'.join(md)+'\n')
    # Absent publications are unknown days too. These placeholders are only
    # for rendering; tables and observed-day arithmetic retain the real points.
    chart_points = []
    if points:
        by_day = {p['since']: p for p in points}
        start, end = J.M.timestamp(min(by_day)), J.M.timestamp(max(by_day))
        for day in range((end-start).days+1):
            at = J.M.iso(start+timedelta(days=day))
            chart_points.append(by_day.get(at, {'since': at}))
    def value(cohort_name, key, scale=1):
        def get(p):
            v = p.get('journey', {}).get('cohorts', {}).get(cohort_name, {}).get(key)
            return None if v is None else v*scale
        return get
    panels = [('Merged cohort first-time approvals', '% reviewed', 'line', [
                   ('Independent approvals', B.AQUA, value('merged', 'approval_share', 100), '{:.0f}%', 'of reviewed merged PRs')]),
              ('Merged cohort review rounds', 'rounds', 'line', [
                   ('Rounds per reviewed PR', B.VIOLET, value('merged', 'rounds_per_pr'), '{:.2f}', 'rounds per reviewed merged PR')])]
    B.write(Path(out)/'journey-reviews.svg', B.chart_days(chart_points, 'Journey reviews',
            'Independent verdicts only; missing samples stay unknown. Sample sizes in journey-trends.md.', panels, grid=False))
    panels = [(k, 'findings', 'count', [(k, color,
               lambda p, k=k: p.get('journey', {}).get('findings', {}).get(k), '{:.0f}', 'findings')])
              for k, color in zip(J.KINDS, (B.BLUE, B.ORANGE, B.AQUA, B.MAGENTA, B.VIOLET))]
    B.write(Path(out)/'journey-findings.svg', B.chart_days(chart_points, 'Journey finding kinds',
            'Selected merged and current open PRs; snapshots overlap, never sum them as weekly incidents.', panels, grid=False))


if __name__ == '__main__': sys.exit(main())
