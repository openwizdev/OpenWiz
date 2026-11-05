#!/usr/bin/env python3
"""#2311: offline public CLI proofs; all timestamps/identities are synthetic.

The old benchmark tests never exercise actual-push or complete-required-result
measurement. These independent literals catch a run-creation proxy, lost
privacy receipt, survivor filtering and duplicated attempt/credit accounting.
"""
import copy
import fnmatch
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / 'fixtures/required/cohorts.json'


def seed():
    return json.loads(FIXTURE.read_text())


def items(bundle):
    return bundle['pages'][0]['items']


class Required(unittest.TestCase):
    def run_report(self, data, error=None):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text(json.dumps(data))
            before = path.read_bytes()
            run = subprocess.run([sys.executable, '-I', str(HERE/'required.py'), str(path)],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['input.json'])
        self.assertEqual(run.returncode, 1 if error else 0, run.stderr)
        if error:
            self.assertEqual(run.stdout, '')
            self.assertIn(error, run.stderr)
            return None
        return json.loads(run.stdout)

    def test_actual_push_to_all_required_results_and_comparable_cut(self):
        report = self.run_report(seed())
        before, after = report['cohorts']
        self.assertEqual(before['push_to_required_seconds'], {'n': 1, 'median': 600, 'p90': 600})
        self.assertEqual(after['push_to_required_seconds'], {'n': 1, 'median': 300, 'p90': 300})
        self.assertEqual(before['job_queue_seconds'], {'n': 2, 'median': 45, 'p90': 60})
        self.assertEqual(before['jobs'], 2)
        self.assertEqual(before['runners'], {'synthetic-hosted': 1, 'synthetic-owned': 1})
        self.assertEqual(report['comparisons'][0]['median_reduction_seconds'], 300)
        self.assertFalse(report['comparisons'][0]['additive'])
        self.assertEqual(report['cost']['whole_bill_usd'], 12)
        self.assertEqual(report['cost']['evidence'], 'synthetic')
        self.assertEqual(report['live_success'], 'Unverified')
        self.assertEqual(len(report['input_sha256']), 64)

    def test_unknown_push_is_never_workflow_creation(self):
        data = seed()
        data['observations'][0]['push'] = None
        report = self.run_report(data)
        self.assertIsNone(report['observations'][0]['push_to_required_seconds'])
        self.assertEqual(report['cohorts'][0]['push_to_required_seconds']['n'], 0)
        self.assertIsNone(report['comparisons'][0]['median_reduction_seconds'])
        data['observations'][0]['push'] = dict(at='2030-01-01T00:02:00Z',
            kind='workflow-created', source='synthetic-run', head='a'*40)
        self.run_report(data, 'push kind')

    def test_all_outcomes_remain_enrolled_and_block_success_claim(self):
        for status, conclusion, expected in [('completed', 'failure', 'failed'),
                ('completed', 'cancelled', 'cancelled'), ('in_progress', None, 'unfinished')]:
            with self.subTest(expected=expected):
                data = seed()
                run = items(data['observations'][0]['runs'])[1]
                job = items(run['jobs'])[0]
                job.update(status=status, conclusion=conclusion)
                if status != 'completed':
                    job['completed_at'] = None
                run.update(status=status, conclusion=conclusion)
                report = self.run_report(data)
                self.assertEqual(report['cohorts'][0]['samples'], 1)
                self.assertEqual(report['cohorts'][0]['outcomes'], {expected: 1})
                self.assertFalse(report['cohorts'][0]['timing_target_met'])
        data = seed()
        data['observations'][0]['superseded'] = True
        report = self.run_report(data)
        self.assertEqual(report['cohorts'][0]['outcomes'], {'superseded': 1})
        self.assertEqual(report['cohorts'][0]['samples'], 1)

    def test_missing_receipts_and_partial_pages_never_become_complete(self):
        data = seed()
        bundle = data['observations'][0]['runs']
        bundle['total_count'] = 1
        items(bundle).pop()
        report = self.run_report(data)
        self.assertEqual(report['cohorts'][0]['outcomes'], {'missing': 1})
        self.assertIsNone(report['observations'][0]['required_result_at'])
        for where in ('membership', 'runs', 'jobs'):
            with self.subTest(where=where):
                data = seed()
                bundle = (data['cohorts'][0]['membership'] if where == 'membership' else
                          data['observations'][0]['runs'] if where == 'runs' else
                          items(data['observations'][0]['runs'])[0]['jobs'])
                bundle['total_count'] += 1
                self.run_report(data, 'pagination')

    def test_foreign_identity_and_duplicates_are_rejected(self):
        for field, value in [('head', 'f'*40), ('run', 999), ('attempt', 2)]:
            data = seed()
            items(items(data['observations'][0]['runs'])[0]['jobs'])[0][field] = value
            self.run_report(data, 'job identity')
        data = seed()
        data['observations'][1]['runs'] = copy.deepcopy(data['observations'][0]['runs'])
        data['observations'][1]['head'] = 'a'*40
        data['observations'][1]['push']['head'] = 'a'*40
        data['observations'][1]['push']['at'] = '2030-01-02T00:00:00Z'
        self.run_report(data, 'duplicate attempt')
        data = seed()
        data['cohorts'][1]['membership'] = copy.deepcopy(data['cohorts'][0]['membership'])
        self.run_report(data, 'membership')

    def test_rerun_cost_and_jobs_count_once_but_old_green_cannot_supply_receipt(self):
        data = seed()
        bundle = data['observations'][0]['runs']
        old = items(bundle)[0]
        old['current'] = False
        latest = copy.deepcopy(old)
        latest.update(attempt=2, current=True, status='in_progress', conclusion=None)
        job = items(latest['jobs'])[0]
        job.update(id=301, attempt=2, status='in_progress', conclusion=None, completed_at=None)
        items(bundle).append(latest)
        bundle['total_count'] = 3
        report = self.run_report(data)
        self.assertEqual(report['cohorts'][0]['jobs'], 3)
        self.assertEqual(report['cohorts'][0]['attempts'], 3)
        self.assertEqual(report['cohorts'][0]['outcomes'], {'unfinished': 1})
        self.assertIsNone(report['observations'][0]['required_result_at'])

    def test_unknown_cost_and_estimates_are_not_whole_bill_proof(self):
        for patch in ({'kind': 'list-estimate'}, {'complete': False}):
            data = seed()
            data['cost'].update(patch)
            report = self.run_report(data)
            self.assertIsNone(report['cost']['whole_bill_usd'])
            self.assertEqual(report['cost']['reported_components_usd'], 12)
        data = seed()
        data['cost']['components'][0]['microusd'] = None
        report = self.run_report(data)
        self.assertIsNone(report['cost']['whole_bill_usd'])
        self.assertTrue(report['cost']['gaps'])

    def test_comparison_cannot_filter_runners_or_change_workload(self):
        for field, value in [('runner_policy', 'free-only'), ('workload', 'docs')]:
            data = seed()
            data['cohorts'][1]['criteria'][field] = value
            self.run_report(data, 'criteria')
        data = seed()
        data['comparisons'].append(copy.deepcopy(data['comparisons'][0]))
        self.run_report(data, 'duplicate cut')

    def test_combined_batch_keeps_identity_and_never_counts_members_as_attempts(self):
        data = seed()
        batch = {'id': 'synthetic-batch', 'base': '0'*40, 'head': 'a'*40,
                 'members': ['b'*40, 'a'*40], 'source': 'synthetic-shadow-receipt'}
        data['observations'][0]['batch'] = batch
        report = self.run_report(data)
        self.assertEqual(report['observations'][0]['batch'], batch)
        self.assertEqual(report['cohorts'][0]['attempts'], 2)
        self.assertEqual(report['cohorts'][0]['samples'], 1)

    def test_multisample_median_p90_and_all_jobs_have_literal_denominators(self):
        data = seed()
        original = copy.deepcopy(data['observations'][0])
        data['observations'] = [data['observations'][1]]
        members = []
        for index, minute in enumerate([4, 6, 10, 18, 22]):
            row = copy.deepcopy(original)
            row['id'] = 'sample-' + str(index)
            row['push_event_id'] = 'synthetic-event-' + str(index)
            members.append(row['id'])
            row['head'] = f'{index+100:040x}'
            row['push'].update(head=row['head'], source=row['id'])
            for offset, run in enumerate(items(row['runs'])):
                run.update(run=1000+index*2+offset, head=row['head'])
                job = items(run['jobs'])[0]
                job.update(id=2000+index*2+offset, run=run['run'], head=row['head'],
                           completed_at=f'2030-01-01T00:{minute-offset:02}:00Z')
            data['observations'].append(row)
        data['cohorts'][0]['membership']['total_count'] = 5
        data['cohorts'][0]['membership']['pages'][0]['items'] = members
        report = self.run_report(data)
        self.assertEqual(report['cohorts'][0]['push_to_required_seconds'],
                         {'n': 5, 'median': 600, 'p90': 1320})
        self.assertEqual(report['cohorts'][0]['jobs'], 10)
        self.assertEqual(report['cohorts'][0]['outcomes'], {'success': 5})
        self.assertFalse(report['cohorts'][0]['timing_target_met'])

    def test_current_run_failure_cannot_be_hidden_by_one_success_receipt(self):
        data = seed()
        items(data['observations'][0]['runs'])[0]['conclusion'] = 'failure'
        report = self.run_report(data)
        self.assertEqual(report['cohorts'][0]['outcomes'], {'failed': 1})
        self.assertFalse(report['cohorts'][0]['timing_target_met'])

    def test_current_run_must_be_latest_across_workflow_run_ids(self):
        # A new run ID, unlike a rerun attempt, was absent from the old proof.
        for status, conclusion in [('in_progress', None), ('completed', 'failure')]:
            for select_new in (False, True):
                with self.subTest(status=status, select_new=select_new):
                    data = seed()
                    bundle = data['observations'][1]['runs']
                    old = items(bundle)[0]
                    new = copy.deepcopy(old)
                    old['current'] = not select_new
                    new.update(run=21, current=select_new, status=status, conclusion=conclusion,
                               created_at='2030-01-02T00:06:00Z')
                    items(new['jobs'])[0].update(id=211, run=21, status=status, conclusion=conclusion,
                        created_at='2030-01-02T00:06:00Z', started_at='2030-01-02T00:06:30Z',
                        completed_at=None if status == 'in_progress' else '2030-01-02T00:07:00Z')
                    items(bundle).append(new)
                    bundle['total_count'] += 1
                    if not select_new:
                        self.run_report(data, 'current run is stale')
                    else:
                        report = self.run_report(data)
                        self.assertEqual(report['cohorts'][1]['outcomes'],
                                         {'unfinished' if status == 'in_progress' else 'failed': 1})
                        self.assertFalse(report['cohorts'][1]['timing_target_met'])
                        self.assertEqual(report['cohorts'][1]['jobs'], 3)
                        if status == 'in_progress':
                            self.assertIsNone(report['observations'][1]['push_to_required_seconds'])

    def test_current_run_order_must_be_unambiguous(self):
        for created in (None, '2030-01-02T00:02:00Z'):
            with self.subTest(created=created):
                data = seed()
                bundle = data['observations'][1]['runs']
                other = copy.deepcopy(items(bundle)[0])
                other.update(run=21, current=False, created_at=created)
                items(other['jobs'])[0].update(id=211, run=21)
                items(bundle).append(other)
                bundle['total_count'] += 1
                self.run_report(data, 'ambiguous current run')

    def test_one_push_cannot_be_split_across_capture_sources(self):
        # Disjoint receipt subsets bypass attempt/job deduplication.
        data = seed()
        original = data['observations'][0]
        duplicate = copy.deepcopy(original)
        duplicate['id'] = 'same-event-other-capture'
        duplicate['push']['source'] = 'synthetic-second-capture'
        items(original['runs']).pop()
        items(duplicate['runs']).pop(0)
        original['runs']['total_count'] = duplicate['runs']['total_count'] = 1
        data['observations'].append(duplicate)
        membership = data['cohorts'][0]['membership']
        items(membership).append(duplicate['id'])
        membership['total_count'] += 1
        self.run_report(data, 'duplicate push membership')

    def test_distinct_push_events_of_same_head_and_source_stay_enrolled(self):
        data = seed()
        later = copy.deepcopy(data['observations'][0])
        later.update(id='later-push', push_event_id='synthetic-later-event')
        later['push']['at'] = '2030-01-01T00:01:00Z'
        for run in items(later['runs']):
            run['run'] += 100
            job = items(run['jobs'])[0]
            job.update(id=job['id']+100, run=run['run'])
        data['observations'].append(later)
        membership = data['cohorts'][0]['membership']
        items(membership).append(later['id'])
        membership['total_count'] += 1
        report = self.run_report(data)
        before = report['cohorts'][0]
        self.assertEqual(before['samples'], 2)
        self.assertEqual(before['outcomes'], {'success': 2})
        self.assertEqual(before['push_to_required_seconds'], {'n': 2, 'median': 570, 'p90': 600})
        self.assertEqual(before['jobs'], 4)

    def test_pending_job_reports_censored_wait_instead_of_zero(self):
        data = seed()
        run = items(data['observations'][0]['runs'])[0]
        run.update(status='queued', conclusion=None)
        job = items(run['jobs'])[0]
        job.update(status='queued', conclusion=None, started_at=None, completed_at=None, runner=None)
        report = self.run_report(data)
        observed = report['observations'][0]
        self.assertEqual(observed['censored_queue_seconds'], [172680])
        self.assertEqual(observed['job_queue_seconds'], {'n': 1, 'median': 60, 'p90': 60})
        self.assertEqual(observed['allocated_jobs'], 1)

    def test_unknown_in_progress_start_does_not_establish_wait(self):
        # The queued proof above positively establishes no allocation; an
        # in-progress job with a lost timestamp may already have been running.
        data = seed()
        run = items(data['observations'][0]['runs'])[0]
        run.update(status='in_progress', conclusion=None)
        job = items(run['jobs'])[0]
        job.update(status='in_progress', conclusion=None, started_at=None,
                   completed_at=None, runner=None)
        report = self.run_report(data)
        observed = report['observations'][0]
        self.assertEqual(observed['censored_queue_seconds'], [])
        self.assertEqual(observed['job_queue_seconds'], {'n': 1, 'median': 60, 'p90': 60})
        self.assertIn('unknown/censored job queue: 101', observed['gaps'])
        self.assertEqual(report['cohorts'][0]['outcomes'], {'unfinished': 1})
        self.assertFalse(report['cohorts'][0]['timing_target_met'])

    def test_cohort_repository_and_provenance_must_match(self):
        data = seed()
        data['observations'][0]['repository'] = 'foreign-owner/foreign-repo'
        self.run_report(data, 'cohort repository')
        data = seed()
        data['observations'][0]['push']['source'] = ''
        self.run_report(data, 'nonempty')

    def test_untrusted_shapes_clocks_pages_and_duplicate_keys_refuse(self):
        for value in (True, 0, -1, '1', None):
            data = seed()
            items(data['observations'][0]['runs'])[0]['attempt'] = value
            self.run_report(data, 'integer')
        for value in ('2030-01-01T00:01:00Z', '2031-01-01T00:00:00Z', 'bad'):
            data = seed()
            items(items(data['observations'][0]['runs'])[0]['jobs'])[0]['completed_at'] = value
            self.run_report(data, 'clock' if value.endswith('00:01:00Z') else
                            'freeze' if value.startswith('2031') else 'timestamp')
        data = seed()
        data['cohorts'][0]['membership']['pages'][0]['next'] = True
        self.run_report(data, 'pagination')
        data = seed()
        data['cohorts'][0]['membership']['pages'][0]['items'] = ['unknown-push']
        self.run_report(data, 'membership')
        data = seed()
        data['cost']['components'][0]['microusd'] = -1
        self.run_report(data, 'integer')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'duplicate.json'
            path.write_text('{"schema":"first","schema":"second"}')
            run = subprocess.run([sys.executable, '-I', str(HERE/'required.py'), str(path)],
                                 capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 1)
            self.assertEqual(run.stdout, '')
            self.assertIn('duplicate JSON key', run.stderr)

    def test_existing_benchmark_proof_executes_suite_and_selects_its_inputs(self):
        # CI registration is an owning execution contract, not test discovery by filename.
        workflow = (HERE.parents[1]/'.github/workflows/ci-bench.yml').read_text()
        proof = workflow.split('  proof:\n', 1)[1].split('\n  publish:', 1)[0]
        self.assertIn('          python3 -I tools/ci-bench/test_required.py\n', proof)
        paths = workflow.split('    paths:\n', 1)[1].split('\npermissions:', 1)[0]
        patterns = [line.strip()[3:-1] for line in paths.splitlines() if line.strip().startswith("- '")]
        for path in ('tools/ci-bench/required.py', 'tools/ci-bench/test_required.py',
                     'tools/ci-bench/fixtures/required/cohorts.json'):
            self.assertTrue(any(fnmatch.fnmatchcase(path, glob) for glob in patterns), path)

    def test_multiple_pages_and_literal_percentiles(self):
        data = seed()
        bundle = data['observations'][0]['runs']
        second = items(bundle).pop()
        bundle['pages'][0]['next'] = True
        bundle['pages'].append({'number': 2, 'next': False, 'items': [second]})
        report = self.run_report(data)
        self.assertEqual(report['cohorts'][0]['push_to_required_seconds']['median'], 600)


if __name__ == '__main__':
    unittest.main()
