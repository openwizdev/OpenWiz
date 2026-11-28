#!/usr/bin/env python3
import json
import math
import re
import sys
import unittest
from datetime import date, datetime, timezone
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
CONTRACT = CONTRACTS / "leaderboard.v1.md"
SCHEMA_PATH = CONTRACTS / "leaderboard.v1.schema.json"
VALID, BROKEN = HERE / "valid", HERE / "broken"
VERSION = "openwiz.leaderboard.v1"
KINDS = {"opt-in": "opt_in", "score": "score", "board": "board", "bans": "ban_list", "case": "case"}
WEIGHT = {"S": 1, "M": 2, "L": 4}
S_MAX, M_MAX, DAILY_CAP = 100, 500, 12
SCORE_FIELDS = {"version", "handle", "period", "pull_requests", "points", "by_size", "boost", "board"}


def pairs(items):
    seen = {}
    for key, value in items:
        if key in seen:
            raise ValueError("repeated key " + key)
        seen[key] = value
    return seen


def load(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def type_ok(value, kind):
    return {
        "object": lambda: isinstance(value, dict), "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str), "boolean": lambda: type(value) is bool,
        "integer": lambda: type(value) is int, "null": lambda: value is None,
        "number": lambda: type(value) in (int, float) and math.isfinite(value),
    }[kind]()


SUPPORTED = {"$schema", "$id", "title", "description", "$defs", "$ref", "oneOf", "if", "then", "else",
             "type", "const", "enum", "pattern", "minimum", "multipleOf", "items", "required",
             "properties", "additionalProperties"}


def errors(value, schema, root, at="$"):
    if schema.keys() - SUPPORTED:
        raise ValueError(f"{at}: unsupported keyword {sorted(schema.keys() - SUPPORTED)}")
    if "$ref" in schema:
        return errors(value, root["$defs"][schema["$ref"].rsplit("/", 1)[-1]], root, at)
    found = []
    if "oneOf" in schema:
        passed = sum(not errors(value, sub, root, at) for sub in schema["oneOf"])
        if passed != 1:
            found.append(f"{at}: matches {passed} of oneOf")
    if "if" in schema:
        branch = "else" if errors(value, schema["if"], root, at) else "then"
        found += errors(value, schema.get(branch, {}), root, at)
    kinds = schema.get("type")
    kinds = kinds if isinstance(kinds, list) else [kinds] if kinds else []
    if kinds and not any(type_ok(value, kind) for kind in kinds):
        return found + [f"{at}: not {' or '.join(kinds)}"]
    if "const" in schema and value != schema["const"]:
        found.append(f"{at}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{at}: not in {schema['enum']}")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        found.append(f"{at}: does not match {schema['pattern']}")
    if type(value) in (int, float):
        if "minimum" in schema and value < schema["minimum"]:
            found.append(f"{at}: below {schema['minimum']}")
        if "multipleOf" in schema and Fraction(value) % Fraction(schema["multipleOf"]):
            found.append(f"{at}: not a multiple of {schema['multipleOf']}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            found += errors(item, schema.get("items", {}), root, f"{at}[{index}]")
    if isinstance(value, dict):
        found += [f"{at}: missing {key}" for key in schema.get("required", []) if key not in value]
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                found += errors(item, properties[key], root, f"{at}.{key}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{at}: unexpected {key}")
    return found


def utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def day(text):
    return date.fromisoformat(text)


def size_of(pr):
    lines = pr["additions"] + pr["deletions"]
    return "S" if lines <= S_MAX else "M" if lines <= M_MAX else "L"


def solo(facts):
    return (facts["owners"], facts["other_contributors"], facts["stars"], facts["forks"]) == (1, 0, 0, 0)


def reviewed(pr):
    return any(review["state"] == "APPROVED" and review["commit"] == pr["head"]
               and review["family"] is not None and review["family"] != pr["builder_family"]
               for review in pr["reviews"])


def score(scorer_input):
    start, end = day(scorer_input["period"]["from"]), day(scorer_input["period"]["to"])
    seen, by_size, days = set(), {"S": 0, "M": 0, "L": 0}, {}
    for pr in scorer_input["pull_requests"]:
        if pr["merged_at"] is None or not start <= utc(pr["merged_at"]).date() <= end:
            continue
        key = (pr["repository"].lower(), pr["number"])
        if key in seen:
            continue
        seen.add(key)
        if not reviewed(pr):
            continue
        size = size_of(pr)
        by_size[size] += 1
        points = Fraction(WEIGHT[size]) / (2 if solo(pr["repository_facts"]) else 1)
        merged = utc(pr["merged_at"]).date()
        days[merged] = days.get(merged, 0) + points
    points = sum(min(DAILY_CAP, total) for total in days.values())
    return {"pull_requests": sum(by_size.values()), "points": float(points), "by_size": by_size}


def kind_of(name):
    return KINDS["opt-in" if name.startswith("opt-in") else name.split("-")[0].removesuffix(".json")]


def outside(name, doc, bans=()):
    kind, found = kind_of(name), []
    if kind == "opt_in" and doc["joined"] is not None:
        if utc(doc["joined"]) < utc(doc["asked"]):
            found.append("$.joined: before asked")
        if doc["left"] is not None and utc(doc["left"]) < utc(doc["joined"]):
            found.append("$.left: before joined")
    records = doc["rows"] if kind == "board" else [doc] if kind == "score" else []
    for index, record in enumerate(records):
        at = f"$.rows[{index}]" if kind == "board" else "$"
        if day(record["period"]["to"]) < day(record["period"]["from"]):
            found.append(f"{at}.period: to before from")
        if sum(record["by_size"].values()) != record["pull_requests"]:
            found.append(f"{at}: by_size does not add up to pull_requests")
        days = (day(record["period"]["to"]) - day(record["period"]["from"])).days + 1
        if record["points"] > min(sum(WEIGHT[s] * n for s, n in record["by_size"].items()), DAILY_CAP * days):
            found.append(f"{at}.points: above what the counted pull requests or the daily cap allow")
    if kind == "board":
        handles = [row["handle"].lower() for row in doc["rows"]]
        if len(set(handles)) != len(handles):
            found.append("$.rows: repeated handle")
        if any(row["period"] != doc["period"] for row in doc["rows"]):
            found.append("$.rows: a row's period is not the board's")
        keys = [(-row["points"], row["handle"].lower()) for row in doc["rows"]]
        if keys != sorted(keys):
            found.append("$.rows: not ranked by points, then handle")
        banned = {ban["handle"].lower() for ban in bans}
        found += [f"$.rows: banned handle {h}" for h in handles if h in banned]
    if kind == "ban_list":
        handles = [ban["handle"].lower() for ban in doc["bans"]]
        if len(set(handles)) != len(handles):
            found.append("$.bans: repeated handle")
    if kind == "case":
        want = score(doc["input"])
        got = {key: doc["claimed"][key] for key in want}
        if got != want or doc["claimed"]["period"] != doc["input"]["period"]:
            found.append(f"$.claimed: {got} is not the rule's {want}")
    return found


class Leaderboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load(SCHEMA_PATH)
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.valid = {p.name: load(p) for p in sorted(VALID.glob("*.json"))}
        cls.broken = {p.name: load(p) for p in sorted(BROKEN.glob("*.json")) if p.name != "expect.json"}
        cls.expect = load(BROKEN / "expect.json")
        cls.bans = cls.valid["bans.json"]["bans"]

    def check(self, name, doc):
        kind = kind_of(name)
        if kind == "case":
            found = errors(doc, self.schema["$defs"]["case"], self.schema)
        else:
            found = errors(doc, self.schema, self.schema)
            found += errors(doc, self.schema["$defs"][kind], self.schema)
        return found or outside(name, doc, self.bans)

    def test_every_rule_has_one_valid_and_one_broken_fixture_in_the_readme(self):
        readme = (HERE / "README.md").read_text(encoding="utf-8")
        rows = re.findall(r"^\| (R\d+) \| [^|]+ \| `valid/([^`]+)` \| `broken/([^`]+)` \|$", readme, re.M)
        self.assertGreaterEqual(len(rows), 11)
        self.assertEqual([rule for rule, _, _ in rows], [f"R{n}" for n in range(1, len(rows) + 1)])
        self.assertEqual({v for _, v, _ in rows}, set(self.valid))
        self.assertEqual({b for _, _, b in rows}, set(self.broken))
        self.assertEqual(len({b for _, _, b in rows}), len(rows))
        for rule, _, _ in rows:
            self.assertIn(f"**{rule}", self.contract, rule)

    def test_valid_fixtures_pass(self):
        for name, doc in self.valid.items():
            self.assertEqual(self.check(name, doc), [], name)

    def test_broken_fixtures_fail_with_the_named_error(self):
        self.assertEqual(set(self.expect), set(self.broken))
        for name, doc in self.broken.items():
            found = self.check(name, doc)
            self.assertNotEqual(found, [], name)
            self.assertIn(self.expect[name], "\n".join(found), name)

    def test_a_score_record_with_a_repository_name_is_refused(self):
        record = dict(self.valid["score.json"], repository="synthetic-owner/synthetic-repo")
        score = self.schema["$defs"]["score"]
        self.assertNotEqual(errors(record, self.schema, self.schema), [])
        self.assertIn("$: unexpected repository", errors(record, score, self.schema))
        for extra in ("path", "title", "branch", "code", "repositories", "kind"):
            self.assertIn(f"$: unexpected {extra}", errors(dict(record, **{extra: "x"}), score, self.schema))
        self.assertEqual(set(self.schema["$defs"]["score"]["properties"]), SCORE_FIELDS)
        self.assertIs(self.schema["$defs"]["score"]["additionalProperties"], False)

    def test_published_fields_carry_no_repository_name(self):
        for name, doc in self.valid.items():
            if name.startswith(("score", "board")):
                self.assertNotIn("/", json.dumps(doc), name)
                self.assertNotIn("synthetic-repo", json.dumps(doc), name)

    def test_the_numbers_are_written_for_a_reader_to_apply_by_hand(self):
        pin = json.loads(re.findall(r"^```json\n(.*?)^```$", self.contract, re.M | re.S)[0])
        self.assertEqual(pin["schema"], VERSION)
        self.assertEqual(self.schema["title"], VERSION)
        self.assertEqual(pin["sizes"], {"S": [0, S_MAX], "M": [S_MAX + 1, M_MAX], "L": [M_MAX + 1, None]})
        self.assertEqual(pin["weights"], WEIGHT)
        self.assertEqual(pin["daily_cap_points"], DAILY_CAP)
        self.assertEqual(pin["solo_repository_multiplier"], 0.5)
        for text in ("0 to 100 changed lines", "101 to 500", "501 or more", "12 points"):
            self.assertIn(text, self.contract)

    def test_size_bounds_and_cap_at_their_edges(self):
        base = self.valid["case-size-weights.json"]["input"]["pull_requests"][0]
        for lines, size in ((0, "S"), (100, "S"), (101, "M"), (500, "M"), (501, "L")):
            self.assertEqual(size_of(dict(base, additions=lines, deletions=0)), size, lines)
        self.assertEqual(size_of(dict(base, additions=60, deletions=41)), "M")
        case = json.loads(json.dumps(self.valid["case-daily-cap.json"]["input"]))
        self.assertEqual(score(case)["points"], DAILY_CAP)

    def test_fixtures_are_synthetic(self):
        handle = re.compile(r'"handle": "(?!synthetic-)')
        for path in HERE.rglob("*.json"):
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(handle.search(text), path.name)
            self.assertNotRegex(text, r'(?i)"repository": "(?!synthetic-owner/)', path.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
