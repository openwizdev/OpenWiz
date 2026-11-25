#!/usr/bin/env python3
import argparse
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description='Run every adapters/<name>/test_*.py, in name order.')
parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1], help='the repository to test')
root = parser.parse_args().root.resolve()
failed, ran = [], 0
for folder in sorted(p for p in root.glob('adapters/*') if p.is_dir()):
    name = folder.relative_to(root).as_posix()
    if (folder / 'driver').exists() and not (folder / 'test_driver.py').is_file():
        failed.append(f'{name} has a driver and no test_driver.py')
    for test in sorted(p for p in folder.glob('test_*.py') if p.is_file()):
        print(f'== {name}/{test.name}', flush=True)
        ran += 1
        if subprocess.run([sys.executable, '-I', str(test)], cwd=root).returncode != 0:
            failed.append(f'{name}/{test.name}')
if not failed and not ran:
    failed.append('no driver test found')
for line in failed:
    print(f'driver-tests: failed: {line}', file=sys.stderr)
if not failed:
    print(f'driver-tests: ok ({ran} test files)')
sys.exit(1 if failed else 0)
