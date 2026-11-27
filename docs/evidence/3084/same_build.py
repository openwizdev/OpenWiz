#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'tools/install'), str(ROOT / 'tools/release')]
import test_package as package

if len(sys.argv) != 2:
    sys.exit('usage: same_build.py <a checkout of the commit before #3084>; this checkout must be clean')
source = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
built = []
for label, checkout in (('before', Path(sys.argv[1]).resolve()), ('after', ROOT)):
    with tempfile.TemporaryDirectory() as temporary:
        work = Path(temporary)
        (work / 'bin').mkdir()
        (work / 'job').mkdir()
        receipts = package.build(work / 'bin', source, package.TARGETS[0], work / 'job')
        args = package.collector(ROOT, work / 'bin', work / 'products', source, package.TARGETS[0], receipts)
        args[2] = str(checkout / 'tools/release/build_products.py')
        subprocess.run(args, check=True)
        built.append((work / 'products.json').read_bytes())
    print(f'{label}: {len(json.loads(built[-1])["assets"])} files, sha256 {hashlib.sha256(built[-1]).hexdigest()}')
print('byte-identical:', built[0] == built[1])
sys.exit(built[0] != built[1])
