#!/usr/bin/env python3
"""WZ-P2 proofs for the standalone check. Every tree, path and skill is synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TOOL = HERE / 'standalone.py'
FIXTURES = ROOT / 'contracts/fixtures/wizskills'
spec = importlib.util.spec_from_file_location('standalone', TOOL)
standalone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(standalone)
SETTINGS = ['docs/agents/*.md', 'changes/README.md', 'GLOSSARY.md']
UP = '../../../'  # from skills/alpha/<folder>/ to above the package root


def refusal(rule, file, line):
    return {'rule': 'standalone.' + rule, 'file': file, 'line': line}


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='standalone-test-')
        self.addCleanup(self.temp.cleanup)
        self.tree = Path(self.temp.name) / 'tree'
        self.tree.mkdir()

    def write(self, name, text, mode=0o644):
        path = self.tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(mode)
        return path


class ContractExamples(Base):
    """The contract-first ticket's reference and refusal examples (#2628)."""

    def test_reference_table(self):
        package = json.loads((FIXTURES / 'package.json').read_text())
        for name, text in package['files'].items():
            self.write(name, text)
        rows = json.loads((FIXTURES / 'references.json').read_text())
        self.assertEqual(len(rows), 20)
        for row in rows:
            with self.subTest(name=row['name']):
                if row['kind'] == 'symlink':
                    link = self.tree / row['file']
                    link.symlink_to(row['target'])
                    self.assertEqual(standalone.check(self.tree, SETTINGS), [row['expected']])
                    link.unlink()
                    continue
                self.assertEqual(standalone.judge(self.tree, row, SETTINGS), row['expected'])
        self.assertEqual(standalone.check(self.tree, SETTINGS), [])

    def test_contract_rules_come_from_the_normative_block(self):
        rules = standalone.contract_rules((ROOT / 'contracts/wizskills.v1.md').read_text())
        self.assertEqual(rules['project_settings'], SETTINGS)
        self.assertIn('contracts/decisions.v1.md', rules['carried_contracts'])
        block = '```wizskills-v1\n{"schema": "openwiz.wizskills.v1", "carried_contracts": [], "project_settings": []}\n```\n'
        for bad in ('no block\n', block + block, block.replace('v1"', 'v2"', 1),
                    block.replace('"carried_contracts": []', '"carried_contracts": [], "carried_contracts": []'),
                    block.replace('[]', '"contracts/a.md"', 1),
                    block.replace('[]', '["../a.md"]', 1),
                    block.replace('[]', '["contracts/a.md", "contracts/a.md"]', 1)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    standalone.contract_rules(bad)


class Discovery(Base):
    """Each reference form a skill uses, discovered in its own file type."""

    def tree_with_every_form(self):
        self.write('contracts/decisions.v1.md', 'Synthetic carried contract.\n')
        self.write('skills/beta/SKILL.md', '# Beta\n')
        self.write('skills/alpha/scripts/run.sh', '#!/bin/sh\nexit 0\n', 0o755)
        self.write('skills/alpha/scripts/helper.py', 'VALUE = 1\n')
        self.write('skills/alpha/scripts/local.mjs', 'export const x = 1;\n')
        self.write('skills/alpha/fixtures/case.json', '{"path": "' + UP + 'elsewhere.md"}\n')
        self.write('skills/alpha/SKILL.md', '\n'.join([
            '# Alpha',                                                    # 1
            'Run [the script](scripts/run.sh), see [carried](../../contracts/decisions.v1.md#part).',
            'Also [beta](../beta/SKILL.md), [top](#alpha) and [docs](https://example.com/x).',
            'Read the project\'s own `docs/agents/fleet.md`; never `' + UP + 'x.md`.',
            '```sh',                                                      # 5
            '[fenced](' + '../../../fenced.md)',
            '```',
            'Outside: [o](' + '../../../elsewhere.md).',                  # 8
            'Setting linked: [f](../../docs/agents/fleet.md "title").',  # 9
            'Encoded: [e](%2E%2E/%2E%2E/%2E%2E/elsewhere.md).',           # 10
            'Absolute: [a](/synthetic/source/x.md).',                     # 11
            '',
            '[ref]: ../../tools/synthetic.md',                            # 13
            'Missing: ![img](images/missing.png)',                       # 14
            '']))
        self.write('skills/alpha/scripts/check.py', '\n'.join([
            'import json, subprocess, sys',                               # 1
            'from pathlib import Path',
            'from helper import VALUE',
            'import outsidehelper',                                       # 4
            'HERE = Path(__file__).resolve().parent',
            'ROOT = Path(__file__).resolve().parents[3]',                 # 6
            'DATA = "' + UP + 'private/x.json"',
            'json.loads((HERE / "../fixtures/case.json").read_text())',
            'for name in ("a", "b"): print(HERE / name)',
            'print(ROOT / "contracts/decisions.v1.md")',                  # 10
            'print((ROOT / "tools/synthetic.json").read_text())',         # 11
            'sys.path.insert(0, str(ROOT / "tools"))',                    # 12
            'subprocess.run([sys.executable, str(ROOT / "tools/run.py")])',  # 13
            'print(ROOT / sys.argv[1])',                                  # 14
            'print(Path(__file__).resolve().parents[5])',                 # 15
            'print(HERE.parent.parent / "beta/SKILL.md")',
            '']))
        self.write('skills/alpha/scripts/run-all.sh', '\n'.join([
            '#!/bin/sh',                                                  # 1
            'HERE=$(cd "$(dirname "$0")" && pwd) || exit 1',
            '# a comment: "$HERE/' + UP + 'ignored.sh"',
            'sh "$HERE/run.sh"',
            'raw docs/agents/fleet.md "$TMP/fleet.md"',                   # 5
            'python3 -I "$HERE/' + UP + 'tools/x.py"',                    # 6
            'cat "$(dirname "$0")/' + UP + 'data/in.json"',               # 7
            'for f in "$HERE"/*.sh; do :; done',
            'ROOTDIR=$(cd -P "$(dirname "$0")/../../.." && pwd)',
            'cat "$ROOTDIR/tools/synthetic.txt"',                         # 10
            '']))
        self.write('skills/alpha/scripts/gate.mjs', '\n'.join([
            "import { readFileSync } from 'node:fs';",                    # 1
            "import { dirname, join } from 'node:path';",
            "import { fileURLToPath } from 'node:url';",
            "import { x } from './local.mjs';",
            "import y from '" + UP + "lib/helper.mjs';",                  # 5
            'const here = dirname(fileURLToPath(import.meta.url));',
            "readFileSync('docs/agents/huntr.md', 'utf8');",
            "readFileSync(join(here, '" + UP + "docs/agents/huntr.md'), 'utf8');",  # 8
            "const run = new URL('" + UP + "tools/x.sh', import.meta.url);",       # 9
            "readFileSync(join(here, '../fixtures/case.json'));",
            "const settings = resolve(here, '" + UP + "docs/agents/huntr.md');",  # 11
            "assert.match(text, /settings/); log('no settings here', `settings ${x}`);",
            '']))
        self.write('skills/alpha/tests/bridge', '#!/usr/bin/env python3\nfrom pathlib import Path\n'
                   'print(Path(__file__).resolve().parents[4] / "apps")\n', 0o755)
        (self.tree / 'skills/alpha/linked.txt').symlink_to('scripts/run.sh')
        self.write('skills/alpha/scripts/broken.py', 'def broken(:\n')

    def test_every_outside_form_is_refused_and_every_inside_form_passes(self):
        self.tree_with_every_form()
        md, py, sh, js = ('skills/alpha/' + p for p in ('SKILL.md', 'scripts/check.py',
                                                         'scripts/run-all.sh', 'scripts/gate.mjs'))
        expected = sorted([
            refusal('link', md, 8), refusal('link', md, 9), refusal('link', md, 10),
            refusal('link', md, 11), refusal('link', md, 13), refusal('link', md, 14),
            refusal('import', 'skills/alpha/scripts/broken.py', 1),
            refusal('import', py, 4), refusal('read', py, 11), refusal('import', py, 12),
            refusal('script', py, 13), refusal('read', py, 14), refusal('read', py, 15),
            refusal('script', sh, 6), refusal('read', sh, 7), refusal('read', sh, 10),
            refusal('import', js, 5), refusal('read', js, 8), refusal('script', js, 9), refusal('read', js, 11),
            refusal('read', 'skills/alpha/tests/bridge', 3),
            refusal('symlink', 'skills/alpha/linked.txt', 1),
        ], key=lambda r: (r['file'], r['line'], r['rule']))
        self.assertEqual(standalone.check(self.tree, SETTINGS), expected)

    def test_a_clean_skill_passes(self):
        self.tree_with_every_form()
        for name in ('SKILL.md', 'scripts/check.py', 'scripts/run-all.sh', 'scripts/gate.mjs',
                     'tests/bridge', 'linked.txt', 'scripts/broken.py'):
            (self.tree / 'skills/alpha' / name).unlink()
        self.write('skills/alpha/SKILL.md', '# Alpha\nRun [it](scripts/run.sh).\n')
        self.assertEqual(standalone.check(self.tree, SETTINGS), [])

    def test_unreadable_code_is_refused_and_binary_data_is_not(self):
        self.write('skills/alpha/SKILL.md', '# Alpha\n')
        (self.tree / 'skills/alpha/run.py').write_bytes(b'\xff\xfeimport x\n')
        (self.tree / 'skills/alpha/image.png').write_bytes(b'\x89PNG\xff\x00')
        self.assertEqual(standalone.check(self.tree, SETTINGS), [refusal('read', 'skills/alpha/run.py', 1)])

    def test_escaping_symlinked_folder_does_not_hide_a_target(self):
        # Containment uses the real path: a link outside the package is refused,
        # and a Markdown target reached through it does not count as inside.
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / 'x.md').write_text('outside\n')
        self.write('skills/alpha/SKILL.md', '# Alpha\n[x](out/x.md)\n')
        (self.tree / 'skills/alpha/out').symlink_to(outside)
        self.assertEqual(standalone.check(self.tree, SETTINGS), [
            refusal('link', 'skills/alpha/SKILL.md', 2), refusal('symlink', 'skills/alpha/out', 1)])


class ReviewRound1(Base):
    """Review R1-R3, R9 and R10 at b4c14770a: dependencies the first scanner missed."""

    def setUp(self):
        super().setUp()
        self.write('skills/alpha/scripts/run.sh', '#!/bin/sh\nexit 0\n', 0o755)
        self.write('skills/alpha/scripts/check.py', 'VALUE = 1\n')

    def refused(self):
        return standalone.check(self.tree, SETTINGS)

    def test_r1_commands_in_instructions(self):
        md = 'skills/alpha/SKILL.md'
        self.write(md, '\n'.join([
            '# Alpha',                                                   # 1
            '```sh',
            'python3 tools/missing.py',                                  # 3
            'sh "<this skill\'s folder>/scripts/run.sh"',
            'python3 -I skills/alpha/scripts/check.py --flag',
            'python3 <external-checker>/tools/check.py',                 # 6
            'python3 -c "print(1)"; python3 -m json.tool',
            '```',
            'Run `python3 -I scripts/missing-local.py` from the project.',  # 9
            'Or `sh scripts/run.sh`, then `bash ../../tools/up.sh`.',     # 10
            '```json',
            '{"run": "python3 tools/data.py"}',
            '```',
            '```console',
            '$ node tools/missing.mjs',                                  # 15
            'python3 output/line.py',
            '```',
            '```sh',                                                     # 18
            'sh "<beta skill\'s folder>/scripts/b.sh" && sh <beta-skill-folder>/scripts/b.sh',
            'python3 <skill-directory>/scripts/check.py; node <installed-beta>/scripts/b.sh',
            'sh <beta>/scripts/missing.sh',                              # 21
            "jq '. as $x | . + 1' data.json | sh <unknown-skill-folder>/x.sh",  # 22
            '```',
            # Re-check R1: a directly executable local path is a command too.
            'The agent prepares it with `tools/github-app/setup.py` and `scripts/run.sh`.',  # 24
            '```sh',
            './tools/x.sh --flag && skills/alpha/scripts/run.sh',          # 26
            'FOO=1 tools/up.py arg',                                     # 27
            '```',
            '']))
        self.write('skills/beta/SKILL.md', '# Beta\n')
        self.write('skills/beta/scripts/b.sh', '#!/bin/sh\n')
        # Relative to the instruction's own file, as a nested README writes it.
        self.write('skills/alpha/test/case/README.md', 'Run `../../scripts/run.sh`.\n')
        self.assertEqual(self.refused(), [refusal('script', md, n) for n in (3, 6, 9, 10, 15, 21, 22, 24, 26, 27)])

    def test_r2_literal_operands_at_sinks(self):
        py, js, sh = 'skills/alpha/scripts/lit.py', 'skills/alpha/scripts/lit.mjs', 'skills/alpha/scripts/lit.sh'
        self.write(py, '\n'.join([
            'import subprocess, sys',                                    # 1
            'from pathlib import Path',
            'print(Path("/synthetic/source/missing.json").read_text())',  # 3
            'print(open("docs/agents/fleet.md").read())',
            'print(open("tools/x.json").read())',                        # 5
            'print(Path("/proc/self/cgroup").read_text())',
            'subprocess.run(["python3", "tools/missing.py"])',           # 7
            'subprocess.run([sys.executable, "-I", "skills/alpha/scripts/check.py"])',
            'subprocess.run(["sh", "run.sh"], cwd=Path(__file__).parent)',
            'subprocess.run(["sh", "gone.sh"], cwd=Path(__file__).parent)',  # 10
            'subprocess.run(["sh", "x.sh"], cwd=sys.argv[1])',
            '']))
        self.write(js, '\n'.join([
            "import { readFileSync } from 'node:fs';",                   # 1
            "readFileSync('../../../missing.json');",                    # 2
            "readFileSync('docs/agents/huntr.md', 'utf8');",
            "spawnSync('node', ['tools/missing.mjs']);",                 # 4
            '']))
        self.write(sh, '\n'.join([
            '#!/bin/sh',                                                 # 1
            'python3 tools/unknown-cwd.py',                              # 2
            'cd "$(dirname "$0")/../../.." || exit 1',
            'python3 tools/missing.py',                                  # 4
            'sh skills/alpha/scripts/run.sh',
            '. tools/lib.sh',                                            # 6
            'cd "$work" && sh whatever.sh',
            'python3 -c "import sys"',
            '']))
        self.assertEqual(self.refused(), [
            refusal('read', js, 2), refusal('script', js, 4),
            refusal('read', py, 3), refusal('read', py, 5), refusal('script', py, 7), refusal('script', py, 10),
            refusal('script', sh, 2), refusal('script', sh, 4), refusal('script', sh, 6)])

    def test_r2_single_quoted_operands_are_kept(self):
        # Re-check R2: a quoted helper path is still an operand; a quoted
        # multi-word string (usage text, a jq program) runs nothing.
        sh = 'skills/alpha/scripts/quoted.sh'
        self.write(sh, '\n'.join([
            '#!/bin/sh',                                                 # 1
            "python3 'tools/quoted-missing.py'",                         # 2
            "sh 'skills/alpha/scripts/run.sh'",
            "die 'usage: sh check-links.sh [--json] <spec>'",
            "jq -r '. as $x | sh tools/no.sh' f.json",
            'python3 "tools/double-missing.py"',                         # 6
            '']))
        self.assertEqual(self.refused(), [refusal('script', sh, 2), refusal('script', sh, 6)])

    def test_r3_dotted_imports_resolve_completely(self):
        self.write('skills/alpha/scripts/pkg/__init__.py', '')
        self.write('skills/alpha/scripts/pkg/present.py', 'X = 1\n')
        self.write('skills/alpha/scripts/imp.py', 'import pkg.present\nfrom pkg import present\n'
                   'import pkg.missing\nfrom pkg.missing import x\nimport os.path\n')
        f = 'skills/alpha/scripts/imp.py'
        self.assertEqual(self.refused(), [refusal('import', f, 3), refusal('import', f, 4)])

    def test_r9_shebang_regardless_of_suffix(self):
        outside = 'source "$(dirname "$0")/' + UP + 'outside.sh"\n'
        self.write('skills/alpha/run.tool', '#!/bin/bash\n' + outside, 0o755)
        self.write('skills/alpha/fixtures/data.txt', '#!/bin/sh\n' + outside)
        self.write('skills/alpha/run.awk', '#!/usr/bin/awk -f\n{ print }\n', 0o755)
        self.assertEqual(self.refused(), [refusal('read', 'skills/alpha/run.awk', 1),
                                          refusal('script', 'skills/alpha/run.tool', 2)])

    def test_r10_unreadable_directory_refuses(self):
        hidden = self.tree / 'skills/alpha/hidden'
        hidden.mkdir()
        (hidden / 'run.py').write_text('import synthetic_missing\n')
        hidden.chmod(0)
        self.addCleanup(hidden.chmod, 0o755)
        with self.assertRaises(OSError):
            standalone.check(self.tree, SETTINGS)
        p = subprocess.run([sys.executable, '-I', str(TOOL), '--tree', str(self.tree)],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual((p.returncode, p.stdout), (1, ''))


class Command(Base):
    def run_tool(self, *args):
        return subprocess.run([sys.executable, '-I', str(TOOL), *map(str, args)],
                              capture_output=True, text=True, timeout=30)

    def test_refusal_report_names_only_rule_file_and_line(self):
        secret = 'synthetic-secret-target'
        self.write('skills/alpha/SKILL.md', '# Alpha\n[x](' + UP + secret + '.md)\n')
        p = self.run_tool('--tree', self.tree)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        records = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual(records, [refusal('link', 'skills/alpha/SKILL.md', 2)])
        self.assertTrue(all(list(r) == ['rule', 'file', 'line'] for r in records))
        self.assertNotIn(secret, p.stdout + p.stderr)
        self.assertNotIn(str(self.tree), p.stdout + p.stderr)

    def test_report_redacts_private_forms_in_file_locations(self):
        # Re-check R4: a refused file's name may itself hold a private form;
        # the report keeps the rule and line but never prints that value.
        for name in ('skills/alpha/notes/the PC has ' + '16' + ' cores.md',
                     'skills/alpha/helper-checks/snapshot.' + 'aB3xQ9' + '/notes.md'):
            self.write(name, '# Note\n[x](' + UP + 'elsewhere.md)\n')
        p = self.run_tool('--tree', self.tree)
        self.assertEqual(p.returncode, 1, p.stderr)
        records = [json.loads(line) for line in p.stdout.splitlines()]
        self.assertEqual([(r['rule'], r['line']) for r in records], [('standalone.link', 2)] * 2)
        self.assertNotIn('16 cores', p.stdout + p.stderr)
        self.assertNotIn('aB3xQ9', p.stdout + p.stderr)

    def test_pass_and_unreadable_inputs(self):
        self.write('skills/alpha/SKILL.md', '# Alpha\n')
        p = self.run_tool('--tree', self.tree)
        self.assertEqual((p.returncode, p.stdout), (0, ''), p.stderr)
        for args in (('--tree', self.tree / 'missing'), ('--tree', self.tree, '--contract', self.tree / 'none.md')):
            with self.subTest(args=args):
                p = self.run_tool(*args)
                self.assertEqual(p.returncode, 1)
                self.assertNotIn(str(self.tree), p.stdout + p.stderr)


if __name__ == '__main__':
    unittest.main()
