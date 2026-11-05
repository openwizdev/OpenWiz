#!/usr/bin/env python3
"""WR1 public boundary proofs, synthetic facts only; no collector is invoked.

Worked facts: 3 merged PRs in one UTC hour; a partial review cohort observes
2 of 4 PRs and cannot turn the missing two into first-pass successes. A source
observed at 12:00, valid through 12:05, is stale at 12:10 regardless of assembly.
These new composition/wire contracts had no existing War room test owner.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('war_room_suite', HERE / 'suite.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)


class Contract(unittest.TestCase):
    def setUp(self):
        self.record = suite.load(HERE / 'fixtures/contract/known.json')

    def metric(self, record=None):
        return (record or self.record)['providers'][0]['metrics'][0]

    def board_provider(self, numerator, denominator, value, unit='ratio', **fields):
        metric = copy.deepcopy(self.metric())
        metric.update(id='board-ratio', group='board', label='Synthetic native board measure',
                      unit=unit, native_unit=unit, statistic='ratio', value=value, **fields)
        metric['source'].update(path='fixtures/board/measures.json', schema='openwiz.plan-links.v1')
        metric['dimensions'].update(direction=None, cohort='board-read')
        metric['sample'] = {'observed': denominator, 'expected': denominator,
                            'identities': [f'item-{4001+i}' for i in range(denominator)],
                            'numerator': numerator, 'denominator': denominator}
        return {'slot': 'board', 'state': 'known', 'prerequisites': [], 'metrics': [metric]}

    def test_r1_native_stock_ratio_and_bounded_proportions(self):
        # plan-links.v1: three ready tickets / one running builder is 3.0,
        # not a proportion. The old ratio guard capped all ratios at one.
        provider = self.board_provider(3, 1, 3.0)
        result = suite.compose('2030-01-02T12:00:00Z', [provider])
        self.assertEqual(3.0, result['providers'][2]['metrics'][0]['value'])
        provider = self.board_provider(2, 4, 0.5)
        provider['metrics'][0]['statistic'] = 'proportion'
        suite.compose('2030-01-02T12:00:00Z', [provider])
        for numerator, denominator, value in ((3, 1, 3), (1, 0, 0)):
            with self.subTest(numerator=numerator, denominator=denominator):
                bad = self.board_provider(numerator, denominator, value)
                bad['metrics'][0]['statistic'] = 'proportion'
                with self.assertRaises(ValueError):
                    suite.compose('2030-01-02T12:00:00Z', [bad])

    def test_r2_native_board_rounding_and_exact_quotients(self):
        # Source literals: 2/3 startable rounds half up to 67%; 1/3 stock
        # rounds to 0.3. Ties 12.5% -> 13 and 0.25 -> 0.3 rule out half-even.
        cases = [(3, 1, 3.0, 'ratio', 'half_up_1', 2.9),
                 (2, 3, 67, 'percent', 'half_up_0', 66),
                 (1, 3, 0.3, 'ratio', 'half_up_1', 0.4),
                 (1, 8, 13, 'percent', 'half_up_0', 12),
                 (1, 4, 0.3, 'ratio', 'half_up_1', 0.2)]
        for numerator, denominator, value, unit, rounding, wrong in cases:
            with self.subTest(unit=unit, numerator=numerator, denominator=denominator):
                provider = self.board_provider(numerator, denominator, value, unit, rounding=rounding)
                result = suite.compose('2030-01-02T12:00:00Z', [provider])
                checked = suite.loads(json.dumps(result))
                self.assertEqual(value, checked['providers'][2]['metrics'][0]['value'])
                provider['metrics'][0]['value'] = wrong
                with self.assertRaises(ValueError):
                    suite.compose('2030-01-02T12:00:00Z', [provider])
        exact = self.board_provider(2, 3, 67, 'percent')
        with self.assertRaisesRegex(ValueError, 'arithmetic'):
            suite.compose('2030-01-02T12:00:00Z', [exact])
        exact = self.board_provider(1, 2, 50, 'percent')
        suite.compose('2030-01-02T12:00:00Z', [exact])
        invalid = self.board_provider(2, 3, 67, 'percent', rounding='half_up_1')
        with self.assertRaises(ValueError):
            suite.compose('2030-01-02T12:00:00Z', [invalid])
        invalid['metrics'][0]['rounding'] = 'unknown'
        with self.assertRaises(ValueError):
            suite.compose('2030-01-02T12:00:00Z', [invalid])

    def test_r3_interval_endpoints_cannot_exceed_source_observation(self):
        # The source was read at 12:00; later assembly cannot establish a
        # completion at 12:04, nor a start at 12:01. Equality is observable.
        cases = [('2030-01-02T11:56:00Z', '2030-01-02T12:04:00Z', '2030-01-02T12:00:00Z', 'known', 480, False),
                 ('2030-01-02T12:01:00Z', None, '2030-01-02T12:00:00Z', 'partial', None, False),
                 ('2030-01-02T11:56:00Z', '2030-01-02T12:00:00Z', '2030-01-02T12:00:00Z', 'known', 240, True),
                 ('2030-01-02T12:00:00Z', '2030-01-02T12:00:00Z', '2030-01-02T12:00:00Z', 'known', 0, True),
                 ('2030-01-02T11:56:00Z', None, '2030-01-02T12:00:00Z', 'partial', None, True),
                 ('2030-01-02T11:56:00Z', None, None, 'unavailable', None, False),
                 (None, '2030-01-02T12:00:00Z', None, 'unavailable', None, False),
                 (None, None, None, 'unavailable', None, True)]
        for start, end, observed, state, value, accepted in cases:
            with self.subTest(start=start, end=end, observed=observed):
                metric = copy.deepcopy(self.metric())
                prerequisites = [] if state == 'known' else ['Open or unavailable source interval']
                metric.update(id='stage-duration', group='stage_waits', state=state, value=value,
                              unit='seconds', native_unit='seconds', statistic='observation',
                              observed_at=observed, fresh_until=None, freshness='unknown',
                              prerequisites=prerequisites,
                              interval={'id': 'wait-1', 'started_at': start, 'ended_at': end})
                metric['sample'].update(observed=1, expected=1, identities=['wait-1'])
                metric['dimensions'].update(direction=None, stage='synthetic-stage', cohort='stage-intervals')
                if observed is None:
                    metric.update(source=None, evidence=[], window=None)
                    metric['sample'].update(observed=0, expected=None, identities=[])
                provider = {'slot': 'stage_waits', 'state': state, 'prerequisites': prerequisites, 'metrics': [metric]}
                if accepted:
                    record = suite.compose('2030-01-02T12:00:00Z', [provider], assembled_at='2030-01-02T12:05:00Z')
                    suite.loads(json.dumps(record))
                else:
                    with self.assertRaises(ValueError):
                        suite.compose('2030-01-02T12:00:00Z', [provider], assembled_at='2030-01-02T12:05:00Z')

    def test_r4_partial_provider_requires_observed_source_evidence(self):
        # A partial label alone previously promoted a wholly unobserved source.
        metric = copy.deepcopy(self.metric())
        metric.update(state='partial', value=None, source=None, window=None, observed_at=None,
                      evidence=[], fresh_until=None, freshness='unknown', prerequisites=['Missing source'])
        metric['sample'].update(observed=0, expected=None, identities=[])
        provider = {'slot': 'activity', 'state': 'partial', 'prerequisites': ['Missing source'], 'metrics': [metric]}
        with self.assertRaises(ValueError):
            suite.compose('2030-01-02T12:00:00Z', [provider])
        for missing in ('source', 'observed_at', 'evidence'):
            with self.subTest(missing=missing):
                metric.update(source=copy.deepcopy(self.metric()['source']), observed_at='2030-01-02T12:00:00Z',
                              evidence=list(self.metric()['evidence']))
                metric[missing] = [] if missing == 'evidence' else None
                with self.assertRaises(ValueError):
                    suite.compose('2030-01-02T12:00:00Z', [provider])
        metric.update(source=copy.deepcopy(self.metric()['source']), observed_at='2030-01-02T12:00:00Z',
                      evidence=list(self.metric()['evidence']))
        for value in (None, 0):
            with self.subTest(sourced_value=value):
                metric['value'] = value
                metric['window'] = copy.deepcopy(self.metric()['window'])
                suite.compose('2030-01-02T12:00:00Z', [provider])
        suite.validate(suite.load(HERE / 'fixtures/contract/partial.json'))

    def test_known_partial_and_unavailable_examples(self):
        for name in ('known', 'partial', 'unavailable'):
            with self.subTest(name=name):
                record = suite.load(HERE / f'fixtures/contract/{name}.json')
                suite.validate(record)
        self.assertEqual(3, self.metric()['value'])
        partial = suite.load(HERE / 'fixtures/contract/partial.json')
        self.assertIsNone(partial['providers'][12]['metrics'][0]['value'])

    def test_one_composition_boundary_and_missing_provider_stubs(self):
        activity = self.record['providers'][0]
        result = suite.compose('2030-01-02T12:00:00Z', [activity])
        self.assertEqual(self.record, result)
        self.assertEqual(17, len(result['providers']))
        self.assertEqual(['throughput', 'stage_waits', 'board', 'ci', 'usage', 'decisions'], result['groups'])
        for slot in ('stage_waits', 'cost', 'answer_time', 'rework', 'eb6', 'eb7', 'eb8', 'eb9'):
            provider = next(p for p in result['providers'] if p['slot'] == slot)
            self.assertEqual('unavailable', provider['state'])
            self.assertTrue(provider['prerequisites'])
            self.assertEqual([], provider['metrics'])

    def test_provider_can_add_metrics_without_a_new_record_version(self):
        activity = copy.deepcopy(self.record['providers'][0])
        extra = copy.deepcopy(activity['metrics'][0])
        extra.update(id='merged-today-sideways', label='Merged today sideways')
        activity['metrics'].append(extra)
        result = suite.compose('2030-01-02T12:00:00Z', [activity])
        self.assertEqual('openwiz.war-room.v1', result['schema'])
        self.assertEqual(2, len(result['providers'][0]['metrics']))
        self.assertEqual(1, len(self.record['providers'][0]['metrics']))

    def test_cost_projection_can_express_usd_per_pr_without_unit_conversion(self):
        # WR4 owns allocation. The seam must be able to hold its derived unit:
        # 15 USD allocated once across two merged PRs = 7.5 USD/merged PR.
        metric = copy.deepcopy(self.metric())
        metric.update(id='all-in-usd-per-merged-pr', group='ci', label='Synthetic all-in USD per merged PR',
                      unit='usd_per_merged_pr', native_unit='usd_per_merged_pr', statistic='ratio', value=7.5)
        metric['dimensions'].update(direction=None, cohort='merged-prs')
        metric['sample'] = {'observed': 2, 'expected': 2, 'identities': ['pr-4001', 'pr-4002'],
                            'numerator': 15, 'denominator': 2}
        provider = {'slot': 'cost', 'state': 'known', 'prerequisites': [], 'metrics': [metric]}
        result = suite.compose('2030-01-02T12:00:00Z', [provider])
        self.assertEqual(7.5, result['providers'][7]['metrics'][0]['value'])
        metric['value'] = 8
        with self.assertRaisesRegex(ValueError, 'arithmetic'):
            suite.compose('2030-01-02T12:00:00Z', [provider])
        # A small positive USD allocation cannot validate as known zero merely
        # because a floating-point comparison has an absolute error tolerance.
        metric['sample']['numerator'] = 1e-13
        metric['value'] = 0
        with self.assertRaisesRegex(ValueError, 'arithmetic'):
            suite.compose('2030-01-02T12:00:00Z', [provider])

    def test_strict_shapes_types_and_units(self):
        # A permissive reader could silently drop a field or treat True as 1.
        mutations = [
            lambda r: r.pop('groups'),
            lambda r: r.update(raw_comments=[]),
            lambda r: r.update(schema='openwiz.war-room.v2'),
            lambda r: r.update(providers=r['providers'][:-1]),
            lambda r: r['providers'].append(r['providers'][0]),
            lambda r: r['groups'].reverse(),
            lambda r: self.metric(r).update(value=True),
            lambda r: self.metric(r).update(value=float('nan')),
            lambda r: self.metric(r).update(value=float('inf')),
            lambda r: self.metric(r).update(unit='usd'),
            lambda r: self.metric(r).update(unit='dollars', native_unit='dollars'),
            lambda r: self.metric(r)['sample'].update(observed=True),
            lambda r: self.metric(r).update(state={'known': None}),
            lambda r: self.metric(r).update(value='3'),
            lambda r: self.metric(r)['source'].update(path='../secret'),
            lambda r: self.metric(r).update(group='decisions'),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                bad = copy.deepcopy(self.record)
                mutate(bad)
                with self.assertRaises(ValueError):
                    suite.validate(bad)

    def test_unknown_and_partial_cannot_claim_complete_zero(self):
        mutations = [
            {'state': 'unavailable', 'value': 0, 'prerequisites': ['Missing source']},
            {'state': 'partial', 'prerequisites': []},
            {'value': None},
            {'source': None},
            {'evidence': []},
        ]
        for fields in mutations:
            with self.subTest(fields=fields):
                bad = copy.deepcopy(self.record)
                self.metric(bad).update(fields)
                with self.assertRaises(ValueError):
                    suite.validate(bad)
        self.metric()['value'] = 0
        suite.validate(self.record)  # A sourced, complete zero is distinct.
        self.metric()['sample']['expected'] = 4
        with self.assertRaisesRegex(ValueError, 'coverage'):
            suite.validate(self.record)

    def test_duplicate_metric_and_observation_identity_refused(self):
        self.record['providers'][0]['metrics'].append(copy.deepcopy(self.metric()))
        with self.assertRaisesRegex(ValueError, 'duplicate metric'):
            suite.validate(self.record)
        self.record['providers'][0]['metrics'].pop()
        with self.assertRaisesRegex(ValueError, 'duplicate provider'):
            suite.compose('2030-01-02T12:00:00Z', [self.record['providers'][0]] * 2)
        self.metric()['sample']['identities'].append('pr-4001')
        with self.assertRaises(ValueError):
            suite.validate(self.record)

    def test_sample_identity_is_utc_boundary_not_source_time(self):
        for at in ('2030-01-02T12:01:00Z', '2030-01-02T12:00:01Z',
                   '2030-01-02T04:00:00-08:00', '2030-02-30T12:00:00Z'):
            with self.subTest(at=at), self.assertRaises(ValueError):
                suite.compose(at)
        bad = copy.deepcopy(self.record)
        bad['sample_id'] = '2030-01-02T12:05:00Z'
        with self.assertRaises(ValueError):
            suite.validate(bad)

    def test_source_freshness_never_moves_with_assembly(self):
        at = '2030-01-02T12:10:00Z'
        activity = self.record['providers'][0]
        with self.assertRaisesRegex(ValueError, 'freshness'):
            suite.compose(at, [activity])  # Source still claims fresh.
        activity['metrics'][0]['freshness'] = 'stale'
        result = suite.compose(at, [activity])
        self.assertEqual('2030-01-02T12:00:00Z', self.metric(result)['observed_at'])
        self.assertEqual(3, self.metric(result)['value'])
        self.assertEqual('stale', self.metric(result)['freshness'])

    def test_bad_time_evidence_ratio_and_interval_refused(self):
        mutations = [
            {'observed_at': '2030-01-02T12:01:00Z'},
            {'window': {'since': '2030-01-02T12:00:00Z', 'until': '2030-01-02T11:00:00Z', 'timezone': 'UTC'}},
            {'evidence': ['javascript:alert(1)']},
            {'statistic': 'ratio', 'value': 0, 'unit': 'ratio', 'native_unit': 'ratio'},
            {'interval': {'id': 'wait-1', 'started_at': '2030-01-02T12:00:00Z', 'ended_at': '2030-01-02T11:00:00Z'}},
        ]
        for fields in mutations:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                bad = copy.deepcopy(self.record)
                self.metric(bad).update(fields)
                suite.validate(bad)

    def test_strict_wire_reader(self):
        encoded = json.dumps(self.record)
        bad = [encoded.replace('"schema":', '"schema":"duplicate", "schema":', 1),
               encoded.replace('"value": 3', '"value": NaN', 1),
               encoded.replace('"value": 3', '"value": 1e999', 1), '[]']
        for wire in bad:
            with self.subTest(wire=wire[:20]), self.assertRaises(ValueError):
                suite.loads(wire)

    def test_identifiers_paths_and_links_reject_terminal_newlines(self):
        # Regex dollar anchors can otherwise accept a final newline. No prior
        # test covered that wire spelling at the public validation boundary.
        mutations = [lambda r: self.metric(r).update(id='merged-hour-forward\n'),
                     lambda r: self.metric(r)['source'].update(path='fixtures/activity/merged.json\n'),
                     lambda r: self.metric(r)['evidence'].__setitem__(0, 'https://github.com/synthetic-owner/work/pull/4001\n')]
        for index, mutate in enumerate(mutations):
            with self.subTest(case=index), self.assertRaises(ValueError):
                record = copy.deepcopy(self.record)
                mutate(record)
                suite.validate(record)

    def test_explicit_empty_assembly_time_is_not_defaulted(self):
        with self.assertRaises(ValueError):
            suite.compose('2030-01-02T12:00:00Z', assembled_at='')

    def test_cli_check_is_finite_read_only_and_round_trips(self):
        path = HERE / 'fixtures/contract/known.json'
        before = path.read_bytes()
        run = subprocess.run([sys.executable, '-I', str(HERE / 'suite.py'), 'check', str(path)],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual(self.record, json.loads(run.stdout))
        self.assertEqual(before, path.read_bytes())
        bad = subprocess.run([sys.executable, '-I', str(HERE / 'suite.py'), 'check', '-'],
                             input='{"schema": "wrong"}', capture_output=True, text=True, timeout=10)
        self.assertEqual(1, bad.returncode)
        self.assertEqual('', bad.stdout)
        self.assertIn('suite:', bad.stderr)


if __name__ == '__main__':
    unittest.main()
