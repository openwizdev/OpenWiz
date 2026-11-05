#!/usr/bin/env python3
"""#1280: command proofs against a synthetic, persistent GitHub API."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TARGET = "openwizdev/openwiz"
SOURCE = "jparker2006/ClosedWiz"
ROOT = f"repos/{TARGET}"
SRC = f"repos/{SOURCE}"

# Expected API values are literal policy, independent of the implementation.
CI = {
    "name": "CI must pass", "target": "branch", "enforcement": "active",
    "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["refs/heads/main", "refs/heads/release-*"], "exclude": []}},
    "rules": [
        {"type": "deletion"}, {"type": "non_fast_forward"},
        {"type": "required_status_checks", "parameters": {
            "strict_required_status_checks_policy": True,
            "do_not_enforce_on_create": False,
            "required_status_checks": [{"context": c} for c in ["web-build", "rust", "web-test", "privacy"]]}},
    ],
}
QUEUE = {
    "name": "Merge queue", "target": "branch", "enforcement": "active",
    "bypass_actors": [],
    "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
    "rules": [{"type": "merge_queue", "parameters": {
        "check_response_timeout_minutes": 75, "grouping_strategy": "ALLGREEN",
        "max_entries_to_build": 5, "max_entries_to_merge": 1,
        "merge_method": "MERGE", "min_entries_to_merge": 1,
        "min_entries_to_merge_wait_minutes": 0,
    }}],
}
LABEL = {"name": "synthetic-label", "color": "aabbcc", "description": "Synthetic purpose"}
MILESTONE = {"title": "synthetic-version", "description": "Synthetic release", "state": "open", "due_on": None}


def world():
    return {
        "repo": {"full_name": TARGET, "visibility": "public", "default_branch": "main",
                 "owner": {"type": "Organization"}},
        "rulesets": [], "fork": {"approval_policy": "first_time_contributors"},
        "runners": [], "variables": [], "organization_variables": [],
        "source_labels": [dict(LABEL)], "labels": [],
        "source_milestones": [dict(MILESTONE, number=7)], "milestones": [],
        "calls": [],
    }


class Settings(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="open-settings-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(HERE / "fixtures" / "gh", self.root / "gh")
        (self.root / "gh").chmod(0o755)
        self.state = self.root / "state.json"
        self.env = dict(os.environ, PATH=f"{self.root}{os.pathsep}{os.environ['PATH']}",
                        SETTINGS_FAKE_STATE=str(self.state))
        self.plan_file = self.root / "plan.json"
        self.journal = self.root / "journal.jsonl"

    def run_tool(self, data=None, *args):
        """Run one command; --apply runs the reviewed two-step path.

        A dry read saves the plan, then apply is bound to that plan file and
        its digest, with a fresh journal. A failed or blocked read returns
        the read's own result: no plan, so no apply.
        """
        if data is not None:
            self.state.write_text(json.dumps(data))
        if "--apply" in args:
            rest = [a for a in args if a != "--apply"]
            self.plan_file.unlink(missing_ok=True)
            p = self.raw(*rest, "--plan-out", str(self.plan_file))
            if p.returncode != 0:
                return p
            self.journal.unlink(missing_ok=True)
            return self.raw(*rest, "--apply", "--plan", str(self.plan_file),
                            "--digest", self.digest(), "--journal", str(self.journal))
        return self.raw(*args)

    def raw(self, *args, env=None):
        p = subprocess.run([sys.executable, "-I", str(HERE / "settings.py"), *args],
                           cwd=self.root, env=env or self.env, text=True, capture_output=True, timeout=20)
        self.data = json.loads(self.state.read_text())
        return p

    def digest(self):
        return json.loads(self.plan_file.read_text())["digest"]

    def save_plan(self, data, *args):
        self.state.write_text(json.dumps(data))
        self.plan_file.unlink(missing_ok=True)
        p = self.raw(*args, "--plan-out", str(self.plan_file))
        self.assertEqual(p.returncode, 0, p.stderr)
        return p

    def apply_plan(self, data=None, *args, digest=None, plan=None):
        if data is not None:
            self.state.write_text(json.dumps(data))
        self.journal.unlink(missing_ok=True)
        return self.raw(*args, "--apply", "--plan", str(plan or self.plan_file),
                        "--digest", digest or self.digest(), "--journal", str(self.journal))

    def recover(self, *args, journal=None):
        return self.raw(*args, "--recover", "--plan", str(self.plan_file), "--digest", self.digest(),
                        "--journal", str(journal or self.journal))

    def writes(self):
        return [c for c in self.data["calls"] if c["method"] != "GET"]

    def test_read_is_read_only_and_reports_differences(self):
        before = world()
        p = self.run_tool(before)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["mode"], "read")
        self.assertEqual(set(out["differences"]), {"CI must pass", "Merge queue", "fork approval", "label:synthetic-label", "milestone:synthetic-version"})
        self.assertEqual(self.writes(), [])
        self.assertEqual({k: v for k, v in self.data.items() if k != "calls"},
                         {k: v for k, v in before.items() if k != "calls"})

    def test_apply_fixes_every_setting_reads_back_and_repeats_without_writes(self):
        p = self.run_tool(world(), "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["differences"], [])
        by_name = {r["name"]: {k: v for k, v in r.items() if k not in ("id", "source", "source_type")} for r in self.data["rulesets"]}
        self.assertEqual(by_name, {"CI must pass": CI, "Merge queue": QUEUE})
        self.assertEqual(self.data["fork"], {"approval_policy": "all_external_contributors"})
        self.assertEqual(self.data["labels"], [LABEL])
        self.assertEqual([{k: v for k, v in m.items() if k != "number"} for m in self.data["milestones"]], [MILESTONE])
        calls = self.data["calls"]
        for i, call in enumerate(calls):
            if call["method"] != "GET":
                self.assertTrue(any(c["method"] == "GET" and c["path"].split('?')[0].startswith(call["path"].split('?')[0]) for c in calls[i + 1:]), call)
        self.assertTrue(all(c["path"].startswith(ROOT + "/") for c in self.writes()))
        self.data["calls"] = []
        p = self.run_tool(self.data, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.writes(), [])

    def test_updates_existing_values_and_keeps_longer_queue_timeout(self):
        w = world()
        ci = copy.deepcopy(CI)
        ci["enforcement"] = "disabled"
        ci["bypass_actors"] = [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}]
        ci["conditions"]["ref_name"]["exclude"] = ["refs/heads/release-test"]
        ci["rules"] = [{"type": "deletion"}]
        q = copy.deepcopy(QUEUE)
        q["rules"][0]["parameters"].update(merge_method="SQUASH", check_response_timeout_minutes=100)
        w["rulesets"] = [dict(ci, id=10, source=TARGET, source_type="Repository"), dict(q, id=11, source=TARGET, source_type="Repository")]
        w["labels"] = [dict(LABEL, color="000000", description=None)]
        w["milestones"] = [dict(MILESTONE, number=99, state="closed", description=None, due_on="2030-01-01T00:00:00Z")]
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["differences"], [])
        self.assertEqual(self.data["rulesets"][1]["rules"][0]["parameters"]["check_response_timeout_minutes"], 100)
        self.assertEqual(self.data["rulesets"][1]["rules"][0]["parameters"]["merge_method"], "MERGE")
        self.assertEqual(self.data["labels"], [LABEL])
        self.assertEqual(self.data["milestones"], [dict(MILESTONE, number=99)])

    def test_required_check_bindings_survive_noop_drift_and_reapply(self):
        expected = [
            {"context": "web-build", "integration_id": 9001},
            {"context": "rust", "integration_id": 9002},
            {"context": "web-test", "integration_id": 9003},
            {"context": "privacy", "integration_id": 9004},
        ]
        for drift in [False, True]:
            with self.subTest(drift=drift):
                w = world(); ci = copy.deepcopy(CI)
                ci["rules"][2]["parameters"]["required_status_checks"] = copy.deepcopy(expected)
                if drift:
                    ci["enforcement"] = "disabled"
                    ci["rules"][2]["parameters"]["strict_required_status_checks_policy"] = False
                w.update(rulesets=[dict(ci, id=10, source=TARGET, source_type="Repository"),
                                   dict(copy.deepcopy(QUEUE), id=11, source=TARGET, source_type="Repository")],
                         fork={"approval_policy": "all_external_contributors"},
                         labels=[dict(LABEL)], milestones=[dict(MILESTONE, number=11)])
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout)["differences"], [])
                self.assertEqual(len(self.writes()), 1 if drift else 0)
                row = next(r for r in self.data["rulesets"] if r["name"] == "CI must pass")
                actual = next(r for r in row["rules"] if r["type"] == "required_status_checks")
                self.assertEqual(actual["parameters"]["required_status_checks"], expected)
                self.assertEqual(row["enforcement"], "active")
                self.assertTrue(actual["parameters"]["strict_required_status_checks_policy"])
                self.data["calls"] = []
                p = self.run_tool(self.data, "--apply")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(self.writes(), [])

    def test_invalid_or_ambiguous_required_check_bindings_refuse_before_writes(self):
        bad_checks = [[{"context": "rust", "integration_id": value}]
                      for value in [True, 0, -1, 1.5, "9001", {}, []]]
        bad_checks += [None, {}, [False], [{"integration_id": 9001}],
                       [{"context": "rust", "integration_id": 9001},
                        {"context": "rust", "integration_id": 9002}]]
        for checks in bad_checks:
            with self.subTest(checks=checks):
                w = world(); ci = copy.deepcopy(CI)
                ci["rules"][2]["parameters"]["required_status_checks"] = checks
                w["rulesets"] = [dict(ci, id=10, source=TARGET, source_type="Repository")]
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("required", p.stderr)
                self.assertEqual(self.writes(), [])

    def test_safety_blocks_all_writes(self):
        cases = [("runners", [{"id": 1}], "self-hosted runners are registered")]
        # Literal policy list, independent of settings.py: every runner variable
        # consulted by the carried workflows must refuse at either scope.
        for key, scope in (("variables", "repository"), ("organization_variables", "organization")):
            for name in ("CI_RUNS_ON", "CI_RUST_RUNS_ON", "CI_WEB_RUNS_ON", "CI_SMALL_RUNS_ON"):
                cases.append((key, [{"name": name}], f"{scope} runner variable {name} is set"))
        for key, value, blocker in cases:
            for args in ((), ("--apply",)):
                with self.subTest(key=key, value=value, args=args):
                    w = world(); w[key] = value
                    p = self.run_tool(w, *args)
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertEqual(json.loads(p.stdout)["blockers"], [blocker])
                    self.assertEqual(self.writes(), [])

    def test_every_read_failure_stops_before_writes(self):
        self.run_tool(world())
        paths = [c["path"] for c in self.data["calls"]]
        self.assertGreaterEqual(len(paths), 9)
        for path in paths:
            with self.subTest(path=path):
                w = world(); w["fail"] = {"method": "GET", "path": path}
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("GET", p.stderr)
                self.assertEqual(self.writes(), [])

    def test_each_failed_write_stops_and_is_reported(self):
        self.run_tool(world(), "--apply")
        fixed = copy.deepcopy(self.data)
        fixed["calls"] = []
        fixed["rulesets"][0]["enforcement"] = "disabled"
        fixed["rulesets"][1]["enforcement"] = "disabled"
        fixed["labels"][0]["color"] = "000000"
        fixed["milestones"][0]["state"] = "closed"
        fixed["fork"] = {"approval_policy": "first_time_contributors"}
        for initial in [world(), fixed]:
            self.run_tool(initial, "--apply")
            writes = self.writes()
            self.assertEqual(len(writes), 5)
            for call in writes:
                with self.subTest(call=call):
                    w = copy.deepcopy(initial)
                    w["fail"] = {"method": call["method"], "path": call["path"]}
                    p = self.run_tool(w, "--apply")
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertIn(call["path"], p.stderr)
                    self.assertEqual(self.writes()[-1]["path"], call["path"])

    def test_acknowledged_but_lost_write_is_not_success(self):
        self.run_tool(world(), "--apply")
        for call in self.writes():
            with self.subTest(call=call):
                w = world(); w["drop_write"] = call["path"]
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("read-back", p.stderr)
                self.assertEqual(self.writes()[-1]["path"], call["path"])

    def test_post_write_read_failure_stops(self):
        w = world(); w["fail_after_write"] = True
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(len(self.writes()), 1)
        self.assertIn("GET", p.stderr)

    def test_malformed_reads_are_never_treated_as_empty(self):
        self.run_tool(world())
        paths = [c["path"] for c in self.data["calls"]]
        for path in paths:
            for bad in [None, {}, False, [], {"total_count": 1, "runners": []}]:
                with self.subTest(path=path, bad=bad):
                    w = world(); w["override"] = {"path": path, "raw": json.dumps(bad)}
                    p = self.run_tool(w, "--apply")
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertEqual(self.writes(), [])
        w = world(); w["override"] = {"path": ROOT, "raw": '{"full_name":"openwizdev/openwiz","full_name":"openwizdev/openwiz"}'}
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(self.writes(), [])

    def test_pagination_includes_every_source_label_and_milestone(self):
        w = world()
        w["source_labels"] = [dict(LABEL, name=f"synthetic-{i}") for i in range(103)]
        w["source_milestones"] = [dict(MILESTONE, title=f"synthetic-{i}", number=i+1) for i in range(103)]
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.data["labels"]), 103)
        self.assertEqual(len(self.data["milestones"]), 103)

    def test_ambiguous_or_inherited_owned_ruleset_is_refused(self):
        for rules in [[dict(CI, id=10, source=TARGET, source_type="Repository"), dict(CI, id=11, source=TARGET, source_type="Repository")],
                      [dict(CI, id=10, source="synthetic-org", source_type="Organization")]]:
            with self.subTest(rules=rules):
                w = world(); w["rulesets"] = rules
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertEqual(self.writes(), [])

    def test_private_source_metadata_is_refused_before_any_write_or_report(self):
        planted = [
            ("source_labels", "name", "thr_" + "planted0001"),
            ("source_labels", "description", "Investigate " + "thr_" + "planted0001"),
            ("source_milestones", "title", "prj_" + "planted0001"),
            ("source_milestones", "description", "owner@" + "planted.invalid"),
            ("source_milestones", "description", ("Ja" + "ke") + ': "keep this private"'),
        ]
        for key, field, value in planted:
            for args in [(), ("--apply",)]:
                with self.subTest(key=key, field=field, args=args):
                    w = world(); w[key][0][field] = value
                    p = self.run_tool(w, *args)
                    self.assertEqual(p.returncode, 1, p.stderr)
                    self.assertIn("privacy", p.stderr)
                    self.assertNotIn(value, p.stdout + p.stderr)
                    self.assertEqual(self.writes(), [])

    def test_polish_milestone_uses_public_description_in_read_and_reconciliation(self):
        private = ("Ja" + "ke") + ', 2030-01-02: "synthetic private decision"'
        public = (
            "Polish when capacity allows: UI design, repository cleanup, public README "
            "and installation, and skill polish (spec #204).\n"
            "Jake, 2026-11-01: the polish milestone has no fixed version number or "
            "urgency ([private record](https://github.com/jparker2006/ClosedWiz/"
            "issues/204#issuecomment-6552796396))."
        )
        expected = dict(MILESTONE, title="0.0.X", description=public, state="closed",
                        due_on="2030-02-03T00:00:00Z")
        for existing in [False, True]:
            with self.subTest(existing=existing):
                w = world()
                w["source_milestones"].append(dict(expected, number=8, description=private))
                if existing:
                    w["milestones"] = [dict(expected, number=42, description="Old public summary")]
                p = self.run_tool(w)
                self.assertEqual(p.returncode, 0, p.stderr)
                out = json.loads(p.stdout)
                proposal = next(a for a in out["plan"] if a["identity"] == "0.0.X")
                self.assertEqual(proposal["value"], expected)
                self.assertNotIn(private, p.stdout + p.stderr)
                self.assertEqual(self.writes(), [])
                self.assertEqual({k: v for k, v in self.data.items() if k != "calls"},
                                 {k: v for k, v in w.items() if k != "calls"})
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout)["differences"], [])
                actual = [{k: v for k, v in m.items() if k != "number"} for m in self.data["milestones"]]
                self.assertCountEqual(actual, [MILESTONE, expected])
                self.data["calls"] = []
                p = self.run_tool(self.data, "--apply")
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(self.writes(), [])

        w["repo"].update(full_name="jparker2006/OpenWiz", owner={"type": "User"})
        p = self.run_tool(w, "--repo", "jparker2006/OpenWiz")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(p.stderr, "")
        out = json.loads(p.stdout)
        self.assertEqual(out["blockers"], ["merge queue requires the O20 organization transfer"])
        self.assertEqual(next(a["value"] for a in out["plan"] if a["identity"] == "0.0.X"), expected)
        self.assertEqual(self.writes(), [])

        literals = self.root / "literals.txt"
        literals.write_text("Polish when capacity allows\n")
        p = self.run_tool(w, "--repo", "jparker2006/OpenWiz", "--literals", str(literals))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("privacy", p.stderr)
        self.assertEqual(p.stdout, "")
        self.assertEqual(self.writes(), [])

    def test_private_literals_and_failed_privacy_input_block_all_writes(self):
        literals = self.root / "literals.txt"
        literals.write_text("synthetic-private-literal\n")
        w = world(); w["source_labels"][0]["description"] = "synthetic-private-literal"
        p = self.run_tool(w, "--apply", "--literals", str(literals))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("privacy", p.stderr)
        self.assertEqual(self.writes(), [])
        literals.unlink()
        p = self.run_tool(world(), "--apply", "--literals", str(literals))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("privacy", p.stderr)
        self.assertEqual(self.writes(), [])
        literals.write_text("synthetic-private-literal\n")
        p = self.run_tool(world(), "--apply", "--literals", str(literals))
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(json.loads(p.stdout)["privacy_literals"])

    def test_old_address_redirect_preserves_compliant_rulesets(self):
        # After transfer, the old URL redirects but rulesets name the new source.
        self.assertEqual(self.run_tool(world(), "--apply").returncode, 0)
        self.data["calls"] = []
        for args in [(), ("--apply",)]:
            with self.subTest(args=args):
                p = self.run_tool(self.data, "--repo", "jparker2006/OpenWiz", *args)
                self.assertEqual(p.returncode, 0, p.stderr)
                out = json.loads(p.stdout)
                self.assertEqual(out["repository"], TARGET)
                self.assertEqual(out["differences"], [])
                self.assertEqual(out["blockers"], [])
                self.assertEqual(self.writes(), [])
        self.data["repo"]["full_name"] = "openwizdev/OpenWiz"
        self.data["rulesets"][0]["enforcement"] = "disabled"
        self.data["calls"] = []
        p = self.run_tool(self.data, "--repo", "jparker2006/OpenWiz", "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["differences"], [])
        self.assertEqual(self.data["rulesets"][-1]["enforcement"], "active")
        self.assertEqual(len(self.writes()), 1)
        self.assertTrue(self.writes()[0]["path"].startswith(ROOT + "/"))

    def test_pretransfer_read_is_complete_but_apply_is_blocked(self):
        for args in [(), ("--apply",)]:
            w = world()
            w["repo"].update(full_name="jparker2006/OpenWiz", owner={"type": "User"})
            p = self.run_tool(w, "--repo", "jparker2006/OpenWiz", *args)
            self.assertEqual(p.returncode, 1, p.stderr)
            out = json.loads(p.stdout)
            self.assertEqual(out["blockers"], ["merge queue requires the O20 organization transfer"])
            self.assertEqual(len(out["differences"]), 5)
            self.assertEqual(self.writes(), [])

    def test_partial_counted_pages_missing_bypass_and_unknown_policy_refuse(self):
        cases = [(ROOT + "/actions/runners?per_page=100", [{"total_count": 2, "runners": []}]),
                 (ROOT + "/actions/variables?per_page=30", [{"total_count": 1, "variables": []}]),
                 (ROOT + "/actions/organization-variables?per_page=30", [{"total_count": 1, "variables": []}]),
                 (ROOT + "/actions/permissions/fork-pr-contributor-approval", {"approval_policy": "unknown"})]
        for path, value in cases:
            with self.subTest(path=path):
                w = world(); w["override"] = {"path": path, "raw": json.dumps(value)}
                p = self.run_tool(w, "--apply")
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertEqual(self.writes(), [])
        w = world()
        w["rulesets"] = [dict(CI, id=1, source=TARGET, source_type="Repository")]
        del w["rulesets"][0]["bypass_actors"]
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(self.writes(), [])

    def test_metadata_identity_null_clearing_and_target_only_entries(self):
        w = world()
        w["source_labels"] = [dict(LABEL, name="Synthetic / label", description=None)]
        w["labels"] = [dict(LABEL, name="synthetic / label"), dict(LABEL, name="target-only")]
        w["source_milestones"] = [dict(MILESTONE, number=7, description=None, state="closed")]
        w["milestones"] = [dict(MILESTONE, number=42, due_on="2030-01-01T00:00:00Z"),
                           dict(MILESTONE, title="target-only", number=43)]
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        out = json.loads(p.stdout)
        self.assertEqual(out["differences"], [])
        self.assertEqual(out["target_only_labels"], ["target-only"])
        self.assertEqual(out["target_only_milestones"], ["target-only"])
        self.assertIn(dict(LABEL, name="Synthetic / label", description=""), self.data["labels"])
        self.assertIn(dict(MILESTONE, number=42, description="", state="closed"), self.data["milestones"])

    def test_paginated_runner_variables_and_rule_ordering(self):
        w = world()
        w["variables"] = [{"name": f"SYNTHETIC_{i}"} for i in range(103)] + [{"name": "CI_WEB_RUNS_ON"}]
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(self.writes(), [])
        w = world()
        ci = copy.deepcopy(CI)
        ci["rules"].reverse()
        ci["conditions"]["ref_name"]["include"].reverse()
        checks = ci["rules"][0]["parameters"]["required_status_checks"]
        checks.reverse()
        for check in checks:
            check["integration_id"] = None
        w["rulesets"] = [dict(ci, id=10, source=TARGET, source_type="Repository"),
                         dict(QUEUE, id=11, source=TARGET, source_type="Repository")]
        w["fork"] = {"approval_policy": "all_external_contributors"}
        w["labels"] = [LABEL]
        w["milestones"] = [dict(MILESTONE, number=11)]
        p = self.run_tool(w, "--apply")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.writes(), [])

    def test_rejects_private_or_unexpected_destination_before_any_write(self):
        for change in [{"visibility": "private"}, {"full_name": SOURCE}, {"default_branch": "other"}]:
            w = world(); w["repo"].update(change)
            p = self.run_tool(w, "--apply")
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertEqual(self.writes(), [])
        p = self.run_tool(world(), "--repo", SOURCE, "--apply")
        self.assertEqual(p.returncode, 2)
        self.assertEqual(self.data["calls"], [])

    # #2408: plan-bound, journalled apply with recovery (fixture claims only).

    def mixed_world(self):
        """Five planned writes: update, create, update, create, update."""
        w = world()
        ci = copy.deepcopy(CI); ci["enforcement"] = "disabled"
        other = dict(copy.deepcopy(QUEUE), name="Synthetic other rules", id=5, source=TARGET, source_type="Repository")
        w["rulesets"] = [other, dict(ci, id=10, source=TARGET, source_type="Repository")]
        w["labels"] = [dict(LABEL, name="target-only")]
        w["milestones"] = [dict(MILESTONE, number=42, state="closed"), dict(MILESTONE, title="target-only", number=43)]
        return w

    def settled(self, data):
        ignore = {"calls", "fail_write", "fail_write_applied", "crash_write"}
        return {k: sorted(v, key=lambda i: json.dumps(i, sort_keys=True)) if isinstance(v, list) else v
                for k, v in data.items() if k not in ignore}

    def records(self, journal=None):
        text = (journal or self.journal).read_text()
        self.assertTrue(text.endswith("\n"))
        return [json.loads(line) for line in text.splitlines()]

    def shape(self, records):
        return [(r["record"], r.get("index"), r.get("result")) for r in records]

    def clear_faults(self):
        self.data = {k: v for k, v in self.data.items() if k not in ("fail_write", "fail_write_applied", "crash_write")}
        self.data["calls"] = []
        self.state.write_text(json.dumps(self.data))

    def test_apply_without_a_reviewed_plan_refuses(self):
        for args in [("--apply",), ("--apply", "--journal", "j.jsonl"),
                     ("--apply", "--plan", "plan.json", "--journal", "j.jsonl")]:
            with self.subTest(args=args):
                p = self.run_tool_raw(world(), *args)
                self.assertNotEqual(p.returncode, 0, p.stdout)
                self.assertEqual(self.writes(), [])

    def run_tool_raw(self, data, *args):
        self.state.write_text(json.dumps(data))
        return self.raw(*args)

    def test_saved_plan_records_every_write_with_its_prior_state(self):
        initial = self.mixed_world()
        p = self.save_plan(initial)
        self.assertEqual(self.writes(), [])
        saved = json.loads(self.plan_file.read_text())
        self.assertEqual(json.loads(p.stdout)["plan_digest"], saved["digest"])
        self.assertEqual(saved["repository"], TARGET)
        rows = [(a["method"], a["path"], a["identity"], a["change"]) for a in saved["actions"]]
        self.assertEqual(rows, [
            ("PUT", ROOT + "/rulesets/10", "CI must pass", "updated"),
            ("POST", ROOT + "/rulesets", "Merge queue", "created"),
            ("PUT", ROOT + "/actions/permissions/fork-pr-contributor-approval", None, "updated"),
            ("POST", ROOT + "/labels", "synthetic-label", "created"),
            ("PATCH", ROOT + "/milestones/42", "synthetic-version", "updated")])
        priors = [a["prior"] for a in saved["actions"]]
        self.assertEqual(priors[0], initial["rulesets"][1])
        self.assertEqual(priors[1:4], [None, {"approval_policy": "first_time_contributors"}, None])
        self.assertEqual(priors[4], dict(MILESTONE, number=42, state="closed"))
        self.assertEqual(saved["actions"][4]["value"], MILESTONE)

    def test_apply_refuses_before_its_first_write(self):
        initial = self.mixed_world()
        self.save_plan(initial)
        good = self.plan_file.read_text()
        drifts = {
            "planned ruleset": lambda w: w["rulesets"][1].update(enforcement="evaluate"),
            "planned creation": lambda w: w["rulesets"].append(dict(QUEUE, id=12, source=TARGET, source_type="Repository")),
            "fork": lambda w: w.update(fork={"approval_policy": "first_time_contributors_new_to_github"}),
            "label": lambda w: w["labels"].append(dict(LABEL, color="000000")),
            "milestone": lambda w: w["milestones"][0].update(description="Synthetic other text"),
        }
        for name, change in drifts.items():
            with self.subTest(drift=name):
                w = copy.deepcopy(initial); change(w)
                p = self.apply_plan(w)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("drift", p.stderr)
                self.assertEqual(self.writes(), [])
                self.assertFalse(self.journal.exists())
        changed = json.loads(good); changed["actions"][1]["value"]["enforcement"] = "disabled"
        for name, text, digest, needle in [
                ("changed", json.dumps(changed), None, "digest"),
                ("truncated", good[: len(good) // 2], json.loads(good)["digest"], "plan"),
                ("empty", "", json.loads(good)["digest"], "plan"),
                ("digest mismatch", good, "0" * 64, "digest"),
                ("malformed digest", good, "not-a-digest", "digest")]:
            with self.subTest(plan=name):
                self.plan_file.write_text(text)
                p = self.apply_plan(initial, digest=digest or json.loads(good)["digest"])
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn(needle, p.stderr)
                self.assertEqual(self.writes(), [])
                self.assertFalse(self.journal.exists())
        self.plan_file.write_text(good)
        with self.subTest(case="different repository"):
            old = copy.deepcopy(initial)
            old["repo"]["full_name"] = "jparker2006/OpenWiz"
            for row in old["rulesets"]:
                row["source"] = "jparker2006/OpenWiz"
            other = self.root / "other-plan.json"
            self.save_plan(old, "--repo", "jparker2006/OpenWiz")
            self.plan_file.rename(other)
            self.plan_file.write_text(good)
            p = self.apply_plan(initial, plan=other, digest=json.loads(other.read_text())["digest"])
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn("repository", p.stderr)
            self.assertEqual(self.writes(), [])
        with self.subTest(case="runner variable"):
            w = copy.deepcopy(initial); w["variables"] = [{"name": "CI_RUNS_ON"}]
            p = self.apply_plan(w)
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertEqual(json.loads(p.stdout)["blockers"], ["repository runner variable CI_RUNS_ON is set"])
            self.assertEqual(self.writes(), [])
            self.assertFalse(self.journal.exists())
        with self.subTest(case="journal already exists"):
            self.state.write_text(json.dumps(initial))
            self.journal.write_text("")
            p = self.raw("--apply", "--plan", str(self.plan_file), "--digest", self.digest(),
                         "--journal", str(self.journal))
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn("journal", p.stderr)
            self.assertEqual(self.writes(), [])
            self.assertEqual(self.journal.read_text(), "")

    def test_failed_third_write_is_recovered_exactly_and_once(self):
        initial = self.mixed_world()
        expected_recovery = {
            # Not applied: undone newest first; the creation removed, the update restored.
            "fail_write": [("DELETE", ROOT + "/rulesets/11"), ("PUT", ROOT + "/rulesets/10")],
            # Applied, then gh failed: the unknown write is resolved by reading.
            "fail_write_applied": [("PUT", ROOT + "/actions/permissions/fork-pr-contributor-approval"),
                                   ("DELETE", ROOT + "/rulesets/11"), ("PUT", ROOT + "/rulesets/10")],
        }
        for fault, recovery_writes in expected_recovery.items():
            with self.subTest(fault=fault):
                self.save_plan(initial)
                w = copy.deepcopy(initial); w[fault] = 3
                p = self.apply_plan(w)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("recover", p.stderr)
                self.assertEqual(len(self.writes()), 3)
                records = self.records()
                self.assertEqual(self.shape(records), [
                    ("start", None, None), ("intent", 0, None), ("completion", 0, "done"),
                    ("intent", 1, None), ("completion", 1, "done"), ("intent", 2, None),
                    ("completion", 2, "unknown")])
                self.assertIsNone(records[-1]["new"])
                self.assertEqual(records[2]["prior"], initial["rulesets"][1])
                self.assertEqual(records[2]["new"]["enforcement"], "active")
                self.clear_faults()
                p = self.recover()
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual([(c["method"], c["path"]) for c in self.writes()], recovery_writes)
                self.assertEqual(self.settled(self.data), self.settled(initial))
                self.data["calls"] = []
                self.state.write_text(json.dumps(self.data))
                p = self.recover()
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.settled(self.data), self.settled(initial))

    def test_crash_after_an_intent_record_is_recovered(self):
        initial = self.mixed_world()
        self.save_plan(initial)
        w = copy.deepcopy(initial); w["crash_write"] = 4
        p = self.apply_plan(w)
        self.assertLess(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.writes()), 4)
        self.assertIn(dict(LABEL), self.data["labels"])
        self.assertEqual(self.shape(self.records())[-2:], [("completion", 2, "done"), ("intent", 3, None)])
        self.clear_faults()
        p = self.recover()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([(c["method"], c["path"]) for c in self.writes()], [
            ("DELETE", ROOT + "/labels/synthetic-label"),
            ("PUT", ROOT + "/actions/permissions/fork-pr-contributor-approval"),
            ("DELETE", ROOT + "/rulesets/11"), ("PUT", ROOT + "/rulesets/10")])
        self.assertEqual(self.settled(self.data), self.settled(initial))
        self.data["calls"] = []
        self.state.write_text(json.dumps(self.data))
        p = self.recover()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.writes(), [])

    def test_recovery_refuses_a_journal_that_does_not_match_its_plan(self):
        initial = self.mixed_world()
        self.save_plan(initial)
        w = copy.deepcopy(initial); w["fail_write"] = 3
        self.apply_plan(w)
        self.clear_faults()
        lines = self.journal.read_text().splitlines(keepends=True)
        edited = json.loads(lines[1]); edited["path"] = ROOT + "/rulesets/5"
        foreign = json.loads(lines[0]); foreign["plan_digest"] = "0" * 64
        completion = json.loads(lines[2]); completion["prior"] = None
        cases = {
            "edited intent": [lines[0], json.dumps(edited) + "\n", *lines[2:]],
            "other plan": [json.dumps(foreign) + "\n", *lines[1:]],
            "edited completion": [*lines[:2], json.dumps(completion) + "\n", *lines[3:]],
            "missing record": [lines[0], *lines[2:]],
            "reordered": [lines[0], lines[3], lines[4], lines[1], lines[2], *lines[5:]],
            "no start": lines[1:],
            "empty": [],
        }
        bad = self.root / "bad.jsonl"
        for name, content in cases.items():
            with self.subTest(journal=name):
                bad.write_text("".join(content))
                self.data["calls"] = []
                self.state.write_text(json.dumps(self.data))
                p = self.recover(journal=bad)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("journal", p.stderr)
                self.assertEqual(self.writes(), [])

    def test_journal_is_complete_on_success_and_holds_no_secret_or_literal(self):
        token = "synthetic-" + "token-0f9e8d7c"
        env = dict(self.env, GH_TOKEN=token, GITHUB_TOKEN=token)
        self.save_plan(self.mixed_world())
        self.journal.unlink(missing_ok=True)
        p = self.raw("--apply", "--plan", str(self.plan_file), "--digest", self.digest(),
                     "--journal", str(self.journal), env=env)
        self.assertEqual(p.returncode, 0, p.stderr)
        records = self.records()
        expected = [("start", None, None)]
        for i in range(5):
            expected += [("intent", i, None), ("completion", i, "done")]
        self.assertEqual(self.shape(records), expected + [("end", None, "complete")])
        for record in records[1:-1]:
            self.assertEqual(set(record) - {"new", "result"},
                             {"record", "index", "method", "path", "identity", "prior", "value"})
        self.assertEqual(oct(self.journal.stat().st_mode & 0o777), "0o600")
        literals = self.root / "literals.txt"
        literals.write_text("synthetic-private-literal\n" + token + "\n")
        for path in (self.journal, self.plan_file):
            self.assertNotIn(token, path.read_text())
            checker = HERE.parent / "privacy-check" / "check.py"
            check = subprocess.run([sys.executable, "-I", str(checker), "--body-file", str(path),
                                    "--literals", str(literals), "--require-literals"],
                                   text=True, capture_output=True, timeout=45)
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        # A plan is spent: repeating the same apply refuses on the existing journal.
        self.data["calls"] = []
        self.state.write_text(json.dumps(self.data))
        p = self.raw("--apply", "--plan", str(self.plan_file), "--digest", self.digest(),
                     "--journal", str(self.journal))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertEqual(self.writes(), [])

    def test_recovery_ignores_a_record_cut_inside_a_character(self):
        # Review R1: a crash can cut the last append inside a multibyte character.
        initial = self.mixed_world()
        initial["source_labels"][0]["description"] = "Synthetic caf\u00e9"
        self.save_plan(initial)
        w = copy.deepcopy(initial); w["crash_write"] = 4
        p = self.apply_plan(w)
        self.assertLess(p.returncode, 0, p.stderr)
        self.clear_faults()
        complete = self.journal.read_bytes()
        with self.journal.open("ab") as journal:
            journal.write(b'{"new":"Synthetic caf\xc3')
        p = self.recover()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(len(self.writes()), 4)
        self.assertEqual(self.settled(self.data), self.settled(initial))
        # Invalid UTF-8 inside a complete record still refuses.
        self.journal.write_bytes(complete + b'{"record":"\xc3"}\n')
        self.data["calls"] = []
        self.state.write_text(json.dumps(self.data))
        p = self.recover()
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("journal", p.stderr)
        self.assertEqual(self.writes(), [])

    def test_private_literal_in_a_prior_object_refuses_before_it_is_saved(self):
        # Review R2: the plan and journal persist prior objects, so they are checked too.
        literals = self.root / "literals.txt"
        literals.write_text("synthetic-private-literal\n")
        for key, row in [("labels", dict(LABEL, color="000000", description="synthetic-private-literal")),
                         ("milestones", dict(MILESTONE, number=42, description="synthetic-private-literal"))]:
            with self.subTest(key=key):
                w = self.mixed_world()
                w[key] = [r for r in w[key] if r.get("number") != 42] + [row]
                self.state.write_text(json.dumps(w))
                self.plan_file.unlink(missing_ok=True)
                p = self.raw("--literals", str(literals), "--plan-out", str(self.plan_file))
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIn("privacy", p.stderr)
                self.assertFalse(self.plan_file.exists())
                self.assertNotIn("synthetic-private-literal", p.stdout + p.stderr)
                self.assertEqual(self.writes(), [])

    def test_private_literal_in_a_read_back_is_never_journalled(self):
        # Review R2: a read-back object is checked before the journal keeps it.
        literals = self.root / "literals.txt"
        literals.write_text("synthetic-private-literal\n")
        w = world(); w["ruleset_note"] = "synthetic-private-literal"
        self.save_plan(w, "--literals", str(literals))
        p = self.apply_plan(None, "--literals", str(literals))
        self.assertEqual(p.returncode, 1, p.stderr)
        self.assertIn("privacy", p.stderr)
        self.assertEqual(len(self.writes()), 1)
        self.assertNotIn("synthetic-private-literal", self.journal.read_text())
        self.assertEqual(self.shape(self.records())[-1], ("completion", 0, "unknown"))

    def test_null_descriptions_are_restored_exactly(self):
        # Review R3: a null prior description is restored as null, not as empty text.
        initial = self.mixed_world()
        initial["labels"].append(dict(LABEL, color="000000", description=None))
        initial["milestones"][0]["description"] = None
        self.save_plan(initial)
        saved = json.loads(self.plan_file.read_text())
        priors = {a["identity"]: a["prior"] for a in saved["actions"]}
        self.assertIsNone(priors["synthetic-label"]["description"])
        self.assertIsNone(priors["synthetic-version"]["description"])
        p = self.apply_plan(initial)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.data["calls"] = []
        self.state.write_text(json.dumps(self.data))
        p = self.recover()
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(self.settled(self.data), self.settled(initial))

    def test_dry_read_writes_no_file_and_its_report_is_unchanged(self):
        p = self.run_tool(world())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(set(json.loads(p.stdout)), {
            "mode", "repository", "differences", "plan", "blockers", "applied", "privacy_literals",
            "target_only_labels", "target_only_milestones"})
        self.assertEqual(sorted(x.name for x in self.root.iterdir()), ["gh", "state.json"])


if __name__ == "__main__":
    unittest.main()
