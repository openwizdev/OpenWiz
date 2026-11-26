#!/usr/bin/env python3
import ctypes
import importlib.util
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
GATEWAY = os.path.join(HERE, 'fixtures', 'gateway.py')
GH_TOKEN = 'gh' + 'p_' + 'Synthetic0Sprites0Value' * 2 + '00'
ANTHROPIC_KEY = 'sk-' + 'ant-' + 'synthetic0sprites0key0' * 2
CONNECTIONS = {'OPENWIZ_SPRITES_ANTHROPIC': 'conn_anth0synthetic01', 'OPENWIZ_SPRITES_OPENAI': 'conn_oai0synthetic02',
               'OPENWIZ_SPRITES_GITHUB': 'conn_gh0synthetic03'}
GATEWAYS = {'ANTHROPIC_BASE_URL': 'https://api.sprites.dev/v1/gateway/anthropic/conn_anth0synthetic01',
            'OPENAI_BASE_URL': 'https://api.sprites.dev/v1/gateway/openai/conn_oai0synthetic02/v1',
            'OPENWIZ_GITHUB_API': 'https://api.sprites.dev/v1/gateway/github/conn_gh0synthetic03'}
ORG, OTHER_ORG = 'example-org', 'example-other-org'
REFUSE_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to "
                 "run it at the host's default")
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
HEARD = r'''
import runpy, sys
heard = open(sys.argv.pop(1), 'a')
sys.addaudithook(lambda event, args: event in ('open', 'import') and heard.write('%%s\n' %% (args[0],)))
sys.argv = [%r] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
''' % DRIVER
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


def kit_module():
    spec = importlib.util.spec_from_file_location('kit', KIT)
    kit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kit)
    return kit


class Sprites(unittest.TestCase):
    maxDiff = None
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        tools = os.path.join(self.folder, 'tools')
        os.mkdir(tools)
        for name in ('python3', 'sh', 'sleep', 'mktemp', 'rm', 'readlink', 'ln', 'mkdir', 'dirname', 'lsof', 'cat',
                     'chmod'):
            os.symlink(shutil.which(name), os.path.join(tools, name))
        self.hold, self.marker = os.path.join(self.folder, 'hold'), 'marker' + secrets.token_hex(8)
        self.env = dict(CONNECTIONS, OPENWIZ_SPRITES_ORG=ORG, HOME=self.folder, KIT_TRACKER=self.tracker, GH_TOKEN=GH_TOKEN,
                        ANTHROPIC_API_KEY=ANTHROPIC_KEY, FAKE_MARKER=self.marker,
                        FAKE_TURNS=os.path.join(self.folder, 'turns'), FAKE_HOLD=self.hold,
                        FAKE_ENVS=os.path.join(self.folder, 'envs'),
                        FAKE_SPRITE_STATE=os.path.join(self.folder, 'sprites.json'),
                        FAKE_SPRITE_CALLS=os.path.join(self.folder, 'sprite-calls'),
                        OPENWIZ_SPRITES_STATE=os.path.join(self.folder, 'state'), OPENWIZ_SPRITES_SETTLE='2',
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
        self.assertNotIn(self.marker, p.stdout + p.stderr, "sprite's own text reached the driver's answer")
        self.assertNotIn('synthetic diagnostic', p.stdout + p.stderr, "sprite's own text reached the driver's answer")
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
            with open(self.env['FAKE_SPRITE_CALLS']) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def args(self, *first):
        return [c['args'] for c in self.calls() if c['args'][:len(first)] == list(first)]

    def sprites(self, org=ORG):
        try:
            with open(self.env['FAKE_SPRITE_STATE']) as f:
                return json.load(f)['orgs'].get(org, {})
        except FileNotFoundError:
            return {}

    def home(self, out, *names):
        return os.path.join(self.env['FAKE_SPRITE_STATE'] + '.homes', ORG, 'openwiz-' + out['run'], *names)

    def envs(self):
        try:
            with open(self.env['FAKE_ENVS']) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def logged(self):
        try:
            with open(self.env['FAKE_TURNS']) as f:
                return [(int(p), s, k) for p, s, k in (line.split() for line in f)]
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

    def saved_run(self, out):
        with open(os.path.join(self.env['OPENWIZ_SPRITES_STATE'], out['run'] + '.json')) as f:
            return json.load(f)

    def ended(self, out):
        pid = self.saved_run(out)['turns'][-1]['pid']
        return self.until(lambda: not alive(pid))

    def test_kit_passes_all_five_for_each_harness(self):
        for harness, model in (('claude', 'claude-opus-5-5'), ('codex', 'gpt-6.2-sol')):
            with self.subTest(harness=harness):
                self.tearDown()
                self.setUp()
                p = self.kit(harness, model)
                self.assertEqual((p.returncode, p.stdout.splitlines()), (0, PASS), p.stderr)
                self.assertEqual(self.sprites(), {})

    def test_kit_passes_all_five_without_proc_as_on_macos(self):
        with open(self.hold, 'w') as f:
            f.write('woken')
        p = self.kit('claude', 'claude-opus-5-5', python=os.path.join(NO_PROC, 'python3'),
                     PATH=NO_PROC + os.pathsep + self.env['PATH'], NO_PROC_PYTHON=sys.executable)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, PASS), p.stderr)

    def test_start_creates_one_labelled_sprite_named_for_the_run(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertRegex(out['run'], r'^sp-[0-9a-f]{12}$')
        self.assertEqual(self.args('create'), [['create', '-o', ORG, '--skip-console', '--label', 'openwiz',
                                                'openwiz-' + out['run']]])
        self.assertEqual(list(self.sprites()), ['openwiz-' + out['run']])

    def test_version_lists_many_at_once_own_sandbox_and_effort(self):
        self.assertEqual(self.driver('version', {}), (0, {'driver': 'sprites', 'records': ['openwiz:records v1'],
                                                          'can': ['start', 'wake', 'stop', 'many-at-once',
                                                                  'own-sandbox', 'effort']}))

    def test_the_only_connector_values_passed_are_gateway_urls(self):
        for request in (REQUEST, CODEX):
            code, out = self.driver('start', request)
            self.assertEqual(code, 0, out)
            self.assertTrue(self.ended(out))
            self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
            self.assertTrue(self.ended(out))
        turns = self.envs()
        self.assertEqual([t['harness'] for t in turns], ['claude', 'claude', 'codex', 'codex'])
        ids = list(CONNECTIONS.values())
        for t in turns:
            base = 'ANTHROPIC_BASE_URL' if t['harness'] == 'claude' else 'OPENAI_BASE_URL'
            self.assertEqual(t['env'][base], GATEWAYS[base])
            self.assertEqual(t['env']['OPENWIZ_GITHUB_API'], GATEWAYS['OPENWIZ_GITHUB_API'])
            for name, value in t['env'].items():
                if any(i in value for i in ids):
                    self.assertIn(name, GATEWAYS, 'a connection id reached %s outside a gateway URL' % name)
                    self.assertEqual(value, GATEWAYS[name])
        for call in self.calls():
            for word in call['args']:
                self.assertFalse(any(i in word for i in ids), 'a connection id is on a local command line: %s' % word)
            text = call['stdin'] or ''
            for url in sorted(GATEWAYS.values(), key=len, reverse=True):
                text = text.replace(url, '')
            self.assertFalse(any(i in text for i in ids), 'the install names a connection id outside a gateway URL')

    def test_no_real_key_or_github_token_reaches_the_sprite(self):
        kit = kit_module()
        for request in (REQUEST, CODEX):
            code, out = self.driver('start', request)
            self.assertEqual(code, 0, out)
            self.assertTrue(self.ended(out))
        turns = self.envs()
        self.assertEqual(len(turns), 2)
        for t in turns:
            key = 'ANTHROPIC_API_KEY' if t['harness'] == 'claude' else 'CODEX_API_KEY'
            self.assertEqual(t['env'][key], 'openwiz-sprites-gateway-holds-the-key')
            self.assertFalse(kit.holds_credential(t['env'][key]), 'the placeholder looks like a credential')
            for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'OPENAI_API_KEY'):
                self.assertNotIn(name, t['env'])
            for word in list(t['env'].values()) + t['args']:
                self.assertNotIn(GH_TOKEN, word)
                self.assertNotIn(ANTHROPIC_KEY, word)
        for call in self.calls():
            text = json.dumps(call)
            self.assertNotIn(GH_TOKEN, text)
            self.assertNotIn(ANTHROPIC_KEY, text)
            self.assertNotIn('openwiz-sprites-gateway-holds-the-key', ' '.join(call['args']))
            self.assertIsNone(re.search(r'API_KEY|TOKEN|--env', ' '.join(call['args'])), call['args'])

    def test_a_given_effort_reaches_the_harness_by_its_documented_flag(self):
        for request, effort, words in ((REQUEST, 'high', ['--effort', 'high']),
                                       (CODEX, 'xhigh', ['-c', 'model_reasoning_effort=xhigh'])):
            with self.subTest(harness=request['harness']):
                code, out = self.driver('start', dict(request, effort=effort))
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out))
                self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
                self.assertTrue(self.ended(out))
                for t in self.envs()[-2:]:
                    self.assertIn(words[0], t['args'], 'the effort did not reach the harness')
                    at = t['args'].index(words[0])
                    self.assertEqual(t['args'][at:at + 2], words)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        self.assertFalse({'--effort', '-c'} & set(self.envs()[-1]['args']), 'an effort was set that no one asked for')

    def test_an_effort_the_harness_cannot_take_is_refused_before_anything_is_created(self):
        for request, effort in ((REQUEST, 'ultra'), (CODEX, 'ultracode'), (REQUEST, 'minimal'),
                                (dict(REQUEST, harness='pi'), 'high')):
            with self.subTest(harness=request['harness'], effort=effort):
                code, err = self.driver('start', dict(request, effort=effort))
                self.assertEqual(code, 1, err)
                self.assertEqual(err['next'], REFUSE_EFFORT)
                self.assertIn(request['harness'], err['error'])
                self.assertIn(effort, err['error'])
                self.assertEqual(self.calls(), [], 'sprite was called for a refused effort')
        code, err = self.driver('start', dict(REQUEST, effort='High'))
        self.assertEqual(code, 1, err)
        self.assertEqual(self.calls(), [])

    def test_start_refuses_before_any_create_without_its_connection_ids(self):
        cases = (('no anthropic connection', REQUEST, {'OPENWIZ_SPRITES_ANTHROPIC': ''}, 'OPENWIZ_SPRITES_ANTHROPIC'),
                 ('no openai connection', CODEX, {'OPENWIZ_SPRITES_OPENAI': ''}, 'OPENWIZ_SPRITES_OPENAI'),
                 ('no github connection', REQUEST, {'OPENWIZ_SPRITES_GITHUB': ''}, 'OPENWIZ_SPRITES_GITHUB'),
                 ('a connection id that is a key', REQUEST, {'OPENWIZ_SPRITES_ANTHROPIC': ANTHROPIC_KEY},
                  'OPENWIZ_SPRITES_ANTHROPIC'),
                 ('a connection id with a slash', REQUEST, {'OPENWIZ_SPRITES_GITHUB': 'conn/../x'},
                  'OPENWIZ_SPRITES_GITHUB'),
                 ('a harness with no connector', dict(REQUEST, harness='pi'), {}, 'pi'),
                 ('no organization', REQUEST, {'OPENWIZ_SPRITES_ORG': ''}, 'OPENWIZ_SPRITES_ORG'),
                 ('an organization that is a flag', CODEX, {'OPENWIZ_SPRITES_ORG': '-x'}, 'OPENWIZ_SPRITES_ORG'))
        for case, request, env, named in cases:
            with self.subTest(case=case):
                code, err = self.driver('start', request, **env)
                self.assertEqual(code, 1, err)
                self.assertIn(named, err['error'] + err['next'])
                self.assertIn('nothing was created', err['error'])
                self.assertNotIn(ANTHROPIC_KEY, json.dumps(err))
                self.assertEqual(self.calls(), [])

    def test_a_wake_after_stop_or_for_an_unknown_run_is_refused(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()))
        harness = self.logged()[0][0]
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(harness), 'the turn still runs after stop')
        code, err = self.driver('wake', out)
        self.assertEqual((code, err['error']), (1, 'run %s is stopped' % out['run']))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)), 'a second stop did not answer')
        code, err = self.driver('wake', {'run': 'sp-0123456789ab'})
        self.assertEqual((code, err['error']), (1, 'no run sp-0123456789ab'))
        self.assertEqual(len(self.logged()), 1)

    def test_stop_runs_sprite_destroy_and_confirms_the_sprite_is_gone(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        name = 'openwiz-' + out['run']
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.args('destroy'), [['destroy', '-o', ORG, '--force', name]])
        self.assertEqual(self.args('api'), [['api', '-o', ORG, '/sprites/' + name, '--', '-sS', '-w',
                                             '\n%{http_code}']] * 3)
        self.assertEqual({tuple(c['args'][:3]) for c in self.calls() if c['args'][0] == 'exec'}, {('exec', '-o', ORG)})
        self.assertEqual(self.args('list'), [])
        self.assertEqual(self.sprites(), {})

    def test_a_run_keeps_its_organization_when_the_default_or_the_variable_changes(self):
        switched = {'FAKE_SPRITE_DEFAULT_ORG': OTHER_ORG, 'OPENWIZ_SPRITES_ORG': OTHER_ORG}
        for same_name_there in (False, True):
            with self.subTest(same_name_there=same_name_there):
                self.tearDown()
                self.setUp()
                code, out = self.driver('start', REQUEST)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out))
                name = 'openwiz-' + out['run']
                if same_name_there:
                    subprocess.run([os.path.join(HERE, 'fixtures', 'bin', 'sprite'), 'create', '-o', OTHER_ORG,
                                    '--skip-console', '--label', 'openwiz', name], env=self.env, check=True,
                                   capture_output=True)
                woke = self.driver('wake', out, **switched)
                self.assertTrue(self.ended(out))
                stopped = self.driver('stop', out, **switched)
                self.assertEqual((woke, stopped, list(self.sprites()), list(self.sprites(OTHER_ORG))),
                                 ((0, dict(out, woke=True)), (0, dict(out, stopped=True)), [],
                                  [name] if same_name_there else []))
                orgs = [c['args'][1:3] for c in self.calls()]
                self.assertEqual(orgs.count(['-o', ORG]), len(orgs) - same_name_there, orgs)

    def test_a_stop_destroys_nothing_but_the_sprite_its_start_read(self):
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.ended(out))
        name = 'openwiz-' + out['run']
        code, err = self.driver('stop', out, FAKE_SPRITE_ORG_ANSWER=OTHER_ORG)
        self.assertEqual((code, list(self.sprites()), self.args('destroy')), (1, [name], []), err)
        self.assertIn('may still be there', err['error'])
        with open(self.env['FAKE_SPRITE_STATE']) as f:
            state = json.load(f)
        state['orgs'][ORG][name]['id'] = 'sprite-11111111-2222-3333-4444-555555555555'
        with open(self.env['FAKE_SPRITE_STATE'], 'w') as f:
            json.dump(state, f)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual((list(self.sprites()), self.args('destroy')), ([name], []))

    def test_a_stop_trusts_only_the_one_sprite_read_never_a_truncated_list(self):
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.ended(out))
        name = 'openwiz-' + out['run']
        code, err = self.driver('stop', out, FAKE_SPRITE_DESTROY_NOOP='1', FAKE_SPRITE_LIST_TRUNCATED='1')
        self.assertEqual((code, list(self.sprites())), (1, [name]), err)
        self.assertIn('may still be there', err['error'])
        self.assertIn('sprite info -o %s %s' % (ORG, name), err['next'])
        self.assertEqual(self.driver('stop', out, FAKE_SPRITE_LIST_TRUNCATED='1'), (0, dict(out, stopped=True)))
        self.assertEqual(self.sprites(), {})

    def test_a_404_counts_as_gone_only_after_the_read_has_shown_this_sprite(self):
        code, err = self.driver('start', REQUEST, FAKE_SPRITE_API_404='1')
        self.assertEqual(code, 1, err)
        self.assertIn('could not read its new Sprite back', err['error'])
        self.assertIn('may still be there', err['error'])
        self.assertTrue(self.args('destroy'))
        self.assertEqual(self.sprites(), {})
        self.assertEqual(self.args('exec'), [])

    def test_a_stop_whose_destroy_did_not_take_says_so_and_a_later_stop_finishes(self):
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.ended(out))
        name = 'openwiz-' + out['run']
        for env, left in (({'FAKE_SPRITE_DESTROY_NOOP': '1'}, [name]), ({'FAKE_SPRITE_FAIL': 'destroy'}, [name]),
                          ({'FAKE_SPRITE_FAIL': 'api'}, [name])):
            with self.subTest(env=env):
                code, err = self.driver('stop', out, **env)
                self.assertEqual((code, list(self.sprites())), (1, left), err)
                self.assertIn('sprite destroy -o %s --force %s' % (ORG, name), err['next'])
                code, err = self.driver('wake', out)
                self.assertEqual((code, err['error']), (1, 'run %s is stopped' % out['run']))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertEqual(self.sprites(), {})

    def test_a_wake_while_the_turn_runs_starts_nothing(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: self.logged()))
        self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
        self.assertEqual(len(self.logged()), 1)

    def test_a_wake_resumes_the_same_session(self):
        for request in (REQUEST, CODEX):
            with self.subTest(harness=request['harness']):
                code, out = self.driver('start', request)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out))
                self.assertEqual(self.driver('wake', out), (0, dict(out, woke=True)))
                self.assertTrue(self.ended(out))
                (_, first, a), (_, then, b) = self.logged()[-2:]
                self.assertEqual((first, a, then, b), (first, 'first', first, 'woken'))
                self.assertEqual(self.notes()[-1][1], 'woke and read the ticket again')
                self.assertEqual(self.saved_run(out)['session'], first)
        self.assertEqual(len(self.notes()), 2)

    def test_a_wake_of_a_sprite_that_lost_its_run_is_refused(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        os.remove(self.home(out, '.openwiz', 'runs', out['run']))
        code, err = self.driver('wake', out)
        self.assertEqual(code, 1, err)
        self.assertIn('lost', err['error'])
        self.assertEqual(len(self.logged()), 1)

    def test_sprite_text_never_reaches_an_answer_and_a_failed_start_step_destroys_the_sprite(self):
        for fails, destroys in (('create', 0), ('exec', 1), ('install-refused', 1), ('exec@2', 1)):
            with self.subTest(fails=fails):
                self.tearDown()
                self.setUp()
                env = {'FAKE_WIZ_COMMIT': '0' * 40} if fails == 'install-refused' else {'FAKE_SPRITE_FAIL': fails}
                code, err = self.driver('start', REQUEST, **env)
                self.assertEqual(code, 1, err)
                self.assertNotIn('synthetic', json.dumps(err))
                self.assertEqual(self.sprites(), {}, err)
                self.assertEqual(self.logged(), [])
                self.assertEqual(len(self.args('destroy')), destroys)
                if fails == 'exec@2':
                    self.assertIn('the claude turn did not begin', err['error'])
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.ended(out))
        code, err = self.driver('wake', out, FAKE_SPRITE_FAIL='exec')
        self.assertEqual(code, 1, err)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_a_start_whose_cleanup_destroy_fails_names_the_run_to_stop(self):
        code, err = self.driver('start', REQUEST, FAKE_WIZ_COMMIT='0' * 40, FAKE_SPRITE_FAIL='destroy')
        self.assertEqual(code, 1, err)
        self.assertEqual(len(self.sprites()), 1)
        run = re.search(r'\bsp-[0-9a-f]{12}\b', err['error'] + err['next'])
        self.assertTrue(run, 'the refusal names no run to stop')
        self.assertIn('sprite destroy -o %s --force openwiz-' % ORG + run.group(0), err['next'])
        self.assertEqual(self.driver('stop', {'run': run.group(0)}), (0, {'run': run.group(0), 'stopped': True}))
        self.assertEqual(self.sprites(), {})

    def test_a_start_whose_harness_refuses_after_it_began_fails_and_destroys_the_sprite(self):
        for request in (REQUEST, CODEX):
            with self.subTest(harness=request['harness']):
                self.tearDown()
                self.setUp()
                open(self.hold, 'w').close()
                code, err = self.driver('start', request, FAKE_HARNESS_401='1')
                self.assertEqual(code, 1, err)
                self.assertIn('so the run did not start', err['error'])
                self.assertEqual(self.sprites(), {}, err)
                self.assertTrue(self.until(lambda: not any(alive(p) for p, _, _ in self.logged())))

    def test_a_wake_whose_harness_refuses_to_resume_fails(self):
        for request in (REQUEST, CODEX):
            with self.subTest(harness=request['harness']):
                code, out = self.driver('start', request)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.ended(out))
                session = self.logged()[-1][1]
                os.remove(self.home(out, '.fake-sessions', session))
                turns = len(self.saved_run(out)['turns'])
                code, err = self.driver('wake', out)
                self.assertEqual(code, 1, err)
                self.assertIn('so the run did not wake', err['error'])
                self.assertEqual(len(self.saved_run(out)['turns']), turns)
                self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_start_refuses_a_credential_by_its_shape_and_never_imports_the_kit(self):
        code, err = self.driver('start', dict(REQUEST, model='sk-' + 'A' * 24))
        self.assertEqual((code, err['error']), (1, 'model looks like a credential, so nothing was saved or started'))
        self.assertEqual(self.calls(), [])
        watcher, heard = os.path.join(self.folder, 'heard.py'), os.path.join(self.folder, 'heard')
        with open(watcher, 'w') as f:
            f.write(HEARD)
        for request in (dict(REQUEST, model='sk-' + 'A' * 24), REQUEST):
            self.driver('start', request, (sys.executable, '-I', watcher, heard))
        with open(heard) as f:
            opened = f.read().splitlines()
        self.assertIn(DRIVER, opened, 'the audit hook heard nothing')
        self.assertEqual([x for x in opened if os.path.basename(x) in ('kit', 'kit.py', 'driver-kit')], [])

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
            self.assertEqual(f.read(), '', 'the driver read an ambient value')

    def test_the_state_folder_and_every_file_in_it_are_owner_only(self):
        state = self.env['OPENWIZ_SPRITES_STATE']
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
            self.assertEqual(sorted({n.rsplit('.', 1)[-1] for n in modes}), ['json', 'lock', 'log', 'sup'])
            self.assertEqual({n: m for n, m in modes.items() if m != 0o600}, {})
        finally:
            os.umask(old)

    def test_the_prompt_sends_the_push_and_github_calls_through_the_gateway(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.ended(out))
        prompt = self.envs()[-1]['args'][-1]
        self.assertIn('openwiz-push <branch>', prompt)
        self.assertIn('never `git push`', prompt)
        self.assertIn('$OPENWIZ_GITHUB_API', prompt)
        self.assertIn('no Authorization header', prompt)
        helper = self.home(out, '.openwiz', 'bin', 'openwiz-push')
        self.assertTrue(os.access(helper, os.X_OK), 'start did not install openwiz-push in the Sprite')


class Push(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sprites = Sprites('run')
        sprites.setUp()
        try:
            code, out = sprites.driver('start', REQUEST)
            assert code == 0, out
            cls.installed = tempfile.mkdtemp()
            shutil.copy(sprites.home(out, '.openwiz', 'bin', 'openwiz-push'), cls.installed)
        finally:
            sprites.tearDown()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.installed)

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.helper = os.path.join(self.installed, 'openwiz-push')
        self.bare = os.path.join(self.folder, 'remote.git')
        self.log = os.path.join(self.folder, 'gateway.log')
        self.git_env = dict(os.environ, HOME=self.folder, GIT_CONFIG_NOSYSTEM='1', TZ='UTC',
                            GIT_AUTHOR_NAME='Example Agent', GIT_AUTHOR_EMAIL='agent@example.com',
                            GIT_COMMITTER_NAME='Example Agent', GIT_COMMITTER_EMAIL='agent@example.com')
        for k in ('GH_TOKEN', 'GITHUB_TOKEN', 'OPENWIZ_GITHUB_API'):
            self.git_env.pop(k, None)
        self.git('init', '-q', '--bare', '-b', 'main', self.bare, cwd=self.folder)
        self.work = os.path.join(self.folder, 'site')
        self.git('init', '-q', '-b', 'main', self.work, cwd=self.folder)
        self.write('README.md', 'synthetic site\n')
        self.write('docs/old.md', 'to be deleted\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'first')
        self.git('push', '-q', self.bare, 'main')
        self.git('remote', 'add', 'origin', 'https://github.com/example/site.git')
        self.git('update-ref', 'refs/remotes/origin/main', 'main')
        self.serve()

    def serve(self, **env):
        self.server = subprocess.Popen([sys.executable, '-I', GATEWAY, self.bare, 'example/site', self.log],
                                       stdout=subprocess.PIPE, text=True, env=dict(self.git_env, **env))
        self.api = 'http://127.0.0.1:%s' % self.server.stdout.readline().strip()

    def tearDown(self):
        self.server.kill()
        self.server.wait()
        shutil.rmtree(self.folder, ignore_errors=True)

    def git(self, *args, cwd=None):
        return subprocess.run(['git'] + list(args), cwd=cwd or self.work, env=self.git_env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, name, text, mode=0o644):
        path = os.path.join(self.work, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(text)
        os.chmod(path, mode)

    def push(self, branch, **env):
        return subprocess.run([sys.executable, '-I', self.helper, branch], cwd=self.work, capture_output=True,
                              text=True, timeout=60, env=dict(dict(self.git_env, OPENWIZ_GITHUB_API=self.api), **env))

    def remote(self, branch):
        p = subprocess.run(['git', '--git-dir', self.bare, 'rev-parse', '--verify', '-q', 'refs/heads/' + branch],
                           capture_output=True, text=True)
        return p.stdout.strip() or None

    def requests(self):
        try:
            with open(self.log) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def writes(self):
        return [r for r in self.requests() if r['method'] != 'GET']

    def test_a_new_branch_is_published_with_the_same_commits_and_trees(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('src/deep/app.py', 'print(1)\n')
        self.write('run.sh', '#!/bin/sh\necho run\n', 0o755)
        os.symlink('README.md', os.path.join(self.work, 'link.md'))
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'add the app\n\nwith a body')
        self.git('rm', '-q', 'docs/old.md')
        self.write('README.md', 'synthetic site, changed\n')
        self.git('commit', '-q', '-am', 'drop the old doc')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        head = self.git('rev-parse', 'HEAD')
        self.assertEqual(self.remote('agent/7'), head)
        self.assertEqual(self.git('rev-parse', 'refs/remotes/origin/agent/7'), head)
        self.assertEqual(subprocess.run(['git', '--git-dir', self.bare, 'rev-parse', 'agent/7^{tree}'],
                                        capture_output=True, text=True).stdout.strip(),
                         self.git('rev-parse', 'HEAD^{tree}'))
        self.assertEqual(self.remote('main'), self.git('rev-parse', 'main'), 'the push moved another branch')
        self.assertEqual([r for r in self.requests() if 'Authorization' in r['headers']], [])
        self.assertEqual([(r['method'], r['path']) for r in self.writes()][-1],
                         ('POST', '/repos/example/site/git/refs'))

    def test_a_fast_forward_moves_the_branch_and_uploads_only_the_new_commits(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('a.txt', 'a\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'a')
        self.assertEqual(self.push('agent/7').returncode, 0)
        before = len(self.requests())
        self.write('b.txt', 'b\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'b')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(self.remote('agent/7'), self.git('rev-parse', 'HEAD'))
        later = [r for r in self.requests()[before:] if r['method'] != 'GET']
        self.assertEqual([r['path'].rsplit('/git/', 1)[1] for r in later],
                         ['blobs', 'trees', 'commits', 'refs/heads/agent/7'])
        self.assertEqual([r['force'] for r in later if r['method'] == 'PATCH'], [False])
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('up to date', p.stdout)

    def test_anything_but_a_fast_forward_is_refused_before_any_write(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('a.txt', 'a\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'a')
        self.assertEqual(self.push('agent/7').returncode, 0)
        published = self.remote('agent/7')
        self.git('commit', '-q', '--amend', '-m', 'a, rewritten')
        writes = len(self.writes())
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('not a fast-forward', p.stderr)
        self.assertEqual((self.remote('agent/7'), len(self.writes())), (published, writes))

    def test_a_branch_whose_remote_head_is_unknown_here_is_refused(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('a.txt', 'a\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'a')
        other = subprocess.run(['git', '--git-dir', self.bare, 'commit-tree', '-p', 'main', '-m', 'elsewhere',
                                'main^{tree}'], capture_output=True, text=True, env=self.git_env).stdout.strip()
        subprocess.run(['git', '--git-dir', self.bare, 'update-ref', 'refs/heads/agent/7', other], check=True)
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('not a fast-forward', p.stderr)
        self.assertEqual((self.remote('agent/7'), self.writes()), (other, []))

    def test_a_commit_github_would_write_with_another_sha_is_refused_before_the_ref_moves(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('a.txt', 'a\n')
        self.git('add', '-A')
        self.git_env['GIT_COMMITTER_DATE'] = '2026-11-23T03:00:00+0200'
        self.git('commit', '-q', '-m', 'a')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('TZ=UTC', p.stderr)
        self.assertIsNone(self.remote('agent/7'))
        self.assertEqual([r for r in self.writes() if '/git/refs' in r['path']], [])

    def test_blobs_github_already_has_are_never_uploaded(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('copy-of-readme.md', 'synthetic site\n')
        self.write('docs/again.md', 'to be deleted\n')
        self.write('new.md', 'new\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'two known blobs at new paths, one new blob')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual(len([r for r in self.writes() if r['path'].endswith('/git/blobs')]), 1)
        self.assertEqual(self.remote('agent/7'), self.git('rev-parse', 'HEAD'))

    def test_a_blob_only_an_older_github_commit_holds_is_never_uploaded_again(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        self.git('rm', '-q', 'docs/old.md')
        self.git('commit', '-q', '-m', 'drop the old doc')
        self.assertEqual(self.push('agent/7').returncode, 0)
        before = len(self.writes())
        self.git('checkout', '-q', 'main', '--', 'docs/old.md')
        self.git('commit', '-q', '-m', 'restore the old doc from history')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([r['path'].rsplit('/git/', 1)[1] for r in self.writes()[before:]],
                         ['trees', 'commits', 'refs/heads/agent/7'])
        self.assertEqual(self.remote('agent/7'), self.git('rev-parse', 'HEAD'))

    def test_a_push_that_changes_more_than_200_files_is_refused_before_any_write(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        for n in range(201):
            self.write('many/%03d.txt' % n, 'file %d\n' % n)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', '201 files')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertEqual(len(p.stderr.strip().splitlines()), 1, p.stderr)
        self.assertIn('201 files', p.stderr)
        self.assertIn('200', p.stderr)
        self.assertEqual((self.remote('agent/7'), self.writes()), (None, []))
        self.git('rm', '-q', 'many/200.txt')
        self.git('commit', '-q', '--amend', '-m', '200 files')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_a_typical_push_of_ten_files_makes_a_fixed_number_of_rest_calls(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        for n in range(10):
            self.write('src/%d.py' % n, 'print(%d)\n' % n)
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'ten files')
        self.assertEqual(self.push('agent/7').returncode, 0)
        self.assertEqual(len(self.requests()), 15, 'a new branch: ref read, base check, 10 blobs, tree, commit, ref')
        before = len(self.requests())
        for n in range(10):
            self.write('src/%d.py' % n, 'print(%d + 1)\n' % n)
        self.git('commit', '-q', '-am', 'ten more changes')
        self.assertEqual(self.push('agent/7').returncode, 0)
        self.assertEqual(len(self.requests()) - before, 14, 'a fast-forward: ref read, 10 blobs, tree, commit, ref')

    def test_a_commit_github_writes_with_another_sha_leaves_the_branch_unmoved(self):
        self.server.kill()
        self.server.wait()
        self.serve(FAKE_GATEWAY_TRIM_MESSAGES='1')
        self.git('checkout', '-q', '-b', 'agent/7')
        self.write('a.txt', 'a\n')
        self.git('add', '-A')
        self.git('commit', '-q', '-m', 'a')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('GitHub wrote commit %s as ' % self.git('rev-parse', 'HEAD'), p.stderr)
        self.assertIn('nothing was moved', p.stderr)
        self.assertIsNone(self.remote('agent/7'))
        self.assertEqual([r for r in self.writes() if '/git/refs' in r['path']], [])

    def test_it_refuses_without_a_gateway_or_a_github_origin_or_a_branch(self):
        self.git('checkout', '-q', '-b', 'agent/7')
        for case, env, branch, word in (('no gateway', {'OPENWIZ_GITHUB_API': ''}, 'agent/7', 'OPENWIZ_GITHUB_API'),
                                        ('no such branch', {}, 'agent/8', 'agent/8'),
                                        ('a bad branch name', {}, '-x', 'branch')):
            with self.subTest(case=case):
                p = self.push(branch, **env)
                self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
                self.assertIn(word, p.stderr)
        self.git('remote', 'set-url', 'origin', 'https://example.com/site.git')
        p = self.push('agent/7')
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn('github.com', p.stderr)
        self.assertEqual(self.writes(), [])


if __name__ == '__main__':
    unittest.main()
