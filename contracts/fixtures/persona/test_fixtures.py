#!/usr/bin/env python3
from copy import deepcopy
from pathlib import Path
import runpy
import unittest

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[1] / "persona.v1.schema.json"
validator = runpy.run_path(str(HERE.parent / "value-meter" / "test_fixtures.py"))
load, errors = validator["load"], validator["errors"]


def changed(document, case):
    broken = deepcopy(document)
    target = broken
    *parents, field = case["path"]
    for parent in parents:
        target = target[parent]
    if "value" in case:
        target[field] = case["value"]
    else:
        del target[field]
    return broken


class PersonaContract(unittest.TestCase):
    def test_valid_and_broken_documents(self):
        self.assertTrue(SCHEMA.is_file(), "persona.v1.schema.json is missing")
        schema = load(SCHEMA)
        docs = {kind: load(HERE / f"{kind}.json") for kind in ("persona", "theme")}
        for kind, document in docs.items():
            with self.subTest(valid=kind):
                self.assertEqual(errors(document, schema, schema), [])
        for family in ("film-ai", "character", "pro", "fun"):
            with self.subTest(family=family):
                self.assertEqual(errors({**docs["persona"], "family": family}, schema, schema), [])
        self.assertEqual(errors({**docs["theme"], "sounds": {}}, schema, schema), [])
        for case in load(HERE / "broken.json"):
            with self.subTest(broken=case["rule"]):
                baseline = docs[case["kind"]]
                self.assertEqual(errors(baseline, schema, schema), [])
                self.assertTrue(errors(changed(baseline, case), schema, schema))

    def test_styling_preserves_source_bytes(self):
        fixtures = load(HERE / "rendering.json")
        protected = ("facts", "next_command", "json_output", "record", "contract")
        source = fixtures["source"]
        styled = fixtures["styled"]
        self.assertNotEqual(source["framing"], styled["framing"])
        self.assertEqual({k: source[k].encode("utf-8") for k in protected},
                         {k: styled[k].encode("utf-8") for k in protected})
        for case in fixtures["broken"]:
            with self.subTest(broken=case["path"]):
                broken = changed(styled, case)
                self.assertNotEqual({k: source[k].encode("utf-8") for k in protected},
                                    {k: broken[k].encode("utf-8") for k in protected})


if __name__ == "__main__":
    unittest.main()
