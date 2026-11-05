#!/usr/bin/env python3
"""roadmap.py on a synthetic GitHub (ClosedWiz#277, spec #276, PS1).

Run from anywhere:  python3 tools/roadmap/test.py

Each case copies the sample pages in fixtures/ to a temporary root, puts the
fake `gh` (fixtures/gh) first on PATH with a synthetic GitHub (fixtures/
world.json, changed by the case), runs roadmap.py there, and checks what it
does from the outside: the exact pages it writes, what it prints, its exit
status and the exact reads it makes. Every expected value is written out by
hand from the fixtures, never computed the way roadmap.py computes it.
ROADMAP_PY=<file> runs the same cases against another script.
"""
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


# The reads for the sample world, in order: the milestones, the release
# branches, the public tags, then each version's issues and the ticket its
# "Done when …" line names, oldest version first (0.0.1, 0.0.2, 0.0.3, 0.0.4,
# 0.0.10 are milestones 1, 3, 4, 6, 7; 0.0.10's line names none). Never the
# lanes' (Infra is 2, 0.0.X is 5).
CALLS = [MILESTONES, HEADS, TAGS, issues(1), ticket(11), issues(3), ticket(21), issues(4), ticket(31),
         issues(6), ticket(43), issues(7)]

NOW_NEXT = f"""\
| Horizon | Version | State | You can … | Done when … | Links |
| --- | --- | --- | --- | --- | --- |
| Now | 0.0.2 | live-checked | You can see the same list on your phone. | Done when the list opens on a real phone (#21). | [milestone]({GH}/milestone/3) · spec [#20]({GH}/issues/20) · live check [#21]({GH}/issues/21) |
| Now | 0.0.3 | built | You can send a message to a thread. | Done when one message reaches one real thread (#31), and no other. | [milestone]({GH}/milestone/4) · spec [#30]({GH}/issues/30) · live check [#31]({GH}/issues/31) |
| Now | 0.0.4 | building | You can start new threads \\| and attach files. | Done when one new thread starts on a real account (#43). | [milestone]({GH}/milestone/6) · spec [#40]({GH}/issues/40) · live check [#43]({GH}/issues/43) |
| Next | 0.0.10 | being grilled | You can keep a fleet running with the lid shut. | Done when the lid stays shut for a whole day. | [milestone]({GH}/milestone/7) · [grill](grills/2026-01-07-ten.md) |"""

PICTURE = """\
```mermaid
flowchart LR
  subgraph now ["Now"]
    v0_0_2["0.0.2: live-checked"]
    v0_0_3["0.0.3: built"]
    v0_0_4["0.0.4: building"]
  end
  subgraph next ["Next"]
    v0_0_10["0.0.10: being grilled"]
  end
  v0_0_2 --> v0_0_3 --> v0_0_4 --> v0_0_10
```"""

VERSIONS = f"""\
| Version | State | You can … | Done when … | Links |
| --- | --- | --- | --- | --- |
| 0.0.1 | published | You can list your threads in the terminal. | Done when the owner lists their threads on a real machine (#11). | [milestone]({GH}/milestone/1) · spec [#10]({GH}/issues/10) · live check [#11]({GH}/issues/11) · [grill](docs/grills/2026-01-01-first-steps.md) |
| 0.0.2 | live-checked | You can see the same list on your phone. | Done when the list opens on a real phone (#21). | [milestone]({GH}/milestone/3) · spec [#20]({GH}/issues/20) · live check [#21]({GH}/issues/21) |
| 0.0.3 | built | You can send a message to a thread. | Done when one message reaches one real thread (#31), and no other. | [milestone]({GH}/milestone/4) · spec [#30]({GH}/issues/30) · live check [#31]({GH}/issues/31) |
| 0.0.4 | building | You can start new threads \\| and attach files. | Done when one new thread starts on a real account (#43). | [milestone]({GH}/milestone/6) · spec [#40]({GH}/issues/40) · live check [#43]({GH}/issues/43) |
| 0.0.10 | being grilled | You can keep a fleet running with the lid shut. | Done when the lid stays shut for a whole day. | [milestone]({GH}/milestone/7) · [grill](docs/grills/2026-01-07-ten.md) |"""

# What the sample pages hold between their markers before a run.
OLD_NOW_NEXT = "| Old | table |\n| --- | --- |\n| stale | row |"
OLD_PICTURE = "an old picture"
OLD_VERSIONS = "| Version | What you get |\n| --- | --- |\n| 0.0.0 | a stale row |"


def region(name, body):
    return f"<!-- roadmap:{name}:begin -->\n{body}\n<!-- roadmap:{name}:end -->"


def sample(name):
    return (FIX / name).read_text(encoding="utf-8")


def expected_roadmap(now_next=NOW_NEXT, picture=PICTURE):
    text = sample("ROADMAP.md")
    for name, old, new in (("now-next", OLD_NOW_NEXT, now_next), ("picture", OLD_PICTURE, picture)):
        before = region(name, old)
        assert text.count(before) == 1, f"the sample ROADMAP.md lost its {name} region"
        text = text.replace(before, region(name, new))
    return text


def expected_status(versions=VERSIONS):
    text = sample("STATUS.md")
    before = region("versions", OLD_VERSIONS)
    assert text.count(before) == 1, "the sample STATUS.md lost its versions region"
    return text.replace(before, region("versions", versions))


def world():
    with open(FIX / "world.json", encoding="utf-8") as f:
        return json.load(f)


def milestone(w, title):
    found = [m for m in w["milestones"] if isinstance(m, dict) and m.get("title") == title]
    assert len(found) == 1, f"the sample world has no single milestone {title}"
    return found[0]


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
        (self.root / "docs").mkdir(parents=True)
        shutil.copyfile(FIX / "ROADMAP.md", self.roadmap)
        shutil.copyfile(FIX / "STATUS.md", self.status)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        (self.bin / "gh").symlink_to(FIX / "gh")

    def fresh_pages(self):
        """The sample pages again, for each subtest: subtests share nothing."""
        shutil.copyfile(FIX / "ROADMAP.md", self.roadmap)
        shutil.copyfile(FIX / "STATUS.md", self.status)

    @property
    def roadmap(self):
        return self.root / "docs" / "ROADMAP.md"

    @property
    def status(self):
        return self.root / "STATUS.md"

    def run_roadmap(self, w=None, *args, env=None, path=None):
        world_file = self.tmp / "world.json"
        world_file.write_text(json.dumps(world() if w is None else w), encoding="utf-8")
        log = self.tmp / "gh.log"
        if log.exists():
            log.unlink()
        full_env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_GH_")}
        full_env.update({
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}" if path is None else path,
            "FAKE_GH_WORLD": str(world_file),
            "FAKE_GH_LOG": str(log),
        })
        full_env.update(env or {})
        proc = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True, timeout=60, env=full_env, cwd=self.tmp)
        calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        return Run(proc, calls)

    def read(self, path):
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()

    def assert_pages(self, roadmap, status):
        self.assertEqual(self.read(self.roadmap), roadmap)
        self.assertEqual(self.read(self.status), status)

    def assert_untouched(self):
        self.assert_pages(sample("ROADMAP.md"), sample("STATUS.md"))


class RepositorySettings(Case):
    """#1279: the reads follow the clone ({owner}/{repo}) and the one public
    repository setting; generated links follow the repository read."""

    def test_tags_come_from_the_public_repo_setting(self):
        r = self.run_roadmap(None, "--public-repo", "synthetic-owner/public-repo",
                             env={"FAKE_GH_PUBLIC": "synthetic-owner/public-repo"})
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.calls, [TAGS.replace("jparker2006/OpenWiz", "synthetic-owner/public-repo")
                                   if c == TAGS else c for c in CALLS])
        self.assert_pages(expected_roadmap(), expected_status())

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
                self.assert_untouched()

    def test_generated_links_follow_the_repository_read(self):
        other = "https://github.com/synthetic-owner/other-repo"
        w = json.loads(json.dumps(world()).replace(GH, other))
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assert_pages(expected_roadmap(NOW_NEXT.replace(GH, other)),
                          expected_status(VERSIONS.replace(GH, other)))
        self.assertNotIn("example-owner", self.read(self.roadmap) + self.read(self.status))


def outside(text, names):
    """The page with each named region's body cut out: its hand-written part."""
    for name in names:
        begin, end = f"<!-- roadmap:{name}:begin -->\n", f"\n<!-- roadmap:{name}:end -->"
        head, rest = text.split(begin)
        _, tail = rest.split(end)
        text = head + begin + "<cut>" + end + tail
    return text


class GeneratedParts(Case):
    """AC1: on synthetic milestones, the generated parts match them exactly,
    and the hand-written parts are untouched."""

    def test_the_generated_parts_match_the_milestones(self):
        r = self.run_roadmap()
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.out, "docs/ROADMAP.md: updated\nSTATUS.md: updated\n")
        self.assert_pages(expected_roadmap(), expected_status())

    def test_the_hand_written_parts_are_untouched(self):
        r = self.run_roadmap()
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(outside(self.read(self.roadmap), ["now-next", "picture"]),
                         outside(sample("ROADMAP.md"), ["now-next", "picture"]))
        self.assertEqual(outside(self.read(self.status), ["versions"]),
                         outside(sample("STATUS.md"), ["versions"]))
        self.assertTrue(self.read(self.roadmap).endswith("The last line has no newline."))

    def test_running_it_twice_changes_nothing(self):
        first = self.run_roadmap()
        self.assertEqual(first.code, 0, first.err)
        before = [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in (self.roadmap, self.status)]
        second = self.run_roadmap()
        self.assertEqual((second.code, second.err), (0, ""))
        self.assertEqual(second.out, "docs/ROADMAP.md: unchanged\nSTATUS.md: unchanged\n")
        after = [(p.read_bytes(), p.stat().st_mtime_ns, p.stat().st_ino) for p in (self.roadmap, self.status)]
        self.assertEqual(after, before)

    def test_it_makes_exactly_these_reads_and_nothing_else(self):
        r = self.run_roadmap()
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(r.calls, CALLS)


class States(Case):
    """A version's state comes from its tag, its live-check ticket, its
    release branch and its spec's tickets, each matched exactly."""

    def states(self, w):
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 0, r.err)
        rows = [line for line in self.read(self.status).splitlines() if line.startswith("| 0.")]
        return {row.split(" | ")[0][2:]: row.split(" | ")[1] for row in rows}

    def test_each_state_from_the_sample_world(self):
        # v0.0.20 doesn't publish 0.0.2; release-0.0.4-no-send doesn't build
        # 0.0.4; 0.0.10's spec has no ticket, so it is still being grilled.
        self.assertEqual(self.states(world()), {
            "0.0.1": "published", "0.0.2": "live-checked", "0.0.3": "built",
            "0.0.4": "building", "0.0.10": "being grilled"})

    def test_a_live_check_closed_as_not_planned_is_not_a_pass(self):
        w = world()
        w["issues"]["3"][1]["state_reason"] = "not_planned"
        self.assertEqual(self.states(w)["0.0.2"], "built")

    def test_a_tag_publishes_whatever_else_is_missing(self):
        w = world()
        w["public_tags"].append("refs/tags/v0.0.10")
        self.assertEqual(self.states(w)["0.0.10"], "published")

    def test_specs_in_number_order_and_each_grill_once(self):
        w = world()
        milestone(w, "0.0.4")["description"] += ("\nGrills: docs/grills/b-later.md, then docs/grills/a-first.md,"
                                                 " and docs/grills/b-later.md again.")
        w["issues"]["6"].append({"number": 39, "state": "open", "state_reason": None, "sub_issues": 4,
                                 "html_url": f"{GH}/issues/39"})
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        expected = row(VERSIONS, "| 0.0.4 |").replace(
            f"[milestone]({GH}/milestone/6) · spec [#40]",
            f"[milestone]({GH}/milestone/6) · spec [#39]({GH}/issues/39) · spec [#40]").replace(
            f"live check [#43]({GH}/issues/43) |",
            f"live check [#43]({GH}/issues/43) · [grill](docs/grills/b-later.md) · [grill](docs/grills/a-first.md) |")
        self.assertEqual(row(self.read(self.status), "| 0.0.4 |"), expected)

    def test_the_picture_with_one_version_and_with_none(self):
        w = world()
        w["public_tags"] += ["refs/tags/v0.0.2", "refs/tags/v0.0.3", "refs/tags/v0.0.10"]
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 0, r.err)
        one = ('```mermaid\nflowchart LR\n  subgraph now ["Now"]\n    v0_0_4["0.0.4: building"]\n  end\n```')
        self.assertEqual(self.read(self.roadmap), expected_roadmap(
            "\n".join(NOW_NEXT.split("\n")[:2] + [row(NOW_NEXT, "| Now | 0.0.4 |")]), one))
        self.fresh_pages()
        w["public_tags"].append("refs/tags/v0.0.4")
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual(self.read(self.roadmap), expected_roadmap("\n".join(NOW_NEXT.split("\n")[:2]),
                                                                   "```mermaid\nflowchart LR\n```"))

    def test_a_published_version_leaves_now_and_next(self):
        w = world()
        w["public_tags"].append("refs/tags/v0.0.2")
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 0, r.err)
        now_next = NOW_NEXT.split("\n")
        now_next = "\n".join(line for line in now_next if not line.startswith("| Now | 0.0.2 |"))
        picture = (PICTURE.replace('    v0_0_2["0.0.2: live-checked"]\n', "")
                   .replace("v0_0_2 --> ", ""))
        self.assertEqual(self.read(self.roadmap), expected_roadmap(now_next, picture))


def row(text, start):
    """The one line of TEXT that starts with START."""
    found = [line for line in text.split("\n") if line.startswith(start)]
    assert len(found) == 1, f"{len(found)} lines start with {start!r}"
    return found[0]


def swap(text, start, old, new):
    """TEXT with OLD replaced by NEW in its one line that starts with START."""
    line = row(text, start)
    assert line.count(old) == 1, f"{old!r} is not once in {line!r}"
    return text.replace(line, line.replace(old, new))


class MissingLines(Case):
    """AC2: a milestone missing its outcome or done line is listed, not guessed."""

    def test_a_missing_outcome_is_listed_and_shown_missing(self):
        w = world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("You can send a message to a thread.\n", "")
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.3: no "You can …" line in its milestone\n')
        self.assertEqual(r.out, "docs/ROADMAP.md: updated\nSTATUS.md: updated\n")
        self.assert_pages(
            expected_roadmap(swap(NOW_NEXT, "| Now | 0.0.3 |", "You can send a message to a thread.", "_missing_")),
            expected_status(swap(VERSIONS, "| 0.0.3 |", "You can send a message to a thread.", "_missing_")))

    def test_no_description_lists_both_lines(self):
        w = world()
        milestone(w, "0.0.10")["description"] = None
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.10: no "You can …" line in its milestone\n'
                                'roadmap: 0.0.10: no "Done when …" line in its milestone\n')
        now_next = swap(NOW_NEXT, "| Next | 0.0.10 |",
                        "You can keep a fleet running with the lid shut. | Done when the lid stays shut for a whole day.",
                        "_missing_ | _missing_")
        now_next = swap(now_next, "| Next | 0.0.10 |", " · [grill](grills/2026-01-07-ten.md)", "")
        versions = swap(VERSIONS, "| 0.0.10 |",
                        "You can keep a fleet running with the lid shut. | Done when the lid stays shut for a whole day.",
                        "_missing_ | _missing_")
        versions = swap(versions, "| 0.0.10 |", " · [grill](docs/grills/2026-01-07-ten.md)", "")
        self.assert_pages(expected_roadmap(now_next), expected_status(versions))

    def test_two_done_lines_are_listed_and_neither_is_read(self):
        w = world()
        milestone(w, "0.0.2")["description"] += "\nDone when a second line says so (#20)."
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.2: 2 "Done when …" lines in its milestone\n')
        self.assertNotIn(ticket(21), r.calls)
        self.assertNotIn(ticket(20), r.calls)
        now_next = swap(NOW_NEXT, "| Now | 0.0.2 |", "Done when the list opens on a real phone (#21).",
                        "_missing (2 lines)_")
        now_next = swap(now_next, "| Now | 0.0.2 |", "live-checked", "built")
        now_next = swap(now_next, "| Now | 0.0.2 |", f" · live check [#21]({GH}/issues/21)", "")
        versions = swap(VERSIONS, "| 0.0.2 |", "Done when the list opens on a real phone (#21).",
                        "_missing (2 lines)_")
        versions = swap(versions, "| 0.0.2 |", "live-checked", "built")
        versions = swap(versions, "| 0.0.2 |", f" · live check [#21]({GH}/issues/21)", "")
        picture = PICTURE.replace('"0.0.2: live-checked"', '"0.0.2: built"')
        self.assert_pages(expected_roadmap(now_next, picture), expected_status(versions))

    def test_two_outcome_lines_are_listed(self):
        w = world()
        milestone(w, "0.0.3")["description"] += "\nYou can also send two."
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.3: 2 "You can …" lines in its milestone\n')
        self.assertEqual(row(self.read(self.status), "| 0.0.3 |"),
                         row(VERSIONS, "| 0.0.3 |").replace("You can send a message to a thread.", "_missing (2 lines)_"))

    def test_look_alike_words_are_not_lines(self):
        w = world()
        milestone(w, "0.0.3")["description"] += "\nYou cannot send two.\nYou can'\nDone whenever it is.\nDone, when asked."
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assert_pages(expected_roadmap(), expected_status())

    def test_lone_carriage_returns_split_lines(self):
        w = world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("\n", "\r")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assert_pages(expected_roadmap(), expected_status())

    def test_no_issues_and_no_tags_at_all(self):
        w = world()
        w["public_tags"] = []
        del w["issues"]["7"]
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(row(self.read(self.status), "| 0.0.1 |"), row(VERSIONS, "| 0.0.1 |").replace("published", "live-checked"))
        self.assertEqual(row(self.read(self.status), "| 0.0.10 |"), row(VERSIONS, "| 0.0.10 |"))

    def test_a_line_counts_only_when_it_starts_with_its_words(self):
        w = world()
        m = milestone(w, "0.0.4")
        m["description"] = m["description"].replace("You can start", "- You can start")
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, 'roadmap: 0.0.4: no "You can …" line in its milestone\n')
        self.assertIn("| Now | 0.0.4 | building | _missing_ |", self.read(self.roadmap))

    def test_a_lane_needs_no_lines(self):
        w = world()
        milestone(w, "Infra")["description"] = None
        milestone(w, "0.0.X")["description"] = "Nothing here."
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assert_pages(expected_roadmap(), expected_status())

    def test_running_it_twice_with_a_gap_changes_nothing(self):
        w = world()
        milestone(w, "0.0.10")["description"] = "You can keep a fleet running with the lid shut."
        first = self.run_roadmap(w)
        self.assertEqual(first.code, 3)
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.roadmap, self.status)]
        second = self.run_roadmap(w)
        self.assertEqual((second.code, second.err), (3, 'roadmap: 0.0.10: no "Done when …" line in its milestone\n'))
        self.assertEqual(second.out, "docs/ROADMAP.md: unchanged\nSTATUS.md: unchanged\n")
        self.assertEqual([(p.read_bytes(), p.stat().st_mtime_ns) for p in (self.roadmap, self.status)], before)


class LiveCheckTicket(Case):
    """The first #N on the "Done when …" line names the live-check ticket,
    wherever it is; with no #N, the version can't read as live-checked."""

    def test_the_ticket_is_read_wherever_it_is(self):
        w = world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(#99, then #31)")
        w["outside"] = [{"number": 99, "state": "closed", "state_reason": "completed",
                         "html_url": f"{GH}/issues/99"}]
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.calls, [c if c != ticket(31) else ticket(99) for c in CALLS])
        self.assertIn(f"| 0.0.3 | live-checked | You can send a message to a thread. | "
                      f"Done when one message reaches one real thread (#99, then #31), and no other. | "
                      f"[milestone]({GH}/milestone/4) · spec [#30]({GH}/issues/30) · live check [#99]({GH}/issues/99) |",
                      self.read(self.status))

    def test_only_a_whole_ticket_number_counts(self):
        w = world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(step 2 of 3: not #0, not #44abc, but #31)")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.calls, CALLS)

    def test_only_closed_as_completed_is_a_pass(self):
        for state, reason in (("closed", "duplicate"), ("closed", None), ("open", "completed"), ("open", "reopened")):
            with self.subTest(state=state, reason=reason):
                self.fresh_pages()
                w = world()
                w["issues"]["3"][1].update(state=state, state_reason=reason)
                r = self.run_roadmap(w)
                self.assertEqual((r.code, r.err), (0, ""))
                self.assertIn("| 0.0.2 | built |", self.read(self.status))

    def test_a_pull_request_is_not_a_live_check_ticket(self):
        w = world()
        m = milestone(w, "0.0.3")
        m["description"] = m["description"].replace("(#31)", "(#99)")
        w["outside"] = [{"number": 99, "state": "closed", "state_reason": "completed", "pull": True,
                         "html_url": f"{GH}/pull/99"}]
        r = self.run_roadmap(w)
        self.assertEqual(r.code, 3)
        self.assertEqual(r.err, "roadmap: 0.0.3: its live-check ticket #99 is a pull request\n")
        self.assertIn(f"| 0.0.3 | built | You can send a message to a thread. | "
                      f"Done when one message reaches one real thread (#99), and no other. | "
                      f"[milestone]({GH}/milestone/4) · spec [#30]({GH}/issues/30) |", self.read(self.status))

    def test_a_done_line_with_no_ticket_never_reads_as_live_checked(self):
        w = world()
        m = milestone(w, "0.0.2")
        m["description"] = m["description"].replace(" (#21)", "")
        r = self.run_roadmap(w)
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertNotIn(ticket(21), r.calls)
        self.assertIn(f"| 0.0.2 | built | You can see the same list on your phone. | "
                      f"Done when the list opens on a real phone. | "
                      f"[milestone]({GH}/milestone/3) · spec [#20]({GH}/issues/20) |", self.read(self.status))


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
    """The sample world, with 0.0.4's outcome public-safe (no "|")."""
    w = world()
    m = milestone(w, "0.0.4")
    m["description"] = m["description"].replace("threads | and", "threads and")
    return w


class Public(Case):
    """AC3: --public writes the short public roadmap, Now and Next only, one
    line each, with no private path, issue number, name or Later idea."""

    def setUp(self):
        super().setUp()
        self.out_dir = self.tmp / "public"
        self.out_dir.mkdir()
        self.public = self.out_dir / "ROADMAP.md"

    def fresh_pages(self):
        super().fresh_pages()
        if self.public.exists():
            self.public.unlink()

    def run_public(self, w):
        return self.run_roadmap(w, "--public", str(self.public))

    def test_the_public_roadmap_is_now_and_next_one_line_each(self):
        r = self.run_public(public_world())
        self.assertEqual((r.code, r.err), (0, ""))
        self.assertEqual(r.out, f"{self.public}: updated\n")
        self.assertEqual(self.read(self.public), PUBLIC)
        self.assertEqual(r.calls, CALLS)
        self.assert_untouched()
        self.assertEqual(sorted(p.name for p in self.out_dir.iterdir()), ["ROADMAP.md"])

    def test_nothing_private_reaches_it(self):
        w = public_world()
        # Private words everywhere but a Now or Next "You can …" line: a
        # published version, a lane, the done lines and the links. The sample
        # pages' Later ideas are there too.
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
                self.fresh_pages()
                w = public_world()
                m = milestone(w, "0.0.3")
                m["description"] = m["description"].replace(line, planted)
                r = self.run_public(w)
                self.assertEqual(r.code, 1)
                self.assertEqual(r.err, f'roadmap: --public: 0.0.3\'s "You can …" line holds {holds}; nothing written\n')
                self.assertEqual(r.out, "")
                self.assertFalse(self.public.exists())
                self.assert_untouched()

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
                self.fresh_pages()
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
    """W with milestone TITLE's answer line replaced by TEXT, exactly."""
    w["milestones"] = [{"__raw__": text} if isinstance(m, dict) and m.get("title") == title else m
                       for m in w["milestones"]]
    return w


GOOD_LINE = ('{"description":null,"html_url":"https://github.com/example-owner/example-repo/milestone/1",'
             '"number":1,"title":"0.0.1"}')


class FailsClosed(Case):
    """Anything it can't read, or read exactly, stops it before it writes."""

    def assert_stopped(self, r, err=None, prefix=None):
        self.assertEqual(r.code, 1, r.err)
        self.assertEqual(r.out, "")
        if err is not None:
            self.assertEqual(r.err, err)
        else:
            self.assertTrue(r.err.startswith(prefix), r.err)
            self.assertTrue(r.err.endswith("; nothing written\n"), r.err)
            self.assertEqual(r.err.count("\n"), 1, r.err)
        self.assert_untouched()
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["STATUS.md", "docs"])
        self.assertEqual(sorted(p.name for p in (self.root / "docs").iterdir()), ["ROADMAP.md"])

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
                    self.fresh_pages()
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
                self.fresh_pages()
                self.assertEqual(json.loads(GOOD_LINE)["title"], "0.0.1")
                self.assert_stopped(self.run_roadmap(raw(world(), "0.0.1", text)), prefix="roadmap: milestones: ")

    def test_a_bad_issue_answer_writes_nothing(self):
        good = {"number": 30, "state": "open", "state_reason": None, "sub_issues": 1, "html_url": f"{GH}/issues/30"}
        for change in ({"sub_issues": None}, {"sub_issues": -1}, {"state": "merged"}, {"state_reason": 3},
                       {"html_url": "http://github.com/x"}, {"extra": 1}):
            with self.subTest(change=change):
                self.fresh_pages()
                w = world()
                w["issues"]["4"][0] = {**good, **change}
                self.assert_stopped(self.run_roadmap(w), prefix="roadmap: milestone 0.0.3's issues: ")

    def test_a_bad_ticket_answer_writes_nothing(self):
        good = {"number": 31, "state": "open", "state_reason": None, "pull": False, "html_url": f"{GH}/issues/31"}
        for change in ({"number": 32}, {"number": 31.0}, {"number": True}, {"pull": "no"}, {"pull": None},
                       {"state": "done"}, {"html_url": None}, {"state_reason": 3}):
            with self.subTest(change=change):
                self.fresh_pages()
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
                self.fresh_pages()
                self.assert_stopped(self.run_roadmap(None, env={fault: "milestones?state"}), err=err)

    def test_a_blank_line_in_an_answer_writes_nothing(self):
        self.assert_stopped(self.run_roadmap(raw(world(), "0.0.1", "")),
                            err="roadmap: milestones: a blank line in the answer; nothing written\n")

    def test_a_ref_outside_its_read_writes_nothing(self):
        for key, ref, what in (("heads", "refs/heads/main", "release branches"),
                               ("public_tags", "refs/heads/v0.0.3", "public tags"),
                               ("public_tags", "refs/tags/release-0.0.3", "public tags")):
            with self.subTest(ref=ref):
                self.fresh_pages()
                w = world()
                w[key].append(ref)
                self.assert_stopped(self.run_roadmap(w), prefix=f"roadmap: {what}: a ref outside ")

    def test_a_milestone_that_is_neither_a_version_nor_a_lane_stops_it(self):
        for title in ("Someday", "0.0.08", "v0.0.9", "0.0.x", " 0.0.9", "0.0.9 ", "0.1", "infra"):
            with self.subTest(title=title):
                self.fresh_pages()
                w = world()
                milestone(w, "0.0.10")["title"] = title
                self.assert_stopped(self.run_roadmap(w), err=f"roadmap: milestone {title!r} is neither a version"
                                                             " (N.N.N) nor a lane (Infra, 0.0.X); nothing written\n")

    def test_two_milestones_for_one_version_stop_it(self):
        w = world()
        milestone(w, "0.0.10")["title"] = "0.0.3"
        self.assert_stopped(self.run_roadmap(w), err="roadmap: two milestones are called 0.0.3; nothing written\n")

    def test_bad_markers_stop_it_before_any_read(self):
        nb, ne = "<!-- roadmap:now-next:begin -->", "<!-- roadmap:now-next:end -->"
        pb, pe = "<!-- roadmap:picture:begin -->", "<!-- roadmap:picture:end -->"
        vb = "<!-- roadmap:versions:begin -->"
        for page, old, new, err in (
            ("ROADMAP", nb + "\n", "",
             f"docs/ROADMAP.md: 0 lines are exactly {nb} (one is needed)"),
            ("ROADMAP", pe, pe + " ",
             f"docs/ROADMAP.md: 0 lines are exactly {pe} (one is needed)"),
            ("ROADMAP", ne, ne + "\n" + ne,
             f"docs/ROADMAP.md: 2 lines are exactly {ne} (one is needed)"),
            ("ROADMAP", f"{nb}\n| Old | table |\n| --- | --- |\n| stale | row |\n{ne}",
             f"{ne}\n| Old | table |\n| --- | --- |\n| stale | row |\n{nb}",
             "docs/ROADMAP.md: the now-next region ends before it begins"),
            ("ROADMAP", f"{ne}\n\nBetween the two regions, hand-written.\n\n{pb}",
             f"\nBetween the two regions, hand-written.\n\n{pb}\n{ne}",
             "docs/ROADMAP.md: the now-next and picture regions overlap"),
            ("ROADMAP", f"{ne}\n\nBetween the two regions, hand-written.\n\n{pb}\nan old picture\n{pe}",
             f"\nBetween the two regions, hand-written.\n\n{pb}\nan old picture\n{pe}\n{ne}",
             "docs/ROADMAP.md: the now-next and picture regions overlap"),
            ("STATUS", vb, vb.upper(),
             f"STATUS.md: 0 lines are exactly {vb} (one is needed)"),
            ("STATUS", vb, vb + "\r",
             f"STATUS.md: 0 lines are exactly {vb} (one is needed)"),
        ):
            with self.subTest(page=page, err=err):
                self.fresh_pages()
                target = self.roadmap if page == "ROADMAP" else self.status
                text = sample(f"{page}.md")
                self.assertEqual(text.count(old), 1)
                bad = text.replace(old, new)
                with open(target, "w", encoding="utf-8", newline="") as f:
                    f.write(bad)
                try:
                    r = self.run_roadmap()
                    self.assertEqual((r.code, r.out, r.err, r.calls),
                                     (1, "", f"roadmap: {err}; nothing written\n", []))
                    self.assertEqual(self.read(target), bad)
                finally:
                    with open(target, "w", encoding="utf-8", newline="") as f:
                        f.write(text)

    def test_regions_in_either_order(self):
        text = sample("ROADMAP.md")
        now_next = region("now-next", OLD_NOW_NEXT)
        picture = region("picture", OLD_PICTURE)
        swapped = text.replace(now_next, "@@N@@").replace(picture, now_next).replace("@@N@@", picture)
        self.roadmap.write_text(swapped, encoding="utf-8")
        r = self.run_roadmap()
        self.assertEqual((r.code, r.err), (0, ""))
        expected = swapped.replace(picture, region("picture", PICTURE)).replace(now_next, region("now-next", NOW_NEXT))
        self.assertEqual(self.read(self.roadmap), expected)

    def test_a_page_it_cant_read_stops_it(self):
        self.status.write_bytes(sample("STATUS.md").encode() + b"\xff")
        r = self.run_roadmap()
        self.assertEqual((r.code, r.out, r.calls), (1, "", []))
        self.assertTrue(r.err.startswith(f"roadmap: could not read {self.status}: "), r.err)
        self.assertEqual(self.read(self.roadmap), sample("ROADMAP.md"))
        self.status.unlink()
        r = self.run_roadmap()
        self.assertEqual((r.code, r.out, r.calls), (1, "", []))
        self.assertEqual(self.read(self.roadmap), sample("ROADMAP.md"))

    def test_a_write_that_fails_halfway_writes_nothing(self):
        # STATUS.md grows past a file size limit the run can't exceed, after
        # docs/ROADMAP.md (well under it) has been prepared.
        status = sample("STATUS.md") + "\n" + ("Long hand-written notes. " * 400)
        self.status.write_text(status, encoding="utf-8")
        limit = 8192
        self.assertLess(len(expected_roadmap().encode()), limit)
        self.assertGreater(len(status.encode()), limit)
        log = self.tmp / "gh.log"
        world_file = self.tmp / "world.json"
        world_file.write_text(json.dumps(world()), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_GH_")}
        env.update({"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_GH_WORLD": str(world_file), "FAKE_GH_LOG": str(log)})
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root)], capture_output=True, text=True, timeout=60,
            env=env, cwd=self.tmp, preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit)))
        self.assertEqual((proc.returncode, proc.stdout), (1, ""), proc.stderr)
        self.assertTrue(proc.stderr.startswith(f"roadmap: could not write {self.status}: "), proc.stderr)
        self.assertTrue(proc.stderr.endswith("; nothing written\n"), proc.stderr)
        self.assertEqual(self.read(self.roadmap), sample("ROADMAP.md"))
        self.assertEqual(self.read(self.status), status)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["STATUS.md", "docs"])
        self.assertEqual(sorted(p.name for p in (self.root / "docs").iterdir()), ["ROADMAP.md"])

    def test_a_page_that_cant_be_put_in_place_says_what_was_written(self):
        # The run's second os.replace fails, as on a full disk: docs/ROADMAP.md
        # is in place already, and the message says so.
        log = self.tmp / "gh.log"
        world_file = self.tmp / "world.json"
        world_file.write_text(json.dumps(world()), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_GH_")}
        env.update({"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                    "FAKE_GH_WORLD": str(world_file), "FAKE_GH_LOG": str(log)})
        driver = (
            "import os, runpy, sys\n"
            "real, calls = os.replace, []\n"
            "def replace(a, b):\n"
            "    calls.append(b)\n"
            "    if len(calls) == 2:\n"
            "        raise OSError(28, 'No space left on device')\n"
            "    return real(a, b)\n"
            "os.replace = replace\n"
            "sys.argv = [sys.argv[1], '--root', sys.argv[2]]\n"
            "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        proc = subprocess.run([sys.executable, "-c", driver, str(SCRIPT), str(self.root)], capture_output=True,
                              text=True, timeout=60, env=env, cwd=self.tmp)
        self.assertEqual((proc.returncode, proc.stdout), (1, ""), proc.stderr)
        self.assertEqual(proc.stderr, f"roadmap: could not write {self.status}: [Errno 28] No space left on device;"
                                      " already written: docs/ROADMAP.md\n")
        self.assert_pages(expected_roadmap(), sample("STATUS.md"))
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["STATUS.md", "docs"])
        self.assertEqual(sorted(p.name for p in (self.root / "docs").iterdir()), ["ROADMAP.md"])

    def test_each_page_keeps_its_mode(self):
        os.chmod(self.roadmap, 0o640)
        os.chmod(self.status, 0o604)
        r = self.run_roadmap()
        self.assertEqual(r.code, 0, r.err)
        self.assertEqual((self.roadmap.stat().st_mode & 0o7777, self.status.stat().st_mode & 0o7777), (0o640, 0o604))

    def test_a_public_file_it_cant_write_writes_nothing(self):
        target = self.tmp / "no-such-folder" / "ROADMAP.md"
        r = self.run_roadmap(public_world(), "--public", str(target))
        self.assertEqual((r.code, r.out), (1, ""))
        self.assertTrue(r.err.startswith(f"roadmap: could not write {target}: "), r.err)
        self.assertFalse(target.exists())
        self.assert_untouched()


if __name__ == "__main__":
    unittest.main(verbosity=2)
