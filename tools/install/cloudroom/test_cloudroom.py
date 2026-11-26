#!/usr/bin/env python3
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIXTURES = HERE / 'fixtures'
RELEASE = 'https://github.com/davidondrej/cloudroom/releases/download/gui-v9001/'
GUIDE = 'https://www.cloudroom.dev/setup.md'
API = 'https://api.github.com/repos/davidondrej/cloudroom/releases/tags/gui-v9001'
DOWNLOAD_PAGE = 'https://www.cloudroom.dev/download'
SIGN_IN_URL = 'https://www.cloudroom.dev/login?desktop=synthetic-nonce-0001'
APPIMAGE = 'Cloudroom-v9001-x86_64.AppImage'
DMG = 'Cloudroom-v9001-arm64.dmg'
SUMS = {line.split('  ')[1]: line.split('  ')[0]
        for line in (FIXTURES / 'SHA256SUMS.txt').read_text().splitlines()}
CLOUDROOM_TEAM = '4AJ9HF33Z5'
OTHER_TEAM = 'SYNTHETIC0'
REQUIREMENT = re.compile(r'=anchor apple generic and certificate 1\[field\.1\.2\.840\.113635\.100\.6\.2\.6\] exists'
                         r' and certificate leaf\[field\.1\.2\.840\.113635\.100\.6\.1\.13\] exists'
                         r' and certificate leaf\[subject\.OU\] = "([A-Z0-9]{10})"')


def load():
    spec = importlib.util.spec_from_file_location('cloudroom_under_test', HERE / 'cloudroom.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloudroom = load()


class Lost(BaseException):
    pass


class FakeHost(cloudroom.Host):
    def __init__(self, base, system='Linux', machine='x86_64'):
        self.base = base
        super().__init__(system=system, machine=machine, home=base / 'home', root=base / 'root')
        (base / 'home').mkdir(mode=0o700)
        (base / 'root').mkdir()
        self.calls, self.fetched, self.opened, self.spawned = [], [], [], []
        self.web = {GUIDE: (FIXTURES / 'setup.md').read_bytes(), API: (FIXTURES / 'release.json').read_bytes(),
                    RELEASE + 'SHA256SUMS.txt': (FIXTURES / 'SHA256SUMS.txt').read_bytes()}
        for name in (APPIMAGE, DMG):
            self.web[RELEASE + name] = (FIXTURES / name).read_bytes()
        self.status = None
        self.cloud_status = None
        self.sign_in_reply = (FIXTURES / 'cloud-sign-in.json').read_bytes()
        self.lose_download = False
        self.during_download = None
        self.during_mount = None
        self.during_codesign = None
        self.effect = 'ok'
        self.codesign = 0
        self.codesign_fails = set()
        self.signers = {}
        self.dmg_signer = CLOUDROOM_TEAM
        self.dead = set()
        self.environ = {'DISPLAY': ':0'}
        for path in ('dev/fuse', 'usr/bin/fusermount3'):
            (base / 'root' / path).parent.mkdir(parents=True, exist_ok=True)
            (base / 'root' / path).write_text('synthetic')
        self.sign_in_code, self.sign_in_said = 0, b''
        self.open_result = (None, b'')

    def fetch(self, url, limit):
        self.fetched.append(url)
        if url not in self.web:
            raise OSError('synthetic: not found')
        data = self.web[url]
        if len(data) > limit:
            raise OSError('synthetic: too large')
        return data

    def download(self, url, path, limit):
        self.fetched.append(url)
        data = self.web[url]
        with open(path, 'wb') as handle:
            handle.write(data[:len(data) // 2])
            if self.lose_download:
                raise Lost()
            handle.write(data[len(data) // 2:])
        if self.during_download:
            self.during_download()

    def run(self, argv, timeout):
        self.calls.append(list(argv))
        name = Path(argv[0]).name
        if name == 'room-cli':
            if argv[1:] == ['cloud', 'status', '--json']:
                if self.status == 'timeout':
                    return None, b''
                if self.status is None:
                    return 1, b''
                if isinstance(self.status, bytes):
                    return 0, self.status
                return 0, (FIXTURES / f'cloud-{self.status}.json').read_bytes()
            if argv[1:] == ['cloud', 'sign-in', '--json']:
                return self.sign_in_code, self.sign_in_reply
            if argv[1:] == ['status', '--json']:
                if self.cloud_status == 'timeout':
                    return None, b''
                if self.cloud_status is None:
                    return 1, b''
                if isinstance(self.cloud_status, bytes):
                    return 0, self.cloud_status
                return 0, json.dumps(self.cloud_status).encode()
            return 2, b''
        if name == 'hdiutil' and argv[1] == 'attach':
            mount = Path(argv[argv.index('-mountpoint') + 1])
            (mount / 'Cloudroom.app/Contents').mkdir(parents=True)
            (mount / 'Cloudroom.app/Contents/Info.plist').write_text('synthetic')
            (mount / 'Cloudroom.app/Contents/synthetic-signer').write_text(self.dmg_signer)
            if self.during_mount:
                self.during_mount()
            return 0, b''
        if name == 'hdiutil' and argv[1] == 'detach':
            shutil.rmtree(argv[2], ignore_errors=True)
            return 0, b''
        if name == 'ditto':
            if self.effect == 'fail':
                return 1, b''
            if self.effect == 'partial':
                Path(argv[2]).mkdir(parents=True, exist_ok=True)
                (Path(argv[2]) / 'half-copied').write_text('partial')
                return 1, b''
            shutil.copytree(argv[1], argv[2], dirs_exist_ok=True)
            return (None if self.effect == 'timeout' else 0), b''
        if name == 'codesign':
            if self.during_codesign:
                self.during_codesign(Path(argv[-1]))
            path = Path(argv[-1])
            if path in self.codesign_fails or self.codesign:
                return 1 if path in self.codesign_fails else self.codesign, b''
            if '-R' not in argv:
                return 0, b''
            match = REQUIREMENT.fullmatch(argv[argv.index('-R') + 1])
            signer = (path / 'Contents/synthetic-signer').read_text() \
                if (path / 'Contents/synthetic-signer').is_file() else self.signers.get(path, CLOUDROOM_TEAM)
            return (0 if match and match.group(1) == signer else 3), b''
        return 127, b''

    def ask(self, argv, timeout):
        code, out = self.run(argv, timeout)
        return code, out, self.sign_in_said if argv[1:] == ['cloud', 'sign-in', '--json'] else b''

    def open(self, argv):
        self.opened.append(list(argv))
        return self.open_result

    def start(self, argv):
        self.opened.append(list(argv))

    def alive(self, pid):
        return pid not in self.dead

    def launcher(self, status='signed-in'):
        self.status = status
        path = self.home / '.local/bin/room-cli'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o700)

    def cloud_launcher(self, reply=None):
        self.cloud_status = ({'childThreads': [], 'thread': {'id': 'thr_syn_0001', 'projectId': 'prj_syn_0001',
                                                             'archived': False, 'status': 'active'}}
                             if reply is None else reply)
        path = self.root / 'usr/local/bin/room-cli'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('#!/bin/sh\nexit 0\n')
        path.chmod(0o700)

    def appimage(self):
        return self.home / 'Applications/Cloudroom.AppImage'

    def plant_appimage(self, path=None, data=b'existing synthetic copy', mode=0o755):
        path = path or self.appimage()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        return path

    def mac_app(self):
        return self.root / 'Applications/Cloudroom.app'

    def publish_appimage(self, data):
        digest = hashlib.sha256(data).hexdigest()
        sums = ''.join(f'{digest if name == APPIMAGE else sha}  {name}\n' for name, sha in SUMS.items()).encode()
        release = json.loads(self.web[API])
        for asset in release['assets']:
            if asset['name'] == APPIMAGE:
                asset.update(size=len(data), digest=f'sha256:{digest}')
            if asset['name'] == 'SHA256SUMS.txt':
                asset.update(size=len(sums), digest=f'sha256:{hashlib.sha256(sums).hexdigest()}')
        self.web.update({API: json.dumps(release).encode(), RELEASE + 'SHA256SUMS.txt': sums, RELEASE + APPIMAGE: data})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-cloudroom-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state'
        self.host = FakeHost(self.base)

    def status(self):
        return cloudroom.status(self.host, self.state)

    def install(self, **kwargs):
        return cloudroom.install(self.host, self.state, **kwargs)

    def sign_in(self):
        return cloudroom.sign_in(self.host, self.state)

    def record(self):
        return json.loads((self.state / 'cloudroom/install.json').read_text())

    def effects(self):
        return ([c for c in self.host.calls if c[1:] != ['cloud', 'status', '--json']], self.host.opened,
                self.host.appimage().exists(), self.host.mac_app().exists())


class Detection(Base):
    def test_no_installation_is_not_installed(self):
        self.assertEqual(self.status()['code'], 'cloudroom_not_installed')
        self.assertFalse(self.state.exists(), 'a read-only status writes nothing')

    def test_each_existing_installation_is_reused_and_never_reinstalled(self):
        cases = [('Linux', 'x86_64', 'home', '.local/bin/room-cli'),
                 ('Darwin', 'arm64', 'root', 'Applications/Cloudroom.app'),
                 ('Darwin', 'arm64', 'home', 'Applications/Cloudroom.app'),
                 ('Darwin', 'x86_64', 'root', 'Applications/Cloudroom.app')]
        for system, machine, where, path in cases:
            with self.subTest(path=path, system=system, machine=machine):
                base = self.base / f'{system}-{machine}-{where}-{path.replace("/", "-")}'
                base.mkdir()
                host = FakeHost(base, system, machine)
                existing = (host.home if where == 'home' else host.root) / path
                existing.parent.mkdir(parents=True, exist_ok=True)
                existing.mkdir() if path.endswith('.app') else host.plant_appimage(existing, b'older synthetic copy')
                before = sorted(p.relative_to(base).as_posix() for p in base.rglob('*'))
                status = cloudroom.status(host, base / 'state')
                launcher = path.endswith('room-cli')
                self.assertEqual(status['code'], 'cloudroom_login_unknown' if launcher else 'cloudroom_reused')
                self.assertEqual(host.calls, [[str(existing), 'cloud', 'status', '--json']] if launcher else [])
                host.calls.clear()
                preview = cloudroom.install(host, base / 'state')
                self.assertEqual(preview['code'], 'cloudroom_reused')
                self.assertIsNone(preview['operation'], 'nothing to install: no operation is proposed')
                self.assertEqual(host.fetched, [], 'reuse reads no installer source')
                self.assertEqual(host.calls, [])
                self.assertEqual(host.opened, [])
                after = sorted(p.relative_to(base).as_posix() for p in base.rglob('*') if 'state' not in p.parts)
                self.assertEqual(after, before, 'nothing is replaced or added')

    def test_unsupported_platforms_install_nothing_and_open_the_download_page_once(self):
        for system, machine in (('Darwin', 'x86_64'), ('Linux', 'aarch64'), ('Windows', 'AMD64'), ('FreeBSD', 'amd64')):
            with self.subTest(system=system, machine=machine):
                base = self.base / f'unsupported-{system}-{machine}'
                base.mkdir()
                host = FakeHost(base, system, machine)
                self.assertEqual(cloudroom.status(host, base / 'state')['code'], 'cloudroom_unsupported')
                preview = cloudroom.install(host, base / 'state')
                self.assertEqual(preview['code'], 'cloudroom_unsupported')
                self.assertIsNone(preview['operation'])
                self.assertEqual(host.opened, [], 'a preview opens nothing')
                done = cloudroom.install(host, base / 'state', yes=True)
                self.assertEqual(done['code'], 'cloudroom_unsupported')
                self.assertEqual(done['opened'], 'download_page')
                self.assertEqual([argv[-1] for argv in host.opened], [DOWNLOAD_PAGE])
                self.assertEqual(host.fetched, [], 'no installer is looked for or downloaded')
                self.assertEqual([c for c in host.calls], [])


class Install(Base):
    def preview(self):
        result = self.install()
        self.assertEqual(result['code'], 'cloudroom_not_installed')
        return result['operation']

    def test_preview_saves_the_id_and_fingerprint_before_any_effect(self):
        operation = self.preview()
        self.assertRegex(operation['operation_id'], '^[0-9a-f]{32}$')
        self.assertRegex(operation['fingerprint'], '^[0-9a-f]{64}$')
        self.assertEqual(operation['phase'], 'proposed')
        self.assertEqual(operation['request'], {
            'target': 'linux-x64', 'tag': 'gui-v9001', 'name': APPIMAGE, 'url': RELEASE + APPIMAGE,
            'sha256': SUMS[APPIMAGE], 'bytes': len((FIXTURES / APPIMAGE).read_bytes()),
            'destination': '~/Applications/Cloudroom.AppImage'})
        self.assertEqual(self.record()['operation']['operation_id'], operation['operation_id'])
        self.assertEqual(self.host.fetched, [GUIDE, API, RELEASE + 'SHA256SUMS.txt'], 'the preview reads the source only')
        self.assertEqual(self.effects(), ([], [], False, False))
        mode = stat.S_IMODE(os.stat(self.state / 'cloudroom/install.json').st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(self.status()['code'], 'cloudroom_not_installed')
        again = self.preview()
        self.assertEqual(again['operation_id'], operation['operation_id'], 'a repeated preview reuses the id')

    def test_an_explicit_request_installs_only_after_the_integrity_check(self):
        operation = self.preview()
        result = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_installed')
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual(result['operation']['operation_id'], operation['operation_id'])
        installed = self.host.appimage()
        self.assertEqual(hashlib.sha256(installed.read_bytes()).hexdigest(), SUMS[APPIMAGE])
        self.assertTrue(os.access(installed, os.X_OK))
        self.assertEqual(self.host.opened, [], 'installing launches nothing')
        self.assertEqual(self.status()['code'], 'cloudroom_installed')
        leftovers = [p.name for p in (self.state / 'cloudroom').iterdir()]
        self.assertEqual(sorted(leftovers), ['.lock', 'install.json'], 'the download is removed')
        fetched = list(self.host.fetched)
        again = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(again['operation']['phase'], 'applied')
        self.assertEqual(self.host.fetched, fetched)

    def test_nothing_happens_without_the_previewed_operation(self):
        self.preview()
        for operation in (None, '0' * 32, 'not-an-id'):
            with self.subTest(operation=operation):
                with self.assertRaises(cloudroom.Refused):
                    self.install(yes=True, operation=operation)
        self.assertEqual(self.effects(), ([], [], False, False))

    def test_a_checksum_mismatch_installs_nothing(self):
        operation = self.preview()
        good = self.host.web[RELEASE + APPIMAGE]
        for at, tampered in enumerate((good + b'more', good[:-2] + b'X\n')):
            if at:
                self.host.web[RELEASE + APPIMAGE] = good
                operation = self.preview()
            self.host.web[RELEASE + APPIMAGE] = tampered
            result = self.install(yes=True, operation=operation['operation_id'])
            self.assertEqual(result['code'], 'cloudroom_checksum_mismatch')
            self.assertFalse(self.host.appimage().exists())
        self.assertEqual(result['operation']['phase'], 'refused')
        self.assertFalse(self.host.appimage().exists())
        self.assertFalse((self.host.home / 'Applications').exists() and any((self.host.home / 'Applications').iterdir()))
        self.assertEqual(sorted(p.name for p in (self.state / 'cloudroom').iterdir()), ['.lock', 'install.json'])
        self.assertEqual(self.status()['code'], 'cloudroom_checksum_mismatch')

    def test_a_source_whose_published_checks_disagree_proposes_nothing(self):
        release = json.loads((FIXTURES / 'release.json').read_text())
        sums = (FIXTURES / 'SHA256SUMS.txt').read_text()
        mutations = {
            'digest differs': ('api', [dict(a, digest='sha256:' + '0' * 64) if a['name'] == APPIMAGE else a
                                       for a in release['assets']]),
            'no digest': ('api', [{k: v for k, v in a.items() if k != 'digest'} if a['name'] == APPIMAGE else a
                                  for a in release['assets']]),
            'sums line differs': ('sums', sums.replace(SUMS[APPIMAGE], 'f' * 64)),
            'sums line missing': ('sums', ''.join(l + '\n' for l in sums.splitlines() if APPIMAGE not in l)),
            'sums file digest differs': ('sums', sums + '\n'),
            'draft release': ('draft', True),
            'guide names another host': ('guide', (FIXTURES / 'setup.md').read_text().replace(
                'https://github.com/davidondrej/cloudroom/releases/download/gui-v9001/' + APPIMAGE,
                'https://example.invalid/releases/download/gui-v9001/' + APPIMAGE)),
            'guide names no installer': ('guide', '# Install Cloudroom\n'),
        }
        for name, (where, value) in mutations.items():
            with self.subTest(name):
                base = self.base / name.replace(' ', '-')
                base.mkdir()
                host = FakeHost(base)
                if where == 'api':
                    host.web[API] = json.dumps(dict(release, assets=value)).encode()
                elif where == 'draft':
                    host.web[API] = json.dumps(dict(release, draft=value)).encode()
                elif where == 'sums':
                    host.web[RELEASE + 'SHA256SUMS.txt'] = value.encode()
                else:
                    host.web[GUIDE] = value.encode()
                result = cloudroom.install(host, base / 'state')
                self.assertEqual(result['code'], 'cloudroom_source_unchecked')
                self.assertIsNone(result['operation'])
                self.assertNotIn(RELEASE + APPIMAGE, host.fetched, 'nothing is downloaded')
                self.assertEqual(host.calls, [])

    def test_a_refusal_installs_nothing(self):
        operation = self.preview()
        result = self.install(decline=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_install_declined')
        self.assertEqual(result['operation']['phase'], 'refused')
        self.assertEqual(self.status()['code'], 'cloudroom_install_declined')
        with self.assertRaises(cloudroom.Refused):
            self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(self.effects(), ([], [], False, False))

    def test_incomplete_source_reads_propose_nothing(self):
        for url in (GUIDE, API, RELEASE + 'SHA256SUMS.txt'):
            with self.subTest(url=url):
                fetch = self.host.fetch

                def incomplete(source, limit):
                    if source == url:
                        raise http.client.IncompleteRead(b'synthetic partial response', 100)
                    return fetch(source, limit)

                with patch.object(self.host, 'fetch', incomplete):
                    result = self.install()
                self.assertEqual(result['code'], 'cloudroom_source_unchecked')
                self.assertIsNone(result['operation'])
                self.assertFalse((self.state / 'cloudroom/install.json').exists())
                self.assertEqual(self.effects(), ([], [], False, False))

    def test_an_incomplete_download_is_failed_and_cleans_up(self):
        operation = self.preview()

        def incomplete(url, path, limit):
            path.write_bytes(b'synthetic partial download')
            raise http.client.IncompleteRead(b'synthetic partial response', 100)

        with patch.object(self.host, 'download', incomplete):
            result = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_install_failed')
        saved = self.record()['operation']
        self.assertEqual(saved['operation_id'], operation['operation_id'])
        self.assertEqual(saved['phase'], 'failed')
        self.assertEqual(saved['reason'], 'download_failed')
        self.assertIsNone(saved['attempt'])
        self.assertEqual(sorted(p.name for p in (self.state / 'cloudroom').iterdir()), ['.lock', 'install.json'])
        self.assertEqual(self.effects(), ([], [], False, False))
        self.host.dead.add(os.getpid())
        self.assertEqual(self.status()['code'], 'cloudroom_install_failed')
        self.assertEqual(self.install()['operation']['operation_id'], operation['operation_id'])
        self.assertEqual(self.install(yes=True, operation=operation['operation_id'])['code'], 'cloudroom_installed')

    def test_an_interrupted_install_is_uncertain_then_reconciled_before_another_attempt(self):
        operation = self.preview()
        self.host.lose_download = True
        with self.assertRaises(Lost):
            self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(self.record()['operation']['phase'], 'installing')
        self.assertEqual(self.status()['code'], 'cloudroom_installing', 'its process is still alive')
        self.host.dead.add(os.getpid())
        self.assertEqual(self.status()['code'], 'cloudroom_install_uncertain')
        self.assertEqual(self.install()['operation']['operation_id'], operation['operation_id'],
                         'a preview reuses the uncertain operation, never a new id')
        self.assertEqual(self.install()['code'], 'cloudroom_install_uncertain')
        with self.assertRaises(cloudroom.Refused):
            self.install(decline=True, operation=operation['operation_id'])
        self.host.lose_download = False
        result = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['operation_id'], operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_installed')
        self.assertEqual(hashlib.sha256(self.host.appimage().read_bytes()).hexdigest(), SUMS[APPIMAGE])

    def test_a_lost_reply_is_uncertain_and_reconciles_to_the_actual_installation(self):
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        state = self.base / 'mac-state'
        operation = cloudroom.install(mac, state)['operation']
        self.assertEqual(operation['request']['destination'], '/Applications/Cloudroom.app')
        self.assertEqual(operation['request']['sha256'], SUMS[DMG])
        mac.effect = 'timeout'
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_install_uncertain')
        self.assertEqual(result['operation']['phase'], 'uncertain')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_uncertain')
        self.assertFalse(mac.mac_app().exists(), 'an unanswered copy is never published')
        mac.effect = 'ok'
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['operation_id'], operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual(result['code'], 'cloudroom_installed')
        self.assertTrue((mac.mac_app() / 'Contents/Info.plist').is_file())
        self.assertEqual(len([c for c in mac.calls if Path(c[0]).name == 'hdiutil' and c[1] == 'attach']), 2)
        state2 = self.base / 'mac-state-2'
        (self.base / 'mac2').mkdir()
        mac2 = FakeHost(self.base / 'mac2', 'Darwin', 'arm64')
        operation = cloudroom.install(mac2, state2)['operation']
        mac2.effect = 'timeout'
        cloudroom.install(mac2, state2, yes=True, operation=operation['operation_id'])
        (mac2.mac_app() / 'Contents').mkdir(parents=True)
        result = cloudroom.install(mac2, state2, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual(len([c for c in mac2.calls if Path(c[0]).name == 'ditto']), 1)

    def test_a_lost_reply_with_an_unverifiable_copy_stays_uncertain(self):
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        state = self.base / 'mac-state'
        operation = cloudroom.install(mac, state)['operation']
        mac.effect = 'timeout'
        cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        (mac.mac_app() / 'Contents').mkdir(parents=True)
        mac.codesign = 1
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'uncertain', 'a later failure never lowers uncertainty')
        self.assertEqual(result['code'], 'cloudroom_install_uncertain')
        self.assertEqual(len([c for c in mac.calls if Path(c[0]).name == 'ditto']), 1, 'nothing is copied over it')

    def test_a_failed_install_is_failed_never_installed(self):
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        state = self.base / 'mac-state'
        operation = cloudroom.install(mac, state)['operation']
        mac.effect = 'partial'
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_install_failed')
        self.assertEqual(result['operation']['phase'], 'failed')
        self.assertFalse(mac.mac_app().exists(), 'a partial copy is never published')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_failed')
        detaches = [c for c in mac.calls if Path(c[0]).name == 'hdiutil' and c[1] == 'detach']
        self.assertEqual(len(detaches), 1, 'the disk image is always detached')
        for residue in (False, True):
            with self.subTest(residue=residue):
                if residue:
                    (mac.mac_app() / 'Contents').mkdir(parents=True)
                    mac.codesign = 1
                preview = cloudroom.install(mac, state)
                self.assertEqual(preview['code'], 'cloudroom_install_failed')
                self.assertEqual(preview['operation']['operation_id'], operation['operation_id'])
        dittos = len([c for c in mac.calls if Path(c[0]).name == 'ditto'])
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual((result['operation']['operation_id'], result['operation']['phase']),
                         (operation['operation_id'], 'failed'))
        self.assertEqual(len([c for c in mac.calls if Path(c[0]).name == 'ditto']), dittos)
        self.assertEqual(sorted(p.name for p in mac.mac_app().iterdir()), ['Contents'])
        shutil.rmtree(mac.mac_app())
        mac.codesign, mac.effect = 0, 'ok'
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual((result['operation']['operation_id'], result['operation']['phase']),
                         (operation['operation_id'], 'applied'))

    def test_an_installation_that_appears_during_the_download_is_never_copied_over(self):
        for system, machine in (('Linux', 'x86_64'), ('Darwin', 'arm64')):
            with self.subTest(system=system):
                (self.base / system).mkdir()
                host = FakeHost(self.base / system, system, machine)
                state = self.base / f'{system}-state'
                operation = cloudroom.install(host, state)['operation']
                target = host.appimage() if system == 'Linux' else host.mac_app()

                def appear():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b'the user installed their own copy meanwhile') if system == 'Linux' \
                        else (target / 'Contents').mkdir(parents=True)
                host.during_download = appear
                result = cloudroom.install(host, state, yes=True, operation=operation['operation_id'])
                self.assertEqual(result['operation']['phase'], 'failed')
                self.assertEqual([c for c in host.calls if Path(c[0]).name in ('ditto', 'hdiutil')], [])
                if system == 'Linux':
                    self.assertEqual(target.read_bytes(), b'the user installed their own copy meanwhile')
                else:
                    self.assertEqual(sorted(p.name for p in target.iterdir()), ['Contents'])

    def test_a_competing_mac_app_during_mounting_or_before_publication_is_preserved(self):
        for when in ('mount', 'publish'):
            with self.subTest(when=when):
                (self.base / when).mkdir()
                mac = FakeHost(self.base / when, 'Darwin', 'arm64')
                state = self.base / f'{when}-state'
                operation = cloudroom.install(mac, state)['operation']

                def compete(*_):
                    if not mac.mac_app().exists():
                        (mac.mac_app() / 'Contents').mkdir(parents=True)
                        (mac.mac_app() / 'Contents/competing').write_text('the user installed their own copy')
                if when == 'mount':
                    mac.during_mount = compete
                else:
                    mac.during_codesign = lambda path: compete() if path != mac.mac_app() else None
                result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
                self.assertEqual(result['operation']['phase'], 'failed')
                self.assertEqual(sorted(p.relative_to(mac.mac_app()).as_posix() for p in mac.mac_app().rglob('*')),
                                 ['Contents', 'Contents/competing'], 'nothing is merged into or over it')
                self.assertEqual((mac.mac_app() / 'Contents/competing').read_text(), 'the user installed their own copy')
                self.assertEqual([p.name for p in mac.mac_app().parent.iterdir()], ['Cloudroom.app'],
                                 'the staging copy is removed')

    def test_a_placed_copy_that_does_not_verify_is_failed_never_applied(self):
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        state = self.base / 'mac-state'
        operation = cloudroom.install(mac, state)['operation']
        mac.codesign = 1
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'failed')
        self.assertEqual(result['code'], 'cloudroom_install_failed')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_failed')
        self.assertFalse(mac.mac_app().exists())
        mac.codesign, mac.codesign_fails = 0, {mac.mac_app()}
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'failed')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_failed')

    def test_an_app_signed_by_another_team_is_never_trusted(self):
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        state = self.base / 'mac-state'
        operation = cloudroom.install(mac, state)['operation']
        mac.dmg_signer = OTHER_TEAM
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual((result['code'], result['operation']['phase']), ('cloudroom_install_failed', 'failed'))
        self.assertFalse(mac.mac_app().exists(), 'an app from another team is never published')
        (self.base / 'mac2').mkdir()
        mac2 = FakeHost(self.base / 'mac2', 'Darwin', 'arm64')
        state2 = self.base / 'mac-state-2'
        operation = cloudroom.install(mac2, state2)['operation']
        mac2.effect = 'timeout'
        cloudroom.install(mac2, state2, yes=True, operation=operation['operation_id'])
        (mac2.mac_app() / 'Contents').mkdir(parents=True)
        mac2.signers[mac2.mac_app()] = OTHER_TEAM
        result = cloudroom.install(mac2, state2, yes=True, operation=operation['operation_id'])
        self.assertEqual((result['code'], result['operation']['phase']),
                         ('cloudroom_install_uncertain', 'uncertain'))
        mac2.signers[mac2.mac_app()] = CLOUDROOM_TEAM
        result = cloudroom.install(mac2, state2, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'applied')

    def test_a_copy_that_appears_before_confirming_blocks_and_is_never_replaced(self):
        operation = self.preview()
        self.host.plant_appimage(data=b'the user installed their own copy meanwhile')
        result = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_destination_blocked')
        self.assertEqual(self.record()['operation']['phase'], 'proposed', 'nothing was attempted')
        self.assertEqual(self.host.appimage().read_bytes(), b'the user installed their own copy meanwhile')
        self.assertNotIn(RELEASE + APPIMAGE, self.host.fetched)

    def test_the_record_and_its_folder_are_synced_before_any_effect(self):
        synced = []
        real = os.fsync

        def recording(fd):
            synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
            real(fd)
        cloudroom.os.fsync = recording
        try:
            operation = self.preview()
            self.assertEqual(synced[-2:], [False, True], 'the file, then its folder')
            synced.clear()

            def failing(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError('synthetic: folder sync failed')
                real(fd)
            cloudroom.os.fsync = failing
            with self.assertRaises(OSError):
                self.install(yes=True, operation=operation['operation_id'])
        finally:
            cloudroom.os.fsync = real
        self.assertNotIn(RELEASE + APPIMAGE, self.host.fetched, 'nothing is downloaded')
        self.assertFalse(self.host.appimage().exists())

    def test_a_fresh_nested_state_path_is_durable_before_any_effect(self):
        state = self.base / 'fresh/nested/state'
        real = os.fsync
        synced = []

        def recording(fd):
            info = os.fstat(fd)
            if stat.S_ISDIR(info.st_mode):
                synced.append((info.st_dev, info.st_ino))
            real(fd)
        ids = lambda path: (os.stat(path).st_dev, os.stat(path).st_ino)
        before_download = []
        self.host.during_download = lambda: before_download.append(list(synced))
        cloudroom.os.fsync = recording
        try:
            operation = cloudroom.install(self.host, state)['operation']
            cloudroom.install(self.host, state, yes=True, operation=operation['operation_id'])
        finally:
            cloudroom.os.fsync = real
        self.assertEqual(len(before_download), 1, 'exactly one download, after the barriers')
        for parent in (self.base, self.base / 'fresh', self.base / 'fresh/nested', state, state / 'cloudroom'):
            self.assertIn(ids(parent), before_download[0], f'{parent} holds a new entry and is synced first')
        for path, mode in ((state, 0o700), (state / 'cloudroom', 0o700), (state / 'cloudroom/install.json', 0o600)):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), mode, path)
        (self.base / 'other').mkdir()
        other = FakeHost(self.base / 'other')
        existing = self.base / 'existing-state'
        existing.mkdir(mode=0o700)
        operation = cloudroom.install(other, existing)['operation']
        self.assertEqual(cloudroom.install(other, existing)['operation']['operation_id'], operation['operation_id'])
        self.assertEqual(stat.S_IMODE(os.stat(existing / 'cloudroom').st_mode), 0o700)

    def test_a_failed_parent_or_installing_record_sync_stops_before_any_effect(self):
        real = os.fsync
        for case in ('new parent', 'installing record'):
            with self.subTest(case):
                base = self.base / case.replace(' ', '-')
                base.mkdir()
                host = FakeHost(base)
                state = base / 'fresh/state'
                if case == 'installing record':
                    operation = cloudroom.install(host, state)['operation']
                target = base / 'fresh' if case == 'new parent' else state / 'cloudroom'
                fired = []

                def failing(fd):
                    info = os.fstat(fd)
                    hit = stat.S_ISDIR(info.st_mode) and os.path.exists(target) and \
                        (info.st_dev, info.st_ino) == (os.stat(target).st_dev, os.stat(target).st_ino)
                    if hit and (case == 'new parent' or
                                b'"installing"' in (state / 'cloudroom/install.json').read_bytes()):
                        fired.append(case)
                        raise OSError('synthetic: folder sync failed')
                    real(fd)
                cloudroom.os.fsync = failing
                try:
                    with self.assertRaises(OSError):
                        if case == 'new parent':
                            cloudroom.install(host, state)
                        else:
                            cloudroom.install(host, state, yes=True, operation=operation['operation_id'])
                finally:
                    cloudroom.os.fsync = real
                self.assertEqual(fired, [case], 'this barrier, and only it, was reached and failed')
                self.assertNotIn(RELEASE + APPIMAGE, host.fetched, 'nothing is downloaded')
                self.assertFalse(host.appimage().exists())
                if case == 'new parent':
                    self.assertFalse((state / 'cloudroom/install.json').exists(), 'no operation without a durable home')
                else:
                    host.dead.add(os.getpid())
                    self.assertEqual(cloudroom.status(host, state)['code'], 'cloudroom_install_uncertain')
                    retry = cloudroom.install(host, state, yes=True, operation=operation['operation_id'])
                    self.assertEqual((retry['operation']['operation_id'], retry['code']),
                                     (operation['operation_id'], 'cloudroom_installed'))

    def test_a_retry_after_a_failed_folder_sync_repairs_it_before_any_effect(self):
        real = os.fsync
        ids = lambda path: (os.stat(path).st_dev, os.stat(path).st_ino)
        for at in ('base', 'fresh', 'nested', 'state', 'cloudroom'):
            with self.subTest(at=at):
                root = self.base / f'retry-{at}'
                root.mkdir()
                host = FakeHost(root)
                state = root / 'fresh/nested/state'
                target = {'base': root, 'fresh': root / 'fresh', 'nested': root / 'fresh/nested',
                          'state': state, 'cloudroom': state / 'cloudroom'}[at]
                armed, synced = [True], []

                def fsync(fd):
                    info = os.fstat(fd)
                    if stat.S_ISDIR(info.st_mode):
                        hit = os.path.exists(target) and (info.st_dev, info.st_ino) == ids(target)
                        if hit and armed[0]:
                            armed[0] = False
                            raise OSError('synthetic: folder sync failed once')
                        synced.append((info.st_dev, info.st_ino))
                    real(fd)
                before_download = []
                host.during_download = lambda: before_download.append(list(synced))
                cloudroom.os.fsync = fsync
                try:
                    with self.assertRaises(OSError):
                        cloudroom.install(host, state)
                    self.assertFalse(armed[0], 'the fault fired on the first attempt')
                    saved = cloudroom.Records(state).read() if at == 'cloudroom' else None
                    synced.clear()
                    operation = cloudroom.install(host, state)['operation']
                    self.assertIn(ids(target), synced, f'{at} is synced again on the retry')
                    if saved is not None:
                        self.assertEqual(operation['operation_id'], saved['operation_id'], 'same identity')
                    result = cloudroom.install(host, state, yes=True, operation=operation['operation_id'])
                finally:
                    cloudroom.os.fsync = real
                self.assertEqual(result['code'], 'cloudroom_installed')
                self.assertEqual(len(before_download), 1)
                self.assertIn(ids(target), before_download[0], f'{at} repaired before the download')

    def test_a_download_is_never_an_installation_launchable_or_not(self):
        for mode in (0o644, 0o755):
            with self.subTest(mode=oct(mode)):
                base = self.base / f'download-{mode:o}'
                base.mkdir()
                self.host, self.state = FakeHost(base), base / 'state'
                download = self.host.plant_appimage(self.host.home / 'Downloads/Cloudroom-v12-x86_64.AppImage',
                                                    b'unchecked synthetic download', mode=mode)
                self.assertEqual(self.status()['code'], 'cloudroom_not_installed')
                with self.assertRaises(cloudroom.Refused):
                    self.sign_in()
                self.assertEqual(self.host.opened, [], 'the download is never launched')
                operation = self.preview()
                result = self.install(yes=True, operation=operation['operation_id'])
                self.assertEqual(result['code'], 'cloudroom_installed')
                self.assertTrue(os.access(self.host.appimage(), os.X_OK))
                self.assertEqual(download.read_bytes(), b'unchecked synthetic download', 'the download is left as it is')
                self.assertEqual(stat.S_IMODE(download.stat().st_mode), mode)
                self.assertEqual(self.sign_in()['opened'], 'app')
                self.assertEqual(self.host.opened, [[str(self.host.appimage())]], 'only the checked copy is launched')

    def test_only_the_checked_copy_at_the_checked_location_counts_as_installed(self):
        checked = (FIXTURES / APPIMAGE).read_bytes()
        cases = [('another name', 'Applications/Cloudroom-other.AppImage', b'unchecked synthetic copy'),
                 ('a renamed checked installer', f'Applications/{APPIMAGE}', checked),
                 ('an unchecked copy at the checked location', 'Applications/Cloudroom.AppImage',
                  b'unchecked synthetic copy')]
        for name, path, data in cases:
            with self.subTest(name):
                base = self.base / name.replace(' ', '-')
                base.mkdir()
                self.host, self.state = FakeHost(base), base / 'state'
                planted = self.host.plant_appimage(self.host.home / path, data)
                self.assertNotEqual(self.status()['code'], 'cloudroom_reused')
                self.assertNotEqual(self.install()['code'], 'cloudroom_reused')
                with self.assertRaises(cloudroom.Refused):
                    self.sign_in()
                self.assertEqual(self.host.opened, [], 'an unchecked AppImage is never launched')
                self.assertEqual(planted.read_bytes(), data, 'it is left as it is')
                self.assertEqual(stat.S_IMODE(planted.stat().st_mode), 0o755)

    def test_the_checked_install_counts_until_its_copy_changes(self):
        self.host.plant_appimage(self.host.home / 'Applications/Cloudroom-other.AppImage', b'unchecked synthetic copy')
        operation = self.preview()
        self.assertEqual(self.install(yes=True, operation=operation['operation_id'])['code'], 'cloudroom_installed')
        self.assertEqual(self.status()['code'], 'cloudroom_installed')
        self.assertEqual(self.sign_in()['opened'], 'app')
        self.assertEqual(self.host.opened, [[str(self.host.appimage())]], 'only the checked copy is launched')
        self.host.opened.clear()
        elsewhere = self.host.plant_appimage(self.base / 'elsewhere/Cloudroom.AppImage', (FIXTURES / APPIMAGE).read_bytes())
        for name, change in (('a link to the same bytes', lambda path: path.symlink_to(elsewhere)),
                             ('other executable bytes',
                              lambda path: self.host.plant_appimage(path, b'replaced after the checked install'))):
            with self.subTest(name):
                self.host.appimage().unlink()
                change(self.host.appimage())
                self.assertTrue(os.access(self.host.appimage(), os.X_OK))
                self.assertEqual(self.status()['code'], 'cloudroom_destination_blocked')
                with self.assertRaises(cloudroom.Refused):
                    self.sign_in()
                self.assertEqual(self.host.opened, [], 'a changed copy is never launched')

    def test_a_blocked_destination_wins_over_an_existing_launcher(self):
        def unchecked():
            self.host.launcher('signed-out')
            self.host.plant_appimage(data=b'unchecked synthetic copy')
            return None

        def changed_after_opening():
            operation = self.preview()
            self.assertEqual(self.install(yes=True, operation=operation['operation_id'])['code'], 'cloudroom_installed')
            self.host.launcher('signed-out')
            self.assertEqual(self.status()['code'], 'cloudroom_login_missing')
            self.host.plant_appimage(data=b'unchecked synthetic copy')
            return operation['operation_id']

        def appears_before_confirming():
            operation = self.preview()
            unchecked()
            return operation['operation_id']

        for name, arrange in (('an unchecked copy', unchecked), ('the checked copy changed after opening',
                                                                 changed_after_opening),
                              ('an unchecked copy before confirming', appears_before_confirming)):
            with self.subTest(name):
                base = self.base / name.replace(' ', '-')
                base.mkdir()
                self.host, self.state = FakeHost(base), base / 'state'
                operation = arrange()
                self.host.calls.clear()
                self.host.fetched.clear()
                self.assertEqual(self.status()['code'], 'cloudroom_destination_blocked')
                self.assertEqual(self.install()['code'], 'cloudroom_destination_blocked')
                if operation is not None:
                    confirmed = self.install(yes=True, operation=operation)
                    self.assertEqual(confirmed['code'], 'cloudroom_destination_blocked')
                with self.assertRaises(cloudroom.Refused):
                    self.sign_in()
                self.assertEqual(self.host.calls, [], 'no launcher call runs')
                self.assertEqual(self.host.opened, [], 'nothing is opened')
                self.assertNotIn(RELEASE + APPIMAGE, self.host.fetched, 'nothing is downloaded')
                self.assertEqual(self.host.appimage().read_bytes(), b'unchecked synthetic copy')
                self.assertTrue(os.access(self.host.appimage(), os.X_OK))

    def test_an_unlaunchable_file_at_the_destination_is_refused_never_overwritten_or_made_executable(self):
        occupied = self.host.plant_appimage(data=b'a non-executable file the user put here', mode=0o644)
        self.assertEqual(self.status()['code'], 'cloudroom_destination_blocked')
        result = self.install()
        self.assertEqual(result['code'], 'cloudroom_destination_blocked')
        self.assertIsNone(result['operation'])
        with self.assertRaises(cloudroom.Refused):
            self.sign_in()
        self.assertEqual(occupied.read_bytes(), b'a non-executable file the user put here')
        self.assertEqual(stat.S_IMODE(occupied.stat().st_mode), 0o644)
        self.assertEqual((self.host.fetched, self.host.calls, self.host.opened), ([], [], []))

    def test_the_install_record_is_owner_only_and_exact(self):
        self.preview()
        path = self.state / 'cloudroom/install.json'
        good = path.read_bytes()
        for name, mutate in (('world readable', lambda: path.chmod(0o644)),
                             ('duplicate key', lambda: path.write_bytes(good.replace(b'{', b'{"schema":"x",', 1))),
                             ('unknown phase', lambda: path.write_bytes(good.replace(b'"proposed"', b'"done"'))),
                             ('extra key', lambda: path.write_bytes(good.replace(b'{', b'{"extra":1,', 1)))):
            with self.subTest(name):
                path.write_bytes(good)
                path.chmod(0o600)
                mutate()
                with self.assertRaises(cloudroom.Refused):
                    self.status()
        path.write_bytes(good)
        path.chmod(0o600)


class Login(Base):
    def installed(self, status):
        operation = self.install()['operation']
        self.assertEqual(self.install(yes=True, operation=operation['operation_id'])['code'], 'cloudroom_installed')
        self.host.fetched.clear()
        if status is not None:
            self.host.launcher(status)

    def test_login_states_from_the_supported_read(self):
        for status, code in (('signed-in', 'cloudroom_login_verified'), ('signed-out', 'cloudroom_login_missing'),
                             ('signing-in', 'cloudroom_login_unknown'), ('timeout', 'cloudroom_login_unknown'),
                             (None, 'cloudroom_installed')):
            with self.subTest(status=status):
                base = self.base / str(status)
                base.mkdir()
                self.host, self.state = FakeHost(base), base / 'state'
                self.installed(status)
                self.assertEqual(self.status()['code'], code)

    def test_only_an_exact_positive_account_verifies(self):
        signed_in = json.loads((FIXTURES / 'cloud-signed-in.json').read_text())
        bad = {
            'account missing': {k: v for k, v in signed_in.items() if k != 'account'},
            'account empty id': dict(signed_in, account={'id': '', 'email': 'owner@example.invalid'}),
            'account extra key': dict(signed_in, account=dict(signed_in['account'], token='x')),
            'account as list': dict(signed_in, account=['acct_synthetic']),
            'still signing in': dict(signed_in, signingIn=True),
            'signed out flag': dict(signed_in, signedOut=True),
            'self hosted': dict(signed_in, selfHosted=True),
            'signingIn as string': dict(signed_in, signingIn='false'),
            'not an object': [signed_in],
        }
        self.installed('signed-in')
        for name, value in bad.items():
            with self.subTest(name):
                self.host.status = json.dumps(value).encode()
                self.assertEqual(self.status()['code'], 'cloudroom_login_unknown')
        for name, raw in (('duplicate key', b'{"account":null,"account":{"id":"a","email":"b"},"signingIn":false}'),
                          ('not JSON', b'Signed out\n'), ('empty', b'')):
            with self.subTest(name):
                self.host.status = raw
                self.assertEqual(self.status()['code'], 'cloudroom_login_unknown')
        self.host.status = 'signed-in'
        self.assertEqual(self.status()['code'], 'cloudroom_login_verified')

    def test_a_reachable_inventory_or_listed_harness_never_verifies(self):
        self.installed('timeout')
        self.assertEqual(self.status()['code'], 'cloudroom_login_unknown')
        self.assertEqual(self.host.calls, [[str(self.host.home / '.local/bin/room-cli'), 'cloud', 'status', '--json']])

    def test_sign_in_opens_cloudrooms_own_sign_in_once(self):
        self.installed('signed-out')
        result = self.sign_in()
        self.assertEqual(result['opened'], 'sign_in')
        self.assertEqual([argv[-1] for argv in self.host.opened], [SIGN_IN_URL])
        self.assertEqual(self.host.opened[0][0], '/usr/bin/xdg-open')
        self.assertEqual(self.host.calls.count([str(self.host.home / '.local/bin/room-cli'), 'cloud', 'sign-in', '--json']), 1)
        self.assertNotIn('synthetic-nonce', json.dumps(result), 'the sign-in link is never printed')
        self.assertFalse((self.state / 'cloudroom').exists() and
                         any(b'synthetic-nonce' in p.read_bytes() for p in (self.state / 'cloudroom').iterdir() if p.is_file()),
                         'or saved')
        self.assertEqual(result['code'], 'cloudroom_login_missing', 'read back, not assumed signed in')
        self.host.status = 'signed-in'
        self.assertEqual(self.status()['code'], 'cloudroom_login_verified')

    def test_an_existing_current_login_is_reused_with_no_second_sign_in(self):
        self.installed('signed-in')
        result = self.sign_in()
        self.assertEqual(result['code'], 'cloudroom_login_verified')
        self.assertIsNone(result['opened'])
        self.assertEqual(self.host.opened, [])
        self.assertNotIn(['cloud', 'sign-in', '--json'], [c[1:] for c in self.host.calls])

    def test_before_cloudroom_has_ever_opened_sign_in_opens_the_app_itself_once(self):
        self.installed(None)
        result = self.sign_in()
        self.assertEqual(result['opened'], 'app')
        self.assertEqual(self.host.opened, [[str(self.host.appimage())]])
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        mac.mac_app().mkdir(parents=True)
        self.assertEqual(cloudroom.sign_in(mac, self.base / 'mac-state')['opened'], 'app')
        self.assertEqual(mac.opened, [['/usr/bin/open', str(mac.mac_app())]])

    def test_sign_in_launches_only_an_executable_app_at_the_real_boundary(self):
        marker = self.base / 'launched'
        real = cloudroom.Host(system='Linux', machine='x86_64', home=self.host.home, root=self.host.root)
        self.host.open = real.open
        self.host.publish_appimage(f'#!/bin/sh\necho launched > {marker}\n'.encode())
        self.installed(None)
        app = self.host.appimage()
        self.assertEqual(self.sign_in()['opened'], 'app')
        for _ in range(200):
            if marker.exists():
                break
            time.sleep(0.01)
        self.assertEqual(marker.read_text(), 'launched\n')
        app.unlink()
        self.host.plant_appimage(self.host.home / 'Downloads/Cloudroom-v12-x86_64.AppImage', mode=0o644)
        with self.assertRaises(cloudroom.Refused):
            self.sign_in()

    def test_a_sign_in_link_not_on_cloudrooms_site_is_never_opened(self):
        self.installed('signed-out')
        for url in ('http://www.cloudroom.dev/login', 'https://www.cloudroom.dev.example.invalid/login',
                    'https://www.cloudroom.dev@example.invalid/login', 'https://www.cloudroom.dev:8443/login',
                    'javascript:alert(1)', '-https://www.cloudroom.dev/login'):
            with self.subTest(url=url):
                self.host.sign_in_reply = json.dumps({'url': url}).encode()
                result = self.sign_in()
                self.assertIsNone(result['opened'])
                self.assertEqual(self.host.opened, [])

    def said(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            cloudroom.main(['sign-in', '--state-dir', str(self.state)], host=self.host)
        result = json.loads(out.getvalue())
        self.assertEqual(set(result), {'schema', 'code', 'operation', 'opened'})
        return result, err.getvalue()

    def test_a_failed_sign_in_never_prints_cloudrooms_raw_output(self):
        self.installed('signed-out')
        secret = (b'Retry at https://www.cloudroom.dev/login?desktop=synthetic-nonce-0001 as owner@example.invalid\n'
                  b'token: synthetic-token-0123456789abcdefghij\n\x1b[31mpassword=hunter2\x1b[0m\n'
                  b'{\n  "error": "refresh failed",\n  "refresh_token":\n\n    "rt1"\n}\n'
                  b'Your refresh token for this session is\n  rt2\n'
                  b'{"message": "Your token is:\\n rt3", "refresh_token": {"detail": "rt4"}}\n')
        run = 'openwiz-cloudroom: to see its full output, run: "$HOME"/.local/bin/room-cli cloud sign-in --json\n'
        cases = (
            (1, b'', secret, "openwiz-cloudroom: CloudRoom's sign-in exited with status 1 and gave no usable link.\n" + run),
            (1, secret, b'', "openwiz-cloudroom: CloudRoom's sign-in exited with status 1 and gave no usable link.\n" + run),
            (0, b'{"error": {"message": "rt5"}}', b'',
             "openwiz-cloudroom: CloudRoom's sign-in exited with status 0 and gave no usable link.\n" + run),
            (None, b'', secret + b'getaddrinfo ENOTFOUND www.cloudroom.dev',
             "openwiz-cloudroom: CloudRoom's sign-in did not answer within 30 seconds; is CloudRoom running?\n"
             'openwiz-cloudroom: CloudRoom reported: CloudRoom could not look up its server; check the network.\n' + run),
            (1, b'', b'connect ECONNREFUSED 127.0.0.1:4100 rt6\nconnect ECONNREFUSED 127.0.0.1:4100 rt6\n',
             "openwiz-cloudroom: CloudRoom's sign-in exited with status 1 and gave no usable link.\n"
             'openwiz-cloudroom: CloudRoom reported: CloudRoom could not connect; is CloudRoom running?\n' + run),
            (1, b'', b'getaddrinfo enotfound www.cloudroom.dev\n',
             "openwiz-cloudroom: CloudRoom's sign-in exited with status 1 and gave no usable link.\n" + run),
        )
        for code, reply, said, expected in cases:
            with self.subTest(code=code, reply=reply, said=said):
                self.host.sign_in_code, self.host.sign_in_reply, self.host.sign_in_said = code, reply, said
                result, err = self.said()
                self.assertEqual((result['code'], result['opened']), ('cloudroom_login_missing', None))
                self.assertEqual(self.host.opened, [])
                self.assertEqual(err, expected)

    def test_an_opener_that_fails_is_shown_and_not_counted_as_opened(self):
        self.installed('signed-out')
        self.host.open_result = (4, b'xdg-open: no method available for opening '
                                    b'https://www.cloudroom.dev/login?desktop=synthetic-nonce-0001\n')
        result, err = self.said()
        self.assertIsNone(result['opened'])
        self.assertEqual(err, 'openwiz-cloudroom: xdg-open exited with status 4; the sign-in page did not open.\n'
                              'openwiz-cloudroom: xdg-open reported: No browser is set up to open the sign-in page.\n'
                              'openwiz-cloudroom: to see its full output, run: /usr/bin/xdg-open https://www.cloudroom.dev\n')
        self.host.open_result = (None, b'')
        result, err = self.said()
        self.assertEqual((result['opened'], err), ('sign_in', ''))

    def test_an_app_that_fails_at_launch_shows_its_status_and_known_errors_only(self):
        real = cloudroom.Host(system='Linux', machine='x86_64', home=self.host.home, root=self.host.root)
        self.host.open = real.open
        self.host.publish_appimage(b'#!/bin/sh\necho "error while loading shared libraries: libnss3.so" >&2\n'
                                   b'echo "see https://example.invalid/help?session=synthetic-0001" >&2\nexit 1\n')
        self.installed(None)
        with patch.object(cloudroom, 'OPEN_WAIT', 120):
            result, err = self.said()
        self.assertIsNone(result['opened'])
        self.assertEqual(err, 'openwiz-cloudroom: CloudRoom exited with status 1 at launch.\n'
                              'openwiz-cloudroom: CloudRoom reported: A system library CloudRoom needs is missing.\n'
                              'openwiz-cloudroom: to see its full output, run: "$HOME"/Applications/Cloudroom.AppImage\n')

    def test_a_launch_that_outlives_the_wait_never_fills_a_file(self):
        go, wrote, pidfile, app = (self.base / name for name in ('go', 'wrote', 'pid', 'app'))
        app.write_text(f'#!/bin/sh\necho $$ > {pidfile}\nwhile [ ! -e {go} ]; do sleep 0.05; done\n'
                       f'head -c 4194304 /dev/zero\necho done > {wrote}\nexec sleep 60\n')
        app.chmod(0o700)
        real = cloudroom.Host(system='Linux', machine='x86_64', home=self.host.home, root=self.host.root)
        with patch.object(cloudroom, 'OPEN_WAIT', 0.5):
            self.assertEqual(real.open([str(app)]), (None, b''))
        for _ in range(400):
            if pidfile.exists() and pidfile.read_text().strip():
                break
            time.sleep(0.05)
        pid = int(pidfile.read_text())
        self.addCleanup(lambda: os.kill(pid, 9))
        go.touch()
        for _ in range(400):
            if wrote.exists():
                break
            time.sleep(0.05)
        self.assertEqual(wrote.read_text(), 'done\n', 'later output is drained, never blocking the app')
        for fd in (1, 2):
            self.assertTrue(os.readlink(f'/proc/{pid}/fd/{fd}').startswith('pipe:'), 'no file holds its output')
        noisy = self.base / 'noisy'
        noisy.write_text('#!/bin/sh\nhead -c 300000 /dev/zero | tr "\\0" x\nexit 7\n')
        noisy.chmod(0o700)
        with patch.object(cloudroom, 'OPEN_WAIT', 120):
            code, out = real.open([str(noisy)])
        self.assertEqual((code, len(out)), (7, 1 << 16))

    def test_a_headless_linux_machine_is_told_what_sign_in_needs(self):
        fuse_runtime = b'\x7fELF synthetic AppImage runtime libfuse.so.2 fusermount'
        cases = {
            'no desktop session': (dict(environ={}), ['needs a desktop session', 'DISPLAY or WAYLAND_DISPLAY',
                                                      'Next: run sign-in from a desktop session']),
            'empty display': (dict(environ={'DISPLAY': '', 'WAYLAND_DISPLAY': ''}), ['needs a desktop session']),
            'no /dev/fuse': (dict(missing='dev/fuse'), ['needs FUSE', '/dev/fuse', 'Next: install FUSE']),
            'no fusermount': (dict(missing='usr/bin/fusermount3'), ['needs FUSE', 'fusermount']),
            'no libfuse2': (dict(app=fuse_runtime), ['libfuse.so.2', 'libfuse2']),
            'headless and no FUSE': (dict(environ={}, missing='dev/fuse'), ['needs a desktop session', 'needs FUSE']),
        }
        for status in ('signed-out', 'signed-in', None):
            for index, (name, (case, words)) in enumerate(cases.items()):
                with self.subTest(name, status=status):
                    base = self.base / f'headless-{index}-{status}'
                    base.mkdir()
                    self.host, self.state = FakeHost(base), base / 'state'
                    if 'app' in case:
                        self.host.publish_appimage(case['app'])
                    self.installed(status)
                    self.host.environ = case.get('environ', self.host.environ)
                    if 'missing' in case:
                        (self.host.root / case['missing']).unlink()
                    self.host.calls.clear()
                    with self.assertRaises(cloudroom.Refused) as refused:
                        self.sign_in()
                    for word in words:
                        self.assertIn(word, str(refused.exception))
                    self.assertEqual(self.host.opened, [])
                    self.assertEqual([c for c in self.host.calls if Path(c[0]).name == 'room-cli'], [])
        base = self.base / 'with libfuse2'
        base.mkdir()
        self.host, self.state = FakeHost(base), base / 'state'
        self.host.publish_appimage(fuse_runtime)
        self.installed(None)
        (self.host.root / 'usr/lib/x86_64-linux-gnu').mkdir(parents=True)
        (self.host.root / 'usr/lib/x86_64-linux-gnu/libfuse.so.2').write_text('synthetic')
        self.assertEqual(self.sign_in()['opened'], 'app')
        (self.base / 'mac').mkdir()
        mac = FakeHost(self.base / 'mac', 'Darwin', 'arm64')
        mac.environ = {}
        mac.mac_app().mkdir(parents=True)
        self.assertEqual(cloudroom.sign_in(mac, self.base / 'mac-state')['opened'], 'app')

    def test_sign_in_never_takes_a_password_or_token(self):
        result = subprocess.run([sys.executable, '-I', str(HERE / 'cloudroom.py'), 'sign-in', '--help'],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stderr)
        for word in ('password', 'token', '--key', 'secret'):
            text = ' '.join(result.stdout.lower().split())
            self.assertNotIn(word, text.replace('never asks for a password or token', ''))

    def test_sign_in_needs_an_installation(self):
        with self.assertRaises(cloudroom.Refused):
            self.sign_in()
        self.assertEqual(self.host.opened, [])


class Allowlist(Base):
    ALLOWLIST = HERE.parents[2] / 'crates/adapters/cloudroom/src/allowlist.rs'
    PINNED = [['cloud', 'status', '--json'], ['cloud', 'sign-in', '--json']]

    def test_the_tool_builds_only_the_allowlists_two_calls(self):
        text = self.ALLOWLIST.read_text()
        self.assertIn('pub const SETUP_LAUNCHER: &str = ".local/bin/room-cli";', text)
        self.assertIn('pub const SETUP_CALLS: [&[&str]; 2] = [\n    &["cloud", "status", "--json"],\n'
                      '    &["cloud", "sign-in", "--json"],\n];', text)
        self.assertEqual([list(call) for call in cloudroom.ROOM_CLI_CALLS], self.PINNED)
        launcher = str(self.host.home / '.local/bin/room-cli')
        for call in self.PINNED:
            self.host.launcher('signed-out')
            cloudroom.room_cli(self.host, tuple(call))
            self.assertEqual(self.host.calls[-1], [launcher, *call])
        calls = len(self.host.calls)
        for other in (('cloud', 'logout', '--json'), ('cloud', 'status'), ('cloud', 'status', '--json', '--x'),
                      ('thread', 'list', '--json'), ('--version',), (), ['cloud', 'status', '--json']):
            with self.subTest(other=other):
                with self.assertRaises(cloudroom.Refused):
                    cloudroom.room_cli(self.host, other)
        self.assertEqual(len(self.host.calls), calls, 'a refused call runs nothing')

    def test_every_path_runs_only_the_two_calls(self):
        for system, machine in (('Linux', 'x86_64'), ('Darwin', 'arm64')):
            for status in ('signed-in', 'signed-out', 'signing-in', 'timeout'):
                base = self.base / f'{system}-{status}'
                base.mkdir()
                host = FakeHost(base, system, machine)
                state = base / 'state'
                operation = cloudroom.install(host, state)['operation']
                cloudroom.install(host, state, yes=True, operation=operation['operation_id'])
                cloudroom.sign_in(host, state)
                host.launcher(status)
                cloudroom.status(host, state)
                cloudroom.sign_in(host, state)
                ran = [c[1:] for c in host.calls if Path(c[0]).name == 'room-cli']
                self.assertTrue(ran, f'{system} {status}')
                self.assertTrue(all(c in self.PINNED for c in ran), ran)
                self.assertTrue(all(c[0] == str(host.home / '.local/bin/room-cli')
                                    for c in host.calls if Path(c[0]).name == 'room-cli'))


class Packaged(Base):
    def test_deeply_nested_release_json_gets_the_fixed_refusal_without_writes(self):
        responses = {
            GUIDE: (FIXTURES / 'setup.md').read_bytes(),
            API: b'[' * 500000 + b'0' + b']' * 500000,
        }
        fetched = []

        def fetch(opener, request, **kwargs):
            fetched.append(request.full_url)
            return io.BytesIO(responses[request.full_url])

        folder = self.state / 'cloudroom'
        folder.mkdir(parents=True, mode=0o700)
        self.state.chmod(0o700)
        (folder / '.lock').touch(mode=0o600)

        def files():
            return {p.relative_to(self.base).as_posix(): p.read_bytes() if p.is_file() else None
                    for p in self.base.rglob('*')}

        before = files()
        out, err = io.StringIO(), io.StringIO()
        real_is_file = Path.is_file
        with patch.dict(os.environ, HOME=str(self.host.home)), \
                patch('platform.system', return_value='Linux'), \
                patch('platform.machine', return_value='x86_64'), \
                patch.object(Path, 'is_file', lambda p: False if p == Path('/usr/local/bin/room-cli') else real_is_file(p)), \
                patch('urllib.request.OpenerDirector.open', fetch), \
                patch('subprocess.Popen', side_effect=AssertionError('no program may run')), \
                patch.object(sys, 'argv', [str(HERE / 'cloudroom.py'), 'install', '--state-dir', str(self.state)]), \
                redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit) as stopped:
                runpy.run_path(str(HERE / 'cloudroom.py'), run_name='__main__')
        self.assertEqual(stopped.exception.code, 5)
        self.assertEqual(out.getvalue(), '')
        self.assertEqual(err.getvalue(),
                         'openwiz-cloudroom: refused: the CloudRoom step could not be completed safely\n')
        self.assertEqual(fetched, [GUIDE, API], 'no installer or checksum is fetched')
        self.assertEqual(files(), before, 'no files, records or applications are written')

    def test_the_command_line_reports_status_as_fixed_json(self):
        result = subprocess.run([sys.executable, '-I', str(HERE / 'cloudroom.py'), 'status', '--state-dir', str(self.state)],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                env={'PATH': '/usr/bin:/bin', 'HOME': str(self.host.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['schema'], 'openwiz.cloudroom-setup.v1')
        self.assertIn(value['code'], ('cloudroom_not_installed', 'cloudroom_unsupported', 'cloudroom_login_verified'))

    def test_the_setup_check_records_the_tools_code_from_the_packaged_runtime(self):
        runtime = self.base / 'build/runtime'
        for source, name in ((HERE.parent / 'setup/setup.py', 'setup/setup.py'),
                             (HERE.parent / 'setup/store.py', 'setup/store.py'), (HERE / 'cloudroom.py', 'cloudroom/cloudroom.py')):
            (runtime / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, runtime / name)
        home = self.host.home
        calls = self.base / 'calls.log'
        launcher = home / '.local/bin/room-cli'
        launcher.parent.mkdir(parents=True)
        launcher.write_text(f'#!/bin/sh\necho "$*" >> {calls}\ncat {FIXTURES / "cloud-signed-in.json"}\n')
        launcher.chmod(0o700)
        for fixture, expected in (('cloud-signed-in.json', 'cloudroom_login_verified'),
                                  ('cloud-signed-out.json', 'cloudroom_login_missing')):
            with self.subTest(fixture):
                launcher.write_text(f'#!/bin/sh\necho "$*" >> {calls}\ncat {FIXTURES / fixture}\n')
                result = subprocess.run([sys.executable, '-I', '-B', str(runtime / 'setup/setup.py'), 'check',
                                         '--state-dir', str(self.state)], capture_output=True, text=True,
                                        stdin=subprocess.DEVNULL, cwd=self.base,
                                        env={'PATH': '/usr/bin:/bin', 'HOME': str(home)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['results']['cloudroom'], expected)
                saved = json.loads((self.state / 'setup/state.json').read_text())
                self.assertEqual(saved['observations']['cloudroom']['code'], expected)
                self.assertNotIn('owner@example.invalid', result.stdout + (self.state / 'setup/state.json').read_text())
        self.assertEqual(calls.read_text(), 'cloud status --json\n' * 2, 'one login read per check, nothing else')


class CloudThread(Base):
    def test_cloud_thread_is_accepted_on_linux_arm64_and_x86_64(self):
        for machine in ('aarch64', 'x86_64'):
            with self.subTest(machine=machine):
                base = self.base / f'cloud-{machine}'
                base.mkdir()
                host = FakeHost(base, 'Linux', machine)
                host.environ = {}
                (host.root / 'dev/fuse').unlink()
                host.cloud_launcher()
                state = base / 'state'
                for result in (cloudroom.status(host, state),
                               cloudroom.install(host, state),
                               cloudroom.install(host, state, yes=True),
                               cloudroom.sign_in(host, state)):
                    self.assertEqual(result['code'], 'cloudroom_login_verified')
                    self.assertIsNone(result['operation'])
                    self.assertIsNone(result['opened'])
                    raw = json.dumps(result)
                    self.assertNotIn('thr_syn_0001', raw)
                    self.assertNotIn('prj_syn_0001', raw)
                self.assertEqual(host.fetched, [])
                self.assertEqual(host.opened, [])
                self.assertTrue(host.calls)
                self.assertTrue(all(call == [str(host.root / 'usr/local/bin/room-cli'), 'status', '--json']
                                    for call in host.calls), host.calls)

    def test_cloud_thread_detection_fails_closed_on_bad_or_non_linux_answers(self):
        cases = (
            ('Linux', 'aarch64', 'timeout', 'cloudroom_unsupported'),
            ('Linux', 'aarch64', b'not json', 'cloudroom_unsupported'),
            ('Linux', 'aarch64', b'{"thread":{"id":"thr_syn_0001","id":"thr_syn_0002","projectId":"prj_syn_0001"}}',
             'cloudroom_unsupported'),
            ('Linux', 'aarch64', {'thread': {'id': '', 'projectId': 'prj_syn_0001'}}, 'cloudroom_unsupported'),
            ('Linux', 'aarch64', {'thread': {'id': 'thr_syn_0001'}}, 'cloudroom_unsupported'),
            ('Linux', 'aarch64', {'thread': {'id': 'thr_syn_0001', 'projectId': 'prj_syn_0001', 'archived': True}},
             'cloudroom_unsupported'),
            ('Linux', 'x86_64', b'{}', 'cloudroom_not_installed'),
            ('Darwin', 'x86_64', {'thread': {'id': 'thr_syn_0001', 'projectId': 'prj_syn_0001', 'archived': False}},
             'cloudroom_unsupported'),
        )
        for index, (system, machine, reply, expected) in enumerate(cases):
            with self.subTest(index=index, system=system, machine=machine):
                base = self.base / f'bad-{index}'
                base.mkdir()
                host = FakeHost(base, system, machine)
                host.cloud_launcher(reply)
                self.assertEqual(cloudroom.status(host, base / 'state')['code'], expected)


if __name__ == '__main__':
    unittest.main()
