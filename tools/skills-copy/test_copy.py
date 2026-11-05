#!/usr/bin/env python3
"""P13 command proofs. Every repository, identifier and quoted reply is synthetic."""
import datetime
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TOOL = HERE / 'copy.py'
DECIDER = 'Ja' + 'ke'
TARGET = 'git@github.com:openwizdev/WizSkills.git'
# Carried bytes a text-mode copy would change: CRLF, no final newline, UTF-8, a NUL.
CARRIED = {'contracts/alpha.v1.md': 'Synthetic \u00e9 contract\r\nno final newline'.encode(),
           'contracts/alpha.v1.schema.json': b'{"synthetic": true}\r\n\x00'}


def contract(carried):
    return ('# Synthetic WizSkills contract\n\n```wizskills-v1\n' + json.dumps({
        'schema': 'openwiz.wizskills.v1', 'carried_contracts': carried,
        'project_settings': ['docs/agents/*.md', 'changes/README.md', 'GLOSSARY.md']}) + '\n```\n')
REAL_GIT = shutil.which('git')
REPO = HERE.parents[1]
REAL_TOOLS = ('tools/skills-copy/standalone.py', 'tools/privacy-check/check.py')
# WZ14 (#2891): what the copy writes into check/ beside WZ7's entrypoint.
GENERATED_CHECK = {'check/standalone.py', 'check/wizskills.v1.json', 'check/redact.py'}
VERSION = '0.1.0'
# A synthetic upstream notice, carried by a skill, as the real skills carry theirs.
NOTICE = ('Copyright (c) 2030 Synthetic Author\n\nPermission is hereby granted, free of charge, '
          'to any person obtaining a copy.\n\nTHE SOFTWARE IS PROVIDED "AS IS". IN NO EVENT SHALL '
          'THE AUTHORS BE LIABLE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE '
          'OR OTHER DEALINGS IN THE\nSOFTWARE.\n')
PACKAGE_FILES = {
    'wizdev/skills/board/SKILL.md': '# Board\n\n' + NOTICE,
    # WZ7's real layout: check/run.py is the entrypoint; the README, tests and
    # red run are ClosedWiz's own proofs of that folder and are never carried.
    'tools/skills-copy/package-check/check/run.py': '# Synthetic check entrypoint\n',
    'tools/skills-copy/package-check/README.md': '# Synthetic check source notes\n',
    'tools/skills-copy/package-check/test_check.py': '# Synthetic ClosedWiz-only proof\n',
    'tools/skills-copy/package-check/red-run.txt': 'synthetic ClosedWiz-only red run\n',
    'tools/skills-copy/package-check/ci.yml': (
        'name: check\non: [push, pull_request]\npermissions:\n  contents: read\njobs:\n  check:\n'
        '    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@v4\n'
        '      - run: python3 check/run.py\n'),
}


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='skills-copy-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_CONFIG_GLOBAL=str(self.root / 'gitconfig'),
                        GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0',
                        GIT_AUTHOR_NAME='Synthetic', GIT_COMMITTER_NAME='Synthetic',
                        GIT_AUTHOR_EMAIL='synthetic@users.noreply.github.com',
                        GIT_COMMITTER_EMAIL='synthetic@users.noreply.github.com')
        # Real Git transport, redirected to local fixtures; log and reject any force.
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        wrapper = self.bin / 'git'
        wrapper.write_text('#!' + sys.executable + '\nimport os,sys,json\n'
                           'a=sys.argv[1:]\n'
                           'with open(os.environ["COPY_GIT_LOG"],"a") as f: f.write(json.dumps(a)+"\\n")\n'
                           'if any(x in ("--force","-f","--force-with-lease") or x.startswith("+") for x in a): sys.exit(93)\n'
                           'if "push" in a and os.environ.get("COPY_FAIL_PUSH"): sys.exit(94)\n'
                           'if any(op in a for op in ("push","fetch","ls-remote")): a=[os.environ["COPY_REMOTE"] if x=="origin" else x for x in a]\n'
                           f'os.execv({REAL_GIT!r},[{REAL_GIT!r}]+a)\n')
        wrapper.chmod(0o755)
        self.log = self.root / 'git.log'
        self.env.update(PATH=str(self.bin) + os.pathsep + self.env['PATH'], COPY_GIT_LOG=str(self.log),
                        COPY_REMOTE=str(self.root / 'remote.git'))
        self.source = self.root / 'source'
        self.source.mkdir()
        self.git(self.source, 'init', '-q', '-b', 'main')
        files = {
            'skills/alpha/SKILL.md': '# Alpha\nSynthetic skill.\n',
            'skills/alpha/scripts/run.sh': '#!/bin/sh\nexit 0\n',
            'skills/alpha/test/case.txt': 'synthetic fixture\n',
            '.claude/skills/export-review/SKILL.md': '# Export review\n',
            '.claude/skills/live-quick-check/SKILL.md': '# Quick check\n',
            '.claude/skills/live-spike/SKILL.md': '# Spike\n',
            'wizdev/skills/board/SKILL.md': '# Board\n',
            'private/planted.txt': 'must stay private\n',
            '.claude/skills/unreviewed/SKILL.md': 'must stay off list\n',
            'not-skills/off-list.txt': 'must stay off list\n',
            'contracts/wizskills.v1.md': contract(sorted(CARRIED)),
            'contracts/uncarried.v1.md': 'must stay off list\n',
        }
        files.update(PACKAGE_FILES)
        for name, data in files.items(): self.write(name, data)
        for name, data in CARRIED.items(): (self.source / name).write_bytes(data)
        (self.source / 'skills/alpha/scripts/run.sh').chmod(0o755)
        shutil.copytree(HERE / 'package', self.source / 'tools/skills-copy/package')
        # The scanner and the privacy check's redaction come from the pinned commit too.
        for name in REAL_TOOLS:
            (self.source / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / name, self.source / name)
        self.commit()
        self.bare = self.root / 'remote.git'
        self.git(self.root, 'init', '--bare', '-q', '-b', 'main', str(self.bare))
        self.dest = self.root / 'destination'
        self.git(self.root, 'clone', '-q', str(self.bare), str(self.dest))
        (self.dest / 'old.txt').write_text('old synthetic copy\n')
        self.git(self.dest, 'add', '.')
        self.git(self.dest, 'commit', '-qm', 'Synthetic destination seed')
        self.git(self.dest, 'push', '-q', 'origin', 'main')
        self.seed = self.git(self.bare, 'rev-parse', 'main').stdout.strip()
        self.git(self.dest, 'remote', 'set-url', 'origin', TARGET)
        self.literals = self.root / 'literals.txt'
        self.literals.write_text('synthetic-denied-machine\n')
        self.log.write_text('')

    def git(self, cwd, *args):
        return subprocess.run(['git', '-C', str(cwd), *args], env=self.env,
                              capture_output=True, text=True, check=True)

    def write(self, name, data):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)

    def commit(self):
        self.git(self.source, 'add', '.')
        self.git(self.source, 'commit', '-qm', 'Synthetic skills')
        return self.git(self.source, 'rev-parse', 'HEAD').stdout.strip()

    def run_copy(self, *args, ok=True, env=None, automatic_literals=False, version=VERSION):
        p = subprocess.run([sys.executable, '-I', str(TOOL), '--source', str(self.source),
                            '--commit', 'HEAD', *([] if version is None else ['--version', version]),
                            *([] if automatic_literals else ['--literals', str(self.literals)]), *args],
                           env=env or self.env, capture_output=True, text=True, timeout=30)
        if ok: self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        else: self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def remote_head(self):
        return self.git(self.bare, 'rev-parse', 'main').stdout.strip()

    def test_exact_selection_install_files_and_determinism(self):
        outputs = [self.root / 'copy1', self.root / 'copy2']
        results = [self.run_copy('--output', str(o)) for o in outputs]
        # The three ClosedWiz release skills in .claude/skills/ stay private.
        expected_skills = ['alpha', 'board']
        expected = {'.claude-plugin/plugin.json', '.claude-plugin/marketplace.json', 'README.md',
                    'CHANGELOG.md', 'LICENSE', 'install.sh', 'check/run.py', *GENERATED_CHECK,
                    'skills/README.md', '.github/workflows/ci.yml', 'skills/alpha/scripts/run.sh',
                    'skills/alpha/test/case.txt', *CARRIED}
        for name in expected_skills:
            expected.update({f'skills/{name}/SKILL.md', f'.agents/skills/{name}', f'.claude/skills/{name}'})
        inventories = []
        for output in outputs:
            paths = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file() or p.is_symlink()}
            self.assertEqual(paths, expected)
            manifest = json.loads((output / '.claude-plugin/plugin.json').read_text())
            self.assertEqual(manifest['skills'], ['./skills/' + n for n in expected_skills])
            market = json.loads((output / '.claude-plugin/marketplace.json').read_text())
            self.assertEqual(market['plugins'], [dict(market['plugins'][0], name='openwiz', source='./')])
            for name in expected_skills:
                for prefix in ('.agents', '.claude'):
                    link = output / prefix / 'skills' / name
                    self.assertTrue(link.is_symlink())
                    self.assertEqual(link.resolve(), output / 'skills' / name)
            self.assertEqual((output / 'skills/alpha/scripts/run.sh').stat().st_mode & 0o777, 0o755)
            self.assertEqual((output / 'skills/alpha/test/case.txt').read_text(), 'synthetic fixture\n')
            inventories.append({n: (os.readlink(output / n) if (output / n).is_symlink()
                                    else (output / n).read_bytes()) for n in paths})
        self.assertEqual(inventories[0], inventories[1])
        self.assertEqual(json.loads(results[0].stdout)['tree'], json.loads(results[1].stdout)['tree'])
        self.assertEqual(json.loads(results[0].stdout)['standalone'], {'status': 'pass', 'skills': {}})
        self.assertFalse(any('push' in json.loads(line) or 'fetch' in json.loads(line) for line in self.log.read_text().splitlines()))

    # WZ3 (#2631), WZ-P5: the versioned package files, from the pinned commit.
    def test_dry_run_writes_the_versioned_package(self):
        output = self.root / 'copy'
        result = json.loads(self.run_copy('--output', str(output)).stdout)
        # WZ2 (#2630): the three .claude/skills release skills are not carried.
        skills = ['alpha', 'board']
        self.assertEqual(result['package'], {'version': VERSION, 'check': 'carried'})
        plugin = json.loads((output / '.claude-plugin/plugin.json').read_text())
        self.assertEqual((plugin['name'], plugin['version'], plugin['skills']),
                         ('openwiz', VERSION, ['./skills/' + n for n in skills]))
        market = json.loads((output / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(market['name'], 'wizskills')
        self.assertIsInstance(market['owner'], dict)
        self.assertEqual([(p['name'], p['source']) for p in market['plugins']], [('openwiz', './')])
        self.assertNotIn('version', market['plugins'][0])
        changelog = (output / 'CHANGELOG.md').read_text().split('\n')
        self.assertEqual(changelog[:2], ['# Changelog', ''])
        self.assertRegex(changelog[2], r'^## 0\.1\.0 - 20[0-9]{2}-[01][0-9]-[0-3][0-9]$')
        datetime.date.fromisoformat(changelog[2][-10:])
        section = changelog[4:changelog.index('', 4)]
        self.assertEqual(section, ["- First public release of OpenWiz's skills, one line per skill below."]
                         + [f'- `{n}`: first public release.' for n in skills])
        readme = (output / 'README.md').read_text()
        for pinned in ('https://github.com/openwizdev/WizSkills.git#v0.1.0', '--version 0.1.0'):
            self.assertIn(pinned, readme)
        self.assertNotIn('{{', readme)
        self.assertEqual((output / 'install.sh').read_bytes(), (HERE / 'package/install.sh').read_bytes())
        self.assertEqual((output / 'install.sh').stat().st_mode & 0o777, 0o755)
        self.assertEqual((output / 'check/run.py').read_text(),
                         PACKAGE_FILES['tools/skills-copy/package-check/check/run.py'])
        self.assertEqual((output / 'check/standalone.py').read_bytes(), (REPO / REAL_TOOLS[0]).read_bytes())
        self.assertFalse((output / 'check/check').exists())
        self.assertFalse((output / 'check/README.md').exists())
        for kept in ('test_check.py', 'red-run.txt'):
            self.assertEqual(list(output.rglob(kept)), [], kept)
        rules = (output / 'skills/README.md').read_text()
        for name in skills:
            self.assertIn(f'[`{name}`]({name}/SKILL.md)', rules)
        for rule in ('Frontmatter', 'Codex', 'Notice', 'Links', 'Manifest', 'check/run.py'):
            self.assertIn(rule, rules)
        self.assertEqual((output / '.github/workflows/ci.yml').read_text(),
                         PACKAGE_FILES['tools/skills-copy/package-check/ci.yml'])
        self.assertFalse((output / 'check/ci.yml').exists())
        licence = (output / 'LICENSE').read_text()
        self.assertEqual(licence.count('Copyright (c) 2030 Synthetic Author'), 1)
        self.assertIn(NOTICE, licence)

    def test_version_disagreeing_with_changelog_or_manifest_is_refused(self):
        package = 'tools/skills-copy/package/'
        plugin = (self.source / package / 'plugin.json').read_text()
        changelog = (self.source / package / 'CHANGELOG.md').read_text()
        cases = (('input', {}, '0.1.1'),
                 ('plugin', {'plugin.json': plugin.replace('"0.1.0"', '"0.2.0"')}, VERSION),
                 ('changelog', {'CHANGELOG.md': changelog.replace('## 0.1.0 ', '## 0.2.0 ', 1)}, VERSION),
                 ('both moved', {'plugin.json': plugin.replace('"0.1.0"', '"0.2.0"'),
                                 'CHANGELOG.md': changelog.replace('## 0.1.0 ', '## 0.2.0 ', 1)}, VERSION))
        for name, edits, version in cases:
            with self.subTest(case=name):
                for file, data in edits.items(): self.write(package + file, data)
                if edits: self.commit()
                self.log.write_text('')
                p = self.run_copy('--destination', str(self.dest), '--publish', version=version, ok=False)
                self.assertEqual(p.returncode, 1)
                self.assertIn('version', p.stderr)
                self.assertEqual(self.remote_head(), self.seed)
                self.assertFalse(any('push' in json.loads(x) for x in self.log.read_text().splitlines()))
                if edits:
                    self.write(package + 'plugin.json', plugin)
                    self.write(package + 'CHANGELOG.md', changelog)
                    self.commit()

    def test_version_input_is_required_and_strict(self):
        for version in (None, 'v0.1.0', '0.01.0', '0.0.1', 'main', '0.1.0\n'):
            with self.subTest(version=version):
                p = self.run_copy('--output', str(self.root / 'never'), version=version, ok=False)
                self.assertFalse((self.root / 'never').exists())
                self.assertNotIn('"tree"', p.stdout)

    def test_missing_check_folder_is_reported_and_blocks_publication(self):
        shutil.rmtree(self.source / 'tools/skills-copy/package-check')
        self.commit()
        output = self.root / 'copy'
        result = json.loads(self.run_copy('--output', str(output)).stdout)
        self.assertEqual(result['package'], {'version': VERSION, 'check': 'missing'})
        self.assertFalse((output / 'check').exists())
        self.assertFalse((output / '.github').exists())
        self.assertFalse((output / 'skills/README.md').exists())
        p = self.run_copy('--destination', str(self.dest), '--publish', ok=False)
        self.assertIn('check', p.stderr)
        self.assertEqual(self.remote_head(), self.seed)

    def test_unknown_or_incomplete_check_folder_is_refused(self):
        # A new file in the check source is either mapped or refused, never
        # silently carried to an unreviewed place or dropped.
        base = 'tools/skills-copy/package-check/'
        for name, change in (('unknown file', lambda: self.write(base + 'check/extra.py', '# synthetic\n')),
                             ('no entrypoint', lambda: (self.source / base / 'check/run.py').unlink()),
                             ('no workflow', lambda: (self.source / base / 'ci.yml').unlink())):
            with self.subTest(case=name):
                change()
                self.commit()
                p = self.run_copy('--output', str(self.root / 'never'), ok=False)
                self.assertIn('check folder', p.stderr)
                self.assertFalse((self.root / 'never').exists())
                self.git(self.source, 'checkout', '-q', 'HEAD~1', '--', base)
                for extra in (self.source / base / 'check/extra.py',):
                    if extra.exists(): extra.unlink()
                self.commit()

    def test_missing_scanner_or_redaction_source_is_refused(self):
        for name in REAL_TOOLS:
            with self.subTest(source=name):
                saved = (self.source / name).read_bytes()
                (self.source / name).unlink()
                self.commit()
                p = self.run_copy('--output', str(self.root / 'never'), ok=False)
                self.assertFalse((self.root / 'never').exists())
                self.assertNotIn('"tree"', p.stdout)
                (self.source / name).write_bytes(saved)
                self.commit()

    def test_redaction_needing_more_than_re_or_missing_is_refused(self):
        # The generated helper is the privacy check's own redaction, standard re
        # only: a redaction that would need another import, or none, refuses.
        name = REAL_TOOLS[1]
        saved = (self.source / name).read_text()
        for case, text in (('another import', saved.replace('    return redacted\n',
                                                              '    return os.path.normpath(redacted)\n', 1)),
                           ('no redaction', saved.replace('def redact(', 'def unrelated(', 1))):
            with self.subTest(case=case):
                self.assertNotEqual(text, saved)
                (self.source / name).write_text(text)
                self.commit()
                output = self.root / ('never-' + case.replace(' ', '-'))
                p = self.run_copy('--output', str(output), ok=False)
                self.assertIn('privacy check', p.stderr)
                self.assertFalse(output.exists())
                (self.source / name).write_text(saved)
                self.commit()

    def test_incomplete_licence_notice_is_refused(self):
        self.write('wizdev/skills/board/SKILL.md', '# Board\n\nCopyright (c) 2030 Synthetic Author\n\nPartial.\n')
        self.commit()
        p = self.run_copy(ok=False)
        self.assertIn('licence', p.stderr)

    def test_tool_sources_pass_privacy_check(self):
        # R1: newly introduced public tool sources must pass the actual public
        # tree boundary; runtime refusal cases alone do not scan their own code.
        p = subprocess.run([sys.executable, '-I', str(HERE.parent / 'privacy-check/check.py'),
                            '--tree', str(HERE)], capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_automatic_closedwiz_literals_refuse_before_destination_operations(self):
        # R2: ordinary GitHub URL spelling must not disable the named-literal
        # gate. Prior fixtures always supplied --literals and missed this path.
        origins = (
            'https://github.com/jparker2006/ClosedWiz.git',
            'https://github.com/jparker2006/closedwiz.git',
            'HTTPS://GITHUB.COM/JPARKER2006/CLOSEDWIZ.GIT/',
            'http://github.com/jparker2006/closedwiz',
            'git@github.com:jparker2006/closedwiz.git',
            'ssh://git@github.com/jparker2006/closedwiz.git',
            'ssh://git@github.com:22/JPARKER2006/closedwiz.git',
            'git://github.com/JPARKER2006/CLOSEDWIZ.git',
            'https://github.com/jparker2006/%63losedwiz.git',
            'github.com:jparker2006/closedwiz.git',
            'GITHUB.COM:JPARKER2006/CLOSEDWIZ.GIT',
            'user@github.com:jparker2006/closedwiz.git',
        )
        self.git(self.source, 'remote', 'add', 'origin', origins[0])
        self.write('skills/alpha/SKILL.md', '# Alpha\nHost synthetic-denied-machine\n')
        self.commit()
        default_list = self.source / 'private/evidence/open-development/privacy-check/literals.txt'
        default_list.parent.mkdir(parents=True, exist_ok=True)
        for origin in origins:
            self.git(self.source, 'remote', 'set-url', 'origin', origin)
            for state, rule in (('missing', 'READ'), ('empty', 'READ'), ('denied', 'T3')):
                with self.subTest(origin=origin, state=state):
                    if state == 'missing':
                        default_list.unlink(missing_ok=True)
                    else:
                        default_list.write_text('' if state == 'empty' else 'synthetic-denied-machine\n')
                    self.log.write_text('')
                    p = self.run_copy('--destination', str(self.dest), '--publish',
                                      ok=False, automatic_literals=True)
                    result = json.loads(p.stdout)
                    self.assertEqual(result['privacy']['status'], 'refused')
                    self.assertIn(rule, result['privacy']['result'])
                    if state == 'denied':
                        self.assertIn('literals: used', result['privacy']['result'])
                    self.assertIsNone(result['published'])
                    self.assertEqual(self.remote_head(), self.seed)
                    calls = [json.loads(x) for x in self.log.read_text().splitlines()]
                    self.assertFalse(any('push' in call or 'fetch' in call for call in calls))
        # A clean source with the readable nonempty automatic list still works.
        self.write('skills/alpha/SKILL.md', '# Alpha\nSynthetic clean skill.\n')
        self.commit()
        result = json.loads(self.run_copy(automatic_literals=True).stdout)
        self.assertEqual(result['privacy']['status'], 'pass')
        self.assertIn('literals: used', result['privacy']['result'])

    def test_unrelated_origins_do_not_require_closedwiz_literals(self):
        origins = (
            'https://example.invalid/jparker2006/ClosedWiz.git',
            'https://github.com/jparker2006/ClosedWiz-tools.git',
            'https://github.com/synthetic/closedwiz.git',
            'https://github.com/jparker2006/OpenWiz.git',
        )
        self.git(self.source, 'remote', 'add', 'origin', origins[0])
        for origin in origins:
            with self.subTest(origin=origin):
                self.git(self.source, 'remote', 'set-url', 'origin', origin)
                result = json.loads(self.run_copy(automatic_literals=True).stdout)
                self.assertEqual(result['privacy']['status'], 'pass')
                self.assertIn('literals: not used', result['privacy']['result'])

    def test_reads_pinned_commit_not_checkout(self):
        self.write('skills/alpha/SKILL.md', DECIDER + ': "synthetic private reply"\n')
        p = self.run_copy('--output', str(self.root / 'copy'))
        self.assertEqual(json.loads(p.stdout)['privacy']['status'], 'pass')
        self.assertEqual((self.root / 'copy/skills/alpha/SKILL.md').read_text(), '# Alpha\nSynthetic skill.\n')

    def test_refuses_private_text_before_any_publication(self):
        cases = [('thread', 'Thread ' + 'thr_' + 'plantedcopy1\n', 'T1'),
                 ('quote', DECIDER + ': "synthetic private reply"\n', 'T2'),
                 ('literal', 'synthetic-denied-machine\n', 'T3')]
        for name, data, rule in cases:
            with self.subTest(name=name):
                self.write('skills/alpha/SKILL.md', data)
                self.commit()
                self.log.write_text('')
                p = self.run_copy('--destination', str(self.dest), '--publish', ok=False)
                result = json.loads(p.stdout)
                self.assertEqual(result['privacy']['status'], 'refused')
                self.assertIn(rule, result['privacy']['result'])
                self.assertEqual(self.remote_head(), self.seed)
                self.assertFalse(any('push' in json.loads(x) for x in self.log.read_text().splitlines()))
                self.assertNotIn('fetch', self.log.read_text())

    def test_refuses_escaping_symlinks_and_private_paths(self):
        for target in ('../../../private/planted.txt', '../../../not-skills/off-list.txt', '/etc/passwd'):
            with self.subTest(target=target):
                link = self.source / 'skills/alpha/escape'
                if link.is_symlink(): link.unlink()
                link.symlink_to(target)
                self.commit()
                self.run_copy('--publish', '--destination', str(self.dest), ok=False)
                self.assertEqual(self.remote_head(), self.seed)
        (self.source / 'skills/alpha/escape').unlink()
        self.write('skills/alpha/private/planted.txt', 'synthetic\n')
        self.commit()
        self.run_copy(ok=False)

    def test_selected_root_symlink_and_submodule_are_not_silently_omitted(self):
        (self.source / 'skills/alias').symlink_to('alpha')
        self.commit()
        self.run_copy(ok=False)
        (self.source / 'skills/alias').unlink()
        self.git(self.source, 'add', '.')
        oid = self.git(self.source, 'rev-parse', 'HEAD').stdout.strip()
        self.git(self.source, 'update-index', '--add', '--cacheinfo', '160000,' + oid + ',skills/module')
        self.git(self.source, 'commit', '-qm', 'Synthetic selected submodule')
        self.run_copy(ok=False)

    def test_exact_selected_roots_refuse_symlinks_and_submodules(self):
        # P13 completeness: replacing a selected directory with an unsupported
        # Git entry must refuse, never publish a copy that silently drops it.
        # Existing coverage checks children of skills/, not exact source roots.
        # .claude/skills is no longer selected (#2630), so only these roots apply.
        for root in ('skills', 'wizdev/skills', 'wizdev'):
            for kind in ('symlink', 'submodule'):
                with self.subTest(root=root, kind=kind):
                    fixture = CopyTests()
                    fixture.setUp()
                    try:
                        path = fixture.source / root
                        shutil.rmtree(path)
                        fixture.git(fixture.source, 'add', '.')
                        if kind == 'symlink':
                            path.symlink_to('synthetic-unsupported-root')
                            fixture.git(fixture.source, 'add', '.')
                        else:
                            oid = fixture.git(fixture.source, 'rev-parse', 'HEAD').stdout.strip()
                            fixture.git(fixture.source, 'update-index', '--add', '--cacheinfo',
                                        '160000,' + oid + ',' + root)
                        fixture.git(fixture.source, 'commit', '-qm', 'Synthetic unsupported selected root')
                        fixture.log.write_text('')
                        fixture.run_copy('--destination', str(fixture.dest), '--publish', ok=False)
                        self.assertEqual(fixture.remote_head(), fixture.seed)
                        calls = [json.loads(x) for x in fixture.log.read_text().splitlines()]
                        self.assertFalse(any('push' in call or 'fetch' in call for call in calls))
                    finally:
                        fixture.doCleanups()

    def test_internal_symlink_is_a_standalone_refusal(self):
        # The contract forbids any symlink inside skills/: plugin installs may drop it.
        (self.source / 'skills/alpha/link').symlink_to('test/case.txt')
        self.commit()
        p = self.run_copy('--output', str(self.root / 'copy'), ok=False)
        self.assertEqual(json.loads(p.stdout)['standalone'], {'status': 'refused', 'skills': {'alpha': [
            {'rule': 'standalone.symlink', 'file': 'skills/alpha/link', 'line': 1}]}})
        self.assertFalse((self.root / 'copy').exists())

    def test_standalone_refusals_by_skill_never_open_publication(self):
        # WZ-P2: a skill linking, importing or running outside the tree is
        # refused with rule, file and line, before any destination operation.
        hidden = 'synthetic-hidden-target'
        self.write('skills/alpha/SKILL.md', '# Alpha\n[x](../../../' + hidden + '.md)\n')
        self.write('wizdev/skills/board/SKILL.md', '# Board\n')
        self.write('wizdev/skills/board/run.py', 'from pathlib import Path\nimport subprocess\n'
                   'subprocess.run([str(Path(__file__).resolve().parents[3] / "tools/' + hidden + '.sh")])\n'
                   'import synthetic_outside_helper\n')
        self.commit()
        self.log.write_text('')
        p = self.run_copy('--destination', str(self.dest), '--publish', ok=False)
        result = json.loads(p.stdout)
        self.assertEqual(result['standalone'], {'status': 'refused', 'skills': {
            'alpha': [{'rule': 'standalone.link', 'file': 'skills/alpha/SKILL.md', 'line': 2}],
            'board': [{'rule': 'standalone.script', 'file': 'skills/board/run.py', 'line': 3},
                      {'rule': 'standalone.import', 'file': 'skills/board/run.py', 'line': 4}]}})
        self.assertEqual(result['privacy']['status'], 'pass')
        self.assertIsNone(result['published'])
        self.assertNotIn(hidden, p.stdout + p.stderr)
        self.assertEqual(self.remote_head(), self.seed)
        calls = [json.loads(x) for x in self.log.read_text().splitlines()]
        self.assertFalse(any('push' in call or 'fetch' in call for call in calls))

    def test_instruction_and_literal_dependencies_are_refused_by_the_copy(self):
        # Review R1/R2: a fenced instruction and a literal read operand that
        # name files outside the copy are refused through the real command.
        self.write('skills/alpha/SKILL.md', '# Alpha\n```sh\npython3 tools/synthetic-missing.py\n```\n')
        self.write('skills/alpha/scripts/read.py', 'from pathlib import Path\n'
                   'print(Path("/synthetic/source/missing.json").read_text())\n')
        self.commit()
        p = self.run_copy(ok=False)
        self.assertEqual(json.loads(p.stdout)['standalone'], {'status': 'refused', 'skills': {'alpha': [
            {'rule': 'standalone.script', 'file': 'skills/alpha/SKILL.md', 'line': 3},
            {'rule': 'standalone.read', 'file': 'skills/alpha/scripts/read.py', 'line': 2}]}})

    def test_copy_report_redacts_private_forms_in_standalone_locations(self):
        # Re-check R4: the whole copy report, not only the privacy result.
        for name in ('skills/alpha/notes/the PC has ' + '16' + ' cores.md',
                     'skills/alpha/helper-checks/snapshot.' + 'aB3xQ9' + '/notes.md'):
            self.write(name, '# Note\n[x](../../../elsewhere.md)\n')
        self.write('skills/alpha/notes/synthetic-denied-machine.md', '# Note\n[x](../../../elsewhere.md)\n')
        self.commit()
        p = self.run_copy(ok=False)
        result = json.loads(p.stdout)
        self.assertEqual(result['privacy']['status'], 'refused')
        self.assertEqual(len(result['standalone']['skills']['alpha']), 3)
        self.assertIsNone(result['published'])
        for value in ('16 cores', 'aB3xQ9', 'synthetic-denied-machine'):
            self.assertNotIn(value, p.stdout + p.stderr)

    def test_carried_contracts_are_byte_identical_and_come_from_the_contract(self):
        output = self.root / 'copy'
        self.run_copy('--output', str(output))
        for name, data in CARRIED.items():
            self.assertEqual((output / name).read_bytes(), data)
        self.assertFalse((output / 'contracts/uncarried.v1.md').exists())
        self.assertFalse((output / 'contracts/wizskills.v1.md').exists())
        # A skill's ../../contracts/<file> link resolves in the copy.
        self.write('skills/alpha/SKILL.md', '# Alpha\n[c](../../contracts/alpha.v1.md)\n')
        self.commit()
        self.run_copy()
        for name, change in (('missing carried source', lambda: (self.source / 'contracts/alpha.v1.md').unlink()),
                             ('symlinked carried source', lambda: ((self.source / 'contracts/alpha.v1.md').unlink(),
                                                                   (self.source / 'contracts/alpha.v1.md').symlink_to('uncarried.v1.md'))),
                             ('no contract', lambda: (self.source / 'contracts/wizskills.v1.md').unlink()),
                             ('outside carried path', lambda: self.write('contracts/wizskills.v1.md', contract(['contracts/../not-skills/off-list.txt']))),
                             ('two blocks', lambda: self.write('contracts/wizskills.v1.md', contract([]) + contract([])))):
            with self.subTest(name=name):
                fixture = CopyTests()
                fixture.setUp()
                try:
                    self.source, saved = fixture.source, self.source
                    change()
                    self.source = saved
                    fixture.commit()
                    fixture.log.write_text('')
                    p = fixture.run_copy('--destination', str(fixture.dest), '--publish', ok=False)
                    self.assertIn('carried contracts', p.stderr)
                    self.assertEqual(fixture.remote_head(), fixture.seed)
                finally:
                    fixture.doCleanups()

    def test_destination_is_openwizdev_wizskills(self):
        for remote in ('git@github.com:openwizdev/WizSkills.git', 'https://github.com/openwizdev/WizSkills.git'):
            with self.subTest(remote=remote):
                self.git(self.dest, 'remote', 'set-url', 'origin', remote)
                self.run_copy('--destination', str(self.dest))
        for remote in ('git@github.com:openwizdev/skills.git', 'https://github.com/openwizdev/skills.git',
                       'https://github.com/openwizdev/WizSkills-old.git'):
            with self.subTest(remote=remote):
                self.git(self.dest, 'remote', 'set-url', 'origin', remote)
                p = self.run_copy('--destination', str(self.dest), ok=False)
                self.assertIn('openwizdev/WizSkills', p.stderr)

    def test_dry_run_does_not_modify_destination(self):
        self.run_copy('--destination', str(self.dest))
        self.assertEqual(self.remote_head(), self.seed)
        self.assertEqual(self.git(self.dest, 'rev-parse', 'HEAD').stdout.strip(), self.seed)
        self.assertEqual(self.git(self.dest, 'status', '--porcelain').stdout, '')
        self.assertFalse(any('push' in json.loads(x) for x in self.log.read_text().splitlines()))
        self.assertNotIn('fetch', self.log.read_text())

    def test_publish_ordinary_parent_then_unchanged_is_noop(self):
        first = self.run_copy('--destination', str(self.dest), '--publish')
        head = self.remote_head()
        self.assertNotEqual(head, self.seed)
        self.assertEqual(self.git(self.bare, 'rev-list', '--parents', '-n', '1', head).stdout.strip(), head + ' ' + self.seed)
        self.assertEqual(json.loads(first.stdout)['published'], head)
        self.assertNotIn(self.git(self.source, 'rev-parse', 'HEAD').stdout.strip(),
                         self.git(self.bare, 'rev-list', 'main').stdout)
        self.assertNotIn('old.txt', self.git(self.bare, 'ls-tree', '-r', '--name-only', 'main').stdout)
        self.run_copy('--destination', str(self.dest), '--publish')
        self.assertEqual(self.remote_head(), head)
        pushes = [json.loads(x) for x in self.log.read_text().splitlines() if 'push' in json.loads(x)]
        self.assertEqual(len(pushes), 1)
        self.assertFalse(any(a.startswith('+') or 'force' in a for p in pushes for a in p))
        self.write('unrelated.txt', 'unrelated source change\n')
        self.commit()
        self.run_copy('--destination', str(self.dest), '--publish')
        self.assertEqual(self.remote_head(), head)

    def test_first_publish_to_empty_destination(self):
        empty_bare = self.root / 'empty.git'
        empty_dest = self.root / 'empty-clone'
        self.git(self.root, 'init', '--bare', '-q', '-b', 'main', str(empty_bare))
        self.git(self.root, 'clone', '-q', str(empty_bare), str(empty_dest))
        self.git(empty_dest, 'remote', 'set-url', 'origin', TARGET)
        p = self.run_copy('--destination', str(empty_dest), '--publish',
                          env=dict(self.env, COPY_REMOTE=str(empty_bare)))
        head = self.git(empty_bare, 'rev-parse', 'main').stdout.strip()
        self.assertEqual(json.loads(p.stdout)['published'], head)
        self.assertEqual(self.git(empty_bare, 'rev-list', '--parents', '-n', '1', head).stdout.strip(), head)
        self.assertEqual(self.git(empty_bare, 'ls-tree', '-r', '--name-only', head, 'private').stdout, '')

    def test_refuses_wrong_destination_and_dirty_clone(self):
        self.git(self.dest, 'remote', 'set-url', 'origin', 'https://example.invalid/wrong.git')
        self.run_copy('--destination', str(self.dest), '--publish', ok=False)
        self.git(self.dest, 'remote', 'set-url', 'origin', TARGET)
        (self.dest / 'untracked.txt').write_text('keep this\n')
        self.run_copy('--destination', str(self.dest), '--publish', ok=False)
        self.assertEqual((self.dest / 'untracked.txt').read_text(), 'keep this\n')
        self.assertEqual(self.remote_head(), self.seed)

    def test_failed_push_stops_without_retry(self):
        self.run_copy('--destination', str(self.dest), '--publish', ok=False,
                      env=dict(self.env, COPY_FAIL_PUSH='1'))
        self.assertEqual(self.remote_head(), self.seed)
        self.assertEqual(sum('push' in json.loads(x) for x in self.log.read_text().splitlines()), 1)



# WZ14 (#2891): run the candidate's own code in a tree holding only the
# candidate, recording every file it opens or lists outside that tree.
PROBE = r"""
import json, os, runpy, sys
root = os.path.realpath(sys.argv[1])
allowed = [root] + sorted({os.path.realpath(p) for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix)})
outside = set()
def hook(event, args):
    if event in ('open', 'os.listdir', 'os.scandir') and args and isinstance(args[0], (str, bytes, os.PathLike)):
        path = os.path.realpath(os.path.join(root, os.fsdecode(args[0])))
        if not any(path == a or path.startswith(a + os.sep) for a in allowed):
            outside.add(path)
sys.addaudithook(hook)
os.chdir(root)
sys.argv = [os.path.join(root, 'check', 'standalone.py'), '--tree', root]
code = 0
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as error:
    code = error.code
sys.stderr.write('PROBE ' + json.dumps({'code': code, 'outside': sorted(outside)}) + '\n')
"""
RULES = r"""
import runpy, sys
check = runpy.run_path(sys.argv[1])
findings = check['rules'](check['ROOT'])
for finding in findings:
    print('finding', finding)
sys.exit(0 if not findings and check['standalone'](check['ROOT']) else 1)
"""


class RealCopyTests(unittest.TestCase):
    """An integrated regression: the real copy of this checkout's HEAD commit,
    then the candidate's own check code, in a tree that holds nothing else."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='skills-copy-real-')
        cls.root = Path(cls.tmp.name)
        literals = cls.root / 'literals.txt'
        literals.write_text('synthetic-denied-machine\n')
        cls.output = cls.root / 'candidate'
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        cls.copy = subprocess.run([sys.executable, '-I', str(TOOL), '--source', str(REPO), '--commit', 'HEAD',
                                   '--version', VERSION, '--literals', str(literals), '--output', str(cls.output)],
                                  env=env, capture_output=True, text=True, timeout=300)
        text = subprocess.run(['git', '-C', str(REPO), 'show', 'HEAD:contracts/wizskills.v1.md'], env=env,
                              capture_output=True, text=True, check=True).stdout
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(HERE))
        import standalone
        cls.contract = standalone.contract_rules(text)
        cls.env = env

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.assertEqual(self.copy.returncode, 0, self.copy.stdout[-4000:] + self.copy.stderr)

    def isolated(self):
        # Only the candidate: nothing of ClosedWiz above or beside it.
        holder = Path(tempfile.mkdtemp(prefix='wizskills-only-'))
        self.addCleanup(shutil.rmtree, holder)
        tree = holder / 'wizskills'
        shutil.copytree(self.output, tree, symlinks=True)
        return tree

    def probe(self, tree):
        p = subprocess.run([sys.executable, '-I', '-c', PROBE, str(tree)], cwd=tree, env=self.env,
                           capture_output=True, text=True, timeout=300)
        line = [x for x in p.stderr.splitlines() if x.startswith('PROBE ')]
        self.assertEqual(len(line), 1, p.stdout + p.stderr)
        return json.loads(line[0][6:]), p.stdout

    def test_real_copy_emits_the_check_at_its_contract_paths(self):
        names = {p.relative_to(self.output).as_posix() for p in self.output.rglob('*')
                 if p.is_file() or p.is_symlink()}
        for path in self.contract['required_files']:
            self.assertTrue(path in names, path)
        self.assertTrue({'check/run.py', *GENERATED_CHECK} <= names, sorted(n for n in names if n.startswith('check/')))
        self.assertFalse((self.output / 'check/check').exists())
        for kept in ('test_check.py', 'red-run.txt'):
            self.assertEqual([n for n in names if n.split('/')[-1] == kept], [])
        self.assertEqual(sorted(n for n in names if n.startswith('check/')), sorted({'check/run.py', *GENERATED_CHECK}))
        self.assertIn('python3 check/run.py', (self.output / '.github/workflows/ci.yml').read_text())
        for path in self.contract['carried_contracts']:
            self.assertEqual((self.output / path).read_bytes(), subprocess.run(
                ['git', '-C', str(REPO), 'show', 'HEAD:' + path], env=self.env, capture_output=True, check=True).stdout)
        self.assertFalse((self.output / 'contracts/wizskills.v1.md').exists())
        values = json.loads((self.output / 'check/wizskills.v1.json').read_text(encoding='utf-8'))
        self.assertEqual(values, self.contract)
        result = json.loads(self.copy.stdout)
        self.assertEqual((result['privacy']['status'], result['standalone']['status']), ('pass', 'pass'))

    def test_candidate_rules_and_standalone_pass_in_a_wizskills_only_tree(self):
        tree = self.isolated()
        p = subprocess.run([sys.executable, '-I', '-c', RULES, str(tree / 'check/run.py')], cwd=tree, env=self.env,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn('standalone: pass', p.stdout)

    def test_scanner_reads_nothing_outside_the_wizskills_tree(self):
        tree = self.isolated()
        result, out = self.probe(tree)
        self.assertEqual(result, {'code': 0, 'outside': []}, out)
        self.assertEqual(out, '')

    def test_scanner_refuses_and_redacts_inside_the_wizskills_tree(self):
        tree = self.isolated()
        thread = 'thr' + '_abc123'
        (tree / f'skills/triage/{thread}.md').write_text('# Note\n[x](missing.md)\n')
        result, out = self.probe(tree)
        self.assertEqual(result, {'code': 1, 'outside': []}, out)
        self.assertEqual([json.loads(x) for x in out.splitlines()],
                         [{'rule': 'standalone.link', 'file': 'skills/triage/<thread>.md', 'line': 2}])
        self.assertNotIn(thread, out)

    def test_scanner_without_its_generated_values_or_redaction_refuses(self):
        for name in ('check/wizskills.v1.json', 'check/redact.py'):
            with self.subTest(missing=name):
                tree = self.isolated()
                (tree / name).unlink()
                result, out = self.probe(tree)
                self.assertEqual(result, {'code': 1, 'outside': []}, out)

    def test_generated_redaction_matches_the_privacy_check(self):
        def load(path, name):
            spec = importlib.util.spec_from_file_location(name, path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        packaged = load(self.output / 'check/redact.py', 'packaged_redact')
        privacy = load(REPO / 'tools/privacy-check/check.py', 'privacy_check_for_test')
        samples = ['skills/a/' + 'thr' + '_abc123/x.md', 'skills/a/' + 'proj' + '_ab12.md',
                   'skills/a/x' + '/home/' + 'someone2/x.md', 'skills/a/' + 'person' + '@corp.io.md',
                   'skills/a/' + 'snapshot.' + 'aB3xQ9' + '/state.json', 'skills/a/the PC has ' + '16' + ' cores.md',
                   'skills/a/synthetic-denied-machine.md', 'skills/a/' + DECIDER + ' said "x".md', 'skills/a/plain.md']
        for sample in samples:
            with self.subTest(sample=sample):
                expected = privacy.redact(sample, ['synthetic-denied-machine'])
                self.assertEqual(packaged.redact(sample, ['synthetic-denied-machine']), expected)
                if sample != 'skills/a/plain.md':
                    self.assertNotEqual(expected, sample)


if __name__ == '__main__':
    unittest.main()
