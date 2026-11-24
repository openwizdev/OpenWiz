#!/usr/bin/env python3
"""#2217 (RL4-R) and #1148 (RL4): packaged product identity, through the collector.

Each case builds a synthetic Git repository, runs the real collector against a
requested source commit and observes only its exit status and its products.
A stale or mismatched tracked runtime (#2217), or a compiled program without
this build's own identity (#1148), must refuse and leave no products; the
exact matching products are accepted and stamped.
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
    'tools/install/access/access.py': b'# Synthetic access tool.\n',
    'tools/github-app/setup.py': b'# Synthetic App setup.\n',
    'tools/github-app/app.py': b'# Synthetic App.\n',
    'tools/github-app/manifest.json': b'{"name":"Synthetic App"}\n',
}
PACKAGED = {'tools/install/install.py': 'runtime/install.py', 'tools/install/pull.py': 'runtime/pull.py',
            'tools/install/setup/setup.py': 'runtime/setup/setup.py',
            'tools/install/setup/store.py': 'runtime/setup/store.py',
            'tools/install/access/access.py': 'runtime/access/access.py',
            'tools/github-app/setup.py': 'runtime/github-app/setup.py',
            'tools/github-app/app.py': 'runtime/github-app/app.py',
            'tools/github-app/manifest.json': 'runtime/github-app/manifest.json'}


# #1148: contracts/release-candidate.v1.md, "Minimum product identity (RL4)".
RECORD = b'OPENWIZ_PRODUCT_V1:'
PROGRAMS = {'cli': 'openwiz'}
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu', 'aarch64-unknown-linux-gnu')


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
        machine = 183 if target.startswith('aarch64') else 62
        struct.pack_into('<HHIQQQIHHHHHH', header, 16, 2, machine, 1, 0, 64, 0, 0, 64, 56, 1, 0, 0, 0)
        segment = struct.pack('<IIQQQQQQ', 1, 5, 0, 0, 0, size, size, 0x1000)
    else:
        size = 32 + 72 + len(body)
        cpu = 0x100000c if target.startswith('aarch64') else 0x1000007
        header = struct.pack('<IiiIIIII', 0xfeedfacf, cpu, 0, 2, 1, 72, 0, 0)
        segment = struct.pack('<II16sQQQQiiII', 0x19, 72, b'__TEXT', 0, size, 0, size, 5, 5, 0, 0)
    return bytes(header) + segment + body + appended


def build(binaries, source, target, work, version=VERSION):
    """What one native build job leaves: the program compiled with this
    identity and the job's receipt (here written as that job would, since
    synthetic programs cannot run)."""
    for product, name in PROGRAMS.items():
        (binaries / name).write_bytes(program(target, identity(product, source, target, version)))
    programs = [{'product': product, 'program': name, 'sha256': sha((binaries / name).read_bytes()),
                 'bytes': len((binaries / name).read_bytes()), 'identity': identity(product, source, target, version)}
                for product, name in sorted(PROGRAMS.items())]
    receipts = {'program': work / 'program-receipt.json'}
    receipts['program'].write_bytes(canonical({'schema': 'openwiz.build-receipt.v1', 'method': 'native-query',
                                               'target': target, 'programs': programs}))
    return receipts


def collector(root, binaries, output, source, target, receipts, version=VERSION):
    return [sys.executable, '-I', str(COLLECTOR), '--root', str(root), '--binaries', str(binaries),
            '--output', str(output), '--version', version, '--source', source,
            '--target', target, '--identity', str(output) + '.json', '--record', str(output) + '.record.json',
            '--program-receipt', str(receipts['program'])]


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
        self.binaries = self.work / 'bin'
        self.binaries.mkdir()
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
        receipts = receipts or build(self.binaries, source, TARGET, self.work)
        self.runs += 1
        output = self.work / f'products-{self.runs}'
        result = subprocess.run(collector(self.repo, self.binaries, output, source, TARGET, receipts),
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
        (self.repo / 'tools/install/access/access.py').write_bytes(b'# Synthetic access tool, revised.\n')
        self.commit('revise synthetic access tool')
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



class LockedSkillsProvenance(Repository):
    """#555: after the cut the source tracks `skills` as a link to the
    gitignored `.wizskills/skills`, and `wizskills.lock` pins the WizSkills
    release. The collector packages the installed skills only when that
    install is exactly the lock's release tree."""

    SKILLS = {'skills/synthetic/SKILL.md': b'Synthetic installed skill.\n',
              'skills/synthetic/scripts/run.sh': b'#!/bin/sh\necho installed\n'}

    def setUp(self):
        super().setUp()
        release = self.repo / '.wizskills'
        release.mkdir()
        for path, data in {**self.SKILLS, 'README.md': b'Synthetic WizSkills.\n'}.items():
            (release / path).parent.mkdir(parents=True, exist_ok=True)
            (release / path).write_bytes(data)
        run = lambda *a: subprocess.run([*GIT, '-C', str(release), *a], check=True,
                                        capture_output=True).stdout.decode().strip()
        run('init', '-q')
        run('add', '-A')
        run('commit', '-q', '-m', 'synthetic release')
        lock = {'version': '0.1.2', 'commit': run('rev-parse', 'HEAD'), 'tree': run('rev-parse', 'HEAD^{tree}')}
        self.git('rm', '-rq', 'skills')
        os.symlink('.wizskills/skills', self.repo / 'skills')
        (self.repo / '.gitignore').write_bytes(b'/.wizskills/\n')
        (self.repo / 'wizskills.lock').write_text(json.dumps(lock, indent=2) + '\n')
        self.source = self.commit('skills come from the pinned WizSkills install')

    def accepted(self):
        result, output, _ = self.collect(self.source)
        self.assertEqual(result.returncode, 0, result.stderr)
        for path, data in self.SKILLS.items():
            self.assertEqual((output / 'runtime' / path).read_bytes(), data, path)

    def test_the_pinned_install_is_packaged(self):
        self.accepted()

    # catches: a release packaging locally edited skills instead of the pinned release.
    def test_a_tampered_install_is_refused(self):
        self.accepted()
        (self.repo / '.wizskills/skills/synthetic/SKILL.md').write_bytes(b'Edited after install.\n')
        self.refused(self.source)

    # catches: a release built with no skills, or from a stale tracked copy, when the install is absent.
    def test_a_missing_install_is_refused(self):
        self.accepted()
        subprocess.run(['rm', '-rf', str(self.repo / '.wizskills')], check=True)
        self.refused(self.source)


def _wizskills_fixture():
    """tools/wizskills/test_install.py's fake tagged WizSkills remote, loaded
    under its own name (tools/install has a test_install.py too)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('wizskills_test_install', ROOT / 'tools/wizskills/test_install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CandidateSourceInstall(_wizskills_fixture().Fixture):
    """#555: the release candidate verifies a bare clone, which has no install
    and no working tree; it installs the release the source's own lock pins."""

    def test_a_bare_source_verifies_against_the_release_its_lock_pins(self):
        # catches: every post-cut release candidate refused, because its bare
        # clone has no .wizskills, or verified against some other install.
        sys.path.insert(0, str(ROOT / 'tools/release'))
        import product_identity as rl4
        pin = self.release('0.1.2')
        source = self.tmp / 'source'
        (source / 'contracts').mkdir(parents=True)
        (source / 'contracts/wizskills.v1.md').write_bytes((ROOT / 'contracts/wizskills.v1.md').read_bytes())
        (source / 'wizskills.lock').write_text(json.dumps(pin) + '\n')
        os.symlink('.wizskills/skills', source / 'skills')
        run = lambda *a: subprocess.run([*GIT, '-C', str(source), *a], check=True,
                                        capture_output=True).stdout.decode().strip()
        run('init', '-q')
        run('add', '-A')
        run('commit', '-q', '-m', 'synthetic cut source')
        commit = run('rev-parse', 'HEAD')
        bare = self.tmp / 'bare.git'
        subprocess.run(['git', 'clone', '-q', '--bare', str(source), str(bare)], check=True)
        scratch = self.tmp / 'scratch'
        scratch.mkdir()
        saved = dict(os.environ)
        os.environ.update(self.env)
        try:
            install = rl4.install_locked(bare, commit, scratch)
        finally:
            os.environ.clear()
            os.environ.update(saved)
        skills_and_contracts = {path: (install / path).read_bytes() for path in
                                ['skills/alpha/SKILL.md', 'skills/alpha/scripts/run.sh',
                                 *(p.relative_to(install).as_posix() for p in (install / 'contracts').iterdir())]}
        rl4.verify_runtime(bare, commit, skills_and_contracts, install)
        for changed in ({**skills_and_contracts, 'skills/alpha/SKILL.md': b'Edited.\n'},
                        {**skills_and_contracts, 'contracts/cli.v1.md': b'Edited.\n'},
                        {p: d for p, d in skills_and_contracts.items() if p != 'contracts/cli.v1.md'}):
            with self.assertRaises(rl4.Refused):
                rl4.verify_runtime(bare, commit, changed, install)


class CompiledProductIdentity(Repository):
    """#1148: the compiled CLI's identity. The runtime always matches here,
    so each refusal is the compiled product's."""

    def prepared(self, target=TARGET, source=None):
        return build(self.binaries, source or self.source, target, self.work)

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

    def refused_with(self, receipts, target=TARGET):
        self.runs += 1
        output = self.work / f'products-{self.runs}'
        result = subprocess.run(collector(self.repo, self.binaries, output, self.source, target, receipts),
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
                'other product': [identity('runtime', self.source, TARGET)],
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
                receipts = build(self.binaries, self.source, TARGET, self.work, version)
                self.runs += 1
                output = self.work / f'products-{self.runs}'
                result = subprocess.run(collector(self.repo, self.binaries, output, self.source, TARGET,
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
            'rebuilt after the query': lambda r: self.rebuilt('openwiz'),
            'receipt claims another identity': lambda r: self.requery(
                r, claimed={'cli': identity('cli', '1' * 40, TARGET)}),
            'receipt for another target': lambda r: r['program'].write_bytes(
                r['program'].read_bytes().replace(b'"target":"x86_64-unknown-linux-gnu"}', b'"target":"x86_64-apple-darwin"}')),
            'receipt from another method': lambda r: r['program'].write_bytes(
                r['program'].read_bytes().replace(b'native-query', b'embedded-record')),
            'receipt without a program': lambda r: r['program'].write_bytes(canonical(dict(
                json.loads(r['program'].read_bytes()), programs=[]))),
            'no receipt': lambda r: r['program'].unlink(),
            'malformed receipt': lambda r: r['program'].write_bytes(b'[]'),
        }
        for case, change in cases.items():
            with self.subTest(case=case):
                receipts = self.prepared()
                change(receipts)
                self.refused_with(receipts)

    def test_every_target_accepts_its_complete_matching_products_without_running_them(self):
        for target in TARGETS:
            with self.subTest(target=target):
                receipts = self.prepared(target)
                self.runs += 1
                output = self.work / f'products-{self.runs}'
                result = subprocess.run(collector(self.repo, self.binaries, output, self.source, target,
                                                  receipts), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                record = json.loads(Path(str(output) + '.record.json').read_bytes())
                self.assertEqual(record['schema'], 'openwiz.product-record.v1')
                products = record['products']
                self.assertEqual([row['identity'] for row in products],
                                 [identity(p, self.source, target) for p in ('cli', 'runtime')])
                rows = {row['identity']['product']: row for row in products}
                for product, name in PROGRAMS.items():
                    self.assertEqual(rows[product]['payload_sha256'], sha((self.binaries / name).read_bytes()))
                    self.assertEqual(rows[product]['verification'], 'embedded-record')
                    self.assertEqual(rows[product]['build_receipt'],
                                     {'record': 'program-receipt.json', 'sha256': sha(receipts['program'].read_bytes())})
                # #2539: the runtime payload is its complete final inventory,
                # including the package stamp the collector writes.
                stamp = f'openwiz.package.v1\n{VERSION}\n{self.source}\n{target}\n'.encode()
                stamps = {'runtime/': {'path': 'runtime/openwiz-build.txt', 'mode': '0600',
                                       'bytes': len(stamp), 'sha256': sha(stamp)}}
                assets = json.loads(Path(str(output) + '.json').read_bytes())['assets']
                final = [row for row in assets if row['path'].startswith('runtime/')]
                self.assertIn(stamps['runtime/'], final)
                self.assertEqual(rows['runtime']['payload_sha256'],
                                 sha(canonical(sorted(final, key=lambda row: row['path']))))
                self.assertFalse([row for row in assets if row['path'].startswith('web/')])
                runtime = [{'path': PACKAGED.get(path, 'runtime/' + path),
                            'mode': '0700' if path.endswith('.sh') else '0600',
                            'bytes': len(data), 'sha256': sha(data)} for path, data in RUNTIME.items()]
                runtime.append(stamps['runtime/'])
                self.assertEqual(rows['runtime']['payload_sha256'],
                                 sha(canonical(sorted(runtime, key=lambda row: row['path']))))
                self.assertEqual(rows['runtime']['verification'], 'tracked-tree')


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
            if name == 'runtime/openwiz-build.txt':
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
        link = tarfile.TarInfo('runtime/install.py')
        link.type, link.linkname = tarfile.SYMTYPE, 'openwiz'
        folder = tarfile.TarInfo('runtime/install.py')
        folder.type, folder.mode = tarfile.DIRTYPE, 0o700
        extra = tarfile.TarInfo('runtime/extra.py')
        extra.mode, extra.size = 0o600, 6
        escape = tarfile.TarInfo('../openwiz')
        escape.mode, escape.size = 0o700, len(program)
        others = [(m, d) for m, d in self.members if m.name != 'runtime/install.py']
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
