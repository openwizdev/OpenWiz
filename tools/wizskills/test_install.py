#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
INSTALL = HERE / 'install.py'
CHECK = HERE / 'check_contracts.py'
URL = 'https://github.com/openwizdev/WizSkills.git'


def contract_carried():
    text = (ROOT / 'contracts/wizskills.v1.md').read_text(encoding='utf-8')
    block = text.split('```wizskills-v1\n', 1)[1].split('```', 1)[0]
    return json.loads(block)['carried_contracts']


CARRIED = contract_carried()

FAKE_INSTALLER = r'''#!/bin/sh
set -eu
version= dest=
while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ -z "$version" ] && [ $# -ge 2 ] || exit 2; version=$2; shift 2 ;;
    --dest) [ -z "$dest" ] && [ $# -ge 2 ] || exit 2; dest=$2; shift 2 ;;
    *) exit 2 ;;
  esac
done
[ -n "$version" ] && [ -n "$dest" ] || exit 2
[ -e "$dest" ] || [ -L "$dest" ] && { echo 'install.sh: destination exists' >&2; exit 1; }
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
BEFORE_FETCH
git init -q "$work/w" || exit 3
git -C "$work/w" fetch -q --no-tags https://github.com/openwizdev/WizSkills.git \
  "refs/tags/v$version:refs/tags/v$version" || exit 3
git -C "$work/w" -c advice.detachedHead=false checkout -q "v$version^{commit}" || exit 3
EXTRA
mv "$work/w" "$dest" || exit 3
'''


def git(*args, cwd=None, env=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, env=env, check=check,
                          capture_output=True, text=True).stdout.strip()


def snapshot(path):
    path = Path(path)
    if not os.path.lexists(path):
        return None
    found = {}
    for here, dirs, files in os.walk(path):
        for name in dirs + files:
            p = Path(here, name)
            st = p.lstat()
            if p.is_symlink():
                found[str(p.relative_to(path))] = ('link', os.readlink(p))
            elif p.is_dir():
                found[str(p.relative_to(path))] = ('dir', st.st_mode)
            else:
                found[str(p.relative_to(path))] = (
                    'file', st.st_mode, st.st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest())
    return found


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='wizskills-test-')).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / 'home'
        self.home.mkdir()
        self.env = {
            'PATH': os.environ.get('PATH', '/usr/bin:/bin'),
            'HOME': str(self.home),
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_AUTHOR_NAME': 'Synthetic', 'GIT_AUTHOR_EMAIL': 'synthetic@example.invalid',
            'GIT_COMMITTER_NAME': 'Synthetic', 'GIT_COMMITTER_EMAIL': 'synthetic@example.invalid',
            'GIT_ALLOW_PROTOCOL': 'file',
            'LC_ALL': 'C',
        }
        self.root = self.tmp / 'closedwiz'
        for rel in ['contracts/wizskills.v1.md', *CARRIED]:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, self.root / rel)
        self.dest = self.root / '.wizskills'
        self.remote = self.tmp / 'WizSkills.git'
        git('init', '-q', '--bare', str(self.remote), env=self.env)
        self.redirect(self.remote)

    def redirect(self, target):
        self.env.update({'GIT_CONFIG_COUNT': '1',
                         'GIT_CONFIG_KEY_0': f'url.{target}.insteadOf',
                         'GIT_CONFIG_VALUE_0': URL})

    def release(self, version, extra_files=None, installer_extra=':',
                record=None, annotated=True, mode=0o755, before_fetch=':'):
        work = self.tmp / f'src-{version}'
        if work.exists():
            shutil.rmtree(work)
        git('init', '-q', str(work), env=self.env)
        files = {
            'README.md': f'Synthetic WizSkills {version}\n',
            'CHANGELOG.md': f'# Changelog\n\n## {version} - 2030-01-02\n\n- Synthetic.\n',
            '.claude-plugin/plugin.json': json.dumps({'name': 'openwiz', 'version': version,
                                                      'skills': ['./skills/alpha']}) + '\n',
            'skills/alpha/SKILL.md': '---\nname: alpha\ndescription: Synthetic.\n---\n',
            'skills/alpha/scripts/run.sh': '#!/bin/sh\necho alpha\n',
        }
        for rel in CARRIED:
            files[rel] = (ROOT / rel).read_text()
        files.update(extra_files or {})
        for rel, text in files.items():
            (work / rel).parent.mkdir(parents=True, exist_ok=True)
            (work / rel).write_text(text)
        (work / 'skills/alpha/scripts/run.sh').chmod(0o755)
        (work / 'install.sh').write_text(FAKE_INSTALLER.replace('EXTRA', installer_extra).replace('BEFORE_FETCH', before_fetch))
        (work / 'install.sh').chmod(mode)
        git('add', '-A', cwd=work, env=self.env)
        git('commit', '-q', '-m', f'release {version}', cwd=work, env=self.env)
        commit = git('rev-parse', 'HEAD', cwd=work, env=self.env)
        tree = git('rev-parse', 'HEAD^{tree}', cwd=work, env=self.env)
        body = record if record is not None else {
            'schema': 'openwiz.wizskills.release.v1', 'version': version,
            'commit': commit, 'tree': tree}
        if annotated:
            git('tag', '-a', f'v{version}', '-m', json.dumps(body), cwd=work, env=self.env)
        else:
            git('tag', f'v{version}', cwd=work, env=self.env)
        git('push', '-q', str(self.remote), f'refs/tags/v{version}', 'HEAD:refs/heads/main',
            '--force', cwd=work, env=self.env)
        return {'version': version, 'commit': commit, 'tree': tree}

    def use_global(self, config, where):
        home_config = self.home / '.gitconfig'
        home_config.unlink(missing_ok=True)
        if where is None:
            self.env.pop('GIT_CONFIG_GLOBAL', None)
            shutil.copyfile(config, home_config)
        else:
            self.env['GIT_CONFIG_GLOBAL'] = where

    def lock(self, value):
        text = value if isinstance(value, str) else json.dumps(value) + '\n'
        (self.root / 'wizskills.lock').write_text(text)

    def run_tool(self, tool):
        return subprocess.run(['python3', '-I', str(tool), '--root', str(self.root)],
                              env=self.env, capture_output=True, text=True, timeout=120)

    def install(self):
        return self.run_tool(INSTALL)

    def installed(self, pin):
        self.lock(pin)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def refused(self, code, reason, before=None):
        before = snapshot(self.dest) if before is None else before
        lock_before = snapshot(self.root)
        result = self.install()
        self.assertEqual(result.returncode, code, result.stderr)
        self.assertIn(reason, result.stderr)
        self.assertEqual(snapshot(self.dest), before)
        self.assertEqual(snapshot(self.root), lock_before)
        return result


class Install(Fixture):
    def test_missing_install_is_the_pinned_release_tree(self):
        pin = self.release('0.1.0')
        self.release('0.2.0', {'skills/alpha/SKILL.md': 'newer\n'})
        self.installed(pin)
        self.assertEqual(git('-C', str(self.dest), 'rev-parse', 'HEAD', env=self.env), pin['commit'])
        self.assertEqual(git('-C', str(self.dest), 'rev-parse', 'HEAD^{tree}', env=self.env), pin['tree'])
        self.assertEqual((self.dest / 'skills/alpha/SKILL.md').read_text(),
                         '---\nname: alpha\ndescription: Synthetic.\n---\n')
        self.assertTrue(os.access(self.dest / 'skills/alpha/scripts/run.sh', os.X_OK))

    def test_current_install_is_a_no_op_without_any_fetch(self):
        pin = self.release('0.1.0')
        self.installed(pin)
        before = snapshot(self.dest)
        self.redirect(self.tmp / 'nowhere.git')
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(snapshot(self.dest), before)

    def test_dirty_install_is_refused_unchanged(self):
        pin = self.release('0.1.0', {'.gitignore': '*.log\n'})
        cases = {
            'modified': lambda d: (d / 'README.md').write_text('changed\n'),
            'one byte': lambda d: (d / 'README.md').write_bytes(
                (d / 'README.md').read_bytes()[:-1] + b'!'),
            'deleted': lambda d: (d / 'skills/alpha/SKILL.md').unlink(),
            'untracked': lambda d: (d / 'skills/alpha/extra.md').write_text('x\n'),
            'ignored by the release': lambda d: (d / 'notes.log').write_text('x\n'),
            'ignored locally': lambda d: ((d / '.git/info/exclude').write_text('*.txt\n'),
                                          (d / 'notes.txt').write_text('x\n')),
            'empty directory': lambda d: (d / 'skills/beta').mkdir(),
            'mode': lambda d: (d / 'skills/alpha/scripts/run.sh').chmod(0o644),
            'staged removal': lambda d: git('-C', str(d), 'rm', '-q', '--cached',
                                            'README.md', env=self.env),
            'moved HEAD': lambda d: git('-C', str(d), 'commit', '-q', '--allow-empty',
                                        '-m', 'local', env=self.env),
            'nested repository': lambda d: git('init', '-q', str(d / 'skills/alpha/inner'),
                                               env=self.env),
        }
        for name, spoil in cases.items():
            with self.subTest(name):
                if os.path.lexists(self.dest):
                    shutil.rmtree(self.dest)
                self.installed(pin)
                spoil(self.dest)
                self.refused(1, 'wizskills: refused:')

    def test_crlf_script_is_refused_whatever_the_attributes(self):
        global_attrs = self.tmp / 'attributes'
        global_attrs.write_text('*.sh text\n')
        global_config = self.tmp / 'gitconfig'
        global_config.write_text(f'[core]\n\tattributesFile = {global_attrs}\n')
        cases = {
            'caller attributes, GIT_CONFIG_GLOBAL': ({}, str(global_config)),
            'caller attributes, ~/.gitconfig': ({}, None),
            'release attributes': ({'.gitattributes': '*.sh text\n'}, os.devnull),
        }
        for name, (extra, where) in cases.items():
            with self.subTest(name):
                if os.path.lexists(self.dest):
                    shutil.rmtree(self.dest)
                self.installed(self.release('0.1.0', extra))
                self.use_global(global_config, where)
                script = self.dest / 'skills/alpha/scripts/run.sh'
                script.write_bytes(script.read_bytes().replace(b'\n', b'\r\n'))
                self.refused(1, 'does not match the lock')
                self.use_global(global_config, os.devnull)

    def test_other_version_installed_is_refused_not_replaced(self):
        old = self.release('0.1.0')
        self.installed(old)
        new = self.release('0.2.0', {'skills/alpha/SKILL.md': 'newer\n'})
        self.lock(new)
        self.refused(1, 'does not match the lock')
        self.assertEqual(git('-C', str(self.dest), 'rev-parse', 'HEAD', env=self.env), old['commit'])

    def test_foreign_destinations_are_refused_unchanged(self):
        pin = self.release('0.1.0')
        self.lock(pin)
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.mkdir()
        cases = {
            'empty directory': lambda: self.dest.mkdir(),
            'file': lambda: self.dest.write_text('x\n'),
            'symlink to a directory': lambda: self.dest.symlink_to(elsewhere),
            'dangling symlink': lambda: self.dest.symlink_to(self.tmp / 'missing'),
            'plain files': lambda: (self.dest.mkdir(), (self.dest / 'README.md').write_text('x\n')),
        }
        for name, make in cases.items():
            with self.subTest(name):
                if self.dest.is_symlink() or self.dest.is_file():
                    self.dest.unlink()
                elif self.dest.exists():
                    shutil.rmtree(self.dest)
                make()
                self.refused(1, 'wizskills: refused:')

    def test_lock_that_disagrees_with_the_release_installs_nothing(self):
        pin = self.release('0.1.0')
        other = self.release('0.3.0')
        cases = {
            'tree': dict(pin, tree=other['tree']),
            'commit': dict(pin, commit=other['commit']),
            'version of another release': dict(other, version='0.1.0'),
        }
        for name, lock in cases.items():
            with self.subTest(name):
                self.lock(lock)
                self.refused(1, 'wizskills: refused:')

    def test_bad_release_records_install_nothing(self):
        base = self.release('0.1.0')
        cases = {
            'lightweight tag': dict(annotated=False),
            'extra key': dict(record=dict(base, schema='openwiz.wizskills.release.v1', extra='x')),
            'wrong schema': dict(record=dict(base, schema='openwiz.wizskills.release.v0')),
            'not json': dict(record='synthetic release'),
            'record names another tree': dict(record=dict(
                base, schema='openwiz.wizskills.release.v1', tree='0' * 40)),
        }
        for name, kwargs in cases.items():
            with self.subTest(name):
                pin = self.release('0.1.0', **kwargs)
                if name == 'record names another tree':
                    pin = dict(pin, tree='0' * 40)
                self.lock(pin)
                self.refused(1, 'wizskills: refused:')

    def test_tag_whose_target_is_not_its_record_installs_nothing(self):
        pin = self.release('0.1.0')
        work = self.tmp / 'src-0.1.0'
        git('commit', '-q', '--allow-empty', '-m', 'child', cwd=work, env=self.env)
        record = dict(pin, schema='openwiz.wizskills.release.v1', version='0.1.1')
        git('tag', '-a', 'v0.1.1', '-m', json.dumps(record), cwd=work, env=self.env)
        git('push', '-q', str(self.remote), 'refs/tags/v0.1.1', cwd=work, env=self.env)
        self.lock(dict(pin, version='0.1.1'))
        self.refused(1, 'no valid release record')

    def test_installer_that_publishes_another_tree_is_reported(self):
        pin = self.release('0.1.0', installer_extra='echo x > "$work/w/stray.txt"')
        self.lock(pin)
        result = self.install()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('does not match the lock', result.stderr)

    def test_release_installer_reads_only_the_verified_copy(self):
        other = self.release('0.3.0', {'skills/alpha/SKILL.md': 'other\n'})
        global_config = self.tmp / 'gitconfig'
        global_config.write_text(f'[url "{self.remote}"]\n\tinsteadOf = {URL}\n')
        move = (f"git -C '{self.remote}' tag -f -a v0.1.0 -m moved {other['commit']} "
                ">/dev/null 2>&1")
        for name, where in {'GIT_CONFIG_GLOBAL': str(global_config),
                            '~/.gitconfig': None}.items():
            with self.subTest(name):
                if os.path.lexists(self.dest):
                    shutil.rmtree(self.dest)
                pin = self.release('0.1.0', before_fetch=move)
                self.lock(pin)
                self.env.pop('GIT_CONFIG_COUNT', None)
                self.use_global(global_config, where)
                result = self.install()
                self.use_global(global_config, os.devnull)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(git('-C', str(self.dest), 'rev-parse', 'HEAD', env=self.env),
                                 pin['commit'])
                self.assertNotEqual(git('--git-dir', str(self.remote), 'rev-parse',
                                        'v0.1.0^{commit}', env=self.env),
                                    pin['commit'])

    def test_installer_refusal_is_passed_on(self):
        pin = self.release('0.1.0', installer_extra='exit 1')
        self.lock(pin)
        self.refused(1, 'release installer refused')

    def test_malformed_lock_is_refused_before_any_fetch(self):
        pin = self.release('0.1.0')
        cases = {
            'missing': None,
            'not json': '{',
            'duplicate key': '{"version":"0.1.0","version":"0.1.0","commit":"%s","tree":"%s"}'
                             % (pin['commit'], pin['tree']),
            'extra key': dict(pin, schema='x'),
            'missing key': {'version': pin['version'], 'commit': pin['commit']},
            'leading v': dict(pin, version='v0.1.0'),
            'abbreviated commit': dict(pin, commit=pin['commit'][:12]),
            'uppercase tree': dict(pin, tree=pin['tree'].upper()),
            'number': dict(pin, version=1),
        }
        self.redirect(self.tmp / 'nowhere.git')
        for name, lock in cases.items():
            with self.subTest(name):
                if lock is None:
                    (self.root / 'wizskills.lock').unlink(missing_ok=True)
                else:
                    self.lock(lock)
                self.refused(2, 'wizskills: invalid lock')

    def test_missing_tag_is_a_fetch_failure(self):
        pin = self.release('0.1.0')
        self.lock(dict(pin, version='0.9.0'))
        self.refused(3, 'wizskills: fetch failed')

    def test_only_the_file_transport_is_used(self):
        pin = self.release('0.1.0')
        self.lock(pin)
        del self.env['GIT_CONFIG_COUNT']
        self.refused(3, 'wizskills: fetch failed')


class ContractCopies(Fixture):
    def check(self):
        return self.run_tool(CHECK)

    def test_identical_copies_pass(self):
        self.installed(self.release('0.1.0'))
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_byte_difference_fails_naming_the_file(self):
        for rel in CARRIED:
            with self.subTest(rel):
                if self.dest.exists():
                    shutil.rmtree(self.dest)
                text = (ROOT / rel).read_bytes()
                changed = text[:-1] + (b'?' if text[-1:] != b'?' else b'!')
                self.installed(self.release('0.1.0', {rel: changed.decode()}))
                result = self.check()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(rel, result.stderr)
                for other in CARRIED:
                    if other != rel:
                        self.assertNotIn(other, result.stderr)

    def test_missing_installed_copy_fails_naming_the_file(self):
        rel = 'contracts/plan-links.v1.schema.json'
        self.installed(self.release('0.1.0'))
        (self.dest / rel).unlink()
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(rel, result.stderr)

    def test_missing_install_fails(self):
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('contracts/decisions.v1.md', result.stderr)


if __name__ == '__main__':
    unittest.main()
