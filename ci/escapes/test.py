#!/usr/bin/env python3
"""The escape finder's tests (#1264, X6 of spec #1256), on synthetic runs and
a fake `gh` (fixtures/gh). Run from anywhere:  python3 -I ci/escapes/test.py

P: the plan reader on the CI selection record's own fixtures
(ci/selection/, #1405): every valid plan is accepted, every invalid one is
refused for the reason ci/selection/README.md gives it, and the contract's
read cases get the answers they expect. L: reading a failed job's log for
the tests that failed. F: the finder end to end, on a synthetic GitHub: its
exact reads, the one issue it opens for an escape, and what it says when it
can't tell. Every expected value is written here by hand from the contract
and the ticket, never computed the way escapes.py computes it.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCRIPT = HERE / "escapes.py"
SELECTION = ROOT / "ci" / "selection"
FAKE_GH = HERE / "fixtures" / "gh"
R = "repos/{owner}/{repo}"

sys.dont_write_bytecode = True  # no __pycache__ beside the finder
spec = importlib.util.spec_from_file_location("escapes", SCRIPT)
escapes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(escapes)


def fixture(rel):
    return (SELECTION / rel).read_text()


def readme_table(section):
    """The README's rows in one section: {"invalid/x.json": "Rule 3: ..."}."""
    text = (SELECTION / "README.md").read_text()
    part = text.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0]
    return dict(re.findall(r"^\| `([^`]+)` \| (.+?) \|$", part, re.M))


class Plans(unittest.TestCase):
    """P: the contract's record, read exactly as tests/checks/ci_selection.rs
    reads it: the schema, then rules 1 to 9."""

    def test_every_valid_plan_is_accepted(self):
        names = sorted(p.name for p in (SELECTION / "valid").iterdir())
        self.assertEqual(sorted(Path(k).name for k in readme_table("Valid")), names)
        self.assertGreaterEqual(len(names), 17)
        for name in names:
            with self.subTest(name):
                self.assertEqual(escapes.refusals(fixture(f"valid/{name}")), [])

    def test_every_invalid_plan_is_refused_for_its_reason(self):
        table = readme_table("Invalid")
        names = sorted(p.name for p in (SELECTION / "invalid").iterdir())
        self.assertEqual(sorted(Path(k).name for k in table), names)
        self.assertGreaterEqual(len(names), 54)
        for rel, why in table.items():
            with self.subTest(rel):
                got = escapes.refusals(fixture(rel))
                self.assertNotEqual(got, [], f"{rel} was accepted")
                kind = why.split(":", 1)[0]
                if kind == "Schema":
                    self.assertTrue(all(g.startswith("schema: ") for g in got), got)
                else:
                    n = re.fullmatch(r"Rule (\d)", kind).group(1)
                    self.assertTrue(any(g.startswith(f"rule {n}: ") for g in got), got)
                    self.assertFalse(any(g.startswith("schema: ") for g in got), got)

    def test_planted_breaks_python_would_let_through(self):
        # Each is a valid plan with one break a naive reader in Python keeps:
        # `$` matching before a final newline, True as an integer, 1.0 as
        # one, and a value that isn't JSON at all.
        base = json.loads(fixture("valid/full-release-branch.json"))
        cases = {
            "a branch ending in a newline": ("run", "base_branch", base["run"]["base_branch"] + "\n"),
            "a run id of true": ("run", "id", True),
            "a run id of 1.0": ("run", "id", 1.0),
            "an attempt of true": ("run", "attempt", True),
        }
        for what, (a, b, value) in cases.items():
            with self.subTest(what):
                plan = json.loads(json.dumps(base))
                plan[a][b] = value
                self.assertNotEqual(escapes.refusals(json.dumps(plan)), [])
        for text in ("", "null", "[]", "{}", '{"schema": NaN}', fixture("valid/full-nightly.json") + "x"):
            with self.subTest(text[:20]):
                self.assertNotEqual(escapes.refusals(text), [])

    def test_the_schema_holds_only_keywords_the_reader_knows(self):
        self.assertEqual(escapes.lint(escapes.schema()), [])
        planted = escapes.schema()
        planted["$defs"]["count"]["exclusiveMaximum"] = 5
        self.assertEqual(escapes.lint(planted), ["#/$defs/count: unknown keyword exclusiveMaximum"])

    def test_the_contracts_read_cases(self):
        # Each case's own `expected`, which the contract's authors wrote.
        cases = sorted((SELECTION / "reads").iterdir())
        self.assertEqual(len(cases), 13)
        for path in cases:
            with self.subTest(path.name):
                case = json.loads(path.read_text())
                self.assertEqual(escapes.read_case(case, SELECTION), case["expected"])


LOG_PREFIX = "2026-11-06T10:06:00.0000000Z "
RUST_TESTS = ROOT / "ci" / "rust-tests.sh"
ALONG = "the skills' tests"


def log(*lines):
    return "".join(LOG_PREFIX + line + "\n" for line in lines)


# A fake cargo for the real ci/rust-tests.sh: FAKE_CARGO_PLAN maps each call
# ("plain" for the one-command path, "crates", or an openwiz-tests target) to
# [what it prints, its exit status]; `metadata` names the targets. The
# release fixture's build before the tests (#1260) is "prebuild", by its exact
# arguments; it prints nothing and passes unless the plan says otherwise.
CARGO = """import json, os, sys
assert 'rust_tests_nonce' not in os.environ, 'wrapper nonce leaked to Cargo'
args = sys.argv[1:]
plan = json.loads(os.environ['FAKE_CARGO_PLAN'])
if args == ['build', '--release', '--locked', '-p', 'openwiz-tests', '--example', 'openwiz']:
    text, rc = plan.get('prebuild', ['', 0])
    sys.stdout.write(text)
    sys.exit(rc)
if args[:1] == ['metadata']:
    targets = [{'name': t, 'test': True, 'kind': ['test']} for t in plan if t not in ('plain', 'crates', 'prebuild')]
    print(json.dumps({'packages': [{'name': 'openwiz-tests', 'targets': targets}]}))
    sys.exit(0)
if '--no-run' in args:
    sys.exit(plan.get('build', ['', 0])[1])
if '--exclude' in args:
    key = 'crates'
elif '--test' in args:
    key = args[args.index('--test') + 1]
else:
    key = 'plain'
text, rc = plan[key]
sys.stdout.write(text)
sys.exit(rc)
"""


def rust_tests_log(cargo, along=("", 0), cpus=2, after=""):
    """A job log of the rust job's test step: the real ci/rust-tests.sh, on
    one command (cpus < 4) or every target at once, with a fake cargo and
    the skills' tests beside it, as GitHub shows it: its step's group, each
    line stamped, then the next step."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        cg = d / "sys/fs/cgroup"
        cg.mkdir(parents=True)
        (cg / "cgroup.controllers").write_text("cpu memory\n")
        (cg / "cpu.max").write_text("max 100000\n")
        (cg / "memory.max").write_text("max\n")
        (d / "proc/self").mkdir(parents=True)
        (d / "proc/self/cgroup").write_text("0::/\n")
        bindir = d / "bin"
        bindir.mkdir()
        (bindir / "cargo.py").write_text(CARGO)
        (bindir / "cargo").write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{bindir / "cargo.py"}" "$@"\n')
        (bindir / "nproc").write_text(f"#!/bin/sh\necho {cpus}\n")
        for name in ("cargo", "nproc"):
            (bindir / name).chmod(0o700)
        env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_EVENT_NAME", "GITHUB_BASE_REF")}
        env.update(PATH=f"{bindir}{os.pathsep}{os.environ['PATH']}", RUST_TESTS_ROOT=str(d),
                   FAKE_CARGO_PLAN=json.dumps(cargo), ALONG_TEXT=along[0], ALONG_RC=str(along[1]),
                   rust_tests_nonce="inherited-value-must-be-unset")
        r = subprocess.run(["sh", str(RUST_TESTS), "--alongside", ALONG, "sh", "-c",
                            'test -z "${rust_tests_nonce+x}" || exit 97; printf "%s" "$ALONG_TEXT"; exit "$ALONG_RC"'],
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env, cwd=d, timeout=60)
    head = "##[group]Run sh ci/rust-tests.sh --alongside \"the skills' tests\" sh -euc \"$SKILLS_TESTS\"\n##[endgroup]\n"
    tail = "##[error]Process completed with exit code 1.\n" if r.returncode else ""
    return "".join(LOG_PREFIX + line + "\n" for line in (head + r.stdout + tail + after).splitlines())


SHAPE = "the wrapper's output can't be split into its own invocations"


def hint(target):
    return f"error: test failed, to rerun pass `-p openwiz-tests --test {target}`\n"


class Logs(unittest.TestCase):
    """L: the tests a failed rust job's log names, read from the real
    ci/rust-tests.sh's output, each cargo hint bound to the invocation that
    printed it and that invocation's own exit status; or why it can't say."""

    def test_one_command_names_its_failing_target(self):
        text = rust_tests_log({"plain": ["test m03_send ... FAILED\n" + hint("messaging")
                                          + "rust-tests: cargo test --workspace exited 0 after 1 s\n", 101]})
        self.assertEqual(escapes.failing_tests(text), ({"rust:test:messaging"}, []))

    def test_a_hint_from_the_suite_beside_it_is_not_a_failure(self):
        # R2 on #1705: the skills' tests pass, yet print an expected hint.
        text = rust_tests_log({"plain": [hint("web-api"), 101]}, along=("expected:\n" + hint("messaging"), 0))
        self.assertEqual(escapes.failing_tests(text), ({"rust:test:web-api"}, []))

    def test_a_hint_in_a_passing_section_is_not_a_failure(self):
        text = rust_tests_log({"crates": ["", 0], "alpha": [hint("alpha"), 0], "web-api": [hint("web-api"), 101]},
                              cpus=8)
        self.assertEqual(escapes.failing_tests(text), ({"rust:test:web-api"}, []))

    def test_every_target_at_once(self):
        text = rust_tests_log({"crates": ["error: test failed, to rerun pass `-p openwiz-core --lib`\n", 101],
                               "alpha": ["", 0], "messaging": [hint("messaging"), 101]}, cpus=8)
        self.assertEqual(escapes.failing_tests(text), ({"rust:lib:openwiz-core", "rust:test:messaging"}, []))

    def test_coloured_as_ci_colours_cargo(self):
        # ci.yml sets CARGO_TERM_COLOR: always, and the log keeps the codes.
        coloured = "\x1b[1m\x1b[91merror\x1b[0m\x1b[1m: test failed, to rerun pass `-p openwiz-tests --test messaging`\x1b[0m\n"
        self.assertEqual(escapes.failing_tests(rust_tests_log({"plain": [coloured, 101]})), ({"rust:test:messaging"}, []))

    def test_a_no_fail_fast_list(self):
        text = rust_tests_log({"plain": ["error: 2 targets failed:\n    `-p openwiz-tests --test messaging`\n"
                                         "    `-p openwiz-tests --test web-api`\n", 101]})
        self.assertEqual(escapes.failing_tests(text), ({"rust:test:messaging", "rust:test:web-api"}, []))

    def test_a_later_steps_output_is_not_this_steps(self):
        text = rust_tests_log({"plain": [hint("web-api"), 101]}, after="##[group]Run cargo test -p openwiz-tests --test checks pending\n" + hint("checks"))
        self.assertEqual(escapes.failing_tests(text), ({"rust:test:web-api"}, []))

    def test_what_it_cannot_name_stays_unknown(self):
        fast = rust_tests_log({"crates": ["", 0], "alpha": ["", 0]}, cpus=8)
        prefix = re.search(r"rust-tests-frame:[0-9a-f]{64} ", fast).group()

        def control(line):
            return LOG_PREFIX + prefix + line + "\n"

        cases = {
            "the skills' tests failed beside them": (
                rust_tests_log({"plain": [hint("messaging"), 101]}, along=("boom\n", 1)),
                {"rust-tests: the skills' tests: failed, with no test named"}),
            "a doc test": (rust_tests_log({"plain": ["error: doctest failed, to rerun pass `-p openwiz-core --doc`\n", 101]}),
                           {"rust-tests: cargo test --workspace: a failure it can't name: -p openwiz-core --doc"}),
            "a build that failed": (rust_tests_log({"plain": ["error: could not compile `openwiz-core`\n", 101]}),
                                    {"rust-tests: cargo test --workspace: failed, with no test named"}),
            "a target with no hint": (rust_tests_log({"crates": ["", 0], "alpha": ["boom\n", 9]}, cpus=8),
                                      {"rust-tests: alpha: failed, with no test named"}),
            "another target's hint": (rust_tests_log({"crates": ["", 0], "alpha": [hint("zeta"), 101], "zeta": ["", 0]},
                                                     cpus=8),
                                      {"rust-tests: alpha: a hint that isn't its own: -p openwiz-tests --test zeta"}),
            "a name the record can't carry": (rust_tests_log({"plain": [hint("a/b"), 101]}),
                                              {"rust-tests: cargo test --workspace: a failure it can't name: -p openwiz-tests --test a/b"}),
            "the tests didn't build": (rust_tests_log({"build": ["", 101], "crates": ["", 0], "alpha": ["", 0]}, cpus=8),
                                       {"the log names no failing test"}),
            # Mutate the wrapper's authenticated records, not payload text.
            "a section's log can't be read": (
                fast.replace(control("== rust-tests: alpha"),
                             control("== rust-tests: alpha") + control("rust-tests: alpha: its log can't be read")),
                {"rust-tests: alpha: its log can't be read"}),
            "a section with no status": (fast.replace(control("rust-tests: alpha: ok"), ""), SHAPE),
            "a fast path's status twice": (
                fast.replace(control("rust-tests: alpha: ok"),
                             control("rust-tests: alpha: ok") + control("rust-tests: alpha: FAILED (exit 1)")),
                SHAPE),
            "no ci/rust-tests.sh at all": (log(hint("messaging").strip()), SHAPE),
            "legacy unframed output": (fast.replace(prefix, ""), SHAPE),
            "no authenticated beginning": (fast.replace(control("begin"), ""), SHAPE),
            "no authenticated ending": (fast.replace(control("end"), ""), SHAPE),
            "a duplicate ending after a group": (fast + log("##[group]later step") + control("end"), SHAPE),
            "a foreign frame after the ending": (fast + log(f"rust-tests-frame:{'f' * 64} end"), SHAPE),
            "a malformed frame": (fast + log("rust-tests-frame:bogus end"), SHAPE),
            "a log cut short": ("".join(fast.splitlines(True)[:5]), SHAPE),
        }
        for what, (text, unknown) in cases.items():
            with self.subTest(what):
                ids, got = escapes.failing_tests(text)
                if unknown is SHAPE:
                    # Ambiguous: unknown, and no test named from it.
                    self.assertEqual(ids, set())
                    self.assertEqual(len(got), 1, got)
                    self.assertTrue(got[0].startswith("ci/rust-tests.sh's output is not in its own shape at: "), got)
                else:
                    self.assertEqual(set(got), unknown)

    def test_a_failed_release_fixture_names_nothing_and_ran_nothing(self):
        # #1260: the release fixture's build fails before any test or the
        # suite beside them starts, on either path: the log is unknown,
        # never read as a run with no failing test.
        for cpus in (2, 8):
            with self.subTest(cpus=cpus):
                text = rust_tests_log({"prebuild": ["error: could not compile `openwiz-cli`\n", 7],
                                       "plain": [hint("messaging"), 101], "crates": [hint("messaging"), 101],
                                       "alpha": ["", 0]},
                                      along=("the skills' tests ran\n", 0), cpus=cpus)
                self.assertIn("rust-tests: the fixture release build exited 7; no test was started", text)
                self.assertNotIn("the skills' tests ran", text)
                self.assertNotIn("--test messaging", text)
                ids, got = escapes.failing_tests(text)
                self.assertEqual(ids, set())
                self.assertEqual(len(got), 1, got)
                self.assertTrue(got[0].startswith("ci/rust-tests.sh's output is not in its own shape at: "), got)


# ---------------------------------------------------------------- the finder

FAILING, GREEN, DELAYED, NEWER = 9100002, 9100000, 9100001, 9100003
CUTOFF = "2026-11-06T10:00:00Z"  # the failed attempt's start
G = "a" * 40  # the last green full run's head
MERGES = ["c" * 40, "d" * 40, "e" * 40]  # main's merge commits since, in order
SINCE = "2026-11-06T09:00:00Z"  # the green run's creation


def ok(value):
    return {"stdout": json.dumps(value), "exit": 0}


def main_run(rid, head, conclusion, created, event="push", attempt=1, started=None):
    return {"id": rid, "path": ".github/workflows/ci.yml", "event": event, "head_branch": "main",
            "head_sha": head, "status": "completed", "conclusion": conclusion, "run_attempt": attempt,
            "created_at": created, "run_started_at": started or created}


def done_at(when, total=1):
    """An attempt's jobs, the last done at `when`."""
    return ok({"total_count": total, "jobs": [{"id": 600 + i, "name": f"job{i}", "conclusion": "success",
                                               "completed_at": when if i == 0 else "2026-11-06T08:00:00Z",
                                               "steps": []} for i in range(total)]})


MESSAGING = rust_tests_log({"plain": [hint("messaging"), 101]})
WEB_API = rust_tests_log({"plain": [hint("web-api"), 101]})


def world(plans, failing_log=MESSAGING, **over):
    """A synthetic GitHub: main's failing full run at the last of MERGES, the
    last green one at G, and one merged pull request per plan file (each
    merged by the next of MERGES), whose CI run kept that plan."""
    plans = [(p, json.loads(fixture(p))) for p in plans]
    head = MERGES[len(plans) - 1] if plans else G
    w = {
        f"api {R}/actions/runs/{FAILING}/attempts/1": ok(over.get("failing", main_run(FAILING, head, "failure", CUTOFF))),
        f"api {R}/actions/runs/{FAILING}/attempts/1/jobs?per_page=100&page=1": ok(over.get("jobs", {
            "total_count": 2,
            "jobs": [
                {"id": 501, "name": "rust", "conclusion": "failure",
                 "steps": [{"name": "The docs-only classifier", "conclusion": "success"},
                           {"name": "Run cargo test --workspace", "conclusion": "failure"},
                           {"name": "The pending list", "conclusion": "skipped"}]},
                {"id": 502, "name": "web-test", "conclusion": "success",
                 "steps": [{"name": "Run npm test", "conclusion": "success"}]},
            ]})),
        f"api --allow-escape-sequences {R}/actions/jobs/501/logs": {"stdout": failing_log, "exit": 0},
        f"api {R}/actions/workflows/ci.yml/runs?branch=main&per_page=100&page=1": ok({
            "workflow_runs": over.get("listed", [main_run(NEWER, "9" * 40, "success", "2026-11-06T11:00:00Z"),
                                                 main_run(GREEN, G, "success", SINCE)]),
            "total_count": len(over.get("listed", [1, 2]))}),
        f"api {R}/actions/runs/{GREEN}/attempts/1/jobs?per_page=100&page=1": done_at("2026-11-06T09:30:00Z", 2),
        f"api {R}/issues?state=all&since={SINCE}&per_page=100&page=1": ok(over.get("issues", [])),
        f"api -X POST {R}/issues --input -": {"post": True},
    }
    commits, runs = [], {}
    for i, (rel, plan) in enumerate(plans):
        merge, run, pr, h = MERGES[i], plan["run"], plan["run"]["pull_request"], plan["run"]["head"]
        parent = MERGES[i - 1] if i else G
        commits += [{"sha": h, "parents": [{"sha": G}]}, {"sha": merge, "parents": [{"sha": parent}, {"sha": h}]}]
        w[f"api {R}/commits/{merge}/pulls?per_page=100"] = ok([
            {"number": pr, "merged_at": "2026-11-06T09:30:00Z", "merge_commit_sha": merge,
             "base": {"ref": "main"}, "head": {"sha": h}}])
        runs.setdefault(h, []).append({"id": run["id"], "path": ".github/workflows/ci.yml", "event": "pull_request",
                                       "head_sha": h, "pull_requests": [{"number": pr}], "run_attempt": run["attempt"]})
        art = 7000 + i
        name = f"ci-selection-{run['attempt']}"
        w[f"api {R}/actions/runs/{run['id']}/artifacts?name={name}&per_page=100&page=1"] = ok(
            {"total_count": 1, "artifacts": [{"id": art, "name": name, "expired": False, "size_in_bytes": 4000}]})
        w[f"api {R}/actions/artifacts/{art}/zip"] = {"zip": {"ci-selection.json": str(SELECTION / rel)}}
    unique = list({c["sha"]: c for c in commits}.values())
    w[f"api {R}/compare/{G}...{head}?per_page=100&page=1"] = ok(over.get("compare", {
        "status": "ahead", "total_commits": len(unique), "commits": unique}))
    for h, rs in runs.items():
        w[f"api {R}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={h}&per_page=100&page=1"] = ok(
            {"total_count": len(rs), "workflow_runs": rs})
    for key, value in over.get("answers", {}).items():
        w[key] = value
    return w


class Finder(unittest.TestCase):
    """F: `escapes.py find --run N` on a synthetic GitHub."""

    def run_finder(self, w, run=FAILING, attempt=1):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            bindir = tmp / "bin"
            bindir.mkdir(mode=0o700)
            (bindir / "gh").symlink_to(FAKE_GH)
            (tmp / "world.json").write_text(json.dumps(w))
            env = {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_WORLD": str(tmp / "world.json"),
                   "FAKE_GH_LOG": str(tmp / "calls.log"), "FAKE_GH_POSTS": str(tmp / "posts.jsonl"),
                   "FAKE_GH_ROOT": str(ROOT)}
            summary = tmp / "summary.md"
            r = subprocess.run([sys.executable, "-I", str(SCRIPT), "find", "--run", str(run), "--attempt", str(attempt),
                                "--summary", str(summary)],
                               capture_output=True, text=True, env=env, cwd=tmp)
            calls = (tmp / "calls.log").read_text().splitlines() if (tmp / "calls.log").exists() else []
            posts = [json.loads(line) for line in (tmp / "posts.jsonl").read_text().splitlines()] \
                if (tmp / "posts.jsonl").exists() else []
            text = summary.read_text() if summary.exists() else ""
            return r, calls, posts, text

    def test_a_skipped_test_failing_on_main_is_one_escape_reported_once(self):
        r, calls, posts, summary = self.run_finder(world(["valid/selected-mixed.json"]))
        self.assertEqual(r.returncode, 0, r.stderr)
        h = "2" * 40
        self.assertEqual(calls, [
            f"api {R}/actions/runs/{FAILING}/attempts/1",
            f"api {R}/actions/runs/{FAILING}/attempts/1/jobs?per_page=100&page=1",
            f"api --allow-escape-sequences {R}/actions/jobs/501/logs",
            f"api {R}/actions/workflows/ci.yml/runs?branch=main&per_page=100&page=1",
            f"api {R}/actions/runs/{GREEN}/attempts/1/jobs?per_page=100&page=1",
            f"api {R}/compare/{G}...{MERGES[0]}?per_page=100&page=1",
            f"api {R}/commits/{MERGES[0]}/pulls?per_page=100",
            f"api {R}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={h}&per_page=100&page=1",
            f"api {R}/actions/runs/9000013/artifacts?name=ci-selection-1&per_page=100&page=1",
            f"api {R}/actions/artifacts/7000/zip",
            f"api {R}/issues?state=all&since={SINCE}&per_page=100&page=1",
            f"api -X POST {R}/issues --input -",
        ])
        self.assertEqual(len(posts), 1)
        issue = posts[0]
        self.assertEqual(sorted(issue), ["body", "labels", "title"])
        self.assertEqual(issue["title"], "Selector escape: rust:test:messaging, skipped by #910")
        self.assertEqual(issue["labels"], ["needs-triage"])
        body = issue["body"]
        self.assertIn("<!-- openwiz.ci-escape.v1 run=9100002 attempt=1 pr=910 test=rust:test:messaging -->", body)
        self.assertTrue(body.startswith("<!-- openwiz.ci-escape.v1 "))
        for words in ("#910", "`` rust:test:messaging ``", "`` the map links no changed path to it ``",
                      "`` crates/server/src/routes.rs ``", "`` skills/plan-graph/scripts/revision.sh ``",
                      "actions/runs/9100002", "actions/runs/9000013"):
            self.assertIn(words, body)
        self.assertIn("Result: escapes (1)", summary)
        self.assertIn("rust:test:messaging", summary)
        self.assertEqual(r.stdout.strip(), summary.strip())

        # Run again, as the next red full run does: the bot's issue is there,
        # so nothing is opened twice. The same words from anyone else are not
        # the finder's report, so they don't count.
        mine = {"number": 1001, "user": {"login": "github-actions[bot]"}, "body": body}
        r, calls, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], issues=[mine]))
        self.assertEqual((r.returncode, posts), (0, []), r.stderr)
        self.assertNotIn(f"api -X POST {R}/issues --input -", calls)
        self.assertIn("Result: escapes (1)", summary)
        self.assertIn("already reported in #1001", summary)
        theirs = dict(mine, user={"login": "someone"})
        r, _, posts, _ = self.run_finder(world(["valid/selected-mixed.json"], issues=[theirs]))
        self.assertEqual((r.returncode, len(posts)), (0, 1), r.stderr)

    def test_only_an_issues_first_line_is_its_marker(self):
        # A plan's changed path may hold any printable text, a marker too:
        # the issue the finder opened for #910 then quotes it in its list of
        # paths. That quote is no report of #911's escape.
        quoted = MARKER_911 = "<!-- openwiz.ci-escape.v1 run=9100002 attempt=1 pr=911 test=rust:test:web-api -->"
        plan = json.loads(fixture("valid/selected-mixed.json"))
        plan["diff"]["paths"].append(quoted)
        self.assertEqual(escapes.refusals(json.dumps(plan)), [])
        body = ("<!-- openwiz.ci-escape.v1 run=9100001 attempt=1 pr=910 test=rust:test:messaging -->\nA synthetic escape.\n"
                f"- `` {MARKER_911} ``")
        mine = {"number": 1001, "user": {"login": "github-actions[bot]"}, "body": body}
        r, _, posts, summary = self.run_finder(world(["valid/selected-mixed.json", "valid/selected-docs-only.json"],
                                                     failing_log=WEB_API, issues=[mine]))
        self.assertEqual((r.returncode, [p["title"] for p in posts]),
                         (0, ["Selector escape: rust:test:web-api, skipped by #911"]), r.stderr)
        self.assertTrue(posts[0]["body"].startswith(MARKER_911 + "\n"))

    def test_a_selected_test_failing_is_not_an_escape(self):
        # selected-mixed ran rust:test:web-api: an ordinary red main.
        r, calls, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], failing_log=WEB_API))
        self.assertEqual((r.returncode, posts), (0, []), r.stderr)
        self.assertNotIn(f"api {R}/issues?state=all&since={SINCE}&per_page=100&page=1", calls)
        self.assertIn("Result: none", summary)
        self.assertIn("rust:test:web-api: ran in every plan: not an escape", summary)

    def test_a_full_plan_skipped_nothing(self):
        r, _, posts, summary = self.run_finder(world(["valid/full-unknown-path.json"]))
        self.assertEqual((r.returncode, posts), (0, []), r.stderr)
        self.assertIn("Result: none", summary)

    def test_a_skipped_lane_skipped_its_tests_and_only_that_pull_request_is_named(self):
        # #910 ran web-api; #911 (docs only) skipped the whole Rust lane.
        r, calls, posts, summary = self.run_finder(world(["valid/selected-mixed.json", "valid/selected-docs-only.json"],
                                                         failing_log=WEB_API))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([p["title"] for p in posts], ["Selector escape: rust:test:web-api, skipped by #911"])
        self.assertIn("`` no test reads README.md ``", posts[0]["body"])
        self.assertIn("`` README.md ``", posts[0]["body"])
        # Both pull requests share one head: its runs are read once.
        h = "2" * 40
        self.assertEqual(calls.count(
            f"api {R}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={h}&per_page=100&page=1"), 1)

    def test_no_readable_plan_is_unknown_never_no_escape(self):
        # Today, before X5 (#1262): CI keeps no plan, so a pull request's run
        # has no ci-selection artifact.
        no_plan = {f"api {R}/actions/runs/9000013/artifacts?name=ci-selection-1&per_page=100&page=1":
                   ok({"total_count": 0, "artifacts": []})}
        expired = {f"api {R}/actions/runs/9000013/artifacts?name=ci-selection-1&per_page=100&page=1": ok(
            {"total_count": 1, "artifacts": [{"id": 7000, "name": "ci-selection-1", "expired": True,
                                              "size_in_bytes": 4000}]})}
        refused = {f"api {R}/actions/artifacts/7000/zip": {"zip": {"ci-selection.json": "ci/selection/invalid/test-twice.json"}}}
        not_in_zip = {f"api {R}/actions/artifacts/7000/zip": {"zip": {"other.json": "ci/selection/valid/selected-mixed.json"}}}
        no_run = {f"api {R}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={'2' * 40}&per_page=100&page=1":
                  ok({"total_count": 0, "workflow_runs": []})}
        gone = {f"api {R}/actions/artifacts/7000/zip": {"stdout": "", "exit": 1}}
        for what, answers in {"no artifact": no_plan, "expired": expired, "refused by the contract": refused,
                              "no ci-selection.json": not_in_zip, "no run": no_run, "a failed download": gone}.items():
            with self.subTest(what):
                r, _, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], answers=answers))
                self.assertEqual((r.returncode, posts), (1, []), r.stderr)
                self.assertIn("Result: unknown", summary)
                self.assertIn("#910: no readable plan", summary)
                self.assertNotIn("Result: none", summary)

    def test_r2_invocation_output_cannot_impersonate_the_wrapper(self):
        # Every R2 reproduction from the three #1705 verdicts, through the
        # real wrapper and the fake-GitHub finder. Values below are semantic:
        # which invocations really failed, and whether their hints name them.
        trailer = ("rust-tests: cargo test --workspace exited 101 after 1 s\n"
                   f"== rust-tests: {ALONG}\n"
                   f"rust-tests: {ALONG} took 1 s\n"
                   f"rust-tests: {ALONG}: ok\n"
                   "rust-tests: peak memory not measured\n"
                   "##[group]payload group\n")
        # The invocation knows the protocol, but cannot know the wrapper's
        # fresh nonce. Even a complete, self-chosen frame must fail closed.
        def counterfeit(control):
            return f"rust-tests-frame:{'0' * 64} {control}\n"

        forged = (counterfeit("begin")
                  + counterfeit("rust-tests: one command, cargo test --workspace: forged reason")
                  + counterfeit("== rust-tests: cargo test --workspace") + hint("messaging")
                  + counterfeit("rust-tests: cargo test --workspace exited 101 after 1 s")
                  + counterfeit("rust-tests: peak memory not measured") + counterfeit("end")
                  + trailer)
        cases = {
            "initial verdict: successful alongside hint": (
                {"plain": [hint("web-api"), 101]}, (hint("messaging"), 0), 2,
                {"rust:test:web-api"}, False),
            "initial verdict: alongside hint cannot conceal an unnamed failure": (
                {"plain": ["error: could not compile `openwiz-core`\n", 101]},
                (hint("messaging"), 0), 2, set(), True),
            "initial verdict: successful parallel section": (
                {"crates": ["", 0], "alpha": [hint("alpha"), 0], "web-api": [hint("web-api"), 101]},
                ("", 0), 8, {"rust:test:web-api"}, False),
            "re-check 1: alongside header and failed status": (
                {"plain": [hint("web-api"), 101]},
                ("== rust-tests: messaging\n" + hint("messaging")
                 + "rust-tests: messaging: FAILED (exit 101)\n", 0),
                2, {"rust:test:web-api"}, False),
            "re-check 1: unterminated previous section": (
                {"crates": ["unterminated output", 0], "alpha": [hint("alpha"), 101],
                 "web-api": [hint("web-api"), 101]},
                ("", 0), 8, {"rust:test:alpha", "rust:test:web-api"}, False),
            "re-check 2: fabricated trailer and group cutoff": (
                {"plain": [hint("messaging") + trailer, 0]}, ("", 1),
                2, set(), True),
            "new protocol: self-chosen nonce impersonation": (
                {"plain": [forged, 0]}, ("", 1), 2, set(), True),
        }
        nonces = set()
        for name, (cargo, along, cpus, expected_ids, expected_unknown) in cases.items():
            with self.subTest(name):
                text = rust_tests_log(cargo, along=along, cpus=cpus)
                ids, unknown = escapes.failing_tests(text)
                nonce = re.search(r"rust-tests-frame:([0-9a-f]{64}) begin", text).group(1)
                self.assertNotIn(nonce, nonces)
                self.assertNotEqual(nonce, "0" * 64)
                nonces.add(nonce)
                r, _, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], failing_log=text))
                # alpha isn't named by this plan, so its real failure is
                # unknown. All the other real Cargo failures were selected.
                finder_unknown = expected_unknown or "rust:test:alpha" in expected_ids
                with self.subTest(case=name, seam="finder"):
                    self.assertEqual((r.returncode, posts), (int(finder_unknown), []), summary + r.stderr)
                    self.assertIn("Result: unknown" if finder_unknown else "Result: none", summary)
                with self.subTest(case=name, seam="parser"):
                    self.assertEqual(ids, expected_ids)
                    self.assertEqual(bool(unknown), expected_unknown, unknown)

    def test_an_escape_is_still_reported_beside_an_unknown(self):
        # messaging is an escape; the skills' tests also failed and name no test.
        text = rust_tests_log({"plain": [hint("messaging"), 101]}, along=("boom\n", 1))
        r, _, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], failing_log=text))
        self.assertEqual((r.returncode, len(posts)), (1, 1), r.stderr)
        self.assertIn("Result: unknown", summary)
        self.assertIn("1 escape reported", summary)

    def test_every_doubt_is_unknown(self):
        npm = {"total_count": 1, "jobs": [{"id": 503, "name": "web-test", "conclusion": "failure",
                                           "steps": [{"name": "Run npm test", "conclusion": "failure"}]}]}
        cancelled = {"total_count": 1, "jobs": [{"id": 501, "name": "rust", "conclusion": "cancelled", "steps": []}]}
        cases = {
            "a failed step it can't read tests from": ({"jobs": npm}, "web-test: Run npm test failed"),
            "a cancelled job": ({"jobs": cancelled}, "rust: cancelled"),
            "a compare that diverged": ({"compare": {"status": "diverged", "total_commits": 1, "commits": []}},
                                       "not ahead of"),
            "a short compare": ({"compare": {"status": "ahead", "total_commits": 9, "commits": []}}, "9 commits"),
            "a merge with no merged pull request": (
                {"answers": {f"api {R}/commits/{MERGES[0]}/pulls?per_page=100": ok([])}},
                f"{MERGES[0]}: no merged pull request"),
            "an unreadable association": (
                {"answers": {f"api {R}/actions/workflows/ci.yml/runs?event=pull_request&head_sha={'2' * 40}&per_page=100&page=1":
                             ok({"total_count": 1, "workflow_runs": [{"id": 9000013, "path": ".github/workflows/ci.yml",
                                                                      "event": "pull_request", "head_sha": "2" * 40,
                                                                      "pull_requests": None, "run_attempt": 1}]})}},
                "#910: no readable plan"),
            "a failed read": ({"answers": {f"api --allow-escape-sequences {R}/actions/jobs/501/logs":
                                           {"stdout": "", "exit": 1}}}, "rust: its log can't be read"),
            "a green attempt with no end": ({"answers": {f"api {R}/actions/runs/{GREEN}/attempts/1/jobs?per_page=100&page=1":
                                                         ok({"total_count": 1, "jobs": [{"id": 1, "name": "rust",
                                                             "conclusion": "success", "completed_at": None, "steps": []}]})}},
                                            f"CI run {GREEN} attempt 1: when it ended can't be read"),
            "no green attempt before it": ({"listed": [main_run(NEWER, "9" * 40, "success", "2026-11-06T11:00:00Z")]},
                                           "no green full run of CI on main ended before"),
        }
        for what, (over, words) in cases.items():
            with self.subTest(what):
                r, _, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], **over))
                self.assertEqual((r.returncode, posts), (1, []), r.stderr)
                self.assertIn("Result: unknown", summary)
                self.assertIn(words, summary)

    def test_a_red_full_run_at_the_green_head_merged_nothing(self):
        r, calls, posts, summary = self.run_finder(world([]))
        self.assertEqual((r.returncode, posts), (0, []), r.stderr)
        self.assertFalse(any("/compare/" in c for c in calls))
        self.assertIn("Result: none", summary)
        self.assertIn("no pull request merged since", summary)

    def test_only_a_failed_full_run_on_main(self):
        for what, run in {"a pull request run": main_run(FAILING, MERGES[0], "failure", "2026-11-06T10:00:00Z",
                                                          event="pull_request"),
                          "a green run": main_run(FAILING, MERGES[0], "success", "2026-11-06T10:00:00Z"),
                          "another branch": dict(main_run(FAILING, MERGES[0], "failure", "2026-11-06T10:00:00Z"),
                                                 head_branch="release-0.0.14")}.items():
            with self.subTest(what):
                r, calls, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], failing=run))
                self.assertEqual((r.returncode, posts, len(calls)), (2, [], 1), r.stderr)
                self.assertIn("not a failed full run of CI on main", r.stderr)

    def test_the_last_green_attempt_ended_before_the_failed_one_started(self):
        # R1 on #1705: an older run at the same head goes green only after
        # the failed attempt started (its first attempt overlapped it, its
        # second came later). It proves nothing about the failure: the green
        # run before it does, and #910 is still an escape.
        listed = [main_run(NEWER, "9" * 40, "success", "2026-11-06T11:00:00Z"),
                  main_run(DELAYED, MERGES[0], "success", "2026-11-06T09:50:00Z", attempt=2, started="2026-11-06T10:50:00Z"),
                  main_run(GREEN, G, "success", SINCE)]
        answers = {
            f"api {R}/actions/runs/{DELAYED}/attempts/2/jobs?per_page=100&page=1": done_at("2026-11-06T11:00:00Z"),
            f"api {R}/actions/runs/{DELAYED}/attempts/1": ok(main_run(DELAYED, MERGES[0], "success", "2026-11-06T09:50:00Z")),
            f"api {R}/actions/runs/{DELAYED}/attempts/1/jobs?per_page=100&page=1": done_at("2026-11-06T10:10:00Z"),
        }
        r, calls, posts, summary = self.run_finder(world(["valid/selected-mixed.json"], listed=listed, answers=answers))
        self.assertEqual((r.returncode, [p["title"] for p in posts]),
                         (0, ["Selector escape: rust:test:messaging, skipped by #910"]), r.stderr)
        self.assertIn(f"The last green full run: CI run {GREEN} attempt 1", summary)
        for call in answers:
            self.assertIn(call, calls)

    def test_its_own_earlier_green_attempt_counts(self):
        # The failed attempt is a rerun at the same head as its own green
        # first attempt, which ended before it started: nothing merged since.
        run = main_run(FAILING, MERGES[0], "failure", CUTOFF, attempt=2, started="2026-11-06T11:00:00Z")
        listed = [run]
        w = world(["valid/selected-mixed.json"], failing=run, listed=listed, answers={
            f"api {R}/actions/runs/{FAILING}/attempts/1": ok(main_run(FAILING, MERGES[0], "success", CUTOFF)),
            f"api {R}/actions/runs/{FAILING}/attempts/1/jobs?per_page=100&page=1": done_at("2026-11-06T10:30:00Z"),
        })
        w[f"api {R}/actions/runs/{FAILING}/attempts/2"] = ok(run)
        w[f"api {R}/actions/runs/{FAILING}/attempts/2/jobs?per_page=100&page=1"] = ok({
            "total_count": 1, "jobs": [{"id": 501, "name": "rust", "conclusion": "failure",
                                        "steps": [{"name": "Run cargo test --workspace", "conclusion": "failure"}]}]})
        r, _, posts, summary = self.run_finder(w, attempt=2)
        self.assertEqual((r.returncode, posts), (0, []), r.stderr)
        self.assertIn("Result: none", summary)
        self.assertIn(f"The last green full run: CI run {FAILING} attempt 1", summary)

    def test_the_nightly_run_and_a_later_attempt(self):
        run = main_run(FAILING, MERGES[0], "failure", "2026-11-06T10:00:00Z", event="schedule", attempt=2)
        w = world(["valid/selected-mixed.json"], failing=run)
        w[f"api {R}/actions/runs/{FAILING}/attempts/2/jobs?per_page=100&page=1"] = \
            w.pop(f"api {R}/actions/runs/{FAILING}/attempts/1/jobs?per_page=100&page=1")
        w[f"api {R}/actions/runs/{FAILING}/attempts/2"] = w.pop(f"api {R}/actions/runs/{FAILING}/attempts/1")
        r, _, posts, summary = self.run_finder(w, attempt=2)
        self.assertEqual((r.returncode, len(posts)), (0, 1), r.stderr)

    def test_usage(self):
        for argv in ([], ["find"], ["find", "--run", "x"], ["find", "--run", "0", "--attempt", "1"],
                     ["find", "--run", "5"], ["find", "--run", "5", "--attempt", "0"]):
            with self.subTest(argv):
                r = subprocess.run([sys.executable, "-I", str(SCRIPT), *argv], capture_output=True, text=True)
                self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
