#!/usr/bin/env python3
"""P3/P8 private-record transformation plus the actual O3 text-check seam."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CHECKER = HERE.parent / 'privacy-check' / 'check.py'
# Split planted tokens so the fixture source itself is safe for the public tree.
POINTER = 'https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001'
WAS = 'was [ClosedWiz #9001](https://github.com/jparker2006/ClosedWiz/issues/9001)'


class TextContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.title = self.root / 'title'
        self.body = self.root / 'body'
        self.literals = self.root / 'literals'
        self.title.write_text('Synthetic move')
        self.literals.write_text('synthetic-private-literal\n')
        self.out = self.root / 'out'

    def draft(self, body, ok=True, checker=None, flags=()):
        self.body.write_text(body)
        result = subprocess.run([
            sys.executable, '-I', str(HERE / 'text.py'), '--title-file', str(self.title),
            '--body-file', str(self.body), '--closedwiz', '9001', '--openwiz', '4001',
            '--kind', 'issue', '--date', '2030-01-02', '--pointer', POINTER,
            '--checker', str(checker or CHECKER), '--literals', str(self.literals),
            '--out', str(self.out), *flags], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, ok, result.stderr or result.stdout)
        return result

    def test_body_aliases_are_scoped_list_bound_and_follow_original_quote_extraction(self):
        # A dry-run alias must not rewrite the exact private quote or disguise
        # unknown composite names, emails, or metadata. The ordinary O3 controls
        # do not exercise an approved substitution before scanning.
        account, name = 'synthetic' + 'account', 'synthetic' + 'person'
        self.literals.write_text(account + '\n' + name + '\n')
        policy = dict(schema='openwiz.body-aliases.v1', mode='dry_run_only',
            authority='https://github.com/jparker2006/ClosedWiz/issues/1283#issuecomment-6711486946',
            literals_sha256=hashlib.sha256(self.literals.read_bytes()).hexdigest(), issues=[9001],
            roles={hashlib.sha256(v.encode()).hexdigest(): role
                   for v, role in [(account, 'home_account'), (name, 'private_name')]})
        path = self.root / 'aliases.json'
        path.write_text(json.dumps(policy))
        flags = ['--body-aliases', str(path)]
        body = ('Ja' 'ke: "' + account + ' exact original"\nUse /home/' + account + '/work, ' +
                account + ' and ' + name + '. Mention `@' + name + '`.\nRun `ssh deploy@' + name + '`.')
        self.draft(body, flags=flags)
        self.assertEqual(self.body.read_text(), body)
        self.assertEqual((self.out / 'body.txt').read_text(), 'Ja' 'ke: [private record](' + POINTER + ')\n'
            'Use ${HOME}/work, <build-account> and <private-name>. Mention `@<private-name>`.\n'
            'Run `ssh deploy@<private-name>`.\n\n' + WAS)
        self.assertIn('1. "' + account + ' exact original"\n', (self.out / 'private-record.txt').read_text())
        for child in self.out.iterdir():
            child.unlink()
        self.out.rmdir()
        for text in [account + '-unknown', name + '.unknown', '/home/' + account + '-unknown/work',
                     account + '@' + 'example.invalid', account + '@host', 'ssh deploy@' + name + '-unknown',
                     'ssh ' + account + '@' + 'example.invalid', 'prj_' + 'unbound42']:
            with self.subTest(unknown=text):
                self.draft(text, ok=False, flags=flags)
                self.assertFalse(self.out.exists())
        for fault in ['title', 'list', 'scope', 'role', 'authority']:
            with self.subTest(fault=fault):
                changed = json.loads(json.dumps(policy))
                self.title.write_text(account if fault == 'title' else 'Synthetic move')
                if fault == 'list':
                    changed['literals_sha256'] = '0' * 64
                elif fault == 'scope':
                    changed['issues'] = [9002]
                elif fault == 'role':
                    changed['roles'][hashlib.sha256(account.encode()).hexdigest()] = 'unknown'
                elif fault == 'authority':
                    changed['authority'] += '-unknown'
                path.write_text(json.dumps(changed))
                self.draft(account, ok=False, flags=flags)
                self.assertFalse(self.out.exists())

    def test_p3_p8_all_record_forms_threads_quotes_and_was_line(self):
        body = ('Follow-up of #9000\n\n'
                '**Approved by Ja' 'ke, 2030-01-01:** "synthetic first thr_synquoted1"\n'
                'Ja' 'ke, 2030-01-01: “synthetic second” and "synthetic third".\n'
                'Ja' 'ke:\n> synthetic fourth\n> synthetic fifth\n\n'
                'Builder thr_synbuilder1 and thr_webbuilder2.\n')
        self.draft(body)
        public = (self.out / 'body.txt').read_text()
        pointer = '[private record](' + POINTER + ')'
        self.assertEqual(public,
                         'Follow-up of #9000\n\n'
                         '**Approved by Ja' 'ke, 2030-01-01:** ' + pointer + '\n'
                         'Ja' 'ke, 2030-01-01: ' + pointer + ' and ' + pointer + '.\n'
                         'Ja' 'ke:\n' + pointer + '\n\nBuilder  and .\n\n' + WAS)
        self.assertEqual((self.out / 'private-record.txt').read_text(),
                         '**Private record for OpenWiz #4001, 2030-01-02:**\n\n'
                         '1. "synthetic first thr_synquoted1"\n'
                         '2. “synthetic second”\n3. "synthetic third"\n'
                         '4. > synthetic fourth\n> synthetic fifth\n')

    def test_p3_titles_bodies_literals_and_unavailable_checker_refuse(self):
        cases = [('Investigate prj_' + 'planted42', 'Clean body', None),
                 ('Synthetic move', 'Contact syntheticperson' + '@' + 'mail.invalid', None),
                 ('Synthetic move', 'synthetic-private-literal', None),
                 ('Synthetic move', 'Clean body', self.root / 'absent-checker')]
        for title, body, checker in cases:
            with self.subTest(title=title, body=body):
                self.title.write_text(title)
                self.draft(body, ok=False, checker=checker)
                self.assertFalse(self.out.exists())
        self.title.write_text('Synthetic move')
        self.literals.unlink()
        self.draft('Clean body', ok=False)
        self.assertFalse(self.out.exists())

    def test_p3_unclosed_ambiguous_or_already_moved_bodies_refuse(self):
        for body in ['Ja' 'ke: "unclosed synthetic quote',
                     'Ja' 'ke: "synthetic quote" then "unclosed',
                     'Clean\n\n' + WAS]:
            with self.subTest(body=body):
                self.draft(body, ok=False)
                self.assertFalse(self.out.exists())

    def test_p3_escaped_outer_record_is_replaced(self):
        self.draft('Ja' 'ke: \\"synthetic escaped\\"')
        self.assertEqual((self.out / 'body.txt').read_text(),
                         'Ja' 'ke: [private record](' + POINTER + ')\n\n' + WAS)
        self.assertIn('1. \\"synthetic escaped\\"\n',
                      (self.out / 'private-record.txt').read_text())

    def test_a8_exact_blockquote_internal_crlf_bytes_are_preserved(self):
        self.draft('Ja' 'ke:\r\n> synthetic first\r\n> synthetic second\r\n\r\nRest.')
        self.assertEqual((self.out / 'private-record.txt').read_bytes(),
                         b'**Private record for OpenWiz #4001, 2030-01-02:**\n\n'
                         b'1. > synthetic first\r\n> synthetic second\n')

    def test_p11_clean_body_needs_no_private_record(self):
        self.draft('Synthetic ordinary body.')
        self.assertEqual((self.out / 'body.txt').read_text(), 'Synthetic ordinary body.\n\n' + WAS)
        self.assertFalse((self.out / 'private-record.txt').exists())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--checker', type=Path, default=CHECKER)
    options, remaining = parser.parse_known_args()
    CHECKER = options.checker
    unittest.main(argv=[sys.argv[0], *remaining])
