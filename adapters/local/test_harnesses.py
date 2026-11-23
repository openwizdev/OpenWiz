#!/usr/bin/env python3
import importlib.machinery, importlib.util, json, os, shutil, signal, socket, subprocess, sys, tempfile, threading, time

sys.dont_write_bytecode = True
USAGE = '''usage: test_harnesses.py            the planted rows, then every row in adapters/local/harnesses/
       test_harnesses.py --rows <dir> only the rows in <dir>'''
HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'driver')
KIT_DIR = os.path.join(HERE, '..', '..', 'kernel', 'driver-kit')
FIXTURES = os.path.join(HERE, 'fixtures')
ROWS = os.path.join(HERE, 'harnesses')
sys.path.insert(0, KIT_DIR)
import kit

local = importlib.util.module_from_spec(importlib.util.spec_from_loader(
    'openwiz_local_driver', importlib.machinery.SourceFileLoader('openwiz_local_driver', DRIVER)))
local.__spec__.loader.exec_module(local)

# SAFETY: no-op stubs for every known agent CLI, so no real one runs here; only a row's own fake goes ahead of them.
STUBS = ('claude codex cursor-agent agent pi opencode copilot goose gemini kimi qwen cline kilo crush vibe auggie '
         'kiro-cli junie amp agy oz sculpt hermes acpx droid').split()
CANT_SET_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster "
                   "to run it at the host's default")
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 1',
        'pass wake: the run edited builder status note 1',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
GOOD = 'the contract, the folder, the kit\'s five checks, and the session, env, background process and effort checks'
PLANTED = {
    'example': 'pass example: ' + GOOD,
    'example-none': 'pass example-none: ' + GOOD,
    'signed-out-json': 'pass signed-out-json: ' + GOOD,
    'wake-no-session': 'fail wake-no-session: row.json wake: it has no {session}',
    'larger-argument': 'fail larger-argument: row.json start: a placeholder sits inside a larger argument; '
                       'each fills a whole argument',
    'credential-env': 'fail credential-env: row.json env: a value looks like a credential; env holds only fixed '
                      'settings that are not credentials',
    'daemon-survives': 'fail daemon-survives: daemon: the background process the row declares still runs after stop',
    'session-differs': 'fail session-differs: session: the wake turn got a different session id from the start turn',
    'claude': 'fail claude: row.json harness: claude is built in, and no row may use a built-in name',
    'effort-unpassed': 'fail effort-unpassed: row.json effort: it maps effort values to arguments, but start has no '
                       '{effort} to pass them',
    'row-missing': 'fail row-missing: row.json is missing',
    'signed-out-bad-pattern': 'fail signed-out-bad-pattern: row.json signed_out: a pattern does not compile',
    'effort-missing': 'fail effort-missing: row.json effort: it has no effort form; give an effort map or '
                      '"none: <one line why>"',
}
ERROR = kit.load_schema()['error']
WRAPPER = '''import importlib.machinery, importlib.util, sys
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_loader('local', importlib.machinery.SourceFileLoader('local', %r))
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
t.START['effort'] = t.EFFORT
t.main()
'''


class Fail(Exception):
    pass


def since(pid):
    if not os.path.isdir('/proc/self'):
        try:
            os.kill(pid, 0)
            return 0
        except OSError:
            return None
    try:
        with open('/proc/%d/stat' % pid) as f:
            fields = f.read().rpartition(')')[2].split()
        return None if fields[0] == 'Z' else int(fields[19])
    except OSError:
        return None


class RunningHubOutsideEveryRun:

    def __init__(self, path, env):
        self.pids, self.sock = [], socket.socket(socket.AF_UNIX)
        self.sock.bind(path)
        self.sock.listen()
        self.env = env
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                p = subprocess.Popen(['sleep', '300'], start_new_session=True, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.pids.append(p)
                conn.sendall(b'%d\n' % p.pid)

    def close(self):
        self.sock.close()
        for p in self.pids:
            p.kill()
            p.wait()


class ThrowawayMachine:

    def __init__(self, rows, name, program=None, fake=None, mode=None, names=()):
        self.folder = tempfile.mkdtemp(prefix='rows-')
        checkout = os.path.join(self.folder, 'checkout', 'adapters', 'local')
        os.makedirs(checkout)
        for link, real in (('driver', DRIVER), ('schema.json', os.path.join(HERE, 'schema.json')), ('harnesses', rows),
                           ('../../kernel', os.path.join(HERE, '..', '..', 'kernel'))):
            os.symlink(os.path.abspath(real), os.path.join(checkout, link))
        self.driver_path = os.path.join(checkout, 'driver')
        self.name, self.state, self.record = name, os.path.join(self.folder, 'state'), os.path.join(self.folder, 'rec')
        stubs, binary, repo = (os.path.join(self.folder, d) for d in ('stubs', 'bin', 'repos/example/site/docs/agents'))
        for d in (stubs, binary, repo):
            os.makedirs(d, mode=0o700)
        for stub in STUBS:
            with open(os.path.join(stubs, stub), 'w') as f:
                f.write('#!/bin/sh\necho "stub: %s is a no-op stub; no real agent CLI runs here" >&2\nexit 1\n' % stub)
            os.chmod(os.path.join(stubs, stub), 0o700)
        if program:
            os.symlink(fake, os.path.join(binary, program))
        os.symlink(os.path.join(FIXTURES, 'gh'), os.path.join(binary, 'gh'))
        with open(os.path.join(repo, 'fleet.md'), 'w') as f:
            f.write('# Fleet\n\n| Setting | Value |\n| --- | --- |\n| Harness permission mode | `%s` |\n' % mode)
        os.makedirs(self.state, mode=0o700)
        with open(os.open(os.path.join(self.state, 'approvals.json'), os.O_WRONLY | os.O_CREAT, 0o600), 'w') as f:
            json.dump({'example/site': {name: mode}}, f)
        self.tracker = os.path.join(self.folder, 'tracker.json')
        with open(self.tracker, 'w') as f:
            json.dump({'record_authors': ['Example-Bot[bot]'], 'comments': []}, f)
        path = os.pathsep.join([binary, stubs, os.environ.get('PATH', '')])
        self.env = dict(os.environ, PATH=path, KIT_TRACKER=self.tracker, FAKE_REPOS=os.path.join(self.folder, 'repos'),
                        OPENWIZ_LOCAL_STATE=self.state, OPENWIZ_LOCAL_SETTLE='2',
                        FAKE_CLI_LIB=FIXTURES, FAKE_CLI_RECORD=self.record, FAKE_CLI_ENV=','.join(names),
                        FAKE_CLI_HOST=os.path.join(self.folder, 'host'), PYTHONDONTWRITEBYTECODE='1')
        self.host = RunningHubOutsideEveryRun(self.env['FAKE_CLI_HOST'], {'PATH': path})
        self.wrapper = os.path.join(self.folder, 'driver-with-effort')
        with open(self.wrapper, 'w') as f:
            f.write('#!%s\n' % sys.executable + WRAPPER % self.driver_path)
        os.chmod(self.wrapper, 0o700)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.host.close()
        for r in self.records():
            if 'daemon' in r and since(r['daemon'][0]) == r['daemon'][1]:
                os.kill(r['daemon'][0], signal.SIGKILL)
        shutil.rmtree(self.folder, ignore_errors=True)

    def records(self):
        try:
            with open(self.record) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def runs(self):
        return sorted(f for f in os.listdir(self.state) if f.startswith('run-') and f.endswith('.json'))

    def driver(self, cmd, request, program=None, **env):
        p = subprocess.run([program or self.driver_path, cmd], input=json.dumps(request), env=dict(self.env, **env),
                           capture_output=True, text=True, timeout=120)
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, {}

    def start(self, harness=None, effort=None, **env):
        req = {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket', 'harness': harness or self.name,
               'model': 'synthetic-1'}
        if effort is None:
            return self.driver('start', req, **env)
        return self.driver('start', dict(req, effort=effort), self.wrapper, **env)

    def start_refused_starting_nothing(self, says, *start, **env):
        before = self.runs(), len(self.records())
        code, out = self.start(*start, **env)
        return code == 1 and kit.invalid(out, ERROR) is None and says(out) and \
            (self.runs(), len(self.records())) == before

    def kit(self):
        p = subprocess.run([sys.executable, '-I', os.path.join(KIT_DIR, 'kit.py'), '--driver', self.driver_path,
                            '--repo', 'example/site', '--ticket', '7', '--harness', self.name, '--model', 'synthetic-1',
                            '--tracker', self.tracker, '--wait', '15'], env=self.env, capture_output=True, text=True,
                           timeout=300)
        return p.stdout.splitlines()


def until(ready, wait=5):
    end = time.monotonic() + wait
    while not ready() and time.monotonic() < end:
        time.sleep(0.05)
    return ready()


def contains(argv, args):
    return any(argv[i:i + len(args)] == args for i in range(len(argv)))


def check_row(rows, name):
    if not hasattr(local, 'read_row'):
        raise Fail('row.json', 'the driver has no row loader')
    folder = os.path.join(rows, name)
    try:
        row = local.read_row(os.path.join(folder, 'row.json'), name)
    except local.Broken as e:
        if name not in local.HARNESSES:
            with ThrowawayMachine(rows, name, mode='auto') as env:
                if not env.start_refused_starting_nothing(lambda out: name + '/row.json' in out['error']):
                    raise Fail('driver', 'it did not refuse this broken row with a D3 error naming the row file, '
                                         'before starting anything')
        raise Fail('row.json ' + e.args[0], e.args[1])
    if row is None:
        raise Fail('row.json is missing', None)
    return folder, row


def check_folder(folder, row):
    fake = os.path.join(folder, 'fake')
    if not (os.path.isfile(fake) and os.access(fake, os.X_OK)):
        raise Fail('folder', 'it has no executable fake')
    try:
        with open(os.path.join(folder, 'README.md')) as f:
            lines = [line for line in f.read().splitlines() if line.strip()]
    except OSError:
        raise Fail('folder', 'it has no README.md')
    if len(lines) < 2 or not lines[0].startswith('# ') or lines[1] != 'Login: ' + row['login']:
        raise Fail('folder', 'its README does not open with a title, then "Login: " and the row\'s login')
    effort = [line for line in lines if line.startswith('Effort: ')]
    none = isinstance(row['effort'], str)
    if len(effort) != 1 or (effort[0] == 'Effort: none') != none or effort[0].startswith('Effort: none ') or \
            effort[0].startswith('Effort: none:'):
        raise Fail('folder', 'its README needs one line "Effort: none", or "Effort: " and the exact flag or setting, '
                             'as its row says')
    return fake


def check_turns(env, row):
    turns = env.records()
    first = [t for t in turns if t['turn'] == 'first']
    woken = [t for t in turns if t['turn'] == 'woken']
    if len(first) != 1 or len(woken) != 1:
        raise Fail('session', 'the fake recorded %d start turns and %d wake turns, not one of each'
                   % (len(first), len(woken)))
    if any(t['session'] != first[0]['session'] for t in woken):
        raise Fail('session', 'the wake turn got a different session id from the start turn')
    if any(t['env'].get(k) != v for t in turns for k, v in row['env'].items()):
        raise Fail('env', 'a turn did not get the row\'s env')
    daemons = [t['daemon'] for t in turns if 'daemon' in t]
    if row['daemon'] == 'none' and daemons:
        raise Fail('daemon', 'the fake started a background process, but the row declares none')
    if row['daemon'] != 'none' and not daemons:
        raise Fail('daemon', 'the row declares a background process, but its fake started none')
    if not until(lambda: all(since(pid) != at for pid, at in daemons)):
        raise Fail('daemon', 'the background process the row declares still runs after stop')


def check_signed_out(env, row):
    if not row.get('signed_out'):
        return
    code, out = env.start(FAKE_CLI_SIGNED_OUT='1')
    if not (code == 1 and kit.invalid(out, ERROR) is None and 'the harness is not signed in' in out['error'] and
            row['login_command'] in out['next']):
        raise Fail('signed_out', "a signed-out first turn did not fail start with 'the harness is not signed in' "
                                 "and a next naming the row's login_command")


def check_effort(env, row):
    table = row['effort'] if isinstance(row['effort'], dict) else {}
    for value, setting in table.items():
        code, out = env.start(effort=value, FAKE_CLI_RECORD_ONLY='1')
        turns = env.records()
        if code:
            raise Fail('effort', 'a start with effort %s was refused' % value)
        env.driver('stop', out)
        got = turns[-1] if turns else {'argv': [], 'env': {}}
        if not (contains(got['argv'], setting) if isinstance(setting, list) else
                all(got['env'].get(k) == v for k, v in setting['env'].items())):
            raise Fail('effort', 'effort %s did not reach the fake CLI\'s command line or environment' % value)
    unlisted = next(v for v in ('medium', 'unlisted') if v not in table)
    if not env.start_refused_starting_nothing(lambda out: out['next'] == CANT_SET_EFFORT, effort=unlisted, FAKE_CLI_RECORD_ONLY='1'):
        raise Fail('effort', 'a start with an effort the row can\'t take was not refused with the fixed next, '
                             'starting nothing')


def check(rows, name):
    try:
        folder, row = check_row(rows, name)
        fake = check_folder(folder, row)
        names = set(row['env']) | {k for s in row['effort'].values() if isinstance(s, dict) for k in s['env']} \
            if isinstance(row['effort'], dict) else set(row['env'])
        with ThrowawayMachine(rows, name, row['program'], fake, next(iter(row['modes'])), sorted(names)) as env:
            lines = env.kit()
            if lines != PASS:
                raise Fail('kit', next((x for x in lines if not x.startswith('pass ')),
                                       'it gave %d lines' % len(lines)))
            check_turns(env, row)
            check_signed_out(env, row)
            check_effort(env, row)
        test = os.path.join(folder, 'test_row.py')
        if os.path.exists(test):
            p = subprocess.run([sys.executable, '-I', test], cwd=folder, capture_output=True, text=True, timeout=600)
            if p.returncode:
                raise Fail('test_row.py', 'it failed (exit %d)' % p.returncode)
        return 'pass %s: %s' % (name, GOOD)
    except Fail as e:
        return 'fail %s: %s' % (name, ': '.join(x for x in e.args if x))


def check_driver_unknown_harness_and_early_wake(rows):
    found = []
    with ThrowawayMachine(rows, 'example', 'example-cli', os.path.join(rows, 'example', 'fake'), 'auto') as env:
        lists = lambda out: out['next'].startswith('use one of: claude, codex, ') and 'example-none' in out['next']
        found.append(('an unknown harness is a D3 error that lists the built-ins and the row folders, and starts '
                      'nothing', env.start_refused_starting_nothing(lists, 'no-such-row')))
        code, out = env.start(FAKE_CLI_QUIET='1', FAKE_CLI_RECORD_ONLY='1')
        before = len(env.records())
        woke = env.driver('wake', out) if code == 0 else (0, {})
        env.driver('stop', out)
        found.append(('a wake before the reported session id is known is a D3 error that starts nothing',
                      woke[0] == 1 and kit.invalid(woke[1], ERROR) is None and 'no session id' in woke[1]['error']
                      and len(env.records()) == before == 1))
    return ['%s driver: %s' % ('pass' if ok else 'fail', what) for what, ok in found]


def folders(rows):
    return sorted(d for d in os.listdir(rows) if os.path.isdir(os.path.join(rows, d))) if os.path.isdir(rows) else []


def main(argv):
    if argv[:1] == ['--rows'] and len(argv) == 2:
        lines = [check(os.path.abspath(argv[1]), name) for name in folders(argv[1])]
        print('\n'.join(lines))
        return 1 if any(x.startswith('fail ') for x in lines) else 0
    if argv:
        print(USAGE, file=sys.stderr)
        return 2
    planted, ok = os.path.join(FIXTURES, 'rows'), True
    if folders(planted) != sorted(PLANTED):
        print('unexpected: fixtures/rows holds other rows than the planted ones')
        ok = False
    for name in sorted(PLANTED):
        got = check(planted, name)
        print(got)
        if got != PLANTED[name]:
            print('unexpected: planted row %s should give: %s' % (name, PLANTED[name]))
            ok = False
    for line in check_driver_unknown_harness_and_early_wake(planted):
        print(line)
        ok = ok and line.startswith('pass ')
    rows = folders(ROWS)
    print('rows in adapters/local/harnesses: %s' % (', '.join(rows) or 'none yet'))
    for name in rows:
        line = check(ROWS, name)
        print(line)
        ok = ok and line.startswith('pass ')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
