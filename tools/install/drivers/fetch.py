#!/usr/bin/env python3
"""Find, check, ask and install a driver package.

The user's add is the yes for a first-party pin. A verified listing needs
``--answer yes``. A listed driver needs ``--answer install-unverified`` after
the warning. Nothing from the archive runs before those checks and that yes.
"""
import argparse
import datetime
import gzip
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import ssl
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse

sys.dont_write_bytecode = True

DESCRIPTION = """Install a driver that is not in the kernel.

add NAME --root ROOT --build BUILD --market-commit SHA [--answer ANSWER]
list --root ROOT
update --root ROOT --build BUILD --market-commit SHA [--answer ANSWER]
"""

KIT_FILES = (
    'kernel/driver-kit/kit.py',
    'kernel/driver-kit/schema.json',
    'kernel/records-kit/check.py',
    'kernel/driver-kit/hostkey.py',
    'kernel/driver-kit/hosts.json',
    'wizskills.lock',
    'openwiz-build.txt',
)
ASSET_HOSTS = frozenset({
    'github.com',
    'release-assets.githubusercontent.com',
    'objects.githubusercontent.com',
})
CDN_HOSTS = frozenset({
    'release-assets.githubusercontent.com',
    'objects.githubusercontent.com',
})
READ_HOSTS = ASSET_HOSTS | {'api.github.com', 'raw.githubusercontent.com'}
REQUIRED = {'driver': '0700', 'schema.json': '0600', 'README.md': '0600'}
PRIORITY = (
    'malformed-archive', 'unsafe-path', 'member-type', 'duplicate-member',
    'extra-file', 'missing-file', 'member-mode', 'member-sha256',
    'driver-name', 'release-identity', 'kit-schema', 'readme',
)
REASONS = {
    'archive-sha256': (
        'the archive does not match the pinned checksum',
        'do not use this release; pick a package whose checksum matches the asset'),
    'checksums': (
        'the checksums file does not match the release assets',
        'do not use this release; its SHA256SUMS does not match the assets'),
    'malformed-archive': (
        'the archive is not a valid driver package',
        'do not use this release; it must be a gzip USTAR of the three files'),
    'unsafe-path': (
        'the archive contains an unsafe path',
        'do not use this release; members must be the three root file names'),
    'member-type': (
        'the archive contains a member that is not a regular file',
        'do not use this release; every member must be a regular file'),
    'duplicate-member': (
        'the archive repeats a file',
        'do not use this release; each file must appear once'),
    'extra-file': (
        'the archive has a file the manifest does not name',
        'do not use this release; it must contain only driver, schema.json and README.md'),
    'missing-file': (
        'the archive is missing a file the manifest names',
        'do not use this release; it must contain driver, schema.json and README.md'),
    'member-mode': (
        'a file in the archive has the wrong mode',
        'do not use this release; driver must be mode 0700 and the data files 0600'),
    'member-sha256': (
        'a file in the archive does not match the manifest hash',
        'do not use this release; its files were changed after the manifest'),
    'driver-name': (
        'the driver name does not match the host you picked',
        'pick the host name this package declares; nothing was installed'),
    'release-identity': (
        'the manifest does not match the pinned release',
        'do not use this release; its version and kit commit must match the pin'),
    'kit-schema': (
        "schema.json does not match this build's driver kit",
        "run openwiz update, or install a driver release made with this build's kit"),
    'readme': (
        'the README does not declare one login line and one abilities line',
        'do not use this release; its README must name the login and the abilities'),
    'asset-repository': (
        "the asset URL is not this repository's release",
        "do not use this listing; its asset must be the repository's own driver.tar.gz"),
}
DRIVER = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
VERSION = re.compile(r'^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')
SHA = re.compile(r'^[0-9a-f]{64}$')
PUBLISHER = re.compile(r'^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$')
REPOSITORY = re.compile(r'^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*/[A-Za-z0-9_-][A-Za-z0-9_.-]*$')
ASSET_URL = re.compile(
    r'^https://github\.com/[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*/'
    r'[A-Za-z0-9_-][A-Za-z0-9_.-]*/releases/download/'
    r'v(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)/driver\.tar\.gz$')
RECEIPT_PATH = re.compile(r'^receipts/[a-z0-9-]+/[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9a-f]{12}\.txt$')
LIMIT = 8 * 1024 * 1024


class Refused(Exception):
    def __init__(self, error, next_step):
        self.error, self.next = error, next_step
        if '\n' in error or '\n' in next_step or not 1 <= len(error) <= 300 or not 1 <= len(next_step) <= 300:
            raise ValueError('bad refusal')


class Malformed(Exception):
    pass


def refuse_reason(kind):
    raise Refused(*REASONS[kind])


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate field')
        value[key] = item
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load_json(raw):
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8')
    return json.loads(raw, object_pairs_hook=unique)


def version_key(value):
    return tuple(int(part) for part in value.split('.'))


def release_url(package):
    return 'https://github.com/%s/releases/download/v%s/driver.tar.gz' % (
        package['repository'], package['version'])


def package_shape(package):
    fields = ('driver', 'version', 'repository', 'commit', 'asset_url', 'sha256', 'kit_commit')
    if not isinstance(package, dict) or set(package) != set(fields):
        return False
    return bool(
        isinstance(package['driver'], str) and DRIVER.fullmatch(package['driver'])
        and isinstance(package['version'], str) and VERSION.fullmatch(package['version'])
        and isinstance(package['repository'], str) and REPOSITORY.fullmatch(package['repository'])
        and isinstance(package['commit'], str) and COMMIT.fullmatch(package['commit'])
        and isinstance(package['asset_url'], str) and ASSET_URL.fullmatch(package['asset_url'])
        and isinstance(package['sha256'], str) and SHA.fullmatch(package['sha256'])
        and isinstance(package['kit_commit'], str) and COMMIT.fullmatch(package['kit_commit']))


def guard(path):
    if not path.is_absolute() or '..' in path.parts or '.' in path.parts:
        raise Refused('the install root must be an absolute path',
                      'pass an absolute --root; nothing was written')
    for parent in (path, *path.parents):
        if parent.exists() or parent.is_symlink():
            if parent.is_symlink() or not parent.is_dir():
                raise Refused('a folder in the install path is a link',
                              'use a real directory you own; nothing was written')


def private(path):
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
        raise Refused('the install root must be a private directory you own',
                      'set it to mode 0700; nothing was written')


def read_regular(path, label):
    if path.is_symlink() or not path.is_file():
        raise Refused('this build is missing %s' % label,
                      'select a complete build; nothing was installed')
    return path.read_bytes()


class Client:
    """HTTPS to GitHub, or the loopback stand-in. The host is still checked."""

    def __init__(self, loopback):
        self.address = None
        if loopback:
            match = re.fullmatch(r'127\.0\.0\.1:([1-9][0-9]{0,4})', loopback)
            port = int(match.group(1)) if match else 0
            if not match or port > 65535:
                raise Refused('the loopback address is not 127.0.0.1:<port>',
                              'pass the fake GitHub as 127.0.0.1 and a port; nothing was installed')
            self.address = ('127.0.0.1', port)
        self.ssl = None if loopback else ssl.create_default_context()

    def get(self, url, role):
        current = url
        for hop in range(4):
            parts = urllib.parse.urlsplit(current)
            self._allow(parts, role, hop)
            target = parts.path or '/'
            if parts.query:
                target += '?' + parts.query
            if self.address:
                conn = http.client.HTTPConnection(self.address[0], self.address[1], timeout=30)
            else:
                conn = http.client.HTTPSConnection(parts.hostname, timeout=30, context=self.ssl)
            try:
                conn.request('GET', target, headers={
                    'Host': parts.hostname,
                    'User-Agent': 'OpenWiz-driver-package-v1',
                    'Accept': '*/*',
                    'Connection': 'close'})
                response = conn.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader('Location')
                    response.read(LIMIT + 1)
                    if not location:
                        break
                    current = urllib.parse.urljoin(current, location)
                    continue
                if response.status != 200:
                    response.read(LIMIT + 1)
                    raise Refused('the pinned release could not be downloaded',
                                  'try again when GitHub answers; nothing was installed')
                length = response.getheader('Content-Length')
                if length is not None and (not length.isdigit() or int(length) > LIMIT):
                    raise Refused('the download is larger than a driver package',
                                  'do not use this release; nothing was installed')
                data = response.read(LIMIT + 1)
            except Refused:
                raise
            except (http.client.HTTPException, OSError, ssl.SSLError, ValueError):
                raise Refused('the pinned release could not be downloaded',
                              'try again when GitHub answers; nothing was installed')
            finally:
                conn.close()
            if len(data) > LIMIT:
                raise Refused('the download is larger than a driver package',
                              'do not use this release; nothing was installed')
            return data
        raise Refused('the download redirected off GitHub',
                      'do not follow that link; the asset must stay on GitHub')

    def _allow(self, parts, role, hop):
        if parts.username or parts.password or parts.fragment or parts.port is not None:
            raise Refused('the download URL carries credentials',
                          'use a release URL with no user name, port or fragment; nothing was installed')
        if parts.scheme != 'https':
            raise Refused('the download switched to an unsecured link',
                          'the release must stay on HTTPS; nothing was installed')
        host = parts.hostname or ''
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise Refused('the download redirected off GitHub',
                          'do not follow that link; the asset must stay on GitHub')
        allowed = ASSET_HOSTS if role == 'asset' else READ_HOSTS
        if host not in allowed or (role == 'asset' and hop == 0 and host != 'github.com'):
            raise Refused('the download redirected off GitHub',
                          'do not follow that link; the asset must stay on GitHub')
        if role == 'read' and hop == 0 and host not in ('api.github.com', 'raw.githubusercontent.com'):
            raise Refused('the download redirected off GitHub',
                          'do not follow that link; the asset must stay on GitHub')
        if parts.query and not (host in CDN_HOSTS or (
                hop == 0 and host == 'api.github.com' and re.fullmatch(r'ref=[0-9a-f]{40}', parts.query))):
            raise Refused('the download URL carries credentials',
                          'use a release URL with no token; nothing was installed')


def manifest_of(raw):
    try:
        value = load_json(raw)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        return None
    files = value.get('files') if isinstance(value, dict) else None
    if not isinstance(value, dict) or set(value) != {
            'driver', 'version', 'driver_contract', 'kit_commit', 'files'}:
        return None
    if value['driver_contract'] != 'openwiz:driver v1' or not isinstance(files, list) or len(files) != 3:
        return None
    if not DRIVER.fullmatch(value['driver']) or not VERSION.fullmatch(value['version']):
        return None
    if not COMMIT.fullmatch(value['kit_commit']):
        return None
    seen = {}
    for item in files:
        if not isinstance(item, dict) or set(item) != {'path', 'mode', 'sha256'}:
            return None
        path, mode, hashed = item['path'], item['mode'], item['sha256']
        if path in seen or path not in REQUIRED or mode != REQUIRED[path] or not SHA.fullmatch(hashed):
            return None
        seen[path] = item
    if set(seen) != set(REQUIRED):
        return None
    value['files'] = seen
    return value


def safe_name(name):
    if not isinstance(name, str) or '\\' in name or name.startswith('/'):
        return False
    parts = name.split('/')
    return bool(parts) and all(part not in ('', '.', '..') for part in parts)


def archive_members(archive):
    try:
        raw = gzip.decompress(archive)
    except OSError as error:
        raise Malformed() from error
    offset = 0
    found = []
    while raw[offset:offset + 512] != bytes(512):
        block = raw[offset:offset + 512]
        if len(block) < 512 or block[257:265] != b'ustar\x0000':
            raise Malformed()
        try:
            member = tarfile.TarInfo.frombuf(block, 'ascii', 'strict')
        except (ValueError, tarfile.TarError) as error:
            raise Malformed() from error
        offset += 512
        end = offset + member.size
        if member.size < 0 or end > len(raw):
            raise Malformed()
        found.append((member, raw[offset:end]))
        offset += ((member.size + 511) // 512) * 512
    if len(raw) - offset < 1024 or any(raw[offset:]):
        raise Malformed()
    return found


def judge(package, manifest, archive, kit_schema):
    failures = set()
    if manifest['driver'] != package['driver']:
        failures.add('driver-name')
    if manifest['version'] != package['version'] or manifest['kit_commit'] != package['kit_commit']:
        failures.add('release-identity')
    seen, readme = set(), None
    try:
        members = archive_members(archive)
    except Malformed:
        return {'malformed-archive'}, None
    for member, data in members:
        path = member.name
        if not safe_name(path):
            failures.add('unsafe-path')
        if path in seen:
            failures.add('duplicate-member')
        seen.add(path)
        if path not in manifest['files']:
            failures.add('extra-file')
        if member.type != tarfile.REGTYPE:
            failures.add('member-type')
            continue
        entry = manifest['files'].get(path)
        if entry is not None:
            if '%04o' % member.mode != entry['mode']:
                failures.add('member-mode')
            if digest(data) != entry['sha256']:
                failures.add('member-sha256')
        if path == 'schema.json' and data != kit_schema:
            failures.add('kit-schema')
        if path == 'README.md':
            readme = data
    if set(REQUIRED) - seen:
        failures.add('missing-file')
    return failures, readme


def readme_of(data, driver):
    try:
        lines = data.decode('utf-8').splitlines()
    except UnicodeError:
        return None
    names = [line[len('Driver: '):] for line in lines if line.startswith('Driver: ')]
    logins = [line[len('Login: '):] for line in lines if line.startswith('Login: ')]
    abilities = [line[len('Abilities: '):] for line in lines if line.startswith('Abilities: ')]
    if names != [driver] or len(logins) != 1 or len(abilities) != 1:
        return None
    can = [part.strip() for part in abilities[0].split(',')]
    if not can or any(not part for part in can):
        return None
    return logins[0], can, abilities[0]


def tag_commit(client, repository, version):
    owner, repo = repository.split('/', 1)
    url = 'https://api.github.com/repos/%s/%s/git/ref/tags/v%s' % (owner, repo, version)
    try:
        body = load_json(client.get(url, 'read'))
    except (UnicodeError, json.JSONDecodeError, ValueError, Refused):
        raise Refused('the release tag does not resolve to the pinned commit',
                      'do not install this package; its tag and commit disagree')
    obj = body.get('object') if isinstance(body, dict) else None
    for _ in range(3):
        if not isinstance(obj, dict):
            break
        kind, sha = obj.get('type'), obj.get('sha')
        if kind == 'commit' and isinstance(sha, str) and COMMIT.fullmatch(sha):
            return sha
        if kind != 'tag' or not isinstance(sha, str) or not COMMIT.fullmatch(sha):
            break
        try:
            peeled = load_json(client.get(
                'https://api.github.com/repos/%s/%s/git/tags/%s' % (owner, repo, sha), 'read'))
        except (UnicodeError, json.JSONDecodeError, ValueError, Refused):
            break
        obj = peeled.get('object') if isinstance(peeled, dict) else None
    raise Refused('the release tag does not resolve to the pinned commit',
                  'do not install this package; its tag and commit disagree')


def prepare(package, publisher, kind, client, kit_schema, receipt_date):
    if not package_shape(package) or not PUBLISHER.fullmatch(publisher):
        raise Refused('the package block is malformed',
                      'do not install this listing; its package block does not match the contract')
    if package['asset_url'] != release_url(package):
        refuse_reason('asset-repository')
    if tag_commit(client, package['repository'], package['version']) != package['commit']:
        raise Refused('the release tag does not resolve to the pinned commit',
                      'do not install this package; its tag and commit disagree')
    base = package['asset_url'][:-len('driver.tar.gz')]
    archive = client.get(package['asset_url'], 'asset')
    manifest_bytes = client.get(base + 'manifest.json', 'asset')
    sums = client.get(base + 'SHA256SUMS', 'asset')
    if digest(archive) != package['sha256']:
        refuse_reason('archive-sha256')
    expect = ('%s  driver.tar.gz\n%s  manifest.json\n' % (digest(archive), digest(manifest_bytes))).encode()
    if sums != expect:
        refuse_reason('checksums')
    manifest = manifest_of(manifest_bytes)
    if manifest is None:
        raise Refused('the manifest does not match the driver package contract',
                      'do not use this release; its manifest must name the three files')
    failures, readme = judge(package, manifest, archive, kit_schema)
    if failures:
        refuse_reason(next(kind for kind in PRIORITY if kind in failures))
    declared = readme_of(readme, package['driver'])
    if declared is None:
        refuse_reason('readme')
    login, can, ability_text = declared
    files = {}
    for member, data in archive_members(archive):
        if member.name in REQUIRED:
            files[member.name] = data
    return {
        'name': package['driver'], 'publisher': publisher, 'version': package['version'],
        'repository': package['repository'], 'sha256': package['sha256'],
        'login': login, 'can': can, 'abilities': ability_text,
        'receipt_date': receipt_date, 'verified': kind == 'verified', 'kind': kind,
        'files': files,
    }


def show(checked, ask):
    lines = []
    if checked['kind'] == 'listed':
        lines.append('Warning: %s has not passed the kit.' % checked['name'])
    lines.extend([
        'Name: ' + checked['name'],
        'Publisher: ' + checked['publisher'],
        'Version: ' + checked['version'],
        'Login: ' + checked['login'],
        'Abilities: ' + checked['abilities'],
    ])
    if checked['receipt_date']:
        lines.append('Receipt: ' + checked['receipt_date'])
    if ask:
        lines.append('This change needs its own yes.')
    elif checked['kind'] == 'listed':
        lines.append('This listed driver needs its own yes.')
    elif checked['kind'] == 'verified':
        lines.append('Confirm this verified driver to install it.')
    print('\n'.join(lines), file=sys.stderr)


def accepted(kind, answer):
    if kind in ('pin', 'move'):
        return True
    if kind == 'verified':
        return answer == 'yes'
    return kind == 'listed' and answer == 'install-unverified'


def gate(checked, answer, ask):
    show(checked, ask)
    if accepted('verified' if ask and checked['verified'] else checked['kind'], answer):
        return
    if checked['kind'] == 'listed' or (ask and not checked['verified']):
        raise Refused('this listed driver has not passed the kit',
                      'say yes to this listed driver on its own, after the warning')
    if ask:
        raise Refused('this change is not covered by the earlier yes',
                      'say yes again after the confirmation; the installed driver was left as it is')
    raise Refused('this verified driver is not installed without a yes',
                  'say yes to install it after the confirmation')


def spawn(program):
    return subprocess.run(
        [str(program), 'version'], cwd=str(program.parent), capture_output=True, timeout=30,
        env={'PATH': '/usr/bin:/bin', 'HOME': '/tmp'})


def stage_and_run(build, checked):
    with tempfile.TemporaryDirectory(prefix='openwiz-driver-') as temporary:
        root = Path(temporary)
        for rel in KIT_FILES:
            source = build / 'runtime' / rel
            data = read_regular(source, rel)
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(target.parent, 0o700)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                os.write(fd, data)
            finally:
                os.close(fd)
            os.chmod(target, 0o600)
        folder = root / 'drivers' / checked['name']
        folder.mkdir(parents=True)
        os.chmod(folder.parent, 0o700)
        os.chmod(folder, 0o700)
        for name, mode in (('driver', 0o700), ('schema.json', 0o600), ('README.md', 0o600)):
            target = folder / name
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
            try:
                os.write(fd, checked['files'][name])
            finally:
                os.close(fd)
            os.chmod(target, mode)
        try:
            result = spawn(folder / 'driver')
        except (OSError, subprocess.TimeoutExpired):
            raise Refused('the driver version answer failed',
                          'do not install this package; nothing was saved')
    if result.returncode != 0:
        raise Refused('the driver version answer failed',
                      'do not install this package; nothing was saved')
    try:
        value = load_json(result.stdout)
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise Refused('the driver version answer does not match its declared name and abilities',
                      'do not install this package; nothing was saved')
    if (not isinstance(value, dict) or set(value) != {'driver', 'records', 'can'}
            or value['driver'] != checked['name'] or value['can'] != checked['can']
            or not isinstance(value['records'], list) or not value['records']):
        raise Refused('the driver version answer does not match its declared name and abilities',
                      'do not install this package; nothing was saved')


def write_file(path, data, mode):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(path, mode)


def install(root, checked):
    stage_and_run(checked.pop('build'), checked)
    guard(root)
    private(root)
    drivers = root / 'drivers'
    if drivers.is_symlink():
        raise Refused('the drivers folder is a link',
                      'use a real drivers directory you own; nothing was written')
    if not drivers.exists():
        drivers.mkdir(mode=0o700)
    os.chmod(drivers, 0o700)
    private(drivers)
    guard(drivers)
    dest = drivers / checked['name']
    if dest.is_symlink():
        raise Refused('the driver folder is a link',
                      'remove the link and add the driver again; nothing was replaced')
    token = secrets.token_hex(8)
    stage = drivers / ('.staging-%s-%s' % (checked['name'], token))
    backup = drivers / ('.backup-%s-%s' % (checked['name'], token))
    approval = (json.dumps({
        'repository': checked['repository'], 'publisher': checked['publisher'],
        'version': checked['version'], 'sha256': checked['sha256']}, indent=2) + '\n').encode()
    try:
        stage.mkdir(mode=0o700)
        os.chmod(stage, 0o700)
        for name, mode in (('driver', 0o700), ('schema.json', 0o600), ('README.md', 0o600)):
            write_file(stage / name, checked['files'][name], mode)
        write_file(stage / 'approval.json', approval, 0o600)
        if dest.exists():
            os.rename(dest, backup)
            os.rename(stage, dest)
            shutil.rmtree(backup, ignore_errors=True)
        else:
            os.rename(stage, dest)
        os.chmod(dest, 0o700)
    except OSError:
        if not dest.exists() and backup.exists():
            os.rename(backup, dest)
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise Refused('the driver could not be written',
                      'check that the drivers folder is yours; the previous driver was left in place')


def kit_schema(build):
    return read_regular(build / 'runtime' / 'kernel' / 'driver-kit' / 'schema.json',
                        'kernel/driver-kit/schema.json')


def core_driver(build, name):
    path = build / 'runtime' / 'adapters' / name / 'driver'
    return path.is_file() and not path.is_symlink()


def load_pin(build, name):
    path = build / 'runtime' / 'pins.json'
    if not path.exists():
        return None
    try:
        value = load_json(read_regular(path, 'pins.json'))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise Refused('the pin file is not a driver package pin',
                      "use the build's pins.json; nothing was installed")
    if not isinstance(value, dict) or set(value) != {'contract', 'pins'} or value['contract'] != 'openwiz.driver-package.v1':
        raise Refused('the pin file is not a driver package pin',
                      "use the build's pins.json; nothing was installed")
    if not isinstance(value['pins'], list):
        raise Refused('the pin file is not a driver package pin',
                      "use the build's pins.json; nothing was installed")
    found = None
    for entry in value['pins']:
        package = entry.get('package') if isinstance(entry, dict) else None
        driver = package.get('driver') if isinstance(package, dict) else None
        if not isinstance(driver, str):
            raise Refused('the pin file is not a driver package pin',
                          "use the build's pins.json; nothing was installed")
        if driver != name:
            continue
        if found is not None:
            raise Refused('more than one pin matches this host',
                          'keep one pin for this driver; nothing was installed')
        publisher = entry.get('publisher')
        if not isinstance(publisher, str) or not PUBLISHER.fullmatch(publisher):
            raise Refused('the pin file is not a driver package pin',
                          "use the build's pins.json; nothing was installed")
        found = (package, publisher)
    return found


def bind_receipt(text, package):
    if text.count('\n') != 14 or not text.endswith('\n'):
        return None
    lines = text.splitlines()
    driver = '# driver: %s@%s' % (package['repository'], package['commit'])
    kit = '# kit: openwizdev/OpenWiz@%s' % package['kit_commit']
    if len(lines) != 14 or lines[2] != driver or lines[3] != kit or lines[13] != 'Result: 5 of 5 pass':
        return None
    if not lines[6].startswith('# date: '):
        return None
    date = lines[6][len('# date: '):]
    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', date):
        return None
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        return None
    return date


def market_listing(client, commit, name):
    if not COMMIT.fullmatch(commit):
        raise Refused('the WizMarket commit is not a full commit',
                      'pass the recorded 40-character main commit; nothing was installed')
    try:
        rows = load_json(client.get(
            'https://api.github.com/repos/openwizdev/WizMarket/contents/listings?ref=' + commit, 'read'))
    except (UnicodeError, json.JSONDecodeError, ValueError):
        raise Refused('the WizMarket snapshot could not be read',
                      'use the recorded main commit; nothing was installed')
    if not isinstance(rows, list):
        raise Refused('the WizMarket snapshot could not be read',
                      'use the recorded main commit; nothing was installed')
    matches = []
    for row in rows:
        filename = row.get('name') if isinstance(row, dict) else None
        if row.get('type') != 'file' or not isinstance(filename, str):
            continue
        if not re.fullmatch(r'[a-z0-9-]{2,40}\.json', filename):
            continue
        try:
            body = load_json(client.get(
                'https://raw.githubusercontent.com/openwizdev/WizMarket/%s/listings/%s' % (commit, filename),
                'read'))
        except (UnicodeError, json.JSONDecodeError, ValueError):
            raise Refused('a WizMarket listing is not JSON',
                          'use a snapshot whose listings are JSON; nothing was installed')
        if not isinstance(body, dict) or 'package' not in body:
            continue
        package = body.get('package')
        if isinstance(package, dict) and package.get('driver') == name:
            matches.append(body)
    if not matches:
        return None
    if len(matches) > 1:
        raise Refused('more than one WizMarket listing matches this host',
                      'use a snapshot with one listing for this driver; nothing was installed')
    body = matches[0]
    tags = body.get('tags')
    if not isinstance(tags, list) or not ({'driver', 'harness'} & set(tags)):
        raise Refused('this listing is not a driver',
                      'pick a driver or harness listing; nothing was installed')
    publisher = body.get('publisher')
    status = body.get('status')
    if not isinstance(publisher, str) or status not in ('listed', 'verified'):
        raise Refused('the package block is malformed',
                      'do not install this listing; its package block does not match the contract')
    date = None
    if status == 'verified':
        proof = body.get('proof')
        path = proof.get('receipt') if isinstance(proof, dict) else None
        if not isinstance(path, str) or not RECEIPT_PATH.fullmatch(path):
            raise Refused("this verified listing's receipt is not for the pinned commit",
                          'do not install it; the receipt must match the package commit')
        try:
            text = client.get(
                'https://raw.githubusercontent.com/openwizdev/WizMarket/%s/%s' % (commit, path), 'read').decode('utf-8')
        except (UnicodeError, Refused):
            raise Refused("this verified listing's receipt is not for the pinned commit",
                          'do not install it; the receipt must match the package commit')
        date = bind_receipt(text, body['package'])
        if date is None:
            raise Refused("this verified listing's receipt is not for the pinned commit",
                          'do not install it; the receipt must match the package commit')
    return body['package'], publisher, 'verified' if status == 'verified' else 'listed', date


def resolve(name, build, commit, client):
    if not DRIVER.fullmatch(name):
        raise Refused('that host name is not a driver name',
                      'use the lowercase name the driver declares; nothing was installed')
    if not COMMIT.fullmatch(commit):
        raise Refused('the WizMarket commit is not a full commit',
                      'pass the recorded 40-character main commit; nothing was installed')
    if core_driver(build, name):
        raise Refused('this host is a core driver in the selected build',
                      "use the build's copy; nothing was downloaded")
    pin = load_pin(build, name)
    if pin is not None:
        return (*pin, 'pin', None)
    found = market_listing(client, commit, name)
    if found is None:
        raise Refused('no WizMarket listing matches this host',
                      'check the name, or the recorded WizMarket commit; nothing was installed')
    return found


def place(root, build, checked):
    checked['build'] = build
    install(root, checked)
    return {
        'name': checked['name'], 'version': checked['version'],
        'publisher': checked['publisher'], 'repository': checked['repository'],
        'sha256': checked['sha256']}


def add(name, root, build, commit, answer, client):
    package, publisher, kind, date = resolve(name, build, commit, client)
    checked = prepare(package, publisher, kind, client, kit_schema(build), date)
    gate(checked, answer, False)
    return place(root, build, checked)


def approvals(root):
    guard(root)
    private(root)
    drivers = root / 'drivers'
    if not drivers.exists():
        return []
    if drivers.is_symlink() or not drivers.is_dir():
        raise Refused('the drivers folder is a link',
                      'use a real drivers directory you own; nothing was changed')
    rows = []
    for child in sorted(drivers.iterdir(), key=lambda item: item.name):
        if child.name.startswith('.') or child.is_symlink() or not child.is_dir():
            continue
        path = child / 'approval.json'
        if path.is_symlink() or not path.is_file():
            continue
        try:
            value = load_json(path.read_text(encoding='utf-8'))
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise Refused('the saved approval for %s is not valid' % child.name,
                          'add that driver again; nothing else was changed')
        fields = ('repository', 'publisher', 'version', 'sha256')
        if not isinstance(value, dict) or any(key not in value for key in fields):
            raise Refused('the saved approval for %s is not valid' % child.name,
                          'add that driver again; nothing else was changed')
        rows.append((child.name, value))
    return rows


def decide(old, repository, publisher, version, sha256, verified):
    same = old['repository'] == repository and old['publisher'] == publisher
    if same and old['version'] == version and old['sha256'] == sha256:
        return 'unchanged'
    if same and verified and version_key(version) > version_key(old['version']):
        return 'move'
    return 'ask'


def update(root, build, commit, answer, client):
    schema = kit_schema(build)
    updated, unchanged, planned = [], [], []
    for name, old in approvals(root):
        found = market_listing(client, commit, name)
        if found is None:
            unchanged.append({'name': name, 'version': old['version']})
            continue
        package, publisher, kind, date = found
        if not package_shape(package):
            raise Refused('the package block is malformed',
                          'do not install this listing; its package block does not match the contract')
        choice = decide(old, package['repository'], publisher, package['version'],
                        package['sha256'], kind == 'verified')
        if choice == 'unchanged':
            unchanged.append({'name': name, 'version': old['version']})
            continue
        checked = prepare(package, publisher, kind, client, schema, date)
        if choice == 'ask':
            gate(checked, answer, True)
        planned.append((checked, old['version'], choice))
    for checked, previous, choice in planned:
        row = place(root, build, checked)
        if choice == 'move':
            notice = 'Notice: %s moved from %s to %s, same publisher %s.' % (
                row['name'], previous, row['version'], row['publisher'])
            print(notice, file=sys.stderr)
            row = {'name': row['name'], 'from': previous, 'to': row['version'], 'notice': notice}
        updated.append(row)
    return {'updated': updated, 'unchanged': unchanged}


def list_drivers(root):
    rows = []
    for name, value in approvals(root):
        rows.append({'name': name, 'repository': value['repository'], 'publisher': value['publisher'],
                     'version': value['version'], 'sha256': value['sha256']})
    return {'drivers': rows}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('the command was not understood',
                      'use add, list or update with --root; nothing was changed')


def parse(argv):
    parser = Parser(prog='fetch.py', description=DESCRIPTION)
    sub = parser.add_subparsers(dest='command')
    commands = {}
    for name in ('add', 'update', 'list'):
        commands[name] = sub.add_parser(name)
        commands[name].add_argument('--root', required=True)
    for name in ('add', 'update'):
        commands[name].add_argument('--build', required=True)
        commands[name].add_argument('--market-commit', required=True)
        commands[name].add_argument('--answer', choices=('yes', 'install-unverified'))
        commands[name].add_argument('--loopback')
    commands['add'].add_argument('name')
    args = parser.parse_args(argv)
    if args.command not in commands:
        raise Refused('the command was not understood',
                      'use add, list or update with --root; nothing was changed')
    return args


def main(argv):
    try:
        args = parse(argv)
        root = Path(args.root)
        if args.command == 'list':
            result = list_drivers(root)
        else:
            client = Client(args.loopback)
            build = Path(args.build)
            if args.command == 'add':
                result = add(args.name, root, build, args.market_commit, args.answer, client)
            else:
                result = update(root, build, args.market_commit, args.answer, client)
    except Refused as refused:
        sys.stdout.write(json.dumps({'error': refused.error, 'next': refused.next}) + '\n')
        return 1
    sys.stdout.write(json.dumps(result) + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
