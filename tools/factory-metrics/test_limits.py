#!/usr/bin/env python3
"""TL1 reader boundary proofs. All settings and paths are synthetic.

C1: omitted/swapped defaults or cwd-dependent loading break the literal report.
C2: permissive parsing silently accepts missing/duplicate/unknown/invalid goals.
C3: ignored edits, whitespace or cwd dependence corrupt consumer settings.
Existing journey/metrics tests have no stage-limit settings seam.
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'limits.py'
DEFAULTS = {'schema': 'closedwiz.factory-limits.v1', 'minutes': {
    'builder_start': 10, 'reviewer_start': 5, 'merge': 5,
    'fix_after_changes': 30, 'builder_question_answer': 15}}
CONFIG = ('builder_start=10\nreviewer_start=5\nmerge=5\n'
          'fix_after_changes=30\nbuilder_question_answer=15\n')


def reader():
    spec = importlib.util.spec_from_file_location('factory_limits', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Limits(unittest.TestCase):
    def cli(self, *args):
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *map(str, args)],
                              cwd=self.root, capture_output=True, text=True)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='synthetic-limits-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_default_report_from_another_directory(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(json.loads(result.stdout), DEFAULTS)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_invalid_settings_have_no_report_or_fallback(self):
        bad = ['', '# only a comment\n']
        for line in CONFIG.splitlines(keepends=True):
            bad.extend([CONFIG.replace(line, ''), CONFIG + line])
        for value in ('0', '-1', '+1', '1.5', '1e2', 'NaN', 'inf', 'true',
                      'none', '', '1_0', '01', '１２', '١٢', '10 # minutes'):
            bad.append(CONFIG.replace('builder_start=10', 'builder_start=' + value))
        bad.extend(CONFIG + line for line in (
            'ci=5\n', 'Builder_start=10\n', 'builder_start_minutes=10\n',
            'broken\n', '=10\n', 'merge=5=6\n', '[limits]\n',
            'unknown_private_value=secret-synthetic\n'))
        bad.extend([CONFIG.replace('merge=5', 'merge\u00a0=5'),
                    '\ufeff' + CONFIG, CONFIG + '# non-ASCII: é\n',
                    CONFIG.replace('merge=5', 'merge=5\x00')])
        module = reader()
        path = self.root / 'synthetic.conf'
        for content in bad:
            with self.subTest(content=content):
                path.write_text(content, encoding='utf-8')
                before = path.read_bytes()
                with self.assertRaises(ValueError):
                    module.read(path)
                result = self.cli('--settings', path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, 'limits: invalid settings\n')
                self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(self.root.iterdir()), [path])

    def test_unreadable_settings_have_no_report_or_fallback(self):
        invalid = self.root / 'non-utf8.conf'
        invalid.write_bytes(b'\xff')
        module = reader()
        for path in (self.root / 'absent.conf', self.root, invalid):
            with self.subTest(path=path.name):
                with self.assertRaises((OSError, ValueError)):
                    module.read(path)
                result = self.cli('--settings', path)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, 'limits: invalid settings\n')

    def test_edited_settings_report_exact_values_through_both_interfaces(self):
        # Reordered, CRLF, comments and horizontal whitespace are benign syntax.
        path = self.root / 'edited.conf'
        path.write_bytes(b'# synthetic edit\r\n\tmerge = 5\r\n\r\n'
                         b'builder_question_answer=15\r\nreviewer_start=5\r\n'
                         b'fix_after_changes=30\r\n builder_start\t=\t12 \r\n')
        expected = {'schema': 'closedwiz.factory-limits.v1', 'minutes': {
            'builder_start': 12, 'reviewer_start': 5, 'merge': 5,
            'fix_after_changes': 30, 'builder_question_answer': 15}}
        before = path.read_bytes()
        module = reader()
        self.assertEqual(module.read(path), expected)
        result = self.cli('--settings', path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual(result.stderr, '')
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(module.read(HERE / 'limits.conf'), DEFAULTS)
        self.assertEqual(module.read(str(path)), expected)
        self.assertEqual(list(self.root.iterdir()), [path])


if __name__ == '__main__':
    unittest.main()
