#!/usr/bin/env python3
"""Synthetic regressions for the 0.0.5 export findings; no product suites or live calls."""
from pathlib import Path
from types import SimpleNamespace
import sys
import subprocess
import tempfile
import unittest
sys.dont_write_bytecode = True
from check import Refused
from scans import historical_text

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests/fixtures/release/export-review'

class ExportFindings(unittest.TestCase):
    def check_texts(self, texts, public_repo=None, public_base='1'*40):
        texts = dict(texts, **{'CHANGELOG.md': '# Changelog\n\n## 0.0.99 · PUBLICATION-DATE\n'})
        check = SimpleNamespace(texts=texts, plan={'live_pending': 0, 'scan_exceptions': [],
                                'public_base': public_base}, args=SimpleNamespace(version='0.0.99'),
                                used_exceptions=set(), report={})
        if public_repo is not None:
            check.args.public_repo = public_repo
        historical_text(check)

    def test_m1_release_state_fixture_fails(self):
        with self.assertRaisesRegex(Refused, '0.0.5-M1'):
            self.check_texts({'README.md': (FIXTURES/'m1/README.md').read_text()})

    def test_m2_private_hash_fixture_fails(self):
        with self.assertRaisesRegex(Refused, '0.0.5-M2'):
            self.check_texts({'README.md': (FIXTURES/'m2/README.md').read_text()})

    def test_l4_placeholder_fixture_fails(self):
        with self.assertRaisesRegex(Refused, '0.0.5-L4'):
            self.check_texts({'src/lib.rs': (FIXTURES/'l4/README.md').read_text()})

    def test_other_machine_checkable_review_findings(self):
        for finding, path in [('0.0.5-L1', 'README.md'), ('0.0.5-L2', 'RELEASING.md'), ('0.0.5-L3', 'docs/dependencies.md')]:
            with self.subTest(finding=finding), self.assertRaisesRegex(Refused, finding):
                self.check_texts({path: (FIXTURES/finding[-2:].lower()/'README.md').read_text()})

    def test_other_recorded_private_pointers_fail(self):
        for path, text in [
            ('src/lib.rs', "/// See ticket 0.0.3-1's evidence.\n"),
            ('src/lib.rs', "/// See the source-diagnostics fix's evidence README.\n"),
            ('src/timing.ts', "// ticket 1's real baseline has not run.\n"),
            ('scripts/fleet.sh', '# contracts/fleet.v1.md defines this.\n'),
        ]:
            with self.subTest(path=path, text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({path: text})

    def test_fixed_prose_and_technical_check_references_pass(self):
        self.check_texts({'README.md': '# Synthetic\n\nSource-inspection: Earlier private-beta candidates were checked.\n',
                         'src/lib.rs': '/// The request validation refuses malformed input.\n',
                         'skills/launch-fleet/scripts/test.sh': '### The contract hold (holds, and the same lines in the check)\n',
                         'skills/example.md': 'The check reports due work.\n'})

    def test_health_and_fleet_check_comments_pass(self):
        for text in [
            "/// What its fix's tries make due next. `None`: the check has no fix.",
            "/// The fix for this incident's `attempt`. `None`: the check has no fix.",
            "// The op id plays no part in the check; the start's own id is one.",
        ]:
            with self.subTest(text=text):
                self.check_texts({'src/sample.rs': text+'\n'})

    def test_check_placeholder_shapes_fail(self):
        for text in [
            '// A result (the check).', '// A result (the check remains).',
            '// A result: the check).', '// A result, the check, remains.',
            "// The sheet's the check remains.", '// The sheet’s the check remains.',
            '// The sheet the check remains.',
        ]:
            with self.subTest(text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.rs': text+'\n'})

    def test_broad_comment_regression_fixtures_fail(self):
        for name in ['comment-history', 'comment-evidence', 'comment-punctuation', 'comment-extension']:
            with self.subTest(name=name), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.rs': (FIXTURES/name/'README.md').read_text()})

    def test_malformed_prose_punctuation_fixture_fails(self):
        with self.assertRaisesRegex(Refused, '0.0.5-L4'):
            self.check_texts({'contracts/example.md': (FIXTURES/'prose-punctuation/README.md').read_text()})

    def test_review_history_variants_fail(self):
        for text in ['// review round two', '// correction-round 9', '// finding H7', '// finding id: X-42', '// reviewer R12', '// review S8']:
            with self.subTest(text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.ts': text+'\n'})

    def test_evidence_pointer_variants_fail(self):
        for text in ['// in the evidence', '// evidence notes', '// private/probes/result.md', "// ticket 8's procedure P0", "// See `private/probes/sample.txt`"]:
            with self.subTest(text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.mjs': text+'\n'})

    def test_punctuation_and_extension_variants_fail(self):
        for text in ['// Request .', '// Fields : names', '// First ; second', '// (not.jsx or.rs)', '// Image named.png']:
            with self.subTest(text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.rs': text+'\n'})

    def test_extensions_dotfiles_and_shell_commands_pass(self):
        for path, text in [
            ('scripts/check.mjs', '// Fail closed: a file the checks cannot read (not .ts or .tsx) is a problem.'),
            ('src/sample.ts', '// not .ts or .tsx'),
            ('test/tray.test.mjs', '// A PNG named .svg never renders as markup.'),
            ('src/sample.rs', '// Read .env and .gitignore before continuing ...'),
            ('script.sh', '#   sh .github/x.sh'),
        ]:
            with self.subTest(path=path, text=text):
                self.check_texts({path: text+'\n'})

    def test_stray_and_orphan_punctuation_fail(self):
        for text in ['// Request .', '// Request , next', '// , ', '// . ', '// : ', '// ; ']:
            with self.subTest(text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.rs': text+'\n'})

    def test_valid_comments_and_runtime_literals_pass(self):
        self.check_texts({'src/sample.rs': '// S1 validates one create; see contracts/request.md.\n// Reads helper.ts and the `.tsx` suffix.\n// A private state directory holds synthetic inputs.\nconst TEXT: &str = "review round two , not.ts";\n',
                         'src/sample.ts': '// Read namedFixture.svg with parse.ts.\nconst url = "https://example.invalid/review round 2 , not.ts";\n',
                         'skills/example.md': 'Each finding gets two correction rounds.\n'})

    def test_multiline_inline_and_block_comments_fail(self):
        for text in ['// See the\n// evidence report.', 'let value = 1; // review round 4', '/* A result ,\n * from the internal evidence notes. */']:
            with self.subTest(text=text), self.assertRaisesRegex(Refused, '0.0.5-L4'):
                self.check_texts({'src/sample.rs': text+'\n'})

    def test_literal_payloads_and_shell_heredocs_are_not_comments(self):
        self.check_texts({'src/sample.rs': 'const TEXT: &str = r#"// review round 2 , not.ts"#;\n',
                         'script.sh': 'cat <<EOF\n# review round 2 , not.ts\nEOF\n# A synthetic request validates once.\n',
                         'src/sample.ts': 'const text = `// review round 2 , not.ts`;\n'})

    def test_older_public_hash_passes_and_private_hash_fails(self):
        with tempfile.TemporaryDirectory(prefix='openwiz-public-history-') as directory:
            repo = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
                    '-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid',
                    '-C', str(repo), *args], stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-q')
            git('commit', '--allow-empty', '-qm', 'Synthetic earlier public commit')
            older = git('rev-parse', 'HEAD')
            git('commit', '--allow-empty', '-qm', 'Synthetic public base')
            base = git('rev-parse', 'HEAD')
            self.check_texts({'README.md': '# Synthetic\n\nSource-inspection: public '+older[:12]+'\n'}, repo, base)
            with self.assertRaisesRegex(Refused, '0.0.5-M2'):
                self.check_texts({'README.md': '# Synthetic\n\nSource-inspection: private b0bad00\n'}, repo, base)

    def test_public_base_hash_can_be_resolved(self):
        self.check_texts({'README.md': '# Synthetic\n\nSource-inspection: https://github.com/example/public/blob/'+ '1'*40 +'/README.md\n'})

if __name__ == '__main__':
    unittest.main()
