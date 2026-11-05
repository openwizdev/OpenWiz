#!/usr/bin/env python3
"""C10 (#2317) offline proofs: the participating readers route through C8's read.py.

Run: python3 -I tools/github-reads/test_consumers.py. Each consumer runs as a
copy at its own relative path in a temporary tree, so it finds the real C8
read.py through its ordinary default location. That tree's read.py records
its arguments and then runs the real one against C8's loopback recording
GitHub. A recording `gh` proves which reads still use it. Synthetic fixtures
only: a pass is fixture evidence, never a live installation, sharing or quota
observation (C13).

Assumption A1: the installation route is used only when its credentials are
configured (`<state>/service/github-reads/installation.json`, the file C9's
protected provisioning writes). Without it every reader keeps its current
`gh` behaviour; with it, a missing helper or a missing, expired or revoked
installation refuses the migrated read and never falls back to `gh`.
"""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import test_read  # noqa: E402  C8's recording GitHub and protected-state fixture

READ = HERE / 'read.py'
COLLECTOR = Path('skills/where-are-we/scripts/read-github.py')
FLEET = Path('skills/launch-fleet/scripts')
FLEET_FIX = ROOT / FLEET / 'fixtures'
REPO = test_read.REPO
FLEET_REPO = 'synthetic-owner/synthetic-repo'  # the launch-fleet fixtures' repository
NOW = '1793534400'  # the launch-fleet fixtures' "now"
NIGHTLY_ENDPOINT = (f'repos/{FLEET_REPO}/actions/workflows/ci.yml/runs?'
                    'event=schedule&branch=main&status=completed&per_page=1')

# synthetic_assumptions: minimal REST-shaped records with invented values,
# not captured from a live account.
SOURCES = {
    'milestones': [{'number': 1, 'title': 'Version one', 'state': 'open', 'open_issues': 2,
                    'closed_issues': 3, 'body': 'PRIVATE_BODY_SENTINEL'}],
    'issues': [{'number': 2, 'title': 'Build one', 'labels': [{'name': 'ready-for-agent'}],
                'milestone': {'number': 1}, 'body': 'PRIVATE_BODY_SENTINEL'},
               {'number': 4, 'title': 'A pull request', 'pull_request': {}, 'labels': [], 'milestone': None}],
    'pulls': [{'number': 3, 'title': 'Change one', 'draft': False, 'head': {'sha': 'synthetic-head-one'},
               'base': {'ref': 'main'}}],
}
QUERIES = {'milestones': 'state=all&per_page=100', 'issues': 'state=open&per_page=100',
           'pulls': 'state=open&per_page=100'}
EXPECTED = {
    'milestones': {'state': 'read', 'items': [
        {'number': 1, 'title': 'Version one', 'state': 'open', 'open_issues': 2, 'closed_issues': 3}]},
    'issues': {'state': 'read', 'items': [
        {'number': 2, 'title': 'Build one', 'labels': ['ready-for-agent'], 'milestone': 1}]},
    'pulls': {'state': 'read', 'items': [
        {'number': 3, 'title': 'Change one', 'draft': False, 'head': {'sha': 'synthetic-head-one'},
         'base': {'ref': 'main'}}]},
}

# The recording gh: logs every call; answers the collector's three slurped
# reads from $ANSWERS, and execs the launch-fleet fake gh for anything else.
GH = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['GH_CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
if os.environ.get('ANSWERS'):
    answers = json.load(open(os.environ['ANSWERS']))
    if args[:5] != ['api', '--method', 'GET', '--paginate', '--slurp'] or args[-1] not in answers:
        sys.exit(91)
    print(json.dumps(answers[args[-1]]))
    sys.exit(0)
os.execv(sys.executable, [sys.executable, '-I', '-S', os.environ['FLEET_GH'], *args])
'''

# The tree's read.py: record the consumer's own arguments, then run C8's.
WRAPPER = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['READER_CALLS'], 'a') as out:
    out.write(json.dumps(sys.argv[1:]) + '\\n')
os.execv(sys.executable, [sys.executable, '-I', {read!r}, *sys.argv[1:], '--api-base', os.environ['READER_BASE']])
'''


class Consumer(test_read.Fixture):
    def setUp(self):
        super().setUp()
        self.root = Path(self.tmp.name)
        self.tree = self.root / 'tree'
        (self.tree / 'tools/github-reads').mkdir(parents=True)
        self.reader = self.tree / 'tools/github-reads/read.py'
        self.reader.write_text(WRAPPER.format(read=str(READ)))
        (self.root / 'bin').mkdir()
        gh = self.root / 'bin/gh'
        gh.write_text(GH)
        gh.chmod(0o755)
        self.gh_calls = self.root / 'gh-calls.jsonl'
        self.reader_calls = self.root / 'reader-calls.jsonl'

    def environment(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN', 'XDG_STATE_HOME')}
        env.update(PATH=f'{self.root / "bin"}{os.pathsep}{os.environ.get("PATH", "")}',
                   HOME=str(self.root / 'home'), OPENWIZ_STATE_DIR=str(self.state),
                   GH_CALLS=str(self.gh_calls), READER_CALLS=str(self.reader_calls),
                   READER_BASE=self.base, GH_TOKEN='synthetic-user-token')
        env.update(extra)
        return env

    def disable(self):
        """Assumption A1's switch off: no configured installation."""
        (self.reads / 'installation.json').unlink()

    def configure(self, *repositories):
        config = self.reads / 'installation.json'
        config.write_text(json.dumps({'installation_id': 2002, 'repositories': list(repositories)}))
        config.chmod(0o600)

    def logged(self, path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def assert_reads_only(self):
        """No accidental write routing: the only non-GET upstream call is the token mint."""
        for call in self.calls:
            if call['method'] != 'GET':
                self.assertEqual((call['method'], call['path']), ('POST', '/app/installations/2002/access_tokens'))


class Collector(Consumer):
    """where-are-we's collector: its three explicit list reads."""

    def setUp(self):
        super().setUp()
        target = self.tree / COLLECTOR
        target.parent.mkdir(parents=True)
        shutil.copy(ROOT / COLLECTOR, target)
        # where-are-we runs launch-fleet's carried copy of the reader (WZ4 #2634, WZ5 #2635).
        self.reader = self.tree / 'skills/launch-fleet/scripts/carried/read.py'
        self.reader.parent.mkdir(parents=True)
        self.reader.write_text(WRAPPER.format(read=str(READ)))
        for name, items in SOURCES.items():
            self.route(f'/repos/{REPO}/{name}?{QUERIES[name]}', items, etag=f'"synthetic-{name}"')
        answers = {f'repos/{{owner}}/{{repo}}/{name}?{QUERIES[name]}': [copy.deepcopy(items)]
                   for name, items in SOURCES.items()}
        self.answers = self.root / 'answers.json'
        self.answers.write_text(json.dumps(answers))

    def collect(self, **extra):
        result = subprocess.run([sys.executable, '-I', str(self.tree / COLLECTOR)], capture_output=True,
                                text=True, timeout=300, env=self.environment(ANSWERS=str(self.answers),
                                                                             **{'GH_REPO': REPO, **extra}))
        self.outputs.append((result.stdout + result.stderr).encode())
        return result.returncode, json.loads(result.stdout), result.stderr

    def test_disabled_keeps_the_gh_reads_unchanged(self):
        self.disable()
        code, sources, _ = self.collect()
        self.assertEqual((code, sources), (0, EXPECTED))
        self.assertEqual([call[-1] for call in self.logged(self.gh_calls)],
                         [f'repos/{{owner}}/{{repo}}/{name}?{QUERIES[name]}' for name in SOURCES])
        self.assertEqual((self.calls, self.logged(self.reader_calls)), ([], []))

    def test_enabled_reads_through_the_installation_with_the_same_output(self):
        code, sources, _ = self.collect()
        self.assertEqual((code, sources), (0, EXPECTED))
        self.assertEqual(self.logged(self.gh_calls), [])
        self.assertEqual(self.logged(self.reader_calls), [
            ['rest', REPO, f'repos/{REPO}/{name}?{QUERIES[name]}', '--purpose', 'display', '--max-age', '60']
            for name in SOURCES])
        reads = self.upstream()
        self.assertEqual([c['path'] for c in reads], [f'/repos/{REPO}/{n}?{QUERIES[n]}' for n in SOURCES])
        for call in reads:
            self.assertEqual(call['method'], 'GET')
            self.assertTrue(call['headers']['Authorization'].startswith('Bearer synthetic-installation-token-'))
            self.assertNotIn('synthetic-user-token', json.dumps(call))
        self.assert_reads_only()
        self.assert_no_secret()

    def test_two_collectors_share_identical_reads(self):
        first = self.collect()
        second = self.collect()
        self.assertEqual((first[:2], second[:2]), ((0, EXPECTED), (0, EXPECTED)))
        # One upstream read per source; the second collector's display reads
        # are answered from the one shared installation cache.
        self.assertEqual(len(self.upstream()), 3)
        self.assertEqual(len(self.mints()), 6)  # every invocation still verifies its authorization
        self.assertEqual(self.logged(self.gh_calls), [])

    def test_missing_expired_or_revoked_installation_refuses_without_gh(self):
        def no_key():
            (self.state / 'service/app/private-key.pem').unlink()
        cases = {'revoked': lambda: self.github.update(mint_status=404),
                 'suspended': lambda: self.github.update(mint_status=403),
                 'expired': lambda: self.github.update(expires_in=-120),
                 'missing credentials': no_key,
                 'unselected repository': lambda: self.configure(test_read.OTHER)}
        for name, plant in cases.items():
            with self.subTest(name):
                self.setUp()
                plant()
                code, sources, _ = self.collect()
                self.assertEqual(code, 2)
                for source in sources.values():
                    self.assertEqual(source['state'], 'unconfirmed')
                    self.assertRegex(source['reason'], r'^installation read refused: [a-z-]+$')
                self.assertEqual(self.logged(self.gh_calls), [])
                self.assertEqual(self.upstream(), [])
                self.assert_no_secret()

    def test_missing_helper_or_repository_refuses_without_gh(self):
        cases = {'helper missing': (lambda: self.reader.unlink(), {},
                                    'installation read refused: the read helper is missing'),
                 'no explicit repository': (lambda: None, {'GH_REPO': ''},
                                            'installation read needs GH_REPO=owner/name')}
        for name, (plant, extra, reason) in cases.items():
            with self.subTest(name):
                self.setUp()
                plant()
                code, sources, _ = self.collect(**extra)
                self.assertEqual(code, 2)
                self.assertEqual(sources, {n: {'state': 'unconfirmed', 'reason': reason} for n in SOURCES})
                self.assertEqual((self.logged(self.gh_calls), self.calls), ([], []))


class Switch(Consumer):
    """A1's one switch reads the same state as C8, in both readers."""

    def verdicts(self, env):
        """Each reader's verdict, seen through its behaviour without GH_REPO."""
        stop = self.root / 'bin/stop-gh'
        stop.write_text('import sys\nsys.exit(7)\n')  # run by the recording gh
        stop.chmod(0o755)
        (self.tree / FLEET).mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / FLEET / 'fleet.sh', self.tree / FLEET / 'fleet.sh')
        (self.tree / COLLECTOR).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / COLLECTOR, self.tree / COLLECTOR)
        base = {k: v for k, v in self.environment(GH_REPO='').items()
                if k not in ('OPENWIZ_STATE_DIR', 'GH_REPO', 'ANSWERS')}
        base.update(env, FLEET_GH=str(stop), GH_CALLS=str(self.root / 'switch-gh.jsonl'))
        fleet = subprocess.run(['/bin/sh', str(self.tree / FLEET / 'fleet.sh'), 'check'], capture_output=True,
                               text=True, timeout=60, env=base, cwd=self.root)
        collector = subprocess.run([sys.executable, '-I', str(self.tree / COLLECTOR)], capture_output=True,
                                   text=True, timeout=60, env=base, cwd=self.root)
        fleet_on = 'the installation read route needs GH_REPO=owner/name' in fleet.stderr
        self.assertTrue(fleet_on or "set GH_REPO=owner/name, or run inside a clone" in fleet.stderr, fleet.stderr)
        reasons = {s['reason'] for s in json.loads(collector.stdout).values()}
        self.assertIn(reasons, ({'installation read needs GH_REPO=owner/name'}, {'gh exited 7'}))
        return fleet_on, reasons == {'installation read needs GH_REPO=owner/name'}

    def test_both_readers_find_the_installation_where_c8_does(self):
        home, xdg = self.root / 'home', self.root / 'xdg'
        layouts = {
            'explicit state': ({'OPENWIZ_STATE_DIR': str(self.state)}, self.state),
            'empty state variable, absolute XDG': ({'OPENWIZ_STATE_DIR': '', 'XDG_STATE_HOME': str(xdg)},
                                                   xdg / 'openwiz'),
            'relative XDG uses HOME': ({'XDG_STATE_HOME': 'relative'}, home / '.local/state/openwiz'),
            'HOME default': ({}, home / '.local/state/openwiz'),
        }
        for name, (env, state) in layouts.items():
            for configured in ('file', 'dangling link', 'none'):
                with self.subTest(name, configured=configured):
                    reads = state / 'service/github-reads'
                    reads.mkdir(parents=True, exist_ok=True)
                    config = reads / 'installation.json'
                    if os.path.lexists(config):
                        config.unlink()  # the fixture's own configured installation
                    if configured == 'file':
                        config.write_text(json.dumps({'installation_id': 2002, 'repositories': [REPO]}))
                    elif configured == 'dangling link':
                        config.symlink_to(reads / 'absent.json')
                    full = dict(env, HOME=str(home))
                    # The independent expectation: C8's own state resolution.
                    expected = subprocess.run(
                        [sys.executable, '-I', '-c', 'import os, sys; sys.path.insert(0, sys.argv[1]); import app; '
                         'print(os.path.lexists(app.state_path(None) / "service/github-reads/installation.json"))',
                         str(ROOT / 'tools/github-app')], capture_output=True, text=True, timeout=60,
                        env=dict({k: v for k, v in os.environ.items()
                                  if k not in ('OPENWIZ_STATE_DIR', 'XDG_STATE_HOME')}, **full)).stdout.strip()
                    self.assertEqual(expected, str(configured != 'none'))
                    self.assertEqual(self.verdicts(full), (configured != 'none',) * 2)
                    if configured != 'none':
                        config.unlink()


class Proxy(dict):
    """REST routes served from the launch-fleet fixture world through its fake gh."""

    def __init__(self, world, log):
        super().__init__()
        self.world, self.log = world, log
        self.page, self.numeric_links = '100', True

    def get(self, path, default=None):
        if path in self:
            return super().get(path, default)
        endpoint = path[1:]
        if endpoint == f'repos/{FLEET_REPO}':
            body = json.dumps({'full_name': FLEET_REPO, 'private': True}).encode()
            return {'raw': body, 'etag': '"synthetic-repository"'}
        accept = ('application/vnd.github.raw+json' if endpoint.startswith(f'repos/{FLEET_REPO}/contents/')
                  else 'application/vnd.github+json')
        result = subprocess.run([sys.executable, '-I', '-S', str(FLEET_FIX / 'gh.py'), 'api', '--include',
                                 '-H', f'Accept: {accept}', endpoint], capture_output=True, timeout=60,
                                env=dict(os.environ, FAKE_GH_WORLD=str(self.world), FAKE_GH_LOG=str(self.log),
                                         FAKE_GH_PAGE=self.page))
        head, _, body = result.stdout.partition(b'\r\n\r\n')
        lines = head.decode().split('\r\n')
        route = {'status': int(lines[0].split()[1]), 'raw': body}
        for line in lines[1:]:
            key, _, value = line.partition(': ')
            if key == 'ETag':
                route['etag'] = value
            elif key == 'Link':
                # The fake gh names later pages by numeric repository id, as
                # GitHub can; a repository-path link is the other form.
                if not self.numeric_links:
                    value = value.replace('/repositories/1/', f'/repos/{FLEET_REPO}/')
                route['link'] = value.replace('https://api.github.com', 'BASE')
        if endpoint.startswith(f'repos/{FLEET_REPO}/actions/workflows/ci.yml/runs?'):
            # Only the latest nightly is requested (per_page=1). Older runs
            # exist, but their numeric next link must never be followed here.
            route['link'] = ('<BASE/repositories/1/actions/workflows/ci.yml/runs?'
                             'event=schedule&branch=main&status=completed&per_page=1&page=2>; rel="next"')
        return route


class Fleet(Consumer):
    """launch-fleet's check: its REST reads through the installation, GraphQL and search on gh."""

    def setUp(self):
        super().setUp()
        shutil.copytree(ROOT / FLEET, self.tree / FLEET, ignore=shutil.ignore_patterns('fixtures', 'test*'))
        # fleet.sh runs the read.py carried beside it (WZ4, #2634): the recording reader goes there.
        self.reader = self.tree / FLEET / 'carried/read.py'
        self.reader.write_text(WRAPPER.format(read=str(READ)))
        self.configure(FLEET_REPO)
        self.github['mint'] = dict(self.github['mint'], repositories=[{'full_name': FLEET_REPO}])
        self.world = self.root / 'world.json'
        world = json.loads((FLEET_FIX / 'check.json').read_text())
        # A failed nightly run: its runs, its commit comments and the
        # checked-in files all come from REST reads (launch-fleet's own
        # `nightly` case, test.sh).
        world['runs'] = [{'id': 801, 'run_attempt': 1, 'head_sha': '81' * 20, 'head_branch': world['default'],
                          'path': '.github/workflows/ci.yml', 'event': 'schedule', 'status': 'completed',
                          'conclusion': 'failure'}]
        self.world.write_text(json.dumps(world))
        self.proxy_log = self.root / 'proxy.log'
        self.proxy = self.github['routes'] = Proxy(self.world, self.proxy_log)

    def check(self, label, **extra):
        env = self.environment(**{'GH_REPO': FLEET_REPO, 'FLEET_GH': str(FLEET_FIX / 'gh.py'),
                                  'FAKE_GH_WORLD': str(self.world),
                                  'FAKE_GH_LOG': str(self.root / f'fake-gh-{label}.log'), 'LAUNCH_FLEET_NOW': NOW,
                                  'LAUNCH_FLEET_CACHE': str(self.root / f'cache-{label}'),
                                  'LAUNCH_FLEET_REVISION': str(FLEET_FIX / 'revision.sh'), **extra})
        result = subprocess.run(['/bin/sh', str(self.tree / FLEET / 'fleet.sh'), 'check'], capture_output=True,
                                text=True, timeout=600, env=env, cwd=self.root)
        self.outputs.append((result.stdout + result.stderr).encode())
        return result.returncode, result.stdout, result.stderr

    def gh_rest(self):
        return [c for c in self.logged(self.gh_calls) if c[:1] == ['api'] and c[-1] != 'graphql'
                and not any(a.startswith('query=') for a in c)]

    def test_routed_check_prints_what_the_gh_check_prints(self):
        self.disable()
        want = self.check('gh')
        self.assertEqual(want[0], 0, want[2])
        self.assertIn('nightly red 801 attempt 1', want[1])
        gh_rest = {c[-1] for c in self.gh_rest()}
        self.assertTrue(any(e.startswith(f'repos/{FLEET_REPO}/') for e in gh_rest), gh_rest)
        self.assertEqual(self.calls, [])

        self.configure(FLEET_REPO)
        self.gh_calls.unlink()
        got = self.check('installation')
        self.assertEqual(got[:2], want[:2], got[2])
        # Repository REST uses the installation except G7's nightly workflow;
        # its exact gh request preserves the existing HTTP-status outcomes.
        self.assertEqual([c[-1] for c in self.gh_rest() if f'repos/{FLEET_REPO}' in c[-1]],
                         [NIGHTLY_ENDPOINT])
        self.assertTrue(all(c[-1] == NIGHTLY_ENDPOINT or c[-1].startswith('search/issues?')
                            for c in self.gh_rest()), self.gh_rest())
        self.assertEqual([c for c in self.logged(self.gh_calls) if c[:1] == ['repo']], [])
        calls = self.logged(self.reader_calls)
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call[:2], ['rest', FLEET_REPO])
            self.assertTrue(call[2].startswith(f'repos/{FLEET_REPO}'), call)
            self.assertIn('--purpose', call)
            self.assertEqual(call[call.index('--purpose') + 1], 'authority')
            self.assertRegex(call[call.index('--challenge') + 1], r'^[0-9]+$')
        self.assertEqual(len({c[c.index('--challenge') + 1] for c in calls}), 1)
        routed = {c[2] for c in calls}
        self.assertIn(f'repos/{FLEET_REPO}', routed)  # the privacy read, too
        self.assertNotIn(NIGHTLY_ENDPOINT, routed)
        self.assertIn(f'repos/{FLEET_REPO}/commits/{"81" * 20}/comments?per_page=100', routed)
        for call in self.upstream():
            self.assertTrue(call['headers']['Authorization'].startswith('Bearer synthetic-installation-token-'))
        self.assert_reads_only()
        self.assert_no_secret()

    def test_every_page_is_read_and_parsed_as_before(self):
        # One item per page: each list the check reads has later pages.
        self.disable()
        want = self.check('gh-pages', FAKE_GH_PAGE='1')
        self.assertEqual(want[0], 0, want[2])
        self.configure(FLEET_REPO)
        self.gh_calls.unlink()
        self.proxy.page, self.proxy.numeric_links = '1', False
        got = self.check('installation-pages', FAKE_GH_PAGE='1')
        self.assertEqual(got[:2], want[:2], got[2])
        pages = [c['path'] for c in self.upstream() if '&page=' in c['path']]
        self.assertTrue(any(f'/repos/{FLEET_REPO}/issues?state=open&per_page=100&page=' in p for p in pages), pages)
        self.assertEqual([c[-1] for c in self.gh_rest() if f'repos/{FLEET_REPO}' in c[-1]],
                         [NIGHTLY_ENDPOINT])

    def test_numeric_page_links_refuse_rather_than_truncate(self):
        # Gap G3: C8 refuses repositories/<id> links, so a routed list with
        # later pages named that way refuses as a whole.
        self.proxy.page = '1'
        code, out, err = self.check('numeric-pages', FAKE_GH_PAGE='1')
        self.assertEqual((code, out), (2, ''), err)
        self.assertRegex(err, r'fleet\.sh: installation read refused: [a-z-]+\n')
        self.assertEqual([c[-1] for c in self.gh_rest() if f'repos/{FLEET_REPO}' in c[-1]], [])

    def test_refused_privacy_read_stops_without_due_lines_or_gh_fallback(self):
        # R1: every other read is valid; only repository privacy is refused.
        self.route(f'/repos/{FLEET_REPO}', {'message': 'synthetic privacy refusal'}, status=500)
        code, out, err = self.check('privacy-refused')
        self.assertEqual((code, out), (2, ''), err)
        self.assertIn('fleet.sh: installation read refused: incomplete\n', err)
        paths = [call['path'] for call in self.upstream()]
        self.assertIn(f'/repos/{FLEET_REPO}/issues?state=open&per_page=100', paths)
        self.assertIn(f'/repos/{FLEET_REPO}', paths)
        self.assertTrue(all(c[-1].startswith('search/issues?') for c in self.gh_rest()), self.gh_rest())
        self.assertEqual([c for c in self.logged(self.gh_calls) if c[:1] == ['repo']], [])
        self.assert_reads_only()
        self.assert_no_secret()

    def test_absent_nightly_workflow_preserves_due_work_with_installation_on(self):
        # R2: a completed dependency leaves an approval check due. A missing
        # workflow must preserve that line with installation reads enabled.
        world = json.loads(self.world.read_text())
        issue = next(item for item in world['issues'] if item['number'] == 12)
        issue['state'] = 'CLOSED'
        issue['comments'].append({'id': 1202, 'at': '2026-11-01T11:05:00Z',
                                  'body': 'launch-fleet: archived'})
        merged = copy.deepcopy(world['pulls'][0])
        merged.update(number=22, head='22' * 20, headline='#12: green', closes=[12],
                      mergedAt='2026-11-01T11:00:00Z', updatedAt='2026-11-01T11:00:00Z',
                      files=[{'filename': 'src/store/store.rs', 'status': 'modified'}])
        world['pulls'].append(merged)
        self.world.write_text(json.dumps(world))
        endpoint = NIGHTLY_ENDPOINT
        self.route('/' + endpoint, {'message': 'Not Found', 'status': '404'}, status=404)
        self.disable()
        want = self.check('gh-no-nightly', FAKE_GH_NIGHTLY_HTTP='404')
        self.assertEqual(want[:2], (0, 're-approve #10: changed since revision 1 '
                                      '(fingerprint now 2c04c427583d)\n'), want[2])
        self.configure(FLEET_REPO)
        self.gh_calls.unlink()
        got = self.check('installation-no-nightly', FAKE_GH_NIGHTLY_HTTP='404')
        self.assertEqual(got[:2], want[:2], got[2])
        self.assertEqual([call[-1] for call in self.gh_rest()
                          if call[-1].startswith(f'repos/{FLEET_REPO}')], [endpoint])
        self.assertTrue(all(c[-1] == endpoint or c[-1].startswith('search/issues?')
                            for c in self.gh_rest()), self.gh_rest())
        self.assertNotIn(endpoint, [call[2] for call in self.logged(self.reader_calls)])
        self.assert_reads_only()
        self.assert_no_secret()

    def test_refusals_stop_the_check_without_gh_rest(self):
        cases = {'revoked': (lambda: self.github.update(mint_status=404), {}, 'refused: credential'),
                 'helper missing': (lambda: self.reader.unlink(), {}, 'the read helper is missing'),
                 'no explicit repository': (lambda: None, {'GH_REPO': ''}, 'needs GH_REPO=owner/name')}
        for name, (plant, extra, reason) in cases.items():
            with self.subTest(name):
                self.setUp()
                plant()
                code, out, err = self.check(name.replace(' ', '-'), **extra)
                self.assertEqual((code, out), (2, ''), err)
                self.assertIn(reason, err)
                self.assertEqual([c for c in self.gh_rest() if f'repos/{FLEET_REPO}' in c[-1]], [])
                self.assertEqual(self.upstream(), [])


if __name__ == '__main__':
    unittest.main()
