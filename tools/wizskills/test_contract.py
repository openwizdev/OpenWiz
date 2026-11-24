#!/usr/bin/env python3
import copy
import datetime
import fnmatch
import json
from pathlib import Path, PurePosixPath
import re
import unittest
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / 'contracts/wizskills.v1.md'
FIXTURES = Path(__file__).resolve().parent / 'fixtures/contract'
RULES = ('link', 'script', 'import', 'read', 'symlink')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def read_json(text):
    return json.loads(text, object_pairs_hook=unique_object)


def identity(value, fields, rules):
    if not isinstance(value, dict) or set(value) != set(fields):
        return False
    return all(isinstance(value[k], str) for k in fields) and bool(
        re.fullmatch(rules['version_pattern'], value['version'])
        and re.fullmatch(rules['oid_pattern'], value['commit'])
        and re.fullmatch(rules['oid_pattern'], value['tree']))


def manifest(text):
    try:
        return read_json(text)
    except ValueError:
        return {}


def package_errors(package, rules):
    errors = set()
    files = package['files']
    for path in rules['required_files'] + rules['carried_contracts']:
        if path not in files:
            errors.add('layout')
    skills = sorted({p.split('/')[1] for p in files if p.startswith('skills/')
                     and p.endswith('/SKILL.md')})
    for name in skills:
        for suffix in rules['skill_files']:
            if f'skills/{name}/{suffix}' not in files:
                errors.add('layout')
    if not skills:
        errors.add('layout')
    executables = package['executables']
    if 'install.sh' not in executables or any(p not in files for p in executables):
        errors.add('layout')
    plugin, marketplace = (manifest(files[f'.claude-plugin/{n}.json']) for n in ('plugin', 'marketplace'))
    if (plugin.get('name') != rules['plugin_name']
            or plugin.get('skills') != [f'./skills/{s}' for s in skills]
            or len(marketplace.get('plugins', [])) != 1
            or marketplace.get('name') != rules['marketplace_name']
            or marketplace['plugins'][0].get('name') != rules['plugin_name']
            or marketplace['plugins'][0].get('source') != './'):
        errors.add('plugin')
    lock, release = package['lock'], package['release']
    if not identity(lock, rules['lock_fields'], rules):
        errors.add('lock')
    if (not identity(release, rules['release_fields'], rules)
            or release.get('schema') != rules['release_schema']):
        errors.add('release')
    if 'lock' not in errors and 'release' not in errors:
        if any(lock[k] != release[k] for k in rules['lock_fields']):
            errors.add('binding')
        if package['tag'] != 'v' + lock['version']:
            errors.add('binding')
    changelog = files['CHANGELOG.md']
    section = r'## (\S+) - (\d{4}-\d{2}-\d{2})\n\n(?:- [^\n]+\n)+'
    sections = re.findall(section, changelog)
    valid = bool(re.fullmatch(rf'# Changelog\n(?:\n{section})+', changelog))
    try:
        for _, day in sections:
            datetime.date.fromisoformat(day)
    except ValueError:
        valid = False
    if not valid or len({v for v, _ in sections}) != len(sections):
        errors.add('changelog')
    elif (plugin.get('version') != sections[0][0]
          or plugin.get('version') != lock.get('version')
          or not all(re.fullmatch(rules['version_pattern'], v) for v, _ in sections)):
        errors.add('version')
    elif [d for _, d in sections] != sorted((d for _, d in sections), reverse=True):
        errors.add('changelog')
    return sorted(errors)


def reference_result(case, files, rules):
    kind, target = case['kind'], case['target']
    if kind == 'data':
        return None
    setting = any(fnmatch.fnmatchcase(target, p)
                  and len(target.split('/')) == len(p.split('/'))
                  for p in rules['project_settings'])
    if (setting and '..' not in PurePosixPath(target).parts
            and (kind == 'words' or (kind == 'read' and case.get('project')))):
        return None
    rule = kind if kind in RULES else 'read'
    failure = {'rule': 'standalone.' + rule, 'file': case['file'], 'line': case['line']}
    if kind not in RULES + ('words',) or kind == 'symlink' or not target or target.startswith(('/', '~')):
        return failure
    parts = list(PurePosixPath(case['base']).parts)
    for part in PurePosixPath(unquote(target).split('#')[0]).parts:
        if part == '..':
            if not parts:
                return failure
            parts.pop()
        elif part != '.':
            parts.append(part)
    return None if '/'.join(parts) in files else failure


class ContractTests(unittest.TestCase):
    def rules(self):
        self.assertTrue(CONTRACT.is_file(), 'WZ-P1 requires the WizSkills contract')
        blocks = re.findall(r'^```wizskills-v1\n(.*?)^```',
                            CONTRACT.read_text(), re.M | re.S)
        self.assertEqual(len(blocks), 1, 'one normative rules block')
        rules = read_json(blocks[0])
        self.assertEqual(rules['schema'], 'openwiz.wizskills.v1')
        return rules

    def test_valid_package_and_carried_sources(self):
        rules = self.rules()
        package = read_json((FIXTURES / 'package.json').read_text())
        self.assertEqual(package_errors(package, rules), [])
        paths = rules['carried_contracts']
        self.assertEqual(len(paths), len(set(paths)))
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(path.startswith('contracts/'))
                self.assertNotIn('..', PurePosixPath(path).parts)
                self.assertTrue((ROOT / path).is_file(), 'carried source exists')

    def test_refusal_examples(self):
        rules = self.rules()
        package = read_json((FIXTURES / 'package.json').read_text())
        cases = read_json((FIXTURES / 'refusals.json').read_text())
        for case in cases:
            with self.subTest(name=case['name']):
                changed = copy.deepcopy(package)
                parent = changed
                for key in case['at'][:-1]:
                    parent = parent[key]
                key = case['at'][-1]
                if case.get('delete'):
                    del parent[key]
                else:
                    parent[key] = case['value']
                self.assertEqual(package_errors(changed, rules), case['errors'])

    def test_historical_changelog_headings_are_checked(self):
        rules = self.rules()
        package = read_json((FIXTURES / 'package.json').read_text())
        current = '# Changelog\n\n## 0.1.0 - 2030-01-02\n\n- Synthetic change.\n\n'
        for name, earlier, errors in (
                ('non-SemVer earlier heading', '## not-semver - 2030-01-01', ['version']),
                ('earlier section dated later', '## 0.1.0-rc.1 - 2030-01-03', ['changelog']),
                ('earlier section on the same day', '## 0.1.0-rc.1 - 2030-01-02', [])):
            with self.subTest(name=name):
                changed = copy.deepcopy(package)
                changed['files']['CHANGELOG.md'] = f'{current}{earlier}\n\n- Earlier change.\n'
                self.assertEqual(package_errors(changed, rules), errors)

    def test_standalone_resolution_examples_and_safe_diagnostics(self):
        rules = self.rules()
        package = read_json((FIXTURES / 'package.json').read_text())
        cases = read_json((FIXTURES / 'references.json').read_text())
        for case in cases:
            with self.subTest(name=case['name']):
                self.assertEqual(reference_result(case, package['files'], rules),
                                 case['expected'])
                if case['expected']:
                    self.assertEqual(set(case['expected']), {'rule', 'file', 'line'})

    def test_duplicate_json_keys_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'duplicate key'):
            read_json('{"version":"0.1.0","version":"0.2.0"}')


if __name__ == '__main__':
    unittest.main()
