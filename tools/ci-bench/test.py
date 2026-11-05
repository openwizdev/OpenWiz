#!/usr/bin/env python3
"""bench.py on recorded and synthetic job data (ClosedWiz#332, spec #330, CS1).

Run from anywhere:  python3 tools/ci-bench/test.py

M: `measure` on fixtures/window, a synthetic window of six runs whose every
number is worked out by hand in the comments below, never the way bench.py
computes it. C: `collect` on the fake `gh` (fixtures/gh) and a synthetic
GitHub built here: the exact reads, the exact files, and a refusal for each
read it can't trust. K: `chart`. B: the 2026-11-01 baseline's recorded
jobs.jsonl (private/evidence/infra-ci-scale/bench/baseline/), whose expected
numbers come from the baseline's own bench.json and from the orchestrator's
answer on #332. BENCH_PY=<file> runs the same cases against another script.
"""
import calendar
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("BENCH_PY", HERE / "bench.py")).resolve()
WINDOW = HERE / "fixtures" / "window"
FAKE_GH = HERE / "fixtures" / "gh"
ROOT = HERE.parent.parent
BASELINE = ROOT / "private" / "evidence" / "infra-ci-scale" / "bench" / "baseline"
# The sha256 of private/evidence/infra-ci-scale/baseline/jobs.jsonl at
# 934fc9123de0f1666a78ec91cf123d1cc7c26df5 (branch room/ci-bench-baseline).
BASELINE_SHA256 = "d171800227907c0285813e4d0376ec79f5d135a6f85a33b137cf2f8c5d9f4b6f"

CODE_RULE = ("successful code runs: push and pull_request runs that succeeded and in which"
             " `Run npm test`, `Run cargo test --workspace` or `Run npm run build` succeeded;"
             " robot time is each job's whole time on its runner")
LEGACY_RULE = ("reconstructed: runs in which `Run npm test` lasted more than 10 s, any event or"
               " conclusion; robot time is the sum of step durations only, with"
               " `The docs-only classifier` counted as setup")

# fixtures/window, by hand (seconds unless said):
#   run 101 PR success, code run. web-build waits 60, runs 180: steps 10 setup,
#     60 + 30 build, 20 docs-only classifier, 50 setup, then 10 between steps.
#     web-test waits 240, runs 360: 30 setup, 300 npm test, 10 setup, 20
#     between. rust waits 240, runs 240: 20 setup, 180 cargo test, 30 triage
#     helper's test, 10 between. A skipped shard job never got a runner (no
#     runner, no steps), though GitHub shows it 30 s long: no robot time, no
#     waiting. Robot time 780; steps 740. Queued to done
#     00:00:00 to 00:10:00, 10 min.
#   run 102 push failure: npm test failed after 90 s, so in the reconstructed
#     cohort only. Steps 30 + 90 + 10 = 130; queued to done 2.5 min.
#   run 103 PR success, docs only: npm test skipped. In neither cohort.
#   run 104 PR success: npm test exactly 10 s (not more than 10, so not
#     reconstructed; it succeeded, so a code run). web-test waits 30, runs 60:
#     10 setup, 10 npm test, 30 setup, 10 between. rust carried over from an
#     earlier attempt (started before it was created): waits 0, runs 120: 100
#     cargo test, 20 between. Robot time 180. Queued to done 01:00:00 to
#     01:01:30, 1.5 min.
#   run 105 the nightly (schedule): in neither cohort.
#   run 106 PR cancelled: two jobs that never got a runner, one of them
#     "completed" a second before it "started", as GitHub shows such jobs.
#     In neither cohort.
# Successful code runs (101, 104): 960 s, 480 s = 8 min a run; 2 robots give
#   2 x 60 / 8 = 15 PRs an hour. Per run: setup (160 + 70) / 2 = 115 s =
#   1.9167 min; build 90 / 2 = 45 s = 0.75; rust (180 + 100) / 2 = 140 s =
#   2.3333; skills (20 + 30) / 2 = 25 s = 0.4167; web (300 + 10) / 2 = 155 s =
#   2.5833. Waiting (540 + 30) / 2 = 285 s = 4.75; running (620 + 110) / 2 =
#   365 s = 6.0833. Queued to done 10 and 1.5: median 5.75, p90 (nearest
#   rank, the 2nd of 2) 10, max 10.
# Reconstructed (101, 102): 870 s, 435 s = 7.25 min; 2 x 60 / 7.25 =
#   16.5517. Per run: setup (140 + 40) / 2 = 90 s = 1.5; build 0.75; rust
#   1.5; skills 30 / 2 = 15 s = 0.25; web (300 + 90) / 2 = 195 s = 3.25.
#   Waiting (540 + 0) / 2 = 4.5; running 690 / 2 = 345 s = 5.75. Queued to
#   done 10 and 2.5: median 6.25, p90 10, max 10.
# Merged: 3 PRs in 2 hours, 1.5 an hour.
WINDOW_POINT = {
    "schema": "closedwiz.ci-bench.v1",
    "label": "synthetic window",
    "since": "2030-01-01T00:00:00Z",
    "until": "2030-01-01T02:00:00Z",
    "hours": 2.0,
    "robots": 2,
    "runs": 6,
    "jobs": 11,
    "merged_prs": 3,
    "merged_per_hour": 1.5,
    "code_runs": {
        "rule": CODE_RULE,
        "runs": 2,
        "robot_seconds": 960,
        "robot_minutes_per_run": 8.0,
        "prs_per_hour": 15.0,
        "categories": {"web": 2.5833, "setup": 1.9167, "rust": 2.3333, "build": 0.75, "skills": 0.4167},
        "split": {"waiting": 4.75, "setup": 1.9167, "running": 6.0833},
        "queued_to_done": {"median": 5.75, "p90": 10.0, "max": 10.0},
    },
    "legacy": {
        "rule": LEGACY_RULE,
        "runs": 2,
        "robot_seconds": 870,
        "robot_minutes_per_run": 7.25,
        "prs_per_hour": 16.5517,
        "categories": {"web": 3.25, "setup": 1.5, "rust": 1.5, "build": 0.75, "skills": 0.25},
        "split": {"waiting": 4.5, "setup": 1.5, "running": 5.75},
        "queued_to_done": {"median": 6.25, "p90": 10.0, "max": 10.0},
    },
}


def run(args, env=None, cwd=None):
    full = dict(os.environ)
    full.update(env or {})
    return subprocess.run([sys.executable, "-I", str(SCRIPT)] + args, capture_output=True, text=True,
                          env=full, cwd=cwd, timeout=120)


def copy_window(tmp, name="w"):
    dest = Path(tmp) / name
    shutil.copytree(WINDOW, dest)
    return dest


def lines(path):
    return Path(path).read_text().splitlines()


class Measure(unittest.TestCase):
    def test_x5_current_job_and_step_names_are_covered(self):
        result = run(['check-steps'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r'^covered [0-9]+ CI steps')

    def test_m11_timestamp_conversion_work(self):
        # #1902's synthetic workloads. Values are worked out in the issue;
        # hashes pin every point.json byte from main at 58b70659, before the
        # optimization. Freeze its price input too; new catalog rows are additive.
        # Count parsing work, not wall time, to avoid a race.
        hashes = {0: "391860f1bd271b3d09a9be7cdee550c3cfb25bb669ab841048c380af5e84aec0",
                  1: "eb17cc2d0bf68d84f5d28d2bd11ff8b6cffecd94fab54cb59422be0d9f042cd8",
                  1000: "fa6153b62b8e501dedaeeb97fd73c6e1db03bafed96915bfd1d9d2d90758f4d3"}
        for n, distinct in ((0, False), (1, False), (1000, False), (1000, True)):
            with self.subTest(jobs=n, distinct=distinct), tempfile.TemporaryDirectory() as tmp:
                w = Path(tmp)
                jobs, waits, attempts = [], [], []
                for i in range(n):
                    def stamp(offset):
                        v = (i if distinct else 0) + offset
                        return f"2030-01-01T{v//3600:02}:{v//60%60:02}:{v%60:02}Z"
                    a, s, e = stamp(0), stamp(60), stamp(120)
                    jobs.append(dict(run=i, event="push", run_concl="success", name="web-test",
                                     conclusion="success", runner_name="synthetic", created_at=a,
                                     started_at=s, completed_at=e, steps=[dict(name="Run npm test",
                                     conclusion="success", started_at=s, completed_at=e)]))
                    waits.append(dict(created_at=a, started_at=s))
                    attempts.append(dict(run=i, attempt=1, started_at=s))
                since, until = "2030-01-01T00:00:00Z", "2030-01-02T00:00:00Z"
                (w / "window.json").write_text(json.dumps(dict(since=since, until=until)))
                (w / "merged.json").write_text("[]")
                (w / "jobs.jsonl").write_text("".join(json.dumps(j) + "\n" for j in jobs))
                (w / "factory.json").write_text(json.dumps(dict(since=since, until=until, prs=[],
                    main=dict(observations=[], carry_in=False, untimed=0), reruns=[],
                    attempts=attempts, jobs=waits)))
                spec = importlib.util.spec_from_file_location("bench_work", SCRIPT)
                bench = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(bench)
                parses = 0

                class CountedDatetime(bench.datetime):
                    @classmethod
                    def strptime(cls, *args):
                        nonlocal parses
                        parses += 1
                        return super().strptime(*args)

                bench.datetime = CountedDatetime
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = bench.main(["measure", str(w), "--robots", "2", "--label", "synthetic", "--allow-empty",
                                     "--prices", str(HERE / "fixtures/timestamp-prices.tsv")])
                self.assertEqual(rc, 0)
                raw = (w / "point.json").read_bytes()
                point = json.loads(raw)
                self.assertEqual((point["runs"], point["jobs"], point["merged_prs"]), (n, n, 0))
                self.assertEqual(point["factory"]["runner_wait_minutes"],
                                 dict(jobs=n, median=1.0 if n else None, p90=1.0 if n else None))
                self.assertEqual(point["factory"]["main_red"], dict(red_minutes=None,
                    unknown_minutes=1440.0, untimed_verdicts=0, verdicts=0))
                self.assertEqual(point["factory"]["reruns"]["attempts"], n)
                self.assertEqual([len(point["buckets"][k]) for k in ("1h", "6h")], [24, 4])
                self.assertEqual([x["ci"]["code_runs"] for x in point["buckets"]["1h"]], [n] + [0]*23)
                if n:
                    self.assertEqual(point["code_runs"]["robot_seconds"], 60*n)
                    self.assertEqual(point["code_runs"]["prs_per_hour"], 120.0)
                    self.assertEqual(point["code_runs"]["queued_to_done"], dict(median=2.0, p90=2.0, max=2.0))
                else:
                    self.assertIsNone(point["code_runs"])
                self.assertEqual(hashlib.sha256(raw).hexdigest(), hashes[n])
                expected = ["synthetic: factory: 0 merged, 0 reviewed, 0 reruns, main red unknown min"]
                if n:
                    expected += [f"synthetic: 120.0 PRs an hour of capacity on 2 robots (1.00 robot-minutes per code run,"
                                 f" {n} successful code runs); 0.0 merged an hour",
                                 f"  reconstructed rule: 120.0 PRs an hour (1.00 robot-minutes per code run, {n} runs)"]
                else:
                    expected += ["synthetic: no successful code runs; daily cost recorded"]
                self.assertEqual(out.getvalue(), "\n".join(expected) + "\n")
                if n == 1000:
                    self.assertLess(parses, 10000, "measure repeatedly reparses timestamps")

    def test_m1_window_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = copy_window(tmp)
            r = run(["measure", str(w), "--robots", "2", "--label", "synthetic window"])
            self.assertEqual(r.returncode, 0, r.stderr)
            point = json.loads((w / "point.json").read_text())
            point.pop("cost")  # #1252 additive cost record has its own public proofs.
            point.pop("buckets")  # #1359's buckets have theirs (test_factory.py B1).
            self.assertEqual(point, WINDOW_POINT)
            self.assertEqual(r.stdout.splitlines(), [
                "synthetic window: 15.0 PRs an hour of capacity on 2 robots (8.00 robot-minutes per code run,"
                " 2 successful code runs); 1.5 merged an hour",
                "  reconstructed rule: 16.6 PRs an hour (7.25 robot-minutes per code run, 2 runs)",
            ])

    def test_m8_queued_to_done_ranks(self):
        # Ten code runs, run k queued to done in k minutes: median 5.5, the
        # nearest-rank p90 the 9th of 10, 9 minutes; max 10.
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp) / "ten"
            w.mkdir()
            (w / "window.json").write_text('{"since": "2030-01-01T00:00:00Z", "until": "2030-01-01T12:00:00Z"}\n')
            (w / "merged.json").write_text("[]\n")
            rows = []
            for k in range(1, 11):
                start, end = f"2030-01-01T{k:02d}:00:00Z", f"2030-01-01T{k:02d}:{k:02d}:00Z"
                rows.append(json.dumps({"completed_at": end, "conclusion": "success", "created_at": start,
                                        "event": "pull_request", "name": "web-test", "run": k, "run_concl": "success",
                                        "runner_name": "runner-1", "started_at": start,
                                        "steps": [{"completed_at": end, "conclusion": "success", "name": "Run npm test",
                                                   "started_at": start}]}))
            (w / "jobs.jsonl").write_text("\n".join(rows) + "\n")
            r = run(["measure", str(w), "--robots", "1", "--label", "ten"])
            self.assertEqual(r.returncode, 0, r.stderr)
            point = json.loads((w / "point.json").read_text())
            self.assertEqual(point["code_runs"]["queued_to_done"], {"median": 5.5, "p90": 9.0, "max": 10.0})

    def test_m2_same_answer_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = copy_window(tmp)
            first = run(["measure", str(w), "--robots", "2", "--label", "synthetic window"])
            one = (w / "point.json").read_bytes()
            second = run(["measure", str(w), "--robots", "2", "--label", "synthetic window"])
            self.assertEqual((first.returncode, second.returncode), (0, 0))
            self.assertEqual((w / "point.json").read_bytes(), one)

    def refused(self, edit, message, code=1, args=None):
        """Apply edit(dir) to a copy of the window; measure must exit with
        code, print message on stderr, and write no point.json."""
        with tempfile.TemporaryDirectory() as tmp:
            w = copy_window(tmp)
            edit(w)
            r = run(args or ["measure", str(w), "--robots", "2", "--label", "x"])
            self.assertEqual(r.returncode, code, r.stdout + r.stderr)
            self.assertIn(message, r.stderr)
            self.assertFalse((w / "point.json").exists())

    def test_m3_unknown_step_fails_closed(self):
        # The second name differs from a row only where the row has a "."
        # (`Run ./.github/actions/docs-only`): a row's text is literal.
        for old, new, job in (("Run cargo test --workspace", "Run cargo bench", "rust"),
                              ("Set up job", "Run ./xgithub/actions/docs-only", "web-build")):
            with self.subTest(new):
                def edit(w, old=old, new=new):
                    p = w / "jobs.jsonl"
                    p.write_text(p.read_text().replace(f'"{old}"', f'"{new}"', 1))
                self.refused(edit, f"bench: step '{new}' (job {job}) matches no row of")

    def test_m3b_step_in_two_rows_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "bench"
            copy.mkdir()
            shutil.copy(SCRIPT, copy / "bench.py")
            (copy / "steps.tsv").write_text((HERE / "steps.tsv").read_text() + "web\tRun npm *\n")
            w = copy_window(tmp)
            r = subprocess.run([sys.executable, "-I", str(copy / "bench.py"), "measure", str(w), "--robots", "2",
                                "--label", "x"], capture_output=True, text=True, timeout=120)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("bench: step 'Run npm run build' (job web-build) matches 2 rows of", r.stderr)
            self.assertFalse((w / "point.json").exists())

    def test_m10_hosted_runner_setup_step(self):
        # #1359's Nov 5 backfill: jobs on the Namespace trial runner have a
        # GitHub-shown 'Set up runner' step and cache-volume mounts with
        # their post steps, all setup. #1989 adds the named fixture
        # checkout's post step. Renaming web-build's 'Set up job' to
        # each keeps every number of the window.
        for name in ("Set up runner", "Mount the cargo-rust cache volume", "Mount the npm cache volume",
                     "Mount the web-test cache volume", "Post Mount the cargo-rust cache volume",
                     "Post Mount the npm cache volume", "Post Mount the web-test cache volume",
                     "Post The reviewed live-check fixture source"):
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                w = copy_window(tmp)
                text = (w / "jobs.jsonl").read_text()
                first, rest = text.split("\n", 1)
                (w / "jobs.jsonl").write_text(first.replace('"Set up job"', json.dumps(name), 1) + "\n" + rest)
                r = run(["measure", str(w), "--robots", "2", "--label", "synthetic window"])
                self.assertEqual(r.returncode, 0, r.stderr)
                point = json.loads((w / "point.json").read_text())
                point.pop("cost"), point.pop("buckets")
                self.assertEqual(point, WINDOW_POINT)

    def test_m9_public_site_steps(self):
        # #429 (R1 on #957): main's ci.yml names two steps no row knew.
        # `Build the public static site` (web-build) is build; `Build and test
        # the public static site` (web-test) builds and tests in one step, and
        # counts as web. Each goes into one of run 101's uncovered gaps, which
        # count as setup today: web-build 00:03:50-00:04:00 (10 s) and
        # web-test 00:09:40-00:10:00 (20 s). By hand, code runs (101, 104):
        # setup (160 - 30 + 70) / 2 = 100 s = 1.6667; build (90 + 10) / 2 = 50 s
        # = 0.8333; web (300 + 20 + 10) / 2 = 165 s = 2.75; running
        # (620 + 30 + 110) / 2 = 380 s = 6.3333; robot time unchanged.
        # Reconstructed (101, 102), steps only: 870 + 30 = 900 s, 450 s = 7.5
        # min, 2 x 60 / 7.5 = 16.0; build 0.8333; web (300 + 20 + 90) / 2 =
        # 205 s = 3.4167; running (690 + 30) / 2 = 360 s = 6.0.
        added = {"web-build": ("Build the public static site", "2030-01-01T00:03:50Z", "2030-01-01T00:04:00Z"),
                 "web-test": ("Build and test the public static site", "2030-01-01T00:09:40Z",
                              "2030-01-01T00:10:00Z")}
        with tempfile.TemporaryDirectory() as tmp:
            w = copy_window(tmp)
            rows = []
            for line in lines(w / "jobs.jsonl"):
                job = json.loads(line)
                if job["run"] == 101 and job["name"] in added:
                    name, start, end = added[job["name"]]
                    job["steps"].append({"completed_at": end, "conclusion": "success", "name": name,
                                         "started_at": start})
                rows.append(json.dumps(job))
            (w / "jobs.jsonl").write_text("\n".join(rows) + "\n")
            r = run(["measure", str(w), "--robots", "2", "--label", "synthetic window"])
            self.assertEqual(r.returncode, 0, r.stderr)
            want = json.loads(json.dumps(WINDOW_POINT))
            code, legacy = want["code_runs"], want["legacy"]
            code["categories"].update({"setup": 1.6667, "build": 0.8333, "web": 2.75})
            code["split"].update({"setup": 1.6667, "running": 6.3333})
            legacy.update({"robot_seconds": 900, "robot_minutes_per_run": 7.5, "prs_per_hour": 16.0})
            legacy["categories"].update({"build": 0.8333, "web": 3.4167})
            legacy["split"].update({"running": 6.0})
            point = json.loads((w / "point.json").read_text())
            point.pop("cost")
            point.pop("buckets")
            self.assertEqual(point, want)

    def test_m9b_near_public_site_names_fail_closed(self):
        # The rows are exact names, with no wildcard: a near name is unknown.
        for old, new, job in (("Run npm run build", "Build the public static sites", "web-build"),
                              ("Run npm test", "Build and test the public static site twice", "web-test")):
            with self.subTest(new):
                def edit(w, old=old, new=new):
                    p = w / "jobs.jsonl"
                    p.write_text(p.read_text().replace(f'"{old}"', f'"{new}"', 1))
                self.refused(edit, f"bench: step '{new}' (job {job}) matches no row of")

    def test_m4_bad_jobs_refused(self):
        first = lines(WINDOW / "jobs.jsonl")[0]
        cases = {
            "repeated key": (first.replace('"run": 101,', '"run": 101, "run": 999,'), "repeated key 'run'"),
            "extra key": (first.replace('"run": 101,', '"run": 101, "attempt": 1,'), "keys"),
            "missing key": (first.replace('"runner_name": "runner-1", ', ''), "keys"),
            "run id true": (first.replace('"run": 101,', '"run": true,'), "'run' is not an integer"),
            "run id text": (first.replace('"run": 101,', '"run": "101",'), "'run' is not an integer"),
            "bad time": (first.replace('"created_at": "2030-01-01T00:00:00Z"', '"created_at": "2030-01-01 00:00"'),
                         "'created_at' is not a UTC time"),
            "bad calendar date": (first.replace('"created_at": "2030-01-01T00:00:00Z"',
                                               '"created_at": "2030-02-30T00:00:00Z"'), "'created_at' is not a UTC time"),
            "NaN": (first.replace('"run": 101,', '"run": NaN,'), "not JSON"),
            "not an object": ("[1, 2]", "not an object"),
            "step backwards": (first.replace('"started_at": "2030-01-01T00:01:10Z"', '"started_at": "2030-01-01T00:02:30Z"', 1),
                               "ends before it starts"),
            "mixed run": (first.replace('"event": "pull_request"', '"event": "push"'), "run 101 has jobs of two events"),
            "mixed conclusion": (first.replace('"run_concl": "success"', '"run_concl": "failure"'),
                                 "run 101 has jobs of two run conclusions"),
            "steps outlast job": (first.replace('"completed_at": "2030-01-01T00:03:50Z"', '"completed_at": "2030-01-01T00:04:30Z"'),
                                  "run 101 job web-build: its steps last longer than the job"),
            "runner but no steps": (first.replace('"completed_at": "2030-01-01T00:04:00Z"', '"completed_at": "2030-01-01T00:00:59Z"')
                                    .split(', "steps": [')[0] + ', "steps": []}', "job web-build ends before it starts"),
            # A job that ran (it has a runner and steps) can't end before it starts.
            "job backwards": (first.replace('"completed_at": "2030-01-01T00:04:00Z"', '"completed_at": "2030-01-01T00:00:59Z"'),
                              "job web-build ends before it starts"),
        }
        for name, (bad, message) in cases.items():
            with self.subTest(name):
                def edit(w, bad=bad):
                    rest = lines(w / "jobs.jsonl")[1:]
                    (w / "jobs.jsonl").write_text("\n".join([bad] + rest) + "\n")
                self.refused(edit, message)

    def test_m5_bad_window_or_merged_refused(self):
        cases = {
            "merged outside": ("merged.json", '[{"merged_at": "2030-01-01T02:00:00Z", "number": 7}]',
                               "PR 7 merged outside the window"),
            "merged repeated": ("merged.json", '[{"merged_at": "2030-01-01T00:15:00Z", "number": 7},'
                                ' {"merged_at": "2030-01-01T00:16:00Z", "number": 7}]', "PR 7 is listed twice"),
            "merged extra key": ("merged.json", '[{"merged_at": "2030-01-01T00:15:00Z", "number": 7, "x": 1}]', "keys"),
            "window backwards": ("window.json", '{"since": "2030-01-01T02:00:00Z", "until": "2030-01-01T00:00:00Z"}',
                                 "the window ends before it starts"),
            "window empty": ("window.json", '{"since": "2030-01-01T00:00:00Z", "until": "2030-01-01T00:00:00Z"}',
                             "the window ends before it starts"),
            "window missing": ("window.json", None, "window.json"),
        }
        for name, (file, text, message) in cases.items():
            with self.subTest(name):
                def edit(w, file=file, text=text):
                    if text is None:
                        (w / file).unlink()
                    else:
                        (w / file).write_text(text + "\n")
                self.refused(edit, message)

    def test_m6_no_code_runs_refused(self):
        def edit(w):
            keep = [line for line in lines(w / "jobs.jsonl") if '"run": 101,' not in line and '"run": 104,' not in line]
            (w / "jobs.jsonl").write_text("\n".join(keep) + "\n")
        self.refused(edit, "bench: no successful code runs in the window")

    def test_m7_bad_command_lines(self):
        for args in (["measure"], ["measure", "DIR"], ["measure", "DIR", "--robots", "0", "--label", "x"],
                     ["measure", "DIR", "--robots", "two", "--label", "x"], ["measure", "DIR", "--robots", "2"],
                     ["measure", "DIR", "--robots", "10000", "--label", "x"], ["measure", "DIR", "--robots", "2", "--label", "   "],
                     ["measure", "DIR", "--robots", "2", "--label", ""], ["weigh"], []):
            with self.subTest(args):
                with tempfile.TemporaryDirectory() as tmp:
                    w = copy_window(tmp)
                    args = [str(w) if a == "DIR" else a for a in args]
                    r = run(args)
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertIn("usage:", r.stderr)
                    self.assertFalse((w / "point.json").exists())


# The synthetic GitHub for collect: the window 2030-01-01T00:00:00Z to
# 02:00:00Z. Runs come in two pages (total 5); run 204 was created exactly
# at the window's end, which the API's range includes and the bench must
# not. Run 201's jobs come in two pages; run 205, a push cancelled before
# any job, has none (total_count 0: one read, no second page). Each run is
# read again after its jobs, and must be the attempt, status and conclusion
# the list showed (#383 R2: a rerun between the reads mixes two attempts).
SINCE, UNTIL = "2030-01-01T00:00:00Z", "2030-01-01T02:00:00Z"


def runs_call(page):
    return (f"api repos/{{owner}}/{{repo}}/actions/workflows/ci.yml/runs?created={SINCE}..{UNTIL}"
            f"&status=completed&per_page=100&page={page}")


def jobs_call(run_id, page):
    return f"api repos/{{owner}}/{{repo}}/actions/runs/{run_id}/jobs?per_page=100&page={page}"


def run_call(run_id):
    return f"api repos/{{owner}}/{{repo}}/actions/runs/{run_id}"


def pulls_call(page):
    return f"api repos/{{owner}}/{{repo}}/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100&page={page}"


CALLS = [runs_call(1), runs_call(2), jobs_call(201, 1), jobs_call(201, 2), run_call(201), jobs_call(202, 1), run_call(202),
         jobs_call(203, 1), run_call(203), jobs_call(205, 1), run_call(205), pulls_call(1), pulls_call(2)]


def gh_run(run_id, event, conclusion, created, status="completed", attempt=1):
    return {"id": run_id, "event": event, "conclusion": conclusion, "created_at": created, "status": status,
            "run_attempt": attempt, "name": "CI", "head_branch": "some-branch"}


def gh_step(name, start, end, conclusion="success"):
    return {"name": name, "status": "completed", "conclusion": conclusion, "number": 1, "started_at": start,
            "completed_at": end}


def gh_job(name, created, started, completed, runner, steps, conclusion="success"):
    return {"id": 1, "run_id": 1, "name": name, "status": "completed", "conclusion": conclusion,
            "created_at": created, "started_at": started, "completed_at": completed, "runner_name": runner,
            "labels": ["self-hosted"], "steps": steps, "run_attempt": 1}


def gh_pull(number, merged, updated):
    return {"number": number, "merged_at": merged, "updated_at": updated, "state": "closed", "title": "t"}


def world():
    t = "2030-01-01T"
    runs1 = {"total_count": 5, "workflow_runs": [gh_run(203, "schedule", "success", t + "01:59:59Z"),
                                                 gh_run(202, "push", "failure", t + "01:00:00Z"),
                                                 gh_run(205, "push", "cancelled", t + "01:30:00Z")]}
    runs2 = {"total_count": 5, "workflow_runs": [gh_run(201, "pull_request", "success", t + "00:00:00Z"),
                                                 gh_run(204, "pull_request", "success", t + "02:00:00Z")]}
    j201a = {"total_count": 2, "jobs": [gh_job("web-build", t + "00:10:00Z", t + "00:10:05Z", t + "00:12:00Z",
                                               "runner-1", [gh_step("Set up job", t + "00:10:05Z", t + "00:10:10Z")])]}
    j201b = {"total_count": 2, "jobs": [gh_job("rust", t + "00:10:00Z", t + "00:12:00Z", t + "00:15:00Z", "runner-2",
                                               [gh_step("Run cargo test --workspace", t + "00:12:00Z", t + "00:14:00Z")])]}
    j202 = {"total_count": 1, "jobs": [gh_job("web-test", t + "01:00:00Z", t + "01:00:00Z", t + "01:00:00Z", None, [],
                                              "cancelled")]}
    j203 = {"total_count": 1, "jobs": [gh_job("rust", t + "01:59:59Z", t + "02:00:10Z", t + "02:03:00Z", "runner-3",
                                              [gh_step("Run cargo test --workspace", t + "02:00:10Z", None,
                                                       None)])]}
    # Pulls, updated newest first: 100 on page 1 (numbers 1000 to 1099; 1000
    # merged in the window, 1001 merged after it, 1002 never merged, the rest
    # merged before it but updated since), then page 2: 50 merged in the
    # window, 51 updated before the window starts.
    page1 = [gh_pull(1000, t + "00:30:00Z", "2030-01-02T00:00:00Z"),
             gh_pull(1001, t + "02:00:00Z", t + "02:00:00Z"),
             gh_pull(1002, None, t + "01:30:00Z")]
    page1 += [gh_pull(n, "2029-12-31T23:00:00Z", t + "01:00:00Z") for n in range(1003, 1100)]
    page2 = [gh_pull(50, t + "00:00:00Z", t + "00:00:00Z"), gh_pull(51, "2029-12-31T22:00:00Z", "2029-12-31T23:59:59Z")]
    j205 = {"total_count": 0, "jobs": []}
    listed = {r["id"]: r for r in runs1["workflow_runs"] + runs2["workflow_runs"]}
    answers = [runs1, runs2, j201a, j201b, listed[201], j202, listed[202], j203, listed[203], j205, listed[205],
               page1, page2]
    return {call: {"stdout": json.dumps(a), "exit": 0} for call, a in zip(CALLS, answers)}


COLLECTED_JOBS = [
    '{"collected_attempt": 1, "completed_at": "2030-01-01T00:12:00Z", "conclusion": "success", "created_at": "2030-01-01T00:10:00Z",'
    ' "event": "pull_request", "id": 1, "name": "web-build", "run": 201, "run_attempt": 1, "run_concl": "success", "run_created_at": "2030-01-01T00:00:00Z", "runner_labels": ["self-hosted"], "runner_name": "runner-1",'
    ' "started_at": "2030-01-01T00:10:05Z", "steps": [{"completed_at": "2030-01-01T00:10:10Z", "conclusion":'
    ' "success", "name": "Set up job", "started_at": "2030-01-01T00:10:05Z"}]}',
    '{"collected_attempt": 1, "completed_at": "2030-01-01T00:15:00Z", "conclusion": "success", "created_at": "2030-01-01T00:10:00Z",'
    ' "event": "pull_request", "id": 1, "name": "rust", "run": 201, "run_attempt": 1, "run_concl": "success", "run_created_at": "2030-01-01T00:00:00Z", "runner_labels": ["self-hosted"], "runner_name": "runner-2",'
    ' "started_at": "2030-01-01T00:12:00Z", "steps": [{"completed_at": "2030-01-01T00:14:00Z", "conclusion":'
    ' "success", "name": "Run cargo test --workspace", "started_at": "2030-01-01T00:12:00Z"}]}',
    '{"collected_attempt": 1, "completed_at": "2030-01-01T01:00:00Z", "conclusion": "cancelled", "created_at": "2030-01-01T01:00:00Z",'
    ' "event": "push", "id": 1, "name": "web-test", "run": 202, "run_attempt": 1, "run_concl": "failure", "run_created_at": "2030-01-01T01:00:00Z", "runner_labels": ["self-hosted"], "runner_name": null,'
    ' "started_at": "2030-01-01T01:00:00Z", "steps": []}',
    '{"collected_attempt": 1, "completed_at": "2030-01-01T02:03:00Z", "conclusion": "success", "created_at": "2030-01-01T01:59:59Z",'
    ' "event": "schedule", "id": 1, "name": "rust", "run": 203, "run_attempt": 1, "run_concl": "success", "run_created_at": "2030-01-01T01:59:59Z", "runner_labels": ["self-hosted"], "runner_name": "runner-3",'
    ' "started_at": "2030-01-01T02:00:10Z", "steps": [{"completed_at": null, "conclusion": null,'
    ' "name": "Run cargo test --workspace", "started_at": "2030-01-01T02:00:10Z"}]}',
]
COLLECTED_MERGED = [{"merged_at": "2030-01-01T00:00:00Z", "number": 50},
                    {"merged_at": "2030-01-01T00:30:00Z", "number": 1000}]


class Collect(unittest.TestCase):
    def collect(self, tmp, the_world, args=None, path=None):
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        shutil.copy(FAKE_GH, bin_dir / "gh")
        (tmp / "world.json").write_text(json.dumps(the_world))
        log = tmp / "calls.log"
        log.write_text("")
        out = tmp / "out"
        env = {"PATH": path if path is not None else f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
               "FAKE_GH_WORLD": str(tmp / "world.json"), "FAKE_GH_LOG": str(log)}
        r = run(args or ["collect", "--since", SINCE, "--until", UNTIL, "--out", str(out)], env=env)
        return r, lines(log), out

    def test_c1_reads_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, calls, out = self.collect(tmp, world())
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls, CALLS)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ["jobs.jsonl", "merged.json", "window.json"])
            self.assertEqual(lines(out / "jobs.jsonl"), COLLECTED_JOBS)
            self.assertEqual(json.loads((out / "merged.json").read_text()), COLLECTED_MERGED)
            self.assertEqual(json.loads((out / "window.json").read_text()), {"since": SINCE, "until": UNTIL})
            self.assertEqual(r.stdout.splitlines(), [f"collected 4 runs, 4 jobs and 2 merged PRs into {out}"])

    def test_c2_untrusted_reads_refused(self):
        def edited(call, change):
            w = world()
            w[call] = change(w[call])
            return w

        def answer(call, value):
            return edited(call, lambda a: {"stdout": json.dumps(value) if not isinstance(value, str) else value,
                                           "exit": 0})

        r1 = json.loads(world()[runs_call(1)]["stdout"])
        j201a = json.loads(world()[jobs_call(201, 1)]["stdout"])
        r201 = json.loads(world()[run_call(201)]["stdout"])

        def rerun():
            # #383 R2: run 201 is listed as attempt 1, success; attempt 2
            # runs before its jobs are read, and its rust job fails.
            w = world()
            t = "2030-01-01T"
            w[jobs_call(201, 1)] = {"stdout": json.dumps({"total_count": 2, "jobs": [dict(
                j201a["jobs"][0], run_attempt=2, steps=[gh_step("Run npm run build", t + "00:20:05Z", t + "00:21:00Z")])]}),
                "exit": 0}
            w[jobs_call(201, 2)] = {"stdout": json.dumps({"total_count": 2, "jobs": [dict(gh_job(
                "rust", t + "00:20:00Z", t + "00:20:05Z", t + "00:25:00Z", "runner-2",
                [gh_step("Run cargo test --workspace", t + "00:20:05Z", t + "00:24:00Z", "failure")], "failure"),
                run_attempt=2)]}), "exit": 0}
            w[run_call(201)] = {"stdout": json.dumps(dict(r201, run_attempt=2, conclusion="failure")), "exit": 0}
            return w
        cases = {
            "gh fails": (edited(runs_call(1), lambda a: {"stdout": "", "exit": 1}), "gh api"),
            "not JSON": (answer(runs_call(1), '{"total_count": 5, "workflow_runs": ['), "not JSON"),
            "repeated key": (answer(runs_call(1), '{"total_count": 5, "total_count": 3, "workflow_runs": []}'),
                             "repeated key 'total_count'"),
            "over 1000": (answer(runs_call(1), dict(r1, total_count=1001)), "more than 1000 runs"),
            "short page": (answer(runs_call(2), {"total_count": 5, "workflow_runs": []}), "fewer runs than"),
            "count moved": (answer(runs_call(2), dict(json.loads(world()[runs_call(2)]["stdout"]), total_count=6)),
                            "total_count changed"),
            "too many runs": (answer(runs_call(2), {"total_count": 5, "workflow_runs": json.loads(
                world()[runs_call(2)]["stdout"])["workflow_runs"] + [gh_run(206, "push", "success", "2030-01-01T00:05:00Z")]}),
                              "more runs than total_count"),
            "run twice": (answer(runs_call(2), {"total_count": 5, "workflow_runs": r1["workflow_runs"][:2]}),
                          "listed twice"),
            "run in progress": (answer(runs_call(1), {"total_count": 5, "workflow_runs": [
                dict(r1["workflow_runs"][0], status="in_progress")] + r1["workflow_runs"][1:]}), "not completed"),
            "run id text": (answer(runs_call(1), {"total_count": 5, "workflow_runs": [
                dict(r1["workflow_runs"][0], id="203")] + r1["workflow_runs"][1:]}), "'id' is not an integer"),
            "short jobs": (answer(jobs_call(201, 2), {"total_count": 2, "jobs": []}), "fewer jobs than"),
            "job no start": (answer(jobs_call(201, 1), {"total_count": 2, "jobs": [
                {k: v for k, v in j201a["jobs"][0].items() if k != "started_at"}]}), "'started_at'"),
            "job bad time": (answer(jobs_call(201, 1), {"total_count": 2, "jobs": [
                dict(j201a["jobs"][0], completed_at="soon")]}), "'completed_at' is not a UTC time"),
            "rerun between reads": (rerun(), "run 201 changed while it was read"),
            "rerun, same conclusion": (answer(run_call(201), dict(r201, run_attempt=2)), "run 201 changed while it was read"),
            "rerun still running": (answer(run_call(201), dict(r201, run_attempt=2, status="in_progress", conclusion=None)),
                                    "run 201 changed while it was read"),
            "conclusion changed": (answer(run_call(201), dict(r201, conclusion="failure")), "run 201 changed while it was read"),
            "re-read fails": (edited(run_call(201), lambda a: {"stdout": "", "exit": 1}), "gh api"),
            "re-read another run": (answer(run_call(201), dict(r201, id=999)), "run 201 read again is run 999"),
            "attempt text": (answer(runs_call(1), {"total_count": 5, "workflow_runs": [
                dict(r1["workflow_runs"][0], run_attempt="1")] + r1["workflow_runs"][1:]}),
                             "'run_attempt' is not an integer"),
            "pulls fail": (edited(pulls_call(2), lambda a: {"stdout": "", "exit": 1}), "gh api"),
            "pull bad merge": (answer(pulls_call(2), [gh_pull(50, "yesterday", "2030-01-01T00:00:00Z")]),
                               "'merged_at' is not a UTC time"),
        }
        for name, (the_world, message) in cases.items():
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as tmp:
                    r, _, out = self.collect(tmp, the_world)
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn(message, r.stderr)
                    self.assertIn("bench: nothing written", r.stderr)
                    self.assertFalse(out.exists())

    def test_c3_no_gh(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, calls, out = self.collect(tmp, world(), path=str(Path(tmp) / "nowhere"))
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn("bench: gh is not on PATH", r.stderr)
            self.assertFalse(out.exists())

    def test_c4_bad_command_lines_make_no_call(self):
        for args in (["collect", "--until", UNTIL, "--out", "o"], ["collect", "--since", UNTIL, "--until", SINCE, "--out", "o"],
                     ["collect", "--since", SINCE, "--until", SINCE, "--out", "o"],
                     ["collect", "--since", "2030-01-01", "--until", UNTIL, "--out", "o"],
                     ["collect", "--since", SINCE, "--until", UNTIL]):
            with self.subTest(args):
                with tempfile.TemporaryDirectory() as tmp:
                    r, calls, _ = self.collect(tmp, world(), args=args)
                    self.assertEqual(r.returncode, 2, r.stderr)
                    self.assertIn("usage:", r.stderr)
                    self.assertEqual(calls, [])


# The dataviz skill's dark categorical steps, validated against GitHub's dark
# page #0d1117 (#1331; private/evidence/ci-bench-charts/palette-validation.log).
PALETTE = {"#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9"}
# GitHub's dark page and its text tokens; white only inside a filled segment.
DARK_SURFACE = "#0d1117"
DARK_TEXT = {"#f0f6fc", "#9198a1", "#7d8590", "#ffffff"}


def measured(tmp, name, robots, label):
    w = copy_window(tmp, name)
    r = run(["measure", str(w), "--robots", str(robots), "--label", label])
    assert r.returncode == 0, r.stderr
    return w


def titles(svg):
    return re.findall(r"<title>([^<]*)</title>", svg)


class Chart(unittest.TestCase):
    def test_k1_prs_per_hour_first_against_the_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = measured(tmp, "base", 2, "synthetic baseline")
            after = measured(tmp, "after", 4, "synthetic after")
            out = Path(tmp) / "charts"
            r = run(["chart", "--baseline", str(base), str(after), "--out", str(out)])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(sorted(p.name for p in out.iterdir()),
                             ["bench.md", "prs-per-hour.svg", "robot-minutes.svg", "time-split.svg"])
            md = (out / "bench.md").read_text()
            self.assertEqual(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", md),
                             ["prs-per-hour.svg", "robot-minutes.svg", "time-split.svg"])
            # 4 robots: 4 x 60 / 8 = 30 PRs an hour.
            self.assertIn("| synthetic baseline | 2030-01-01T00:00:00Z to 2030-01-01T02:00:00Z | 2 | 16.55 | 15.00 |"
                          " 1.50 (3 in 2.0 h) |", md)
            self.assertIn("| synthetic after | 2030-01-01T00:00:00Z to 2030-01-01T02:00:00Z | 4 | – | 30.00 |"
                          " 1.50 (3 in 2.0 h) |", md)
            self.assertIn("| synthetic baseline | reconstructed | 2 | 7.25 | 3.25 | 1.50 | 1.50 | 0.75 | 0.25 |", md)
            self.assertIn("| synthetic baseline | successful code runs | 2 | 8.00 | 2.58 | 1.92 | 2.33 | 0.75 | 0.42 |", md)
            self.assertIn("| synthetic after | successful code runs | 2 | 8.00 | 2.58 | 1.92 | 2.33 | 0.75 | 0.42 |", md)
            self.assertIn("| synthetic baseline | successful code runs | 4.75 | 1.92 | 6.08 | 5.75 | 10.00 | 10.00 |", md)
            self.assertIn("| synthetic baseline | reconstructed | 4.50 | 1.50 | 5.75 | 6.25 | 10.00 | 10.00 |", md)

            prs = (out / "prs-per-hour.svg").read_text()
            self.assertEqual(titles(prs)[1:], [
                "synthetic baseline, capacity, reconstructed rule: 16.6 PRs an hour",
                "synthetic baseline, capacity, successful code runs: 15.0 PRs an hour",
                "synthetic baseline, merged: 1.5 PRs an hour",
                "synthetic after, capacity, successful code runs: 30.0 PRs an hour",
                "synthetic after, merged: 1.5 PRs an hour",
                "10x the baseline: 165.5 PRs an hour",
            ])
            labels = re.findall(r'<text class="value"[^>]*>([^<]*)</text>', prs)
            self.assertEqual(labels, ["16.6", "15.0", "1.5", "30.0", "1.5"])
            for legend in ("Capacity, reconstructed rule (baseline)", "Capacity, successful code runs", "Merged"):
                self.assertIn(f">{legend}</text>", prs)

            minutes = (out / "robot-minutes.svg").read_text()
            totals = re.findall(r'<text class="value"[^>]*>([^<]*)</text>', minutes)
            self.assertEqual(totals, ["7.25", "8.00", "8.00"])
            self.assertIn("synthetic baseline, reconstructed rule, Web tests: 3.25 robot-minutes", titles(minutes))
            split = (out / "time-split.svg").read_text()
            self.assertIn("synthetic after, successful code runs, Waiting: 4.75 minutes", titles(split))
            # Each mark's colour follows its series, and each legend lists
            # its series in order.
            def marks(svg):
                return {t.split(": ")[0].split(", ", 1)[1]: c for t, c in
                        re.findall(r'<g><title>([^<]*)</title><path d="[^"]*" fill="(#[0-9a-f]{6})"/>', svg)}

            def legend(svg):
                return re.findall(r'width="10" height="10" rx="2" fill="(#[0-9a-f]{6})"/>\n<text[^>]*>([^<]*)</text>', svg)
            self.assertEqual(marks(prs), {"capacity, reconstructed rule": "#199e70",
                                          "capacity, successful code runs": "#3987e5", "merged": "#d95926"})
            self.assertEqual(legend(prs), [("#199e70", "Capacity, reconstructed rule (baseline)"),
                                           ("#3987e5", "Capacity, successful code runs"), ("#d95926", "Merged")])
            self.assertEqual(marks(minutes), {
                "reconstructed rule, Web tests": "#3987e5", "reconstructed rule, Setup and teardown": "#d95926",
                "reconstructed rule, Rust tests": "#199e70", "reconstructed rule, Build, lint, typecheck": "#c98500",
                "reconstructed rule, Skill tests": "#d55181",
                "successful code runs, Web tests": "#3987e5", "successful code runs, Setup and teardown": "#d95926",
                "successful code runs, Rust tests": "#199e70", "successful code runs, Build, lint, typecheck": "#c98500",
                "successful code runs, Skill tests": "#d55181"})
            self.assertEqual([n for _, n in legend(minutes)],
                             ["Web tests", "Setup and teardown", "Rust tests", "Build, lint, typecheck", "Skill tests"])
            self.assertEqual(marks(split), {
                "reconstructed rule, Waiting": "#9085e9", "reconstructed rule, Setup": "#d95926",
                "reconstructed rule, Running": "#199e70", "successful code runs, Waiting": "#9085e9",
                "successful code runs, Setup": "#d95926", "successful code runs, Running": "#199e70"})
            self.assertEqual([n for _, n in legend(split)], ["Waiting", "Setup", "Running"])
            for svg in (prs, minutes, split):
                fills = set(re.findall(r'fill="(#[0-9a-f]{6})"', svg)) - {DARK_SURFACE} - DARK_TEXT
                self.assertTrue(fills, "no data marks")
                self.assertLessEqual(fills, PALETTE)

    def test_k2_the_baseline_is_the_first_point_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            after = measured(tmp, "after", 4, "synthetic after")
            out = Path(tmp) / "charts"
            r = run(["chart", str(after), "--out", str(out)])
            self.assertEqual(r.returncode, 0, r.stderr)
            got = titles((out / "prs-per-hour.svg").read_text())
            self.assertTrue(got[1].startswith("2026-11-01 baseline, capacity, reconstructed rule: 17.4 PRs an hour"),
                            got[1])
            self.assertTrue(got[-1].startswith("10x the baseline: 174.0"), got[-1])

    def test_k3_bad_point_refused(self):
        cases = {
            "schema": (lambda p: dict(p, schema="closedwiz.ci-bench.v0"), "schema"),
            "no hours": (lambda p: {k: v for k, v in p.items() if k != "hours"}, "keys"),
            "hours text": (lambda p: dict(p, hours="2"), "'hours' is not a number"),
            "robots text": (lambda p: dict(p, robots="4"), "'robots' is not an integer"),
            "no split": (lambda p: dict(p, code_runs={k: v for k, v in p["code_runs"].items() if k != "split"}), "keys"),
            "category missing": (lambda p: dict(p, code_runs=dict(p["code_runs"], categories={"web": 1.0})), "keys"),
            "legacy wrong": (lambda p: dict(p, legacy=[]), "'legacy'"),
        }
        for name, (edit, message) in cases.items():
            with self.subTest(name):
                with tempfile.TemporaryDirectory() as tmp:
                    after = measured(tmp, "after", 4, "synthetic after")
                    p = after / "point.json"
                    p.write_text(json.dumps(edit(json.loads(p.read_text()))))
                    out = Path(tmp) / "charts"
                    r = run(["chart", str(after), "--out", str(out)])
                    self.assertEqual(r.returncode, 1, r.stderr)
                    self.assertIn(message, r.stderr)
                    self.assertNotIn("Traceback", r.stderr)
                    self.assertFalse(out.exists())


def daily_windows(tmp, minutes, capacity):
    """Full PST days from 2030-07-01, each with a hand-chosen median and capacity."""
    out = []
    for i, (m, c) in enumerate(zip(minutes, capacity)):
        day = i + 1
        w = copy_window(tmp, f"day{day}")
        r = run(["measure", str(w), "--robots", "5", "--label", f"2030-07-{day:02d} PST"])
        assert r.returncode == 0, r.stderr
        point = json.loads((w / "point.json").read_text())
        point.update(since=f"2030-07-{day:02d}T08:00:00Z", until=f"2030-07-{day + 1:02d}T08:00:00Z", hours=24,
                     latency_basis="workflow created to last job completed")
        point["code_runs"]["queued_to_done"]["median"] = m
        point["code_runs"]["prs_per_hour"] = c
        (w / "point.json").write_text(json.dumps(point))
        out.append(w)
    return out


def texts(svg, cls):
    return re.findall(rf'<text class="{cls}"[^>]*>([^<]*)</text>', svg)


class DarkCharts(unittest.TestCase):
    """#1331, Jake's pick B: GitHub-dark charts with no scales, every value labelled,
    the two headline numbers first. Expected values are worked by hand below."""

    def dashboard(self, tmp, minutes, capacity):
        out = Path(tmp) / "dashboard"
        r = run(["dashboard", *map(str, daily_windows(tmp, minutes, capacity)), "--out", str(out)])
        self.assertEqual(r.returncode, 0, r.stderr)
        return out

    def test_d1_every_chart_is_dark_with_dark_text_and_dark_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.dashboard(tmp, [12.0, 20.0, 30.0], [24.0, 22.0, 9.0])
            for name in ("daily-metrics.svg", "prs-per-hour.svg", "robot-minutes.svg", "time-split.svg",
                         "minutes-per-pr.svg"):
                with self.subTest(name):
                    svg = (out / name).read_text()
                    self.assertRegex(svg, r'<title>[^<]*</title>\n<rect width="820" height="\d+" fill="#0d1117"/>')
                    self.assertNotIn("#fcfcfb", svg)
                    self.assertLessEqual(set(re.findall(r'<text[^>]* fill="(#[0-9a-f]{6})"', svg)), DARK_TEXT)
                    marks = set(re.findall(r'<(?:path|circle|rect x)[^>]* fill="(#[0-9a-f]{6})"', svg))
                    self.assertTrue(marks)
                    self.assertLessEqual(marks - {"#0d1117"}, PALETTE)

    def test_d2_no_scales_only_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.dashboard(tmp, [12.0, 20.0, 30.0], [24.0, 22.0, 9.0])
            for name in ("daily-metrics.svg", "prs-per-hour.svg", "robot-minutes.svg", "time-split.svg",
                         "minutes-per-pr.svg"):
                with self.subTest(name):
                    svg = (out / name).read_text()
                    self.assertNotIn('class="tick"', svg)
                    self.assertNotIn("#21262d", svg)  # no gridlines
            daily = (out / "daily-metrics.svg").read_text()
            # Every day carries its value: minutes panel, then capacity panel.
            self.assertEqual(texts(daily, "value"), ["12.0", "20.0", "30.0", "24.0", "22.0", "9.0"])
            for day in ("Mon Jul 1", "Tue Jul 2", "Wed Jul 3"):
                self.assertEqual(daily.count(f">{day}</text>"), 4)
            self.assertEqual(texts((out / "minutes-per-pr.svg").read_text(), "value")[-1], "30.0")

    def test_d3_the_two_big_numbers_come_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = (self.dashboard(tmp, [12.0, 20.0, 30.0], [24.0, 22.0, 9.0]) / "daily-metrics.svg").read_text()
            self.assertEqual(texts(daily, "hero"), ["30.0", "9.0"])
            self.assertIn('font-size="52"', daily.split('class="hero"', 1)[1].split(">", 1)[0])
            self.assertLess(daily.index('class="hero"'), daily.index('class="metric-point"'))
            # 30.0 - 20.0 = 10.0 more minutes (worse); 9.0 - 22.0 = 13.0 fewer PRs (worse).
            self.assertIn('Wed Jul 3 · <tspan fill="#ec835a">▲</tspan> 10.0 worse than Tue', daily)
            self.assertIn('Wed Jul 3 · <tspan fill="#ec835a">▼</tspan> 13.0 worse than Tue', daily)
            self.assertIn(">Tonight's goal: under 10 · 20.0 to go<", daily)
            self.assertIn(">Tonight's goal: 25+ · 16.0 to go<", daily)

    def test_d4_each_axis_fits_its_own_values_and_goals_off_scale_are_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            daily = (self.dashboard(tmp, [12.0, 20.0, 30.0], [24.0, 22.0, 9.0]) / "daily-metrics.svg").read_text()
            # Plot y 228 (top) to 408 (zero), 180 px. Minutes: 30 x 1.08 = 32.4 -> axis end 40,
            # so 30 sits at 408 - 180 x 30/40 = 273 and tonight's 10 at 363.
            # Capacity: 24 x 1.08 = 25.92 -> axis end 30: 24 at 264, 9 at 354, tonight's 25 at 258.
            cys = re.findall(r'class="metric-point"><title>[^<]*</title><circle cx="([\d.]+)" cy="([\d.]+)"', daily)
            # Minutes 12, 20, 30 -> 354, 318, 273; capacity 24, 22, 9 -> 264, 276, 354.
            self.assertEqual([y for _, y in cys], ["354.0", "318.0", "273.0", "264.0", "276.0", "354.0"])
            goals = re.findall(r'<line class="goal-line"[^>]* y1="([\d.]+)"[^>]*><title>([^<]*)</title>', daily)
            self.assertEqual(goals, [("363.0", "Tonight: 10 min"), ("258.0", "Tonight: 25 PRs/hour")])
            self.assertIn(">then this week 3, north star 1 min<", daily)
            self.assertIn(">then this week 80, north star 500 PRs/hour<", daily)
        with tempfile.TemporaryDirectory() as tmp:
            # Capacity 6, 7, 8: 8 x 1.08 = 8.64 -> axis end 10, so tonight's 25 is off scale too.
            daily = (self.dashboard(tmp, [12.0, 20.0, 30.0], [6.0, 7.0, 8.0]) / "daily-metrics.svg").read_text()
            goals = re.findall(r'<line class="goal-line"[^>]*><title>([^<]*)</title>', daily)
            self.assertEqual(goals, ["Tonight: 10 min"])
            self.assertIn(">off scale: tonight 25, this week 80, north star 500 PRs/hour<", daily)
            self.assertEqual(re.findall(r'cy="([\d.]+)"', daily)[-1], "264.0")  # 408 - 180 x 8/10

    def test_d5_prs_an_hour_fits_its_bars_not_the_10x_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = measured(tmp, "base", 2, "synthetic baseline")
            after = measured(tmp, "after", 4, "synthetic after")
            out = Path(tmp) / "charts"
            r = run(["chart", "--baseline", str(base), str(after), "--out", str(out)])
            self.assertEqual(r.returncode, 0, r.stderr)
            prs = (out / "prs-per-hour.svg").read_text()
            # Largest bar 30.0: 30 x 1.08 = 32.4 -> axis end 40. Bars run x 170..760 (590 px),
            # so 30.0 ends at 170 + 590 x 30/40 = 612.5 and its label starts 6 px later.
            labels = re.findall(r'<text class="value" x="([\d.]+)"[^>]*>([^<]*)</text>', prs)
            self.assertIn(("618.5", "30.0"), labels)
            self.assertIn(">10× the baseline: 165.5 an hour, off scale →<", prs)


class DarkChartsReview(unittest.TestCase):
    """#1439 review R1, R2 and R4 on the B charts. Expected values worked by hand."""

    def test_r1_an_all_zero_daily_series_draws_on_the_zero_line(self):
        # Zero minutes with positive capacity, then the reverse: no division by a zero range;
        # the zero points sit on the zero line at y=408.
        for minutes, capacity, zero_panel in (([0.0, 0.0], [5.0, 6.0], 0), ([5.0, 6.0], [0.0, 0.0], 1)):
            with self.subTest(minutes=minutes, capacity=capacity):
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "dashboard"
                    r = run(["dashboard", *map(str, daily_windows(tmp, minutes, capacity)), "--out", str(out)])
                    self.assertEqual(r.returncode, 0, r.stderr)
                    self.assertNotIn("Traceback", r.stderr)
                    daily = (out / "daily-metrics.svg").read_text()
                    cys = re.findall(r'class="metric-point"><title>[^<]*</title><circle cx="[\d.]+" cy="([\d.]+)"', daily)
                    self.assertEqual(cys[2 * zero_panel:2 * zero_panel + 2], ["408.0", "408.0"])
                    self.assertEqual(texts(daily, "hero")[zero_panel], "0.0")

    def test_r2_tonights_goal_is_met_only_strictly_under_the_latency_and_at_or_over_the_capacity(self):
        # Latency: under 10 means < 10, so exactly 10 is not met. Capacity: 25+ means >= 25.
        cases = [(9.9, 25.0, "under 10 · met", "25+ · met"),
                 (10.0, 24.99, "under 10 · not yet", "25+ · not yet"),
                 (10.5, 24.9, "under 10 · 0.5 to go", "25+ · 0.1 to go")]
        for minutes, capacity, latency_text, capacity_text in cases:
            with self.subTest(minutes=minutes, capacity=capacity):
                with tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp) / "dashboard"
                    r = run(["dashboard", *map(str, daily_windows(tmp, [minutes], [capacity])), "--out", str(out)])
                    self.assertEqual(r.returncode, 0, r.stderr)
                    daily = (out / "daily-metrics.svg").read_text()
                    self.assertIn(f">Tonight's goal: {latency_text}<", daily)
                    self.assertIn(f">Tonight's goal: {capacity_text}<", daily)

    def test_r4_text_without_its_own_fill_inherits_the_dark_ink(self):
        # Only the baseline, no daily windows: every chart, including the factory and bucket
        # empty states, takes the dark ink from its root, never the default black.
        with tempfile.TemporaryDirectory() as tmp:
            base = measured(tmp, "base", 2, "synthetic baseline")
            out = Path(tmp) / "dashboard"
            r = run(["dashboard", "--baseline", str(base), "--out", str(out)])
            self.assertEqual(r.returncode, 0, r.stderr)
            svgs = sorted(out.glob("*.svg"))
            self.assertGreaterEqual(len(svgs), 5)
            unstyled = 0
            for path in svgs:
                with self.subTest(path.name):
                    svg = path.read_text()
                    unstyled += len(re.findall(r"<text(?![^>]*\bfill=)[^>]*>", svg))
                    self.assertIn('fill="#f0f6fc"', svg.split(">", 1)[0])
            self.assertGreater(unstyled, 0)  # the empty states this guards are really there


class Baseline(unittest.TestCase):
    """CS1 on the 2026-11-01 baseline's recorded jobs.jsonl."""

    def test_b1_reproduces_the_baseline(self):
        jobs = BASELINE / "jobs.jsonl"
        self.assertEqual(hashlib.sha256(jobs.read_bytes()).hexdigest(), BASELINE_SHA256)
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp) / "baseline"
            w.mkdir()
            for name in ("jobs.jsonl", "merged.json", "window.json"):
                shutil.copy(BASELINE / name, w / name)
            r = run(["measure", str(w), "--robots", "3", "--label", "2026-11-01 baseline"])
            self.assertEqual(r.returncode, 0, r.stderr)
            point = json.loads((w / "point.json").read_text())
            timing = dict(point)
            timing.pop("cost")
            timing.pop("buckets")
            self.assertEqual(json.loads((BASELINE / "point.json").read_text()), timing)
        legacy, code = point["legacy"], point["code_runs"]
        # bench.json at 934fc91: 93 runs, total 10.34, per_run, wall_med 8.7.
        self.assertEqual((legacy["runs"], legacy["robot_seconds"]), (93, 57718))
        self.assertEqual(round(legacy["robot_minutes_per_run"], 2), 10.34)
        self.assertEqual({k: round(v, 2) for k, v in legacy["categories"].items()},
                         {"setup": 2.86, "build": 0.46, "rust": 2.09, "skills": 0.18, "web": 4.75})
        self.assertEqual(round(legacy["queued_to_done"]["median"], 1), 8.7)
        # The ticket: "about 17 PRs an hour of capacity" on three robots.
        self.assertEqual(round(legacy["prs_per_hour"], 1), 17.4)
        # #332, the orchestrator's answer: 95 runs, 59,091 s, 10.37 (10.366842), 17.36 (180 / 10.366842 = 17.3631).
        self.assertEqual((code["runs"], code["robot_seconds"]), (95, 59091))
        self.assertEqual(code["robot_minutes_per_run"], 10.3668)
        self.assertEqual(code["prs_per_hour"], 17.3631)
        self.assertEqual((point["runs"], point["jobs"], point["robots"]), (145, 437, 3))


# Selector escapes (#1264): `escapes` on the fake gh, then `measure` and
# `dashboard`. The window is fixtures/window's; every count is by hand. Each
# CI attempt belongs to the window it started in, as the rerun bench's do: a
# run of the 30 days before can have a failed attempt in the window (R3 on
# #1705), so main's runs are listed a day at a time over those days too.
ES, EU = "2030-01-01T00:00:00Z", "2030-01-01T02:00:00Z"
BOT = "github-actions[bot]"
DAY = 86400


def utc_at(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def at_secs(text):
    return calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ"))


def day_edges(since, until):
    s = at_secs(since)
    return [utc_at(s - DAY * d) for d in range(30, 0, -1)] + [since, until]


def main_list(a, b):
    return f"api repos/{{owner}}/{{repo}}/actions/workflows/ci.yml/runs?branch=main&created={a}..{b}&per_page=100&page=1"


def main_lists(since, until):
    edges = day_edges(since, until)
    return [main_list(a, b) for a, b in zip(edges, edges[1:])]


def finders_call(since, until):
    return ("api repos/{owner}/{repo}/actions/workflows/ci-escapes.yml/runs?event=workflow_run"
            f"&created={since}..{utc_at(at_secs(until) + DAY)}&per_page=100&page=1")


def issues_call(since):
    return f"api repos/{{owner}}/{{repo}}/issues?state=all&since={since}&per_page=100&page=1"


def attempt_call(rid, k):
    return f"api repos/{{owner}}/{{repo}}/actions/runs/{rid}/attempts/{k}"


def main_ci(rid, event, conclusion, created="2030-01-01T00:30:00Z", status="completed", branch="main", attempt=1,
            started=None, updated=None):
    return {"id": rid, "event": event, "conclusion": conclusion, "created_at": created, "status": status,
            "run_attempt": attempt, "name": "CI", "head_branch": branch, "run_started_at": started or created,
            "updated_at": updated or started or created}


def finder(rid, ci, conclusion, status="completed", attempt=1):
    return {"id": rid, "display_title": f"Selector escapes in CI run {ci} attempt {attempt}", "status": status,
            "conclusion": conclusion, "event": "workflow_run"}


def marked(user, run, pr, test, n=1, attempt=1):
    return {"number": n, "user": {"login": user},
            "body": f"<!-- openwiz.ci-escape.v1 run={run} attempt={attempt} pr={pr} test={test} -->\nA synthetic escape."}


def escape_world(ci=None, finders=None, issues=None, attempts=None, since=ES, until=EU):
    """main's runs, each listed on the day it was created; each earlier
    attempt ((run, k): attempt) readable; the finder's runs; the issues."""
    ci = ci if ci is not None else [
        main_ci(301, "push", "success"),
        main_ci(302, "schedule", "failure"),
        main_ci(303, "push", "failure"),
        main_ci(304, "pull_request", "failure"),                       # not a full run
        main_ci(305, "push", "failure", branch="release-0.0.14"),      # not main
        main_ci(306, "push", "failure", created=until),                # the window's end is outside it
    ]
    finders = finders if finders is not None else [
        finder(401, 302, "success"), finder(402, 303, "failure"), finder(403, 303, "success"),
        finder(404, 301, "skipped")]
    issues = issues if issues is not None else [
        marked(BOT, 302, 910, "rust:test:messaging", 1),
        marked(BOT, 303, 911, "rust:test:web-api", 2),
        marked(BOT, 302, 910, "rust:test:messaging", 3),     # the same escape twice: once
        marked("someone", 302, 912, "rust:test:checks", 4),  # not the finder's
        marked(BOT, 299, 913, "rust:test:proof", 5),         # another window's run
        marked(BOT, 302, 914, "rust:test:fleet", 6, attempt=2),  # an attempt that never ran
        {"number": 7, "user": {"login": BOT}, "body": None},
    ]
    answers = {finders_call(since, until): {"total_count": len(finders), "workflow_runs": finders},
               issues_call(since): issues}
    edges = day_edges(since, until)
    for a, b in zip(edges, edges[1:]):
        # The API's range includes its end.
        day = [r for r in ci if at_secs(a) <= at_secs(r["created_at"]) <= at_secs(b)]
        answers[main_list(a, b)] = {"total_count": len(day), "workflow_runs": day}
    for (rid, k), a in (attempts or {}).items():
        answers[attempt_call(rid, k)] = a
    return {k: {"stdout": json.dumps(v), "exit": 0} for k, v in answers.items()}


def attempt(rid, k, conclusion, started):
    return {"id": rid, "run_attempt": k, "status": "completed", "conclusion": conclusion, "run_started_at": started}


class Escapes(unittest.TestCase):
    def escapes(self, tmp, the_world, since=ES, until=EU, name="w"):
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        shutil.copy(FAKE_GH, bin_dir / "gh")
        (tmp / "world.json").write_text(json.dumps(the_world))
        log = tmp / "calls.log"
        log.write_text("")
        w = copy_window(tmp, name)
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_WORLD": str(tmp / "world.json"),
               "FAKE_GH_LOG": str(log)}
        r = run(["escapes", "--since", since, "--until", until, "--out", str(w)], env=env)
        return r, lines(log), w

    def facts(self, w):
        return json.loads((w / "escapes.json").read_text())

    def point(self, w):
        r = run(["measure", str(w), "--robots", "2", "--label", "synthetic window"])
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads((w / "point.json").read_text()), r.stdout

    def day_row(self, tmp, w):
        base = copy_window(tmp, "base")
        self.assertEqual(run(["measure", str(base), "--robots", "2", "--label", "base"]).returncode, 0)
        out = Path(tmp) / "dash"
        r = run(["dashboard", str(w), "--baseline", str(base), "--out", str(out)])
        self.assertEqual(r.returncode, 0, r.stderr)
        readme = lines(out / "README.md")
        self.assertIn("| Window | UTC bounds (PST = UTC−08:00) | Robots | Code runs | Minutes/PR | Capacity/hour |"
                      " Merged/hour | Cost/code run | Window cost | Selector escapes |", readme)
        rows = [line for line in readme if line.startswith(f"| synthetic window | {ES} ")]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def test_e1_counts_each_reported_escape_of_the_windows_failed_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, calls, w = self.escapes(tmp, escape_world())
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls, main_lists(ES, EU) + [finders_call(ES, EU), issues_call(ES)])
            self.assertEqual(len(calls), 33)
            # Full-run attempts started in the window: 301, 302, 303 (each
            # attempt 1). Failed: 302, 303; their finders' newest runs (401,
            # 403) passed. Escapes: issues 1 and 2 (3 repeats 1).
            self.assertEqual(self.facts(w), {
                "since": ES, "until": EU, "attempts": 3, "failed_attempts": [[302, 1], [303, 1]],
                "escapes": [[302, 1, 910, "rust:test:messaging"], [303, 1, 911, "rust:test:web-api"]], "unknown": []})
            point, out = self.point(w)
            self.assertEqual(point["escapes"], {"count": 2, "attempts": 3, "failed_attempts": 2, "unknown": 0})
            self.assertIn("synthetic window: selector escapes 2", out)
            self.assertTrue(self.day_row(tmp, w).endswith(" | 2 |"))

    def test_e1b_an_escape_counts_once_on_the_day_its_attempt_started(self):
        # R3 on #1705: run 290, created on Dec 29, passed then; its second
        # attempt started in Jan 1's window, failed, and its finder reported
        # one escape. Jan 1 counts it; Dec 29 knows 0; neither is unknown.
        run_290 = main_ci(290, "push", "failure", created="2029-12-29T09:00:00Z", attempt=2,
                          started="2030-01-01T00:40:00Z", updated="2030-01-01T01:00:00Z")
        first = {(290, 1): attempt(290, 1, "success", "2029-12-29T09:00:00Z")}
        found = [marked(BOT, 290, 915, "rust:test:service", 8, attempt=2)]
        with tempfile.TemporaryDirectory() as tmp:
            r, calls, w = self.escapes(tmp, escape_world(ci=[run_290], attempts=first, issues=found,
                                                         finders=[finder(405, 290, "success", attempt=2)]))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls, main_lists(ES, EU) + [attempt_call(290, 1), finders_call(ES, EU), issues_call(ES)])
            self.assertEqual(self.facts(w)["escapes"], [[290, 2, 915, "rust:test:service"]])
            self.assertEqual(self.point(w)[0]["escapes"]["count"], 1)
        dec29, dec30 = "2029-12-29T08:00:00Z", "2029-12-30T08:00:00Z"
        with tempfile.TemporaryDirectory() as tmp:
            r, calls, w = self.escapes(tmp, escape_world(ci=[run_290], attempts=first, issues=found, since=dec29,
                                                         until=dec30, finders=[finder(405, 290, "success", attempt=2)]),
                                       since=dec29, until=dec30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls, main_lists(dec29, dec30) + [attempt_call(290, 1)])
            e = self.facts(w)
            self.assertEqual((e["attempts"], e["failed_attempts"], e["escapes"], e["unknown"]), (1, [], [], []))
        with tempfile.TemporaryDirectory() as tmp:
            # Without its finder run, the second attempt leaves Jan 1 unknown.
            r, _, w = self.escapes(tmp, escape_world(ci=[run_290], attempts=first, issues=found, finders=[]))
            self.assertEqual(self.facts(w)["unknown"], ["CI run 290 attempt 2 failed, and no escape finder ran for it"])

    def test_e1c_only_a_success_or_a_cancel_needs_no_finder(self):
        for conclusion in ("timed_out", None, "action_required", "startup_failure"):
            with self.subTest(conclusion), tempfile.TemporaryDirectory() as tmp:
                r, _, w = self.escapes(tmp, escape_world(ci=[main_ci(301, "push", conclusion)]))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(self.facts(w)["unknown"], [f"CI run 301 attempt 1 on main ended {conclusion}: not judged"])
        with tempfile.TemporaryDirectory() as tmp:
            # A cancel tested nothing; the next full run tests the same commits.
            r, calls, w = self.escapes(tmp, escape_world(ci=[main_ci(301, "push", "cancelled")]))
            self.assertEqual((r.returncode, calls), (0, main_lists(ES, EU)), r.stderr)
            self.assertEqual(self.facts(w)["unknown"], [])

    def test_e1d_only_an_issues_first_line_is_its_marker(self):
        quoted = marked(BOT, 302, 910, "rust:test:messaging", 1)
        quoted["body"] += "\n- `` <!-- openwiz.ci-escape.v1 run=303 attempt=1 pr=911 test=rust:test:web-api --> ``"
        with tempfile.TemporaryDirectory() as tmp:
            r, _, w = self.escapes(tmp, escape_world(issues=[quoted]))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(self.facts(w)["escapes"], [[302, 1, 910, "rust:test:messaging"]])

    def test_e2_no_failed_attempt_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, calls, w = self.escapes(tmp, escape_world(ci=[main_ci(301, "push", "success"),
                                                             main_ci(302, "schedule", "success")]))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(calls, main_lists(ES, EU))
            point, _ = self.point(w)
            self.assertEqual(point["escapes"], {"count": 0, "attempts": 2, "failed_attempts": 0, "unknown": 0})
            self.assertTrue(self.day_row(tmp, w).endswith(" | 0 |"))

    def test_e3_unknown_is_unknown_never_zero(self):
        cases = {
            "the finder failed": (escape_world(finders=[finder(401, 302, "success"), finder(402, 303, "failure")]),
                                  "the escape finder for CI run 303 attempt 1 is completed, failure: unknown"),
            "no finder ran": (escape_world(finders=[finder(401, 302, "success")]),
                              "CI run 303 attempt 1 failed, and no escape finder ran for it"),
            "the finder still runs": (escape_world(finders=[finder(401, 302, "success"),
                                                            finder(403, 303, None, status="in_progress")]),
                                      "the escape finder for CI run 303 attempt 1 is in_progress, None: unknown"),
            "a full run still runs": (escape_world(ci=[main_ci(301, "push", None, status="in_progress")]),
                                      "CI run 301 attempt 1 on main is still in_progress"),
        }
        for what, (the_world, why) in cases.items():
            with self.subTest(what), tempfile.TemporaryDirectory() as tmp:
                r, _, w = self.escapes(tmp, the_world)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(why, self.facts(w)["unknown"])
                self.assertIn("escapes: unknown", r.stdout)
                point, _ = self.point(w)
                self.assertIsNone(point["escapes"]["count"])
                self.assertTrue(self.day_row(tmp, w).endswith(" | unknown |"))

    def test_e4_a_window_without_a_count_shows_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = copy_window(tmp)
            point, _ = self.point(w)
            self.assertNotIn("escapes", point)
            self.assertTrue(self.day_row(tmp, w).endswith(" | unknown |"))

    def test_e5_untrusted_reads_write_nothing(self):
        lists = main_lists(ES, EU)
        broken = {
            "a failed read": {lists[0]: {"stdout": "", "exit": 1}},
            "an issue page that isn't a list": {issues_call(ES): {"stdout": "{}", "exit": 0}},
            "a run without its title": {finders_call(ES, EU): {"stdout": json.dumps({"total_count": 1, "workflow_runs": [
                {"id": 401, "status": "completed", "conclusion": "success"}]}), "exit": 0}},
            "a run without its start": {lists[-1]: {"stdout": json.dumps({"total_count": 1, "workflow_runs": [
                {k: v for k, v in main_ci(302, "push", "failure").items() if k != "run_started_at"}]}), "exit": 0}},
            "a run listed twice": {lists[-1]: {"stdout": json.dumps({"total_count": 2, "workflow_runs": [
                main_ci(302, "schedule", "failure"), main_ci(302, "schedule", "failure")]}), "exit": 0}},
        }
        for what, edit in broken.items():
            with self.subTest(what), tempfile.TemporaryDirectory() as tmp:
                the_world = escape_world()
                the_world.update(edit)
                r, _, w = self.escapes(tmp, the_world)
                self.assertEqual(r.returncode, 1)
                self.assertIn("bench: nothing written", r.stderr)
                self.assertFalse((w / "escapes.json").exists())

    def test_e6_a_point_whose_count_hides_an_unknown_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, w = self.escapes(tmp, escape_world())
            point, _ = self.point(w)
            for bad in ({"count": 0, "attempts": 3, "failed_attempts": 2, "unknown": 1},
                        {"count": None, "attempts": 3, "failed_attempts": 2, "unknown": 0},
                        {"count": 2, "attempts": 1, "failed_attempts": 2, "unknown": 0},
                        {"count": 2, "attempts": 3, "failed_attempts": 2, "unknown": 0, "runs": [302]}):
                with self.subTest(bad):
                    (w / "point.json").write_text(json.dumps(dict(point, escapes=bad)))
                    r = run(["dashboard", str(w), "--baseline", str(w), "--out", str(Path(tmp) / "d")])
                    self.assertEqual(r.returncode, 1, r.stderr)
                    self.assertIn("escapes", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
