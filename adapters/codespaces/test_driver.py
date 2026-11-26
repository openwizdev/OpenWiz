#!/usr/bin/env python3
import ctypes
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
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'kit.py')
NO_PROC = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'fixtures', 'no-proc')
TOKEN = 'gh' + 'p_' + 'Synthetic0Spaces0Value' * 2 + '00'
SECRET_NAMES = ('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY', 'CODEX_API_KEY')
RESERVED = SECRET_NAMES + ('OPENAI_API_KEY', 'GITHUB_TOKEN', 'GH_TOKEN')
WATCHED = 'PLANTED_AMBIENT_TOKEN'
WATCH_READS = r'''
import os, runpy, sys
reads, real = os.environ['WATCH_READS'], os._Environ.__getitem__
def watched(self, key):
    if key == %r:
        with open(reads, 'a') as f:
            f.write(sys._getframe(1).f_code.co_name + '\n')
    return real(self, key)
os._Environ.__getitem__ = watched
sys.argv = [%r] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
''' % (WATCHED, DRIVER)
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 1; effort: medium reached a process the run started',
        'pass wake: the run edited builder status note 1',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}
CODEX = dict(REQUEST, harness='codex', model='gpt-6.2-sol')

if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
    raise SystemExit('these tests need Linux, to keep the processes they start under them')


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


class Codespaces(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        tools = os.path.join(self.folder, 'tools')
        os.mkdir(tools)
        for name in ('python3', 'sh', 'sleep', 'mktemp', 'rm', 'readlink', 'ln', 'mkdir', 'dirname', 'lsof'):
            os.symlink(shutil.which(name), os.path.join(tools, name))
        self.hold, self.marker = os.path.join(self.folder, 'hold'), 'marker' + secrets.token_hex(8)
        self.env = dict(HOME=self.folder, KIT_TRACKER=self.tracker, GH_TOKEN=TOKEN, FAKE_MARKER=self.marker,
                        FAKE_TURNS=os.path.join(self.folder, 'turns'), FAKE_HOLD=self.hold,
                        FAKE_GH_STATE=os.path.join(self.folder, 'gh.json'),
                        FAKE_GH_ARGS=os.path.join(self.folder, 'gh-args'),
                        OPENWIZ_CODESPACES_STATE=os.path.join(self.folder, 'state'), OPENWIZ_CODESPACES_SETTLE='2',
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + tools)
        for real in ('claude', 'codex', 'git', 'npm'):
            self.assertIsNone(shutil.which(real, path=self.env['PATH']), "a real %s is on the tests' PATH" % real)

    def tearDown(self):
        def ours():
            children = {}
            for pid in filter(str.isdigit, os.listdir('/proc')):
                try:
                    with open('/proc/%s/stat' % pid) as f:
                        fields = f.read().rpartition(')')[2].split()
                except OSError:
                    continue
                if fields[0] != 'Z':
                    children.setdefault(int(fields[1]), []).append(int(pid))
            found, todo = [], [os.getpid()]
            while todo:
                for c in children.get(todo.pop(), []):
                    found.append(c)
                    todo.append(c)
            return found
        for pid in ours():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG)[0] == 0:
                    time.sleep(0.01)
            except ChildProcessError:
                break
        shutil.rmtree(self.folder, ignore_errors=True)

    def driver(self, cmd, request, program=(DRIVER,), **env):
        p = subprocess.run(list(program) + [cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        self.assertNotIn(self.marker, p.stdout + p.stderr, "gh's own text reached the driver's answer")
        out = json.loads(p.stdout)
        if p.returncode:
            self.assertEqual(sorted(out), ['error', 'next'])
            self.assertTrue(all(0 < len(v) <= 300 and '\n' not in v for v in out.values()), out)
        return p.returncode, out

    def kit(self, harness, model, **env):
        return subprocess.run([env.pop('python', sys.executable), '-I', KIT, '--driver', DRIVER, '--repo',
                               'example/site', '--ticket', '7', '--harness', harness, '--model', model,
                               '--tracker', self.tracker, '--wait', '8'],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=300)

    def calls(self):
        try:
            with open(self.env['FAKE_GH_ARGS']) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def codespaces(self):
        try:
            with open(self.env['FAKE_GH_STATE']) as f:
                return {k: v['state'] for k, v in json.load(f)['codespaces'].items()}
        except FileNotFoundError:
            return {}

    def logged(self):
        try:
            with open(self.env['FAKE_TURNS']) as f:
                return [(int(p), s, k) for p, s, k, _ in (line.split() for line in f)]
        except FileNotFoundError:
            return []

    def efforts(self):
        try:
            with open(self.env['FAKE_TURNS']) as f:
                return [(k, e) for _, _, k, e in (line.split() for line in f)]
        except FileNotFoundError:
            return []

    def notes(self):
        with open(self.tracker) as f:
            return [(c['id'], c['body'].split('step: ')[1].split('\n')[0]) for c in json.load(f)['comments']]

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def ended(self, out):
        with open(os.path.join(self.env['OPENWIZ_CODESPACES_STATE'], out['run'] + '.json')) as f:
            pid = json.load(f)['turns'][-1]['pid']
        return self.until(lambda: not alive(pid))

    def test_kit_passes_all_five_for_each_harness(self):
        for harness, model in (('claude', 'claude-opus-5-5'), ('codex', 'gpt-6.2-sol')):
            with self.subTest(harness=harness):
                self.tearDown()
                self.setUp()
                p = self.kit(harness, model)
                self.assertEqual((p.returncode, p.stdout.splitlines()), (0, PASS), p.stderr)
                self.assertEqual(set(self.codespaces().values()), {'Shutdown'})

    def test_kit_passes_all_five_without_proc_as_on_macos(self):
        with open(self.hold, 'w') as f:
            f.write('woken')
        p = self.kit('claude', 'claude-opus-5-5', python=os.path.join(NO_PROC, 'python3'),
                     PATH=NO_PROC + os.pathsep + self.env['PATH'], NO_PROC_PYTHON=sys.executable)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, PASS), p.stderr)

    def test_the_prechecks_refuse_before_any_codespace_create(self):
        cases = (('no codespace scope', REQUEST, {'FAKE_GH_SCOPES': 'gist, read:org, repo, workflow'},
                  'codespace scope'),
                 ('no secret of the harness', CODEX, {'FAKE_GH_SECRETS': '{"ANTHROPIC_API_KEY": ["example/site"]}'},
                  'CODEX_API_KEY'),
                 ('the secret is for another repository', REQUEST,
                  {'FAKE_GH_SECRETS': '{"CLAUDE_CODE_OAUTH_TOKEN": ["example/other"]}'}, 'example/site'),
                 ('gh is not signed in', REQUEST, {'FAKE_GH_FAIL': 'auth'}, 'signed in'),
                 ('the secrets cannot be listed', REQUEST, {'FAKE_GH_FAIL': 'secrets'}, 'secrets'),
                 ('a harness Codespaces has no secret for', dict(REQUEST, harness='pi'), {}, 'pi'))
        for case, request, env, named in cases:
            with self.subTest(case=case):
                code, err = self.driver('start', request, **env)
                self.assertEqual(code, 1, err)
                self.assertIn(named, err['error'] + err['next'])
                self.assertIn('nothing was created', err['error'])
                self.assertEqual([c for c in self.calls() if c[:2] == ['codespace', 'create']], [])
                self.assertEqual(self.codespaces(), {})
        code, out = self.driver('start', dict(REQUEST, repository='Example/Site'),
                                FAKE_GH_SECRETS='{"ANTHROPIC_API_KEY": ["example/site"]}')
        self.assertEqual(code, 0, out)

    def test_create_takes_the_specs_flags_and_always_names_a_machine(self):
        for env, machine in (({}, ['-m', 'basicLinux32gb']),
                             ({'OPENWIZ_CODESPACES_MACHINE': 'standardLinux32gb'}, ['-m', 'standardLinux32gb'])):
            code, out = self.driver('start', REQUEST, **env)
            self.assertEqual(code, 0, out)
            self.assertRegex(out['run'], r'^cs-[0-9a-f]{12}$')
            self.assertEqual([c for c in self.calls() if c[:2] == ['codespace', 'create']][-1],
                             ['codespace', 'create', '-R', 'example/site', '--default-permissions', '--display-name',
                              'openwiz-7', '--idle-timeout', '240m', '--retention-period', '72h'] + machine)
        code, err = self.driver('start', REQUEST, OPENWIZ_CODESPACES_MACHINE='bad machine; rm')
        self.assertEqual(code, 1, err)
        self.assertIn('OPENWIZ_CODESPACES_MACHINE', err['error'])
        creates = len([c for c in self.calls() if c[:2] == ['codespace', 'create']])
        for settle in ('0', '61', 'soon'):
            code, err = self.driver('start', REQUEST, OPENWIZ_CODESPACES_SETTLE=settle)
            self.assertEqual(code, 1, err)
            self.assertIn('OPENWIZ_CODESPACES_SETTLE', err['error'])
        self.assertEqual(len([c for c in self.calls() if c[:2] == ['codespace', 'create']]), creates)

    def test_a_wake_after_stop_or_for_an_unknown_run_is_refused(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()))
        harness = self.logged()[0][0]
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(harness), 'the turn still runs after stop')
        self.assertEqual(list(self.codespaces().values()), ['Shutdown'])
        code, err = self.driver('wake', out)
        self.assertEqual((code, err['error']), (1, 'run %s is stopped' % out['run']))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)), 'a second stop did not answer')
        code, err = self.driver('wake', {'run': 'cs-0123456789ab'})
        self.assertEqual((code, err['error']), (1, 'no run cs-0123456789ab'))
        self.assertEqual(len(self.logged()), 1)

    def test_an_effort_reaches_the_fake_harness_on_start_and_every_wake_and_none_passes_no_flag(self):
        version = subprocess.run([DRIVER, 'version'], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertIn('effort', json.loads(version.stdout)['can'])
        for request, effort in ((REQUEST, 'xhigh'), (CODEX, 'high'), (REQUEST, None), (CODEX, None)):
            with self.subTest(harness=request['harness'], effort=effort):
                self.tearDown()
                self.setUp()
                code, out = self.driver('start', dict(request, effort=effort) if effort else request)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out), 'the first turn never ended')
                self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
                self.assertTrue(self.ended(out), 'the woken turn never ended')
                self.assertEqual(self.efforts(), [('first', effort or '-'), ('woken', effort or '-')])

    def test_a_wake_after_github_stopped_the_codespace_resumes_the_same_session(self):
        for request in (REQUEST, CODEX):
            with self.subTest(harness=request['harness']):
                code, out = self.driver('start', request)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out), 'the first turn never ended')
                name = max(self.codespaces())
                subprocess.run(['gh', 'codespace', 'stop', '-c', name], env=self.env, check=True)
                self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
                self.assertTrue(self.ended(out), 'the woken turn never ended')
                (_, first, a), (_, then, b) = self.logged()[-2:]
                self.assertEqual((first, a, then, b), (first, 'first', first, 'woken'))
                self.assertEqual(self.notes()[-1][1], 'woke and read the ticket again')
                self.assertEqual(self.codespaces()[name], 'Available')
                with open(os.path.join(self.env['OPENWIZ_CODESPACES_STATE'], out['run'] + '.json')) as f:
                    self.assertEqual(json.load(f)['session'], first)
        self.assertEqual(len(self.notes()), 2)

    def test_a_wake_while_the_turn_runs_starts_nothing(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual(len(self.logged()), 1)

    def test_a_rebuilt_codespace_refuses_the_wake_in_one_line(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        shutil.rmtree(self.env['FAKE_GH_STATE'] + '.homes/' + max(self.codespaces()))
        code, err = self.driver('wake', out)
        self.assertEqual(code, 1, err)
        self.assertIn('lost its home folder', err['error'])
        self.assertEqual(len(self.logged()), 1)

    def test_no_ssh_command_names_or_expands_a_secret(self):
        for request in (REQUEST, CODEX):
            code, out = self.driver('start', request)
            self.assertEqual(code, 0, out)
            self.assertTrue(self.ended(out))
            self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
            self.assertTrue(self.ended(out))
        sent = [' '.join(c[5:]) for c in self.calls() if c[:2] == ['codespace', 'ssh']]
        self.assertEqual(len(sent), 8)
        for command in sent:
            for name in SECRET_NAMES:
                self.assertNotIn(name, command)
            self.assertIsNone(re.search(r'\b(?:printenv|env|export|declare)\b|\bset\b(?! -eu\n)', command), command)
        self.assertEqual(len(self.notes()), 2, 'a harness did not sign in with the codespace secret')

    def test_gh_text_never_reaches_an_answer_and_a_failed_start_step_stops_the_codespace(self):
        for fails in ('create', 'ssh', 'ssh-install-refused'):
            with self.subTest(fails=fails):
                env = {'FAKE_WIZ_COMMIT': '0' * 40} if fails == 'ssh-install-refused' else {'FAKE_GH_FAIL': fails}
                code, err = self.driver('start', REQUEST, **env)
                self.assertEqual(code, 1, err)
                self.assertNotIn('synthetic', json.dumps(err))
                self.assertEqual(set(self.codespaces().values()) - {'Shutdown'}, set(), err)
                self.assertEqual(self.logged(), [])
        self.assertEqual(len(self.codespaces()), 2)
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.ended(out))
        code, err = self.driver('wake', out, FAKE_GH_FAIL='ssh')
        self.assertEqual(code, 1, err)
        code, err = self.driver('stop', out, FAKE_GH_FAIL='stop')
        self.assertEqual(code, 1, err)
        self.assertIn('gh codespace stop -c %s' % max(self.codespaces()), err['next'])
        for _ in range(2):
            self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_a_start_whose_cleanup_stop_fails_retries_then_names_the_run_to_stop(self):
        code, err = self.driver('start', REQUEST, FAKE_WIZ_COMMIT='0' * 40, FAKE_GH_FAIL='stop*1')
        self.assertEqual((code, list(self.codespaces().values())), (1, ['Shutdown']), err)
        code, err = self.driver('start', REQUEST, FAKE_WIZ_COMMIT='0' * 40, FAKE_GH_FAIL='stop,view')
        self.assertEqual((code, self.codespaces()['fake-space-0002']), (1, 'Available'), err)
        self.assertIn('codespace fake-space-0002 may still run', err['error'])
        self.assertIn('gh codespace stop -c fake-space-0002', err['next'])
        run = re.search(r'\bcs-[0-9a-f]{12}\b', err['error'] + err['next'])
        self.assertTrue(run, 'the refusal names no run to stop')
        self.assertEqual(self.driver('stop', {'run': run.group(0)}), (0, {'run': run.group(0), 'stopped': True}))
        self.assertEqual(self.codespaces()['fake-space-0002'], 'Shutdown')

    def test_stop_never_reads_a_codespace_missing_from_a_cut_list_as_stopped(self):
        with open(self.env['FAKE_GH_STATE'], 'w') as f:
            json.dump({'codespaces': {'other-%02d' % i: {'repository': 'example/other', 'displayName': 'x',
                                                          'state': 'Available', 'machine': None} for i in range(30)}}, f)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        code, err = self.driver('stop', out, FAKE_GH_FAIL='stop')
        self.assertEqual((code, self.codespaces()['fake-space-0031']), (1, 'Available'), err)
        self.assertIn('gh codespace stop -c fake-space-0031', err['next'])
        with open(self.env['FAKE_GH_STATE']) as f:
            state = json.load(f)
        del state['codespaces']['fake-space-0031']
        with open(self.env['FAKE_GH_STATE'], 'w') as f:
            json.dump(state, f)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_start_refuses_a_credential_by_its_shape_and_never_reads_the_environment_for_one(self):
        env = {'PLANTED_TOKEN': 'plainwordvalue1234'}
        code, out = self.driver('start', dict(REQUEST, model='plainwordvalue1234'), **env)
        self.assertEqual(code, 0, out)
        code, err = self.driver('start', dict(REQUEST, model='sk-' + 'A' * 24), **env)
        self.assertEqual((code, err['error']), (1, 'model looks like a credential, so nothing was saved or started'))
        with open(DRIVER) as f:
            self.assertNotIn('kit.py', f.read())

    def test_every_stop_confirms_the_codespace_stopped_with_gh_codespace_view(self):
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.ended(out))
        code, err = self.driver('stop', out, FAKE_GH_STOP_NOOP='1')
        self.assertEqual((code, self.codespaces()['fake-space-0001']), (1, 'Available'), err)
        self.assertIn('gh codespace stop -c fake-space-0001', err['next'])
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.codespaces()['fake-space-0001'], 'Shutdown')

    def test_a_start_whose_turn_never_began_is_refused_and_stops_the_codespace(self):
        for request in (REQUEST, CODEX):
            with self.subTest(harness=request['harness']):
                self.tearDown()
                self.setUp()
                code, err = self.driver('start', request, FAKE_GH_FAIL='ssh@2')
                self.assertEqual(code, 1, err)
                self.assertEqual((list(self.codespaces().values()), self.logged()), (['Shutdown'], []), err)

    def saved_run(self, out):
        with open(os.path.join(self.env['OPENWIZ_CODESPACES_STATE'], out['run'] + '.json')) as f:
            return json.load(f)

    def test_a_turn_inherits_the_environment_natively_and_reads_no_ambient_value(self):
        watcher = os.path.join(self.folder, 'watch.py')
        with open(watcher, 'w') as f:
            f.write(WATCH_READS)
        reads = os.path.join(self.folder, 'reads')
        program = (sys.executable, '-I', watcher)
        env = {WATCHED: 'synthetic-ambient-value-%s' % secrets.token_hex(4), 'WATCH_READS': reads}
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST, program, **env)
        self.assertEqual(code, 0, out)
        with open('/proc/%d/environ' % self.saved_run(out)['turns'][-1]['pid'], 'rb') as f:
            turn_env = f.read().decode().split('\0')
        self.assertIn('OPENWIZ_RUN=' + out['run'], turn_env)
        self.assertIn('%s=%s' % (WATCHED, env[WATCHED]), turn_env, 'the turn did not inherit the environment')
        os.remove(self.hold)
        self.assertTrue(self.ended(out))
        self.assertEqual(self.driver('wake', out, program, **env), (0, dict(out, woke=True)))
        self.assertTrue(self.ended(out))
        with open(reads, 'a+') as f:
            f.seek(0)
            self.assertEqual(f.read(), '', 'the driver read an ambient value at a turn launch')

    def test_a_reserved_secret_name_or_whitespace_in_a_field_is_refused_before_any_gh_call(self):
        cases = [('model', 'prefix ' + n) for n in RESERVED[:1]] + [('model', 'claude-' + n) for n in RESERVED] + [
            ('model', 'claude opus'), ('repository', 'example/' + RESERVED[4]), ('model', 'x-gh_token')]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                code, err = self.driver('start', dict(REQUEST, **{key: value}))
                self.assertEqual(code, 1, err)
                self.assertTrue(err['error'].startswith(key + ' '), err)
                self.assertNotIn(value, json.dumps(err))
                self.assertEqual(self.calls(), [], 'gh was called for a refused start')
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        name = os.path.join(self.env['OPENWIZ_CODESPACES_STATE'], out['run'] + '.json')
        for model in ('claude-' + RESERVED[1], 'claude opus'):
            with self.subTest(saved_model=model):
                state = self.saved_run(out)
                state['request']['model'] = model
                with open(name, 'w') as f:
                    json.dump(state, f)
                calls = len(self.calls())
                code, err = self.driver('wake', out)
                self.assertEqual(code, 1, err)
                self.assertTrue(err['error'].startswith('model '), err)
                self.assertEqual([c for c in self.calls()[calls:] if c[:2] == ['codespace', 'ssh']], [])
        self.assertEqual(len(self.logged()), 1)

    def test_a_start_whose_harness_refuses_after_the_marker_fails_and_stops_the_codespace(self):
        for case, env in (('the codespace gives no login', {'FAKE_GH_NO_SECRET_VALUES': '1'}),
                          ('the harness logs a refusal and runs on', {'FAKE_HARNESS_401': '1'})):
            for request in (REQUEST, CODEX):
                with self.subTest(case=case, harness=request['harness']):
                    self.tearDown()
                    self.setUp()
                    open(self.hold, 'w').close()
                    code, err = self.driver('start', request, **env)
                    self.assertEqual(code, 1, err)
                    self.assertIn('so the run did not start', err['error'])
                    self.assertEqual(list(self.codespaces().values()), ['Shutdown'], err)
                    self.assertTrue(self.until(lambda: not any(alive(p) for p, _, _ in self.logged())))
        self.tearDown()
        self.setUp()
        code, out = self.driver('start', CODEX, FAKE_HARNESS_401='in-a-tool-output')
        self.assertEqual(code, 0, out)

    def test_a_wake_whose_harness_refuses_to_resume_fails(self):
        for request in (REQUEST, CODEX):
            with self.subTest(harness=request['harness']):
                code, out = self.driver('start', request)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out))
                session = self.logged()[-1][1]
                os.remove(os.path.join(self.env['FAKE_GH_STATE'] + '.homes', max(self.codespaces()), '.fake-sessions',
                                       session))
                turns = len(self.saved_run(out)['turns'])
                code, err = self.driver('wake', out)
                self.assertEqual(code, 1, err)
                self.assertIn('so the run did not wake', err['error'])
                self.assertEqual(len(self.saved_run(out)['turns']), turns)
                self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_the_state_folder_and_every_file_in_it_are_owner_only(self):
        state = self.env['OPENWIZ_CODESPACES_STATE']
        os.mkdir(state, 0o755)
        os.chmod(state, 0o755)
        old = os.umask(0o022)
        try:
            open(self.hold, 'w').close()
            code, out = self.driver('start', REQUEST)
            self.assertEqual(code, 0, out)
            self.assertTrue(self.until(lambda: any(n.endswith('.sup') for n in os.listdir(state))))
            modes = {n: os.stat(os.path.join(state, n)).st_mode & 0o777 for n in os.listdir(state)}
            self.assertEqual(os.stat(state).st_mode & 0o777, 0o700)
            self.assertEqual(sorted({n.split('.', 1)[1].rsplit('.', 1)[-1] for n in modes}), ['json', 'lock', 'log', 'sup'])
            self.assertEqual({n: m for n, m in modes.items() if m != 0o600}, {})
        finally:
            os.umask(old)

if __name__ == '__main__':
    unittest.main()
