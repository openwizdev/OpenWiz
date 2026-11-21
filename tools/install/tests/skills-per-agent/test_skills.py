#!/usr/bin/env python3
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
INSTALL = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('test_install', INSTALL / 'test_install.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

NAMES = ('grill', 'handoff', 'launch-fleet', 'research', 'setup', 'to-spec', 'to-tickets', 'triage')
CLASHES = ('handoff', 'research', 'to-spec', 'to-tickets', 'triage')


def skill(name, text):
    return b'---\nname: %s\n---\n%s\n' % (name.encode(), text.encode())


def bundled():
    files = {f'runtime/skills/{name}/SKILL.md': skill(name, 'Synthetic bundled copy.') for name in NAMES}
    files['runtime/skills/launch-fleet/scripts/fleet.sh'] = b'#!/bin/sh\necho synthetic bundled fleet\n'
    return files


class Skills(base.Bundles):
    def setUp(self):
        super().setUp()
        self.run_install(self.bundle(override=bundled()))
        self.home = self.base / 'home'
        self.home.mkdir()

    def skills(self, env=None):
        result = subprocess.run([sys.executable, '-I', str(INSTALL / 'install'), 'skills', '--root', str(self.root)],
                                capture_output=True, text=True,
                                env={'PATH': os.environ['PATH'], 'HOME': str(self.home), **(env or {})})
        return result.returncode, json.loads(result.stdout or '{}')

    def text(self, folder, name='grill'):
        return (folder / name / 'SKILL.md').read_bytes()

    def rows(self, result):
        return {row['id']: row for row in result.get('harnesses', [])}


class Report(Skills):
    def test_no_agent_folder_is_absent_and_never_reported_installed(self):
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (5, 'refused'), result)
        for row in result['harnesses']:
            with self.subTest(agent=row['id']):
                self.assertEqual(row['state'], 'absent')
                folder = str(self.home / ('.config/opencode' if row['id'] == 'opencode' else
                                          '.claude' if row['id'] == 'claude-code' else '.' + row['id']))
                self.assertIn(folder, row['next'])
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [])
        self.assertFalse((self.root / 'skills').exists())

    def test_codex_home_lands_the_skills_there_and_leaves_dot_codex_alone(self):
        elsewhere = self.base / 'codex-elsewhere'
        elsewhere.mkdir()
        code, result = self.skills(env={'CODEX_HOME': str(elsewhere)})
        self.assertEqual((code, result.get('outcome')), (0, 'installed'), result)
        row = self.rows(result)['codex']
        self.assertEqual((row['state'], row['path']), ('installed', str(elsewhere / 'skills')))
        self.assertEqual(sorted(p.name for p in (elsewhere / 'skills').iterdir()), sorted(NAMES))
        self.assertFalse((self.home / '.codex').exists())


class PerSkill(Skills):
    def test_the_users_own_same_named_skills_in_one_agent_block_nothing_else(self):
        (self.home / '.claude').mkdir()
        own = self.home / '.codex/skills'
        for name in CLASHES:
            (own / name).mkdir(parents=True)
            (own / name / 'SKILL.md').write_bytes(b'The owner ' + name.encode() + b'.\n')
        before = base.snapshot(own)
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
        rows = self.rows(result)
        self.assertEqual(rows['claude-code']['state'], 'installed')
        self.assertEqual(sorted(p.name for p in (self.home / '.claude/skills').iterdir()), sorted(NAMES))
        self.assertEqual(rows['codex']['state'], 'partial')
        self.assertEqual([s['skill'] for s in rows['codex']['skipped']], list(CLASHES))
        for skipped in rows['codex']['skipped']:
            with self.subTest(skill=skipped['skill']):
                self.assertIn(str(own / skipped['skill']), skipped['next'])
                self.assertIn('Codex', skipped['next'])
                self.assertIn('run this again', skipped['next'])
        for name in set(NAMES) - set(CLASHES):
            self.assertEqual(self.text(own, name), skill(name, 'Synthetic bundled copy.'))
        self.assertEqual({k: v for k, v in base.snapshot(own).items() if k.split('/')[0] in CLASHES}, before)
        self.assertEqual(sorted(p.name for p in (self.root / 'skills').iterdir()), sorted(NAMES))
        again = self.skills()
        self.assertEqual((again[0], again[1].get('outcome')), (0, 'partial'))
        self.assertEqual({k: v for k, v in base.snapshot(own).items() if k.split('/')[0] in CLASHES}, before)

    def test_a_linked_skill_folder_is_skipped_and_its_link_kept(self):
        (self.home / '.claude/skills').mkdir(parents=True)
        mine = self.base / 'my-grill'
        mine.mkdir()
        os.symlink(mine, self.home / '.claude/skills/grill')
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
        skipped = self.rows(result)['claude-code']['skipped']
        self.assertEqual([s['skill'] for s in skipped], ['grill'])
        self.assertIn(str(self.home / '.claude/skills/grill'), skipped[0]['next'])
        self.assertNotIn('nothing was changed', skipped[0]['next'])
        self.assertEqual(os.readlink(self.home / '.claude/skills/grill'), str(mine))
        self.assertEqual(list(mine.iterdir()), [])



class Truthful(Skills):
    def test_a_linked_canonical_folder_is_refused_on_its_own_and_every_agent_still_installs(self):
        (self.home / '.claude').mkdir()
        dotfiles = self.base / 'dotfiles-skills'
        dotfiles.mkdir()
        os.symlink(dotfiles, self.root / 'skills')
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
        self.assertEqual(self.rows(result)['claude-code']['state'], 'installed')
        self.assertEqual(sorted(p.name for p in (self.home / '.claude/skills').iterdir()), sorted(NAMES))
        self.assertIn(str(self.root / 'skills'), result.get('canonical_refused', ''))
        self.assertEqual(list(dotfiles.iterdir()), [])
        self.assertTrue((self.root / 'skills').is_symlink())

    @unittest.skipIf(os.getuid() == 0, 'root ignores write permission')
    def test_a_read_only_agent_folder_fails_on_its_own_row_and_the_next_agent_installs(self):
        (self.home / '.claude/skills').mkdir(parents=True)
        (self.home / '.claude/skills').chmod(0o500)
        self.addCleanup((self.home / '.claude/skills').chmod, 0o700)
        (self.home / '.codex').mkdir()
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
        rows = self.rows(result)
        self.assertEqual(rows['claude-code']['state'], 'refused')
        self.assertIn(str(self.home / '.claude/skills'), rows['claude-code']['next'])
        self.assertIn('run this again', rows['claude-code']['next'])
        self.assertEqual(list((self.home / '.claude/skills').iterdir()), [])
        self.assertEqual(rows['codex']['state'], 'installed')
        self.assertEqual(sorted(p.name for p in (self.home / '.codex/skills').iterdir()), sorted(NAMES))
        self.assertEqual(sorted(p.name for p in (self.root / 'skills').iterdir()), sorted(NAMES))

    @unittest.skipIf(os.getuid() == 0, 'root ignores write permission')
    def test_when_no_agent_can_be_written_the_canonical_folder_is_not_written_either(self):
        (self.home / '.claude/skills').mkdir(parents=True)
        (self.home / '.claude/skills').chmod(0o500)
        self.addCleanup((self.home / '.claude/skills').chmod, 0o700)
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (5, 'refused'), result)
        self.assertEqual(self.rows(result).get('claude-code', {}).get('state'), 'refused')
        self.assertFalse((self.root / 'skills').exists())



class Isolation(base.Bundles):
    def test_the_in_process_installer_suites_never_touch_an_agent_home_outside_their_synthetic_home(self):
        codex = self.base / 'developer-codex'
        (codex / 'skills/grill').mkdir(parents=True)
        (codex / 'skills/grill/.openwiz-skill').write_bytes(b'openwiz.skill-copy.v1\n' + b'2' * 40 + b'\n')
        (codex / 'skills/grill/SKILL.md').write_bytes(b'The developer sentinel.\n')
        home = self.base / 'developer-home'
        home.mkdir()
        before = base.snapshot(self.base)
        for suite in ('installer/test_root_safety.py', 'installer/test_installer.py'):
            with self.subTest(suite=suite):
                run = subprocess.run([sys.executable, '-I', str(INSTALL / 'tests' / suite)], capture_output=True,
                                     text=True, env={'PATH': os.environ['PATH'], 'HOME': str(home),
                                                     'CODEX_HOME': str(codex), 'TMPDIR': str(self.base / 'tmp')})
                self.assertEqual(run.returncode, 0, run.stderr[-2000:])
        self.assertEqual({k: v for k, v in base.snapshot(self.base).items() if not k.startswith('tmp')}, before)


if __name__ == '__main__':
    unittest.main()
