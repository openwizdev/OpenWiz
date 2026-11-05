#!/usr/bin/env python3
"""The cold-consumer install journey (#1109, IF1-IF9 integration), on fixtures only.

From the one install line to a first fleet, in the confirmed order the packaged
install skill gives (its numbered sections, read from the installed copy): the
actual entry `tools/install/install` checks the machine, downloads a synthetic
release through an injected transport and installs it; the installed runtime's
own setup tool checks connections and prepares the project against T3's
recording fakes; the installed `openwiz engine` runs the installed engine; and
the first fleet replays T6's recorded conversation through the installed
onboarding helper and launch-fleet scripts. The consumer is a plain folder with
no OpenWiz sources and no skills checkout. Recording `cargo`, `rustc`, `npm`,
`node` and `npx` come first on PATH: any call fails the journey.

Fixtures prove the composition, its gates and its refusals; never a real
release, account, machine, elapsed time or live behaviour.
"""
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
TOOLS = ROOT / 'tools/install'
ENTRY = TOOLS / 'install'
CONNECT = ROOT / 'apps/web/test/fixtures/install-connections'
ONBOARD_TESTS = TOOLS / 'tests/onboard'
TARGET = 'x86_64-unknown-linux-gnu'
VERSION = '0.0.99'
NAME = 'openwiz-' + TARGET
BASE = 'https://github.com/openwizdev/openwiz/releases/'
LINE = 'Install OpenWiz from github.com/openwizdev/openwiz'
ORDER = ['Preflight', 'Verified install', 'Setup and connections', 'Engine', 'Explain', 'First fleet']
# #2293 (PR6, copy only): contracts/public-offer.v1.md's free-only copy, as independent literals.
FREE_ONLY = ('OpenWiz is free now. Paid plans come later. '
             'CloudRoom and model charges are separate and not included.')
NO_REFERRAL = 'Referral verification is unavailable. No referral is applied.'
NOT_OFFERED = re.compile(r'upgrad|\btrial|\$\s?[0-9]|per month|checkout|subscri', re.I)
BUILD_TOOLS = ('cargo', 'rustc', 'rustup', 'npm', 'node', 'npx')
REPO = 'synthetic-owner/synthetic-consumer'
PROFILE = {'metadata': 'read', 'contents': 'write', 'issues': 'write', 'pull_requests': 'write',
           'checks': 'read', 'actions': 'read'}
TOKEN = 'ghs_SyntheticInstallationToken0000000000000001'
PERSONAL = 'gho_SyntheticPersonalToken00000000000000000002'

sys.path.insert(0, str(TOOLS))
sys.dont_write_bytecode = True
from fixture_bundle import handover_runtime  # noqa: E402
from install import HANDOVER_RUNTIME, PROGRAMS, REQUIRED, sha  # noqa: E402


def module(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    value = importlib.util.module_from_spec(spec)
    loader.exec_module(value)
    return value


def entry():
    """The actual install entry, loaded as a module so the transport can be injected."""
    return module('openwiz_install_entry', ENTRY)


def tracked(folder, prefix):
    """Every tracked regular file under a source folder, at its runtime path."""
    out = {}
    for path in sorted(folder.rglob('*')):
        if (path.is_file() and not path.is_symlink() and '__pycache__' not in path.parts
                and not any(part.startswith('.') for part in path.relative_to(folder).parts)):
            out[prefix + path.relative_to(folder).as_posix()] = path.read_bytes()
    return out


def bundle_assets(source):
    """A synthetic release bundle holding the tracked runtime the journey runs.

    Programs are fixtures: `openwiz` is the journey's dispatcher, the server and
    service are inert. Every runtime file is the repository's own bytes."""
    assets = {path: b'Synthetic runtime, no effects.\n' for path in REQUIRED}
    for program in PROGRAMS:
        assets[program] = b'#!/bin/sh\nexit 0\n'
    assets['openwiz'] = (HERE / 'fake_openwiz').read_bytes()
    assets['web/index.html'] = b'<!doctype html><title>OpenWiz</title>\n'
    assets['web/setup.html'] = b'<!doctype html><title>Set up OpenWiz</title>\n'
    for name in ('install.py', 'pull.py'):
        assets['runtime/' + name] = (TOOLS / name).read_bytes()
    assets.update(tracked(TOOLS / 'setup', 'runtime/setup/'))
    assets.update(tracked(ROOT / 'tools/github-app', 'runtime/github-app/'))
    assets['runtime/access/access.py'] = (TOOLS / 'access/access.py').read_bytes()
    assets.update(handover_runtime())
    for skill in ('setup', 'grill', 'plan-graph', 'launch-fleet', 'onboard', 'install'):
        assets.update(tracked(ROOT / 'skills' / skill, f'runtime/skills/{skill}/'))
    assets = {k: v for k, v in assets.items() if not re.search(r'(^|/)test[^/]*$|/tests?/', k)}
    identity = f'openwiz.package.v1\n{VERSION}\n{source}\n{TARGET}\n'.encode()
    assets['web/openwiz-build.txt'] = identity
    assets['runtime/openwiz-build.txt'] = identity
    return assets


def release(folder, source='1' * 40, tamper=False):
    """The release's published files, as GitHub serves them: checksum file, manifest, archive."""
    folder.mkdir(mode=0o700)
    assets = bundle_assets(source)
    archive_name = f'openwiz-{VERSION}-{TARGET}.tar.gz'
    buffer = io.BytesIO()
    rows = []
    with tarfile.open(fileobj=buffer, mode='w:gz', format=tarfile.USTAR_FORMAT) as tar:
        for path, data in sorted(assets.items()):
            mode = '0700' if path in PROGRAMS or path.endswith('.sh') else '0600'
            info = tarfile.TarInfo(path)
            info.size, info.mode = len(data), int(mode, 8)
            tar.addfile(info, io.BytesIO(data))
            rows.append({'path': path, 'sha256': sha(data), 'bytes': len(data), 'mode': mode})
    archive = buffer.getvalue()
    manifest = json.dumps({'schema': 'openwiz.install.v1', 'version': VERSION, 'source': source,
                           'target': TARGET, 'setup_api': 1, 'archive': archive_name,
                           'archive_sha256': sha(archive), 'archive_bytes': len(archive),
                           'assets': rows}).encode()
    if tamper:
        archive = archive[:-1] + bytes([archive[-1] ^ 1])
    files = {NAME + '.sha256': f'{sha(manifest)}  {NAME}.manifest.json\n'.encode(),
             NAME + '.manifest.json': manifest, archive_name: archive}
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return {'assets': assets, 'archive': archive_name, 'files': files}


class Transport:
    """GitHub's release downloads, from a local folder; every URL is recorded."""

    def __init__(self, published):
        self.published = published
        self.urls = []

    def __call__(self, url, limit):
        self.urls.append(url)
        files = self.published['files']
        for prefix in (BASE + 'latest/download/', BASE + f'download/v{VERSION}/'):
            if url.startswith(prefix) and url[len(prefix):] in files:
                data = files[url[len(prefix):]]
                if len(data) > limit:
                    raise ValueError('artifact exceeds its declared byte bound')
                return data
        raise OSError('synthetic: 404')


class AppAPI:
    """GitHub's App API on 127.0.0.1 for the installed setup check; records each request."""

    def __init__(self, case):
        requests = self.requests = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def reply(self, status, value):
                body = json.dumps(value).encode()
                self.send_response(status)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                requests.append(('GET', self.path))
                if self.path == '/app/installations':
                    return self.reply(200, [{'id': 2002, 'app_id': 1001, 'account': {'login': 'synthetic-owner'},
                                             'permissions': PROFILE, 'repository_selection': 'selected',
                                             'suspended_at': None}])
                self.reply(404, {'message': 'synthetic: unexpected route'})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))) or b'{}')
                requests.append(('POST', self.path))
                if self.path == '/app/installations/2002/access_tokens':
                    expiry = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 3000))
                    return self.reply(201, {'token': TOKEN, 'expires_at': expiry,
                                            'permissions': body.get('permissions', {}),
                                            'repository_selection': 'selected',
                                            'repositories': [{'full_name': REPO}]})
                self.reply(404, {'message': 'synthetic: unexpected route'})

        self.server = HTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        case.addCleanup(self.server.server_close)
        case.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:%d' % self.server.server_address[1]


class Consumer:
    """A cold consumer: a private HOME, a plain project folder and recording build tools."""

    def __init__(self, case):
        self.case = case
        self.dir = Path(tempfile.mkdtemp(prefix='install-journey-'))
        case.addCleanup(shutil.rmtree, self.dir, True)
        self.dir.chmod(0o700)
        self.home = self.dir / 'home'
        self.home.mkdir(mode=0o700)
        self.project = self.dir / 'project'
        shutil.copytree(CONNECT / 'consumer', self.project)
        self.root = self.home / '.local/lib/openwiz'
        self.downloads = self.dir / 'downloads'
        self.shims = self.dir / 'shims'
        self.shims.mkdir()
        self.build_log = self.dir / 'build-tools.log'
        for tool in BUILD_TOOLS:
            shim = self.shims / tool
            shim.write_text('#!/bin/sh\necho "%s $*" >> "%s"\nexit 97\n' % (tool, self.build_log))
            shim.chmod(0o755)
        # T3's recording `gh` (the agents' own login), alone in its own folder.
        self.gh = self.dir / 'gh'
        self.gh.mkdir()
        (self.gh / 'gh').write_text('#!/bin/sh\nexec /usr/bin/python3 -I "%s" "$@"\n' % (CONNECT / 'gh'))
        (self.gh / 'gh').chmod(0o755)
        self.fakes = self.dir / 'fakes'
        self.fakes.mkdir()
        os.symlink(ONBOARD_TESTS, self.fakes / 'onboard')
        os.symlink(CONNECT, self.fakes / 'connections')
        self.scenario = self.dir / 'scenario.json'
        self.calls = self.dir / 'calls.jsonl'
        self.scenario.write_text(json.dumps({
            'cloudroom': 'ok', 'repository': REPO, 'identity': 'person', 'settings': True,
            'issue': {'number': 7, 'state': 'open'}, 'threads': {'thr_synthetic_answer': 'prj_synthetic'},
            'harnesses': [{'harness': 'claude-code', 'provider': 'claude-code', 'attachments': None,
                           'steer': None, 'models': [{'model': 'synthetic-model', 'efforts': ['high']}]}]}))
        self.outputs = []

    def env(self):
        env = {k: v for k, v in os.environ.items() if k in ('LANG', 'LC_ALL', 'TMPDIR')}
        if getattr(self, 'host', None):
            env['JOURNEY_HOST'] = self.host
        env.update(HOME=str(self.home), PATH='%s:%s:/usr/bin:/bin' % (self.shims, self.gh),
                   GH_TOKEN=PERSONAL, SYNTHETIC_SCENARIO=str(self.scenario),
                   SYNTHETIC_CALLS=str(self.calls), JOURNEY_FAKES=str(self.fakes))
        return env

    def run(self, argv, check=None):
        result = subprocess.run(argv, cwd=self.project, env=self.env(), capture_output=True,
                                text=True, timeout=120)
        self.outputs.append(result.stdout + result.stderr)
        if check is not None:
            self.case.assertEqual(result.returncode, check, (argv, result.stdout, result.stderr))
        return result

    def entry(self, *args, check=0):
        return self.run([sys.executable, '-I', str(ENTRY), *args], check)

    def build_tool_calls(self):
        return self.build_log.read_text().splitlines() if self.build_log.exists() else []


def documented(skill, marker, **values):
    """The one command the skill documents containing `marker`, as an argv, with
    its placeholders (<build>, <state>, <root>, <id>, cloud|local) filled in."""
    text = skill.read_text()
    found = [line.strip() for line in re.findall(r'^(.*)$', text, re.M) if marker in line and not line.lstrip().startswith(('#', '-', '>'))]
    found += re.findall(r'`([^`\n]*%s[^`\n]*)`' % re.escape(marker), text)
    commands = sorted({c for c in found if c.startswith(('python3 ', '<build>/'))})
    assert len(commands) == 1, (marker, commands)
    argv = shlex.split(commands[0])
    names = {'<build>': 'build', '$build': 'build', '<state>': 'state', '<root>': 'root', '<id>': 'operation'}
    out = []
    for word in argv:
        for token, key in names.items():
            if token in word:
                word = word.replace(token, str(values[key]))
        out.append('local' if word == 'cloud|local' else word)
    return [sys.executable if out[0] == 'python3' else out[0], *out[1:]]


def steps(skill):
    """The packaged skill's numbered sections, in order."""
    return [m for m in re.findall(r'^## [0-9]+\. (.+)$', skill.read_text(), re.M)]


def section(skill, title):
    text = skill.read_text()
    return text.split(f'. {title}\n', 1)[1].split('\n## ', 1)[0]


class InstallJourney(unittest.TestCase):

    def install(self, c, published, transport=None):
        """The skill's step 2, with the transport injected into the actual entry."""
        transport = transport or Transport(published)
        out = io.StringIO()
        code = entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                            fetch=transport, stdout=out)
        self.assertEqual(code, 0, out.getvalue())
        result = c.entry('install', '--assets', str(c.downloads), '--target', TARGET, '--root', str(c.root))
        return json.loads(result.stdout), transport

    def test_the_line_resolves_to_the_packaged_skill_and_its_confirmed_order(self):
        plugin = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        self.assertIn('./skills/install', plugin['skills'])
        skill = ROOT / 'skills/install/SKILL.md'
        self.assertIn('> ' + LINE + '\n', skill.read_text())
        self.assertIn('Install OpenWiz from', skill.read_text().split('\n---\n', 1)[0], 'its description names the line')
        self.assertEqual(steps(skill), ORDER)

    def test_the_packaged_skill_and_guide_offer_free_now_and_paid_plans_later(self):
        # #2293: OpenWiz is free; a CloudRoom purchase is upstream and separate, never an
        # OpenWiz upgrade; no price, trial or checkout; no referral, and the copy says why.
        for path in ('skills/install/SKILL.md', 'docs/install.md'):
            with self.subTest(path):
                text = ' '.join((ROOT / path).read_text().split())
                self.assertIn(FREE_ONLY, text)
                self.assertIn(NO_REFERRAL, text)
                self.assertEqual(NOT_OFFERED.findall(text), [])
                self.assertEqual(set(re.findall(r'cloudroom\.dev/[^\s`)]*', text)), {'cloudroom.dev/pricing'},
                                 "CloudRoom's own page, with no referral code or parameter")

    def test_from_the_line_to_a_first_fleet_on_a_cold_consumer(self):
        c = Consumer(self)
        published = release(self.dir_for(c))
        done = []

        def preflight():
            # The actual entry on this machine's real PATH and disk; the host is
            # the journey's supported Linux target, so any CI host replays it.
            out = io.StringIO()
            self.assertEqual(entry().main(['preflight'], host=('Linux', 'x86_64'), stdout=out), 0, out.getvalue())
            result = type('Result', (), {'stdout': out.getvalue()})
            report = json.loads(result.stdout)
            self.assertEqual(report['schema'], 'openwiz.preflight.v1')
            self.assertEqual(report['target'], TARGET)
            self.assertTrue(report['ready'])
            ids = [check['id'] for check in report['checks']]
            self.assertEqual(ids, ['python', 'target', 'disk', 'room-cli', 'gh', 'git'])
            self.assertNotIn('cargo', result.stdout)

        def verified_install():
            result, transport = self.install(c, published)
            self.assertEqual((result['version'], result['target'], result['activated']), (VERSION, TARGET, True))
            self.assertEqual(transport.urls, [BASE + f'latest/download/{NAME}.sha256',
                                              BASE + f'latest/download/{NAME}.manifest.json',
                                              BASE + f'download/v{VERSION}/{published["archive"]}'])
            self.build = Path(result['build'])
            self.state = Path(result['state_root'])
            self.assertEqual(Path(os.readlink(c.root / 'current')), self.build)
            self.assertEqual((c.root / 'channel.json').read_text(),
                             '{"schema":"openwiz.update-channel.v1","channel":"packaged"}\n')
            status = json.loads(c.entry('status', '--root', str(c.root)).stdout)
            self.assertEqual((status['version'], status['channel'], status['build']), (VERSION, 'packaged', str(self.build)))

        def setup_and_connections():
            # The installed runtime's own setup tool; each component's result
            # code is the evidence the setup page turns into its states.
            tool = [sys.executable, '-I', '-B', str(self.build / 'runtime/setup/setup.py')]
            api = AppAPI(self)
            check = [*tool, 'check', '--state-dir', str(self.state), '--api-base', api.base]
            results = json.loads(c.run(check, 0).stdout)['results']
            self.assertEqual((results['github_app'], results['project']), ('app_missing', 'project_unprepared'))
            self.assertEqual(api.requests, [], 'no App API call before an App is connected')
            prepare = [*tool, 'prepare', '--state-dir', str(self.state), '--repository', REPO,
                       '--project', 'prj_synthetic', '--operator', 'synthetic-owner', '--service-issue', '7',
                       '--answer-thread', 'thr_synthetic_answer', '--harness', 'claude-code',
                       '--model', 'synthetic-model', '--effort', 'high']
            proposed = json.loads(c.run(prepare, 0).stdout)
            self.assertEqual(proposed['phase'], 'proposed')
            self.assertEqual(json.loads(c.run(check, 0).stdout)['results']['project'], 'project_unprepared',
                             'a proposal saves nothing')
            applied = json.loads(c.run([*prepare, '--yes', '--operation', proposed['operation_id']], 0).stdout)
            self.assertEqual(applied['phase'], 'applied')
            self.connect_app()
            results = json.loads(c.run(check, 0).stdout)['results']
            self.assertEqual({k: results[k] for k in ('harness', 'personal_github', 'github_app', 'project')},
                             {'harness': 'harness_listed', 'personal_github': 'identity_verified',
                              'github_app': 'app_verified', 'project': 'project_verified'}, results)
            self.assertTrue(any(r[0] == 'POST' for r in api.requests), 'the App token was minted to prove access')

        def engine():
            openwiz = str(self.build / 'openwiz')
            preview = c.run([openwiz, 'engine', 'preview', '--location', 'local',
                             '--state-dir', str(self.state), '--json'])
            value = json.loads(preview.stdout)
            self.assertEqual(preview.returncode, 0, preview.stdout + preview.stderr)
            self.assertEqual(value['schema'], 'openwiz.engine.v1')
            text = json.dumps(value)
            self.assertIn('unknown', text, 'no measurement: the cost stays unknown')
            status = json.loads(c.run([openwiz, 'engine', 'status', '--state-dir', str(self.state), '--json'], 0).stdout)
            self.assertNotEqual(status.get('state'), 'running', 'a preview starts no engine')

        def explain():
            installed = self.build / 'runtime/skills'
            said = section(installed / 'install/SKILL.md', 'Explain')
            quote = [line for line in said.splitlines() if line.startswith('> ')]
            onboard = [line for line in section(installed / 'onboard/SKILL.md', 'Explain').splitlines()
                       if line.startswith('> ')]
            self.assertEqual(quote, onboard, 'the same few sentences the onboarding gives')
            for concept in ('**idea**', '**grill**', '**spec**', '**tickets**', '**builder**', '**reviewer**', '**merges**'):
                self.assertIn(concept, quote[0])

        def first_fleet():
            onboard = module('onboard_journey', ONBOARD_TESTS / 'test_journey.py')
            installed = self.build / 'runtime/skills/onboard'
            onboard.SKILL = installed / 'SKILL.md'
            onboard.HELPER = installed / 'scripts/onboard.py'
            j = onboard.Journey(self)
            j.openwiz = self.build / 'openwiz'
            env = j.env
            j.env = lambda: dict(env(), PATH='%s:%s' % (c.shims, env()['PATH']), JOURNEY_FAKES=str(c.fakes))
            results = j.replay()
            for turn, result in results:
                self.assertEqual(result.returncode, turn['exit'], (turn['tool'], result.stdout, result.stderr))
            self.assertEqual(len(j.logged('fleet.tick')), 1, 'the approved frontier starts once')
            watch = results[-1][1].stdout
            self.assertIn('5 tickets: 3 building, 2 blocked', watch)
            self.assertNotEqual(Path(onboard.HELPER).resolve().parents[3], ROOT.resolve())

        runners = {'Preflight': preflight, 'Verified install': verified_install,
                   'Setup and connections': setup_and_connections, 'Engine': engine,
                   'Explain': explain, 'First fleet': first_fleet}
        skill = ROOT / 'skills/install/SKILL.md'
        self.assertEqual(steps(skill), ORDER)
        for title in steps(skill):
            runners[title]()
            done.append(title)
            if title == 'Verified install':
                self.assertEqual(steps(self.build / 'runtime/skills/install/SKILL.md'), ORDER,
                                 'the installed skill gives the same order')
        self.assertEqual(done, ORDER)
        self.assertEqual(c.build_tool_calls(), [], 'no Rust or Node tool was run')
        self.assertFalse(any(p.startswith('private/') or '/private/' in p for p in published['assets']))
        self.assertEqual(sorted(p.name for p in c.project.iterdir()), ['README.md', 'docs'],
                         'the consumer has no OpenWiz sources or skills checkout')
        for output in c.outputs:
            self.assertNotIn(TOKEN, output)
            self.assertNotIn(PERSONAL, output)

    # Helpers for the journey's state.
    def dir_for(self, c):
        return c.dir / 'published'

    def connect_app(self):
        """The App connection T3's flow saves: a disposable key and the App's id."""
        folder = self.state / 'service/app'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        (self.state / 'service').chmod(0o700)
        subprocess.run(['/usr/bin/openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048',
                        '-out', str(folder / 'private-key.pem')], check=True, capture_output=True)
        (folder / 'private-key.pem').chmod(0o600)
        (folder / 'app.json').write_text('{"app_id":1001}')
        (folder / 'app.json').chmod(0o600)

    def test_a_tampered_release_is_refused_and_the_last_good_build_stays(self):
        c = Consumer(self)
        good = release(c.dir / 'good')
        first, _ = self.install(c, good)
        bad = release(c.dir / 'bad', source='2' * 40, tamper=True)
        shutil.rmtree(c.downloads)
        out = io.StringIO()
        self.assertEqual(entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                                      fetch=Transport(bad), stdout=out), 0, out.getvalue())
        refused = c.entry('install', '--assets', str(c.downloads), '--target', TARGET, '--root', str(c.root), check=5)
        self.assertEqual(json.loads(refused.stdout)['outcome'], 'refused')
        self.assertEqual(os.readlink(c.root / 'current'), first['build'], 'the last good build stays selected')
        self.assertFalse((c.root / 'state/service/builds' / ('2' * 40)).exists())

    def test_a_repeated_install_reuses_the_verified_build(self):
        c = Consumer(self)
        published = release(c.dir / 'published')
        first, _ = self.install(c, published)
        again = json.loads(c.entry('install', '--assets', str(c.downloads), '--target', TARGET,
                                   '--root', str(c.root)).stdout)
        self.assertEqual(again['build'], first['build'])
        self.assertEqual(os.readlink(c.root / 'current'), first['build'])

    def test_an_interrupted_download_installs_nothing_until_it_completes(self):
        c = Consumer(self)
        published = release(c.dir / 'published')
        cut = dict(published, files={k: v for k, v in published['files'].items() if k != published['archive']})
        out = io.StringIO()
        self.assertEqual(entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                                      fetch=Transport(cut), stdout=out), 5)
        self.assertEqual(json.loads(out.getvalue())['outcome'], 'refused')
        c.entry('install', '--assets', str(c.downloads), '--target', TARGET, '--root', str(c.root), check=5)
        self.assertFalse((c.root / 'current').exists())
        shutil.rmtree(c.downloads, ignore_errors=True)
        result, _ = self.install(c, published)
        self.assertTrue(result['activated'])

    def test_a_published_checksum_that_does_not_match_downloads_nothing(self):
        c = Consumer(self)
        published = release(c.dir / 'published')
        files = dict(published['files'])
        files[NAME + '.sha256'] = ('0' * 64 + f'  {NAME}.manifest.json\n').encode()
        out = io.StringIO()
        self.assertEqual(entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                                      fetch=Transport(dict(published, files=files)), stdout=out), 5)
        self.assertFalse(c.downloads.exists() and any(c.downloads.iterdir()))

    def test_a_manifest_naming_any_other_archive_path_downloads_nothing(self):
        c = Consumer(self)
        published = release(c.dir / 'published')
        for name in ('../escape.tar.gz', 'nested/openwiz-0.0.99-x86_64-unknown-linux-gnu.tar.gz', 'archive.zip'):
            manifest = json.loads(published['files'][NAME + '.manifest.json'])
            manifest['archive'] = name
            raw = json.dumps(manifest).encode()
            files = {NAME + '.sha256': f'{sha(raw)}  {NAME}.manifest.json\n'.encode(),
                     NAME + '.manifest.json': raw, name: published['files'][published['archive']]}
            transport = Transport(dict(published, files=files))
            out = io.StringIO()
            self.assertEqual(entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                                          fetch=transport, stdout=out), 5, (name, out.getvalue()))
            self.assertEqual(len(transport.urls), 2, 'the archive is never requested')
            self.assertFalse(c.downloads.exists())

    def test_a_fresh_home_installs_without_any_precreated_folder(self):
        # R7: a new user's HOME has no ~/.local/lib; the documented install still completes.
        c = Consumer(self)
        self.assertFalse((c.home / '.local').exists())
        result, _ = self.install(c, release(c.dir / 'published'))
        self.assertTrue(result['activated'])
        for folder in (c.home / '.local', c.home / '.local/lib', c.root):
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700, folder)

    def test_the_install_parent_is_never_made_outside_home_or_through_a_link(self):
        c = Consumer(self)
        published = release(c.dir / 'published')
        out = io.StringIO()
        self.assertEqual(entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                                      fetch=Transport(published), stdout=out), 0, out.getvalue())
        outside = c.dir / 'elsewhere/lib/openwiz'
        c.entry('install', '--assets', str(c.downloads), '--target', TARGET, '--root', str(outside), check=5)
        self.assertFalse((c.dir / 'elsewhere').exists(), 'nothing is made outside HOME')
        (c.dir / 'target').mkdir()
        os.symlink(c.dir / 'target', c.home / '.local')
        c.entry('install', '--assets', str(c.downloads), '--target', TARGET, '--root', str(c.root), check=5)
        self.assertEqual(list((c.dir / 'target').iterdir()), [], 'nothing is made through a link')

    def installed(self, c, setup=False):
        result, _ = self.install(c, release(c.dir / 'published'))
        build, state = Path(result['build']), Path(result['state_root'])
        if setup:
            # Setup before the engine, as the skill orders it: its documented
            # check, the project prepared, the App connected, then checked again.
            self.build, self.state = build, state
            skill = build / 'runtime/skills/install/SKILL.md'
            api = AppAPI(self)
            check = [*documented(skill, 'setup.py check', build=build, state=state, root=c.root), '--api-base', api.base]
            c.run(check, 0)
            prepare = [sys.executable, '-I', '-B', str(build / 'runtime/setup/setup.py'), 'prepare', '--state-dir', str(state),
                       '--repository', REPO, '--project', 'prj_synthetic', '--operator', 'synthetic-owner',
                       '--service-issue', '7', '--answer-thread', 'thr_synthetic_answer', '--harness', 'claude-code',
                       '--model', 'synthetic-model', '--effort', 'high']
            proposed = json.loads(c.run(prepare, 0).stdout)
            c.run([*prepare, '--yes', '--operation', proposed['operation_id']], 0)
            self.connect_app()
            results = json.loads(c.run(check, 0).stdout)['results']
            self.assertEqual(results['project'], 'project_verified', 'the documented check reads the install state')
        return build, state

    def test_the_documented_engine_commands_use_the_install_state(self):
        # R3: the skill's own commands, as written, keep every setup effect in the install's state.
        c = Consumer(self)
        build, state = self.installed(c, setup=True)
        skill = build / 'runtime/skills/install/SKILL.md'
        values = {'build': build, 'state': state, 'root': c.root}
        preview = c.run(documented(skill, 'engine preview', **values), 0)
        operation = json.loads(preview.stdout)
        saved = json.loads((state / 'setup/state.json').read_text()) if (state / 'setup/state.json').exists() else {}
        self.assertIn(operation['operation']['operation_id'] if 'operation' in operation else operation.get('operation_id'),
                      json.dumps(saved), 'the preview is saved in the install state')

    def test_the_documented_local_activation_reaches_its_existing_gates(self):
        # R4: the documented confirmation names the installation and reaches the
        # existing holds on every host; nothing is activated or started anywhere.
        # On the PC's own target (Linux x86_64) T9 records one held PC activation;
        # on any other host the PC path stops before any record.
        expected = {'Linux/x86_64': (6, 'held', 'held', 'No service was started'),
                    'Linux/aarch64': (5, 'not_activated', 'absent', 'no service was started'),
                    'Darwin/arm64': (5, 'not_activated', 'absent', 'no service was started')}
        for host, (code, status, pc, words) in expected.items():
            with self.subTest(host=host):
                c = Consumer(self)
                c.host = host
                build, state = self.installed(c, setup=True)
                skill = build / 'runtime/skills/install/SKILL.md'
                values = {'build': build, 'state': state, 'root': c.root}
                preview = json.loads(c.run(documented(skill, 'engine preview', **values), 0).stdout)
                operation = preview['engine']['operation_id']
                self.assertEqual([p for p in build.rglob('*') if p.name == '__pycache__'], [],
                                 'the documented setup commands leave the verified build unchanged')
                activated = c.run(documented(skill, 'engine activate', operation=operation, **values))
                held = json.loads(activated.stdout)
                self.assertNotIn('Name this installation with --root', held['reason'])
                self.assertNotIn('not the verified selected installation', held['reason'])
                self.assertEqual((activated.returncode, held['activation_allowed'], held['location_status'],
                                  held['pc_activation']['state'], held['operation']['phase']),
                                 (code, False, status, pc, 'proposed'), held['reason'])
                self.assertIn(words, held['reason'])
                status_now = json.loads(c.run(documented(skill, 'engine status', **values), 0).stdout)
                self.assertEqual((status_now['activation_allowed'], status_now['location_status']), (False, status),
                                 'status reads the same hold, never running')

    def test_open_serves_setup_with_the_install_state(self):
        # R3: the setup server `install open` starts reads the same state the tools write.
        c = Consumer(self)
        build, state = self.installed(c)
        install = entry()
        seen = {}

        def serve(result, port, browser=False):
            seen.update(result=result, state=os.environ.get('OPENWIZ_STATE_DIR'))
            return 0
        install.installer.serve_installed = serve
        previous = os.environ.pop('OPENWIZ_STATE_DIR', None)
        try:
            self.assertEqual(install.main(['open', '--root', str(c.root)], stdout=io.StringIO()), 0)
        finally:
            os.environ.pop('OPENWIZ_STATE_DIR', None)
            if previous is not None:
                os.environ['OPENWIZ_STATE_DIR'] = previous
        self.assertEqual(seen['state'], str(state))
        self.assertEqual(seen['result']['build'], str(build))

    def test_status_and_open_refuse_a_selection_they_cannot_verify(self):
        # R6: the selected build must be this state's, named by its own verified source.
        for case in ('foreign', 'manifest', 'source', 'asset'):
            c = Consumer(self)
            build, state = self.installed(c)
            if case == 'foreign':
                other = state / 'service/builds/not-a-commit'
                shutil.copytree(build, other, symlinks=True)
                os.unlink(c.root / 'current')
                os.symlink(other, c.root / 'current')
            elif case == 'manifest':
                manifest = json.loads((build / 'install-manifest.json').read_text())
                manifest['assets'] = manifest['assets'][:3]
                (build / 'install-manifest.json').write_text(json.dumps(manifest))
            elif case == 'source':
                other = state / 'service/builds' / ('2' * 40)
                shutil.copytree(build, other, symlinks=True)
                os.unlink(c.root / 'current')
                os.symlink(other, c.root / 'current')
            else:
                (build / 'runtime/setup/setup.py').write_text('# changed\n')
            served = []
            install = entry()
            install.installer.serve_installed = lambda *a, **k: served.append(a) or 0
            for command in ('status', 'open'):
                out = io.StringIO()
                self.assertEqual(install.main([command, '--root', str(c.root)], stdout=out), 5, (case, command, out.getvalue()))
            self.assertEqual(served, [], case)

    def test_status_and_open_refuse_a_symlinked_ancestor(self):
        # R6 (re-check): a valid build reached through a redirected ancestor of the
        # root, an explicit state, service/ or builds/ is refused; the paths read
        # the same, but one folder on the way is now a link to a moved copy.
        def redirect(folder):
            moved = folder.with_name(folder.name + '-moved')
            os.rename(folder, moved)
            os.symlink(moved, folder)

        for case in ('control', 'custom-control', 'root-ancestor', 'custom-state-ancestor', 'service', 'builds'):
            with self.subTest(case=case):
                c = Consumer(self)
                custom = case.startswith('custom')
                state_arg = []
                if custom:
                    (c.home / 'custom').mkdir(mode=0o700)
                    state_arg = ['--state-root', str(c.home / 'custom/state')]
                published = release(c.dir / 'published')
                out = io.StringIO()
                self.assertEqual(entry().main(['download', '--target', TARGET, '--dir', str(c.downloads)],
                                              fetch=Transport(published), stdout=out), 0, out.getvalue())
                result = json.loads(c.entry('install', '--assets', str(c.downloads), '--target', TARGET,
                                            '--root', str(c.root), *state_arg).stdout)
                state = Path(result['state_root'])
                if case == 'root-ancestor':
                    redirect(c.home / '.local/lib')
                elif case == 'custom-state-ancestor':
                    redirect(c.home / 'custom')
                elif case == 'service':
                    redirect(state / 'service')
                elif case == 'builds':
                    redirect(state / 'service/builds')
                served = []
                install = entry()
                install.installer.serve_installed = lambda *a, **k: served.append(a) or 0
                want = 0 if case.endswith('control') else 5
                for command in ('status', 'open'):
                    out = io.StringIO()
                    self.assertEqual(install.main([command, '--root', str(c.root), *state_arg], stdout=out), want,
                                     (case, command, out.getvalue()))
                self.assertEqual(len(served), 1 if want == 0 else 0, case)

    def test_preflight_names_each_supported_target_and_refuses_the_rest(self):
        install = entry()
        for host, target in ((('Darwin', 'arm64'), 'aarch64-apple-darwin'),
                             (('Darwin', 'x86_64'), 'x86_64-apple-darwin'),
                             (('Linux', 'x86_64'), 'x86_64-unknown-linux-gnu'),
                             (('Linux', 'aarch64'), None), (('Windows', 'AMD64'), None)):
            out = io.StringIO()
            code = install.main(['preflight'], host=host, stdout=out)
            report = json.loads(out.getvalue())
            self.assertEqual(report['target'], target, host)
            if target is None:
                self.assertEqual(code, 5)
                check = next(item for item in report['checks'] if item['id'] == 'target')
                self.assertEqual(check['state'], 'refused')
                self.assertIn('macOS', check['next'])


if __name__ == '__main__':
    unittest.main()
