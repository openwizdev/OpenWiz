#!/usr/bin/env python3
"""K2: version data selection and independent recorded-result comparison."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("dry_run", HERE / "dry-run.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class Plans(unittest.TestCase):
    def test_version_plans_select_all_recorded_steps_and_budgets(self):
        for profile, version in runner.PROFILES.items():
            with self.subTest(profile=profile):
                runner.read_plan(profile, HERE / (version + ".json"))

    def test_planted_budget_or_step_change_fails_dry_run(self):
        with tempfile.TemporaryDirectory() as directory:
            for profile, version in runner.PROFILES.items():
                original = json.loads((HERE / (version + ".json")).read_text())
                for fault in ("budget", "step", "target", "expectation", "fault"):
                    with self.subTest(profile=profile, fault=fault):
                        plan = copy.deepcopy(original)
                        if fault == "budget":
                            plan["budget"]["sends"] -= 1
                        elif fault == "step":
                            plan["groups"][0]["steps"].pop(0)
                        elif fault == "expectation":
                            plan["groups"][0]["steps"][0]["expect"]["calls"] = 99
                        else:
                            step = next(s for g in plan["groups"] for s in g["steps"]
                                        if s["expect"].get("calls") and ("thread" in s or "target" in s))
                            if fault == "fault":
                                step["fault"] = "fail-before"
                            else:
                                key = "thread" if profile == "send" else "target"
                                step[key] = "T-B" if step[key] == "T-A" else "T-A"
                        candidate = Path(directory) / "candidate.json"
                        candidate.write_text(json.dumps(plan))
                        if fault in ("target", "expectation", "fault"):
                            with self.assertRaisesRegex(ValueError, "operative step bodies differ"):
                                runner.read_plan(profile, candidate)
                        result = subprocess.run([sys.executable, str(HERE / "dry-run.py"),
                                                 "--profile", profile, "--plan", str(candidate),
                                                 "--log", str(Path(directory) / "unused.log")],
                                                capture_output=True, text=True)
                        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                        diagnostic = {"budget": "budget differs", "step": "ordered steps differ"}.get(
                            fault, "operative step bodies differ")
                        self.assertIn(diagnostic, result.stderr)

    def test_race_scheduling_preserves_one_effect_and_valid_results(self):
        for version, group_id, step_id, action, orders in (
                ("0.0.3", "C7", "C7-race", "send", ([0, 7, 7, 7], [7, 7, 7, 0], [0, 0, 0, 0])),
                ("0.0.4", "C3", "C3-N2", "create", ([7, 0], [0, 0]))):
            recorded = json.loads((HERE / (version + ".recorded.json")).read_text())
            row = next(r for r in recorded["steps"] if r[1] == step_id)
            expected = {"steps": [row]}
            for order in orders:
                got = copy.deepcopy(row[4])
                got["exit_list"] = order
                if action == "send":
                    won = order[0] == 0
                    got.update(exit=order[0], status="accepted" if won else "in_progress",
                               delivery="accepted" if won else None, effect="starts_turn" if won else "unknown",
                               replayed=False if won else None, recovered=False if won else None)
                report = {"outcome": "as_expected", "landing_at_end": "as_expected", "groups": [
                    {"group": group_id, "outside": {"verdict": "as_expected"}, "steps": [
                        {"step": step_id, "do": action, "verdict": "as_expected", "got": got}]}]}
                with self.subTest(version=version, order=order):
                    self.assertEqual(runner.compare("\n" + json.dumps(report), expected)["calls"], 1)
                for fault in ("all_pending", "bad_exit", "missing_child", "extra_call", "bad_status"):
                    bad = copy.deepcopy(report)
                    observation = bad["groups"][0]["steps"][0]["got"]
                    if fault == "all_pending": observation["exit_list"] = [7] * len(order)
                    elif fault == "bad_exit": observation["exit_list"][0] = 9
                    elif fault == "missing_child": observation["exit_list"].pop()
                    elif fault == "extra_call": observation["calls"] = 2
                    else: observation["status"] = "uncertain"
                    with self.subTest(version=version, fault=fault), self.assertRaises(ValueError):
                        runner.compare("\n" + json.dumps(bad), expected)

    def test_ambiguous_budget_data_is_refused(self):
        # A duplicate key must not silently replace an earlier allowance;
        # float spellings must not compare equal to the integer contract.
        original = (HERE / "0.0.4.json").read_text()
        with tempfile.TemporaryDirectory() as directory:
            for bad in (original.replace('"creates": 4', '"creates": 0, "creates": 4'),
                        original.replace('"creates": 4', '"creates": 4.0')):
                path = Path(directory) / "ambiguous.json"
                path.write_text(bad)
                with self.subTest(data=bad[:40]), self.assertRaises(ValueError):
                    runner.read_plan("new", path)

    def test_comparison_rejects_false_success_missing_duplicate_or_changed_outcome(self):
        # Hand-worked one-step observation, independent of a version plan.
        step = {"step": "C1-one", "do": "send", "verdict": "as_expected",
                "got": {"calls": 1, "status": "accepted", "ms": 200}}
        group = {"group": "C1", "outside": {"verdict": "as_expected"}, "steps": [step]}
        report = {"outcome": "as_expected", "landing_at_end": "as_expected", "groups": [group]}
        expected = {"steps": [["C1", "C1-one", "send", "as_expected", {"calls": 1, "status": "accepted"}]]}
        self.assertEqual(runner.compare("\n" + json.dumps(report), expected),
                         {"calls": 1, "steps": 1, "outcome": "as_expected"})
        for fault in ("empty", "missing", "duplicate", "calls", "outcome", "landing", "unexpected_report"):
            bad = copy.deepcopy(report)
            if fault == "missing":
                bad["groups"][0]["steps"] = []
            elif fault == "duplicate":
                bad["groups"][0]["steps"] *= 2
            elif fault == "calls":
                bad["groups"][0]["steps"][0]["got"]["calls"] = 2
            elif fault == "outcome":
                bad["groups"][0]["steps"][0]["got"]["status"] = "uncertain"
            elif fault == "landing":
                bad["landing_at_end"] = "not_as_expected"
            elif fault == "unexpected_report":
                bad["groups"][0]["steps"][0]["got"]["report"] = "unexpected output"
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                runner.compare("" if fault == "empty" else "\n" + json.dumps(bad), expected)


if __name__ == "__main__":
    unittest.main()
