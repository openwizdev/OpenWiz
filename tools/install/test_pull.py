#!/usr/bin/env python3
"""Published-artifact transport with synthetic bytes and recorded URLs only."""
import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_install as fixture

HERE = Path(__file__).resolve().parent


class Pull(unittest.TestCase):
    def test_published_upgrade_stages_verified_files_keeps_selection_and_refuses_rollback(self):
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        old = f.bundle(version='0.0.98')
        f.run_install(old)
        before = (f.root / 'current').readlink()
        new = f.bundle(source='2' * 40)
        raw = new[0].read_bytes()
        digest = fixture.sha(raw)
        target = fixture.TARGETS[2]
        calls = []
        def fetch(url, limit):
            calls.append(url)
            if url.endswith('.sha256'):
                return (digest + '  openwiz-' + target + '.manifest.json\n').encode()
            if url.endswith('.manifest.json'):
                return raw
            if url.endswith('.tar.gz'):
                return new[1].read_bytes()
            self.fail('unexpected transport URL ' + url)
        candidate = pull.discover(target, fetch=fetch)
        self.assertEqual(candidate['source'], '2' * 40)
        pull.stage(target, '0.0.99', '2' * 40, digest, f.root, f.root / 'state', fetch=fetch)
        self.assertEqual((f.root / 'current').readlink(), before)
        self.assertTrue((f.root / 'state/service/builds' / ('2' * 40) / 'runtime/install.py').exists())
        self.assertEqual(calls, [
            'https://github.com/openwizdev/OpenWiz/releases/latest/download/openwiz-x86_64-unknown-linux-gnu.sha256',
            'https://github.com/openwizdev/OpenWiz/releases/latest/download/openwiz-x86_64-unknown-linux-gnu.manifest.json',
            'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/openwiz-0.0.99-x86_64-unknown-linux-gnu.manifest.json',
            'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/bundle.tar.gz',
        ])
        with self.assertRaises(pull.Refused):
            pull.stage(target, '0.0.98', '2' * 40, digest, f.root, f.root / 'state', fetch=fetch)
        with self.assertRaises(pull.Refused):
            pull.stage(target, '0.0.99', '2' * 40, '0' * 64, f.root, f.root / 'state', fetch=fetch)
        self.assertEqual((f.root / 'current').readlink(), before)


    def test_pre_ap11_selected_build_reports_status_and_upgrades_to_a_cli_only_candidate(self):
        # catches: the CLI-only allowlist applied to the already-installed manifest,
        # so status refuses a working pre-AP11 install and the update never stages.
        spec = importlib.util.spec_from_file_location('pull', Path(__file__).with_name('pull.py'))
        pull = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(pull)
        f = fixture.Install()
        f.setUp()
        self.addCleanup(f.doCleanups)
        target, legacy = fixture.TARGETS[2], 'a' * 40
        # The pre-AP11 (a0130bc) layout, as its installer left it: three programs,
        # web/ beside runtime/ and both build stamps. Today's installer refuses to make it.
        identity = f'openwiz.package.v1\n0.0.98\n{legacy}\n{target}\n'.encode()
        programs = ('openwiz', 'openwiz-service', 'openwiz-server')
        files = {path: b'Synthetic runtime\n' for path in fixture.REQUIRED}
        files.update({path: b'#!/bin/sh\nexit 0\n' for path in programs})
        files.update({'web/index.html': b'<h1>Synthetic</h1>', 'web/setup.html': b'<h1>Synthetic</h1>',
                      'web/openwiz-build.txt': identity, 'runtime/openwiz-build.txt': identity})
        mode = lambda path: '0700' if path in programs or path.endswith('.sh') else '0600'
        raw = json.dumps({'schema': 'openwiz.install.v1', 'version': '0.0.98', 'source': legacy,
                          'target': target, 'setup_api': 1, 'archive': 'bundle.tar.gz',
                          'archive_sha256': '0' * 64, 'archive_bytes': 1,
                          'assets': [{'path': path, 'sha256': fixture.sha(data), 'bytes': len(data),
                                      'mode': mode(path)} for path, data in sorted(files.items())]}).encode()
        build = f.root / 'state/service/builds' / legacy
        for folder in (f.root, f.root / 'state', f.root / 'state/service', build.parent, build):
            folder.mkdir(mode=0o700)
            folder.chmod(0o700)
        for path, data in {**files, 'install-manifest.json': raw}.items():
            for folder in reversed((build / path).relative_to(build).parents[:-1]):
                (build / folder).mkdir(mode=0o700, exist_ok=True)
                (build / folder).chmod(0o700)
            (build / path).write_bytes(data)
            (build / path).chmod(int(mode(path), 8))
        (f.root / 'channel.json').write_bytes(b'{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n')
        (f.root / 'channel.json').chmod(0o600)
        (f.root / 'current').symlink_to(build)

        def status():
            result = subprocess.run([sys.executable, str(HERE / 'install'), 'status', '--root', str(f.root)],
                                    capture_output=True, text=True)
            return result.returncode, json.loads(result.stdout)
        code, value = status()
        self.assertEqual((code, value.get('source'), value.get('version')), (0, legacy, '0.0.98'), value)

        # A candidate in the legacy layout stays refused: the legacy layout is only for the selected build.
        legacy_raw = raw.replace(legacy.encode(), b'3' * 40).replace(b'0.0.98', b'0.0.99')
        with self.assertRaisesRegex(pull.Refused, 'unknown asset role'):
            pull.stage(target, '0.0.99', '3' * 40, fixture.sha(legacy_raw), f.root, f.root / 'state',
                       fetch=lambda url, limit: legacy_raw)

        new = f.bundle(source='2' * 40)
        new_raw, archive = new[0].read_bytes(), new[1].read_bytes()
        fetched = []
        def fetch(url, limit):
            fetched.append(url)
            return archive if url.endswith('.tar.gz') else new_raw
        staged = pull.stage(target, '0.0.99', '2' * 40, fixture.sha(new_raw), f.root, f.root / 'state', fetch=fetch)
        self.assertEqual(fetched[-1], 'https://github.com/openwizdev/OpenWiz/releases/download/v0.0.99/bundle.tar.gz')
        self.assertEqual(((f.root / 'current').readlink(), staged['activated']), (build, False))
        # The switch: the same verified package, now selected; status reads the new build.
        f.run_install(new)
        code, value = status()
        self.assertEqual((code, value.get('source'), value.get('version')), (0, '2' * 40, '0.0.99'), value)


if __name__ == '__main__':
    unittest.main()
