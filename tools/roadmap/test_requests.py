#!/usr/bin/env python3
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "roadmap.py"
REQUESTS_PY = HERE / "requests.py"
FIX = HERE / "fixtures"
OWNER_REPO = "https://github.com/openwizdev/OpenWiz"
SKILLS_REPO = "https://github.com/openwizdev/WizSkills"
MARKET_REPO = "https://github.com/openwizdev/WizMarket"

FAKE_GH = '''#!/usr/bin/env python3
import json
import os
import sys

MILESTONES_JQ = ".[] | {number, title, description, html_url}"
ISSUES_JQ = (".[] | select(.pull_request == null)"
             " | {number, state, state_reason, sub_issues: .sub_issues_summary.total, html_url}")
SPEC_ISSUES_JQ = (".[] | select(.pull_request == null)"
                  " | {number, title, state, sub_issues: .sub_issues_summary.total, html_url}")
REQUESTS_JQ = (".[] | select(.pull_request == null)"
               " | {number, title, state, body, html_url, plus_one: .reactions[\\"+1\\"]}")
REFS_JQ = ".[].ref"
TICKET_JQ = "{number, state, state_reason, pull: (.pull_request != null), html_url}"
PUBLIC = os.environ.get("FAKE_GH_PUBLIC", "jparker2006/OpenWiz")


def fail(message):
    print(f"fake gh: {message}", file=sys.stderr)
    sys.exit(1)


def line_of(item):
    if isinstance(item, dict) and set(item) == {"__raw__"}:
        return item["__raw__"]
    if isinstance(item, str):
        return item
    return json.dumps(item, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def emit(out, logline):
    planted = os.environ.get("FAKE_GH_FAIL", "")
    if planted and planted in logline:
        fail(f"planted failure: {logline}")
    sys.stdout.buffer.write(out.encode("utf-8"))
    sys.stdout.flush()
    sys.exit(0)


def main(args):
    world_file = os.environ.get("FAKE_GH_WORLD") or fail("FAKE_GH_WORLD is not set")
    log_file = os.environ.get("FAKE_GH_LOG") or fail("FAKE_GH_LOG is not set")
    with open(world_file, encoding="utf-8") as f:
        world = json.load(f)
    logline = " ".join(args)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(logline + "\\n")

    ticket_prefix = "repos/{owner}/{repo}/issues/"
    if len(args) == 4 and args[0] == "api" and args[1].startswith(ticket_prefix) and args[2:] == ["--jq", TICKET_JQ]:
        number = args[1][len(ticket_prefix):]
        found = [i for lst in [*world["issues"].values(), world.get("outside", [])] for i in lst
                 if isinstance(i, dict) and i.get("number") == int(number)]
        if not found:
            fail("Not Found (HTTP 404)")
        i = found[0]
        emit(line_of({"number": i["number"], "state": i["state"], "state_reason": i["state_reason"],
                      "pull": i.get("pull", False), "html_url": i["html_url"]}) + "\\n", logline)

    if len(args) != 5 or args[:2] != ["api", "--paginate"] or args[3] != "--jq":
        fail(f"unexpected: gh {logline}")
    path, jq = args[2], args[4]
    issues_prefix = "repos/{owner}/{repo}/issues?milestone="
    if path == "repos/{owner}/{repo}/milestones?state=all&per_page=100" and jq == MILESTONES_JQ:
        items = world["milestones"]
    elif path == "repos/{owner}/{repo}/git/matching-refs/heads/release-" and jq == REFS_JQ:
        items = world["heads"]
    elif path == f"repos/{PUBLIC}/git/matching-refs/tags/v" and jq == REFS_JQ:
        items = world["public_tags"]
    elif path.startswith(issues_prefix) and path.endswith("&state=all&per_page=100") and jq == ISSUES_JQ:
        number = path[len(issues_prefix):-len("&state=all&per_page=100")]
        items = world["issues"].get(number, [])
    elif path.startswith(issues_prefix) and path.endswith("&state=open&per_page=100") and jq == SPEC_ISSUES_JQ:
        number = path[len(issues_prefix):-len("&state=open&per_page=100")]
        items = world.get("spec_issues", {}).get(number, [])
    elif path.startswith("repos/") and path.endswith("/issues?state=open&per_page=100") and jq == REQUESTS_JQ:
        repo = path[len("repos/"):-len("/issues?state=open&per_page=100")]
        items = []
        for item in world.get("requests", {}).get(repo, []):
            if isinstance(item, dict) and set(item) == {"__raw__"}:
                items.append(item)
            elif isinstance(item, dict) and item.get("pull_request") is None:
                items.append({
                    "number": item["number"],
                    "title": item["title"],
                    "state": item["state"],
                    "body": item["body"],
                    "html_url": item["html_url"],
                    "plus_one": item["reactions"]["+1"],
                })
    else:
        fail(f"unexpected: gh {logline}")

    emit("".join(line_of(item) + "\\n" for item in items), logline)


if __name__ == "__main__":
    main(sys.argv[1:])
'''


def marker(n):
    return f"OpenWiz subscriber request operation {n:032x}"


def request_body(text="Show the sample configuration.", kind="feature", visibility="public", op=1, crlf=False):
    lines = [f"Kind: {kind}"]
    if visibility is not None:
        lines.append(f"Visibility: {visibility}")
    lines += ["", text, "", marker(op)]
    return ("\r\n" if crlf else "\n").join(lines) + ("\r\n" if crlf else "\n")


def request_issue(repo_url, number, title, plus_one, body=None, state="open", extra=None):
    item = {
        "number": number,
        "title": title,
        "state": state,
        "body": request_body(op=number) if body is None else body,
        "html_url": f"{repo_url}/issues/{number}",
        "reactions": {"+1": plus_one},
    }
    if extra:
        item.update(extra)
    return item


def base_world():
    with open(FIX / "world.json", encoding="utf-8") as f:
        w = json.load(f)
    for m in w["milestones"]:
        m["html_url"] = m["html_url"].replace("https://github.com/example-owner/example-repo", OWNER_REPO)
        if m["title"] == "0.0.4":
            m["description"] = m["description"].replace("threads | and", "threads and")
    for lst in w["issues"].values():
        for i in lst:
            i["html_url"] = i["html_url"].replace("https://github.com/example-owner/example-repo", OWNER_REPO)
    w["spec_issues"] = {
        "6": [
            {"number": 45, "title": "0.0.4 spec: attach files to a thread", "state": "open",
             "sub_issues": 3, "html_url": f"{OWNER_REPO}/issues/45"},
            {"number": 42, "title": "0.0.4 spec: finished spec", "state": "closed",
             "sub_issues": 4, "html_url": f"{OWNER_REPO}/issues/42"},
            {"number": 41, "title": "0.0.4 ticket: plain ticket", "state": "open",
             "sub_issues": 0, "html_url": f"{OWNER_REPO}/issues/41"},
            {"number": 40, "title": "0.0.4 spec: start new threads", "state": "open",
             "sub_issues": 2, "html_url": f"{OWNER_REPO}/issues/40"},
        ]
    }
    w["requests"] = {
        "openwizdev/OpenWiz": [
            request_issue(OWNER_REPO, 101, "Add a Linux driver", 14,
                          body=request_body(kind="driver", visibility="public", op=101)),
            request_issue(OWNER_REPO, 102, "Support offline cache", 9,
                          body=request_body(kind="feature", visibility=None, op=102)),
            request_issue(OWNER_REPO, 103, "Fix startup timeout", 9,
                          body=request_body(kind="bug", visibility="public", op=103, crlf=True)),
            request_issue(OWNER_REPO, 104, "Show quickstart config", 2,
                          body=request_body(kind="docs", visibility="public", op=104)),
            request_issue(OWNER_REPO, 105, "Low priority tweak", 0,
                          body=request_body(kind="feature", visibility=None, op=105)),
        ],
        "openwizdev/WizSkills": [
            request_issue(SKILLS_REPO, 201, "Add a review skill", 19,
                          body=request_body(kind="feature", visibility=None, op=201)),
            request_issue(SKILLS_REPO, 202, "Fix skill runner retry", 9,
                          body=request_body(kind="bug", visibility="public", op=202)),
            request_issue(SKILLS_REPO, 203, "Explain skill pins", 5,
                          body=request_body(kind="docs", visibility="public", op=203)),
            request_issue(SKILLS_REPO, 204, "Add a release check skill", 3,
                          body=request_body(kind="feature", visibility="public", op=204)),
        ],
        "openwizdev/WizMarket": [
            request_issue(MARKET_REPO, 301, "List a calendar driver", 11,
                          body=request_body(kind="driver", visibility="public", op=301)),
            request_issue(MARKET_REPO, 302, "Add a search filter", 6,
                          body=request_body(kind="feature", visibility=None, op=302)),
            request_issue(MARKET_REPO, 303, "Add listing badges", 1,
                          body=request_body(kind="feature", visibility="public", op=303)),
        ],
    }
    return w


def load_requests_module():
    spec = importlib.util.spec_from_file_location("roadmap_requests", REQUESTS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RequestsCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="roadmap-requests-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "root"
        self.root.mkdir()
        self.out_dir = self.tmp / "public"
        self.out_dir.mkdir()
        self.public = self.out_dir / "ROADMAP.md"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh_path = self.bin / "gh"
        gh_path.write_text(FAKE_GH, encoding="utf-8")
        gh_path.chmod(gh_path.stat().st_mode | stat.S_IXUSR)

    def run_roadmap(self, w, *args, extra_env=None):
        world_file = self.tmp / "world.json"
        world_file.write_text(json.dumps(w), encoding="utf-8")
        log = self.tmp / "gh.log"
        if log.exists():
            log.unlink()
        env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_GH_")}
        env.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_GH_WORLD": str(world_file),
            "FAKE_GH_LOG": str(log),
        })
        env.update(extra_env or {})
        argv = [sys.executable, "-I", str(SCRIPT), "--root", str(self.root), "--public", str(self.public), *args]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=env, cwd=self.tmp)
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return proc, calls

    def test_specs_in_progress_and_top_ten_public_requests_in_order(self):
        w = base_world()
        proc, calls = self.run_roadmap(w, "--with-requests")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        expected = f"""\
# OpenWiz roadmap

What is being built now, and what comes next.

## Now

- **0.0.2**, live-checked: You can see the same list on your phone.
- **0.0.3**, built: You can send a message to a thread.
- **0.0.4**, building: You can start new threads and attach files.

## Specs in progress

- **0.0.4**: [0.0.4 spec: start new threads]({OWNER_REPO}/issues/40)
- **0.0.4**: [0.0.4 spec: attach files to a thread]({OWNER_REPO}/issues/45)

## Most wanted

- [Add a review skill]({SKILLS_REPO}/issues/201) — 19 +1s
- [Add a Linux driver]({OWNER_REPO}/issues/101) — 14 +1s
- [List a calendar driver]({MARKET_REPO}/issues/301) — 11 +1s
- [Support offline cache]({OWNER_REPO}/issues/102) — 9 +1s
- [Fix startup timeout]({OWNER_REPO}/issues/103) — 9 +1s
- [Fix skill runner retry]({SKILLS_REPO}/issues/202) — 9 +1s
- [Add a search filter]({MARKET_REPO}/issues/302) — 6 +1s
- [Explain skill pins]({SKILLS_REPO}/issues/203) — 5 +1s
- [Add a release check skill]({SKILLS_REPO}/issues/204) — 3 +1s
- [Show quickstart config]({OWNER_REPO}/issues/104) — 2 +1s

## Next

- **0.0.10**, being grilled: You can keep a fleet running with the lid shut.
"""
        self.assertEqual(self.public.read_text(encoding="utf-8"), expected)
        self.assertNotIn("Add listing badges", expected)
        self.assertNotIn("Low priority tweak", expected)
        self.assertTrue(any("repos/openwizdev/OpenWiz/issues?state=open&per_page=100" in c for c in calls))
        self.assertTrue(any("repos/openwizdev/WizSkills/issues?state=open&per_page=100" in c for c in calls))
        self.assertTrue(any("repos/openwizdev/WizMarket/issues?state=open&per_page=100" in c for c in calls))

    def test_singular_and_zero_plus_one_counts_and_empty_sections(self):
        w = base_world()
        w["spec_issues"] = {"6": []}
        w["requests"] = {
            "openwizdev/OpenWiz": [
                request_issue(OWNER_REPO, 106, "One vote ask", 1),
                request_issue(OWNER_REPO, 107, "Zero vote ask", 0),
            ],
            "openwizdev/WizSkills": [],
            "openwizdev/WizMarket": [],
        }
        proc, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        text = self.public.read_text(encoding="utf-8")
        self.assertIn("## Specs in progress\n\n- None right now.\n", text)
        self.assertIn(f"- [One vote ask]({OWNER_REPO}/issues/106) — 1 +1\n", text)
        self.assertIn(f"- [Zero vote ask]({OWNER_REPO}/issues/107) — 0 +1s\n", text)

        w["requests"] = {"openwizdev/OpenWiz": [], "openwizdev/WizSkills": [], "openwizdev/WizMarket": []}
        proc2, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((proc2.returncode, proc2.stderr), (0, ""))
        self.assertIn("## Most wanted\n\n- None right now.\n", self.public.read_text(encoding="utf-8"))

    def test_private_request_business_detail_and_tier_never_appear(self):
        w = base_world()
        w["requests"] = {
            "openwizdev/OpenWiz": [
                request_issue(OWNER_REPO, 501, "Confidential business ask", 999,
                              body=request_body(text="Business tier 100 private details", kind="feature",
                                                visibility="private", op=501),
                              extra={"tier": "100", "business_verified": True, "author": "synthetic-biz"}),
                request_issue(OWNER_REPO, 502, "Uppercase private ask", 888,
                              body=request_body(kind="feature", visibility="Private", op=502)),
                request_issue(OWNER_REPO, 503, "Unknown visibility ask", 777,
                              body=request_body(kind="feature", visibility="internal", op=503)),
                request_issue(OWNER_REPO, 504, "Public ask with hidden metadata", 8,
                              body=request_body(text="Tier 100 business body text should never show.",
                                                kind="docs", visibility="public", op=504),
                              extra={"tier": "100", "business_verified": False, "author": "synthetic-pub",
                                     "entitlement": {"tier": "100", "bank": None}}),
            ],
            "openwizdev/WizSkills": [],
            "openwizdev/WizMarket": [],
        }
        proc, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        text = self.public.read_text(encoding="utf-8")
        self.assertIn(f"- [Public ask with hidden metadata]({OWNER_REPO}/issues/504) — 8 +1s\n", text)
        for forbidden in ("Confidential business ask", "Uppercase private ask", "Unknown visibility ask",
                          "Business", "business_verified", "tier", "Tier", "100", "entitlement",
                          "synthetic-biz", "synthetic-pub", "body text should never show",
                          "OpenWiz subscriber request operation"):
            self.assertNotIn(forbidden, text)

    def test_non_request_and_malformed_marker_issues_are_ignored(self):
        w = base_world()
        w["requests"] = {
            "openwizdev/OpenWiz": [
                request_issue(OWNER_REPO, 601, "Ordinary issue", 50, body="Just a regular bug report.\n"),
                request_issue(OWNER_REPO, 602, "Null body", 40, body=None),
                request_issue(OWNER_REPO, 603, "Trailing text after marker", 30,
                              body=request_body(op=603) + "Extra words\n"),
                request_issue(OWNER_REPO, 604, "Short marker hex", 25,
                              body="Kind: bug\n\nFix it.\n\nOpenWiz subscriber request operation 0000\n"),
                request_issue(OWNER_REPO, 605, "Uppercase marker hex", 24,
                              body=f"Kind: bug\n\nFix it.\n\nOpenWiz subscriber request operation {'A' * 32}\n"),
                request_issue(OWNER_REPO, 606, "Invalid kind", 23,
                              body=request_body(kind="support", op=606)),
                request_issue(OWNER_REPO, 607, "No blank line before marker", 22,
                              body=f"Kind: bug\n\nFix it.\n{marker(607)}\n"),
                request_issue(OWNER_REPO, 608, "Empty prose", 21,
                              body=f"Kind: bug\n\n\n{marker(608)}\n"),
                request_issue(OWNER_REPO, 609, "Closed request", 20, state="closed",
                              body=request_body(op=609)),
                request_issue(OWNER_REPO, 610, "Multi-paragraph valid request", 4,
                              body=f"Kind: feature\n\nFirst paragraph.\n\nSecond paragraph.\n\n{marker(610)}\n"),
            ],
            "openwizdev/WizSkills": [],
            "openwizdev/WizMarket": [],
        }
        w["requests"]["openwizdev/OpenWiz"][1]["body"] = None
        proc, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        text = self.public.read_text(encoding="utf-8")
        most_wanted = text.split("## Most wanted\n\n", 1)[1].split("\n\n## Next", 1)[0]
        self.assertEqual(most_wanted, f"- [Multi-paragraph valid request]({OWNER_REPO}/issues/610) — 4 +1s")

    def test_non_scope_or_private_repo_is_refused_before_any_read(self):
        w = base_world()
        for bad in ("example-owner/private-intake", "openwizdev/WizSite", "openwizdev/todo-demo", "bad"):
            with self.subTest(bad=bad):
                proc, calls = self.run_roadmap(w, "--with-requests", "--scope-repo", bad)
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn("not an allowed scope repository", proc.stderr)
                self.assertEqual(calls, [])
                self.assertFalse(self.public.exists())

    def test_scope_repo_without_with_requests_is_usage_error(self):
        proc, calls = self.run_roadmap(base_world(), "--scope-repo", "openwizdev/OpenWiz")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("--scope-repo requires --with-requests", proc.stderr)
        self.assertEqual(calls, [])
        self.assertFalse(self.public.exists())

    def test_scope_repo_narrows_reads_and_deduplicates(self):
        w = base_world()
        proc, calls = self.run_roadmap(
            w, "--with-requests", "--scope-repo", "openwizdev/wizskills", "--scope-repo", "openwizdev/WizSkills"
        )
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        req_calls = [c for c in calls if "/issues?state=open&per_page=100" in c]
        self.assertEqual(len(req_calls), 1)
        self.assertIn("repos/openwizdev/WizSkills/issues?state=open&per_page=100", req_calls[0])
        text = self.public.read_text(encoding="utf-8")
        self.assertIn("Add a review skill", text)
        self.assertNotIn("Add a Linux driver", text)
        self.assertNotIn("List a calendar driver", text)

    def test_running_with_requests_twice_is_unchanged(self):
        w = base_world()
        first, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((first.returncode, first.stderr), (0, ""))
        before = (self.public.read_bytes(), self.public.stat().st_mtime_ns, self.public.stat().st_ino)
        second, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((second.returncode, second.stderr, second.stdout), (0, "", f"{self.public}: unchanged\n"))
        self.assertEqual((self.public.read_bytes(), self.public.stat().st_mtime_ns, self.public.stat().st_ino), before)

    def test_spoofed_spec_url_and_empty_spec_title_fail_closed(self):
        w = base_world()
        w["spec_issues"]["6"] = [
            {"number": 40, "title": "Spoofed spec", "state": "open", "sub_issues": 2,
             "html_url": "https://github.com/example-owner/private-repo/issues/40"},
        ]
        proc, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unexpected html_url", proc.stderr)
        self.assertFalse(self.public.exists())

        w2 = base_world()
        w2["spec_issues"]["6"] = [
            {"number": 40, "title": "   \n\t ", "state": "open", "sub_issues": 2,
             "html_url": f"{OWNER_REPO}/issues/40"},
        ]
        proc2, _ = self.run_roadmap(w2, "--with-requests")
        self.assertEqual(proc2.returncode, 1)
        self.assertIn("empty title", proc2.stderr)
        self.assertFalse(self.public.exists())

    def test_markdown_and_control_characters_in_titles_are_sanitized(self):
        w = base_world()
        w["spec_issues"] = {
            "6": [
                {"number": 40, "title": "0.0.4 spec: [alpha] <tag>\nline two", "state": "open",
                 "sub_issues": 1, "html_url": f"{OWNER_REPO}/issues/40"},
            ]
        }
        w["requests"] = {
            "openwizdev/OpenWiz": [
                request_issue(OWNER_REPO, 701, "[driver] Add <foo>\\bar\r\nnow", 7),
            ],
            "openwizdev/WizSkills": [],
            "openwizdev/WizMarket": [],
        }
        proc, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual((proc.returncode, proc.stderr), (0, ""))
        text = self.public.read_text(encoding="utf-8")
        self.assertIn(f"- **0.0.4**: [0.0.4 spec: \\[alpha\\] &lt;tag&gt; line two]({OWNER_REPO}/issues/40)\n", text)
        self.assertIn(f"- [\\[driver\\] Add &lt;foo&gt;\\\\bar now]({OWNER_REPO}/issues/701) — 7 +1s\n", text)

    def test_spoofed_url_and_failed_reads_fail_closed(self):
        w = base_world()
        w["requests"]["openwizdev/OpenWiz"] = [
            {
                "number": 801,
                "title": "Spoofed link",
                "state": "open",
                "body": request_body(op=801),
                "html_url": "https://github.com/example-owner/private-intake/issues/801",
                "reactions": {"+1": 10},
            }
        ]
        proc, _ = self.run_roadmap(w, "--with-requests")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("; nothing written\n", proc.stderr)
        self.assertFalse(self.public.exists())

        w2 = base_world()
        w2["requests"]["openwizdev/WizSkills"] = [
            {"__raw__": json.dumps({"number": 1, "title": "x", "state": "open", "body": request_body(op=1),
                                    "html_url": f"{SKILLS_REPO}/issues/1", "plus_one": 1, "tier": "100"})}
        ]
        proc2, _ = self.run_roadmap(w2, "--with-requests")
        self.assertEqual(proc2.returncode, 1)
        self.assertIn("; nothing written\n", proc2.stderr)
        self.assertFalse(self.public.exists())

        proc3, _ = self.run_roadmap(base_world(), "--with-requests",
                                    extra_env={"FAKE_GH_FAIL": "repos/openwizdev/WizMarket/issues?state=open"})
        self.assertEqual(proc3.returncode, 1)
        self.assertIn("; nothing written\n", proc3.stderr)
        self.assertFalse(self.public.exists())

    def test_direct_module_refuses_non_scope_repo(self):
        mod = load_requests_module()
        calls = []
        with self.assertRaises(RuntimeError):
            mod.read_requests(self.root, ("example-owner/private-intake",),
                              lambda *a, **k: calls.append(a), lambda *a, **k: [], RuntimeError)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
