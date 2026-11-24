#!/usr/bin/env python3
import fcntl
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
INSTALL = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('test_install', INSTALL / 'test_install.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
sys.path.insert(0, str(INSTALL / 'tests' / 'installer'))
from test_installer import Download, Path_, Preflight, Repair, entry
from test_root_safety import Remove, RootSafety
per_agent = importlib.util.spec_from_file_location('test_skills', INSTALL / 'tests/skills-per-agent/test_skills.py')
skills = importlib.util.module_from_spec(per_agent)
per_agent.loader.exec_module(skills)


class LinkedConfig(base.HarnessSkills):
    def linked_config(self, opencode):
        dotfiles = self.base / 'dotfiles'
        (dotfiles / ('opencode' if opencode else 'other')).mkdir(parents=True)
        os.symlink(dotfiles, self.home / '.config')
        (self.home / '.claude').mkdir()
        return dotfiles

    def test_an_absent_harness_under_a_linked_config_blocks_nothing(self):
        dotfiles = self.linked_config(opencode=False)
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'installed'), result)
        rows = {r['id']: r for r in result['harnesses']}
        self.assertEqual(rows['opencode']['state'], 'absent')
        self.assertEqual(rows['claude-code']['state'], 'installed')
        self.assertEqual(base.skill_files(self.home / '.claude/skills'),
                         base.skill_files(self.root / 'current/runtime/skills'))
        self.assertEqual(base.snapshot(dotfiles), {'other': 'dir'})

    @unittest.skipIf(os.getuid() == 0, 'root ignores search permission')
    def test_a_linked_config_without_search_permission_is_refused_on_its_own_row(self):
        dotfiles = self.linked_config(opencode=True)
        dotfiles.chmod(0o600)
        self.addCleanup(dotfiles.chmod, 0o700)
        code, result = self.skills()
        self.assertEqual((code, result.get('schema'), result.get('outcome')),
                         (0, 'openwiz.skills-install.v1', 'partial'), result)
        self.assertEqual(base.skill_files(self.home / '.claude/skills'),
                         base.skill_files(self.root / 'current/runtime/skills'))
        rows = {r['id']: r for r in result['harnesses']}
        self.assertEqual({h: r['state'] for h, r in rows.items()},
                         {'claude-code': 'installed', 'codex': 'absent', 'cursor': 'absent',
                          'opencode': 'refused', 'grok': 'absent'})
        self.assertIn(str(self.home / '.config'), rows['opencode']['next'])
        self.assertIn('chmod u+rx', rows['opencode']['next'])
        self.assertIn('run this again', rows['opencode']['next'])
        dotfiles.chmod(0o700)
        self.assertEqual(base.snapshot(dotfiles), {'opencode': 'dir'})

    def test_a_config_file_in_place_of_the_folder_means_opencode_is_absent(self):
        (self.home / '.config').write_bytes(b'Synthetic dotfile.\n')
        (self.home / '.claude').mkdir()
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'installed'), result)
        self.assertEqual({r['id']: r['state'] for r in result['harnesses']}['opencode'], 'absent')
        self.assertEqual((self.home / '.config').read_bytes(), b'Synthetic dotfile.\n')

    def test_a_present_harness_behind_a_linked_config_is_refused_on_its_own_row(self):
        dotfiles = self.linked_config(opencode=True)
        before = base.snapshot(dotfiles)
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'partial'), result)
        self.assertEqual(base.snapshot(dotfiles), before)
        self.assertEqual(base.skill_files(self.home / '.claude/skills'),
                         base.skill_files(self.root / 'current/runtime/skills'))
        rows = {r['id']: r for r in result['harnesses']}
        self.assertEqual({h: r['state'] for h, r in rows.items()},
                         {'claude-code': 'installed', 'codex': 'absent', 'cursor': 'absent',
                          'opencode': 'refused', 'grok': 'absent'})
        self.assertIn(str(self.home / '.config'), rows['opencode']['next'])
        self.assertIn('link', rows['opencode']['next'])
        self.assertIn('run this again', rows['opencode']['next'])

    @unittest.skipIf(os.getuid() == 0, 'root ignores write permission')
    def test_a_read_only_backup_still_counts_the_promoted_skill_and_the_rest_install(self):
        (self.home / '.claude').mkdir()
        self.assertEqual(self.skills()[0], 0)
        folder, old = self.home / '.claude/skills', self.home / '.claude/skills/.openwiz-old-grill'
        for name in ('launch-fleet', 'setup'):
            base.shutil.rmtree(folder / name)
        (folder / 'grill').chmod(0o500)
        self.addCleanup(lambda: old.exists() and old.chmod(0o700))
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'installed'), result)
        row = {r['id']: r for r in result['harnesses']}['claude-code']
        self.assertEqual(row['state'], 'installed', row)
        self.assertEqual(base.skill_files(folder, skip=('.openwiz-old-grill',)),
                         base.skill_files(self.root / 'current/runtime/skills'))
        self.assertIn(str(old), row['next'])
        self.assertIn('run this again', row['next'])
        code, result = self.skills()
        row = {r['id']: r for r in result['harnesses']}['claude-code']
        self.assertEqual((code, row['state']), (0, 'partial'), result)
        self.assertIn(str(old), row['next'])

    @unittest.skipIf(os.getuid() == 0, 'root ignores write permission')
    def test_a_read_only_canonical_backup_is_cleanup_advice_and_the_install_is_whole(self):
        (self.home / '.claude').mkdir()
        self.assertEqual(self.skills()[0], 0)
        canonical, old = self.root / 'skills', self.root / 'skills/.openwiz-old-grill'
        (canonical / 'grill').chmod(0o500)
        self.addCleanup(lambda: old.exists() and old.chmod(0o700))
        code, result = self.skills()
        self.assertEqual((code, result.get('outcome')), (0, 'installed'), result)
        self.assertEqual({r['id']: r['state'] for r in result['harnesses']}['claude-code'], 'installed')
        self.assertEqual(base.skill_files(canonical, skip=('.openwiz-old-grill',)),
                         base.skill_files(self.root / 'current/runtime/skills'))
        self.assertNotIn('canonical_refused', result)
        self.assertIn(str(old), result.get('canonical_cleanup', ''))
        self.assertIn('run this again', result['canonical_cleanup'])


class LockedRemove(Remove):
    def test_remove_on_a_root_without_its_lock_holds_one_against_a_new_install(self):
        self.installed()
        (self.root / 'install.lock').unlink()
        seen, real = [], entry.remove_unlocked

        def probe(*args):
            with open(self.root / 'install.lock', 'a+b') as other:
                try:
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    seen.append('free')
                except BlockingIOError:
                    seen.append('held')
            return real(*args)
        code, value = self.run_entry('remove', '--root', str(self.root))
        self.assertEqual((code, value['outcome']), (0, 'preview'), value)
        self.assertFalse(os.path.lexists(self.root / 'install.lock'))
        with mock.patch.object(entry, 'remove_unlocked', probe):
            code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome'], seen), (0, 'removed', ['held']), value)
        self.assertIn(str(self.root / 'install.lock'), value['delete'])
        self.assertFalse(self.root.exists())

    def test_an_install_that_wins_the_lock_remove_made_keeps_it_and_a_retry_is_refused(self):
        state, _ = self.installed()
        (self.root / 'install.lock').unlink()
        holder = []

        def install_first(fd, flags):
            holder.append(open(self.root / 'install.lock', 'a+b'))
            fcntl.flock(holder[0], fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fcntl.flock(fd, flags)
        race = mock.Mock(wraps=fcntl, flock=install_first, LOCK_EX=fcntl.LOCK_EX, LOCK_NB=fcntl.LOCK_NB)
        with mock.patch.object(entry, 'fcntl', race):
            code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.addCleanup(holder[0].close)
        self.assertEqual((code, value['outcome']), (5, 'refused'), value)
        self.assertTrue(os.path.lexists(self.root / 'install.lock'))
        self.assertTrue(os.path.samestat(os.stat(self.root / 'install.lock'), os.fstat(holder[0].fileno())))
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (5, 'refused'), value)
        self.assertTrue((state / 'service/config.json').exists())

    def test_remove_refuses_a_lock_that_is_not_a_private_file(self):
        self.installed()
        (self.root / 'install.lock').chmod(0o644)
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (5, 'refused'), value)
        self.assertIn(str(self.root / 'install.lock'), value['reason'])
        self.assertTrue((self.root / 'current').is_symlink())


    def test_a_preview_whose_lock_vanishes_before_it_opens_stays_read_only(self):
        self.installed()
        lock, real_open, seen = self.root / 'install.lock', os.open, []

        def vanish(path, *args, **kwargs):
            if Path(path) == lock and os.path.lexists(lock):
                os.unlink(lock)
            return real_open(path, *args, **kwargs)

        def probe(*args):
            seen.append(os.path.lexists(lock))
            return real(*args)
        real = entry.remove_unlocked
        with mock.patch.object(entry.os, 'open', vanish), mock.patch.object(entry, 'remove_unlocked', probe):
            code, value = self.run_entry('remove', '--root', str(self.root))
        self.assertEqual((code, value['outcome'], seen), (0, 'preview', [False]), value)
        self.assertFalse(os.path.lexists(lock))
        self.assertTrue((self.root / 'current').is_symlink())


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromNames(sorted(name for name in LinkedConfig.__dict__ if name.startswith('test_')),
                                      LinkedConfig)
    suite.addTests(loader.loadTestsFromTestCase(case)
                   for case in (Download, Path_, Preflight, Repair, RootSafety, LockedRemove,
                                skills.Report, skills.PerSkill, skills.Truthful, skills.Isolation))
    return suite


if __name__ == '__main__':
    unittest.main()
