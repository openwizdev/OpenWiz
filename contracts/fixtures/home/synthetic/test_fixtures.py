#!/usr/bin/env python3
from datetime import datetime, timedelta
import json
from pathlib import Path
from runpy import run_path
import unittest

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[2]
DOC = CONTRACTS / "home.v1.md"
SCHEMA = CONTRACTS / "home.v1.schema.json"
RULES = (
    "Machine", "Project", "The Wiz thread", "Boot inputs", "State",
    "Watchdog", "Installed loops", "Chat", "Updates", "Server",
)

SETTINGS_VALIDATOR = run_path(str(CONTRACTS / "fixtures" / "settings" / "test_fixtures.py"))
load, errors = SETTINGS_VALIDATOR["load"], SETTINGS_VALIDATOR["errors"]


def utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def watchdog_fixture_is_late(case, schema):
    now = utc(case["now"])
    completed = []
    for line in case.get("log", []):
        if errors(line, schema, schema):
            continue
        time, loop_id, status, _ = line.split(" ", 3)
        try:
            time = utc(time)
        except ValueError:
            continue
        if loop_id == case["loop"] and status in {"ok", "quiet"} and time <= now:
            completed.append(time)
    last = max(completed, default=None)
    if case.get("lastRunStatus") == "failed":
        return True
    if "every_ms" in case:
        return last is None or now - last > 2 * timedelta(milliseconds=case["every_ms"])
    if not case.get("last_due"):
        return False
    due = utc(case["last_due"])
    return now > due + timedelta(minutes=30) and (last is None or last < due)


class Home(unittest.TestCase):
    def test_contract(self):
        self.assertTrue(DOC.is_file(), "contracts/home.v1.md is missing")
        text = DOC.read_text(encoding="utf-8")
        scenarios = (HERE / "scenarios.md").read_text(encoding="utf-8")
        for rule in RULES:
            with self.subTest(rule=rule):
                self.assertIn(f"## {rule}\n", text)
                self.assertIn(f"## {rule}\n", scenarios)
        self.assertIn("[`roles.orchestrator`](settings.v1.md#fields)", text)
        self.assertIn("(settings.v1.md#where-the-file-lives)", text)

    def test_valid_records(self):
        schema = load(SCHEMA)
        for value in load(HERE / "valid.json"):
            with self.subTest(record=value):
                self.assertEqual(errors(value, schema, schema), [])

    def test_invalid_records(self):
        schema = load(SCHEMA)
        for name, case in load(HERE / "invalid.json").items():
            with self.subTest(case=name):
                self.assertTrue(errors(case, schema, schema), f"accepted {name}")

    def test_duplicate_loop_id(self):
        fixture = HERE / "duplicate-loop-id.json"
        schema = load(SCHEMA)
        last_value_wins = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(errors(last_value_wins, schema, schema), [])
        with self.assertRaisesRegex(ValueError, "^repeated key synthetic-sweep$"):
            load(fixture)

    def test_watchdog(self):
        schema = load(SCHEMA)
        for name, case in load(HERE / "watchdog.json").items():
            with self.subTest(case=name):
                self.assertEqual(watchdog_fixture_is_late(case, schema), case["late"])


if __name__ == "__main__":
    unittest.main()
