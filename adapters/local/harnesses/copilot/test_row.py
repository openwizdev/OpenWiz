import json, os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
SID = '0cb916db-26aa-40f2-86b5-1ba81b225fd2'
FIRST = 'Take up the throwaway ticket with the build-ticket skill.'
WOKEN = 'You were woken: take up the throwaway ticket again, with the build-ticket skill.'
START = ['-p', FIRST, '--output-format', 'json', '--session-id', SID, '--model', 'example-model']
WAKE = ['-p', WOKEN, '--session-id', SID]


def run(argv, record):
    env = {'PATH': os.environ.get('PATH', ''), 'FAKE_CLI_LIB': os.path.join(HERE, '..', '..', 'fixtures'),
           'FAKE_CLI_RECORD': record, 'FAKE_CLI_RECORD_ONLY': '1'}
    return subprocess.run([sys.executable, FAKE] + argv, env=env, capture_output=True, timeout=60).returncode


ALLOWED = [START, START + ['--allow-all-tools'], START + ['--allow-all'], WAKE + ['--allow-all'], WAKE,
           WAKE + ['--allow-all-tools']]
REFUSED = {
    'no -p': START[2:],
    'a flag as the prompt': ['-p', '--model'] + START[2:],
    'the model joined to its flag': START[:6] + ['--model=example-model'],
    'a session id that is not a UUID': START[:5] + ['fake-0123456789ab'] + START[6:],
    'start without --model': START[:6],
    'start without --output-format json': ['-p', FIRST, '--session-id', SID, '--model', 'example-model'],
    'start with text output': START[:3] + ['text'] + START[4:],
    'unsupported: a top-level --yes': START + ['--yes'],
    'effort on start': START + ['--allow-all', '--reasoning-effort', 'xhigh'],
    'effort on start with no mode': START + ['--reasoning-effort', 'low'],
    'effort on wake': WAKE + ['--allow-all-tools', '--reasoning-effort', 'max'],
    'the effort alias on start': START + ['--effort', 'high'],
    'effort before the mode': START + ['--reasoning-effort', 'low', '--allow-all'],
    'two modes': START + ['--allow-all-tools', '--allow-all'],
    'wake with --resume': ['-p', WOKEN, '--resume', SID],
    'wake with --output-format json': ['-p', WOKEN, '--output-format', 'json', '--session-id', SID],
    'a start prompt on the wake line': ['-p', FIRST, '--session-id', SID],
    'a woken prompt on the start line': ['-p', WOKEN] + START[2:],
    'a wake for a session with no start': ['-p', WOKEN, '--session-id', SID.replace('0cb9', '1cb9')],
    'unsupported: a stray positional argument': WAKE + ['extra'],
}

failed = []
with tempfile.TemporaryDirectory() as tmp:
    record = os.path.join(tmp, 'record')
    for argv in ALLOWED:
        code = run(argv, record)
        if code:
            failed.append('allowed %s exited %d' % (json.dumps(argv), code))
    for why, argv in REFUSED.items():
        code = run(argv, record)
        if code != 2:
            failed.append('%s exited %d, not 2' % (why, code))
    turns = []
    if os.path.exists(record):
        with open(record) as f:
            turns = [json.loads(line) for line in f]
    if [t['turn'] for t in turns] != ['first'] * 3 + ['woken'] * 3 or {t['session'] for t in turns} != {SID}:
        failed.append('the fake did not record three first turns and three woken turns of one session')
for line in failed:
    print('fail copilot test_row.py: ' + line)
print('pass copilot test_row.py: %d row lines run, %d lines outside the row grammar exit 2' % (len(ALLOWED), len(REFUSED))
      if not failed else 'fail copilot test_row.py: %d problems' % len(failed))
sys.exit(1 if failed else 0)
