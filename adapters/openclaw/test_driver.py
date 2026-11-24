#!/usr/bin/env python3
import ctypes
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
TOKEN = 'gh' + 'p_' + 'Synthetic0Claw0Value' * 2 + '00'
REAL = ('claude', 'codex', 'acpx', 'openclaw', 'gh', 'npx', 'node', 'bash', 'sh')
DIAGNOSTIC = 'synthetic acpx diagnostic'
CLAUDE = ['npx', '-y', '--package=@agentclientprotocol/claude-agent-acp@^0.95.0', '--', 'claude-agent-acp']
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}
BREAKS_AFTER_SPAWN = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('claw', importlib.machinery.SourceFileLoader('claw', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
launch = t.launch
def broken(req, run, woken):
    turn = launch(req, run, woken)
    os.mkdir(os.path.join(t.STATE, run + '.json.new'))
    return turn
t.launch = broken
t.main()
'''


ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


def owned():
    children = {}
    for p in filter(str.isdigit, os.listdir('/proc')):
        try:
            with open('/proc/%s/stat' % p) as f:
                fields = f.read().rpartition(')')[2].split()
        except OSError:
            continue
        if fields[0] != 'Z':
            children.setdefault(int(fields[1]), []).append(int(p))
    found, todo = set(), [os.getpid()]
    while todo:
        for c in children.get(todo.pop(), []):
            if c not in found:
                found.add(c)
                todo.append(c)
    return sorted(found)


class OpenClaw(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.calls, self.state = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'state')
        self.home = os.path.join(self.folder, "a user's home")
        os.mkdir(self.home)
        self.env = dict(HOME=self.home, LANG='C.UTF-8', KIT_TRACKER=self.tracker, GH_TOKEN=TOKEN,
                        FAKE_TURNS=self.turns, FAKE_HOLD=self.hold, FAKE_ACPX_CALLS=self.calls,
                        FAKE_ACPX_STATE=os.path.join(self.folder, 'acpx.json'), OPENWIZ_OPENCLAW_STATE=self.state,
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + self.bare())
        real = [shutil.which(t, path=self.env['PATH']) for t in REAL]
        self.assertEqual([r for r in real if r and not r.startswith(os.path.join(HERE, 'fixtures'))], [],
                         'a real harness or host tool is on the test PATH')

    def bare(self):
        bare = os.path.join(self.folder, 'bare')
        os.mkdir(bare)
        for tool in ('python3', 'sleep'):
            os.symlink(shutil.which(tool), os.path.join(bare, tool))
        return bare

    def tearDown(self):
        for pid in owned():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        while True:
            try:
                if os.waitpid(-1, os.WNOHANG) == (0, 0):
                    break
            except ChildProcessError:
                break
        shutil.rmtree(self.folder, ignore_errors=True)

    def logged(self):
        try:
            with open(self.turns) as f:
                return [(int(a), b) for a, b in (line.split() for line in f)]
        except FileNotFoundError:
            return []

    def seen(self):
        try:
            with open(self.calls) as f:
                calls = [json.loads(line) for line in f]
        except FileNotFoundError:
            return []
        return calls

    def adapter(self):
        return ['env', 'HOME=' + self.home] + CLAUDE

    def acpx(self):
        return [c['args'] for c in self.seen()]

    def kept(self, text):
        found = []
        for root, _, files in os.walk(self.state):
            for name in files:
                if os.path.islink(os.path.join(root, name)):
                    continue
                with open(os.path.join(root, name), 'rb') as f:
                    if text.encode() in f.read():
                        found.append(name)
        return found

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def driver(self, cmd, request, program=DRIVER, **env):
        p = subprocess.run([program, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, json.loads(p.stdout)

    def test_kit_passes_all_five(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site',
                            '--ticket', '7', '--harness', 'claude', '--model', 'claude-opus-5-5',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=self.env, capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver']), p.stderr)

    def test_acpx_runs_with_a_permission_policy_and_a_short_queue_owner(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertTrue(self.until(lambda: len(self.logged()) == 2))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        calls, run = self.acpx(), out['run']
        split = [(dict(zip(c[:n][::2], c[:n][1::2])), c[n:])
                 for c in calls for n in [next(i for i in range(0, len(c), 2) if not c[i].startswith('--'))]]
        self.assertEqual([v[:4] for _, v in split], [['sessions', 'new', '--name', run],
                                                     ['prompt', '-s', run, '--no-wait'],
                                                     ['prompt', '-s', run, '--no-wait'], ['cancel', '-s', run],
                                                     ['sessions', 'close', run]])
        self.assertEqual([c['ran'] for c in self.seen()], [self.adapter()] * 5)
        for c, (g, _) in zip(calls, split):
            self.assertNotIn('--approve-all', c)
            self.assertFalse(any('gateway' in a for a in c), c)
            self.assertEqual(g['--cwd'], split[0][0]['--cwd'])
            if c in calls[:3]:
                self.assertEqual((g['--auth-policy'], g['--non-interactive-permissions']), ('fail', 'deny'))
                policy = json.loads(g['--permission-policy'])
                self.assertEqual(policy['defaultAction'], 'deny')
                self.assertNotIn('*', policy['autoApprove'])
                self.assertIn('delete', policy['autoDeny'])
        self.assertEqual(split[0][0]['--model'], 'claude-opus-5-5')
        for g, _ in split[1:3]:
            self.assertTrue(0 < int(g['--ttl']) <= 300, g)

    def test_a_harness_acpx_would_run_as_a_command_is_refused_without_echoing_it(self):
        for harness in ('sh', 'zz-unknown-agent', 'openclaw', 'gemini'):
            with self.subTest(harness=harness):
                code, out = self.driver('start', dict(REQUEST, harness=harness))
                self.assertEqual(code, 1, out)
                self.assertIn('claude, codex', out['next'])
                self.assertNotIn(harness, out['error'])
        self.assertEqual(self.acpx(), [])

    def test_a_field_shaped_like_a_credential_is_refused_before_anything_keeps_it(self):
        for model in (TOKEN, 'Bear' + 'er Synthetic0Value', 'sk-' + 'Synthetic0Claw0Value00'):
            with self.subTest(model=model[:6]):
                code, out = self.driver('start', dict(REQUEST, model=model))
                self.assertEqual(code, 1, out)
                self.assertNotIn(model, json.dumps(out))
                self.assertEqual(self.kept(model), [])
        self.assertEqual(self.acpx(), [])

    def test_a_refused_prompt_fails_start_and_wake(self):
        code, out = self.driver('start', REQUEST, FAKE_ACPX_FAIL='prompt')
        self.assertEqual(code, 1, out)
        self.assertEqual((self.logged(), owned()), ([], []))
        run = re.search(r'run-[0-9a-f]{12}', out['error']).group()
        self.assertEqual(self.driver('wake', {'run': run})[0], 1)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        code, err = self.driver('wake', out, FAKE_ACPX_FAIL='prompt')
        self.assertEqual(code, 1, err)
        self.assertNotIn('woke', err)

    def test_a_wake_during_a_turn_reaches_the_same_session_after_acpx_acknowledged_the_first(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        time.sleep(0.5)
        self.assertEqual(len(self.logged()), 1, 'a wake started a second turn beside the running one')
        os.remove(self.hold)
        self.assertTrue(self.until(lambda: len(self.logged()) == 2))
        [(first, a), (second, b)] = self.logged()
        self.assertEqual((first, a, b), (second, 'first', 'woken'), 'the follow-up ran in another session')
        with open(self.tracker) as f:
            self.assertEqual(len(json.load(f)['comments']), 1)

    def test_acpx_output_is_never_kept(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        self.assertEqual(self.driver('wake', out)[0], 0)
        self.assertEqual(self.driver('stop', out)[0], 0)
        code, err = self.driver('start', REQUEST, FAKE_ACPX_FAIL='new')
        self.assertEqual(code, 1, err)
        self.assertNotIn(DIAGNOSTIC, json.dumps(err))
        self.assertIn('signed in', err['next'])
        self.assertEqual(self.kept(DIAGNOSTIC), [])

    def test_stop_runs_the_built_in_adapter_even_when_a_config_appears_while_it_runs(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual(self.driver('stop', out, FAKE_REMAP_ON_CANCEL='1'), (0, dict(out, stopped=True)))
        self.assertTrue(os.path.exists(os.path.join(self.state, 'work', out['run'], '.acpxrc.json')))
        seen = self.seen()
        self.assertEqual([c['auth'] for c in seen], [[]] * len(seen), 'acpx loaded the project config')
        self.assertEqual([c['ran'] for c in seen], [self.adapter()] * 4)
        self.assertEqual(owned(), [])

    def test_a_project_acpx_config_in_the_run_folder_never_reaches_acpx(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        calls = len(self.seen())
        project = os.path.join(self.state, 'work', out['run'], '.acpxrc.json')
        for planted in ('file', 'link'):
            with self.subTest(planted=planted):
                if planted == 'file':
                    with open(project, 'w') as f:
                        json.dump({'auth': {'synthetic-project-method': 'synthetic-not-a-login'}}, f)
                else:
                    os.remove(project)
                    os.symlink(os.path.join(self.folder, 'missing.json'), project)
                code, err = self.driver('wake', out)
                self.assertEqual(code, 1, err)
                self.assertIn('.acpxrc.json', err['error'])
                self.assertNotIn('synthetic', json.dumps(err))
                self.assertEqual(len(self.seen()), calls, 'acpx ran with a project config in the run folder')
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(len(self.seen()), calls, 'stop ran acpx with a project config in the run folder')
        self.assertEqual((owned(), self.kept('synthetic-not-a-login')), ([], []))

    def test_the_driver_never_reads_your_acpx_config_and_acpx_never_loads_it(self):
        os.mkdir(os.path.join(self.home, '.acpx'))
        config = os.path.join(self.home, '.acpx', 'config.json')
        with open(config, 'w') as f:
            json.dump({'agents': {'gemini': {'argv': ['synthetic-agent']}},
                       'auth': {'synthetic-method': 'synthetic-not-a-login'}}, f)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual([c['auth'] for c in self.seen()], [[]] * 5, 'acpx loaded the auth in your acpx config')
        os.remove(config)
        os.mkdir(config)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, 'the driver opened ~/.acpx/config.json: %s' % out)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        seen = self.seen()
        self.assertEqual(len(seen), 9)
        for c in seen:
            self.assertEqual((c['ran'], c['auth']), (self.adapter(), []))
            self.assertTrue(c['home'].startswith(self.state + os.sep), c['home'])
            self.assertFalse(os.path.exists(os.path.join(c['home'], '.acpx', 'config.json')))

    def test_a_start_whose_session_fails_leaves_nothing(self):
        code, out = self.driver('start', REQUEST, FAKE_ACPX_FAIL='new')
        self.assertEqual(code, 1, out)
        self.assertEqual((self.logged(), owned()), ([], []))
        run = re.search(r'run-[0-9a-f]{12}', out['error']).group()
        self.assertEqual(self.driver('wake', {'run': run})[0], 1)
        self.assertEqual(self.logged(), [])

    def test_a_missing_acpx_is_refused_with_how_to_install_it(self):
        code, out = self.driver('start', REQUEST, PATH=os.path.join(self.folder, 'bare'))
        self.assertEqual(code, 1, out)
        self.assertIn('npm install -g acpx', out['next'])

    def test_stop_ends_a_queue_owner_with_a_clean_environment(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST, FAKE_CLEAN='1')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        [(owner, _)] = self.logged()
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual((alive(owner), owned()), (False, []))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)), 'stopping again answers again')

    def test_save_failure_after_the_prompt_reports_unknown(self):
        path = os.path.join(self.folder, 'breaks')
        with open(path, 'w') as f:
            f.write('#!%s\n' % sys.executable + BREAKS_AFTER_SPAWN % DRIVER)
        os.chmod(path, 0o700)
        code, out = self.driver('start', REQUEST, program=path)
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertNotIn('retry', json.dumps(out))
        self.assertTrue(self.until(lambda: not owned()), 'the turn it could not save still runs')


    def test_a_provider_qualified_model_reaches_acpx(self):
        code, out = self.driver('start', dict(REQUEST, model='openrouter/anthropic/claude-sonnet-4.6'))
        self.assertEqual(code, 0, out)
        first = self.acpx()[0]
        self.assertEqual(first[first.index('--model') + 1], 'openrouter/anthropic/claude-sonnet-4.6')


if __name__ == '__main__':
    unittest.main(verbosity=2)
