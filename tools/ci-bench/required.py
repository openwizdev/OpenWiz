#!/usr/bin/env python3
"""Offline CI2 actual-push/required-result measurement (#2311).

Read a frozen, independently acquired evidence bundle. No network, subprocess,
publication or account mutation. This is measurement, never CI admission.
"""
import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
import sys

MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 10000
TERMINAL = {'success', 'failure', 'cancelled', 'skipped', 'neutral',
            'timed_out', 'action_required', 'stale', 'startup_failure'}
ACTIVE = {'queued', 'in_progress', 'waiting', 'pending', 'requested'}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def obj(value, keys):
    need(type(value) is dict and set(value) == set(keys.split()), 'object keys: ' + keys)
    return value


def text(value):
    need(type(value) is str and 0 < len(value) <= 500 and value.isascii()
         and all(32 <= ord(c) < 127 for c in value), 'nonempty ASCII text required')
    return value


def array(value):
    need(type(value) is list and len(value) <= MAX_ITEMS, 'bounded array required')
    return value


def number(value, minimum=0):
    need(type(value) is int and value >= minimum, 'integer required')
    return value


def boolean(value):
    need(type(value) is bool, 'boolean required')
    return value


def sha(value):
    need(type(value) is str and re.fullmatch('[0-9a-f]{40}', value), 'head SHA required')
    return value


def clock(value):
    need(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value),
         'UTC timestamp required')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def optional_clock(value, frozen):
    if value is None:
        return None
    result = clock(value)
    need(result <= frozen, 'timestamp after freeze')
    return result


def distinct(values, what):
    need(len(values) == len(set(values)), 'duplicate ' + what)


def pages(value):
    """A normalized complete export: page order, next links and counts agree.

    Source points to the independent capture, not a claim of live acquisition.
    There is no inference that a short first page means the feed is complete.
    """
    obj(value, 'source total_count pages')
    text(value['source'])
    total = number(value['total_count'])
    need(total <= MAX_ITEMS, 'pagination bound')
    blocks = array(value['pages'])
    need(blocks, 'pagination missing')
    result = []
    for index, block in enumerate(blocks, 1):
        obj(block, 'number next items')
        need(type(block['number']) is int and block['number'] == index, 'pagination page order')
        need(type(block['next']) is bool and block['next'] == (index < len(blocks)),
             'pagination next link')
        rows = array(block['items'])
        need(rows or len(blocks) == 1, 'pagination empty intermediate page')
        result.extend(rows)
    need(len(result) == total, 'pagination total mismatch')
    return result


def summary(values):
    values = sorted(v for v in values if v is not None)
    return {'n': len(values), 'median': statistics.median(values) if values else None,
            'p90': values[math.ceil(len(values) * .9) - 1] if values else None}


def state(row):
    status, conclusion = row['status'], row['conclusion']
    need(type(status) is str and status in ACTIVE | {'completed'}, 'status')
    need((status == 'completed' and type(conclusion) is str and conclusion in TERMINAL)
         or (status in ACTIVE and conclusion is None), 'status/conclusion')


def measure_observation(row, frozen, attempts_seen, jobs_seen):
    obj(row, 'id repository head push_event_id push superseded batch runs')
    oid = text(row['id'])
    push_event_id = text(row['push_event_id'])
    repository = text(row['repository'])
    need(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository), 'repository')
    head = sha(row['head'])
    boolean(row['superseded'])
    pushed = None
    if row['push'] is not None:
        push = obj(row['push'], 'kind source head at')
        need(push['kind'] in ('push-log', 'webhook'), 'push kind must be independent push-log or webhook')
        text(push['source'])
        need(sha(push['head']) == head, 'push head identity')
        pushed = optional_clock(push['at'], frozen)
    batch = row['batch']
    if batch is not None:
        obj(batch, 'id base head members source')
        text(batch['id'])
        text(batch['source'])
        sha(batch['base'])
        need(sha(batch['head']) == head, 'batch head identity')
        members = [sha(s) for s in array(batch['members'])]
        need(members and members[-1] == head, 'batch combined head/member identity')
        distinct(members, 'batch member')
    runs = pages(row['runs'])
    current = {}
    latest = {}
    workflow_runs = {}
    jobs, queues, runners, attempt_records = [], [], Counter(), []
    censored, allocated = [], 0
    gaps = []
    for run in runs:
        obj(run, 'run attempt head workflow current created_at status conclusion source jobs')
        rid, attempt = number(run['run'], 1), number(run['attempt'], 1)
        identity = (repository, rid, attempt)
        need(identity not in attempts_seen, 'duplicate attempt')
        attempts_seen.add(identity)
        need(sha(run['head']) == head, 'run head identity')
        workflow = text(run['workflow'])
        text(run['source'])
        boolean(run['current'])
        state(run)
        created = optional_clock(run['created_at'], frozen)
        if created is not None and pushed is not None:
            need(created >= pushed, 'run predates push')
        run_clocks = workflow_runs.setdefault(workflow, {})
        if rid in run_clocks:
            need(run_clocks[rid] == created, 'inconsistent run creation time')
        run_clocks[rid] = created
        latest[rid] = max(latest.get(rid, 0), attempt)
        run_jobs = pages(run['jobs'])
        by_name = {}
        for job in run_jobs:
            obj(job, 'id run attempt head name status conclusion created_at started_at completed_at runner')
            jid = number(job['id'], 1)
            need((repository, jid) not in jobs_seen, 'duplicate job')
            jobs_seen.add((repository, jid))
            need(type(job['run']) is int and type(job['attempt']) is int
                 and job['run'] == rid and job['attempt'] == attempt and job['head'] == head,
                 'job identity differs from head/run/attempt')
            name = text(job['name'])
            need(name not in by_name, 'duplicate job name within attempt')
            by_name[name] = job
            state(job)
            a = optional_clock(job['created_at'], frozen)
            b = optional_clock(job['started_at'], frozen)
            c = optional_clock(job['completed_at'], frozen)
            if pushed is not None:
                need(all(t is None or t >= pushed for t in (a, b, c)), 'job predates push')
            need(all(x is None or y is None or x <= y for x, y in ((a, b), (a, c), (b, c))),
                 'job clock reversed')
            need(job['status'] == 'completed' or c is None, 'unfinished job has end')
            if b is not None:
                allocated += 1
            if job['runner'] is not None:
                text(job['runner'])
                need(b is not None, 'runner without observed start')
                runners[job['runner']] += 1
            elif b is not None:
                gaps.append('unknown actual runner: ' + str(jid))
            if a is not None and b is not None:
                queues.append((b - a).total_seconds())
            else:
                gaps.append('unknown/censored job queue: ' + str(jid))
                if a is not None and b is None and job['status'] == 'queued':
                    censored.append((frozen - a).total_seconds())
            jobs.append(job)
        attempt_records.append({'run': rid, 'attempt': attempt, 'workflow': workflow,
                                'current': run['current'], 'status': run['status'],
                                'conclusion': run['conclusion'], 'jobs': len(run_jobs),
                                'source': run['source']})
        if run['current']:
            need(workflow not in current, 'multiple current runs for workflow')
            current[workflow] = (run, by_name)
    for run, _ in current.values():
        run_clocks = workflow_runs[run['workflow']]
        if len(run_clocks) > 1:
            need(all(t is not None for t in run_clocks.values()), 'ambiguous current run')
            newest = max(run_clocks.values())
            need(list(run_clocks.values()).count(newest) == 1, 'ambiguous current run')
            need(run_clocks[run['run']] == newest, 'current run is stale')
        need(run['attempt'] == latest[run['run']], 'current attempt is stale')
    return {'id': oid, 'repository': repository, 'head': head, 'push': row['push'],
            'push_event_id': push_event_id,
            'batch': batch, 'superseded': row['superseded'], 'attempt_records': attempt_records,
            'jobs': len(jobs), 'job_records': jobs,
            'allocated_jobs': allocated, 'censored_queue_seconds': censored,
            'attempts': len(runs), 'runners': dict(sorted(runners.items())),
            'job_queue_seconds': summary(queues), 'gaps': sorted(set(gaps)),
            '_current': current, '_pushed': pushed, '_queues': queues}


def required_result(observation, required, frozen):
    checks, ends, missing, unfinished = [], [], False, False
    run_outcomes = set()
    for check in required:
        workflow, name = check['workflow'], check['name']
        found = observation['_current'].get(workflow)
        job = found[1].get(name) if found else None
        if job is None:
            missing = True
            checks.append({'workflow': workflow, 'name': name, 'outcome': 'missing'})
            continue
        run = found[0]
        run_outcomes.add(run['conclusion'])
        checks.append({'workflow': workflow, 'name': name, 'run': run['run'],
                       'attempt': run['attempt'], 'job': job['id'], 'outcome': job['conclusion'],
                       'source': run['jobs']['source']})
        end = optional_clock(job['completed_at'], frozen)
        if job['status'] != 'completed' or end is None or run['status'] != 'completed':
            unfinished = True
        else:
            ends.append(end)
    outcomes = {c['outcome'] for c in checks}
    if observation['superseded']:
        outcome = 'superseded'
    elif missing:
        outcome = 'missing'
    elif unfinished:
        outcome = 'unfinished'
    elif 'cancelled' in outcomes | run_outcomes:
        outcome = 'cancelled'
    elif outcomes != {'success'} or run_outcomes != {'success'}:
        outcome = 'failed'
    else:
        outcome = 'success'
    complete = not missing and not unfinished
    end = max(ends) if complete else None
    pushed = observation['_pushed']
    observation.update(outcome=outcome, checks=checks,
        required_result_at=end.strftime('%Y-%m-%dT%H:%M:%SZ') if end else None,
        push_to_required_seconds=(end - pushed).total_seconds() if end and pushed else None)
    if pushed is None:
        observation['gaps'].append('actual push time unknown; run creation is not a substitute')
    if end is None:
        observation['gaps'].append('complete required result time unknown')


def measure_cost(cost):
    obj(cost, 'id kind evidence complete since until source components')
    text(cost['id'])
    text(cost['source'])
    need(cost['kind'] in ('whole-bill', 'list-estimate'), 'cost kind')
    need(cost['evidence'] in ('synthetic', 'observation'), 'cost evidence')
    boolean(cost['complete'])
    need(clock(cost['since']) < clock(cost['until']), 'cost period')
    categories = []
    amounts = []
    gaps = []
    for component in array(cost['components']):
        obj(component, 'category microusd source')
        categories.append(text(component['category']))
        text(component['source'])
        amount = component['microusd']
        if amount is None:
            gaps.append('unknown cost: ' + component['category'])
        else:
            amounts.append(number(amount))
    distinct(categories, 'cost category')
    need(set(categories) == {'plan', 'seats', 'compute', 'storage', 'app', 'other'}, 'whole-bill categories')
    if cost['kind'] != 'whole-bill':
        gaps.append('list-price estimates are not whole-bill proof')
    if not cost['complete']:
        gaps.append('incomplete billing coverage')
    known = sum(amounts) / 1000000 if len(amounts) == len(categories) else None
    return dict(cost, reported_components_usd=known, whole_bill_usd=known if not gaps else None,
                gaps=gaps, counted_once=True)


def measure(data, fingerprint):
    obj(data, 'schema evidence frozen_at synthetic_assumptions cohorts observations comparisons cost')
    for assumption in array(data['synthetic_assumptions']):
        text(assumption)
    need(data['evidence'] != 'synthetic' or data['synthetic_assumptions'], 'synthetic assumptions required')
    need(data['schema'] == 'closedwiz.ci-required.v1', 'schema')
    need(data['evidence'] in ('synthetic', 'observation'), 'evidence class')
    frozen = clock(data['frozen_at'])
    observations = {}
    attempts_seen, jobs_seen = set(), set()
    for row in array(data['observations']):
        observed = measure_observation(row, frozen, attempts_seen, jobs_seen)
        need(observed['id'] not in observations, 'duplicate observation')
        observations[observed['id']] = observed
    cohorts, cohort_index, enrolled = [], {}, set()
    batch_ids, push_ids = set(), set()
    for cohort in array(data['cohorts']):
        obj(cohort, 'id since until criteria membership')
        cid = text(cohort['id'])
        need(cid not in cohort_index, 'duplicate cohort')
        since, until = clock(cohort['since']), clock(cohort['until'])
        need(since < until <= frozen, 'cohort window/freeze')
        criteria = obj(cohort['criteria'], 'repository event workload selection_policy runner_policy required_checks')
        for key in ('repository', 'event', 'workload', 'selection_policy'):
            text(criteria[key])
        need(criteria['event'] in ('pull_request', 'push', 'merge_group', 'schedule'), 'criteria event')
        need(criteria['runner_policy'] == 'all', 'criteria must include all actual runners')
        required = array(criteria['required_checks'])
        need(required, 'empty required checks')
        for check in required:
            obj(check, 'workflow name')
            text(check['workflow'])
            text(check['name'])
        distinct([(c['workflow'], c['name']) for c in required], 'required check')
        members = pages(cohort['membership'])
        for member in members:
            text(member)
        distinct(members, 'membership')
        need(all(m in observations and m not in enrolled for m in members), 'membership reused or unknown')
        enrolled.update(members)
        selected = [observations[m] for m in members]
        queue, runner_counts = [], Counter()
        for observation in selected:
            need(observation['repository'] == criteria['repository'], 'cohort repository mismatch')
            pushed = observation['_pushed']
            if pushed is not None:
                need(since <= pushed < until, 'push outside cohort window')
            push_key = (observation['repository'], observation['push_event_id'])
            need(push_key not in push_ids, 'duplicate push membership')
            push_ids.add(push_key)
            batch = observation['batch']
            if batch is not None:
                batch_key = (observation['repository'], batch['id'])
                need(batch_key not in batch_ids, 'duplicate batch credit')
                batch_ids.add(batch_key)
            required_result(observation, required, frozen)
            queue.extend(observation['_queues'])
            runner_counts.update(observation['runners'])
        latency = summary(o['push_to_required_seconds'] for o in selected)
        success = bool(selected) and all(o['outcome'] == 'success' for o in selected)
        result = dict(cohort, samples=len(selected),
            outcomes=dict(sorted(Counter(o['outcome'] for o in selected).items())),
            push_to_required_seconds=latency, job_queue_seconds=summary(queue),
            jobs=sum(o['jobs'] for o in selected),
            allocated_jobs=sum(o['allocated_jobs'] for o in selected),
            censored_queue_seconds=[v for o in selected for v in o['censored_queue_seconds']],
            attempts=sum(o['attempts'] for o in selected),
            runners=dict(sorted(runner_counts.items())),
            timing_target_met=(success and latency['n'] == len(selected)
                               and latency['median'] < 600 and latency['p90'] < 1200),
            gaps=sorted(set(g for o in selected for g in o['gaps'])))
        cohorts.append(result)
        cohort_index[cid] = result
    need(enrolled == set(observations), 'membership must include every observation')
    comparisons, cuts = [], set()
    for cut in array(data['comparisons']):
        obj(cut, 'id before after change')
        text(cut['id'])
        text(cut['change'])
        need(cut['id'] not in cuts, 'duplicate cut')
        cuts.add(cut['id'])
        need(cut['before'] in cohort_index and cut['after'] in cohort_index
             and cut['before'] != cut['after'], 'comparison cohorts')
        before, after = cohort_index[cut['before']], cohort_index[cut['after']]
        need(before['criteria'] == after['criteria'], 'comparison criteria differ')
        a, b = before['push_to_required_seconds'], after['push_to_required_seconds']
        complete = (a['n'] == before['samples'] and b['n'] == after['samples']
                    and before['samples'] > 0 and after['samples'] > 0)
        comparisons.append(dict(cut, additive=False,
            median_reduction_seconds=a['median'] - b['median'] if complete else None,
            p90_reduction_seconds=a['p90'] - b['p90'] if complete else None,
            cost_ref=data['cost']['id']))
    cost = measure_cost(data['cost'])
    need(all(clock(cost['since']) <= clock(c['since']) and clock(c['until']) <= clock(cost['until'])
             for c in cohorts), 'bill does not cover cohort windows')
    for observation in observations.values():
        for key in ('_current', '_pushed', '_queues'):
            del observation[key]
    return {'schema': 'closedwiz.ci-required-report.v1', 'input_sha256': fingerprint,
            'frozen_at': data['frozen_at'], 'evidence': data['evidence'],
            'synthetic_assumptions': data['synthetic_assumptions'], 'cohorts': cohorts,
            'observations': list(observations.values()), 'comparisons': comparisons, 'cost': cost,
            'live_success': 'Unverified',
            'limits': ['Offline evidence validation does not authenticate its capture or prove live CS1.',
                       'Terminal-result timing includes failures; success counts remain separate.',
                       'Job-created-to-started queue includes scheduler/dependency effects; censored waits are gaps.',
                       'Batch membership is reported, not verified combined-work admission.',
                       'Shared bills and overlapping cut improvements must never be summed.',
                       'CI1/X10 and historical creation-to-result metrics are separate.']}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path, help='frozen evidence bundle (offline; at most 8 MiB)')
    args = parser.parse_args()
    try:
        with args.input.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        need(len(raw) <= MAX_BYTES, 'input exceeds 8 MiB')
        data = json.loads(raw, object_pairs_hook=unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite number')))
        report = measure(data, hashlib.sha256(raw).hexdigest())
        print(json.dumps(report, indent=2, allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as error:
        print('required: ' + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
