#!/usr/bin/env python3
import json, os, shutil, signal, subprocess, sys, tempfile, time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as th

ROWS, NAME = os.path.dirname(HERE), os.path.basename(HERE)
FAKE = os.path.join(HERE, 'fake')
LIB = os.path.join(HERE, '..', '..', 'fixtures')
MODE = 'default'
NEXT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
        "at the host's default")
PROMPT = 'Use the build-ticket skill on example/site#7 with the build-ticket skill'
failed = []


def check(what, ok):
    print('%s %s: %s' % ('pass' if ok else 'fail', NAME, what))
    if not ok:
        failed.append(what)


def without_sculpt(path):
    return os.pathsep.join(d for d in path.split(os.pathsep) if not os.path.exists(os.path.join(d, 'sculpt')))


def alive(pid):
    if not pid:
        return False
    try:
        with open('/proc/%d/stat' % pid) as f:
            fields = f.read().rpartition(')')[2].split()
    except OSError:
        return False
    return fields[0] != 'Z'


def parent(pid):
    with open('/proc/%d/stat' % pid) as f:
        return int(f.read().rpartition(')')[2].split()[1])


def ancestors(pid):
    found = []
    while pid > 1 and alive(pid) and pid not in found:
        found.append(pid)
        pid = parent(pid)
    return found


def run_fake(argv, **env):
    base = dict(os.environ, FAKE_CLI_LIB=LIB, PYTHONDONTWRITEBYTECODE='1')
    base.update(env)
    try:
        return subprocess.run([FAKE] + argv, env=base, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None


def kill(pid):
    if alive(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


with th.ThrowawayMachine(ROWS, NAME, mode=MODE) as env:
    gh_only = os.pathsep.join([os.path.join(env.folder, 'bin'), without_sculpt(env.env['PATH'])])
    before = env.runs()
    code, out = env.start(PATH=gh_only)
    check('not installed is a D3 error whose next says to install sculpt, and starts nothing',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and out.get('error') == 'harness sculpt is not installed here'
          and 'install sculpt' in out.get('next', '') and env.runs() == before)

folder = tempfile.mkdtemp(prefix='sculpt-backend-')
record = os.path.join(folder, 'rec')
pid = None
try:
    created = run_fake(['agent', 'create', '--prompt', PROMPT, '--model', 'synthetic-1', '--json'],
                       FAKE_CLI_RECORD=record, FAKE_CLI_RECORD_ONLY='1')
    session = ''
    if created and created.returncode == 0 and created.stdout.strip():
        session = json.loads(created.stdout)['id']
        with open(record + '.backends') as f:
            pid = json.loads(f.readline())['pid']
    check('create starts a backend session that is not a child of the sculpt process, and that process has exited',
          bool(created) and created.returncode == 0 and session and alive(pid) and parent(pid) == 1)
    interrupted = run_fake(['agent', 'interrupt', session or 'missing'], FAKE_CLI_RECORD=record)
    check('interrupt is a documented command and leaves the backend session running',
          bool(interrupted) and interrupted.returncode == 0 and alive(pid))
    bare = run_fake(['agent', 'delete', session or 'missing'], FAKE_CLI_RECORD=record)
    check('delete without -y exits 2 and leaves the backend session running',
          bool(bare) and bare.returncode == 2 and alive(pid))
    ended = run_fake(['agent', 'delete', session or 'missing', '-y'], FAKE_CLI_RECORD=record)
    check('delete -y ends that backend session',
          bool(ended) and ended.returncode == 0 and session and not alive(pid))
finally:
    kill(pid)
    shutil.rmtree(folder, ignore_errors=True)

with th.ThrowawayMachine(ROWS, NAME, 'sculpt', FAKE, MODE) as env:
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
    woke = env.driver('wake', out) if code == 0 else (1, {})
    env.driver('stop', out)
    turns = env.records()
    first = turns[0]['argv'] if turns else []
    check('start runs `sculpt agent create --prompt <prompt> --model <m> --json`',
          code == 0 and first[:3] == ['agent', 'create', '--prompt'] and first[-3:] == ['--model', 'synthetic-1', '--json']
          and PROMPT in first)
    second = turns[1]['argv'] if len(turns) > 1 else []
    check('wake runs `sculpt agent send <id> <prompt> --model <m> --follow` with the start\'s agent id',
          woke[0] == 0 and len(turns) == 2 and second[:2] == ['agent', 'send'] and second[2] == turns[0]['session']
          and second[-3:] == ['--model', 'synthetic-1', '--follow'])
    check('the agent id read from the indented "id" line is the id wake sends',
          len(turns) == 2 and turns[1]['session'] == turns[0]['session'])

with th.ThrowawayMachine(ROWS, NAME, 'sculpt', FAKE, MODE) as env:
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_LINGER='1')
    pid = None
    sup = None
    session = ''
    try:
        with open(env.record + '.backends') as f:
            pid = json.loads(f.readline())['pid']
    except OSError:
        pid = None
    runs = env.runs()
    if code == 0 and runs:
        state = env.state_of(runs[0][:-len('.json')])
        sup = (state.get('turns') or [{}])[0].get('supervisor')
        session = (env.records() or [{}])[0].get('session', '')
    outside = bool(pid) and alive(pid) and sup and sup not in ancestors(pid)
    stopped = env.driver('stop', out) if code == 0 else (1, {})
    calls = env.calls()
    deadline = time.monotonic() + 2
    while pid and alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    check('stop runs `sculpt agent delete <id> -y` while the turn still runs, and that ends the backend session '
          'the process tree does not hold',
          code == 0 and stopped[0] == 0 and outside and calls and calls[-1]['turns_alive']
          and calls[-1]['argv'] == ['agent', 'delete', session, '-y'] and not alive(pid))
    kill(pid)

refused = {
    'an --effort flag': ['agent', 'create', '--prompt', PROMPT, '--model', 'synthetic-1', '--effort', 'high', '--json'],
    'a --reasoning flag': ['agent', 'create', '--prompt', PROMPT, '--model', 'synthetic-1', '--reasoning', 'high', '--json'],
    'no --json': ['agent', 'create', '--prompt', PROMPT, '--model', 'synthetic-1'],
    'no --prompt': ['agent', 'create', '--model', 'synthetic-1', '--json'],
    'an option where --model needs its value': ['agent', 'create', '--model', '--json', '--prompt', PROMPT],
    'a repeated --prompt': ['agent', 'create', '--prompt', PROMPT, '--prompt', PROMPT, '--model', 'synthetic-1', '--json'],
    'agent run': ['agent', 'run', '--prompt', PROMPT],
    'sculpt run': ['run', PROMPT, '--json'],
    'delete without an agent id': ['agent', 'delete', '-y'],
}
for what, argv in refused.items():
    got = run_fake(argv)
    check('the fake exits 2 on %s' % what, bool(got) and got.returncode == 2)

with th.ThrowawayMachine(ROWS, NAME, 'sculpt', FAKE, MODE) as env:
    for level in ('low', 'medium', 'high', 'xhigh', 'max'):
        check('effort %s is refused with the fixed next, starting nothing' % level,
              env.start_refused_starting_nothing(lambda out: out.get('next') == NEXT, effort=level,
                                                 FAKE_CLI_RECORD_ONLY='1'))

sys.exit(1 if failed else 0)
