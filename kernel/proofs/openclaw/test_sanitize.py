"""Tests for sanitize.py: python3 -I kernel/proofs/openclaw/test_sanitize.py

Every value here is synthetic. Each case plants one private form in a raw
folder and checks what reaches the public folder, or that nothing does.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SANITIZE = HERE / 'sanitize.py'
TOKEN = 'gh' + 'p_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'
# Planted private forms, built in pieces so this file itself passes the privacy check.
THREAD = 'thr_' + 'planted42'
HOME = '/' + 'home/planted'
MAC_HOME = '/' + 'Users/planted'
EMAIL = 'synth.person' + '@' + 'corp-planted.dev'
CLOUD = 'proj' + '_planted9'
MACHINE = "The owner's PC has " + '32' + ' cores for the run.'


class Sanitize(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.raw = self.root / 'raw'
        self.raw.mkdir()
        self.out = self.root / 'out'
        self.literals = self.root / 'literals.txt'
        self.literals.write_text('synthbox-7\nsynth-owner-records\n', encoding='utf-8')

    def put(self, name, text):
        path = self.raw / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_it(self, *extra):
        args = [sys.executable, '-I', str(SANITIZE), str(self.raw), str(self.out)]
        args += list(extra) if extra else ['--literals', str(self.literals)]
        return subprocess.run(args, capture_output=True, text=True, timeout=120)

    def refused(self, result, code=1):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertFalse(self.out.exists(), 'a refused run wrote its output folder')

    def test_private_forms_are_rewritten_and_public_ones_kept(self):
        # catches: a sanitizer that copies private forms through, or rewrites public ones
        self.put('notes/run.md', '\n'.join([
            'builder thread ' + THREAD + ' started',
            'log at ' + HOME + '/.local/state/openwiz-local/run-1.log',
            'and ' + MAC_HOME + '/work/clone',
            'mail ' + EMAIL + ', commit 12345+someone@users.noreply.github.com',
            'project ' + CLOUD + ' on synthbox-7, records in synth-owner-records',
            'merged #4 at 0123456789abcdef0123456789abcdef01234567',
        ]) + '\n')
        result = self.run_it()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.out / 'notes/run.md').read_text(encoding='utf-8').splitlines(), [
            'builder thread <thread> started',
            'log at ~/.local/state/openwiz-local/run-1.log',
            'and ~/work/clone',
            'mail <email>, commit 12345+someone@users.noreply.github.com',
            'project <cloud-id> on <literal>, records in <literal>',
            'merged #4 at 0123456789abcdef0123456789abcdef01234567',
        ])
        self.assertEqual(sorted(p.name for p in self.out.rglob('*') if p.is_file()), ['run.md'])

    def test_a_credential_refuses_the_whole_run_and_is_never_printed(self):
        # catches: redacting a token (it must be rotated, not hidden) or echoing it in the error
        for i, line in enumerate([TOKEN, 'Authorization: Bearer ' + 'x' * 32,
                                  'sk-' + 'ant-' + 'a' * 30, '-----BEGIN OPENSSH PRIVATE KEY-----']):
            with self.subTest(i=i):
                self.put('ok.md', 'fine\n')
                self.put('logs/turn.log', 'start\n' + line + '\n')
                result = self.run_it()
                self.refused(result)
                self.assertIn('logs/turn.log:2', result.stderr)
                self.assertNotIn(line, result.stdout + result.stderr)

    def test_unknown_files_refuse(self):
        # catches: a binary, an unlisted kind or a symlink passing unread
        cases = {'shot.png': b'\x89PNG\r\n', 'data.bin': b'abc', 'bad.txt': b'\xff\xfe broken'}
        for name, data in cases.items():
            with self.subTest(name=name):
                for p in self.raw.iterdir():
                    p.unlink()
                (self.raw / name).write_bytes(data)
                self.refused(self.run_it())
        for p in self.raw.iterdir():
            p.unlink()
        self.put('real.md', 'fine\n')
        os.symlink(self.raw / 'real.md', self.raw / 'link.md')
        self.refused(self.run_it())

    def test_literals_are_required_and_must_be_readable(self):
        # catches: running without the private literals list, so named machines pass
        self.put('ok.md', 'fine\n')
        self.refused(self.run_it('--literals', str(self.root / 'missing.txt')), 2)
        self.literals.write_text('', encoding='utf-8')
        self.refused(self.run_it(), 2)
        self.refused(self.run_it('--other'), 2)

    def test_the_privacy_check_gates_what_rewriting_misses(self):
        # catches: a sanitizer that never runs the privacy check on its own output
        self.put('ok.md', MACHINE + '\n')
        result = self.run_it()
        self.refused(result)
        self.assertIn('privacy check', result.stderr)

    def test_an_existing_output_folder_is_never_overwritten(self):
        # catches: a second run silently mixing into or replacing earlier evidence
        self.put('ok.md', 'fine\n')
        self.out.mkdir()
        (self.out / 'keep.md').write_text('earlier\n', encoding='utf-8')
        result = self.run_it()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual([p.name for p in self.out.iterdir()], ['keep.md'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
