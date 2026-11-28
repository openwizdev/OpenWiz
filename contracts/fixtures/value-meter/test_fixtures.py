#!/usr/bin/env python3
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[1]
CONTRACT = CONTRACTS / "value-meter.v1.md"
SCHEMA_PATH = CONTRACTS / "value-meter.v1.schema.json"
VALID = HERE / "valid"
INVALID = HERE / "invalid"
METRICS = ("merged_prs", "hours_saved", "money_saved_usd",
           "cost_per_merged_pr_credits", "cost_per_merged_pr_usd")
COST = {"cost_per_merged_pr_credits", "cost_per_merged_pr_usd"}
PRIVATE = re.compile(
    r"\bthr_(?!syn|web)|\b(?:proj|prj|mch|usr|acct|auto)_(?!syn|web)|"
    r"/(?:Users|home)/(?!runner|synthetic|example)|"
    r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net)|users\.noreply\.github\.com)")


def pairs(items):
    seen = {}
    for key, value in items:
        if key in seen:
            raise ValueError("repeated key " + key)
        seen[key] = value
    return seen


def load(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)


def resolve(schema, root):
    while isinstance(schema, dict) and "$ref" in schema:
        schema = root["$defs"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def type_ok(value, kind):
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return type(value) is bool
    if kind == "integer":
        return type(value) is int
    if kind == "null":
        return value is None
    if kind == "number":
        return type(value) in (int, float) and math.isfinite(value)
    return False


def errors(value, schema, root, at="$"):
    schema = resolve(schema, root)
    found = []
    if "allOf" in schema:
        for sub in schema["allOf"]:
            found += errors(value, sub, root, at)
    if "oneOf" in schema:
        reports = [(sub, errors(value, sub, root, at)) for sub in schema["oneOf"]]
        passed = [report for _, report in reports if not report]
        if len(passed) != 1:
            found.append(f"{at}: matches {len(passed)} of oneOf")
            kind = value.get("kind") if isinstance(value, dict) else None
            chosen = []
            for sub, report in reports:
                const = resolve(sub, root).get("properties", {}).get("kind", {}).get("const")
                if kind is not None and const == kind:
                    chosen = [report]
                    break
            if not chosen:
                typed = []
                for sub, report in reports:
                    spec = resolve(sub, root).get("type")
                    names = spec if isinstance(spec, list) else [spec] if spec else []
                    if names and any(type_ok(value, name) for name in names):
                        typed.append(report)
                chosen = typed or [report for _, report in reports]
            for report in chosen:
                found.extend(report)
    if "if" in schema:
        if not errors(value, schema["if"], root, at):
            if "then" in schema:
                found += errors(value, schema["then"], root, at)
        elif "else" in schema:
            found += errors(value, schema["else"], root, at)
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind] if kind else []
    if kinds and not any(type_ok(value, name) for name in kinds):
        found.append(f"{at}: not {' or '.join(kinds)}")
        return found
    if "const" in schema and value != schema["const"]:
        found.append(f"{at}: not {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{at}: not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            found.append(f"{at}: shorter than {schema.get('minLength')}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            found.append(f"{at}: does not match {schema['pattern']}")
    if type(value) in (int, float) and type(value) is not bool:
        if "exclusiveMinimum" in schema and not value > schema["exclusiveMinimum"]:
            found.append(f"{at}: not above {schema['exclusiveMinimum']}")
        if "minimum" in schema and value < schema["minimum"]:
            found.append(f"{at}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            found.append(f"{at}: above {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            found.append(f"{at}: fewer than {schema['minItems']} items")
        if schema.get("uniqueItems") and len({json.dumps(item, sort_keys=True) for item in value}) != len(value):
            found.append(f"{at}: repeated items")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            found += errors(item, item_schema, root, f"{at}[{index}]")
    if isinstance(value, dict):
        required = schema.get("required", [])
        found += [f"{at}: missing {key}" for key in required if key not in value]
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                found += errors(item, properties[key], root, f"{at}.{key}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{at}: unexpected {key}")
            elif isinstance(schema.get("additionalProperties"), dict):
                found += errors(item, schema["additionalProperties"], root, f"{at}.{key}")
    return found


def utc(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def windows_hold(doc):
    end = utc(doc["windows"]["end"])
    as_of = utc(doc["as_of"])
    this_week, last_week = doc["windows"]["this_week"], doc["windows"]["last_week"]
    return (doc["windows"]["timezone"] == "fixed-PST" and end <= as_of < end + timedelta(days=1)
            and utc(this_week["start"]) == end - timedelta(days=7) and utc(this_week["end"]) == end
            and utc(last_week["start"]) == end - timedelta(days=14)
            and utc(last_week["end"]) == end - timedelta(days=7))


def direction_holds(delta):
    if delta["state"] == "unknown":
        return delta["value"] is None and delta["direction"] == "unknown" and delta["reason"]
    if delta["state"] not in ("known", "partial") or not isinstance(delta["value"], (int, float)):
        return False
    want = "up" if delta["value"] > 0 else "down" if delta["value"] < 0 else "flat"
    return delta["direction"] == want


def coverage(metric, at, cost):
    found = []
    known, total = metric["known_count"], metric["total_count"]
    if known > total:
        found.append(f"{at}: known_count above total_count")
    if cost and metric["state"] == "known" and known != total:
        found.append(f"{at}: known cost must cover every pull request")
    if cost and metric["state"] == "partial" and not 0 < known < total:
        found.append(f"{at}: partial cost must be a strict subset")
    return found


def measured(value):
    return type(value) in (int, float)


def normalize_repos(repos):
    seen, out = set(), []
    for repo in repos:
        key = repo.lower()
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def deduplicate_records(records):
    seen, out = set(), []
    for record in records:
        repo = record["repository"].lower()
        key = (repo, record["pull_request"])
        if key not in seen:
            seen.add(key)
            out.append(dict(record, repository=repo))
    return out


def collection_complete(doc):
    reads = doc.get("reads") or []
    return bool(reads) and all(read.get("status") == "complete" for read in reads)


def expected_delta_state(this, last):
    states = (this["state"], last["state"])
    if "unknown" in states:
        return "unknown"
    if "partial" in states:
        return "partial"
    return "known"


def delta_rules(this, last, delta, at):
    found = []
    numeric = sum(measured(row["value"]) for row in (this, last))
    want_state = expected_delta_state(this, last)
    if delta["state"] != want_state:
        found.append(f"{at}: state {delta['state']!r} does not match expected {want_state!r}")
    if delta["total_count"] != 2:
        found.append(f"{at}: total_count is not 2")
    if delta["known_count"] > delta["total_count"]:
        found.append(f"{at}: known_count above total_count")
    if delta["known_count"] != numeric:
        found.append(f"{at}: known_count is not the numeric weeks")
    if numeric == 2 and measured(delta["value"]) and not math.isclose(delta["value"], this["value"] - last["value"]):
        found.append(f"{at}: value is not this week minus last week")
    if delta["state"] in ("known", "partial") and delta["known_count"] != 2:
        found.append(f"{at}: a numeric delta counts both weeks")
    if not direction_holds(delta):
        found.append(f"{at}: direction does not match the value")
    return found


def outside(doc):
    kind = doc.get("kind")
    if kind == "config":
        seen, found = set(), []
        for index, repo in enumerate(doc.get("repos", [])):
            key = repo.lower()
            if key in seen:
                found.append(f"$.repos[{index}]: duplicate repository {key}")
            seen.add(key)
        return found
    if kind == "collection":
        found, read_repos, seen_prs = [], set(), set()
        for index, read in enumerate(doc.get("reads", [])):
            key = read["repository"].lower()
            if key in read_repos:
                found.append(f"$.reads[{index}]: duplicate repository {key}")
            read_repos.add(key)
        for index, record in enumerate(doc.get("records", [])):
            repo = record["repository"].lower()
            if repo not in read_repos:
                found.append(f"$.records[{index}]: repository {repo} not in reads")
            pair = (repo, record["pull_request"])
            if pair in seen_prs:
                found.append(f"$.records[{index}]: duplicate pull request {repo}#{record['pull_request']}")
            seen_prs.add(pair)
        return found
    if kind not in ("report", "aggregate"):
        return []
    found = []
    try:
        aligned = windows_hold(doc)
    except (KeyError, ValueError):
        aligned = False
    if not aligned:
        found.append("$.windows: not the fixed-PST pair")
    for side, metrics in doc["metrics"].items():
        for name, metric in metrics.items():
            found += coverage(metric, f"$.metrics.{side}.{name}", name in COST)
    for name, delta in doc["week_over_week"].items():
        found += delta_rules(doc["metrics"]["this_week"][name], doc["metrics"]["last_week"][name],
                             delta, f"$.week_over_week.{name}")
    return found


def pin_of(text):
    blocks = re.findall(r"^```json\n(.*?)^```$", text, re.M | re.S)
    return json.loads(blocks[0], object_pairs_hook=pairs)


class Proof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load(SCHEMA_PATH)
        cls.contract = CONTRACT.read_text(encoding="utf-8")
        cls.pin = pin_of(cls.contract)
        cls.valid = {path.name: load(path) for path in sorted(VALID.glob("*.json"))}
        cls.invalid = {path.name: load(path) for path in sorted(INVALID.glob("*.json"))
                       if path.name not in ("expect.json", "repeated-key.json")}
        cls.expect = load(INVALID / "expect.json")

    def validate(self, document):
        return errors(document, self.schema, self.schema)

    def test_valid_fixtures_match_the_schema(self):
        self.assertGreaterEqual(set(self.valid), {
            "config-opted-in.json", "config-opted-out.json", "config-enabled-no-repos.json",
            "pr-record-known.json", "pr-record-unknown.json", "collection-complete.json",
            "collection-empty.json", "report-opted-in.json", "report-opted-out.json",
            "report-partial.json", "report-zero-merges.json", "report-unconfigured-repos.json",
            "aggregate.json", "aggregate-partial.json"})
        for name, document in self.valid.items():
            self.assertEqual(self.validate(document), [], name)

    def test_invalid_fixtures_fail_with_the_named_error(self):
        self.assertEqual(set(self.expect), set(self.invalid))
        for name, document in self.invalid.items():
            found = self.validate(document)
            self.assertNotEqual(found, [], name)
            self.assertIn(self.expect[name], "\n".join(found), name)

    def test_windows_and_honesty_rules_hold_on_the_valid_reports(self):
        for name in ("report-opted-in.json", "report-opted-out.json", "report-partial.json",
                     "report-zero-merges.json", "report-unconfigured-repos.json",
                     "aggregate.json", "aggregate-partial.json"):
            self.assertTrue(windows_hold(self.valid[name]), name)
            for side in ("this_week", "last_week"):
                for metric, value in self.valid[name]["metrics"][side].items():
                    self.assertLessEqual(value["known_count"], value["total_count"], f"{name} {metric}")
                    if value["state"] == "unknown":
                        self.assertIsNone(value["value"], f"{name} {side} {metric}")
                        self.assertTrue(value["reason"], f"{name} {side} {metric}")
                    if metric in COST and value["state"] == "partial":
                        self.assertLess(value["known_count"], value["total_count"], f"{name} {metric}")
                    if metric not in COST:
                        self.assertNotEqual(value["state"], "partial", f"{name} {metric}")
            for metric, delta in self.valid[name]["week_over_week"].items():
                self.assertTrue(direction_holds(delta), f"{name} {metric}")
        zero = self.valid["report-zero-merges.json"]["metrics"]["this_week"]
        self.assertEqual((zero["merged_prs"]["state"], zero["merged_prs"]["value"]), ("known", 0))
        for metric in COST:
            self.assertEqual(zero[metric]["state"], "unknown")
            self.assertIsNone(zero[metric]["value"])
        unconfigured = self.valid["report-unconfigured-repos.json"]
        self.assertIs(unconfigured["opted_in"], True)
        for side in unconfigured["metrics"].values():
            for value in side.values():
                self.assertEqual(value["state"], "unknown")
                self.assertIsNone(value["value"])
        for delta in unconfigured["week_over_week"].values():
            self.assertEqual(delta["state"], "unknown")
            self.assertIsNone(delta["value"])
        partial = self.valid["report-partial.json"]["metrics"]["this_week"]
        self.assertEqual(partial["hours_saved"]["state"], "unknown")
        self.assertEqual(partial["cost_per_merged_pr_credits"]["state"], "partial")
        self.assertLess(partial["cost_per_merged_pr_credits"]["known_count"],
                        partial["cost_per_merged_pr_credits"]["total_count"])
        opted_out = self.valid["report-opted-out.json"]
        self.assertIs(opted_out["opted_in"], False)
        for side in opted_out["metrics"].values():
            for value in side.values():
                self.assertEqual(value["state"], "unknown")
                self.assertIsNone(value["value"])

    def test_the_aggregate_carries_no_repository_or_private_token(self):
        for name in ("aggregate.json", "aggregate-partial.json"):
            text = json.dumps(self.valid[name])
            self.assertNotIn("repository", text, name)
            self.assertNotIn("synthetic-owner", text, name)
            self.assertIsNone(PRIVATE.search(text), name)
            self.assertNotIn("/", text, name)
        for path_fn in (
            lambda d: d["metrics"]["this_week"]["cost_per_merged_pr_usd"].__setitem__(
                "reason", "failed reading synthetic-owner/synthetic-repo"),
            lambda d: d["metrics"]["this_week"]["money_saved_usd"].__setitem__(
                "net_reason", "failed reading synthetic-owner/synthetic-repo"),
            lambda d: d["metrics"]["this_week"]["cost_per_merged_pr_credits"].__setitem__(
                "reason", "2 of 4 merged pull requests had a known credit cost"),
            lambda d: d["metrics"]["this_week"]["hours_saved"].__setitem__(
                "reason", "hours_per_merged_pr is not configured"),
            lambda d: d["week_over_week"]["cost_per_merged_pr_usd"].__setitem__(
                "reason", "synthetic-owner/synthetic-repo was incomplete"),
        ):
            agg = json.loads(json.dumps(self.valid["aggregate-partial.json"]))
            path_fn(agg)
            self.assertNotEqual(self.validate(agg), [], agg)

    def test_the_contract_pins_the_seam_and_the_schema_name(self):
        self.assertEqual(self.pin["schema"], "openwiz.value-meter.v1")
        self.assertEqual(self.schema["title"], "openwiz.value-meter.v1")
        self.assertIn("render_section(report) -> str", self.contract)
        self.assertIn('<section class="value-meter">', self.contract)
        self.assertEqual(self.pin["defaults"]["enabled"], False)
        self.assertEqual(self.pin["defaults"]["share_aggregates"], False)
        self.assertEqual(self.pin["windows"]["boundary_utc"], "08:00:00Z")
        self.assertEqual(self.pin["aggregate_reasons"], self.schema["$defs"]["aggregate_reason"]["enum"])
        self.assertNotIn("case-sensitively", self.contract)

    def test_empty_source_list_is_unconfigured_and_case_variants_deduplicate(self):
        self.assertFalse(collection_complete(self.valid["collection-empty.json"]))
        zero_collection = {
            "schema": "openwiz.value-meter.v1",
            "kind": "collection",
            "reads": [{"repository": "synthetic-owner/synthetic-repo", "status": "complete", "reason": None}],
            "records": [],
        }
        self.assertEqual(self.validate(zero_collection), [])
        self.assertEqual(outside(zero_collection), [])
        self.assertTrue(collection_complete(zero_collection))
        partial_reads = json.loads(json.dumps(zero_collection))
        partial_reads["reads"].append({"repository": "synthetic-owner/other-repo",
                                       "status": "incomplete", "reason": "rate limited"})
        self.assertFalse(collection_complete(partial_reads))
        lower_dup_config = json.loads(json.dumps(self.valid["config-opted-in.json"]))
        lower_dup_config["repos"].append("synthetic-owner/synthetic-repo")
        self.assertIn("repeated items", "\n".join(self.validate(lower_dup_config)))
        self.assertIn("duplicate repository", "\n".join(outside(lower_dup_config)))
        orphan = json.loads(json.dumps(self.valid["collection-complete.json"]))
        orphan["reads"] = []
        self.assertIn("not in reads", "\n".join(outside(orphan)))
        dup_config = self.invalid["config-duplicate-repo-case.json"]
        self.assertIn("duplicate repository", "\n".join(outside(dup_config)))
        dup_collection = self.invalid["collection-duplicate-pr-case.json"]
        dup_errors = "\n".join(outside(dup_collection))
        self.assertIn("duplicate repository", dup_errors)
        self.assertIn("duplicate pull request", dup_errors)
        lower_dup_reads = json.loads(json.dumps(self.valid["collection-complete.json"]))
        lower_dup_reads["reads"].append({"repository": "synthetic-owner/synthetic-repo",
                                         "status": "incomplete", "reason": "rate limited"})
        self.assertIn("duplicate repository", "\n".join(outside(lower_dup_reads)))
        lower_dup_pr = json.loads(json.dumps(self.valid["collection-complete.json"]))
        second = json.loads(json.dumps(lower_dup_pr["records"][0]))
        second["cost_credits"] = 25
        lower_dup_pr["records"].append(second)
        self.assertIn("duplicate pull request", "\n".join(outside(lower_dup_pr)))
        normalized = normalize_repos(["Synthetic-Owner/Synthetic-Repo", "synthetic-owner/synthetic-repo"])
        self.assertEqual(normalized, ["synthetic-owner/synthetic-repo"])
        deduped = deduplicate_records(dup_collection["records"])
        self.assertEqual(len(deduped), 1)
        self.assertEqual((deduped[0]["repository"], deduped[0]["pull_request"]),
                         ("synthetic-owner/synthetic-repo", 7))

    def test_a_non_finite_rate_and_a_repeated_key_are_refused(self):
        config = dict(self.valid["config-opted-in.json"])
        config["hours_per_merged_pr"] = float("nan")
        self.assertNotEqual(self.validate(config), [])
        config["hourly_rate_usd"] = float("inf")
        self.assertNotEqual(self.validate(config), [])
        raw = (INVALID / "repeated-key.json").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            json.loads(raw, object_pairs_hook=pairs)

    def test_rules_the_schema_cannot_see(self):
        for name, document in self.valid.items():
            self.assertEqual(outside(document), [], name)
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["metrics"]["this_week"]["money_saved_usd"]["net_of_known_cost_usd"] = -12.5
        self.assertEqual(self.validate(report), [], "a negative net is a measured loss")
        self.assertEqual(outside(report), [])
        report["metrics"]["this_week"]["merged_prs"]["value"] = 4.5
        self.assertIn("not integer", "\n".join(self.validate(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["metrics"]["this_week"]["hours_saved"]["value"] = -1
        self.assertIn("below 0", "\n".join(self.validate(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["metrics"]["this_week"]["merged_prs"]["known_count"] = 5
        report["metrics"]["this_week"]["merged_prs"]["total_count"] = 1
        self.assertEqual(self.validate(report), [])
        self.assertIn("known_count above total_count", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["metrics"]["this_week"]["cost_per_merged_pr_credits"]["known_count"] = 1
        self.assertEqual(self.validate(report), [])
        self.assertIn("known cost must cover every pull request", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["week_over_week"]["merged_prs"]["direction"] = "down"
        self.assertEqual(self.validate(report), [])
        self.assertIn("direction does not match the value", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["windows"]["this_week"]["start"] = "2030-01-09T08:00:00Z"
        self.assertEqual(self.validate(report), [])
        self.assertIn("not the fixed-PST pair", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["week_over_week"]["merged_prs"]["total_count"] = 1
        self.assertEqual(self.validate(report), [])
        self.assertIn("total_count is not 2", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-partial.json"]))
        self.assertEqual(report["week_over_week"]["cost_per_merged_pr_usd"]["known_count"], 1)
        report["week_over_week"]["cost_per_merged_pr_usd"]["known_count"] = 0
        self.assertIn("known_count is not the numeric weeks", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-partial.json"]))
        report["week_over_week"]["cost_per_merged_pr_credits"]["state"] = "known"
        report["week_over_week"]["cost_per_merged_pr_credits"]["reason"] = None
        self.assertEqual(self.validate(report), [])
        self.assertIn("state 'known' does not match expected 'partial'", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["week_over_week"]["merged_prs"] = {
            "state": "unknown", "value": None, "direction": "unknown",
            "known_count": 2, "total_count": 2, "reason": "forced unknown",
        }
        self.assertEqual(self.validate(report), [])
        self.assertIn("state 'unknown' does not match expected 'known'", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-opted-in.json"]))
        report["metrics"]["this_week"]["cost_per_merged_pr_credits"]["state"] = "partial"
        report["metrics"]["this_week"]["cost_per_merged_pr_credits"]["known_count"] = 2
        report["metrics"]["this_week"]["cost_per_merged_pr_credits"]["reason"] = "2 of 4 known"
        self.assertEqual(self.validate(report), [])
        self.assertIn("state 'known' does not match expected 'partial'", "\n".join(outside(report)))
        report = json.loads(json.dumps(self.valid["report-partial.json"]))
        report["week_over_week"]["cost_per_merged_pr_usd"]["state"] = "partial"
        report["week_over_week"]["cost_per_merged_pr_usd"]["value"] = 0
        report["week_over_week"]["cost_per_merged_pr_usd"]["direction"] = "flat"
        self.assertIn("state 'partial' does not match expected 'unknown'", "\n".join(outside(report)))

    def test_fixtures_use_synthetic_identifiers_only(self):
        blobs = [self.contract, SCHEMA_PATH.read_text(encoding="utf-8")]
        blobs += [path.read_text(encoding="utf-8") for path in HERE.rglob("*.json")]
        for blob in blobs:
            self.assertIsNone(PRIVATE.search(blob), blob[:80])


def demo():
    schema = load(SCHEMA_PATH)
    print("schema openwiz.value-meter.v1")
    failed = 0
    for path in sorted(VALID.glob("*.json")):
        found = errors(load(path), schema, schema)
        print(f"valid {path.name}: {'ok' if not found else found[0]}")
        failed += bool(found)
    expect = load(INVALID / "expect.json")
    for path in sorted(INVALID.glob("*.json")):
        if path.name == "expect.json":
            continue
        if path.name == "repeated-key.json":
            try:
                load(path)
            except ValueError as error:
                print(f"invalid {path.name}: {error}")
                continue
            print(f"invalid {path.name}: repeated key was accepted")
            failed += 1
            continue
        found = errors(load(path), schema, schema)
        text = "\n".join(found)
        shown = next((line for line in found if "matches" not in line), found[0] if found else "accepted")
        print(f"invalid {path.name}: {shown}")
        failed += not found or expect[path.name] not in text
    return failed


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        sys.exit(demo())
    unittest.main(verbosity=2)
