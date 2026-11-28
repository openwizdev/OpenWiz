import hashlib
import json
import re
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCHEMA = HERE.parents[1] / "factory-bench.v1.schema.json"
READINGS = {"pass", "baseline", "fail", "unknown"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate(value, rule, defs, at="$"):
    supported = {
        "$ref", "oneOf", "type", "const", "enum", "pattern", "minLength",
        "minimum", "minItems", "items", "required", "properties",
        "additionalProperties",
    }
    if rule.keys() - supported:
        raise ValueError(f"{at}: unsupported schema keyword")
    if "$ref" in rule:
        return validate(value, defs[rule["$ref"].removeprefix("#/$defs/")], defs, at)
    if "oneOf" in rule:
        matches = [validate(value, option, defs, at) for option in rule["oneOf"]]
        return [] if matches.count([]) == 1 else [f"{at}: expected exactly one matching shape"]
    types = {
        "object": (dict,), "array": (list,), "string": (str,), "null": (type(None),),
        "integer": (int,), "number": (int, float),
    }
    kind = rule.get("type")
    if kind and type(value) not in types[kind]:
        return [f"{at}: expected {kind}"]
    for keyword, valid in (
        ("const", lambda x: value == x),
        ("enum", lambda x: value in x),
        ("pattern", lambda x: re.search(x, value)),
        ("minLength", lambda x: len(value) >= x),
        ("minimum", lambda x: value >= x),
        ("minItems", lambda x: len(value) >= x),
    ):
        if keyword in rule and not valid(rule[keyword]):
            return [f"{at}: violates {keyword}"]
    errors = []
    if kind == "object":
        properties = rule.get("properties", {})
        errors.extend(f"{at}.{key}: required" for key in rule.get("required", []) if key not in value)
        for key, item in value.items():
            if key in properties:
                errors.extend(validate(item, properties[key], defs, f"{at}.{key}"))
            elif rule.get("additionalProperties") is False:
                errors.append(f"{at}.{key}: unexpected")
    if kind == "array":
        for index, item in enumerate(value):
            errors.extend(validate(item, rule["items"], defs, f"{at}[{index}]"))
    return errors


def task_set_hash(task_set):
    canonical = json.dumps(task_set, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def score(result):
    tasks = result["tasks"]
    return Fraction(sum(task["result"] == "pass" for task in tasks), len(tasks))


def reading(candidate, previous, task_set, defs):
    expected_hash = task_set_hash(task_set)
    ids = {task["id"] for task in task_set["tasks"]}

    def incomplete(result):
        actual = [task["id"] for task in result["tasks"]]
        return len(actual) != len(ids) or set(actual) != ids

    if candidate is None:
        return "unknown: candidate result missing"
    if validate(candidate, defs["result"], defs) or incomplete(candidate):
        return "unknown: candidate result unreadable"
    if candidate["hash"] != expected_hash:
        return "unknown: candidate task-set hash differs"
    if previous is None:
        return "baseline"
    if validate(previous, defs["result"], defs):
        return "unknown: previous result unreadable"
    if previous["hash"] != expected_hash:
        return "baseline"
    if incomplete(previous):
        return "unknown: previous result unreadable"
    if score(previous) - score(candidate) > Fraction(1, 20):
        return "fail: score dropped by more than 0.05"
    return "pass"


class FactoryBench(unittest.TestCase):
    def schema(self):
        self.assertTrue(SCHEMA.is_file(), "factory bench schema is missing")
        return read(SCHEMA)

    def test_task_set_and_each_reading_fixture(self):
        schema = self.schema()
        defs = schema["$defs"]
        task_set = read(HERE / "tasks.v1.json")
        self.assertEqual(validate(task_set, {"oneOf": schema["oneOf"]}, defs), [])
        cases = {path.stem: read(path) for path in HERE.glob("*.json") if path.name != "tasks.v1.json"}
        self.assertEqual(set(cases), READINGS)
        for name, case in cases.items():
            with self.subTest(reading=name):
                for result in (case["candidate"], case["previous"]):
                    if result is not None:
                        self.assertEqual(validate(result, {"oneOf": schema["oneOf"]}, defs), [])
                actual = reading(case["candidate"], case["previous"], task_set, defs)
                self.assertEqual(actual.split(":", 1)[0], name)
                self.assertEqual(actual, case["expected"])
                if case["candidate"] is not None:
                    tasks = case["candidate"]["tasks"]
                    unproved = [task["id"] for task in tasks if task["result"].startswith("unproved: ")]
                    self.assertEqual(unproved, case["unproved"])
                    self.assertEqual(score(case["candidate"]), Fraction(case["score"]))

    def test_refuses_a_planted_bad_task(self):
        defs = self.schema()["$defs"]
        example = read(HERE / "tasks.v1.json")
        source = example["tasks"][0]["source"]
        for field, value in (("licence", "GPL-3.0-only"), ("commit", "main")):
            with self.subTest(field=field):
                original = source[field]
                source[field] = value
                self.assertTrue(any(f".source.{field}:" in error
                                    for error in validate(example, defs["task_set"], defs)),
                                f"schema accepted a planted bad {field}")
                source[field] = original

    def test_unknown_on_unreadable_or_mismatched_candidate(self):
        defs = self.schema()["$defs"]
        task_set = read(HERE / "tasks.v1.json")
        case = read(HERE / "pass.json")
        candidate, previous = case["candidate"], case["previous"]
        self.assertEqual(reading("broken JSON", previous, task_set, defs),
                         "unknown: candidate result unreadable")
        candidate["tasks"][0]["result"] = "unproved: "
        self.assertEqual(reading(candidate, previous, task_set, defs),
                         "unknown: candidate result unreadable")
        self.assertEqual(reading(previous, "broken JSON", task_set, defs),
                         "unknown: previous result unreadable")
        candidate["tasks"][0]["result"] = "pass"
        candidate["hash"] = "0" * 64
        self.assertEqual(reading(candidate, previous, task_set, defs),
                         "unknown: candidate task-set hash differs")

    def test_accepts_a_drop_of_exactly_five_percentage_points(self):
        defs = self.schema()["$defs"]
        task_set = read(HERE / "tasks.v1.json")
        case = read(HERE / "pass.json")
        task = task_set["tasks"][0]
        task_set["tasks"] = [dict(task, id=f"sample-{n}") for n in range(20)]
        candidate, previous = case["candidate"], case["previous"]
        for result, passes in ((candidate, 9), (previous, 10)):
            example = result["tasks"][0]
            result["hash"] = task_set_hash(task_set)
            result["tasks"] = [
                dict(example, id=task["id"], result="pass" if n < passes else "fail")
                for n, task in enumerate(task_set["tasks"])
            ]
        self.assertEqual(reading(candidate, previous, task_set, defs), "pass")
        candidate["tasks"][0]["result"] = "fail"
        self.assertEqual(reading(candidate, previous, task_set, defs),
                         "fail: score dropped by more than 0.05")


if __name__ == "__main__":
    unittest.main(verbosity=2)
