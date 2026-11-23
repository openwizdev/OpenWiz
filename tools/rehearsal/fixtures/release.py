import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools/release'))
from product_identity import mode
TOOLS = {
    'runtime/install.py': 'tools/install/install.py',
    'runtime/pull.py': 'tools/install/pull.py',
    'runtime/setup/setup.py': 'tools/install/setup/setup.py',
    'runtime/setup/store.py': 'tools/install/setup/store.py',
    'runtime/setup/github_login.py': 'tools/install/setup/github_login.py',
    'runtime/setup/init.py': 'tools/install/setup/init.py',
    'runtime/github-app/setup.py': 'tools/github-app/setup.py',
    'runtime/github-app/app.py': 'tools/github-app/app.py',
    'runtime/github-app/manifest.json': 'tools/github-app/manifest.json',
    'runtime/access/access.py': 'tools/install/access/access.py',
    'runtime/cloudroom/cloudroom.py': 'tools/install/cloudroom/cloudroom.py',
    'runtime/adapters/local/driver': 'adapters/local/driver',
    'runtime/adapters/local/schema.json': 'adapters/local/schema.json',
    'runtime/kernel/driver-kit/kit.py': 'kernel/driver-kit/kit.py',
    'runtime/kernel/driver-kit/schema.json': 'kernel/driver-kit/schema.json',
    'runtime/kernel/records-kit/check.py': 'kernel/records-kit/check.py',
    'runtime/kernel/records.v1.md': 'kernel/records.v1.md',
    'runtime/wizskills.lock': 'wizskills.lock',
}
BREAKS = ('flipped-archive-byte', 'other-version-manifest', 'other-commit-identity', 'setup-needs-cloudroom',
          'dry-run-writes', 'calls-cargo')
NOT_NEEDED = "'cloudroom_not_needed' if host != 'cloud' else"
NEEDS_CLOUDROOM = "'cloudroom_missing' if host != 'cloud' else"
WHERE_READ = "login = run(['gh', 'api', 'user', '--jq', '.login'], env)"
WHERE_WRITE = "run(['gh', 'api', '-X', 'POST', 'user/repos', '-f', 'name=synthetic-planted'], env)\n    " + WHERE_READ

PROGRAM = '''#!/usr/bin/env python3
import json, shutil, subprocess, sys
IDENTITY = %r
CALLS_CARGO = %r
args = sys.argv[1:]
if args == ['--build-identity']:
    if CALLS_CARGO:
        subprocess.run(['cargo', 'build', '--release'])
    print(IDENTITY)
    sys.exit(0)
if args == ['models', '--json', '--host', 'local']:
    found = shutil.which('claude') is not None
    print(json.dumps({'schema': 'openwiz.cloud-options.v1', 'source': 'local', 'label': 'This computer',
                      'state': {'kind': 'offered'} if found else {'kind': 'no_options'},
                      'harnesses': [{'harness': 'claude-code', 'provider': 'claude-code', 'models': [
                          {'model': 'synthetic-claude-model', 'efforts': ['medium']}]}] if found else [],
                      'unavailable': []}))
    sys.exit(0)
sys.stderr.write('synthetic openwiz: not part of the rehearsal fixture\\n')
sys.exit(2)
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def products(skills, version, source, target, planted):
    files = {name: (ROOT / tool).read_bytes() for name, tool in TOOLS.items()}
    for path in sorted(Path(skills).rglob('*')):
        if path.is_file() and '__pycache__' not in path.parts:
            files['runtime/skills/' + path.relative_to(skills).as_posix()] = path.read_bytes()
    files['runtime/openwiz-build.txt'] = f'openwiz.package.v1\n{version}\n{source}\n{target}\n'.encode()
    claimed = '2' * 40 if planted == 'other-commit-identity' else source
    identity = json.dumps({'product': 'cli', 'schema': 'openwiz.product.v1', 'source': claimed,
                           'target': target, 'version': version}, separators=(',', ':'))
    files['openwiz'] = (PROGRAM % (identity, planted == 'calls-cargo')).encode()
    if planted == 'setup-needs-cloudroom':
        files['runtime/setup/setup.py'] = replace_once(files['runtime/setup/setup.py'], NOT_NEEDED, NEEDS_CLOUDROOM)
    return files


def replace_once(data, old, new):
    text = data.decode('utf-8')
    assert text.count(old) == 1, 'the planted edit no longer matches: ' + old
    return text.replace(old, new).encode()


def plant_skill(skills):
    path = Path(skills) / 'install/scripts/first_fleet.py'
    path.write_bytes(replace_once(path.read_bytes(), WHERE_READ, WHERE_WRITE))


def build(folder, skills, version='0.0.99', source='1' * 40, target='x86_64-unknown-linux-gnu', planted=None):
    assert planted in (None,) + BREAKS
    folder = Path(folder)
    shipped = '0.0.98' if planted == 'other-version-manifest' else version
    files = products(skills, shipped, source, target, planted)
    tree = folder / 'products'
    rows = []
    for name, data in sorted(files.items()):
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(int(mode(name), 8))
        rows.append({'path': name, 'sha256': sha(data), 'bytes': len(data), 'mode': mode(name)})
    identity = folder / 'products.json'
    identity.write_text(json.dumps({'schema': 'openwiz.build-products.v1', 'version': shipped, 'source': source,
                                    'target': target, 'assets': rows}))
    packages = folder / 'packages'
    subprocess.run([sys.executable, '-I', str(ROOT / 'tools/release/package.py'), '--products', str(tree),
                    '--identity', str(identity), '--output', str(packages)], check=True)
    archive = packages / f'openwiz-{shipped}-{target}.tar.gz'
    if planted == 'flipped-archive-byte':
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 1
        archive.write_bytes(bytes(data))
    return archive
