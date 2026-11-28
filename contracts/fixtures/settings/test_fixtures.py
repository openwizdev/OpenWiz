#!/usr/bin/env python3
import json
import math
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
DOC = CONTRACTS / "settings.v1.md"
SCHEMA = CONTRACTS / "settings.v1.schema.json"
MODELS = CONTRACTS / "models.v1.md"
VALID, INVALID = HERE / "valid", HERE / "invalid"
ROLES = ("orchestrator", "builder", "fixer", "reviewer", "small_builder")
RULES = {"cross_family", "reserved_in_role", "reserved_in_fallback", "key_shaped", "at_in_label",
         "history_over_10", "unknown_field", "overflow_not_builders"}
PRIVATE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}|/(?:Users|home)/|\bthr_|\b(?:proj|prj|mch|usr|acct|auto)_|"
    r"\b(?:sk-(?!syn-)|gh[pousr]_|github_pat_|xox[abprs]-|AKIA|AIza|eyJ)[A-Za-z0-9_-]{8}|-----BEGIN")


def pairs(items):
    seen = {}
    for key, value in items:
        if key in seen:
            raise ValueError("repeated key " + key)
        seen[key] = value
    return seen


def load(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def kind_ok(value, kind):
    return {"object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": type(value) is bool,
            "integer": type(value) is int, "null": value is None,
            "number": type(value) in (int, float) and math.isfinite(value)}[kind]


def errors(value, schema, root, at="$"):
    known = {"$schema", "$id", "$ref", "$defs", "title", "description", "allOf", "oneOf", "not", "if",
             "then", "else", "type", "const", "enum", "pattern", "minLength", "maxLength", "minimum",
             "maximum", "exclusiveMinimum", "minItems", "maxItems", "uniqueItems", "items", "required",
             "properties", "additionalProperties", "propertyNames"}
    unknown = set(schema) - known
    if unknown:
        raise AssertionError(f"schema keyword not supported here: {sorted(unknown)}")
    if "$ref" in schema:
        return errors(value, root["$defs"][schema["$ref"].rsplit("/", 1)[-1]], root, at)
    found = []
    for sub in schema.get("allOf", []):
        found += errors(value, sub, root, at)
    if "oneOf" in schema:
        reports = [errors(value, sub, root, at) for sub in schema["oneOf"]]
        if sum(not report for report in reports) != 1:
            found.append(f"{at}: matches {sum(not r for r in reports)} of oneOf")
            found += min(reports, key=len)
    if "not" in schema and not errors(value, schema["not"], root, at):
        found.append(f"{at}: matches a refused form")
    if "if" in schema:
        branch = "then" if not errors(value, schema["if"], root, at) else "else"
        if branch in schema:
            found += errors(value, schema[branch], root, at)
    kinds = schema.get("type", [])
    kinds = kinds if isinstance(kinds, list) else [kinds]
    if kinds and not any(kind_ok(value, kind) for kind in kinds):
        return found + [f"{at}: not {' or '.join(kinds)}"]
    if "const" in schema and value != schema["const"]:
        found.append(f"{at}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{at}: not in {schema['enum']}")
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", math.inf):
            found.append(f"{at}: wrong length")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            found.append(f"{at}: does not match {schema['pattern']}")
    if type(value) in (int, float):
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            found.append(f"{at}: out of range")
        if "exclusiveMinimum" in schema and not value > schema["exclusiveMinimum"]:
            found.append(f"{at}: not above {schema['exclusiveMinimum']}")
    if isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", math.inf):
            found.append(f"{at}: {len(value)} items")
        if schema.get("uniqueItems") and len({json.dumps(v, sort_keys=True) for v in value}) != len(value):
            found.append(f"{at}: repeated items")
        for index, item in enumerate(value):
            found += errors(item, schema.get("items", {}), root, f"{at}[{index}]")
    if isinstance(value, dict):
        found += [f"{at}: missing {key}" for key in schema.get("required", []) if key not in value]
        properties, extra = schema.get("properties", {}), schema.get("additionalProperties", True)
        for key, item in value.items():
            if "propertyNames" in schema:
                found += [f"{at}.{key}: bad name: {e}" for e in errors(key, schema["propertyNames"], root, at)]
            if key in properties:
                found += errors(item, properties[key], root, f"{at}.{key}")
            elif extra is False:
                found.append(f"{at}.{key}: unexpected")
            elif isinstance(extra, dict):
                found += errors(item, extra, root, f"{at}.{key}")
    return found


def choices(doc):
    for role in ROLES:
        choice = doc["roles"][role]
        if isinstance(choice, dict):
            yield f"$.roles.{role}", choice, "role"
            for index, entry in enumerate(choice["fallback"]):
                yield f"$.roles.{role}.fallback[{index}]", entry, "fallback"


def rule_errors(doc):
    found = []
    for part in [doc] + doc.get("history", []):
        accounts = part["accounts"]
        on = {name for name, turned_on in part["drivers"].items() if turned_on}
        for at, choice, where in choices(part):
            account = accounts.get(choice["account"])
            if account is None or account["harness"] != choice["harness"]:
                found.append(f"{at}.account: no {choice['harness']} account {choice['account']!r}")
            elif account["reserved"]:
                found.append(f"{at}.account: reserved account in a {where}")
        hosts = part["hosts"]
        named = [(f"$.hosts.home.{r}", h) for r, h in hosts["home"].items()]
        named += [("$.hosts.overflow.host", hosts["overflow"]["host"])] if hosts["overflow"] else []
        named += [(f"$.hosts.projects.{p}", h) for p, line in hosts["projects"].items() for h in line]
        found += [f"{at}: host {host!r} is not a turned-on driver" for at, host in named if host not in on]
    version, held = doc["version"], [entry["version"] for entry in doc["history"]]
    if held != list(range(max(1, version - 10), version)):
        found.append("$.history: must hold the versions just before this one, oldest first, up to 10")
    return found


def refusals(doc, schema):
    found = errors(doc, schema, schema)
    return found or rule_errors(doc)


def fields_table(text):
    section = re.search(r"^## Fields\n(.*?)(?=^## )", text, re.M | re.S)
    if section is None:
        return []
    rows = [line for line in section[1].splitlines() if line.startswith("| `")]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def property_names(schema):
    names = set()
    if isinstance(schema, dict):
        names |= set(schema.get("properties", {}))
        for value in schema.values():
            names |= property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= property_names(value)
    return names


def free_strings(node, at="#"):
    if isinstance(node, dict):
        if node.get("type") == "string" and "const" not in node and "enum" not in node:
            yield at, node
        for key, value in node.items():
            yield from free_strings(value, f"{at}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from free_strings(value, f"{at}/{index}")


class Settings(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DOC.is_file(), "settings.v1.md is missing")
        self.assertTrue(SCHEMA.is_file(), "settings.v1.schema.json is missing")
        self.schema, self.text = load(SCHEMA), DOC.read_text(encoding="utf-8")

    def test_every_valid_fixture_is_accepted(self):
        names = sorted(VALID.glob("*.json"))
        self.assertGreaterEqual(len(names), 3)
        for path in names:
            with self.subTest(path.name):
                self.assertEqual(refusals(load(path), self.schema), [])

    def test_every_invalid_fixture_is_refused_for_its_rule(self):
        expect = load(INVALID / "expect.json")
        self.assertEqual(sorted(expect), sorted(p.name for p in INVALID.glob("*.json") if p.name != "expect.json"))
        self.assertLessEqual(RULES, {case["rule"] for case in expect.values()})
        for name, case in expect.items():
            with self.subTest(name):
                doc = load(INVALID / name)
                found = errors(doc, self.schema, self.schema)
                if case["by"] == "rule":
                    self.assertEqual(found, [], "the schema alone accepts a cross-section case")
                    found = rule_errors(doc)
                self.assertTrue(any(line.startswith(case["at"]) for line in found), found)
                self.assertIn(f"`{name}`", self.text, "the contract names each fixture")

    def test_each_invalid_fixture_is_a_valid_one_with_one_change(self):
        for name, case in load(INVALID / "expect.json").items():
            with self.subTest(name):
                base, doc = load(VALID / case["from"]), load(INVALID / name)
                changed = [k for k in set(base) | set(doc) if base.get(k) != doc.get(k)]
                self.assertEqual(len(changed), 1, changed)

    def test_the_cross_family_reason_is_the_contracts(self):
        reason = load(INVALID / "expect.json")["reviewer-builder-family.json"]["reason"]
        self.assertIn(reason, self.text)
        self.assertIn("models.v1.md#the-cross-family-rule", self.text)

    def test_any_free_string_refuses_a_key_shaped_value(self):
        no_key = {"$ref": "#/$defs/no_key"}
        for at, node in free_strings(self.schema):
            with self.subTest(at):
                self.assertIn(no_key, node.get("allOf", []))
        for value in ("sk-" + "0" * 24, "ghp_" + "0" * 36, "-----BEGIN SYN KEY-----",
                      "eyJzeW4iOiJzeW4ifQ.syn", "A" * 40):
            self.assertTrue(errors(value, no_key, self.schema), value)
        for value in ("work", "openwiz-devin", "claude-opus-5-5", "vendor/demo", "~/.syn-work"):
            self.assertEqual(errors(value, no_key, self.schema), [], value)

    def test_a_new_file_is_local_only_opt_in_off_telemetry_off_updates_ask(self):
        block = re.search(r"^## A new file\n.*?```json\n(.*?)^```$", self.text, re.M | re.S)
        self.assertIsNotNone(block, "the contract's new-file block is missing")
        new = json.loads(block[1])
        for path in sorted(VALID.glob("new-file*.json")):
            with self.subTest(path.name):
                doc = load(path)
                for key, value in new.items():
                    self.assertEqual(doc[key], value, key)
                self.assertEqual([name for name, on in doc["drivers"].items() if on], ["local"])
                self.assertEqual([name for name, on in doc["channels"].items() if on], ["t3"])
                self.assertEqual([n for n, k in doc["keys"].items() if k["opt_in"] and k["on"]], [])
                self.assertTrue(any(k["opt_in"] for k in doc["keys"].values()), "a new file shows an opt-in key")
                self.assertEqual((doc["telemetry"], doc["updates"], doc["changed_by"]), (False, "ask", "fill"))
        self.assertGreaterEqual(len(list(VALID.glob("new-file*.json"))), 2)

    def test_the_contract_names_every_field_with_type_default_and_writer(self):
        rows = fields_table(self.text)
        self.assertTrue(rows, "the Fields table is missing")
        named = set()
        for row in rows:
            self.assertEqual(len(row), 4, row)
            self.assertTrue(all(row), row)
            named |= {part.strip("`[]<>") for part in re.split(r"[.\s]", row[0].strip("`"))}
        missing = property_names(self.schema) - named
        self.assertEqual(missing, set())
        for word in ("`openwiz settings`", "`openwiz/settings`", "`.openwiz/settings.json`",
                     "`key-use.log` in the home checkout's `.openwiz/home` folder", "agents only read"):
            self.assertIn(word, self.text)

    def test_the_key_use_log_holds_names_and_times_only(self):
        rule = re.search(r"^Each line is exactly `(.*?)`", self.text, re.M)
        self.assertIsNotNone(rule, "the key-use line rule is missing")
        self.assertEqual(rule[1], "<key name> <UTC time>")
        keys = load(VALID / "full.json")["keys"]
        line = re.compile(r"^([A-Za-z0-9_-]{1,32}) ([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z)$")
        last = {}
        for text in (HERE / "key-use.log").read_text(encoding="utf-8").splitlines():
            match = line.match(text)
            self.assertIsNotNone(match, text)
            self.assertIn(match[1], keys)
            last[match[1]] = max(last.get(match[1], ""), match[2])
        self.assertEqual(last, load(HERE / "last-used.json"))

    def test_models_v1_points_here_in_one_paragraph(self):
        paragraphs = [p for p in MODELS.read_text(encoding="utf-8").split("\n\n") if "settings.v1.md" in p]
        self.assertEqual(len(paragraphs), 1)
        self.assertIn("`.openwiz/settings.json`", paragraphs[0])
        self.assertIn("`## Models`", paragraphs[0])

    def test_nothing_real_in_the_contract_schema_or_fixtures(self):
        shapes = {key: value for key, value in self.schema["$defs"].items() if key != "no_key"}
        self.assertIsNone(PRIVATE.search(json.dumps({**self.schema, "$defs": shapes})), "the schema")
        for path in [DOC] + sorted(p for p in HERE.rglob("*") if p.is_file() and p.suffix != ".py"):
            with self.subTest(path.name):
                self.assertIsNone(PRIVATE.search(path.read_text(encoding="utf-8")), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
