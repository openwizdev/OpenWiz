#!/usr/bin/env python3
import ctypes
import io
import json
import os
import re
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
FAKE = os.path.join(HERE, 'fixtures', 'bin', 'hermes')
TOKEN = 'gh' + 'p_' + 'Synthetic0Hermes0Value' * 2
API_KEY = 'synthetic-' + 'hermes-api-server-value'
CALLER_ONLY = 'synthetic-caller-only-value'
LOCALE_LOOKALIKE = 'synthetic-lc-named-app-value'
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'synthetic-model-1'}
CANT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at "
        "the host's default")
PR_SET_CHILD_SUBREAPER = 36
CHILD_ENV_ALLOWED = {'HOME', 'PATH', 'LANG', 'LC_ALL', 'OPENWIZ_RUN', 'OPENWIZ_KIT_RUN'}


def setUpModule():
    if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'the tests cannot keep the processes they start as their own')


def children(pid):
    found = set()
    try:
        for task in os.listdir('/proc/%d/task' % pid):
            with open('/proc/%d/task/%s/children' % (pid, task)) as f:
                found.update(int(c) for c in f.read().split())
    except OSError:
        pass
    return found


def running(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


class Hermes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.envs, self.state = os.path.join(self.folder, 'envs'), os.path.join(self.folder, 'state')
        self.configure()
        self.env = {'HOME': self.folder, 'LANG': 'C.UTF-8', 'GH_TOKEN': TOKEN, 'API_SERVER_KEY': API_KEY,
                    'CALLER_ONLY_SETTING': CALLER_ONLY, 'LC_ALL': 'C.UTF-8',
                    'LC_APPLICATION_SETTING': LOCALE_LOOKALIKE, 'OPENWIZ_HERMES_STATE': self.state,
                    'PATH': os.pathsep.join([os.path.join(HERE, 'fixtures', 'bin'), '/usr/bin', '/bin'])}
        reachable = {name: shutil.which(name, path=self.env['PATH']) for name in ('claude', 'codex', 'hermes')}
        self.assertEqual(reachable, {'claude': None, 'codex': None, 'hermes': FAKE},
                         'a real agent CLI is reachable on the test PATH: refusing to run')
        self.assertTrue(os.path.exists('/proc/%d/task/%d/children' % (os.getpid(), os.getpid())),
                        'this kernel lists no child processes, so the tests cannot find their own')

    def tearDown(self):
        for pid in self.ours():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def configure(self, **settings):
        with open(os.path.join(self.folder, '.fake-hermes.json'), 'w') as f:
            json.dump(dict({'hermes_home': os.path.join(self.folder, 'hermes'), 'tracker': self.tracker,
                            'turns': self.turns, 'hold': self.hold, 'envs': self.envs}, **settings), f)

    def ours(self):
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    break
            except ChildProcessError:
                break
        found, todo = set(), [os.getpid()]
        while todo:
            for c in children(todo.pop()) - found:
                found.add(c)
                todo.append(c)
        return sorted(p for p in found if running(p))

    def alive(self, pid):
        return pid in self.ours()

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def driver(self, cmd, request, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, json.loads(p.stdout)

    def logged(self):
        try:
            with open(self.turns) as f:
                return [(int(a), int(b), c, d, json.loads(e)) for a, b, c, d, e in
                        (line.rstrip('\n').split(' ', 4) for line in f)]
        except FileNotFoundError:
            return []

    def notes(self):
        with open(self.tracker) as f:
            return [(c['id'], c['body'].split('step: ')[1].split('\n')[0]) for c in json.load(f)['comments']]

    def test_version_lists_effort(self):
        code, out = self.driver('version', {})
        self.assertEqual(code, 0, out)
        self.assertEqual(set(out), {'driver', 'records', 'can'})
        self.assertIn('effort', out['can'])

    def test_a_hermes_start_passes_reasoning_at_start_and_wake(self):
        for model, effort in (('synthetic-model-1', 'medium'),
                              ('anthropic/claude-sonnet-4.6', 'medium'),
                              ('openrouter/anthropic/' + 'a' * 79, 'ultra')):
            with self.subTest(model=model, effort=effort):
                before = len(self.logged())
                code, out = self.driver('start', dict(REQUEST, harness='hermes', model=model, effort=effort))
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: len(self.logged()) > before
                                           and not self.alive(self.logged()[-1][0])),
                                'the first turn never ended')
                self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
                self.assertTrue(self.until(lambda: len(self.logged()) >= before + 2), 'the wake started no turn')
                for row in self.logged()[-2:]:
                    argv = row[4]
                    self.assertEqual(argv[argv.index('-m') + 1], model)
                    self.assertEqual(argv[argv.index('--reasoning') + 1], effort)

    def test_an_effort_hermes_cannot_set_is_refused_and_starts_nothing(self):
        cases = (dict(REQUEST, effort='medium'), dict(REQUEST, harness='codex', effort='high'),
                 dict(REQUEST, harness='hermes', effort='ultracode'), dict(REQUEST, harness='pi', effort='medium'),
                 dict(REQUEST, harness='claude', model='anthropic/claude-sonnet-4.6', effort='medium'),
                 dict(REQUEST, harness='codex', model='openrouter/anthropic/claude-sonnet-4.6', effort='high'))
        for req in cases:
            with self.subTest(harness=req['harness'], model=req['model'], effort=req['effort']):
                code, out = self.driver('start', req)
                self.assertEqual((code, out.get('next')), (1, CANT), out)
                self.assertIn(req['harness'], out['error'])
                self.assertIn(req['effort'], out['error'])
        for bad in ('a' * 101, '/anthropic/claude-sonnet-4.6', 'anthropic/', 'anthropic//claude-sonnet-4.6'):
            with self.subTest(bad_model=bad):
                code, out = self.driver('start', dict(REQUEST, harness='hermes', model=bad, effort='medium'))
                self.assertEqual((code, out), (1, {'error': 'model is not valid',
                                                   'next': 'fix model as `driver schema` shows'}))
        self.assertEqual((self.logged(), self.ours()), ([], []))
        self.assertFalse(os.path.isdir(self.state) and os.listdir(self.state), 'a refused start saved a run')

    def test_the_readme_effort_line_sits_under_login(self):
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        login = lines.index('Login: stays on your machine')
        effort = next(i for i, line in enumerate(lines) if line.startswith('Effort:'))
        self.assertEqual(effort, login + 2)
        self.assertTrue(lines[effort].startswith('Effort: passed as `hermes chat --reasoning <level>`'))
        rest = lines[effort + 1:]
        while rest and not rest[0].strip():
            rest.pop(0)
        rows = []
        for row in rest:
            if not row.startswith('|'):
                break
            rows.append(row)
        table = {}
        for row in rows:
            cells = [c.strip() for c in row.strip().strip('|').split('|')]
            if len(cells) >= 2 and cells[0] not in ('Harness', '---'):
                table[cells[0].strip('`')] = cells[1]
        self.assertTrue(table['hermes'].startswith('`--reasoning <level>`'))
        self.assertTrue(table['claude'].startswith("can't"))
        self.assertTrue(table['codex'].startswith("can't"))
        readme = '\n'.join(lines)
        self.assertIn('--format stream-json', readme)
        self.assertIn('v2026.9.24', readme)

    def test_kit_passes_all_five(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site',
                            '--ticket', '7', '--harness', 'claude', '--model', 'synthetic-model-1',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: refused for claude with the refusal text, '
            'as the README says',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver']), p.stderr)

    def test_wake_resumes_the_session_its_start_reported(self):
        for harness, skill in (('claude', 'claude-code'), ('codex', 'codex')):
            with self.subTest(harness=harness):
                code, out = self.driver('start', dict(REQUEST, harness=harness))
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: not self.alive(self.logged()[-1][0])), 'the first turn never ended')
                self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
                self.assertTrue(self.until(lambda: len(self.logged()) % 2 == 0), 'the wake started no turn')
                first, woken = self.logged()[-2:]
                self.assertEqual((first[3], woken[3], woken[2]), ('first', 'woken', first[2]))
                self.assertEqual(woken[4][woken[4].index('--resume') + 1], first[2])
                for argv in (first[4], woken[4]):
                    self.assertEqual(argv[argv.index('-s') + 1], skill)
                    self.assertNotIn('-m', argv)
                    self.assertIn('the model synthetic-model-1', argv[-1])
                self.assertEqual(self.notes()[-1][1], 'woke and read the ticket again')
        self.assertEqual(len(self.notes()), 2, 'a wake posted a second note')
        code, out = self.driver('start', dict(REQUEST, harness='hermes'))
        self.assertEqual(code, 0, out)
        argv = self.until(lambda: len(self.logged()) == 5) and self.logged()[-1][4]
        self.assertEqual((argv[argv.index('-m') + 1], '-s' in argv, '--reasoning' in argv),
                         ('synthetic-model-1', False, False))

    def test_a_wake_during_a_turn_runs_once_that_turn_ends(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()), 'the turn never began')
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        time.sleep(0.5)
        self.assertEqual(len(self.logged()), 1, 'a wake started a second turn beside the running one')
        os.remove(self.hold)
        self.assertTrue(self.until(lambda: len(self.logged()) >= 2), 'the wake was dropped once the turn ended')
        time.sleep(0.5)
        first, woken = self.logged()
        self.assertEqual((woken[3], woken[4][woken[4].index('--resume') + 1]), ('woken', first[2]))
        self.assertEqual(self.notes(), [(1, 'woke and read the ticket again')])
        self.assertTrue(self.until(lambda: not self.alive(woken[0])), 'the woken turn never ended')
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertTrue(self.until(lambda: len(self.logged()) == 3), 'a wake after both turns started none')

    def test_stop_interrupts_the_turn_then_ends_everything(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()), 'the turn never began')
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual([t[3] for t in self.logged()], ['first', 'interrupted'], 'stop never interrupted Hermes')
        time.sleep(0.5)
        self.assertEqual((len(self.logged()), self.ours()), (2, []), 'something of the run still runs after stop')
        self.assertEqual(self.driver('wake', out)[0], 1, 'a wake after stop was not refused')

    def test_hermes_gets_only_the_environment_it_needs(self):
        code, out = self.driver('start', REQUEST, OPENWIZ_KIT_RUN='synthetic-mark')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: os.path.exists(self.envs)), 'the turn never began')
        with open(self.envs) as f:
            [seen] = [json.loads(line)['env'] for line in f]
        self.assertLessEqual(set(seen), CHILD_ENV_ALLOWED, 'a caller variable reached Hermes')
        for value in (TOKEN, API_KEY, CALLER_ONLY, LOCALE_LOOKALIKE):
            self.assertNotIn(value, json.dumps(seen))
        self.assertEqual((seen['HOME'], seen['LC_ALL'], seen['OPENWIZ_KIT_RUN'], seen['OPENWIZ_RUN']),
                         (self.folder, 'C.UTF-8', 'synthetic-mark', out['run']))

    def test_cleanup_reads_no_process_before_it_knows_the_process_is_ours(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()), 'the turn never began')
        owned, strays, real = {str(os.getpid())}, [], open

        def recording(path, *args, **kwargs):
            f = real(path, *args, **kwargs)
            parts = path.split('/') if isinstance(path, str) else []
            if parts[:2] == ['', 'proc'] and parts[2].isdigit():
                if parts[2] not in owned:
                    strays.append(path)
                if parts[-1] == 'children':
                    text = f.read()
                    f.close()
                    owned.update(text.split())
                    return io.StringIO(text)
            return f
        globals()['open'] = recording
        try:
            found = self.ours()
        finally:
            del globals()['open']
        self.assertEqual(strays, [], 'cleanup read a process before it knew the process was ours')
        self.assertTrue({self.logged()[0][0], self.logged()[0][1]} <= set(found), 'cleanup missed the held turn')

    def test_the_turns_output_never_reaches_the_disk(self):
        self.configure(loud=2000)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged() and not self.alive(self.logged()[0][0])),
                        'a turn with a lot of output never ended')
        for root, _, files in os.walk(self.state):
            for name in files:
                self.assertRegex(name, r'^run-[0-9a-f]{12}\.(json|lock)$')
                with open(os.path.join(root, name), errors='replace') as f:
                    self.assertNotIn('SYNTHETIC-TRANSCRIPT-LINE', f.read())

    def test_a_start_without_a_session_starts_nothing_wakeable(self):
        self.configure(no_init=True)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 1, out)
        self.assertIn('did not report a session', out['error'])
        self.assertTrue(self.until(lambda: not self.ours()), 'its turn still runs')
        run = re.search(r'run-[0-9a-f]{12}', out['error']).group()
        self.assertEqual(self.driver('wake', {'run': run})[0], 1)
        self.assertEqual(len(self.logged()), 1, 'a wake started the failed run')

    def test_a_start_it_cannot_run_starts_nothing(self):
        code, out = self.driver('start', dict(REQUEST, harness='pi'))
        self.assertEqual((code, out['next']), (1, 'use one of: claude, codex, hermes'))
        code, out = self.driver('start', REQUEST, PATH='/usr/bin:/bin')
        self.assertEqual((code, out['error']), (1, 'hermes is not installed here'))
        self.assertEqual((self.logged(), self.ours()), ([], []))

    def test_the_readme_says_where_the_login_lives_under_its_title(self):
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        self.assertEqual(lines[:3], ['# Hermes driver', '', 'Login: stays on your machine'])

    def test_the_readme_leads_with_the_fixture_run(self):
        with open(os.path.join(HERE, 'README.md')) as f:
            kit = f.read().split('## The kit', 1)[1]
        commands = re.findall(r'^python3 .*$', kit.split('```sh', 1)[1].split('```', 1)[0], re.M)
        self.assertTrue(commands[0].startswith('python3 -I adapters/hermes/test_driver.py'), commands)
        self.assertNotIn('kit.py', kit.split('```sh', 1)[1].split('```', 1)[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
