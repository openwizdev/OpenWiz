#!/usr/bin/env python3
import contextlib, importlib.machinery, importlib.util, json, os, re, shlex, shutil, signal, socket, subprocess, sys, tempfile, threading, time

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
         'kiro-cli junie amp agy oz sculpt hermes acpx droid boat pane openclaw kiro cn aider').split()
CANT_SET_EFFORT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster "
                   "to run it at the host's default")
PASS = ['pass version: openwiz:records v1, and the schema is driver v1',
        'pass start: the run posted builder status note 1; effort: medium reached a process the run started',
        'pass wake: the run edited builder status note 1',
        'pass stop: the run ended, and a wake after it is refused',
        'pass token: no login or token passed through the driver']
GOOD = 'the contract, the folder, the kit\'s five checks, and the session, env, background process and effort checks'
PLANTED = {
    'example': 'pass example: ' + GOOD,
    'example-none': 'pass example-none: ' + GOOD,
    'effort-crowded': 'pass effort-crowded: ' + GOOD,
    'signed-out-json': 'pass signed-out-json: ' + GOOD,
    'login-env-good': 'pass login-env-good: ' + GOOD,
    'login-env-lowercase': 'fail login-env-lowercase: row.json login_env: it is not one variable name: a capital, then '
                           '1 to 63 capitals, digits or _',
    'login-env-value': 'fail login-env-value: row.json login_env: it looks like a credential; login_env names a '
                       'variable, never its value',
    'login-env-no-command': 'fail login-env-no-command: row.json login_command: a row with login_env names the '
                            'command the user runs to sign in',
    'login-env-too-long': "fail login-env-too-long: row.json login_env: with it, the not-signed-in next passes D3's "
                          '300 characters; shorten login_command, login_env or program',
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
    'row-commands': 'pass row-commands: ' + GOOD,
    'precheck-other-program': "fail precheck-other-program: row.json precheck: it runs another program; it starts with "
                              "the row's program",
    'stop-other-program': "fail stop-other-program: row.json stop: it runs another program; it starts with the row's "
                          "program",
    'precheck-placeholder': 'fail precheck-placeholder: row.json precheck: it takes only {model} and {effort}, each '
                            'once and as a whole argument',
    'stop-placeholder': 'fail stop-placeholder: row.json stop: it takes only {session}, once and as a whole argument',
    'stop-no-session': "fail stop-no-session: row.json stop: it has no {session}, so it could reach other runs' "
                       "sessions",
    'precheck-credential': 'fail precheck-credential: row.json precheck: a fixed argument looks like a credential; a '
                           'row holds no login, key or token',
    'precheck-matches-anything': 'fail precheck-matches-anything: row.json precheck: its match pattern matches empty '
                                 'output, so it would pass anything',
    'precheck-unmatched': "fail precheck-unmatched: precheck: a start with the row's own fake was refused by its "
                          "precheck",
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
SHORT_COMMANDS = WRAPPER.replace("t.START['effort'] = t.EFFORT", 't.PRECHECK_SECONDS = t.STOP_SECONDS = 1')
CALLS = '''import json, os, sys, time
sys.dont_write_bytecode = True
folder, fake = %r, %r


def alive(turn):
    if not os.path.isdir('/proc/self'):
        try:
            os.kill(turn['supervisor'], 0)
            return True
        except OSError:
            return False
    try:
        with open('/proc/%%d/stat' %% turn['supervisor']) as f:
            fields = f.read().rpartition(')')[2].split()
    except OSError:
        return False
    return fields[0] != 'Z' and int(fields[19]) == turn['supervisor_since']


def turns_alive():
    found = []
    for name in sorted(os.listdir(os.path.join(folder, 'state'))):
        if name.startswith('run-') and name.endswith('.json'):
            try:
                with open(os.path.join(folder, 'state', name)) as f:
                    found += [alive(t) for t in json.load(f)['turns']]
            except (OSError, ValueError, KeyError):
                continue
    return any(found)


try:
    with open(os.path.join(folder, 'control')) as f:
        control = f.read()
except FileNotFoundError:
    control = ''
args = sys.argv[1:]
names = [n for n in os.environ.get('FAKE_CLI_ENV', '').split(',') if n]
with open(os.open(os.path.join(folder, 'calls'), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), 'w') as f:
    f.write(json.dumps({'argv': args, 'env': {n: os.environ.get(n) for n in names}, 'turns_alive': turns_alive(),
                        'cwd': os.getcwd(), 'pid': os.getpid()}) + '\\n')
if control and args[:1] != ['run']:
    print('synthetic %%s output 7d3a' %% control, flush=True)
    if control == 'effort':
        print('effort %%s for %%s' %% (args[-1], args[1]), flush=True)
    if control == 'signed-out-elsewhere':
        print('warning: not logged in to another provider\\nmodel %%s ready' %% args[1], flush=True)
    if control == 'hang':
        time.sleep(300)
    sys.exit(1 if control == 'exit' else 0)
os.execv(fake, [fake] + args)
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


def effort_cell(said):
    flags = [s.split() for s in re.findall(r'`(-[^` ]* [a-z][a-z0-9-]*)`', said)]
    words = list(dict.fromkeys(word for flag, word in flags if flag == flags[0][0]))
    if not words or '<' in said:
        return "can't (its README says none)" if said == 'none' else said
    return '`%s <level>`, for %s' % (flags[0][0], ' and '.join([', '.join(words[:-1])] * (len(words) > 1) + words[-1:]))


class ThrowawayMachine:

    def __init__(self, rows, name, program=None, fake=None, mode=None, names=(), clone_says=None):
        self.folder = tempfile.mkdtemp(prefix='rows-')
        checkout = os.path.join(self.folder, 'checkout', 'adapters', 'local')
        os.makedirs(checkout)
        for link, real in (('driver', DRIVER), ('schema.json', os.path.join(HERE, 'schema.json')), ('harnesses', rows),
                           ('../../kernel', os.path.join(HERE, '..', '..', 'kernel'))):
            os.symlink(os.path.abspath(real), os.path.join(checkout, link))
        self.driver_path = os.path.join(checkout, 'driver')
        self.readmes = os.path.join(HERE, 'README.md'), os.path.join(rows, name, 'README.md')
        self.name, self.state, self.record = name, os.path.join(self.folder, 'state'), os.path.join(self.folder, 'rec')
        stubs, binary, repo = (os.path.join(self.folder, d) for d in ('stubs', 'bin', 'repos/example/site/docs/agents'))
        for d in (stubs, binary, repo):
            os.makedirs(d, mode=0o700)
        for stub in STUBS:
            with open(os.path.join(stubs, stub), 'w') as f:
                f.write('#!/bin/sh\necho "stub: %s is a no-op stub; no real agent CLI runs here" >&2\nexit 1\n' % stub)
            os.chmod(os.path.join(stubs, stub), 0o700)
        if program:
            with open(os.path.join(binary, program), 'w') as f:
                f.write('#!%s -I\n' % sys.executable + CALLS % (self.folder, fake))
            os.chmod(os.path.join(binary, program), 0o700)
        if clone_says is None:
            os.symlink(os.path.join(FIXTURES, 'gh'), os.path.join(binary, 'gh'))
        else:
            with open(os.path.join(binary, 'gh'), 'w') as f:
                f.write('#!/bin/sh\necho %s\nexec %s "$@"\n' % (shlex.quote(clone_says),
                                                                shlex.quote(os.path.join(FIXTURES, 'gh'))))
            os.chmod(os.path.join(binary, 'gh'), 0o700)
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

    def calls(self):
        try:
            with open(os.path.join(self.folder, 'calls')) as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def control(self, what):
        with open(os.path.join(self.folder, 'control'), 'w') as f:
            f.write(what)

    def forget_calls(self):
        for name in ('calls', 'rec', 'control'):
            with contextlib.suppress(FileNotFoundError):
                os.remove(os.path.join(self.folder, name))

    def short_driver(self):
        path = os.path.join(self.folder, 'driver-short-commands')
        with open(path, 'w') as f:
            f.write('#!%s\n' % sys.executable + SHORT_COMMANDS % self.driver_path)
        os.chmod(path, 0o700)
        return path

    def raw(self, cmd, request, program=None, **env):
        try:
            p = subprocess.run([program or self.driver_path, cmd], input=json.dumps(request),
                               env=dict(self.env, **env), capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return None, {}, ''
        try:
            return p.returncode, json.loads(p.stdout), p.stdout + p.stderr
        except ValueError:
            return p.returncode, {}, p.stdout + p.stderr

    def log(self, run):
        try:
            with open(os.path.join(self.state, run + '.log'), errors='replace') as f:
                return f.read()
        except OSError:
            return ''

    def state_of(self, run):
        with open(os.path.join(self.state, run + '.json')) as f:
            return json.load(f)

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

    def stage_effort(self):
        said = []
        for readme in self.readmes:
            with open(readme) as f:
                said.append(next(line for line in f.read().splitlines() if line.startswith('Effort: ')))
        with open(os.path.join(os.path.dirname(self.driver_path), 'README.md'), 'w') as f:
            f.write('%s\n\n| Harness | Effort |\n| --- | --- |\n| `%s` | %s |\n' % (
                said[0], self.name, effort_cell(said[1][len('Effort: '):])))

    def kit(self):
        self.stage_effort()
        p = subprocess.run([sys.executable, '-I', os.path.join(KIT_DIR, 'kit.py'), '--driver', self.driver_path,
                            '--repo', 'example/site', '--ticket', '7', '--harness', self.name, '--model', 'synthetic-1',
                            '--tracker', self.tracker, '--wait', '15'], env=self.env, capture_output=True, text=True,
                           timeout=300)
        return p.stdout.splitlines()


def passes(name, row):
    if isinstance(row['effort'], str):
        effort = 'refused for %s with the refusal text, as the README says' % name
    elif 'medium' in row['effort']:
        return PASS
    else:
        effort = 'refused medium with the refusal text, a word its README does not list for %s' % name
    return [PASS[0], PASS[1].partition('; effort: ')[0] + '; effort: ' + effort] + PASS[2:]


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


def filled(args, values):
    return [values.get(a, a) for a in args]


def names_effort(row):
    return 'precheck' in row and '{effort}' in json.dumps(row['precheck'])


def check_precheck(env, row):
    if 'precheck' not in row:
        return
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
    if code == 0:
        env.driver('stop', out)
    env.forget_calls()
    if code:
        raise Fail('precheck', "a start with the row's own fake was refused by its precheck")


def check_commands(env, row):
    turns, calls = env.records(), env.calls()
    session = turns[0]['session']
    want = [t['argv'] for t in turns]
    if 'precheck' in row and not names_effort(row):
        want.insert(0, filled(row['precheck']['run'][1:], {'{model}': 'synthetic-1'}))
    if 'stop' in row:
        want.append(filled(row['stop'][1:], {'{session}': session}))
    if [c['argv'] for c in calls] != want:
        raise Fail('commands', 'the program ran %d times, not exactly once for each turn%s' % (
            len(calls), ''.join(', ' + f for f in ('precheck', 'stop') if f in row)))
    if 'stop' in row and not calls[-1]['turns_alive']:
        raise Fail('stop', "the row's stop ran after the turns had ended, not before the process tree was ended")
    if any(c['env'].get(k) != v for c in calls for k, v in row['env'].items()):
        raise Fail('env', "the row's precheck or stop did not get the row's env")


def check_signed_out(env, row):
    if not row.get('signed_out'):
        return
    code, out = env.start(FAKE_CLI_SIGNED_OUT='1')
    if not (code == 1 and kit.invalid(out, ERROR) is None and 'the harness is not signed in' in out['error'] and
            row['login_command'] in out['next']):
        raise Fail('signed_out', "a signed-out first turn did not fail start with 'the harness is not signed in' "
                                 "and a next naming the row's login_command")
    if 'login_env' in row:
        check_login_env(env, row)


def check_login_env(env, row):
    # PRIVACY: a canary value under the row's login_env must reach the CLI only through the environment it inherits.
    name, value = row['login_env'], 'synthetic-canary-0000-2918'
    want = 'sign in with %s, or set %s for %s yourself, then start again' % (row['login_command'], name, row['program'])
    code, said = env.start(FAKE_CLI_SIGNED_OUT='1', **{name: value})
    if not (said.get('next') == want or said.get('next', '').startswith(want + '; ')):
        raise Fail('login_env', 'a signed-out first turn\'s next does not name both sign-in routes: ' + want)
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_ENV=name, **{name: value})
    env.driver('stop', out)
    turns = env.records()
    saved = []
    for folder, _, files in os.walk(env.state):
        for f in files:
            with open(os.path.join(folder, f), 'rb') as g:
                saved.append(g.read())
    if code or not turns or turns[-1]['env'].get(name) != value:
        raise Fail('login_env', "the CLI did not get the login_env variable from the driver's environment")
    if value in json.dumps([said, out]) or any(value.encode() in b for b in saved) or \
            any(value in a for t in turns for a in t['argv']):
        raise Fail('login_env', "the login_env variable's value reached an answer, a state file or argv")


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
    unlisted = next(v for v in ['unlisted'] + ['unlisted-%d' % i for i in range(len(table))] if v not in table)
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
            check_precheck(env, row)
            lines = env.kit()
            if lines != passes(name, row):
                raise Fail('kit', next((x for x in lines if not x.startswith('pass ')),
                                       'it gave %d lines' % len(lines)))
            check_turns(env, row)
            check_commands(env, row)
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


@contextlib.contextmanager
def example_variant(name, drop=(), **fields):
    with tempfile.TemporaryDirectory(prefix='variant-') as rows:
        folder = os.path.join(rows, name)
        shutil.copytree(os.path.join(FIXTURES, 'rows', 'example'), folder)
        with open(os.path.join(folder, 'row.json')) as f:
            row = json.load(f)
        row.update(fields)
        for key in drop:
            del row[key]
        with open(os.path.join(folder, 'row.json'), 'w') as f:
            json.dump(row, f)
        yield rows


def broken_rows_name_their_file(planted):
    long = 'a' * 60
    with ThrowawayMachine(planted, 'row-missing', mode='auto') as env:
        ok = env.start_refused_starting_nothing(lambda out: 'harnesses/row-missing/row.json' in out['error'])
    for name, drop, fields in (('example', (), {'harness': ['example']}), (long, ('login',), {'harness': long})):
        with example_variant(name, drop, **fields) as rows, ThrowawayMachine(rows, name, mode='auto') as env:
            ok = env.start_refused_starting_nothing(
                lambda out: 'harnesses/%s/row.json' % name in out['error'] and 'harnesses/%s/row.json' % name
                in out['next']) and ok
    return ok


def rows_read_first_turn_output(planted):
    example = (planted, 'example', 'example-cli', os.path.join(planted, 'example', 'fake'), 'auto')
    with ThrowawayMachine(*example, clone_says='{"session": {"id": "clone-0000"}}') as env:
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
        woke = env.driver('wake', out) if code == 0 else (1, {})
        env.driver('stop', out)
        turns = env.records()
        ok = woke[0] == 0 and len(turns) == 2 and turns[1]['session'] == turns[0]['session'] != 'clone-0000'
    with ThrowawayMachine(*example, clone_says='Error: not authenticated') as env:
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
        env.driver('stop', out)
        ok = ok and code == 0
    with ThrowawayMachine(*example) as env:
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_PRELUDE='{"session": {"id": null}}')
        woke = env.driver('wake', out) if code == 0 else (0, {})
        env.driver('stop', out)
        ok = ok and woke[0] == 1 and 'no session id' in woke[1].get('error', '') and len(env.records()) == 1
    return ok


def effort_checked_first_with_its_grammar(planted):
    with ThrowawayMachine(planted, 'example', mode='auto') as env:
        ok = env.start_refused_starting_nothing(lambda out: out['next'] == CANT_SET_EFFORT, effort='medium')
    with example_variant('example', effort={'High': ['--effort', 'high']}) as rows, \
            ThrowawayMachine(rows, 'example', mode='auto') as env:
        ok = env.start_refused_starting_nothing(lambda out: 'harnesses/example/row.json' in out['error'] and '(effort:' in out['error']) and ok
    return ok


def supervisor_keeps_the_drivers_environment(planted):
    with ThrowawayMachine(planted, 'example', 'example-cli', os.path.join(planted, 'example', 'fake'), 'auto',
                          ('EXAMPLE_CLI_BACKEND', 'EXAMPLE_CLI_THINKING')) as env:
        code, out = env.start(effort='max', FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_LINGER='1')
        try:
            with open(os.path.join(env.state, out['run'] + '.json')) as f:
                supervisor = json.load(f)['turns'][0]['supervisor']
            with open('/proc/%d/environ' % supervisor, 'rb') as f:
                names = {v.partition(b'=')[0] for v in f.read().split(b'\0')}
        except (OSError, KeyError, ValueError):
            names = None
        env.driver('stop', out)
        turns = env.records()
    return code == 0 and names is not None and not names & {b'EXAMPLE_CLI_BACKEND', b'EXAMPLE_CLI_THINKING'} and \
        len(turns) == 1 and turns[0]['env'] == {'EXAMPLE_CLI_BACKEND': 'local', 'EXAMPLE_CLI_THINKING': 'max'}


def credential_arguments_refused(planted):
    example = local.read_row(os.path.join(planted, 'example', 'row.json'), 'example')
    value, ok = 'synthetic-0000', True
    for field, fields in (
            ('modes', {'modes': dict(example['modes'], auto=['--yes', '--token=' + value])}),
            ('modes', {'modes': dict(example['modes'], auto=['--api-key', value])}),
            ('start', {'start': ['password=' + value] + example['start']}),
            ('effort', {'effort': dict(example['effort'], low=['--effort', 'low', '--auth', value])})):
        with example_variant('example', **fields) as rows, ThrowawayMachine(rows, 'example', mode='auto') as env:
            ok = env.start_refused_starting_nothing(
                lambda out: 'harnesses/example/row.json' in out['error'] and '(%s:' % field in out['error'] and
                value not in json.dumps(out)) and ok
    return ok


def busy_wake_needs_no_write(env):
    before = len(env.records())
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_LINGER='1')
    if code != 0 or not until(lambda: len(env.records()) == before + 1):
        return False
    path = os.path.join(env.state, out['run'] + '.json')
    first = env.driver('wake', out)
    with open(path) as f:
        kept = json.load(f)['session']
    os.mkdir(path + '.new')
    try:
        again = env.driver('wake', out)
    finally:
        os.rmdir(path + '.new')
        env.driver('stop', out)
    return first == again == (0, {'run': out['run'], 'woke': True}) and kept == env.records()[-1]['session'] and \
        len(env.records()) == before + 1


def commands_machine(planted, rows=None, name='row-commands', program='row-commands-cli'):
    return ThrowawayMachine(rows or planted, name, program, os.path.join(planted, name, 'fake'), 'auto',
                            ('ROW_COMMANDS_CLI_BACKEND', 'EXAMPLE_CLI_BACKEND'))


def gone(pid):
    return until(lambda: since(pid) is None)


def precheck_refusals_start_nothing(planted):
    ok = True
    for control, why in (('exit', 'it exited 1'), ('mismatch', "its output did not match the row's pattern"),
                         ('hang', 'it ran past its 1-second limit')):
        with commands_machine(planted) as env:
            env.control(control)
            code, out, said = env.raw('start', {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket',
                                                'harness': 'row-commands', 'model': 'synthetic-1'}, env.short_driver())
            run = next((r[:-5] for r in env.runs()), None)
            calls = env.calls()
            state = env.state_of(run) if run else {}
            ok = (code == 1 and kit.invalid(out, ERROR) is None and why in out['error'] and
                  'nothing was started' in out['error'] and env.records() == [] and len(calls) == 1 and
                  calls[0]['argv'] == ['models', 'synthetic-1', '--verbose'] and
                  calls[0]['env'].get('ROW_COMMANDS_CLI_BACKEND') == 'local' and
                  not calls[0]['cwd'].startswith(os.path.join(env.state, 'work')) and
                  state.get('turns') == [] and state.get('stopped') is True and
                  '7d3a' in env.log(run) and '7d3a' not in said and gone(calls[0]['pid'])) and ok
    return ok


def precheck_output_is_not_the_turns(planted):
    with commands_machine(planted) as env:
        env.control('signed-out-elsewhere')
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
        if code == 0:
            env.driver('stop', out)
        calls = env.calls()
    return code == 0 and [c['argv'][:1] for c in calls] == [['models'], ['run'], ['stop']]


def precheck_effort_skipped_and_escaped(planted):
    check = {'run': ['row-commands-cli', 'models', '{model}', '--effort', '{effort}'],
             'match': '^effort {effort} for {model}$'}
    with tempfile.TemporaryDirectory(prefix='variant-') as rows:
        shutil.copytree(os.path.join(planted, 'row-commands'), os.path.join(rows, 'row-commands'))
        with open(os.path.join(rows, 'row-commands', 'row.json')) as f:
            row = json.load(f)
        with open(os.path.join(rows, 'row-commands', 'row.json'), 'w') as f:
            json.dump(dict(row, precheck=check), f)
        with commands_machine(planted, rows) as env:
            env.control('effort')
            plain_code, plain = env.start(FAKE_CLI_RECORD_ONLY='1')
            skipped = [c['argv'][:1] for c in env.calls()] == [['run']]
            env.driver('stop', plain)
            env.forget_calls()
            env.control('effort')
            code, out = env.driver('start', {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket',
                                             'harness': 'row-commands', 'model': 'synthetic+1', 'effort': 'high'},
                                   env.wrapper, FAKE_CLI_RECORD_ONLY='1')
            env.driver('stop', out)
            calls = env.calls()
    return plain_code == 0 and skipped and code == 0 and calls[0]['argv'] == ['models', 'synthetic+1', '--effort', 'high'] \
        and [c['argv'][:1] for c in calls] == [['models'], ['run'], ['stop']]


def failing_stop_still_ends_the_tree(planted):
    ok = True
    for control, why in (('exit', "the row's stop exited 1"),
                         ('hang', "the row's stop ran past its 1-second limit")):
        with commands_machine(planted) as env:
            code, out = env.start()
            if code:
                return False
            state = env.state_of(out['run'])
            env.control(control)
            stopped, answer, said = env.raw('stop', out, env.short_driver())
            calls = env.calls()
            ok = (stopped == 0 and answer == {'run': out['run'], 'stopped': True} and why in said and
                  "the driver still ended the run's process tree" in said and '7d3a' not in said and
                  '7d3a' in env.log(out['run']) and why in env.log(out['run']) and
                  calls[-1]['argv'] == ['stop', '--session', state['session']] and calls[-1]['turns_alive'] and
                  gone(calls[-1]['pid']) and all(gone(t['supervisor']) for t in state['turns'])) and ok
    return ok


def stop_uses_only_the_runs_own_session(planted):
    stop = ['example-cli', 'stop', '--session', '{session}']
    ok = True
    with example_variant('example', stop=stop) as rows:
        for prelude, quiet, want in ((None, None, True), ('{"session": {"id": "--all"}}', '1', False),
                                     (None, '1', False)):
            with commands_machine(planted, rows, 'example', 'example-cli') as env:
                env.control('quiet')
                extra = dict(FAKE_CLI_PRELUDE=prelude) if prelude else {}
                code, out = env.start(FAKE_CLI_QUIET=quiet or '', **extra)
                state = env.state_of(out['run']) if code == 0 else {'turns': []}
                stopped, answer, said = env.raw('stop', out)
                session = env.records()[0]['session'] if env.records() else None
                calls = [c['argv'] for c in env.calls() if c['argv'][:1] == ['stop']]
                ok = (code == 0 and stopped == 0 and all(gone(t['supervisor']) for t in state['turns']) and
                      (calls == [['stop', '--session', session]] if want else
                       calls == [] and "the row's stop was skipped: the run has no session id it can pass" in said)) \
                    and ok
    return ok


def row_commands_keep_the_drivers_environment(planted):
    before = dict(os.environ)
    if not hasattr(local, 'row_command'):
        return False
    with tempfile.TemporaryDirectory(prefix='env-') as folder:
        probe = os.path.join(folder, 'probe')
        with open(probe, 'w') as f:
            f.write('#!/bin/sh\nprintf "%%s" "$ROW_COMMANDS_CLI_BACKEND" > %s\n' % shlex.quote(probe + '.out'))
        os.chmod(probe, 0o700)
        saved, local.STATE = local.STATE, folder
        try:
            result = local.row_command('run-000000000000', [probe], {'ROW_COMMANDS_CLI_BACKEND': 'local'}, 5)
        finally:
            local.STATE = saved
        try:
            with open(probe + '.out') as f:
                got = f.read()
        except OSError:
            got = None
    return result[0] == 0 and got == 'local' and dict(os.environ) == before


def precheck_that_cannot_run_is_refused(planted):
    with open(os.path.join(planted, 'row-commands', 'row.json')) as f:
        state = {'request': {'harness': 'row-commands', 'model': 'synthetic-1'}, 'program': 'row-commands-cli',
                 'row': json.load(f)}
    saved = local.row_command
    local.row_command = lambda *_: (_ for _ in ()).throw(OSError('no temporary folder: synthetic'))
    try:
        local.precheck('run-000000000000', state)
        return False
    except local.Refused as e:
        return 'it could not run; nothing was started' in str(e.args[0])
    except OSError:
        return False
    finally:
        local.row_command = saved


def row_command_ended_when_its_watch_fails(planted):
    if not os.path.isdir('/proc/self'):
        return True
    looks, saved = [], (local.STATE, local.LINUX, local.ps)

    def ps_fails_on_its_third_look(*args):
        looks.append(args)
        if len(looks) > 2:
            raise OSError('ps did not run: synthetic')
        return saved[2](*args)

    with tempfile.TemporaryDirectory(prefix='watch-') as folder:
        pid = os.path.join(folder, 'pid')
        local.STATE, local.LINUX, local.ps = folder, False, ps_fails_on_its_third_look
        try:
            local.row_command('run-000000000000', ['/bin/sh', '-c', 'echo $$ > %s; exec sleep 300' % shlex.quote(pid)],
                              {}, 30)
            raised = False
        except OSError:
            raised = True
        finally:
            local.STATE, local.LINUX, local.ps = saved
        with open(pid) as f:
            child = int(f.read())
    return raised and len(looks) == 3 and gone(child)


def longest_login_env_fits(planted):
    good = local.read_row(os.path.join(planted, 'login-env-good', 'row.json'), 'login-env-good')
    try:
        local.check_row(dict(good, login_env='LOGIN_ENV_GOOD_CLI_LOGIN', env={'LOGIN_ENV_GOOD_CLI_LOGIN': 'local'}),
                        'login-env-good')
        in_env = False
    except local.Broken as e:
        in_env = e.args == ('login_env', "the row's env sets it; only the user sets it, for the CLI")
    with tempfile.TemporaryDirectory(prefix='variant-') as rows:
        folder = os.path.join(rows, 'login-env-good')
        shutil.copytree(os.path.join(planted, 'login-env-good'), folder)
        row = dict(good)
        row.update(program='p' * 60, login_env='K' * 64, login_command='c' * 122)
        with open(os.path.join(folder, 'row.json'), 'w') as f:
            json.dump(row, f)
        with ThrowawayMachine(rows, 'login-env-good', row['program'], os.path.join(folder, 'fake'),
                              'workspace-write') as env:
            code, out = env.start(FAKE_CLI_SIGNED_OUT='1')
        row['login_command'] += 'c'
        with open(os.path.join(folder, 'row.json'), 'w') as f:
            json.dump(row, f)
        with ThrowawayMachine(rows, 'login-env-good', mode='workspace-write') as env:
            longer = env.start_refused_starting_nothing(lambda out: '(login_env:' in out['error'])
    return code == 1 and kit.invalid(out, ERROR) is None and \
        out['next'].startswith('sign in with %s, or set %s for %s yourself, then start again' % (
            'c' * 122, 'K' * 64, 'p' * 60)) and longer and in_env


def check_driver(rows):
    found = [("a broken row's D3 error names its row file and fits the error schema: a row folder with no row.json, "
              "a harness that is not a string, and a 60-character harness with a missing field",
              broken_rows_name_their_file(rows)),
             ("a row's session id and signed_out patterns are read from its first turn's output, never the clone's, "
              "and the first line that has the session's JSON path decides it", rows_read_first_turn_output(rows)),
             ("an effort the row can't take is refused before the driver looks for its program, and a row's effort "
              "ids are lower-case words of up to 20 characters", effort_checked_first_with_its_grammar(rows)),
             ("a row whose fixed arguments in start, wake, modes or effort look like a credential, joined or as a "
              "flag and its value, is refused naming only its field", credential_arguments_refused(rows)),
             ("a precheck that exits non-zero, does not match or runs past its timeout is a D3 refusal that starts "
              "no turn, runs outside the clone with the row's env, and keeps its output in the run's log only",
              precheck_refusals_start_nothing(rows)),
             ("a precheck that cannot open the run's log or its folder is the same D3 refusal, so its run is saved "
              "as stopped", precheck_that_cannot_run_is_refused(rows)),
             ("a precheck's output is left out of the first turn's sign-in check, so a first turn that ends at once "
              "with exit 0 still starts", precheck_output_is_not_the_turns(rows)),
             ("a precheck that names {effort} is skipped for a start without an effort, and its model and effort "
              "fill whole arguments and match as literal text", precheck_effort_skipped_and_escaped(rows)),
             ("a row's stop runs with the run's session while the turns still run, and a failing or hanging stop "
              "still ends the process tree, saying so in fixed words with its output in the run's log only",
              failing_stop_still_ends_the_tree(rows)),
             ("a row's stop gets only its run's own reported session, and is skipped, still ending the tree, when "
              "there is none or it starts with a dash", stop_uses_only_the_runs_own_session(rows)),
             ("a precheck's or stop's env reaches only its own process, never the driver's environment",
              row_commands_keep_the_drivers_environment(rows)),
             ("a precheck or stop is still ended when the driver's watch on it fails, as when ps fails on macOS",
              row_command_ended_when_its_watch_fails(rows)),
             ("the longest valid login_env row's not-signed-in next fits D3's 300 characters, one character more "
              "refuses the row, and so does a row whose env sets its login_env", longest_login_env_fits(rows))]
    if os.path.isdir('/proc/self'):
        found.append(("a row's env and effort setting reach only the harness, never the turn's supervisor",
                      supervisor_keeps_the_drivers_environment(rows)))
    with ThrowawayMachine(rows, 'example', 'example-cli', os.path.join(rows, 'example', 'fake'), 'auto') as env:
        lists = lambda out: out['next'].startswith('use one of: claude, codex, ') and 'example-none' in out['next']
        found.append(('an unknown harness is a D3 error that lists the built-ins and the row folders, and starts '
                      'nothing', env.start_refused_starting_nothing(lists, 'no-such-row')))
        early = []
        for linger in ('', '1'):
            code, out = env.start(FAKE_CLI_QUIET='1', FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_LINGER=linger)
            before = len(env.records())
            woke = env.driver('wake', out) if code == 0 else (0, {})
            env.driver('stop', out)
            early.append(woke[0] == 1 and kit.invalid(woke[1], ERROR) is None and 'no session id' in woke[1]['error']
                         and len(env.records()) == before == len(early) + 1)
        found.append(('a wake before the reported session id is known is a D3 error that starts nothing, whether '
                      'the first turn has ended or still runs', all(early)))
        found.append(("a wake while the first turn runs saves its newly reported session id, and once it is saved "
                      "answers woke with no state write and starts nothing", busy_wake_needs_no_write(env)))
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
    for line in check_driver(planted):
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
