import importlib.machinery, importlib.util, json, os, re, signal, subprocess, sys, time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
FAKE = os.path.join(HERE, 'fake')
LIB = os.environ.get('FAKE_CLI_LIB') or os.path.join(HERE, '..', '..', 'fixtures')
SID = '123e4567-e89b-12d3-a456-426614174000'
FIRST = 'Take up example/site#7 with the build-ticket skill.'
WOKEN = 'You were woken: take up example/site#7 again, with the build-ticket skill.'
START = ['--output-format', 'stream-json', '--session-id', SID, '--model', 'synthetic-1', '--approval-mode', 'yolo',
         FIRST]
WAKE = ['--output-format', 'stream-json', '--resume', SID, '--model', 'synthetic-1', '--approval-mode', 'yolo', WOKEN]
GOOD = [START, WAKE] + [START[:7] + [m, FIRST] for m in ('plan', 'default', 'auto-edit', 'auto')]
NOT_QWEN = {
    'an approval mode qwen does not have': START[:7] + ['never', FIRST],
    '--yolo with --approval-mode': START[:8] + ['--yolo', FIRST],
    '--session-id with --resume': WAKE[:4] + ['--session-id', SID] + WAKE[4:],
    'a session id that is not a UUID': START[:3] + ['fake-0123456789ab'] + START[4:],
    'an effort flag qwen does not have': START[:8] + ['--reasoning-effort', 'high', FIRST],
}
OUTSIDE_THE_ROW = {
    'the deprecated -p prompt flag': START[:8] + ['-p', FIRST],
    'no prompt': START[:8],
    'two prompts': START + ['again'],
    'text output': ['--output-format', 'text'] + START[2:],
    'no --model': START[:4] + START[6:],
    'the serve subcommand': ['serve'],
    'the removed auth subcommand': ['auth', 'qwen-oauth'],
}
FIXTURE_RULE = {
    'the start prompt on a resume': WAKE[:8] + [FIRST],
    'a wake prompt on a new session': START[:8] + [WOKEN],
}
BAD = dict(NOT_QWEN, **OUTSIDE_THE_ROW, **FIXTURE_RULE)
HEADLESS_DENIED = {
    'plan': {'run_shell_command', 'monitor', 'edit', 'write_file'},
    'default': {'run_shell_command', 'monitor', 'edit', 'write_file'},
    'auto': {'run_shell_command', 'monitor', 'edit', 'write_file'},
    'auto-edit': {'run_shell_command', 'monitor'},
    'yolo': set(),
}
SIGNED_OUT = ('none', 'qwen-oauth', 'openai', 'openai-env-key', 'provider-key', 'provider-env-key', 'enforced-type',
              'subscription-expired')


def run(argv, **env):
    return subprocess.run([sys.executable, FAKE] + argv, capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, FAKE_CLI_LIB=LIB, **env))


def supervisor_shape():
    if not os.path.isdir('/proc/self'):
        return ['this row holds on Linux only: its detached StopFailure hook supervisor needs the Linux subreaper']
    os.environ['FAKE_CLI_LIB'] = LIB
    loader = importlib.machinery.SourceFileLoader('qwen_fake', FAKE)
    fake = importlib.util.module_from_spec(importlib.util.spec_from_loader('qwen_fake', loader))
    loader.exec_module(fake)
    pid, _ = fake.stop_failure_hook_supervisor('stop-failure-hook')
    try:
        fds = {fd: os.readlink('/proc/%d/fd/%d' % (pid, fd)) for fd in (0, 1, 2, 3)}
        shape = (os.getsid(pid), os.getpgid(pid), fds[0], fds[1], fds[2], fds[3].startswith('pipe:'))
        if shape != (pid, pid, os.devnull, os.devnull, os.devnull, True) or os.getsid(0) == pid:
            return ["the fake's StopFailure hook supervisor is not qwen's detached shape: %r" % (shape,)]
        return []
    finally:
        hooks = []
        for _ in range(1000):
            with open('/proc/%d/task/%d/children' % (pid, pid)) as f:
                hooks = [int(c) for c in f.read().split()]
            if hooks:
                break
            time.sleep(0.01)
        for p in hooks + [pid]:
            os.kill(p, signal.SIGKILL)
        os.waitpid(pid, 0)


def headless_modes(readme):
    table = readme.partition('## The modes')[2].partition('\n## ')[0]
    rows = [[c.strip() for c in l.strip('|').split('|')] for l in table.splitlines() if l.startswith('|')]
    if not rows or not any('headless' in c.lower() for c in rows[0]):
        return ['the README modes table has no column for what each mode does headless']
    col = [i for i, c in enumerate(rows[0]) if 'headless' in c.lower()][0]
    found = {r[0].strip('`'): set(re.findall(r'`(run_shell_command|monitor|edit|write_file)`', r[col]))
             for r in rows[2:] if len(r) > col}
    failures = [] if found == HEADLESS_DENIED else \
        ["the README's headless column does not list the tools qwen removes in each mode: %r" % found]
    if 'security.folderTrust' not in table or 'overridden to "default"' not in table:
        failures.append('the README modes section does not say an untrusted clone downgrades the mode to default')
    return failures


def main():
    with open(os.path.join(HERE, 'row.json')) as f:
        row = json.load(f)
    failures = []
    for name, argv in BAD.items():
        p = run(argv, FAKE_CLI_SIGNED_OUT='1')
        if p.returncode != 2 or p.stdout:
            failures.append('the fake took %s (exit %d)' % (name, p.returncode))
    for argv in GOOD:
        p = run(argv, FAKE_CLI_SIGNED_OUT='1')
        lines = p.stdout.splitlines()
        if p.returncode != 1 or len(lines) != 1 or json.loads(lines[0])['type'] != 'result' or \
                not any(re.search(s, lines[0], re.I) for s in row['signed_out']):
            failures.append('the fake refused a documented line %r (exit %d)' % (argv[:8], p.returncode))
    failures += supervisor_shape()
    seen = set()
    for auth in SIGNED_OUT:
        p = run(START, FAKE_CLI_SIGNED_OUT='1', FAKE_QWEN_AUTH=auth)
        lines = p.stdout.splitlines()
        if p.returncode != 1 or len(lines) != 1 or lines[0] in seen or \
                not any(re.search(s, lines[0], re.I) for s in row['signed_out']):
            failures.append("the row's signed_out misses qwen's %s refusal (exit %d)" % (auth, p.returncode))
        seen.add(lines[0] if lines else '')
    p = run(WAKE, FAKE_QWEN_CHAT_RECORDING='false')
    if p.returncode != 1 or p.stdout or p.stderr != 'No saved session found with ID %s. Run `qwen --resume` without an ' \
            'ID to choose from existing sessions.\n' % SID or any(re.search(s, p.stderr, re.I) for s in row['signed_out']):
        failures.append('a wake with chat recording off is not qwen\'s missing-session exit, or reads as signed out')
    with open(os.path.join(HERE, 'README.md')) as f:
        commands = f.read().partition('## The commands')[2].partition('\n## ')[0]
    if not re.search(r'- Start: .*\n- Wake: .*\n(.*\n)?.*`general\.chatRecording`', commands):
        failures.append('the README does not name the general.chatRecording prerequisite beside start and wake')
    with open(os.path.join(HERE, 'README.md')) as f:
        failures += headless_modes(f.read())
    if 'subscription_credentials.json' not in row['login'] or 'oauth_creds.json' in row['login']:
        failures.append("the row's login does not name the Qwen subscription sign-in, subscription_credentials.json")
    if sorted(row['modes']) != sorted(['plan', 'default', 'auto-edit', 'auto', 'yolo']) or \
            any(v != ['--approval-mode', k] for k, v in row['modes'].items()):
        failures.append("the row's modes are not qwen's five --approval-mode values")
    for line in failures:
        print('fail: ' + line)
    print('test_row.py: %d lines checked for refusal (%d not qwen, %d valid qwen outside this row, %d fixture rules), '
          '%d documented lines, %d sign-in refusals: %s'
          % (len(BAD), len(NOT_QWEN), len(OUTSIDE_THE_ROW), len(FIXTURE_RULE), len(GOOD), len(SIGNED_OUT),
             'fail' if failures else 'ok'))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
