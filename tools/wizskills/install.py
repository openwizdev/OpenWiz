#!/usr/bin/env python3
"""Install the WizSkills release pinned by `wizskills.lock` into `.wizskills/`.

Contract: contracts/wizskills.v1.md ("ClosedWiz pin and move"). The only
remote read is one fetch of the pinned tag. The tag's record, target and tree
are checked against the lock before the release's own `install.sh` runs, and
that installer fetches from the verified local copy, never the network again.

Exit codes: 0 installed or already current; 1 refused (mismatch, dirty or
foreign install, bad release record); 2 invalid lock; 3 fetch or I/O failure.
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
URL = 'https://github.com/openwizdev/WizSkills.git'
DEST = '.wizskills'
LOCK = 'wizskills.lock'
CONTRACT = 'contracts/wizskills.v1.md'
# Git variables that would point a command at another repository, index or
# object store, or redirect its transport; the installer sets its own.
GIT_LOCATION = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
                'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_COMMON_DIR', 'GIT_NAMESPACE',
                'GIT_CEILING_DIRECTORIES', 'GIT_DISCOVERY_ACROSS_FILESYSTEM')


class Stop(Exception):
    def __init__(self, code, reason):
        super().__init__(reason)
        self.code = code
        self.reason = reason


def refuse(reason):
    return Stop(1, f'wizskills: refused: {reason}')


def rules(root):
    """The contract's normative vocabulary block."""
    try:
        text = (root / CONTRACT).read_text(encoding='utf-8')
        blocks = re.findall(r'^```wizskills-v1\n(.*?)^```', text, re.M | re.S)
        if len(blocks) != 1:
            raise ValueError
        return json.loads(blocks[0])
    except (OSError, ValueError, UnicodeError):
        raise Stop(3, f'wizskills: cannot read {CONTRACT}') from None


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def identity(text, fields, vocab):
    """Parse a lock or release record: exactly `fields`, all well-formed strings."""
    value = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError
    if not all(isinstance(value[k], str) for k in fields):
        raise ValueError
    if not (re.fullmatch(vocab['version_pattern'], value['version'])
            and re.fullmatch(vocab['oid_pattern'], value['commit'])
            and re.fullmatch(vocab['oid_pattern'], value['tree'])):
        raise ValueError
    return value


def read_lock(root, vocab):
    try:
        return identity((root / LOCK).read_text(encoding='utf-8'), vocab['lock_fields'], vocab)
    except (OSError, ValueError, UnicodeError):
        raise Stop(2, f'wizskills: invalid lock: {LOCK}') from None


def git_env(extra=None):
    """Git isolated from the caller's configuration and attributes, file transport only.

    Every Git command but the one tag fetch uses this, the release installer
    included: no global, system or inherited `-c`/`GIT_CONFIG_*` setting (an
    attribute filter, a URL rewrite) can change what is verified or fetched.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in GIT_LOCATION and not k.startswith('GIT_CONFIG')}
    env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                'GIT_ATTR_NOSYSTEM': '1', 'GIT_ALLOW_PROTOCOL': 'file'})
    env.update(extra or {})
    return env


def caller_env():
    """The caller's environment for the one tag fetch: its own transport settings stay."""
    return {k: v for k, v in os.environ.items() if k not in GIT_LOCATION}


def git(args, env, cwd=None):
    try:
        done = subprocess.run(['git', '-c', 'core.fsmonitor=false', *args], cwd=cwd, env=env,
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise Stop(3, 'wizskills: cannot run git') from None
    return done.returncode, done.stdout


def git_input(args, env, data):
    try:
        done = subprocess.run(['git', *args], env=env, input=data,
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        raise Stop(3, 'wizskills: cannot run git') from None
    return done.returncode, done.stdout


def out(args, env, reason, cwd=None):
    code, stdout = git(args, env, cwd)
    if code != 0:
        raise refuse(reason)
    return stdout.decode('utf-8', 'replace').strip()


def verify_install(dest, lock, workdir):
    """Refuse unless `dest` is exactly the locked release, clean, with its `.git`."""
    if dest.is_symlink() or not dest.is_dir():
        raise refuse(f'{DEST} is not a directory')
    gitdir = dest / '.git'
    if gitdir.is_symlink() or not gitdir.is_dir():
        raise refuse(f'{DEST} is not a WizSkills checkout')
    env = git_env()
    mine = ['--git-dir', str(gitdir), '--work-tree', str(dest)]
    head = out([*mine, 'rev-parse', '--verify', '-q', 'HEAD^{commit}'], env,
               f'{DEST} is not a WizSkills checkout')
    head_tree = out([*mine, 'rev-parse', '--verify', '-q', 'HEAD^{tree}'], env,
                    f'{DEST} is not a WizSkills checkout')
    if head != lock['commit'] or head_tree != lock['tree']:
        raise refuse(f'{DEST} does not match the lock (another version or commit)')
    # Nothing staged: the index must equal the locked tree.
    code, _ = git([*mine, 'diff-index', '--cached', '--quiet', '--no-ext-diff',
                   lock['commit'], '--'], env)
    if code != 0:
        raise refuse(f'{DEST} does not match the lock (staged changes)')
    # The actual files, as raw bytes and modes, hashed into a scratch
    # repository, never into the installation's own .git.
    actual, dirs = raw_tree(dest, workdir)
    if actual != lock['tree']:
        raise refuse(f'{DEST} does not match the lock (files differ from the release tree)')
    # Git records no empty directories; any directory the tree lacks is extra.
    scratch = ['--git-dir', str(workdir / 'verify.git')]
    listed = out([*scratch, 'ls-tree', '-r', '-d', '--name-only', '-z', actual], env,
                 f'{DEST} cannot be read')
    if dirs - set(filter(None, listed.encode().split(b'\0'))):
        raise refuse(f'{DEST} does not match the lock (extra directory)')


def raw_tree(dest, workdir):
    """The tree of every path under `dest` but its top `.git`: raw bytes, no filters.

    Each entry's mode and blob come straight from the file system (regular,
    executable or symlink), so no attribute, line-ending or clean filter can
    make changed bytes hash like the release. Returns (tree, directories).
    """
    env = git_env({'GIT_INDEX_FILE': str(workdir / 'verify.index')})
    scratch = ['--git-dir', str(workdir / 'verify.git')]
    out(['init', '-q', '--bare', str(workdir / 'verify.git')], env,
        'cannot create scratch repository')
    unreadable = f'{DEST} does not match the lock (unexpected file)'
    root = os.fsencode(dest)
    files, links, dirs = [], [], set()
    for here, subdirs, names in os.walk(root):
        rel = os.path.relpath(here, root)
        if rel == b'.':
            subdirs[:] = [d for d in subdirs if d != b'.git']
        else:
            dirs.add(rel)
        for name in list(subdirs):
            if os.path.islink(os.path.join(here, name)):
                subdirs.remove(name)
                names.append(name)
        for name in subdirs + names:
            if name == b'.git' or b'\n' in name:
                raise refuse(unreadable)
        for name in names:
            path = os.path.join(here, name)
            entry = os.path.normpath(os.path.join(rel, name))
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode):
                links.append((entry, os.readlink(path)))
            elif stat.S_ISREG(st.st_mode):
                mode = b'100755' if st.st_mode & stat.S_IXUSR else b'100644'
                files.append((mode, entry, path))
            else:
                raise refuse(unreadable)
    index = []
    if files:
        code, stdout = git_input([*scratch, 'hash-object', '-w', '--no-filters', '--stdin-paths'],
                                 env, b''.join(path + b'\n' for _, _, path in files))
        blobs = stdout.split()
        if code != 0 or len(blobs) != len(files):
            raise refuse(unreadable)
        index += [(mode, blob, entry) for (mode, entry, _), blob in zip(files, blobs)]
    for entry, target in links:
        code, stdout = git_input([*scratch, 'hash-object', '-w', '--no-filters', '--stdin'],
                                 env, target)
        if code != 0:
            raise refuse(unreadable)
        index.append((b'120000', stdout.strip(), entry))
    code, _ = git_input([*scratch, 'update-index', '-z', '--index-info'], env,
                        b''.join(b'%s %s\t%s\0' % item for item in index))
    if code != 0:
        raise refuse(unreadable)
    return out([*scratch, 'write-tree'], env, unreadable), dirs


def fetch_release(repo, lock, vocab):
    """Fetch only the pinned tag and check its record, target and tree."""
    tag = f'v{lock["version"]}'
    env = git_env()
    out(['init', '-q', '--bare', str(repo)], env, 'cannot create staging repository')
    code, _ = git(['--git-dir', str(repo), 'fetch', '-q', '--no-tags', '--no-write-fetch-head',
                   URL, f'+refs/tags/{tag}:refs/tags/{tag}'], caller_env())
    if code != 0:
        raise Stop(3, f'wizskills: fetch failed: tag {tag}')
    on = ['--git-dir', str(repo)]
    kind = out([*on, 'cat-file', '-t', f'refs/tags/{tag}'], env, 'release tag unreadable')
    if kind != 'tag':
        raise refuse(f'release tag {tag} is not annotated')
    code, raw = git([*on, 'cat-file', 'tag', f'refs/tags/{tag}'], env)
    if code != 0:
        raise refuse('release tag unreadable')
    header, sep, message = raw.partition(b'\n\n')
    fields = dict(line.split(' ', 1) for line in header.decode('utf-8', 'replace').split('\n')
                  if ' ' in line)
    try:
        record = identity(message.decode('utf-8'), vocab['release_fields'], vocab)
    except (ValueError, UnicodeError):
        raise refuse(f'release tag {tag} has no valid release record') from None
    if (not sep or record['schema'] != vocab['release_schema']
            or fields.get('type') != 'commit' or fields.get('tag') != tag
            or fields.get('object') != record['commit']):
        raise refuse(f'release tag {tag} has no valid release record')
    if any(record[k] != lock[k] for k in vocab['lock_fields']):
        raise refuse(f'release tag {tag} does not match the lock')
    tree = out([*on, 'rev-parse', '--verify', '-q', f'{lock["commit"]}^{{tree}}'], env,
               f'release tag {tag} does not match the lock')
    if tree != lock['tree']:
        raise refuse(f'release tag {tag} does not match the lock')
    # The release installer, from the verified tree: a regular executable file.
    entry = out([*on, 'ls-tree', lock['commit'], '--', 'install.sh'], env,
                'release has no install.sh')
    if not entry.startswith('100755 blob '):
        raise refuse('release has no executable install.sh')
    code, script = git([*on, 'cat-file', 'blob', entry.split()[2]], env)
    if code != 0:
        raise refuse('release has no install.sh')
    return script


def run_release_installer(script, repo, lock, dest, workdir):
    path = workdir / 'install.sh'
    path.write_bytes(script)
    path.chmod(0o700)
    # Point the release URL at the verified local copy: no second download.
    env = git_env({'GIT_CONFIG_COUNT': '1',
                   'GIT_CONFIG_KEY_0': f'url.{repo.as_uri()}.insteadOf',
                   'GIT_CONFIG_VALUE_0': URL})
    try:
        done = subprocess.run(['sh', str(path), '--version', lock['version'],
                               '--dest', str(dest)], cwd=workdir, env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
    except (OSError, subprocess.SubprocessError):
        raise Stop(3, 'wizskills: cannot run the release installer') from None
    if done.returncode == 1:
        raise refuse('release installer refused')
    if done.returncode != 0:
        raise Stop(3, f'wizskills: release installer failed (exit {done.returncode})')


def install(root):
    vocab = rules(root)
    lock = read_lock(root, vocab)
    dest = root / DEST
    with tempfile.TemporaryDirectory(prefix='wizskills-') as tmp:
        workdir = Path(tmp)
        if os.path.lexists(dest):
            verify_install(dest, lock, workdir)
            return 'already installed'
        repo = workdir / 'release.git'
        script = fetch_release(repo, lock, vocab)
        if os.path.lexists(dest):
            raise refuse(f'{DEST} appeared during installation')
        run_release_installer(script, repo, lock, dest, workdir)
        check = workdir / 'check'
        check.mkdir()
        try:
            verify_install(dest, lock, check)
        except Stop as stop:
            raise Stop(1, f'{stop.reason}; installed by the release installer, left in place')
    return 'installed'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[2]),
                        help='the ClosedWiz checkout (default: this one)')
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve(strict=True)
        result = install(root)
    except Stop as stop:
        print(stop.reason, file=sys.stderr)
        return stop.code
    except OSError:
        print('wizskills: local I/O failure', file=sys.stderr)
        return 3
    print(f'wizskills: {result}: {DEST}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
