import ctypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import signal
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FixtureCase = runpy.run_path(str(HERE / 'test_smoke.py'))['FixtureCase']


class Review(FixtureCase):
    def test_r6_timeout_reaps_a_child_that_started_its_own_session(self):
        libc = ctypes.CDLL(None, use_errno=True)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        pid_file = self.root / 'child-pid'
        child = self.root / 'synthetic-session.py'
        child.write_text('import os, pathlib, signal\n'
                         'if os.fork() == 0:\n'
                         '    os.setsid()\n'
                         f'    pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n'
                         '    signal.pause()\n'
                         'os.wait()\n')
        python = str(Path(sys.executable).resolve())
        self.kit['artifacts'].update({python: self.sha(Path(python)), str(child): self.sha(child)})
        step = self.kit['steps'][0]
        step['kind'] = 'read'
        step['argv'] = [python, '-I', str(child)]
        self.kit['steps'].append({'id': 'fleet_write', 'claim': 'fleet', 'kind': 'write',
            'argv': [str(self.fake), 'fleet'], 'exit': 0,
            'checks': [{'path': '/count', 'equals': 1}]})
        result = self.invoke()
        self.assertTrue(pid_file.exists(), 'the new-session child actually ran')
        pid = int(pid_file.read_text())
        try:
            self.assertEqual(self.report(result, 3)['reason'], 'timeout')
            self.assertFalse(Path(f'/proc/{pid}').exists(), 'the new-session child must be gone and reaped')
        finally:
            if Path(f'/proc/{pid}').exists():
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    os.waitpid(pid, 0)
                except ChildProcessError:
                    pass


    def test_r8_cleanup_readback_is_bounded_and_never_repeats_write(self):
        helper = HERE / 'cleanup.py'
        python = str(Path(sys.executable).resolve())
        gh = self.root / 'synthetic-gh'
        gh.write_text(r'''#!/usr/bin/env python3
import json, pathlib, sys
root = pathlib.Path(__file__).parent
if sys.argv[1:3] == ['issue', 'edit']:
    with (root / 'cleanup-writes').open('a') as stream:
        stream.write('write\n')
    print('{}')
else:
    mode = (root / 'readback-mode').read_text()
    if mode == 'stderr':
        sys.stderr.write('synthetic noisy stderr ' * 1024)
    labels = [{'name': 'X' * 16384}] if mode == 'stdout' else []
    print(json.dumps({'number': 9004, 'state': 'OPEN', 'labels': labels}))
''')
        gh.chmod(0o700)
        wrapper = self.root / 'small-limit-runner.py'
        wrapper.write_text('import runpy\n'
            f'module=runpy.run_path({str(HERE / "smoke.py")!r})\n'
            "module['command'].__globals__['LIMIT']=4096\n"
            "raise SystemExit(module['main']())\n")
        self.kit['artifacts'].update({python: self.sha(Path(python)),
            str(helper): self.sha(helper), str(gh): self.sha(gh)})
        self.kit['steps'][0] = {'id': 'cleanup_write', 'claim': 'fleet', 'kind': 'write',
            'argv': [python, '-I', str(helper), '--gh', str(gh), '--repo',
                     'synthetic-owner/synthetic-repo', '--ticket', '9004', '--action', 'unlabel'],
            'exit': 0, 'checks': [{'path': '/state', 'equals': 'OPEN'},
                                 {'path': '/needs_info', 'equals': False}]}
        self.kit_path.write_text(json.dumps(self.kit))
        (self.root / 'replies.json').write_text(json.dumps(self.replies))
        writes = self.root / 'cleanup-writes'
        for mode in ('stdout', 'stderr', 'normal'):
            with self.subTest(mode=mode):
                if writes.exists():
                    writes.unlink()
                self.state = self.root / ('cleanup-' + mode)
                (self.root / 'readback-mode').write_text(mode)
                argv = [python, '-I', str(wrapper), '--kit', str(self.kit_path),
                        '--state', str(self.state), '--fixture']
                code = 3 if mode == 'stdout' else 0
                result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                doc = self.report(result, code)
                self.assertEqual(doc['reason'], 'uncertain_write' if mode == 'stdout' else 'none')
                self.assertEqual(writes.read_text().splitlines(), ['write'])
                before = self.call_list()
                result = subprocess.run(argv, capture_output=True, text=True, timeout=10)
                self.report(result, code)
                self.assertEqual(writes.read_text().splitlines(), ['write'])
                if mode == 'stdout':
                    self.assertNotIn(['send'], self.call_list())
                    self.assertEqual(self.call_list(), before + [['ls', '--json']])


if __name__ == '__main__':
    unittest.main()
