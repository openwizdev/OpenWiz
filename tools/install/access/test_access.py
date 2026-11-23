import importlib.util
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import access
sys.path.insert(0, str(ROOT / 'tools/install/access/fixtures'))
from provider import Recording, credentials, jwt, selected


class Access(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='openwiz-access-tool-')
        self.root = Path(self.temp.name)
        self.state = self.root / 'state'
        self.plan_file = self.root / 'plan.json'
        self.secret_file = self.root / 'secrets.json'
        self.p = selected()
        self.secrets = credentials()
        self.provider = Recording(self.p, self.secrets)
        self.provider.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations': access.store.Store(str(self.state)).read()['operations']}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        for path, value in [(self.plan_file, self.p), (self.secret_file, self.secrets)]:
            path.write_text(json.dumps(value))
            path.chmod(0o600)

    def run_tool(self, *args):
        return access.execute(['configure', '--state-dir', str(self.state), '--plan', str(self.plan_file), *args],
                              http=self.provider, local=self.provider.local)

    def preview(self):
        return self.run_tool()['operation']

    def apply(self, operation):
        return self.run_tool('--yes', '--operation', operation['operation_id'], '--secrets', str(self.secret_file))

    def test_exact_confirmation_and_private_durable_proposal_precede_provider_reads(self):
        proposed = self.preview()
        self.assertEqual(proposed['phase'], 'proposed')
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.preview()['operation_id'], proposed['operation_id'])
        with self.assertRaises(access.store.Refused):
            self.apply({**proposed, 'operation_id': '0' * 32})
        self.assertEqual(self.provider.calls, [])
        self.p['host'] = 'another.synthetic.invalid'
        self.save()
        with self.assertRaises(access.store.Refused):
            self.apply(proposed)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(os.stat(self.state / 'setup/state.json').st_mode & 0o777, 0o600)

    def test_late_claim_cannot_overwrite_a_newer_committed_verification(self):
        operation = self.preview()
        start_check = access.store.Store.start_check
        newer = []
        saved = []
        def interleaved(store):
            generation = start_check(store)
            if generation == 1:
                newer.append(self.apply(operation))
                saved.append((self.state / 'setup/state.json').read_bytes())
            return generation
        with patch.object(access.store.Store, 'start_check', interleaved):
            with self.assertRaises(access.store.Superseded):
                self.apply(operation)
        self.assertEqual(newer[0]['observation']['code'], 'access_cloudflare_verified')
        state = access.store.Store(str(self.state)).read()
        self.assertEqual(state['checks'], {'started': 2, 'committed': 2})
        self.assertEqual(state['observations']['remote_access']['code'], 'access_cloudflare_verified')
        self.assertEqual((self.state / 'setup/state.json').read_bytes(), saved[0],
                         'the late caller must mutate neither the observation nor the newer witness')

    def test_cloudflare_refusal_gates_and_unknowns_never_verify_a_tunnel_process(self):
        operation = self.preview()
        for identity in ('anonymous', 'expired', 'foreign'):
            with self.subTest(identity=identity):
                self.provider.leak = {identity}
                result = self.apply(operation)
                self.assertEqual(result['observation']['code'], 'access_refused')
                self.assertEqual(result['operation']['phase'], 'uncertain')
        self.provider.leak = set()
        for mutate, undo in [
            (lambda: self.provider.config['ingress'][0]['originRequest']['access'].update(required=False),
             lambda: self.provider.config['ingress'][0]['originRequest']['access'].update(required=True)),
            (lambda: self.provider.policies[0].update(include=[{'everyone': {}}]),
             lambda: self.provider.policies[0].update(include=[{'email': {'email': self.p['owner']}}])),
            (lambda: self.provider.tunnel.update(config_src='local'), lambda: self.provider.tunnel.update(config_src='cloudflare')),
        ]:
            mutate()
            self.assertEqual(self.apply(operation)['observation']['code'], 'access_refused')
            undo()
        self.provider.offline = True
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_unavailable')
        self.provider.offline = False
        self.provider.apps.append({'id': 'synthetic-shadow', 'type': 'self_hosted', 'domain': self.p['host'] + '/api'})
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_refused')
        self.provider.apps.pop()
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_cloudflare_verified')
        saved = (self.state / 'setup/state.json').read_text()
        for secret in self.secrets.values():
            self.assertNotIn(secret, saved)
        self.assertTrue(all(call[0] == 'GET' for call in self.provider.calls))

    def check_untrusted_context(self, **claims):
        operation = self.preview()
        original = dict(self.secrets)
        for label in ('expired', 'foreign'):
            with self.subTest(context=label):
                self.secrets.update(original)
                email = self.p['owner'] if label == 'expired' else 'foreign@example.invalid'
                expiry = 1 if label == 'expired' else 2_500_000_000
                self.secrets[label] = jwt(email, expiry, **claims)
                self.save()
                result = self.apply(operation)
                self.assertEqual(result['observation']['code'], 'access_unavailable')
                self.assertEqual(result['operation']['phase'], 'uncertain')

    def test_cloudflare_negative_context_wrong_issuer_stays_unknown(self):
        self.check_untrusted_context(iss='https://wrong-team.cloudflareaccess.com')

    def test_cloudflare_negative_context_wrong_audience_stays_unknown(self):
        self.check_untrusted_context(aud=['WrongApplication'])

    def test_cloudflare_negative_context_invalid_signature_stays_unknown(self):
        operation = self.preview()
        original = dict(self.secrets)
        for label in ('expired', 'foreign'):
            with self.subTest(context=label):
                self.secrets.update(original)
                header, payload, signature = self.secrets[label].split('.')
                signature = ('A' if signature[0] != 'A' else 'B') + signature[1:]
                self.secrets[label] = '.'.join((header, payload, signature))
                self.save()
                result = self.apply(operation)
                self.assertEqual(result['observation']['code'], 'access_unavailable')
                self.assertEqual(result['operation']['phase'], 'uncertain')

    def test_cloudflare_hostname_routed_to_another_tunnel_stays_unknown(self):
        self.provider.dns[0]['content'] = '88888888-8888-8888-8888-888888888888.cfargotunnel.com'
        result = self.apply(self.preview())
        self.assertEqual(result['observation']['code'], 'access_unavailable')
        self.assertEqual(result['operation']['phase'], 'uncertain')

    def test_cloudflare_serving_connector_with_stale_config_stays_unknown(self):
        self.provider.clients[0]['config_version'] = 6
        result = self.apply(self.preview())
        self.assertEqual(result['observation']['code'], 'access_unavailable')
        self.assertEqual(result['operation']['phase'], 'uncertain')

    def test_cloudflare_incomplete_or_changed_route_evidence_stays_unknown(self):
        operation = self.preview()
        original = {key: deepcopy(getattr(self.provider, key))
                    for key in ('zones', 'dns', 'clients', 'config_version')}
        stale = deepcopy(self.provider.clients[0])
        stale.update(id='99999999-9999-9999-9999-999999999999', config_version=6)
        stale['conns'][0]['client_id'] = stale['id']
        stale['conns'][0]['id'] = '88888888-8888-8888-8888-888888888888'
        for key, value in [('zones', []), ('dns', []), ('clients', []), ('config_version', None),
                           ('clients', [{'id': self.provider.clients[0]['id'], 'conns': []}]),
                           ('clients', [*self.provider.clients, stale])]:
            for during_probe in (False, True):
                with self.subTest(field=key, value=value, during_probe=during_probe):
                    for field, saved in original.items():
                        setattr(self.provider, field, deepcopy(saved))
                    change = lambda: setattr(self.provider, key, deepcopy(value))
                    if during_probe:
                        self.provider.after_probe = change
                    else:
                        change()
                    self.assertEqual(self.apply(operation)['observation']['code'], 'access_unavailable')
        for field, saved in original.items():
            setattr(self.provider, field, deepcopy(saved))
        for field, value in [('content', '88888888-8888-8888-8888-888888888888.cfargotunnel.com'),
                             ('proxied', False)]:
            self.provider.after_probe = lambda: self.provider.dns[0].update({field: value})
            self.assertEqual(self.apply(operation)['observation']['code'], 'access_unavailable')
            self.provider.dns = deepcopy(original['dns'])
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_cloudflare_verified')

    def test_cloudflare_unavailable_signing_provenance_stays_unknown(self):
        operation = self.preview()
        keys = deepcopy(self.provider.keys)
        for value in ([], keys + keys, [{**keys[0], 'alg': 'HS256'}]):
            with self.subTest(keys=value):
                self.provider.keys = value
                self.assertEqual(self.apply(operation)['observation']['code'], 'access_unavailable')
        self.provider.keys = keys
        with patch.object(access.subprocess, 'run', side_effect=FileNotFoundError('synthetic missing OpenSSL')):
            self.assertEqual(self.apply(operation)['observation']['code'], 'access_unavailable')
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_cloudflare_verified')

    def test_lost_reply_restart_refusal_and_reconnect_reconcile_one_operation(self):
        operation = self.preview()
        self.provider.interrupt = True
        with self.assertRaises(SystemExit):
            self.apply(operation)
        status = access.execute(['status', '--state-dir', str(self.state), '--operation', operation['operation_id']])
        self.assertEqual(status['operation']['phase'], 'uncertain')
        self.assertEqual(status['observation']['code'], 'access_checking')
        self.assertEqual(self.preview()['operation_id'], operation['operation_id'])
        self.provider.interrupt = False
        self.provider.leak = {'foreign'}
        self.assertEqual(self.apply(operation)['operation']['phase'], 'uncertain')
        self.provider.leak = set()
        self.assertEqual(self.apply(operation)['operation']['phase'], 'applied')
        self.assertEqual(self.apply(operation)['operation']['phase'], 'applied')
        self.provider.offline = True
        result = self.apply(operation)
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual(result['observation']['code'], 'access_unavailable')
        self.assertEqual(len(access.store.Store(str(self.state)).read()['operations']), 1)
        self.assertTrue(all(call[0] == 'GET' for call in self.provider.calls))

    def test_current_selection_and_later_checks_supersede_old_access_evidence(self):
        operation = self.preview()
        def changed():
            def update(value):
                value['revision'] += 1
            access.store.Store(str(self.state)).update(update)
        self.provider.after_probe = changed
        with self.assertRaises(access.store.Superseded):
            self.apply(operation)
        saved = access.store.Store(str(self.state)).read()
        self.assertEqual(saved['operations'][0]['phase'], 'uncertain')
        self.assertEqual(saved['observations']['remote_access']['code'], 'access_checking')
        self.p['host'] = 'another.synthetic.invalid'
        self.save()
        with self.assertRaises(access.store.Refused):
            self.preview()
        self.p['host'] = 'openwiz.synthetic.invalid'
        self.save()
        reconciled = access.execute(['reconcile', '--state-dir', str(self.state), '--plan', str(self.plan_file),
                                     '--secrets', str(self.secret_file), '--operation', operation['operation_id'],
                                     '--revision', '0', '--yes'], http=self.provider, local=self.provider.local)
        self.assertEqual(reconciled['operation']['phase'], 'applied')
        self.assertEqual(reconciled['observation']['revision'], 0, 'old evidence never verifies the new selection')
        self.assertNotEqual(self.preview()['operation_id'], operation['operation_id'])
        fresh = self.preview()
        self.provider.after_probe = lambda: access.store.Store(str(self.state)).start_check()
        with self.assertRaises(access.store.Superseded):
            self.apply(fresh)

    def test_bad_private_files_duplicate_keys_and_quick_tunnels_fail_closed(self):
        for value in ['{"schema":"x","schema":"x"}', '[]']:
            self.plan_file.write_text(value)
            with self.assertRaises(access.store.Refused):
                self.preview()
        self.save()
        self.plan_file.chmod(0o644)
        with self.assertRaises(access.store.Refused):
            self.preview()
        self.plan_file.chmod(0o600)
        for host in ('localhost', '127.0.0.1', 'x.trycloudflare.com', 'owner@example.invalid', 'safe.invalid/path'):
            self.p['host'] = host
            self.save()
            with self.assertRaises(access.store.Refused):
                self.preview()
        self.assertEqual(self.provider.calls, [])

    def test_tailscale_checks_active_policy_expiry_and_private_serve(self):
        self.p, self.secrets = selected('tailscale'), credentials('tailscale')
        self.provider = Recording(self.p, self.secrets)
        self.provider.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations': access.store.Store(str(self.state)).read()['operations']}
        self.save()
        operation = self.preview()
        self.provider.status['BackendState'] = 'NeedsLogin'
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_expired')
        self.provider.status['BackendState'] = 'Running'
        self.provider.acl['acls'][0]['src'] = ['*']
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_refused')
        self.provider.acl['acls'][0]['src'] = [self.p['owner']]
        self.provider.status['Self']['Expired'] = True
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_expired')
        self.provider.status['Self']['Expired'] = False
        self.provider.serve['AllowFunnel'][self.p['host'] + ':443'] = True
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_refused')
        self.provider.serve['AllowFunnel'][self.p['host'] + ':443'] = False
        self.provider.validation_body = b'{"message":"synthetic failed test"}'
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_refused')
        self.provider.validation_body = b''
        result = self.apply(operation)
        self.assertEqual(result['observation']['code'], 'access_tailscale_verified')
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual([c[0] for c in self.provider.calls if c[0] != 'local-read'].count('POST'), 2)
        self.assertTrue(all(c[0] in ('GET', 'local-read') or c[-1].endswith('/acl/validate') for c in self.provider.calls))
        del self.provider.status['Self']['Expired']
        del self.provider.serve['AllowFunnel']
        self.assertEqual(self.apply(operation)['observation']['code'], 'access_tailscale_verified')

    def test_expired_owner_cookie_invalidates_previously_applied_readiness(self):
        operation = self.preview()
        self.assertEqual(self.apply(operation)['operation']['phase'], 'applied')
        self.secrets['owner'] = self.secrets['expired']
        self.save()
        result = self.apply(operation)
        self.assertEqual(result['operation']['phase'], 'applied')
        self.assertEqual(result['observation']['code'], 'access_expired')

    def test_positive_evidence_cannot_outlive_the_checked_owner_session(self):
        self.secrets.update(owner=jwt(self.p['owner'], 2_000_000_060),
                            expired=jwt(self.p['owner'], 1_999_999_940),
                            foreign=jwt('foreign@example.invalid', 2_000_007_200))
        self.save()
        with patch.object(access.time, 'time', return_value=2_000_000_000):
            result = self.apply(self.preview())
        self.assertEqual(result['observation']['code'], 'access_cloudflare_verified')
        self.assertEqual(result['observation']['at'], 1_999_996_460_000,
                         'the existing one-hour freshness window must end at 2,000,000,060 seconds')

    def test_owner_probe_must_reach_this_state_and_this_current_check(self):
        for provider in ('cloudflare', 'tailscale'):
            with self.subTest(provider=provider):
                self.state = self.root / provider
                self.p, self.secrets = selected(provider), credentials(provider)
                self.provider = Recording(self.p, self.secrets)
                self.save()
                operation = self.preview()
                self.provider.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations': [{
                    **operation, 'phase': 'uncertain', 'reason': 'A different host or an old check.'}]}
                result = self.apply(operation)
                self.assertEqual(result['observation']['code'], 'access_unavailable')
                self.assertEqual(result['operation']['phase'], 'uncertain')

    def test_deeply_nested_or_truncated_provider_answers_keep_the_fixed_code(self):
        class Truncated(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_):
                pass
            def do_GET(self):
                self.send_response(200)
                if self.path == '/chunked':
                    self.send_header('Transfer-Encoding', 'chunked')
                    self.end_headers()
                    self.wfile.write(b'400\r\n{"keys": [')
                else:
                    self.send_header('Content-Length', str(len(keys) + 64))
                    self.end_headers()
                    self.wfile.write(keys)
                self.close_connection = True
        keys = json.dumps({'keys': self.provider.keys}).encode()
        server = HTTPServer(('127.0.0.1', 0), Truncated)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        cut = f'http://127.0.0.1:{server.server_port}'
        answers = {'nested': lambda: (200, b'[' * 100_000),
                   'truncated': lambda: access.Http().request('GET', cut + '/chunked', {}),
                   'short': lambda: access.Http().request('GET', cut + '/short', {})}
        recorded = self.provider.request
        operation = self.preview()
        try:
            for case, answer in answers.items():
                with self.subTest(case=case):
                    def request(method, url, headers, body=None):
                        reply = recorded(method, url, headers, body)
                        return answer() if url.endswith('/cdn-cgi/access/certs') else reply
                    with patch.object(self.provider, 'request', request):
                        result = self.apply(operation)
                    self.assertEqual(result['observation']['code'], 'access_unavailable')
                    self.assertEqual(result['operation']['phase'], 'uncertain')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_status_reports_only_the_observation_of_its_own_operation_and_route(self):
        first = self.preview()
        self.assertEqual(self.apply(first)['observation']['code'], 'access_cloudflare_verified')
        self.p['host'] = 'second.synthetic.invalid'
        self.save()
        second = self.preview()
        self.assertNotEqual(second['operation_id'], first['operation_id'])
        self.provider.offline = True
        self.assertEqual(self.apply(second)['observation']['code'], 'access_unavailable')
        status = lambda operation: access.execute(['status', '--state-dir', str(self.state),
                                                   '--operation', operation['operation_id']])
        self.assertEqual(status(second)['observation']['code'], 'access_unavailable')
        self.assertIsNone(status(first)['observation'], 'the second route\'s result is not the first operation\'s')

    def test_pruning_the_checked_operation_never_hands_its_observation_to_an_older_check(self):
        project = ['--repository', 'synthetic-owner/synthetic-repo', '--operator', 'Synthetic Operator',
                   '--service-issue', '7', '--harness', 'claude-code', '--model', 'claude-opus-5-5',
                   '--effort', 'medium', '--host', 'local']
        def setup_preview():
            subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'tools/install/setup/setup.py'), 'prepare',
                            '--state-dir', str(self.state), *project], check=True, capture_output=True,
                           env={'PATH': '/usr/bin:/bin', 'HOME': str(self.root)}, timeout=30)
        def access_preview():
            self.p['host'] = 'third.synthetic.invalid'
            self.save()
            self.preview()
        for pruner in (access_preview, setup_preview):
            with self.subTest(pruner=pruner.__name__):
                self.state = self.root / pruner.__name__
                self.p = selected()
                self.provider = Recording(self.p, self.secrets)
                self.provider.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations':
                                                      access.store.Store(str(self.state)).read()['operations']}
                self.p['host'] = 'second.synthetic.invalid'
                self.save()
                pruned = self.preview()
                self.p['host'] = 'openwiz.synthetic.invalid'
                self.save()
                kept = self.preview()
                self.assertEqual(self.apply(kept)['operation']['phase'], 'applied')
                self.p['host'] = 'second.synthetic.invalid'
                self.save()
                owner_report, self.provider = self.provider.owner_report, Recording(self.p, self.secrets)
                self.provider.owner_report = owner_report
                self.assertEqual(self.apply(pruned)['operation']['phase'], 'applied')
                def fill(value):
                    value['operations'] += [{**value['operations'][0], 'operation_id': f'{n:032x}',
                                             'phase': 'proposed', 'reason': 'Synthetic unchecked proposal.'}
                                            for n in range(access.store.MAX_OPERATIONS - len(value['operations']))]
                access.store.Store(str(self.state)).update(fill)
                pruner()
                saved = access.store.Store(str(self.state)).read()['operations']
                self.assertNotIn(pruned['operation_id'], [o['operation_id'] for o in saved])
                status = access.execute(['status', '--state-dir', str(self.state), '--operation', kept['operation_id']])
                self.assertIsNone(status['observation'], 'the pruned later check\'s result is not the kept operation\'s')

    def test_tailscale_cli_runs_only_from_a_fixed_location_with_a_fixed_environment(self):
        planted, fixed = self.root / 'planted', self.root / 'fixed'
        planted.mkdir()
        fixed.mkdir()
        marker = self.root / 'planted-ran'
        for folder, script in [(planted, f'touch {marker}\necho {{}}'),
                               (fixed, f'env > {self.root / "fixed-env"}\necho \'{{"Synthetic": true}}\'')]:
            (folder / 'tailscale').write_text('#!/bin/sh\n' + script + '\n')
            (folder / 'tailscale').chmod(0o700)
        environment = {'PATH': f'{planted}:/usr/bin:/bin', 'SYNTHETIC_INHERITED': 'planted'}
        with patch.dict(os.environ, environment), \
                patch.object(access, 'TAILSCALE', (str(self.root / 'missing/tailscale'),), create=True):
            with self.assertRaises(access.Unverified) as refused:
                access.local_tailscale('status')
        self.assertEqual(refused.exception.code, 'access_unavailable')
        self.assertFalse(marker.exists(), 'a tailscale found on PATH must never run')
        with patch.dict(os.environ, environment), \
                patch.object(access, 'TAILSCALE', (str(self.root / 'missing/tailscale'), str(fixed / 'tailscale')),
                             create=True):
            self.assertEqual(access.local_tailscale('serve'), {'Synthetic': True})
        self.assertFalse(marker.exists())
        self.assertNotIn('SYNTHETIC_INHERITED', (self.root / 'fixed-env').read_text())

    def test_transport_never_follows_redirects_or_ambient_proxies(self):
        paths = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                paths.append(self.path)
                if self.path == '/redirect':
                    self.send_response(302)
                    self.send_header('Location', '/credential-sink')
                else:
                    self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Synthetic response')
        server = HTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with patch.dict(os.environ, {'http_proxy': base, 'HTTP_PROXY': base, 'NO_PROXY': '', 'no_proxy': ''}):
                status, _ = access.Http().request('GET', base + '/redirect', {'Authorization': 'Bearer SyntheticAccessCredential'})
            self.assertEqual(status, 302)
            self.assertEqual(paths, ['/redirect'], 'no proxy or credential-sink request is permitted')
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_packaged_tool_is_mandatory_private_and_runs_without_a_source_checkout(self):
        spec = importlib.util.spec_from_file_location('collector', ROOT / 'tools/release/build_products.py')
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        source = self.root / 'source'
        binaries = self.root / 'bin'
        binaries.mkdir()
        for name in ('install.py', 'pull.py', 'setup/setup.py', 'setup/store.py', 'access/access.py'):
            target = source / 'tools/install' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'tools/install' / name, target)
        for name in ('setup.py', 'app.py', 'manifest.json'):
            target = source / 'tools/github-app' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{"name":"Synthetic App fixture"}\n' if name.endswith('.json')
                              else '# Synthetic unused App resource.\n')
        for args in (['init', '-q'], ['add', 'tools'],
                     ['-c', 'user.name=Synthetic Builder', '-c', 'user.email=builder@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'Synthetic runtime fixture']):
            subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
        source_commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        sys.path.insert(0, str(ROOT / 'tools/release'))
        from test_product_identity import build
        receipts = build(binaries, source_commit, 'x86_64-unknown-linux-gnu', self.root, '0.0.13')
        def collect(output):
            return collector.collect(source, binaries, output, '0.0.13', source_commit, 'x86_64-unknown-linux-gnu',
                                     receipts['program'])[0]
        products = self.root / 'products'
        manifest = collect(products)
        slots = [row for row in manifest['assets'] if row['path'].startswith('runtime/access/')]
        self.assertEqual([row['path'] for row in slots], ['runtime/access/access.py'])
        self.assertEqual(slots[0]['mode'], '0600')
        result = subprocess.run([sys.executable, '-I', '-B', str(products / 'runtime/access/access.py'),
                                 'configure', '--plan', str(self.plan_file), '--state-dir', str(self.state)],
                                cwd=self.root, env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['operation']['phase'], 'proposed')
        help_result = subprocess.run([sys.executable, '-I', '-B', str(products / 'runtime/access/access.py'), '--help'],
                                     cwd=self.root, env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn('openwiz.access-plan.v1', help_result.stdout)
        self.assertIn('tunnel and application', help_result.stdout)
        self.assertIn('current device approval/expiry', help_result.stdout)
        tool = source / 'tools/install/access/access.py'
        tool.unlink()
        rejected = self.root / 'rejected'
        with self.assertRaises(collector.Refused):
            collect(rejected)
        self.assertFalse(rejected.exists())
        tool.symlink_to(ROOT / 'tools/install/access/access.py')
        with self.assertRaises(collector.Refused):
            collect(rejected)
        tool.unlink()
        os.link(products / 'runtime/access/access.py', tool)
        with self.assertRaises(collector.Refused):
            collect(rejected)


if __name__ == '__main__':
    unittest.main(verbosity=2)
