#!/usr/bin/env python3
import hashlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
BOOTSTRAP = os.path.join(HERE, 'bootstrap.sh')
TOOLS = os.path.join(HERE, 'tools.json')
AGENT_CLIS = ('claude codex cursor-agent agent pi opencode copilot goose gemini kimi qwen cline kilo crush vibe '
              'auggie kiro-cli junie amp agy oz sculpt hermes acpx droid').split()
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

    def wheel(self, name, version):
        path = os.path.join(self.dl, name)
        with zipfile.ZipFile(path, 'w') as z:
            z.writestr('fakewheel/__init__.py', '')
            z.writestr('fakewheel/cli.py', 'import sys\n'
                       'def main():\n'
                       '    with open(%r, "a") as f:\n'
                       '        f.write("runpane " + " ".join(sys.argv[1:]) + "\\n")\n'
                       '    print("fake %s (synthetic)")\n'
                       '    return 0\n' % (self.calls, version))
        return path

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

    def run(self, *args, tools=None):
        env = dict(PLANTED, HOME=self.home, LANG='C', TMPDIR=self.tmp, PATH=os.pathsep.join(
            [self.stubs, self.bin, '/usr/bin', '/bin']), http_proxy=DEAD_PROXY, https_proxy=DEAD_PROXY,
            HTTP_PROXY=DEAD_PROXY, HTTPS_PROXY=DEAD_PROXY, ALL_PROXY=DEAD_PROXY, no_proxy='', NO_PROXY='')
        return subprocess.run(['bash', BOOTSTRAP, '--tools', tools or self.tools] + list(args), env=env,
                              cwd=self.root, capture_output=True, text=True, timeout=120)

    def remove_downloads(self):
        for name in os.listdir(self.dl):
            os.remove(os.path.join(self.dl, name))

    def tree(self):
        found = []
        for d, _, files in os.walk(self.home):
            found += [os.path.join(d, f) for f in files]
        return sorted(found)


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

    def test_existing_launcher_is_never_replaced(self):
        launcher = os.path.join(self.fx.prefix, 'bin', 'fakeagent')
        os.makedirs(os.path.dirname(launcher))
        script(launcher, 'echo "fake 2.0.0 (synthetic)"\n')
        working = sha256(launcher)
        r = self.fx.run()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('left out fakeagent: your existing %s is kept (it does not name 3.2.1); move it aside to '
                      'install the pinned one' % launcher, self.summary(r.stdout)[1])
        self.assertEqual(sha256(launcher), working)
        self.assertEqual(read(self.fx.installer_log), '')

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
