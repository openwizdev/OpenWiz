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
DOC = CONTRACTS / "feed.v1.md"
SCHEMA = CONTRACTS / "feed.v1.schema.json"
SETTINGS_DOC = CONTRACTS / "settings.v1.md"
VALID, INVALID = HERE / "valid", HERE / "invalid"
COMMENTS_VALID, COMMENTS_INVALID = HERE / "comments" / "valid", HERE / "comments" / "invalid"
RESOLUTION = HERE / "resolution" / "cases.json"
PING = HERE / "ping"

KINDS = (
    "spec-to-approve",
    "pr-ready-to-merge",
    "release",
    "key-needed",
    "setting-proposal",
    "blocker",
    "quota-switch",
    "driver-suggestion",
)
NEEDS_OWNER_KINDS = ("spec-to-approve", "pr-ready-to-merge", "release", "key-needed", "setting-proposal")
SCROLL_ONLY_KINDS = ("quota-switch", "driver-suggestion")
ID_PREFIX = {
    "spec-to-approve": "spec",
    "pr-ready-to-merge": "pr",
    "release": "release",
    "key-needed": "key",
    "setting-proposal": "setting",
    "blocker": "blocker",
    "quota-switch": "quota",
    "driver-suggestion": "driver",
}
COMMENT_FORMS = {
    "openwiz:setting-proposal v1": ("setting_proposal_comment", ("path", "current", "proposed", "reason", "role")),
    "openwiz:key-needed v1": ("key_needed_comment", ("key",)),
    "openwiz:quota-switch v1": ("quota_switch_comment", ("role", "from", "to", "resets_at")),
    "openwiz:driver-suggestion v1": ("driver_suggestion_comment", ("driver", "reason", "listing")),
}
ROLES = {"orchestrator", "builder", "fixer", "reviewer", "small_builder"}
HOME_HOST_ROLES = {"orchestrator", "builder", "reviewer"}
LABEL_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
HOST_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
REPO_RE = re.compile(r"^[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}/[A-Za-z0-9._-]{1,100}$")
LANE_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*:[A-Za-z0-9._-]+:[A-Za-z0-9_-]{1,32}$")
REAL_PRIVATE = re.compile(
    r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net|invalid)\b|users\.noreply\.github\.com\b)[A-Za-z0-9-]+\.[A-Za-z]{2,}"
    r"|/(?:Users|home)/(?!example|synthetic)"
    r"|\bthr_(?!syn|web)"
    r"|\b(?:proj|prj|mch|usr|acct|auto|cr)_(?!syn|web)"
    r"|\b(?:sk-(?!syn-)|gh[pousr]_|github_pat_|xox[abprs]-|AKIA|AIza|eyJ)[A-Za-z0-9_-]{8}"
    r"|-----BEGIN"
)


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
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "boolean": type(value) is bool,
        "integer": type(value) is int,
        "null": value is None,
        "number": type(value) in (int, float) and math.isfinite(value),
    }[kind]


def errors(value, schema, root, at="$"):
    known = {
        "$schema", "$id", "$ref", "$defs", "title", "description", "allOf", "oneOf", "not", "if",
        "then", "else", "type", "const", "enum", "pattern", "minLength", "maxLength", "minimum",
        "maximum", "exclusiveMinimum", "minItems", "maxItems", "uniqueItems", "items", "required",
        "properties", "additionalProperties", "propertyNames",
    }
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


def rule_errors(doc):
    found = []
    if doc["budget"]["used"] > doc["budget"]["allowed"]:
        found.append("$.budget.used: exceeds budget.allowed")
    seen_ids = set()
    read_at = doc["read_at"]
    for index, card in enumerate(doc["cards"]):
        at = f"$.cards[{index}]"
        card_id = card["id"]
        if card_id in seen_ids:
            found.append(f"{at}.id: duplicate card id {card_id!r}")
        seen_ids.add(card_id)
        rec = card["record"]
        repo, number, comment_id = rec["repository"], rec["number"], rec["comment_id"]
        prefix = ID_PREFIX[card["kind"]]
        if card["kind"] == "pr-ready-to-merge":
            if not card_id.startswith(f"pr:{repo}#{number}@"):
                found.append(f"{at}.id: does not match record {repo}#{number}")
            expected_links = {f"https://github.com/{repo}/pull/{number}"}
        elif comment_id is None:
            if card_id != f"{prefix}:{repo}#{number}":
                found.append(f"{at}.id: does not match record {repo}#{number}")
            expected_links = {f"https://github.com/{repo}/issues/{number}"}
        else:
            if card_id != f"{prefix}:{repo}#{number}:{comment_id}":
                found.append(f"{at}.id: does not match record {repo}#{number}:{comment_id}")
            expected_links = {
                f"https://github.com/{repo}/issues/{number}#issuecomment-{comment_id}",
                f"https://github.com/{repo}/pull/{number}#issuecomment-{comment_id}",
            }
        if card["link"] not in expected_links:
            found.append(f"{at}.link: does not match record")
        if card["since"] > read_at:
            found.append(f"{at}.since: after read_at")
        if card["resolved_at"] is not None:
            if card["resolved_at"] < card["since"]:
                found.append(f"{at}.resolved_at: before since")
            if card["resolved_at"] > read_at:
                found.append(f"{at}.resolved_at: after read_at")
    return found


def refusals(doc, schema):
    found = errors(doc, schema, schema)
    return found or rule_errors(doc)


def is_host(name):
    return len(name) <= 40 and HOST_RE.fullmatch(name) is not None


def settings_path_ok(path):
    if path == "telemetry":
        return True
    if path.startswith("hosts.projects."):
        return REPO_RE.fullmatch(path[len("hosts.projects."):]) is not None
    if path.startswith("budgets."):
        rest = path[len("budgets."):]
        for suffix in (".amount", ".unit", ".by"):
            if rest.endswith(suffix):
                rest = rest[:-len(suffix)]
                break
        return len(rest) <= 120 and LANE_RE.fullmatch(rest) is not None
    parts = path.split(".")
    if parts[0] == "roles" and len(parts) in (2, 3) and parts[1] in ROLES:
        return len(parts) == 2 or parts[2] in {"harness", "model", "effort", "account", "fallback"}
    if parts[0] == "accounts" and len(parts) in (3, 4) and LABEL_RE.fullmatch(parts[1]):
        if len(parts) == 3:
            return parts[2] in {"harness", "host", "reserved", "profile"}
        return parts[2] == "profile" and parts[3] in {"variable", "folder"}
    if parts[0] == "hosts":
        if len(parts) == 2:
            return parts[1] in {"overflow", "max_agents"}
        if len(parts) == 3 and parts[1] == "home" and parts[2] in HOME_HOST_ROLES:
            return True
        if parts == ["hosts", "overflow", "host"]:
            return True
    if parts[0] == "drivers" and len(parts) == 2:
        return is_host(parts[1])
    if parts[0] == "keys" and len(parts) == 3 and LABEL_RE.fullmatch(parts[1]):
        return parts[2] in {"store", "entry", "on"}
    if parts[0] == "channels" and len(parts) == 2:
        return parts[1] != "t3" and is_host(parts[1])
    return False


def parse_comment(text, schema):
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        return None, ["unknown_marker: empty comment"]
    marker = lines[0]
    if marker not in COMMENT_FORMS:
        return None, [f"unknown_marker: {marker!r}"]
    def_name, expected_keys = COMMENT_FORMS[marker]
    keys, parsed = [], {}
    for line in lines[1:]:
        if ": " not in line:
            return None, [f"fields_exact: malformed line {line!r}"]
        key, value = line.split(": ", 1)
        keys.append(key)
        parsed[key] = value
    if tuple(keys) != expected_keys:
        return None, [f"fields_exact: got {tuple(keys)}, expected {expected_keys}"]
    found = errors(parsed, {"$ref": f"#/$defs/{def_name}"}, schema, "$")
    if def_name == "setting_proposal_comment":
        if not settings_path_ok(parsed["path"]):
            found.append(f"settings_path: {parsed['path']!r} is not a writable settings.v1 path")
        if parsed["current"] == parsed["proposed"]:
            found.append("proposal_differs: proposed equals current")
    if def_name == "quota_switch_comment" and parsed["from"] == parsed["to"]:
        found.append("switch_differs: to equals from")
    return parsed, found


def resolve_card(card, event, read_at):
    kind = card["kind"]
    etype = event["type"]
    resolved_at = None
    if etype == "issue_closed":
        resolved_at = event["at"]
    elif kind == "spec-to-approve":
        if (etype == "owner_decision" and event.get("author_is_owner")
                and event.get("after_comment_id") == card["record"]["comment_id"]):
            resolved_at = event["at"]
    elif kind == "pr-ready-to-merge":
        if etype in {"pr_merged", "pr_closed", "head_moved", "required_check_failed", "standing_grant_added"}:
            resolved_at = event["at"]
    elif kind == "release":
        if (etype == "owner_ship_decision" and event.get("author_is_owner")) or etype == "tag_published":
            resolved_at = event["at"]
    elif kind == "key-needed":
        if (etype == "settings_key_set" and event.get("set_at") is not None
                and event["set_at"] >= card["since"]):
            resolved_at = event["set_at"]
    elif kind == "setting-proposal":
        if etype == "proposal_answered" and event.get("by_owner_or_wiz"):
            resolved_at = event["at"]
    elif kind == "blocker":
        reasons = event.get("blocker_close_reasons", [])
        if (etype == "blockers_updated" and event.get("owner_wait_cleared")
                and all(reason == "COMPLETED" for reason in reasons)):
            resolved_at = event["at"]
    elif kind == "quota-switch":
        if etype == "clock" and read_at >= event["resets_at"]:
            resolved_at = event["resets_at"]
    elif kind == "driver-suggestion":
        if ((etype == "settings_driver" and event.get("enabled") is True)
                or (etype == "owner_dismissed" and event.get("author_is_owner"))):
            resolved_at = event["at"]
    if resolved_at is None:
        return dict(card)
    return {**card, "needs_owner": False, "resolved_at": resolved_at}


def needs_you(cards):
    return [card for card in cards if card["needs_owner"] and card["resolved_at"] is None]


def select_pings(cards, ledger, at):
    emitted = []
    updated = {"schema": ledger["schema"], "pinged": dict(ledger["pinged"])}
    for card in needs_you(cards):
        if card["id"] not in updated["pinged"]:
            emitted.append(card["id"])
            updated["pinged"][card["id"]] = at
    return emitted, updated


def markdown_table(text, heading):
    section = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if section is None:
        return []
    rows = [line for line in section[1].splitlines() if line.startswith("| `")]
    return [[cell.strip() for cell in row.strip("|").split("|")] for row in rows]


def root_property_names(schema):
    names = set(schema.get("properties", {}))
    for def_name in ("budget", "card", "record", "unavailable_source"):
        if def_name in schema.get("$defs", {}):
            names |= set(schema["$defs"][def_name].get("properties", {}))
    return names


class FeedContract(unittest.TestCase):
    def setUp(self):
        self.assertTrue(DOC.is_file(), "feed.v1.md is missing")
        self.assertTrue(SCHEMA.is_file(), "feed.v1.schema.json is missing")
        self.schema, self.text = load(SCHEMA), DOC.read_text(encoding="utf-8")

    def test_every_valid_feed_fixture_is_accepted(self):
        names = sorted(VALID.glob("*.json"))
        self.assertGreaterEqual(len(names), len(KINDS) + 3)
        seen_kinds = set()
        for path in names:
            with self.subTest(path.name):
                doc = load(path)
                self.assertEqual(refusals(doc, self.schema), [])
                seen_kinds |= {card["kind"] for card in doc["cards"]}
        self.assertEqual(seen_kinds, set(KINDS))

    def test_every_invalid_feed_fixture_is_refused_for_its_rule(self):
        expect = load(INVALID / "expect.json")
        self.assertEqual(
            sorted(expect),
            sorted(p.name for p in INVALID.glob("*.json") if p.name != "expect.json"),
        )
        for name, case in expect.items():
            with self.subTest(name):
                doc = load(INVALID / name)
                found = errors(doc, self.schema, self.schema)
                if case["by"] == "rule":
                    self.assertEqual(found, [], "the schema alone accepts a cross-field case")
                    found = rule_errors(doc)
                self.assertTrue(any(line.startswith(case["at"]) for line in found), found)
                self.assertIn(f"`{name}`", self.text, "the contract names each invalid fixture")

    def test_each_invalid_feed_fixture_changes_one_top_level_field(self):
        for name, case in load(INVALID / "expect.json").items():
            with self.subTest(name):
                base, doc = load(VALID / case["from"]), load(INVALID / name)
                changed = [k for k in set(base) | set(doc) if base.get(k) != doc.get(k)]
                self.assertEqual(len(changed), 1, changed)

    def test_blocker_distinguishes_owner_waiting_from_scroll_only(self):
        owner_doc = load(VALID / "blocker-needs-owner.json")
        scroll_doc = load(VALID / "blocker-scroll-only.json")
        self.assertEqual(refusals(owner_doc, self.schema), [])
        self.assertEqual(refusals(scroll_doc, self.schema), [])
        self.assertTrue(all(c["kind"] == "blocker" and c["needs_owner"] for c in owner_doc["cards"]))
        self.assertEqual(len(needs_you(owner_doc["cards"])), len(owner_doc["cards"]))
        self.assertTrue(all(c["kind"] == "blocker" and not c["needs_owner"] for c in scroll_doc["cards"]))
        self.assertEqual(needs_you(scroll_doc["cards"]), [])

    def test_valid_and_invalid_comment_forms(self):
        valid_files = sorted(COMMENTS_VALID.glob("*.txt"))
        self.assertEqual(len(valid_files), len(COMMENT_FORMS))
        seen_markers = set()
        for path in valid_files:
            with self.subTest(path.name):
                raw = path.read_text(encoding="utf-8")
                parsed, found = parse_comment(raw, self.schema)
                self.assertEqual(found, [], found)
                self.assertIsNotNone(parsed)
                seen_markers.add(raw.splitlines()[0])
        self.assertEqual(seen_markers, set(COMMENT_FORMS))

        expect = load(COMMENTS_INVALID / "expect.json")
        self.assertEqual(sorted(expect), sorted(p.name for p in COMMENTS_INVALID.glob("*.txt")))
        rule_markers = {
            "settings_path": ("settings_path:",),
            "proposal_differs": ("proposal_differs:",),
            "privacy_email": ("$.reason: matches a refused form",),
            "fields_exact": ("fields_exact:",),
            "privacy_key": ("$.key: matches a refused form",),
            "privacy_account_id": ("$.to: matches a refused form",),
            "utc_time": ("$.resets_at: does not match",),
            "switch_differs": ("switch_differs:",),
            "suggestion_reason": ("$.reason: not in",),
            "listing_url": ("$.listing: does not match",),
            "unknown_marker": ("unknown_marker:",),
        }
        for name, case in expect.items():
            with self.subTest(name):
                _, found = parse_comment((COMMENTS_INVALID / name).read_text(encoding="utf-8"), self.schema)
                self.assertTrue(found, f"{name} should be refused")
                prefixes = rule_markers[case["rule"]]
                self.assertTrue(any(line.startswith(prefixes) for line in found), (name, case["rule"], found))
                self.assertIn(f"`{name}`", self.text, "the contract names each invalid comment fixture")
        self.assertEqual({case["form"] for case in expect.values()} - {"unknown"},
                         {"setting-proposal", "key-needed", "quota-switch", "driver-suggestion"})
        for good_path in ("roles.builder", "roles.builder.effort", "accounts.work.profile.folder",
                          "hosts.home.builder", "hosts.overflow.host", "hosts.max_agents",
                          "hosts.projects.syn-owner/syn-app", "drivers.boat",
                          "budgets.local:claude:work.amount", "keys.devin.on", "channels.slack", "telemetry"):
            self.assertTrue(settings_path_ok(good_path), good_path)
        for bad_path in ("schema", "channels.t3", "updates", "version", "changed_at", "changed_by",
                         "history", "hosts.overflow.serves", "keys.devin.value", "keys.devin.set_at",
                         "keys.devin.opt_in", "unknown.section"):
            self.assertFalse(settings_path_ok(bad_path), bad_path)

    def test_resolution_transitions_cover_every_kind_and_leave_needs_you(self):
        cases = load(RESOLUTION)
        resolved_kinds, unresolved_kinds = set(), set()
        for case in cases:
            with self.subTest(case["name"]):
                after = resolve_card(case["before"], case["event"], case["read_at"])
                wrapped = {
                    "schema": "openwiz.feed.v1",
                    "read_at": case["read_at"],
                    "budget": {"used": 2, "allowed": 60},
                    "cards": [after],
                    "unavailable": [],
                }
                self.assertEqual(refusals(wrapped, self.schema), [])
                if case["expect_resolved"]:
                    self.assertIsNotNone(after["resolved_at"])
                    self.assertFalse(after["needs_owner"])
                    self.assertEqual(needs_you([after]), [])
                    resolved_kinds.add(case["kind"])
                else:
                    self.assertIsNone(after["resolved_at"])
                    self.assertEqual(after["needs_owner"], case["before"]["needs_owner"])
                    unresolved_kinds.add(case["kind"])
        self.assertEqual(resolved_kinds, set(KINDS))
        self.assertEqual(unresolved_kinds, set(KINDS))

    def test_one_ping_rule_and_ledger_shape(self):
        ledger_schema = {"$ref": "#/$defs/ping_ledger"}
        self.assertEqual(errors(load(PING / "valid-ledger.json"), ledger_schema, self.schema), [])
        self.assertTrue(errors(load(PING / "invalid-ledger-extra-field.json"), ledger_schema, self.schema))
        self.assertTrue(errors(load(PING / "invalid-ledger-bad-id.json"), ledger_schema, self.schema))
        suite = load(PING / "cases.json")
        ledger = suite["initial_ledger"]
        self.assertEqual(errors(ledger, ledger_schema, self.schema), [])
        for run in suite["runs"]:
            with self.subTest(run["name"]):
                emitted, ledger = select_pings(run["cards"], ledger, run["at"])
                self.assertEqual(emitted, run["expect_pings"])
                self.assertEqual(errors(ledger, ledger_schema, self.schema), [])

    def test_privacy_refuses_key_email_and_account_id_shapes(self):
        def walk_strings(node, at="#"):
            if isinstance(node, dict):
                if node.get("type") == "string" and "const" not in node and "enum" not in node:
                    yield at, node
                for key, value in node.items():
                    if key != "not":
                        yield from walk_strings(value, f"{at}/{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    yield from walk_strings(value, f"{at}/{index}")

        guards = ({"$ref": "#/$defs/no_private"}, {"$ref": "#/$defs/no_private_id"})
        for at, node in walk_strings(self.schema):
            if at.endswith("/resolved_at"):
                continue
            with self.subTest(schema_string=at):
                self.assertTrue(any(guard in node.get("allOf", []) for guard in guards), at)
        no_private = {"$ref": "#/$defs/no_private"}
        for bad in (
            "sk-syn-0000000000000000",
            "ghp_" + "0" * 36,
            "syn-key-" + "0" * 40,
            "-----BEGIN SYN KEY-----",
            "eyJzeW4iOiJzeW4ifQ.syn",
            "alice@example.com",
            "acct_syn_example01",
            "usr_syn_example01",
            "thr_syn_example01",
            "/Users/example/home",
        ):
            with self.subTest(bad=bad):
                self.assertTrue(errors(bad, no_private, self.schema), bad)
        for good in (
            "0.2.0 spec: synthetic widget queue",
            "Two builds stalled on medium effort and passed on high.",
            "syn-owner/syn-app:pulls",
            "https://openwiz.dev/market/drivers/boat",
            "codex:vendor/demo:medium:codex-work",
        ):
            with self.subTest(good=good):
                self.assertEqual(errors(good, no_private, self.schema), [], good)

    def test_the_contract_documents_all_fields_kinds_forms_and_rules(self):
        field_rows = markdown_table(self.text, "Fields")
        self.assertTrue(field_rows, "the Fields table is missing")
        named = set()
        for row in field_rows:
            self.assertEqual(len(row), 3, row)
            self.assertTrue(all(row), row)
            named |= {part.strip("`[]<>") for part in re.split(r"[.\s]", row[0].strip("`"))}
        self.assertEqual(root_property_names(self.schema) - named, set())

        kind_rows = markdown_table(self.text, "Card kinds")
        self.assertEqual([row[0].strip("`") for row in kind_rows], list(KINDS))
        for row in kind_rows:
            self.assertEqual(len(row), 5, row)
            self.assertTrue(all(row), row)

        for required_phrase in (
            "**This contract grants nothing.**",
            "`.openwiz/feed.v1.json`",
            "`pinged.json` in the home checkout's `.openwiz/home` folder",
            "`openwiz.feed-pinged.v1`",
            "settings.v1.md",
            "plan-links.v1.md",
            "kernel/records.v1.md",
            *COMMENT_FORMS,
        ):
            self.assertIn(required_phrase, self.text)
        self.assertTrue(SETTINGS_DOC.is_file())

    def test_nothing_real_in_contract_schema_or_fixtures(self):
        shapes = {k: v for k, v in self.schema["$defs"].items() if k not in {"no_private", "no_private_id"}}
        self.assertIsNone(REAL_PRIVATE.search(json.dumps({**self.schema, "$defs": shapes})), "the schema")
        for path in [DOC] + sorted(p for p in HERE.rglob("*") if p.is_file() and p.suffix != ".py"):
            with self.subTest(path.name):
                self.assertIsNone(REAL_PRIVATE.search(path.read_text(encoding="utf-8")), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
