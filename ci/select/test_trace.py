#!/usr/bin/env python3
"""The tracer's and the map builder's own tests (#432, K15), on synthetic
strace lines and a synthetic repository; no test runs under strace here.

  python3 -I ci/select/test_trace.py
"""
import importlib
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import map as map_mod  # noqa: E402
import pick  # noqa: E402
import resolve  # noqa: E402
import trace  # noqa: E402

R = '/w/repo'


def parse(text, cwd=R):
    return trace.parse(text.strip('\n').splitlines(), cwd)


class Parse(unittest.TestCase):
    def test_opens_stats_and_probes_that_found_nothing_all_count(self):
        touched, _ = parse(f'''
10 openat(AT_FDCWD<{R}>, "crates/core/src/lib.rs", O_RDONLY|O_CLOEXEC) = 3<{R}/crates/core/src/lib.rs>
10 newfstatat(AT_FDCWD<{R}>, "tests/fixtures/maybe.json", 0x7ffd, 0) = -1 ENOENT (No such file or directory)
10 statx(AT_FDCWD<{R}/apps/web>, "test/support/x.ts", AT_STATX_SYNC_AS_STAT, STATX_ALL, 0x1) = 0
10 access("{R}/skills/a/SKILL.md", R_OK) = 0
''')
        self.assertEqual(touched, {f'{R}/crates/core/src/lib.rs', f'{R}/tests/fixtures/maybe.json',
                                   f'{R}/apps/web/test/support/x.ts', f'{R}/skills/a/SKILL.md'})

    def test_relative_paths_follow_each_process_s_folder(self):
        touched, _ = parse(f'''
10 chdir("apps/web") = 0
10 clone(child_stack=NULL, flags=CLONE_CHILD_CLEARTID|SIGCHLD) = 11
11 open("src/App.tsx", O_RDONLY) = 3<{R}/apps/web/src/App.tsx>
10 open("../../docs/x.md", O_RDONLY) = -1 ENOENT (No such file or directory)
11 fchdir(4<{R}/tests>) = 0
11 stat("fixtures/a.json", 0x1) = 0
''')
        self.assertEqual(touched, {f'{R}/apps/web/src/App.tsx', f'{R}/docs/x.md', f'{R}/apps/web',
                                   f'{R}/tests/fixtures/a.json'})

    def test_a_call_split_across_two_lines_is_read_whole(self):
        touched, _ = parse(f'''
10 openat(AT_FDCWD<{R}>, "crates/a.rs", O_RDONLY <unfinished ...>
11 openat(AT_FDCWD<{R}>, "crates/b.rs", O_RDONLY) = 3<{R}/crates/b.rs>
10 <... openat resumed>) = 4<{R}/crates/a.rs>
''')
        self.assertEqual(touched, {f'{R}/crates/a.rs', f'{R}/crates/b.rs'})

    def test_the_fd_s_own_path_is_kept_too_through_a_symlink(self):
        touched, _ = parse(f'''
10 execve("/tmp/x/room-cli", ["room-cli"], 0x1 /* 3 vars */) = 0
10 openat(AT_FDCWD</tmp/x>, "/tmp/x/fake", O_RDONLY) = 3<{R}/target/debug/fake-room-cli>
''')
        self.assertIn(f'{R}/target/debug/fake-room-cli', touched)

    def test_cargo_s_own_reads_are_left_out_but_the_programs_it_runs_are_not(self):
        touched, _ = parse(f'''
10 execve("/home/synthetic/.cargo/bin/cargo", ["cargo", "test"], 0x1 /* 3 vars */) = 0
10 newfstatat(AT_FDCWD<{R}>, "crates/store/src/lib.rs", 0x1, 0) = 0
10 openat(AT_FDCWD<{R}>, "target/debug/.fingerprint/x", O_RDONLY) = 3<{R}/target/debug/.fingerprint/x>
10 clone3({{flags=CLONE_VM, exit_signal=SIGCHLD}}, 88) = 12
12 openat(AT_FDCWD<{R}>, "crates/store/Cargo.toml", O_RDONLY) = 3<{R}/crates/store/Cargo.toml>
12 execve("{R}/target/debug/deps/proof-0123456789abcdef", ["proof"], 0x1 /* 3 vars */) = 0
12 openat(AT_FDCWD<{R}/tests>, "fixtures/a.json", O_RDONLY) = 3<{R}/tests/fixtures/a.json>
''')
        self.assertEqual(touched, {f'{R}/target/debug/deps/proof-0123456789abcdef', f'{R}/tests/fixtures/a.json'})

    def test_listings_are_the_folders_read_with_getdents(self):
        _, listed = parse(f'''
10 openat(AT_FDCWD<{R}>, "tests/fixtures", O_RDONLY|O_DIRECTORY|O_CLOEXEC) = 3<{R}/tests/fixtures>
10 getdents64(3<{R}/tests/fixtures>, 0x55 /* 4 entries */, 32768) = 112
10 openat(AT_FDCWD<{R}>, "crates", O_RDONLY|O_DIRECTORY|O_PATH) = 4<{R}/crates>
''')
        self.assertEqual(listed, {f'{R}/tests/fixtures'})

    def test_escaped_paths_come_back_whole(self):
        touched, _ = parse(f'''
10 openat(AT_FDCWD<{R}>, "tests/a b\\"q\\\\\\n\\303\\251.json", O_RDONLY) = -1 ENOENT (No such file or directory)
''')
        self.assertEqual(touched, {f'{R}/tests/a b"q\\\né.json'})

    def test_an_empty_path_is_the_open_file_itself(self):
        touched, _ = parse(f'''
10 newfstatat(3<{R}/a.rs>, "", {{st_mode=S_IFREG}}, AT_EMPTY_PATH) = 0
''')
        self.assertEqual(touched, set())


class Repo(unittest.TestCase):
    """A synthetic repository with a target/ and dep-info, and a cargo
    metadata answer given directly."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        files = {
            'crates/core/Cargo.toml': '', 'crates/core/src/lib.rs': '',
            'crates/store/Cargo.toml': '', 'crates/store/src/lib.rs': '',
            'crates/server/Cargo.toml': '', 'crates/server/src/main.rs': '', 'crates/server/src/web.rs': '',
            'tests/Cargo.toml': '', 'tests/proof/main.rs': 'use openwiz_core::x; mod support;',
            'tests/proof/support.rs': 'fn f() { openwiz_server::y(); }',
            'apps/web/out/index.html': '', 'apps/web/node_modules/react/index.js': '', 'apps/web/package.json': '',
            'target/debug/deps/proof-0123456789abcdef': '',
            'target/debug/deps/proof-0123456789abcdef.d':
                f'{self.root}/target/debug/deps/proof-0123456789abcdef: tests/proof/main.rs tests/proof/support.rs\n',
            'target/debug/deps/openwiz_core-1111111111111111.d':
                f'{self.root}/target/debug/deps/libopenwiz_core-1111111111111111.rlib: crates/core/src/lib.rs\n',
            'target/debug/deps/openwiz_store-2222222222222222.d':
                f'{self.root}/target/debug/deps/libopenwiz_store-2222222222222222.rlib: crates/store/src/lib.rs\n',
            'target/debug/deps/openwiz_server-3333333333333333.d':
                f'{self.root}/target/debug/deps/libopenwiz_server-3333333333333333.rlib: '
                f'{self.root}/crates/server/src/main.rs {self.root}/crates/server/src/web.rs\n',
            'target/debug/openwiz-server': '',
            'target/debug/openwiz-server.d':
                f'{self.root}/target/debug/openwiz-server: {self.root}/crates/server/src/main.rs '
                f'{self.root}/crates/server/src/web.rs {self.root}/crates/core/src/lib.rs\n',
            'target/debug/examples/openwiz-server': '',
            'target/debug/examples/openwiz-server.d':
                f'{self.root}/target/debug/examples/openwiz-server: {self.root}/tests/fixture-entrypoints/server.rs '
                f'{self.root}/crates/server/src/web.rs {self.root}/crates/core/src/lib.rs\n',
            'crates/server/build.rs': '',
            'target/debug/mystery': '',
            'target/tmp/scratch.txt': '',
        }
        for rel, text in files.items():
            os.makedirs(os.path.dirname(os.path.join(self.root, rel)), exist_ok=True)
            with open(os.path.join(self.root, rel), 'w') as f:
                f.write(text)
        self.r = resolve.Resolver(self.root)
        self.r._meta = resolve.index(self.metadata(), os.path.realpath(self.root))

    def metadata(self, extra=()):
        """A `cargo metadata --no-deps` answer with this tree's collision
        (#1579 R5): the server's library and an openwiz-tests example are both
        `openwiz-server`, so both are the crate name `openwiz_server`."""
        real = os.path.realpath(self.root)

        def pkg(name, folder, targets, deps=()):
            return {'name': name, 'manifest_path': f'{real}/{folder}/Cargo.toml',
                    'dependencies': [{'name': d, 'path': f'{real}/x'} for d in deps] + [{'name': 'serde'}],
                    'targets': [{'name': n, 'kind': k} for n, k in targets]}
        return {'packages': [
            pkg('openwiz-core', 'crates/core', [('openwiz_core', ['lib'])]),
            pkg('openwiz-store', 'crates/store', [('openwiz_store', ['lib'])], ['openwiz-core']),
            pkg('openwiz-server', 'crates/server', [('openwiz_server', ['lib']), ('openwiz-server', ['bin'])],
                ['openwiz-core']),
            pkg('openwiz-tests', 'tests', [('proof', ['test']), ('openwiz-server', ['example']),
                                           ('fake-room-cli', ['bin'])],
                ['openwiz-core', 'openwiz-store', 'openwiz-server']),
            *extra]}

    def at(self, *rels):
        return {os.path.join(self.root, r) for r in rels}

    def test_a_test_binary_becomes_its_sources_and_the_crates_they_name(self):
        files, dirs, why = self.r.resolve(self.at('target/debug/deps/proof-0123456789abcdef'), set())
        self.assertIsNone(why)
        self.assertEqual(files, ['crates/core/Cargo.toml', 'crates/core/src/lib.rs', 'crates/server/Cargo.toml',
                                 'crates/server/build.rs', 'crates/server/src/main.rs', 'crates/server/src/web.rs',
                                 'tests/Cargo.toml', 'tests/proof/main.rs', 'tests/proof/support.rs'])

    def test_a_program_a_test_ran_becomes_its_uplifted_dep_info(self):
        files, _, why = self.r.resolve(self.at('target/debug/openwiz-server'), set())
        self.assertIsNone(why)
        self.assertEqual(files, ['crates/core/Cargo.toml', 'crates/core/src/lib.rs', 'crates/server/Cargo.toml',
                                 'crates/server/build.rs', 'crates/server/src/main.rs', 'crates/server/src/web.rs'])

    def test_a_test_naming_a_crate_whose_name_an_example_shares_keeps_that_crate(self):
        files, _, why = self.r.resolve(self.at('target/debug/deps/proof-0123456789abcdef'), set())
        self.assertIsNone(why)
        self.assertIn('crates/server/src/web.rs', files)
        self.assertIn('crates/server/Cargo.toml', files)

    def test_an_uplifted_program_adds_its_package_s_manifests_and_build_scripts(self):
        files, _, why = self.r.resolve(self.at('target/debug/examples/openwiz-server'), set())
        self.assertIsNone(why)
        for f in ('crates/server/Cargo.toml', 'crates/server/build.rs', 'crates/core/Cargo.toml', 'tests/Cargo.toml',
                  'crates/server/src/web.rs', 'tests/fixture-entrypoints/server.rs'):
            self.assertIn(f, files)

    def test_a_crate_manifest_change_selects_the_browser_proof_running_that_program(self):
        files, dirs, why = self.r.resolve(self.at('target/debug/examples/openwiz-server'), set())
        mp = {'schema': pick.MAP_SCHEMA, 'commit': 'c' * 40,
              'units': {'web:browser:v1-faithful': {'files': files, 'dirs': dirs}}}
        result = pick.select([('M', 'crates/server/Cargo.toml')], mp, ['web:browser:v1-faithful'],
                             lambda p: b'', lambda ps: set())
        self.assertEqual(result['tests'], ['web:browser:v1-faithful'])

    def test_a_program_or_crate_name_two_packages_share_leaves_the_test_out(self):
        twin = {'name': 'openwiz-twin', 'manifest_path': f'{os.path.realpath(self.root)}/crates/twin/Cargo.toml',
                'dependencies': [], 'targets': [{'name': 'openwiz-server', 'kind': ['bin']},
                                                {'name': 'openwiz_core', 'kind': ['lib']}]}
        r = resolve.Resolver(self.root)
        r._meta = resolve.index(self.metadata([twin]), os.path.realpath(self.root))
        self.assertIsNotNone(r.resolve(self.at('target/debug/openwiz-server'), set())[2])
        self.assertIsNotNone(r.resolve(self.at('target/debug/deps/proof-0123456789abcdef'), set())[2])

    def test_cargo_s_bookkeeping_and_scratch_are_not_inputs(self):
        files, _, why = self.r.resolve(self.at('target/tmp/scratch.txt', 'target/debug/deps/proof-0123456789abcdef.d',
                                               'target/debug/.fingerprint/x', 'target/debug/build/x/out/y'), set())
        self.assertIsNone(why)
        self.assertEqual(files, [])

    def test_a_build_product_it_can_t_trace_leaves_the_test_out(self):
        files, dirs, why = self.r.resolve(self.at('target/debug/mystery', 'crates/core/src/lib.rs'), set())
        self.assertEqual((files, dirs), ([], []))
        self.assertIn('target/debug/mystery', why)

    def test_git_s_index_or_objects_leave_the_test_out(self):
        for rel in ('.git/index', '.git/objects/pack/p.pack'):
            with self.subTest(rel):
                self.assertIsNotNone(self.r.resolve({f'{self.root}/{rel}'}, set())[2])
        self.assertIsNone(self.r.resolve({f'{self.root}/.git/HEAD', f'{self.root}/.git/refs/heads/main'}, set())[2])

    def test_the_export_node_modules_and_missing_files(self):
        files, dirs, why = self.r.resolve(
            self.at('apps/web/out/index.html', 'apps/web/node_modules/react/index.js', 'docs/missing.md',
                    'crates/core'),
            self.at('apps/web/out', 'tests/fixtures', 'apps/web/node_modules/react', 'target/debug', '.'))
        self.assertIsNone(why)
        self.assertEqual(files, [resolve.EXPORT, 'apps/web/package-lock.json', 'apps/web/package.json',
                                 'docs/missing.md'])
        self.assertEqual(dirs, ['.', 'tests/fixtures'])

    def test_the_export_through_the_folder_it_is_mounted_from(self):
        mount = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, mount)
        shutil.rmtree(os.path.join(self.root, 'apps/web/out'))
        os.symlink(mount, os.path.join(self.root, 'apps/web/out'))
        r = resolve.Resolver(self.root)
        files, _, why = r.resolve({os.path.join(mount, 'index.html')}, set())
        self.assertEqual(files, [resolve.EXPORT])

    def test_the_export_s_inputs_leave_out_tests_and_build_output(self):
        files, dirs = self.r.export_inputs(
            self.at('apps/web/package.json', 'apps/web/src/App.tsx', 'apps/web/test/unit/a.test.ts',
                    'apps/web/node_modules/next/x.js', 'apps/web/.next/cache/y', 'apps/web/out/z.html'),
            self.at('apps/web/src', 'apps/web/test/unit', 'apps/web/node_modules/next'))
        self.assertEqual(files, ['apps/web/package-lock.json', 'apps/web/package.json', 'apps/web/src/App.tsx'])
        self.assertEqual(dirs, ['apps/web/src'])


class Map(unittest.TestCase):
    LISTED = {'rust:test:proof', 'web:browser:v1', 'web:unit:api'}
    EXPORT = {'files': ['apps/web/src/App.tsx'], 'dirs': ['apps/web/src']}

    def records(self):
        return {
            'rust:test:proof': {'files': ['tests/proof/main.rs'], 'dirs': [], 'seconds': 2.0, 'exit': 0, 'traced': True},
            'web:browser:v1': {'files': [resolve.EXPORT, 'apps/web/test/browser/v1.test.mjs'], 'dirs': [],
                               'seconds': 9.0, 'exit': 0, 'traced': True},
            'web:unit:api': {'files': [], 'dirs': [], 'seconds': 1.0, 'exit': 0, 'traced': False,
                             'untraced': 'failed under strace'},
        }

    def test_the_export_is_replaced_by_its_inputs_and_untraced_tests_are_left_out(self):
        mp, left = map_mod.build(self.records(), self.EXPORT, 'c' * 40, self.LISTED)
        self.assertEqual(mp['schema'], pick.MAP_SCHEMA)
        self.assertEqual(mp['units']['web:browser:v1'],
                         {'files': ['apps/web/src/App.tsx', 'apps/web/test/browser/v1.test.mjs'],
                          'dirs': ['apps/web/src'], 'seconds': 9.0, 'web_export': True})
        self.assertNotIn('web:unit:api', mp['units'])
        self.assertEqual(left, {'web:unit:api': 'failed under strace'})

    def test_k16_map_keeps_which_tests_need_the_export(self):
        mp, _ = map_mod.build(self.records(), self.EXPORT, 'c' * 40, self.LISTED)
        self.assertIs(mp['units']['web:browser:v1']['web_export'], True)
        self.assertIs(mp['units']['rust:test:proof']['web_export'], False)

    def test_a_test_without_a_record_refuses_the_map(self):
        recs = self.records()
        del recs['rust:test:proof']
        with self.assertRaises(SystemExit):
            map_mod.build(recs, self.EXPORT, 'c' * 40, self.LISTED)

    def test_a_record_for_a_test_not_here_refuses_the_map(self):
        with self.assertRaises(SystemExit):
            map_mod.build(self.records(), self.EXPORT, 'c' * 40, self.LISTED - {'web:unit:api'})

    def test_the_export_needed_and_missing_refuses_the_map(self):
        with self.assertRaises(SystemExit):
            map_mod.build(self.records(), None, 'c' * 40, self.LISTED)

    def test_the_selector_reads_the_map_it_builds(self):
        mp, _ = map_mod.build(self.records(), self.EXPORT, 'c' * 40, self.LISTED)
        result = pick.select([('M', 'apps/web/src/App.tsx')], json.loads(json.dumps(mp)), sorted(self.LISTED),
                             lambda p: b'', lambda ps: set())
        self.assertEqual(result['tests'], ['web:browser:v1', 'web:unit:api'])


class TraceLane(unittest.TestCase):
    """The web lane's own full-run rules, on the real trace_lane() with the
    test runs stubbed (self-review on #1579): the attempt that decides is the
    one checked, and a full run owes the soak, run and not skipped."""

    SOAK_OK = 'ok soak\n\u2714 soak: 2 simulated hours, then failures, then a hidden hour (49.2ms)\n\u2139 skipped 0\n'
    PLAIN_OK = '\u2714 a proof (1ms)\n\u2139 skipped 0\n'

    def lane(self, logs, only=None, units=('web:unit:x', 'web:browser:v7-soak')):
        """logs: {test: (traced exit, traced log, plain exit or None, plain log)}."""
        out = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, out)
        saved = (trace.commands, trace.strace_run, trace.plain_run, trace.subprocess.run, resolve.Resolver.resolve)

        def strace_run(argv, cwd, env, log):
            uid = argv[0]
            with open(log, 'a') as f:
                f.write(logs[uid][1])
            return logs[uid][0], set(), set(), 0.1

        def plain_run(argv, cwd, env, log):
            uid = argv[0]
            with open(log, 'a') as f:
                f.write(logs[uid][3])
            return logs[uid][2], 0.1

        trace.commands = lambda lane, root, threads: {u: ([u], root) for u in units}
        trace.strace_run, trace.plain_run = strace_run, plain_run
        trace.subprocess.run = lambda *a, **k: subprocess_ok()
        resolve.Resolver.resolve = lambda self, t, l: (['apps/web/x.ts'], [], None)
        try:
            with open(os.devnull, 'w') as devnull:
                real, sys.stdout = sys.stdout, devnull
                try:
                    return trace.trace_lane('web', out, 2, 8, os.getcwd(), only)
                finally:
                    sys.stdout = real
        finally:
            trace.commands, trace.strace_run, trace.plain_run, trace.subprocess.run, resolve.Resolver.resolve = saved

    def test_a_full_web_run_with_the_soak_run_passes(self):
        self.assertEqual(self.lane({'web:unit:x': (0, self.PLAIN_OK, None, ''),
                                    'web:browser:v7-soak': (0, self.SOAK_OK, None, '')}), 0)

    def test_the_rerun_that_decides_is_the_one_checked_for_skips(self):
        self.assertEqual(self.lane({'web:unit:x': (1, '\u2139 skipped 0\n', 0, '\u2139 skipped 1\n'),
                                    'web:browser:v7-soak': (0, self.SOAK_OK, None, '')}), 1)

    def test_a_rerun_that_skips_nothing_passes(self):
        self.assertEqual(self.lane({'web:unit:x': (1, '\u2139 skipped 1\n', 0, self.PLAIN_OK),
                                    'web:browser:v7-soak': (0, self.SOAK_OK, None, '')}), 0)

    def test_a_full_web_run_without_the_soak_s_file_fails(self):
        self.assertEqual(self.lane({'web:unit:x': (0, self.PLAIN_OK, None, '')}, units=('web:unit:x',)), 1)

    def test_a_full_web_run_whose_soak_did_not_run_fails(self):
        no_soak = '\u2714 a server retry hint far in the future is capped (Sol 3) (1ms)\n\u2139 skipped 0\n'
        self.assertEqual(self.lane({'web:unit:x': (0, self.PLAIN_OK, None, ''),
                                    'web:browser:v7-soak': (0, no_soak, None, '')}), 1)

    def test_a_soak_that_ran_only_in_the_failed_traced_attempt_fails(self):
        rerun_no_soak = '\u2714 a server retry hint far in the future is capped (Sol 3) (1ms)\n\u2139 skipped 0\n'
        self.assertEqual(self.lane({'web:unit:x': (0, self.PLAIN_OK, None, ''),
                                    'web:browser:v7-soak': (1, self.SOAK_OK, 0, rerun_no_soak)}), 1)

    def test_a_chosen_few_by_hand_owe_no_soak(self):
        self.assertEqual(self.lane({'web:unit:x': (0, self.PLAIN_OK, None, '')}, only=['web:unit:x'],
                                   units=('web:unit:x',)), 0)


def subprocess_ok():
    import subprocess
    return subprocess.CompletedProcess([], 0)


# Planted breaks: each, in a copy of the module, must make a test above fail.
BROKEN = [
    ('trace', "if exe.get(pid) in QUIET:", "if False:", "cargo's own reads kept"),
    ('trace', "        touched.add(full)\n", "        pass\n", "probes and plain paths dropped"),
    ('trace', "cwd[int(ret)] = here", "pass", "a child's folder not inherited"),
    ('trace', "listed.add(unescape(f.group(2)))", "pass", "listings dropped"),
    ('trace', "pending[pid] = rest[:-len('<unfinished ...>')].rstrip()", "pass", "split calls dropped"),
    ('resolve', "return f'reads {r}, a build product it can\\'t trace to its sources'", "return None",
     "an unknown build product kept"),
    ('resolve', "return f'reads git\\'s own {r}, through which it can see any file'", "return None",
     "git's index kept"),
    ('resolve', "return files | self.package_files(used) | mine", "return files",
     "the crates a test names dropped"),
    ('resolve', "files.add(EXPORT)\n            return None", "return None", "the export dropped"),
    ('resolve', "        return next(iter(found)) if len(found) == 1 else None", "        return next(iter(found), None)",
     "an ambiguous owner taken (R5)"),
    ('resolve', "return self.read_depinfo(uplifted) | self.manifests([pkg])", "return self.read_depinfo(uplifted)",
     "an uplifted program's manifests dropped (R6)"),
    ('map', "raise SystemExit(f'map: {uid} has no record: every test must be traced')", "pass",
     "a missing record allowed"),
    ('map', "if not rec.get('traced'):", "if False:", "an untraced test mapped"),
    ('map', "files |= set(export['files'])", "pass", "the export's inputs dropped"),
]


class Broken(unittest.TestCase):
    def test_each_planted_break_is_caught(self):
        for name, old, new, what in BROKEN:
            with self.subTest(what):
                path = os.path.join(HERE, name + '.py')
                with open(path) as f:
                    source = f.read()
                self.assertEqual(source.count(old), 1, f'{old!r} must be in {name}.py exactly once')
                module = sys.modules[name if name != 'map' else 'map']
                broken = types.ModuleType(module.__name__)
                broken.__file__ = path
                exec(compile(source.replace(old, new), path, 'exec'), broken.__dict__)
                globals_name = {'trace': 'trace', 'resolve': 'resolve', 'map': 'map_mod'}[name]
                real = globals()[globals_name]
                globals()[globals_name] = broken
                sys.modules[module.__name__] = broken
                try:
                    suite = unittest.TestSuite()
                    for case in (Parse, Repo, Map):
                        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
                    with open(os.devnull, 'w') as devnull:
                        outcome = unittest.TextTestRunner(stream=devnull, verbosity=0).run(suite)
                finally:
                    globals()[globals_name] = real
                    sys.modules[module.__name__] = real
                self.assertFalse(outcome.wasSuccessful(), f'not caught: {what}')


ROOT = os.path.dirname(os.path.dirname(HERE))
PRIVACY = os.path.join(ROOT, 'tools/privacy-check/check.py')
# The selector's committed files the public tree carries (#2298): the measured
# map and this file's synthetic strace fixtures.
PUBLISHED = ('ci/select/map.json', 'ci/select/test_trace.py')


class Privacy(unittest.TestCase):
    """The open-development privacy check (T3: home-shaped paths) passes the
    committed map and fixtures, and still refuses a planted home row."""

    def check(self, edit=None):
        with tempfile.TemporaryDirectory() as tree:
            for rel in PUBLISHED:
                os.makedirs(os.path.join(tree, os.path.dirname(rel)), exist_ok=True)
                with open(os.path.join(ROOT, rel)) as f:
                    text = f.read()
                with open(os.path.join(tree, rel), 'w') as f:
                    f.write(edit(rel, text) if edit else text)
            import subprocess
            r = subprocess.run([sys.executable, '-I', PRIVACY, '--tree', tree], capture_output=True, text=True)
        return r.returncode, [ln for ln in r.stdout.splitlines() if ln.startswith(('T', 'F', 'READ'))]

    def test_the_committed_map_and_fixtures_have_no_finding(self):
        rc, findings = self.check()
        self.assertEqual((len(findings), findings[:5]), (0, []))
        self.assertEqual(rc, 0)

    def test_a_planted_home_row_is_still_refused(self):
        # Split so this source line is not itself a home-shaped path.
        planted = '"apps/web/' + 'home' + '/package.json",'

        def plant(rel, text):
            if rel != 'ci/select/map.json':
                return text
            at = text.index('"files": [') + len('"files": [')
            return text[:at] + '\n    ' + planted + text[at:]
        rc, findings = self.check(plant)
        self.assertEqual(len(findings), 1, findings)
        self.assertTrue(findings[0].startswith('T3 staged:"ci/select/map.json"'), findings)
        self.assertNotEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
