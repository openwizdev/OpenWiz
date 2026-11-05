#!/usr/bin/env python3
"""IF1/IF2: synthetic archives through the real installer; no network or source tools."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
SOURCE = '1' * 40
REQUIRED = ['web/openwiz-build.txt', 'runtime/openwiz-build.txt', 'openwiz', 'openwiz-service', 'openwiz-server', 'web/index.html',
            'web/setup.html', 'runtime/skills/setup/SKILL.md', 'runtime/skills/grill/SKILL.md',
            'runtime/skills/plan-graph/SKILL.md', 'runtime/skills/launch-fleet/SKILL.md',
            'runtime/skills/launch-fleet/scripts/fleet.sh', 'runtime/install.py', 'runtime/pull.py']
# #1105 (R9): the setup and App connection tools an installed consumer runs.
SETUP_TOOLS = ['runtime/setup/setup.py', 'runtime/setup/store.py', 'runtime/github-app/setup.py',
               'runtime/github-app/app.py', 'runtime/github-app/manifest.json']
REQUIRED += SETUP_TOOLS
# #2201: setup's CloudRoom install, reuse and sign-in tool.
CLOUDROOM_TOOL = 'runtime/cloudroom/cloudroom.py'
REQUIRED += [CLOUDROOM_TOOL]


def sha(data):
    return hashlib.sha256(data).hexdigest()


class Install(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-if1-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'installed'
        self.counter = 0

    def bundle(self, target=TARGETS[2], source=SOURCE, mutate=None, extra=None, version='0.0.99', omit=None):
        self.counter += 1
        files = {path: (b'#!/bin/sh\nexit 0\n' if path in ('openwiz', 'openwiz-service', 'openwiz-server') else
                        b'<h1>Set up OpenWiz</h1><p>CloudRoom: unknown. Connect CloudRoom to continue.</p>'
                        if path.endswith('.html') else b'Synthetic runtime\n') for path in REQUIRED if path != omit}
        identity = f'openwiz.package.v1\n{version}\n{source}\n{target}\n'.encode()
        files['web/openwiz-build.txt'] = identity
        files['runtime/openwiz-build.txt'] = identity
        manifest = {'schema': 'openwiz.install.v1', 'version': version, 'source': source,
                    'target': target, 'setup_api': 1, 'archive': 'bundle.tar.gz',
                    'archive_sha256': '', 'archive_bytes': 0,
                    'assets': [{'path': path, 'sha256': sha(data), 'bytes': len(data),
                                'mode': '0700' if path in ('openwiz', 'openwiz-service', 'openwiz-server') or path.endswith('.sh') else '0600'}
                               for path, data in sorted(files.items())]}
        archive = self.base / f'archive-{self.counter}.tar.gz'
        with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
            for path, data in files.items():
                info = tarfile.TarInfo(path)
                info.size = len(data)
                info.mode = 0o700 if path in ('openwiz', 'openwiz-service', 'openwiz-server') or path.endswith('.sh') else 0o600
                tar.addfile(info, io.BytesIO(data))
            if extra:
                info = tarfile.TarInfo(extra[0])
                if extra[1] == 'symlink':
                    info.type, info.linkname = tarfile.SYMTYPE, '/tmp/synthetic-escape'
                    tar.addfile(info)
                else:
                    info.size = 1
                    tar.addfile(info, io.BytesIO(b'x'))
        manifest['archive_sha256'] = sha(archive.read_bytes())
        manifest['archive_bytes'] = archive.stat().st_size
        if mutate:
            mutate(manifest)
        path = self.base / f'manifest-{self.counter}.json'
        path.write_text(json.dumps(manifest))
        return path, archive, files

    def run_install(self, bundle, target=TARGETS[2], ok=True):
        manifest, archive, _ = bundle
        result = subprocess.run([sys.executable, str(HERE / 'install.py'), '--manifest', str(manifest),
                                 '--archive', str(archive), '--manifest-sha256', sha(manifest.read_bytes()),
                                 '--root', str(self.root), '--target', target],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        if ok:
            return json.loads(result.stdout)
        return result

    def installed(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*')
                if p.is_file() and not p.is_symlink()}

    def test_all_targets_install_matching_assets_and_repeat_without_build_tools(self):
        for target in TARGETS:
            with self.subTest(target=target):
                self.root = self.base / target
                b = self.bundle(target)
                result = self.run_install(b, target)
                self.assertEqual(result['setup_url'], 'http://127.0.0.1:7370/setup')
                self.assertEqual(result['source'], SOURCE)
                self.assertEqual(result['target'], target)
                selected = self.root / 'current'
                self.assertTrue(selected.is_symlink())
                for path, data in b[2].items():
                    self.assertEqual((selected / path).read_bytes(), data)
                self.assertIn(b'CloudRoom', (selected / 'web/setup.html').read_bytes())
                settings = self.root / 'owner-settings.json'
                settings.write_text('synthetic owner settings')
                before = self.installed()
                self.run_install(b, target)
                self.assertEqual(self.installed(), before)
                self.assertEqual((self.root / 'channel.json').read_text(),
                                 '{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n')

    def test_corruption_and_manifest_refusals_preserve_last_good_and_settings(self):
        self.run_install(self.bundle())
        (self.root / 'owner-settings.json').write_text('synthetic settings')
        before = self.installed()
        old = os.readlink(self.root / 'current')
        mutations = [lambda m: m.update(target='unsupported'),
                     lambda m: m.update(source='bad'),
                     lambda m: m.update(setup_api=2),
                     lambda m: m.update(unknown=True),
                     lambda m: m['assets'].append(m['assets'][0]),
                     lambda m: m['assets'].pop(),
                     lambda m: m['assets'][0].update(sha256='0' * 64),
                     lambda m: m['assets'][0].update(path='../escape'),
                     lambda m: m.update(archive_bytes=m['archive_bytes'] + 1)]
        for change in mutations:
            with self.subTest(change=change):
                self.run_install(self.bundle(source='2' * 40, mutate=change), ok=False)
                self.assertEqual(self.installed(), before)
                self.assertEqual(os.readlink(self.root / 'current'), old)
        b = self.bundle(source='2' * 40)
        b[1].write_bytes(b[1].read_bytes() + b'corrupt')
        self.run_install(b, ok=False)
        self.assertEqual(self.installed(), before)

    def test_a_bundle_without_any_setup_tool_is_refused(self):
        # #1105 R9: an installed consumer must be able to run setup from its bundle.
        self.root = self.base / 'complete'
        self.run_install(self.bundle())  # control: the same bundle with every tool installs
        for path in SETUP_TOOLS:
            with self.subTest(missing=path):
                self.root = self.base / ('missing-' + path.replace('/', '-'))
                self.run_install(self.bundle(omit=path), ok=False)
                self.assertFalse((self.root / 'current').exists())

    def test_a_bundle_without_the_cloudroom_tool_is_refused(self):
        # #2201: setup's CloudRoom step runs its packaged tool, never a source checkout.
        self.root = self.base / 'without-cloudroom'
        self.run_install(self.bundle(omit=CLOUDROOM_TOOL), ok=False)
        self.assertFalse((self.root / 'current').exists())

    def test_duplicate_json_keys_and_unsafe_archive_members_are_refused(self):
        self.run_install(self.bundle())
        before = self.installed()
        b = self.bundle(source='2' * 40)
        b[0].write_text(b[0].read_text().replace('"schema":', '"schema":"duplicate","schema":'))
        self.run_install(b, ok=False)
        for member in [('../escape', 'file'), ('/tmp/escape', 'file'),
                       ('runtime/escape', 'symlink'), ('web/index.html', 'file')]:
            self.run_install(self.bundle(source='2' * 40, extra=member), ok=False)
        self.assertEqual(self.installed(), before)

    def test_private_path_and_existing_foreign_selection_refusals(self):
        b = self.bundle()
        self.root.mkdir(mode=0o755)
        self.root.chmod(0o755)
        self.run_install(b, ok=False)
        self.root.chmod(0o700)
        os.symlink(self.base, self.root / 'current')
        self.run_install(b, ok=False)
        self.assertEqual(os.readlink(self.root / 'current'), str(self.base))

    def test_program_web_runtime_identity_cannot_be_relabelled_as_another_version(self):
        self.run_install(self.bundle())
        before = self.installed()
        self.run_install(self.bundle(source='2' * 40, mutate=lambda m: m.update(version='0.0.100')), ok=False)
        self.assertEqual(self.installed(), before)

    def test_existing_source_install_is_not_silently_migrated_to_packaged(self):
        self.run_install(self.bundle())
        (self.root / 'channel.json').unlink()
        before = self.installed()
        selected = (self.root / 'current').readlink()
        self.run_install(self.bundle(source='2' * 40), ok=False)
        self.assertEqual(self.installed(), before)
        self.assertEqual((self.root / 'current').readlink(), selected)

    def test_disk_permission_and_interrupted_activation_keep_last_good(self):
        spec = importlib.util.spec_from_file_location('installer', HERE / 'install.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        self.run_install(self.bundle())
        before = os.readlink(self.root / 'current')
        b = self.bundle(source='2' * 40)
        args = dict(manifest=b[0], archive=b[1], manifest_sha256=sha(b[0].read_bytes()),
                    root=self.root, target=TARGETS[2])
        with self.assertRaises(installer.Refused):
            installer.install(**args, free_bytes=lambda _: 0)
        def denied(*_):
            raise PermissionError('synthetic refusal')
        for failure in (denied, lambda *_: (_ for _ in ()).throw(InterruptedError('synthetic crash'))):
            with self.assertRaises((OSError, installer.Refused)):
                installer.install(**args, activate=failure)
            self.assertEqual(os.readlink(self.root / 'current'), before)
        self.run_install(b)
        self.assertEqual(os.readlink(self.root / 'current'), str(self.root / 'state/service/builds' / ('2' * 40)))


class FirstHourContract(unittest.TestCase):
    def test_pc_activation_contract(self):
        result = subprocess.run([sys.executable, '-I',
                                 str(HERE / 'pc_activation/test_activation.py'), '-v'],
                                capture_output=True, text=True)
        print(result.stdout + result.stderr, end='', flush=True)
        self.assertEqual(result.returncode, 0, 'PC activation contract checks failed')

    def test_first_hour_contract(self):
        # #2200: the release:install log must show the contract suite ran.
        result = subprocess.run([sys.executable, '-I',
                                 str(HERE / 'tests/first-hour-contract/test_contract.py'), '-v'],
                                capture_output=True, text=True)
        print(result.stdout + result.stderr, end='', flush=True)
        self.assertEqual(result.returncode, 0, 'first-hour contract checks failed')


    def test_completion_checkpoint(self):
        result = subprocess.run([sys.executable, '-I',
                                 str(HERE / 'completion/test_checkpoint.py'), '-v'],
                                capture_output=True, text=True)
        print(result.stdout + result.stderr, end='', flush=True)
        self.assertEqual(result.returncode, 0, 'completion checkpoint checks failed')

    def test_installed_handover(self):
        # #2379: the release:install log must show the handover suite ran.
        result = subprocess.run([sys.executable, '-I',
                                 str(HERE / 'handover/test_handover.py'), '-v'],
                                capture_output=True, text=True)
        print(result.stdout + result.stderr, end='', flush=True)
        self.assertEqual(result.returncode, 0, 'installed handover checks failed')


if __name__ == '__main__':
    unittest.main()
