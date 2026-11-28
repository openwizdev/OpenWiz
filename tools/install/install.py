#!/usr/bin/env python3
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
import tempfile

DESCRIPTION = """Verified, offline package installation. Python 3.9+; no Cargo, npm or network.

Transport supplies a manifest, its separately checked checksum, and an archive.
Checksums establish integrity, not a signed publisher identity. No program from
an archive is run while validating or installing it.
"""

TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu', 'aarch64-unknown-linux-gnu')
VERSION_RE = re.compile(r'0\.[0-9]+\.[0-9]+')
RC_VERSION_RE = re.compile(r'0\.[0-9]+\.[0-9]+-rc\.[0-9]+')
EARLY_VERSION_RE = re.compile(r'0\.[0-9]+\.[0-9]+(?:-rc\.[0-9]+)?')
SEMVER_RE = re.compile(r'^(0)\.([0-9]+)\.([0-9]+)(?:-rc\.([0-9]+))?$')
CHANNELS = {
    'packaged': b'{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n',
    'early': b'{"schema":"openwiz.update-channel.v1","channel":"early"}\n',
}
EARLY_RELEASE_SCHEMA = 'openwiz.early-release.v1'
PROGRAMS = {'openwiz'}
REQUIRED = PROGRAMS | {'runtime/openwiz-build.txt', 'runtime/install.py', 'runtime/pull.py',
    'runtime/skills/setup/SKILL.md', 'runtime/skills/grill/SKILL.md',
    'runtime/skills/to-tickets/SKILL.md', 'runtime/skills/launch-fleet/SKILL.md',
    'runtime/skills/launch-fleet/scripts/fleet.sh',
    'runtime/setup/setup.py', 'runtime/setup/store.py', 'runtime/setup/github_login.py',
    'runtime/github-app/setup.py',
    'runtime/github-app/app.py', 'runtime/github-app/manifest.json',
    'runtime/cloudroom/cloudroom.py',
    'runtime/setup/init.py'}
LEGACY_PROGRAMS = PROGRAMS | {'openwiz-service', 'openwiz-server'}
LEGACY_REQUIRED = REQUIRED | LEGACY_PROGRAMS | {'web/openwiz-build.txt', 'web/index.html', 'web/setup.html'}
PREVIOUS_SKILLS = {'runtime/skills/to-tickets/SKILL.md': 'runtime/skills/plan-graph/SKILL.md'}


def previous(required):
    return {PREVIOUS_SKILLS.get(path, path) for path in required}


class Refused(Exception):
    pass


def require(value, reason):
    if not value:
        raise Refused(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate manifest key')
        result[key] = value
    return result


def shape(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()), 'unexpected manifest shape')


def digest(value, length=64):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{%d}' % length, value) is not None


def safe(path, legacy=False):
    require(isinstance(path, str) and re.fullmatch(r'[A-Za-z0-9_+./-]+', path), 'unsafe asset path')
    require(not path.startswith('/') and all(p not in ('', '.', '..') and not p.startswith('.')
            for p in path.split('/')), 'unsafe asset path')
    require(path in (LEGACY_PROGRAMS if legacy else PROGRAMS)
            or path.startswith(('runtime/', 'web/') if legacy else 'runtime/'), 'unknown asset role')
    return path


def manifest_at(path, checksum, target, selected=False):
    data = path.read_bytes()
    require(len(data) <= 4 * 1024 * 1024 and sha(data) == checksum, 'manifest checksum mismatch')
    value = json.loads(data, object_pairs_hook=unique)
    shape(value, 'schema version source target setup_api archive archive_sha256 archive_bytes assets')
    require(value['schema'] == 'openwiz.install.v1', 'unsupported manifest schema')
    require(isinstance(value['version'], str) and VERSION_RE.fullmatch(value['version']), 'invalid version')
    require(digest(value['source'], 40), 'invalid source identity')
    require(target in TARGETS and value['target'] == target, 'unsupported or mismatched target')
    require(type(value['setup_api']) is int and value['setup_api'] == 1, 'incompatible setup API')
    require(isinstance(value['archive'], str) and re.fullmatch(r'[A-Za-z0-9_.-]+\.tar\.gz', value['archive']), 'invalid archive name')
    require(digest(value['archive_sha256']), 'invalid archive hash')
    require(type(value['archive_bytes']) is int and value['archive_bytes'] > 0, 'invalid archive size')
    require(type(value['assets']) is list and value['assets'], 'empty asset list')
    legacy = selected and any(type(item) is dict and (item.get('path') in LEGACY_PROGRAMS - PROGRAMS
                              or str(item.get('path')).startswith('web/')) for item in value['assets'])
    programs = LEGACY_PROGRAMS if legacy else PROGRAMS
    assets = {}
    for item in value['assets']:
        shape(item, 'path sha256 bytes mode')
        path = safe(item['path'], legacy)
        require(path not in assets and not any(path.startswith(p + '/') or p.startswith(path + '/') for p in assets),
                'duplicate or overlapping asset')
        require(digest(item['sha256']) and type(item['bytes']) is int and item['bytes'] >= 0, 'invalid asset identity')
        require(item['mode'] == ('0700' if path in programs or path.endswith('.sh')
                                 or re.fullmatch(r'runtime/adapters/[a-z0-9-]+/driver', path) else '0600'),
                'invalid asset mode')
        assets[path] = item
    required = LEGACY_REQUIRED if legacy else REQUIRED
    layouts = (required, previous(required)) if selected else (required,)
    require(any(layout <= assets.keys() for layout in layouts), 'incomplete program or skill runtime')
    identity = f"openwiz.package.v1\n{value['version']}\n{value['source']}\n{target}\n".encode()
    for stamp in ('runtime/openwiz-build.txt', 'web/openwiz-build.txt') if legacy else ('runtime/openwiz-build.txt',):
        require(assets[stamp]['sha256'] == sha(identity) and assets[stamp]['bytes'] == len(identity),
                'runtime build identity mismatch')
    return value, assets, data


def private(path, directory=True):
    meta = path.lstat()
    require((stat.S_ISDIR(meta.st_mode) if directory else stat.S_ISREG(meta.st_mode))
            and meta.st_uid == os.getuid() and meta.st_mode & 0o077 == 0
            and (directory or meta.st_nlink == 1), 'path must be private, owned and have the expected type')


def path_guard(path):
    require(path.is_absolute() and '..' not in path.parts and '.' not in path.parts, 'absolute plain path required')
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            require(not parent.is_symlink() and parent.is_dir(), 'symlink or non-directory ancestor')


def directory(path):
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    private(path)


def sync(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write(path, data, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def verify_installed(build, assets, raw):
    private(build)
    require((build / 'install-manifest.json').read_bytes() == raw, 'existing source has a different manifest')
    actual = set()
    for parent, dirs, files in os.walk(build, followlinks=False):
        private(Path(parent))
        for name in dirs:
            private(Path(parent) / name)
        for name in files:
            file = Path(parent) / name
            private(file, False)
            relative = file.relative_to(build).as_posix()
            if relative != 'install-manifest.json':
                actual.add(relative)
                require(relative in assets and sha(file.read_bytes()) == assets[relative]['sha256']
                        and file.stat().st_size == assets[relative]['bytes']
                        and stat.S_IMODE(file.stat().st_mode) == int(assets[relative]['mode'], 8), 'installed asset mismatch')
    require(actual == set(assets), 'installed asset set mismatch')


def damaged(build, assets, raw):
    try:
        verify_installed(build, assets, raw)
        return None
    except (Refused, OSError):
        meta = build.lstat()
        require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid(), 'a foreign build is in the way')
        os.chmod(build, 0o700)
        stored = build / 'install-manifest.json'
        try:
            require(not (stored.exists() or stored.is_symlink())
                    or (stored.is_file() and not stored.is_symlink() and stored.read_bytes() == raw),
                    'existing source has a different manifest')
        except BaseException:
            os.chmod(build, stat.S_IMODE(meta.st_mode))
            raise
        return meta


def same_directory(path, meta):
    try:
        now = path.lstat()
    except OSError:
        return False
    return (now.st_dev, now.st_ino) == (meta.st_dev, meta.st_ino)


def repair_backups(builds, source, raw):
    found = sorted(builds.glob('.damaged-*-' + source))
    for backup in found:
        meta = backup.lstat()
        require(stat.S_ISDIR(meta.st_mode) and meta.st_uid == os.getuid(), 'a foreign repair backup is in the way')
        stored = backup / 'install-manifest.json'
        require(stored.is_file() and not stored.is_symlink() and stored.read_bytes() == raw,
                'existing source has a different manifest in its repair backup ' + backup.name)
    return found


def stage_private(path, data, prefix):
    temporary = path.parent / (prefix + str(os.getpid()))
    temporary.unlink(missing_ok=True)
    write(temporary, data)
    return temporary


def replace_private(path, data, prefix):
    temporary = stage_private(path, data, prefix)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def semver_key(version):
    match = SEMVER_RE.fullmatch(version) if isinstance(version, str) else None
    require(match, 'invalid release version')
    major, minor, patch = int(match[1]), int(match[2]), int(match[3])
    return (major, minor, patch, 1, 0) if match[4] is None else (major, minor, patch, 0, int(match[4]))


def early_release_bytes(version, source, next_entry=None):
    payload = {'schema': EARLY_RELEASE_SCHEMA, 'version': version, 'source': source}
    if next_entry is not None:
        payload['next'] = next_entry
    return (json.dumps(payload, separators=(',', ':')) + '\n').encode('ascii')


def _rc_or_none(value, allow_none=False):
    if value is None and allow_none:
        return None
    require(isinstance(value, str) and RC_VERSION_RE.fullmatch(value), 'invalid early release version')
    return value


def read_early_release(path, expected_version=None, expected_source=None, allow_transition=False):
    private(path, False)
    data = json.loads(path.read_bytes(), object_pairs_hook=unique)
    require(type(data) is dict, 'unexpected early release metadata')
    keys = set(data)
    if keys == {'schema', 'version', 'source'}:
        require(data['schema'] == EARLY_RELEASE_SCHEMA, 'unsupported early release metadata')
        version = _rc_or_none(data['version'], allow_none=False)
        require(digest(data['source'], 40), 'invalid early release source')
        if expected_source is not None:
            require(data['source'] == expected_source, 'early release source does not match manifest source')
        if expected_version is not None:
            require(version.split('-rc.', 1)[0] == expected_version,
                    'early release version does not match manifest version')
        return version
    require(allow_transition and keys == {'schema', 'version', 'source', 'next'},
            'unsupported early release metadata')
    require(data['schema'] == EARLY_RELEASE_SCHEMA, 'unsupported early release metadata')
    cur_version = _rc_or_none(data['version'], allow_none=True)
    require(digest(data['source'], 40), 'invalid early release source')
    nxt = data['next']
    shape(nxt, 'version source')
    nxt_version = _rc_or_none(nxt['version'], allow_none=True)
    require(digest(nxt['source'], 40) and nxt['source'] != data['source'], 'invalid early release source')
    require(cur_version is not None or nxt_version is not None, 'invalid early release metadata')
    if expected_source is None:
        return nxt_version or cur_version
    if expected_source == data['source']:
        chosen = cur_version
    elif expected_source == nxt['source']:
        chosen = nxt_version
    else:
        raise Refused('early release source does not match manifest source')
    if chosen is None:
        return expected_version
    if expected_version is not None:
        require(chosen.split('-rc.', 1)[0] == expected_version,
                'early release version does not match manifest version')
    return chosen


ROOT_ENTRIES = re.compile(r'current|channel\.json|early-release\.json|install\.lock|skills|contracts|\.claude-plugin|state'
                          r'|\.(?:current|channel|early-release|early-release-final)-[0-9]+')
STATE_ENTRIES = (('', re.compile(r'setup|cloudroom|service')),
                 ('service', re.compile(r'config\.json|app|state\.json|loops|clone|builds')),
                 ('service/builds', re.compile(r'[0-9a-f]{40}|\.stage-[A-Za-z0-9_]+|\.damaged-[0-9]+-[0-9a-f]{40}')))


def entries(folder):
    return sorted(os.listdir(folder)) if folder.is_dir() and not folder.is_symlink() else []


def previous_state(root, state_root):
    builds = state_root / 'service/builds'
    if (root / 'current').is_symlink() and Path(os.readlink(root / 'current')).parent == builds:
        return True
    for name in entries(builds):
        try:
            if digest(name, 40) and (builds / name / 'install-manifest.json').is_file():
                return True
        except OSError:
            pass
    return False


def only_ours(root, state_root):
    unexpected = 'it is not OpenWiz\'s, so nothing was changed. Give install a new or empty folder'
    if not (os.path.lexists(root / 'current') or os.path.lexists(root / 'channel.json')):
        for name in entries(root):
            require(ROOT_ENTRIES.fullmatch(name), '%s is already there and %s' % (root / name, unexpected))
            if name == 'early-release.json':
                try:
                    read_early_release(root / name, allow_transition=True)
                except (Refused, OSError, ValueError):
                    raise Refused('%s is already there and %s' % (root / name, unexpected)) from None
    if not previous_state(root, state_root):
        for folder, names in STATE_ENTRIES:
            for name in entries(state_root / folder if folder else state_root):
                require(names.fullmatch(name), '%s is already there and %s' % (state_root / folder / name, unexpected))


def activate_link(build, root):
    temporary = root / ('.current-' + str(os.getpid()))
    os.symlink(build, temporary)
    try:
        os.replace(temporary, root / 'current')
        sync(root)
    finally:
        temporary.unlink(missing_ok=True)


def install(manifest, archive, manifest_sha256, root, target, state_root=None,
            free_bytes=lambda path: shutil.disk_usage(path).free, activate=activate_link, stage_only=False,
            channel='packaged', release_version=None):
    require(channel in CHANNELS, 'unsupported update channel')
    manifest, archive, root = Path(manifest), Path(archive), Path(root)
    value, assets, raw = manifest_at(manifest, manifest_sha256, target)
    if release_version is not None:
        require(channel == 'early' and isinstance(release_version, str)
                and RC_VERSION_RE.fullmatch(release_version), 'invalid early release version')
        require(release_version.split('-rc.', 1)[0] == value['version'],
                'early release version does not match manifest version')
    require(archive.stat().st_size == value['archive_bytes'], 'archive size mismatch')
    hasher = hashlib.sha256()
    with archive.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    require(hasher.hexdigest() == value['archive_sha256'], 'archive checksum mismatch')
    path_guard(root)
    require(root.parent.is_dir(), 'installation parent must exist')
    only_ours(root, Path(state_root) if state_root else root / 'state')
    directory(root)
    lock_path = root / 'install.lock'
    if lock_path.exists() or lock_path.is_symlink():
        private(lock_path, False)
    with lock_path.open('a+b') as lock:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        private(root)
        state_root = Path(state_root) if state_root else root / 'state'
        path_guard(state_root)
        directory(state_root)
        directory(state_root / 'service')
        builds = state_root / 'service/builds'
        directory(builds)
        link = root / 'current'
        selected = None
        if link.exists() or link.is_symlink():
            require(link.is_symlink() and link.lstat().st_uid == os.getuid(), 'foreign current selection')
            selected = Path(os.readlink(link))
            require(selected.is_absolute() and selected.parent == builds and digest(selected.name, 40), 'foreign current selection')
            if selected != builds / value['source']:
                private(selected)
        channel_file = root / 'channel.json'
        require(channel_file.exists() or not link.is_symlink(), 'source installation requires an explicit channel migration')
        channel_bytes = CHANNELS[channel]
        existing_channel_name = None
        migrate_packaged = False
        if channel_file.exists() or channel_file.is_symlink():
            private(channel_file, False)
            existing_channel = channel_file.read_bytes()
            if existing_channel == CHANNELS['packaged']:
                existing_channel_name = 'packaged'
            elif existing_channel == CHANNELS['early']:
                existing_channel_name = 'early'
            if channel == 'early' and existing_channel_name == 'packaged':
                migrate_packaged = True
            else:
                require(existing_channel == channel_bytes, 'existing update channel requires explicit migration')
        build = builds / value['source']
        early_file = root / 'early-release.json'
        early_exists = early_file.exists() or early_file.is_symlink()
        new_version = release_version or value['version']
        owns_early_file = False
        old_rc = None
        if selected is not None:
            if selected != build:
                old_manifest_path = selected / 'install-manifest.json'
                private(old_manifest_path, False)
                old_raw = old_manifest_path.read_bytes()
                old_target = json.loads(old_raw, object_pairs_hook=unique).get('target')
                old_manifest = manifest_at(old_manifest_path, sha(old_raw), old_target, selected=True)[0]
                require(old_manifest['source'] == selected.name, 'selected build source mismatch')
                old_manifest_version = old_manifest['version']
            else:
                old_manifest_version = value['version']
            if existing_channel_name == 'early':
                if early_exists:
                    old_version = read_early_release(early_file, expected_version=old_manifest_version,
                                                     expected_source=selected.name, allow_transition=True)
                    owns_early_file = True
                    old_rc = old_version if RC_VERSION_RE.fullmatch(old_version) else None
                else:
                    old_version = old_manifest_version
            else:
                old_version = old_manifest_version
                if migrate_packaged and early_exists:
                    require(release_version is not None, 'unrelated early-release.json blocks early channel migration')
                    matched = read_early_release(early_file, expected_version=value['version'],
                                                 expected_source=value['source'])
                    require(matched == release_version, 'unrelated early-release.json blocks early channel migration')
            if not stage_only:
                require(semver_key(new_version) >= semver_key(old_version),
                        'refusing to downgrade from %s to %s' % (old_version, new_version))
        elif early_exists and channel == 'early':
            read_early_release(early_file, allow_transition=True)
        with tarfile.open(archive, 'r:gz') as tar:
            members = []
            seen = set()
            for member in tar:
                require(len(members) < len(assets), 'archive asset count mismatch')
                members.append(member)
                path = safe(member.name)
                require(member.isfile() and not member.pax_headers and path not in seen and path in assets,
                        'unsafe, duplicate or unlisted archive member')
                item = assets[path]
                require(member.size == item['bytes'] and member.mode == int(item['mode'], 8), 'archive asset metadata mismatch')
                seen.add(path)
            require(seen == set(assets), 'incomplete archive')
            damaged_meta = damaged(build, assets, raw) if build.exists() or build.is_symlink() else None
            repair = damaged_meta is not None
            if repair or not (build.exists() or build.is_symlink()):
                try:
                    backups = repair_backups(builds, value['source'], raw)
                    needed = sum(item['bytes'] for item in assets.values()) + len(raw)
                    require(free_bytes(builds) >= needed, 'insufficient disk space')
                    temporary = Path(tempfile.mkdtemp(prefix='.stage-', dir=builds))
                    try:
                        for member in members:
                            item = assets[member.name]
                            stream = tar.extractfile(member)
                            hasher = hashlib.sha256()
                            destination = temporary / member.name
                            for parent in reversed(destination.parent.relative_to(temporary).parents):
                                directory(temporary / parent)
                            directory(destination.parent)
                            with destination.open('xb') as out:
                                os.chmod(destination, int(item['mode'], 8))
                                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                                    hasher.update(chunk)
                                    out.write(chunk)
                                out.flush()
                                os.fsync(out.fileno())
                            require(hasher.hexdigest() == item['sha256'], 'asset checksum mismatch')
                        write(temporary / 'install-manifest.json', raw)
                        verify_installed(temporary, assets, raw)
                        for parent, _, _ in os.walk(temporary, topdown=False):
                            sync(Path(parent))
                        if repair:
                            aside = builds / ('.damaged-%d-%s' % (os.getpid(), value['source']))
                            os.rename(build, aside)
                            try:
                                os.rename(temporary, build)
                            except BaseException:
                                os.rename(aside, build)
                                raise
                            backups.append(aside)
                        else:
                            os.rename(temporary, build)
                        sync(builds)
                        verify_installed(build, assets, raw)
                        for backup in backups:
                            shutil.rmtree(backup, ignore_errors=True)
                    finally:
                        if temporary.exists():
                            shutil.rmtree(temporary)
                except BaseException:
                    if damaged_meta is not None and same_directory(build, damaged_meta):
                        os.chmod(build, stat.S_IMODE(damaged_meta.st_mode))
                    raise
        if not stage_only:
            def restore_early():
                try:
                    if old_rc is not None:
                        replace_private(early_file, early_release_bytes(old_rc, selected.name), '.early-release-')
                    else:
                        early_file.unlink(missing_ok=True)
                    sync(root)
                except BaseException:
                    pass

            if not channel_file.exists() or selected is None:
                if release_version:
                    replace_private(early_file, early_release_bytes(release_version, value['source']),
                                    '.early-release-')
                if not channel_file.exists():
                    write(channel_file, channel_bytes)
                sync(root)
                activate(build, root)
            elif migrate_packaged:
                created_early = False
                tmp_channel = stage_private(channel_file, channel_bytes, '.channel-')
                try:
                    if release_version and not early_exists:
                        replace_private(early_file, early_release_bytes(release_version, value['source']),
                                        '.early-release-')
                        created_early = True
                    sync(root)
                    activate(build, root)
                    try:
                        os.replace(tmp_channel, channel_file)
                        sync(root)
                    except BaseException:
                        try:
                            activate(selected, root)
                        except BaseException:
                            pass
                        raise
                except BaseException:
                    if created_early:
                        early_file.unlink(missing_ok=True)
                    raise
                finally:
                    tmp_channel.unlink(missing_ok=True)
            elif channel == 'early':
                if selected == build:
                    activate(build, root)
                    if release_version:
                        replace_private(early_file, early_release_bytes(release_version, value['source']),
                                        '.early-release-')
                        sync(root)
                    elif owns_early_file:
                        early_file.unlink()
                        sync(root)
                elif release_version or old_rc is not None:
                    transition = early_release_bytes(
                        old_rc, selected.name,
                        next_entry={'version': release_version, 'source': value['source']})
                    final_tmp = (stage_private(early_file, early_release_bytes(release_version, value['source']),
                                               '.early-release-final-')
                                 if release_version else None)
                    try:
                        replace_private(early_file, transition, '.early-release-')
                        sync(root)
                        try:
                            activate(build, root)
                        except BaseException:
                            restore_early()
                            raise
                        try:
                            if final_tmp is not None:
                                os.replace(final_tmp, early_file)
                            else:
                                early_file.unlink()
                            sync(root)
                        except BaseException:
                            try:
                                activate(selected, root)
                            except BaseException:
                                pass
                            else:
                                restore_early()
                            raise
                    finally:
                        if final_tmp is not None:
                            final_tmp.unlink(missing_ok=True)
                else:
                    if owns_early_file:
                        early_file.unlink()
                        sync(root)
                    activate(build, root)
            else:
                activate(build, root)
        return {'schema': 'openwiz.install-result.v1', 'version': release_version or value['version'],
                'source': value['source'], 'target': target, 'build': str(build), 'state_root': str(state_root),
                'activated': not stage_only, 'repaired': repair}


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    for flag in ('manifest', 'archive', 'manifest-sha256', 'root', 'target'):
        parser.add_argument('--' + flag, required=True)
    parser.add_argument('--state-root')
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--channel', choices=tuple(CHANNELS), default='packaged')
    parser.add_argument('--release-version')
    args = vars(parser.parse_args())
    try:
        result = install(**args)
        print(json.dumps(result, separators=(',', ':')), flush=True)
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        print('openwiz-install: refused; last-good selection and owner settings retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
