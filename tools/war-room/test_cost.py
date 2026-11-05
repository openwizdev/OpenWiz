#!/usr/bin/env python3
"""WR4 synthetic public provider/suite proofs; expected arithmetic is in fixtures/cost/README.md."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIX = HERE / 'fixtures/cost'
AT = '2030-01-03T00:00:00Z'
LINK = 'https://github.com/example/synthetic/pull/4001'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


suite = module('cost_suite', HERE / 'suite.py')


class Cost(unittest.TestCase):
    def setUp(self):
        self.cost = module('cost_projection', HERE / 'cost.py')
        self.allocation = json.loads((FIX / 'allocation.json').read_text())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def source(self, filename, data=None):
        wire = (FIX / filename).read_bytes() if data is None else json.dumps(data).encode()
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(wire)
        return {'path': path, 'source_path': 'fixtures/synthetic/' + filename,
                'observed_at': AT, 'evidence': [LINK]}

    def project(self, **kwargs):
        provider = self.cost.project(AT, **kwargs)
        record = suite.loads(json.dumps(suite.compose(AT, [provider], assembled_at=kwargs.get('assembled_at'))))
        return next(p for p in record['providers'] if p['slot'] == 'cost')

    def metrics(self, provider):
        return {m['id']: m for m in provider['metrics']}

    def test_absent_is_visible_unknown_with_each_component_prerequisite(self):
        p = self.project()
        m = self.metrics(p)['all-in']
        self.assertEqual(('unavailable', None, 'usd_per_merged_pr'),
                         (m['state'], m['value'], m['unit']))
        for component in ('models', 'shared_parent', 'helpers', 'sandbox', 'ci'):
            self.assertTrue(any(component in gap for gap in p['prerequisites']))
        self.assertIsNone(m['sample']['expected'])

    def test_complete_synthetic_cohort_has_independent_arithmetic_and_binding(self):
        original = copy.deepcopy(self.allocation)
        p = self.project(synthetic_allocation=self.allocation)
        m = self.metrics(p)['all-in']
        self.assertEqual(('known', 6, 12, 2),
                         (m['state'], m['value'], m['sample']['numerator'], m['sample']['denominator']))
        self.assertEqual(['pr-4001', 'pr-4002'], m['sample']['identities'])
        self.assertIn('Synthetic', m['label'])
        self.assertEqual(original, self.allocation)
        self.assertEqual('known', p['state'])
        component = self.metrics(p)['allocation-shared_parent']
        self.assertEqual((2, 2), (component['value'], component['sample']['observed']))

    def test_disjoint_allocations_sum_once_in_one_component_series(self):
        # Coverage for one component may be supplied in disjoint PR subsets.
        # The displayed component total must retain both, independent of order.
        a = copy.deepcopy(self.allocation)
        row = a['components'][0]
        row.update(prs=[4001], value=1)
        other = copy.deepcopy(row)
        other.update(prs=[4002], value=3, charges=['synthetic-models-other'])
        a['components'].append(other)
        for rows in (a['components'], list(reversed(a['components']))):
            a['components'] = rows
            p = self.project(synthetic_allocation=a)
            m = self.metrics(p)
            self.assertEqual(6, m['all-in']['value'])
            self.assertEqual((4, 2, 2), (m['allocation-models']['value'],
                             m['allocation-models']['sample']['observed'],
                             m['allocation-models']['sample']['expected']))
            self.assertEqual(6, len(p['metrics']))

    def test_each_missing_or_unallocated_component_keeps_all_in_unknown(self):
        for index in range(5):
            for mode in ('missing', 'partial'):
                with self.subTest(index=index, mode=mode):
                    a = copy.deepcopy(self.allocation)
                    component = a['components'][index]['component']
                    if mode == 'missing':
                        a['components'].pop(index)
                    else:
                        a['components'][index]['complete'] = False
                    p = self.project(synthetic_allocation=a)
                    m = self.metrics(p)['all-in']
                    self.assertIsNone(m['value'])
                    self.assertEqual('unavailable', m['state'])
                    self.assertTrue(any(component in gap for gap in p['prerequisites']))

    def test_no_merges_rejects_denominator_without_inventing_zero_cost(self):
        a = copy.deepcopy(self.allocation)
        a['prs'], a['components'] = [], []
        p = self.project(synthetic_allocation=a)
        self.assertIsNone(self.metrics(p)['all-in']['value'])
        self.assertTrue(any('merged' in gap for gap in p['prerequisites']))

    def test_allocation_refuses_double_counts_mismatches_and_bad_shapes(self):
        for mutation in ('duplicate-pr', 'overlap', 'charge', 'currency', 'foreign-pr',
                         'unknown-component', 'extra', 'nonfinite', 'bool', 'real-source', 'empty-charge'):
            with self.subTest(mutation=mutation):
                a = copy.deepcopy(self.allocation)
                row = a['components'][0]
                if mutation == 'duplicate-pr': a['prs'].append(4001)
                if mutation == 'overlap': a['components'].append(copy.deepcopy(row))
                if mutation == 'charge': a['components'][1]['charges'] = row['charges'][:]
                if mutation == 'currency': row['unit'] = 'credits'
                if mutation == 'foreign-pr': row['prs'] = [4003]
                if mutation == 'unknown-component': row['component'] = 'invented'
                if mutation == 'extra': row['allocation_rule'] = 'divide-everything'
                if mutation == 'nonfinite': row['value'] = float('inf')
                if mutation == 'bool': row['value'] = True
                if mutation == 'real-source': a['evidence_class'] = 'observation'
                if mutation == 'empty-charge': row['charges'] = []
                with self.assertRaises(ValueError):
                    self.project(synthetic_allocation=a)

    def test_native_daily_units_lower_bounds_and_ci_estimate_are_separate(self):
        journey = self.source('journey.json')
        ci = self.source('ci/point.json')
        p = self.project(journey=journey, ci=ci)
        m = self.metrics(p)
        self.assertEqual('partial', p['state'])
        self.assertIsNone(m['all-in']['value'])
        self.assertEqual((6, 'usd'), (m['daily-2030-01-01-gpt-usd']['value'], m['daily-2030-01-01-gpt-usd']['unit']))
        self.assertEqual((9, 'credits'), (m['daily-2030-01-01-gpt-credits']['value'], m['daily-2030-01-01-gpt-credits']['unit']))
        self.assertEqual((6000, 'tokens'), (m['daily-2030-01-01-gpt-tokens']['value'], m['daily-2030-01-01-gpt-tokens']['unit']))
        self.assertEqual((6, 'hours'), (m['daily-2030-01-01-sandbox-hours']['value'], m['daily-2030-01-01-sandbox-hours']['unit']))
        ratio = m['daily-2030-01-01-gpt-usd-ratio']
        self.assertEqual((3, 'usd_per_merged_pr', 'UTC'), (ratio['value'], ratio['unit'], ratio['window']['timezone']))
        self.assertIn('day ratio', ratio['label'])
        self.assertEqual((0.2, 'PST-fixed-UTC-08:00'), (m['ci-estimate']['value'], m['ci-estimate']['window']['timezone']))
        self.assertIn('estimate', m['ci-estimate']['label'])
        self.assertTrue(any('2030-01-01' in gap for gap in m['ci-estimate']['prerequisites']))
        parent = m['spec-3001-gpt-usd']
        self.assertEqual((2, 'partial'), (parent['value'], parent['state']))
        self.assertIn('lower bound', parent['label'])
        self.assertEqual(1, len([x for x in p['metrics'] if x['id'] == 'spec-3001-gpt-usd']))
        self.assertEqual(['pr-4001'], m['all-in']['sample']['identities'])
        self.assertEqual(hashlib.sha256(Path(journey['path']).read_bytes()).hexdigest(), ratio['source']['sha256'])
        self.assertEqual('unknown', ratio['freshness'])

    def test_native_partial_missing_days_and_zero_daily_denominator(self):
        doc = json.loads((FIX / 'journey.json').read_text())
        doc['tickets'][0]['usage'][5]['missing_days'] = ['2030-01-01']
        doc['daily_usage'][0]['merged_prs'] = 0
        for units in doc['daily_usage'][0]['totals'].values():
            for amount in units.values(): amount['per_merged_pr'] = None
        p = self.project(journey=self.source('journey.json', doc))
        m = self.metrics(p)
        self.assertIsNone(m['daily-2030-01-01-gpt-usd-ratio']['value'])
        self.assertTrue(any('2030-01-01' in gap for gap in m['ticket-3101-gpt-usd']['prerequisites']))
        self.assertIsNone(m['all-in']['value'])

    def test_native_daily_non_usd_ratios_preserve_native_units_and_rounding(self):
        doc = json.loads((FIX / 'journey.json').read_text())
        doc['daily_usage'][0]['merged_prs'] = 3
        for units in doc['daily_usage'][0]['totals'].values():
            for amount in units.values():
                amount['per_merged_pr'] = round(amount['total'] / 3, 6)
        p = self.project(journey=self.source('journey.json', doc))
        m = self.metrics(p)
        self.assertEqual(2, m['daily-2030-01-01-gpt-usd-ratio']['value'])
        self.assertEqual((2000, 'tokens'), (m['daily-2030-01-01-gpt-tokens-ratio']['value'], m['daily-2030-01-01-gpt-tokens-ratio']['unit']))
        self.assertEqual('observation', m['daily-2030-01-01-gpt-tokens-ratio']['statistic'])

    def test_unknown_units_and_ci_prices_never_turn_into_zero(self):
        doc = json.loads((FIX / 'journey.json').read_text())
        doc['daily_usage'][0]['totals']['gpt']['usd'] = {'total': None, 'per_merged_pr': None}
        point = json.loads((FIX / 'ci/point.json').read_text())
        point['cost']['window_usd'] = None
        point['cost']['unknown_minutes'] = 5
        p = self.project(journey=self.source('journey.json', doc), ci=self.source('ci/point.json', point))
        m = self.metrics(p)
        self.assertIsNone(m['daily-2030-01-01-gpt-usd']['value'])
        self.assertIsNone(m['ci-estimate']['value'])
        self.assertIsNone(m['all-in']['value'])

    def test_r1_producer_independently_rounds_total_and_day_ratio(self):
        # The raw total is rounded independently from raw total / merges.
        # Re-dividing the saved total loses information and rejects valid data.
        for raw, count, total, ratio in ((1.2345674, 2, 1.234567, 0.617284),
                                         (0.0000006, 2, 0.000001, 0.0),
                                         (1.2345674, 1, 1.234567, 1.234567)):
            with self.subTest(raw=raw, count=count):
                doc = json.loads((FIX / 'journey.json').read_text())
                day = doc['daily_usage'][0]
                day['merged_prs'] = count
                for units in day['totals'].values():
                    for amount in units.values():
                        amount['per_merged_pr'] = round(amount['total'] / count, 6)
                produced = self.cost.J.M.amount(raw, count)
                self.assertEqual({'total': total, 'per_merged_pr': ratio}, produced)
                day['totals']['gpt']['usd'] = produced
                self.cost.J.validate(doc)
                m = self.metrics(self.project(journey=self.source('journey.json', doc)))
                self.assertEqual(total, m['daily-2030-01-01-gpt-usd']['value'])
                self.assertIsNone(m['all-in']['value'])
                quotient = m['daily-2030-01-01-gpt-usd-ratio']
                if count == 1:
                    self.assertEqual(ratio, quotient['value'])
                else:
                    self.assertEqual('unavailable', quotient['state'])
                    self.assertIsNone(quotient['value'])
                    self.assertTrue(any('exact' in gap for gap in quotient['prerequisites']))
        # Adjacent rounding cells must not admit an impossible one-merge pair.
        for count, total, ratio in ((1, 1, 1.000001), (2, 1.234567, 0.617285)):
            doc = json.loads((FIX / 'journey.json').read_text())
            day = doc['daily_usage'][0]
            day['merged_prs'] = count
            for units in day['totals'].values():
                for amount in units.values():
                    amount['per_merged_pr'] = round(amount['total'] / count, 6)
            day['totals']['gpt']['usd'] = {'total': total, 'per_merged_pr': ratio}
            with self.assertRaises(ValueError):
                self.project(journey=self.source('journey.json', doc))

    def test_r2_usage_windows_follow_each_entity_utc_days_and_exports(self):
        # Spec is January 1 only. Ticket 3102 also has its own January 2
        # event, while its shared PR merged January 1. Assembly adds no days.
        doc = json.loads((FIX / 'journey.json').read_text())
        doc['tickets'][1]['events'][0]['at'] = '2030-01-02T12:00:00Z'
        day2 = copy.deepcopy(doc['daily_usage'][0])
        day2['date'] = '2030-01-02'
        doc['daily_usage'].append(day2)
        m = self.metrics(self.project(journey=self.source('journey.json', doc)))
        for identity, until in (('spec-3001', '2030-01-02T00:00:00Z'),
                                ('ticket-3101', '2030-01-02T00:00:00Z'),
                                ('ticket-3102', '2030-01-03T00:00:00Z')):
            row = m[identity + '-gpt-usd']
            self.assertEqual({'since': '2030-01-01T00:00:00Z', 'until': until,
                              'timezone': 'UTC'}, row['window'])
            self.assertEqual(AT, row['observed_at'])
            self.assertEqual('partial', row['state'])
        # Removing January 1 exports cannot give the spec a January 2 window.
        doc['daily_usage'].pop(0)
        for entity in doc['specs'] + doc['tickets']:
            for usage in entity['usage']:
                usage['missing_days'] = ['2030-01-01']
        m = self.metrics(self.project(journey=self.source('journey.json', doc)))
        self.assertIsNone(m['spec-3001-gpt-usd']['value'])
        self.assertIsNone(m['spec-3001-gpt-usd']['window'])
        self.assertEqual({'since': '2030-01-02T00:00:00Z',
                          'until': '2030-01-03T00:00:00Z', 'timezone': 'UTC'},
                         m['ticket-3102-gpt-usd']['window'])
        self.assertTrue(any('2030-01-01' in gap for gap in m['ticket-3102-gpt-usd']['prerequisites']))
        # An entity with no timed events has no inferable usage window.
        doc['specs'][0]['events'] = []
        m = self.metrics(self.project(journey=self.source('journey.json', doc)))
        self.assertIsNone(m['spec-3001-gpt-usd']['value'])
        self.assertIsNone(m['spec-3001-gpt-usd']['window'])

    def test_r3_injected_assembly_can_follow_sample_and_source_observation(self):
        for kind, filename in (('journey', 'journey.json'), ('ci', 'ci/point.json')):
            source = self.source(filename)
            source['observed_at'] = '2030-01-03T00:00:01Z'
            p = self.project(**{kind: source}, assembled_at='2030-01-03T00:00:02Z')
            row = self.metrics(p)['ci-estimate' if kind == 'ci' else 'daily-2030-01-01-gpt-usd']
            self.assertEqual('2030-01-03T00:00:01Z', row['observed_at'])
            # The sample is still AT; later source or earlier assembly refuses.
            with self.assertRaises(ValueError):
                self.project(**{kind: source}, assembled_at=AT)
            with self.assertRaises(ValueError):
                self.project(**{kind: source}, assembled_at='2030-01-02T23:59:59Z')
        a = copy.deepcopy(self.allocation)
        a['observed_at'] = '2030-01-03T00:00:01Z'
        m = self.metrics(self.project(synthetic_allocation=a, assembled_at='2030-01-03T00:00:02Z'))
        self.assertEqual(6, m['all-in']['value'])
        self.assertEqual('2030-01-03T00:00:01Z', m['all-in']['observed_at'])

    def test_r4_rejected_export_keeps_explicit_unknown_coverage_gap(self):
        doc = json.loads((FIX / 'journey.json').read_text())
        doc['daily_usage'].append({'date': None, 'merged_prs': None, 'totals': None})
        self.cost.J.validate(doc)
        p = self.project(journey=self.source('journey.json', doc))
        self.assertTrue(any('rejected' in gap.lower() and 'unknown' in gap.lower()
                            for gap in p['prerequisites']))
        m = self.metrics(p)
        self.assertEqual(6, m['daily-2030-01-01-gpt-usd']['value'])
        self.assertIsNone(m['all-in']['value'])
        self.assertEqual('partial', p['state'])
        doc['daily_usage'] = [{'date': None, 'merged_prs': None, 'totals': None}]
        p = self.project(journey=self.source('journey.json', doc))
        self.assertEqual('unavailable', p['state'])
        self.assertTrue(any('rejected' in gap.lower() and 'unknown' in gap.lower()
                            for gap in p['prerequisites']))
        self.assertIsNone(self.metrics(p)['all-in']['value'])

    def test_sources_refuse_invalid_json_binding_time_and_native_artifacts(self):
        for mode in ('duplicate-key', 'native', 'future-event', 'observation', 'path', 'link', 'ratio'):
            with self.subTest(mode=mode):
                doc = json.loads((FIX / 'journey.json').read_text())
                if mode == 'native': doc['history'] = 'complete'
                if mode == 'future-event': doc['pull_requests'][0]['events'][0]['at'] = '2030-01-04T00:00:00Z'
                if mode == 'ratio': doc['daily_usage'][0]['totals']['gpt']['usd']['per_merged_pr'] = 999
                source = self.source('journey.json', doc)
                if mode == 'duplicate-key': source['path'].write_text('{"schema":1,"schema":2}')
                if mode == 'observation': source['observed_at'] = '2030-01-01T00:00:00Z'
                if mode == 'path': source['source_path'] = '../private.json'
                if mode == 'link': source['evidence'] = ['javascript:bad']
                with self.assertRaises(ValueError): self.project(journey=source)

    def test_partial_component_cohort_and_source_windows_cannot_complete_total(self):
        a = copy.deepcopy(self.allocation)
        a['components'][0]['prs'] = [4001]
        p = self.project(synthetic_allocation=a)
        self.assertIsNone(self.metrics(p)['all-in']['value'])
        self.assertTrue(any('models' in gap and '4002' in gap for gap in p['prerequisites']))
        a = copy.deepcopy(self.allocation)
        a['components'][0]['window']['until'] = '2030-01-01T12:00:00Z'
        with self.assertRaises(ValueError): self.project(synthetic_allocation=a)


if __name__ == '__main__':
    unittest.main()
