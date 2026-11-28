#!/usr/bin/env python3
import http.client
import importlib.machinery
import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
HOSTKEY = os.path.join(HERE, 'hostkey.py')
KEY = 'synthetic-host-key-' + 'Kit0Value' * 3
PRODUCTION = 'synthetic-production-key-' + 'Kit0Value' * 3
NAMES = 'DEVIN_API_KEY or the keychain entry openwiz-devin'
NO_TEST_KEY = "the kit's fake host gave no test key"
GOOD = {'host': 'devin', 'method': 'POST', 'path': '/v3/organizations/org-syn1/sessions', 'body': {'prompt': 'hi'}}


def module(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    found = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(found)
    return found


kit = module(os.path.join(HERE, 'kit.py'), 'kit')
FAKE_TOOL = """#!/bin/sh
printf '%s\\n' "$0 $*" >> "$TOOL_LOG"
env >> "$TOOL_LOG"
[ -f "$TOOL_KEY" ] && cat "$TOOL_KEY"
exit "${TOOL_EXIT:-0}"
"""


class Helper(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.bin = os.path.join(self.folder, 'bin')
        os.mkdir(self.bin)
        for tool in ('secret-tool', 'security'):
            with open(os.path.join(self.bin, tool), 'w') as f:
                f.write(FAKE_TOOL)
            os.chmod(os.path.join(self.bin, tool), 0o700)
        self.log = os.path.join(self.folder, 'tool.log')
        self.host = self.fake()

    def fake(self, *answer, test_key=KEY):
        host = kit.FakeHost(*answer, test_key=test_key)
        self.addCleanup(host.close)
        return host

    def env(self, **more):
        env = {'PATH': self.bin + os.pathsep + '/usr/bin:/bin', 'HOME': self.folder, 'TMPDIR': self.folder,
               'TOOL_LOG': self.log, 'DEVIN_API_KEY': PRODUCTION, 'OPENWIZ_HOSTKEY_TEST_ORIGIN': self.host.origin}
        env.update(more)
        return {k: v for k, v in env.items() if v is not None}

    def run_helper(self, request, raw=None, isolated=True, **env):
        p = subprocess.run([sys.executable] + ['-I'] * isolated + [HOSTKEY], cwd=self.folder,
                           input=json.dumps(request) if raw is None else raw, env=self.env(**env),
                           capture_output=True, text=True, timeout=60)
        for text in (p.stdout, p.stderr):
            self.assertNotIn(KEY, text)
            self.assertNotIn(PRODUCTION, text)
        self.assertEqual(p.stderr, '')
        files = [os.path.join(d, n) for d, _, names in os.walk(self.folder) for n in names]
        for name in files:
            with open(name, 'rb') as f:
                data = f.read()
                self.assertNotIn(KEY.encode(), data, name)
                self.assertNotIn(PRODUCTION.encode(), data, name)
        for _, headers, _ in self.host.requests:
            self.assertNotIn(PRODUCTION, repr(headers), 'a production key reached the loopback fake')
        return p.returncode, json.loads(p.stdout, parse_constant=lambda name: self.fail('the answer is not strict '
                                                                                         'JSON: ' + name))

    def refused(self, request, why, raw=None, **env):
        code, out = self.run_helper(request, raw, **env)
        self.assertEqual((code, sorted(out)), (1, ['error', 'next']), out)
        for text in out.values():
            self.assertTrue(isinstance(text, str) and 1 <= len(text) <= 300 and '\n' not in text, out)
        self.assertIn(why, out['error'])
        self.assertEqual(self.host.requests, [], 'a refused request reached the host')
        return out

    def test_a_good_request_reaches_the_registered_host_with_the_key_only_in_its_header(self):
        code, out = self.run_helper(GOOD)
        self.assertEqual((code, out), (0, {'status': 200, 'body': {}}))
        [(line, headers, body)] = self.host.requests
        self.assertEqual(line, 'POST /v3/organizations/org-syn1/sessions HTTP/1.1')
        self.assertEqual(json.loads(body), {'prompt': 'hi'})
        self.assertEqual([v for k, v in headers if k.lower() == 'authorization'], ['Bearer ' + KEY])
        self.assertNotIn(KEY, line + body.decode() + repr([h for h in headers if h[0].lower() != 'authorization']))
        self.assertFalse(os.path.exists(self.log), 'the keychain was read though the variable was set')

    def test_get_and_delete_with_no_body_and_a_query(self):
        for method in ('GET', 'DELETE'):
            with self.subTest(method):
                self.host.requests.clear()
                code, out = self.run_helper({'host': 'devin', 'method': method, 'path': '/v1/runs/run-1?a=b&c=d'})
                self.assertEqual((code, out), (0, {'status': 200, 'body': {}}))
                self.assertEqual(self.host.requests[0][0], method + ' /v1/runs/run-1?a=b&c=d HTTP/1.1')

    def test_input_that_is_not_exactly_the_request_is_refused(self):
        cases = {'not json': 'the input is not', '[]': 'the input needs', '{"host": "devin"}': 'the input needs',
                 json.dumps(dict(GOOD, token='x')): 'the input needs', json.dumps(dict(GOOD, host=1)): 'host is not',
                 json.dumps(GOOD)[:-1] + ', "host": "devin"}': 'a key is repeated',
                 json.dumps(dict(GOOD, body=[1])): 'body is not an object',
                 json.dumps(dict(GOOD, body=None)): 'body is not an object',
                 json.dumps(GOOD)[:-2] + ', "n": NaN}}': 'the input is not',
                 json.dumps(dict(GOOD, path=7)): 'path is not a string'}
        for raw, why in cases.items():
            with self.subTest(raw):
                self.refused(None, why, raw)

    def test_a_method_outside_the_three_is_refused(self):
        for method in ('PUT', 'get', 'PATCH', 'GET ', 'CONNECT', 1):
            with self.subTest(method):
                self.refused(dict(GOOD, method=method), 'method is not GET, POST or DELETE')

    def test_a_host_not_in_the_registry_is_refused(self):
        for host in ('nothost', 'Devin', 'devin ', '', 'https://api.devin.ai', '__proto__'):
            with self.subTest(host):
                self.refused(dict(GOOD, host=host), 'host is not in kernel/driver-kit/hosts.json')

    def test_each_path_escape_is_refused_before_any_network_call(self):
        cases = {'v1/runs': 'not absolute', '': 'not absolute', 'https://evil.example/v1': 'not absolute',
                 '//evil.example/v1': '//', '/v1//runs': '//', '/v1/%2F%2Fevil.example': '//',
                 '/v1/../x': '..', '/v1/..': '..', '/v1/%2e%2e/x': '..', '/v1\\x': 'backslash', '/v1/%5Cx': 'backslash',
                 '/v1/user@evil.example': '@', '/v1/%40x': '@', '/v1#frag': '#', '/v1/%23x': '#',
                 '/https:/evil.example': 'a scheme or a port', '/v1:8443/x': 'a scheme or a port',
                 '/v1/%3Ax': 'a scheme or a port', '/v1\r\nX-Evil: 1': 'control character',
                 '/v1\nx': 'control character', '/v1\x00': 'control character', '/v1\x7f': 'control character',
                 '/v1/%0d%0ax': 'control character', '/v1/%00': 'control character', '/v1 x': 'outside',
                 '/v1/\u00e9': 'outside', '/v1/<x>': 'outside', '/v1/%': 'percent', '/v1/%zz': 'percent',
                 '/v1/%252e%252e': 'encoded twice', '/v1/%EF%BC%8F%EF%BC%8F': 'outside printable ASCII',
                 '/v1/%C3%A9': 'outside printable ASCII', '/v1/%ff': 'percent', '/' + 'a' * 2048: 'longer'}
        for path, why in cases.items():
            with self.subTest(path):
                self.refused(dict(GOOD, path=path), why)

    def test_the_test_override_is_honoured_only_for_loopback_http_with_a_port(self):
        bad = ['http://127.0.0.2:%d', 'https://127.0.0.1:%d', 'http://localhost:%d', 'http://[::1]:%d',
               'http://127.0.0.1', 'http://127.0.0.1:0', 'http://127.0.0.1:65536', 'http://127.0.0.1:0%d',
               'http://127.0.0.1:%d/', 'http://127.0.0.1:%d/x', 'http://u@127.0.0.1:%d', ' http://127.0.0.1:%d',
               'http://127.0.0.1:%d\n', 'HTTP://127.0.0.1:%d', 'http://127.0.0.1.evil.example:%d', '']
        port = int(self.host.origin.rpartition(':')[2])
        for value in bad:
            value = value % port if '%d' in value else value
            with self.subTest(value):
                self.refused(GOOD, 'OPENWIZ_HOSTKEY_TEST_ORIGIN is not http://127.0.0.1:<port>',
                             OPENWIZ_HOSTKEY_TEST_ORIGIN=value)
                self.assertFalse(os.path.exists(self.log), 'the keychain was read')

    def test_a_redirect_comes_back_as_its_status_and_is_never_followed(self):
        target = self.fake()
        for status in (301, 302, 303, 307, 308):
            with self.subTest(status):
                hop = self.fake(status, [('Location', target.origin + '/v1/stolen')], b'')
                code, out = self.run_helper(GOOD, OPENWIZ_HOSTKEY_TEST_ORIGIN=hop.origin)
                self.assertEqual((code, out), (0, {'status': status, 'body': None}))
                self.assertEqual(len(hop.requests), 1)
        self.assertEqual(target.requests, [], 'the helper followed a redirect')

    def test_the_helper_ignores_proxy_variables(self):
        proxy = self.fake()
        code, out = self.run_helper(GOOD, HTTP_PROXY=proxy.origin, HTTPS_PROXY=proxy.origin, ALL_PROXY=proxy.origin,
                                    http_proxy=proxy.origin, https_proxy=proxy.origin, NO_PROXY='', no_proxy='')
        self.assertEqual((code, len(self.host.requests), proxy.requests), (0, 1, []))

    def test_an_answer_that_holds_the_key_is_dropped(self):
        bodies = [json.dumps({'echo': 'Bearer ' + KEY}).encode(), ('<p>' + KEY + '</p>').encode(),
                  json.dumps({'k': KEY}, ensure_ascii=True).replace('s', '\\u0073').encode(),
                  json.dumps({KEY: 1}).encode()]
        for body in bodies:
            with self.subTest(body):
                host = self.fake(500, [], body)
                code, out = self.run_helper(GOOD, OPENWIZ_HOSTKEY_TEST_ORIGIN=host.origin)
                self.assertEqual(code, 1)
                self.assertIn("the host's answer held the key", out['error'])

    def test_under_the_override_no_production_key_is_ever_read(self):
        for env in ({}, {'DEVIN_API_KEY': None}, {'OPENWIZ_HOSTKEY_TEST_KEY': KEY}):
            with self.subTest(env):
                bare = self.fake(test_key=None)
                out = self.refused(GOOD, NO_TEST_KEY, OPENWIZ_HOSTKEY_TEST_ORIGIN=bare.origin, **env)
                self.assertEqual(bare.requests, [])
                self.assertFalse(os.path.exists(self.log), 'the keychain was read under the test override')
        code, out = self.run_helper(GOOD)
        self.assertEqual([v for k, v in self.host.requests[0][1] if k == 'Authorization'], ['Bearer ' + KEY])

    def test_a_request_that_holds_the_key_is_refused_before_it_is_sent(self):
        quoted = KEY.replace('s', '%73')
        cases = [dict(GOOD, path='/v1/' + KEY), dict(GOOD, path='/v1?k=' + KEY), dict(GOOD, path='/v1/' + quoted),
                 dict(GOOD, body={'k': KEY}), dict(GOOD, body={KEY: 1}), dict(GOOD, body={'k': ['x' + KEY + 'y']})]
        for request in cases:
            with self.subTest(request):
                self.refused(request, 'the request holds the key')

    def test_a_body_strict_json_cannot_hold_comes_back_null_with_its_status(self):
        for body in (b'{"n": 1e400}', b'[-1e999]'):
            with self.subTest(body):
                host = self.fake(200, [], body)
                self.assertEqual(self.run_helper(GOOD, OPENWIZ_HOSTKEY_TEST_ORIGIN=host.origin),
                                 (0, {'status': 200, 'body': None}))

    def test_native_tls_configuration_from_the_environment_never_reaches_the_helper(self):
        conf = os.path.join(self.folder, 'one13.cnf')
        with open(conf, 'w') as f:
            f.write('openssl_conf = c\n[c]\nssl_conf = s\n[s]\nsystem_default = d\n[d]\n'
                    'Ciphersuites = TLS_AES_128_GCM_SHA256\n')
        probe = ('import importlib.machinery as m, importlib.util as u, sys\n'
                 'if sys.argv[1] == "helper":\n'
                 '    s = u.spec_from_loader("hostkey", m.SourceFileLoader("hostkey", %r))\n'
                 '    s.loader.exec_module(u.module_from_spec(s))\n'
                 'import ssl\nprint(len([c for c in ssl.create_default_context().get_ciphers()'
                 ' if c["protocol"] == "TLSv1.3"]))\n' % HOSTKEY)
        seen = {}
        for who in ('control', 'helper'):
            p = subprocess.run([sys.executable, '-I', '-c', probe, who], capture_output=True, text=True, timeout=60,
                               env=dict(self.env(), OPENSSL_CONF=conf, OPENSSL_MODULES=self.folder,
                                        OPENSSL_ENGINES=self.folder, SSLKEYLOGFILE=os.path.join(self.folder, 'k')))
            self.assertEqual(p.returncode, 0, p.stderr)
            seen[who] = int(p.stdout)
        self.assertEqual(seen['control'], 1, 'the planted configuration does not work')
        self.assertGreater(seen['helper'], 1, 'the helper took the planted TLS 1.3 cipher suites')

    def test_a_non_json_answer_comes_back_as_a_null_body(self):
        for body in (b'', b'not json', b'{"n": NaN}', b'\xff'):
            with self.subTest(body):
                host = self.fake(404, [], body)
                self.assertEqual(self.run_helper(GOOD, OPENWIZ_HOSTKEY_TEST_ORIGIN=host.origin),
                                 (0, {'status': 404, 'body': None}))

    def test_an_unreachable_host_is_an_error_without_the_key(self):
        port = int(self.host.origin.rpartition(':')[2])
        self.host.close()
        self.refused(GOOD, 'could not reach the host', OPENWIZ_HOSTKEY_TEST_ORIGIN='http://127.0.0.1:%d' % port)

    def test_a_key_outside_the_supported_format_is_refused_without_its_value(self):
        for bad in (KEY + '\n', KEY + ' x', 'a\rb', KEY + '\t', KEY + '\u00e9', 'short-key-15chr', KEY + '"q',
                    KEY + '\\', KEY + ':', 'x' * 4097):
            with self.subTest(repr(bad)):
                host = self.fake(test_key=bad)
                code, out = self.run_helper(GOOD, OPENWIZ_HOSTKEY_TEST_ORIGIN=host.origin)
                self.assertEqual(code, 1)
                self.assertIn('is not a key of 16 to 4096 letters, digits or ._~+/=-', out['error'])
                self.assertNotIn(bad.strip(), json.dumps(out))
                self.assertEqual(self.host.requests, [])

    def test_a_key_that_fits_inside_the_helpers_own_texts_is_never_printed(self):
        for key in ('held', 'the'):
            with self.subTest(key):
                host = self.fake(200, [], json.dumps({'echo': key}).encode(), test_key=key)
                p = subprocess.run([sys.executable, '-I', HOSTKEY], input=json.dumps(GOOD), capture_output=True,
                                   text=True, timeout=60, env=self.env(DEVIN_API_KEY=key, OPENWIZ_HOSTKEY_TEST_ORIGIN=
                                                                       host.origin))
                self.assertEqual(p.returncode, 1)
                self.assertNotIn(key, p.stdout)

    def test_every_output_path_including_its_fallbacks_holds_no_key(self):
        hostkey = module(HOSTKEY, 'hostkey')
        for keys in (['the-answer-held-the-key'], ['the answer held the key'], ['helper did not print']):
            with self.subTest(keys):
                text, code = hostkey.render({'status': 200, 'body': {'k': keys[0]}}, keys)
                self.assertEqual(code, 1)
                self.assertFalse(any(k in text for k in keys), text)
                self.assertEqual(sorted(json.loads(text)), ['error', 'next'])
        for keys in (['{'], ['e'], ['"']):
            with self.subTest(keys):
                self.assertEqual(hostkey.render({'error': 'x', 'next': 'y'}, keys), ('', 1))

    def test_the_helper_runs_only_in_isolated_mode(self):
        code, out = self.run_helper(GOOD, isolated=False)
        self.assertEqual(code, 1)
        self.assertIn('python3 -I', out['error'] + out['next'])
        self.assertEqual(self.host.requests, [])

    def test_deeply_nested_json_refuses_cleanly_without_recursion_error(self):
        hostkey = module(HOSTKEY, 'hostkey')
        hosts = hostkey.registry()
        deep = '[' * 2000 + ']' * 2000

        with self.assertRaises(hostkey.Refused):
            hostkey.read_request(deep, hosts)

        self.assertEqual(hostkey.answer(200, deep.encode('ascii'), KEY), {'status': 200, 'body': None})

        key_deep = ('[' * 2000 + '"' + KEY + '"' + ']' * 2000).encode('ascii')
        with self.assertRaises(hostkey.Refused):
            hostkey.answer(200, key_deep, KEY)

        deep_reg = os.path.join(self.folder, 'deep-hosts.json')
        with open(deep_reg, 'w') as f:
            f.write(deep)
        with self.assertRaises(hostkey.Refused):
            hostkey.registry(deep_reg)

        deep_host = self.fake(200, [], deep.encode('ascii'))
        code, out = self.run_helper(GOOD, OPENWIZ_HOSTKEY_TEST_ORIGIN=deep_host.origin)
        self.assertEqual(code, 0)
        self.assertEqual(out, {'status': 200, 'body': None})

        code, out = self.run_helper(None, raw=deep)
        self.assertEqual(code, 1)
        self.assertEqual(out['error'], 'the input is not one JSON object')

        deep_dict = {}
        cur = deep_dict
        for _ in range(1500):
            nxt = {}
            cur['a'] = nxt
            cur = nxt
        with self.assertRaises(hostkey.Refused):
            hostkey.screen({'path': '/v1', 'body': deep_dict}, KEY)
        with self.assertRaises(hostkey.Refused):
            hostkey.send(self.host.origin, 'POST', '/v1', deep_dict, KEY)


class Keychain(unittest.TestCase):
    def setUp(self):
        Helper.setUp(self)
        self.hostkey = module(HOSTKEY, 'hostkey')
        self.entry = self.hostkey.registry()['devin']
        with open(os.path.join(self.folder, 'key'), 'w') as f:
            f.write(KEY + '\n')

    fake = Helper.fake

    def lookup(self, platform='linux', tool_exit=0, key_file='key', **env):
        trusted = os.path.join(self.folder, 'trusted')
        os.makedirs(trusted, exist_ok=True)
        for tool in ('secret-tool', 'security'):
            with open(os.path.join(trusted, tool), 'w') as f:
                f.write(FAKE_TOOL.replace('"$TOOL_LOG"', repr(self.log)).replace('"$TOOL_KEY"', repr(
                    os.path.join(self.folder, key_file))).replace('${TOOL_EXIT:-0}', str(tool_exit)))
            os.chmod(os.path.join(trusted, tool), 0o700)
        environ = {'PATH': self.bin + os.pathsep + '/usr/bin:/bin', 'HOME': self.folder, 'LANG': 'C.UTF-8',
                   'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/synthetic/bus', 'XDG_RUNTIME_DIR': '/synthetic/run',
                   'PLANTED': 'from the driver', 'LD_PRELOAD': '/synthetic/planted.so'}
        environ.update(env)
        old, tools = sys.platform, dict(self.hostkey.TOOLS)
        sys.platform = platform
        self.hostkey.TOOLS.update({p: [os.path.join(trusted, argv[0].rpartition('/')[2])] + argv[1:]
                                   for p, argv in tools.items()})
        try:
            return self.hostkey.find_key(self.entry, {k: v for k, v in environ.items() if v is not None})
        finally:
            sys.platform = old
            self.hostkey.TOOLS.update(tools)

    def tool_calls(self):
        if not os.path.exists(self.log):
            return ''
        with open(self.log) as f:
            return f.read()

    def test_the_variable_wins_and_no_tool_runs(self):
        self.assertEqual(self.lookup(DEVIN_API_KEY='from-the-variable'), 'from-the-variable')
        self.assertEqual(self.tool_calls(), '')

    def test_an_empty_variable_reads_the_keychain_from_its_trusted_path_with_a_minimal_environment(self):
        hijack = {'PATH': self.bin, 'TOOL_LOG': self.log, 'TOOL_KEY': os.path.join(self.folder, 'key')}
        old = sys.platform
        sys.platform = 'linux'
        try:
            self.hostkey.find_key(self.entry, dict(hijack, DEVIN_API_KEY=''))
        except self.hostkey.Refused:
            pass
        finally:
            sys.platform = old
        self.assertEqual(self.tool_calls(), '', 'a keychain tool found on the caller\'s PATH ran')
        allowed = {'linux': {'PATH', 'HOME', 'LANG', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR'},
                   'darwin': {'PATH', 'HOME', 'LANG'}}
        self.assertEqual(self.hostkey.TOOLS, {'linux': ['/usr/bin/secret-tool', 'lookup', 'service'],
                                              'darwin': ['/usr/bin/security', 'find-generic-password', '-w', '-s']})
        for platform, argv in (('linux', 'secret-tool lookup service openwiz-devin'),
                               ('darwin', 'security find-generic-password -w -s openwiz-devin')):
            with self.subTest(platform):
                os.path.exists(self.log) and os.remove(self.log)
                self.assertEqual(self.lookup(platform, DEVIN_API_KEY=''), KEY)
                calls = self.tool_calls().splitlines()
                self.assertEqual(calls[0], os.path.join(self.folder, 'trusted', argv))
                names = {line.partition('=')[0] for line in calls[1:]} - {'PWD', 'SHLVL', '_', 'OLDPWD'}
                self.assertEqual(names, allowed[platform])
                self.assertIn('PATH=/usr/bin:/bin', calls)
                self.assertNotIn(KEY, '\n'.join(calls[:1] + [c for c in calls[1:] if not c.startswith('PATH=')]))

    def test_a_failed_or_empty_keychain_is_a_missing_key(self):
        for kw in ({'tool_exit': 1}, {'key_file': 'none'}):
            with self.subTest(kw):
                with self.assertRaises(self.hostkey.Refused) as caught:
                    self.lookup(**kw)
                self.assertIn(NAMES, ' '.join(caught.exception.args))

    def test_under_the_test_override_neither_production_source_is_read(self):
        bare, serving = self.fake(test_key=None), self.fake()
        for env in ({}, {'DEVIN_API_KEY': PRODUCTION}, {'OPENWIZ_HOSTKEY_TEST_KEY': KEY}):
            with self.subTest(env):
                with self.assertRaises(self.hostkey.Refused) as caught:
                    self.lookup(OPENWIZ_HOSTKEY_TEST_ORIGIN=bare.origin, **env)
                self.assertIn(NO_TEST_KEY, caught.exception.args[0])
                self.assertEqual(self.tool_calls(), '')
        self.assertEqual(self.lookup(OPENWIZ_HOSTKEY_TEST_ORIGIN=serving.origin, DEVIN_API_KEY=PRODUCTION), KEY)
        self.assertEqual(self.tool_calls(), '')

    def test_tls_is_verified_with_the_system_defaults_and_ignores_cert_variables(self):
        cert, key = os.path.join(self.folder, 'c.pem'), os.path.join(self.folder, 'k.pem')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', key, '-out', cert,
                        '-days', '1', '-subj', '/CN=127.0.0.1', '-addext', 'subjectAltName=IP:127.0.0.1'],
                       check=True, capture_output=True, timeout=60)
        host = self.fake()
        host.server.handle_error = lambda *a: None
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        host.server.socket = tls.wrap_socket(host.server.socket, server_side=True)
        port = host.server.server_address[1]
        trusted = http.client.HTTPSConnection('127.0.0.1', port, timeout=30,
                                              context=ssl.create_default_context(cafile=cert))
        trusted.request('GET', '/control')
        self.assertEqual(trusted.getresponse().status, 200, 'the TLS fake does not work')
        trusted.close()
        saved = {k: os.environ.get(k) for k in ('SSL_CERT_FILE', 'SSL_CERT_DIR')}
        os.environ.update(SSL_CERT_FILE=cert, SSL_CERT_DIR=self.folder)
        try:
            with self.assertRaises(self.hostkey.Refused) as caught:
                self.hostkey.send('https://127.0.0.1:%d' % port, 'GET', '/v1', None, KEY)
        finally:
            for k, v in saved.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.assertIn('TLS', caught.exception.args[0])
        self.assertEqual([r[0] for r in host.requests], ['GET /control HTTP/1.1'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
