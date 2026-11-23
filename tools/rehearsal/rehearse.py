#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

DESCRIPTION = """The clean-machine install rehearsal (#2441, spec #2437): a stranger's install of one built package.

  rehearse.py --assets DIR --target TARGET --version X.Y.Z --source COMMIT \\
      --checkout DIR --skills DIR --output FILE

DIR for --assets is the Packages run's `packages/` folder for TARGET; --checkout is the candidate
commit's OpenWiz checkout; --skills is the install skill's release at that checkout's
`wizskills.lock` commit (the checkout's `.wizskills/skills`). It follows the install skill's
no-CloudRoom path ("This computer", Claude Code), with the 0.1.1 runbook's two substitutions for
an unpublished candidate: the installer is the checkout's, and step 2 is `install install
--assets` instead of `download`. Six named steps, each a pass or a fail, in this order, stopping
at the first fail:

  preflight            install preflight passes; room-cli reads missing and does not stop it
  install              install install --assets prints "activated": true, the version and target
  build_identity       <root>/current/openwiz --build-identity reads the version and the commit
  setup                setup.py prepare --host local (preview, then its own --yes: owner-only
                       local state), then setup.py check reads cloudroom_not_needed, and
                       github_login.py status reads the fake account
  skills               install skills copies the skills into a fresh Claude Code skills folder
  first_fleet_dry_run  first_fleet.py where --agents local and the read-only steps after it, on
                       a fake repository: previews only, no --yes, and no GitHub write

Every command runs in a stranger's environment: `env -i`, a fresh HOME, and a PATH holding only
python3, git, sh, uname, ldd (Linux), the fake gh and claude (fakes/) and recording cargo, rustc,
rustup, npm, node and npx, which fail the step that calls them. No other agent or host CLI
(ABSENT, room-cli included) may be on it. It writes the receipt (contracts/rehearsal.v1.md) to
FILE and exits 0 on pass, 1 on fail, printing the failed step's commands and their exact output;
2 is a usage or environment refusal, with no receipt. A passed step's commands and output go to stderr. Standard-library Python 3.9 on Linux
and macOS. It proves an install of these bytes with fakes for GitHub and the harness; never a
real account, repository, harness or fleet.
"""

SCHEMA = 'openwiz.rehearsal.v1'
STEPS = ('preflight', 'install', 'build_identity', 'setup', 'skills', 'first_fleet_dry_run')
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
BUILD_TOOLS = ('cargo', 'rustc', 'rustup', 'npm', 'node', 'npx')
ALLOWED = ('python3', 'git', 'sh', 'uname', 'ldd')
ABSENT = ('room-cli', 'cloudroom', 'codex', 'openwiz', 'boat', 'hermes', 'acpx', 'openclaw', 'droid', 'runpane',
          'pane', 'cursor-agent', 'cursor', 'opencode', 'gemini', 'amp', 'aider', 'goose', 'copilot', 'qwen',
          'kiro', 'crush', 'jules', 'devin', 'oz', 'warp', 'openhands', 'capy', 'tembo', 'conductor', 'factory',
          'codespaces')
SECRET = re.compile(r'(GITHUB_TOKEN|GH_TOKEN|GH_ENTERPRISE_TOKEN|GITHUB_ENTERPRISE_TOKEN|OPENWIZ_GITHUB_APP_.*'
                    r'|ACTIONS_.*TOKEN.*|ROOM_.*|CLOUDROOM.*)')
HERE = Path(__file__).resolve().parent
FAKES = HERE / 'fakes'
WORLD = json.loads((FAKES / 'world.json').read_text(encoding='utf-8'))
LOGIN = WORLD['api']['user']['login']
REPO = next(path[len('repos/'):] for path in WORLD['api'] if path.count('/') == 2)
TIMEOUT = 300


class Failed(Exception):
    pass


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, why):
    if not condition:
        raise Failed(why)


def parsed(text):
    for candidate in (text, (text.strip().splitlines() or [''])[-1]):
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise Failed('its output is not one JSON object')


class Stranger:

    def __init__(self, work):
        self.work = work
        self.home, self.bin, tmp = work / 'home', work / 'bin', work / 'tmp'
        for folder in (self.home, self.bin, tmp, self.home / '.claude'):
            folder.mkdir(mode=0o700)
        for tool in BUILD_TOOLS:
            shutil.copyfile(FAKES / 'build-tool', self.bin / tool)
        for fake in ('gh', 'claude'):
            shutil.copyfile(FAKES / fake, self.bin / fake)
        for tool in os.listdir(self.bin):
            (self.bin / tool).chmod(0o755)
        for tool in ALLOWED:
            found = shutil.which(tool, path=os.defpath + os.pathsep + os.environ.get('PATH', ''))
            if found:
                os.symlink(os.path.realpath(found), self.bin / tool)
        for tool in ('python3', 'git', 'sh'):
            require((self.bin / tool).exists(), 'this machine has no %s' % tool)
        self.python = str(self.bin / 'python3')
        self.world, self.gh_log, self.tool_log = work / 'world.json', work / 'gh.log', work / 'tools.log'
        shutil.copyfile(FAKES / 'world.json', self.world)
        self.gh_log.write_text('')
        self.tool_log.write_text('')
        self.env = {'HOME': str(self.home), 'PATH': str(self.bin), 'USER': 'stranger', 'LOGNAME': 'stranger',
                    'SHELL': '/bin/sh', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'TERM': 'dumb', 'TMPDIR': str(tmp),
                    'REHEARSAL_GH_WORLD': str(self.world), 'REHEARSAL_GH_LOG': str(self.gh_log),
                    'REHEARSAL_TOOL_LOG': str(self.tool_log)}
        for tool in ABSENT:
            require(shutil.which(tool, path=self.env['PATH']) is None, '%s is on the stranger\'s PATH' % tool)
        self.transcript = []

    def run(self, argv, extra=None):
        argv = [str(a) for a in argv]
        try:
            done = subprocess.run(['/usr/bin/env', '-i'] + ['%s=%s' % kv for kv in
                                                            sorted(dict(self.env, **(extra or {})).items())] + argv,
                                  cwd=str(self.home), stdin=subprocess.DEVNULL, capture_output=True,
                                  text=True, timeout=TIMEOUT)
            code, out, err = done.returncode, done.stdout, done.stderr
        except subprocess.TimeoutExpired:
            code, out, err = 'timeout', '', 'timed out after %d seconds' % TIMEOUT
        self.transcript.append('$ %s\nexit %s\n%s%s' % (' '.join(shlex.quote(a) for a in argv), code, out, err))
        return code, out

    def json(self, argv, want=0, extra=None):
        code, out = self.run(argv, extra)
        require(code == want, 'exit %s, not %s' % (code, want))
        return parsed(out)

    def effects(self):
        called = self.tool_log.read_text().strip()
        require(not called, 'it called a build tool or the harness: %s' % called.replace('\n', '; '))
        calls = [json.loads(line) for line in self.gh_log.read_text().splitlines()]
        writes = [' '.join(c['argv']) for c in calls if c['kind'] != 'read']
        require(not writes, 'it wrote to GitHub, or ran a gh command the fake does not know: gh %s'
                % '; gh '.join(writes))


class Rehearsal:
    def __init__(self, args, work):
        self.args, self.s = args, Stranger(work)
        self.root = self.s.home / '.local/lib/openwiz'
        self.build = self.state = None
        self.installer = Path(args.checkout) / 'tools/install/install'

    def preflight(self):
        value = self.s.json([self.s.python, '-I', self.installer, 'preflight'])
        require(value.get('ready') is True, 'preflight is not ready')
        require(value.get('target') == self.args.target, 'preflight reads target %r' % value.get('target'))
        rooms = [c for c in value.get('checks', []) if c.get('id') == 'room-cli']
        require(len(rooms) == 1 and rooms[0].get('state') == 'missing', 'room-cli does not read missing')

    def install(self):
        download = self.s.work / 'download'
        download.mkdir(mode=0o700)
        for path in self.assets():
            shutil.copyfile(path, download / path.name)
            (download / path.name).chmod(0o600)
        value = self.s.json([self.s.python, '-I', self.installer, 'install', '--assets', download,
                             '--target', self.args.target, '--root', self.root])
        require(value.get('activated') is True, 'it did not print "activated": true')
        for key in ('version', 'source', 'target'):
            require(value.get(key) == getattr(self.args, key), 'it installed %s %r' % (key, value.get(key)))
        self.build, self.state = Path(value['build']), Path(value['state_root'])

    def build_identity(self):
        value = self.s.json([self.root / 'current/openwiz', '--build-identity'])
        require(value.get('schema') == 'openwiz.product.v1', 'it is not an openwiz.product.v1 identity')
        for key in ('version', 'source', 'target'):
            require(value.get(key) == getattr(self.args, key), 'the build identity reads %s %r' % (key, value.get(key)))

    def setup(self):
        tools, state = self.build / 'runtime/setup', ['--state-dir', self.state]
        extra = {'OPENWIZ_STATE_DIR': str(self.state)}
        models = self.s.json([self.root / 'current/openwiz', 'models', '--json', '--host', 'local'])
        claude = [h for h in models.get('harnesses', []) if h.get('harness') == 'claude-code']
        require(len(claude) == 1 and claude[0].get('models'), 'This computer offers no Claude Code model')
        model = claude[0]['models'][0]
        prepare = [self.s.python, '-I', '-B', tools / 'setup.py', 'prepare'] + state + [
            '--repository', REPO, '--operator', LOGIN, '--service-issue', '1', '--host', 'local',
            '--harness', 'claude-code', '--model', model['model'], '--effort', model['efforts'][0]]
        operation = self.s.json(prepare, extra=extra).get('operation_id')
        require(operation, 'prepare printed no operation to confirm')
        require(self.s.json(prepare + ['--yes', '--operation', operation], extra=extra).get('phase') == 'applied',
                'prepare did not save the local host')
        check = self.s.json([self.s.python, '-I', '-B', tools / 'setup.py', 'check'] + state, extra=extra)
        require(check.get('host') == 'local', 'the setup check is not under the local host')
        cloudroom = (check.get('results') or {}).get('cloudroom')
        require(cloudroom == 'cloudroom_not_needed', 'the setup check reads cloudroom %r' % cloudroom)
        login = self.s.json([self.s.python, '-I', '-B', tools / 'github_login.py', 'status'] + state, extra=extra)
        require(login.get('code') == 'login_signed_in' and login.get('login') == LOGIN,
                'github_login.py status reads %r as %r' % (login.get('login'), login.get('code')))

    def skills(self):
        folder = self.s.home / '.claude/skills'
        value = self.s.json([self.s.python, '-I', self.installer, 'skills', '--root', self.root])
        rows = [r for r in value.get('harnesses', []) if r.get('id') == 'claude-code']
        require(len(rows) == 1 and rows[0].get('state') == 'installed' and rows[0].get('path') == str(folder),
                'Claude Code did not get the skills')
        pinned = Path(self.args.skills)
        names = sorted(p.name for p in pinned.iterdir() if (p / 'SKILL.md').is_file())
        missing = [n for n in names if not (folder / n / 'SKILL.md').is_file()]
        require(names and not missing, 'the Claude Code skills folder lacks %s' % ', '.join(missing or ['all']))
        for path in ('install/SKILL.md', 'install/scripts/first_fleet.py'):
            require((folder / path).read_bytes() == (pinned / path).read_bytes(),
                    'the installed %s is not the pinned release\'s' % path)

    def first_fleet_dry_run(self):
        first_fleet = [self.s.python, '-I', self.s.home / '.claude/skills/install/scripts/first_fleet.py']
        onboarding = self.s.work / 'onboarding'
        onboarding.mkdir(mode=0o700)
        road = ['--state', onboarding / 'state.json']
        extra = {'OPENWIZ_STATE_DIR': str(self.state)}
        code, out = self.s.run(first_fleet + ['where'] + road + ['--agents', 'local', '--build', self.build], extra)
        require(code == 12 and 'Nothing recorded' in out, 'where --agents local was not a preview (exit %s)' % code)
        require('claude-code' in out, 'where does not find Claude Code on this machine')
        code, out = self.s.run(first_fleet + ['select'] + road + ['--repo', REPO], extra)
        require(code == 0, 'select exit %s' % code)
        login = self.s.json([self.s.python, '-I', '-B', self.build / 'runtime/setup/github_login.py', 'status',
                             '--repository', REPO, '--state-dir', self.state], extra=extra)
        require(login.get('repository') == 'identity_verified',
                'the fake repository reads %r' % login.get('repository'))
        code, out = self.s.run(first_fleet + ['next'] + road + ['--setup-state', self.state], extra)
        require(code == 0 and out.startswith('Next: '), 'next exit %s' % code)

    def assets(self):
        folder, target = Path(self.args.assets), self.args.target
        found = [folder / ('openwiz-%s.sha256' % target), folder / ('openwiz-%s.manifest.json' % target)]
        archives = sorted(folder.glob('openwiz-*-%s.tar.gz' % target))
        require(len(archives) == 1 and all(p.is_file() for p in found),
                'the archive folder lacks the checksum file, manifest or one archive for %s' % target)
        return found + archives

    def rehearse(self):
        steps = []
        for name in STEPS:
            self.s.transcript = []
            try:
                getattr(self, name)()
                self.s.effects()
            except (Failed, OSError, KeyError, TypeError, ValueError, AttributeError, IndexError) as why:
                steps.append({'name': name, 'status': 'fail'})
                print('step %s: fail: %s' % (name, why if isinstance(why, Failed) else type(why).__name__))
                print(''.join(self.s.transcript), end='')
                return steps
            steps.append({'name': name, 'status': 'pass'})
            print('step %s: pass' % name)
            print(''.join(self.s.transcript), end='', file=sys.stderr)
        return steps


def digest_of(folder, pattern):
    found = sorted(Path(folder).glob(pattern))
    return sha(found[0]) if len(found) == 1 and found[0].is_file() else None


def main(argv=None):
    parser = argparse.ArgumentParser(prog='rehearse.py', description=DESCRIPTION,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('assets', 'target', 'version', 'source', 'checkout', 'skills', 'output'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    held = sorted(name for name in os.environ if SECRET.fullmatch(name))
    problems = (['a token, App or CloudRoom variable is set: %s' % ', '.join(held)] if held else []) + [
        why for ok, why in ((args.target in TARGETS, 'unknown --target'),
                            (re.fullmatch(r'0\.[0-9]+\.[0-9]+', args.version), '--version is not 0.minor.patch'),
                            (re.fullmatch(r'[0-9a-f]{40}', args.source), '--source is not a full commit'),
                            (Path(args.assets).is_dir(), '--assets is not a folder'),
                            ((Path(args.checkout) / 'tools/install/install').is_file(), '--checkout has no installer'),
                            ((Path(args.skills) / 'install/SKILL.md').is_file(), '--skills has no install skill'),
                            (not os.path.lexists(args.output), '--output exists'))
        if not ok]
    if problems:
        print('rehearse.py: refused: %s' % '; '.join(problems), file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='openwiz-rehearsal-') as work:
        try:
            steps = Rehearsal(args, Path(work).resolve()).rehearse()
        except Failed as why:
            print('rehearse.py: refused: %s' % why, file=sys.stderr)
            return 2
    passed = [s['name'] for s in steps if s['status'] == 'pass'] == list(STEPS)
    receipt = {'schema': SCHEMA, 'version': args.version, 'source': args.source, 'target': args.target,
               'archive_sha256': digest_of(args.assets, 'openwiz-*-%s.tar.gz' % args.target),
               'manifest_sha256': digest_of(args.assets, 'openwiz-%s.manifest.json' % args.target),
               'status': 'pass' if passed else 'fail', 'steps': steps}
    Path(args.output).write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print('rehearsal: %s' % receipt['status'])
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
