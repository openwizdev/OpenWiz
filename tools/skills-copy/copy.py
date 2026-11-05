#!/usr/bin/env python3
"""Stage the reviewed skills copy. Dry-run by default; --publish is a separate write."""
import argparse
import datetime
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import standalone  # noqa: E402

PRIVACY = HERE.parent / 'privacy-check' / 'check.py'
TARGETS = {'git@github.com:openwizdev/WizSkills.git', 'https://github.com/openwizdev/WizSkills.git'}
# Reviewed carriage list (#1408, WZ2 #2630). Never copy a whole checkout or
# .claude/skills: ClosedWiz's three release skills there stay private.
CONTRACT = 'contracts/wizskills.v1.md'
# WizDev has not been planned (#1288). This optional root is its extension seam;
# another layout must first change this reviewed list and the workflow filter.
ROOTS = ('skills', 'wizdev/skills')
ENV = {k: v for k, v in os.environ.items() if k not in {
    'GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_OBJECT_DIRECTORY',
    'GIT_ALTERNATE_OBJECT_DIRECTORIES', 'GIT_COMMON_DIR'}}
ENV.update(GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0')


class Refusal(Exception):
    pass


def git(repo, *args, data=None, allowed=(0,), env=None):
    result = subprocess.run(['git', '-C', str(repo), *args], input=data,
                            capture_output=True, env=env or ENV)
    if result.returncode not in allowed:
        raise Refusal('Git operation refused: ' + args[0])
    return result


def resolve(repo, ref, kind='commit'):
    value = git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{' + kind + '}').stdout.decode().strip()
    if not re.fullmatch('[0-9a-f]{40}', value):
        raise Refusal('Expected a SHA-1 repository')
    return value


def entries(repo, ref):
    result = {}
    for row in git(repo, 'ls-tree', '-rz', '--full-tree', ref).stdout.split(b'\0'):
        if row:
            info, name = row.split(b'\t', 1)
            mode, kind, oid = info.decode().split()
            result[name.decode('utf-8')] = (mode, kind, oid)
    return result


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def stage(source, commit, output):
    tracked = entries(source, commit)
    # ls-tree -r omits directories, so an exact entry at a selected root or
    # ancestor is a file/link/submodule, never a directory we may silently skip.
    for folder in ROOTS:
        path = PurePosixPath(folder)
        if any(parent.as_posix() in tracked for parent in (path, *path.parents)):
            raise Refusal('Selected source roots and ancestors must be directories')
    folders = []
    for root in ROOTS:
        # Every direct child must be a skill folder, never a silently dropped tree.
        selected = {p: entry for p, entry in tracked.items() if p.startswith(root + '/')}
        if any(entry[0] not in ('100644', '100755') for p, entry in selected.items()
               if '/' not in p[len(root) + 1:]):
            raise Refusal('A skill root cannot be a symlink or submodule')
        children = {p[len(root) + 1:].split('/')[0] for p in selected if '/' in p[len(root) + 1:]}
        for name in sorted(children):
            folder = root + '/' + name
            if folder + '/SKILL.md' not in tracked:
                raise Refusal('Selected folder has no SKILL.md')
            folders.append((folder, name))
    names = sorted(name for _, name in folders)
    if not names or len(set(names)) != len(names):
        raise Refusal('No skills, or colliding skill names')
    for folder, name in folders:
        if not re.fullmatch('[a-z0-9][a-z0-9-]*', name):
            raise Refusal('Invalid skill folder name')
        if tracked[folder + '/SKILL.md'][0] not in ('100644', '100755'):
            raise Refusal('SKILL.md must be a regular file')
        for path, (mode, kind, oid) in tracked.items():
            if not path.startswith(folder + '/'):
                continue
            suffix = path[len(folder) + 1:]
            parts = PurePosixPath(suffix).parts
            if (not parts or any(p in ('.', '..', '.git', 'private') for p in parts)
                    or PurePosixPath(suffix).is_absolute() or kind != 'blob'
                    or mode not in ('100644', '100755', '120000')):
                raise Refusal('Private, unsafe or unsupported selected path')
            dest = output / 'skills' / name / suffix
            dest.parent.mkdir(parents=True, exist_ok=True)
            data = git(source, 'cat-file', 'blob', oid).stdout
            if mode == '120000':
                dest.symlink_to(data.decode('utf-8'))
            else:
                dest.write_bytes(data)
                dest.chmod(0o755 if mode == '100755' else 0o644)
    # Never follow links while copying. Validate all targets only after extraction.
    for path in output.rglob('*'):
        if path.is_symlink():
            target = path.resolve(strict=True)
            if not target.is_relative_to(output / 'skills') or not target.is_file():
                raise Refusal('Skill symlink leaves the selected files')
    rules = carry(source, tracked, output)
    for prefix in ('.agents', '.claude'):
        folder = output / prefix / 'skills'
        folder.mkdir(parents=True)
        for name in names:
            (folder / name).symlink_to('../../skills/' + name)
    return names, rules


def carry(source, tracked, output):
    # The contract at the pinned commit names the carried contracts; each is
    # written byte for byte at its same relative path, so a skill's
    # ../../contracts/<file> link resolves in both trees.
    try:
        mode, kind, oid = tracked[CONTRACT]
        if mode not in ('100644', '100755'):
            raise ValueError('contract is not a regular file')
        rules = standalone.contract_rules(git(source, 'cat-file', 'blob', oid).stdout.decode('utf-8'))
    except (KeyError, ValueError, UnicodeError):
        raise Refusal('Unreadable carried contracts list') from None
    for path in rules['carried_contracts']:
        entry = tracked.get(path)
        if not entry or entry[0] not in ('100644', '100755') or entry[1] != 'blob':
            raise Refusal('A carried contracts source is missing or not a regular file')
        dest = output / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git(source, 'cat-file', 'blob', entry[2]).stdout)
        dest.chmod(0o644)
    return rules


# Generated files (WZ3, #2631): the WizSkills package around the copied skills.
# Templates and WZ7's check folder come from the pinned commit, like the skills.
PACKAGE = 'tools/skills-copy/package/'
PACKAGE_CHECK = 'tools/skills-copy/package-check/'
# openwiz.wizskills.v1's version_pattern.
VERSION = re.compile(
    r'(?:0\.[1-9][0-9]*|[1-9][0-9]*\.(?:0|[1-9][0-9]*))\.(?:0|[1-9][0-9]*)'
    r'(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?'
    r'(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?')
NOTICE = re.compile(r'^Copyright \(c\) [^\n]+\n.*?OTHER DEALINGS IN THE\s+SOFTWARE\.$', re.M | re.S)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refusal('Package template has a duplicate JSON key')
        result[key] = value
    return result


def package(source, commit, output, names, version):
    """Write README, CHANGELOG, LICENSE, both manifests, install.sh and WZ7's check."""
    if not VERSION.fullmatch(version):
        raise Refusal('Invalid --version: a SemVer version without a leading v, 0.1.0 or later')
    tracked = entries(source, commit)

    def template(name):
        entry = tracked.get(PACKAGE + name)
        if not entry or entry[1] != 'blob' or entry[0] not in ('100644', '100755'):
            raise Refusal('Package template missing or not a regular file')
        return git(source, 'cat-file', 'blob', entry[2]).stdout.decode('utf-8')

    plugin = json.loads(template('plugin.json'), object_pairs_hook=unique_object)
    market = json.loads(template('marketplace.json'), object_pairs_hook=unique_object)
    changelog = template('CHANGELOG.md')
    heading = next((line for line in changelog.split('\n') if line.startswith('## ')), '')
    latest = re.fullmatch(r'## (\S+) - ([0-9]{4}-[0-9]{2}-[0-9]{2})', heading)
    if not (isinstance(plugin, dict) and plugin.get('version') == version
            and latest and latest.group(1) == version):
        raise Refusal('Package version disagrees: --version, plugin.json and the latest CHANGELOG.md section must agree')
    datetime.date.fromisoformat(latest.group(2))
    if (plugin.get('name') != 'openwiz' or 'skills' in plugin or not isinstance(market, dict)
            or market.get('name') != 'wizskills' or not isinstance(market.get('owner'), dict)
            or not isinstance(market.get('plugins'), list) or len(market['plugins']) != 1
            or not isinstance(market['plugins'][0], dict)
            or market['plugins'][0].get('name') != 'openwiz' or market['plugins'][0].get('source') != './'
            or market['plugins'][0].get('version', version) != version):
        raise Refusal('Package manifests do not match openwiz.wizskills.v1')
    section = changelog[changelog.index(heading):].split('\n## ')[0]
    if (not changelog.startswith('# Changelog\n') or changelog.count('{{skills}}\n') != 1
            or '{{skills}}\n' not in section):
        raise Refusal('CHANGELOG.md template must hold one {{skills}} line in its latest section')
    write_json(output / '.claude-plugin/plugin.json', dict(plugin, skills=['./skills/' + n for n in names]))
    write_json(output / '.claude-plugin/marketplace.json', market)
    (output / 'CHANGELOG.md').write_text(changelog.replace(
        '{{skills}}\n', ''.join(f'- `{n}`: first public release.\n' for n in names)), encoding='utf-8')
    readme = template('README.md').replace('{{version}}', version)
    if '{{' in readme:
        raise Refusal('README.md template has an unknown placeholder')
    (output / 'README.md').write_text(readme, encoding='utf-8')
    # LICENSE: the upstream notices the copied skills carry, each once, as carried.
    notices = {}
    for name in names:
        text = (output / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')
        found = NOTICE.findall(text)
        if len(found) != len(re.findall(r'^Copyright \(c\) ', text, re.M)):
            raise Refusal('Incomplete licence notice in a copied SKILL.md')
        for notice in found:
            notices.setdefault(' '.join(notice.split()), notice)
    (output / 'LICENSE').write_text(template('LICENSE') + ''.join(
        '\n---\n\n' + n + '\n' for n in notices.values()), encoding='utf-8')
    (output / 'install.sh').write_text(template('install.sh'), encoding='utf-8')
    (output / 'install.sh').chmod(0o755)
    # WZ7's check folder goes to check/; its ci.yml is the one workflow.
    carried = False
    for path, (mode, kind, oid) in sorted(tracked.items()):
        if not path.startswith(PACKAGE_CHECK):
            continue
        suffix = path[len(PACKAGE_CHECK):]
        parts = PurePosixPath(suffix).parts
        if kind != 'blob' or mode not in ('100644', '100755') or any(p in ('.', '..', '.git', 'private') for p in parts):
            raise Refusal('Unsupported path in the WizSkills check folder')
        dest = output / ('.github/workflows/ci.yml' if suffix == 'ci.yml' else 'check/' + suffix)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(git(source, 'cat-file', 'blob', oid).stdout)
        dest.chmod(0o755 if mode == '100755' else 0o644)
        carried = True
    return {'version': version, 'check': 'carried' if carried else 'missing'}


def tree(repo, output):
    # Build an exact index: do not let copied .gitignore files exclude scripts/tests,
    # or copied attributes/filters execute anything during staging.
    rows = []
    for path in sorted(output.rglob('*')):
        if path.is_symlink():
            mode, data = '120000', os.readlink(path).encode('utf-8')
        elif path.is_file():
            mode = '100755' if path.stat().st_mode & 0o111 else '100644'
            data = path.read_bytes()
        else:
            continue
        oid = git(repo, 'hash-object', '-w', '--stdin', data=data).stdout.decode().strip()
        rows.append((mode + ' ' + oid + '\t' + path.relative_to(output).as_posix()).encode() + b'\0')
    git(repo, 'update-index', '-z', '--index-info', data=b''.join(rows))
    return resolve(repo, git(repo, 'write-tree').stdout.decode().strip(), 'tree')


def difference(before, after):
    return {kind: sorted(p for p in paths if predicate(p)) for kind, paths, predicate in (
        ('added', after, lambda p: p not in before),
        ('modified', after, lambda p: p in before and before[p] != after[p]),
        ('deleted', before, lambda p: p not in after))}


def destination_base(destination, publish):
    if not destination:
        if publish:
            raise Refusal('--publish requires --destination, a dedicated skills clone')
        return None
    remote = git(destination, 'remote', 'get-url', 'origin').stdout.decode().strip()
    push_remote = git(destination, 'remote', 'get-url', '--push', '--all', 'origin').stdout.decode().splitlines()
    if remote not in TARGETS or push_remote != [remote]:
        raise Refusal('Destination origin must be openwizdev/WizSkills, with the same single push URL')
    if publish:
        if git(destination, 'status', '--porcelain', '--untracked-files=all', '--ignored').stdout:
            raise Refusal('Destination must be a clean dedicated clone')
        read = git(destination, 'ls-remote', '--exit-code', 'origin', 'refs/heads/main', allowed=(0, 2))
        if read.returncode == 2:
            return None
        expected = read.stdout.decode().strip().split('\t')
        if len(expected) != 2 or expected[1] != 'refs/heads/main':
            raise Refusal('Unreadable destination main')
        git(destination, 'fetch', '--no-tags', 'origin', 'refs/heads/main')
        parent = resolve(destination, 'FETCH_HEAD')
        if parent != expected[0]:
            raise Refusal('Destination moved during read; inspect and rerun')
        return parent
    # Dry runs read cached refs only; they never fetch, commit or push in destination.
    for ref in ('refs/remotes/origin/main', 'refs/heads/main'):
        result = git(destination, 'show-ref', '--verify', '--hash', ref, allowed=(0, 1, 128))
        if result.returncode == 0:
            return resolve(destination, ref)
    return None


def closedwiz_origin(remote):
    # Match repository identity, never a substring of an unrelated host/path.
    # GitHub owner/repository spelling is case-insensitive across Git URL forms.
    # SSH configuration may supply the user for a userless scp origin.
    scp = None
    if '://' not in remote:
        scp = re.fullmatch(r'(?:[^@/:]+@)?([^/:]+):(.+)', remote, re.IGNORECASE)
    if scp:
        host, path = scp.groups()
    else:
        parsed = urlsplit(remote)
        if parsed.scheme not in ('https', 'http', 'ssh', 'git'):
            return False
        host, path = parsed.hostname or '', parsed.path
    path = unquote(path).strip('/')
    if path.casefold().endswith('.git'):
        path = path[:-4]
    return host.casefold() == 'github.com' and path.casefold() == 'jparker2006/closedwiz'


def run(args):
    if args.output and (args.output.exists() or args.output.is_symlink()):
        raise Refusal('--output must not exist')
    if args.publish and args.output:
        raise Refusal('Save a dry-run output separately before publication')
    commit = resolve(args.source, args.commit)
    remote = git(args.source, 'config', '--get', 'remote.origin.url', allowed=(0, 1)).stdout.decode().strip()
    literals = args.literals
    if closedwiz_origin(remote) and literals is None:
        literals = args.source / 'private/evidence/open-development/privacy-check/literals.txt'
    with tempfile.TemporaryDirectory(prefix='skills-copy-') as temp:
        root = Path(temp)
        output = root / 'stage'
        output.mkdir()
        names, rules = stage(args.source, commit, output)
        packaged = package(args.source, commit, output, names, args.version)
        objects = root / 'objects'
        objects.mkdir()
        git(objects, 'init', '-q')
        new_tree = tree(objects, output)
        paths = [p for p in output.rglob('*') if p.is_file() or p.is_symlink()]
        result = {'commit': commit, 'skills': names, 'tree': new_tree, 'files': len(paths),
                  'bytes': sum(len(os.readlink(p).encode()) if p.is_symlink() else p.stat().st_size for p in paths),
                  'published': None, 'mode': 'publish' if args.publish else 'dry-run', 'package': packaged}
        command = [sys.executable, '-I', str(PRIVACY), '--tree', str(output)]
        if literals is not None:
            command += ['--literals', str(literals), '--require-literals']
        check = subprocess.run(command, capture_output=True, text=True)
        result['privacy'] = {'status': 'pass' if check.returncode == 0 else 'refused',
                             'result': (check.stdout + check.stderr).replace(str(output), '<staged>')}
        # The standalone check reads the staged tree only; its records hold
        # rule, file and line, never contents or targets.
        refusals = standalone.check(output, rules['project_settings'])
        # Every printed location is redacted like the privacy check's own.
        # An unreadable list is already a privacy refusal; the other forms
        # are still redacted.
        try:
            values = [v for v in literals.read_text(encoding='utf-8').splitlines() if v] if literals is not None else ()
        except (OSError, UnicodeError):
            values = ()
        result['standalone'] = {'status': 'refused' if refusals else 'pass', 'skills': {
            name: standalone.redacted(records, values) for name, records in standalone.by_skill(refusals).items()}}
        if check.returncode != 0 or refusals:
            print(json.dumps(result, indent=2))
            return 1
        if args.publish and packaged['check'] != 'carried':
            raise Refusal('The WizSkills check folder is missing; publication refused')
        parent = destination_base(args.destination, args.publish)
        before = entries(args.destination, parent) if parent else {}
        after = entries(objects, new_tree)
        result['diff'] = difference(before, after)
        result['parent'] = parent
        result['unchanged'] = bool(parent and resolve(args.destination, parent, 'tree') == new_tree)
        result['proposed_commit'] = None
        if not result['unchanged']:
            if parent:
                # Read destination objects without fetching or modifying its clone.
                # No source history enters the candidate repository.
                object_path = git(args.destination, 'rev-parse', '--path-format=absolute', '--git-path', 'objects').stdout.decode().strip()
                (objects / '.git/objects/info/alternates').write_text(object_path + '\n', encoding='utf-8')
            timestamp = git(args.source, 'show', '-s', '--format=%ct', commit).stdout.decode().strip()
            identity = dict(ENV, GIT_AUTHOR_NAME='OpenWiz', GIT_COMMITTER_NAME='OpenWiz',
                            GIT_AUTHOR_EMAIL='noreply@github.com', GIT_COMMITTER_EMAIL='noreply@github.com',
                            GIT_AUTHOR_DATE=timestamp + ' +0000', GIT_COMMITTER_DATE=timestamp + ' +0000')
            candidate = git(objects, '-c', 'commit.gpgSign=false', 'commit-tree', new_tree, *(['-p', parent] if parent else []),
                            data=b'Update skills copy from OpenWiz\n', env=identity).stdout.decode().strip()
            result['proposed_commit'] = candidate
            if args.publish:
                git(objects, 'update-ref', 'refs/heads/candidate', candidate)
                git(args.destination, 'fetch', '--no-tags', str(objects), 'refs/heads/candidate')
                # Ordinary fast-forward only, explicit ref, no retries, tags or hooks.
                git(args.destination, '-c', 'core.hooksPath=/dev/null', 'push', '--no-follow-tags',
                    'origin', candidate + ':refs/heads/main')
                published = git(args.destination, 'ls-remote', '--exit-code', 'origin', 'refs/heads/main').stdout.decode().strip()
                if published != candidate + '\trefs/heads/main':
                    raise Refusal('Push outcome could not be verified; inspect destination before retrying')
                result['published'] = candidate
        if args.output:
            if args.output.exists() or args.output.is_symlink():
                raise Refusal('--output must not exist')
            shutil.copytree(output, args.output, symlinks=True)
        print(json.dumps(result, indent=2))
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.cwd())
    parser.add_argument('--commit', default='HEAD', help='immutable source commit/ref')
    parser.add_argument('--version', required=True,
                        help='WizSkills version; must equal plugin.json and the latest CHANGELOG.md section')
    parser.add_argument('--destination', type=Path, help='dedicated openwizdev/WizSkills clone; dry-run reads cached main')
    parser.add_argument('--output', type=Path, help='save checked tree to a new directory')
    parser.add_argument('--literals', type=Path, help='private deny list; required automatically on ClosedWiz')
    parser.add_argument('--publish', action='store_true', help='requires separate publication approval')
    args = parser.parse_args()
    try:
        return run(args)
    except Refusal as error:
        print('skills-copy: ' + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, UnicodeError, RuntimeError):
        # Paths and external stderr can contain private content. Do not echo them.
        print('skills-copy: refused; invalid/unreadable input or failed Git operation', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
