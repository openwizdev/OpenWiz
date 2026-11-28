#!/usr/bin/env python3
"""The fetcher copy's own test: offline, loopback only, good and tampered packages."""
import hashlib
import http.client
import json
from pathlib import Path
import socket
import subprocess
import sys
import unittest
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import loopback  # noqa: E402  (installs the guard for this whole test process)
import server  # noqa: E402


class FetcherCopy(unittest.TestCase):
    def setUp(self):
        self.copy = server.start()
        self.addCleanup(self.copy.stop)

    def get(self, path):
        with urllib.request.urlopen(self.copy.url + path, timeout=5) as response:
            return response.status, response.read()

    def test_starts_on_loopback_only(self):
        host, port = self.copy.address
        self.assertEqual(host, '127.0.0.1')
        self.assertTrue(self.copy.url.startswith('http://127.0.0.1:%d/' % port))

    def test_index_lists_every_package_without_its_label(self):
        status, body = self.get('index.json')
        self.assertEqual(status, 200)
        index = json.loads(body)
        names = {p['name'] for p in index['packages']}
        self.assertEqual(names, {p['name'] for p in server.load()['packages']})
        self.assertNotIn(b'"variant"', body)
        for package in index['packages']:
            self.assertEqual(sorted(package), ['name', 'path', 'sha256', 'version'])

    def test_good_package_matches_its_pin_and_tampered_ones_do_not(self):
        index = {p['name']: p for p in json.loads(self.get('index.json')[1])['packages']}
        for package in server.load()['packages']:
            pinned = index[package['name']]
            served = self.get(pinned['path'])[1]
            ok = hashlib.sha256(served).hexdigest() == pinned['sha256']
            self.assertEqual(server.verify(served, pinned['sha256']), ok)
            self.assertEqual(ok, package['variant'] == 'good', package['name'])
        variants = {p['variant'] for p in server.load()['packages']}
        self.assertEqual(variants, {'good', 'tampered', 'swapped-after-pin', 'truncated'})

    def test_off_host_redirect_is_served_but_never_followed(self):
        index = {p['name']: p for p in json.loads(self.get('index.json')[1])['packages']}
        conn = http.client.HTTPConnection(*self.copy.address, timeout=5)
        conn.request('GET', '/redirect/' + index['driver-good']['path'])
        response = conn.getresponse()
        self.assertEqual(response.status, 302)
        self.assertTrue(response.getheader('Location').startswith('http://fetch.invalid/'))
        conn.close()
        with self.assertRaises(urllib.error.URLError) as caught:
            self.get('redirect/' + index['driver-good']['path'])
        self.assertIsInstance(caught.exception.reason, PermissionError)

    def test_logs_every_request(self):
        self.get('index.json')
        self.assertEqual([r['path'] for r in self.copy.log], ['/index.json'])

    def test_guard_refuses_networks_beyond_localhost_and_spawning(self):
        with self.assertRaises(PermissionError):
            socket.getaddrinfo('example.com', 443)
        with self.assertRaises(PermissionError):
            socket.create_connection(('192.0.2.1', 80), timeout=1)
        with self.assertRaises(PermissionError):
            subprocess.run(['true'])
        socket.getaddrinfo('localhost', self.copy.address[1])

    def test_packages_are_synthetic(self):
        for package in server.load()['packages']:
            self.assertTrue(package['name'].startswith('driver-'))
            self.assertIn('synthetic', package['body'])


if __name__ == '__main__':
    unittest.main()
