#!/usr/bin/env python3
"""Process-boundary proofs using synthetic GitHub and CloudRoom only."""
import copy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("RELAY_SCRIPT", HERE / "relay.py"))
REPO = "example/synthetic"
BASE = "repos/" + REPO
PULLS = BASE + "/pulls?state=open&per_page=100&page=1"
TICKETS = BASE + "/issues?state=open&labels=ready-for-agent&per_page=100&page=1"
COMMENTS = BASE + "/issues/71/comments?per_page=100&page=1"
REVIEWS = BASE + "/pulls/71/reviews?per_page=100&page=1"
INLINE = BASE + "/pulls/71/comments?per_page=100&page=1"
TICKET = BASE + "/issues/41"
RECORDS = TICKET + "/comments?per_page=100&page=1"
RUNS = BASE + "/actions/runs?head_sha=" + "a" * 40 + "&per_page=100&page=1"
SHA = "a" * 40


def comment(n=901, body=None):
    return {"id": n, "body": body or "VERDICT: CHANGES at " + SHA,
            "updated_at": "2030-01-01T00:01:00Z"}


def world():
    result = {"api": {
        PULLS: [{"number": 71, "body": "Closes #41", "state": "open",
                 "head": {"sha": SHA}, "base": {"ref": "main"}}],
        COMMENTS: [comment()], REVIEWS: [], INLINE: [],
        TICKET: {"number": 41, "state": "open", "labels": [{"name": "ready-for-agent"}]},
        TICKET + "/parent": {"http_status": 404},
        RECORDS: [comment(800, '**Approved on its own by Robin, 2030-01-01:** "yes"'),
                  comment(801, "launch-fleet: started, thread thr_synthetic")],
        RUNS: {"total_count": 0, "workflow_runs": []}},
        "threads": [{"id": "thr_synthetic", "archivedAt": None}]}
    result["api"][TICKETS] = [result["api"][TICKET]]
    return result


def fleet(size):
    result = {"api": {PULLS: [], TICKETS: []}, "threads": []}
    for i in range(size):
        p, t, sha = 1000 + i, 2000 + i, f"{i + 1:040x}"
        issue = {"number": t, "state": "open", "labels": [{"name": "ready-for-agent"}]}
        result["api"][TICKETS].append(issue)
        result["api"][BASE + f"/issues/{t}"] = issue  # old implementation's regression seam
        result["api"][PULLS].append({"number": p, "state": "open", "body": f"Closes #{t}", "head": {"sha": sha}})
        result["api"][BASE + f"/issues/{t}/parent"] = {"http_status": 404}
        result["api"][BASE + f"/issues/{t}/comments?per_page=100&page=1"] = [
            comment(10000 + 3*i, '**Approved on its own by Robin, 2030-01-01:** "yes"'),
            comment(10001 + 3*i, f"launch-fleet: started, thread thr_synthetic_{i}")]
        result["api"][BASE + f"/issues/{p}/comments?per_page=100&page=1"] = [comment(10002 + 3*i, "VERDICT: CHANGES at " + sha)]
        result["api"][BASE + f"/pulls/{p}/reviews?per_page=100&page=1"] = []
        result["api"][BASE + f"/pulls/{p}/comments?per_page=100&page=1"] = []
        result["api"][BASE + f"/actions/runs?head_sha={sha}&per_page=100&page=1"] = {"total_count": 0, "workflow_runs": []}
        result["threads"].append({"id": f"thr_synthetic_{i}", "archivedAt": None})
    return result


class Relay(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.world = world()
        self.env = dict(os.environ, PATH=str(HERE / "fixtures") + os.pathsep + os.environ["PATH"],
                        RELAY_WORLD=str(self.root / "world.json"),
                        RELAY_CALLS=str(self.root / "calls.jsonl"))
        self.env.pop("REVIEW_RELAY_GH_TOKEN", None)
        self.env["GH_TOKEN"] = "synthetic-owner-login"

    def run_relay(self, ok=True):
        Path(self.env["RELAY_WORLD"]).write_text(json.dumps(self.world))
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--repo", REPO,
                                 "--state-dir", str(self.root / "state")],
                                env=self.env, capture_output=True, text=True, timeout=15)
        if ok:
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        else:
            self.assertEqual(result.returncode, 1, result)
            self.assertEqual(result.stderr, "")
            self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
            self.assertTrue(result.stdout.startswith("review-relay: "), result.stdout)
            self.assertNotIn("synthetic private", result.stdout)
        return result

    def calls(self, tool=None):
        path = Path(self.env["RELAY_CALLS"])
        calls = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [c for c in calls if tool is None or c["tool"] == tool]

    def tells(self):
        return [c["args"] for c in self.calls("room-cli") if c["args"][:2] == ["thread", "tell"]]

    def test_verdict_once_and_silent_repeat(self):
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review verdict; read the report on GitHub."]])
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)

    def test_public_checked_builder_resolves_by_title_and_branch(self):
        self.world["api"][RECORDS][1]["body"] = "launch-fleet: start checked, branch room/41-synthetic"
        self.world["threads"][0].update(title="#41: Synthetic", branch="room/41-synthetic")
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)

    def test_public_builder_ambiguity_or_branch_mismatch_never_delivers(self):
        for kind in ("ambiguous", "branch"):
            self.world = world()
            self.world["api"][RECORDS][1]["body"] = "launch-fleet: start checked, branch room/41-synthetic"
            self.world["threads"][0].update(title="#41: Synthetic", branch="room/41-other" if kind == "branch" else "room/41-synthetic")
            if kind == "ambiguous":
                self.world["threads"].append(dict(self.world["threads"][0], id="thr_synduplicate"))
            self.run_relay()
            self.assertEqual(self.tells(), [])

    def test_ci_failure_and_success_at_head_once(self):
        self.world["api"][COMMENTS] = []
        self.world["api"][RUNS] = {"total_count": 3, "workflow_runs": [
            {"id": 301, "run_attempt": 1, "head_sha": SHA, "status": "completed", "conclusion": "failure"},
            {"id": 302, "run_attempt": 1, "head_sha": SHA, "status": "completed", "conclusion": "success"},
            {"id": 303, "run_attempt": 1, "head_sha": "b" * 40, "status": "completed", "conclusion": "failure"}]}
        self.run_relay()
        self.assertEqual(self.tells(), [
            ["thread", "tell", "thr_synthetic", "PR #71 at " + SHA + ": CI failure (run 301, attempt 1); read the run on GitHub."],
            ["thread", "tell", "thr_synthetic", "PR #71 at " + SHA + ": CI success (run 302, attempt 1); read the run on GitHub."]])
        self.run_relay()
        self.assertEqual(len(self.tells()), 2)

    def test_unknown_archived_and_ambiguous_builder_skipped(self):
        for kind in ("unknown", "archived", "ambiguous"):
            with self.subTest(kind=kind):
                self.world = world()
                if kind == "unknown":
                    self.world["api"][RECORDS].pop()
                elif kind == "archived":
                    self.world["threads"][0]["archivedAt"] = "2030-01-01T00:00:00Z"
                else:
                    self.world["api"][RECORDS].append(comment(802, "launch-fleet: started, thread thr_synother"))
                self.run_relay()
                self.assertEqual(self.tells(), [])

    def test_hidden_active_builder_and_checked_record_are_reachable(self):
        self.world["threads"][0]["hidden"] = True
        self.world["api"][RECORDS][1]["body"] = "launch-fleet: start checked, thread thr_synthetic, branch room/41-synthetic"
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)

    def test_unknown_ci_state_refuses_the_whole_check(self):
        self.world["api"][RUNS] = {"total_count": 1, "workflow_runs": [
            {"id": 301, "run_attempt": 1, "head_sha": SHA, "status": "unknown", "conclusion": {"failure": None}}]}
        self.run_relay(ok=False)
        self.assertEqual(self.tells(), [])

    def test_failed_read_tells_nothing(self):
        self.world["fail"] = RUNS  # after a verdict has already been read
        self.run_relay(ok=False)
        self.assertEqual(self.tells(), [])
        self.world.pop("fail")
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)

    def test_conditionals_token_and_read_only_rest(self):
        self.env["REVIEW_RELAY_GH_TOKEN"] = "synthetic-app-token"
        self.run_relay()
        first = len(self.calls("gh"))
        self.run_relay()
        calls = self.calls("gh")
        self.assertEqual(len(calls), first * 2)
        self.assertTrue(all(c["token"] == "synthetic-app-token" for c in calls))
        conditional = [c for c in calls[first:] if "If-None-Match:" in " ".join(c["args"])]
        self.assertEqual(len(conditional), first - 2)  # parent 404 and privacy discovery are not cached
        state = (self.root / "state/state.json").read_text()
        self.assertNotIn("synthetic-app-token", state)
        self.assertNotIn("synthetic-owner-login", state)

    # #725 red run, before the cache fix (synthetic processes only):
    # python3 tools/review-relay/test.py \
    #   Relay.test_cache_keeps_only_fields_needed_for_delivery \
    #   Relay.test_legacy_full_responses_are_compacted_on_304 \
    #   Relay.test_complete_check_evicts_old_heads_pages_and_closed_pulls \
    #   Relay.test_failed_check_does_not_evict_unrequested_cache_entries -v
    # Ran 4 tests in 4.283s; FAILED (failures=4):
    # - compact fields: cached responses still contain unused_payload/base/repo.
    # - legacy 304: 'unused_payload' unexpectedly found in state.json.
    # - complete check: old head's runs and comments page=2 remain cached.
    # - recovery: old head's runs remain cached after the successful check.
    def test_cache_keeps_only_fields_needed_for_delivery(self):
        self.world["api"][RUNS] = {"total_count": 1, "workflow_runs": [
            {"id": 301, "run_attempt": 1, "head_sha": SHA,
             "status": "completed", "conclusion": "failure"}]}
        expected = {
            PULLS: [{"number": 71, "body": "Closes #41", "state": "open", "head": {"sha": SHA}}],
            TICKETS: [{"number": 41, "state": "open", "labels": [{"name": "ready-for-agent"}]}],
            RECORDS: [{"id": row["id"], "body": row["body"]} for row in self.world["api"][RECORDS]],
            COMMENTS: [{"id": 901, "body": "VERDICT: CHANGES at " + SHA}],
            REVIEWS: [], INLINE: [], RUNS: copy.deepcopy(self.world["api"][RUNS])}
        for response in self.world["api"].values():
            rows = response if type(response) is list else [response]
            for row in rows:
                row["unused_payload"] = "synthetic private unused " * 2000
        self.world["api"][PULLS][0]["head"]["repo"] = {"unused": "synthetic"}
        self.world["api"][TICKETS][0]["labels"][0]["description"] = "unused label details"
        self.world["api"][RUNS]["workflow_runs"][0]["repository"] = {"unused": "synthetic"}
        self.run_relay()
        saved = self.root / "state/state.json"
        cache = json.loads(saved.read_text())["cache"]
        self.assertEqual({path: entry["body"] for path, entry in cache.items()}, expected)
        self.assertLess(saved.stat().st_size, 6000)
        self.run_relay()  # compact entities still support 304 and deduplication
        self.assertEqual(len(self.tells()), 2)

    def test_legacy_full_responses_are_compacted_on_304(self):
        self.run_relay()
        saved = self.root / "state/state.json"
        state = json.loads(saved.read_text())
        for path, entry in state["cache"].items():
            entry["body"] = copy.deepcopy(self.world["api"][path])
            rows = entry["body"] if type(entry["body"]) is list else [entry["body"]]
            for row in rows:
                row["unused_payload"] = "synthetic legacy metadata"
        saved.write_text(json.dumps(state))
        first = len(self.calls("gh"))
        self.run_relay()
        self.assertNotIn("unused_payload", saved.read_text())
        self.assertNotIn("updated_at", saved.read_text())
        self.assertEqual(len(self.tells()), 1)
        warm = self.calls("gh")[first:]
        self.assertEqual(sum("If-None-Match:" in " ".join(c["args"]) for c in warm), 7)

    def test_complete_check_evicts_old_heads_pages_and_closed_pulls(self):
        page2 = COMMENTS.replace("&page=1", "&page=2")
        self.world["api"][page2] = [comment(902)]
        self.world["next"] = {COMMENTS: page2}
        self.run_relay()
        saved = self.root / "state/state.json"
        self.assertIn(page2, json.loads(saved.read_text())["cache"])
        new_sha = "b" * 40
        new_runs = RUNS.replace(SHA, new_sha)
        self.world["api"][PULLS][0]["head"]["sha"] = new_sha
        self.world["api"][COMMENTS] = []
        self.world["api"][new_runs] = {"total_count": 0, "workflow_runs": []}
        self.world["next"] = {}
        self.run_relay()
        cache = json.loads(saved.read_text())["cache"]
        self.assertEqual(set(cache), {PULLS, TICKETS, RECORDS, COMMENTS, REVIEWS, INLINE, new_runs})
        self.world["api"][PULLS] = []
        self.run_relay()
        state = json.loads(saved.read_text())
        self.assertEqual(set(state["cache"]), {PULLS})
        self.assertEqual(len(state["sent"]), 2)  # eviction never forgets deliveries
        self.assertEqual(len(self.tells()), 2)

    def test_failed_check_does_not_evict_unrequested_cache_entries(self):
        self.run_relay()
        new_runs = RUNS.replace(SHA, "b" * 40)
        self.world["api"][PULLS][0]["head"]["sha"] = "b" * 40
        self.world["api"][new_runs] = {"total_count": 0, "workflow_runs": []}
        self.world["fail"] = new_runs
        self.run_relay(ok=False)
        saved = self.root / "state/state.json"
        self.assertIn(RUNS, json.loads(saved.read_text())["cache"])
        self.assertEqual(len(self.tells()), 1)
        self.world.pop("fail")
        self.run_relay()
        self.assertNotIn(RUNS, json.loads(saved.read_text())["cache"])
        self.assertEqual(len(self.tells()), 1)

    def test_login_fallback(self):
        self.run_relay()
        self.assertTrue(all(c["token"] == "synthetic-owner-login" for c in self.calls("gh")))

    def test_forty_pr_fleet_has_bounded_cold_and_warm_rest_calls(self):
        self.world = fleet(40)
        self.run_relay()
        cold = len(self.calls("gh"))
        self.assertEqual(len(self.tells()), 40)
        self.run_relay()
        warm = len(self.calls("gh")) - cold
        self.assertEqual(len(self.tells()), 40)
        with self.subTest(cache="cold"):
            self.assertLessEqual(cold, 243)
        with self.subTest(cache="warm"):
            self.assertLessEqual(warm, 243)

    def test_independent_pr_reads_overlap(self):
        self.world = fleet(2)
        self.world["barrier"] = [BASE + "/issues/2000/parent", BASE + "/issues/2001/parent"]
        self.run_relay()
        self.assertEqual(len(self.tells()), 2)

    def test_failed_read_checkpoints_successful_reads_without_telling(self):
        self.world["fail"] = RUNS
        self.run_relay(ok=False)
        saved = self.root / "state/state.json"
        self.assertTrue(saved.is_file(), "a failed check must retain successful reads")
        state = json.loads(saved.read_text())
        self.assertIn(PULLS, state["cache"])
        self.assertEqual(state["sent"], [])
        self.assertEqual(self.tells(), [])

    def test_ticket_comment_edit_is_read_without_metadata_change(self):
        self.run_relay()
        self.run_relay()
        self.world["api"][RECORDS][1]["body"] = "launch-fleet: started, thread thr_synchanged"
        self.world["threads"].append({"id": "thr_synchanged", "archivedAt": None})
        self.run_relay()
        self.assertEqual([tell[2] for tell in self.tells()], ["thr_synthetic", "thr_synchanged"])
        self.assertEqual(sum(c["args"][4] == RECORDS for c in self.calls("gh")), 3)

    def test_blank_review_is_not_a_findings_event(self):
        self.world["api"][COMMENTS] = []
        self.world["api"][REVIEWS] = [{"id": 444, "body": None, "state": "APPROVED"}]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_pending_and_old_head_reviews_are_not_new_findings(self):
        self.world["api"][COMMENTS] = []
        self.world["api"][REVIEWS] = [{"id": 440, "body": "Draft feedback", "state": "PENDING", "commit_id": SHA},
                                               {"id": 441, "body": "Old feedback", "state": "COMMENTED", "commit_id": "b" * 40}]
        self.world["api"][INLINE] = [{"id": 442, "body": "Old inline", "commit_id": "b" * 40}]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_state_never_lives_in_a_checkout(self):
        (self.root / ".git").mkdir()
        self.run_relay(ok=False)
        self.assertEqual(self.calls(), [])

    def test_foreign_references_and_unrelated_comments_do_not_tell(self):
        self.world["api"][PULLS][0]["body"] = "Closes other/repository#41"
        self.run_relay()
        self.assertEqual(self.tells(), [])
        self.world["api"][PULLS][0]["body"] = "Fixes https://github.com/example/synthetic/issues/41"
        self.world["api"][COMMENTS] = [comment(body="Thank you"), comment(902, "VERDICT: CHANGES at " + "b" * 40)]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_builder_replies_and_chatter_are_not_review_events(self):
        # #726: a builder's own reply, and any trivial review or inline body,
        # must not count as "new review findings" for its own builder.
        self.world["api"][COMMENTS] = [
            comment(body="R1 fixed at abc1234: the synthetic case is handled"),
            comment(902, "R2 disputed: the evidence does not hold\n\nSee the report."),
            comment(903, "All findings addressed; ready for re-check."),
        ]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_nonempty_review_and_inline_chatter_are_not_findings(self):
        self.world["api"][COMMENTS] = []
        self.world["api"][REVIEWS] = [{"id": 450, "body": "Thanks!", "state": "COMMENTED", "commit_id": SHA}]
        self.world["api"][INLINE] = [{"id": 451, "body": "Nice work", "commit_id": SHA}]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_reviewer_report_markers_still_tell(self):
        # The fix must keep a real reviewer's report: a current-head verdict,
        # and a findings report whose body leads with its own marker.
        self.world["api"][COMMENTS] = [comment(body="## Findings\nR1: fix the synthetic case")]
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_marker_must_begin_the_body(self):
        # A builder reply that quotes a finding mid-body is still no event,
        # and a genuine inline finding that begins with its marker still tells.
        self.world["api"][COMMENTS] = [
            comment(body="R1 fixed at abc1234. The report said:\n- **R1 [low]** something")]
        self.world["api"][INLINE] = [{"id": 452,
            "body": "- **R2 [medium]** a real inline finding", "commit_id": SHA}]
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_builder_status_headings_are_not_findings(self):
        # #726 (helper R1): a status reply that happens to start with a
        # heading (`## R1 fixed`, `## Findings addressed`) is a builder reply,
        # not the reviewer's report.
        self.world["api"][COMMENTS] = [
            comment(body="## R1 fixed at abc1234: the synthetic case is handled"),
            comment(902, "## Findings addressed\nAll addressed; ready for re-check."),
        ]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_punctuated_builder_replies_are_not_findings(self):
        # #726 (review R2): a status reply stays a status reply with a colon
        # after the marker (`R1: fixed ...`, `## Findings: addressed ...`).
        self.world["api"][COMMENTS] = [
            comment(body="R1: fixed at abc1234; ready for re-check."),
            comment(902, "## Findings: addressed\nAll addressed; ready for re-check."),
        ]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_status_replies_in_any_formatting_are_not_findings(self):
        # #726 (helper R1): case, Markdown emphasis, a qualifier and any
        # punctuation must not turn a status reply into a report.
        self.world["api"][COMMENTS] = [
            comment(body="R1: Fixed at abc1234; ready for re-check."),
            comment(902, "R1: **fixed** at abc1234"),
            comment(903, "R1: now fixed at abc1234; ready for re-check."),
            comment(904, "R1 [medium]: still disputed: synthetic evidence"),
            comment(905, "R1: resolved\u2014ready for re-check."),
            comment(906, "## Findings: **addressed**"),
            comment(907, "## Findings: all addressed"),
            comment(908, "## Findings\nAll findings addressed; ready for re-check."),
        ]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_colon_form_reports_still_tell(self):
        # The colon form of a real finding (`R1: a synthetic bug`) is still the
        # reviewer's report.
        self.world["api"][COMMENTS] = [comment(body="R1: a synthetic bug\nR2: another")]
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_findings_that_mention_a_status_word_still_tell(self):
        # #726 (review R3): a finding whose description merely contains a status
        # word (`... resolved ...`, `Fixed-size ...`, `Resolved hostnames ...`)
        # is a report, not a builder status reply.
        bodies = [
            "## Findings\nR1: The adapter marks a pending write as resolved before confirming delivery.",
            "## Findings\n\nR1: The adapter marks a pending write as resolved before confirming delivery.",
            "R1 [medium]: Fixed-size buffers truncate long attachment names.",
            "R1: Resolved hostnames bypass the private-address check.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                self.root = Path(self.tmp.name)
                self.env["RELAY_WORLD"] = str(self.root / "world.json")
                self.env["RELAY_CALLS"] = str(self.root / "calls.jsonl")
                self.world = world()
                self.world["api"][COMMENTS] = [comment(body=body)]
                self.run_relay()
                self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                                 "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_finding_describing_a_status_still_tells(self):
        # #726 (helper round 3, finding 1): a finding whose prose contains
        # `resolved at startup` is a report; the earlier word-prefix rule
        # dropped it.
        body = "R1: The adapter marks a pending write as resolved at startup before confirming delivery."
        self.world["api"][COMMENTS] = [comment(body=body)]
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_clause_delimited_and_headed_status_replies_are_not_findings(self):
        # #726 (helper round 3, findings 2 and 3): `;`/`.` end the status
        # clause, and a status reply is still a reply under a `Findings`
        # heading.
        self.world["api"][COMMENTS] = [
            comment(body="R1: fixed; ready"),
            comment(902, "R1: resolved. Ready for re-check."),
            comment(903, "## Findings\nR1: fixed at abc1234; ready"),
        ]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_more_status_reply_shapes_are_not_findings(self):
        # #726 (helper round 4, finding 2): a colon and bold braces after the
        # finding id do not hide a status reply.
        self.world["api"][COMMENTS] = [
            comment(body="- **R1 [medium]**: fixed at abc1234; ready."),
            comment(902, "R1: ~~fixed~~ at abc1234; ready"),
            comment(903, "R1: fixed\nR2: fixed"),
        ]
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_findings_block_needs_a_finding_line(self):
        # #726 (helper round 4, findings 3 and 4): a `Findings` block with only
        # chatter or a quoted finding is not a report; the block's own finding
        # line is.
        for body in ("## Findings\nThanks!",
                     "Findings look good. Thanks!",
                     "## Findings\n\nThe previous report said:\n```md\nR1: a synthetic bug\n```"):
            with self.subTest(body=body):
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                self.root = Path(self.tmp.name)
                self.env["RELAY_WORLD"] = str(self.root / "world.json")
                self.env["RELAY_CALLS"] = str(self.root / "calls.jsonl")
                self.world = world()
                self.world["api"][COMMENTS] = [comment(body=body)]
                self.run_relay()
                self.assertEqual(self.tells(), [])

    def test_finding_descriptions_and_headings_still_tell(self):
        # #726: `at` and punctuation end a status clause, but `in <word>` is
        # prose (`Fixed in-memory ...`, `Resolved in the wrong order ...`), a
        # `#`-headed finding is still a finding, and an empty marker is not.
        accept = [
            "R1: Fixed in-memory buffers truncate long attachment names.",
            "R1: Resolved in the wrong order, dependencies are initialized before their prerequisites.",
            "## R1 [medium]: a synthetic bug",
            "## Findings\n\nThe adapter has a synthetic bug.\n\nR1: A pending write is resolved before confirming delivery.",  # noqa: E501
        ]
        reject = ["R1:"]
        for body in accept + reject:
            with self.subTest(body=body):
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                self.root = Path(self.tmp.name)
                self.env["RELAY_WORLD"] = str(self.root / "world.json")
                self.env["RELAY_CALLS"] = str(self.root / "calls.jsonl")
                self.world = world()
                self.world["api"][COMMENTS] = [comment(body=body)]
                self.run_relay()
                expected = [["thread", "tell", "thr_synthetic",
                             "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]] \
                    if body in accept else []
                self.assertEqual(self.tells(), expected)

    def test_bare_findings_report_still_tells(self):
        # #726 (helper R2): the documented headings (`Findings`, a `R<n>: ...`
        # finding line) are the reviewer's report and must tell.
        self.world["api"][COMMENTS] = [comment(body="Findings\n\n- R1 [medium] something")]
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_bare_finding_line_report_still_tells(self):
        self.world["api"][COMMENTS] = [
            comment(body="R1 [medium]: a synthetic finding\nR2 [low]: another")]
        self.run_relay()
        self.assertEqual(self.tells(), [["thread", "tell", "thr_synthetic",
                         "PR #71 at " + SHA + ": new review findings; read the report on GitHub."]])

    def test_findings_edits_and_ci_reruns(self):
        self.world["api"][COMMENTS] = [comment(body="## Findings\nR1: fix the synthetic case")]
        self.run_relay()
        self.assertEqual(self.tells()[0][-1], "PR #71 at " + SHA + ": new review findings; read the report on GitHub.")
        self.world["api"][COMMENTS][0]["body"] += "\nR2: another synthetic case"
        self.run_relay()
        self.assertEqual(len(self.tells()), 2)
        self.world["api"][RUNS] = {"total_count": 1, "workflow_runs": [
            {"id": 333, "run_attempt": 1, "head_sha": SHA, "status": "completed", "conclusion": "failure"}]}
        self.run_relay()
        self.world["api"][RUNS]["workflow_runs"][0].update(run_attempt=2, conclusion="success")
        self.run_relay()
        self.assertEqual(len(self.tells()), 4)

    def test_each_failed_read_sends_nothing(self):
        for path in (p for p in world()["api"] if p != TICKET):
            with self.subTest(path=path):
                self.world["fail"] = path
                self.run_relay(ok=False)
                self.assertEqual(self.tells(), [])
        self.world.pop("fail")
        self.world["room_fail"] = True
        self.run_relay(ok=False)
        self.assertEqual(self.tells(), [])

    def test_uncertain_tell_is_never_retried(self):
        self.world["tell_fail"] = True
        result = self.run_relay(ok=False)
        self.assertIn("delivery uncertain", result.stdout)
        self.world.pop("tell_fail")
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)

    def test_concurrent_check_skips_without_reading(self):
        (self.root / "state").mkdir(mode=0o700)
        with open(self.root / "state/lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.run_relay()
        self.assertEqual(self.calls(), [])

    def test_paginated_comments_and_304_keep_later_pages(self):
        page2 = COMMENTS.replace("&page=1", "&page=2")
        self.world["api"][COMMENTS] = []
        self.world["api"][page2] = [comment()]
        self.world["next"] = {COMMENTS: page2}
        self.run_relay()
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)
        self.assertEqual(sum(c["args"][4] == page2 for c in self.calls("gh")), 2)

    def test_next_page_must_increment_the_original_query(self):
        page2 = COMMENTS.replace("&page=1", "&page=2")
        page3 = COMMENTS.replace("&page=1", "&page=3")
        self.world["api"][page2] = [comment(902)]
        self.world["next"] = {COMMENTS: page3}
        self.world["api"][page3] = []
        result = self.run_relay(ok=False)
        self.assertEqual(result.stdout, "review-relay: pagination changed its page or filters.\n")
        self.assertEqual(self.tells(), [])
        reads = [c["args"][4] for c in self.calls("gh")]
        self.assertNotIn(page2, reads)
        self.assertNotIn(page3, reads)

    def test_skipped_page_proof_catches_missing_equality_guard(self):
        # #798 red run, before the page-2 fixture was added (fakes only):
        # python3 tools/review-relay/test.py \
        #   Relay.test_skipped_page_proof_catches_missing_equality_guard -v
        # FAIL: AssertionError: 0 != 1; the nested skipped-page proof was OK
        # with only the page/filter equality guard deleted.
        guard = '                require(dict(advertised) == expected, "pagination changed its page or filters")\n'
        source = SCRIPT.read_text()
        self.assertEqual(source.count(guard), 1)
        mutant = self.root / "candidate/tools/review-relay/relay.py"
        mutant.parent.mkdir(parents=True)
        mutant.write_text(source.replace(guard, "", 1))
        (self.root / "candidate/skills/launch-fleet/scripts").mkdir(parents=True)
        (self.root / "candidate/skills/launch-fleet/scripts/records.py").write_text((HERE.parents[1] / "skills/launch-fleet/scripts/records.py").read_text())
        result = subprocess.run(
            [sys.executable, "-I", str(HERE / "test.py"),
             "Relay.test_next_page_must_increment_the_original_query", "-v"],
            env=dict(self.env, RELAY_SCRIPT=str(mutant)),
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1, result)
        self.assertIn("FAIL: test_next_page_must_increment_the_original_query", result.stderr)
        self.assertIn("AssertionError: 0 != 1", result.stderr)

    def test_pagination_cannot_escape_through_dot_segments(self):
        unsafe = BASE + "/../../other?per_page=100&page=2"
        self.world["next"] = {PULLS: unsafe}
        self.world["api"][unsafe] = []
        self.run_relay(ok=False)
        self.assertEqual(self.tells(), [])
        self.assertNotIn(unsafe, [call["args"][4] for call in self.calls("gh")])

    def test_malformed_reads_and_corrupt_state_fail_closed(self):
        for path, bad in ((PULLS, {}), (COMMENTS, [{"id": True, "body": "VERDICT: CHANGES at " + SHA}]),
                          (RUNS, {"total_count": 2, "workflow_runs": []})):
            with self.subTest(path=path):
                self.world = world()
                self.world["api"][path] = bad
                self.run_relay(ok=False)
                self.assertEqual(self.tells(), [])
        (self.root / "state/state.json").write_text('{"repo":"example/synthetic","repo":"x"}')
        self.run_relay(ok=False)
        self.assertEqual(self.tells(), [])

    def test_approval_is_required_and_held_tickets_are_skipped(self):
        self.world["api"][RECORDS].pop(0)
        self.run_relay()
        self.assertEqual(self.tells(), [])
        self.world = world()
        self.world["api"][TICKET]["labels"].append({"name": "held"})
        self.run_relay()
        self.assertEqual(self.tells(), [])

    def test_latest_spec_approval_row_selects_ticket(self):
        parent_comments = BASE + "/issues/40/comments?per_page=100&page=1"
        self.world["api"][TICKET + "/parent"] = {"number": 40}
        self.world["api"][RECORDS].pop(0)
        self.world["api"][parent_comments] = [comment(700, "**Plan graph approved by Robin, 2030-01-01, revision 1:**\n\n| #41 | Synthetic | none | ready-for-agent |")]
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)
        self.world["api"][parent_comments].append(comment(701, "**Plan graph approved by Robin, 2030-01-01, revision 2:**\n\n| #41 | Synthetic | none | ready-for-human |"))
        self.world["api"][COMMENTS] = [comment(902)]
        self.run_relay()
        self.assertEqual(len(self.tells()), 1)


if __name__ == "__main__":
    unittest.main()
