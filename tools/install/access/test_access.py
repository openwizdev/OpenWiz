"""IF7 tool, privacy, recovery and packaging proofs; run by install-access.test.mjs.
All providers are recording fixtures; no real accounts or external network.
Signature verification uses production OpenSSL; transport checks use loopback.
"""
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
sys.path.insert(0, str(ROOT / 'apps/web/test/fixtures/install-access'))
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
                # Pause the first caller after its durable generation, before
                # its claim. A second real-store caller completes meanwhile.
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
        # Token/cookie bodies and provider errors never enter durable public state.
        saved = (self.state / 'setup/state.json').read_text()
        for secret in self.secrets.values():
            self.assertNotIn(secret, saved)
        self.assertTrue(all(call[0] == 'GET' for call in self.provider.calls))

    def check_untrusted_context(self, **claims):
        # IF7/R1: each negative context must authenticate the selected app and
        # team before its denial can count. Old tests supplied only labels.
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
        # IF7/R2: a different tunnel can reach this same process/witness while
        # lacking the selected tunnel's origin guard. Prior tests missed DNS.
        self.provider.dns[0]['content'] = '88888888-8888-8888-8888-888888888888.cfargotunnel.com'
        result = self.apply(self.preview())
        self.assertEqual(result['observation']['code'], 'access_unavailable')
        self.assertEqual(result['operation']['phase'], 'uncertain')

    def test_cloudflare_serving_connector_with_stale_config_stays_unknown(self):
        # IF7/R2: a stored guard says nothing about a connector still serving an
        # earlier configuration. Keep the public witness and edge probes valid.
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
        # Even a new selection cannot change resource while the old effect is uncertain.
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
        del self.provider.status['Self']['Expired']  # The real CLI omits false.
        del self.provider.serve['AllowFunnel']  # Serve omits the map when Funnel is off.
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
        binaries, web = self.root / 'bin', self.root / 'web'
        binaries.mkdir()
        web.mkdir()
        (web / 'setup.html').write_text('Synthetic setup page')
        for name in ('install.py', 'pull.py', 'setup/setup.py', 'setup/store.py', 'platform/runtime.py', 'access/access.py', 'engine/engine.py'):
            target = source / 'tools/install' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'tools/install' / name, target)
        for name in ('setup.py', 'app.py', 'manifest.json'):
            target = source / 'tools/github-app' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # App behavior is outside this fixture; web-test prunes its real
            # sources. Supply explicit unused bytes for those collector slots.
            target.write_text('{"name":"Synthetic App fixture"}\n' if name.endswith('.json')
                              else '# Synthetic unused App resource.\n')
        for args in (['init', '-q'], ['add', 'tools'],
                     ['-c', 'user.name=Synthetic Builder', '-c', 'user.email=builder@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'Synthetic runtime fixture']):
            subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True)
        source_commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
        # #1148: programs and web built with this identity, plus that job's receipts.
        sys.path.insert(0, str(ROOT / 'tools/release'))
        from test_product_identity import build
        receipts = build(binaries, web, source_commit, 'x86_64-unknown-linux-gnu', self.root, '0.0.13')
        def collect(output):
            return collector.collect(source, binaries, web, output, '0.0.13', source_commit, 'x86_64-unknown-linux-gnu',
                                     receipts['program'], receipts['web'])[0]
        products = self.root / 'products'
        manifest = collect(products)
        slots = [row for row in manifest['assets'] if row['path'].startswith('runtime/access/')]
        self.assertEqual([row['path'] for row in slots], ['runtime/access/access.py'])
        self.assertEqual(slots[0]['mode'], '0600')
        # Actual CLI from collected runtime, outside the repository. No API calls.
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
