#!/usr/bin/env python3
"""K16 dispatch proof at the workflow boundary. Synthetic fake commands only."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class Dispatch(unittest.TestCase):
    def run_skills(self, selected, fail=''):
        # Run the actual plan executor, replacing only suite subprocesses.
        import hashlib
        import json
        with tempfile.TemporaryDirectory() as folder:
            tmp = Path(folder)
            record = json.loads((ROOT / 'ci/selection/valid/selected-skill-only.json').read_text())
            names = ['triage', 'where-are-we', 'hill-climb', 'image', 'plan-graph', 'launch-fleet']
            chosen = names if selected == 'all' else ([] if selected == 'none' else selected.split())
            record['lanes']['skills'] = [dict(skill=n, **(
                {'decision': 'run', 'tests': ['skill:'+n], 'skipped': []} if n in chosen else
                {'decision': 'skip', 'reason': 'not selected'})) for n in names]
            raw = json.dumps(record)
            (tmp/'ci-selection.json').write_text(raw)
            flags = dict.fromkeys(('build-web','lint-rust','export-rust','export-web','build-site','image-skills',
                                  'rust','web','site','release','trace','planted','toolkit'),False)
            flags.update(skills=[n for n in names if n in chosen],plan_sha256=hashlib.sha256(raw.encode()).hexdigest())
            (tmp/'ci-dispatch.json').write_text(json.dumps(flags))
            log = tmp/'calls'
            fake = "#!PYTHON\nimport os,sys\nline=os.path.basename(sys.argv[0])+' '+' '.join(sys.argv[1:])\nwith open(os.environ['CALLS'],'a') as f: f.write(line+'\\n')\nsys.exit(9 if os.environ.get('FAIL') and os.environ['FAIL'] in line else 0)\n".replace('PYTHON',sys.executable)
            for name in ('python3','sh'):
                (tmp/name).write_text(fake); (tmp/name).chmod(0o755)
            env=dict(os.environ,PATH=str(tmp)+os.pathsep+os.environ['PATH'],CALLS=str(log),FAIL=fail,
                     GITHUB_RUN_ID=str(record['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='pull_request')
            code=0
            for name in flags['skills']:
                proc=subprocess.run([sys.executable,'-I',str(ROOT/'.github/actions/docs-only/run.py'),
                    'execute',str(tmp),'skill:'+name],cwd=ROOT,env=env,capture_output=True,text=True)
                if proc.returncode: code=proc.returncode; break
            return code,log.read_text().splitlines() if log.exists() else []

    def test_triage_and_collector_full_and_selected(self):
        all_calls=['python3 -I skills/triage/test/test_find_work.py',
            'python3 -I skills/where-are-we/test/test_read_github.py',
            'python3 -I -m unittest discover -s skills/hill-climb/tests',
            'python3 -I -m unittest discover -s skills/image/tests',
            'python3 -I skills/plan-graph/scripts/test_check_approval.py',
            'sh skills/plan-graph/test/test-revision.sh','sh skills/launch-fleet/scripts/test.sh',
            'python3 -I skills/launch-fleet/test/ops-protocol/test_protocol.py',
            'python3 -I skills/launch-fleet/scripts/test-effects.py',
            'python3 -I skills/launch-fleet/scripts/test-grants.py',
            'python3 -I skills/launch-fleet/scripts/test-inbox.py',
            'python3 -I tools/review-relay/test_inbox.py']
        self.assertEqual(self.run_skills('all'),(0,all_calls))
        for selected,expected in [('triage',all_calls[:1]),('where-are-we',all_calls[1:2]),('none',[])]:
            self.assertEqual(self.run_skills(selected),(0,expected))

    def test_suite_failure_is_exposed_only_when_selected(self):
        for selected,failed in [('all',True),('launch-fleet',True),('none',False),('triage',False)]:
            code,calls=self.run_skills(selected,'skills/launch-fleet/scripts/test.sh')
            self.assertEqual(code!=0,failed,(selected,calls))
            self.assertEqual(any('skills/launch-fleet/scripts/test.sh' in c for c in calls),failed)

    def test_ops_protocol_failure_fails_its_selected_lane(self):
        proof = 'skills/launch-fleet/test/ops-protocol/test_protocol.py'
        for selected, failed in [('launch-fleet', True), ('all', True), ('triage', False), ('none', False)]:
            code, calls = self.run_skills(selected, proof)
            self.assertEqual(code != 0, failed, (selected, calls))
            self.assertEqual(any(proof in call for call in calls), failed)


    def test_ops_effects_execution_and_failure_propagation(self):
        proof = 'skills/launch-fleet/scripts/test-effects.py'
        command = 'python3 -I ' + proof
        for selected, included in [('launch-fleet', True), ('all', True),
                                   ('triage', False), ('none', False)]:
            for failure in ('', proof):
                with self.subTest(selected=selected, failure=bool(failure)):
                    code, calls = self.run_skills(selected, failure)
                    self.assertEqual(code != 0, included and bool(failure), (selected, calls))
                    self.assertEqual(calls.count(command), int(included), (selected, calls))


    def test_ops_grants_execution_and_failure_propagation(self):
        proof = 'skills/launch-fleet/scripts/test-grants.py'
        command = 'python3 -I ' + proof
        for selected, included in [('launch-fleet', True), ('all', True),
                                   ('triage', False), ('none', False)]:
            for failure in ('', proof):
                with self.subTest(selected=selected, failure=bool(failure)):
                    code, calls = self.run_skills(selected, failure)
                    self.assertEqual(code != 0, included and bool(failure), (selected, calls))
                    self.assertEqual(calls.count(command), int(included), (selected, calls))

    def test_ops_inbox_execution_and_failure_propagation(self):
        for proof in ('skills/launch-fleet/scripts/test-inbox.py', 'tools/review-relay/test_inbox.py'):
            command = 'python3 -I ' + proof
            for selected, included in [('launch-fleet', True), ('all', True),
                                       ('triage', False), ('none', False)]:
                for failure in ('', proof):
                    with self.subTest(proof=proof, selected=selected, failure=bool(failure)):
                        code, calls = self.run_skills(selected, failure)
                        self.assertEqual(code != 0, included and bool(failure), (selected, calls))
                        self.assertEqual(calls.count(command), int(included), (selected, calls))


class Validation(unittest.TestCase):
    FULL = {'selection': 'full', 'rust-tests': 'all', 'web-tests': 'all', 'web-files': 'all',
            'skill-tests': 'all', 'build-web': 'true', 'lint-rust': 'true', 'export-rust': 'true',
            'export-web': 'true', 'build-site': 'true', 'image-skills': 'true'}
    DOCS = {'selection': 'selected', 'rust-tests': 'rust:test:checks', 'web-tests': 'none', 'web-files': 'none',
            'skill-tests': 'none', 'build-web': 'false', 'lint-rust': 'false', 'export-rust': 'false',
            'export-web': 'false', 'build-site': 'false', 'image-skills': 'false'}

    def validate(self, text, code=0):
        action = (ROOT / '.github/actions/docs-only/action.yml').read_text()
        script = action.split('    - id: select\n', 1)[1].split('      run: |\n', 1)[1].split('    - id: prune', 1)[0]
        script = '\n'.join(line[8:] for line in script.splitlines())
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            out = tmp / 'output'
            wrapper = tmp / 'python3'
            wrapper.write_text('''#!PYTHON
import os, subprocess, sys
if sys.argv[1:4] == ['-I', 'ci/select/job.py', 'select']:
    path = sys.argv[sys.argv.index('--github-output') + 1]
    if 'ANSWER' in os.environ:
        with open(path, 'w') as f: f.write(os.environ['ANSWER'])
    sys.exit(int(os.environ['SELECTOR_RC']))
sys.exit(subprocess.call([sys.executable, *sys.argv[1:]]))
'''.replace('PYTHON', sys.executable))
            wrapper.chmod(0o755)
            env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ['PATH'],
                       PLAIN=str(tmp / 'plain'), REPO='synthetic/repo', GITHUB_OUTPUT=str(out),
                       GITHUB_STEP_SUMMARY=str(tmp / 'summary'), SELECTOR_RC=str(code))
            if text is not None:
                env['ANSWER'] = text
            proc = subprocess.run(['/bin/bash', '-euo', 'pipefail', '-c', script], cwd=ROOT,
                                  env=env, capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return dict(line.split('=', 1) for line in out.read_text().splitlines())

    def test_complete_docs_answer_and_every_kind_of_incomplete_answer(self):
        valid = ''.join(f'{k}={v}\n' for k, v in self.DOCS.items())
        self.assertEqual(self.validate(valid), self.DOCS)
        self.assertEqual(self.validate(valid, code=1), self.FULL)
        for text in (None, '', valid.replace('skill-tests=none\n', ''), valid + 'build-web=false\n',
                     valid.replace('lint-rust=false', 'lint-rust=FALSE'),
                     valid.replace('skill-tests=none', 'skill-tests=unknown'),
                     valid.replace('rust-tests=rust:test:checks', 'rust-tests=garbage'),
                     valid.replace('selection=selected', 'selection=full'), valid + 'unknown=false\n',
                     valid.replace('export-rust=false', 'export-rust=true'),
                     valid.replace('skill-tests=none', 'skill-tests=image'),
                     valid.replace('web-tests=none', 'web-tests=web:unit:api')):
            with self.subTest(text=text):
                self.assertEqual(self.validate(text), self.FULL)



class Workflow(unittest.TestCase):
    def scheduled(self, output, export_result='success'):
        source=(ROOT/'.github/workflows/ci.yml').read_text().split('jobs:\n',1)[1]
        blocks=re.findall(r'^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)',source,re.M|re.S)
        ran=set()
        for name,block in blocks:
            if name in ('changes','select-map','ci','web-test','toolkit-nightly'): continue
            expression=re.search(r'^    if: \$\{\{ (.*) \}\}$',block,re.M)[1]
            expression=re.sub(r'needs\.changes\.outputs\.([a-z-]+)',lambda m:repr(output.get(m[1],'')),expression)
            expression=expression.replace('needs.changes.result',repr('success')).replace('needs.web-build.result',repr(export_result))
            expression=expression.replace('!cancelled()','True').replace('&&',' and ').replace('||',' or ')
            if eval(expression,{'__builtins__':{}},{}): ran.add(name)
        return ran

    def test_skill_only_full_conditional_export_and_missing_answers(self):
        full=dict.fromkeys(('rust','web','site','release','build-web','export-rust','export-web'),'true')
        full['skills']='["triage","launch-fleet"]'
        self.assertEqual(self.scheduled(full),{'always','web-build','rust-export','web-export','site','release','skills'})
        direct=dict(full,**{'export-rust':'false','export-web':'false'})
        self.assertEqual(self.scheduled(direct),{'always','web-build','rust','web','site','release','skills'})
        self.assertEqual(self.scheduled(dict(skills='["launch-fleet"]')),{'always','skills'})
        self.assertEqual(self.scheduled({}),{'always'})
        self.assertEqual(self.scheduled(full,'failure'),{'always','web-build','site','release','skills'})
        # A missing answer does not certify skipped work: final-job fixture
        # tests require each plan-named job and every matrix receipt.



if __name__ == '__main__':
    unittest.main()
