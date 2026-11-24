#!/usr/bin/env python3
import ast
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.join(HERE, '..', '..', '..'))
HOSTS = os.path.join(HERE, 'hosts')
PAGE = os.path.join(HERE, 'SIGN-IN.md')
RIG = os.path.join(ROOT, 'kernel', 'live-rig', 'rig.py')
KIT = os.path.join(ROOT, 'kernel', 'driver-kit', 'kit.py')
# SAFETY: refusing stubs first on PATH for every agent CLI, except a fake a test wires on purpose, so a config or
# fixture mistake can never start a real one. No real status or sign-in command is ever on a test's PATH.
AGENT_CLIS = ['claude', 'codex', 'cursor-agent', 'agent', 'cursor', 'pi', 'opencode', 'copilot', 'goose', 'gemini',
              'kimi', 'qwen', 'cline', 'kilo', 'kilocode', 'crush', 'vibe', 'auggie', 'kiro-cli', 'junie', 'amp',
              'agy', 'oz', 'sculpt', 'hermes', 'acpx', 'droid', 'boat', 'room-cli', 'runpane', 'pane', 'openhands',
              'devin', 'warp', 'grok', 'codespaces', 'conductor']
SECRET = 'fk-' + 'Synthetic0Vps0Value' * 2
CONFIGS = {
    'hermes': {'host': 'Hermes', 'driver': 'adapters/hermes/driver', 'tool': 'hermes', 'key': None, 'harness': 'claude'},
    'pane': {'host': 'Pane', 'driver': 'adapters/pane/driver', 'tool': 'runpane', 'key': None, 'harness': 'claude'},
    'factory': {'host': 'Factory', 'driver': 'adapters/factory/driver', 'tool': 'droid', 'key': 'FACTORY_API_KEY', 'harness': 'droid'},
    'conductor': {'host': 'Conductor', 'driver': 'adapters/conductor/driver', 'tool': 'curl', 'key': 'CONDUCTOR_API_KEY',
                  'harness': 'claude'},
    'cursor': {'host': 'Cursor', 'driver': 'adapters/cursor/driver', 'tool': 'curl', 'key': 'CURSOR_API_KEY', 'harness': 'cursor'},
}
KEYCHAIN = {'conductor': 'openwiz-conductor', 'cursor': 'openwiz-cursor-cloud'}
KEYCHAIN_TOOLS = ['secret-tool', 'security', 'gdbus', 'busctl', 'dbus-send', 'kwallet-query']
APPROACH = 'docs/evidence/2895/approach.md'
GH_PROBE = ['env', 'GH_TELEMETRY=0', 'gh', 'config', 'get', '-h', 'github.com', 'user']
BILLS = {'hermes': 'unknown', 'pane': 'unknown', 'factory': 'unknown', 'conductor': 'unknown', 'cursor': 'unknown'}
SITUATIONS = ('tool missing', 'gh missing', 'tool signed out', 'key name unset', 'gh signed out', 'signed in')


def load(name, path):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def host_names():
    return sorted(n[:-len('.json')] for n in (os.listdir(HOSTS) if os.path.isdir(HOSTS) else []) if n.endswith('.json'))


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=Example', '-c', 'user.email=example@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null'] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Configs(unittest.TestCase):
    def test_the_five_configs_load_through_rig_load_host(self):
        rig = load('rig', RIG)
        self.assertEqual(host_names(), sorted(CONFIGS))
        self.assertEqual(sorted(h['host'] for h in rig.load_hosts(HOSTS, None)),
                         sorted(c['host'] for c in CONFIGS.values()))
        for name, want in CONFIGS.items():
            with self.subTest(host=name):
                config = rig.load_host(os.path.join(HOSTS, name + '.json'))
                self.assertEqual(config['host'], want['host'])
                self.assertEqual(config['driver'], want['driver'])
                self.assertEqual(config['needs'], [want['tool'], 'gh'])
                self.assertEqual(config['cost'], 'paid')
                self.assertEqual([r['harness'] for r in config['runs']], [want['harness']])
                self.assertEqual(config['signed_in'][-1], GH_PROBE)
                self.assertEqual([c for c in config['signed_in'] if c[0] == 'gh' or
                                  c[0] == 'env' and 'gh' in c], [GH_PROBE])
                self.assertFalse(any(c[:3] == ['claude', 'auth', 'status'] for c in config['signed_in']))


class KeyProbe(unittest.TestCase):
    def probe(self, host):
        with open(os.path.join(HOSTS, host + '.json')) as f:
            config = json.load(f)
        probes = [c for c in config['signed_in'] if c[0] == 'python3']
        self.assertEqual(len(probes), 1)
        self.assertEqual(probes[0][:3], ['python3', '-I', '-c'])
        self.assertEqual(len(probes[0]), 4)
        return probes[0][3]

    def test_the_key_probe_compares_names_only_and_starts_nothing(self):
        for host, entry in sorted(KEYCHAIN.items()):
            with self.subTest(host=host):
                tree = ast.parse(self.probe(host))
                variable = CONFIGS[host]['key']
                environ = []
                for node in ast.walk(tree):
                    self.assertNotIsInstance(node, (ast.Subscript, ast.ImportFrom, ast.Lambda, ast.Starred))
                    if isinstance(node, ast.Import):
                        self.assertLessEqual({a.name for a in node.names}, {'os', 'sys'})
                    if isinstance(node, ast.Attribute):
                        self.assertIn((getattr(node.value, 'id', None), node.attr), {('os', 'environ'), ('sys', 'exit')})
                        if node.attr == 'environ':
                            environ.append(node)
                    if isinstance(node, ast.Call):
                        name = node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)
                        self.assertIn(name, {'any', 'sys.exit'})
                    if isinstance(node, ast.Compare):
                        self.assertEqual([type(o) for o in node.ops], [ast.Eq])
                        self.assertEqual([getattr(c, 'value', None) for c in node.comparators], [variable])
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, {'open', 'exec', 'eval', 'getattr', '__import__', 'vars'})
                iters = [g.iter for g in ast.walk(tree) if isinstance(g, ast.comprehension)]
                self.assertTrue(environ)
                self.assertTrue(all(any(e is i for i in iters) for e in environ), 'os.environ only as names to iterate')

    def test_the_key_probe_says_why_a_keychain_only_key_skips(self):
        for host, entry in sorted(KEYCHAIN.items()):
            with self.subTest(host=host):
                texts = [n.value for n in ast.walk(ast.parse(self.probe(host)))
                         if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value != CONFIGS[host]['key']]
                self.assertEqual(len(texts), 1, 'one why string in the probe')
                why = texts[0]
                for word in (entry, 'skipped: not signed in', 'prompt', APPROACH):
                    self.assertIn(word, why)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, APPROACH)))


class Skips(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.checkout = os.path.join(self.folder, 'checkout')
        self.hosts = os.path.join(self.checkout, 'kernel', 'live-rig', 'vps', 'hosts')
        shutil.copytree(HOSTS, self.hosts)
        shutil.copy2(RIG, os.path.join(self.checkout, 'kernel', 'live-rig', 'rig.py'))
        os.makedirs(os.path.join(self.checkout, 'kernel', 'driver-kit'))
        shutil.copy2(KIT, os.path.join(self.checkout, 'kernel', 'driver-kit', 'kit.py'))
        git(self.checkout, 'init', '-q')
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'fixture checkout')
        self.settings = os.path.join(self.folder, 'settings.json')
        with open(self.settings, 'w') as f:
            json.dump({'repo': 'example/vps-throwaway', 'ticket': 7}, f)
        self.log = os.path.join(self.folder, 'calls.log')

    def path_of_stubs_then_fakes(self, situation, tool):
        stubs, fakes = tempfile.mkdtemp(dir=self.folder), tempfile.mkdtemp(dir=self.folder)
        wired = {'tool missing': [], 'gh missing': [tool]}.get(situation, [tool, 'gh'])
        # SAFETY: PATH holds only these folders, so nothing real can answer for a missing tool, which gets no stub
        # either (a stub would count as installed).
        absent = [tool] if situation == 'tool missing' else []
        for name in AGENT_CLIS:
            if name not in wired + absent:
                with open(os.path.join(stubs, name), 'w') as f:
                    f.write('#!/bin/sh\necho "%s: refused, the VPS host tests never start an agent CLI" >&2\n'
                            'exit 1\n' % name)
                os.chmod(os.path.join(stubs, name), 0o755)
        for name in wired:
            out = name == 'gh' and situation == 'gh signed out' or name == tool and situation == 'tool signed out'
            only = ' '.join(GH_PROBE[3:]) if name == 'gh' else ''
            with open(os.path.join(fakes, name), 'w') as f:
                f.write('#!/bin/sh\necho "%s $*" >> "%s"\n' % (name, self.log))
                if only:
                    f.write('[ "$GH_TELEMETRY" = 0 ] && [ "$*" = "%s" ] || '
                            '{ echo "%s refused" >> "%s"; exit 2; }\n' % (only, name, self.log))
                f.write('exit %d\n' % (1 if out else 0))
            os.chmod(os.path.join(fakes, name), 0o755)
        if situation == 'key in keychain only':
            # SAFETY: fake keychain tools that answer as if the entry existed, and print the planted value, so a probe
            # that called one would pass, log the call, or leak the value; never a real keychain.
            for name in KEYCHAIN_TOOLS:
                with open(os.path.join(fakes, name), 'w') as f:
                    f.write('#!/bin/sh\necho "%s $*" >> "%s"\necho "%s"\nexit 0\n' % (name, self.log, SECRET))
                os.chmod(os.path.join(fakes, name), 0o755)
        for name, real in (('env', shutil.which('env')), ('git', shutil.which('git')),
                           ('python3', sys.executable)):
            os.symlink(real, os.path.join(fakes, name))
        return stubs + os.pathsep + fakes

    def fixture_env(self, host, situation):
        env = {'PATH': self.path_of_stubs_then_fakes(situation, CONFIGS[host]['tool']), 'HOME': self.folder,
               'LANG': 'C.UTF-8'}
        for key in ('FACTORY_API_KEY', 'CONDUCTOR_API_KEY', 'CURSOR_API_KEY'):
            if situation not in ('key name unset', 'key in keychain only'):
                env[key] = SECRET
        return env

    def rig(self, host, situation):
        want = CONFIGS[host]
        env = self.fixture_env(host, situation)
        out = os.path.join(self.folder, 'out-' + host + '-' + situation.replace(' ', '-'))
        p = subprocess.run([sys.executable, '-I', os.path.join(self.checkout, 'kernel', 'live-rig', 'rig.py'),
                            '--hosts', self.hosts, '--settings', self.settings, '--out', out, '--host', want['host']],
                           cwd=self.checkout, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=120)
        records = []
        for day in os.listdir(out) if os.path.isdir(out) else []:
            if os.path.isdir(os.path.join(out, day)):
                for name in os.listdir(os.path.join(out, day)):
                    with open(os.path.join(out, day, name)) as f:
                        records.append(json.load(f))
        return p, records

    def test_each_config_gives_its_exact_skip_line_and_starts_nothing(self):
        for host, config in CONFIGS.items():
            missing = {'tool missing': 'not installed: ' + config['tool'], 'gh missing': 'not installed: gh'}
            for situation in SITUATIONS:
                why = missing.get(situation, 'cost')
                with self.subTest(host=host, situation=situation):
                    p, records = self.rig(host, situation)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual(p.stdout, 'skipped %s %s: %s\n' % (CONFIGS[host]['host'], CONFIGS[host]['harness'],
                                                                         why))
                    self.assertEqual([(r['outcome'], r['skipped'], r['kit_exit']) for r in records],
                                     [('skipped', why, None)])
                    self.assertFalse(os.path.exists(self.log))
                    for text in (p.stdout, p.stderr, json.dumps(records)):
                        self.assertNotIn(SECRET, text)

    def test_a_keychain_only_key_skips_and_no_keychain_tool_is_called(self):
        rig = load('rig', RIG)
        for host in sorted(KEYCHAIN):
            with self.subTest(host=host):
                config = rig.load_host(os.path.join(HOSTS, host + '.json'))
                with patch.dict(os.environ, self.fixture_env(host, 'key in keychain only'), clear=True):
                    self.assertEqual(rig.check_host(dict(config, cost='none')), 'not signed in: python3')
                calls = []
                if os.path.isfile(self.log):
                    with open(self.log) as f:
                        calls = f.read().splitlines()
                self.assertEqual([c for c in calls if c.split()[0] in KEYCHAIN_TOOLS], [])

    def test_cost_override_runs_only_the_read_only_status_commands(self):
        rig = load('rig', RIG)
        for host in CONFIGS:
            with self.subTest(host=host):
                config = rig.load_host(os.path.join(HOSTS, host + '.json'))
                with patch.dict(os.environ, self.fixture_env(host, 'signed in'), clear=True):
                    self.assertIsNone(rig.check_host(dict(config, cost='none')))
        calls = []
        if os.path.isfile(self.log):
            with open(self.log) as f:
                calls = f.read().splitlines()
        self.assertEqual(sorted(calls), sorted([' '.join(GH_PROBE[2:])] * 5 + ['runpane repos list --json']))


class Page(unittest.TestCase):
    def setUp(self):
        self.page = ''
        if os.path.isfile(PAGE):
            with open(PAGE) as f:
                self.page = f.read()
        files = {c['host']: name for name, c in CONFIGS.items()}
        self.row_names = []
        self.rows = {}
        for line in self.page.splitlines():
            cells = [c.strip() for c in line.strip().strip('|').split('|')] if line.startswith('|') else []
            if cells and cells[0].strip('`*') in files:
                self.row_names.append(files[cells[0].strip('`*')])
                self.rows[files[cells[0].strip('`*')]] = cells
        self.code = '\n'.join(re.findall(r'```[a-z]*\n(.*?)```', self.page, re.S))

    def test_the_page_has_exactly_one_row_per_host_in_hosts(self):
        self.assertEqual(sorted(self.row_names), host_names())

    def test_every_row_cites_the_driver_readme_and_the_tools_docs_and_says_whether_it_bills(self):
        self.assertEqual(sorted(self.rows), sorted(CONFIGS))
        for host, cells in self.rows.items():
            with self.subTest(host=host):
                row = ' | '.join(cells)
                self.assertIn('adapters/%s/README.md' % host, row)
                self.assertIn('hosts/%s.json' % host, row)
                self.assertRegex(row, r'\]\(https://[^)]+\)')
                self.assertEqual(cells[-2].strip('*`'), BILLS[host])
                key = CONFIGS[host]['key']
                if key:
                    self.assertIn('`%s`' % key, row)

    def test_the_session_is_written_out_in_order(self):
        steps = ['kernel/live-rig/vps/bootstrap.sh', '../../driver-kit/README.md#the-throwaway-ticket',
                 'curl -fsSL https://claude.ai/install.sh | bash',
                 'gh auth login',
                 'python3 -I kernel/live-rig/heads.py --tickets kernel/live-rig/vps/live-tickets.json '
                 '--hosts kernel/live-rig/vps/hosts --settings ']
        at = [self.page.find(s) for s in steps]
        self.assertNotIn(-1, at, steps)
        self.assertEqual(at, sorted(at))

    def test_pane_doctor_follows_daemon_start_and_registration_of_the_same_checkout(self):
        commands = re.findall(r'(?<!`)`([^`\n]+)`(?!`)', self.page)
        doctors = [command for command in commands if command.startswith('runpane agents doctor ')]
        self.assertEqual(len(doctors), 1)
        start = 'pane --ozone-platform=headless --disable-gpu --daemon-headless'
        register = 'runpane repos add --path "$CHECKOUT"'
        self.assertIn(register, commands)
        self.assertLess(commands.index(register), commands.index(doctors[0]), 'register before running doctor')
        self.assertIn(start, commands)
        self.assertLess(commands.index(start), commands.index(register), 'start Pane before registering')
        self.assertEqual(doctors[0], 'runpane agents doctor --agent claude --repo "$CHECKOUT" --json')

    def test_the_page_blocks_real_runs_until_both_fixes_merge(self):
        intro, section, _ = self.page.partition('## The session, in order')
        self.assertTrue(section)
        warning = re.search(r'No real `heads\.py` run[^\n]*', intro)
        self.assertIsNotNone(warning, 'put the real-run gate above the session steps')
        line = warning.group()
        self.assertIn('with or without `--post`', line)
        self.assertRegex(line, r'until both.*#2689.*#2755.*have merged')

    def test_factory_and_pane_use_the_bootstrapped_tools(self):
        for host, installed in [('factory', '`droid`'), ('pane', 'Pane and `runpane`')]:
            with self.subTest(host=host):
                sign_in = self.rows[host][1]
                self.assertNotRegex(sign_in, r'(?i)\b(?:re)?install\b')
                self.assertIn(f'The bootstrap installed {installed}.', sign_in)

    def test_the_paid_command_is_given_once_with_post_and_no_shell_placeholder(self):
        commands = [line for line in self.code.splitlines() if 'heads.py' in line]
        self.assertEqual(len(commands), 1, commands)
        self.assertIn(' --post', commands[0])
        self.assertNotRegex(self.code, r'[<>]')
        self.assertRegex(self.page, r'[Ww]ithout `--post`[^.]*bill')

    def test_the_page_names_each_hand_check_the_probes_cannot_make(self):
        self.assertIn('`Record authors`', self.page)
        self.assertIn('claude auth status', self.page)
        self.assertRegex(self.page, r'--allow-cost[^.]*only[^.]*(checked|signed in)')

    def test_the_status_column_names_the_no_prompt_github_probe(self):
        table = self.page.partition('## One row per host')[2]
        legend = table.partition('| Host |')[0]
        self.assertTrue('The GitHub probe is `' + ' '.join(GH_PROBE) + '`' in legend)
        for host, cells in self.rows.items():
            with self.subTest(host=host):
                self.assertIn('the GitHub probe', cells[3])
                self.assertNotIn('claude auth status', cells[3])

    def test_the_page_holds_names_never_values(self):
        self.assertTrue(self.page, 'no sign-in page')
        kit = load('kit', KIT)
        self.assertIsNone(kit.SHAPES.search(self.page))
        for key in ('FACTORY_API_KEY', 'CONDUCTOR_API_KEY', 'CURSOR_API_KEY'):
            self.assertIn('`%s`' % key, self.page)
            self.assertNotRegex(self.page, key + r'\s*[=:]')
        self.assertNotRegex(self.page, r'\b(?:fk|sk|key|crsr)[-_][A-Za-z0-9]{8,}')


if __name__ == '__main__':
    unittest.main()
