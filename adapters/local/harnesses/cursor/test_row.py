#!/usr/bin/env python3
import json, os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(HERE, '..', '..')
FIXTURES = os.path.join(LOCAL, 'fixtures')
DRIVER = os.path.join(LOCAL, 'driver')
FAKE = os.path.join(HERE, 'fake')
ENV = dict(os.environ, FAKE_CLI_LIB=FIXTURES, FAKE_CLI_SIGNED_OUT='1')
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
    (2, 'a --header without a colon', PRINT + ['--header', 'missing-colon', START]),
    (2, 'a -H without a colon', PRINT + ['-H', 'missing-colon', START]),
    (2, 'a --header= without a colon', PRINT + ['--header=missing-colon', START]),
    (2, 'a --header with an empty name', PRINT + ['--header', ': value', START]),
    (2, 'a --header with a blank name', PRINT + ['--header', '   : value', START]),
    (2, 'a --header with whitespace in the name', PRINT + ['--header', 'Bad Name: value', START]),
    (2, 'a bad second --header after a valid one', PRINT + ['--header', 'X-Test: ok', '--header', 'missing-colon',
                                                            START]),
    (2, 'a bad first --header before a valid one', PRINT + ['--header', 'missing-colon', '--header', 'X-Test: ok',
                                                            START]),
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


def load_row():
    with open(os.path.join(HERE, 'row.json')) as f:
        return json.load(f)


def row_lines(row):
    for mode, extra in row['modes'].items():
        for field, text in (('start', START), ('wake', WAKE)):
            fills = {'{prompt}': [text], '{model}': ['synthetic-1'], '{session}': [SID], '{mode}': extra,
                     '{effort}': []}
            yield '%s with mode %s' % (field, mode), [b for a in row[field] for b in fills.get(a, [a])]


def refuses_allowlist():
    with tempfile.TemporaryDirectory(prefix='cursor-allowlist-') as tmp:
        bin_dir, state = os.path.join(tmp, 'bin'), os.path.join(tmp, 'state')
        repo = os.path.join(tmp, 'repos', 'example', 'site', 'docs', 'agents')
        for d in (bin_dir, state, repo):
            os.makedirs(d, mode=0o700)
        os.symlink(FAKE, os.path.join(bin_dir, 'agent'))
        os.symlink(os.path.join(FIXTURES, 'gh'), os.path.join(bin_dir, 'gh'))
        with open(os.path.join(repo, 'fleet.md'), 'w') as f:
            f.write('# Fleet\n\n| Setting | Value |\n| --- | --- |\n| Harness permission mode | `allowlist` |\n')
        with open(os.open(os.path.join(state, 'approvals.json'), os.O_WRONLY | os.O_CREAT, 0o600), 'w') as f:
            json.dump({'example/site': {'cursor': 'allowlist'}}, f)
        record = os.path.join(tmp, 'rec')
        env = dict(os.environ, PATH=os.pathsep.join([bin_dir, os.environ.get('PATH', '')]),
                   OPENWIZ_LOCAL_STATE=state, OPENWIZ_LOCAL_SETTLE='1',
                   FAKE_REPOS=os.path.join(tmp, 'repos'), FAKE_CLI_LIB=FIXTURES,
                   FAKE_CLI_RECORD=record, FAKE_CLI_RECORD_ONLY='1', PYTHONDONTWRITEBYTECODE='1')
        req = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket',
               'harness': 'cursor', 'model': 'synthetic-1'}
        p = subprocess.run([sys.executable, '-I', DRIVER, 'start'], input=json.dumps(req),
                           env=env, capture_output=True, text=True, timeout=30)
        try:
            out = json.loads(p.stdout)
        except ValueError:
            out = {}
        if p.returncode == 0 and 'run' in out:
            subprocess.run([sys.executable, '-I', DRIVER, 'stop'], input=json.dumps(out),
                           env=env, capture_output=True, text=True, timeout=30)
        return p.returncode == 1 and 'not one its row lists' in out.get('error', '') and not os.path.exists(record)


def main():
    failed = 0
    for want, what, args in CASES:
        got = run(args)[0]
        print('%s %s: exit %d' % ('pass' if got == want else 'fail', what, got))
        failed += got != want
    code, out = run(PRINT + ['--force', '--header', 'X-Test: ok', '-H', 'X-Two: a:b', START])
    ok = code == 1 and "Please run 'agent login'" in out
    print('%s valid --header and -H reach the turn: exit %d' % ('pass' if ok else 'fail', code))
    failed += not ok
    row = load_row()
    ok = row['modes'] == {'force': ['--force']}
    print('%s row.json requires explicit force mode: %s' % ('pass' if ok else 'fail', ', '.join(row['modes'])))
    failed += not ok
    ok = refuses_allowlist()
    print('%s driver refuses allowlist approval: %s' % ('pass' if ok else 'fail', 'refused' if ok else 'accepted'))
    failed += not ok
    for what, args in row_lines(row):
        code, out = run(args)
        ok = code == 1 and "Please run 'agent login'" in out
        print('%s the row\'s %s reaches the turn: exit %d' % ('pass' if ok else 'fail', what, code))
        failed += not ok
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
