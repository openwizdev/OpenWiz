#!/usr/bin/env python3
import json
import re
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


def lock_pin():
    data = json.loads((ROOT / 'wizskills.lock').read_text(encoding='utf-8'))
    version, commit = data['version'], data['commit']
    if not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('wizskills.lock version')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('wizskills.lock commit')
    return version, commit


def pin_failures(section, guide, version):
    failures = []
    if 'wizskills.lock' not in section or '<commit>' not in section:
        failures.append('the agent section does not derive the skill from the release tag\'s wizskills.lock commit')
    if 'stop and say so' not in section:
        failures.append('a release with no wizskills.lock commit does not stop')
    if 'git clone --depth 1 --branch "$tag" -- https://github.com/openwizdev/OpenWiz' not in section:
        failures.append('the agent section clones without -- before the repository')
    if 'v[0-9]+\\.[0-9]+\\.[0-9]+' not in section or '[0-9a-f]{40}' not in section:
        failures.append('the agent section does not require a release tag and a 40-hex commit')
    if '--branch v0.1.1' in section:
        failures.append('the agent section clones v0.1.1')
    for tag in SKILL_TAG.findall(section):
        failures.append('the agent section hardcodes %s instead of the lock commit' % tag)
    if OPEN_RANGE.search(section) and ('v0.4.0' in section or SKILL_TAG.search(section)):
        failures.append('an open-ended range is pinned to one WizSkills tag')
    if 'wizskills.lock' not in guide:
        failures.append('the install guide does not name wizskills.lock')
    if 'git clone --depth 1 --branch "$tag" -- https://github.com/openwizdev/OpenWiz' not in guide:
        failures.append('the install guide clones without -- before the repository')
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
