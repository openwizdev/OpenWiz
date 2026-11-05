#!/usr/bin/env python3
"""C7 public-boundary proofs. All API data and identities are synthetic.

C6 tests document conformance. These cases catch independent API failures,
pending terminal checks, dropped pending members and a stale restart instead.
Only GitHub reads are replaced; no mock supplies a coverage decision.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))


def seed():
    document = json.loads((HERE / 'fixtures/contract/superseded-pending.json').read_text())
    context = json.loads((HERE / 'fixtures/contract/superseded-pending-expected.json').read_text())
    reads = json.loads((HERE / 'fixtures/shadow/github.json').read_text())
    return document, context, reads


class RecordingGitHub:
    def __init__(self, reads):
        self.reads = copy.deepcopy(reads)
        self.calls = []
        self.on_read = None

    def get(self, path):
        self.calls.append(path)
        if self.on_read:
            self.on_read(path)
        if path not in self.reads:
            raise ValueError('unrecorded GET: ' + path)
        return copy.deepcopy(self.reads[path])

    def packet(self, rid, attempt, head):
        self.calls.append('authenticated-artifact')
        return copy.deepcopy(self.reads['_packet'])


class Shadow(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('shadow', HERE / 'shadow.py')
        self.shadow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.shadow)
        self.document, self.context, self.reads = seed()
        self.packet = dict(plan=self.document['plan'], receipts=self.document['receipts'],
                           event={'repository': 'synthetic/ci-example',
                                  'run': json.loads(self.document['plan'])['run']},
                           rust=self.reads['_packet']['rust'], complete=False, reason='terminal checks pending')
        self.state = dict(repository='synthetic/ci-example', covered='1'*40, pending=[], last=None)

    def reconcile(self, packet=None, context=None, state=None, source=None):
        return self.shadow.reconcile(source or RecordingGitHub(self.reads),
            self.packet if packet is None else packet,
            self.context if context is None else context,
            self.state if state is None else state, self.context['inventory'])

    def test_combined_success_advances_all_members_and_replay_is_idempotent(self):
        report, state = self.reconcile()
        self.assertTrue(report['complete'], report)
        self.assertEqual(state['covered'], '3'*40)
        self.assertEqual(state['pending'], [])
        self.assertEqual(state['last']['batch']['members'], self.context['batch']['members'])
        self.assertFalse(report['switch_authorized'])
        again, after = self.reconcile(state=json.loads(json.dumps(state)))
        self.assertTrue(again['complete'], again)
        self.assertEqual(after, state)

    def test_combined_only_failure_cannot_use_constituent_pr_greens(self):
        # Both constituent PRs can be green while messaging fails only at C.
        self.reads['actions/runs/9000100/attempts/1/jobs?per_page=100&page=1']['jobs'][2]['conclusion'] = 'failure'
        report, state = self.reconcile()
        self.assertFalse(report['complete'])
        self.assertEqual(state['covered'], '1'*40)
        self.assertEqual(state['pending'], self.context['batch']['members'])

    def test_missing_cancelled_pending_stale_and_matrix_work_refuse(self):
        original = copy.deepcopy(self.reads)
        for change in ('missing-job', 'cancelled', 'pending-ci', 'old-attempt',
                       'missing-check', 'missing-skill', 'missing-shard', 'failed-toolkit'):
            with self.subTest(change=change):
                self.reads = copy.deepcopy(original)
                jobs = self.reads['actions/runs/9000100/attempts/1/jobs?per_page=100&page=1']
                if change == 'missing-job':
                    jobs['jobs'].pop(1); jobs['total_count'] -= 1
                elif change == 'cancelled': jobs['jobs'][2]['conclusion'] = 'cancelled'
                elif change == 'pending-ci': jobs['jobs'][-1].update(status='in_progress', conclusion=None)
                elif change == 'old-attempt': self.reads['actions/runs/9000100']['run_attempt'] = 2
                elif change == 'missing-check':
                    self.reads['actions/runs/9000101/attempts/1/jobs?per_page=100&page=1']['jobs'] = []
                    self.reads['actions/runs/9000101/attempts/1/jobs?per_page=100&page=1']['total_count'] = 0
                elif change == 'missing-skill':
                    jobs['jobs'] = [j for j in jobs['jobs'] if j['name'] != 'skills (triage)']
                    jobs['total_count'] -= 1
                elif change == 'missing-shard':
                    jobs['jobs'] = [j for j in jobs['jobs'] if j['name'] != 'rust (2)']
                    jobs['total_count'] -= 1
                else: jobs['jobs'][2]['steps'][0]['conclusion'] = 'failure'
                report, state = self.reconcile()
                self.assertFalse(report['complete'], report)
                self.assertEqual(state['covered'], '1'*40)

    def test_planted_omitted_work_and_missing_receipt_refuse(self):
        for mutation in ('inventory', 'receipt', 'plan-bytes', 'event-base', 'extra-key'):
            with self.subTest(mutation=mutation):
                packet = copy.deepcopy(self.packet)
                if mutation == 'inventory':
                    plan = json.loads(packet['plan'])
                    plan['lanes']['rust']['tests'].remove('rust:test:messaging')
                    packet['plan'] = json.dumps(plan)
                elif mutation == 'receipt': packet['receipts'].pop(0)
                elif mutation == 'plan-bytes': packet['plan'] += '\n'
                elif mutation == 'event-base': packet['event']['run']['base'] = '1'*40
                else: packet['switch_authorized'] = True
                report, state = self.reconcile(packet=packet)
                self.assertFalse(report['complete'], report)
                self.assertEqual(state['covered'], '1'*40)

    def test_consistent_authenticated_undersized_plan_cannot_shrink_inventory(self):
        packet = copy.deepcopy(self.packet)
        plan = json.loads(packet['plan'])
        plan['lanes']['rust']['tests'].remove('rust:test:messaging')
        packet['plan'] = json.dumps(plan)
        digest = hashlib.sha256(packet['plan'].encode()).hexdigest()
        for receipt in packet['receipts']:
            receipt['plan_sha256'] = digest
            if receipt['lane'] == 'rust': receipt['tests'].remove('rust:test:messaging')
        for share in packet['rust']['shares']:
            if 'rust:test:messaging' in share['tests']: share['tests'].remove('rust:test:messaging')
        source = RecordingGitHub(self.reads)
        source.reads['_packet'] = copy.deepcopy(packet)
        report, state = self.reconcile(packet=packet,source=source)
        self.assertFalse(report['complete'],report)
        self.assertIn('independent candidate inventory',report['refusals'][0])
        self.assertEqual(state['covered'],'1'*40)

    def test_superseded_pending_push_restart_and_conflicting_history(self):
        # Pending B never received a full result; the complete B->C execution
        # must still cover A->C and retain both members until it is complete.
        state = dict(self.state, pending=self.context['batch']['members'][:1])
        source = RecordingGitHub(self.reads)
        source.reads['actions/runs/9000100/attempts/1/jobs?per_page=100&page=1']['jobs'][-1].update(
            status='in_progress', conclusion=None)
        report, pending = self.reconcile(state=state, source=source)
        self.assertFalse(report['complete'])
        self.assertEqual(pending['pending'], self.context['batch']['members'])
        report, complete = self.reconcile(state=json.loads(json.dumps(pending)))
        self.assertTrue(report['complete'], report)
        self.assertEqual(complete['covered'], '3'*40)
        for conflict in (dict(self.state, covered='2'*40),
                         dict(self.state, pending=[dict(self.context['batch']['members'][0], head='f'*40)])):
            report, unchanged = self.reconcile(state=conflict)
            self.assertFalse(report['complete'])
            self.assertEqual(unchanged, conflict)

    def test_independent_graph_protection_and_currentness_cannot_be_forged(self):
        for mutation in ('parent', 'pr-head', 'required', 'pagination', 'foreign-run', 'new-run'):
            with self.subTest(mutation=mutation):
                gh = RecordingGitHub(self.reads)
                if mutation == 'parent': gh.reads['commits/'+'3'*40]['parents'][0]['sha'] = '1'*40
                elif mutation == 'pr-head': gh.reads['pulls/9001']['head']['sha'] = 'f'*40
                elif mutation == 'required': gh.reads['branches/main/protection/required_status_checks']['contexts'].append('legacy')
                elif mutation == 'pagination': gh.reads['actions/runs/9000100/attempts/1/jobs?per_page=100&page=1']['total_count'] += 1
                elif mutation == 'foreign-run': gh.reads['actions/runs/9000100']['head_sha'] = 'f'*40
                else:
                    runs = gh.reads['actions/workflows/900/runs?head_sha='+'3'*40+'&per_page=100&page=1']
                    runs['workflow_runs'].append(dict(runs['workflow_runs'][0], id=9000102))
                    runs['total_count'] += 1
                report, state = self.reconcile(source=gh)
                self.assertFalse(report['complete'], report)
                self.assertEqual(state['covered'], '1'*40)
        gh = RecordingGitHub(self.reads)
        def change_between_reads(path):
            if path == 'actions/runs/9000100' and gh.calls.count(path) == 2:
                gh.reads[path]['run_attempt'] = 2
        gh.on_read = change_between_reads
        report, state = self.reconcile(source=gh)
        self.assertFalse(report['complete'], report)
        self.assertEqual(state['covered'], '1'*40)

    def test_measurement_keeps_unknown_push_and_cost_honest(self):
        report, _ = self.reconcile()
        self.assertEqual(report['measurement']['batch']['members'], ['2'*40, '3'*40])
        self.assertIsNone(report['measurement']['push_to_required_seconds'])
        self.assertIsNone(report['measurement']['whole_bill_usd'])
        self.assertEqual(report['measurement']['job_queue_seconds']['median'], 30)
        self.assertEqual(report['measurement']['required_result_at'], '2030-01-01T00:05:00Z')

    def test_skipped_placeholder_clocks_are_not_queue_waits(self):
        # Bug: a skipped job row's placeholder clocks (created == started) were
        # counted as zero-second waits, lowering the median and p90.
        page = self.reads['actions/runs/9000100/attempts/1/jobs?per_page=100&page=1']
        for number, name in enumerate(('rust-export', 'web-export', 'toolkit-nightly'), 9000300):
            page['jobs'].append(dict(id=number, run_id=9000100, run_attempt=1, head_sha='3'*40, name=name,
                status='completed', conclusion='skipped', created_at='2030-01-01T00:00:00Z',
                started_at='2030-01-01T00:00:00Z', completed_at='2030-01-01T00:00:00Z'))
        page['total_count'] += 3
        report, _ = self.reconcile()
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['measurement']['job_queue_seconds'], {'n': 13, 'median': 30, 'p90': 30})

    def test_absent_legacy_protection_reads_as_empty_set(self):
        # Bug: GitHub's 404 "Branch not protected" for a ruleset-only main was an
        # unreadable protection, so reconcile always refused. Only that exact
        # answer means "no legacy checks"; every other failure still refuses.
        legacy = 'branches/main/protection/required_status_checks'
        rules = 'rules/branches/main?per_page=100&page=1'
        ruleset = [dict(type='required_status_checks', parameters=dict(required_status_checks=[
            dict(context='ci', integration_id=9000600), dict(context='privacy', integration_id=9000600)]))]
        absent = b'{"message":"Branch not protected","documentation_url":"https://docs.github.com/rest","status":"404"}'
        def transport(answers):
            def run(args, **_):
                path = args[-1].removeprefix('repos/synthetic/ci-example').removeprefix('/')
                if path in answers:
                    return SimpleNamespace(returncode=answers[path][0], stdout=answers[path][1])
                return SimpleNamespace(returncode=0, stdout=json.dumps(self.reads[path]).encode())
            return run
        def github(answers):
            gh = self.shadow.GitHub('synthetic/ci-example')
            gh.packet = lambda rid, attempt, head: copy.deepcopy(self.reads['_packet'])
            return gh, patch.object(self.shadow.subprocess, 'run', side_effect=transport(answers))
        self.reads[rules] = ruleset
        gh, transport_patch = github({legacy: (1, absent)})
        with transport_patch:
            report, state = self.reconcile(source=gh)
        self.assertTrue(report['complete'], report)
        self.assertEqual(state['covered'], '3'*40)
        refusals = {
            'other 404': (1, b'{"message":"Not Found","status":"404"}'),
            'forbidden': (1, b'{"message":"Branch not protected","status":"403"}'),
            'unreadable body': (1, b'Branch not protected'),
            'failed empty body': (1, b''),
        }
        for kind, answer in refusals.items():
            with self.subTest(kind=kind):
                gh, transport_patch = github({legacy: answer})
                with transport_patch:
                    report, state = self.reconcile(source=gh)
                self.assertFalse(report['complete'], report)
                self.assertEqual(state['covered'], '1'*40)
        with self.subTest(kind='absent legacy and no ruleset ci'):
            self.reads[rules] = []
            gh, transport_patch = github({legacy: (1, absent)})
            with transport_patch:
                report, state = self.reconcile(source=gh)
            self.assertFalse(report['complete'], report)
            self.assertEqual(state['covered'], '1'*40)

    def test_later_separate_required_workflow_sets_required_end(self):
        self.reads['actions/runs/9000101/attempts/1/jobs?per_page=100&page=1']['jobs'][0]['completed_at'] = '2030-01-01T00:08:00Z'
        report, _ = self.reconcile()
        self.assertTrue(report['complete'], report)
        self.assertEqual(report['measurement']['required_result_at'], '2030-01-01T00:08:00Z')

    def test_changed_protection_and_inconsistent_latest_attempt_refuse(self):
        gh = RecordingGitHub(self.reads)
        path = 'branches/main/protection/required_status_checks'
        def change_protection(read):
            if read == path and gh.calls.count(path) == 2:
                for check in gh.reads[path]['checks']:
                    check['app_id'] = None
        gh.on_read = change_protection
        report, state = self.reconcile(source=gh)
        self.assertFalse(report['complete'], report)
        self.assertEqual(state['covered'], '1'*40)
        gh = RecordingGitHub(self.reads)
        gh.reads['actions/workflows/900/runs?head_sha='+'3'*40+'&per_page=100&page=1']['workflow_runs'][0]['run_attempt'] = 2
        report, _ = self.reconcile(source=gh)
        self.assertFalse(report['complete'], report)

    def test_transport_is_explicit_host_get_and_empty_ids_never_reach_api(self):
        gh = self.shadow.GitHub('synthetic/ci-example')
        with patch.object(self.shadow.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=b'{}')) as command:
            gh.get('actions/runs/9000100')
            args = command.call_args.args[0]
            self.assertEqual(args[:6], ['gh','api','--hostname','github.com','--method','GET'])
            for missing in (None, '', 0, True):
                with self.subTest(id=missing), self.assertRaises(ValueError):
                    gh.packet(missing, 1, '3'*40)
            self.assertEqual(command.call_count, 1)

    def test_artifact_zip_is_bounded_exact_and_authenticated(self):
        import io
        import zipfile
        for kind in ('valid', 'expired', 'duplicate', 'foreign', 'extra-file', 'truncated'):
            with self.subTest(kind=kind):
                gh = self.shadow.GitHub('synthetic/ci-example')
                artifact = dict(id=9000500,name='main-shadow-1',expired=kind=='expired',size_in_bytes=123,
                                workflow_run=dict(id=9000100,head_sha='f'*40 if kind=='foreign' else '3'*40))
                listing = dict(total_count=2 if kind=='duplicate' else 1,
                               artifacts=[artifact,artifact] if kind=='duplicate' else [artifact])
                stream = io.BytesIO()
                with zipfile.ZipFile(stream,'w') as archive:
                    archive.writestr('observation.json',json.dumps(self.packet))
                    if kind=='extra-file': archive.writestr('../untrusted.json','{}')
                raw = b'bad zip' if kind=='truncated' else stream.getvalue()
                def transport(path):
                    if path=='actions/runs/9000100/artifacts?per_page=100&page=1':
                        return json.dumps(listing).encode()
                    self.assertEqual(path,'actions/artifacts/9000500/zip')
                    return raw
                gh.raw = transport
                if kind=='valid': self.assertEqual(gh.packet(9000100,1,'3'*40),self.packet)
                else:
                    with self.assertRaises((ValueError,zipfile.BadZipFile)):
                        gh.packet(9000100,1,'3'*40)

    def test_durable_result_write_is_private_and_failed_replace_keeps_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            self.shadow.atomic(path,self.state)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            report, after = self.reconcile(state=self.shadow.load(path))
            self.assertTrue(report['complete'],report)
            with patch.object(self.shadow.os,'replace',side_effect=OSError('synthetic failure')):
                with self.assertRaises(OSError): self.shadow.atomic(path,after)
            self.assertEqual(self.shadow.load(path),self.state)
            self.assertEqual([p.name for p in Path(directory).iterdir()],['state.json'])
            self.shadow.atomic(path,after)
            self.assertEqual(self.shadow.load(path),after)

    def test_capture_never_claims_terminal_coverage_and_preserves_exact_bytes(self):
        original = copy.deepcopy(self.document)
        for newline in ('\n', '\r\n'):
            self.document = copy.deepcopy(original)
            self.document['plan'] = original['plan'].replace('\n', newline)
            digest = hashlib.sha256(self.document['plan'].encode()).hexdigest()
            for receipt in self.document['receipts']:
                receipt['plan_sha256'] = digest
            with tempfile.TemporaryDirectory() as directory:
                folder = Path(directory); receipts = folder/'receipts'; receipts.mkdir()
                (folder/'ci-selection.json').write_text(self.document['plan'])
                plan = json.loads(self.document['plan'])
                dispatch = dict.fromkeys(('build-web','lint-rust','export-rust','export-web',
                    'build-site','image-skills','rust','web','site','release','toolkit'), True)
                dispatch.update(**{'export-rust':False,'export-web':False},
                    skills=['launch-fleet','plan-graph','triage'],trace=False,planted=False,
                    plan_sha256=hashlib.sha256(self.document['plan'].encode()).hexdigest())
                (folder/'ci-dispatch.json').write_text(json.dumps(dispatch))
                for i, receipt in enumerate(self.document['receipts']):
                    (receipts/f'{i}.json').write_text(json.dumps(receipt))
                (folder/'rust-ran').mkdir()
                for share in self.packet['rust']['shares']:
                    (folder/'rust-ran'/f'ran-{share["shard"]}.txt').write_text('\n'.join(share['tests'])+'\n')
                needs = {k:{'result':'success'} for k in ('changes','always','web-build','rust','web','site','release','skills')}
                needs.update({k:{'result':'skipped'} for k in ('rust-export','web-export')})
                (folder/'needs.json').write_text(json.dumps(needs))
                (folder/'event.json').write_text(json.dumps({'before':'2'*40,'after':'3'*40,
                    'ref':'refs/heads/main','repository':{'full_name':'synthetic/ci-example'}}))
                env = dict(os.environ,GITHUB_RUN_ID='9000100',GITHUB_RUN_ATTEMPT='1',GITHUB_EVENT_NAME='push',
                    GITHUB_REF_NAME='main',GITHUB_SHA='3'*40,GITHUB_REPOSITORY='synthetic/ci-example',
                    GITHUB_EVENT_PATH=str(folder/'event.json'))
                args = [sys.executable,'-I',str(HERE/'shadow.py'),'capture',str(folder),
                    str(folder/'needs.json'),str(receipts),str(folder/'packet.json')]
                result = subprocess.run(args,env=env,capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
                packet = json.loads((folder/'packet.json').read_text())
                self.assertFalse(packet['complete'])
                self.assertEqual(packet['plan'],self.document['plan'])
                self.assertCountEqual(packet['receipts'],self.document['receipts'])
                env['GITHUB_SHA'] = 'f'*40
                result = subprocess.run(args,env=env,capture_output=True,text=True,timeout=10)
                self.assertNotEqual(result.returncode,0)

    def test_workflow_only_appends_capture_after_finish_for_main(self):
        self.assert_current_shadow_workflow((ROOT/'.github/workflows/ci.yml').read_text())

    def test_historical_c7_append_only_evidence(self):
        self.assert_historical_c7_evidence((HERE/'fixtures/shadow/ci-before.sha256').read_text())

    def assert_historical_c7_evidence(self, evidence):
        baseline, record = evidence.split('\n', 1)
        # This original digest is never refreshed for later workflow edits.
        self.assertEqual(baseline, '56820befdd6f70436c178cd4d1db6c93cac992df3b851cfef86607ee6b35118c')
        record = json.loads(record)
        self.assertEqual(set(record), {'source_before', 'source_after', 'historical_after'})
        self.assertEqual(record['source_before'], 'dcd532b2d7578d74702a56839dbe84f466bd46b2')
        self.assertEqual(record['source_after'], 'cf44ac9cccfd0bcaca778f48b07615c9f794606f')
        historical = record['historical_after']
        start = historical.index('      # C7 shadow evidence:')
        end = historical.index('\n  # Transition bridge:', start)
        self.assertEqual(hashlib.sha256((historical[:start]+historical[end:]).encode()).hexdigest(),
                         baseline, 'historical append-only evidence')
        self.assertEqual(hashlib.sha256(historical.encode()).hexdigest(),
                         'efda9f31e479cc1f19d52529beb0908ec872ba13d46f81c9ea662064af078561', 'historical source-after binding')

    def test_historical_c7_evidence_refuses_changed_outside_bytes(self):
        evidence = (HERE/'fixtures/shadow/ci-before.sha256').read_text()
        baseline, record = evidence.split('\n', 1)
        record = json.loads(record)
        record['historical_after'] = record['historical_after'].replace('name: CI\n', 'name: altered\n')
        with self.assertRaisesRegex(AssertionError, 'historical append-only evidence'):
            self.assert_historical_c7_evidence(baseline+'\n'+json.dumps(record))

    def assert_current_shadow_workflow(self, workflow):
        import re
        start = workflow.index('      # C7 shadow evidence:')
        end = workflow.index('\n  # Transition bridge:', start)
        block = workflow[start:end]
        ci = workflow[workflow.index('\n  ci:\n'):start]
        self.assertIn('    if: ${{ always() }}\n', ci, 'required result always runs')
        self.assertIn('    needs: [changes, always, web-build, rust, rust-export, web, web-export, site, release, skills]\n',
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
        self.assertIn("  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n",
                      workflow, 'admission running push/nightly retained')

    def test_approved_runner_representation_preserves_shadow_contract(self):
        workflow = (ROOT/'.github/workflows/ci.yml').read_text()
        # A hosted literal is independently permitted by F2. Runner selection
        # is outside the C7 append-only claim; operative shadow guards remain.
        lines = ['    runs-on: ubuntu-24.04' if line.startswith('    runs-on: ')
                 else line for line in workflow.splitlines()]
        self.assert_current_shadow_workflow('\n'.join(lines)+'\n')

    def test_current_shadow_boundaries_refuse_mutations(self):
        workflow = (ROOT/'.github/workflows/ci.yml').read_text()
        start = workflow.index('      # C7 shadow evidence:')
        end = workflow.index('\n  # Transition bridge:', start)
        block = workflow[start:end]
        prefix, suffix = workflow[:start], workflow[end:]
        mutations = [
            ('early capture', prefix.replace('      - name: Every planned lane passed',
                block+'      - name: Every planned lane passed')+suffix, 'required result'),
            ('failed finish', prefix+block.replace('success() && ', '')+suffix, 'eligibility'),
            ('scheduled capture', prefix+block.replace("github.event_name == 'push'",
                "github.event_name == 'schedule'")+suffix, 'eligibility'),
            ('foreign group', prefix+block.replace("github.event.merge_group.base_ref == 'refs/heads/main'",
                "github.event.merge_group.base_ref != 'refs/heads/main'")+suffix, 'eligibility'),
            ('failed capture upload', prefix+block.replace("steps.main_shadow.outcome == 'success' && ", '')+suffix, 'eligibility'),
            ('required-result impact', prefix+block.replace('continue-on-error: true',
                'continue-on-error: false')+suffix, 'required result'),
            ('swallowed required failure', workflow.replace(
                '          python3 -I .github/actions/docs-only/run.py finish ',
                '          set +e\n          python3 -I .github/actions/docs-only/run.py finish '
            ).replace('"$RUNNER_TEMP/receipts"\n      # C7',
                '"$RUNNER_TEMP/receipts"\n          exit 0\n      # C7'), 'required result'),
            ('replaced result environment', workflow.replace(
                '          NEEDS: ${{ toJSON(needs) }}', "          NEEDS: '{}'"), 'required result'),
            ('missing result input write', workflow.replace(
                '          printf \'%s\' "$NEEDS" > "$RUNNER_TEMP/needs.json"\n', ''), 'required result'),
            ('alternate required shell', workflow.replace('      - name: Every planned lane passed\n',
                '      - name: Every planned lane passed\n        shell: bash {0}\n'), 'required result'),
            ('required finish bypass', workflow.replace('"$RUNNER_TEMP/receipts"\n      # C7',
                '"$RUNNER_TEMP/receipts" || true\n      # C7'), 'required result'),
            ('main push removed', workflow.replace('  push:\n    branches: [main]',
                '  push:\n    branches: [other]'), 'admission'),
            ('nightly removed', workflow.replace("- cron: '23 9 * * *'",
                "- cron: '23 9 * * 1'"), 'admission'),
            ('PR removed', workflow.replace('  pull_request:', '  workflow_dispatch:'), 'admission'),
            ('push cancellation', workflow.replace("cancel-in-progress: ${{ github.event_name == 'pull_request' }}",
                'cancel-in-progress: ${{ true }}'), 'admission'),
        ]
        for name, mutant, reason in mutations:
            with self.subTest(case=name):
                self.assertNotEqual(mutant, workflow)
                with self.assertRaisesRegex(AssertionError, reason):
                    self.assert_current_shadow_workflow(mutant)

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


def load_tests(loader, tests, pattern):
    spec = importlib.util.spec_from_file_location('batch_kit', ROOT/'tools/ci2-live/test_batch_kit.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    tests.addTests(loader.loadTestsFromModule(module))
    return tests


if __name__ == '__main__':
    unittest.main()
