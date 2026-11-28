#!/usr/bin/env python3
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
SCHEMA = CONTRACTS / "next-prompt.v1.schema.json"


class NextPromptFixtures(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8")) if SCHEMA.is_file() else {}
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema, format_checker=FormatChecker())

    def test_each_rule_accepts_its_valid_fixture_and_refuses_its_broken_fixture(self):
        # comment-ok: catches: a schema admitting an unsupported source, fallback, or acceptance record.
        examples = json.loads((HERE / "valid.json").read_text(encoding="utf-8"))
        cases = json.loads((HERE / "broken.json").read_text(encoding="utf-8"))
        self.assertEqual(set(examples), {case["valid"] for case in cases})
        self.assertEqual(len(cases), len({case["rule"] for case in cases}))
        admitted = []
        for case in cases:
            with self.subTest(rule=case["rule"]):
                valid = examples[case["valid"]]
                self.validator.validate(valid)
                broken = copy.deepcopy(valid)
                parent = broken
                for key in case["at"][:-1]:
                    parent = parent[key]
                field = case["at"][-1]
                if "value" in case:
                    parent[field] = case["value"]
                else:
                    del parent[field]
                self.assertNotEqual(broken, valid)
                if self.validator.is_valid(broken):
                    admitted.append(case["rule"])
        self.assertFalse(admitted, f"Schema admitted broken rules: {', '.join(admitted)}")

    def test_predict_surfaces_match_the_unchanged_ghost_contract(self):
        # comment-ok: catches: the extension accepting different composer surfaces from ghost v1.
        ghost = json.loads((CONTRACTS / "ghost.v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(self.schema.get("$defs", {}).get("surface"), ghost["$defs"]["surface"])
        predict = self.validator.evolve(schema={"$ref": "#/$defs/predict_request"})
        for surface in ghost["$defs"]["surface"]["enum"]:
            with self.subTest(surface=surface):
                predict.validate({"surface": surface})


if __name__ == "__main__":
    unittest.main(verbosity=2)
