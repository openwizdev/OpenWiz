#!/usr/bin/env python3
"""Proof for tools/release/pull.py on a fake `gh` (H5 of the 0.2.0 hot-update spec).

The fake `gh` serves a synthetic repository from a JSON state file, logs every
call, and records any release or tag deletion so a test fails on it.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[2]
PULL = ROOT / "tools/release/pull.py"
GRANTS = ROOT / "contracts/fixtures/release-grant"
REPO = "example-owner/example-release"
SHIPPED = "2035-01-10T00:00:00Z"

FAKE_GH = textwrap.dedent(r'''
    #!/usr/bin/env python3
    import json, os, sys
    from urllib.parse import urlsplit, parse_qs
    state_path = os.environ["FAKE_GH_STATE"]
    with open(state_path) as f:
        state = json.load(f)
    args = sys.argv[1:]
    with open(os.environ["FAKE_GH_CALLS"], "a") as f:
        f.write(json.dumps(args) + "\n")

    def save():
        with open(state_path, "w") as f:
            json.dump(state, f)

    def deletion(reason):
        state["deletions"].append({"args": args, "reason": reason})
        save()
        print("fake gh: deletion refused", file=sys.stderr)
        sys.exit(99)

    words = [a.lower() for a in args]
    if "delete" in words or "delete-asset" in words or any(w in ("-xdelete", "--method=delete") for w in words):
        deletion("delete")
    if args[:1] != ["api"]:
        print("fake gh: only `gh api` is served", file=sys.stderr)
        sys.exit(98)
    method, fields, path, rest = "GET", {}, None, args[1:]
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("-X", "--method"):
            method = rest[i + 1].upper(); i += 2; continue
        if a in ("-f", "-F", "--raw-field", "--field"):
            k, _, v = rest[i + 1].partition("="); fields[k] = v; i += 2; continue
        if a.startswith("-"):
            print(f"fake gh: unknown flag {a}", file=sys.stderr); sys.exit(98)
        path = a; i += 1
    if method == "DELETE" or "/git/refs" in (path or ""):
        deletion("ref or delete method")
    url = urlsplit(path)
    query = parse_qs(url.query)
    parts = url.path.strip("/").split("/")
    if parts[:3] != ["repos", *state["repo"].split("/")]:
        print("fake gh: unknown repository", file=sys.stderr); sys.exit(98)
    parts = parts[3:]
    out = None
    if method == "GET" and parts == ["releases", "latest"]:
        out = next(r for r in state["releases"] if r["id"] == state["latest"])
    elif method == "GET" and parts == ["releases"]:
        out = state["releases"]
    elif method == "PATCH" and parts[:1] == ["releases"] and len(parts) == 2:
        if set(fields) != {"make_latest"} or fields["make_latest"] != "true":
            print("fake gh: only make_latest is served", file=sys.stderr); sys.exit(98)
        state["latest"] = int(parts[1])
        out = next(r for r in state["releases"] if r["id"] == int(parts[1]))
    elif method == "GET" and parts[:2] == ["actions", "workflows"] and parts[3:] == ["runs"]:
        runs = [r for r in state["runs"] if parts[2] == state["workflow"]
                and r["event"] == query.get("event", [r["event"]])[0]
                and r["status"] == query.get("status", [r["status"]])[0]]
        out = {"total_count": len(runs), "workflow_runs": runs}
    elif method == "GET" and parts == ["issues"]:
        label = query.get("labels", [None])[0]
        out = [i for i in state["issues"] if label is None or label in i["labels_names"]]
        out = [dict(i, labels=[{"name": n} for n in i["labels_names"]]) for i in out]
    elif method == "POST" and parts == ["issues"]:
        number = 900 + len(state["opened"])
        state["opened"].append(dict(fields, number=number))
        out = {"number": number, "html_url": f"https://github.com/{state['repo']}/issues/{number}"}
    elif method == "GET" and len(parts) == 3 and parts[0] == "issues" and parts[2] == "comments":
        out = [c for c in state["comments"] if c["issue"] == int(parts[1])]
    elif method == "POST" and len(parts) == 3 and parts[0] == "issues" and parts[2] == "comments":
        state["comments"].append({"issue": int(parts[1]), "body": fields["body"]})
        out = {"html_url": f"https://github.com/{state['repo']}/issues/{parts[1]}#issuecomment-1"}
    else:
        print(f"fake gh: unserved {method} {path}", file=sys.stderr); sys.exit(98)
    save()
    print(json.dumps(out))
''').lstrip()


def release(id, version, published, **extra):
    return dict({"id": id, "tag_name": f"v{version}", "name": f"OpenWiz {version}", "draft": False,
                 "prerelease": False, "published_at": published,
                 "html_url": f"https://github.com/{REPO}/releases/tag/v{version}"}, **extra)


def run_(id, conclusion, created):
    return {"id": id, "event": "schedule", "status": "completed", "conclusion": conclusion,
            "created_at": created, "html_url": f"https://github.com/{REPO}/actions/runs/{id}"}


def issue(number, created, labels=("regression",), pr=False):
    item = {"number": number, "title": f"Synthetic report {number}", "created_at": created,
            "labels_names": list(labels), "html_url": f"https://github.com/{REPO}/issues/{number}"}
    if pr:
        item["pull_request"] = {"url": "synthetic"}
    return item


class PullTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="pull-proof-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        bin_ = self.root / "bin"
        bin_.mkdir()
        gh = bin_ / "gh"
        gh.write_text(f"#!{sys.executable}\n" + FAKE_GH.split("\n", 1)[1])
        gh.chmod(0o755)
        for refused in ("git", "curl", "wget"):
            stub = bin_ / refused
            stub.write_text(f"#!/bin/sh\necho '{refused}: refused in the pull proof' >&2\nexit 97\n")
            stub.chmod(0o755)
        self.state_path = self.root / "state.json"
        self.calls_path = self.root / "calls.jsonl"
        self.record = self.root / "hot-update.json"
        self.env = dict(os.environ, PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}",
                        FAKE_GH_STATE=str(self.state_path), FAKE_GH_CALLS=str(self.calls_path))
        self.env.pop("GH_TOKEN", None)
        self.env.pop("GITHUB_TOKEN", None)
        self.write_state({
            "repo": REPO, "workflow": "live-check.yml", "latest": 3,
            "releases": [release(3, "0.2.2", SHIPPED), release(2, "0.2.1", "2035-01-05T00:00:00Z"),
                         release(1, "0.2.0", "2035-01-01T00:00:00Z"),
                         release(4, "0.2.3", "2035-01-11T00:00:00Z", draft=True)],
            "runs": [run_(11, "success", "2035-01-09T00:00:00Z")],
            "issues": [issue(50, "2035-01-04T00:00:00Z")],
            "comments": [], "opened": [], "deletions": [],
        })
        self.write_record({"schema": "openwiz.hot-update.v1", "record": "release-record",
                           "latest": "0.2.2", "pulled": []})
        self.addCleanup(self.assert_nothing_deleted)

    def write_state(self, state):
        self.state_path.write_text(json.dumps(state))

    def state(self):
        return json.loads(self.state_path.read_text())

    def change(self, key, value):
        state = self.state()
        state[key] = value
        self.write_state(state)

    def write_record(self, record):
        self.record.write_text(json.dumps(record, indent=2) + "\n")

    def calls(self):
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def pull(self, grant="patch-and-pull", *extra):
        command = [sys.executable, "-I", str(PULL), "--repo", REPO, "--record", str(self.record),
                   "--live-check", "live-check.yml", "--threshold", "2", "--notes-issue", "7"]
        if grant is not None:
            command += ["--fleet", str(GRANTS / f"{grant}.md")]
        return subprocess.run(command + list(extra), capture_output=True, text=True, env=self.env,
                              cwd=self.root)

    def assert_nothing_deleted(self):
        self.assertEqual(self.state()["deletions"], [], "a release or tag deletion was attempted")

    def assert_untouched(self):
        state = self.state()
        self.assertEqual(state["latest"], 3)
        self.assertEqual(state["opened"], [])
        self.assertEqual(json.loads(self.record.read_text())["pulled"], [])
        self.assertFalse([c for c in self.calls() if "-X" in c and c[c.index("-X") + 1] == "PATCH"])

    def assert_pulled(self, result, reason):
        self.assertEqual(result.returncode, 0, result.stderr)
        state = self.state()
        self.assertEqual(state["latest"], 2, "the previous good release is latest again")
        self.assertEqual(json.loads(self.record.read_text()), {
            "schema": "openwiz.hot-update.v1", "record": "release-record", "latest": "0.2.1",
            "pulled": [{"version": "0.2.2", "last_good": "0.2.1", "reason": reason}]})
        self.assertEqual(len(state["opened"]), 1, "one fix-forward ticket")
        ticket = state["opened"][0]
        self.assertIn("0.2.2", ticket["title"])
        self.assertIn("Fix forward", ticket["title"])
        self.assertIn(reason, ticket["body"])
        self.assertIn("0.2.1", ticket["body"])
        self.assertEqual(state["comments"], [], "a granted pull asks nobody")
        self.assertIn("pulled 0.2.2", result.stdout)
        return ticket

    # Healthy

    def test_healthy_release_is_left_alone(self):
        state = self.state()
        state["runs"].append(run_(12, "success", "2035-01-11T00:00:00Z"))
        state["issues"].append(issue(51, "2035-01-11T00:00:00Z"))
        self.write_state(state)
        result = self.pull()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("0.2.2 is healthy", result.stdout)
        self.assert_untouched()
        self.assertEqual(self.state()["comments"], [])

    def test_a_later_passing_run_clears_an_earlier_failure(self):
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z"),
                             run_(13, "success", "2035-01-12T00:00:00Z")])
        result = self.pull()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_untouched()

    def test_old_reports_prs_and_other_labels_do_not_count(self):
        self.change("issues", [issue(50, "2035-01-04T00:00:00Z"), issue(51, "2035-01-09T23:59:59Z"),
                               issue(52, "2035-01-11T00:00:00Z", pr=True),
                               issue(53, "2035-01-11T00:00:00Z", labels=("bug",)),
                               issue(54, "2035-01-11T00:00:00Z")])
        result = self.pull()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_untouched()

    # Granted pulls

    def test_failing_live_check_pulls_the_release(self):
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        ticket = self.assert_pulled(self.pull(), "live-check-failed")
        self.assertIn(f"https://github.com/{REPO}/actions/runs/12", ticket["body"])

    def test_timed_out_live_check_pulls_the_release(self):
        self.change("runs", [run_(12, "timed_out", "2035-01-11T00:00:00Z")])
        self.assert_pulled(self.pull(), "live-check-failed")

    def test_regression_reports_at_the_threshold_pull_the_release(self):
        self.change("issues", [issue(51, "2035-01-11T00:00:00Z"), issue(52, "2035-01-12T00:00:00Z")])
        ticket = self.assert_pulled(self.pull(), "regression-threshold")
        for number in (51, 52):
            self.assertIn(f"https://github.com/{REPO}/issues/{number}", ticket["body"])

    def test_previous_good_skips_pulled_releases(self):
        self.write_record({"schema": "openwiz.hot-update.v1", "record": "release-record", "latest": "0.2.2",
                           "pulled": [{"version": "0.2.1", "last_good": "0.2.0", "reason": "live-check-failed"}]})
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        result = self.pull()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state()["latest"], 1)
        self.assertEqual(json.loads(self.record.read_text())["pulled"][-1],
                         {"version": "0.2.2", "last_good": "0.2.0", "reason": "live-check-failed"})

    def test_a_second_run_opens_no_second_ticket(self):
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        self.assert_pulled(self.pull(), "live-check-failed")
        again = self.pull()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("0.2.1 was reinstated", again.stdout)
        self.assertEqual(len(self.state()["opened"]), 1)
        self.assertEqual(self.state()["latest"], 2)

    def test_an_already_pulled_latest_is_not_pulled_twice(self):
        self.write_record({"schema": "openwiz.hot-update.v1", "record": "release-record", "latest": "0.2.1",
                           "pulled": [{"version": "0.2.2", "last_good": "0.2.1", "reason": "live-check-failed"}]})
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        result = self.pull()
        self.assertEqual(result.returncode, 1)
        self.assertIn("already pulled", result.stderr)
        self.assertEqual(self.state()["latest"], 3)
        self.assertEqual(self.state()["opened"], [])

    def test_no_good_predecessor_pulls_nothing(self):
        self.change("releases", [release(3, "0.2.2", SHIPPED)])
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        result = self.pull()
        self.assertEqual(result.returncode, 1)
        self.assertIn("no good release", result.stderr)
        self.assert_untouched()

    def test_a_malformed_record_pulls_nothing(self):
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        self.record.write_text('{"schema": "openwiz.hot-update.v1", "record": "release-record", "latest": "0.2.2"}\n')
        result = self.pull()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.state()["latest"], 3)
        self.assertEqual(self.state()["opened"], [])

    # Without the grant

    def test_without_the_grant_nothing_is_pulled_and_the_owner_gets_one_note(self):
        for grant in ("no-grant", "patch-only", "missing-pointer", None):
            with self.subTest(grant=grant or "today's Approval rules"):
                self.change("comments", [])
                self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
                result = self.pull(grant)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assert_untouched()
                comments = self.state()["comments"]
                self.assertEqual(len(comments), 1)
                self.assertEqual(comments[0]["issue"], 7)
                self.assertTrue(comments[0]["body"].startswith("Needs you: "))
                self.assertIn("0.2.2", comments[0]["body"].splitlines()[0])
                self.assertIn("live-check-failed", comments[0]["body"])
                again = self.pull(grant)
                self.assertEqual(again.returncode, 2, again.stderr)
                self.assertEqual(len(self.state()["comments"]), 1, "the owner gets one note, not one per run")

    # Deletion guard

    def test_the_fake_gh_fails_on_release_or_tag_deletion(self):
        for args in (["release", "delete", "v0.2.2", "--yes"], ["api", "-X", "DELETE", f"repos/{REPO}/releases/3"],
                     ["api", "--method", "DELETE", f"repos/{REPO}/git/refs/tags/v0.2.2"],
                     ["api", f"repos/{REPO}/git/refs/tags/v0.2.2"]):
            with self.subTest(args=args):
                before = len(self.state()["deletions"])
                result = subprocess.run(["gh", *args], capture_output=True, text=True, env=self.env)
                self.assertEqual(result.returncode, 99)
                self.assertEqual(len(self.state()["deletions"]), before + 1)
        self.change("deletions", [])

    def test_pull_never_names_a_delete(self):
        source = PULL.read_text(encoding="utf-8").lower()
        for word in ("delete", "git/refs", "\"git\"", "'git'"):
            self.assertNotIn(word, source)
        self.change("runs", [run_(12, "failure", "2035-01-11T00:00:00Z")])
        self.assert_pulled(self.pull(), "live-check-failed")
        for call in self.calls():
            self.assertEqual(call[0], "api")
            self.assertFalse([a for a in call if "delete" in a.lower()])


if __name__ == "__main__":
    unittest.main()
