#!/usr/bin/env python3
import contextlib, fcntl, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SPEC = importlib.util.spec_from_file_location('live_check', os.path.join(HERE, 'live_check.py'))
lc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lc)

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
d, a = os.environ['FAKE_GH'], sys.argv[1:]
state = json.load(open(os.path.join(d, 'gh.json')))
with open(os.path.join(d, 'calls.jsonl'), 'a') as f:
    f.write(json.dumps(a) + '\n')
if a[:2] == ['api', '--paginate']:
    print('\n'.join(state['branches']))
elif a[:2] == ['pr', 'list']:
    print(json.dumps(state['prs']))
elif a[:2] == ['issue', 'comment']:
    with open(os.path.join(d, 'posted.jsonl'), 'a') as f:
        f.write(json.dumps(open(a[a.index('--body-file') + 1]).read()) + '\n')
    print('https://github.com/example/site/issues/%s#issuecomment-1' % a[2])
elif a[:2] != ['pr', 'close'] and a[:3] != ['api', '-X', 'DELETE']:
    sys.exit(3)
'''

FAKE_KIT = r'''import json, os, sys
d = os.environ['FAKE_GH']
lines = open(os.path.join(d, 'kit.txt')).read().splitlines()
for line in lines:
    print(line, flush=True)
opens = os.path.join(d, 'opens.json')
if os.path.exists(opens):
    state, new = json.load(open(os.path.join(d, 'gh.json'))), json.load(open(opens))
    state['branches'] += new['branches']
    state['prs'] += new['prs']
    json.dump(state, open(os.path.join(d, 'gh.json'), 'w'))
    os.remove(opens)
sys.exit(1 if any(x.startswith('fail ') for x in lines) else 0)
'''

FAKE_FILES = {
    'adapters/fake/driver': '#!/bin/sh\nexit 0\n',
    'adapters/fake/test_driver.py': 'import sys\nprint("Ran 3 tests in 0.010s\\n\\nOK", file=sys.stderr)\n',
    'kernel/driver-kit/kit.py': FAKE_KIT,
    'tools/privacy-check/check.py': 'import sys\nsys.exit(1 if "REFUSE-ME" in open(sys.argv[-1]).read() else 0)\n',
}
PASS_ALL = ['pass version: v1', 'pass start: the run posted builder status note 11', 'pass wake: edited note 11',
            'pass stop: the run ended', 'pass token: no login']


def git(*args, cwd=None):
    subprocess.run(['git', '-c', 'user.name=example', '-c', 'user.email=1+example@users.noreply.github.com',
                    '-c', 'init.defaultBranch=main'] + list(args), cwd=cwd, check=True, capture_output=True)


class Logic(unittest.TestCase):
    def test_each_check_gets_its_time_and_its_offset(self):
        found = lc.checks([(0.5, 'pass version: v1'), (2.0, 'fail start: no session for run-0123456789ab'),
                           (2.0, 'fail wake: not run: start failed'), (9.0, 'noise')])
        self.assertEqual(found['start'], {'verdict': 'fail', 'what': 'no session for run-0123456789ab', 'at': 2.0,
                                          'took': 1.5})
        self.assertEqual(found['wake']['took'], 0.0)
        self.assertNotIn('stop', found)

    def test_the_signature_ignores_run_ids_note_numbers_and_pids(self):
        def result(what):
            return {'offline': {'verdict': 'pass'}, 'kit': {'exit': 1, 'timed_out': False, 'stderr': ''},
                    'checks': {'start': {'verdict': 'fail', 'what': what}}}
        one = lc.signature(result('run run-0123456789ab: note 4, process 10, 11'))
        self.assertEqual(one, lc.signature(result('run run-ba9876543210: note 9, process 77')))
        self.assertNotEqual(one, lc.signature(result('another reason')))
        self.assertEqual(one['version'], 'missing')

    def test_it_posts_first_on_change_and_once_a_day(self):
        sig, now = {'start': 'pass'}, 100000.0
        self.assertEqual(lc.why_post(sig, {}, now), 'first run')
        self.assertIn('changed', lc.why_post(sig, {'signature': {'start': 'fail: x'}, 'posted_at': now}, now))
        self.assertIsNone(lc.why_post(sig, {'signature': sig, 'posted_at': now - 6 * 3600}, now))
        self.assertIn('daily', lc.why_post(sig, {'signature': sig, 'posted_at': now - 23 * 3600}, now))

    def test_only_new_branches_and_pull_requests_tied_to_the_ticket_are_strays(self):
        pr = lambda n, head, body='': {'number': n, 'headRefName': head, 'title': 't', 'body': body}
        before = ({'main', 'builder/7-old'}, {1: pr(1, 'builder/7-old')})
        after = ({'main', 'builder/7-old', 'builder/7-new', 'agent-work', 'other-70', 'x-7'},
                 {1: pr(1, 'builder/7-old'), 2: pr(2, 'agent-work', 'Closes #7'), 3: pr(3, 'other-70', 'see #70')})
        prs, branches = lc.strays(before, after, 7)
        self.assertEqual([p['number'] for p in prs], [2])
        self.assertEqual(branches, ['agent-work', 'builder/7-new', 'x-7'])

    def test_the_receipt_quotes_failures_exactly_and_hides_the_home_folder(self):
        lines = [(0.4, 'pass version: v1'), (3.0, 'fail start: hermes did not report a session for run-0123456789ab'),
                 (3.0, 'fail wake: not run: start failed'), (3.0, 'fail stop: not run: start failed'),
                 (3.1, 'pass token: no login')]
        r = {'at': 0, 'took': 9.0, 'head': 'a' * 40, 'driver_commit': 'b' * 40 + ' 2026-01-01 Fix it',
             'versions': ['Fake Host v1'], 'cleanup': [], 'checks': lc.checks(lines),
             'offline': {'verdict': 'pass', 'summary': 'Ran 3 tests in 0.010s, OK', 'took': 1.0, 'tail': ''},
             'kit': {'exit': 1, 'lines': lines, 'took': 3.2, 'timed_out': False,
                     'stderr': lc.redact(os.path.expanduser('~/x') + ' note')}}
        cfg = lc.load_config_dict({'driver': 'fake', 'checkout': '/tmp', 'repo': 'example/site', 'ticket': 7,
                                   'harness': 'fake', 'model': 'm1', 'receipts': 'example/site#1'})
        body = lc.receipt(cfg, r, 'first run', '')
        self.assertIn('2 of 5 checks pass** (failed: start, wake, stop)', body)
        self.assertIn('fail start: hermes did not report a session for run-0123456789ab\n', body)
        self.assertIn('| start | **fail** | 2.6 s | 3.0 s |', body)
        self.assertIn('| wake | **fail** (not run) | 0.0 s | 3.0 s |', body)
        self.assertIn('created no branch or pull request', body)
        self.assertNotIn(os.path.expanduser('~') + '/', body)


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.fake = os.path.join(self.tmp, 'gh')
        bin_dir = os.path.join(self.tmp, 'bin')
        for d in (self.fake, bin_dir):
            os.makedirs(d)
        for name, text in (('gh', FAKE_GH), ('fakehost', '#!/bin/sh\necho "Fake Host v1.0"\n')):
            with open(os.path.join(bin_dir, name), 'w') as f:
                f.write(text)
            os.chmod(os.path.join(bin_dir, name), 0o755)
        origin, work = os.path.join(self.tmp, 'origin.git'), os.path.join(self.tmp, 'work')
        git('init', '--bare', '-q', origin)
        git('clone', '-q', origin, work)
        for path, text in FAKE_FILES.items():
            os.makedirs(os.path.dirname(os.path.join(work, path)), exist_ok=True)
            with open(os.path.join(work, path), 'w') as f:
                f.write(text)
        git('add', '.', cwd=work)
        git('commit', '-q', '-m', 'Fake driver', cwd=work)
        git('push', '-q', 'origin', 'HEAD:main', cwd=work)
        self.checkout = os.path.join(self.tmp, 'checkout')
        git('clone', '-q', origin, self.checkout)
        self.state = os.path.join(self.tmp, 'state')
        self.config = os.path.join(self.tmp, 'box.json')
        with open(self.config, 'w') as f:
            json.dump({'driver': 'fake', 'checkout': self.checkout, 'repo': 'example/site', 'ticket': 7,
                       'harness': 'fake', 'model': 'm1', 'receipts': 'example/site#1', 'tools': ['fakehost'],
                       'state': self.state, 'about': 'synthetic box'}, f)
        self.gh({'branches': ['main'], 'prs': []})
        self.env = mock_env({'PATH': bin_dir + os.pathsep + os.environ.get('PATH', os.defpath),
                             'FAKE_GH': self.fake})
        self.env.__enter__()

    def tearDown(self):
        self.env.__exit__(None, None, None)
        shutil.rmtree(self.tmp)

    def gh(self, state):
        with open(os.path.join(self.fake, 'gh.json'), 'w') as f:
            json.dump(state, f)

    def kit_says(self, lines, opens=None):
        with open(os.path.join(self.fake, 'kit.txt'), 'w') as f:
            f.write('\n'.join(lines) + '\n')
        if opens:
            with open(os.path.join(self.fake, 'opens.json'), 'w') as f:
                json.dump(opens, f)

    def posted(self):
        path = os.path.join(self.fake, 'posted.jsonl')
        return jsonl(path) if os.path.exists(path) else []

    def calls(self):
        return jsonl(os.path.join(self.fake, 'calls.jsonl'))

    def rig(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = lc.main(['--config', self.config] + list(extra))
        return code, out.getvalue()

    def test_it_posts_on_change_or_once_a_day_and_cleans_up_what_the_run_opened(self):
        stray = {'number': 31, 'headRefName': 'builder/7-live', 'title': 'Build #7', 'body': ''}
        other = {'number': 32, 'headRefName': 'elsewhere', 'title': 'Unrelated', 'body': 'see #70'}
        self.kit_says(PASS_ALL, {'branches': ['builder/7-live', 'elsewhere'], 'prs': [stray, other]})
        code, out = self.rig()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.posted()), 1)
        body = self.posted()[0]
        self.assertIn('5 of 5 checks pass', body)
        self.assertIn('Fake Host v1.0; synthetic box', body)
        self.assertIn('closed pull request #31; deleted branch `builder/7-live`', body)
        self.assertIn(['pr', 'close', '31', '--repo', 'example/site', '--comment',
                       'Closed by the live-check rig: a driver kit run opened it on a throwaway ticket.'], self.calls())
        self.assertIn(['api', '-X', 'DELETE', 'repos/example/site/git/refs/heads/builder/7-live'], self.calls())
        self.assertFalse([c for c in self.calls() if '32' in c or any('elsewhere' in x for x in c)])

        code, out = self.rig()
        self.assertEqual((code, len(self.posted())), (0, 1), out)
        self.assertIn('no receipt: unchanged', out)

        self.kit_says(['pass version: v1', 'fail start: no session for run-0123456789ab',
                       'fail wake: not run: start failed', 'fail stop: not run: start failed', 'pass token: no login'])
        code, out = self.rig()
        self.assertEqual((code, len(self.posted())), (1, 2), out)
        self.assertIn('the result changed', self.posted()[1])

        code, out = self.rig()
        self.assertEqual(len(self.posted()), 2, out)
        state_path = os.path.join(self.state, 'state.json')
        state = lc.saved(state_path)
        lc.saved(state_path, dict(state, posted_at=state['posted_at'] - 23 * 3600))
        code, out = self.rig()
        self.assertEqual((code, len(self.posted())), (1, 3), out)
        self.assertIn('daily receipt', self.posted()[2])
        self.assertEqual(len(jsonl(os.path.join(self.state, 'history.jsonl'))), 5)

    def test_a_dry_run_writes_nothing_to_github(self):
        self.kit_says(PASS_ALL, {'branches': ['builder/7-live'], 'prs': []})
        code, out = self.rig('--dry-run')
        self.assertEqual((code, self.posted()), (0, []), out)
        self.assertIn('would delete branch `builder/7-live`', out)
        self.assertFalse([c for c in self.calls() if c[:2] in (['pr', 'close'], ['issue', 'comment']) or
                          c[:3] == ['api', '-X', 'DELETE']])
        self.assertFalse(os.path.exists(os.path.join(self.state, 'state.json')))

    def test_a_refused_receipt_is_not_posted_and_is_retried(self):
        self.kit_says(['fail version: REFUSE-ME'] + PASS_ALL[1:])
        code, out = self.rig()
        self.assertEqual((code, self.posted()), (2, []), out)
        self.assertIn('the privacy check refused the receipt', out)
        self.kit_says(PASS_ALL)
        self.assertEqual(self.rig()[0], 0)
        self.assertEqual(len(self.posted()), 1)

    def test_a_dirty_checkout_is_reported_not_moved(self):
        with open(os.path.join(self.checkout, 'adapters/fake/driver'), 'a') as f:
            f.write('# local edit\n')
        self.kit_says(PASS_ALL)
        code, out = self.rig()
        self.assertEqual(code, 2, out)
        self.assertIn('could not run', self.posted()[0])
        self.assertIn('not a clean git checkout', self.posted()[0])

    def test_a_second_run_waits_for_nothing_while_one_holds_the_lock(self):
        self.kit_says(PASS_ALL)
        os.makedirs(self.state)
        with open(os.path.join(self.state, 'lock'), 'w') as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            code, out = self.rig()
        self.assertEqual((code, self.posted()), (0, []))
        self.assertIn('another run holds the lock', out)


def jsonl(path):
    with open(path) as f:
        return [json.loads(x) for x in f]


@contextlib.contextmanager
def mock_env(values):
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


if __name__ == '__main__':
    unittest.main(verbosity=2)
