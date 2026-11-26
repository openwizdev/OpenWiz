#!/usr/bin/env python3
import hashlib
import importlib.util
from io import StringIO
import json
from pathlib import Path
import shutil
import socket
import stat
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
FIXTURES = ROOT / 'contracts' / 'fixtures' / 'driver-package'
MARKET = '1111111111111111111111111111111111111111'
COMMIT = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
KIT = 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
REPO = 'example-publisher/example-driver'
spec = importlib.util.spec_from_file_location('driver_fetch', HERE / 'fetch.py')
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)

PHRASES = {
    'wrong-checksum': 'pinned checksum',
    'extra-file': 'does not name',
    'missing-file': 'missing a file',
    'link': 'regular file',
    'wrong-mode': 'wrong mode',
    'wrong-driver-name': 'does not match',
    'changed-schema': 'openwiz update',
    'off-repository': 'not this repository',
    'wrong-file-hash': 'manifest hash',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def receipt(commit, date='2030-01-02'):
    lines = [
        '# listing: synthetic-host', '# host: local',
        '# driver: %s@%s' % (REPO, commit),
        '# kit: openwizdev/OpenWiz@%s' % KIT,
        '# harness: synthetic', '# model: synthetic',
        '# date: %s' % date, '# run by: example-publisher',
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
        body['proof'] = {'receipt': 'receipts/synthetic-host/2030-01-02-%s.txt' % package['commit'][:12]}
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
        self.root = Path(self.tmp.name) / 'install'
        self.root.mkdir(mode=0o700)
        self.build = Path(self.tmp.name) / 'build'
        runtime = self.build / 'runtime'
        for rel in fetch.KIT_FILES:
            source = ROOT / rel
            target = runtime / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if rel == 'openwiz-build.txt' or not source.is_file():
                target.write_text('openwiz.package.v1\n0.2.0\n%s\nx86_64-unknown-linux-gnu\n' % ('c' * 40))
            else:
                shutil.copyfile(source, target)
            target.chmod(0o600)
        self.calls = []
        real_spawn = fetch.spawn

        def spy(program):
            self.calls.append(str(program))
            return real_spawn(program)

        fetch.spawn = spy
        self.addCleanup(setattr, fetch, 'spawn', real_spawn)

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
        self.route('api.github.com', '/repos/openwizdev/WizMarket/contents/listings?ref=' + MARKET,
                   json.dumps([{'name': 'synthetic-host.json', 'type': 'file'},
                               {'name': 'plain.json', 'type': 'file'}]).encode())
        self.route('raw.githubusercontent.com',
                   '/openwizdev/WizMarket/%s/listings/synthetic-host.json' % MARKET,
                   listing(package, status, publisher))
        self.route('raw.githubusercontent.com',
                   '/openwizdev/WizMarket/%s/listings/plain.json' % MARKET,
                   b'{"name":"Plain","summary":"A synthetic listing with no package.","tags":["skill"],'
                   b'"url":"https://example.com/plain","plugs_into":"OpenWiz","publisher":"example-publisher",'
                   b'"stage":"available","status":"listed"}')
        if status == 'verified':
            path = '/openwizdev/WizMarket/%s/receipts/synthetic-host/2030-01-02-%s.txt' % (MARKET, package['commit'][:12])
            self.route('raw.githubusercontent.com', path, receipt(package['commit']))

    def command(self, *args):
        out, err = StringIO(), StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            code = fetch.main(list(args))
        finally:
            sys.stdout, sys.stderr = old
        return code, out.getvalue(), err.getvalue()

    def add(self, name='synthetic-host', answer=None, market=MARKET):
        args = ['add', name, '--root', str(self.root), '--build', str(self.build),
                '--market-commit', market, '--loopback', self.loopback]
        if answer:
            args.extend(['--answer', answer])
        return self.command(*args)

    def package(self, case='good'):
        return json.loads((FIXTURES / case / 'package.json').read_text())

    def test_a_good_package_installs_only_after_yes(self):
        self.publish(self.package(), FIXTURES / 'good', redirect=True)
        code, out, err = self.add()
        self.assertEqual(code, 1)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'drivers').exists())
        self.assertIn('example-publisher', err)
        self.assertIn('2030-01-02', err)
        self.assertIn('no login (fixture only)', err)
        self.assertIn('start, wake, stop', err)
        code, out, err = self.add(answer='yes')
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.calls), 1)
        driver = self.root / 'drivers' / 'synthetic-host' / 'driver'
        self.assertTrue(driver.is_file())
        manifest = json.loads((FIXTURES / 'good' / 'manifest.json').read_text())
        expected = next(item['sha256'] for item in manifest['files'] if item['path'] == 'driver')
        self.assertEqual(sha(driver.read_bytes()), expected)
        self.assertEqual(stat.S_IMODE(driver.stat().st_mode), 0o700)
        approval = json.loads((driver.parent / 'approval.json').read_text())
        self.assertEqual(approval['repository'], REPO)
        self.assertEqual(approval['publisher'], 'example-publisher')
        self.assertEqual(approval['version'], '1.2.3')
        self.assertEqual(approval['sha256'], self.package()['sha256'])
        code, listed, _ = self.command('list', '--root', str(self.root))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(listed)['drivers'][0]['name'], 'synthetic-host')
        hosts = [host for host, _ in self.server.seen]
        self.assertIn('release-assets.githubusercontent.com', hosts)
        self.assertNotIn('evil.example', hosts)

    def test_each_broken_fixture_is_refused_and_not_run(self):
        cases = json.loads((FIXTURES / 'cases.json').read_text())
        for case, phrase in PHRASES.items():
            with self.subTest(case=case):
                self.server.routes.clear()
                self.server.seen.clear()
                self.calls.clear()
                shutil.rmtree(self.root / 'drivers', ignore_errors=True)
                self.publish(self.package(case), FIXTURES / case)
                code, out, err = self.add(answer='yes')
                self.assertEqual(code, 1, out)
                body = json.loads(out)
                self.assertIn(phrase, body['error'] + body['next'])
                self.assertTrue(1 <= len(body['error']) <= 300 and 1 <= len(body['next']) <= 300)
                self.assertNotIn('\n', body['error'])
                self.assertEqual(self.calls, [])
                self.assertFalse((self.root / 'drivers').exists())
                self.assertEqual(cases[case] is not None, True)
                if case == 'off-repository':
                    self.assertFalse(any('driver.tar.gz' in path for _, path in self.server.seen))

    def test_a_listed_driver_needs_its_own_yes(self):
        self.publish(self.package(), FIXTURES / 'good', status='listed')
        code, out, err = self.add(answer='yes')
        self.assertEqual(code, 1)
        self.assertIn('has not passed the kit', err)
        self.assertIn('own', json.loads(out)['next'])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'drivers').exists())
        code, out, _ = self.add(answer='install-unverified')
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / 'drivers' / 'synthetic-host' / 'driver').is_file())
        self.assertEqual(len(self.calls), 1)

    def test_update_moves_the_same_publisher_and_asks_otherwise(self):
        self.publish(self.package(), FIXTURES / 'good')
        self.assertEqual(self.add(answer='yes')[0], 0)
        moved = dict(self.package(), version='1.3.0', commit='d' * 40)
        moved['asset_url'] = moved['asset_url'].replace('v1.2.3', 'v1.3.0')
        manifest = json.loads((FIXTURES / 'good' / 'manifest.json').read_text())
        manifest['version'] = '1.3.0'
        folder = Path(self.tmp.name) / 'moved'
        folder.mkdir()
        (folder / 'driver.tar.gz').write_bytes((FIXTURES / 'good' / 'driver.tar.gz').read_bytes())
        raw = (json.dumps(manifest, indent=2) + '\n').encode()
        (folder / 'manifest.json').write_bytes(raw)
        archive = (folder / 'driver.tar.gz').read_bytes()
        (folder / 'SHA256SUMS').write_bytes(
            ('%s  driver.tar.gz\n%s  manifest.json\n' % (sha(archive), sha(raw))).encode())
        before = len(self.calls)
        self.publish(moved, folder)
        code, out, err = self.command(
            'update', '--root', str(self.root), '--build', str(self.build),
            '--market-commit', MARKET, '--loopback', self.loopback)
        self.assertEqual(code, 0, out)
        self.assertIn('moved from 1.2.3 to 1.3.0', err)
        self.assertIn('same publisher', err)
        self.assertGreater(len(self.calls), before)
        approval = json.loads((self.root / 'drivers' / 'synthetic-host' / 'approval.json').read_text())
        self.assertEqual(approval['version'], '1.3.0')
        self.assertEqual(approval['publisher'], 'example-publisher')
        parked = len(self.calls)
        again, out, err = self.command(
            'update', '--root', str(self.root), '--build', str(self.build),
            '--market-commit', MARKET, '--loopback', self.loopback)
        self.assertEqual(again, 0, out)
        self.assertEqual(len(self.calls), parked)
        self.assertEqual(json.loads(out)['unchanged'][0]['name'], 'synthetic-host')
        changed = dict(moved, version='1.4.0', commit='e' * 40)
        changed['asset_url'] = changed['asset_url'].replace('v1.3.0', 'v1.4.0')
        manifest['version'] = '1.4.0'
        raw = (json.dumps(manifest, indent=2) + '\n').encode()
        (folder / 'manifest.json').write_bytes(raw)
        (folder / 'SHA256SUMS').write_bytes(
            ('%s  driver.tar.gz\n%s  manifest.json\n' % (sha(archive), sha(raw))).encode())
        self.publish(changed, folder, publisher='other-publisher')
        code, out, err = self.command(
            'update', '--root', str(self.root), '--build', str(self.build),
            '--market-commit', MARKET, '--loopback', self.loopback)
        self.assertEqual(code, 1, out)
        self.assertIn('own yes', err)
        self.assertIn('other-publisher', err)
        self.assertEqual(len(self.calls), parked)
        approval = json.loads((self.root / 'drivers' / 'synthetic-host' / 'approval.json').read_text())
        self.assertEqual(approval['version'], '1.3.0')
        self.assertEqual(approval['publisher'], 'example-publisher')
        code, out, _ = self.command(
            'update', '--root', str(self.root), '--build', str(self.build),
            '--market-commit', MARKET, '--loopback', self.loopback, '--answer', 'yes')
        self.assertEqual(code, 0, out)
        approval = json.loads((self.root / 'drivers' / 'synthetic-host' / 'approval.json').read_text())
        self.assertEqual((approval['publisher'], approval['version']), ('other-publisher', '1.4.0'))

    def test_a_redirect_off_github_is_refused(self):
        self.publish(self.package(), FIXTURES / 'good')
        base = '/%s/releases/download/v1.2.3/driver.tar.gz' % REPO
        self.route('github.com', base, 'https://evil.example/driver.tar.gz')
        code, out, _ = self.add(answer='yes')
        self.assertEqual(code, 1)
        self.assertIn('off GitHub', out)
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'drivers').exists())
        self.assertNotIn('evil.example', [host for host, _ in self.server.seen])

    def test_a_pin_is_the_yes_and_a_core_driver_is_not_fetched(self):
        package = self.package()
        self.publish(package, FIXTURES / 'good')
        pins = {'contract': 'openwiz.driver-package.v1', 'pins': [{
            'package': package, 'publisher': 'example-publisher',
            'evidence': {'bundled_version': '0.1.1'}}]}
        pin_path = self.build / 'runtime' / 'pins.json'
        pin_path.write_text(json.dumps(pins))
        pin_path.chmod(0o600)
        self.server.seen.clear()
        code, out, _ = self.add()
        self.assertEqual(code, 0, out)
        self.assertTrue((self.root / 'drivers' / 'synthetic-host' / 'driver').is_file())
        self.assertFalse(any('listings' in path for _, path in self.server.seen))
        shutil.rmtree(self.root / 'drivers')
        core = self.build / 'runtime' / 'adapters' / 'synthetic-host'
        core.mkdir(parents=True)
        (core / 'driver').write_text('#!/bin/sh\n')
        (core / 'driver').chmod(0o700)
        self.server.seen.clear()
        self.calls.clear()
        code, out, _ = self.add(answer='yes')
        self.assertEqual(code, 1)
        self.assertIn('core driver', out)
        self.assertEqual(self.server.seen, [])
        self.assertEqual(self.calls, [])
        self.assertFalse((self.root / 'drivers').exists())


if __name__ == '__main__':
    unittest.main()
