#!/usr/bin/env python3
"""X5 workflow contracts, plus execution of the final job's actual script."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import test_lanes


def jobs():
    source=(ROOT/'.github/workflows/ci.yml').read_text().split('jobs:\n',1)[1]
    return dict((m[1],m[2]) for m in re.finditer(r'^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)',source,re.M|re.S))


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
            'workflow_dispatch': [],
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
        for event in ('pull_request','push','schedule','merge_group','workflow_dispatch'):
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

    def test_independent_jobs_wait_for_export_only_when_needed(self):
        blocks=jobs()
        self.assertEqual(set(blocks),{'changes','always','web-build','rust','rust-export','web','web-export',
                                      'site','release','skills','launch-fleet','select-map','ci','web-test','toolkit-nightly',
                                      'main-light'})
        for name in ('always','web-build','rust','web','site','release','skills','launch-fleet'):
            self.assertRegex(blocks[name],r'^    needs: changes\n')
        for name in ('rust-export','web-export'):
            self.assertRegex(blocks[name],r'^    needs: \[changes, web-build\]\n')
            self.assertIn("needs.web-build.result == 'success'",blocks[name])
        self.assertIn('fail-fast: false',blocks['skills'])
        self.assertIn('fromJSON(needs.changes.outputs.skill-jobs)',blocks['skills'])
        self.assertIn('fail-fast: false',blocks['launch-fleet'])

    def test_selected_site_cut_uses_one_job_but_full_runs_keep_both(self):
        blocks = jobs()
        for combined in (True, False):
            with self.subTest(combined=combined):
                active = []
                for name, block in blocks.items():
                    match = re.search(r'^    if: (.*)$', block, re.M)
                    if match is None:
                        active.append(name)
                        continue
                    condition = match[1].removeprefix('${{ ').removesuffix(' }}')
                    outputs = dict.fromkeys(('rust', 'toolkit', 'web', 'build-web',
                        'export-rust', 'export-web', 'trace', 'planted'), 'false')
                    outputs.update(site='true', release='true', skills='[]', **{'skill-jobs': '[]'},
                                   **{'site-in-release': str(combined).lower()})
                    values = {'needs.changes.result': 'success', 'needs.web-build.result': 'skipped',
                              'needs.ci.result': 'success', 'github.event_name': 'pull_request',
                              'github.ref': 'refs/pull/909/merge'}
                    values.update({'needs.changes.outputs.' + key: value for key, value in outputs.items()})
                    for key in sorted(values, key=len, reverse=True):
                        condition = condition.replace(key, repr(values[key]))
                    condition = condition.replace('!cancelled()', 'True').replace('always()', 'True')
                    condition = condition.replace('&&', ' and ').replace('||', ' or ')
                    if eval(condition, {'__builtins__': {}}, {'contains': lambda a, b: b in a}):
                        active.append(name)
                self.assertEqual(active, ['changes', 'always', *([] if combined else ['site']),
                                           'release', 'ci', 'web-test'])
                # A site-only PR also starts the separate Privacy and Changelog
                # workflows. No matrix is active for this selected fixture.
                self.assertEqual(len(active) + 2, 7 if combined else 8)
        self.assertIn('site-in-release: ${{ steps.plan.outputs.site-in-release }}', blocks['changes'])
        # #743: each release member records its share; the ci job stamps the
        # separate receipts only after every unit is checked to have run once.
        self.assertIn('run.py execute "$RUNNER_TEMP/ci-plan" release --shard ', blocks['release'])
        self.assertIn('run.py check-shards "$RUNNER_TEMP/ci-plan" release ', blocks['ci'])
        self.assertIn('run.py stamp "$RUNNER_TEMP/ci-plan" release', blocks['ci'])

    def test_one_writer_keeps_attempt_specific_plan_and_summary(self):
        workflow=(ROOT/'.github/workflows/ci.yml').read_text()
        blocks=jobs()
        self.assertEqual(workflow.count('python3 -I .github/actions/docs-only/plan.py '),1)
        self.assertIn('python3 -I .github/actions/docs-only/plan.py ',blocks['changes'])
        self.assertIn('name: ci-selection-${{ github.run_attempt }}',blocks['changes'])
        self.assertIn('retention-days: 30',blocks['changes'])
        for name in ('always','web-build','rust','rust-export','web','web-export','site','release','skills','launch-fleet','ci'):
            self.assertIn('name: ci-selection-${{ github.run_attempt }}',blocks[name])
        self.assertNotIn('uses: ./.github/actions/docs-only\n',workflow)

    # Which events run ci (always on pull requests, merge groups and nightly,
    # never on a main push) is ci.test.mjs's job-graph simulation (#744).
    def test_final_ci_waits_for_all_jobs_and_always_runs(self):
        block=jobs()['ci']
        deps=re.search(r'^    needs: \[(.*)\]$',block,re.M)[1].split(', ')
        self.assertEqual(set(deps),set(jobs())-{'ci','select-map','web-test','toolkit-nightly','main-light'})
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
            if state is None: del needs['rust-export']
            else: needs['rust-export']['result']=state
            env=dict(os.environ,RUNNER_TEMP=str(fixture.path),NEEDS=json.dumps(needs),
                     GITHUB_RUN_ID=str(fixture.plan['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='schedule')
            result=subprocess.run(['bash','-euo','pipefail','-c',script],cwd=ROOT,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0 if state=='success' else 1,result.stderr)


class Security(unittest.TestCase):
    def test_privacy_and_ci_small_jobs_share_fallback_order_and_hosted_forks(self):
        privacy=(ROOT/'.github/workflows/privacy.yml').read_text()
        runners={'privacy':re.search(r'^    runs-on: (.*)$',privacy,re.M)[1]}
        for name in ('changes','select-map','ci','web-test'):
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
        small={'changes','select-map','ci','web-test','main-light'}
        rust={'always','rust','rust-export','toolkit-nightly'}
        web={'web-build','web','web-export','site','release','skills','launch-fleet'}
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
                if name not in ('changes','ci','select-map','web-test','toolkit-nightly','main-light'):
                    prepare=[s for s in steps if 'uses: ./.github/actions/docs-only/setup\n' in s]
                    self.assertEqual(len(prepare),1,name)
                    self.assertIn('hosted: ${{ steps.guard.outputs.hosted }}',prepare[0])
                    self.assertIn('save: ${{ steps.guard.outputs.save }}',prepare[0])
                    if name in ('always','rust','rust-export','web','web-export','release'):
                        self.assertIn("cargo: 'true'",prepare[0])
                    if name in ('web-build','web','web-export','site','release'):
                        self.assertIn("npm: 'true'",prepare[0])
                    if name in ('rust','rust-export'):
                        npm=re.findall(r'^          npm: (.+)$',prepare[0],re.M)
                        self.assertEqual(len(npm),1,name+' npm prerequisite')
                        for planted,want in [('true','true'),('false','false')]:
                            with self.subTest(planted=planted):
                                value=npm[0]
                                if value.startswith('${{'):
                                    expression=value[3:-2].strip().replace(
                                        'needs.changes.outputs.planted',repr(planted))
                                    value=eval(expression.replace('&&',' and ').replace('||',' or '),
                                               {'__builtins__':{}},{})
                                else: value=value.strip("'\"")
                                self.assertEqual(str(value).lower(),want,name+' npm prerequisite')
                    if name in ('web','web-export','site','release'):
                        self.assertIn("browser: 'true'",prepare[0])
                    if name=='skills':
                        self.assertIn("npm: ${{ matrix.skill == 'image' }}",prepare[0])
                        self.assertIn("browser: ${{ matrix.skill == 'image' }}",prepare[0])
                for step in steps:
                    if 'uses: actions/cache/restore@' in step:
                        if name=='changes':
                            self.assertIn('path: ~/.cache/closedwiz-ci-select',step)
                            self.assertIn('key: ci-select-map-none',step)
                            self.assertIn('restore-keys: ci-select-map-',step)
                        else:self.assertIn("if: steps.guard.outputs.hosted == 'true'",step)
                    if 'uses: actions/cache/save@' in step:
                        if name=='select-map':
                            self.assertIn("if: steps.map.outputs.save == 'true'",step)
                            self.assertIn('path: ~/.cache/closedwiz-ci-select',step)
                        else:self.assertIn("if: steps.guard.outputs.save == 'true'",step)
                    if re.search(r'^        run: sh ci/runner/cache.sh save ',step,re.M):
                        self.assertIn("if: github.ref == 'refs/heads/main' && (github.event_name == 'push' || github.event_name == 'schedule')",step)

    def test_rust_export_saves_and_restores_a_cargo_cache_no_other_job_saves(self):
        # #742: always saved cargo-rust first, so rust-export's save of the same
        # key failed ("Unable to reserve cache") and its release build stayed cold.
        savers={}
        for name,block in jobs().items():
            for partition in (re.findall(r'^          key: (cargo-[a-z-]+)-\$\{\{ runner\.os \}\}',block,re.M)
                              +re.findall(r'^        run: sh ci/runner/cache\.sh save (cargo-[a-z-]+) ',block,re.M)):
                savers.setdefault(partition,set()).add(name)
        own={p for p,names in savers.items() if 'rust-export' in names}
        self.assertEqual(len(own),1,own)
        partition=own.pop()
        self.assertEqual(savers[partition],{'rust-export'})
        prepare=jobs()['rust-export'].split('uses: ./.github/actions/docs-only/setup\n',1)[1].split('      - ',1)[0]
        self.assertEqual(re.findall(r'^          cache: (\S+)$',prepare,re.M),[partition])

    def test_release_pass_does_not_depend_on_absent_cargo_cache_inputs(self):
        block=jobs()['release']
        commands=re.findall(r'^        run: (sh ci/runner/cache.sh save cargo-[^\n]+)$',block,re.M)
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder);(home/'out').mkdir();(home/'bin').mkdir()
            curl=home/'bin/curl';curl.write_text('#!/bin/sh\necho blocked-network >&2\nexit 99\n');curl.chmod(0o755)
            env=dict(os.environ,HOME=str(home),GITHUB_WORKSPACE=str(home/'workspace'),
                CLOSEDWIZ_CACHE_OUT=str(home/'out'),CLOSEDWIZ_CACHE_AUDIENCE='synthetic',
                ACTIONS_ID_TOKEN_REQUEST_URL='https://example.invalid/oidc',ACTIONS_ID_TOKEN_REQUEST_TOKEN='synthetic',
                RUNNER_ENVIRONMENT='self-hosted',PATH=str(home/'bin')+os.pathsep+os.environ['PATH'])
            for command in commands:
                result=subprocess.run(['bash','-euc',command],cwd=ROOT,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)

    def test_checks_only_has_an_unguarded_plan_bound_lint_fallback(self):
        step=jobs()['always'].split('      - name: Build and lint Rust\n',1)[1].split('      - ',1)[0]
        self.assertNotIn('        if:',step)
        self.assertIn('run.py lint-always "$RUNNER_TEMP/ci-plan"',step)

    def test_retry_contracts_follow_the_shared_bootstrap_and_npm_setup(self):
        setup=(HERE/'setup/action.yml').read_text()
        npm=[line.strip() for line in setup.splitlines() if 'run:' in line and 'npm ci' in line]
        self.assertEqual(npm,['run: sh ci/retry.sh 3 -- npm ci --ignore-scripts --prefix apps/web'])
        bootstrap=(HERE/'python.sh').read_text()
        downloads=[line.strip() for line in bootstrap.splitlines() if line.strip().startswith('curl ')]
        self.assertEqual(len(downloads),1)
        self.assertTrue(downloads[0].startswith('curl -fsSL --retry 5 --retry-delay 10 '))

    # #783: a manual dispatch from main signs like the nightly run; from any
    # other ref (a branch, a release branch, a tag) it signs nothing.
    def test_actual_map_step_signs_and_enables_save_only_for_main_push_nightly_or_dispatch(self):
        step=jobs()['select-map'].split('      - name: Save the select-map cache\n',1)[1].split('      - ',1)[0]
        expression=re.search(r'^          MAIN: \$\{\{ (.*) \}\}$',step,re.M)[1]
        body=step.split('        run: |\n',1)[1]
        script='\n'.join(line[10:] for line in body.splitlines() if not line or line.startswith('          '))
        for event,ref,wants in [('push','refs/heads/main',True),('schedule','refs/heads/main',True),
            ('pull_request','refs/pull/7/merge',False),('pull_request','refs/heads/main',False),
            ('workflow_dispatch','refs/heads/main',True),('workflow_dispatch','refs/heads/room/some-branch',False),
            ('workflow_dispatch','refs/heads/release-0.1',False),('workflow_dispatch','refs/tags/main',False),
            ('schedule','refs/heads/room/some-branch',False),('push','refs/heads/release-0.1',False),
            ('push','refs/tags/main',False)]:
            with self.subTest(event=event,ref=ref),tempfile.TemporaryDirectory() as folder:
                tmp=Path(folder);(tmp/'bin').mkdir()
                fake=tmp/'bin/python3';fake.write_text('#!/bin/sh\nprintf \"%s\\n\" \"$*\" >> \"$CALLS\"\n');fake.chmod(0o755)
                expr=expression.replace('github.ref',repr(ref)).replace('github.event_name',repr(event)).replace('&&',' and ').replace('||',' or ')
                main=eval(expr,{'__builtins__':{}},{})
                env=dict(os.environ,HOME=str(tmp),MAIN=str(main).lower(),PATH=str(tmp/'bin')+os.pathsep+os.environ['PATH'],
                    CALLS=str(tmp/'calls'),GITHUB_OUTPUT=str(tmp/'output'),GITHUB_SHA='a'*40,RUNNER_TEMP=str(tmp))
                result=subprocess.run(['bash','-euo','pipefail','-c',script],cwd=ROOT,env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stderr)
                calls=(tmp/'calls').read_text().splitlines()
                self.assertEqual(sum('ci/select/job.py sign' in c for c in calls),int(wants),calls)
                self.assertEqual((tmp/'output').read_text().splitlines() if (tmp/'output').exists() else [],['save=true'] if wants else [])

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
