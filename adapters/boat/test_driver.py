#!/usr/bin/env python3
"""D1, D2 for the boat.dev driver, on a synthetic `boat` CLI (fixtures/bin/boat) and a local tracker.

Run: python3 -I adapters/boat/test_driver.py   (Linux: the kit watches /proc)
"""
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
# A synthetic value in a GitHub token's shape, built here so no file holds one.
TOKEN = 'gh' + 'p_' + 'Synthetic0Boat0Value' * 2 + '00'
# A driver whose next save fails once a turn's `boat prompt` has begun, as a full disk would make it.
BREAKS_AFTER_SPAWN = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('boat', importlib.machinery.SourceFileLoader('boat', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
prompt = t.prompt
def broken(state, run, *rest):
    out = prompt(state, run, *rest)
    os.mkdir(os.path.join(t.STATE, run + '.json.new'))
    return out
t.prompt = broken
t.main()
'''
# A driver with planted failures: with RAISE, its `prompt` raises an error the driver doesn't expect (not
# Refused), before it runs `boat prompt` or once the turn has begun, as an unexpected boat answer did on the live
# run (L2); with DENY_PROC, listing /proc fails; with DENY_SIGNALS, every signal fails; with READ_ONLY, every mark and save fails.
RAISES = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('boat', importlib.machinery.SourceFileLoader('boat', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
prompt, save = t.prompt, t.saved
def broken(*args):
    if os.environ.get('RAISE') == 'after':
        prompt(*args)
    raise KeyError('planted')
if os.environ.get('RAISE'):
    t.prompt = broken
if os.environ.get('DENY_PROC'):  # Linux refuses to list /proc
    listdir = os.listdir
    t.os.listdir = lambda p='.': listdir(p) if p != '/proc' else (_ for _ in ()).throw(PermissionError(13, 'denied'))
if os.environ.get('DENY_SIGNALS'):  # Linux refuses every signal the driver sends
    def denied(*args):
        raise PermissionError(1, 'Operation not permitted')
    t.signal.pidfd_send_signal, t.GRACE = denied, 0.2
if os.environ.get('AUDIT'):  # write down every open of a process's environment, and refuse it
    import re
    def audit(event, args, seen=os.environ['AUDIT']):
        if event == 'open' and isinstance(args[0], (str, bytes)) and re.search(r'^/proc/[0-9]+/environ$', os.fsdecode(args[0])):
            with open(seen, 'a') as f:
                f.write(os.fsdecode(args[0]) + '\\n')
            raise PermissionError(13, 'denied by the test')
    sys.addaudithook(audit)
if os.environ.get('READ_ONLY'):  # a read-only filesystem: no mark and no save can be written
    def unsaved(run, state=None):
        if state is not None:
            raise OSError(30, 'Read-only file system')
        return save(run)
    t.saved, t.mark_stopping = unsaved, lambda run: False
t.main()
'''
# A driver whose wake pauses once it reads the sandbox's state, until the file named by RELEASE exists.
PAUSES_IN_WAKE = '''import importlib.machinery, importlib.util, os, sys, time
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('boat', importlib.machinery.SourceFileLoader('boat', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
sandbox_state = t.sandbox_state
def paused(*args):
    answer = sandbox_state(*args)
    open(os.environ['PAUSED'], 'w').close()
    while not os.path.exists(os.environ['RELEASE']):
        time.sleep(0.01)
    return answer
t.sandbox_state = paused
t.main()
'''
ODD_BOAT = '''import json, os, sys
if sys.argv[1:2] == ['exec'] and 'openwiz-push-ok' in ' '.join(sys.argv) and os.environ.get('PUSH_ANSWER'):
    ok = os.environ['PUSH_ANSWER'] == 'ok'
    sys.stdout.buffer.write(b'\\xff\\xfe synthetic\\n' + (b'openwiz-push-ok\\n' if ok else b''))
    sys.stderr.buffer.write(b'\\xff synthetic diagnostic\\n')
    sys.exit(0 if ok else 1)
if sys.argv[1:2] == [os.environ.get('STDERR_FOR')]:
    if os.environ['STDERR_HOW'] == 'code':
        print('Error: provider_not_configured (synthetic detail %%s)' %% os.environ['FAKE_MARKER'], file=sys.stderr)
    else:
        print(json.dumps({'event': 'error', 'error': 'Synthetic failure', 'code': 'internal_error'}), flush=True)
        print('Synthetic: login expired, session ' + os.environ['FAKE_MARKER'], file=sys.stderr)
    sys.exit(1)
os.execv(%r, [%r] + sys.argv[1:])
'''
EXEC_FAILS = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('boat', importlib.machinery.SourceFileLoader('boat', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
run = t.subprocess.run
def failing(args, *rest, **options):
    if 'openwiz-push-ok' in ' '.join(args):
        raise OSError(7, 'Argument list too long')
    return run(args, *rest, **options)
t.subprocess.run = failing
t.main()
'''
ENVIRON_OPENS, WATCHING = [], []


def watch(event, args):
    if WATCHING and event == 'open' and isinstance(args[0], (str, bytes)) \
            and re.search(r'^/proc/[0-9]+/environ$', os.fsdecode(args[0])):
        ENVIRON_OPENS.append(os.fsdecode(args[0]))


sys.addaudithook(watch)
PR_SET_CHILD_SUBREAPER = 36


def adopt_every_orphan_of_these_tests():
    if ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
        raise SystemExit('these tests need Linux, to keep the processes they start under them')


def reap_adopted_orphans():
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                return
        except ChildProcessError:
            return


adopt_every_orphan_of_these_tests()
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}
CANT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at "
        "the host's default")
HARNESSES = ('claude', 'codex', 'pi', 'opencode', 'prime', 'kimi', 'mistral')


def alive(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            return f.read().rpartition(')')[2].split()[0] != 'Z'
    except OSError:
        return False


class Boat(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.turns, self.hold = os.path.join(self.folder, 'turns'), os.path.join(self.folder, 'hold')
        self.env = dict(HOME=self.folder, KIT_TRACKER=self.tracker, KIT_TEST=self.mark, GH_TOKEN=TOKEN,
                        FAKE_TURNS=self.turns, FAKE_HOLD=self.hold,
                        FAKE_BOAT_STATE=os.path.join(self.folder, 'boat.json'),
                        OPENWIZ_BOAT_STATE=os.path.join(self.folder, 'state'), OPENWIZ_BOAT_SETTLE='2',
                        PATH=os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + self.only_these_tools())
        for real in ('claude', 'codex', 'gh', 'git'):
            self.assertIsNone(shutil.which(real, path=self.env['PATH']), 'a real %s is on the tests\' PATH' % real)
        self.assertEqual(shutil.which('boat', path=self.env['PATH']), os.path.join(HERE, 'fixtures', 'bin', 'boat'))
        self.assertNotIn('BASH_ENV', self.env)
        found = subprocess.run(['sh', '-c', 'command -v claude codex gh git; echo "$PATH"'], env=self.env,
                               capture_output=True, text=True).stdout.splitlines()
        self.assertEqual(found, [self.env['PATH']], 'the tests\' shell reaches a real binary')

    def only_these_tools(self):
        tools = os.path.join(self.folder, 'tools')
        os.mkdir(tools)
        for name in ('python3', 'sh', 'sleep', 'mktemp', 'rm', 'readlink', 'ln', 'mkdir', 'dirname', 'lsof'):
            os.symlink(shutil.which(name), os.path.join(tools, name))
        return tools

    def tearDown(self):
        for pid in self.live_descendants_of_this_test():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        self.until(lambda: not self.live_descendants_of_this_test())
        reap_adopted_orphans()

    def live_descendants_of_this_test(self):
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

    def recorded_by_supervisors(self, run):
        state, found = self.env['OPENWIZ_BOAT_STATE'], set()
        for name in os.listdir(state):
            if name.startswith(run + '.') and name.endswith('.sup'):
                try:
                    with open(os.path.join(state, name)) as f:
                        found.update(int(p) for p in json.load(f)['kept'])
                except (OSError, ValueError):
                    pass
        return found

    def logged(self):
        """The turns the fake `boat prompt` logged: [(prompt pid, worker pid, conversation, first|woken)]."""
        try:
            with open(self.turns) as f:
                return [(int(a), int(b), c, d) for a, b, c, d in (line.split() for line in f)]
        except FileNotFoundError:
            return []

    def until(self, ready):
        deadline = time.monotonic() + 10
        while not ready() and time.monotonic() < deadline:
            time.sleep(0.05)
        return ready()

    def wrapper(self, name, source):
        path = os.path.join(self.folder, name)
        with open(path, 'w') as f:
            f.write('#!%s\n' % sys.executable + source % DRIVER)
        os.chmod(path, 0o700)
        return path

    def driver(self, cmd, request, program=DRIVER, **env):
        p = subprocess.run([program, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        return p.returncode, json.loads(p.stdout)

    def sandboxes(self):
        try:
            with open(self.env['FAKE_BOAT_STATE']) as f:
                return {k: v['state'] for k, v in json.load(f)['sandboxes'].items()}
        except FileNotFoundError:
            return {}

    def notes(self):
        with open(self.tracker) as f:
            return [(c['id'], c['body'].split('step: ')[1].split('\n')[0]) for c in json.load(f)['comments']]

    def test_kit_passes_all_five(self):
        # catches: a wake that opens a new boat conversation (a second note), a start that answers before
        # the agent's turn is queued, a token passed into the `boat` processes the driver starts.
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

    def test_a_wake_after_the_turn_ended_prompts_the_saved_conversation(self):
        # catches: a driver that reads `state` only at the top of `boat info`'s answer, so with the live nested
        # shape (#1874) it finds the sandbox `unknown` and refuses every wake once a turn has ended; one that
        # wakes only `running`; and one that no longer reads the older flat shape.
        for shape, now in (('nested', 'running'), ('nested', 'idle'), ('nested', 'ready'), ('flat', 'idle')):
            with self.subTest(shape=shape, state=now):
                code, out = self.driver('start', REQUEST)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])), 'the first turn never ended')
                self.set_state(now)
                self.assertEqual(self.driver('wake', out, FAKE_BOAT_INFO=shape), (0, dict(out, woke=True)))
                self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])), 'the woken turn never ended')
                self.assertEqual([t[2:] for t in self.logged()[-2:]], [('c1', 'first'), ('c1', 'woken')])
                self.assertEqual(self.notes()[-1][1], 'woke and read the ticket again')
        # A state boat names that no wake may prompt in still refuses, and says which.
        self.set_state('archived')
        code, err = self.driver('wake', out)
        self.assertEqual((code, len(self.logged())), (1, 8), err)
        self.assertIn('is archived, not running', err['error'])

    def boat_calls(self, log):
        try:
            with open(log) as f:
                return [json.loads(x) for x in f]
        except FileNotFoundError:
            return []

    def run_files(self):
        try:
            return os.listdir(self.env['OPENWIZ_BOAT_STATE'])
        except FileNotFoundError:
            return []

    def start_and_wake(self, request, calls, prompts):
        code, out = self.driver('start', request, FAKE_BOAT_ARGS=calls, FAKE_PROMPTS=prompts,
                                FAKE_BOAT_PROVIDERS='claude,codex,kimi')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])), 'the first turn never ended')
        self.set_state('idle')
        self.assertEqual(self.driver('wake', out, FAKE_BOAT_ARGS=calls, FAKE_PROMPTS=prompts,
                                     FAKE_BOAT_PROVIDERS='claude,codex,kimi'), (0, dict(out, woke=True)))
        self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])), 'the woken turn never ended')
        turns = [c for c in self.boat_calls(calls) if c[:1] == ['prompt'] and '--help' not in c]
        helps = [c for c in self.boat_calls(calls) if c[:1] == ['prompt'] and '--help' in c]
        with open(prompts) as f:
            texts = [json.loads(x) for x in f]
        return turns, helps, texts

    def test_an_effort_reaches_boat_as_reasoning_effort(self):
        for harness, model, effort in (('claude', 'claude-opus-5-5', 'medium'), ('claude', 'syn-claude-also', 'max'),
                                       ('codex', 'syn-codex-second', 'xhigh'), ('kimi', 'syn-kimi', 'none')):
            with self.subTest(harness=harness, model=model, effort=effort):
                calls, prompts = os.path.join(self.folder, 'calls-' + effort), os.path.join(self.folder, 'p-' + effort)
                turns, helps, texts = self.start_and_wake(dict(REQUEST, harness=harness, model=model, effort=effort),
                                                          calls, prompts)
                self.assertEqual(helps, [['prompt', '--help', '--no-update']])
                self.assertEqual(len(turns), 2)
                for turn in turns:
                    self.assertEqual(turn.count('--reasoning-effort'), 1, turn)
                    self.assertEqual(turn[turn.index('--reasoning-effort') + 1], effort)
                    self.assertEqual(turn[turn.index('--provider') + 1], harness)
                    self.assertEqual(turn[turn.index('--model') + 1], model)
                self.assertEqual(len(texts), 2)
                for text in texts:
                    self.assertIn('`<your model> %s effort`' % effort, text)
                    self.assertNotIn('default effort', text)

    def test_no_effort_runs_at_the_hosts_default(self):
        calls, prompts = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'prompts')
        turns, helps, texts = self.start_and_wake(REQUEST, calls, prompts)
        self.assertEqual(helps, [])
        self.assertEqual(len(turns), 2)
        for turn in turns:
            self.assertNotIn('--reasoning-effort', turn)
        self.assertEqual(len(texts), 2)
        for text in texts:
            self.assertRegex(text, r"host's default effort")
            self.assertRegex(text, r'status note.* model field .*`<your model> default effort`')

    def test_an_effort_boat_cannot_set_is_refused_and_starts_nothing(self):
        for harness, model, effort in (('claude', 'claude-opus-5-5', 'minimal'),
                                       ('claude', 'syn-claude-small', 'xhigh'), ('claude', 'syn-claude-plain', 'low'),
                                       ('claude', 'syn-unlisted', 'medium'),
                                       ('codex', 'claude-opus-5-5', 'medium'), ('opencode', 'syn-open-one', 'medium'),
                                       ('pi', 'syn-pi', 'medium'), ('kimi', 'syn-kimi', 'low')):
            with self.subTest(harness=harness, model=model, effort=effort):
                calls = os.path.join(self.folder, 'calls-%s-%s' % (harness, effort))
                code, out = self.driver('start', dict(REQUEST, harness=harness, model=model, effort=effort),
                                        FAKE_BOAT_ARGS=calls, FAKE_BOAT_PROVIDERS='claude,codex,opencode,pi,kimi')
                self.assertEqual((code, sorted(out)), (1, ['error', 'next']), out)
                self.assertEqual(out['next'], CANT)
                self.assertRegex(out['error'], r'(?<![\w-])%s(?![\w-])' % re.escape(harness))
                self.assertRegex(out['error'], r'(?<![\w-])%s(?![\w-])' % re.escape(effort))
                self.assertLessEqual(len(out['error']), 300)
                self.assertEqual(self.boat_calls(calls), [['prompt', '--help', '--no-update']])
                self.assertEqual((self.sandboxes(), self.run_files(), self.logged()), ({}, [], []))
        for effort in ('medium', None):
            with self.subTest(harness='gemini', effort=effort):
                calls = os.path.join(self.folder, 'calls-gemini-%s' % effort)
                request = dict(REQUEST, harness='gemini', model='gemini-3.8-flash',
                               **({'effort': effort} if effort else {}))
                code, out = self.driver('start', request, FAKE_BOAT_ARGS=calls)
                self.assertEqual((code, sorted(out)), (1, ['error', 'next']), out)
                if effort:
                    self.assertEqual(out['next'], CANT)
                    self.assertRegex(out['error'], r'(?<![\w-])gemini(?![\w-])')
                    self.assertRegex(out['error'], r'(?<![\w-])medium(?![\w-])')
                    self.assertLessEqual(len(out['error']), 300)
                else:
                    self.assertEqual(out, {'error': 'boat has no harness gemini',
                                           'next': 'use one of: claude, codex, pi, opencode, prime, kimi, mistral'})
                self.assertEqual((self.boat_calls(calls), self.sandboxes(), self.run_files(), self.logged()),
                                 ([], {}, [], []))

    def test_the_driver_reads_the_level_list_boat_1_0_105_prints(self):
        for harness, model, effort, passed in (('claude', 'opus-5-5', 'medium', True),
                                               ('codex', 'gpt-5.6-terra', 'none', True),
                                               ('pi', 'llmgateway:glm-5.3', 'max', True),
                                               ('kimi', 'moonshot:kimi-k2.6', 'none', True),
                                               ('codex', 'gpt-5.4', 'max', False), ('claude', 'haiku', 'low', False),
                                               ('opencode', 'claude-sonnet-5', 'medium', False),
                                               ('claude', 'claude-opus-5-5', 'medium', False)):
            with self.subTest(harness=harness, model=model, effort=effort):
                calls = os.path.join(self.folder, 'calls-%s-%s-%s' % (harness, effort, passed))
                code, out = self.driver('start', dict(REQUEST, harness=harness, model=model, effort=effort),
                                        FAKE_BOAT_ARGS=calls, FAKE_BOAT_HELP='live',
                                        FAKE_BOAT_PROVIDERS='claude,codex,pi,opencode,kimi')
                self.assertEqual(code, 0 if passed else 1, out)
                self.assertEqual(out.get('next'), None if passed else CANT)
                turns = [c for c in self.boat_calls(calls) if c[:1] == ['prompt'] and '--help' not in c]
                self.assertEqual([c[c.index('--reasoning-effort') + 1] for c in turns], [effort] if passed else [])

    def test_a_start_whose_levels_cannot_be_read_starts_nothing(self):
        marker = 'sk-' + 'Synthetic0Host0Marker' + self.mark
        for name, env in (('fails', dict(FAKE_BOAT_FAIL='prompt')), ('no level list', dict(FAKE_BOAT_HELP='bare')),
                          ('no model rows', dict(FAKE_BOAT_HELP='headed')),
                          ('truncated', dict(FAKE_BOAT_HELP='truncated')),
                          ('diagnostic', dict(PATH=self.odd_boat(), STDERR_FOR='prompt', STDERR_HOW='mixed',
                                              FAKE_MARKER=marker))):
            with self.subTest(name):
                code, out = self.driver('start', dict(REQUEST, effort='medium'), **env)
                self.assertEqual((code, sorted(out)), (1, ['error', 'next']), out)
                self.assertNotEqual(out['next'], CANT)
                self.assertIn('nothing was saved or started', out['error'])
                self.assertIn('boat prompt --help', out['next'])
                self.assertNotIn(marker, json.dumps(out))
                self.assertNotIn('Synthetic', json.dumps(out))
                self.assertEqual((self.sandboxes(), self.run_files(), self.logged()), ({}, [], []))
        for effort in ('Medium', 'medium high', '', 'x' * 21, 5, None):
            with self.subTest(effort=effort):
                calls = os.path.join(self.folder, 'calls-bad')
                code, out = self.driver('start', dict(REQUEST, effort=effort), FAKE_BOAT_ARGS=calls)
                self.assertEqual((code, out), (1, {'error': 'effort is not valid',
                                                   'next': 'fix effort as `driver schema` shows'}))
                self.assertEqual((self.boat_calls(calls), self.sandboxes(), self.run_files()), ([], {}, []))

    def test_version_lists_effort_and_the_readme_says_how(self):
        self.assertEqual(self.driver('version', {}), (0, {
            'driver': 'boat', 'records': ['openwiz:records v1'],
            'can': ['start', 'wake', 'stop', 'many-at-once', 'own-sandbox', 'effort']}))
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        rest = [x for x in lines[lines.index('Login: held by boat.dev') + 1:] if x.strip()]
        self.assertTrue(rest[0].startswith('Effort: passed as `boat prompt --reasoning-effort <effort>`'), rest[0])
        rows = {}
        for row in rest[1:]:
            if not row.startswith('|'):
                break
            cells = [c.strip().strip('`') for c in row.strip().strip('|').split('|')]
            rows[cells[0]] = cells[1]
        self.assertEqual(set(rows) - {'Harness', '---'}, set(HARNESSES))
        for harness in HARNESSES:
            if harness == 'opencode':
                self.assertTrue(rows[harness].startswith("can't ("), rows[harness])
            else:
                self.assertIn('--reasoning-effort <effort>', rows[harness])
        start_row = [x for x in lines if x.startswith('| `start` |')]
        self.assertEqual(len(start_row), 1)
        self.assertIn('[--reasoning-effort <effort>]', start_row[0])
        self.assertNotIn('driver v2 field', '\n'.join(lines))

    def set_state(self, now):
        """Set the newest synthetic sandbox's state, as boat would once the agent's turn has ended."""
        with open(self.env['FAKE_BOAT_STATE']) as f:
            boat = json.load(f)
        boat['sandboxes'][max(boat['sandboxes'])]['state'] = now
        with open(self.env['FAKE_BOAT_STATE'], 'w') as f:
            json.dump(boat, f)

    def test_a_wake_never_resumes_a_stopped_sandbox_and_stop_ends_it(self):
        # catches: a wake that resumes a stopped sandbox (after boat's auto-stop, or a stop whose every local
        # write failed) and runs the builder again, and a stop that leaves the sandbox running on boat.dev.
        code, started = self.driver('start', REQUEST)
        self.assertEqual(code, 0, started)
        boxes = self.sandboxes()
        self.assertEqual(list(boxes.values()), ['running'])
        sid = next(iter(boxes))
        subprocess.run(['boat', 'stop', sid, '--json'], env=self.env, capture_output=True, check=True)
        code, err = self.driver('wake', started)
        self.assertEqual((code, self.sandboxes(), self.notes()), (1, {sid: 'stopped'}, [(1, 'started the throwaway ticket')]))
        self.assertIn('is stopped, not running', err['error'])  # its reason: boat's state, read where boat puts it
        self.assertIn('start a new run', err['next'])
        for _ in range(2):  # stopping a stopped run answers again
            self.assertEqual(self.driver('stop', started), (0, dict(started, stopped=True)))
            self.assertEqual(self.sandboxes(), {sid: 'stopped'})

    def files_holding(self, marker):
        found = []
        for root, _, names in os.walk(self.folder):
            for name in names:
                try:
                    with open(os.path.join(root, name), errors='replace') as f:
                        if marker in f.read():
                            found.append(os.path.join(root, name))
                except OSError:
                    pass
        return found

    def test_a_credential_shaped_start_field_is_refused_before_anything_starts(self):
        args = os.path.join(self.folder, 'boat-args')
        for field, value in (('model', 'sk-' + 'Synthetic0Marker' * 2), ('model', 'token: synthetic0marker'),
                             ('model', 'AKIA' + 'SYNTHETIC0MARK00'), ('repository', TOKEN + '/site'),
                             ('skill', 'sk-synthetic0marker0value00'), ('harness', 'sk-synthetic0marker0value00')):
            with self.subTest(field=field, value=value):
                code, err = self.driver('start', dict(REQUEST, **{field: value}), FAKE_BOAT_ARGS=args)
                self.assertEqual(code, 1, err)
                self.assertIn(field, err['error'])
                self.assertIn('credential', err['error'])
                self.assertNotIn(value, json.dumps(err))
                self.assertFalse(os.path.exists(args), 'boat ran')
                self.assertEqual((self.sandboxes(), self.notes()), ({}, []))
                self.assertEqual(self.files_holding(value), [])

    def test_boat_diagnostics_never_reach_the_drivers_answer(self):
        marker = 'sk-' + 'Synthetic0Host0Marker' + self.mark
        cases = (('new', 'json', 'sign in to boat'), ('new', 'code', 'boat new failed'),
                 ('new', 'stderr', 'sign in to boat'), ('exec', 'json', 'sign in to boat'),
                 ('exec', 'stderr', 'skills'), ('prompt', 'json', 'sign in to boat'),
                 ('prompt', 'stderr', 'sign in to boat'), ('prompt', 'code', 'boat prompt failed'))
        for cmd, how, says in cases:
            with self.subTest(cmd=cmd, how=how):
                code, err = self.driver('start', REQUEST, FAKE_BOAT_LEAK=cmd + ':' + how, FAKE_MARKER=marker)
                self.assertEqual(code, 1, err)
                self.assertNotIn(marker, json.dumps(err))
                self.assertNotIn('Synthetic', json.dumps(err))
                self.assertIn(says, json.dumps(err))
                self.assertNotIn('running', self.sandboxes().values())
        self.assertEqual(self.notes(), [])

    def test_boat_output_never_reaches_a_wake_or_stop_answer(self):
        marker = 'sk-' + 'Synthetic0Host0Marker' + self.mark
        for shape in ('nested', 'flat'):
            with self.subTest(shape=shape):
                code, out = self.driver('start', REQUEST)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])), 'the first turn never ended')
                self.set_state('<b>Synthetic diagnostic</b> ' + marker)
                code, err = self.driver('wake', out, FAKE_BOAT_INFO=shape)
                self.assertEqual(code, 1, err)
                self.assertIn('is unknown, not running', err['error'])
                self.assertNotIn(marker, json.dumps(err))
                self.assertNotIn('Synthetic', json.dumps(err))
                self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        code, err = self.driver('start', REQUEST, FAKE_BOAT_ID=marker)
        self.assertEqual(code, 1, err)
        self.assertNotIn(marker, json.dumps(err))
        self.assertIn('sandbox id', err['error'])

    def test_a_start_that_fails_leaves_no_sandbox_running(self):
        # catches: a sandbox left running (and billing) when the agent can't start, or created for a
        # harness boat doesn't have.
        code, error = self.driver('start', dict(REQUEST, harness='fake-harness'))
        self.assertEqual((code, self.sandboxes()), (1, {}), error)
        self.assertIn('claude, codex', error['next'])
        self.env['FAKE_BOAT_PROVIDERS'] = 'codex'
        code, error = self.driver('start', REQUEST)
        self.assertEqual((code, list(self.sandboxes().values())), (1, ['stopped']), error)
        self.assertIn('provider_not_configured', error['error'])
        self.assertIn('dashboard', error['next'])

    def test_a_first_turn_that_hits_a_usage_limit_or_does_nothing_fails_start(self):
        cases = (('usage_limit:auth_expiry', False, 'hit a usage limit (auth_expiry)'),
                 ('usage_limit_flat:rate_limit', False, 'hit a usage limit (rate_limit)'),
                 ('usage_limit:auth_expiry', True, 'hit a usage limit (auth_expiry)'),
                 ('usage_limit:<b>raw text</b>', False, 'hit a usage limit (unknown)'),
                 ('usage_limit:private_diagnostic', False, 'hit a usage limit (unknown)'),
                 ('no_tools', False, 'finished with no tool call'))
        for turn, held, why in cases:
            with self.subTest(turn=turn, held=held):
                open(self.hold, 'w').close() if held else None
                code, err = self.driver('start', REQUEST, FAKE_TURN=turn)
                self.assertEqual((code, list(self.sandboxes().values())[-1]), (1, 'stopped'), err)
                self.assertIn(why, err['error'])
                run = re.search(r'run-[0-9a-f]{12}', err['error']).group()
                self.assertIn(os.path.join(self.folder, 'state', run + '.0.log'), err['next'])
                for raw in ('Synthetic', 'OAuth', 'raw text', 'private_diagnostic', TOKEN):
                    self.assertNotIn(raw, json.dumps(err))
                self.assertTrue(self.until(lambda: not any(alive(p) or alive(w) for p, w, _, _ in self.logged())),
                                'its turn still runs')
                self.assertEqual(self.driver('wake', {'run': run})[0], 1, 'a wake reopened the failed run')
                os.remove(self.hold) if held else None
        self.assertEqual(self.notes(), [])

    def test_a_working_first_turn_answers_within_the_settle_time(self):
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual((code, list(self.sandboxes().values())), (0, ['running']), out)
        self.assertTrue(alive(self.logged()[0][0]), 'the first turn was ended')
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_a_bad_settle_setting_refuses_start_and_never_blocks_stop(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        for bad in ('two', 'nan', 'inf', '-1', '0', '61'):
            with self.subTest(settle=bad):
                code, err = self.driver('start', REQUEST, OPENWIZ_BOAT_SETTLE=bad)
                self.assertEqual((code, len(self.sandboxes())), (1, 1), err)
                self.assertIn('OPENWIZ_BOAT_SETTLE', err['error'])
        self.assertEqual(self.driver('stop', out, OPENWIZ_BOAT_SETTLE='two'), (0, dict(out, stopped=True)))
        self.assertEqual(list(self.sandboxes().values()), ['stopped'])

    def test_stop_ends_a_worker_the_prompt_left_in_a_clean_environment(self):
        # catches: a stop that signals only the `boat prompt` process group, or finds processes only by the
        # mark they inherit, so a worker the CLI left in its own session keeps running after stop (R2).
        code, out = self.driver('start', REQUEST, FAKE_CLEAN='1')
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1 and not alive(self.logged()[0][0])))
        worker = self.logged()[0][1]
        self.assertTrue(alive(worker))
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
        self.assertFalse(alive(worker), 'a worker the prompt left still runs after stop')

    def test_simultaneous_wakes_start_one_turn(self):
        # catches: two wakes that both pass their checks before either saves its turn, so both run
        # `boat prompt` and two turns work the ticket at once (R1), and a wake during a running turn adding one.
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1 and not alive(self.logged()[0][0])))
        open(self.hold, 'w').close()
        paused, release = os.path.join(self.folder, 'paused'), os.path.join(self.folder, 'release')
        first = subprocess.Popen([self.wrapper('pauses', PAUSES_IN_WAKE), 'wake'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, env=dict(self.env, PAUSED=paused, RELEASE=release))
        first.stdin.write(json.dumps(out).encode())
        first.stdin.close()
        self.assertTrue(self.until(lambda: os.path.exists(paused)), 'the first wake never reached its pause')
        second = subprocess.Popen([DRIVER, 'wake'], stdin=subprocess.PIPE, stdout=subprocess.PIPE, env=self.env)
        second.stdin.write(json.dumps(out).encode())
        second.stdin.close()
        try:  # without a lock the second wake finishes now; with one it waits for the first
            second.wait(3)
        except subprocess.TimeoutExpired:
            pass
        open(release, 'w').close()
        answers = [json.loads(p.stdout.read()) for p in (first, second)]
        self.assertEqual(([p.wait(60) for p in (first, second)], answers), ([0, 0], [dict(out, woke=True)] * 2))
        time.sleep(0.5)  # time for a second turn to log itself, if one was started
        self.assertEqual([t[3] for t in self.logged()], ['first', 'woken'], 'two wakes ran two turns')

    def test_stop_ends_the_run_when_it_cannot_save(self):
        # catches: a stop whose save fails before it ends anything, answering "retry" while the turn and the
        # sandbox keep running, and a wake that then runs another turn (R3).
        open(self.hold, 'w').close()
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        os.mkdir(os.path.join(self.folder, 'state', out['run'] + '.json.new'))
        code, err = self.driver('stop', out)
        self.assertEqual(code, 1, err)
        self.assertNotIn('retry', json.dumps(err))
        self.assertEqual((self.live_descendants_of_this_test(), list(self.sandboxes().values())), ([], ['stopped']), 'stop left it working')
        code, err = self.driver('wake', out)
        self.assertEqual((code, len(self.logged()), self.live_descendants_of_this_test()), (1, 1, []), 'a wake ran it again')

    def test_wake_checks_its_save_before_and_after_spawn(self):
        # catches: a wake that runs `boat prompt` before it knows it can save the turn, and a save failure
        # after it answering "retry" while the unsaved turn keeps working (R4).
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1 and not alive(self.logged()[0][0])))
        blocked = os.path.join(self.folder, 'state', out['run'] + '.json.new')
        os.mkdir(blocked)
        code, err = self.driver('wake', out)
        self.assertEqual((code, len(self.logged())), (1, 1), 'a wake ran a turn with nowhere to save it')
        self.assertIn('nothing was started', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        os.rmdir(blocked)
        open(self.hold, 'w').close()
        before = set(self.live_descendants_of_this_test())
        code, err = self.driver('wake', out, program=self.wrapper('breaks', BREAKS_AFTER_SPAWN))
        self.assertEqual(code, 1, err)
        self.assertIn('unknown', err['error'])
        self.assertNotIn('retry', json.dumps(err))
        self.assertTrue(self.until(lambda: set(self.live_descendants_of_this_test()) <= before), 'the unsaved turn still runs')

    def test_a_start_not_fully_saved_is_never_woken(self):
        # catches: a start whose last save fails after its turn began answering "retry", leaving the turn and
        # the sandbox running, and a wake on the surviving record opening a second conversation (R5).
        code, out = self.driver('start', REQUEST, program=self.wrapper('breaks', BREAKS_AFTER_SPAWN))
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertNotIn('retry', json.dumps(out))
        self.assertTrue(self.until(lambda: not self.live_descendants_of_this_test()), 'the turn it could not save still runs')
        self.assertEqual(list(self.sandboxes().values()), ['stopped'])
        run = re.search(r'run-[0-9a-f]{12}', out['error']).group()
        os.rmdir(os.path.join(self.folder, 'state', run + '.json.new'))
        code, err = self.driver('wake', {'run': run})
        self.assertEqual((code, [t[2] for t in self.logged()]), (1, ['c1']), 'a wake reopened the failed run')
        self.assertIn('never finished starting', err['error'])

    def test_a_failed_stop_is_never_undone_by_a_wake(self):
        # catches: a stop whose save failed leaving the run wakeable, so once storage recovers an ordinary wake
        # resumes the stopped sandbox and runs the builder again before anyone stops it again (#1707); also when
        # both of the stop's writes fail (its record and the lock file's content), and when the lock file is gone.
        # Here `boat stop` fails too, so the sandbox still runs and only the local marks can refuse the wake.
        for block in ('staged-save', 'read-only-folder', 'both-writes'):
            with self.subTest(block=block):
                code, out = self.driver('start', REQUEST)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])))
                state, staged = os.path.join(self.folder, 'state'), os.path.join(self.folder, 'state', out['run'] + '.json.new')
                lock = os.path.join(state, out['run'] + '.lock')
                os.mkdir(staged) if block == 'staged-save' else os.chmod(state, 0o500)
                if block == 'both-writes':
                    os.chmod(lock, 0o400)
                code, err = self.driver('stop', out, FAKE_BOAT_FAIL='stop')
                self.assertEqual(code, 1, err)
                os.rmdir(staged) if block == 'staged-save' else os.chmod(state, 0o700)
                os.chmod(lock, 0o600)
                if block != 'both-writes':
                    os.utime(lock)  # a copy or a restore resets the mtime: the content mark must hold alone
                turns, sandbox = len(self.logged()), self.sandboxes()
                code, err = self.driver('wake', out)
                self.assertEqual((code, len(self.logged()), self.sandboxes()), (1, turns, sandbox), 'a wake undid the stop')
                self.assertIn('stop it again', err['next'])
                self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))
                self.assertEqual(self.driver('wake', out)[0], 1)
        # A read-only filesystem: no mark, no save; the stop still stops the sandbox, so boat refuses the wake.
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])))
        code, err = self.driver('stop', out, program=self.wrapper('fails', RAISES), READ_ONLY='1')
        self.assertEqual((code, list(self.sandboxes().values())[-1]), (1, 'stopped'), err)
        self.assertIn('do not wake it', err['error'])
        turns = len(self.logged())
        self.assertEqual((self.driver('wake', out)[0], len(self.logged())), (1, turns), 'a wake undid the stop')
        code, out = self.driver('start', REQUEST)
        self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])))
        os.remove(os.path.join(self.folder, 'state', out['run'] + '.lock'))
        turns = len(self.logged())
        code, err = self.driver('wake', out)
        self.assertEqual((code, len(self.logged())), (1, turns), 'a wake ran without its lock')
        self.assertIn('lost its lock file', err['error'])

    def test_an_unexpected_error_leaves_nothing_running(self):
        # catches: an error that isn't Refused (a KeyError on the live run) skipping the cleanup once the sandbox
        # exists, leaving the sandbox running with its agent working and the local turn alive (L2), also when
        # `boat info` fails too.
        program = self.wrapper('raises', RAISES)
        for when, fails in (('before', ''), ('after', ''), ('after', 'info')):
            with self.subTest(command='start', when=when, fails=fails):
                code, err = self.driver('start', REQUEST, program=program, RAISE=when, FAKE_BOAT_FAIL=fails)
                self.assertEqual((code, err['error']), (1, 'the driver failed: KeyError'), err)
                self.assertTrue(self.until(lambda: not self.live_descendants_of_this_test()), 'its turn still runs')
                self.assertEqual(set(self.sandboxes().values()), {'stopped'}, 'its sandbox still runs')
        # catches: cleanup that gives up on `boat stop` when Linux denies the driver's signals, or its listing of
        # /proc (L2), in a failed start and in a stop; each failure is reported.
        for deny in ('DENY_SIGNALS', 'DENY_PROC'):
            code, err = self.driver('start', REQUEST, program=program, RAISE='after', **{deny: '1'})
            self.assertEqual((code, list(self.sandboxes().values())[-1]), (1, 'stopped'), err)
            self.assertIn('local processes', err['error'])
            code, out = self.driver('start', REQUEST)
            self.assertEqual(code, 0, out)
            code, err = self.driver('stop', out, program=program, **{deny: '1'})
            self.assertEqual((code, list(self.sandboxes().values())[-1], 'local processes' in err['error']), (1, 'stopped', True), err)
        # catches: a sandbox the driver could not stop going unreported (L2, the outcome).
        code, err = self.driver('start', REQUEST, program=program, RAISE='after', FAKE_BOAT_FAIL='info,stop')
        self.assertEqual(code, 1, err)
        self.assertIn('may still run', err['error'])
        self.assertRegex(err['next'], r'`boat stop bx_fake\d+`')
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: not alive(self.logged()[-1][0])))
        open(self.hold, 'w').close()
        before = set(self.live_descendants_of_this_test())
        code, err = self.driver('wake', out, program=program, RAISE='after')
        self.assertEqual((code, err['error']), (1, 'the driver failed: KeyError'), err)
        self.assertTrue(self.until(lambda: set(self.live_descendants_of_this_test()) <= before), 'the woken turn still runs')

    def test_stop_and_failure_cleanup_never_open_another_process_environment(self):
        seen = os.path.join(self.folder, 'environ-opens')
        program = self.wrapper('audited', RAISES)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1 and not alive(self.logged()[0][0])))
        first_turn_worker = set(self.live_descendants_of_this_test())
        code, err = self.driver('start', REQUEST, program=program, RAISE='after', AUDIT=seen)
        self.assertEqual((code, err['error']), (1, 'the driver failed: KeyError'), err)
        self.assertFalse(os.path.exists(seen), 'a failed start opened another process\'s environment')
        self.assertEqual(list(self.sandboxes().values())[-1], 'stopped')
        self.assertTrue(self.until(lambda: set(self.live_descendants_of_this_test()) <= first_turn_worker),
                        'the failed start\'s turn still runs')
        self.assertEqual(self.driver('stop', out, program=program, AUDIT=seen), (0, dict(out, stopped=True)))
        self.assertFalse(os.path.exists(seen), 'a stop opened another process\'s environment')
        self.assertTrue(self.until(lambda: not self.live_descendants_of_this_test()), 'a turn still runs')

    def test_the_tests_track_only_their_own_processes(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        del ENVIRON_OPENS[:]
        WATCHING.append(1)
        try:
            self.assertTrue(self.live_descendants_of_this_test(), 'the run\'s turn was not found')
            self.tearDown()
            self.assertTrue(self.until(lambda: not self.live_descendants_of_this_test()), 'teardown left a process running')
        finally:
            WATCHING.pop()
        self.assertEqual(ENVIRON_OPENS, [], 'the tests opened another process\'s environment')

    def test_a_start_that_cannot_push_fails_fast_naming_the_fix(self):
        code, err = self.driver('start', REQUEST, FAKE_BOAT_PUSH='denied')
        self.assertEqual((code, err), (1, {
            'error': "the sandbox cannot push to example/site: the GitHub account connected in boat needs write "
                     "access to it",
            'next': "give the GitHub account connected in boat's dashboard write access to example/site, then start "
                    "again"}))
        self.assertEqual((self.logged(), list(self.sandboxes().values())), ([], ['stopped']),
                         'a start that cannot push ran a turn or left its sandbox running')
        for detail in ('synthetic-app', '403', 'Permission', TOKEN, 'bx_fake'):
            self.assertNotIn(detail, json.dumps(err))

    def odd_boat(self):
        folder = os.path.join(self.folder, 'odd-boat')
        os.makedirs(folder, exist_ok=True)
        real = os.path.join(HERE, 'fixtures', 'bin', 'boat')
        with open(os.path.join(folder, 'boat'), 'w') as f:
            f.write('#!%s\n' % sys.executable + ODD_BOAT % (real, real))
        os.chmod(os.path.join(folder, 'boat'), 0o700)
        return folder + os.pathsep + self.env['PATH']

    def test_the_push_refusal_holds_when_the_check_answers_odd_bytes_or_cannot_run(self):
        refusal = (1, {'error': "the sandbox cannot push to example/site: the GitHub account connected in boat needs "
                                "write access to it",
                       'next': "give the GitHub account connected in boat's dashboard write access to example/site, then "
                               "start again"})
        for case, program, env in (('odd bytes', DRIVER, {'PUSH_ANSWER': 'odd', 'PATH': self.odd_boat()}),
                                   ('exec fails', self.wrapper('exec-fails', EXEC_FAILS), {})):
            with self.subTest(case):
                self.assertEqual(self.driver('start', REQUEST, program=program, **env), refusal)
                self.assertEqual(self.logged(), [], 'a start that cannot push ran a turn')
                self.assertNotIn('running', self.sandboxes().values())
        code, out = self.driver('start', REQUEST, PUSH_ANSWER='ok', PATH=self.odd_boat())
        self.assertEqual(code, 0, out)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_known_boat_guidance_reaches_the_answer_from_stderr(self):
        marker = 'sk-' + 'Synthetic0Host0Marker' + self.mark
        path = self.odd_boat()
        for cmd, how, says in (('new', 'code', 'Agents & Proxying'), ('prompt', 'code', 'Agents & Proxying'),
                               ('new', 'mixed', 'sign in to boat'), ('prompt', 'mixed', 'sign in to boat')):
            with self.subTest(cmd=cmd, how=how):
                code, err = self.driver('start', REQUEST, PATH=path, STDERR_FOR=cmd, STDERR_HOW=how, FAKE_MARKER=marker)
                self.assertEqual(code, 1, err)
                self.assertIn(says, err['next'] if how == 'code' else json.dumps(err))
                if how == 'code':
                    self.assertIn('provider_not_configured', err['error'])
                self.assertNotIn(marker, json.dumps(err))
                self.assertNotIn('Synthetic', json.dumps(err))
                self.assertNotIn('running', self.sandboxes().values())

    def test_the_push_refusal_fits_driver_v1_for_the_longest_repository_name(self):
        longest = 'o' * 100 + '/' + 'r' * 100
        code, err = self.driver('start', dict(REQUEST, repository=longest), FAKE_BOAT_PUSH='denied')
        self.assertEqual(code, 1, err)
        for key in ('error', 'next'):
            self.assertLessEqual(len(err[key]), 300, err[key])
            self.assertIn(longest, err[key])
            self.assertIn('write access', err[key])

    def test_a_pushable_repository_starts_after_one_dry_run_push(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        pushes = self.env['FAKE_BOAT_STATE'] + '.homes/bx_fake0001/.fake-github-pushes'
        with open(pushes) if os.path.exists(pushes) else open(os.devnull) as f:
            self.assertEqual(f.read().splitlines(), ['dry-run https://github.com/example/site.git '
                                                     'HEAD:refs/heads/openwiz-push-check-' + out['run']])
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_a_writable_repository_that_has_an_old_probe_branch_starts(self):
        code, out = self.driver('start', REQUEST, FAKE_GITHUB_BRANCHES='openwiz-push-check')
        self.assertEqual(code, 0, out)
        self.assertEqual(self.driver('stop', out), (0, dict(out, stopped=True)))

    def test_the_kits_start_check_names_the_push_fix(self):
        p = subprocess.run([sys.executable, '-I', KIT, '--driver', DRIVER, '--repo', 'example/site',
                            '--ticket', '7', '--harness', 'claude', '--model', 'claude-opus-5-5',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=dict(self.env, FAKE_BOAT_PUSH='denied'), capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()[1]), (1, "fail start: the sandbox cannot push to "
                         "example/site: the GitHub account connected in boat needs write access to it"), p.stderr)

    def test_start_installs_the_pinned_skills_or_refuses(self):
        # catches: a sandbox without the pinned WizSkills skills, so its agent can't follow the skill or post
        # its note (L4, live run 3); a release whose commit isn't the lock's installed anyway; an existing
        # different skill entry overwritten; and a failed install leaving the sandbox running.
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        home = self.env['FAKE_BOAT_STATE'] + '.homes/bx_fake0001'
        for root in ('.claude', '.agents'):
            self.assertTrue(os.path.islink(os.path.join(home, root, 'skills', 'build-ticket')), 'no skill in the sandbox')
            self.assertEqual(os.readlink(os.path.join(home, root, 'skills', 'build-ticket')),
                             os.path.join(home, 'wizskills', 'skills', 'build-ticket'))
        os.makedirs(self.env['FAKE_BOAT_STATE'] + '.homes/bx_fake0003/.claude/skills/build-ticket')
        for case, env in (('moved tag', {'FAKE_WIZ_COMMIT': '0' * 40}), ('existing entry', {}),
                          ('another commit, same tree', {'FAKE_WIZ_COMMIT': '3' * 40, 'FAKE_WIZ_SAME_TREE': '1'})):
            with self.subTest(case=case):
                turns = len(self.logged())
                code, err = self.driver('start', REQUEST, **env)
                self.assertEqual((code, len(self.logged())), (1, turns), err)
                self.assertIn('skills', err['error'])
                self.assertEqual(list(self.sandboxes().values())[-1], 'stopped')
        # catches: the installer fetching the tag again, after it moved, and that unverified release linked.
        code, out = self.driver('start', REQUEST, FAKE_WIZ_COMMIT='moved')
        with open(os.path.join(HERE, '..', '..', 'wizskills.lock')) as f, \
                open(self.env['FAKE_BOAT_STATE'] + '.homes/bx_fake0005/wizskills/.git/fake.json') as g:
            self.assertEqual((code, json.load(g)['commit']), (0, json.load(f)['commit']), out)


    def test_on_macos_the_driver_never_asks_ps_for_any_process_environment(self):
        calls = os.path.join(self.folder, 'ps-calls')
        logging_ps = os.path.join(self.folder, 'logging-ps')
        os.mkdir(logging_ps)
        with open(os.path.join(logging_ps, 'ps'), 'w') as f:
            f.write('#!/bin/sh\nprintf \'%%s\\n\' "$*" >> %s\nexec %s "$@"\n' % (calls, os.path.join(NO_PROC, 'ps')))
        os.chmod(os.path.join(logging_ps, 'ps'), 0o700)
        macos = {'PATH': logging_ps + os.pathsep + NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.driver('start', REQUEST, **macos)
        self.assertEqual(code, 0, out)
        self.assertEqual(self.driver('stop', out, **macos), (0, dict(out, stopped=True)))
        with open(calls) as f:
            asked = f.read().splitlines()
        self.assertTrue(any(' -A ' in ' %s ' % c for c in asked), 'the driver never listed processes through ps')
        self.assertEqual([c for c in asked if '-E' in c.split() or 'e' in c.split()], [],
                         'the driver asked ps for process environments')

    def test_without_proc_as_on_macos_stop_ends_a_worker_writing_the_log_after_its_supervisor_is_gone(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.driver('start', REQUEST, **macos)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        prompt_pid, worker_pid = self.logged()[0][:2]
        self.assertTrue(self.until(lambda: not alive(prompt_pid)))
        with open(os.path.join(self.env['OPENWIZ_BOAT_STATE'], out['run'] + '.json')) as f:
            supervisor = json.load(f)['turns'][0]['supervisor']
        os.kill(supervisor, signal.SIGKILL)
        self.assertTrue(self.until(lambda: not alive(supervisor)))
        self.assertTrue(alive(worker_pid))
        self.assertEqual(self.driver('stop', out, **macos), (0, dict(out, stopped=True)))
        self.assertFalse(alive(worker_pid), 'a worker writing the turn log still runs after stop')

    def test_without_proc_as_on_macos_a_failed_wake_ends_only_its_own_turn(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.driver('start', REQUEST, **macos)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        prompt_pid, earlier = self.logged()[0][:2]
        self.assertTrue(self.until(lambda: not alive(prompt_pid)))
        code, woke = self.driver('wake', out, FAKE_RESUME_FAILS='1', **macos)
        self.assertEqual(code, 1, woke)
        failed = self.logged()[1][1]
        self.assertFalse(alive(failed), "the failed wake's worker still runs")
        self.assertTrue(alive(earlier), "the failed wake ended an earlier turn's worker")
        self.assertEqual(self.driver('stop', out, **macos), (0, dict(out, stopped=True)))
        self.assertFalse(alive(earlier))

    def test_without_proc_as_on_macos_a_wake_that_cannot_save_ends_only_its_own_turn(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.driver('start', REQUEST, **macos)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        prompt_pid, earlier = self.logged()[0][:2]
        self.assertTrue(self.until(lambda: not alive(prompt_pid)))
        breaks = os.path.join(self.folder, 'breaks-without-proc')
        with open(breaks, 'w') as f:
            f.write('#!/usr/bin/env python3\n' + BREAKS_AFTER_SPAWN % DRIVER)
        os.chmod(breaks, 0o700)
        code, err = self.driver('wake', out, program=breaks, **macos)
        self.assertEqual(code, 1, err)
        self.assertIn('could not save', err['error'])
        self.assertTrue(self.until(lambda: len(self.logged()) == 2))
        failed = self.logged()[1][1]
        self.assertTrue(self.until(lambda: not alive(failed)), "the failed wake's worker still runs")
        self.assertTrue(alive(earlier), "the failed wake ended an earlier turn's worker")
        os.rmdir(os.path.join(self.env['OPENWIZ_BOAT_STATE'], out['run'] + '.json.new'))
        self.assertEqual(self.driver('stop', out, **macos), (0, dict(out, stopped=True)))
        self.assertFalse(alive(earlier))

    def test_without_proc_as_on_macos_stop_ends_a_worker_the_turn_hands_off_as_it_exits(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        code, out = self.driver('start', REQUEST, FAKE_LATE_WORKER='0.7', **macos)
        self.assertEqual(code, 0, out)
        self.assertTrue(self.until(lambda: len(self.logged()) == 1))
        prompt_pid, worker_pid = self.logged()[0][:2]
        self.assertTrue(self.until(lambda: not alive(prompt_pid)))
        time.sleep(1)
        self.assertTrue(alive(worker_pid))
        self.assertEqual(self.driver('stop', out, **macos), (0, dict(out, stopped=True)))
        self.assertFalse(alive(worker_pid), 'a worker the turn handed off as it exited still runs after stop')

    def test_without_proc_as_on_macos_the_kit_passes_and_stop_ends_each_grandchild(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        for worker in ({'FAKE_DAEMON': '1'}, {'FAKE_CLEAN': '1', 'FAKE_SAME_GROUP': '1'}):
            with self.subTest(**worker):
                self.tearDown()
                self.setUp()
                macos['PATH'] = NO_PROC + os.pathsep + self.env['PATH']
                detached = 'FAKE_DAEMON' in worker
                if detached:
                    open(self.hold, 'w').close()
                code, out = self.driver('start', REQUEST, **macos, **worker)
                self.assertEqual(code, 0, out)
                self.assertTrue(self.until(lambda: len(self.logged()) == 1))
                worker_pid = self.logged()[0][1]
                if detached:
                    self.assertTrue(self.until(lambda: worker_pid in self.recorded_by_supervisors(out['run'])),
                                    'the supervisor never recorded the detached worker')
                    os.remove(self.hold)
                self.assertTrue(self.until(lambda: not alive(self.logged()[0][0])))
                self.assertTrue(alive(worker_pid))
                self.assertEqual(self.driver('stop', out, **macos), (0, dict(out, stopped=True)))
                self.assertFalse(alive(worker_pid), 'a worker the prompt left still runs after stop')

        self.tearDown()
        self.setUp()
        macos['PATH'] = NO_PROC + os.pathsep + self.env['PATH']
        p = subprocess.run([os.path.join(NO_PROC, 'python3'), '-I', KIT, '--driver', DRIVER, '--repo', 'example/site',
                            '--ticket', '7', '--harness', 'claude', '--model', 'claude-opus-5-5',
                            '--tracker', self.tracker, '--wait', '8'],
                           env=dict(self.env, **macos), capture_output=True, text=True, timeout=300)
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver']), p.stderr)

if __name__ == '__main__':
    unittest.main()
