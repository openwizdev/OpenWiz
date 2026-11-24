#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
LOCAL = os.path.abspath(os.path.join(HERE, '..', '..'))
LIB = os.path.join(LOCAL, 'fixtures')
sys.path.insert(0, LOCAL)
from test_harnesses import ThrowawayMachine
BASE = ['--skip-update-check', '--output-format', 'json']
REFUSED = {
    'text output': ['--skip-update-check', '--output-format', 'text', '--model', 'm', '--task', 'p'],
    'no update-check skip': ['--output-format', 'json', '--model', 'm', '--task', 'p'],
    'no model': BASE + ['--task', 'p'],
    'empty task': BASE + ['--model', 'm', '--task', ''],
    'a bare --resume, which resumes the last session, not this run\'s': BASE + ['--resume', '--model', 'm', '--task', 'p'],
    'a session id without --resume': BASE + ['--session-id', 's-1', '--model', 'm', '--task', 'p'],
    'a session id that is not one': BASE + ['--session-id', 'a b', '--resume', '--model', 'm', '--task', 'p'],
    '--effort, which the row never sends': BASE + ['--model', 'm', '--effort', 'high', '--task', 'p'],
    '--brave, which is interactive only': BASE + ['--model', 'm', '--brave', '--task', 'p'],
    'a positional task': BASE + ['--model', 'm', 'p'],
}


def run(args, **env):
    return subprocess.run([FAKE] + args, capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, FAKE_CLI_LIB=LIB, PYTHONDONTWRITEBYTECODE='1', **env))


def check_start(bad):
    with ThrowawayMachine(os.path.dirname(HERE), 'junie', 'junie', FAKE, 'allow-all') as machine:
        code, out = machine.start(FAKE_CLI_SIGNED_OUT='1')
        if code == 1 and 'the harness is not signed in (exit 0)' in out.get('error', '') and \
                'sign in yourself with `junie`' in out.get('next', ''):
            print('pass junie start: a signed-out response asks the user to sign in')
        else:
            bad.append('a signed-out Junie response did not fail start with sign-in guidance')

        reply = json.dumps({
            'sessionId': 'synthetic-junie-session',
            'errors': [],
            'result': 'The log said: "Cannot find authorization. Please authenticate before running Junie."',
        })
        code, out = machine.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_QUIET='1', FAKE_CLI_PRELUDE=reply)
        if code == 0 and 'run' in out:
            stopped, _ = machine.driver('stop', out)
            if stopped == 0:
                print('pass junie start: a successful result quoting the diagnostic starts normally')
            else:
                bad.append('the run quoting the diagnostic did not stop')
        elif 'the harness is not signed in' in out.get('error', ''):
            bad.append('a successful Junie result quoting the diagnostic was treated as signed out')
        else:
            bad.append('a successful Junie result quoting the diagnostic did not start a run')


def main():
    bad = []
    for why, args in REFUSED.items():
        p = run(args)
        if p.returncode != 2:
            bad.append('fake accepted %s (exit %d)' % (why, p.returncode))
    with tempfile.TemporaryDirectory() as d:
        p = run(BASE + ['--model', 'm', '--task', 'start with the build-ticket skill'], FAKE_CLI_SIGNED_OUT='1',
                FAKE_CLI_RECORD=os.path.join(d, 'rec'))
        out = [json.loads(line) for line in p.stdout.splitlines() if line.strip()]
        if p.returncode != 0 or len(out) != 1 or 'sessionId' in out[0] or not out[0].get('errors') or \
                os.path.exists(os.path.join(d, 'rec')):
            bad.append('fake signed out did not answer as Junie 26.9.7 does: one errors line, no sessionId, exit 0, '
                       'and no turn')
    check_start(bad)
    for line in bad:
        print('fail ' + line)
    print('pass junie test_row.py: the fake refuses %d command lines the row never sends, and answers signed out '
          'as Junie does' % len(REFUSED) if not bad else 'fail junie test_row.py: %d problem(s)' % len(bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
