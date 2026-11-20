#!/usr/bin/env python3
"""#2220 baseline: planted synthetic credentials at the existing App and access
refusal, revocation and expiry boundaries (#1105, #1107). Assessment proof only.

Each case runs the existing tool through its public entry point against a
recording provider: `access.execute` with the #1107 recording fixture, and the
#1105 `setup.py check` program against a loopback GitHub App API and a fake
`gh`. It proves that a refused, revoked or expired case verifies nothing, makes
no write, sends each planted credential only to its own provider, and leaves no
credential in output, errors or state. Synthetic values only; no network.

  python3 -I tools/install/tests/public-release-security/baseline/test_baseline.py
"""
import base64
import binascii
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import http.client
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / 'tools/install/access'))
import access  # noqa: E402
sys.path.insert(0, str(ROOT / 'tools/install/access/fixtures'))
from provider import Recording, credentials, jwt, selected  # noqa: E402

OWNER_EMAIL = 'owner@example.invalid'
# Planted values: unmistakable, synthetic, never a real credential.
PLANTED_API = 'SyntheticPlantedProviderToken2220aaaaaaaaaaaaaaaa'
PLANTED_INSTALLATION = 'ghs_SyntheticPlantedInstallation2220bbbbbbbbbb'
PLANTED_PERSONAL = 'gho_SyntheticPlantedPersonal2220cccccccccccccccc'
REPO = 'synthetic-owner/synthetic-consumer'
PROFILE = {'metadata': 'read', 'contents': 'write', 'issues': 'write',
           'pull_requests': 'write', 'checks': 'read', 'actions': 'read'}
VERIFIED = ('access_cloudflare_verified', 'access_tailscale_verified')


def files_text(folder):
    """Every byte under FOLDER, as text, so a planted value anywhere is found."""
    return ''.join(p.read_bytes().decode('utf-8', 'replace') for p in sorted(Path(folder).rglob('*')) if p.is_file())


class Planted(Recording):
    """The #1107 recording provider, also keeping each request's headers and
    body, and answering 401 from the provider API once its token is revoked."""

    def __init__(self, p, secrets):
        super().__init__(p, secrets)
        self.seen = []
        self.revoked = False

    def request(self, method, url, headers, body=None):
        self.seen.append((method, url, dict(headers), body or b''))
        if self.revoked and urlsplit(url).netloc in ('api.cloudflare.com', 'api.tailscale.com'):
            return 401, b'{"synthetic":"token revoked"}'
        return super().request(method, url, headers, body)


class AccessBoundaries(unittest.TestCase):
    """#1107: refused, revoked and expired phone-access checks."""

    def run_case(self, provider, change):
        with tempfile.TemporaryDirectory(prefix='openwiz-2220-access-') as folder:
            root = Path(folder)
            p, secrets = selected(provider), credentials(provider)
            secrets['api_token'] = PLANTED_API
            recording = Planted(p, secrets)
            state = root / 'state'
            recording.owner_report = lambda: {'schema': 'openwiz.setup.v1',
                                              'operations': access.store.Store(str(state)).read()['operations']}
            change(recording, secrets)
            for name, value in (('plan.json', p), ('secrets.json', secrets)):
                (root / name).write_text(json.dumps(value))
                (root / name).chmod(0o600)
            args = ['configure', '--state-dir', str(state), '--plan', str(root / 'plan.json')]
            stdout, stderr = io.StringIO(), io.StringIO()
            error, result = '', None
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    operation = access.execute(args, http=recording, local=recording.local)['operation']
                    self.assertEqual(recording.seen, [], 'the preview reads no provider')
                    result = access.execute(args + ['--yes', '--operation', operation['operation_id'],
                                                    '--secrets', str(root / 'secrets.json')],
                                            http=recording, local=recording.local)
                except Exception:  # Capture streams even when either call raises.
                    error = traceback.format_exc()
            saved = access.store.Store(str(state)).read()
            leaked = json.dumps(result) + error + stdout.getvalue() + stderr.getvalue() + files_text(state)
            return p, secrets, recording, result, error, saved, leaked

    def assert_confined(self, p, secrets, recording, saved, leaked):
        # Nothing verified, nothing applied: the operation stays uncertain.
        self.assertNotIn(saved['observations']['remote_access']['code'], VERIFIED)
        self.assertEqual([o['phase'] for o in saved['operations']], ['uncertain'])
        api_host = 'api.' + p['provider'] + '.com'
        validate = '/api/v2/tailnet/' + p.get('tailnet', '') + '/acl/validate'
        for method, url, headers, body in recording.seen:
            parts = urlsplit(url)
            # No write: reads only, plus Tailscale's current-policy test.
            self.assertTrue(method == 'GET' or (method, parts.netloc, parts.path) == ('POST', api_host, validate),
                            f'{method} {url}')
            text = url + json.dumps(headers) + body.decode('utf-8', 'replace')
            for label, value in secrets.items():
                if value not in text:
                    continue
                if label == 'api_token':
                    allowed = parts.netloc == api_host and headers.get('Authorization') == 'Bearer ' + value
                else:
                    allowed = parts.netloc == p['host'] and headers.get('Cookie') == 'CF_Authorization=' + value
                self.assertTrue(allowed, f'{label} sent to {parts.netloc}')
                self.assertEqual(text.count(value), 1, f'{label} sent once per request')
        for label, value in secrets.items():
            self.assertFalse(value in leaked, f'{label} reached output, an error or state')

    def test_refused_revoked_and_expired_routes_verify_nothing_and_confine_credentials(self):
        past = '2020-01-01T00:00:00Z'
        foreign_open = [{'action': 'accept', 'src': ['*'], 'dst': ['100.100.100.10:443']}]
        cases = [
            # (provider, case, change, code): codes from the setup report's table:
            # refused = owner-only access or refusal
            # not proved; expired = account, session or device authorization.
            ('cloudflare', 'API token revoked', lambda r, s: setattr(r, 'revoked', True), 'access_expired'),
            ('cloudflare', 'anonymous request reaches OpenWiz', lambda r, s: r.leak.add('anonymous'), 'access_refused'),
            ('cloudflare', 'expired session reaches OpenWiz', lambda r, s: r.leak.add('expired'), 'access_refused'),
            ('cloudflare', 'foreign identity reaches OpenWiz', lambda r, s: r.leak.add('foreign'), 'access_refused'),
            ('cloudflare', 'owner session expired',
             lambda r, s: s.update(owner=jwt(OWNER_EMAIL, 1_000_000_000)), 'access_expired'),
            ('tailscale', 'API token revoked', lambda r, s: setattr(r, 'revoked', True), 'access_expired'),
            ('tailscale', 'device key expired', lambda r, s: r.device.update(expires=past), 'access_expired'),
            ('tailscale', 'device approval revoked', lambda r, s: r.device.update(authorized=False), 'access_refused'),
            ('tailscale', 'node expired on this host', lambda r, s: r.status['Self'].update(Expired=True), 'access_expired'),
            ('tailscale', 'Funnel exposes the route', lambda r, s: r.serve.update(AllowFunnel={
                'engine.synthetic.ts.net:443': True}), 'access_refused'),
            ('tailscale', 'policy admits everyone', lambda r, s: r.acl.update(acls=foreign_open), 'access_refused'),
        ]
        self.assertEqual(len(cases), 11)
        for provider, name, change, code in cases:
            with self.subTest(provider=provider, case=name):
                p, secrets, recording, result, error, saved, leaked = self.run_case(provider, change)
                self.assertEqual(error, '', 'a refusal is a result, never a crash')
                self.assertEqual(result['observation']['code'], code)
                self.assertGreater(len(recording.seen) + len(recording.calls), 0, 'the refusal came from a provider or local read')
                self.assert_confined(p, secrets, recording, saved, leaked)

    def test_provider_answers_the_tool_cannot_parse_fail_closed_without_leaking(self):
        # Unknown stays unknown even when the tool stops on an answer it cannot
        # handle: no verification, no applied operation, no credential in the
        # result, the error text or state. (Assessed as finding B-A3.)
        def deep(r, s):
            original = r.request

            def request(method, url, headers, body=None):
                if url.endswith('/acl'):
                    r.seen.append((method, url, dict(headers), body or b''))
                    return 200, b'[' * 100_000 + b']' * 100_000
                return original(method, url, headers, body)
            r.request = request

        def truncated(r, s):
            original = r.request

            def request(method, url, headers, body=None):
                if url.endswith('/acl'):
                    r.seen.append((method, url, dict(headers), body or b''))
                    raise http.client.IncompleteRead(b'{"acls":')
                return original(method, url, headers, body)
            r.request = request
        cases = [
            ('device expiry outside the representable range',
             lambda r, s: r.device.update(expires='0001-01-01T00:59:59+01:00')),
            ('deeply nested policy answer', deep),
            ('truncated policy answer', truncated),
        ]
        for name, change in cases:
            with self.subTest(case=name):
                p, secrets, recording, result, error, saved, leaked = self.run_case('tailscale', change)
                if result is not None:
                    self.assertNotIn(result['observation']['code'], VERIFIED)
                self.assert_confined(p, secrets, recording, saved, leaked)


class GitHub(BaseHTTPRequestHandler):
    """A loopback GitHub App API recording every request. `server.app` steers it."""

    def log_message(self, *_args):
        pass

    def answer(self, status, value, link=None):
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        if link is not None:
            self.send_header('Link', link)
        self.end_headers()
        self.wfile.write(data)

    def handle_one(self, method):
        size = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(size).decode() if size else ''
        app = self.server.app
        self.server.seen.append((method, self.path, dict(self.headers), body))
        if app['key_rejected']:
            return self.answer(401, {'message': 'synthetic: bad credentials'})
        if method == 'GET' and self.path == '/app':  # the setup check's App-owner read (#606 review R3)
            return self.answer(200, {'id': 1001, 'owner': {'login': 'synthetic-owner'}})
        if method == 'GET' and self.path == '/app/installations':
            # #2857: with a second page, GitHub's rel="next" link points to it.
            link = (f'<http://127.0.0.1:{self.server.server_port}/app/installations?page=2>; rel="next"'
                    if app['page_2'] is not None else None)
            return self.answer(200, app['installations'], link)
        if method == 'GET' and self.path == '/app/installations?page=2' and app['page_2'] is not None:
            return self.answer(200, app['page_2'])
        if method == 'POST' and self.path == '/app/installations/2002/access_tokens':
            if not any(i['id'] == 2002 for i in app['installations'] + (app['page_2'] or [])):
                return self.answer(404, {'message': 'synthetic: not found'})
            if app['wrong_repository']:
                return self.answer(422, {'message': 'synthetic: no access'})
            asked = json.loads(body)
            return self.answer(201, dict({'token': PLANTED_INSTALLATION, 'expires_at': app['expires_at'],
                                          'permissions': asked['permissions'],
                                          'repositories': [{'full_name': REPO}]}, **app['mint']))
        return self.answer(404, {'message': 'synthetic: unexpected route'})

    def do_GET(self):
        self.handle_one('GET')

    def do_POST(self):
        self.handle_one('POST')


# The agents' own login, separate from the App: reads `gh api user|repos/...`,
# and records its arguments and whether it was handed anything but the planted
# personal token.
FAKE_GH = r'''#!PYTHON
import json, os, re, sys
material = json.dumps(dict(os.environ)) + json.dumps(sys.argv[1:])
personal_matches = os.environ.get('GH_TOKEN') == __PERSONAL__
app_absent = (not any(marker in material for marker in __APP_MARKERS__)
              and re.search(r'ey[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+', material) is None)
with open(os.environ['SYNTHETIC_CALLS'], 'a') as calls:
    calls.write(json.dumps({'argv': sys.argv[1:], 'env': sorted(k for k in os.environ
                            if any(w in k for w in ('TOKEN', 'KEY', 'JWT', 'AUTH'))),
                            'personal_token_matches': personal_matches,
                            'app_material_absent': app_absent}) + '\n')
if not personal_matches:
    sys.exit(4)
if sys.argv[1:] == ['api', 'user']:
    print(json.dumps({'login': 'synthetic-agent', 'type': 'User'}))
elif sys.argv[1:] == ['api', 'repos/REPO']:
    print(json.dumps({'full_name': 'REPO', 'permissions': {'pull': True, 'push': True}}))
else:
    sys.exit(1)
'''


class AppBoundaries(unittest.TestCase):
    """#1105: the setup check's App connection, beside the agents' own login."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='openwiz-2220-app-')
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        app_dir = self.state / 'service/app'
        app_dir.mkdir(parents=True, mode=0o700)
        (self.state / 'service').chmod(0o700)
        subprocess.run(['/usr/bin/openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                        '-out', str(app_dir / 'private-key.pem')], check=True, capture_output=True)
        (app_dir / 'private-key.pem').chmod(0o600)
        self.key = (app_dir / 'private-key.pem').read_text()
        self.public_key = self.root / 'app-public.pem'
        subprocess.run(['/usr/bin/openssl', 'pkey', '-in', str(app_dir / 'private-key.pem'),
                        '-pubout', '-out', str(self.public_key)], check=True, capture_output=True)
        (app_dir / 'app.json').write_text('{"app_id":1001}')
        (app_dir / 'app.json').chmod(0o600)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        app_markers = [PLANTED_INSTALLATION, *self.key.splitlines()]
        fake = (FAKE_GH.replace('PYTHON', sys.executable).replace('REPO', REPO)
                .replace('__PERSONAL__', repr(PLANTED_PERSONAL))
                .replace('__APP_MARKERS__', repr(app_markers)))
        (self.bin / 'gh').write_text(fake)
        (self.bin / 'gh').chmod(0o700)
        self.calls = self.root / 'calls.jsonl'
        self.server = HTTPServer(('127.0.0.1', 0), GitHub)
        self.server.seen = []
        self.server.app = None
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.outputs = ''
        prepare = ['prepare', '--repository', REPO, '--project', 'prj_synthetic', '--operator', 'synthetic-owner',
                   '--service-issue', '7', '--answer-thread', 'thr_synthetic_answer', '--harness', 'claude-code',
                   '--model', 'synthetic-model', '--effort', 'high']
        proposal = json.loads(self.tool(*prepare).stdout)
        self.assertEqual(self.tool(*prepare, '--yes', '--operation', proposal['operation_id']).returncode, 0)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.temp.cleanup()

    def tool(self, *args):
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(ROOT / 'tools/install/setup/setup.py'), *args,
             '--state-dir', str(self.state)],
            cwd=self.root, capture_output=True, text=True, timeout=60,
            env={'PATH': f'{self.bin}:/usr/bin:/bin', 'HOME': str(self.root), 'GH_TOKEN': PLANTED_PERSONAL,
                 'SYNTHETIC_CALLS': str(self.calls)})
        self.outputs += result.stdout + result.stderr
        return result

    def scenario(self, **changes):
        app = {'key_rejected': False, 'wrong_repository': False, 'mint': {}, 'page_2': None,
               'expires_at': '2099-01-01T00:00:00Z',
               'installations': [{'id': 2002, 'app_id': 1001, 'account': {'login': 'synthetic-owner'},
                                  'permissions': dict(PROFILE), 'repository_selection': 'selected',
                                  'suspended_at': None}]}
        app.update(changes)
        self.server.app = app
        self.server.seen.clear()

    def check(self):
        result = self.tool('check', '--api-base', f'http://127.0.0.1:{self.server.server_port}')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)['results']

    def assert_app_identity(self, authorization):
        self.assertTrue(authorization.startswith('Bearer '), 'App JWT uses Bearer authentication')
        parts = authorization[7:].split('.')
        self.assertEqual(len(parts), 3, 'App JWT has a header, claims and signature')
        try:
            decoded = [base64.b64decode(p + '=' * (-len(p) % 4), altchars=b'-_', validate=True)
                       for p in parts]
            header, claims = [json.loads(p) for p in decoded[:2]]
        except (binascii.Error, ValueError):
            self.fail('App JWT contains valid base64url and JSON')
        self.assertEqual(header, {'alg': 'RS256', 'typ': 'JWT'})
        self.assertIsInstance(claims, dict)
        self.assertEqual(claims.get('iss'), '1001', 'App JWT names the configured App issuer')
        signature = self.root / 'app-signature.bin'
        signature.write_bytes(decoded[2])
        verified = subprocess.run(
            ['/usr/bin/openssl', 'dgst', '-sha256', '-verify', str(self.public_key),
             '-signature', str(signature)], input=(parts[0] + '.' + parts[1]).encode('ascii'),
            capture_output=True, timeout=10)
        self.assertEqual(verified.returncode, 0, 'App JWT signature matches the generated App key')

    def test_refused_revoked_and_expired_app_connections_keep_identities_apart(self):
        state_file = self.state / 'setup/state.json'

        def first(app):
            return app['installations'][0]

        def owner_on_page_2(app):
            # #2857 (C-G2): a full first page of other accounts' installations.
            others = [dict(first(app), id=3000 + n, account={'login': f'synthetic-other-{n}'}) for n in range(30)]
            expiry = datetime.fromtimestamp(time.time() + 1800, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            app.update(page_2=[first(app)], installations=others, expires_at=expiry)
        cases = [
            # (case, change to the API, expected App code, token requests)
            ('installation removed after it was recorded',
             lambda app: app.update(installations=[]), 'app_revoked', 0),
            ('App key rejected or expired', lambda app: app.update(key_rejected=True), 'app_key_rejected', 0),
            ('installation suspended',
             lambda app: first(app).update(suspended_at='2026-11-01T00:00:00Z'), 'app_suspended', 0),
            ('installed on every repository',
             lambda app: first(app).update(repository_selection='all'), 'app_all_repositories', 0),
            ('chosen repository not granted', lambda app: app.update(wrong_repository=True), 'app_wrong_repository', 1),
            ('minted token already expired',
             lambda app: app.update(expires_at='2020-01-01T00:00:00Z'), 'app_token_unusable', 1),
            ('minted token outlives an hour',
             lambda app: app.update(expires_at='2099-01-01T00:00:00Z'), 'app_token_unusable', 1),
            ('owner installation on page 2, not revoked', owner_on_page_2, 'app_verified', 1),
        ]
        self.assertEqual(len(cases), 8)
        for name, change, code, mints in cases:
            with self.subTest(case=name):
                value = json.loads(state_file.read_text())
                value['app'] = {'app_id': 1001, 'installation_id': 2002}  # recorded by an earlier check
                state_file.write_text(json.dumps(value))
                self.scenario()
                change(self.server.app)
                self.calls.write_text('')
                results = self.check()
                gh_calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                self.assertTrue(all(c['personal_token_matches'] for c in gh_calls),
                                'each gh invocation receives the planted personal token')
                self.assertTrue(all(c['app_material_absent'] for c in gh_calls),
                                'each gh invocation is free of App material in its environment and arguments')
                self.assertEqual([c['argv'] for c in gh_calls], [['api', 'user'], ['api', f'repos/{REPO}']])
                self.assertEqual(results['github_app'], code)
                self.assertEqual(results['personal_github'], 'identity_verified')
                if code == 'app_revoked':
                    self.assertEqual(json.loads(state_file.read_text())['app'],
                                     {'app_id': 1001, 'installation_id': None})
                seen = list(self.server.seen)
                self.assertEqual(len([s for s in seen if s[0] == 'POST']), mints, [s[:2] for s in seen])
                for method, path, headers, body in seen:
                    # App reads and at most one token request, for exactly the
                    # chosen repository, signed by the App's key alone.
                    self.assertIn((method, path), [('GET', '/app'), ('GET', '/app/installations'),
                                                   ('GET', '/app/installations?page=2'),
                                                   ('POST', '/app/installations/2002/access_tokens')])
                    if method == 'POST':
                        self.assertEqual(json.loads(body), {'repositories': [REPO.split('/')[1]],
                                                            'permissions': PROFILE})
                    self.assert_app_identity(headers.get('Authorization', ''))
                    self.assertFalse(PLANTED_PERSONAL in json.dumps(headers) + body + path, 'personal token sent to the App API')
                for planted in (PLANTED_INSTALLATION, 'Bearer', 'BEGIN'):
                    self.assertFalse(planted in json.dumps(gh_calls), 'an App credential handed to gh')
                # gh gets the agents' own login and no other credential variable.
                self.assertEqual([c['env'] for c in gh_calls], [['GH_TOKEN'], ['GH_TOKEN']])
        stored = files_text(self.state / 'setup')
        key_lines = [line for line in self.key.splitlines() if len(line) > 20 and not line.startswith('-----')]
        for planted in [PLANTED_INSTALLATION, PLANTED_PERSONAL, *key_lines]:
            self.assertFalse(planted in self.outputs + stored, 'a credential reached output or state')


if __name__ == '__main__':
    unittest.main()
