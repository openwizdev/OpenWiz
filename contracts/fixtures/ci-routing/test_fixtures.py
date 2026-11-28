#!/usr/bin/env python3
import json
from pathlib import Path
import re
import unittest

HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parent.parent / "ci-routing.v1.md"
STATES = ("normal", "all-jog")
LIMIT_SIGNALS = ("minutes", "spending", "queue")
CREDENTIAL = re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}|github_pat_|-----BEGIN|(?<![0-9])[0-9]{8,}(?![0-9])")


def pin_of(text):
    blocks = re.findall(r"^```json\n(.*?)^```$", text, re.M | re.S)
    return json.loads(blocks[0])


def cases():
    return {path.name: json.loads(path.read_text()) for path in sorted(HERE.glob("*.json"))}


def state_of(pin, variables):
    seen = {name: variables.get(name) or spec["fallback"] for name, spec in pin["variables"].items()}
    for state, values in pin["states"].items():
        if values == seen:
            return state
    return None


def limit_hits(pin, read):
    rule = pin["rule"]["to_all_jog"]
    hits = []
    minutes = read.get("minutes")
    if minutes is not None and minutes["included"] > 0 and minutes["used"] >= minutes["included"]:
        hits.append("minutes")
    spending = read.get("spending")
    if spending is not None and spending["limit_cents"] and spending["spent_cents"] >= spending["limit_cents"]:
        hits.append("spending")
    if any(job["runner"] == "github-hosted" and job["reason"] in rule["queue"]["limit_reasons"]
           and job["queued_seconds"] >= rule["queue"]["at_least_seconds"] for job in read.get("queued", [])):
        hits.append("queue")
    return hits


def readable(pin, case):
    read = case["read"]
    if not read.get("ok"):
        return False
    if read.get("period") != case["now"][:7]:
        return False
    return all(isinstance(read.get(key), dict) or read.get(key) is None for key in ("minutes", "spending"))


def switched_period(pin, switches):
    for line in reversed(switches):
        match = re.fullmatch(pin["record"]["pattern"], line)
        if match and match.group("to") == "all-jog":
            return match.group("at")[:7]
    return None


def decide(pin, case):
    before = state_of(pin, case["before"]["variables"])
    if before is None or not readable(pin, case):
        return before, None
    hits = limit_hits(pin, case["read"])
    reasons = pin["rule"]["reasons"]
    if before == "normal" and hits:
        return "all-jog", f"{case['now']} ci-routing normal -> all-jog: {reasons[hits[0]]}"
    if before == "all-jog" and not hits:
        since = switched_period(pin, case["before"]["switches"])
        if since is None or case["read"]["period"] > since:
            return "normal", f"{case['now']} ci-routing all-jog -> normal: {reasons['reset']}"
    return before, None


class Contract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(CONTRACT.is_file(), "contracts/ci-routing.v1.md is missing")
        self.text = CONTRACT.read_text()
        self.pin = pin_of(self.text)


class TheVariables(Contract):
    def test_two_org_variables_with_their_fallbacks_and_visibility(self):
        self.assertEqual(self.pin["schema"], "openwiz.ci-routing.v1")
        self.assertEqual(self.pin["organization"], "openwizdev")
        self.assertEqual(self.pin["jog_label"], "jog-4vcpu")
        self.assertEqual(self.pin["variables"], {
            "OPENWIZ_RUNS_ON": {"repositories": "public", "fallback": "ubuntu-24.04", "visibility": "all",
                                "runs_on": "${{ vars.OPENWIZ_RUNS_ON || 'ubuntu-24.04' }}"},
            "OPENWIZ_PRIVATE_RUNS_ON": {"repositories": "private", "fallback": "jog-4vcpu", "visibility": "private",
                                        "runs_on": "${{ vars.OPENWIZ_PRIVATE_RUNS_ON || 'jog-4vcpu' }}"},
        })

    def test_the_exact_expressions_are_written_in_the_prose(self):
        for spec in self.pin["variables"].values():
            self.assertIn(f"runs-on: {spec['runs_on']}", self.text)

    def test_only_linux_jobs_read_the_variables(self):
        hosted = self.pin["hosted_only"]
        self.assertEqual(hosted["systems"], ["macos", "windows"])
        self.assertEqual(hosted["while_all_jog"], "waiting on the limit, not failed")


class TheStates(Contract):
    def test_two_states_and_their_values(self):
        self.assertEqual(self.pin["states"], {
            "normal": {"OPENWIZ_RUNS_ON": "ubuntu-24.04", "OPENWIZ_PRIVATE_RUNS_ON": "jog-4vcpu"},
            "all-jog": {"OPENWIZ_RUNS_ON": "jog-4vcpu", "OPENWIZ_PRIVATE_RUNS_ON": "jog-4vcpu"},
        })

    def test_normal_is_what_the_fallbacks_give(self):
        self.assertEqual(state_of(self.pin, {}), "normal")
        self.assertIsNone(state_of(self.pin, {"OPENWIZ_RUNS_ON": "ubuntu-22.04"}))


class TheRule(Contract):
    def test_every_number_is_written_exactly(self):
        rule = self.pin["rule"]
        self.assertEqual(rule["to_all_jog"]["any_of"], list(LIMIT_SIGNALS))
        self.assertEqual(rule["to_all_jog"]["minutes"], "used >= included, included > 0")
        self.assertEqual(rule["to_all_jog"]["spending"], "limit_cents > 0 and spent_cents >= limit_cents")
        self.assertEqual(rule["to_all_jog"]["queue"], {
            "runner": "github-hosted", "at_least_seconds": 900,
            "limit_reasons": ["minutes", "spending", "concurrency"]})
        self.assertEqual(rule["to_normal"], {
            "period": "UTC calendar month, reset at 00:00:00Z on the 1st",
            "after_reset": "the read's period is later than the month of the newest switch to all-jog",
            "room": "no limit signal"})
        self.assertEqual(rule["unreadable"], {
            "causes": ["gh-error", "scope", "malformed", "stale"], "state": "unchanged", "record": None})
        self.assertEqual(rule["unknown_variables"], {"state": "unchanged", "record": None})

    def test_each_reason_is_a_fixed_sentence_without_usage_figures(self):
        reasons = self.pin["rule"]["reasons"]
        self.assertEqual(set(reasons), {*LIMIT_SIGNALS, "reset", "forced"})
        for reason in reasons.values():
            self.assertRegex(reason, r"^[a-z][a-z ]+[a-z]$")


class TheRecord(Contract):
    def test_one_line_per_switch_on_one_tracking_issue(self):
        record = self.pin["record"]
        self.assertEqual(record["form"], "<UTC> ci-routing <from> -> <to>: <reason>")
        self.assertEqual(record["state_file"], "<state>/ci-route/switches.log")
        self.assertEqual(record["tracking_issue"], {
            "repository": "openwizdev/OpenWiz", "title": "CI routing: switch record", "state": "open",
            "created_by": "the owner", "none_or_several": "post nothing and say so"})
        line = "2026-12-14T09:30:00Z ci-routing normal -> all-jog: " + self.pin["rule"]["reasons"]["minutes"]
        self.assertRegex(line, record["pattern"])
        self.assertNotRegex("2026-12-14 09:30 ci-routing normal -> normal: x", record["pattern"])


class TheAuthority(Contract):
    def test_the_tool_needs_the_owners_grant_and_own_gh_and_never_edits_a_workflow(self):
        self.assertEqual(self.pin["authority"], {
            "grant": "the owner's, before any read or write",
            "gh": "the owner's own signed-in gh",
            "scope": "admin:org",
            "owner_step": "gh auth refresh -h github.com -s admin:org",
            "refuses_when_set": ["GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ACTIONS"],
            "app_token": False,
            "edits_workflows": False,
            "default": "--dry-run",
            "writes_only_with": "--apply",
            "writes": ["gh variable set --org", "one comment on the tracking issue"],
        })
        for words in ("owner's grant", "own signed-in `gh`", "never edits a workflow", "App token"):
            self.assertIn(words, self.text)


class TheFixtures(Contract):
    def test_each_case_follows_the_rule(self):
        for name, case in cases().items():
            with self.subTest(name):
                self.assertEqual(case["schema"], "openwiz.ci-routing.v1")
                state, record = decide(self.pin, case)
                self.assertEqual(state, case["expect"]["state"])
                self.assertEqual(record, case["expect"]["record"])
                if state:
                    self.assertEqual(self.pin["states"][state], case["expect"]["variables"])
                if record:
                    self.assertRegex(record, self.pin["record"]["pattern"])

    def test_the_fixtures_cover_every_change_and_every_hold(self):
        seen = set()
        for case in cases().values():
            before = state_of(self.pin, case["before"]["variables"])
            if not readable(self.pin, case):
                seen.add(("unreadable", before, case["read"].get("cause", "stale")))
            elif case["expect"]["record"]:
                seen.add((before, case["expect"]["state"], (limit_hits(self.pin, case["read"]) or ["reset"])[0]))
            else:
                seen.add(("stays", before))
        for signal in LIMIT_SIGNALS:
            self.assertIn(("normal", "all-jog", signal), seen)
        self.assertIn(("all-jog", "normal", "reset"), seen)
        self.assertIn(("stays", "all-jog"), seen)
        self.assertIn(("stays", "normal"), seen)
        for state in STATES:
            self.assertTrue(any(s[:2] == ("unreadable", state) for s in seen), state)

    def test_an_unreadable_read_never_changes_the_state(self):
        for name, case in cases().items():
            if not readable(self.pin, case):
                before = state_of(self.pin, case["before"]["variables"])
                self.assertEqual(case["expect"], {"state": before, "variables": self.pin["states"][before],
                                                  "record": None}, name)

    def test_the_rule_would_be_caught_if_it_drifted(self):
        case = cases()["normal-to-all-jog-queue.json"]
        job = case["read"]["queued"][0]
        self.assertEqual(job["queued_seconds"], self.pin["rule"]["to_all_jog"]["queue"]["at_least_seconds"])
        drifted = json.loads(json.dumps(self.pin))
        drifted["rule"]["to_all_jog"]["queue"]["at_least_seconds"] += 1
        self.assertEqual(decide(drifted, case), ("normal", None))

    def test_nothing_private_or_secret(self):
        for path in [CONTRACT, *HERE.glob("*.json")]:
            self.assertIsNone(CREDENTIAL.search(path.read_text()), path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
