#!/usr/bin/env python3
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


# SAFETY: this PATH holds no crush at all, neither the fake nor a stub, so nothing named crush can run.
with machine(None) as env, tempfile.TemporaryDirectory() as bare:
    os.symlink(sys.executable, os.path.join(bare, 'python3'))
    before = env.runs()
    code, out = env.start(PATH=bare)
    check('not installed is a D3 error whose next says to install and sign in, and starts nothing',
          d3(code, out) and out.get('next') == NOT_INSTALLED and 'not installed' in out.get('error', '')
          and env.runs() == before and env.records() == [])

with machine() as env:
    code, out = env.start(FAKE_CLI_SIGNED_OUT='1')
    log = out.get('next', '').partition('; ')[2].partition(' has the turn')[0]
    try:
        with open(log) as f:
            said = f.read()
    except OSError:
        said = ''
    check('not signed in is a D3 error whose next says to sign in with crush login',
          d3(code, out) and 'the harness is not signed in' in out.get('error', '')
          and out['next'].startswith('sign in yourself with `crush login` on this machine, then start again')
          and "No providers configured - please run 'crush' to set up a provider interactively." in said
          and env.records() == [] and processes_under(env.folder) == [])

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

# A user with both OpenRouter and Anthropic configured: Crush reads a first segment naming a configured provider as
# a filter, so the README's example names its provider in full to find exactly one model.
OPENROUTER_SONNET = 'openrouter/anthropic/claude-sonnet-4.6'
BOTH = {'FAKE_CRUSH_PROVIDERS': 'openrouter,anthropic'}
with machine() as env:
    code, out = env.driver('start', {'repository': 'example/site', 'ticket': 7, 'skill': 'build-ticket',
                                     'harness': 'crush', 'model': OPENROUTER_SONNET}, **BOTH)
    started = code == 0 and 'run' in out
    first = runner.until(lambda: len(env.records()) == 1) and env.records()[0]
    woke = env.driver('wake', out, **BOTH) if started else (1, {})
    second = runner.until(lambda: len(env.records()) == 2) and env.records()[1]
    if started:
        env.driver('stop', out)
    check('with OpenRouter and Anthropic configured, %s reaches crush --model unchanged and runs, on start and wake'
          % OPENROUTER_SONNET,
          started and bool(first) and woke[0] == 0 and bool(second)
          and first['argv'][3:5] == ['--model', OPENROUTER_SONNET]
          and second['argv'][5:7] == ['--model', OPENROUTER_SONNET])

sys.exit(1 if failures else 0)
