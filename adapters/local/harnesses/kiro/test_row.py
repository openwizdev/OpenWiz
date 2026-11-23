#!/usr/bin/env python3
import os, sys

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


with th.ThrowawayMachine(ROWS, NAME, mode='trust-all-tools') as env:
    gh_only = os.pathsep.join([os.path.join(env.folder, 'bin'), without_kiro(env.env['PATH'])])
    before = env.runs()
    code, out = env.start(PATH=gh_only)
    check('not installed is a D3 error whose next says to install kiro-cli, and starts nothing',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and out.get('error') == 'harness kiro is not installed here'
          and 'install kiro-cli' in out.get('next', '') and env.runs() == before)

for how, lines in (('both', 'its runError line and its stderr line'), ('json', 'its runError line alone')):
    with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
        code, out = env.start(KIRO_FAKE_SIGNED_OUT=how)
        log = ''
        if env.runs():
            with open(os.path.join(env.state, env.runs()[0][:-len('.json')] + '.log')) as f:
                log = f.read()
        check('not signed in (%s) is a D3 error that says so, and its next names kiro-cli login' % lines,
              code == 1 and th.kit.invalid(out, th.ERROR) is None and 'not signed in' in out.get('error', '')
              and 'kiro-cli login' in out.get('next', '') and '"stage":"auth"' in log and 'KIRO_API_KEY' in log)
        stop_all(env)

for mode, flags in (('permissions-yaml', []), ('trust-all-tools', ['--trust-all-tools'])):
    with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, mode) as env:
        code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
        env.driver('stop', out)
        argv = env.records()[-1]['argv'] if env.records() else []
        check('mode %s starts `kiro-cli %s`' % (mode, ' '.join(HEADLESS + ['--model', '<m>'] + flags + ['<prompt>'])),
              code == 0 and argv[:-1] == HEADLESS + ['--model', 'synthetic-1'] + flags)

with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
    for level in ('low', 'medium', 'high', 'xhigh', 'max'):
        check('effort %s is refused with the fixed next, starting nothing' % level,
              env.start_refused_starting_nothing(lambda out: out['next'] == NEXT, effort=level,
                                                 FAKE_CLI_RECORD_ONLY='1'))

sys.exit(1 if failed else 0)
