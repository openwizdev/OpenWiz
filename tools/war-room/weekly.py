#!/usr/bin/env python3
"""WR7: weekly stage changes from retained War room history. Offline only.

Reads validated `openwiz.war-room.v1` samples (`history.read_all`) and an
optional explicit local file of recorded changes. It collects nothing, runs no
eval, starts no schedule, opens no socket and writes nothing: the report is
printed. Cohorts follow the contract's weekly seam: two adjacent seven-day
windows ending at the latest complete fixed-PST day before `--at`.

Comparison reuses existing semantics instead of a new policy: pooled exact
distributions (`ci-bench/trends.distribution`, never averaged medians), ci-bench's
thin rule (n < 3) and skills-eval's like-with-like refusal (any changed limit,
unit, statistic, source schema or source window makes the stage noncomparable).
A faster/slower label is an observation; it never names a cause.
"""
import argparse
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import suite  # noqa: E402
import sources  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


trends = _load('war_room_weekly_trends', HERE.parent / 'ci-bench' / 'trends.py')

SCHEMA = 'openwiz.war-room.weekly.v1'
PST = 'PST-fixed-UTC-08:00'
STEP = timedelta(minutes=5)
WEEK = timedelta(days=7)
EXPECTED = WEEK // STEP  # 2016 retained five-minute samples per week.
DAY = timedelta(days=1) // STEP  # 288.
THIN = 3  # ci-bench: thin buckets are n < 3.
NOTES = [
    'Temporal association only: no recorded change is claimed as the cause of a stage change.',
    'Faster/slower compares pooled medians of completed, deduplicated native waits; '
    'it is shown only when both weeks are complete, on one basis, with n >= 3.',
    'Expected interval counts are null: the stage source does not establish its complete cohort.',
]
CHANGE_KEYS = {'at', 'label', 'evidence'}
LABEL = re.compile(r"[A-Za-z0-9 .,:;()'/#+-]{1,200}")
# WR3's explanation for an ended wait whose edited end record gives only a range: its
# endpoint is uncertain, not open. Any other partial wait stays open (censored).
EDITED_END = re.compile(r'Edited end record: the wait lies between [0-9]+(\.[0-9]+)? and [0-9]+(\.[0-9]+)? minutes\.')


def _iso(value):
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')


def end_of(at):
    """The latest fixed-PST day boundary (08:00 UTC) at or before `at`."""
    moment = suite._time(at)
    end = moment.replace(hour=8, minute=0, second=0)
    return end if end <= moment else end - timedelta(days=1)


def _private_text():
    checker_module = sources.native('tools/privacy-check/check.py')

    class Quiet(checker_module.Checker):
        def refuse(self, *args, **kwargs):
            self.findings += 1
    return Quiet()


def _changes(changes):
    """Exact recorded-change objects: UTC time, short safe label, GitHub links."""
    suite.require(type(changes) in (list, tuple), 'recorded changes must be an array')
    checker = _private_text()
    out = []
    for change in changes:
        suite.require(type(change) is dict and set(change) == CHANGE_KEYS, 'recorded change shape')
        suite._time(change['at'])
        label, evidence = change['label'], change['evidence']
        suite.require(type(label) is str and LABEL.fullmatch(label) is not None, 'recorded change label')
        suite.require(type(evidence) is list and evidence and all(
            type(u) is str and sources.LINK.fullmatch(u) for u in evidence), 'recorded change evidence')
        # Every recorded-change string passes the privacy checker and sources.safe_record's
        # retained-history credential pattern, named once in sources.py.
        for text in (change['at'], label, *evidence):
            checker.text(text, 'change')
            suite.require(not sources.CREDENTIAL.search(text), 'private recorded change refused')
        out.append({'at': change['at'], 'label': label, 'evidence': sorted(set(evidence))})
    suite.require(checker.findings == 0, 'private recorded change refused')
    return out


def _gaps(present, since, until):
    gaps, at, start = [], since, None
    while at < until:
        if _iso(at) in present:
            if start is not None:
                gaps.append({'since': _iso(start), 'until': _iso(at)})
                start = None
        elif start is None:
            start = at
        at += STEP
    if start is not None:
        gaps.append({'since': _iso(start), 'until': _iso(until)})
    return gaps


def _stage_metrics(record):
    provider = next(p for p in record['providers'] if p['slot'] == 'stage_waits')
    return provider['metrics']


def _basis(m):
    return {'unit': m['unit'], 'statistic': m['statistic'], 'schema': m['source']['schema'],
            'cohort': m['dimensions']['cohort']}


def _distinct(values):
    out = []
    for v in values:
        if v not in out:
            out.append(v)
    return out


def report(records, at, changes=()):
    """Return the weekly report dict. Raises ValueError on invalid input."""
    end = end_of(at)
    weeks = [('previous', end - 2 * WEEK, end - WEEK), ('latest', end - WEEK, end)]
    recorded = _changes(changes)
    by_id = {}
    for record in records:
        suite.validate(record)
        prior = by_id.setdefault(record['sample_id'], record)
        suite.require(prior == record, 'sample identity has differing payloads')
    kept = sorted((r for r in by_id.values() if weeks[0][1] <= suite._time(r['sample_at']) < end),
                  key=lambda r: r['sample_at'])

    def week_of(time):
        moment = suite._time(time)
        return next((name for name, a, b in weeks if a <= moment < b), None)

    def empty():
        return {name: {'samples': 0, 'limits': [], 'windows': [], 'basis': [], 'prerequisites': []}
                for name, _, _ in weeks}

    def buckets():
        return {'completed': [], 'open': [], 'unknown': [], 'conflicting': []}

    # Per sample, per stage: its limit, basis and source window, if the stage was read.
    stages, waits, derived = {}, {}, []
    last = {}
    for record in kept:
        sample, week = record['sample_at'], week_of(record['sample_at'])
        per = {}
        for m in _stage_metrics(record):
            stage, kind = m['dimensions']['stage'], m['id'].split(':', 1)[0]
            suite.require(type(stage) is str, 'stage metric without a source stage')
            row = per.setdefault(stage, {'limit': None, 'evidence': [], 'window': None, 'window_evidence': [],
                                         'basis': [], 'prerequisites': []})
            if kind == 'limit' and m['state'] == 'known':
                row['limit'] = {'value': m['value'], 'unit': m['unit'], 'schema': m['source']['schema']}
                row['evidence'] = m['evidence']
            elif kind == 'intervals' and m['state'] != 'unavailable':
                row['window'] = {'since': m['window']['since'], 'timezone': m['window']['timezone']}
                row['window_evidence'] = m['evidence']
                row['prerequisites'] += m['prerequisites']
            elif kind == 'wait':
                suite.require(m['interval'] is not None, 'wait without a native interval')
                key = m['interval']['id']
                row['basis'].append(_basis(m))
                waits.setdefault(key, []).append((sample, stage, m))
        for stage, row in per.items():
            s = stages.setdefault(stage, empty())[week]
            if row['window'] is not None and row['limit'] is not None:
                s['samples'] += 1
            s['limits'].append(row['limit'])
            s['windows'].append(row['window'])
            s['basis'] += row['basis']
            s['prerequisites'] += row['prerequisites']
            previous = last.get(stage)
            # A limit or source-window change is itself a recorded change, from history.
            for kind, key, links in (('limit', 'limit', 'evidence'), ('source_window', 'window', 'window_evidence')):
                if previous is not None and previous[key] != row[key]:
                    old, new = previous[key], row[key]
                    derived.append({'at': sample, 'week': week, 'kind': kind, 'stage': stage,
                                    'from': old['value'] if kind == 'limit' and old else old,
                                    'to': new['value'] if kind == 'limit' and new else new,
                                    'evidence': sorted(set(row[links])),
                                    'association': 'temporal only'})
            last[stage] = row

    # The snapshot at `end` is outside both coverage windows, but it is the first read of
    # intervals that completed just before it. Its waits are extracted only, never counted
    # as coverage; their cohort still comes from each interval's source end.
    for record in (r for r in by_id.values() if suite._time(r['sample_at']) == end):
        for m in _stage_metrics(record):
            if m['id'].split(':', 1)[0] == 'wait':
                suite.require(m['interval'] is not None, 'wait without a native interval')
                waits.setdefault(m['interval']['id'], []).append((record['sample_at'], m['dimensions']['stage'], m))

    # One observation per native interval id, however many snapshots repeat it.
    intervals = {name: {stage: buckets() for stage in stages} for name, _, _ in weeks}
    for key, seen in waits.items():
        stage = seen[-1][1]
        latest = seen[-1][2]
        # Open, unknown and conflicting ids stay with the week of their last in-window sighting;
        # one seen only at the closing boundary belongs to the next report.
        home = next((week_of(s) for s, _, _ in reversed(seen) if week_of(s) is not None), None)
        known = {(m['value'], m['interval']['started_at'], m['interval']['ended_at'])
                 for _, _, m in seen if m['state'] == 'known'}
        if len({s for _, s, _ in seen}) > 1 or len(known) > 1 or (known and latest['state'] != 'known'):
            if home is not None and stage in stages:
                intervals[home][stage]['conflicting'].append(key)
        elif known:
            value, _, ended = next(iter(known))
            week = week_of(ended)
            if week is not None:  # Ended before the previous week: outside both cohorts.
                if stage not in stages:  # First read at the closing boundary: no in-window stage coverage.
                    stages[stage] = empty()
                    for name, _, _ in weeks:
                        intervals[name][stage] = buckets()
                intervals[week][stage]['completed'].append(value)
                if week_of(seen[-1][0]) is None:  # A boundary read's basis joins the week it counts in.
                    stages[stage][week]['basis'].append(_basis(latest))
        elif home is not None:
            edited = [p for p in latest['prerequisites'] if EDITED_END.fullmatch(p)]
            bucket = 'open' if latest['state'] == 'partial' and not edited else 'unknown'
            intervals[home][stage][bucket].append(key)
            stages[stage][home]['prerequisites'] += edited  # Its explanation stays with the stage.

    rows = []
    for stage in sorted(stages):
        reasons, out = [], []
        for name, since, until in weeks:
            s, i = stages[stage][name], intervals[name][stage]
            observed = sum(1 for r in kept if week_of(r['sample_at']) == name)
            limits = _distinct(x for x in s['limits'] if x is not None)
            windows = _distinct(x for x in s['windows'] if x is not None)
            basis = _distinct(s['basis'])
            n = len(i['completed'])
            if observed < EXPECTED:
                reasons.append(f'{name} week: {EXPECTED - observed} of {EXPECTED} samples missing')
            if s['samples'] < observed:
                reasons.append(f'{name} week: stage data missing in {observed - s["samples"]} of {EXPECTED} samples')
            if len(limits) > 1 or None in s['limits']:
                reasons.append(f'{name} week: limit changed within the week' if len(limits) > 1
                               else f'{name} week: limit unknown in some samples')
            if len(windows) > 1:
                reasons.append(f'{name} week: source window changed within the week')
            if len(basis) > 1:
                reasons.append(f'{name} week: basis changed within the week')
            if n < THIN:
                reasons.append(f'{name} week: thin cohort, {n} completed waits (n < 3, the ci-bench thin rule)')
            if i['open']:
                reasons.append(f'{name} week: {len(i["open"])} open (censored) waits')
            if i['unknown']:
                reasons.append(f'{name} week: {len(i["unknown"])} waits with unknown endpoints')
            if i['conflicting']:
                reasons.append(f'{name} week: {len(i["conflicting"])} conflicting snapshots of one interval')
            out.append({'name': name, 'stage_samples': {'observed': s['samples'], 'expected': EXPECTED},
                        'limits': limits, 'source_windows': windows, 'basis': basis,
                        'intervals': {'completed': n, 'open': len(i['open']), 'unknown': len(i['unknown']),
                                      'conflicting': len(i['conflicting']), 'expected': None},
                        'waits': trends.distribution(i['completed']),
                        'open_ids': sorted(i['open']), 'unknown_ids': sorted(i['unknown']),
                        'conflicting_ids': sorted(i['conflicting'])})
        a, b = out
        for key, reason in (('limits', 'limits differ between the weeks'),
                            ('source_windows', 'source windows differ between the weeks'),
                            ('basis', 'basis differs between the weeks')):
            if a[key] and b[key] and a[key] != b[key]:
                reasons.append(reason)
        change = 'unknown'
        if not reasons:
            before, after = a['waits']['median'], b['waits']['median']
            change = 'faster' if after < before else 'slower' if after > before else 'unchanged'
        limitations = _distinct(p for name, _, _ in weeks for p in stages[stage][name]['prerequisites'])
        rows.append({'stage': stage, 'change': change, 'reasons': reasons, 'weeks': out,
                     'limitations': limitations})

    notes, excluded = [], 0
    for c in recorded:
        week = week_of(c['at'])
        if week is None:
            excluded += 1
            continue
        notes.append(dict(c, week=week, kind='recorded', association='temporal only'))
    present = {r['sample_at'] for r in kept}
    report_weeks = []
    for name, since, until in weeks:
        observed = sum(1 for r in kept if since <= suite._time(r['sample_at']) < until)
        days = []
        for d in range(7):
            a, b = since + d * timedelta(days=1), since + (d + 1) * timedelta(days=1)
            days.append({'window': {'since': _iso(a), 'until': _iso(b), 'timezone': PST},
                         'observed': sum(1 for r in kept if a <= suite._time(r['sample_at']) < b),
                         'expected': DAY})
        report_weeks.append({'name': name, 'window': {'since': _iso(since), 'until': _iso(until), 'timezone': PST},
                             'samples': {'observed': observed, 'expected': EXPECTED, 'missing': EXPECTED - observed,
                                         'gaps': _gaps(present, since, until)},
                             'days': days})
    return {'schema': SCHEMA, 'at': at, 'end': _iso(end), 'weeks': report_weeks, 'stages': rows,
            'changes': sorted(notes + derived, key=lambda c: (c['at'], c['kind'], c.get('stage', ''))),
            'excluded_changes': excluded, 'notes': NOTES}


def markdown(r):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')

    def num(value):
        return 'unknown' if value is None else f'{value:g}'
    lines = [f'# War room weekly stage report, ending {r["end"]}', '',
             'Weeks are fixed PST (UTC-08:00) days; source windows keep their own labels.', '',
             '| Week | UTC bounds | Samples (observed/expected) | Gaps |', '| --- | --- | --- | --- |']
    for w in r['weeks']:
        lines.append(f'| {w["name"]} | {w["window"]["since"]} to {w["window"]["until"]} | '
                     f'{w["samples"]["observed"]}/{w["samples"]["expected"]} | {len(w["samples"]["gaps"])} |')
    lines += ['', '| Stage | Change | Previous median (n) | Latest median (n) | Open / unknown | Why not compared |',
              '| --- | --- | --- | --- | --- | --- |']
    for s in r['stages']:
        a, b = s['weeks']
        lines.append(f'| {cell(s["stage"])} | {s["change"]} | {num(a["waits"]["median"])} min (n={a["waits"]["n"]}) | '
                     f'{num(b["waits"]["median"])} min (n={b["waits"]["n"]}) | '
                     f'{a["intervals"]["open"] + b["intervals"]["open"]} / '
                     f'{a["intervals"]["unknown"] + b["intervals"]["unknown"]} | {cell("; ".join(s["reasons"]) or "-")} |')
    lines += ['', '## Recorded changes (shown alongside, not a cause)', '']
    for c in r['changes']:
        what = cell(c['label']) if c['kind'] == 'recorded' else f'{c["stage"]} {c["kind"]}: {c["from"]} -> {c["to"]}'
        lines.append(f'- {c["at"]} ({c["week"]} week): {what}; ' + (', '.join(c['evidence']) or 'no link'))
    if not r['changes']:
        lines.append('- none recorded in these weeks')
    return '\n'.join(lines + ['', *(f'_{n}_' for n in r['notes'])]) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', required=True, type=Path, help='retained War room history root')
    parser.add_argument('--at', required=True, help='explicit UTC report time; no clock is read')
    parser.add_argument('--changes', type=Path, help='local JSON array of recorded changes')
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    args = parser.parse_args()
    try:
        suite._time(args.at)
    except ValueError:
        parser.error('--at must be a UTC time like 2030-01-02T12:00:00Z')
    try:
        import history
        records = history.read_all(args.history)
        changes = suite._decode(args.changes.read_text(encoding='utf-8')) if args.changes else []
        result = report(records, args.at, changes)
    except (OSError, ValueError, UnicodeError, KeyError, TypeError):
        print('weekly: unreadable or invalid input', file=sys.stderr)
        return 1
    if args.format == 'markdown':
        sys.stdout.write(markdown(result))
    else:
        print(json.dumps(result, sort_keys=True, indent=1, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
