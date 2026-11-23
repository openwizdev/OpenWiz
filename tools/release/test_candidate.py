#!/usr/bin/env python3
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REAL_GIT = shutil.which('git')
PUBLIC = 'openwizdev/OpenWiz'
PUBLIC_URL = 'https://github.com/openwizdev/OpenWiz.git'
PRIVATE = 'jparker2006/ClosedWiz'
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
PRODUCTS = ('cli', 'runtime')
VERSION = '0.0.99'
NOREPLY = '123+fixture@users.noreply.github.com'
PUBLISHED = '# Changelog\n\n## 0.0.98 · 2026-01-01\n\nContext: Earlier public entry.  \n'
NOTES = ('## 0.0.99 · 2026-11-20\n\nFixture-tested: You can preview a synthetic export.\n\n'
         '- Fixture-tested: You can save a preview.\n- Fixture-tested: You can cancel a preview.\n\n'
         'Live-checked: Synthetic export smoke passes; a real export remains unverified.\n\n'
         '[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.99)\n')

CURATED = ("## 0.0.99 · 2026-11-20\n\n**Preview an export**\n\n**What's new for you**\n\n"
           "- You can preview a synthetic export.\n- You can cancel a preview.\n\n"
           "Live-checked: a synthetic export smoke; a real export is still unverified.\n\n"
           "**Under the hood**\n\n- The preview reads one synthetic file.\n\n"
           "[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.99)\n")


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


receipts_fixture = load('release_candidate_receipt_fixture', ROOT / 'tools/live-smoke/test_receipt.py')
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'tools/install'))
import package
import build_products
rl4 = load('release_candidate_rl4_fixture', HERE / 'test_product_identity.py')
RUNTIME = dict(rl4.RUNTIME, **{f'skills/{name}': f'Synthetic {name}.\n'.encode() for name in (
    'setup/SKILL.md', 'grill/SKILL.md', 'to-tickets/SKILL.md', 'launch-fleet/SKILL.md')},
    **{'skills/launch-fleet/scripts/fleet.sh': b'#!/bin/sh\necho synthetic\n'})
RELEASED_CONTRACTS = {'contracts/alpha.v1.md': b'Synthetic alpha contract.\n',
                      'contracts/beta.v1.md': b'Synthetic beta contract.\n'}
RUNTIME['tools/install/cloudroom/cloudroom.py'] = b'# Synthetic CloudRoom setup tool.\n'
rl4.PACKAGED['tools/install/cloudroom/cloudroom.py'] = 'runtime/cloudroom/cloudroom.py'
RUNTIME['tools/install/setup/init.py'] = b'# Synthetic init runtime.\n'
rl4.PACKAGED['tools/install/setup/init.py'] = 'runtime/setup/init.py'
RUNTIME['tools/install/setup/github_login.py'] = b'# Synthetic GitHub sign-in helper.\n'
rl4.PACKAGED['tools/install/setup/github_login.py'] = 'runtime/setup/github_login.py'
LINUX = 'x86_64-unknown-linux-gnu'
SCHEMA = json.loads((ROOT / 'contracts/release-candidate.v1.schema.json').read_text())


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def iso(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def section_sha(text, version):
    start = text.index(f'## {version} · ')
    rest = text.find('\n## ', start + 1)
    return sha(text[start:(rest + 1 if rest >= 0 else len(text))].rstrip('\n').encode())


LAUNCH = ('import os, sys; sys.path.insert(0, sys.argv.pop(1)); import candidate; '
          'candidate.ANCHOR = sys.argv.pop(1); '
          'import json; m = os.environ.get("MOVED"); '
          'm and setattr(candidate.entry, "MOVED", candidate.entry.moved(json.loads(m))); '
          'candidate.today = (lambda: os.environ["TODAY"]) if "TODAY" in os.environ else candidate.today; '
          'candidate.now = (lambda: int(os.environ["AT"])) if "AT" in os.environ else candidate.now; '
          'w = os.environ.get("WAIVABLE"); w = w and {tuple(x) for x in json.loads(w)}; '
          'w and setattr(candidate, "WAIVABLE", w); load = candidate.smoke_module; '
          'w and setattr(candidate, "smoke_module", lambda: (lambda m: (setattr(m, "WAIVABLE", w), m)[1])(load())); '
          'i = os.environ.get("WIZSKILLS_INSTALL"); import product_identity, pathlib; '
          'i and setattr(product_identity, "install_locked", lambda root, source, scratch: pathlib.Path(i)); '
          'f = os.environ.get("FETCH"); f and exec(f, vars(candidate)); '
          'h = os.environ.get("HOLD"); h and exec(h, vars(candidate)); '
          'sys.exit(candidate.main(sys.argv[1:]))')

FAKE_GIT = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
REAL, URL = @REAL@, @URL@
args = sys.argv[1:]
verbs = ("push", "tag", "clone", "fetch", "ls-remote")
verb = next((a for a in args if a in verbs), "read")
action = "read"
if verb == "push":
    action = "tag-push" if any(":refs/tags/" in a for a in args) else "main-push"
elif verb == "tag" and "-a" in args:
    action = "tag"
with open(os.environ["CALLS"], "a") as log:
    log.write(json.dumps({"tool": "git", "action": action, "args": args}) + "\n")
if os.environ.get("FAIL_ACTION") == action:
    sys.exit(42)
if os.environ.get("FAIL_ACTION") == "fetch" and verb == "fetch":
    sys.exit(42)
# Only network operations reach the fake remote; a configured URL stays as written.
network = verb in verbs
mapped = [os.environ["PUBLIC_FAKE"] if a == URL and network else a for a in args]
if network and any(a.startswith(("https://", "http://", "ssh://", "git@")) for a in mapped):
    sys.exit(97)
sys.exit(subprocess.run([REAL] + mapped).returncode)
'''.replace('@REAL@', repr(REAL_GIT)).replace('@URL@', repr(PUBLIC_URL))

FAKE_FETCH = r'''
def fetch_release(url, limit):
    import json, os, pathlib, urllib.error
    base = "https://github.com/openwizdev/OpenWiz/releases/"
    assert url.startswith(base), url
    with open(os.environ["CALLS"], "a") as log:
        log.write(json.dumps({"tool": "https", "action": "download", "args": [url]}) + "\n")
    if os.environ.get("FETCH_STATUS"):
        raise urllib.error.HTTPError(url, int(os.environ["FETCH_STATUS"]), "Synthetic", None, None)
    store, rest = pathlib.Path(os.environ["RELEASES"]), url[len(base):]
    if rest.startswith("latest/download/"):
        shown = [m.parent.name for m in store.glob("*/meta.json") if not json.loads(m.read_text())["prerelease"]]
        tag = max(shown, key=lambda t: tuple(map(int, t[1:].split("."))), default="")
        name = rest[len("latest/download/"):]
    else:
        tag, name = rest[len("download/"):].split("/", 1)
    file = store / tag / "assets" / name
    if not tag or not file.is_file():
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
    return file.read_bytes()[:limit + 1]
'''

HOLD_INDEX = r'''
def _hold(write):
    def held(self, name, value):
        import os, pathlib, time
        if name != "install-attempts.json":
            return write(self, name, value)
        hold, me, end = pathlib.Path(os.environ["HOLD_DIR"]), os.environ["HOLD_ME"], time.time() + 60
        (hold / ("read-" + me)).touch()
        while len(list(hold.glob("read-*"))) < 2 and time.time() < end:
            time.sleep(0.05)
        while me != "first" and not (hold / "done-first").exists() and time.time() < end:
            time.sleep(0.05)
        write(self, name, value)
        (hold / ("done-" + me)).touch()
    return held
State.write = _hold(State.write)
'''

FAKE_GH = r'''#!/usr/bin/env python3
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as log:
    action = "release" if args[:2] == ["release", "create"] else "gh-read"
    log.write(json.dumps({"tool": "gh", "action": action, "args": args}) + "\n")
world = json.loads(pathlib.Path(os.environ["GH_WORLD"]).read_text())
store = pathlib.Path(os.environ["RELEASES"])
plant = os.environ.get("PLANT", "")
if args[:2] == ["release", "create"]:
    if os.environ.get("FAIL_ACTION") == "release":
        sys.exit(42)
    tag = args[2]
    files = [a for a in args[3:] if a.startswith("/") and not a.endswith("notes.md")]
    notes = pathlib.Path(args[args.index("--notes-file") + 1]).read_text()
    folder = store / tag
    (folder / "assets").mkdir(parents=True)
    for f in files:
        shutil.copy(f, folder / "assets" / pathlib.Path(f).name)
    (folder / "meta.json").write_text(json.dumps({"tag": tag, "title": args[args.index("--title") + 1],
                                                  "notes": notes, "prerelease": "--prerelease" in args}))
    sys.exit(42 if os.environ.get("FAIL_ACTION") == "release-response" else 0)
if args[:2] == ["release", "download"]:
    folder = store / args[2] / "assets"
    out = pathlib.Path(args[args.index("--dir") + 1])
    for f in sorted(folder.iterdir()):
        data = f.read_bytes()
        if plant == "asset" and f.name.endswith(".tar.gz") and "linux" in f.name:
            data += b"synthetic changed download"
        (out / f.name).write_bytes(data)
    sys.exit(0)
assert args[0] == "api" and not any(x in args for x in ("--method", "-X", "-f", "-F")), args
path = next(a for a in args if a.startswith("repos/"))
if path.startswith("repos/openwizdev/OpenWiz/releases/tags/"):
    meta = store / path.rsplit("/", 1)[1] / "meta.json"
    if not meta.exists() or plant == "unreadable":
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        sys.exit(1)
    m = json.loads(meta.read_text())
    assets = [{"name": f.name, "size": f.stat().st_size} for f in sorted((meta.parent / "assets").iterdir())]
    print(json.dumps({"tag_name": m["tag"], "name": m["title"],
                      "body": {"notes": m["notes"] + "Synthetic edit", "crlf": m["notes"].replace("\n", "\r\n"),
                               "trimmed": m["notes"].rstrip("\n")}.get(plant, m["notes"]),
                      "draft": False, "prerelease": m["prerelease"], "immutable": plant != "mutable",
                      "assets": assets}))
    sys.exit(0)
if path in world.get("_fail", []):
    sys.exit(94)
if path not in world:
    print("unexpected fixture read: " + path, file=sys.stderr)
    sys.exit(95)
value = world[path]
print(json.dumps(value))
'''


class World(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='release-candidate-proof-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name, text in (('git', FAKE_GIT), ('gh', FAKE_GH)):
            (self.bin / name).write_text(text)
            (self.bin / name).chmod(0o755)
        self.remote = self.root / 'public.git'
        self.repo = self.root / 'clone'
        self.state = self.root / 'state'
        self.releases = self.root / 'releases'
        self.releases.mkdir()
        self.world_path = self.root / 'world.json'
        self.env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME='Synthetic', GIT_COMMITTER_NAME='Synthetic',
                        GIT_AUTHOR_EMAIL=NOREPLY, GIT_COMMITTER_EMAIL=NOREPLY,
                        PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        CALLS=str(self.root / 'calls.jsonl'), PUBLIC_FAKE=str(self.remote),
                        GH_WORLD=str(self.world_path), RELEASES=str(self.releases), TODAY='2026-11-20',
                        FETCH=FAKE_FETCH)
        self.now = int(time.time())
        self.world = {f'repos/{PUBLIC}': {'full_name': PUBLIC, 'visibility': 'public', 'archived': False,
                                          'default_branch': 'main'},
                      f'repos/{PUBLIC}/immutable-releases': {'enabled': True, 'enforced_by_owner': False},
                      f'repos/{PRIVATE}/issues/1285': {'state': 'closed', 'state_reason': 'completed', 'labels': []},
                      f'repos/{PRIVATE}/issues/1284': {'state': 'closed', 'state_reason': 'completed', 'labels': []},
                      f'repos/{PUBLIC}/rulesets?per_page=100': [[{'id': 71}]],
                      f'repos/{PUBLIC}/rulesets/71': {
                          'id': 71, 'enforcement': 'active', 'target': 'branch', 'bypass_actors': [],
                          'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}},
                          'rules': [{'type': 'required_status_checks', 'parameters': {'required_status_checks': [
                              {'context': 'ci'}, {'context': 'privacy'}]}}]}}
        self.comments = {}
        self.literals = self.root / 'literals.txt'
        self.literals.write_text('synthetic-private-term-zq\n')
        self.history()

    def git(self, cwd, *args):
        result = subprocess.run([REAL_GIT, '-C', str(cwd), *map(str, args)], env=self.env,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message='Synthetic fixture'):
        self.git(self.repo, 'add', '-A')
        self.git(self.repo, 'commit', '--allow-empty', '-qm', message)
        return self.git(self.repo, 'rev-parse', 'HEAD')

    def history(self, notes=NOTES, published=PUBLISHED, published_version='0.0.98'):
        self.repo.mkdir()
        self.git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / 'README.md').write_text('# Synthetic public repository\n')
        for path, data in RUNTIME.items():
            (self.repo / path).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / path).write_bytes(data)
        self.anchor = self.commit('Synthetic public anchor')
        (self.repo / 'CHANGELOG.md').write_text(published)
        self.published = self.commit('Synthetic published version')
        self.git(self.repo, 'tag', '-a', 'v' + published_version, '-m', 'Synthetic published tag')
        self.notes = notes
        self.sources(notes)
        at = published.index('## ')
        (self.repo / 'CHANGELOG.md').write_text(published[:at] + notes + '\n' + published[at:])
        self.head = self.commit('Synthetic candidate')
        self.git(self.root, 'clone', '-q', '--bare', self.repo, self.remote)
        self.git(self.repo, 'remote', 'add', 'origin', PUBLIC_URL)

    def sources(self, notes):
        (self.repo / 'changes').mkdir(exist_ok=True)
        self.entry = {'versions': [], 'excluded': []}
        for index, part in enumerate(notes.split('\n## ') if notes else []):
            part = part if index == 0 else '## ' + part
            lines = part.rstrip('\n').split('\n')
            version, date = lines[0][3:].split(' · ')
            patch = int(version.split('.')[2])
            spec = 4000 + patch
            self.world[f'repos/{{owner}}/{{repo}}/issues/{spec}'] = {
                'number': spec, 'body': f'## Changelog headline\n\n{lines[2]}\n', 'pull': False, 'sub_issues': 2,
                'milestone': {'number': 900 + patch, 'title': version}}
            bullets = [line[2:] for line in lines if line.startswith('- ')]
            for k, bullet in enumerate(bullets):
                number = 10000 + patch * 100 + k
                (self.repo / f'changes/{number}.md').write_text(f'kind: added\n\n{bullet}\n')
                self.world[f'repos/{{owner}}/{{repo}}/issues/{number}'] = {
                    'number': number, 'body': '', 'pull': False, 'sub_issues': 0,
                    'milestone': {'number': 900 + patch, 'title': version}}
            tested = lines[-3] if bullets else 'Fixture-tested: Headline-only section.'
            self.entry['versions'].append({'version': version, 'spec': spec, 'date': date, 'tested': tested})
        if len(self.entry['versions']) == 1:
            self.entry['versions'] = {k: v for k, v in self.entry['versions'][0].items() if k != 'version'}
        self.world_path.write_text(json.dumps(self.world))

    def classification(self, **overrides):
        changed = self.git(self.repo, 'diff', '--name-only', '--no-renames', self.published, self.head).splitlines()
        return [dict({'path': p, 'send': 'no', 'new': 'no', 'app_permissions': 'no', 'spending': 'no'},
                     **overrides.get(p, {})) for p in changed]

    def artifacts(self, version=VERSION, folder=None):
        folder = folder or self.root / 'artifacts'
        folder.mkdir()
        sums, self.product_rows, self.product_receipts = [], [], []
        build = Path(tempfile.mkdtemp(prefix='build-', dir=self.root))
        for target in TARGETS:
            binaries, work = (build / f'{kind}-{target}' for kind in ('bin', 'work'))
            for path in (binaries, work):
                path.mkdir()
            receipts = rl4.build(binaries, self.head, target, work, version)
            identity, record = build_products.collect(self.repo, binaries, build / f'products-{target}', version,
                                                      self.head, target, receipts['program'])
            runtime = next(p for p in record['products'] if p['identity']['product'] == 'runtime')
            selection = sorted([repository, name] for repository, name in
                               ([p, 'runtime/' + p] if p.startswith('skills/') else [p, rl4.PACKAGED[p]]
                                for p in RUNTIME))
            selection = sorted(selection + [[p, 'runtime/' + p] for p in getattr(self, 'released', {})])
            if getattr(self, 'released', None):
                selection = sorted(selection + [['wizskills.lock', 'runtime/wizskills.lock']])
            assert sha(rl4.canonical({'source': self.head, 'selection': selection})) == runtime['build_receipt']['sha256']
            if getattr(self, 'swapped', None):
                selection = self.swap_packaged(build / f'products-{target}', identity, runtime, selection, *self.swapped)
            (build / f'identity-{target}.json').write_text(json.dumps(identity))
            out = build / f'bundle-{target}'
            package.assemble(build / f'products-{target}', build / f'identity-{target}.json', out)
            self.product_rows += record['products']
            self.product_receipts.append({
                'target': target, 'selection': selection,
                **{kind: {'name': receipts[kind].name, 'utf8': receipts[kind].read_text()} for kind in ('program',)}})
            for item in out.iterdir():
                if item.name == 'SHA256SUMS':
                    sums += item.read_text().splitlines(keepends=True)
                else:
                    shutil.copy(item, folder / item.name)
        (folder / 'SHA256SUMS').write_text(''.join(sums))
        return folder

    def body(self, version=VERSION, notes=None, promises=None, risk=None):
        notes = self.notes if notes is None else notes
        folder = self.root / 'artifacts'
        roles = {}
        for target in TARGETS:
            roles[f'openwiz-{version}-{target}.tar.gz'] = ('archive', target)
            roles[f'openwiz-{version}-{target}.manifest.json'] = ('manifest', target)
            roles[f'openwiz-{target}.manifest.json'] = ('manifest_alias', target)
            roles[f'openwiz-{target}.sha256'] = ('manifest_checksum', target)
        roles['SHA256SUMS'] = ('checksums', None)
        artifacts = [{'name': n, 'role': roles[n][0], 'target': roles[n][1],
                      'sha256': sha((folder / n).read_bytes()), 'bytes': (folder / n).stat().st_size}
                     for n in sorted(roles)]
        products = json.loads(json.dumps(self.product_rows))
        versions = promises or [(version, ['synthetic_fleet', 'synthetic_send'])]
        return {'source': {'repository': PUBLIC, 'commit': self.head,
                           'tree': self.git(self.repo, 'rev-parse', 'HEAD^{tree}'), 'anchor': self.anchor},
                'build_id': sha(b'synthetic build provenance'), 'release_version': versions[0][0],
                'included_versions': [{'version': v, 'section_sha256': section_sha(notes, v), 'promises': p}
                                      for v, p in versions],
                'changelog': {'utf8': notes, 'sha256': sha(notes.encode()), 'bytes': len(notes.encode())},
                'products': products, 'artifacts': artifacts,
                'kit': {'sha256': self.kit_sha, 'scope_sha256': self.scope_sha,
                        'authority': f'https://github.com/{PRIVATE}/issues/9000#issuecomment-9900'},
                'risk': risk or {'send': {'required': 'yes', 'reason': 'Synthetic send change.'},
                                 'new': {'required': 'yes', 'reason': 'Synthetic new change.'},
                                 'app_permissions': {'required': 'no', 'reason': 'Synthetic: no App change.'},
                                 'spending': {'required': 'no', 'reason': 'Synthetic: no spending change.'}}}

    def smoke_kit(self, coverage=None, version=VERSION):
        helper = receipts_fixture.Receipts('test_live_run_yields_candidate_bound_smoke_and_risk_receipts')
        helper.setUp()
        self.addCleanup(helper.tmp.cleanup)
        if coverage:
            helper.kit['release']['coverage'] = coverage
        tested = Path(helper.tmp.name) / 'tested-openwiz'
        tested.write_bytes(rl4.program(LINUX, rl4.identity('cli', self.head, LINUX, version)))
        helper.kit['artifacts'][str(tested)] = sha(tested.read_bytes())
        helper.live()
        self.helper = helper
        self.kit_sha = receipts_fixture.smoke.digest(helper.kit)
        self.scope_sha = canonical(helper.kit['release']['scope'])
        self.comment(9900, 'Private record: Jake, 2026-11-20, synthetic kit approval restated.\n'
                     f'Release kit authority: scope {self.scope_sha}\n', self.now - 3600)

    def save(self):
        self.world.update(self.comments)
        rows = {}
        for path, item in self.comments.items():
            issue = item['issue_url'].rsplit('/', 1)[1]
            rows.setdefault(issue, []).append(item)
        for issue, items in rows.items():
            self.world[f'repos/{PRIVATE}/issues/{issue}/comments?per_page=100'] = [items]
        self.world_path.write_text(json.dumps(self.world))

    def comment(self, number, body, at, issue=9000):
        self.comments[f'repos/{PRIVATE}/issues/comments/{number}'] = {
            'id': number, 'body': body, 'user': {'login': 'jparker2006'}, 'created_at': iso(at),
            'updated_at': iso(at), 'issue_url': f'https://api.github.com/repos/{PRIVATE}/issues/{issue}'}
        self.save()
        return f'https://github.com/{PRIVATE}/issues/{issue}#issuecomment-{number}'

    def cli(self, *args, anchor=None, **extra):
        result = subprocess.run([sys.executable, '-c', LAUNCH, str(HERE), anchor or self.anchor, *map(str, args)],
                                env=dict(self.env, **extra), capture_output=True, text=True, timeout=120)
        try:
            out = json.loads(result.stdout)
        except ValueError:
            self.fail(result.stdout + result.stderr)
        return result.returncode, out

    def calls(self):
        path = self.root / 'calls.jsonl'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def writes(self):
        return [c['action'] for c in self.calls() if c['action'] in ('main-push', 'tag', 'tag-push', 'release')]

    def blocked(self, result, *reasons):
        code, out = result
        self.assertEqual(code, 1, out)
        for reason in reasons:
            self.assertIn(reason, out['reasons'])
        return out

    def prepare(self, body=None, rows=None, **extra):
        path = self.root / 'body.json'
        path.write_text(json.dumps(body if body is not None else self.made))
        (self.root / 'entry.json').write_text(json.dumps(self.entry))
        (self.root / 'classification.json').write_text(json.dumps(self.classification() if rows is None else rows))
        return self.cli('prepare', '--state', self.state, '--repo', self.repo, '--body', path,
                        '--artifacts', self.root / 'artifacts', '--entry', self.root / 'entry.json',
                        '--classification', self.root / 'classification.json', **extra)

    def record(self):
        return json.loads((self.state / 'record.json').read_text())

    def decisions(self, ship_at=None, notes_at=None):
        record = self.record()
        ship_at = self.now - 900 if ship_at is None else ship_at
        notes_at = self.now - 780 if notes_at is None else notes_at
        self.ship = self.comment(9101, 'Private record: Jake, 2026-11-20, synthetic ship.\n'
                                 f'Release decision: ship {record["candidate_sha256"]}\n', ship_at)
        self.approval = self.comment(9102, 'Private record: Jake, 2026-11-20, synthetic changelog approval.\n'
                                     f'Release decision: changelog {record["candidate"]["changelog"]["sha256"]}\n',
                                     notes_at)
        self.assertEqual(self.cli('decide', '--state', self.state, '--ship', self.ship)[0], 0)
        self.assertEqual(self.cli('decide', '--state', self.state, '--changelog', self.approval)[0], 0)

    def checks(self, runs=None, workflows=None):
        actions = {'slug': 'github-actions'}
        self.world[f'repos/{PUBLIC}/commits/{self.head}/check-runs?per_page=100'] = [{'check_runs': runs or [
            {'id': 11, 'name': 'ci', 'head_sha': self.head, 'status': 'completed', 'conclusion': 'success',
             'app': actions, 'check_suite': {'id': 501}},
            {'id': 12, 'name': 'privacy', 'head_sha': self.head, 'status': 'completed', 'conclusion': 'success',
             'app': actions, 'check_suite': {'id': 502}}]}]
        self.world[f'repos/{PUBLIC}/actions/runs?head_sha={self.head}&per_page=100'] = [{'workflow_runs': workflows or [
            {'id': 601, 'path': '.github/workflows/ci.yml', 'head_sha': self.head, 'status': 'completed',
             'conclusion': 'success', 'check_suite_id': 501, 'run_attempt': 1, 'created_at': '2026-11-20T00:00:00Z'},
            {'id': 602, 'path': '.github/workflows/privacy.yml', 'head_sha': self.head, 'status': 'completed',
             'conclusion': 'success', 'check_suite_id': 502, 'run_attempt': 1, 'created_at': '2026-11-20T00:00:00Z'}]}]
        self.save()

    def receipt(self, gate, cls='source-inspection', status='pass', **extra):
        record = self.record()
        inputs = {'gate': gate, 'candidate_sha256': record['candidate_sha256'],
                  'artifacts_sha256': canonical(record['candidate']['artifacts'])}
        inputs.update({'ci': {'check_runs': [{'name': 'ci', 'id': 11}]},
                       'privacy': {'check_runs': [{'name': 'privacy', 'id': 12}]},
                       'claims': {'notes_sha256': record['candidate']['changelog']['sha256']},
                       'products': {'products': record['candidate']['products'],
                                    'receipts': self.product_receipts},
                       'cutover': {'repository': PUBLIC}}[gate])
        inputs.update(extra)
        number = 9200 + list(('cutover', 'ci', 'privacy', 'claims', 'products')).index(gate)
        body = f'Synthetic {gate} evidence for {record["candidate_sha256"]}.\n'
        pointer = self.comment(number, body, self.now - 600)
        receipt = {'candidate_sha256': record['candidate_sha256'], 'inputs_sha256': canonical(inputs),
                   'artifacts_sha256': inputs['artifacts_sha256'], 'kit_sha256': None, 'evidence_class': cls,
                   'status': status, 'started_at': self.now - 700, 'finished_at': self.now - 600,
                   'evidence': {'record': pointer, 'sha256': sha(body.encode())}, 'coverage': [], 'gaps': []}
        (self.root / f'{gate}-receipt.json').write_text(json.dumps(receipt))
        (self.root / f'{gate}-inputs.json').write_text(json.dumps(inputs))
        return self.cli('gate', '--state', self.state, '--gate', gate,
                        '--receipt', self.root / f'{gate}-receipt.json', '--inputs', self.root / f'{gate}-inputs.json',
                        '--repo', self.repo, '--artifacts', self.root / 'artifacts')

    def gates(self):
        self.checks()
        self.assertEqual(self.receipt('products', 'ci'), (0, {'status': 'recorded', 'gate': 'products'}))

    def smoke(self, *mode):
        self.helper.candidate = self.record()
        if mode:
            self.helper.execute(*mode)
        else:
            code, report = self.helper.execute()
            self.assertEqual((code, report['verdict'], report['evidence']), (0, 'pass', 'live'), report)
        pointer = f'https://github.com/{PRIVATE}/issues/9000#issuecomment-9301'
        result = self.cli('live', '--state', self.state, '--kit', self.helper.kit_path,
                          '--smoke-state', self.helper.state, '--record', pointer)
        if result[0] == 0:
            saved = json.loads((self.state / 'live.json').read_text())
            self.comment(9301, 'Synthetic preserved run record.\n' + str(saved['doc']['preserve']) + '\n',
                         self.now + 3600)
        return result

    def ready(self, body=None):
        self.smoke_kit()
        self.artifacts()
        self.made = body or self.body()
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        self.assertEqual(self.smoke()[0], 0)

    def evaluate(self, **extra):
        return self.cli('evaluate', '--state', self.state, '--repo', self.repo,
                        '--artifacts', self.root / 'artifacts', '--literals', self.literals, **extra)

    def publish(self, **extra):
        return self.cli('publish', '--state', self.state, '--repo', self.repo,
                        '--artifacts', self.root / 'artifacts', '--literals', self.literals, **extra)

    def latest(self, version=VERSION, latest=True):
        meta = self.releases / ('v' + version) / 'meta.json'
        meta.write_text(json.dumps(dict(json.loads(meta.read_text()), prerelease=not latest)))

    def install_check(self, target=LINUX, **extra):
        return self.cli('install', '--state', self.state, '--target', target, **extra)

    def downloads(self):
        return [c['args'][0] for c in self.calls() if c['tool'] == 'https']


class Candidate(World):
    def test_one_checked_candidate_publishes_without_a_third_human_action(self):
        self.ready()
        self.assertEqual(self.evaluate(), (0, {'status': 'ready', 'candidate_sha256': self.record()['candidate_sha256']}))
        before = self.git(self.remote, 'rev-parse', 'main')
        code, out = self.publish()
        self.assertEqual((code, out['status']), (0, 'published'), out)
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.assertEqual(self.git(self.remote, 'rev-parse', 'main'), before)
        self.assertEqual(self.git(self.remote, 'cat-file', '-t', 'refs/tags/v' + VERSION), 'tag')
        self.assertEqual(self.git(self.remote, 'rev-parse', f'refs/tags/v{VERSION}^{{}}'), self.head)
        created = next(c['args'] for c in self.calls() if c['action'] == 'release')
        self.assertIn('--verify-tag', created)
        self.assertIn('--prerelease', created)
        meta = json.loads((self.releases / ('v' + VERSION) / 'meta.json').read_text())
        self.assertEqual(meta['notes'], NOTES)
        uploaded = sorted(p.name for p in (self.releases / ('v' + VERSION) / 'assets').iterdir())
        self.assertEqual(uploaded, sorted(p.name for p in (self.root / 'artifacts').iterdir()))
        publication = self.record()['publication']
        self.assertEqual((publication['status'], publication['commit'], publication['immutable'],
                          publication['prerelease'], publication['notes_sha256']),
                         ('complete', self.head, True, True, sha(NOTES.encode())))
        self.assertEqual(publication['tag_object'], self.git(self.remote, 'rev-parse', 'refs/tags/v' + VERSION))
        self.assertEqual(self.publish(), (0, {'status': 'published', 'tag': 'v' + VERSION}))
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.latest()
        code, out = self.install_check()
        self.assertEqual((code, out['status'], out['target_met']), (0, 'complete', True), out)

    def test_install_check_takes_the_strangers_latest_route_and_refuses_a_prerelease(self):
        self.ready()
        self.assertEqual(self.publish()[0], 0)
        base = 'https://github.com/openwizdev/OpenWiz/releases/'
        name = 'openwiz-' + LINUX
        self.assertEqual(self.install_check(), (1, {'status': 'blocked', 'reasons': ['install_latest_unresolved']}))
        self.assertEqual(self.downloads(), [base + f'latest/download/{name}.sha256'])
        self.assertIsNone(self.record()['install'])
        other = self.artifacts('0.0.100', self.root / 'other')
        (self.releases / 'v0.0.100' / 'assets').mkdir(parents=True)
        for item in other.iterdir():
            shutil.copy(item, self.releases / 'v0.0.100' / 'assets' / item.name)
        (self.releases / 'v0.0.100' / 'meta.json').write_text(json.dumps({'prerelease': False}))
        self.assertEqual(self.install_check(), (1, {'status': 'blocked', 'reasons': ['install_latest_not_candidate']}))
        self.assertIsNone(self.record()['install'])
        shutil.rmtree(self.releases / 'v0.0.100')
        self.latest()
        archive = self.releases / ('v' + VERSION) / 'assets' / f'openwiz-{VERSION}-{LINUX}.tar.gz'
        good = archive.read_bytes()
        for planted, reason in ((good + b'x', 'install_download_refused'),
                                (good[:-1] + bytes([good[-1] ^ 1]), 'install_download_refused')):
            archive.write_bytes(planted)
            self.assertEqual(self.install_check(), (1, {'status': 'blocked', 'reasons': [reason]}))
            self.assertIsNone(self.record()['install'])
        archive.write_bytes(good)
        sealed = (self.state / 'record.json').read_bytes()
        other = self.record()
        row = next(a for a in other['candidate']['artifacts'] if (a['role'], a['target']) == ('archive', LINUX))
        row['sha256'] = sha(b'x')
        (self.state / 'record.json').write_text(json.dumps(other))
        self.assertEqual(self.install_check(), (1, {'status': 'blocked', 'reasons': ['install_mismatch']}))
        (self.state / 'record.json').write_bytes(sealed)
        (self.root / 'calls.jsonl').unlink()
        code, out = self.install_check()
        self.assertEqual((code, out['status']), (0, 'complete'), out)
        self.assertEqual(self.downloads(), [base + f'latest/download/{name}.sha256',
                                            base + f'latest/download/{name}.manifest.json',
                                            base + f'download/v{VERSION}/openwiz-{VERSION}-{LINUX}.tar.gz',
                                            base + f'download/v{VERSION}/SHA256SUMS'])
        self.assertNotIn(['release', 'download'], [c['args'][:2] for c in self.calls()])
        installed = self.record()['install']
        self.assertEqual(sorted(installed), sorted(SCHEMA['$defs']['install']['required']))
        saved = self.state / installed['evidence']['record']
        self.assertEqual(sha(saved.read_bytes()), installed['evidence']['sha256'])
        self.assertEqual([d['url'] for d in json.loads(saved.read_text())['downloads']], self.downloads())
        passed = self.cli('status', '--state', self.state)[1]
        self.assertEqual(self.install_check(FETCH_STATUS='503'),
                         (1, {'status': 'blocked', 'reasons': ['install_download_refused']}))
        self.assertEqual(self.record()['install'], installed)
        self.assertEqual(sha(saved.read_bytes()), installed['evidence']['sha256'])
        status = self.cli('status', '--state', self.state)[1]
        [attempt] = status.pop('install_attempts')
        self.assertEqual((status['status'], status['finished_at']), ('incomplete', passed['finished_at']))
        self.assertEqual({k: attempt[k] for k in ('target', 'status', 'reasons')},
                         {'target': LINUX, 'status': 'blocked', 'reasons': ['install_download_refused']})
        failed = self.state / attempt['evidence']['record']
        self.assertNotEqual(failed, saved)
        self.assertEqual(sha(failed.read_bytes()), attempt['evidence']['sha256'])
        self.assertEqual(json.loads(failed.read_text())['downloads'][0]['status'], 503)
        rows = {(a['role'], a['target']): a['sha256'] for a in self.record()['candidate']['artifacts']}
        self.assertEqual({k: installed[k] for k in ('route', 'version', 'source', 'target', 'manifest_sha256',
                                                    'archive_sha256')},
                         {'route': 'install', 'version': VERSION, 'source': self.head, 'target': LINUX,
                          'manifest_sha256': rows[('manifest', LINUX)], 'archive_sha256': rows[('archive', LINUX)]})

    def test_overlapping_install_checks_for_two_targets_keep_both_attempts(self):
        self.ready()
        self.assertEqual(self.publish()[0], 0)
        hold = self.root / 'hold'
        hold.mkdir()
        mac = 'aarch64-apple-darwin'
        runs = [subprocess.Popen([sys.executable, '-c', LAUNCH, str(HERE), self.anchor, 'install', '--state',
                                  str(self.state), '--target', target], stdout=subprocess.PIPE, text=True,
                                 env=dict(self.env, HOLD=HOLD_INDEX, HOLD_DIR=str(hold), HOLD_ME=me))
                for target, me in ((LINUX, 'first'), (mac, 'second'))]
        for run in runs:
            out, _ = run.communicate(timeout=120)
            self.assertEqual((run.returncode, json.loads(out)),
                             (1, {'status': 'blocked', 'reasons': ['install_latest_unresolved']}))
        status = self.cli('status', '--state', self.state)[1]
        self.assertEqual(sorted((a['target'], a['status']) for a in status.get('install_attempts', [])),
                         [(mac, 'blocked'), (LINUX, 'blocked')])
        for attempt in status['install_attempts']:
            saved = self.state / attempt['evidence']['record']
            self.assertEqual(sha(saved.read_bytes()), attempt['evidence']['sha256'])

    def test_missing_ship_or_exact_changelog_approval_refuses_before_any_write(self):
        self.smoke_kit()
        self.artifacts()
        self.made = self.body()
        self.assertEqual(self.prepare()[0], 0)
        self.gates()
        self.assertEqual(self.smoke()[0], 0)
        self.blocked(self.publish(), 'ship_missing', 'changelog_missing')
        record = self.record()
        approval = self.comment(9102, 'Private record: Jake, 2026-11-20, synthetic changelog approval.\n'
                                f'Release decision: changelog {record["candidate"]["changelog"]["sha256"]}\n',
                                self.now - 60)
        self.assertEqual(self.cli('decide', '--state', self.state, '--changelog', approval)[0], 0)
        out = self.blocked(self.publish(), 'ship_missing')
        self.assertNotIn('changelog_missing', out['reasons'])
        self.assertEqual(self.writes(), [])

    def test_invented_or_unrecorded_approval_is_never_a_decision(self):
        self.ready()
        record = self.record()
        sealed = record['candidate_sha256']
        flag = subprocess.run([sys.executable, '-c', LAUNCH, str(HERE), self.anchor, 'publish', '--state',
                               str(self.state), '--repo', str(self.repo), '--artifacts', str(self.root / 'artifacts'),
                               '--literals', str(self.literals), '--approval', 'publish ' + VERSION],
                              env=self.env, capture_output=True, text=True)
        self.assertEqual(flag.returncode, 2, flag.stdout)
        self.assertIn('unrecognized arguments: --approval', flag.stderr)
        cases = {
            'agent-written': ('Builder: approved, ship it.\nRelease decision: ship ' + sealed + '\n', {}),
            'edited': ('Private record: Jake, 2026-11-20.\nRelease decision: ship ' + sealed + '\n',
                       {'updated_at': iso(self.now)}),
            'other author': ('Private record: Jake, 2026-11-20.\nRelease decision: ship ' + sealed + '\n',
                             {'user': {'login': 'synthetic-other'}}),
            'no binding': ('Private record: Jake, 2026-11-20. Ship it.\n', {})}
        for name, (body, change) in cases.items():
            with self.subTest(case=name):
                pointer = self.comment(9150, body, self.now - 900)
                self.comments[f'repos/{PRIVATE}/issues/comments/9150'].update(change)
                self.save()
                self.blocked(self.cli('decide', '--state', self.state, '--ship', pointer), 'ship_not_a_decision')
        foreign = f'https://github.com/example-owner/example-repo/issues/1#issuecomment-1'
        self.blocked(self.cli('decide', '--state', self.state, '--ship', foreign), 'pointer_invalid')
        self.comment(9160, 'Synthetic note quoting `Release decision revoked: 9101` for review.\n', self.now - 10)
        self.assertEqual(self.evaluate()[0], 0)
        self.comment(9160, 'Release decision revoked: 9101\n', self.now - 10)
        self.blocked(self.publish(), 'ship_revoked')
        del self.comments[f'repos/{PRIVATE}/issues/comments/9160']
        self.world.pop(f'repos/{PRIVATE}/issues/comments/9160')
        self.save()
        record['decisions']['ship']['decided_at'] -= 3600
        (self.state / 'record.json').write_text(json.dumps(record))
        self.blocked(self.publish(), 'ship_changed')
        self.assertEqual(self.writes(), [])

    def test_changed_notes_or_candidate_refuse_until_their_decisions_match(self):
        self.ready()
        first = self.record()
        shutil.rmtree(self.root / 'artifacts')
        self.artifacts()
        (self.root / 'artifacts' / 'SHA256SUMS').write_text((self.root / 'artifacts' / 'SHA256SUMS').read_text())
        rebuilt = self.body()
        rebuilt['build_id'] = sha(b'synthetic second build')
        self.made = rebuilt
        self.assertEqual(self.prepare()[0], 0)
        second = self.record()
        self.assertNotEqual(second['candidate_sha256'], first['candidate_sha256'])
        self.assertEqual(second['timing']['original_ship_at'], first['timing']['original_ship_at'])
        out = self.blocked(self.publish(), 'ship_stale', 'products_missing', 'smoke_missing')
        self.assertFalse([r for r in out['reasons'] if r.startswith('changelog')], out)
        self.assertEqual(self.writes(), [])

    def test_changed_notes_after_approval_refuse(self):
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        changed = NOTES.replace('You can save a preview.', 'You can save every preview.')
        self.notes = changed
        self.helper.tmp.cleanup()
        for path in (self.root / 'artifacts',):
            shutil.rmtree(path)
        shutil.rmtree(self.repo)
        shutil.rmtree(self.remote)
        self.history(notes=changed)
        self.smoke_kit()
        self.artifacts()
        shutil.rmtree(self.state)
        self.made = self.body()
        self.assertEqual(self.prepare()[0], 0)
        self.gates()
        self.assertEqual(self.smoke()[0], 0)
        old = self.approval
        self.assertEqual(self.cli('decide', '--state', self.state, '--changelog', old)[1]['reasons'],
                         ['changelog_binding_mismatch'])
        tampered = self.body()
        tampered['changelog']['sha256'] = sha(NOTES.encode())
        shutil.rmtree(self.state)
        self.blocked(self.prepare(tampered), 'changelog_changed')
        self.assertEqual(self.writes(), [])

    def test_private_or_unrelated_source_and_absent_cutover_refuse(self):
        self.smoke_kit()
        self.artifacts()
        good = self.body()
        private = json.loads(json.dumps(good))
        private['source']['repository'] = PRIVATE
        self.blocked(self.prepare(private), 'private_source')
        (self.root / 'body.json').write_text(json.dumps(good))
        (self.root / 'entry.json').write_text(json.dumps(self.entry))
        (self.root / 'classification.json').write_text(json.dumps(self.classification()))
        code, out = self.cli('prepare', '--state', self.state, '--repo', self.repo, '--body', self.root / 'body.json',
                             '--artifacts', self.root / 'artifacts', '--entry', self.root / 'entry.json',
                             '--classification', self.root / 'classification.json', anchor='e' * 40)
        self.assertEqual((code, out['reasons']), (1, ['unrelated_history']))
        self.git(self.repo, 'commit', '--amend', '--no-edit', '-q', '--date', '2001-01-01T00:00:00')
        local = json.loads(json.dumps(good))
        local['source']['commit'] = self.git(self.repo, 'rev-parse', 'HEAD')
        self.blocked(self.prepare(local), 'not_on_public_main')
        self.git(self.repo, 'reset', '-q', '--hard', self.head)
        self.git(self.repo, 'remote', 'set-url', 'origin', f'https://github.com/{PRIVATE}.git')
        self.blocked(self.prepare(good), 'private_source')
        self.git(self.repo, 'remote', 'set-url', 'origin', 'https://github.com/openwizdev/openwiz2.git')
        self.blocked(self.prepare(good), 'private_source')
        self.git(self.repo, 'remote', 'set-url', 'origin', 'https://github.com/OpenWizDev/OPENWIZ.git')
        self.made = good
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        self.assertEqual(self.smoke()[0], 0)
        self.assertEqual(self.evaluate()[0], 0)
        self.d3_cutover_read_backs_refuse()

    def release_branch(self, name='release-' + VERSION, ruleset=None):
        self.git(self.repo, 'checkout', '-q', '-b', 'release')
        (self.repo / 'README.md').write_text('# Synthetic public repository\n\nSynthetic cherry-picked fix.\n')
        self.head = self.commit('Synthetic cherry-picked fix')
        self.git(self.repo, 'push', '-q', self.remote, f'HEAD:refs/heads/{name}')
        self.git(self.root / 'public.git', 'update-ref', 'refs/heads/main', self.published)
        self.world[f'repos/{PUBLIC}/rulesets?per_page=100'] = [[{'id': 71}, {'id': 72}]]
        self.world[f'repos/{PUBLIC}/rulesets/72'] = ruleset or {
            'id': 72, 'enforcement': 'active', 'target': 'branch', 'bypass_actors': [],
            'conditions': {'ref_name': {'include': ['refs/heads/release-*'], 'exclude': []}},
            'rules': [{'type': 'deletion'}, {'type': 'non_fast_forward'},
                      {'type': 'required_status_checks', 'parameters': {'required_status_checks': [
                          {'context': 'ci'}, {'context': 'privacy'}]}}]}
        self.save()

    def test_964_a_candidate_on_its_protected_release_branch_publishes(self):
        self.release_branch()
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        code, out = self.publish()
        self.assertEqual((code, out['status']), (0, 'published'), out)
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.assertEqual(self.git(self.remote, 'rev-parse', f'refs/tags/v{VERSION}^{{}}'), self.head)
        self.assertEqual(self.git(self.remote, 'rev-parse', 'main'), self.published)

    def test_2127_an_unreadable_release_branch_gives_evaluate_publishs_reasons(self):
        self.release_branch()
        self.ready()

        def checked():
            return [p['name'] for p in self.record()['timing']['phases']].count('checks')
        before = checked()
        evaluated = self.blocked(self.evaluate(FAIL_ACTION='fetch'), 'release_branch_unreadable')
        self.assertEqual(checked(), before + 1)
        refused = self.blocked(self.publish(FAIL_ACTION='fetch'), 'release_branch_unreadable')
        self.assertEqual((evaluated['status'], evaluated['reasons']), ('blocked', refused['reasons']))
        self.assertEqual(self.writes(), [])

    def test_964_each_unproven_release_branch_refuses_with_its_reason(self):
        self.release_branch()
        self.smoke_kit()
        self.artifacts()
        self.made = self.body()
        rules = f'repos/{PUBLIC}/rulesets/72'
        checks = {'type': 'required_status_checks', 'parameters': {'required_status_checks': [
            {'context': 'ci'}, {'context': 'privacy'}]}}
        for name, change, reason in (
                ('force-push allowed', {'rules': [{'type': 'deletion'}, checks]}, 'release_branch_unprotected'),
                ('deletion allowed', {'rules': [{'type': 'non_fast_forward'}, checks]}, 'release_branch_unprotected'),
                ('privacy not required', {'rules': [{'type': 'deletion'}, {'type': 'non_fast_forward'}, {
                    'type': 'required_status_checks', 'parameters': {'required_status_checks': [{'context': 'ci'}]}}]},
                 'release_branch_unprotected'),
                ('a bypass actor', {'bypass_actors': [{'actor_type': 'RepositoryRole', 'actor_id': 5}]},
                 'release_branch_unprotected'),
                ('ruleset disabled', {'enforcement': 'disabled'}, 'release_branch_unprotected'),
                ('only main covered', {'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'], 'exclude': []}}},
                 'release_branch_unprotected'),
                ('branch excluded', {'conditions': {'ref_name': {'include': ['~ALL'],
                                                                 'exclude': [f'refs/heads/release-{VERSION}']}}},
                 'release_branch_unprotected'),
                ('an unevaluable condition', {'conditions': {'ref_name': {'include': ['refs/heads/**']}}},
                 'release_ruleset_unreadable')):
            with self.subTest(case=name):
                before = json.loads(json.dumps(self.world[rules]))
                self.world[rules].update(change)
                self.save()
                self.assertEqual(self.prepare()[1]['reasons'], [reason])
                self.world[rules] = before
                self.save()
        with self.subTest(case='ruleset unreadable'):
            self.world['_fail'] = [rules]
            self.save()
            self.assertEqual(self.prepare()[1]['reasons'], ['release_ruleset_unreadable'])
            del self.world['_fail']
            self.save()
        with self.subTest(case='branch unreadable'):
            self.assertEqual(self.prepare(FAIL_ACTION='fetch')[1]['reasons'], ['release_branch_unreadable'])
        branch = f'refs/heads/release-{VERSION}'
        with self.subTest(case='not reachable from the branch'):
            self.git(self.remote, 'update-ref', branch, self.published)
            self.assertEqual(self.prepare()[1]['reasons'], ['not_on_release_branch'])
        with self.subTest(case='the branch of another version'):
            self.git(self.remote, 'update-ref', 'refs/heads/release-0.0.98', self.head)
            self.git(self.remote, 'update-ref', '-d', branch)
            self.assertEqual(self.prepare()[1]['reasons'], ['release_branch_wrong_version'])
        self.assertEqual(self.writes(), [])

    def d3_cutover_read_backs_refuse(self):
        public = f'repos/{PUBLIC}'
        for name in ('openwizdev/openwiz', 'openwizdev/OpenWiz', 'OpenWizDev/OPENWIZ'):
            with self.subTest(full_name=name):
                self.world[public]['full_name'] = name
                self.save()
                code, out = self.evaluate()
                self.assertEqual(code, 0, out)
        self.world[public]['full_name'] = PUBLIC
        self.save()
        rules = f'repos/{PUBLIC}/rulesets/71'
        o16, o17 = f'repos/{PRIVATE}/issues/1284', f'repos/{PRIVATE}/issues/1285'
        held = [{'name': 'held'}]
        for name, path, change in (
                ('O17 open', o17, {'state': 'open', 'state_reason': None}),
                ('O17 not completed', o17, {'state_reason': 'not_planned'}),
                ('O17 held', o17, {'labels': held}),
                ('O16 held', o16, {'labels': held}),
                ('public repository private', f'repos/{PUBLIC}', {'visibility': 'private'}),
                ('another repository', f'repos/{PUBLIC}', {'full_name': 'openwizdev/openwiz2'}),
                ('immutable releases off', f'repos/{PUBLIC}/immutable-releases', {'enabled': False}),
                ('a bypass actor', rules, {'bypass_actors': [{'actor_type': 'RepositoryRole', 'actor_id': 5}]}),
                ('ruleset disabled', rules, {'enforcement': 'disabled'}),
                ('privacy not required', rules, {'rules': [{'type': 'required_status_checks', 'parameters': {
                    'required_status_checks': [{'context': 'ci'}]}}]}),
                ('main excluded', rules, {'conditions': {'ref_name': {'include': ['~ALL'],
                                                                      'exclude': ['refs/heads/main']}}}),
                ('default branch excluded', rules, {'conditions': {'ref_name': {'include': ['~DEFAULT_BRANCH'],
                                                                                'exclude': ['~DEFAULT_BRANCH']}}}),
                ('main excluded by a pattern', rules, {'conditions': {'ref_name': {'include': ['refs/heads/*'],
                                                                                   'exclude': ['refs/heads/ma*']}}}),
                ('an unevaluable condition', rules, {'conditions': {'ref_name': {'include': ['~ALL'], 'exclude': []},
                                                                    'repository_name': {'include': ['~ALL']}}})):
            with self.subTest(case=name):
                before = json.loads(json.dumps(self.world[path]))
                self.world[path].update(change)
                self.save()
                self.assertEqual(self.blocked(self.publish(), 'cutover_unverified')['reasons'], ['cutover_unverified'])
                self.world[path] = before
                self.save()
        raw = 'FAIL: verification failed, no valid evidence.\n'
        self.comment(9200, raw, self.now)
        (self.root / 'cutover-receipt.json').write_text(json.dumps({'status': 'pass', 'evidence': {
            'record': f'https://github.com/{PRIVATE}/issues/9000#issuecomment-9200', 'sha256': sha(raw.encode())}}))
        (self.root / 'cutover-inputs.json').write_text('{}')
        self.blocked(self.cli('gate', '--state', self.state, '--gate', 'cutover', '--receipt',
                              self.root / 'cutover-receipt.json', '--inputs', self.root / 'cutover-inputs.json'),
                     'cutover_read_by_the_command')
        self.assertEqual(self.writes(), [])

    def test_missing_failed_unreadable_or_untrusted_ci_and_privacy_refuse(self):
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        path = f'repos/{PUBLIC}/commits/{self.head}/check-runs?per_page=100'
        flows = f'repos/{PUBLIC}/actions/runs?head_sha={self.head}&per_page=100'
        runs, workflows = self.world[path][0]['check_runs'], self.world[flows][0]['workflow_runs']
        retried = dict(workflows[0], id=603, check_suite_id=503, conclusion='failure', created_at='2026-11-20T01:00:00Z')
        for name, check, flow, reasons in (
                ('missing', [runs[1]], workflows, ['ci_missing']),
                ('failed', [dict(runs[0], conclusion='failure'), runs[1]], workflows, ['ci_failed']),
                ('privacy failed', [runs[0], dict(runs[1], conclusion='failure')], workflows, ['privacy_failed']),
                ('other commit', [dict(runs[0], head_sha='f' * 40), runs[1]], workflows, ['ci_failed']),
                ('another app', [dict(runs[0], app={'slug': 'synthetic-app'}), runs[1]], workflows, ['ci_untrusted']),
                ('untrusted workflow', runs, [dict(workflows[0], path='.github/workflows/other.yml'), workflows[1]],
                 ['ci_untrusted']),
                ('latest attempt failed', runs + [dict(runs[0], id=13, conclusion='failure', check_suite={'id': 503})],
                 workflows + [retried], ['ci_failed']),
                ('run from an older suite', runs, [dict(retried, conclusion='success'), workflows[1]], ['ci_failed'])):
            with self.subTest(case=name):
                self.world[path] = [{'check_runs': []}, {'check_runs': check}]
                self.world[flows] = [{'workflow_runs': []}, {'workflow_runs': flow}]
                self.save()
                self.assertEqual(self.blocked(self.publish(), *reasons)['reasons'], reasons)
        self.world[path], self.world[flows] = [{'check_runs': runs}], [{'workflow_runs': workflows}]
        self.world['_fail'] = [flows]
        self.save()
        self.blocked(self.publish(), 'ci_unreadable', 'privacy_unreadable')
        self.world['_fail'] = []
        self.save()
        for gate in ('ci', 'privacy', 'claims'):
            with self.subTest(gate=gate):
                self.blocked(self.cli('gate', '--state', self.state, '--gate', gate, '--receipt', self.root / 'x.json',
                                      '--inputs', self.root / 'x.json'), f'{gate}_read_by_the_command')
        self.assertEqual(self.evaluate()[0], 0)
        self.assertEqual(self.writes(), [])

    def test_a_run_whose_ci_job_was_skipped_is_not_evidence(self):
        self.ready()
        path = f'repos/{PUBLIC}/commits/{self.head}/check-runs?per_page=100'
        flows = f'repos/{PUBLIC}/actions/runs?head_sha={self.head}&per_page=100'
        runs, workflows = self.world[path][0]['check_runs'], self.world[flows][0]['workflow_runs']
        queued = dict(workflows[0], event='merge_group')
        pushed = dict(workflows[0], id=604, event='push', check_suite_id=504, created_at='2026-11-20T01:00:00Z')
        skipped = dict(runs[0], id=14, conclusion='skipped', check_suite={'id': 504})
        self.world[path] = [{'check_runs': runs + [skipped]}]
        self.world[flows] = [{'workflow_runs': [queued, pushed, workflows[1]]}]
        self.save()
        self.assertEqual(self.evaluate()[0], 0)
        self.world[path] = [{'check_runs': [dict(runs[0], conclusion='skipped'), skipped, runs[1]]}]
        self.save()
        self.assertEqual(self.blocked(self.publish(), 'ci_missing')['reasons'], ['ci_missing'])
        self.assertEqual(self.writes(), [])

    def test_r1_products_pass_only_through_rl4s_verifiers_of_the_staged_archives(self):
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        good = json.loads((self.root / 'products-inputs.json').read_text())
        swapped = json.loads(json.dumps(good['receipts']))
        swapped[0]['program'], swapped[2]['program'] = swapped[2]['program'], swapped[0]['program']
        stale = json.loads(json.dumps(good['receipts']))
        stale[1]['selection'] = stale[1]['selection'][1:]
        for name, receipts in (('no receipts', []), ('another target\'s program receipt', swapped),
                               ('partial runtime selection', stale)):
            with self.subTest(case=name):
                self.blocked(self.receipt('products', 'ci', receipts=receipts), 'products_unverified')
        self.assertEqual(self.receipt('products', 'ci'), (0, {'status': 'recorded', 'gate': 'products'}))
        self.assertEqual(self.writes(), [])

    def swap_packaged(self, products, identity, runtime, selection, first, second):
        names = ('runtime/' + first, 'runtime/' + second)
        data = [(products / name).read_bytes() for name in names]
        for name, bytes_ in zip(names, reversed(data)):
            (products / name).write_bytes(bytes_)
        rows = {row['path']: row for row in identity['assets']}
        a, b = (rows[name] for name in names)
        for key in ('sha256', 'bytes'):
            a[key], b[key] = b[key], a[key]
        runtime['payload_sha256'] = build_products.payload([r for r in identity['assets'] if r['path'].startswith('runtime/')])
        selection = [pair for pair in selection if pair[0] not in (first, second)]
        selection = sorted(selection + [[first, names[1]], [second, names[0]]])
        runtime['build_receipt']['sha256'] = sha(rl4.canonical({'source': self.head, 'selection': selection}))
        return selection

    def lock_mode(self):
        install = self.repo / '.wizskills'
        install.mkdir()
        self.released = RELEASED_CONTRACTS
        for path, data in {**RUNTIME, **RELEASED_CONTRACTS}.items():
            if path.startswith(('skills/', 'contracts/')):
                (install / path).parent.mkdir(parents=True, exist_ok=True)
                (install / path).write_bytes(data)
        (install / 'README.md').write_text('Synthetic WizSkills.\n')
        self.git(install, 'init', '-q')
        self.git(install, 'add', '-A')
        self.git(install, 'commit', '-q', '-m', 'Synthetic WizSkills release')
        lock = {'version': '0.1.2', 'commit': self.git(install, 'rev-parse', 'HEAD'),
                'tree': self.git(install, 'rev-parse', 'HEAD^{tree}')}
        self.git(self.repo, 'rm', '-rq', 'skills')
        os.symlink('.wizskills/skills', self.repo / 'skills')
        (self.repo / '.gitignore').write_text('/.wizskills/\n')
        (self.repo / 'wizskills.lock').write_text(json.dumps(lock) + '\n')
        self.head = self.commit('Synthetic cut: skills from WizSkills')
        self.git(self.repo, 'push', '-q', self.remote, 'HEAD:main')
        self.env['WIZSKILLS_INSTALL'] = str(install)
        return install

    def test_wz12_products_from_the_pinned_install_pass_and_a_tampered_install_is_refused(self):
        install = self.lock_mode()
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        self.assertEqual(self.receipt('products', 'ci'), (0, {'status': 'recorded', 'gate': 'products'}))
        skill = install / 'skills/synthetic/SKILL.md'
        skill.write_bytes(skill.read_bytes() + b'Edited after packaging.\n')
        self.blocked(self.receipt('products', 'ci'), 'products_unverified')
        self.assertEqual(self.writes(), [])

    def test_r1_a_locked_contract_packaged_at_another_contracts_path_is_refused(self):
        self.lock_mode()
        self.swapped = ('contracts/alpha.v1.md', 'contracts/beta.v1.md')
        self.smoke_kit()
        self.artifacts()
        self.made = self.body()
        self.assertEqual(self.prepare()[0], 0)
        self.decisions()
        self.checks()
        self.blocked(self.receipt('products', 'ci'), 'products_unverified')
        self.assertEqual(self.writes(), [])

    def test_d2_a_private_term_in_any_staged_runtime_file_refuses(self):
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        self.literals.write_text('synthetic-private-term-zq\nSynthetic installer\n')
        self.assertEqual(self.blocked(self.publish(), 'privacy_finding')['reasons'], ['privacy_finding'])
        self.literals.unlink()
        self.assertEqual(self.blocked(self.publish(), 'privacy_literals_missing')['reasons'],
                         ['privacy_literals_missing'])
        self.assertEqual(self.writes(), [])

    def curate(self, curated, released=None):
        at = PUBLISHED.index('## ')
        whole = PUBLISHED[:at] + curated + '\n' + PUBLISHED[at:]
        (self.repo / 'changes/notes').mkdir(exist_ok=True)
        (self.repo / 'changes/notes/0.0.99.md').write_text(whole)
        (self.repo / 'CHANGELOG.md').write_text(whole)
        self.head = self.commit('Synthetic curated notes')
        self.git(self.repo, 'push', '-q', self.remote, 'HEAD:main')
        self.notes = curated if released is None else released
        self.entry = {'curated': 'changes/notes/0.0.99.md', 'curated_sha256': sha(whole.encode()),
                      'notes_sha256': sha(curated.encode()), 'included': [VERSION]}

    def test_rl6_curated_notes_pass_every_gate_and_publish_exactly(self):
        self.curate(CURATED)
        self.ready()
        self.assertEqual(self.evaluate(), (0, {'status': 'ready', 'candidate_sha256': self.record()['candidate_sha256']}))
        self.assertEqual(self.blocked(self.publish(TODAY='2026-11-21'), 'changelog_date')['reasons'], ['changelog_date'])
        self.assertEqual(self.writes(), [])
        self.assertEqual(self.publish()[1]['status'], 'published')
        self.assertEqual(json.loads((self.releases / ('v' + VERSION) / 'meta.json').read_text())['notes'], CURATED)

    def test_rl6_approved_notes_that_are_not_the_curated_sections_refuse(self):
        self.curate(CURATED, released=CURATED.replace('cancel a preview', 'cancel any preview'))
        self.ready()
        self.assertEqual(self.blocked(self.publish(), 'claims_mismatch')['reasons'], ['claims_mismatch'])
        self.assertEqual(self.writes(), [])

    def test_d4_notes_must_be_exactly_what_changes_generates_at_the_candidate(self):
        (self.repo / 'changes/19901.md').write_text('kind: added\n\nFixture-tested: You can cancel every preview.\n')
        self.head = self.commit('Synthetic changed source line')
        self.git(self.repo, 'push', '-q', self.remote, 'HEAD:main')
        self.ready()
        self.assertEqual(self.blocked(self.publish(), 'claims_mismatch')['reasons'], ['claims_mismatch'])
        self.assertEqual(self.writes(), [])

    def test_r12_preparing_the_same_candidate_refreshes_its_supporting_inputs(self):
        right = json.loads(json.dumps(self.entry))
        wrong = json.loads(json.dumps(right))
        wrong['versions']['tested'] = 'Fixture-tested: A mistaken tested line.'
        self.entry = wrong
        self.ready()
        self.assertEqual(self.blocked(self.evaluate(), 'claims_mismatch')['reasons'], ['claims_mismatch'])
        first = self.record()
        self.entry = right
        rows = self.classification()
        rows[0]['new'] = 'yes'
        self.assertEqual(self.prepare(rows=rows), (0, {'status': 'prepared', 'candidate_sha256':
                                                       first['candidate_sha256'], 'unchanged': False}))
        self.assertEqual(json.loads((self.state / 'classification.json').read_text()), rows)
        second = self.record()
        for name in ('candidate', 'decisions', 'timing'):
            self.assertEqual(second[name], first[name], name)
        self.assertEqual(second['gates']['products'], first['gates']['products'])
        self.assertEqual(self.evaluate(), (0, {'status': 'ready', 'candidate_sha256': first['candidate_sha256']}))
        self.assertIsNotNone(self.record()['gates']['claims'])
        self.assertEqual(self.prepare(rows=rows), (0, {'status': 'prepared', 'candidate_sha256':
                                                       first['candidate_sha256'], 'unchanged': True}))
        before = self.record()
        self.entry = wrong
        self.assertEqual(self.prepare(rows=rows)[1]['unchanged'], False)
        after = self.record()
        self.assertIsNone(after['gates']['claims'])
        before['gates']['claims'] = None
        self.assertEqual(after, before)
        self.blocked(self.evaluate(), 'claims_mismatch')
        self.entry = right
        self.assertEqual(self.prepare(rows=rows)[0], 0)
        self.assertEqual(self.publish(FAIL_ACTION='tag-push')[0], 1)
        attempt = (self.state / 'attempt.json').read_bytes()
        self.entry = wrong
        self.assertEqual(self.blocked(self.prepare(rows=rows), 'publication_started')['reasons'],
                         ['publication_started'])
        self.assertEqual((self.state / 'attempt.json').read_bytes(), attempt)
        self.assertEqual(json.loads((self.state / 'entry.json').read_text()), right)
        self.entry = right
        self.assertEqual(self.prepare(rows=rows)[1]['unchanged'], True)
        self.assertEqual(self.writes(), ['tag', 'tag-push'])

    def test_r11_only_a_revocation_posted_after_its_record_revokes_it(self):
        self.ready()
        for target, number, decided, reason in ((9101, 9160, self.now - 900, 'ship'),
                                                (9900, 9161, self.now - 3600, 'kit_authority')):
            path = f'repos/{PRIVATE}/issues/comments/{number}'
            for name, created, expected in (
                    ('earlier', iso(decided - 60), None),
                    ('earlier, then edited', iso(decided - 60), f'{reason}_revoked'),
                    ('later', iso(decided + 60), f'{reason}_revoked'),
                    ('same second', iso(decided), f'{reason}_unreadable'),
                    ('unreadable time', 'synthetic-not-a-time', f'{reason}_unreadable'),
                    ('no time', None, f'{reason}_unreadable')):
                with self.subTest(record=reason, case=name):
                    self.comment(number, f'Release decision revoked: {target}\n', decided)
                    self.comments[path].update(created_at=created,
                                               updated_at=iso(decided) if 'edited' in name else created)
                    self.save()
                    if expected is None:
                        self.assertEqual(self.evaluate()[0], 0)
                    else:
                        self.assertEqual(self.blocked(self.publish(), expected)['reasons'], [expected])
            del self.comments[path]
            self.world.pop(path)
            self.save()
        self.assertEqual(self.writes(), [])

    def test_r3_kit_authority_must_name_this_scope_and_still_apply(self):
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        grant = f'repos/{PRIVATE}/issues/comments/9900'
        original = json.loads(json.dumps(self.comments[grant]))
        for name, change, reason in (
                ('missing', None, 'kit_authority_unreadable'),
                ('another scope', {'body': original['body'].replace(self.scope_sha, 'e' * 64)}, 'kit_authority_scope'),
                ('edited', {'updated_at': iso(self.now)}, 'kit_authority_not_a_grant'),
                ('not a private record', {'body': 'Agent note.\nRelease kit authority: scope ' + self.scope_sha + '\n'},
                 'kit_authority_not_a_grant')):
            with self.subTest(case=name):
                if change is None:
                    del self.comments[grant]
                    self.world.pop(grant)
                else:
                    self.comments[grant] = dict(original, **change)
                self.save()
                self.assertEqual(self.blocked(self.publish(), reason)['reasons'], [reason])
                self.comments[grant] = original
                self.save()
        self.comment(9161, 'Release decision revoked: 9900\n', self.now)
        self.assertEqual(self.blocked(self.publish(), 'kit_authority_revoked')['reasons'], ['kit_authority_revoked'])
        self.assertEqual(self.writes(), [])

    def test_r4_every_no_rests_on_a_complete_per_path_classification(self):
        (self.repo / 'spend.py').write_text('def on_update(client):\n    client.purchase(usd=1000)\n')
        (self.repo / 'crates/core/src/messaging').mkdir(parents=True)
        (self.repo / 'crates/core/src/messaging/send.rs').write_text('// Synthetic send change.\n')
        self.head = self.commit('Synthetic new spending operation and send change')
        self.git(self.repo, 'push', '-q', self.remote, 'HEAD:main')
        self.smoke_kit()
        self.artifacts()
        self.made = self.body()
        self.made['risk']['spending'] = {'required': 'no', 'reason': 'No change, without diff evidence.'}
        (self.root / 'body.json').write_text(json.dumps(self.made))
        (self.root / 'entry.json').write_text(json.dumps(self.entry))
        self.blocked(self.cli('prepare', '--state', self.state, '--repo', self.repo, '--body', self.root / 'body.json',
                              '--artifacts', self.root / 'artifacts', '--entry', self.root / 'entry.json',
                              '--classification', self.root / 'absent.json'), 'risk_classification_missing')
        complete = self.classification()
        for name, rows, reason in (
                ('partial', [r for r in complete if r['path'] != 'spend.py'], 'risk_classification_incomplete'),
                ('spending yes, declared no', self.classification(**{
                    'spend.py': {'spending': 'yes'}, 'crates/core/src/messaging/send.rs': {'send': 'yes'}}),
                 'spending_classification_unsupported'),
                ('a send path classified no', complete, 'send_classification_unsupported')):
            with self.subTest(case=name):
                self.assertEqual(self.blocked(self.prepare(rows=rows), reason)['reasons'], [reason])
        rows = self.classification(**{'crates/core/src/messaging/send.rs': {'send': 'yes'}})
        self.assertEqual(self.prepare(rows=rows)[0], 0)
        self.assertEqual(self.writes(), [])

    def test_fixture_dry_run_or_missing_smoke_never_counts_as_live(self):
        self.smoke_kit()
        self.artifacts()
        self.made = self.body()
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        self.blocked(self.publish(), 'smoke_missing', 'send_live_missing', 'new_live_missing')
        self.assertEqual(self.smoke('--fixture')[0], 0)
        self.blocked(self.publish(), 'smoke_not_live', 'send_not_live', 'new_not_live')
        self.assertEqual(self.writes(), [])

    def test_dry_run_receipts_never_count_as_live(self):
        self.smoke_kit()
        self.artifacts()
        self.made = self.body()
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        pointer = f'https://github.com/{PRIVATE}/issues/9000#issuecomment-9301'
        self.assertEqual(self.cli('live', '--state', self.state, '--kit', self.helper.kit_path,
                                  '--smoke-state', self.root / 'never-ran', '--record', pointer)[0], 0)
        self.blocked(self.publish(), 'smoke_not_live')
        self.assertEqual(self.writes(), [])

    def test_each_risk_category_without_its_live_result_refuses(self):
        for risk in ('send', 'new'):
            with self.subTest(risk=risk):
                self.setUp()
                self.ready()
                saved = json.loads((self.state / 'live.json').read_text())
                saved['doc']['gates'][risk] = None
                (self.state / 'live.json').write_text(json.dumps(saved))
                self.assertEqual(self.blocked(self.publish(), f'{risk}_live_missing')['reasons'],
                                 [f'{risk}_live_missing'])
                self.assertEqual(self.writes(), [])
        for risk in ('app_permissions', 'spending'):
            with self.subTest(risk=risk, required='yes'):
                self.setUp()
                self.smoke_kit()
                self.artifacts()
                body = self.body()
                body['risk'][risk] = {'required': 'yes', 'reason': f'Synthetic {risk} change.'}
                self.made = body
                self.assertEqual(self.prepare()[0], 0)
                self.decisions()
                self.gates()
                result = self.smoke()
                if risk == 'spending':
                    self.blocked(result, 'smoke_risk_missing')
                    self.blocked(self.publish(), 'spending_live_missing')
                else:
                    self.assertEqual(result[0], 0)
                    saved = json.loads((self.state / 'live.json').read_text())
                    saved['doc']['gates'][risk] = None
                    (self.state / 'live.json').write_text(json.dumps(saved))
                    self.blocked(self.publish(), 'app_permissions_live_missing')
                self.assertEqual(self.writes(), [])
        self.setUp()
        self.smoke_kit()
        self.artifacts()
        body = self.body()
        body['risk']['send'] = {'required': 'unknown', 'reason': 'Synthetic: unclassified.'}
        self.made = body
        self.assertEqual(self.prepare()[0], 0)
        self.blocked(self.publish(), 'send_unknown')
        del body['risk']['spending']
        shutil.rmtree(self.state)
        self.blocked(self.prepare(body), 'risk_missing')
        self.assertEqual(self.writes(), [])

    def test_any_mismatched_readback_blocks_success_and_is_never_retried(self):
        for plant, reason in (('notes', 'readback_notes'), ('crlf', 'readback_notes'), ('trimmed', 'readback_notes'),
                              ('asset', 'readback_asset_bytes'), ('mutable', 'readback_immutable')):
            with self.subTest(plant=plant):
                self.setUp()
                self.ready()
                code, out = self.publish(PLANT=plant, AT=str(self.now - 300))
                self.assertEqual((code, out['status']), (1, 'incomplete'), out)
                self.assertIn(reason, out['reasons'])
                self.assertEqual(self.record()['publication']['status'], 'incomplete')
                self.assertEqual(self.install_check(),
                                 (1, {'status': 'blocked', 'reasons': ['publication_incomplete']}))
                self.assertEqual(self.publish(PLANT=plant, AT=str(self.now - 200))[1]['reasons'], out['reasons'])
                self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
                self.assertEqual(self.publish(AT=str(self.now - 100)), (0, {'status': 'published', 'tag': 'v' + VERSION,
                                                                       'tag_object': self.git(self.remote, 'rev-parse',
                                                                                              'refs/tags/v' + VERSION)}))
                self.assertEqual([(p['started_at'], p['finished_at']) for p in self.record()['timing']['phases']
                                  if p['name'] == 'publish'],
                                 [(self.now - 300, self.now - 300), (self.now - 300, self.now - 200),
                                  (self.now - 200, self.now - 100)])
                self.assertEqual(self.record()['publication']['status'], 'complete')
                self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])

    def test_2552_an_unreadable_readback_records_its_flags_unverified(self):
        self.ready()
        code, out = self.publish(PLANT='unreadable')
        self.assertEqual((code, out), (1, {'status': 'incomplete', 'reasons': ['readback_unreadable']}))
        publication = self.record()['publication']
        self.assertEqual((publication['status'], publication['immutable'], publication['prerelease']),
                         ('incomplete', False, False))
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])

    def ready_public(self, version='0.1.0'):
        shutil.rmtree(self.repo)
        shutil.rmtree(self.remote)
        self.history(notes=NOTES.replace(VERSION, version))
        self.smoke_kit(version=version, coverage=[
            {'version': version, 'promise': 'synthetic_fleet', 'steps': receipts_fixture.FLEET_ROW},
            {'version': version, 'promise': 'synthetic_send', 'steps': ['send_once', 'new_once']}])
        self.artifacts(version=version)
        self.made = self.body(version=version)
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        self.assertEqual(self.smoke()[0], 0)

    def test_1836_publishing_0_1_0_creates_and_reads_back_openwiz_0_01(self):
        self.ready_public()
        code, out = self.publish()
        self.assertEqual((code, out['status']), (0, 'published'), out)
        created = next(c['args'] for c in self.calls() if c['action'] == 'release')
        self.assertEqual(created[created.index('--title') + 1], 'OpenWiz 0.01')
        self.assertEqual(json.loads((self.releases / 'v0.1.0' / 'meta.json').read_text())['title'], 'OpenWiz 0.01')
        self.assertEqual(self.record()['publication']['status'], 'complete')
        self.assertEqual(self.git(self.remote, 'tag', '-l', '--format=%(contents:subject)', 'v0.1.0'), 'OpenWiz 0.1.0')

    def test_2278_publishing_0_1_1_creates_and_reads_back_openwiz_0_1_1(self):
        self.ready_public('0.1.1')
        code, out = self.publish()
        self.assertEqual((code, out['status']), (0, 'published'), out)
        created = next(c['args'] for c in self.calls() if c['action'] == 'release')
        self.assertEqual(created[created.index('--title') + 1], 'OpenWiz 0.1.1')
        self.assertEqual(json.loads((self.releases / 'v0.1.1' / 'meta.json').read_text())['title'], 'OpenWiz 0.1.1')
        self.assertEqual(self.record()['publication']['status'], 'complete')
        self.assertEqual(self.git(self.remote, 'tag', '-l', '--format=%(contents:subject)', 'v0.1.1'), 'OpenWiz 0.1.1')

    def test_2527_from_0_1_1_on_a_release_is_named_by_its_version(self):
        candidate = load('release_candidate_public_name', HERE / 'candidate.py')
        self.assertEqual(candidate.public_name('0.1.0'), 'OpenWiz 0.01')
        for version in ('0.1.1', '0.1.2'):
            with self.subTest(version=version):
                self.assertEqual(candidate.public_name(version), 'OpenWiz ' + version)

    def test_1836_a_0_1_0_release_read_back_under_another_name_is_incomplete(self):
        self.ready_public()
        fake = self.bin / 'gh'
        fake.write_text(fake.read_text().replace('"title": args[args.index("--title") + 1]',
                                                 '"title": os.environ["RENAME"]'))
        meta = self.releases / 'v0.1.0' / 'meta.json'
        self.assertEqual(self.publish(RENAME='OpenWiz 0.1.0'),
                         (1, {'status': 'incomplete', 'reasons': ['readback_release_identity']}))
        for name in ('OpenWiz 0.01 ', 'openwiz 0.01', 'OpenWiz 0.1', 'OpenWiz 0.01.0'):
            with self.subTest(name=name):
                meta.write_text(json.dumps(dict(json.loads(meta.read_text()), title=name)))
                self.assertEqual(self.publish(), (1, {'status': 'incomplete', 'reasons': ['readback_release_identity']}))
                self.assertEqual(self.record()['publication']['status'], 'incomplete')
        meta.write_text(json.dumps(dict(json.loads(meta.read_text()), title='OpenWiz 0.01')))
        self.assertEqual(self.publish()[1]['status'], 'published')
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])

    def test_1836_a_version_outside_the_table_keeps_its_semver_name(self):
        self.ready_public('0.0.99')
        self.assertEqual(self.publish()[0], 0)
        self.assertEqual(json.loads((self.releases / 'v0.0.99' / 'meta.json').read_text())['title'], 'OpenWiz 0.0.99')
        self.assertEqual(self.git(self.remote, 'tag', '-l', '--format=%(contents:subject)', 'v0.0.99'),
                         'OpenWiz 0.0.99')

    def swap_tag(self):
        return ('    subprocess.run([REAL, "-C", os.environ["PUBLIC_FAKE"], "-c", "user.name=Synthetic",\n'
                f'                    "-c", "user.email={NOREPLY}", "tag", "-f", "-a", "-m", "Synthetic other",\n'
                f'                    "v{VERSION}", "v{VERSION}^{{}}"], check=True, capture_output=True)')

    def test_2552_the_tag_reads_back_as_the_intended_annotated_object(self):
        tag = 'v' + VERSION
        self.ready()
        self.after_push(self.swap_tag())
        self.assertEqual(self.publish(), (1, {'status': 'uncertain', 'reasons': ['uncertain_tag']}))
        self.assertEqual(self.writes(), ['tag', 'tag-push'])
        self.assertFalse((self.releases / tag).exists())
        self.setUp()
        self.ready()
        self.assertEqual(self.publish(PLANT='notes')[1]['reasons'], ['readback_notes'])
        intended = self.git(self.remote, 'rev-parse', 'refs/tags/' + tag)
        self.git(self.remote, 'tag', '-f', '-a', '-m', 'Synthetic other', tag, tag + '^{}')
        self.assertEqual(self.git(self.remote, 'rev-parse', tag + '^{}'), self.head)
        self.assertNotEqual(self.git(self.remote, 'rev-parse', 'refs/tags/' + tag), intended)
        self.assertEqual(self.publish(), (1, {'status': 'incomplete', 'reasons': ['readback_tag']}))
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])

    def test_artifacts_must_match_the_candidate_inventory(self):
        self.smoke_kit()
        self.artifacts()
        body = self.body()
        for name, change, reason in (
                ('missing', lambda: (self.root / 'artifacts' / 'openwiz-x86_64-apple-darwin.sha256').unlink(),
                 'artifacts_incomplete'),
                ('changed', lambda: (self.root / 'artifacts' / 'SHA256SUMS').write_text('changed\n'),
                 'artifact_changed')):
            with self.subTest(case=name):
                shutil.rmtree(self.root / 'artifacts')
                self.artifacts()
                change()
                self.blocked(self.prepare(body), reason)
        self.assertEqual(self.writes(), [])

    def test_timer_counts_waits_after_ship_and_survives_resume(self):
        self.ready()
        ship = self.record()['timing']['original_ship_at']
        self.assertEqual(ship, self.now - 900)
        self.assertIn({'name': 'changelog_wait', 'started_at': self.now - 900, 'finished_at': self.now - 780},
                      self.record()['timing']['phases'])
        code, out = self.publish(FAIL_ACTION='release')
        self.assertEqual(code, 1, out)
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.assertEqual(self.publish(), (1, {'status': 'uncertain', 'reasons': ['uncertain_release']}))
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.assertEqual(self.record()['timing']['original_ship_at'], ship)

    def test_interrupted_tag_push_is_never_repeated(self):
        self.ready()
        self.assertEqual(self.publish(FAIL_ACTION='tag-push')[0], 1)
        self.assertEqual(self.publish(), (1, {'status': 'uncertain', 'reasons': ['uncertain_tag']}))
        self.assertEqual(self.writes(), ['tag', 'tag-push'])

    def after_push(self, extra):
        fake = self.bin / 'git'
        fake.write_text(fake.read_text().replace(
            'sys.exit(subprocess.run([REAL] + mapped).returncode)',
            'result = subprocess.run([REAL] + mapped)\n'
            'if action == "tag-push" and result.returncode == 0:\n' + extra +
            '\nsys.exit(result.returncode)'))

    def test_r5_a_revocation_after_the_tag_push_stops_before_release_creation(self):
        self.ready()
        self.after_push(
            '    path = os.environ["GH_WORLD"]\n'
            '    world = json.load(open(path))\n'
            f'    rows = world["repos/{PRIVATE}/issues/9000/comments?per_page=100"][0]\n'
            f'    rows.append(dict(rows[0], id=9160, created_at="{iso(self.now)}",\n'
            '                     body="Release decision revoked: 9101\\n"))\n'
            '    open(path, "w").write(json.dumps(world))')
        self.blocked(self.publish(), 'ship_revoked')
        self.assertEqual(self.writes(), ['tag', 'tag-push'])
        self.assertFalse((self.releases / ('v' + VERSION)).exists())
        self.blocked(self.publish(), 'ship_revoked')
        self.assertEqual(self.writes(), ['tag', 'tag-push'])

    def test_r6_a_lost_tag_push_response_settles_and_creates_the_release_once(self):
        self.ready()
        self.after_push('    sys.exit(42)')
        self.assertEqual(self.publish()[0], 1)
        self.assertEqual(self.git(self.remote, 'rev-parse', f'refs/tags/v{VERSION}^{{}}'), self.head)
        code, out = self.publish()
        self.assertEqual((code, out['status']), (0, 'published'), out)
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.assertEqual(self.record()['publication']['status'], 'complete')

    def test_rl6_a_next_day_resume_after_a_lost_tag_push_refuses_before_creating_the_release(self):
        self.curate(CURATED)
        self.ready()
        self.after_push('    sys.exit(42)')
        self.assertEqual(self.publish(TODAY='2026-11-20')[0], 1)
        self.assertEqual(self.writes(), ['tag', 'tag-push'])
        self.assertEqual(self.blocked(self.publish(TODAY='2026-11-21'), 'changelog_date')['reasons'], ['changelog_date'])
        self.assertEqual(self.writes(), ['tag', 'tag-push'])
        code, out = self.publish(TODAY='2026-11-20')
        self.assertEqual((code, out['status']), (0, 'published'), out)
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])

    def test_r7_a_lost_release_response_settles_published_on_the_first_recovery(self):
        self.ready()
        self.assertEqual(self.publish(FAIL_ACTION='release-response', AT=str(self.now - 300))[0], 1)
        self.assertTrue((self.releases / ('v' + VERSION) / 'meta.json').exists())
        self.assertEqual(self.publish(AT=str(self.now - 200)), (0, {'status': 'published', 'tag': 'v' + VERSION,
                                                               'tag_object': self.git(self.remote, 'rev-parse',
                                                                                      'refs/tags/v' + VERSION)}))
        self.assertEqual(self.writes(), ['tag', 'tag-push', 'release'])
        self.assertEqual(self.record()['publication']['status'], 'complete')
        self.assertEqual([p for p in self.record()['timing']['phases'] if p['name'] == 'publish'],
                         [{'name': 'publish', 'started_at': self.now - 300, 'finished_at': self.now - 200}])

    def corrupt(self, target, data):
        folder = self.root / 'artifacts'
        archive = folder / f'openwiz-{VERSION}-{target}.tar.gz'
        archive.write_bytes(data)
        manifest = folder / f'openwiz-{VERSION}-{target}.manifest.json'
        value = json.loads(manifest.read_bytes())
        value.update(archive_sha256=sha(data), archive_bytes=len(data))
        manifest.write_text(json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n')
        alias = folder / f'openwiz-{target}.manifest.json'
        alias.write_bytes(manifest.read_bytes())
        (folder / f'openwiz-{target}.sha256').write_text(f'{sha(alias.read_bytes())}  {alias.name}\n')
        (folder / 'SHA256SUMS').write_text(''.join(
            f'{sha(p.read_bytes())}  {p.name}\n' for p in sorted(folder.iterdir())
            if p.name.endswith('.tar.gz') or (p.name.startswith(f'openwiz-{VERSION}-') and p.name.endswith('.manifest.json'))))

    def test_r2_an_archive_users_cannot_install_refuses_before_any_write(self):
        import gzip, io, tarfile
        target = 'x86_64-unknown-linux-gnu'
        member = io.BytesIO()
        with tarfile.open(fileobj=member, mode='w', format=tarfile.USTAR_FORMAT) as tar:
            info = tarfile.TarInfo('openwiz')
            info.size, info.mode = 5, 0o700
            tar.addfile(info, io.BytesIO(b'other'))
        for name, data in (('not a gzip archive', b'not a gzip archive\n'),
                           ('wrong members', gzip.compress(member.getvalue(), mtime=0))):
            with self.subTest(case=name):
                self.setUp()
                self.smoke_kit()
                self.artifacts()
                self.corrupt(target, data)
                self.made = self.body()
                self.assertEqual(self.blocked(self.prepare(), 'artifact_archive')['reasons'], ['artifact_archive'])
                self.assertEqual(self.writes(), [])

    def test_completed_run_reports_elapsed_from_original_ship(self):
        self.ready()
        self.assertEqual(self.evaluate()[0], 0)
        self.assertEqual(self.publish()[0], 0)
        late = self.now - 900 + 1800
        self.latest()
        code, out = self.install_check(AT=str(max(late, self.record()['publication']['verified_at'])))
        self.assertEqual(code, 0, out)
        self.assertEqual(out['original_ship_at'], self.now - 900)
        self.assertEqual(out['elapsed_seconds'], out['finished_at'] - (self.now - 900))
        self.assertIs(out['target_met'], out['elapsed_seconds'] < 1800)
        self.assertEqual([p['name'] for p in out['phases']][:1], ['changelog_wait'])
        self.assertIn('publish', [p['name'] for p in out['phases']])
        self.assertIn('install', [p['name'] for p in out['phases']])
        status = self.cli('status', '--state', self.state)[1]
        self.assertEqual(status, out)

    def test_publication_order_and_published_history_are_kept(self):
        self.smoke_kit()
        self.artifacts()
        old = self.body()
        old['release_version'] = '0.0.97'
        old['included_versions'][0]['version'] = '0.0.97'
        self.blocked(self.prepare(old), 'version_order')
        (self.repo / 'CHANGELOG.md').write_text(
            (self.repo / 'CHANGELOG.md').read_text().replace('Earlier public entry.', 'Rewritten entry.'))
        self.head = self.commit('Synthetic history rewrite')
        self.git(self.repo, 'push', '-q', self.remote, 'HEAD:main')
        self.blocked(self.prepare(self.body()), 'changelog_history')
        self.assertEqual(self.writes(), [])

    def test_combined_release_keeps_every_section_in_order(self):
        versions = ['0.0.12', '0.0.11', '0.0.10', '0.0.9', '0.0.8', '0.0.7', '0.0.6']
        sections = '\n'.join(
            f'## {v} · 2026-11-20\n\nFixture-tested: Version {v} headline.\n'
            + ('' if v == '0.0.7' else f'\n- Fixture-tested: Synthetic {v} entry.\n\n'
               f'Live-checked: Synthetic {v} checks pass.\n\n'
               '[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)\n')
            for v in versions)
        published = '# Changelog\n\n## 0.0.5 · 2026-01-05\n\nContext: Earlier public entry.  \n'
        shutil.rmtree(self.repo)
        shutil.rmtree(self.remote)
        self.history(notes=sections, published=published, published_version='0.0.5')
        coverage = [{'version': v, 'promise': f'synthetic_{v}', 'steps': receipts_fixture.FLEET_ROW + ['send_once', 'new_once']}
                    for v in versions if v != '0.0.7']
        self.smoke_kit(coverage=coverage, version='0.0.12')
        self.artifacts(version='0.0.12')
        self.made = self.body(version='0.0.12', promises=[(v, [f'synthetic_{v}']) for v in versions])
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        self.assertEqual(self.smoke()[0], 0)
        self.assertEqual(self.publish()[0], 0)
        meta = json.loads((self.releases / 'v0.0.12' / 'meta.json').read_text())
        self.assertEqual(meta['notes'], sections)
        self.assertEqual(re_headings(meta['notes']), [f'## {v} · 2026-11-20' for v in versions])
        kept = subprocess.run([REAL_GIT, '-C', str(self.remote), 'show', 'v0.0.5:CHANGELOG.md'],
                              capture_output=True, text=True, check=True).stdout
        self.assertEqual(kept, published)
        reordered = json.loads(json.dumps(self.made))
        reordered['included_versions'][0], reordered['included_versions'][1] = \
            reordered['included_versions'][1], reordered['included_versions'][0]
        shutil.rmtree(self.state)
        self.blocked(self.prepare(reordered), 'version_order')

    def test_prepare_refuses_each_broken_binding_and_publish_its_prewrite_checks(self):
        self.smoke_kit()
        self.artifacts()
        good = self.body()

        def notes(text):
            return lambda b: b['changelog'].update(utf8=text, sha256=sha(text.encode()), bytes=len(text.encode()))

        def alias(b):
            path = self.root / 'artifacts' / 'openwiz-x86_64-unknown-linux-gnu.manifest.json'
            path.write_bytes(path.read_bytes() + b' ')
            row = next(r for r in b['artifacts'] if r['name'] == path.name)
            row.update(sha256=sha(path.read_bytes()), bytes=path.stat().st_size)
        for name, change, reason in (
                ('tree', lambda b: b['source'].update(tree='f' * 40), 'tree_mismatch'),
                ('section', lambda b: b['included_versions'][0].update(section_sha256='0' * 64), 'section_changed'),
                ('placeholder', notes(NOTES.replace('Synthetic export', 'LIVE-PENDING')), 'changelog_placeholder'),
                ('range heading', notes(NOTES + '\n## 0.0.99 – 0.0.98 · 2026-11-20\n\nSynthetic.\n'),
                 'changelog_range_heading'),
                ('unknown key', lambda b: b.update(approval='publish ' + VERSION), 'invalid_body'),
                ('products order', lambda b: b['products'].reverse(), 'products_incomplete'),
                ('product source', lambda b: b['products'][0]['identity'].update(source='f' * 40),
                 'product_identity_mismatch'),
                ('kit authority', lambda b: b['kit'].update(authority='https://example.invalid/kit'), 'invalid_kit'),
                ('artifact role', lambda b: b['artifacts'][0].update(role='archive'), 'invalid_artifacts'),
                ('alias', alias, 'artifact_links')):
            with self.subTest(case=name):
                body = json.loads(json.dumps(good))
                change(body)
                self.assertEqual(self.blocked(self.prepare(body), reason)['reasons'], [reason])
                shutil.rmtree(self.root / 'artifacts')
                self.artifacts()
        self.made = good
        prepared = self.prepare()
        self.assertEqual(prepared[0], 0, prepared)
        self.decisions()
        self.gates()
        self.assertEqual(self.smoke()[0], 0)
        self.world[f'repos/{PUBLIC}/immutable-releases'] = {'enabled': False}
        self.save()
        self.blocked(self.publish(), 'cutover_unverified')
        self.world[f'repos/{PUBLIC}/immutable-releases'] = {'enabled': True}
        self.save()
        self.git(self.remote, 'tag', 'v' + VERSION, self.published)
        self.blocked(self.publish(), 'version_order')
        self.assertEqual(self.writes(), [])

    def author(self, name, email):
        shutil.rmtree(self.repo)
        shutil.rmtree(self.remote)
        saved = self.env['GIT_AUTHOR_NAME'], self.env['GIT_AUTHOR_EMAIL']
        self.env['GIT_AUTHOR_NAME'], self.env['GIT_AUTHOR_EMAIL'] = name, email
        self.history()
        self.env['GIT_AUTHOR_NAME'], self.env['GIT_AUTHOR_EMAIL'] = saved

    def unprotected(self):
        self.world[f'repos/{PUBLIC}/immutable-releases'] = {'enabled': False}
        self.save()
        return {}

    def test_2127_evaluate_gives_each_publish_precondition_publish_refuses_before_its_first_write(self):
        def changed():
            alias = self.root / 'artifacts' / 'openwiz-x86_64-apple-darwin.sha256'
            alias.write_bytes(alias.read_bytes() + b'synthetic change\n')
            return {}

        def tagged():
            self.git(self.remote, 'tag', 'v' + VERSION, self.published)
            return {}
        for name, before, after, reason, same in (
                ('notes dated the day before', None, lambda: {'TODAY': '2026-11-21'}, 'changelog_date', True),
                ('asset bytes changed after the gates', None, changed, 'artifact_changed', True),
                ('author name with a digit', lambda: self.author('Synthetic Maintainer 2', NOREPLY), None,
                 'tagger_identity', True),
                ('author email not a noreply address',
                 lambda: self.author('Synthetic Maintainer', 'fixture@example.invalid'), None, 'tagger_identity', True),
                ('immutable releases off', None, self.unprotected, 'immutable_releases_off', False),
                ('tag already present', None, tagged, 'tag_exists', False)):
            with self.subTest(case=name):
                self.setUp()
                before and before()
                self.ready()
                extra = after() if after else {}
                out = self.blocked(self.evaluate(**extra), reason)
                refused = self.blocked(self.publish(**extra))
                if same:
                    self.assertEqual((out['reasons'], refused['reasons']), ([reason], [reason]))
                self.assertEqual(self.writes(), [])

    def test_dispatcher_exposes_the_candidate_command(self):
        result = subprocess.run([sys.executable, str(HERE / 'release'), 'candidate', '--help'],
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        for action in ('prepare', 'decide', 'evaluate', 'publish', 'install', 'notes'):
            self.assertIn(action, result.stdout)
        self.assertEqual(self.calls(), [])


COMBINED = ('0.0.12', '0.0.11', '0.0.10', '0.0.9', '0.0.8', '0.0.7', '0.0.6')
SETTLED = {'0.0.12': 6, '0.0.11': 6, '0.0.10': 4, '0.0.9': 11, '0.0.8': 7, '0.0.7': 0, '0.0.6': 17}
BASE_05 = '# Changelog\n\n## 0.0.5 · 2026-01-05\n\nContext: Earlier public entry.  \n'


class Waiver(World):
    FIXTURE = json.dumps([['app_permissions', VERSION]])

    def app_yes(self, drop=True):
        self.smoke_kit()
        self.artifacts()
        body = self.body()
        body['risk']['app_permissions'] = {'required': 'yes', 'reason': 'Synthetic App permission change.'}
        self.made = body
        self.assertEqual(self.prepare()[0], 0)
        self.decisions()
        self.gates()
        self.assertEqual(self.smoke()[0], 0)
        if drop:
            self.drop('app_permissions')

    def drop(self, gate):
        saved = json.loads((self.state / 'live.json').read_text())
        saved['doc']['gates'][gate] = None
        (self.state / 'live.json').write_text(json.dumps(saved))

    def waiver(self, line, number=9500, at=None, first='Private record: Jake, 2026-11-20, synthetic waiver.'):
        return self.comment(number, f'{first}\n{line}\n', self.now - 300 if at is None else at)

    def waive(self, pointer, table=None):
        return self.cli('decide', '--state', self.state, '--waiver', pointer, WAIVABLE=table or self.FIXTURE)

    def test_app_permissions_waiver_stands_in_for_only_that_live_receipt_as_waived(self):
        self.app_yes()
        self.assertEqual(self.blocked(self.evaluate(WAIVABLE=self.FIXTURE), 'app_permissions_live_missing')['reasons'],
                         ['app_permissions_live_missing'])
        pointer = self.waiver(f'Release waiver: app_permissions v{VERSION}')
        self.assertEqual(self.waive(pointer), (0, {'status': 'recorded', 'decision': 'waiver',
                                                   'waived': 'app_permissions'}))
        code, out = self.evaluate(WAIVABLE=self.FIXTURE)
        self.assertEqual((code, out), (0, {'status': 'ready', 'candidate_sha256': self.record()['candidate_sha256'],
                                           'waived': ['app_permissions']}))
        gate = self.record()['gates']['app_permissions']
        self.assertEqual(gate['status'], 'waived')
        self.assertEqual(gate['waiver']['pointer'], pointer)
        self.assertNotIn('pass', json.dumps(gate))
        run = f'https://github.com/{PRIVATE}/issues/9000#issuecomment-9301'
        self.assertEqual(self.cli('live', '--state', self.state, '--kit', self.helper.kit_path,
                                  '--smoke-state', self.helper.state, '--record', run, WAIVABLE=self.FIXTURE),
                         (0, {'status': 'recorded', 'gates': {'smoke': 'pass', 'send': 'pass', 'new': 'pass',
                                                              'app_permissions': 'waived', 'spending': None}}))
        self.assertEqual(self.evaluate(WAIVABLE=self.FIXTURE)[0], 0)

    def test_a_waiver_never_stands_in_for_another_risks_receipt(self):
        self.app_yes()
        self.assertEqual(self.waive(self.waiver(f'Release waiver: app_permissions v{VERSION}'))[0], 0)
        self.drop('send')
        self.assertEqual(self.blocked(self.evaluate(WAIVABLE=self.FIXTURE))['reasons'], ['send_live_missing'])
        self.assertEqual(self.writes(), [])

    def test_no_waiver_line_or_an_unrecorded_one_is_never_a_waiver(self):
        self.app_yes()
        for name, pointer, change in (
                ('no line', self.waiver('Synthetic: no waiver here.', 9501), {}),
                ('no record line', self.waiver(f'Release waiver: app_permissions v{VERSION}', 9502,
                                               first='Synthetic note.'), {}),
                ('other author', self.waiver(f'Release waiver: app_permissions v{VERSION}', 9503),
                 {'user': {'login': 'someone-else'}})):
            with self.subTest(name):
                self.comments[f'repos/{PRIVATE}/issues/comments/{pointer.rsplit("-", 1)[1]}'].update(change)
                self.save()
                self.blocked(self.waive(pointer), 'waiver_not_a_record')
        self.blocked(self.evaluate(WAIVABLE=self.FIXTURE), 'app_permissions_live_missing')

    def test_an_edited_waiver_refuses(self):
        self.app_yes()
        pointer = self.waiver(f'Release waiver: app_permissions v{VERSION}')
        path = f'repos/{PRIVATE}/issues/comments/9500'
        self.comments[path]['updated_at'] = iso(self.now - 100)
        self.save()
        self.blocked(self.waive(pointer), 'waiver_not_a_record')
        self.comments[path]['updated_at'] = self.comments[path]['created_at']
        self.save()
        self.assertEqual(self.waive(pointer)[0], 0)
        self.comments[path]['updated_at'] = iso(self.now - 100)
        self.save()
        self.blocked(self.evaluate(WAIVABLE=self.FIXTURE), 'waiver_not_a_record', 'app_permissions_live_missing')

    def test_a_revoked_waiver_refuses(self):
        self.app_yes()
        pointer = self.waiver(f'Release waiver: app_permissions v{VERSION}')
        self.assertEqual(self.waive(pointer)[0], 0)
        self.comment(9510, 'Private record: Jake, 2026-11-20.\nRelease waiver revoked: 9500\n', self.now - 60)
        self.blocked(self.evaluate(WAIVABLE=self.FIXTURE), 'waiver_revoked', 'app_permissions_live_missing')
        self.blocked(self.waive(pointer), 'waiver_revoked')

    def test_a_revocation_added_by_editing_an_older_comment_refuses(self):
        for name, edited_at in (('edited after the waiver', self.now - 60),
                                ('edited, even before the waiver', self.now - 350)):
            with self.subTest(name):
                self.setUp()
                self.app_yes()
                self.comment(9499, 'Synthetic earlier note.\n', self.now - 400)
                pointer = self.waiver(f'Release waiver: app_permissions v{VERSION}', at=self.now - 300)
                self.assertEqual(self.waive(pointer)[0], 0)
                self.comments[f'repos/{PRIVATE}/issues/comments/9499'].update(
                    body='Release waiver revoked: 9500\n', updated_at=iso(edited_at))
                self.save()
                self.blocked(self.evaluate(WAIVABLE=self.FIXTURE), 'waiver_revoked', 'app_permissions_live_missing')
                self.blocked(self.publish(WAIVABLE=self.FIXTURE), 'waiver_revoked')
                self.assertEqual(self.writes(), [])

    def test_direct_publication_records_the_applied_waiver(self):
        self.app_yes(drop=False)
        self.assertEqual(self.record()['gates']['app_permissions']['status'], 'pass')
        self.assertEqual(self.waive(self.waiver(f'Release waiver: app_permissions v{VERSION}'))[0], 0)
        code, out = self.publish(WAIVABLE=self.FIXTURE)
        self.assertEqual((code, out['status']), (0, 'published'), out)
        gate = self.record()['gates']['app_permissions']
        self.assertEqual((gate['status'], gate.get('waiver', {}).get('pointer')),
                         ('waived', f'https://github.com/{PRIVATE}/issues/9000#issuecomment-9500'))

    def test_a_waiver_for_another_version_refuses(self):
        self.app_yes()
        self.blocked(self.waive(self.waiver('Release waiver: app_permissions v0.0.98', 9520)), 'waiver_wrong_version')
        real = self.waiver(f'Release waiver: app_permissions v{VERSION}', 9521)
        self.blocked(self.cli('decide', '--state', self.state, '--waiver', real), 'waiver_wrong_version')
        self.blocked(self.waive(self.waiver('Release waiver: app_permissions v0.0.12', 9522)), 'waiver_wrong_version')

    def test_a_waiver_for_another_risk_refuses(self):
        self.app_yes()
        for number, risk in enumerate(('send', 'new', 'spending')):
            with self.subTest(risk):
                pointer = self.waiver(f'Release waiver: {risk} v{VERSION}', 9530 + number)
                self.blocked(self.waive(pointer), 'waiver_wrong_risk')

    def test_a_waiver_naming_several_risks_or_a_range_refuses(self):
        self.app_yes()
        for number, line in enumerate((f'Release waiver: app_permissions,send v{VERSION}',
                                       f'Release waiver: app_permissions send v{VERSION}',
                                       f'Release waiver: app_permissions v0.0.98-v{VERSION}',
                                       'Release waiver: app_permissions v0.0.*',
                                       f'Release waiver: app_permissions v{VERSION} v0.0.98')):
            with self.subTest(line):
                self.blocked(self.waive(self.waiver(line, 9540 + number)), 'waiver_invalid')
        two = self.waiver(f'Release waiver: app_permissions v{VERSION}\nRelease waiver: app_permissions v{VERSION}', 9549)
        self.blocked(self.waive(two), 'waiver_invalid')


class Notes(World):
    def setUp(self):
        super().setUp()
        shutil.rmtree(self.repo)
        shutil.rmtree(self.remote)
        self.history(notes='', published=BASE_05, published_version='0.0.5')
        (self.repo / 'changes').mkdir(exist_ok=True)
        (self.repo / 'changes/README.md').write_text('Synthetic contract.\n')
        self.milestones = {}

    def spec(self, version, headline=True):
        number = 5000 + int(version.split('.')[2])
        self.milestones.setdefault(version, 100 + len(self.milestones))
        body = f'## Changelog headline\n\nFixture-tested: Version {version} headline.\n' if headline else ''
        self.world[f'repos/{{owner}}/{{repo}}/issues/{number}'] = {
            'number': number, 'body': body, 'pull': False, 'sub_issues': 2,
            'milestone': {'number': self.milestones[version], 'title': version}}
        return number

    def line(self, number, version, text=None, raw=None):
        if version is None:
            milestone = {'number': None, 'title': None}
        else:
            self.milestones.setdefault(version, 100 + len(self.milestones))
            milestone = {'number': self.milestones[version], 'title': version}
        self.world[f'repos/{{owner}}/{{repo}}/issues/{number}'] = {
            'number': number, 'body': '', 'pull': False, 'sub_issues': 0, 'milestone': milestone}
        path = self.repo / f'changes/{number}.md'
        path.write_bytes(raw if raw is not None else f'kind: added\n\n{text or f"Synthetic entry {number}."}\n'.encode())
        return f'changes/{number}.md', sha(path.read_bytes())

    def settle(self, counts, release=COMBINED):
        number = 6000
        for version in release:
            self.spec(version)
            for _ in range(counts.get(version, 1)):
                number += 7
                self.line(number, version)
        return number

    def generate(self, versions, excluded=()):
        self.commit('Synthetic changes')
        self.save()
        entry = {'versions': [{'version': v, 'spec': 5000 + int(v.split('.')[2]), 'date': '2026-11-20',
                               'tested': f'Fixture-tested: Synthetic {v} checks pass.'} for v in versions]
                 if len(versions) > 1 else {'spec': 5000 + int(versions[0].split('.')[2]), 'date': '2026-11-20',
                                            'tested': f'Fixture-tested: Synthetic {versions[0]} checks pass.'},
                 'excluded': [{'path': p, 'sha256': h, 'reason': 'Synthetic recorded decision.'} for p, h in excluded]}
        (self.root / 'entry.json').write_text(json.dumps(entry))
        out = self.root / f'notes-{len(list(self.root.glob("notes-*")))}'
        return self.cli('notes', versions[0], '--repo', self.repo, '--entry', self.root / 'entry.json',
                        '--out', out), out

    def test_combined_notes_keep_every_original_entry_under_the_recorded_caps(self):
        self.settle(SETTLED)
        unassigned = [self.line(7001, None), self.line(7002, None, raw=b'kind: fixed\n\nNo final newline.'),
                      self.line(7003, 'Design')]
        (code, out), folder = self.generate(COMBINED, excluded=unassigned)
        self.assertEqual(code, 0, out)
        text = (folder / 'notes.md').read_text()
        self.assertEqual(re_headings(text), [f'## {v} · 2026-11-20' for v in COMBINED])
        sources = json.loads((folder / 'sources.json').read_text())['versions']
        for version, count in SETTLED.items():
            section = text[text.index(f'## {version} · '):]
            section = section[:section.find('\n## ') + 1 or len(section)]
            bullets = [l[2:] for l in section.splitlines() if l.startswith('- ')]
            self.assertEqual(len(bullets), count, version)
            self.assertEqual(bullets, [r['sentence'] for r in sources[version]])
            self.assertEqual([r['path'] for r in sources[version]],
                             sorted((r['path'] for r in sources[version]), key=lambda p: int(p[8:-3])))
        self.assertIn('## 0.0.7 · 2026-11-20\n\nFixture-tested: Version 0.0.7 headline.\n\n## 0.0.6', text)
        self.assertNotIn('releases/tag/v0.0.7', text)
        self.assertNotIn('Synthetic 0.0.7 checks pass.', text)
        self.assertEqual((folder / 'CHANGELOG.md').read_text(), '# Changelog\n\n' + text + '\n'
                         + BASE_05.removeprefix('# Changelog\n\n'))
        self.assertEqual(out['notes_sha256'], sha(text.encode()))
        self.assertEqual([s['entries'] for s in out['sections']], [SETTLED[v] for v in COMBINED])
        footers = re.findall(r'releases/tag/v([0-9.]+)\)', text)
        self.assertEqual(footers, ['0.0.12'] * 6)

    def test_the_five_line_cap_stays_for_every_other_section_and_release(self):
        for name, counts, release, reason in (
                ('over a recorded count', dict(SETTLED, **{'0.0.6': 18}), COMBINED, 'more than 17'),
                ('section without an exception', dict(SETTLED, **{'0.0.10': 6}), COMBINED, 'more than five'),
                ('ordinary release', {'0.0.13': 6}, ('0.0.13',), 'more than five'),
                ('a different combined range', {'0.0.12': 6, '0.0.11': 1}, ('0.0.12', '0.0.11'), 'more than five')):
            with self.subTest(case=name):
                self.setUp()
                self.settle(counts, release)
                (code, out), _ = self.generate(release)
                self.assertEqual(code, 1, out)
                self.assertTrue(any(reason in r for r in out['reasons']), out)

    def test_headline_only_is_generic_and_a_version_with_neither_refuses(self):
        self.spec('0.0.13')
        (code, out), folder = self.generate(('0.0.13',))
        self.assertEqual(code, 0, out)
        self.assertEqual((folder / 'notes.md').read_text(),
                         '## 0.0.13 · 2026-11-20\n\nFixture-tested: Version 0.0.13 headline.\n')
        self.setUp()
        self.spec('0.0.13')
        self.line(6001, '0.0.13')
        (code, out), folder = self.generate(('0.0.13',))
        self.assertEqual(code, 0, out)
        self.assertEqual(re.findall(r'releases/tag/v([0-9.]+)\)', (folder / 'notes.md').read_text()), ['0.0.13'])
        self.setUp()
        self.spec('0.0.13', headline=False)
        (code, out), _ = self.generate(('0.0.13',))
        self.assertEqual(code, 1, out)
        self.assertIn('entry: spec needs one Changelog headline', out['reasons'])

    def test_unassigned_sources_need_their_exact_recorded_exclusion(self):
        self.spec('0.0.13')
        self.line(6001, '0.0.13')
        unassigned = self.line(7001, None)
        (code, out), _ = self.generate(('0.0.13',))
        self.assertEqual((code, out['reasons']), (1, ['entry: ticket 7001 has no version milestone']))
        (code, out), _ = self.generate(('0.0.13',), excluded=[(unassigned[0], 'a' * 64)])
        self.assertEqual((code, out['reasons']), (1, ['entry: excluded source changed: changes/7001.md']))
        (code, out), _ = self.generate(('0.0.13',), excluded=[unassigned, ('changes/7999.md', 'b' * 64)])
        self.assertEqual((code, out['reasons']), (1, ['entry: excluded source missing: changes/7999.md']))
        versioned = self.line(6002, '0.0.13')
        (code, out), _ = self.generate(('0.0.13',), excluded=[unassigned, versioned])
        self.assertEqual((code, out['reasons']), (1, ['entry: excluded source has a version milestone: changes/6002.md']))
        (self.repo / 'changes/6002.md').unlink()
        (code, out), folder = self.generate(('0.0.13',), excluded=[unassigned])
        self.assertEqual(code, 0, out)
        self.assertNotIn('7001', (folder / 'notes.md').read_text())

    def test_a_moved_closedwiz_line_is_never_assigned_by_the_colliding_openwiz_ticket(self):
        self.env['MOVED'] = json.dumps({'schema': 'openwiz.moved-changes.v1', 'moved': [
            {'closedwiz': 718, 'openwiz': None, 'sha256': 'a' * 64}]})
        self.spec('0.0.13')
        self.line(718, '0.0.13', 'Fixture-tested: The new ticket line.')
        moved = self.repo / 'changes/closedwiz-718.md'
        moved.write_text('kind: fixed\n\nFixture-tested: The moved line.\n')
        (code, out), _ = self.generate(('0.0.13',))
        self.assertEqual((code, out['reasons']), (1, [
            'entry: changes/closedwiz-718.md: ClosedWiz #718 has no OpenWiz ticket: record it as an exclusion']))
        (code, out), folder = self.generate(('0.0.13',), excluded=[
            ('changes/closedwiz-718.md', sha(moved.read_bytes()))])
        self.assertEqual(code, 0, out)
        text = (folder / 'notes.md').read_text()
        self.assertIn('- Fixture-tested: The new ticket line.\n', text)
        self.assertNotIn('The moved line', text)
        (code, out), _ = self.generate(('0.0.13',), excluded=[('changes/closedwiz-718.md', 'a' * 64)])
        self.assertEqual((code, out['reasons']), (1, ['entry: excluded source changed: changes/closedwiz-718.md']))
        moved.rename(self.repo / 'changes/closedwiz-0718.md')
        (code, out), _ = self.generate(('0.0.13',))
        self.assertEqual((code, out['reasons']), (1, ['entry: invalid changelog filename changes/closedwiz-0718.md']))

    def untagged(self, base):
        shutil.rmtree(self.repo)
        shutil.rmtree(self.remote)
        self.repo.mkdir()
        self.git(self.repo, 'init', '-q', '-b', 'main')
        (self.repo / 'changes').mkdir()
        (self.repo / 'changes/README.md').write_text('Synthetic contract.\n')
        (self.repo / 'CHANGELOG.md').write_text(base)
        self.anchor = self.commit('Synthetic public anchor')
        self.git(self.root, 'clone', '-q', '--bare', self.repo, self.remote)
        self.git(self.repo, 'remote', 'add', 'origin', PUBLIC_URL)

    def curated(self, text, included, **hashes):
        (self.repo / 'changes/notes').mkdir(exist_ok=True)
        (self.repo / 'changes/notes/release.md').write_text(text)
        self.commit('Synthetic curated notes')
        cut = text[text.index('## '):]
        later = [m.start() for m in re.finditer('^## ', cut, re.M)][len(included):]
        cut = (cut[:later[0]] if later else cut).rstrip('\n') + '\n'
        (self.root / 'entry.json').write_text(json.dumps(dict(
            {'curated': 'changes/notes/release.md', 'curated_sha256': sha(text.encode()),
             'notes_sha256': sha(cut.encode())}, **hashes, included=included)))
        out = self.root / f'notes-{len(list(self.root.glob("notes-*")))}'
        return self.cli('notes', included[0], '--repo', self.repo, '--entry', self.root / 'entry.json',
                        '--out', out), out

    def test_rl6_with_nothing_published_the_changelog_keeps_the_unpublished_history(self):
        self.untagged(HISTORY)
        (self.repo / 'changes/notes').mkdir()
        (self.repo / 'changes/notes/release.md').write_text(section('0.0.13'))
        self.spec('0.0.13')
        self.line(6001, '0.0.13')
        (code, out), folder = self.generate(('0.0.13',))
        self.assertEqual(code, 0, out)
        text = (folder / 'notes.md').read_text()
        at = HISTORY.index('## ')
        self.assertEqual((folder / 'CHANGELOG.md').read_text(), HISTORY[:at] + text + '\n' + HISTORY[at:])

    def test_rl6_curated_notes_release_their_leading_sections_over_the_kept_history(self):
        self.untagged(HISTORY)
        text = PREAMBLE + section('0.0.14') + '\n' + section('0.0.13') + '\n' + section('0.0.5')
        released = section('0.0.14') + '\n' + section('0.0.13')
        (code, out), folder = self.curated(text, ['0.0.14', '0.0.13'])
        self.assertEqual(code, 0, out)
        self.assertEqual((folder / 'notes.md').read_text(), released)
        self.assertEqual((folder / 'CHANGELOG.md').read_text(), text)
        self.assertEqual((out['notes_sha256'], out['curated_sha256'], out['changelog_sha256']),
                         (sha(released.encode()), sha(text.encode()), sha(text.encode())))
        for name, hashes, reason in (
                ('curated file', {'curated_sha256': 'a' * 64}, 'entry: curated notes are not the approved bytes'),
                ('release notes', {'notes_sha256': 'b' * 64},
                 'entry: release notes cut from the curated file are not the approved bytes')):
            with self.subTest(case=name):
                (code, out), _ = self.curated(text, ['0.0.14', '0.0.13'], **hashes)
                self.assertEqual((code, out['reasons']), (1, [reason]))

    def test_rl6_the_approved_changelog_passes_as_is(self):
        raw = (ROOT / 'changes/notes/0.0.12.md').read_bytes()
        self.assertEqual(sha(raw), 'e690a1652787865d67cb557fc1a2a59588b87a21a067b2e547b90a709f5e6e3d')
        current, cut = (ROOT / 'CHANGELOG.md').read_bytes(), raw.index(b'\n\n', raw.index(b'All OpenWiz versions')) + 2
        self.assertTrue(current.startswith(raw[:cut]) and current.endswith(raw[cut:]))
        self.untagged(raw.decode())
        (self.repo / 'changes/notes').mkdir()
        (self.repo / 'changes/notes/0.0.12.md').write_bytes(raw)
        (code, out), folder = self.curated(raw.decode(), list(COMBINED))
        self.assertEqual(code, 0, out)
        self.assertEqual(out['notes_sha256'], '27135ed4d22479e17d6f02806ccb9e8a8b33e2ef37a970e1a216800da4af9191')
        self.assertEqual(out['notes_bytes'], 6896)
        self.assertEqual((folder / 'CHANGELOG.md').read_bytes(), raw)

    def test_rl6_malformed_curated_notes_refuse_with_their_reason(self):
        good = PREAMBLE + section('0.0.14') + '\n' + section('0.0.13')
        for name, text, included, reason in (
                ('missing part', good.replace("**Under the hood**\n\n- Synthetic 0.0.13 internals.\n", ''),
                 ['0.0.14'], 'entry: 0.0.13 needs Under the hood here'),
                ('wrong order', PREAMBLE + section('0.0.13') + '\n' + section('0.0.14'), ['0.0.13'],
                 'entry: curated versions must be newest first, each once'),
                ('included not leading', good, ['0.0.13'],
                 'entry: curated notes must start with the included versions, in order'),
                ('foreign link', good.replace('(https://github.com/openwizdev/OpenWiz/issues/1)',
                                              '(https://github.com/jparker2006/ClosedWiz/issues/1)'), ['0.0.14'],
                 'entry: curated link is not to openwizdev/OpenWiz: https://github.com/jparker2006/ClosedWiz/issues/1'),
                ('bare foreign address', good.replace('Synthetic 0.0.13 internals.',
                                                      'See github.com/jparker2006/ClosedWiz for internals.'), ['0.0.14'],
                 'entry: curated link is not to openwizdev/OpenWiz: github.com/jparker2006/ClosedWiz'),
                ('relative link', good.replace('(https://github.com/openwizdev/OpenWiz/issues/1)', '(docs/x.md)'),
                 ['0.0.14'], 'entry: curated link is not to openwizdev/OpenWiz: docs/x.md'),
                ('tag that will not exist', good.replace('Synthetic 0.0.13 internals.',
                                                         '[0.0.13](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.13).'),
                 ['0.0.14'], 'entry: curated link to a tag that will not exist: v0.0.13'),
                ('per-line caveat', good.replace('- You can use 0.0.14 part one.',
                                                 '- On synthetic fixtures, you can use 0.0.14 part one.'), ['0.0.14'],
                 "entry: 0.0.14 What's new for you carries a fixture caveat: say it once in the footer"),
                ('too many lines', good.replace('- You can use 0.0.14 part two.\n', '- You can use 0.0.14 part two.\n' * 4),
                 ['0.0.14'], "entry: 0.0.14 What's new for you needs 2 to 4 lines"),
                ('no footer', good.replace('Tested on synthetic 0.0.14 checks.\n\n', ''), ['0.0.14'],
                 "entry: 0.0.14 needs one footer line after What's new for you"),
                ('footer twice', good.replace('- Synthetic 0.0.14 internals.', '- Tested on nothing else.'), ['0.0.14'],
                 'entry: 0.0.14 says how it was tested more than once'),
                ('no headline', good.replace('**Use 0.0.13**\n\n', ''), ['0.0.14'],
                 'entry: 0.0.13 needs its bold headline here'),
                ('no preamble', good.removeprefix(PREAMBLE), ['0.0.14'],
                 'entry: curated notes start with # Changelog and at most one plain paragraph'),
                ('CRLF', good.replace('\n', '\r\n'), ['0.0.14'],
                 'entry: curated notes are LF text ending in one newline')):
            with self.subTest(case=name):
                self.setUp()
                self.untagged(HISTORY)
                (code, out), _ = self.curated(text, included)
                self.assertEqual((code, out['reasons']), (1, [reason]))

    def test_rl6_moved_lines_take_their_version_from_the_ticket_they_moved_to(self):
        moved = b'kind: fixed\n\nFixture-tested: The moved line.\n'
        self.env['MOVED'] = json.dumps({'schema': 'openwiz.moved-changes.v1', 'moved': [
            {'closedwiz': 718, 'openwiz': 31, 'sha256': sha(moved)},
            {'closedwiz': 2201, 'openwiz': None, 'sha256': sha(moved)}]})
        self.spec('0.0.13')
        self.spec('0.0.14')
        self.world['repos/{owner}/{repo}/issues/31'] = {
            'number': 31, 'body': 'Moved ticket, was [ClosedWiz #718](https://example.invalid/718).',
            'pull': False, 'sub_issues': 0, 'milestone': {'number': self.milestones['0.0.13'], 'title': '0.0.13'}}
        self.line(718, '0.0.14', 'Fixture-tested: The unrelated OpenWiz 718 line.')
        (self.repo / 'changes/718.md').write_bytes(moved)
        (code, out), folder = self.generate(('0.0.14', '0.0.13'))
        self.assertEqual(code, 0, out)
        text = (folder / 'notes.md').read_text()
        self.assertIn('## 0.0.13 · 2026-11-20\n\nFixture-tested: Version 0.0.13 headline.\n\n'
                      '- Fixture-tested: The moved line.\n', text)
        self.assertNotIn('unrelated', text)
        (self.repo / 'changes/718.md').rename(self.repo / 'changes/closedwiz-718.md')
        self.line(718, '0.0.14', 'Fixture-tested: The new OpenWiz 718 line.')
        (code, out), folder = self.generate(('0.0.14', '0.0.13'))
        self.assertEqual(code, 0, out)
        text = (folder / 'notes.md').read_text()
        self.assertIn('- Fixture-tested: The moved line.\n', text[text.index('## 0.0.13'):])
        self.assertIn('- Fixture-tested: The new OpenWiz 718 line.\n', text[:text.index('## 0.0.13')])
        for name, change, reason in (
                ('overwritten moved line', lambda: (self.repo / 'changes/closedwiz-718.md').unlink(),
                 'entry: changes/718.md is not the moved ClosedWiz #718 line: rename the moved line '
                 'changes/closedwiz-718.md, or record its new bytes in the moved-number map'),
                ('unmapped prefix', lambda: (self.repo / 'changes/closedwiz-9.md').write_bytes(moved),
                 'entry: changes/closedwiz-9.md: ClosedWiz #9 is not in the moved-number map'),
                ('moved ticket that did not move', lambda: (self.repo / 'changes/2201.md').write_bytes(moved),
                 'entry: changes/2201.md: ClosedWiz #2201 has no OpenWiz ticket: record it as an exclusion'),
                ('map without the was link', lambda: self.world['repos/{owner}/{repo}/issues/31'].update(body=''),
                 'entry: OpenWiz #31 does not say it was ClosedWiz #718')):
            with self.subTest(case=name):
                state = {p: p.read_bytes() for p in (self.repo / 'changes').iterdir()}
                world = json.loads(json.dumps(self.world))
                change()
                (code, out), _ = self.generate(('0.0.14', '0.0.13'))
                self.assertEqual((code, out['reasons']), (1, [reason]))
                for p in (self.repo / 'changes').iterdir():
                    if p not in state:
                        p.unlink()
                for p, data in state.items():
                    p.write_bytes(data)
                self.world = world
        (self.repo / 'changes/2201.md').write_bytes(moved)
        (code, out), _ = self.generate(('0.0.14', '0.0.13'), excluded=[('changes/2201.md', sha(moved))])
        self.assertEqual(code, 0, out)


def section(version):
    return (f"## {version} · 2026-11-20\n\n**Use {version}**\n\n**What's new for you**\n\n"
            f"- You can use {version} part one.\n- You can use {version} part two.\n\n"
            f"Tested on synthetic {version} checks.\n\n"
            f"**Under the hood**\n\n- Synthetic {version} internals.\n- See "
            f"[the ticket](https://github.com/openwizdev/OpenWiz/issues/1).\n")


PREAMBLE = '# Changelog\n\nAll synthetic versions, newest first.\n\n'
HISTORY = ('# Changelog\n\nAll synthetic versions, newest first.\n\n'
           '## 0.0.5 · 2026-01-05\n\n**Earlier unpublished entry**\n\n- Synthetic 0.0.5 line.\n\n'
           '## 0.0.4 · 2026-01-04\n\n**Older unpublished entry**\n\n- Synthetic 0.0.4 line.\n')


def re_headings(text):
    return [line for line in text.splitlines() if line.startswith('## ')]


class ArchivePrivacy(unittest.TestCase):
    """D2 scans each staged archive's runtime: the open development contract shipped at
    runtime/contracts/open-development.v1.md gets the repository's bad-block rule, nothing else does."""
    PLANTED = ('thr_' + 'planted0001', '/home/' + 'plantedname/notes', 'prj_' + 'planted42', 'robin' + '@' + 'mail.invalid')
    CONTRACT = 'runtime/contracts/open-development.v1.md'

    def setUp(self):
        import candidate
        self.candidate = candidate
        self.tmp = tempfile.TemporaryDirectory(prefix='release-d2-archive-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / 'artifacts'
        self.folder.mkdir()
        for target in TARGETS:
            (self.folder / f'openwiz-{VERSION}-{target}.manifest.json').write_text('{}\n')
        self.literals = self.root / 'literals.txt'
        self.literals.write_text('synthetic-private-term-zq\n')

    def bad(self, planted=None):
        return ''.join('Bad: a planted case.\n\n```bad\n' + x + '\n```\n\n' for x in planted or self.PLANTED)

    def scan(self, files):
        def stage(manifest, archive, checksum, target, keep=None):
            build = Path(keep) / ('build-' + target)
            for name, text in files.items():
                (build / name).parent.mkdir(parents=True, exist_ok=True)
                (build / name).write_text(text)
            return build
        real = self.candidate.stage
        self.candidate.stage = stage
        try:
            return self.candidate.scan_artifacts({'release_version': VERSION}, self.folder, self.literals)
        finally:
            self.candidate.stage = real

    def test_d2_the_contracts_planted_bad_blocks_pass_at_its_runtime_path(self):
        self.assertEqual(self.scan({self.CONTRACT: '# Contract\n\n' + self.bad() + '```good\nclean\n```\n',
                                    'runtime/install.py': '# clean\n'}), [])

    def test_d2_a_planted_string_outside_a_bad_block_in_the_contract_is_still_a_finding(self):
        for planted in self.PLANTED:
            for outside in (planted + '\n', '```good\n' + planted + '\n```\n', '```bad\nok\n```\n' + planted + '\n'):
                with self.subTest(planted=planted, outside=outside):
                    self.assertEqual(self.scan({self.CONTRACT: self.bad() + outside}), ['finding'])

    def test_d2_a_bad_block_in_any_other_runtime_file_is_still_a_finding(self):
        for name in ('runtime/contracts/agent-status.v1.md', 'runtime/skills/triage/SKILL.md',
                     'runtime/install.py', 'runtime/open-development.v1.md'):
            for planted in self.PLANTED:
                with self.subTest(name=name, planted=planted):
                    self.assertEqual(self.scan({self.CONTRACT: self.bad(), name: self.bad([planted])}), ['finding'])

    def test_d2_another_member_ending_in_the_contracts_name_gets_no_exemption(self):
        for name in ('runtime/skills/synthetic/contracts/open-development.v1.md', 'runtime/runtime/contracts/open-development.v1.md',
                     'runtime/contracts/x-open-development.v1.md', 'runtime/skills/open-development.v1.md'):
            with self.subTest(name=name):
                self.assertEqual(self.scan({name: self.bad()}), ['finding'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
