import json
from pathlib import Path
import re
import unittest

from jsonschema import Draft202012Validator


HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]


def leaf_errors(error):
    if not error.context:
        yield (list(error.absolute_path), error.validator)
    for child in error.context:
        yield from leaf_errors(child)


class HotUpdateFixtures(unittest.TestCase):
    def test_fixture_pairs(self):
        cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
        documented = (HERE / "README.md").read_text(encoding="utf-8")
        self.assertEqual(
            re.findall(r"^\| `([a-z0-9-]+)` \|", documented, re.MULTILINE),
            list(cases),
        )
        path = CONTRACTS / "hot-update.v1.schema.json"
        self.assertTrue(path.is_file(), "hot-update schema must exist for the fixture pairs")
        schema = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        for name, case in cases.items():
            with self.subTest(rule=name, fixture="valid"):
                validator.validate(case["valid"])
            with self.subTest(rule=name, fixture="broken"):
                errors = [
                    refusal
                    for error in validator.iter_errors(case["broken"])
                    for refusal in leaf_errors(error)
                ]
                self.assertIn((case["path"], case["keyword"]), errors)
        print(f"Checked {len(cases)} valid and {len(cases)} broken synthetic fixtures.")

    def test_contract_pins_owner_policy_and_kernel_swap_point(self):
        path = CONTRACTS / "hot-update.v1.md"
        self.assertTrue(path.is_file(), "hot-update contract must state the owner and swap rules")
        contract = path.read_text(encoding="utf-8")
        self.assertIn("The default is `ask`.", contract)
        self.assertIn("A minor version always asks", contract)
        self.assertRegex(
            contract,
            r"(?m)^The kernel swaps the installer's existing `<ROOT>/current` link "
            r"from the \[install contract\]\(install\.v1\.md\)\.",
        )


if __name__ == "__main__":
    unittest.main()
