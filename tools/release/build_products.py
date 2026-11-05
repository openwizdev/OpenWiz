#!/usr/bin/env python3
"""Record native build products, web export and exact tracked skill runtime."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'install'))
from install import ENGINE_RUNTIME, HANDOVER_RUNTIME, PROGRAMS, Refused, TARGETS, digest, require, sha
sys.path.insert(0, str(Path(__file__).resolve().parent))
from product_identity import PROGRAMS as COMPILED, architecture, canonical, expected, git, mode, payload, \
    release_version, verify_programs, verify_runtime, verify_web


def collect(root, binaries, web, output, version, source, target, program_receipt, web_receipt):
    require(target in TARGETS and digest(source, 40) and release_version(version), 'invalid build identity')
    require(not output.exists(), 'products output must be new')
    files = {}
    for program in sorted(PROGRAMS):
        path = binaries / program
        require(path.is_file() and not path.is_symlink() and architecture(path.open('rb').read(64), target), 'native binary target mismatch')
        files[program] = path
    for path in web.rglob('*'):
        require(not path.is_symlink(), 'web symlink')
        if path.is_file():
            files['web/' + path.relative_to(web).as_posix()] = path
    for path in subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z', 'skills']).split(b'\0'):
        if path:
            relative = path.decode('utf-8')
            actual = root / relative
            require(actual.is_file() and not actual.is_symlink(), 'unsafe tracked skill runtime')
            files['runtime/' + relative] = actual
    files['runtime/install.py'] = root / 'tools/install/install.py'
    files['runtime/pull.py'] = root / 'tools/install/pull.py'
    # #1105: the setup and App connection tools an installed consumer runs.
    for name, tool in (('setup/setup.py', 'tools/install/setup/setup.py'),
                       ('setup/store.py', 'tools/install/setup/store.py'),
                       ('github-app/setup.py', 'tools/github-app/setup.py'),
                       ('github-app/app.py', 'tools/github-app/app.py'),
                       ('github-app/manifest.json', 'tools/github-app/manifest.json')):
        path = root / tool
        require(path.is_file() and not path.is_symlink(), 'unsafe or missing setup tool')
        files['runtime/' + name] = path
    manager = root / 'tools/install/platform/runtime.py'
    require(manager.is_file() and not manager.is_symlink(), 'unsafe or missing platform runtime')
    files['runtime/platform/runtime.py'] = manager
    # #1107: explicit production files only; never fixture providers or tests.
    access = root / 'tools/install/access/access.py'
    require(access.is_file() and access.stat().st_nlink == 1
            and not any(path.is_symlink() for path in (access, *list(access.parents)[:3])),
            'unsafe or missing access tool')
    files['runtime/access/access.py'] = access
    engine = root / 'tools/install/engine/engine.py'
    require(engine.is_file() and engine.stat().st_nlink == 1
            and not any(p.is_symlink() for p in (engine, *list(engine.parents)[:3])),
            'unsafe or missing engine runtime')
    files[ENGINE_RUNTIME] = engine
    # #2201: setup's CloudRoom tool ships from its exact tracked file when the
    # requested commit tracks it; the installer requires it.
    if git(root, 'ls-tree', '-z', '--name-only', '--end-of-options', source,
           '--', 'tools/install/cloudroom/cloudroom.py') == b'tools/install/cloudroom/cloudroom.py\0':
        tool = root / 'tools/install/cloudroom/cloudroom.py'
        require(tool.is_file() and tool.stat().st_nlink == 1
                and not any(p.is_symlink() for p in (tool, *list(tool.parents)[:3])),
                'unsafe or missing CloudRoom setup tool')
        files['runtime/cloudroom/cloudroom.py'] = tool
    # #2379: the requested commit decides: if it tracks the installed handover,
    # its whole role ships from exact tracked files; older commits keep theirs.
    if git(root, 'ls-tree', '-z', '--name-only', '--end-of-options', source,
           '--', 'tools/install/handover/handover.py') == b'tools/install/handover/handover.py\0':
        for name in HANDOVER_RUNTIME:
            path = root / 'tools/install' / name.removeprefix('runtime/')
            require(path.is_file() and path.stat().st_nlink == 1
                    and not any(p.is_symlink() for p in (path, *list(path.parents)[:3])),
                    'unsafe or missing handover runtime')
            files[name] = path
    output.mkdir(mode=0o700)
    rows, runtime = [], {}
    for name, path in sorted(files.items()):
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
        data = destination.read_bytes()
        destination.chmod(int(mode(name), 8))
        rows.append({'path':name, 'sha256':sha(data), 'bytes':len(data), 'mode':mode(name)})
        if name.startswith('runtime/'):
            runtime[path.relative_to(root).as_posix()] = data
    try:
        # #2217: the copied runtime bytes are the requested commit's, before any stamp.
        verify_runtime(root, source, runtime)
        # #1148: so are the compiled programs and the web export, by their own
        # build identity and receipts; a correct architecture or stamp is not.
        products = verify_programs({p: (output / name).read_bytes() for p, name in COMPILED.items()},
                                   program_receipt, version, source, target)
        # #2539: the web-build receipt matches the export as built, before its stamp.
        products.append(verify_web([r for r in rows if r['path'].startswith('web/')], web_receipt, version, source, target))
        selection = sorted([repository, name] for name, path in files.items() if name.startswith('runtime/')
                           for repository in [path.relative_to(root).as_posix()])
        products.append({'identity': expected('runtime', version, source, target),
                         'verification': 'tracked-tree',
                         'build_receipt': {'record': 'tracked-tree',
                                           'sha256': sha(canonical({'source': source, 'selection': selection}))}})
    except Exception:
        shutil.rmtree(output)
        raise
    identity = f'openwiz.package.v1\n{version}\n{source}\n{target}\n'.encode()
    for name in ('web/openwiz-build.txt', 'runtime/openwiz-build.txt'):
        destination = output / name
        require(not destination.exists(), 'build stamp must be produced in this job')
        destination.write_bytes(identity)
        destination.chmod(0o600)
        rows.append({'path':name, 'sha256':sha(identity), 'bytes':len(identity), 'mode':'0600'})
    # #2539: each web/runtime payload is its complete final inventory, stamp
    # included; the stamp is a deterministic function of version/source/target.
    for product in products:
        kind = product['identity']['product']
        if kind in ('web', 'runtime'):
            product['payload_sha256'] = payload([r for r in rows if r['path'].startswith(kind + '/')])
    record = {'schema': 'openwiz.product-record.v1', 'version': version, 'source': source, 'target': target,
              'products': sorted(products, key=lambda row: row['identity']['product'])}
    return {'schema':'openwiz.build-products.v1', 'version':version, 'source':source,
            'target':target, 'assets':rows}, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'binaries', 'web', 'output', 'program-receipt', 'web-receipt'):
        parser.add_argument('--' + key, required=True, type=Path)
    for key in ('version', 'source', 'target'):
        parser.add_argument('--' + key, required=True)
    parser.add_argument('--identity', required=True, type=Path)
    parser.add_argument('--record', required=True, type=Path, help="the candidate's product rows")
    args = vars(parser.parse_args())
    identity, record = args.pop('identity'), args.pop('record')
    try:
        require(not identity.exists() and not record.exists(), 'identity outputs must be new')
        products, rows = collect(**args)
        identity.write_text(json.dumps(products, sort_keys=True, indent=2) + '\n')
        record.write_bytes(canonical(rows) + b'\n')
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('build-products: refused incomplete or non-native products', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
