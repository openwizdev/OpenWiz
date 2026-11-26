#!/usr/bin/env python3
import json, os, shutil, subprocess, sys, tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as th

ROWS, NAME = os.path.dirname(HERE), os.path.basename(HERE)
FAKE = os.path.join(HERE, 'fake')
EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')
failed = []


def check(what, ok):
    print('%s %s: %s' % ('pass' if ok else 'fail', NAME, what))
    if not ok:
        failed.append(what)


def without_amp(path):
    return os.pathsep.join(d for d in path.split(os.pathsep) if not os.path.exists(os.path.join(d, 'amp')))


def fake(*argv, **env):
    return subprocess.run([FAKE] + list(argv), env=dict(os.environ, FAKE_CLI_LIB=th.FIXTURES, **env),
                          capture_output=True, text=True, timeout=30).returncode


def start_and_wake(mode, effort=None):
    with th.ThrowawayMachine(ROWS, NAME, 'amp', FAKE, mode, ['AMP_SKIP_UPDATE_CHECK']) as env:
        code, out = env.start(effort=effort, FAKE_CLI_RECORD_ONLY='1')
        woke = code == 0 and th.until(lambda: len(env.records()) == 1) and \
            env.driver('wake', out)[0] == 0 and th.until(lambda: len(env.records()) == 2)
        env.driver('stop', out)
        return woke, [r['argv'][:1] + ['<prompt>'] + r['argv'][2:] if r['turn'] == 'first' else
                      r['argv'][:4] + ['<prompt>'] + r['argv'][5:] for r in env.records()], \
            [r['session'] for r in env.records()]


with th.ThrowawayMachine(ROWS, NAME, mode='allow-all') as env:
    before = env.runs()
    code, out = env.start(PATH=os.pathsep.join([os.path.join(env.folder, 'bin'), without_amp(env.env['PATH'])]))
    check('not installed is a D3 error whose next says to install amp, and starts nothing',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and out.get('error') == 'harness amp is not installed here'
          and 'install amp' in out.get('next', '') and env.runs() == before)

with th.ThrowawayMachine(ROWS, NAME, 'amp', FAKE, 'allow-all', ['AMP_SKIP_UPDATE_CHECK']) as env:
    code, out = env.start(AMP_FAKE_SIGNED_OUT='1')
    check('not signed in (amp\'s own stderr line) is a D3 error that says so, and its next names amp login',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and 'not signed in' in out.get('error', '')
          and 'amp login' in out.get('next', ''))
    for run in env.runs():
        env.driver('stop', {'run': run[:-len('.json')]})

for mode, flags in (('default', []), ('allow-all', ['--dangerously-allow-all'])):
    woke, argv, sessions = start_and_wake(mode)
    start = ['-x', '<prompt>', '--stream-json', '--no-archive-after-execute', '--model', 'synthetic-1'] + flags
    wake = ['threads', 'continue', sessions[0] if sessions else '?', '-x', '<prompt>', '--stream-json'] + flags
    check('mode %s starts `amp %s` and wakes `amp %s`' % (mode, ' '.join(start), ' '.join(wake[:2] + ['<thread id>'] + wake[3:])),
          woke and argv == [start, wake] and len(set(sessions)) == 1)

for level in EFFORTS:
    woke, argv, _ = start_and_wake('allow-all', level)
    check('effort %s starts with --model <m> --effort %s, and the wake passes no effort' % (level, level),
          woke and len(argv) == 2 and argv[0][-2:] == ['--effort', level] and '--model' in argv[0]
          and '--effort' not in argv[1])

with tempfile.TemporaryDirectory(prefix='amp-archives-') as rows:
    shutil.copytree(HERE, os.path.join(rows, NAME))
    with open(os.path.join(rows, NAME, 'row.json')) as f:
        row = json.load(f)
    row['start'].remove('--no-archive-after-execute')
    with open(os.path.join(rows, NAME, 'row.json'), 'w') as f:
        json.dump(row, f)
    with th.ThrowawayMachine(rows, NAME, 'amp', os.path.join(rows, NAME, 'fake'), 'allow-all',
                             ['AMP_SKIP_UPDATE_CHECK']) as env:
        lines = env.kit()
        logs = ''
        for run in env.runs():
            with open(os.path.join(env.state, run[:-len('.json')] + '.log')) as f:
                logs += f.read()
        check('without --no-archive-after-execute, amp archives the started thread and the wake fails: %s'
              % next((x for x in lines if not x.startswith('pass ')), 'the kit passed'),
              lines[:2] == th.PASS[:2] and lines[2:3] != th.PASS[2:3]
              and 'This thread is archived and cannot be continued.' in logs
              and [r['turn'] for r in env.records()] == ['first'])

ok = {'AMP_SKIP_UPDATE_CHECK': '1'}
for why, argv, env in (
        ('--stream-json without -x', ['--stream-json', '--model', 'm', 'with the build-ticket skill'], ok),
        ('--effort on a continued thread', ['threads', 'continue', 'T-1', '-x', 'You were woken with the x skill',
                                            '--stream-json', '--effort', 'high'], ok),
        ('an effort level amp does not know', ['-x', 'with the build-ticket skill', '--stream-json',
                                               '--no-archive-after-execute', '--model', 'm', '--effort', 'ultra'], ok),
        ('an orb run', ['-ox', 'with the build-ticket skill', '--stream-json'], ok),
        ('a run with update checks left on', ['-x', 'with the build-ticket skill', '--stream-json',
                                              '--no-archive-after-execute', '--model', 'm'], {})):
    check('the fake exits 2 on %s' % why, fake(*argv, **env) == 2)

sys.exit(1 if failed else 0)
