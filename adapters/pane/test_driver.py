#!/usr/bin/env python3
"""The Pane driver on a synthetic `runpane` CLI (fixtures/bin/runpane) and a local tracker.

Run: python3 -I adapters/pane/test_driver.py   (Linux: the kit watches /proc)
"""
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'kit.py')
# A synthetic value in a GitHub token's shape, built here so no file holds one.
TOKEN = 'gh' + 'p_' + 'Synthetic0Pane0Value' * 2 + '00'
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}


class Pane(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.calls = os.path.join(self.folder, 'calls')
        self.env = dict(os.environ, KIT_TRACKER=self.tracker, KIT_TEST=self.mark, GH_TOKEN=TOKEN,
                        FAKE_PANE_STATE=os.path.join(self.folder, 'pane.json'), FAKE_PANE_CALLS=self.calls,
                        OPENWIZ_PANE_STATE=os.path.join(self.folder, 'state'),
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + os.environ.get('PATH', ''))

    def tearDown(self):
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass

    def driver(self, cmd, request, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, json.loads(p.stdout)

    def called(self):
        """Every runpane call so far, as argument lists."""
        try:
            with open(self.calls) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def pane(self):
        with open(self.env['FAKE_PANE_STATE']) as f:
            return json.load(f)

    def test_kit_passes_all_five(self):
        # catches: a wake that opens a second tab (a second note), a stop that never closes the agent's tab (its
        # agent still runs), a token passed on to a `runpane` process, a start that takes a token field.
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
        # catches: a model with a space split into two words of the tool command, a permission-skipping flag the
        # owner never chose, a tab not marked as agent-opened (Pane then refuses to close it), and a saved
        # repository picked by a name Pane could read as another selector instead of by its id.
        code, out = self.driver('start', dict(REQUEST, harness='codex', model='gpt 5.5'),
                                FAKE_PANE_REPOS='active,site')
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
        # catches: a start that creates a Pane for a harness Pane can't run, in a repository Pane hasn't saved or
        # saved twice, or whose failure hides Pane's own next step (open the app).
        cases = (({}, dict(REQUEST, harness='gemini'), 'Pane runs no harness gemini'),
                 ({'FAKE_PANE_REPOS': 'other'}, REQUEST, 'runpane repos add'),
                 ({'FAKE_PANE_REPOS': 'site,site'}, REQUEST, 'saved more than once'),
                 ({'FAKE_PANE_DOWN': '1'}, REQUEST, 'open the Pane app'))
        for i, (env, request, words) in enumerate(cases):
            with self.subTest(env=env, harness=request['harness']):
                env = dict(env, FAKE_PANE_STATE=os.path.join(self.folder, 'pane-%d.json' % i))
                code, out = self.driver('start', request, **env)
                self.assertEqual(code, 1, out)
                self.assertIn(words, out['error'] + ' ' + out['next'])
                self.assertFalse([c for c in self.called() if c[:2] == ['panes', 'create']])

    def test_a_start_whose_agent_never_gets_ready_closes_its_tab_and_archives_its_pane(self):
        # catches: a start that refuses but leaves its new Pane and worktree behind.
        code, out = self.driver('start', REQUEST, FAKE_PANE_READY='no')
        self.assertEqual(code, 1, out)
        self.assertIn('command-exited', out['error'])
        state = self.pane()
        self.assertEqual(([p['closed'] for p in state['panels'].values()],
                          [p['archived'] for p in state['panes'].values()]), ([True], [True]))

    def test_stop_keeps_uncommitted_work_and_says_where(self):
        # catches: a stop that forces the archive and deletes the agent's uncommitted files, and a stop that
        # forgets the run is stopped when Pane keeps its worktree (a later wake would reach a closed tab).
        code, run = self.driver('start', REQUEST)
        self.assertEqual(code, 0, run)
        code, out = self.driver('stop', run, FAKE_PANE_DIRTY='uncommitted')
        self.assertEqual(code, 1, out)
        self.assertIn('/synthetic/worktrees/openwiz-' + run['run'], out['error'])
        self.assertEqual([p['archived'] for p in self.pane()['panes'].values()], [False])
        self.assertTrue(all(p['closed'] for p in self.pane()['panels'].values()))
        self.assertEqual(self.driver('wake', run)[0], 1)
        # Once the work is dealt with, the same stop archives the Pane.
        self.assertEqual(self.driver('stop', run), (0, dict(run, stopped=True)))
        self.assertEqual([p['archived'] for p in self.pane()['panes'].values()], [True])

    def test_stop_archives_unpushed_commits_and_answers_again(self):
        # catches: a stop that fails forever on commits Pane keeps on the local branch anyway, and a second stop
        # that calls Pane again (it would refuse: that Pane is archived).
        code, run = self.driver('start', REQUEST)
        self.assertEqual(self.driver('stop', run, FAKE_PANE_DIRTY='unpushed'), (0, dict(run, stopped=True)))
        archives = [c for c in self.called() if c[:2] == ['panes', 'archive']]
        self.assertEqual([('--force' in c) for c in archives], [False, True])
        before = len(self.called())
        self.assertEqual(self.driver('stop', run), (0, dict(run, stopped=True)))
        code, out = self.driver('wake', run)
        self.assertEqual((code, len(self.called())), (1, before), out)
        self.assertIn('is stopped', out['error'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
