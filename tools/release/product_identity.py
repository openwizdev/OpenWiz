#!/usr/bin/env python3
"""Verify packaged products against the requested release identity.

#2217 (RL4-R): the tracked runtime (skills and runtime tools) must be exactly
the requested source commit's regular-file blobs, and its skills exactly that
commit's skills tree, before the collector accepts or stamps them.

#555 (WZ12): a source that tracks `skills` as a link takes its skills from the
gitignored WizSkills install that its `wizskills.lock` pins. The install must
be exactly the lock's release tree (tools/wizskills/install.py's own check),
and the packaged skills exactly that tree's `skills/` blobs; a missing or
edited install refuses.

#1148 (RL4): the compiled CLI identity of contracts/release-candidate.v1.md,
"Minimum product identity (RL4)". The native build job runs `query` to write
its receipt; the collector verifies the product against it without executing
any program; `artifacts` binds one target's packaged files for the release
candidate. Never publishes. (The server, the service and the web export, and
their identities, went in #1264.)
"""
import argparse
import hashlib
import importlib.util
import io
import json
import os
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
PROGRAMS = {'cli': 'openwiz'}
STAMPS = ('runtime/openwiz-build.txt',)


def git(root, *args):
    return subprocess.run(['git', '--no-replace-objects', '-C', str(root), *args],
                          check=True, capture_output=True).stdout


def skill(path):
    return path == 'skills' or path.startswith('skills/')


LINK = ('120000', 'blob')
WIZSKILLS = '.wizskills'


def wizskills():
    """tools/wizskills/install.py, loaded under its own name (`install` is the product installer)."""
    path = Path(__file__).resolve().parents[1] / 'wizskills' / 'install.py'
    spec = importlib.util.spec_from_file_location('wizskills_install', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_tree(root, source):
    """{path: (mode, kind, oid)} of the requested commit, or refuse."""
    require(digest(source, 40), 'invalid runtime source')
    resolved = git(root, 'rev-parse', '--verify', '--quiet', '--end-of-options', source + '^{commit}')
    require(resolved == (source + '\n').encode(), 'runtime source is not the requested commit')
    tree = {}
    for entry in git(root, 'ls-tree', '-r', '-z', '--full-tree', source).split(b'\0'):
        if entry:
            meta, path = entry.split(b'\t', 1)
            mode, kind, oid = meta.decode('ascii').split(' ')
            tree[path.decode('utf-8')] = (mode, kind, oid)
    return tree


def install_locked(root, source, scratch):
    """For a source tracking the WizSkills link, install the release its own
    lock pins under `scratch` (tools/wizskills/install.py, which verifies the
    tag, commit and tree) and return that install; None for a source that
    tracks its skills. For a checkout without a working tree (#555: the
    release candidate's bare clone)."""
    tree = source_tree(root, source)
    if tree.get('skills', ('', '', ''))[:2] != LINK:
        return None
    scratch = Path(scratch)
    for path in ('wizskills.lock', 'contracts/wizskills.v1.md'):
        require(tree.get(path, ('', '', ''))[:2] in {(m, 'blob') for m in REGULAR}, 'skills link without a WizSkills lock')
        (scratch / path).parent.mkdir(parents=True, exist_ok=True)
        (scratch / path).write_bytes(git(root, 'cat-file', 'blob', tree[path][2]))
    ws = wizskills()
    try:
        ws.install(scratch)
    except ws.Stop:
        raise Refused('the locked WizSkills release cannot be installed')
    return scratch / WIZSKILLS


def locked_skills(root, source, tree=None, install=None):
    tree = tree if tree is not None else source_tree(root, source)
    if tree.get('skills', ('', '', ''))[:2] != LINK:
        return None
    require(git(root, 'cat-file', 'blob', tree['skills'][2]) == b'.wizskills/skills',
            'skills link does not point at the WizSkills install')
    require(tree.get('wizskills.lock', ('', '', ''))[:2] in {(m, 'blob') for m in REGULAR},
            'skills link without a WizSkills lock')
    ws = wizskills()
    try:
        lock = ws.identity(git(root, 'cat-file', 'blob', tree['wizskills.lock'][2]).decode('utf-8'),
                           ['version', 'commit', 'tree'],
                           {'version_pattern': r'[0-9]+\.[0-9]+\.[0-9]+', 'oid_pattern': '[0-9a-f]{40}'})
    except (ValueError, UnicodeError):
        raise Refused('invalid WizSkills lock')
    dest = Path(install) if install is not None else Path(root) / WIZSKILLS
    require(os.path.lexists(dest), 'WizSkills install missing')
    with tempfile.TemporaryDirectory(prefix='wizskills-verify-') as scratch:
        try:
            ws.verify_install(dest, lock, Path(scratch))
            listed = ws.out(['--git-dir', str(dest / '.git'), 'ls-tree', '-r', '-z', '--full-tree',
                             lock['tree'], '--', 'skills', 'contracts'], ws.git_env(), 'WizSkills install unreadable')
        except ws.Stop:
            raise Refused('WizSkills install is not the locked release')
    skills = {}
    for entry in listed.split('\0'):
        if entry:
            meta, path = entry.split('\t', 1)
            mode, kind, oid = meta.split(' ')
            require(kind == 'blob' and mode in REGULAR, 'WizSkills skill is not a regular file')
            skills[path] = oid
    require(any(skill(path) for path in skills), 'WizSkills release has no skills')
    return skills


def verify_runtime(root, source, runtime, install=None):
    """Refuse unless `runtime` ({repository path: packaged bytes}) is the
    requested commit's tracked runtime: every file a regular blob there with
    identical bytes, and the skills exactly the commit's skills tree."""
    tree = source_tree(root, source)
    installed = locked_skills(root, source, tree, install)
    if installed is not None:
        released = lambda p: skill(p) or p.startswith('contracts/')
        require(set(installed) == {p for p in runtime if released(p)},
                'packaged skills differ from the locked WizSkills release')
        for path in installed:
            data = runtime[path]
            require(hashlib.sha1(b'blob %d\0' % len(data) + data).hexdigest() == installed[path],
                    'packaged skill differs from the locked WizSkills release')
        runtime = {p: d for p, d in runtime.items() if not released(p)}
    else:
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
    return '0700' if name in PROGRAMS.values() or name.endswith('.sh') \
        or re.fullmatch(r'runtime/adapters/[a-z0-9-]+/driver', name) else '0600'  # #1699: a host driver


def payload(rows):
    """A runtime payload hash: its path-sorted {path, mode, bytes, sha256} rows."""
    return sha(canonical(sorted(rows, key=lambda row: row['path'])))


ELF_MACHINES = {'aarch64-unknown-linux-gnu': 183, 'x86_64-unknown-linux-gnu': 62}
MACHO_CPUS = {'aarch64-apple-darwin': 0x100000c, 'x86_64-apple-darwin': 0x1000007}


def architecture(data, target):
    if target in ELF_MACHINES:
        return (data[:6] == b'\x7fELF\x02\x01' and len(data) >= 20
                and struct.unpack_from('<H', data, 18)[0] == ELF_MACHINES[target])
    if target in MACHO_CPUS:
        return (data[:4] == b'\xcf\xfa\xed\xfe' and len(data) >= 8
                and struct.unpack_from('<I', data, 4)[0] == MACHO_CPUS[target])
    return False


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
    for (product, name), row in zip(sorted(PROGRAMS.items()), value['programs'] + [None] * len(PROGRAMS)):
        data, want = programs[product], expected(product, version, source, target)
        require(architecture(data, target) and embedded(data) == want, 'stale or mismatched compiled product')
        require(len(value['programs']) == len(PROGRAMS) and row == {'product': product, 'program': name, 'sha256': sha(data),
                'bytes': len(data), 'identity': want}, 'program differs from its native query receipt')
        rows.append({'identity': want, 'payload_sha256': sha(data), 'verification': 'embedded-record',
                     'build_receipt': evidence})
    return rows


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
    bound = commands.add_parser('artifacts', help="write one target's candidate artifact rows")
    bound.add_argument('--identity', required=True, type=Path)
    bound.add_argument('--packages', required=True, type=Path)
    for command in (native, bound):
        command.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        require(not args.output.exists(), 'output must be new')
        if args.command == 'query':
            value = query(args.binaries, args.target)
        else:
            value = {'schema': 'openwiz.candidate-artifacts.v1', 'artifacts': artifacts(args.identity, args.packages)}
        args.output.write_bytes(canonical(value) + b'\n')
        return 0
    except (Refused, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('product-identity: refused unidentified or mismatched products', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
