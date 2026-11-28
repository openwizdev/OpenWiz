#!/usr/bin/env python3
import importlib.machinery, importlib.util, json, os, re, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
FAKE = os.path.join(HERE, 'fake')
LOCAL = os.path.abspath(os.path.join(HERE, '..', '..'))
LIB = os.path.join(LOCAL, 'fixtures')
DRIVER = os.path.join(LOCAL, 'driver')
RELEASE = os.path.join(LOCAL, 'release.json')
with open(os.path.join(HERE, 'row.json')) as f:
    ROW = json.load(f)
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
PRINTED = '00000000-0000-4000-8000-'
START_PROMPT = 'Build the ticket: example/site#7, with the build-ticket skill. Keep one status note there.'
WAKE_PROMPT = ('You were woken: take up example/site#7 again, with the build-ticket skill. '
               'Edit your own status note there; post no second one.')
SID = PRINTED + '0123456789ab'
START = ['chat', '--v3', '--no-interactive', '--output-format', 'stream-json',
         '--model', 'synthetic-1', '--trust-all-tools', START_PROMPT]
WAKE = ['chat', '--v3', '--no-interactive', '--output-format', 'stream-json',
        '--resume-id', SID, '--model', 'synthetic-1', '--trust-all-tools', WAKE_PROMPT]
REFUSED = {
    'a login flag and its value': START + ['--api-key', 'synthetic-login-value'],
    'a login flag with the value joined': ['--api-key=synthetic-login-value'] + START,
    'the login variable as an argument': START + ['KIRO_API_KEY=synthetic-login-value'],
    'an effort flag': START + ['--effort', 'high'],
    'no headless flag': [a for a in START if a != '--no-interactive'],
    'no stream-json output format': START[:3] + START[5:],
    'an unknown output format': START[:4] + ['plain'] + START[5:],
    'interactive chat': ['chat', START_PROMPT],
    'resume the newest session': START[:5] + ['--resume', '--model', 'synthetic-1', '--trust-all-tools', WAKE_PROMPT],
    'a cloud run': START[:5] + ['--cloud'] + START[5:],
    'trust-tools in place of trust-all-tools': START[:7] + ['--trust-tools=read_file', START_PROMPT],
    'a prompt that is a flag': START[:8] + ['--api-key'],
    'a wake prompt on a start': START[:8] + [WAKE_PROMPT],
    'a start prompt on a wake': WAKE[:10] + [START_PROMPT],
    'a resume id that is not a full UUID': WAKE[:6] + ['abc123-def456'] + WAKE[7:],
    'resume without a session': ['chat', '--v3', '--no-interactive', '--output-format', 'stream-json',
                                 '--resume-id', '--model', 'synthetic-1', '--trust-all-tools', WAKE_PROMPT],
    'nothing': [],
}


QUOTED = {
    "the command reference's example": 'kiro-cli chat --resume-id abc123-def456',
    'a backticked full UUID': 'Resume with `kiro-cli chat --resume-id f2946a26-3735-4b08-8d05-c928010302d5` later',
    'a full UUID in a Markdown code block': '```bash\nkiro-cli chat --resume-id f2946a26-3735-4b08-8d05-c928010302d5\n```',
    'an assistant stream-json message quoting a full UUID': json.dumps({
        'type': 'message',
        'data': {'text': '```bash\nkiro-cli chat --resume-id f2946a26-3735-4b08-8d05-c928010302d5\n```'},
    }),
    'the placeholder': 'kiro-cli chat --resume-id <SESSION_ID>',
}
SIGNED_OUT_ACCEPTED = {
    'prose explaining the Not logged in diagnostic': 'Explaining the "Not logged in" message: run kiro-cli login.',
    'an assistant stream-json message quoting the diagnostic': json.dumps({
        'type': 'message',
        'data': {'text': 'Not logged in. Login with kiro-cli login.'},
    }),
}


def run(args, **extra):
    env = {'PATH': os.environ.get('PATH', ''), 'FAKE_CLI_LIB': LIB, 'PYTHONDONTWRITEBYTECODE': '1'}
    env.update(extra)
    return subprocess.run([sys.executable, '-I', FAKE] + args, env=env, capture_output=True, text=True, timeout=30)


def allows(bad):
    with tempfile.TemporaryDirectory() as folder:
        record = os.path.join(folder, 'calls')
        started = run(START, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
        sid = printed_session(started.stdout) if started.returncode == 0 else ''
        if started.returncode != 0 or not sid.startswith(PRINTED) or read_session(started.stdout) != sid:
            bad.append('a headless start exited %d and printed %r' % (started.returncode, started.stdout))
        else:
            woken = run(WAKE[:6] + [sid] + WAKE[7:], FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
            if woken.returncode != 0:
                bad.append('a resume of the same session exited %d' % woken.returncode)
            else:
                try:
                    rows = [json.loads(line) for line in open(record) if line.strip()]
                except ValueError:
                    rows = []
                if len(rows) != 2 or not re.fullmatch(UUID, sid) or not \
                        rows[0].get('session') == rows[1].get('session') == 'fake-' + sid[len(PRINTED):]:
                    bad.append('the resume did not keep the session the start printed')
        signed = run(START, FAKE_CLI_SIGNED_OUT='1', FAKE_CLI_RECORD=os.path.join(folder, 'absent'))
        if signed.returncode != 1 or 'Not logged in' not in signed.stdout or 'sessionId' in signed.stdout or \
                os.path.exists(os.path.join(folder, 'absent')):
            bad.append('a signed-out start did not print Not logged in and exit 1 before a session')


def load_driver():
    spec = importlib.util.spec_from_loader('openwiz_local_driver',
                                           importlib.machinery.SourceFileLoader('openwiz_local_driver', DRIVER))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_session(output):
    session = ROW['session']
    for line in output.splitlines():
        if 'pattern' in session:
            found = re.search(session['pattern'], line)
            if found:
                return found.group(1)
        elif 'json' in session:
            try:
                value = json.loads(line) if line.lstrip().startswith('{') else None
            except ValueError:
                value = None
            missing = object()
            for key in session['json']:
                value = value[key] if isinstance(value, dict) and key in value else missing
            if value is not missing:
                return value if isinstance(value, str) else None
    return None


def printed_session(stdout):
    last = stdout.strip().splitlines()[-1] if stdout.strip() else ''
    if last.lstrip().startswith('{'):
        return json.loads(last).get('data', {}).get('sessionId', '')
    return last.rpartition(' ')[2]


def announcement(bad):
    for why, line in QUOTED.items():
        with tempfile.TemporaryDirectory() as folder:
            got = run(START, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=os.path.join(folder, 'calls'),
                      FAKE_CLI_PRELUDE=line)
            printed = printed_session(got.stdout)
            if got.returncode or read_session(got.stdout) != printed or not re.fullmatch(UUID, printed):
                bad.append('with %s before the notice, the row read %r, not the full UUID the CLI printed'
                           % (why, read_session(got.stdout)))


def signed_out_controls(bad):
    local = load_driver()
    genuine = 'Not logged in. Login with kiro-cli login.\n'
    if not (local.SIGNED_OUT.search(genuine) or local.signed_out_by_row(ROW, genuine)):
        bad.append('genuine signed-out diagnostic was not detected')
    for why, line in SIGNED_OUT_ACCEPTED.items():
        log = line + '\n'
        if local.SIGNED_OUT.search(log) or local.signed_out_by_row(ROW, log):
            bad.append('successful turn with %s was wrongly refused as signed out' % why)


def release_packaging(bad):
    with open(RELEASE) as f:
        extra = json.load(f).get('extra_files', [])
    if 'harnesses/kiro-cli/row.json' not in extra:
        bad.append('adapters/local/release.json does not list harnesses/kiro-cli/row.json')


def main():
    bad = []
    with tempfile.TemporaryDirectory() as folder:
        record = os.path.join(folder, 'calls')
        for why, argv in REFUSED.items():
            got = run(argv, FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=record)
            if got.returncode != 2:
                bad.append('%s exited %d, not 2' % (why, got.returncode))
    helped = run(['--help'])
    if helped.returncode or 'https://kiro.dev/docs/cli/headless/' not in helped.stdout:
        bad.append('--help did not name the headless reference')
    allows(bad)
    announcement(bad)
    signed_out_controls(bad)
    release_packaging(bad)
    for line in bad:
        print('fail: ' + line)
    print('test_row.py: %d refusals checked, %d failed' % (len(REFUSED), len(bad)))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
