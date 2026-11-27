#!/usr/bin/env python3
import importlib.machinery, importlib.util, json, os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.abspath(os.path.join(HERE, '..', '..', 'fixtures'))
DRIVER = os.path.join(HERE, '..', '..', 'driver')
START_PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.'
WAKE_PROMPT = ('You were woken: take up example/site#7 again, with the build-ticket skill. '
               'Edit your own status note there; post no second one.')
SID = 'fake-0123456789ab'
START = ['-p', '--output-format', 'json', '--model', 'synthetic-1', '--force', START_PROMPT]
WAKE = ['-p', '--output-format', 'json', '--resume', SID, '--model', 'synthetic-1', '--force', WAKE_PROMPT]
REFUSED = {
    'a login flag and its value': START + ['--api-key', 'synthetic-login-value'],
    'a login flag with the value joined': ['--api-key=synthetic-login-value'] + START,
    'text output': ['-p', '--output-format', 'text', '--model', 'synthetic-1', '--force', START_PROMPT],
    'no print mode': START[1:],
    'no model': ['-p', '--output-format', 'json', '--force', START_PROMPT],
    'plan mode': START[:5] + ['--mode', 'plan', START_PROMPT],
    'ask mode': START[:5] + ['--mode', 'ask', START_PROMPT],
    'yolo in place of force': START[:5] + ['--yolo', START_PROMPT],
    'an effort flag': START + ['--reasoning-effort', 'high'],
    'a header flag': START + ['--header', 'Name: Value'],
    'a prompt that is a flag': START[:6] + ['--api-key'],
    'a wake prompt on a start': START[:6] + [WAKE_PROMPT],
    'a start prompt on a wake': WAKE[:-1] + [START_PROMPT],
    'resume without a session': ['-p', '--output-format', 'json', '--resume', '--model', 'synthetic-1', '--force',
                                 WAKE_PROMPT],
    'nothing': [],
}
NOT_AUTHENTICATED = 'Not authenticated. Run agent login or set CURSOR_API_KEY.'
SIGNED_OUT = {
    'the sign-in error on its own line': NOT_AUTHENTICATED + '\n',
    'the sign-in error after an Error: prefix': 'Error: ' + NOT_AUTHENTICATED + '\n',
}


def success(text):
    return json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': text, 'session_id': SID})


ACCEPTED = {
    'a success whose answer mentions the error': success('Added a test for the "Not authenticated" error.'),
    'a success whose answer starts with the error': success(NOT_AUTHENTICATED + ' is now tested.'),
}


def run(args, **extra):
    env = {'PATH': os.environ.get('PATH', ''), 'FAKE_CLI_LIB': LIB, 'PYTHONDONTWRITEBYTECODE': '1'}
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE] + args, env=env, capture_output=True, text=True, timeout=30)


def allows(bad):
    with tempfile.TemporaryDirectory() as folder:
        record = os.path.join(folder, 'calls')
        started = run(START, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
        try:
            line = json.loads(started.stdout.strip())
        except ValueError:
            line = {}
        if started.returncode != 0 or not line.get('session_id', '').startswith('fake-'):
            bad.append('a print-mode start exited %d and printed %r' % (started.returncode, started.stdout))
        woken = run(WAKE, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
        if woken.returncode != 0:
            bad.append('a resume of the same session exited %d' % woken.returncode)
        signed = run(START, FAKE_CLI_SIGNED_OUT='1', FAKE_CLI_RECORD=os.path.join(folder, 'absent'))
        if signed.returncode != 1 or 'Not authenticated' not in signed.stdout or 'session_id' in signed.stdout or \
                os.path.exists(os.path.join(folder, 'absent')):
            bad.append('a signed-out start did not print Not authenticated and exit 1 before a session')


def reads_sign_in(bad):
    with open(os.path.join(HERE, 'row.json')) as f:
        row = json.load(f)
    local = importlib.util.module_from_spec(importlib.util.spec_from_loader(
        'openwiz_local_driver', importlib.machinery.SourceFileLoader('openwiz_local_driver', DRIVER)))
    local.__spec__.loader.exec_module(local)
    signed_out = lambda log: bool(local.SIGNED_OUT.search(log) or local.signed_out_by_row(row, log))
    for why, log in SIGNED_OUT.items():
        if not signed_out(log):
            bad.append("the driver's first-turn check did not read %s as signed out" % why)
    for why, line in ACCEPTED.items():
        if signed_out(line + '\n'):
            bad.append("the driver's first-turn check read %s as signed out" % why)


def main():
    bad = []
    with tempfile.TemporaryDirectory() as folder:
        record = os.path.join(folder, 'calls')
        for why, argv in REFUSED.items():
            got = run(argv, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
            if got.returncode != 2:
                bad.append('%s exited %d, not 2' % (why, got.returncode))
    helped = run(['--help'])
    if helped.returncode or 'cursor.com/docs/cli/reference/parameters' not in helped.stdout:
        bad.append('--help did not name the parameters reference')
    allows(bad)
    reads_sign_in(bad)
    for line in bad:
        print('fail: ' + line)
    print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
