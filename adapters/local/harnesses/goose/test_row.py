#!/usr/bin/env python3
import os, re, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as runner

ROWS = os.path.dirname(HERE)
FAKE = os.path.join(HERE, 'fake')
UUID = r'[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}'
SID = '0b8f2c1e-5d4a-4c3b-9a2f-6e7d8c9b0a1f'
failures = []


def check(what, ok):
    print('%s goose row: %s' % ('pass' if ok else 'fail', what))
    if not ok:
        failures.append(what)


def fake_exit(args, mode='auto'):
    env = {'PATH': os.environ.get('PATH', ''), 'FAKE_CLI_LIB': runner.FIXTURES}
    if mode is not None:
        env['GOOSE_MODE'] = mode
    return subprocess.run([sys.executable, '-I', FAKE] + args, env=env, capture_output=True, timeout=30).returncode


START = 'Build the ticket: example/site#7, with the build-ticket skill.'
WAKE = 'You were woken: take up example/site#7 again, with the build-ticket skill.'
REFUSED = [
    ('a session id without --resume', ['run', '--session-id', SID, '--model', 'm', '--output-format', 'json', '-t', START]),
    ('--no-session with a name', ['run', '--no-session', '-n', SID, '--model', 'm', '--output-format', 'json', '-t', START]),
    ('an output format goose does not have', ['run', '-n', SID, '--model', 'm', '--output-format', 'yaml', '-t', START]),
    ('-t and an instructions file together', ['run', '-n', SID, '--model', 'm', '--output-format', 'json', '-i', 'x.md',
                                              '-t', START]),
    ('no text at all', ['run', '-n', SID, '--model', 'm', '--output-format', 'json']),
    ('an effort flag goose does not have', ['run', '-n', SID, '--model', 'm', '--output-format', 'json', '--effort',
                                            'high', '-t', START]),
    ('a name that is not the driver\'s uuid', ['run', '-n', 'project-x', '--model', 'm', '--output-format', 'json', '-t',
                                               START]),
    ('a wake prompt without --resume', ['run', '-n', SID, '--model', 'm', '--output-format', 'json', '-t', WAKE]),
    ('a start prompt with --resume', ['run', '-n', SID, '--resume', '--model', 'm', '--output-format', 'json', '-t',
                                      START]),
    ('a switch where the model goes', ['run', '-n', SID, '--model', '--bogus', '--output-format', 'json', '-t', START]),
    ('a switch where the text goes', ['run', '-n', SID, '--model', 'm', '--output-format', 'json', '-t', '--bogus']),
]
for what, args in REFUSED:
    check('the fake exits 2 on %s' % what, fake_exit(args) == 2)
good = ['run', '-n', SID, '--model', 'm', '--output-format', 'json', '-t', START]
check('the fake exits 2 on a documented line without GOOSE_MODE=auto', fake_exit(good, None) == 2 and
      fake_exit(good, 'approve') == 2)

row = runner.local.read_row(os.path.join(HERE, 'row.json'), 'goose')
with runner.ThrowawayMachine(ROWS, 'goose', 'goose', FAKE, 'auto', ['GOOSE_MODE']) as env:
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1', GOOSE_MODE='approve')
    woke = env.driver('wake', out) if code == 0 else (1, {})
    env.driver('stop', out)
    turns = env.records()
    sid = turns[0]['session'] if turns else ''
    check('the driver chose a UUID session id and named the session with it at start and wake',
          code == 0 and woke[0] == 0 and len(turns) == 2 and re.fullmatch(UUID, sid) is not None and
          turns[1]['session'] == sid)
    check('a turn runs the documented goose run lines exactly',
          len(turns) == 2 and turns[0]['argv'][:-1] == ['run', '-n', sid, '--model', 'synthetic-1', '--output-format',
                                                        'json', '-t'] and
          turns[1]['argv'][:-1] == ['run', '-n', sid, '--resume', '--model', 'synthetic-1', '--output-format', 'json',
                                    '-t'] and turns[0]['argv'][-1].startswith('Build the ticket: example/site#7') and
          turns[1]['argv'][-1].startswith('You were woken'))
    check("the row's GOOSE_MODE=auto wins over the user's own GOOSE_MODE=approve",
          len(turns) == 2 and all(t['env'] == {'GOOSE_MODE': 'auto'} for t in turns))


SETUP = [
    ('Configuration value not found: ANTHROPIC_API_KEY', True),
    ('Configuration value not found: OPENROUTER_API_KEY', True),
    ('Configuration value not found: DATABRICKS_TOKEN', True),
    ('Configuration value not found: DATABRICKS_HOST', False),
    ('Failed to access keyring: synthetic keyring failure', False),
]
with runner.ThrowawayMachine(ROWS, 'goose', 'goose', FAKE, 'auto', ['GOOSE_MODE']) as env:
    for error, signed_out in SETUP:
        code, out = env.start(FAKE_GOOSE_SETUP_ERROR=error)
        if signed_out:
            check('a first turn that says "%s" fails start as not signed in, naming goose configure' % error,
                  code == 1 and 'the harness is not signed in' in out.get('error', '') and
                  'goose configure' in out.get('next', ''))
        else:
            check('a first turn that says "%s" stays a generic failure, not a sign-in one' % error,
                  code == 1 and 'not signed in' not in out.get('error', '') and 'the harness failed' in
                  out.get('error', ''))


def stat(pid):
    try:
        with open('/proc/%d/stat' % pid) as f:
            fields = f.read().rpartition(')')[2].split()
        return {'ppid': int(fields[1]), 'pgid': int(fields[2])}
    except OSError:
        return None


def fd(pid, n):
    try:
        return os.readlink('/proc/%d/fd/%d' % (pid, n))
    except OSError:
        return ''


def group(pgid):
    return [int(p) for p in os.listdir('/proc') if p.isdigit() and (stat(int(p)) or {}).get('pgid') == pgid]


check('the row declares the shell background process and claims Linux only',
      row['daemon'] != 'none' and 'Linux only' in row['daemon'])
if not os.path.isdir('/proc/self'):
    check('the shell background process check runs on Linux, the only platform the row claims', False)
else:
    with runner.ThrowawayMachine(ROWS, 'goose', 'goose', FAKE, 'auto', ['GOOSE_MODE']) as env:
        code, out = env.start()
        runner.until(lambda: any('daemon' in t for t in env.records()))
        bg = [t['daemon'] for t in env.records() if 'daemon' in t]
        pid, at = bg[0] if len(bg) == 1 else (0, None)
        s = stat(pid) if pid else None
        check('a start leaves one background process, as a backgrounded shell command does',
              code == 0 and len(bg) == 1 and s is not None and runner.since(pid) == at)
        check("it is in the shell's own process group, whose leader, the shell, has exited",
              s is not None and s['pgid'] != pid and stat(s['pgid']) is None and group(s['pgid']) == [pid])
        check('its stdin is closed and its stdout and stderr are the shell\'s own pipes',
              s is not None and fd(pid, 0) == os.devnull and fd(pid, 1).startswith('pipe:') and
              fd(pid, 2).startswith('pipe:'))
        stopped = env.driver('stop', out)
        check('stop ends it on Linux', stopped[0] == 0 and pid and runner.until(lambda: runner.since(pid) != at))

sys.exit(1 if failures else 0)
