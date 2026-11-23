#!/usr/bin/env python3
import argparse
import importlib.machinery
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
import threading
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HERE, 'fixtures')
TEMPLATE = os.path.join(HERE, '..', '..', 'adapters', 'template', 'driver')
NO_PROC = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'fixtures', 'no-proc')
REPO = os.path.realpath(os.path.join(HERE, '..', '..'))
HARNESSES = ('claude', 'claude-code', 'codex', 'gemini', 'opencode', 'openclaw', 'cursor-agent', 'amp', 'aider',
             'goose')
TOOLS = ('sh', 'ps', 'lsof', 'awk', 'sleep', 'dirname', 'true')
TOKEN = 'gh' + 'p_' + 'Synthetic0Kit0Value' * 2 + '00'
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 2',
        'pass wake: the run edited builder status note 2',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
PLANTED = {
    'token-in-args': PASS[:4] + ['fail token: a process the driver started holds a credential on its command line'],
    'token-in-env': PASS[:4] + ['fail token: a process the driver started holds a credential in OPENWIZ_GITHUB, '
                                'which the kit never gave it'],
    'echoes-token': PASS[:4] + ['fail token: the driver printed a credential'],
    'takes-token': PASS[:4] + ['fail token: start took a token field instead of refusing it'],
    'stop-leaves-run': PASS[:3] + ['fail stop: a process the run started still runs after stop', PASS[4]],
    'wake-does-nothing': PASS[:2] + ['fail wake: builder status note 2 did not change after the wake'] + PASS[3:],
    'old-records': ['fail version: it names no openwiz:records v1'] + PASS[1:],
    'error-without-next': PASS[:3] + ['fail stop: next is not a string',
                                      'fail token: its answer to a token field: next is not a string'],
}


KEY = 'synthetic-kit-key-' + 'Kit0Value' * 2
KEY_PASS = PASS[4] + ", and on start, wake and stop the devin key reached its host only from the key helper, in its header"
KEY_HOST = os.path.join(FIXTURES, 'key-host', 'driver')
NOT_RUN = ['fail wake: not run: start failed', 'fail stop: not run: start failed']
NEVER = "fail token: the devin key never reached the kit's fake host"
IN_ARGS = 'a process the driver started holds a credential on its command line'
NO_HEADER = "a request reached the kit's fake host without the devin key in the helper's header"
SCRIPT = "names DEVIN_API_KEY, the key's variable"
PLANTED_KEY = {
    'key-reads-itself': PASS[:4] + ["fail token: the driver's file driver " + SCRIPT],
    'key-in-args': PASS[:4] + ['fail token: ' + IN_ARGS],
    'key-unregistered-host': [PASS[0], 'fail start: the key helper refused: host is not in '
                              'kernel/driver-kit/hosts.json'] + NOT_RUN + [NEVER],
    'key-host-in-path': [PASS[0], 'fail start: the key helper refused: path has // (a host)'] + NOT_RUN + [NEVER],
    'key-in-env': PASS[:4] + ['fail token: a process the driver started holds a credential in OPENWIZ_COPY, which '
                              'the kit never gave it'],
    'key-echoed': PASS[:4] + ['fail token: the driver printed a credential'],
    'key-in-body': [PASS[0], 'fail start: the key helper refused: the request holds the key, so the helper did not '
                    'send it'] + NOT_RUN + [KEY_PASS],
    'key-calls-keychain': PASS[:4] + ["fail token: the driver's file driver calls the keychain tool secret-tool"],
    'key-env-name': PASS[:4] + ['fail token: a process the driver started holds a credential in a variable the kit '
                                'does not name, which the kit never gave it'],
    'key-sent-directly': PASS[:4] + ['fail token: ' + NO_HEADER],
    'key-fake-helper': PASS[:4] + ["fail token: a process that is not the key helper asked the kit's fake host for "
                                   "the key; " + NO_HEADER],
    'key-start-refused': PASS[:4] + ["fail token: start failed against the kit's fake host, so the kit could not "
                                     "check wake and stop"],
    'key-hidden-in-test-file': PASS[:4] + ["fail token: the driver's file test_reader.py " + SCRIPT],
    'key-readme-names-variable': PASS[:4] + ["fail token: the driver's file README.md " + SCRIPT],
    'key-readme-twice': PASS[:4] + ["fail token: the driver's file README.md " + SCRIPT],
    'key-symlinked-dir': PASS[:4] + ["fail token: the driver's file lib/reader.py " + SCRIPT],
    'key-runtime-script': PASS[:4] + ['fail token: the file ../../runtime-reader, which a process of the driver ran, '
                                      + SCRIPT],
    'key-runtime-relative': PASS[:4] + ['fail token: the file ../../runtime-reader, which a process of the driver '
                                        'ran, ' + SCRIPT],
    'key-runtime-credential-path': PASS[:4] + ['fail token: %s; a file a process of the driver ran, which the kit '
                                               'does not name, %s' % (IN_ARGS, SCRIPT)],
    'key-local-login': PASS[:4] + [KEY_PASS],
    'key-runtime-missing-path': PASS[:4] + ['fail token: the kit could not resolve a file a process of the driver ran, '
                                            'so it cannot check it'],
    'key-relative-helper': PASS[:4] + ["fail token: a process that is not the key helper asked the kit's fake host "
                                       "for the key; " + NO_HEADER],
    'key-helper-loader-env': PASS[:4] + ["fail token: a process that is not the key helper asked the kit's fake host "
                                         "for the key; " + NEVER[len('fail token: '):]],
}
LINUX_ONLY = {'key-undumpable-child': PASS[:4] + ['fail token: a process of the driver hides its details, so the kit '
                                                  'cannot check it']}
HOST_SCHEMA = {'type': 'object', 'required': ['origin', 'variable', 'keychain', 'header'],
               'additionalProperties': False,
               'properties': {'origin': {'type': 'string',
                                         'pattern': r'^https://[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+(-[a-z0-9]+)*)+$'},
                              'variable': {'type': 'string', 'pattern': '^[A-Z][A-Z0-9_]{0,63}$'},
                              'keychain': {'type': 'string', 'pattern': r'^[a-z0-9]+([.-][a-z0-9]+)*$'},
                              'header': {'const': 'authorization-bearer'}}}
HOST_NAME = {'type': 'string', 'pattern': '^(?=.{1,40}$)[a-z0-9]+(-[a-z0-9]+)*$'}
CONTRACT_FORMATS = ['token=', 'key=', 'secret=', 'password=', 'sig=', 'password:', 'Bearer', 'gh?_', 'github_pat_',
                    'AKIA', 'xox?-', 'sk-']


def started_at(pid):
    with open('/proc/%s/stat' % pid) as f:
        return int(f.read().rpartition(')')[2].split()[19])


def planted(name):
    return module(os.path.join(FIXTURES, 'planted', name))


def module(path):
    name = os.path.basename(path)
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pinned_path(folder, *fixtures):
    tools = os.path.join(folder, 'tools')
    os.makedirs(tools)
    for name in TOOLS:
        if shutil.which(name):
            os.symlink(shutil.which(name), os.path.join(tools, name))
    os.symlink(sys.executable, os.path.join(tools, 'python3'))
    return no_real_harness(os.pathsep.join(fixtures + (tools,)))


def no_real_harness(path):
    for name in HARNESSES:
        found = shutil.which(name, path=path)
        if found and not os.path.realpath(found).startswith(REPO + os.sep):
            raise AssertionError('%s on the PATH is %s, outside the fixtures: a test could launch a real harness'
                                 % (name, found))
    return path


def tracker(folder):
    path = os.path.join(folder, 'tracker.json')
    old = '<!-- openwiz:status v1 -->\nagent: builder\nstate: stopped\nharness: Fake\nmodel: m\n' \
          'skills: build-ticket@0.1.2\nstep: an earlier run\ntime: 2030-01-02T03:04:05Z\n'
    with open(path, 'w') as f:
        json.dump({'record_authors': ['Example-Bot[bot]'], 'comments': [
            {'id': 1, 'author': 'example-bot[bot]', 'updated_at': '2030-01-02T03:04:05Z', 'body': old}]}, f)
    return path


class Kit(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.mark = secrets.token_hex(8)
        self.env = dict(os.environ, KIT_TRACKER=tracker(self.folder), KIT_TEST=self.mark, GH_TOKEN=TOKEN,
                        OPENWIZ_TEMPLATE_STATE=os.path.join(self.folder, 'state'),
                        PATH=pinned_path(self.folder, FIXTURES))

    def left(self):
        found = []
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        found.append(int(pid))
            except OSError:
                pass
        return found

    def tearDown(self):
        for pid in self.left():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    def kit(self, driver, python=sys.executable, wait='8', **env):
        env = dict(self.env, **env)
        no_real_harness(env['PATH'])
        p = subprocess.run([python, '-I', os.path.join(HERE, 'kit.py'), '--driver', driver,
                            '--repo', 'example/site', '--ticket', '7', '--harness', 'fake-harness',
                            '--model', 'Synthetic 1', '--tracker', self.env['KIT_TRACKER'], '--wait', wait],
                           env=env, capture_output=True, text=True, timeout=120,
                           cwd=os.path.join(HERE, '..', '..'))
        return p.returncode, p.stdout.splitlines(), p.stderr

    def keyed(self, driver, *answer, python=sys.executable, **env):
        kit = module(os.path.join(HERE, 'kit.py'))
        host = kit.FakeHost(*answer, test_key=KEY)
        self.addCleanup(host.close)
        code, out, err = self.kit(driver, python, DEVIN_API_KEY=KEY, OPENWIZ_HOSTKEY_TEST_ORIGIN=host.origin, **env)
        self.assertNotIn('gh' + 'p_', '\n'.join(out) + err)
        texts = ['\n'.join(out) + err]
        for d, _, names in os.walk(self.folder):
            for n in names:
                with open(os.path.join(d, n), errors='replace') as f:
                    texts.append(f.read())
        for text in texts:
            self.assertNotIn('kit-canary-', text)
            self.assertNotIn(KEY, text)
        return code, out, host

    def test_a_key_host_driver_that_uses_only_the_helper_passes_all_five(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        for python, env in ((sys.executable, {}), (os.path.join(NO_PROC, 'python3'), macos)):
            with self.subTest(python):
                self.tearDown()
                self.setUp()
                code, out, host = self.keyed(KEY_HOST, python=python, **dict(env, PATH=env and macos['PATH']
                                                                                 or self.env['PATH']))
                self.assertEqual((code, out), (0, PASS[:4] + [KEY_PASS]))
                lines = [re.sub(r'run-[0-9a-f]{12}', '<run>', r[0].rpartition(' ')[0]) for r in host.requests]
                self.assertEqual(lines, ['POST /v1/runs/<run>/start', 'POST /v1/runs/<run>/wake',
                                         'DELETE /v1/runs/<run>'])
                for _, headers, _ in host.requests:
                    self.assertEqual([v for k, v in headers if k == 'Authorization'], ['Bearer ' + KEY])

    def test_the_canary_never_reaches_the_driver(self):
        code, out, _ = self.keyed(os.path.join(FIXTURES, 'key-host-dumps-env', 'driver'))
        self.assertEqual((code, out), (0, PASS[:4] + [KEY_PASS]))
        with open(os.path.join(self.folder, 'state', 'environments.txt')) as f:
            seen = [json.loads(line) for line in f]
        self.assertEqual([s['kit'] for s in seen], [[]] * len(seen), 'the canary reached the driver')
        self.assertTrue(any('DEVIN_API_KEY' not in s['names'] for s in seen), 'the key check never ran the driver')
        self.assertFalse(any('OPENWIZ_HOSTKEY_TEST_KEY' in s['names'] for s in seen))

    def test_a_failed_process_watch_fails_the_key_check(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        k = kit.Kit.__new__(kit.Kit)
        k.lock, k.leaks = threading.RLock(), []
        k.call = lambda *a: (time.sleep(0.2), ('ok', {}))[1]

        def broken(canary=None):
            raise OSError('synthetic')
        k.scan = broken
        self.assertEqual(k.sampled('start', {}, {}, ('devin', 'kit-canary-0', 'DEVIN_API_KEY')), ('ok', {}))
        self.assertEqual(k.leaks, ["the kit's process watch failed, so it cannot check the driver"])

    def test_a_script_whose_path_holds_a_space_is_scanned_on_linux_and_macos(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        driver = os.path.join(FIXTURES, 'planted', 'key-runtime-spaced-path', 'driver')
        for python, env in ((sys.executable, {}), (os.path.join(NO_PROC, 'python3'), macos)):
            with self.subTest(python):
                self.tearDown()
                self.setUp()
                env = dict(env, PATH=NO_PROC + os.pathsep + self.env['PATH']) if env else {}
                code, out, _ = self.keyed(driver, python=python, **env)
                script = os.path.realpath(os.path.join(self.folder, 'state', 'a spaced folder', 'reader'))
                rel = os.path.relpath(script, os.path.realpath(os.path.dirname(driver)))
                self.assertEqual((code, out), (1, PASS[:4] + ['fail token: the file %s, which a process of the driver '
                                                             'ran, %s' % (rel, SCRIPT)]))

    def test_the_kit_trusts_only_its_own_interpreter_not_one_on_path(self):
        fake = os.path.join(self.folder, 'bin')
        os.makedirs(fake)
        with open(os.path.join(fake, 'python3'), 'w') as f:
            f.write('#!/bin/sh\nexit 1\n')
        os.chmod(os.path.join(fake, 'python3'), 0o700)
        probe = ('import importlib.machinery as m, importlib.util as u\n'
                 's = u.spec_from_loader("kit", m.SourceFileLoader("kit", %r))\nk = u.module_from_spec(s)\n'
                 's.loader.exec_module(k)\nprint("\\n".join(sorted(k.TRUSTED_PYTHONS)))\n' % os.path.join(HERE, 'kit.py'))
        p = subprocess.run([sys.executable, '-I', '-c', probe], env=dict(self.env, PATH=fake + os.pathsep + '/usr/bin:/bin'),
                           capture_output=True, text=True, timeout=60)
        own = {os.path.realpath(x) for x in (sys.executable, getattr(sys, '_base_executable', sys.executable))}
        self.assertEqual(set(p.stdout.split()), own, p.stderr)

    def test_a_helper_without_a_visible_environment_row_is_not_trusted(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        k = kit.Kit.__new__(kit.Kit)
        k.mark = 'OPENWIZ_KIT_RUN=synthetic'
        k.peer = lambda port, server: (424242, [sys.executable, '-I', kit.HOSTKEY])
        k.process_cwd = lambda pid: HERE
        k.executable = lambda pid: os.path.realpath(sys.executable)
        rows = {'missing': {}, 'no mark': {424242: sys.executable + ' -I ' + kit.HOSTKEY + ' HOME=/synthetic'},
                'loader': {424242: sys.executable + ' -I ' + kit.HOSTKEY + ' LD_BIND_NOW=1 ' + k.mark},
                'good': {424242: sys.executable + ' -I ' + kit.HOSTKEY + ' HOME=/synthetic ' + k.mark}}
        old = kit.PROC
        kit.PROC = False
        try:
            for name, row in rows.items():
                with self.subTest(name):
                    k.ps = lambda *a, row=row: row
                    self.assertEqual(k.trusted_helper(1, 2), name == 'good')
        finally:
            kit.PROC = old

    @unittest.skipUnless(os.path.isdir('/proc/self'), 'reads /proc')
    def test_a_hidden_process_costs_a_retry_once_and_one_older_than_the_kit_none(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        hide = ('import ctypes, os, sys, time; ctypes.CDLL(None).prctl(4, 0, 0, 0, 0); print(flush=True); '
                'time.sleep(30)')

        def hidden():
            child = subprocess.Popen([sys.executable, '-c', hide], stdout=subprocess.PIPE, start_new_session=False)
            self.addCleanup(child.kill)
            child.stdout.readline()
            return child
        older = hidden()
        time.sleep(0.05)
        k = kit.Kit.__new__(kit.Kit)
        k.lock, k.leaks, k.mark, k.hidden = threading.RLock(), [], 'OPENWIZ_KIT_RUN=synthetic', set()
        k.since = started_at(str(older.pid)) + 1
        time.sleep(0.05)
        newer = hidden()
        while started_at(str(newer.pid)) <= k.since:
            newer.kill()
            newer = hidden()
        pauses = []
        real = kit.time.sleep
        kit.time.sleep = lambda seconds: pauses.append(seconds)
        try:
            first = k.table()
            once = len(pauses)
            list(k.started())
            k.table()
        finally:
            kit.time.sleep = real
        self.assertEqual((first[str(older.pid)][2], first[str(newer.pid)][2]), (None, None))
        self.assertEqual(once, kit.HIDDEN_TRIES - 1, 'only the hidden process newer than the kit is retried')
        self.assertEqual(len(pauses), once, 'a process already found hidden was retried again')
        self.assertEqual(k.leaks, ['a process of the driver hides its details, so the kit cannot check it'])

    def test_a_path_diagnostic_never_prints_the_active_canary(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        k = kit.Kit.__new__(kit.Kit)
        k.lock, k.leaks = threading.RLock(), []
        canary = 'kit-canary-' + secrets.token_hex(16)
        k.active = {canary}
        folder, drv = os.path.join(self.folder, canary), os.path.join(self.folder, 'drv')
        os.makedirs(os.path.join(drv, canary))
        os.makedirs(folder)
        for path in (os.path.join(folder, 'reader'), os.path.join(drv, canary, 'reader'), os.path.join(drv, 'driver')):
            with open(path, 'w') as f:
                f.write('' if path.endswith('driver') else 'DEVIN_API_KEY\n')
        k.runtime = {os.path.join(folder, 'reader')}
        k.args = argparse.Namespace(driver=os.path.join(drv, 'driver'))
        entry = {'variable': 'DEVIN_API_KEY', 'keychain': 'openwiz-devin'}
        k.runtime_check(entry)
        k.file_check(entry)
        self.assertEqual(len(k.leaks), 2, k.leaks)
        self.assertFalse(any(canary in leak for leak in k.leaks), k.leaks)

    def test_each_planted_key_driver_fails_with_its_own_line(self):
        for name, lines in dict(PLANTED_KEY, **(LINUX_ONLY if os.path.isdir('/proc/self') else {})).items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                code, out, _ = self.keyed(os.path.join(FIXTURES, 'planted', name, 'driver'))
                self.assertEqual((code, out), (0 if all(x.startswith('pass') for x in lines) else 1, lines))

    def test_on_macos_a_key_in_an_argument_or_another_variable_is_caught(self):
        for name in ('key-in-args', 'key-in-env', 'key-runtime-script', 'key-runtime-relative'):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                code, out, _ = self.keyed(os.path.join(FIXTURES, 'planted', name, 'driver'),
                                          python=os.path.join(NO_PROC, 'python3'), NO_PROC_PYTHON=sys.executable,
                                          PATH=NO_PROC + os.pathsep + self.env['PATH'])
                self.assertEqual((code, out), (1, PLANTED_KEY[name]))

    def test_without_the_key_helper_the_kit_refuses_a_driver_with_a_readme_and_runs_one_without(self):
        kit = os.path.join(self.folder, 'kernel', 'driver-kit')
        os.makedirs(kit)
        for name in ('kit.py', 'schema.json'):
            shutil.copy(os.path.join(HERE, name), kit)
        shutil.copytree(os.path.join(HERE, '..', 'records-kit'), os.path.join(self.folder, 'kernel', 'records-kit'))
        shutil.copy(os.path.join(HERE, '..', 'records.v1.md'), os.path.join(self.folder, 'kernel'))
        bare = os.path.join(self.folder, 'bare')
        os.makedirs(bare)
        for name in ('driver', 'schema.json'):
            shutil.copy(os.path.join(os.path.dirname(TEMPLATE), name), bare)
        for driver, want in ((KEY_HOST, 2), (TEMPLATE, 2), (os.path.join(bare, 'driver'), 0)):
            with self.subTest(driver):
                p = subprocess.run([sys.executable, '-I', os.path.join(kit, 'kit.py'), '--driver', driver, '--repo',
                                    'example/site', '--ticket', '7', '--harness', 'fake-harness', '--model', 'm',
                                    '--tracker', self.env['KIT_TRACKER'], '--wait', '8'], env=self.env,
                                   capture_output=True, text=True, timeout=120)
                self.assertEqual(p.returncode, want, p.stdout + p.stderr)
                if want:
                    self.assertEqual(p.stderr, 'kit.py: the key helper kernel/driver-kit/hostkey.py is missing, so '
                                               'the kit cannot check host keys\n')

    def test_a_host_that_answers_a_redirect_fails_start_and_the_redirect_is_never_followed(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        target = kit.FakeHost()
        self.addCleanup(target.close)
        code, out, host = self.keyed(KEY_HOST, 302, [('Location', target.origin + '/v1/runs')], b'')
        self.assertEqual((code, out), (1, [PASS[0], 'fail start: the host answered 302'] + NOT_RUN + [KEY_PASS]))
        self.assertEqual((len(host.requests), target.requests), (1, []))

    def test_the_registry_holds_devin_and_the_schema_and_helper_refuse_the_same_registries(self):
        kit, hostkey = module(os.path.join(HERE, 'kit.py')), module(os.path.join(HERE, 'hostkey.py'))
        good = {'devin': {'origin': 'https://api.devin.ai', 'variable': 'DEVIN_API_KEY', 'keychain': 'openwiz-devin',
                          'header': 'authorization-bearer'}}
        hosts = hostkey.registry()
        self.assertEqual(hosts['devin'], good['devin'])
        for name, entry in hosts.items():
            self.assertEqual((kit.invalid(name, HOST_NAME), kit.invalid(entry, HOST_SCHEMA)), (None, None), name)
        entry = good['devin']
        cases = [good, dict(good, other=dict(entry, origin='https://api.example.org')), {}, [entry], {'devin': [1]},
                 {'Devin': entry}, {'d' * 41: entry}, {'devin': dict(entry, extra='x')}, {'devin': {'origin': 'x'}},
                 {'devin': dict(entry, origin='http://api.devin.ai')}, {'devin': dict(entry, origin=entry['origin'] + '/')},
                 {'devin': dict(entry, origin=entry['origin'] + ':443')}, {'devin': dict(entry, origin='https://API.devin.ai')},
                 {'devin': dict(entry, origin='https://localhost')}, {'devin': dict(entry, header='x-api-key')},
                 {'devin': dict(entry, variable='devin_api_key')}, {'devin': dict(entry, keychain='openwiz devin')},
                 {'devin': dict(entry, variable=7)}, 'raw:{"devin": %s, "devin": %s}' % (json.dumps(entry), json.dumps(entry)),
                 'raw:{"devin": {"origin": NaN}}', 'raw:not json']
        for case in cases:
            with self.subTest(case):
                path = os.path.join(self.folder, 'hosts.json')
                with open(path, 'w') as f:
                    f.write(case[4:] if isinstance(case, str) else json.dumps(case))
                try:
                    value = kit.parse(case[4:]) if isinstance(case, str) else case
                    schema = isinstance(value, dict) and bool(value) and all(
                        kit.invalid(n, HOST_NAME) is None and kit.invalid(e, HOST_SCHEMA) is None for n, e in value.items())
                except ValueError:
                    schema, value = False, None
                try:
                    helper = hostkey.registry(path) == value
                except hostkey.Refused:
                    helper = False
                self.assertEqual((schema, helper), (schema, schema))

    def test_template_passes_all_five(self):
        self.assertEqual(self.kit(TEMPLATE)[:2], (0, PASS))

    def test_without_proc_as_on_macos_the_template_passes_all_five(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        self.assertEqual(self.kit(TEMPLATE, os.path.join(NO_PROC, 'python3'), **macos)[:2], (0, PASS))
        for name in ('stop-leaves-run', 'token-in-env'):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                macos['PATH'] = NO_PROC + os.pathsep + self.env['PATH']
                code, out, err = self.kit(os.path.join(FIXTURES, 'planted', name), os.path.join(NO_PROC, 'python3'),
                                          **macos)
                self.assertEqual((code, out), (1, PLANTED[name]), err)
        self.tearDown()
        self.setUp()
        spaced = dict(macos, PATH=NO_PROC + os.pathsep + self.env['PATH'], GH_TOKEN='Bearer ' + TOKEN[4:])
        code, out, err = self.kit(os.path.join(FIXTURES, 'planted', 'token-in-env'), os.path.join(NO_PROC, 'python3'),
                                  **spaced)
        self.assertEqual((code, out), (1, PLANTED['token-in-env']), err)

    def test_without_proc_as_on_macos_a_driver_whose_run_stays_in_the_kits_group_passes_all_five(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable,
                 'FAKE_SAME_GROUP': '1'}
        code, out, err = self.kit(os.path.join(FIXTURES, 'same-group-driver'), os.path.join(NO_PROC, 'python3'),
                                  **macos)
        self.assertEqual((code, out), (0, PASS), err)

    def test_the_kits_visibility_probe_signals_ready_through_the_macos_shim_and_runs_until_its_stdin_closes(self):
        p = subprocess.run([os.path.join(NO_PROC, 'python3')] + module(os.path.join(HERE, 'kit.py')).PROBE,
                           input='', env=dict(self.env, NO_PROC_PYTHON=sys.executable), capture_output=True,
                           text=True, timeout=60)
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, '.', ''))

    def test_without_proc_or_the_runs_visible_environment_stop_and_token_fail_unverified(self):
        cases = {'NO_PROC_HIDE_ENV': "ps shows no process's environment here, so the kit cannot tell which "
                                     "processes the driver started",
                 'NO_PROC_PROBE_ONLY': "ps -E never showed a process of this run, so the kit cannot tell which "
                                       "processes the driver started"}
        for hide, why in cases.items():
            for name in ('template', 'stop-leaves-run', 'token-in-env'):
                with self.subTest(hide=hide, driver=name):
                    self.tearDown()
                    self.setUp()
                    driver = TEMPLATE if name == 'template' else os.path.join(FIXTURES, 'planted', name)
                    code, out, err = self.kit(driver, os.path.join(NO_PROC, 'python3'), **{hide: '1'},
                                              PATH=NO_PROC + os.pathsep + self.env['PATH'],
                                              NO_PROC_PYTHON=sys.executable)
                    self.assertEqual((code, out), (1, PASS[:3] + ['fail stop: ' + why, 'fail token: ' + why]), err)
                    self.assertEqual(bool(self.left()), name == 'stop-leaves-run',
                                     "the driver's own stop lost its baseline under the kit's hidden view")

    def test_probe_only_hides_environments_from_the_kits_own_listing_only(self):
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], env=self.env)
        try:
            for caller, shown in (({}, False), ({'OPENWIZ_KIT_RUN': self.mark}, True)):
                with self.subTest(caller=caller):
                    p = subprocess.run([os.path.join(NO_PROC, 'ps'), '-A', '-ww', '-o', 'pid=', '-o', 'command=', '-E'],
                                       env=dict(self.env, NO_PROC_PROBE_ONLY='1', **caller), capture_output=True,
                                       text=True, timeout=30)
                    rows = [r for r in p.stdout.splitlines() if r.split()[:1] == [str(child.pid)]]
                    self.assertEqual((bool(rows), any('KIT_TEST=' + self.mark in r for r in rows)), (True, shown))
        finally:
            child.kill()
            child.wait()

    def test_a_failed_start_check_still_stops_its_run(self):
        sleepy = os.path.join(self.folder, 'sleepy')
        os.mkdir(sleepy)
        with open(os.path.join(sleepy, 'fake-harness'), 'w') as f:
            f.write('#!%s\nimport time\ntime.sleep(120)\n' % sys.executable)
        os.chmod(os.path.join(sleepy, 'fake-harness'), 0o700)
        code, out, err = self.kit(TEMPLATE, wait='2', PATH=sleepy + os.pathsep + self.env['PATH'])
        self.assertEqual((code, out), (1, [PASS[0], 'fail start: no builder status note appeared within 2 seconds',
                                           'fail wake: not run: start failed', 'fail stop: not run: start failed',
                                           PASS[4]]), err)
        self.assertEqual(self.left(), [], 'the run whose start check failed still runs after the kit')

    def test_no_harness_outside_the_fixtures_is_on_the_tests_path(self):
        outside = os.path.join(self.folder, 'outside')
        os.mkdir(outside)
        with open(os.path.join(outside, 'claude'), 'w') as f:
            f.write('#!/bin/sh\nexit 0\n')
        os.chmod(os.path.join(outside, 'claude'), 0o700)
        old = os.environ['PATH']
        os.environ['PATH'] = outside + os.pathsep + old
        try:
            self.tearDown()
            self.setUp()
        finally:
            os.environ['PATH'] = old
        self.assertIsNone(shutil.which('claude', path=self.env['PATH']), 'the PATH reaches a real claude')
        self.assertEqual(shutil.which('fake-harness', path=self.env['PATH']), os.path.join(FIXTURES, 'fake-harness'))
        with self.assertRaisesRegex(AssertionError, 'could launch a real harness'):
            self.kit(TEMPLATE, PATH=outside + os.pathsep + self.env['PATH'])

    def test_each_planted_driver_fails_its_check(self):
        for name, lines in PLANTED.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self.assertEqual(self.kit(os.path.join(FIXTURES, 'planted', name))[:2], (1, lines))

    def test_a_refusal_holding_a_credential_never_reaches_the_output(self):
        sample = planted('refuses-with-credential').SAMPLE
        for escape in ('', '1'):
            with self.subTest(escape=escape):
                self.tearDown()
                self.setUp()
                self.env['KIT_ESCAPE'] = escape
                self.assertFalse(any(sample in v for v in self.env.values()))
                code, out, err = self.kit(os.path.join(FIXTURES, 'planted', 'refuses-with-credential'))
                self.assertNotIn(sample, '\n'.join(out) + err)
                self.assertEqual((code, out), (1, PASS[:3] + [
                    'fail stop: its stop output held a credential, which the kit does not show',
                    'fail token: the driver printed a credential; its answer to a token field: its start output '
                    'held a credential, which the kit does not show']))

    def test_each_status_contract_credential_format_is_caught(self):
        formats = planted('leaks-format').FORMATS
        self.assertLessEqual(set(CONTRACT_FORMATS), set(formats))
        for name, sample in formats.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self.env['KIT_LEAK'] = name
                self.assertFalse(any(sample in v for v in self.env.values()))
                code, out, err = self.kit(os.path.join(FIXTURES, 'planted', 'leaks-format'))
                self.assertEqual((code, out), (1, PASS[:4] + ['fail token: the driver printed a credential']))
                self.assertNotIn(sample, '\n'.join(out) + err)

    def test_template_and_schema_refuse_the_same_starts(self):
        sys.path.insert(0, HERE)
        import kit
        good = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'true',
                'model': 'Opus 5.5 Medium'}
        cases = [json.dumps(good), json.dumps(dict(good, token='x')), json.dumps({'repository': 'example/site'}),
                 json.dumps(dict(good, ticket=0)), json.dumps(dict(good, ticket='7')),
                 json.dumps(dict(good, ticket=True)), json.dumps(dict(good, repository='a/b/c')),
                 json.dumps(dict(good, skill='Build')), json.dumps(dict(good, skill='b' * 61)),
                 json.dumps(dict(good, harness='/usr/bin/true')), json.dumps(dict(good, model='m' * 61)),
                 json.dumps(dict(good, model='m\n')), json.dumps([good]), 'not json',
                 json.dumps(good)[:-1] + ', "ticket": 8}']
        schema = kit.load_schema()['commands']['start']['input']
        for case in cases:
            with self.subTest(case):
                try:
                    valid = kit.invalid(kit.parse(case), schema) is None
                except ValueError:
                    valid = False
                p = subprocess.run([TEMPLATE, 'start'], input=case, env=self.env, capture_output=True, text=True,
                                   timeout=60)
                self.assertEqual((p.returncode == 0), valid, p.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
