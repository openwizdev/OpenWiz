#!/usr/bin/env python3
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import importlib.util
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
_spec = importlib.util.spec_from_file_location('kit', os.path.join(KIT, 'kit.py'))
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)

START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude', 'model': 'default'}
RUNS = '/api/v1/agent/runs'
REFUSAL = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
           "at the host's default")
UNCERTAIN_CREATE = ('look in Warp for a new run on this ticket and cancel it there (or keep it and track it by hand), '
                    'then start again: retrying now can start a second run')
LOGINS = {'OPENWIZ_WARP_CLAUDE_LOGIN': 'SYN_CLAUDE_LOGIN', 'OPENWIZ_WARP_CODEX_LOGIN': 'SYN_CODEX_LOGIN'}


class Driver(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.tracker, self.log = os.path.join(self.folder, 'tracker.json'), os.path.join(self.folder, 'warp.log')
        self.faults = os.path.join(self.folder, 'faults.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.fault({})
        open(self.log, 'w').close()
        self.key = 'syn-test-key-' + secrets.token_hex(12)
        self.warp = subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'fixtures', 'fake-warp-oz'),
                                      self.tracker, self.log, self.faults], stdout=subprocess.PIPE, text=True,
                                     env=dict(os.environ, FAKE_WARP_OZ_KEY=self.key))
        self.addCleanup(self.warp.stdout.close)
        self.addCleanup(self.warp.wait)
        self.addCleanup(self.warp.kill)
        self.env = dict(os.environ, KIT_TRACKER=self.tracker, OPENWIZ_WARP_OZ_STATE=os.path.join(self.folder, 'state'),
                        OPENWIZ_HOSTKEY_TEST_ORIGIN=self.warp.stdout.readline().strip(), **LOGINS)
        self.env.pop('OPENWIZ_WARP_ENVIRONMENT', None)

    def fault(self, faults):
        with open(self.faults, 'w') as f:
            json.dump(faults, f)

    def calls(self):
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def call(self, cmd, request, **env):
        p = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request), capture_output=True, text=True,
                           env=dict(self.env, **env), timeout=60)
        out = json.loads(p.stdout)
        schema = kit.load_schema()
        self.assertIsNone(kit.invalid(out, schema['commands'][cmd]['output'] if p.returncode == 0 else schema['error']))
        self.assertNotIn(self.key, p.stdout + p.stderr)
        return p.returncode, out

    def test_kit_passes_all_five_with_its_key_check(self):
        p = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER, '--repo',
                            'example/site', '--ticket', '7', '--harness', 'claude', '--model', 'default',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: refused for claude with the refusal text, '
            'as the README says',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the warp-oz key '
            'reached its host only from the key helper, in its header']), p.stderr)

    def test_version_lists_effort_and_schema_is_the_kits_own(self):
        p = subprocess.run([sys.executable, DRIVER, 'version'], capture_output=True, text=True, env=self.env)
        self.assertEqual((p.returncode, json.loads(p.stdout)),
                         (0, {'driver': 'warp-oz', 'records': ['openwiz:records v1'],
                              'can': ['start', 'wake', 'stop', 'effort']}))
        with open(os.path.join(HERE, 'schema.json'), 'rb') as a, open(os.path.join(KIT, 'schema.json'), 'rb') as b:
            self.assertEqual(a.read(), b.read())

    def test_start_wake_and_stop_are_warps_documented_calls(self):
        code, out = self.call('start', dict(START, harness='codex', model='gpt-5-codex'),
                              OPENWIZ_WARP_ENVIRONMENT='env-syn0001')
        self.assertEqual(code, 0, out)
        run = out['run']
        self.assertRegex(run, r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
        self.assertEqual(self.call('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        create, followup, cancel = self.calls()
        self.assertEqual((create['method'], create['path'], create['body']), ('POST', RUNS, {
            'prompt': 'Build the ticket: example/site#7, with the build-ticket skill.',
            'config': {'harness': {'type': 'codex', 'model_id': 'gpt-5-codex'},
                       'harness_auth_secrets': {'codex_auth_secret_name': 'SYN_CODEX_LOGIN'},
                       'environment_id': 'env-syn0001'}}))
        self.assertEqual((followup['method'], followup['path'], followup['body']), (
            'POST', '%s/%s/followups' % (RUNS, run),
            {'message': 'You were woken: read the ticket again and carry on: example/site#7, with the '
                        'build-ticket skill.'}))
        self.assertEqual((cancel['method'], cancel['path'], cancel['body']), ('POST', '%s/%s/cancel' % (RUNS, run),
                                                                              None))
        self.assertEqual({c['authorization'] for c in self.calls()}, {'Bearer ' + self.key})
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a stopped run took a wake')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.call('wake', {'run': '0' * 8 + '-0000-0000-0000-' + '0' * 12})[0], 1,
                         'an unknown run took a wake')
        self.assertEqual(len(self.calls()), 3, 'a stopped or unknown run reached Warp')

    def test_harness_login_and_environment_are_checked_before_any_call(self):
        self.assertEqual(self.call('start', START)[0], 0)
        self.assertEqual([c['body']['config'] for c in self.calls()], [{
            'harness': {'type': 'claude'}, 'harness_auth_secrets': {'claude_auth_secret_name': 'SYN_CLAUDE_LOGIN'}}])
        for request, env in ((dict(START, harness='oz'), {}), (dict(START, harness='gemini'), {}),
                             (START, {'OPENWIZ_WARP_CLAUDE_LOGIN': ''}),
                             (dict(START, harness='codex'), {'OPENWIZ_WARP_CODEX_LOGIN': 'a b'}),
                             (START, {'OPENWIZ_WARP_CLAUDE_LOGIN': 'x' * 200}),
                             (START, {'OPENWIZ_WARP_ENVIRONMENT': 'env/../x'})):
            with self.subTest(request=request, env=env):
                self.assertEqual(self.call('start', request, **env)[0], 1)
        self.assertEqual(len(self.calls()), 1)

    def test_codex_effort_reaches_warp_as_its_reasoning_level(self):
        for effort in ('low', 'medium', 'high', 'xhigh'):
            with self.subTest(effort=effort):
                code, out = self.call('start', dict(START, harness='codex', effort=effort))
                self.assertEqual(code, 0, out)
                self.assertEqual(self.calls()[-1]['body']['config']['harness'],
                                 {'type': 'codex', 'reasoning_level': effort})
        self.assertEqual(len(self.calls()), 4)

    def test_an_effort_warp_cant_set_is_refused_and_starts_nothing(self):
        for harness, effort in (('claude', 'medium'), ('claude', 'low'), ('codex', 'max'), ('codex', 'minimal')):
            with self.subTest(harness=harness, effort=effort):
                code, out = self.call('start', dict(START, harness=harness, effort=effort))
                self.assertEqual((code, out['next']), (1, REFUSAL))
                self.assertIn(harness, out['error'])
                self.assertIn(effort, out['error'])
        for bad in ('Medium', '', 7, 'a' * 21):
            with self.subTest(effort=bad):
                self.assertEqual(self.call('start', dict(START, harness='codex', effort=bad))[0], 1)
        state = self.env['OPENWIZ_WARP_OZ_STATE']
        self.assertEqual((self.calls(), os.listdir(state) if os.path.isdir(state) else []), ([], []))

    def test_a_host_refusal_is_an_error_and_a_failed_stop_is_tried_again(self):
        for answer in ({'status': 401, 'body': {'error': 'synthetic refusal'}},
                       {'status': 200, 'body': {'run_id': 'ghp_' + 'Synthetic0' * 3, 'state': 'QUEUED'}},
                       {'status': 200, 'body': {'state': 'QUEUED'}}):
            with self.subTest(answer=answer):
                self.fault({'POST create': answer})
                code, out = self.call('start', START)
                self.assertEqual(code, 1, out)
                self.assertNotIn('Synthetic', json.dumps(out))
        state = self.env['OPENWIZ_WARP_OZ_STATE']
        self.assertEqual(os.listdir(state) if os.path.isdir(state) else [], [], 'a refused start left a run')
        self.fault({})
        run = self.call('start', START)[1]['run']
        self.fault({'POST followups': {'status': 500, 'body': {}}, 'POST cancel': {'status': 409, 'body': {}}})
        self.assertEqual(self.call('wake', {'run': run})[0], 1)
        self.assertEqual(self.call('stop', {'run': run})[0], 1)
        self.fault({})
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a run being stopped took a wake')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual([c['path'].rsplit('/', 1)[1] for c in self.calls()][-3:], ['followups', 'cancel', 'cancel'])

    def test_a_wake_or_cancel_answer_warp_never_documents_is_unknown_and_stop_stays_retryable(self):
        run = self.call('start', START)[1]['run']
        other = '1' * 8 + '-1111-1111-1111-' + '1' * 12
        for answer in ({'status': 200, 'body': None}, {'status': 200, 'raw': 'not json'}, {'status': 200, 'body': {}},
                       {'status': 200, 'body': {'followup_id': 'f1', 'outcome': 'delivered'}},
                       {'status': 200, 'body': {'followup_id': 7, 'outcome': 'live_session'}},
                       {'status': 200, 'body': {'followup_id': None, 'outcome': 'live_session'}},
                       {'status': 200, 'body': {'followup_id': 'f1', 'outcome': 'live_session', 'extra': 1}},
                       {'status': 202, 'body': {'followup_id': 'f1', 'outcome': 'live_session'}}):
            with self.subTest(wake=answer):
                self.fault({'POST followups': answer})
                code, out = self.call('wake', {'run': run})
                self.assertEqual(code, 1, out)
                self.assertIn(run, out['error'])
        problem = {'type': 'https://example.invalid/errors', 'title': 'Bad Request', 'status': 400,
                   'error': 'the run is already in a terminal state'}
        gone = dict(problem, title='Not Found', status=404, error='run not found')
        item = {'run_id': run, 'task_id': run, 'title': 'synthetic run', 'state': 'INPROGRESS', 'prompt': 'p',
                'created_at': 't', 'finished_at': None, 'updated_at': 't', 'root_run_id': run}
        for faults in ({'POST cancel': {'status': 200, 'body': None}},
                       {'POST cancel': {'status': 200, 'raw': '{not json'}},
                       {'POST cancel': {'status': 200, 'body': {'run_id': run}}},
                       {'POST cancel': {'status': 200, 'body': other}},
                       {'POST cancel': {'status': 204, 'body': None}},
                       {'POST cancel': {'status': 400, 'body': {'error': 'bad request'}}},
                       {'POST cancel': {'status': 404, 'body': None}},
                       {'POST cancel': {'status': 400, 'body': dict(problem, status=404)}},
                       {'POST cancel': {'status': 400, 'body': problem}},
                       {'POST cancel': {'status': 400, 'body': problem}, 'GET run': {'status': 200, 'body': None}},
                       {'POST cancel': {'status': 400, 'body': problem},
                        'GET run': {'status': 200, 'body': dict(item, run_id=other, state='CANCELLED')}},
                       {'POST cancel': {'status': 400, 'body': problem},
                        'GET run': {'status': 200, 'body': dict(item, state='cancelled')}},
                       {'POST cancel': {'status': 400, 'body': problem}, 'GET run': {'status': 404, 'body': gone}},
                       {'POST cancel': {'status': 404, 'body': gone}},
                       {'POST cancel': {'status': 404, 'body': gone}, 'GET run': {'status': 404, 'body': None}},
                       {'POST cancel': {'status': 404, 'body': gone}, 'GET run': {'status': 500, 'body': gone}},
                       {'POST cancel': {'status': 404, 'body': dict(gone, instance='/x')},
                        'GET run': {'status': 404, 'body': gone}}):
            with self.subTest(stop=faults):
                self.fault(faults)
                before = len(self.calls())
                code, out = self.call('stop', {'run': run})
                self.assertEqual(code, 1, out)
                self.assertIn(run, out['error'])
                self.assertEqual(self.calls()[before]['path'], '%s/%s/cancel' % (RUNS, run), 'stop was not retried')
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a run being stopped took a wake')
        self.fault({'POST cancel': {'status': 400, 'body': problem},
                    'GET run': {'status': 200, 'body': dict(item, state='CANCELLED')}})
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        before = len(self.calls())
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(len(self.calls()), before, 'an ended run reached Warp again')

    def test_a_run_saved_but_not_cancelled_says_so(self):
        run = '2' * 8 + '-2222-2222-2222-' + '2' * 12
        state = self.env['OPENWIZ_WARP_OZ_STATE']
        os.makedirs(os.path.join(state, run + '.json'))
        gone = {'type': 'https://example.invalid/errors', 'title': 'Not Found', 'status': 404,
                'error': 'run not found'}
        for extra, said in (({'POST cancel': {'status': 200, 'body': None}}, 'could not cancel'),
                            ({'POST cancel': {'status': 200, 'body': '3' * 8 + '-3333-3333-3333-' + '3' * 12}},
                             'could not cancel'),
                            ({'POST cancel': {'status': 400, 'body': {'error': 'bad request'}}}, 'could not cancel'),
                            ({'POST cancel': {'status': 404, 'body': gone}, 'GET run': {'status': 404, 'body': gone}},
                             'could not cancel'),
                            ({'POST cancel': {'status': 200, 'body': run}}, 'so it cancelled it')):
            with self.subTest(extra=extra):
                self.fault(dict({'POST create': {'status': 200, 'body': {'run_id': run, 'state': 'QUEUED'}}}, **extra))
                code, out = self.call('start', START)
                self.assertEqual(code, 1, out)
                self.assertIn(run, out['error'])
                self.assertIn(said, out['error'])

    def test_an_uncertain_create_is_never_retried_and_a_confirmed_refusal_is_told_apart(self):
        for fault in ({'drop': True}, {'status': 503, 'body': {}}, {'status': 408, 'body': {}},
                      {'status': 200, 'body': {'state': 'QUEUED'}}):
            with self.subTest(fault=fault):
                self.fault({'POST create': fault})
                code, out = self.call('start', START)
                self.assertEqual(code, 1, out)
                self.assertIn('outcome is unknown', out['error'])
                self.assertEqual(out['next'], UNCERTAIN_CREATE)
        with open(self.tracker) as f:
            self.assertEqual(len(json.load(f)['comments']), 1, 'the dropped create never ran on the fake host')
        self.fault({'POST create': {'status': 422, 'body': {}}})
        code, out = self.call('start', START)
        self.assertEqual((code, out['error']), (1, 'Warp refused the new run (422), so nothing was started'))
        self.fault({'GET key': {'status': 200, 'body': {'key': ''}}})
        code, out = self.call('start', START)
        self.assertEqual(code, 1, out)
        self.assertNotIn('outcome is unknown', out['error'])
        self.assertTrue(out['error'].startswith("the key helper refused: the kit's fake host gave no test key"), out)
        state = self.env['OPENWIZ_WARP_OZ_STATE']
        self.assertEqual(os.listdir(state) if os.path.isdir(state) else [], [], 'an unsaved start left a run')
        self.assertEqual([c['method'] for c in self.calls()], ['POST'] * 5)

    def test_a_404_on_stop_stays_retryable_when_another_team_key_cannot_see_the_run(self):
        run = self.call('start', START)[1]['run']
        other_key = 'syn-other-team-' + secrets.token_hex(12)
        self.fault({'GET key': {'status': 200, 'body': {'key': other_key}}})
        before = len(self.calls())
        code, out = self.call('stop', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertIn(run, out['error'])
        self.assertIn('404', out['error'])
        self.assertIn('team or account', out['next'])
        self.assertEqual([(c['method'], c['path'], c['authorization']) for c in self.calls()[before:]],
                         [('POST', '%s/%s/cancel' % (RUNS, run), 'Bearer ' + other_key),
                          ('GET', '%s/%s' % (RUNS, run), 'Bearer ' + other_key)])
        before = len(self.calls())
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a run being stopped took a wake')
        self.assertEqual(len(self.calls()), before, 'a wake after a 404 stop reached Warp')
        self.fault({})
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual([(c['method'], c['path'], c['authorization']) for c in self.calls()[before:]],
                         [('POST', '%s/%s/cancel' % (RUNS, run), 'Bearer ' + self.key)])
        before = len(self.calls())
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(len(self.calls()), before, 'an ended run reached Warp again')

    def test_a_provider_qualified_model_within_the_schema_reaches_warp(self):
        for model in ('kimi-code/kimi-for-coding', 'openrouter/anthropic/claude-sonnet-4.6',
                      'anthropic/claude-sonnet-4@20250514', 'a/' + 'b' * 98):
            with self.subTest(model=model):
                code, out = self.call('start', dict(START, model=model))
                self.assertEqual(code, 0, out)
                self.assertEqual(self.calls()[-1]['body']['config']['harness']['model_id'], model)
                run = out['run']
        self.assertEqual(self.call('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        before = len(self.calls())
        for bad in ('/leading-slash', 'trailing/', 'a//b', 'a' * 101, ''):
            with self.subTest(bad_model=bad):
                self.assertEqual(self.call('start', dict(START, model=bad))[0], 1)
        self.assertEqual(len(self.calls()), before)

    def test_a_credential_shaped_model_is_refused_before_start(self):
        for shape, model in (('bearer', 'Bearer synthetic-value'),
                             ('credential field', 'token: synthetic-value'),
                             ('qualified token', 'example/' + 'ghp_' + 'Synthetic0' * 3)):
            with self.subTest(shape=shape):
                self.assertIsNotNone(kit.SHAPES.search(model))
                code, out = self.call('start', dict(START, model=model),
                                      OPENWIZ_HOSTKEY_TEST_ORIGIN='invalid-test-origin')
                self.assertEqual((code, out), (1, {
                    'error': 'the model looks like a credential',
                    'next': 'choose a model id for this harness and keep credentials out of the request',
                }))
        self.assertEqual(self.calls(), [])
        self.assertFalse(os.path.exists(self.env['OPENWIZ_WARP_OZ_STATE']))

    def test_a_saved_run_is_read_only_in_its_exact_shape(self):
        run = self.call('start', START)[1]['run']
        record = os.path.join(self.env['OPENWIZ_WARP_OZ_STATE'], run + '.json')
        with open(record) as f:
            good = f.read()
        request = json.loads(good)['request']
        for bad in ({'request': request, 'stopped': False, 'ended': 'false'},
                    {'request': request, 'stopped': 'false', 'ended': False},
                    {'request': request, 'stopped': 0, 'ended': 0},
                    {'request': request, 'stopped': True, 'ended': 1},
                    {'request': request, 'stopped': False, 'ended': True},
                    {'request': request, 'stopped': False},
                    {'request': request, 'stopped': False, 'ended': False, 'extra': 1},
                    {'request': dict(request, ticket='7'), 'stopped': False, 'ended': False},
                    {'request': dict(request, harness='oz'), 'stopped': False, 'ended': False},
                    {'request': 'x', 'stopped': False, 'ended': False},
                    [request, False, False], None, '{"request": 1, "request": 2}'):
            for cmd in ('wake', 'stop'):
                with self.subTest(record=bad, cmd=cmd):
                    with open(record, 'w') as f:
                        f.write(bad if isinstance(bad, str) else json.dumps(bad))
                    code, out = self.call(cmd, {'run': run})
                    self.assertEqual(code, 1, out)
                    self.assertIn(run, out['error'])
                    self.assertNotIn('no run', out['error'])
        with open(record, 'w') as f:
            f.write(good)
        state = self.env['OPENWIZ_WARP_OZ_STATE']
        os.chmod(state, 0)
        self.addCleanup(os.chmod, state, 0o700)
        for cmd in ('wake', 'stop'):
            with self.subTest(inaccessible=cmd):
                code, out = self.call(cmd, {'run': run})
                self.assertEqual(code, 1, out)
                self.assertIn(run, out['error'])
                self.assertNotIn('no run', out['error'])
        os.chmod(state, 0o700)
        missing = '4' * 8 + '-4444-4444-4444-' + '4' * 12
        self.assertEqual(self.call('stop', {'run': missing})[1]['error'], 'no run ' + missing)
        self.assertEqual(len(self.calls()), 1, 'a malformed, unreadable or missing record reached Warp')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))


if __name__ == '__main__':
    unittest.main()
