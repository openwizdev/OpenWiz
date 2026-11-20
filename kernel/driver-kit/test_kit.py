#!/usr/bin/env python3
"""D1, D2: the driver kit passes the template on a throwaway ticket and fails each planted bad driver.

Run: python3 -I kernel/driver-kit/test_kit.py   (Linux: the kit watches /proc)
"""
import importlib.machinery
import importlib.util
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
FIXTURES = os.path.join(HERE, 'fixtures')
TEMPLATE = os.path.join(HERE, '..', '..', 'adapters', 'template', 'driver')
NO_PROC = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit', 'fixtures', 'no-proc')
# A synthetic value in a GitHub token's shape, built here so no file holds one.
TOKEN = 'gh' + 'p_' + 'Synthetic0Kit0Value' * 2 + '00'
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 2',
        'pass wake: the run edited builder status note 2',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
# Each planted driver, with the exact lines the kit must print for it, and nothing else.
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


# The credential formats the pinned status contract lists (agent-status v1, "What it never holds").
CONTRACT_FORMATS = ['token=', 'key=', 'secret=', 'password=', 'sig=', 'password:', 'Bearer', 'gh?_', 'github_pat_',
                    'AKIA', 'xox?-', 'sk-']


def planted(name):
    """A planted driver's module, without running it."""
    path = os.path.join(FIXTURES, 'planted', name)
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tracker(folder):
    """A throwaway ticket: one older note from an earlier run, which the kit must leave alone."""
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
                        PATH=FIXTURES + os.pathsep + os.environ.get('PATH', ''))

    def tearDown(self):
        # A planted driver can leave its fake harness running: end every process this test started.
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('KIT_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass

    def kit(self, driver, python=sys.executable, **env):
        p = subprocess.run([python, '-I', os.path.join(HERE, 'kit.py'), '--driver', driver,
                            '--repo', 'example/site', '--ticket', '7', '--harness', 'fake-harness',
                            '--model', 'Synthetic 1', '--tracker', self.env['KIT_TRACKER'], '--wait', '8'],
                           env=dict(self.env, **env), capture_output=True, text=True, timeout=120)
        return p.returncode, p.stdout.splitlines(), p.stderr

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

    def test_without_proc_or_any_visible_environment_stop_and_token_fail_unverified(self):
        blind = "ps shows no process's environment here, so the kit cannot tell which processes the driver started"
        expected = {'template': PASS[:3] + ['fail stop: ' + blind, 'fail token: ' + blind],
                    'stop-leaves-run': PASS[:3] + ['fail stop: ' + blind, 'fail token: ' + blind],
                    'token-in-env': PASS[:3] + ['fail stop: ' + blind, 'fail token: ' + blind]}
        for name, lines in expected.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                driver = TEMPLATE if name == 'template' else os.path.join(FIXTURES, 'planted', name)
                code, out, err = self.kit(driver, os.path.join(NO_PROC, 'python3'), NO_PROC_HIDE_ENV='1',
                                          PATH=NO_PROC + os.pathsep + self.env['PATH'], NO_PROC_PYTHON=sys.executable)
                self.assertEqual((code, out), (1, lines), err)

    def test_each_planted_driver_fails_its_check(self):
        for name, lines in PLANTED.items():
            with self.subTest(name):
                self.tearDown()
                self.setUp()
                self.assertEqual(self.kit(os.path.join(FIXTURES, 'planted', name))[:2], (1, lines))

    def test_a_refusal_holding_a_credential_never_reaches_the_output(self):
        # #1524: the kit used to print a refusal's error text as its diagnostic, credential and all.
        # Escaped: the JSON text holds only \\u escapes, and decoding restores the credential.
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
        # #1568: the kit's shapes missed formats the status contract lists, when no secret of its environment held them.
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
