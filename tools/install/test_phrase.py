#!/usr/bin/env python3
import importlib.util
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PHRASE = 'Install OpenWiz'
QUOTE = '> ' + PHRASE
SURFACES = (
    'README.md',
    'AGENTS.md',
    'docs/install.md',
    'docs/first-hour.md',
    'docs/grok-bot.md',
)
FORBIDDEN = 'Install OpenWiz from'
SKILL_010 = ('https://github.com/openwizdev/WizSkills/blob/'
             '33eef93ba30cd8db256f6fe270e3ed28747a79bd/skills/install/SKILL.md')
SKILL_TAG = re.compile(
    r'https://github\.com/openwizdev/WizSkills/blob/(v[0-9][^/\s)]*)/skills/install/SKILL\.md')
OPEN_RANGE = re.compile(r'\bor later\b|\bonward\b|\band later\b|\bor newer\b')
TAG_PATTERN = r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
COMMIT_PATTERN = r'[0-9a-f]{40}'
REPO = 'https://github.com/openwizdev/OpenWiz'
SAFE_CLONE = 'git clone --depth 1 --branch "$tag" -- ' + REPO + ' "$openwiz"'


def clone_argv(tag, directory):
    if re.fullmatch(TAG_PATTERN, tag) is None:
        raise ValueError('tag')
    if (not isinstance(directory, str) or not directory or directory.startswith('-')
            or '\n' in directory or '\x00' in directory):
        raise ValueError('directory')
    return ['git', 'clone', '--depth', '1', '--branch', tag, '--', REPO, directory]


def lock_pin():
    data = json.loads((ROOT / 'wizskills.lock').read_text(encoding='utf-8'))
    version, commit = data['version'], data['commit']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('wizskills.lock version')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('wizskills.lock commit')
    return version, commit


def published_commit(version):
    if re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version) is None:
        raise ValueError('version')
    ref = 'refs/tags/v%s^{}' % version
    done = subprocess.run(
        ['git', 'ls-remote', 'https://github.com/openwizdev/WizSkills.git', ref],
        cwd='/', capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise AssertionError('wizskills tag v%s' % version)
    found = []
    for line in done.stdout.splitlines():
        oid, _, name = line.partition('\t')
        if name == ref and re.fullmatch(COMMIT_PATTERN, oid):
            found.append(oid)
    if len(found) != 1:
        raise AssertionError('wizskills tag v%s' % version)
    return found[0]


def pin_failures(section, guide, version):
    failures = []
    if 'wizskills.lock' not in section or '<commit>' not in section:
        failures.append('the agent section does not derive the skill from the release tag\'s wizskills.lock commit')
    if 'stop and say so' not in section:
        failures.append('a release with no wizskills.lock commit does not stop')
    if SAFE_CLONE not in section:
        failures.append('the agent section clones without -- before the repository')
    if TAG_PATTERN not in section or COMMIT_PATTERN not in section or 'whole value' not in section:
        failures.append('the agent section does not require the whole tag and the whole commit')
    if '--branch v0.1.1' in section:
        failures.append('the agent section clones v0.1.1')
    for tag in SKILL_TAG.findall(section):
        failures.append('the agent section hardcodes %s instead of the lock commit' % tag)
    if OPEN_RANGE.search(section) and ('v0.4.0' in section or SKILL_TAG.search(section)):
        failures.append('an open-ended range is pinned to one WizSkills tag')
    if 'wizskills.lock' not in guide:
        failures.append('the install guide does not name wizskills.lock')
    if SAFE_CLONE not in guide or TAG_PATTERN not in guide or 'whole value' not in guide:
        failures.append('the install guide clones without a whole-value tag check and --')
    if '--branch v0.1.1' in guide:
        failures.append('the install guide clones --branch v0.1.1')
    for tag in SKILL_TAG.findall(guide):
        failures.append('the install guide hardcodes %s; wizskills.lock is %s' % (tag, version))
    if 'WizSkills 0.4.0' in guide and version != '0.4.0':
        failures.append('the install guide names WizSkills 0.4.0 while wizskills.lock is %s' % version)
    return failures


class InstallPhrase(unittest.TestCase):
    def test_each_surface_quotes_the_phrase_alone(self):
        for name in SURFACES:
            text = (ROOT / name).read_text(encoding='utf-8')
            lines = [line.strip() for line in text.splitlines()]
            with self.subTest(name):
                self.assertIn(QUOTE, lines)
                self.assertNotIn(FORBIDDEN, text)

    def section(self):
        text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        parts = text.split('## Install OpenWiz', 1)
        self.assertEqual(len(parts), 2, 'AGENTS.md has an Install OpenWiz section')
        return parts[1].split('\n## ', 1)[0]

    def test_the_agent_section_is_enough_to_start(self):
        section = self.section()
        for needed in (
            QUOTE,
            'That phrase is enough to start.',
            'https://github.com/openwizdev/OpenWiz/releases/latest',
            'https://github.com/openwizdev/OpenWiz',
            'where your agents run',
            'yes before each change',
        ):
            self.assertIn(needed, section, needed)

    def test_tag_and_commit_cannot_inject_clone_options(self):
        loose = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+')
        self.assertIsNotNone(loose.search('v0.1.1 --upload-pack=evil'))
        argv = clone_argv('v0.1.1', '/tmp/openwiz-synthetic')
        self.assertEqual(argv, [
            'git', 'clone', '--depth', '1', '--branch', 'v0.1.1', '--',
            REPO, '/tmp/openwiz-synthetic'])
        for bad in ('-c', '--upload-pack=evil', 'v0.1.1 --upload-pack=evil',
                    'v0.1.1;rm', '', 'v01.2.3', 'v0.1.1-rc.1'):
            with self.subTest(tag=bad):
                with self.assertRaises(ValueError):
                    clone_argv(bad, '/tmp/openwiz-synthetic')
        with self.assertRaises(ValueError):
            clone_argv('v0.1.1', '--separate-git-dir=/tmp/openwiz-synthetic')
        for bad in ('-deadbeef', '--upload-pack=evil', 'cf2abfe', '',
                    'CF2ABFE13020661b47c47adb71afa993caaf16bf',
                    'cf2abfe13020661b47c47adb71afa993caaf16bf extra'):
            with self.subTest(commit=bad):
                self.assertIsNone(re.fullmatch(COMMIT_PATTERN, bad))
        section = self.section()
        guide = (ROOT / 'docs/install.md').read_text(encoding='utf-8')
        self.assertIn(TAG_PATTERN, section)
        self.assertIn(COMMIT_PATTERN, section)
        self.assertIn(TAG_PATTERN, guide)
        self.assertIn(SAFE_CLONE, section)
        self.assertIn(SAFE_CLONE, guide)

    def test_the_checkout_follows_the_lock(self):
        version, commit = lock_pin()
        section = self.section()
        guide = (ROOT / 'docs/install.md').read_text(encoding='utf-8')
        self.assertEqual(pin_failures(section, guide, version), [])
        self.assertIn(SKILL_010, section)
        self.assertIn('`0.1.0`', section)
        self.assertIn('docs/install.md#openwiz-010', section)
        self.assertIn('`v0.1.0`', section)
        self.assertNotEqual(commit, '33eef93ba30cd8db256f6fe270e3ed28747a79bd')
        self.assertNotIn('blob/%s/' % commit, section)
        self.assertNotIn('blob/%s/' % commit, guide)
        self.assertEqual(commit, published_commit(version))
        self.assertIn('including `v0.1.1`', section)
        self.assertIn('openwiz=$(mktemp -d)', section)
        self.assertIn("not the `commit` in that tag's `wizskills.lock`", section)
        self.assertIn('expect build identity `0.1.1`', section)
        self.assertIn('When `<version>` is not `0.1.1`, stop unless that guide expects `<version>`', section)
        self.assertIn('command reference for OpenWiz 0.1.1', guide)
        self.assertNotIn('command reference for that same tag', guide)
        self.assertNotIn('Linux on ARM is not supported', guide)
        self.assertIn('ARM64 (aarch64)', guide)
        self.assertIn('hard `GLIBC_2.39` requirement does not start', guide)
        self.assertIn('docs/install.md#openwiz-010', (ROOT / 'README.md').read_text(encoding='utf-8'))

    def test_a_lock_that_only_matches_itself_is_not_the_published_tag(self):
        version, commit = lock_pin()
        source = published_commit(version)
        forged = 'a' * 40
        forged_lock = (ROOT / 'wizskills.lock').read_text(encoding='utf-8').replace(commit, forged)
        self.assertIn(forged, forged_lock)
        self.assertNotEqual(forged, source)
        self.assertEqual(commit, source)

    def test_a_stale_pin_fails_even_when_the_urls_are_present(self):
        version, _ = lock_pin()
        self.assertNotEqual(version, '0.4.0')
        stale_section = (
            '- For `0.1.1` or later, the skill is '
            'https://github.com/openwizdev/WizSkills/blob/v0.4.0/skills/install/SKILL.md '
            'and the steps clone --branch v0.1.1.\n')
        stale_guide = (
            'follow https://github.com/openwizdev/WizSkills/blob/v0.4.0/skills/install/SKILL.md. '
            'git clone --depth 1 --branch v0.1.1 https://github.com/openwizdev/OpenWiz "$openwiz" '
            '(WizSkills 0.4.0)\n')
        failures = pin_failures(stale_section, stale_guide, version)
        self.assertTrue(any('v0.4.0' in item for item in failures), failures)
        self.assertTrue(any('v0.1.1' in item for item in failures), failures)
        self.assertTrue(any(version in item for item in failures), failures)

    def test_readme_is_covered_by_the_release_pin_check(self):
        path = ROOT / 'docs/evidence/2227/check_docs.py'
        spec = importlib.util.spec_from_file_location('check_docs_2227', path)
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        bare = '# Readme\n\n## OpenWiz 0.1.0\n\nSee docs/install.md#openwiz-010.\n'
        failures = check.release_path('README.md', bare)
        self.assertTrue(any('wizskills.lock' in item for item in failures), failures)
        self.assertTrue(any('clone' in item for item in failures), failures)
        self.assertTrue(any('pattern' in item for item in failures), failures)
        real = check.release_path('README.md', (ROOT / 'README.md').read_text(encoding='utf-8'))
        pin = [item for item in real if 'wizskills.lock' in item or 'clone' in item
               or 'v0.4.0' in item or 'pattern' in item]
        self.assertEqual(pin, [])

    def test_the_pages_point_at_the_agent_section(self):
        for name in ('README.md', 'docs/install.md', 'docs/first-hour.md', 'docs/grok-bot.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            with self.subTest(name):
                self.assertIn('AGENTS.md#install-openwiz', text)

    def test_install_help_names_the_phrase_and_keeps_the_commands(self):
        text = (ROOT / 'tools/install/install').read_text(encoding='utf-8')
        self.assertIn("OpenWiz's install entry (#1109): the commands the install skill runs.", text)
        self.assertIn('The install instruction is: Install OpenWiz.', text)


if __name__ == '__main__':
    unittest.main()
