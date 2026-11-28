import copy
from datetime import datetime
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parents[1] / "agent-states.v1.md"
SCHEMA = CONTRACT.with_suffix(".schema.json")
TICKET_STATES = {"waiting", "ready", "building", "ci", "review", "fix", "merged", "closed"}
AGENT_STATES = {"queued", "building", "ci", "review", "fix", "merge", "done"}
PROBLEMS = {"blocked", "failing", "stale", "held", None}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


class StatesContract(unittest.TestCase):
    def validator(self, definition=None):
        self.assertTrue(SCHEMA.is_file(), "the states schema must exist")
        schema = read(SCHEMA)
        Draft202012Validator.check_schema(schema)
        if definition:
            schema = {"$defs": schema["$defs"], "$ref": f"#/$defs/{definition}"}
        formats = FormatChecker()

        @formats.checks("date-time", raises=ValueError)
        def calendar_time(value):
            return not isinstance(value, str) or bool(datetime.fromisoformat(value))

        return Draft202012Validator(schema, format_checker=formats)

    def test_ticket_and_agent_states_have_record_examples(self):
        self.assertTrue(CONTRACT.is_file(), "the state-to-record contract must exist")
        contract = CONTRACT.read_text(encoding="utf-8")
        for state in TICKET_STATES | AGENT_STATES:
            self.assertIn(f"| `{state}` |", contract)
        validator = self.validator()
        fixture = read(HERE / "states.json")
        ticket_states, agent_states, problems = set(), set(), set()
        for name, case in fixture["cases"].items():
            with self.subTest(case=name):
                self.assertTrue(case["github"])
                snapshot = fixture["snapshot"] | case["expected"]
                validator.validate(snapshot)
                ticket_states.update(ticket["state"] for ticket in snapshot["tickets"])
                agent_states.update(agent["state"] for agent in snapshot["agents"])
                problems.update(ticket["problem"] and ticket["problem"]["kind"]
                                for ticket in snapshot["tickets"])
        self.assertEqual(TICKET_STATES, ticket_states)
        self.assertEqual(AGENT_STATES, agent_states)
        self.assertEqual(PROBLEMS, problems)
        self.assertEqual([], fixture["cases"]["unreadable-checks"]["expected"]["tickets"])

    def test_recheck_keeps_name_and_fresh_fix_has_its_own_name(self):
        fixture = read(HERE / "rounds.json")
        validator = self.validator()
        for wake in fixture["wakes"] + fixture["extra_cases"]:
            validator.validate(wake["expected"])
        first, recheck, final = [
            {agent["name"] for agent in wake["expected"]["agents"]}
            for wake in fixture["wakes"]
        ]
        self.assertEqual({"reviewer-9201-1", "builder-9101"}, first)
        self.assertEqual(first, recheck)
        self.assertEqual(first | {"fixer-9201-2"}, final)

    def test_malformed_snapshots_are_refused(self):
        validator = self.validator()
        fixture = read(HERE / "states.json")
        ready = fixture["snapshot"] | fixture["cases"]["ready"]["expected"]
        rejected = {
            "missing-budget": {key: value for key, value in ready.items() if key != "budget"},
            "unknown-schema": ready | {"schema": "openwiz.states.v2"},
            "invalid-clock": ready | {"read_at": "2030-02-31T01:00:00Z"},
            "raw-source": ready | {"private_input": "synthetic input"}
        }
        for name, patch in {
            "unknown-state": {"state": "in-progress"},
            "missing-problem-reason": {"problem": {"kind": "held"}},
            "repeated-blocker": {"blockers": [9103, 9103]},
            "merged-without-merge-time": {
                "state": "merged", "pull_request": {
                    "repo": "example/forge", "number": 9201, "merged_at": None
                }
            }
        }.items():
            rejected[name] = ready | {"tickets": [ready["tickets"][0] | patch]}
        for name, patch in {
            "bad-name": {"name": "builder-09101"},
            "wrong-role-name": {"name": "reviewer-9201-1"},
            "fleet-with-ticket": {"name": "fleet-9001", "role": "fleet"},
            "missing-fixer-pr": {"name": "fixer-9201-1", "role": "fixer"}
        }.items():
            rejected[name] = ready | {"agents": [ready["agents"][0] | patch]}
        rejected["private-provenance"] = copy.deepcopy(ready)
        rejected["private-provenance"]["agents"][0]["record"]["thread"] = "synthetic input"
        for name, snapshot in rejected.items():
            with self.subTest(case=name):
                self.assertFalse(validator.is_valid(snapshot))

    def test_ping_form_and_refusals(self):
        validator = self.validator("ping")
        for name, case in read(HERE / "pings.json").items():
            with self.subTest(case=name):
                self.assertEqual(case["accepted"], validator.is_valid(case["comment"]))


if __name__ == "__main__":
    unittest.main()
