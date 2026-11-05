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
        raw = json.dumps(self.plan)
        self.sha = hashlib.sha256(raw.encode()).hexdigest()
        (self.path / 'ci-selection.json').write_text(raw)
        self.dispatch = {**dict.fromkeys(('build-web','lint-rust','export-rust','export-web','build-site','image-skills'), True),
                         'rust': True, 'web': True, 'site': True, 'release': True, 'toolkit': True,
                         'skills': ['launch-fleet','plan-graph','triage'], 'trace': False, 'planted': False,
                         'plan_sha256': self.sha}
        (self.path / 'ci-dispatch.json').write_text(json.dumps(self.dispatch))
        self.needs = {k: {'result': 'success'} for k in
                      ('changes','always','web-build','rust-export','web-export','site','release','skills')}
        self.needs.update({k: {'result': 'skipped'} for k in ('rust','web')})
        self.expected = {k: self.plan['lanes'][k]['tests'] for k in ('always','rust','web')}
        self.expected.update(site=['site:build','site:test'], release=['release:package'])
        self.expected.update({'skill:'+s['skill']: s['tests'] for s in self.plan['lanes']['skills']})
        self.expected['prerequisite:toolkit'] = []
        self.expected['build:web_export'] = []
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

    def selected_site_release(self):
        self.plan['selection'] = {'mode': 'selected'}
        self.plan['run'].update(event='pull_request', action='synchronize',
                                base='1' * 40, pull_request=909)
        self.plan['diff'] = {'state': 'read', 'paths': ['apps/site/index.html']}
        raw = json.dumps(self.plan)
        self.sha = hashlib.sha256(raw.encode()).hexdigest()
        (self.path / 'ci-selection.json').write_text(raw)
        self.dispatch['plan_sha256'] = self.sha
        (self.path / 'ci-dispatch.json').write_text(json.dumps(self.dispatch))
        self.needs['site']['result'] = 'skipped'
        for name, tests in self.expected.items():
            self.receipt(name, tests)

    def test_selected_site_and_release_need_both_receipts_in_one_job(self):
        self.selected_site_release()
        result = self.run_finish()
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('site', 'release'):
            with self.subTest(missing=name):
                path = self.receipts / (name + '.json')
                path.unlink()
                result = self.run_finish()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(name, result.stderr)
                self.receipt(name, self.expected[name])
        for state in ('failure', 'cancelled', 'skipped', None):
            with self.subTest(release=state):
                if state is None:
                    del self.needs['release']
                else:
                    self.needs['release']['result'] = state
                result = self.run_finish()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('release', result.stderr)
        self.needs['release'] = {'result': 'success'}
        self.needs['site']['result'] = 'success'
        result = self.run_finish()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('site', result.stderr)

    def test_combined_receipts_reject_omitted_work_stale_plan_and_foreign_head_attempt(self):
        self.selected_site_release()
        for field, value in [('tests', []), ('plan_sha256', '0' * 64),
                             ('head', 'f' * 40), ('attempt', 2)]:
            with self.subTest(field=field):
                path = self.receipt('site', self.expected['site'])
                entry = json.loads(path.read_text())
                if field in ('head', 'attempt'):
                    entry['run'][field] = value
                else:
                    entry[field] = value
                path.write_text(json.dumps(entry))
                result = self.run_finish()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('site', result.stderr)
        self.receipt('site', self.expected['site'])
        self.receipts.joinpath('duplicate.json').write_bytes(self.receipts.joinpath('site.json').read_bytes())
        result = self.run_finish()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('duplicate', result.stderr)

    def test_selected_release_stamp_keeps_separate_site_and_release_receipts(self):
        self.selected_site_release()
        for path in self.receipts.glob('*.json'):
            path.unlink()
        env = dict(os.environ, GITHUB_RUN_ID=str(self.plan['run']['id']),
                   GITHUB_RUN_ATTEMPT='1', GITHUB_EVENT_NAME='pull_request')
        result = subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), 'stamp',
            str(self.path), 'release', str(self.receipts)], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in self.receipts.glob('*.json')), ['release.json', 'site.json'])
        for name in ('site', 'release'):
            self.assertEqual(json.loads(self.receipts.joinpath(name + '.json').read_text()),
                {'lane': name, 'tests': self.expected[name], 'plan_sha256': self.sha, 'run': self.plan['run']})

    def test_every_planned_job_and_skill_member_passed(self):
        result = self.run_finish()
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('every planned lane passed',result.stdout)

    def test_actual_job_failure_cancellation_and_absence_fail(self):
        original = json.loads(json.dumps(self.needs))
        for job in ('changes','always','web-build','rust-export','web-export','site','release','skills'):
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


if __name__=='__main__': unittest.main()
