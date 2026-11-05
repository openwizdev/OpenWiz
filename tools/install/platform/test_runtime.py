"""IF3: real synthetic installation, recording supervisors; never live tools."""
import importlib.util
import io
import tarfile
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Runtime(unittest.TestCase):
    def setUp(self):
        home = patch.dict(os.environ,{'HOME':'/synthetic/owner-home'})
        home.start()
        self.addCleanup(home.stop)
        self.installer = load('synthetic_install', HERE.parent / 'test_install.py').Install()
        self.installer.setUp()
        self.addCleanup(self.installer.doCleanups)
        self.calls = []
        self.online, self.supervisor = True, 'active'
        self.registered = None
        self.fail_after_effect = False

    def fixture(self, target):
        self.installer.root = self.installer.base / (target + getattr(self,'install_suffix',''))
        bundle = self.installer.bundle(target)
        manifest_path, archive, files = bundle
        # Ship the actual manager and install verifier in this synthetic release.
        # The selected package, rather than the source checkout, supplies its code.
        files['runtime/install.py'] = (HERE.parent/'install.py').read_bytes()
        files['runtime/platform/runtime.py'] = (HERE/'runtime.py').read_bytes()
        digest = load('install_shapes', HERE.parent/'install.py').sha
        manifest = json.loads(manifest_path.read_bytes())
        with tarfile.open(archive,'w:gz',format=tarfile.USTAR_FORMAT) as tar:
            for path,data in files.items():
                mode = 0o700 if path in ('openwiz','openwiz-service','openwiz-server') or path.endswith('.sh') else 0o600
                info = tarfile.TarInfo(path)
                info.size,info.mode = len(data),mode
                tar.addfile(info,io.BytesIO(data))
        manifest['assets'] = [{'path':p,'sha256':digest(data),'bytes':len(data),
            'mode':'0700' if p in ('openwiz','openwiz-service','openwiz-server') or p.endswith('.sh') else '0600'}
            for p,data in sorted(files.items())]
        manifest['archive_sha256'] = digest(archive.read_bytes())
        manifest['archive_bytes'] = archive.stat().st_size
        manifest_path.write_text(json.dumps(manifest))
        result = self.installer.run_install(bundle, target)
        self.root = self.installer.root
        self.state = Path(result['state_root'])
        (self.state / 'service/config.json').write_text('{}')
        (self.state / 'service/config.json').chmod(0o600)
        self.build = result['source']
        return result

    def run_tool(self, args, env):
        self.calls.append((args, env))
        if args[-2:] == ['status', '--json']:
            return subprocess.CompletedProcess(args, 0 if self.online else 1,
                json.dumps({'schema':'openwiz.service-status.v1',
                            'service':{'build':self.build, 'since':1000}}).encode(), b'')
        if '--property=FragmentPath' in args:
            return subprocess.CompletedProcess(args, 0, (self.registered or '').encode(), b'')
        if 'link' in args:
            self.registered = args[-1]
        if 'bootstrap' in args:
            self.registered = args[-1]
            if self.fail_after_effect:
                self.fail_after_effect = False
                return subprocess.CompletedProcess(args,1,b'',b'synthetic private diagnostic')
        if 'show' in args:
            return subprocess.CompletedProcess(args, 0, self.supervisor.encode(), b'')
        if 'print' in args:
            return subprocess.CompletedProcess(args, 0 if self.registered else 1,
                b'state = waiting\nlast exit code = 9\n' if self.supervisor == 'failed' else b'', b'')
        return subprocess.CompletedProcess(args, 0, b'', b'')

    def manager(self, target):
        self.fixture(target)
        module = load('platform_runtime', self.root / 'current/runtime/platform/runtime.py')
        host = {'aarch64-apple-darwin':('Darwin','arm64'),
                'x86_64-apple-darwin':('Darwin','x86_64'),
                'x86_64-unknown-linux-gnu':('Linux','x86_64')}[target]
        return module.Manager(self.root, self.state, self.run_tool, *host)

    def test_installed_start_status_restart_all_targets(self):
        for target in ('aarch64-apple-darwin','x86_64-apple-darwin','x86_64-unknown-linux-gnu'):
            with self.subTest(target=target):
                self.calls.clear()
                self.registered = None
                manager = self.manager(target)
                self.assertEqual(manager.apply('start')['state'], 'awake')
                first = list(self.calls)
                self.assertEqual(first[0][0][0], '/bin/launchctl' if 'apple' in target else '/usr/bin/systemctl')
                self.assertEqual(sum('bootstrap' in a or 'link' in a for a, _ in first), 1)
                self.calls.clear()
                self.assertEqual(manager.apply('start')['state'], 'awake')
                self.assertFalse(any('bootstrap' in a or 'link' in a for a, _ in self.calls))
                self.calls.clear()
                self.assertEqual(manager.apply('restart')['state'], 'awake')
                self.assertEqual(self.calls[0][0][1:3], ['kickstart','-k'] if 'apple' in target else ['--user','restart'])
                self.assertEqual(len(self.calls), 2)
                self.calls.clear()
                result = manager.apply('status')
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(result['native'], 'Unverified')
                self.assertEqual(result['supervisor'], 'launchd' if 'apple' in target else 'systemd')
                self.assertIn('Cloud agents', result['reason'])
                self.assertTrue(all(env.get('OPENWIZ_STATE_DIR') == str(self.state) for _,env in self.calls))
                self.assertEqual(list((self.state/'service/platform').glob('*'))[0].stat().st_mode & 0o777, 0o600)

    def test_supervisor_running_never_substitutes_for_live_ipc(self):
        manager = self.manager('x86_64-unknown-linux-gnu')
        self.online = False
        result = manager.apply('status')
        self.assertEqual(result['state'], 'offline_or_unknown')
        self.assertFalse(result['orchestrating'])
        self.assertEqual(len(self.calls), 2)
        self.supervisor = 'failed'
        self.assertEqual(manager.apply('status')['state'], 'failed')

    def test_unsafe_paths_and_changed_build_refuse_before_any_tool(self):
        manager = self.manager('x86_64-unknown-linux-gnu')
        config = self.state / 'service/config.json'
        config.chmod(0o644)
        with self.assertRaises(ValueError): manager.apply('start')
        self.assertEqual(self.calls, [])
        config.chmod(0o600)
        os.link(config, self.state / 'alias')
        with self.assertRaises(ValueError): manager.apply('start')
        self.assertEqual(self.calls, [])
        (self.state / 'alias').unlink()
        program = self.root / 'current/openwiz-service'
        program.write_bytes(b'changed synthetic bytes')
        with self.assertRaises(ValueError): manager.apply('start')
        self.assertEqual(self.calls, [])

    def test_platform_mismatch_refuses_before_effect(self):
        manager = self.manager('aarch64-apple-darwin')
        manager.system, manager.machine = 'Linux', 'x86_64'
        with self.assertRaises(ValueError): manager.apply('start')
        self.assertEqual(self.calls, [])

    def test_symlinked_install_and_state_ancestors_refuse_before_any_tool(self):
        for kind in ('install','state'):
            with self.subTest(ancestor=kind):
                self.calls.clear()
                self.registered = None
                self.install_suffix = '-'+kind
                manager = self.manager('x86_64-unknown-linux-gnu')
                alias = self.installer.base / (kind+'-parent-alias')
                if kind == 'install':
                    alias.symlink_to(self.root.parent,target_is_directory=True)
                    install = alias/self.root.name
                    state = self.state
                else:
                    alias.symlink_to(self.state.parent,target_is_directory=True)
                    install = self.root
                    state = alias/self.state.name
                    # Keep every other selection/ownership/hash check valid.
                    # Only the state's symlinked ancestor is unsafe.
                    selected = state/'service/builds'/self.build
                    (install/'current').unlink()
                    (install/'current').symlink_to(selected,target_is_directory=True)
                through_alias = type(manager)(install,state,self.run_tool,'Linux','x86_64')
                try:
                    with self.assertRaises(ValueError): through_alias.apply('start')
                    self.assertEqual(self.calls,[])
                finally:
                    alias.unlink()

    def test_linux_unit_preserves_restart_policy_and_literal_private_paths(self):
        self.install_suffix = ' space $X%"'
        manager = self.manager('x86_64-unknown-linux-gnu')
        manager.apply('start')
        unit = next((self.state/'service/platform').glob('*.service')).read_text()
        # Same recovery fields as deploy/pc/openwiz.service; systemd command
        # expansion and Environment= quoting have different dollar semantics.
        for expected in ('StartLimitIntervalSec=0','Restart=always','RestartSec=5',
                         'space $$X%%\\"/current/openwiz-service'):
            with self.subTest(required=expected):
                self.assertIn(expected,unit)
        self.assertIn('space $X%%\\"/state',unit)

    def test_lost_launch_reply_reconciles_without_duplicate_bootstrap(self):
        manager = self.manager('aarch64-apple-darwin')
        self.fail_after_effect = True
        with self.assertRaises(ValueError) as error: manager.apply('start')
        self.assertNotIn('synthetic private diagnostic', str(error.exception))
        fresh = type(manager)(manager.root,manager.state,self.run_tool,'Darwin','arm64')
        self.assertEqual(fresh.apply('start')['state'],'awake')
        self.assertEqual(sum('bootstrap' in a for a,_ in self.calls),1)
        self.online = False
        self.supervisor = 'failed'
        self.assertEqual(fresh.apply('status')['state'],'failed')

    def test_status_is_read_only_and_wrong_build_never_becomes_awake(self):
        manager = self.manager('x86_64-unknown-linux-gnu')
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        self.build = '2'*40
        self.assertEqual(manager.apply('status')['state'],'offline_or_unknown')
        after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        self.assertEqual(before,after)
        self.assertFalse((self.state/'service/platform.lock').exists())

    def test_conflicting_definition_is_preserved_and_refused(self):
        manager = self.manager('x86_64-unknown-linux-gnu')
        manager.apply('start')
        unit = next((self.state/'service/platform').glob('*.service'))
        unit.write_bytes(b'synthetic owner definition')
        self.calls.clear()
        with self.assertRaises(ValueError): manager.apply('start')
        self.assertEqual(unit.read_bytes(),b'synthetic owner definition')
        self.assertEqual(self.calls,[])

if __name__ == '__main__':
    unittest.main()
