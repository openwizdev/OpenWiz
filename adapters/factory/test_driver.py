#!/usr/bin/env python3
import json
import os
import ctypes
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
TOKEN = 'gh' + 'p_' + 'Synthetic0Factory0Value' * 2
API_KEY = 'fk' + '-synthetic0factory0value'
REAL_PROGRAMS = ('droid', 'claude', 'codex', 'gh', 'hermes', 'boat', 'cursor-agent', 'devin', 'room-cli', 'git',
                 'sh', 'sleep')
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'droid',
           'model': 'synthetic-model-1'}


CANT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to "
        "run it at the host's default")


def setUpModule():
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise unittest.SkipTest('this host cannot make the test a subreaper')


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


class Factory(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.turns = os.path.join(self.folder, 'turns')
        self.pydir = self.python()
        self.env = {'HOME': self.folder, 'LANG': 'C.UTF-8', 'KIT_TRACKER': self.tracker,
                    'GH_TOKEN': TOKEN, 'FACTORY_API_KEY': API_KEY, 'FAKE_TURNS': self.turns,
                    'FAKE_FACTORY_HOME': os.path.join(self.folder, 'factory'),
                    'OPENWIZ_FACTORY_STATE': os.path.join(self.folder, 'state'),
                    'PATH': os.pathsep.join([os.path.join(HERE, 'fixtures', 'bin'), self.pydir])}
        for real in REAL_PROGRAMS:
            found = shutil.which(real, path=self.env['PATH'])
            self.assertTrue(found is None or os.path.dirname(found) == os.path.join(HERE, 'fixtures', 'bin'),
                            'a real %s is reachable on the test PATH: %s' % (real, found))

    def python(self):
        only = os.path.join(self.folder, 'python-only')
        os.mkdir(only)
        os.symlink(sys.executable, os.path.join(only, 'python3'))
        return only

    def tearDown(self):
        self.addCleanup(shutil.rmtree, self.folder, True)
        for pid in self.marked():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def marked(self):
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
        parents = {}
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/stat' % pid) as f:
                    fields = f.read().rpartition(')')[2].split()
            except OSError:
                continue
            if fields[0] != 'Z':
                parents.setdefault(int(fields[1]), []).append(int(pid))
        found, todo = [], [os.getpid()]
        while todo:
            for child in parents.get(todo.pop(), []):
                found.append(child)
                todo.append(child)
        return found

    def call(self, cmd, request, cwd=None, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env), cwd=cwd,
                           capture_output=True, text=True, timeout=60, preexec_fn=lambda: os.umask(0o022))
        return p.returncode, json.loads(p.stdout)

    def logged(self):
        try:
            with open(self.turns) as f:
                return [tuple(line.split()) for line in f]
        except FileNotFoundError:
            return []

    def test_kit_passes_all_five(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site',
                            '--ticket', '7', '--harness', 'droid', '--model', 'synthetic-model-1',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines(), p.stderr), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: medium reached a process the run started',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver'], ''))

    def test_other_harness_is_refused_before_anything_runs(self):
        code, out = self.call('start', dict(REQUEST, harness='claude'))
        self.assertEqual(code, 1, out)
        self.assertIn('droid', out['next'])
        time.sleep(0.5)
        self.assertEqual((self.logged(), self.marked()), ([], []))

    def test_wake_without_a_session_starts_nothing(self):
        code, out = self.call('start', REQUEST, FAKE_SIGNED_OUT='1')
        self.assertEqual(code, 0, out)
        deadline = time.monotonic() + 10
        while self.marked() and time.monotonic() < deadline:
            time.sleep(0.05)
        code, err = self.call('wake', out, FAKE_SIGNED_OUT='')
        self.assertEqual(code, 1, err)
        self.assertIn('no Droid session', err['error'])
        time.sleep(0.5)
        self.assertEqual((self.logged(), self.marked()), ([], []))

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def test_turn_inherits_the_callers_environment_unchanged(self):
        seen = os.path.join(self.folder, 'turn-env.json')
        code, out = self.call('start', REQUEST, FAKE_ENV_LOG=seen)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: os.path.exists(seen) and os.path.getsize(seen)), 'no turn ran')
        with open(seen) as f:
            self.assertEqual(json.load(f), dict(self.env, FAKE_ENV_LOG=seen))

    def test_state_keeps_only_the_session_id(self):
        code, out = self.call('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1), 'no turn ran')
        session = self.logged()[0][2]
        self.assertEqual(self.call('wake', out), (0, dict(out, woke=True)))
        self.assertTrue(self.until(lambda: len(self.logged()) == 2), 'the wake ran no turn')
        self.assertEqual(self.logged()[0][3:], ('first', '-'))
        self.assertEqual(self.logged()[1][2:], (session, 'woken', '-'))
        kept = b''
        for root, _, files in os.walk(self.env['OPENWIZ_FACTORY_STATE']):
            for name in files:
                with open(os.path.join(root, name), 'rb') as f:
                    kept += f.read()
        self.assertNotIn(b'FAKE-STDOUT-MARKER', kept)
        self.assertNotIn(b'FAKE-STDERR-MARKER', kept)
        self.assertNotIn(b'Synthetic turn.', kept)

    def test_state_is_owner_only(self):
        code, out = self.call('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.call('stop', out), (0, dict(out, stopped=True)))
        modes = {}
        for root, dirs, files in os.walk(self.env['OPENWIZ_FACTORY_STATE']):
            for name in dirs + files:
                modes[os.path.join(root, name)] = os.stat(os.path.join(root, name)).st_mode & 0o077
        self.assertTrue(modes)
        self.assertEqual({p: m for p, m in modes.items() if m}, {})

    def test_state_others_can_read_is_refused_before_anything_runs(self):
        shared = os.path.join(self.folder, 'shared')
        os.mkdir(shared, 0o755)
        os.chmod(shared, 0o755)
        code, out = self.call('start', REQUEST, OPENWIZ_FACTORY_STATE=shared)
        self.assertEqual(code, 1, out)
        self.assertIn('chmod 700', out['next'])
        time.sleep(0.5)
        self.assertEqual((self.logged(), self.marked(), os.listdir(shared)), ([], [], []))

    def unrelated_tree(self):
        other = subprocess.Popen([sys.executable, '-c', 'import subprocess, sys, time; print(subprocess.Popen(['
                                  'sys.executable, "-c", "import time; time.sleep(60)"]).pid, flush=True); '
                                  'time.sleep(60)'], stdout=subprocess.PIPE, text=True)
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)
        child = int(other.stdout.readline())
        other.stdout.close()
        with open('/proc/%d/stat' % other.pid) as f:
            since = int(f.read().rpartition(')')[2].split()[19])
        return other, child, [{'n': 0, 'pid': other.pid, 'since': since, 'supervisor': other.pid,
                               'supervisor_since': since}]

    def test_stop_on_a_tampered_folder_never_signals_a_process_matched_by_its_command_line(self):
        state = self.env['OPENWIZ_FACTORY_STATE']
        os.mkdir(state, 0o700)
        run = 'run-00000000000b'
        with open(os.path.join(state, run + '.json'), 'w') as f:
            json.dump({'request': REQUEST, 'stopped': False, 'turns': []}, f)
        lookalike = subprocess.Popen([sys.executable, '-I', DRIVER, '--turn', os.path.join(state, run + '.0.session'),
                                      sys.executable, '-c', 'import time; time.sleep(60)'],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
        self.addCleanup(lookalike.wait)
        self.addCleanup(lookalike.kill)
        child = json.loads(lookalike.stdout.readline())['pid']
        lookalike.stdout.close()
        self.addCleanup(lambda: alive(child) and os.kill(child, signal.SIGKILL))
        os.chmod(state, 0o777)
        code, out = self.call('stop', {'run': run})
        self.assertTrue(alive(lookalike.pid) and alive(child), 'stop signalled a process matched by command line')
        self.assertEqual(code, 1, out)
        self.assertIn(state, out['error'])
        self.assertIn('by hand', out['next'])

    def test_stop_on_a_tampered_folder_ends_nothing_and_says_so(self):
        state = self.env['OPENWIZ_FACTORY_STATE']
        code, out = self.call('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1), 'no turn ran')
        worker = int(self.logged()[0][1])
        other, child, planted = self.unrelated_tree()
        manifest = os.path.join(state, out['run'] + '.json')
        with open(manifest) as f:
            saved = json.load(f)
        with open(manifest, 'w') as f:
            json.dump(dict(saved, turns=planted), f)
        os.chmod(manifest, 0o666)
        os.chmod(state, 0o777)
        code, err = self.call('stop', out)
        self.assertEqual(code, 1, err)
        self.assertIn(state, err['error'])
        self.assertIn('by hand', err['next'])
        self.assertTrue(alive(child) and alive(other.pid), 'stop ended a process named only by the tampered state')
        self.assertTrue(alive(worker), 'stop signalled a process it found without trusted state')
        self.assertEqual(self.call('wake', out)[0], 1, 'a wake ran on a tampered folder')

    def test_stop_and_wake_refuse_a_run_they_cannot_trust(self):
        state = self.env['OPENWIZ_FACTORY_STATE']
        other, child, turns = self.unrelated_tree()
        planted = {'request': REQUEST, 'stopped': False, 'session': 'synthetic-session-1', 'turns': turns}
        elsewhere = os.path.join(self.folder, 'elsewhere.json')
        for case, folder_mode, file_mode, linked in (('others can write the folder', 0o777, 0o600, False),
                                                     ('others can write the manifest', 0o700, 0o666, False),
                                                     ('the manifest is a link', 0o700, 0o600, True)):
            with self.subTest(case):
                shutil.rmtree(state, True)
                os.mkdir(state)
                manifest = os.path.join(state, 'run-00000000000a.json')
                with open(elsewhere if linked else manifest, 'w') as f:
                    json.dump(planted, f)
                if linked:
                    os.symlink(elsewhere, manifest)
                os.chmod(elsewhere if linked else manifest, file_mode)
                os.chmod(state, folder_mode)
                for cmd in ('stop', 'wake'):
                    code, out = self.call(cmd, {'run': 'run-00000000000a'})
                    self.assertEqual(code, 1, '%s accepted a run it cannot trust: %s' % (cmd, out))
                    self.assertNotIn('still has processes', out['error'], '%s went after the planted processes' % cmd)
                    self.assertIn('not yours alone', out['error'])
                    self.assertIn(state, out['error'])
                    self.assertIn('by hand', out['next'])
                    self.assertTrue(alive(child), '%s ended a process the driver never started' % cmd)
                self.assertEqual(self.logged(), [], 'a wake ran a turn from a run it cannot trust')

    def test_relative_state_still_runs_the_turn(self):
        code, out = self.call('start', REQUEST, cwd=self.folder, OPENWIZ_FACTORY_STATE='relative-state')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1), 'droid never ran its turn')
        self.assertTrue(os.path.isdir(os.path.join(self.folder, 'relative-state', 'work', out['run'])))

    def droid_calls(self, path):
        try:
            with open(path) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def test_a_listed_effort_reaches_droid_on_start_and_wake(self):
        pairs = [('synthetic-model-all', e) for e in
                 ('none', 'dynamic', 'off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')] + [
            ('synthetic-model-1', 'high'), ('synthetic-model-max', 'max'),
            ('synthetic-model-narrow', 'off'), ('synthetic-model-legacy', 'minimal')]
        for i, (model, effort) in enumerate(pairs):
            with self.subTest(model=model, effort=effort):
                calls = os.path.join(self.folder, 'calls-%d' % i)
                argv = os.path.join(self.folder, 'argv-%d' % i)
                code, out = self.call('start', dict(REQUEST, model=model, effort=effort),
                                      FAKE_TURNS=calls, FAKE_DROID_ARGS=argv)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: len(self.rows(calls)) == 1), calls)
                code, woke = self.call('wake', out, FAKE_TURNS=calls, FAKE_DROID_ARGS=argv)
                self.assertEqual((code, woke.get('woke')), (0, True), woke)
                self.assertTrue(self.until(lambda: len(self.rows(calls)) == 2), calls)
                rows = self.rows(calls)
                self.assertEqual([row[3:] for row in rows], [['first', effort], ['woken', effort]])
                self.assertEqual(rows[0][2], rows[1][2])
                self.assertEqual([c for c in self.droid_calls(argv) if c == ['exec', '--help']], [['exec', '--help']])

    def rows(self, path):
        try:
            with open(path) as f:
                return [line.split() for line in f]
        except FileNotFoundError:
            return []

    def test_an_effort_droid_cannot_take_is_refused_and_nothing_starts(self):
        cases = (
            (dict(REQUEST, model='synthetic-model-1', effort='max'), [['exec', '--help']]),
            (dict(REQUEST, model='synthetic-model-1', effort='off'), [['exec', '--help']]),
            (dict(REQUEST, model='synthetic-model-narrow', effort='medium'), [['exec', '--help']]),
            (dict(REQUEST, model='synthetic-model-max', effort='minimal'), [['exec', '--help']]),
            (dict(REQUEST, model='synthetic-model-plain', effort='none'), [['exec', '--help']]),
            (dict(REQUEST, model='synthetic-model-plain', effort='low'), [['exec', '--help']]),
            (dict(REQUEST, model='synthetic-unlisted', effort='medium'), [['exec', '--help']]),
            (dict(REQUEST, model='anthropic/claude-sonnet-4.6', effort='medium'), [['exec', '--help']]),
            (dict(REQUEST, effort='ultra'), [['exec', '--help']]),
            (dict(REQUEST, effort='thinking'), [['exec', '--help']]),
            (dict(REQUEST, harness='claude', effort='medium'), []),
            (dict(REQUEST, harness='claude', model='anthropic/claude-sonnet-4.6', effort='medium'), []),
            (dict(REQUEST, model='custom:synthetic-0', effort='medium'), []),
            (dict(REQUEST, model='custom:synthetic-0', effort='max'), []))
        for i, (req, expected_calls) in enumerate(cases):
            with self.subTest(harness=req['harness'], model=req['model'], effort=req['effort']):
                calls = os.path.join(self.folder, 'refused-%d' % i)
                argv = os.path.join(self.folder, 'refused-argv-%d' % i)
                state = os.path.join(self.folder, 'refused-state-%d' % i)
                code, out = self.call('start', req, FAKE_TURNS=calls, FAKE_DROID_ARGS=argv,
                                      OPENWIZ_FACTORY_STATE=state)
                self.assertEqual((code, out.get('next')), (1, CANT), out)
                self.assertIn(req['harness'], out['error'])
                self.assertIn(req['effort'], out['error'])
                self.assertLessEqual(len(out['error']), 300)
                time.sleep(0.05)
                self.assertEqual((self.droid_calls(argv), self.rows(calls), self.marked(),
                                  os.path.exists(state)), (expected_calls, [], [], False))

    def test_the_driver_reads_the_level_list_droid_1_21_1_prints(self):
        cases = (
            ('gpt-5.4', 'high', True),
            ('gpt-5.4', 'max', False),
            ('claude-opus-5-5', 'max', True),
            ('claude-opus-5-5', 'off', False),
            ('gpt-6-sol', 'none', True),
            ('auto', 'none', False),
            ('minimax-m3', 'high', True),
            ('minimax-m3', 'medium', False),
            ('gemini-3.5-flash', 'minimal', True),
            ('mistral-medium-3.5', 'off', True),
            ('mistral-medium-3.5', 'low', False),
            ('claude-sonnet-4-5-20250929', 'high', True),
            ('claude-sonnet-4-5-20250929', 'max', False))
        for i, (model, effort, passed) in enumerate(cases):
            with self.subTest(model=model, effort=effort):
                calls = os.path.join(self.folder, 'live-%d' % i)
                argv = os.path.join(self.folder, 'live-argv-%d' % i)
                state = os.path.join(self.folder, 'live-state-%d' % i)
                code, out = self.call('start', dict(REQUEST, model=model, effort=effort),
                                      FAKE_DROID_HELP='live', FAKE_TURNS=calls, FAKE_DROID_ARGS=argv,
                                      OPENWIZ_FACTORY_STATE=state)
                self.assertEqual(code, 0 if passed else 1, out)
                if passed:
                    self.assertTrue(self.until(lambda: len(self.rows(calls)) == 1), calls)
                    self.assertEqual(self.rows(calls)[0][3:], ['first', effort])
                else:
                    self.assertEqual(out['next'], CANT, out)
                    self.assertIn('droid', out['error'])
                    self.assertIn(effort, out['error'])
                    self.assertEqual((self.droid_calls(argv), self.rows(calls), os.path.exists(state)),
                                     ([['exec', '--help']], [], False))

    def test_a_start_whose_levels_cannot_be_read_starts_nothing(self):
        marker = 'sk-' + 'Synthetic0Factory0Marker'
        cases = (
            ('help fails', dict(FAKE_DROID_FAIL='help', FAKE_MARKER=marker)),
            ('no available models', dict(FAKE_DROID_HELP='bare')),
            ('no model details', dict(FAKE_DROID_HELP='no-details')),
            ('truncated model details', dict(FAKE_DROID_HELP='truncated')),
            ('malformed model detail', dict(FAKE_DROID_HELP='bad-line')),
            ('invalid effort word', dict(FAKE_DROID_HELP='bad-level')),
            ('empty supported levels', dict(FAKE_DROID_HELP='empty-levels')),
            ('stdout diagnostic', dict(FAKE_DROID_HELP='stdout-secret', FAKE_MARKER=marker)),
            ('droid missing', dict(PATH=self.pydir)))
        for i, (name, extra) in enumerate(cases):
            with self.subTest(name):
                calls = os.path.join(self.folder, 'unreadable-%d' % i)
                state = os.path.join(self.folder, 'unreadable-state-%d' % i)
                code, out = self.call('start', dict(REQUEST, effort='medium'),
                                      FAKE_TURNS=calls, OPENWIZ_FACTORY_STATE=state, **extra)
                self.assertEqual((code, sorted(out)), (1, ['error', 'next']), out)
                self.assertNotEqual(out['next'], CANT)
                self.assertNotIn(marker, json.dumps(out))
                self.assertNotIn('Synthetic', json.dumps(out))
                self.assertEqual((self.rows(calls), self.marked(), os.path.exists(state)), ([], [], False))

    def test_a_custom_model_with_no_effort_still_starts_at_the_host_default(self):
        calls = os.path.join(self.folder, 'custom-default')
        argv = os.path.join(self.folder, 'custom-argv')
        code, out = self.call('start', dict(REQUEST, model='custom:synthetic-0'),
                              FAKE_TURNS=calls, FAKE_DROID_ARGS=argv)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.rows(calls)) == 1), calls)
        self.assertEqual(self.rows(calls)[0][3:], ['first', '-'])
        self.assertNotIn(['exec', '--help'], self.droid_calls(argv))

    def test_an_effort_word_outside_the_schema_is_refused_as_input(self):
        code, out = self.call('start', dict(REQUEST, effort='Medium'))
        self.assertEqual((code, out), (1, {'error': 'effort is not valid',
                                            'next': 'fix effort as `driver schema` shows'}))
        self.assertFalse(os.path.exists(self.env['OPENWIZ_FACTORY_STATE']))

    def test_version_lists_effort(self):
        self.assertEqual(self.call('version', None), (0, {
            'driver': 'factory', 'records': ['openwiz:records v1'],
            'can': ['start', 'wake', 'stop', 'effort']}))

    def test_readme_opens_with_the_login_line_under_its_title(self):
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        self.assertEqual((lines[0][:2], lines[1:4]), ('# ', ['', 'Login: held by Factory', '']))
        self.assertTrue(lines[4].startswith('Effort: passed as `--reasoning-effort <level>` to `droid exec`'), lines[4])
        self.assertIn('`droid exec --help`', lines[4])
        self.assertIn('`FACTORY_API_KEY`', '\n'.join(lines))
        self.assertIn('**Platforms:** Linux only, Python 3.9 or later', '\n'.join(lines))


if __name__ == '__main__':
    unittest.main(verbosity=2)
