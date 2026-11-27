#!/usr/bin/env python3
import importlib.util, json, os, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(HERE, '..', '..', 'test_harnesses.py')
FAKE = os.path.join(HERE, 'fake')
ENV = {'PATH': os.environ.get('PATH', ''), 'FAKE_CLI_LIB': os.path.join(HERE, '..', '..', 'fixtures'),
       'PYTHONDONTWRITEBYTECODE': '1'}
UUID = '0f2b9a4e-7c1d-4e5f-9a8b-1c2d3e4f5a6b'
START = ['-p', 'Start ticket 7 with the build-ticket skill', '-o', 'stream-json', '--session-id', UUID,
         '-m', 'synthetic-1', '--approval-mode', 'yolo', '--skip-trust']
WAKE = ['-p', 'You were woken: with the build-ticket skill', '-o', 'stream-json', '--resume', UUID,
        '-m', 'synthetic-1', '--approval-mode', 'yolo', '--skip-trust']
REFUSED = {
    'plan mode is read-only': START[:9] + ['plan'],
    'an unknown approval mode': START[:9] + ['ask'],
    'no approval mode': START[:8],
    'text output': START[:3] + ['text'] + START[4:],
    'no output format': START[:2] + START[4:],
    'the session given twice': START[:6] + ['--resume', UUID] + START[6:],
    'a session id that is not a UUID': START[:5] + ['latest'] + START[6:],
    'no model': START[:6] + START[8:],
    'an effort flag': START + ['--effort', 'high'],
    'a thinking budget flag': START + ['--thinking-budget', '4096'],
    'a positional prompt beside -p': START + ['more'],
    'a wake prompt on a start': START[:1] + WAKE[1:2] + START[2:],
    'a start prompt on a wake': WAKE[:1] + START[1:2] + WAKE[2:],
    'interactive -i': ['-i'] + START[1:],
    'nothing': [],
    'an option-shaped prompt after -p': START[:1] + ['--unknown=with the build-ticket skill'] + START[2:],
}
SIGNED_OUT = ('no-auth-type', 'api-key-missing', 'vertex-missing', 'manual-authorization')


def signed_out_starts(bad):
    spec = importlib.util.spec_from_file_location('openwiz_test_harnesses', RUNNER)
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    with open(os.path.join(HERE, 'row.json')) as f:
        row = json.load(f)
    rows = os.path.dirname(HERE)
    with runner.ThrowawayMachine(rows, 'gemini', row['program'], os.path.join(HERE, 'fake'),
                                 next(iter(row['modes']))) as env:
        for auth in SIGNED_OUT:
            code, out = env.start(FAKE_CLI_SIGNED_OUT='1', FAKE_GEMINI_AUTH=auth)
            if not (code == 1 and 'the harness is not signed in (exit 41)' in out.get('error', '') and
                    '`gemini`' in out.get('next', '')):
                bad.append('a first turn signed out with %s gave %r, not the harness is not signed in naming gemini'
                           % (auth, out.get('error', code)))


def main():
    bad = []
    for why, argv in REFUSED.items():
        code = subprocess.run([sys.executable, '-I', FAKE] + argv, env=ENV, capture_output=True, timeout=30).returncode
        if code != 2:
            bad.append('%s exited %d, not 2' % (why, code))
    helped = subprocess.run([sys.executable, '-I', FAKE, '--help'], env=ENV, capture_output=True, text=True, timeout=30)
    if helped.returncode or 'v0.70.0' not in helped.stdout:
        bad.append('--help did not name the version it follows')
    signed_out_starts(bad)
    for line in bad:
        print('fail: ' + line)
    print('test_row.py: %d refusals and %d signed-out first turns checked, %d failed'
          % (len(REFUSED), len(SIGNED_OUT), len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
