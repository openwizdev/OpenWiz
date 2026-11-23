#!/usr/bin/env python3
import fcntl
import json
import os
import shlex
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_installer import Installer, TARGET

SETTINGS = ('setup/answers.json', 'cloudroom/session.json', 'service/config.json', 'service/app/key.pem',
            'service/state.json', 'service/loops/loop.json', 'service/clone/README')


def tree(folder):
    return sorted(p.relative_to(folder).as_posix() for p in Path(folder).rglob('*'))


class RootSafety(Installer):
    def install(self, root, *argv):
        if not (self.base / 'assets').exists():
            self.assets()
        return self.run_entry('install', '--assets', str(self.base / 'assets'), '--target', TARGET,
                              '--root', str(root), *argv)

    def own(self, folder, *files):
        for name in files:
            path = Path(folder) / name
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.write_text('synthetic ' + name)

    def test_a_root_with_an_unrelated_entry_is_refused_by_name_and_left_as_it_was(self):
        self.root.mkdir(mode=0o700, parents=True)
        self.own(self.root, 'notes.txt')
        code, value = self.install(self.root)
        self.assertEqual((code, value['outcome']), (5, 'refused'), value)
        self.assertIn(str(self.root / 'notes.txt'), value['reason'])
        self.assertEqual(tree(self.root), ['notes.txt'])

    def test_an_empty_root_and_a_previous_install_are_accepted(self):
        self.root.mkdir(mode=0o700, parents=True)
        code, value = self.install(self.root)
        self.assertEqual((code, value['outcome']), (0, 'installed'), value)
        self.own(self.root / 'state', *SETTINGS)
        (self.home / '.claude').mkdir()
        self.assertEqual(self.run_entry('skills', '--root', str(self.root))[0], 0)
        code, value = self.install(self.root)
        self.assertEqual((code, value['outcome']), (0, 'installed'), value)

    def test_a_state_root_with_another_apps_entries_is_refused_by_name(self):
        for n, entry in enumerate(('other.txt', 'service/other-service.txt', 'service/builds/other')):
            with self.subTest(entry=entry):
                root, state = self.home / ('root-%d' % n), self.base / ('state-%d' % n)
                state.mkdir(mode=0o700)
                self.own(state, entry)
                before = tree(state)
                code, value = self.install(root, '--state-root', str(state))
                self.assertEqual((code, value['outcome']), (5, 'refused'), value)
                self.assertIn(str(state / entry), value['reason'])
                self.assertEqual(tree(state), before)
                self.assertFalse(root.exists())

    def test_an_empty_state_root_and_a_previous_openwiz_state_are_accepted(self):
        state = self.base / 'state'
        state.mkdir(mode=0o700)
        code, value = self.install(self.root, '--state-root', str(state))
        self.assertEqual(code, 0, value)
        self.own(state, *SETTINGS)
        code, value = self.install(self.home / 'second-root', '--state-root', str(state))
        self.assertEqual((code, value['outcome']), (0, 'installed'), value)


class Remove(Installer):
    def setUp(self):
        super().setUp()
        (self.home / '.claude/skills').mkdir(parents=True)
        (self.home / '.claude/skills/mine').mkdir()

    def installed(self, *argv):
        code, value = self.run_entry('install', '--assets', str(self.assets()), '--target', TARGET,
                                     '--root', str(self.root), *argv)
        self.assertEqual(code, 0, value)
        self.assertEqual(self.run_entry('skills', '--root', str(self.root), *argv)[0], 0)
        RootSafety.own(self, Path(value['state_root']), *SETTINGS)
        return Path(value['state_root']), Path(value['build'])

    def test_remove_previews_then_deletes_only_openwiz_entries_and_keeps_unrelated_files(self):
        state, build = self.installed()
        RootSafety.own(self, self.root, 'notes.txt')
        RootSafety.own(self, state, 'other.txt', 'service/other-service.txt')
        before = tree(self.root)
        code, value = self.run_entry('remove', '--root', str(self.root))
        self.assertEqual((code, value['outcome']), (0, 'preview'), value)
        for path in (self.root / 'current', build, state / 'setup', state / 'service/app'):
            self.assertIn(str(path), value['delete'])
        self.assertNotIn(str(self.root / 'notes.txt'), value['delete'])
        self.assertEqual(tree(self.root), before)
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (0, 'removed'), value)
        self.assertEqual(tree(self.root), ['notes.txt', 'state', 'state/other.txt', 'state/service',
                                           'state/service/other-service.txt'])
        self.assertEqual(self.run_entry('status', '--root', str(self.root))[1]['outcome'], 'not installed')

    def test_remove_of_a_dedicated_install_leaves_no_root_and_lists_agent_skills_to_clean(self):
        self.installed()
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (0, 'removed'), value)
        self.assertFalse(self.root.exists())
        skills = self.home / '.claude/skills'
        self.assertEqual([row['path'] for row in value['skills']], [str(skills)])
        self.assertIn('setup', value['skills'][0]['names'])
        self.assertNotIn('mine', value['skills'][0]['names'])
        self.assertTrue((skills / 'setup/SKILL.md').exists() and (skills / 'mine').is_dir())

    def test_remove_never_deletes_a_shared_state_root_or_follows_a_link(self):
        state = self.base / 'shared state'
        state.mkdir(mode=0o700)
        _, build = self.installed('--state-root', str(state))
        RootSafety.own(self, state, 'other-app/data')
        outside = self.base / 'outside'
        RootSafety.own(self, outside, 'kept.txt')
        RootSafety.own(self, state / 'service', 'builds/' + 'f' * 40 + '/install-manifest.json')
        os.rename(state / 'cloudroom', self.base / 'cloudroom-moved')
        os.symlink(outside, state / 'cloudroom')
        linked = self.base / 'linked service'
        RootSafety.own(self, linked, 'config.json', 'app/data.db', 'keep.txt')
        os.rename(state / 'service', self.base / 'service-moved')
        os.symlink(linked, state / 'service')
        for argv in (('--yes',), ()):
            code, value = self.run_entry('remove', '--root', str(self.root), '--state-root', str(state), *argv)
            self.assertEqual((code, value['outcome']), (5, 'refused'), value)
            self.assertIn(str(state / 'service') + ' is a link', value['reason'])
        self.assertEqual(tree(linked), ['app', 'app/data.db', 'config.json', 'keep.txt'])
        self.assertTrue((self.root / 'current').is_symlink())
        os.unlink(state / 'service')
        os.rename(self.base / 'service-moved', state / 'service')
        for folder in (state / 'service/builds', self.root / 'skills'):
            os.rename(folder, self.base / 'moved')
            os.symlink(linked, folder)
            code, value = self.run_entry('remove', '--root', str(self.root), '--state-root', str(state), '--yes')
            self.assertEqual((code, value['outcome']), (5, 'refused'), value)
            self.assertIn(str(folder) + ' is a link', value['reason'])
            self.assertEqual(tree(linked), ['app', 'app/data.db', 'config.json', 'keep.txt'])
            os.unlink(folder)
            os.rename(self.base / 'moved', folder)
        before = tree(state)
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (5, 'refused'), value)
        self.assertIn('selects a build outside ' + str(self.root / 'state/service/builds'), value['reason'])
        self.assertEqual((tree(state), (self.root / 'current').is_symlink()), (before, True))
        code, value = self.run_entry('remove', '--root', str(self.root), '--state-root', str(state))
        self.assertEqual((code, value['outcome']), (0, 'preview'), value)
        command = shlex.split(value['next'].split('Run ', 1)[1].split(' to delete')[0])
        self.assertEqual(command, ['install', 'remove', '--root', str(self.root), '--state-root', str(state), '--yes'])
        code, value = self.run_entry(*command[1:])
        self.assertEqual((code, value['outcome']), (0, 'removed'), value)
        self.assertEqual(tree(outside), ['kept.txt'])
        self.assertFalse(build.exists())
        self.assertEqual(tree(state), ['other-app', 'other-app/data', 'service', 'service/builds',
                                       'service/builds/' + 'f' * 40,
                                       'service/builds/' + 'f' * 40 + '/install-manifest.json'])

    def test_remove_refuses_while_an_install_or_update_holds_the_lock(self):
        state, build = self.installed()
        before = tree(self.root)
        with open(self.root / 'install.lock', 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for argv in ((), ('--yes',)):
                code, value = self.run_entry('remove', '--root', str(self.root), *argv)
                self.assertEqual((code, value['outcome']), (5, 'refused'), value)
                self.assertIn('an install or update is running', value['reason'])
        self.assertEqual(tree(self.root), before)
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (0, 'removed'), value)

    def test_remove_on_a_root_with_nothing_installed_changes_nothing(self):
        self.root.mkdir(mode=0o700, parents=True)
        RootSafety.own(self, self.root, 'notes.txt')
        code, value = self.run_entry('remove', '--root', str(self.root), '--yes')
        self.assertEqual((code, value['outcome']), (1, 'not installed'), value)
        self.assertEqual(tree(self.root), ['notes.txt'])


if __name__ == '__main__':
    unittest.main()
