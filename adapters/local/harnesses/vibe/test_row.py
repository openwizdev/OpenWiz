#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.abspath(os.path.join(HERE, '..', '..', 'fixtures'))
PROMPT = 'Do the task with the ship skill.'
WAKE = 'You were woken: take up example/open#1 again, with the ship skill.'
SID = 'fake-0123456789ab'
START = ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--trust', '--auto-approve']
REFUSED = {
    'api key flag': ['--api-key', 'synthetic-canary-0000-2918', *START],
    'api key equals': ['--prompt', PROMPT, '--api-key=synthetic-canary-0000-2918'],
    'thinking on resume': ['--prompt', WAKE, '--output', 'streaming', '--resume', SID, '--trust', '--auto-approve',
                           '--thinking', 'low'],
    'model on resume': ['--prompt', WAKE, '--output', 'streaming', '--model', 'devstral-2', '--resume', SID,
                        '--trust', '--auto-approve'],
    'unlisted thinking': [*START, '--thinking', 'turbo'],
    'yolo alias': ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--trust', '--yolo'],
    'text output': ['--prompt', PROMPT, '--output', 'text', '--model', 'devstral-2', '--trust', '--auto-approve'],
    'missing trust': ['--prompt', PROMPT, '--output', 'streaming', '--model', 'devstral-2', '--auto-approve'],
    'setup': ['--setup'],
}
SIGNED_OUT = 'Missing MISTRAL_API_KEY environment variable for mistral provider'


def run(argv, **extra):
    env = dict(os.environ, FAKE_CLI_LIB=LIB)
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE, *argv], capture_output=True, text=True, env=env)


failed = 0
for name, argv in REFUSED.items():
    got = run(argv)
    if got.returncode != 2:
        failed += 1
        print('fail %s: exited %s, not 2' % (name, got.returncode))

with tempfile.TemporaryDirectory() as tmp:
    record = os.path.join(tmp, 'record')
    start = run([*START, '--thinking', 'low'], FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
    try:
        announced = json.loads(start.stdout)
    except ValueError:
        announced = {}
    sid = announced.get('sessionId')
    wake = run(['--prompt', WAKE, '--output', 'streaming', '--resume', sid or '', '--trust', '--auto-approve'],
               FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
    if start.returncode or not sid or wake.returncode:
        failed += 1
        print('fail allowed lines: start %s session %s wake %s' % (start.returncode, sid, wake.returncode))
    signed = run(START, FAKE_CLI_SIGNED_OUT='1', FAKE_CLI_RECORD_ONLY='1',
                 FAKE_CLI_RECORD=os.path.join(tmp, 'signed'))
    if signed.returncode != 1 or SIGNED_OUT not in signed.stdout or os.path.exists(os.path.join(tmp, 'signed')):
        failed += 1
        print('fail signed out: exited %s' % signed.returncode)

print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), failed))
sys.exit(1 if failed else 0)
