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
RECEIPT = os.path.join(HERE, 'receipt.py')
FIXTURES = os.path.join(HERE, 'fixtures', 'receipts')
RECORDS = os.path.join(FIXTURES, 'records')
EXPECTED = os.path.join(FIXTURES, 'expected')
WIZMARKET_FIXTURE = os.path.join(FIXTURES, 'wizmarket', 'verified-driver.txt')
WIZMARKET_SOURCE = 'fixtures/valid/verified-driver/receipts/example-driver/2026-11-01-aaaaaaaaaaaa.txt'
PRIVATE_IDS = [p + '_' + 'example1' for p in ('thr', 'proj', 'mch', 'usr', 'acct', 'cr')]
TOKEN = 'gh' + 'p_' + 'Synthetic0Receipt0Value' * 2
AGENT_CLIS = ('claude codex cursor-agent agent pi opencode copilot goose gemini kimi qwen cline kilo crush vibe '
              'auggie kiro-cli junie amp agy oz sculpt hermes acpx droid').split()


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
TOKENS = ['claude', 'codex', 'claude-opus-5-5', 'gpt-5.1', 'a', '0', 'a' * 60]


def kit_test_pass_lines():
    spec = importlib.util.spec_from_loader('kit_tests', importlib.machinery.SourceFileLoader('kit_tests', KIT_TESTS))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PASS


class Receipt(unittest.TestCase):
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
                    preexec=None):
        path = os.path.join(self.tmp, 'record.json')
        with open(path, 'wb') as f:
            f.write(raw if raw is not None else json.dumps(rec).encode())
        e = dict(os.environ, PATH=STUBS + os.pathsep + os.environ.get('PATH', ''))
        e.pop('OPENWIZ_GITHUB_APP_KEY', None)
        e.update(env or {})
        argv = args if args is not None else [path, '--listing=' + listing, '--run-by=' + run_by, '-o', self.out]
        return subprocess.run([sys.executable, '-I', RECEIPT] + argv, capture_output=True, text=True, env=e,
                              timeout=60, preexec_fn=preexec)

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
        self.refused(record('4-of-5.json'), 'kit.py exited 1, not 0')

    def test_a_fail_line_with_exit_0_writes_nothing(self):
        self.refused(record('4-of-5.json', kit_exit=0), 'the run is 4 of 5 pass, not 5 of 5')

    def test_skipped_record_writes_nothing(self):
        self.refused(record('skipped.json'), 'the run record is a skipped run')

    def test_lines_out_of_order_write_nothing(self):
        self.refused(record('out-of-order.json'),
                     "kit.py's lines are out of order; the order is version, start, wake, stop, token")

    def test_a_missing_or_extra_line_writes_nothing(self):
        lines = record('5-of-5.json')['stdout'].splitlines(True)
        self.refused(record('5-of-5.json', stdout=''.join(lines[:4])), "kit.py's stdout has 4 lines, not its five")
        self.refused(record('5-of-5.json', stdout=''.join(lines) + 'pass extra: more\n'),
                     "kit.py's stdout has 6 lines, not its five")
        self.refused(record('5-of-5.json', stdout=''.join(lines)[:-1]), "kit.py's stdout does not end in a newline")

    def test_a_credential_shape_in_a_token_writes_nothing(self):
        shape = 'sk-' + 'synthetic0receipt0' * 2
        self.refused(record('5-of-5.json', model=shape), 'line 6 holds a credential shape')

    def test_a_secret_from_the_environment_writes_nothing(self):
        value = 'synthetic-environment-value-0001'
        self.refused(record('5-of-5.json', model=value), 'line 6 holds a credential shape',
                     env={'EXAMPLE_SERVICE_TOKEN': value})

    def test_harness_and_model_must_be_public_tokens(self):
        for key in ('harness', 'model'):
            for value in NOT_TOKENS:
                with self.subTest(key=key, value=value):
                    self.fresh()
                    self.refused(record('5-of-5.json', **{key: value}), 'the run record %s is not a public token' % key)
            for value in TOKENS:
                with self.subTest(key=key, value=value):
                    self.fresh()
                    p = self.run_receipt(record('5-of-5.json', **{key: value}))
                    self.assertEqual(p.returncode, 0, p.stderr)
                    text = self.written(os.path.join('receipts', 'local', '2026-11-01-aaaaaaaaaaaa.txt')).decode()
                    self.assertIn('# %s: %s\n' % (key, value), text)

    def test_a_private_id_in_a_token_writes_nothing(self):
        for key, line in (('harness', 5), ('model', 6)):
            for value in PRIVATE_IDS:
                with self.subTest(key=key, value=value):
                    self.refused(record('5-of-5.json', **{key: value}), 'line %d holds a private id' % line)

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
        with open(os.path.join(HERE, 'listings.json')) as f:
            self.assertEqual(json.load(f), dict(MAPPED))
        for host, listing in MAPPED:
            with self.subTest(host=host):
                p = self.run_receipt(record('5-of-5.json', host=host), listing=listing)
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
        p = self.run_receipt(record('5-of-5.json', harness='codex', model='other-model'))
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
