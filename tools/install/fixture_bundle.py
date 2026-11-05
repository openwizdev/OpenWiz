#!/usr/bin/env python3
"""Synthetic package for installed-server proofs; never a distributable release.

Only openwiz-server is a supplied real test executable; CLI/service and skills
are inert synthetic assets. Native build identity is tested by the assembler's
separate proofs and artifact job, not inferred from this fixture.
"""
import argparse
import io
import json
from pathlib import Path
import sys
import tarfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from install import HANDOVER_RUNTIME, PROGRAMS, REQUIRED, sha


def create(output, server, web, service=None, source='1' * 40):
    output.mkdir(mode=0o700)
    assets = {path: b'Synthetic runtime, no effects.\n' for path in REQUIRED}
    for program in PROGRAMS:
        assets[program] = b'#!/bin/sh\nexit 0\n'
    assets['openwiz-server'] = server.read_bytes()
    if service:
        assets['openwiz-service'] = service.read_bytes()
    for path in web.rglob('*'):
        if path.is_file():
            assets['web/' + path.relative_to(web).as_posix()] = path.read_bytes()
    for name in ('install.py', 'pull.py'):
        assets['runtime/' + name] = Path(__file__).with_name(name).read_bytes()
    identity = f"openwiz.package.v1\n0.0.99\n{source}\nx86_64-unknown-linux-gnu\n".encode()
    assets['web/openwiz-build.txt'] = identity
    assets['runtime/openwiz-build.txt'] = identity
    archive = output / 'fixture.tar.gz'
    rows = []
    with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
        for path, data in sorted(assets.items()):
            mode = '0700' if path in PROGRAMS or path.endswith('.sh') else '0600'
            info = tarfile.TarInfo(path)
            info.size, info.mode = len(data), int(mode, 8)
            tar.addfile(info, io.BytesIO(data))
            rows.append({'path':path, 'sha256':sha(data), 'bytes':len(data), 'mode':mode})
    manifest = output / 'fixture.manifest.json'
    manifest.write_text(json.dumps({'schema':'openwiz.install.v1', 'version':'0.0.99',
        'source':source, 'target':'x86_64-unknown-linux-gnu', 'setup_api':1,
        'archive':archive.name, 'archive_sha256':sha(archive.read_bytes()),
        'archive_bytes':archive.stat().st_size, 'assets':rows}))
    return {'manifest':str(manifest), 'archive':str(archive), 'checksum':sha(manifest.read_bytes())}


def handover_runtime(tools=Path(__file__).resolve().parent):
    """The reviewed tracked handover files, at their installed runtime paths."""
    return {path: (tools / path.removeprefix('runtime/')).read_bytes() for path in HANDOVER_RUNTIME}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('output', 'server', 'web'):
        parser.add_argument('--' + flag, type=Path, required=True)
    parser.add_argument('--service', type=Path)
    parser.add_argument('--source', default='1' * 40)
    print(json.dumps(create(**vars(parser.parse_args()))))
