#!/usr/bin/env python3
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("ROADMAP_PY", HERE / "roadmap.py")).resolve()
FIX = HERE / "fixtures"
GH = "https://github.com/example-owner/example-repo"

MILESTONES = ("api --paginate repos/{owner}/{repo}/milestones?state=all&per_page=100"
              " --jq .[] | {number, title, description, html_url}")
HEADS = "api --paginate repos/{owner}/{repo}/git/matching-refs/heads/release- --jq .[].ref"
TAGS = "api --paginate repos/jparker2006/OpenWiz/git/matching-refs/tags/v --jq .[].ref"


def issues(milestone):
    return (f"api --paginate repos/{{owner}}/{{repo}}/issues?milestone={milestone}&state=all&per_page=100"
            " --jq .[] | select(.pull_request == null)"
            " | {number, state, state_reason, sub_issues: .sub_issues_summary.total, html_url}")


def ticket(number):
    return (f"api repos/{{owner}}/{{repo}}/issues/{number}"
            " --jq {number, state, state_reason, pull: (.pull_request != null), html_url}")


CALLS = [MILESTONES, HEADS, TAGS, issues(1), ticket(11), issues(3), ticket(21), issues(4), ticket(31),
         issues(6), ticket(43), issues(7)]


def world():
    with open(FIX / "world.json", encoding="utf-8") as f:
        return json.load(f)


def milestone(w, title):
    found = [m for m in w["milestones"] if isinstance(m, dict) and m.get("title") == title]
    assert len(found) == 1, f"the sample world has no single milestone {title}"
    return found[0]


PUBLIC = """\
# OpenWiz roadmap

What is being built now, and what comes next.

## Now

- **0.0.2**, live-checked: You can see the same list on your phone.
- **0.0.3**, built: You can send a message to a thread.
- **0.0.4**, building: You can start new threads and attach files.

## Next

- **0.0.10**, being grilled: You can keep a fleet running with the lid shut.
"""


def public_world():
    w = world()
    m = milestone(w, "0.0.4")
    m["description"] = m["description"].replace("threads | and", "threads and")
    return w



def page(**states):
    text = PUBLIC
    for key, (old, new) in states.items():
        title = key[1:].replace("_", ".")
        line = f"- **{title}**, {old}:"
        assert text.count(line) == 1, line
        text = text.replace(line, f"- **{title}**, {new}:")
    return text


class Run:
    def __init__(self, proc, calls):
        self.code = proc.returncode
        self.out = proc.stdout
        self.err = proc.stderr
        self.calls = calls


class Case(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="roadmap-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.root = self.tmp / "root"
        self.root.mkdir()
        self.out_dir = self.tmp / "public"
        self.out_dir.mkdir()
        self.public = self.out_dir / "ROADMAP.md"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "gh").symlink_to(FIX / "gh")

    def fresh(self):
        if self.public.exists():
            self.public.unlink()

    def env(self, w, path=None, extra=None):
        world_file = self.tmp / "world.json"
        world_file.write_text(json.dumps(public_world() if w is None else w), encoding="utf-8")
        log = self.tmp / "gh.log"
        if log.exists():
            log.unlink()
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_GH_")}
        full_env.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}" if path is None else path,
            "FAKE_GH_WORLD": str(world_file),
            "FAKE_GH_LOG": str(log),
        })
        full_env.update(extra or {})
        return full_env, log

    def run_roadmap(self, w=None, *args, env=None, path=None, public=True):
        full_env, log = self.env(w, path, env)
        argv = [sys.executable, str(SCRIPT), "--root", str(self.root), *args]
        if public:
            argv += ["--public", str(self.public)]
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60, env=full_env, cwd=self.tmp)
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return Run(proc, calls)

    def read(self, path):
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()

    def assert_root_untouched(self):
        self.assertEqual(sorted(self.root.iterdir()), [])


class OnlyPublic(Case):
    def test_without_public_it_is_a_usage_error_and_reads_nothing(self):
        r = self.run_roadmap(public=False)
        self.assertEqual((r.code, r.out, r.calls), (2, "", []))
        self.assertIn("--public", r.err)
        self.assert_root_untouched()

    def test_no_page_in_the_repository_is_read_or_written(self):
        (self.root / "docs" / "ROADMAP.md").mkdir(parents=True)
        r = self.run_roadmap()
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), PUBLIC)
        self.assertTrue((self.root / "docs" / "ROADMAP.md").is_dir())
        self.assertEqual(sorted(p.name for p in self.root.rglob("*")), ["ROADMAP.md", "docs"])


class RepositorySettings(Case):
    def test_tags_come_from_the_public_repo_setting(self):
        r = self.run_roadmap(None, "--public-repo", "synthetic-owner/public-repo",
                             env={"FAKE_GH_PUBLIC": "synthetic-owner/public-repo"})
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.calls, [TAGS.replace("jparker2006/OpenWiz", "synthetic-owner/public-repo")
                                   if c == TAGS else c for c in CALLS])
        self.assertEqual(self.read(self.public), PUBLIC)

    def test_the_default_public_repo_is_openwiz(self):
        r = self.run_roadmap()
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertIn(TAGS, r.calls)

    def test_a_bad_public_repo_is_refused_before_any_read(self):
        for bad in ("synthetic-owner", "a/b/c", "{owner}/{repo}", "synthetic owner/repo",
                    "https://github.com/synthetic-owner/repo", "synthetic-owner/..", ""):
            with self.subTest(bad=bad):
                r = self.run_roadmap(None, "--public-repo", bad)
                self.assertEqual(r.code, 2, r.err)
                self.assertEqual(r.calls, [])
                self.assertFalse(self.public.exists())


class States(Case):
    def states(self, w):
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 0, r.err)
        found = {"0.0.1": "published", "0.0.2": "published", "0.0.3": "published",
                 "0.0.4": "published", "0.0.10": "published"}
        for line in self.read(self.public).splitlines():
            if line.startswith("- **"):
                title, rest = line[4:].split("**, ", 1)
                found[title] = rest.split(":", 1)[0]
        return found

    def test_each_state_from_the_sample_world(self):
        self.assertEqual(self.states(public_world()), {
            "0.0.1": "published", "0.0.2": "live-checked", "0.0.3": "built",
            "0.0.4": "building", "0.0.10": "being grilled"})

    def test_a_live_check_closed_as_not_planned_is_not_a_pass(self):
        w = public_world()
        w["issues"]["3"][1]["state_reason"] = "not_planned"
        self.assertEqual(self.states(w)["0.0.2"], "built")

    def test_a_tag_publishes_whatever_else_is_missing(self):
        w = public_world()
        w["public_tags"].append("refs/tags/v0.0.10")
        self.assertEqual(self.states(w)["0.0.10"], "published")

    def test_a_published_version_leaves_now_and_next(self):
        w = public_world()
        w["public_tags"].append("refs/tags/v0.0.2")
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(self.read(self.public),
                         PUBLIC.replace("- **0.0.2**, live-checked: You can see the same list on your phone.\n", ""))


class MissingLines(Case):
    def test_two_done_lines_are_listed_and_neither_is_read(self):
        w = public_world()
        milestone(w, "0.0.2")["description"] += "\nDone when a second line says so (#20)."
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.2: 2 "Done when …" lines in its milestone\n')
        self.assertNotIn(ticket(21), r.calls)
        self.assertNotIn(ticket(20), r.calls)
        self.assertEqual(self.read(self.public), page(v0_0_2=("live-checked", "built")))

    def test_look_alike_words_are_not_lines(self):
        w = public_world()
        milestone(w, "0.0.3")["description"] += "\nYou cannot send two.\nYou can'\nDone whenever it is.\nDone, when asked."
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), PUBLIC)

    def test_lone_carriage_returns_split_lines(self):
        w = public_world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("\n", "\r")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), PUBLIC)

    def test_no_issues_and_no_tags_at_all(self):
        w = public_world()
        w["public_tags"] = []
        del w["issues"]["7"]
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), PUBLIC.replace(
            "## Now\n\n", "## Now\n\n- **0.0.1**, live-checked: You can list your threads in the terminal.\n"))

    def test_a_line_counts_only_when_it_starts_with_its_words(self):
        w = public_world()
        m = milestone(w, "0.0.4")
        m["description"] = m["description"].replace("You can start", "- You can start")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.out), (1, ""))
        self.assertEqual(r.err, 'roadmap: --public: 0.0.4 has no single "You can …" line; nothing written\n')
        self.assertFalse(self.public.exists())

    def test_a_lane_needs_no_lines(self):
        w = public_world()
        milestone(w, "Infra")["description"] = None
        milestone(w, "0.0.X")["description"] = "Nothing here."
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), PUBLIC)

    def test_running_it_twice_with_a_gap_changes_nothing(self):
        w = public_world()
        milestone(w, "0.0.10")["description"] = "You can keep a fleet running with the lid shut."
        first = self.run_roadmap(w)
        self.assertEqual(first.code, 3)
        before = (self.public.read_bytes(), self.public.stat().st_mtime_ns)
        second = self.run_roadmap(w)
        self.assertEqual((second.code, second.err), (3, 'roadmap: 0.0.10: no "Done when …" line in its milestone\n'))
        self.assertEqual(second.out, f"{self.public}: unchanged\n")
        self.assertEqual((self.public.read_bytes(), self.public.stat().st_mtime_ns), before)


class LiveCheckTicket(Case):
    def test_the_ticket_is_read_wherever_it_is(self):
        w = public_world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(#99, then #31)")
        w["outside"] = [{"number": 99, "state": "closed", "state_reason": "completed",
                         "html_url": f"{GH}/issues/99"}]
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.calls, [c if c != ticket(31) else ticket(99) for c in CALLS])
        self.assertEqual(self.read(self.public), page(v0_0_3=("built", "live-checked")))

    def test_only_a_whole_ticket_number_counts(self):
        w = public_world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(step 2 of 3: not #0, not #44abc, but #31)")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.calls, CALLS)

    def test_only_closed_as_completed_is_a_pass(self):
        for state, reason in (("closed", "duplicate"), ("closed", None), ("open", "completed"), ("open", "reopened")):
            with self.subTest(state=state, reason=reason):
                self.fresh()
                w = public_world()
                w["issues"]["3"][1].update(state=state, state_reason=reason)
                r = self.run_roadmap(w)
                self.assertEqual((r.code, r.err), (0, ""))
                self.assertEqual(self.read(self.public), page(v0_0_2=("live-checked", "built")))

    def test_a_pull_request_is_not_a_live_check_ticket(self):
        w = public_world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(#99)")
        w["outside"] = [{"number": 99, "state": "closed", "state_reason": "completed", "pull": True,
                         "html_url": f"{GH}/pull/99"}]
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, "roadmap: 0.0.3: its live-check ticket #99 is a pull request\n")
        self.assertEqual(self.read(self.public), PUBLIC)

    def test_a_done_line_with_no_ticket_never_reads_as_live_checked(self):
        w = public_world()
        m = milestone(w, "0.0.2")
        m["description"] = m["description"].replace(" (#21)", "")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertNotIn(ticket(21), r.calls)
        self.assertEqual(self.read(self.public), page(v0_0_2=("live-checked", "built")))


class Public(Case):
    def run_public(self, w):
        return self.run_roadmap(w)

    def test_the_public_roadmap_is_now_and_next_one_line_each(self):
        r = self.run_public(public_world())
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.out, f"{self.public}: updated\n")
        self.assertEqual(self.read(self.public), PUBLIC)
        self.assertEqual(r.calls, CALLS)
        self.assert_root_untouched()
        self.assertEqual(sorted(p.name for p in self.out_dir.iterdir()), ["ROADMAP.md"])

    def test_nothing_private_reaches_it(self):
        w = public_world()
        milestone(w, "0.0.1")["description"] = (
            "You can ask Robin about private/notes.md (#11).\nDone when Robin says so (#11).")
        milestone(w, "Infra")["description"] = "You can read docs/grills/2026-01-01-first-steps.md and ask Robin."
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("one real thread", "Robin's private/evidence/thread")
        r = self.run_public(w)
        self.assertEqual((r.code, r.err), (0, ""))
        text = self.read(self.public)
        self.assertEqual(text, PUBLIC)
        self.assertNotRegex(text, r"#[0-9]")
        for private in ("private/", "docs/", "github.com", "example-owner", "Robin", "Done when",
                        "**0.0.1**", "Infra", "0.0.X", "Later idea", "kitchen timers", "write themselves"):
            self.assertNotIn(private, text)

    def test_a_private_word_in_a_now_or_next_line_stops_it(self):
        line = "You can send a message to a thread."
        for planted, holds in (
            ("You can send a message to a thread (#31).", 'the character "#"'),
            ("You can send a message, as private/notes.md says.", 'the character "/"'),
            ("You can send a message to https://example.com.", 'the character "/"'),
            ("You can send a message to @robin.", 'the character "@"'),
            ("You can send a message with `send`.", 'the character "`"'),
            ("You can send a message to a thread | fast.", 'the character "|"'),
            ("You can send a message to [a thread](x).", 'the character "["'),
            ("You can send a message to Zoë.", 'the character "ë"'),
            ("You can send a message to robin2006.", 'the token "robin2006", which mixes letters and digits'),
            ("You can send a message to Robin.", 'the word "Robin", which isn\'t on the public word list'),
            ("You can send a message to ROBIN.", 'the word "ROBIN", which isn\'t on the public word list'),
            ("You can send a message to jRobin.", 'the word "jRobin", which isn\'t on the public word list'),
            ("You can send a message to deRobin.", 'the word "deRobin", which isn\'t on the public word list'),
            ("You can ask J about it.", 'the word "J", which isn\'t on the public word list'),
            ("You can run v2 now.", 'the token "v2", which mixes letters and digits'),
            ("You can send a message to a thread|", 'the character "|"'),
            ("You can send a message & more.", 'the character "&"'),
            ("You can send a message ~ more.", 'the character "~"'),
            ("You can send a message for $5.", 'the character "$"'),
            ("You can send a message to snake_case.", 'the character "_"'),
            ("You can send a *message*.", 'the character "*"'),
            ("You can send a message \\ more.", 'the character "\\"'),
            ("You can send 50% of a message.", 'the character "%"'),
            ("You can send a = b.", 'the character "="'),
            ("You can send <b>a message</b>.", 'the character "<"'),
            ("You can send a message + more.", 'the character "+"'),
        ):
            with self.subTest(planted=planted):
                self.fresh()
                w = public_world()
                m = milestone(w, "0.0.3")
                m["description"] = m["description"].replace(line, planted)
                r = self.run_public(w)
                self.assertEqual(r.code, 1)
                self.assertEqual(r.err, f'roadmap: --public: 0.0.3\'s "You can …" line holds {holds}; nothing written\n')
                self.assertEqual(r.out, "")
                self.assertFalse(self.public.exists())
                self.assert_root_untouched()

    def test_a_next_line_is_checked_too(self):
        w = public_world()
        m = milestone(w, "0.0.10")
        m["description"] = m["description"].replace("lid shut.", "lid shut, ask Robin.")
        r = self.run_public(w)
        self.assertEqual(r.code, 1)
        self.assertEqual(r.err, 'roadmap: --public: 0.0.10\'s "You can …" line holds the word "Robin", which isn\'t'
                                ' on the public word list; nothing written\n')
        self.assertFalse(self.public.exists())

    def test_every_allowed_character_and_public_word_passes(self):
        line = ('You can use OpenWiz, CloudRoom and GitHub on a Mac or PC; it\'s "fast" (really)! ok? 0.0.9: 2 ways'
                ' - yes — no – “quoted” it’s …')
        w = public_world()
        m = milestone(w, "0.0.10")
        m["description"] = m["description"].replace("You can keep a fleet running with the lid shut.", line)
        r = self.run_public(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), PUBLIC.replace(
            "You can keep a fleet running with the lid shut.", line))

    def test_a_new_public_file_takes_the_umask(self):
        log = self.tmp / "gh.log"
        world_file = self.tmp / "world.json"
        world_file.write_text(json.dumps(public_world()), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_GH_")}
        env.update({"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_GH_WORLD": str(world_file), "FAKE_GH_LOG": str(log)})
        proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), "--public", str(self.public)],
                              capture_output=True, text=True, timeout=60, env=env, cwd=self.tmp,
                              preexec_fn=lambda: os.umask(0o027))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.public.stat().st_mode & 0o7777, 0o640)

    def test_a_now_or_next_version_without_its_outcome_stops_it(self):
        for change in ("drop", "double"):
            with self.subTest(change=change):
                self.fresh()
                w = public_world()
                m = milestone(w, "0.0.10")
                if change == "drop":
                    m["description"] = m["description"].replace("You can keep", "We keep")
                else:
                    m["description"] += "\nYou can also do a second thing."
                r = self.run_public(w)
                self.assertEqual(r.code, 1)
                self.assertEqual(r.err, 'roadmap: --public: 0.0.10 has no single "You can …" line; nothing written\n')
                self.assertFalse(self.public.exists())

    def test_a_gap_outside_now_and_next_is_listed_and_the_page_written(self):
        w = public_world()
        milestone(w, "0.0.1")["description"] = "You can list your threads in the terminal."
        r = self.run_public(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.1: no "Done when …" line in its milestone\n')
        self.assertEqual(self.read(self.public), PUBLIC)

    def test_empty_now_and_next(self):
        w = public_world()
        w["public_tags"] += ["refs/tags/v0.0.2", "refs/tags/v0.0.3", "refs/tags/v0.0.4", "refs/tags/v0.0.10"]
        r = self.run_public(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(self.read(self.public), "# OpenWiz roadmap\n\nWhat is being built now, and what comes next.\n\n"
                                                 "## Now\n\n- None right now.\n\n## Next\n\n- None right now.\n")

    def test_running_it_twice_changes_nothing(self):
        first = self.run_public(public_world())
        self.assertEqual(first.code, 0, first.err)
        before = (self.public.read_bytes(), self.public.stat().st_mtime_ns, self.public.stat().st_ino)
        second = self.run_public(public_world())
        self.assertEqual((second.code, second.err, second.out), (0, "", f"{self.public}: unchanged\n"))
        self.assertEqual((self.public.read_bytes(), self.public.stat().st_mtime_ns, self.public.stat().st_ino), before)


def raw(w, title, text):
    w["milestones"] = [{"__raw__": text} if isinstance(m, dict) and m.get("title") == title else m
                       for m in w["milestones"]]
    return w


GOOD_LINE = ('{"description":null,"html_url":"https://github.com/example-owner/example-repo/milestone/1",'
             '"number":1,"title":"0.0.1"}')


class FailsClosed(Case):
    def assert_stopped(self, r, err=None, prefix=None):
        self.assertEqual(r.code, 1, r.err)
        self.assertEqual(r.out, "")
        if err is not None:
            self.assertEqual(r.err, err)
        else:
            self.assertTrue(r.err.startswith(prefix), r.err)
            self.assertTrue(r.err.endswith("; nothing written\n"), r.err)
            self.assertEqual(r.err.count("\n"), 1, r.err)
        self.assert_root_untouched()
        self.assertFalse(self.public.exists())

    def test_a_failed_read_writes_nothing(self):
        for planted, path in (
            ("milestones?state", "repos/{owner}/{repo}/milestones?state=all&per_page=100"),
            ("heads/release-", "repos/{owner}/{repo}/git/matching-refs/heads/release-"),
            ("tags/v", "repos/jparker2006/OpenWiz/git/matching-refs/tags/v"),
            ("issues?milestone=4&", "repos/{owner}/{repo}/issues?milestone=4&state=all&per_page=100"),
            ("issues/31 ", "repos/{owner}/{repo}/issues/31"),
        ):
            for fault in ("FAKE_GH_FAIL", "FAKE_GH_PARTIAL"):
                with self.subTest(planted=planted, fault=fault):
                    self.fresh()
                    r = self.run_roadmap(None, env={fault: planted})
                    self.assert_stopped(r, prefix=f"roadmap: gh failed reading {path} (exit 1): fake gh: planted failure")

    def test_a_ticket_that_isnt_there_writes_nothing(self):
        w = world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(#98)")
        self.assert_stopped(self.run_roadmap(w), err="roadmap: gh failed reading repos/{owner}/{repo}/issues/98"
                                                     " (exit 1): fake gh: Not Found (HTTP 404); nothing written\n")

    def test_no_gh_writes_nothing(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        r = self.run_roadmap(None, path=str(empty))
        self.assert_stopped(r, prefix="roadmap: could not run gh for repos/{owner}/{repo}/milestones?state=all&per_page=100: ")

    def test_a_bad_milestone_answer_writes_nothing(self):
        for text in (
            '{"number": 1,',
            "[1]",
            '"0.0.1"',
            "",
            GOOD_LINE.replace('"number":1', '"number":1,"number":1'),
            GOOD_LINE.replace(',"title":"0.0.1"', ""),
            GOOD_LINE.replace('"number":1', '"number":1,"state":"open"'),
            GOOD_LINE.replace('"number":1', '"number":"1"'),
            GOOD_LINE.replace('"number":1', '"number":true'),
            GOOD_LINE.replace('"number":1', '"number":0'),
            GOOD_LINE.replace('"title":"0.0.1"', '"title":null'),
            GOOD_LINE.replace('"description":null', '"description":7'),
            '["description","html_url","number","title"]',
            GOOD_LINE.replace("https://github.com/", "https://example.com/"),
            GOOD_LINE.replace("https://github.com/", "https://githubXcom/"),
            GOOD_LINE.replace("milestone/1", "milestone/1)"),
            GOOD_LINE.replace("milestone/1", "milestone/1 x"),
        ):
            with self.subTest(text=text):
                self.fresh()
                self.assertEqual(json.loads(GOOD_LINE)["title"], "0.0.1")
                self.assert_stopped(self.run_roadmap(raw(world(), "0.0.1", text)), prefix="roadmap: milestones: ")

    def test_a_bad_issue_answer_writes_nothing(self):
        good = {"number": 30, "state": "open", "state_reason": None, "sub_issues": 1, "html_url": f"{GH}/issues/30"}
        for change in ({"sub_issues": None}, {"sub_issues": -1}, {"state": "merged"}, {"state_reason": 3},
                       {"html_url": "http://github.com/x"}, {"extra": 1}):
            with self.subTest(change=change):
                self.fresh()
                w = world()
                w["issues"]["4"][0] = {**good, **change}
                self.assert_stopped(self.run_roadmap(w), prefix="roadmap: milestone 0.0.3's issues: ")

    def test_a_bad_ticket_answer_writes_nothing(self):
        good = {"number": 31, "state": "open", "state_reason": None, "pull": False, "html_url": f"{GH}/issues/31"}
        for change in ({"number": 32}, {"number": 31.0}, {"number": True}, {"pull": "no"}, {"pull": None},
                       {"state": "done"}, {"html_url": None}, {"state_reason": 3}):
            with self.subTest(change=change):
                self.fresh()
                w = world()
                w["ticket_raw"] = {"31": json.dumps({**good, **change})}
                self.assert_stopped(self.run_roadmap(w), prefix="roadmap: 0.0.3's live-check ticket #31: ")

    def test_two_answers_for_one_ticket_write_nothing(self):
        line = json.dumps({"number": 31, "state": "open", "state_reason": None, "pull": False,
                           "html_url": f"{GH}/issues/31"})
        w = world()
        w["ticket_raw"] = {"31": f"{line}\n{line}"}
        self.assert_stopped(self.run_roadmap(w), err="roadmap: 0.0.3's live-check ticket #31: 2 answers"
                                                     " (one is needed); nothing written\n")

    def test_an_answer_cut_short_or_not_utf8_writes_nothing(self):
        path = "repos/{owner}/{repo}/milestones?state=all&per_page=100"
        for fault, err in (
            ("FAKE_GH_NO_NEWLINE", "roadmap: milestones: the answer doesn't end with a newline; nothing written\n"),
            ("FAKE_GH_NOT_UTF8", f"roadmap: gh's answer for {path} is not UTF-8; nothing written\n"),
        ):
            with self.subTest(fault=fault):
                self.fresh()
                self.assert_stopped(self.run_roadmap(None, env={fault: "milestones?state"}), err=err)

    def test_a_blank_line_in_an_answer_writes_nothing(self):
        self.assert_stopped(self.run_roadmap(raw(world(), "0.0.1", "")),
                            err="roadmap: milestones: a blank line in the answer; nothing written\n")

    def test_a_ref_outside_its_read_writes_nothing(self):
        for key, ref, what in (("heads", "refs/heads/main", "release branches"),
                               ("public_tags", "refs/heads/v0.0.3", "public tags"),
                               ("public_tags", "refs/tags/release-0.0.3", "public tags")):
            with self.subTest(ref=ref):
                self.fresh()
                w = world()
                w[key].append(ref)
                self.assert_stopped(self.run_roadmap(w), prefix=f"roadmap: {what}: a ref outside ")

    def test_a_milestone_that_is_neither_a_version_nor_a_lane_stops_it(self):
        for title in ("Someday", "0.0.08", "v0.0.9", "0.0.x", " 0.0.9", "0.0.9 ", "0.1", "infra"):
            with self.subTest(title=title):
                self.fresh()
                w = world()
                milestone(w, "0.0.10")["title"] = title
                self.assert_stopped(self.run_roadmap(w), err=f"roadmap: milestone {title!r} is neither a version"
                                                             " (N.N.N) nor a lane (Infra, 0.0.X); nothing written\n")

    def test_two_milestones_for_one_version_stop_it(self):
        w = world()
        milestone(w, "0.0.10")["title"] = "0.0.3"
        self.assert_stopped(self.run_roadmap(w), err="roadmap: two milestones are called 0.0.3; nothing written\n")

    def test_a_write_that_fails_writes_nothing(self):
        w = public_world()
        m = milestone(w, "0.0.10")
        m["description"] = m["description"].replace("lid shut.", "lid shut" + ", and keep going" * 600 + ".")
        limit = 8192
        env, _ = self.env(w)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--public", str(self.public)],
            capture_output=True, text=True, timeout=60, env=env, cwd=self.tmp,
            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)))
        self.assertEqual((proc.returncode, proc.stdout), (1, ""), proc.stderr)
        self.assertTrue(proc.stderr.startswith(f"roadmap: could not write {self.public}: "), proc.stderr)
        self.assertTrue(proc.stderr.endswith("; nothing written\n"), proc.stderr)
        self.assertEqual(sorted(self.out_dir.iterdir()), [])
        self.assert_root_untouched()

    def test_a_page_that_cant_be_put_in_place_says_what_was_written(self):
        env, _ = self.env(None)
        driver = (
            "import os, runpy, sys\n"
            "def replace(a, b):\n"
            "    raise OSError(28, 'No space left on device')\n"
            "os.replace = replace\n"
            "sys.argv = [sys.argv[1], '--root', sys.argv[2], '--public', sys.argv[3]]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        proc = subprocess.run([sys.executable, "-c", driver, str(SCRIPT), str(self.root), str(self.public)],
                              capture_output=True, text=True, timeout=60, env=env, cwd=self.tmp)
        self.assertEqual((proc.returncode, proc.stdout), (1, ""), proc.stderr)
        self.assertEqual(proc.stderr, f"roadmap: could not write {self.public}: [Errno 28] No space left on device;"
                                      " already written: none\n")
        self.assertEqual(sorted(self.out_dir.iterdir()), [])

    def test_an_existing_public_file_keeps_its_mode(self):
        self.public.write_text("an old page\n", encoding="utf-8")
        os.chmod(self.public, 0o604)
        r = self.run_roadmap()
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(self.read(self.public), PUBLIC)
        self.assertEqual(self.public.stat().st_mode & 0o7777, 0o604)

    def test_a_public_file_it_cant_write_writes_nothing(self):
        target = self.tmp / "no-such-folder" / "ROADMAP.md"
        r = self.run_roadmap(public_world(), "--public", str(target), public=False)
        self.assertEqual((r.code, r.out), (1, ""))
        self.assertTrue(r.err.startswith(f"roadmap: could not write {target}: "), r.err)
        self.assertFalse(target.exists())
        self.assert_root_untouched()


if __name__ == "__main__":
    unittest.main(verbosity=2)
