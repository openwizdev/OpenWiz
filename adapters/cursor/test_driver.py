#!/usr/bin/env python3
"""The Cursor cloud agents driver passes the kit on a synthetic Cursor, and never leaves an agent running.

Run: python3 -I adapters/cursor/test_driver.py   (Linux: it reads /proc)
`fixtures/bin/curl` is a synthetic Cursor cloud agents API behind a fake `curl`; nothing reaches the network.
"""
import json
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
TOKEN = 'synthetic-' + 'x' * 24  # in the driver's environment as CURSOR_API_KEY: it must never pass it on


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
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.log = os.path.join(self.folder, 'calls')
        self.env = dict(os.environ, KIT_TRACKER=self.tracker, KIT_TEST=self.mark, CURSOR_API_KEY=TOKEN,
                        FAKE_TURNS=self.turns, FAKE_HOLD=self.hold, FAKE_CURSOR_LOG=self.log,
                        FAKE_CURSOR_STATE=os.path.join(self.folder, 'cursor.json'),
                        OPENWIZ_CURSOR_STATE=os.path.join(self.folder, 'state'),
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + os.environ.get('PATH', ''))

    def tearDown(self):
        for pid in self.marked():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def marked(self):
        """Every live process this test started that still carries its mark."""
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
        """The runs the fake agent logged: [(pid, first|woken)], waiting up to 10 seconds for `count` of them."""
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

    def test_kit_passes_all_five(self):
        # catches: a driver that runs a local harness instead of Cursor's API, a wake that opens a second agent
        # (a second note), a stop that leaves the run working, and a key passed to the `curl` processes it starts.
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
        # catches: a key put on curl's command line (`-u`, an Authorization header) or in the request body, a
        # start that lets Cursor mint the agent id so a lost answer leaves an agent no stop can reach, and a
        # prompt that never tells the cloud agent where the pinned skills are.
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [call] = self.calls()
        self.assertEqual(call['call'], 'POST /agents')
        self.assertIn('--netrc', call['argv'])
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

    def test_start_refuses_any_harness_but_cursor_and_creates_nothing(self):
        # catches: a driver that quietly runs Cursor's own agent when the user asked for another harness.
        code, out = self.driver('start', dict(START, harness='synthetic-harness'))
        self.assertEqual(code, 1, out)
        self.assertIn('cursor', out['next'])
        self.assertEqual(self.calls(), [])

    def test_a_start_whose_answer_is_lost_archives_its_agent(self):
        # catches: a create whose answer never came back leaving a cloud agent working on the ticket with no
        # run id to stop it, and an error that says to retry, which starts a second agent beside it.
        code, out = self.driver('start', START, FAKE_CURSOR_FAIL='POST /agents=lost')
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertNotIn('retry', json.dumps(out))
        [agent] = self.agents().values()
        self.assertTrue(agent['archived'])
        self.assertEqual([r['status'] for r in agent['runs']], ['CANCELLED'])
        self.assertEqual(self.marked(), [])

    def test_a_wake_during_a_run_starts_no_second_run_and_one_after_it_follows_up(self):
        # catches: a wake that sends a follow-up while the agent's run is active (Cursor refuses it as busy, so a
        # driver that reports that as an error tells the fleet the run is lost), and a wake after the run ended
        # that starts nothing.
        open(self.hold, 'w').close()
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        [(first, _)] = self.logged(1)
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        time.sleep(0.5)  # time for a second run to log itself, if one was started
        self.assertEqual(len(self.logged()), 1, 'a wake during an active run started a second run')
        os.remove(self.hold)
        self.assertTrue(self.until(lambda: not alive(first)), 'the fake run did not end')
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual([r[1] for r in self.logged(2)], ['first', 'woken'], 'a wake after the run started none')
        [agent] = self.agents().values()
        self.assertIn('build-ticket skill', agent['prompt'])

    def test_stop_cancels_the_active_run_then_archives_and_never_deletes(self):
        # catches: a stop that archives without cancelling (the run may keep working), one that deletes the agent
        # for good, a wake after stop that is taken, and a second stop that fails instead of answering again.
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
        # catches: a stop whose save fails before it reaches Cursor, leaving the agent working, and a wake that
        # then trusts the stale local record and sends a follow-up.
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
        # catches: a stop that answers stopped while Cursor never confirmed the archive, so an agent nobody
        # watches keeps its machine.
        code, out = self.driver('start', START)
        self.assertEqual(code, 0, out)
        code, err = self.driver('stop', out, FAKE_CURSOR_FAIL='POST /archive=500')
        self.assertEqual(code, 1, err)
        [agent] = self.agents()
        self.assertIn(agent, err['error'] + err['next'])
        self.assertEqual(self.driver('wake', out)[0], 1, 'a wake was taken after a stop')

    def test_a_refused_login_says_where_the_key_lives_and_shows_no_answer(self):
        # catches: a driver that asks for the key in its input or echoes Cursor's error body (which may quote
        # what was sent) instead of pointing to the user's own ~/.netrc.
        code, err = self.driver('start', START, FAKE_CURSOR_FAIL='POST /agents=401')
        self.assertEqual(code, 1, err)
        self.assertIn('~/.netrc', err['next'])
        self.assertNotIn('fake_failure', json.dumps(err))
        self.assertEqual(self.agents(), {})


if __name__ == '__main__':
    unittest.main(verbosity=2)
