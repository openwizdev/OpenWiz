#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import install
from install import require

SCHEMA = 'openwiz.hot-update.v1'
KERNEL = ('kernel', 'kernel')
VERSION = re.compile(r'(?:0|[1-9][0-9]*)(?:\.(?:0|[1-9][0-9]*)){2}')
ID = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')


def matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=install.unique)


def read_set(path):
    if not os.path.lexists(path):
        return dict(schema=SCHEMA, record='installed-set', access='owner-only', components=[]), None
    install.private(path, False)
    require(stat.S_IMODE(path.stat().st_mode) == 0o600, 'installed-set mode must be 0600')
    value = read_json(path)
    install.shape(value, 'schema record access components')
    require((value['schema'], value['record'], value['access']) == (SCHEMA, 'installed-set', 'owner-only')
            and isinstance(value['components'], list), 'invalid installed set')
    rows = {}
    for row in value['components']:
        install.shape(row, 'kind id current last_good history')
        require(row['kind'] in ('kernel', 'skills', 'driver', 'market-item')
                and matches(ID, row['id']) and matches(VERSION, row['current'])
                and matches(VERSION, row['last_good']), 'invalid installed component')
        key = (row['kind'], row['id'])
        require(key not in rows, 'duplicate installed component')
        require(isinstance(row['history'], list) and len(row['history']) <= 5, 'invalid installed history')
        for entry in row['history']:
            install.shape(entry, 'version result')
            require(matches(VERSION, entry['version']) and entry['result'] in ('good', 'health-failed', 'pulled'),
                    'invalid installed history entry')
        rows[key] = row
    return value, rows.get(KERNEL)


def write_set(path, value):
    data = (json.dumps(value, indent=2) + '\n').encode()
    with tempfile.TemporaryDirectory(prefix='.installed-set-', dir=path.parent) as folder:
        staged = Path(folder) / path.name
        install.write(staged, data)
        os.replace(staged, path)
        install.sync(path.parent)


def build_manifest(build):
    install.private(build)
    manifest = build / 'install-manifest.json'
    install.private(manifest, False)
    return manifest


def inspect_build(build, target=None, *, staged=False, verify=True):
    path = build_manifest(build)
    raw = path.read_bytes()
    if target is None:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=install.unique)
        target = value.get('target') if isinstance(value, dict) else None
    value, assets, raw = install.manifest_at(path, install.sha(raw), target, selected=not staged)
    require(value['source'] == build.name and matches(VERSION, value['version']), 'invalid build identity')
    if verify:
        install.verify_installed(build, assets, raw)
    return value


def find_build(builds, version, target):
    matches_version = []
    for build in builds.iterdir():
        if install.digest(build.name, 40):
            try:
                identity = read_json(build_manifest(build))
            except (OSError, ValueError, install.Refused):
                continue
            if isinstance(identity, dict) and (identity.get('version'), identity.get('target')) == (version, target):
                matches_version.append(build)
    require(len(matches_version) == 1, 'missing or ambiguous versioned build')
    return matches_version[0]


def verify_candidate(candidate, manifest, archive):
    value = read_json(manifest)
    install.shape(value, 'schema record kind id version sha256')
    require((value['schema'], value['record'], value['kind'], value['id'], value['version'])
            == (SCHEMA, 'component-manifest', *KERNEL, candidate['version']), 'kernel component identity mismatch')
    require(install.digest(value['sha256']) and value['sha256'] == candidate['archive_sha256'],
            'component and installer archive checksums disagree')
    assets = {asset['path']: asset for asset in candidate['assets']}
    with archive.open('rb') as stream:
        require(os.fstat(stream.fileno()).st_size == candidate['archive_bytes'], 'archive size mismatch')
        require(stream_sha256(stream) == value['sha256'], 'archive checksum mismatch')
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode='r:gz') as bundle:
            for member in bundle:
                asset = assets.pop(member.name, None)
                require(asset is not None and member.isfile() and not member.pax_headers
                        and member.size == asset['bytes'] and member.mode == int(asset['mode'], 8),
                        'archive asset mismatch')
                with bundle.extractfile(member) as payload:
                    require(stream_sha256(payload) == asset['sha256'], 'archive asset mismatch')
    require(not assets, 'incomplete archive')


def stream_sha256(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def swap_kernel(root, *, state_root=None, manifest=None, archive=None, source=None, back=False):
    require((back and manifest is None and archive is None and source is None)
            or (not back and manifest is not None and archive is not None and install.digest(source, 40)),
            'use --back alone or provide --manifest, --archive and --source')
    root = Path(root)
    state = Path(state_root) if state_root is not None else root / 'state'
    install.path_guard(root)
    install.private(root)
    with os.fdopen(os.open(root / 'install.lock', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as lock:
        meta = os.fstat(lock.fileno())
        require(stat.S_ISREG(meta.st_mode) and stat.S_IMODE(meta.st_mode) == 0o600
                and meta.st_uid == os.getuid() and meta.st_nlink == 1, 'invalid installer lock')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return swap_locked(root, state, manifest, archive, source, back)


def swap_locked(root, state, manifest, archive, source, back):
    builds = state / 'service/builds'
    install.path_guard(builds)
    for folder in (state, builds.parent, builds):
        install.private(folder)
    require(stat.S_IMODE(state.stat().st_mode) == 0o700, 'installer state mode must be 0700')
    link = root / 'current'
    require(link.is_symlink() and link.lstat().st_uid == os.getuid(), 'foreign current selection')
    selected = link.readlink()
    require(selected.parent == builds and install.digest(selected.name, 40), 'foreign current selection')
    old = inspect_build(selected, verify=not back)
    version, target = old['version'], old['target']
    record = state / 'installed-set.json'
    value, row = read_set(record)
    if back:
        require(row is not None and version in (row['current'], row['last_good']),
                'current selection disagrees with the installed set')
        restored = find_build(builds, row['last_good'], target)
        inspect_build(restored, target)
        if selected != restored:
            install.activate_link(restored, root)
        row['current'] = row['last_good']
        write_set(record, value)
        return row

    if row is None:
        row = dict(kind=KERNEL[0], id=KERNEL[1], current=version, last_good=version, history=[])
        value['components'].append(row)
    require(row['current'] == version, 'interrupted selection; restore with --back')
    require(version == row['last_good'] or row['history'][:1] == [{'version': version, 'result': 'good'}],
            'current build awaits health confirmation; verify it or restore with --back')
    candidate = builds / source
    new = inspect_build(candidate, target, staged=True)
    verify_candidate(new, Path(manifest), Path(archive))
    if candidate == selected:
        return row
    require(new['version'] != version, 'cannot replace an existing version with a different build')
    find_build(builds, new['version'], target)
    find_build(builds, version, target)
    row.update(current=new['version'], last_good=version)
    write_set(record, value)
    install.activate_link(candidate, root)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description='Select a verified staged kernel or restore the recorded fallback.')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--manifest', type=Path, help='verified kernel component manifest')
    parser.add_argument('--archive', type=Path, help='exact payload used to stage the build')
    parser.add_argument('--source', help='source commit of the staged build')
    parser.add_argument('--back', action='store_true', help='restore the recorded last good build')
    try:
        swap_kernel(**vars(parser.parse_args(argv)))
    except (OSError, ValueError, EOFError, tarfile.TarError, install.Refused) as error:
        reason = str(error) if isinstance(error, install.Refused) else 'invalid input or filesystem error'
        print(f'kernel swap refused: {reason}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
