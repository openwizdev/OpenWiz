#!/usr/bin/env python3
"""Manage only this verified installation's local service, never a fleet."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True


def require(value):
    if not value:
        raise ValueError('local runtime refused; check private installation and service configuration')


def private(path, directory=False):
    meta = path.lstat()
    require(meta.st_uid == os.geteuid() and not meta.st_mode & 0o077 and
            (stat.S_ISDIR(meta.st_mode) if directory else
             stat.S_ISREG(meta.st_mode) and meta.st_nlink == 1))


def absolute(path):
    require(path.is_absolute() and '..' not in path.parts and not any(ord(c) < 32 or ord(c) == 127 for c in str(path)))
    for parent in (path, *path.parents):
        require(not parent.is_symlink() and not (parent / '.git').exists())


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def system_tool(args, env):
    return subprocess.run(args, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=15, check=False)


class Manager:
    # Tests inject tools and host facts directly. Production exposes no environment bypass.
    def __init__(self, root, state, runner=system_tool, system=None, machine=None):
        self.root, self.state, self.run = Path(root), Path(state), runner
        self.system = system or platform.system()
        self.machine = machine or platform.machine()
        self.label = 'dev.openwiz.' + hashlib.sha256(
            (str(self.root) + '\0' + str(self.state)).encode()).hexdigest()[:24]
        self.env = {'HOME':os.environ.get('HOME', ''), 'PATH':'/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin',
                    'OPENWIZ_STATE_DIR':str(self.state)}
        if self.system == 'Linux':
            self.env['XDG_RUNTIME_DIR'] = '/run/user/' + str(os.geteuid())

    def inspect(self):
        for path in (self.root, self.state):
            absolute(path)
            private(path, True)
        require(not any(ord(c) < 32 or ord(c) == 127 for c in self.env['HOME']))
        private(self.state/'service', True)
        private(self.state/'service/config.json')
        config = json.loads((self.state/'service/config.json').read_bytes(), object_pairs_hook=unique)
        require(isinstance(config, dict))
        # No ambient repository or working-directory discovery may select the
        # service's GitHub context. Re-inspection also clears stale selection.
        self.env.pop('GH_REPO', None)
        if 'repository' in config:
            repository = config['repository']
            require(isinstance(repository, dict) and set(repository) == {'owner','name'})
            owner, name = repository['owner'], repository['name']
            require(isinstance(owner, str) and re.fullmatch(r'[A-Za-z0-9][-A-Za-z0-9]*', owner)
                    and isinstance(name, str) and re.fullmatch(r'[-A-Za-z0-9_.]+', name)
                    and name not in ('.', '..'))
            self.env['GH_REPO'] = owner + '/' + name
        link = self.root/'current'
        require(link.is_symlink() and link.lstat().st_uid == os.geteuid())
        build = Path(os.readlink(link))
        require(build.parent == self.state/'service/builds' and len(build.name) == 40
                and all(c in '0123456789abcdef' for c in build.name))
        absolute(build)
        private(build, True)
        private(build/'install-manifest.json')
        manifest = json.loads((build/'install-manifest.json').read_bytes(), object_pairs_hook=unique)
        target = {('Darwin','arm64'):'aarch64-apple-darwin',
                  ('Darwin','x86_64'):'x86_64-apple-darwin',
                  ('Linux','x86_64'):'x86_64-unknown-linux-gnu'}.get((self.system,self.machine))
        require(target and manifest['target'] == target and manifest['source'] == build.name)
        # The already selected manifest is the trust anchor from verified installation.
        # Use its strict reader and complete asset verification before any supervisor call.
        spec = importlib.util.spec_from_file_location('verified_install', Path(__file__).parents[1]/'install.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        raw = (build/'install-manifest.json').read_bytes()
        try:
            _, assets, raw = installer.manifest_at(build/'install-manifest.json', installer.sha(raw), target)
            installer.verify_installed(build, assets, raw)
        except installer.Refused:
            raise ValueError('installed asset mismatch') from None
        self.build = build
        self.supervisor = 'launchd' if self.system == 'Darwin' else 'systemd'
        return build

    def call(self, args):
        return self.run([str(a) for a in args], self.env)

    def definition(self):
        program = str(self.root/'current/openwiz-service')
        if self.supervisor == 'launchd':
            return plistlib.dumps({'Label':self.label, 'ProgramArguments':[program],
                'EnvironmentVariables':self.env, 'RunAtLoad':True, 'KeepAlive':True,
                'ProcessType':'Background', 'Umask':0o077})
        # systemd percent expansion and quoting are independent of shell quoting.
        quote = lambda s: '"' + s.replace('\\','\\\\').replace('"','\\"').replace('%','%%') + '"'
        return ('[Unit]\nDescription=OpenWiz local runtime\nStartLimitIntervalSec=0\n[Service]\nType=simple\nUMask=0077\n'
                'ExecStart=' + quote(program).replace('$','$$') + '\n' +
                ''.join('Environment=' + quote(k+'='+v) + '\n' for k,v in self.env.items()) +
                'Restart=always\nRestartSec=5\n[Install]\nWantedBy=default.target\n').encode()

    def start(self):
        directory = self.state/'service/platform'
        if not directory.exists():
            directory.mkdir(mode=0o700)
        private(directory, True)
        suffix = '.plist' if self.supervisor == 'launchd' else '.service'
        unit = directory/(self.label+suffix)
        expected = self.definition()
        if unit.exists() or unit.is_symlink():
            private(unit)
            require(unit.read_bytes() == expected)
        else:
            # Publish complete bytes only. An interrupted write leaves an inert
            # temporary file, never an apparently installed partial definition.
            with tempfile.NamedTemporaryFile(dir=directory, prefix='.unit-', delete=False) as stream:
                temporary = Path(stream.name)
                try:
                    stream.write(expected)
                    stream.flush()
                    os.fsync(stream.fileno())
                    os.replace(temporary, unit)
                    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(parent)
                    finally:
                        os.close(parent)
                finally:
                    temporary.unlink(missing_ok=True)
        if self.supervisor == 'launchd':
            domain = 'gui/' + str(os.geteuid())
            observed = self.call(['/bin/launchctl','print',domain+'/'+self.label])
            if observed.returncode != 0:
                require(self.call(['/bin/launchctl','bootstrap',domain,unit]).returncode == 0)
        else:
            # link is repeatable, scoped to this installation's unique unit.
            observed = self.call(['/usr/bin/systemctl','--user','show',self.label+'.service','--property=FragmentPath','--value'])
            require(observed.returncode == 0)
            loaded = observed.stdout.decode().strip()
            require(not loaded or loaded == str(unit))
            if not loaded:
                require(self.call(['/usr/bin/systemctl','--user','link',unit]).returncode == 0)
            require(self.call(['/usr/bin/systemctl','--user','enable','--now',self.label+'.service']).returncode == 0)

    def status(self):
        result = self.call([self.build/'openwiz-service','status','--json'])
        awake = False
        if result.returncode == 0:
            try:
                value = json.loads(result.stdout, object_pairs_hook=unique)
                awake = (value['schema'] == 'openwiz.service-status.v1' and
                         value['service']['build'] == self.build.name)
            except (ValueError, KeyError, TypeError):
                pass
        state = 'awake' if awake else 'offline_or_unknown'
        if not awake and self.supervisor == 'systemd':
            observed = self.call(['/usr/bin/systemctl','--user','show',self.label+'.service',
                                  '--property=ActiveState','--value'])
            if observed.returncode == 0 and observed.stdout.strip() == b'failed':
                state = 'failed'
        if not awake and self.supervisor == 'launchd':
            observed = self.call(['/bin/launchctl','print','gui/'+str(os.geteuid())+'/'+self.label])
            if observed.returncode == 0 and re.search(rb'^\s*state = waiting\s*$', observed.stdout, re.M):
                exit_code = re.search(rb'^\s*last exit code = ([0-9]+)\s*$', observed.stdout, re.M)
                if exit_code and int(exit_code[1]) != 0:
                    state = 'failed'
        orchestrating = awake and value.get('tick',{}).get('running') is not None
        return {'state':state, 'orchestrating':orchestrating, 'supervisor':self.supervisor,
                'native':'Unverified', 'reason':
                'Local orchestration requires an awake host and answering service. '
                'Sleeping stops new Local orchestration; running Cloud agents may continue. '
                'Missing IPC cannot distinguish sleep from offline or unavailable status. '
                'Runtime availability alone does not establish engine activation.'}

    def apply(self, action, expected_binding=None):
        require(action in ('start','status','restart'))
        self.inspect()
        if action == 'status':
            return self.status()
        lock = self.state/'service/platform.lock'
        if lock.exists() or lock.is_symlink():
            private(lock)
        fd = os.open(lock, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW|os.O_NONBLOCK, 0o600)
        with os.fdopen(fd, 'rb+') as stream:
            private(lock)
            meta = os.fstat(stream.fileno())
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.geteuid() and
                    not meta.st_mode & 0o077 and meta.st_nlink == 1)
            fcntl.flock(stream, fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.inspect()
            if expected_binding is not None:
                require(action == 'start' and self.binding() == expected_binding)
            if action == 'restart':
                # The supervisor uses its saved definition, not this command's
                # environment. Refuse stale repository context before dispatch.
                directory = self.state/'service/platform'
                private(directory, True)
                suffix = '.plist' if self.supervisor == 'launchd' else '.service'
                unit = directory/(self.label+suffix)
                private(unit)
                require(unit.read_bytes() == self.definition())
            if action == 'start':
                self.start()
            elif self.supervisor == 'launchd':
                require(self.call(['/bin/launchctl','kickstart','-k',
                                  'gui/'+str(os.geteuid())+'/'+self.label]).returncode == 0)
            else:
                require(self.call(['/usr/bin/systemctl','--user','restart',self.label+'.service']).returncode == 0)
            return self.status()


class PcManager(Manager):
    """Explicitly injected PC boundary for the pinned activation contract."""
    def __init__(self, root, state, runner, system=None, machine=None):
        super().__init__(root, state, runner, system, machine)
        self.label = 'openwiz'

    def binding(self):
        require((self.system, self.machine) == ('Linux', 'x86_64'))
        build = self.inspect()
        # Reuse the descriptor-relative signer boundary for metadata only.
        spec = importlib.util.spec_from_file_location('pc_key_metadata', Path(__file__).with_name('security.py'))
        security = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(security)
        key = security.open_key(str(self.state))
        try:
            require(stat.S_IMODE(os.fstat(key).st_mode) == 0o600)
            for directory in (self.state, self.state/'service', self.state/'service/app'):
                require(stat.S_IMODE(directory.lstat().st_mode) == 0o700)
        finally:
            os.close(key)
        raw = (self.state/'service/config.json').read_bytes()
        config = json.loads(raw, object_pairs_hook=unique)
        manifest = json.loads((build/'install-manifest.json').read_bytes(), object_pairs_hook=unique)
        app = config['github_app']
        require(type(app) is dict and set(app) == {'app_id', 'installation_id'}
                and all(type(v) is int and 0 < v < 2**53 for v in app.values())
                and type(config['service_issue']) is int and 0 < config['service_issue'] < 2**53)
        unit = self.state/'service/platform/openwiz.service'
        if unit.exists() or unit.is_symlink():
            private(unit.parent, True)
            private(unit)
            require(unit.read_bytes() == self.definition())
        return {'owner_uid': os.geteuid(), 'unit': 'openwiz.service',
                'root': str(self.root), 'state_root': str(self.state),
                'repository': self.env['GH_REPO'], 'project': config['project'],
                'runtime': manifest['version'] + ' ' + build.name, 'build': build.name,
                'config_sha256': hashlib.sha256(raw).hexdigest(),
                'unit_sha256': hashlib.sha256(self.definition()).hexdigest(),
                'app_id': app['app_id'], 'installation_id': app['installation_id'],
                'service_issue': config['service_issue']}

    def enable_start(self, binding):
        self.inspect()
        # Serialize with the verified installer through dispatch. The platform
        # lock alone cannot fence a concurrent change to current.
        lock = self.root/'install.lock'
        fd = os.open(lock, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb+') as stream:
            private(lock)
            meta = os.fstat(stream.fileno())
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.geteuid()
                    and stat.S_IMODE(meta.st_mode) == 0o600 and meta.st_nlink == 1)
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            named = lock.lstat()
            require((named.st_dev, named.st_ino) == (meta.st_dev, meta.st_ino))
            return self.apply('start', expected_binding=binding)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('start','status','restart'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(Manager(args.root,args.state_root).apply(args.action)))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('local runtime refused; verify private paths, matching bundle, service config and user supervisor', file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
