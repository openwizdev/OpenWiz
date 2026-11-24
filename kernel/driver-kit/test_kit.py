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
BASE = os.path.join(FIXTURES, 'base', 'driver')
NO_PROC = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'fixtures', 'no-proc')
REPO = os.path.realpath(os.path.join(HERE, '..', '..'))
HARNESSES = ('claude', 'claude-code', 'codex', 'gemini', 'opencode', 'openclaw', 'cursor-agent', 'amp', 'aider',
             'goose')
TOOLS = ('sh', 'ps', 'lsof', 'awk', 'sleep', 'dirname', 'true')
TOKEN = 'gh' + 'p_' + 'Synthetic0Kit0Value' * 2 + '00'
STARTED = 'pass start: the run posted builder status note 2'
NOT_DECLARED = 'note start: effort: not declared yet; required from EF14\n'
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        STARTED,
        'pass wake: the run edited builder status note 2',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
CANT = STARTED + "; effort: a start with it was refused, as the README's Effort: line says"
CANT_PASS = [PASS[0], CANT] + PASS[2:]
PLANTED = {
    'token-in-args': CANT_PASS[:4] + ['fail token: a process the driver started holds a credential on its command '
                                      'line'],
    'token-in-env': CANT_PASS[:4] + ['fail token: a process the driver started holds a credential in OPENWIZ_GITHUB, '
                                     'which the kit never gave it'],
    'echoes-token': CANT_PASS[:4] + ['fail token: the driver printed a credential'],
    'takes-token': [PASS[0], 'fail start: effort: its can does not list effort, but a start with it was taken',
                    'fail wake: not run: start failed', 'fail stop: not run: start failed',
                    'fail token: start took a token field instead of refusing it'],
    'stop-leaves-run': CANT_PASS[:3] + ['fail stop: a process the run started still runs after stop', PASS[4]],
    'wake-does-nothing': CANT_PASS[:2] + ['fail wake: builder status note 2 did not change after the wake']
    + PASS[3:],
    'old-records': ['fail version: it names no openwiz:records v1'] + CANT_PASS[1:],
    'error-without-next': CANT_PASS[:3] + ['fail stop: next is not a string',
                                           'fail token: its answer to a token field: next is not a string'],
}


KEY = 'synthetic-kit-key-' + 'Kit0Value' * 2
KEY_PASS = PASS[4] + ", and on start, wake and stop the devin key reached its host only from the key helper, in its header"
KEY_HOST = os.path.join(FIXTURES, 'key-host', 'driver')
NOT_RUN = ['fail wake: not run: start failed', 'fail stop: not run: start failed']
NEVER = "fail token: the devin key never reached the kit's fake host"
CHECKS = ('version', 'start', 'wake', 'stop', 'token')
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
EFFORT_FAIL = [PASS[0], 'fail start: effort: %s'] + NOT_RUN
EFFORT = {
    'effort': [PASS[0], STARTED + '; effort: medium reached a process the run started'] + PASS[2:],
    'effort-one-shot': [PASS[0], STARTED + '; effort: medium reached a process the run started'] + PASS[2:],
    'effort-refused': [PASS[0], STARTED + '; effort: refused for fake-harness with the refusal text, as the README '
                       'says'] + PASS[2:],
    'effort-cant': [PASS[0], STARTED + "; effort: a start with it was refused, as the README's Effort: line says"]
    + PASS[2:],
    'planted/effort-dropped': EFFORT_FAIL + [PASS[4]],
    'planted/effort-wrong-next': [PASS[0], 'fail start: harness fake-harness cannot run at effort medium; next: start '
                                  'it again without the effort'] + NOT_RUN + [PASS[4]],
    'planted/effort-no-readme-line': EFFORT_FAIL + [PASS[4]],
    'planted/effort-taken-without-can': EFFORT_FAIL + [PASS[4]],
    'planted/effort-no-readme': EFFORT_FAIL + [PASS[4]],
    'planted/effort-refuses-listed': EFFORT_FAIL + [PASS[4]],
    'planted/effort-word-elsewhere': EFFORT_FAIL + [PASS[4]],
    'planted/effort-cant-harness-taken': EFFORT_FAIL + [PASS[4]],
}
EFFORT_WHY = {
    'planted/effort-dropped': 'medium never reached a process the run started',
    'planted/effort-no-readme-line': "its can lists effort, but its README has no Effort: line naming the flag",
    'planted/effort-taken-without-can': 'its can does not list effort, but a start with it was taken',
    'planted/effort-no-readme': "its can lists effort, but its README has no Effort: line naming the flag",
    'planted/effort-refuses-listed': 'start refused medium for fake-harness, but its README says that harness takes '
                                     'medium',
    'planted/effort-word-elsewhere': 'medium never reached a process the run started',
    'planted/effort-cant-harness-taken': "its README says fake-harness can't set effort, but a start with it was taken",
}
HARNESS_EFFORTS = {'effort': 2, 'planted/effort-taken-without-can': 1, 'planted/effort-cant-harness-taken': 1}
EFFORT_KEY = {
    'effort-key-host': [PASS[0], "pass start: the run posted builder status note 3; effort: medium reached the kit's "
                        "fake devin host", 'pass wake: the run edited builder status note 3', PASS[3], KEY_PASS],
    'planted/effort-dropped-key-host': [PASS[0], "fail start: effort: medium never reached the kit's fake devin host"]
    + NOT_RUN + [KEY_PASS],
    'planted/effort-key-host-starts-then-refuses': [PASS[0], "fail start: effort: start refused medium with the "
                                                    "refusal text after it sent the kit's fake devin host a start "
                                                    "request"] + NOT_RUN + [KEY_PASS],
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

LOCAL = os.path.join(REPO, 'adapters', 'local', 'driver')
KIMI = 'https://github.com/MoonshotAI/kimi-code/blob/9a82686b0e91c532f4d49da0bc088a0eac9bdede/docs/en/'
PI = 'https://github.com/badlogic/pi-mono/blob/8209929fb553e7a8c91dc0894569f9ec43dd201f/packages/coding-agent/docs/'
OPENCODE = ('https://github.com/anomalyco/opencode/blob/6d04312b71ac33e7c150234d7087da01388ff2ab/services/site/src/'
            'docs/v1/content/')
KILO = 'https://github.com/Kilo-Org/kilocode/blob/bfdec5496922452222223c01b4cc6c89305b0279/'
CRUSH = 'https://github.com/charmbracelet/catwalk/blob/v3.2.9/internal/providers/configs/'
REAL_MODELS = {
    'kimi-code/kimi-for-coding': KIMI + 'reference/kimi-command.md#L127',
    'kimi-code/kimi-for-coding-highspeed': KIMI + 'configuration/config-files.md#L50',
    'azure/gpt-5.4': PI + 'providers.md#L140',
    'openrouter/typesafe/jev-1.13': PI + 'codemode.md#L95',
    'anthropic/claude-sonnet-5-5': OPENCODE + 'commands.mdx#L26',
    'openrouter/google/gemini-3.8-flash': OPENCODE + 'troubleshooting.mdx#L239',
    'openrouter/anthropic/claude-sonnet-4-20250514': KILO + 'packages/kilo-docs/pages/ai-providers/openrouter.md#L55',
    'openrouter/openai/gpt-5': KILO + 'specs/v2/config.md#L261',
    'openrouter/anthropic/claude-sonnet-4.6': CRUSH + 'openrouter.json#L7',
    'openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free': CRUSH + 'openrouter.json#L2145',
    'fireworks/accounts/fireworks/models/nemotron-lightning-3p5-30b-a3b': CRUSH + 'fireworks.json#L337',
}
BAD_MODELS = ['/x', 'x/', 'x//y', 'x/../y', 'x/./y', 'x/ /y', 'x/' + 'm' * 99, '..', 'x/.y', 'x/-y',
              'https://host.example/x', 'x/y\n', 'x\\y']


def efforts(path):
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [a[a.index('--effort') + 1] for a in map(json.loads, f) if '--effort' in a]


def started_at(pid):
    with open('/proc/%s/stat' % pid) as f:
        return int(f.read().rpartition(')')[2].split()[19])


def template_expected():
    with open(os.path.join(os.path.dirname(TEMPLATE), 'README.md')) as f:
        line = any(x.startswith('Effort:') for x in f.read().splitlines())
    if 'effort' in module(TEMPLATE).VERSION['can']:
        return [PASS[0], STARTED + '; effort: medium reached a process the run started'] + PASS[2:], ''
    return (CANT_PASS, '') if line else (PASS, NOT_DECLARED)


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

    def kit(self, driver, python=sys.executable, wait='8', extra=(), script='kit.py', **env):
        env = dict(self.env, **env)
        no_real_harness(env['PATH'])
        p = subprocess.run([python, '-I', os.path.join(HERE, script), '--driver', driver,
                            '--repo', 'example/site', '--ticket', '7', '--harness', 'fake-harness',
                            '--model', 'Synthetic 1', '--tracker', self.env['KIT_TRACKER'], '--wait', wait] + list(extra),
                           env=env, capture_output=True, text=True, timeout=120, cwd=os.path.join(HERE, '..', '..'))
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

    def test_a_relative_script_without_a_prefix_or_behind_a_decoy_is_scanned_on_linux_and_macos(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        cases = {'key-runtime-relative-spaced': ('shared scripts', 'reader.py'),
                 'key-runtime-decoy-run': ('y', 'reader.py')}
        for name, script in cases.items():
            driver = os.path.join(FIXTURES, 'planted', name, 'driver')
            for python, env in ((sys.executable, {}), (os.path.join(NO_PROC, 'python3'), macos)):
                with self.subTest(name, python=python):
                    self.tearDown()
                    self.setUp()
                    env = dict(env, PATH=NO_PROC + os.pathsep + self.env['PATH']) if env else {}
                    code, out, _ = self.keyed(driver, python=python, **env)
                    path = os.path.realpath(os.path.join(self.folder, 'state', *script))
                    rel = os.path.relpath(path, os.path.realpath(os.path.dirname(driver)))
                    self.assertEqual((code, out), (1, PASS[:4] + ['fail token: the file %s, which a process of the '
                                                                 'driver ran, %s' % (rel, SCRIPT)]))

    def test_a_child_that_lives_only_during_one_call_is_seen_for_each_of_start_wake_and_stop(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        driver = os.path.join(FIXTURES, 'planted', 'key-runtime-one-call', 'driver')
        for call in ('start', 'wake', 'stop'):
            for python, env in ((sys.executable, {}), (os.path.join(NO_PROC, 'python3'), macos)):
                with self.subTest(call, python=python):
                    self.tearDown()
                    self.setUp()
                    env = dict(env, PATH=NO_PROC + os.pathsep + self.env['PATH']) if env else {}
                    code, out, _ = self.keyed(driver, python=python, KIT_ONE_CALL=call, **env)
                    path = os.path.realpath(os.path.join(self.folder, 'state', 'one-call-reader.py'))
                    rel = os.path.relpath(path, os.path.realpath(os.path.dirname(driver)))
                    self.assertEqual((code, out), (1, PASS[:4] + ['fail token: the file %s, which a process of the '
                                                                 'driver ran, %s' % (rel, SCRIPT)]))

    @unittest.skipIf(os.geteuid() == 0, 'root lists every folder')
    def test_a_relative_script_in_a_folder_the_kit_cannot_list_is_still_found_in_macos_text(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        k = kit.Kit.__new__(kit.Kit)
        k.lock, k.leaks = threading.RLock(), []
        cwd = os.path.join(self.folder, 'unlisted')
        os.makedirs(os.path.join(cwd, 'Shared Scripts'))
        script = os.path.join(cwd, 'Shared Scripts', 'reader.py')
        with open(script, 'w') as f:
            f.write('\n')
        os.chmod(cwd, 0o311)
        self.addCleanup(os.chmod, cwd, 0o700)
        self.assertEqual(list(k.text_files('python3 Shared Scripts/reader.py', cwd)), [script])
        self.assertEqual(k.leaks, [])

    def test_a_word_under_a_missing_folder_costs_one_lookup_in_macos_text(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        k = kit.Kit.__new__(kit.Kit)
        k.lock, k.leaks = threading.RLock(), []
        looked, real = [], kit.os.path.exists
        kit.os.path.exists = lambda path: looked.append(path) or real(path)
        try:
            found = list(k.text_files('python3 /nonexistent/openwiz/v1 ' + 'word ' * 500, self.folder))
        finally:
            kit.os.path.exists = real
        self.assertEqual(found, [])
        self.assertLessEqual(len(looked), 510, 'the search kept growing under a folder that does not exist')

    @unittest.skipUnless(os.path.isdir('/proc/self'), 'reads /proc')
    def test_a_live_marked_process_whose_folder_cannot_be_read_fails_the_check(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        k = kit.Kit.__new__(kit.Kit)
        k.lock, k.leaks, k.mark = threading.RLock(), [], 'OPENWIZ_KIT_RUN=synthetic'
        k.table = lambda: {str(child.pid): (os.getpid(), os.getuid(), [k.mark], [sys.executable, ''], 0, 0)}

        def unreadable(pid, tries=kit.HIDDEN_TRIES):
            raise OSError(5, 'Input/output error')
        k.folder_of = unreadable
        self.assertEqual(list(k.run_processes()), [])
        self.assertEqual(k.leaks, ["the kit could not read a process of the driver's working folder, so it cannot "
                                   "check it"])
        child.kill()
        child.wait()
        k.leaks = []
        self.assertEqual(list(k.run_processes()), [])
        self.assertEqual(k.leaks, [], 'a process that has exited is skipped')

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
            shutil.copy(os.path.join(os.path.dirname(BASE), name), bare)
        for driver, want in ((KEY_HOST, 2), (TEMPLATE, 2), (os.path.join(bare, 'driver'), 0)):
            with self.subTest(driver):
                p = subprocess.run([sys.executable, '-I', os.path.join(kit, 'kit.py'), '--driver', driver, '--repo',
                                    'example/site', '--ticket', '7', '--harness', 'fake-harness', '--model', 'm',
                                    '--tracker', self.env['KIT_TRACKER'], '--wait', '8'], env=self.env,
                                   capture_output=True, text=True, timeout=120)
                self.assertEqual(p.returncode, want, p.stdout + p.stderr)
                note = {KEY_HOST: '', TEMPLATE: template_expected()[1]}.get(driver, NOT_DECLARED)
                if want:
                    self.assertEqual(p.stderr, note + 'kit.py: the key helper kernel/driver-kit/hostkey.py is missing, '
                                                      'so the kit cannot check host keys\n')
                else:
                    self.assertEqual(p.stderr, note)

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
        self.assertEqual(self.kit(TEMPLATE), (0,) + template_expected())

    def test_the_fixed_undeclared_driver_passes_all_five_with_the_note_on_stderr(self):
        self.assertEqual(self.kit(BASE), (0, PASS, NOT_DECLARED))

    def test_a_declared_driver_gets_no_note(self):
        for name in ('effort', 'effort-cant'):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self.assertEqual(self.kit(os.path.join(FIXTURES, name, 'driver'))[::2], (0, ''))

    def test_each_effort_driver_prints_its_own_start_line(self):
        for name, lines in EFFORT.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                args = os.path.join(self.folder, 'args')
                if name in EFFORT_WHY:
                    lines = [x % EFFORT_WHY[name] if x.startswith('fail start') else x for x in lines]
                code, out, err = self.kit(os.path.join(FIXTURES, name, 'driver'), FAKE_ARGS=args)
                self.assertEqual((code, out), (0 if all(x.startswith('pass') for x in lines) else 1, lines), err)
                self.assertEqual(efforts(args), ['medium'] * HARNESS_EFFORTS.get(name, 0), name)

    def test_a_refusal_that_is_not_about_effort_is_reported_plainly(self):
        cases = {'planted/effort-refuses-every-start': 'fail start: the sandbox cannot push to example/site; next: '
                                                       'give the connected account write access',
                 'planted/effort-wrong-next': 'fail start: harness fake-harness cannot run at effort medium; next: '
                                              'start it again without the effort'}
        once = [{'sampled': 1, 'effort': True, 'token': False, 'canary': False},
                {'sampled': 0, 'effort': False, 'token': True, 'canary': False}]
        for name, line in cases.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                calls = os.path.join(self.folder, 'calls')
                code, out, err = self.kit(os.path.join(FIXTURES, name, 'driver'),
                                          script=os.path.join('fixtures', 'recorded-kit'), KIT_CALLS=calls)
                with open(calls) as f:
                    self.assertEqual(json.load(f), once, 'the kit sent a second start after an effort refusal')
                self.assertEqual((code, out), (1, [PASS[0], line] + NOT_RUN + [PASS[4]]), err)
                self.assertEqual(self.left(), [])

    def test_an_effort_refusal_that_may_have_left_a_run_starts_no_other(self):
        room = os.path.join(REPO, 'adapters', 'cloudroom')
        wrapper = os.path.join(self.folder, 'room')
        os.mkdir(wrapper)
        with open(os.path.join(wrapper, 'room-cli'), 'w') as f:
            f.write('#!%s -I\nimport os, sys\nargs, env = sys.argv[1:], dict(os.environ)\n'
                    'if args[:2] == ["thread", "spawn"] and "--reasoning-level" in args:\n'
                    '    env["FAKE_ROOM_RECEIPT"] = "Synthetic lost receipt"\n'
                    'os.execve(sys.executable, [sys.executable, %r] + args, env)\n'
                    % (sys.executable, os.path.join(room, 'fixtures', 'room-cli')))
        os.chmod(os.path.join(wrapper, 'room-cli'), 0o700)
        log = os.path.join(self.folder, 'room.log')
        code, out, err = self.kit(os.path.join(room, 'driver'), PATH=wrapper + os.pathsep + self.env['PATH'],
                                  ROOM_PROJECT_ID='prj_syn_0001', ROOM_THREAD_ID='thr_syn_parent', FAKE_ROOM_LOG=log,
                                  FAKE_ROOM_HOST='cloud', OPENWIZ_CLOUDROOM_STATE=os.path.join(self.folder, 'room'))
        with open(log) as f:
            calls = [c[:2] for c in (json.loads(line) for line in f) if c[:2] in (['thread', 'spawn'],
                                                                                  ['thread', 'archive'])]
        with open(log + '.threads') as f:
            active = [t for t, v in json.load(f).items() if not v.get('archived')]
        self.assertEqual(code, 1, err)
        self.assertEqual(calls, [['thread', 'spawn']], 'the kit started a second run')
        self.assertRegex(out[1], r'^fail start: run (run-\S+): .*; next: stop \1, which ends any thread it started, '
                                 r'then start a new run$')
        self.assertEqual(len(active), 1)

    def test_without_proc_as_on_macos_effort_on_a_command_line_is_seen(self):
        for name in ('effort', 'planted/effort-dropped'):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                lines = [x % EFFORT_WHY.get(name, '') if x.startswith('fail start') else x for x in EFFORT[name]]
                code, out, err = self.kit(os.path.join(FIXTURES, name, 'driver'), os.path.join(NO_PROC, 'python3'),
                                          PATH=NO_PROC + os.pathsep + self.env['PATH'], NO_PROC_PYTHON=sys.executable)
                self.assertEqual((code, out), (int(name != 'effort'), lines), err)

    def test_the_effort_flag_names_the_value_the_kit_sends(self):
        args = os.path.join(self.folder, 'args')
        code, out, err = self.kit(os.path.join(FIXTURES, 'effort', 'driver'), extra=['--effort', 'xhigh'],
                                  FAKE_ARGS=args)
        self.assertEqual((code, out[1]), (0, STARTED + '; effort: xhigh reached a process the run started'), err)
        self.assertEqual(efforts(args), ['xhigh', 'xhigh'])
        code, out, err = self.kit(BASE, extra=['--effort', 'Not A Word'])
        self.assertEqual((code, out), (2, []), err)

    def test_changing_only_the_effort_changes_what_the_kit_saw(self):
        for word in ('low', 'high'):
            with self.subTest(word):
                self.tearDown()
                self.setUp()
                args = os.path.join(self.folder, 'args')
                code, out, err = self.kit(os.path.join(FIXTURES, 'effort', 'driver'), extra=['--effort', word],
                                          FAKE_ARGS=args)
                self.assertEqual((code, out[1]), (0, STARTED + '; effort: %s reached a process the run started'
                                                  % word), err)
                self.assertEqual(efforts(args), [word, word])

    def test_the_effort_word_in_another_input_is_no_receipt(self):
        why = 'fail start: effort: medium never reached a process the run started'
        for name, extra in (('planted/effort-dropped', ['--model', 'medium']), ('planted/effort-word-elsewhere', [])):
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                code, out, err = self.kit(os.path.join(FIXTURES, name, 'driver'), extra=extra)
                self.assertEqual((code, out), (1, [PASS[0], why] + NOT_RUN + [PASS[4]]), err)

    def test_a_word_the_readme_does_not_list_may_be_refused_and_the_rest_runs_without_effort(self):
        args = os.path.join(self.folder, 'args')
        code, out, err = self.kit(os.path.join(FIXTURES, 'effort', 'driver'), extra=['--effort', 'turbo'],
                                  FAKE_ARGS=args)
        self.assertEqual((code, out), (0, [PASS[0], STARTED + '; effort: refused turbo with the refusal text, a word '
                                           'its README does not list for fake-harness'] + PASS[2:]), err)
        self.assertEqual(efforts(args), [])

    def test_the_setting_is_the_effort_placeholder_and_a_list_follows_the_setting(self):
        kit = module(os.path.join(HERE, 'kit.py'))
        cases = [('`--effort <level>`', ('argv', '--effort', 'medium'), None),
                 ('`set -s <run> effort <effort>`, for each level `claude-agent-acp` 0.95 lists',
                  ('argv', 'effort', 'medium'), None),
                 ('`-c model_reasoning_effort=<level>`, for low and high, with any harness',
                  ('argv', '-c', 'model_reasoning_effort=medium'), ['low', 'high']),
                 ('passed as `--effort <level>`, for low, medium, high, xhigh and max, with any harness',
                  ('argv', '--effort', 'medium'), ['low', 'medium', 'high', 'xhigh', 'max']),
                 ('the `effort` field of the start request', ('field', 'effort'), None)]
        for text, want, words in cases:
            with self.subTest(text):
                self.assertEqual((kit.setting(text, 'medium'), kit.listed(text)), (want, words))

    def test_effort_given_only_to_a_one_shot_host_command_during_start_is_seen(self):
        args = os.path.join(self.folder, 'args')
        code, out, err = self.kit(os.path.join(FIXTURES, 'effort-one-shot', 'driver'), FAKE_ARGS=args)
        self.assertEqual((code, out), (0, EFFORT['effort-one-shot']), err)
        with open(args) as f:
            calls = [json.loads(x) for x in f]
        self.assertEqual([c for c in calls if c[:2] == ['thread', 'spawn']],
                         [['thread', 'spawn', '--reasoning-level', 'medium']])
        self.assertEqual(efforts(args), [])

    def test_effort_that_first_shows_after_starts_verdict_is_no_receipt(self):
        late = os.path.join(self.folder, 'late')
        code, out, err = self.kit(os.path.join(FIXTURES, 'planted', 'effort-only-at-cleanup', 'driver'), FAKE_LATE=late)
        self.assertEqual((code, out), (1, [EFFORT_FAIL[0], EFFORT_FAIL[1] % 'medium never reached a process the run '
                                           'started'] + EFFORT_FAIL[2:] + [PASS[4]]), err)
        with open(late) as f:
            self.assertEqual(len(f.read().split()), 1, "the kit's cleanup stop did not run")

    def test_each_key_host_effort_driver_prints_its_own_start_line(self):
        for name, lines in EFFORT_KEY.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                code, out, host = self.keyed(os.path.join(FIXTURES, name, 'driver'))
                self.assertEqual((code, out), (0 if all(x.startswith('pass') for x in lines) else 1, lines))

    def test_without_proc_as_on_macos_the_template_passes_all_five(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        self.assertEqual(self.kit(TEMPLATE, os.path.join(NO_PROC, 'python3'), **macos)[:2],
                         (0, template_expected()[0]))
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

    def test_a_driver_whose_processes_live_only_during_each_call_passes_all_five_on_linux_and_macos(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        for python, env in ((sys.executable, {}), (os.path.join(NO_PROC, 'python3'), macos)):
            with self.subTest(python=python):
                self.tearDown()
                self.setUp()
                env = dict(env, PATH=NO_PROC + os.pathsep + self.env['PATH']) if env else {}
                code, out, err = self.kit(os.path.join(FIXTURES, 'short-lived-driver'), python, **env)
                self.assertEqual((code, out), (0, PASS), err)

    def test_each_effort_form_samples_its_one_main_start_and_no_other_start(self):
        plain, main = {'sampled': 0, 'effort': True, 'token': False, 'canary': False}, \
            {'sampled': 1, 'effort': False, 'token': False, 'canary': False}
        probe = dict(main, sampled=0, token=True)
        forms = {'taken': (os.path.join(FIXTURES, 'effort', 'driver'), [dict(main, effort=True), probe]),
                 'refused': (os.path.join(FIXTURES, 'effort-refused', 'driver'),
                             [dict(plain, sampled=1), main, probe]),
                 'undeclared': (BASE, [plain, main, probe]),
                 'key-host': (os.path.join(FIXTURES, 'effort-key-host', 'driver'),
                              [dict(plain, canary=True), dict(main, effort=True), probe, dict(main, canary=True)])}
        for form, (driver, starts) in forms.items():
            with self.subTest(form=form):
                self.tearDown()
                self.setUp()
                calls = os.path.join(self.folder, 'calls')
                if form == 'key-host':
                    code, out, _ = self.keyed(driver, script=os.path.join('fixtures', 'recorded-kit'), KIT_CALLS=calls)
                else:
                    code, out, _ = self.kit(driver, script=os.path.join('fixtures', 'recorded-kit'), KIT_CALLS=calls)
                self.assertEqual([line.partition(':')[0] for line in out], ['pass ' + n for n in CHECKS], out)
                with open(calls) as f:
                    self.assertEqual(json.load(f), starts)

    def test_a_child_living_only_during_the_main_start_is_watched_in_every_effort_form_on_linux_and_macos(self):
        macos = {'PATH': NO_PROC + os.pathsep + self.env['PATH'], 'NO_PROC_PYTHON': sys.executable}
        for form in ('undeclared', 'refused', 'key-host'):
            for python, env in ((sys.executable, {}), (os.path.join(NO_PROC, 'python3'), macos)):
                with self.subTest(form=form, python=python):
                    self.tearDown()
                    self.setUp()
                    starts = os.path.join(self.folder, 'starts')
                    driver = os.path.join(FIXTURES, 'start-child', form, 'driver')
                    if form == 'key-host':
                        code, out, _ = self.keyed(driver, python=python, FAKE_STARTS=starts, **env)
                    else:
                        code, out, _ = self.kit(driver, python, FAKE_STARTS=starts, **env)
                    self.assertEqual([line.partition(':')[0] for line in out],
                                     ['pass ' + n for n in CHECKS[:4]] + ['fail token'], out)
                    self.assertEqual(out[4], 'fail token: ' + IN_ARGS)
                    with open(starts) as f:
                        self.assertEqual(len(f.read().split()), 2 if form == 'key-host' else 1,
                                         "a start ran other than the main start and the key host's effort start")

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
            for name in ('base', 'stop-leaves-run', 'token-in-env'):
                with self.subTest(hide=hide, driver=name):
                    self.tearDown()
                    self.setUp()
                    driver = BASE if name == 'base' else os.path.join(FIXTURES, 'planted', name)
                    code, out, err = self.kit(driver, os.path.join(NO_PROC, 'python3'), **{hide: '1'},
                                              PATH=NO_PROC + os.pathsep + self.env['PATH'],
                                              NO_PROC_PYTHON=sys.executable)
                    start = PASS[:3] if name == 'base' else CANT_PASS[:3]
                    self.assertEqual((code, out), (1, start + ['fail stop: ' + why, 'fail token: ' + why]), err)
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
        code, out, err = self.kit(BASE, wait='2', PATH=sleepy + os.pathsep + self.env['PATH'])
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
            self.kit(BASE, PATH=outside + os.pathsep + self.env['PATH'])

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
                self.assertEqual((code, out), (1, CANT_PASS[:3] + [
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
                self.assertEqual((code, out), (1, CANT_PASS[:4] + ['fail token: the driver printed a credential']))
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
                 json.dumps(dict(good, harness='/usr/bin/true')), json.dumps(dict(good, model='m' * 101)),
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

    def model_start(self, model):
        start = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'synthetic-none',
                 'model': model}
        sys.path.insert(0, HERE)
        import kit
        schema = kit.invalid(start, kit.load_schema()['commands']['start']['input'])
        p = subprocess.run([LOCAL, 'start'], input=json.dumps(start), capture_output=True, text=True, timeout=60,
                           env=dict(self.env, OPENWIZ_LOCAL_STATE=os.path.join(self.folder, 'local')))
        return schema, p.returncode, json.loads(p.stdout)['error'], kit.holds_credential(model)

    def test_real_provider_qualified_models_pass_the_schema_and_the_local_driver(self):
        for model, source in REAL_MODELS.items():
            with self.subTest(model, source=source):
                self.assertEqual(self.model_start(model),
                                 (None, 1, 'harness synthetic-none is not one this driver runs', False))

    def test_bad_model_shapes_are_refused_by_the_schema_and_the_local_driver(self):
        for model in BAD_MODELS:
            with self.subTest(model):
                schema, code, error, _ = self.model_start(model)
                self.assertRegex(schema, '^model (does not match|has the wrong length)')
                self.assertEqual((code, error), (1, 'model is not valid'))
        self.assertEqual(self.model_start('m' * 100)[:3],
                         (None, 1, 'harness synthetic-none is not one this driver runs'))

    def test_a_credential_sent_as_a_provider_qualified_model_is_still_refused(self):
        for model in ('s' + 'k-' + 'Synthetic0Model0Value00', 'openrouter/s' + 'k-' + 'Synthetic0Model0Value00'):
            with self.subTest(model):
                self.assertEqual(self.model_start(model)[1:],
                                 (1, 'model looks like a credential, so nothing was saved or started', True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
