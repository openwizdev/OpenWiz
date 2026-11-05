#!/usr/bin/env python3
"""FA3: black-box lifecycle proof and planted violations; no live endpoints."""
import argparse
import copy
import json
import importlib.util
from pathlib import Path
import shutil
import time
import tempfile
import unittest
from unittest import mock
import sys
sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('load', HERE / 'load.py')
load = importlib.util.module_from_spec(spec)
spec.loader.exec_module(load)


seams = load.extension('test_seams')
MeasurementIdentityProof = seams.MeasurementIdentityProof
InstalledBuildProof = seams.InstalledBuildProof


class LoadProof(unittest.TestCase):
    report_path = None
    trace_path = None
    scale_report_path = None

    @classmethod
    def setUpClass(cls):
        cls.report = json.loads(cls.trace_path.read_text()) if cls.trace_path else load.run(scaled=True)
        if cls.report_path:
            cls.report_path.write_text(json.dumps(cls.report, indent=2) + '\n')
        cls.scale = load.extension('scale')
        if cls.scale_report_path:
            cls.scale_report_path.write_text(json.dumps(cls.scale.report(cls.report), indent=2) + '\n')
        events = cls.report['events']
        ticks = cls.report['ticks']
        peak = max(sum(t['points'] for t in ticks if end['now'] - 3600 < t['now'] <= end['now']) for end in ticks)
        print(f'100 tickets / 5 specs / {len(ticks)} spec ticks; '
              f'{sum(t["questions"] for t in ticks)} check questions; '
              f'peak {peak}/1250 GraphQL points per simulated hour; '
              f'{sum(e["kind"] == "archive" for e in events)} archives', flush=True)

    def test_50_active_mixed_roles(self):
        intervals = self.scale.intervals(self.report)
        self.assertEqual(max(i['builders'] + i['reviewers'] for i in intervals), 50,
                         'S5 synthetic active execution peak')
        self.assertTrue(any(i['builders'] + i['reviewers'] == 50 and i['builders'] and i['reviewers']
                            for i in intervals), 'S5 both roles must overlap')

    def test_transport_and_merge_measurements(self):
        self.scale.verify(self.report)
        summary = self.scale.report(self.report)
        self.assertEqual(summary['metrics']['verified_merges'], 100)
        self.assertEqual(summary['metrics']['starts']['accepted'], 200)
        revision = next(e for e in self.report['events'] if e.get('args', [])[:2] == ['issue', 'view'] and e['args'][4] == 'subIssues')
        self.assertEqual([h['rows'] for h in revision['http']], [7, 7, 6])
        self.assertGreater(summary['budgets']['rest']['requests'] + summary['budgets']['graphql']['requests'],
                           sum(e['tool'] == 'gh' for e in self.report['events']))
        for fault, finding in [('page', 'S6 omitted HTTP page'), ('http-budget', 'S6 HTTP budget overrun'), ('rest-budget', 'S6 HTTP budget overrun: rest'),
                               ('merge-starvation', 'S6 merge starvation'), ('merge-readback', 'S6 unverified merge')]:
            report = copy.deepcopy(self.report)
            with self.subTest(fault=fault):
                if fault == 'page':
                    next(e for e in report['events'] if e.get('paginated') and len(e['http']) > 1)['http'].pop()
                elif fault == 'http-budget':
                    next(h for e in report['events'] for h in e.get('http', []) if h['api'] == 'graphql')['cost'] += 5001
                elif fault == 'rest-budget':
                    event = next(e for e in report['events'] if e['tool'] == 'gh' and e['http'][0]['api'] == 'rest')
                    event.update(http=[dict(api='rest', page=1, cost=0, rows=1) for _ in range(5001)], http_expected=5001, paginated=False)
                elif fault == 'merge-starvation':
                    next(e for e in report['events'] if e['kind'] == 'merge-readback')['now'] += 1801
                else:
                    next(e for e in report['events'] if e['kind'] == 'merge-readback')['merged'] = False
                with self.assertRaisesRegex(AssertionError, finding):
                    self.scale.verify(report)

    def test_report_preserves_safety_and_measurement_snapshot(self):
        # A public report must reject unsafe traces and omitted shared consumers.
        report = copy.deepcopy(self.report)
        thread = next(q['thread'] for q in report['quiet'] if q['role'] == 'reviewer')
        for e in report['events']:
            if e['kind'] == 'output' and e['thread'] == thread:
                e['kind'] = 'output-omitted'
        with self.assertRaisesRegex(AssertionError, 'S3 quiet reviewer'):
            self.scale.report(report)
        report = copy.deepcopy(self.report)
        for e in report['events']:
            if e['tool'] == 'shared': e['tool'] = 'workload'
        with self.assertRaisesRegex(AssertionError, 'S6 shared consumer omission'):
            self.scale.report(report)
        # Replay must work from recorded metadata, without reopening local files.
        with mock.patch.object(Path, 'read_bytes', side_effect=AssertionError('reopened current config')), \
             mock.patch.object(Path, 'read_text', side_effect=AssertionError('reopened current config')):
            result = self.scale.report(self.report)
        self.assertEqual(result['candidate'], self.report['identity']['candidate'])
        legacy = copy.deepcopy(self.report)
        legacy['identity'].pop('measurement_model', None)
        partial = self.scale.report(legacy)
        self.assertEqual(partial['state'], 'partial')
        self.assertIsNone(partial['measurement_model'])
        with self.assertRaises(ValueError):
            self.scale.api.compare(partial, partial)

    def test_100_ticket_lifecycle(self):
        load.verify(self.report)

    def test_planted_violations(self):
        # The guard must reject each real observed-effect violation by name.
        for fault, finding in [('duplicate', 'S2 duplicate'),
                               ('quiet-builder', 'S3 quiet builder'),
                               ('quiet-reviewer', 'S3 quiet reviewer'),
                               ('budget', 'S4 budget'),
                               ('missed', 'S2 missed'),
                               ('owner', 'S1 owner'),
                               ('archive', 'S1 archive'),
                               ('start-owner', 'S1 owner'),
                               ('point-cost', 'S4 budget'),
                               ('review-label', 'S2 missed reviewer'),
                               ('early-archive', 'S1 archive'),
                               ('unsafe-merge', 'S2 unsafe merge'),
                               ('target', 'S1 target'),
                               ('actual-findings-target', 'S1 notification'),
                               ('actual-recheck-role', 'S1 notification'),
                               ('same-tick-archive', 'S1 archive')]:
            with self.subTest(fault=fault):
                report = copy.deepcopy(self.report)
                load.plant(report, fault)
                with self.assertRaisesRegex(AssertionError, finding):
                    load.verify(report)

    def test_merge_then_archive_in_same_tick_is_valid(self):
        report = copy.deepcopy(self.report)
        archive = next(e for e in report['events'] if e['kind'] == 'archive')
        ticket = next(e['ticket'] for e in report['events'] if e['kind'] == 'spawn' and e['thread'] == archive['thread'])
        merge = next(e for e in report['events'] if e['kind'] == 'merge' and e['ticket'] == ticket)
        archive['now'] = merge['now']
        load.verify(report)


class HeadProof(unittest.TestCase):
    """R1: the assigned head survives changes before execution/reporting.

    Share only immutable setup; every case gets its own world, command log,
    tasks and fake thread state. Exercise unchanged driver/fake endpoints.
    """
    A, B = 'a' * 40, 'b' * 40

    @classmethod
    def setUpClass(cls):
        cls.base_dir = tempfile.TemporaryDirectory(prefix='fa3-head-base-')
        cls.prototype = load.Workload(cls.base_dir.name, load.SCRIPTS / 'fleet.sh')

    @classmethod
    def tearDownClass(cls):
        cls.base_dir.cleanup()

    def setUp(self):
        self.case_dir = tempfile.TemporaryDirectory(prefix='fa3-head-case-')
        self.addCleanup(self.case_dir.cleanup)
        w = copy.copy(self.prototype)
        w.root = Path(self.case_dir.name)
        shutil.copytree(self.prototype.root / 'bin', w.root / 'bin')
        w.path, w.events = w.root / 'world.json', w.root / 'events.jsonl'
        w.world = copy.deepcopy(self.prototype.world)
        w.tasks, w.ticks, w.quiet = [], [], []
        w.builders, w.reviewers, w.review_starts = {}, {}, {}
        w.deadline = time.monotonic() + 60
        w.env = dict(self.prototype.env, PATH=f'{w.root / "bin"}:{self.prototype.env["PATH"]}',
                     FAKE_GH_WORLD=str(w.path), LOAD_EVENTS=str(w.events), LAUNCH_FLEET_STATE=str(w.root / 'private-routing.json'),
                     FAKE_GH_LOG=str(w.root / 'gh.log'), LOAD_FLEET='thr_synfleet100')
        w.later(0, 'open', 1004)
        w.advance()
        w.item(2004)['head'] = self.A
        self.w = w

    def finish_review(self):
        self.w.now += 600
        self.w.env['LAUNCH_FLEET_NOW'] = str(self.w.now)
        self.w.advance()
        self.assertEqual(self.w.item(2004)['comments'][-1]['body'], f'VERDICT: APPROVE at {self.A}')
        with self.assertRaises(AssertionError):
            self.w.command(['gh', 'pr', 'merge', '2004', '--merge', '--match-head-commit', self.B])
        self.assertEqual(self.w.item(2004)['state'], 'OPEN')

    def test_review_head_changes_before_verdict(self):
        self.w.dispatch(f'review #2004 for #1004 at {self.A}: first review')
        self.w.item(2004)['head'] = self.B
        self.finish_review()

    def test_stale_review_preserves_requested_head(self):
        self.w.item(2004)['head'] = self.B
        self.w.dispatch(f'review #2004 for #1004 at {self.A}: first review')
        self.finish_review()

    def test_stale_recheck_preserves_requested_head(self):
        thread = self.w.agent('reviewer', 1004)
        self.w.reviewers[1004] = thread
        self.w.review_starts[1004] = self.A
        self.w.item(2004)['head'] = self.B
        self.w.dispatch(f're-check #2004 for #1004 at {self.A}: tell its reviewer, thread {thread}')
        self.finish_review()

    def test_stale_merge_cannot_merge_current_head(self):
        self.w.item(2004)['head'] = self.B
        self.w.note(2004, f'VERDICT: APPROVE at {self.B}')
        with self.assertRaises(AssertionError):
            self.w.dispatch(f'merge #2004 for #1004 at {self.A}: APPROVE and CI green')
        self.assertEqual(self.w.item(2004)['state'], 'OPEN')

    def test_notifications_preserve_requested_head(self):
        builder = self.w.agent('builder', 1004)
        reviewer = self.w.agent('reviewer', 1004)
        self.w.builders[1004] = (builder, 0)
        self.w.reviewers[1004] = reviewer
        self.w.review_starts[1004] = self.A
        self.w.item(2004)['head'] = self.B
        for action, thread in [('findings', builder), ('CI failed', builder), ('check review', reviewer)]:
            with self.subTest(action=action):
                self.w.dispatch(f'{action} #2004 for #1004 at {self.A}: tell thread {thread}')
                message = next(e['args'][3] for e in reversed(self.w.read_events()) if e['kind'] == 'tell')
                self.assertEqual(message, f'{action} #2004 for #1004 at {self.A}')


class TargetProof(unittest.TestCase):
    def test_foreign_target_from_due_line_is_refused(self):
        with tempfile.TemporaryDirectory(prefix='fa3-target-') as root:
            workload = load.Workload(root, load.SCRIPTS / 'fleet.sh')
            workload.env['LOAD_FLEET'] = 'thr_synfleet100'
            own = workload.agent('builder', 1001)
            workload.builders[1001] = (own, workload.note(1001, 'launch-fleet: starting'))
            workload.world['pulls'].append(dict(number=2001, head='a' * 40, comments=[]))
            workload.env['LOAD_FLEET'] = 'thr_synfleet200'
            foreign = workload.agent('builder', 1021)
            workload.env['LOAD_FLEET'] = 'thr_synfleet100'
            with self.assertRaisesRegex(AssertionError, 'S1 owner'):
                workload.dispatch(f'findings #2001 for #1001 at {"a" * 40}: tell its builder, thread {foreign}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--verify-report', type=Path)
    parser.add_argument('--scale-report', type=Path)
    args, remaining = parser.parse_known_args()
    LoadProof.report_path = args.report
    LoadProof.trace_path = args.verify_report
    LoadProof.scale_report_path = args.scale_report
    unittest.main(argv=[sys.argv[0], *remaining])
