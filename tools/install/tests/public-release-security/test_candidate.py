#!/usr/bin/env python3
from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]

PLANTED_ACCOUNT_ID = 'acct_synthetic2206plantedaaaaaaaa'
PLANTED_EMAIL = 'planted-2206-owner@example.invalid'
PLANTED_NONCE = 'PlantedSyntheticNonce2206bbbbbbbbbbbb'
PLANTED_SIGN_IN_ERROR = 'synthetic-token-2206-in-an-error-field'
PLANTED_PERSONAL = 'gho_PlantedSyntheticPersonal2206dddddddddddd'
PLANTED_MINTED = 'ghs_PlantedSyntheticMinted2206eeeeeeeeeeeeee'


def files_text(folder):
    folder = Path(folder)
    if not folder.exists():
        return ''
    return ''.join(p.read_bytes().decode('utf-8', 'replace') for p in sorted(folder.rglob('*')) if p.is_file())


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cloudroom_tests = load('cloudroom_tests_for_2206', ROOT / 'tools/install/cloudroom/test_cloudroom.py')
cloudroom = cloudroom_tests.cloudroom


def status_answer(**change):
    value = {'ready': True, 'account': {'id': PLANTED_ACCOUNT_ID, 'email': PLANTED_EMAIL},
             'signedOut': False, 'projectId': None, 'repository': None, 'model': None,
             'error': None, 'signingIn': False, 'signInError': None}
    value.update(change)
    return json.dumps(value).encode()


class CloudRoomBoundary(unittest.TestCase):
    PLANTED = (PLANTED_ACCOUNT_ID, PLANTED_EMAIL, PLANTED_NONCE, PLANTED_SIGN_IN_ERROR)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-2206-cloudroom-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state'
        self.host = cloudroom_tests.FakeHost(self.base)
        self.host.launcher()
        self.host.sign_in_reply = json.dumps(
            {'url': f'https://www.cloudroom.dev/login?desktop={PLANTED_NONCE}'}).encode()

    def run_tool(self, *argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            cloudroom.main([*argv, '--state-dir', str(self.state)], host=self.host)
        answer = json.loads(stdout.getvalue())
        leaked = stdout.getvalue() + stderr.getvalue() + files_text(self.state) + files_text(self.base / 'home')
        return answer, leaked

    def assert_confined(self, leaked):
        for planted in self.PLANTED:
            self.assertNotIn(planted, leaked, 'a CloudRoom account or link value reached output or state')

    def assert_no_install(self):
        self.assertFalse(self.host.appimage().exists(), 'nothing is installed on a login path')
        programs = [c for c in self.host.calls if Path(c[0]).name != 'room-cli']
        self.assertEqual(programs, [], 'no program but room-cli runs on a login path')

    def test_lost_refused_and_contradictory_login_reads_never_verify_or_leak(self):
        cases = [
            ('lost reply: the status read times out', 'timeout', 'cloudroom_login_unknown'),
            ('the status read fails', None, 'cloudroom_login_unknown'),
            ('a truncated answer', status_answer()[:40], 'cloudroom_login_unknown'),
            ('a duplicate account key', status_answer()[:-1] + b', "account": null}', 'cloudroom_login_unknown'),
            ('signed out, with a planted error text',
             status_answer(account=None, signedOut=True, signInError=PLANTED_SIGN_IN_ERROR),
             'cloudroom_login_missing'),
            ('still signing in', status_answer(signingIn=True), 'cloudroom_login_unknown'),
            ('an account that also says signed out', status_answer(signedOut=True), 'cloudroom_login_unknown'),
            ('a self-hosted connection', status_answer(selfHosted=True), 'cloudroom_login_unknown'),
            ('an account with an extra field',
             status_answer(account={'id': PLANTED_ACCOUNT_ID, 'email': PLANTED_EMAIL, 'token': PLANTED_NONCE}),
             'cloudroom_login_unknown'),
        ]
        self.assertEqual(len(cases), 9)
        for name, answer, code in cases:
            with self.subTest(case=name):
                self.host.status = answer
                self.host.calls.clear()
                result, leaked = self.run_tool('status')
                self.assertEqual(result, {'schema': 'openwiz.cloudroom-setup.v1', 'code': code,
                                          'operation': None, 'opened': None})
                self.assertEqual(self.host.calls, [[str(self.host.home / '.local/bin/room-cli'),
                                                    'cloud', 'status', '--json']])
                self.assert_no_install()
                self.assertEqual(self.host.opened, [])
                self.assert_confined(leaked)

    def test_a_verified_login_is_reported_by_code_only(self):
        self.host.status = status_answer()
        result, leaked = self.run_tool('status')
        self.assertEqual(result['code'], 'cloudroom_login_verified')
        self.assert_confined(leaked)

    def test_sign_in_opens_the_planted_link_once_and_never_repeats_it(self):
        self.host.status = status_answer(account=None, signedOut=True)
        result, leaked = self.run_tool('sign-in')
        self.assertEqual(result['opened'], 'sign_in')
        self.assertEqual(result['code'], 'cloudroom_login_missing')
        self.assertEqual(self.host.opened, [['/usr/bin/xdg-open',
                                             f'https://www.cloudroom.dev/login?desktop={PLANTED_NONCE}']])
        self.assert_no_install()
        self.assert_confined(leaked)

    def test_lost_or_refused_sign_in_replies_open_nothing_and_leak_nothing(self):
        cases = [
            ('lost reply: no sign-in answer', b''),
            ('a truncated sign-in answer', b'{"url": "https://www.cloudroom.dev/login?desktop=' + PLANTED_NONCE.encode()),
            ('a link on another host', json.dumps({'url': f'https://cloudroom.example.invalid/?n={PLANTED_NONCE}'}).encode()),
            ('a plain-HTTP link', json.dumps({'url': f'http://www.cloudroom.dev/login?desktop={PLANTED_NONCE}'}).encode()),
            ('a link with a user part', json.dumps({'url': f'https://{PLANTED_NONCE}@www.cloudroom.dev/'}).encode()),
            ('an extra field beside the link',
             json.dumps({'url': 'https://www.cloudroom.dev/login', 'token': PLANTED_NONCE}).encode()),
        ]
        self.assertEqual(len(cases), 6)
        for name, reply in cases:
            with self.subTest(case=name):
                self.host.status = status_answer(account=None, signedOut=True)
                self.host.sign_in_reply = reply
                self.host.opened.clear()
                result, leaked = self.run_tool('sign-in')
                self.assertIsNone(result['opened'])
                self.assertEqual(result['code'], 'cloudroom_login_missing')
                self.assertEqual(self.host.opened, [])
                self.assert_no_install()
                self.assert_confined(leaked)


MINT = ROOT / 'tools/github-app/mint-token.py'
READ = {'metadata': 'read', 'contents': 'read', 'issues': 'read', 'pull_requests': 'read',
        'checks': 'read', 'actions': 'read'}
OWNER, NAME = 'synthetic-owner', 'synthetic-consumer'


class AppApi(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_GET(self):
        found = {'/app': {'id': 1001, 'owner': {'login': OWNER}},
                 '/app/installations/3003': {'id': 3003, 'app_id': 1001, 'account': {'login': OWNER},
                                             'repository_selection': 'selected'}}.get(self.path)
        data = json.dumps(found or {'message': 'synthetic: not found'}).encode()
        self.send_response(200 if found else 404)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        size = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(size).decode() if size else ''
        self.server.seen.append((self.path, dict(self.headers), body))
        answer = self.server.answer
        if answer == 'lost':
            self.close_connection = True
            return
        status, value = answer
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MintBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='openwiz-2206-mint-')
        cls.root = Path(cls.temp.name)
        cls.state = cls.root / 'state'
        app_dir = cls.state / 'service/app'
        app_dir.mkdir(parents=True, mode=0o700)
        for folder in (cls.state, cls.state / 'service', app_dir):
            folder.chmod(0o700)
        subprocess.run(['/usr/bin/openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                        '-out', str(app_dir / 'private-key.pem')], check=True, capture_output=True)
        (app_dir / 'private-key.pem').chmod(0o600)
        cls.key_lines = [line for line in (app_dir / 'private-key.pem').read_text().splitlines()
                         if len(line) > 20 and not line.startswith('-----')]
        (app_dir / 'app.json').write_text('{"app_id":1001}')
        (app_dir / 'app.json').chmod(0o600)
        cls.server = HTTPServer(('127.0.0.1', 0), AppApi)
        cls.server.seen = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def mint(self, answer):
        self.server.answer = answer
        self.server.seen.clear()
        run = subprocess.run(
            [sys.executable, '-B', str(MINT), '--installation-id', '3003', '--repository', f'{OWNER}/{NAME}',
             '--state-dir', str(self.state), '--api-base', f'http://127.0.0.1:{self.server.server_port}'],
            capture_output=True, text=True, timeout=60, cwd=self.root,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'GH_TOKEN': PLANTED_PERSONAL,
                 'OPENWIZ_SYNTHETIC_GITHUB': '1'})
        return run

    def minted(self, **change):
        value = {'token': PLANTED_MINTED, 'expires_at': '2099-01-01T00:00:00Z', 'permissions': dict(READ),
                 'repository_selection': 'selected', 'repositories': [{'full_name': f'{OWNER}/{NAME}'}]}
        value.update(change)
        return value

    def soon(self):
        import datetime
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=50)
        return later.strftime('%Y-%m-%dT%H:%M:%SZ')

    def assert_request(self):
        self.assertEqual(len(self.server.seen), 1)
        path, headers, body = self.server.seen[0]
        self.assertEqual(path, '/app/installations/3003/access_tokens')
        self.assertEqual(json.loads(body), {'permissions': READ, 'repositories': [NAME]})
        self.assertTrue(headers.get('Authorization', '').startswith('Bearer ey'), 'signed by the App JWT')
        self.assertNotIn(PLANTED_PERSONAL, json.dumps(headers) + body, 'the personal login reached the App API')

    def test_the_exact_answer_prints_the_token_and_its_expiry_only(self):
        run = self.mint((201, self.minted(expires_at=self.soon())))
        self.assertEqual(run.returncode, 0, run.stderr)
        lines = run.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0], PLANTED_MINTED)
        self.assertRegex(lines[1], r'^[0-9]+$')
        self.assertEqual(run.stderr, '')
        self.assert_request()

    def test_refused_revoked_expired_wider_and_lost_answers_print_no_token(self):
        cases = [
            ('installation revoked', (404, {'message': 'synthetic: not found'})),
            ('App key rejected', (401, {'message': 'synthetic: bad credentials'})),
            ('repository not granted', (422, {'message': f'synthetic: {PLANTED_MINTED}'})),
            ('lost reply', 'lost'),
            ('token already expired', (201, self.minted(expires_at='2020-01-01T00:00:00Z'))),
            ('token outlives an hour', (201, self.minted())),
            ('every repository', (201, self.minted(expires_at=self.soon(), repository_selection='all'))),
            ('a foreign repository too', (201, self.minted(expires_at=self.soon(), repositories=[
                {'full_name': f'{OWNER}/{NAME}'}, {'full_name': 'synthetic-stranger/other'}]))),
            ('another repository instead', (201, self.minted(expires_at=self.soon(), repositories=[
                {'full_name': f'{OWNER}/another'}]))),
            ('write permission granted', (201, self.minted(expires_at=self.soon(),
                                                           permissions=dict(READ, contents='write')))),
        ]
        self.assertEqual(len(cases), 10)
        for name, answer in cases:
            with self.subTest(case=name):
                run = self.mint(answer)
                self.assertEqual(run.returncode, 1)
                self.assertEqual(run.stdout, '', 'no token on stdout')
                self.assertEqual(run.stderr.strip(), 'App token refused: check PC state permissions, '
                                 'App installation and GitHub availability.')
                self.assert_request()
                for planted in (PLANTED_MINTED, PLANTED_PERSONAL, *self.key_lines):
                    self.assertNotIn(planted, run.stdout + run.stderr)
                self.assertNotIn(PLANTED_MINTED, files_text(self.state), 'a token was stored')


class SetupSettingsBoundary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self, **settings):
        values = dict({'harness': 'claude-code', 'model': 'synthetic-model', 'effort': 'high'}, **settings)
        return subprocess.run(
            [sys.executable, '-I', '-B', str(ROOT / 'tools/install/setup/setup.py'), 'prepare',
             '--repository', 'synthetic-owner/synthetic-consumer', '--project', 'prj_synthetic',
             '--operator', 'synthetic-owner', '--service-issue', '7', '--answer-thread', 'thr_synthetic_answer',
             *(x for key in ('harness', 'model', 'effort') for x in (f'--{key}', values[key])),
             '--state-dir', str(self.state)],
            cwd=self.root, capture_output=True, text=True, timeout=60,
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root)})

    def test_credential_shaped_agent_settings_are_refused_before_any_effect(self):
        a = 'A' * 36
        planted = ['ghp_' + a, 'gho_' + a, 'ghs_' + a, 'ghu_' + a, 'ghr_' + a, 'github_pat_' + a,
                   'sk-ant-synthetic' + a, 'sk-' + a, 'xoxb-' + a, 'AKIA' + a[:16],
                   'eyJ' + a[:12] + '.eyJ' + a[:12] + '.' + a[:12], 'synthetic/ghp_' + a]
        self.assertEqual(len(planted), 12)
        for key in ('harness', 'model', 'effort'):
            for value in planted:
                with self.subTest(setting=key, shape=value[:4]):
                    run = self.prepare(**{key: value})
                    self.assertEqual(run.returncode, 5)
                    self.assertEqual(run.stdout, '')
                    self.assertEqual(run.stderr, 'openwiz-setup: refused: invalid agent setting\n')
                    self.assertEqual(files_text(self.state), '', 'state was written')

    def test_ordinary_agent_settings_still_prepare(self):
        for harness, model, effort in (('claude-code', 'claude-opus-5-5', 'xhigh'),
                                       ('codex', 'gpt-5.1-codex', 'medium'),
                                       ('task-runner', 'desk-ghp', 'o3')):
            with self.subTest(model=model):
                run = self.prepare(harness=harness, model=model, effort=effort)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertIn(f'Run agents on {harness}, {model}, {effort} effort.',
                              json.loads(run.stdout)['effects'])


if __name__ == '__main__':
    unittest.main()
