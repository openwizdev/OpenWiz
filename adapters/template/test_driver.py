#!/usr/bin/env python3
"""The template driver never leaves an agent running or starts two (#1530, #1549, #1570).

Run: python3 -I adapters/template/test_driver.py   (Linux: it reads /proc)
The kit's five checks against the template are kernel/driver-kit/test_kit.py.
"""
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
NO_PROC = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'fixtures', 'no-proc')
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'fake-harness',
         'model': 'Synthetic 1'}
# A driver whose next save fails once its turn has begun, as a full disk or a removed folder would make it:
# BREAK=folder replaces the state folder with a file; BREAK=write blocks only the run's next write;
# BREAK=readonly makes the state folder read-only.
BREAKS_AFTER_SPAWN = '''import importlib.machinery, importlib.util, os, shutil, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('template', importlib.machinery.SourceFileLoader('template', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
launch = t.launch
def broken(req, run, woken):
    pid = launch(req, run, woken)
    if os.environ['BREAK'] == 'folder':
        shutil.rmtree(t.STATE)
        open(t.STATE, 'w').close()
    elif os.environ['BREAK'] == 'write':
        os.mkdir(os.path.join(t.STATE, run + '.json.new'))
    else:
        os.chmod(t.STATE, 0o500)
    return pid
t.launch = broken
t.main()
'''
# A driver that pauses right after its wake's liveness check, until the file named by RELEASE exists.
PAUSES_AFTER_CHECK = '''import importlib.machinery, importlib.util, os, sys, time
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('template', importlib.machinery.SourceFileLoader('template', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
running = t.running
def paused(*args):
    answer = running(*args)
    open(os.environ['PAUSED'], 'w').close()
    while not os.path.exists(os.environ['RELEASE']):
        time.sleep(0.01)
    return answer
t.running = paused
t.main()
'''


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


class Template(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.env = dict(os.environ, KIT_TEST=self.mark, FAKE_TURNS=self.turns, FAKE_HOLD=self.hold,
                        OPENWIZ_TEMPLATE_STATE=os.path.join(self.folder, 'state'),
                        PATH=os.path.join(HERE, 'fixtures') + os.pathsep + os.environ.get('PATH', ''))

    def tearDown(self):
        os.chmod(self.folder, 0o700)
        for root, dirs, _ in os.walk(self.folder):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o700)
        for pid in self.marked() + [child for _, child, _ in self.logged() if self.sleeps(child)]:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def marked(self):
        """Every live process this test started, through the driver or not."""
        found = []
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0') and alive(int(pid)):
                        found.append(int(pid))
            except OSError:
                pass
        return found

    def sleeps(self, pid):
        """Whether pid is still one of the fake harness's `sleep 120` children."""
        try:
            with open('/proc/%d/cmdline' % pid, 'rb') as f:
                return f.read() == b'sleep\x00120\x00' and alive(pid)
        except OSError:
            return False

    def wrapper(self, name, source):
        path = os.path.join(self.folder, name)
        with open(path, 'w') as f:
            f.write('#!%s\n' % sys.executable + source % DRIVER)
        os.chmod(path, 0o700)
        return path

    def call(self, cmd, request, driver=DRIVER, **env):
        p = subprocess.run([driver, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=60)
        return p.returncode, json.loads(p.stdout)

    def logged(self, count=None):
        """The turns the fake harness logged: [(turn pid, child pid, first|woken)], waiting for `count`."""
        deadline = time.monotonic() + 10
        while True:
            try:
                with open(self.turns) as f:
                    turns = [(int(a), int(b), c) for a, b, c in (line.split() for line in f)]
            except FileNotFoundError:
                turns = []
            if count is None or len(turns) >= count or time.monotonic() > deadline:
                return turns
            time.sleep(0.05)

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def test_stop_ends_what_the_turn_left_behind_after_it_exits(self):
        # catches: a stop that signals only the turn's own process group, after checking only the turn's
        # leader, so a worker the harness started in its own session keeps running once the leader exits
        # while stop still answers stopped (#1530).
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, child, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        self.assertTrue(alive(child))
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.marked(), [], 'a process the run started still runs after stop')
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)), 'stopping again answers again')

    def test_wake_while_a_turn_runs_starts_no_second_turn(self):
        # catches: a wake during a long turn starting a second agent on the same ticket beside the first
        # (#1549), and a wake after that turn ends starting nothing.
        open(self.hold, 'w').close()
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, _, _)] = self.logged(1)
        self.assertEqual(self.call('wake', out), (0, dict(out, woke=True)))
        time.sleep(0.5)  # time for a second turn to log itself, if one was started
        self.assertEqual(len(self.logged()), 1, 'a wake during a running turn started a second turn')
        os.remove(self.hold)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        self.assertEqual(self.call('wake', out), (0, dict(out, woke=True)))
        self.assertEqual([t[2] for t in self.logged(2)], ['first', 'woken'], 'a wake after the turn started none')

    def test_start_with_nowhere_to_save_starts_nothing(self):
        # catches: a start that launches its turn before it saves the run, then fails to save it, leaving
        # an agent running with no run id to stop it, and an error that says to retry (#1570).
        blocker = os.path.join(self.folder, 'a-file')
        open(blocker, 'w').close()
        for state in (blocker, os.path.join(blocker, 'state')):
            with self.subTest(state=state):
                code, out = self.call('start', START, OPENWIZ_TEMPLATE_STATE=state)
                self.assertEqual(code, 1, out)
                time.sleep(0.5)  # time for a turn to log itself, if one was started
                self.assertEqual((self.logged(), self.marked()), ([], []), 'it started a turn with nowhere to save')
                self.assertNotIn('retry', json.dumps(out))

    def test_save_failure_after_spawn_reports_unknown(self):
        # catches: a start whose save fails once its turn has begun answering the generic "retry", which
        # starts a second agent while the first runs on with no run id (#1570).
        driver = self.wrapper('breaks-after-spawn', BREAKS_AFTER_SPAWN)
        for mode in ('folder', 'write'):
            with self.subTest(mode=mode):
                state = os.path.join(self.folder, 'state-' + mode)
                code, out = self.call('start', START, driver=driver, BREAK=mode, OPENWIZ_TEMPLATE_STATE=state)
                self.assertEqual(code, 1, out)
                self.assertIn('unknown', out['error'])
                self.assertNotIn('retry', json.dumps(out))
                self.assertTrue(self.until(lambda: not self.marked()), 'the turn it could not save still runs')
        # catches: the run's first save, still on disk, letting a wake on the run id in the error start it again.
        run = re.search(r'run-[0-9a-f]{12}', out['error']).group()
        turns = len(self.logged())
        code, _ = self.call('wake', {'run': run}, OPENWIZ_TEMPLATE_STATE=state)
        time.sleep(0.5)  # time for a turn to log itself, if one was started
        self.assertEqual((code, len(self.logged()), self.marked()), (1, turns, []), 'a wake restarted the failed run')


    def test_start_record_is_not_wakeable_before_it_is_confirmed(self):
        # catches: a start whose final save fails leaving its first record on disk as a wakeable run (the
        # folder was read-only, so it could not be removed); once the folder is writable again, a wake on the
        # run id from the error starts the failed run (R5).
        if os.geteuid() == 0:
            self.skipTest('root ignores a read-only folder')
        driver, state = self.wrapper('breaks-after-spawn', BREAKS_AFTER_SPAWN), os.path.join(self.folder, 'state')
        code, out = self.call('start', START, driver=driver, BREAK='readonly')
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertTrue(self.until(lambda: not self.marked()), 'the turn it could not save still runs')
        os.chmod(state, 0o700)
        turns = len(self.logged())
        code, _ = self.call('wake', {'run': re.search(r'run-[0-9a-f]{12}', out['error']).group()})
        time.sleep(0.5)  # time for a turn to log itself, if one was started
        self.assertEqual((code, len(self.logged()), self.marked()), (1, turns, []), 'a wake started the failed run')

    def test_stop_ends_a_worker_with_a_clean_environment(self):
        # catches: a stop that finds the run's processes only by the OPENWIZ_RUN mark they inherit, so a worker
        # the harness started with a clean environment keeps working after stop answers stopped (R2).
        code, out = self.call('start', START, FAKE_CLEAN='1')
        self.assertEqual(code, 0, out)
        [(turn, child, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        self.assertTrue(alive(child))
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(child), 'a worker without the mark still runs after stop')

    def test_simultaneous_wakes_start_one_turn(self):
        # catches: two wakes that both pass the liveness check before either saves its turn, so both launch
        # and two agents work on the ticket (R1).
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, _, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        open(self.hold, 'w').close()
        paused, release = os.path.join(self.folder, 'paused'), os.path.join(self.folder, 'release')
        first = subprocess.Popen([self.wrapper('pauses', PAUSES_AFTER_CHECK), 'wake'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, env=dict(self.env, PAUSED=paused, RELEASE=release))
        first.stdin.write(json.dumps(out).encode())
        first.stdin.close()
        self.assertTrue(self.until(lambda: os.path.exists(paused)), 'the first wake never reached its check')
        second = subprocess.Popen([DRIVER, 'wake'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.env)
        second.stdin.write(json.dumps(out).encode())
        second.stdin.close()
        try:  # without a lock the second wake finishes now; with one it waits for the first
            second.wait(3)
        except subprocess.TimeoutExpired:
            pass
        open(release, 'w').close()
        answers = [json.loads(p.stdout.read()) for p in (first, second)]
        self.assertEqual([p.wait(30) for p in (first, second)], [0, 0])
        self.assertEqual(answers, [dict(out, woke=True)] * 2)
        time.sleep(0.5)  # time for a second turn to log itself, if one was started
        self.assertEqual([t[2] for t in self.logged()], ['first', 'woken'], 'two wakes started two turns')

    def test_stop_ends_the_run_when_it_cannot_save(self):
        # catches: a stop whose save fails before it signals anything, leaving the agent working, and a wake
        # that then launches against state it cannot update (R3).
        open(self.hold, 'w').close()
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, child, _)] = self.logged(1)
        os.mkdir(os.path.join(self.folder, 'state', out['run'] + '.json.new'))
        code, err = self.call('stop', out)
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.assertEqual((alive(turn), alive(child), self.marked()), (False, False, []), 'stop left the run working')
        code, err = self.call('wake', out)
        time.sleep(0.5)  # time for a turn to log itself, if one was started
        self.assertEqual((code, len(self.logged()), self.marked()), (1, 1, []), 'a wake launched it again')

    def test_wake_checks_its_save_before_and_after_spawn(self):
        # catches: a wake that launches before it knows it can save the turn, and a save failure after the
        # launch answering the generic "retry", whose retry starts a second turn beside the first (R4).
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, _, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        blocked = os.path.join(self.folder, 'state', out['run'] + '.json.new')
        os.mkdir(blocked)
        code, err = self.call('wake', out)
        time.sleep(0.5)  # time for a turn to log itself, if one was started
        self.assertEqual((code, len(self.logged())), (1, 1), 'a wake launched with nowhere to save its turn')
        self.assertIn('nothing was started', err['error'])  # not ended after a launch: never launched at all
        self.assertNotIn('retry', json.dumps(err))
        os.rmdir(blocked)
        open(self.hold, 'w').close()
        before = set(self.marked())  # the first turn's worker still runs
        code, err = self.call('wake', out, driver=self.wrapper('breaks-after-spawn', BREAKS_AFTER_SPAWN),
                              BREAK='write')
        self.assertEqual(code, 1, err)
        self.assertIn('unknown', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        self.assertTrue(self.until(lambda: set(self.marked()) <= before), 'the unsaved turn still runs')


    def test_without_proc_as_on_macos_stop_ends_each_grandchild(self):
        for worker in ({}, {'FAKE_CLEAN': '1', 'FAKE_SAME_GROUP': '1'}):
            with self.subTest(**worker):
                self.tearDown()
                self.setUp()
                macos = dict(worker, PATH=NO_PROC + os.pathsep + self.env['PATH'], NO_PROC_PYTHON=sys.executable)
                code, out = self.call('start', START, **macos)
                self.assertEqual(code, 0, out)
                [(turn, child, _)] = self.logged(1)
                self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
                self.assertTrue(alive(child))
                self.assertEqual(self.call('stop', out, **macos), (0, dict(out, stopped=True)))
                self.assertFalse(alive(child), 'a grandchild of the harness still runs after stop')
                self.assertEqual(self.marked(), [], 'a process the run started still runs after stop')


if __name__ == '__main__':
    unittest.main(verbosity=2)
