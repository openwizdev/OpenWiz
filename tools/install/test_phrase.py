#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import io
import json
import re
import shlex
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
PHRASE = 'Install OpenWiz'
QUOTE = '> ' + PHRASE
SURFACES = ('README.md', 'AGENTS.md', 'docs/install.md', 'docs/first-hour.md', 'docs/grok-bot.md')
FORBIDDEN = 'Install OpenWiz from'
SKILL_010_COMMIT = '33eef93ba30cd8db256f6fe270e3ed28747a79bd'
SKILL_010_TREE = '30d1eaf27658efd8f781f98703fbbdb81bcd705d'
SKILL_010 = f'https://github.com/openwizdev/WizSkills/blob/{SKILL_010_COMMIT}/skills/install/SKILL.md'
SKILL_TEMPLATE = 'https://github.com/openwizdev/WizSkills/blob/<commit>/skills/install/SKILL.md'
SKILL_TAG = re.compile(r'https://github\.com/openwizdev/WizSkills/blob/(v[0-9][^/\s)]*)/skills/install/SKILL\.md')
SKILL_COMMIT = re.compile(r'https://github\.com/openwizdev/WizSkills/blob/([0-9a-f]{40})/skills/install/SKILL\.md')
OPEN_RANGE = re.compile(r'\bv?\d+\.\d+\.\d+\s+(?:or later|or newer|and later|onward)\b')
NAMED_SKILL = re.compile(r'WizSkills (\d+\.\d+\.\d+)')
MISSING_LOCK = 'lock has no `commit`, stop and say so'
TAG_PATTERN = r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
COMMIT_PATTERN = r'[0-9a-f]{40}'
REPO = 'https://github.com/openwizdev/OpenWiz'
SAFE_CLONE = 'git clone --depth 1 --branch "$tag" -- ' + REPO + ' "$openwiz"'
TAGGED_INSTALLER = '"$openwiz"/tools/install/install'
DOWNLOAD_PIN = '--version "$tag"'


def clone_argv(tag, directory):
    if re.fullmatch(TAG_PATTERN, tag) is None:
        raise ValueError('tag')
    if (not isinstance(directory, str) or not directory or directory.startswith('-')
            or '\n' in directory or '\x00' in directory):
        raise ValueError('directory')
    return ['git', 'clone', '--depth', '1', '--branch', tag, '--', REPO, directory]


def read_lock(text):
    data = json.loads(text)
    version, commit = data.get('version', ''), data.get('commit', '')
    if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('wizskills.lock version')
    if not isinstance(commit, str) or not re.fullmatch(COMMIT_PATTERN, commit):
        raise ValueError('wizskills.lock commit')
    return version, commit


def lock_pin():
    return read_lock((ROOT / 'wizskills.lock').read_text(encoding='utf-8'))


def skill_url_for_lock(template, lock_text):
    if template != SKILL_TEMPLATE:
        raise ValueError('template')
    _, commit = read_lock(lock_text)
    return template.replace('<commit>', commit)


def section_010(guide):
    match = re.search(r'^## OpenWiz 0\.1\.0\n(.*?)(?=^## |\Z)', guide, re.M | re.S)
    return match.group(0) if match else ''


def load_entry():
    loader = importlib.machinery.SourceFileLoader('install_entry_phrase', str(HERE / 'install'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def pin_failures(section, guide, version):
    failures = []
    if 'wizskills.lock' not in section or '<commit>' not in section:
        failures.append('the agent section does not derive the skill from the release tag\'s wizskills.lock commit')
    if MISSING_LOCK not in section:
        failures.append('a release with no wizskills.lock commit does not stop')
    if SAFE_CLONE not in section:
        failures.append('the agent section clones without -- before the repository')
    if TAG_PATTERN not in section or COMMIT_PATTERN not in section or 'whole value' not in section:
        failures.append('the agent section does not require the whole tag and the whole commit')
    if '--branch v0.1.1' in section:
        failures.append('the agent section clones v0.1.1')
    for tag in SKILL_TAG.findall(section):
        failures.append('the agent section hardcodes %s instead of the lock commit' % tag)
    for sha in SKILL_COMMIT.findall(section):
        if sha != SKILL_010_COMMIT:
            failures.append('the agent section hardcodes commit %s instead of <commit>' % sha)
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
    for sha in SKILL_COMMIT.findall(guide):
        if sha != SKILL_010_COMMIT:
            failures.append('the install guide hardcodes commit %s instead of <commit>' % sha)
    for named in NAMED_SKILL.findall(guide):
        if named != version:
            failures.append('the install guide names WizSkills %s while wizskills.lock is %s' % (named, version))
    return failures


def fallback_010_failures(section, guide):
    failures = [why for needed, why in (
        (SKILL_010_COMMIT, 'agent 0.1.0 fallback omits the pinned WizSkills commit'),
        (SKILL_010_TREE, 'agent 0.1.0 fallback omits the pinned skills/install tree OID'),
        ('rev-parse HEAD:skills/install', 'agent 0.1.0 fallback does not verify the fetched skills/install tree'),
        ('0.2.0', 'agent 0.1.0 fallback does not warn against restarting onto the packaged 0.2.0 skill'),
    ) if needed not in section]
    old = section_010(guide)
    failures += [why for needed, why in (
        ('git clone --depth 1 --branch v0.1.0 -- ' + REPO + ' "$openwiz"', '0.1.0 runbook omits v0.1.0 clone'),
        ('install preflight', '0.1.0 runbook omits preflight'),
        ('releases/download/v0.1.0/', '0.1.0 runbook omits explicit v0.1.0 download'),
        ('install install --assets', '0.1.0 runbook omits install install --assets'),
        ('--build-identity', '0.1.0 runbook omits --build-identity'),
        ('runtime/setup/setup.py check', '0.1.0 runbook omits setup.py check'),
        ('runtime/setup/github_login.py sign-in', '0.1.0 runbook omits github_login.py sign-in'),
        ('runtime/cloudroom/cloudroom.py', '0.1.0 runbook omits cloudroom.py commands'),
        ('install skills --root', '0.1.0 runbook omits install skills'),
        (SKILL_010_COMMIT, '0.1.0 runbook omits pinned WizSkills commit'),
        (SKILL_010_TREE, '0.1.0 runbook omits pinned skills/install tree OID'),
        ('rev-parse HEAD:skills/install', '0.1.0 runbook omits tree OID verification'),
        ('.openwiz-skill', '0.1.0 runbook omits .openwiz-skill check'),
        ('^version: 0.2.2$', '0.1.0 runbook omits version 0.2.2 check'),
        ('install ope[n] ', '0.1.0 runbook omits rejecting 0.2.0 install open copy'),
    ) if needed not in old]
    return failures


def tagged_download_commands(guide):
    return [line.strip() for line in guide.splitlines() if f'{TAGGED_INSTALLER} download ' in line]


def download_pin_failures(section, guide):
    failures = []
    if DOWNLOAD_PIN not in section:
        failures.append('the agent section does not pass --version "$tag" to install download')
    if not re.search(r'before[^\n.]*activat', section, re.I):
        failures.append('the agent section does not check the selected version before activation')
    lines = tagged_download_commands(guide)
    if not lines or any(DOWNLOAD_PIN not in line for line in lines):
        failures.append('the install guide download command omits --version "$tag"')
    step2 = guide.split('2. **Verified download and install.**', 1)
    body = step2[1].split('\n3. **', 1)[0] if len(step2) == 2 else ''
    dl_at = body.find(f'{TAGGED_INSTALLER} download ')
    install_at = body.find(f'{TAGGED_INSTALLER} install --assets')
    between = body[dl_at:install_at] if 0 <= dl_at < install_at else ''
    if 'before activation' not in between.lower() or '"version"' not in between:
        failures.append('the install guide does not check the downloaded version before running install install')
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
        for needed in (QUOTE, 'That phrase is enough to start.',
                       'https://github.com/openwizdev/OpenWiz/releases/latest',
                       'https://github.com/openwizdev/OpenWiz', 'where your agents run', 'yes before each change'):
            self.assertIn(needed, section, needed)

    def test_tag_and_commit_cannot_inject_clone_options(self):
        loose = re.compile(r'v[0-9]+\.[0-9]+\.[0-9]+')
        self.assertIsNotNone(loose.search('v0.1.1 --upload-pack=evil'))
        self.assertEqual(clone_argv('v0.1.1', '/tmp/openwiz-synthetic'),
                         ['git', 'clone', '--depth', '1', '--branch', 'v0.1.1', '--', REPO, '/tmp/openwiz-synthetic'])
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
        for needed in (TAG_PATTERN, COMMIT_PATTERN, SAFE_CLONE):
            self.assertIn(needed, section)
        for needed in (TAG_PATTERN, SAFE_CLONE):
            self.assertIn(needed, guide)

    def test_the_checkout_follows_the_lock(self):
        version, commit = lock_pin()
        section = self.section()
        guide = (ROOT / 'docs/install.md').read_text(encoding='utf-8')
        self.assertEqual(pin_failures(section, guide, version), [])
        for needed in (SKILL_010, '`0.1.0`', 'docs/install.md#openwiz-010', '`v0.1.0`', MISSING_LOCK,
                       'including `v0.1.1`', 'openwiz=$(mktemp -d)',
                       "not the `commit` in that tag's `wizskills.lock`", 'expect build identity `0.1.1`',
                       'When `<version>` is not `0.1.1`, stop unless that guide expects `<version>`'):
            self.assertIn(needed, section)
        self.assertNotEqual(commit, SKILL_010_COMMIT)
        self.assertNotIn('blob/%s/' % commit, section)
        self.assertNotIn('blob/%s/' % commit, guide)
        for needed in ('command reference for OpenWiz 0.1.1', 'ARM64 (aarch64)',
                       'hard `GLIBC_2.39` requirement does not start'):
            self.assertIn(needed, guide)
        self.assertNotIn('command reference for that same tag', guide)
        self.assertNotIn('Linux on ARM is not supported', guide)
        self.assertIn('docs/install.md#openwiz-010', (ROOT / 'README.md').read_text(encoding='utf-8'))

    def test_documented_skill_url_derives_commit_from_lock(self):
        version, commit = lock_pin()
        section = self.section()
        guide = (ROOT / 'docs/install.md').read_text(encoding='utf-8')
        self.assertIn(SKILL_TEMPLATE, section)
        raw_lock = (ROOT / 'wizskills.lock').read_text(encoding='utf-8')
        self.assertEqual(skill_url_for_lock(SKILL_TEMPLATE, raw_lock), SKILL_TEMPLATE.replace('<commit>', commit))
        forged = 'a' * 40
        self.assertEqual(skill_url_for_lock(SKILL_TEMPLATE, raw_lock.replace(commit, forged)),
                         SKILL_TEMPLATE.replace('<commit>', forged))
        for bad in ('{"version":"0.5.0"}', '{"version":"0.5.0","commit":"-deadbeef"}',
                    '{"version":"0.5.0","commit":"deadbeef"}', '{"version":"0.5.0","commit":"' + 'A' * 40 + '"}'):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    skill_url_for_lock(SKILL_TEMPLATE, bad)
        for sha in (commit, forged):
            url = SKILL_TEMPLATE.replace('<commit>', sha)
            self.assertTrue(any(sha in f for f in pin_failures(section + '\n' + url, guide, version)))
            self.assertTrue(any(sha in f for f in pin_failures(section, guide + '\n' + url, version)))

    def test_010_fallback_recovers_pinned_skill_and_covers_setup_and_replacement(self):
        section = self.section()
        guide = (ROOT / 'docs/install.md').read_text(encoding='utf-8')
        self.assertEqual(fallback_010_failures(section, guide), [])
        self.assertTrue(fallback_010_failures(section.replace(SKILL_010_TREE, '0' * 40), guide))
        self.assertTrue(fallback_010_failures(section, guide.replace('runtime/setup/setup.py check', '')))
        self.assertTrue(fallback_010_failures(section, guide.replace('^version: 0.2.2$', '')))

    def test_011_fallback_downloads_selected_tag_and_checks_version_before_activation(self):
        section = self.section()
        guide = (ROOT / 'docs/install.md').read_text(encoding='utf-8')
        lines = tagged_download_commands(guide)
        self.assertEqual(len(lines), 1, lines)
        sys.path.insert(0, str(HERE))
        import test_install as fixture
        f = fixture.Bundles()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target = fixture.TARGETS[2]
        def publish(ver, src):
            arc = f'openwiz-{ver}-{target}.tar.gz'
            b = f.bundle(target=target, source=src, version=ver, mutate=lambda m: m.__setitem__('archive', arc))
            raw, data = b[0].read_bytes(), b[1].read_bytes()
            return {'sha': f'{fixture.sha(raw)}  openwiz-{target}.manifest.json\n'.encode(), 'raw': raw,
                    'arc_name': arc, 'arc': data,
                    'sums': f'{fixture.sha(raw)}  openwiz-{ver}-{target}.manifest.json\n{fixture.sha(data)}  {arc}\n'.encode()}
        releases = {'0.1.1': publish('0.1.1', '1' * 40), '0.1.2': publish('0.1.2', '2' * 40)}
        urls = []
        def serve(latest_ver, v011_ver='0.1.1'):
            def fetch(url, limit):
                urls.append(url)
                rel = releases[latest_ver] if '/releases/latest/' in url else (
                    releases[v011_ver] if '/download/v0.1.1/' in url else releases['0.1.2'])
                if url.endswith('.sha256'):
                    return rel['sha']
                if url.endswith('.manifest.json'):
                    return rel['raw']
                if url.endswith('SHA256SUMS'):
                    return rel['sums']
                if url.endswith(rel['arc_name']):
                    return rel['arc']
                raise AssertionError(url)
            return fetch
        dl = f.base / 'dl-011'
        cmd = lines[0].replace('"$tag"', 'v0.1.1').replace('<target>', target).replace('<new private folder>', shlex.quote(str(dl)))
        argv = shlex.split(cmd)[3:]
        entry = load_entry()
        out = io.StringIO()
        code = entry.main(argv, fetch=serve('0.1.2'), stdout=out)
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())['version'], '0.1.1')
        self.assertFalse(any('/releases/latest/' in u for u in urls), urls)
        out2 = io.StringIO()
        code2 = entry.main(['install', '--assets', str(dl), '--target', target, '--root', str(f.root)], stdout=out2)
        self.assertEqual((code2, json.loads(out2.getvalue())['version']), (0, '0.1.1'))
        bad = io.StringIO()
        bad_code = entry.main(['download', '--target', target, '--dir', str(f.base / 'dl-bad'), '--version', 'v0.1.1'],
                              fetch=serve('0.1.2', v011_ver='0.1.2'), stdout=bad)
        self.assertEqual(bad_code, 5, bad.getvalue())
        self.assertFalse((f.base / 'dl-bad').exists())
        self.assertEqual(download_pin_failures(section, guide), [])
        self.assertTrue(download_pin_failures(section.replace(DOWNLOAD_PIN, ''), guide))
        self.assertTrue(download_pin_failures(section.replace('activat', 'install'), guide))
        self.assertTrue(download_pin_failures(section, guide.replace(DOWNLOAD_PIN, '')))
        self.assertTrue(download_pin_failures(section, guide.replace('Check before activation', 'Afterwards check')))

    def test_each_pin_failure_is_its_own_case(self):
        version = '9.9.9'
        whole = TAG_PATTERN + ' ' + COMMIT_PATTERN + ' whole value'
        section = 'wizskills.lock <commit> ' + MISSING_LOCK + '\n' + SAFE_CLONE + '\n' + whole
        guide = 'wizskills.lock ' + whole + '\n' + SAFE_CLONE + '\n'
        self.assertEqual(pin_failures(section, guide, version), [])
        python_only = section + '\nYou need Python 3.9 or later.\n'
        self.assertEqual(pin_failures(python_only, guide, version), [])
        cases = (
            (section.replace('wizskills.lock', 'lockfile'), guide, 'does not derive'),
            (section.replace('<commit>', '<sha>'), guide, 'does not derive'),
            (section.replace(MISSING_LOCK, 'GitHub has no Latest release: stop and say so'), guide, 'does not stop'),
            (section.replace(SAFE_CLONE, 'git clone --branch "$tag" ' + REPO), guide, 'clones without'),
            (section.replace(TAG_PATTERN, 'v[0-9]+'), guide, 'whole tag'),
            (section.replace(COMMIT_PATTERN, '[0-9a-f]+'), guide, 'whole tag'),
            (section.replace('whole value', 'a prefix'), guide, 'whole tag'),
            (section + '\n--branch v0.1.1\n', guide, 'clones v0.1.1'),
            (section + '\nhttps://github.com/openwizdev/WizSkills/blob/v9.9.9/skills/install/SKILL.md\n',
             guide, 'hardcodes v9.9.9'),
            (section + '\n0.1.1 or later https://github.com/openwizdev/WizSkills/blob/v1.2.3/skills/install/SKILL.md\n',
             guide, 'open-ended range'),
            (section, guide.replace('wizskills.lock', 'lockfile'), 'does not name wizskills.lock'),
            (section, guide.replace(SAFE_CLONE, 'git clone --branch <tag> ' + REPO), 'whole-value'),
            (section, guide.replace(TAG_PATTERN, 'v[0-9]+'), 'whole-value'),
            (section, guide.replace('whole value', 'a prefix'), 'whole-value'),
            (section, guide + '\n--branch v0.1.1\n', 'clones --branch v0.1.1'),
            (section, guide + '\nhttps://github.com/openwizdev/WizSkills/blob/v1.2.3/skills/install/SKILL.md\n',
             'hardcodes v1.2.3'),
            (section, guide + '\nWizSkills 1.2.3\n', 'names WizSkills 1.2.3'),
        )
        for bad_section, bad_guide, needle in cases:
            with self.subTest(needle=needle):
                failures = pin_failures(bad_section, bad_guide, version)
                self.assertTrue(any(needle in item for item in failures), failures)
        same = pin_failures(section, guide + '\nWizSkills 9.9.9\n', version)
        self.assertFalse(any('names WizSkills' in item for item in same), same)

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
