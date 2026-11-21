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
import threading
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
sys.path.insert(0, KIT)
import kit
NO_PROC = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'fixtures', 'no-proc')

TOKEN = 'gh' + 'p_' + 'Synthetic0Local0Value' * 2 + '00'
OPAQUE = 'opaque-fixture-value-7Kq2Zr9w'
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 1',
        'pass wake: the run edited builder status note 1',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
BREAKS_AFTER_SPAWN = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('local', importlib.machinery.SourceFileLoader('local', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
launch = t.launch
def broken(*args):
    turn = launch(*args)
    if os.environ['BREAK'] == 'write':
        os.mkdir(os.path.join(t.STATE, args[1] + '.json.new'))
    else:
        os.chmod(t.STATE, 0o500)
    return turn
t.launch = broken
t.main()
'''


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

class Local(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.bin = os.path.join(self.folder, 'bin')
        os.mkdir(self.bin)
        for name, fake in (('claude', 'fake-harness'), ('codex', 'fake-harness'), ('gh', 'gh')):
            os.symlink(os.path.join(HERE, 'fixtures', fake), os.path.join(self.bin, name))
        repos = os.path.join(self.folder, 'repos')
        for repo, row in (('site', '| Harness permission mode | `acceptEdits` |'), ('blog', '| Harness | x |'),
                          ('refuser', '| Harness permission mode | `refuse` |'),
                          ('expired', '| Harness permission mode | `expired` |'),
                          ('broken', '| Harness permission mode | `fail` |'), ('quick', '| Harness permission mode | `quick` |'),
                          ('raiser', '| Harness permission mode | `bypassPermissions` |'),
                          ('unapproved', '| Harness permission mode | `acceptEdits` |')):
            os.makedirs(os.path.join(repos, 'example', repo, 'docs', 'agents'))
            with open(os.path.join(repos, 'example', repo, 'docs', 'agents', 'fleet.md'), 'w') as f:
                f.write('# Fleet\n\n| Setting | Value |\n| --- | --- |\n%s\n' % row)
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['Example-Bot[bot]'], 'comments': []}, f)
        self.mark = secrets.token_hex(8)
        self.log = os.path.join(self.folder, 'turns')
        self.env = dict(os.environ, KIT_TRACKER=self.tracker, LOCAL_TEST=self.mark, GH_TOKEN=TOKEN, FAKE_TURNS=self.log,
                        FAKE_REPOS=repos, OPENWIZ_LOCAL_SETTLE='2',
                        OPENWIZ_LOCAL_STATE=os.path.join(self.folder, 'state'),
                        PATH=self.bin + os.pathsep + os.environ.get('PATH', ''))
        self.approve(self.env['OPENWIZ_LOCAL_STATE'])

    def approve(self, state):
        os.makedirs(state, mode=0o700, exist_ok=True)
        modes = {'site': 'acceptEdits', 'blog': 'acceptEdits', 'refuser': 'refuse', 'expired': 'expired',
                 'broken': 'fail', 'quick': 'quick', 'raiser': 'acceptEdits', 'missing': 'acceptEdits'}
        path = os.path.join(state, 'approvals.json')
        with open(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
            json.dump({'example/' + repo: {'claude': mode, 'codex': mode} for repo, mode in modes.items()}, f)
        return path

    def tearDown(self):
        for root, dirs, _ in os.walk(self.folder):
            for d in dirs:
                os.chmod(os.path.join(root, d), 0o700)
        for pid in self.marked('LOCAL_TEST=' + self.mark) + [child for _, child, *_ in self.logged()]:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def marked(self, entry):
        found = []
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if entry.encode() in f.read().split(b'\0'):
                        found.append(int(pid))
            except OSError:
                pass
        return found

    def logged(self):
        try:
            with open(self.log) as f:
                return [(int(a), int(b), c, d, e) for a, b, c, d, e in (line.split() for line in f)]
        except FileNotFoundError:
            return []

    def wrapper(self):
        path = os.path.join(self.folder, 'breaks-after-spawn')
        with open(path, 'w') as f:
            f.write('#!%s\n' % sys.executable + BREAKS_AFTER_SPAWN % DRIVER)
        os.chmod(path, 0o700)
        return path

    def driver(self, cmd, request=None, env=None, program=DRIVER):
        p = subprocess.run([program, cmd], input='' if request is None else json.dumps(request),
                           env=env or self.env, capture_output=True, text=True, timeout=60)
        return p.returncode, json.loads(p.stdout)

    def start(self, harness='claude', env=None, program=DRIVER, repository='example/site'):
        return self.driver('start', {'repository': repository, 'ticket': 7, 'skill': 'build-ticket',
                                     'harness': harness, 'model': 'synthetic-1'}, env, program)

    def first_turn(self, **env):
        code, out = self.start(env=dict(self.env, **env))
        self.assertEqual(code, 0, out)
        self.until(lambda: len(self.logged()) == 1)
        return out, self.logged()[0][0], self.logged()[0][1]

    def no_new_turn(self, count):
        time.sleep(0.5)
        self.assertEqual(len(self.logged()), count, 'a turn was started')

    def test_stop_ends_a_worker_with_a_clean_environment(self):
        out, turn, child = self.first_turn(FAKE_CLEAN='1')
        self.until(lambda: not alive(turn))
        self.assertTrue(alive(child))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(child), 'a worker without the mark still runs after stop')

    def test_stop_ends_the_run_when_it_cannot_save(self):
        open(os.path.join(self.folder, 'hold'), 'w').close()
        out, turn, child = self.first_turn(FAKE_HOLD=os.path.join(self.folder, 'hold'))
        os.mkdir(os.path.join(self.folder, 'state', out['run'] + '.json.new'))
        code, err = self.driver('stop', out)
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.assertEqual((alive(turn), alive(child), self.marked('OPENWIZ_RUN=' + out['run'])), (False, False, []))
        self.assertEqual(self.driver('wake', out)[0], 1)
        self.no_new_turn(1)

    def test_wake_checks_its_save_before_and_after_spawn(self):
        out, turn, _ = self.first_turn()
        self.until(lambda: not alive(turn))
        blocked = os.path.join(self.folder, 'state', out['run'] + '.json.new')
        os.mkdir(blocked)
        code, err = self.driver('wake', out)
        self.assertEqual(code, 1, err)
        self.no_new_turn(1)
        self.assertIn('nothing was started', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        os.rmdir(blocked)
        before = set(self.marked('OPENWIZ_RUN=' + out['run']))
        code, err = self.driver('wake', out, dict(self.env, BREAK='write'), self.wrapper())
        self.assertEqual(code, 1, err)
        self.assertIn('unknown', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        self.assertLessEqual(set(self.marked('OPENWIZ_RUN=' + out['run'])), before, 'the unsaved turn still runs')

    def test_start_with_nowhere_to_save_starts_nothing(self):
        blocker = os.path.join(self.folder, 'a-file')
        open(blocker, 'w').close()
        code, err = self.start(env=dict(self.env, OPENWIZ_LOCAL_STATE=os.path.join(blocker, 'state')))
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.no_new_turn(0)

    def test_start_record_is_not_wakeable_before_it_is_confirmed(self):
        for mode in ('write', 'readonly'):
            with self.subTest(mode=mode):
                if mode == 'readonly' and os.geteuid() == 0:
                    self.skipTest('root ignores a read-only folder')
                state = os.path.join(self.folder, 'state-' + mode)
                self.approve(state)
                env = dict(self.env, BREAK=mode, OPENWIZ_LOCAL_STATE=state)
                code, err = self.start(env=env, program=self.wrapper())
                self.assertEqual(code, 1, err)
                self.assertIn('unknown', err['error'])
                self.assertNotIn('retry', json.dumps(err))
                self.until(lambda: not any(alive(t) or alive(c) for t, c, *_ in self.logged()))
                os.chmod(state, 0o700)
                if mode == 'write':
                    os.rmdir(os.path.join(state, re.search(r'run-[0-9a-f]{12}', err['error']).group() + '.json.new'))
                count = len(self.logged())
                code, _ = self.driver('wake', {'run': re.search(r'run-[0-9a-f]{12}', err['error']).group()},
                                      dict(self.env, OPENWIZ_LOCAL_STATE=state))
                self.assertEqual(code, 1)
                self.no_new_turn(count)

    def test_kit_passes_all_five_with_each_harness(self):
        for harness in ('claude', 'codex'):
            with self.subTest(harness):
                self.tearDown()
                self.setUp()
                p = subprocess.run([sys.executable, '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER,
                                    '--repo', 'example/site', '--ticket', '7', '--harness', harness,
                                    '--model', 'synthetic-1', '--tracker', self.tracker, '--wait', '15'],
                                   env=self.env, capture_output=True, text=True, timeout=180)
                self.assertEqual((p.returncode, p.stdout.splitlines()), (0, PASS), p.stderr)

    def test_several_runs_at_once_stop_only_their_own(self):
        answers = []
        threads = [threading.Thread(target=lambda: answers.append(self.start())) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual([code for code, _ in answers], [0, 0, 0], answers)
        runs = [a['run'] for _, a in answers]
        self.assertEqual(len(set(runs)), 3)
        end = time.monotonic() + 15
        while not all(self.marked('OPENWIZ_RUN=' + r) for r in runs) and time.monotonic() < end:
            time.sleep(0.1)
        self.assertTrue(all(self.marked('OPENWIZ_RUN=' + r) for r in runs))
        self.assertEqual(self.driver('stop', {'run': runs[0]}), (0, {'run': runs[0], 'stopped': True}))
        self.assertEqual(self.marked('OPENWIZ_RUN=' + runs[0]), [])
        self.assertTrue(all(self.marked('OPENWIZ_RUN=' + r) for r in runs[1:]))
        self.assertEqual(self.driver('wake', {'run': runs[1]}), (0, {'run': runs[1], 'woke': True}))
        self.assertEqual(self.driver('wake', {'run': runs[0]})[0], 1)

    def until(self, ready):
        end = time.monotonic() + 15
        while not ready() and time.monotonic() < end:
            time.sleep(0.05)
        self.assertTrue(ready())

    def test_wake_while_a_turn_runs_starts_no_second_turn(self):
        hold = os.path.join(self.folder, 'hold')
        open(hold, 'w').close()
        out, turn, _ = self.first_turn(FAKE_HOLD=hold)
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.no_new_turn(1)
        os.remove(hold)
        self.until(lambda: not alive(turn))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.until(lambda: [t[2] for t in self.logged()] == ['first', 'woken'])

    def test_each_run_works_in_its_own_clone_of_its_repository(self):
        first, _, _ = self.first_turn()
        second = self.start()[1]
        self.until(lambda: len(self.logged()) == 2)
        folders = [t[3] for t in self.logged()]
        self.assertNotEqual(folders[0], folders[1])
        for folder in folders:
            self.assertNotEqual(os.path.realpath(folder), os.path.realpath(os.getcwd()))
            with open(os.path.join(folder, 'docs', 'agents', 'fleet.md')) as f:
                self.assertIn('`acceptEdits`', f.read())
        self.until(lambda: not any(alive(t[0]) for t in self.logged()))
        self.assertEqual(self.driver('wake', first)[0], 0)
        self.until(lambda: len(self.logged()) == 3)
        self.assertEqual(self.logged()[2][3], folders[0])
        self.assertTrue(second['run'])

    def test_permission_mode_is_the_repositorys_own_or_start_refuses(self):
        for harness in ('claude', 'codex'):
            with self.subTest(harness):
                self.assertEqual(self.start(harness)[0], 0)
                self.until(lambda: len(self.logged()) and self.logged()[-1][4] == 'acceptEdits')
        count = len(self.logged())
        code, err = self.start(repository='example/blog')
        self.assertEqual(code, 1, err)
        self.assertIsNone(kit.invalid(err, kit.load_schema()['error']), err)
        self.assertIn('Harness permission mode', err['next'])
        self.no_new_turn(count)

    def test_permission_mode_needs_this_machines_approval(self):
        approvals = os.path.join(self.env['OPENWIZ_LOCAL_STATE'], 'approvals.json')
        for repo, says in (('raiser', 'does not match'), ('unapproved', 'no permission mode is approved')):
            with self.subTest(repo):
                code, err = self.start(repository='example/' + repo)
                self.assertEqual(code, 1, err)
                self.assertIsNone(kit.invalid(err, kit.load_schema()['error']), err)
                self.assertIn(says, err['error'])
                self.assertIn(approvals, err['next'])
        os.chmod(approvals, 0o666)
        code, err = self.start()
        self.assertEqual(code, 1, err)
        self.assertIn('others can change', err['error'])
        self.no_new_turn(0)
        os.chmod(approvals, 0o600)
        self.assertEqual(self.start()[0], 0)
        self.until(lambda: [t[4] for t in self.logged()] == ['acceptEdits'])

    def test_a_first_turn_that_ends_at_once_fails_start_with_its_reason(self):
        for repo, says in (('refuser', 'refused'), ('expired', 'not signed in'), ('broken', 'exit 3'),
                           ('missing', 'could not clone')):
            with self.subTest(repo):
                code, err = self.start(repository='example/' + repo)
                self.assertEqual(code, 1, err)
                self.assertIsNone(kit.invalid(err, kit.load_schema()['error']), err)
                self.assertIn(says, err['error'])
                self.assertNotIn(OPAQUE, json.dumps(err))
                run = re.search(r'run-[0-9a-f]{12}', err['error']).group()
                log = os.path.join(self.env['OPENWIZ_LOCAL_STATE'], run + '.log')
                self.assertIn(log, err['next'])
                with open(log) as f:
                    self.assertIn(OPAQUE, f.read())
                self.assertEqual(os.stat(log).st_mode & 0o777, 0o600)
                self.assertEqual(self.marked('OPENWIZ_RUN=' + run), [])
                self.assertEqual(self.driver('wake', {'run': run})[0], 1)
        code, out = self.start(repository='example/quick')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))

    def test_a_credential_shaped_start_field_is_refused_before_anything_starts(self):
        calls, logging = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'logging-bin')
        os.mkdir(logging)
        for name in ('claude', 'codex', 'gh'):
            with open(os.path.join(logging, name), 'w') as f:
                f.write('#!/bin/sh\nprintf \'%%s\\n\' "$*" >> %s\nexec %s "$@"\n' % (calls, os.path.join(self.bin, name)))
            os.chmod(os.path.join(logging, name), 0o700)
        env = dict(self.env, PATH=logging + os.pathsep + self.env['PATH'])
        request = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
                   'model': 'synthetic-1'}
        for field, value in (('model', 'sk-' + 'Synthetic0Marker' * 2), ('model', 'token: synthetic0marker'),
                             ('model', 'AKIA' + 'SYNTHETIC0MARK00'), ('repository', TOKEN + '/site'),
                             ('skill', 'sk-synthetic0marker0value00'), ('harness', 'sk-synthetic0marker0value00')):
            with self.subTest(field=field, value=value):
                code, out = self.driver('start', dict(request, **{field: value}), env)
                self.assertEqual(code, 1, out)
                self.assertIn(field, out['error'])
                self.assertIn('credential', out['error'])
                self.assertNotIn(value, json.dumps(out))
                self.assertFalse(os.path.exists(calls), 'a harness or gh ran')
                state = self.env['OPENWIZ_LOCAL_STATE']
                self.assertEqual(sorted(os.listdir(state)), ['approvals.json'])
        self.assertEqual(self.logged(), [])

    def test_missing_or_unknown_harness_is_an_error_with_next(self):
        python = os.path.join(self.folder, 'python')
        os.mkdir(python)
        os.symlink(sys.executable, os.path.join(python, 'python3'))
        bare = dict(self.env, PATH=python)
        schema = kit.load_schema()['error']
        for harness, env, says in (('claude', bare, 'install claude'), ('codex', bare, 'install codex'),
                                   ('fake-harness', self.env, 'claude, codex')):
            with self.subTest(harness):
                code, out = self.start(harness, env)
                self.assertEqual(code, 1)
                self.assertIsNone(kit.invalid(out, schema), out)
                self.assertIn(says, out['next'])
        self.assertEqual([f for f in os.listdir(self.env['OPENWIZ_LOCAL_STATE']) if f.startswith('run-')], [])


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
        folder, pids = self.harness_handing_off_as_it_exits('claude')
        macos = {'PATH': folder + os.pathsep + NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.start(env=dict(self.env, **macos))
        self.assertEqual(code, 0, out)
        worker = self.handed_off(pids)
        self.assertEqual(self.driver('stop', out, dict(self.env, **macos)), (0, dict(out, stopped=True)))
        self.assertFalse(alive(worker), 'a worker the turn handed off as it exited still runs after stop')

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

    def test_without_proc_as_on_macos_the_kit_passes_and_stop_ends_each_grandchild(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        for worker in ({}, {'FAKE_CLEAN': '1', 'FAKE_SAME_GROUP': '1'}):
            with self.subTest(**worker):
                self.tearDown()
                self.setUp()
                calls = os.path.join(self.folder, 'ps-calls')
                macos['PATH'] = self.logging_ps(calls) + os.pathsep + NO_PROC + os.pathsep + self.env['PATH']
                out, turn, child = self.first_turn(**macos, **worker)
                self.until(lambda: not alive(turn))
                self.assertTrue(alive(child))
                self.assertEqual(self.driver('stop', out, dict(self.env, **macos)), (0, dict(out, stopped=True)))
                self.assertFalse(alive(child), 'a grandchild of the harness still runs after stop')
                self.assertEqual(self.asked_ps_for_environments(calls), [], 'the driver asked ps for process environments')

        self.tearDown()
        self.setUp()
        macos['PATH'] = NO_PROC + os.pathsep + self.env['PATH']
        p = subprocess.run([os.path.join(NO_PROC, 'python3'), '-I', os.path.join(KIT, 'kit.py'), '--driver', DRIVER,
                            '--repo', 'example/site', '--ticket', '7', '--harness', 'claude',
                            '--model', 'synthetic-1', '--tracker', self.tracker, '--wait', '15'],
                           env=dict(self.env, **macos), capture_output=True, text=True, timeout=180)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, PASS), p.stderr)

if __name__ == '__main__':
    unittest.main(verbosity=2)
