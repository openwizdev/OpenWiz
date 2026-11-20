#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'kit.py')
KEY = 'sk-' + 'Synthetic0Conductor0Value' * 2
NEVER_READS_THE_KEY = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
fetch = os._Environ.__getitem__
def guarded(self, name):
    if name in ('CONDUCTOR_API_KEY', b'CONDUCTOR_API_KEY'):
        raise AssertionError('the driver fetched the key')
    return fetch(self, name)
os._Environ.__getitem__ = guarded
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
import os, sys
if sys.argv[1:] == ['start'] and os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):
            os.dup2(null, fd)
        with open(%r, 'w') as f:
            f.write(str(os.getpid()))
        os.execv(sys.executable, [sys.executable, '-c', 'import time; time.sleep(30)'])
    os._exit(0)
os.execv(%r, [%r] + sys.argv[1:])
'''
KNOBS = {'OPENWIZ_KIT_RUN', 'SCOPED_KIT_OPENED', 'FAKE_CONDUCTOR_FAIL', 'FAKE_CONDUCTOR_LOSE', 'FAKE_CURL_VERSION'}
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'opus-5-5-1m'}


class Conductor(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': []}, f)
        self.log, self.host = os.path.join(self.folder, 'calls'), os.path.join(self.folder, 'conductor.json')
        tools = os.path.join(self.folder, 'bin')
        os.mkdir(tools)
        os.symlink(sys.executable, os.path.join(tools, 'python3'))
        path = os.path.join(HERE, 'fixtures', 'bin') + os.pathsep + tools
        for real in ('claude', 'codex', 'cursor', 'conductor'):
            self.assertIsNone(shutil.which(real, path=path), 'a real %s is reachable from the tests' % real)
        self.assertEqual(shutil.which('curl', path=path), os.path.join(HERE, 'fixtures', 'bin', 'curl'))
        self.env = dict(KIT_TRACKER=self.tracker, CONDUCTOR_API_KEY=KEY, FAKE_CONDUCTOR_KEY=KEY,
                        FAKE_CONDUCTOR_STATE=self.host, FAKE_CONDUCTOR_LOG=self.log,
                        OPENWIZ_CONDUCTOR_STATE=os.path.join(self.folder, 'state'),
                        PATH=path, HOME=self.folder, LANG='C.UTF-8')

    def driver(self, cmd, request=None, **env):
        p = subprocess.run([DRIVER, cmd], input=json.dumps(request) if request is not None else '',
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=60)
        self.assertNotIn(KEY, p.stdout + p.stderr, 'the driver printed the key')
        return p.returncode, json.loads(p.stdout)

    def calls(self):
        try:
            with open(self.log) as f:
                logged = [json.loads(line) for line in f]
        except FileNotFoundError:
            return []
        for c in logged:
            self.assertNotIn(KEY, ' '.join(c['args']), 'the key was on a command line')
            self.assertEqual(c['key_in'], ['CONDUCTOR_API_KEY', 'FAKE_CONDUCTOR_KEY'],
                             'curl got the key in a variable the test never gave it')
            self.assertLessEqual(set(c['env']), set(self.env) | KNOBS,
                                 'curl ran with a variable the test never gave it')
        return [(c['args'][5], c['args'][-1].split('.build', 1)[1]) for c in logged if c['args'][-1] != '--version']

    def workspaces(self):
        with open(self.host) as f:
            return json.load(f)['workspaces']

    def kit(self, driver, wait, **env):
        scoped = os.path.join(self.folder, 'scoped-kit')
        with open(scoped, 'w') as f:
            f.write(SCOPED_KIT % KIT)
        return subprocess.run([sys.executable, '-I', scoped, '--driver', driver, '--repo', 'example/site',
                               '--ticket', '7', '--harness', 'claude', '--model', 'opus-5-5-1m',
                               '--tracker', self.tracker, '--wait', str(wait)],
                              env=dict(self.env, **env), capture_output=True, text=True, timeout=300)

    def test_the_kit_passes_all_five(self):
        opened = os.path.join(self.folder, 'opened')
        outside = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], env={'OUTSIDE': 'x'})
        try:
            p = self.kit(DRIVER, 20, SCOPED_KIT_OPENED=opened)
        finally:
            outside.kill()
            outside.wait()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertEqual([line.split(':')[0] for line in p.stdout.splitlines()],
                         ['pass version', 'pass start', 'pass wake', 'pass stop', 'pass token'])
        self.calls()
        with open(opened) if os.path.exists(opened) else open(os.devnull) as f:
            self.assertNotIn(str(outside.pid), f.read().split(), 'the kit read a process outside its run')

    def test_the_scoped_kit_still_sees_a_process_the_run_leaves(self):
        worker = os.path.join(self.folder, 'worker')
        leaves = os.path.join(self.folder, 'leaves-a-worker')
        with open(leaves, 'w') as f:
            f.write(LEAVES_A_WORKER % (sys.executable, worker, DRIVER, DRIVER))
        os.chmod(leaves, 0o700)
        try:
            p = self.kit(leaves, 3)
        finally:
            with open(worker) as f:
                pid = int(f.read())
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        self.assertIn('fail stop: a process the run started still runs after stop', p.stdout, p.stdout + p.stderr)

    def test_start_wake_and_stop_reach_one_workspace(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        run = out['run']
        self.assertEqual(self.driver('wake', {'run': run}), (0, {'run': run, 'woke': True}))
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual([c for c in self.calls()], [
            ('POST', '/v0/workspaces'), ('POST', '/v0/sessions/se_fake0001/messages'),
            ('POST', '/v0/sessions/se_fake0001/cancel'), ('POST', '/v0/workspaces/ws_fake0001/archive')])
        self.assertEqual(self.workspaces()['ws_fake0001']['status'], 'archived')
        self.assertEqual(self.workspaces()['ws_fake0001']['repositoryUrl'], 'https://github.com/example/site')
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        code, out = self.driver('wake', {'run': run})
        self.assertEqual(code, 1, out)
        self.assertEqual(len(self.calls()), 4, 'a stopped run called Conductor again')

    def test_a_lost_start_reply_is_never_retried(self):
        code, out = self.driver('start', REQUEST, FAKE_CONDUCTOR_LOSE='POST /v0/workspaces')
        self.assertEqual(code, 1, out)
        self.assertIn('unknown', out['error'])
        self.assertIn('openwiz-', out['next'], 'it names no workspace to look for')
        self.assertEqual(self.calls(), [('POST', '/v0/workspaces')], 'a start that may have worked was sent again')
        self.assertEqual(len(self.workspaces()), 1)

    def test_a_refused_start_starts_nothing_and_says_what_to_do(self):
        for env, word in (({'FAKE_CONDUCTOR_FAIL': 'POST /v0/workspaces=400'}, 'planted failure'),
                          ({'CONDUCTOR_API_KEY': 'sk-' + 'Another0Synthetic0Value0'}, 'CONDUCTOR_API_KEY')):
            with self.subTest(env=sorted(env)):
                code, out = self.driver('start', REQUEST, **env)
                self.assertEqual(code, 1, out)
                self.assertIn('nothing was started', out['error'] + out['next'])
                self.assertIn(word, out['error'] + out['next'])
        self.assertFalse(os.path.exists(self.host) and self.workspaces(), 'a refused start made a workspace')

    def test_nothing_is_called_without_a_key_a_harness_or_a_state_folder(self):
        unset = dict(self.env)
        del unset['CONDUCTOR_API_KEY']
        blocker = os.path.join(self.folder, 'a-file')
        open(blocker, 'w').close()
        for name, env, request in (('no key', {}, REQUEST), ('unknown harness', {}, dict(REQUEST, harness='pi')),
                                   ('no state folder', {'OPENWIZ_CONDUCTOR_STATE': blocker}, REQUEST)):
            with self.subTest(name):
                saved, self.env = self.env, unset if name == 'no key' else self.env
                code, out = self.driver('start', request, **env)
                self.env = saved
                self.assertEqual(code, 1, out)
                self.assertIn('nothing was started', out['error'])
        self.assertEqual(self.calls(), [])

    def test_a_failed_archive_says_so_and_the_run_stays_stopped(self):
        code, out = self.driver('start', REQUEST)
        run = out['run']
        code, out = self.driver('stop', {'run': run}, FAKE_CONDUCTOR_FAIL='POST /v0/workspaces/{id}/archive=500')
        self.assertEqual(code, 1, out)
        self.assertIn('ws_fake0001', out['next'], 'it names no workspace to archive by hand')
        self.assertEqual(self.workspaces()['ws_fake0001']['status'], 'ready')
        code, out = self.driver('wake', {'run': run})
        self.assertEqual(code, 1, 'a run whose stop began was woken')
        self.assertEqual(self.driver('stop', {'run': run}), (0, {'run': run, 'stopped': True}))
        self.assertEqual(self.workspaces()['ws_fake0001']['status'], 'archived')


    def test_the_driver_never_reads_the_key(self):
        guarded = os.path.join(self.folder, 'guarded')
        with open(guarded, 'w') as f:
            f.write(NEVER_READS_THE_KEY % DRIVER)
        for cmd, request in (('start', REQUEST), ('wake', None), ('stop', None)):
            p = subprocess.run([sys.executable, '-I', guarded, cmd],
                               input=json.dumps(request or {'run': self.run_id}), env=self.env,
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            if cmd == 'start':
                self.run_id = json.loads(p.stdout)['run']
        self.assertEqual(len(self.calls()), 4)

    def test_an_old_curl_is_refused_by_its_version(self):
        for version in ('7.88.1', '8.2.1'):
            with self.subTest(version):
                code, out = self.driver('start', REQUEST, FAKE_CURL_VERSION=version)
                self.assertEqual(code, 1, out)
                self.assertIn('curl %s is too old' % version, out['error'])
                self.assertIn('8.3 or later', out['error'] + out['next'])
        self.assertEqual(self.calls(), [], 'it called Conductor with a curl too old to send the key')
        self.assertEqual(self.driver('start', REQUEST, FAKE_CURL_VERSION='8.3.0')[0], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
