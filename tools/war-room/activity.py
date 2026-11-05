#!/usr/bin/env python3
"""WR8: finite injected source observation -> activity provider + evidence bytes.

No CLI, default source reader, scheduler, network activation or billing call.
The caller retains the returned observation bytes at source_path with the
provider. Its SHA-256 binds every projected value to those sanitized bytes.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


B = _module('activity_ci_bench', HERE.parent / 'ci-bench/bench.py')
M = _module('activity_factory_metrics', HERE.parent / 'factory-metrics/metrics.py')
DIRECTIONS = ('forward', 'sideways', 'backwards')
COST_SCOPE = ('Complete cost today needs running jobs, earlier attempts, other workflows and billing; '
              'this estimate covers latest completed ci.yml runs created in this UTC day only, '
              'before included/free minutes; excludes storage, power, hardware and add-ons.')


def project(at, *, repo, read_started_at, source_path, pools=(),
            ci_read=None, pr_read=None, ticket_read=None):
    """Return (provider, canonical sanitized observation bytes).

    `at` is the caller's source read upper bound; read_started_at is its lower
    bound. No assembly clock or invented TTL. Pools are explicitly selected
    exact known labels, not an inventory assertion. None readers stay grey.
    `pr_read` is the existing factory collect_prs seam; ticket_read is graphql.
    """
    end, start = M.timestamp(at), M.timestamp(read_started_at)
    if start >= end or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('invalid observation bounds or repository')
    if len(set(pools)) != len(pools) or any(p not in B.ACTIVITY_POOLS for p in pools):
        raise ValueError('select unique exact supported pool labels')
    day, hour = end.replace(hour=0, minute=0, second=0), end.replace(minute=0, second=0)
    since = M.iso(day)
    observation = {'schema': 'openwiz.war-room.activity.v1', 'repo': repo,
                   'read_started_at': read_started_at, 'observed_at': at,
                   'pools': list(pools), 'ci': None, 'prs': None, 'gaps': []}
    if ci_read is not None:
        try:
            observation['ci'] = B.current_activity(since, at, repo=repo, read=ci_read)
        except (B.Fail, OSError, ValueError, TypeError, KeyError):
            observation['gaps'].append('Complete stable ci.yml run/job pagination and attempt/status observations required (existing 1000-item reader limit).')
    else:
        observation['gaps'].append('Injected supported CI run/job reader required; no live source activated.')
    if pr_read is not None and ticket_read is not None:
        try:
            prs = pr_read(repo)
            if any(p['merged'] is not None and p['merged'] > end for p in prs.values()):
                raise M.ReadError('unobserved merge')
            cohort = {n: p for n, p in prs.items() if p['merged'] is not None and day <= p['merged'] < end}
            observation['prs'] = M.activity_directions(repo, cohort, read=ticket_read)
        except (M.ReadError, OSError, ValueError, TypeError, KeyError):
            observation['prs'] = None
            observation['gaps'].append('Complete factory PR/closing-link pages and current closing-ticket milestone/title/label pages required.')
    else:
        observation['gaps'].append('Injected existing factory PR and closing-ticket metadata readers required; no live source activated.')
    # The observation contains no titles, labels, runner names or raw errors.
    wire = (json.dumps(observation, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    source = {'path': source_path, 'schema': observation['schema'], 'sha256': hashlib.sha256(wire).hexdigest()}
    metrics = []
    ci_evidence = [f'https://github.com/{repo}/actions/runs/{rid}'
                   for rid in (observation['ci'] or {}).get('runs', [])]
    pr_evidence = [f'https://github.com/{repo}/pull/{p["number"]}' for p in observation['prs'] or []]
    def metric(key, label, group, value, identities, lo, *, state='known', gaps=(),
               direction=None, pool=None, unit='count', links=()):
        if lo >= end:
            state, value, gaps = 'unavailable', None, ('No elapsed UTC calendar window at this boundary.',)
        metrics.append({'id': key, 'label': label, 'group': group, 'state': state, 'value': value,
            'unit': unit, 'native_unit': unit, 'statistic': 'count' if unit == 'count' else 'total',
            'window': {'since': M.iso(lo), 'until': at, 'timezone': 'UTC'} if lo < end else None, 'observed_at': at,
            'fresh_until': None, 'freshness': 'unknown', 'source': source,
            'evidence': sorted(set(links)),
            'sample': {'observed': len(identities), 'expected': len(identities) if state == 'known' else None,
                       'identities': identities, 'numerator': None, 'denominator': None},
            'dimensions': {'direction': direction, 'pool': pool, 'stage': None,
                           'ticket': None, 'cohort': key}, 'interval': None, 'prerequisites': list(gaps)})

    prs = observation['prs']
    for period, lo in [('hour', hour), ('day', day)]:
        selected = [p for p in prs or [] if M.iso(lo) <= p['merged_at'] < at]
        complete = prs is not None and all(p['direction'] is not None for p in selected)
        for direction in DIRECTIONS:
            ids = [f'pr-{p["number"]}' for p in selected if p['direction'] == direction]
            links = pr_evidence
            known = complete and bool(links)
            metric(f'merged-{period}-{direction}',
                   f'Merged this UTC {period} {direction} (current ticket metadata; all base branches)',
                   'throughput', len(ids) if known else None, ids, lo,
                   state='known' if known else 'partial' if links else 'unavailable',
                   gaps=() if known else ('Complete linked unambiguous current ticket direction and source coverage anchor required; historical metadata unavailable.',),
                   direction=direction, links=links)

    ci = observation['ci']
    jobs = (ci or {}).get('jobs', [])
    active = [j for j in jobs if j['status'] != 'completed']
    classified = {j['id']: j['pool'] for j in active}
    complete = ci is not None and all(classified.values()) and bool(ci_evidence)
    for pool in pools:
        for status, label in [('in_progress', 'running'), ('queued', 'queued')]:
            ids = [f'job-{j["id"]}' for j in active if j['status'] == status and classified[j['id']] == pool]
            metric(f'ci-{label}-{pool}', f'CI {label} in exact pool {pool} (read bounds)', 'ci',
                   len(ids) if complete else None, ids, start,
                   state='known' if complete else 'partial' if ci_evidence else 'unavailable',
                   gaps=() if complete else ('Complete stable run/job pages, explicit job status and exact pool labels for every active job required.',),
                   pool=pool, links=ci_evidence)
    if not pools:
        metric('ci-pools', 'Current CI running/queued pool coverage', 'ci', None, [], start,
               state='unavailable', gaps=('Select exact supported source pool labels; no runner inventory endpoint is assumed.',))
    cost = (ci or {}).get('cost')
    dates = sorted({p['verified_on'] for p in cost['prices']}) if cost else []
    metric('ci-cost-today-estimate', 'CI cost today estimate (latest completed ci.yml run-created UTC cohort)',
           'ci', cost['window_usd'] if cost and ci_evidence else None,
           [f'job-{jid}' for jid in (ci or {}).get('cost_jobs', [])], day,
           state='partial' if cost and ci_evidence else 'unavailable', unit='usd',
           gaps=(COST_SCOPE, 'Retained list-price verification dates: ' + ', '.join(dates)) if dates else (COST_SCOPE,), links=ci_evidence)
    metric('ci-cost-today-billing', 'CI cost today billing (separate from list estimates)',
           'ci', None, [], day, state='unavailable', unit='usd',
           gaps=('Complete day-specific existing billing evidence required; no billing source activated.',))
    gaps = sorted({p for m in metrics for p in m['prerequisites']} | set(observation['gaps']))
    available = any(m['state'] != 'unavailable' and m['evidence'] for m in metrics)
    return {'slot': 'activity', 'state': 'partial' if available else 'unavailable',
            'prerequisites': gaps, 'metrics': metrics}, wire
