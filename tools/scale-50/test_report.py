#!/usr/bin/env python3
"""Public report boundary: fixed synthetic inputs, no live commands."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import sys
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class ReportProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = module('scale_report', HERE / 'report.py')

    def fixture(self):
        return self.api.read(HERE / 'fixtures/report-v1.json')

    def test_literal_fixture_and_repeat(self):
        report = self.fixture()
        for evidence, limits in [('fixture', 'unknown'), ('live', 'unknown'), ('live', 'observed')]:
            changed = copy.deepcopy(report)
            changed['evidence_class'] = evidence
            changed['budgets']['live_limits'] = limits
            with self.subTest(evidence=evidence, limits=limits):
                self.api.validate(changed)
        self.assertEqual(self.api.compare(report, copy.deepcopy(report))['tick_p95_ms_delta'], 0)
        self.assertEqual(report['metrics']['starts'], {'attempted': 200, 'accepted': 200, 'uncertain': 0, 'refused': 0})
        self.assertEqual(report['metrics']['accepted_starts_per_minute'], 20)
        self.assertEqual(report['metrics']['http_per_tick']['rest_requests']['p95'], 4)
        self.assertEqual(report['budgets']['rest']['requests'], 12)
        self.assertEqual(report['budgets']['graphql']['cost'], 7)
        candidate = copy.deepcopy(report)
        candidate['candidate']['revision'] = 'synthetic-b'
        candidate['metrics']['tick_ms'] = {'p50': 10, 'p95': 20, 'samples': 1}
        candidate['budgets']['rest']['requests'] = 14
        candidate['budgets']['graphql']['cost'] = 10
        delta = self.api.compare(report, candidate)
        self.assertEqual(delta['tick_p95_ms_delta'], 20)
        self.assertEqual(delta['rest_requests_delta'], 2)
        self.assertEqual(delta['graphql_cost_delta'], 3)
        self.assertEqual(delta['candidate_changes'], {'revision': ['synthetic-a', 'synthetic-b']})

    def test_comparison_rejects_workload_or_bounds_changes(self):
        report = self.fixture()
        candidate = copy.deepcopy(report)
        candidate['candidate']['revision'] = 'synthetic-b'
        self.assertEqual(self.api.compare(report, candidate), {
            'tick_p95_ms_delta': 0, 'rest_requests_delta': 0,
            'graphql_cost_delta': 0,
            'candidate_changes': {'revision': ['synthetic-a', 'synthetic-b']},
        })
        for field in ['workload', 'bounds', 'coverage', 'evidence_class', 'measurement_model']:
            changed = copy.deepcopy(report)
            if field == 'workload': changed[field]['id'] = 'different-workload'
            elif field == 'bounds': changed[field]['quiet_s'] = 1801
            elif field == 'coverage': changed[field][0]['mode'] = 'different-route'
            elif field == 'measurement_model':
                files = {'synthetic/measurement-model.py': 'a' * 64}
                changed[field] = {'files': files, 'sha256': hashlib.sha256(
                    json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}
            else: changed[field] = 'live'
            self.api.validate(changed)
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.api.compare(report, changed)

    def test_complete_requires_mixed_concurrency_evidence(self):
        report = self.fixture()
        for intervals in [[], [dict(start_s=0, end_s=600, builders=50, reviewers=0)]]:
            report['window']['active_intervals'] = intervals
            with self.subTest(intervals=intervals), self.assertRaises(ValueError):
                self.api.validate(report)

    def test_comparison_refuses_shortened_valid_window(self):
        baseline = self.fixture()
        candidate = copy.deepcopy(baseline)
        candidate['window']['end_s'] = 599
        candidate['window']['active_intervals'][0]['end_s'] = 599
        self.api.validate(candidate)
        with self.assertRaises(ValueError):
            self.api.compare(baseline, candidate)

    def test_unknown_and_partial_never_become_pass(self):
        report = self.fixture()
        report['state'] = 'partial'
        report['gaps'].append('Missing timing sample')
        report['measurement_model'] = None
        report['metrics']['tick_ms'] = None
        report['metrics']['http_per_tick']['rest_requests'] = None
        report['budgets']['rest']['limit'] = None
        report['budgets']['rest']['remaining'] = None
        self.api.validate(report)
        with self.assertRaises(ValueError):
            self.api.compare(report, report)

        for state in ('partial', 'unknown'):
            for side in ('baseline', 'candidate'):
                baseline = self.fixture()
                candidate = copy.deepcopy(baseline)
                candidate['candidate']['revision'] = 'synthetic-b'
                incomplete = baseline if side == 'baseline' else candidate
                incomplete['state'] = state
                incomplete['gaps'].append('Synthetic missing observation')
                self.api.validate(incomplete)
                with self.subTest(state=state, side=side), self.assertRaisesRegex(
                        ValueError, 'comparison requires complete measurements'):
                    self.api.compare(baseline, candidate)

    def test_measurement_model_requires_complete_consistent_identity(self):
        report = self.fixture()
        for value in [None, {'files': {}, 'sha256': 'a' * 64},
                      {'files': {'synthetic/model.py': 'a' * 64}, 'sha256': 'b' * 64}]:
            report['measurement_model'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.api.validate(report)

    def test_bad_input_is_refused(self):
        report = self.fixture()
        for path, value in [('schema', 'v2'), ('state', True), ('metrics', []), ('extra', 1),
                            ('budgets.live_limits', 'observed')]:
            changed = copy.deepcopy(report)
            if path == 'budgets.live_limits': changed['budgets']['live_limits'] = value
            else: changed[path] = value
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.api.validate(changed)
        with self.assertRaises(ValueError):
            self.api.decode('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):
            self.api.decode('{"schema":NaN}')
        fields = [
            'metrics.tick_ms.p95', 'metrics.review_queue_s.p95',
            'metrics.event_action_s.p50', 'metrics.recheck_delay_s.p95',
            'metrics.merge_delay_s.p50', 'metrics.ci_wait_s.p95',
            'metrics.http_per_tick.rest_requests.p95',
            'metrics.http_per_tick.graphql_requests.p50',
            'metrics.http_per_tick.graphql_cost.p95',
            'metrics.merges_per_hour', 'metrics.requests_per_ticket',
            'metrics.graphql_cost_per_ticket', 'metrics.accepted_starts_per_minute',
        ]
        with tempfile.TemporaryDirectory(prefix='scale-report-refusal-') as td:
            path = Path(td) / 'synthetic.json'
            for field in fields:
                for value in (-1, True, 'synthetic-private-value', None, 1e309):
                    with self.subTest(field=field, value=value):
                        changed = copy.deepcopy(report)
                        target = changed
                        *parents, key = field.split('.')
                        for parent in parents:
                            target = target[parent]
                        target[key] = value
                        # A valid JSON number that overflows to infinity on read.
                        path.write_text(json.dumps(changed).replace('Infinity', '1e309'))
                        result = subprocess.run(
                            [sys.executable, '-B', str(HERE / 'report.py'), str(path)],
                            capture_output=True, text=True,
                        )
                        self.assertEqual(result.returncode, 1)
                        self.assertEqual(result.stdout, '')
                        self.assertEqual(result.stderr.splitlines()[-1],
                                         'ValueError: ' + field + ': expected finite nonnegative number')
                        self.assertNotIn('synthetic-private-value', result.stderr)


if __name__ == '__main__':
    unittest.main()
