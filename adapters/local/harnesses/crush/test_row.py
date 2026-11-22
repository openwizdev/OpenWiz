#!/usr/bin/env python3
# The crush row's own checks, beyond the runner's: not installed, not signed in, the CRUSH_CLIENT_SERVER override,
# and that stop leaves no process of the run. Only this folder's fake runs; the runner's stubs stay on PATH.
import os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as runner

ROWS = os.path.dirname(HERE)
FAKE = os.path.join(HERE, 'fake')
NOT_INSTALLED = 'install crush on this machine and sign in to it yourself, then start again'
failures = []


def check(what, ok):
    print('%s crush row: %s' % ('pass' if ok else 'fail', what))
    if not ok:
        failures.append(what)


def d3(code, out):
    return code == 1 and runner.kit.invalid(out, runner.ERROR) is None


def processes_under(folder):
    out = subprocess.run(['ps', '-A', '-o', 'pid=', '-o', 'args='], capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if folder in line and 'ps -A' not in line]


def machine(program='crush'):
    return runner.ThrowawayMachine(ROWS, 'crush', program, FAKE if program else None, 'yolo',
                                   ['CRUSH_CLIENT_SERVER'])


# Not installed: a PATH that holds no crush at all, neither the fake nor a stub, so nothing named crush can run.
with machine(None) as env, tempfile.TemporaryDirectory() as bare:
    os.symlink(sys.executable, os.path.join(bare, 'python3'))
    before = env.runs()
    code, out = env.start(PATH=bare)
    check('not installed is a D3 error whose next says to install and sign in, and starts nothing',
          d3(code, out) and out.get('next') == NOT_INSTALLED and 'not installed' in out.get('error', '')
          and env.runs() == before and env.records() == [])

# Not signed in: Crush's own "No providers configured" exit, which the driver's first-turn watch turns into D3.
with machine() as env:
    code, out = env.start(FAKE_CRUSH_SIGNED_OUT='1')
    log = out.get('next', '').partition('read ')[2].partition(', fix what it says there')[0]
    try:
        with open(log) as f:
            said = f.read()
    except OSError:
        said = ''
    check('not signed in is a D3 error whose next points at the log that says how to set up a provider',
          d3(code, out) and 'the first turn ended at once' in out.get('error', '')
          and out['next'] == 'read %s, fix what it says there, then start again' % log
          and "No providers configured - please run 'crush' to set up a provider interactively." in said
          and env.records() == [] and processes_under(env.folder) == [])

# The user's own CRUSH_CLIENT_SERVER=1 would attach the turn to a server outside the run; the row's env wins.
with machine() as env:
    code, out = env.start(CRUSH_CLIENT_SERVER='1')
    started = code == 0 and 'run' in out
    first = runner.until(lambda: len(env.records()) == 1) and env.records()[0]
    alive = runner.until(lambda: processes_under(env.folder) != [])
    woke = env.driver('wake', out) if started else (1, {})
    second = runner.until(lambda: len(env.records()) == 2) and env.records()[1]
    code_stop, stopped = env.driver('stop', out) if started else (1, {})
    gone = runner.until(lambda: processes_under(env.folder) == [])
    check('a turn gets CRUSH_CLIENT_SERVER=0 over the user\'s own setting, and attaches to no outside server',
          started and bool(first) and first['env'] == {'CRUSH_CLIENT_SERVER': '0'} and 'daemon' not in first)
    check('the wake gets the session id crush logged to stderr at start',
          started and bool(first) and woke[0] == 0 and bool(second) and second['turn'] == 'woken'
          and second['session'] == first['session'] and second['argv'][3:5] == ['--session', first['session']])
    check('stop leaves no process of the run', started and alive and code_stop == 0
          and stopped == {'run': out['run'], 'stopped': True} and gone)

sys.exit(1 if failures else 0)
