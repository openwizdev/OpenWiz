#!/usr/bin/env python3
"""Published-artifact transport with synthetic bytes and recorded URLs only."""
import importlib.util
import json
from pathlib import Path
import unittest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_install as fixture


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
        self.assertTrue((f.root / 'state/service/builds' / ('2' * 40) / 'web/setup.html').exists())
        self.assertEqual(calls, [
            'https://github.com/openwizdev/openwiz/releases/latest/download/openwiz-x86_64-unknown-linux-gnu.sha256',
            'https://github.com/openwizdev/openwiz/releases/latest/download/openwiz-x86_64-unknown-linux-gnu.manifest.json',
            'https://github.com/openwizdev/openwiz/releases/download/v0.0.99/openwiz-0.0.99-x86_64-unknown-linux-gnu.manifest.json',
            'https://github.com/openwizdev/openwiz/releases/download/v0.0.99/bundle.tar.gz',
        ])
        with self.assertRaises(pull.Refused):
            pull.stage(target, '0.0.98', '2' * 40, digest, f.root, f.root / 'state', fetch=fetch)
        with self.assertRaises(pull.Refused):
            pull.stage(target, '0.0.99', '2' * 40, '0' * 64, f.root, f.root / 'state', fetch=fetch)
        self.assertEqual((f.root / 'current').readlink(), before)


if __name__ == '__main__':
    unittest.main()
