#!/usr/bin/env python3
import contextlib
import ctypes
import datetime
import errno
import io
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
FAKES = os.path.join(HERE, 'fixtures', 'rig')
REPO, TICKET, LOGIN = 'example/rig-throwaway', 7, 'example-rig-login'
SECRET = 'gh' + 'p_' + 'Synthetic0Rig0Value' * 2 + '00'
KEYS = ['host', 'harness', 'model', 'date', 'driver_commit', 'kit_commit', 'outcome', 'skipped', 'kit_exit',
        'stdout', 'seconds']
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 2',
        'pass wake: the run edited builder status note 2',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
SKIPS = {'fixture-missing': 'not installed: rig-fixture-not-installed',
         'fixture-signed-out': 'not signed in: fake-signed-out',
         'fixture-cost': 'cost'}
EARLIER = '<!-- openwiz:status v1 -->\nagent: builder\nstate: stopped\nharness: Fake\nmodel: m\n' \
          'skills: build-ticket@0.1.2\nstep: an earlier run\ntime: 2030-01-02T03:04:05Z\n'
# SAFETY: no-op stubs first on PATH for every agent CLI, so a fixture mistake can never start a real one.
AGENT_CLIS = ['claude', 'codex', 'cursor-agent', 'agent', 'pi', 'opencode', 'copilot', 'goose', 'gemini', 'kimi',
              'qwen', 'cline', 'kilo', 'crush', 'vibe', 'auggie', 'kiro-cli', 'junie', 'amp', 'agy', 'oz', 'sculpt',
              'hermes', 'acpx', 'droid']
COPIED = ['kernel/live-rig/rig.py', 'kernel/live-rig/fixtures/hosts', 'kernel/driver-kit/kit.py',
          'kernel/driver-kit/schema.json',
          'kernel/driver-kit/fixtures/planted', 'kernel/records-kit/check.py', 'kernel/records.v1.md',
          'adapters/template/driver', 'adapters/template/schema.json']


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=Example', '-c', 'user.email=example@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null'] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Rig(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        PR_SET_CHILD_SUBREAPER = 36
        ctypes.CDLL(None, use_errno=True).prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.checkout = os.path.join(self.folder, 'checkout')
        for path in COPIED:
            src, dst = os.path.join(ROOT, path), os.path.join(self.checkout, path)
            if not os.path.exists(src):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
        for name in ('planted', 'quoting'):
            os.makedirs(os.path.join(self.checkout, 'adapters', name))
            shutil.copy2(os.path.join(FAKES, name + '-driver'), os.path.join(self.checkout, 'adapters', name, 'driver'))
        git(self.checkout, 'init', '-q')
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'fixture checkout')
        self.head = git(self.checkout, 'rev-parse', 'HEAD')
        self.hosts = os.path.join(self.checkout, 'kernel', 'live-rig', 'fixtures', 'hosts')
        self.settings = os.path.join(self.folder, 'settings.json')
        with open(self.settings, 'w') as f:
            json.dump({'repo': REPO, 'ticket': TICKET}, f)
        self.out = os.path.join(self.folder, 'out')
        self.gh_log = os.path.join(self.folder, 'gh.log')
        tracker = os.path.join(self.folder, 'tracker.json')
        with open(tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': [
                {'id': 1, 'author': 'example-bot[bot]', 'updated_at': '2030-01-02T03:04:05Z', 'body': EARLIER}]}, f)
        stubs = tempfile.mkdtemp(dir=self.folder)
        for name in AGENT_CLIS:
            with open(os.path.join(stubs, name), 'w') as f:
                f.write('#!/bin/sh\necho "%s: refused, the rig tests never start an agent CLI" >&2\nexit 1\n' % name)
            os.chmod(os.path.join(stubs, name), 0o700)
        path = os.pathsep.join([stubs, FAKES, os.path.join(ROOT, 'kernel', 'driver-kit', 'fixtures'),
                                os.environ['PATH']])
        self.assertEqual({shutil.which(name, path=path) for name in AGENT_CLIS},
                         {os.path.join(stubs, name) for name in AGENT_CLIS})
        self.env = dict(os.environ, PATH=path, KIT_TRACKER=tracker, RIG_GH_LOG=self.gh_log, RIG_GH_LOGIN=LOGIN,
                        RIG_GH_REPO=REPO, RIG_GH_TICKET=str(TICKET), GH_TOKEN=SECRET, RIG_PLANTED_KEY=SECRET,
                        OPENWIZ_TEMPLATE_STATE=os.path.join(self.folder, 'state'))

    def tearDown(self):
        children = {}
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/stat' % pid) as f:
                    children.setdefault(int(f.read().rpartition(')')[2].split()[1]), []).append(int(pid))
            except (OSError, IndexError, ValueError):
                pass
        todo = list(children.get(os.getpid(), []))
        while todo:
            pid = todo.pop()
            todo += children.get(pid, [])
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def module(self):
        old_path = os.environ['PATH']
        os.environ['PATH'] = self.env['PATH']
        self.addCleanup(os.environ.__setitem__, 'PATH', old_path)
        spec = importlib.util.spec_from_loader('rig', importlib.machinery.SourceFileLoader(
            'rig', os.path.join(self.checkout, 'kernel', 'live-rig', 'rig.py')))
        rig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(rig)
        return rig

    def commit_host(self, name, config):
        with open(os.path.join(self.hosts, name), 'w') as f:
            f.write(config if isinstance(config, str) else json.dumps(config))
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'a host config')

    def command(self, *extra):
        rig = os.path.join(self.checkout, 'kernel', 'live-rig', 'rig.py')
        return [sys.executable, '-I', rig, '--hosts', self.hosts,
                '--settings', self.settings, '--out', self.out] + list(extra)

    def rig(self, *extra):
        p = subprocess.run(self.command(*extra), env=self.env, capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout.splitlines(), p.stderr

    def kit_calls(self):
        if not os.path.exists(self.gh_log):
            return []
        with open(self.gh_log) as f:
            return f.read().splitlines()

    def records(self):
        return sorted(n for _, _, names in os.walk(self.out) for n in names if n.endswith('.json'))

    def record(self, host):
        utc = datetime.datetime.now(datetime.timezone.utc)
        days = {(utc - datetime.timedelta(days=n)).strftime('%Y-%m-%d') for n in (0, 1)}
        found = [d for d in os.listdir(self.out) if os.path.exists(
            os.path.join(self.out, d, '%s-fake-harness-Synthetic 1.json' % host))]
        self.assertEqual(len(found), 1, found)
        with open(os.path.join(self.out, found[0], '%s-fake-harness-Synthetic 1.json' % host)) as f:
            text = f.read()
        record = json.loads(text)
        self.assertEqual(list(record), KEYS)
        self.assertEqual((record['host'], record['harness'], record['model'], record['date']),
                         (host, 'fake-harness', 'Synthetic 1', found[0]))
        self.assertIn(record['date'], days)
        self.assertEqual((record['driver_commit'], record['kit_commit']), (self.head, self.head))
        self.assertIs(type(record['seconds']), int)
        for private in (self.folder, os.path.realpath(self.folder), REPO, 'example-bot', SECRET, 'rig-throwaway',
                        LOGIN):
            self.assertNotIn(private, text)
        return record

    def test_a_signed_in_host_with_free_runs_runs_five_of_five_and_writes_its_record(self):
        code, out, err = self.rig('--host', 'fixture-template')
        self.assertEqual((code, out), (0, ['ran fixture-template fake-harness: 5 of 5']), err)
        record = self.record('fixture-template')
        self.assertEqual({k: record[k] for k in KEYS[6:10]},
                         {'outcome': 'ran', 'skipped': None, 'kit_exit': 0, 'stdout': '\n'.join(PASS) + '\n'})
        self.assertTrue(self.kit_calls())

    def test_a_missing_signed_out_or_possibly_paid_host_is_skipped_and_recorded_and_starts_no_kit(self):
        for host, why in SKIPS.items():
            with self.subTest(host):
                code, out, err = self.rig('--host', host)
                self.assertEqual((code, out), (0, ['skipped %s fake-harness: %s' % (host, why)]), err)
                self.assertNotIn('output the rig discards', err)
                record = self.record(host)
                self.assertEqual({k: record[k] for k in KEYS[6:10]},
                                 {'outcome': 'skipped', 'skipped': why, 'kit_exit': None, 'stdout': None})
                self.assertEqual(self.kit_calls(), [])

    def test_a_dirty_checkout_exits_2_and_runs_nothing(self):
        for dirty in ('adapters/template/schema.json', 'untracked.txt'):
            with self.subTest(dirty):
                with open(os.path.join(self.checkout, dirty), 'a') as f:
                    f.write('\n')
                code, out, err = self.rig('--host', 'fixture-template')
                self.assertEqual((code, out), (2, []), err)
                self.assertIn('rig.py: ', err)
                self.assertEqual((self.kit_calls(), self.records()), ([], []))
                git(self.checkout, 'checkout', '-q', '--', '.')
                git(self.checkout, 'clean', '-qfd')

    def test_a_held_lock_exits_0_and_runs_nothing(self):
        first = subprocess.Popen(self.command('--host', 'fixture-template'), env=self.env, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, text=True)
        end = time.monotonic() + 60
        while not self.kit_calls() and time.monotonic() < end and first.poll() is None:
            time.sleep(0.05)
        self.assertTrue(self.kit_calls(), 'the first run never started its kit')
        code, out, err = self.rig('--host', 'fixture-cost')
        self.assertEqual((code, out, err), (0, [], 'rig.py: another run holds the lock\n'))
        first_out, first_err = first.communicate(timeout=300)
        self.assertEqual((first.returncode, first_out), (0, 'ran fixture-template fake-harness: 5 of 5\n'), first_err)
        self.assertEqual(self.records(), ['fixture-template-fake-harness-Synthetic 1.json'])

    def test_a_planted_drivers_failing_kit_exits_1_with_its_count(self):
        code, out, err = self.rig('--host', 'fixture-planted')
        self.assertEqual((code, out), (1, ['ran fixture-planted fake-harness: 4 of 5']), err)
        record = self.record('fixture-planted')
        self.assertEqual((record['outcome'], record['kit_exit']), ('ran', 1))
        self.assertIn('fail wake: builder status note 2 did not change after the wake', record['stdout'])

    def test_a_kit_line_quoting_the_checkout_or_the_repository_is_withheld_from_the_record_and_shown_on_stderr(self):
        code, out, err = self.rig('--host', 'fixture-quoting')
        self.assertEqual((code, out), (1, ['ran fixture-quoting fake-harness: 2 of 5']), err)
        self.assertEqual(self.record('fixture-quoting')['stdout'].splitlines(),
                         [PASS[0], 'fail start: withheld', 'fail wake: not run: start failed',
                          'fail stop: not run: start failed', PASS[4]])
        self.assertIn('fail start: cannot start %s in %s/adapters/quoting\n' % (REPO, os.path.realpath(
            self.checkout)), err)

    def test_the_record_keeps_only_the_five_check_lines_each_free_of_paths_the_repository_the_login_and_shapes(self):
        rig = self.module()
        settings = {'repo': REPO, 'ticket': TICKET}
        cases = {PASS[0]: PASS[0], 'fail stop: a process still runs': 'fail stop: a process still runs',
                 'fail start: its schema is not kernel/driver-kit/schema.json': 'fail start: withheld',
                 'fail start: no ticket in Example': 'fail start: withheld',
                 'fail start: rig-throwaway has no fleet.md': 'fail start: withheld',
                 'fail wake: posted as %s' % LOGIN: 'fail wake: withheld',
                 'fail token: it sent token=abc123456789': 'fail token: withheld',
                 'kit.py: a line that is no check': None, 'pass other: not one of the five': None}
        for line, kept in cases.items():
            with self.subTest(line):
                self.assertEqual(rig.record_stdout(line + '\n', settings, LOGIN), kept + '\n' if kept else '')
        self.assertEqual(rig.record_stdout(PASS[0] + '\n', settings, None), 'pass version: withheld\n')

    def test_a_line_with_any_path_a_non_ascii_or_other_unusual_character_is_withheld_and_clean_lines_kept(self):
        rig = self.module()
        settings = {'repo': REPO, 'ticket': TICKET}
        for line in ['fail start: cannot open /\u00dcser/x', 'fail start: cannot open /\u00e9t\u00e9',
                     'fail start: cannot open /\u4e2d\u6587', 'fail start: cannot open a/b',
                     'fail start: cannot open \uff0fhome\uff0fsomeone', 'fail start: C:\\Users\\someone',
                     'fail start: ~someone has no state', 'fail start: mailed someone@example.invalid',
                     'fail start: HOME=somewhere', 'fail start: \x1b[31mred', 'fail start: caf\u00e9 is missing',
                     'fail start: the tab\there']:
            with self.subTest(line):
                self.assertEqual(rig.record_stdout(line + '\n', settings, LOGIN), 'fail start: withheld\n')
        self.assertEqual(rig.record_stdout(''.join(p + '\n' for p in PASS), settings, LOGIN),
                         ''.join(p + '\n' for p in PASS))
        for line in ['fail stop: a process the run started still runs after stop',
                     'fail start: no builder status note appeared within 900 seconds',
                     "fail start: the run posted 2 builder notes; it keeps one"]:
            self.assertEqual(rig.record_stdout(line + '\n', settings, LOGIN), line + '\n')

    def test_case_equivalent_host_or_record_names_exit_2_before_any_run(self):
        with open(os.path.join(self.hosts, 'template.json')) as f:
            config = json.load(f)
        for name, bad in (('template.json', dict(config, runs=config['runs'] + [
                              {'harness': 'fake-harness', 'model': 'SYNTHETIC 1'}])),
                          ('upper.json', dict(config, host='Fixture-Template'))):
            with self.subTest(bad):
                self.commit_host(name, bad)
                code, out, err = self.rig('--host', 'fixture-template')
                self.assertEqual((code, out), (2, []), err)
                self.assertIn('rig.py: ', err)
                self.assertEqual((self.kit_calls(), self.records()), ([], []))
            if name == 'upper.json':
                os.remove(os.path.join(self.hosts, name))
            self.commit_host('template.json', config)
            shutil.rmtree(self.out, ignore_errors=True)
            if os.path.exists(self.gh_log):
                os.remove(self.gh_log)

    def test_a_symlinked_host_config_or_hosts_folder_exits_2_and_runs_nothing(self):
        marker = os.path.join(self.folder, 'status-ran')
        with open(os.path.join(self.hosts, 'cost-unknown.json')) as f:
            config = json.load(f)
        outside = os.path.join(self.folder, 'outside.json')
        with open(outside, 'w') as f:
            json.dump(dict(config, host='fixture-linked', signed_in=[['touch', marker]]), f)
        inside = os.path.join(self.checkout, 'kernel', 'live-rig', 'inside.json')
        shutil.copy2(outside, inside)
        hosts_link = os.path.join(self.checkout, 'kernel', 'live-rig', 'hosts-link')
        os.symlink('fixtures/hosts', hosts_link)
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'a linked hosts folder')
        for target in (outside, os.path.relpath(inside, self.hosts)):
            with self.subTest(target):
                link = os.path.join(self.hosts, 'linked.json')
                os.symlink(target, link)
                git(self.checkout, 'add', '-A')
                git(self.checkout, 'commit', '-q', '-m', 'a tracked symlink')
                try:
                    code, out, err = self.rig('--host', 'fixture-linked')
                    self.assertEqual((code, out), (2, []), err)
                    self.assertIn('rig.py: ', err)
                    self.assertFalse(os.path.exists(marker))
                    self.assertEqual((self.kit_calls(), self.records()), ([], []))
                finally:
                    os.remove(link)
                    git(self.checkout, 'commit', '-qam', 'drop it')
                    shutil.rmtree(self.out, ignore_errors=True)
        command = self.command('--host', 'fixture-cost')
        command[command.index('--hosts') + 1] = hosts_link
        p = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (2, ''), p.stderr)
        self.assertIn('rig.py: --hosts', p.stderr)
        self.assertEqual((self.kit_calls(), self.records()), ([], []))

    def test_load_host_and_check_host_are_importable_and_give_the_exact_skip_reasons(self):
        rig = self.module()
        files = {'fixture-template': 'template.json', 'fixture-missing': 'missing.json',
                 'fixture-signed-out': 'signed-out.json', 'fixture-cost': 'cost-unknown.json'}
        for host, why in dict(SKIPS, **{'fixture-template': None}).items():
            with self.subTest(host):
                config = rig.load_host(os.path.join(self.hosts, files[host]))
                self.assertEqual((config['host'], rig.check_host(config)), (host, why))
        self.assertEqual(self.kit_calls(), [])

    def test_every_host_in_one_run_keeps_paths_logins_the_repository_and_planted_secrets_out(self):
        code, out, err = self.rig()
        self.assertEqual(code, 1, err)
        self.assertEqual(sorted(out), sorted(['ran fixture-template fake-harness: 5 of 5',
                                              'ran fixture-planted fake-harness: 4 of 5',
                                              'ran fixture-quoting fake-harness: 2 of 5'] +
                                             ['skipped %s fake-harness: %s' % s for s in SKIPS.items()]))
        for host in ['fixture-template', 'fixture-planted', 'fixture-quoting'] + list(SKIPS):
            self.record(host)
        self.assertNotIn(SECRET, '\n'.join(out) + err)

    def test_an_unknown_host_or_a_bad_host_config_exits_2_and_only_json_files_are_hosts(self):
        self.assertEqual(self.rig('--host', 'fixture-nowhere')[:2], (2, []))
        self.commit_host('test_cost.py', 'not a host config\n')
        self.assertEqual(self.rig('--host', 'fixture-cost')[:2], (0, ['skipped fixture-cost fake-harness: cost']))
        shutil.rmtree(self.out)
        with open(os.path.join(self.hosts, 'cost-unknown.json')) as f:
            config = json.load(f)
        twice = dict(config, runs=config['runs'] * 2)
        for bad in (dict(config, extra=1), dict(config, wait=901), dict(config, driver='../driver'),
                    dict(config, cost='free'), {k: v for k, v in config.items() if k != 'runs'}, twice,
                    dict(config, signed_in=[['fake-signed-in', 'sta\0tus']])):
            with self.subTest(bad):
                self.commit_host('cost-unknown.json', bad)
                self.assertEqual(self.rig('--host', 'fixture-cost')[:2], (2, []))
        self.commit_host('cost-unknown.json', config)
        self.commit_host('clash.json', dict(config, host='fixture-cost-fake', runs=[{'harness': 'harness',
                                                                                    'model': 'Synthetic 1'}]))
        self.assertEqual(self.rig('--host', 'fixture-cost')[:2], (2, []))
        self.assertEqual(self.records(), [])

    def test_hosts_outside_the_checkout_or_untracked_exit_2_and_run_nothing(self):
        outside = os.path.join(self.folder, 'hosts')
        shutil.copytree(self.hosts, outside)
        command = self.command('--host', 'fixture-cost')
        command[command.index('--hosts') + 1] = outside
        p = subprocess.run(command, env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (2, ''), p.stderr)
        self.assertIn('rig.py: --hosts', p.stderr)
        self.assertEqual((self.kit_calls(), self.records()), ([], []))
        shutil.copy2(os.path.join(self.hosts, 'cost-unknown.json'), os.path.join(self.hosts, 'untracked.json'))
        code, out, err = self.rig('--host', 'fixture-cost')
        self.assertEqual((code, out, self.records()), (2, [], []), err)
        self.assertIn('git does not track', err)

    def test_a_lock_error_other_than_another_run_exits_2(self):
        rig = self.module()

        def no_lock(*_):
            raise OSError(errno.ENOLCK, 'No locks available')
        rig.fcntl.flock, err = no_lock, io.StringIO()
        with contextlib.redirect_stderr(err):
            code = rig.main(self.command('--host', 'fixture-cost')[3:])
        self.assertEqual(code, 2, err.getvalue())
        self.assertNotIn('another run holds the lock', err.getvalue())
        self.assertEqual(self.records(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
