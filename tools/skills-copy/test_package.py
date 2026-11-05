#!/usr/bin/env python3
"""WZ-P5 installer proofs (#2631): package/install.sh against a local fake WizSkills.

Every repository, version, date and skill here is synthetic. The installer's one
remote, https://github.com/openwizdev/WizSkills.git, is redirected to a local
bare repository through Git's own url.<base>.insteadOf configuration, so the
real installer runs unchanged and nothing leaves the machine.
"""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
INSTALL = HERE / 'package' / 'install.sh'
REMOTE = 'https://github.com/openwizdev/WizSkills.git'
REAL_GIT = shutil.which('git')
SCHEMA = 'openwiz.wizskills.release.v1'
CONTRACT = HERE.parents[1] / 'contracts' / 'wizskills.v1.md'


def snapshot(root):
    """Every path under root (including .git) with its kind, mode and bytes."""
    result = {}
    if not (root.exists() or root.is_symlink()):
        return result
    for path in sorted([root, *root.rglob('*')]):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[rel] = ('link', os.readlink(path))
        elif path.is_dir():
            result[rel] = ('dir', path.stat().st_mode & 0o777)
        else:
            result[rel] = ('file', path.stat().st_mode & 0o777, path.read_bytes())
    return result


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wizskills-install-test-')
        self.addCleanup(self.tmp.cleanup)
        # Resolve: the installer refuses any symlink ancestor (macOS /tmp is one).
        self.root = Path(self.tmp.name).resolve()
        self.bare = self.root / 'fake-wizskills.git'
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.log = self.root / 'git.log'
        self.log.write_text('')
        wrapper = self.bin / 'git'
        wrapper.write_text('#!' + sys.executable + '\nimport os,sys,json\n'
                           'with open(os.environ["INSTALL_GIT_LOG"],"a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\n'
                           f'os.execv({REAL_GIT!r},[{REAL_GIT!r}]+sys.argv[1:])\n')
        wrapper.chmod(0o755)
        self.base_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        self.base_env.update(
            GIT_CONFIG_GLOBAL=str(self.root / 'gitconfig'), GIT_CONFIG_NOSYSTEM='1',
            GIT_TERMINAL_PROMPT='0', HOME=str(self.root / 'home'),
            GIT_AUTHOR_NAME='Synthetic', GIT_COMMITTER_NAME='Synthetic',
            GIT_AUTHOR_EMAIL='synthetic@users.noreply.github.com',
            GIT_COMMITTER_EMAIL='synthetic@users.noreply.github.com',
            GIT_AUTHOR_DATE='2030-01-02T00:00:00Z', GIT_COMMITTER_DATE='2030-01-02T00:00:00Z')
        (self.root / 'home').mkdir()
        # The installer's remote now reads the local fake, through Git's own config.
        self.env = dict(self.base_env, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        INSTALL_GIT_LOG=str(self.log), GIT_CONFIG_COUNT='1',
                        GIT_CONFIG_KEY_0='url.' + self.bare.as_uri() + '.insteadOf',
                        GIT_CONFIG_VALUE_0=REMOTE)
        self.git(self.root, 'init', '-q', '--bare', str(self.bare))
        self.work = self.root / 'release-work'
        self.git(self.root, 'init', '-q', '-b', 'main', str(self.work))
        self.parent = self.root / 'installs'
        self.parent.mkdir()
        self.dest = self.parent / 'wizskills'
        self.release = self.publish('0.1.0')

    def git(self, cwd, *args, env=None, check=True):
        return subprocess.run(['git', '-C', str(cwd), *args], env=env or self.base_env,
                              capture_output=True, text=True, check=check)

    def package_files(self, version, plugin=None, changelog=None):
        plugin_version = version if plugin is None else plugin
        changelog_version = version if changelog is None else changelog
        return {
            '.claude-plugin/plugin.json': json.dumps(
                {'name': 'openwiz', 'version': plugin_version, 'skills': ['./skills/alpha']}, indent=2) + '\n',
            '.claude-plugin/marketplace.json': json.dumps(
                {'name': 'wizskills', 'owner': {'name': 'Synthetic'},
                 'plugins': [{'name': 'openwiz', 'source': './'}]}, indent=2) + '\n',
            'CHANGELOG.md': f'# Changelog\n\n## {changelog_version} - 2030-01-02\n\n'
                            "- First public release of OpenWiz's skills.\n- `alpha`: first public release.\n",
            'README.md': '# Synthetic WizSkills\n',
            'LICENSE': 'Synthetic notices.\n',
            '.gitignore': 'ignored-*\n',
            'install.sh': INSTALL.read_bytes().decode(),
            'skills/alpha/SKILL.md': '---\nname: alpha\ndescription: Synthetic.\n---\n# Alpha\n',
            'skills/alpha/scripts/run.sh': '#!/bin/sh\nexit 0\n',
        }

    def publish(self, version, *, record=None, files=None, lightweight=False, raw_message=None, links=None):
        """Commit a synthetic release on the fake's main and tag v<version>."""
        for path in self.work.iterdir():
            if path.name != '.git':
                shutil.rmtree(path) if path.is_dir() else path.unlink()
        for name, data in (files or self.package_files(version)).items():
            path = self.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(data)
        for name in ('install.sh', 'skills/alpha/scripts/run.sh'):
            (self.work / name).chmod(0o755)
        for name, target in (links or {}).items():
            (self.work / name).symlink_to(target)
        self.git(self.work, 'add', '-A')
        self.git(self.work, 'commit', '-q', '--allow-empty', '-m', 'Synthetic release ' + version)
        commit = self.git(self.work, 'rev-parse', 'HEAD').stdout.strip()
        tree = self.git(self.work, 'rev-parse', 'HEAD^{tree}').stdout.strip()
        value = {'schema': SCHEMA, 'version': version, 'commit': commit, 'tree': tree}
        if record is not None:
            value = record(dict(value))
        tag = 'v' + version
        if lightweight:
            self.git(self.work, 'tag', tag, commit)
        else:
            message = raw_message(value) if raw_message else json.dumps(value) + '\n'
            path = self.root / 'tag-message'
            path.write_text(message)
            self.git(self.work, 'tag', '-a', '--cleanup=verbatim', '-F', str(path), tag, commit)
        self.git(self.work, 'push', '-q', str(self.bare), 'main', tag)
        return {'commit': commit, 'tree': tree, 'tag': tag}

    def install(self, *args, code=0, env=None):
        args = args or ('--version', '0.1.0', '--dest', str(self.dest))
        self.log.write_text('')
        p = subprocess.run(['sh', str(INSTALL), *args], env=env or self.env, cwd=self.root,
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        if code:
            self.assertRegex(p.stderr, r'^install\.sh: refused: [A-Za-z .,;/-]+\n\Z')
        return p

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def remote_calls(self):
        return [c for c in self.calls() if any(op in c for op in ('fetch', 'clone', 'ls-remote', 'pull', 'push'))]

    def assert_refused_unchanged(self, *args, code=1, before=None):
        before = snapshot(self.parent) if before is None else before
        self.install(*args, code=code)
        self.assertEqual(snapshot(self.parent), before)



class InstallTests(Fixture):
    # Criterion 3: installs a local fake tagged repository.
    def test_installs_the_tagged_release_as_a_detached_checkout(self):
        before = set(os.listdir(self.parent))
        self.install()
        self.assertEqual(set(os.listdir(self.parent)), before | {'wizskills'})
        self.assertEqual(self.git(self.dest, 'rev-parse', 'HEAD').stdout.strip(), self.release['commit'])
        self.assertEqual(self.git(self.dest, 'rev-parse', 'HEAD^{tree}').stdout.strip(), self.release['tree'])
        self.assertEqual(self.git(self.dest, 'symbolic-ref', '-q', 'HEAD', check=False).returncode, 1)
        files = {p.relative_to(self.dest).as_posix() for p in self.dest.rglob('*')
                 if p.is_file() and '.git' not in p.relative_to(self.dest).parts}
        self.assertEqual(files, set(self.package_files('0.1.0')))
        for name, data in self.package_files('0.1.0').items():
            self.assertEqual((self.dest / name).read_text(), data)
        self.assertEqual((self.dest / 'skills/alpha/scripts/run.sh').stat().st_mode & 0o111, 0o111)
        self.assertEqual((self.dest / 'README.md').stat().st_mode & 0o111, 0)
        self.assertEqual(self.git(self.dest, 'status', '--porcelain', '--ignored').stdout, '')
        # Exactly one remote read: the explicit tag, from the one fixed URL, no force.
        self.assertEqual(len(self.remote_calls()), 1, self.calls())
        fetch = self.remote_calls()[0]
        self.assertIn('fetch', fetch)
        self.assertIn(REMOTE, fetch)
        self.assertIn('refs/tags/v0.1.0:refs/tags/v0.1.0', fetch)
        self.assertFalse(any(a.startswith('+') or a in ('-f', '--force') for a in fetch))
        # The caller's Git configuration is untouched.
        self.assertFalse((self.root / 'gitconfig').exists())

    def test_matching_install_is_a_noop(self):
        self.install()
        before = snapshot(self.parent)
        self.install()
        self.assertEqual(snapshot(self.parent), before)

    def test_relative_destination_resolves_from_the_working_directory(self):
        self.install('--version', '0.1.0', '--dest', 'installs/wizskills')
        self.assertEqual(self.git(self.dest, 'rev-parse', 'HEAD').stdout.strip(), self.release['commit'])

    # Criterion 3: refuses a tree mismatch and writes nothing.
    def test_refuses_a_mismatched_or_malformed_release_record(self):
        other_tree = '4b825dc642cb6eb9a060e54bf8d69288fbee4904'
        other_commit = 'a' * 40
        cases = {
            'tree': lambda r: dict(r, tree=other_tree),
            'commit': lambda r: dict(r, commit=other_commit),
            'version': lambda r: dict(r, version='0.1.1'),
            'schema': lambda r: dict(r, schema='openwiz.wizskills.release.v2'),
            'unknown key': lambda r: dict(r, extra='x'),
            'missing key': lambda r: {k: v for k, v in r.items() if k != 'tree'},
            'short id': lambda r: dict(r, tree=r['tree'][:12]),
            'upper id': lambda r: dict(r, tree=r['tree'].upper()),
            'number': lambda r: dict(r, version=1),
        }
        raw = {
            'duplicate key': lambda r: json.dumps(r)[:-1] + ', "tree": "' + r['tree'] + '"}',
            'not json': lambda r: 'release ' + r['version'],
            'array': lambda r: json.dumps([r]),
            'trailing text': lambda r: json.dumps(r) + '\nsigned-off',
            'escaped value': lambda r: json.dumps(r).replace('"%s"' % r['version'], '"%s\\u%04x"' % (r['version'][:-1], ord(r['version'][-1]))),
            'space in value': lambda r: json.dumps(dict(r, version=r['version'] + ' ')),
        }
        for index, name in enumerate([*cases, *raw]):
            with self.subTest(record=name):
                version = '0.2.' + str(index)
                if name in cases:
                    self.publish(version, record=cases[name])
                else:
                    self.publish(version, raw_message=raw[name])
                self.assert_refused_unchanged('--version', version, '--dest', str(self.dest))
                self.assertFalse(self.dest.exists())

    def test_accepts_a_formatted_record_in_any_key_order(self):
        release = self.publish('0.3.0', raw_message=lambda r: '{\n  "tree": "%s",\n  "commit": "%s",\n'
                               '  "version": "0.3.0",\n  "schema": "%s"\n}\n' % (r['tree'], r['commit'], SCHEMA))
        self.install('--version', '0.3.0', '--dest', str(self.dest))
        self.assertEqual(self.git(self.dest, 'rev-parse', 'HEAD').stdout.strip(), release['commit'])

    def test_refuses_a_lightweight_tag(self):
        self.publish('0.4.0', lightweight=True)
        self.assert_refused_unchanged('--version', '0.4.0', '--dest', str(self.dest))

    def test_refuses_manifest_or_changelog_disagreeing_with_the_version(self):
        for name, files in (('plugin', self.package_files('0.5.0', plugin='0.5.1')),
                            ('changelog', self.package_files('0.5.0', changelog='0.5.1'))):
            with self.subTest(file=name):
                self.git(self.work, 'tag', '-d', 'v0.5.0', check=False)
                self.git(self.bare, 'tag', '-d', 'v0.5.0', check=False)
                self.publish('0.5.0', files=files)
                self.assert_refused_unchanged('--version', '0.5.0', '--dest', str(self.dest))

    def test_missing_tag_is_a_fetch_failure_and_writes_nothing(self):
        self.assert_refused_unchanged('--version', '0.9.0', '--dest', str(self.dest), code=3)
        self.assertEqual(len(self.remote_calls()), 1)

    # Criterion 3: refuses a dirty destination and writes nothing.
    def test_refuses_a_dirty_destination_unchanged(self):
        def modified(d): (d / 'README.md').write_text('changed\n')
        def untracked(d): (d / 'extra.txt').write_text('extra\n')
        def ignored(d): (d / 'ignored-file').write_text('ignored\n')
        def deleted(d): (d / 'LICENSE').unlink()
        def mode(d): (d / 'README.md').chmod(0o755)
        def staged(d):
            (d / 'README.md').write_text('staged\n')
            self.git(d, 'add', 'README.md')
            (d / 'README.md').write_text('# Synthetic WizSkills\n')
        def moved_head(d):
            self.git(d, 'commit', '-q', '--allow-empty', '-m', 'local')
        for name, dirty in (('modified', modified), ('untracked', untracked), ('ignored', ignored),
                            ('deleted', deleted), ('mode', mode), ('staged', staged),
                            ('moved head', moved_head)):
            with self.subTest(dirty=name):
                if self.dest.exists():
                    shutil.rmtree(self.dest)
                self.install()
                dirty(self.dest)
                self.assert_refused_unchanged()

    # R1 (#2704): Git's attributes and filters must never certify changed bytes.
    def test_caller_attributes_never_rewrite_installed_bytes(self):
        attributes = self.root / 'attributes'
        attributes.write_text('*.sh text eol=crlf\n')
        env = dict(self.env, GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_1='core.attributesFile',
                   GIT_CONFIG_VALUE_1=str(attributes))
        self.install(env=env)
        script = self.dest / 'skills/alpha/scripts/run.sh'
        self.assertEqual(script.read_bytes(), b'#!/bin/sh\nexit 0\n')
        self.assertEqual(subprocess.run([str(script)]).returncode, 0)
        self.install(env=env)  # verification of the raw bytes: still a no-op

    def test_release_attributes_that_transform_checkout_are_refused(self):
        files = self.package_files('0.7.0')
        files['.gitattributes'] = '*.sh text eol=crlf\n'
        self.publish('0.7.0', files=files)
        self.assert_refused_unchanged('--version', '0.7.0', '--dest', str(self.dest))

    def test_a_clean_filter_cannot_hide_a_changed_script(self):
        self.install()
        original = self.root / 'original.sh'
        original.write_text('#!/bin/sh\nexit 0\n')
        (self.dest / '.git/info').mkdir(exist_ok=True)
        (self.dest / '.git/info/attributes').write_text('*.sh filter=hide\n')
        script = self.dest / 'skills/alpha/scripts/run.sh'
        script.write_text('#!/bin/sh\necho changed-script\nexit 7\n')
        env = dict(self.env, GIT_CONFIG_COUNT='3', GIT_CONFIG_KEY_1='filter.hide.clean',
                   GIT_CONFIG_VALUE_1='cat ' + str(original), GIT_CONFIG_KEY_2='filter.hide.required',
                   GIT_CONFIG_VALUE_2='true')
        before = snapshot(self.parent)
        self.install(env=env, code=1)
        self.assertEqual(snapshot(self.parent), before)

    def test_refuses_nested_git_entries_and_extra_empty_directories(self):
        for name, make in (('nested .git file', lambda d: (d / 'skills/alpha/.git').write_text('gitdir: x\n')),
                           ('nested .git dir', lambda d: (d / 'skills/alpha/.git').mkdir()),
                           ('empty dir', lambda d: (d / 'skills/alpha/empty').mkdir())):
            with self.subTest(case=name):
                if self.dest.exists():
                    shutil.rmtree(self.dest)
                self.install()
                make(self.dest)
                self.assert_refused_unchanged()

    # R1 re-check (#2704): a quoted-looking name is a different path, not the release file.
    def test_a_quoted_filename_cannot_stand_in_for_a_release_file(self):
        self.install()
        (self.dest / 'README.md').rename(self.dest / '"README.md"')
        self.assert_refused_unchanged()

    # R1 re-check (#2704): a link target's trailing newline is part of its bytes.
    def test_a_link_target_with_a_trailing_newline_is_a_different_link(self):
        self.publish('0.8.0', links={'skills/alpha/latest': 'scripts/run.sh'})
        self.install('--version', '0.8.0', '--dest', str(self.dest))
        link = self.dest / 'skills/alpha/latest'
        link.unlink()
        link.symlink_to('scripts/run.sh\n')
        self.assert_refused_unchanged('--version', '0.8.0', '--dest', str(self.dest))

    def test_refuses_a_foreign_or_mismatched_destination_unchanged(self):
        self.dest.mkdir()
        self.assert_refused_unchanged()  # empty directory
        (self.dest / 'notes.txt').write_text('keep\n')
        self.assert_refused_unchanged()  # not an installation
        shutil.rmtree(self.dest)
        self.publish('0.6.0')
        self.install('--version', '0.6.0', '--dest', str(self.dest))
        self.assert_refused_unchanged()  # another version's installation
        shutil.rmtree(self.dest)
        self.dest.write_text('a file\n')
        self.assert_refused_unchanged()  # non-directory collision

    def test_refuses_symlink_destination_or_ancestor(self):
        real = self.root / 'real'
        real.mkdir()
        (self.parent / 'link').symlink_to(real)
        self.assert_refused_unchanged('--version', '0.1.0', '--dest', str(self.parent / 'link'))
        self.assert_refused_unchanged('--version', '0.1.0', '--dest', str(self.parent / 'link' / 'wizskills'))
        self.assertEqual(list(real.iterdir()), [])

    def test_refuses_a_missing_parent_without_creating_it(self):
        self.assert_refused_unchanged('--version', '0.1.0', '--dest', str(self.parent / 'missing' / 'wizskills'))
        self.assertFalse((self.parent / 'missing').exists())

    def test_argument_errors_exit_2_before_any_git_call(self):
        dest = str(self.dest)
        for args in ((), ('--version', '0.1.0'), ('--dest', dest),
                     ('--version', '0.1.0', '--version', '0.1.0', '--dest', dest),
                     ('--version', '0.1.0', '--dest', dest, '--dest', dest),
                     ('--version', '0.1.0', '--dest', dest, '--force'),
                     ('--version', '0.1.0', '--dest', dest, 'extra'),
                     ('--version', 'v0.1.0', '--dest', dest),
                     ('--version', 'latest', '--dest', dest),
                     ('--version', 'main', '--dest', dest),
                     ('--version', '0.01.0', '--dest', dest),
                     ('--version', '0.0.1', '--dest', dest),
                     ('--version', '0.1.0\n0.1.0', '--dest', dest),
                     ('--version', '', '--dest', dest),
                     ('--version', '0.1.0', '--dest', ''),
                     ('--version',)):
            with self.subTest(args=args):
                before = snapshot(self.parent)
                p = subprocess.run(['sh', str(INSTALL), *args], env=self.env, cwd=self.root,
                                   capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
                self.assertEqual(snapshot(self.parent), before)
                self.assertEqual(self.log.read_text(), '')

    def test_valid_semver_forms_are_accepted(self):
        for version in ('0.10.0', '1.0.0', '0.1.0-rc.1', '0.1.0+build.7'):
            with self.subTest(version=version):
                dest = self.parent / ('v' + version)
                self.publish(version)
                self.install('--version', version, '--dest', str(dest))

    def test_diagnostics_never_echo_the_destination_or_upstream_text(self):
        self.dest.mkdir()
        (self.dest / 'secret-name.txt').write_text('x\n')
        p = self.install(code=1)
        self.assertNotIn(str(self.root), p.stderr)
        self.assertNotIn('secret-name', p.stderr)


class ReadmeTests(Fixture):
    """Criterion 4: the README's installs are the contract's, and its commands work."""

    def readme(self):
        return (HERE / 'package' / 'README.md').read_text().replace('{{version}}', '0.1.0')

    def blocks(self):
        blocks = re.findall(r'^```sh\n(.*?)^```$', self.readme(), re.S | re.M)
        kinds = {}
        for block in blocks:
            kind = ('claude' if 'claude plugin' in block else 'source' if 'git clone' in block
                    else 'codex' if '.agents/skills' in block else 'install' if 'install.sh' in block
                    else 'other')
            self.assertNotIn(kind, kinds)
            kinds[kind] = block
        self.assertEqual(set(kinds), {'claude', 'source', 'install', 'codex', 'other'})
        return kinds

    def sh(self, block, cwd, code=0):
        p = subprocess.run(['sh', '-c', block], env=self.env, cwd=cwd, capture_output=True,
                           text=True, timeout=60)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p.stdout

    def test_claude_code_commands_are_the_contracts(self):
        section = CONTRACT.read_text().split("## README's three installs")[1].split('\n## ')[0]
        commands = [c for c in re.findall(r'`([^`]+)`', section) if c.startswith('claude plugin')]
        self.assertEqual(len(commands), 3)
        readme = self.readme()
        for command in commands:
            self.assertIn(command, readme)
        pinned = [c for c in commands if '#v' in c]
        self.assertEqual(self.blocks()['claude'].split('\n')[:2], pinned + ['claude plugin install openwiz@wizskills --scope project'])
        self.assertIn('install.sh --version <version> --dest <dir>', readme)

    def test_installer_source_install_codex_and_other_agent_blocks_run(self):
        blocks = self.blocks()
        project = self.root / 'project'
        project.mkdir()
        out = self.sh(blocks['source'], project).split('\n')
        record = json.loads(next(line for line in out if line.startswith('{')))
        self.assertEqual(record, {'schema': SCHEMA, 'version': '0.1.0', 'commit': self.release['commit'],
                                  'tree': self.release['tree']})
        self.assertIn(self.release['commit'] + '\n' + self.release['tree'] + '\n', '\n'.join(out))
        self.assertEqual(out[-1], '')  # status --porcelain --ignored printed nothing
        self.assertIn('--version 0.1.0', blocks['install'])
        self.sh(blocks['install'], project)
        installed = self.root / 'home' / 'wizskills'
        self.assertEqual(self.git(installed, 'rev-parse', 'HEAD').stdout.strip(), self.release['commit'])
        self.sh(blocks['install'], project)  # a repeat is a no-op
        self.sh(blocks['codex'], project)
        link = project / '.agents/skills/alpha'
        self.assertEqual(os.readlink(link), str(installed / 'skills/alpha'))
        self.assertTrue((link / 'scripts/run.sh').is_file())
        self.sh(blocks['codex'], project)  # existing matching links are kept
        link.unlink()
        link.symlink_to(self.root)
        self.sh(blocks['codex'], project, code=1)  # a conflicting link is refused, not replaced
        self.assertEqual(os.readlink(link), str(self.root))
        self.assertEqual(self.sh(blocks['other'].replace('build-ticket', 'alpha'), project), 'ok\n')


if __name__ == '__main__':
    unittest.main()
