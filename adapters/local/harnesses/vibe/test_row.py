#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FAKE = os.path.join(HERE, 'fake')
LOCAL = os.path.abspath(os.path.join(HERE, '..', '..'))
LIB = os.path.join(LOCAL, 'fixtures')
sys.path.insert(0, LOCAL)
from test_harnesses import ThrowawayMachine
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
SIGNED_OUT_MISSING = 'Error: Missing MISTRAL_API_KEY environment variable for mistral provider'
SIGNED_OUT_MISTRAL = 'Error: You are not signed in to Mistral. Sign in and retry.'
QUOTED_STREAMS = (
    ('missing key', 'When unset, Vibe prints:\n' + SIGNED_OUT_MISSING),
    ('not signed in', 'If not logged in, Vibe prints:\n' + SIGNED_OUT_MISTRAL),
)


def run(argv, **extra):
    env = dict(os.environ, FAKE_CLI_LIB=LIB)
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE, *argv], capture_output=True, text=True, env=env)


def stream_message(text):
    return json.dumps({
        'type': 'message',
        'role': 'assistant',
        'sessionId': SID,
        'generationStatus': 'completed',
        'content': [{'type': 'text', 'text': text}],
    }, separators=(',', ':'))


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
    for mode, expected in (('1', SIGNED_OUT_MISSING), ('not-signed-in', SIGNED_OUT_MISTRAL)):
        rec = os.path.join(tmp, 'signed-' + mode)
        signed = run(START, FAKE_CLI_SIGNED_OUT=mode, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=rec)
        if signed.returncode != 1 or signed.stdout.strip() != expected or os.path.exists(rec):
            failed += 1
            print('fail fake signed out (%s): exited %s, stdout %r' % (mode, signed.returncode, signed.stdout.strip()))

with ThrowawayMachine(os.path.dirname(HERE), 'vibe', 'vibe', FAKE, 'auto-approve') as machine:
    for mode in ('1', 'not-signed-in'):
        code, out = machine.start(FAKE_CLI_SIGNED_OUT=mode)
        if not (code == 1 and 'the harness is not signed in (exit 1)' in out.get('error', '')
                and 'vibe --setup' in out.get('next', '') and 'MISTRAL_API_KEY' in out.get('next', '')):
            failed += 1
            print('fail driver signed out (%s): code %s out %r' % (mode, code, out))
    for label, text in QUOTED_STREAMS:
        code, out = machine.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_QUIET='1',
                                  FAKE_CLI_PRELUDE=stream_message(text))
        if code == 0 and 'run' in out:
            stopped, _ = machine.driver('stop', out)
            if stopped != 0:
                failed += 1
                print('fail quoted stream stop (%s): code %s' % (label, stopped))
        else:
            failed += 1
            print('fail quoted stream (%s): code %s error %r' % (label, code, out.get('error')))

print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), failed))
sys.exit(1 if failed else 0)
