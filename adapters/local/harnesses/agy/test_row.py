#!/usr/bin/env python3
import os, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as th

ROWS, NAME = os.path.dirname(HERE), os.path.basename(HERE)
FAKE = os.path.join(HERE, 'fake')
HEAD = ['--output-format', 'stream-json', '--model', 'synthetic-1']
MODES = {'auto': ['--mode=auto'], 'accept-edits': ['--mode=accept-edits'],
         'dangerously-skip-permissions': ['--dangerously-skip-permissions'], 'settings': []}
failed = []


def check(what, ok):
    print('%s %s: %s' % ('pass' if ok else 'fail', NAME, what))
    if not ok:
        failed.append(what)


def fake_exit(args, **env):
    full = dict(os.environ, FAKE_CLI_LIB=th.FIXTURES, **dict({'AGY_CLI_DISABLE_AUTO_UPDATE': 'true'}, **env))
    return subprocess.run([sys.executable, FAKE] + args, env=full, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=30).returncode


def without_agy(path):
    return os.pathsep.join(d for d in path.split(os.pathsep) if not os.path.exists(os.path.join(d, 'agy')))


def log(env):
    if not env.runs():
        return ''
    with open(os.path.join(env.state, env.runs()[0][:-len('.json')] + '.log')) as f:
        return f.read()


def stop_all(env):
    for run in env.runs():
        env.driver('stop', {'run': run[:-len('.json')]})


woken = 'You were woken with the build-ticket skill'
undocumented = [
    ('--mode=default, a mode agy --mode does not take', ['-p', 'x', '--output-format', 'stream-json', '--model', 'm',
                                                        '--mode=default']),
    ('--permission-mode, which agy does not have', ['-p', 'x', '--output-format', 'stream-json', '--model', 'm',
                                                     '--permission-mode', 'auto']),
    ('--effort turbo, not an effort level', ['-p', 'x', '--output-format', 'stream-json', '--model', 'm',
                                             '--effort', 'turbo']),
    ('--output-format yaml, not an output format', ['-p', 'x', '--output-format', 'yaml', '--model', 'm']),
    ('--input-format stream-json, which drops a -p prompt', ['-p', 'x', '--input-format', 'stream-json',
                                                             '--output-format', 'stream-json', '--model', 'm']),
    ('--conversation with no id', ['-p', woken, '--conversation']),
    ('no -p prompt', ['--output-format', 'stream-json', '--model', 'm']),
]
with tempfile.TemporaryDirectory() as scratch:
    accepted = os.access(FAKE, os.X_OK) and fake_exit(
        ['-p', 'x with the build-ticket skill'] + HEAD + ['--mode=auto', '--effort', 'xhigh'],
        FAKE_CLI_RECORD_ONLY='1', FAKE_CLI_RECORD=os.path.join(scratch, 'rec')) == 0
check('the fake is executable and takes the documented start line, exiting 0', accepted)
for what, args in undocumented:
    check('the fake exits 2 on %s' % what, accepted and fake_exit(args) == 2)
check('the fake exits 2 without AGY_CLI_DISABLE_AUTO_UPDATE=true',
      accepted and fake_exit(['-p', 'x with the build-ticket skill'] + HEAD, AGY_CLI_DISABLE_AUTO_UPDATE='false') == 2)

with th.ThrowawayMachine(ROWS, NAME, mode='auto') as env:
    gh_only = os.pathsep.join([os.path.join(env.folder, 'bin'), without_agy(env.env['PATH'])])
    before = env.runs()
    code, out = env.start(PATH=gh_only)
    check('not installed is a D3 error that names agy, and starts nothing',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and out.get('error') == 'harness agy is not installed here'
          and env.runs() == before)

with th.ThrowawayMachine(ROWS, NAME, 'agy', FAKE, 'auto') as env:
    code, out = env.start(FAKE_CLI_SIGNED_OUT='1')
    check("not signed in is a D3 error that says so, its next names agy, and the log keeps agy's own line",
          code == 1 and th.kit.invalid(out, th.ERROR) is None and 'not signed in' in out.get('error', '')
          and 'agy' in out.get('next', '') and 'authentication required' in log(env))
    stop_all(env)

for mode, flags in MODES.items():
    with th.ThrowawayMachine(ROWS, NAME, 'agy', FAKE, mode) as env:
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
        env.driver('stop', out)
        argv = env.records()[-1]['argv'] if env.records() else []
        check('mode %s starts `agy -p <prompt> %s`' % (mode, ' '.join(HEAD[:3] + ['<m>'] + flags)),
              code == 0 and argv[:1] == ['-p'] and argv[2:] == HEAD + flags)

with th.ThrowawayMachine(ROWS, NAME, 'agy', FAKE, 'accept-edits', names=['AGY_CLI_DISABLE_AUTO_UPDATE']) as env:
    code, out = env.start()
    th.until(lambda: len(env.records()) >= 1)
    first = env.records()[0] if env.records() else {}
    woke = env.driver('wake', out)[0] == 0 and th.until(lambda: len(env.records()) >= 2, 30)
    second = env.records()[1] if woke else {}
    check('wake resumes with `agy -p <prompt> --conversation <the init event\'s id> %s --mode=accept-edits`'
          % ' '.join(HEAD[:3] + ['<m>']),
          code == 0 and woke and second.get('argv', [None])[1:] ==
          [second['argv'][1]] + ['--conversation', first.get('session')] + HEAD + ['--mode=accept-edits']
          and second['argv'][1].startswith('You were woken') and first.get('session') is not None)
    check('each turn gets AGY_CLI_DISABLE_AUTO_UPDATE=true',
          [r.get('env', {}).get('AGY_CLI_DISABLE_AUTO_UPDATE') for r in env.records()[:2]] == ['true', 'true'])
    stop_all(env)

with th.ThrowawayMachine(ROWS, NAME, 'agy', FAKE, 'settings') as env:
    for level in ('low', 'medium', 'high', 'xhigh', 'max'):
        code, out = env.start(effort=level, FAKE_CLI_RECORD_ONLY='1')
        env.driver('stop', out)
        argv = env.records()[-1]['argv'] if env.records() else []
        check('effort %s ends the start line with --effort %s' % (level, level),
              code == 0 and argv[-2:] == ['--effort', level])
    code, out = env.start(effort='high', FAKE_CLI_RECORD_ONLY='1')
    n = len(env.records())
    woke = env.driver('wake', out, FAKE_CLI_RECORD_ONLY='1')[0] == 0 and th.until(lambda: len(env.records()) > n, 30)
    env.driver('stop', out)
    check('a wake passes the start\'s effort again, since agy\'s --effort lasts one invocation',
          code == 0 and woke and env.records()[-1]['argv'][2] == '--conversation'
          and env.records()[-1]['argv'][-2:] == ['--effort', 'high'])
    check('an effort agy has no level for is refused with the fixed next, starting nothing',
          env.start_refused_starting_nothing(lambda out: out['next'] == th.CANT_SET_EFFORT, effort='minimal',
                                             FAKE_CLI_RECORD_ONLY='1'))

sys.exit(1 if failed else 0)
