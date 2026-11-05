#!/usr/bin/env python3
"""WR6 public journey-to-suite proofs, synthetic/offline only.

Plausible break: summing per-ticket bench rows counts the shared PR twice;
counting every verdict admits duplicate/self reports, and absent reviews look
like successes. Existing journey tests own parsing, not this suite projection.
Worked cohort: PR 4201 closes two tickets, has two independent CHANGES, one
repeated report, one self report, one answered and one unanswered fix round,
and one CI rerun. PR 4202 has an APPROVE; 4203 has no review; 4204 is absent.
Thus 3 evidenced merges, 2 reviewed, 1/2 evidenced CHANGES, 2 recorded fixes,
1 answered fix, 1 CI rerun. History remains unknown, including in fixtures.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('wr_rework', HERE / 'rework.py')
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
WIRE = (HERE / 'fixtures/rework/journeys.json').read_bytes()
AT = '2030-01-03T00:00:00Z'


class Rework(unittest.TestCase):
    def project(self, wire=WIRE, **overrides):
        args = dict(source_path='tools/war-room/fixtures/rework/journeys.json',
                    cohort='merged-synthetic-day', merged_prs=[4201, 4202, 4203, 4204],
                    since='2030-01-02T00:00:00Z', until=AT, observed_at=AT)
        args.update(overrides)
        return R.project(wire, **args)

    def metrics(self, provider):
        record = R.S.compose(AT, [provider])
        checked = R.S.loads(json.dumps(record))
        return {m['id']: m for p in checked['providers'] if p['slot'] == 'rework' for m in p['metrics']}

    def test_pr_identities_and_independent_arithmetic(self):
        p = self.project()
        m = self.metrics(p)
        self.assertEqual('partial', p['state'])
        for name, value in [('merged-prs', 3), ('reviewed-coverage', 2/3),
                            ('review-changes-share', 0.5), ('review-rounds', 4),
                            ('fix-rounds', 2), ('answered-fix-rounds', 1), ('ci-reruns', 1)]:
            self.assertEqual(value, m[name]['value'], name)
        self.assertEqual(dict(observed=2, expected=4, identities=['pr-4201','pr-4202'], numerator=1, denominator=2),
                         m['review-changes-share']['sample'])
        self.assertEqual(2, m['reviewed-coverage']['sample']['numerator'])
        self.assertEqual(3, m['reviewed-coverage']['sample']['denominator'])
        self.assertIn('4204', ' '.join(p['prerequisites']))
        self.assertIn('4203', ' '.join(p['prerequisites']))
        self.assertIn('unanswered', ' '.join(p['prerequisites']).lower())
        for metric in m.values():
            self.assertEqual('partial', metric['state'])
            self.assertEqual(hashlib.sha256(WIRE).hexdigest(), metric['source']['sha256'])
            self.assertEqual(AT, metric['observed_at'])
            self.assertEqual('unknown', metric['freshness'])
            self.assertEqual('merged-synthetic-day', metric['dimensions']['cohort'])

    def test_r1_repeated_excluded_ci_attempts_keep_partial_provider(self):
        # R1: repeated incomplete CI facts must compose as partial coverage.
        # The original fixture only has eligible attempts, so it misses duplicate
        # prerequisites. Keep literal zero/one rerun expectations independently.
        for eligible_reruns in (0, 1):
            for exclusion in ('post-merge', 'edited', 'mixed'):
                with self.subTest(eligible_reruns=eligible_reruns, exclusion=exclusion):
                    doc = json.loads(WIRE)
                    pr = doc['pull_requests'][0]
                    attempts = [e for e in pr['events'] if e['kind'] == 'ci_attempt']
                    eligible = attempts[:1] if eligible_reruns == 0 else attempts[:2]
                    first = attempts[1] if eligible_reruns == 0 else copy.deepcopy(attempts[1])
                    first.update(id='e17', source='s17', attempt=2 if eligible_reruns == 0 else 3)
                    second = copy.deepcopy(first)
                    second.update(id='e18', source='s18', attempt=first['attempt'] + 1)
                    excluded = [first, second]
                    if eligible_reruns == 1:
                        pr['events'].append(first)
                    pr['events'].append(second)
                    for index, event in enumerate(excluded):
                        edited = exclusion == 'edited' or (exclusion == 'mixed' and index == 0)
                        event.update(completeness='edited' if edited else 'complete',
                                     at=f'2030-01-02T{3+index if edited else 11+index:02}:00:00Z')
                        doc['sources'][event['source']] = (
                            f'https://github.com/synthetic-owner/work/actions/runs/4501/attempts/{event["attempt"]}')
                    # Keep source event order, including the unanswered fix round.
                    events = {e['id']: e for e in pr['events']}
                    pr['events'].sort(key=lambda e: e['at'] or events[e['after']]['at'])
                    R.J.validate(doc)
                    provider = self.project(json.dumps(doc).encode(), merged_prs=[4201])
                    metrics = self.metrics(provider)
                    self.assertEqual('partial', provider['state'])
                    self.assertEqual('partial', metrics['ci-reruns']['state'])
                    self.assertEqual(eligible_reruns, metrics['ci-reruns']['value'])
                    self.assertEqual(1, provider['prerequisites'].count(
                        'PR 4201: edited or post-merge CI attempt needs source evidence.'))
                    for event in eligible:
                        self.assertIn(doc['sources'][event['source']], metrics['ci-reruns']['evidence'])
                    for event in excluded:
                        self.assertNotIn(doc['sources'][event['source']], metrics['ci-reruns']['evidence'])

    def test_edited_absent_and_unfinished_evidence_cannot_be_success(self):
        doc = json.loads(WIRE)
        for pr in doc['pull_requests']:
            for event in pr['events']:
                if event['kind'] == 'verdict': event['completeness'] = 'edited'
        p = self.project(json.dumps(doc).encode())
        m = self.metrics(p)
        self.assertIsNone(m['review-changes-share']['value'])
        self.assertEqual(0, m['review-changes-share']['sample']['observed'])
        self.assertEqual('unavailable', m['review-changes-share']['state'])
        self.assertIn('edited', ' '.join(p['prerequisites']).lower())
        # An answered fix is a recorded answer, never evidence of resolution.
        self.assertEqual(0, m['answered-fix-rounds']['value'])

    def test_no_merges_or_no_reviews_are_explicit_unknowns(self):
        for cohort in ([], [4204]):
            with self.subTest(cohort=cohort):
                p = self.project(merged_prs=cohort)
                m = self.metrics(p)
                self.assertEqual('unavailable', p['state'])
                self.assertTrue(all(x['value'] is None for x in m.values()))
        p = self.project(merged_prs=[4203])
        m = self.metrics(p)
        self.assertIsNone(m['review-changes-share']['value'])
        self.assertEqual(0, m['reviewed-coverage']['value'])
        self.assertTrue(p['prerequisites'])

    def test_observed_zero_changes_keeps_history_partial(self):
        m = self.metrics(self.project(merged_prs=[4202]))
        self.assertEqual(0, m['review-changes-share']['value'])
        self.assertEqual('partial', m['review-changes-share']['state'])
        self.assertEqual(1, m['review-changes-share']['sample']['denominator'])

    def test_source_validator_and_cohort_bounds_fail_closed(self):
        bad = json.loads(WIRE)
        bad['pull_requests'].append(copy.deepcopy(bad['pull_requests'][0]))
        invalid = [json.dumps(bad).encode(), WIRE.replace(b'"duplicates": 2', b'"duplicates": 2, "duplicates": 2'),
                   WIRE.replace(b'"duplicates": 2', b'"duplicates": NaN')]
        for wire in invalid:
            with self.assertRaises(ValueError): self.project(wire)
        for args in [dict(merged_prs=[4201,4201]), dict(merged_prs=[True]),
                     dict(until='2030-01-01T00:00:00Z'), dict(observed_at='2030-01-02T00:00:00Z'),
                     dict(source_path='../private.json'), dict(cohort='thr_synth-secret')]:
            with self.subTest(args=args), self.assertRaises(ValueError): self.project(**args)
        # A selected PR outside the merge window is missing coverage, not a merge.
        p = self.project(since='2030-01-02T11:00:00Z')
        self.assertEqual('unavailable', p['state'])

    def test_existing_bench_cf4_and_input_are_preserved(self):
        doc = R.J.M.load(WIRE)
        R.J.validate(doc)
        bench, findings = R.J.bench(doc), R.J.cf4(doc)
        # Independent source-contract literals: per-ticket repetition stays in
        # bench; WR6 consumes the PR identities instead. CF4 owns finding kinds.
        self.assertEqual([3,3,1,0], [r['rounds'] for r in bench['tickets']])
        self.assertEqual([2,2,0,0], [r['fix_rounds'] for r in bench['tickets']])
        self.assertEqual([1,1,0,0], [r['reruns'] for r in bench['tickets']])
        self.assertEqual([False,False,True,None], [r['first_time_approval'] for r in bench['tickets']])
        self.assertEqual({'missing-proof':0,'stale-docs':0,'spec-mismatch':0,'fail-open':1,'unknown':1},
                         findings['by_kind'])
        self.assertEqual(['F1','F2'], [f['key'] for f in findings['findings']])
        self.assertEqual('https://github.com/synthetic-owner/work/pull/4201#issuecomment-5004',
                         findings['provenance']['F1'])
        self.assertEqual(2, self.metrics(self.project())['fix-rounds']['value'])

    def test_cli_provider_and_sanitized_refusal(self):
        command = [sys.executable, '-I', str(HERE/'rework.py'),
                   str(HERE/'fixtures/rework/journeys.json'),
                   '--source-path','tools/war-room/fixtures/rework/journeys.json',
                   '--cohort','merged-synthetic-day','--pr','4201','--pr','4202',
                   '--since','2030-01-02T00:00:00Z','--until',AT,'--observed-at',AT]
        p = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(0, p.returncode, p.stderr)
        self.metrics(json.loads(p.stdout))
        p = subprocess.run(command + ['--pr','4201'], capture_output=True, text=True)
        self.assertEqual(1, p.returncode)
        self.assertEqual('', p.stdout)
        self.assertEqual('refused: invalid rework input\n', p.stderr)


if __name__ == '__main__': unittest.main()
