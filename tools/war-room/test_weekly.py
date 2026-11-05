#!/usr/bin/env python3
"""WR7 weekly report proof over retained suite history. Synthetic, virtual time.

Every history here is generated: one complete `openwiz.war-room.v1` record per
five-minute boundary, each carrying a WR3-shaped `stage_waits` provider. Each
completed native interval is repeated in every later snapshot, as WR3 repeats
it, so deduplication is exercised by every case. Expected waits are literal
minutes in WAITS (never computed by the report):

  builder_start  previous 10, 12, 14 (median 12, p90 14); latest 6, 8, 9 (median 8)
  merge          previous 5, 5, 7 (median 5);             latest 9, 11, 13 (median 11)

Report end 2030-03-15T08:00:00Z is the latest complete fixed-PST day before
AT; the cohorts are [03-01T08:00Z, 03-08T08:00Z) and [03-08T08:00Z, 03-15T08:00Z),
2016 expected samples each. All ids, links, hashes and paths are synthetic.
"""
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIXTURES = HERE / 'fixtures' / 'weekly'
TL2_FIXTURE = HERE.parents[1] / 'tools/factory-metrics/fixtures/stage-waits'
sys.path.insert(0, str(HERE))
import history  # noqa: E402
import sources  # noqa: E402
import suite  # noqa: E402


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


AT = '2030-03-15T09:30:00Z'
END = '2030-03-15T08:00:00Z'
PREVIOUS = ('2030-03-01T08:00:00Z', '2030-03-08T08:00:00Z')
LATEST = ('2030-03-08T08:00:00Z', END)
PST = 'PST-fixed-UTC-08:00'
COHORT_SINCE = '2030-03-01T00:00:00Z'
REPO = 'https://github.com/example/factory'
TL2 = {'path': 'synthetic/stage-waits.json', 'schema': 'closedwiz.journey.stage-waits.v1', 'sha256': 'e' * 64}
TL1 = {'path': 'synthetic/limits.conf', 'schema': 'closedwiz.factory-limits.v1', 'sha256': 'f' * 64}
HISTORY_NOTE = 'TL2 #2337 history is unknown: synthetic counts are those the collection still shows.'
LIMITS = {'builder_start': 10, 'merge': 5}
# (stage, TL2 key, start, end, literal minutes, ticket)
WAITS = [
    ('builder_start', 'builder_start:t5101', '2030-03-02T09:00:00Z', '2030-03-02T09:10:00Z', 10.0, 5101),
    ('builder_start', 'builder_start:t5102', '2030-03-04T10:00:00Z', '2030-03-04T10:12:00Z', 12.0, 5102),
    ('builder_start', 'builder_start:t5103', '2030-03-06T11:00:00Z', '2030-03-06T11:14:00Z', 14.0, 5103),
    ('builder_start', 'builder_start:t5201', '2030-03-09T09:00:00Z', '2030-03-09T09:06:00Z', 6.0, 5201),
    ('builder_start', 'builder_start:t5202', '2030-03-11T10:00:00Z', '2030-03-11T10:08:00Z', 8.0, 5202),
    ('builder_start', 'builder_start:t5203', '2030-03-13T11:00:00Z', '2030-03-13T11:09:00Z', 9.0, 5203),
    ('merge', 'merge:p5401:c7101', '2030-03-02T12:00:00Z', '2030-03-02T12:05:00Z', 5.0, 5101),
    ('merge', 'merge:p5402:c7102', '2030-03-04T12:00:00Z', '2030-03-04T12:05:00Z', 5.0, 5102),
    ('merge', 'merge:p5403:c7103', '2030-03-06T12:00:00Z', '2030-03-06T12:07:00Z', 7.0, 5103),
    ('merge', 'merge:p5501:c7201', '2030-03-09T12:00:00Z', '2030-03-09T12:09:00Z', 9.0, 5201),
    ('merge', 'merge:p5502:c7202', '2030-03-11T12:00:00Z', '2030-03-11T12:11:00Z', 11.0, 5202),
    ('merge', 'merge:p5503:c7203', '2030-03-13T12:00:00Z', '2030-03-13T12:13:00Z', 13.0, 5203),
]


def t(value):
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def iso(value):
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')


def boundaries(since=PREVIOUS[0], until=END):
    at, end = t(since), t(until)
    while at < end:
        yield iso(at)
        at += timedelta(minutes=5)


def metric(id, stage, state, value, unit, statistic, window, observed_at, source, evidence, *,
           ids=(), expected='same', interval=None, ticket=None, prerequisites=()):
    return {'id': id, 'group': 'stage_waits', 'label': id, 'state': state, 'value': value,
            'unit': unit, 'native_unit': unit, 'statistic': statistic, 'window': window,
            'observed_at': observed_at, 'fresh_until': None, 'freshness': 'unknown',
            'source': source, 'evidence': evidence,
            'sample': {'observed': len(ids), 'expected': len(ids) if expected == 'same' else expected,
                       'identities': list(ids), 'numerator': None, 'denominator': None},
            'dimensions': {'direction': None, 'pool': None, 'stage': stage, 'ticket': ticket,
                           'cohort': 'tl2-stage-waits'},
            'interval': interval, 'prerequisites': [] if state == 'known' else list(prerequisites)}


def stage_provider(at, waits=WAITS, limits=LIMITS, *, tl2=TL2, cohort_since=COHORT_SINCE,
                   open_ends=(), unknown=(), stages=None):
    """A WR3-shaped provider as read at `at` (TL2's read is the sample boundary)."""
    metrics = []
    for stage in stages or sorted({w[0] for w in waits} | set(limits)):
        seen = [w for w in waits if w[0] == stage and w[2] < at]
        span = {'since': cohort_since, 'until': at, 'timezone': 'UTC'}
        if stage in limits:
            metrics.append(metric('limit:' + stage, stage, 'known', limits[stage], 'minutes', 'limit', span,
                                  at, TL1, [REPO + '/commit/' + 'c' * 40]))
        evidence = [f'{REPO}/issues/{w[5]}' for w in seen] or [REPO + '/issues/5000']
        metrics.append(metric('intervals:' + stage, stage, 'partial', len(seen), 'count', 'count', span, at, tl2,
                              sorted(set(evidence)), ids=[w[1] for w in seen], expected=None,
                              prerequisites=[HISTORY_NOTE]))
        for _, key, start, end, minutes, ticket in seen:
            window = {'since': start, 'until': at, 'timezone': 'UTC'}
            links = [f'{REPO}/issues/{ticket}', f'{REPO}/issues/{ticket}#issuecomment-{ticket}1']
            if key in unknown:
                metrics.append(metric('wait:' + key, stage, 'unavailable', None, 'minutes', 'observation', window,
                                      at, tl2, links, ids=[key], ticket=ticket,
                                      interval={'id': key, 'started_at': start, 'ended_at': None},
                                      prerequisites=['TL2 gated: held']))
            elif end <= at and key not in open_ends:
                metrics.append(metric('wait:' + key, stage, 'known', minutes, 'minutes', 'observation', window,
                                      at, tl2, links, ids=[key], ticket=ticket,
                                      interval={'id': key, 'started_at': start, 'ended_at': end}))
            else:
                lower = (t(at) - t(start)).total_seconds() / 60
                metrics.append(metric('wait:' + key, stage, 'partial', lower, 'minutes', 'observation', window,
                                      at, tl2, links, ids=[key], ticket=ticket,
                                      interval={'id': key, 'started_at': start, 'ended_at': None},
                                      prerequisites=['Open at the TL2 read: the wait is a lower bound.']))
    return {'slot': 'stage_waits', 'state': 'partial', 'metrics': metrics, 'prerequisites': [HISTORY_NOTE]}


def records(*, drop=(), refused=(), vary=None, since=PREVIOUS[0], until=END):
    """One validated record per boundary. `vary(at)` returns stage_provider kwargs."""
    out = []
    for at in boundaries(since, until):
        if at in drop:
            continue  # Interrupted sampling: the boundary is simply absent.
        mine = None if at in refused else stage_provider(at, **(vary(at) if vary else {}))
        # The report validates every record itself; compose's checks are proved by WR1.
        out.append({'schema': 'openwiz.war-room.v1', 'sample_id': at, 'sample_at': at, 'assembled_at': at,
                    'groups': suite.GROUPS, 'providers': [
                        mine if mine and d['slot'] == 'stage_waits' else
                        {'slot': d['slot'], 'state': 'unavailable', 'prerequisites': d['prerequisites'],
                         'metrics': []} for d in suite.PROVIDERS]})
    return out


CHANGES = json.loads((FIXTURES / 'changes.json').read_text()) if (FIXTURES / 'changes.json').exists() else None


class Weekly(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.weekly = module('weekly')
        cls.complete = records()

    def report(self, history=None, changes=()):
        return self.weekly.report(self.complete if history is None else history, AT, changes=changes)

    def stage(self, result, name):
        return next(s for s in result['stages'] if s['stage'] == name)

    def week(self, row, name):
        return next(w for w in row['weeks'] if w['name'] == name)

    # AC1: two complete synthetic weeks, independently checked per-stage changes.
    def test_complete_weeks_report_literal_stage_changes(self):
        r = self.report(changes=CHANGES)
        self.assertEqual('openwiz.war-room.weekly.v1', r['schema'])
        self.assertEqual([('previous', *PREVIOUS, PST), ('latest', *LATEST, PST)],
                         [(w['name'], w['window']['since'], w['window']['until'], w['window']['timezone'])
                          for w in r['weeks']])
        for w in r['weeks']:
            self.assertEqual({'observed': 2016, 'expected': 2016, 'missing': 0, 'gaps': []}, w['samples'])
            self.assertEqual(7, len(w['days']))
            self.assertEqual([(288, 288, PST)] * 7, [(d['observed'], d['expected'], d['window']['timezone'])
                                                      for d in w['days']])
        b, m = self.stage(r, 'builder_start'), self.stage(r, 'merge')
        self.assertEqual(('faster', []), (b['change'], b['reasons']))
        self.assertEqual(('slower', []), (m['change'], m['reasons']))
        prev, last = self.week(b, 'previous'), self.week(b, 'latest')
        self.assertEqual((3, 12.0, 14.0), (prev['waits']['n'], prev['waits']['median'], prev['waits']['p90']))
        self.assertEqual((3, 8.0, 9.0), (last['waits']['n'], last['waits']['median'], last['waits']['p90']))
        self.assertEqual((3, 5.0, 11.0), (self.week(m, 'previous')['waits']['n'],
                                         self.week(m, 'previous')['waits']['median'],
                                         self.week(m, 'latest')['waits']['median']))
        self.assertEqual({'completed': 3, 'open': 0, 'unknown': 0, 'conflicting': 0, 'expected': None},
                         prev['intervals'])
        self.assertEqual({'observed': 2016, 'expected': 2016}, prev['stage_samples'])
        self.assertEqual([{'value': 10, 'unit': 'minutes', 'schema': TL1['schema']}], prev['limits'])
        # The source's own window label survives; WR7 never relabels it as a PST day.
        self.assertEqual([{'since': COHORT_SINCE, 'timezone': 'UTC'}], prev['source_windows'])
        self.assertIn(HISTORY_NOTE, b['limitations'])

    def test_recorded_changes_keep_source_links_and_claim_no_cause(self):
        r = self.report(changes=CHANGES)
        recorded = [c for c in r['changes'] if c['kind'] == 'recorded']
        self.assertEqual([('2030-03-08T15:00:00Z', 'latest', ['https://github.com/example/factory/pull/5301'])],
                         [(c['at'], c['week'], c['evidence']) for c in recorded])
        self.assertEqual(1, r['excluded_changes'])  # The fixture's out-of-window note is not shown as weekly.
        self.assertIn('Temporal association only: no recorded change is claimed as the cause of a stage change.',
                      r['notes'])
        for c in r['changes']:
            self.assertEqual('temporal only', c['association'])

    def test_bad_recorded_changes_refuse(self):
        good = {'at': '2030-03-09T00:00:00Z', 'label': 'Synthetic change', 'evidence': [REPO + '/pull/5301']}
        bad = [dict(good, extra=1), {k: v for k, v in good.items() if k != 'evidence'}, dict(good, evidence=[]),
               dict(good, evidence=['https://example.com/x']), dict(good, at='2030-03-09'),
               dict(good, label=''), dict(good, label='see ' + 'thr' + '_abc123def'), dict(good, label=7),
               dict(good, label='token ghp_' + 'a' * 36),
               # sources.safe_record's retained-history credential shapes, synthetic: a label the
               # LABEL characters admit, and GitHub organization/repository components LINK admits.
               dict(good, label='sk-' + 'a' * 40),
               dict(good, evidence=['https://github.com/ghp_' + 'a' * 36 + '/factory/pull/5301']),
               dict(good, evidence=['https://github.com/example/sk-' + 'a' * 40 + '/pull/5301']),
               dict(good, evidence=['https://github.com/example/github_pat_' + 'a' * 22 + '/issues/5301']),
               dict(good, evidence=['https://github.com/' + 'thr' + '_abc123def/factory/pull/5301'])]
        self.weekly.report(self.complete[:1], AT, changes=[good])
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.weekly.report(self.complete[:1], AT, changes=[change])

    # #2718: one named credential pattern, sources.CREDENTIAL, behind both guards. Each synthetic
    # shape rides in a carrier the other checks admit (a metric label for safe_record; a change
    # label, or a GitHub organization component LINK admits, for weekly), so only the credential
    # guard can refuse it. The privacy checker alone misses all but the thread id.
    def test_safe_record_and_weekly_refuse_the_same_credential_shapes(self):
        refused = [('label', 'sk-' + 'a' * 40), ('org', 'ghp_' + 'a' * 36), ('org', 'gho_' + 'a' * 8),
                   ('org', 'github_pat_' + 'a' * 22), ('label', 'Authorization: synthetic'),
                   ('label', 'bearer synthetic'), ('label', '-----BEGIN PRIVATE KEY'),
                   ('org', 'thr' + '_abc123def')]
        accepted = [('label', 'sk-' + 'abc')]  # Below the eight-character floor: both guards admit it.

        def record(text):
            out = json.loads(json.dumps(self.complete[0]))
            next(p for p in out['providers'] if p['slot'] == 'stage_waits')['metrics'][0]['label'] = text
            return out

        def change(carrier, text):
            change = {'at': '2030-03-09T00:00:00Z', 'label': 'Synthetic change', 'evidence': [REPO + '/pull/5301']}
            if carrier == 'label':
                return dict(change, label=text)
            return dict(change, evidence=[f'https://github.com/{text}/factory/pull/5301'])

        for carrier, text in refused:
            with self.subTest(text=text):
                self.assertIsNotNone(sources.CREDENTIAL.search(text))
                with self.assertRaisesRegex(ValueError, 'private payload refused'):
                    sources.safe_record(record(text))
                with self.assertRaisesRegex(ValueError, 'private recorded change refused'):
                    self.weekly.report(self.complete[:1], AT, changes=[change(carrier, text)])
        for carrier, text in accepted:
            with self.subTest(text=text):
                self.assertIsNone(sources.CREDENTIAL.search(text))
                sources.safe_record(record(text))
                self.weekly.report(self.complete[:1], AT, changes=[change(carrier, text)])

    # AC2: repeated snapshots count once.
    def test_repeated_snapshots_are_one_interval(self):
        # Every completed wait is repeated in each later snapshot (thousands of times).
        seen = sum(1 for rec in self.complete for p in rec['providers'] if p['slot'] == 'stage_waits'
                   for m in p['metrics'] if m['id'] == 'wait:builder_start:t5101')
        self.assertGreater(seen, 3000)
        r = self.report(self.complete + self.complete[:10])  # Identical duplicate records are idempotent.
        self.assertEqual(3, self.week(self.stage(r, 'builder_start'), 'previous')['waits']['n'])
        self.assertEqual(2016, r['weeks'][0]['samples']['observed'])

    def test_differing_duplicate_sample_refuses(self):
        other = suite.compose(self.complete[5]['sample_at'], [], assembled_at=self.complete[5]['assembled_at'])
        with self.assertRaises(ValueError):
            self.report(self.complete + [other])

    def test_conflicting_snapshots_of_one_interval_are_unknown(self):
        def vary(at):
            if at >= '2030-03-10T00:00:00Z':  # A later read reports a different completed wait.
                return {'waits': [w if w[1] != 'builder_start:t5101' else (*w[:4], 99.0, w[5]) for w in WAITS]}
            return {}
        b = self.stage(self.report(records(vary=vary)), 'builder_start')
        self.assertEqual('unknown', b['change'])
        self.assertEqual(1, self.week(b, 'latest')['intervals']['conflicting'])
        self.assertEqual(2, self.week(b, 'previous')['waits']['n'])
        self.assertIn('conflicting snapshots of one interval', ' '.join(b['reasons']))

    # AC2: interrupted sampling and missing history stay partial/Unknown.
    def test_interrupted_sampling_is_a_gap_not_a_change(self):
        gap = set(boundaries('2030-03-12T03:00:00Z', '2030-03-12T04:00:00Z'))
        r = self.report(records(drop=gap))
        self.assertEqual({'observed': 2004, 'expected': 2016, 'missing': 12,
                          'gaps': [{'since': '2030-03-12T03:00:00Z', 'until': '2030-03-12T04:00:00Z'}]},
                         r['weeks'][1]['samples'])
        self.assertEqual(276, r['weeks'][1]['days'][3]['observed'])
        for name in ('builder_start', 'merge'):
            s = self.stage(r, name)
            self.assertEqual('unknown', s['change'])
            self.assertIn('latest week: 12 of 2016 samples missing', s['reasons'])
        # The observations are still shown, with their sample sizes.
        self.assertEqual(3, self.week(self.stage(r, 'builder_start'), 'latest')['waits']['n'])

    def test_missing_history_week_is_unknown(self):
        latest_only = [r for r in self.complete if r['sample_at'] >= LATEST[0]]
        r = self.report(latest_only)
        self.assertEqual({'observed': 0, 'expected': 2016, 'missing': 2016,
                          'gaps': [{'since': PREVIOUS[0], 'until': PREVIOUS[1]}]}, r['weeks'][0]['samples'])
        b = self.stage(r, 'builder_start')
        self.assertEqual('unknown', b['change'])
        self.assertIn('previous week: 2016 of 2016 samples missing', b['reasons'])
        # Waits that ended in the unsampled week are still read once, by their source end,
        # from later retained snapshots; the week itself stays a gap.
        self.assertEqual(3, self.week(b, 'previous')['waits']['n'])
        empty = self.report([])
        self.assertEqual([], empty['stages'])
        self.assertEqual([2016, 2016], [w['samples']['missing'] for w in empty['weeks']])

    def test_refused_stage_slot_is_a_stage_gap(self):
        refused = set(boundaries('2030-03-02T00:00:00Z', '2030-03-02T00:30:00Z'))
        r = self.report(records(refused=refused))
        self.assertEqual(2016, r['weeks'][0]['samples']['observed'])
        b = self.stage(r, 'builder_start')
        self.assertEqual({'observed': 2010, 'expected': 2016}, self.week(b, 'previous')['stage_samples'])
        self.assertEqual('unknown', b['change'])
        self.assertIn('previous week: stage data missing in 6 of 2016 samples', b['reasons'])

    # AC2: changed limits or basis never produce a speedup.
    def test_changed_limit_is_a_recorded_change_and_noncomparable(self):
        switch = '2030-03-10T00:00:00Z'
        r = self.report(records(vary=lambda at: {'limits': dict(LIMITS, builder_start=20)} if at >= switch else {}))
        b = self.stage(r, 'builder_start')
        self.assertEqual('unknown', b['change'])
        self.assertIn('latest week: limit changed within the week', b['reasons'])
        self.assertEqual([{'value': 10, 'unit': 'minutes', 'schema': TL1['schema']},
                          {'value': 20, 'unit': 'minutes', 'schema': TL1['schema']}],
                         self.week(b, 'latest')['limits'])
        self.assertEqual('slower', self.stage(r, 'merge')['change'])  # Other stages keep their own basis.
        limit = [c for c in r['changes'] if c['kind'] == 'limit']
        self.assertEqual([(switch, 'latest', 'builder_start', 10, 20)],
                         [(c['at'], c['week'], c['stage'], c['from'], c['to']) for c in limit])
        self.assertEqual([REPO + '/commit/' + 'c' * 40], limit[0]['evidence'])

    def test_limit_differing_between_weeks_is_noncomparable(self):
        r = self.report(records(vary=lambda at: {'limits': dict(LIMITS, merge=8)} if at >= LATEST[0] else {}))
        m = self.stage(r, 'merge')
        self.assertEqual('unknown', m['change'])
        self.assertIn('limits differ between the weeks', m['reasons'])

    def test_changed_source_basis_or_window_is_noncomparable(self):
        schema = dict(TL2, schema='closedwiz.journey.stage-waits.v2')
        for vary, reason in [
                (lambda at: {'tl2': schema} if at >= LATEST[0] else {}, 'basis differs between the weeks'),
                (lambda at: {'cohort_since': '2030-03-05T00:00:00Z'} if at >= '2030-03-05T00:05:00Z' else {},
                 'previous week: source window changed within the week')]:
            with self.subTest(reason=reason):
                r = self.report(records(vary=vary))
                b = self.stage(r, 'builder_start')
                self.assertEqual('unknown', b['change'])
                self.assertIn(reason, b['reasons'])
        # #2498: the derived source-window note keeps the links of the intervals read that changed it
        # (t5101 and t5102 had started by 03-05T00:05Z), and Markdown prints them, not 'no link'.
        r = self.report(records(vary=lambda at: {'cohort_since': '2030-03-05T00:00:00Z'}
                                if at >= '2030-03-05T00:05:00Z' else {}))
        notes = [c for c in r['changes'] if c['kind'] == 'source_window' and c['stage'] == 'builder_start']
        self.assertEqual([('2030-03-05T00:05:00Z', [REPO + '/issues/5101', REPO + '/issues/5102'])],
                         [(c['at'], c['evidence']) for c in notes])
        self.assertIn(f'2030-03-05T00:05:00Z (previous week): builder_start source_window: '
                      f'{{\'since\': \'{COHORT_SINCE}\', \'timezone\': \'UTC\'}} -> '
                      f'{{\'since\': \'2030-03-05T00:00:00Z\', \'timezone\': \'UTC\'}}; '
                      f'{REPO}/issues/5101, {REPO}/issues/5102\n', self.weekly.markdown(r))

    # AC2: thin cohorts and open/unknown waits.
    def test_thin_cohort_is_unknown(self):
        thin = [w for w in WAITS if w[1] != 'builder_start:t5203']
        b = self.stage(self.report(records(vary=lambda at: {'waits': thin})), 'builder_start')
        self.assertEqual(2, self.week(b, 'latest')['waits']['n'])
        self.assertEqual('unknown', b['change'])
        self.assertIn('latest week: thin cohort, 2 completed waits (n < 3, the ci-bench thin rule)', b['reasons'])

    def test_open_and_unknown_waits_are_separate_never_zero(self):
        extra = WAITS + [('builder_start', 'builder_start:t5204', '2030-03-14T20:00:00Z', '2030-03-16T00:00:00Z',
                          100.0, 5204),
                         ('builder_start', 'builder_start:t5205', '2030-03-14T21:00:00Z', '2030-03-14T21:01:00Z',
                          1.0, 5205)]
        vary = lambda at: {'waits': extra, 'unknown': ('builder_start:t5205',)}  # noqa: E731
        r = self.report(records(vary=vary))
        # Still open or unknown in the closing 08:00 snapshot: the same ids, in the same week.
        self.assertEqual(r, self.report(records(vary=vary, until='2030-03-15T08:05:00Z')))
        b = self.stage(r, 'builder_start')
        last = self.week(b, 'latest')
        self.assertEqual({'completed': 3, 'open': 1, 'unknown': 1, 'conflicting': 0, 'expected': None},
                         last['intervals'])
        self.assertEqual((3, 8.0), (last['waits']['n'], last['waits']['median']))  # No zero, no 1-minute value.
        self.assertEqual(['builder_start:t5204'], last['open_ids'])
        self.assertEqual(['builder_start:t5205'], last['unknown_ids'])
        self.assertEqual('unknown', b['change'])
        self.assertIn('latest week: 1 open (censored) waits', b['reasons'])
        self.assertIn('latest week: 1 waits with unknown endpoints', b['reasons'])

    def test_edited_end_is_an_unknown_endpoint_with_its_explanation(self):
        # #2497: WR3 projects an ended wait whose edited end record lies 09:10-09:12 (10 to 12 minutes,
        # within a 15-minute limit) as partial. It is no open wait: its endpoint is uncertain, and the
        # producer's explanation stays in the stage's limitations.
        b = self.stage(self.wr3_report(builder_start=15, edited_end='2030-03-01T09:12:00Z'), 'builder_start')
        latest = self.week(b, 'latest')
        # TL2's fixture also holds t4303 open at its read and t4302, t4304 with unknown results.
        self.assertEqual({'completed': 0, 'open': 1, 'unknown': 3, 'conflicting': 0, 'expected': None},
                         latest['intervals'])
        self.assertEqual(['builder_start:t4303'], latest['open_ids'])
        self.assertEqual(['builder_start:t4301', 'builder_start:t4302', 'builder_start:t4304'],
                         latest['unknown_ids'])
        self.assertEqual(0, latest['waits']['n'])  # Its 10-minute lower bound is no completed value.
        self.assertIn('Edited end record: the wait lies between 10.0 and 12.0 minutes.', b['limitations'])
        self.assertEqual('unknown', b['change'])
        self.assertIn('latest week: 1 open (censored) waits', b['reasons'])
        self.assertIn('latest week: 3 waits with unknown endpoints', b['reasons'])

    def test_wait_assigned_by_its_source_end(self):
        # Starts in the previous week, ends in the latest: one latest-week observation.
        across = WAITS + [('merge', 'merge:p5504:c7204', '2030-03-08T07:58:00Z', '2030-03-08T08:01:00Z', 3.0, 5204)]
        m = self.stage(self.report(records(vary=lambda at: {'waits': across})), 'merge')
        self.assertEqual((3, 4), (self.week(m, 'previous')['waits']['n'], self.week(m, 'latest')['waits']['n']))

    def test_wait_first_seen_completed_at_the_closing_boundary_counts_by_its_end(self):
        # Latest builder_start waits 11, 13, 14, plus three 3-minute waits 07:56 -> 07:59 on 03-15 that
        # first appear (completed) in the 08:00 snapshot: latest is 3, 3, 3, 11, 13, 14 (median 7), faster.
        late = [w for w in WAITS if w[0] != 'builder_start' or w[2] < LATEST[0]] + [
            ('builder_start', 'builder_start:t5211', '2030-03-09T09:00:00Z', '2030-03-09T09:11:00Z', 11.0, 5211),
            ('builder_start', 'builder_start:t5212', '2030-03-11T10:00:00Z', '2030-03-11T10:13:00Z', 13.0, 5212),
            ('builder_start', 'builder_start:t5213', '2030-03-13T11:00:00Z', '2030-03-13T11:14:00Z', 14.0, 5213),
            *(('builder_start', f'builder_start:t522{k}', '2030-03-15T07:56:00Z', '2030-03-15T07:59:00Z', 3.0,
               5220 + k) for k in range(3))]
        history = records(vary=lambda at: {'waits': late}, until='2030-03-15T08:05:00Z')
        self.assertEqual(4033, len(history))
        b = self.stage(self.report(history), 'builder_start')
        last = self.week(b, 'latest')
        self.assertEqual((6, 7.0), (last['waits']['n'], last['waits']['median']))
        self.assertEqual(('faster', []), (b['change'], b['reasons']))
        self.assertEqual({'observed': 2016, 'expected': 2016}, last['stage_samples'])
        # The basis guard still holds: a boundary read on another source schema is noncomparable.
        v2 = dict(TL2, schema='closedwiz.journey.stage-waits.v2')
        switched = records(vary=lambda at: {'waits': late, **({'tl2': v2} if at == END else {})},
                           until='2030-03-15T08:05:00Z')
        b = self.stage(self.report(switched), 'builder_start')
        self.assertEqual('unknown', b['change'])
        self.assertIn('latest week: basis changed within the week', b['reasons'])
        # #2655: an id seen earlier in-window keeps its boundary read's basis. t5299 (07:51 -> 07:59, 8 minutes)
        # is open at 07:55 and completes in the 08:00 read; latest is 6, 8, 8, 9 (median 8). An id already
        # completed and repeated unchanged at 08:00 (WAITS alone) keeps it too.
        crossing = WAITS + [('builder_start', 'builder_start:t5299', '2030-03-15T07:51:00Z', '2030-03-15T07:59:00Z',
                             8.0, 5299)]
        for waits, tl2, n, change in ((crossing, TL2, 4, 'faster'), (crossing, v2, 4, 'unknown'),
                                      (WAITS, v2, 3, 'unknown')):
            history = records(vary=lambda at: {'waits': waits, **({'tl2': tl2} if at == END else {})},
                              until='2030-03-15T08:05:00Z')
            b = self.stage(self.report(history), 'builder_start')
            last = self.week(b, 'latest')
            self.assertEqual((n, 8.0, []), (last['waits']['n'], last['waits']['median'], last['open_ids']))
            self.assertEqual({'observed': 2016, 'expected': 2016}, last['stage_samples'])
            self.assertEqual(change, b['change'])
            if tl2 is v2:
                self.assertIn('latest week: basis changed within the week', b['reasons'])
        # #2656: a stage first read at the closing boundary still keeps its completed waits by source end.
        # Every in-window stage provider is unavailable (or the boundary snapshot is the only one), so the
        # 08:00 read alone carries the 12 WAITS: per stage, previous and latest n=3, never counted as coverage.
        refused = set(boundaries())
        for history, observed in ((records(refused=refused, until='2030-03-15T08:05:00Z'), 2016),
                                  (records(since=END, until='2030-03-15T08:05:00Z'), 0)):
            r = self.report(history)
            self.assertEqual([observed, observed], [w['samples']['observed'] for w in r['weeks']])
            self.assertEqual(['builder_start', 'merge'], [s['stage'] for s in r['stages']])
            for name, medians in (('builder_start', (12.0, 8.0)), ('merge', (5.0, 11.0))):
                row = self.stage(r, name)
                self.assertEqual('unknown', row['change'])
                self.assertEqual(medians, tuple(self.week(row, w)['waits']['median'] for w in ('previous', 'latest')))
                for week in ('previous', 'latest'):
                    w = self.week(row, week)
                    self.assertEqual((3, {'observed': 0, 'expected': 2016}), (w['waits']['n'], w['stage_samples']))
                    self.assertIn(f'{week} week: stage data missing in 2016 of 2016 samples' if observed
                                  else f'{week} week: 2016 of 2016 samples missing', row['reasons'])

    # AC3: fixed-PST boundaries, labels and read-only operation.
    def test_end_is_the_latest_complete_fixed_pst_day(self):
        self.assertEqual(END, self.weekly.report([], '2030-03-15T08:00:00Z')['end'])
        self.assertEqual('2030-03-14T08:00:00Z', self.weekly.report([], '2030-03-15T07:59:59Z')['end'])
        r = self.weekly.report([], AT)
        self.assertEqual(('2030-03-01T08:00:00Z', '2030-03-02T08:00:00Z', PST),
                         tuple(r['weeks'][0]['days'][0]['window'].values()))
        with self.assertRaises(ValueError):
            self.weekly.report([], '2030-03-15 09:30')

    def test_samples_after_the_end_are_not_read(self):
        later = records(since=END, until='2030-03-15T09:00:00Z')
        self.assertEqual(self.report(), self.report(self.complete + later))

    def wr3_report(self, builder_start=10, edited_end=None):
        """The weekly report over one real WR3 projection of TL2's fixture.

        `edited_end` makes builder_start t4301's end record (09:10) edited, last
        changed at that time, as TL2 records an edited endpoint."""
        sw = module('stage_waits')
        root = Path(tempfile.mkdtemp(prefix='wr7-'))
        self.addCleanup(shutil.rmtree, root)
        doc = json.loads((TL2_FIXTURE / 'journeys.json').read_text(encoding='utf-8'))
        side = json.loads((TL2_FIXTURE / 'stage-waits.json').read_text(encoding='utf-8'))
        if edited_end is not None:
            event = next(e for t in doc['tickets'] if t['ticket'] == 4301 for e in t['events']
                         if e['kind'] == 'builder_start')
            event['completeness'] = 'edited'
            side['intervals'][0]['end']['latest'] = edited_end
            side['journey_hash'] = sw.producer.journey_hash(doc)
        (root / 'journeys.json').write_text(json.dumps(doc), encoding='utf-8')
        (root / 'stage-waits.json').write_text(json.dumps(side), encoding='utf-8')
        (root / 'limits.conf').write_text(f'builder_start={builder_start}\nreviewer_start=5\nmerge=5\n'
                                          'fix_after_changes=30\nbuilder_question_answer=15\n', encoding='ascii')
        at = '2030-03-01T12:05:00Z'
        provider = sw.project(at, root=root, journey='journeys.json', sidecar='stage-waits.json',
                              settings='limits.conf', settings_evidence=[REPO + '/commit/' + 'c' * 40],
                              assembled_at=at, cohort_since='2030-03-01T00:00:00Z',
                              settings_read_at='2030-03-01T12:04:00Z')
        return self.weekly.report([suite.compose(at, [provider], assembled_at=at)], '2030-03-02T08:00:00Z')

    def test_real_wr3_projection_is_read(self):
        r = self.wr3_report()
        b = self.stage(r, 'builder_start')
        latest = self.week(b, 'latest')
        # TL2's fixture: builder_start t4301 09:00 -> 09:10 = 10 minutes, its one measured builder start.
        self.assertEqual([{'value': 10.0, 'count': 1}], latest['waits']['histogram'])
        self.assertEqual([{'value': 10, 'unit': 'minutes', 'schema': 'closedwiz.factory-limits.v1'}],
                         latest['limits'])
        self.assertEqual('unknown', b['change'])

    def test_no_network_or_subprocess_while_reporting(self):
        def refuse(*args, **kwargs):
            raise AssertionError('WR7 must not open a socket or start a program')
        saved = socket.socket, subprocess.Popen
        socket.socket, subprocess.Popen = refuse, refuse
        try:
            self.report(changes=CHANGES)
        finally:
            socket.socket, subprocess.Popen = saved

    def test_cli_reads_history_and_writes_nothing(self):
        root = Path(tempfile.mkdtemp(prefix='wr7-history-'))
        self.addCleanup(shutil.rmtree, root)
        for record in self.complete[-24:]:
            history.save(root, record)
        before = sorted((p.relative_to(root), p.stat().st_mtime_ns) for p in root.rglob('*'))
        command = [sys.executable, '-I', str(HERE / 'weekly.py'), '--history', str(root), '--at', AT,
                   '--changes', str(FIXTURES / 'changes.json')]
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual((0, ''), (done.returncode, done.stderr))
        printed = json.loads(done.stdout)
        self.assertEqual(24, printed['weeks'][1]['samples']['observed'])
        self.assertEqual('unknown', self.stage(printed, 'builder_start')['change'])
        self.assertEqual(before, sorted((p.relative_to(root), p.stat().st_mtime_ns) for p in root.rglob('*')))
        markdown = subprocess.run(command + ['--format', 'markdown'], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, markdown.returncode)
        self.assertIn('fixed PST (UTC-08:00)', markdown.stdout)
        self.assertIn('https://github.com/example/factory/pull/5301', markdown.stdout)
        self.assertIn('not a cause', markdown.stdout)
        for args, code in [(['--at', AT], 2), (['--history', str(root), '--at', 'yesterday'], 2),
                           (['--history', str(root / 'absent'), '--at', AT], 0)]:
            with self.subTest(args=args):
                run = subprocess.run([sys.executable, '-I', str(HERE / 'weekly.py'), *args],
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(code, run.returncode, run.stderr)
        (root / 'samples' / '2030-03-15T07-55-00Z.json').write_text('{"schema": 1}')
        broken = subprocess.run(command, capture_output=True, text=True, timeout=60)
        self.assertEqual((1, ''), (broken.returncode, broken.stdout))
        self.assertEqual('weekly: unreadable or invalid input\n', broken.stderr)


if __name__ == '__main__':
    unittest.main()
