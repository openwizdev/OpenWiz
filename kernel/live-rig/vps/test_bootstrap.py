#!/usr/bin/env python3
import hashlib
import io
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
BOOTSTRAP = os.path.join(HERE, 'bootstrap.sh')
TOOLS = os.path.join(HERE, 'tools.json')
AGENT_CLIS = ('claude codex cursor-agent agent cursor pi opencode copilot goose gemini kimi qwen cline kilo kilocode '
              'crush vibe auggie kiro-cli junie amp agy oz sculpt hermes acpx droid boat room-cli runpane pane '
              'openhands devin warp grok codespaces conductor').split()
PLATFORMS = ['linux-x86_64', 'linux-aarch64', 'darwin-x86_64', 'darwin-arm64']
PLANTED = {'GH_TOKEN': 'synthetic-planted-value', 'ANTHROPIC_API_KEY': 'synthetic-planted-value',
           'HERMES_INSTALL_CHANNEL': 'main', 'HERMES_INSTALL_DIR': '/synthetic/elsewhere'}
DEAD_PROXY = 'http://127.0.0.1:9'
PASSED_ON = {'HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TERM', 'TMPDIR', 'TZ', 'PATH',
             'DO_NOT_TRACK', 'PWD', 'OLDPWD', 'SHLVL', '_'}


def script(path, body):
    with open(path, 'w') as f:
        f.write('#!/bin/sh\n' + body)
    os.chmod(path, 0o755)


def sha256(path):
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def read(path):
    if not os.path.exists(path):
        return ''
    with open(path) as f:
        return f.read()


def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


class Fixture:
    def __init__(self, root):
        self.root = root
        self.home = os.path.join(root, 'home')
        self.prefix = os.path.join(self.home, '.local')
        self.dl = os.path.join(root, 'downloads')
        self.bin = os.path.join(root, 'bin')
        self.stubs = os.path.join(root, 'stubs')
        self.tmp = os.path.join(root, 'tmp')
        self.calls = os.path.join(root, 'calls.log')
        self.envs = os.path.join(root, 'env-names.log')
        self.installer_log = os.path.join(root, 'installer.log')
        for d in (self.home, self.dl, self.bin, self.stubs, self.tmp):
            os.makedirs(d)
        for name in AGENT_CLIS:
            script(os.path.join(self.stubs, name), 'echo "refused: %s is a stub" >&2\nexit 1\n' % name)
        script(os.path.join(self.bin, 'curl'), 'echo "curl 7.88.1 (synthetic)"\n')
        script(os.path.join(self.bin, 'git'), 'echo "git version 2.43.0 (synthetic)"\n')
        script(os.path.join(self.bin, 'sudo'), 'echo sudo-ran >> "%s"\nexec "$@"\n' % self.installer_log)
        script(os.path.join(self.bin, 'python3'), 'exec %s "$@"\n' % sys.executable)
        self.tools = self.write_tools()

    def logged_fake_tool(self, version):
        return ('echo "$(basename "$0") $*" >> "{calls}"\nenv | cut -d= -f1 >> "{envs}"\n'
                'echo "fake {version} (synthetic)"\n').format(calls=self.calls, envs=self.envs, version=version)

    def raw(self, name, version):
        path = os.path.join(self.dl, name)
        script(path, self.logged_fake_tool(version))
        return path

    def archive(self, name, member, version, zipped=False):
        body = ('#!/bin/sh\n' + self.logged_fake_tool(version)).encode()
        path = os.path.join(self.dl, name)
        if zipped:
            with zipfile.ZipFile(path, 'w') as z:
                info = zipfile.ZipInfo(member)
                info.external_attr = 0o755 << 16
                z.writestr(info, body)
        else:
            with tarfile.open(path, 'w:xz') as t:
                info = tarfile.TarInfo(member)
                info.size, info.mode = len(body), 0o755
                t.addfile(info, io.BytesIO(body))
        return path

    def wheel(self, name, version, tag='', gate=None, fail_if=None):
        path = os.path.join(self.dl, name)
        wait = ''
        if gate:
            wait = ('    import os, time\n'
                    '    open(%r, "w").close()\n'
                    '    while not os.path.exists(%r):\n'
                    '        time.sleep(0.02)\n' % (gate + '.probing', gate + '.go'))
        fail = ''
        if fail_if:
            fail = ('    import os\n'
                    '    if os.path.exists(%r):\n'
                    '        return 1\n' % fail_if)
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('fakewheel/__init__.py', '')
            z.writestr('fakewheel/cli.py', 'import sys\n'
                       'def main():\n' + wait + fail +
                       '    with open(%r, "a") as f:\n'
                       '        f.write("runpane%s " + " ".join(sys.argv[1:]) + "\\n")\n'
                       '    print("fake %s (synthetic)")\n'
                       '    return 0\n' % (self.calls, tag and ':' + tag, version))
        return path

    def repin(self, tag, gate=None, fail_if=None):
        with open(self.tools) as f:
            manifest = json.load(f)
        path = self.wheel('fake-2.4.246-%s.whl' % tag, '2.4.246', tag=tag, gate=gate, fail_if=fail_if)
        pane = [t for t in manifest['tools'] if t['name'] == 'runpane'][0]
        pane['files'] = {'any': {'url': 'file://' + path, 'sha256': sha256(path)}}
        tools = os.path.join(self.root, 'tools-%s.json' % tag)
        with open(tools, 'w') as f:
            json.dump(manifest, f)
        return tools, sha256(path)

    def installer_that_tries_sudo(self, name):
        payload = self.raw('fakeagent.payload', '3.2.1')
        path = os.path.join(self.dl, name)
        with open(path, 'w') as f:
            f.write('#!/usr/bin/env bash\n'
                    'echo "args: $*" >> "{log}"\n'
                    'env | cut -d= -f1 >> "{envs}"\n'
                    'sudo -n true 2>/dev/null && echo "sudo answered" >> "{log}"\n'
                    'echo "export PATH=\\"$HOME/.local/bin:\\$PATH\\"" >> "$HOME/.bashrc"\n'
                    'mkdir -p "$HOME/.local/bin" && cp "{payload}" "$HOME/.local/bin/fakeagent"\n'
                    .format(log=self.installer_log, envs=self.envs, payload=payload))
        return path

    def entry(self, path, **extra):
        return {p: dict({'url': 'file://' + path, 'sha256': sha256(path)}, **extra) for p in PLATFORMS}

    def write_tools(self, droid_version='1.17.2', droid_says='1.17.2', pane_says='2.4.246'):
        tools = [
            {'name': 'python3', 'kind': 'system', 'min_version': '3.9', 'hosts': ['all'],
             'source': 'the system package manager', 'why': 'synthetic'},
            {'name': 'git', 'kind': 'system', 'min_version': '2.0', 'hosts': ['all'],
             'source': 'the system package manager', 'why': 'synthetic'},
            {'name': 'curl', 'kind': 'archive', 'version': '8.23.0', 'system_min': '8.3', 'hosts': ['all'],
             'source': 'synthetic', 'why': 'synthetic',
             'files': self.entry(self.archive('curl.tar.xz', 'curl', '8.23.0'), member='curl')},
            {'name': 'gh', 'kind': 'archive', 'version': '2.105.0', 'hosts': ['all'], 'source': 'synthetic',
             'why': 'synthetic',
             'files': self.entry(self.archive('gh.zip', 'gh_x/bin/gh', '2.105.0', zipped=True),
                                 member='gh_x/bin/gh')},
            {'name': 'fakedroid', 'kind': 'binary', 'version': droid_version, 'hosts': ['factory'],
             'source': 'synthetic', 'why': 'synthetic',
             'files': self.entry(self.raw('fakedroid-' + droid_says, droid_says))},
            {'name': 'fakeapp', 'kind': 'binary', 'version': '2.4.246', 'run_version': False, 'hosts': ['pane'],
             'source': 'synthetic', 'why': 'synthetic', 'files': self.entry(self.raw('fakeapp', '2.4.246'))},
            {'name': 'runpane', 'kind': 'wheel', 'version': '2.4.246', 'module': 'fakewheel.cli',
             'hosts': ['pane'], 'source': 'synthetic', 'why': 'synthetic',
             'files': {'any': {'url': 'file://' + self.wheel('fake-%s.whl' % pane_says, pane_says),
                               'sha256': sha256(os.path.join(self.dl, 'fake-%s.whl' % pane_says))}}},
            {'name': 'fakeagent', 'kind': 'installer', 'version': '3.2.1', 'needs': ['git', 'curl'],
             'args': ['--pin', 'abc123', '--dir', '{home}/.fakeagent'], 'home_only': '~/.fakeagent',
             'hosts': ['hermes'], 'source': 'synthetic', 'why': 'synthetic',
             'files': {'any': {'url': 'file://' + self.installer_that_tries_sudo('install.sh'),
                               'sha256': sha256(os.path.join(self.dl, 'install.sh'))}}},
            {'name': 'gatedtool', 'kind': 'binary', 'version': '1.0.0', 'hosts': ['all'], 'source': 'synthetic',
             'why': 'synthetic', 'left_out': 'its only download needs a paid account'},
        ]
        path = os.path.join(self.root, 'tools.json')
        with open(path, 'w') as f:
            json.dump({'tools': tools}, f)
        return path

    def env(self):
        return dict(PLANTED, HOME=self.home, LANG='C', TMPDIR=self.tmp, PATH=os.pathsep.join(
            [self.stubs, self.bin, '/usr/bin', '/bin']), http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
            HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY, no_proxy='', NO_PROXY='')

    def run(self, *args, tools=None, timeout=120):
        return subprocess.run(['bash', BOOTSTRAP, '--tools', tools or self.tools] + list(args), env=self.env(),
                              cwd=self.root, capture_output=True, text=True, timeout=timeout)

    def start(self, tag, tools):
        out, err = (os.path.join(self.root, '%s.%s' % (tag, x)) for x in ('out', 'err'))
        with open(out, 'w') as o, open(err, 'w') as e:
            proc = subprocess.Popen(['bash', BOOTSTRAP, '--tools', tools], env=self.env(), cwd=self.root,
                                    stdout=o, stderr=e)
        return proc, out, err

    def remove_downloads(self):
        for name in os.listdir(self.dl):
            os.remove(os.path.join(self.dl, name))

    def tree(self):
        found = []
        for d, _, files in os.walk(self.home):
            found += [os.path.join(d, f) for f in files]
        return sorted(found)


def wait_for(check):
    for _ in range(3000):
        if check():
            return
        time.sleep(0.02)
    raise AssertionError('timed out waiting for the fixture')


class BootstrapTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.fx = Fixture(self.root)

    def summary(self, out):
        lines = out.rstrip('\n').split('\n')
        index = [i for i, line in enumerate(lines) if line.startswith('bootstrap: ')]
        self.assertEqual(len(index), 1, out)
        return lines[index[0]], lines[index[0] + 1:]

    def dry_run_watching_tmp(self, tools=None):
        os.utime(self.fx.tmp, ns=(10 ** 18, 10 ** 18))
        return self.fx.run('--dry-run', tools=tools)

    def assert_wrote_nothing(self):
        self.assertEqual(self.fx.tree(), [])
        self.assertEqual(os.stat(self.fx.tmp).st_mtime_ns, 10 ** 18, 'something was made or removed in TMPDIR')
        self.assertEqual(read(self.fx.calls), '')

    def test_dry_run_prints_every_step_and_writes_nothing(self):
        self.fx.remove_downloads()
        r = self.dry_run_watching_tmp()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for name in ('curl 8.23.0', 'gh 2.105.0', 'fakedroid 1.17.2', 'fakeapp 2.4.246', 'runpane 2.4.246',
                     'fakeagent 3.2.1'):
            self.assertIn('would install ' + name, r.stdout)
        self.assertIn('already there python3', r.stdout)
        self.assertIn('already there git', r.stdout)
        line, rest = self.summary(r.stdout)
        self.assertEqual(line, 'bootstrap: dry run, 6 to install, 2 already there, 1 left out')
        self.assertEqual(rest, ['left out gatedtool: its only download needs a paid account'])
        self.assert_wrote_nothing()

    def test_real_tools_plan_offline_on_refusing_downloads(self):
        with open(TOOLS) as f:
            manifest = json.load(f)
        for tool in manifest['tools']:
            for file in tool.get('files', {}).values():
                file['url'] = 'file://' + os.path.join(self.root, 'refused', tool['name'])
        offline = os.path.join(self.root, 'offline-tools.json')
        with open(offline, 'w') as f:
            json.dump(manifest, f)
        r = self.dry_run_watching_tmp(tools=offline)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assert_wrote_nothing()
        if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
            self.skipTest('the exact plan is pinned for Linux x86_64 and aarch64')
        planned = re.findall(r'(?m)^would install (\S+) (\S+) from file://', r.stdout)
        self.assertEqual(planned, [('curl', '8.23.0'), ('gh', '2.105.0'), ('hermes', '0.23.3'),
                                   ('runpane', '2.4.246'), ('pane', '2.4.246'), ('droid', '1.17.2')])
        self.assertEqual(self.summary(r.stdout), ('bootstrap: dry run, 6 to install, 2 already there, 0 left out', []))

    def test_fixture_install_into_home_prefix(self):
        r = self.fx.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line, rest = self.summary(r.stdout)
        self.assertEqual(line, 'bootstrap: 6 installed, 2 already there, 1 left out')
        self.assertEqual(rest, ['left out gatedtool: its only download needs a paid account'])
        for name in ('curl 8.23.0', 'gh 2.105.0', 'fakedroid 1.17.2', 'fakeapp 2.4.246', 'runpane 2.4.246',
                     'fakeagent 3.2.1'):
            self.assertRegex(r.stdout, '(?m)^installed %s$' % name)
            self.assertTrue(os.access(os.path.join(self.fx.prefix, 'bin', name.split()[0]), os.X_OK), name)
        log = read(self.fx.installer_log)
        self.assertIn('args: --pin abc123 --dir %s/.fakeagent\n' % self.fx.home, log)
        self.assertNotIn('sudo', log)
        calls = read(self.fx.calls).splitlines()
        self.assertEqual(sorted(calls), sorted('%s --version' % n for n in
                                               ('curl', 'gh', 'fakedroid', 'runpane', 'fakeagent')))
        names = set(read(self.fx.envs).split())
        self.assertTrue(names, 'no environment was recorded')
        self.assertEqual(names - PASSED_ON, set())
        self.assertEqual(os.listdir(self.fx.tmp), [])

    def test_checksum_mismatch_is_refused_and_nothing_from_it_runs(self):
        with open(os.path.join(self.fx.dl, 'install.sh'), 'a') as f:
            f.write('echo tampered >> "%s"\n' % self.fx.installer_log)
        with open(os.path.join(self.fx.dl, 'fakedroid-1.17.2'), 'a') as f:
            f.write('# tampered\n')
        r = self.fx.run()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        line, rest = self.summary(r.stdout)
        self.assertEqual(line, 'bootstrap: 4 installed, 2 already there, 3 left out')
        self.assertEqual(len(rest), 3, rest)
        for name in ('fakedroid', 'fakeagent'):
            self.assertTrue(any(re.match(r'left out %s: checksum mismatch: expected [0-9a-f]{64}, got [0-9a-f]{64}$'
                                         % name, x) for x in rest), rest)
            self.assertFalse(os.path.lexists(os.path.join(self.fx.prefix, 'bin', name)), name)
        self.assertEqual(read(self.fx.installer_log), '')
        self.assertNotIn('fakedroid', read(self.fx.calls))

    def test_second_run_installs_nothing(self):
        first = self.fx.run()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = {p: sha256(p) for p in self.fx.tree()}
        installer_log = read(self.fx.installer_log)
        self.fx.remove_downloads()
        r = self.fx.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line, rest = self.summary(r.stdout)
        self.assertEqual(line, 'bootstrap: 0 installed, 8 already there, 1 left out')
        self.assertEqual({p: sha256(p) for p in self.fx.tree()}, before)
        self.assertEqual(read(self.fx.installer_log), installer_log)

    def test_wrong_version_keeps_the_working_tool(self):
        self.assertEqual(self.fx.run().returncode, 0)
        dst = os.path.join(self.fx.prefix, 'bin', 'fakedroid')
        working = sha256(dst)
        r = self.fx.run(tools=self.fx.write_tools(droid_version='1.17.3', droid_says='9.9.9'))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('left out fakedroid: `fakedroid --version` does not name 1.17.3 (the existing one is kept)',
                      self.summary(r.stdout)[1])
        self.assertEqual(sha256(dst), working)
        self.assertFalse(os.path.exists(os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'staged')))

    def test_same_version_repin_that_fails_keeps_the_working_wheel(self):
        self.assertEqual(self.fx.run().returncode, 0)
        lib = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps')
        launcher = os.path.join(self.fx.prefix, 'bin', 'runpane')
        imported = re.findall(r"(%s/[^' ]+\.whl)" % re.escape(lib), read(launcher))
        self.assertEqual(len(imported), 1, read(launcher))
        before = {p: sha256(p) for p in self.fx.tree()}
        r = self.fx.run(tools=self.fx.write_tools(pane_says='9.9.9'))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('left out runpane: `runpane --version` does not name 2.4.246 (the existing one is kept)',
                      self.summary(r.stdout)[1])
        self.assertEqual({p: sha256(p) for p in self.fx.tree()}, before)
        self.assertEqual(subprocess.run([launcher, '--version'], capture_output=True, text=True).stdout,
                         'fake 2.4.246 (synthetic)\n')

    def assert_runpane_at(self, pin):
        lib = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps')
        with open(os.path.join(lib, 'runpane.json')) as f:
            stamp = json.load(f)
        launcher = os.path.join(self.fx.prefix, 'bin', 'runpane')
        self.assertEqual(stamp, {'version': '2.4.246', 'sha256': pin, 'launcher_type': 'file',
                                 'launcher': sha256(launcher)})
        wheel = os.path.join(lib, 'wheels', 'runpane', pin + '.whl')
        self.assertEqual(re.findall(r"(%s/[^' ]+\.whl)" % re.escape(lib), read(launcher)), [wheel])
        self.assertEqual(os.listdir(os.path.dirname(wheel)), [pin + '.whl'])
        self.assertEqual(sha256(wheel), pin)
        self.assertEqual(subprocess.run([launcher, '--version'], capture_output=True, text=True).stdout,
                         'fake 2.4.246 (synthetic)\n')

    def plant_corrupt_cache(self, pin):
        cache = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'wheels', 'runpane', pin + '.whl')
        shutil.copy(self.fx.wheel('corrupt.whl', '2.4.246', tag='corrupt'), cache)
        self.assertNotEqual(sha256(cache), pin)
        return cache

    def test_corrupt_cached_wheel_is_never_imported(self):
        self.assertEqual(self.fx.run().returncode, 0)
        tools, pin = self.fx.repin('valid')
        cache = self.plant_corrupt_cache(pin)
        r = self.fx.run(tools=tools)
        self.assertNotIn('runpane:corrupt', read(self.fx.calls))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, '(?m)^installed runpane 2.4.246$')
        self.assertEqual(sha256(cache), pin)
        self.assert_runpane_at(pin)

    def test_failed_recovery_from_a_corrupt_cache_keeps_the_working_tool(self):
        self.assertEqual(self.fx.run().returncode, 0)
        with open(os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'runpane.json')) as f:
            working = json.load(f)['sha256']
        tools, pin = self.fx.repin('valid')
        cache = self.plant_corrupt_cache(pin)
        os.makedirs(cache + '.part')
        before = {p: sha256(p) for p in self.fx.tree()}
        r = self.fx.run(tools=tools)
        self.assertNotIn('runpane:corrupt', read(self.fx.calls))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('left out runpane: its cached wheel fails its checksum and cannot be replaced: '
                      'IsADirectoryError (the existing one is kept)', self.summary(r.stdout)[1])
        self.assertEqual({p: sha256(p) for p in self.fx.tree()}, before)
        os.rmdir(cache + '.part')
        os.remove(cache)
        self.assert_runpane_at(working)

    def test_overlapping_repins_leave_one_verified_install(self):
        self.assertEqual(self.fx.run().returncode, 0)
        gate = os.path.join(self.root, 'gate')
        tools_a, _ = self.fx.repin('a', gate=gate)
        tools_b, pin_b = self.fx.repin('b')
        a, a_out, a_err = self.fx.start('a', tools_a)
        self.addCleanup(a.kill)
        wait_for(lambda: os.path.exists(gate + '.probing') or a.poll() is not None)
        self.assertIsNone(a.poll(), read(a_out) + read(a_err))
        b, b_out, b_err = self.fx.start('b', tools_b)
        self.addCleanup(b.kill)
        wait_for(lambda: b.poll() is not None or 'waiting for another bootstrap' in read(b_err))
        open(gate + '.go', 'w').close()
        for proc, out, err in ((a, a_out, a_err), (b, b_out, b_err)):
            self.assertEqual(proc.wait(timeout=120), 0, read(out) + read(err))
            self.assertRegex(read(out), '(?m)^installed runpane 2.4.246$')
        self.assertIn('bootstrap: waiting for another bootstrap on %s' % self.fx.prefix, read(b_err))
        self.assert_runpane_at(pin_b)

    def hand_replace(self, name):
        launcher = os.path.join(self.fx.prefix, 'bin', name)
        script(launcher, 'echo "%s ran by hand $*" >> "%s"\necho "fake 2.4.246 (synthetic)"\n' % (name, self.fx.calls))
        return launcher, sha256(launcher)

    def assert_kept_by_hand(self, r, name, launcher, before):
        self.assertNotIn('ran by hand', read(self.fx.calls))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('left out %s: your existing %s is not the copy this bootstrap installed there (or its record is '
                      'too old to tell), so it is kept and never run; move it aside to install the pinned 2.4.246'
                      % (name, launcher), self.summary(r.stdout)[1])
        self.assertEqual(sha256(launcher), before)

    def test_a_hand_replaced_launcher_is_kept_on_a_repin(self):
        self.assertEqual(self.fx.run().returncode, 0)
        launcher, before = self.hand_replace('runpane')
        tools, _ = self.fx.repin('valid')
        r = self.fx.run(tools=tools)
        self.assert_kept_by_hand(r, 'runpane', launcher, before)

    def test_a_stamp_that_names_no_launcher_keeps_it(self):
        self.assertEqual(self.fx.run().returncode, 0)
        stamp = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'runpane.json')
        with open(stamp) as f:
            legacy = {k: v for k, v in json.load(f).items() if k in ('version', 'sha256')}
        with open(stamp, 'w') as f:
            json.dump(legacy, f)
        launcher, before = self.hand_replace('runpane')
        r = self.fx.run()
        self.assert_kept_by_hand(r, 'runpane', launcher, before)

    def test_a_user_symlink_to_a_stamped_binary_survives_a_repin(self):
        self.assertEqual(self.fx.run().returncode, 0)
        launcher = os.path.join(self.fx.prefix, 'bin', 'fakedroid')
        moved = os.path.join(self.root, 'moved-fakedroid')
        shutil.move(launcher, moved)
        before = sha256(moved)
        os.symlink(moved, launcher)
        r = self.fx.run(tools=self.fx.write_tools(droid_version='1.17.3', droid_says='1.17.3'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.islink(launcher), 'user symlink was replaced on repin')
        self.assertEqual(os.readlink(launcher), moved)
        self.assertEqual(sha256(moved), before)
        self.assertIn('left out fakedroid: your existing %s is not the copy this bootstrap installed there (or its '
                      'record is too old to tell), so it is kept and never run; move it aside to install the pinned '
                      '1.17.3' % launcher, self.summary(r.stdout)[1])
        self.assertEqual(read(self.fx.calls).splitlines().count('fakedroid --version'), 1)

    def test_an_unrecognised_launcher_entry_type_fails_closed(self):
        self.assertEqual(self.fx.run().returncode, 0)
        launcher = os.path.join(self.fx.prefix, 'bin', 'fakedroid')
        before = sha256(launcher)
        stamp = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'fakedroid.json')
        with open(stamp) as f:
            data = json.load(f)
        data['launcher_type'] = 'unrecognised'
        with open(stamp, 'w') as f:
            json.dump(data, f)
        r = self.fx.run(tools=self.fx.write_tools(droid_version='1.17.3', droid_says='1.17.3'))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('left out fakedroid: your existing %s is not the copy this bootstrap installed there (or its '
                      'record is too old to tell), so it is kept and never run; move it aside to install the pinned '
                      '1.17.3' % launcher, self.summary(r.stdout)[1])
        self.assertEqual(sha256(launcher), before)

    def test_a_failed_same_pin_probe_leaves_the_active_install_byte_identical(self):
        fail_if = os.path.join(self.root, 'fail-probe')
        tools, pin = self.fx.repin('probe', fail_if=fail_if)
        self.assertEqual(self.fx.run(tools=tools).returncode, 0)
        wheel = self.plant_corrupt_cache(pin)
        launcher = os.path.join(self.fx.prefix, 'bin', 'runpane')
        stamp = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'runpane.json')
        before = {p: read_bytes(p) for p in (launcher, wheel, stamp)}
        open(fail_if, 'w').close()
        r = self.fx.run(tools=tools)
        self.assertNotIn('runpane:corrupt', read(self.fx.calls))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn('left out runpane: `runpane --version` does not name 2.4.246 (the existing one is kept)',
                      self.summary(r.stdout)[1])
        for p, expected in before.items():
            self.assertTrue(os.path.isfile(p), 'active file missing after failed probe: %s' % p)
            self.assertEqual(read_bytes(p), expected, 'active file changed after failed probe: %s' % p)

    def test_a_fifo_at_a_stamped_launcher_path_is_refused_without_opening(self):
        self.assertEqual(self.fx.run().returncode, 0)
        launcher = os.path.join(self.fx.prefix, 'bin', 'fakedroid')
        os.remove(launcher)
        os.mkfifo(launcher)
        try:
            r = self.fx.run(tools=self.fx.write_tools(droid_version='1.17.3', droid_says='1.17.3'), timeout=5)
        except subprocess.TimeoutExpired:
            self.fail('bootstrap blocked opening a FIFO at %s' % launcher)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(stat.S_ISFIFO(os.lstat(launcher).st_mode), 'FIFO was replaced or removed')
        self.assertIn('left out fakedroid: your existing %s is not the copy this bootstrap installed there (or its '
                      'record is too old to tell), so it is kept and never run; move it aside to install the pinned '
                      '1.17.3' % launcher, self.summary(r.stdout)[1])

    def test_sign_in_page_notes_earlier_install_waits_for_2929(self):
        page = read(os.path.join(HERE, 'SIGN-IN.md'))
        self.assertRegex(page, r'(?i)earlier bootstrap install[^\n]*#2929[^\n]*re-running',
                         'SIGN-IN.md does not note that an earlier bootstrap install waits for #2929')
        self.assertRegex(page, r"(?i)fresh install[^\n]*(?:not affected|isn't affected)",
                         'SIGN-IN.md does not note that a fresh install is not affected')

    def test_a_same_pin_rerun_hashes_the_active_wheel(self):
        self.assertEqual(self.fx.run().returncode, 0)
        with open(os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'runpane.json')) as f:
            pin = json.load(f)['sha256']
        wheel = self.plant_corrupt_cache(pin)
        saved = os.path.join(self.root, 'saved-downloads')
        shutil.copytree(self.fx.dl, saved)
        self.fx.remove_downloads()
        offline = self.fx.run()
        self.assertNotIn('runpane:corrupt', read(self.fx.calls))
        self.assertEqual(offline.returncode, 1, offline.stdout + offline.stderr)
        self.assertTrue(any(x.startswith('left out runpane: download failed: ') for x in self.summary(offline.stdout)[1]),
                        offline.stdout)
        for name in os.listdir(saved):
            shutil.copy(os.path.join(saved, name), self.fx.dl)
        r = self.fx.run()
        self.assertNotIn('runpane:corrupt', read(self.fx.calls))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, '(?m)^installed runpane 2.4.246$')
        self.assertEqual(sha256(wheel), pin)
        self.assert_runpane_at(pin)

    def test_home_only_installer_is_refused_under_another_prefix(self):
        prefix = os.path.join(self.root, 'elsewhere')
        r = self.fx.run('--prefix', prefix)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('left out fakeagent: its installer installs into your home (~/.fakeagent) with no option to '
                      'confine it, so it is never installed under --prefix; run without --prefix to install it',
                      self.summary(r.stdout)[1])
        self.assertEqual(read(self.fx.installer_log), '')
        self.assertEqual(self.fx.tree(), [])
        self.assertTrue(os.path.isfile(os.path.join(prefix, 'bin', 'gh')))

    def test_existing_tools_it_did_not_install_are_kept_and_never_run(self):
        pins = {'curl': '8.23.0', 'fakedroid': '1.17.2', 'runpane': '2.4.246', 'fakeagent': '3.2.1'}
        os.makedirs(os.path.join(self.fx.prefix, 'bin'))
        for name in pins:
            script(os.path.join(self.fx.prefix, 'bin', name),
                   'echo "%s ran $*" >> "%s"\necho "fake %s (synthetic)"\n' % (name, self.fx.calls, pins[name]))
        before = {p: sha256(p) for p in self.fx.tree()}
        r = self.fx.run()
        self.assertEqual(read(self.fx.calls).count(' ran '), 0, read(self.fx.calls))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line, rest = self.summary(r.stdout)
        self.assertEqual(line, 'bootstrap: 2 installed, 2 already there, 5 left out')
        for name, version in pins.items():
            self.assertIn('left out %s: your existing %s was not installed by this bootstrap, so it is kept and never '
                          'run; move it aside to install the pinned %s'
                          % (name, os.path.join(self.fx.prefix, 'bin', name), version), rest)
        self.assertEqual({p: sha256(p) for p in self.fx.tree() if p in before}, before)
        self.assertEqual(read(self.fx.installer_log), '')

    def test_an_older_pin_of_an_installed_tool_is_kept_and_its_installer_never_rerun(self):
        self.assertEqual(self.fx.run().returncode, 0)
        stamp = os.path.join(self.fx.prefix, 'lib', 'openwiz-vps', 'fakeagent.json')
        with open(stamp) as f:
            older = dict(json.load(f), version='3.2.0', sha256='0' * 64)
        with open(stamp, 'w') as f:
            json.dump(older, f)
        launcher = os.path.join(self.fx.prefix, 'bin', 'fakeagent')
        before, calls, installer_log = sha256(launcher), read(self.fx.calls), read(self.fx.installer_log)
        r = self.fx.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('left out fakeagent: your existing %s is kept and not run, since its installer would overwrite '
                      'it in place; move it aside to install the pinned 3.2.1' % launcher, self.summary(r.stdout)[1])
        self.assertEqual((sha256(launcher), read(self.fx.calls), read(self.fx.installer_log)),
                         (before, calls, installer_log))

    def test_too_old_system_tool_is_left_out_with_its_reason(self):
        script(os.path.join(self.fx.bin, 'git'), 'echo "git version 1.8.5 (synthetic)"\n')
        r = self.fx.run('--dry-run')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        line, rest = self.summary(r.stdout)
        self.assertEqual(line, 'bootstrap: dry run, 5 to install, 1 already there, 3 left out')
        self.assertIn('left out git: git 1.8.5 is older than 2.0; install git 2.0 or later with your system package '
                      'manager (this bootstrap never runs sudo)', rest)
        self.assertIn('left out fakeagent: needs git', rest)


class ToolsJsonTest(unittest.TestCase):
    def test_every_tool_names_its_source_exact_version_checksum_and_why(self):
        with open(TOOLS) as f:
            tools = json.load(f)['tools']
        names = [t['name'] for t in tools]
        for need in ('hermes', 'runpane', 'pane', 'droid', 'curl', 'git', 'gh', 'python3'):
            self.assertIn(need, names)
        hosts = {h for t in tools for h in t['hosts']}
        self.assertTrue({'hermes', 'pane', 'factory', 'conductor', 'cursor'} <= hosts, hosts)
        for t in tools:
            self.assertTrue(t['source'].startswith('https://') or t['kind'] == 'system', t['name'])
            self.assertGreater(len(t['why']), 20, t['name'])
            if t['kind'] == 'system':
                self.assertRegex(t['min_version'], r'^\d+\.\d+$')
                continue
            self.assertRegex(t['version'], r'^\d+\.\d+\.\d+$', t['name'])
            self.assertTrue(t['files'], t['name'])
            for platform_key, file in t['files'].items():
                self.assertIn(platform_key, PLATFORMS + ['any'])
                self.assertTrue(file['url'].startswith('https://'), file)
                self.assertRegex(file['sha256'], r'^[0-9a-f]{64}$', file)
        curl = [t for t in tools if t['name'] == 'curl'][0]
        self.assertEqual(curl['system_min'], '8.3')
        hermes = [t for t in tools if t['name'] == 'hermes'][0]
        self.assertTrue(hermes.get('home_only'))
        self.assertNotIn('{prefix}', ' '.join(hermes['args']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
