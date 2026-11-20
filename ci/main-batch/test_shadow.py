#!/usr/bin/env python3
"""C7's workflow boundary: the non-authoritative shadow steps can never
change or bypass CI's required result. Synthetic contexts only.
"""
import json
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Shadow(unittest.TestCase):
    def test_workflow_only_appends_capture_after_finish_for_main(self):
        self.assert_current_shadow_workflow((ROOT/'.github/workflows/ci.yml').read_text())

    def assert_current_shadow_workflow(self, workflow):
        import re
        start = workflow.index('      # C7 shadow evidence:')
        end = workflow.index('\n  # Transition bridge:', start)
        block = workflow[start:end]
        ci = workflow[workflow.index('\n  ci:\n'):start]
        # #1055: an admitted old-map main push runs ci; every other event always.
        self.assertIn("    if: ${{ always() && (github.event_name != 'push' || needs.changes.result != 'success' || needs.changes.outputs.trace == 'true') }}\n", ci, 'required result always runs')
        self.assertIn('    needs: [changes, always, rust, release, skills, launch-fleet]\n',
                      ci, 'required result dependencies')
        finish = '          python3 -I .github/actions/docs-only/run.py finish "$RUNNER_TEMP/ci-plan" "$RUNNER_TEMP/needs.json" "$RUNNER_TEMP/receipts"'
        self.assertEqual(workflow.count('run.py finish'), 1, 'required result finish count')
        self.assertIn(finish+'\n', ci, 'required result before capture; no bypass')
        last = ci.rsplit('      - name:', 1)[1]
        approved_finish = ''' Every planned lane passed
        env:
          NEEDS: ${{ toJSON(needs) }}
        run: |
          printf '%s' "$NEEDS" > "$RUNNER_TEMP/needs.json"
          python3 -I .github/actions/docs-only/run.py finish "$RUNNER_TEMP/ci-plan" "$RUNNER_TEMP/needs.json" "$RUNNER_TEMP/receipts"
'''
        # This complete required-result step is the protected boundary. Extra
        # commands or properties can swallow failure or change its inputs.
        self.assertEqual(last, approved_finish, 'required result complete approved step')
        self.assertEqual(block.count('      - name:'), 2, 'required result isolated shadow steps')
        self.assertEqual(block.count('continue-on-error: true'), 2, 'required result unaffected by shadow failures')
        self.assertIn('        id: main_shadow\n', block)
        self.assertIn('shadow.py capture', block)
        self.assertNotIn('reconcile', block)
        expressions = re.findall(r'^        if: (.+)$', block, re.M)
        self.assertEqual(len(expressions), 2, 'eligibility conditions')
        cases = []
        for event, ref, base in [
            ('push', 'refs/heads/main', None),
            ('push', 'refs/heads/main-other', None),
            ('push', 'refs/heads/release-synthetic', None),
            ('schedule', 'refs/heads/main', None),
            ('pull_request', 'refs/pull/9001/merge', None),
            ('workflow_dispatch', 'refs/heads/main', None),
            ('merge_group', 'refs/heads/gh-readonly-queue/main/pr-9001', 'refs/heads/main'),
            ('merge_group', 'refs/heads/gh-readonly-queue/other/pr-9001', 'refs/heads/other'),
            ('merge_group', 'refs/heads/gh-readonly-queue/main/pr-9001', None),
        ]:
            for finish_ok in (False, True):
                for capture in ('success', 'failure', 'cancelled', 'skipped'):
                    cases.append(dict(github=dict(event_name=event, ref=ref,
                        event=dict(merge_group=dict(base_ref=base),pull_request=dict(number=9001))),
                        finish=finish_ok, capture=capture))
        code = '''import {runInNewContext} from 'node:vm';
const expressions=JSON.parse(process.argv[1]), cases=JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(c=>expressions.map(e=>Boolean(runInNewContext(e,{
 github:c.github,steps:{main_shadow:{outcome:c.capture}},success:()=>c.finish
},{timeout:100}))))));'''
        result = subprocess.run(['node','--input-type=module','-e',code,json.dumps(expressions),json.dumps(cases)],
                                capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = []
        for case in cases:
            g = case['github']
            eligible = case['finish'] and (g['event_name']=='push' and g['ref']=='refs/heads/main' or
                g['event_name']=='merge_group' and g['event']['merge_group']['base_ref']=='refs/heads/main')
            expected.append([eligible, eligible and case['capture']=='success'])
        self.assertEqual(json.loads(result.stdout), expected, 'eligibility and capture-success dependency')
        # Independently specified admission contracts, not a hash of unrelated
        # workflow bytes. Later runner/setup edits are outside C7's boundary.
        for pattern in (
            r"(?m)^  push:\n    branches: \[main\]$",
            r"(?m)^  pull_request:\n    branches: \[main, 'release-\*'\]\n    types: \[opened, synchronize, reopened, ready_for_review, converted_to_draft\]$",
            r"(?m)^  schedule:\n    - cron: '23 9 \* \* \*'(?: #.*)?$",
            r"(?m)^  merge_group:\n    types: \[checks_requested\]\n    branches: \[main\]$",
        ):
            self.assertRegex(workflow, pattern, 'admission preserved')
        self.assertIn('  group: ci-${{ github.event_name }}-${{ github.event.pull_request.number || github.ref }}\n',
                      workflow, 'admission slots preserved')
        self.assertIn("  cancel-in-progress: ${{ github.event_name == 'pull_request' || (github.event_name == 'push' && github.ref == 'refs/heads/main') }}\n",
                      workflow, 'admission obsolete pushes cancelled; nightly isolated')

    def test_shadow_step_failures_do_not_replace_the_existing_required_result(self):
        workflow = (ROOT/'.github/workflows/ci.yml').read_text()
        block = workflow.split('      # C7 shadow evidence:',1)[1].split('\n  # Transition bridge:',1)[0]
        self.assertEqual(block.count('continue-on-error: true'),2)
        self.assertIn("steps.main_shadow.outcome == 'success'",block)
        expressions = [line.split('if: ',1)[1] for line in block.splitlines() if 'if: ' in line]
        code = '''import {runInNewContext} from 'node:vm';
const expressions=JSON.parse(process.argv[1]);
const cases=JSON.parse(process.argv[2]);
console.log(JSON.stringify(cases.map(c=>expressions.map(e=>Boolean(runInNewContext(e,{
 github:c.github,steps:{'main_shadow':{outcome:c.capture}},success:()=>c.finish
},{timeout:100}))))));'''
        cases=[]
        for event,ref,base in [('push','refs/heads/main',None),('schedule','refs/heads/main',None),
            ('pull_request','refs/pull/9001/merge',None),('push','refs/heads/release-synthetic',None),
            ('merge_group','refs/heads/gh-readonly-queue/main/pr-9001','refs/heads/main')]:
            for finish in (False,True):
                for capture in ('failure','success'):
                    cases.append(dict(github=dict(event_name=event,ref=ref,event=dict(merge_group=dict(base_ref=base))),
                                      finish=finish,capture=capture))
        result=subprocess.run(['node','--input-type=module','-e',code,json.dumps(expressions),json.dumps(cases)],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        expected=[]
        for case in cases:
            event=case['github']['event_name']
            eligible=case['finish'] and (event=='merge_group' or event=='push' and case['github']['ref']=='refs/heads/main')
            expected.append([eligible,eligible and case['capture']=='success'])
        self.assertEqual(json.loads(result.stdout),expected)


if __name__ == '__main__':
    unittest.main()
