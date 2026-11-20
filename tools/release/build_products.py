#!/usr/bin/env python3
"""Record the native program and exact skill runtime: the source's tracked
skills, or (#555) the WizSkills install its lock pins."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'install'))
from install import PROGRAMS, Refused, TARGETS, digest, require, sha
sys.path.insert(0, str(Path(__file__).resolve().parent))
from product_identity import PROGRAMS as COMPILED, WIZSKILLS, architecture, canonical, expected, git, \
    locked_skills, mode, payload, release_version, verify_programs, verify_runtime


def collect(root, binaries, output, version, source, target, program_receipt):
    require(target in TARGETS and digest(source, 40) and release_version(version), 'invalid build identity')
    require(not output.exists(), 'products output must be new')
    files = {}
    for program in sorted(PROGRAMS):
        path = binaries / program
        require(path.is_file() and not path.is_symlink() and architecture(path.open('rb').read(64), target), 'native binary target mismatch')
        files[program] = path
    # #555: a source tracking `skills` as the WizSkills link packages the
    # verified install its lock pins; verify_runtime checks the bytes again.
    installed = locked_skills(root, source)
    if installed is not None:
        skills = [(relative, root / WIZSKILLS / relative) for relative in sorted(installed)]
    else:
        skills = [(path.decode('utf-8'), root / path.decode('utf-8')) for path in subprocess.check_output(
            ['git', '-C', str(root), 'ls-files', '-z', 'skills']).split(b'\0') if path]
    for relative, actual in skills:
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
    # #1107: explicit production files only; never fixture providers or tests.
    access = root / 'tools/install/access/access.py'
    require(access.is_file() and access.stat().st_nlink == 1
            and not any(path.is_symlink() for path in (access, *list(access.parents)[:3])),
            'unsafe or missing access tool')
    files['runtime/access/access.py'] = access
    # #2201: setup's CloudRoom tool ships from its exact tracked file when the
    # requested commit tracks it; the installer requires it.
    if git(root, 'ls-tree', '-z', '--name-only', '--end-of-options', source,
           '--', 'tools/install/cloudroom/cloudroom.py') == b'tools/install/cloudroom/cloudroom.py\0':
        tool = root / 'tools/install/cloudroom/cloudroom.py'
        require(tool.is_file() and tool.stat().st_nlink == 1
                and not any(p.is_symlink() for p in (tool, *list(tool.parents)[:3])),
                'unsafe or missing CloudRoom setup tool')
        files['runtime/cloudroom/cloudroom.py'] = tool
    # #635: installed `openwiz init`'s runtime, the same way: from its exact
    # tracked file when the requested commit tracks it; the installer requires it.
    if git(root, 'ls-tree', '-z', '--name-only', '--end-of-options', source,
           '--', 'tools/install/setup/init.py') == b'tools/install/setup/init.py\0':
        tool = root / 'tools/install/setup/init.py'
        require(tool.is_file() and tool.stat().st_nlink == 1
                and not any(p.is_symlink() for p in (tool, *list(tool.parents)[:3])),
                'unsafe or missing init runtime')
        files['runtime/setup/init.py'] = tool
    # #633: setup's GitHub sign-in helper, likewise from its exact tracked file
    # when the requested commit tracks it; the installer requires it.
    if git(root, 'ls-tree', '-z', '--name-only', '--end-of-options', source,
           '--', 'tools/install/setup/github_login.py') == b'tools/install/setup/github_login.py\0':
        tool = root / 'tools/install/setup/github_login.py'
        require(tool.is_file() and tool.stat().st_nlink == 1
                and not any(p.is_symlink() for p in (tool, *list(tool.parents)[:3])),
                'unsafe or missing GitHub sign-in helper')
        files['runtime/setup/github_login.py'] = tool
    # #555: a runtime file's repository path, as the receipt records it and the
    # candidate verifies it: a skill is skills/<path>, the path users and briefs
    # see through the link, even when its bytes come from the WizSkills install.
    def repository(name, path):
        return name[len('runtime/'):] if name.startswith('runtime/skills/') else path.relative_to(root).as_posix()

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
            runtime[repository(name, path)] = data
    try:
        # #2217: the copied runtime bytes are the requested commit's, before any stamp.
        verify_runtime(root, source, runtime)
        # #1148: so is the compiled program, by its own build identity and
        # receipt; a correct architecture or stamp is not.
        products = verify_programs({p: (output / name).read_bytes() for p, name in COMPILED.items()},
                                   program_receipt, version, source, target)
        selection = sorted([repository(name, path), name] for name, path in files.items()
                           if name.startswith('runtime/'))
        products.append({'identity': expected('runtime', version, source, target),
                         'verification': 'tracked-tree',
                         'build_receipt': {'record': 'tracked-tree',
                                           'sha256': sha(canonical({'source': source, 'selection': selection}))}})
    except Exception:
        shutil.rmtree(output)
        raise
    identity = f'openwiz.package.v1\n{version}\n{source}\n{target}\n'.encode()
    for name in ('runtime/openwiz-build.txt',):
        destination = output / name
        require(not destination.exists(), 'build stamp must be produced in this job')
        destination.write_bytes(identity)
        destination.chmod(0o600)
        rows.append({'path':name, 'sha256':sha(identity), 'bytes':len(identity), 'mode':'0600'})
    # #2539: the runtime payload is its complete final inventory, stamp
    # included; the stamp is a deterministic function of version/source/target.
    for product in products:
        kind = product['identity']['product']
        if kind == 'runtime':
            product['payload_sha256'] = payload([r for r in rows if r['path'].startswith(kind + '/')])
    record = {'schema': 'openwiz.product-record.v1', 'version': version, 'source': source, 'target': target,
              'products': sorted(products, key=lambda row: row['identity']['product'])}
    return {'schema':'openwiz.build-products.v1', 'version':version, 'source':source,
            'target':target, 'assets':rows}, record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('root', 'binaries', 'output', 'program-receipt'):
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
