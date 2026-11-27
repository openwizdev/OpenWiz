#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.abspath(os.path.join(HERE, '..', '..', 'fixtures'))
PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill.'
WAKE = 'You were woken: take up example/site#7 again, with the build-ticket skill.'
SID = 'fake-0123456789ab'
START = ['run', '--quiet', '--verbose', '--model', 'synthetic-1', '-y', '--', PROMPT]
WAKE_LINE = ['run', '--quiet', '--verbose', '--session', SID, '--model', 'synthetic-1', '-y', '--', WAKE]
REFUSED = {
    'api key flag': ['run', '--api-key', 'synthetic-canary-0000-2918', *START],
    'api key equals': ['run', '--api-key=synthetic-canary-0000-2918', *START],
    'key-shaped model': ['run', '--quiet', '--verbose', '--model', 'token=synthetic-canary-0000-2918', '-y', '--',
                         PROMPT],
    'bare key as the model': ['run', '--quiet', '--verbose', '--model', 'sk-synthetic0000canary0000', '-y', '--',
                              PROMPT],
    'wake without a model': ['run', '--quiet', '--verbose', '--session', SID, '-y', '--', WAKE],
    'unlisted reasoning effort': [*START[:6], '--reasoning-effort', 'turbo', '--', PROMPT],
    'effort flag the command does not have': [*START[:6], '--effort', 'high', '--', PROMPT],
    'session and continue together': ['run', '--quiet', '--verbose', '--session', SID, '--continue', '-y', '--',
                                      PROMPT],
    'no prompt': ['run', '--quiet', '--verbose', '--model', 'synthetic-1', '-y'],
    'unknown flag': ['run', '--quiet', '--verbose', '--model', 'synthetic-1', '-y', '--bogus', '--', PROMPT],
    'missing run': ['--quiet', '--verbose', '--model', 'synthetic-1', '-y', '--', PROMPT],
}
SIGNED_OUT = "no providers configured - please run 'crush' to set up a provider interactively"


def run(argv, **extra):
    env = dict(os.environ, FAKE_CLI_LIB=LIB, CRUSH_CLIENT_SERVER='0')
    env.pop('FAKE_CLI_SIGNED_OUT', None)
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE, *argv], capture_output=True, text=True, env=env)


failed = 0
with tempfile.TemporaryDirectory() as tmp:
    refused = {name: run(argv, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=os.path.join(tmp, 'refused'))
               for name, argv in REFUSED.items()}
for name, got in refused.items():
    if got.returncode != 2:
        failed += 1
        print('fail %s: exited %s, not 2' % (name, got.returncode))

with_effort = [*START[:6], '--reasoning-effort', 'high', '--', PROMPT]
with tempfile.TemporaryDirectory() as tmp:
    allowed = run(with_effort, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=os.path.join(tmp, 'start'))
    woke = run(WAKE_LINE, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=os.path.join(tmp, 'wake'))
if allowed.returncode or 'session_id=' not in allowed.stdout or woke.returncode:
    failed += 1
    print('fail allowed lines: start %s wake %s' % (allowed.returncode, woke.returncode))
with open(os.path.join(HERE, 'row.json')) as f:
    row = json.load(f)
fills = {'{prompt}': [WAKE], '{model}': ['synthetic-1'], '{session}': [SID], '{mode}': row['modes']['yolo'],
         '{effort}': []}
with tempfile.TemporaryDirectory() as tmp:
    record = os.path.join(tmp, 'wake')
    again = run([b for a in row['wake'] for b in fills.get(a, [a])], FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
    argv = json.load(open(record))['argv'] if os.path.exists(record) else []
model = argv[argv.index('--model') + 1] if '--model' in argv[:-1] else None
if again.returncode or model != 'synthetic-1':
    failed += 1
    print('fail wake after a first turn with no reply: the row\'s wake ran without the start\'s model')
bare = run(START, CRUSH_CLIENT_SERVER='')
if bare.returncode != 2:
    failed += 1
    print('fail without CRUSH_CLIENT_SERVER=0: exited %s' % bare.returncode)
signed = run(START, FAKE_CLI_SIGNED_OUT='1')
if signed.returncode != 1 or SIGNED_OUT not in signed.stdout:
    failed += 1
    print('fail signed out: exited %s' % signed.returncode)

print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), failed))
sys.exit(1 if failed else 0)
