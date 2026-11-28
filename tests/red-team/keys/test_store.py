#!/usr/bin/env python3
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import loopback  # noqa: E402 -- the copy's folder is put on the path first, since -I leaves it off
import store  # noqa: E402 -- the copy's folder is put on the path first, since -I leaves it off

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
with open(os.path.join(ROOT, 'kernel', 'driver-kit', 'hosts.json'), encoding='utf-8') as f:
    HOSTS = json.load(f)
HELPER_KEY = re.compile(r'[A-Za-z0-9._~+/=-]{16,4096}')


class KeyStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loopback.guard()

    def test_holds_only_canary_keys(self):
        keys = store.load()
        self.assertEqual(set(keys), set(HOSTS))
        self.assertEqual(len(set(keys.values())), len(keys))
        for host, key in keys.items():
            self.assertRegex(key, store.CANARY)
            self.assertIn(host, key)
            self.assertTrue(HELPER_KEY.fullmatch(key), host)
        with open(store.STORE, encoding='utf-8') as f:
            self.assertEqual(json.load(f), keys)

    def test_refuses_a_store_with_a_key_that_is_not_a_canary(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ({'devin': 'sk-live-0123456789abcdef'}, {'devin': 'openwiz-canary-devin-not-a-real-key',
                                                                'extra': 1}):
                path = os.path.join(tmp, 'store.json')
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(bad, f)
                with self.assertRaises(ValueError):
                    store.load(path)

    def test_starts_on_loopback_only(self):
        with store.Store('devin') as s:
            self.assertRegex(s.origin, r'^http://127\.0\.0\.1:[0-9]+$')
            self.assertEqual(s.server.server_address[0], '127.0.0.1')

    def test_key_helper_reads_and_sends_only_the_canary(self):
        for host in HOSTS:
            with store.Store(host) as s:
                out = store.helper(s.origin, {'host': host, 'method': 'POST', 'path': '/v1/things', 'body': {'n': 1}})
            self.assertEqual(out.returncode, 0, out.stdout)
            self.assertEqual(json.loads(out.stdout), {'status': 200, 'body': {}})
            self.assertNotIn(s.key, out.stdout)
            self.assertEqual(s.log, [{'method': 'GET', 'path': store.KEY_PATH, 'gave': 'canary'},
                                     {'method': 'POST', 'path': '/v1/things', 'authorized': True, 'leaked': False}])

    def test_key_helper_gets_no_production_key_source(self):
        env = store.helper_env('http://127.0.0.1:1')
        self.assertEqual(set(env), {'OPENWIZ_HOSTKEY_TEST_ORIGIN', 'PATH'})
        self.assertFalse({h['variable'] for h in HOSTS.values()} & set(env))

    def test_guard_refuses_networks_beyond_localhost_and_spawning(self):
        with self.assertRaises(loopback.Offline):
            socket.create_connection(('192.0.2.1', 9), timeout=1)
        with self.assertRaises(loopback.Offline):
            socket.getaddrinfo('example.com', 443)
        probe = ('import socket, subprocess\n'
                 'for f in (lambda: socket.create_connection(("192.0.2.1", 9), timeout=1),\n'
                 '          lambda: socket.getaddrinfo("example.com", 443),\n'
                 '          lambda: subprocess.run(["true"])):\n'
                 '    try:\n'
                 '        f()\n'
                 '        print("reached")\n'
                 '    except Exception as e:\n'
                 '        print(type(e).__name__)\n')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'probe.py')
            with open(path, 'w', encoding='utf-8') as f:
                f.write(probe)
            out = subprocess.run([sys.executable, '-I', loopback.__file__, path], capture_output=True, text=True,
                                 env={'PATH': '/usr/bin:/bin'}, timeout=60)
        self.assertEqual(out.stdout.split(), ['Offline'] * 3, out.stderr)

    def test_copy_names_no_address_beyond_localhost(self):
        for name in sorted(os.listdir(HERE)):
            if name.endswith(('.py', '.json')) and not name.startswith('test_'):
                with open(os.path.join(HERE, name), encoding='utf-8') as f:
                    for url in re.findall(r'https?://[^\s\'"]*', f.read()):
                        self.assertRegex(url, r'^http://127\.0\.0\.1:', name)


if __name__ == '__main__':
    unittest.main()
