import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from unittest.mock import patch


HELPER = Path(__file__).with_name('stubs.py')
INVENTORY = HELPER.with_name('agent-clis.json')
TOOLS = {'gh', 'git', 'python3', 'sh'}


class StubPath(unittest.TestCase):
    def load_helper(self):
        self.assertTrue(HELPER.is_file(), 'the shared stub helper is missing')
        sys.dont_write_bytecode = True
        spec = importlib.util.spec_from_file_location('stubs', HELPER)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        return helper

    def executable(self, path):
        path.write_text('#!/bin/sh\nprintf "unguarded\\n"\nexit 42\n', encoding='utf-8')
        path.chmod(0o700)

    def assert_refuses(self, name, env):
        directory = env['PATH'].split(os.pathsep)[0]
        self.assertEqual(shutil.which(name, path=env['PATH']), str(Path(directory) / name))
        result = subprocess.run([name], env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual((result.returncode, result.stdout), (1, ''))
        self.assertIn(name, result.stderr)
        self.assertIn('refused', result.stderr)

    def test_each_stub_shadows_a_later_command_and_keeps_required_tools(self):
        helper = self.load_helper()
        names = set(json.loads(INVENTORY.read_text(encoding='utf-8')))
        self.assertTrue(names)
        self.assertFalse(names & TOOLS)
        self.assertTrue(all(Path(name).name == name and name not in {'', '.', '..'} for name in names))
        with tempfile.TemporaryDirectory(prefix='synthetic tools ') as temporary:
            fake = Path(temporary)
            for name in names | TOOLS:
                self.executable(fake / name)
            with patch.dict(os.environ, PATH=temporary):
                guarded = helper.stub_path()
                self.assertEqual(os.environ['PATH'], temporary)
            directory, suffix = guarded.split(os.pathsep, 1)
            self.addCleanup(shutil.rmtree, directory)
            self.assertEqual(suffix, temporary)
            self.assertEqual(stat.S_IMODE(Path(directory).stat().st_mode), 0o700)
            self.assertEqual({p.name for p in Path(directory).iterdir()}, names)
            for name in sorted(names):
                with self.subTest(name=name):
                    self.assert_refuses(name, dict(os.environ, PATH=guarded))
            for name in sorted(TOOLS):
                with self.subTest(name=name):
                    self.assertEqual(shutil.which(name, path=guarded), str(fake / name))

    def test_print_path_can_be_exported_by_a_shell(self):
        self.assertTrue(HELPER.is_file(), 'the shared stub helper is missing')
        with tempfile.TemporaryDirectory(prefix='synthetic tools ') as temporary:
            fake = Path(temporary)
            self.executable(fake / 'claude')
            env = dict(os.environ, PATH=temporary, TMPDIR=temporary)
            shell = 'guarded=$("$1" -I "$2" --print-path) || exit; export PATH="$guarded"; printf "%s\\n" "$PATH"'
            result = subprocess.run(['/bin/sh', '-c', shell, 'test', sys.executable, HELPER], env=env,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual((result.returncode, result.stderr), (0, ''))
            self.assertEqual(len(result.stdout.splitlines()), 1)
            directory, suffix = result.stdout.rstrip('\n').split(os.pathsep, 1)
            self.assertEqual(suffix, temporary)
            self.assertEqual(Path(directory).parent, fake)
            self.assert_refuses('claude', dict(env, PATH=result.stdout.rstrip('\n')))

    def test_invalid_inventory_leaves_no_partial_path(self):
        self.assertTrue(HELPER.is_file(), 'the shared stub helper is missing')
        invalid = ['{', '{}', '[]', '["claude", "claude"]', '["claude", 7]',
                   '["claude", "../escape"]', '["claude", "a.b"]', '["claude", "工具"]']
        invalid += [json.dumps(['claude', tool]) for tool in sorted(TOOLS)]
        with tempfile.TemporaryDirectory() as temporary:
            fake = Path(temporary)
            helper = fake / HELPER.name
            shutil.copyfile(HELPER, helper)
            inventory = fake / INVENTORY.name
            env = dict(os.environ, PATH=temporary, TMPDIR=temporary)
            for text in invalid:
                with self.subTest(inventory=text):
                    inventory.write_text(text, encoding='utf-8')
                    result = subprocess.run([sys.executable, '-I', helper, '--print-path'], env=env,
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual((result.returncode, result.stdout), (1, ''))
                    self.assertIn('inventory', result.stderr)
                    self.assertEqual(set(fake.iterdir()), {helper, inventory})


if __name__ == '__main__':
    unittest.main(verbosity=2)
