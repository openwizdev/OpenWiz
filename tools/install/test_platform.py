#!/usr/bin/env python3
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
WSL_NOTE = 'WSL has community support. It works for some users and the project does not test it.'
WINDOWS_LINE = ('Native Windows is not supported. Use Windows Subsystem for Linux (WSL). ' + WSL_NOTE
                + ' OpenWiz installs on macOS (Apple silicon or Intel) and on Linux (x86_64 or aarch64).')

RUN = """
import platform
import runpy
import shutil
import subprocess
import sys
import urllib.request
from unittest import mock

entry, system, machine, release, fcntl, *args = sys.argv[1:]
if fcntl == 'missing':
    sys.modules['fcntl'] = None
sys.argv = [entry, *args]
ldd = subprocess.CompletedProcess(['ldd', '--version'], 0, 'ldd (GNU libc) 2.36\\n', '')
with mock.patch.object(platform, 'system', return_value=system), \\
     mock.patch.object(platform, 'machine', return_value=machine), \\
     mock.patch.object(platform, 'release', return_value=release), \\
     mock.patch.object(shutil, 'disk_usage', return_value=mock.Mock(free=1024**3)), \\
     mock.patch.object(shutil, 'which', side_effect=lambda name: name), \\
     mock.patch.object(subprocess, 'run', return_value=ldd), \\
     mock.patch.object(urllib.request.OpenerDirector, 'open', side_effect=AssertionError('unexpected download')):
    runpy.run_path(entry, run_name='__main__')
"""


class Platforms(unittest.TestCase):
    def run_entry(self, system, machine, release, *args, fcntl='present', distro=None):
        env = {key: value for key, value in os.environ.items() if key not in ('WSL_DISTRO_NAME', 'WSL_INTEROP')}
        if distro is not None:
            env['WSL_DISTRO_NAME'] = distro
        return subprocess.run([sys.executable, '-I', '-c', RUN, str(HERE / 'install'),
                               system, machine, release, fcntl, *args],
                              capture_output=True, text=True, env=env, timeout=15)

    def preflight(self, system, machine, release, code=0, **options):
        result = self.run_entry(system, machine, release, 'preflight', **options)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '')
        report = json.loads(result.stdout)
        self.assertEqual(report['schema'], 'openwiz.preflight.v1')
        self.assertEqual(report['ready'], code == 0)
        return report

    def test_native_windows_preflight_refuses_even_without_posix_imports(self):
        report = self.preflight('Windows', 'AMD64', '11', code=5, fcntl='missing')
        self.assertIsNone(report['target'])
        self.assertEqual(report['checks'], [{'id': 'target', 'state': 'refused', 'next': WINDOWS_LINE}])

    def test_native_windows_download_stops_before_creating_a_directory_or_fetching(self):
        for system in ('Windows', 'CYGWIN_NT-10.0', 'MSYS_NT-10.0', 'MINGW64_NT-10.0'):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as folder:
                dest = Path(folder) / 'downloads'
                result = self.run_entry(system, 'x86_64', '11', 'download',
                                        '--target', 'x86_64-unknown-linux-gnu', '--dir', str(dest))
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertEqual(json.loads(result.stdout), {
                    'schema': 'openwiz.install-error.v1', 'outcome': 'refused',
                    'command': 'download', 'reason': WINDOWS_LINE,
                })
                self.assertFalse(dest.exists())

    def test_wsl_preflight_keeps_linux_checks_and_adds_one_note(self):
        for release, distro in (('4.4.0-19041-Microsoft', None),
                                ('6.6.87.2-microsoft-standard-WSL2', None),
                                ('6.6.87.2-custom', 'Synthetic Linux')):
            with self.subTest(release=release):
                linux = self.preflight('Linux', 'x86_64', '6.6.87.2')
                wsl = self.preflight('Linux', 'x86_64', release, distro=distro)
                self.assertEqual(json.dumps(wsl).count(WSL_NOTE), 1)
                target = next(check for check in wsl['checks'] if check['id'] == 'target')
                self.assertEqual(target['next'], WSL_NOTE)
                target['next'] = 'Supported.'
                self.assertEqual(wsl, linux)

    def test_macos_and_linux_keep_their_existing_targets(self):
        for system, machine, target in (
            ('Darwin', 'arm64', 'aarch64-apple-darwin'),
            ('Darwin', 'x86_64', 'x86_64-apple-darwin'),
            ('Linux', 'x86_64', 'x86_64-unknown-linux-gnu'),
            ('Linux', 'aarch64', 'aarch64-unknown-linux-gnu'),
        ):
            with self.subTest(system=system, machine=machine):
                report = self.preflight(system, machine, '6.6.87.2')
                self.assertEqual(report['target'], target)
                self.assertNotIn(WSL_NOTE, json.dumps(report))
                self.assertEqual('glibc' in {check['id'] for check in report['checks']}, system == 'Linux')

    def test_platform_documentation_names_all_three_levels(self):
        docs = (HERE.parents[1] / 'docs/install.md').read_text(encoding='utf-8')
        self.assertIn('\n## Platforms\n', docs)
        platforms = docs.split('\n## Platforms\n', 1)[1].split('\n## ', 1)[0]
        self.assertIn('**Supported.**', platforms)
        self.assertIn('macOS on Apple silicon and Intel', platforms)
        self.assertIn('Linux on x86_64 and aarch64', platforms)
        self.assertIn('**Community.**', platforms)
        self.assertIn('Windows through WSL', platforms)
        self.assertIn('**Unsupported.**', platforms)
        self.assertIn('Native Windows', platforms)


if __name__ == '__main__':
    unittest.main()
