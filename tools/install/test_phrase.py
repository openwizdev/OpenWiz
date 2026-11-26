#!/usr/bin/env python3
"""The public install instruction is the phrase `Install OpenWiz`.

A person says that phrase to a coding agent. The files below are what that
agent reads, and each quotes the phrase on its own line. `tools/install/install
--help` names the same phrase and keeps the commands as the reference the
agent runs. The pinned WizSkills install skill still quotes the older line
until its pin moves; `tests/journey/test_journey.py` checks that copy.
"""
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
SKILL_011 = 'https://github.com/openwizdev/WizSkills/blob/v0.4.0/skills/install/SKILL.md'


class InstallPhrase(unittest.TestCase):
    def test_each_surface_quotes_the_phrase_alone(self):
        for name in SURFACES:
            text = (ROOT / name).read_text(encoding='utf-8')
            lines = [line.strip() for line in text.splitlines()]
            with self.subTest(name):
                self.assertIn(QUOTE, lines)
                self.assertNotIn(FORBIDDEN, text)

    def test_the_agent_section_is_enough_to_start(self):
        text = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
        parts = text.split('## Install OpenWiz', 1)
        self.assertEqual(len(parts), 2, 'AGENTS.md has an Install OpenWiz section')
        section = parts[1].split('\n## ', 1)[0]
        for needed in (
            QUOTE,
            'That phrase is enough to start.',
            'https://github.com/openwizdev/OpenWiz/releases/latest',
            'https://github.com/openwizdev/OpenWiz',
            SKILL_010,
            SKILL_011,
            'docs/install.md#openwiz-010',
            'docs/install.md',
            'where your agents run',
            'yes before each change',
        ):
            self.assertIn(needed, section, needed)

    def test_readme_and_guide_point_at_the_agent_section(self):
        for name in ('README.md', 'docs/install.md'):
            text = (ROOT / name).read_text(encoding='utf-8')
            with self.subTest(name):
                self.assertIn('AGENTS.md#install-openwiz', text)

    def test_install_help_names_the_phrase_and_keeps_the_commands(self):
        text = (ROOT / 'tools/install/install').read_text(encoding='utf-8')
        self.assertIn("OpenWiz's install entry (#1109): the commands the install skill runs.", text)
        self.assertIn('The install instruction is: Install OpenWiz.', text)


if __name__ == '__main__':
    unittest.main()
