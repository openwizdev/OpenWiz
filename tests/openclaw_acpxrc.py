#!/usr/bin/env python3
import ctypes
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DRIVER = os.path.join(ROOT, 'adapters', 'openclaw', 'driver')
FAKE = os.path.join(ROOT, 'adapters', 'openclaw', 'fixtures', 'bin', 'acpx')
REQUEST = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
           'model': 'claude-opus-5-5'}
MARKER = {'auth': {'synthetic-race-marker': 'marker'}}

ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)


def owned():
    children = {}
    for pid in filter(str.isdigit, os.listdir('/proc')):
        try:
            with open('/proc/%s/stat' % pid) as handle:
                fields = handle.read().rpartition(')')[2].split()
        except OSError:
            continue
        if fields[0] != 'Z':
            children.setdefault(int(fields[1]), []).append(int(pid))
    found, todo = set(), [os.getpid()]
    while todo:
        for child in children.get(todo.pop(), []):
            if child not in found:
                found.add(child)
                todo.append(child)
    return sorted(found)


class AcpxProjectConfig(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.calls = os.path.join(self.folder, 'calls')
        self.state = os.path.join(self.folder, 'state')
        self.home = os.path.join(self.folder, 'home')
        os.mkdir(self.home)
        self.env = dict(HOME=self.home, LANG='C.UTF-8', FAKE_ACPX_CALLS=self.calls,
                        FAKE_ACPX_STATE=os.path.join(self.folder, 'acpx.json'),
                        OPENWIZ_OPENCLAW_STATE=self.state,
                        PATH=os.path.join(ROOT, 'adapters', 'openclaw', 'fixtures', 'bin') + os.pathsep + self.bare())

    def bare(self):
        bare = os.path.join(self.folder, 'bare')
        os.mkdir(bare)
        for tool in ('python3', 'sleep'):
            os.symlink(shutil.which(tool), os.path.join(bare, tool))
        return bare

    def tearDown(self):
        for pid in owned():
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def seen(self):
        with open(self.calls) as handle:
            return [json.loads(line) for line in handle]

    def plant(self, folder):
        os.makedirs(folder)
        with open(os.path.join(folder, '.acpxrc.json'), 'w') as handle:
            json.dump(MARKER, handle)

    def fake(self, cwd, config_dir):
        env = dict(self.env, HOME=self.home)
        subprocess.run([sys.executable, FAKE, '--cwd', config_dir, '--agent', 'env HOME=/tmp true'],
                       cwd=cwd, env=env, capture_output=True, text=True, timeout=30)
        return self.seen()[-1]

    def test_acpx_reads_project_config_from_cwd_not_the_process_folder(self):
        process, chosen = (os.path.join(self.folder, name) for name in ('process', 'chosen'))
        self.plant(process)
        os.mkdir(chosen)
        self.assertEqual(self.fake(process, chosen)['auth'], [])
        os.remove(self.calls)
        self.plant(os.path.join(self.folder, 'loaded'))
        self.assertEqual(self.fake(process, os.path.join(self.folder, 'loaded'))['auth'], ['synthetic-race-marker'])

    def driver(self, cmd, request, **env):
        result = subprocess.run([sys.executable, DRIVER, cmd], input=json.dumps(request),
                                env=dict(self.env, **env), capture_output=True, text=True, timeout=120)
        return result.returncode, json.loads(result.stdout)

    def test_a_config_written_between_the_check_and_the_read_never_reaches_acpx(self):
        code, out = self.driver('start', REQUEST)
        self.assertEqual(code, 0, out)
        work = os.path.join(self.state, 'work', out['run'])
        before = len(self.seen())
        code, woke = self.driver('wake', out, FAKE_ACPX_RACE=work)
        self.assertEqual(code, 0, woke)
        self.assertTrue(os.path.exists(os.path.join(work, '.acpxrc.json')))
        self.assertEqual(self.seen()[before]['auth'], [], 'acpx loaded the project config')
        self.assertNotIn('synthetic-race-marker', json.dumps(self.seen()[before]))


if __name__ == '__main__':
    unittest.main(verbosity=2)
