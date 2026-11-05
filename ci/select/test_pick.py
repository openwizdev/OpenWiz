#!/usr/bin/env python3
"""The selector's own tests (#432, K15): every hidden change fails closed.

  python3 -I ci/select/test_pick.py

Synthetic cases on a small map; the research's five broken selectors, each
planted in a copy of pick.py and caught; and, on the committed traced map
(ci/select/map.json), every link in it: each file a test was seen to read,
changed alone, selects that test.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import pick  # noqa: E402

FIX = 'tests/fixtures/room-cli'
UNITS = sorted([
    'rust:test:proof', 'rust:test:web-api', 'rust:test:checks', 'rust:lib:openwiz-core',
    'web:browser:v1-faithful', 'web:unit:api', 'web:unit:brand-new',
])
COMMIT = 'a' * 40
MAP = {
    'schema': pick.MAP_SCHEMA,
    'commit': COMMIT,
    'units': {
        'rust:test:proof': {'files': ['crates/core/src/lib.rs', 'tests/proof/main.rs', f'{FIX}/a/scenario.json'],
                            'dirs': [FIX]},
        'rust:test:web-api': {'files': ['crates/server/src/lib.rs', 'crates/core/src/lib.rs', 'tests/web-api/main.rs',
                                        'tests/fixtures/probe/optional.json'], 'dirs': []},
        'rust:test:checks': {'files': ['tests/checks/main.rs'], 'dirs': ['crates', 'crates/core', 'crates/core/src']},
        'rust:lib:openwiz-core': {'files': ['crates/core/src/lib.rs', 'crates/core/Cargo.toml'], 'dirs': []},
        'web:browser:v1-faithful': {'files': ['apps/web/src/App.tsx', 'apps/web/test/browser/v1-faithful.test.mjs'],
                                    'dirs': ['apps/web/src']},
        'web:unit:api': {'files': ['apps/web/src/api.ts', 'apps/web/test/unit/api.test.ts'], 'dirs': []},
    },
}
# What each file a test reads holds at the head: the selector greps these for a new file's name.
TEXT = {
    'tests/proof/main.rs': b'let p = root.join("p01_coverage");',
    'tests/checks/main.rs': b'walk("crates")',
    'apps/web/test/unit/api.test.ts': b'import "../../src/api.ts"',
}
NOBODY = ('STATUS.md', 'AGENTS.md')
DOCS = [('M', f'private/notes/{i}.md') for i in range(40)] + [('M', 'STATUS.md'), ('A', 'AGENTS.md')]


def read(path):
    if path in TEXT:
        return TEXT[path]
    return b'' if any(path in u['files'] for u in MAP['units'].values()) else None


def nobody(paths):
    return {p for p in paths if p in NOBODY or p.startswith('private/')}


def sel(changes, mp=MAP, units=UNITS):
    return pick.select(changes, mp, units, read, nobody)


M = lambda p: ('M', p)  # noqa: E731
A = lambda p: ('A', p)  # noqa: E731
D = lambda p: ('D', p)  # noqa: E731


def codes(result):
    return [r['code'] for r in result['reasons']]


class Synthetic(unittest.TestCase):
    """Each rule, and each change hidden among 42 paths no job reads."""

    def full(self, result, code):
        self.assertEqual(result['mode'], 'full', result)
        self.assertIn(code, codes(result), result)
        self.assertEqual(result['tests'], UNITS)
        self.assertEqual(result['skipped'], [])

    def picked(self, result, has=(), lacks=()):
        self.assertEqual(result['mode'], 'selected', result)
        for u in has:
            self.assertIn(u, result['tests'], result)
        for u in lacks:
            self.assertIn(u, [s['test'] for s in result['skipped']], result)
        self.assertEqual(sorted(result['tests'] + [s['test'] for s in result['skipped']]), UNITS)
        self.assertTrue(all(s['reason'] for s in result['skipped']))

    # The map itself.
    def test_no_map_runs_everything(self):
        self.full(sel([M('apps/web/src/api.ts')], mp=None), 'selector_error')

    def test_a_map_of_another_schema_runs_everything(self):
        self.full(sel([M('apps/web/src/api.ts')], mp=dict(MAP, schema='other')), 'selector_error')

    def test_a_map_without_units_runs_everything(self):
        self.full(sel([M('apps/web/src/api.ts')], mp=dict(MAP, units={})), 'selector_error')

    def test_a_unit_without_files_runs_everything(self):
        bad = dict(MAP, units=dict(MAP['units'], **{'web:unit:api': {'dirs': []}}))
        self.full(sel([M('apps/web/src/api.ts')], mp=bad), 'selector_error')

    def test_a_map_with_an_extra_key_runs_everything(self):
        self.full(sel([M('apps/web/src/api.ts')], mp=dict(MAP, extra=1)), 'selector_error')

    def test_a_map_with_a_path_outside_the_repository_runs_everything(self):
        bad = dict(MAP, units=dict(MAP['units'], **{'web:unit:api': {'files': ['../x'], 'dirs': []}}))
        self.full(sel([M('apps/web/src/api.ts')], mp=bad), 'selector_error')

    def test_a_map_commit_that_is_not_a_commit_runs_everything(self):
        self.full(sel([M('apps/web/src/api.ts')], mp=dict(MAP, commit='HEAD')), 'selector_error')

    def test_no_units_runs_everything(self):
        result = pick.select([M('apps/web/src/api.ts')], MAP, [], read, nobody)
        self.assertEqual(result['mode'], 'full')
        self.assertIn('selector_error', codes(result))

    # The diff.
    def test_an_empty_diff_runs_everything(self):
        self.full(sel([]), 'empty_diff')

    def test_only_paths_no_job_reads_runs_just_the_always_run_set(self):
        result = sel(DOCS)
        self.picked(result, has=pick.ALWAYS, lacks=['rust:test:proof', 'web:browser:v1-faithful'])

    def test_ci_and_toolchain_paths_hidden_in_docs_run_everything(self):
        for p in ['.github/workflows/ci.yml', '.github/actions/docs-only/classify.sh', 'ci/select/pick.py',
                  'ci/select/map.json', 'ci/runner/cache.sh', 'ci/runner/Dockerfile', 'ci/rust-tests.sh',
                  'Cargo.toml', 'Cargo.lock', 'apps/web/package-lock.json', 'apps/site/package-lock.json',
                  'rust-toolchain.toml', '.nvmrc']:
            with self.subTest(p):
                result = sel(DOCS[:20] + [M(p)] + DOCS[20:])
                self.full(result, 'ci_change')
                self.assertEqual([r['paths'] for r in result['reasons'] if r['code'] == 'ci_change'], [[p]])

    def test_lockfiles_and_manifests_no_job_reads_are_not_ci_changes(self):
        for p in ['private/evidence/x/package-lock.json', 'private/evidence/x/Cargo.toml',
                  'private/evidence/x/Cargo.lock', 'private/evidence/x/.github/workflows/ci.yml']:
            with self.subTest(p):
                self.picked(sel(DOCS + [A(p)]), has=pick.ALWAYS, lacks=['rust:test:proof'])

    def test_a_path_with_a_control_character_runs_everything(self):
        self.full(sel([M('apps/web/src/a\nb.ts')]), 'unknown_path')

    def test_an_odd_status_counts_as_new(self):
        self.full(sel([('T', 'docs/q/p01_coverage')]), 'unknown_path')
        self.full(sel([('X', 'docs/never/seen.md')]), 'unknown_path')

    # Modified paths.
    def test_a_modified_file_selects_its_readers_only(self):
        self.picked(sel([M('crates/core/src/lib.rs')]),
                    has=['rust:test:proof', 'rust:test:web-api', 'rust:lib:openwiz-core'],
                    lacks=['web:unit:api', 'web:browser:v1-faithful'])

    def test_a_fixture_read_only_at_run_time_hidden_in_docs_selects_its_reader(self):
        self.picked(sel(DOCS + [M(f'{FIX}/a/scenario.json')]), has=['rust:test:proof'],
                    lacks=['rust:test:web-api', 'web:browser:v1-faithful'])

    def test_a_web_source_selects_its_readers_only(self):
        self.picked(sel([M('apps/web/src/api.ts')]), has=['web:unit:api'],
                    lacks=['rust:test:proof', 'web:browser:v1-faithful'])

    def test_a_traced_file_no_test_touched_selects_nothing_more(self):
        self.picked(sel([M('docs/adr/0001.md')]), has=pick.ALWAYS, lacks=['rust:test:proof', 'web:unit:api'])

    # New paths.
    def test_a_new_file_a_test_names_runs_everything(self):
        result = sel(DOCS[:20] + [A('docs/zzz/p01_coverage')] + DOCS[20:])
        self.full(result, 'unknown_path')
        self.assertEqual([r['paths'] for r in result['reasons']], [['docs/zzz/p01_coverage']])

    def test_a_new_file_a_test_names_runs_everything_even_under_a_listed_folder(self):
        self.full(sel([A(f'{FIX}/z/p01_coverage')]), 'unknown_path')

    def test_a_new_file_the_map_does_not_know_runs_everything(self):
        self.full(sel(DOCS[:20] + [A('docs/grills/brand-new.md')] + DOCS[20:]), 'unknown_path')

    def test_a_new_file_under_a_listed_folder_selects_the_lister(self):
        self.picked(sel(DOCS[:20] + [A('crates/core/src/brand_new.rs')] + DOCS[20:]), has=['rust:test:checks'],
                    lacks=['rust:test:proof'])

    def test_a_new_path_with_a_space_under_a_listed_folder_selects_the_lister(self):
        self.picked(sel([A(f'{FIX}/a b.json')]), has=['rust:test:proof'], lacks=['rust:test:web-api'])

    def test_a_new_web_source_selects_whatever_lists_its_folder(self):
        self.picked(sel([A('apps/web/src/new.ts')]), has=['web:browser:v1-faithful'],
                    lacks=['rust:test:proof', 'web:unit:api'])

    def test_a_new_file_a_test_probed_for_selects_the_prober(self):
        self.picked(sel([A('tests/fixtures/probe/optional.json')]), has=['rust:test:web-api'],
                    lacks=['rust:test:proof'])

    def test_a_path_that_is_a_prefix_of_a_mapped_one_is_another_file(self):
        self.full(sel([A('tests/proof/mai')]), 'unknown_path')

    # Deleted paths.
    def test_a_deleted_fixture_selects_its_reader_and_the_lister(self):
        self.picked(sel([D(f'{FIX}/a/scenario.json')]), has=['rust:test:proof'], lacks=['rust:test:web-api'])

    def test_a_deleted_file_nobody_read_listed_or_named_selects_nothing_more(self):
        self.picked(sel([D('docs/adr/0001.md')]), lacks=['rust:test:proof', 'web:unit:api'])

    def test_a_deleted_file_nobody_read_or_listed_but_a_test_names_runs_everything(self):
        self.full(sel([D('docs/old/p01_coverage')]), 'unknown_path')

    # Units.
    def test_a_test_the_map_has_never_seen_always_runs(self):
        self.picked(sel([M('apps/web/src/api.ts')]), has=['web:unit:brand-new'])

    def test_the_always_run_set_always_runs(self):
        self.picked(sel([M('apps/web/src/api.ts')]), has=pick.ALWAYS)

    def test_a_mapped_test_no_longer_in_the_tree_is_not_run(self):
        result = pick.select([M('crates/core/src/lib.rs')], MAP, [u for u in UNITS if u != 'rust:test:proof'], read,
                             nobody)
        self.assertNotIn('rust:test:proof', result['tests'])

    def test_every_run_test_says_why(self):
        result = sel([M('crates/core/src/lib.rs')])
        self.assertEqual(sorted(result['why']), result['tests'])
        self.assertEqual(result['why']['rust:test:proof'], 'reads crates/core/src/lib.rs')
        self.assertEqual(result['why']['web:unit:brand-new'], 'not in the map yet')

    def test_a_read_that_fails_runs_everything(self):
        def broken(path):
            raise OSError('unreadable')
        result = pick.select([A('crates/core/src/x.rs')], MAP, UNITS, broken, nobody)
        self.assertEqual(result['mode'], 'full')
        self.assertIn('selector_error', codes(result))

    def test_a_classifier_that_fails_runs_everything(self):
        def broken(paths):
            raise RuntimeError('classify failed')
        result = pick.select([M('crates/core/src/lib.rs')], MAP, UNITS, read, broken)
        self.assertEqual(result['mode'], 'full')
        self.assertIn('selector_error', codes(result))


# The research's five broken selectors (research/ci-test-selection,
# raw/red-runs.txt), planted in pick.py: each must make a synthetic case fail.
BROKEN = {
    'a named new path not run in full': ('            if named(path):', '            if False:'),
    'the CI rule off': ('if CI_CHANGE.fullmatch(path):', 'if False:'),
    'an empty diff not full': ("return full('empty_diff')", 'pass'),
    'new tests dropped': ('picked |= {u for u in units if u not in known}', 'pass'),
    'a read file not selecting its reader': ('picked |= owners.get(path, set())', 'pass'),
}


class Broken(unittest.TestCase):
    def test_each_broken_selector_is_caught(self):
        source = (HERE / 'pick.py').read_text()
        for name, (old, new) in BROKEN.items():
            with self.subTest(name):
                self.assertEqual(source.count(old), 1, f'{old!r} must be in pick.py exactly once')
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / 'pick.py'
                    path.write_text(source.replace(old, new))
                    spec = importlib.util.spec_from_file_location('broken_pick', path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    suite = unittest.TestSuite()
                    for case in unittest.defaultTestLoader.getTestCaseNames(Synthetic):
                        test = Synthetic(case)
                        test.module = module
                        suite.addTest(test)
                    global pick
                    real, pick = pick, module
                    try:
                        with open(os.devnull, 'w') as devnull:
                            outcome = unittest.TextTestRunner(stream=devnull, verbosity=0).run(suite)
                    finally:
                        pick = real
                    self.assertFalse(outcome.wasSuccessful(), f'broken selector not caught: {name}')


class RealMap(unittest.TestCase):
    """Every link in the committed map selects its test."""

    def test_every_link_in_the_map_selects_its_test(self):
        mp = json.loads((HERE / 'map.json').read_text())
        units = sorted(mp['units'])
        owners = {}
        for uid, u in mp['units'].items():
            for f in u['files']:
                owners.setdefault(f, set()).add(uid)
        self.assertGreater(len(owners), 100)
        pairs = missed = 0
        for path, readers in sorted(owners.items()):
            result = pick.select([('M', path)], mp, units, lambda p: b'', lambda ps: set())
            for uid in readers:
                pairs += 1
                if uid not in result['tests']:
                    missed += 1
        print(f'real map: {pairs} (test, file) links, {missed} hidden', file=sys.stderr)
        self.assertEqual(missed, 0)


class Lanes(unittest.TestCase):
    """What each CI job is told to run."""

    def test_a_full_run_tells_every_lane_all(self):
        self.assertEqual(pick.lanes(sel([])), {'rust': 'all', 'web': 'all'})

    def test_a_selected_run_names_each_lane_s_tests(self):
        self.assertEqual(pick.lanes(sel([M('crates/core/src/lib.rs')])),
                         {'rust': 'rust:lib:openwiz-core rust:test:checks rust:test:proof rust:test:web-api',
                          'web': 'web:unit:brand-new'})

    def test_a_lane_with_nothing_selected_is_none(self):
        mp = dict(MAP, units=dict(MAP['units'], **{'web:unit:brand-new': {'files': ['x.ts'], 'dirs': []}}))
        self.assertEqual(pick.lanes(sel([M('crates/server/src/lib.rs')], mp=mp)),
                         {'rust': 'rust:test:checks rust:test:web-api', 'web': 'none'})

    def test_an_answer_that_is_not_a_plain_selection_is_all(self):
        good = sel([M('crates/core/src/lib.rs')])
        for bad in ({}, dict(good, mode='other'), dict(good, tests='rust:test:checks'),
                    dict(good, tests=['rust:test:checks', 'rust:test:checks x'])):
            with self.subTest(bad=str(bad)[:60]):
                self.assertEqual(pick.lanes(bad), {'rust': 'all', 'web': 'all'})


class Command(unittest.TestCase):
    """The command reads a real git diff, and fails closed."""

    def git(self, root, *args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout

    def repo(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ['rm', '-rf', str(tmp)])
        self.git(tmp, 'init', '-q')
        self.git(tmp, 'config', 'user.email', 't@example.invalid')
        self.git(tmp, 'config', 'user.name', 't')
        (tmp / 'tests/proof').mkdir(parents=True)
        (tmp / 'tests/proof/main.rs').write_text('fn main() {}\n')
        (tmp / 'docs').mkdir()
        (tmp / 'docs/a.md').write_text('a\n')
        self.git(tmp, 'add', '-A')
        self.git(tmp, 'commit', '-qm', 'traced')
        traced = self.git(tmp, 'rev-parse', 'HEAD').strip()
        mp = {'schema': pick.MAP_SCHEMA, 'commit': traced,
              'units': {'rust:test:proof': {'files': ['tests/proof/main.rs'], 'dirs': []}}}
        (tmp / 'map.json').write_text(json.dumps(mp))
        return tmp, traced

    def run_pick(self, root, units='rust:test:proof\nrust:test:checks\n'):
        (root / 'units.txt').write_text(units)
        out = subprocess.run([sys.executable, '-I', str(HERE / 'pick.py'), '--map', str(root / 'map.json'),
                              '--units-file', str(root / 'units.txt'), '--root', str(root), '--no-classify'],
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout)

    def test_a_change_since_the_traced_commit_selects_its_reader(self):
        root, _ = self.repo()
        (root / 'tests/proof/main.rs').write_text('fn main() { }\n')
        self.git(root, 'commit', '-qam', 'change')
        result = self.run_pick(root)
        self.assertEqual(result['mode'], 'selected')
        self.assertEqual(result['tests'], ['rust:test:checks', 'rust:test:proof'])

    def test_a_traced_file_no_test_read_selects_only_the_always_run_set(self):
        root, _ = self.repo()
        (root / 'docs/a.md').write_text('b\n')
        self.git(root, 'commit', '-qam', 'docs')
        result = self.run_pick(root)
        self.assertEqual(result['tests'], ['rust:test:checks'])
        self.assertEqual(result['skipped'], [{'test': 'rust:test:proof', 'reason': 'no changed path reaches it'}])

    def test_the_head_being_the_traced_commit_runs_everything(self):
        root, _ = self.repo()
        self.full_with(self.run_pick(root), 'empty_diff')

    def test_a_traced_commit_not_in_the_clone_runs_everything(self):
        root, _ = self.repo()
        mp = json.loads((root / 'map.json').read_text())
        mp['commit'] = 'b' * 40
        (root / 'map.json').write_text(json.dumps(mp))
        self.full_with(self.run_pick(root), 'failed_diff')

    def test_a_missing_map_file_runs_everything(self):
        root, _ = self.repo()
        (root / 'map.json').unlink()
        self.full_with(self.run_pick(root), 'selector_error')

    def test_a_map_with_a_repeated_key_runs_everything(self):
        root, traced = self.repo()
        (root / 'map.json').write_text('{"schema": "%s", "commit": "%s", "commit": "%s", "units": {}}'
                                       % (pick.MAP_SCHEMA, traced, traced))
        self.full_with(self.run_pick(root), 'selector_error')

    def test_the_github_output_names_each_lane(self):
        root, _ = self.repo()
        (root / 'tests/proof/main.rs').write_text('fn main() { }\n')
        self.git(root, 'commit', '-qam', 'change')
        (root / 'units.txt').write_text('rust:test:proof\nrust:test:checks\nweb:unit:api\n')
        mp = json.loads((root / 'map.json').read_text())
        mp['units']['web:unit:api'] = {'files': ['apps/web/src/api.ts'], 'dirs': []}
        (root / 'map.json').write_text(json.dumps(mp))
        out = root / 'github-output'
        run = subprocess.run([sys.executable, '-I', str(HERE / 'pick.py'), '--map', str(root / 'map.json'),
                              '--units-file', str(root / 'units.txt'), '--root', str(root), '--no-classify',
                              '--github-output', str(out)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(out.read_text(), 'selection=selected\nrust-tests=rust:test:checks rust:test:proof\n'
                                          'web-tests=none\n')

    def full_with(self, result, code):
        self.assertEqual(result['mode'], 'full', result)
        self.assertIn(code, codes(result))
        self.assertEqual(result['tests'], ['rust:test:checks', 'rust:test:proof'])


if __name__ == '__main__':
    unittest.main()
