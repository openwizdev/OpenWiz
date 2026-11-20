#!/usr/bin/env python3
import json
import re
import os
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
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'kit.py')
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'cursor',
         'model': 'synthetic-model-1'}
ENV_KEYS = ('PATH', 'KIT_TRACKER', 'KIT_TEST', 'CURSOR_API_KEY', 'FAKE_TURNS', 'FAKE_HOLD', 'FAKE_CURSOR_LOG',
            'FAKE_CURSOR_STATE', 'OPENWIZ_CURSOR_STATE')
TOKEN = 'synthetic-' + 'x' * 24


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


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
        self.log = os.path.join(self.folder, 'calls')
        self.env = dict(os.environ, KIT_TRACKER=self.tracker, KIT_TEST=self.mark, CURSOR_API_KEY=TOKEN,
                        FAKE_TURNS=self.turns, FAKE_HOLD=self.hold, FAKE_CURSOR_LOG=self.log,
                        FAKE_CURSOR_STATE=os.path.join(self.folder, 'cursor.json'),
                        OPENWIZ_CURSOR_STATE=os.path.join(self.folder, 'state'),
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + python)

    def tearDown(self):
        for pid in self.marked():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def marked(self):
        found = []
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0') and alive(int(pid)):
                        found.append(int(pid))
            except OSError:
                pass
        return found

    def driver(self, cmd, request, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, json.loads(p.stdout)

    def calls(self):
        try:
            with open(self.log) as f:
                return [json.loads(x) for x in f]
        except FileNotFoundError:
            return []

    def agents(self):
        try:
            with open(self.env['FAKE_CURSOR_STATE']) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

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
        found = {name: shutil.which(name, path=self.env['PATH']) for name in ('curl', 'claude', 'codex', 'agent', 'gh')}
        self.assertEqual(found, dict.fromkeys(found, None) | {'curl': os.path.join(HERE, 'fixtures', 'bin', 'curl')})
        self.assertEqual(sorted(os.listdir(self.env['PATH'].split(os.pathsep)[1])), ['python3'])
        self.assertEqual(sorted(self.env), sorted(ENV_KEYS))

    def test_kit_passes_all_five(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site',
                            '--ticket', '7', '--harness', 'cursor', '--model', 'synthetic-model-1',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver']), p.stderr)

    def test_start_creates_one_agent_under_an_id_it_saved_first_with_no_login(self):
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [call] = self.calls()
        self.assertEqual(call['call'], 'POST /agents')
        self.assertEqual(call['argv'][1:5], ['--variable', '%CURSOR_API_KEY', '--expand-oauth2-bearer',
                                             '{{CURSOR_API_KEY}}'])
        self.assertNotIn(TOKEN, json.dumps(call))
        body = json.loads(call['body'])
        self.assertEqual(body['repos'], [{'url': 'https://github.com/example/site'}])
        self.assertEqual(body['model'], {'id': 'synthetic-model-1'})
        self.assertIs(body['autoCreatePR'], False)
        with open(os.path.join(HERE, '..', '..', 'wizskills.lock')) as f:
            lock = json.load(f)
        for part in ('example/site', '#7', 'build-ticket skill', lock['version'], lock['commit'], lock['tree']):
            self.assertIn(part, body['prompt']['text'])
        with open(os.path.join(self.env['OPENWIZ_CURSOR_STATE'], out['run'] + '.json')) as f:
            self.assertEqual(json.load(f)['agent'], body['agentId'])
        self.assertEqual(list(self.agents()), [body['agentId']])

    def test_the_key_never_passes_through_the_driver(self):
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        outputs = [json.dumps(out)]
        for cmd in ('wake', 'stop'):
            self.until(lambda: not any(alive(p) for p, _ in self.logged(1)))
            code, answer = self.driver(cmd, out)
            self.assertEqual(code, 0, answer)
            outputs.append(json.dumps(answer))
        with open(DRIVER) as f:
            source = f.read()
        self.assertNotIn(TOKEN, source)
        self.assertEqual(re.findall(r'\benviron\b\S*', source), ["environ.get('OPENWIZ_CURSOR_STATE')"])
        self.assertEqual([x for x in ('getenv', 'environb', 'env=') if x in source], [])
        calls = self.calls()
        self.assertEqual([c['call'].split(' ')[0] for c in calls], ['POST', 'GET', 'POST', 'GET', 'POST', 'POST'])
        self.assertNotIn(TOKEN, json.dumps(calls) + ''.join(outputs))
        self.assertEqual({tuple(c['key_in']) for c in calls}, {('CURSOR_API_KEY',)})

    def test_an_old_curl_or_a_missing_key_is_a_clear_error_and_sends_nothing(self):
        code, err = self.driver('start', START, FAKE_CURL_VERSION='8.2.1')
        self.assertEqual(code, 1, err)
        self.assertIn('8.3', err['error'] + err['next'])
        for key in (None, ''):
            env = dict(self.env, CURSOR_API_KEY=key) if key is not None else \
                {k: v for k, v in self.env.items() if k != 'CURSOR_API_KEY'}
            p = subprocess.run([DRIVER, 'start'], input=json.dumps(START), env=env, capture_output=True, text=True,
                               timeout=60)
            err = json.loads(p.stdout)
            self.assertEqual(p.returncode, 1, err)
            self.assertIn('CURSOR_API_KEY', err['error'])
            self.assertNotIn('unknown', err['error'])
        self.assertEqual((self.calls(), self.agents()), ([], {}))

    def test_start_refuses_any_harness_but_cursor_and_creates_nothing(self):
        code, out = self.driver('start', dict(START, harness='synthetic-harness'))
        self.assertEqual(code, 1, out)
        self.assertIn('cursor', out['next'])
        self.assertEqual(self.calls(), [])

    def test_a_start_whose_answer_is_lost_archives_its_agent(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', START, FAKE_CURSOR_FAIL='POST /agents=lost')
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertNotIn('retry', json.dumps(out))
        [agent] = self.agents().values()
        self.assertTrue(agent['archived'])
        self.assertEqual([r['status'] for r in agent['runs']], ['CANCELLED'])
        self.assertEqual(self.marked(), [])

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

    def test_stop_cancels_the_active_run_then_archives_and_never_deletes(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [(first, _)] = self.logged(1)
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
        code, err = self.driver('stop', out, FAKE_CURSOR_FAIL='POST /archive=500')
        self.assertEqual(code, 1, err)
        [agent] = self.agents()
        self.assertIn(agent, err['error'] + err['next'])
        self.assertEqual(self.driver('wake', out)[0], 1, 'a wake was taken after a stop')

    def test_a_refused_login_says_where_the_key_lives_and_shows_no_answer(self):
        code, err = self.driver('start', START, FAKE_CURSOR_FAIL='POST /agents=401')
        self.assertEqual(code, 1, err)
        self.assertIn('CURSOR_API_KEY', err['next'])
        self.assertNotIn('told to fail', json.dumps(err))
        self.assertEqual(self.agents(), {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
