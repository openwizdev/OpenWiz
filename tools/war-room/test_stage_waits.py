#!/usr/bin/env python3
"""WR3 stage-wait proof at the producer-to-suite boundary. Synthetic only.

The producer inputs are TL2's own sanitized demonstration outputs
(tools/factory-metrics/fixtures/stage-waits/), checked by TL2's validator.
Expected waits are read off that fixture's literal endpoints, never computed by
the adapter: builder_start 09:00 -> 09:10 = 10, reviewer_start 10:00 -> 10:06 =
6 and 11:11 -> 11:15 = 4, merge 11:31 -> 11:36 = 5, fix_after_changes
10:30 -> 11:01 = 31, builder_question_answer 09:45 -> 10:01 = 16 minutes.
Only the TL1 settings file varies, so each stage is seen at, below and above
its limit without inventing a producer record.
"""
import hashlib
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
TL2 = HERE.parents[1] / 'tools/factory-metrics/fixtures/stage-waits'
sys.path.insert(0, str(HERE))
import main  # noqa: E402  (WR2's one tick: history + page)
import history  # noqa: E402
import page  # noqa: E402
import sources  # noqa: E402
import suite  # noqa: E402


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


AT = '2030-03-01T12:05:00Z'
EVIDENCE = ['https://github.com/example/factory/commit/' + 'c' * 40]
# The caller's established selection: its cohort start (TL2 names none) and when
# it read the settings, after TL2's 12:00 read. Synthetic assumptions.
SELECTION = {'cohort_since': '2030-03-01T00:00:00Z', 'settings_read_at': '2030-03-01T12:04:00Z'}
DEFAULTS = {'builder_start': 10, 'reviewer_start': 5, 'merge': 5,
            'fix_after_changes': 30, 'builder_question_answer': 15}
# One measured, ended fixture wait per stage (key, literal minutes).
MEASURED = {
    'builder_start': ('builder_start:t4301', 10.0),
    'reviewer_start': ('reviewer_start:p4401:' + '1a' * 20 + ':2030-03-01t10:00:00z', 6.0),
    'merge': ('merge:p4401:' + '2b' * 20 + ':c6205:2030-03-01t11:31:00z', 5.0),
    'fix_after_changes': ('fix_after_changes:p4401:' + '1a' * 20 + ':c6202', 31.0),
    'builder_question_answer': ('builder_question_answer:t4301:c6102', 16.0),
}
UNMEASURED = {  # TL2 key -> its documented Unknown/gated/stale gap
    'builder_start:t4302': 'start record outside its gate',
    'builder_start:t4304': 'label history incomplete',
    'builder_question_answer:t4302:c6302': 'edited record',
    'reviewer_start:p4402:' + '3c' * 20 + ':2030-03-01t08:20:00z': 'reviewer start unconfirmed',
    'reviewer_start:p4402:' + '5e' * 20 + ':2030-03-01t08:35:00z': 'no longer current',
    'reviewer_start:p4402:' + '4d' * 20 + ':2030-03-01t08:50:00z': 'held',
    'merge:p4402:' + '3c' * 20 + ':c6402:2030-03-01t08:23:00z': 'no longer current',
}


class StageWaits(unittest.TestCase):
    def setUp(self):
        self.adapter = module('stage_waits')
        self.root = Path(tempfile.mkdtemp(prefix='wr3-'))
        self.addCleanup(shutil.rmtree, self.root)
        for name in ('journeys.json', 'stage-waits.json'):
            shutil.copyfile(TL2 / name, self.root / name)
        self.settings(DEFAULTS)

    def settings(self, minutes, text=None):
        body = text if text is not None else ''.join(f'{k}={v}\n' for k, v in minutes.items())
        (self.root / 'limits.conf').write_text(body, encoding='ascii')

    def rewrite(self, change):
        """A producer-valid variant: edit both files, rebind TL2's journey hash."""
        doc = json.loads((self.root / 'journeys.json').read_text())
        side = json.loads((self.root / 'stage-waits.json').read_text())
        change(doc, side)
        side['journey_hash'] = self.adapter.producer.journey_hash(doc)
        self.adapter.producer.validate_stage_waits(side, doc)  # TL2 accepts it.
        (self.root / 'journeys.json').write_text(json.dumps(doc))
        (self.root / 'stage-waits.json').write_text(json.dumps(side))
        return self.adapter.producer.stage_bench(side, self.adapter.limits.read(self.root / 'limits.conf'))

    def provider(self, **selection):
        result = self.adapter.project(AT, root=self.root, journey='journeys.json',
                                      sidecar='stage-waits.json', settings='limits.conf',
                                      settings_evidence=EVIDENCE, **dict(SELECTION, **selection))
        record = suite.compose('2030-03-01T12:05:00Z', [result], assembled_at=AT)
        sources.safe_record(record)  # The page's own privacy/link guard.
        checked = suite.loads(json.dumps(record, allow_nan=False))
        return next(p for p in checked['providers'] if p['slot'] == 'stage_waits')

    def metrics(self, **selection):
        return {m['id']: m for m in self.provider(**selection)['metrics']}

    def test_r1_unanswered_changes_round_keeps_every_other_wait(self):
        def unanswered(doc, side):
            e = next(e for p in doc['pull_requests'] for e in p['events'] if e['kind'] == 'fix_round')
            e.update(at=None, source=None, completeness='unknown', answers=[])
            i = next(i for i in side['intervals'] if i['stage'] == 'fix_after_changes')
            i.update(end=None, support=[], state='open')
        bench = self.rewrite(unanswered)
        self.assertEqual(14, len(bench['waits']))
        p = self.provider()
        m = {x['id']: x for x in p['metrics']}
        self.assertEqual('partial', p['state'])
        self.assertEqual(14, sum(k.startswith('wait:') for k in m))
        fix = m['wait:' + MEASURED['fix_after_changes'][0]]
        self.assertEqual(('partial', None), (fix['state'], fix['interval']['ended_at']))
        self.assertEqual(('known', 30), (m['limit:fix_after_changes']['state'], m['limit:fix_after_changes']['value']))

    def test_r2_limits_carry_the_settings_read_not_the_tl2_read(self):
        self.settings(dict(DEFAULTS, merge=1))  # Edited after TL2's 12:00 read.
        m = self.metrics()
        self.assertEqual(('known', 1, '2030-03-01T12:04:00Z'),
                         (m['limit:merge']['state'], m['limit:merge']['value'], m['limit:merge']['observed_at']))
        self.assertEqual('2030-03-01T12:00:00Z', m['wait:' + MEASURED['merge'][0]]['observed_at'])
        for when, reason in ((None, 'settings read time'), ('2030-03-01T11:00:00Z', 'before')):
            with self.subTest(settings_read_at=when):
                limit = self.metrics(settings_read_at=when)['limit:merge']
                self.assertEqual(('unavailable', None), (limit['state'], limit['value']))
                self.assertTrue(any(reason in x for x in limit['prerequisites']), limit['prerequisites'])

    def test_r3_no_invented_cohort_window(self):
        m = self.metrics()
        self.assertEqual({'since': '2030-03-01T00:00:00Z', 'until': '2030-03-01T12:00:00Z', 'timezone': 'UTC'},
                         m['intervals:merge']['window'])
        # Each wait keeps only its own native span: its TL2 start to TL2's read.
        q = m['wait:' + MEASURED['builder_question_answer'][0]]
        self.assertEqual({'since': '2030-03-01T09:45:00Z', 'until': '2030-03-01T12:00:00Z', 'timezone': 'UTC'},
                         q['window'])
        for since in (None, '2030-03-01T09:00:00Z'):  # absent, or after a TL2 record
            with self.subTest(cohort_since=since):
                m = self.metrics(cohort_since=since)
                for key in ('intervals:merge', 'missed:reviewer_start', 'limit:merge'):
                    self.assertEqual(('unavailable', None, None),
                                     (m[key]['state'], m[key]['value'], m[key]['window']), key)
                    self.assertTrue(any('cohort window' in x for x in m[key]['prerequisites']), key)
                self.assertEqual(('known', 16.0), (m['wait:' + MEASURED['builder_question_answer'][0]]['state'],
                                                   m['wait:' + MEASURED['builder_question_answer'][0]]['value']))

    def test_r4_shared_pr_miss_counts_once_with_each_ticket_referenced(self):
        def shared(doc, side):
            pr = next(p for p in doc['pull_requests'] if p['number'] == 4401)
            pr['tickets'] = [4301, 4303]
            next(t for t in doc['tickets'] if t['ticket'] == 4303)['pull_requests'] = [4401]
            for i in side['intervals']:
                if i['pull_request'] == 4401:
                    i['tickets'] = [4301, 4303]
        self.rewrite(shared)
        m = self.metrics()
        for stage in ('reviewer_start', 'fix_after_changes'):
            key = MEASURED[stage][0]
            miss = m['miss:' + key]
            self.assertEqual((1, None), (miss['value'], miss['dimensions']['ticket']))
            for ticket in (4301, 4303):
                ref = m[f'miss-ticket:{key}:t{ticket}']
                self.assertEqual(('partial', None, ticket, miss['interval']),
                                 (ref['state'], ref['value'], ref['dimensions']['ticket'], ref['interval']))
                self.assertIn(f'https://github.com/example/factory/issues/{ticket}', ref['evidence'])
        self.assertEqual(3, sum(k.startswith('miss:') for k in m))
        self.assertEqual(3, sum(m[f'missed:{s}']['value'] for s in DEFAULTS))

    def test_each_stage_at_below_and_above_its_loaded_limit(self):
        for stage, (key, wait) in MEASURED.items():
            for limit, result in ((int(wait), 'not missed'), (int(wait) + 1, 'not missed'),
                                  (int(wait) - 1, 'missed')):
                with self.subTest(stage=stage, limit=limit):
                    self.settings(dict(DEFAULTS, **{stage: limit}))
                    m = self.metrics()
                    self.assertEqual(('known', limit, 'minutes', 'limit', stage),
                                     (m['limit:' + stage]['state'], m['limit:' + stage]['value'],
                                      m['limit:' + stage]['unit'], m['limit:' + stage]['statistic'],
                                      m['limit:' + stage]['dimensions']['stage']))
                    self.assertEqual('closedwiz.factory-limits.v1', m['limit:' + stage]['source']['schema'])
                    w = m['wait:' + key]
                    self.assertEqual(('known', wait, 'minutes', stage),
                                     (w['state'], w['value'], w['unit'], w['dimensions']['stage']))
                    self.assertIn(result, w['label'])
                    self.assertEqual(result == 'missed', 'miss:' + key in m)
                    if result == 'missed':
                        miss = m['miss:' + key]
                        self.assertEqual((1, 'count', 4301, w['interval']),
                                         (miss['value'], miss['unit'], miss['dimensions']['ticket'],
                                          miss['interval']))
                        self.assertIn('https://github.com/example/factory/issues/4301', miss['evidence'])

    def test_default_fixture_counts_waits_and_ticket_linked_misses(self):
        m = self.metrics()
        # The producer's own literal denominators for the default settings.
        expected = {'builder_start': (4, 0, 1, 1, 2, 0, 0), 'reviewer_start': (5, 1, 1, 0, 1, 1, 1),
                    'merge': (2, 0, 1, 0, 0, 0, 1), 'fix_after_changes': (1, 1, 0, 0, 0, 0, 0),
                    'builder_question_answer': (2, 1, 0, 0, 1, 0, 0)}
        for stage, counts in expected.items():
            got = tuple(m[f'{name}:{stage}']['value'] for name in
                        ('intervals', 'missed', 'not-missed', 'pending', 'unknown', 'gated', 'stale'))
            self.assertEqual(counts, got, stage)
            denominator = m['intervals:' + stage]
            self.assertEqual(('partial', counts[0], None), (denominator['state'], denominator['sample']['observed'],
                                                            denominator['sample']['expected']))
            self.assertTrue(any('history' in p for p in denominator['prerequisites']))
        misses = sorted(k for k in m if k.startswith('miss:'))
        self.assertEqual(sorted('miss:' + k for k in (
            MEASURED['reviewer_start'][0], MEASURED['fix_after_changes'][0],
            MEASURED['builder_question_answer'][0])), misses)
        q = m['wait:' + MEASURED['builder_question_answer'][0]]
        self.assertEqual({'id': MEASURED['builder_question_answer'][0], 'started_at': '2030-03-01T09:45:00Z',
                          'ended_at': '2030-03-01T10:01:00Z'}, q['interval'])
        self.assertEqual({'https://github.com/example/factory/issues/4301',
                          'https://github.com/example/factory/issues/4301#issuecomment-6102',
                          'https://github.com/example/factory/issues/4301#issuecomment-6104'}, set(q['evidence']))
        self.assertEqual('2030-03-01T12:00:00Z', q['observed_at'])
        self.assertEqual('closedwiz.journey.stage-waits.v1', q['source']['schema'])
        self.assertEqual(hashlib.sha256((TL2 / 'stage-waits.json').read_bytes()).hexdigest(),
                         q['source']['sha256'])
        pending = m['wait:builder_start:t4303']
        self.assertEqual(('partial', 5.0, None), (pending['state'], pending['value'],
                                                   pending['interval']['ended_at']))
        self.assertEqual('partial', self.provider()['state'])

    def test_unknown_gated_and_stale_stay_unknown_even_under_tiny_limits(self):
        self.settings({k: 1 for k in DEFAULTS})
        m = self.metrics()
        for key, gap in UNMEASURED.items():
            w = m['wait:' + key]
            self.assertEqual(('unavailable', None), (w['state'], w['value']), key)
            self.assertTrue(any(gap in p for p in w['prerequisites']), key)
            self.assertNotIn('miss:' + key, m)
        # Every measured wait now misses, each exactly once; the open one too.
        misses = [k for k in m if k.startswith('miss:')]
        self.assertEqual(len(misses), len(set(misses)))
        # 7 measured: 10, 5 (open), 16, 6, 4, 31 and 5 minutes; 7 unmeasured stay out.
        self.assertEqual(7, len(misses))
        self.assertEqual('partial', m['miss:builder_start:t4303']['state'])
        self.assertEqual(sum(m[f'missed:{s}']['value'] for s in DEFAULTS), len(misses))

    def test_refused_or_missing_producer_evidence_is_grey_never_a_miss(self):
        cases = {
            'missing sidecar': lambda: (self.root / 'stage-waits.json').unlink(),
            'sidecar of another journey': lambda: (self.root / 'journeys.json').write_text(
                (TL2 / 'journeys.json').read_text().replace('2030-03-01T09:10:00Z', '2030-03-01T09:11:00Z', 1)),
            'unknown interval claims an end': lambda: (self.root / 'stage-waits.json').write_text(
                (TL2 / 'stage-waits.json').read_text().replace('"state": "unknown"', '"state": "ended"', 1)),
            'duplicate setting': lambda: self.settings(None, ''.join(
                f'{k}={v}\n' for k, v in DEFAULTS.items()) + 'merge=5\n'),
            'missing setting': lambda: self.settings({k: v for k, v in DEFAULTS.items() if k != 'merge'}),
        }
        for name, damage in cases.items():
            with self.subTest(name):
                self.setUp()
                damage()
                p = self.provider()
                self.assertEqual(('unavailable', []), (p['state'], p['metrics']))
                self.assertTrue(p['prerequisites'])
                self.assertTrue(any('#2337' in x or '#2336' in x for x in p['prerequisites']))

    def test_projection_starts_nothing_and_has_no_authority(self):
        calls = []
        saved = (subprocess.Popen.__init__, socket.socket.connect)

        def refuse(*args, **kwargs):
            calls.append(args[:1])
            raise AssertionError('no process or connection')
        subprocess.Popen.__init__ = refuse
        socket.socket.connect = refuse
        try:
            self.provider()
        finally:
            subprocess.Popen.__init__, socket.socket.connect = saved
        self.assertEqual([], calls)
        self.assertFalse(hasattr(self.adapter, 'act'))

    def test_saved_sample_and_page_carry_the_stage_group(self):
        provider = self.adapter.project(AT, root=self.root, journey='journeys.json',
                                        sidecar='stage-waits.json', settings='limits.conf',
                                        settings_evidence=EVIDENCE, **SELECTION)
        out = self.root / 'out'
        saved = main.tick(AT, out / 'history', out / 'page/index.html', lambda at, previous: [provider])
        latest = history.latest(out / 'history')
        self.assertEqual(saved, latest)
        slot = next(p for p in latest['providers'] if p['slot'] == 'stage_waits')
        self.assertEqual(provider, slot)
        html = (out / 'page/index.html').read_text(encoding='utf-8')
        section = html.split('<section id="stage_waits">')[1].split('</section>')[0]
        self.assertIn('Ticket miss', section)
        self.assertIn('limit (TL1 setting)', section)
        self.assertEqual(html, page.render(latest))

    def test_cli_prints_a_projected_provider_for_source_selection(self):
        script = HERE / 'stage_waits.py'
        done = subprocess.run([sys.executable, '-I', str(script), '--at', AT, '--root', str(self.root),
                               '--journey', 'journeys.json', '--sidecar', 'stage-waits.json',
                               '--settings', 'limits.conf', '--settings-evidence', EVIDENCE[0],
                               '--cohort-since', SELECTION['cohort_since'],
                               '--settings-read-at', SELECTION['settings_read_at']],
                              capture_output=True, text=True, check=False)
        self.assertEqual((0, ''), (done.returncode, done.stderr))
        wire = done.stdout.encode()
        (self.root / 'stage.json').write_bytes(wire)
        chosen = sources.select(self.root, [{'kind': 'projected', 'slot': 'stage_waits', 'path': 'stage.json',
                                             'sha256': hashlib.sha256(wire).hexdigest(),
                                             'observed_at': AT, 'evidence': EVIDENCE}], AT)
        self.assertEqual('partial', chosen[0]['state'])
        self.assertIn('miss:' + MEASURED['fix_after_changes'][0], {m['id'] for m in chosen[0]['metrics']})
        bad = subprocess.run([sys.executable, '-I', str(script), '--at', AT], capture_output=True, text=True)
        self.assertEqual(2, bad.returncode)


if __name__ == '__main__':
    unittest.main()
