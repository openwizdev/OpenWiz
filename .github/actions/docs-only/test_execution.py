#!/usr/bin/env python3
"""Lane execution proofs at X5's actual executor boundary.

Only suite/build processes are replaced; no Cargo work runs. The web, site
and export cases went with the web view and the site copy (#1264).
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
            tmp=Path(folder)
            record=json.loads((ROOT/'ci/selection/valid/full-nightly.json').read_text())
            gone={'decision':'skip','reason':'the web view and its export went in #1264'}
            record['lanes']['web']=gone
            record['builds']['web_export']=gone
            record['lanes']['site']['tests']=['release:package','release:install']
            if over.get('RELEASE_SMOKE'):
                record['lanes']['site']['tests']=['release:test']
            if 'release_tests' in over:
                record['lanes']['site']['tests']=list(over.pop('release_tests'))
            selection=over.pop('selection','full')
            checks_only=over.pop('checks_only',False)
            mode=over.pop('mode','execute')
            extra=over.pop('args',[])
            if selection=='selected' or checks_only:
                record['selection']={'mode':'selected'}
                record['run'].update(event='pull_request',action='synchronize',base='1'*40,pull_request=909)
                record['diff']={'state':'read','paths':['tests/checks/main.rs']}
            if checks_only:
                record['lanes']['rust']={'decision':'skip','reason':'checks execute in always'}
            raw=json.dumps(record)
            (tmp/'ci-selection.json').write_text(raw)
            dispatch=dict.fromkeys(('build-site','image-skills','rust','release'),True)
            dispatch.update(**{'lint-rust':checks_only},skills=['launch-fleet','plan-graph','triage'],
                            trace=False,planted=False,
                            plan_sha256=hashlib.sha256(raw.encode()).hexdigest())
            if checks_only:
                dispatch['rust']=False
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
if os.environ.get('FAIL') and os.environ['FAIL'] in line: sys.exit(9)
'''.replace('PYTHON',sys.executable)
            for name in ('python3','sh','cargo'):
                (bin/name).write_text(fake); (bin/name).chmod(0o755)
            env=dict(os.environ,PATH=str(bin)+os.pathsep+os.environ['PATH'],CALLS=str(tmp/'calls'),
                     RUNNER_TEMP=str(tmp),GITHUB_RUN_ID=str(record['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME=record['run']['event'],REAL_ROOT=str(ROOT),REAL_INTERPRETER=sys.executable,**over)
            result=subprocess.run([sys.executable,'-I',str(HERE/'run.py'),mode,str(tmp),*([kind] if mode=='execute' else []),*extra],
                                  cwd=tmp,env=env,capture_output=True,text=True)
            calls=(tmp/'calls').read_text().splitlines() if (tmp/'calls').exists() else []
            if over.get('KEEP_RAN'):
                for ran in tmp.glob('ran-*.json'): shutil.copy(ran,over['KEEP_RAN'])
            return result.returncode,calls,result.stderr

    def test_release_shards_together_run_every_command_once_with_its_build(self):
        # catches (#743): a member split that drops or doubles a release proof
        # or runs the package proof without its build.
        tests=['release:package','release:install','release:test','release:ci-runner']
        code,whole,err=self.execute('release',release_tests=tests)
        self.assertEqual(code,0,err)
        want=sorted(whole)
        with tempfile.TemporaryDirectory() as keep:
            ran=[]
            for k in (1,2,3):
                code,calls,err=self.execute('release',release_tests=tests,KEEP_RAN=keep,
                    args=['--shard',f'{k}/3',f'ran-{k}.json'])
                self.assertEqual(code,0,err)
                if any('test_package.py' in c for c in calls):
                    build=calls.index('cargo build --locked --jobs 2 -p openwiz-cli --bins')
                    self.assertEqual(calls[build+1],'python3 -I tools/release/test_package.py')
                ran+=calls
            self.assertEqual(sorted(ran),want)
            self.assertEqual(len(list(Path(keep).glob('ran-*.json'))),3)

    def test_always_runs_format_selector_and_the_whole_static_checks_binary_once(self):
        code,calls,err=self.execute('always')
        self.assertEqual(code,0,err)
        self.assertEqual(calls,['cargo fmt --check','sh .github/actions/docs-only/test.sh --always',
            'sh ci/hosted/test.sh','cargo test -p openwiz-tests --test checks --locked'])

    def test_checks_only_selection_still_executes_its_lint_request(self):
        code,calls,err=self.execute('rust',checks_only=True,mode='lint')
        self.assertEqual(code,0,err)
        self.assertEqual(calls,['cargo clippy --workspace --all-targets -- -D warnings',
            'cargo build --workspace --locked','cargo build --release --locked'])

    def test_always_lint_fallback_runs_only_without_a_rust_test_lane(self):
        code,calls,err=self.execute('rust',checks_only=True,mode='lint-always')
        self.assertEqual(code,0,err)
        self.assertEqual(len(calls),3,calls)
        code,calls,err=self.execute('rust',mode='lint-always')
        self.assertEqual(code,0,err)
        self.assertEqual(calls,[])

    def test_selected_suite_failure_is_never_swallowed(self):
        for kind,fail in [('rust','ci/rust-tests.sh --only'),('release','tools/release/test_package.py'),
                          ('release','cargo build')]:
            good,successful,err=self.execute(kind)
            self.assertEqual(good,0,(successful,err))
            code,calls,err=self.execute(kind,FAIL=fail)
            self.assertEqual(code,1,(calls,err))
            matches=[i for i,c in enumerate(calls) if fail in c]
            self.assertEqual(len(matches),1,(kind,calls))
            self.assertEqual(calls,successful[:matches[0]+1])
            self.assertIn('exit status 9',err)

    def test_release_package_owns_its_binary_build_and_stops_on_failure(self):
        # The package proof reads the debug CLI. A separate job must prepare
        # it even when its Cargo cache is cold.
        build='cargo build --locked --jobs 2 -p openwiz-cli --bins'
        package='python3 -I tools/release/test_package.py'
        code,calls,err=self.execute('release',release_tests=['release:package'])
        self.assertEqual(code,0,err)
        self.assertEqual(calls,[build,package])
        for fail,wants in [('cargo build',[build]),('test_package.py',[build,package])]:
            with self.subTest(fail=fail):
                code,calls,err=self.execute('release',
                    release_tests=['release:package'],FAIL=fail)
                self.assertEqual(code,1,(calls,err))
                self.assertEqual(calls,wants)
                self.assertIn('exit status 9',err)
        code,calls,err=self.execute('release',release_tests=['release:install'])
        self.assertEqual(code,0,err)
        self.assertEqual(calls,['python3 -I tools/install/test_install.py'])

    def test_release_entrypoint_can_import_its_sibling_proofs(self):
        # Exercise the real release entrypoint and one existing cheap case;
        # stubbing Python here previously hid its script-directory imports.
        code,calls,err=self.execute('release',RELEASE_SMOKE='1')
        self.assertEqual(code,0,err)
        self.assertEqual(len(calls),1,calls)
        self.assertIn('Ran 1 test',err)


if __name__=='__main__': unittest.main()
