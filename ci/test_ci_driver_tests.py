#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'ci/driver-tests.py'
PASS = 'import sys\nfrom pathlib import Path\nprint("ran", Path(__file__).name, sys.flags.isolated, flush=True)\n'
FAIL = PASS + 'sys.exit(3)\n'
KILLED = PASS + 'import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n'


class DriverTests(unittest.TestCase):
    def run_on(self, files):
        with tempfile.TemporaryDirectory(prefix='openwiz-driver-tests-') as temporary:
            root = Path(temporary)
            for path, text in files.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_text(text)
            return subprocess.run([sys.executable, '-I', str(RUNNER), '--root', str(root)],
                                  capture_output=True, text=True, timeout=60)

    def test_every_folders_tests_run_once_in_name_order(self):
        result = self.run_on({'adapters/zed/driver': '', 'adapters/zed/test_driver.py': PASS,
                              'adapters/abc/driver': '', 'adapters/abc/test_driver.py': PASS,
                              'adapters/abc/test_rows.py': PASS, 'adapters/abc/helper.py': FAIL,
                              'adapters/abc/fixtures/test_fake.py': FAIL,
                              'adapters/note/README.md': 'no driver yet', 'adapters/test_stray.py': FAIL})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.splitlines(), [
            '== adapters/abc/test_driver.py', 'ran test_driver.py 1', '== adapters/abc/test_rows.py',
            'ran test_rows.py 1', '== adapters/zed/test_driver.py', 'ran test_driver.py 1',
            'driver-tests: ok (3 test files)'])

    def test_a_failing_test_fails_the_run_and_the_rest_still_run(self):
        for text in (FAIL, KILLED):
            for first, last in ((text, PASS), (PASS, text)):
                result = self.run_on({'adapters/abc/driver': '', 'adapters/abc/test_driver.py': first,
                                      'adapters/zed/driver': '', 'adapters/zed/test_driver.py': last})
                self.assertEqual(result.returncode, 1)
                self.assertEqual(result.stdout.count('ran test_driver.py 1\n'), 2)
                name = 'abc' if first == text else 'zed'
                self.assertEqual(result.stderr, f'driver-tests: failed: adapters/{name}/test_driver.py\n')

    def test_a_driver_folder_without_test_driver_fails_and_is_named(self):
        for extra in ({}, {'adapters/bare/test_other.py': PASS}, {'adapters/bare/test_driver.py/x': ''}):
            result = self.run_on({'adapters/bare/driver': '', 'adapters/abc/driver': '',
                                  'adapters/abc/test_driver.py': PASS, **extra})
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, 'driver-tests: failed: adapters/bare has a driver and no test_driver.py\n')
            self.assertEqual(result.stdout.count('ran test_driver.py 1\n'), 1)

    def test_nothing_to_run_fails(self):
        for files in ({}, {'adapters/note/README.md': ''}):
            result = self.run_on(files)
            self.assertEqual((result.returncode, result.stderr), (1, 'driver-tests: failed: no driver test found\n'))


if __name__ == '__main__':
    unittest.main()
