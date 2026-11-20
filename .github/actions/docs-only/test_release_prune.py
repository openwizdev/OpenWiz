#!/usr/bin/env python3
"""The split release lane retains the inputs of both former parent jobs."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HERE=Path(__file__).resolve().parent


class ReleaseInputs(unittest.TestCase):
    def test_prune_keeps_rust_and_web_readers_but_no_unlisted_private_file(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/'repo';root.mkdir()
            paths=['tools/github-app/test.py','tools/release/test.py','docs/agents/fleet.md',
                   'ci/escapes/escapes.py','STATUS.md','private/keep.txt','private/unlisted.txt']
            for name in paths:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic\n')
            reads=Path(folder)/'reads.txt';reads.write_text('private/keep.txt\n')
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            result=subprocess.run(['sh',str(HERE/'prune.sh'),str(reads),'release'],cwd=root,
                                  env=os.environ,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            left=sorted(str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and '.git' not in p.parts)
            self.assertEqual(left,['ci/escapes/escapes.py','docs/agents/fleet.md',
                                   'private/keep.txt','tools/github-app/test.py','tools/release/test.py'])


if __name__=='__main__':unittest.main()
