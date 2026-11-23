#!/usr/bin/env python3
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
REPO = os.path.realpath(os.path.join(HERE, '..', '..'))
HARNESSES = ('claude', 'claude-code', 'codex', 'gemini', 'opencode', 'openclaw', 'cursor-agent', 'amp', 'aider',
             'goose')
TOOLS = ('sh', 'ps', 'lsof', 'awk', 'sleep', 'dirname')
START = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'fake-harness',
         'model': 'Synthetic 1'}
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


def pinned_path(folder, *fixtures):
    tools = os.path.join(folder, 'tools')
    os.makedirs(tools)
    for name in TOOLS:
        if shutil.which(name):
            os.symlink(shutil.which(name), os.path.join(tools, name))
    os.symlink(sys.executable, os.path.join(tools, 'python3'))
    return no_real_harness(os.pathsep.join(fixtures + (tools,)))


def no_real_harness(path):
    for name in HARNESSES:
        found = shutil.which(name, path=path)
        if found and not os.path.realpath(found).startswith(REPO + os.sep):
            raise AssertionError('%s on the PATH is %s, outside the fixtures: a test could launch a real harness'
                                 % (name, found))
    return path


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


def read(path):
    with open(path) as f:
        return f.read()


HANDS_OFF_AS_IT_EXITS = """#!%s
import os, subprocess, time
time.sleep(0.7)
worker = subprocess.Popen(['sleep', '120'], start_new_session=True, stdin=subprocess.DEVNULL)
with open(%r, 'w') as f:
    f.write('%%d %%d' %% (os.getpid(), worker.pid))
"""

class Template(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.env = dict(os.environ, KIT_TEST=self.mark, FAKE_TURNS=self.turns, FAKE_HOLD=self.hold,
                        OPENWIZ_TEMPLATE_STATE=os.path.join(self.folder, 'state'),
                        PATH=pinned_path(self.folder, os.path.join(HERE, 'fixtures')))

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
        env = dict(self.env, **env)
        no_real_harness(env['PATH'])
        p = subprocess.run([driver, cmd], input=json.dumps(request), env=env, capture_output=True, text=True,
                           timeout=60)
        return p.returncode, json.loads(p.stdout)

    def logged(self, count=None):
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

    def test_no_harness_outside_the_fixtures_is_on_the_tests_path(self):
        outside = os.path.join(self.folder, 'outside')
        os.mkdir(outside)
        with open(os.path.join(outside, 'claude'), 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(os.path.join(outside, 'claude'), 0o700)
        old = os.environ['PATH']
        os.environ['PATH'] = outside + os.pathsep + old
        try:
            self.setUp()
        finally:
            os.environ['PATH'] = old
        self.assertIsNone(shutil.which('claude', path=self.env['PATH']), 'the PATH reaches a real claude')
        self.assertEqual(shutil.which('fake-harness', path=self.env['PATH']),
                         os.path.join(HERE, 'fixtures', 'fake-harness'))
        with self.assertRaisesRegex(AssertionError, 'could launch a real harness'):
            self.call('start', dict(START, harness='claude'), PATH=outside + os.pathsep + self.env['PATH'])

    def test_stop_ends_what_the_turn_left_behind_after_it_exits(self):
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, child, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        self.assertTrue(alive(child))
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.marked(), [], 'a process the run started still runs after stop')
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)), 'stopping again answers again')

    def test_wake_while_a_turn_runs_starts_no_second_turn(self):
        open(self.hold, 'w').close()
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, _, _)] = self.logged(1)
        self.assertEqual(self.call('wake', out), (0, dict(out, woke=True)))
        time.sleep(0.5)
        self.assertEqual(len(self.logged()), 1, 'a wake during a running turn started a second turn')
        os.remove(self.hold)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        self.assertEqual(self.call('wake', out), (0, dict(out, woke=True)))
        self.assertEqual([t[2] for t in self.logged(2)], ['first', 'woken'], 'a wake after the turn started none')

    def test_start_with_nowhere_to_save_starts_nothing(self):
        blocker = os.path.join(self.folder, 'a-file')
        open(blocker, 'w').close()
        for state in (blocker, os.path.join(blocker, 'state')):
            with self.subTest(state=state):
                code, out = self.call('start', START, OPENWIZ_TEMPLATE_STATE=state)
                self.assertEqual(code, 1, out)
                time.sleep(0.5)
                self.assertEqual((self.logged(), self.marked()), ([], []), 'it started a turn with nowhere to save')
                self.assertNotIn('retry', json.dumps(out))

    def test_save_failure_after_spawn_reports_unknown(self):
        driver = self.wrapper('breaks-after-spawn', BREAKS_AFTER_SPAWN)
        for mode in ('folder', 'write'):
            with self.subTest(mode=mode):
                state = os.path.join(self.folder, 'state-' + mode)
                code, out = self.call('start', START, driver=driver, BREAK=mode, OPENWIZ_TEMPLATE_STATE=state)
                self.assertEqual(code, 1, out)
                self.assertIn('unknown', out['error'])
                self.assertNotIn('retry', json.dumps(out))
                self.assertTrue(self.until(lambda: not self.marked()), 'the turn it could not save still runs')
        run = re.search(r'run-[0-9a-f]{12}', out['error']).group()
        turns = len(self.logged())
        code, _ = self.call('wake', {'run': run}, OPENWIZ_TEMPLATE_STATE=state)
        time.sleep(0.5)
        self.assertEqual((code, len(self.logged()), self.marked()), (1, turns, []), 'a wake restarted the failed run')


    def test_start_record_is_not_wakeable_before_it_is_confirmed(self):
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
        time.sleep(0.5)
        self.assertEqual((code, len(self.logged()), self.marked()), (1, turns, []), 'a wake started the failed run')

    def test_stop_ends_a_worker_with_a_clean_environment(self):
        code, out = self.call('start', START, FAKE_CLEAN='1')
        self.assertEqual(code, 0, out)
        [(turn, child, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        self.assertTrue(alive(child))
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(child), 'a worker without the mark still runs after stop')

    def test_simultaneous_wakes_start_one_turn(self):
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
        try:
            second.wait(3)
        except subprocess.TimeoutExpired:
            pass
        open(release, 'w').close()
        answers = [json.loads(p.stdout.read()) for p in (first, second)]
        self.assertEqual([p.wait(30) for p in (first, second)], [0, 0])
        self.assertEqual(answers, [dict(out, woke=True)] * 2)
        time.sleep(0.5)
        self.assertEqual([t[2] for t in self.logged()], ['first', 'woken'], 'two wakes started two turns')

    def test_stop_ends_the_run_when_it_cannot_save(self):
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
        time.sleep(0.5)
        self.assertEqual((code, len(self.logged()), self.marked()), (1, 1, []), 'a wake launched it again')

    def test_wake_checks_its_save_before_and_after_spawn(self):
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [(turn, _, _)] = self.logged(1)
        self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
        blocked = os.path.join(self.folder, 'state', out['run'] + '.json.new')
        os.mkdir(blocked)
        code, err = self.call('wake', out)
        time.sleep(0.5)
        self.assertEqual((code, len(self.logged())), (1, 1), 'a wake launched with nowhere to save its turn')
        self.assertIn('nothing was started', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        os.rmdir(blocked)
        open(self.hold, 'w').close()
        before = set(self.marked())
        code, err = self.call('wake', out, driver=self.wrapper('breaks-after-spawn', BREAKS_AFTER_SPAWN),
                              BREAK='write')
        self.assertEqual(code, 1, err)
        self.assertIn('unknown', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        self.assertTrue(self.until(lambda: set(self.marked()) <= before), 'the unsaved turn still runs')


    def recorded_by_supervisors(self, run):
        state, found = self.env['OPENWIZ_TEMPLATE_STATE'], set()
        for name in os.listdir(state):
            if name.startswith(run + '.') and name.endswith('.sup'):
                try:
                    with open(os.path.join(state, name)) as f:
                        found.update(int(p) for p in json.load(f)['kept'])
                except (OSError, ValueError):
                    pass
        return found

    def harness_handing_off_as_it_exits(self, name):
        folder, pids = os.path.join(self.folder, 'hands-off'), os.path.join(self.folder, 'handed-off')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), 'w') as f:
            f.write(HANDS_OFF_AS_IT_EXITS % (sys.executable, pids))
        os.chmod(os.path.join(folder, name), 0o700)
        return folder, pids

    def handed_off(self, pids):
        written = lambda: os.path.exists(pids) and len(read(pids).split()) == 2
        self.until(written)
        self.assertTrue(written(), 'the turn never handed off')
        with open(pids) as f:
            turn, worker = map(int, f.read().split())
        self.until(lambda: not alive(turn))
        self.assertFalse(alive(turn), 'the turn did not exit')
        time.sleep(1)
        self.assertTrue(alive(worker))
        return worker

    def test_without_proc_as_on_macos_stop_ends_a_worker_handed_off_as_the_turn_exits(self):
        folder, pids = self.harness_handing_off_as_it_exits('fake-harness')
        macos = {'PATH': folder + os.pathsep + NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.call('start', START, **macos)
        self.assertEqual(code, 0, out)
        worker = self.handed_off(pids)
        self.assertEqual(self.call('stop', out, **macos), (0, dict(out, stopped=True)))
        self.assertFalse(alive(worker), 'a worker the turn handed off as it exited still runs after stop')

    def test_without_proc_as_on_macos_stop_says_when_lsof_cannot_check_the_output_file(self):
        for broken in (False, True):
            with self.subTest(lsof_fails=broken):
                self.tearDown()
                self.setUp()
                macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
                code, out = self.call('start', START, **macos)
                self.assertEqual(code, 0, out)
                self.logged(1)
                stop = dict(self.env, **macos)
                if broken:
                    folder = os.path.join(self.folder, 'broken-lsof')
                    os.mkdir(folder)
                    with open(os.path.join(folder, 'lsof'), 'w') as f:
                        f.write('#!/bin/sh\necho "lsof: synthetic failure %s" >&2\nexit 1\n' % self.mark)
                    os.chmod(os.path.join(folder, 'lsof'), 0o700)
                    stop['PATH'] = folder + os.pathsep + stop['PATH']
                p = subprocess.run([DRIVER, 'stop'], input=json.dumps(out), env=stop, capture_output=True, text=True,
                                   timeout=60)
                self.assertEqual((p.returncode, json.loads(p.stdout)), (0, dict(out, stopped=True)))
                self.assertEqual('could not check' in p.stderr, broken, p.stderr)
                self.assertNotIn(self.mark, p.stderr)

    def asked_ps_for_environments(self, calls):
        with open(calls) as f:
            asked = f.read().splitlines()
        self.assertTrue(any(' -A ' in ' %s ' % c for c in asked), 'the driver never listed processes through ps')
        return [c for c in asked if '-E' in c.split() or 'e' in c.split()]

    def logging_ps(self, calls):
        folder = os.path.join(self.folder, 'logging-ps')
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, 'ps'), 'w') as f:
            f.write('#!/bin/sh\nprintf \'%%s\\n\' "$*" >> %s\nexec %s "$@"\n' % (calls, os.path.join(NO_PROC, 'ps')))
        os.chmod(os.path.join(folder, 'ps'), 0o700)
        return folder

    def test_without_proc_as_on_macos_stop_ends_each_grandchild(self):
        for worker in ({}, {'FAKE_CLEAN': '1', 'FAKE_SAME_GROUP': '1'}):
            with self.subTest(**worker):
                self.tearDown()
                self.setUp()
                calls = os.path.join(self.folder, 'ps-calls')
                macos = dict(worker, PATH=self.logging_ps(calls) + os.pathsep + NO_PROC + os.pathsep + self.env['PATH'],
                             NO_PROC_PYTHON=sys.executable)
                closes_its_output = not worker
                if closes_its_output:
                    open(self.hold, 'w').close()
                code, out = self.call('start', START, **macos)
                self.assertEqual(code, 0, out)
                [(turn, child, _)] = self.logged(1)
                if closes_its_output:
                    self.assertTrue(self.until(lambda: child in self.recorded_by_supervisors(out['run'])),
                                    'the supervisor never recorded the detached child')
                    os.remove(self.hold)
                self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
                self.assertTrue(alive(child))
                self.assertEqual(self.call('stop', out, **macos), (0, dict(out, stopped=True)))
                self.assertFalse(alive(child), 'a grandchild of the harness still runs after stop')
                self.assertEqual(self.marked(), [], 'a process the run started still runs after stop')
                self.assertEqual(self.asked_ps_for_environments(calls), [], 'the driver asked ps for process environments')


if __name__ == '__main__':
    unittest.main(verbosity=2)
