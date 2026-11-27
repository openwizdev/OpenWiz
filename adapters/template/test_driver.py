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
sys.path.insert(0, os.path.join(REPO, 'kernel', 'driver-kit'))
from stubs import stub_path
sys.path.pop(0)

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
REFUSAL = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
           "at the host's default")
CANT_FORM = '''import importlib.machinery, importlib.util, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('template', importlib.machinery.SourceFileLoader('template', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
t.VERSION['can'] = [c for c in t.VERSION['can'] if c != 'effort']
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
PRE_1590_TEMPLATE = '''import json, os, secrets, subprocess, sys
cmd = sys.argv[1]
req = json.loads(sys.stdin.read())
state_dir = os.environ['OPENWIZ_TEMPLATE_STATE']
os.makedirs(state_dir, mode=0o700, exist_ok=True)
def launch(start_req, run, woken):
    what = 'You were woken: read the ticket again and carry on' if woken else 'Build the ticket'
    prompt = '%s: %s#%d, with the %s skill.' % (what, start_req['repository'], start_req['ticket'], start_req['skill'])
    return subprocess.Popen([start_req['harness'], '--model', start_req['model'], '-p', prompt],
                            env=dict(os.environ, OPENWIZ_RUN=run), start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).pid
if cmd == 'start':
    run = 'run-' + secrets.token_hex(6)
    state = {'request': req, 'turns': [launch(req, run, False)], 'stopped': False}
    with open(os.path.join(state_dir, run + '.json'), 'w') as f:
        json.dump(state, f)
    print(json.dumps({'run': run}))
elif cmd == 'wake':
    run = req['run']
    path = os.path.join(state_dir, run + '.json')
    with open(path) as f:
        state = json.load(f)
    state['turns'].append(launch(state['request'], run, True))
    with open(path, 'w') as f:
        json.dump(state, f)
    print(json.dumps({'run': run, 'woke': True}))
'''
CHECKPOINT_HARNESS = '''import os, signal, sys, time
if os.environ.get('IGNORE_TERM'):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    def on_term(*_):
        time.sleep(0.25)
        with open(os.environ['CHECKPOINT'], 'w') as f:
            f.write('saved')
        sys.exit(0)
    signal.signal(signal.SIGTERM, on_term)
with open(os.environ['READY'], 'w') as f:
    f.write(str(os.getpid()))
while True:
    time.sleep(0.05)
'''
LEGACY_STOP_WRAPPER = '''import importlib.machinery, importlib.util, os, re, signal, sys
sys.dont_write_bytecode = True
if os.environ.get('AUDIT_ENVIRON') or os.environ.get('DENY_ENVIRON'):
    seen, deny = os.environ.get('AUDIT_ENVIRON'), os.environ.get('DENY_ENVIRON')
    def audit(event, args):
        if event == 'open' and isinstance(args[0], (str, bytes)):
            path = os.fsdecode(args[0])
            if re.fullmatch(r'/proc/[0-9]+/environ', path):
                if seen:
                    with open(seen, 'a') as f:
                        f.write(path + '\\n')
                if deny:
                    raise PermissionError('synthetic environ refusal')
    sys.addaudithook(audit)
spec = importlib.util.spec_from_loader('template', importlib.machinery.SourceFileLoader('template', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
if os.environ.get('SHORT_GRACE'):
    t.GRACE = float(os.environ['SHORT_GRACE'])
    if hasattr(t, 'KILL_GRACE'):
        t.KILL_GRACE = float(os.environ['SHORT_GRACE'])
if os.environ.get('DENY_SIGNALS'):
    def denied(*_):
        raise PermissionError('synthetic signal refusal')
    if hasattr(signal, 'pidfd_send_signal'):
        signal.pidfd_send_signal = denied
    os.killpg = denied
    real_kill = os.kill
    os.kill = lambda pid, sig: real_kill(pid, sig) if sig == 0 else denied(pid, sig)
t.main()
'''


def pinned_path(folder, *fixtures):
    tools = os.path.join(folder, 'tools')
    os.makedirs(tools)
    for name in TOOLS:
        if shutil.which(name):
            os.symlink(shutil.which(name), os.path.join(tools, name))
    os.symlink(sys.executable, os.path.join(tools, 'python3'))
    guarded = stub_path(path=tools)
    stub_dir = guarded.split(os.pathsep, 1)[0]
    path = os.pathsep.join((*fixtures, guarded))
    no_real_harness(path, stub_dir, fixtures)
    return path, stub_dir


def no_real_harness(path, stub_dir, fixtures=(os.path.join(HERE, 'fixtures'),)):
    if stub_dir not in path.split(os.pathsep):
        raise AssertionError('the shared stub directory is missing from PATH')
    allowed = {os.path.realpath(stub_dir)} | {os.path.realpath(f) for f in fixtures}
    for name in os.listdir(stub_dir):
        found = shutil.which(name, path=path)
        if found and os.path.dirname(os.path.realpath(found)) not in allowed:
            raise AssertionError('%s on the PATH is %s, outside the fixtures and stubs: a test could launch a real harness'
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
NO_LSOF = ('driver: lsof could not run or failed, so the driver could not check which processes hold this '
           "run's output files open; it ended only the turns' process groups and the processes their "
           'supervisors recorded')


class Template(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        path, self.stub_dir = pinned_path(self.folder, os.path.join(HERE, 'fixtures'))
        self.addCleanup(shutil.rmtree, self.stub_dir)
        no_real_harness(path, self.stub_dir)
        self.env = dict(os.environ, KIT_TEST=self.mark, FAKE_TURNS=self.turns, FAKE_HOLD=self.hold,
                        OPENWIZ_TEMPLATE_STATE=os.path.join(self.folder, 'state'), OPENWIZ_TEMPLATE_LIVE='1',
                        PATH=path)

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

    def script(self, name, source, folder=None):
        folder = folder or self.folder
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, 'w') as f:
            f.write('#!%s\n' % sys.executable + source)
        os.chmod(path, 0o700)
        return path

    def wrapper(self, name, source):
        return self.script(name, source % DRIVER)

    def call(self, cmd, request, driver=DRIVER, **env):
        env = dict(self.env, **env)
        no_real_harness(env['PATH'], self.stub_dir)
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
        self.assertEqual(shutil.which('claude', path=self.env['PATH']), os.path.join(self.stub_dir, 'claude'))
        self.assertEqual(shutil.which('fake-harness', path=self.env['PATH']),
                         os.path.join(HERE, 'fixtures', 'fake-harness'))
        with self.assertRaisesRegex(AssertionError, 'could launch a real harness'):
            self.call('start', dict(START, harness='claude'), PATH=outside + os.pathsep + self.env['PATH'])

    def test_without_the_live_opt_in_start_and_wake_start_no_harness(self):
        for live in ('', '0', 'yes'):
            with self.subTest(live=live):
                code, out = self.call('start', START, OPENWIZ_TEMPLATE_LIVE=live)
                self.assertEqual((code, out.get('error')),
                                 (1, 'the template starts no harness unless OPENWIZ_TEMPLATE_LIVE=1 is set'), out)
        code, run = self.call('start', START)
        self.assertEqual(code, 0, run)
        self.logged(1)
        code, out = self.call('wake', run, OPENWIZ_TEMPLATE_LIVE='')
        self.assertEqual((code, out.get('error')),
                         (1, 'the template starts no harness unless OPENWIZ_TEMPLATE_LIVE=1 is set'), out)
        self.assertEqual(len(self.logged()), 1, 'a turn started without the live opt-in')
        self.assertEqual(self.call('stop', run), (0, dict(run, stopped=True)))

    def test_a_checkout_executable_outside_the_fixtures_is_refused_as_a_harness(self):
        local = os.path.join(self.folder, 'local')
        os.mkdir(local)
        os.symlink(os.path.realpath(DRIVER), os.path.join(local, 'codex'))
        self.assertTrue(os.path.realpath(shutil.which('codex', path=local)).startswith(REPO + os.sep))
        with self.assertRaisesRegex(AssertionError, 'codex on the PATH is .*outside the fixtures'):
            no_real_harness(local + os.pathsep + self.stub_dir, self.stub_dir)

    def test_the_readmes_start_example_answers_as_documented(self):
        with open(os.path.join(HERE, 'README.md')) as f:
            found = re.search(r"^echo '(\{.*\})' \\\n *\| adapters/template/driver start +# (.*)$", f.read(), re.M)
        self.assertIsNotNone(found, 'the README has no start example')
        self.assertEqual(self.call('start', json.loads(found.group(1)), OPENWIZ_TEMPLATE_LIVE='')[1],
                         json.loads(found.group(2)))

    def args(self, count=0):
        deadline = time.monotonic() + 10
        while True:
            try:
                with open(self.env['FAKE_ARGS']) as f:
                    found = [json.loads(line) for line in f]
            except FileNotFoundError:
                found = []
            if len(found) >= count or time.monotonic() > deadline:
                return found
            time.sleep(0.05)

    def effort_in(self, args):
        return [args[i + 1] for i, a in enumerate(args[:-1]) if a == '--effort']

    def nothing_started(self):
        time.sleep(0.5)
        state = self.env['OPENWIZ_TEMPLATE_STATE']
        return (self.logged(), self.marked(), os.listdir(state) if os.path.isdir(state) else []) == ([], [], [])

    def test_version_lists_effort_and_the_readme_says_how_under_its_login_line(self):
        code, version = self.call('version', {})
        self.assertEqual(code, 0, version)
        self.assertIn('effort', version['can'])
        lines = read(os.path.join(HERE, 'README.md')).splitlines()
        login = next(i for i, line in enumerate(lines) if line.startswith('Login:'))
        self.assertEqual(lines[login + 1], "Effort: passed as each harness's own flag, for the harnesses and levels "
                                           'in the table below; any other harness or level is refused')
        rows = {}
        for line in lines[login + 2:]:
            if line.startswith('|'):
                cells = [c.strip() for c in line.strip().strip('|').split('|')]
                rows[cells[0]] = cells[1]
            elif rows:
                break
        self.assertEqual(rows['`fake-harness`'], '`--effort <level>`, for low, medium, high, xhigh and max')
        self.assertTrue(rows['`pi`'].startswith("can't ("), rows)
        self.assertTrue(rows['any other harness'].startswith("can't ("), rows)

    def test_start_passes_its_effort_to_the_harness_and_wake_passes_it_again(self):
        for effort in ('low', 'medium', 'high', 'xhigh', 'max'):
            with self.subTest(effort=effort):
                self.env['FAKE_ARGS'] = os.path.join(self.folder, 'args-' + effort)
                self.turns = self.env['FAKE_TURNS'] = os.path.join(self.folder, 'turns-' + effort)
                code, out = self.call('start', dict(START, effort=effort))
                self.assertEqual(code, 0, out)
                [first] = self.args(1)
                self.assertEqual(self.effort_in(first), [effort], first)
                [(turn, _, _)] = self.logged(1)
                self.assertTrue(self.until(lambda: not alive(turn)), 'the fake turn did not end')
                self.assertEqual(self.call('wake', out), (0, dict(out, woke=True)))
                self.assertEqual(len(self.args(2)), 2, 'the wake started no turn')
                self.assertEqual(self.effort_in(self.args()[1]), [effort], 'the wake dropped the effort')
                self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))

    def test_start_without_effort_passes_none(self):
        self.env['FAKE_ARGS'] = os.path.join(self.folder, 'args')
        code, out = self.call('start', START)
        self.assertEqual(code, 0, out)
        [args] = self.args(1)
        self.assertNotIn('--effort', args)
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))

    def test_an_effort_it_does_not_pass_is_refused_and_nothing_starts(self):
        for effort in ('turbo', 'minimal', 'none', 'medium-high'):
            with self.subTest(effort=effort):
                code, out = self.call('start', dict(START, effort=effort))
                self.assertEqual(code, 1, out)
                self.assertEqual(out['next'], REFUSAL)
                self.assertIn('fake-harness', out['error'])
                self.assertIn(effort, out['error'])
                self.assertTrue(self.nothing_started(), 'a refused effort started something')

    def test_a_harness_it_does_not_pass_effort_to_is_refused_and_nothing_starts(self):
        for harness in ('pi', 'fake-other'):
            with self.subTest(harness=harness):
                code, out = self.call('start', dict(START, harness=harness, effort='medium'))
                self.assertEqual(code, 1, out)
                self.assertEqual(out['next'], REFUSAL)
                self.assertIn(harness, out['error'])
                self.assertIn('medium', out['error'])
                self.assertTrue(self.nothing_started(), 'a refused harness started something')

    def test_a_harness_without_effort_still_starts_at_its_default(self):
        self.env['FAKE_ARGS'] = os.path.join(self.folder, 'args')
        code, out = self.call('start', dict(START, harness='pi'))
        self.assertEqual(code, 0, out)
        [args] = self.args(1)
        self.assertNotIn('--effort', args)
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))

    def test_an_effort_that_is_not_a_word_is_refused_as_input(self):
        for effort in ('Medium', '', 'x' * 21, 7, None):
            with self.subTest(effort=effort):
                code, out = self.call('start', dict(START, effort=effort))
                self.assertEqual(code, 1, out)
                self.assertEqual(out, {'error': 'effort is not valid', 'next': 'fix effort as `driver schema` shows'})
                self.assertTrue(self.nothing_started(), 'an invalid effort started something')

    def test_the_cant_form_leaves_effort_out_of_can_and_refuses_it_as_input(self):
        driver = self.wrapper('cant-form', CANT_FORM)
        code, version = self.call('version', {}, driver=driver)
        self.assertEqual((code, version['can']), (0, ['start', 'wake', 'stop']))
        code, out = self.call('start', dict(START, effort='medium'), driver=driver)
        self.assertEqual(code, 1, out)
        self.assertNotEqual(out['next'], REFUSAL, "the can't form answered as if it could set some effort")
        self.assertIn('the input needs exactly', out['error'])
        self.assertTrue(self.nothing_started(), "the can't form started a run with an effort")
        self.env['FAKE_ARGS'] = os.path.join(self.folder, 'args')
        code, out = self.call('start', START, driver=driver)
        self.assertEqual(code, 0, out)
        [args] = self.args(1)
        self.assertNotIn('--effort', args)
        self.assertEqual(self.call('stop', out, driver=driver), (0, dict(out, stopped=True)))
        readme = read(os.path.join(HERE, 'README.md'))
        self.assertIn('drop `effort` from `can`', readme)
        self.assertIn("Effort: the host can't set it (<why>)", readme)

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

    def test_without_proc_as_on_macos_stop_warns_when_lsof_failed_in_a_supervisor_that_has_exited(self):
        folder, pids = self.harness_handing_off_as_it_exits('fake-harness')
        broken = os.path.join(self.folder, 'broken-lsof')
        os.mkdir(broken)
        with open(os.path.join(broken, 'lsof'), 'w') as f:
            f.write('#!/bin/sh\necho "lsof: synthetic failure %s" >&2\nexit 1\n' % self.mark)
        os.chmod(os.path.join(broken, 'lsof'), 0o700)
        macos = dict(self.env, PATH=os.pathsep.join((broken, folder, NO_PROC, self.env['PATH'])),
                     NO_PROC_PYTHON=sys.executable)
        code, out = self.call('start', START, **macos)
        self.assertEqual(code, 0, out)
        self.handed_off(pids)
        state = self.env['OPENWIZ_TEMPLATE_STATE']
        with open(os.path.join(state, out['run'] + '.json')) as f:
            supervisor = json.load(f)['turns'][0]['supervisor']
        self.until(lambda: not alive(supervisor))
        output = os.path.join(state, '%s.%d.out' % (out['run'], supervisor))
        self.assertTrue(os.path.exists(output), 'the output file was removed before stop')
        p = subprocess.run([DRIVER, 'stop'], input=json.dumps(out), env=macos, capture_output=True, text=True, timeout=60)
        self.assertEqual((p.returncode, json.loads(p.stdout)), (0, dict(out, stopped=True)))
        self.assertEqual([l for l in p.stderr.splitlines() if 'could not check' in l], [NO_LSOF], p.stderr)
        self.assertNotIn(self.mark, p.stderr)
        self.assertEqual([f for f in os.listdir(state) if f.startswith('%s.%d.' % (out['run'], supervisor))], [])

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


    def test_a_run_saved_by_the_older_template_stops_and_does_not_wake(self):
        old_driver = self.script('pre-1590-driver', PRE_1590_TEMPLATE)
        code, started = self.call('start', START, driver=old_driver, FAKE_SAME_GROUP='1')
        self.assertEqual(code, 0, started)
        run = started['run']
        [(turn, child, _)] = self.logged(1)
        record_path = os.path.join(self.env['OPENWIZ_TEMPLATE_STATE'], run + '.json')
        self.assertEqual(json.loads(read(record_path))['turns'], [turn])
        self.assertTrue(self.until(lambda: not alive(turn)), 'the legacy harness did not exit')
        self.assertTrue(alive(child))
        code, out = self.call('wake', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertIn('older template', out['error'])
        self.assertNotIn('TypeError', json.dumps(out))
        self.assertEqual(len(self.logged()), 1, 'wake started a second turn for a legacy run')
        self.assertTrue(alive(child))
        outsider = subprocess.Popen(['sleep', '120'], start_new_session=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda p=outsider: (p.kill(), p.wait()))
        audited = os.path.join(self.folder, 'environ-opens')
        driver = self.wrapper('legacy-audit', LEGACY_STOP_WRAPPER)
        code, out = self.call('stop', {'run': run}, driver=driver, AUDIT_ENVIRON=audited)
        self.assertEqual((code, out), (0, {'run': run, 'stopped': True}))
        self.assertFalse(alive(child), 'a worker in the legacy turn group still runs after stop')
        self.assertEqual(self.marked(), [], 'a legacy run process still runs after stop')
        self.assertTrue(alive(outsider.pid), 'stop affected an unrelated process')
        opened = read(audited).splitlines() if os.path.exists(audited) else []
        self.assertNotIn('/proc/%d/environ' % outsider.pid, opened, 'stop read an unrelated process environment')
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))

    def test_stop_gives_a_legacy_run_shutdown_grace_before_sigkill(self):
        old_driver = self.script('pre-1590-driver', PRE_1590_TEMPLATE)
        fixtures = os.path.join(self.folder, 'checkpoint-fixtures')
        self.script('fake-harness', CHECKPOINT_HARNESS, folder=fixtures)
        path = fixtures + os.pathsep + self.env['PATH']
        ready = os.path.join(self.folder, 'ready-grace')
        checkpoint = os.path.join(self.folder, 'checkpoint')
        code, started = self.call('start', START, driver=old_driver, PATH=path, READY=ready, CHECKPOINT=checkpoint)
        self.assertEqual(code, 0, started)
        self.assertTrue(self.until(lambda: os.path.exists(ready) and bool(read(ready).strip())))
        pid = int(read(ready).strip())
        code, out = self.call('stop', started, PATH=path)
        self.assertEqual((code, out), (0, dict(started, stopped=True)))
        self.assertFalse(alive(pid), 'the legacy harness still runs after stop')
        self.assertTrue(os.path.exists(checkpoint) and read(checkpoint) == 'saved',
                        'stop killed the legacy harness before it saved its checkpoint')
        ready_ign = os.path.join(self.folder, 'ready-ignore')
        code, started_ign = self.call('start', START, driver=old_driver, PATH=path, READY=ready_ign, IGNORE_TERM='1')
        self.assertEqual(code, 0, started_ign)
        self.assertTrue(self.until(lambda: os.path.exists(ready_ign) and bool(read(ready_ign).strip())))
        pid_ign = int(read(ready_ign).strip())
        driver = self.wrapper('legacy-short-grace', LEGACY_STOP_WRAPPER)
        t0 = time.monotonic()
        code, out = self.call('stop', started_ign, driver=driver, PATH=path, SHORT_GRACE='0.4')
        elapsed = time.monotonic() - t0
        self.assertEqual((code, out), (0, dict(started_ign, stopped=True)))
        self.assertGreaterEqual(elapsed, 0.35, 'stop did not wait the shutdown grace before SIGKILL')
        self.assertFalse(alive(pid_ign), 'a SIGTERM-ignoring legacy harness still runs after stop')

    def test_stop_refuses_a_legacy_run_before_marking_stopped_when_shutdown_is_unconfirmed(self):
        old_driver = self.script('pre-1590-driver', PRE_1590_TEMPLATE)
        open(self.hold, 'w').close()
        code, started = self.call('start', START, driver=old_driver, FAKE_SAME_GROUP='1')
        self.assertEqual(code, 0, started)
        [(turn, child, _)] = self.logged(1)
        record_path = os.path.join(self.env['OPENWIZ_TEMPLATE_STATE'], started['run'] + '.json')
        driver = self.wrapper('legacy-deny-signals', LEGACY_STOP_WRAPPER)
        code, out = self.call('stop', started, driver=driver, DENY_SIGNALS='1', SHORT_GRACE='0.2')
        self.assertEqual(code, 1, out)
        self.assertIn('still has processes', out['error'])
        self.assertTrue(out.get('next'), out)
        self.assertFalse(json.loads(read(record_path))['stopped'], 'stop marked the run stopped despite survivors')
        self.assertTrue(alive(turn))
        code, out = self.call('stop', started, driver=driver, DENY_ENVIRON='1')
        self.assertEqual(code, 1, out)
        self.assertIn('cannot inspect', out['error'])
        self.assertTrue(out.get('next'), out)
        self.assertFalse(json.loads(read(record_path))['stopped'], 'stop marked the run stopped with unreadable environ')
        self.assertTrue(alive(turn))
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.call('stop', started, **macos)
        self.assertEqual(code, 1, out)
        self.assertTrue(out.get('error') and out.get('next'), out)
        self.assertFalse(json.loads(read(record_path))['stopped'], 'stop marked the run stopped without /proc')
        self.assertTrue(alive(turn))
        self.assertEqual(self.call('stop', started), (0, dict(started, stopped=True)))
        self.assertEqual((alive(turn), alive(child)), (False, False))
        self.assertEqual(self.call('stop', started, **macos), (0, dict(started, stopped=True)))

    def test_stop_does_not_signal_an_unrelated_process_that_reused_a_legacy_pid(self):
        run = 'run-' + secrets.token_hex(6)
        folder = self.env['OPENWIZ_TEMPLATE_STATE']
        os.makedirs(folder, exist_ok=True)
        unmarked = subprocess.Popen(['sleep', '120'], start_new_session=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda p=unmarked: (p.kill(), p.wait()))
        with open(os.path.join(folder, run + '.json'), 'w') as f:
            json.dump({'request': START, 'turns': [unmarked.pid], 'stopped': False}, f)
        self.assertEqual(self.call('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertTrue(alive(unmarked.pid), 'stop signaled a process without OPENWIZ_RUN')

    def test_a_provider_qualified_model_reaches_the_harness(self):
        self.env['FAKE_ARGS'] = os.path.join(self.folder, 'args')
        code, out = self.call('start', dict(START, model='kimi-code/kimi-for-coding'))
        self.assertEqual(code, 0, out)
        [args] = self.args(1)
        self.assertEqual(args[args.index('--model') + 1], 'kimi-code/kimi-for-coding')
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))


if __name__ == '__main__':
    unittest.main(verbosity=2)
