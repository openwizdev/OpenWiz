#!/usr/bin/env python3
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT_DIR = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
KIT = os.path.join(KIT_DIR, 'kit.py')
with open(os.path.join(KIT_DIR, 'hosts.json')) as _f:
    ENTRY = json.load(_f).get('conductor', {})
VARIABLE = ENTRY.get('variable', 'unregistered')
NEVER_READS_THE_KEY = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
variable = os.environ.pop('GUARDED_VARIABLE')
for name in ('__getitem__', 'get', '__contains__', 'pop', 'copy', 'items', 'values'):
    real = getattr(os._Environ, name)
    def guarded(self, *args, _real=real, _name=name):
        if _name in ('items', 'values', 'copy') or (args and args[0] in (variable, variable.encode())):
            raise AssertionError('the driver touched the key variable through os.environ.' + _name)
        return _real(self, *args)
    setattr(os._Environ, name, guarded)
spec = importlib.util.spec_from_loader('conductor', importlib.machinery.SourceFileLoader('conductor', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
t.main()
'''
SCOPED_KIT = '''import builtins, ctypes, importlib.machinery, importlib.util, os, re, sys
sys.dont_write_bytecode = True
if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
    sys.exit('the scoped kit cannot become a subreaper')
listdir, real_open, opened = os.listdir, builtins.open, os.environ.get('SCOPED_KIT_OPENED')
def ours():
    children = {}
    for p in filter(str.isdigit, listdir('/proc')):
        try:
            with real_open('/proc/%%s/stat' %% p) as f:
                children.setdefault(int(f.read().rpartition(')')[2].split()[1]), []).append(p)
        except (OSError, IndexError, ValueError):
            pass
    found, todo = [], [os.getpid()]
    while todo:
        for c in children.get(todo.pop(), []):
            found.append(c)
            todo.append(int(c))
    return found
os.listdir = lambda path='.': ours() if path == '/proc' else listdir(path)
def logged_open(path, *args, **kwargs):
    m = isinstance(path, str) and re.fullmatch(r'/proc/([0-9]+)/environ', path)
    if m and opened:
        with real_open(opened, 'a') as f:
            f.write(m.group(1) + '\\n')
    return real_open(path, *args, **kwargs)
builtins.open = logged_open
spec = importlib.util.spec_from_loader('kit', importlib.machinery.SourceFileLoader('kit', %r))
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)
sys.exit(kit.main(sys.argv[1:]))
'''
LEAVES_A_WORKER = '''#!%s -I
import os, subprocess, sys
driver = %r
if sys.argv[1:] != ['start']:
    os.execv(driver, [driver] + sys.argv[1:])
start = subprocess.run([driver, 'start'])
if start.returncode == 0 and os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        with open(%r, 'a') as f:
            f.write('%%d\\n' %% os.getpid())
        os.execv(sys.executable, [sys.executable, '-c', 'import time; time.sleep(30)'])
    os._exit(0)
sys.exit(start.returncode)
'''
FLEET_CALLER = '''import importlib.util, json, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('host', os.path.realpath(%r))
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)
host.BACKOFF, host.DRIVER_ENV = (0, 0), dict(os.environ)
command, given = sys.argv[1], json.loads(sys.argv[2])
try:
    out = {'can': host.can('conductor')} if command == 'version' else {'run': host.tried('conductor', command, given)}
except host.Refused as e:
    out = {'refused': [e.error, e.next]}
except host.Outcome as e:
    out = {'unknown': str(e)}
print(json.dumps(out))
'''
CALLER = os.path.join(HERE, '..', '..', 'skills', 'launch-fleet', 'scripts', 'host.py')
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'opus-5-5-1m'}
CANT_SET_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster "
                   "to run it at the host's default")
# External: the levels Conductor's workspace create takes for every model of each agent, in its OpenAPI document
# /v0/openapi.json, https://www.conductor.build/docs/api
EFFORTS = {'claude': ['low', 'medium', 'high', 'xhigh', 'max'], 'codex': ['none', 'low', 'medium', 'high', 'xhigh'],
           'cursor': ['low', 'medium', 'high', 'xhigh']}


class Conductor(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.log, self.host = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'conductor.json')
        self.faults, self.key_file = os.path.join(self.folder, 'faults.json'), os.path.join(self.folder, 'key')
        self.fault({})
        open(self.log, 'w').close()
        self.key = 'syn-test-key-' + secrets.token_hex(12)
        with open(self.key_file, 'w') as f:
            f.write(self.key)
        tools = os.path.join(self.folder, 'bin')
        os.mkdir(tools)
        os.symlink(sys.executable, os.path.join(tools, 'python3'))
        for real in ('claude', 'codex', 'cursor', 'cursor-agent', 'conductor', 'curl'):
            self.assertIsNone(shutil.which(real, path=tools), 'a real %s is reachable from the tests' % real)
        fake = subprocess.Popen([sys.executable, '-I', os.path.join(HERE, 'fixtures', 'fake-conductor'),
                                 self.tracker, self.log, self.faults, self.key_file, self.host],
                                stdout=subprocess.PIPE, text=True, env={'PATH': tools, 'LANG': 'C.UTF-8'})
        self.addCleanup(fake.stdout.close)
        self.addCleanup(fake.wait)
        self.addCleanup(fake.kill)
        self.env = dict(KIT_TRACKER=self.tracker, OPENWIZ_CONDUCTOR_STATE=os.path.join(self.folder, 'state'),
                        OPENWIZ_HOSTKEY_TEST_ORIGIN=fake.stdout.readline().strip(),
                        PATH=tools, HOME=self.folder, LANG='C.UTF-8')

    def fault(self, faults):
        with open(self.faults, 'w') as f:
            json.dump(faults, f)

    def driver(self, cmd, request=None, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request) if request is not None else '',
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=120)
        self.assertNotIn(self.key, p.stdout + p.stderr, 'the driver printed the key')
        return p.returncode, json.loads(p.stdout)

    def calls(self):
        with open(self.log) as f:
            logged = [json.loads(line) for line in f]
        return [(c['method'], c['path']) for c in logged], {c['authorization'] for c in logged}

    def workspaces(self):
        with open(self.host) as f:
            return json.load(f)['workspaces']

    def sessions(self):
        with open(self.host) as f:
            return json.load(f)['sessions']

    def bodies(self):
        with open(self.log) as f:
            return [c['body'] for c in map(json.loads, f) if c['path'] == '/v0/workspaces']

    def caller(self, command, given):
        self.assertTrue(os.path.isfile(CALLER), 'Install the pinned WizSkills first: tools/wizskills/install.py')
        script = os.path.join(self.folder, 'fleet-caller')
        with open(script, 'w') as f:
            f.write(FLEET_CALLER % CALLER)
        p = subprocess.run([sys.executable, '-I', script, command, json.dumps(given)], capture_output=True, text=True,
                           timeout=300, env=dict(self.env, OPENWIZ_ADAPTERS=os.path.dirname(HERE)))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def kit(self, driver, wait, **env):
        scoped = os.path.join(self.folder, 'scoped-kit')
        with open(scoped, 'w') as f:
            f.write(SCOPED_KIT % KIT)
        return subprocess.run([sys.executable, '-I', scoped, '--driver', driver, '--repo', 'example/site',
                               '--ticket', '7', '--harness', 'claude', '--model', 'opus-5-5-1m',
                               '--tracker', self.tracker, '--wait', str(wait)],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=300)

    def test_the_key_reaches_conductor_only_through_the_helper(self):
        self.assertEqual((ENTRY.get('origin'), ENTRY.get('keychain')),
                         ('https://api.conductor.build', 'openwiz-conductor'), 'conductor is not in hosts.json')
        named = []
        for folder, _, names in os.walk(HERE):
            for n in names:
                path = os.path.join(folder, n)
                with open(path, 'rb') as f:
                    lines = f.read().split(b'\n')
                for line in lines:
                    exempt = n == 'README.md' and folder == HERE and ENTRY['keychain'].encode() in line
                    if VARIABLE.encode() in line and not exempt:
                        named.append(os.path.relpath(path, HERE))
        self.assertEqual(sorted(set(named)), [], 'these files name the key variable')
        with open(DRIVER) as f:
            self.assertFalse(ENTRY['origin'].split('//')[1] in f.read(), 'the driver picks the address itself')
        guarded = os.path.join(self.folder, 'guarded')
        with open(guarded, 'w') as f:
            f.write(NEVER_READS_THE_KEY % DRIVER)
        other = 'syn-other-key-' + secrets.token_hex(12)
        run = None
        for cmd in ('start', 'wake', 'stop'):
            p = subprocess.run([sys.executable, '-I', guarded, cmd], input=json.dumps(
                REQUEST if cmd == 'start' else {'run': run}), capture_output=True, text=True, timeout=120,
                env=dict(self.env, GUARDED_VARIABLE=VARIABLE, **{VARIABLE: other}))
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertNotIn(other, p.stdout + p.stderr)
            run = run or json.loads(p.stdout)['run']
        calls, bearers = self.calls()
        self.assertEqual(len(calls), 4)
        self.assertEqual(bearers, {'Bearer ' + self.key}, 'a call did not carry the helper\'s key')
        with open(self.log) as f:
            self.assertNotIn(other, f.read())

    def test_the_kit_passes_all_five(self):
        opened = os.path.join(self.folder, 'opened')
        outside = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], env={'OUTSIDE': 'x'})
        try:
            p = self.kit(DRIVER, 20, SCOPED_KIT_OPENED=opened)
        finally:
            outside.kill()
            outside.wait()
        self.assertEqual((p.returncode, p.stdout.splitlines()), (0, [
            'pass version: openwiz:records v1, and the schema is driver v1',
            'pass start: the run posted builder status note 1; effort: medium reached the kit\'s fake conductor host',
            'pass wake: the run edited builder status note 1',
            'pass stop: the run ended, and a wake after it is refused',
            'pass token: no login or token passed through the driver, and on start, wake and stop the conductor key '
            'reached its host only from the key helper, in its header']), p.stderr)
        with open(opened) if os.path.exists(opened) else open(os.devnull) as f:
            self.assertNotIn(str(outside.pid), f.read().split(), 'the kit read a process outside its run')

    def test_the_scoped_kit_still_sees_a_process_the_run_leaves(self):
        worker, wrapped = os.path.join(self.folder, 'worker'), os.path.join(self.folder, 'wrapped')
        os.mkdir(wrapped)
        for name in ('README.md', 'fixtures'):
            os.symlink(os.path.join(HERE, name), os.path.join(wrapped, name))
        leaves = os.path.join(wrapped, 'leaves-a-worker')
        with open(leaves, 'w') as f:
            f.write(LEAVES_A_WORKER % (sys.executable, DRIVER, worker))
        os.chmod(leaves, 0o700)
        try:
            p = self.kit(leaves, 3)
        finally:
            with open(worker) as f:
                pids = [int(line) for line in f]
            for pid in pids:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
        self.assertIn('fail start: effort: a process the start with effort began still runs', p.stdout,
                      p.stdout + p.stderr)

    def test_start_wake_and_stop_reach_one_workspace(self):
        model = 'example/provider/opus-5-5-1m'
        code, out = self.driver('start', dict(REQUEST, model=model))
        self.assertEqual(code, 0, out)
        run = out['run']
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.calls()[0], [
            ('POST', '/v0/workspaces'), ('POST', '/v0/sessions/se_fake0001/messages'),
            ('POST', '/v0/sessions/se_fake0001/cancel'), ('POST', '/v0/workspaces/ws_fake0001/archive')])
        with open(self.log) as f:
            self.assertEqual(json.loads(next(f))['body']['model'], model)
        self.assertEqual(self.workspaces()['ws_fake0001'], {
            'name': 'openwiz-' + run, 'repositoryUrl': 'https://github.com/example/site', 'agent': 'claude',
            'status': 'archived'})
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        code, out = self.driver('wake', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertEqual(len(self.calls()[0]), 4, 'a stopped run called Conductor again')

    def test_a_lost_start_reply_is_never_retried(self):
        for n, fault in enumerate(({'lose': True}, {'status': 503}, {'status': 408}), 1):
            with self.subTest(fault=fault):
                self.fault({'POST /v0/workspaces': fault})
                code, out = self.driver('start', dict(REQUEST, ticket=n))
                self.assertEqual(code, 1, out)
                self.assertIn('outcome is unknown', out['error'])
                self.assertIn('openwiz-run-', out['next'], 'it names no workspace to look for')
                self.assertEqual(self.calls()[0], [('POST', '/v0/workspaces')] * n, 'a start was sent again')

    def test_a_refused_start_starts_nothing_and_says_what_to_do(self):
        for faults, word in (({'POST /v0/workspaces': {'status': 400}}, 'planted failure'),
                             ({'serve': 'syn-wrong-key-' + secrets.token_hex(8)}, 'refused the key (401)')):
            with self.subTest(word):
                self.fault(faults)
                code, out = self.driver('start', REQUEST)
                self.assertEqual(code, 1, out)
                self.assertIn('nothing was started', out['error'])
                self.assertIn(word, out['error'])
                self.assertNotIn('outcome is unknown', out['error'])
        self.assertFalse(os.path.exists(self.host) and self.workspaces(), 'a refused start made a workspace')
        self.fault({'serve': ''})
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 1, out)
        self.assertTrue(out['error'].startswith("the key helper refused: the kit's fake host gave no test key"), out)
        self.assertIn('nothing was started', out['error'])
        self.assertEqual(len(self.calls()[0]), 2, 'a start without a key reached Conductor')

    def test_a_start_the_helper_refuses_leaves_no_input_in_run_state(self):
        for field in ('model', 'repository'):
            with self.subTest(field):
                pasted = self.key if field == 'model' else 'example/' + self.key
                code, out = self.driver('start', dict(REQUEST, **{field: pasted}))
                self.assertEqual(code, 1, out)
                self.assertIn('the request holds the key', out['error'])
                self.assertIn('nothing was started', out['error'])
        state = self.env['OPENWIZ_CONDUCTOR_STATE']
        for name in os.listdir(state) if os.path.isdir(state) else []:
            with open(os.path.join(state, name), 'rb') as f:
                self.assertNotIn(self.key.encode(), f.read(), 'run state %s holds the key' % name)
        self.assertEqual(self.calls()[0], [], 'a start holding the key reached Conductor')

    def test_nothing_is_called_without_a_harness_or_a_state_folder(self):
        blocker = os.path.join(self.folder, 'a-file')
        open(blocker, 'w').close()
        for name, env, request in (('unknown harness', {}, dict(REQUEST, harness='pi')),
                                   ('no state folder', {'OPENWIZ_CONDUCTOR_STATE': blocker}, REQUEST),
                                   ('an effort that is not a word', {}, dict(REQUEST, effort='High'))):
            with self.subTest(name):
                code, out = self.driver('start', request, **env)
                self.assertEqual(code, 1, out)
                self.assertIn('nothing was started' if name != 'an effort that is not a word' else 'effort is not '
                              'valid', out['error'])
        self.assertEqual(self.calls()[0], [])

    def test_an_effort_conductor_takes_reaches_it_and_any_other_is_refused(self):
        self.assertIn('effort', self.driver('version')[1]['can'])
        self.assertIn('effort', self.caller('version', {})['can'], 'the fleet caller sees no effort in can')
        sent = []
        for harness, levels in EFFORTS.items():
            for level in levels:
                with self.subTest(harness=harness, effort=level):
                    code, out = self.driver('start', dict(REQUEST, harness=harness, effort=level))
                    self.assertEqual(code, 0, out)
                    sent.append(level)
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        self.assertEqual([b.get('effort') for b in self.bodies()], sent + [None], 'an effort was not sent as given')
        before = len(self.calls()[0])
        for harness, level, named in (('claude', 'ultracode', 'harness claude at effort ultracode'),
                                      ('claude', 'none', 'harness claude at effort none'),
                                      ('codex', 'max', 'harness codex at effort max'),
                                      ('codex', 'ultra', 'harness codex at effort ultra'),
                                      ('cursor', 'max', 'harness cursor at effort max'),
                                      ('cursor', 'none', 'harness cursor at effort none'),
                                      ('pi', 'high', 'that harness at effort high'),
                                      ('claude', 'minimal', 'harness claude at that effort')):
            with self.subTest(harness=harness, effort=level):
                code, out = self.driver('start', dict(REQUEST, harness=harness, effort=level))
                self.assertEqual((code, out['next']), (1, CANT_SET_EFFORT), out)
                self.assertIn(named, out['error'])
                self.assertIn('nothing was started', out['error'])
        self.assertEqual(len(self.calls()[0]), before, 'a refused effort reached Conductor')
        with open(os.path.join(HERE, 'README.md')) as f:
            lines = f.read().splitlines()
        login = lines.index('Login: held by Conductor')
        self.assertEqual((lines[login + 1], lines[login + 2][:18]), ('', 'Effort: passed as '))
        for harness, levels in EFFORTS.items():
            self.assertIn('| `%s` | `effort`, for %s and %s |' % (harness, ', '.join(levels[:-1]), levels[-1]), lines)

    def test_an_effort_refusal_never_repeats_a_value_it_was_sent(self):
        marker = self.key[:20]
        for name, request in (('harness', dict(REQUEST, harness=self.key, effort='high')),
                              ('effort', dict(REQUEST, effort=marker)),
                              ('both', dict(REQUEST, harness=self.key, effort=marker))):
            with self.subTest(name):
                p = subprocess.run([DRIVER, 'start'], input=json.dumps(request), env=self.env, capture_output=True,
                                   text=True, timeout=120)
                self.assertNotIn(marker, p.stdout + p.stderr, 'the effort refusal repeated a pasted key')
                out = json.loads(p.stdout)
                self.assertEqual((p.returncode, out['next']), (1, CANT_SET_EFFORT), out)
                self.assertIn('nothing was started', out['error'])
        self.assertEqual(self.calls()[0], [], 'a refused effort reached Conductor')

    def test_the_fleet_caller_sends_one_create_when_the_answer_is_lost(self):
        for n, fault in enumerate(({'lose': True}, {'status': 503}, {'status': 408}), 1):
            with self.subTest(fault=fault):
                self.fault({'POST /v0/workspaces': fault})
                given = dict(REQUEST, ticket=n)
                out = self.caller('start', given)
                self.assertIn('refused', out, out)
                self.assertRegex(out['refused'][0], 'outcome is (still )?unknown')
                self.assertIn('openwiz-run-', out['refused'][1], 'it names no workspace to look for')
                self.assertEqual(self.calls()[0], [('POST', '/v0/workspaces')] * n, 'the caller sent the create again')
                self.fault({})
                code, again = self.driver('start', given)
                self.assertEqual(code, 1, again)
                self.assertIn('outcome is still unknown', again['error'])
                self.assertIn('nothing was sent', again['error'])
                self.assertEqual(len(self.calls()[0]), n, 'a start with an unknown outcome was sent again')
        self.assertEqual(len(self.workspaces()), 1, 'a lost create made more than one workspace')
        self.assertEqual(self.driver('start', dict(REQUEST, ticket=9))[0], 0, 'another ticket is held back too')
        run = re.search('run-[0-9a-f]{12}', again['error']).group(0)
        code, out = self.driver('stop', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertIn('openwiz-' + run, out['next'])
        self.assertEqual(self.driver('start', dict(REQUEST, ticket=3))[0], 0, 'a stopped run still holds its start')

    def test_the_fleet_caller_sends_one_wake_when_the_answer_is_lost(self):
        for n, fault in enumerate(({'lose': True}, {'status': 503}, {'status': 408}), 1):
            with self.subTest(fault=fault):
                self.fault({})
                code, started = self.driver('start', dict(REQUEST, ticket=n))
                self.assertEqual(code, 0, started)
                run, sid = started['run'], 'se_fake%04d' % n
                before = [c for c in self.calls()[0] if c[1].endswith('/messages')]
                self.fault({'POST /v0/sessions/{id}/messages': fault})
                out = self.caller('wake', {'run': run})
                self.assertIn('refused', out, out)
                self.assertRegex(out['refused'][0], 'outcome is (still )?unknown')
                self.assertIn('read the ticket', out['refused'][1])
                self.assertIn(run, out['refused'][1])
                after = [c for c in self.calls()[0] if c[1].endswith('/messages')]
                self.assertEqual(len(after) - len(before), 1, 'the caller sent the wake again')
                if fault.get('lose'):
                    self.assertEqual(self.sessions()[sid]['messages'], 2, 'a lost wake delivered more than one message')
                self.fault({})
                code, again = self.driver('wake', {'run': run})
                self.assertEqual(code, 1, again)
                self.assertIn('outcome is still unknown', again['error'])
                self.assertIn('nothing was sent', again['error'])
                self.assertEqual(len([c for c in self.calls()[0] if c[1].endswith('/messages')]), len(after))
                self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        code, started = self.driver('start', dict(REQUEST, ticket=9))
        self.assertEqual(code, 0, started)
        run = started['run']
        self.fault({'POST /v0/sessions/{id}/messages': {'status': 400}})
        self.assertEqual(self.driver('wake', {'run': run})[0], 1)
        self.fault({})
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))

    def test_a_stop_conductor_does_not_confirm_never_says_the_run_stopped(self):
        run = self.driver('start', REQUEST)[1]['run']
        self.fault({'POST /v0/sessions/{id}/cancel': {'status': 503},
                    'POST /v0/workspaces/{id}/archive': {'status': 503}})
        code, out = self.driver('stop', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertNotIn('is stopped', out['error'])
        self.assertIn('may still be working', out['error'])
        self.assertIn('ws_fake0001', out['next'])
        self.assertEqual((self.sessions()['se_fake0001']['status'], self.workspaces()['ws_fake0001']['status']),
                         ('working', 'ready'))
        self.fault({})
        code, out = self.driver('wake', {'run': run})
        self.assertEqual(code, 1, 'a run whose stop is pending was woken')
        self.assertNotIn('is stopped', out['error'])
        self.assertIn('may still be working', out['error'])
        self.assertNotIn(('POST', '/v0/sessions/se_fake0001/messages'), self.calls()[0])
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.workspaces()['ws_fake0001']['status'], 'archived')

    def test_the_readme_revokes_the_key_at_conductor_before_the_local_copy(self):
        with open(os.path.join(HERE, 'README.md')) as f:
            line = next(x for x in f.read().splitlines() if 'revoke' in x.lower())
        self.assertIn("Conductor's API keys page", line)
        self.assertLess(line.index('API keys page'), line.index('keychain'), 'it removes the local copy first')

    def test_a_failed_archive_says_so_and_the_run_stays_stopped(self):
        run = self.driver('start', REQUEST)[1]['run']
        self.fault({'POST /v0/workspaces/{id}/archive': {'status': 500}})
        code, out = self.driver('stop', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertIn('ws_fake0001', out['next'], 'it names no workspace to archive by hand')
        self.assertNotIn('is stopped', out['error'], 'it says a run whose workspace still runs is stopped')
        self.assertEqual(self.workspaces()['ws_fake0001']['status'], 'ready')
        self.fault({})
        code, out = self.driver('wake', {'run': run})
        self.assertEqual(code, 1, 'a run whose stop began was woken')
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.workspaces()['ws_fake0001']['status'], 'archived')


if __name__ == '__main__':
    unittest.main(verbosity=2)
