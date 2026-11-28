#!/usr/bin/env python3
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
from io import BytesIO, StringIO
import json
from pathlib import Path
import socket
import stat
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURES = ROOT / 'contracts' / 'fixtures' / 'driver-package'
MARKET = '1111111111111111111111111111111111111111'
KIT = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
REPO = 'example-publisher/example-driver'
spec = importlib.util.spec_from_file_location('driver_fetch', HERE / 'fetch.py')
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)

def sha(data):
    return hashlib.sha256(data).hexdigest()


def receipt(package):
    lines = [
        '# listing: ' + package['driver'], '# host: local',
        '# driver: %s@%s' % (package['repository'], package['commit']),
        '# kit: openwizdev/OpenWiz@%s' % KIT,
        '# harness: synthetic', '# model: synthetic',
        '# date: 2030-01-02', '# run by: example-publisher',
        'pass version: synthetic',
        'pass start: the run posted builder status note <note>',
        'pass wake: the run edited builder status note <note>',
        'pass stop: synthetic',
        'pass token: no login or token passed through the driver',
        'Result: 5 of 5 pass']
    return ''.join(line + '\n' for line in lines).encode()


def listing(package, status, publisher='example-publisher'):
    body = {
        'name': 'Synthetic host',
        'summary': 'A synthetic driver pinned to one release of its own repository.',
        'tags': ['driver'], 'url': 'https://example.com/synthetic-host',
        'plugs_into': 'OpenWiz driver v1', 'publisher': publisher,
        'stage': 'available', 'status': status, 'package': package}
    if status == 'verified':
        body['proof'] = {'receipt': 'receipts/%s/2030-01-02-%s.txt' % (
            package['driver'], package['commit'][:12])}
    return json.dumps(body).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        host = (self.headers.get('Host') or '').split(':')[0].lower()
        self.server.seen.append((host, self.path))
        item = self.server.routes.get((host, self.path))
        if isinstance(item, str):
            body = b''
            self.send_response(302)
            self.send_header('Location', item)
        elif item is None:
            body = b'no'
            self.send_response(404)
        else:
            body = item
            self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        real = socket.create_connection

        def guarded(address, *args, **kwargs):
            host = address[0] if isinstance(address, tuple) else address
            if host != '127.0.0.1':
                raise AssertionError('network ' + str(address))
            return real(address, *args, **kwargs)

        socket.create_connection = guarded
        cls.addClassCleanup(setattr, socket, 'create_connection', real)

    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.routes, self.server.seen = {}, []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.server.server_close)
        self.loopback = '127.0.0.1:%d' % self.server.server_port
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve() / 'install'
        self.root.mkdir(mode=0o700)
        self.build = self.root.with_name('build')
        runtime = self.build / 'runtime'
        assets = []
        for rel in fetch.KIT_FILES:
            target = runtime / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            data = (b'openwiz.package.v1\n0.2.0\n' + b'c' * 40 + b'\nx86_64-unknown-linux-gnu\n'
                    if rel == 'openwiz-build.txt' else (ROOT / rel).read_bytes())
            target.write_bytes(data)
            target.chmod(0o600)
            assets.append({'path': 'runtime/' + rel, 'bytes': len(data), 'mode': '0600',
                           'sha256': sha(data)})
        (self.build / 'install-manifest.json').write_text(json.dumps({
            'schema': 'openwiz.install.v1', 'version': '0.2.0', 'source': 'c' * 40,
            'target': 'x86_64-unknown-linux-gnu', 'setup_api': 1,
            'archive': 'openwiz.tar.gz', 'archive_bytes': 1, 'archive_sha256': 'd' * 64,
            'assets': assets}))
        spy = patch.object(fetch, 'spawn', wraps=fetch.spawn)
        self.calls = spy.start().call_args_list
        self.addCleanup(spy.stop)

    def route(self, host, path, body):
        self.server.routes[(host, path)] = body

    def publish(self, package, folder, status='verified', publisher='example-publisher', redirect=False):
        archive = (folder / 'driver.tar.gz').read_bytes()
        manifest = (folder / 'manifest.json').read_bytes()
        sums = (folder / 'SHA256SUMS').read_bytes()
        base = '/%s/releases/download/v%s/' % (package['repository'], package['version'])
        archive_path = base + 'driver.tar.gz'
        if redirect:
            self.route('github.com', archive_path, 'https://release-assets.githubusercontent.com/assets/driver.tar.gz')
            self.route('release-assets.githubusercontent.com', '/assets/driver.tar.gz', archive)
        else:
            self.route('github.com', archive_path, archive)
        self.route('github.com', base + 'manifest.json', manifest)
        self.route('github.com', base + 'SHA256SUMS', sums)
        ref = '/repos/%s/git/ref/tags/v%s' % (package['repository'], package['version'])
        self.route('api.github.com', ref, json.dumps({
            'ref': 'refs/tags/v' + package['version'],
            'object': {'type': 'commit', 'sha': package['commit']}}).encode())
        market_path = '/repos/openwizdev/WizMarket/contents/listings?ref=' + MARKET
        rows = json.loads(self.server.routes.get(('api.github.com', market_path), b'[]'))
        filename = package['driver'] + '.json'
        for name in (filename, 'plain.json'):
            if {'name': name, 'type': 'file'} not in rows:
                rows.append({'name': name, 'type': 'file'})
        self.route('api.github.com', market_path, json.dumps(rows).encode())
        self.route('raw.githubusercontent.com', '/openwizdev/WizMarket/%s/listings/%s' % (MARKET, filename),
                   listing(package, status, publisher))
        self.route('raw.githubusercontent.com',
                   '/openwizdev/WizMarket/%s/listings/plain.json' % MARKET,
                   b'{"name":"Plain","summary":"A synthetic listing with no package.","tags":["skill"],'
                   b'"url":"https://example.com/plain","plugs_into":"OpenWiz","publisher":"example-publisher",'
                   b'"stage":"available","status":"listed"}')
        if status == 'verified':
            path = '/openwizdev/WizMarket/%s/receipts/%s/2030-01-02-%s.txt' % (
                MARKET, package['driver'], package['commit'][:12])
            self.route('raw.githubusercontent.com', path, receipt(package))

    def command(self, *args):
        with redirect_stdout(StringIO()) as out, redirect_stderr(StringIO()) as err:
            code = fetch.main(list(args))
        return code, out.getvalue(), err.getvalue()

    def add(self, name='synthetic-host', answer=None):
        args = ['add', name, '--root', str(self.root), '--build', str(self.build),
                '--market-commit', MARKET, '--loopback', self.loopback]
        if answer:
            args.extend(['--answer', answer])
        return self.command(*args)

    def update(self, *args, answers=None):
        stdin = StringIO(answers or '')
        with patch('sys.stdin', stdin), patch.object(stdin, 'isatty', return_value=answers is not None):
            return self.command('update', '--root', str(self.root), '--build', str(self.build),
                                '--market-commit', MARKET, '--loopback', self.loopback, *args)

    def package(self, case='good'):
        return json.loads((FIXTURES / case / 'package.json').read_text())

    def release(self, name, version, commit):
        folder = Path(self.tmp.name) / (name + '-' + version)
        folder.mkdir()
        manifest = json.loads((FIXTURES / 'good' / 'manifest.json').read_text())
        manifest.update(driver=name, version=version)
        with tarfile.open(FIXTURES / 'good' / 'driver.tar.gz', 'r:gz') as fixture:
            with tarfile.open(folder / 'driver.tar.gz', 'w:gz', format=tarfile.USTAR_FORMAT) as archive:
                for entry in manifest['files']:
                    member = fixture.getmember(entry['path'])
                    data = fixture.extractfile(member).read().replace(b'synthetic-host', name.encode())
                    entry['sha256'] = sha(data)
                    member.size = len(data)
                    archive.addfile(member, BytesIO(data))
        raw = json.dumps(manifest).encode()
        (folder / 'manifest.json').write_bytes(raw)
        archive_sha = sha((folder / 'driver.tar.gz').read_bytes())
        (folder / 'SHA256SUMS').write_text('%s  driver.tar.gz\n%s  manifest.json\n' % (archive_sha, sha(raw)))
        repository = REPO if name == 'synthetic-host' else 'example-publisher/' + name
        package = dict(self.package(), driver=name, version=version, commit=commit,
                       repository=repository, sha256=archive_sha,
                       asset_url='https://github.com/%s/releases/download/v%s/driver.tar.gz' % (repository, version))
        return package, folder

    def pin(self, package):
        pins = {'contract': 'openwiz.driver-package.v1', 'pins': [{
            'package': package, 'publisher': 'example-publisher',
            'evidence': {'bundled_version': '0.1.1'}}]}
        path = self.build / 'runtime' / 'pins.json'
        path.write_text(json.dumps(pins))
        path.chmod(0o600)
        return path

    def assert_refused(self, result, phrase):
        code, out, err = result
        self.assertEqual(code, 1, out)
        body = json.loads(out)
        self.assertEqual(set(body), {'error', 'next'})
        for value in body.values():
            self.assertTrue(1 <= len(value) <= 300)
            self.assertNotIn('\n', value)
        self.assertIn(phrase, out + err)
        return err

    def assert_ok(self, result):
        code, out, err = result
        self.assertEqual(code, 0, out)
        return json.loads(out), err

    def test_a_good_package_installs_only_after_yes(self):
        package = self.package()
        self.publish(package, FIXTURES / 'good', redirect=True)
        err = self.assert_refused(self.add(), 'after the confirmation')
        for detail in ('example-publisher', '1.2.3', '2030-01-02', 'no login (fixture only)', 'start, wake, stop'):
            self.assertIn(detail, err)
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])
        self.assert_ok(self.add(answer='yes'))
        driver = self.root / 'drivers/synthetic-host/driver'
        manifest = json.loads((FIXTURES / 'good/manifest.json').read_text())
        self.assertEqual(sha(driver.read_bytes()), manifest['files'][0]['sha256'])
        self.assertEqual(stat.S_IMODE(driver.stat().st_mode), 0o700)
        approval = json.loads((driver.parent / 'approval.json').read_text())
        expected = {key: package[key] for key in ('repository', 'version', 'sha256')}
        self.assertEqual(approval, dict(expected, publisher='example-publisher'))
        for rel in fetch.KIT_FILES:
            kit_file = driver.parent / '..' / '..' / rel
            self.assertEqual(kit_file.read_bytes(), (self.build / 'runtime' / rel).read_bytes())
            self.assertEqual(stat.S_IMODE(kit_file.stat().st_mode), 0o600)
        result, _ = self.assert_ok(self.command('list', '--root', str(self.root)))
        self.assertEqual(result['drivers'], [dict(approval, name='synthetic-host')])
        self.assertIn('release-assets.githubusercontent.com', [host for host, _ in self.server.seen])

    def test_each_broken_fixture_is_refused_and_not_run(self):
        cases = json.loads((FIXTURES / 'cases.json').read_text())
        for case, reason in cases.items():
            if reason is None:
                continue
            with self.subTest(case=case):
                self.server.seen.clear()
                self.publish(self.package(case), FIXTURES / case)
                self.assert_refused(self.add(answer='yes'), fetch.REASONS[reason][0])
                self.assertEqual(self.calls, [])
                self.assertEqual(list(self.root.iterdir()), [])
                if case == 'off-repository':
                    self.assertFalse(any('driver.tar.gz' in path for _, path in self.server.seen))

    def test_a_listed_driver_needs_its_own_yes(self):
        self.publish(self.package(), FIXTURES / 'good', status='listed')
        self.assert_refused(self.add(answer='yes'), 'has not passed the kit')
        self.assertEqual(self.add(answer='install-unverified')[0], 0)
        self.assertEqual(len(self.calls), 1)

    def test_update_moves_the_same_publisher_and_asks_otherwise(self):
        self.publish(self.package(), FIXTURES / 'good')
        self.assertEqual(self.add(answer='yes')[0], 0)
        moved, folder = self.release('synthetic-host', '1.3.0', 'd' * 40)
        self.publish(moved, folder)
        result, err = self.assert_ok(self.update())
        self.assertIn('moved from 1.2.3 to 1.3.0, same publisher example-publisher', err)
        result, _ = self.assert_ok(self.update())
        self.assertEqual(result['unchanged'], [{'name': 'synthetic-host', 'version': '1.3.0'}])
        changed, folder = self.release('synthetic-host', '1.4.0', 'e' * 40)
        self.publish(changed, folder, publisher='other-publisher')
        err = self.assert_refused(self.update(), 'own yes')
        self.assertIn('other-publisher', err)
        result, _ = self.assert_ok(self.update(answers='yes\n'))
        self.assertEqual(result['updated'][0]['publisher'], 'other-publisher')

    def test_build_and_installed_kit_mismatches_are_refused(self):
        self.publish(self.package(), FIXTURES / 'good')
        rel = 'kernel/driver-kit/hosts.json'
        source = self.build / 'runtime' / rel
        original = source.read_bytes()
        source.write_bytes(b'{}')
        self.assert_refused(self.add(answer='yes'), 'does not match the install manifest')
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])
        source.write_bytes(original)
        self.assertEqual(self.add(answer='yes')[0], 0)
        installed = self.root / rel
        installed.write_bytes(b'{}')
        self.assert_refused(self.add(answer='yes'), 'installed kit')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(installed.read_bytes(), b'{}')

    def test_update_uses_core_and_pins_before_wizmarket(self):
        package = self.package()
        self.publish(package, FIXTURES / 'good')
        self.pin(package)
        self.assertEqual(self.add()[0], 0)
        self.assertFalse(any('/listings' in path for _, path in self.server.seen))
        moved, folder = self.release('synthetic-host', '1.3.0', 'd' * 40)
        self.publish(moved, folder)
        self.server.seen.clear()
        result, _ = self.assert_ok(self.update())
        self.assertEqual(result['unchanged'], [{'name': 'synthetic-host', 'version': '1.2.3'}])
        self.assertEqual(self.server.seen, [])
        pin = self.pin(moved)
        core = self.build / 'runtime/adapters/synthetic-host/driver'
        core.parent.mkdir(parents=True)
        core.write_text('#!/bin/sh\n')
        core.chmod(0o700)
        self.assert_refused(self.add(answer='yes'), 'core driver')
        self.assertEqual(json.loads(self.update()[1])['updated'], [])
        self.assertEqual(self.server.seen, [])
        core.unlink()
        result, err = self.assert_ok(self.update())
        self.assertEqual(result['updated'][0]['version'], '1.3.0')
        self.assertNotIn('same publisher', err)
        self.assertFalse(any('/listings' in path for _, path in self.server.seen))
        pin.unlink()
        newer, folder = self.release('synthetic-host', '1.4.0', 'e' * 40)
        self.publish(newer, folder)
        self.assert_refused(self.update(), 'own yes')

    def test_losing_verification_needs_its_own_yes_for_the_same_release(self):
        package = self.package()
        self.publish(package, FIXTURES / 'good')
        self.assertEqual(self.add(answer='yes')[0], 0)
        self.publish(package, FIXTURES / 'good', status='listed')
        for answers in (None, 'yes\n'):
            self.assert_refused(self.update(answers=answers), 'has not passed the kit')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.update(answers='install-unverified\n')[0], 0)
        result, err = self.assert_ok(self.update())
        self.assertEqual(result['unchanged'], [{'name': 'synthetic-host', 'version': '1.2.3'}])
        self.assertNotIn('has not passed the kit', err)

    def test_each_changed_driver_needs_a_separate_answer(self):
        second, folder = self.release('synthetic-other', '2.0.0', 'e' * 40)
        for package, source in ((self.package(), FIXTURES / 'good'), (second, folder)):
            self.publish(package, source)
            self.assertEqual(self.add(package['driver'], answer='yes')[0], 0)
            self.publish(package, source, status='listed', publisher='other-publisher')
        self.assert_refused(self.update('--answer', 'install-unverified'), 'not understood')
        result, err = self.assert_ok(self.update(answers='install-unverified\nno\n'))
        for detail in ('Name: synthetic-host', 'Name: synthetic-other', second['sha256']):
            self.assertIn(detail, err)
        self.assertEqual([item['name'] for item in result['updated']], ['synthetic-host'])
        self.assertEqual(result['unchanged'], [{'name': 'synthetic-other', 'version': '2.0.0'}])
        _, out, _ = self.command('list', '--root', str(self.root))
        self.assertEqual([item['publisher'] for item in json.loads(out)['drivers']],
                         ['other-publisher', 'example-publisher'])
        self.assertEqual(len(self.calls), 3)

    def test_off_github_redirect_failed_receipt_and_missing_root_are_refused(self):
        self.publish(self.package(), FIXTURES / 'good')
        self.assert_refused(self.command('list', '--root', str(self.root / 'missing')), 'private directory')
        self.root.rmdir()
        self.assert_refused(self.add(answer='yes'), 'private directory')
        self.root.mkdir(mode=0o700)
        self.route('github.com', '/%s/releases/download/v1.2.3/driver.tar.gz' % REPO,
                   'https://evil.example/driver.tar.gz')
        self.assert_refused(self.add(answer='yes'), 'off GitHub')
        self.assertNotIn('evil.example', [host for host, _ in self.server.seen])
        path = '/openwizdev/WizMarket/%s/receipts/synthetic-host/2030-01-02-%s.txt' % (
            MARKET, self.package()['commit'][:12])
        self.route('raw.githubusercontent.com', path, receipt(self.package()).replace(b'pass start:', b'fail start:'))
        self.assert_refused(self.add(answer='yes'), 'receipt')
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
