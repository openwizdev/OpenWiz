#!/usr/bin/env python3
import json, os, re, subprocess, sys, tempfile, time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FAKE = os.path.join(HERE, 'fake')
LOCAL = os.path.abspath(os.path.join(HERE, '..', '..'))
LIB = os.path.join(LOCAL, 'fixtures')
sys.path.insert(0, LOCAL)
from test_harnesses import CANT_SET_EFFORT, ThrowawayMachine, local
PROMPT = 'Do the task with the ship skill.'
WAKE = 'You were woken: take up example/open#1 again, with the ship skill.'
SID = 'fake-0123456789ab'
MODEL = 'mistral-large-4-0'
START = ['--prompt', PROMPT, '--output', 'streaming', '--model', MODEL, '--auto-approve']
RESUME = ['--prompt', WAKE, '--output', 'streaming', '--resume', SID, '--auto-approve']
REFUSED = {
    'api key flag': ['--api-key', 'synthetic-canary-0000-2918', *START],
    'api key equals': ['--prompt', PROMPT, '--api-key=synthetic-canary-0000-2918'],
    'thinking at start': [*START, '--thinking', 'low'],
    'thinking off at start': [*START, '--thinking', 'off'],
    'thinking on resume': [*RESUME, '--thinking', 'low'],
    'model on resume': ['--prompt', WAKE, '--output', 'streaming', '--model', MODEL, '--resume', SID,
                        '--auto-approve'],
    'empty model': ['--prompt', PROMPT, '--output', 'streaming', '--model', '', '--auto-approve'],
    'blank model': ['--prompt', PROMPT, '--output', 'streaming', '--model', '  ', '--auto-approve'],
    'bare resume': ['--prompt', WAKE, '--output', 'streaming', '--resume', '--auto-approve'],
    'trust': [*START[:6], '--trust', '--auto-approve'],
    'yolo alias': [*START[:6], '--yolo'],
    'text output': ['--prompt', PROMPT, '--output', 'text', '--model', MODEL, '--auto-approve'],
    'no approval': START[:6],
    'setup': ['--setup'],
}
SIGNED_OUT = {
    '1': 'Error: Missing MISTRAL_API_KEY environment variable for mistral provider',
    'not-signed-in': 'Error: You are not signed in to Mistral. Sign in and retry.',
    'keyring': "Error: Can't read MISTRAL_API_KEY from the system keyring for mistral provider (locked). Unlock the "
               "system keyring or approve its prompt, or set the MISTRAL_API_KEY environment variable",
}
LIMIT_LINE = ('Error: API error occurred: Status 429. Body: {"object":"error","message":"Requests rate limit exceeded",'
              '"type":"rate_limited","param":null,"code":"1300"}')
NOT_LIMITS = (
    'Error: API error occurred: Status 400. Body: {"object":"error","message":"Invalid model"}',
    'Error: Unknown model: synthetic-1. Available: mistral-large-4-0, mistral-medium-3.5',
    *SIGNED_OUT.values(),
)
QUOTED_STREAMS = (
    ('missing key', 'When unset, Vibe prints:\n' + SIGNED_OUT['1']),
    ('not signed in', 'If not logged in, Vibe prints:\n' + SIGNED_OUT['not-signed-in']),
)
TIMED = '''import importlib.machinery, importlib.util, os, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('local', importlib.machinery.SourceFileLoader('local', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
t.SELF = os.path.abspath(__file__)
t.limit_jitter = lambda: 0.0
def no_sleep(seconds, run):
    with open(os.environ['VIBE_WAITS'], 'a') as f:
        f.write('%%.1f\\n' %% seconds)
    return not t.limit_stop_requested(run)
t.limit_sleep = no_sleep
t.main()
'''

with open(os.path.join(HERE, 'row.json')) as f:
    ROW = json.load(f)
failed = 0


def fail(message):
    global failed
    failed += 1
    print('fail ' + message)


def run(argv, **extra):
    env = dict(os.environ, FAKE_CLI_LIB=LIB)
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE, *argv], capture_output=True, text=True, env=env)


def stream_message(text):
    return json.dumps({'type': 'message', 'role': 'assistant', 'sessionId': SID, 'generationStatus': 'completed',
                       'content': [{'type': 'text', 'text': text}]}, separators=(',', ':'))


def until(ready, wait=20):
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if ready():
            return True
        time.sleep(0.1)
    return ready()


if not (isinstance(ROW.get('effort'), str) and ROW['effort'].startswith('none: ') and 'v3.1.5' in ROW['effort']):
    fail('row effort: not the none form naming mistral-vibe v3.1.5')
if any('{effort}' in ROW[k] or '--thinking' in ROW[k] or '--trust' in ROW[k] for k in ('start', 'wake')):
    fail('row start/wake: still passes {effort}, --thinking or --trust')
if '--model' in ROW['wake'] or ROW['start'][ROW['start'].index('--model') + 1:][:1] != ['{model}']:
    fail('row model: start must pass {model} to --model as one argument, and wake no model')
if ROW.get('daemon', 'none') == 'none':
    fail("row daemon: vibe -p's app-server runs in its own process group; the row must name it")
try:
    local.check_row(dict(ROW), 'vibe')
except Exception as e:
    fail('row.json: the driver refuses it: %s' % e)
limit = ROW.get('limit')
if not limit:
    fail('row limit: no usage-limit pattern')
else:
    if not re.search(limit, LIMIT_LINE, re.I):
        fail("row limit: the pattern misses Vibe's own 429 line")
    for line in NOT_LIMITS + (stream_message(LIMIT_LINE),):
        if re.search(limit, line, re.I):
            fail('row limit: the pattern matches a line that is not a usage limit: %r' % line)
    got = local.detect_limit(['{"type":"message"}', LIMIT_LINE], ROW, now=1795460000.0)
    if not got or got['kind'] != 'limit' or got['reset_at'] is not None:
        fail('row limit: the driver reads %r, not a limit with no reset time' % (got,))
for mode, line in SIGNED_OUT.items():
    if not any(re.search(p, line, re.I) for p in ROW.get('signed_out', [])):
        fail('row signed_out: misses %r' % line)

for name, argv in REFUSED.items():
    got = run(argv)
    if got.returncode != 2:
        fail('%s: exited %s, not 2' % (name, got.returncode))

with tempfile.TemporaryDirectory() as tmp:
    record = os.path.join(tmp, 'record')
    start = run(START, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
    try:
        sid = json.loads(start.stdout).get('sessionId')
    except ValueError:
        sid = None
    wake = run([*RESUME[:5], sid or '', '--auto-approve'], FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
    if start.returncode or not sid or wake.returncode:
        fail('allowed lines: start %s session %s wake %s' % (start.returncode, sid, wake.returncode))
    for mode, expected in SIGNED_OUT.items():
        rec = os.path.join(tmp, 'signed-' + mode)
        signed = run(START, FAKE_CLI_SIGNED_OUT=mode, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=rec)
        if signed.returncode != 1 or signed.stdout.strip() != expected or os.path.exists(rec):
            fail('fake signed out (%s): exited %s, stdout %r' % (mode, signed.returncode, signed.stdout.strip()))
    asked = run(START, FAKE_CLI_LIMIT='now', FAKE_CLI_RECORD=os.path.join(tmp, 'limit'))
    if asked.returncode != 2 or asked.stderr.strip() != LIMIT_LINE:
        fail('fake limit: exited %s, stderr %r' % (asked.returncode, asked.stderr.strip()))

with ThrowawayMachine(os.path.dirname(HERE), 'vibe', 'vibe', FAKE, 'auto-approve') as machine:
    for mode in SIGNED_OUT:
        code, out = machine.start(FAKE_CLI_SIGNED_OUT=mode)
        if not (code == 1 and 'the harness is not signed in (exit 1)' in out.get('error', '')
                and 'vibe --setup' in out.get('next', '') and 'MISTRAL_API_KEY' in out.get('next', '')):
            fail('driver signed out (%s): code %s out %r' % (mode, code, out))
    for label, text in QUOTED_STREAMS:
        code, out = machine.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_QUIET='1', FAKE_CLI_PRELUDE=stream_message(text))
        if code == 0 and 'run' in out:
            if machine.driver('stop', out)[0] != 0:
                fail('quoted stream stop (%s)' % label)
        else:
            fail('quoted stream (%s): code %s error %r' % (label, code, out.get('error')))
    for level in ('off', 'low', 'medium', 'high', 'xhigh', 'max'):
        if not machine.start_refused_starting_nothing(lambda out: out.get('next') == CANT_SET_EFFORT, None, level,
                                                      FAKE_CLI_RECORD_ONLY='1'):
            fail('effort %s: not refused with the fixed next, or something started' % level)

    machine.forget_calls()
    timed = os.path.join(machine.folder, 'driver-no-wait')
    with open(timed, 'w') as f:
        f.write('#!%s\n' % sys.executable + TIMED % machine.driver_path)
    os.chmod(timed, 0o700)
    waits = os.path.join(machine.folder, 'waits')
    req = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'vibe',
           'model': MODEL}
    code, out = machine.driver('start', req, timed, FAKE_CLI_LIMIT='first', VIBE_WAITS=waits)
    if code != 0 or 'run' not in out:
        fail('limit: start failed: %s %r' % (code, out))
    else:
        resumed = until(lambda: [r['turn'] for r in machine.records()] == ['first', 'woken'])
        turns = machine.records()
        log = machine.log(out['run'])
        if not resumed:
            fail('limit: no single resume after the 429 line: %r' % [r['turn'] for r in turns])
        elif turns[0]['session'] != turns[1]['session'] or '--model' in turns[1]['argv'] \
                or turns[1]['argv'][turns[1]['argv'].index('--resume') + 1] != turns[0]['session']:
            fail('limit: the resume was not on the same session: %r' % turns)
        if LIMIT_LINE not in log or 'driver: limit; waiting until' not in log:
            fail("limit: the run's log lacks the 429 line or the driver's wait")
        until(lambda: 'woke and read the ticket again' in open(machine.tracker).read())
        if 'model: %s' % MODEL not in open(machine.tracker).read():
            fail('limit: the resumed turn did not run on %s' % MODEL)
        try:
            with open(waits) as f:
                waited = f.read().split()
        except OSError:
            waited = []
        if waited != ['60.0']:
            fail('limit: waits %r, not one 60-second wait' % waited)
        if machine.driver('stop', out, timed, VIBE_WAITS=waits)[0] != 0:
            fail('limit: stop failed')

print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), failed))
sys.exit(1 if failed else 0)
