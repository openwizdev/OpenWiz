#!/usr/bin/env python3
import argparse
import ctypes
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import re
import secrets
import select
import shlex
import shutil
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'setup'))
import store
from store import Refused, require

DESCRIPTION = """OpenWiz setup's CloudRoom step: install, reuse and sign in (#2201).

  cloudroom.py status
      Reads only: is CloudRoom installed here, and does CloudRoom report a
      signed-in account now? Prints one fixed code.
  cloudroom.py install
      Preview. Reuses an existing installation; otherwise finds CloudRoom's
      published installer for this platform and its published checksum, and
      saves the install operation (id and fingerprint) before any effect.
  cloudroom.py install --yes --operation ID
      Installs exactly that preview, only after the checksum matches. A retry
      reuses the same operation; an uncertain one is reconciled first.
  cloudroom.py install --no --operation ID
      Declines that preview. Nothing is installed.
  cloudroom.py sign-in
      Opens CloudRoom's own sign-in once, then reads the result back. If it
      fails, standard error gets its exit status, fixed text for any known
      error, and the command to run to see its full output; never its raw
      output. On Linux it first checks for a desktop session and FUSE, and
      names whichever is missing with its next step.

Contract: contracts/public-cloudroom-setup.v1.md. Records go to owner-only
`<state>/cloudroom/install.json`. Output is JSON with fixed public codes; never
a sign-in link, account detail, password or token. Python 3.9+, standard
library only.
"""

SCHEMA = 'openwiz.cloudroom-setup.v1'
RECORD = 'openwiz.cloudroom-install.v1'
KIND = 'install_cloudroom'
GUIDE = 'https://www.cloudroom.dev/setup.md'
RELEASES = 'https://github.com/davidondrej/cloudroom/releases/download/'
API = 'https://api.github.com/repos/davidondrej/cloudroom/releases/tags/'
DOWNLOAD_PAGE = 'https://www.cloudroom.dev/download'
LINK = re.compile(r'https://github\.com/davidondrej/cloudroom/releases/download/'
                  r'(gui-v([0-9]{1,6}))/(Cloudroom-v([0-9]{1,6})-([A-Za-z0-9_]{1,16})\.(dmg|AppImage|exe))')
SIGN_IN_HOSTS = ('www.cloudroom.dev', 'cloudroom.dev')
FETCH_HOSTS = ('www.cloudroom.dev', 'api.github.com', 'github.com',
               'objects.githubusercontent.com', 'release-assets.githubusercontent.com')
TARGETS = {('Darwin', 'arm64'): ('macos-arm64', 'arm64', 'dmg'),
           ('Linux', 'x86_64'): ('linux-x64', 'x86_64', 'AppImage')}
DESTINATIONS = {'macos-arm64': '/Applications/Cloudroom.app', 'linux-x64': '~/Applications/Cloudroom.AppImage'}
LAUNCHER = '.local/bin/room-cli'
CLOUD_LAUNCHER = 'usr/local/bin/room-cli'
CLOUD_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}')
ROOM_CLI_CALLS = (('cloud', 'status', '--json'), ('cloud', 'sign-in', '--json'))
PHASES = ('proposed', 'installing', 'applied', 'failed', 'refused', 'uncertain')
REASONS = ('proposed', 'installed', 'existing', 'declined', 'checksum_mismatch', 'download_failed',
           'install_failed', 'unverified', 'lost_reply')
TEAM_ID = '4AJ9HF33Z5'
REQUIREMENT = ('=anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] exists'
               ' and certificate leaf[field.1.2.840.113635.100.6.1.13] exists'
               f' and certificate leaf[subject.OU] = "{TEAM_ID}"')
INSTALLER_LIMIT = 1 << 30
TIMEOUT = 30
EFFECT_TIMEOUT = 900
RUNNING_MS = 30 * 60 * 1000
OPEN_WAIT = 3
OPEN_CAPTURE = 1 << 16
FUSERMOUNT = ('usr/bin/fusermount', 'usr/bin/fusermount3', 'bin/fusermount', 'bin/fusermount3')
LIBFUSE2 = tuple(f'{d}/libfuse.so.2' for d in ('lib/x86_64-linux-gnu', 'usr/lib/x86_64-linux-gnu', 'lib64',
                                                'usr/lib64', 'lib', 'usr/lib'))
RUNTIME_BYTES = 2 << 20
KNOWN_ERRORS = (
    ('error loading libfuse.so.2', "CloudRoom's AppImage could not load FUSE 2 (libfuse.so.2)."),
    ('AppImages require FUSE to run', "CloudRoom's AppImage needs FUSE to run."),
    ('Missing X server or $DISPLAY', 'CloudRoom found no desktop session.'),
    ('error while loading shared libraries', 'A system library CloudRoom needs is missing.'),
    ('The SUID sandbox helper binary was found, but is not configured correctly',
     "CloudRoom's sandbox helper is not set up."),
    ('no method available for opening', 'No browser is set up to open the sign-in page.'),
    ('ENOTFOUND', 'CloudRoom could not look up its server; check the network.'),
    ('ECONNREFUSED', 'CloudRoom could not connect; is CloudRoom running?'),
    ('ETIMEDOUT', 'CloudRoom timed out reaching its server; check the network.'),
)


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in FETCH_HOSTS or parts.port is not None:
            return None
        return super().redirect_request(request, fp, code, message, headers, url)


class Host:
    def __init__(self, system=None, machine=None, home=None, root=None):
        self.system = system or platform.system()
        self.machine = machine or platform.machine()
        home = Path(home if home is not None else os.environ.get('HOME', ''))
        require(home.is_absolute() and str(home) != '/', 'no absolute HOME')
        self.home = home
        self.root = Path(root or '/')
        self.environ = os.environ

    def _open_url(self, url):
        parts = urllib.parse.urlsplit(url)
        require(parts.scheme == 'https' and parts.hostname in FETCH_HOSTS and parts.port is None,
                'only CloudRoom and GitHub over HTTPS are read')
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), Redirects())
        return opener.open(urllib.request.Request(url, headers={'User-Agent': 'OpenWiz-setup'}), timeout=TIMEOUT)

    def fetch(self, url, limit):
        with self._open_url(url) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise OSError('answer too large')
        return data

    def download(self, url, path, limit):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as handle, self._open_url(url) as response:
            total = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise OSError('download too large')
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())

    def run(self, argv, timeout):
        return self.ask(argv, timeout)[:2]

    def ask(self, argv, timeout):
        try:
            result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
                                    env={'PATH': '/usr/bin:/bin', 'HOME': str(self.home), 'LC_ALL': 'C'})
        except subprocess.TimeoutExpired as late:
            return None, (late.stdout or b'')[:1 << 20], (late.stderr or b'')[:1 << 20]
        except OSError:
            return -1, b'', b''
        return result.returncode, result.stdout[:1 << 20], result.stderr[:1 << 20]

    def start(self, argv):
        subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)

    def open(self, argv):
        read, write = os.pipe()
        try:
            try:
                child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=write, stderr=write,
                                         start_new_session=True, close_fds=True)
            finally:
                os.close(write)
            captured, ended = bytearray(), False
            deadline = time.monotonic() + OPEN_WAIT
            while not ended:
                left = deadline - time.monotonic()
                if left <= 0 or not select.select([read], [], [], left)[0]:
                    break
                chunk = os.read(read, 1 << 16)
                ended = not chunk
                captured += chunk[:OPEN_CAPTURE - len(captured)]
            try:
                code = child.wait(max(0.0, deadline - time.monotonic()) if ended else 0)
            except subprocess.TimeoutExpired:
                code = None
            if not ended:
                try:
                    subprocess.Popen(['/bin/cat'], stdin=read, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True, close_fds=True)
                except OSError:
                    pass
            return code, bytes(captured)
        finally:
            os.close(read)

    def alive(self, pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True


def room_cli(host, call, messages=False):
    require(type(call) is tuple and call in ROOM_CLI_CALLS, 'not an allowlisted room-cli call')
    argv = [str(host.home / LAUNCHER), *call]
    return host.ask(argv, TIMEOUT) if messages else host.run(argv, TIMEOUT)


def target(host):
    return TARGETS.get((host.system, host.machine))


def checked_appimage(host, operation):
    if operation is None or operation['phase'] != 'applied' or operation['request']['target'] != 'linux-x64':
        return None
    path = destination(host, 'linux-x64')
    try:
        if (stat.S_ISREG(os.lstat(path).st_mode) and os.access(path, os.X_OK)
                and file_sha256(path) == operation['request']['sha256']):
            return path
    except OSError:
        pass
    return None


def cloud_thread(host):
    if host.system != 'Linux' or os.path.lexists(host.home / LAUNCHER):
        return False
    launcher = host.root / CLOUD_LAUNCHER
    try:
        if not (launcher.is_file() and os.access(launcher, os.X_OK)):
            return False
    except OSError:
        return False
    return all(isinstance(host.environ.get(name), str) and bool(CLOUD_ID.fullmatch(host.environ[name]))
               for name in ('ROOM_THREAD_ID', 'ROOM_PROJECT_ID'))


def installation(host, operation):
    if blocked(host, operation):
        return []
    found = [host.home / LAUNCHER] if os.path.lexists(host.home / LAUNCHER) else []
    if host.system == 'Darwin':
        found += [p for p in (host.root / 'Applications/Cloudroom.app', host.home / 'Applications/Cloudroom.app')
                  if os.path.lexists(p)]
    elif host.system == 'Linux':
        found += [p for p in (checked_appimage(host, operation),) if p is not None]
        if not found and cloud_thread(host):
            found.append(host.root / CLOUD_LAUNCHER)
    return found


def blocked(host, operation):
    path = destination(host, 'linux-x64')
    return host.system == 'Linux' and os.path.lexists(path) and checked_appimage(host, operation) is None


def destination(host, name):
    return host.root / 'Applications/Cloudroom.app' if name == 'macos-arm64' else host.home / 'Applications/Cloudroom.AppImage'


class Records:
    def __init__(self, state_dir):
        self.state = store.state_path(state_dir)
        self.dir = self.state / 'cloudroom'
        self.file = self.dir / 'install.json'

    def read(self):
        if not os.path.lexists(self.dir):
            return None
        store.private_directory(self.state, False)
        store.private_directory(self.dir, False)
        try:
            fd = os.open(self.file, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(fd)
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_mode & 0o077 == 0
                    and info.st_nlink == 1 and info.st_size <= 65536, 'CloudRoom install record is unsafe')
            with os.fdopen(os.dup(fd), 'rb') as handle:
                data = handle.read(65537)
        finally:
            os.close(fd)
        try:
            value = json.loads(data, object_pairs_hook=store.unique)
        except ValueError:
            raise Refused('CloudRoom install record is not valid JSON')
        require(type(value) is dict and set(value) == {'schema', 'operation'} and value['schema'] == RECORD,
                'invalid CloudRoom install record')
        if value['operation'] is not None:
            check(value['operation'])
        return value['operation']

    def locked(self):
        durable_directory(self.state)
        store.private_directory(self.state, False)
        durable_directory(self.dir)
        store.private_directory(self.dir, False)
        sync_directory(self.dir)
        sync_chain(self.dir)
        return Lock(self.dir / '.lock')

    def save(self, operation):
        check(operation)
        data = (json.dumps({'schema': RECORD, 'operation': operation}, sort_keys=True) + '\n').encode()
        temporary = self.dir / f'.install.{secrets.token_hex(8)}.tmp'
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.file)
        finally:
            temporary.unlink(missing_ok=True)
        sync_directory(self.dir)


def durable_directory(path):
    missing, probe = [], path
    while not os.path.lexists(probe):
        missing.append(probe)
        probe = probe.parent
    for folder in reversed(missing):
        os.mkdir(folder, 0o700 if folder == path else 0o777)
        sync_directory(folder.parent)


def sync_chain(path):
    for folder in (path, *path.parents):
        if folder == folder.parent or os.lstat(folder).st_uid != os.getuid():
            return
        sync_directory(folder.parent)


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Lock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        info = os.fstat(self.fd)
        if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600):
            os.close(self.fd)
            raise Refused('CloudRoom install lock is unsafe')
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        os.close(self.fd)


def check(operation):
    require(type(operation) is dict and set(operation) == {
        'operation_id', 'kind', 'phase', 'fingerprint', 'request', 'effects', 'reason', 'attempt'},
        'invalid CloudRoom install operation')
    require(isinstance(operation['operation_id'], str) and re.fullmatch('[0-9a-f]{32}', operation['operation_id'])
            and operation['kind'] == KIND and operation['phase'] in PHASES and operation['reason'] in REASONS
            and isinstance(operation['fingerprint'], str) and re.fullmatch('[0-9a-f]{64}', operation['fingerprint']),
            'invalid CloudRoom install operation')
    request = operation['request']
    require(type(request) is dict and set(request) == {'target', 'tag', 'name', 'url', 'sha256', 'bytes', 'destination'}
            and request['target'] in DESTINATIONS and request['destination'] == DESTINATIONS[request['target']]
            and all(isinstance(request[k], str) for k in ('tag', 'name', 'url', 'sha256'))
            and request['url'] == RELEASES + request['tag'] + '/' + request['name']
            and re.fullmatch('[0-9a-f]{64}', request['sha256'])
            and type(request['bytes']) is int and 0 < request['bytes'] <= INSTALLER_LIMIT,
            'invalid CloudRoom install request')
    require(store.fingerprint(KIND, request) == operation['fingerprint'], 'CloudRoom install fingerprint mismatch')
    require(type(operation['effects']) is list and all(isinstance(e, str) for e in operation['effects']),
            'invalid CloudRoom install effects')
    attempt = operation['attempt']
    require(attempt is None or (type(attempt) is dict and set(attempt) == {'pid', 'started'}
                                and store.positive(attempt['pid']) and store.positive(attempt['started'])),
            'invalid CloudRoom install attempt')


def resolve(host, name):
    _, arch, kind = name
    try:
        guide = host.fetch(GUIDE, 256 * 1024).decode('utf-8')
        links = {m.groups() for m in LINK.finditer(guide) if m.group(5) == arch and m.group(6) == kind}
        require(len(links) == 1, 'the guide names no single installer for this platform')
        tag, tag_number, asset, asset_number = next(iter(links))[:4]
        require(tag_number == asset_number, 'the guide link names two versions')
        release = json.loads(host.fetch(API + tag, 1 << 20), object_pairs_hook=store.unique)
        require(type(release) is dict and release.get('tag_name') == tag and release.get('draft') is False
                and release.get('prerelease') is False and type(release.get('assets')) is list,
                'not a published release')

        def published(file):
            rows = [a for a in release['assets'] if type(a) is dict and a.get('name') == file]
            require(len(rows) == 1, 'release asset missing')
            row = rows[0]
            digest, size = row.get('digest'), row.get('size')
            require(isinstance(digest, str) and re.fullmatch('sha256:[0-9a-f]{64}', digest)
                    and type(size) is int and 0 < size <= INSTALLER_LIMIT
                    and row.get('browser_download_url') == RELEASES + tag + '/' + file, 'unchecked release asset')
            return digest[7:], size
        sha256, size = published(asset)
        sums_sha256, sums_size = published('SHA256SUMS.txt')
        sums = host.fetch(RELEASES + tag + '/SHA256SUMS.txt', 65536)
        require(len(sums) == sums_size and hashlib.sha256(sums).hexdigest() == sums_sha256, 'checksum list differs')
        listed = [line[:64] for line in sums.decode('ascii').split('\n')
                  if re.fullmatch('[0-9a-f]{64}  [A-Za-z0-9._-]{1,128}', line) and line[66:] == asset]
        require(listed == [sha256], 'the published checksums disagree')
    except (OSError, http.client.HTTPException, ValueError, UnicodeError, Refused):
        return None
    return {'target': name[0], 'tag': tag, 'name': asset, 'url': RELEASES + tag + '/' + asset,
            'sha256': sha256, 'bytes': size, 'destination': DESTINATIONS[name[0]]}


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def signed_by_cloudroom(host, path):
    code, _ = host.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', '-R', REQUIREMENT, str(path)], 300)
    return code == 0


def copy_verifies(host, request):
    path = destination(host, request['target'])
    if not os.path.lexists(path):
        return False
    if request['target'] == 'linux-x64':
        try:
            return True if path.is_file() and file_sha256(path) == request['sha256'] else None
        except OSError:
            return None
    return True if signed_by_cloudroom(host, path) else None


def place(host, records, operation, download):
    request = operation['request']
    path = destination(host, request['target'])
    if os.path.lexists(path):
        return 'failed'
    if request['target'] == 'linux-x64':
        temporary = path.parent / f'.Cloudroom.AppImage.openwiz-{operation["operation_id"][:12]}'
        try:
            path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            temporary.unlink(missing_ok=True)
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o700)
            with os.fdopen(fd, 'wb') as out, open(download, 'rb') as source:
                for chunk in iter(lambda: source.read(1 << 20), b''):
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            os.chmod(temporary, 0o755)
            os.link(temporary, path)
            return 'ok'
        except OSError:
            return 'failed'
        finally:
            temporary.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.parent / f'.Cloudroom.app.openwiz-{operation["operation_id"][:12]}'
    shutil.rmtree(staging, ignore_errors=True)
    mount = records.dir / f'mount-{operation["operation_id"][:12]}'
    mount.mkdir(mode=0o700, exist_ok=True)
    try:
        try:
            code, _ = host.run(['/usr/bin/hdiutil', 'attach', '-nobrowse', '-readonly', '-quiet',
                                '-mountpoint', str(mount), str(download)], 300)
            if code != 0:
                return 'failed'
            source = mount / 'Cloudroom.app'
            if not source.is_dir() or source.is_symlink():
                return 'failed'
            code, _ = host.run(['/usr/bin/ditto', str(source), str(staging)], EFFECT_TIMEOUT)
            if code != 0:
                return 'lost' if code is None else 'failed'
        finally:
            host.run(['/usr/bin/hdiutil', 'detach', str(mount), '-quiet'], 120)
            try:
                mount.rmdir()
            except OSError:
                pass
        if not signed_by_cloudroom(host, staging):
            return 'failed'
        return 'ok' if publish(staging, path) else 'failed'
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def publish(source, target):
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        if sys.platform == 'darwin':
            result = libc.renamex_np(os.fsencode(source), os.fsencode(target), ctypes.c_uint(0x00000004))
        else:
            result = libc.renameat2(ctypes.c_int(-100), os.fsencode(source), ctypes.c_int(-100),
                                    os.fsencode(target), ctypes.c_uint(1))
    except (AttributeError, OSError):
        return False
    return result == 0


def running(host, operation):
    attempt = operation['attempt']
    now = int(time.time() * 1000)
    return attempt is not None and host.alive(attempt['pid']) and 0 <= now - attempt['started'] < RUNNING_MS


def install_code(host, operation):
    present = bool(installation(host, operation))
    if operation is not None:
        phase = operation['phase']
        if phase == 'installing':
            return 'cloudroom_installing' if running(host, operation) else 'cloudroom_install_uncertain'
        if phase == 'uncertain':
            return 'cloudroom_install_uncertain'
        if phase == 'failed':
            return 'cloudroom_install_failed'
    if blocked(host, operation):
        return 'cloudroom_destination_blocked'
    if operation is not None:
        phase = operation['phase']
        if phase == 'refused' and not present and operation['reason'] in ('declined', 'checksum_mismatch'):
            return 'cloudroom_install_declined' if operation['reason'] == 'declined' else 'cloudroom_checksum_mismatch'
        if phase == 'applied' and present:
            return 'cloudroom_installed'
    if present:
        return 'cloudroom_reused'
    return 'cloudroom_not_installed' if target(host) else 'cloudroom_unsupported'


def login_code(host):
    launcher = host.home / LAUNCHER
    if not launcher.is_file():
        return None
    code, out = room_cli(host, ROOM_CLI_CALLS[0])
    if code != 0:
        return 'cloudroom_login_unknown'
    try:
        value = json.loads(out, object_pairs_hook=store.unique)
    except (ValueError, Refused):
        return 'cloudroom_login_unknown'
    if type(value) is not dict or 'account' not in value or type(value.get('signingIn')) is not bool:
        return 'cloudroom_login_unknown'
    signed_out, self_hosted = value.get('signedOut', False), value.get('selfHosted', False)
    if type(signed_out) is not bool or type(self_hosted) is not bool or value['signingIn'] or self_hosted:
        return 'cloudroom_login_unknown'
    account = value['account']
    if account is None:
        return 'cloudroom_login_missing' if signed_out else 'cloudroom_login_unknown'
    if (type(account) is dict and set(account) == {'id', 'email'} and not signed_out
            and all(isinstance(account[k], str) and 0 < len(account[k]) <= 512 for k in account)):
        return 'cloudroom_login_verified'
    return 'cloudroom_login_unknown'


def code_for(host, operation):
    code = install_code(host, operation)
    if code == 'cloudroom_reused' and cloud_thread(host):
        return 'cloudroom_login_verified'
    if code in ('cloudroom_installed', 'cloudroom_reused'):
        return login_code(host) or code
    return code


def answer(code, operation=None, opened=None):
    return {'schema': SCHEMA, 'code': code, 'operation': operation, 'opened': opened}


def status(host, state_dir):
    return answer(code_for(host, Records(state_dir).read()))


def effects(request):
    return [f"Download CloudRoom {request['tag']} ({request['name']}) from CloudRoom's GitHub release.",
            f"Check it against the SHA-256 CloudRoom publishes ({request['sha256'][:12]}...); install nothing if it differs.",
            f"Install it at {request['destination']}. Nothing existing is replaced.",
            "Change nothing else. Sign-in happens in CloudRoom's own window."]


def install(host, state_dir, yes=False, decline=False, operation=None):
    require(not (yes and decline), 'choose --yes or --no')
    records = Records(state_dir)
    with records.locked():
        saved = records.read()
        if saved is not None and saved['phase'] in ('installing', 'uncertain'):
            if saved['phase'] == 'installing' and running(host, saved):
                require(not yes and not decline, 'that install is still running')
                return answer('cloudroom_installing', saved)
            if not yes:
                require(not decline, 'an uncertain install is reconciled, never declined')
                return answer('cloudroom_install_uncertain', saved)
            require(operation == saved['operation_id'], 'reconcile the pending install operation first')
            return apply(host, records, saved, reconcile=True)
        if decline:
            require(saved is not None and operation == saved['operation_id'] and saved['phase'] == 'proposed',
                    'no such proposed install operation')
            saved.update(phase='refused', reason='declined')
            records.save(saved)
            return answer(code_for(host, saved), saved)
        if yes and operation is not None:
            require(saved is not None and operation == saved['operation_id'], 'no such install operation; preview again')
            if saved['phase'] == 'applied':
                return answer(code_for(host, saved), saved)
            require(saved['phase'] in ('proposed', 'failed'), 'that install operation was refused; preview again')
            return apply(host, records, saved, reconcile=saved['phase'] == 'failed')
        if saved is not None and saved['phase'] == 'failed':
            return answer(code_for(host, saved), saved)
        if installation(host, saved):
            return answer('cloudroom_reused')
        if blocked(host, saved):
            return answer('cloudroom_destination_blocked')
        name = target(host)
        source = resolve(host, name) if name else None
        if source is None:
            code = 'cloudroom_source_unchecked' if name else 'cloudroom_unsupported'
            if yes:
                host.start(opener(host) + [DOWNLOAD_PAGE])
                return answer(code, opened='download_page')
            return answer(code)
        require(not yes, '--yes needs --operation from the preview')
        digest = store.fingerprint(KIND, source)
        if saved is not None and saved['fingerprint'] == digest and saved['phase'] in ('proposed', 'failed'):
            return answer('cloudroom_not_installed', saved)
        proposal = {'operation_id': secrets.token_hex(16), 'kind': KIND, 'phase': 'proposed', 'fingerprint': digest,
                    'request': source, 'effects': effects(source), 'reason': 'proposed', 'attempt': None}
        records.save(proposal)
        return answer('cloudroom_not_installed', proposal)


def apply(host, records, operation, reconcile):
    request = operation['request']
    if reconcile:
        verdict = copy_verifies(host, request)
        if verdict is True:
            operation.update(phase='applied', reason='installed', attempt=None)
            records.save(operation)
            return answer(code_for(host, operation), operation)
        if verdict is None:
            operation.update(phase='uncertain' if operation['phase'] != 'failed' else 'failed', attempt=None)
            records.save(operation)
            return answer(code_for(host, operation), operation)
    if installation(host, operation):
        operation.update(phase='refused', reason='existing', attempt=None)
        records.save(operation)
        return answer(code_for(host, operation), operation)
    if blocked(host, operation):
        return answer('cloudroom_destination_blocked', operation)
    operation.update(phase='installing', attempt={'pid': os.getpid(), 'started': int(time.time() * 1000)})
    records.save(operation)
    download = records.dir / 'download.part'
    download.unlink(missing_ok=True)
    try:
        try:
            host.download(request['url'], download, request['bytes'])
        except (OSError, http.client.HTTPException):
            operation.update(phase='failed', reason='download_failed', attempt=None)
            records.save(operation)
            return answer(code_for(host, operation), operation)
        if os.path.getsize(download) != request['bytes'] or file_sha256(download) != request['sha256']:
            operation.update(phase='refused', reason='checksum_mismatch', attempt=None)
            records.save(operation)
            return answer(code_for(host, operation), operation)
        outcome = place(host, records, operation, download)
    finally:
        download.unlink(missing_ok=True)
    if outcome == 'lost':
        operation.update(phase='uncertain', reason='lost_reply', attempt=None)
    elif outcome == 'failed':
        operation.update(phase='failed', reason='install_failed', attempt=None)
    elif copy_verifies(host, request) is True:
        operation.update(phase='applied', reason='installed', attempt=None)
    else:
        operation.update(phase='failed', reason='unverified', attempt=None)
    records.save(operation)
    return answer(code_for(host, operation), operation)


def opener(host):
    return ['/usr/bin/open'] if host.system == 'Darwin' else ['/usr/bin/xdg-open']


def sign_in_link(raw):
    try:
        value = json.loads(raw, object_pairs_hook=store.unique)
    except (ValueError, Refused):
        return None
    if type(value) is not dict or set(value) != {'url'} or not isinstance(value['url'], str):
        return None
    url = value['url']
    parts = urllib.parse.urlsplit(url)
    if (len(url) > 4096 or re.search(r'[\s\x00-\x1f\x7f]', url) or parts.scheme != 'https'
            or parts.netloc not in SIGN_IN_HOSTS):
        return None
    return url


def shown(host, argv):
    words = []
    for word in argv:
        path = Path(word)
        if path.is_absolute() and path.is_relative_to(host.home):
            words.append('"$HOME"/' + shlex.quote(str(path.relative_to(host.home))))
        else:
            words.append(shlex.quote(word))
    return ' '.join(words)


def report(who, status, output, command):
    print(f'openwiz-cloudroom: {status}', file=sys.stderr)
    for phrase, text in KNOWN_ERRORS:
        if phrase.encode() in output:
            print(f'openwiz-cloudroom: {who} reported: {text}', file=sys.stderr)
    print(f'openwiz-cloudroom: to see its full output, run: {command}', file=sys.stderr)


def launched(host, who, argv, command):
    try:
        code, out = host.open(argv)
    except OSError:
        print(f'openwiz-cloudroom: {who} could not be started here', file=sys.stderr)
        return False
    if code in (None, 0):
        return True
    status = (f'{who} exited with status {code} at launch.' if who == 'CloudRoom'
              else f'{who} exited with status {code}; the sign-in page did not open.')
    report(who, status, out, command)
    return False


def linux_needs(host, operation):
    if host.system != 'Linux':
        return
    reasons = []
    if not (host.environ.get('DISPLAY') or host.environ.get('WAYLAND_DISPLAY')):
        reasons.append("CloudRoom's sign-in needs a desktop session, and this machine has none "
                       '(no DISPLAY or WAYLAND_DISPLAY). Next: run sign-in from a desktop session on this machine, '
                       'such as a local or remote desktop login; a headless server cannot sign in.')
    missing = [] if os.path.exists(host.root / 'dev/fuse') else ['/dev/fuse']
    if not any(os.path.exists(host.root / p) for p in FUSERMOUNT):
        missing.append('fusermount')
    app = checked_appimage(host, operation)
    if app is not None and not any(os.path.exists(host.root / p) for p in LIBFUSE2):
        try:
            with open(app, 'rb') as handle:
                if b'libfuse.so.2' in handle.read(RUNTIME_BYTES):
                    missing.append('libfuse.so.2')
        except OSError:
            pass
    if missing:
        reasons.append("CloudRoom's AppImage needs FUSE, and this machine has no " + ' or '.join(missing) + '. '
                       "Next: install FUSE with your distribution's packages (libfuse2, or libfuse2t64 on Ubuntu "
                       '24.04 and later, and fuse3), make sure /dev/fuse exists, then run sign-in again.')
    require(not reasons, ' '.join(reasons))


def sign_in(host, state_dir):
    records = Records(state_dir)
    operation = records.read()
    installed = install_code(host, operation)
    require(installed in ('cloudroom_installed', 'cloudroom_reused'), 'CloudRoom is not installed here; install it first')
    if installed == 'cloudroom_reused' and cloud_thread(host):
        return answer('cloudroom_login_verified')
    linux_needs(host, operation)
    code = login_code(host) or installed
    if code == 'cloudroom_login_verified':
        return answer(code)
    launcher = host.home / LAUNCHER
    opened = None
    if launcher.is_file():
        result, out, err = room_cli(host, ROOM_CLI_CALLS[1], messages=True)
        url = sign_in_link(out) if result == 0 else None
        if url is not None:
            command = opener(host)
            opened = 'sign_in' if launched(host, Path(command[0]).name, command + [url],
                                           shown(host, command + ['https://www.cloudroom.dev'])) else None
        else:
            status = (f"CloudRoom's sign-in did not answer within {TIMEOUT} seconds; is CloudRoom running?"
                      if result is None else f"CloudRoom's sign-in exited with status {result} and gave no usable link.")
            report('CloudRoom', status, err + b'\n' + out, shown(host, [str(launcher), *ROOM_CLI_CALLS[1]]))
    else:
        app = next((p for p in installation(host, records.read()) if p.name != 'room-cli'), None)
        if app is not None:
            command = (['/usr/bin/open'] if host.system == 'Darwin' else []) + [str(app)]
            opened = 'app' if launched(host, 'CloudRoom', command, shown(host, command)) else None
    return answer(code_for(host, records.read()), opened=opened)


def main(argv=None, host=None):
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status', description='Read whether CloudRoom is installed and signed in. Reads only.')
    p = commands.add_parser('install', description='Preview, confirm or decline installing CloudRoom.')
    p.add_argument('--yes', action='store_true', help='install exactly the previewed operation')
    p.add_argument('--no', action='store_true', help='decline the previewed operation')
    p.add_argument('--operation', help='the operation id from the preview')
    commands.add_parser('sign-in', description="Open CloudRoom's own sign-in once, then read the login back. "
                                               'OpenWiz never asks for a password or token.')
    for command in commands.choices.values():
        command.add_argument('--state-dir', help="absolute OpenWiz state directory (default: the store's)")
    args = parser.parse_args(argv)
    host = host or Host()
    if args.command == 'status':
        result = status(host, args.state_dir)
    elif args.command == 'install':
        result = install(host, args.state_dir, yes=args.yes, decline=args.no, operation=args.operation)
    else:
        result = sign_in(host, args.state_dir)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Refused as refusal:
        print(f'openwiz-cloudroom: refused: {refusal}', file=sys.stderr)
        sys.exit(5)
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        print('openwiz-cloudroom: refused: the CloudRoom step could not be completed safely', file=sys.stderr)
        sys.exit(5)
