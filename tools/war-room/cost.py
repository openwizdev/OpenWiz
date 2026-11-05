#!/usr/bin/env python3
"""Offline WR4 cost projection; no collector, billing read or allocation policy.

project returns the existing suite's cost provider. Native inputs are explicit
local artifacts with independently supplied observation/evidence metadata.
synthetic_allocation is only a worked projection example, never a native source.
"""
import copy
from datetime import timedelta
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


S = _module('wr4_suite', HERE / 'suite.py')
J = _module('wr4_journey', HERE.parent / 'factory-metrics/journey.py')
B = _module('wr4_ci', HERE.parent / 'ci-bench/bench.py')
COMPONENTS = ('models', 'shared_parent', 'helpers', 'sandbox', 'ci')
require = S.require


def _exact(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'invalid cost input fields')


def _ids(values):
    require(type(values) is list and all(type(n) is int and n > 0 for n in values)
            and len(set(values)) == len(values), 'invalid or repeated PR identity')
    return [f'pr-{n}' for n in sorted(values)]


def _number(value):
    require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
            'invalid cost amount')


def _unique(values):
    return list(dict.fromkeys(values))


def _metric(key, label, value, unit, *, source=None, evidence=(), window=None,
            observed_at=None, identities=(), expected=None, gaps=(), statistic='total',
            numerator=None, denominator=None, cohort=None):
    return {'id': key, 'group': 'ci', 'label': label,
            'state': 'unavailable' if value is None else 'partial' if gaps else 'known',
            'value': value, 'unit': unit, 'native_unit': unit, 'statistic': statistic,
            'window': copy.deepcopy(window), 'observed_at': observed_at,
            'fresh_until': None, 'freshness': 'unknown', 'source': copy.deepcopy(source),
            'evidence': list(evidence), 'sample': {'observed': len(identities),
                'expected': expected, 'identities': list(identities),
                'numerator': numerator, 'denominator': denominator},
            'dimensions': {'direction': None, 'pool': None, 'stage': None,
                           'ticket': None, 'cohort': cohort},
            'interval': None, 'prerequisites': _unique(gaps)}


def _read(selection, kind):
    _exact(selection, ('path', 'source_path', 'observed_at', 'evidence'))
    path = Path(selection['path'])
    wire = path.read_bytes()
    # Strict decode first, including duplicate keys and overflow, even if an
    # upstream validator only inspects the numeric fields used by its charts.
    doc = S._decode(wire)
    if kind == 'journey':
        J.validate(doc)
    else:
        require(path.name == 'point.json', 'CI selection must be point.json')
        native = B.read_point(path.parent)
        require(path.read_bytes() == wire and native == doc, 'CI artifact changed during read')
    source = {'path': selection['source_path'], 'schema': doc['schema'],
              'sha256': hashlib.sha256(wire).hexdigest()}
    S._shape(source, S.SCHEMA['$defs']['source'])
    observed = S._time(selection['observed_at'])
    require(type(selection['evidence']) is list and bool(selection['evidence']),
            'source needs independent evidence')
    # Validate the full metadata through the suite at project completion too.
    return doc, {'source': source, 'observed_at': selection['observed_at'],
                 'evidence': selection['evidence']}, observed


def _daily_pair(total, ratio, count):
    """Validate two independently rounded producer outputs, without a raw sum.

    Each saved six-decimal number describes a half-micro-unit rounding cell.
    Intersect the total's cell with the ratio's cell scaled by its denominator.
    A producer witness inside/adjacent to those bounds handles binary division
    and tie rounding, and refuses impossible touching cells (notably count=1).
    We retain neither this witness nor a fabricated unrounded source value.
    """
    if total is None or not count:
        require(ratio is None, 'native daily ratio needs a total and merges')
        return
    require(ratio is not None, 'native daily ratio is missing')
    _number(ratio)
    expected = {'total': total, 'per_merged_pr': ratio}
    if J.M.amount(total, count) == expected:
        return  # The saved total itself is one valid producer witness.
    half = Decimal('0.0000005')  # metrics.amount's documented six places.
    center, quotient = Decimal(str(total)), Decimal(str(ratio))
    lo = max(Decimal(0), center - half, (quotient - half) * count)
    hi = min(center + half, (quotient + half) * count)
    for boundary in (lo, hi, (lo + hi) / 2):
        candidate = float(boundary)
        for value in (candidate, math.nextafter(candidate, -math.inf),
                      math.nextafter(candidate, math.inf)):
            if math.isfinite(value) and value >= 0 and J.M.amount(value, count) == expected:
                return
    raise ValueError('native daily ratio arithmetic mismatch')


def _journey(selection):
    doc, meta, observed = _read(selection, 'journey')
    times = [S._time(e['at']) for group in ('specs', 'tickets', 'pull_requests')
             for entity in doc[group] for e in entity['events'] if e['at'] is not None]
    require(all(t <= observed for t in times), 'journey event beyond observation')
    export_days = {day['date'] for day in doc['daily_usage'] if day['date'] is not None}
    rejected = sum(day['date'] is None for day in doc['daily_usage'])
    source_gaps = ([f'{rejected} rejected daily usage export(s): date and coverage unknown; valid export required']
                   if rejected else [])
    metrics = []
    for day in doc['daily_usage']:
        if day['date'] is None:
            continue  # Retained explicitly in the source prerequisites below.
        since = day['date'] + 'T00:00:00Z'
        until = (S._time(since) + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
        require(S._time(until) <= observed, 'daily usage beyond observation')
        day_window = {'since': since, 'until': until, 'timezone': 'UTC'}
        count = day['merged_prs']
        for provider, units in day['totals'].items():
            for unit, amount in units.items():
                total, ratio = amount['total'], amount['per_merged_pr']
                if total is not None:
                    _number(total)
                _daily_pair(total, ratio, count)
                key = f'daily-{day["date"]}-{provider}-{unit}'
                identity = [f'day-{day["date"]}']
                metrics.append(_metric(key, f'{provider} UTC daily usage ({unit})', total, unit,
                    **meta, window=day_window, identities=identity, expected=1,
                    gaps=[] if total is not None else [f'{provider}/{unit}: complete daily usage export required']))
                # These are source day aggregates, not PR attribution or a
                # manufactured list of the day's PR identities.
                ratio_unit = 'usd_per_merged_pr' if unit == 'usd' else unit
                gaps = [] if ratio is not None else ['A known daily total and nonzero merged denominator are required']
                if unit == 'usd' and ratio is not None and not math.isclose(ratio, total / count, rel_tol=1e-12, abs_tol=0):
                    ratio = None
                    gaps = ['Native six-decimal USD day ratio is not representable as an exact suite quotient']
                metrics.append(_metric(key + '-ratio', f'{provider} UTC day ratio ({unit}/merge); not PR attribution',
                    ratio, ratio_unit, **meta, window=day_window,
                    identities=[f'day-{day["date"]}-merge-{n+1}' for n in range(count)], expected=count,
                    statistic='ratio' if unit == 'usd' else 'observation',
                    numerator=total if unit == 'usd' and total is not None and count else None,
                    denominator=count if unit == 'usd' and total is not None and count else None,
                    gaps=gaps))
    for group, name, field in (('specs', 'spec', 'spec'), ('tickets', 'ticket', 'ticket')):
        for entity in doc[group]:
            identity = f'{name}-{entity[field]}'
            events = list(entity['events'])
            if name == 'ticket':
                events.extend(e for pr in doc['pull_requests'] if pr['number'] in entity['pull_requests']
                              for e in pr['events'])
            span = J.days(events)  # Existing producer's full UTC-day rule.
            covered = sorted(span & export_days)
            window = None if not covered else {
                'since': covered[0] + 'T00:00:00Z',
                'until': (S._time(covered[-1] + 'T00:00:00Z') + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'timezone': 'UTC'}
            for usage in entity['usage']:
                provider, unit = usage['provider'], usage['unit']
                gaps = ['Thread-record lower bound: helpers/unrecorded threads and complete attribution are unproven',
                        'Shared parent work is separate; sandbox and CI are unallocated']
                missing = sorted(set(usage['missing_days']) | (span - export_days))
                if missing:
                    gaps.append('Missing usage days: ' + ', '.join(missing))
                if window is None:
                    gaps.append('Entity-specific UTC usage days and valid export coverage are unavailable')
                if usage['status'] != 'known':
                    gaps.append('Native usage status: ' + usage['status'])
                metrics.append(_metric(f'{identity}-{provider}-{unit}',
                    f'{identity} {provider} thread-record lower bound ({unit})',
                    usage['value'] if window is not None else None, unit,
                    **meta, window=window, identities=[identity], gaps=gaps))
    prs = [p['number'] for p in doc['pull_requests'] if p['state'] == 'merged']
    return metrics, _ids(prs), source_gaps


def _ci(selection):
    point, meta, observed = _read(selection, 'ci')
    require(S._time(point['since']) < S._time(point['until']) <= observed, 'CI window beyond observation')
    cost = point.get('cost')
    value = None if cost is None else cost['window_usd']
    prices = [] if cost is None else cost['prices']
    gaps = ['CI list-rate estimate, not invoice; latest attempts/completed ci.yml jobs only; '
            'other workflows, storage, PC costs and add-ons excluded',
            'Requires complete CI attribution to the selected merged-PR cohort']
    gaps.append('Price verification: ' + (', '.join(sorted({p['verified_on'] for p in prices})) or 'unavailable'))
    if value is None:
        gaps.append('Complete known job prices/durations and a cost record required')
    return [_metric('ci-estimate', 'CI window list-rate estimate (USD); not all-in cost', value, 'usd',
                    **meta, window={'since': point['since'], 'until': point['until'],
                                   'timezone': 'PST-fixed-UTC-08:00' if point['since'][11:] == '08:00:00Z'
                                   and point['until'][11:] == '08:00:00Z' else 'UTC'},
                    identities=['ci-window'], expected=None, gaps=gaps)]


def _allocation(facts):
    """Synthetic-only demonstration; no existing source provides this allocation.

    Each row's full charge is already attributed to exactly its stated PR set.
    No division, apportionment, currency conversion or inference is performed.
    Coverage rows for a component must be disjoint; charge IDs are global.
    """
    _exact(facts, ('evidence_class', 'cohort', 'prs', 'window', 'observed_at', 'components'))
    require(facts['evidence_class'] == 'synthetic', 'no real allocation source is supported')
    identities = _ids(facts['prs'])
    require(type(facts['cohort']) is str and re.fullmatch(r'[a-z0-9][a-z0-9._:-]*', facts['cohort']), 'invalid cohort')
    S._shape(facts['window'], S.SCHEMA['$defs']['window'])
    S._time(facts['observed_at'])
    require(type(facts['components']) is list, 'components must be an array')
    covered, charges, evidence = {c: set() for c in COMPONENTS}, set(), []
    total = Decimal(0)
    for row in facts['components']:
        _exact(row, ('component', 'prs', 'value', 'unit', 'complete', 'charges', 'window', 'source', 'evidence'))
        component = row['component']
        require(type(component) is str and component in COMPONENTS, 'unknown cost component')
        row_ids = _ids(row['prs'])
        require(bool(row_ids) and set(row_ids) <= set(identities), 'foreign or empty component cohort')
        require(not (set(row_ids) & covered[component]), 'overlapping component coverage')
        # Incomplete rows reserve coverage too, so another row cannot duplicate
        # their charges under a complete label.
        covered[component].update(row_ids)
        require(row['unit'] == 'usd', 'all-in allocation requires USD')
        require(row['window'] == facts['window'], 'allocation window mismatch')
        require(type(row['complete']) is bool, 'invalid allocation completeness')
        require(type(row['charges']) is list and bool(row['charges'])
                and all(type(c) is str and re.fullmatch(r'[a-z0-9][a-z0-9._:-]*', c) for c in row['charges'])
                and len(set(row['charges'])) == len(row['charges']) and not (charges & set(row['charges'])),
                'repeated or missing underlying charge')
        charges.update(row['charges'])
        if row['value'] is not None:
            _number(row['value'])
            total += Decimal(str(row['value']))
        S._shape(row['source'], S.SCHEMA['$defs']['source'])
        S._shape(row['evidence'], S.SCHEMA['$defs']['metric']['properties']['evidence'])
        require(bool(row['evidence']), 'component requires evidence')
        evidence.extend(row['evidence'])
    gaps = []
    for component in COMPONENTS:
        complete = {identity for row in facts['components'] if row['component'] == component
                    and row['complete'] and row['value'] is not None for identity in _ids(row['prs'])}
        missing = sorted(set(identities) - complete)
        if missing or not identities:
            gaps.append(f'{component}: complete USD allocation required' + (': ' + ', '.join(missing) if missing else ''))
    if not identities:
        gaps.append('A nonzero unique merged-PR denominator is required')
    # This digest binds the normalized example facts; individual row sources are
    # separately retained on their metrics. It is not a native export identity.
    source = {'path': 'fixtures/synthetic/cost-projection.json', 'schema': 'synthetic.cost-projection.v1',
              'sha256': hashlib.sha256(json.dumps(facts, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()}
    metrics = []
    for component in COMPONENTS:
        rows = [row for row in facts['components'] if row['component'] == component]
        complete = {identity for row in rows if row['complete'] and row['value'] is not None
                    for identity in _ids(row['prs'])}
        component_gaps = [gap for gap in gaps if gap.startswith(component + ':')]
        known = [Decimal(str(row['value'])) for row in rows if row['value'] is not None]
        value = float(sum(known)) if known else None
        metrics.append(_metric('allocation-' + component, 'Synthetic allocated ' + component + ' (USD)',
            value, 'usd', source=source, evidence=_unique([link for row in rows for link in row['evidence']]),
            window=facts['window'], observed_at=facts['observed_at'],
            identities=sorted(complete), expected=len(identities),
            gaps=component_gaps, cohort=facts['cohort']))
    all_in = _metric('all-in', 'Synthetic all-in USD per merged PR', None if gaps else float(total / len(identities)),
        'usd_per_merged_pr', source=source, evidence=_unique(evidence), window=facts['window'],
        observed_at=facts['observed_at'], identities=identities, expected=len(identities), gaps=gaps,
        statistic='ratio', numerator=None if gaps else float(total), denominator=None if gaps else len(identities),
        cohort=facts['cohort'])
    return [all_in] + metrics, gaps


def project(sample_at, *, journey=None, ci=None, synthetic_allocation=None, assembled_at=None):
    """Return one suite cost provider from explicit local selections.

    journey/ci each contain path (actual input), source_path (sanitized artifact
    identity), observed_at and evidence. CI path names point.json. Inputs are
    validated using their native readers; no CLI, clock or network is invoked.
    assembled_at is an explicit injection; omission keeps the suite's sample-time default.
    Synthetic allocation never incorporates daily/lower-bound/estimate totals.
    """
    try:
        metrics, identities, source_gaps = [], [], []
        if journey is not None:
            values, identities, source_gaps = _journey(journey)
            metrics.extend(values)
        if ci is not None:
            metrics.extend(_ci(ci))
        if synthetic_allocation is None:
            gaps = [f'{component}: complete nonoverlapping USD allocation to one merged-PR cohort required'
                    for component in COMPONENTS]
            gaps.extend(source_gaps)
            if not identities:
                gaps.append('A known nonzero unique merged-PR cohort is required')
            all_in = _metric('all-in', 'All-in USD per merged PR: Unknown', None, 'usd_per_merged_pr',
                identities=identities, expected=len(identities) if journey is not None else None,
                gaps=gaps, statistic='ratio')
            metrics.insert(0, all_in)
        else:
            require(journey is None and ci is None, 'synthetic allocation cannot assert native source completeness')
            metrics, gaps = _allocation(synthetic_allocation)
        observed = any(m['state'] != 'unavailable' for m in metrics)
        state = 'known' if not gaps else 'partial' if observed else 'unavailable'
        provider = {'slot': 'cost', 'state': state, 'prerequisites': gaps, 'metrics': metrics}
        # A complete envelope check also validates every source/time/unit/link,
        # denominator and metric identity before the provider escapes this seam.
        return next(p for p in S.compose(sample_at, [provider], assembled_at=assembled_at)['providers'] if p['slot'] == 'cost')
    except (OSError, UnicodeError, TypeError, KeyError, OverflowError, J.ReadError, B.Fail) as error:
        raise ValueError('invalid or unreadable cost artifact') from error
