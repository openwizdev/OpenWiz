#!/usr/bin/env python3
"""#567: public CLI proofs, synthetic gh/loop snapshots and private state."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get("STALL_ALARM_SCRIPT", HERE / "alarm.py")).resolve()
NOW = 1793620800  # 2026-11-02T12:00:00Z
SHA = "a" * 40
OTHER = "b" * 40


def stamp(seconds):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat().replace("+00:00", "Z")


def comment(body, age=3600, ident=1):
    return {"databaseId": ident, "createdAt": stamp(NOW - age),
            "updatedAt": stamp(NOW - age), "body": body}


def connection(nodes):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}


def pull():
    return {"number": 41, "isDraft": False, "baseRefName": "main",
            "headRefOid": SHA, "mergeable": "MERGEABLE",
            "comments": {"nodes": [comment(f"VERDICT: APPROVE at {SHA}")],
                         "pageInfo": {"hasPreviousPage": False}},
            "commits": {"nodes": [{"commit": {"oid": SHA,
                "statusCheckRollup": {"state": "SUCCESS", "contexts": connection([
                    {"__typename": "CheckRun", "name": name, "status": "COMPLETED",
                     "conclusion": "SUCCESS"} for name in ("ci",)])}}}]}}


def world():
    return {"data": {"repository": {"defaultBranchRef": {"name": "main"},
                      "pullRequests": connection([])}, "search": {"issueCount": 0}}}


class Alarm(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        # The fake is deliberately strict about every external call.
        for name in ("gh", "room-cli"):
            target = self.bin / name
            target.write_text("#!/usr/bin/env python3\n" +
                "import json, os, pathlib, sys, time\n"
                "root = pathlib.Path(os.environ['FAKE_ROOT'])\n"
                "name = pathlib.Path(sys.argv[0]).name\n"
                "with (root / 'calls').open('a') as f: f.write(json.dumps([name, *sys.argv[1:]]) + '\\n')\n"
                "assert (name == 'gh' and sys.argv[1:3] == ['api', 'graphql']) or "
                "(name == 'room-cli' and sys.argv[1:] == ['loop', 'list', '--json']), sys.argv\n"
                "mode = (root / (name + '.mode')).read_text()\n"
                "if mode == 'hang': time.sleep(120)\n"
                "if mode == 'fail': print('synthetic private stdout'); "
                "print('synthetic private stderr', file=sys.stderr); sys.exit(1)\n"
                "if name == 'gh' and 'cursor=next' in sys.argv:\n"
                "    sys.stdout.write((root / 'gh.next.json').read_text()); sys.exit(0)\n"
                "sys.stdout.write((root / (name + '.json')).read_text())\n")
            target.chmod(0o755)
            (self.root / (name + ".mode")).write_text("ok")
        self.github = world()
        # Synthetic repeating fleet. Installed scheduler code advances attempt
        # timestamps even for skipped script output; see 1466-skipped-tick.md.
        self.fleet = {"id": "loop_fixture", "enabled": True, "cron": "*/10 * * * *",
                      "last_error": None, "last_run_at": stamp(NOW - 60)}
        self.fleet_running = True
        self.loops = {"automations": [self.fleet]}

    def run_alarm(self, offset=0, deadline=4, repo="example-owner/example-repo", grace=None,
                  checks=None):
        if self.fleet_running:
            self.fleet["last_run_at"] = stamp(NOW + offset - 60)
        for name, data in (("gh", self.github), ("room-cli", self.loops)):
            (self.root / (name + ".json")).write_text(
                data if isinstance(data, str) else json.dumps(data))
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_ROOT=str(self.root))
        began = time.monotonic()
        proc = subprocess.run([sys.executable, str(SCRIPT), "--repo", repo,
            "--fleet-loop", "loop_fixture", "--state", str(self.root / "state.json"),
            "--now", stamp(NOW + offset), "--deadline", str(deadline),
            *[arg for check in checks or [] for arg in ("--check", check)],
            *([] if grace is None else ["--fleet-grace", str(grace)])],
            env=env, capture_output=True, text=True, timeout=deadline + 3)
        self.assertIn(proc.returncode, (0, 1), proc.stderr)
        self.assertEqual(proc.stderr, "")
        self.assertEqual(proc.returncode, 1 if proc.stdout else 0)
        return proc.stdout.splitlines(), time.monotonic() - began

    def once_clear_recur(self, activate, clear, expected):
        activate()
        lines, _ = self.run_alarm()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(expected, lines[0])
        self.assertEqual(self.run_alarm(600)[0], [])
        self.assertEqual(self.run_alarm(1799)[0], [])
        lines, _ = self.run_alarm(1800)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("JAKE", lines[0])
        self.assertIn(expected, lines[0])
        self.assertEqual(self.run_alarm(2400)[0], [])
        clear()
        self.assertEqual(self.run_alarm(3000)[0], [])
        activate()
        lines, _ = self.run_alarm(3600)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn(expected, lines[0])
        self.assertNotIn("JAKE", lines[0])

    def test_quiet_factory_and_reads(self):
        self.assertEqual(self.run_alarm()[0], [])
        self.assertEqual(self.run_alarm(3600)[0], [])
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual([c[0] for c in calls].count("room-cli"), 2)
        self.assertEqual([c[0] for c in calls].count("gh"), 2)
        query = next(c[c.index("-f") + 1] for c in calls if c[0] == "gh")
        self.assertIn("query=", query)
        self.assertNotIn("mutation", query)

    def test_empty_script_ticks_stay_quiet_then_a_stopped_clock_alarms(self):
        self.fleet_running = False
        # synthetic_assumptions: legacy loop-list envelope/ISO timestamps;
        # attempt evolution comes from the installed scheduler's claim-before-
        # dispatch code, not an observed live skipped tick or agent wake count.
        self.fleet.update(runs=0, next_run_at=stamp(NOW))
        for offset in (0, 600, 1200, 1800, 2400):
            with self.subTest(skipped_tick=offset):
                self.fleet.update(last_run_at=stamp(NOW + offset),
                                  next_run_at=stamp(NOW + offset + 600),
                                  runs=self.fleet["runs"] + 1)
                self.assertEqual(self.run_alarm(offset)[0], [])
        # Once attempts actually stop, the last skipped attempt still ages out.
        self.assertEqual(self.run_alarm(3600)[0], [])
        self.assertEqual(self.run_alarm(3601)[0], ["ALARM: fleet loop last run overdue"])
        self.fleet.update(last_run_at=stamp(NOW + 4200),
                          next_run_at=stamp(NOW + 4800), runs=6)
        self.assertEqual(self.run_alarm(4200)[0], [])

    def test_reads_follow_the_repo_setting(self):
        # #1279: the repository is only --repo. A state file kept for another
        # repository is refused, so a switched loop needs its own state file.
        self.assertEqual(self.run_alarm(repo="synthetic-owner/other-repo")[0], [])
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        read = next(c for c in calls if c[0] == "gh")
        self.assertIn("owner=synthetic-owner", read)
        self.assertIn("name=other-repo", read)
        self.assertIn("recent=repo:synthetic-owner/other-repo is:pr is:merged base:main "
                      "merged:>2026-11-02T11:00:00Z", read)
        self.assertNotIn("example-owner", json.dumps(calls))
        self.assertEqual(self.run_alarm(repo="synthetic-owner/next-repo")[0],
                         ["ALARM: read failed: alarm configuration or local state unavailable"])

    def test_local_managed_cli_requests_json_loop_status(self):
        self.run_alarm()
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual([call for call in calls if call[0] == "room-cli"],
                         [["room-cli", "loop", "list", "--json"]])

    def test_loop_error_once_clear_recur_and_jake(self):
        def activate(): self.loops["automations"][0]["last_error"] = "synthetic timeout"
        def clear(): self.loops["automations"][0]["last_error"] = None
        self.once_clear_recur(activate, clear, "fleet loop")

    def test_disabled_stale_and_never_run_once_escalate_recover_rearm(self):
        for kind, expected in (("disabled", "fleet loop disabled"),
                               ("stale", "fleet loop last run overdue"),
                               ("never", "fleet loop never ran after startup grace")):
            with self.subTest(kind=kind):
                (self.root / "state.json").unlink(missing_ok=True)
                self.fleet_running = True
                self.fleet.update(enabled=True, last_error=None)
                # Persist detector startup before the never-run grace expires.
                if kind == "never":
                    self.fleet_running = False
                    self.fleet["last_run_at"] = None
                self.assertEqual(self.run_alarm(-1201)[0], [])

                def activate():
                    self.fleet["enabled"] = kind != "disabled"
                    self.fleet_running = False
                    self.fleet["last_run_at"] = None if kind == "never" else stamp(NOW - 7 * 86400)

                def clear():
                    self.fleet["enabled"] = True
                    self.fleet_running = True

                self.once_clear_recur(activate, clear, expected)

    def test_cadence_and_grace_boundaries(self):
        self.fleet_running = False
        # Ten-minute cadence plus the default ten-minute grace.
        self.fleet["last_run_at"] = stamp(NOW - 1200)
        self.assertEqual(self.run_alarm()[0], [])
        self.assertEqual(self.run_alarm(1)[0], ["ALARM: fleet loop last run overdue"])
        # Read the monitored cadence again; a 30-minute loop is still healthy.
        self.fleet["cron"] = "*/30 * * * *"
        self.assertEqual(self.run_alarm(2)[0], [])
        self.assertEqual(self.run_alarm(1200)[0], [])
        self.assertEqual(self.run_alarm(1201)[0], ["ALARM: fleet loop last run overdue"])

    def test_offset_and_irregular_cadences_and_custom_grace(self):
        self.fleet_running = False
        for cron, age in (("8,18,28,38,48,58 * * * *", 720),
                          ("0,10,40 * * * *", 1920), ("7 * * * *", 3720),
                          ("* * * * *", 180), ("*/7 * * * *", 540)):
            with self.subTest(cron=cron):
                (self.root / "state.json").unlink(missing_ok=True)
                self.fleet.update(cron=cron, last_run_at=stamp(NOW - age))
                self.assertEqual(self.run_alarm(grace=120)[0], [])
                self.assertEqual(self.run_alarm(1, grace=120)[0],
                                 ["ALARM: fleet loop last run overdue"])

    def test_never_run_grace_persists_between_invocations(self):
        self.fleet_running = False
        self.fleet["last_run_at"] = None
        self.assertEqual(self.run_alarm(grace=120)[0], [])
        self.assertEqual(self.run_alarm(720, grace=120)[0], [])
        self.assertEqual(self.run_alarm(721, grace=120)[0],
                         ["ALARM: fleet loop never ran after startup grace"])

    def test_run_during_read_or_within_future_grace_is_quiet(self):
        self.fleet_running = False
        # --now is captured before the external read. A scheduler can return
        # a timestamp after it, even when the two clocks agree.
        for ahead in (0.001, 1, 600):
            with self.subTest(ahead=ahead):
                (self.root / "state.json").unlink(missing_ok=True)
                self.fleet["last_run_at"] = stamp(NOW + ahead)
                self.assertEqual(self.run_alarm()[0], [])
        (self.root / "state.json").unlink(missing_ok=True)
        self.fleet["last_run_at"] = stamp(NOW + 120)
        self.assertEqual(self.run_alarm(grace=120)[0], [])
        (self.root / "state.json").unlink(missing_ok=True)
        self.fleet["last_run_at"] = stamp(NOW + 121)
        self.assertEqual(self.run_alarm(grace=120)[0],
                         ["ALARM: read failed: loop status unavailable: future timestamp"])

    def test_legacy_state_preserves_an_open_alarm_and_its_escalation_age(self):
        # A pre-#1466 state has no startup timestamp; upgrading must not rearm
        # an existing error or postpone its already-running escalation timer.
        state = {"version": 1, "scope": {"repo": "example-owner/example-repo",
                 "loop": "loop_fixture", "base": "main",
                 "checks": ["ci"]},
                 "alarms": {"loop/error": {"since": NOW - 1200, "escalated": False}}}
        self.fleet["last_error"] = "synthetic timeout"
        for checks in (["ci"], ["web-build", "rust", "web-test"]):
            with self.subTest(checks=checks):
                state["scope"]["checks"] = checks
                (self.root / "state.json").write_text(json.dumps(state))
                self.assertEqual(self.run_alarm()[0], [])
                self.assertEqual(self.run_alarm(600)[0],
                                 ["JAKE: fleet loop last run errored; still open after 30 minutes"])

    def test_default_check_upgrade_preserves_history_and_escalates_on_time(self):
        # The default-name upgrade must keep deduplication, both escalation
        # states, the existing episode ages and the startup grace origin.
        state = {"version": 1, "scope": {"repo": "example-owner/example-repo",
                 "loop": "loop_fixture", "base": "main",
                 "checks": ["web-build", "rust", "web-test"]},
                 "started_at": NOW - 7200,
                 "alarms": {"loop/error": {"since": NOW - 1200, "escalated": False},
                            "github/merges": {"since": NOW - 2400, "escalated": True}}}
        path = self.root / "state.json"
        path.write_text(json.dumps(state))
        self.fleet["last_error"] = "synthetic timeout"
        self.github["data"]["repository"]["pullRequests"]["nodes"] = [pull()]
        self.assertEqual(self.run_alarm()[0], [])
        expected = copy.deepcopy(state)
        expected["scope"]["checks"] = ["ci"]
        self.assertEqual(json.loads(path.read_text()), expected)
        self.assertEqual(self.run_alarm(600)[0],
                         ["JAKE: fleet loop last run errored; still open after 30 minutes"])
        expected["alarms"]["loop/error"]["escalated"] = True
        self.assertEqual(json.loads(path.read_text()), expected)
        self.assertEqual(self.run_alarm(1200)[0], [])

    def test_default_check_upgrade_refuses_every_other_scope_transition(self):
        old_scope = {"repo": "example-owner/example-repo", "loop": "loop_fixture",
                     "base": "main", "checks": ["web-build", "rust", "web-test"]}
        cases = [({**old_scope, field: value}, None) for field, value in (
            ("repo", "synthetic-owner/other-repo"), ("loop", "other_fixture"),
            ("base", "release-fixture"), ("extra", "unexpected"),
            ("checks", ["rust", "web-build", "web-test"]),
            ("checks", ["web-build", "rust"]),
            ("checks", ["web-build", "rust", "web-test", "ci"]))]
        cases += [(old_scope, ["ci", "custom"]), (old_scope, ["custom"]),
                  ({**old_scope, "checks": ["ci"]}, old_scope["checks"])]
        for scope, checks in cases:
            with self.subTest(scope=scope, checks=checks):
                path = self.root / "state.json"
                raw = json.dumps({"version": 1, "scope": scope, "started_at": NOW - 7200,
                                  "alarms": {"loop/error": {"since": NOW - 1200,
                                                            "escalated": False}}})
                path.write_text(raw)
                self.assertEqual(self.run_alarm(checks=checks)[0],
                                 ["ALARM: read failed: alarm configuration or local state unavailable"])
                self.assertEqual(path.read_text(), raw)
                self.assertFalse((self.root / "calls").exists())

    def test_invalid_loop_liveness_fields_fail_loudly(self):
        good = copy.deepcopy(self.fleet)
        self.fleet_running = False
        for field, value in (("enabled", None), ("enabled", "false"), ("enabled", 1),
                             ("cron", None), ("cron", "*/0 * * * *"),
                             ("cron", "60 * * * *"), ("cron", "*/61 * * * *"),
                             ("cron", "0 12 * * *"), ("last_run_at", stamp(NOW + 601))):
            with self.subTest(field=field, value=value):
                (self.root / "state.json").unlink(missing_ok=True)
                self.fleet.clear()
                self.fleet.update(good, **{field: value})
                cause = (": unsupported cadence" if field == "cron" else
                         ": future timestamp" if field == "last_run_at" else "")
                self.assertEqual(self.run_alarm()[0],
                                 ["ALARM: read failed: loop status unavailable" + cause])

    def test_merge_stall_once_clear_recur_and_jake(self):
        self.github["data"]["repository"]["pullRequests"]["nodes"] = [pull()]
        def activate(): self.github["data"]["search"]["issueCount"] = 0
        def clear(): self.github["data"]["search"]["issueCount"] = 1
        self.once_clear_recur(activate, clear, "no merges")

    def test_each_idle_record_once_clear_recur_and_jake(self):
        for kind in ("findings sent", "CI failure sent", "re-check sent"):
            with self.subTest(kind=kind):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                self.github["data"]["search"]["issueCount"] = 1
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                def activate():
                    p["headRefOid"] = SHA
                    suffix = ", thread thr_syn_fixture" if kind == "re-check sent" else ""
                    p["comments"]["nodes"] = [comment(f"launch-fleet: {kind} {SHA}{suffix}")]
                def clear(): p["headRefOid"] = OTHER
                activate()
                lines, _ = self.run_alarm(-1)
                self.assertEqual(lines, [])
                self.once_clear_recur(activate, clear, "idle #41")

    def test_new_record_or_commit_clears_idle_but_discussion_does_not(self):
        self.github["data"]["search"]["issueCount"] = 1
        for newer in ("launch-fleet: review starting " + SHA, "VERDICT: CHANGES at " + SHA,
                      "a plain discussion comment"):
            with self.subTest(newer=newer):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                p["comments"]["nodes"] = [comment("launch-fleet: findings sent " + SHA),
                                          comment(newer, age=300, ident=2)]
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                lines, _ = self.run_alarm()
                self.assertEqual(len(lines), 1 if newer.startswith("a plain") else 0, lines)

    def test_review_record_on_another_pull_does_not_hide_idle_stall(self):
        self.github["data"]["search"]["issueCount"] = 1
        records = [(kind, suffix) for kind in ("review started", "review told again")
                   for suffix in ("", ", thread thr_syn_fixture")]
        records += [("review given up", ": synthetic no verdict"),
                    ("review failed", ", thread thr_syn_fixture: synthetic no verdict"),
                    ("re-check sent", ", thread thr_syn_fixture (synthetic note)")]
        for kind, suffix in records:
            with self.subTest(kind=kind, suffix=suffix):
                (self.root / "state.json").unlink(missing_ok=True)
                idle = pull()
                idle["comments"]["nodes"] = [comment("launch-fleet: CI failure sent " + SHA)]
                other = dict(pull(), number=42)
                other["comments"]["nodes"] = [comment(
                    f"launch-fleet: {kind} {SHA}{suffix}", age=300, ident=2)]
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [idle, other]
                self.assertEqual(self.run_alarm()[0],
                                 ["ALARM: idle #41: 60 minutes after CI failure sent"])

    def test_public_and_legacy_recheck_keep_the_same_idle_boundary(self):
        self.github["data"]["search"]["issueCount"] = 1
        for suffix in ("", ", thread thr_syn_fixture"):
            for age in (0, 3599, 3600, 3601):
                with self.subTest(suffix=suffix, age=age):
                    (self.root / "state.json").unlink(missing_ok=True)
                    idle = pull()
                    idle["comments"]["nodes"] = [comment("launch-fleet: CI failure sent " + SHA)]
                    other = dict(pull(), number=42)
                    other["comments"]["nodes"] = [comment(
                        f"launch-fleet: re-check sent {SHA}{suffix}", age=age, ident=2)]
                    self.github["data"]["repository"]["pullRequests"]["nodes"] = [idle, other]
                    expected = ["ALARM: idle #41: 60 minutes after CI failure sent"]
                    if age >= 3600:
                        expected += ["ALARM: idle #42: 60 minutes after re-check sent"]
                    self.assertEqual(self.run_alarm()[0], expected)

    def test_annotated_sent_records_keep_idle_classification(self):
        self.github["data"]["search"]["issueCount"] = 1
        for kind, suffix in (("findings sent", " (synthetic note)"),
                             ("CI failure sent", ": synthetic note"),
                             ("re-check sent", ", thread thr_syn_fixture (synthetic note)")):
            with self.subTest(kind=kind):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                p["comments"]["nodes"] = [comment(f"launch-fleet: {kind} {SHA}{suffix}")]
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                self.assertEqual(self.run_alarm()[0],
                                 [f"ALARM: idle #41: 60 minutes after {kind}"])

    def test_record_prefixes_require_kind_and_commit_boundaries(self):
        malformed = ["launch-fleet: findings sender " + SHA,
                     "launch-fleet: review startedness " + SHA,
                     "launch-fleet: findings sent " + SHA + "0 synthetic note",
                     "launch-fleet: review given up " + SHA,
                     "launch-fleet: review given up " + SHA + ":"]
        for kind in ("review started", "review told again", "re-check sent"):
            malformed += [f"launch-fleet: {kind} {commit}{suffix}"
                          for commit, suffix in (("not-a-commit", ""), (SHA[:-1], ""),
                                                 (SHA + "0", ""), (SHA, ", thread"),
                                                 (SHA, ", thread !"))]
        for line in malformed:
            with self.subTest(line=line):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                p["comments"]["nodes"] = [comment(line)]
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                self.assertEqual(self.run_alarm()[0],
                                 ["ALARM: read failed: github status unavailable"])

    def test_edited_sent_record_starts_a_new_episode_even_after_missed_ticks(self):
        self.github["data"]["search"]["issueCount"] = 1
        p = pull()
        record = comment("launch-fleet: findings sent " + SHA)
        p["comments"]["nodes"] = [record]
        self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
        self.assertEqual(len(self.run_alarm()[0]), 1)
        # A new action was recorded 30 minutes later, but no check ran until
        # that action itself reached 60 minutes. It is a fresh stall, not
        # 30 more minutes of the previous one.
        record["updatedAt"] = stamp(NOW - 1800)
        lines, _ = self.run_alarm(1800)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("ALARM: idle #41", lines[0])
        self.assertNotIn("JAKE", lines[0])

    def test_merge_needs_latest_approval_green_current_head_and_no_conflict(self):
        variants = []
        p = pull(); p["comments"]["nodes"][0]["body"] = "VERDICT: APPROVE at " + OTHER; variants.append(p)
        p = pull(); p["comments"]["nodes"].append(comment("VERDICT: CHANGES at " + SHA, 10, 2)); variants.append(p)
        p = pull(); p["comments"]["nodes"].append(comment("VERDICT: malformed", 10, 2)); variants.append(p)
        for value in ("CONFLICTING", "UNKNOWN"):
            p = pull(); p["mergeable"] = value; variants.append(p)
        p = pull(); p["isDraft"] = True; variants.append(p)
        p = pull(); p["baseRefName"] = "release-example"; variants.append(p)
        p = pull(); p["commits"]["nodes"][0]["commit"]["oid"] = OTHER; variants.append(p)
        # #964: a FAILURE rollup is not green even when the named check
        # themselves report SUCCESS.
        p = pull(); p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["state"] = "FAILURE"; variants.append(p)
        for name in ("ci",):
            for outcome in ("FAILURE", None, "missing"):
                p = pull(); nodes = p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"]
                if outcome == "missing": nodes[:] = [n for n in nodes if n["name"] != name]
                else: next(n for n in nodes if n["name"] == name)["conclusion"] = outcome
                variants.append(p)
        for p in variants:
            with self.subTest(p=p):
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                self.assertEqual(self.run_alarm()[0], [])

        # synthetic_assumptions: literal legacy StatusContext outcomes, not
        # observed live checks. Only SUCCESS makes the required check green.
        for state, expected in (
            ("SUCCESS", ["ALARM: no merges for 60 minutes with an approved green conflict-free pull request"]),
            ("FAILURE", []), ("PENDING", []), ("ERROR", []),
        ):
            with self.subTest(status_context=state):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]["nodes"] = [
                    {"__typename": "StatusContext", "context": "web-build", "state": "SUCCESS"},
                    {"__typename": "StatusContext", "context": "ci", "state": state},
                    {"__typename": "StatusContext", "context": "web-test", "state": "SUCCESS"},
                ]
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                self.assertEqual(self.run_alarm()[0], expected)

    def test_approval_must_start_the_comment_like_the_fleet(self):
        for prefix in ("\n", " ", "quoted report:\n"):
            with self.subTest(prefix=prefix):
                p = pull()
                p["comments"]["nodes"][0]["body"] = prefix + "VERDICT: APPROVE at " + SHA
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                self.assertEqual(self.run_alarm()[0], [])

    def test_unknown_fleet_record_never_silently_clears_an_idle_stall(self):
        self.github["data"]["search"]["issueCount"] = 1
        for newer in ("launch-fleet: bogus", "launch-fleet: review starting not-a-commit"):
            with self.subTest(newer=newer):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                p["comments"]["nodes"] = [comment("launch-fleet: findings sent " + SHA),
                                          comment(newer, age=300, ident=2)]
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                lines, _ = self.run_alarm()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("read failed", lines[0])

    def test_failed_read_once_recovery_and_bad_shapes(self):
        good = copy.deepcopy(self.github)
        for bad in ("not JSON", '{"data":{},"data":{}}', {"errors": [{"message": "synthetic"}], **good},
                    {"data": {"repository": None}}, []):
            with self.subTest(bad=bad):
                (self.root / "state.json").unlink(missing_ok=True)
                self.github = bad
                lines, _ = self.run_alarm()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("read failed", lines[0])
                self.assertEqual(self.run_alarm(600)[0], [])
                self.github = good
                self.assertEqual(self.run_alarm(1200)[0], [])

    def test_missing_loop_and_failed_command_are_not_healthy(self):
        self.loops["automations"] = []
        lines, _ = self.run_alarm()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("read failed", lines[0])
        self.assertEqual(self.run_alarm(600)[0], [])

    def test_nonzero_read_recovers_and_rearms(self):
        for source in ("gh", "room-cli"):
            with self.subTest(source=source):
                (self.root / (source + ".mode")).write_text("fail")
                lines, _ = self.run_alarm()
                message = ("read failed: loop status unavailable: command failed" if source == "room-cli"
                           else "read failed: github status unavailable")
                self.assertEqual(lines, ["ALARM: " + message])
                # A read alarm that stays open escalates to JAKE once, at 30
                # minutes, exactly like a fleet or github alarm (#964).
                self.assertEqual(self.run_alarm(600)[0], [])
                self.assertEqual(self.run_alarm(1799)[0], [])
                lines, _ = self.run_alarm(1800)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("JAKE", lines[0])
                self.assertIn("read failed", lines[0])
                self.assertEqual(self.run_alarm(2400)[0], [])
                # Recovery is silent and must re-arm the source: failing again
                # alarms afresh, without an escalation, at a new since (#964).
                (self.root / (source + ".mode")).write_text("ok")
                self.assertEqual(self.run_alarm(3000)[0], [])
                (self.root / (source + ".mode")).write_text("fail")
                lines, _ = self.run_alarm(3600)
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("read failed", lines[0])
                self.assertNotIn("JAKE", lines[0])

    def test_loop_cause_changes_preserve_stalls_dedup_and_escalation(self):
        self.fleet["enabled"] = False
        self.assertEqual(self.run_alarm()[0], ["ALARM: fleet loop disabled"])
        self.loops = "synthetic private invalid JSON"
        self.assertEqual(self.run_alarm(600)[0],
                         ["ALARM: read failed: loop status unavailable: invalid JSON"])
        self.loops = {"automations": []}
        self.github["data"]["repository"]["pullRequests"]["nodes"] = [pull()]
        self.assertEqual(self.run_alarm(1200)[0],
                         ["ALARM: no merges for 60 minutes with an approved green conflict-free pull request"])
        # Cause changes keep one read/loop episode and its original age.
        self.assertEqual(self.run_alarm(2399)[0], [])
        self.assertEqual(self.run_alarm(2400)[0],
                         ["JAKE: read failed: loop status unavailable: selected loop missing; still open after 30 minutes"])
        self.assertEqual(self.run_alarm(2401)[0], [])
        state = json.loads((self.root / "state.json").read_text())["alarms"]
        self.assertEqual(state["read/loop"], {"since": NOW + 600, "escalated": True})
        self.assertEqual(state["loop/disabled"], {"since": NOW, "escalated": False})
        self.fleet["enabled"] = True
        self.loops = {"automations": [self.fleet]}
        self.github["data"]["search"]["issueCount"] = 1
        self.assertEqual(self.run_alarm(2500)[0], [])
        self.assertEqual(json.loads((self.root / "state.json").read_text())["alarms"], {})
        self.loops = "synthetic private invalid JSON"
        self.assertEqual(self.run_alarm(2600)[0],
                         ["ALARM: read failed: loop status unavailable: invalid JSON"])

    def test_failed_read_preserves_existing_stall_and_other_source(self):
        self.github["data"]["repository"]["pullRequests"]["nodes"] = [pull()]
        self.assertEqual(len(self.run_alarm()[0]), 1)
        (self.root / "gh.mode").write_text("fail")
        self.loops["automations"][0]["last_error"] = "synthetic error"
        lines, _ = self.run_alarm(600)
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(any("fleet loop" in line for line in lines))
        self.assertTrue(any("read failed" in line for line in lines))
        self.assertEqual(self.run_alarm(1200)[0], [])
        (self.root / "gh.mode").write_text("ok")
        lines, _ = self.run_alarm(1800)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("JAKE: no merges", lines[0])

    def test_open_pull_pagination_and_recent_merge_query(self):
        conn = self.github["data"]["repository"]["pullRequests"]
        conn["nodes"] = [dict(pull(), isDraft=True)]
        conn["pageInfo"] = {"hasNextPage": True, "endCursor": "next"}
        following = world()
        following["data"]["repository"]["pullRequests"]["nodes"] = [dict(pull(), number=42)]
        (self.root / "gh.next.json").write_text(json.dumps(following))
        lines, _ = self.run_alarm()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("no merges", lines[0])
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        reads = [call for call in calls if call[0] == "gh"]
        self.assertEqual(len(reads), 2)
        self.assertIn("cursor=next", reads[1])
        self.assertIn("recent=repo:example-owner/example-repo is:pr is:merged base:main merged:>2026-11-02T11:00:00Z", reads[0])

    def test_loop_malformed_duplicate_and_missing_fields_fail_loudly(self):
        for bad in ([], {}, {"automations": []}, "synthetic private invalid JSON",
                    '{"automations":[],"automations":[]}',
                    {"automations": [{"id": "loop_fixture", "last_run_at": None}]},
                    {"automations": [{"id": "loop_fixture", "last_error": False, "last_run_at": None}]},
                    {"automations": [self.loops["automations"][0]] * 2}):
            with self.subTest(bad=bad):
                (self.root / "state.json").unlink(missing_ok=True)
                self.loops = bad
                lines, _ = self.run_alarm()
                cause = (": invalid JSON" if isinstance(bad, str) else
                         ": selected loop missing" if bad == {"automations": []} else "")
                self.assertEqual(lines, ["ALARM: read failed: loop status unavailable" + cause])

    def test_truncated_nested_connections_fail_loudly(self):
        for section, flag in (("comments", "hasPreviousPage"), ("checks", "hasNextPage")):
            with self.subTest(section=section):
                (self.root / "state.json").unlink(missing_ok=True)
                p = pull()
                conn = p["comments"] if section == "comments" else p["commits"]["nodes"][0]["commit"]["statusCheckRollup"]["contexts"]
                conn["pageInfo"][flag] = True
                self.github["data"]["repository"]["pullRequests"]["nodes"] = [p]
                lines, _ = self.run_alarm()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("read failed", lines[0])

    def test_hung_read_and_complete_check_fit_deadline(self):
        lines, elapsed = self.run_alarm()
        self.assertEqual(lines, [])
        self.assertLess(elapsed, 3)
        print(f"Measured fake check: quiet factory in {elapsed:.3f}s")
        (self.root / "gh.mode").write_text("hang")
        lines, elapsed = self.run_alarm(deadline=1)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("read failed", lines[0])
        self.assertLess(elapsed, 3)
        print(f"Measured fake check: hung read terminated in {elapsed:.3f}s (1s budget)")

    def test_readme_embedded_script_runs_without_a_checkout(self):
        # Execute the documented header verbatim, except for its temporary
        # output path, and then run the embedded check from an empty folder.
        page = (HERE / "README.md").read_text()
        block = page.split("## How the orchestrator creates the loop", 1)[1].split("```sh\n", 1)[1].split("```", 1)[0]
        build = block.split("room-cli loop create", 1)[0]
        wrapper = self.root / "embedded.sh"
        build = build.replace("/tmp/stall-alarm-check.sh", str(wrapper))
        build = build.replace("tools/stall-alarm/alarm.py", str(SCRIPT))
        subprocess.run(["sh", "-c", build], check=True, cwd=self.root, capture_output=True)
        self.loops["automations"][0]["last_error"] = "synthetic timeout"
        for name, data in (("gh", self.github), ("room-cli", self.loops)):
            (self.root / (name + ".json")).write_text(json.dumps(data))
        # The local check pins the managed executable. An ambient room-cli
        # can be the restricted Cloud shim and must never receive this read.
        managed = self.root / "managed" / "room-cli"
        managed.parent.mkdir()
        managed.write_text((self.bin / "room-cli").read_text())
        managed.chmod(0o755)
        ambient = self.bin / "room-cli"
        ambient.write_text("#!/bin/sh\nprintf 'ambient CLI was used\\n' >&2\nexit 9\n")
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}", FAKE_ROOT=str(self.root),
                   STALL_ALARM_STATE=str(self.root / "embedded-state.json"),
                   STALL_ALARM_ROOM_CLI=str(managed))
        for code, count in ((1, 1), (0, 0)):
            proc = subprocess.run(["sh", str(wrapper)], cwd=self.root, env=env, capture_output=True,
                                  text=True, timeout=5)
            self.assertEqual(proc.returncode, code, proc.stderr)
            self.assertEqual(proc.stderr, "")
            self.assertEqual(len(proc.stdout.splitlines()), count)
            if count:
                self.assertIn("fleet loop", proc.stdout)
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual([call for call in calls if call[0] == "room-cli"],
                         [["room-cli", "loop", "list", "--json"]] * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
