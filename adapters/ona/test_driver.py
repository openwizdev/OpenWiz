#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import os
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
KEY = 'synthetic-ona-' + 'Kit0Value' * 2
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'codex',
         'model': 'gpt-6.1-sol'}
PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill.'
WOKEN = 'You were woken: read the ticket again and carry on.'
AGENT = '/api/gitpod.v1.AgentService/'
ENVIRONMENT = '/api/gitpod.v1.EnvironmentService/'
UUID_ONE = '00000000-0000-4000-8000-0000000000bb'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
NO_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run "
             "it at the host's default")
KIT_PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
            "pass start: the run posted builder status note 2; effort: medium reached the kit's fake ona host",
            'pass wake: the run edited builder status note 2',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the ona '
            'key reached its host only from the key helper, in its header']


def module(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fake = module(os.path.join(HERE, 'fixtures', 'fake_ona.py'), 'fake_ona')


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
        self.use()

    def use(self, **kw):
        self.host = fake.FakeOna(KEY, self.tracker, **kw)
        self.addCleanup(self.host.close)
        self.env = dict(os.environ, KIT_TEST=self.mark, OPENWIZ_HOSTKEY_TEST_ORIGIN=self.host.origin)

    def tearDown(self):
        if not os.path.isdir('/proc'):
            return
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

    def kit(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site', '--ticket', '7',
                            '--harness', 'codex', '--model', 'gpt-6.1-sol', '--tracker', self.tracker,
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
        self.assertEqual(len(self.host.requests), 7)
        for method, path, body, auth in self.host.requests:
            self.assertEqual((method, auth), ('POST', 'Bearer ' + KEY))
            self.assertNotIn(KEY, path + body.decode())

    def test_start_starts_codex_on_the_repository_then_sends_the_prompt(self):
        run = self.started()
        self.assertRegex(run, UUID)
        self.assertEqual(self.host.calls(), [AGENT + 'StartAgent', AGENT + 'SendToAgentExecution'])
        self.assertEqual(self.host.bodies('StartAgent'), [{
            'agentId': '00000000-0000-0000-0000-000000007800',
            'codeContext': {'contextUrl': {'url': 'https://github.com/example/site'}},
            'name': 'OpenWiz: example/site#7',
            'codexSettings': {'model': 'CODEX_OPEN_AI_MODEL_GPT_6_1_SOL'}}])
        [sent] = self.host.bodies('SendToAgentExecution')
        self.assertEqual(set(sent), {'agentExecutionId', 'userInput'})
        self.assertEqual(sent['agentExecutionId'], run)
        self.assertRegex(sent['userInput']['id'], UUID)
        self.assertEqual(sent['userInput']['inputs'], [{'text': {'content': PROMPT}}])
        self.assertEqual(len(self.notes()), 1)

    def test_models_map_to_ona_codex_models_and_others_are_refused(self):
        for model, value in (('gpt-5.5', 'GPT_5_5'), ('gpt-6-sol', 'GPT_6_SOL'), ('gpt-5.6-terra', 'GPT_5_6_TERRA'),
                             ('GPT-6-Luna', 'GPT_6_LUNA')):
            self.started(model=model)
            self.assertEqual(self.host.bodies('StartAgent')[-1]['codexSettings'],
                             {'model': 'CODEX_OPEN_AI_MODEL_' + value})
        self.host.requests.clear()
        for model in ('gpt-9', 'opus', 'gpt-6.1-sol-x', 'gpt_6_sol'):
            code, out = self.driver('start', dict(START, model=model))
            self.assertEqual((code, out['error']), (1, 'model %s is not a Codex model Ona offers' % model))
        self.assertEqual(self.host.requests, [])

    def test_only_codex_runs(self):
        for harness in ('claude-code', 'claude', 'gemini-cli'):
            code, out = self.driver('start', dict(START, harness=harness))
            self.assertEqual(code, 1)
            self.assertEqual(out, {'error': 'harness %s is not one Ona runs through its API' % harness,
                                   'next': 'use harness codex'})
        self.assertEqual(self.host.requests, [])

    def test_another_harness_with_effort_gets_the_exact_effort_refusal(self):
        for harness, effort in (('claude-code', 'medium'), ('gemini-cli', 'high')):
            code, out = self.driver('start', dict(START, harness=harness, effort=effort))
            self.assertEqual((code, out), (1, {'error': 'Ona cannot set effort %s for harness %s' % (effort, harness),
                                               'next': NO_EFFORT}))
        self.assertEqual(self.host.requests, [])

    def test_effort_reaches_the_host_as_codex_reasoning_effort(self):
        for effort, value in (('low', 'LOW'), ('medium', 'MEDIUM'), ('high', 'HIGH'),
                              ('xhigh', 'EXTRA_HIGH'), ('max', 'MAX'), ('ultra', 'ULTRA')):
            want = 'CODEX_REASONING_EFFORT_' + value
            run = self.started(effort=effort)
            self.assertEqual(self.host.bodies('StartAgent')[-1]['codexSettings'],
                             {'model': 'CODEX_OPEN_AI_MODEL_GPT_6_1_SOL', 'reasoningEffort': want})
            self.assertEqual(self.host.runs[run]['effort'], want)

    def test_long_repository_bounds_display_name_and_keeps_full_context_and_prompt(self):
        repo = 'example/' + 'a' * 82
        self.started(repository=repo)
        [start] = self.host.bodies('StartAgent')
        self.assertLessEqual(len(start['name']), 100)
        self.assertEqual(start['codeContext'], {'contextUrl': {'url': 'https://github.com/' + repo}})
        [sent] = self.host.bodies('SendToAgentExecution')
        self.assertEqual(sent['userInput']['inputs'],
                         [{'text': {'content': 'Build the ticket: %s#7, with the build-ticket skill.' % repo}}])

    def test_a_dropped_start_connection_directs_the_user_to_check_ona_before_retrying(self):
        self.host.faults = {'StartAgent': (fake.DROP, None, True)}
        code, out = self.driver('start', START)
        self.assertEqual((code, out['next']), (1, 'look for a new OpenWiz run in Ona, stop it, then retry'))
        self.assertEqual((len(self.host.runs), self.host.calls()), (1, [AGENT + 'StartAgent']))

    def test_no_effort_sends_none(self):
        self.started()
        self.assertNotIn('reasoningEffort', self.host.bodies('StartAgent')[0]['codexSettings'])

    def test_an_effort_ona_has_no_value_for_is_refused_and_starts_nothing(self):
        for effort in ('minimal', 'extra-high', 'none'):
            code, out = self.driver('start', dict(START, effort=effort))
            self.assertEqual((code, out), (1, {'error': 'Ona cannot set effort %s for harness codex' % effort,
                                               'next': NO_EFFORT}))
        self.assertEqual(self.host.requests, [])

    def test_a_refused_start_sends_nothing_more(self):
        self.use(refuse_efforts=('CODEX_REASONING_EFFORT_ULTRA',))
        code, out = self.driver('start', dict(START, effort='ultra'))
        self.assertEqual((code, out), (1, {'error': 'Ona answered 403 to POST %sStartAgent' % AGENT,
                                           'next': "check your key and Ona's status, then retry"}))
        self.assertEqual((self.host.calls(), self.host.runs), ([AGENT + 'StartAgent'], {}))

    def test_a_lost_prompt_names_its_run_so_stop_can_end_it(self):
        self.use(lose_send=True)
        code, out = self.driver('start', START)
        [run] = self.host.runs
        self.assertEqual((code, out), (1, {
            'error': 'run %s may have started: Ona answered 503 to POST %sSendToAgentExecution' % (run, AGENT),
            'next': 'stop run %s with `driver stop`, then start again' % run}))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.host.runs[run]['phase'], 'PHASE_STOPPED')

    def test_wake_sends_to_the_same_execution_once_its_turn_has_finished(self):
        run = self.started()
        self.assertEqual(self.host.runs[run]['phase'], 'PHASE_WAITING_FOR_INPUT')
        self.host.requests.clear()
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.host.calls(), [AGENT + 'GetAgentExecution', AGENT + 'SendToAgentExecution'])
        [sent] = self.host.bodies('SendToAgentExecution')
        self.assertEqual((sent['agentExecutionId'], sent['userInput']['inputs']),
                         (run, [{'text': {'content': WOKEN}}]))
        self.assertEqual(self.host.runs[run]['messages'], [PROMPT, WOKEN])
        [note] = self.notes()
        self.assertIn('step: woke and read the ticket again', note['body'])

    def test_wake_of_a_running_execution_queues_the_message(self):
        self.use(idle_phase='PHASE_RUNNING')
        run = self.started()
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.host.runs[run]['messages'], [PROMPT, WOKEN])

    def test_stop_ends_the_execution_and_its_environment_and_wake_after_is_refused(self):
        run = self.started()
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        env = self.host.runs[run]['environment']
        self.assertEqual(self.host.calls(), [AGENT + 'GetAgentExecution', AGENT + 'StopAgentExecution',
                                             '/api/gitpod.v1.EnvironmentService/StopEnvironment'])
        self.assertEqual(json.loads(self.host.requests[-1][2]), {'environmentId': env})
        self.assertEqual((self.host.runs[run]['phase'], self.host.environments[env]),
                         ('PHASE_STOPPED', 'ENVIRONMENT_PHASE_STOPPED'))
        code, out = self.driver('wake', {'run': run})
        self.assertEqual((code, out['error']), (1, 'run %s is stopped' % run))
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertNotIn(AGENT + 'StopAgentExecution', self.host.calls())
        self.assertEqual(self.host.runs[run]['messages'], [PROMPT])

    def test_unknown_run(self):
        run = '00000000-0000-4000-8000-0000000000ff'
        code, out = self.driver('wake', {'run': run})
        self.assertEqual((code, out['error']), (1, 'Ona has no run %s' % run))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.host.calls(), [AGENT + 'GetAgentExecution'] * 2)

    def refused_with(self, cmd, run, sent=()):
        self.host.requests.clear()
        code, out = self.driver(cmd, {'run': run})
        self.assertEqual(code, 1, out)
        self.assertIn(run, out['error'])
        self.assertIn(run, out['next'])
        for method in sent:
            self.assertNotIn(method, self.host.calls())
        return out

    def test_a_lookup_off_its_documented_shape_is_refused_before_wake_or_stop_acts(self):
        other = '00000000-0000-4000-8000-0000000000aa'
        for answer in ((200, b'<html>ok</html>'), (200, []), (200, {}), (200, b'null'), (200, b''),
                       (200, {'agentExecution': []}), (200, {'agentExecution': {'id': other, 'status': {}}}),
                       (200, {'agentExecution': {'status': {'phase': 'PHASE_RUNNING'}}}),
                       (404, b'<html>gone</html>'), (404, {}), (404, {'code': 'unimplemented'}),
                       (404, {'code': ['not_found']}), (500, {'code': 'internal'}), (201, {})):
            self.host.faults.clear()
            run = self.started()
            self.host.faults['GetAgentExecution'] = answer + (False,)
            self.refused_with('wake', run, [AGENT + 'SendToAgentExecution'])
            self.refused_with('stop', run, [AGENT + 'StopAgentExecution', ENVIRONMENT + 'StopEnvironment'])
            self.assertEqual(self.host.runs[run]['messages'], [PROMPT], answer)
            self.assertEqual(self.host.runs[run]['phase'], 'PHASE_WAITING_FOR_INPUT', answer)

    def test_a_phase_ona_does_not_document_is_refused_before_wake_or_stop_acts(self):
        for phase in ('PHASE_UNSPECIFIED', 'PHASE_SOMETHING_NEW', None, 3, fake.DROP):
            run = self.started()
            self.host.status_patch = {'phase': phase}
            self.refused_with('wake', run, [AGENT + 'SendToAgentExecution'])
            self.refused_with('stop', run, [AGENT + 'StopAgentExecution', ENVIRONMENT + 'StopEnvironment'])
            self.host.status_patch = {}
            self.assertEqual(self.host.runs[run]['messages'], [PROMPT], phase)
        self.host.status_patch = {'phase': 'PHASE_RUNNING'}
        self.host.faults['GetAgentExecution'] = (200, {'agentExecution': {'id': run, 'status': []}}, False)
        self.refused_with('wake', run, [AGENT + 'SendToAgentExecution'])

    def test_an_unreadable_write_acknowledgement_is_refused_with_the_run(self):
        for answer in ((200, b'null'), (200, b'<html>ok</html>'), (200, []), (200, b''), (201, {}), (204, b'')):
            run = self.started()
            self.host.faults['SendToAgentExecution'] = answer + (True,)
            self.refused_with('wake', run)
            self.host.faults = {'StopAgentExecution': answer + (False,)}
            self.refused_with('stop', run)
            self.assertEqual(self.host.runs[run]['phase'], 'PHASE_WAITING_FOR_INPUT', answer)
            self.host.faults = {'SendToAgentExecution': answer + (True,)}
            self.host.runs.clear()
            code, out = self.driver('start', START)
            [run] = self.host.runs
            self.assertEqual((code, out['error'].startswith('run %s may have started: ' % run)), (1, True), answer)
            self.assertIn(run, out['next'])
            self.host.faults = {}

    def test_an_unreadable_start_acknowledgement_starts_nothing_more(self):
        for answer in ((200, b'null'), (200, b'<html>ok</html>'), (201, {'agentExecutionId': UUID_ONE})):
            self.host.faults = {'StartAgent': answer + (False,)}
            self.host.requests.clear()
            code, out = self.driver('start', START)
            self.assertEqual(code, 1, answer)
            self.assertEqual(self.host.calls(), [AGENT + 'StartAgent'])

    def test_environment_data_off_its_shape_is_refused_before_stop_writes(self):
        for used in ({}, 'x', None, [1], [{'environmentId': 'not-a-uuid', 'createdByAgent': True}],
                     [{'createdByAgent': True}], [{'environmentId': UUID_ONE, 'createdByAgent': 'yes'}],
                     [{'environmentId': 7}], [[UUID_ONE, True]]):
            run = self.started()
            self.host.status_patch = {'usedEnvironments': used}
            self.refused_with('stop', run, [AGENT + 'StopAgentExecution', ENVIRONMENT + 'StopEnvironment'])
            self.assertEqual(self.host.runs[run]['phase'], 'PHASE_WAITING_FOR_INPUT', used)
            env = self.host.runs[run]['environment']
            self.assertEqual(self.host.environments[env], 'ENVIRONMENT_PHASE_RUNNING', used)

    def test_omitted_environments_are_none_and_only_the_execution_stops(self):
        run = self.started()
        self.host.status_patch = {'usedEnvironments': fake.DROP}
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.host.calls(), [AGENT + 'GetAgentExecution', AGENT + 'StopAgentExecution'])

    def test_a_rejected_environment_stop_is_refused_with_the_run(self):
        for answer in ((400, {'code': 'invalid_argument'}), (404, b'<html>gone</html>'), (404, {}), (200, b'null'),
                       (500, {'code': 'internal'})):
            run = self.started()
            env = self.host.runs[run]['environment']
            self.host.faults = {'StopEnvironment': answer + (False,)}
            out = self.refused_with('stop', run)
            self.assertIn(env, out['error'])
            self.assertEqual(self.host.environments[env], 'ENVIRONMENT_PHASE_RUNNING', answer)
            self.host.faults = {}

    def test_an_environment_ona_no_longer_has_or_already_stopped_counts_as_stopped(self):
        run = self.started()
        env = self.host.runs[run]['environment']
        self.host.faults = {'StopEnvironment': (404, {'code': 'not_found', 'message': 'synthetic'}, False)}
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.host.faults = {}
        self.host.environments[env] = 'ENVIRONMENT_PHASE_STOPPED'
        self.host.stopped_environment_answer = fake.error(400, 'failed_precondition', 'synthetic: already stopped')
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.host.calls(), [AGENT + 'GetAgentExecution', ENVIRONMENT + 'StopEnvironment',
                                             ENVIRONMENT + 'GetEnvironment'])
        self.host.environments[env] = 'ENVIRONMENT_PHASE_RUNNING'
        self.host.faults = {'StopEnvironment': (400, {'code': 'failed_precondition'}, False)}
        out = self.refused_with('stop', run)
        self.assertIn(env, out['error'])
        self.host.faults = {'StopEnvironment': (400, {'code': 'failed_precondition'}, False),
                            'GetEnvironment': (200, b'null', False)}
        self.refused_with('stop', run)

    def test_a_200_connect_error_object_is_a_refusal_never_a_write(self):
        for envelope in ({'code': 'unavailable', 'message': 'synthetic-host-text'}, {'code': 'internal'},
                         {'code': 'not_found', 'message': 'synthetic-host-text', 'details': []}, {'code': 7}):
            self.host.faults = {}
            run = self.started()
            env = self.host.runs[run]['environment']
            self.host.faults = {'SendToAgentExecution': (200, envelope, False)}
            out = self.refused_with('wake', run)
            self.assertEqual(out['error'], 'run %s: Ona answered 200 to POST %sSendToAgentExecution with an error '
                                            'object' % (run, AGENT))
            self.host.faults = {'StopAgentExecution': (200, envelope, False)}
            self.refused_with('stop', run, [ENVIRONMENT + 'StopEnvironment'])
            self.assertEqual(self.host.runs[run]['phase'], 'PHASE_WAITING_FOR_INPUT', envelope)
            self.host.faults = {'StopEnvironment': (200, envelope, False)}
            out = self.refused_with('stop', run)
            self.assertIn(env, out['error'])
            self.assertEqual(self.host.environments[env], 'ENVIRONMENT_PHASE_RUNNING', envelope)
            self.host.faults = {'SendToAgentExecution': (200, envelope, False)}
            self.host.runs.clear()
            code, out = self.driver('start', START)
            [run] = self.host.runs
            self.assertEqual((code, out), (1, {
                'error': 'run %s may have started: Ona answered 200 to POST %sSendToAgentExecution with an error '
                         'object' % (run, AGENT),
                'next': 'stop run %s with `driver stop`, then start again' % run}), envelope)
            self.assertNotIn('synthetic-host-text', json.dumps(out))

    def test_an_ambiguous_start_that_names_a_run_keeps_its_id_and_sends_no_prompt(self):
        for answer in ((201, {'agentExecutionId': UUID_ONE}),
                       (503, {'code': 'unavailable', 'agentExecutionId': UUID_ONE}),
                       (200, {'code': 'internal', 'message': 'synthetic-host-text', 'agentExecutionId': UUID_ONE})):
            self.host.faults = {'StartAgent': answer + (False,)}
            self.host.requests.clear()
            code, out = self.driver('start', START)
            self.assertEqual(code, 1, answer)
            self.assertTrue(out['error'].startswith('run %s may have started: Ona answered %d to POST %sStartAgent'
                                                    % (UUID_ONE, answer[0], AGENT)), out)
            self.assertEqual(out['next'], 'stop run %s with `driver stop`, then start again' % UUID_ONE)
            self.assertNotIn('synthetic-host-text', json.dumps(out))
            self.assertEqual(self.host.calls(), [AGENT + 'StartAgent'], answer)
        for answer in ((201, {'agentExecutionId': 'not-a-uuid'}), (201, {'agentExecutionId': 7}), (201, [UUID_ONE])):
            self.host.faults = {'StartAgent': answer + (False,)}
            code, out = self.driver('start', START)
            self.assertEqual((code, out['next']), (1, 'look for a new OpenWiz run in Ona, stop it, then retry'))

    def test_an_environment_ona_answers_not_found_after_a_refused_stop_counts_as_stopped(self):
        run = self.started()
        refused = (400, {'code': 'failed_precondition'}, False)
        self.host.faults = {'StopEnvironment': refused,
                            'GetEnvironment': (404, {'code': 'not_found', 'message': 'synthetic'}, False)}
        self.host.requests.clear()
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.host.calls()[-2:], [ENVIRONMENT + 'StopEnvironment', ENVIRONMENT + 'GetEnvironment'])
        for gone in ((404, {}), (404, {'code': 'unimplemented'}), (404, b'<html>gone</html>'),
                     (200, {'code': 'not_found'})):
            self.host.faults = {'StopEnvironment': refused, 'GetEnvironment': gone + (False,)}
            self.refused_with('stop', run)

    def test_inputs_off_the_schema_are_refused_before_any_request(self):
        for bad in (dict(START, token='kit-probe-not-a-login'), {k: v for k, v in START.items() if k != 'model'},
                    dict(START, ticket='7'), dict(START, repository='https://example.com/x'),
                    dict(START, effort='High')):
            self.assertEqual(self.driver('start', bad)[0], 1)
        for bad in ({'run': 'not a uuid'}, {'run': '../x'}, {'run': '00000000-0000-4000-8000-0000000000ff', 'x': 1}):
            for cmd in ('wake', 'stop'):
                self.assertEqual(self.driver(cmd, bad)[0], 1)
        self.assertEqual(self.host.requests, [])

    def test_a_host_error_is_a_fixed_refusal(self):
        self.use(served_key='synthetic-wrong-' + 'Kit0Value' * 2)
        code, out = self.driver('start', START)
        self.assertEqual((code, out), (1, {'error': 'Ona answered 401 to POST %sStartAgent' % AGENT,
                                           'next': "check your key and Ona's status, then retry"}))

    def test_version_and_schema(self):
        self.assertEqual(self.driver('version'), (0, {'driver': 'ona', 'records': ['openwiz:records v1'],
                                                       'can': ['start', 'wake', 'stop', 'effort']}))
        with open(os.path.join(ROOT, 'kernel', 'driver-kit', 'schema.json'), 'rb') as a, \
                open(os.path.join(HERE, 'schema.json'), 'rb') as b:
            self.assertEqual(a.read(), b.read())


if __name__ == '__main__':
    unittest.main()
