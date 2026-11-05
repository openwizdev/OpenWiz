#!/usr/bin/env python3
"""CP1 at its offline verifier/recording boundary, with independent literals.

The missing gate could accept an old positive check after a pinned fact changed.
Existing installed-engine tests exercise a permanent refusal and cannot cover a
positive verifier. These cases own CP1's positive, mutation and privacy claims.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def fixture():
    plan_text = ('plan-graph revision v2\n'
        'spec #900 body sha256 ' + 'a' * 64 + '\n'
        'ticket #901 blocked-by none body sha256 ' + 'b' * 64 + ' title Synthetic builder\n'
        'ticket #902 blocked-by #901 body sha256 ' + 'c' * 64 + ' title Synthetic live check\n')
    candidate = {'version':'0.0.99', 'head':'1' * 40, 'tree':'2' * 40, 'build_sha256':'3' * 64}
    plan = {'revision':4, 'fingerprint':sha(plan_text), 'revision_text':plan_text,
            'approval':{'comment_id':400, 'body_sha256':'4' * 64}}
    follow = {'ticket':903, 'classification':'polish', 'labels':['polish'],
              'state':'closed', 'subissue':False, 'archived':True}
    live = {'schema':'openwiz.completion-live.v1', 'repository':'example/synthetic',
        'spec':900, 'candidate':candidate, 'ticket':902, 'evidence_class':'live_observation',
        'result':'passed', 'checks':[{'claim':'native', 'result':'passed'},
                                   {'claim':'timed-fleet', 'result':'passed'}], 'gaps':[]}
    live_body = json.dumps(live)
    checkpoint = {'schema':'openwiz.completion-checkpoint.v1',
        'repository':'example/synthetic', 'spec':900, 'plan':plan,
        'candidate':candidate,
        'live':[{'ticket':902, 'comment_id':500, 'body_sha256':sha(live_body)}],
        'follow_ups':[follow]}
    body = json.dumps(checkpoint)
    pin = {'repository':'example/synthetic', 'spec':900,
        'checkpoint':{'comment_id':600, 'body_sha256':sha(body)},
        'orchestrator':'synthetic-owner', 'candidate':candidate,
        'required_live':[{'ticket':902, 'claims':['native','timed-fleet']}]}
    def comment(number, text, role, subject):
        return {'id':number, 'repository':'example/synthetic', 'subject':subject,
                'author':'synthetic-owner', 'writer_role':role, 'body':text}
    observation = {'schema':'openwiz.completion-read.v1',
        'repository':{'name':'example/synthetic', 'private':True}, 'spec':900,
        'plan':plan, 'candidate':candidate, 'required_live':pin['required_live'],
        'comments':{'total':1, 'pages':[{'cursor':None, 'next_cursor':None,
                    'items':[comment(600, body, 'orchestrator', 900)]}]},
        'live':{'total':1, 'pages':[{'cursor':None, 'next_cursor':None,
                    'items':[comment(500, live_body, 'live_runner', 902)]}]},
        'planned':[{'ticket':901, 'kind':'builder', 'state':'closed',
                    'verified_merge':True, 'human_complete':False, 'archived':True},
                   {'ticket':902, 'kind':'human', 'state':'closed',
                    'verified_merge':False, 'human_complete':True, 'archived':True}],
        'follow_ups':{'total':1, 'pages':[{'cursor':None, 'next_cursor':None, 'items':[follow]}]},
        'summary_recorded':True}
    return {'pin':pin, 'reads':[observation], 'effects':['spec_summary','all_closed']}


class Checkpoint(unittest.TestCase):
    def run_recording(self, recording, expected=0):
        with tempfile.TemporaryDirectory(prefix='synthetic-cp1-') as folder:
            path = Path(folder) / 'recording.json'
            text = recording if isinstance(recording, str) else json.dumps(recording)
            path.write_text(text)
            before = path.read_bytes()
            process = subprocess.run([sys.executable, '-I', str(HERE/'checkpoint.py'),
                '--recording', str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(process.returncode, expected, process.stdout + process.stderr)
            self.assertEqual(process.stderr, '')
            self.assertEqual(path.read_bytes(), before)
            return json.loads(process.stdout)

    def held(self, recording, reason):
        result = self.run_recording(recording, 5)
        self.assertEqual(result, {'schema':'openwiz.completion-recording.v1',
            'recording_only':True, 'reason':reason, 'effects':[]})

    def test_matching_checkpoint_records_exactly_two_effects_after_fresh_reads(self):
        result = self.run_recording(fixture())
        self.assertEqual(result, {'schema':'openwiz.completion-recording.v1',
            'recording_only':True, 'reason':'CP1_verified',
            'effects':['spec_summary','all_closed']})

    def test_revision_title_separators_preserve_both_completion_effects(self):
        # Unchanged revision.sh output over synthetic gh responses. Unicode
        # title separators are content; only literal LF separates records.
        # Plain-title fixtures miss splitlines() treating these as boundaries.
        recording = fixture()
        plan = recording['reads'][0]['plan']
        plan['revision_text'] = (HERE/'unicode-title.revision.txt').read_text(encoding='utf-8')
        plan['fingerprint'] = sha(plan['revision_text'])
        self.repin(recording, checkpoint_change=lambda value: value.update(plan=plan))
        self.assertEqual(self.run_recording(recording),
            {'schema':'openwiz.completion-recording.v1', 'recording_only':True,
             'reason':'CP1_verified', 'effects':['spec_summary','all_closed']})

    def test_revision_records_require_literal_lf_termination(self):
        text = fixture()['reads'][0]['plan']['revision_text']
        for malformed in (text[:-1], text + 'ticket #903', text + '\n'):
            with self.subTest(revision=malformed):
                recording = fixture()
                plan = recording['reads'][0]['plan']
                plan.update(revision_text=malformed, fingerprint=sha(malformed))
                self.repin(recording, checkpoint_change=lambda value: value.update(plan=plan))
                self.held(recording, 'CP1_plan')

    def test_every_pinned_input_is_rechecked_at_each_effect(self):
        # Each pair supplies a valid first read and a changed final read.
        changes = [
            ('comment edit', lambda r: r['comments']['pages'][0]['items'][0].update(body='edited'), 'CP1_checkpoint'),
            ('wrong author', lambda r: r['comments']['pages'][0]['items'][0].update(author='engine'), 'CP1_checkpoint'),
            ('self attestation', lambda r: r['comments']['pages'][0]['items'][0].update(writer_role='engine'), 'CP1_checkpoint'),
            ('repository', lambda r: r['repository'].update(name='example/other'), 'CP1_identity'),
            ('public repository', lambda r: r['repository'].update(private=False), 'CP1_identity'),
            ('spec', lambda r: r.update(spec=999), 'CP1_identity'),
            ('plan', lambda r: r['plan'].update(revision=5), 'CP1_plan'),
            ('plan bytes', lambda r: r['plan'].update(revision_text=r['plan']['revision_text']+'\n'), 'CP1_plan'),
            ('approval', lambda r: r['plan']['approval'].update(comment_id=401), 'CP1_plan'),
            ('version', lambda r: r['candidate'].update(version='0.0.98'), 'CP1_build'),
            ('candidate', lambda r: r['candidate'].update(head='9'*40), 'CP1_build'),
            ('build', lambda r: r['candidate'].update(build_sha256='9'*64), 'CP1_build'),
            ('tree', lambda r: r['candidate'].update(tree='9'*40), 'CP1_build'),
            ('label', lambda r: r['follow_ups']['pages'][0]['items'][0].update(labels=[]), 'CP1_follow_ups'),
            ('class', lambda r: r['follow_ups']['pages'][0]['items'][0].update(classification='unknown'), 'CP1_follow_ups'),
            ('membership', lambda r: r['follow_ups'].update(total=0,pages=[{'cursor':None,'next_cursor':None,'items':[]}]), 'CP1_follow_ups'),
            ('live edit', lambda r: r['live']['pages'][0]['items'][0].update(body='transport accepted'), 'CP1_live'),
            ('live subject', lambda r: r['live']['pages'][0]['items'][0].update(subject=999), 'CP1_live'),
            ('live self attestation', lambda r: r['live']['pages'][0]['items'][0].update(writer_role='engine'), 'CP1_live'),
            ('live missing', lambda r: r['live'].update(total=0,pages=[{'cursor':None,'next_cursor':None,'items':[]}]), 'CP1_live'),
            ('builder merge', lambda r: r['planned'][0].update(verified_merge=False), 'CP1_planned_work'),
            ('human work', lambda r: r['planned'][1].update(human_complete=False), 'CP1_planned_work'),
        ]
        for name, change, reason in changes:
            for effect in ('spec_summary','all_closed'):
                with self.subTest(name=name,effect=effect):
                    recording = fixture()
                    after = copy.deepcopy(recording['reads'][0])
                    change(after)
                    recording['reads'].append(after)
                    recording['effects'] = [effect]
                    self.held(recording,reason)

    def test_failed_unknown_fixture_or_incomplete_live_result_never_accepts(self):
        for mutation in ({'result':'failed'}, {'result':'unknown'},
                         {'evidence_class':'fixture_test'}, {'gaps':['synthetic native gap']},
                         {'checks':[{'claim':'native','result':'passed'}]},
                         {'checks':[{'claim':'native','result':'passed'},
                                    {'claim':'timed-fleet','result':'failed'}]},
                         {'candidate':{'version':'0.0.99','head':'9'*40,'tree':'2'*40,'build_sha256':'3'*64}}):
            with self.subTest(mutation=mutation):
                recording = fixture()
                read = recording['reads'][0]
                live = read['live']['pages'][0]['items'][0]
                value = json.loads(live['body'])
                value.update(mutation)
                live['body'] = json.dumps(value)
                # Even an orchestrator-pinned failure/fixture is insufficient.
                self.repin(recording, live_hash=sha(live['body']))
                self.held(recording,'CP1_live')

    @staticmethod
    def repin(recording, live_hash=None, checkpoint_change=None):
        comment = recording['reads'][0]['comments']['pages'][0]['items'][0]
        value = json.loads(comment['body'])
        if live_hash:
            value['live'][0]['body_sha256'] = live_hash
        if checkpoint_change:
            checkpoint_change(value)
        comment['body'] = json.dumps(value)
        recording['pin']['checkpoint']['body_sha256'] = sha(comment['body'])

    def test_pagination_duplicates_conflicts_and_unreadable_sources_hold(self):
        for feed, reason in [('comments','CP1_checkpoint'),('live','CP1_live'),('follow_ups','CP1_follow_ups')]:
            for case in ('partial','wrong total','duplicate','bad cursor','unreadable'):
                with self.subTest(feed=feed,case=case):
                    recording = fixture()
                    data = recording['reads'][0][feed]
                    if case == 'partial':
                        data['pages'][0]['next_cursor'] = 'unread-next'
                    elif case == 'wrong total':
                        data['total'] = 2
                    elif case == 'duplicate':
                        data['pages'][0]['items'] *= 2
                        data['total'] = 2
                    elif case == 'bad cursor':
                        data['pages'][0]['cursor'] = 'wrong-first'
                    else:
                        recording['reads'][0][feed] = None
                    self.held(recording,reason)
        recording = fixture()
        comments = recording['reads'][0]['comments']
        other = copy.deepcopy(comments['pages'][0]['items'][0])
        other['id'] = 601
        comments['pages'][0]['items'].append(other)
        comments['total'] = 2
        self.held(recording,'CP1_checkpoint')
        recording = fixture()
        recording['reads'] = [None]
        self.held(recording,'CP1_unreadable')

    def test_strict_wire_shapes_and_fixed_private_output(self):
        for payload in ('[]','{"pin":{},"pin":{}}','{"secret":"planted-secret"}',
                        '{"schema":"openwiz.completion-checkpoint.v1", "bad":NaN}'):
            with self.subTest(payload=payload):
                self.held(payload,'CP1_malformed')
        for value in (True, 900.0, '900', {'900':None}):
            recording = fixture()
            recording['pin']['spec'] = value
            self.held(recording,'CP1_malformed')
        recording = fixture()
        comment = recording['reads'][0]['comments']['pages'][0]['items'][0]
        comment['body'] = comment['body'][:-1] + ',"spec":900}'
        recording['pin']['checkpoint']['body_sha256'] = sha(comment['body'])
        self.held(recording,'CP1_checkpoint')
        recording = fixture()
        recording['reads'][0]['comments']['pages'][0]['items'][0]['body'] = 'planted-secret'
        self.held(recording,'CP1_checkpoint')

    def test_closed_issue_and_empty_live_list_do_not_replace_required_evidence(self):
        recording = fixture()
        self.repin(recording, checkpoint_change=lambda value: value.update(live=[]))
        self.held(recording,'CP1_live')

    def test_shipped_close_conditions_stay_additional_to_checkpoint(self):
        for change in (lambda r: r.update(summary_recorded=False),
                       lambda r: r['planned'][0].update(archived=False),
                       lambda r: r['follow_ups']['pages'][0]['items'][0].update(subissue=True,archived=False)):
            recording = fixture()
            change(recording['reads'][0])
            current = recording['reads'][0]['follow_ups']['pages'][0]['items']
            self.repin(recording, checkpoint_change=lambda c: c.update(follow_ups=current))
            recording['effects'] = ['all_closed']
            self.held(recording,'CP1_tick_conditions')
        recording = fixture()
        recording['reads'][0]['follow_ups']['pages'][0]['items'][0]['state'] = 'open'
        self.repin(recording, checkpoint_change=lambda c: c['follow_ups'][0].update(state='open'))
        recording['effects'] = ['spec_summary']
        self.run_recording(recording)
        recording['effects'] = ['all_closed']
        self.held(recording,'CP1_tick_conditions')

    def test_subissue_archive_evidence_is_required_before_close(self):
        recording = fixture()
        follow = recording['reads'][0]['follow_ups']['pages'][0]['items'][0]
        follow['subissue'] = True
        follow.pop('archived', None)
        def change(value):
            value['follow_ups'][0]['subissue'] = True
            value['follow_ups'][0].pop('archived', None)
        self.repin(recording, checkpoint_change=change)
        recording['effects'] = ['all_closed']
        self.held(recording, 'CP1_checkpoint')

    def test_missing_bundled_contract_has_fixed_private_refusal(self):
        with tempfile.TemporaryDirectory(prefix='synthetic-cp1-contract-') as folder:
            root = Path(folder)
            program = root/'checkpoint.py'
            program.write_bytes((HERE/'checkpoint.py').read_bytes())
            source = root/'recording.json'
            source.write_text(json.dumps(fixture()))
            process = subprocess.run([sys.executable,'-I',str(program),'--recording',str(source)],
                capture_output=True,text=True,timeout=10)
            self.assertEqual(process.returncode,5,process.stdout+process.stderr)
            self.assertEqual(process.stderr,'')
            self.assertEqual(json.loads(process.stdout),
                {'schema':'openwiz.completion-recording.v1','recording_only':True,
                 'reason':'CP1_unreadable','effects':[]})

    def test_empty_recording_never_claims_checkpoint_verification(self):
        spec = importlib.util.spec_from_file_location('synthetic_checkpoint',HERE/'checkpoint.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        result = verifier.record_completion(None,None,[])
        self.assertEqual(result['reason'],'CP1_effect_scope')
        self.assertEqual(result['effects'],[])

    def test_complete_pagination_accepts_unrelated_comments(self):
        recording = fixture()
        feed = recording['reads'][0]['comments']
        unrelated = copy.deepcopy(feed['pages'][0]['items'][0])
        unrelated.update(id=599, body='Synthetic unrelated comment.')
        page = feed['pages'][0]
        page['cursor'] = 'page-two'
        feed.update(total=2, pages=[{'cursor':None,'next_cursor':'page-two','items':[unrelated]},page])
        self.run_recording(recording)

    def test_fresh_reader_challenge_refuses_cached_or_failed_reads(self):
        spec = importlib.util.spec_from_file_location('synthetic_checkpoint',HERE/'checkpoint.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        recording = fixture()
        cached = None
        def reader(nonce):
            nonlocal cached
            if cached is None:
                cached = json.dumps({**recording['reads'][0], 'nonce':nonce})
            return cached
        self.assertEqual(verifier.verify_completion(reader,recording['pin'],'spec_summary'),
                         'CP1_unreadable')
        def failed(nonce):
            raise OSError('planted-secret')
        self.assertEqual(verifier.verify_completion(failed,recording['pin'],'all_closed'),
                         'CP1_unreadable')

    def test_a_recorded_summary_cannot_authorize_a_later_stale_close(self):
        recording = fixture()
        before = recording['reads'][0]
        after = copy.deepcopy(before)
        after['comments']['pages'][0]['items'][0]['body'] = 'edited after summary'
        recording['reads'] = [before,before,after]
        result = self.run_recording(recording,5)
        self.assertEqual(result['reason'],'CP1_checkpoint')
        self.assertEqual(result['effects'],['spec_summary'])

    def test_private_visibility_requires_a_json_boolean(self):
        # A numeric truth value can compare equal to True in Python while
        # leaving repository privacy unverified under the wire contract.
        for value in (1, 1.0):
            for effect in ('spec_summary', 'all_closed'):
                with self.subTest(value=value, effect=effect):
                    recording = fixture()
                    recording['reads'][0]['repository']['private'] = value
                    recording['effects'] = [effect]
                    self.held(recording, 'CP1_unreadable')

    def test_schema_patterns_and_runtime_reject_the_same_malformed_identities(self):
        # JSON Schema's pattern uses search semantics. Published patterns must
        # reject extra prefix/suffix bytes, including a terminal newline.
        spec = importlib.util.spec_from_file_location('synthetic_checkpoint', HERE/'checkpoint.py')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        cases = [
            ('reference', 'body_sha256', '3'*64, True),
            ('reference', 'body_sha256', '3'*65, False),
            ('reference', 'body_sha256', '3'*64+'\n', False),
            ('candidate', 'head', '1'*40, True),
            ('candidate', 'head', 'x'+'1'*40, False),
            ('candidate', 'head', '1'*40+'x', False),
            ('candidate', 'version', '0.0.99', True),
            ('candidate', 'version', 'junk0.0.99junk', False),
            ('candidate', 'version', '0.0.99'+'\n', False),
            ('checkpoint', 'repository', 'example/synthetic', True),
            ('checkpoint', 'repository', '!example/synthetic', False),
            ('checkpoint', 'repository', 'example/synthetic?', False),
            ('checkpoint', 'repository', 'example/synthetic'+'\n', False),
            ('pin', 'orchestrator', 'synthetic-owner', True),
            ('pin', 'orchestrator', '!synthetic-owner', False),
            ('pin', 'orchestrator', 'synthetic-owner'+'\n', False),
        ]
        for definition, field, value, expected in cases:
            with self.subTest(definition=definition, field=field, value=value):
                rule = verifier.SCHEMA['$defs'][definition]['properties'][field]
                self.assertEqual(re.search(rule['pattern'], value) is not None, expected)
                self.assertEqual(verifier.validate(value, rule), expected)

    def test_unrelated_approved_work_has_no_checkpoint_dependency(self):
        recording = {'pin':None, 'reads':[], 'effects':['frontier']}
        self.held(recording,'CP1_effect_scope')


if __name__ == '__main__':
    unittest.main()
