#!/usr/bin/env python3
"""X5's required-check boundary, on synthetic plans and lane conclusions only.

The workflow must call gate.py with the persisted plan and normalized job
conclusions (including each skill suite). These fixtures prove refusal at
that boundary; they do not prove GitHub scheduling or a live required check.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
GATE = Path(__file__).with_name('gate.py')
FIXTURES = ROOT / 'ci/selection/valid'


class RequiredCheck(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((FIXTURES / 'full-nightly.json').read_text())
        self.results = {
            'changes': 'success', 'always': 'success', 'rust': 'success',
            'web': 'success', 'site': 'success', 'build:web_export': 'success',
            'skill:launch-fleet': 'success', 'skill:plan-graph': 'success',
            'skill:triage': 'success',
        }

    def run_gate(self, results=None, plan=None, raw=None, **context):
        plan = self.plan if plan is None else plan
        results = self.results if results is None else results
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            record, outcomes = folder / 'ci-selection.json', folder / 'outcomes.json'
            record.write_text(json.dumps(plan) if raw is None else raw)
            outcomes.write_text(json.dumps(results))
            env = dict(os.environ, GITHUB_RUN_ID=str(plan['run']['id']),
                       GITHUB_RUN_ATTEMPT=str(plan['run']['attempt']),
                       GITHUB_EVENT_NAME=plan['run']['event'])
            env.update(context)
            return subprocess.run([sys.executable, '-I', str(GATE), str(record), str(outcomes)],
                                  env=env, capture_output=True, text=True, timeout=10)

    def test_every_named_lane_passed(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('every planned lane passed', result.stdout)

    def test_failed_cancelled_missing_or_nonpassing_lane_never_passes(self):
        for lane in self.results:
            for state in ('failure', 'cancelled', 'skipped', 'neutral', None):
                with self.subTest(lane=lane, state=state):
                    outcomes = dict(self.results)
                    if state is None:
                        del outcomes[lane]
                    else:
                        outcomes[lane] = state
                    result = self.run_gate(outcomes)
                    self.assertEqual(result.returncode, 1, result.stderr)
                    self.assertIn(lane, result.stderr)

    def test_only_planned_lanes_may_skip(self):
        plan = json.loads((FIXTURES / 'selected-skill-only.json').read_text())
        outcomes = {'changes': 'success', 'always': 'success', 'skill:launch-fleet': 'success'}
        result = self.run_gate(outcomes, plan)
        self.assertEqual(result.returncode, 0, result.stderr)
        for lane in ('rust', 'web', 'site', 'build:web_export', 'skill:plan-graph', 'skill:triage'):
            outcomes[lane] = 'skipped'
        result = self.run_gate(outcomes, plan)
        self.assertEqual(result.returncode, 0, result.stderr)
        outcomes['rust'] = 'success'
        result = self.run_gate(outcomes, plan)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('rust', result.stderr)

    def test_a_missing_skill_matrix_member_fails(self):
        del self.results['skill:plan-graph']
        result = self.run_gate()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('skill:plan-graph', result.stderr)

    def test_invalid_or_stale_plan_cannot_certify_a_run(self):
        raw = json.dumps(self.plan)
        for bad in ('{}', raw.replace('"schema":', '"schema": "openwiz.ci-selection.v1", "schema":', 1),
                    raw.replace('ci-selection-1', 'ci-selection-2')):
            with self.subTest(raw=bad):
                result = self.run_gate(raw=bad)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn('plan', result.stderr)
        for variable, value in (('GITHUB_RUN_ID', '9000099'), ('GITHUB_RUN_ATTEMPT', '2'),
                                ('GITHUB_EVENT_NAME', 'push')):
            with self.subTest(variable=variable):
                result = self.run_gate(**{variable: value})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(variable, result.stderr)



if __name__ == '__main__':
    unittest.main()
