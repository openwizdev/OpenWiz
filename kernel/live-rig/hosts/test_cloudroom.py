#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', '..')
COPIED = ['kernel/live-rig/rig.py', 'kernel/driver-kit/kit.py', 'kernel/live-rig/hosts/cloudroom.json']
AGENT_CLIS = ['claude', 'codex', 'cursor-agent', 'agent', 'cursor', 'pi', 'opencode', 'copilot', 'goose', 'gemini',
              'kimi', 'qwen', 'cline', 'kilo', 'kilocode', 'crush', 'vibe', 'auggie', 'kiro-cli', 'junie', 'amp', 'agy',
              'oz', 'sculpt', 'hermes', 'acpx', 'droid', 'boat', 'room-cli', 'runpane', 'pane', 'openhands', 'devin',
              'warp', 'grok', 'codespaces', 'conductor']
ROOM_STATUS = ['room-cli', 'status']
GH_STATUS = ['env', 'GH_TELEMETRY=0', 'gh', 'config', 'get', '-h', 'github.com', 'user']
STATUS = {'room-cli': ' '.join(ROOM_STATUS), 'gh': ' '.join(GH_STATUS[1:])}
RUNS = [('claude', 'claude-opus-5-5')]
FAKE = '''#!/bin/sh
actual="%s$*"
printf '%%s\\n' "$actual" >> "$FAKE_LOG"
if [ "$actual" = "%s" ]; then exit %d; fi
echo "%s: refused, the Cloudroom host tests answer only its status command" >&2
exit 3
'''


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=Example', '-c', 'user.email=example@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null'] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class CloudroomHost(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.checkout = os.path.join(self.folder, 'checkout')
        for path in COPIED:
            src, dst = os.path.join(ROOT, path), os.path.join(self.checkout, path)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(src):
                shutil.copy2(src, dst)
        git(self.checkout, 'init', '-q')
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'fixture checkout')
        self.head = git(self.checkout, 'rev-parse', 'HEAD')
        self.settings = os.path.join(self.folder, 'settings.json')
        with open(self.settings, 'w') as f:
            json.dump({'repo': 'example/cloudroom-throwaway', 'ticket': 7}, f)
        self.out = os.path.join(self.folder, 'out')
        self.log = os.path.join(self.folder, 'fake.log')
        self.stubs, self.fakes, tools = (os.path.join(self.folder, d) for d in ('stubs', 'fakes', 'tools'))
        for d in (self.stubs, self.fakes, tools):
            os.mkdir(d)
        for name in ('env', 'git'):
            os.symlink(shutil.which(name), os.path.join(tools, name))
        for name in AGENT_CLIS:
            if name in STATUS:
                continue
            with open(os.path.join(self.stubs, name), 'w') as f:
                f.write('#!/bin/sh\necho "%s: refused, the Cloudroom host tests never start an agent CLI" >&2\n'
                        'exit 1\n' % name)
            os.chmod(os.path.join(self.stubs, name), 0o700)
        self.path = os.pathsep.join([self.stubs, self.fakes, tools])

    def rig(self, why, *, signed_out=None, missing=None, expected_probes=None):
        if signed_out is not None:
            path = os.path.join(self.checkout, 'kernel', 'live-rig', 'hosts', 'cloudroom.json')
            with open(path) as f:
                config = json.load(f)
            config['cost'] = 'none'
            with open(path, 'w') as f:
                json.dump(config, f)
            git(self.checkout, 'commit', '-qam', 'allow fixture-only probes')
            self.head = git(self.checkout, 'rev-parse', 'HEAD')
        for name, command in STATUS.items():
            if name == missing:
                continue
            prefix = 'GH_TELEMETRY=$GH_TELEMETRY gh ' if name == 'gh' else 'room-cli '
            with open(os.path.join(self.fakes, name), 'w') as f:
                f.write(FAKE % (prefix, command, 1 if name == signed_out else 0, name))
            os.chmod(os.path.join(self.fakes, name), 0o700)
        for name in AGENT_CLIS + ['gh']:
            want = None if name == missing else os.path.join(self.fakes if name in STATUS else self.stubs, name)
            self.assertEqual(shutil.which(name, path=self.path), want, name)
        env = dict(os.environ, PATH=self.path, HOME=self.folder, FAKE_LOG=self.log, GH_TELEMETRY='1')
        p = subprocess.run([sys.executable, '-I', os.path.join(self.checkout, 'kernel', 'live-rig', 'rig.py'),
                            '--hosts', os.path.join(self.checkout, 'kernel', 'live-rig', 'hosts'),
                            '--settings', self.settings, '--out', self.out, '--host', 'Cloudroom'],
                           env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        if expected_probes is not None:
            probes = []
            if os.path.exists(self.log):
                with open(self.log) as f:
                    probes = f.read().splitlines()
            self.assertEqual(probes, expected_probes)
        self.assertEqual((p.returncode, p.stdout.splitlines()),
                         (0, ['skipped Cloudroom %s: %s' % (h, why) for h, _ in RUNS]), p.stderr)
        days = os.listdir(self.out)
        days.remove('rig.lock')
        self.assertEqual(len(days), 1)
        self.assertEqual(sorted(os.listdir(os.path.join(self.out, days[0]))),
                         sorted('Cloudroom-%s-%s.json' % run for run in RUNS))
        for harness, model in RUNS:
            with open(os.path.join(self.out, days[0], 'Cloudroom-%s-%s.json' % (harness, model))) as f:
                record = json.load(f)
            seconds = record.pop('seconds')
            self.assertTrue(type(seconds) is int and 0 <= seconds < 60, seconds)
            self.assertEqual(record, {
                'host': 'Cloudroom', 'harness': harness, 'model': model, 'date': days[0], 'driver_commit': self.head,
                'kit_commit': self.head, 'outcome': 'skipped', 'skipped': why, 'kit_exit': None,
                'stdout': None})

    def test_the_config_checks_only_the_cited_read_only_status_commands(self):
        self.assertTrue(os.path.isfile(os.path.join(HERE, 'cloudroom.json')),
                        'kernel/live-rig/hosts/cloudroom.json is missing')
        with open(os.path.join(HERE, 'cloudroom.json')) as f:
            config = json.load(f)
        self.assertEqual((config['host'], config['driver'], config['needs'], config['cost'], config['wait']),
                         ('Cloudroom', 'adapters/cloudroom/driver', ['room-cli', 'gh'], 'unknown', 900))
        self.assertEqual(config['signed_in'], [ROOM_STATUS, GH_STATUS])
        self.assertEqual([(r['harness'], r['model']) for r in config['runs']], RUNS)

    def test_unknown_cost_skips_the_kit(self):
        self.rig('cost')

    def test_room_cli_signed_out_stops_before_gh(self):
        self.rig('not signed in: room-cli', signed_out='room-cli', expected_probes=[STATUS['room-cli']])

    def test_gh_signed_out_runs_with_telemetry_disabled(self):
        self.rig('not signed in: gh', signed_out='gh', expected_probes=[STATUS['room-cli'], STATUS['gh']])

    def test_room_cli_missing_is_skipped_and_runs_no_status_command(self):
        self.rig('not installed: room-cli', missing='room-cli', expected_probes=[])

    def test_gh_missing_is_skipped_and_runs_no_status_command(self):
        self.rig('not installed: gh', missing='gh', expected_probes=[])


if __name__ == '__main__':
    unittest.main(verbosity=2)
