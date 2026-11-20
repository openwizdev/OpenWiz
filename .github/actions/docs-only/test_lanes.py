#!/usr/bin/env python3
"""X5's real final-step adapter on synthetic GitHub needs and receipts."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


class Lanes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.receipts = self.path / 'receipts'; self.receipts.mkdir()
        self.plan = json.loads((ROOT / 'ci/selection/valid/full-nightly.json').read_text())
        # #1264: the contract's example still plans the web view, the site
        # copy and the export, which went; the plan this lane runs skips them.
        gone = {'decision': 'skip', 'reason': 'the web view, the site copy and the export went in #1264'}
        self.plan['builds']['web_export'] = gone
        self.plan['lanes']['web'] = gone
        self.plan['lanes']['site']['tests'] = ['release:package']
        raw = json.dumps(self.plan)
        self.sha = hashlib.sha256(raw.encode()).hexdigest()
        (self.path / 'ci-selection.json').write_text(raw)
        self.dispatch = {**dict.fromkeys(('lint-rust','build-site','image-skills'), True),
                         'rust': True, 'release': True,
                         'skills': ['launch-fleet','plan-graph','triage'], 'trace': False, 'planted': False,
                         'plan_sha256': self.sha}
        (self.path / 'ci-dispatch.json').write_text(json.dumps(self.dispatch))
        self.needs = {k: {'result': 'success'} for k in
                      ('changes','always','rust','release','skills','launch-fleet')}
        self.expected = {k: self.plan['lanes'][k]['tests'] for k in ('always','rust')}
        self.expected.update(release=['release:package'])
        self.expected.update({'skill:'+s['skill']: s['tests'] for s in self.plan['lanes']['skills']})
        for name, tests in self.expected.items():
            self.receipt(name, tests)

    def receipt(self, name, tests):
        path = self.receipts / (name.replace(':','-') + '.json')
        path.write_text(json.dumps({'lane': name, 'tests': tests, 'plan_sha256': self.sha, 'run': self.plan['run']}))
        return path

    def run_finish(self):
        (self.path / 'needs.json').write_text(json.dumps(self.needs))
        env = dict(os.environ, GITHUB_RUN_ID=str(self.plan['run']['id']),
                   GITHUB_RUN_ATTEMPT=str(self.plan['run']['attempt']), GITHUB_EVENT_NAME=self.plan['run']['event'])
        return subprocess.run([sys.executable,'-I',str(HERE/'run.py'),'finish',str(self.path),
                               str(self.path/'needs.json'),str(self.receipts)],
                              env=env,capture_output=True,text=True,timeout=10)

    def test_every_planned_job_and_skill_member_passed(self):
        result = self.run_finish()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('every planned lane passed',result.stdout)

    def test_actual_job_failure_cancellation_and_absence_fail(self):
        original = json.loads(json.dumps(self.needs))
        for job in ('changes','always','rust','release','skills','launch-fleet'):
            for state in ('failure','cancelled','skipped',None):
                with self.subTest(job=job,state=state):
                    self.needs = json.loads(json.dumps(original))
                    if state is None: del self.needs[job]
                    else: self.needs[job]['result'] = state
                    result = self.run_finish()
                    self.assertEqual(result.returncode,1,result.stderr)
                    self.assertIn(job,result.stderr)

    def test_successful_matrix_aggregate_cannot_hide_a_missing_member(self):
        self.receipt('skill:plan-graph',self.expected['skill:plan-graph']).unlink()
        result = self.run_finish()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('skill:plan-graph',result.stderr)

    def test_receipts_bind_the_exact_tests_and_plan(self):
        for change in ('tests','plan_sha256','run'):
            with self.subTest(change=change):
                p = self.receipt('rust',self.expected['rust'])
                entry = json.loads(p.read_text())
                entry[change] = [] if change=='tests' else ('0'*64 if change=='plan_sha256' else {})
                p.write_text(json.dumps(entry))
                result = self.run_finish()
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('rust',result.stderr)
                self.receipt('rust',self.expected['rust'])

    def test_dispatch_cannot_be_reused_for_different_plan_bytes(self):
        with (self.path/'ci-selection.json').open('a') as f: f.write('\n')
        result = self.run_finish()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('plan',result.stderr)


    def check_shards(self, kind, records):
        paths = []
        for i, entry in enumerate(records):
            path = self.path / f'ran-{i}.json'
            path.write_text(json.dumps(entry))
            paths.append(str(path))
        env = dict(os.environ, GITHUB_RUN_ID=str(self.plan['run']['id']),
                   GITHUB_RUN_ATTEMPT=str(self.plan['run']['attempt']), GITHUB_EVENT_NAME=self.plan['run']['event'])
        return subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), 'check-shards', str(self.path), kind, *paths],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)

    def test_shard_records_must_run_every_unit_once_and_add_up_to_the_total(self):
        # catches (#743): a member that never reported, a unit run twice, or a
        # record from another plan. The launch-fleet lane runs the pinned inbox suite.
        unit = 'skill:launch-fleet:skills/launch-fleet/scripts/test-inbox.py'
        def member(k, units):
            return {'lane': 'skill:launch-fleet', 'shard': k, 'shards': 3, 'plan_sha256': self.sha,
                    'units': dict.fromkeys(units, 1.0), 'counts': {}}
        def fleet():
            return [member(1, [unit]), member(2, []), member(3, [])]
        result = self.check_shards('skill:launch-fleet', fleet())
        self.assertEqual(result.returncode, 0, result.stderr)
        def twice(r): r[1]['units'][unit] = 1.0
        def missing(r): del r[2]
        def foreign(r): r[0]['plan_sha256'] = '0' * 64
        def dropped(r): r[0]['units'] = {}
        for name, change, wants in [('twice', twice, ['test-inbox.py: ran 2 times']),
                                    ('missing member', missing, ['shard 3 of 3 reported 0 times']),
                                    ('foreign plan', foreign, ['another lane or plan']),
                                    ('dropped unit', dropped, ['test-inbox.py: never ran'])]:
            with self.subTest(name):
                records = fleet(); change(records)
                result = self.check_shards('skill:launch-fleet', records)
                self.assertEqual(result.returncode, 1, result.stdout)
                for want in wants:
                    self.assertIn(want, result.stderr)


if __name__=='__main__': unittest.main()
