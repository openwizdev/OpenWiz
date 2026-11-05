#!/usr/bin/env python3
"""Prepare an ordinary public commit or a reviewed public patch, entirely locally."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


class Refused(Exception):
    pass


def environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1',
               GIT_TERMINAL_PROMPT='0', GIT_ALLOW_PROTOCOL='',
               GIT_CONFIG_COUNT='3', GIT_CONFIG_KEY_0='core.hooksPath',
               GIT_CONFIG_VALUE_0='/dev/null', GIT_CONFIG_KEY_1='protocol.allow',
               GIT_CONFIG_VALUE_1='never', GIT_CONFIG_KEY_2='core.fsmonitor',
               GIT_CONFIG_VALUE_2='false')
    return env


def git(repo, *args, data=None):
    r = subprocess.run(['git', '--literal-pathspecs', '-C', str(repo), *args], input=data,
                       capture_output=True, env=environment())
    if r.returncode:
        raise Refused('Git input or local operation refused')
    return r.stdout


def oid(repo, ref):
    # End options before resolving untrusted revision spellings.
    value = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    if not re.fullmatch('[0-9a-f]{40}', value):
        raise Refused('only SHA-1 repositories are supported')
    return value


def repository(path):
    path = path.resolve(strict=True)
    root_flag = '--absolute-git-dir' if git(path, 'rev-parse', '--is-bare-repository').strip() == b'true' else '--show-toplevel'
    path = Path(git(path, 'rev-parse', root_flag).decode().removesuffix('\n')).resolve(strict=True)
    if git(path, 'rev-parse', '--is-shallow-repository').strip() != b'false':
        raise Refused('shallow repository cannot prove ancestry')
    grafts = git(path, 'rev-parse', '--git-path', 'info/grafts').decode().removesuffix('\n')
    if (path / grafts).exists():
        raise Refused('grafts cannot prove ancestry')
    return path


def check_patch_output(output, repositories):
    output = output.resolve()
    for repo in repositories:
        excluded = {repo}
        for flags in (('--absolute-git-dir',), ('--path-format=absolute', '--git-common-dir')):
            path = Path(git(repo, 'rev-parse', *flags).decode().removesuffix('\n'))
            if not path.is_absolute():
                raise Refused('unreadable repository directory')
            excluded.add(path.resolve())
        # NUL records preserve spaces/newlines and avoid Git's quoted-path form.
        records = git(repo, 'worktree', 'list', '--porcelain', '-z').split(b'\0\0')
        if len(records) < 2 or records[-1] != b'':
            raise Refused('unreadable worktree inventory')
        for record in records[:-1]:
            header, *fields = record.split(b'\0')
            if not header.startswith(b'worktree '):
                raise Refused('unreadable worktree inventory')
            metadata = {}
            for field in fields:
                key, separator, value = field.partition(b' ')
                if key not in {b'HEAD', b'branch', b'bare', b'detached', b'locked', b'prunable'} or key in metadata:
                    raise Refused('unreadable worktree inventory')
                if key in {b'bare', b'detached'} and separator:
                    raise Refused('unreadable worktree inventory')
                if key in {b'HEAD', b'branch'} and (not separator or not value):
                    raise Refused('unreadable worktree inventory')
                if key == b'HEAD' and not re.fullmatch(b'[0-9a-f]{40}', value):
                    raise Refused('unreadable worktree inventory')
                metadata[key] = value
            if b'bare' in metadata:
                valid = not ({b'HEAD', b'branch', b'detached'} & metadata.keys())
            else:
                valid = b'HEAD' in metadata and ((b'branch' in metadata) != (b'detached' in metadata))
            if not valid:
                raise Refused('unreadable worktree inventory')
            path = Path(header[len(b'worktree '):].decode())
            if not path.is_absolute():
                raise Refused('unreadable worktree inventory')
            # Keep registered but currently missing/prunable roots excluded too.
            excluded.add(path.resolve())
        if any(output.is_relative_to(root) for root in excluded):
            raise Refused('patch output must be outside input repositories')


def safe_name(name):
    if (not name or name.startswith('/') or '\\' in name or
            any(ord(c) < 32 or ord(c) == 127 for c in name) or
            any(p in ('', '.', '..') or p.casefold() == '.git' for p in name.split('/'))):
        raise Refused('unsafe tree path')


def entries(repo, commit):
    result = {}
    for row in git(repo, 'ls-tree', '-rz', '--full-tree', commit).split(b'\0'):
        if not row:
            continue
        info, raw = row.split(b'\t', 1)
        mode, kind, object_id = info.decode().split()
        name = raw.decode('utf-8')
        safe_name(name)
        if kind != 'blob' or mode not in ('100644', '100755', '120000'):
            raise Refused('unsupported tree entry (submodules are not carried)')
        result[name] = (mode, object_id)
    return result


def load(repo, listing):
    return {name: (mode, git(repo, 'cat-file', 'blob', object_id))
            for name, (mode, object_id) in listing.items()}


def policy():
    raw = (HERE / 'paths.json').read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def private_or_retired(name):
    return (name == 'private' or name.startswith('private/') or
            ((name == 'docs/grills' or name.startswith('docs/grills/')) and name != 'docs/grills/README.md') or
            name.startswith(('tools/ci-overflow/', 'tools/pc-capacity/')) or
            (name.startswith('ci/runner/') and name not in
             ('ci/runner/cache.sh', 'ci/runner/.gitattributes')))


def carries(name, rules):
    if private_or_retired(name) or name in rules['keep']:
        return False
    for pattern in rules['source']:
        if pattern.endswith('/**') and name.startswith(pattern[:-2]):
            return True
        if pattern == 'docs/*' and name.startswith('docs/') and name.count('/') == 1:
            return True
        if name == pattern:
            return True
    return False


def selected(source, head, public, base, rules):
    src = entries(source, head)
    unknown = [n for n in src if not carries(n, rules) and
               not private_or_retired(n) and n not in rules['keep']]
    if unknown:
        raise Refused(f'unlisted source paths: {len(unknown)}; review the carriage list')
    result = load(source, {n: v for n, v in src.items() if carries(n, rules)})
    keep = entries(public, base)
    result.update(load(public, {n: v for n, v in keep.items() if n in rules['keep']}))
    return result


def validate_links(files, require_targets=True):
    directories = {''}
    for name in files:
        safe_name(name)
        parts = name.split('/')
        prefixes = {'/'.join(parts[:i]) for i in range(1, len(parts))}
        if prefixes & files.keys():
            raise Refused('tree path prefix conflict')
        directories.update(prefixes)

    def resolve(parts, current, active):
        # Expand links as each component is traversed. Collapsing '..' first
        # erases intermediate symlinks and can turn an escape into a safe path.
        for part in parts:
            parent = '/'.join(current)
            if parent in files or (require_targets and parent not in directories):
                raise Refused('symlink traverses a non-directory or missing path')
            if part in ('', '.'):
                continue
            if part == '..':
                if not current:
                    raise Refused('symlink leaves public carriage')
                current = current[:-1]
                continue
            candidate = '/'.join([*current, part])
            safe_name(candidate)
            mode, data = files.get(candidate, ('', b''))
            if mode == '120000':
                if candidate in active:
                    raise Refused('cyclic public symlink')
                target = data.decode('utf-8')
                if (not target or target.startswith('/') or '\\' in target or
                        any(ord(c) < 32 or ord(c) == 127 for c in target)):
                    raise Refused('unsafe symlink')
                current = resolve(target.split('/'), current, active | {candidate})
            else:
                current = [*current, part]
        result = '/'.join(current)
        if private_or_retired(result):
            raise Refused('symlink leaves public carriage')
        if require_targets and result not in files and result not in directories:
            raise Refused('dangling public symlink')
        return current

    for name, (mode, data) in files.items():
        if mode == '120000':
            resolve(name.split('/'), [], frozenset())


@contextlib.contextmanager
def directory(files, require_targets=True):
    validate_links(files, require_targets)
    with tempfile.TemporaryDirectory(prefix='open-import-tree-') as folder:
        root = Path(folder)
        for name, (mode, data) in sorted(files.items()):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if mode == '120000':
                path.symlink_to(data.decode('utf-8'))
            else:
                path.write_bytes(data)
                path.chmod(0o755 if mode == '100755' else 0o644)
        yield root


def privacy(args, *flags):
    r = subprocess.run([sys.executable, '-I', str(args.checker.resolve(strict=True)),
                        '--literals', str(args.literals.resolve(strict=True)),
                        '--require-literals', *map(str, flags)],
                       capture_output=True, text=True, env=environment())
    output = r.stdout
    if r.returncode or 'literals: used' not in output:
        raise Refused('privacy refused\n' + output)
    return output


def check_files(args, files, require_targets=True):
    with directory(files, require_targets) as root:
        return privacy(args, '--tree', root)


def pack(repo, head, base=None):
    revisions = head + '\n' + ('^' + base + '\n' if base else '')
    return git(repo, 'pack-objects', '--stdout', '--revs', data=revisions.encode())


def write_tree(repo, files):
    nested = {}
    for name, (mode, data) in files.items():
        target = nested
        parts = name.split('/')
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        blob = git(repo, 'hash-object', '-w', '--stdin', data=data).decode().strip()
        target[parts[-1]] = (mode, blob)

    def tree(items):
        rows = []
        for name, value in items.items():
            mode, kind, obj = ('040000', 'tree', tree(value)) if isinstance(value, dict) else (value[0], 'blob', value[1])
            rows.append(f'{mode} {kind} {obj}\t{name}'.encode() + b'\0')
        return git(repo, 'mktree', '-z', data=b''.join(rows)).decode().strip()
    return tree(nested)


def commit(repo, tree, base):
    # Fixed public identity and the base's timestamp make identical inputs stable.
    timestamp = git(repo, 'show', '-s', '--format=%ct', base).decode().strip()
    env = environment()
    for role in ('AUTHOR', 'COMMITTER'):
        env['GIT_' + role + '_NAME'] = 'OpenWiz import'
        env['GIT_' + role + '_EMAIL'] = 'openwiz@users.noreply.github.com'
        env['GIT_' + role + '_DATE'] = '@' + timestamp + ' +0000'
    r = subprocess.run(['git', '-C', str(repo), 'commit-tree', tree, '-p', base],
                       input=b'Prepare reviewed public files\n', capture_output=True, env=env)
    if r.returncode:
        raise Refused('local commit creation refused')
    return r.stdout.decode().strip()


def summary(before, after):
    return {'added': len(after.keys() - before.keys()),
            'deleted': len(before.keys() - after.keys()),
            'modified': sum(before[n] != after[n] for n in before.keys() & after.keys())}


def read_binding(args, base, digest, rules):
    folder = args.patch_dir.resolve(strict=True)
    raw = (folder / 'binding.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.binding_sha256:
        raise Refused('patch binding digest mismatch')
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise Refused('duplicate patch binding key')
            result[key] = value
        return result
    binding = json.loads(raw, object_pairs_hook=pairs)
    keys = {'schema', 'source_base', 'source_head', 'destination_base', 'tree',
            'patch_sha256', 'policy_sha256', 'paths', 'excluded'}
    if (not isinstance(binding, dict) or set(binding) != keys or
            binding['schema'] != 'openwiz.public-patch.v1' or
            binding['destination_base'] != base or binding['policy_sha256'] != digest or
            not isinstance(binding['paths'], list) or not binding['paths'] or
            any(not isinstance(n, str) or not carries(n, rules) for n in binding['paths']) or
            len(set(binding['paths'])) != len(binding['paths']) or
            type(binding['excluded']) is not int or binding['excluded'] < 0 or
            any(not isinstance(binding[k], str) or not re.fullmatch('[0-9a-f]{40}', binding[k])
                for k in ('source_base', 'source_head', 'tree'))):
        raise Refused('patch binding shape, policy or destination mismatch')
    patch = (folder / 'public.patch').read_bytes()
    if hashlib.sha256(patch).hexdigest() != binding['patch_sha256']:
        raise Refused('patch binding bytes mismatch')
    return binding, patch


def prepare(args):
    rules, digest = policy()
    public = repository(args.destination)
    base = oid(public, 'refs/heads/main')
    # C1 is checked on the final candidate in scratch, before any destination
    # write. The old public tree may contain text this import replaces.
    before = load(public, entries(public, base))
    with tempfile.TemporaryDirectory(prefix='open-import-') as folder:
        scratch = Path(folder)
        git(scratch, 'init', '--bare', '-q')
        git(scratch, 'unpack-objects', '-q', data=pack(public, base))
        patch_bytes, binding = None, None
        if args.command == 'apply-patch':
            binding, patch_bytes = read_binding(args, base, digest, rules)
            git(scratch, 'read-tree', base)
            git(scratch, '-c', 'apply.whitespace=nowarn', 'apply', '--cached', '--binary', '--whitespace=nowarn', data=patch_bytes)
            candidate = git(scratch, 'write-tree').decode().strip()
            files = load(scratch, entries(scratch, candidate))
            changed = sorted(n for n in before.keys() | files.keys() if before.get(n) != files.get(n))
            if candidate != binding['tree'] or changed != binding['paths']:
                raise Refused('patch binding tree or changed paths mismatch')
        else:
            source = repository(args.source)
            if source == public:
                raise Refused('source and destination must be separate repositories')
            if args.command == 'patch':
                check_patch_output(args.output, (source, public))
            head = oid(source, args.commit)
            if args.command == 'tree':
                files = selected(source, head, public, base, rules)
            else:
                source_base = oid(source, args.source_base)
                git(source, 'merge-base', '--is-ancestor', source_base, head)
                old, new = entries(source, source_base), entries(source, head)
                changed = sorted(n for n in old.keys() | new.keys() if old.get(n) != new.get(n))
                if any(not carries(n, rules) and not private_or_retired(n) and n not in rules['keep'] for n in changed):
                    raise Refused('unlisted patch carriage')
                paths = [n for n in changed if carries(n, rules)]
                if not paths:
                    raise Refused('no public patch carriage')
                # Removed lines are public patch contents too: scan both sides.
                # Include actual unchanged destination workflows for local
                # reusable references, and symlinks for component resolution.
                context = {n: v for n, v in before.items() if v[0] == '120000' or
                           re.fullmatch(r'\.github/workflows/[^/]+\.ya?ml', n)}
                for listing in (old, new):
                    snapshot = {n: v for n, v in context.items() if n not in paths}
                    snapshot.update(load(source, {n: listing[n] for n in paths if n in listing}))
                    check_files(args, snapshot, require_targets=False)
                patch_bytes = git(source, 'diff', '--binary', '--full-index', '--no-renames',
                                  '--no-ext-diff', '--no-textconv', '--no-color', '--no-relative',
                                  '--src-prefix=a/', '--dst-prefix=b/', source_base, head, '--', *paths)
                git(scratch, 'read-tree', base)
                git(scratch, 'apply', '--cached', '--binary', '--whitespace=nowarn', data=patch_bytes)
                candidate = git(scratch, 'write-tree').decode().strip()
                files = load(scratch, entries(scratch, candidate))
                applied = sorted(n for n in before.keys() | files.keys() if before.get(n) != files.get(n))
                if applied != paths:
                    raise Refused('patch carriage read-back mismatch')
                binding = dict(schema='openwiz.public-patch.v1', source_base=source_base,
                               source_head=head, destination_base=base, tree=candidate,
                               patch_sha256=hashlib.sha256(patch_bytes).hexdigest(),
                               policy_sha256=digest, paths=paths, excluded=len(changed) - len(paths))
        result = dict(files=len(files), bytes=sum(len(v[1]) for v in files.values()),
                      destination_base=base, diff=summary(before, files), dry_run=not args.write_local)
        try:
            result['privacy'] = check_files(args, files)
            tree = write_tree(scratch, files)
            head_commit = commit(scratch, tree, base)
            result['privacy'] += privacy(args, '--repo', scratch, '--git-tree', tree,
                                         '--base', base, '--head', head_commit)
        except Refused as error:
            result.update(status='refused', privacy=str(error))
            print(json.dumps(result, indent=2))
            return 1
        result.update(status='checked', tree=tree, commit=head_commit)
        if oid(public, 'refs/heads/main') != base:
            raise Refused('destination main changed during preparation')
        if args.command == 'patch':
            raw = (json.dumps(binding, indent=2, sort_keys=True) + '\n').encode()
            result['binding_sha256'] = hashlib.sha256(raw).hexdigest()
            # Read the inventory again immediately before creating artifacts.
            check_patch_output(args.output, (source, public))
            # New folder only: never replace an earlier reviewed patch.
            args.output.mkdir(mode=0o700)
            (args.output / 'public.patch').write_bytes(patch_bytes)
            (args.output / 'binding.json').write_bytes(raw)
        if args.write_local:
            git(public, 'unpack-objects', '-q', data=pack(scratch, head_commit, base))
            if oid(public, head_commit) != head_commit:
                raise Refused('local commit read-back failed')
            result['saved'] = True
        print(json.dumps(result, indent=2))
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('tree', 'patch', 'apply-patch'):
        command = commands.add_parser(name)
        command.add_argument('--destination', type=Path, required=True)
        command.add_argument('--checker', type=Path, default=HERE.parent / 'privacy-check/check.py')
        command.add_argument('--literals', type=Path, required=True)
        if name != 'patch':
            command.add_argument('--write-local', action='store_true')
        else:
            command.set_defaults(write_local=False)
        if name != 'apply-patch':
            command.add_argument('--source', type=Path, required=True)
            command.add_argument('--commit', required=True)
        if name == 'patch':
            command.add_argument('--source-base', required=True)
            command.add_argument('--output', type=Path, required=True)
        if name == 'apply-patch':
            command.add_argument('--patch-dir', type=Path, required=True)
            command.add_argument('--binding-sha256', required=True)
    args = parser.parse_args()
    try:
        return prepare(args)
    except (Refused, OSError, ValueError, UnicodeError, RecursionError):
        # Do not echo Git stderr, source content or identifiers on input failures.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, Refused) else 'unreadable input or invalid shape', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
