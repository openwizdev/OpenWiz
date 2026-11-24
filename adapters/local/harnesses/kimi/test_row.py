#!/usr/bin/env python3
import json, os, re, secrets, signal, subprocess, sys, tempfile
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.join(HERE, '..', '..', 'fixtures')
PROMPT = 'Work on the ticket with the build-ticket skill.'
WOKEN = 'You were woken. Carry on with the build-ticket skill.'
START = ['-p', PROMPT, '--output-format', 'stream-json', '-m', 'kimi-code/kimi-for-coding']

# External: kimi refuses -p with --yolo, --auto or --plan, --output-format without -p, and an empty or blank model,
# https://github.com/MoonshotAI/kimi-code/blob/56145f849caa305d42acd09b67fb65d11146f887/apps/kimi-code/src/cli/options.ts
REFUSED = [START + ['--yolo'], START + ['-y'], START + ['--yes'], START + ['--auto-approve'], START + ['--auto'],
           START + ['--plan'], START[2:], START + ['-p', PROMPT], ['-p', ' '] + START[2:],
           ['-p', PROMPT, '--output-format', 'json', '-m', 'm'], ['-p', PROMPT, '-m', 'm'],
           ['-p', PROMPT, '--output-format', 'stream-json'], ['--continue'] + START, START + ['extra'],
           ['-S', '', '-p', WOKEN], ['-S', 'fake-1', '-p', WOKEN, '--yolo'], ['-S', 'fake-1'], ['--prompt=' + PROMPT],
           START[:-1] + [''], START[:-1] + [' \t'], ['--model', ' ', '--output-format', 'stream-json', '--prompt', PROMPT],
           ['-S', 'fake-1', '-p', WOKEN, '-m', '']]
ALLOWED = [(START, None), (['--model', 'm', '--output-format', 'stream-json', '--prompt', PROMPT], None),
           (['-S', 'fake-1', '-p', WOKEN], 'fake-1'), (['--resume', 'fake-2', '--prompt', WOKEN, '-m', 'm'], 'fake-2')]

# External: with no `kimi login` token, print mode stops in ensureReady and main prints the thrown message;
# a third-party provider's missing key or an unresolved model is not fixed by `kimi login`.
# https://github.com/MoonshotAI/kimi-code/blob/56145f849caa305d42acd09b67fb65d11146f887/packages/agent-core-v2/src/app/auth/auth.ts
# https://github.com/MoonshotAI/kimi-code/blob/56145f849caa305d42acd09b67fb65d11146f887/apps/kimi-code/src/cli/main.ts
NOT_SIGNED_OUT = ['error: failed to run prompt: provider my-openai has no credential configured',
                  'error: failed to run prompt: provider managed:kimi-code-extra has no credential configured',
                  'error: failed to run prompt: model kimi-code/kimi-for-coding does not resolve to a configured provider',
                  'error: failed to run prompt: no default model configured',
                  '{"role":"assistant","content":"the provider is managed:kimi-code"}']


def signed_out(folder):
    with open(os.path.join(HERE, 'row.json')) as f:
        row = json.load(f)
    patterns = [re.compile(x, re.I) for x in row.get('signed_out', [])]
    p = run(START, folder, FAKE_CLI_SIGNED_OUT='1')
    bad = [] if row.get('login_command') == 'kimi login' else ['the row has no login_command `kimi login`']
    if p.returncode != 1 or not any(x.search(line) for x in patterns for line in p.stdout.splitlines()):
        bad.append('signed-out turn printed %r (exit %d), which the row\'s signed_out misses' % (p.stdout, p.returncode))
    bad += ['the row\'s signed_out matches %r' % line for line in NOT_SIGNED_OUT if any(x.search(line) for x in patterns)]
    return bad

# External: kimi runs each background Bash task with spawn's detached: true and piped stdio on Unix, so the task
# leads its own session and process group and its output goes back to kimi.
# https://github.com/MoonshotAI/kimi-code/blob/56145f849caa305d42acd09b67fb65d11146f887/packages/agent-core-v2/src/os/backends/node-local/hostProcessService.ts


def background_shape(folder):
    if not os.path.isdir('/proc/self'):
        return []
    mark = secrets.token_hex(8)
    with open(os.path.join(folder, 'tracker'), 'w') as f:
        json.dump({'comments': []}, f)
    with open(os.path.join(folder, 'run-1.json'), 'w') as f:
        json.dump({'starting': False}, f)
    record = os.path.join(folder, 'record-shape')
    env = dict(PATH=os.environ.get('PATH', ''), FAKE_CLI_LIB=LIB, FAKE_CLI_RECORD=record, KIMI_CODE_NO_AUTO_UPDATE='1',
               KIT_TRACKER=os.path.join(folder, 'tracker'), OPENWIZ_LOCAL_STATE=folder, OPENWIZ_RUN='run-1',
               KIMI_TEST_MARK=mark)
    turn = subprocess.Popen([sys.executable, '-I', FAKE] + START, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pids = []
    try:
        turn.wait(timeout=60)
        with open(record) as f:
            pids.append(json.loads(f.readline())['daemon'][0])
        pid, bad = pids[0], []
        if not (os.getsid(pid) == os.getpgid(pid) == pid != os.getsid(0)):
            bad.append('the background process does not lead its own session and process group, as a kimi Bash task does')
        fds = [os.readlink('/proc/%d/fd/%d' % (pid, n)) for n in (0, 1, 2)]
        if not all(x.startswith('pipe:') for x in fds):
            bad.append('the background process has stdio %r, not the pipes a kimi Bash task has' % fds)
        return bad
    finally:
        for p in [x for x in os.listdir('/proc') if x.isdigit()]:
            try:
                with open('/proc/%s/environ' % p, 'rb') as f:
                    if ('KIMI_TEST_MARK=' + mark).encode() in f.read().split(b'\0'):
                        pids.append(int(p))
            except OSError:
                pass
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

def run(argv, folder, **extra):
    env = dict(PATH=os.environ.get('PATH', ''), FAKE_CLI_LIB=LIB, FAKE_CLI_RECORD=os.path.join(folder, 'record'),
               FAKE_CLI_RECORD_ONLY='1', KIMI_CODE_NO_AUTO_UPDATE='1', **extra)
    return subprocess.run([sys.executable, '-I', FAKE] + argv, env=env, capture_output=True, text=True, timeout=60)


def main():
    bad = []
    with tempfile.TemporaryDirectory() as folder:
        for argv in REFUSED:
            p = run(argv, folder)
            if p.returncode != 2 or p.stdout:
                bad.append('the fake allowed %r (exit %d)' % (argv, p.returncode))
        for argv, session in ALLOWED:
            p = run(argv, folder)
            lines = [json.loads(x) for x in p.stdout.splitlines()]
            hint = [x for x in lines if x.get('type') == 'session.resume_hint']
            if p.returncode != 0 or (session is None) != (len(hint) == 1) or \
                    (hint and hint[0]['command'] != 'kimi -r ' + hint[0]['session_id']):
                bad.append('the fake refused or misreported %r (exit %d)' % (argv, p.returncode))
        if not bad:
            with open(os.path.join(folder, 'record')) as f:
                sessions = [json.loads(x)['session'] for x in f]
            if sessions[2:] != ['fake-1', 'fake-2']:
                bad.append('the fake\'s woken turns got %r' % sessions[2:])
        bad += signed_out(folder)
        bad += background_shape(folder)
    for line in bad:
        print('fail: ' + line)
    print('fail' if bad else 'pass: the fake takes only the documented kimi command lines, and signed_out matches only kimi\'s missing login')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
