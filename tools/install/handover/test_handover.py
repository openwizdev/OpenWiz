#!/usr/bin/env python3
"""IF2/IF5/IF6/IF10-handoff recording proofs through a real synthetic installation.

Every identity, key byte and credit value is synthetic. No supervisor, network,
CloudRoom, GitHub or credit source is reached; recording providers stand in.
"""
import copy
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
HOUR = 3600000


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load('t12_install', TOOLS / 'install.py')
bundles = load('t12_fixture_bundle', TOOLS / 'fixture_bundle.py')
handover = load('t12_handover', HERE / 'handover.py')
checkpoints = load('t12_checkpoint_fixture', TOOLS / 'completion/test_checkpoint.py')
CONFIG = {'repository': {'owner': 'synthetic-owner', 'name': 'synthetic-repo'},
          'project': 'prj_syn_handover', 'github_app': {'app_id': 31, 'installation_id': 42},
          'service_issue': 9001}


class Recording:
    """Recording authority/observer/supervisor/App sink; never a native default."""
    def __init__(self, case):
        self.case, self.records, self.online, self.lost = case, [], False, False
        self.delivery = 'confirmed'

    def authority(self, request, challenge, now):
        return {'request': copy.deepcopy(request), 'challenge': challenge, 'at': now, 'authorized': True}

    def observe(self, request, challenge, now):
        return {'request': copy.deepcopy(request), 'challenge': challenge, 'at': now,
                'state': 'healthy' if self.online else 'not_applied',
                'lock': 'held' if self.online else 'free'}

    def enable_start(self, request):
        self.case.manager().enable_start(request['binding'])
        self.online = True
        if self.lost:
            self.lost = False
            raise TimeoutError('synthetic lost start reply')

    def record(self, issue, body):
        self.records.append((issue, body))
        return self.delivery


class Installed(unittest.TestCase):
    """A clean consumer: the real installer, a synthetic bundle, private state."""
    handover_runtime = True

    def setUp(self):
        home = patch.dict(os.environ, {'HOME': '/synthetic/owner-home'})
        home.start()
        self.addCleanup(home.stop)
        self.install = load('t12_install_tests', TOOLS / 'test_install.py').Install()
        self.install.setUp()
        self.addCleanup(self.install.doCleanups)
        self.calls, self.registered, self.now = [], None, 5000
        self.root = self.install_bundle('1' * 40)
        self.state = self.root / 'state'
        config = self.state / 'service/config.json'
        config.write_text(json.dumps(CONFIG))
        config.chmod(0o600)
        app = self.state / 'service/app'
        app.mkdir(mode=0o700)
        (app / 'private-key.pem').write_bytes(b'synthetic-key-bytes')
        (app / 'private-key.pem').chmod(0o600)
        self.prepare_setup()
        self.provider = Recording(self)

    def install_bundle(self, source):
        manifest, archive, files = self.install.bundle(installer.TARGETS[2], source=source)
        if self.handover_runtime:
            files.update(bundles.handover_runtime())
        modes = lambda p: '0700' if p in installer.PROGRAMS or p.endswith('.sh') else '0600'
        with tarfile.open(archive, 'w:gz', format=tarfile.USTAR_FORMAT) as tar:
            for path, data in files.items():
                info = tarfile.TarInfo(path)
                info.size, info.mode = len(data), int(modes(path), 8)
                tar.addfile(info, io.BytesIO(data))
        value = json.loads(manifest.read_bytes())
        value['assets'] = [{'path': p, 'sha256': installer.sha(d), 'bytes': len(d), 'mode': modes(p)}
                           for p, d in sorted(files.items())]
        value['archive_sha256'] = installer.sha(archive.read_bytes())
        value['archive_bytes'] = archive.stat().st_size
        manifest.write_text(json.dumps(value))
        self.install.run_install((manifest, archive, files))
        return self.install.root

    def prepare_setup(self):
        runtime = handover.resolve(self.root)
        store = handover.modules(runtime)['store'].Store(self.state)
        def prepare(value):
            value['revision'] = 1
            value['project'] = {'repository': 'synthetic-owner/synthetic-repo',
                'project': 'prj_syn_handover', 'operator': 'synthetic-owner',
                'service_issue': 9001, 'answer_thread': 'thr_syn_answer', 'harness': 'codex',
                'model': 'synthetic-model', 'effort': 'high', 'runtime': runtime['runtime']}
            value['app'] = CONFIG['github_app']
        store.update(prepare)

    def run_tool(self, args, env):
        self.calls.append(args)
        if '--property=FragmentPath' in args:
            return subprocess.CompletedProcess(args, 0, (self.registered or '').encode(), b'')
        if 'link' in args:
            self.registered = args[-1]
        return subprocess.CompletedProcess(args, 0, b'', b'')

    def manager(self):
        return handover.manager(handover.resolve(self.root), self.state, self.run_tool,
                                system='Linux', machine='x86_64')

    def executor(self, provider=None):
        return handover.executor(self.root, self.state, provider or self.provider,
                                 lambda: self.now, self.run_tool, system='Linux', machine='x86_64')

    def starts(self):
        return [args for args in self.calls if 'enable' in args]

    def report(self):
        return handover.status(self.root, self.state)


class Handover(Installed):
    def test_clean_installed_consumer_applies_once_and_reads_back_exact_outcome(self):
        self.assertEqual(self.report()['activation'], 'absent')
        executor = self.executor()
        request = executor.preview()
        result = executor.execute(json.dumps(request))
        self.assertEqual((result['operation']['phase'], result['record_state'], result['outcome']),
                         ('applied', 'confirmed', 'applied'))
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(len(self.provider.records), 1)
        report = self.report()
        self.assertEqual((report['runtime']['source'], report['activation'], report['login'],
                          report['handover_allowed']), ('1' * 40, 'verified', 'unknown', True))
        self.assertEqual(report['completion'], 'held')
        self.assertEqual(report['cloud'], 'unresolved')

    def test_lost_start_reply_restart_reconciles_without_a_second_start(self):
        request = self.executor().preview()
        self.provider.lost = True
        first = self.executor().execute(json.dumps(request))
        self.assertEqual(first['operation']['phase'], 'uncertain')
        self.assertEqual(self.report()['activation'], 'held')
        self.now += 1
        again = self.executor().execute(json.dumps(request))
        self.assertEqual(again['outcome'], 'applied')
        self.assertEqual(len(self.starts()), 1)
        self.assertEqual(len(self.provider.records), 1)

    def test_uncertain_app_record_holds_across_restart_and_is_never_reposted(self):
        request = self.executor().preview()
        self.provider.delivery = 'uncertain'
        held = self.executor().execute(json.dumps(request))
        self.assertEqual((held['record_state'], held['outcome']), ('uncertain', 'held'))
        self.now += 1
        self.provider.delivery = 'confirmed'
        self.executor().execute(json.dumps(request))
        self.assertEqual(len(self.provider.records), 1)
        self.assertEqual(self.report()['activation'], 'held')
        self.assertFalse(self.report()['handover_allowed'])

    def test_production_provider_holds_with_zero_effects(self):
        executor = self.executor(handover.Unavailable())
        request = executor.preview()
        result = executor.execute(json.dumps(request))
        self.assertEqual((result['operation']['phase'], result['outcome']), ('proposed', 'held'))
        self.assertEqual(self.starts(), [])
        self.assertEqual(self.report()['activation'], 'held')

    def test_changed_target_config_or_owner_refuses_an_applied_record(self):
        request = self.executor().preview()
        self.executor().execute(json.dumps(request))
        self.assertEqual(self.report()['activation'], 'verified')
        config = self.state / 'service/config.json'
        original = config.read_bytes()
        config.write_text(json.dumps({**CONFIG, 'project': 'prj_syn_changed'}))
        self.assertEqual(self.report()['activation'], 'held')
        config.write_bytes(original)
        self.assertEqual(self.report()['activation'], 'verified')
        with patch.object(handover.os, 'geteuid', return_value=os.geteuid() + 1):
            self.assertEqual(self.report()['activation'], 'held')
        self.install_bundle('2' * 40)
        report = self.report()
        self.assertEqual((report['runtime']['source'], report['activation']), ('2' * 40, 'held'))

    def test_damaged_journal_is_unreadable_never_completed(self):
        request = self.executor().preview()
        self.executor().execute(json.dumps(request))
        journal = self.state / 'setup/pc-activation.json'
        value = journal.read_text()
        journal.write_text(value[:-1] + ',"outcome":"applied"}')
        self.assertEqual(self.report()['activation'], 'unreadable')
        journal.write_text(value.replace('"applied"', '"applied" '))
        journal.chmod(0o644)
        self.assertEqual(self.report()['activation'], 'unreadable')

    def test_runtime_resolution_has_no_source_checkout_or_path_fallback(self):
        runtime = handover.resolve(self.root)
        build = Path(runtime['build'])
        for module in handover.modules(runtime).values():
            self.assertTrue(Path(module.__file__).resolve().is_relative_to(build), module.__file__)
        tampered = build / 'runtime/pc_activation/activation.py'
        original = tampered.read_bytes()
        tampered.write_bytes(original + b'\n# tampered\n')
        with self.assertRaises(handover.Refused):
            handover.resolve(self.root)
        tampered.write_bytes(original)
        current = self.root / 'current'
        # An identical verified copy outside this installation's builds is foreign.
        elsewhere = self.install.base / 'elsewhere'
        elsewhere.mkdir(mode=0o700)
        copy_ = elsewhere / build.name
        subprocess.run(['cp', '-a', str(build), str(copy_)], check=True)
        current.unlink()
        os.symlink(copy_, current)
        with self.assertRaises(handover.Refused):
            handover.resolve(self.root)
        current.unlink()
        os.symlink(TOOLS, current)
        with self.assertRaises(handover.Refused):
            handover.resolve(self.root)
        current.unlink()
        with self.assertRaises(handover.Refused):
            handover.resolve(self.root)
        report = self.report()
        self.assertEqual((report['runtime'], report['activation'], report['handover_allowed']),
                         (None, 'unreadable', False))

    def test_completion_verifier_is_the_installed_one_and_reads_fresh(self):
        recording = checkpoints.fixture()
        reads = []
        def reader(nonce):
            reads.append(nonce)
            return json.dumps({**recording['reads'][0], 'nonce': nonce})
        self.assertEqual(handover.completion(self.root, recording['pin'], 'spec_summary', reader),
                         'CP1_verified')
        self.assertEqual(len(set(reads)), 2)
        stale = []
        def changed(nonce):
            stale.append(nonce)
            value = copy.deepcopy(recording['reads'][0])
            if len(stale) == 2:
                value['planned'][0]['verified_merge'] = False
            return json.dumps({**value, 'nonce': nonce})
        self.assertEqual(handover.completion(self.root, recording['pin'], 'spec_summary', changed),
                         'CP1_planned_work')
        self.assertEqual(handover.completion(self.root, recording['pin'], 'all_closed'), 'CP1_unreadable')


class ColdConsumer(Installed):
    handover_runtime = False

    def prepare_setup(self):
        pass

    def test_installed_bundle_without_handover_runtime_refuses(self):
        with self.assertRaises(handover.Refused):
            handover.modules(handover.resolve(self.root))
        with self.assertRaises(handover.Refused):
            self.executor()
        report = self.report()
        self.assertEqual((report['runtime']['source'], report['activation'], report['handover_allowed']),
                         ('1' * 40, 'unreadable', False))
        self.assertEqual(handover.completion(self.root, checkpoints.fixture()['pin'], 'spec_summary',
                         lambda nonce: '{}'), 'CP1_unreadable')
        self.assertEqual(self.starts(), [])


def evidence(**change):
    value = {'schema': 'openwiz.credit-evidence.v1',
             'candidate': {'version': '0.0.99', 'source': '1' * 40},
             'interval': {'started_at': 10 * HOUR, 'ended_at': 11 * HOUR},
             'usage': {'source': 'cloudroom_usage', 'provenance': 'measured',
                       'credits': 0.5, 'observed_at': 11 * HOUR},
             'allowance': {'source': 'cloudroom_plan', 'credits': 3000,
                           'observed_at': 11 * HOUR}}
    for path, item in change.items():
        target = value
        keys = path.split('__')
        for key in keys[:-1]:
            target = target[key]
        if item is KeyError:
            del target[keys[-1]]
        else:
            target[keys[-1]] = item
    return value


class Credit(unittest.TestCase):
    now = 11 * HOUR + 1000
    candidate = {'version': '0.0.99', 'source': '1' * 40}

    def check(self, value, candidate=None):
        return handover.credit(value, self.now, candidate or self.candidate)

    def test_measured_branches_follow_the_existing_tenth_of_allowance_policy(self):
        # 0.25 credits/hour projects to 180 per 30 days, within a tenth of 3000.
        cheap = self.check(evidence(usage__credits=0.25))
        self.assertEqual((cheap['policy_branch'], cheap['provenance']), ('cloud', 'measured'))
        self.assertEqual(cheap['monthly_projection']['credits'], 180.0)
        self.assertEqual(cheap['monthly_projection']['label'], 'estimate: 30 days at the observed rate')
        self.assertEqual(cheap['provider_charges'], 'separate_unavailable')
        # 0.5 credits/hour projects to 360 per 30 days, above a tenth of 3000.
        costly = self.check(evidence())
        self.assertEqual(costly['policy_branch'], 'local')
        self.assertEqual(costly['monthly_projection']['credits'], 360.0)

    def test_estimated_stale_unknown_or_foreign_evidence_never_proves_cloud(self):
        cases = {
            'estimated': evidence(usage__provenance='estimated'),
            'stale usage': evidence(usage__observed_at=11 * HOUR - 2 * HOUR,
                                    interval__ended_at=9 * HOUR - 1, interval__started_at=8 * HOUR),
            'stale allowance': evidence(allowance__observed_at=self.now - HOUR - 1),
            'unknown credits': evidence(usage__credits=None, usage__provenance='unknown'),
            'unsourced allowance': evidence(allowance__source='pricing_constant'),
            'same source allowance': evidence(allowance__source='cloudroom_usage'),
            'missing allowance': evidence(allowance=KeyError),
            'observed before interval end': evidence(usage__observed_at=11 * HOUR - 1),
            'empty interval': evidence(interval__started_at=11 * HOUR),
            'future observation': evidence(usage__observed_at=self.now + 1, interval__ended_at=self.now + 1),
            'negative credits': evidence(usage__credits=-1),
            'non-finite credits': evidence(usage__credits=math.inf),
            'boolean credits': evidence(usage__credits=True),
            'extra field': evidence(extra=1),
            'wrong schema': evidence(schema='openwiz.credit-evidence.v2'),
        }
        for name, value in cases.items():
            with self.subTest(name):
                result = self.check(value)
                self.assertEqual(result['policy_branch'], 'explicit_choice', name)
                self.assertIsNone(result['monthly_projection'] if name != 'estimated' else None)
        foreign = self.check(evidence(), {'version': '0.0.99', 'source': '2' * 40})
        self.assertEqual((foreign['policy_branch'], foreign['provenance']), ('explicit_choice', 'unknown'))
        estimated = self.check(evidence(usage__provenance='estimated'))
        self.assertEqual(estimated['provenance'], 'estimated')
        self.assertEqual(estimated['monthly_projection']['label'], 'estimate: 30 days at the observed rate')

    def test_validator_and_schema_refuse_the_same_records(self):
        schema = json.loads((HERE / 'contract.v1.schema.json').read_text())
        def conforms(value, rule):
            if '$ref' in rule:
                rule = schema['$defs'][rule['$ref'].split('/')[-1]]
            if 'anyOf' in rule:
                return any(conforms(value, r) for r in rule['anyOf'])
            kinds = {'object': dict, 'string': str, 'integer': int, 'null': type(None)}
            if rule['type'] == 'number':
                return type(value) in (int, float) and math.isfinite(value) and value >= rule['minimum']
            if type(value) is not kinds[rule['type']]:
                return False
            if 'const' in rule or 'enum' in rule:
                return value in rule.get('enum', [rule.get('const')])
            if rule['type'] == 'object':
                return set(value) == set(rule['required']) and all(
                    conforms(value[k], r) for k, r in rule['properties'].items())
            if rule['type'] == 'integer':
                return value >= rule['minimum']
            # JSON Schema `pattern` is an unanchored search; anchors must be explicit.
            return rule['type'] != 'string' or re.search(rule['pattern'], value) is not None
        table = [evidence(), evidence(usage__credits=None), evidence(usage__credits=-1),
                 evidence(usage__provenance='guessed'), evidence(extra=1), evidence(candidate__source='x'),
                 evidence(interval__started_at=-1), evidence(allowance__credits=math.nan),
                 evidence(usage__observed_at=1.5), evidence(allowance=KeyError),
                 evidence(candidate__version='x0.0.99x'), evidence(candidate__version='0.0.99\n'),
                 evidence(candidate__source='x' + '1' * 40 + 'x'), evidence(candidate__source='1' * 40 + '\n')]
        for value in table:
            with self.subTest(value=value):
                self.assertEqual(conforms(value, schema['$defs']['credit_evidence']),
                                 handover.credit_shape(value))

    def test_offline_validator_command_has_fixed_output_and_status(self):
        path = Path(self.id().replace('.', '_') + '.json')
        tmp = Path(os.environ.get('TMPDIR', '/tmp')) / path
        self.addCleanup(lambda: tmp.unlink(missing_ok=True))
        for value, code, branch in ((evidence(usage__credits=0.25), 0, 'cloud'), (evidence(), 0, 'local'),
                                    (evidence(usage__provenance='estimated'), 5, 'explicit_choice')):
            tmp.write_text(json.dumps(value))
            result = subprocess.run([sys.executable, '-I', str(HERE / 'handover.py'), 'credit', str(tmp),
                                     '--now', str(self.now), '--version', '0.0.99', '--source', '1' * 40],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, code, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual((output['schema'], output['policy_branch']), ('openwiz.credit-handoff.v1', branch))
        for field in ('usage__credits', 'allowance__credits'):
            with self.subTest(huge=field):
                self.assertEqual(self.check(evidence(**{field: 10 ** 400}))['policy_branch'], 'explicit_choice')
                tmp.write_text(json.dumps(evidence(**{field: 10 ** 400})))
                result = subprocess.run([sys.executable, '-I', str(HERE / 'handover.py'), 'credit', str(tmp),
                                         '--now', str(self.now), '--version', '0.0.99', '--source', '1' * 40],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 5, result.stderr)
                self.assertEqual(json.loads(result.stdout)['policy_branch'], 'explicit_choice')
        tmp.write_text('{"schema":"openwiz.credit-evidence.v1","schema":"x"}')
        result = subprocess.run([sys.executable, '-I', str(HERE / 'handover.py'), 'credit', str(tmp),
                                 '--now', str(self.now), '--version', '0.0.99', '--source', '1' * 40],
                                capture_output=True, text=True)
        self.assertEqual((result.returncode, json.loads(result.stdout)['policy_branch']), (5, 'explicit_choice'))


class Packaging(unittest.TestCase):
    """The real release collector ships the handover role from tracked files."""
    def collect(self, omit=None, delete_after_commit=None):
        import tempfile
        temporary = tempfile.TemporaryDirectory(prefix='openwiz-t12-products-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        web, binaries = root / 'web', root / 'bin'
        web.mkdir()
        binaries.mkdir()
        (web / 'index.html').write_text('Synthetic setup, no accounts.')
        (root / 'skills/setup').mkdir(parents=True)
        (root / 'skills/setup/SKILL.md').write_text('Synthetic skill.')
        tracked = {'install.py', 'pull.py', 'setup/setup.py', 'setup/store.py', 'platform/runtime.py',
                   'access/access.py', 'engine/engine.py', '../github-app/setup.py', '../github-app/app.py',
                   '../github-app/manifest.json'}
        tracked |= {name.removeprefix('runtime/') for name in installer.HANDOVER_RUNTIME}
        tracked.discard(omit)
        for name in tracked:
            path = root / 'tools/install' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(f'Synthetic tracked {name}.\n'.encode())
        for args in (['init', '-q'], ['add', 'skills', 'tools'],
                     ['-c', 'user.name=Synthetic Builder', '-c', 'user.email=builder@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'Synthetic runtime']):
            subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
        source = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
        if delete_after_commit:
            (root / 'tools/install' / delete_after_commit).unlink()
        # The release collector's own synthetic native build job and receipts.
        sys.path.insert(0, str(TOOLS.parent / 'release'))
        identities = load('t12_product_identity_fixtures', TOOLS.parent / 'release/test_product_identity.py')
        (root / 'job').mkdir()
        receipts = identities.build(binaries, web, source, installer.TARGETS[2], root / 'job')
        output = root / 'products'
        identity = Path(str(output) + '.json')
        result = subprocess.run(identities.collector(root, binaries, web, output, source,
                                                     installer.TARGETS[2], receipts),
                                capture_output=True, text=True)
        return root, output, identity, result

    def test_every_handover_runtime_asset_is_packaged_from_its_tracked_file(self):
        root, output, identity, result = self.collect()
        self.assertEqual(result.returncode, 0, result.stderr)
        assets = {row['path']: row for row in json.loads(identity.read_bytes())['assets']}
        for name in installer.HANDOVER_RUNTIME:
            data = (root / 'tools/install' / name.removeprefix('runtime/')).read_bytes()
            self.assertEqual((output / name).read_bytes(), data, name)
            self.assertEqual((assets[name]['sha256'], assets[name]['mode']), (installer.sha(data), '0600'), name)

    def test_a_handover_commit_missing_any_role_file_is_refused(self):
        for name in installer.HANDOVER_RUNTIME:
            if name in ('runtime/handover/handover.py', 'runtime/install.py', 'runtime/setup/store.py',
                        'runtime/platform/runtime.py', 'runtime/engine/engine.py'):
                continue
            with self.subTest(name):
                _, output, _, result = self.collect(omit=name.removeprefix('runtime/'))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(output.exists())


    def test_a_tracked_handover_missing_from_the_checkout_is_refused(self):
        for name in ('handover/handover.py', 'pc_activation/activation.py'):
            with self.subTest(name):
                _, output, _, result = self.collect(delete_after_commit=name)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertFalse(output.exists())

    def test_a_commit_without_the_handover_keeps_its_prior_assets(self):
        root, output, identity, result = self.collect(omit='handover/handover.py')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((output / 'runtime/pc_activation/activation.py').exists())


if __name__ == '__main__':
    unittest.main()
