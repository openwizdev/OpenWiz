#!/usr/bin/env python3
import json, os, shlex, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.realpath(__file__))
LOCAL = os.path.abspath(os.path.join(HERE, '..', '..'))
ROOT = os.path.abspath(os.path.join(LOCAL, '..', '..'))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.join(LOCAL, 'fixtures')
KIT_FILES = (
    'kernel/driver-kit/kit.py',
    'kernel/driver-kit/schema.json',
    'kernel/records-kit/check.py',
    'kernel/records.v1.md',
    'kernel/driver-kit/hostkey.py',
    'kernel/driver-kit/hosts.json',
)
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

with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(LOCAL, 'release.json')) as f:
        extra = json.load(f)['extra_files']
    runtime = os.path.join(tmp, 'runtime')
    selected = ['adapters/local/driver', 'adapters/local/schema.json',
                *('adapters/local/' + name for name in extra), *KIT_FILES]
    for rel in selected:
        dst = os.path.join(runtime, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, rel), dst)
        os.chmod(dst, 0o700 if rel == 'adapters/local/driver' else 0o600)
    binary = os.path.join(tmp, 'bin')
    state = os.path.join(tmp, 'state')
    repo = os.path.join(tmp, 'repos', 'example', 'site', 'docs', 'agents')
    for d in (binary, state, repo):
        os.makedirs(d, mode=0o700)
    crush_bin = os.path.join(binary, 'crush')
    with open(crush_bin, 'w') as f:
        f.write('#!/bin/sh\nexec %s -I %s "$@"\n' % (shlex.quote(sys.executable), shlex.quote(FAKE)))
    os.chmod(crush_bin, 0o700)
    os.symlink(os.path.join(LIB, 'gh'), os.path.join(binary, 'gh'))
    with open(os.path.join(repo, 'fleet.md'), 'w') as f:
        f.write('# Fleet\n\n| Setting | Value |\n| --- | --- |\n| Harness permission mode | `yolo` |\n')
    with open(os.open(os.path.join(state, 'approvals.json'), os.O_WRONLY | os.O_CREAT, 0o600), 'w') as f:
        json.dump({'example/site': {'crush': 'yolo'}}, f)
    tracker = os.path.join(tmp, 'tracker.json')
    with open(tracker, 'w') as f:
        json.dump({'record_authors': ['Example-Bot[bot]'], 'comments': []}, f)
    staged_env = dict(
        os.environ,
        PATH=os.pathsep.join((binary, os.environ.get('PATH', ''))),
        KIT_TRACKER=tracker,
        FAKE_REPOS=os.path.join(tmp, 'repos'),
        OPENWIZ_LOCAL_STATE=state,
        OPENWIZ_LOCAL_SETTLE='1',
        FAKE_CLI_LIB=LIB,
        FAKE_CLI_RECORD=os.path.join(tmp, 'staged-rec'),
        FAKE_CLI_RECORD_ONLY='1',
        PYTHONDONTWRITEBYTECODE='1',
    )
    staged_env.pop('FAKE_CLI_SIGNED_OUT', None)
    staged_driver = os.path.join(runtime, 'adapters', 'local', 'driver')
    req = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': 'crush',
           'model': 'synthetic-1'}
    started = subprocess.run([staged_driver, 'start'], input=json.dumps(req), env=staged_env,
                             capture_output=True, text=True, timeout=60)
    try:
        out = json.loads(started.stdout)
    except ValueError:
        out = {}
    if started.returncode != 0 or not isinstance(out.get('run'), str):
        failed += 1
        print('fail installed runtime: exited %s, stdout=%s' % (started.returncode, started.stdout.strip()))
    else:
        subprocess.run([staged_driver, 'stop'], input=json.dumps({'run': out['run']}), env=staged_env,
                       capture_output=True, text=True, timeout=60)

print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), failed))
sys.exit(1 if failed else 0)
