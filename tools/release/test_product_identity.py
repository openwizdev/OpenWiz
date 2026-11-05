#!/usr/bin/env python3
"""#2217 (RL4-R) and #1148 (RL4): packaged product identity, through the collector.

Each case builds a synthetic Git repository, runs the real collector against a
requested source commit and observes only its exit status and its products.
A stale or mismatched tracked runtime (#2217), or a compiled program or web
export without this build's own identity (#1148), must refuse and leave no
products; the exact matching products are accepted and stamped.
"""
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / 'tools/release/build_products.py'
TARGET = 'x86_64-unknown-linux-gnu'
VERSION = '0.0.99'
GIT = ['git', '-c', 'user.name=Synthetic Builder', '-c', 'user.email=builder@example.invalid',
       '-c', 'commit.gpgsign=false', '-c', 'init.defaultBranch=main']
# Every tracked runtime file the collector packages, with synthetic bytes.
RUNTIME = {
    'skills/synthetic/SKILL.md': b'Synthetic skill.\n',
    'skills/synthetic/scripts/run.sh': b'#!/bin/sh\necho synthetic\n',
    'tools/install/install.py': b'# Synthetic installer.\n',
    'tools/install/pull.py': b'# Synthetic pull.\n',
    'tools/install/setup/setup.py': b'# Synthetic setup.\n',
    'tools/install/setup/store.py': b'# Synthetic store.\n',
    'tools/install/platform/runtime.py': b'# Synthetic platform runtime.\n',
    'tools/install/access/access.py': b'# Synthetic access tool.\n',
    'tools/install/engine/engine.py': b'# Synthetic engine.\n',
    'tools/github-app/setup.py': b'# Synthetic App setup.\n',
    'tools/github-app/app.py': b'# Synthetic App.\n',
    'tools/github-app/manifest.json': b'{"name":"Synthetic App"}\n',
}
PACKAGED = {'tools/install/install.py': 'runtime/install.py', 'tools/install/pull.py': 'runtime/pull.py',
            'tools/install/setup/setup.py': 'runtime/setup/setup.py',
            'tools/install/setup/store.py': 'runtime/setup/store.py',
            'tools/install/platform/runtime.py': 'runtime/platform/runtime.py',
            'tools/install/access/access.py': 'runtime/access/access.py',
            'tools/install/engine/engine.py': 'runtime/engine/engine.py',
            'tools/github-app/setup.py': 'runtime/github-app/setup.py',
            'tools/github-app/app.py': 'runtime/github-app/app.py',
            'tools/github-app/manifest.json': 'runtime/github-app/manifest.json'}


# #1148: contracts/release-candidate.v1.md, "Minimum product identity (RL4)".
RECORD = b'OPENWIZ_PRODUCT_V1:'
PROGRAMS = {'cli': 'openwiz', 'server': 'openwiz-server', 'service': 'openwiz-service'}
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')


def canonical(value):
    """The contract's canonical JSON, quoted from it."""
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def identity(product, source, target, version=VERSION):
    return {'schema': 'openwiz.product.v1', 'product': product, 'version': version,
            'source': source, 'target': target}


def program(target, *records, appended=b''):
    """A synthetic 64-bit program for `target`: one loaded segment covering the
    whole file, holding each given compiled record, then any appended bytes."""
    body = b'synthetic compiled program\0' + b''.join(
        RECORD + (r if isinstance(r, bytes) else canonical(r)) + b'\n' for r in records) + b'\0end'
    if target.endswith('linux-gnu'):
        size = 64 + 56 + len(body)
        header = bytearray(64)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<HHIQQQIHHHHHH', header, 16, 2, 62, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
        segment = struct.pack('<IIQQQQQQ', 1, 5, 0, 0, 0, size, size, 0x1000)
    else:
        size = 32 + 72 + len(body)
        cpu = 0x100000c if target.startswith('aarch64') else 0x1000007
        header = struct.pack('<IiiIIIII', 0xfeedfacf, cpu, 0, 2, 1, 72, 0, 0)
        segment = struct.pack('<II16sQQQQiiII', 0x19, 72, b'__TEXT', 0, size, 0, size, 5, 5, 0, 0)
    return bytes(header) + segment + body + appended


def inventory(web):
    """The install-relative {path, mode, bytes, sha256} rows of a web export."""
    rows = []
    for path in sorted(web.rglob('*')):
        if path.is_file():
            data = path.read_bytes()
            name = 'web/' + path.relative_to(web).as_posix()
            rows.append({'path': name, 'mode': '0700' if name.endswith('.sh') else '0600',
                         'bytes': len(data), 'sha256': sha(data)})
    return sorted(rows, key=lambda row: row['path'])


def build(binaries, web, source, target, work, version=VERSION):
    """What one native build job leaves: three programs compiled with this
    identity, a web export generated with it, and the job's two receipts (here
    written as that job would, since synthetic programs cannot run)."""
    for product, name in PROGRAMS.items():
        (binaries / name).write_bytes(program(target, identity(product, source, target, version)))
    (web / 'openwiz-product.json').write_bytes(canonical(identity('web', source, target, version)) + b'\n')
    programs = [{'product': product, 'program': name, 'sha256': sha((binaries / name).read_bytes()),
                 'bytes': len((binaries / name).read_bytes()), 'identity': identity(product, source, target, version)}
                for product, name in sorted(PROGRAMS.items())]
    receipts = {'program': work / 'program-receipt.json', 'web': work / 'web-receipt.json'}
    receipts['program'].write_bytes(canonical({'schema': 'openwiz.build-receipt.v1', 'method': 'native-query',
                                               'target': target, 'programs': programs}))
    rows = inventory(web)
    receipts['web'].write_bytes(canonical({'schema': 'openwiz.build-receipt.v1', 'method': 'web-build',
        'identity': identity('web', source, target, version), 'payload_sha256': sha(canonical(rows)), 'inventory': rows}))
    return receipts


def collector(root, binaries, web, output, source, target, receipts, version=VERSION):
    return [sys.executable, '-I', str(COLLECTOR), '--root', str(root), '--binaries', str(binaries),
            '--web', str(web), '--output', str(output), '--version', version, '--source', source,
            '--target', target, '--identity', str(output) + '.json', '--record', str(output) + '.record.json',
            '--program-receipt', str(receipts['program']), '--web-receipt', str(receipts['web'])]


class Repository(unittest.TestCase):
    """A synthetic repository and one native build job's products."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='openwiz-runtime-identity-')
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        self.repo = self.work / 'repo'
        for path, data in RUNTIME.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_bytes(data)
        self.git('init', '-q')
        self.source = self.commit('synthetic runtime')
        self.binaries, self.web = self.work / 'bin', self.work / 'web'
        self.binaries.mkdir()
        self.web.mkdir()
        (self.web / 'setup.html').write_bytes(b'Synthetic setup page.\n')
        self.runs = 0

    def git(self, *args):
        return subprocess.run([*GIT, '-C', str(self.repo), *args], check=True,
                              capture_output=True).stdout.decode().strip()

    def commit(self, message):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def collect(self, source, receipts=None):
        # The compiled products match the requested source unless a case says
        # otherwise, so a runtime case refuses only for its runtime.
        receipts = receipts or build(self.binaries, self.web, source, TARGET, self.work)
        self.runs += 1
        output = self.work / f'products-{self.runs}'
        result = subprocess.run(collector(self.repo, self.binaries, self.web, output, source, TARGET, receipts),
                                capture_output=True, text=True)
        return result, output, Path(str(output) + '.json')

    def refused(self, source):
        result, output, identity = self.collect(source)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stderr, 'build-products: refused incomplete or non-native products\n')
        self.assertFalse(output.exists(), 'a refused runtime leaves no products to stamp or package')
        self.assertFalse(identity.exists())


class TrackedRuntimeProvenance(Repository):
    def test_matching_runtime_is_accepted_and_stamped(self):
        result, output, identity = self.collect(self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        stamp = f'openwiz.package.v1\n{VERSION}\n{self.source}\n{TARGET}\n'.encode()
        self.assertEqual((output / 'runtime/openwiz-build.txt').read_bytes(), stamp)
        for path, data in RUNTIME.items():
            packaged = PACKAGED.get(path, 'runtime/' + path)
            self.assertEqual((output / packaged).read_bytes(), data, packaged)
        self.assertTrue(identity.is_file())

    def test_stale_checkout_of_an_older_commit_refuses_a_newer_source(self):
        (self.repo / 'skills/synthetic/SKILL.md').write_bytes(b'Synthetic skill, revised.\n')
        newer = self.commit('revise synthetic skill')
        self.git('checkout', '-q', '--detach', self.source)
        self.refused(newer)

    def test_requested_older_source_refuses_newer_runtime_bytes(self):
        (self.repo / 'tools/install/engine/engine.py').write_bytes(b'# Synthetic engine, revised.\n')
        self.commit('revise synthetic engine')
        self.refused(self.source)

    def test_uncommitted_edits_to_any_tracked_runtime_file_refuse(self):
        for path, data in RUNTIME.items():
            with self.subTest(path=path):
                (self.repo / path).write_bytes(data + b'# uncommitted\n')
                self.refused(self.source)
                (self.repo / path).write_bytes(data)
        self.assertEqual(self.collect(self.source)[0].returncode, 0)

    def test_skill_files_must_be_exactly_the_sources_tracked_skills(self):
        extra = self.repo / 'skills/synthetic/extra.md'
        extra.write_bytes(b'Synthetic staged skill file.\n')
        self.git('add', str(extra))
        self.refused(self.source)
        self.git('rm', '-q', '--cached', str(extra))
        extra.unlink()
        self.git('rm', '-q', '--cached', 'skills/synthetic/SKILL.md')
        self.refused(self.source)

    def test_source_entry_that_is_not_a_regular_file_refuses_identical_bytes(self):
        link = self.repo / 'skills/synthetic/link.md'
        os.symlink('SKILL.md', link)
        linked = self.commit('add synthetic skill link')
        link.unlink()
        link.write_bytes(b'SKILL.md')
        self.refused(linked)

    def test_requested_source_must_name_a_commit_in_the_repository(self):
        tree = self.git('rev-parse', 'HEAD^{tree}')
        blob = self.git('rev-parse', 'HEAD:tools/install/install.py')
        self.git('tag', '-a', '-m', 'synthetic tag', 'v0.0.99')
        tag = self.git('rev-parse', 'v0.0.99')
        self.assertNotEqual(tag, self.source)
        for source in ('0' * 40, tree, blob, tag):
            with self.subTest(source=source):
                self.refused(source)



class CompiledProductIdentity(Repository):
    """#1148: compiled CLI/server/service and generated web identity. The
    runtime always matches here, so each refusal is the compiled product's."""

    def prepared(self, target=TARGET, source=None):
        return build(self.binaries, self.web, source or self.source, target, self.work)

    def requery(self, receipts, target=TARGET, source=None, claimed=None):
        """Rewrite the native receipt over the programs' current bytes, as a
        caller would to make it agree; its claimed identities stay the build's."""
        source = source or self.source
        rows = [{'product': product, 'program': name, 'sha256': sha((self.binaries / name).read_bytes()),
                 'bytes': len((self.binaries / name).read_bytes()),
                 'identity': (claimed or {}).get(product, identity(product, source, target))}
                for product, name in sorted(PROGRAMS.items())]
        receipts['program'].write_bytes(canonical({'schema': 'openwiz.build-receipt.v1', 'method': 'native-query',
                                                   'target': target, 'programs': rows}))

    def rerecord_web(self, receipts, target=TARGET):
        rows = inventory(self.web)
        receipts['web'].write_bytes(canonical({'schema': 'openwiz.build-receipt.v1', 'method': 'web-build',
            'identity': identity('web', self.source, target), 'payload_sha256': sha(canonical(rows)), 'inventory': rows}))

    def refused_with(self, receipts, target=TARGET):
        self.runs += 1
        output = self.work / f'products-{self.runs}'
        result = subprocess.run(collector(self.repo, self.binaries, self.web, output, self.source, target, receipts),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(result.stderr, 'build-products: refused incomplete or non-native products\n')
        self.assertFalse(output.exists(), 'a refused product leaves nothing to stamp or package')
        self.assertFalse(Path(str(output) + '.json').exists())
        self.assertFalse(Path(str(output) + '.record.json').exists())

    def test_architecture_only_programs_refuse_on_every_target(self):
        # #1148 reproduced: a correct executable architecture is not identity.
        for target in TARGETS:
            for name in PROGRAMS.values():
                with self.subTest(target=target, program=name):
                    receipts = self.prepared(target)
                    (self.binaries / name).write_bytes(program(target))
                    self.requery(receipts, target)
                    self.refused_with(receipts, target)

    def test_stale_mismatched_or_malformed_compiled_identity_refuses(self):
        other = '1' * 40
        for product, name in PROGRAMS.items():
            want = identity(product, self.source, TARGET)
            wrong = {
                'older version': [identity(product, self.source, TARGET, '0.0.98')],
                'older source': [identity(product, other, TARGET)],
                'other target': [identity(product, self.source, 'x86_64-apple-darwin')],
                'other product': [identity('server' if product == 'cli' else 'cli', self.source, TARGET)],
                'other schema': [dict(want, schema='openwiz.product.v0')],
                'extra field': [dict(want, build='synthetic')],
                'missing field': [{k: v for k, v in want.items() if k != 'target'}],
                'not canonical': [json.dumps(want).encode()],
                'not JSON': [b'{"product":'],
                'ambiguous': [identity(product, other, TARGET), want],
                'repeated': [want, want],
            }
            for case, records in wrong.items():
                with self.subTest(program=name, case=case):
                    receipts = self.prepared()
                    (self.binaries / name).write_bytes(program(TARGET, *records))
                    self.requery(receipts)
                    self.refused_with(receipts)
            with self.subTest(program=name, case='appended to an unidentified program'):
                receipts = self.prepared()
                (self.binaries / name).write_bytes(program(TARGET, appended=RECORD + canonical(want) + b'\n'))
                self.requery(receipts)
                self.refused_with(receipts)

    def test_a_malformed_release_version_refuses_even_when_every_product_agrees(self):
        # The contract's version: 0.<minor>.<patch>, without leading zeroes.
        for version in ('0.0.1-dev', '1.0.0', '0.01.2', '0.0', ''):
            with self.subTest(version=version):
                receipts = build(self.binaries, self.web, self.source, TARGET, self.work, version)
                self.runs += 1
                output = self.work / f'products-{self.runs}'
                result = subprocess.run(collector(self.repo, self.binaries, self.web, output, self.source, TARGET,
                                                  receipts, version), capture_output=True, text=True)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(output.exists())

    def rebuilt(self, name):
        """Change one ordinary payload byte after the native query: same format,
        same size and the same sole compiled identity, so only the receipt's
        sha256 can tell these bytes from the queried ones."""
        path = self.binaries / name
        queried = path.read_bytes()
        changed = queried.replace(b'synthetic compiled program', b'Synthetic compiled program', 1)
        self.assertEqual((len(changed), changed.count(RECORD), changed[:4]), (len(queried), 1, b'\x7fELF'))
        self.assertEqual(changed[changed.index(RECORD):], queried[queried.index(RECORD):])
        self.assertNotEqual(sha(changed), sha(queried))
        path.write_bytes(changed)

    def test_programs_must_be_the_bytes_the_native_build_job_queried(self):
        cases = {
            'rebuilt after the query': lambda r: self.rebuilt('openwiz-server'),
            'receipt claims another identity': lambda r: self.requery(
                r, claimed={'cli': identity('cli', '1' * 40, TARGET)}),
            'receipt for another target': lambda r: r['program'].write_bytes(
                r['program'].read_bytes().replace(b'"target":"x86_64-unknown-linux-gnu"}', b'"target":"x86_64-apple-darwin"}')),
            'receipt from another method': lambda r: r['program'].write_bytes(
                r['program'].read_bytes().replace(b'native-query', b'embedded-record')),
            'receipt without a program': lambda r: r['program'].write_bytes(canonical(dict(
                json.loads(r['program'].read_bytes()), programs=json.loads(r['program'].read_bytes())['programs'][:2]))),
            'no receipt': lambda r: r['program'].unlink(),
            'malformed receipt': lambda r: r['program'].write_bytes(b'[]'),
        }
        for case, change in cases.items():
            with self.subTest(case=case):
                receipts = self.prepared()
                change(receipts)
                self.refused_with(receipts)

    def test_web_export_must_carry_this_builds_identity_and_receipted_files(self):
        marker = self.web / 'openwiz-product.json'
        cases = {
            'no generated identity': lambda r: (marker.unlink(), self.rerecord_web(r)),
            'stale identity': lambda r: (marker.write_bytes(
                canonical(identity('web', '1' * 40, TARGET)) + b'\n'), self.rerecord_web(r)),
            'identity of another product': lambda r: (marker.write_bytes(
                canonical(identity('cli', self.source, TARGET)) + b'\n'), self.rerecord_web(r)),
            'malformed identity': lambda r: (marker.write_bytes(b'{}\n'), self.rerecord_web(r)),
            'file changed after the build': lambda r: (self.web / 'setup.html').write_bytes(b'Synthetic later page.\n'),
            'file added after the build': lambda r: (self.web / 'later.html').write_bytes(b'Synthetic later page.\n'),
            'no web receipt': lambda r: r['web'].unlink(),
        }
        for case, change in cases.items():
            with self.subTest(case=case):
                receipts = self.prepared()
                change(receipts)
                self.refused_with(receipts)
                for extra in ('later.html',):
                    (self.web / extra).unlink(missing_ok=True)
                (self.web / 'setup.html').write_bytes(b'Synthetic setup page.\n')

    def test_every_target_accepts_its_complete_matching_products_without_running_them(self):
        for target in TARGETS:
            with self.subTest(target=target):
                receipts = self.prepared(target)
                web_rows = inventory(self.web)
                self.runs += 1
                output = self.work / f'products-{self.runs}'
                result = subprocess.run(collector(self.repo, self.binaries, self.web, output, self.source, target,
                                                  receipts), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                record = json.loads(Path(str(output) + '.record.json').read_bytes())
                self.assertEqual(record['schema'], 'openwiz.product-record.v1')
                products = record['products']
                self.assertEqual([row['identity'] for row in products],
                                 [identity(p, self.source, target) for p in ('cli', 'runtime', 'server', 'service', 'web')])
                rows = {row['identity']['product']: row for row in products}
                for product, name in PROGRAMS.items():
                    self.assertEqual(rows[product]['payload_sha256'], sha((self.binaries / name).read_bytes()))
                    self.assertEqual(rows[product]['verification'], 'embedded-record')
                    self.assertEqual(rows[product]['build_receipt'],
                                     {'record': 'program-receipt.json', 'sha256': sha(receipts['program'].read_bytes())})
                # #2539: a web/runtime payload is its complete final inventory,
                # including the package stamp the collector writes.
                stamp = f'openwiz.package.v1\n{VERSION}\n{self.source}\n{target}\n'.encode()
                stamps = {prefix: {'path': prefix + 'openwiz-build.txt', 'mode': '0600',
                                   'bytes': len(stamp), 'sha256': sha(stamp)} for prefix in ('web/', 'runtime/')}
                assets = json.loads(Path(str(output) + '.json').read_bytes())['assets']
                for product in ('web', 'runtime'):
                    final = [row for row in assets if row['path'].startswith(product + '/')]
                    self.assertIn(stamps[product + '/'], final)
                    self.assertEqual(rows[product]['payload_sha256'],
                                     sha(canonical(sorted(final, key=lambda row: row['path']))))
                self.assertEqual(rows['web']['payload_sha256'],
                                 sha(canonical(sorted(web_rows + [stamps['web/']], key=lambda row: row['path']))))
                self.assertEqual(rows['web']['verification'], 'web-build')
                self.assertEqual(rows['web']['build_receipt'],
                                 {'record': 'web-receipt.json', 'sha256': sha(receipts['web'].read_bytes())})
                runtime = [{'path': PACKAGED.get(path, 'runtime/' + path),
                            'mode': '0700' if path.endswith('.sh') else '0600',
                            'bytes': len(data), 'sha256': sha(data)} for path, data in RUNTIME.items()]
                runtime.append(stamps['runtime/'])
                self.assertEqual(rows['runtime']['payload_sha256'],
                                 sha(canonical(sorted(runtime, key=lambda row: row['path']))))
                self.assertEqual(rows['runtime']['verification'], 'tracked-tree')
                self.assertEqual((output / 'web/openwiz-product.json').read_bytes(),
                                 canonical(identity('web', self.source, target)) + b'\n')

    def test_the_export_config_generates_the_web_identity_it_is_built_for(self):
        # next.config.mjs runs at the start of the actual export; copy it alone
        # so its public/ is this case's, never the repository's.
        app = self.work / 'app'
        (app / 'public').mkdir(parents=True)
        config = app / 'next.config.mjs'
        config.write_bytes((ROOT / 'apps/web/next.config.mjs').read_bytes())
        marker = app / 'public/openwiz-product.json'

        def load(**env):
            return subprocess.run(['node', '--input-type=module', '-e', 'await import(process.argv[1])',
                                   config.as_uri()], env={'PATH': os.environ['PATH'], **env},
                                  capture_output=True, text=True)

        built = {'OPENWIZ_BUILD_VERSION': VERSION, 'OPENWIZ_BUILD_TARGET': TARGET, 'OPENWIZ_SERVICE_BUILD': self.source}
        result = load(**built)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_bytes(), canonical(identity('web', self.source, TARGET)) + b'\n')
        receipts = self.prepared()
        (self.web / 'openwiz-product.json').write_bytes(marker.read_bytes())
        self.assertEqual(self.collect(self.source, receipts)[0].returncode, 0)
        for case, env in {'no version': {k: v for k, v in built.items() if k != 'OPENWIZ_BUILD_VERSION'},
                          'no source': {k: v for k, v in built.items() if k != 'OPENWIZ_SERVICE_BUILD'},
                          'bad source': dict(built, OPENWIZ_SERVICE_BUILD='unavailable'),
                          'dev version': dict(built, OPENWIZ_BUILD_VERSION='0.0.1-dev'),
                          'leading zero': dict(built, OPENWIZ_BUILD_VERSION='0.01.2'),
                          'unsupported target': dict(built, OPENWIZ_BUILD_TARGET='synthetic-target')}.items():
            with self.subTest(case=case):
                marker.unlink(missing_ok=True)
                self.assertNotEqual(load(**env).returncode, 0)
                self.assertFalse(marker.exists())
        marker.write_bytes(b'stale\n')
        # An ordinary build, or the service's own update build, carries none.
        for env in ({}, {'OPENWIZ_SERVICE_BUILD': self.source}):
            marker.write_bytes(b'stale\n')
            self.assertEqual(load(**env).returncode, 0)
            self.assertFalse(marker.exists())


class CandidateArtifacts(unittest.TestCase):
    """#2542: `artifacts` binds a package only if its archive holds exactly the
    expected assets, as the installer reads them. Each corruption keeps the
    expected asset inventory and refreshes the archive's size and digests in the
    manifest, its alias and both checksum files, so only the members differ."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='openwiz-candidate-artifacts-')
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name)
        sys.path.insert(0, str(ROOT / 'tools/install'))
        from test_install import REQUIRED
        payload, rows = self.work / 'products', []
        for name in REQUIRED:
            data = f'synthetic {name}\n'.encode()
            if name in ('web/openwiz-build.txt', 'runtime/openwiz-build.txt'):
                data = f'openwiz.package.v1\n{VERSION}\n{"1" * 40}\n{TARGET}\n'.encode()
            (payload / name).parent.mkdir(parents=True, exist_ok=True)
            (payload / name).write_bytes(data)
            mode = '0700' if name in PROGRAMS.values() or name.endswith('.sh') else '0600'
            rows.append({'path': name, 'sha256': sha(data), 'bytes': len(data), 'mode': mode})
        self.identity = self.work / 'products.json'
        self.identity.write_text(json.dumps({'schema': 'openwiz.build-products.v1', 'version': VERSION,
                                             'source': '1' * 40, 'target': TARGET, 'assets': rows}))
        self.packages = self.work / 'packages'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/release/package.py'), '--products',
                                 str(payload), '--identity', str(self.identity), '--output', str(self.packages)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.archive = self.packages / f'openwiz-{VERSION}-{TARGET}.tar.gz'
        with tarfile.open(self.archive, 'r:gz') as tar:
            self.members = [(member, tar.extractfile(member).read()) for member in tar]
        self.assertEqual(len(self.members), len(REQUIRED))
        self.runs = 0

    def artifacts(self):
        self.runs += 1
        output = self.work / f'artifacts-{self.runs}.json'
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/release/product_identity.py'), 'artifacts',
                                 '--identity', str(self.identity), '--packages', str(self.packages),
                                 '--output', str(output)], capture_output=True, text=True)
        return result, output

    def repack(self, archive):
        """Replace the archive and refresh every digest and size bound to it."""
        self.archive.write_bytes(archive)
        manifest = self.packages / f'openwiz-{VERSION}-{TARGET}.manifest.json'
        value = json.loads(manifest.read_bytes())
        value.update(archive_sha256=sha(archive), archive_bytes=len(archive))
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode() + b'\n'
        alias = self.packages / f'openwiz-{TARGET}.manifest.json'
        manifest.write_bytes(raw)
        alias.write_bytes(raw)
        (self.packages / f'openwiz-{TARGET}.sha256').write_bytes(f'{sha(raw)}  {alias.name}\n'.encode())
        (self.packages / 'SHA256SUMS').write_bytes(
            f'{sha(raw)}  {manifest.name}\n{sha(archive)}  {self.archive.name}\n'.encode())

    @staticmethod
    def tar(members, format=tarfile.USTAR_FORMAT):
        stream = io.BytesIO()
        with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0, filename='') as gz:
            with tarfile.open(fileobj=gz, mode='w', format=format) as tar:
                for info, data in members:
                    tar.addfile(info, io.BytesIO(data) if info.isfile() else None)
        return stream.getvalue()

    def changed(self, path, **fields):
        """The package's members with one member's header fields or bytes replaced."""
        result = []
        for member, data in self.members:
            if member.name == path:
                member, data = tarfile.TarInfo(path), fields.pop('data', data)
                member.mode, member.size = fields.pop('mode', 0o700 if path == 'openwiz' else 0o600), len(data)
                for key, value in fields.items():
                    setattr(member, key, value)
            result.append((member, data))
        return result

    def test_package_archive_members_must_be_exactly_the_expected_assets(self):
        original = {path.name: path.read_bytes() for path in self.packages.iterdir()}
        # The control: the same members repacked, with refreshed digests, still bind.
        self.repack(self.tar(self.members))
        result, output = self.artifacts()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(output.read_bytes())['artifacts']), 4)
        program = next(data for member, data in self.members if member.name == 'openwiz')
        same_size = bytes([program[0] ^ 1]) + program[1:]
        link = tarfile.TarInfo('web/index.html')
        link.type, link.linkname = tarfile.SYMTYPE, 'openwiz'
        folder = tarfile.TarInfo('web/index.html')
        folder.type, folder.mode = tarfile.DIRTYPE, 0o700
        extra = tarfile.TarInfo('runtime/extra.py')
        extra.mode, extra.size = 0o600, 6
        escape = tarfile.TarInfo('../openwiz')
        escape.mode, escape.size = 0o700, len(program)
        others = [(m, d) for m, d in self.members if m.name != 'web/index.html']
        cases = {
            'not a gzip tar archive': b'synthetic bytes that are not a gzip tar archive\n',
            'changed program payload of the same size': self.tar(self.changed('openwiz', data=same_size)),
            'changed member size': self.tar(self.changed('openwiz', data=program + b'!')),
            'changed member mode': self.tar(self.changed('openwiz', mode=0o755)),
            'missing member': self.tar(others),
            'extra member': self.tar(self.members + [(extra, b'extra\n')]),
            'duplicate member': self.tar(self.members + self.members[:1]),
            'symlink member': self.tar(others + [(link, b'')]),
            'directory member': self.tar(others + [(folder, b'')]),
            'unsafe member path': self.tar([(m, d) for m, d in self.members if m.name != 'openwiz']
                                           + [(escape, program)]),
            'pax header member': self.tar(self.changed('openwiz', pax_headers={'comment': 'synthetic'}),
                                          format=tarfile.PAX_FORMAT),
            'truncated archive': self.tar(self.members)[:-40],
        }
        for case, archive in cases.items():
            with self.subTest(case=case):
                self.repack(archive)
                result, output = self.artifacts()
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(result.stderr, 'product-identity: refused unidentified or mismatched products\n')
                self.assertFalse(output.exists())
                for name, data in original.items():
                    (self.packages / name).write_bytes(data)


if __name__ == '__main__':
    unittest.main()
