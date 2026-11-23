#!/usr/bin/env python3
import base64
import datetime
import importlib.machinery
import importlib.util
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..')
FIX = os.path.join(HERE, 'fixtures', 'heads')
REPO, TICKET, LOGIN = 'example/heads-throwaway', 7, 'example-runner'
SECRET = 'gh' + 'p_' + 'Synthetic0Heads0Value' * 2 + '00'
KEYS = ['host', 'harness', 'model', 'date', 'driver_commit', 'kit_commit', 'outcome', 'skipped', 'kit_exit',
        'stdout', 'seconds']
EARLIER = '<!-- openwiz:status v1 -->\nagent: builder\nstate: stopped\nharness: Fake\nmodel: m\n' \
          'skills: build-ticket@0.1.2\nstep: an earlier run\ntime: 2030-01-02T03:04:05Z\n'
LINE = 'launch-fleet: look: live run due at the approved frozen head of #%d: %s (APPROVE 1). Run the kit 5 of 5.'
# SAFETY: no-op stubs first on PATH for every agent CLI, so a fixture mistake can never start a real one.
AGENT_CLIS = ['claude', 'codex', 'cursor-agent', 'agent', 'pi', 'opencode', 'copilot', 'goose', 'gemini', 'kimi',
              'qwen', 'cline', 'kilo', 'crush', 'vibe', 'auggie', 'kiro-cli', 'junie', 'amp', 'agy', 'oz', 'sculpt',
              'hermes', 'acpx', 'droid']
CHECKOUT = ['kernel/live-rig/heads.py', 'kernel/live-rig/rig.py', 'kernel/live-rig/receipt.py', 'kernel/driver-kit/kit.py',
            'kernel/driver-kit/schema.json', 'kernel/records-kit/check.py', 'kernel/records.v1.md']
DRIVER_PR_HEAD = {'adapters/template/driver': os.path.join(ROOT, 'adapters', 'template', 'driver'),
           'adapters/template/schema.json': os.path.join(ROOT, 'adapters', 'template', 'schema.json'),
           'adapters/four/driver': os.path.join(FIX, 'four-driver'),
           'adapters/quoting/driver': os.path.join(FIX, 'quoting-driver')}


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.name=Example', '-c', 'user.email=example@example.invalid',
                           '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null'] + list(args),
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def read(path):
    with open(path) as f:
        return f.read()


class Heads(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.checkout = os.path.join(self.folder, 'checkout')
        for path in CHECKOUT:
            if os.path.exists(os.path.join(ROOT, path)):
                copy(os.path.join(ROOT, path), os.path.join(self.checkout, path))
        copy(os.path.join(FIX, 'listings.json'), os.path.join(self.checkout, 'kernel', 'live-rig', 'listings.json'))
        copy(os.path.join(FIX, 'fleet.md'), os.path.join(self.checkout, 'docs', 'agents', 'fleet.md'))
        self.hosts = os.path.join(self.checkout, 'kernel', 'live-rig', 'vps', 'hosts')
        shutil.copytree(os.path.join(FIX, 'hosts'), self.hosts)
        git(self.checkout, 'init', '-q', '-b', 'main')
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'fixture checkout')
        self.kit_head = git(self.checkout, 'rev-parse', 'HEAD')
        remote = os.path.join(self.folder, 'fake-remote.git')
        git(self.folder, 'init', '-q', '--bare', remote)
        git(remote, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
        git(self.checkout, 'push', '-q', remote, 'main')
        work = os.path.join(self.folder, 'work')
        git(self.folder, 'clone', '-q', remote, work)
        for dst, src in DRIVER_PR_HEAD.items():
            copy(src, os.path.join(work, dst))
        git(work, 'add', '-A')
        git(work, 'commit', '-q', '-m', 'driver PR head')
        self.head = git(work, 'rev-parse', 'HEAD')
        git(work, 'push', '-q', 'origin', 'HEAD:refs/pull/201/head')
        shutil.rmtree(work)
        git(self.checkout, 'remote', 'add', 'origin', remote)
        self.assertNotEqual(subprocess.run(['git', 'cat-file', '-e', self.head], cwd=self.checkout,
                                           stderr=subprocess.DEVNULL).returncode, 0)

        self.settings = os.path.join(self.folder, 'settings.json')
        with open(self.settings, 'w') as f:
            json.dump({'repo': REPO, 'ticket': TICKET}, f)
        self.out = os.path.join(self.folder, 'out')
        self.gh_log = os.path.join(self.folder, 'gh.log')
        self.state = os.path.join(self.folder, 'gh-state')
        os.makedirs(self.state)
        tracker = os.path.join(self.folder, 'tracker.json')
        with open(tracker, 'w') as f:
            json.dump({'record_authors': ['example-bot[bot]'], 'comments': [
                {'id': 1, 'author': 'example-bot[bot]', 'updated_at': '2030-01-02T03:04:05Z', 'body': EARLIER}]}, f)
        self.comments = os.path.join(self.folder, 'comments.json')
        lead = lambda n, body: {'id': n, 'user': {'login': 'example-lead'}, 'body': body}
        with open(self.comments, 'w') as f:
            json.dump({
                '101': [lead(11, LINE % (201, '0' * 40)), lead(12, 'Earlier line above.\n' + LINE % (201, self.head))],
                '102': [lead(21, LINE % (202, self.head))],
                '103': [lead(31, 'launch-fleet: started'),
                        {'id': 32, 'user': {'login': 'someone-else'}, 'body': LINE % (203, self.head)}],
                '104': [lead(41, LINE % (204, self.head))],
                '105': [lead(51, LINE % (205, self.head))],
                '106': [lead(61, LINE % (206, self.head))]}, f)
        stubs = tempfile.mkdtemp(dir=self.folder)
        for name in AGENT_CLIS:
            with open(os.path.join(stubs, name), 'w') as f:
                f.write('#!/bin/sh\necho "%s: refused, the heads tests never start an agent CLI" >&2\nexit 1\n' % name)
            os.chmod(os.path.join(stubs, name), 0o700)
        path = os.pathsep.join([stubs, os.path.join(FIX, 'bin'), os.path.join(ROOT, 'kernel', 'driver-kit', 'fixtures'),
                                os.environ['PATH']])
        self.assertEqual({shutil.which(name, path=path) for name in AGENT_CLIS},
                         {os.path.join(stubs, name) for name in AGENT_CLIS})
        self.assertEqual(shutil.which('gh', path=path), os.path.join(FIX, 'bin', 'gh'))
        self.mark = secrets.token_hex(8)
        env = {k: v for k, v in os.environ.items() if k != 'OPENWIZ_GITHUB_APP_KEY'}
        self.env = dict(env, PATH=path, KIT_TRACKER=tracker, HEADS_TEST=self.mark, HEADS_GH_LOG=self.gh_log,
                        HEADS_GH_STATE=self.state, HEADS_COMMENTS=self.comments, HEADS_KIT_REPO=REPO,
                        HEADS_KIT_TICKET=str(TICKET), HEADS_GH_LOGIN=LOGIN, GH_TOKEN=SECRET,
                        OPENWIZ_TEMPLATE_STATE=os.path.join(self.folder, 'template-state'))

    def tearDown(self):
        for pid in filter(str.isdigit, os.listdir('/proc')):
            try:
                with open('/proc/%s/environ' % pid, 'rb') as f:
                    if ('HEADS_TEST=' + self.mark).encode() in f.read().split(b'\0'):
                        os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass
        shutil.rmtree(self.folder, ignore_errors=True)

    def heads(self, hosts, *extra, env=None, folder=None):
        with open(os.path.join(FIX, 'live-tickets.json')) as f:
            every = json.load(f)
        tickets = os.path.join(self.folder, 'live-tickets.json')
        with open(tickets, 'w') as f:
            json.dump({h: every[h] for h in hosts}, f)
        command = [sys.executable, '-I', os.path.join(self.checkout, 'kernel', 'live-rig', 'heads.py'),
                   '--tickets', tickets, '--hosts', folder or self.hosts, '--settings', self.settings,
                   '--out', self.out] + list(extra)
        p = subprocess.run(command, env=env or self.env, capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout, p.stderr

    def calls(self):
        if not os.path.exists(self.gh_log):
            return []
        return [json.loads(line) for line in read(self.gh_log).splitlines()]

    def writes(self):
        return [c for c in self.calls() if '-X' in c['args']]

    def kit_ran(self):
        return any(c['args'][:2] == ['api', 'graphql'] for c in self.calls())

    def found(self, suffix):
        return sorted(os.path.relpath(os.path.join(d, n), self.out)
                      for d, _, names in os.walk(self.out) for n in names if n.endswith(suffix))

    def day(self):
        days = self.found('.json')
        records = [d for d in days if d.endswith('-fake-harness-Synthetic 1.json')]
        self.assertTrue(records, days)
        return records[0].split(os.sep)[0]

    def expected_comment(self):
        return read(os.path.join(FIX, 'expected-comment.md')).replace('{head}', self.head)

    def expected_receipt(self, day):
        return read(os.path.join(FIX, 'expected-receipt.txt')).replace('{head}', self.head).replace(
            '{kit}', self.kit_head).replace('{date}', day)

    def test_a_ticket_with_no_frozen_head_line_from_a_record_author_is_skipped_and_starts_no_kit(self):
        for run in (1, 2):
            with self.subTest(run=run):
                code, out, err = self.heads(['fixture-nohead'], '--allow-cost', 'fixture-nohead')
                self.assertEqual((code, out), (0, 'skipped fixture-nohead: no frozen head\n'), err)
        reads = [c['args'] for c in self.calls()]
        path = 'repos/openwizdev/OpenWiz/issues/103/comments?per_page=100'
        self.assertEqual(reads[0], ['api', '-i', path])
        self.assertEqual(reads[1][:3] + reads[1][4:], ['api', '-i', '-H', path])
        self.assertTrue(reads[1][3].startswith('If-None-Match: W/"'), reads[1])
        self.assertFalse(self.kit_ran())
        self.assertEqual(self.found('.json'), ['heads-etags.json'])

    def test_a_fetched_commit_that_is_not_the_frozen_head_is_refused_and_runs_no_kit(self):
        mismatch = os.path.join(FIX, 'mismatch')
        env = dict(self.env, PATH=mismatch + os.pathsep + self.env['PATH'], HEADS_REAL_GIT=shutil.which('git'),
                   HEADS_OTHER_SHA=self.kit_head)
        code, out, err = self.heads(['fixture-five'], '--allow-cost', 'fixture-five', env=env)
        self.assertEqual((code, out), (1, 'skipped fixture-five: git fetched %s, not the frozen head %s\n' % (
            self.kit_head[:12], self.head[:12])), err)
        self.assertFalse(self.kit_ran())
        self.assertEqual(self.found('.txt'), [])

    def test_a_host_not_signed_in_is_skipped_and_starts_no_kit(self):
        code, out, err = self.heads(['fixture-signed-out'], '--allow-cost', 'fixture-signed-out')
        self.assertEqual((code, out), (0, 'skipped fixture-signed-out: not signed in: heads-signed-out\n'), err)
        self.assertNotIn('output heads.py discards', out + err)
        self.assertFalse(self.kit_ran())

    def test_a_paid_host_without_its_allow_cost_is_skipped_and_starts_no_kit(self):
        for extra in ([], ['--allow-cost', 'fixture-nohead']):
            with self.subTest(extra=extra):
                code, out, err = self.heads(['fixture-paid', 'fixture-nohead'], *extra)
                self.assertEqual((code, out), (0, 'skipped fixture-paid: cost\nskipped fixture-nohead: no frozen head\n'),
                                 err)
        self.assertFalse(self.kit_ran())

    def test_five_of_five_gives_the_exact_pr_comment_receipt_and_record_and_writes_nothing_to_github(self):
        code, out, err = self.heads(['fixture-five'], '--allow-cost', 'fixture-five')
        self.assertEqual(code, 0, err)
        day = self.day()
        receipt = 'receipts/fixture-five/%s-%s.txt' % (day, self.head[:12])
        self.assertEqual(out, ''.join([
            'ran fixture-five: 5 of 5 at %s\n' % self.head[:12],
            'would post on openwizdev/OpenWiz#201:\n', self.expected_comment(),
            'would add %s to openwizdev/WizMarket:\n' % receipt, self.expected_receipt(day)]))
        receipts = self.found('.txt')
        self.assertEqual(len(receipts), 1, receipts)
        self.assertTrue(receipts[0].endswith(receipt), receipts)
        self.assertEqual(read(os.path.join(self.out, receipts[0])), self.expected_receipt(day))
        text = read(os.path.join(self.out, day, 'fixture-five-fake-harness-Synthetic 1.json'))
        record = json.loads(text)
        self.assertEqual(list(record), KEYS)
        self.assertEqual({k: record[k] for k in KEYS[:9]}, {
            'host': 'fixture-five', 'harness': 'fake-harness', 'model': 'Synthetic 1', 'date': day,
            'driver_commit': self.head, 'kit_commit': self.kit_head, 'outcome': 'ran', 'skipped': None,
            'kit_exit': 0})
        self.assertIn(day, {(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=n)).strftime(
            '%Y-%m-%d') for n in (0, 1)})
        for private in (self.folder, os.path.realpath(self.folder), REPO, 'heads-throwaway', SECRET):
            self.assertNotIn(private, text + out + err)
        self.assertTrue(self.kit_ran())
        self.assertEqual(self.writes(), [])
        self.assertEqual(git(self.checkout, 'status', '--porcelain', '--untracked-files=all'), '')
        self.assertEqual(git(self.checkout, 'worktree', 'list', '--porcelain').count('worktree '), 1)

    def test_four_of_five_gives_a_comment_and_no_receipt(self):
        code, out, err = self.heads(['fixture-four'], '--allow-cost', 'fixture-four')
        self.assertEqual(code, 1, err)
        lines = out.splitlines()
        self.assertEqual(lines[:3], ['ran fixture-four: 4 of 5 at %s' % self.head[:12],
                                     'would post on openwizdev/OpenWiz#202:',
                                     '**FX2L live kit run: 4 of 5 pass**, at head `%s`' % self.head])
        self.assertIn('fail wake: builder status note 2 did not change after the wake', lines)
        self.assertNotIn('would add', out)
        self.assertEqual((self.found('.txt'), self.writes()), ([], []))

    def test_post_reaches_only_the_fake_gh_with_one_comment_per_run_and_one_wizmarket_pull_request(self):
        code, out, err = self.heads(['fixture-five', 'fixture-four'], '--allow-cost', 'fixture-five',
                                    '--allow-cost', 'fixture-four', '--post')
        self.assertEqual(code, 1, err)
        day = self.day()
        self.assertEqual(out.splitlines(), [
            'ran fixture-five: 5 of 5 at %s' % self.head[:12],
            'posted https://github.com/openwizdev/OpenWiz/pull/201#issuecomment-901',
            'ran fixture-four: 4 of 5 at %s' % self.head[:12],
            'posted https://github.com/openwizdev/OpenWiz/pull/202#issuecomment-902',
            'posted https://github.com/openwizdev/WizMarket/pull/41'])
        writes = self.writes()
        self.assertEqual([c['args'][2:4] for c in writes], [
            ['POST', 'repos/openwizdev/OpenWiz/issues/201/comments'],
            ['POST', 'repos/openwizdev/OpenWiz/issues/202/comments'],
            ['POST', 'repos/openwizdev/WizMarket/forks'],
            ['POST', 'repos/%s/WizMarket/git/refs' % LOGIN],
            ['PUT', 'repos/%s/WizMarket/contents/receipts/fixture-five/%s-%s.txt' % (LOGIN, day, self.head[:12])],
            ['POST', 'repos/openwizdev/WizMarket/pulls']])
        sent = [json.loads(c['stdin']) for c in writes]
        self.assertEqual(sent[0], {'body': self.expected_comment()})
        self.assertTrue(sent[1]['body'].startswith('**FX2L live kit run: 4 of 5 pass**, at head `%s`\n' % self.head))
        branch = 'receipts-fixture-five-%s-%s' % (day, self.head[:12])
        self.assertEqual(sent[3], {'ref': 'refs/heads/' + branch, 'sha': 'c' * 40})
        self.assertEqual(base64.b64decode(sent[4].pop('content')).decode(), self.expected_receipt(day))
        self.assertEqual(sent[4]['branch'], branch)
        self.assertEqual((sent[5]['head'], sent[5]['base']), (LOGIN + ':' + branch, 'main'))
        self.assertIn('https://github.com/openwizdev/OpenWiz/pull/201#issuecomment-901', sent[5]['body'])
        for c in self.calls():
            self.assertNotIn(SECRET, json.dumps(c))
            for private in (REPO, 'heads-throwaway', self.folder):
                if c['args'][:2] != ['api', 'graphql']:
                    self.assertNotIn(private, json.dumps(c))

    def test_a_planted_credential_is_refused_before_anything_is_printed_or_posted(self):
        env = dict(self.env, HEADS_PLANTED_TOKEN=self.head)
        code, out, err = self.heads(['fixture-five'], '--allow-cost', 'fixture-five', '--post', env=env)
        self.assertEqual(code, 1, err)
        lines = out.splitlines()
        self.assertEqual(lines[:2], ['ran fixture-five: 5 of 5 at %s' % self.head[:12],
                                     'refused fixture-five: the comment holds a credential, so it is not posted'])
        self.assertFalse([line for line in lines if line.startswith('posted')], out)
        self.assertEqual(self.writes(), [])
        self.assertNotIn(self.head, out + err)

    def test_an_allow_cost_naming_no_listed_host_and_a_bad_tickets_file_exit_2(self):
        self.assertEqual(self.heads(['fixture-paid'], '--allow-cost', 'fixture-typo')[:2], (2, ''))
        with open(os.path.join(FIX, 'live-tickets.json')) as f:
            good = json.load(f)['fixture-paid']
        for bad in (dict(good, extra=1), dict(good, pr='205'), dict(good, listing='Bad_Id'), dict(good, id='')):
            with self.subTest(bad=bad):
                tickets = os.path.join(self.folder, 'bad.json')
                with open(tickets, 'w') as f:
                    json.dump({'fixture-paid': bad}, f)
                p = subprocess.run([sys.executable, '-I', os.path.join(self.checkout, 'kernel', 'live-rig', 'heads.py'),
                                    '--tickets', tickets, '--hosts', self.hosts, '--settings',
                                    self.settings, '--out', self.out], env=self.env, capture_output=True, text=True,
                                   timeout=60)
                self.assertEqual((p.returncode, p.stdout), (2, ''), p.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_frozen_head_naming_another_pr_or_a_host_with_no_config_is_skipped_and_starts_no_kit(self):
        tickets = os.path.join(self.folder, 'other.json')
        with open(tickets, 'w') as f:
            json.dump({'fixture-paid': {'id': 'FX5L', 'ticket': 105, 'pr': 999, 'listing': 'fixture-paid'},
                       'fixture-absent': {'id': 'FX7L', 'ticket': 105, 'pr': 205, 'listing': 'fixture-absent'}}, f)
        p = subprocess.run([sys.executable, '-I', os.path.join(self.checkout, 'kernel', 'live-rig', 'heads.py'),
                            '--tickets', tickets, '--hosts', self.hosts, '--settings', self.settings, '--out', self.out,
                            '--allow-cost', 'fixture-paid'], env=self.env, capture_output=True, text=True, timeout=60)
        self.assertEqual((p.returncode, p.stdout), (0, 'skipped fixture-paid: the frozen head names #205, not the build '
                                                       'PR #999\nskipped fixture-absent: no host config\n'), p.stderr)
        self.assertFalse(self.kit_ran())

    def test_a_kit_line_quoting_a_path_the_repository_or_the_login_is_withheld_from_the_record_and_comment(self):
        code, out, err = self.heads(['fixture-quoting'], '--allow-cost', 'fixture-quoting')
        self.assertEqual(code, 1, err)
        day = self.day()
        record = json.loads(read(os.path.join(self.out, day, 'fixture-quoting-fake-harness-Synthetic 1.json')))
        self.assertEqual(record['stdout'].splitlines()[:2], [
            'pass version: openwiz:records v1, and the schema is driver v1', 'fail start: withheld'])
        self.assertEqual(len(record['stdout'].splitlines()), 5, record['stdout'])
        self.assertIn('```\npass version: openwiz:records v1, and the schema is driver v1\nfail start: withheld\n', out)
        self.assertIn('cannot start %s in ' % REPO, err)
        comment = out.split('```\n', 1)[1]
        self.assertEqual(comment, record['stdout'] + '```\n')
        for private in (self.folder, os.path.realpath(self.folder), REPO, 'heads-throwaway', '/'):
            self.assertNotIn(private, record['stdout'])

    def test_hosts_outside_the_checkout_or_untracked_in_it_exit_2_and_run_nothing(self):
        self.assertEqual(self.heads(['fixture-paid'], folder=os.path.join(FIX, 'hosts'))[:2], (2, ''))
        with open(os.path.join(self.hosts, 'extra.json'), 'w') as f:
            f.write(read(os.path.join(FIX, 'hosts', 'fixture-paid.json')).replace('fixture-paid', 'fixture-extra'))
        git(self.checkout, 'add', '-A')
        git(self.checkout, 'commit', '-q', '-m', 'a tracked extra host')
        ignored = os.path.join(self.checkout, 'ignored')
        os.makedirs(ignored)
        copy(os.path.join(FIX, 'hosts', 'fixture-paid.json'), os.path.join(ignored, 'fixture-paid.json'))
        with open(os.path.join(self.checkout, '.git', 'info', 'exclude'), 'a') as f:
            f.write('ignored/\n')
        self.assertEqual(self.heads(['fixture-paid'], folder=ignored)[:2], (2, ''))
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.heads(['fixture-paid'])[:2], (0, 'skipped fixture-paid: cost\n'))

    def test_the_vps_live_tickets_file_names_the_five_live_checks_their_build_prs_and_listing_ids(self):
        spec = importlib.util.spec_from_loader('heads', importlib.machinery.SourceFileLoader(
            'heads', os.path.join(HERE, 'heads.py')))
        heads = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(heads)
        self.assertEqual(heads.load_tickets(os.path.join(HERE, 'vps', 'live-tickets.json')), {
            'Hermes': {'id': 'DW1L', 'ticket': 1990, 'pr': 2017, 'listing': 'hermes'},
            'Conductor': {'id': 'DW3L', 'ticket': 1993, 'pr': 2020, 'listing': 'conductor'},
            'Cursor': {'id': 'DW4L', 'ticket': 1995, 'pr': 2021, 'listing': 'cursor-cloud-agents'},
            'Factory': {'id': 'DW6L', 'ticket': 1999, 'pr': 2022, 'listing': 'factory'},
            'Pane': {'id': 'DW7L', 'ticket': 2001, 'pr': 2029, 'listing': 'pane'}})


if __name__ == '__main__':
    unittest.main(verbosity=2)
