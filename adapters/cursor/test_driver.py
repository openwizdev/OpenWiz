#!/usr/bin/env python3
import http.client
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
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
HOST = 'cursor-cloud'
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'cursor',
         'model': 'synthetic-model-1'}
ENV_KEYS = ('PATH', 'KIT_TRACKER', 'KIT_TEST', 'OPENWIZ_CURSOR_STATE', 'OPENWIZ_HOSTKEY_TEST_ORIGIN')
_spec = importlib.util.spec_from_file_location('hostkey', os.path.join(KIT, 'hostkey.py'))
hostkey = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hostkey)


def process_row(pid, column):
    try:
        p = subprocess.run(['ps', '-p', str(pid), '-o', column + '='], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return p.stdout.strip() if p.returncode == 0 else ''


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return process_row(pid, 'stat')[:1] not in ('', 'Z')


class Cursor(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        python = os.path.join(self.folder, 'python')
        os.mkdir(python)
        os.symlink(sys.executable, os.path.join(python, 'python3'))
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.log, self.faults = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'faults.json')
        self.state, self.key_file = os.path.join(self.folder, 'cursor.json'), os.path.join(self.folder, 'key')
        self.key = 'syn-test-key-' + secrets.token_hex(12)
        with open(self.key_file, 'w') as f:
            f.write(self.key)
        self.fault({})
        open(self.log, 'w').close()
        self.cursor = subprocess.Popen(
            [sys.executable, '-I', os.path.join(HERE, 'fixtures', 'fake-cursor'), self.state, self.log, self.faults,
             self.key_file], stdout=subprocess.PIPE, text=True,
            env={'PATH': python, 'KIT_TRACKER': self.tracker, 'FAKE_TURNS': self.turns, 'FAKE_HOLD': self.hold})
        self.origin = self.cursor.stdout.readline().strip()
        self.env = dict(KIT_TRACKER=self.tracker, KIT_TEST=self.mark, PATH=python,
                        OPENWIZ_CURSOR_STATE=os.path.join(self.folder, 'state'),
                        OPENWIZ_HOSTKEY_TEST_ORIGIN=self.origin)
        real = [n for n in ('claude', 'codex', 'agent', 'cursor-agent', 'gh', 'boat', 'curl')
                if shutil.which(n, path=self.env['PATH'])]
        if real or not re.fullmatch(r'http://127\.0\.0\.1:[0-9]+', self.origin):
            raise RuntimeError('the test reaches a real program or host: %s' % (real or [self.origin]))

    def tearDown(self):
        self.cursor.send_signal(signal.SIGTERM)
        self.cursor.wait(30)
        self.cursor.stdout.close()
        for pid in self.running():
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def running(self):
        return [pid for pid, _ in self.logged() if alive(pid) and self.fake_agent(pid)]

    def fake_agent(self, pid):
        needle = os.path.join(HERE, 'fixtures', 'fake-agent')
        try:
            with open('/proc/%d/cmdline' % pid, 'rb') as f:
                return needle.encode() in f.read().split(b'\0')
        except OSError:
            return needle in process_row(pid, 'command')

    def fault(self, faults):
        with open(self.faults, 'w') as f:
            json.dump(faults, f)

    def driver(self, cmd, request, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        self.assertNotIn(self.key, p.stdout + p.stderr)
        return p.returncode, json.loads(p.stdout)

    def calls(self):
        with open(self.log) as f:
            return [dict(c, call=c['method'] + ' ' + c['path'][len('/v1'):]) for c in map(json.loads, f)]

    def agents(self):
        try:
            with open(self.state) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def on_disk(self):
        folder, found = self.env['OPENWIZ_CURSOR_STATE'], ''
        for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
            with open(os.path.join(folder, name)) as f:
                found += name + '\n' + f.read()
        return found

    def logged(self, count=0):
        deadline = time.monotonic() + 10
        while True:
            try:
                with open(self.turns) as f:
                    runs = [(int(a), b) for a, b in (x.split() for x in f)]
            except FileNotFoundError:
                runs = []
            if len(runs) >= count or time.monotonic() > deadline:
                return runs
            time.sleep(0.05)

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def test_runs_reach_only_the_fake_cursor_and_python(self):
        self.assertEqual(sorted(os.listdir(self.env['PATH'])), ['python3'])
        self.assertEqual(sorted(self.env), sorted(ENV_KEYS))
        self.assertRegex(self.env['OPENWIZ_HOSTKEY_TEST_ORIGIN'], r'^http://127\.0\.0\.1:[0-9]+$')

    def test_kit_passes_all_five_with_its_key_check(self):
        p = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER, '--repo',
                            'example/site', '--ticket', '7', '--harness', 'cursor', '--model', 'synthetic-model-1',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            "pass start: the run posted builder status note 1; effort: a start with it was refused, as the README's "
            'Effort: line says',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the %s key '
            'reached its host only from the key helper, in its header' % HOST]), p.stderr)

    def test_start_creates_one_agent_under_an_id_it_saved_first_with_no_login(self):
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [call] = self.calls()
        self.assertEqual((call['call'], call['authorization']), ('POST /agents', 'Bearer ' + self.key))
        body = json.loads(call['body'])
        self.assertEqual(body['repos'], [{'url': 'https://github.com/example/site'}])
        self.assertEqual(body['model'], {'id': 'synthetic-model-1'})
        self.assertIs(body['autoCreatePR'], False)
        with open(os.path.join(HERE, '..', '..', 'wizskills.lock')) as f:
            lock = json.load(f)
        for part in ('example/site', '#7', 'build-ticket skill', lock['version'], lock['commit'], lock['tree']):
            self.assertIn(part, body['prompt']['text'])
        with open(os.path.join(self.env['OPENWIZ_CURSOR_STATE'], out['run'] + '.json')) as f:
            self.assertEqual(json.load(f), {'agent': body['agentId'], 'stopped': False, 'starting': False, 'request':
                             {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket'}})
        self.assertEqual(list(self.agents()), [body['agentId']])

    def test_a_saved_run_file_is_created_owner_only_then_renamed(self):
        previous = os.umask(0)
        try:
            code, out = self.driver('start', START)
        finally:
            os.umask(previous)
        self.assertEqual(code, 0, out)
        folder = self.env['OPENWIZ_CURSOR_STATE']
        saved = os.path.join(folder, out['run'] + '.json')
        self.assertEqual(oct(os.stat(saved).st_mode & 0o777), oct(0o600))
        self.assertFalse(any(name.endswith('.json.new') for name in os.listdir(folder)))

    def test_a_provider_qualified_model_reaches_cursor(self):
        with open(os.path.join(HERE, 'README.md'), encoding='utf-8') as f:
            lines = f.read().splitlines()
        login = next(i for i, line in enumerate(lines) if line.startswith('Login:'))
        following = next(line for line in lines[login + 1:] if line.strip())
        self.assertTrue(following.startswith("Effort: the host can't set it"), following)
        qualified = 'openrouter/anthropic/claude-sonnet-4.6'
        longest = 'm' * 49 + '/' + 'n' * 50
        self.assertEqual(len(longest), 100)
        sent = []
        for model in (qualified, longest):
            code, out = self.driver('start', dict(START, model=model))
            self.assertEqual(code, 0, out)
            sent.append(json.loads(self.calls()[-1]['body'])['model']['id'])
            self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(sent, [qualified, longest])
        before = len(self.calls())
        over = longest + 'x'
        code, err = self.driver('start', dict(START, model=over))
        self.assertEqual((code, err), (1, {'error': 'model is not valid',
                                            'next': 'fix model as `driver schema` shows'}))
        self.assertEqual(len(self.calls()), before, 'a model past 100 characters was sent')

    def test_the_key_never_passes_through_the_driver(self):
        hosts = hostkey.registry()
        self.assertIn(HOST, hosts)
        entry = hosts[HOST]
        self.assertEqual(entry['origin'], 'https://api.cursor.com')
        with open(DRIVER) as f:
            source = f.read()
        self.assertFalse(entry['variable'] in source, 'the driver names the key')
        for folder, _, names in os.walk(HERE):
            for name in names:
                with open(os.path.join(folder, name), 'rb') as f:
                    lines = f.read().decode('utf-8').split('\n')
                if os.path.join(folder, name) == os.path.join(HERE, 'README.md'):
                    lines = [x for x in lines if entry['keychain'] not in x]
                self.assertEqual([x for x in lines if entry['variable'] in x], [], 'a file names the key: ' + name)
        self.assertEqual(re.findall(r'\benviron\b\S*', source), ["environ.get('OPENWIZ_CURSOR_STATE')"])
        self.assertEqual([x for x in ('getenv', 'environb', 'env=', 'curl', entry['origin'], entry['keychain'])
                          if x in source], [])
        planted = 'syn-planted-key-' + secrets.token_hex(12)
        code, out = self.driver('start', START, **{entry['variable']: planted})
        self.assertEqual(code, 0, out)
        outputs = [json.dumps(out)]
        for cmd in ('wake', 'stop'):
            self.until(lambda: not any(alive(p) for p, _ in self.logged(1)))
            code, answer = self.driver(cmd, out, **{entry['variable']: planted})
            self.assertEqual(code, 0, answer)
            outputs.append(json.dumps(answer))
        calls = self.calls()
        self.assertEqual([c['call'].split(' ')[0] for c in calls], ['POST', 'GET', 'POST', 'GET', 'POST', 'POST'])
        self.assertEqual({c['authorization'] for c in calls}, {'Bearer ' + self.key})
        sent = json.dumps([[c['path'], c['body']] for c in calls]) + ''.join(outputs)
        self.assertEqual([k for k in (self.key, planted) if k in sent], [])

    def test_a_missing_key_is_a_clear_error_and_sends_nothing(self):
        with open(self.key_file, 'w') as f:
            f.write('')
        code, err = self.driver('start', START)
        self.assertEqual(code, 1, err)
        self.assertIn('key helper refused', err['error'])
        self.assertIn('nothing was sent', err['error'])
        self.assertNotIn('unknown', err['error'])
        self.assertEqual((self.calls(), self.agents(), self.on_disk()), ([], {}, ''))

    def test_a_key_pasted_into_the_model_is_refused_and_never_saved(self):
        code, err = self.driver('start', dict(START, model=self.key))
        self.assertEqual(code, 1, err)
        self.assertIn('nothing was sent', err['error'])
        self.assertEqual((self.calls(), self.on_disk()), ([], ''))

    def test_the_tests_read_no_other_process_environment(self):
        with open(os.path.abspath(__file__)) as f:
            self.assertNotIn('/' + 'environ', f.read())

    def test_a_live_fake_agent_is_seen_when_proc_is_missing(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [(pid, _)] = self.logged(1)
        self.assertEqual(self.running(), [pid])
        import builtins
        real = builtins.open

        def hidden(file, *args, **kwargs):
            name = file.decode() if isinstance(file, bytes) else file
            if isinstance(name, str) and (name == '/proc' or name.startswith('/proc/')):
                raise FileNotFoundError(2, 'No such file or directory', file)
            return real(file, *args, **kwargs)

        builtins.open = hidden
        try:
            self.assertTrue(alive(pid), 'a live agent looks dead without /proc')
            self.assertTrue(self.fake_agent(pid), 'the fake agent is not recognized without /proc')
            self.assertEqual(self.running(), [pid])
        finally:
            builtins.open = real
        os.remove(self.hold)

    def test_an_installed_driver_starts_with_the_pin_its_build_names(self):
        runtime = os.path.join(self.folder, 'current', 'runtime')
        os.makedirs(os.path.join(runtime, 'adapters', 'cursor'))
        os.makedirs(os.path.join(runtime, 'kernel', 'driver-kit'))
        for name in ('driver', 'schema.json'):
            shutil.copy2(os.path.join(HERE, name), os.path.join(runtime, 'adapters', 'cursor', name))
        for name in ('hostkey.py', 'hosts.json'):
            shutil.copy2(os.path.join(KIT, name), os.path.join(runtime, 'kernel', 'driver-kit', name))
        source = '0123456789abcdef0123456789abcdef01234567'
        with open(os.path.join(runtime, 'openwiz-build.txt'), 'w') as f:
            f.write('openwiz.package.v1\n0.1.1\n%s\nx86_64-unknown-linux-gnu\n' % source)
        p = subprocess.run([os.path.join(runtime, 'adapters', 'cursor', 'driver'), 'start'], input=json.dumps(START),
                           env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, 0, p.stdout)
        [call] = self.calls()
        text = json.loads(call['body'])['prompt']['text']
        for part in ('wizskills.lock', 'https://github.com/openwizdev/OpenWiz', source, 'build-ticket skill'):
            self.assertIn(part, text)

    def test_a_lost_create_cursor_does_not_show_yet_stays_unconfirmed_and_stoppable(self):
        open(self.hold, 'w').close()
        self.fault({'POST /agents': 'pending'})
        code, err = self.driver('start', START)
        self.assertEqual(code, 1, err)
        self.assertNotIn('archived', err['error'])
        self.assertIn('unknown', err['error'])
        run = re.search(r'run-[0-9a-f]{12}', err['error'] + err['next']).group()
        self.assertIn('stop', err['next'])
        self.fault({})
        with open(self.state + '.pending', 'rb') as f:
            late = f.read()
        conn = http.client.HTTPConnection('127.0.0.1', int(self.origin.rpartition(':')[2]), timeout=60)
        conn.request('POST', '/v1/agents', body=late, headers={'Content-Type': 'application/json'})
        self.assertEqual(conn.getresponse().status, 201)
        conn.close()
        [agent] = self.agents().values()
        self.assertFalse(agent['archived'])
        self.assertEqual(self.driver('wake', {'run': run})[0], 1, 'a wake reopened an unconfirmed start')
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        [agent] = self.agents().values()
        self.assertTrue(agent['archived'])
        self.assertEqual(self.running(), [])

    def test_start_refuses_any_harness_but_cursor_and_creates_nothing(self):
        code, out = self.driver('start', dict(START, harness='synthetic-harness'))
        self.assertEqual(code, 1, out)
        self.assertIn('cursor', out['next'])
        self.assertEqual(self.calls(), [])

    def test_a_start_whose_answer_is_lost_archives_its_agent(self):
        open(self.hold, 'w').close()
        self.fault({'POST /agents': 'lost'})
        code, out = self.driver('start', START)
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertNotIn('retry', json.dumps(out))
        [agent] = self.agents().values()
        self.assertTrue(agent['archived'])
        self.assertEqual([r['status'] for r in agent['runs']], ['CANCELLED'])
        self.assertEqual(self.running(), [])

    def test_a_wake_during_a_run_starts_no_second_run_and_one_after_it_follows_up(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [(first, _)] = self.logged(1)
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        time.sleep(0.5)
        self.assertEqual(len(self.logged()), 1, 'a wake during an active run started a second run')
        os.remove(self.hold)
        self.assertTrue(self.until(lambda: not alive(first)), 'the fake run did not end')
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual([r[1] for r in self.logged(2)], ['first', 'woken'], 'a wake after the run started none')
        [agent] = self.agents().values()
        self.assertIn('build-ticket skill', agent['prompt'])

    def test_a_server_error_on_wake_is_transient_and_the_run_stays_wakeable(self):
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: not any(alive(p) for p, _ in self.logged(1))), 'the fake run did not end')
        self.fault({'POST /runs': 500})
        code, err = self.driver('wake', out)
        self.assertEqual(code, 1, err)
        self.assertNotIn('refused', err['error'].lower())
        self.assertEqual(('unknown' in err['error'], '500' in err['error']), (True, True))
        self.assertNotIn('start a new run', err['next'])
        self.assertIn('wake it again', err['next'])
        self.fault({})
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))

    def test_stop_cancels_the_active_run_then_archives_and_never_deletes(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [(first, _)] = self.logged(1)
        self.assertEqual(self.running(), [first])
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(first), 'the active run still works after stop')
        names = [c['call'].split(' /agents/')[0] + ' ' + c['call'].rpartition('/')[2] for c in self.calls()[1:]]
        self.assertEqual([n for n in names if not n.startswith('GET')][-2:], ['POST cancel', 'POST archive'])
        self.assertNotIn('DELETE', ' '.join(names))
        code, err = self.driver('wake', out)
        self.assertEqual(code, 1, err)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)), 'stopping again answers again')
        [agent] = self.agents().values()
        self.assertTrue(agent['archived'])

    def test_stopping_again_does_not_archive_an_agent_cursor_already_archived(self):
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        [agent] = self.agents()
        archive = 'POST /agents/%s/archive' % agent
        before = [c['call'] for c in self.calls()]
        self.assertEqual(before.count(archive), 1)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        after = [c['call'] for c in self.calls()]
        self.assertEqual(after, before + ['GET /agents/' + agent])
        self.assertEqual(after.count(archive), 1, 'stop archived an agent Cursor already shows as archived')

    def test_a_stop_that_cannot_save_still_archives_and_no_wake_reopens_it(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [(first, _)] = self.logged(1)
        os.mkdir(os.path.join(self.env['OPENWIZ_CURSOR_STATE'], out['run'] + '.json.new'))
        code, err = self.driver('stop', out)
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.assertFalse(alive(first), 'stop left the run working')
        [agent] = self.agents().values()
        self.assertTrue(agent['archived'])
        code, err = self.driver('wake', out)
        self.assertEqual(code, 1, err)
        self.assertEqual(len(self.logged()), 1, 'a wake reopened the stopped run')

    def test_a_failed_archive_is_reported_with_the_agent_to_archive(self):
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        self.fault({'POST /archive': 500})
        code, err = self.driver('stop', out)
        self.assertEqual(code, 1, err)
        [agent] = self.agents()
        self.assertIn(agent, err['error'] + err['next'])
        self.assertEqual(self.driver('wake', out)[0], 1, 'a wake was taken after a stop')

    def test_a_refused_login_says_where_the_key_lives_and_shows_no_answer(self):
        self.fault({'POST /agents': 401})
        code, err = self.driver('start', START)
        self.assertEqual(code, 1, err)
        self.assertIn('adapters/cursor/README.md', err['next'])
        self.assertNotIn('told to fail', json.dumps(err))
        self.assertEqual((self.agents(), self.on_disk()), ({}, ''))

    def test_a_lost_create_whose_cleanup_the_helper_refuses_stays_stoppable(self):
        open(self.hold, 'w').close()
        self.fault({'POST /agents': 'lost-keyless'})
        code, err = self.driver('start', START)
        self.assertEqual(code, 1, err)
        self.assertNotIn('nothing was sent', err['error'])
        self.assertIn('unknown', err['error'])
        run = re.search(r'run-[0-9a-f]{12}', err['error'] + err['next']).group()
        self.assertIn('stop', err['next'])
        [agent] = self.agents()
        self.assertIn(agent, self.on_disk())
        with open(self.key_file, 'w') as f:
            f.write(self.key)
        self.fault({})
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertTrue(self.agents()[agent]['archived'])
        self.assertEqual(self.running(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
