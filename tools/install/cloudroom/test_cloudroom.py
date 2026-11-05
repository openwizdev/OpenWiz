#!/usr/bin/env python3
"""#2201: the CloudRoom install, reuse and sign-in tool, on recording fakes only.

No test downloads, installs, opens or signs in to anything real: every program,
URL and file the tool touches goes through the FakeHost below, inside a private
temporary directory. Expected values come from the fixtures and the contract
(contracts/public-cloudroom-setup.v1.md), never from the tool's own helpers.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

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
# The published digests, read from the fixture's own SHA256SUMS.txt lines.
SUMS = {line.split('  ')[1]: line.split('  ')[0]
        for line in (FIXTURES / 'SHA256SUMS.txt').read_text().splitlines()}


def load():
    spec = importlib.util.spec_from_file_location('cloudroom_under_test', HERE / 'cloudroom.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloudroom = load()


class Lost(BaseException):
    """The tool's process dies here (a crash or kill): nothing after it runs."""


class FakeHost(cloudroom.Host):
    """Records every program, URL and open; the tests steer each answer."""

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
        self.status = None          # room-cli cloud status --json: fixture name, bytes, or 'timeout'
        self.sign_in_reply = (FIXTURES / 'cloud-sign-in.json').read_bytes()
        self.lose_download = False  # the process dies mid-download
        self.during_download = None  # something else happens on the host meanwhile
        self.during_mount = None     # ... while the disk image mounts
        self.during_codesign = None  # ... while a copy is being verified: (path) -> None
        self.effect = 'ok'          # ditto/hdiutil: 'ok', 'fail', 'timeout', 'partial'
        self.codesign = 0
        self.codesign_fails = set()  # paths whose signature check fails even when codesign is 0
        self.dead = set()

    # --- the host's seams -------------------------------------------------
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
                return 0, self.sign_in_reply
            return 2, b''
        if name == 'hdiutil' and argv[1] == 'attach':
            mount = Path(argv[argv.index('-mountpoint') + 1])
            (mount / 'Cloudroom.app/Contents').mkdir(parents=True)
            (mount / 'Cloudroom.app/Contents/Info.plist').write_text('synthetic')
            if self.during_mount:
                self.during_mount()
            return 0, b''
        if name == 'hdiutil' and argv[1] == 'detach':
            shutil.rmtree(argv[2], ignore_errors=True)
            return 0, b''
        if name == 'ditto':
            # Like ditto: copies into an existing folder too, merging and overwriting.
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
            return (1 if Path(argv[-1]) in self.codesign_fails else self.codesign), b''
        return 127, b''

    def open(self, argv):
        self.opened.append(list(argv))

    def alive(self, pid):
        return pid not in self.dead

    # --- helpers for the tests --------------------------------------------
    def launcher(self, status='signed-in'):
        self.status = status
        path = self.home / '.local/bin/room-cli'
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
        """Every effect the tool caused: programs other than the login read, opens and installs."""
        return ([c for c in self.host.calls if c[1:] != ['cloud', 'status', '--json']], self.host.opened,
                self.host.appimage().exists(), self.host.mac_app().exists())


class Detection(Base):
    """An existing installation is reused: never reinstalled, replaced or downgraded."""

    def test_no_installation_is_not_installed(self):
        self.assertEqual(self.status()['code'], 'cloudroom_not_installed')
        self.assertFalse(self.state.exists(), 'a read-only status writes nothing')

    def test_each_existing_installation_is_reused_and_never_reinstalled(self):
        cases = [('Linux', 'x86_64', 'home', 'Applications/Cloudroom.AppImage'),
                 ('Linux', 'x86_64', 'home', 'Downloads/Cloudroom-v12-x86_64.AppImage'),
                 ('Linux', 'x86_64', 'home', '.local/bin/room-cli'),
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
                # CloudRoom's launcher means it has opened here: its login is read, and only that.
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
        # A retry applies nothing twice.
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
        for at, tampered in enumerate((good + b'more', good[:-2] + b'X\n')):  # another size, then the same size
            if at:
                self.host.web[RELEASE + APPIMAGE] = good
                operation = self.preview()  # a refused operation needs a new preview
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
        # The retry reconciles first: nothing is installed, so the same operation tries again.
        self.host.lose_download = False  # the lost process stays dead; this is a new attempt
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
        mac.effect = 'timeout'  # ditto copied, but its answer was lost
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_install_uncertain')
        self.assertEqual(result['operation']['phase'], 'uncertain')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_uncertain')
        self.assertFalse(mac.mac_app().exists(), 'an unanswered copy is never published')
        # Reconciled against the actual installation first: nothing is there, so
        # the same operation copies again, verifies and publishes.
        mac.effect = 'ok'
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['operation_id'], operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual(result['code'], 'cloudroom_installed')
        self.assertTrue((mac.mac_app() / 'Contents/Info.plist').is_file())
        self.assertEqual(len([c for c in mac.calls if Path(c[0]).name == 'hdiutil' and c[1] == 'attach']), 2)
        # A signed app found when reconciling is applied without copying again.
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
        (mac.mac_app() / 'Contents').mkdir(parents=True)  # something appeared that does not verify
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
        # R1: a resuming agent's preview returns the failed operation, never reuse.
        for residue in (False, True):
            with self.subTest(residue=residue):
                if residue:  # a copy appears that does not verify
                    (mac.mac_app() / 'Contents').mkdir(parents=True)
                    mac.codesign = 1
                preview = cloudroom.install(mac, state)
                self.assertEqual(preview['code'], 'cloudroom_install_failed')
                self.assertEqual(preview['operation']['operation_id'], operation['operation_id'])
        # A retry reconciles with the same id: an unverifiable residue keeps it failed, untouched.
        dittos = len([c for c in mac.calls if Path(c[0]).name == 'ditto'])
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual((result['operation']['operation_id'], result['operation']['phase']),
                         (operation['operation_id'], 'failed'))
        self.assertEqual(len([c for c in mac.calls if Path(c[0]).name == 'ditto']), dittos)
        self.assertEqual(sorted(p.name for p in mac.mac_app().iterdir()), ['Contents'])
        # With the residue gone, the same operation installs.
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
                else:  # while OpenWiz's own copy is verified, just before it would be published
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
        mac.codesign = 1  # the copy finished, but Apple's signature check refuses it
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'failed')
        self.assertEqual(result['code'], 'cloudroom_install_failed')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_failed')
        self.assertFalse(mac.mac_app().exists())
        # The staged copy verifies, but the published one does not: still never applied.
        mac.codesign, mac.codesign_fails = 0, {mac.mac_app()}
        result = cloudroom.install(mac, state, yes=True, operation=operation['operation_id'])
        self.assertEqual(result['operation']['phase'], 'failed')
        self.assertEqual(cloudroom.status(mac, state)['code'], 'cloudroom_install_failed')

    def test_an_installation_that_appears_before_confirming_is_reused_not_replaced(self):
        operation = self.preview()
        self.host.plant_appimage(data=b'the user installed their own copy meanwhile')
        result = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_reused')
        self.assertEqual(self.host.appimage().read_bytes(), b'the user installed their own copy meanwhile')
        self.assertNotIn(RELEASE + APPIMAGE, self.host.fetched)

    def test_the_record_and_its_folder_are_synced_before_any_effect(self):
        # R3: each save syncs the file and then its folder; a failed folder sync
        # stops the install before any effect.
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
        # R3 re-check: every folder created on first use is synced into its parent,
        # and the record's folder after each save, all before the first download.
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
        # Owner-only state, folder and record, as before.
        for path, mode in ((state, 0o700), (state / 'cloudroom', 0o700), (state / 'cloudroom/install.json', 0o600)):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), mode, path)
        # A state folder that already exists still works, and its existing parent needs no new sync.
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
                    # The operation keeps its identity: once its process is gone it is
                    # uncertain, and a retry with the same id reconciles, then installs.
                    host.dead.add(os.getpid())
                    self.assertEqual(cloudroom.status(host, state)['code'], 'cloudroom_install_uncertain')
                    retry = cloudroom.install(host, state, yes=True, operation=operation['operation_id'])
                    self.assertEqual((retry['operation']['operation_id'], retry['code']),
                                     (operation['operation_id'], 'cloudroom_installed'))

    def test_a_retry_after_a_failed_folder_sync_repairs_it_before_any_effect(self):
        # R3 on #2772: a folder whose parent sync failed still exists. Every retry
        # syncs it again (and the record's folder) before any download, and keeps
        # the operation's identity where one was saved.
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

    def test_an_unlaunchable_download_is_not_an_installation(self):
        # R4: a plain download (not executable) in ~/Downloads does not block a checked install.
        download = self.host.plant_appimage(self.host.home / 'Downloads/Cloudroom-v12-x86_64.AppImage', mode=0o644)
        self.assertEqual(self.status()['code'], 'cloudroom_not_installed')
        operation = self.preview()
        result = self.install(yes=True, operation=operation['operation_id'])
        self.assertEqual(result['code'], 'cloudroom_installed')
        self.assertTrue(os.access(self.host.appimage(), os.X_OK))
        self.assertEqual(stat.S_IMODE(download.stat().st_mode), 0o644, 'the download is left as it is')

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
    """One sign-in screen: CloudRoom's own sign-in opens once; signed in only on positive evidence."""

    def installed(self, status):
        self.host.plant_appimage()
        if status is not None:
            self.host.launcher(status)

    def test_login_states_from_the_supported_read(self):
        for status, code in (('signed-in', 'cloudroom_login_verified'), ('signed-out', 'cloudroom_login_missing'),
                             ('signing-in', 'cloudroom_login_unknown'), ('timeout', 'cloudroom_login_unknown'),
                             (None, 'cloudroom_reused')):
            with self.subTest(status=status):
                base = self.base / str(status)
                base.mkdir()
                self.host = FakeHost(base)
                self.installed(status)
                self.assertEqual(cloudroom.status(self.host, base / 'state')['code'], code)

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
        # Other room-cli reads answer; only the login read can verify, and it
        # is the only read made.
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
        # R4: production Host.open, a real process. A launchable AppImage starts; a
        # non-executable download is never launched, and sign-in says so instead of crashing.
        marker = self.base / 'launched'
        real = cloudroom.Host(system='Linux', machine='x86_64', home=self.host.home, root=self.host.root)
        self.host.open = real.open
        app = self.host.plant_appimage(data=f'#!/bin/sh\necho launched > {marker}\n'.encode())
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

    def test_sign_in_never_takes_a_password_or_token(self):
        # The command line has no secret option, and nothing reads stdin.
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
    """J30: exactly two room-cli calls, pinned in the Rust allowlist and the contract; no other can be built."""

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
        # Install, reuse, every login state and sign-in, on both platforms: every
        # room-cli argument list the tool ran is one of the two.
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
    def test_the_command_line_reports_status_as_fixed_json(self):
        result = subprocess.run([sys.executable, '-I', str(HERE / 'cloudroom.py'), 'status', '--state-dir', str(self.state)],
                                capture_output=True, text=True, stdin=subprocess.DEVNULL,
                                env={'PATH': '/usr/bin:/bin', 'HOME': str(self.host.home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['schema'], 'openwiz.cloudroom-setup.v1')
        self.assertIn(value['code'], ('cloudroom_not_installed', 'cloudroom_unsupported'))

    def test_the_setup_check_records_the_tools_code_from_the_packaged_runtime(self):
        # The collector's layout: runtime/setup/ and runtime/cloudroom/, outside any repository.
        runtime = self.base / 'build/runtime'
        for source, name in ((HERE.parent / 'setup/setup.py', 'setup/setup.py'),
                             (HERE.parent / 'setup/store.py', 'setup/store.py'), (HERE / 'cloudroom.py', 'cloudroom/cloudroom.py')):
            (runtime / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, runtime / name)
        home = self.host.home
        self.host.plant_appimage()
        calls = self.base / 'calls.log'
        launcher = home / '.local/bin/room-cli'
        launcher.parent.mkdir(parents=True)
        # A recording fake of CloudRoom's launcher: logs its arguments, answers the fixture.
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


if __name__ == '__main__':
    unittest.main()
