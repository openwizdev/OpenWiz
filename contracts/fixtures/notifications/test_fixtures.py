#!/usr/bin/env python3
import json
from pathlib import Path
import re
import unittest
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker


HERE = Path(__file__).resolve().parent
CONTRACT = HERE.parents[1] / "notifications.v1.md"
SCHEMA = CONTRACT.with_suffix(".schema.json")
FORMATS = FormatChecker()


@FORMATS.checks("iana-time-zone", raises=(ZoneInfoNotFoundError, ValueError))
def is_time_zone(value):
    return not isinstance(value, str) or bool(ZoneInfo(value))


class NotificationFixtures(unittest.TestCase):
    def test_schema_accepts_and_refuses_each_listed_pair(self):
        # catches: an incomplete or permissive preference or default schema.
        cases = json.loads((HERE / "cases.json").read_text())
        readme = (HERE / "README.md").read_text()
        names = [case["rule"] for case in cases]
        self.assertEqual(re.findall(r"^\| `([\w-]+)` \|", readme, re.M), names)
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(SCHEMA.is_file(), f"{SCHEMA.name} is missing")
        schema = json.loads(SCHEMA.read_text())
        Draft202012Validator.check_schema(schema)
        for case in cases:
            with self.subTest(rule=case["rule"]):
                target = dict(schema, **{"$ref": case.get("ref", schema["$ref"])})
                validator = Draft202012Validator(target, format_checker=FORMATS)
                validator.validate(case["valid"])
                actual = [(error.validator, list(error.absolute_path))
                          for error in validator.iter_errors(case["broken"])]
                self.assertEqual(actual, [(case["keyword"], case["at"])])

    def test_contract_example_and_channel_gate(self):
        # catches: an unusable example or a contract that drops the Settings gate.
        self.assertTrue(CONTRACT.is_file(), f"{CONTRACT.name} is missing")
        schema = json.loads(SCHEMA.read_text())
        contract = CONTRACT.read_text()
        examples = re.findall(r"(?ms)^~~~json\n(.*?)^~~~$", contract)
        self.assertEqual(len(examples), 1)
        Draft202012Validator(schema, format_checker=FORMATS).validate(json.loads(examples[0]))
        self.assertIn(
            "A channel beyond T3 is never used unless that channel is on in Settings.",
            contract.splitlines(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
