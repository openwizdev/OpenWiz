#!/usr/bin/env python3
"""#2206: planted synthetic secrets at the candidate's changed and new boundaries.

P10's baseline cases (baseline/) cover the App setup check and phone access as
they stood at its source revision. These cases cover what the candidate added
or changed since then, each through its public entry point and a recording
provider:

- the CloudRoom install and sign-in tool (#2201), on its own recording host;
- the feedback helper (#2292), on a recording `gh` that answers by credential;
- the PC read-token tool's repository downscope (#2315), on a loopback App API.

Each case plants unmistakable synthetic values (an account, a sign-in nonce,
tokens, private-looking context), drives a refused, revoked, expired or
lost-reply path, and proves that nothing unauthorized took effect and that no
planted value reached output, errors, saved state or a request it was not meant
for. Synthetic values only; no network beyond 127.0.0.1.

  python3 -I tools/install/tests/public-release-security/test_candidate.py
"""
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

# Planted values: unmistakable, synthetic, never a real credential.
PLANTED_ACCOUNT_ID = 'acct_synthetic2206plantedaaaaaaaa'
PLANTED_EMAIL = 'planted-2206-owner@example.invalid'
PLANTED_NONCE = 'PlantedSyntheticNonce2206bbbbbbbbbbbb'
PLANTED_SIGN_IN_ERROR = 'synthetic-token-2206-in-an-error-field'
PLANTED_APP_TOKEN = 'ghs_PlantedSyntheticInstallation2206cccccccc'
PLANTED_PERSONAL = 'gho_PlantedSyntheticPersonal2206dddddddddddd'
PLANTED_CONTEXT = 'synthetic-token-000000'
PLANTED_PATH = '/home/synthetic-user/secret-project'
PLANTED_MINTED = 'ghs_PlantedSyntheticMinted2206eeeeeeeeeeeeee'


def files_text(folder):
    """Every byte under FOLDER, as text, so a planted value anywhere is found."""
    folder = Path(folder)
    if not folder.exists():
        return ''
    return ''.join(p.read_bytes().decode('utf-8', 'replace') for p in sorted(folder.rglob('*')) if p.is_file())


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --- #2201: the CloudRoom install, reuse and sign-in tool ---------------------

# The tool's own recording host (every program, URL and open is recorded).
cloudroom_tests = load('cloudroom_tests_for_2206', ROOT / 'tools/install/cloudroom/test_cloudroom.py')
cloudroom = cloudroom_tests.cloudroom


def status_answer(**change):
    value = {'ready': True, 'account': {'id': PLANTED_ACCOUNT_ID, 'email': PLANTED_EMAIL},
             'signedOut': False, 'projectId': None, 'repository': None, 'model': None,
             'error': None, 'signingIn': False, 'signInError': None}
    value.update(change)
    return json.dumps(value).encode()


class CloudRoomBoundary(unittest.TestCase):
    """The login read and sign-in handoff never repeat CloudRoom's account or link."""

    PLANTED = (PLANTED_ACCOUNT_ID, PLANTED_EMAIL, PLANTED_NONCE, PLANTED_SIGN_IN_ERROR)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-2206-cloudroom-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.state = self.base / 'state'
        self.host = cloudroom_tests.FakeHost(self.base)
        self.host.launcher()  # CloudRoom installed and opened before: reuse, no install
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
            # (case, room-cli cloud status answer, expected code)
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


# --- #2292: the feedback helper, through the user's own gh login --------------

FEEDBACK = ROOT / 'skills/feedback/scripts/feedback.py'
FEEDBACK_FAKE = ROOT / 'skills/feedback/test/fake_gh.py'
USER = {'login': 'synthetic-user', 'id': 9001}
REPO = {'full_name': 'openwizdev/openwiz', 'private': False, 'visibility': 'public',
        'archived': False, 'has_issues': True}
TITLE = 'Plan page hides the approve button on a narrow phone'
BODY = 'On a 360-pixel screen the approve button sits under the footer.'

# A recording gh that answers by credential: an App installation token is not
# a user login, so GitHub answers GET /user with 403, as it does for an
# installation token; a personal login is handed to the #2292 recording gh.
CREDENTIAL_GH = r'''#!PYTHON
import json, os, sys
token = os.environ.get('GH_TOKEN', '')
with open(os.environ['CREDENTIAL_LOG'], 'a') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'app_token': token.startswith('ghs_'),
                          'stdin': '' if sys.stdin.isatty() else '<read by the fake>'}) + '\n')
if token.startswith('ghs_'):
    args = sys.argv[1:]
    if 'POST' in args:
        status, body = 403, {'message': 'Resource not accessible by integration'}
    elif args[-1] == 'user':
        status, body = 403, {'message': 'Resource not accessible by integration'}
    else:
        status, body = 200, __REPO__
    sys.stdout.write(f'HTTP/2.0 {status} Synthetic\nContent-Type: application/json\n\n' + json.dumps(body))
    sys.exit(0 if status < 400 else 1)
os.execv(sys.executable, [sys.executable, '-I', __FAKE__, *sys.argv[1:]])
'''


class FeedbackBoundary(unittest.TestCase):
    """Feedback goes only through the user's own login; planted material stays put."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='openwiz-2206-feedback-'))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.tmp / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(CREDENTIAL_GH.replace('PYTHON', sys.executable).replace('__FAKE__', repr(str(FEEDBACK_FAKE)))
                      .replace('__REPO__', repr(REPO)))
        gh.chmod(0o700)
        self.state = self.tmp / 'state'
        self.log = self.tmp / 'gh.log'
        self.log.write_text('')
        self.credential_log = self.tmp / 'credential.log'
        self.credential_log.write_text('')
        # Planted private-looking context: the agent's folder and environment.
        self.work = self.tmp / PLANTED_PATH.lstrip('/')
        self.work.mkdir(parents=True)
        (self.work / 'notes.txt').write_text(f'private notes {PLANTED_CONTEXT}\n')
        self.scenario = self.tmp / 'world.json'
        self.scenario.write_text(json.dumps({'user': USER, 'repo': REPO, 'create': {'status': 201},
                                             'readback': 'ok', 'list': 'ok', 'issues': [], 'next_number': 41}))
        (self.tmp / 'title.txt').write_text(TITLE)
        (self.tmp / 'body.txt').write_text(BODY)
        self.outputs = ''

    def world(self, **change):
        world = json.loads(self.scenario.read_text())
        world.update(change)
        self.scenario.write_text(json.dumps(world))

    def helper(self, *args, login):
        env = {'PATH': str(self.bin), 'OPENWIZ_STATE_DIR': str(self.state), 'HOME': str(self.work),
               'FAKE_GH_SCENARIO': str(self.scenario), 'FAKE_GH_LOG': str(self.log),
               'CREDENTIAL_LOG': str(self.credential_log), 'LC_ALL': 'C', 'GH_TOKEN': login,
               'SYNTHETIC_PRIVATE_TOKEN': PLANTED_CONTEXT, 'SYNTHETIC_PRIVATE_PATH': PLANTED_PATH}
        run = subprocess.run([sys.executable, '-I', str(FEEDBACK), *args], capture_output=True, text=True,
                             env=env, cwd=self.work, timeout=60)
        self.outputs += run.stdout + run.stderr
        return run.returncode, json.loads(run.stdout)

    def creates(self):
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [c for c in calls if 'POST' in c['argv']]

    def credential_calls(self):
        return [json.loads(line) for line in self.credential_log.read_text().splitlines()]

    def draft(self, login):
        code, answer = self.helper('draft', '--title-file', str(self.tmp / 'title.txt'),
                                   '--body-file', str(self.tmp / 'body.txt'), login=login)
        self.assertEqual((code, answer['phase']), (0, 'draft'))
        return answer['operation_id']

    def assert_confined(self, planted):
        stored = files_text(self.state)
        for value in planted:
            self.assertNotIn(value, self.outputs + stored, 'a planted value reached output or the record')

    def test_an_app_installation_token_is_never_a_feedback_login(self):
        op = self.draft(PLANTED_APP_TOKEN)
        code, preview = self.helper('preview', op, login=PLANTED_APP_TOKEN)
        self.assertEqual(code, 1)
        self.assertIn('Your GitHub login could not be read', preview['refused'])
        _, status = self.helper('status', op, login=PLANTED_APP_TOKEN)
        self.assertEqual(status['phase'], 'draft', 'the draft is kept; nothing previewed')
        # A yes to a preview that never happened sends nothing either.
        code, sent = self.helper('send', op, '--preview-id', '0' * 16, login=PLANTED_APP_TOKEN)
        self.assertEqual((code, sent['phase']), (1, 'refused'))
        calls = self.credential_calls()
        self.assertTrue(calls and all(c['app_token'] for c in calls))
        self.assertEqual([c for c in calls if 'POST' in c['argv']], [], 'no create request as the App')
        self.assertEqual(self.creates(), [])
        self.assert_confined([PLANTED_APP_TOKEN, PLANTED_CONTEXT, PLANTED_PATH])

    def test_a_lost_create_reply_stays_uncertain_and_sends_only_the_previewed_bytes(self):
        self.world(create={'drop': True})
        op = self.draft(PLANTED_PERSONAL)
        code, preview = self.helper('preview', op, login=PLANTED_PERSONAL)
        self.assertEqual((code, preview['phase']), (0, 'previewed'))
        code, sent = self.helper('send', op, '--preview-id', preview['preview_id'], login=PLANTED_PERSONAL)
        self.assertEqual((code, sent['phase']), (1, 'uncertain'))
        creates = self.creates()
        self.assertEqual(len(creates), 1)
        self.assertEqual(json.loads(creates[0]['stdin']),
                         {'title': TITLE, 'body': f'{BODY}\n\nOpenWiz feedback operation {op}'})
        # The lost reply is never resent: a repeated yes and a new preview make no call.
        self.world(create={'status': 201})
        code, again = self.helper('send', op, '--preview-id', preview['preview_id'], login=PLANTED_PERSONAL)
        self.assertEqual((code, again['phase']), (1, 'uncertain'))
        code, re_preview = self.helper('preview', op, login=PLANTED_PERSONAL)
        self.assertEqual((code, re_preview['phase']), (1, 'uncertain'))
        self.assertEqual(len(self.creates()), 1)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        sent_text = json.dumps(calls)
        for planted in (PLANTED_PERSONAL, PLANTED_CONTEXT, PLANTED_PATH):
            self.assertNotIn(planted, sent_text, 'a planted value reached a GitHub request')
        self.assert_confined([PLANTED_PERSONAL, PLANTED_CONTEXT])


# --- #2315: the PC read-token tool's repository downscope ---------------------

MINT = ROOT / 'tools/github-app/mint-token.py'
READ = {'metadata': 'read', 'contents': 'read', 'issues': 'read', 'pull_requests': 'read',
        'checks': 'read', 'actions': 'read'}
OWNER, NAME = 'synthetic-owner', 'synthetic-consumer'


class AppApi(BaseHTTPRequestHandler):
    """A loopback GitHub App API for one installation, 3003; each answer steered by the test."""

    def log_message(self, *_args):
        pass

    def do_POST(self):
        size = int(self.headers.get('Content-Length') or 0)
        body = self.rfile.read(size).decode() if size else ''
        self.server.seen.append((self.path, dict(self.headers), body))
        answer = self.server.answer
        if answer == 'lost':
            self.close_connection = True
            return  # lost reply: the connection closes with no response
        status, value = answer
        data = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class MintBoundary(unittest.TestCase):
    """mint-token.py --repository: a refused, expired, wider or lost answer prints no token."""

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
            env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root), 'GH_TOKEN': PLANTED_PERSONAL})
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


if __name__ == '__main__':
    unittest.main()
