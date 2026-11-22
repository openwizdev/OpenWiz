#!/usr/bin/env python3
"""The kiro row's own checks, on top of the runner's: not installed, not signed in, the approved mode only, and
effort refused with the fixed next. Synthetic: only this folder's fake runs, never a real kiro-cli."""
import json, os, sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import test_harnesses as th

ROWS, NAME = os.path.dirname(HERE), os.path.basename(HERE)
FAKE = os.path.join(HERE, 'fake')
HEADLESS = ['chat', '--v3', '--no-interactive', '--output-format', 'stream-json']
NEXT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
        "at the host's default")
failed = []


def check(what, ok):
    print('%s %s: %s' % ('pass' if ok else 'fail', NAME, what))
    if not ok:
        failed.append(what)


def without_kiro(path):
    return os.pathsep.join(d for d in path.split(os.pathsep) if not os.path.exists(os.path.join(d, 'kiro-cli')))


def stop_all(env):
    for run in env.runs():
        env.driver('stop', {'run': run[:-len('.json')]})


# Not installed: no kiro-cli anywhere on PATH (not even the runner's no-op stub).
with th.ThrowawayMachine(ROWS, NAME, mode='trust-all-tools') as env:
    gh_only = os.pathsep.join([os.path.join(env.folder, 'bin'), without_kiro(env.env['PATH'])])
    before = env.runs()
    code, out = env.start(PATH=gh_only)
    check('not installed is a D3 error whose next says to install kiro-cli, and starts nothing',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and out.get('error') == 'harness kiro is not installed here'
          and 'install kiro-cli' in out.get('next', '') and env.runs() == before)

# Not signed in: the fake answers as Kiro CLI 3.5.0 does signed out (its runError line and its stderr line, exit 1).
with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
    code, out = env.start(KIRO_FAKE_SIGNED_OUT='1')
    log = ''
    if env.runs():
        with open(os.path.join(env.state, env.runs()[0][:-len('.json')] + '.log')) as f:
            log = f.read()
    check('not signed in is a D3 error that says so, and its log names kiro-cli login and KIRO_API_KEY',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and 'not signed in' in out.get('error', '')
          and out.get('next', '').startswith('read ') and 'run `kiro-cli login` first' in log and 'KIRO_API_KEY' in log)
    stop_all(env)

# The approved mode only: permissions-yaml adds no trust flag; trust-all-tools adds exactly --trust-all-tools.
for mode, flags in (('permissions-yaml', []), ('trust-all-tools', ['--trust-all-tools'])):
    with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, mode) as env:
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
        env.driver('stop', out)
        argv = env.records()[-1]['argv'] if env.records() else []
        check('mode %s starts `kiro-cli %s`' % (mode, ' '.join(HEADLESS + ['--model', '<m>'] + flags + ['<prompt>'])),
              code == 0 and argv[:-1] == HEADLESS + ['--model', 'synthetic-1'] + flags)

# Effort: the row declares none, so every Kiro level is refused with the fixed next, and nothing starts.
with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
    for level in ('low', 'medium', 'high', 'xhigh', 'max'):
        check('effort %s is refused with the fixed next, starting nothing' % level,
              env.start_refused_starting_nothing(lambda out: out['next'] == NEXT, effort=level,
                                                 FAKE_CLI_RECORD_ONLY='1'))

sys.exit(1 if failed else 0)
