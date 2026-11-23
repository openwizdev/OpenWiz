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
KEY = 'synthetic-tembo-' + 'Kit0Value' * 2
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude-code',
         'model': 'synthetic-model-1'}
PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill.'
REPO = '00000000-0000-4000-8000-0000000000a2'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
NO_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run "
             "it at the host's default")
KEYCHAIN_TOOLS_SPELLED_IN_PARTS = re.compile(rb'(?<![\w-])(secur' + rb'ity|secret' + rb'-tool)(?![\w-])')
KIT_PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 2',
            'pass wake: the run edited builder status note 2',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the tembo '
            'key reached its host only from the key helper, in its header']


def module(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fake = module(os.path.join(HERE, 'fixtures', 'fake_tembo.py'), 'fake_tembo')


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
        self.env = dict(os.environ, KIT_TEST=self.mark, OPENWIZ_HOSTKEY_TEST_ORIGIN=self.host.origin)

    def fake(self, **kw):
        host = fake.FakeTembo(KEY, self.tracker, **kw)
        self.addCleanup(host.close)
        return host

    def use(self, **kw):
        self.host = self.fake(**kw)
        self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'] = self.host.origin

    def tearDown(self):
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass

    def driver(self, cmd, request=None):
        p = subprocess.run([DRIVER, cmd], input='' if request is None else json.dumps(request), env=self.env,
                           capture_output=True, text=True, timeout=120)
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

    def posts(self):
        return [p for m, p in self.host.calls() if m != 'GET']

    def kit(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site', '--ticket', '7',
                            '--harness', 'claude-code', '--model', 'synthetic-model-1', '--tracker', self.tracker,
                            '--wait', '8'], env=self.env, capture_output=True, text=True, timeout=300)
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

    def test_start_creates_one_session_on_the_harness_agent(self):
        run = self.started()
        self.assertRegex(run, UUID)
        self.assertEqual(list(self.host.sessions), [run])
        self.assertEqual(self.host.sessions[run]['request'], {
            'id': run, 'description': PROMPT, 'agent': 'claudeCode:synthetic-model-1', 'codeRepositoryIds': [REPO],
            'queueRightAway': True})
        self.assertEqual(self.posts(), ['/v1/sessions'])
        self.assertEqual(len(self.notes()), 1)
        for harness, agent in (('claude', 'claudeCode'), ('codex', 'codex')):
            run = self.started(harness=harness, model='synthetic-model-2')
            self.assertEqual(self.host.sessions[run]['request']['agent'], agent + ':synthetic-model-2')

    def test_start_picks_the_repository_by_its_exact_owner_and_name(self):
        run = self.started()
        self.assertEqual(self.host.sessions[run]['request']['codeRepositoryIds'], [REPO])
        self.assertIn(('GET', '/v1/repositories?search=site&limit=100'), self.host.calls())

    def test_start_refuses_a_repository_tembo_has_not_connected(self):
        code, out = self.driver('start', dict(START, repository='example/elsewhere'))
        self.assertEqual((code, out), (1, {
            'error': 'Tembo has no connected repository example/elsewhere',
            'next': 'connect example/elsewhere to Tembo (Settings, Integrations, GitHub), then start again'}))
        self.assertEqual(self.posts(), [])

    def test_start_refuses_a_harness_tembo_does_not_run_for_openwiz(self):
        code, out = self.driver('start', dict(START, harness='gemini-cli'))
        self.assertEqual((code, out), (1, {'error': 'harness gemini-cli is not one Tembo runs for OpenWiz',
                                           'next': 'use claude-code (or claude) or codex'}))
        self.assertEqual(self.host.requests, [])

    def test_wake_queues_one_message_on_the_same_session(self):
        run = self.started()
        self.host.requests.clear()
        code, out = self.driver('wake', {'run': run})
        self.assertEqual((code, out), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.posts(), ['/v1/messages'])
        self.assertEqual(json.loads(self.host.requests[-1][2]), {
            'sessionId': run, 'content': 'You were woken: read the ticket again and carry on.',
            'deliveryMode': 'queue'})
        [note] = self.notes()
        self.assertIn('step: woke and read the ticket again', note['body'])

    def test_stop_stops_then_archives_and_wake_after_is_refused(self):
        run = self.started()
        self.host.requests.clear()
        code, out = self.driver('stop', {'run': run})
        self.assertEqual((code, out), (0, {'run': run, 'stopped': True}))
        self.assertEqual([(m, p) for m, p in self.host.calls() if m != 'GET'],
                         [('POST', '/v1/sessions/%s/stop?cancelQueued=true' % run), ('DELETE', '/v1/sessions/' + run)])
        self.assertEqual((self.host.sessions[run]['stopped'], self.host.sessions[run]['level']), (True, 0))
        code, out = self.driver('wake', {'run': run})
        self.assertEqual((code, out), (1, {'error': 'run %s is stopped' % run, 'next': 'start a new run'}))
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.posts(), [])

    def test_a_lost_start_names_its_run_so_stop_can_end_it(self):
        self.use(lose_start=True)
        code, out = self.driver('start', START)
        self.assertEqual(code, 1)
        [run] = self.host.sessions
        self.assertEqual(out, {'error': 'run %s may have started: Tembo answered 502 to POST /v1/sessions' % run,
                               'next': 'stop run %s with `driver stop`, then start again' % run})
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.host.sessions[run]['level'], 0)

    def test_unknown_run_is_refused_by_wake_and_stopped_by_stop(self):
        run = '00000000-0000-4000-8000-0000000000ff'
        self.assertEqual(self.driver('wake', {'run': run}),
                         (1, {'error': 'Tembo has no run ' + run, 'next': 'start a new run'}))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.posts(), [])

    def test_codex_effort_reaches_the_host_as_its_reasoning_level(self):
        run = self.started(harness='codex', effort='high')
        self.assertEqual(self.host.sessions[run]['request']['agentOptions'], {'reasoningLevel': 'high'})

    def test_an_effort_tembo_does_not_document_starts_nothing(self):
        for harness, effort in (('claude-code', 'high'), ('codex', 'max'), ('codex', 'minimal')):
            code, out = self.driver('start', dict(START, harness=harness, effort=effort))
            self.assertEqual((code, out), (1, {
                'error': 'Tembo cannot set effort %s for harness %s' % (effort, harness), 'next': NO_EFFORT}))
        self.assertEqual((self.host.requests, self.notes()), ([], []))

    def test_inputs_off_the_schema_are_refused_before_any_request(self):
        for bad in (dict(START, token='kit-probe-not-a-login'), {k: v for k, v in START.items() if k != 'model'},
                    dict(START, ticket='7'), dict(START, repository='https://example.com/x'),
                    dict(START, effort='High')):
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
        self.assertEqual((code, out), (1, {'error': 'Tembo answered 401 to GET /v1/repositories',
                                           'next': "check your key and Tembo's status, then retry"}))
        run = self.started()
        for cmd in ('wake', 'stop'):
            self.assertNotIn('synthetic-session-value', json.dumps(self.driver(cmd, {'run': run})[1]))

    def test_no_driver_file_names_the_key_or_the_keychain(self):
        for folder, _, names in os.walk(HERE):
            for n in names:
                with open(os.path.join(folder, n), 'rb') as f:
                    lines = f.read().split(b'\n')
                rel = os.path.relpath(os.path.join(folder, n), HERE)
                for line in lines:
                    if rel == 'README.md' and b'openwiz-tembo' in line and b'_API_KEY' in line:
                        continue
                    self.assertNotIn(b'TEMBO' + b'_API_KEY', line, rel)
                    self.assertIsNone(KEYCHAIN_TOOLS_SPELLED_IN_PARTS.search(line), rel)

    def test_version_and_schema(self):
        self.assertEqual(self.driver('version'), (0, {'driver': 'tembo', 'records': ['openwiz:records v1'],
                                                       'can': ['start', 'wake', 'stop', 'effort']}))
        with open(os.path.join(ROOT, 'kernel', 'driver-kit', 'schema.json'), 'rb') as a, \
                open(os.path.join(HERE, 'schema.json'), 'rb') as b:
            self.assertEqual(a.read(), b.read())


if __name__ == '__main__':
    unittest.main()
