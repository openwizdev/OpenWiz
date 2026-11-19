#!/usr/bin/env python3
"""Bundle assembly from reviewed, hash-bound synthetic build products."""
import hashlib
import json
import os
import socket
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

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
    def test_packaged_service_start_gate(self):
        # catches: a verified install cannot serve its packaged web page without activation.
        target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target'))
        if not target.is_absolute():
            target = ROOT / target
        service = target / 'debug/openwiz-service'
        self.assertTrue(service.is_file(), 'Build the service before the packaged start-gate proof.')
        build_id = subprocess.check_output([service, '--update-build'], text=True).strip()
        import fixture_bundle

        with tempfile.TemporaryDirectory(prefix='ow-gate-') as temporary:
            root = Path(temporary)
            home, web = root / 'home', root / 'web'
            web.mkdir()
            page = b'Synthetic page, no accounts.'
            (web / 'index.html').write_bytes(page)
            # catches (#1274): a packaged web root carrying its product record stops the service at start.
            record = b'{"schema":"synthetic.product","version":"0.0.99"}\n'
            (web / 'openwiz-product.json').write_bytes(record)
            # Only the installed service can serve the page.
            inert_server = root / 'inert-server'
            inert_server.write_bytes(b'#!/bin/sh\nexit 1\n')
            bundle = fixture_bundle.create(root / 'bundle', inert_server, web, service=service,
                                           source=build_id)

            for layout, installed in (
                ('default', root / 'installed'),
                ('standard', home / '.local/lib/openwiz'),
                ('split', root / 'split-install'),
            ):
                with self.subTest(layout=layout):
                    installed.parent.mkdir(parents=True, exist_ok=True)
                    args = [sys.executable, '-I', str(ROOT / 'tools/install/install.py'),
                            '--manifest', bundle['manifest'], '--manifest-sha256', bundle['checksum'],
                            '--archive', bundle['archive'], '--target', 'x86_64-unknown-linux-gnu',
                            '--root', str(installed)]
                    if layout != 'default':
                        args += ['--state-root', str(root / (layout + '-state'))]
                    result = subprocess.run(args, capture_output=True, text=True, check=True)
                    state = Path(json.loads(result.stdout)['state_root'])
                    selected = installed / 'current'
                    program = selected / 'openwiz-service'
                    env = {'HOME': str(home), 'PATH': '/synthetic/no-build-tools',
                           'OPENWIZ_STATE_DIR': str(state)}

                    def refuse(executable, reason):
                        denied = subprocess.run([executable], env=env, cwd=root,
                                                capture_output=True, text=True, timeout=60)
                        self.assertEqual(denied.returncode, 1, denied.stderr)
                        self.assertIn(reason, denied.stderr)

                    if layout == 'split':
                        # catches: startup accepts an install root it cannot verify.
                        refuse(program, 'cannot identify the private install root')
                        continue

                    # The offline config writer documented for PC setup is install(1).
                    # Stage the example input with just the test's loopback port changed.
                    with socket.socket() as listener:
                        listener.bind(('127.0.0.1', 0))
                        port = listener.getsockname()[1]
                    example = json.loads((ROOT / 'deploy/pc/config.example.json').read_bytes())
                    example['server']['port'] = port
                    setup_input = root / 'config.example.json'
                    setup_input.write_text(json.dumps(example))
                    subprocess.run(['install', '-m', '600', setup_input, state / 'service/config.json'],
                                   check=True)
                    if layout == 'default':
                        # Let main reach its activation-record check on the red run.
                        (state / 'setup').mkdir(mode=0o700)
                    self.assertFalse((state / 'setup/pc-activation.json').exists())
                    with self.subTest(case='installed HTTP and login'):
                        with tempfile.TemporaryFile(mode='w+b') as stderr:
                            with subprocess.Popen([program], env=env, cwd=root, stderr=stderr) as child:
                                try:
                                    deadline = time.monotonic() + 60
                                    while child.poll() is None and time.monotonic() < deadline:
                                        if (state / 'service/status.sock').exists():
                                            status = subprocess.run([program, 'status', '--json'], env=env,
                                                                    cwd=root, capture_output=True, timeout=3)
                                            if status.returncode == 0:
                                                self.assertEqual(json.loads(status.stdout)['server']['port'], port)
                                                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                                                with opener.open(f'http://127.0.0.1:{port}/', timeout=3) as response:
                                                    self.assertEqual(response.read(), page)
                                                with self.assertRaises(urllib.error.HTTPError) as missing:
                                                    opener.open(f'http://127.0.0.1:{port}/openwiz-product.json', timeout=3)
                                                self.assertEqual(missing.exception.code, 404)
                                                self.assertEqual((selected / 'web/openwiz-product.json').read_bytes(), record)
                                                break
                                        time.sleep(0.05)
                                    else:
                                        stderr.seek(0)
                                        self.fail(stderr.read().decode() or 'Installed service never answered status.')
                                finally:
                                    if child.poll() is None:
                                        child.kill()
                                    child.wait()
                            stderr.seek(0)
                            self.assertIn(b'login: unknown', stderr.read())
                        self.assertFalse((state / 'setup/pc-activation.json').exists())

                    if layout != 'default':
                        continue
                    with self.subTest(case='missing manifest'):
                        # catches: a missing manifest is treated as a source deployment.
                        manifest = selected / 'install-manifest.json'
                        saved = manifest.read_bytes()
                        manifest.unlink()
                        try:
                            refuse(program, 'the installed manifest is unreadable')
                        finally:
                            manifest.write_bytes(saved)
                            manifest.chmod(0o600)

                    for directory, reason in (
                        (state, "the runtime state is not this installation's private state"),
                        (state / 'setup', "the runtime state is not this installation's private state"),
                        (state / 'service/builds', "the runtime state is not this installation's private state"),
                        (installed, 'cannot identify the private install root'),
                    ):
                        with self.subTest(case='non-private directory', directory=directory.name):
                            # catches: startup accepts group access to private paths.
                            directory.chmod(0o750)
                            try:
                                refuse(program, reason)
                            finally:
                                directory.chmod(0o700)
                    build = selected.resolve()
                    with self.subTest(case='different selection'):
                        # catches: a verified build no longer selected by its install root starts.
                        selected.unlink()
                        selected.symlink_to(root / 'a-different-build')
                        try:
                            refuse(build / 'openwiz-service', 'cannot identify the private install root')
                        finally:
                            selected.unlink()
                            selected.symlink_to(build)
                    with self.subTest(case='package outside state'):
                        # catches: a relocated package is accepted outside its private state.
                        moved = root / 'outside-package'
                        build.rename(moved)
                        try:
                            refuse(moved / 'openwiz-service', 'the build is outside an installed state root')
                        finally:
                            moved.rename(build)
                    with self.subTest(case='unlisted running executable'):
                        # catches: a running executable absent from the package is accepted.
                        foreign = selected / 'foreign-service'
                        program.rename(foreign)
                        try:
                            refuse(foreign, 'the running executable does not belong to the installed package')
                        finally:
                            foreign.rename(program)
                    with self.subTest(case='tampered asset'):
                        # catches: the service starts with a mismatched asset hash.
                        asset = selected / 'web/index.html'
                        asset.write_bytes(b's' + page[1:])
                        refuse(program, 'an installed asset differs from the verified manifest')

    def test_installed_platform_and_private_key_contracts(self):
        # Rust runs before Python is provisioned on the PC runner. Register the
        # platform proofs in this existing Python stage, using its exact tool.
        for name in ('test_runtime.py','test_security.py'):
            with self.subTest(proof=name):
                result = subprocess.run([sys.executable,'-I',
                    str(ROOT/'tools/install/platform'/name)], capture_output=True,text=True)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_compiled_programs_answer_their_identity_query_without_effects(self):
        # #1148: the real debug programs the packaged start-gate proof uses.
        target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target'))
        target = target if target.is_absolute() else ROOT / target
        import product_identity
        host = subprocess.run(['rustc', '-vV'], capture_output=True, text=True, check=True).stdout
        host = next(line[6:] for line in host.splitlines() if line.startswith('host: '))
        version = next(line.split('"')[1] for line in (ROOT / 'Cargo.toml').read_text().splitlines()
                       if line.startswith('version = '))
        source = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        for product in ('cli', 'service'):
            path = target / 'debug' / PROGRAMS[product]
            with self.subTest(program=path.name), tempfile.TemporaryDirectory(prefix='openwiz-query-') as temporary:
                self.assertTrue(path.is_file(), 'Build the CLI and service before the identity query proof.')
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

    def test_native_product_collector_checks_all_three_executable_architectures(self):
        with tempfile.TemporaryDirectory(prefix='openwiz-native-products-') as temporary:
            root = Path(temporary)
            web, binaries = root / 'web', root / 'bin'
            web.mkdir()
            binaries.mkdir()
            for name in ('index.html', 'setup.html'):
                (web / name).write_text('Synthetic setup, no accounts.')
            for name in REQUIRED:
                if name.startswith('runtime/skills/'):
                    path = root / name.removeprefix('runtime/')
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('Synthetic required skill resource.')
            scripts = root / 'tools/install'
            scripts.mkdir(parents=True)
            for name in ('install.py', 'pull.py'):
                (scripts / name).write_text('Synthetic runtime resource.')
            (scripts / 'platform').mkdir()
            (scripts / 'platform/runtime.py').write_bytes(b'Synthetic local runtime manager.\n')
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
                receipts = build(binaries, web, source, target, root / 'job')
                header = (binaries / 'openwiz-server').read_bytes()
                output = root / (target + '-products')
                identity_file = Path(str(output) + '.json')
                args = collector(root, binaries, web, output, source, target, receipts)
                result = subprocess.run(args, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                assets = {row['path']:row for row in json.loads(identity_file.read_bytes())['assets']}
                # #874: the engine, handover and activation runtimes are retired;
                # the build neither needs nor ships them.
                self.assertEqual([p for p in assets if p.startswith(('runtime/engine/', 'runtime/handover/',
                                  'runtime/pc_activation/', 'runtime/completion/'))], [])
                self.assertEqual((output/'runtime/cloudroom/cloudroom.py').read_bytes(), b'Synthetic CloudRoom setup tool.\n')
                self.assertEqual(assets['runtime/cloudroom/cloudroom.py']['mode'], '0600')
                self.assertIn('runtime/platform/runtime.py',assets)
                resource = assets['runtime/platform/runtime.py']
                self.assertEqual(resource['mode'],'0600')
                self.assertEqual(resource['bytes'],len(b'Synthetic local runtime manager.\n'))
                self.assertEqual(resource['sha256'],hashlib.sha256(b'Synthetic local runtime manager.\n').hexdigest())
                self.assertEqual((output/'runtime/platform/runtime.py').read_bytes(),b'Synthetic local runtime manager.\n')
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
                (binaries / 'openwiz-server').write_bytes(b'wrong architecture')
                bad = elsewhere(args, str(output) + '-bad')
                result = subprocess.run(bad, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(Path(str(output) + '-bad').exists())
                (binaries/'openwiz-server').write_bytes(header)
                manager = scripts/'platform/runtime.py'
                manager.unlink()
                for suffix in ('missing-manager','linked-manager'):
                    if suffix == 'linked-manager':
                        manager.symlink_to(scripts/'install.py')
                    bad = elsewhere(args, str(output)+'-'+suffix)
                    refused = subprocess.run(bad,capture_output=True,text=True)
                    self.assertNotEqual(refused.returncode,0)
                    self.assertFalse(Path(str(output)+'-'+suffix).exists())
                manager.unlink()
                manager.write_bytes(b'Synthetic local runtime manager.\n')

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
        self.assertEqual((root / (target + '-installed/current/web/openwiz-product.json')).read_bytes(),
                         (bundle.parent / (target + '-products/web/openwiz-product.json')).read_bytes())
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
                for name in [*REQUIRED,'runtime/platform/runtime.py']:
                    data = (target + '\n0.0.99\n' + '1' * 40 + '\n' + name).encode()
                    if name in ('web/openwiz-build.txt', 'runtime/openwiz-build.txt'):
                        data = ('openwiz.package.v1\n0.0.99\n' + '1' * 40 + '\n' + target + '\n').encode()
                    path = payload / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                    mode = '0700' if name in ('openwiz', 'openwiz-service', 'openwiz-server') or name.endswith('.sh') else '0600'
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
                selected = root / (target + '-installed/current/runtime/platform/runtime.py')
                self.assertEqual(selected.read_bytes(),(payload/'runtime/platform/runtime.py').read_bytes())
                (payload / 'web/setup.html').write_text('synthetic mismatched web export')
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
