#!/usr/bin/env python3
"""C8 offline proofs for read.py: recording GitHub, separate processes, no network.

Run: python3 -I tools/github-reads/test_read.py. Synthetic fixtures only; a
pass is fixture evidence, never a live installation or quota observation.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
READ = HERE / 'read.py'
FIX = HERE / 'fixtures' / 'reads'
REPO = 'synthetic-owner/work'
OTHER = 'synthetic-owner/other'
PERMISSIONS = {name: 'read' for name in (
    'metadata', 'contents', 'issues', 'pull_requests', 'checks', 'actions')}
PROVIDER_BODY = 'synthetic-provider-error-body'


def fixture(name):
    return json.loads((FIX / name).read_text())


@contextmanager
def recording_github():
    """A loopback GitHub that records every call and serves fixture behaviour."""
    calls, lock = [], threading.Lock()
    state = {'mint_status': 201, 'mint_count': 0, 'mint_hold': None, 'expires_in': 3600,
             'mint': fixture('mint.json'), 'rate': fixture('rate-limit.json'),
             'rate_status': 200, 'rate_delay': 0.0, 'routes': {}, 'graphql': fixture('graphql.json'),
             'core_remaining': None, 'delay': 0.0, 'hold': None,
             'hold_entered': threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body=b'', headers=()):
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass  # a caller this test killed on purpose

        def record(self, body=b''):
            with lock:
                calls.append({'method': self.command, 'path': self.path,
                              'headers': dict(self.headers), 'body': body.decode()})

        def rate_headers(self, resource):
            if resource != 'core' or state['core_remaining'] is None:
                return []
            with lock:
                state['core_remaining'] = max(0, state['core_remaining'] - 1)
                remaining = state['core_remaining']
            return [('x-ratelimit-limit', str(state['rate']['resources']['core']['limit'])),
                    ('x-ratelimit-remaining', str(remaining)),
                    ('x-ratelimit-reset', str(state['rate']['resources']['core']['reset'])),
                    ('x-ratelimit-resource', 'core')]

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            self.record(body)
            if self.path == '/app/installations/2002/access_tokens':
                with lock:
                    state['mint_count'] += 1
                    count = state['mint_count']
                if state['mint_status'] != 201:
                    return self.send(state['mint_status'], json.dumps({'message': PROVIDER_BODY}).encode())
                result = dict(state['mint'], token=f'synthetic-installation-token-{count}',
                              expires_at=(datetime.now(timezone.utc) + timedelta(
                                  seconds=state['expires_in'])).isoformat())
                if state['mint_hold'] is not None:
                    state['mint_hold'].wait(10)
                return self.send(201, json.dumps(result).encode())
            if self.path == '/graphql':
                n = json.loads(body).get('variables', {}).get('n')
                response = state.get('graphql_responses', {}).get(n, state['graphql'])
                hold = state['hold']
                if hold is not None:
                    state['hold_entered'].set()
                    hold.wait(10)
                if response.get('disconnect'):
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                return self.send(response.get('status', 200), json.dumps(response['body']).encode(),
                                 [(k, v) for k, v in response.get('headers', {}).items()])
            self.send(404, json.dumps({'message': PROVIDER_BODY}).encode())

        def do_GET(self):
            self.record()
            if self.path == '/rate_limit':
                time.sleep(state['rate_delay'])
                rate = state['rate']
                return self.send(state['rate_status'], json.dumps(rate).encode())
            route = state['routes'].get(self.path)
            if route is None:
                return self.send(404, json.dumps({'message': PROVIDER_BODY}).encode())
            hold = state['hold']
            if hold is not None:
                state['hold_entered'].set()
                hold.wait(10)
            if route.get('disconnect'):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            time.sleep(state['delay'])
            headers = list(route.get('headers', {}).items()) + self.rate_headers('core')
            etag = route.get('etag')
            if etag and self.headers.get('If-None-Match') == etag and not route.get('force_200'):
                return self.send(304, b'', headers + [('ETag', etag)])
            if etag:
                headers.append(('ETag', etag))
            if 'link' in route:
                headers.append(('Link', route['link'].replace('BASE', base)))
            body = route.get('raw', json.dumps(route.get('body')).encode())
            self.send(route.get('status', 200), body, headers)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    base = f'http://127.0.0.1:{server.server_port}'
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield base, calls, state
    finally:
        if state['hold'] is not None:
            state['hold'].set()
        server.shutdown()
        server.server_close()
        thread.join()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-reads-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state'
        app = self.state / 'service/app'
        app.mkdir(parents=True, mode=0o700)
        for path in (self.state, self.state / 'service'):
            path.chmod(0o700)
        key = app / 'private-key.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt',
                        'rsa_keygen_bits:2048', '-out', str(key)], check=True, capture_output=True)
        key.chmod(0o600)
        self.pem = key.read_bytes()
        (app / 'app.json').write_text('{"app_id":1001}')
        (app / 'app.json').chmod(0o600)
        self.reads = self.state / 'service/github-reads'
        self.reads.mkdir(mode=0o700)
        self.reads.chmod(0o700)
        config = self.reads / 'installation.json'
        config.write_text(json.dumps({'installation_id': 2002, 'repositories': [REPO, OTHER]}))
        config.chmod(0o600)
        self.base = self.calls = self.github = None
        context = recording_github()
        self.base, self.calls, self.github = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        self.outputs = []

    def route(self, path, body, **extra):
        self.github['routes'][path] = dict(extra, body=body)

    def command(self, *args, stdin=None, purpose='display', max_age='600', extra=()):
        return [sys.executable, '-I', str(READ), *args, '--purpose', purpose, '--max-age', max_age,
                '--state-dir', str(self.state), '--api-base', self.base, *extra]

    def read(self, *args, stdin=None, **kwargs):
        result = subprocess.run(self.command(*args, **kwargs), input=(stdin or '').encode(),
                                capture_output=True, timeout=60)
        self.outputs.append(result.stdout + result.stderr)
        return result.returncode, result.stdout.decode(), result.stderr.decode().strip()

    def upstream(self, prefix='/repos/'):
        return [c for c in self.calls if c['path'].startswith(prefix)]

    def mints(self):
        return [c for c in self.calls if c['path'].endswith('/access_tokens')]

    def assert_no_secret(self):
        tokens = [f'synthetic-installation-token-{n}'.encode() for n in range(1, 40)]
        needles = tokens + [self.pem] + self.pem.splitlines()[1:-1] + [PROVIDER_BODY.encode()]
        stored = [p.read_bytes() for p in self.reads.rglob('*') if p.is_file()]
        for output in self.outputs + stored:
            for needle in needles:
                self.assertNotIn(needle, output)
        for call in self.calls:
            for needle in tokens:
                self.assertNotIn(needle.decode(), call['path'] + call['body'])


class Authentication(Fixture):
    def test_installation_token_downscoped_to_selected_repositories(self):
        """C8-auth: a read mints a read-only installation token for the configured selection."""
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')
        self.assertEqual((code, err), (0, 'fresh: current'))
        self.assertEqual(json.loads(out), {'number': 1})
        self.assertEqual(len(self.mints()), 1)
        self.assertEqual(json.loads(self.mints()[0]['body']),
                         {'permissions': PERMISSIONS, 'repositories': ['other', 'work']})
        read = self.upstream()[0]
        self.assertEqual(read['method'], 'GET')
        self.assertEqual(read['headers']['Authorization'], 'Bearer synthetic-installation-token-1')
        self.assert_no_secret()

    def test_missing_revoked_foreign_or_unsafe_credentials_refuse_without_fallback(self):
        """C8-auth: no token, a foreign selection or unsafe state refuses; nothing falls back."""
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        env_token = dict(os.environ, GH_TOKEN='synthetic-user-token', GITHUB_TOKEN='synthetic-user-token')
        cases = {
            'revoked': lambda: self.github.update(mint_status=404),
            'suspended': lambda: self.github.update(mint_status=403),
            'foreign': lambda: self.github.update(mint=dict(fixture('mint.json'), repositories=[
                {'full_name': 'synthetic-elsewhere/work'}, {'full_name': 'synthetic-owner/other'}])),
            'wider': lambda: self.github.update(mint=dict(fixture('mint.json'), permissions=dict(
                PERMISSIONS, issues='write'))),
            'missing-key': lambda: (self.state / 'service/app/private-key.pem').rename(
                self.state / 'service/app/moved.pem'),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                self.github.update(mint_status=201, mint=fixture('mint.json'))
                change()
                before = len(self.upstream())
                result = subprocess.run(self.command('rest', REPO, 'repos/synthetic-owner/work/issues/1'),
                                        capture_output=True, timeout=60, env=env_token)
                self.outputs.append(result.stdout + result.stderr)
                self.assertEqual((result.returncode, result.stdout, result.stderr.decode().strip()),
                                 (1, b'', 'refused: credential'))
                self.assertEqual(len(self.upstream()), before)
                moved = self.state / 'service/app/moved.pem'
                if moved.exists():
                    moved.rename(self.state / 'service/app/private-key.pem')
        for call in self.calls:
            self.assertNotIn('synthetic-user-token', json.dumps(call))
        self.assert_no_secret()

    def test_expired_credentials_refuse_before_cached_data_is_returned(self):
        """C8-auth: an expired authorization re-mints; a failed mint returns no cached body."""
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        self.github['expires_in'] = 2
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')[0], 0)
        time.sleep(2.5)
        self.github['mint_status'] = 404
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')
        self.assertEqual((code, out, err), (1, '', 'refused: credential'))
        self.assertEqual(len(self.upstream()), 1)
        self.assert_no_secret()

    def test_changed_authorization_invalidates_cached_entries(self):
        """C8-auth: a refusal then a new grant is a new generation; old entries never serve it."""
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1}, etag='"synthetic-1"')
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')[0], 0)
        self.github['mint_status'] = 404
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1',
                                   max_age='0')[2], 'refused: credential')
        self.github['mint_status'] = 201
        code, _out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')
        self.assertEqual((code, err), (0, 'fresh: current'))
        reads = self.upstream()
        self.assertEqual(len(reads), 2)
        self.assertNotIn('If-None-Match', reads[1]['headers'])


class SharedCache(Fixture):
    def spawn(self, *args, **kwargs):
        return subprocess.Popen(self.command(*args, **kwargs), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def finish(self, procs):
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            self.outputs.append(out + err)
            results.append((proc.returncode, out.decode(), err.decode().strip()))
        return results

    def test_identical_concurrent_reads_coalesce_across_processes(self):
        """C8-share: six separate caller processes cause one upstream read."""
        self.route('/repos/synthetic-owner/work/pulls/7', {'number': 7})
        self.github['delay'] = 0.8
        challenge = str(int(time.time()) - 1)
        for purpose in ('display', 'authority'):
            with self.subTest(purpose=purpose):
                self.calls.clear()
                procs = [self.spawn('rest', REPO, 'repos/synthetic-owner/work/pulls/7',
                                    purpose=purpose, max_age='60',
                                    extra=('--challenge', challenge) if purpose == 'authority' else ())
                         for _ in range(6)]
                results = self.finish(procs)
                self.assertEqual([r[0] for r in results], [0] * 6, results)
                self.assertEqual({json.dumps(json.loads(r[1])) for r in results}, {'{"number": 7}'})
                self.assertEqual(len(self.upstream()), 1)
                # The next whole second, strictly after every display read began.
                after = int(time.time()) + 1
                time.sleep(after - time.time() + 0.1)
                challenge = str(after)
        self.assert_no_secret()

    def test_partitions_by_repository_and_request(self):
        """C8-share: different repository or request never shares an entry."""
        self.route('/repos/synthetic-owner/work/issues/1', {'repo': 'work'})
        self.route('/repos/synthetic-owner/other/issues/1', {'repo': 'other'})
        self.route('/repos/synthetic-owner/work/issues/1?per_page=1', {'repo': 'work-1'})
        seen = {}
        for repo, endpoint in ((REPO, 'repos/synthetic-owner/work/issues/1'),
                               (OTHER, 'repos/synthetic-owner/other/issues/1'),
                               (REPO, 'repos/synthetic-owner/work/issues/1?per_page=1')):
            code, out, _err = self.read('rest', repo, endpoint)
            self.assertEqual(code, 0)
            seen[endpoint] = json.loads(out)['repo']
        for _ in range(2):
            for repo, endpoint in ((REPO, 'repos/synthetic-owner/work/issues/1'),
                                   (OTHER, 'repos/synthetic-owner/other/issues/1')):
                code, out, err = self.read('rest', repo, endpoint)
                self.assertEqual((code, err, json.loads(out)['repo']), (0, 'display: cache', seen[endpoint]))
        self.assertEqual(seen['repos/synthetic-owner/work/issues/1?per_page=1'], 'work-1')
        self.assertEqual(len(self.upstream()), 3)

    def test_crashed_leader_never_leaves_a_complete_entry(self):
        """C8-share: a killed leader's claim is dropped; the follower reads again."""
        self.route('/repos/synthetic-owner/work/issues/2', {'number': 2})
        self.github['hold'] = threading.Event()
        leader = self.spawn('rest', REPO, 'repos/synthetic-owner/work/issues/2')
        deadline = time.time() + 20
        while not self.upstream() and time.time() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(self.upstream()), 1)
        leader.send_signal(signal.SIGKILL)
        leader.communicate(timeout=10)
        self.github['hold'].set()
        self.github['hold'] = None
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/2')
        self.assertEqual((code, err, json.loads(out)), (0, 'fresh: current', {'number': 2}))
        self.assertEqual(len(self.upstream()), 2)

    def test_unshared_or_unsafe_state_refuses(self):
        """C8-share: a namespace other callers cannot safely share refuses, never a private cache."""
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        self.reads.chmod(0o755)
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1'),
                         (1, '', 'refused: sharing'))
        self.reads.chmod(0o700)
        self.assertEqual(self.calls, [])


class Freshness(Fixture):
    def test_authority_needs_a_current_read_and_304_revalidates_each_page(self):
        """C8-fresh: authority never takes a cache hit; a 304 must match a cached page."""
        page2 = '/repos/synthetic-owner/work/issues/3/comments?per_page=1&page=2'
        self.route('/repos/synthetic-owner/work/issues/3/comments?per_page=1', [{'id': 1}],
                   etag='"page-1"', link=f'<BASE{page2}>; rel="next"')
        self.route(page2, [{'id': 2}], etag='"page-2"')
        endpoint = 'repos/synthetic-owner/work/issues/3/comments?per_page=1'
        code, out, err = self.read('rest', REPO, endpoint)
        self.assertEqual((code, err, [json.loads(line) for line in out.splitlines()]),
                         (0, 'fresh: current', [[{'id': 1}], [{'id': 2}]]))
        self.assertEqual(self.read('rest', REPO, endpoint)[2], 'display: cache')
        self.assertEqual(len(self.upstream()), 2)
        self.github['routes'][page2].update(body=[{'id': 3}], etag='"page-2b"')
        code, out, err = self.read('rest', REPO, endpoint, purpose='authority')
        self.assertEqual((code, err, [json.loads(line) for line in out.splitlines()]),
                         (0, 'fresh: current', [[{'id': 1}], [{'id': 3}]]))
        reads = self.upstream()[2:]
        self.assertEqual([r['headers'].get('If-None-Match') for r in reads], ['"page-1"', '"page-2"'])
        self.assertEqual(self.read('rest', REPO, endpoint, purpose='authority',
                                   extra=('--challenge', str(int(time.time()) + 60)))[2], 'refused: freshness')

    def test_unrequested_304_or_errors_never_publish(self):
        """C8-fresh: a 304 without a cached page and HTTP errors are gaps, not success."""
        self.route('/repos/synthetic-owner/work/issues/4', None, status=304)
        self.route('/repos/synthetic-owner/work/issues/5', {'message': PROVIDER_BODY}, status=500)
        self.route('/repos/synthetic-owner/work/issues/6', {'message': PROVIDER_BODY}, status=404)
        for number in (4, 5, 6):
            with self.subTest(number=number):
                self.assertEqual(self.read('rest', REPO, f'repos/synthetic-owner/work/issues/{number}'),
                                 (1, '', 'refused: incomplete'))
        self.assertEqual(sorted(p.name for p in self.reads.iterdir() if p.name.startswith('entry-')), [])
        self.assert_no_secret()

    def test_pagination_must_be_complete_same_host_and_repository(self):
        """C8-fresh: foreign, repeated or unbounded pages produce an explicit gap."""
        cases = {
            'foreign-repo': '<BASE/repos/synthetic-owner/other/issues?page=2>; rel="next"',
            'foreign-host': '<https://example.invalid/repos/synthetic-owner/work/issues?page=2>; rel="next"',
            'repeated': '<BASE/repos/synthetic-owner/work/issues?per_page=1>; rel="next"',
        }
        for name, link in cases.items():
            with self.subTest(case=name):
                self.route('/repos/synthetic-owner/work/issues?per_page=1', [{'id': 1}], link=link)
                self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues?per_page=1',
                                           purpose='authority'),
                                 (1, '', 'refused: incomplete'))
        self.assertEqual(self.upstream('/repos/synthetic-owner/other'), [])
        # Numeric repository links lack independent identity evidence and refuse.
        self.route('/repos/synthetic-owner/work/issues?per_page=1', [{'id': 1}],
                   link='<BASE/repositories/11/issues?per_page=1&page=2>; rel="next"')
        self.route('/repositories/11/issues?per_page=1&page=2', [{'id': 2}],
                   link='<BASE/repositories/12/issues?per_page=1&page=3>; rel="next"')
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues?per_page=1',
                                   purpose='authority'), (1, '', 'refused: incomplete'))
        self.assertEqual(self.upstream('/repositories/12'), [])
        del self.github['routes']['/repositories/11/issues?per_page=1&page=2']['link']
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues?per_page=1', purpose='authority')
        self.assertEqual((code, out, err), (1, '', 'refused: incomplete'))
        self.assertEqual(self.upstream('/repositories/'), [])

    def test_graphql_errors_and_open_page_chains_are_incomplete(self):
        """C8-fresh: GraphQL errors with HTTP 200 and an unfinished pageInfo refuse."""
        query = 'query Item($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { id } }'
        variables = json.dumps({'owner': 'synthetic-owner', 'name': 'work'})
        code, out, err = self.read('graphql', REPO, '--variables', variables, stdin=query)
        self.assertEqual((code, err), (0, 'fresh: current'))
        self.assertEqual(json.loads(out)['data']['repository']['id'], 'synthetic-node')
        for body in ({'data': None, 'errors': [{'type': 'NOT_FOUND', 'message': PROVIDER_BODY}]},
                     {'data': {'repository': {'issues': {'pageInfo': {'hasNextPage': True}, 'nodes': []}}}},
                     {'data': {'repository': {'issues': {'pageInfo': {}, 'nodes': []}}}}):
            with self.subTest(body=body):
                self.github['graphql'] = {'body': body}
                self.assertEqual(self.read('graphql', REPO, '--variables', variables, stdin=query,
                                           purpose='authority'), (1, '', 'refused: incomplete'))
        self.assert_no_secret()


class Budget(Fixture):
    def test_unknown_budget_admits_no_read(self):
        """C8-budget: an unreadable or contradictory budget probe defers every read."""
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        past = fixture('rate-limit.json')
        past['resources']['core']['reset'] = int(time.time()) - 10
        for change in ({'rate_status': 500}, {'rate': past}):
            with self.subTest(change=list(change)):
                self.github.update(rate_status=200, rate=fixture('rate-limit.json'))
                self.github.update(change)
                code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1', purpose='authority')
                self.assertEqual((code, out), (1, ''))
                self.assertTrue(err.startswith('deferred: budget-unknown'), err)
        self.assertEqual(self.upstream(), [])

    def test_more_processes_tokens_and_entries_add_no_allowance(self):
        """C8-budget: three remaining requests admit three reads across six processes and tokens."""
        rate = fixture('rate-limit.json')
        rate['resources']['core'].update(limit=5, remaining=3, reset=int(time.time()) + 3000)
        self.github.update(rate=rate, core_remaining=3)
        for n in range(6):
            self.route(f'/repos/synthetic-owner/work/issues/{n}', {'number': n})
        procs = [subprocess.Popen(self.command('rest', REPO, f'repos/synthetic-owner/work/issues/{n}'),
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) for n in range(6)]
        errors = []
        for proc in procs:
            out, err = proc.communicate(timeout=60)
            self.outputs.append(out + err)
            errors.append(err.decode().strip().split(' ')[0:2])
        self.assertEqual(len(self.upstream()), 3)
        self.assertEqual(sorted(e[0] for e in errors).count('fresh:'), 3)
        self.assertEqual(sum(e == ['deferred:', 'primary-budget'] for e in errors), 3, errors)
        self.assertGreaterEqual(len({c['headers'].get('Authorization') for c in self.upstream()}), 2)
        self.assert_no_secret()

    def test_graphql_and_rest_spend_their_own_installation_pools(self):
        """C8-budget: an exhausted GraphQL pool defers GraphQL reads while REST still reads."""
        rate = fixture('rate-limit.json')
        rate['resources']['graphql'].update(remaining=0, reset=int(time.time()) + 3000)
        self.github['rate'] = rate
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        query = 'query { viewer { login } }'
        code, out, err = self.read('graphql', REPO, stdin=query)
        self.assertEqual((code, out, err.split(' ')[0:2]), (1, '', ['deferred:', 'primary-budget']))
        self.assertEqual(self.upstream('/graphql'), [])
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')[0], 0)

    def test_primary_reset_and_secondary_backoff_persist_across_processes(self):
        """C8-budget: rate-limit answers set shared deadlines a new process or token cannot clear."""
        reset = int(time.time()) + 900
        self.route('/repos/synthetic-owner/work/issues/1', {'message': PROVIDER_BODY}, status=403,
                   headers={'x-ratelimit-remaining': '0', 'x-ratelimit-limit': '5000',
                            'x-ratelimit-reset': str(reset), 'x-ratelimit-resource': 'core'})
        for _ in range(2):
            self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1', purpose='authority'),
                             (1, '', f'deferred: primary-budget until={reset}'))
        self.assertEqual(len(self.upstream()), 1)
        self.route('/repos/synthetic-owner/work/issues/2', {'message': PROVIDER_BODY}, status=429,
                   headers={'Retry-After': '30'})
        self.route('/repos/synthetic-owner/work/issues/3', {'message': PROVIDER_BODY}, status=429)
        self.github['rate'] = fixture('rate-limit.json')
        state = self.reads / 'installation-2002.json'
        record = json.loads(state.read_text())
        record['pools']['rest'] = None
        record['probe_not_before'] = 0  # model a newly eligible probe after reset
        state.write_text(json.dumps(record))
        start = time.time()
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/2', purpose='authority')
        self.assertEqual((code, out, err.split('=')[0]), (1, '', 'deferred: backoff until'))
        self.assertTrue(start + 29 <= int(err.split('=')[1]) <= time.time() + 31, err)
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/2', purpose='authority')[2], err)
        self.assertEqual(len(self.upstream()), 2)
        # Without Retry-After, GitHub's one-minute minimum, then a longer bounded wait.
        for expected in (60, 120):
            record = json.loads(state.read_text())
            record['secondary_not_before'] = 0
            state.write_text(json.dumps(record))
            start = time.time()
            err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/3', purpose='authority')[2]
            until = int(err.split('=')[1])
            self.assertTrue(start + expected - 1 <= until <= time.time() + expected + 1, (expected, err))
        self.assert_no_secret()

    def test_low_budget_paces_reads(self):
        """C8-budget: below a tenth of the pool, reads are spread until the reset."""
        rate = fixture('rate-limit.json')
        rate['resources']['core'].update(limit=100, remaining=5, reset=int(time.time()) + 100)
        self.github['rate'] = rate
        self.route('/repos/synthetic-owner/work/issues/1', {'number': 1})
        self.route('/repos/synthetic-owner/work/issues/2', {'number': 2})
        self.assertEqual(self.read('rest', REPO, 'repos/synthetic-owner/work/issues/1')[0], 0)
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/2')
        self.assertEqual((code, out, err.split('=')[0]), (1, '', 'deferred: backoff until'))
        self.assertEqual(len(self.upstream()), 1)


class ReadOnly(Fixture):
    def test_writes_and_unallowlisted_requests_refuse_before_any_call(self):
        """C8-write: mutations, other methods, hosts, repositories and endpoints never run."""
        mutation = 'mutation { addComment(input: {subjectId: $id, body: $b}) { clientMutationId } }'
        cases = [
            (('rest', REPO, 'repos/synthetic-owner/work/issues', '--method', 'POST'), '', 2, None),
            (('graphql', REPO), mutation, 1, 'refused: shape'),
            (('graphql', REPO), 'query A { viewer { login } } mutation B { x }', 1, 'refused: shape'),
            (('graphql', REPO), 'subscription { x }', 1, 'refused: shape'),
            (('graphql', REPO), 'query A { a } query B { b }', 1, 'refused: shape'),
            (('graphql', REPO), 'query { repository(owner: "synthetic-owner", name: "other") { id } }',
             1, 'refused: shape'),
            (('graphql', REPO, '--variables', '{"owner":"synthetic-owner","name":"other"}'),
             'query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { id } }',
             1, 'refused: binding'),
            (('rest', REPO, 'app/installations/2002/access_tokens'), '', 1, 'refused: shape'),
            (('rest', REPO, 'https://api.github.com/repos/synthetic-owner/work/issues'), '', 1, 'refused: shape'),
            (('rest', REPO, 'repos/synthetic-owner/work/../other/issues'), '', 1, 'refused: shape'),
            (('rest', REPO, 'repos/synthetic-owner/other/issues'), '', 1, 'refused: binding'),
            (('rest', 'synthetic-owner/unselected', 'repos/synthetic-owner/unselected/issues'), '', 1,
             'refused: binding'),
            (('rest', REPO, 'repos/synthetic-owner/work/issues', '--accept', 'text/html'), '', 1, 'refused: shape'),
        ]
        for args, stdin, code, message in cases:
            with self.subTest(args=args):
                result = self.read(*args, stdin=stdin)
                self.assertEqual(result[0], code, result)
                self.assertEqual(result[1], '')
                if message:
                    self.assertEqual(result[2], message)
        self.assertEqual(self.calls, [])



class ReviewRegressions(Fixture):
    """R1–R10: observable C1 gaps missing from the original happy-path proofs.

    Synthetic assumptions: the fixture can omit pagination/limit evidence,
    revoke a grant, change conditional metadata, delay or drop a response.
    No test authorizes or observes a live installation.
    """
    endpoint = 'repos/synthetic-owner/work/issues/1'
    connection = ('query($owner: String!, $name: String!, $n: Int!) { '
                  'repository(owner: $owner, name: $name) { issues(first: $n) { '
                  'nodes { number } pageInfo { hasNextPage hasPreviousPage } } } }')

    def graphql(self, query=None, n=2, **kwargs):
        return self.read('graphql', REPO, '--variables', json.dumps({
            'owner': 'synthetic-owner', 'name': 'work', 'n': n}),
            stdin=query or self.connection, **kwargs)

    def process(self, endpoint=None, **kwargs):
        proc = subprocess.Popen(self.command('rest', REPO, endpoint or self.endpoint, **kwargs),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(self.stop, proc)
        return proc

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.kill()
            proc.communicate(timeout=10)

    def wait_for(self, predicate):
        end = time.monotonic() + 10
        while not predicate() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(predicate(), 'fixture never reached the expected request')

    @contextmanager
    def completed_mint_waiting_on_lock(self, **kwargs):
        """Hold a mint response until the parent owns the publication lock."""
        gate = self.github['mint_hold'] = threading.Event()
        self.addCleanup(gate.set)
        proc = self.process(purpose='authority', **kwargs)
        self.wait_for(lambda: len(self.mints()) == 1)
        path = self.reads / 'installation-2002.lock'
        path.touch(mode=0o600, exist_ok=True)
        with path.open('r+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            gate.set()
            self.wait_for(lambda: not Path(
                f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().strip())
            try:
                yield proc
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def test_r2_older_mint_cannot_restore_a_newer_invalidated_generation(self):
        # C8-auth: warm-cache/direct denial proofs did not interleave mint publication.
        self.route('/' + self.endpoint, {'number': 1})
        with self.completed_mint_waiting_on_lock() as first:
            os.kill(first.pid, signal.SIGSTOP)
            self.addCleanup(lambda: os.kill(first.pid, signal.SIGCONT)
                            if first.poll() is None else None)
            self.wait_for(lambda: 'State:\tT' in Path(f'/proc/{first.pid}/status').read_text())
        self.github['mint_status'] = 500
        self.assertEqual(self.read('rest', REPO, self.endpoint, purpose='authority'),
                         (1, '', 'refused: credential'))
        os.kill(first.pid, signal.SIGCONT)
        out, err = first.communicate(timeout=15)
        self.assertEqual((first.returncode, out, err.decode().strip()),
                         (1, b'', 'refused: credential'))
        self.assertEqual(len(self.upstream()), 0)
        # Only a genuinely subsequent successful observation may recover.
        self.github['mint_status'] = 201
        self.assertEqual(self.read('rest', REPO, self.endpoint)[2], 'fresh: current')
        self.assert_no_secret()

    def test_r5_mint_observation_age_includes_the_publication_lock_wait(self):
        # C8-freshness: slow HTTP/probe cases missed a completed mint waiting on flock.
        self.route('/' + self.endpoint, {'number': 1})
        with self.completed_mint_waiting_on_lock(max_age='1') as proc:
            threading.Event().wait(1.3)  # deliberately beyond the explicit one-second bound
        out, err = proc.communicate(timeout=15)
        self.assertEqual((proc.returncode, out, err.decode().strip()),
                         (1, b'', 'refused: freshness'))
        self.assertEqual(len(self.upstream()), 0)

    def test_r3_delayed_headers_never_absorb_another_requests_uncertain_spend(self):
        # C8-budget: the earlier crash proof had no concurrent successful settlement.
        for api, capacity, remaining, missing in (
                ('rest', 2, 1, 'disconnect'), ('rest', 2, 1, 'headers'),
                ('graphql', 7, 4, 'disconnect'), ('graphql', 7, 4, 'headers')):
            with self.subTest(api=api, missing=missing):
                state = self.reads / 'installation-2002.json'
                if state.exists():
                    state.unlink()
                reset = int(time.time()) + 300
                rate = fixture('rate-limit.json')
                rate['resources']['core' if api == 'rest' else 'graphql'].update(
                    limit=10, remaining=capacity, reset=reset)
                self.github['rate'] = rate
                headers = {'x-ratelimit-resource': 'core' if api == 'rest' else 'graphql',
                           'x-ratelimit-limit': '10', 'x-ratelimit-remaining': str(remaining),
                           'x-ratelimit-reset': str(reset)}
                hold = self.github['hold'] = threading.Event()
                self.github['hold_entered'].clear()
                self.addCleanup(hold.set)
                prefix = '/repos/' if api == 'rest' else '/graphql'
                before = len(self.upstream(prefix))
                if api == 'rest':
                    self.route('/' + self.endpoint, {'number': 1}, headers=headers)
                    second = self.endpoint.replace('/1', '/2')
                    third = self.endpoint.replace('/1', '/3')
                    self.route('/' + second, {'number': 2}, disconnect=missing == 'disconnect')
                    self.route('/' + third, {'number': 3})
                    first = self.process(purpose='authority')
                    invoke = lambda ep: self.read('rest', REPO, ep, purpose='authority')
                else:
                    body = {'data': {'repository': {'issues': {'nodes': [], 'pageInfo': {
                        'hasNextPage': False, 'hasPreviousPage': False}}}}}
                    self.github['graphql_responses'] = {
                        2: {'body': body, 'headers': headers},
                        3: {'body': body, 'disconnect': missing == 'disconnect'},
                        1: {'body': body}}
                    variables = json.dumps({'owner': 'synthetic-owner', 'name': 'work', 'n': 2})
                    first = subprocess.Popen(self.command('graphql', REPO, '--variables', variables,
                                                         purpose='authority'), stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self.addCleanup(self.stop, first)
                    first.stdin.write(self.connection.encode())
                    first.stdin.close()
                    first.stdin = None
                    second, third = 3, 1
                    invoke = lambda n: self.graphql(n=n, purpose='authority')
                self.wait_for(lambda: self.github['hold_entered'].is_set())
                self.assertEqual(len(self.upstream(prefix)), before + 1)
                # Only the first response stays delayed. A headerless success or
                # lost second response settles before its older header arrives.
                self.github['hold'] = None
                result = invoke(second)
                self.assertEqual(result[0], 1 if missing == 'disconnect' else 0, result)
                hold.set()
                out, err = first.communicate(timeout=15)
                self.assertEqual((first.returncode, err.decode().strip()), (0, 'fresh: current'))
                code, out, err = invoke(third)
                self.assertEqual((code, out, err.split(' until=')[0]),
                                 (1, '', 'deferred: primary-budget'))
                self.assertEqual(len(self.upstream(prefix)), before + 2)

    def test_r3_reset_changes_cannot_refund_uncertain_spend(self):
        # C8-budget: previous mixed-settlement cases never crossed reset. These
        # synthetic headers model A's new-window snapshot before B spends,
        # delivered after B settles. Admission time cannot identify spend time.
        for api in ('rest', 'graphql'):
            for cross in (False, True):
                for response in ('headerless', 'disconnect', 'accounted'):
                    with self.subTest(api=api, cross_reset=cross, response=response):
                        self.reset_ordering_case(api, cross, response)

    def reset_ordering_case(self, api, cross, response):
        state_path = self.reads / 'installation-2002.json'
        if state_path.exists():
            state_path.unlink()
        resource = 'core' if api == 'rest' else 'graphql'
        capacity, after_a, debit = (2, 1, 1) if api == 'rest' else (7, 4, 4)
        # Both callers must reach their barriers before the old deadline.
        old_reset = int(time.time()) + (4 if cross else 300)
        reset = old_reset + 300 if cross else old_reset
        rate = fixture('rate-limit.json')
        rate['resources'][resource].update(limit=20, remaining=capacity, reset=old_reset)
        self.github['rate'] = rate
        headers = {'x-ratelimit-resource': resource, 'x-ratelimit-limit': '20',
                   'x-ratelimit-remaining': str(after_a), 'x-ratelimit-reset': str(reset)}
        b_headers = dict(headers, **{'x-ratelimit-remaining': '0'}) if response == 'accounted' else {}
        prefix = '/repos/' if api == 'rest' else '/graphql'
        before = len(self.upstream(prefix))
        if api == 'rest':
            first, second, third = (self.endpoint.replace('/1', '/' + str(n)) for n in (1, 2, 3))
            self.route('/' + first, {'number': 1}, headers=headers)
            self.route('/' + second, {'number': 2}, headers=b_headers,
                       disconnect=response == 'disconnect')
            self.route('/' + third, {'number': 3})
            invoke = lambda ep: self.read('rest', REPO, ep, purpose='authority')
        else:
            first, second, third = 2, 3, 1  # conservative costs 3, 4, 2
            body = {'data': {'repository': {'issues': {'nodes': [], 'pageInfo': {
                'hasNextPage': False, 'hasPreviousPage': False}}}}}
            self.github['graphql_responses'] = {
                first: {'body': body, 'headers': headers},
                second: {'body': body, 'headers': b_headers, 'disconnect': response == 'disconnect'},
                third: {'body': body}}
            invoke = lambda n: self.graphql(n=n, purpose='authority')

        def start(value):
            if api == 'rest':
                return self.process(value, purpose='authority')
            variables = json.dumps({'owner': 'synthetic-owner', 'name': 'work', 'n': value})
            proc = subprocess.Popen(self.command('graphql', REPO, '--variables', variables,
                                                 purpose='authority'), stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(self.stop, proc)
            proc.stdin.write(self.connection.encode())
            proc.stdin.close()
            proc.stdin = None
            return proc

        hold_a, hold_b = threading.Event(), threading.Event()
        self.addCleanup(hold_a.set)
        self.addCleanup(hold_b.set)
        try:
            self.github['hold'] = hold_a
            self.github['hold_entered'].clear()
            a = start(first)
            self.wait_for(lambda: self.github['hold_entered'].is_set())
            self.github['hold'] = hold_b
            self.github['hold_entered'].clear()
            b = start(second)
            self.wait_for(lambda: self.github['hold_entered'].is_set())
            self.assertLess(time.time(), old_reset, 'both admissions must precede reset')
            if cross:
                threading.Event().wait(max(0, old_reset + .1 - time.time()))
            # A snapshots before B spends; only response delivery is reordered.
            hold_b.set()
            bo, be = b.communicate(timeout=15)
            expected = ((1, b'', 'refused: incomplete') if response == 'disconnect' else
                        (1, b'', 'refused: freshness') if cross and response == 'headerless' else
                        None)
            if expected is None:
                self.assertEqual((b.returncode, be.decode().strip()), (0, 'fresh: current'))
                self.assertEqual(json.loads(bo), {'number': 2} if api == 'rest' else body)
            else:
                self.assertEqual((b.returncode, bo, be.decode().strip()), expected)
            pool = json.loads(state_path.read_text())['pools'][api]
            expected_debit = 0 if response == 'accounted' else debit
            self.assertEqual(pool.get('unconfirmed_spent', 0), expected_debit)
            hold_a.set()
            ao, ae = a.communicate(timeout=15)
            self.assertEqual((a.returncode, ae.decode().strip()), (0, 'fresh: current'))
            pool = json.loads(state_path.read_text())['pools'][api]
            self.github['hold'] = None
            code, out, err = invoke(third)
            self.assertEqual((code, out, err.split(' until=')[0]),
                             (1, '', 'deferred: primary-budget'))
            self.assertEqual(len(self.upstream(prefix)), before + 2)
            self.assertEqual(pool['unconfirmed_spent'], expected_debit)
        finally:
            hold_a.set()
            hold_b.set()
            self.github['hold'] = None

    def test_r3_unknown_observation_and_new_window_probe_keep_uncertain_spend(self):
        # C8-budget: an invalid response can replace the provider observation,
        # but cannot erase earlier unresolved spending when a later probe succeeds.
        for api in ('rest', 'graphql'):
            with self.subTest(api=api):
                path = self.reads / 'installation-2002.json'
                if path.exists():
                    path.unlink()
                resource = 'core' if api == 'rest' else 'graphql'
                capacity = 3 if api == 'rest' else 7
                reset = int(time.time()) + 300
                rate = fixture('rate-limit.json')
                rate['resources'][resource].update(limit=20, remaining=capacity, reset=reset)
                self.github['rate'] = rate
                invalid = {'x-ratelimit-resource': resource, 'x-ratelimit-limit': '20',
                           'x-ratelimit-remaining': '0',
                           'x-ratelimit-reset': str(int(time.time()) - 1)}
                prefix = '/repos/' if api == 'rest' else '/graphql'
                before = len(self.upstream(prefix))
                if api == 'rest':
                    first, second, third = (self.endpoint.replace('/1', '/' + str(n))
                                            for n in (1, 2, 3))
                    self.route('/' + first, {'number': 1})
                    self.route('/' + second, {'number': 2}, headers=invalid)
                    self.route('/' + third, {'number': 3})
                    invoke = lambda ep: self.read('rest', REPO, ep, purpose='authority')
                else:
                    first, second, third = 2, 3, 1
                    body = {'data': {'repository': {'issues': {'nodes': [], 'pageInfo': {
                        'hasNextPage': False, 'hasPreviousPage': False}}}}}
                    self.github['graphql_responses'] = {
                        first: {'body': body}, second: {'body': body, 'headers': invalid},
                        third: {'body': body}}
                    invoke = lambda n: self.graphql(n=n, purpose='authority')
                self.assertEqual(invoke(first)[2], 'fresh: current')
                self.assertEqual(invoke(second), (1, '', 'refused: freshness'))
                # Model the persisted scheduler cooldown having elapsed, without
                # waiting 60 seconds; all debit and provider evidence is untouched.
                state = json.loads(path.read_text())
                state['probe_not_before'] = time.time() - 1
                path.write_text(json.dumps(state))
                # Neither unsettled request has a proven spending window.
                unresolved = 2 if api == 'rest' else 7
                rate['resources'][resource].update(remaining=unresolved, reset=reset + 300)
                probes = len(self.upstream('/rate_limit'))
                code, out, err = invoke(third)
                self.assertEqual((code, out, err.split(' until=')[0]),
                                 (1, '', 'deferred: primary-budget'))
                self.assertEqual(len(self.upstream('/rate_limit')), probes + 1)
                self.assertEqual(len(self.upstream(prefix)), before + 2)

    def test_r4_pagination_preserves_resource_and_nonpagination_parameters(self):
        # C8-pages: earlier checks bound only host/repository, not resource/filter.
        ep = self.endpoint + '/comments?per_page=1&sort=created&direction=asc'
        for conditional in (False, True):
            for switch in ('resource', 'filter', 'page-size'):
                with self.subTest(conditional=conditional, switch=switch):
                    self.route('/' + ep, [{'id': 1}], etag='"one"')
                    if conditional:
                        self.assertEqual(self.read('rest', REPO, ep, purpose='authority')[0], 0)
                    target = '/' + ep + '&page=2'
                    if switch == 'resource':
                        target = target.replace('/issues/1/', '/issues/2/')
                    elif switch == 'filter':
                        target = target.replace('direction=asc', 'direction=desc')
                    else:
                        target = target.replace('per_page=1', 'per_page=2')
                    self.route(target, [{'id': 999}])
                    route = self.github['routes']['/' + ep]
                    route['headers'] = {'Link': f'<{self.base}{target}>; rel="next"'}
                    route['force_200'] = not conditional
                    self.assertEqual(self.read('rest', REPO, ep, purpose='authority'),
                                     (1, '', 'refused: incomplete'))
                    self.assertEqual(self.upstream(target), [])
        page2 = '/' + ep + '&page=2'
        self.route(page2, [{'id': 2}])
        self.github['routes']['/' + ep]['headers'] = {'Link': f'<{self.base}{page2}>; rel="next"'}
        code, out, err = self.read('rest', REPO, ep, purpose='authority')
        self.assertEqual((code, err, [json.loads(line) for line in out.splitlines()]),
                         (0, 'fresh: current', [[{'id': 1}], [{'id': 2}]]))
        self.assertEqual(len(self.upstream(page2)), 1)

    def test_r1_connection_completeness_follows_query_selections(self):
        # Omitted and aliased pageInfo evaded the response-only walker.
        for selection, body in (
            ('nodes { number }', {'nodes': [{'number': 1}]}),
            ('nodes { number } info: pageInfo { more: hasNextPage }',
             {'nodes': [], 'info': {'more': True}}),
            ('nodes { number } pageInfo { hasNextPage hasPreviousPage }',
             {'nodes': [], 'pageInfo': {'hasNextPage': False}})):
            with self.subTest(selection=selection):
                query = self.connection.replace(
                    'nodes { number } pageInfo { hasNextPage hasPreviousPage }', selection)
                self.github['graphql'] = {'body': {'data': {'repository': {'issues': body}}}}
                self.assertEqual(self.graphql(query, purpose='authority'),
                                 (1, '', 'refused: incomplete'))
        query = self.connection.replace('pageInfo { hasNextPage hasPreviousPage }',
                                        'info: pageInfo { more: hasNextPage before: hasPreviousPage }')
        self.github['graphql'] = {'body': {'data': {'repository': {'issues': {
            'nodes': [], 'info': {'more': False, 'before': False}}}}}}
        self.assertEqual(self.graphql(query)[2], 'fresh: current')

    def test_r2_warm_cache_rechecks_missing_and_revoked_credentials(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.assertEqual(self.read('rest', REPO, self.endpoint)[0], 0)
        key = self.state / 'service/app/private-key.pem'
        key.unlink()
        self.assertEqual(self.read('rest', REPO, self.endpoint), (1, '', 'refused: credential'))
        key.write_bytes(self.pem)
        key.chmod(0o600)
        self.github['mint_status'] = 404
        self.assertEqual(self.read('rest', REPO, self.endpoint), (1, '', 'refused: credential'))
        self.assertEqual(len(self.upstream()), 1)
        self.assert_no_secret()

    def test_r2_denied_read_invalidates_warm_cache(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.assertEqual(self.read('rest', REPO, self.endpoint)[0], 0)
        self.route('/' + self.endpoint, {'message': PROVIDER_BODY}, status=403)
        self.assertEqual(self.read('rest', REPO, self.endpoint, purpose='authority'),
                         (1, '', 'refused: credential'))
        self.route('/' + self.endpoint, {'number': 2})
        result = self.read('rest', REPO, self.endpoint)
        self.assertEqual((result[0], result[2], json.loads(result[1])),
                         (0, 'fresh: current', {'number': 2}))

    def test_r3_crash_and_transport_failure_do_not_replenish_budget(self):
        for failure in ('crash', 'disconnect'):
            with self.subTest(failure=failure):
                state = self.reads / 'installation-2002.json'
                if state.exists():
                    state.unlink()
                for entry in self.reads.glob('entry-*'):
                    entry.unlink()
                rate = fixture('rate-limit.json')
                rate['resources']['core'].update(limit=3, remaining=1, reset=int(time.time()) + 300)
                self.github['rate'] = rate
                self.route('/' + self.endpoint, {'number': 1}, disconnect=failure == 'disconnect')
                before = len(self.upstream())
                if failure == 'crash':
                    self.github['hold'] = threading.Event()
                    proc = self.process()
                    self.wait_for(lambda: len(self.upstream()) == before + 1)
                    self.stop(proc)
                    self.github['hold'].set()
                    self.github['hold'] = None
                else:
                    self.assertEqual(self.read('rest', REPO, self.endpoint)[0:2], (1, ''))
                self.route('/repos/synthetic-owner/work/issues/2', {'number': 2})
                code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/2')
                self.assertEqual((code, out, err.split(' until=')[0]),
                                 (1, '', 'deferred: primary-budget'))
                self.assertEqual(len(self.upstream()), before + 1)

    def test_r4_conditional_metadata_extends_or_refuses_the_page_chain(self):
        ep = self.endpoint + '/comments?per_page=1'
        page2 = '/' + ep + '&page=2'
        self.route('/' + ep, [{'id': 1}], etag='"one"')
        self.assertEqual(self.read('rest', REPO, ep)[0], 0)
        self.route(page2, [{'id': 2}])
        route = self.github['routes']['/' + ep]
        route['headers'] = {'Link': f'<{self.base}{page2}>; rel="next"'}
        code, out, err = self.read('rest', REPO, ep, purpose='authority')
        self.assertEqual((code, err, [json.loads(line) for line in out.splitlines()]),
                         (0, 'fresh: current', [[{'id': 1}], [{'id': 2}]]))
        self.assertEqual(len(self.upstream(page2)), 1)
        for target in ('/' + ep, '/repos/synthetic-owner/other/issues?page=2'):
            route['headers'] = {'Link': f'<{self.base}{target}>; rel="next"'}
            self.assertEqual(self.read('rest', REPO, ep, purpose='authority'),
                             (1, '', 'refused: incomplete'))
        self.assertEqual(self.upstream('/repos/synthetic-owner/other'), [])

    def test_r5_slow_read_cannot_publish_expired_authorization_evidence(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.github['delay'] = 1.2
        self.assertEqual(self.read('rest', REPO, self.endpoint, purpose='authority', max_age='1'),
                         (1, '', 'refused: freshness'))
        self.assertEqual(list(self.reads.glob('entry-*')), [])

    def test_r5_zero_age_refuses_before_admitting_a_stale_read(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.assertEqual(self.read('rest', REPO, self.endpoint, purpose='authority', max_age='0'),
                         (1, '', 'refused: freshness'))
        self.assertEqual(len(self.upstream()), 0)

    def test_r5_slow_probe_rechecks_authorization_before_data_admission(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.github['rate_delay'] = 1.2
        self.assertEqual(self.read('rest', REPO, self.endpoint, purpose='authority', max_age='1'),
                         (1, '', 'refused: freshness'))
        self.assertEqual(len(self.upstream()), 0)

    def test_r5_stale_budget_must_be_observed_before_admission(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.assertEqual(self.read('rest', REPO, self.endpoint)[0], 0)
        path = self.reads / 'installation-2002.json'
        state = json.loads(path.read_text())
        state['pools']['rest']['observed_at'] = time.time() - 10
        path.write_text(json.dumps(state))
        self.github['rate_status'] = 500
        self.route('/repos/synthetic-owner/work/issues/2', {'number': 2})
        code, out, err = self.read('rest', REPO, 'repos/synthetic-owner/work/issues/2', max_age='1')
        self.assertEqual((code, out, err.split(' until=')[0]), (1, '', 'deferred: budget-unknown'))
        self.assertEqual(len(self.upstream()), 1)

    def test_r6_sequential_authority_calls_never_reuse_a_completed_entry(self):
        self.route('/' + self.endpoint, {'number': 1}, etag='"one"')
        for _ in range(2):
            self.assertEqual(self.read('rest', REPO, self.endpoint, purpose='authority',
                                       extra=('--challenge', str(int(time.time()) - 10)))[2],
                             'fresh: current')
        self.assertEqual(len(self.upstream()), 2)
        self.assertEqual(self.upstream()[1]['headers'].get('If-None-Match'), '"one"')

    def test_r7_numeric_repository_links_refuse_before_fetch(self):
        self.route('/' + self.endpoint, {'number': 1},
                   link='<BASE/repositories/999/issues/1?page=2>; rel="next"')
        self.route('/repositories/999/issues/1?page=2', {'number': 2})
        self.assertEqual(self.read('rest', REPO, self.endpoint), (1, '', 'refused: incomplete'))
        self.assertEqual(self.upstream('/repositories/'), [])

    def test_r8_graphql_cost_is_reserved_across_processes_without_headers(self):
        rate = fixture('rate-limit.json')
        rate['resources']['graphql'].update(limit=10, remaining=5, reset=int(time.time()) + 300)
        self.github.update(rate=rate, hold=threading.Event(), graphql={'body': {
            'data': {'repository': {'issues': {'nodes': [], 'pageInfo': {
                'hasNextPage': False, 'hasPreviousPage': False}}}}}})
        # Both mints must postdate the same challenge, regardless of completion
        # order; this proof exercises quota reservation, not mint freshness.
        challenge = str(int(time.time()) - 1)
        procs = []
        for n in (2, 3):  # conservative bounds 3 and 4; together exceed five points
            variables = json.dumps({'owner': 'synthetic-owner', 'name': 'work', 'n': n})
            proc = subprocess.Popen(self.command('graphql', REPO, '--variables', variables,
                                                 purpose='authority', extra=('--challenge', challenge)),
                                    stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.addCleanup(self.stop, proc)
            proc.stdin.write(self.connection.encode())
            proc.stdin.close()
            proc.stdin = None
            procs.append(proc)
        self.wait_for(lambda: len(self.upstream('/graphql')) >= 1)
        self.wait_for(lambda: len(self.upstream('/graphql')) == 2 or
                      any(p.poll() is not None for p in procs))
        self.github['hold'].set()
        results = [(p.communicate(timeout=15), p.returncode) for p in procs]
        self.assertEqual(sorted(code for _, code in results), [0, 1], results)
        self.assertEqual(len(self.upstream('/graphql')), 1)
        code, out, err = self.graphql(n=4, purpose='authority')
        self.assertEqual((code, out, err.split(' until=')[0]), (1, '', 'deferred: primary-budget'))
        self.assertEqual(len(self.upstream('/graphql')), 1)

    def test_r8_actual_headers_reconcile_a_conservative_query_bound(self):
        rate = fixture('rate-limit.json')
        rate['resources']['graphql'].update(limit=10, remaining=5, reset=int(time.time()) + 300)
        self.github.update(rate=rate, graphql={'body': {
            'data': {'repository': {'issues': {'nodes': [], 'pageInfo': {
                'hasNextPage': False, 'hasPreviousPage': False}}}}}, 'headers': {
                    'x-ratelimit-resource': 'graphql', 'x-ratelimit-limit': '10',
                    'x-ratelimit-remaining': '4',
                    'x-ratelimit-reset': str(rate['resources']['graphql']['reset'])}})
        self.assertEqual(self.graphql(n=2, purpose='authority')[2], 'fresh: current')
        self.github['graphql']['headers']['x-ratelimit-remaining'] = '3'
        # The first bound was three, but the actual response spent one: four
        # points remain, so the next bound of four can be admitted.
        self.assertEqual(self.graphql(n=3, purpose='authority')[2], 'fresh: current')
        self.assertEqual(len(self.upstream('/graphql')), 2)
        for query in ('query { viewer { repositories { nodes { id } } } }',
                      'query { viewer { ...User } } fragment User on User { login }',
                      self.connection.replace('first: $n', 'first: $missing')):
            with self.subTest(query=query):
                self.assertEqual(self.graphql(query), (1, '', 'refused: incomplete'))
        self.assertEqual(len(self.upstream('/graphql')), 2)

    def test_r9_later_challenge_never_overwrites_an_active_leader(self):
        self.route('/' + self.endpoint, {'number': 1})
        self.github['hold'] = threading.Event()
        first = self.process(purpose='authority')
        self.wait_for(lambda: len(self.upstream()) == 1)
        second = self.process(purpose='authority')
        self.wait_for(lambda: len(self.mints()) >= 2)
        self.github['hold'].set()
        results = [(p.communicate(timeout=15), p.returncode) for p in (first, second)]
        self.assertEqual([code for _, code in results], [0, 0], results)
        self.assertEqual(len(self.upstream()), 2)

    def test_r10_failed_budget_probes_have_a_persisted_retry_deadline(self):
        self.route('/' + self.endpoint, {'number': 1})
        for response in ({'rate_status': 500}, {'rate_status': 200, 'rate': {'resources': {}}}):
            with self.subTest(response=response):
                state = self.reads / 'installation-2002.json'
                if state.exists():
                    state.unlink()
                self.calls.clear()
                self.github.update(response)
                results = [self.read('rest', REPO, self.endpoint) for _ in range(2)]
                for code, out, err in results:
                    self.assertEqual((code, out, err.split(' until=')[0]),
                                     (1, '', 'deferred: budget-unknown'))
                    self.assertIn(' until=', err)
                self.assertEqual(results[0][2], results[1][2])
                self.assertEqual(len(self.upstream('/rate_limit')), 1)
                self.assertEqual(self.upstream(), [])

if __name__ == '__main__':
    unittest.main()
