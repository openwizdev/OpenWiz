#!/usr/bin/env python3
"""#1410: ci/rust-tests.sh's main-only exclusions (#1253), on both paths.

Runs the real script with a recording fake `cargo`, a fake `nproc` and a
synthetic cgroup under RUST_TESTS_ROOT: no Rust build, no network. A pull
request to main must pass the same four exact `--skip` names to the fallback
`cargo test --workspace` and to every call of the parallel path; every other
event must pass none.

Run from anywhere: python3 -I ci/test_rust_tests.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'rust-tests.sh'
ROOT = SCRIPT.parent.parent
# Copied by hand from #1253's list, not read from the script.
MAIN_ONLY = [
    'a_candidate_that_exits_without_readiness_rolls_back_to_the_running_old_build',
    'a_failing_merge_is_kept_and_recorded_once_without_retrying_the_gate',
    'a_passing_main_merge_is_staged_but_not_reported_as_running',
    'a_real_candidate_must_confirm_readiness_before_selection_or_switched',
]
SKIPS = ['--exact'] + [a for t in MAIN_ONLY for a in ('--skip', t)]
# Synthetic openwiz-tests targets: one plain, and web-api with its own threads.
TARGETS = ['alpha', 'web-api', 'zeta']
# Every event but a pull request to main runs every proof.
OTHERS = [
    ('push', ''),
    ('schedule', ''),
    ('merge_group', ''),
    ('workflow_dispatch', ''),
    ('pull_request', 'release-0.0.9'),
    ('pull_request', 'main-null'),
    ('pull_request', ''),
    ('pull_request_target', 'main'),
    (None, None),  # by hand: neither variable set
]

# The release fixture's build, before any test (#1260, Q1).
PREBUILD = ['build', '--release', '--locked', '-p', 'openwiz-tests', '--example', 'openwiz']

# The fake cargo: each call writes its argv to its own file (calls run at
# once), and its kind to the order log; answers `metadata` with the synthetic
# targets, and exits 0, or FAKE_PREBUILD_RC for the release fixture's build.
CARGO = '''import json, os, sys, tempfile
args = sys.argv[1:]
fd, _ = tempfile.mkstemp(dir=os.environ['FAKE_CARGO_CALLS'], suffix='.json')
with os.fdopen(fd, 'w') as f:
    json.dump(args, f)
prebuild = args == ['build', '--release', '--locked', '-p', 'openwiz-tests', '--example', 'openwiz']
with open(os.environ['FAKE_CARGO_ORDER'], 'a') as f:
    f.write(('prebuild' if prebuild else 'other') + '\\n')
if prebuild:
    sys.exit(int(os.environ.get('FAKE_PREBUILD_RC', '0')))
if args[:1] == ['metadata']:
    targets = [{'name': t, 'test': True, 'kind': ['test']} for t in json.loads(os.environ['FAKE_CARGO_TARGETS'])]
    print(json.dumps({'packages': [{'name': 'openwiz-tests', 'targets': targets}]}))
'''


class MainOnly(unittest.TestCase):
    def script(self, event, base, cpus, prebuild_rc=0):
        """Run the script; return (its stdout, every cargo call's argv). The
        release fixture's build comes first, once (#1260); with prebuild_rc,
        it fails and the script must exit with it, having run nothing else."""
        tmp = tempfile.TemporaryDirectory(prefix='rust-tests-1410-')
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        cg = d / 'sys/fs/cgroup'
        cg.mkdir(parents=True)
        (cg / 'cgroup.controllers').write_text('cpu memory\n')
        (cg / 'cpu.max').write_text('max 100000\n')
        (cg / 'memory.max').write_text('max\n')
        (d / 'proc/self').mkdir(parents=True)
        (d / 'proc/self/cgroup').write_text('0::/\n')
        calls = d / 'calls'
        calls.mkdir()
        bin_ = d / 'bin'
        bin_.mkdir()
        (bin_ / 'cargo.py').write_text(CARGO)
        (bin_ / 'cargo').write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{bin_ / "cargo.py"}" "$@"\n')
        (bin_ / 'nproc').write_text(f'#!/bin/sh\necho {cpus}\n')
        for name in ('cargo', 'nproc'):
            (bin_ / name).chmod(0o700)
        env = {k: v for k, v in os.environ.items() if k not in ('GITHUB_EVENT_NAME', 'GITHUB_BASE_REF')}
        env.update(PATH=f'{bin_}{os.pathsep}{os.environ["PATH"]}', RUST_TESTS_ROOT=str(d),
                   FAKE_CARGO_CALLS=str(calls), FAKE_CARGO_TARGETS=json.dumps(TARGETS),
                   FAKE_CARGO_ORDER=str(d / 'order'), FAKE_PREBUILD_RC=str(prebuild_rc))
        if event is not None:
            env['GITHUB_EVENT_NAME'] = event
        if base is not None:
            env['GITHUB_BASE_REF'] = base
        r = subprocess.run(['sh', str(SCRIPT)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, prebuild_rc, r.stdout + r.stderr)
        order = (d / 'order').read_text().splitlines()
        self.assertEqual(order[:1], ['prebuild'], order)
        self.assertEqual(order.count('prebuild'), 1, order)
        found = sorted(json.loads(p.read_text()) for p in calls.iterdir())
        self.assertEqual(found.count(PREBUILD), 1, found)
        return r.stdout, [c for c in found if c != PREBUILD]

    def parallel(self, event, base):
        """The parallel path's calls, checked apart from their skip arguments;
        returns {call: what follows its `--`, minus --test-threads}."""
        out, calls = self.script(event, base, 4)
        self.assertIn('rust-tests: every target at once', out)
        self.assertEqual(calls.count(['test', '--workspace', '--no-run', '--locked']), 1, calls)
        self.assertEqual(calls.count(['metadata', '--no-deps', '--format-version', '1', '--locked']), 1, calls)
        runs = [c for c in calls if c[0] == 'test' and '--no-run' not in c]
        self.assertEqual(len(runs), 1 + len(TARGETS), calls)
        found = {}
        for c in runs:
            head, tail = c[:c.index('--')], c[c.index('--') + 1:]
            if '--exclude' in head:
                self.assertEqual(head, ['test', '--workspace', '--exclude', 'openwiz-tests', '--locked'])
                name, threads = 'crates', '8'
            else:
                self.assertEqual((head[:5], len(head)), (['test', '-p', 'openwiz-tests', '--locked', '--test'], 6), c)
                name = head[5]
                threads = '24' if name == 'web-api' else '8'
            self.assertNotIn(name, found, calls)
            self.assertEqual(tail[0], f'--test-threads={threads}', c)
            found[name] = tail[1:]
        self.assertEqual(sorted(found), sorted(['crates'] + TARGETS))
        return out, found

    def fallback(self, event, base):
        """The fallback's one call; returns what follows its `--`."""
        out, calls = self.script(event, base, 3)
        self.assertIn('rust-tests: one command, cargo test --workspace: 3 CPUs by nproc, fewer than 4', out)
        self.assertEqual(len(calls), 1, calls)
        c = calls[0]
        self.assertEqual(c[:c.index('--')], ['test', '--workspace', '--locked'])
        # #1260, Q3: 8 test threads, before any skips.
        tail = c[c.index('--') + 1:]
        self.assertEqual(tail[:1], ['--test-threads=8'], c)
        return out, tail[1:]

    def test_main_pr_parallel_skips_in_every_call(self):
        out, found = self.parallel('pull_request', 'main')
        self.assertIn('skipping the main-only proofs', out)
        for name, tail in found.items():
            with self.subTest(call=name):
                self.assertEqual(tail, SKIPS)

    def test_main_pr_fallback_skips(self):
        out, tail = self.fallback('pull_request', 'main')
        self.assertIn('skipping the main-only proofs', out)
        self.assertEqual(tail, SKIPS)

    def test_other_events_run_every_proof(self):
        for event, base in OTHERS:
            with self.subTest(event=event, base=base, path='parallel'):
                out, found = self.parallel(event, base)
                self.assertNotIn('skipping', out)
                self.assertEqual(found, {name: [] for name in ['crates'] + TARGETS})
            with self.subTest(event=event, base=base, path='fallback'):
                out, tail = self.fallback(event, base)
                self.assertNotIn('skipping', out)
                self.assertEqual(tail, [])

    def test_a_failed_release_fixture_runs_nothing_else(self):
        # #1260: on either path, with or without the skips.
        for cpus in (3, 4):
            for event, base in (('pull_request', 'main'), (None, None)):
                with self.subTest(cpus=cpus, event=event):
                    _, calls = self.script(event, base, cpus, prebuild_rc=7)
                    self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
