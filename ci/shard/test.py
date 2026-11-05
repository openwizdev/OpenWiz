#!/usr/bin/env python3
"""The shard balancer's tests (#1266, X8 of spec #1256).

Runs the real ci/shard/shard.py on synthetic plans (ci/selection/'s valid
full-run fixture with synthetic Rust ids), synthetic times and synthetic CI
logs: no Rust build, no network, no gh. Each expected split is worked out by
hand below (longest first, each to the least loaded shard), never computed
the way the balancer computes it.

Run from anywhere: python3 -I ci/shard/test.py
"""
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True  # imports escapes and test_lanes: no __pycache__ beside them

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SHARD = HERE / 'shard.py'
FULL = ROOT / 'ci' / 'selection' / 'valid' / 'full-push-main.json'
SKIPPED = ROOT / 'ci' / 'selection' / 'valid' / 'selected-skill-only.json'
INVALID = ROOT / 'ci' / 'selection' / 'invalid'
PC = 'closedwiz-pc'
NAMESPACE = 'namespace-profile-closedwiz-rust'
GITHUB = 'ubuntu-24.04'


def rid(name):
    return f'rust:test:{name}'


# The worked example: five binaries, seconds by hand.
FIVE = {'alpha': 10, 'bravo': 7, 'charlie': 6, 'delta': 5, 'echo': 4}
TS = '2026-01-02T03:04:05.6789012Z '
NONCE = 'ab' * 32


class Case(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def file(self, name, text):
        p = self.dir / name
        p.write_text(text)
        return p

    def plan(self, tests):
        """full-push-main.json, its Rust lane running exactly these ids."""
        plan = json.loads(FULL.read_text())
        plan['lanes']['rust'] = {'decision': 'run', 'tests': tests, 'skipped': []}
        return self.file('plan.json', json.dumps(plan))

    def times(self, rows):
        return self.file('times.tsv', '# synthetic\n' + ''.join(f'{i}\t{s}\n' for i, s in rows.items()))

    def run_shard(self, *args):
        return subprocess.run([sys.executable, '-I', str(SHARD), *map(str, args)],
                              capture_output=True, text=True, timeout=60)

    def balance(self, tests, times, most):
        r = self.run_shard('plan', self.plan(tests), '--shards', most, '--times', self.times(times))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def five(self, most):
        return self.balance([rid(n) for n in FIVE], {rid(n): s for n, s in FIVE.items()}, most)

    def split(self, out):
        return [(s['tests'], s['seconds']) for s in out['shards']]


class Balance(Case):
    def test_two_shards_longest_first_to_the_least_loaded(self):
        # alpha 10 -> 1; bravo 7 -> 2; charlie 6 -> 2 (7 < 10): 13;
        # delta 5 -> 1 (10 < 13): 15; echo 4 -> 2 (13 < 15): 17.
        out = self.five(2)
        self.assertEqual(self.split(out), [
            ([rid('alpha'), rid('delta')], 15),
            ([rid('bravo'), rid('charlie'), rid('echo')], 17),
        ])
        self.assertEqual(out['seconds'], 17)
        self.assertEqual(out['unmeasured'], [])

    def test_three_shards(self):
        # alpha -> 1 (10); bravo -> 2 (7); charlie -> 3 (6); delta -> 3 (11);
        # echo -> 2 (11).
        self.assertEqual(self.split(self.five(3)), [
            ([rid('alpha')], 10),
            ([rid('bravo'), rid('echo')], 11),
            ([rid('charlie'), rid('delta')], 11),
        ])

    def test_never_more_shards_than_needed(self):
        # Up to 8 allowed, 5 tests: four shards already finish in alpha's 10 s
        # (delta and echo share one: 9 s), so a fifth would add a runner for
        # nothing.
        self.assertEqual(self.split(self.five(8)), [
            ([rid('alpha')], 10),
            ([rid('bravo')], 7),
            ([rid('charlie')], 6),
            ([rid('delta'), rid('echo')], 9),
        ])

    def test_one_long_binary_takes_one_shard_and_the_rest_share_one(self):
        times = {rid('huge'): 100, rid('a'): 1, rid('b'): 1, rid('c'): 1}
        out = self.balance(list(times), times, 4)
        self.assertEqual(self.split(out), [([rid('huge')], 100), ([rid('a'), rid('b'), rid('c')], 3)])

    def test_one_shard_is_every_test_longest_first(self):
        self.assertEqual(self.split(self.five(1)), [([rid(n) for n in FIVE], 32)])

    def test_every_planned_test_in_exactly_one_shard_with_libs(self):
        tests = [rid(n) for n in FIVE] + ['rust:lib:openwiz-core', 'rust:lib:openwiz-service']
        times = {rid(n): s for n, s in FIVE.items()} | {'rust:lib:openwiz-core': 0.02, 'rust:lib:openwiz-service': 62.1}
        out = self.balance(tests, times, 3)
        placed = [t for s in out['shards'] for t in s['tests']]
        self.assertEqual(sorted(placed), sorted(tests))
        self.assertEqual(len(placed), len(set(placed)))
        # openwiz-service alone outlasts the rest together (32.02 s).
        self.assertEqual(self.split(out), [
            (['rust:lib:openwiz-service'], 62.1),
            ([rid(n) for n in FIVE] + ['rust:lib:openwiz-core'], 32.02),
        ])

    def test_an_unmeasured_binary_counts_as_the_longest_measured(self):
        # echo has no time: 10 s, alpha's. Sorted by time, then id: alpha 10,
        # echo 10, bravo 7, charlie 6, delta 5. alpha -> 1; echo -> 2;
        # bravo -> 1 (17); charlie -> 2 (16); delta -> 2 (21).
        times = {rid(n): s for n, s in FIVE.items() if n != 'echo'}
        out = self.balance([rid(n) for n in FIVE], times, 2)
        self.assertEqual(self.split(out), [
            ([rid('alpha'), rid('bravo')], 17),
            ([rid('echo'), rid('charlie'), rid('delta')], 21),
        ])
        self.assertEqual(out['unmeasured'], [rid('echo')])

    def test_a_skipped_rust_lane_has_no_shards(self):
        r = self.run_shard('plan', SKIPPED, '--shards', 4, '--times', self.times({rid('a'): 1}))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['shards'], [])

    def test_the_same_answer_every_time(self):
        first = self.run_shard('plan', self.plan([rid(n) for n in FIVE]), '--shards', 3,
                               '--times', self.times({rid(n): s for n, s in FIVE.items()}))
        again = self.run_shard('plan', self.dir / 'plan.json', '--shards', 3,
                               '--times', self.dir / 'times.tsv')
        self.assertEqual((first.returncode, first.stdout), (again.returncode, again.stdout))


class Refuse(Case):
    def refused(self, r, words):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(r.stdout, '')
        self.assertIn(words, r.stderr)

    def test_a_plan_the_contract_refuses(self):
        times = self.times({rid('a'): 1})
        for name, words in [('test-twice.json', 'rule 6'), ('duplicate-key.json', 'rule 1'),
                            ('rust-test-unknown-kind.json', 'rule 7')]:
            with self.subTest(name=name):
                self.refused(self.run_shard('plan', INVALID / name, '--shards', 2,
                                            '--times', times), words)

    def test_a_plan_that_is_not_there(self):
        self.refused(self.run_shard('plan', self.dir / 'none.json', '--shards', 2,
                                    '--times', self.times({rid('a'): 1})), 'none.json')

    def test_odd_times(self):
        plan = self.plan([rid('a')])
        for text, words in [
            ('rust:test:a\t1\nrust:test:a\t2\n', 'twice'),
            ('rust:test:a 1\n', 'line 1'),
            ('rust:test:a\t-1\n', 'line 1'),
            ('rust:test:a\tnan\n', 'line 1'),
            ('rust:test:a\t1e3\n', 'line 1'),
            ('web:unit:a\t1\n', 'line 1'),
            ('rust:test:\t1\n', 'line 1'),
            ('\n', 'line 1'),
            ('# nothing timed\n', 'times nothing'),
            ('rust:test:a\t1\nrust:test:b\t2', 'newline'),
        ]:
            with self.subTest(text=text):
                self.refused(self.run_shard('plan', plan, '--shards', 2,
                                            '--times', self.file('odd.tsv', text)), words)

    def test_a_bad_command_line(self):
        plan, times = self.plan([rid('a')]), self.times({rid('a'): 1})
        for args in [[], ['plan', plan], ['plan', plan, '--times', times], ['plan', plan, '--shards', 2],
                     ['plan', plan, '--shards', 0, '--times', times],
                     ['plan', plan, '--shards', 'x', '--times', times],
                     ['plan', plan, '--shards', '1000', '--times', times],
                     ['plan', plan, '--runner', GITHUB, '--max', 2, '--times', times],
                     ['share', plan, '--shards', 2, '--times', times],
                     ['share', plan, '--shards', 2, '--shard', 0, '--times', times],
                     ['share', plan, '--shards', 2, '--shard', 3, '--times', times],
                     ['check'], ['times'], ['other']]:
            with self.subTest(args=args):
                r = self.run_shard(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(r.stdout, '')


class Check(Case):
    """Every selected binary ran exactly once, across the shards' records."""

    def ran(self, *shards):
        return [self.file(f'ran-{i}.txt', ''.join(f'{t}\n' for t in s)) for i, s in enumerate(shards, 1)]

    def check(self, *shards):
        plan = self.plan([rid(n) for n in FIVE])
        return self.run_shard('check', plan, *self.ran(*shards))

    def test_each_once_passes(self):
        r = self.check([rid('alpha'), rid('delta')], [rid('bravo'), rid('charlie'), rid('echo')])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('every one of the 5 selected Rust tests ran exactly once', r.stdout)

    def test_a_missing_binary_fails(self):
        r = self.check([rid('alpha'), rid('delta')], [rid('bravo'), rid('charlie')])
        self.assertEqual(r.returncode, 1)
        self.assertIn('rust:test:echo: never ran', r.stderr)

    def test_a_doubled_binary_fails(self):
        for shards in [([rid('alpha'), rid('delta')], [rid('bravo'), rid('charlie'), rid('echo'), rid('delta')]),
                       ([rid('alpha'), rid('delta'), rid('delta')], [rid('bravo'), rid('charlie'), rid('echo')])]:
            with self.subTest(shards=shards):
                r = self.check(*shards)
                self.assertEqual(r.returncode, 1)
                self.assertIn('rust:test:delta: ran 2 times', r.stderr)

    def test_an_unselected_binary_fails(self):
        r = self.check([rid('alpha'), rid('delta')], [rid('bravo'), rid('charlie'), rid('echo'), rid('zulu')])
        self.assertEqual(r.returncode, 1)
        self.assertIn('rust:test:zulu: ran, but the plan did not select it', r.stderr)

    def test_no_shard_record_fails(self):
        r = self.run_shard('check', self.plan([rid('a')]))
        self.assertEqual(r.returncode, 1)
        self.assertIn('rust:test:a: never ran', r.stderr)

    def test_a_skipped_lane_with_no_records_passes(self):
        r = self.run_shard('check', SKIPPED)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_an_odd_record_fails(self):
        for text in ['rust:test:alpha\n\n', ' rust:test:alpha\n', 'web:unit:alpha\n', 'rust:test:alpha']:
            with self.subTest(text=text):
                r = self.run_shard('check', self.plan([rid('alpha')]), self.file('odd.txt', text))
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn('odd.txt', r.stderr)

    def test_a_record_that_is_not_there_fails(self):
        r = self.run_shard('check', self.plan([rid('a')]), self.dir / 'none.txt')
        self.assertEqual(r.returncode, 1)
        self.assertIn('none.txt', r.stderr)

    def test_a_refused_plan_fails(self):
        r = self.run_shard('check', INVALID / 'test-twice.json', *self.ran([rid('a')]))
        self.assertEqual(r.returncode, 1)
        self.assertIn('rule 6', r.stderr)


class Times(Case):
    """Each binary's time from CI's Rust logs: its libtest totals, median."""

    def test_traced_and_at_once_logs(self):
        traced = self.file('traced.log', ''.join(TS + line + '\n' for line in [
            '== trace: rust:lib:openwiz-core',
            '   Compiling openwiz-core v0.0.1-dev',
            'test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.50s',
            'test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.25s',
            '== trace: rust:test:fleet',
            'test result: ok. 9 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 80.00s',
            'trace: rust:test:fleet: ok, 256.2 s, 0 files, 0 folders, mapped',
            "== trace: the skills' tests",
            'test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 99.00s',
        ]))
        at_once = self.file('at-once.log', ''.join(TS + line + '\n' for line in [
            # crates: every package but openwiz-tests in one call, each
            # package's tests after its library's (cargo's order), then the
            # doc tests by library name. A result before any library is no
            # package's.
            f'rust-tests-frame:{NONCE} == rust-tests: crates',
            'test result: ok. 3 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 5.00s',
            '     Running unittests src/lib.rs (target/debug/deps/openwiz_core-1aad9666a4a83714)',
            'test result: ok. 7 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.50s',
            '     Running unittests src/lib.rs (target/debug/deps/openwiz_service-0dd6291d0532ac04)',
            'test result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.06s',
            '     Running unittests src/main.rs (target/debug/deps/openwiz_service-1aa150db7fc42db5)',
            'test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s',
            '     Running ../../tests/service/t6_update.rs (target/debug/deps/t6_update-6ef3f0dfbb20baea)',
            'test result: ok. 31 passed; 0 failed; 0 ignored; 0 measured; 4 filtered out; finished in 31.07s',
            '   Doc-tests openwiz_core',
            'test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.25s',
            '   Doc-tests openwiz_service',
            'test result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.10s',
            f'rust-tests-frame:{NONCE} == rust-tests: fleet',
            'test result: ok. 9 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 90.00s',
            f'rust-tests-frame:{NONCE} == rust-tests: web-api',
            'test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 30.5s',
            f'rust-tests-frame:{NONCE} rust-tests: web-api: ok',
        ]))
        third = self.file('third.log', '\n'.join([
            '== trace: rust:test:fleet',
            'test result: ok. 9 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 100.00s',
        ]) + '\n')
        r = self.run_shard('times', traced, at_once, third)
        self.assertEqual(r.returncode, 0, r.stderr)
        # fleet: 80, 90 and 100, median 90. core: 1.5 + 0.25 traced and
        # 0.5 + 0.25 at once, median 1.25. service: 0.06 + 0 + 31.07 + 0.10.
        self.assertEqual(r.stdout, ''.join([
            'rust:lib:openwiz-core\t1.25\n',
            'rust:lib:openwiz-service\t31.23\n',
            'rust:test:fleet\t90.00\n',
            'rust:test:web-api\t30.50\n',
        ]))

    def test_the_times_file_it_writes_balances(self):
        log = self.file('one.log', '== trace: rust:test:a\ntest result: ok. finished in 2.00s\n')
        r = self.run_shard('times', log)
        self.assertEqual(r.returncode, 0, r.stderr)
        tsv = self.file('made.tsv', r.stdout)
        b = self.run_shard('plan', self.plan([rid('a')]), '--shards', 2, '--times', tsv)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(json.loads(b.stdout)['seconds'], 2)

    def test_a_log_with_no_rust_time_is_refused(self):
        r = self.run_shard('times', self.file('none.log', "== trace: the skills' tests\nfinished in 3.00s\n"))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, '')
        self.assertIn('none.log', r.stderr)

    def test_a_binary_twice_in_one_log_is_refused(self):
        r = self.run_shard('times', self.file('twice.log', ''.join([
            '== trace: rust:test:a\n', 'test result: ok. finished in 1.00s\n',
            '== trace: rust:test:a\n', 'test result: ok. finished in 1.00s\n'])))
        self.assertEqual(r.returncode, 1)
        self.assertIn('rust:test:a', r.stderr)


class Share(Case):
    """One shard's tests, one a line, for ci.yml's matrix member."""

    def share(self, n, k, tests=None, times=None):
        tests = tests or [rid(x) for x in FIVE]
        return self.run_shard('share', self.plan(tests), '--shards', n, '--shard', k,
                              '--times', self.times(times or {rid(x): t for x, t in FIVE.items()}))

    def test_each_shard_its_share(self):
        # As test_two_shards_longest_first_to_the_least_loaded.
        self.assertEqual([self.share(2, k).stdout for k in (1, 2)],
                         ['rust:test:alpha\nrust:test:delta\n', 'rust:test:bravo\nrust:test:charlie\nrust:test:echo\n'])

    def test_a_member_past_the_shards_needed_runs_nothing(self):
        # Two tests, three members: the third has nothing to run.
        tests, times = [rid('a'), rid('b')], {rid('a'): 1, rid('b'): 1}
        out = [self.share(3, k, tests, times) for k in (1, 2, 3)]
        self.assertEqual([(r.returncode, r.stdout) for r in out], [(0, 'rust:test:a\n'), (0, 'rust:test:b\n'), (0, '')])

    def test_a_skipped_lane_shares_nothing(self):
        r = self.run_shard('share', SKIPPED, '--shards', 1, '--shard', 1, '--times', self.times({rid('a'): 1}))
        self.assertEqual((r.returncode, r.stdout), (0, ''), r.stderr)

    def test_a_refused_plan_shares_nothing(self):
        r = self.run_shard('share', INVALID / 'test-twice.json', '--shards', 1, '--shard', 1,
                           '--times', self.times({rid('a'): 1}))
        self.assertEqual((r.returncode, r.stdout), (1, ''))


class Committed(Case):
    def test_the_committed_times_balance_every_rust_test_the_tree_has(self):
        # Every Rust id units.py lists at this checkout is timed (none
        # unmeasured), and each lands in exactly one of 4 shards.
        sys.path.insert(0, str(ROOT / 'ci' / 'select'))
        import units
        ids = sorted(i for i in units.rust_units(str(ROOT)))
        r = self.run_shard('plan', self.plan(ids), '--shards', 4, '--times', HERE / 'times.tsv')
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out['unmeasured'], [])
        placed = [t for s in out['shards'] for t in s['tests']]
        self.assertEqual(sorted(placed), ids)


WORKFLOW = ROOT / '.github' / 'workflows' / 'ci.yml'
DOCS_ONLY = ROOT / '.github' / 'actions' / 'docs-only'
# GitHub's free runners for this repository's CI: the PC's, and GitHub's
# standard one (free on a public repository). Namespace is paid.
FREE = {PC, GITHUB}


def jobs():
    source = WORKFLOW.read_text().split('jobs:\n', 1)[1]
    return {m[1]: m[2] for m in re.finditer(r'^  ([a-z][a-z0-9-]*):\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)', source, re.M | re.S)}


def step(block, name):
    """A job's step by name: its text, and its run script, dedented."""
    steps = [x for x in block.split('    steps:\n', 1)[1].split('      - ')[1:] if x.startswith(f'name: {name}\n')]
    if len(steps) != 1:
        raise AssertionError(f'{len(steps)} steps named {name!r}')
    text = steps[0]
    one = re.search(r'^        run: (?!\|)(.*)$', text, re.M)
    if one:
        return text, one[1]
    if '        run: |\n' not in text:
        return text, None
    body = text.split('        run: |\n', 1)[1]
    lines = []
    for line in body.splitlines():
        if line and not line.startswith('          '):
            break
        lines.append(line[10:])
    return text, '\n'.join(lines)


MATRIX = re.compile(r"^        shard: \$\{\{ fromJSON\(\(needs\.changes\.outputs\.trace == 'true' \|\| "
                    r"needs\.changes\.outputs\.planted == 'true'\) && '\[1\]' \|\| fromJSON\('(\{[^']*\})'\)"
                    r"\[(.*)\] \|\| '\[1\]'\) \}\}$", re.M)


class Workflow(Case):
    """ci.yml's Rust lanes: shards by runner kind, and the ci check counting them."""

    def test_both_rust_jobs_fan_out_by_runner_kind_and_only_on_free_runners(self):
        blocks = jobs()
        found = []
        for name in ('rust', 'rust-export'):
            with self.subTest(job=name):
                block = blocks[name]
                self.assertIn('    strategy:\n      fail-fast: false\n      matrix:\n', block)
                m = MATRIX.search(block)
                self.assertIsNotNone(m, 'the shard matrix line')
                runner = re.search(r'^    runs-on: \$\{\{ (.*) \}\}$', block, re.M)[1]
                # The label the setting is read for is the one the job runs on.
                self.assertEqual(m[2], runner)
                kinds = escapes_json(m[1])
                found.append(kinds)
                # Free CI only: a runner kind not named gets one shard, and
                # only free kinds may be named.
                self.assertLessEqual(set(kinds), FREE)
                for kind, members in kinds.items():
                    n = len(json.loads(members))
                    self.assertEqual(json.loads(members), list(range(1, n + 1)), kind)
        self.assertEqual(found[0], found[1])

    def plan_dir(self, tests):
        folder = self.dir / 'ci-plan'
        folder.mkdir(exist_ok=True)
        (folder / 'ci-selection.json').write_text(self.plan(tests).read_text())
        return folder

    def test_each_member_records_its_share_and_the_shares_cover_the_plan(self):
        tests = [rid(n) for n in FIVE]
        for name in ('rust', 'rust-export'):
            for n in (1, 2, 3):
                with self.subTest(job=name, shards=n):
                    self.plan_dir(tests)
                    # The member's share, then (its tests passed) its record.
                    scripts = [step(jobs()[name], x)[1] for x in ('The Rust shard', 'Record passed lane')]
                    for k in range(1, n + 1):
                        env = dict(os.environ, RUNNER_TEMP=str(self.dir), SHARDS=str(n), SHARD=str(k))
                        for script in scripts:
                            r = subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=ROOT, env=env,
                                               capture_output=True, text=True, timeout=60)
                            self.assertEqual(r.returncode, 0, r.stderr)
                    ran = [t for k in range(1, n + 1)
                           for t in (self.dir / 'rust-ran' / f'ran-{k}.txt').read_text().split()]
                    self.assertEqual(sorted(ran), sorted(tests))
                    for f in (self.dir / 'rust-ran').iterdir():
                        f.unlink()

    def test_once_only_steps_run_on_the_first_member(self):
        for name in ('rust', 'rust-export'):
            block = jobs()[name]
            for once in ('Build and lint Rust', "The shard balancer's tests", 'Save the cargo-rust cache',
                         'Save the GitHub cargo-rust cache'):
                with self.subTest(job=name, step=once):
                    text, _ = step(block, once)
                    self.assertIsNotNone(re.search(r'^        if: .*&& strategy\.job-index == 0$|^        if: strategy\.job-index == 0$',
                                                   text, re.M), text)

    def test_ci_runs_these_proofs_in_both_rust_jobs(self):
        # The balancer, the check and this wiring are enforced by CI itself.
        for name in ('rust', 'rust-export'):
            with self.subTest(job=name):
                _, script = step(jobs()[name], "The shard balancer's tests")
                self.assertEqual(script, 'python3 -I ci/shard/test.py')

    def lanes(self):
        sys.path.insert(0, str(DOCS_ONLY))
        import test_lanes
        fixture = test_lanes.Lanes('test_every_planned_job_and_skill_member_passed')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        (fixture.receipts / 'rust.json').unlink()
        (fixture.path / 'ci-plan').mkdir()
        for name in ('ci-selection.json', 'ci-dispatch.json'):
            (fixture.path / 'ci-plan' / name).write_bytes((fixture.path / name).read_bytes())
        return fixture

    def ci_check(self, fixture, *shards):
        ran = fixture.path / 'rust-ran'
        ran.mkdir(exist_ok=True)
        for f in ran.iterdir():
            f.unlink()
        for k, share in enumerate(shards, 1):
            (ran / f'ran-{k}.txt').write_text(''.join(t + '\n' for t in share))
        text, script = step(jobs()['ci'], 'Every Rust test ran exactly once')
        env = dict(os.environ, RUNNER_TEMP=str(fixture.path), GITHUB_RUN_ID=str(fixture.plan['run']['id']),
                   GITHUB_RUN_ATTEMPT='1', GITHUB_EVENT_NAME='schedule')
        return subprocess.run(['bash', '-euo', 'pipefail', '-c', script], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_the_ci_check_counts_every_shard(self):
        fixture = self.lanes()
        tests = fixture.expected['rust']
        self.assertGreaterEqual(len(tests), 2)
        half = len(tests) // 2
        for shards, ok in [((tests[:half], tests[half:]), True),
                           ((tests[:half], tests[half + 1:]), False),
                           ((tests[:half + 1], tests[half:]), False),
                           ((), False)]:
            with self.subTest(shards=shards):
                (fixture.receipts / 'rust.json').unlink(missing_ok=True)
                r = self.ci_check(fixture, *shards)
                self.assertEqual(r.returncode, 0 if ok else 1, r.stdout + r.stderr)
                self.assertEqual((fixture.receipts / 'rust.json').exists(), ok)
                finish = fixture.run_finish()
                self.assertEqual(finish.returncode, 0 if ok else 1, finish.stderr)

    def test_the_ci_check_runs_when_either_rust_job_passed_and_before_the_verdict(self):
        block = jobs()['ci']
        text, _ = step(block, 'Every Rust test ran exactly once')
        self.assertIn("        if: needs.rust.result == 'success' || needs.rust-export.result == 'success'\n", text)
        self.assertLess(block.index('name: Every Rust test ran exactly once'), block.index('name: Every planned lane passed'))
        self.assertIn('pattern: rust-ran-${{ github.run_attempt }}-*', block)


class RustTests(Case):
    """ci/rust-tests.sh --only, a shard's runner: it builds only its share."""

    CARGO = """import json, os, sys, tempfile
args = sys.argv[1:]
fd, _ = tempfile.mkstemp(dir=os.environ['FAKE_CARGO_CALLS'], suffix='.json')
with os.fdopen(fd, 'w') as f:
    json.dump(args, f)
if args[:1] == ['metadata']:
    targets = [{'name': t, 'test': True, 'kind': ['test']} for t in ('alpha', 'bravo', 'web-api')]
    print(json.dumps({'packages': [{'name': 'openwiz-tests', 'targets': targets}]}))
"""

    def calls(self, only):
        """Every cargo call of `rust-tests.sh --only ONLY` where every target
        may run at once (4 CPUs, no cgroup limit), with a recording cargo."""
        return self.run_script(['sh', str(ROOT / 'ci' / 'rust-tests.sh'), '--only', only], {})

    def run_script(self, argv, extra):
        """Run ARGV with the recording cargo; every cargo call, in order."""
        d = self.dir
        cg = d / 'sys/fs/cgroup'
        cg.mkdir(parents=True)
        (cg / 'cgroup.controllers').write_text('cpu memory\n')
        (cg / 'cpu.max').write_text('max 100000\n')
        (cg / 'memory.max').write_text('max\n')
        (d / 'proc/self').mkdir(parents=True)
        (d / 'proc/self/cgroup').write_text('0::/\n')
        (d / 'calls').mkdir()
        b = d / 'bin'
        b.mkdir()
        (b / 'cargo.py').write_text(self.CARGO)
        (b / 'cargo').write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{b / "cargo.py"}" "$@"\n')
        (b / 'nproc').write_text('#!/bin/sh\necho 4\n')
        for name in ('cargo', 'nproc'):
            (b / name).chmod(0o700)
        env = {k: v for k, v in os.environ.items() if k not in ('GITHUB_EVENT_NAME', 'GITHUB_BASE_REF')}
        env.update(PATH=f'{b}{os.pathsep}{os.environ["PATH"]}', RUST_TESTS_ROOT=str(d), FAKE_CARGO_CALLS=str(d / 'calls'),
                   **extra)
        r = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('rust-tests: every target at once', r.stdout)
        return sorted(json.loads(p.read_text()) for p in (d / 'calls').iterdir())

    def test_a_share_builds_only_its_own_tests(self):
        calls = self.calls('rust:lib:openwiz-core rust:test:alpha')
        builds = [c for c in calls if '--no-run' in c]
        self.assertEqual(builds, [['test', '--locked', '-p', 'openwiz-core', '--no-run'],
                                  ['test', '--locked', '-p', 'openwiz-tests', '--test', 'alpha', '--no-run']])

    def test_a_share_of_targets_only_builds_no_package(self):
        builds = [c for c in self.calls('rust:test:alpha rust:test:web-api') if '--no-run' in c]
        self.assertEqual(builds, [['test', '--locked', '-p', 'openwiz-tests', '--test', 'alpha', '--test', 'web-api',
                                   '--no-run']])


def escapes_json(text):
    sys.path.insert(0, str(ROOT / 'ci' / 'escapes'))
    import escapes
    return escapes.strict_json(text)


if __name__ == '__main__':
    os.chdir(ROOT)
    unittest.main(verbosity=2)
