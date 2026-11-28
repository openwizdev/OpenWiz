#!/usr/bin/env python3
import fcntl
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import install
import test_install

OLD, NEW = '1' * 40, '2' * 40
OLD_VERSION, NEW_VERSION = '0.2.1', '0.2.2'
TARGET = test_install.TARGETS[2]
SCHEMA = 'openwiz.hot-update.v1'


class HotSwap(unittest.TestCase):
    def setUp(self):
        self.fixtures = test_install.Bundles()
        self.addCleanup(self.fixtures.doCleanups)
        self.fixtures.setUp()
        self.root = self.fixtures.root
        self.state = self.root / 'state'
        self.selector = self.root / 'current'
        self.record = self.state / 'installed-set.json'
        self.old, _ = self.stage(OLD, OLD_VERSION, stage_only=False)
        self.new, self.archive = self.stage(NEW, NEW_VERSION, stage_only=True)
        self.manifest = self.fixtures.base / 'component.json'
        self.component = dict(schema=SCHEMA, record='component-manifest', kind='kernel',
                              id='kernel', version=NEW_VERSION,
                              sha256=install.sha(self.archive.read_bytes()))
        self.write_component()

    def stage(self, source, version, stage_only):
        program = b'''#!/bin/sh
set -eu
build=${0%/*}
cat "$build/runtime/fixture-version"
if [ "${1:-}" = wait ]; then
    read -r signal
    cat "$build/runtime/fixture-version"
fi
'''
        manifest, archive, _ = self.fixtures.bundle(
            source=source, version=version,
            override={'openwiz': program, 'runtime/fixture-version': (version + '\n').encode()})
        install.install(manifest, archive, install.sha(manifest.read_bytes()), self.root,
                        TARGET, stage_only=stage_only)
        return self.state / 'service/builds' / source, archive

    def write_component(self):
        self.manifest.write_text(json.dumps(self.component), encoding='utf-8')

    def tool(self):
        try:
            import hot_swap
        except ModuleNotFoundError as error:
            self.fail(f'Hot swap entry point is unavailable ({error.name})')
        return hot_swap

    def forward(self):
        return self.tool().swap_kernel(self.root, manifest=self.manifest, archive=self.archive, source=NEW)

    def assert_one_selection_replace(self, operation, before, after):
        replace = os.replace

        def observe(source, destination):
            if Path(destination) == self.selector:
                self.assertEqual(self.selector.readlink(), before)
                self.assertEqual(Path(source).parent, self.root)
                self.assertEqual(Path(source).readlink(), after)
            replace(source, destination)

        with patch.object(os, 'replace', side_effect=observe) as calls:
            operation()
        changes = [call for call in calls.call_args_list if Path(call.args[1]) == self.selector]
        self.assertEqual(len(changes), 1)
        self.assertEqual(self.selector.readlink(), after)

    def test_swap_is_one_rename_and_records_last_good(self):
        self.assert_one_selection_replace(self.forward, self.old, self.new)
        self.assertEqual(stat.S_IMODE(self.record.stat().st_mode), 0o600)
        self.assertEqual(json.loads(self.record.read_bytes()), {
            'schema': SCHEMA, 'record': 'installed-set', 'access': 'owner-only',
            'components': [{'kind': 'kernel', 'id': 'kernel', 'current': NEW_VERSION,
                            'last_good': OLD_VERSION, 'history': []}],
        })
        self.assertTrue(self.old.is_dir() and self.new.is_dir())

    def test_running_launch_keeps_using_its_resolved_build(self):
        with subprocess.Popen([str(self.selector.resolve() / 'openwiz'), 'wait'],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as running:
            try:
                self.assertTrue(select.select([running.stdout], [], [], 5)[0])
                self.assertEqual(running.stdout.readline().decode().strip(), OLD_VERSION)
                self.forward()
                launched = subprocess.check_output([str(self.selector.resolve() / 'openwiz')], timeout=5)
                self.assertEqual(launched.decode().strip(), NEW_VERSION)
                remaining, _ = running.communicate(b'continue\n', timeout=5)
                self.assertEqual(running.returncode, 0)
                self.assertEqual(remaining.decode().strip(), OLD_VERSION)
            finally:
                if running.poll() is None:
                    running.kill()

    def test_bad_checksum_leaves_current_and_record_untouched(self):
        self.archive.write_bytes(b'x' * self.archive.stat().st_size)
        with patch.object(os, 'replace', wraps=os.replace) as calls:
            with self.assertRaisesRegex(install.Refused, 'checksum'):
                self.forward()
        calls.assert_not_called()
        self.assertEqual(self.selector.readlink(), self.old)
        self.assertFalse(self.record.exists())

    def test_back_is_one_rename_and_keeps_both_builds(self):
        self.forward()
        arguments = ['--root', str(self.root), '--back']
        self.assert_one_selection_replace(lambda: self.assertEqual(self.tool().main(arguments), 0),
                                          self.new, self.old)
        row, = json.loads(self.record.read_bytes())['components']
        self.assertEqual((row['current'], row['last_good']), (OLD_VERSION, OLD_VERSION))
        self.assertTrue(self.old.is_dir() and self.new.is_dir())

    def test_modified_staged_asset_is_refused(self):
        (self.new / 'runtime/fixture-version').write_text('modified\n', encoding='utf-8')
        with self.assertRaisesRegex(install.Refused, 'installed asset mismatch'):
            self.forward()
        self.assertEqual(self.selector.readlink(), self.old)
        self.assertFalse(self.record.exists())

    def test_rewritten_staged_manifest_cannot_redefine_verified_bytes(self):
        asset = b'modified\n'
        (self.new / 'runtime/fixture-version').write_bytes(asset)
        manifest = self.new / 'install-manifest.json'
        value = json.loads(manifest.read_bytes())
        entry = next(item for item in value['assets'] if item['path'] == 'runtime/fixture-version')
        entry.update(sha256=install.sha(asset), bytes=len(asset))
        manifest.write_text(json.dumps(value), encoding='utf-8')
        with self.assertRaisesRegex(install.Refused, 'archive asset mismatch'):
            self.forward()
        self.assertEqual(self.selector.readlink(), self.old)
        self.assertFalse(self.record.exists())

    def test_pending_build_cannot_replace_the_last_good_version(self):
        self.forward()
        record = self.record.read_bytes()
        with self.assertRaisesRegex(install.Refused, 'awaits health confirmation'):
            self.forward()
        self.assertEqual(self.record.read_bytes(), record)
        self.assertEqual(self.selector.readlink(), self.new)

    def test_uses_the_installers_lock(self):
        self.tool()
        with (self.root / 'install.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.forward()
        self.assertEqual(self.selector.readlink(), self.old)

    def test_interrupted_selection_requires_restore(self):
        hot_swap = self.tool()
        with patch.object(install, 'activate_link', side_effect=OSError('synthetic interruption')):
            with self.assertRaisesRegex(OSError, 'synthetic interruption'):
                self.forward()
        self.assertEqual(self.selector.readlink(), self.old)
        with self.assertRaisesRegex(install.Refused, 'interrupted'):
            self.forward()
        hot_swap.swap_kernel(self.root, back=True)
        self.forward()
        self.assertEqual(self.selector.readlink(), self.new)


if __name__ == '__main__':
    unittest.main()
