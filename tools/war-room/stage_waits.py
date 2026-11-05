#!/usr/bin/env python3
"""WR3: project TL2's measured stage waits and TL1's limits into the War room.

Reads three explicit local files once each: TL2's `journeys.json`, its bound
`stage-waits.json` sidecar and a TL1 `limits.conf`. The producers' own checks
run first (`journey.validate_stage_waits`, `limits.read`), then TL2's own
`stage_bench` computes every wait, result and miss. This file only maps those
facts onto suite metrics: no timer, settings owner, source parser, recovery or
effect. Any refusal leaves the whole slot grey with its prerequisite. Windows
and read times come only from their own source or the caller's selection.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent / 'factory-metrics'


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


suite = _load('war_room_suite', HERE / 'suite.py')
producer = _load('war_room_tl2_journey', TOOLS / 'journey.py')
limits = producer.limits_module()

SLOT, GROUP, COHORT = 'stage_waits', 'stage_waits', 'tl2-stage-waits'
NAMES = {'builder_start': 'Builder start', 'reviewer_start': 'Reviewer start', 'merge': 'Merge',
         'fix_after_changes': 'Fix after CHANGES', 'builder_question_answer': 'Builder question answer'}
HISTORY = ('TL2 #2337 history is unknown: deleted comments or label events are invisible, '
           'so counts are those the collection still shows, not a complete cohort.')
REFUSED = ('TL2 #2337 journeys.json and its bound stage-waits.json sidecar, checked by TL2, and a TL1 #2336 '
           'limits.conf read by limits.py; {what} was unavailable or refused, so no wait, limit or miss is shown.')


def unavailable(what='the producer input'):
    return {'slot': SLOT, 'state': 'unavailable', 'metrics': [],
            'prerequisites': [REFUSED.format(what=what)]}


def _pinned(root, relative):
    base = Path(root).resolve()
    path = (base / relative).resolve()
    suite.require(path.is_relative_to(base) and path != base, 'input escapes root')
    raw = path.read_bytes()
    return raw, {'path': path.relative_to(base).as_posix(), 'sha256': hashlib.sha256(raw).hexdigest()}


def _settings(root, relative, raw):
    """TL1's own reader on the file, refused unless its bytes are the hashed ones."""
    path = Path(root).resolve() / relative
    loaded = limits.read(path)
    suite.require(path.read_bytes() == raw, 'settings changed while read')
    return loaded


def project(sample_at, *, root, journey, sidecar, settings, settings_evidence, assembled_at=None,
            cohort_since=None, settings_read_at=None):
    """Return the `stage_waits` provider for `suite.compose`. Never raises on
    producer refusal: that is the explicit unavailable slot, never zero.

    TL2 chooses no collection window, so `cohort_since` is the caller's
    established start for the tickets it named (ending at TL2's read), and
    `settings_read_at` is when the caller read the settings. Without either, the
    metrics that need it stay grey; each wait keeps its own native span."""
    names = {'journey': journey, 'sidecar': sidecar, 'settings': settings}
    pinned = {}
    for what, relative in names.items():
        try:
            pinned[what] = _pinned(root, relative)
        except (OSError, ValueError):
            return unavailable('the ' + what)
    try:
        doc = producer.M.load(pinned['journey'][0].decode('utf-8'))
        side = producer.M.load(pinned['sidecar'][0].decode('utf-8'))
        producer.validate_stage_waits(side, doc)
    except (ValueError, UnicodeError, KeyError, TypeError, StopIteration, producer.ReadError):
        return unavailable('the TL2 journey/sidecar pair')
    try:
        loaded = _settings(root, settings, pinned['settings'][0])
    except (OSError, ValueError, UnicodeError):
        return unavailable('the TL1 settings file')
    try:
        provider = _project(doc, side, loaded, pinned, list(settings_evidence), cohort_since, settings_read_at)
        checked = suite.compose(sample_at, [provider], assembled_at=assembled_at)
    except (ValueError, KeyError, TypeError):
        return unavailable('a valid suite projection of the producer facts')
    return next(p for p in checked['providers'] if p['slot'] == SLOT)


def _project(doc, side, loaded, pinned, settings_evidence, cohort_since, settings_read_at):
    bench = producer.stage_bench(side, loaded)
    suite.require(bench['authority'] == 'none', 'stage facts carry no authority')
    repo, links = side['repo'], side['sources']
    read_at = side['read_at']
    intervals = {i['key']: i for i in side['intervals']}
    points = [i[n]['at'] for i in intervals.values() for n in ('start', 'end') if i[n]]
    cohort, cohort_gap = None, None
    if cohort_since is None:
        cohort_gap = 'No established cohort window: TL2 chooses none; supply the selection\'s start.'
    elif not (suite._time(cohort_since) < suite._time(read_at) and all(cohort_since <= t for t in points)):
        cohort_gap = 'The supplied cohort window does not contain every TL2 record before its read.'
    else:
        cohort = {'since': cohort_since, 'until': read_at, 'timezone': 'UTC'}
    settings_gap = None
    if settings_read_at is None:
        settings_gap = 'The settings read time is not established.'
    elif suite._time(settings_read_at) < suite._time(read_at):
        settings_gap = 'The settings were read before the TL2 read, so they are not the limits these waits were judged by.'
    tl2 = {'path': pinned['sidecar'][1]['path'], 'schema': side['schema'], 'sha256': pinned['sidecar'][1]['sha256']}
    tl1 = {'path': pinned['settings'][1]['path'], 'schema': loaded['schema'],
           'sha256': pinned['settings'][1]['sha256']}
    collection = sorted({f'https://github.com/{repo}/issues/{t["ticket"]}' for t in doc['tickets']})

    def ident(key):
        return key.lower()  # TL2 keys differ from suite ids only by T/Z in fixed timestamps.

    def metric(id, label, stage, value, unit, statistic, state, ids, evidence, prerequisites,
               source, window, *, ticket=None, interval=None, expected='same', observed_at=read_at, gap=None):
        if gap is not None or (window is None and value is not None):
            state, value = 'unavailable', None
            window = None
            prerequisites = list(prerequisites) + [gap or 'No native source window for this value.']
        return {'id': id, 'group': GROUP, 'label': label, 'state': state,
                'value': None if state == 'unavailable' else value, 'unit': unit, 'native_unit': unit,
                'statistic': statistic, 'window': window, 'observed_at': observed_at,
                'fresh_until': None, 'freshness': 'unknown', 'source': source, 'evidence': sorted(set(evidence)),
                'sample': {'observed': len(ids), 'expected': len(ids) if expected == 'same' else expected,
                           'identities': list(ids), 'numerator': None, 'denominator': None},
                'dimensions': {'direction': None, 'pool': None, 'stage': stage, 'ticket': ticket, 'cohort': COHORT},
                'interval': interval, 'prerequisites': [] if state == 'known' else list(dict.fromkeys(prerequisites))}

    metrics = []
    for row in bench['stages']:
        stage, name = row['stage'], NAMES[row['stage']]
        metrics.append(metric('limit:' + stage, f'{name} limit (TL1 setting)', stage, row['limit_minutes'],
                              'minutes', 'limit', 'known', [], settings_evidence, [], tl1, cohort,
                              observed_at=settings_read_at or read_at, gap=cohort_gap or settings_gap))
        mine = [w for w in bench['waits'] if w['stage'] == stage]
        evidence = collection + [links[w[n]] for w in mine for n in ('start', 'end') if w[n]]
        metrics.append(metric('intervals:' + stage, f'{name} intervals (denominator)', stage, row['intervals'],
                              'count', 'count', 'partial', [ident(w['key']) for w in mine], evidence,
                              [HISTORY], tl2, cohort, expected=None, gap=cohort_gap))
        for result, count in row['results'].items():
            ids = [ident(w['key']) for w in mine if w['result'] == result]
            suite.require(count == len(ids), 'TL2 result count disagrees with its waits')
            metrics.append(metric(f'{result.replace(" ", "-")}:{stage}', f'{name} {result}', stage, count,
                                  'count', 'count', 'partial', ids, evidence, [HISTORY], tl2, cohort,
                                  expected=None, gap=cohort_gap))
    missed = []
    for w in bench['waits']:
        i, key, stage = intervals[w['key']], ident(w['key']), w['stage']
        ticket = w['tickets'][0] if len(w['tickets']) == 1 else None
        evidence = [f'https://github.com/{repo}/issues/{t}' for t in w['tickets']]
        if w['pull_request'] is not None:
            evidence.append(f'https://github.com/{repo}/pull/{w["pull_request"]}')
        evidence += [links[s] for s in [w['start'], w['end'], *w['support']] if s]
        start = i['start']['at'] if i['start'] else None
        # Native span only: this interval's TL2 start to TL2's read.
        window = {'since': start, 'until': read_at, 'timezone': 'UTC'} if start and start < read_at else None
        exact_end = i['end'] and i['end']['at'] == i['end']['latest']
        interval = {'id': key, 'started_at': start,
                    'ended_at': i['end']['at'] if start and exact_end else None}
        result, gaps = w['result'], [f'TL2 {w["result"]}: {g}' for g in w['gaps']]
        if result in ('unknown', 'gated', 'stale'):
            state, value = 'unavailable', None
        elif i['end'] is None:
            state, value = 'partial', w['wait_range_minutes'][0]
            gaps.append('Open at the TL2 read: the wait is a lower bound measured to its read time.')
        elif w['wait_minutes'] is None:
            state, value = 'partial', w['wait_range_minutes'][0]
            gaps.append('Edited end record: the wait lies between {} and {} minutes.'.format(*w['wait_range_minutes']))
        else:
            state, value = 'known', w['wait_minutes']
        metrics.append(metric('wait:' + key, f'{NAMES[stage]} wait: {result}', stage, value, 'minutes',
                              'observation', state, [key], evidence, gaps, tl2, window, ticket=ticket, interval=interval))
        if result == 'missed':
            missed.append(w['key'])
            metrics.append(metric('miss:' + key, f'Ticket miss: {NAMES[stage]} over its {w["limit_minutes"]}-minute limit',
                                  stage, 1, 'count', 'count', state,
                                  [key], evidence, gaps, tl2, window, ticket=ticket, interval=interval))
            if ticket is None:
                # A shared PR wait is one miss. Each linked ticket gets a
                # non-counting reference, never a second miss or an owner.
                for t in w['tickets']:
                    note = (f'Shared by {len(w["tickets"])} tickets: counted once on miss:{key}; '
                            'this ticket reference adds no miss.')
                    metrics.append(metric(f'miss-ticket:{key}:t{t}', f'Ticket reference for a shared {NAMES[stage]} miss',
                                          stage, None, 'count', 'count', 'partial', [key],
                                          evidence, gaps + [note], tl2, window, ticket=t, interval=interval,
                                          expected=None))
    # One miss per TL2 key, never a second one from another read of the same interval.
    suite.require(missed == bench['misses'] and len(set(missed)) == len(missed), 'TL2 misses disagree')
    state = 'partial' if any(m['state'] != 'unavailable' for m in metrics) else 'unavailable'
    return {'slot': SLOT, 'state': state, 'metrics': metrics,
            'prerequisites': list(dict.fromkeys([HISTORY] + [p for m in metrics for p in m['prerequisites']]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--at', required=True, help='explicit UTC assembly time; no clock is read')
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--journey', required=True)
    parser.add_argument('--sidecar', required=True)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--settings-evidence', required=True, action='append')
    parser.add_argument('--cohort-since', help="UTC start of the caller's ticket selection; TL2 chooses none")
    parser.add_argument('--settings-read-at', help='UTC time the caller read the settings file')
    args = parser.parse_args()
    try:
        at = suite._time(args.at)
        for value in (args.cohort_since, args.settings_read_at):
            if value is not None:
                suite._time(value)
        sample = at.replace(minute=at.minute // 5 * 5, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')
        provider = project(sample, root=args.root, journey=args.journey, sidecar=args.sidecar,
                           settings=args.settings, settings_evidence=args.settings_evidence,
                           assembled_at=args.at, cohort_since=args.cohort_since,
                           settings_read_at=args.settings_read_at)
    except ValueError:
        print('stage_waits: invalid arguments', file=sys.stderr)
        return 2
    print(json.dumps(provider, sort_keys=True, separators=(',', ':'), allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
