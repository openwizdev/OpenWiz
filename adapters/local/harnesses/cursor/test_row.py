#!/usr/bin/env python3
import json, os, subprocess, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
ENV = dict(os.environ, FAKE_CLI_LIB=os.path.join(HERE, '..', '..', 'fixtures'), FAKE_CLI_SIGNED_OUT='1')
START = 'Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.'
WAKE = 'You were woken: take up example/site#7 again, with the build-ticket skill. Edit your own status note there.'
SID = '00000000-0000-4000-8000-000000000000'
PRINT = ['--print', '--output-format', 'stream-json', '--trust', '--model', 'synthetic-1']
CASES = [
    (2, 'an unknown option', PRINT + ['--effort', 'high', START]),
    (2, 'the hidden --new-session-id', PRINT + ['--new-session-id', SID, START]),
    (2, 'a --model with no value', ['--print', '--output-format', 'stream-json', '--trust', '--model']),
    (2, 'an --output-format outside its choices', ['--print', '--output-format', 'ndjson', '--trust', '--model',
                                                  'synthetic-1', START]),
    (2, 'a --sandbox outside its choices', PRINT + ['--sandbox', 'on', START]),
    (2, 'a --mode outside its choices', PRINT + ['--mode', 'agent', START]),
    (2, '--stream-partial-output without stream-json', ['--print', '--output-format', 'json', '--trust',
                                                        '--stream-partial-output', '--model', 'synthetic-1', START]),
    (2, '--resume with --continue', PRINT + ['--resume', SID, '--continue', WAKE]),
    (2, 'a bare --resume in print mode', PRINT + [WAKE, '--resume']),
    (2, 'a wake prompt without --resume', PRINT + [WAKE]),
    (2, 'a start prompt with --resume', PRINT + ['--resume', SID, START]),
    (3, 'the login command', ['login']),
    (3, 'a login in argv', PRINT + ['--api-key', 'synthetic', START]),
    (3, 'the json output format', ['--print', '--output-format', 'json', '--trust', '--model', 'synthetic-1', START]),
    (3, 'a run without --print', ['--output-format', 'stream-json', '--trust', '--model', 'synthetic-1', START]),
    (3, 'a run with no --model', ['--print', '--output-format', 'stream-json', '--trust', START]),
    (1, 'an untrusted workspace', ['--print', '--output-format', 'stream-json', '--model', 'synthetic-1', START]),
]


def run(args):
    p = subprocess.run([FAKE] + args, env=ENV, capture_output=True, text=True, timeout=30)
    return p.returncode, p.stdout


def row_lines():
    with open(os.path.join(HERE, 'row.json')) as f:
        row = json.load(f)
    for mode, extra in row['modes'].items():
        for field, text in (('start', START), ('wake', WAKE)):
            fills = {'{prompt}': [text], '{model}': ['synthetic-1'], '{session}': [SID], '{mode}': extra,
                     '{effort}': []}
            yield '%s with mode %s' % (field, mode), [b for a in row[field] for b in fills.get(a, [a])]


def main():
    failed = 0
    for want, what, args in CASES:
        got = run(args)[0]
        print('%s %s: exit %d' % ('pass' if got == want else 'fail', what, got))
        failed += got != want
    for what, args in row_lines():
        code, out = run(args)
        ok = code == 1 and "Please run 'agent login'" in out
        print('%s the row\'s %s reaches the turn: exit %d' % ('pass' if ok else 'fail', what, code))
        failed += not ok
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
