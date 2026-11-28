#!/usr/bin/env python3
import json
import runpy
from pathlib import Path
from unittest import TestCase, main

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
SCHEMA = CONTRACTS / "usage.v1.schema.json"
SETTINGS_PROOF = HERE.parent / "settings" / "test_fixtures.py"

INVALID = {
    "account-id-field": "$.accountId: unexpected",
    "email-field": "$.email: unexpected",
    "harness-left": "$: matches a refused form",
    "nested-account-key-field": "$.windows[0].account_key: unexpected",
    "nested-token-field": "$.target.accessToken: unexpected",
    "organisation-id-field": "$.organisation_id: unexpected",
    "pace-without-target": "$: missing target",
    "percent-above-hundred": "$.windows[0].used_percent: out of range",
    "percent-below-zero": "$.windows[0].used_percent: out of range",
    "raw-message": "$.message: not",
    "response-extra-field": "$.token: unexpected",
    "target-without-margin": "$: missing margin",
    "unavailable-without-reason": "$: missing reason",
    "unavailable-zero": "$.windows: 1 items",
}

PACE_EDGES = {
    "lower-edge": (35, "on pace"),
    "upper-edge": (45, "on pace"),
    "behind": (34.99, "behind"),
    "ahead": (45.01, "ahead"),
}


class UsageFixtures(TestCase):
    def schema(self):
        self.assertTrue(SCHEMA.is_file(), "usage.v1.schema.json is missing")
        return json.loads(SCHEMA.read_text(encoding="utf-8"))

    def test_valid_readings_and_responses_match_the_schema(self):
        schema = self.schema()
        proof = runpy.run_path(str(SETTINGS_PROOF))
        paths = sorted((HERE / "valid").glob("*.json"))
        self.assertEqual(len(paths), 15)
        for path in paths:
            with self.subTest(path=path.name):
                self.assertEqual(proof["errors"](proof["load"](path), schema, schema), [])

    def test_invalid_readings_and_responses_are_refused_at_the_expected_field(self):
        schema = self.schema()
        proof = runpy.run_path(str(SETTINGS_PROOF))
        self.assertEqual({path.stem for path in (HERE / "invalid").glob("*.json")}, set(INVALID))
        for name, expected in INVALID.items():
            with self.subTest(name=name):
                shape = "response" if name.startswith("response-") else "lane"
                fixture = proof["load"](HERE / "invalid" / f"{name}.json")
                errors = proof["errors"](fixture, schema["$defs"][shape], schema)
                self.assertTrue(any(error.startswith(expected) for error in errors), errors)
                self.assertTrue(proof["errors"](fixture, schema, schema))

    def test_history_line_and_pace_edges(self):
        schema = self.schema()
        proof = runpy.run_path(str(SETTINGS_PROOF))
        path = HERE / "history.jsonl"
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("\n"))
        self.assertEqual(len(text.splitlines()), 1)
        baseline = proof["load"](path)
        self.assertEqual(proof["errors"](baseline, schema["$defs"]["lane"], schema), [])
        self.assertEqual(baseline["checked_at"], "2030-01-10T00:00:00Z")
        self.assertEqual(baseline["windows"][0]["used_percent"], 20)
        for name, (observed, pace) in PACE_EDGES.items():
            with self.subTest(name=name):
                reading = proof["load"](HERE / "valid" / f"pace-{name}.json")
                self.assertEqual(reading["lane"], baseline["lane"])
                self.assertEqual(reading["checked_at"], "2030-01-10T12:00:00Z")
                self.assertEqual(reading["target"], {
                    "amount": 60, "unit": "percent", "by": "2030-01-11T00:00:00Z",
                })
                self.assertEqual(reading["margin"], 5)
                self.assertEqual(reading["windows"][0], dict(baseline["windows"][0], used_percent=observed))
                self.assertEqual(reading["pace"], pace)


if __name__ == "__main__":
    main()
