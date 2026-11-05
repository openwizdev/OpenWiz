#!/usr/bin/env python3
"""LT3 prerequisites at the real X5 workflow/receipt boundary; no builds."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import test_lanes


def workflow():
    return Path(os.environ.get('X5_TEST_WORKFLOW',ROOT/'.github/workflows/ci.yml')).read_text()


def jobs(source):
    return dict((m[1],m[2]) for m in re.finditer(
        r'^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)',source.split('jobs:\n',1)[1],re.M|re.S))


def step(block, name):
    matches=[s for s in re.split(r'(?=^      - )',block,flags=re.M)
             if re.search(r'^        name: '+re.escape(name)+r'$',s,re.M)
             or s.startswith('      - name: '+name+'\n')]
    if len(matches)!=1: raise AssertionError('expected one step: '+name)
    return matches[0]


class Routing(unittest.TestCase):
    def test_toolkit_follows_exactly_one_rust_route_and_never_always(self):
        blocks=jobs(workflow())
        self.assertNotIn('live-check',blocks['always'])
        for required,rust,export in ((True,True,True),(True,True,False),(True,False,False),
                                     (False,True,True),(False,True,False),(False,False,False)):
            active=[]
            for name in ('rust','rust-export'):
                block=blocks[name]
                expr=re.search(r'^    if: \$\{\{ (.*) \}\}$',block,re.M)[1]
                for key,value in {'rust':rust,'toolkit':required,'export-rust':export}.items():
                    expr=expr.replace('needs.changes.outputs.'+key,repr(str(value).lower()))
                expr=expr.replace('needs.changes.result',repr('success')).replace('needs.web-build.result',repr('success')).replace('!cancelled()','True')
                expr=expr.replace('&&',' and ').replace('||',' or ')
                if eval(expr,{'__builtins__':{}},{}): active.append(name)
                self.assertIn('    timeout-minutes: 60\n',block)
                self.assertEqual(step(block,'The live-check toolkit (fixtures only)').count(
                    "        if: needs.changes.outputs.toolkit == 'true'\n"),1)
                self.assertIn('TOOLKIT_RESULT: ${{ steps.toolkit.outcome }}',step(block,'Record passed toolkit'))
                self.assertLess(block.index('Record passed toolkit'),block.index('Record passed lane'))
            self.assertEqual(active,(['rust-export' if export else 'rust'] if required or rust else []))

    def test_pr_shells_are_fast_and_nightly_retains_historical_work(self):
        blocks=jobs(workflow())
        for name in ('rust','rust-export'):
            fast=step(blocks[name],'The live-check toolkit (fixtures only)')
            body=re.search(r'^        run: \|\n((?:          .*\n|\n)+)',fast,re.M)[1]
            self.assertEqual([l.strip() for l in body.splitlines() if l.strip()], [
                'export PYTHONDONTWRITEBYTECODE=1', 'python3 tools/live-check/test_core.py',
                'python3 tools/live-check/plans/test_plans.py'])
            self.assertNotRegex(blocks[name],r'live-check-source|\.lt3-fixture-source|test_mutants\.py|live-check/(?:mutants\.py|plans/dry-run\.py|send/scripts/test|new/scripts/test)')
        nightly=blocks['toolkit-nightly']
        self.assertNotIn('    needs:',nightly)
        expression=re.search(r'^    if: (.+)$',nightly,re.M)[1]
        for event,ref,wants in [('pull_request','refs/pull/7/merge',False),('push','refs/heads/main',False),
            ('merge_group','refs/heads/main',False),('workflow_dispatch','refs/heads/main',False),
            ('schedule','refs/heads/release-x',False),('schedule','refs/heads/main',True)]:
            expr=expression.replace('github.event_name',repr(event)).replace('github.ref',repr(ref)).replace('&&',' and ')
            self.assertEqual(eval(expr,{'__builtins__':{}},{}),wants)
        self.assertIn('    timeout-minutes: 360\n',nightly)
        self.assertIn('    permissions:\n      contents: read\n',nightly)
        body=step(nightly,'The live-check toolkit (nightly fixtures and mutants)').split('        run: |\n',1)[1]
        for command in ('python3 tools/live-check/test_mutants.py',
            'sh tools/live-check/send/scripts/test/c8-tests.sh','sh tools/live-check/send/scripts/test/kit-tests.sh',
            'sh tools/live-check/send/scripts/test/sol-tests.sh','sh tools/live-check/new/scripts/test/kit-tests.sh',
            'python3 tools/live-check/plans/dry-run.py --profile send --log "$evidence/plan-send.log"',
            'python3 tools/live-check/plans/dry-run.py --profile new --log "$evidence/plan-new.log"',
            'python3 tools/live-check/mutants.py --logs "$evidence/mutants" --jobs 2'):
            self.assertEqual([l.strip() for l in body.splitlines()].count(command),1,command)
        for contract in ('export CARGO_BUILD_JOBS=2','trap finish_live_check EXIT',
                         'test -z "$fixture_remotes"','exit "$toolkit_status"'):
            self.assertIn(contract,body)
        upload=step(nightly,'Keep the nightly toolkit evidence')
        self.assertIn('        if: always()\n',upload)
        self.assertIn('          path: ${{ runner.temp }}/live-check-evidence\n',upload)



class Receipts(unittest.TestCase):
    def setUp(self):
        self.fixture=test_lanes.Lanes('test_every_planned_job_and_skill_member_passed')
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.fixture.dispatch['toolkit']=True
        self.save_dispatch()
        (self.fixture.receipts/'rust.json').unlink()
        (self.fixture.receipts/'prerequisite-toolkit.json').unlink()

    def save_dispatch(self):
        (self.fixture.path/'ci-dispatch.json').write_text(json.dumps(self.fixture.dispatch))

    def command(self,*args):
        env=dict(os.environ,RUNNER_TEMP=str(self.fixture.path),GITHUB_RUN_ID=str(self.fixture.plan['run']['id']),
                 GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='schedule')
        return subprocess.run([sys.executable,'-I',str(HERE/'run.py'),*args],
                              env=env,capture_output=True,text=True)

    def complete_from_workflow(self, job, outcome):
        f=self.fixture
        plan=f.path/'ci-plan';plan.mkdir(exist_ok=True)
        for name in ('ci-selection.json','ci-dispatch.json'):
            (plan/name).write_bytes((f.path/name).read_bytes())
        block=step(jobs(workflow())[job],'Record passed toolkit')
        script=re.search(r'^        run: (.+)$',block,re.M)[1]
        env=dict(os.environ,RUNNER_TEMP=str(f.path),TOOLKIT_RESULT=outcome,
                 GITHUB_RUN_ID=str(f.plan['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='schedule')
        return subprocess.run(['bash','-euo','pipefail','-c',script],cwd=ROOT,env=env,
                              capture_output=True,text=True)

    def test_successful_toolkit_allows_exact_plan_bound_rust_receipt(self):
        f=self.fixture
        for job in ('rust','rust-export'):
            with self.subTest(job=job):
                result=self.complete_from_workflow(job,'success')
                self.assertEqual(result.returncode,0,result.stderr)
                result=self.command('stamp',str(f.path),'rust',str(f.receipts))
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(f.run_finish().returncode,0)
                entry=json.loads((f.receipts/'prerequisite-toolkit.json').read_text())
                self.assertEqual(entry,dict(lane='prerequisite:toolkit',tests=[],plan_sha256=f.sha,run=f.plan['run']))
                (f.receipts/'rust.json').unlink()
                (f.receipts/'prerequisite-toolkit.json').unlink()

    def test_failed_skipped_or_missing_toolkit_prevents_receipt_and_ci(self):
        f=self.fixture
        for job,state in [(j,s) for j in ('rust','rust-export') for s in ('failure','cancelled','skipped','')]:
            with self.subTest(job=job,state=state):
                result=self.complete_from_workflow(job,state)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('toolkit',result.stderr)
                self.assertFalse((f.receipts/'prerequisite-toolkit.json').exists())
                result=self.command('stamp',str(f.path),'rust',str(f.receipts))
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('toolkit',result.stderr)
                self.assertFalse((f.receipts/'rust.json').exists())
                result=f.run_finish()
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn('missing',result.stderr)

    def test_deleting_the_toolkit_completion_step_still_cannot_stamp_or_pass_ci(self):
        f=self.fixture
        # A skipped/deleted completion step supplies no file at all.
        result=self.command('stamp',str(f.path),'rust',str(f.receipts))
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('toolkit',result.stderr)
        self.assertFalse((f.receipts/'rust.json').exists())
        result=f.run_finish()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('missing',result.stderr)

    def test_final_ci_requires_toolkit_even_when_all_lane_receipts_are_present(self):
        f=self.fixture
        f.receipt('rust',f.expected['rust'])
        result=f.run_finish()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn('missing lane receipts: prerequisite:toolkit',result.stderr)
        self.assertEqual(self.complete_from_workflow('rust-export','success').returncode,0)
        result=f.run_finish()
        self.assertEqual(result.returncode,0,result.stderr)

    def test_toolkit_only_rust_route_requires_its_receipt_without_inventing_test_ids(self):
        f=self.fixture
        f.plan['selection']={'mode':'selected'}
        f.plan['run'].update(event='pull_request',action='synchronize',base='1'*40,pull_request=909)
        f.plan['diff']={'state':'read','paths':['tools/live-check/core.py']}
        f.plan['lanes']['rust']={'decision':'skip','reason':'no mapped Rust tests affected'}
        raw=json.dumps(f.plan)
        f.sha=hashlib.sha256(raw.encode()).hexdigest()
        (f.path/'ci-selection.json').write_text(raw)
        f.dispatch.update(rust=False,**{'export-rust':False,'plan_sha256':f.sha})
        self.save_dispatch()
        f.needs.update(rust={'result':'success'},**{'rust-export':{'result':'skipped'}})
        f.needs['site']['result']='skipped'  # Selected site work runs in release.
        f.expected.pop('rust')
        for name,tests in f.expected.items():
            if name!='prerequisite:toolkit': f.receipt(name,tests)
        env=dict(os.environ,GITHUB_RUN_ID=str(f.plan['run']['id']),GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='pull_request')
        def run(*args):
            return subprocess.run([sys.executable,'-I',str(HERE/'run.py'),*args],env=env,capture_output=True,text=True)
        result=run('execute',str(f.path),'rust')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('only the planned toolkit',result.stdout)
        self.assertEqual(run('stamp',str(f.path),'rust',str(f.receipts)).returncode,1)
        self.assertEqual(run('toolkit',str(f.path),'success',str(f.receipts)).returncode,0)
        self.assertEqual(run('stamp',str(f.path),'rust',str(f.receipts)).returncode,0)
        self.assertFalse((f.receipts/'rust.json').exists())
        (f.path/'needs.json').write_text(json.dumps(f.needs))
        result=run('finish',str(f.path),str(f.path/'needs.json'),str(f.receipts))
        self.assertEqual(result.returncode,0,result.stderr)

    def test_stale_prerequisite_cannot_satisfy_the_rust_stamp(self):
        f=self.fixture
        self.assertEqual(self.command('toolkit',str(f.path),'success',str(f.receipts)).returncode,0)
        p=f.receipts/'prerequisite-toolkit.json'; original=p.read_text()
        for field,value in (('plan_sha256','0'*64),('run',{}),('tests',['unexpected']),('lane','other'),
                            ('run',dict(f.plan['run'],attempt=True))):
            entry=json.loads(original);entry[field]=value;p.write_text(json.dumps(entry))
            result=self.command('stamp',str(f.path),'rust',str(f.receipts))
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertIn('toolkit',result.stderr)


if __name__=='__main__': unittest.main()
