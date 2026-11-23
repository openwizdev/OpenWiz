#!/usr/bin/env python3
import argparse
import gzip
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'install'))
from install import Refused, PROGRAMS, REQUIRED, TARGETS, digest, manifest_at, require, safe, sha, shape, unique

DESCRIPTION = """Assemble artifacts only from an exact hash-bound build inventory. Never publish."""


def assemble(products, identity, output):
    value = json.loads(identity.read_bytes(), object_pairs_hook=unique)
    shape(value, 'schema version source target assets')
    require(value['schema'] == 'openwiz.build-products.v1', 'invalid build identity')
    require(value['target'] in TARGETS and digest(value['source'], 40), 'invalid build target/source')
    name = f"openwiz-{value['version']}-{value['target']}"
    manifest = dict(value, schema='openwiz.install.v1', setup_api=1, archive=name + '.tar.gz',
                    archive_sha256='0' * 64, archive_bytes=1)
    manifest['assets'] = sorted(value['assets'], key=lambda row: row['path'])
    with tempfile.TemporaryDirectory(prefix='openwiz-manifest-') as temporary:
        test = Path(temporary) / 'manifest.json'
        raw = json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode() + b'\n'
        test.write_bytes(raw)
        _, assets, _ = manifest_at(test, sha(raw), value['target'])
    actual = {}
    require(products.is_dir() and not products.is_symlink(), 'invalid product root')
    for parent, dirs, files in os.walk(products, followlinks=False):
        require(not any((Path(parent) / d).is_symlink() for d in dirs), 'symlink product directory')
        for file in files:
            path = Path(parent) / file
            require(path.is_file() and not path.is_symlink() and path.stat().st_nlink == 1, 'unsafe product file')
            relative = safe(path.relative_to(products).as_posix())
            actual[relative] = path
    require(set(actual) == set(assets), 'build inventory must equal the complete product tree')
    for path, file in actual.items():
        require(file.stat().st_size == assets[path]['bytes'] and sha(file.read_bytes()) == assets[path]['sha256'],
                'build product differs from reviewed identity')
    require(not output.exists() and output.parent.is_dir(), 'output must be new with an existing parent')
    with tempfile.TemporaryDirectory(prefix='.package-', dir=output.parent) as temporary:
        stage = Path(temporary)
        archive = stage / manifest['archive']
        with archive.open('wb') as stream, gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as gz:
            with tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                for path, item in assets.items():
                    info = tarfile.TarInfo(path)
                    info.mode, info.size = int(item['mode'], 8), item['bytes']
                    data = actual[path].read_bytes()
                    require(sha(data) == item['sha256'], 'product changed during assembly')
                    tar.addfile(info, io.BytesIO(data))
        manifest['archive_sha256'] = sha(archive.read_bytes())
        manifest['archive_bytes'] = archive.stat().st_size
        manifest_file = stage / (name + '.manifest.json')
        manifest_file.write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n')
        alias = stage / ('openwiz-' + value['target'] + '.manifest.json')
        alias.write_bytes(manifest_file.read_bytes())
        (stage / ('openwiz-' + value['target'] + '.sha256')).write_text(sha(alias.read_bytes()) + '  ' + alias.name + '\n')
        (stage / 'SHA256SUMS').write_text(''.join(sha(p.read_bytes()) + '  ' + p.name + '\n'
            for p in (manifest_file, archive)))
        os.rename(stage, output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    for key in ('products', 'identity', 'output'):
        parser.add_argument('--' + key, required=True, type=Path)
    try:
        assemble(**vars(parser.parse_args()))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError):
        print('package: refused mismatched or incomplete build products', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
