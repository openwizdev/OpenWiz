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

ORG = 'org-syn0001'
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'devin', 'model': 'default'}
SESSIONS = '/v3/organizations/%s/sessions' % ORG
UNCERTAIN_CREATE = ('look in Devin for a new session on this ticket and terminate it there (or keep it and track it by '
                    'hand), then start again: retrying now can start a second session')
CANT_SET_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster "
                   "to run it at the host's default")


class Driver(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.tracker, self.log = os.path.join(self.folder, 'tracker.json'), os.path.join(self.folder, 'devin.log')
        self.faults = os.path.join(self.folder, 'faults.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.fault({})
        open(self.log, 'w').close()
        self.key = 'syn-test-key-' + secrets.token_hex(12)
        self.key_file = key_file = os.path.join(self.folder, 'key')
        with open(key_file, 'w') as f:
            f.write(self.key)
        self.devin = subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'fixtures', 'fake-devin'),
                                       self.tracker, self.log, self.faults, key_file], stdout=subprocess.PIPE,
                                      text=True)
        self.addCleanup(self.devin.stdout.close)
        self.addCleanup(self.devin.wait)
        self.addCleanup(self.devin.kill)
        self.env = dict(os.environ, DEVIN_ORG_ID=ORG, KIT_TRACKER=self.tracker,
                        OPENWIZ_DEVIN_STATE=os.path.join(self.folder, 'state'),
                        OPENWIZ_HOSTKEY_TEST_ORIGIN=self.devin.stdout.readline().strip())

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
                            'example/site', '--ticket', '7', '--harness', 'devin', '--model', 'default',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: a start with it was refused, as the README\'s '
            'Effort: line says',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the devin key '
            'reached its host only from the key helper, in its header']), p.stderr)

    def test_start_wake_and_stop_are_devins_documented_calls(self):
        code, out = self.call('start', dict(START, model='fast'))
        self.assertEqual(code, 0, out)
        run = out['run']
        self.assertRegex(run, r'^devin-[0-9a-f]{32}$')
        self.assertEqual(self.call('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        create, message, end = self.calls()
        self.assertEqual((create['method'], create['path'], sorted(create['body'])),
                         ('POST', SESSIONS, ['devin_mode', 'prompt']))
        self.assertEqual(create['body']['devin_mode'], 'fast')
        self.assertEqual(create['body']['prompt'], 'Build the ticket: example/site#7, with the build-ticket skill.')
        self.assertEqual((message['method'], message['path'], message['body']), (
            'POST', '%s/%s/messages' % (SESSIONS, run),
            {'message': 'You were woken: read the ticket again and carry on: example/site#7, with the '
                        'build-ticket skill.'}))
        self.assertEqual((end['method'], end['path'], end['body']), ('DELETE', '%s/%s' % (SESSIONS, run), None))
        self.assertEqual({c['authorization'] for c in self.calls()}, {'Bearer ' + self.key})
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a stopped run took a wake')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.call('wake', {'run': 'devin-' + '0' * 32})[0], 1, 'an unknown run took a wake')
        self.assertEqual(len(self.calls()), 3, 'a stopped or unknown run reached Devin')

    def test_model_harness_and_organization_are_checked_before_any_call(self):
        self.assertEqual(self.call('start', START)[0], 0)
        self.assertNotIn('devin_mode', self.calls()[0]['body'])
        for request, env in ((dict(START, model='Opus 5.5'), {}), (dict(START, harness='claude'), {}),
                             (START, {'DEVIN_ORG_ID': ''}), (START, {'DEVIN_ORG_ID': 'org-x/../y'})):
            with self.subTest(request=request, env=env):
                self.assertEqual(self.call('start', request, **env)[0], 1)
        self.assertEqual(len(self.calls()), 1)

    def test_a_host_refusal_is_an_error_and_a_failed_stop_is_tried_again(self):
        for answer in ({'status': 401, 'body': {'detail': 'synthetic refusal'}},
                       {'status': 200, 'body': {'session_id': 'ghp_' + 'Synthetic0' * 3, 'status': 'new'}},
                       {'status': 200, 'body': {'status': 'new'}}):
            with self.subTest(answer=answer):
                self.fault({'POST create': answer})
                code, out = self.call('start', START)
                self.assertEqual(code, 1, out)
                self.assertNotIn('Synthetic', json.dumps(out))
        state = self.env['OPENWIZ_DEVIN_STATE']
        self.assertEqual(os.listdir(state) if os.path.isdir(state) else [], [], 'a refused start left a run')
        self.fault({})
        run = self.call('start', START)[1]['run']
        self.fault({'POST message': {'status': 500, 'body': {}}, 'DELETE end': {'status': 500, 'body': {}}})
        self.assertEqual(self.call('wake', {'run': run})[0], 1)
        self.assertEqual(self.call('stop', {'run': run})[0], 1)
        self.fault({})
        self.assertEqual(self.call('wake', {'run': run})[0], 1, 'a run being stopped took a wake')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual([c['method'] for c in self.calls()][-3:], ['POST', 'DELETE', 'DELETE'])

    def test_an_uncertain_create_is_never_retried_and_a_confirmed_refusal_is_told_apart(self):
        for fault in ({'drop': True}, {'status': 503, 'body': {}}, {'status': 408, 'body': {}}):
            with self.subTest(fault=fault):
                self.fault({'POST create': fault})
                code, out = self.call('start', START)
                self.assertEqual(code, 1, out)
                self.assertIn('outcome is unknown', out['error'])
                self.assertEqual(out['next'], UNCERTAIN_CREATE)
        self.fault({'POST create': {'status': 422, 'body': {}}})
        code, out = self.call('start', START)
        self.assertEqual((code, out['error']), (1, 'Devin refused the new session (422), so nothing was started'))
        with open(self.key_file, 'w') as f:
            f.write('')
        code, out = self.call('start', START)
        self.assertEqual(code, 1)
        self.assertNotIn('outcome is unknown', out['error'])
        self.assertTrue(out['error'].startswith("the key helper refused: the kit's fake host gave no test key"), out)
        state = self.env['OPENWIZ_DEVIN_STATE']
        self.assertEqual(os.listdir(state) if os.path.isdir(state) else [], [], 'an unsaved start left a run')
        self.assertEqual([c['method'] for c in self.calls()], ['POST'] * 4)

    def test_a_start_with_an_effort_is_refused_and_nothing_starts(self):
        for effort in ('medium', 'max', 'Not A Word'):
            with self.subTest(effort=effort):
                code, out = self.call('start', dict(START, effort=effort))
                self.assertEqual((code, out['next']), (1, CANT_SET_EFFORT))
                self.assertIn('devin', out['error'])
                if effort != 'Not A Word':
                    self.assertIn(effort, out['error'])
        state = self.env['OPENWIZ_DEVIN_STATE']
        self.assertEqual((self.calls(), os.listdir(state) if os.path.isdir(state) else []), ([], []))
        code, version = self.call('version', None)
        self.assertNotIn('effort', version['can'])
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        login = lines.index('Login: held by Devin')
        self.assertEqual((lines[login + 1], lines[login + 2][:35]), ('', "Effort: the host can't set it (Devi"))


    def test_a_provider_qualified_model_passes_the_pattern_and_meets_devins_own_modes(self):
        code, out = self.call('start', dict(START, model='kimi-code/kimi-for-coding'))
        self.assertEqual((code, out['error']), (1, 'model is not a Devin mode'))
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
