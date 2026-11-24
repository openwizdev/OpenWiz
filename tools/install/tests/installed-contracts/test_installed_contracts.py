#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
INSTALL = ROOT / 'tools/install'
sys.path.insert(0, str(ROOT / 'tools/release'))
from test_product_identity import build, collector

TARGET = 'x86_64-unknown-linux-gnu'
VERSION = '0.0.99'
HARNESS_HOMES = ('.claude', '.codex', '.cursor', '.config/opencode', '.grok')
OLD_SPEC_WITHOUT_CHECKPOINTS = json.dumps({'body': '# Spec\n\nNo checkpoints.\n', 'createdAt': '2026-01-01T00:00:00Z'})
CONTRACTS_READ_FROM_ABOVE_SKILLS = (('to-tickets/scripts/check-approval.sh', 'contracts/checkpoints.v1.md'),
                                    ('launch-fleet/scripts/merge.py', 'contracts/checkpoints.v1.md'),
                                    ('launch-fleet/scripts/effects.py', 'contracts/ops-dispatch.v1.schema.json'),
                                    ('write-driver/scripts/write_driver.py', 'contracts/write-driver.v1.md'))


def run(args, **kw):
    return subprocess.run(args, capture_output=True, text=True, **kw)


class InstalledContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (ROOT / '.wizskills/skills').is_dir():
            raise AssertionError('Install WizSkills first: python3 -I tools/wizskills/install.py')
        cls.tmp = tempfile.TemporaryDirectory(prefix='openwiz-installed-contracts-')
        work = Path(cls.tmp.name)
        source = run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], check=True).stdout.strip()
        binaries, job = work / 'bin', work / 'job'
        binaries.mkdir()
        job.mkdir()
        receipts = build(binaries, source, TARGET, job, VERSION)
        products = work / 'products'
        result = run(collector(ROOT, binaries, products, source, TARGET, receipts, VERSION))
        assert result.returncode == 0, 'build_products refused: ' + result.stderr
        package = work / 'package'
        result = run([sys.executable, '-I', str(ROOT / 'tools/release/package.py'), '--products', str(products),
                      '--identity', str(products) + '.json', '--output', str(package)])
        assert result.returncode == 0, 'package refused: ' + result.stderr
        manifest = package / f'openwiz-{VERSION}-{TARGET}.manifest.json'
        digest = (package / f'openwiz-{TARGET}.sha256').read_text().split()[0]
        cls.root, cls.home = work / 'installed', work / 'home'
        result = run([sys.executable, '-I', str(INSTALL / 'install.py'), '--manifest', str(manifest),
                      '--archive', str(package / f'openwiz-{VERSION}-{TARGET}.tar.gz'),
                      '--manifest-sha256', digest, '--root', str(cls.root), '--target', TARGET])
        assert result.returncode == 0, 'install refused: ' + result.stdout + result.stderr
        for folder in HARNESS_HOMES:
            (cls.home / folder).mkdir(parents=True)
        result = run([sys.executable, '-I', str(INSTALL / 'install'), 'skills', '--root', str(cls.root)],
                     env={'PATH': os.environ['PATH'], 'HOME': str(cls.home)})
        cls.skills = json.loads(result.stdout or '{}')
        assert result.returncode == 0, 'install skills refused: ' + result.stdout + result.stderr
        cls.path_without_gh = work / 'nogh'
        cls.path_without_gh.mkdir()
        for tool in ('sh', 'python3', 'git', 'jq'):
            found = next((Path(d) / tool for d in os.environ['PATH'].split(':') if (Path(d) / tool).is_file()), None)
            if found:
                (cls.path_without_gh / tool).symlink_to(found)
        cls.bases = [cls.root, cls.root / 'current/runtime'] + [cls.home / f for f in HARNESS_HOMES]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_skills_install_reports_every_agent_installed(self):
        self.assertEqual(self.skills.get('outcome'), 'installed', self.skills)

    def test_the_installed_plan_checker_reads_its_contract_from_every_install(self):
        for base in self.bases:
            with self.subTest(installed=str(base)):
                checker = base / 'skills/to-tickets/scripts/check-approval.sh'
                self.assertTrue(checker.is_file(), checker)
                result = run(['sh', str(checker), '--checkpoints', '7'], input=OLD_SPEC_WITHOUT_CHECKPOINTS,
                             env={'PATH': os.environ['PATH'], 'HOME': str(self.home)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('#7 checkpoint answers are valid', result.stdout)

    def test_every_contract_an_installed_script_reads_is_installed_beside_it(self):
        for base in self.bases:
            for script, contract in CONTRACTS_READ_FROM_ABOVE_SKILLS:
                with self.subTest(installed=str(base), script=script):
                    self.assertTrue((base / 'skills' / script).is_file(), base / 'skills' / script)
                    self.assertTrue((base / contract).is_file(), base / contract)

    def test_the_installed_status_note_accepts_the_skills_it_was_given(self):
        version = next(line[len('version: '):] for line in
                       (self.root / 'skills/launch-fleet/SKILL.md').read_text().splitlines()
                       if line.startswith('version: '))
        for base in self.bases[:1] + self.bases[2:]:
            with self.subTest(installed=str(base)):
                result = run([sys.executable, '-I', str(base / 'skills/launch-fleet/scripts/status.py'), 'write',
                              '--repo', 'synthetic/repo', '--ticket', '7', '--agent', 'builder',
                              '--harness', 'claude-code', '--model', 'synthetic', '--state', 'working',
                              '--skills', 'launch-fleet@' + version, '--step', 'Testing the install.'],
                             env={'PATH': str(self.path_without_gh), 'HOME': str(self.home)})
                self.assertNotIn('refused', result.stderr)
                self.assertIn('repos/synthetic/repo/contents/docs/agents/fleet.md', result.stderr)

    def test_every_installed_python_script_imports_cleanly(self):
        probe = (
            'import importlib.util, pathlib, sys\n'
            'base = pathlib.Path(sys.argv[1])\n'
            'scripts = sorted(p for p in base.glob("skills/*/scripts/**/*.py") '
            'if "fixtures" not in p.parts and "evidence" not in p.parts '
            'and not p.name.startswith(("test_", "test-")))\n'
            'assert any(p.as_posix().endswith("skills/launch-fleet/scripts/post.py") for p in scripts)\n'
            'failures = []\n'
            'for i, p in enumerate(scripts):\n'
            '    parent = str(p.parent)\n'
            '    added = parent not in sys.path\n'
            '    if added:\n'
            '        sys.path.insert(0, parent)\n'
            '    try:\n'
            '        spec = importlib.util.spec_from_file_location(f"installed_script_{i}", p)\n'
            '        mod = importlib.util.module_from_spec(spec)\n'
            '        spec.loader.exec_module(mod)\n'
            '    except BaseException as exc:\n'
            '        failures.append(f"{p.relative_to(base)}: {type(exc).__name__}: {exc}")\n'
            '    finally:\n'
            '        if added and parent in sys.path:\n'
            '            sys.path.remove(parent)\n'
            'if failures:\n'
            '    sys.stderr.write("\\n".join(failures) + "\\n")\n'
            '    sys.exit(1)\n'
        )
        for base in self.bases:
            with self.subTest(installed=str(base)):
                result = run([sys.executable, '-I', '-c', probe, str(base)],
                             env={'PATH': str(self.path_without_gh), 'HOME': str(self.home)})
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_remove_previews_the_contracts_copies(self):
        result = run([sys.executable, '-I', str(INSTALL / 'install'), 'remove', '--root', str(self.root)],
                     env={'PATH': os.environ['PATH'], 'HOME': str(self.home)})
        value = json.loads(result.stdout)
        self.assertIn(str(self.root / 'contracts'), value['delete'])
        self.assertIn(str(self.root / '.claude-plugin'), value['delete'])
        listed = {row['path']: row.get('beside') for row in value['skills']}
        for folder in HARNESS_HOMES:
            base = self.home / folder
            self.assertEqual(listed.get(str(base / 'skills')), [str(base / 'contracts'), str(base / '.claude-plugin')])


if __name__ == '__main__':
    unittest.main()
