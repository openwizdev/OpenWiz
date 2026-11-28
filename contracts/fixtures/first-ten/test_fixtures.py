import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT.parent.parent / "first-ten.v1.schema.json"


class FirstTenFixtures(unittest.TestCase):
    def test_schema_accepts_good_records_and_rejects_each_broken_rule(self):
        pairs = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
        valid = json.loads((ROOT / "valid.json").read_text(encoding="utf-8"))
        broken = json.loads((ROOT / "broken.json").read_text(encoding="utf-8"))
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertEqual(set(pairs), set(broken))
        self.assertEqual({case["valid"] for case in pairs.values()}, set(valid))
        for rule, case in pairs.items():
            with self.subTest(rule=rule):
                row = f'| `{rule}` | `{case["valid"]}` | `{rule}` |'
                self.assertIn(row, readme)

        self.assertTrue(SCHEMA.is_file(), "first-ten records have no schema to validate them")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for name, record in valid.items():
            with self.subTest(valid=name):
                self.assertEqual(list(validator.iter_errors(record)), [])

        for rule, case in pairs.items():
            with self.subTest(broken=rule):
                errors = list(validator.iter_errors(broken[rule]))
                actual = {(tuple(error.path), error.validator) for error in errors}
                self.assertIn((tuple(case["path"]), case["keyword"]), actual)


if __name__ == "__main__":
    unittest.main()
