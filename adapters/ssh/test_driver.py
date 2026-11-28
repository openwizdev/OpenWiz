#!/usr/bin/env python3
import errno, importlib.machinery, importlib.util, json, os, shlex, shutil, socket, stat, subprocess, sys, tempfile, time, unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER, KIT = os.path.join(HERE, 'driver'), os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
CANARY = 'canary-synthetic-0123456789'
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'fake-harness',
         'model': 'synthetic-model'}


class SshDriver(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.log, self.tracker = os.path.join(self.folder, 'ssh.log'), os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as handle:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, handle)
        path = os.pathsep.join([os.path.join(HERE, 'fixtures'), os.path.join(KIT, 'fixtures'), '/usr/bin', '/bin'])
        self.env = dict(os.environ, PATH=path, OPENWIZ_SSH_STATE=os.path.join(self.folder, 'state'),
                        OPENWIZ_SSH_TARGET='builder@vps.example', OPENWIZ_SSH_LOG=self.log, KIT_TRACKER=self.tracker)
        for key in ('OPENWIZ_SSH_ARGS', 'SYNTHETIC_API_KEY'):
            self.env.pop(key, None)

    def call(self, cmd, request, **extra):
        process = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request),
                                 capture_output=True, text=True, env=dict(self.env, **extra), timeout=30)
        self.assertNotIn(CANARY, process.stdout + process.stderr)
        try:
            return process.returncode, json.loads(process.stdout)
        except ValueError:
            return process.returncode, process.stdout

    def lines(self, count=1):
        deadline, rows = time.time() + 2, []
        while time.time() < deadline:
            if os.path.exists(self.log):
                with open(self.log) as handle:
                    rows = [json.loads(line) for line in handle if line.strip()]
            if len(rows) >= count:
                return rows
            time.sleep(0.05)
        return rows

    def state_path(self, run):
        return os.path.join(self.env['OPENWIZ_SSH_STATE'], run + '.json')

    def read_state(self, run):
        with open(self.state_path(run)) as handle:
            return json.load(handle)

    def write_state(self, run, state):
        os.makedirs(self.env['OPENWIZ_SSH_STATE'], exist_ok=True)
        with open(self.state_path(run), 'w') as handle:
            json.dump(state, handle)

    def start_held(self, stop=True, **extra):
        code, out = self.call('start', START, OPENWIZ_SSH_HOLD='30', **extra)
        self.assertEqual(code, 0, out)
        if stop:
            self.addCleanup(self.call, 'stop', {'run': out['run']})
        return out['run']

    def sleeper(self, env=None):
        proc = subprocess.Popen(['sleep', '60'], start_new_session=True, env=env)
        self.addCleanup(lambda: (proc.kill() if proc.poll() is None else None, proc.wait(timeout=5)))
        return proc

    def running(self, pid):
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def reap(self, pid):
        try:
            os.kill(pid, 15)
        except OSError:
            pass

    def kill_and_wait(self, pid):
        os.kill(pid, 9)
        for _ in range(40):
            if not self.running(pid):
                break
            time.sleep(0.05)
        self.assertFalse(self.running(pid))

    def driver(self):
        loader = importlib.machinery.SourceFileLoader('ssh_driver', DRIVER)
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader('ssh_driver', loader))
        loader.exec_module(module)
        return module

    def left(self):
        state = self.env['OPENWIZ_SSH_STATE']
        return sorted(os.listdir(state)) if os.path.isdir(state) else []

    def ssh_home(self, name, content):
        home = os.path.join(self.folder, name)
        os.makedirs(os.path.join(home, '.ssh'))
        with open(os.path.join(home, '.ssh', 'config'), 'w') as handle:
            handle.write(content)
        return home

    def test_a_secret_in_the_argument_template_is_refused_before_ssh_starts(self):
        code, out = self.call('start', START, SYNTHETIC_API_KEY=CANARY,
                              OPENWIZ_SSH_ARGS=json.dumps(['--model', '{model}', '-p', '{prompt}', CANARY]))
        self.assertEqual((code, out['error'], self.lines()), (1, 'the ssh command would carry a secret from the environment', []))

    def test_the_brief_stays_one_argument_and_sendenv_is_cleared(self):
        home = self.ssh_home('home', 'SendEnv SYNTHETIC_TOKEN\n')
        code, out = self.call('start', dict(START, model='synthetic model'), HOME=home)
        self.assertEqual(code, 0, out)
        self.addCleanup(self.call, 'stop', {'run': out['run']})
        argv = self.lines()[0]
        remote = argv[argv.index('--') + 1:]
        parsed = shlex.split(remote[0])
        self.assertEqual((len(remote), parsed[parsed.index('-p') + 1], parsed[parsed.index('--model') + 1]),
                         (1, 'Build the ticket: example/site#7, with the build-ticket skill.', 'synthetic model'))
        config = argv[argv.index('-F') + 1]
        with open(config) as handle:
            text = handle.read()
        self.assertIn('SendEnv -*', text)
        self.assertIn(os.path.join(home, '.ssh', 'config'), text)
        listed = subprocess.run(['/usr/bin/ssh', '-G', '-F', config, 'builder@vps.example'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual((listed.returncode, [l.split()[1] for l in listed.stdout.splitlines()
                                              if l.lower().startswith('sendenv ')]), (0, []))

    def test_a_secret_left_only_in_the_environment_never_reaches_ssh(self):
        code, out = self.call('start', START, SYNTHETIC_API_KEY=CANARY)
        self.assertEqual((code, bool(self.lines())), (0, True))
        self.assertNotIn(CANARY, json.dumps(self.lines()))
        self.call('stop', {'run': out['run']})

    def test_a_name_that_contains_key_is_refused_before_ssh_starts(self):
        for name in ('MYKEY', 'APIKEY', 'MYTOKEN', 'MYPASSWORD', 'mykey'):
            with self.subTest(name=name):
                if os.path.exists(self.log):
                    os.remove(self.log)
                code, out = self.call('start', START, **{name: CANARY, 'OPENWIZ_SSH_ARGS': json.dumps(
                    ['--model', '{model}', '-p', '{prompt}', CANARY])})
                self.assertEqual((code, out['error'], self.lines()),
                                 (1, 'the ssh command would carry a secret from the environment', []))

    def test_a_wake_while_ssh_is_alive_starts_no_second_one(self):
        run = self.start_held()
        self.assertEqual(len(self.lines()), 1)
        code, woke = self.call('wake', {'run': run})
        self.assertEqual((code, woke['woke'], len(self.lines())), (0, True, 1))

    def test_stop_does_not_signal_a_pid_that_is_not_the_recorded_ssh(self):
        run = self.start_held(stop=False)
        state = self.read_state(run)
        self.addCleanup(self.reap, state['pids'][0]['pid'])
        victim = self.sleeper()
        state['pids'] = [victim.pid]
        self.write_state(run, state)
        self.assertEqual(self.call('wake', {'run': run})[0], 0)
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(self.call('stop', {'run': run})[0], 0)
        self.assertIsNone(victim.poll())

    def test_a_recycled_pid_with_a_different_start_time_is_not_signalled(self):
        run = self.start_held(stop=False)
        state = self.read_state(run)
        record = state['pids'][0]
        pid = record['pid']
        self.assertNotEqual(record['start'], '1')
        record['start'] = '1'
        self.write_state(run, state)
        self.addCleanup(self.reap, pid)
        self.assertEqual(self.call('wake', {'run': run}, OPENWIZ_SSH_HOLD='30')[0], 0)
        self.assertEqual(len(self.lines(2)), 2)
        self.assertNotEqual(self.read_state(run)['pids'][-1].get('pid'), pid)
        self.assertTrue(self.running(pid))
        self.assertEqual(self.call('stop', {'run': run})[0], 0)
        self.assertTrue(self.running(pid))

    def test_two_starts_do_not_share_one_ssh_config(self):
        self.start_held()
        self.start_held()
        configs = [row[row.index('-F') + 1] for row in self.lines(2) if '-F' in row]
        self.assertGreaterEqual(len(configs), 2)
        self.assertNotEqual(configs[0], configs[1])
        self.assertNotIn('ssh-config.tmp', ' '.join(configs))

    def test_the_user_ssh_config_is_included_before_the_system_one(self):
        home = self.ssh_home('home', 'Host *\n')
        self.start_held(HOME=home)
        row = self.lines()[0]
        with open(row[row.index('-F') + 1]) as handle:
            text = handle.read().splitlines()
        self.assertLess(next(i for i, l in enumerate(text) if home in l),
                        next(i for i, l in enumerate(text) if '/etc/ssh/ssh_config' in l))

    def test_a_wake_that_cannot_save_ends_the_ssh_it_started(self):
        run = self.start_held(stop=False)
        self.kill_and_wait(self.read_state(run)['pids'][0]['pid'])
        os.mkdir(self.state_path(run) + '.tmp')
        code, woke = self.call('wake', {'run': run}, OPENWIZ_SSH_HOLD='30')
        self.assertEqual(code, 1, woke)
        self.assertIn('could not be saved', json.dumps(woke))
        self.assertFalse(self.still_has(run))

    def still_has(self, run):
        needle = ('OPENWIZ_SSH_RUN=%s' % run).encode()
        if not os.path.isdir('/proc'):
            return False
        for name in os.listdir('/proc'):
            if name.isdigit() and name != str(os.getpid()):
                try:
                    with open('/proc/%s/cmdline' % name, 'rb') as handle:
                        if needle in handle.read():
                            return True
                except OSError:
                    continue
        return False

    def test_stop_asks_the_vps_to_end_the_harness(self):
        run = self.start_held(stop=False)
        self.assertEqual(self.call('stop', {'run': run})[0], 0)
        dumped = json.dumps(self.lines(2))
        self.assertIn('kill -TERM', dumped)
        self.assertIn('OPENWIZ_SSH_RUN=%s' % run, dumped)

    def test_stop_ends_only_exact_run_env_and_spares_multiline_mentions(self):
        run = self.start_held(stop=False)
        self.assertEqual(self.call('stop', {'run': run})[0], 0)
        rows = self.lines(2)
        remote = [r[r.index('--') + 1] for r in rows if '--' in r and 'fake-harness' not in r[r.index('--') + 1]]
        self.assertEqual(len(remote), 1, rows)
        marked = self.sleeper(env={'PATH': '/usr/bin:/bin', 'OPENWIZ_SSH_RUN': run})
        multiline = self.sleeper(env={'PATH': '/usr/bin:/bin', 'NOTES': 'before\nOPENWIZ_SSH_RUN=%s\nafter' % run})
        subprocess.run(['sh', '-c', remote[0]], timeout=10)
        self.assertIsNotNone(marked.poll())
        self.assertIsNone(multiline.poll())

    def test_a_bad_target_is_refused_before_ssh_starts(self):
        for target in ('', 'vps.example', 'builder@', '@vps.example', '-oProxyCommand=id@vps.example',
                       'builder@-vps.example', 'builder@vps..example', 'builder@vps.example -p 2',
                       'builder@vps.example;id', 'builder@vps.example\nHost *'):
            with self.subTest(target=target):
                code, out = self.call('start', START, OPENWIZ_SSH_TARGET=target)
                self.assertEqual((code, out['error'], os.path.exists(self.log), self.left()),
                                 (1, 'OPENWIZ_SSH_TARGET must be user@host', False, []))

    def test_a_bad_argument_template_is_refused_before_ssh_starts(self):
        for raw in ('not json', '"{prompt}"', '{"a": "{prompt}"}', '[]', '["-p"]', '["{prompt}", "{prompt}"]',
                    '["{prompt}", 7]', '["{prompt}", ""]', '["{prompt}", "{effort}"]', '["{Prompt}", "{prompt}"]',
                    '["{prompt}", "a\\nb"]', '["{prompt}", "a\\u0000b"]'):
            with self.subTest(raw=raw):
                code, out = self.call('start', START, OPENWIZ_SSH_ARGS=raw)
                self.assertEqual((code, out['error'].startswith('OPENWIZ_SSH_ARGS '), os.path.exists(self.log),
                                  self.left()), (1, True, False, []))

    def test_a_custom_template_fills_each_placeholder_as_one_argument(self):
        code, out = self.call('start', dict(START, model='synthetic model'), OPENWIZ_SSH_HOLD='30',
                              OPENWIZ_SSH_ARGS=json.dumps(['run', '--model={model}', '{model}', '-s', '{session}', '{prompt}']))
        self.assertEqual(code, 0, out)
        self.addCleanup(self.call, 'stop', {'run': out['run']})
        row = self.lines()[0]
        parsed = shlex.split(row[row.index('--') + 1])
        self.assertEqual(parsed[parsed.index('env'):], [
            'env', 'OPENWIZ_SSH_RUN=' + out['run'], 'fake-harness', 'run', '--model={model}', 'synthetic model',
            '-s', out['run'], 'Build the ticket: example/site#7, with the build-ticket skill.'])

    def test_a_state_folder_that_cannot_be_written_is_refused_as_json(self):
        blocked = os.path.join(self.folder, 'blocked')
        open(blocked, 'w').close()
        for cmd, request in (('start', START), ('wake', {'run': 'run-0123456789ab'}), ('stop', {'run': 'run-0123456789ab'})):
            with self.subTest(cmd=cmd):
                code, out = self.call(cmd, request, OPENWIZ_SSH_STATE=os.path.join(blocked, 'state'))
                self.assertEqual((code, set(out), os.path.exists(self.log)), (1, {'error', 'next'}, False))

    def test_stop_spares_a_process_whose_environment_only_mentions_the_run(self):
        run = self.start_held(stop=False)
        decoy = self.sleeper(env={'PATH': '/usr/bin:/bin', 'DECOY': 'OPENWIZ_SSH_RUN=' + run, 'OPENWIZ_SSH_RUN': run + '0'})
        self.assertEqual(self.call('stop', {'run': run})[0], 0)
        self.assertIsNone(decoy.poll())

    def test_wake_and_stop_keep_the_runs_original_target(self):
        run = self.start_held(stop=False, OPENWIZ_SSH_TARGET='first@host1.example')
        self.kill_and_wait(self.read_state(run)['pids'][0]['pid'])
        self.assertEqual(self.call('wake', {'run': run}, OPENWIZ_SSH_HOLD='30', OPENWIZ_SSH_TARGET='second@host2.example')[0], 0)
        self.assertEqual(self.call('stop', {'run': run}, OPENWIZ_SSH_TARGET='third@host3.example')[0], 0)
        self.assertEqual([row[row.index('--') - 1] for row in self.lines(3)], ['first@host1.example'] * 3)

    def test_start_and_wake_refuse_an_early_ssh_exit_on_a_closed_port(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        home = self.ssh_home('closed', 'Host 127.0.0.1\n  Port %d\n  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n' % port)
        real_ssh = dict(PATH='/usr/bin:/bin', HOME=home, OPENWIZ_SSH_TARGET='builder@127.0.0.1', SYNTHETIC_API_KEY=CANARY)
        code, out = self.call('start', START, **real_ssh)
        self.assertEqual((code, set(out), self.left()), (1, {'error', 'next'}, []))
        self.assertIn('connection refused', out['error'])
        run = 'run-0123456789ab'
        self.write_state(run, {'request': START, 'target': 'builder@127.0.0.1', 'stopped': False, 'pids': []})
        code, woke = self.call('wake', {'run': run}, **real_ssh)
        self.assertEqual((code, set(woke)), (1, {'error', 'next'}))
        self.assertIn('connection refused', woke['error'])

    def test_early_ssh_errors_are_sanitized_and_missing_ack_is_refused(self):
        bad_bin = os.path.join(self.folder, 'badbin')
        os.makedirs(bad_bin)
        bad_ssh = os.path.join(bad_bin, 'ssh')
        with open(bad_ssh, 'w') as handle:
            handle.write('#!/bin/sh\necho "secret %s token=synthetic-not-a-secret-9999 /home/example/.ssh/id_test" >&2\nexit 1\n' % CANARY)
        os.chmod(bad_ssh, 0o700)
        code, out = self.call('start', START, PATH=bad_bin + os.pathsep + '/usr/bin:/bin', SYNTHETIC_API_KEY=CANARY)
        self.assertEqual((code, self.left()), (1, []))
        self.assertNotIn('synthetic-not-a-secret', json.dumps(out))
        self.assertNotIn('/home/example', json.dumps(out))
        code, missing = self.call('start', dict(START, harness='no-such-harness'))
        self.assertEqual((code, self.left()), (1, []))
        self.assertIn('harness not found', missing['error'])
        with mock.patch.dict(os.environ, dict(self.env, OPENWIZ_SSH_HOLD='30', OPENWIZ_SSH_NO_ACK='1')):
            driver = self.driver()
            with mock.patch.object(driver, 'LAUNCH_TIMEOUT', 0.2), self.assertRaises(driver.Refused) as refused:
                driver.start(START)
        self.assertIn('in time', refused.exception.args[0])

    @unittest.skipUnless(hasattr(os, 'waitid') and os.path.isdir('/proc'), 'needs waitid and /proc')
    def test_an_ssh_that_exits_at_once_keeps_its_start_so_a_reused_pid_does_not_block_wake(self):
        real = subprocess.Popen

        def exits_at_once(argv, **options):
            process = real(['sh', '-c', 'printf "%s\\n" "$1"', 'sh', 'OPENWIZ_SSH_READY:fast'], **options)
            os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
            return process

        with mock.patch.dict(os.environ, self.env):
            driver = self.driver()
            with mock.patch.object(driver.subprocess, 'Popen', exits_at_once):
                record = driver.launch(['ssh'], 'OPENWIZ_SSH_READY:fast')
        self.assertTrue(record['start'], record)
        time.sleep(0.05)
        other = self.sleeper()
        run = 'run-0123456789ab'
        self.write_state(run, {'request': START, 'target': 'builder@vps.example', 'stopped': False,
                               'pids': [dict(record, pid=other.pid)]})
        code, woke = self.call('wake', {'run': run}, OPENWIZ_SSH_HOLD='30')
        self.addCleanup(self.call, 'stop', {'run': run})
        self.assertEqual((code, len(self.lines()), other.poll()), (0, 1, None))

    def test_a_stop_that_cannot_save_still_ends_the_run_on_the_vps(self):
        run = self.start_held(stop=False)
        pid = self.read_state(run)['pids'][0]['pid']
        self.addCleanup(self.reap, pid)
        state, real = os.path.realpath(self.env['OPENWIZ_SSH_STATE']), tempfile.mkstemp
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

    def unreachable(self):
        down = os.path.join(self.folder, 'down')
        os.makedirs(down, exist_ok=True)
        stub = os.path.join(down, 'ssh')
        with open(stub, 'w') as handle:
            handle.write('#!/bin/sh\necho "Connection refused" >&2\nexit 255\n')
        os.chmod(stub, 0o700)
        return {'PATH': down + os.pathsep + self.env['PATH']}

    def test_a_repeated_stop_answers_again_while_the_vps_is_unreachable(self):
        run = self.start_held(stop=False)
        stopped = (0, {'run': run, 'stopped': True})
        self.assertEqual(self.call('stop', {'run': run}), stopped)
        self.assertEqual(self.call('stop', {'run': run}, **self.unreachable()), stopped)
        self.assertEqual(self.call('wake', {'run': run})[1]['error'], 'run %s is stopped' % run)

    def test_a_failed_stop_is_retried_until_the_vps_confirms(self):
        run = self.start_held(stop=False)
        pid = self.read_state(run)['pids'][0]['pid']
        self.addCleanup(self.reap, pid)
        code, out = self.call('stop', {'run': run}, **self.unreachable())
        self.assertEqual((code, out['error']), (1, 'the VPS did not end run %s (connection refused)' % run))
        self.assertEqual(self.call('wake', {'run': run})[1]['error'], 'run %s is stopped' % run)
        code, out = self.call('stop', {'run': run}, **self.unreachable())
        self.assertEqual((code, out['error']), (1, 'the VPS did not end run %s (connection refused)' % run))
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertIn('kill -TERM', json.dumps(self.lines(2)))
        self.assertEqual(self.call('stop', {'run': run}, **self.unreachable()), (0, {'run': run, 'stopped': True}))

    def test_an_older_stopped_record_without_confirmation_still_retries_the_vps(self):
        run = self.start_held(stop=False)
        state = self.read_state(run)
        self.write_state(run, dict(state, stopped=True))
        code, out = self.call('stop', {'run': run}, **self.unreachable())
        self.assertEqual((code, out['error']), (1, 'the VPS did not end run %s (connection refused)' % run))
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))

    def test_kit_passes_all_five(self):
        process = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER,
                                  '--repo', 'example/site', '--ticket', '7', '--harness', 'fake-harness',
                                  '--model', 'synthetic-model', '--tracker', self.tracker, '--wait', '8'],
                                 env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(process.stdout.splitlines(), [
            'pass version: openwiz:records v1, and the schema is driver v1',
            "pass start: the run posted builder status note 1; effort: a start with it was refused, as the README's "
            'Effort: line says',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver'])
        self.assertNotIn(CANARY, process.stdout + process.stderr)


if __name__ == '__main__':
    os.chmod(os.path.join(HERE, 'fixtures', 'ssh'), os.stat(os.path.join(HERE, 'fixtures', 'ssh')).st_mode | stat.S_IEXEC)
    os.chmod(DRIVER, os.stat(DRIVER).st_mode | stat.S_IEXEC)
    unittest.main()
