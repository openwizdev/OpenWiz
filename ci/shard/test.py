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
INVALID = ROOT / 'ci' / 'selection' / 'invalid' / 'expand.py'  # the invalid plans' table
PC = 'closedwiz-pc'
NAMESPACE = 'namespace-profile-closedwiz-rust'
GITHUB = 'ubuntu-24.04'


def rid(name):
    return f'rust:test:{name}'


# The worked example: five binaries, seconds by hand.
FIVE = {'alpha': 10, 'bravo': 7, 'charlie': 6, 'delta': 5, 'echo': 4}


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

    def invalid(self, name):
        """One of the contract's invalid plans (ci/selection/invalid/cases.json), as a file."""
        sys.path.insert(0, str(INVALID.parent))
        import expand
        return self.file(name, expand.plan(name))

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

    def split(self, out):
        return [(s['tests'], s['seconds']) for s in out['shards']]


class Balance(Case):
    def test_every_planned_test_in_exactly_one_shard_with_libs(self):
        tests = [rid(n) for n in FIVE] + ['rust:lib:openwiz-core', 'rust:lib:openwiz-adapter-github']
        times = {rid(n): s for n, s in FIVE.items()} | {'rust:lib:openwiz-core': 0.02, 'rust:lib:openwiz-adapter-github': 62.1}
        out = self.balance(tests, times, 3)
        placed = [t for s in out['shards'] for t in s['tests']]
        self.assertEqual(sorted(placed), sorted(tests))
        self.assertEqual(len(placed), len(set(placed)))
        # openwiz-adapter-github alone outlasts the rest together (32.02 s).
        self.assertEqual(self.split(out), [
            (['rust:lib:openwiz-adapter-github'], 62.1),
            ([rid(n) for n in FIVE] + ['rust:lib:openwiz-core'], 32.02),
        ])


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
                self.refused(self.run_shard('plan', self.invalid(name), '--shards', 2,
                                            '--times', times), words)

    def test_a_plan_that_is_not_there(self):
        self.refused(self.run_shard('plan', self.dir / 'none.json', '--shards', 2,
                                    '--times', self.times({rid('a'): 1})), 'none.json')


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
        r = self.run_shard('check', self.invalid('test-twice.json'), *self.ran([rid('a')]))
        self.assertEqual(r.returncode, 1)
        self.assertIn('rule 6', r.stderr)


class Share(Case):
    """One shard's tests, one a line, for ci.yml's matrix member."""

    def share(self, n, k, tests=None, times=None):
        tests = tests or [rid(x) for x in FIVE]
        return self.run_shard('share', self.plan(tests), '--shards', n, '--shard', k,
                              '--times', self.times(times or {rid(x): t for x, t in FIVE.items()}))

    def test_a_refused_plan_shares_nothing(self):
        r = self.run_shard('share', self.invalid('test-twice.json'), '--shards', 1, '--shard', 1,
                           '--times', self.times({rid('a'): 1}))
        self.assertEqual((r.returncode, r.stdout), (1, ''))


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

    def test_the_rust_job_fans_out_by_runner_kind_and_only_on_free_runners(self):
        blocks = jobs()
        found = []
        for name in ('rust',):
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
        self.assertEqual(len(found), 1)

    def plan_dir(self, tests):
        folder = self.dir / 'ci-plan'
        folder.mkdir(exist_ok=True)
        (folder / 'ci-selection.json').write_text(self.plan(tests).read_text())
        return folder

    def test_each_member_records_its_share_and_the_shares_cover_the_plan(self):
        tests = [rid(n) for n in FIVE]
        for name in ('rust',):
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

    def test_the_ci_check_runs_when_the_rust_job_passed_and_before_the_verdict(self):
        block = jobs()['ci']
        text, _ = step(block, 'Every Rust test ran exactly once')
        self.assertIn("        if: needs.rust.result == 'success'\n", text)
        self.assertLess(block.index('name: Every Rust test ran exactly once'), block.index('name: Every planned lane passed'))
        self.assertIn('pattern: rust-ran-${{ github.run_attempt }}-*', block)



def escapes_json(text):
    sys.path.insert(0, str(ROOT / 'ci' / 'escapes'))
    import escapes
    return escapes.strict_json(text)


if __name__ == '__main__':
    os.chdir(ROOT)
    unittest.main(verbosity=2)
