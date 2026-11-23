#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
FIXTURES = os.path.join(HERE, 'fixtures', 'receipts')
COPIED = ['kernel/live-rig/receipt.py', 'kernel/live-rig/rig.py', 'kernel/live-rig/listings.json',
          'kernel/driver-kit/kit.py', 'kernel/driver-kit/schema.json', 'kernel/records-kit/check.py',
          'kernel/records.v1.md']
VPS_PAIRS = [('Conductor', 'claude', 'opus-5-5-1m'), ('Cursor', 'cursor', 'composer-2.5'),
             ('Factory', 'droid', 'claude-opus-5-5'), ('Hermes', 'claude', 'claude-opus-5-5'),
             ('Pane', 'claude', 'claude-opus-5-5')]
RECORDS = os.path.join(FIXTURES, 'records')
EXPECTED = os.path.join(FIXTURES, 'expected')
WIZMARKET_FIXTURE = os.path.join(FIXTURES, 'wizmarket', 'verified-driver.txt')
WIZMARKET_SOURCE = 'fixtures/valid/verified-driver/receipts/example-driver/2026-11-01-aaaaaaaaaaaa.txt'
PRIVATE_IDS = [p + '_' + 'example1' for p in ('thr', 'proj', 'mch', 'usr', 'acct', 'cr')]
TOKEN = 'gh' + 'p_' + 'Synthetic0Receipt0Value' * 2
AGENT_CLIS = ('claude codex cursor-agent agent cursor pi opencode copilot goose gemini kimi qwen cline kilo kilocode '
              'crush vibe auggie kiro-cli junie amp agy oz sculpt hermes acpx droid boat room-cli runpane pane '
              'openhands devin warp grok codespaces conductor').split()
LOGIN = 'octo-example'
UUID = '12345678-1234-4abc-8def-123456789abc'
NOT_CONFIGURED = 'the run record host, harness and model are not one runs entry of a tracked host config'
NOT_FIVE = 'the run is not 5 of 5 pass'


def stubs():
    d = tempfile.mkdtemp(prefix='receipt-stubs-')
    for name in AGENT_CLIS:
        path = os.path.join(d, name)
        with open(path, 'w') as f:
            f.write('#!/bin/sh\necho "refused: %s is a test stub" >&2\nexit 1\n' % name)
        os.chmod(path, 0o755)
    return d


STUBS = stubs()


def record(name, **changes):
    with open(os.path.join(RECORDS, name)) as f:
        r = json.load(f)
    r.update(changes)
    return r


def files(root):
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _, fs in os.walk(root) for f in fs)


KIT_TESTS = os.path.join(HERE, '..', 'driver-kit', 'test_kit.py')
MAPPED = [('local', 'local'), ('boat.dev', 'boat-dev'), ('Cloudroom', 'cloudroom'), ('Hermes', 'hermes'),
          ('Pane', 'pane'), ('Factory', 'factory'), ('Conductor', 'conductor'), ('Cursor', 'cursor-cloud-agents')]
NOT_TOKENS = ['', 'Claude', 'Example Harness', 'someone@example.com', '/tmp/example', 'C:\\example',
              'two\nlines', 'tab\there', '\ud800', 'caf\u00e9', '\u0661\u0662', '-leading', '.leading', 'a' * 61,
              1, None, ['claude']]
CONFIGURED = [('claude', 'example-model'), ('codex', 'gpt-5.1'), ('opencode', 'o3')]


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=Example', '-c', 'user.email=example@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null'] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def checkout(dest, extra=None, init=True):
    for path in COPIED:
        os.makedirs(os.path.dirname(os.path.join(dest, path)), exist_ok=True)
        shutil.copy2(os.path.join(ROOT, path), os.path.join(dest, path))
    configs = {os.path.join('kernel', 'live-rig', 'hosts', n): t for n, t in LOCAL_CONFIGS.items()}
    configs.update({os.path.join('kernel', 'live-rig', 'vps', 'hosts', n): t for n, t in VPS_CONFIGS.items()})
    configs.update(extra or {})
    for rel, text in configs.items():
        os.makedirs(os.path.dirname(os.path.join(dest, rel)), exist_ok=True)
        with open(os.path.join(dest, rel), 'w') as f:
            f.write(text)
    if init:
        git(dest, 'init', '-q')
        git(dest, 'add', '-A')
        git(dest, 'commit', '-q', '-m', 'fixture checkout')
    return os.path.join(dest, 'kernel', 'live-rig', 'receipt.py')


VPS_CONFIGS = {
    'conductor.json': (
        '{\n'
        '  "host": "Conductor",\n'
        '  "driver": "adapters/conductor/driver",\n'
        '  "needs": ["curl", "gh"],\n'
        '  "signed_in": [["python3", "-I", "-c", "import sys, os; sys.exit(0 if any(n == '
        '\'CONDUCTOR_API_KEY\' for n in os.environ) else 1)"], ["gh", "auth", "status", '
        '"--hostname", "github.com", "--active", "--no-refresh"]],\n'
        '  "cost": "paid",\n'
        '  "runs": [{"harness": "claude", "model": "opus-5-5-1m"}],\n'
        '  "wait": 900\n'
        '}\n'),
    'cursor.json': (
        '{\n'
        '  "host": "Cursor",\n'
        '  "driver": "adapters/cursor/driver",\n'
        '  "needs": ["curl", "gh"],\n'
        '  "signed_in": [["python3", "-I", "-c", "import sys, os; sys.exit(0 if any(n == '
        '\'CURSOR_API_KEY\' for n in os.environ) else 1)"], ["gh", "auth", "status", "--hostname", '
        '"github.com", "--active", "--no-refresh"]],\n'
        '  "cost": "paid",\n'
        '  "runs": [{"harness": "cursor", "model": "composer-2.5"}],\n'
        '  "wait": 900\n'
        '}\n'),
    'factory.json': (
        '{\n'
        '  "host": "Factory",\n'
        '  "driver": "adapters/factory/driver",\n'
        '  "needs": ["droid", "gh"],\n'
        '  "signed_in": [["python3", "-I", "-c", "import sys, os; sys.exit(0 if any(n == '
        '\'FACTORY_API_KEY\' for n in os.environ) else 1)"], ["gh", "auth", "status", "--hostname", '
        '"github.com", "--active", "--no-refresh"]],\n'
        '  "cost": "paid",\n'
        '  "runs": [{"harness": "droid", "model": "claude-opus-5-5"}],\n'
        '  "wait": 900\n'
        '}\n'),
    'hermes.json': (
        '{\n'
        '  "host": "Hermes",\n'
        '  "driver": "adapters/hermes/driver",\n'
        '  "needs": ["hermes", "gh"],\n'
        '  "signed_in": [["gh", "auth", "status", "--hostname", "github.com", "--active", '
        '"--no-refresh"]],\n'
        '  "cost": "paid",\n'
        '  "runs": [{"harness": "claude", "model": "claude-opus-5-5"}],\n'
        '  "wait": 900\n'
        '}\n'),
    'pane.json': (
        '{\n'
        '  "host": "Pane",\n'
        '  "driver": "adapters/pane/driver",\n'
        '  "needs": ["runpane", "gh"],\n'
        '  "signed_in": [["runpane", "repos", "list", "--json"], ["gh", "auth", "status", '
        '"--hostname", "github.com", "--active", "--no-refresh"]],\n'
        '  "cost": "paid",\n'
        '  "runs": [{"harness": "claude", "model": "claude-opus-5-5"}],\n'
        '  "wait": 900\n'
        '}\n'),
}


def config(host, harness, model, more=()):
    return json.dumps({'host': host, 'driver': 'adapters/example/driver', 'needs': ['gh'],
                       'signed_in': [['gh', 'auth', 'status']], 'cost': 'none',
                       'runs': [{'harness': harness, 'model': model}] + [{'harness': h, 'model': m} for h, m in more],
                       'wait': 900}) + '\n'


LOCAL_CONFIGS = {'local.json': config('local', *CONFIGURED[0], more=CONFIGURED[1:]),
                 'boat-dev.json': config('boat.dev', *CONFIGURED[0]),
                 'cloudroom.json': config('Cloudroom', *CONFIGURED[0])}


def kit_test_pass_lines():
    spec = importlib.util.spec_from_loader('kit_tests', importlib.machinery.SourceFileLoader('kit_tests', KIT_TESTS))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PASS


class Receipt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.mkdtemp(prefix='receipt-checkout-')
        cls.receipt = checkout(cls.folder)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='receipt-test-')
        self.out = os.path.join(self.tmp, 'out')
        os.mkdir(self.out)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def fresh(self):
        shutil.rmtree(self.out)
        os.mkdir(self.out)

    def run_receipt(self, rec, listing='local', run_by='example-runner', env=None, raw=None, args=None,
                    preexec=None, receipt=None):
        path = os.path.join(self.tmp, 'record.json')
        with open(path, 'wb') as f:
            f.write(raw if raw is not None else json.dumps(rec).encode())
        e = dict(os.environ, PATH=STUBS + os.pathsep + os.environ.get('PATH', ''))
        e.pop('OPENWIZ_GITHUB_APP_KEY', None)
        e.update(env or {})
        argv = args if args is not None else [path, '--listing=' + listing, '--run-by=' + run_by, '-o', self.out]
        return subprocess.run([sys.executable, '-I', receipt or self.receipt] + argv, capture_output=True, text=True,
                              env=e, timeout=60, preexec_fn=preexec)

    def written(self, rel):
        with open(os.path.join(self.out, rel), 'rb') as f:
            return f.read()

    def one_line(self, p, code, why):
        self.assertEqual(p.returncode, code, p.stderr)
        self.assertEqual(p.stdout, '')
        self.assertEqual(p.stderr, 'receipt.py: %s\n' % why)

    def refused(self, rec, why, **kw):
        p = self.run_receipt(rec, **kw)
        self.one_line(p, 1, why)
        self.assertEqual(files(self.out), [], 'a refused record wrote a file')
        return p.stderr

    def test_five_of_five_gives_the_byte_exact_receipt(self):
        p = self.run_receipt(record('5-of-5.json'))
        self.assertEqual(p.returncode, 0, p.stderr)
        rel = os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')
        self.assertEqual(files(self.out), [rel])
        with open(os.path.join(EXPECTED, rel), 'rb') as f:
            self.assertEqual(self.written(rel), f.read())
        self.assertEqual(p.stdout, os.path.join(self.out, rel) + '\n')
        self.assertEqual(p.stderr, '')

    def test_receipt_matches_wizmarkets_own_valid_fixture(self):
        self.assertEqual(self.run_receipt(record('5-of-5.json')).returncode, 0)
        ours = self.written(os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')).decode()
        with open(WIZMARKET_FIXTURE) as f:
            theirs = f.read()
        self.assertEqual(len(ours.splitlines(True)), 14)
        self.assertEqual([l.split(': ', 1)[0] for l in ours.splitlines(True)[:8]],
                         [l.split(': ', 1)[0] for l in theirs.splitlines(True)[:8]])
        self.assertEqual(ours.splitlines(True)[8:], theirs.splitlines(True)[8:])

    def test_the_kits_own_tested_pass_lines_make_a_receipt(self):
        kit_pass = kit_test_pass_lines()
        p = self.run_receipt(record('5-of-5.json', stdout='\n'.join(kit_pass) + '\n'))
        self.assertEqual(p.returncode, 0, p.stderr)
        body = self.written(os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')).decode()
        self.assertEqual(body.splitlines()[8:13], [re.sub(r'note [0-9]+$', 'note <note>', l) for l in kit_pass])

    def test_four_of_five_writes_nothing(self):
        self.refused(record('4-of-5.json'), 'kit.py exited non-zero, not 0')

    def test_a_nonzero_exit_is_one_fixed_line_without_its_value(self):
        for code in (2, -9, 123456789012):
            with self.subTest(code=code):
                err = self.refused(record('4-of-5.json', kit_exit=code), 'kit.py exited non-zero, not 0')
                self.assertNotIn(str(abs(code)), err)

    def test_a_too_deep_record_is_one_fixed_line(self):
        for raw in (b'[' * 50000, b'{"a": ' * 10000):
            with self.subTest(raw=raw[:8]):
                self.refused(None, 'the run record is not readable JSON with each key once', raw=raw)

    def test_a_too_large_record_is_one_fixed_line(self):
        text = json.dumps(record('5-of-5.json')).encode()
        self.refused(None, 'the run record is larger than 64 KiB', raw=text + b' ' * (65536 - len(text) + 1))
        p = self.run_receipt(None, raw=text + b' ' * (65536 - len(text)))
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a_fail_line_with_exit_0_writes_nothing(self):
        self.refused(record('4-of-5.json', kit_exit=0), NOT_FIVE)

    def test_any_count_short_of_five_is_one_fixed_line(self):
        lines = record('5-of-5.json')['stdout'].splitlines(True)
        for k in range(5):
            with self.subTest(k=k):
                out = ''.join(l.replace('pass ', 'fail ', 1) if n >= k else l for n, l in enumerate(lines))
                err = self.refused(record('5-of-5.json', stdout=out), NOT_FIVE)
                self.assertNotIn(str(k) + ' of', err)

    def test_skipped_record_writes_nothing(self):
        self.refused(record('skipped.json'), 'the run record is a skipped run')

    def test_lines_out_of_order_write_nothing(self):
        self.refused(record('out-of-order.json'),
                     "kit.py's lines are out of order; the order is version, start, wake, stop, token")

    def test_a_missing_or_extra_line_writes_nothing(self):
        lines = record('5-of-5.json')['stdout'].splitlines(True)
        self.refused(record('5-of-5.json', stdout=''.join(lines[:4])), "kit.py's stdout does not have its five lines")
        self.refused(record('5-of-5.json', stdout=''.join(lines) + 'pass extra: more\n'),
                     "kit.py's stdout does not have its five lines")
        self.refused(record('5-of-5.json', stdout=''.join(lines)[:-1]), "kit.py's stdout does not end in a newline")

    def test_a_credential_shape_in_a_token_writes_nothing(self):
        shape = 'claude-sk-' + 'synthetic0receipt0' * 2
        self.refused(record('5-of-5.json', model=shape), 'line 6 holds a credential shape')

    def test_a_secret_from_the_environment_writes_nothing(self):
        value = 'claude-synthetic-environment-value-0001'
        self.refused(record('5-of-5.json', model=value), 'line 6 holds a credential shape',
                     env={'EXAMPLE_SERVICE_TOKEN': value})

    def test_harness_and_model_must_be_public_tokens(self):
        for key in ('harness', 'model'):
            for value in NOT_TOKENS:
                with self.subTest(key=key, value=value):
                    self.fresh()
                    self.refused(record('5-of-5.json', **{key: value}), 'the run record %s is not a public token' % key)
        for harness, model in CONFIGURED:
            with self.subTest(harness=harness, model=model):
                self.fresh()
                p = self.run_receipt(record('5-of-5.json', harness=harness, model=model))
                self.assertEqual(p.returncode, 0, p.stderr)
                text = self.written(os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')).decode()
                self.assertIn('# harness: %s\n# model: %s\n' % (harness, model), text)

    def test_a_login_as_harness_or_model_writes_nothing(self):
        for value in (LOGIN, 'example-runner', 'example-login', 'example', 'model', 'a', '0', 'a' * 60):
            with self.subTest(value=value):
                self.refused(record('5-of-5.json', harness=value), NOT_CONFIGURED)
                self.refused(record('5-of-5.json', model=value), NOT_CONFIGURED)

    def test_a_login_shaped_model_writes_nothing(self):
        for value in ('claude-' + LOGIN, 'gpt-example-runner', 'claude-opus-' + LOGIN, 'o12345678', 'o1-' + LOGIN,
                      'gemini-example-login', 'example-model-' + LOGIN):
            with self.subTest(value=value):
                self.refused(record('5-of-5.json', model=value), NOT_CONFIGURED)
        self.refused(record('5-of-5.json', harness='claude-' + LOGIN), NOT_CONFIGURED)

    def test_each_vps_configs_exact_pair_makes_a_receipt(self):
        with open(os.path.join(ROOT, 'kernel', 'live-rig', 'listings.json')) as f:
            listings = json.load(f)
        found = []
        for name in sorted(VPS_CONFIGS):
            c = json.loads(VPS_CONFIGS[name])
            found += [(c['host'], r['harness'], r['model']) for r in c['runs']]
        self.assertEqual(found, VPS_PAIRS)
        for host, harness, model in VPS_PAIRS:
            with self.subTest(host=host):
                self.fresh()
                p = self.run_receipt(record('5-of-5.json', host=host, harness=harness, model=model),
                                     listing=listings[host])
                self.assertEqual(p.returncode, 0, p.stderr)
                text = self.written(os.path.join('receipts', listings[host], '2026-11-01-aaaaaaaaaaaa.txt')).decode()
                self.assertIn('# host: %s\n' % host, text)
                self.assertIn('# harness: %s\n# model: %s\n' % (harness, model), text)

    def test_a_pair_in_no_config_writes_nothing(self):
        for host, harness, model, listing in (
                ('Conductor', 'claude', 'claude-opus-5-5', 'conductor'),
                ('Hermes', 'claude', 'opus-5-5-1m', 'hermes'),
                ('Factory', 'claude', 'claude-opus-5-5', 'factory'),
                ('Cursor', 'cursor', 'example-model', 'cursor-cloud-agents'),
                ('local', 'codex', 'example-model', 'local'),
                ('local', 'claude', 'gpt-5.1', 'local'),
                ('local', 'droid', 'claude-opus-5-5', 'local'),
                ('boat.dev', 'codex', 'gpt-5.1', 'boat-dev')):
            with self.subTest(host=host, harness=harness, model=model):
                self.refused(record('5-of-5.json', host=host, harness=harness, model=model), NOT_CONFIGURED,
                             listing=listing)

    def own_checkout(self, extra=None, init=True):
        dest = os.path.join(self.tmp, 'checkout')
        shutil.rmtree(dest, ignore_errors=True)
        return dest, checkout(dest, extra, init)

    def test_only_tracked_unchanged_regular_configs_count(self):
        login = record('5-of-5.json', model='claude-' + LOGIN)
        added = config('local', 'claude', 'claude-' + LOGIN)
        dest, receipt = self.own_checkout()
        with open(os.path.join(dest, 'kernel', 'live-rig', 'hosts', 'untracked.json'), 'w') as f:
            f.write(added)
        self.refused(login, NOT_CONFIGURED, receipt=receipt)
        git(dest, 'add', '-A')
        self.refused(login, NOT_CONFIGURED, receipt=receipt)
        git(dest, 'commit', '-q', '-m', 'tracked now')
        self.assertEqual(self.run_receipt(login, receipt=receipt).returncode, 0)
        self.fresh()
        dest, receipt = self.own_checkout()
        with open(os.path.join(dest, 'kernel', 'live-rig', 'hosts', 'local.json'), 'w') as f:
            f.write(added)
        self.refused(login, NOT_CONFIGURED, receipt=receipt)
        dest, receipt = self.own_checkout()
        with open(os.path.join(self.tmp, 'outside.json'), 'w') as f:
            f.write(added)
        os.symlink(os.path.join(self.tmp, 'outside.json'), os.path.join(dest, 'kernel', 'live-rig', 'hosts', 'l.json'))
        git(dest, 'add', '-A')
        git(dest, 'commit', '-q', '-m', 'a tracked symlink')
        self.refused(login, NOT_CONFIGURED, receipt=receipt)
        dest, receipt = self.own_checkout({'kernel/live-rig/stray.json': added})
        self.refused(login, NOT_CONFIGURED, receipt=receipt)
        for folder in ('hosts', os.path.join('vps', 'hosts')):
            with self.subTest(folder=folder):
                dest, receipt = self.own_checkout()
                real = os.path.join(self.tmp, 'real-hosts')
                shutil.rmtree(real, ignore_errors=True)
                os.rename(os.path.join(dest, 'kernel', 'live-rig', folder), real)
                with open(os.path.join(real, 'added.json'), 'w') as f:
                    f.write(added)
                os.symlink(real, os.path.join(dest, 'kernel', 'live-rig', folder))
                self.refused(login, NOT_CONFIGURED, receipt=receipt)

    def test_a_checkout_git_cannot_read_is_one_fixed_line(self):
        dest, receipt = self.own_checkout(init=False)
        self.refused(record('5-of-5.json'), 'the tracked host configs could not be read', receipt=receipt)
        git(self.tmp, 'init', '-q')
        git(self.tmp, 'add', 'checkout')
        git(self.tmp, 'commit', '-q', '-m', 'an outer repository tracks the checkout')
        self.refused(record('5-of-5.json'), 'the tracked host configs could not be read', receipt=receipt)

    def test_a_git_dir_from_the_environment_is_not_trusted(self):
        added = config('local', 'claude', 'claude-' + LOGIN)
        dest, receipt = self.own_checkout({'kernel/live-rig/hosts/added.json': added})
        other = checkout(os.path.join(self.tmp, 'other'))
        self.refused(record('5-of-5.json', model='claude-' + LOGIN), NOT_CONFIGURED, receipt=other,
                     env={'GIT_DIR': os.path.join(dest, '.git'), 'GIT_WORK_TREE': dest})

    def test_an_invalid_tracked_config_is_one_fixed_line(self):
        dest, receipt = self.own_checkout({'kernel/live-rig/vps/hosts/broken.json': '{"host": "Conductor"}\n'})
        self.refused(record('5-of-5.json'), 'a tracked host config is not a valid host config', receipt=receipt)

    def test_a_configured_private_id_or_credential_still_writes_nothing(self):
        shape = 'claude-sk-' + 'synthetic0receipt0' * 2
        for model, why in (('claude-' + UUID, 'line 6 holds a private id'),
                           ('claude-' + PRIVATE_IDS[0], 'line 6 holds a private id'),
                           (shape, 'line 6 holds a credential shape')):
            with self.subTest(model=model):
                added = config('local', 'claude', model)
                dest, receipt = self.own_checkout({'kernel/live-rig/hosts/added.json': added})
                self.refused(record('5-of-5.json', model=model), why, receipt=receipt)

    def test_a_uuid_shaped_id_writes_nothing(self):
        bare = UUID.replace('-', '')
        for value in (UUID, bare):
            with self.subTest(value=value):
                self.refused(record('5-of-5.json', harness=value), 'line 5 holds a private id')
                self.refused(record('5-of-5.json', model=value), 'line 6 holds a private id')
        for value in ('claude-' + UUID, 'gpt-' + bare, 'claude-opus-' + UUID + '-1'):
            with self.subTest(value=value):
                self.refused(record('5-of-5.json', model=value), 'line 6 holds a private id')

    def test_a_private_id_in_a_token_writes_nothing(self):
        for value in PRIVATE_IDS:
            with self.subTest(value=value):
                self.refused(record('5-of-5.json', harness=value), 'line 5 holds a private id')
                self.refused(record('5-of-5.json', model=value), 'line 6 holds a private id')
                self.refused(record('5-of-5.json', model='claude-' + value), 'line 6 holds a private id')

    def test_version_stop_and_token_must_be_kits_exact_pass_lines(self):
        base = record('5-of-5.json')['stdout']
        for old, new, check in (
                ('openwiz:records v1', 'openwiz:records v2', 'version'),
                ('and the schema is driver v1', 'and the schema is driver v1 ' + TOKEN, 'version'),
                ('is refused', 'is refused ' + PRIVATE_IDS[0], 'stop'),
                ('a wake after it is refused', 'a wake after it is refused, at /tmp/example', 'stop'),
                ('no login or token passed', 'nothing passed', 'token'),
                ('the driver\n', 'the driver \n', 'token')):
            with self.subTest(check=check, new=new):
                err = self.refused(record('5-of-5.json', stdout=base.replace(old, new)),
                                   "the %s line is not kit.py's passing %s line" % (check, check))
                self.assertNotIn(TOKEN, err)

    def test_start_and_wake_must_be_kits_text_with_only_the_note_id_varying(self):
        base = record('5-of-5.json')['stdout']
        for old, new, check in (
                ('posted builder status note', 'posted note', 'start'),
                ('posted builder status note 1000000001', 'posted builder status note 10a', 'start'),
                ('posted builder status note 1000000001', 'posted builder status note \u0661\u0662', 'start'),
                ('posted builder status note 1000000001', 'posted builder status note ', 'start'),
                ('note 1000000001\npass stop', 'note <note>\npass stop', 'wake'),
                ('note 1000000001\npass stop', 'note 1000000001 ' + PRIVATE_IDS[0] + '\npass stop', 'wake')):
            with self.subTest(new=new):
                self.refused(record('5-of-5.json', stdout=base.replace(old, new, 1)),
                             "the %s line is not kit.py's passing %s line" % (check, check))

    def test_start_and_wake_must_name_the_same_note(self):
        base = record('5-of-5.json')['stdout']
        for old, new in (('edited builder status note 1000000001', 'edited builder status note 1000000002'),
                         ('posted builder status note 1000000001', 'posted builder status note 1')):
            with self.subTest(new=new):
                err = self.refused(record('5-of-5.json', stdout=base.replace(old, new)),
                                   'the start and wake lines name different builder status notes')
                self.assertNotIn('100000000', err)

    def test_a_malformed_record_writes_nothing(self):
        consistent = 'the run record is not a consistent ran or skipped record'
        for changes, why in (
                ({'driver_commit': 'a' * 12}, 'the run record driver_commit is not a 40-hex lowercase commit'),
                ({'kit_commit': 'B' * 40}, 'the run record kit_commit is not a 40-hex lowercase commit'),
                ({'kit_commit': '\u0661' * 40}, 'the run record kit_commit is not a 40-hex lowercase commit'),
                ({'date': '2026-11-1'}, 'the run record date is not a real YYYY-MM-DD date'),
                ({'date': '2026-02-30'}, 'the run record date is not a real YYYY-MM-DD date'),
                ({'date': '2026-13-01'}, 'the run record date is not a real YYYY-MM-DD date'),
                ({'date': '\u0662\u0660\u0662\u0666-11-01'}, 'the run record date is not a real YYYY-MM-DD date'),
                ({'date': 20261101}, 'the run record date is not a real YYYY-MM-DD date'),
                ({'host': 7}, 'the run record host is not in listings.json'),
                ({'kit_exit': False}, consistent),
                ({'kit_exit': 0.0}, consistent),
                ({'kit_exit': '0'}, consistent),
                ({'kit_exit': None}, consistent),
                ({'skipped': 'not signed in: example-tool'}, consistent),
                ({'stdout': None}, consistent),
                ({'outcome': 'passed'}, consistent),
                ({'seconds': 1.5}, 'the run record seconds is not a whole number of seconds'),
                ({'seconds': True}, 'the run record seconds is not a whole number of seconds'),
                ({'seconds': -1}, 'the run record seconds is not a whole number of seconds'),
                ({'seconds': '412'}, 'the run record seconds is not a whole number of seconds')):
            with self.subTest(changes=changes):
                self.refused(record('5-of-5.json', **changes), why)
        rec = record('5-of-5.json')
        del rec['seconds']
        self.refused(rec, 'the run record does not have exactly the run record keys')
        self.refused(record('5-of-5.json', extra=1), 'the run record does not have exactly the run record keys')
        self.refused(record('skipped.json', skipped=None), consistent)
        self.refused(record('skipped.json', kit_exit=0), consistent)
        self.refused(record('skipped.json', stdout='pass version: x\n'), consistent)

    def test_an_unreadable_record_writes_nothing(self):
        why = 'the run record is not readable JSON with each key once'
        text = json.dumps(record('5-of-5.json'))
        for raw in (b'', b'{', b'\xff\xfe', b'[]', (text[:-1] + ', "seconds": 412}').encode(), b'{"a": NaN}'):
            with self.subTest(raw=raw[:20]):
                self.refused(None, why if raw != b'[]' else 'the run record does not have exactly the run record keys',
                             raw=raw)
        p = self.run_receipt(None, args=[os.path.join(self.tmp, 'missing.json'), '--listing=local',
                                         '--run-by=example-runner', '-o', self.out])
        self.one_line(p, 1, why)

    def test_a_withheld_line_writes_nothing(self):
        lines = record('5-of-5.json')['stdout'].splitlines()
        for n, check in enumerate(('version', 'start', 'wake', 'stop', 'token')):
            for verdict in ('pass', 'fail'):
                withheld = lines[:n] + ['%s %s: withheld' % (verdict, check)] + lines[n + 1:]
                with self.subTest(check=check, verdict=verdict):
                    self.refused(record('5-of-5.json', stdout='\n'.join(withheld) + '\n'),
                                 "the %s line is withheld in the run record; a receipt needs kit.py's line" % check)

    def test_an_unmapped_host_writes_nothing(self):
        for host in ('example-host', 'local\nsecond line', TOKEN, 'Local'):
            with self.subTest(host=host):
                err = self.refused(record('5-of-5.json', host=host), 'the run record host is not in listings.json')
                self.assertNotIn(TOKEN, err)

    def test_a_listing_that_is_not_this_runs_writes_nothing(self):
        self.refused(record('5-of-5.json'), "--listing is not this run's driver listing, and its harness has no "
                     'listing in listings.json', listing='claude')
        self.refused(record('5-of-5.json'), "--listing is not this run's driver listing, and its harness has no "
                     'listing in listings.json', listing='boat-dev')
        self.refused(record('5-of-5.json'), '--listing is not a listing id', listing='local\nsecond line')
        self.refused(record('5-of-5.json'), '--listing is not a listing id', listing=TOKEN)

    def test_every_mapped_host_names_its_listing(self):
        pairs = {h: (a, m) for h, a, m in VPS_PAIRS}
        for host, listing in MAPPED:
            with self.subTest(host=host):
                harness, model = pairs.get(host, ('claude', 'example-model'))
                p = self.run_receipt(record('5-of-5.json', host=host, harness=harness, model=model), listing=listing)
                self.assertEqual(p.returncode, 0, p.stderr)
                text = self.written(os.path.join('receipts', listing, '2026-11-01-aaaaaaaaaaaa.txt')).decode()
                self.assertTrue(text.startswith('# listing: %s\n# host: %s\n' % (listing, host)), text)

    def test_run_by_must_be_a_login(self):
        for login in ('/home/example', '-example', 'example-', 'exa--mple', 'a' * 40, 'two\nlines', ''):
            with self.subTest(login=login):
                self.refused(record('5-of-5.json'), '--run-by is not a GitHub login', run_by=login)

    def test_a_usage_error_is_one_fixed_line(self):
        usage = 'usage: receipt.py <run record> --listing <id> --run-by <login> -o <dir>'
        for args in ([], ['--bogus\nsecond line=' + TOKEN], ['record.json', '--listing=local']):
            with self.subTest(args=args):
                p = self.run_receipt(None, raw=b'', args=args)
                self.one_line(p, 2, usage)
                self.assertNotIn(TOKEN, p.stderr)

    def test_the_first_receipt_is_kept(self):
        self.assertEqual(self.run_receipt(record('5-of-5.json')).returncode, 0)
        rel = os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')
        first = self.written(rel)
        p = self.run_receipt(record('5-of-5.json', harness='codex', model='gpt-5.1'))
        self.one_line(p, 1, 'a receipt is already at its path; the first one is kept')
        self.assertEqual(self.written(rel), first)
        self.assertEqual(files(self.out), [rel])

    def test_a_failed_write_leaves_no_receipt(self):
        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (64, 64))
        p = self.run_receipt(record('5-of-5.json'), preexec=limit)
        self.one_line(p, 1, 'the receipt could not be written')
        self.assertEqual(files(self.out), [])

    def test_a_blocked_output_directory_leaves_no_receipt(self):
        with open(os.path.join(self.out, 'receipts'), 'w') as f:
            f.write('in the way\n')
        p = self.run_receipt(record('5-of-5.json'))
        self.one_line(p, 1, 'the receipt could not be written')
        self.assertEqual(files(self.out), ['receipts'])


class WizMarket(unittest.TestCase):

    def checkout(self):
        root = os.environ.get('WIZMARKET')
        if not root or not os.path.isdir(os.path.join(root, 'contracts')):
            self.skipTest('skipped: no WizMarket checkout reachable (set WIZMARKET to one)')
        return root

    def test_our_copy_of_the_fixture_is_wizmarkets(self):
        root = self.checkout()
        with open(os.path.join(root, WIZMARKET_SOURCE), 'rb') as a, open(WIZMARKET_FIXTURE, 'rb') as b:
            self.assertEqual(a.read(), b.read())

    def test_wizmarkets_checker_accepts_the_receipt(self):
        root = self.checkout()
        check = os.path.join(root, 'check', 'check.py')
        if not os.path.isfile(check):
            self.skipTest('skipped: WizMarket ships no check/check.py at this checkout')
        reg = tempfile.mkdtemp(prefix='receipt-registry-')
        try:
            rel = os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')
            os.makedirs(os.path.join(reg, 'listings'))
            os.makedirs(os.path.join(reg, os.path.dirname(rel)))
            shutil.copy(os.path.join(EXPECTED, rel), os.path.join(reg, rel))
            with open(os.path.join(reg, 'listings', 'local.json'), 'w') as f:
                json.dump({'name': 'Local', 'summary': 'Runs builders on your own computer.', 'tags': ['driver'],
                           'url': 'https://github.com/openwizdev/OpenWiz', 'plugs_into': 'The OpenWiz driver interface',
                           'publisher': 'example-runner', 'stage': 'available', 'status': 'verified',
                           'proof': {'receipt': rel.replace(os.sep, '/')}}, f, indent=2)
                f.write('\n')
            p = subprocess.run([sys.executable, '-I', check, 'check'], cwd=reg, capture_output=True, text=True,
                               timeout=120)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        finally:
            shutil.rmtree(reg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
