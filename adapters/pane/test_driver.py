#!/usr/bin/env python3
import glob
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'kit.py')
TOKEN = 'gh' + 'p_' + 'Synthetic0Pane0Value' * 2 + '00'
REAL = ('claude', 'codex', 'cursor-agent', 'agent', 'opencode', 'pi', 'boat', 'gh', 'npm', 'node')
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
        self.git_seen = os.path.join(self.folder, 'git-seen')
        with open(os.path.join(folder, 'git'), 'w') as f:
            f.write('#!%s -I\nimport json, os, sys\nwith open(%r, "a") as f:\n    f.write(json.dumps(sorted(os.environ)) + "\\n")\n'
                    'os.execv(%r, [%r] + sys.argv[1:])\n' % (sys.executable, self.git_seen, shutil.which('git'), 'git'))
        os.chmod(os.path.join(folder, 'git'), 0o700)
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
            'pass start: the run posted builder status note 1; effort: medium reached a process the run started',
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
                 ({'FAKE_PANE_GIT': 'include'}, REQUEST, 'runpane repos add'),
                 ({'FAKE_PANE_GIT': 'insteadof'}, REQUEST, 'runpane repos add'),
                 ({'FAKE_PANE_GIT': 'pushurl'}, REQUEST, 'runpane repos add'),
                 ({'FAKE_PANE_DOWN': '1'}, REQUEST, 'open the Pane app'))
        for i, (env, request, words) in enumerate(cases):
            with self.subTest(case=i, env=env, harness=request['harness']):
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

    def test_start_refuses_each_credential_the_kit_recognises_inside_a_field(self):
        spec = importlib.util.spec_from_loader('kit', importlib.machinery.SourceFileLoader('kit', KIT))
        kit = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kit)
        known = (('model', 'x' + 'sk-' + 'Synthetic0Value0Synth'), ('model', 'x' + 'AKIA' + 'SYNTHETIC0VALUE0'),
                 ('model', 'x' + 'xoxb-' + 'synthetic0value'), ('model', 'claude password: ' + 'synthetic'),
                 ('repository', 'example/x' + 'ghp_' + 'Synthetic0Value0Synth0'))
        google = ('model', 'AIza' + 'Synthetic0Value0' * 2 + 'Syn')
        for field, value in known + (google,):
            with self.subTest(field=field, shape=value[:5]):
                self.assertTrue((field, value) == google or kit.SHAPES.search(value), value[:5])
                code, out = self.driver('start', dict(REQUEST, **{field: value}))
                self.assertEqual(code, 1, out)
                self.assertIn('looks like a login', out['error'])
                self.assertNotIn(value, json.dumps(out))
                self.assertEqual([c for c in self.called() if value in json.dumps(c)], [])
        self.assertFalse([c for c in self.called() if c[:2] == ['panes', 'create']])

    def test_a_provider_qualified_model_is_accepted_up_to_100_characters(self):
        qualified = 'openrouter/anthropic/claude-sonnet-4.6'
        wide = 'openrouter/' + 'a' * (100 - len('openrouter/'))
        self.assertEqual(len(wide), 100)
        for i, model in enumerate((qualified, wide)):
            with self.subTest(model=model[:24]):
                code, out = self.driver('start', dict(REQUEST, model=model),
                                        FAKE_PANE_STATE=os.path.join(self.folder, 'pane-model-%d.json' % i))
                self.assertEqual(code, 0, out)
        commands = [c for c in self.called() if c[:2] == ['panes', 'create']]
        self.assertEqual([c[c.index('--tool-command') + 1] for c in commands],
                         ['claude --model ' + qualified, 'claude --model ' + wide])
        code, out = self.driver('start', dict(REQUEST, model=wide + 'b'))
        self.assertEqual(code, 1, out)
        self.assertIn('model is not valid', out['error'])
        self.assertEqual(len([c for c in self.called() if c[:2] == ['panes', 'create']]), 2)

    def test_effort_is_declared_and_schema_matches_the_kit(self):
        lines = (Path(HERE) / 'README.md').read_text().splitlines()
        login = next(i for i, line in enumerate(lines) if line.startswith('Login:'))
        self.assertEqual(lines[login + 1], 'Effort: passed as harness options via `runpane panes create --tool-command`.')
        self.assertEqual([line for line in lines if line.startswith('Effort:')], [lines[login + 1]])
        code, out = self.driver('version', None)
        self.assertEqual((code, out['can'].count('effort')), (0, 1))
        self.assertEqual((Path(HERE) / 'schema.json').read_bytes(), Path(KIT).with_name('schema.json').read_bytes())

    def test_effort_reaches_the_pane_agent_command_and_is_recorded(self):
        cases = (('claude', 'medium', 'claude --model synthetic-model --effort medium', {}),
                 ('codex', 'xhigh', 'codex --model synthetic-model -c model_reasoning_effort=xhigh',
                  {'FAKE_PANE_QUEUE': '1'}))
        for i, (harness, effort, command, env) in enumerate(cases, 1):
            with self.subTest(harness=harness):
                code, run = self.driver('start', dict(REQUEST, harness=harness, model='synthetic-model', effort=effort),
                                        **env)
                self.assertEqual(code, 0, run)
                create = [c for c in self.called() if c[:2] == ['panes', 'create']]
                self.assertEqual(len(create), i)
                self.assertEqual(create[-1][create[-1].index('--tool-command') + 1], command)
                self.assertEqual(self.pane()['panels']['panel-%d' % i]['effort'], effort)
                self.assertEqual(self.driver('stop', run), (0, dict(run, stopped=True)))

    def test_unsupported_effort_refuses_without_calling_pane_or_saving_a_run(self):
        next_step = ("this host can't set effort: remove the effort for this harness in your Models table or Roster "
                     "to run it at the host's default")
        for harness, effort in (('claude', 'minimal'), ('codex', 'turbo'), ('cursor', 'medium'),
                                ('opencode', 'medium'), ('pi', 'medium'), ('gemini', 'medium')):
            with self.subTest(harness=harness, effort=effort):
                code, out = self.driver('start', dict(REQUEST, harness=harness, effort=effort))
                self.assertEqual((code, set(out), out['next']), (1, {'error', 'next'}, next_step))
                self.assertIn(harness, out['error'])
                self.assertIn(effort, out['error'])
        self.assertEqual(self.called(), [])
        self.assertFalse(os.path.exists(self.env['OPENWIZ_PANE_STATE']))

    def test_malformed_or_credential_shaped_effort_is_not_echoed_or_sent(self):
        for effort in ('MEDIUM', 'a' * 21, None, 'xoxb-synthetic'):
            with self.subTest(effort=effort):
                code, out = self.driver('start', dict(REQUEST, effort=effort))
                self.assertEqual((code, set(out)), (1, {'error', 'next'}))
                self.assertIn('effort ', out['error'])
                if isinstance(effort, str):
                    self.assertNotIn(effort, json.dumps(out))
        self.assertEqual(self.called(), [])
        self.assertFalse(os.path.exists(self.env['OPENWIZ_PANE_STATE']))

    def runs(self):
        return sorted(name[:-5] for name in os.listdir(self.env['OPENWIZ_PANE_STATE']) if name.endswith('.json'))

    def saved_run(self, run):
        with open(os.path.join(self.env['OPENWIZ_PANE_STATE'], run + '.json')) as f:
            return json.load(f)

    def test_a_create_that_times_out_stays_recoverable_until_stop_closes_the_agent(self):
        code, out = self.driver('start', REQUEST, FAKE_PANE_HANG='create', OPENWIZ_PANE_RUNPANE_SECONDS='1')
        self.assertEqual(code, 1, out)
        self.assertNotIn('stopped', out)
        [run] = self.runs()
        self.assertIn(run, out['next'])
        state = self.saved_run(run)
        self.assertEqual((state['stopped'], state['pane'], state['panel']), (False, None, None))
        agent = self.pane()['panels']['panel-1']['agent']
        self.assertTrue(self.alive(agent))
        code, refused = self.driver('stop', {'run': run}, FAKE_PANE_HANG='list', OPENWIZ_PANE_RUNPANE_SECONDS='1')
        self.assertEqual(code, 1, refused)
        self.assertNotIn('stopped', refused)
        self.assertTrue(self.alive(agent))
        self.assertFalse(self.saved_run(run)['stopped'])
        self.assertEqual(self.driver('stop', {'run': run}, OPENWIZ_PANE_RUNPANE_SECONDS='1'),
                         (0, {'run': run, 'stopped': True}))
        self.assertFalse(self.alive(agent))
        self.assertEqual(self.pane()['panes']['pane-1']['archived'], True)
        self.assertFalse([c for c in self.called() if '--force' in c and c[:2] == ['panes', 'archive']])

    def test_a_create_that_times_out_before_a_pane_exists_answers_stopped_only_once_none_is_there(self):
        code, out = self.driver('start', REQUEST, FAKE_PANE_HANG='before-create', OPENWIZ_PANE_RUNPANE_SECONDS='1')
        self.assertEqual(code, 1, out)
        self.assertNotIn('stopped', out)
        [run] = self.runs()
        self.assertFalse(self.saved_run(run)['stopped'])
        self.assertEqual(self.pane()['panes'], {})
        self.assertEqual(self.driver('stop', {'run': run}, OPENWIZ_PANE_RUNPANE_SECONDS='1'),
                         (0, {'run': run, 'stopped': True}))
        self.assertFalse([c for c in self.called() if c[:2] in (['panels', 'close'], ['panes', 'archive'])])

    def test_origin_matches_github_hostname_case_insensitively(self):
        for i, host in enumerate(('GitHub.com', 'GITHUB.COM')):
            with self.subTest(host=host):
                code, out = self.driver('start', REQUEST, FAKE_PANE_HOST=host,
                                        FAKE_PANE_STATE=os.path.join(self.folder, 'pane-host-%d.json' % i))
                self.assertEqual(code, 0, out)
        self.assertEqual(len([c for c in self.called() if c[:2] == ['panes', 'create']]), 2)

    def test_a_queued_create_tracks_its_pane_until_ready_and_can_wake_and_stop(self):
        code, out = self.driver('start', REQUEST, FAKE_PANE_QUEUE='2')
        self.assertEqual(code, 0, out)
        run = out['run']
        state = self.saved_run(run)
        self.assertEqual((state['pane'], state['panel'], state['starting'], state['stopped']),
                         ('pane-1', 'panel-1', False, False))
        agent = self.pane()['panels']['panel-1']['agent']
        self.assertTrue(self.alive(agent))
        self.assertTrue([c for c in self.called() if c[:2] == ['panels', 'list']])
        self.assertTrue([c for c in self.called() if c[:2] == ['panels', 'wait']])
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertFalse(self.alive(agent))
        self.assertEqual(self.pane()['panes']['pane-1']['archived'], True)

    def test_a_queued_create_that_never_gets_ready_cleans_up_before_refusing(self):
        code, out = self.driver('start', REQUEST, FAKE_PANE_QUEUE='1', FAKE_PANE_READY='no',
                                FAKE_PANE_STATE=os.path.join(self.folder, 'pane-q-notready.json'))
        self.assertEqual(code, 1, out)
        self.assertIn('command-exited', out['error'])
        self.assertNotIn('synthetic', out['error'] + out['next'])
        [run] = self.runs()
        state = self.saved_run(run)
        self.assertEqual((state['pane'], state['panel'], state['closed'], state['archived'], state['stopped']),
                         ('pane-1', 'panel-1', True, True, True))
        with open(os.path.join(self.folder, 'pane-q-notready.json')) as f:
            pstate = json.load(f)
        self.assertEqual((pstate['panels']['panel-1']['closed'], pstate['panes']['pane-1']['archived']), (True, True))
        code, out = self.driver('start', REQUEST, FAKE_PANE_QUEUE='never', OPENWIZ_PANE_RUNPANE_SECONDS='1',
                                FAKE_PANE_STATE=os.path.join(self.folder, 'pane-q-timeout.json'))
        self.assertEqual(code, 1, out)
        self.assertNotIn('synthetic', out['error'] + out['next'])
        run2 = [r for r in self.runs() if r != run][0]
        state2 = self.saved_run(run2)
        self.assertEqual((state2['pane'], state2['panel'], state2['archived'], state2['stopped']),
                         ('pane-1', None, True, True))
        with open(os.path.join(self.folder, 'pane-q-timeout.json')) as f:
            pstate2 = json.load(f)
        self.assertEqual(pstate2['panes']['pane-1']['archived'], True)

    def test_a_queued_create_whose_cleanup_cannot_be_confirmed_stays_recoverable_for_stop(self):
        code, out = self.driver('start', REQUEST, FAKE_PANE_QUEUE='never', FAKE_PANE_QUEUE_LOCK='1',
                                OPENWIZ_PANE_RUNPANE_SECONDS='1')
        self.assertEqual(code, 1, out)
        self.assertNotIn('synthetic', out['error'] + out['next'])
        [run] = self.runs()
        self.assertIn(run, out['next'])
        state = self.saved_run(run)
        self.assertEqual((state['pane'], state['panel'], state['starting'], state['stopped'], state['archived']),
                         ('pane-1', None, True, False, False))
        code, woke = self.driver('wake', {'run': run})
        self.assertEqual(code, 1, woke)
        self.assertIn('never finished starting', woke['error'])
        code, refused = self.driver('stop', {'run': run}, FAKE_PANE_QUEUE_LOCK='1')
        self.assertEqual(code, 1, refused)
        self.assertFalse(self.saved_run(run)['stopped'])
        self.assertEqual(self.driver('stop', {'run': run}, FAKE_PANE_QUEUE_FINISH='1'),
                         (0, {'run': run, 'stopped': True}))
        agent = self.pane()['panels']['panel-1']['agent']
        self.assertFalse(self.alive(agent))
        self.assertEqual((self.pane()['panels']['panel-1']['closed'], self.pane()['panes']['pane-1']['archived']),
                         (True, True))

    def test_git_sees_only_non_secret_settings(self):
        planted = dict(GITHUB_TOKEN='synthetic-github-value', EXAMPLE_API_KEY='synthetic-api-value', LANG='C.UTF-8',
                       XDG_CONFIG_HOME=os.path.join(self.folder, 'xdg'), GIT_DIR=os.path.join(self.folder, 'elsewhere'))
        code, out = self.driver('start', REQUEST, **planted)
        self.assertEqual(code, 0, out)
        with open(self.git_seen) as f:
            seen = [json.loads(line) for line in f]
        self.assertEqual(len(seen), 2)
        for names in seen:
            self.assertEqual(names, ['HOME', 'LANG', 'PATH', 'XDG_CONFIG_HOME'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
