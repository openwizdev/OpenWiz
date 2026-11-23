#!/usr/bin/env python3
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

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.join(HERE, '..', '..', '..'))
HOSTS = os.path.join(HERE, 'hosts')
PAGE = os.path.join(HERE, 'SIGN-IN.md')
RIG = os.path.join(ROOT, 'kernel', 'live-rig', 'rig.py')
KIT = os.path.join(ROOT, 'kernel', 'driver-kit', 'kit.py')
# SAFETY: refusing stubs first on PATH for every agent CLI, except a fake a test wires on purpose, so a config or
# fixture mistake can never start a real one. No real status or sign-in command is ever on a test's PATH.
AGENT_CLIS = ['claude', 'codex', 'cursor-agent', 'agent', 'pi', 'opencode', 'copilot', 'goose', 'gemini', 'kimi',
              'qwen', 'cline', 'kilo', 'crush', 'vibe', 'auggie', 'kiro-cli', 'junie', 'amp', 'agy', 'oz', 'sculpt',
              'hermes', 'acpx', 'droid']
SECRET = 'fk-' + 'Synthetic0Vps0Value' * 2
CONFIGS = {
    'hermes': {'host': 'Hermes', 'driver': 'adapters/hermes/driver', 'tool': 'hermes', 'key': None, 'harness': 'claude'},
    'pane': {'host': 'Pane', 'driver': 'adapters/pane/driver', 'tool': 'runpane', 'key': None, 'harness': 'claude'},
    'factory': {'host': 'Factory', 'driver': 'adapters/factory/driver', 'tool': 'droid', 'key': 'FACTORY_API_KEY', 'harness': 'droid'},
    'conductor': {'host': 'Conductor', 'driver': 'adapters/conductor/driver', 'tool': 'curl', 'key': 'CONDUCTOR_API_KEY',
                  'harness': 'claude'},
    'cursor': {'host': 'Cursor', 'driver': 'adapters/cursor/driver', 'tool': 'curl', 'key': 'CURSOR_API_KEY', 'harness': 'cursor'},
}
GH_PROBE = ['gh', 'auth', 'status', '--hostname', 'github.com', '--active', '--no-refresh']
BILLS = {'hermes': 'unknown', 'pane': 'unknown', 'factory': 'unknown', 'conductor': 'unknown', 'cursor': 'unknown'}
SKIPS = {
    'hermes': {'tool missing': 'not installed: hermes', 'gh missing': 'not installed: gh', 'tool signed out': 'cost',
               'key name unset': 'cost', 'gh signed out': 'not signed in: gh', 'signed in': 'cost'},
    'pane': {'tool missing': 'not installed: runpane', 'gh missing': 'not installed: gh',
             'tool signed out': 'not signed in: runpane', 'key name unset': 'cost', 'gh signed out': 'not signed in: gh',
             'signed in': 'cost'},
    'factory': {'tool missing': 'not installed: droid', 'gh missing': 'not installed: gh', 'tool signed out': 'cost',
                'key name unset': 'not signed in: python3', 'gh signed out': 'not signed in: gh', 'signed in': 'cost'},
    'conductor': {'tool missing': 'not installed: curl', 'gh missing': 'not installed: gh', 'tool signed out': 'cost',
                  'key name unset': 'not signed in: python3', 'gh signed out': 'not signed in: gh', 'signed in': 'cost'},
    'cursor': {'tool missing': 'not installed: curl', 'gh missing': 'not installed: gh', 'tool signed out': 'cost',
               'key name unset': 'not signed in: python3', 'gh signed out': 'not signed in: gh', 'signed in': 'cost'},
}


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
                self.assertEqual([c for c in config['signed_in'] if c[0] == 'gh'], [GH_PROBE])


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
            only = ' '.join(GH_PROBE[1:]) if name == 'gh' else ''
            with open(os.path.join(fakes, name), 'w') as f:
                f.write('#!/bin/sh\necho "%s $*" >> "%s"\n' % (name, self.log))
                if only:
                    f.write('[ "$*" = "%s" ] || { echo "%s refused" >> "%s"; exit 2; }\n' % (only, name, self.log))
                f.write('exit %d\n' % (1 if out else 0))
            os.chmod(os.path.join(fakes, name), 0o755)
        for name, real in (('git', shutil.which('git')), ('python3', sys.executable)):
            os.symlink(real, os.path.join(fakes, name))
        return stubs + os.pathsep + fakes

    def rig(self, host, situation):
        want = CONFIGS[host]
        env = {'PATH': self.path_of_stubs_then_fakes(situation, want['tool']), 'HOME': self.folder, 'LANG': 'C.UTF-8'}
        for key in ('FACTORY_API_KEY', 'CONDUCTOR_API_KEY', 'CURSOR_API_KEY'):
            if situation != 'key name unset':
                env[key] = SECRET
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
        for host, situations in SKIPS.items():
            for situation, why in situations.items():
                with self.subTest(host=host, situation=situation):
                    p, records = self.rig(host, situation)
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual(p.stdout, 'skipped %s %s: %s\n' % (CONFIGS[host]['host'], CONFIGS[host]['harness'],
                                                                         why))
                    self.assertEqual([(r['outcome'], r['skipped'], r['kit_exit']) for r in records],
                                     [('skipped', why, None)])
                    for text in (p.stdout, p.stderr, json.dumps(records)):
                        self.assertNotIn(SECRET, text)

    def test_status_checks_call_only_read_only_status_commands(self):
        for host in SKIPS:
            self.rig(host, 'signed in')
        calls = []
        if os.path.isfile(self.log):
            with open(self.log) as f:
                calls = f.read().splitlines()
        self.assertEqual(sorted(calls), sorted([' '.join(GH_PROBE)] * 5 + ['runpane repos list --json']))


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
                 'curl -fsSL https://claude.ai/install.sh | bash', 'runpane agents doctor --agent claude',
                 'gh auth login',
                 'python3 -I kernel/live-rig/heads.py --tickets kernel/live-rig/vps/live-tickets.json '
                 '--hosts kernel/live-rig/vps/hosts --settings ']
        at = [self.page.find(s) for s in steps]
        self.assertNotIn(-1, at, steps)
        self.assertEqual(at, sorted(at))

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
