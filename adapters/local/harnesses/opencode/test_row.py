#!/usr/bin/env python3
import os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.join(HERE, '..', '..', 'fixtures')
ID = 'ses_0a1b2c3d4e5fSynthetic00'
M = 'example/synthetic-1'
START = 'Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.'
WAKE = 'You were woken: take up example/site#7 again, with the build-ticket skill. Edit your own status note there; ' \
       'post no second one.'
REFUSED = {
    'run --attach, which uses a server someone else started': ['run', '--attach', 'http://localhost:4096', '--format',
                                                               'json', '--model', M, '--', START],
    'run --port': ['run', '--port', '4096', '--format', 'json', '--model', M, '--', START],
    'run --variant, which the row never passes': ['run', '--format', 'json', '--model', M, '--variant', 'high', '--',
                                                  START],
    'a --format other than json': ['run', '--format', 'default', '--model', M, '--', START],
    'a --format the CLI does not know': ['run', '--format', 'yaml', '--model', M, '--', START],
    'a start with no --model': ['run', '--format', 'json', '--', START],
    'a start with no prompt': ['run', '--format', 'json', '--model', M, '--'],
    'a prompt not after --': ['run', '--format', 'json', '--model', M, START],
    'a second prompt word': ['run', '--format', 'json', '--model', M, '--', START, 'more'],
    'an unknown flag': ['run', '--format', 'json', '--model', M, '--yes', '--', START],
    'the serve command': ['serve', '--port', '4096'],
    'no run subcommand': ['--format', 'json', '--model', M, '--', START],
    'a wake with no session id': ['run', '--session', '--format', 'json', '--model', M, '--', WAKE],
    'a session id that starts with a dash': ['run', '--session', '-x', '--format', 'json', '--model', M, '--', WAKE],
    '--continue instead of the session id': ['run', '--continue', '--format', 'json', '--model', M, '--', WAKE],
    'a wake prompt on a start line': ['run', '--format', 'json', '--model', M, '--', WAKE],
    'a start prompt on a wake line': ['run', '--session', ID, '--format', 'json', '--model', M, '--', START],
}
failures = []


def check(what, ok):
    print('%s opencode row: %s' % ('pass' if ok else 'fail', what))
    if not ok:
        failures.append(what)


env = dict(os.environ, FAKE_CLI_LIB=LIB)
for what, argv in sorted(REFUSED.items()):
    p = subprocess.run([sys.executable, FAKE] + argv, env=env, capture_output=True, text=True, timeout=30)
    check('the fake exits 2 on ' + what, p.returncode == 2)
ACCEPTED = {
    'the row\'s start line': ['run', '--format', 'json', '--model', M, '--', START],
    'the row\'s start line with --auto': ['run', '--format', 'json', '--model', M, '--auto', '--', START],
    'the row\'s wake line': ['run', '--session', ID, '--format', 'json', '--model', M, '--', WAKE],
}
with tempfile.TemporaryDirectory(prefix='opencode-row-') as folder:
    record = dict(env, FAKE_CLI_RECORD=os.path.join(folder, 'rec'), FAKE_CLI_RECORD_ONLY='1')
    for what, argv in sorted(ACCEPTED.items()):
        p = subprocess.run([sys.executable, FAKE] + argv, env=record, capture_output=True, text=True, timeout=30)
        check('the fake takes ' + what, p.returncode == 0)
p = subprocess.run([sys.executable, FAKE, '--help'], env=env, capture_output=True, text=True, timeout=30)
check('the fake\'s --help names only the two run forms', p.returncode == 0 and p.stdout.count('opencode run ') == 2)
sys.exit(1 if failures else 0)
