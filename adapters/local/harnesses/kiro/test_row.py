#!/usr/bin/env python3
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'release'))
import build_products
import test_harnesses as th

ROWS, NAME = os.path.dirname(HERE), os.path.basename(HERE)
FAKE = os.path.join(HERE, 'fake')
HEADLESS = ['chat', '--v3', '--no-interactive', '--output-format', 'stream-json']
NEXT = ("this host can't set effort: remove the effort for this harness in your Models table or Roster to run it "
        "at the host's default")
SIGN_IN = 'sign in with kiro-cli login, or set KIRO_API_KEY for kiro-cli yourself, then start again'
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
        check('not signed in (%s) is a D3 error that says so, and its next names kiro-cli login and KIRO_API_KEY' % lines,
              code == 1 and th.kit.invalid(out, th.ERROR) is None and 'not signed in' in out.get('error', '')
              and out.get('next', '').split('; ')[0] == SIGN_IN and '"stage":"auth"' in log)
        stop_all(env)

with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
    env.driver('stop', out)
    argv = env.records()[-1]['argv'] if env.records() else []
    check('mode trust-all-tools starts `kiro-cli %s`' % ' '.join(HEADLESS + ['--model', '<m>', '--trust-all-tools',
                                                                        '<prompt>']),
          code == 0 and argv[:-1] == HEADLESS + ['--model', 'synthetic-1', '--trust-all-tools'])

with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'permissions-yaml') as env:
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
    check('mode permissions-yaml is refused before kiro-cli runs: a headless run would load the clone\'s own hooks',
          code == 1 and th.kit.invalid(out, th.ERROR) is None and 'is not one its row lists' in out.get('error', '')
          and env.records() == [])
    stop_all(env)

with th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
    for level in ('low', 'medium', 'high', 'xhigh', 'max'):
        check('effort %s is refused with the fixed next, starting nothing' % level,
              env.start_refused_starting_nothing(lambda out: out['next'] == NEXT, effort=level,
                                                 FAKE_CLI_RECORD_ONLY='1'))

with tempfile.TemporaryDirectory(prefix='kiro-packaged-') as scratch, \
        th.ThrowawayMachine(ROWS, NAME, 'kiro-cli', FAKE, 'trust-all-tools') as env:
    repo = Path(scratch) / 'repo'
    local_dir = Path(ROOT) / 'adapters' / 'local'
    for rel in ('driver', 'schema.json', 'release.json'):
        dst = repo / 'adapters' / 'local' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_dir / rel, dst)
    for row in sorted((local_dir / 'harnesses').glob('*/row.json')):
        dst = repo / row.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row, dst)
    git = lambda *args: subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True)
    git('init', '-q')
    git('add', 'adapters/local')
    git('-c', 'user.name=test', '-c', 'user.email=test@example.invalid', 'commit', '-q', '-m', 'local')
    sha = git('rev-parse', 'HEAD').stdout.strip()
    selected = build_products.drivers(repo, sha)
    packaged = Path(scratch) / 'packaged'
    for rel in [*selected, *build_products.KIT]:
        src = (repo / rel) if rel.startswith('adapters/') else (Path(ROOT) / rel)
        dst = packaged / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        dst.chmod(0o700 if rel.endswith('/driver') else 0o600)
    env.driver_path = str(packaged / 'adapters' / 'local' / 'driver')
    code, out = env.start(FAKE_CLI_RECORD_ONLY='1')
    if code == 0 and isinstance(out, dict) and out.get('run'):
        env.driver('stop', out)
    stop_all(env)
    check('packaged runtime selects harnesses/kiro/row.json and starts kiro',
          'adapters/local/harnesses/kiro/row.json' in selected and code == 0
          and isinstance(out, dict) and bool(out.get('run')))

sys.exit(1 if failed else 0)
