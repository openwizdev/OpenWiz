#!/usr/bin/env python3
import importlib.machinery, importlib.util, json, os, secrets, shutil, signal, subprocess, sys, tempfile, time, unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT, DRIVER = os.path.join(HERE, '..', '..'), os.path.join(HERE, 'driver')
KIT = os.path.join(ROOT, 'kernel', 'driver-kit', 'kit.py')
KEY = 'synthetic-capy-' + 'Kit0Value' * 2
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude-code', 'model': 'claude-synthetic-1'}
PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill.'
WOKEN = 'You were woken: read the ticket again and carry on.'
NO_EFFORT = "this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default"
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'

def module(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

fake = module(os.path.join(HERE, 'fixtures', 'fake_capy.py'), 'fake_capy')

class Driver(unittest.TestCase):
    def setUp(self):
        self.folder, self.mark = tempfile.mkdtemp(), secrets.token_hex(8)
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.tracker = fake.tracker(self.folder)
        self.env = dict(os.environ, KIT_TEST=self.mark, OPENWIZ_CAPY_POLL='0.01', OPENWIZ_CAPY_STATE=os.path.join(self.folder, 'state'))
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

    def test_kit_passes_for_both_supported_and_refused_effort(self):
        for word, proof in (('medium', 'medium reached'), ('ultra', 'refused ultra with the refusal text')):
            with self.subTest(effort=word):
                p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site', '--ticket', '7',
                                    '--harness', 'claude-code', '--model', 'claude-synthetic-1', '--effort', word,
                                    '--tracker', self.tracker, '--wait', '8'], env=dict(self.env, CAPY_PROJECT_ID='project_synthetic1'),
                                   capture_output=True, text=True, timeout=300)
                self.assertEqual((p.returncode, p.stderr, [line.split(':')[0] for line in p.stdout.splitlines()]),
                                 (0, '', ['pass version', 'pass start', 'pass wake', 'pass stop', 'pass token']), p.stdout)
                self.assertTrue(proof in p.stdout and 'key reached its host only from the key helper, in its header' in p.stdout, p.stdout)

    def test_start_creates_one_thread_in_the_repository_project_on_the_harness_model(self):
        run = self.started(effort='high')
        [sent] = self.host.bodies('POST', '/api/v1/threads')
        self.assertRegex(sent.pop('requestId'), UUID)
        self.assertEqual(sent, {'projectId': 'project_synthetic1', 'title': 'OpenWiz: example/site#7', 'message': PROMPT,
                                'model': {'modelId': 'anthropic/claude-synthetic-1', 'reasoningMode': 'high'}})
        self.assertEqual((self.host.calls(), len(self.notes())), ([('GET', '/api/v1/projects'), ('POST', '/api/v1/threads')], 1))
        run = self.started(harness='codex', model='gpt-synthetic-2', repository='example/other')
        self.assertEqual((self.host.threads[run]['create']['model'], self.host.threads[run]['create']['projectId']),
                         ({'modelId': 'openai/gpt-synthetic-2'}, 'project_synthetic2'))

    def test_start_takes_capy_project_id_else_the_project_listing_the_repository_else_refuses(self):
        self.use(projects=fake.PROJECTS[1:])
        self.assertIn('CAPY_PROJECT_ID', self.refused('start', START, 'no Capy project lists example/site')['next'])
        self.use(projects=fake.PROJECTS * 2)
        self.refused('start', START, 'more than one Capy project lists example/site')
        self.assertEqual(self.posts(), [])
        self.host.requests.clear()
        self.env['CAPY_PROJECT_ID'] = 'project_synthetic2'
        run = self.started()
        self.assertEqual((self.host.threads[run]['create']['projectId'], self.host.calls()),
                         ('project_synthetic2', [('POST', '/api/v1/threads')]))
        self.env['CAPY_PROJECT_ID'] = 'project synthetic"2'
        self.refused('start', START, 'CAPY_PROJECT_ID is not a Capy project id')
        self.assertEqual(len(self.host.requests), 1)

    def test_start_refuses_a_harness_capy_has_no_subscription_for(self):
        self.refused('start', dict(START, harness='gemini-cli'), 'harness gemini-cli')
        for change in ({'harness': 'gemini-cli', 'effort': 'high'}, {'effort': 'ultra'}):
            self.assertEqual(self.refused('start', dict(START, **change), 'at effort ' + change['effort'])['next'], NO_EFFORT)
        self.assertEqual(self.host.requests, [])

    def test_a_capy_qualified_model_is_kept_and_only_a_bare_one_gets_the_harness_prefix(self):
        run = self.started(model='anthropic/claude-synthetic-1')
        self.assertEqual(self.host.threads[run]['create']['model'], {'modelId': 'anthropic/claude-synthetic-1'})
        self.host.requests.clear()
        self.refused('start', dict(START, model='openai/gpt-synthetic-2'), 'not an anthropic model')
        self.assertEqual(self.host.requests, [])

    def test_an_effort_the_model_does_not_offer_is_the_exact_refusal_and_starts_nothing(self):
        self.assertEqual(self.refused('start', dict(START, effort='xhigh'), 'at effort xhigh')['next'], NO_EFFORT)
        self.assertEqual((self.host.threads, self.notes()), ({}, []))
        self.assertIn('Settings, Models', self.refused('start', dict(START, model='claude-synthetic-9', effort='high'), 'claude-synthetic-9')['next'])

    def test_a_lost_create_is_retried_with_the_same_request_id_and_starts_one_thread(self):
        self.use(lose_creates=1)
        run = self.started()
        first, second = self.host.bodies('POST', '/api/v1/threads')
        self.assertEqual((first, list(self.host.threads)), (second, [run]))
        self.use(lose_creates=2)
        out = self.refused('start', START, 'a thread may have started')
        self.assertIn('archive the Capy thread titled OpenWiz: example/site#7', out['next'])
        self.use(lose_creates=1, replay=(401, fake.tag('Unauthorized')))
        self.assertEqual((self.driver('start', START)[1], len(self.host.threads)), (out, 1))

    def test_a_start_the_key_helper_never_sent_keeps_the_helpers_setup_advice(self):
        self.use(served_key='')
        self.env['CAPY_PROJECT_ID'] = 'project_synthetic1'
        out = self.refused('start', START, "the key helper refused: the kit's fake host gave no test key")
        self.assertTrue(out['next'].startswith('unset OPENWIZ_HOSTKEY_TEST_ORIGIN') and not self.host.requests, out)

    def test_lost_create_replies_leave_time_for_recovery_before_the_kit_timeout(self):
        capy = module(DRIVER, 'capy_driver')
        capy.STATE, capy.POLL = self.env['OPENWIZ_CAPY_STATE'], 3
        clock, creates = mock.Mock(), []
        clock.monotonic.return_value = 0
        def advance(seconds):
            clock.monotonic.return_value += seconds
        def helper(argv, *, input, timeout, **_):
            sent = json.loads(input)
            status, body = self.host.route(sent['method'], sent['path'], sent.get('body'))
            if sent['method'] == 'GET':
                advance(20)
                return subprocess.CompletedProcess(argv, 0, json.dumps({'status': status, 'body': body}))
            creates.append(sent['body']['requestId'])
            advance(timeout)
            raise subprocess.TimeoutExpired(argv, timeout)
        clock.sleep.side_effect = advance
        with mock.patch.dict(os.environ, self.env, clear=True), mock.patch.object(capy, 'time', clock), \
                mock.patch.object(capy.subprocess, 'run', side_effect=helper):
            os.environ.pop('CAPY_PROJECT_ID', None)
            with self.assertRaises(capy.Refused) as failure:
                capy.create(START)
        self.assertLess(clock.monotonic(), 120)
        self.assertEqual((creates[0], len(creates), len(self.host.threads)), (creates[1], 2, 1))
        self.assertIn('a thread may have started', failure.exception.args[0])
        self.assertIn('archive the Capy thread titled OpenWiz: example/site#7', failure.exception.args[1])

    def test_a_rate_limited_create_waits_the_seconds_capy_asks_then_sends_it_once_more(self):
        self.use(throttle=[1])
        began, run = time.monotonic(), self.started()
        self.assertGreaterEqual(time.monotonic() - began, 1)
        first, second = self.host.bodies('POST', '/api/v1/threads')
        self.assertEqual((first, list(self.host.threads)), (second, [run]))
        self.use(throttle=[600])
        self.refused('start', START, 'asked to wait 600 seconds')
        self.assertEqual((len(self.host.bodies('POST', '/api/v1/threads')), self.host.threads), (1, {}))
        self.use(throttle=[0, 600])
        self.assertIn('600 seconds', self.refused('start', START, 'twice')['next'])
        self.assertEqual(len(self.host.bodies('POST', '/api/v1/threads')), 2)

    def test_wake_steers_the_same_thread_until_it_is_stopped(self):
        run = self.started()
        path = '/api/v1/threads/%s/message' % run
        self.host.answers[:] = [('POST', path, 403, fake.tag('Forbidden'))]
        self.refused('wake', {'run': run}, '403')
        self.host.answers.clear()
        self.host.requests.clear()
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.host.calls(), [('GET', '/api/v1/threads/' + run), ('POST', path)])
        [sent] = self.host.threads[run]['messages']
        message = sent.copy()
        self.assertRegex(message.pop('clientKey'), UUID)
        self.assertEqual((message, len(self.notes())), ({'text': WOKEN, 'delivery': 'steer'}, 1))
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.posts(), ['/api/v1/threads/%s/interrupt' % run, '/api/v1/threads/%s/archive' % run])
        self.assertTrue(self.host.threads[run]['archived'])
        self.assertEqual(self.refused('wake', {'run': run}, 'is stopped')['next'], 'start a new run')
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual((len(self.posts()), self.host.threads[run]['messages']), (2, [sent]))

    def test_stop_stays_unconfirmed_until_a_late_wake_is_accounted_for(self):
        run = self.started()
        request, path = {'run': run}, '/api/v1/threads/%s/message' % run
        self.host.answers[:] = [('POST', path, None, None)]
        self.refused('wake', request)
        [late] = self.host.bodies('POST', path)
        self.refused('stop', request, 'unconfirmed')
        self.assertTrue(self.host.threads[run]['archived'])
        self.refused('stop', request, 'unconfirmed')
        self.refused('wake', request, 'stopped')
        with mock.patch.object(self, 'env', dict(self.env, OPENWIZ_CAPY_STATE=os.path.join(self.folder, 'second-controller'))):
            self.refused('stop', request, 'controller')
        self.host.answers.clear()
        self.host.route('POST', path, late)
        self.assertFalse(self.host.threads[run]['archived'])
        self.assertEqual(self.driver('stop', request), (0, {'run': run, 'stopped': True}))
        self.assertEqual((self.host.threads[run]['archived'], self.host.bodies('POST', path)), (True, [late]))

    def test_a_wake_that_never_arrives_settles_on_retry_wake_or_bounded_stop(self):
        run = self.started()
        req, path = {'run': run}, '/api/v1/threads/%s/message' % run
        self.host.answers[:] = [('POST', path, 503, {'_tag': 'synthetic/Unavailable'})]
        self.refused('wake', req, 'unconfirmed')
        [first] = self.host.bodies('POST', path)
        self.host.answers[:] = [('POST', path, 429, fake.tag('RateLimited', retryAfterSeconds=5))]
        self.refused('wake', req, 'rate-limited')
        self.host.answers.clear()
        self.assertEqual(self.driver('wake', req), (0, {'run': run, 'woke': True}))
        self.assertEqual((self.host.bodies('POST', path), self.host.threads[run]['messages']), ([first, first, first], [first]))
        self.assertEqual(self.driver('stop', req), (0, {'run': run, 'stopped': True}))
        run2 = self.started()
        req2, path2 = {'run': run2}, '/api/v1/threads/%s/message' % run2
        self.host.answers[:] = [('POST', path2, None, None)]
        self.refused('wake', req2, 'unconfirmed')
        [sent] = self.host.bodies('POST', path2)
        self.host.answers.clear()
        self.host.route('POST', path2, sent)
        self.assertEqual(self.driver('wake', req2), (0, {'run': run2, 'woke': True}))
        self.assertEqual((self.host.threads[run2]['messages'], self.driver('stop', req2)), ([sent], (0, {'run': run2, 'stopped': True})))
        run3 = self.started()
        req3, path3, msgs3 = {'run': run3}, '/api/v1/threads/%s/message' % run3, '/api/v1/threads/%s/messages' % run3
        self.host.answers[:] = [('POST', path3, 503, {'_tag': 'synthetic/Unavailable'})]
        self.refused('wake', req3, 'unconfirmed')
        self.refused('stop', req3, 'unconfirmed')
        self.assertTrue(self.host.threads[run3]['archived'])
        with mock.patch.object(self, 'env', dict(self.env, OPENWIZ_CAPY_WAKE_SETTLE='0.05')):
            time.sleep(0.06)
            for code, body in ((500, {'_tag': 'synthetic/Down'}), (200, {'items': [], 'cursor': 'evt_stall', 'beforeCursor': None})):
                self.host.answers[:] = [('GET', msgs3, code, body)]
                self.refused('stop', req3, 'unconfirmed')
            self.host.answers.clear()
            self.assertEqual((self.driver('stop', req3), self.driver('stop', req3)), ((0, {'run': run3, 'stopped': True}),) * 2)

    def test_stop_follows_any_opaque_transcript_cursor_to_settle_a_late_wake(self):
        run = self.started()
        req, path, msgs = {'run': run}, '/api/v1/threads/%s/message' % run, '/api/v1/threads/%s/messages' % run
        self.host.answers[:] = [('POST', path, None, None)]
        self.refused('wake', req, 'unconfirmed')
        [late] = self.host.bodies('POST', path)
        self.host.answers.clear()
        self.host.route('POST', path, late)
        item = {'id': '01SYNTHETIC' + '0' * 15, 'source': 'user', 'text': WOKEN, 'clientKey': late['clientKey']}
        self.host.answers[:] = [('GET', msgs + r'\?after=evt_page-2', 200, {'items': [item], 'cursor': None, 'beforeCursor': None}),
                                ('GET', msgs, 200, {'items': [], 'cursor': 'evt_page-2', 'beforeCursor': None})]
        self.assertEqual((self.driver('stop', req), self.host.threads[run]['archived']), ((0, {'run': run, 'stopped': True}), True))

    def test_a_stop_during_a_wake_of_the_same_run_waits_for_it_and_leaves_the_run_stopped(self):
        run = self.started()
        self.host.hold = ('GET', '/api/v1/threads/' + run)
        def begin(cmd):
            p = subprocess.Popen([DRIVER, cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.env, text=True)
            p.stdin.write(json.dumps({'run': run}))
            p.stdin.close()
            return p
        state = self.env['OPENWIZ_CAPY_STATE']
        with begin('wake') as wake:
            try:
                self.assertTrue(self.host.held.wait(30))
                self.env['OPENWIZ_CAPY_STATE'] = os.path.join(self.folder, 'second-controller')
                for cmd in ('stop', 'wake'):
                    self.refused(cmd, {'run': run}, 'controller')
                self.assertEqual(self.posts(), ['/api/v1/threads'])
                self.env['OPENWIZ_CAPY_STATE'] = state
                with begin('stop') as stop:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        stop.wait(1.5)
                    self.host.release.set()
                    for p, key in ((wake, 'woke'), (stop, 'stopped')):
                        self.assertEqual((json.loads(p.stdout.read()), p.wait(60)), ({'run': run, key: True}, 0))
            finally:
                self.host.release.set()
                self.env['OPENWIZ_CAPY_STATE'] = state
        self.assertTrue(self.host.threads[run]['archived'])
        self.env['OPENWIZ_CAPY_STATE'] = self.tracker
        self.host.requests.clear()
        for cmd in ('wake', 'stop'):
            self.assertEqual(self.driver(cmd, {'run': run})[1]['error'], 'the driver cannot lock run ' + run)
        self.assertEqual(self.host.requests, [])

    def test_fields_capy_adds_to_its_answers_change_nothing(self):
        self.use(widen={'addedLater': [1]})
        run = self.started()
        self.assertEqual((self.driver('wake', {'run': run}), self.driver('stop', {'run': run})),
                         ((0, {'run': run, 'woke': True}), (0, {'run': run, 'stopped': True})))
        self.assertEqual(self.driver('start', dict(START, effort='xhigh'))[1]['next'], NO_EFFORT)

    def test_an_unreadable_or_mismatched_thread_read_refuses_wake_and_stop_before_any_write(self):
        for cmd in ('wake', 'stop'):
            self.assertEqual(self.refused(cmd, {'run': 'jam_01UNKNOWN'}, 'Capy has no run')['next'], 'start a new run')
        run = self.started()
        t = self.host.threads[run]
        good = self.host._thread(t)
        for code, body in ((200, None), (200, {'archived': True}), (404, None), (404, {'_tag': 'capy/Unrelated'}),
                           (404, {'_tag': 'capy/ThreadNotFound', 'threadId': 'jam_other'}), (201, good),
                           (200, dict(good, id='jam_other')), (200, dict(good, archived='yes')),
                           (200, dict(good, status='paused')), (200, dict(good, status='archived')),
                           (200, dict(good, archived=True, status='working')),
                           (200, {k: v for k, v in good.items() if k != 'usage'})):
            self.host.answers[:] = [('GET', '/api/v1/threads/' + run, code, body)]
            for cmd in ('wake', 'stop'):
                self.assertNotEqual(self.refused(cmd, {'run': run}, run)['next'], 'start a new run')
        self.assertEqual((self.posts(), t['archived'], t['status'], t['messages'], t['interrupts']),
                         (['/api/v1/threads'], False, 'working', [], 0))

    def test_wake_and_stop_refuse_unless_capy_confirms_each_write(self):
        receipt = {'id': '01SYNTHETIC' + '0' * 15, 'deduped': False}
        for code, body in ((200, None), (200, {}), (200, dict(receipt, id='01SHORT')), (202, receipt), (200, dict(receipt, deduped='no'))):
            for cmd, route in (('wake', 'message'), ('stop', 'interrupt')):
                run = self.started()
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
        for body in (None, {}, {'items': None}, {'items': [good, None]}, {'items': [dict(good, repos=None)]},
                     {'items': [{k: v for k, v in good.items() if k != 'repos'}]}, {'items': [dict(good, id=7)]},
                     {'items': [dict(good, id='')]}, {'items': [dict(good, repos=[{'repoFullName': 'Example/Site'}])]},
                     {'items': [good, dict(other, repos='example/other')]}):
            self.host.answers[:] = [('GET', '/api/v1/projects', 200, body)]
            self.assertIn('CAPY_PROJECT_ID', self.refused('start', START)['next'])
        self.assertEqual(self.posts(), [])

    def test_a_create_receipt_off_its_shape_or_for_another_project_is_a_possible_start(self):
        run = self.started()
        good = self.host._thread(self.host.threads[run])
        for body, shows in ((dict(good, id='jam_other', projectId='project_other'), 'jam_other'), (None, None),
                            (dict(good, archived=True, status='archived'), run), (dict(good, id='x/y'), None),
                            ({'id': run}, run), (dict(good, status='paused'), run), (dict(good, projectId=None), run)):
            self.host.answers[:] = [('POST', '/api/v1/threads', 200, body)]
            out = self.refused('start', START, shows)
            self.assertTrue('may have started' in out['error'] and 'archive' in out['next'], out)

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
                    dict(START, effort='High'), dict(START, model='m' * 101)):
            self.assertEqual(self.driver('start', bad)[0], 1)
        for bad in ({'run': '../x'}, {'run': 'jam_01?x=1'}, {'run': 'jam_01', 'x': 1}, {'run': 'a' * 101}):
            for cmd in ('wake', 'stop'):
                self.assertEqual(self.driver(cmd, bad)[0], 1)
        self.assertEqual(self.host.requests, [])

if __name__ == '__main__':
    unittest.main()
