#!/usr/bin/env python3
import json, os, re, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.abspath(os.path.join(HERE, '..', '..', 'fixtures'))
with open(os.path.join(HERE, 'row.json')) as f:
    PATTERN = json.load(f)['session']['pattern']
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
PRINTED = '00000000-0000-4000-8000-'
START_PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.'
WAKE_PROMPT = ('You were woken: take up example/site#7 again, with the build-ticket skill. '
               'Edit your own status note there; post no second one.')
SID = PRINTED + '0123456789ab'
START = ['chat', '--v3', '--no-interactive', '--model', 'synthetic-1', '--trust-all-tools', START_PROMPT]
WAKE = ['chat', '--v3', '--no-interactive', '--resume-id', SID, '--model', 'synthetic-1', '--trust-all-tools',
        WAKE_PROMPT]
REFUSED = {
    'a login flag and its value': START + ['--api-key', 'synthetic-login-value'],
    'a login flag with the value joined': ['--api-key=synthetic-login-value'] + START,
    'the login variable as an argument': START + ['KIRO_API_KEY=synthetic-login-value'],
    'an effort flag': START + ['--effort', 'high'],
    'no headless flag': [a for a in START if a != '--no-interactive'],
    'interactive chat': ['chat', START_PROMPT],
    'resume the newest session': START[:3] + ['--resume', '--model', 'synthetic-1', '--trust-all-tools', WAKE_PROMPT],
    'a cloud run': START[:3] + ['--cloud'] + START[3:],
    'trust-tools in place of trust-all-tools': START[:5] + ['--trust-tools=read_file', START_PROMPT],
    'a prompt that is a flag': START[:6] + ['--api-key'],
    'a wake prompt on a start': START[:6] + [WAKE_PROMPT],
    'a start prompt on a wake': WAKE[:8] + [START_PROMPT],
    'a resume id that is not a full UUID': WAKE[:4] + ['abc123-def456'] + WAKE[5:],
    'resume without a session': ['chat', '--v3', '--no-interactive', '--resume-id', '--model', 'synthetic-1',
                                 '--trust-all-tools', WAKE_PROMPT],
    'nothing': [],
}


QUOTED = {
    "the command reference's example": 'kiro-cli chat --resume-id abc123-def456',
    'a backticked full UUID': 'Resume with `kiro-cli chat --resume-id f2946a26-3735-4b08-8d05-c928010302d5` later',
    'the placeholder': 'kiro-cli chat --resume-id <SESSION_ID>',
}


def run(args, **extra):
    env = {'PATH': os.environ.get('PATH', ''), 'FAKE_CLI_LIB': LIB, 'PYTHONDONTWRITEBYTECODE': '1'}
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE] + args, env=env, capture_output=True, text=True, timeout=30)


def allows(bad):
    with tempfile.TemporaryDirectory() as folder:
        record = os.path.join(folder, 'calls')
        started = run(START, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
        if started.returncode != 0 or 'kiro-cli chat --resume-id ' + PRINTED not in started.stdout:
            bad.append('a headless start exited %d and printed %r' % (started.returncode, started.stdout))
        else:
            sid = started.stdout.strip().rpartition(' ')[2]
            woken = run(WAKE[:4] + [sid] + WAKE[5:], FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
            if woken.returncode != 0:
                bad.append('a resume of the same session exited %d' % woken.returncode)
            else:
                try:
                    rows = [json.loads(line) for line in open(record) if line.strip()]
                except ValueError:
                    rows = []
                if len(rows) != 2 or not re.fullmatch(UUID, sid) or not \
                        rows[0].get('session') == rows[1].get('session') == 'fake-' + sid[len(PRINTED):]:
                    bad.append('the resume did not keep the session the start printed')
        signed = run(START, FAKE_CLI_SIGNED_OUT='1', FAKE_CLI_RECORD=os.path.join(folder, 'absent'))
        if signed.returncode != 1 or 'Not logged in' not in signed.stdout or 'resume-id' in signed.stdout or \
                os.path.exists(os.path.join(folder, 'absent')):
            bad.append('a signed-out start did not print Not logged in and exit 1 before a session')


def read_session(output):
    for line in output.splitlines():
        found = re.search(PATTERN, line)
        if found:
            return found.group(1)
    return None


def announcement(bad):
    for why, line in QUOTED.items():
        with tempfile.TemporaryDirectory() as folder:
            got = run(START, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=os.path.join(folder, 'calls'),
                      FAKE_CLI_PRELUDE=line)
            printed = got.stdout.strip().rpartition(' ')[2]
            if got.returncode or read_session(got.stdout) != printed or not re.fullmatch(UUID, printed):
                bad.append('with %s before the notice, the row read %r, not the full UUID the CLI printed'
                           % (why, read_session(got.stdout)))


def main():
    bad = []
    with tempfile.TemporaryDirectory() as folder:
        record = os.path.join(folder, 'calls')
        for why, argv in REFUSED.items():
            got = run(argv, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
            if got.returncode != 2:
                bad.append('%s exited %d, not 2' % (why, got.returncode))
    helped = run(['--help'])
    if helped.returncode or 'https://kiro.dev/docs/cli/headless/' not in helped.stdout:
        bad.append('--help did not name the headless reference')
    allows(bad)
    announcement(bad)
    for line in bad:
        print('fail: ' + line)
    print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
