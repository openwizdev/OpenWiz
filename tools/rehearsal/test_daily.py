#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'daily.py'
TITLE = 'Daily install check failed'
RUN = 'https://github.com/openwizdev/OpenWiz/actions/runs/99'
REPO = 'openwizdev/OpenWiz'

FAKE = r"""#!/usr/bin/env python3
import json, os, sys
path = os.environ['DAILY_FAKE_GH']
state = json.loads(open(path, encoding='utf-8').read())
argv = sys.argv[1:]
state.setdefault('log', []).append(argv)

def flag(name):
    return argv[argv.index(name) + 1]

if argv[:2] == ['issue', 'list']:
    rows = [{'number': i['number'], 'title': i['title']} for i in state['issues'] if i['state'] == 'open']
    json.dump(rows, sys.stdout)
elif argv[:2] == ['issue', 'comment']:
    state.setdefault('comments', []).append({'number': int(argv[2]), 'body': flag('--body')})
elif argv[:2] == ['issue', 'close']:
    number = int(argv[2])
    for issue in state['issues']:
        if issue['number'] == number:
            issue['state'] = 'closed'
    state.setdefault('closed', []).append({'number': number, 'reason': flag('--reason')})
elif argv[:2] == ['issue', 'create']:
    number = max([i['number'] for i in state['issues']] or [0]) + 1
    state['issues'].append({'number': number, 'title': flag('--title'), 'state': 'open', 'body': flag('--body')})
    state.setdefault('created', []).append(number)
elif argv[:1] == ['api']:
    json.dump({'jobs': state['jobs']}, sys.stdout)
else:
    sys.stderr.write('unexpected gh %s\n' % ' '.join(argv))
    sys.exit(2)
open(path, 'w', encoding='utf-8').write(json.dumps(state))
"""

FAILED = (
    'The daily install check of the latest published release (v0.1.0) failed.\n\n'
    '- `release`: failure\n'
    '- `rehearse x86_64-unknown-linux-gnu`: skipped\n\n'
    'Run: %s\n' % RUN)
PASSED = 'Passed on every target for v0.1.0: %s' % RUN
JOBS = [
    {'name': 'release', 'conclusion': 'failure'},
    {'name': 'rehearse x86_64-unknown-linux-gnu', 'conclusion': 'skipped'},
    {'name': 'track', 'conclusion': 'success'},
    {'name': 'rehearse aarch64-apple-darwin', 'conclusion': 'success'},
]


class DailyIssue(unittest.TestCase):
    def setUp(self):
        self.work = Path(tempfile.mkdtemp(prefix='daily-test-'))
        self.addCleanup(shutil.rmtree, self.work, True)
        fake = self.work / 'gh'
        fake.write_text(FAKE)
        fake.chmod(0o755)
        self.state_path = self.work / 'state.json'
        self.env = os.environ.copy()
        self.env['PATH'] = '%s:%s' % (self.work, self.env.get('PATH', ''))
        self.env['DAILY_FAKE_GH'] = str(self.state_path)

    def given(self, issues):
        self.state_path.write_text(json.dumps({'issues': issues, 'jobs': JOBS, 'log': []}))

    def run_daily(self, release='failure', rehearsal='yes', linux='skipped', macos='skipped', tag='v0.1.0'):
        done = subprocess.run(
            [sys.executable, '-I', str(SCRIPT), '--repo', REPO, '--tag', tag, '--run', RUN,
             '--run-id', '99', '--run-attempt', '1', '--release', release, '--rehearsal', rehearsal,
             '--linux', linux, '--macos', macos],
            capture_output=True, text=True, env=self.env, timeout=30)
        state = json.loads(self.state_path.read_text())
        return done, state

    def test_failure_with_no_issue_opens_one(self):
        self.given([])
        done, state = self.run_daily()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertEqual(state['created'], [1])
        opened = state['issues'][0]
        self.assertEqual(opened['title'], TITLE)
        self.assertEqual(opened['body'], FAILED)
        self.assertEqual(opened['state'], 'open')
        self.assertNotIn('comments', state)

    def test_failure_comments_on_the_existing_issue(self):
        self.given([
            {'number': 9, 'title': TITLE, 'state': 'open'},
            {'number': 8, 'title': 'Daily install check failed yesterday', 'state': 'open'},
            {'number': 7, 'title': TITLE, 'state': 'open'},
        ])
        done, state = self.run_daily()
        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        self.assertNotIn('created', state)
        self.assertEqual(state['comments'], [{'number': 7, 'body': FAILED}])
        self.assertEqual([i['state'] for i in state['issues']], ['open', 'open', 'open'])

    def test_pass_comments_and_closes_every_open_issue(self):
        self.given([
            {'number': 9, 'title': TITLE, 'state': 'open'},
            {'number': 8, 'title': 'Daily install check failed yesterday', 'state': 'open'},
            {'number': 7, 'title': TITLE, 'state': 'open'},
        ])
        done, state = self.run_daily(release='success', rehearsal='yes', linux='success', macos='success')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertNotIn('created', state)
        self.assertEqual(state['comments'], [
            {'number': 7, 'body': PASSED},
            {'number': 9, 'body': PASSED},
        ])
        self.assertEqual(state['closed'], [
            {'number': 7, 'reason': 'completed'},
            {'number': 9, 'reason': 'completed'},
        ])
        self.assertEqual(state['issues'][1]['state'], 'open')
        self.assertNotIn(['api'], [call[:1] for call in state['log']])

    def test_neutral_run_leaves_the_open_issue(self):
        self.given([{'number': 7, 'title': TITLE, 'state': 'open'}])
        done, state = self.run_daily(release='success', rehearsal='no', linux='skipped', macos='skipped')
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertIn('neutral: v0.1.0 has no tools/rehearsal/rehearse.py', done.stdout)
        self.assertNotIn('created', state)
        self.assertNotIn('comments', state)
        self.assertNotIn('closed', state)
        self.assertEqual(state['issues'][0]['state'], 'open')


if __name__ == '__main__':
    unittest.main()
