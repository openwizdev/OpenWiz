"""Check the public context-engine fixtures with a Draft 2020-12 validator."""

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


FIXTURES = Path(__file__).resolve().parent
CONTRACTS = FIXTURES.parent.parent


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def broken_record(valid, recipe):
    record = copy.deepcopy(valid[recipe["from"]])
    for path, value in recipe.get("set", {}).items():
        *parents, field = path.split(".")
        target = record
        for name in parents:
            target = target[int(name)] if isinstance(target, list) else target[name]
        if isinstance(target, list):
            target[int(field)] = value
        else:
            target[field] = value
    return record


class ContextEngineContract(unittest.TestCase):
    def test_contract_fixtures(self):
        schema_path = CONTRACTS / "context-engine.v1.schema.json"
        self.assertTrue(schema_path.is_file(), "context-engine v1 schema is missing")
        schema = read(schema_path)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        cases = read(FIXTURES / "cases.json")
        for name, record in cases["valid"].items():
            with self.subTest(valid=name):
                validator.validate(record)
        for name, recipe in cases["broken"].items():
            with self.subTest(broken=name):
                self.assertFalse(validator.is_valid(broken_record(cases["valid"], recipe)))

        # Every top-level field and every fixed-shape nested field is required.
        # A pillar map is intentionally free to have any number of owner entries.
        for name, record in cases["valid"].items():
            for field in record:
                with self.subTest(missing=f"{name}/{field}"):
                    self.assertFalse(validator.is_valid({k: v for k, v in record.items() if k != field}))
            if record["kind"] == "ledger":
                for field in record["state"]:
                    with self.subTest(missing=f"{name}/state/{field}"):
                        candidate = copy.deepcopy(record)
                        del candidate["state"][field]
                        self.assertFalse(validator.is_valid(candidate))


if __name__ == "__main__":
    unittest.main()
