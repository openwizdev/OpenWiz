#!/usr/bin/env python3
import glob
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'kit.py')
TOKEN = 'gh' + 'p_' + 'Synthetic0Pane0Value' * 2 + '00'
REAL = ('claude', 'codex', 'cursor-agent', 'agent', 'opencode', 'pi', 'boat', 'gh', 'git', 'npm', 'node')
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}


class Pane(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.calls = os.path.join(self.folder, 'calls')
        self.env = dict(HOME=self.folder, KIT_TRACKER=self.tracker, GH_TOKEN=TOKEN,
                        FAKE_PANE_STATE=os.path.join(self.folder, 'pane.json'), FAKE_PANE_CALLS=self.calls,
                        OPENWIZ_PANE_STATE=os.path.join(self.folder, 'state'),
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + self.tools())
        reachable = [name for name in REAL if shutil.which(name, path=self.env['PATH'])]
        if reachable:
            raise RuntimeError('a real program is on the test PATH: ' + ', '.join(reachable))

    def tools(self):
        folder = os.path.join(self.folder, 'tools')
        os.mkdir(folder)
        for name, found in (('python3', sys.executable), ('sleep', shutil.which('sleep'))):
            os.symlink(found, os.path.join(folder, name))
        return folder

    def tearDown(self):
        for state in glob.glob(os.path.join(self.folder, 'pane*.json')):
            with open(state) as f:
                agents = [p['agent'] for p in json.load(f)['panels'].values() if p['agent']]
            for pid in agents:
                try:
                    with open('/proc/%d/cmdline' % pid, 'rb') as f:
                        if f.read().split(b'\0')[:2] == [b'sleep', b'300']:
                            os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    def driver(self, cmd, request, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, json.loads(p.stdout)

    def called(self):
        try:
            with open(self.calls) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def pane(self):
        with open(self.env['FAKE_PANE_STATE']) as f:
            return json.load(f)

    def test_no_real_harness_or_host_cli_is_on_the_path(self):
        found = {name: shutil.which(name, path=self.env['PATH']) for name in REAL}
        self.assertEqual({k: v for k, v in found.items() if v}, {})
        self.assertEqual(shutil.which('runpane', path=self.env['PATH']), os.path.join(HERE, 'fixtures', 'bin', 'runpane'))

    def test_the_environment_is_built_from_scratch(self):
        self.assertEqual(sorted(self.env), sorted(('KIT_TRACKER', 'GH_TOKEN', 'FAKE_PANE_STATE',
                                                   'FAKE_PANE_CALLS', 'OPENWIZ_PANE_STATE', 'PATH', 'HOME')))

    def test_errors_carry_fixed_reasons_never_pane_text(self):
        code, run = self.driver('start', REQUEST)
        answers = [self.driver('start', REQUEST, FAKE_PANE_DOWN='1'), self.driver('start', REQUEST, FAKE_PANE_READY='no'),
                   self.driver('stop', run, FAKE_PANE_DOWN='1')]
        for code, out in answers:
            self.assertEqual(code, 1, out)
            self.assertNotIn('synthetic', out['error'] + out['next'])
        self.assertNotIn('/synthetic/', json.dumps(answers))
        self.assertIn('open the Pane app', answers[0][1]['next'])
        self.assertIn('command-exited', answers[1][1]['error'])
        self.assertIn('runpane panels close failed', answers[2][1]['error'])

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

    def test_start_opens_one_agent_tab_with_the_model_and_no_permission_flag(self):
        code, out = self.driver('start', dict(REQUEST, harness='codex', model='gpt 5.5'),
                                FAKE_PANE_REPOS='other/site,example/site')
        self.assertEqual(code, 0, out)
        create = [c for c in self.called() if c[:2] == ['panes', 'create']]
        self.assertEqual(len(create), 1)
        args = {a: v for a, v in zip(create[0], create[0][1:]) if a.startswith('--') and not v.startswith('--')}
        self.assertEqual((args['--repo'], args['--agent'], args['--tool-command'], args['--source']),
                         ('2', 'codex', "codex --model 'gpt 5.5'", 'agent'))
        self.assertIn('example/site#7', args['--prompt'])
        self.assertIn('the build-ticket skill', args['--prompt'])
        self.assertNotIn('--force', create[0])

    def test_start_refuses_before_creating_anything(self):
        cases = (({}, dict(REQUEST, harness='gemini'), 'Pane runs no harness gemini'),
                 ({'FAKE_PANE_REPOS': 'example/other'}, REQUEST, 'runpane repos add'),
                 ({'FAKE_PANE_REPOS': 'other/site'}, REQUEST, 'runpane repos add'),
                 ({'FAKE_PANE_REPOS': 'example/site,example/site'}, REQUEST, 'saved more than once'),
                 ({'FAKE_PANE_DOWN': '1'}, REQUEST, 'open the Pane app'))
        for i, (env, request, words) in enumerate(cases):
            with self.subTest(env=env, harness=request['harness']):
                env = dict(env, FAKE_PANE_STATE=os.path.join(self.folder, 'pane-%d.json' % i))
                code, out = self.driver('start', request, **env)
                self.assertEqual(code, 1, out)
                self.assertIn(words, out['error'] + ' ' + out['next'])
                self.assertFalse([c for c in self.called() if c[:2] == ['panes', 'create']])

    def test_a_start_whose_agent_never_gets_ready_closes_its_tab_and_archives_its_pane(self):
        code, out = self.driver('start', REQUEST, FAKE_PANE_READY='no')
        self.assertEqual(code, 1, out)
        self.assertIn('command-exited', out['error'])
        state = self.pane()
        self.assertEqual(([p['closed'] for p in state['panels'].values()],
                          [p['archived'] for p in state['panes'].values()]), ([True], [True]))

    def test_stop_with_work_ends_the_agent_keeps_the_pane_and_answers_stopped(self):
        for dirty in ('unpushed', 'uncommitted'):
            with self.subTest(dirty=dirty):
                code, run = self.driver('start', REQUEST)
                self.assertEqual(code, 0, run)
                agent = self.pane()['panels']['panel-%d' % len(self.pane()['panels'])]['agent']
                self.assertEqual(self.driver('stop', run, FAKE_PANE_DIRTY=dirty), (0, dict(run, stopped=True)))
                self.assertFalse(self.alive(agent))
                self.assertEqual(self.pane()['panes']['pane-%d' % len(self.pane()['panes'])]['archived'], False)
                self.assertEqual(self.driver('stop', run, FAKE_PANE_DIRTY=dirty), (0, dict(run, stopped=True)))
                code, out = self.driver('wake', run)
                self.assertEqual(code, 1, out)
                self.assertIn('is stopped', out['error'])
        archives = [c for c in self.called() if c[:2] == ['panes', 'archive']]
        self.assertEqual((len(archives), [c for c in archives if '--force' in c]), (4, []))

    def test_a_later_stop_archives_the_pane_once_its_work_is_gone(self):
        code, run = self.driver('start', REQUEST)
        self.assertEqual(self.driver('stop', run, FAKE_PANE_DIRTY='unpushed'), (0, dict(run, stopped=True)))
        self.assertEqual(self.driver('stop', run), (0, dict(run, stopped=True)))
        self.assertEqual([p['archived'] for p in self.pane()['panes'].values()], [True])
        before = len(self.called())
        self.assertEqual(self.driver('stop', run), (0, dict(run, stopped=True)))
        self.assertEqual(len(self.called()), before)

    def alive(self, pid):
        try:
            with open('/proc/%d/stat' % pid) as f:
                return f.read().rpartition(')')[2].split()[0] != 'Z'
        except OSError:
            return False

    def test_start_refuses_a_credential_in_any_field(self):
        shapes = (TOKEN, 'sk-' + 'Synthetic0Value0' * 2, 'AKIA' + 'SYNTHETIC0VALUE0', 'xoxb-' + 'synthetic-0value',
                  'github_pat_' + 'Synthetic0Value0' * 2, 'bearer ' + 'synthetic', 'token: ' + 'synthetic')
        for value in shapes:
            with self.subTest(shape=value[:4]):
                code, out = self.driver('start', dict(REQUEST, model=value))
                self.assertEqual(code, 1, out)
                self.assertNotIn(value, json.dumps(out))
                self.assertEqual([c for c in self.called() if value in json.dumps(c)], [])
        self.assertFalse([c for c in self.called() if c[:2] == ['panes', 'create']])


if __name__ == '__main__':
    unittest.main(verbosity=2)
