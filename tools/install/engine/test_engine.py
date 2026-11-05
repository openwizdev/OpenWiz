"""Installed engine preparation: synthetic state, no account or external executor."""
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import tarfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


class Engine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='openwiz-engine-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.runtime = self.root / 'package/runtime'
        (self.runtime / 'engine').mkdir(parents=True)
        (self.runtime / 'setup').mkdir()
        shutil.copyfile(HERE / 'engine.py', self.runtime / 'engine/engine.py')
        shutil.copyfile(HERE.parent / 'setup/store.py', self.runtime / 'setup/store.py')
        (self.runtime / 'openwiz-build.txt').write_text('openwiz.package.v1\n0.0.99\n' + '1' * 40 + '\nx86_64-unknown-linux-gnu\n')
        self.state = self.root / 'state'
        spec = importlib.util.spec_from_file_location('engine_fixture_store', self.runtime / 'setup/store.py')
        self.store_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.store_module)
        self.store = self.store_module.Store(self.state)
        def prepare(v):
            v['revision'] = 1
            v['project'] = {'repository':'synthetic-owner/synthetic-repo','project':'prj_syn_engine',
                'operator':'synthetic-owner','service_issue':7,'answer_thread':'thr_syn_answer',
                'harness':'codex','model':'synthetic-model','effort':'high','runtime':'0.0.99 ' + '1' * 40}
            v['app'] = {'app_id':1001,'installation_id':2002}
        self.store.update(prepare)

    def run_engine(self, *args, code=0):
        result = subprocess.run([sys.executable, '-I', str(self.runtime / 'engine/engine.py'),
            *args, '--state-dir', str(self.state), '--json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stderr + result.stdout)
        self.assertEqual(result.stderr, '')
        return json.loads(result.stdout)

    def test_installed_supervisor_repository_context_and_validation(self):
        spec = importlib.util.spec_from_file_location('engine_platform_fixture', HERE.parent / 'platform/test_runtime.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fixture = module.Runtime()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        for target in ('aarch64-apple-darwin','x86_64-apple-darwin','x86_64-unknown-linux-gnu'):
            with self.subTest(target=target):
                fixture.calls.clear()
                fixture.registered = None
                manager = fixture.manager(target)
                config = fixture.state / 'service/config.json'
                config.write_text(json.dumps({'repository':{'owner':'synthetic-owner','name':'selected.repo'}}))
                for action in ('start','restart'):
                    with patch.dict(os.environ, {'GH_REPO':'hostile-owner/wrong-repo'}):
                        fresh = type(manager)(manager.root, manager.state, fixture.run_tool, manager.system, manager.machine)
                        self.assertEqual(fresh.apply(action)['state'],'awake')
                    self.assertEqual(fresh.env['GH_REPO'],'synthetic-owner/selected.repo')
                    self.assertTrue(all(env['GH_REPO']=='synthetic-owner/selected.repo' for _,env in fixture.calls))
                    self.assertNotIn(b'wrong-repo',fresh.definition())
                    units = list((fixture.state / 'service/platform').glob('*'))
                    self.assertEqual(len(units),1)
                    self.assertEqual(units[0].read_bytes(),fresh.definition())
                    if 'apple' in target:
                        import plistlib
                        self.assertEqual(plistlib.loads(units[0].read_bytes())['EnvironmentVariables']['GH_REPO'],
                            'synthetic-owner/selected.repo')
                    else:
                        self.assertIn(b'Environment="GH_REPO=synthetic-owner/selected.repo"',units[0].read_bytes())
                # Restart uses the persisted supervisor definition, not the
                # command's environment. Selecting B must not restart A.
                saved = units[0].read_bytes()
                for selection in [{'repository':{'owner':'synthetic-owner','name':'changed.repo'}}, {}]:
                    with self.subTest(restart_selection=selection):
                        config.write_text(json.dumps(selection))
                        fixture.calls.clear()
                        restarted = type(manager)(manager.root, manager.state, fixture.run_tool,
                            manager.system, manager.machine)
                        with self.assertRaises(ValueError):
                            restarted.apply('restart')
                        self.assertEqual(fixture.calls,[])
                        self.assertEqual(units[0].read_bytes(),saved)
                for repository in [None, {}, [], 'synthetic-owner/selected.repo',
                                   {'owner':'-synthetic','name':'repo'},
                                   {'owner':'synthetic-owner','name':'../wrong'},
                                   {'owner':'synthetic-owner','name':'repo\nGH_REPO=wrong'},
                                   {'owner':'synthetic-owner','name':'.'},
                                   {'owner':'synthetic-owner','name':'..'},
                                   {'owner':'synthetic-owner','name':'r','extra':'wrong'}]:
                    with self.subTest(repository=repository):
                        config.write_text(json.dumps({'repository':repository}))
                        fixture.calls.clear()
                        with self.assertRaises(ValueError):
                            fresh.apply('restart')
                        self.assertEqual(fixture.calls,[])
                config.write_text(json.dumps({'repository':{'owner':'a-','name':'_synthetic.repo-'}}))
                fresh.inspect()
                self.assertEqual(fresh.env['GH_REPO'],'a-/_synthetic.repo-')
                # Legacy unrelated controls use an empty document. Missing
                # selection clears prior context instead of inheriting ambient.
                config.write_text('{}')
                fresh.inspect()
                self.assertNotIn('GH_REPO',fresh.env)

    def test_preview_survives_wakes_and_activation_is_closed(self):
        first = self.run_engine('preview', '--location', 'local')
        again = self.run_engine('preview', '--location', 'local')
        self.assertEqual(first['operation']['operation_id'], again['operation']['operation_id'])
        self.assertEqual(first['engine']['location'], 'local')
        self.assertEqual(first['service_config']['orchestrator_thread'], 'thr_syn_answer')
        self.assertEqual(first['service_config']['operator'], 'synthetic-owner')
        self.assertEqual(first['service_config']['github_app'], {'app_id':1001,'installation_id':2002})
        self.assertFalse((self.state / 'service/config.json').exists())
        status = self.run_engine('status')
        self.assertEqual(status['operation'], first['operation'])
        # Without a named verified installation, Local activation writes nothing
        # and keeps the preview for an authorized retry (#1106 revision 17).
        result = self.run_engine('activate', '--yes', '--operation', first['operation']['operation_id'], code=5)
        self.assertFalse(result['activation_allowed'])
        self.assertEqual(result['operation']['phase'], 'proposed')
        self.assertEqual(result['location_status'], 'not_activated')
        self.assertEqual(result['pc_activation'], {'state':'absent','operation_id':None})
        self.assertFalse((self.state / 'service').exists())
        cloud = self.run_engine('preview', '--location', 'cloud')
        refused = self.run_engine('activate', '--yes', '--operation', cloud['operation']['operation_id'], code=5)
        self.assertEqual(refused['operation']['phase'], 'refused')
        self.assertIn('Cloud engine activation is an unresolved gap', refused['reason'])
        self.assertFalse((self.state / 'service').exists())

    def test_unknown_delivery_is_never_downgraded_or_replaced(self):
        first = self.run_engine('preview', '--location', 'cloud')
        operation = first['operation']['operation_id']
        self.store.settle(operation, 'uncertain', 'Synthetic lost activation reply.')
        for args in [('status',), ('preview','--location','local'), ('activate','--yes','--operation',operation)]:
            with self.subTest(args=args):
                result = self.run_engine(*args, code=6)
                self.assertEqual(result['operation']['operation_id'], operation)
                self.assertEqual(result['operation']['phase'], 'uncertain')
        self.assertEqual(len(self.store.read()['operations']), 1)

    def test_recorded_activation_needs_verification_before_another_proposal(self):
        first = self.run_engine('preview', '--location', 'local')
        operation = first['operation']['operation_id']
        self.store.settle(operation, 'applied', 'Synthetic imported outcome, not current runtime evidence.')
        result = self.run_engine('preview', '--location', 'cloud', code=6)
        self.assertEqual(result['operation']['operation_id'], operation)
        self.assertEqual(result['location_status'], 'unknown')
        self.assertEqual(len(self.store.read()['operations']), 1)

    def preview_access(self, label):
        # Preview has no confirmation, secrets, provider or transport call.
        tool = self.runtime / 'access/access.py'
        tool.parent.mkdir(exist_ok=True)
        shutil.copyfile(HERE.parent / 'access/access.py', tool)
        plan = self.root / 'synthetic-access.json'
        plan.write_text(json.dumps({'schema':'openwiz.access-plan.v1',
            'provider':'cloudflare','host':f'route{label}.synthetic.invalid','port':7370,
            'owner':'owner@example.invalid','account':'1'*32,
            'tunnel':'11111111-1111-1111-1111-111111111111',
            'application':'22222222-2222-2222-2222-222222222222','team':'synthetic-team'}))
        plan.chmod(0o600)
        result = subprocess.run([sys.executable,'-I',str(tool),'configure',
            '--state-dir',str(self.state),'--plan',str(plan)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout)['operation']['phase'],'proposed')

    def test_other_setup_operations_cannot_prune_the_selected_engine_identity(self):
        first = self.run_engine('preview', '--location', 'local')
        self.run_engine('preview', '--location', 'cloud')
        selected = self.run_engine('preview', '--location', 'local')
        self.assertEqual(selected['operation']['operation_id'], first['operation']['operation_id'])
        self.run_engine('activate','--yes','--operation',first['operation']['operation_id'], code=5)
        for n in range(65):
            if n % 2 == 0:
                self.preview_access(n)
            else:
                self.store.propose('prepare_project', {'synthetic':n}, ['Synthetic local proposal.'], 'Synthetic.')
        result = self.run_engine('status')
        self.assertEqual(result['operation']['operation_id'], first['operation']['operation_id'])
        self.assertEqual(len(self.store.read()['operations']), 64)

    def test_access_preview_prunes_stale_engine_proposals_at_capacity(self):
        # Produce prior proposals through the real engine tool. No activation
        # occurs; each revision represents a different recorded setup selection.
        for revision in range(1, 63):
            self.store.update(lambda value: value.update(revision=revision))
            self.run_engine('preview', '--location', 'local')
        self.store.update(lambda value: value.update(revision=63))
        local_a = self.run_engine('preview', '--location', 'local')
        cloud_b = self.run_engine('preview', '--location', 'cloud')
        selected = self.run_engine('preview', '--location', 'local')
        self.assertNotEqual(local_a['operation']['operation_id'], cloud_b['operation']['operation_id'])
        self.assertEqual(selected['operation']['operation_id'], local_a['operation']['operation_id'])
        self.assertEqual(len(self.store.read()['operations']), 64)
        self.preview_access('capacity')
        after = self.run_engine('status')
        self.assertEqual(after['engine']['location'], 'local')
        self.assertEqual(after['operation']['operation_id'], local_a['operation']['operation_id'])
        operations = self.store.read()['operations']
        self.assertEqual(len(operations), 64)
        self.assertEqual(sum(o['kind'] == 'configure_access' for o in operations), 1)
        self.assertTrue(all(o['phase'] == 'proposed' for o in operations))

    def test_authorization_must_name_the_current_preview_not_an_older_equal_request(self):
        first = self.run_engine('preview', '--location', 'cloud')
        old = first['operation']['operation_id']
        self.run_engine('activate', '--yes', '--operation', old, code=5)
        current = self.run_engine('preview', '--location', 'cloud')
        self.assertNotEqual(current['operation']['operation_id'], old)
        before = (self.state / 'setup/state.json').read_bytes()
        self.run_engine('activate', '--yes', '--operation', old, code=10)
        self.assertEqual((self.state / 'setup/state.json').read_bytes(), before)
        self.assertEqual(self.run_engine('status')['operation'], current['operation'])

    def test_projected_service_config_refuses_invalid_ids_without_saving_a_proposal(self):
        original = self.store.read()['project']
        for mutation in [{'project':'-synthetic'}, {'answer_thread':'-synthetic'},
                         {'repository':'-synthetic/synthetic-repo'}]:
            with self.subTest(mutation=mutation):
                self.store.update(lambda value: value.update(project={**original, **mutation}))
                before = (self.state / 'setup/state.json').read_bytes()
                refused = self.run_engine('preview', '--location', 'local', code=10)
                self.assertEqual(refused['schema'], 'openwiz.cli-error.v1')
                self.assertEqual((self.state / 'setup/state.json').read_bytes(), before)
        self.store.update(lambda value: value.update(project={**original, 'project':'_synthetic',
            'answer_thread':'a' * 128, 'repository':'a-/synthetic.repo'}))
        accepted = self.run_engine('preview', '--location', 'local')
        self.assertEqual(accepted['service_config']['project'], '_synthetic')
        self.assertEqual(accepted['service_config']['orchestrator_thread'], 'a' * 128)

    def test_status_is_read_only_and_stale_selection_cannot_activate(self):
        first = self.run_engine('preview', '--location', 'local')
        before = (self.state / 'setup/state.json').read_bytes()
        self.run_engine('status')
        self.assertEqual((self.state / 'setup/state.json').read_bytes(), before)
        self.store.update(lambda v: v.update(revision=2))
        self.run_engine('activate','--yes','--operation',first['operation']['operation_id'], code=8)

    def test_measured_default_branches_and_unknown_are_distinct(self):
        now = int(time.time() * 1000)
        for credits, expected in [(1,'cloud'), (20,'local')]:
            with self.subTest(credits=credits):
                evidence = {'source':'cloudroom_usage','provenance':'measured','credits':credits,
                    'window_s':86400,'free_allowance':3000,'observed_at':now,'allowance_at':now}
                path = self.state / 'setup/engine-cost.json'
                path.write_text(json.dumps(evidence)); path.chmod(0o600)
                result = self.run_engine('preview')
                self.assertEqual(result['engine']['location'], expected)
                self.assertEqual(result['cost']['monthly_projection'], 30 * credits)
                self.assertEqual(result['cost']['window_s'], 86400)
                self.assertIn('Provider charges', result['cost']['reason'])
        (self.state / 'setup/engine-cost.json').unlink()
        result = self.run_engine('preview', code=5)
        self.assertIsNone(result['default_location'])
        self.assertEqual(result['cost']['provenance'], 'unknown')
        self.assertIsNone(result['cost']['credits'])

    def test_unsafe_stale_or_estimated_credit_evidence_cannot_choose_cloud(self):
        now = int(time.time() * 1000)
        base = {'source':'cloudroom_usage','provenance':'measured','credits':1,
            'window_s':86400,'free_allowance':3000,'observed_at':now,'allowance_at':now}
        for mutation in [{'credits':True}, {'window_s':0}, {'credits':float('nan')},
                         {'allowance_at':1}, {'source':'unverified'}, {'extra':'synthetic'},
                         {'provenance':'estimated'}]:
            with self.subTest(mutation=mutation):
                path = self.state / 'setup/engine-cost.json'
                path.write_text(json.dumps({**base,**mutation})); path.chmod(0o600)
                result = self.run_engine('preview', code=5)
                self.assertIsNone(result['default_location'])
        path.chmod(0o644)
        self.assertEqual(self.run_engine('preview', code=5)['cost']['provenance'], 'unknown')

    def test_preview_saves_the_same_cost_observation_that_selected_its_default(self):
        # An observation owner can replace its file while preview waits for
        # the store lock. A second read must not bind a different observation.
        spec = importlib.util.spec_from_file_location('engine_fixture_runtime', self.runtime / 'engine/engine.py')
        engine = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(engine)
        now = int(time.time() * 1000)
        first = {'source':'cloudroom_usage','provenance':'measured','credits':1,
            'window_s':86400,'free_allowance':3000,'observed_at':now,'allowance_at':now}
        replacement = {**first, 'credits':20}
        with patch.object(engine, 'evidence', side_effect=[first, replacement]):
            preview, code = engine.execute('preview', {'--state-dir':str(self.state)})
        self.assertEqual(code, 0)
        self.assertEqual(preview['engine']['location'], 'cloud')
        self.assertEqual(preview['engine']['cost'], first)
        status = self.run_engine('status')
        self.assertEqual(status['cost'], preview['cost'])
        self.assertEqual(status['default_location'], 'cloud')

    def test_verified_installer_carries_real_engine_and_cli_without_build_tools(self):
        cli = os.environ.get('OPENWIZ_ENGINE_FIXTURE_CLI')
        if cli is None:
            # The ordinary Python stage proves installed tool/state behavior.
            # The registered Rust process proof supplies the real built CLI.
            cli_bytes = b'#!/bin/sh\nexit 0\n'
        else:
            cli_bytes = Path(cli).read_bytes()
        spec = importlib.util.spec_from_file_location('engine_fixture_installer', HERE.parent / 'install.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        files = {name:b'Synthetic required resource.\n' for name in installer.REQUIRED}
        for name in installer.PROGRAMS:
            files[name] = b'#!/bin/sh\nexit 0\n'
        files['openwiz'] = cli_bytes
        service = os.environ.get('OPENWIZ_ENGINE_FIXTURE_SERVICE')
        if service:
            files['openwiz-service'] = Path(service).read_bytes()
        for name in ('web/openwiz-build.txt','runtime/openwiz-build.txt'):
            files[name] = (self.runtime / 'openwiz-build.txt').read_bytes()
        files['runtime/engine/engine.py'] = (HERE / 'engine.py').read_bytes()
        files['runtime/setup/store.py'] = (HERE.parent / 'setup/store.py').read_bytes()
        archive = self.root / 'synthetic.tar.gz'
        rows = []
        with tarfile.open(archive,'w:gz',format=tarfile.USTAR_FORMAT,compresslevel=1) as tar:
            for name,data in sorted(files.items()):
                mode = 0o700 if name in installer.PROGRAMS or name.endswith('.sh') else 0o600
                item = tarfile.TarInfo(name); item.size = len(data); item.mode = mode
                tar.addfile(item,io.BytesIO(data))
                rows.append({'path':name,'sha256':installer.sha(data),'bytes':len(data),'mode':format(mode,'04o')})
        manifest = self.root / 'synthetic.manifest.json'
        manifest.write_text(json.dumps({'schema':'openwiz.install.v1','version':'0.0.99','source':'1'*40,
            'target':'x86_64-unknown-linux-gnu','setup_api':1,'archive':archive.name,
            'archive_sha256':installer.sha(archive.read_bytes()),'archive_bytes':archive.stat().st_size,'assets':rows}))
        target = self.root / 'verified'
        installed = subprocess.run([sys.executable,'-I',str(HERE.parent/'install.py'),
            '--manifest',str(manifest),'--manifest-sha256',installer.sha(manifest.read_bytes()),
            '--archive',str(archive),'--target','x86_64-unknown-linux-gnu','--root',str(target)],capture_output=True,text=True)
        self.assertEqual(installed.returncode,0,installed.stderr)
        env = {**os.environ,'PATH':'/synthetic/no-build-tools','OPENWIZ_STATE_DIR':str(self.state)}
        command = [str(target/'current/openwiz'),'engine'] if cli else [sys.executable,'-I',str(target/'current/runtime/engine/engine.py')]
        result = subprocess.run([*command,'preview','--location','local','--json'],env=env,capture_output=True,text=True,cwd=self.root)
        self.assertEqual(result.returncode,0,result.stderr+result.stdout)
        preview = json.loads(result.stdout)
        self.assertFalse(preview['activation_allowed'])
        self.assertEqual(preview['engine']['runtime'],'0.0.99 '+'1'*40)
        if cli:
            tool = target / 'current/runtime/engine/engine.py'
            # Exercise isolation and refusal through the installed executable,
            # using only this synthetic package's writable child resources.
            trap = self.root / 'trap'
            trap.mkdir()
            (trap / 'python3').write_text('#!/bin/sh\nexit 97\n')
            (trap / 'python3').chmod(0o700)
            source_fallback = self.root / 'tools/install/engine/engine.py'
            source_fallback.parent.mkdir(parents=True)
            observed = ('PATH','PYTHONPATH','OPENWIZ_ENGINE_PROGRAM','OPENWIZ_ENGINE_RUNTIME')
            spy = ('import json,os\nreport=json.loads(' + repr(json.dumps(preview)) + ')\n'
                + 'report["reason"]=json.dumps({k:k in os.environ for k in ' + repr(observed) + '})\n'
                + 'print(json.dumps(report))\n')
            source_fallback.write_text(spy)
            tool.write_text(spy)
            hostile = {**env,'PATH':str(trap),'PYTHONPATH':str(trap),
                'OPENWIZ_ENGINE_PROGRAM':str(trap/'python3'),
                'OPENWIZ_ENGINE_RUNTIME':str(source_fallback)}
            isolated = subprocess.run([*command,'status','--json'],env=hostile,cwd=self.root,
                capture_output=True,text=True)
            self.assertEqual(isolated.returncode,0,isolated.stdout+isolated.stderr)
            self.assertEqual(json.loads(json.loads(isolated.stdout)['reason']),{k:False for k in observed})
            saved = tool.with_name('saved-engine.py')
            tool.rename(saved)
            for symlink in (False, True):
                with self.subTest(runtime_symlink=symlink):
                    if symlink:
                        tool.symlink_to(saved)
                    refused = subprocess.run([*command,'status','--json'],env=hostile,cwd=self.root,
                        capture_output=True,text=True)
                    self.assertEqual(refused.returncode,1,refused.stdout+refused.stderr)
                    self.assertEqual(json.loads(refused.stdout)['error']['kind'],'unavailable')
                    if symlink:
                        tool.unlink()
            saved.rename(tool)
            directory = tool.parent
            real_directory = directory.with_name('saved-engine')
            directory.rename(real_directory)
            directory.symlink_to(real_directory, target_is_directory=True)
            refused = subprocess.run([*command,'status','--json'],env=hostile,cwd=self.root,
                capture_output=True,text=True)
            self.assertEqual(refused.returncode,1,refused.stdout+refused.stderr)
            directory.unlink()
            real_directory.rename(directory)
            tool.write_bytes((HERE / 'engine.py').read_bytes())
            # This copied installed child is an untrusted source boundary.
            valid = {**preview, 'service_config':None}
            malformed = [
                ('{"schema":"openwiz.engine.v1","activation_allowed":false}', 0),
                (json.dumps(valid)[:-1] + ',"activation_allowed":false}', 0),
                (json.dumps({**valid, 'extra':'synthetic'}), 0),
                (json.dumps({**valid, 'cost':[]}), 0),
                (json.dumps({**valid, 'location_status':{'not_activated':None}}), 0),
                (json.dumps({'schema':'openwiz.cli-error.v1','command':'engine.preview',
                    'exit_code':2,'error':{'kind':'usage','message':'Synthetic.'}}), 2),
                (json.dumps({'schema':'openwiz.cli-error.v1','command':'engine.status',
                    'exit_code':10,'error':{'kind':'store_unavailable','message':'Synthetic.'}}), 2),
            ]
            for payload, exit_code in malformed:
                with self.subTest(payload=payload):
                    tool.write_text('import sys\nsys.stdout.write(' + repr(payload) + ')\nsys.exit(' + str(exit_code) + ')\n')
                    rejected = subprocess.run([*command,'status','--json'],env=env,capture_output=True,text=True)
                    self.assertEqual(rejected.returncode,1,rejected.stdout+rejected.stderr)
                    self.assertEqual(json.loads(rejected.stdout)['schema'],'openwiz.cli-error.v1')
                    self.assertEqual(json.loads(rejected.stdout)['error']['kind'],'unavailable')
                    self.assertEqual(rejected.stderr,'')
            error = {'schema':'openwiz.cli-error.v1','command':'engine.status','exit_code':2,
                'error':{'kind':'usage','message':'Synthetic usage refusal.'}}
            for payload, exit_code in [(json.dumps(valid),0),(json.dumps(error),2)]:
                tool.write_text('import sys\nsys.stdout.write(' + repr(payload) + ')\nsys.exit(' + str(exit_code) + ')\n')
                accepted = subprocess.run([*command,'status','--json'],env=env,capture_output=True,text=True)
                self.assertEqual(accepted.returncode,exit_code,accepted.stdout+accepted.stderr)
                self.assertEqual(json.loads(accepted.stdout),json.loads(payload))
            tool.write_bytes((HERE / 'engine.py').read_bytes())
        if service:
            blocked = subprocess.run([str(target/'current/openwiz-service')],env=env,capture_output=True,text=True)
            self.assertEqual(blocked.returncode,1)
            self.assertIn('Activation remains closed',blocked.stderr)
            (target/'current/install-manifest.json').unlink()
            damaged = subprocess.run([str(target/'current/openwiz-service')],env=env,capture_output=True,text=True,timeout=10)
            self.assertEqual(damaged.returncode,1)
            self.assertIn('Activation remains closed',damaged.stderr)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PcActivation(unittest.TestCase):
    """Revision 17, PC-first: the engine command drives #2379's installed
    handover executor with its production provider. Synthetic state only; no
    supervisor command, credential, CloudRoom call or App record is reached."""

    def setUp(self):
        # #2379's real installed consumer: the verified installer, a synthetic
        # bundle that ships the handover runtime and private owner state.
        fixtures = load_module('engine_pc_handover_fixture', HERE.parent / 'handover/test_handover.py')
        self.handover = fixtures.handover
        self.installed = fixtures.Installed()
        self.installed.setUp()
        self.addCleanup(self.installed.doCleanups)
        self.root, self.state = self.installed.root, self.installed.state
        self.config = self.state / 'service/config.json'
        self.journal = self.state / 'setup/pc-activation.json'
        self.foreign = self.config.read_bytes()
        # A consumer's service config comes from its engine preview, not by hand.
        self.config.unlink()
        self.tool = Path(self.handover.resolve(self.root)['build']) / 'runtime/engine/engine.py'

    def engine(self, *args, tool=None):
        """The installed engine tool, in process, on a simulated Linux x86_64 PC."""
        saved = sys.modules.pop('store', None)
        try:
            module = load_module('engine_pc_' + os.urandom(4).hex(), tool or self.tool)
            with patch('platform.system', return_value='Linux'), \
                 patch('platform.machine', return_value='x86_64'):
                return module.main([*args, '--state-dir', str(self.state), '--json'])
        finally:
            sys.modules.pop('store', None)
            if saved is not None:
                sys.modules['store'] = saved

    def preview(self, location='local'):
        result, code = self.engine('preview', '--location', location)
        self.assertEqual(code, 0, result)
        return result

    def activate(self, operation, *extra):
        return self.engine('activate', '--yes', '--operation', operation, *extra)

    def saved(self):
        return json.loads(self.journal.read_bytes())

    def operations(self):
        return json.loads((self.state / 'setup/state.json').read_bytes())['operations']

    def test_local_activation_installs_the_previewed_config_and_holds_with_zero_effects(self):
        preview = self.preview()
        self.assertEqual(preview['pc_activation'], {'state': 'absent', 'operation_id': None})
        self.assertEqual(preview['login'], 'unknown')
        result, code = self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        self.assertEqual(code, 6, result)
        # The exact previewed service configuration, owner-only, created once.
        expected = (json.dumps(preview['service_config'], sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.assertEqual(self.config.read_bytes(), expected)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((self.state / 'service').stat().st_mode), 0o700)
        journal = self.saved()
        self.assertEqual((journal['outcome'], journal['operation']['phase'], journal['started_at'],
                          journal['record_state'], journal['record_at']),
                         ('held', 'proposed', None, 'pending', None))
        self.assertEqual(journal['request']['binding']['config_sha256'], hashlib.sha256(expected).hexdigest())
        self.assertEqual((result['pc_activation'], result['location_status'], result['login']),
                         ({'state': 'held', 'operation_id': journal['request']['operation_id']}, 'held', 'unknown'))
        self.assertEqual(result['operation'], preview['operation'])
        self.assertIn('No service was started', result['reason'])
        # No unit definition was published, so no supervisor step was reached.
        self.assertFalse((self.state / 'service/platform').exists())
        # A clean wake re-runs the same saved operation; nothing new appears.
        count = len(self.operations())
        again, code = self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        self.assertEqual(code, 6, again)
        self.assertEqual(self.saved()['request'], journal['request'])
        self.assertEqual(self.saved()['started_at'], None)
        self.assertEqual(len(self.operations()), count)
        self.assertEqual(self.config.read_bytes(), expected)

    def test_status_reports_the_journal_outcome_and_unknown_login(self):
        before, code = self.engine('status')
        self.assertEqual(code, 0, before)
        self.assertEqual((before['pc_activation']['state'], before['login']), ('absent', 'unknown'))
        preview = self.preview()
        self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        stored = (self.state / 'setup/state.json').read_bytes(), self.journal.read_bytes()
        after, code = self.engine('status')
        self.assertEqual(code, 0, after)
        self.assertEqual((after['pc_activation']['state'], after['location_status'], after['login']),
                         ('held', 'held', 'unknown'))
        self.assertEqual(((self.state / 'setup/state.json').read_bytes(), self.journal.read_bytes()), stored)
        self.journal.chmod(0o644)
        unsafe, code = self.engine('status')
        self.assertEqual((unsafe['pc_activation']['state'], unsafe['location_status']), ('unreadable', 'unknown'))

    def test_a_different_existing_config_refuses_before_any_journal(self):
        preview = self.preview()
        self.config.write_bytes(self.foreign)
        self.config.chmod(0o600)
        result, code = self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        self.assertEqual(code, 5, result)
        self.assertIn('different service configuration', result['reason'])
        self.assertEqual(self.config.read_bytes(), self.foreign)
        self.assertFalse(self.journal.exists())
        # A byte-identical existing configuration is accepted as already installed.
        expected = (json.dumps(preview['service_config'], sort_keys=True, separators=(',', ':')) + '\n').encode()
        self.config.write_bytes(expected)
        result, code = self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        self.assertEqual(code, 6, result)
        self.assertEqual(self.saved()['outcome'], 'held')

    def test_cloud_activation_refuses_as_the_named_gap(self):
        preview = self.preview('cloud')
        result, code = self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        self.assertEqual(code, 5, result)
        self.assertIn('Cloud engine activation is an unresolved gap pending its separate decision', result['reason'])
        self.assertEqual(result['operation']['phase'], 'refused')
        self.assertFalse(self.config.exists())
        self.assertFalse(self.journal.exists())

    def test_local_activation_needs_the_selected_installation_and_writes_nothing_otherwise(self):
        preview = self.preview()
        operation = preview['operation']['operation_id']
        before = (self.state / 'setup/state.json').read_bytes()
        # An identical copy of the installed runtime outside the selected build.
        copied = Path(self.installed.install.tmp.name) / 'copied-runtime'
        shutil.copytree(self.tool.parents[1], copied)
        source = copied / 'engine/engine.py'
        for args, tool in [((), None), (('--root', str(self.root)), source),
                           (('--root', str(self.root / 'missing')), None)]:
            with self.subTest(args=args, tool=tool):
                result, code = self.activate(operation, *args) if tool is None else \
                    self.engine('activate', '--yes', '--operation', operation, *args, tool=tool)
                self.assertEqual(code, 5, result)
                self.assertEqual(result['pc_activation']['state'], 'absent')
                self.assertFalse(self.config.exists())
                self.assertFalse(self.journal.exists())
                self.assertEqual((self.state / 'setup/state.json').read_bytes(), before)

    def test_a_recorded_pc_activation_holds_a_changed_selection(self):
        preview = self.preview()
        self.activate(preview['operation']['operation_id'], '--root', str(self.root))
        count = len(self.operations())
        result, code = self.engine('preview', '--location', 'cloud')
        self.assertEqual(code, 8, result)
        self.assertIn('Reconcile the recorded PC activation', result['reason'])
        self.assertEqual(len(self.operations()), count)
        self.assertEqual(self.preview()['operation'], preview['operation'])

    def bytes_now(self):
        read = lambda path: path.read_bytes() if path.exists() else None
        return read(self.state / 'setup/state.json'), read(self.journal), read(self.config)

    def test_r1_an_earlier_proposal_cannot_bypass_the_recorded_selection(self):
        self.preview('cloud')
        local = self.preview()
        self.activate(local['operation']['operation_id'], '--root', str(self.root))
        before = self.bytes_now()
        result, code = self.engine('preview', '--location', 'cloud')
        self.assertEqual((code, result['engine']['location'], result['pc_activation']['state']),
                         (8, 'local', 'held'), result)
        self.assertIn('Reconcile the recorded PC activation', result['reason'])
        self.assertEqual(self.bytes_now(), before)

    def lock_probe(self):
        """True when another process cannot take the shared setup lock now."""
        probe = ('import fcntl,os,sys\nfd=os.open(sys.argv[1],os.O_RDWR)\n'
                 'try:\n fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)\nexcept BlockingIOError:\n sys.exit(3)\n')
        return subprocess.run([sys.executable, '-I', '-c', probe, str(self.state / 'setup/.lock')]).returncode == 3

    def engine_with(self, hooks, *args):
        """The installed engine, with recording hooks on its handover seam."""
        saved = sys.modules.pop('store', None)
        try:
            module = load_module('engine_pc_' + os.urandom(4).hex(), self.tool)
            real_sibling, real_install = module.sibling, module.install_config
            def sibling(name):
                loaded = real_sibling(name)
                if name == 'handover/handover.py':
                    real_executor = loaded.executor
                    def executor(*a, **k):
                        made = real_executor(*a, **k)
                        hooks.get('executor', lambda: None)()
                        for method in ('preview', 'execute'):
                            def wrapped(*b, _real=getattr(made, method), _name=method):
                                hooks.get(_name, lambda: None)()
                                return _real(*b)
                            setattr(made, method, wrapped)
                        return made
                    loaded.executor = executor
                return loaded
            def install_config(*a):
                hooks.get('install_config', lambda: None)()
                return real_install(*a)
            module.sibling, module.install_config = sibling, install_config
            with patch('platform.system', return_value='Linux'), \
                 patch('platform.machine', return_value='x86_64'):
                return module.main([*args, '--state-dir', str(self.state), '--json'])
        finally:
            sys.modules.pop('store', None)
            if saved is not None:
                sys.modules['store'] = saved

    def test_r2_config_publication_and_both_t9_steps_hold_the_setup_lock(self):
        operation = self.preview()['operation']['operation_id']
        seen = []
        hooks = {name: (lambda name=name: seen.append((name, self.lock_probe())))
                 for name in ('install_config', 'preview', 'execute')}
        result, code = self.engine_with(hooks, 'activate', '--yes', '--operation', operation, '--root', str(self.root))
        self.assertEqual(code, 6, result)
        self.assertEqual(seen, [('install_config', True), ('preview', True), ('execute', True)])

    def test_r2_a_competing_preparation_before_the_lock_refuses_without_config_or_journal(self):
        operation = self.preview()['operation']['operation_id']
        store = self.handover.modules(self.handover.resolve(self.root))['store'].Store(self.state)
        def prepare():
            # A concurrent authorized preparation: new revision and answer target.
            store.update(lambda value: value.update(revision=2, project={**value['project'],
                'answer_thread':'thr_syn_new_answer'}))
        result, code = self.engine_with({'executor': prepare}, 'activate', '--yes', '--operation', operation,
                                        '--root', str(self.root))
        self.assertEqual(code, 8, result)
        self.assertIn('preview it again', result['reason'])
        self.assertFalse(self.config.exists())
        self.assertFalse(self.journal.exists())

    def test_r2_a_competing_cloud_preview_before_the_lock_refuses_without_config_or_journal(self):
        operation = self.preview()['operation']['operation_id']
        def cloud():
            done = subprocess.run([sys.executable, '-I', str(self.tool), 'preview', '--location', 'cloud',
                '--state-dir', str(self.state), '--json'], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        result, code = self.engine_with({'executor': cloud}, 'activate', '--yes', '--operation', operation,
                                        '--root', str(self.root))
        self.assertEqual(code, 8, result)
        self.assertEqual(result['engine']['location'], 'cloud')
        self.assertFalse(self.config.exists())
        self.assertFalse(self.journal.exists())


if __name__ == '__main__':
    unittest.main()
