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
KEY = 'synthetic-capy-' + 'Kit0Value' * 2
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude-code',
         'model': 'claude-synthetic-1'}
PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill.'
WOKEN = 'You were woken: read the ticket again and carry on.'
NO_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
             "at the host's default")
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
KEYCHAIN_TOOLS_SPELLED_IN_PARTS = re.compile(rb'(?<![\w-])(secur' + rb'ity|secret' + rb'-tool)(?![\w-])')
KIT_PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
            "pass start: the run posted builder status note 2; effort: medium reached the kit's fake capy host",
            'pass wake: the run edited builder status note 2',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the capy '
            'key reached its host only from the key helper, in its header']


def module(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fake = module(os.path.join(HERE, 'fixtures', 'fake_capy.py'), 'fake_capy')


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
        self.env = dict(os.environ, KIT_TEST=self.mark, OPENWIZ_CAPY_POLL='0.01')
        self.use()

    def use(self, **kw):
        self.host = fake.FakeCapy(KEY, self.tracker, **kw)
        self.addCleanup(self.host.close)
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
            for line in out.values():
                self.assertTrue(isinstance(line, str) and 1 <= len(line) <= 300 and '\n' not in line, out)
        return p.returncode, out

    def refused(self, cmd, request, shows=None):
        code, out = self.driver(cmd, request)
        self.assertEqual(code, 1, (request, self.host.answers, out))
        if shows:
            self.assertIn(shows, out['error'])
        return out

    def started(self, **kw):
        code, out = self.driver('start', dict(START, **kw))
        self.assertEqual(code, 0, out)
        return out['run']

    def notes(self):
        with open(self.tracker) as f:
            return [c for c in json.load(f)['comments'] if 'state: working' in c['body']]

    def posts(self):
        return [p for m, p in self.host.calls() if m == 'POST']

    def test_kit_passes_all_five_on_the_fake_host(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site', '--ticket', '7',
                            '--harness', 'claude-code', '--model', 'claude-synthetic-1', '--tracker', self.tracker,
                            '--wait', '8'], env=dict(self.env, CAPY_PROJECT_ID='project_synthetic1'),
                           capture_output=True, text=True, timeout=300)
        self.assertEqual((p.stdout.splitlines(), p.stderr), (KIT_PASS, ''))
        self.assertEqual(p.returncode, 0)

    def test_every_request_reaches_the_host_with_the_key_header_only(self):
        run = self.started()
        self.driver('wake', {'run': run})
        self.driver('stop', {'run': run})
        self.assertTrue(self.host.requests)
        for method, path, body, auth in self.host.requests:
            self.assertEqual(auth, 'Bearer ' + KEY)
            self.assertNotIn(KEY, path + body.decode())

    def test_start_creates_one_thread_in_the_repository_project_on_the_harness_model(self):
        run = self.started()
        self.assertEqual(list(self.host.threads), [run])
        [sent] = self.host.bodies('POST', '/api/v1/threads')
        self.assertRegex(sent.pop('requestId'), UUID)
        self.assertEqual(sent, {'projectId': 'project_synthetic1', 'title': 'OpenWiz: example/site#7',
                                'message': PROMPT, 'model': {'modelId': 'anthropic/claude-synthetic-1'}})
        self.assertEqual(self.host.calls(), [('GET', '/api/v1/projects'), ('POST', '/api/v1/threads')])
        self.assertEqual(len(self.notes()), 1)
        run = self.started(harness='codex', model='gpt-synthetic-2', repository='example/other')
        self.assertEqual(self.host.threads[run]['create']['model'], {'modelId': 'openai/gpt-synthetic-2'})
        self.assertEqual(self.host.threads[run]['create']['projectId'], 'project_synthetic2')

    def test_start_takes_capy_project_id_else_the_project_listing_the_repository_else_refuses(self):
        self.use(projects=fake.PROJECTS[1:])
        code, out = self.driver('start', START)
        self.assertEqual((code, out), (1, {
            'error': 'no Capy project lists example/site',
            'next': 'add the repository to one Capy project (Settings, Projects & setup), or set CAPY_PROJECT_ID '
                    'to the project to run it in, then start again'}))
        self.use(projects=fake.PROJECTS * 2)
        self.assertEqual(self.driver('start', START)[1]['error'], 'more than one Capy project lists example/site')
        self.assertEqual(self.posts(), [])
        self.host.requests.clear()
        self.env['CAPY_PROJECT_ID'] = 'project_synthetic2'
        run = self.started()
        self.assertEqual(self.host.threads[run]['create']['projectId'], 'project_synthetic2')
        self.assertEqual(self.host.calls(), [('POST', '/api/v1/threads')])
        self.env['CAPY_PROJECT_ID'] = 'project synthetic"2'
        self.assertEqual(self.driver('start', START), (1, {'error': 'CAPY_PROJECT_ID is not a Capy project id',
                                                           'next': 'set CAPY_PROJECT_ID to a project id from '
                                                                   'Capy\'s Settings, Projects & setup, or unset it'}))
        self.assertEqual(len(self.host.requests), 1)

    def test_start_refuses_a_harness_capy_has_no_subscription_for(self):
        code, out = self.driver('start', dict(START, harness='gemini-cli'))
        self.assertEqual(out, {'error': 'harness gemini-cli is not one Capy runs for OpenWiz',
                               'next': 'use claude-code (or claude) or codex'})
        self.assertEqual(self.host.requests, [])

    def test_effort_reaches_the_host_as_the_model_reasoning_mode(self):
        run = self.started(effort='high')
        self.assertEqual(self.host.threads[run]['create']['model'],
                         {'modelId': 'anthropic/claude-synthetic-1', 'reasoningMode': 'high'})

    def test_an_effort_the_model_does_not_offer_is_the_exact_refusal_and_starts_nothing(self):
        code, out = self.driver('start', dict(START, effort='xhigh'))
        self.assertEqual((code, out), (1, {'error': 'Capy cannot run claude-code (model claude-synthetic-1) at '
                                                    'effort xhigh',
                                           'next': NO_EFFORT}))
        self.assertEqual((self.host.threads, self.notes()), ({}, []))
        code, out = self.driver('start', dict(START, model='claude-synthetic-9', effort='high'))
        self.assertEqual(out, {'error': 'Capy cannot run model anthropic/claude-synthetic-9 for this key',
                               'next': "pick a model Capy lists for your key (Settings, Models), or connect the "
                                       "subscription that serves it, then start again"})

    def test_a_lost_create_is_retried_with_the_same_request_id_and_starts_one_thread(self):
        self.use(lose_creates=1)
        run = self.started()
        first, second = self.host.bodies('POST', '/api/v1/threads')
        self.assertEqual(first, second)
        self.assertEqual(list(self.host.threads), [run])
        self.use(lose_creates=2)
        code, out = self.driver('start', START)
        self.assertEqual(out, {'error': 'Capy answered 503 to POST /api/v1/threads, so a thread may have started',
                               'next': 'archive the Capy thread titled OpenWiz: example/site#7 if it is there, '
                                       'then start again'})

    def test_wake_steers_a_message_into_the_same_thread_and_its_note_is_edited(self):
        run = self.started()
        self.host.requests.clear()
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.host.calls(), [('GET', '/api/v1/threads/' + run),
                                             ('POST', '/api/v1/threads/%s/message' % run)])
        self.assertEqual(self.host.threads[run]['messages'], [{'text': WOKEN, 'delivery': 'steer'}])
        self.assertEqual(len(self.notes()), 1)

    def test_stop_interrupts_then_archives_and_a_wake_after_it_is_refused(self):
        run = self.started()
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.posts(), ['/api/v1/threads/%s/interrupt' % run, '/api/v1/threads/%s/archive' % run])
        self.assertTrue(self.host.threads[run]['archived'])
        self.assertEqual(self.driver('wake', {'run': run}), (1, {'error': 'run %s is stopped' % run,
                                                                 'next': 'start a new run'}))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual((len(self.posts()), self.host.threads[run]['messages']), (2, []))

    def test_an_unknown_run_is_refused_by_wake_and_stop(self):
        for cmd in ('wake', 'stop'):
            self.assertEqual(self.driver(cmd, {'run': 'jam_01UNKNOWN'}),
                             (1, {'error': 'Capy has no run jam_01UNKNOWN', 'next': 'start a new run'}))
        self.assertEqual(self.posts(), [])

    def test_an_unreadable_or_mismatched_thread_read_refuses_wake_and_stop_before_any_write(self):
        run = self.started()
        t = self.host.threads[run]
        good = self.host._thread(t)
        for code, body in ((200, None), (200, {'archived': True}), (404, None), (404, {'_tag': 'capy/Unrelated'}),
                           (404, {'_tag': 'capy/ThreadNotFound', 'threadId': 'jam_other'}), (201, good),
                           (200, dict(good, id='jam_other')), (200, dict(good, archived='yes')),
                           (200, dict(good, status='paused')), (200, dict(good, status='archived')),
                           (200, dict(good, archived=True, status='working')), (200, dict(good, extra=1)),
                           (200, {k: v for k, v in good.items() if k != 'usage'})):
            self.host.answers[:] = [('GET', '/api/v1/threads/' + run, code, body)]
            for cmd in ('wake', 'stop'):
                self.assertNotEqual(self.refused(cmd, {'run': run}, run)['next'], 'start a new run')
        self.assertEqual(self.posts(), ['/api/v1/threads'])
        self.assertEqual((t['archived'], t['status'], t['messages'], t['interrupts']), (False, 'working', [], 0))

    def test_wake_and_stop_refuse_unless_capy_confirms_each_write(self):
        run = self.started()
        receipt = {'id': '01SYNTHETIC' + '0' * 15, 'deduped': False}
        for code, body in ((200, None), (200, {}), (200, dict(receipt, id='01SHORT')), (202, receipt),
                           (200, dict(receipt, deduped='no')), (200, dict(receipt, extra=1))):
            for cmd, route in (('wake', 'message'), ('stop', 'interrupt')):
                self.host.answers[:] = [('POST', '/api/v1/threads/%s/%s' % (run, route), code, body)]
                self.host.requests.clear()
                self.refused(cmd, {'run': run}, run)
                self.assertEqual(self.posts(), ['/api/v1/threads/%s/%s' % (run, route)])
        archived = dict(self.host._thread(self.host.threads[run]), automation=None, archived=True, status='archived')
        for body in (None, dict(archived, archived=False, status='idle'), dict(archived, id='jam_other'),
                     dict(archived, status='working'), {k: v for k, v in archived.items() if k != 'automation'}):
            self.host.answers[:] = [('POST', '/api/v1/threads/%s/archive' % run, 200, body)]
            self.refused('stop', {'run': run}, run)
        self.assertFalse(self.host.threads[run]['archived'])

    def test_a_project_list_off_its_documented_shape_is_refused_before_any_create(self):
        good, other = fake.PROJECTS
        for body in (None, {}, {'items': None}, {'items': [good], 'more': 1}, {'items': [good, None]},
                     {'items': [dict(good, repos=None)]}, {'items': [{k: v for k, v in good.items() if k != 'repos'}]},
                     {'items': [dict(good, id=7)]}, {'items': [dict(good, id='')]}, {'items': [dict(good, extra=1)]},
                     {'items': [dict(good, repos=[{'repoFullName': 'Example/Site'}])]},
                     {'items': [good, dict(other, repos='example/other')]}):
            self.host.answers[:] = [('GET', '/api/v1/projects', 200, body)]
            self.assertIn('CAPY_PROJECT_ID', self.refused('start', START)['next'])
        self.assertEqual(self.posts(), [])

    def test_a_create_receipt_off_its_shape_or_for_another_project_is_a_possible_start(self):
        run = self.started()
        good = self.host._thread(self.host.threads[run])
        for body, shows in ((dict(good, id='jam_other', projectId='project_other'), 'jam_other'), (None, None),
                            (dict(good, archived=True, status='archived'), run), (dict(good, id='x/y'), None),
                            ({'id': run}, run), (dict(good, status='paused'), run)):
            self.host.answers[:] = [('POST', '/api/v1/threads', 200, body)]
            out = self.refused('start', START, shows)
            self.assertIn('may have started', out['error'])
            self.assertIn('archive', out['next'])

    def test_an_effort_outside_capys_reasoning_modes_is_refused_before_any_request(self):
        for effort in ('ultra', 'extra-high', 'maximum'):
            self.assertEqual(self.driver('start', dict(START, effort=effort)), (1, {
                'error': 'Capy cannot run claude-code (model claude-synthetic-1) at effort ' + effort,
                'next': NO_EFFORT}))
        self.assertEqual(self.host.requests, [])

    def test_a_rejected_effort_needs_a_readable_model_list_to_say_the_model_cannot_set_it(self):
        default = {'modelId': fake.MODELS[0]['id'], 'source': 'org', 'skipped': []}
        for body in (None, {'items': None, 'default': default}, {'items': fake.MODELS},
                     {'items': [dict(fake.MODELS[0], reasoningModes=None)], 'default': default},
                     {'items': fake.MODELS + fake.MODELS[:1], 'default': default},
                     {'items': [dict(fake.MODELS[0], reasoningModes=['low', 7])], 'default': default}):
            self.host.answers[:] = [('GET', '/api/v1/models', 200, body)]
            self.assertNotEqual(self.refused('start', dict(START, effort='xhigh'), 'xhigh')['next'], NO_EFFORT)
        self.assertEqual(self.host.threads, {})

    def test_every_refusal_fits_d3_even_for_the_longest_repository_and_ticket(self):
        repo = 'o' * 100 + '/' + 'r' * 100
        self.refused('start', dict(START, repository=repo), repo)
        self.use(lose_creates=2)
        self.env['CAPY_PROJECT_ID'] = 'project_synthetic1'
        self.assertIn('may have started', self.refused('start', dict(START, repository=repo, ticket=10 ** 40))['error'])

    def test_inputs_off_the_schema_are_refused_before_any_request(self):
        for bad in (dict(START, token='kit-probe-not-a-login'), {k: v for k, v in START.items() if k != 'model'},
                    dict(START, ticket='7'), dict(START, repository='https://example.com/x'),
                    dict(START, effort='High')):
            self.assertEqual(self.driver('start', bad)[0], 1)
        for bad in ({'run': '../x'}, {'run': 'jam_01?x=1'}, {'run': 'jam_01', 'x': 1}, {'run': 'a' * 101}):
            for cmd in ('wake', 'stop'):
                self.assertEqual(self.driver(cmd, bad)[0], 1)
        self.assertEqual(self.host.requests, [])

    def test_a_host_error_is_a_fixed_refusal(self):
        self.use(served_key='synthetic-wrong-' + 'Kit0Value' * 2)
        code, out = self.driver('start', START)
        self.assertEqual((code, out), (1, {'error': 'Capy answered 401 to GET /api/v1/projects',
                                           'next': "check your key and Capy's status, then retry"}))
        self.assertNotIn('Unauthorized', json.dumps(out))

    def test_no_driver_file_names_the_key_or_the_keychain(self):
        with open(os.path.join(ROOT, 'kernel', 'driver-kit', 'hosts.json')) as f:
            host = json.load(f)['capy']
        names = [host['variable'].encode(), host['keychain'].encode()]
        with open(os.path.join(HERE, 'README.md'), 'rb') as f:
            [key_line] = [line for line in f.read().split(b'\n') if all(n in line for n in names)]
        for folder, _, files in os.walk(HERE):
            for n in files:
                with open(os.path.join(folder, n), 'rb') as f:
                    lines = f.read().split(b'\n')
                rel = os.path.relpath(os.path.join(folder, n), HERE)
                for line in lines:
                    if rel == 'README.md' and line == key_line:
                        continue
                    for name in names:
                        self.assertNotIn(name, line, rel)
                    self.assertIsNone(KEYCHAIN_TOOLS_SPELLED_IN_PARTS.search(line), rel)

    def test_version_lists_effort_and_the_schema_is_the_kernels(self):
        self.assertEqual(self.driver('version'), (0, {'driver': 'capy', 'records': ['openwiz:records v1'],
                                                       'can': ['start', 'wake', 'stop', 'effort']}))
        with open(os.path.join(ROOT, 'kernel', 'driver-kit', 'schema.json'), 'rb') as a, \
                open(os.path.join(HERE, 'schema.json'), 'rb') as b:
            self.assertEqual(a.read(), b.read())


if __name__ == '__main__':
    unittest.main()
