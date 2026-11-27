#!/usr/bin/env python3
import errno
import importlib.machinery
import importlib.util
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

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

    def test_the_brief_stays_one_argument_and_sendenv_is_cleared(self):
        home = os.path.join(self.folder, 'home')
        os.makedirs(os.path.join(home, '.ssh'))
        with open(os.path.join(home, '.ssh', 'config'), 'w') as handle:
            handle.write('SendEnv SYNTHETIC_TOKEN\n')
        started = dict(START, model='synthetic model')
        code, out = self.call('start', started, HOME=home)
        self.assertEqual(code, 0, out)
        self.addCleanup(self.call, 'stop', {'run': out['run']})
        argv = self.logged()[0]
        remote = argv[argv.index('--') + 1:]
        self.assertEqual(len(remote), 1)
        parsed = shlex.split(remote[0])
        prompt = 'Build the ticket: example/site#7, with the build-ticket skill.'
        self.assertEqual(parsed[parsed.index('-p') + 1], prompt)
        self.assertEqual(parsed[parsed.index('--model') + 1], 'synthetic model')
        config = argv[argv.index('-F') + 1]
        with open(config) as handle:
            text = handle.read()
        self.assertIn('SendEnv -*', text)
        self.assertIn(os.path.join(home, '.ssh', 'config'), text)
        listed = subprocess.run(['/usr/bin/ssh', '-G', '-F', config, 'builder@vps.example'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(listed.returncode, 0, listed.stderr)
        sent = [line.split()[1] for line in listed.stdout.splitlines() if line.lower().startswith('sendenv ')]
        self.assertEqual(sent, [])

    def test_a_secret_left_only_in_the_environment_never_reaches_ssh(self):
        code, out = self.call('start', START, SYNTHETIC_API_KEY=CANARY)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.logged())
        self.assertNotIn(CANARY, json.dumps(self.logged()))
        self.call('stop', {'run': out['run']})

    def test_a_name_that_contains_key_is_refused_before_ssh_starts(self):
        value = 'canary-synthetic-0123456789'
        for name in ('MYKEY', 'APIKEY', 'MYTOKEN', 'MYPASSWORD', 'mykey'):
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

    def test_a_recycled_pid_with_a_different_start_time_is_not_signalled(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        path = os.path.join(self.env['OPENWIZ_SSH_STATE'], out['run'] + '.json')
        with open(path) as handle:
            state = json.load(handle)
        record = state['pids'][0]
        pid = record['pid']
        self.assertNotEqual(record['start'], '1')
        record['start'] = '1'
        with open(path, 'w') as handle:
            json.dump(state, handle)
        self.addCleanup(self.reap, pid)
        code, woke = self.call('wake', {'run': out['run']})
        self.assertEqual(code, 0, woke)
        self.assertEqual(len(self.lines(2)), 2)
        with open(path) as handle:
            saved = json.load(handle)
        self.assertNotEqual(saved['pids'][-1].get('pid'), pid)
        self.assertTrue(self.running(pid))
        code, stopped = self.call('stop', {'run': out['run']})
        self.assertEqual(code, 0, stopped)
        self.assertTrue(self.running(pid))

    def lines(self, count):
        deadline = time.time() + 2
        rows = []
        while time.time() < deadline:
            if os.path.exists(self.log):
                with open(self.log) as handle:
                    rows = [json.loads(line) for line in handle if line.strip()]
            if len(rows) >= count:
                return rows
            time.sleep(0.05)
        return rows

    def running(self, pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def reap(self, pid):
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    def test_two_starts_do_not_share_one_ssh_config(self):
        code, first = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, first)
        code, second = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, second)
        self.addCleanup(self.call, 'stop', {'run': first['run']})
        self.addCleanup(self.call, 'stop', {'run': second['run']})
        configs = [row[row.index('-F') + 1] for row in self.lines(2) if '-F' in row]
        self.assertGreaterEqual(len(configs), 2)
        self.assertNotEqual(configs[0], configs[1])
        self.assertNotIn('ssh-config.tmp', ' '.join(configs))

    def test_the_user_ssh_config_is_included_before_the_system_one(self):
        home = os.path.join(self.folder, 'home')
        os.makedirs(os.path.join(home, '.ssh'))
        with open(os.path.join(home, '.ssh', 'config'), 'w') as handle:
            handle.write('Host *\n')
        code, out = self.call('start', START, HOME=home, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        self.addCleanup(self.call, 'stop', {'run': out['run']})
        config = self.logged()[0]
        config = config[config.index('-F') + 1]
        with open(config) as handle:
            text = handle.read().splitlines()
        user = next(i for i, line in enumerate(text) if home in line)
        system = next(i for i, line in enumerate(text) if '/etc/ssh/ssh_config' in line)
        self.assertLess(user, system)

    def test_a_wake_that_cannot_save_ends_the_ssh_it_started(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        path = os.path.join(self.env['OPENWIZ_SSH_STATE'], out['run'] + '.json')
        with open(path) as handle:
            pid = json.load(handle)['pids'][0]['pid']
        os.kill(pid, 9)
        for _ in range(40):
            if not self.running(pid):
                break
            time.sleep(0.05)
        self.assertFalse(self.running(pid))
        os.mkdir(path + '.tmp')
        code, woke = self.call('wake', {'run': out['run']}, OPENWIZ_SSH_HOLD='30')
        text = woke if isinstance(woke, str) else json.dumps(woke)
        self.assertEqual(code, 1, text)
        self.assertIn('could not be saved', text)
        self.assertFalse(self.still_has(out['run']))

    def still_has(self, run):
        needle = ('OPENWIZ_SSH_RUN=%s' % run).encode()
        if not os.path.isdir('/proc'):
            return False
        for name in os.listdir('/proc'):
            if not name.isdigit():
                continue
            try:
                with open('/proc/%s/cmdline' % name, 'rb') as handle:
                    command = handle.read()
            except OSError:
                continue
            if needle in command and name != str(os.getpid()):
                return True
        return False

    def test_stop_asks_the_vps_to_end_the_harness(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        code, stopped = self.call('stop', {'run': out['run']})
        self.assertEqual(code, 0, stopped)
        self.assertIn('kill -TERM', json.dumps(self.logged()))
        self.assertIn('OPENWIZ_SSH_RUN=%s' % out['run'], json.dumps(self.logged()))

    def test_stop_ends_a_harness_that_keeps_the_run_only_in_its_environment(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        run = out['run']
        code, stopped = self.call('stop', {'run': run})
        self.assertEqual(code, 0, stopped)
        with open(self.log) as handle:
            rows = [json.loads(line) for line in handle if line.strip()]
        remote = [row[row.index('--') + 1] for row in rows if '--' in row and 'fake-harness' not in row[row.index('--') + 1]]
        self.assertEqual(len(remote), 1, rows)
        sleeper = subprocess.Popen(['sleep', '60'], env=dict(os.environ, OPENWIZ_SSH_RUN=run), start_new_session=True)
        self.addCleanup(self.reap, sleeper.pid)
        subprocess.run(['sh', '-c', remote[0]], timeout=10)
        self.assertIsNotNone(sleeper.poll())

    def driver(self):
        loader = importlib.machinery.SourceFileLoader('ssh_driver', DRIVER)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader('ssh_driver', loader))
        loader.exec_module(module)
        return module

    def left(self):
        state = self.env['OPENWIZ_SSH_STATE']
        return sorted(os.listdir(state)) if os.path.isdir(state) else []

    def test_a_bad_target_is_refused_before_ssh_starts(self):
        for target in ('', 'vps.example', 'builder@', '@vps.example', '-oProxyCommand=id@vps.example',
                       'builder@-vps.example', 'builder@vps..example', 'builder@vps.example -p 2',
                       'builder@vps.example;id', 'builder@vps.example\nHost *'):
            with self.subTest(target=target):
                code, out = self.call('start', START, OPENWIZ_SSH_TARGET=target)
                self.assertEqual(code, 1, out)
                self.assertEqual(out['error'], 'OPENWIZ_SSH_TARGET must be user@host')
                self.assertFalse(os.path.exists(self.log))
                self.assertEqual(self.left(), [])

    def test_a_bad_argument_template_is_refused_before_ssh_starts(self):
        for raw in ('not json', '"{prompt}"', '{"a": "{prompt}"}', '[]', '["-p"]', '["{prompt}", "{prompt}"]',
                    '["{prompt}", 7]', '["{prompt}", ""]', '["{prompt}", "{effort}"]', '["{Prompt}", "{prompt}"]',
                    '["{prompt}", "a\\nb"]', '["{prompt}", "a\\u0000b"]'):
            with self.subTest(raw=raw):
                code, out = self.call('start', START, OPENWIZ_SSH_ARGS=raw)
                self.assertEqual(code, 1, out)
                self.assertTrue(out['error'].startswith('OPENWIZ_SSH_ARGS '), out)
                self.assertFalse(os.path.exists(self.log))
                self.assertEqual(self.left(), [])

    def test_a_custom_template_fills_each_placeholder_as_one_argument(self):
        code, out = self.call('start', dict(START, model='synthetic model'), OPENWIZ_SSH_HOLD='30',
                              OPENWIZ_SSH_ARGS=json.dumps(['run', '--model={model}', '{model}', '-s', '{session}',
                                                           '{prompt}']))
        self.assertEqual(code, 0, out)
        self.addCleanup(self.call, 'stop', {'run': out['run']})
        row = self.logged()[0]
        self.assertEqual(shlex.split(row[row.index('--') + 1]), [
            'env', 'OPENWIZ_SSH_RUN=' + out['run'], 'fake-harness', 'run', '--model={model}', 'synthetic model',
            '-s', out['run'], 'Build the ticket: example/site#7, with the build-ticket skill.'])

    def test_a_state_folder_that_cannot_be_written_is_refused_as_json(self):
        blocked = os.path.join(self.folder, 'blocked')
        open(blocked, 'w').close()
        for cmd, request in (('start', START), ('wake', {'run': 'run-0123456789ab'}),
                             ('stop', {'run': 'run-0123456789ab'})):
            with self.subTest(cmd=cmd):
                code, out = self.call(cmd, request, OPENWIZ_SSH_STATE=os.path.join(blocked, 'state'))
                self.assertEqual(code, 1, out)
                self.assertIsInstance(out, dict, out)
                self.assertEqual(set(out), {'error', 'next'})
                self.assertFalse(os.path.exists(self.log))

    def test_stop_spares_a_process_whose_environment_only_mentions_the_run(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        run = out['run']
        decoy = subprocess.Popen(['sleep', '60'], start_new_session=True, env={
            'PATH': '/usr/bin:/bin', 'DECOY': 'OPENWIZ_SSH_RUN=' + run, 'OPENWIZ_SSH_RUN': run + '0'})
        self.addCleanup(self.reap, decoy.pid)
        code, stopped = self.call('stop', {'run': run})
        self.assertEqual(code, 0, stopped)
        self.assertIsNone(decoy.poll())

    @unittest.skipUnless(hasattr(os, 'waitid') and os.path.isdir('/proc'), 'needs waitid and /proc')
    def test_an_ssh_that_exits_at_once_keeps_its_start_so_a_reused_pid_does_not_block_wake(self):
        real = subprocess.Popen

        def exits_at_once(argv, **options):
            process = real(['true'], **options)
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
            return process

        with mock.patch.dict(os.environ, self.env):
            driver = self.driver()
            with mock.patch.object(driver.subprocess, 'Popen', exits_at_once):
                record = driver.launch(['ssh'])
        self.assertTrue(record['start'], record)
        time.sleep(0.05)
        other = subprocess.Popen(['sleep', '60'], start_new_session=True)
        self.addCleanup(self.reap, other.pid)
        run = 'run-0123456789ab'
        os.makedirs(self.env['OPENWIZ_SSH_STATE'])
        with open(os.path.join(self.env['OPENWIZ_SSH_STATE'], run + '.json'), 'w') as handle:
            json.dump({'request': START, 'stopped': False, 'pids': [dict(record, pid=other.pid)]}, handle)
        code, woke = self.call('wake', {'run': run}, OPENWIZ_SSH_HOLD='30')
        self.addCleanup(self.call, 'stop', {'run': run})
        self.assertEqual(code, 0, woke)
        self.assertEqual(len(self.logged()), 1)
        self.assertIsNone(other.poll())

    def test_a_stop_that_cannot_save_still_ends_the_run_on_the_vps(self):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 0, out)
        run = out['run']
        with open(os.path.join(self.env['OPENWIZ_SSH_STATE'], run + '.json')) as handle:
            pid = json.load(handle)['pids'][0]['pid']
        self.addCleanup(self.reap, pid)
        state = os.path.realpath(self.env['OPENWIZ_SSH_STATE'])
        real = tempfile.mkstemp
        full = OSError(errno.ENOSPC, 'No space left on device')

        def mkstemp(*args, **options):
            if os.path.realpath(options.get('dir') or tempfile.gettempdir()) == state:
                raise full
            return real(*args, **options)

        with mock.patch.dict(os.environ, self.env):
            driver = self.driver()
            with mock.patch.object(driver, 'write_json', side_effect=full), \
                    mock.patch.object(driver.tempfile, 'mkstemp', mkstemp), self.assertRaises(driver.Refused) as refused:
                driver.stop(run)
        self.assertIn('could not save that it is stopped', refused.exception.args[0])
        self.assertIn('kill -TERM', json.dumps(self.lines(2)))
        self.assertFalse(self.running(pid))

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
