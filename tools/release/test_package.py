#!/usr/bin/env python3
"""Bundle assembly from reviewed, hash-bound synthetic build products."""
import hashlib
import json
import os
import shutil
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
            scripts = runtime_root(self, root)
            source = commit(root, 'skills', 'tools')
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

    def test_runtime_carries_exactly_the_selected_drivers_and_kit_where_the_caller_finds_them(self):
        # #1699: KN6's caller runs `$OPENWIZ_ADAPTERS/<host>/driver`; the archive must carry each
        # tracked launch driver's entry point and schema, and the kernel files the driver kit's
        # checks read, at their tracked paths under runtime/, and nothing else from those folders.
        # The boat driver is the repository's template driver, and the kit is the real kit, so the
        # installed kit's `version` check runs for real against the installed driver.
        kit = ('kernel/driver-kit/kit.py', 'kernel/driver-kit/schema.json', 'kernel/records-kit/check.py',
               'kernel/records.v1.md', 'kernel/driver-kit/hostkey.py', 'kernel/driver-kit/hosts.json')
        carried = {'adapters/devin/driver': (ROOT / 'adapters/devin/driver').read_bytes(),
                   'adapters/devin/schema.json': (ROOT / 'adapters/devin/schema.json').read_bytes(),
                   'adapters/devin/README.md': (ROOT / 'adapters/devin/README.md').read_bytes(),
                   'adapters/devin/fixtures/kit-host.json': (ROOT / 'adapters/devin/fixtures/kit-host.json').read_bytes(),
                   'adapters/boat/driver': (ROOT / 'adapters/template/driver').read_bytes(),
                   'adapters/boat/schema.json': (ROOT / 'adapters/template/schema.json').read_bytes(),
                   'adapters/cloudroom/driver': (ROOT / 'adapters/cloudroom/driver').read_bytes(),
                   'adapters/cloudroom/schema.json': (ROOT / 'adapters/cloudroom/schema.json').read_bytes(),
                   'adapters/local/driver': b'#!/usr/bin/env python3\nprint("synthetic local driver")\n',
                   'adapters/local/schema.json': b'{"synthetic": "local schema"}\n',
                   'adapters/made-up/driver': b'#!/usr/bin/env python3\nprint("synthetic new driver")\n',
                   'adapters/made-up/schema.json': b'{"synthetic": "new schema"}\n',
                   'adapters/made-up/fixtures/deep/host.json': b'{"synthetic": "extra file"}\n',
                   **{path: (ROOT / path).read_bytes() for path in kit}}
        left = ('adapters/boat/README.md', 'adapters/boat/test_driver.py', 'adapters/boat/fixtures/bin/boat',
                'adapters/boat/evidence/red.txt', 'adapters/template/driver', 'adapters/template/schema.json',
                'adapters/unlisted/driver', 'adapters/unlisted/schema.json', 'kernel/driver.v1.md',
                'kernel/driver-kit/README.md', 'kernel/driver-kit/test_kit.py',
                'kernel/driver-kit/fixtures/fake-harness', 'kernel/records-kit/test_check.py',
                'kernel/records/backfill.md')
        releases = {'adapters/boat/release.json': [], 'adapters/cloudroom/release.json': [],
                    'adapters/local/release.json': [],
                    'adapters/devin/release.json': ['README.md', 'fixtures/kit-host.json'],
                    'adapters/made-up/release.json': ['fixtures/deep/host.json'],
                    'adapters/boat/fixtures/release.json': []}
        with tempfile.TemporaryDirectory(prefix='openwiz-driver-products-') as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            runtime_root(self, root)
            listed = {path: json.dumps({'extra_files': extra}).encode() for path, extra in releases.items()}
            for path, data in [*carried.items(), *listed.items(),
                               *((path, b'synthetic, never carried\n') for path in left)]:
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(data)
            source = commit(root, 'skills', 'tools', 'kernel', *(p for p in [*carried, *listed, *left]
                                                                 if p.startswith('adapters/')))
            target = TARGETS[0]
            (root / 'job').mkdir()
            (root / 'tracker.json').write_text(json.dumps({'record_authors': ['synthetic-author'], 'comments': []}))
            receipts = build(binaries, source, target, root / 'job')
            output = root / 'products'
            result = subprocess.run(collector(root, binaries, output, source, target, receipts),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            assets = {row['path']: row for row in json.loads(Path(str(output) + '.json').read_bytes())['assets']}
            self.assertEqual(sorted(p for p in assets if p.startswith(('runtime/adapters/', 'runtime/kernel/'))),
                             sorted('runtime/' + path for path in carried))
            bundle = root / 'bundle'
            result = subprocess.run([sys.executable, str(ROOT / 'tools/release/package.py'), '--products', str(output),
                                     '--identity', str(output) + '.json', '--output', str(bundle)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.bound_and_installed(root, target, Path(str(output) + '.json'), bundle,
                                     products=output, home=root / 'installed')
            adapters = root / 'installed/current/runtime/adapters'
            for path, data in carried.items():
                self.assertEqual((adapters.parent / path).read_bytes(), data, path)
                # #1699: KN6's caller runs only an executable driver; every other file stays data.
                executable = path.endswith('/driver')
                self.assertEqual(assets['runtime/' + path]['mode'], '0700' if executable else '0600', path)
                self.assertEqual(os.access(adapters.parent / path, os.X_OK), executable, path)
            fixtures = adapters.parent / 'kernel/driver-kit/fixtures'
            fixtures.mkdir()
            shutil.copy2(ROOT / 'kernel/driver-kit/fixtures/fake-harness', fixtures)
            (fixtures / 'devin').symlink_to('fake-harness')
            fixture_path = os.pathsep.join((str(fixtures), os.environ['PATH']))
            # The installed kit's first check, `version`, passes against the installed driver.
            checked = subprocess.run([sys.executable, '-I', 'kernel/driver-kit/kit.py', '--driver', 'adapters/boat/driver',
                                      '--repo', 'synthetic/throwaway', '--ticket', '1', '--harness', 'fake-harness',
                                      '--model', 'synthetic', '--tracker', str(root / 'tracker.json'), '--wait', '1'],
                                     cwd=adapters.parent, capture_output=True, text=True, timeout=120,
                                     env={'PATH': fixture_path, 'OPENWIZ_TEMPLATE_LIVE': '1'})
            self.assertEqual(checked.stdout.splitlines()[:1],
                             ['pass version: openwiz:records v1, and the schema is driver v1'], checked.stderr)
            devin = subprocess.run([str(adapters / 'devin/driver'), 'start'], input=json.dumps(
                {'repository': 'synthetic/throwaway', 'ticket': 1, 'skill': 'build-ticket', 'harness': 'devin',
                 'model': 'default'}), capture_output=True, text=True, timeout=120, env={
                'PATH': os.environ['PATH'], 'HOME': str(root), 'DEVIN_ORG_ID': 'org-syn0001',
                'OPENWIZ_HOSTKEY_TEST_ORIGIN': 'https://example.invalid'})
            refused = 'the key helper refused: OPENWIZ_HOSTKEY_TEST_ORIGIN is not http://127.0.0.1:<port>'
            self.assertEqual((devin.returncode, json.loads(devin.stdout)['error'][:len(refused)]), (1, refused))
            keyed = subprocess.run([sys.executable, '-I', 'kernel/driver-kit/kit.py', '--driver', 'adapters/devin/driver',
                                    '--repo', 'synthetic/throwaway', '--ticket', '1', '--harness', 'devin',
                                    '--model', 'default', '--tracker', str(root / 'tracker.json'), '--wait', '1'],
                                   cwd=adapters.parent, capture_output=True, text=True, timeout=300,
                                   env={'PATH': fixture_path, 'HOME': str(root), 'DEVIN_ORG_ID': 'org-syn0001',
                                        'OPENWIZ_HOSTKEY_TEST_ORIGIN': 'http://127.0.0.1:9'})
            self.assertEqual(keyed.stdout.splitlines()[-1:], [
                'pass token: no login or token passed through the driver, and on start, wake and stop the devin key '
                'reached its host only from the key helper, in its header'], keyed.stderr)

    def test_an_untracked_selected_host_is_never_carried(self):
        tracked = {'adapters/local/driver': b'#!/usr/bin/env python3\nprint("synthetic local driver")\n',
                   'adapters/local/schema.json': b'{"synthetic": "local schema"}\n'}
        with tempfile.TemporaryDirectory(prefix='openwiz-untracked-host-') as temporary:
            root = Path(temporary)
            runtime_root(self, root)
            for path, data in tracked.items():
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                (root / path).write_bytes(data)
            (root / 'adapters/local/release.json').write_bytes(b'{"extra_files": []}\n')
            source = commit(root, 'skills', 'tools', 'adapters/local')
            room = root / 'adapters/cloudroom'
            room.mkdir()
            (room / 'driver').write_bytes(b'untracked synthetic driver\n')
            (room / 'schema.json').write_bytes(b'{}\n')
            (room / 'release.json').write_bytes(b'{"extra_files": []}\n')
            result, output = collected(root, source)
            self.assertEqual(result.returncode, 0, result.stderr)
            assets = {row['path'] for row in json.loads(Path(str(output) + '.json').read_bytes())['assets']}
            self.assertEqual(sorted(p for p in assets if p.startswith('runtime/adapters/')),
                             sorted('runtime/' + path for path in tracked))

    def test_every_driver_shipped_before_its_folder_decided_still_ships_the_same_files(self):
        hosts = ('boat', 'cloudroom', 'devin', 'factory', 'hermes', 'local', 'openclaw')
        before = {f'runtime/adapters/{host}/{name}' for host in hosts for name in ('driver', 'schema.json')}
        before |= {'runtime/adapters/devin/README.md', 'runtime/adapters/devin/fixtures/kit-host.json'}
        with tempfile.TemporaryDirectory(prefix='openwiz-driver-set-') as temporary:
            root = Path(temporary)
            runtime_root(self, root)
            shutil.copytree(ROOT / 'adapters', root / 'adapters')
            result, output = collected(root, commit(root, 'skills', 'tools', 'adapters'))
            self.assertEqual(result.returncode, 0, result.stderr)
            assets = {row['path'] for row in json.loads(Path(str(output) + '.json').read_bytes())['assets']}
            self.assertEqual(sorted(before - assets), [])
            self.assertEqual([p for p in assets if p.startswith('runtime/adapters/template/')], [])

    def test_a_malformed_release_json_stops_the_build_and_is_named(self):
        listed = lambda *names: json.dumps({'extra_files': names}).encode()
        bad = {'not JSON': b'{', 'not UTF-8': b'{"extra_files": ["\xff"]}', 'an array': b'[]', 'empty': b'',
               'no key': b'{}', 'another key': b'{"extra_files": [], "ship": true}',
               'a repeated key': b'{"extra_files": ["README.md"], "extra_files": []}',
               'not a list': b'{"extra_files": "README.md"}', 'null': b'{"extra_files": null}',
               'a number': b'{"extra_files": [1]}', 'deep nesting': b'[' * 200000,
               'a repeated file': listed('README.md', 'README.md'), 'the driver': listed('driver'),
               'the schema': listed('schema.json'), 'absolute': listed('/README.md'),
               'outside': listed('../boat/README.md'), 'a dot': listed('./README.md'),
               'a doubled slash': listed('fixtures//host.json'), 'an empty name': listed(''),
               'a folder': listed('fixtures'), 'missing': listed('absent.md'),
               'untracked': listed('untracked.md'), 'a link': listed('link.md'),
               'a surrogate': b'{"extra_files": ["\\ud800"]}'}
        good = listed('README.md', 'fixtures/host.json')
        for case, data in [('good', good), *bad.items()]:
            with self.subTest(case), tempfile.TemporaryDirectory(prefix='openwiz-release-json-') as temporary:
                root = Path(temporary)
                runtime_root(self, root)
                folder = root / 'adapters/made-up'
                (folder / 'fixtures').mkdir(parents=True)
                for name in ('driver', 'schema.json', 'README.md', 'fixtures/host.json'):
                    (folder / name).write_bytes(b'synthetic\n')
                (folder / 'link.md').symlink_to('README.md')
                (folder / 'release.json').write_bytes(data)
                source = commit(root, 'skills', 'tools', 'adapters')
                (folder / 'untracked.md').write_bytes(b'synthetic\n')
                (folder / 'release.json').write_bytes(good)
                result, output = collected(root, source)
                if case == 'good':
                    self.assertEqual(result.returncode, 0, result.stderr)
                    continue
                self.assertEqual((result.returncode, result.stderr), (1,
                    'build-products: refused adapters/made-up/release.json: not {"extra_files": [...]} naming '
                    'tracked regular files in its folder\n'))
                self.assertFalse(output.exists())

    def test_a_release_json_that_can_not_ship_a_driver_is_named(self):
        for folder, names, kind in (('made-up', ('schema.json',), 'file'), ('made-up', ('driver',), 'file'),
                                    ('Made_Up', ('driver', 'schema.json'), 'file'),
                                    ('made-up', ('driver', 'schema.json'), 'link')):
            with self.subTest(folder=folder, names=names, kind=kind), \
                    tempfile.TemporaryDirectory(prefix='openwiz-release-json-') as temporary:
                root = Path(temporary)
                runtime_root(self, root)
                home = root / 'adapters' / folder
                home.mkdir(parents=True)
                for name in names:
                    (home / name).write_bytes(b'synthetic\n')
                if kind == 'link':
                    (home / 'real.json').write_bytes(b'{"extra_files": []}')
                    (home / 'release.json').symlink_to('real.json')
                else:
                    (home / 'release.json').write_bytes(b'{"extra_files": []}')
                result, output = collected(root, commit(root, 'skills', 'tools', 'adapters'))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn(f'build-products: refused adapters/{folder}/release.json: ', result.stderr)
                self.assertFalse(output.exists())

    def test_installed_build_carries_the_wizskills_root_files_its_skills_read(self):
        release = ROOT / '.wizskills'
        self.assertTrue((release / '.git').is_dir(), 'Install the pinned WizSkills first: tools/wizskills/install.py')
        show = lambda *a: subprocess.check_output(['git', '-C', str(release), *a])
        roots = [p for p in show('ls-tree', '-r', '-z', '--name-only', 'HEAD', '--', 'contracts').decode().split('\0') if p]
        with tempfile.TemporaryDirectory(prefix='openwiz-wizskills-products-') as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            runtime_root(self, root)
            subprocess.run(['rm', '-rf', str(root / 'skills')], check=True)
            shutil.copytree(release, root / '.wizskills', symlinks=True)
            os.symlink('.wizskills/skills', root / 'skills')
            (root / '.gitignore').write_bytes(b'/.wizskills/\n')
            shutil.copyfile(ROOT / 'wizskills.lock', root / 'wizskills.lock')
            source = commit(root, '.gitignore', 'wizskills.lock', 'skills', 'tools')
            target = TARGETS[0]
            (root / 'job').mkdir()
            receipts = build(binaries, source, target, root / 'job')
            output = root / 'products'
            result = subprocess.run(collector(root, binaries, output, source, target, receipts),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            bundle = root / 'bundle'
            result = subprocess.run([sys.executable, str(ROOT / 'tools/release/package.py'), '--products', str(output),
                                     '--identity', str(output) + '.json', '--output', str(bundle)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.bound_and_installed(root, target, Path(str(output) + '.json'), bundle,
                                     products=output, home=root / 'installed')
            runtime = root / 'installed/current/runtime'
            host = subprocess.run([sys.executable, '-I', str(runtime / 'skills/launch-fleet/scripts/host.py')],
                                  cwd=root, capture_output=True, text=True, timeout=60, env={'PATH': os.environ['PATH']})
            self.assertNotIn('FileNotFoundError', host.stderr)
            self.assertIn('usage: which', host.stderr)
            for path in roots:
                self.assertEqual((runtime / path).read_bytes(), show('show', 'HEAD:' + path), path)
            assets = json.loads(Path(str(output) + '.json').read_bytes())['assets']
            self.assertEqual(sorted(a['path'] for a in assets if a['path'].startswith('runtime/contracts/')),
                             sorted('runtime/' + path for path in roots))

    def test_installed_boat_driver_finds_the_wizskills_pin(self):
        release = ROOT / '.wizskills'
        self.assertTrue((release / '.git').is_dir(), 'Install the pinned WizSkills first: tools/wizskills/install.py')
        driver = ('adapters/boat/driver', 'adapters/boat/schema.json', 'adapters/boat/release.json',
                  'kernel/driver-kit/kit.py',
                  'kernel/driver-kit/schema.json', 'kernel/records-kit/check.py', 'kernel/records.v1.md',
                  'kernel/driver-kit/hostkey.py', 'kernel/driver-kit/hosts.json')
        with tempfile.TemporaryDirectory(prefix='openwiz-boat-pin-') as temporary:
            root = Path(temporary)
            binaries = root / 'bin'
            binaries.mkdir()
            runtime_root(self, root)
            subprocess.run(['rm', '-rf', str(root / 'skills')], check=True)
            shutil.copytree(release, root / '.wizskills', symlinks=True)
            os.symlink('.wizskills/skills', root / 'skills')
            (root / '.gitignore').write_bytes(b'/.wizskills/\n')
            for path in ('wizskills.lock', *driver):
                (root / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / path, root / path)
            source = commit(root, '.gitignore', 'wizskills.lock', 'skills', 'tools', *driver)
            target = TARGETS[0]
            (root / 'job').mkdir()
            receipts = build(binaries, source, target, root / 'job')
            output = root / 'products'
            result = subprocess.run(collector(root, binaries, output, source, target, receipts),
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            bundle = root / 'bundle'
            result = subprocess.run([sys.executable, str(ROOT / 'tools/release/package.py'), '--products', str(output),
                                     '--identity', str(output) + '.json', '--output', str(bundle)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.bound_and_installed(root, target, Path(str(output) + '.json'), bundle,
                                     products=output, home=root / 'installed')
            installed = root / 'installed/current/runtime/adapters/boat/driver'
            boats = root / 'boat.json'
            env = {'HOME': str(root / 'home'), 'PATH': str(ROOT / 'adapters/boat/fixtures/bin') + os.pathsep
                   + os.environ['PATH'], 'FAKE_BOAT_STATE': str(boats), 'OPENWIZ_BOAT_STATE': str(root / 'state'),
                   'OPENWIZ_BOAT_SETTLE': '1', 'KIT_TRACKER': str(root / 'tracker.json'),
                   'FAKE_BOAT_FAIL': 'exec'}
            (root / 'tracker.json').write_text(json.dumps({'record_authors': ['synthetic-author'], 'comments': []}))
            started = subprocess.run([str(installed), 'start'], input=json.dumps(
                {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude',
                 'model': 'synthetic'}), env=env, capture_output=True, text=True, timeout=120)
            self.assertNotIn('wizskills.lock', started.stdout + started.stderr)
            self.assertEqual(len(json.loads(boats.read_bytes())['sandboxes']), 1, started.stdout + started.stderr)
            self.assertEqual((root / 'installed/current/runtime/wizskills.lock').read_bytes(),
                             (ROOT / 'wizskills.lock').read_bytes())
            (root / 'wizskills.lock').write_bytes((ROOT / 'wizskills.lock').read_bytes() + b'\n')
            stale = subprocess.run(elsewhere(collector(root, binaries, output, source, target, receipts),
                                             str(output) + '-stale'), capture_output=True, text=True)
            self.assertEqual(stale.returncode, 1, stale.stderr)
            self.assertFalse(Path(str(output) + '-stale').exists())

    def bound_and_installed(self, root, target, identity_file, bundle, products=None, home=None):
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
            '--root', str(home or root / (target + '-installed')), '--manifest', str(manifest),
            '--archive', str(bundle / f'openwiz-0.0.99-{target}.tar.gz'),
            '--manifest-sha256', hashlib.sha256(manifest.read_bytes()).hexdigest(), '--target', target],
            capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual(((home or root / (target + '-installed')) / 'current/runtime/openwiz-build.txt').read_bytes(),
                         ((products or bundle.parent / (target + '-products')) / 'runtime/openwiz-build.txt').read_bytes())
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


def runtime_root(case, root):
    """A synthetic source with every required runtime file; returns its tools/install folder."""
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
    case.assertEqual(sorted(SETUP_SOURCES), sorted(SETUP_TOOLS))
    for name, source in SETUP_SOURCES.items():
        (root / source).parent.mkdir(parents=True, exist_ok=True)
        (root / source).write_bytes(f'Synthetic setup tool {name}.\n'.encode())
    return scripts


def commit(root, *paths):
    """Commits `paths` in the synthetic source; returns the commit."""
    for args in (['init', '-q'], ['add', *paths],
                 ['-c', 'user.name=Synthetic Builder', '-c', 'user.email=builder@example.invalid',
                  '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'Synthetic runtime fixture']):
        subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
    return subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()


def collected(root, source):
    (root / 'bin').mkdir()
    (root / 'job').mkdir()
    receipts = build(root / 'bin', source, TARGETS[0], root / 'job')
    output = root / 'products'
    return subprocess.run(collector(root, root / 'bin', output, source, TARGETS[0], receipts),
                          capture_output=True, text=True), output


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
