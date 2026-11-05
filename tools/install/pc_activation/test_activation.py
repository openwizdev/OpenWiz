"""IF2–IF6 recording proofs. All identities and key bytes are synthetic."""
import copy
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import activation


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Recording:
    def __init__(self, case):
        self.case = case
        self.calls = []
        self.online = False
        self.lost = False
        self.delivery = 'confirmed'
        self.evidence = 'not_applied'
        self.mutate = lambda value: None
        self.resource = None

    def authority(self, request, challenge, now):
        return {'request': copy.deepcopy(request), 'challenge': challenge,
                'at': now, 'authorized': True}

    def observe(self, request, challenge, now):
        result = {'request': copy.deepcopy(self.resource or request), 'challenge': challenge,
                  'at': now, 'state': 'healthy' if self.online else self.evidence,
                  'lock': 'held' if self.online else 'free'}
        self.mutate(result)
        return result

    def enable_start(self, request):
        # Use the actual Linux supervisor boundary with an injected recording tool.
        self.case.manager.enable_start(request['binding'])
        self.resource = copy.deepcopy(request)
        self.online = True
        if self.lost:
            self.lost = False
            raise TimeoutError('synthetic-provider-secret')

    def record(self, issue, body):
        self.calls.append((issue, body))
        return self.delivery


class Activation(unittest.TestCase):
    def setUp(self):
        fixture = load('pc_runtime_fixtures', HERE.parent / 'platform/test_runtime.py').Runtime()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.fixture('x86_64-unknown-linux-gnu')
        self.fixture = fixture
        config = {'repository': {'owner': 'synthetic-owner', 'name': 'synthetic-repo'},
                  'project': 'prj_syn_activation', 'github_app': {'app_id': 31, 'installation_id': 42},
                  'service_issue': 9001}
        self.config = fixture.state / 'service/config.json'
        self.config.write_text(json.dumps(config))
        app = fixture.state / 'service/app'
        app.mkdir(mode=0o700)
        self.key = app / 'private-key.pem'
        self.key.write_bytes(b'synthetic-provider-secret')
        self.key.chmod(0o600)
        runtime = load('pc_runtime', HERE.parent / 'platform/runtime.py')
        self.manager = runtime.PcManager(fixture.root, fixture.state, fixture.run_tool,
                                         system='Linux', machine='x86_64')
        self.store = activation.store.Store(fixture.state)
        def prepare(value):
            value['revision'] = 1
            value['project'] = {'repository': 'synthetic-owner/synthetic-repo',
                'project': 'prj_syn_activation', 'operator': 'synthetic-owner',
                'service_issue': 9001, 'answer_thread': 'thr_syn_answer',
                'harness': 'codex', 'model': 'synthetic-model', 'effort': 'high',
                'runtime': '0.0.99 ' + fixture.build}
            value['app'] = config['github_app']
        self.store.update(prepare)
        self.provider = Recording(self)
        self.executor = activation.Executor(self.store, self.manager, self.provider, clock=lambda: 5000)

    def preview(self):
        return self.executor.preview()

    def execute(self, request):
        return self.executor.execute(json.dumps(request))

    def starts(self):
        return [args for args, env in self.fixture.calls if 'enable' in args]

    def test_lost_reply_restart_reconciles_exact_resource_without_second_start(self):
        request = self.preview()
        self.provider.lost = True
        first = self.execute(request)
        self.assertEqual(first['operation']['phase'], 'uncertain')
        self.executor = activation.Executor(self.store, self.manager, self.provider, clock=lambda: 5001)
        after = self.execute(request)
        self.assertEqual(after['operation']['phase'], 'applied')
        self.assertEqual(self.starts(), [['/usr/bin/systemctl', '--user', 'enable', '--now', 'openwiz.service']])
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.preview(), request)
        self.assertEqual(self.execute(request)['operation']['phase'], 'applied')
        self.assertEqual(len(self.starts()), 1)

    def test_wrong_identity_never_turns_a_lost_reply_into_applied(self):
        request = self.preview()
        self.provider.lost = True
        self.execute(request)
        def wrong(value):
            value['request']['binding']['project'] = 'prj_syn_foreign'
        self.provider.mutate = wrong
        self.assertEqual(self.execute(request)['operation']['phase'], 'uncertain')
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.provider.calls, [])

    def test_secret_provider_diagnostics_never_reach_records_or_output(self):
        request = self.preview()
        self.provider.lost = True
        result = self.execute(request)
        self.assertEqual(len(self.starts()), 1)
        surfaces = json.dumps([request, result, self.provider.calls, self.fixture.calls])
        surfaces += ''.join(p.read_text() for p in self.store.dir.glob('*.json'))
        self.assertNotIn('synthetic-provider-secret', surfaces)

    def test_provider_request_types_must_be_strict_before_identity_comparison(self):
        request = self.preview()
        self.provider.lost = True
        self.execute(request)
        def wrong(value):
            value['request']['revision'] = True
        self.provider.mutate = wrong
        self.assertEqual(self.execute(request)['operation']['phase'], 'uncertain')
        self.assertEqual(len(self.starts()), 1)

    def test_every_resource_binding_and_freshness_mismatch_holds(self):
        request = self.preview()
        self.provider.lost = True
        self.execute(request)
        for key, changed in {'owner_uid': os.geteuid() + 1, 'unit': 'other.service',
                'root': '/synthetic/other', 'state_root': '/synthetic/other',
                'repository': 'synthetic-owner/other', 'project': 'prj_syn_other',
                'runtime': '0.0.98 ' + self.fixture.build, 'build': '2' * 40,
                'config_sha256': '2' * 64, 'unit_sha256': '2' * 64,
                'app_id': 33, 'installation_id': 44, 'service_issue': 9002}.items():
            with self.subTest(binding=key):
                def wrong(value):
                    value['request']['binding'][key] = changed
                self.provider.mutate = wrong
                self.assertEqual(self.execute(request)['outcome'], 'held')
        for key, changed in {'at': 4999, 'challenge': 'stale', 'lock': 'free',
                             'state': 'unknown', 'extra': 'synthetic-provider-secret'}.items():
            with self.subTest(evidence=key):
                self.provider.mutate = lambda value: value.update({key: changed})
                self.assertEqual(self.execute(request)['outcome'], 'held')
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(self.provider.calls, [])

    def test_changed_request_or_setup_or_config_never_starts(self):
        request = self.preview()
        for key, changed in {'operation_id': 'f' * 32, 'request_hash': 'f' * 64,
                             'host': 'cloud', 'action': 'restart'}.items():
            wrong = copy.deepcopy(request)
            wrong[key] = changed
            with self.subTest(key=key), self.assertRaises(activation.store.Refused):
                self.execute(wrong)
        self.store.update(lambda value: value.update(revision=2))
        self.assertEqual(self.execute(request)['outcome'], 'held')
        self.store.update(lambda value: value.update(revision=1))
        self.config.write_text(self.config.read_text() + '\n')
        self.assertEqual(self.execute(request)['outcome'], 'held')
        self.assertEqual(self.starts(), [])

    def test_absent_or_wrong_authority_never_starts(self):
        request = self.preview()
        for evidence in (None, {}, {'authorized': False}):
            with self.subTest(evidence=evidence), patch.object(self.provider, 'authority', return_value=evidence):
                self.assertEqual(self.execute(request)['outcome'], 'held')
        with patch.object(self.provider, 'authority', side_effect=TimeoutError('synthetic-provider-secret')):
            result = self.execute(request)
        self.assertEqual(result['outcome'], 'held')
        self.assertNotIn('synthetic-provider-secret', json.dumps(result))
        self.assertEqual(self.starts(), [])

    def test_unsafe_key_and_lock_metadata_refuse_before_any_effect(self):
        request = self.preview()
        for path, mode in ((self.key, 0o640), (self.key.parent, 0o750),
                           (self.key.parent.parent, 0o750)):
            old = path.stat().st_mode & 0o777
            path.chmod(mode)
            self.assertEqual(self.execute(request)['outcome'], 'held')
            path.chmod(old)
        lock = self.store.dir / '.lock'
        lock.chmod(0o640)
        with self.assertRaises(activation.store.Refused):
            self.execute(request)
        lock.chmod(0o600)
        link = self.store.dir / '.lock-alias'
        os.link(lock, link)
        with self.assertRaises(activation.store.Refused):
            self.execute(request)
        link.unlink()
        self.assertEqual(self.starts(), [])

    def test_permission_failure_and_interrupted_persistence_precede_start(self):
        request = self.preview()
        original = self.store._write
        def interrupted(path, value):
            if path == self.store.file:
                raise PermissionError('synthetic-provider-secret')
            return original(path, value)
        with patch.object(self.store, '_write', interrupted), self.assertRaises(activation.store.Refused) as error:
            self.execute(request)
        self.assertNotIn('synthetic-provider-secret', str(error.exception))
        self.assertEqual(self.starts(), [])
        self.assertEqual(json.loads((self.store.dir/'pc-activation.json').read_text())['operation']['phase'],
                         'uncertain')
        self.assertEqual(self.execute(request)['outcome'], 'applied')
        self.assertEqual(len(self.starts()), 1)

    def test_record_delivery_uncertain_is_never_blindly_repeated(self):
        request = self.preview()
        self.provider.delivery = 'uncertain'
        first = self.execute(request)
        self.assertEqual((first['operation']['phase'], first['record_state'], first['outcome']),
                         ('applied', 'uncertain', 'held'))
        self.provider.delivery = 'confirmed'
        self.assertEqual(self.execute(request)['outcome'], 'held')
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(len(self.starts()), 1)

    def test_only_definitely_unsent_record_retries_without_another_start(self):
        request = self.preview()
        self.provider.delivery = 'unsent'
        self.assertEqual(self.execute(request)['outcome'], 'held')
        self.provider.delivery = 'confirmed'
        self.assertEqual(self.execute(request)['outcome'], 'applied')
        self.assertEqual(len(self.provider.calls), 2)
        self.assertEqual(self.provider.calls[0], self.provider.calls[1])
        self.assertEqual(len(self.starts()), 1)

    def test_concurrent_callers_share_one_operation_and_one_effect(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            requests = list(pool.map(lambda _: self.preview(), range(3)))
            self.assertEqual(requests, [requests[0]] * 3)
            results = list(pool.map(self.execute, requests))
        self.assertEqual([r['outcome'] for r in results], ['applied'] * 3)
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(len(self.provider.calls), 1)

    def test_unknown_or_unbound_old_healthy_status_permits_no_start(self):
        request = self.preview()
        self.provider.evidence = 'unknown'
        self.assertEqual(self.execute(request)['outcome'], 'held')
        self.provider.online = True
        self.assertEqual(self.execute(request)['outcome'], 'held')
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.provider.calls, [])

    def test_a_terminal_setup_operation_cannot_be_reopened_by_its_companion(self):
        request = self.preview()
        self.store.settle(request['operation_id'], 'refused', 'Synthetic owner refusal.')
        with self.assertRaises(activation.store.Refused):
            self.execute(request)
        self.assertEqual(self.starts(), [])

    def test_concurrent_verified_install_cannot_change_the_dispatched_build(self):
        request = self.preview()
        replacement = self.fixture.installer.bundle(source='2' * 40)
        apply = self.manager.apply
        installs = []
        def interleave(*args, **kwargs):
            # Real installer in a separate process takes its normal install lock.
            manifest, archive, _ = replacement
            import hashlib
            result = subprocess.run([sys.executable, '-I', str(HERE.parent/'install.py'),
                '--manifest', str(manifest), '--archive', str(archive),
                '--manifest-sha256', hashlib.sha256(manifest.read_bytes()).hexdigest(),
                '--root', str(self.manager.root), '--target', 'x86_64-unknown-linux-gnu'],
                capture_output=True, text=True)
            installs.append(result.returncode)
            return apply(*args, **kwargs)
        with patch.object(self.manager, 'apply', interleave):
            self.execute(request)
        self.assertEqual((self.manager.root/'current').readlink().name, self.fixture.build)
        self.assertEqual(installs, [1])
        self.assertEqual(len(self.starts()), 1)

    def test_config_is_rechecked_after_acquiring_the_effect_lock(self):
        request = self.preview()
        flock = self.manager.__class__.apply.__globals__['fcntl'].flock
        def interleave(fd, operation):
            result = flock(fd, operation)
            number = fd.fileno() if hasattr(fd, 'fileno') else fd
            if Path('/proc/self/fd', str(number)).readlink() == self.fixture.state/'service/platform.lock':
                self.config.write_text(self.config.read_text() + '\n')
            return result
        with patch.object(activation.store.fcntl, 'flock', interleave):
            self.assertEqual(self.execute(request)['outcome'], 'held')
        self.assertEqual(self.starts(), [])

    def test_strict_reader_and_schema_refuse_the_same_structural_variants(self):
        core = load('pc_schema_checker', HERE.parents[2] / 'tools/live-check/core.py')
        schemas = core.Schemas(HERE.parents[2] / 'contracts')
        schemas.docs['activation'] = json.loads((HERE/'contract.v1.schema.json').read_text())
        request = self.preview()
        variants = [(request, True), (list(request.values()), False)]
        for key, value in {'schema': 'unknown', 'host': {'pc': None}, 'action': 'restart',
                'operation_id': 'A'*32, 'revision': True, 'request_hash': 'x'*64}.items():
            changed = copy.deepcopy(request)
            changed[key] = value
            variants.append((changed, False))
        for key, value in {'owner_uid': -1, 'unit': 'foreign.service', 'root': '/synthetic/../state',
                'state_root': '/synthetic/é', 'repository': 'owner/..', 'project': '-foreign',
                'app_id': 0, 'installation_id': 42.0, 'service_issue': 2**53,
                'runtime': 'unknown', 'config_sha256': '', 'build': 'F'*40}.items():
            changed = copy.deepcopy(request)
            changed['binding'][key] = value
            variants.append((changed, False))
        for document, expected in variants:
            with self.subTest(document=document):
                self.assertEqual(not schemas.problems(document, 'activation', 'request'), expected)
                try:
                    activation.request(document)
                    accepted = True
                except activation.store.Refused:
                    accepted = False
                self.assertEqual(accepted, expected)
        after = self.execute(request)
        self.assertEqual(schemas.problems(after, 'activation', 'journal'), [])
        for key, changed in {'created_at': True, 'updated_at': 0, 'record_state': {'confirmed': None},
                             'outcome': 'unknown', 'extra': 'unlisted'}.items():
            wrong = copy.deepcopy(after)
            wrong[key] = changed
            self.assertTrue(schemas.problems(wrong, 'activation', 'journal'))
            with self.assertRaises(activation.store.Refused):
                activation.journal(wrong)
        raw = json.dumps(request)
        for changed in (raw.replace('"host": "pc"', '"host":"pc","host":"pc"'),
                        raw.replace('"revision": 1', '"revision":NaN')):
            with self.assertRaises(activation.store.Refused):
                self.executor.execute(changed)


if __name__ == '__main__':
    unittest.main()
