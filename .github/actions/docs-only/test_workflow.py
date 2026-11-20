#!/usr/bin/env python3
"""X5 workflow contracts, plus execution of the final job's actual script."""
import contextlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
sys.dont_write_bytecode = True
import unittest
from unittest import mock

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import test_lanes


def jobs():
    source=(ROOT/'.github/workflows/ci.yml').read_text().split('jobs:\n',1)[1]
    return dict((m[1],m[2]) for m in re.finditer(r'^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)',source,re.M|re.S))


class MainRunAge(unittest.TestCase):
    """#1055, #1486: a main push runs the full plan only when main's last full
    run (a push or nightly whose ci job passed) finished over 120 minutes ago.

    catches: a push running everything after a recent full run, rounding away
    the strict 120-minute boundary, a light push counting as a full run, or an
    unreadable answer deciding instead of failing. Only GitHub's answers and
    the clock are fixture inputs.
    """
    NOW = 1_700_010_000

    def setUp(self):
        blocks = jobs()['changes']
        self.assertIn('      - name: Check the last full main run\n', blocks)
        step = blocks.split('      - name: Check the last full main run\n', 1)[1].split('      - ', 1)[0]
        body = step.split('        run: |\n', 1)[1]
        lines = [line[10:] for line in body.splitlines() if line.startswith('          ')]
        self.script = '\n'.join(lines[1:-1])
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        (self.tmp / 'bin').mkdir()
        gh = self.tmp / 'bin/gh'
        gh.write_text('#!' + sys.executable + ' -I\nimport json, os, sys\n'
                      'if os.environ.get("GH_FAIL"): sys.exit(1)\n'
                      'print(json.load(open(os.environ["GH_ANSWERS"]))[sys.argv[2].split("?")[0]])\n')
        gh.chmod(0o755)

    def at(self, minutes):
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(round(self.NOW - minutes * 60)))

    def gate(self, runs, fail=False):
        """runs: (id, event, updated minutes ago, ci job's completion minutes ago or None)."""
        answers = {'repos/synthetic/repo/actions/workflows/ci.yml/runs': json.dumps({'workflow_runs': [
            {'id': i, 'event': e, 'updated_at': self.at(u)} for i, e, u, _ in runs]})}
        for i, _, _, ci in runs:
            answers[f'repos/synthetic/repo/actions/runs/{i}/jobs'] = json.dumps({'jobs': [
                {'name': 'changes', 'conclusion': 'success', 'completed_at': self.at(1)}]
                + ([{'name': 'ci', 'conclusion': 'success', 'completed_at': self.at(ci)}] if ci is not None else [])})
        (self.tmp / 'answers.json').write_text(json.dumps(answers))
        output = self.tmp / 'output'
        output.unlink(missing_ok=True)
        env = dict(GH_ANSWERS=str(self.tmp / 'answers.json'), GITHUB_OUTPUT=str(output), GITHUB_RUN_ID='77',
                   GITHUB_REPOSITORY='synthetic/repo', RETRY_WAIT='0', GH_FAIL='1' if fail else '',
                   PATH=str(self.tmp / 'bin') + os.pathsep + os.environ['PATH'])
        original = Path.cwd()
        try:
            os.chdir(ROOT)
            with mock.patch.dict(os.environ, env), mock.patch('time.time', return_value=self.NOW), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                exec(compile(self.script, 'ci.yml:main_age', 'exec'), {'__name__': '__main__'})
        finally:
            os.chdir(original)
        return output.read_text()

    def test_a_full_run_119_minutes_ago_keeps_the_push_light_and_121_runs_everything(self):
        for event in ('push', 'schedule'):
            with self.subTest(event=event):
                self.assertEqual(self.gate([(5, event, 100, 119)]), 'trace=false\n')
                self.assertEqual(self.gate([(5, event, 100, 121)]), 'trace=true\n')

    def test_exactly_120_minutes_is_not_older_but_one_second_more_is(self):
        self.assertEqual(self.gate([(5, 'push', 100, 120)]), 'trace=false\n')
        self.assertEqual(self.gate([(5, 'push', 100, 120 + 1 / 60)]), 'trace=true\n')

    def test_a_light_push_a_pull_request_or_this_run_is_not_a_full_run(self):
        runs = [(77, 'push', 1, 1), (6, 'push', 5, None), (7, 'pull_request', 5, 5), (8, 'merge_group', 5, 5)]
        self.assertEqual(self.gate(runs), 'trace=true\n')
        self.assertEqual(self.gate([]), 'trace=true\n')
        self.assertEqual(self.gate(runs + [(9, 'schedule', 30, 30)]), 'trace=false\n')

    def test_an_unreadable_answer_decides_nothing(self):
        with self.assertRaisesRegex(SystemExit, 'Last full main run: unknown'):
            self.gate([(5, 'push', 100, 119)], fail=True)
        self.assertFalse((self.tmp / 'output').exists(), 'an unreadable age must not emit a decision')


class Workflow(unittest.TestCase):
    def assert_trigger_contract(self, source):
        block=re.search(r'^on:\n(.*?)(?=^[^ #\n])',source,re.M|re.S)
        self.assertIsNotNone(block, 'operative on block')
        events=dict((m[1],m[2]) for m in re.finditer(
            r'^  ([a-z_]+):\n(.*?)(?=^  [a-z_]+:\n|\Z)',block[1],re.M|re.S))
        expected={
            'pull_request': ["branches: [main, 'release-*']",
                'types: [opened, synchronize, reopened, ready_for_review, converted_to_draft]'],
            'push': ['branches: [main]'],
            'schedule': ["- cron: '23 9 * * *'"],
            'merge_group': ['types: [checks_requested]', 'branches: [main]'],
        }
        self.assertCountEqual(re.findall(r'^  ([a-z_]+):$',block[1],re.M),expected,
                              'operative trigger event set')
        for event, lines in expected.items():
            actual=[re.sub(r'\s+#.*$','',line).strip() for line in events[event].splitlines()
                    if line.strip() and not line.lstrip().startswith('#')]
            self.assertEqual(actual,lines,event+' trigger contract')

    def test_operative_trigger_contract(self):
        self.assert_trigger_contract((ROOT/'.github/workflows/ci.yml').read_text())

    def test_missing_or_altered_safety_triggers_are_refused(self):
        source=(ROOT/'.github/workflows/ci.yml').read_text()
        self.assert_trigger_contract(source)
        for event in ('pull_request','push','schedule','merge_group'):
            mutant=re.sub(r'^  '+event+r':\n.*?(?=^  [a-z_]+:\n|^permissions:)',
                          '',source,flags=re.M|re.S)
            with self.subTest(removed=event), self.assertRaisesRegex(AssertionError,'trigger event set'):
                self.assert_trigger_contract(mutant)
        for before,after,event in [("'23 9 * * *'","'23 9 * * 1'",'schedule'),
            ('  push:\n    branches: [main]','  push:\n    branches: [other]','push'),
            ('types: [checks_requested]','types: [other]','merge_group'),
            ('  merge_group:\n    types: [checks_requested]\n    branches: [main]',
             '  merge_group:\n    types: [checks_requested]\n    branches: [other]','merge_group'),
            ('ready_for_review, converted_to_draft','converted_to_draft','pull_request')]:
            self.assertEqual(source.count(before),1)
            with self.subTest(altered=event,before=before), self.assertRaisesRegex(AssertionError,event+' trigger contract'):
                self.assert_trigger_contract(source.replace(before,after))

    def test_independent_jobs_need_only_the_plan(self):
        blocks=jobs()
        self.assertEqual(set(blocks),{'changes','always','rust','release','skills','launch-fleet',
                                      'ci','web-test','main-light','owned-paths'})
        for name in ('always','rust','release','skills','launch-fleet'):
            self.assertRegex(blocks[name],r'^    needs: changes\n')
        self.assertIn('fail-fast: false',blocks['skills'])
        self.assertIn('fromJSON(needs.changes.outputs.skill-jobs)',blocks['skills'])
        self.assertIn('fail-fast: false',blocks['launch-fleet'])

    def test_a_selected_release_change_starts_only_its_lanes(self):
        blocks = jobs()
        for _ in (None,):
            with self.subTest():
                active = []
                for name, block in blocks.items():
                    match = re.search(r'^    if: (.*)$', block, re.M)
                    if match is None:
                        active.append(name)
                        continue
                    condition = match[1].removeprefix('${{ ').removesuffix(' }}')
                    outputs = dict.fromkeys(('rust', 'trace', 'planted'), 'false')
                    outputs.update(release='true', skills='[]', **{'skill-jobs': '[]'})
                    values = {'needs.changes.result': 'success',
                              'needs.ci.result': 'success', 'github.event_name': 'pull_request',
                              'github.ref': 'refs/pull/909/merge'}
                    values.update({'needs.changes.outputs.' + key: value for key, value in outputs.items()})
                    for key in sorted(values, key=len, reverse=True):
                        condition = condition.replace(key, repr(values[key]))
                    condition = condition.replace('!cancelled()', 'True').replace('always()', 'True')
                    condition = condition.replace('&&', ' and ').replace('||', ' or ')
                    if eval(condition, {'__builtins__': {}}, {'contains': lambda a, b: b in a}):
                        active.append(name)
                self.assertEqual(active, ['changes', 'always', 'release', 'owned-paths', 'ci', 'web-test'])
                # Such a PR also starts the separate Privacy and Changelog
                # workflows. No matrix is active for this selected fixture.
                self.assertEqual(len(active) + 2, 8)
        # #743: each release member records its share; the ci job stamps the
        # separate receipts only after every unit is checked to have run once.
        self.assertIn('run.py execute "$RUNNER_TEMP/ci-plan" release --shard ', blocks['release'])
        self.assertIn('run.py check-shards "$RUNNER_TEMP/ci-plan" release ', blocks['ci'])
        self.assertIn('run.py stamp "$RUNNER_TEMP/ci-plan" release', blocks['ci'])

    def test_main_push_plan_requires_an_old_full_run_but_other_events_do_not(self):
        # catches: a main push writing a full plan after a recent full run, or a PR/nightly/
        # merge group made dependent on the main-push age read (#1055, #1486).
        block = jobs()['changes']
        self.assertIn('      - name: Check the last full main run\n', block)
        steps = {name: block.split('      - name: ' + name + '\n', 1)[1].split('      - ', 1)[0]
                 for name in ('Check the last full main run', 'Write the CI plan')}
        upload = block.split('      - uses: actions/upload-artifact@', 1)[1]
        # catches (#1612 R2): a main push's rerun skipping the full suite because another
        # full run finished within 120 minutes; every rerun runs everything.
        for event in ('push', 'pull_request', 'schedule', 'merge_group'):
            for old in (False, True):
                for attempt in (1, 2):
                    values = {'github.event_name': repr(event), 'github.run_attempt': repr(str(attempt)),
                              'steps.main_age.outputs.trace': repr(str(old).lower())}
                    for name, step in {**steps, 'selection artifact': upload}.items():
                        expression = re.search(r'^        if: (.+)$', step, re.M)
                        code = expression[1] if expression else 'True'
                        for key, value in values.items():
                            code = code.replace(key, value)
                        code = code.replace('&&', ' and ').replace('||', ' or ')
                        gate = event == 'push' and attempt == 1
                        expected = gate if name == 'Check the last full main run' else not gate or old
                        with self.subTest(event=event, old=old, attempt=attempt, step=name):
                            self.assertEqual(eval(code, {'__builtins__': {}}, {}), expected)

    def test_one_writer_keeps_attempt_specific_plan_and_summary(self):
        workflow=(ROOT/'.github/workflows/ci.yml').read_text()
        blocks=jobs()
        self.assertEqual(workflow.count('python3 -I .github/actions/docs-only/plan.py '),1)
        self.assertIn('python3 -I .github/actions/docs-only/plan.py ',blocks['changes'])
        self.assertIn('name: ci-selection-${{ github.run_attempt }}',blocks['changes'])
        self.assertIn('retention-days: 30',blocks['changes'])
        for name in ('always','rust','release','skills','launch-fleet','ci'):
            self.assertIn('name: ci-selection-${{ github.run_attempt }}',blocks[name])
        self.assertNotIn('uses: ./.github/actions/docs-only\n',workflow)

    # Which events run ci (always on pull requests, merge groups and nightly,
    # on a main push after an old full run) is ci.test.mjs's job-graph simulation (#1055, #1486).
    def test_final_ci_waits_for_all_jobs_and_always_runs(self):
        block=jobs()['ci']
        deps=re.search(r'^    needs: \[(.*)\]$',block,re.M)[1].split(', ')
        self.assertEqual(set(deps),set(jobs())-{'ci','web-test','main-light','owned-paths'})
        self.assertIn('NEEDS: ${{ toJSON(needs) }}',block)

    def test_actual_ci_script_refuses_failure_cancellation_and_missing_lane(self):
        fixture=test_lanes.Lanes('test_every_planned_job_and_skill_member_passed')
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        block=jobs()['ci']
        step=block.split('      - name: Every planned lane passed\n',1)[1]
        body=step.split('        run: |\n',1)[1]
        lines=[]
        for line in body.splitlines():
            if line and not line.startswith('          '): break
            lines.append(line[10:])
        script='\n'.join(lines)
        (fixture.path/'ci-plan').mkdir()
        for name in ('ci-selection.json','ci-dispatch.json'):
            (fixture.path/'ci-plan'/name).write_bytes((fixture.path/name).read_bytes())
        for state in ('success','failure','cancelled',None):
            needs=json.loads(json.dumps(fixture.needs))
            if state is None: del needs['rust']
            else: needs['rust']['result']=state
            env=dict(os.environ,RUNNER_TEMP=str(fixture.path),NEEDS=json.dumps(needs),
                     GITHUB_RUN_ID=str(fixture.plan['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='schedule')
            result=subprocess.run(['bash','-euo','pipefail','-c',script],cwd=ROOT,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0 if state=='success' else 1,result.stderr)


class Security(unittest.TestCase):
    def test_privacy_and_ci_small_jobs_share_fallback_order_and_hosted_forks(self):
        privacy=(ROOT/'.github/workflows/privacy.yml').read_text()
        runners={'privacy':re.search(r'^    runs-on: (.*)$',privacy,re.M)[1]}
        for name in ('changes','ci','web-test'):
            runners[name]=re.search(r'^    runs-on: (.*)$',jobs()[name],re.M)[1]
        for event,head in [('push',''),('pull_request','jparker2006/ClosedWiz'),
                           ('merge_group',''),('pull_request','fork/repo')]:
            for small,web,expected in [
                ('small-pool','web-pool','small-pool'),
                ('','web-pool','web-pool'),
                ('small-pool','','small-pool'),
                ('','','namespace-profile-closedwiz-rust'),
            ]:
                for name,runner in runners.items():
                    with self.subTest(event=event,head=head,small=small,web=web,job=name):
                        expression=runner[3:-2].strip()
                        for key,value in {
                            'github.event_name':event,
                            'github.event.pull_request.head.repo.full_name':head,
                            'github.repository':'jparker2006/ClosedWiz',
                            'vars.CI_SMALL_RUNS_ON':small,
                            'vars.CI_WEB_RUNS_ON':web,
                        }.items(): expression=expression.replace(key,repr(value))
                        actual=eval(expression.replace('&&',' and ').replace('||',' or '),
                                    {'__builtins__':{}},{})
                        self.assertEqual(actual,'ubuntu-24.04' if head=='fork/repo' else expected)

    def test_runner_choices_keep_small_jobs_independent_and_forks_hosted(self):
        small={'changes','ci','web-test','main-light','owned-paths'}
        rust={'always','rust'}
        web={'release','skills','launch-fleet'}
        blocks=jobs()
        self.assertEqual(set(blocks),small|rust|web)
        # Literal expectations describe the runner pool, independently of the
        # expression being evaluated. Distinct labels expose accidental sharing.
        for event,head,small_runner,web_runner,rust_runner,expected in [
            ('pull_request','jparker2006/ClosedWiz','small-pool','web-pool','rust-pool',
             ('small-pool','web-pool','rust-pool')),
            ('push','', 'small-pool','web-pool','rust-pool',
             ('small-pool','web-pool','rust-pool')),
            ('schedule','', 'small-pool','web-pool','rust-pool',
             ('small-pool','web-pool','rust-pool')),
            ('merge_group','', 'small-pool','web-pool','rust-pool',
             ('small-pool','web-pool','rust-pool')),
            ('pull_request','jparker2006/ClosedWiz','','web-pool','rust-pool',
             ('web-pool','web-pool','rust-pool')),
            ('pull_request','jparker2006/ClosedWiz','small-pool','','rust-pool',
             ('small-pool','namespace-profile-closedwiz-rust','rust-pool')),
            ('pull_request','jparker2006/ClosedWiz','','','rust-pool',
             ('namespace-profile-closedwiz-rust','namespace-profile-closedwiz-rust','rust-pool')),
            ('pull_request','jparker2006/ClosedWiz','small-pool','web-pool','',
             ('small-pool','web-pool','namespace-profile-closedwiz-rust')),
            ('pull_request','jparker2006/ClosedWiz','','','',
             ('namespace-profile-closedwiz-rust',)*3),
            ('pull_request','fork/repo','small-pool','web-pool','rust-pool',
             ('ubuntu-24.04',)*3),
            ('pull_request','fork/repo','','','',('ubuntu-24.04',)*3),
            ('pull_request','fork/repo','self-hosted','unknown','namespace-profile-planted',
             ('ubuntu-24.04',)*3),
            ('pull_request','jparker2006/ClosedWiz','self-hosted','unknown','namespace-profile-planted',
             ('self-hosted','unknown','namespace-profile-planted')),
        ]:
            for repository in ('jparker2006/ClosedWiz','openwizdev/OpenWiz','owner/repo'):
                event_head=repository if head=='jparker2006/ClosedWiz' else head
                for name,block in blocks.items():
                    with self.subTest(repository=repository,event=event,head=head,small=small_runner,
                                      web=web_runner,rust=rust_runner,job=name):
                        runner=re.search(r'^    runs-on: (.*)$',block,re.M)[1]
                        expression=runner[3:-2].strip()
                        for key,value in {
                            'github.event_name':event,
                            'github.event.pull_request.head.repo.full_name':event_head,
                            'github.repository':repository,
                            'vars.CI_SMALL_RUNS_ON':small_runner,
                            'vars.CI_WEB_RUNS_ON':web_runner,
                            'vars.CI_RUST_RUNS_ON':rust_runner,
                        }.items(): expression=expression.replace(key,repr(value))
                        actual=eval(expression.replace('&&',' and ').replace('||',' or '),
                                    {'__builtins__':{}},{})
                        self.assertEqual(actual,expected[0 if name in small else 2 if name in rust else 1]
                                         if repository=='jparker2006/ClosedWiz' else 'ubuntu-24.04')

    def test_every_job_routes_forks_and_runs_guard_immediately(self):
        for name,block in jobs().items():
            with self.subTest(job=name):
                steps=block.split('    steps:\n',1)[1].split('      - ')[1:]
                self.assertTrue(steps[0].startswith('uses: actions/checkout@'))
                self.assertTrue(steps[1].startswith('name: The runner guard\n'))
                self.assertIn('run: sh ci/hosted/guard.sh',steps[1])
                self.assertIn('HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}',steps[1])
                self.assertNotIn('        if:',steps[1])
                if name not in ('changes','ci','web-test','main-light','owned-paths'):
                    prepare=[s for s in steps if 'uses: ./.github/actions/docs-only/setup\n' in s]
                    self.assertEqual(len(prepare),1,name)
                    self.assertIn('hosted: ${{ steps.guard.outputs.hosted }}',prepare[0])
                    self.assertIn('save: ${{ steps.guard.outputs.save }}',prepare[0])
                    if name in ('always','rust','release'):
                        self.assertIn("cargo: 'true'",prepare[0])
                    # #1264: no lane installs the web view's packages any more.
                    self.assertNotIn('npm:',prepare[0])
                    if name=='skills':
                        self.assertIn("browser: ${{ matrix.skill == 'image' }}",prepare[0])
                for step in steps:
                    if 'uses: actions/cache/restore@' in step:
                        self.assertIn("if: steps.guard.outputs.hosted == 'true'",step)
                    if 'uses: actions/cache/save@' in step:
                        self.assertIn("if: steps.guard.outputs.save == 'true'",step)
                    if re.search(r'^        run: sh ci/runner/cache.sh save ',step,re.M):
                        self.assertIn("if: github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'schedule')",step)

    def test_shared_setup_preserves_hosted_cache_and_setup_guards(self):
        source=(HERE/'setup/action.yml').read_text()
        for block in source.split('    - ')[1:]:
            if 'uses: actions/cache/' in block:
                self.assertIn("inputs.hosted == 'true'",block)
                self.assertIn('uses: actions/cache/restore@',block)
            if 'run: sh ci/runner/cache.sh restore ' in block:
                self.assertIn("inputs.hosted != 'true'",block)
                self.assertIn("steps.volume.outputs.namespace != 'true'",block)
        hosted=source.split('    - name: The hosted setup\n',1)[1].split('    - ',1)[0]
        self.assertIn("if: inputs.hosted == 'true'",hosted)
        self.assertIn('sh ci/hosted/setup.sh python chromium zsh',hosted)
        self.assertIn('sh ci/hosted/setup.sh python zsh',hosted)
        for path in (ROOT/'.github/workflows/ci.yml',HERE/'setup/action.yml'):
            for action in re.findall(r'^\s+(?:- )?uses: (.+)$',path.read_text(),re.M):
                self.assertTrue(action.startswith('./') or re.fullmatch(r'[^ @]+@[0-9a-f]{40} # v[0-9.]+',action),action)
        self.assertNotIn('uses: actions/cache@',source)

if __name__=='__main__': unittest.main()
