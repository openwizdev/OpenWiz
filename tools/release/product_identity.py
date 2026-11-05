#!/usr/bin/env python3
"""Verify packaged products against the requested release identity.

#2217 (RL4-R): the tracked runtime (skills and runtime tools) must be exactly
the requested source commit's regular-file blobs, and its skills exactly that
commit's skills tree, before the collector accepts or stamps them.

#1148 (RL4): the compiled CLI/server/service and generated web identity of
contracts/release-candidate.v1.md, "Minimum product identity (RL4)". The
native build job runs `query` and `web` to write its receipts; the collector
verifies each product against them without executing any program; `artifacts`
binds one target's packaged files for the release candidate. Never publishes.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tarfile
import tempfile
import zlib

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'install'))
from install import Refused, digest, manifest_at, require, safe, sha, unique

REGULAR = ('100644', '100755')
RECORD = b'OPENWIZ_PRODUCT_V1:'
SCHEMA = 'openwiz.product.v1'
RECEIPT = 'openwiz.build-receipt.v1'
FIELDS = {'schema', 'product', 'version', 'source', 'target'}
PROGRAMS = {'cli': 'openwiz', 'server': 'openwiz-server', 'service': 'openwiz-service'}
WEB_IDENTITY = 'openwiz-product.json'
STAMPS = ('web/openwiz-build.txt', 'runtime/openwiz-build.txt')


def git(root, *args):
    return subprocess.run(['git', '--no-replace-objects', '-C', str(root), *args],
                          check=True, capture_output=True).stdout


def skill(path):
    return path == 'skills' or path.startswith('skills/')


def verify_runtime(root, source, runtime):
    """Refuse unless `runtime` ({repository path: packaged bytes}) is the
    requested commit's tracked runtime: every file a regular blob there with
    identical bytes, and the skills exactly the commit's skills tree."""
    require(digest(source, 40), 'invalid runtime source')
    resolved = git(root, 'rev-parse', '--verify', '--quiet', '--end-of-options', source + '^{commit}')
    require(resolved == (source + '\n').encode(), 'runtime source is not the requested commit')
    tree = {}
    for entry in git(root, 'ls-tree', '-r', '-z', '--full-tree', source).split(b'\0'):
        if entry:
            meta, path = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode('ascii').split(' ')
            tree[path.decode('utf-8')] = (mode, kind, oid)
    require({p for p in tree if skill(p)} == {p for p in runtime if skill(p)},
            'tracked skills differ from the requested source')
    for path, data in runtime.items():
        mode, kind, oid = tree.get(path, ('', '', ''))
        require(kind == 'blob' and mode in REGULAR, 'runtime file is not a regular file in the requested source')
        blob = hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest()
        require(blob == oid, 'stale tracked runtime')


def canonical(value):
    """The contract's canonical JSON bytes."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def strict(raw):
    def refuse(_):
        raise Refused('nonfinite number')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique, parse_constant=refuse)


def release_version(value):
    """The release candidate contract's version: 0.<minor>.<patch>, no leading zeroes."""
    return isinstance(value, str) and re.fullmatch(r'0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value) is not None


def expected(product, version, source, target):
    return {'schema': SCHEMA, 'product': product, 'version': version, 'source': source, 'target': target}


def identity(raw):
    """A strict, canonical product identity, or refuse."""
    value = strict(raw)
    require(type(value) is dict and set(value) == FIELDS and all(type(v) is str for v in value.values())
            and value['schema'] == SCHEMA and canonical(value) == raw, 'malformed product identity')
    return value


def mode(name):
    return '0700' if name in PROGRAMS.values() or name.endswith('.sh') else '0600'


def payload(rows):
    """A web/runtime payload hash: its path-sorted {path, mode, bytes, sha256} rows."""
    return sha(canonical(sorted(rows, key=lambda row: row['path'])))


def architecture(data, target):
    if target.endswith('linux-gnu'):
        return data[:6] == b'\x7fELF\x02\x01' and len(data) >= 20 and struct.unpack_from('<H', data, 18)[0] == 62
    cpu = 0x100000c if target.startswith('aarch64') else 0x1000007
    return data[:4] == b'\xcf\xfa\xed\xfe' and len(data) >= 8 and struct.unpack_from('<I', data, 4)[0] == cpu


def segments(data):
    """The file ranges a 64-bit little-endian ELF or Mach-O program loads.
    Mach-O's __LINKEDIT (symbols, signature) holds no compiled data."""
    ranges = []
    try:
        if data[:6] == b'\x7fELF\x02\x01':
            table, (size, count) = struct.unpack_from('<Q', data, 32)[0], struct.unpack_from('<HH', data, 54)
            require(size >= 56, 'malformed program headers')
            for at in range(table, table + size * count, size):
                if struct.unpack_from('<I', data, at)[0] == 1:
                    start, length = struct.unpack_from('<Q', data, at + 8)[0], struct.unpack_from('<Q', data, at + 32)[0]
                    ranges.append((start, start + length))
        elif data[:4] == b'\xcf\xfa\xed\xfe':
            at = 32
            for _ in range(struct.unpack_from('<I', data, 16)[0]):
                command, length = struct.unpack_from('<II', data, at)
                require(length >= 8, 'malformed load commands')
                if command == 0x19 and data[at + 8:at + 24].rstrip(b'\0') != b'__LINKEDIT':
                    start, size = struct.unpack_from('<QQ', data, at + 40)
                    ranges.append((start, start + size))
                at += length
    except struct.error:
        raise Refused('malformed program headers')
    return ranges


def embedded(data):
    """The one product identity compiled into a program's loaded segments;
    absent, repeated, appended or malformed records refuse."""
    require(data.count(RECORD) == 1, 'missing or ambiguous compiled product identity')
    start = data.index(RECORD)
    end = data.find(b'\n', start)
    require(end > start and any(low <= start and end < high for low, high in segments(data)),
            'product identity outside the compiled program')
    return identity(data[start + len(RECORD):end])


def native_query(path):
    """Run a native program's `--build-identity` with no environment in an
    empty directory; it must leave that empty and print its compiled record."""
    data = path.read_bytes()
    record = embedded(data)
    with tempfile.TemporaryDirectory(prefix='openwiz-identity-query-') as empty:
        result = subprocess.run([str(path.resolve()), '--build-identity'], env={}, cwd=empty,
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
        untouched = not any(Path(empty).iterdir())
    require(result.returncode == 0 and not result.stderr and untouched
            and result.stdout == canonical(record) + b'\n', 'native identity query differs from the compiled record')
    return record, data


def query(binaries, target):
    """The native build job's receipt: each program it just built, queried."""
    rows = []
    for product, name in sorted(PROGRAMS.items()):
        path = binaries / name
        require(path.is_file() and not path.is_symlink(), 'missing native program')
        record, data = native_query(path)
        require(architecture(data, target) and record['product'] == product and record['target'] == target,
                'native program target or product mismatch')
        rows.append({'product': product, 'program': name, 'sha256': sha(data), 'bytes': len(data), 'identity': record})
    return {'schema': RECEIPT, 'method': 'native-query', 'target': target, 'programs': rows}


def inventory(web):
    """A web export's install-relative rows."""
    rows = []
    for path in sorted(web.rglob('*')):
        require(not path.is_symlink(), 'web symlink')
        if path.is_file():
            data, name = path.read_bytes(), 'web/' + path.relative_to(web).as_posix()
            rows.append({'path': name, 'mode': mode(name), 'bytes': len(data), 'sha256': sha(data)})
    return sorted(rows, key=lambda row: row['path'])


def record_web(web):
    """The web build job's receipt, written right after the export it made."""
    raw = (web / WEB_IDENTITY).read_bytes()
    require(raw.endswith(b'\n'), 'malformed web product identity')
    value = identity(raw[:-1])
    require(value['product'] == 'web', 'web product identity mismatch')
    rows = inventory(web)
    return {'schema': RECEIPT, 'method': 'web-build', 'identity': value, 'payload_sha256': payload(rows),
            'inventory': rows}


def receipt(path):
    raw = path.read_bytes()
    return strict(raw), {'record': path.name, 'sha256': sha(raw)}


def verify_programs(programs, path, version, source, target):
    """Refuse unless each program's one compiled record is this build's
    identity and its bytes are the ones the native build job queried.
    `programs` is {product: packaged bytes}. Nothing is executed."""
    value, evidence = receipt(path)
    require(type(value) is dict and set(value) == {'schema', 'method', 'target', 'programs'}
            and value['schema'] == RECEIPT and value['method'] == 'native-query' and value['target'] == target
            and type(value['programs']) is list, 'invalid native query receipt')
    rows = []
    for (product, name), row in zip(sorted(PROGRAMS.items()), value['programs'] + [None] * 3):
        data, want = programs[product], expected(product, version, source, target)
        require(architecture(data, target) and embedded(data) == want, 'stale or mismatched compiled product')
        require(len(value['programs']) == 3 and row == {'product': product, 'program': name, 'sha256': sha(data),
                'bytes': len(data), 'identity': want}, 'program differs from its native query receipt')
        rows.append({'identity': want, 'payload_sha256': sha(data), 'verification': 'embedded-record',
                     'build_receipt': evidence})
    return rows


def verify_web(rows, path, version, source, target):
    """Refuse unless the packaged web rows are exactly the export the web
    build job recorded, carrying this build's generated identity."""
    value, evidence = receipt(path)
    want = expected('web', version, source, target)
    marker = [row for row in rows if row['path'] == 'web/' + WEB_IDENTITY]
    require(type(value) is dict and set(value) == {'schema', 'method', 'identity', 'payload_sha256', 'inventory'}
            and value['schema'] == RECEIPT and value['method'] == 'web-build' and value['identity'] == want
            and value['inventory'] == sorted(rows, key=lambda row: row['path'])
            and value['payload_sha256'] == payload(rows), 'web export differs from its build receipt')
    data = canonical(want) + b'\n'
    require(marker == [{'path': 'web/' + WEB_IDENTITY, 'mode': '0600', 'bytes': len(data), 'sha256': sha(data)}],
            'stale or missing web product identity')
    return {'identity': want, 'payload_sha256': payload(rows), 'verification': 'web-build', 'build_receipt': evidence}


def members(archive, assets):
    """Refuse unless the archive's members are exactly the expected assets,
    read by the installer's archive rules: each one a plain regular file at a
    safe listed path, once, with its listed size, mode and SHA-256."""
    seen = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode='r:gz') as tar:
            for member in tar:
                require(len(seen) < len(assets), 'archive asset count mismatch')
                path = safe(member.name)
                require(member.isfile() and not member.pax_headers and path not in seen and path in assets,
                        'unsafe, duplicate or unlisted archive member')
                item = assets[path]
                require(member.size == item['bytes'] and member.mode == int(item['mode'], 8),
                        'archive asset metadata mismatch')
                require(sha(tar.extractfile(member).read()) == item['sha256'], 'asset checksum mismatch')
                seen.add(path)
    except (tarfile.TarError, EOFError, OSError, zlib.error):
        raise Refused('unreadable archive')
    require(seen == set(assets), 'incomplete archive')


def artifacts(products, packages):
    """One target's release-candidate artifact rows, after checking its
    package against the collector's products identity. The global
    SHA256SUMS across targets is the release command's."""
    value = strict(products.read_bytes())
    version, target = value['version'], value['target']
    names = {f'openwiz-{version}-{target}.tar.gz': 'archive', f'openwiz-{version}-{target}.manifest.json': 'manifest',
             f'openwiz-{target}.manifest.json': 'manifest_alias', f'openwiz-{target}.sha256': 'manifest_checksum'}
    files = {path.name: path for path in packages.iterdir()}
    require(set(files) == set(names) | {'SHA256SUMS'}
            and all(p.is_file() and not p.is_symlink() for p in files.values()), 'incomplete or unexpected package files')
    data = {name: files[name].read_bytes() for name in files}
    manifest, alias, archive = (f'openwiz-{version}-{target}.manifest.json', f'openwiz-{target}.manifest.json',
                                f'openwiz-{version}-{target}.tar.gz')
    installed, assets, _ = manifest_at(files[manifest], sha(data[manifest]), target)
    require(installed['version'] == version and installed['source'] == value['source']
            and installed['assets'] == sorted(value['assets'], key=lambda row: row['path'])
            and installed['archive'] == archive and installed['archive_sha256'] == sha(data[archive])
            and installed['archive_bytes'] == len(data[archive]), 'package differs from its products identity')
    require(data[alias] == data[manifest] and data[f'openwiz-{target}.sha256'] == f'{sha(data[alias])}  {alias}\n'.encode()
            and data['SHA256SUMS'] == f'{sha(data[manifest])}  {manifest}\n{sha(data[archive])}  {archive}\n'.encode(),
            'package alias or checksum mismatch')
    members(data[archive], assets)
    return [{'name': name, 'role': role, 'target': target, 'sha256': sha(data[name]), 'bytes': len(data[name])}
            for name, role in sorted(names.items())]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest='command', required=True)
    native = commands.add_parser('query', help="write the native build job's program receipt")
    native.add_argument('--binaries', required=True, type=Path)
    native.add_argument('--target', required=True)
    web = commands.add_parser('web', help="write the web build job's receipt")
    web.add_argument('--web', required=True, type=Path)
    bound = commands.add_parser('artifacts', help="write one target's candidate artifact rows")
    bound.add_argument('--identity', required=True, type=Path)
    bound.add_argument('--packages', required=True, type=Path)
    for command in (native, web, bound):
        command.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        require(not args.output.exists(), 'output must be new')
        if args.command == 'query':
            value = query(args.binaries, args.target)
        elif args.command == 'web':
            value = record_web(args.web)
        else:
            value = {'schema': 'openwiz.candidate-artifacts.v1', 'artifacts': artifacts(args.identity, args.packages)}
        args.output.write_bytes(canonical(value) + b'\n')
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('product-identity: refused unidentified or mismatched products', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
