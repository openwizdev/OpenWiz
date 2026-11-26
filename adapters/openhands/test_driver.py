#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(ROOT, 'kernel', 'driver-kit', 'kit.py')
KEY = 'synthetic-openhands-' + 'Kit0Value' * 2
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude-code',
         'model': 'Synthetic 1'}
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
KIT_PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
            "pass start: the run posted builder status note 2; effort: a start with it was refused, as the README's "
            'Effort: line says',
            'pass wake: the run edited builder status note 2',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the openhands '
            'key reached its host only from the key helper, in its header']


def module(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fake = module(os.path.join(HERE, 'fixtures', 'fake_openhands.py'), 'fake_openhands')


def tracker(folder):
    path = os.path.join(folder, 'tracker.json')
    old = '<!-- openwiz:status v1 -->\nagent: builder\nstate: stopped\nharness: Fake\nmodel: m\n' \
          'skills: build-ticket@0.1.2\nstep: an earlier run\ntime: 2030-01-02T03:04:05Z\n'
    with open(path, 'w') as f:
        json.dump({'record_authors': ['Example-Bot[bot]'], 'comments': [
            {'id': 1, 'author': 'example-bot[bot]', 'updated_at': '2030-01-02T03:04:05Z', 'body': old}]}, f)
    return path


class Driver(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.mark = secrets.token_hex(8)
        self.tracker = tracker(self.folder)
        self.host = self.fake()
        self.env = dict(os.environ, KIT_TEST=self.mark,
                        OPENWIZ_HOSTKEY_TEST_ORIGIN=self.host.origin)

    def fake(self, **kw):
        host = fake.FakeOpenHands(KEY, self.tracker, **kw)
        self.addCleanup(host.close)
        return host

    def tearDown(self):
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass

    def driver(self, cmd, request=None, **env):
        p = subprocess.run([DRIVER, cmd], input='' if request is None else json.dumps(request),
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=120)
        self.assertEqual(p.stderr, '')
        self.assertIn(p.returncode, (0, 1))
        out = json.loads(p.stdout)
        if p.returncode:
            self.assertEqual(set(out), {'error', 'next'}, out)
        return p.returncode, out

    def started(self, **kw):
        code, out = self.driver('start', dict(START, **kw))
        self.assertEqual(code, 0, out)
        return out['run']

    def notes(self):
        with open(self.tracker) as f:
            return [c for c in json.load(f)['comments'] if 'state: working' in c['body']]

    def kit(self, driver=DRIVER, **env):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', driver, '--repo', 'example/site', '--ticket', '7',
                            '--harness', 'claude-code', '--model', 'Synthetic 1', '--tracker', self.tracker,
                            '--wait', '8'], env=dict(self.env, **env), capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout.splitlines(), p.stderr

    def test_kit_passes_all_five_on_the_fake_host(self):
        code, out, err = self.kit()
        self.assertEqual((out, err), (KIT_PASS, ''))
        self.assertEqual(code, 0)

    def test_every_request_reaches_the_host_with_the_key_header_only(self):
        run = self.started()
        self.driver('wake', {'run': run})
        self.driver('stop', {'run': run})
        self.assertTrue(self.host.requests)
        for method, path, body, auth in self.host.requests:
            self.assertEqual(auth, 'Bearer ' + KEY)
            self.assertNotIn(KEY, path + body.decode())

    def test_start_creates_one_conversation_on_the_harness_profile(self):
        run = self.started()
        self.assertRegex(run, UUID)
        self.assertEqual(list(self.host.conversations), [run])
        sent = self.host.conversations[run]['request']
        self.assertEqual(sent, {
            'conversation_id': run, 'agent_profile_id': '00000000-0000-4000-8000-00000000000b',
            'selected_repository': 'example/site', 'git_provider': 'github',
            'title': 'OpenWiz: example/site#7',
            'initial_message': {'role': 'user', 'run': True, 'content': [
                {'type': 'text', 'text': 'Build the ticket: example/site#7, with the build-ticket skill.'}]}})
        run = self.started(harness='codex', model='Synthetic 2')
        self.assertEqual(self.host.conversations[run]['request']['agent_profile_id'],
                         '00000000-0000-4000-8000-00000000000c')
        self.assertIn(('GET', '/api/agent-profiles/codex-synthetic?scope=org'), self.host.calls())

    def test_start_refuses_without_a_profile_for_the_harness(self):
        for harness, model in (('codex', 'Synthetic 1'), ('gemini-cli', 'Synthetic 1')):
            code, out = self.driver('start', dict(START, harness=harness, model=model))
            self.assertEqual(code, 1)
            self.assertNotIn('POST', [m for m, _ in self.host.calls()])
        code, out = self.driver('start', dict(START, harness='codex', model='Synthetic 1'))
        self.assertEqual(out['error'], 'OpenHands Cloud has no ACP agent profile for codex with model Synthetic 1')
        code, out = self.driver('start', dict(START, harness='gemini-cli'))
        self.assertEqual(out['error'], 'harness gemini-cli is not one OpenHands Cloud runs for OpenWiz')

    def test_wake_resumes_the_paused_sandbox_then_sends_the_message(self):
        run = self.started()
        self.driver('stop', {'run': self.started()})
        self.host.requests.clear()
        code, out = self.driver('wake', {'run': run})
        self.assertEqual((code, out), (0, {'run': run, 'woke': True}))
        sandbox = self.host.conversations[run]['sandbox_id']
        posts = [p for m, p in self.host.calls() if m == 'POST']
        self.assertEqual(posts, ['/api/v1/sandboxes/%s/resume' % sandbox,
                                 '/api/v1/app-conversations/%s/send-message' % run])
        self.assertEqual(self.host.conversations[run]['messages'],
                         ['You were woken: read the ticket again and carry on.'])
        self.assertEqual(len(self.notes()), 2)

    def test_wake_of_a_running_sandbox_sends_without_resuming(self):
        self.host = self.fake(pause_after_turn=False)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        run = self.started()
        self.driver('wake', {'run': run})
        self.assertNotIn('resume', ' '.join(p for _, p in self.host.calls()))
        self.assertEqual(len(self.host.conversations[run]['messages']), 1)

    def test_stop_pauses_then_deletes_and_wake_after_is_refused(self):
        run = self.started()
        self.host.requests.clear()
        code, out = self.driver('stop', {'run': run})
        self.assertEqual((code, out), (0, {'run': run, 'stopped': True}))
        sandbox = self.host.conversations[run]['sandbox_id']
        self.assertEqual([(m, p) for m, p in self.host.calls() if m != 'GET'],
                         [('POST', '/api/v1/sandboxes/%s/pause' % sandbox),
                          ('DELETE', '/api/v1/app-conversations/%s' % run)])
        self.assertTrue(self.host.conversations[run]['deleted'])
        code, out = self.driver('wake', {'run': run})
        self.assertEqual(code, 1)
        self.assertEqual(out['error'], 'run %s is stopped' % run)
        code, out = self.driver('stop', {'run': run})
        self.assertEqual((code, out), (0, {'run': run, 'stopped': True}))

    def test_stop_while_starting_waits_for_the_conversation_then_ends_it(self):
        self.host = self.fake(starting_lookups=3)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        run = self.started()
        code, out = self.driver('stop', {'run': run}, OPENWIZ_OPENHANDS_POLL='0.01')
        self.assertEqual((code, out), (0, {'run': run, 'stopped': True}))
        self.assertTrue(self.host.conversations[run]['deleted'])

    def test_a_lost_start_names_its_run_so_stop_can_end_it(self):
        self.host = self.fake(lose_start=True)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        code, out = self.driver('start', START)
        self.assertEqual(code, 1)
        [run] = self.host.conversations
        self.assertEqual(out, {'error': 'run %s may have started: OpenHands Cloud answered 503 to POST '
                                        '/api/v1/app-conversations' % run,
                               'next': 'stop run %s with `driver stop`, then start again' % run})
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertTrue(self.host.conversations[run]['deleted'])

    def refused(self, cmd, run, **env):
        code, out = self.driver(cmd, {'run': run}, **env)
        self.assertEqual(code, 1, out)
        self.assertIn(run, out['error'])
        self.assertIn(run, out['next'])
        return out

    def mutations(self):
        return [(m, p) for m, p in self.host.calls() if m != 'GET']

    def test_stop_and_wake_refuse_an_unreadable_conversation_lookup(self):
        for reply in (None, {}, [], [None, None], ['x'], [{'sandbox_id': 'sandbox-synthetic-0'}],
                      [{'id': '00000000-0000-4000-8000-0000000000aa', 'sandbox_id': 'sandbox-synthetic-0',
                        'sandbox_status': 'RUNNING'}],
                      [{'id': 'RUN', 'sandbox_id': 'sandbox-synthetic-0', 'sandbox_status': 'BOGUS'}],
                      [{'id': 'RUN', 'sandbox_id': None, 'sandbox_status': 'RUNNING'}]):
            with self.subTest(reply=reply):
                run = self.started()
                self.host.requests.clear()
                body = json.loads(json.dumps(reply).replace('RUN', run))
                self.host.answer('GET', '/api/v1/app-conversations', 200, body, times=1)
                self.refused('stop', run)
                self.host.answer('GET', '/api/v1/app-conversations', 200, body, times=1)
                self.refused('wake', run)
                self.assertEqual(self.mutations(), [])
                self.assertFalse(self.host.conversations[run]['deleted'])
                self.assertEqual(self.host.conversations[run]['messages'], [])

    def test_stop_and_wake_refuse_an_unreadable_task_lookup(self):
        self.host = self.fake(starting_lookups=100)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        for reply in (None, {}, {'items': None}, {'items': ['x']}, {'items': [{'status': 'BOGUS'}]},
                      {'items': [{'status': 'READY', 'app_conversation_id': '00000000-0000-4000-8000-0000000000aa'}]},
                      {'items': [{'status': 'WORKING'}, {'status': 'WORKING'}]}):
            with self.subTest(reply=reply):
                run = self.started()
                self.host.requests.clear()
                for cmd in ('stop', 'wake'):
                    self.host.answer('GET', '/api/v1/app-conversations/start-tasks/search', 200, reply, times=1)
                    self.refused(cmd, run, OPENWIZ_OPENHANDS_POLL='0.01')
                self.assertEqual(self.mutations(), [])

    def test_a_run_absent_from_both_lookups_is_stopped_but_not_woken(self):
        run = '00000000-0000-4000-8000-0000000000ff'
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.mutations(), [])

    def test_start_refuses_an_unacknowledged_create_naming_the_run(self):
        for reply in (None, [], {}, {'status': 'BOGUS', 'id': 'task-synthetic'},
                      {'status': 'WORKING', 'id': None},
                      {'status': 'READY', 'id': 'task-synthetic',
                       'app_conversation_id': '00000000-0000-4000-8000-0000000000aa'}):
            with self.subTest(reply=reply):
                self.host.answer('POST', '/api/v1/app-conversations', 200, reply, times=1)
                code, out = self.driver('start', START)
                self.assertEqual(code, 1, out)
                run = re.search(UUID, out['error']).group(0)
                self.assertTrue(out['error'].startswith('run %s may have started: ' % run), out)
                self.assertEqual(out['next'], 'stop run %s with `driver stop`, then start again' % run)

    def test_wake_refuses_an_unconfirmed_send_or_resume(self):
        for path in ('/api/v1/app-conversations/[^/]+/send-message', '/api/v1/sandboxes/[^/]+/resume'):
            for reply in ({'success': False, 'sandbox_status': 'RUNNING'}, None, {}):
                with self.subTest(path=path, reply=reply):
                    run = self.started()
                    self.host.answer('POST', path, 200, reply, times=1)
                    out = self.refused('wake', run)
                    self.assertNotIn('woke', out)
                    self.assertEqual(self.host.conversations[run]['messages'], [])

    def test_stop_refuses_an_unconfirmed_pause_or_delete(self):
        for path, code, reply in (('/api/v1/sandboxes/[^/]+/pause', 200, {'success': False}),
                                  ('/api/v1/sandboxes/[^/]+/pause', 200, None),
                                  ('/api/v1/sandboxes/[^/]+/pause', 409, {'detail': 'synthetic conflict'}),
                                  ('/api/v1/app-conversations/[^/]+', 200, {'success': False}),
                                  ('/api/v1/app-conversations/[^/]+', 200, None)):
            with self.subTest(path=path, code=code, reply=reply):
                run = self.started()
                self.host.requests.clear()
                self.host.answer('POST' if 'sandboxes' in path else 'DELETE', path, code, reply, times=1)
                self.refused('stop', run)
                if 'sandboxes' in path:
                    self.assertNotIn('DELETE', [m for m, _ in self.mutations()])
                self.assertFalse(self.host.conversations[run]['deleted'])

    def test_stop_takes_a_pause_404_only_when_the_sandbox_is_confirmed_stopped(self):
        run = self.started()
        self.host.conversations[run]['sandbox_status'] = 'RUNNING'
        self.host.answer('POST', '/api/v1/sandboxes/[^/]+/pause', 404, {'detail': 'Item not found'}, times=1)
        self.refused('stop', run)
        self.assertNotIn('DELETE', [m for m, _ in self.mutations()])
        self.assertFalse(self.host.conversations[run]['deleted'])
        self.host.conversations[run]['sandbox_status'] = 'PAUSED'
        self.host.answer('POST', '/api/v1/sandboxes/[^/]+/pause', 404, {'detail': 'Item not found'}, times=1)
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertTrue(self.host.conversations[run]['deleted'])

    def test_stop_takes_a_delete_404_only_when_the_conversation_is_confirmed_gone(self):
        run = self.started()
        self.host.answer('DELETE', '/api/v1/app-conversations/[^/]+', 404, {'detail': 'Item not found'}, times=1)
        self.refused('stop', run)
        self.assertFalse(self.host.conversations[run]['deleted'])

    def test_wake_while_starting_waits_then_sends_the_follow_up(self):
        self.host = self.fake(starting_lookups=3)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        run = self.started()
        code, out = self.driver('wake', {'run': run}, OPENWIZ_OPENHANDS_POLL='0.01')
        self.assertEqual((code, out), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.host.conversations[run]['messages'],
                         ['You were woken: read the ticket again and carry on.'])

    def test_wake_still_starting_after_the_wait_refuses_with_a_retry(self):
        self.host = self.fake(starting_lookups=10 ** 6)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        run = self.started()
        out = self.refused('wake', run, OPENWIZ_OPENHANDS_POLL='0.01', OPENWIZ_OPENHANDS_WAIT='0.3')
        self.assertEqual(out, {'error': 'run %s is still starting on OpenHands Cloud' % run,
                               'next': 'wake run %s again in a minute' % run})
        self.assertFalse([p for m, p in self.host.calls() if 'send-message' in p])

    def test_start_refuses_when_only_a_default_model_profile_exists(self):
        profiles = fake.PROFILES + [dict(fake.PROFILES[1], id='00000000-0000-4000-8000-00000000000d',
                                         name='claude-default', acp_model=None)]
        self.host = self.fake(profiles=profiles)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        code, out = self.driver('start', dict(START, model='Synthetic 9'))
        self.assertEqual((code, out['error']), (1, 'OpenHands Cloud has no ACP agent profile for claude-code '
                                                   'with model Synthetic 9'))
        self.assertEqual(self.mutations(), [])
        run = self.started()
        self.assertEqual(self.host.conversations[run]['request']['agent_profile_id'],
                         '00000000-0000-4000-8000-00000000000b')

    def test_unknown_run_is_refused_by_wake(self):
        code, out = self.driver('wake', {'run': '00000000-0000-4000-8000-0000000000ff'})
        self.assertEqual(code, 1)
        self.assertEqual(out['error'], 'OpenHands Cloud has no run 00000000-0000-4000-8000-0000000000ff')

    def test_start_refuses_effort_before_any_request(self):
        code, out = self.driver('start', dict(START, effort='high'))
        self.assertEqual((code, out), (1, {
            'error': 'OpenHands Cloud cannot set effort high for harness claude-code',
            'next': "this host can't set effort: remove the effort for this harness in your Models table or Roster "
                    "to run it at the host's default"}))
        self.assertEqual(self.host.key_requests, 0)
        self.assertEqual(self.host.requests, [])

    def test_inputs_off_the_schema_are_refused_before_any_request(self):
        for bad in (dict(START, token='kit-probe-not-a-login'), {k: v for k, v in START.items() if k != 'model'},
                    dict(START, ticket='7'), dict(START, repository='https://example.com/x')):
            code, out = self.driver('start', bad)
            self.assertEqual(code, 1)
        for bad in ({'run': 'not a uuid'}, {'run': '../x'}, {'run': '00000000-0000-4000-8000-0000000000ff', 'x': 1}):
            for cmd in ('wake', 'stop'):
                self.assertEqual(self.driver(cmd, bad)[0], 1)
        self.assertEqual(self.host.requests, [])

    def test_a_host_error_is_a_fixed_refusal(self):
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.fake(served_key='synthetic-wrong-' + 'Kit0Value' * 2).origin
        code, out = self.driver('start', START)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin
        self.assertEqual(code, 1)
        self.assertEqual(out['error'], 'OpenHands Cloud answered 401 to GET /api/agent-profiles')
        run = self.started()
        code, out = self.driver('wake', {'run': run})
        self.assertNotIn('synthetic-session-value', json.dumps(out))

    def test_version_and_schema(self):
        self.assertEqual(self.driver('version'), (0, {'driver': 'openhands', 'records': ['openwiz:records v1'],
                                                       'can': ['start', 'wake', 'stop']}))
        with open(os.path.join(ROOT, 'kernel', 'driver-kit', 'schema.json'), 'rb') as a, \
                open(os.path.join(HERE, 'schema.json'), 'rb') as b:
            self.assertEqual(a.read(), b.read())


if __name__ == '__main__':
    unittest.main()
