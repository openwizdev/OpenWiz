#!/usr/bin/env python3
"""Bundle assembly from reviewed, hash-bound synthetic build products."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/install'))
from test_install import REQUIRED, SETUP_TOOLS, TARGETS
sys.path.insert(0, str(ROOT / 'tools/release'))
# #1148: synthetic programs compiled with an identity, and their build receipts.
from test_product_identity import PROGRAMS, build, collector, identity, program

# #1105 R9: each setup tool's source in the repository, by its runtime path.
SETUP_SOURCES = {'runtime/setup/setup.py': 'tools/install/setup/setup.py',
                 'runtime/setup/store.py': 'tools/install/setup/store.py',
                 'runtime/setup/github_login.py': 'tools/install/setup/github_login.py',  # #633
                 'runtime/github-app/setup.py': 'tools/github-app/setup.py',
                 'runtime/github-app/app.py': 'tools/github-app/app.py',
                 'runtime/github-app/manifest.json': 'tools/github-app/manifest.json',
                 'runtime/setup/init.py': 'tools/install/setup/init.py'}  # #635


class Package(unittest.TestCase):
    def test_installed_platform_and_private_key_contracts(self):
        # Rust runs before Python is provisioned on the PC runner. Register the
        # platform proof in this existing Python stage, using its exact tool.
        for name in ('test_security.py',):
            with self.subTest(proof=name):
                result = subprocess.run([sys.executable,'-I',
                    str(ROOT/'tools/install/platform'/name)], capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_compiled_programs_answer_their_identity_query_without_effects(self):
        # #1148: the real debug CLI.
        target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target'))
        target = target if target.is_absolute() else ROOT / target
        import product_identity
        host = subprocess.run(['rustc', '-vV'], capture_output=True, text=True, check=True).stdout
        host = next(line[6:] for line in host.splitlines() if line.startswith('host: '))
        version = next(line.split('"')[1] for line in (ROOT / 'Cargo.toml').read_text().splitlines()
                       if line.startswith('version = '))
        source = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        for product in ('cli',):
            path = target / 'debug' / PROGRAMS[product]
            with self.subTest(program=path.name), tempfile.TemporaryDirectory(prefix='openwiz-query-') as temporary:
                self.assertTrue(path.is_file(), 'Build the CLI before the identity query proof.')
                record, _ = product_identity.native_query(path)
                self.assertEqual(record, identity(product, source, host, version))
                result, left = query_with_spy(path, Path(temporary))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), record)
                self.assertEqual(left, ['bin', 'room-cli'])

    def test_identity_query_spy_records_a_call_whose_failure_is_ignored(self):
        # #2540: a query that calls room-cli and ignores its exit status must still leave the spy's marker.
        with tempfile.TemporaryDirectory(prefix='openwiz-query-') as temporary:
            work = Path(temporary)
            query = work / 'query'
            query.write_text('#!/bin/sh\nroom-cli\necho \'{}\'\n')
            query.chmod(0o700)
            (work / 'spied').mkdir()
            result, left = query_with_spy(query, work / 'spied')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(left, ['bin', 'room-cli', 'room-cli.called'])

    def test_native_product_collector_checks_the_executable_architecture(self):
        with tempfile.TemporaryDirectory(prefix='openwiz-native-products-') as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            for name in REQUIRED:
                if name.startswith('runtime/skills/'):
                    path = root / name.removeprefix('runtime/')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('Synthetic required skill resource.')
            scripts = root / 'tools/install'
            scripts.mkdir(parents=True)
            for name in ('install.py', 'pull.py'):
                (scripts / name).write_text('Synthetic runtime resource.')
            (scripts / 'access').mkdir()
            (scripts / 'access/access.py').write_bytes(b'Synthetic access verifier.\n')
            (scripts / 'cloudroom').mkdir()  # #2201
            (scripts / 'cloudroom/cloudroom.py').write_bytes(b'Synthetic CloudRoom setup tool.\n')
            self.assertEqual(sorted(SETUP_SOURCES), sorted(SETUP_TOOLS))
            for name, source in SETUP_SOURCES.items():
                (root / source).parent.mkdir(parents=True, exist_ok=True)
                (root / source).write_bytes(f'Synthetic setup tool {name}.\n'.encode())
            for args in (['init', '-q'], ['add', 'skills', 'tools'],
                         ['-c', 'user.name=Synthetic Builder', '-c', 'user.email=builder@example.invalid',
                          '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'Synthetic runtime fixture']):
                subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
            source = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
            for target in TARGETS:
                (root / 'job').mkdir(exist_ok=True)
                receipts = build(binaries, source, target, root / 'job')
                header = (binaries / 'openwiz').read_bytes()
                output = root / (target + '-products')
                identity_file = Path(str(output) + '.json')
                args = collector(root, binaries, output, source, target, receipts)
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                assets = {row['path']:row for row in json.loads(identity_file.read_bytes())['assets']}
                # #874: the engine, handover and activation runtimes are retired;
                # the build neither needs nor ships them.
                self.assertEqual([p for p in assets if p.startswith(('runtime/engine/', 'runtime/handover/',
                                  'runtime/pc_activation/', 'runtime/completion/'))], [])
                self.assertEqual((output/'runtime/cloudroom/cloudroom.py').read_bytes(), b'Synthetic CloudRoom setup tool.\n')
                self.assertEqual(assets['runtime/cloudroom/cloudroom.py']['mode'], '0600')
                self.assertNotIn('runtime/platform/runtime.py', assets)
                verifier = assets['runtime/access/access.py']
                self.assertEqual(verifier['mode'], '0600')
                self.assertEqual(verifier['bytes'], len(b'Synthetic access verifier.\n'))
                self.assertEqual(verifier['sha256'], hashlib.sha256(b'Synthetic access verifier.\n').hexdigest())
                self.assertEqual((output/'runtime/access/access.py').read_bytes(), b'Synthetic access verifier.\n')
                access = scripts/'access/access.py'
                access.unlink()
                missing = elsewhere(args, str(output) + '-missing-access')
                result = subprocess.run(missing, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(str(output) + '-missing-access').exists())
                access.symlink_to(scripts/'pull.py')
                linked = elsewhere(args, str(output) + '-linked-access')
                result = subprocess.run(linked, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(str(output) + '-linked-access').exists())
                access.unlink()
                access.write_bytes(b'Synthetic access verifier.\n')
                for name in SETUP_TOOLS:
                    data = f'Synthetic setup tool {name}.\n'.encode()
                    self.assertEqual(assets[name]['mode'], '0600', name)
                    self.assertEqual(assets[name]['sha256'], hashlib.sha256(data).hexdigest(), name)
                    self.assertEqual((output / name).read_bytes(), data, name)
                bundle = root / (target + '-bundle')
                result = subprocess.run([sys.executable, str(ROOT / 'tools/release/package.py'),
                    '--products', str(output), '--identity', str(identity_file), '--output', str(bundle)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.bound_and_installed(root, target, identity_file, bundle)
                (binaries / 'openwiz').write_bytes(b'wrong architecture')
                bad = elsewhere(args, str(output) + '-bad')
                result = subprocess.run(bad, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(str(output) + '-bad').exists())
                (binaries/'openwiz').write_bytes(header)

    def bound_and_installed(self, root, target, identity_file, bundle):
        """#1148: the collected, packaged target's candidate artifact rows bind
        each package file's digest, and the bundle installs."""
        rows = root / (target + '-artifacts.json')
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/release/product_identity.py'), 'artifacts',
            '--identity', str(identity_file), '--packages', str(bundle), '--output', str(rows)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        roles = {f'openwiz-0.0.99-{target}.tar.gz': 'archive', f'openwiz-0.0.99-{target}.manifest.json': 'manifest',
                 f'openwiz-{target}.manifest.json': 'manifest_alias', f'openwiz-{target}.sha256': 'manifest_checksum'}
        self.assertEqual(json.loads(rows.read_bytes()), {'schema': 'openwiz.candidate-artifacts.v1', 'artifacts': [
            {'name': name, 'role': role, 'target': target, 'bytes': (bundle / name).stat().st_size,
             'sha256': hashlib.sha256((bundle / name).read_bytes()).hexdigest()} for name, role in sorted(roles.items())]})
        manifest = bundle / f'openwiz-0.0.99-{target}.manifest.json'
        installed = subprocess.run([sys.executable, str(ROOT / 'tools/install/install.py'),
            '--root', str(root / (target + '-installed')), '--manifest', str(manifest),
            '--archive', str(bundle / f'openwiz-0.0.99-{target}.tar.gz'),
            '--manifest-sha256', hashlib.sha256(manifest.read_bytes()).hexdigest(), '--target', target],
            capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual((root / (target + '-installed/current/runtime/openwiz-build.txt')).read_bytes(),
                         (bundle.parent / (target + '-products/runtime/openwiz-build.txt')).read_bytes())
        alias = bundle / f'openwiz-{target}.manifest.json'
        for name, data in ((alias.name, alias.read_bytes() + b' '), ('SHA256SUMS', b'')):
            with self.subTest(target=target, changed=name):
                original = (bundle / name).read_bytes()
                (bundle / name).write_bytes(data)
                refused = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/release/product_identity.py'), 'artifacts',
                    '--identity', str(identity_file), '--packages', str(bundle), '--output', str(rows) + '-' + name],
                    capture_output=True, text=True)
                self.assertEqual(refused.returncode, 1)
                self.assertFalse(Path(str(rows) + '-' + name).exists())
                (bundle / name).write_bytes(original)

    def test_all_targets_assemble_then_install_complete_matching_products(self):
        with tempfile.TemporaryDirectory(prefix='openwiz-package-') as temporary:
            root = Path(temporary)
            for target in TARGETS:
                payload = root / target
                payload.mkdir()
                rows = []
                for name in REQUIRED:
                    data = (target + '\n0.0.99\n' + '1' * 40 + '\n' + name).encode()
                    if name == 'runtime/openwiz-build.txt':
                        data = ('openwiz.package.v1\n0.0.99\n' + '1' * 40 + '\n' + target + '\n').encode()
                    path = payload / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    mode = '0700' if name == 'openwiz' or name.endswith('.sh') else '0600'
                    rows.append({'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data), 'mode': mode})
                identity = {'schema': 'openwiz.build-products.v1', 'version': '0.0.99',
                            'source': '1' * 40, 'target': target, 'assets': rows}
                provenance = root / (target + '.json')
                provenance.write_text(json.dumps(identity))
                out = root / (target + '-out')
                cmd = [sys.executable, str(ROOT / 'tools/release/package.py'), '--products', str(payload),
                       '--identity', str(provenance), '--output', str(out)]
                result = subprocess.run(cmd, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                manifest = out / f'openwiz-0.0.99-{target}.manifest.json'
                archive = out / f'openwiz-0.0.99-{target}.tar.gz'
                data = json.loads(manifest.read_bytes())
                self.assertEqual(data['source'], '1' * 40)
                self.assertEqual(data['target'], target)
                self.assertEqual(data['assets'], sorted(rows, key=lambda row: row['path']))
                installed = subprocess.run([sys.executable, str(ROOT / 'tools/install/install.py'),
                    '--root', str(root / (target + '-installed')), '--manifest', str(manifest),
                    '--archive', str(archive), '--manifest-sha256', hashlib.sha256(manifest.read_bytes()).hexdigest(),
                    '--target', target], capture_output=True, text=True)
                self.assertEqual(installed.returncode, 0, installed.stderr)
                selected = root / (target + '-installed/current/runtime/install.py')
                self.assertEqual(selected.read_bytes(),(payload/'runtime/install.py').read_bytes())
                (payload / 'runtime/install.py').write_text('synthetic mismatched runtime')
                result = subprocess.run(cmd[:-1] + [str(out) + '-bad'], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(str(out) + '-bad').exists())


def query_with_spy(program, work):
    """Runs the identity query with a spy room-cli on PATH, and a home and state directory it must leave alone."""
    (work / 'bin').mkdir()
    spy = work / 'bin/room-cli'
    spy.write_text('#!/bin/sh\n: > "$0.called"\n')
    spy.chmod(0o700)
    result = subprocess.run([str(program), '--build-identity'], cwd=work, capture_output=True, timeout=30,
        env={'PATH': str(work / 'bin'), 'HOME': str(work / 'home'), 'OPENWIZ_STATE_DIR': str(work / 'state')})
    return result, sorted(p.name for p in work.rglob('*'))


def elsewhere(args, output):
    """The same collector call with new outputs."""
    args = args.copy()
    args[args.index('--output') + 1] = output
    args[args.index('--identity') + 1] = output + '.json'
    args[args.index('--record') + 1] = output + '.record.json'
    return args


if __name__ == '__main__':
    unittest.main()
