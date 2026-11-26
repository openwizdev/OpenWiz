#!/usr/bin/env python3
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
FAKE_HARNESS = os.path.join(KIT, 'fixtures')
CANARY = 'canary-synthetic-0123456789'
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'fake-harness',
         'model': 'synthetic-model'}


class SshDriver(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.log = os.path.join(self.folder, 'ssh.log')
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as handle:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, handle)
        path = os.pathsep.join([os.path.join(HERE, 'fixtures'), FAKE_HARNESS, '/usr/bin', '/bin'])
        self.env = dict(os.environ, PATH=path, OPENWIZ_SSH_STATE=os.path.join(self.folder, 'state'),
                        OPENWIZ_SSH_TARGET='builder@vps.example', OPENWIZ_SSH_LOG=self.log,
                        KIT_TRACKER=self.tracker)
        self.env.pop('OPENWIZ_SSH_ARGS', None)
        self.env.pop('SYNTHETIC_API_KEY', None)

    def call(self, cmd, request, **extra):
        env = dict(self.env, **extra)
        process = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request),
                                 capture_output=True, text=True, env=env, timeout=30)
        self.assertNotIn(CANARY, process.stdout + process.stderr)
        try:
            out = json.loads(process.stdout)
        except ValueError:
            out = process.stdout
        return process.returncode, out

    def logged(self):
        deadline = time.time() + 2
        rows = []
        while time.time() < deadline:
            if os.path.exists(self.log):
                with open(self.log) as handle:
                    rows = [json.loads(line) for line in handle if line.strip()]
            if rows:
                return rows
            time.sleep(0.05)
        return rows

    def test_a_secret_in_the_argument_template_is_refused_before_ssh_starts(self):
        code, out = self.call('start', START, SYNTHETIC_API_KEY=CANARY,
                              OPENWIZ_SSH_ARGS=json.dumps(['--model', '{model}', '-p', '{prompt}', CANARY]))
        self.assertEqual(code, 1)
        self.assertEqual(out['error'], 'the ssh command would carry a secret from the environment')
        self.assertEqual(self.logged(), [])

    def test_a_secret_left_only_in_the_environment_never_reaches_ssh(self):
        code, out = self.call('start', START, SYNTHETIC_API_KEY=CANARY)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.logged())
        self.assertNotIn(CANARY, json.dumps(self.logged()))
        self.call('stop', {'run': out['run']})

    def test_a_name_that_contains_key_is_refused_before_ssh_starts(self):
        value = 'canary-synthetic-0123456789'
        for name in ('MYKEY', 'APIKEY'):
            with self.subTest(name=name):
                if os.path.exists(self.log):
                    os.remove(self.log)
                code, out = self.call('start', START, **{name: value, 'OPENWIZ_SSH_ARGS': json.dumps(
                    ['--model', '{model}', '-p', '{prompt}', value])})
                self.assertEqual(code, 1, out)
                self.assertEqual(out['error'], 'the ssh command would carry a secret from the environment')
                self.assertEqual(self.logged(), [])

    def test_a_wake_while_ssh_is_alive_starts_no_second_one(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        self.addCleanup(self.call, 'stop', {'run': out['run']})
        self.assertEqual(len(self.logged()), 1)
        code, woke = self.call('wake', {'run': out['run']})
        self.assertEqual(code, 0, woke)
        self.assertEqual(woke['woke'], True)
        self.assertEqual(len(self.logged()), 1)

    def test_stop_does_not_signal_a_pid_that_is_not_the_recorded_ssh(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        path = os.path.join(self.env['OPENWIZ_SSH_STATE'], out['run'] + '.json')
        with open(path) as handle:
            state = json.load(handle)
        original = state['pids'][0]
        original_pid = original['pid'] if isinstance(original, dict) else original

        def end_original():
            try:
                os.kill(original_pid, 15)
            except OSError:
                pass

        self.addCleanup(end_original)
        victim = subprocess.Popen(['sleep', '60'], start_new_session=True)

        def end_victim():
            if victim.poll() is None:
                victim.kill()
                victim.wait(timeout=5)

        self.addCleanup(end_victim)
        state['pids'] = [victim.pid]
        with open(path, 'w') as handle:
            json.dump(state, handle)
        code, woke = self.call('wake', {'run': out['run']})
        self.assertEqual(code, 0, woke)
        self.assertEqual(len(self.logged()), 1)
        code, stopped = self.call('stop', {'run': out['run']})
        self.assertEqual(code, 0, stopped)
        self.assertIsNone(victim.poll())

    def test_kit_passes_all_five(self):
        process = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER,
                                 '--repo', 'example/site', '--ticket', '7', '--harness', 'fake-harness',
                                 '--model', 'synthetic-model', '--tracker', self.tracker, '--wait', '8'],
                                env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stdout.splitlines(), [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: a start with it was refused, as the README\'s '
            'Effort: line says',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver'])
        self.assertNotIn(CANARY, process.stdout + process.stderr)


if __name__ == '__main__':
    os.chmod(os.path.join(HERE, 'fixtures', 'ssh'), os.stat(os.path.join(HERE, 'fixtures', 'ssh')).st_mode | stat.S_IEXEC)
    os.chmod(DRIVER, os.stat(DRIVER).st_mode | stat.S_IEXEC)
    unittest.main()
