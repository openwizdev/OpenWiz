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
NO_LSOF = ('driver: lsof could not run or failed, so the driver could not check which processes hold this '
           "run's output file open; it ended only the turns' process groups and the processes their "
           'supervisors recorded')
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
                        FAKE_ARGS=os.path.join(self.folder, 'argv'),
                        FAKE_REPOS=repos, OPENWIZ_LOCAL_SETTLE='2',
                        OPENWIZ_LOCAL_STATE=os.path.join(self.folder, 'state'),
                        PATH=self.bin + os.pathsep + os.environ.get('PATH', ''))
        self.env.pop('CLAUDE_CODE_EFFORT_LEVEL', None)
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

    def start(self, harness='claude', env=None, program=DRIVER, repository='example/site', effort=None):
        request = {'repository': repository, 'ticket': 7, 'skill': 'build-ticket', 'harness': harness,
                   'model': 'synthetic-1'}
        return self.driver('start', request if effort is None else dict(request, effort=effort), env, program)

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

    def test_a_quick_clean_first_turn_starts(self):
        talker = os.path.join(self.folder, 'talker')
        os.mkdir(talker)
        with open(os.path.join(talker, 'claude'), 'w') as f:
            f.write('#!%s\nimport os\nprint(os.environ["TALK"])\n' % sys.executable)
        os.chmod(os.path.join(talker, 'claude'), 0o700)
        request = {'repository': 'example/quick', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
                   'model': 'synthetic-1'}
        talks = dict(self.env, PATH=talker + os.pathsep + self.env['PATH'])
        for case, env in [('relative state', dict(self.env, OPENWIZ_LOCAL_STATE='state'))] + [
                (said, dict(talks, TALK=said)) for said in (
                    'Updated the permission documentation and the login guide.',
                    'Added tests for unauthorized requests.',
                    'Summary: unauthorized requests now get a 401, and a denied upload was refused.',
                    'Checked that the session token is invalid after logout, and that the request was denied.')]:
            with self.subTest(case):
                p = subprocess.run([DRIVER, 'start'], input=json.dumps(request), env=env, cwd=self.folder,
                                   capture_output=True, text=True, timeout=60)
                self.assertEqual(p.returncode, 0, p.stdout)
                self.assertEqual(self.driver('wake', json.loads(p.stdout))[0], 0)
        for said, says in (('Error: 401 Unauthorized', 'not signed in'), ('Unauthorized', 'not signed in'),
                           ('Not logged in \u00b7 Please run /login', 'not signed in'),
                           ('API Error: OAuth token has expired.', 'not signed in'),
                           ('Error: permission to use Write was denied.', 'refused a tool')):
            with self.subTest(said):
                code, err = self.start(env=dict(talks, TALK=said), repository='example/quick')
                self.assertEqual(code, 1, err)
                self.assertIn(says + ' (exit 0)', err['error'])

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

    def test_without_proc_as_on_macos_stop_says_when_lsof_cannot_check_the_output_file(self):
        for broken in (False, True):
            with self.subTest(lsof_fails=broken):
                self.tearDown()
                self.setUp()
                macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
                out, _, _ = self.first_turn(**macos)
                stop = dict(self.env, **macos)
                if broken:
                    folder = os.path.join(self.folder, 'broken-lsof')
                    os.mkdir(folder)
                    with open(os.path.join(folder, 'lsof'), 'w') as f:
                        f.write('#!/bin/sh\necho "lsof: synthetic failure %s" >&2\nexit 1\n' % OPAQUE)
                    os.chmod(os.path.join(folder, 'lsof'), 0o700)
                    stop['PATH'] = folder + os.pathsep + stop['PATH']
                p = subprocess.run([DRIVER, 'stop'], input=json.dumps(out), env=stop, capture_output=True, text=True,
                                   timeout=60)
                self.assertEqual((p.returncode, json.loads(p.stdout)), (0, dict(out, stopped=True)))
                self.assertEqual('could not check' in p.stderr, broken, p.stderr)
                self.assertNotIn(OPAQUE, p.stderr)

    def test_without_proc_as_on_macos_stop_warns_when_lsof_failed_in_a_supervisor_that_has_exited(self):
        folder, pids = self.harness_handing_off_as_it_exits('claude')
        broken = os.path.join(self.folder, 'broken-lsof')
        os.mkdir(broken)
        with open(os.path.join(broken, 'lsof'), 'w') as f:
            f.write('#!/bin/sh\necho "lsof: synthetic failure %s" >&2\nexit 1\n' % OPAQUE)
        os.chmod(os.path.join(broken, 'lsof'), 0o700)
        macos = dict(self.env, PATH=os.pathsep.join((broken, folder, NO_PROC, self.env['PATH'])),
                     NO_PROC_PYTHON=sys.executable)
        code, out = self.start(env=macos)
        self.assertEqual(code, 0, out)
        self.handed_off(pids)
        with open(os.path.join(self.env['OPENWIZ_LOCAL_STATE'], out['run'] + '.json')) as f:
            supervisor = json.load(f)['turns'][0]['supervisor']
        self.until(lambda: not alive(supervisor))
        p = subprocess.run([DRIVER, 'stop'], input=json.dumps(out), env=macos, capture_output=True, text=True, timeout=60)
        self.assertEqual((p.returncode, json.loads(p.stdout)), (0, dict(out, stopped=True)))
        self.assertEqual([l for l in p.stderr.splitlines() if 'could not check' in l], [NO_LSOF], p.stderr)
        self.assertNotIn(OPAQUE, p.stderr)

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

    def repository_with(self, name, rows, modes):
        folder = os.path.join(self.env['FAKE_REPOS'], 'example', name, 'docs', 'agents')
        os.makedirs(folder)
        with open(os.path.join(folder, 'fleet.md'), 'w') as f:
            f.write('# Fleet\n\n| Setting | Value |\n| --- | --- |\n%s\n' % '\n'.join(rows))
        path = os.path.join(self.env['OPENWIZ_LOCAL_STATE'], 'approvals.json')
        approvals = json.loads(read(path))
        approvals['example/' + name] = modes
        with open(os.open(path, os.O_WRONLY | os.O_TRUNC), 'w') as f:
            json.dump(approvals, f)
        return 'example/' + name

    def refused(self, harness, repository):
        code, err = self.start(harness, repository=repository)
        self.assertEqual(code, 1, err)
        self.assertIsNone(kit.invalid(err, kit.load_schema()['error']), err)
        return err

    def test_per_harness_rows_start_each_harness_with_its_own_mode(self):
        repository = self.repository_with('pair', ['| Harness permission mode (claude) | `acceptEdits` |',
                                                   '| Harness permission mode (codex) | `workspace-write` |'],
                                          {'claude': 'acceptEdits', 'codex': 'workspace-write'})
        for harness, mode in (('claude', 'acceptEdits'), ('codex', 'workspace-write')):
            with self.subTest(harness):
                code, out = self.start(harness, repository=repository)
                self.assertEqual(code, 0, out)
                self.until(lambda: len(self.logged()) and self.logged()[-1][4] == mode)
        self.assertEqual([t[4] for t in self.logged()], ['acceptEdits', 'workspace-write'])

    def test_a_missing_or_mismatched_per_harness_row_refuses_naming_the_harness(self):
        half = self.repository_with('half', ['| Harness permission mode (claude) | `acceptEdits` |'],
                                    {'claude': 'acceptEdits', 'codex': 'workspace-write'})
        wider = self.repository_with('wider', ['| Harness permission mode (claude) | `acceptEdits` |',
                                               '| Harness permission mode (codex) | `danger-full-access` |'],
                                     {'claude': 'acceptEdits', 'codex': 'workspace-write'})
        twice = self.repository_with('twice', ['| Harness permission mode (codex) | `workspace-write` |',
                                               '| Harness permission mode (codex) | `workspace-write` |'],
                                     {'codex': 'workspace-write'})
        for repository, says in ((half, 'no harness permission mode for codex'),
                                 (twice, 'no harness permission mode for codex'),
                                 (wider, 'Harness permission mode (codex) row')):
            with self.subTest(repository):
                err = self.refused('codex', repository)
                self.assertIn(says, err['error'])
                self.assertIn('codex', err['next'])
        self.assertIn('`| Harness permission mode (codex) | `<mode>` |`', self.refused('codex', half)['next'])
        self.assertIn('does not match the mode approved on this machine for codex', self.refused('codex', wider)['error'])
        self.no_new_turn(0)

    def test_a_single_row_and_a_per_harness_row_for_the_same_harness_refuse(self):
        both = self.repository_with('both', ['| Harness permission mode | `acceptEdits` |',
                                             '| Harness permission mode (claude) | `acceptEdits` |'],
                                    {'claude': 'acceptEdits'})
        err = self.refused('claude', both)
        self.assertIn('both the single Harness permission mode row and a Harness permission mode (claude) row',
                      err['error'])
        self.assertIn('keep one of them', err['next'])
        self.no_new_turn(0)

    def test_a_single_row_file_refuses_with_todays_exact_words(self):
        approvals = os.path.join(self.env['OPENWIZ_LOCAL_STATE'], 'approvals.json')
        self.assertEqual(self.refused('codex', 'example/blog'), {
            'error': 'example/blog has no single harness permission mode saved in docs/agents/fleet.md; nothing was '
                     'started',
            'next': 'choose the mode codex may run in and save it there as the row `| Harness permission mode | '
                    '`<mode>` |`, then start again'})
        self.assertEqual(self.refused('claude', 'example/raiser'), {
            'error': 'the Harness permission mode row in example/raiser does not match the mode approved on this '
                     'machine; nothing was started',
            'next': 'save the one mode you approve in both its docs/agents/fleet.md and %s, then start again'
                    % approvals})
        self.no_new_turn(0)

    def test_padded_row_labels_count_as_the_same_row(self):
        padded = self.repository_with('padded', ['| Harness permission mode | `acceptEdits` |',
                                                 '| Harness permission mode (claude)  | `acceptEdits` |'],
                                      {'claude': 'acceptEdits'})
        spaced = self.repository_with('spaced', ['|  Harness  permission mode  | `acceptEdits` |',
                                                 '| Harness permission mode (claude) | `acceptEdits` |'],
                                      {'claude': 'acceptEdits'})
        twice = self.repository_with('twice-padded', ['| Harness permission mode (codex) | `workspace-write` |',
                                                      '| Harness permission mode (codex)  | `workspace-write` |'],
                                     {'codex': 'workspace-write'})
        for harness, repository, says in (('claude', padded, 'saves both'), ('claude', spaced, 'saves both'),
                                          ('codex', twice, 'no harness permission mode for codex')):
            with self.subTest(repository):
                self.assertIn(says, self.refused(harness, repository)['error'])
        self.no_new_turn(0)
        aligned = self.repository_with('aligned', ['|  Harness permission mode (claude)   | `acceptEdits`     |',
                                                   '| Harness  permission mode (codex)    | `workspace-write` |'],
                                       {'claude': 'acceptEdits', 'codex': 'workspace-write'})
        for harness, mode in (('claude', 'acceptEdits'), ('codex', 'workspace-write')):
            with self.subTest(harness):
                self.assertEqual(self.start(harness, repository=aligned)[0], 0)
                self.until(lambda: len(self.logged()) and self.logged()[-1][4] == mode)
        self.assertEqual([t[4] for t in self.logged()], ['acceptEdits', 'workspace-write'])
    def argv_seen(self):
        try:
            with open(self.env['FAKE_ARGS']) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def test_version_lists_effort(self):
        code, out = self.driver('version')
        self.assertEqual(code, 0, out)
        self.assertIn('effort', out['can'])
        self.assertIsNone(kit.invalid(out, kit.load_schema()['commands']['version']['output']), out)

    def test_each_built_in_gets_the_effort_flag_at_start_and_at_wake(self):
        expected = {'claude': lambda argv: argv[-2:] == ['--effort', 'medium'],
                    'codex': lambda argv: argv[:3] == ['exec', '-c', 'model_reasoning_effort=medium']}
        for harness, flagged in expected.items():
            with self.subTest(harness):
                self.tearDown()
                self.setUp()
                env = dict(self.env, CLAUDE_CODE_EFFORT_LEVEL='low')
                code, out = self.start(harness, env, effort='medium')
                self.assertEqual(code, 0, out)
                self.until(lambda: len(self.logged()) == 1 and not alive(self.logged()[0][0]))
                self.assertEqual(self.driver('wake', out, env), (0, dict(out, woke=True)))
                self.until(lambda: len(self.argv_seen()) == 2)
                seen = self.argv_seen()
                self.assertEqual([r['woken'] for r in seen], [False, True])
                for record in seen:
                    self.assertTrue(flagged(record['argv']), record['argv'])
                    self.assertEqual(record['effort'], 'medium')
                if harness == 'claude':
                    self.assertEqual([r['CLAUDE_CODE_EFFORT_LEVEL'] for r in seen], ['medium', 'medium'],
                                     'an exported CLAUDE_CODE_EFFORT_LEVEL outranks --effort, so it must match')

    def test_a_start_without_effort_adds_no_effort_flag_or_setting(self):
        for harness in ('claude', 'codex'):
            with self.subTest(harness):
                self.assertEqual(self.start(harness, repository='example/quick')[0], 0)
        seen = self.argv_seen()
        self.assertEqual(len(seen), 2)
        for record in seen:
            self.assertIsNone(record['effort'], record['argv'])
            self.assertIsNone(record['CLAUDE_CODE_EFFORT_LEVEL'])

    def documented(self, help_file, listed):
        with open(os.path.join(HERE, 'fixtures', 'help', help_file)) as f:
            return re.split(r',\s*(?:or\s+)?', re.search(listed, f.read()).group(1))

    def test_every_level_in_each_clis_help_reaches_it_and_ultracode_is_refused(self):
        claude = self.documented('claude.txt', r'--effort: .*?Options: (.*?)\. ')
        codex = self.documented('codex-exec.txt', r'model_reasoning_effort: .*?such as (.*?)\. ')
        self.assertEqual((claude, codex), (['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
                                           ['low', 'medium', 'high', 'xhigh', 'max', 'ultra']))
        passed = [('claude', level) for level in claude if level != 'ultracode'] + [('codex', l) for l in codex]
        for harness, level in passed:
            with self.subTest(harness=harness, level=level):
                code, out = self.start(harness, repository='example/quick', effort=level)
                self.assertEqual(code, 0, out)
                self.assertEqual((self.argv_seen()[-1]['cli'], self.argv_seen()[-1]['effort']), (harness, level))
        self.assertEqual(len(self.argv_seen()), len(passed))

    def test_an_effort_the_driver_cant_set_is_refused_before_anything_runs(self):
        calls, logging = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'logging-bin')
        os.mkdir(logging)
        for name in ('claude', 'codex', 'gh'):
            with open(os.path.join(logging, name), 'w') as f:
                f.write('#!/bin/sh\nprintf \'%%s\\n\' "$*" >> %s\nexec %s "$@"\n' % (calls, os.path.join(self.bin, name)))
            os.chmod(os.path.join(logging, name), 0o700)
        env = dict(self.env, PATH=logging + os.pathsep + self.env['PATH'])
        schema = kit.load_schema()['error']
        for harness, effort in (('claude', 'ultracode'), ('claude', 'minimal'), ('claude', 'ultra'),
                                ('codex', 'minimal'), ('codex', 'none'), ('codex', 'ultracode'),
                                ('fake-harness', 'medium'), ('no-such-cli', 'high')):
            with self.subTest(harness=harness, effort=effort):
                code, out = self.start(harness, env, effort=effort)
                self.assertEqual(code, 1, out)
                self.assertIsNone(kit.invalid(out, schema), out)
                self.assertEqual(out['next'], "this host can't set effort: remove the effort for this harness in "
                                              "your Models table or Roster to run it at the host's default")
                self.assertIn(harness, out['error'])
                self.assertIn(effort, out['error'])
                self.assertFalse(os.path.exists(calls), 'a harness or gh ran')
                self.assertEqual(sorted(os.listdir(self.env['OPENWIZ_LOCAL_STATE'])), ['approvals.json'])
        self.assertEqual((self.logged(), self.argv_seen()), ([], []))

    def test_readme_has_the_effort_line_and_table_under_its_login_line(self):
        lines = read(os.path.join(HERE, 'README.md')).splitlines()
        login = lines.index('Login: stays on your machine')
        self.assertTrue(lines[login + 1].startswith('Effort: passed as '), lines[login + 1])
        table = [line for line in lines[login + 2:login + 12] if line.startswith('| ')]
        rows = {r.split('|')[1].strip().strip('`'): r for r in table[2:]}
        self.assertIn('`--effort <level>`', rows['claude'])
        self.assertIn('`CLAUDE_CODE_EFFORT_LEVEL`', rows['claude'])
        self.assertIn('-c model_reasoning_effort=<level>`', rows['codex'])
        for harness, levels in (('claude', ['low', 'medium', 'high', 'xhigh', 'max']),
                                ('codex', ['low', 'medium', 'high', 'xhigh', 'max', 'ultra'])):
            self.assertEqual(re.findall(r'`([a-z]+)`', rows[harness].split('|')[2].partition('for ')[2]), levels)
        self.assertIn('harness-row.md', ' '.join(table))


if __name__ == '__main__':
    unittest.main(verbosity=2)
