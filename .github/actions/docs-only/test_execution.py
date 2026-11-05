#!/usr/bin/env python3
"""K15 trace/fallback/planted proofs at X5's actual executor boundary.

Only suite/build processes are replaced; no Cargo, npm or browser work runs.
These replace the previous workflow-shell stubs, preserving their cases.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


class Execution(unittest.TestCase):
    def execute(self,kind,**over):
        with tempfile.TemporaryDirectory() as folder:
            tmp=Path(folder); (tmp/'apps/web/test/unit').mkdir(parents=True)
            (tmp/'apps/site').mkdir(parents=True)
            (tmp/'apps/web/test/unit/api.test.ts').write_text('// synthetic')
            record=json.loads((ROOT/'ci/selection/valid/full-nightly.json').read_text())
            record['lanes']['web']['tests']=['web:unit:api']
            record['lanes']['site']['tests']=['site:build','site:test','site:ci','release:package','release:install','release:open-tickets']
            if over.get('RELEASE_SMOKE'):
                record['lanes']['site']['tests']=['site:build','site:test','site:ci','release:test']
            if 'release_tests' in over:
                record['lanes']['site']['tests']=['site:build','site:test','site:ci',*over.pop('release_tests')]
            selection=over.pop('selection','full')
            checks_only=over.pop('checks_only',False)
            mode=over.pop('mode','execute')
            if selection=='selected' or checks_only:
                record['selection']={'mode':'selected'}
                record['run'].update(event='pull_request',action='synchronize',base='1'*40,pull_request=909)
                record['diff']={'state':'read','paths':['tests/checks/main.rs']}
            if checks_only:
                record['lanes']['rust']={'decision':'skip','reason':'checks execute in always'}
            if over.get('SOAK_CASE')=='execution':
                record['lanes']['web']['tests'].append('web:browser:v7-soak')
                soak=tmp/'apps/web/test/browser/v7-soak.test.mjs'
                soak.parent.mkdir(parents=True,exist_ok=True);soak.write_text('// synthetic')
            raw=json.dumps(record)
            (tmp/'ci-selection.json').write_text(raw)
            dispatch=dict.fromkeys(('build-web','export-rust','export-web','build-site','image-skills',
                                   'rust','web','site','release'),True)
            dispatch.update(**{'lint-rust':checks_only},skills=['launch-fleet','plan-graph','triage'],
                            trace=over.pop('trace',True),planted=over.pop('planted',False),toolkit=not checks_only,
                            plan_sha256=hashlib.sha256(raw.encode()).hexdigest())
            if checks_only:
                dispatch['rust']=False
                dispatch['export-rust']=False
            (tmp/'ci-dispatch.json').write_text(json.dumps(dispatch))
            bin=tmp/'bin'; bin.mkdir()
            fake='''#!PYTHON
import os,sys,subprocess,json
sys.dont_write_bytecode=True
line=os.path.basename(sys.argv[0])+' '+' '.join(sys.argv[1:])
with open(os.environ['CALLS'],'a') as f: f.write(line+'\\n')
if os.environ.get('RELEASE_SMOKE') and 'tools/release/test.py' in sys.argv:
    os.chdir(os.environ['REAL_ROOT'])
    os.execv(os.environ['REAL_INTERPRETER'],[os.environ['REAL_INTERPRETER'],*sys.argv[1:],
        'ExportFindings.test_fixed_prose_and_technical_check_references_pass'])
if 'trace.py ready' in line: sys.exit(int(os.environ.get('READY_RC','0')))
if 'ci/rust-tests.sh --can-run-at-once' in line: sys.exit(int(os.environ.get('ROOM_RC','0')))
if 'ci/select/trace.py web ' in line and os.environ.get('SOAK_CASE'):
    sys.path.insert(0,os.path.join(os.environ['REAL_ROOT'],'ci/select'))
    import test_trace
    fixture=test_trace.TraceLane('test_a_full_web_run_without_the_soak_s_file_fails')
    logs={'web:unit:api':(0,fixture.PLAIN_OK,None,'')}
    if os.environ['SOAK_CASE']=='execution': logs['web:browser:v7-soak']=(0,fixture.PLAIN_OK,None,'')
    only=sys.argv[sys.argv.index('--only')+1:] if '--only' in sys.argv else None
    try: code=fixture.lane(logs,only=only,units=tuple(logs))
    finally: fixture.doCleanups()
    if code: print('real tracer soak coverage refused',file=sys.stderr)
    sys.exit(code)
if 'ci/select/trace.py ' in line: sys.exit(int(os.environ.get('TRACE_RC','0')))
if os.environ.get('SOAK_CASE') and (line=='npm test' or line.startswith('node test/run-browser.mjs')):
    root=os.environ['REAL_ROOT']
    only=sys.argv[sys.argv.index('--only')+1:] if '--only' in sys.argv else None
    driver="const {checkSkips}=await import('file://"+root+"/apps/web/test/soak-skip.mjs');"+"const {soakSelected}=await import('file://"+root+"/apps/web/test/run-browser.mjs');"+"checkSkips([{file:'test/unit/api.test.ts',name:'synthetic',nesting:0,skip:false}],false,soakSelected({only:"+json.dumps(only)+"},"+json.dumps(only or ['test/unit/api.test.ts'])+"));"
    sys.exit(subprocess.run([os.environ['REAL_NODE'],'--input-type=module','-e',driver]).returncode)
if os.environ.get('FAIL') and os.environ['FAIL'] in line: sys.exit(9)
'''.replace('PYTHON',sys.executable)
            for name in ('python3','sh','cargo','node','npm'):
                (bin/name).write_text(fake); (bin/name).chmod(0o755)
            env=dict(os.environ,PATH=str(bin)+os.pathsep+os.environ['PATH'],CALLS=str(tmp/'calls'),
                     RUNNER_TEMP=str(tmp),GITHUB_RUN_ID=str(record['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME=record['run']['event'],REAL_ROOT=str(ROOT),REAL_NODE=shutil.which('node'),REAL_INTERPRETER=sys.executable,**over)
            result=subprocess.run([sys.executable,'-I',str(HERE/'run.py'),mode,str(tmp),*([kind] if mode=='execute' else [])],
                                  cwd=tmp,env=env,capture_output=True,text=True)
            calls=(tmp/'calls').read_text().splitlines() if (tmp/'calls').exists() else []
            return result.returncode,calls,result.stderr

    def test_trace_failures_fallback_and_planted_edits_for_both_lanes(self):
        for kind in ('rust','web'):
            for overrides,traces,normal,fails in [({},True,False,False),({'TRACE_RC':'1'},True,False,True),
                ({'TRACE_RC':'3'},True,True,False),({'READY_RC':'1'},False,True,False),
                ({'trace':False},False,True,False)]:
                with self.subTest(kind=kind,overrides=overrides):
                    code,calls,err=self.execute(kind,planted=True,**overrides)
                    self.assertEqual(code!=0,fails,err)
                    self.assertEqual(any('ci/select/trace.py '+kind+' ' in c for c in calls),traces)
                    needle='sh ci/rust-tests.sh --only ' if kind=='rust' else 'npm test'
                    self.assertEqual(any(c.startswith(needle) for c in calls),normal,calls)
                    self.assertEqual(any('planted.py '+kind+' ' in c for c in calls),not fails,calls)
        code,calls,err=self.execute('rust',ROOM_RC='1',planted=True)
        self.assertEqual(code,0,err)
        self.assertFalse(any('trace.py rust ' in c for c in calls))
        self.assertTrue(any('planted.py rust ' in c for c in calls))
        self.assertTrue(any(c.startswith('sh ci/rust-tests.sh --only ') for c in calls))

    def test_export_trace_and_fallback_and_failure(self):
        for overrides,normal,fails in [({},False,False),({'TRACE_RC':'3'},True,False),
            ({'TRACE_RC':'1'},False,True),({'trace':False},True,False)]:
            code,calls,err=self.execute('build:web_export',**overrides)
            self.assertEqual(code!=0,fails,err)
            self.assertEqual('npm run build' in calls,normal,calls)
            self.assertEqual('npm run typecheck' in calls,not fails,calls)
            self.assertEqual('npm run check' in calls,not fails,calls)

    def test_always_runs_format_selector_and_the_whole_static_checks_binary_once(self):
        code,calls,err=self.execute('always',trace=False)
        self.assertEqual(code,0,err)
        self.assertEqual(calls,['cargo fmt --check','sh .github/actions/docs-only/test.sh --always',
            'sh ci/hosted/test.sh','python3 -I ci/select/test_pick.py','python3 -I ci/select/test_trace.py',
            'python3 -I ci/select/test_job.py','python3 -I ci/select/test_steps.py',
            'cargo test -p openwiz-tests --test checks --locked'])

    def test_checks_only_selection_still_executes_its_lint_request(self):
        code,calls,err=self.execute('rust',checks_only=True,trace=False,mode='lint')
        self.assertEqual(code,0,err)
        self.assertEqual(calls,['cargo clippy --workspace --all-targets -- -D warnings',
            'cargo build --workspace --locked','cargo build --release --locked'])

    def test_always_lint_fallback_runs_only_without_a_rust_test_lane(self):
        code,calls,err=self.execute('rust',checks_only=True,trace=False,mode='lint-always')
        self.assertEqual(code,0,err)
        self.assertEqual(len(calls),3,calls)
        code,calls,err=self.execute('rust',trace=False,mode='lint-always')
        self.assertEqual(code,0,err)
        self.assertEqual(calls,[])

    def test_full_web_refuses_missing_soak_file_and_execution(self):
        for case in ('file','execution'):
            for traced in (True,False):
                with self.subTest(case=case,traced=traced):
                    code,calls,err=self.execute('web',SOAK_CASE=case,trace=traced)
                    self.assertEqual(code,1,(calls,err))
                    self.assertIn('soak',err)

    def test_selected_web_can_leave_the_soak_unselected(self):
        code,calls,err=self.execute('web',SOAK_CASE='file',selection='selected',trace=False)
        self.assertEqual(code,0,err)
        self.assertTrue(any(c.startswith('node test/run-browser.mjs --with-unit --only ') for c in calls))

    def test_selected_suite_failure_is_never_swallowed(self):
        for kind,fail in [('rust','ci/rust-tests.sh --only'),('web','npm test'),
                          ('site','npm test'),('release','tools/release/test_package.py'),
                          ('release','cargo build'),
                          ('release','tools/open-tickets/test.sh')]:
            good,successful,err=self.execute(kind,trace=False)
            self.assertEqual(good,0,(successful,err))
            code,calls,err=self.execute(kind,trace=False,FAIL=fail)
            self.assertEqual(code,1,(calls,err))
            matches=[i for i,c in enumerate(calls) if fail in c]
            self.assertEqual(len(matches),1,(kind,calls))
            self.assertEqual(calls,successful[:matches[0]+1])
            self.assertIn('exit status 9',err)

    def test_release_package_owns_its_binary_build_and_stops_on_failure(self):
        # The installed-engine package proof reads two debug binaries. A
        # separate job must prepare them even when its Cargo cache is cold.
        build='cargo build --locked --jobs 2 -p openwiz-cli -p openwiz-service --bins'
        package='python3 -I tools/release/test_package.py'
        code,calls,err=self.execute('release',trace=False,release_tests=['release:package'])
        self.assertEqual(code,0,err)
        self.assertEqual(calls,[build,package])
        for fail,wants in [('cargo build',[build]),('test_package.py',[build,package])]:
            with self.subTest(fail=fail):
                code,calls,err=self.execute('release',trace=False,
                    release_tests=['release:package'],FAIL=fail)
                self.assertEqual(code,1,(calls,err))
                self.assertEqual(calls,wants)
                self.assertIn('exit status 9',err)
        code,calls,err=self.execute('release',trace=False,release_tests=['release:install'])
        self.assertEqual(code,0,err)
        self.assertEqual(calls,['python3 -I tools/install/test_install.py'])

    def test_selected_release_executes_site_work_once_and_stops_on_either_failure(self):
        expected = ['npm run build', 'npm test', 'npm run test:ci',
                    'python3 -I tools/install/test_install.py']
        for failure, count in [('', 4), ('npm run build', 1), ('npm test', 2),
                               ('npm run test:ci', 3), ('test_install.py', 4)]:
            with self.subTest(failure=failure):
                code, calls, err = self.execute('release', selection='selected', trace=False,
                    release_tests=['release:install'], FAIL=failure)
                self.assertEqual(calls, expected[:count])
                self.assertEqual(code, 1 if failure else 0, err)
                if failure:
                    self.assertIn('exit status 9', err)

    def test_ops_live_controls_runs_the_exact_proof_and_propagates_failure(self):
        command = 'python3 -I tools/ops-live/controls/test_kit.py'
        for fail in ('', 'tools/ops-live/controls/test_kit.py'):
            with self.subTest(fail=bool(fail)):
                code,calls,err=self.execute('release',trace=False,
                    release_tests=['release:ops-live-controls'],FAIL=fail)
                self.assertEqual(calls,[command])
                self.assertEqual(code,1 if fail else 0,err)
                if fail:
                    self.assertIn('exit status 9',err)

    def test_ops_live_acceptance_runs_the_exact_proof_and_propagates_failure(self):
        command = 'python3 -I tools/ops-live/test_acceptance.py'
        for fail in ('', 'tools/ops-live/test_acceptance.py'):
            with self.subTest(fail=bool(fail)):
                code,calls,err=self.execute('release',trace=False,
                    release_tests=['release:ops-live-acceptance'],FAIL=fail)
                self.assertEqual(calls,[command])
                self.assertEqual(code,1 if fail else 0,err)
                if fail:
                    self.assertIn('exit status 9',err)

    def test_ci2_read_contract_executes_and_propagates_failure(self):
        # C1-CI: a green plan cannot hide a missing or failed validator.
        for fail in ('', 'tools/github-reads/test_contract.py'):
            with self.subTest(fail=bool(fail)):
                code, calls, err = self.execute('release', trace=False,
                    release_tests=['release:ci2-read-contract'], FAIL=fail)
                self.assertEqual(calls, ['python3 -I tools/github-reads/test_contract.py'])
                self.assertEqual(code, 1 if fail else 0, err)
                if fail:
                    self.assertIn('exit status 9', err)

    def test_ci2_shared_reads_executes_and_propagates_failure(self):
        # C8-CI: a green plan cannot hide a missing or failed shared-read proof.
        for fail in ('', 'tools/github-reads/test_read.py'):
            with self.subTest(fail=bool(fail)):
                code, calls, err = self.execute('release', trace=False,
                    release_tests=['release:ci2-shared-reads'], FAIL=fail)
                self.assertEqual(calls, ['python3 -I tools/github-reads/test_read.py'])
                self.assertEqual(code, 1 if fail else 0, err)
                if fail:
                    self.assertIn('exit status 9', err)

    def test_ci2_read_consumers_executes_and_propagates_failure(self):
        # C10-CI: a green plan cannot hide a missing or failed consumer proof.
        for fail in ('', 'tools/github-reads/test_consumers.py'):
            with self.subTest(fail=bool(fail)):
                code, calls, err = self.execute('release', trace=False,
                    release_tests=['release:ci2-read-consumers'], FAIL=fail)
                self.assertEqual(calls, ['python3 -I tools/github-reads/test_consumers.py'])
                self.assertEqual(code, 1 if fail else 0, err)
                if fail:
                    self.assertIn('exit status 9', err)

    def test_ci2_spending_runs_and_propagates_failure(self):
        command = 'python3 -I tools/ci-overflow/test.py GuardedHosted'
        for fail in ('', 'tools/ci-overflow/test.py'):
            code,calls,err=self.execute('release',trace=False,
                release_tests=['release:ci2-spending'],FAIL=fail)
            self.assertEqual(calls,[command])
            self.assertEqual(code,1 if fail else 0,err)

    def test_ci2_batch_contract_executes_and_propagates_failure(self):
        command = 'python3 -I ci/main-batch/test_contract.py'
        for fail in ('', 'ci/main-batch/test_contract.py'):
            with self.subTest(fail=bool(fail)):
                code, calls, err = self.execute('release', trace=False,
                    release_tests=['release:ci2-batch-contract'], FAIL=fail)
                self.assertEqual(calls, [command])
                self.assertEqual(code, 1 if fail else 0, err)
                if fail:
                    self.assertIn('exit status 9', err)

    def test_ci2_batch_shadow_executes_and_propagates_failure(self):
        command = 'python3 -I ci/main-batch/test_shadow.py'
        for fail in ('', 'ci/main-batch/test_shadow.py'):
            with self.subTest(fail=bool(fail)):
                code, calls, err = self.execute('release', trace=False,
                    release_tests=['release:ci2-batch-shadow'], FAIL=fail)
                self.assertEqual(calls, [command])
                self.assertEqual(code, 1 if fail else 0, err)
                if fail:
                    self.assertIn('exit status 9', err)

    def test_release_entrypoint_can_import_its_sibling_proofs(self):
        # Exercise the real release entrypoint and one existing cheap case;
        # stubbing Python here previously hid its script-directory imports.
        code,calls,err=self.execute('release',trace=False,RELEASE_SMOKE='1')
        self.assertEqual(code,0,err)
        self.assertEqual(len(calls),1,calls)
        self.assertIn('Ran 1 test',err)

    def test_ci2_overload_executes_and_propagates_failure(self):
        for fail in ('', 'tools/ci-overload/test.py'):
            with self.subTest(fail=fail):
                code,calls,err=self.execute('release',trace=False,
                    release_tests=['release:ci2-overload'],FAIL=fail)
                self.assertEqual(calls,['python3 -I tools/ci-overload/test.py'])
                self.assertEqual(code,1 if fail else 0,err)



if __name__=='__main__': unittest.main()
