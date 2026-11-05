#!/usr/bin/env python3
"""WR8 answer-category proof at the suite boundary, synthetic evidence only.

The independent worked interval is 11:00 -> 11:07 = 420 seconds. The selected
three-request cohort has one answer, one open request and one unprovable request;
coverage is 1/3, never 1/1. Existing generic suite tests cannot detect a category
adapter that mistakes a receipt/status for a substantive answer or drops a wait.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def module(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


suite = module('suite')


class AnswerTime(unittest.TestCase):
    def setUp(self):
        self.adapter = module('answer_time')
        path = HERE / 'fixtures/answer-time/pairs.json'
        wire = path.read_bytes()
        self.args = json.loads(wire)['projection']
        self.args['source'] = {
            'path': 'tools/war-room/fixtures/answer-time/pairs.json',
            'schema': 'synthetic.answer-evidence',
            'sha256': hashlib.sha256(wire).hexdigest(),
        }

    def through_suite(self, args=None):
        args = self.args if args is None else args
        provider = self.adapter.project(**args)
        record = suite.compose(args['sample_at'], [provider],
                               assembled_at=args.get('assembled_at'))
        checked = suite.loads(json.dumps(record, allow_nan=False))
        return next(p for p in checked['providers'] if p['slot'] == 'answer_time')

    def metrics(self, args=None):
        return {m['id']: m for m in self.through_suite(args)['metrics']}

    def test_known_open_unknown_keep_latency_denominator_and_references(self):
        before = copy.deepcopy(self.args)
        metrics = self.metrics()
        known = metrics['interval-q-4001']
        self.assertEqual(('known', 420, 'seconds'),
                         (known['state'], known['value'], known['native_unit']))
        self.assertEqual({'id': 'q-4001', 'started_at': '2030-01-02T11:00:00Z',
                          'ended_at': '2030-01-02T11:07:00Z'}, known['interval'])
        self.assertEqual([self.args['requests'][0]['reference'],
                          self.args['dispositions'][0]['reference']], known['evidence'])
        self.assertEqual(self.args['source'], known['source'])
        self.assertEqual(self.args['window'], known['window'])
        self.assertEqual('2030-01-02T12:00:00Z', known['observed_at'])
        self.assertEqual('unknown', known['freshness'])
        self.assertEqual(('partial', None),
                         (metrics['interval-q-4002']['state'], metrics['interval-q-4002']['value']))
        self.assertIsNone(metrics['interval-q-4002']['interval']['ended_at'])
        self.assertEqual(('unavailable', None),
                         (metrics['interval-q-4003']['state'], metrics['interval-q-4003']['value']))
        self.assertEqual({'observed': 3, 'expected': 3,
                          'identities': ['q-4001', 'q-4002', 'q-4003'],
                          'numerator': 1, 'denominator': 3}, metrics['answer-coverage']['sample'])
        self.assertEqual(1 / 3, metrics['answer-coverage']['value'])
        self.assertEqual(1, metrics['open-censored']['value'])
        self.assertEqual(1, metrics['unknown-censored']['value'])
        self.assertEqual('partial', self.through_suite()['state'])
        self.assertEqual(before, self.args)

    def test_receipts_status_and_label_removal_cannot_close_a_request(self):
        # Plausible bug: a resolved status/accepted notification supplies end time.
        for kind in ('notification_sent', 'notification_accepted',
                     'needs_info_removed', 'status_resolved', 'unknown'):
            with self.subTest(kind=kind):
                args = copy.deepcopy(self.args)
                args['dispositions'][0]['kind'] = kind
                metric = self.metrics(args)['interval-q-4001']
                self.assertIsNone(metric['value'])
                self.assertIsNone(metric['interval']['ended_at'])
                self.assertTrue(metric['prerequisites'])
                self.assertEqual(0, self.metrics(args)['answer-coverage']['sample']['numerator'])

    def test_duplicate_requests_and_receipts_do_not_change_the_cohort(self):
        expected = self.through_suite()
        self.args['requests'] *= 2
        self.args['dispositions'] *= 3
        self.assertEqual(expected, self.through_suite())

    def test_existing_projected_timing_retains_its_native_fact_and_rejects_mismatch(self):
        # Existing suite format, NOT claimed TL2-native fields. A measured seven
        # minutes remains seven minutes rather than a second seconds timer.
        timing = {
            'id': 'existing-wait', 'group': 'stage_waits', 'label': 'Existing wait',
            'state': 'known', 'value': 7, 'unit': 'minutes', 'native_unit': 'minutes',
            'statistic': 'observation', 'window': copy.deepcopy(self.args['window']),
            'observed_at': self.args['observed_at'], 'fresh_until': None,
            'freshness': 'unknown', 'source': copy.deepcopy(self.args['source']),
            'evidence': [self.args['requests'][0]['reference'],
                         self.args['dispositions'][0]['reference']],
            'sample': {'observed': 1, 'expected': 1, 'identities': ['q-4001'],
                       'numerator': None, 'denominator': None},
            'dimensions': {'direction': None, 'pool': None, 'stage': 'synthetic-stage',
                           'ticket': 4001, 'cohort': 'existing-source-cohort'},
            'interval': {'id': 'q-4001', 'started_at': '2030-01-02T11:00:00Z',
                         'ended_at': '2030-01-02T11:07:00Z'},
            'prerequisites': [],
        }
        self.args['timings'] = [timing]
        result = self.metrics()['interval-q-4001']
        self.assertEqual((7, 'minutes', 'minutes'),
                         (result['value'], result['unit'], result['native_unit']))
        for field in ('source', 'window', 'observed_at', 'interval', 'dimensions', 'sample'):
            self.assertEqual(timing[field], result[field])
        # R1: matching endpoints cannot excuse a different non-null ticket.
        # The previous reuse proof checked only the matching-ticket fixture.
        for request_ticket, timing_ticket, accepted in (
                (4001, 4001, True), (4001, None, True),
                (None, 4001, True), (None, None, True), (4001, 4999, False)):
            with self.subTest(request_ticket=request_ticket, timing_ticket=timing_ticket):
                args = copy.deepcopy(self.args)
                args['requests'][0]['ticket'] = request_ticket
                args['timings'][0]['dimensions']['ticket'] = timing_ticket
                if accepted:
                    reused = self.metrics(args)['interval-q-4001']
                    self.assertEqual(timing_ticket, reused['dimensions']['ticket'])
                    self.assertEqual((7, 'minutes'), (reused['value'], reused['native_unit']))
                else:
                    with self.assertRaises(ValueError):
                        self.through_suite(args)
        self.args['timings'][0]['interval']['ended_at'] = '2030-01-02T11:08:00Z'
        with self.assertRaises(ValueError):
            self.through_suite()

    def test_incomplete_edited_deleted_or_unlinked_endpoints_stay_censored(self):
        # Plausible bug: parse the current edited text as complete history, or
        # use a timestamp despite an absent independent source/link to request.
        mutations = [('requests', 'reference', None), ('requests', 'at', None),
                     ('dispositions', 'reference', None), ('dispositions', 'at', None),
                     ('dispositions', 'request', None),
                     ('dispositions', 'request', self.args['requests'][1]['reference']),
                     ('dispositions', 'reference', self.args['requests'][0]['reference'])]
        mutations += [(side, 'completeness', state)
                      for side in ('requests', 'dispositions')
                      for state in ('edited', 'deleted', 'unknown')]
        for side, field, value in mutations:
            with self.subTest(side=side, field=field, value=value):
                args = copy.deepcopy(self.args)
                args[side][0][field] = value
                metric = self.metrics(args)['interval-q-4001']
                self.assertIsNone(metric['value'])
                self.assertIsNone(metric['interval']['ended_at'])
                self.assertTrue(metric['prerequisites'])

    def test_reversed_or_unobserved_times_cannot_fabricate_a_known_answer(self):
        for at in ('2030-01-02T10:59:59Z', '2030-01-02T12:00:01Z'):
            with self.subTest(at=at):
                self.args['dispositions'][0]['at'] = at
                metric = self.metrics()['interval-q-4001']
                self.assertIsNone(metric['value'])
                self.assertIsNone(metric['interval']['ended_at'])
                self.assertTrue(metric['prerequisites'])

    def test_missing_expected_history_and_source_do_not_become_complete(self):
        self.args['expected'] = None
        self.args['history'] = 'unknown'
        metric = self.metrics()['answer-coverage']
        self.assertEqual('partial', metric['state'])
        self.assertIsNone(metric['sample']['expected'])
        self.assertTrue(metric['prerequisites'])
        self.args['source'] = None
        provider = self.through_suite()
        self.assertEqual('unavailable', provider['state'])
        self.assertTrue(all(m['value'] is None for m in provider['metrics']))

    def test_complete_selected_cohort_and_real_zero_interval_are_known(self):
        # A sourced same-second answer is zero; an unanswered request is not.
        self.args.update(requests=self.args['requests'][:1],
                         dispositions=self.args['dispositions'][:1],
                         expected=1, history='complete')
        self.args['dispositions'][0]['at'] = '2030-01-02T11:00:00Z'
        provider = self.through_suite()
        self.assertEqual('known', provider['state'])
        metrics = {m['id']: m for m in provider['metrics']}
        self.assertEqual(0, metrics['interval-q-4001']['value'])
        self.assertEqual(1, metrics['answer-coverage']['value'])
        self.assertEqual(0, metrics['open-censored']['value'])

    def test_empty_cohort_and_absent_native_capability_remain_visible(self):
        self.args.update(requests=[], dispositions=[], expected=0)
        metrics = self.metrics()
        self.assertIsNone(metrics['answer-coverage']['value'])
        self.assertEqual(0, metrics['answer-coverage']['sample']['denominator'])
        provider = self.adapter.unavailable()
        record = suite.compose(self.args['sample_at'], [provider])
        provider = next(p for p in record['providers'] if p['slot'] == 'answer_time')
        self.assertEqual('unavailable', provider['state'])
        self.assertTrue(any('substantive' in p for p in provider['prerequisites']))
        self.assertTrue(any('TL2' in p for p in provider['prerequisites']))

    def test_identity_conflicts_bad_shapes_and_out_of_cohort_requests_refuse(self):
        cases = []
        args = copy.deepcopy(self.args)
        args['requests'].append(dict(args['requests'][0], at='2030-01-02T11:01:00Z'))
        cases.append(args)
        args = copy.deepcopy(self.args)
        args['dispositions'].append(dict(args['dispositions'][0], at='2030-01-02T11:08:00Z'))
        cases.append(args)
        for field, value in [('expected', True), ('expected', 2), ('history', 'complete-ish')]:
            args = copy.deepcopy(self.args)
            args[field] = value
            cases.append(args)
        for field, value in [('at', 'bad'), ('at', '2030-01-02T12:00:00Z'),
                             ('at', '2030-01-02T10:59:59Z'),
                             ('extra', 'raw text'), ('reference', 'javascript:private')]:
            args = copy.deepcopy(self.args)
            args['requests'][0][field] = value
            cases.append(args)
        for args in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    self.through_suite(args)


if __name__ == '__main__':
    unittest.main()
