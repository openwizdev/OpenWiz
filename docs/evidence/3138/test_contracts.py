"""Proofs for the records, release-manifest and fleet OpenWiz contracts.

Needs `jsonschema` (Draft 2020-12). A stock Python has no such module.
How to run it: docs/evidence/3239/README.md.
"""

import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_SCHEMA_PATH = ROOT / "contracts" / "release-manifest.v1.schema.json"
MANIFEST_DOC_PATH = ROOT / "contracts" / "release-manifest.v1.md"
RECORDS_DOC_PATH = ROOT / "contracts" / "records.v1.md"
FLEET_DOC_PATH = ROOT / "contracts" / "fleet.v1.md"
WIZSKILLS_DOC_PATH = ROOT / "contracts" / "wizskills.v1.md"

SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
WIZSKILLS_VERSION_RE = re.compile(
    r"^(?:0\.[1-9][0-9]*|[1-9][0-9]*\.(?:0|[1-9][0-9]*))\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
RECORDS_VERSION_RE = re.compile(r"^v[1-9][0-9]*$")


def load_strict_json(raw: str):
    def no_dups(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate key: {key}")
            out[key] = value
        return out

    def reject_float(token):
        raise ValueError(f"non-integer number: {token}")

    return json.loads(raw, object_pairs_hook=no_dups, parse_float=reject_float)


def extract_json_blocks(markdown: str) -> list[str]:
    blocks = []
    lines = markdown.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].strip() == "```json":
            start = i + 1
            i += 1
            while i < len(lines) and lines[i].strip() != "```":
                i += 1
            blocks.append("\n".join(lines[start:i]))
        i += 1
    return blocks


def parse_openwiz_table(markdown: str) -> dict[str, str]:
    lines = markdown.replace("\r\n", "\n").splitlines()
    headings = [idx for idx, line in enumerate(lines) if line.strip() == "## OpenWiz"]
    if len(headings) != 1:
        raise ValueError(f"expected exactly one ## OpenWiz heading, found {len(headings)}")
    start = headings[0] + 1
    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    section = lines[start:end]
    table_start = next((idx for idx, line in enumerate(section) if line.startswith("|")), None)
    if table_start is None:
        raise ValueError("no table in ## OpenWiz section")
    table_lines = []
    for line in section[table_start:]:
        if not line.startswith("|"):
            break
        table_lines.append(line)
    if len(table_lines) < 2:
        raise ValueError("incomplete table header")

    def split_row(line: str) -> list[str]:
        if not (line.startswith("|") and line.endswith("|")):
            raise ValueError(f"malformed table row: {line}")
        return [cell.strip() for cell in line[1:-1].split("|")]

    header = split_row(table_lines[0])
    sep = split_row(table_lines[1])
    if header != ["Setting", "Value"]:
        raise ValueError(f"unexpected header: {header}")
    if len(sep) != 2 or not all(re.fullmatch(r"-{3,}", cell) for cell in sep):
        raise ValueError(f"unexpected separator: {sep}")
    expected_rows = ["OpenWiz", "WizSkills", "Records contract"]
    data_rows = [split_row(line) for line in table_lines[2:]]
    if len(data_rows) != len(expected_rows):
        raise ValueError(f"expected {len(expected_rows)} rows, found {len(data_rows)}")
    parsed = {}
    for expected_name, cells in zip(expected_rows, data_rows):
        if len(cells) != 2:
            raise ValueError(f"row must have 2 cells: {cells}")
        name, raw_val = cells
        if name != expected_name:
            raise ValueError(f"expected row {expected_name!r}, found {name!r}")
        if raw_val.startswith("`") and raw_val.endswith("`") and len(raw_val) >= 2:
            val = raw_val[1:-1]
        else:
            val = raw_val
        if name == "OpenWiz":
            if not SEMVER_RE.fullmatch(val):
                raise ValueError(f"invalid semver for {name}: {val!r}")
        elif name == "WizSkills":
            if not WIZSKILLS_VERSION_RE.fullmatch(val):
                raise ValueError(f"invalid WizSkills version: {val!r}")
        else:
            if not RECORDS_VERSION_RE.fullmatch(val):
                raise ValueError(f"invalid records contract version: {val!r}")
        parsed[name] = val
    return parsed


def valid_manifest() -> dict:
    return {
        "schema": "openwiz.release-manifest.v1",
        "kernel_version": "0.1.2",
        "wizskills": {
            "version": "0.5.0",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "tree": "89abcdef0123456789abcdef0123456789abcdef",
        },
        "records_contract": 1,
    }


class ReleaseManifestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = load_strict_json(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(self.schema)
        self.validator = Draft202012Validator(self.schema)

    def test_schema_declares_id_and_title(self):
        self.assertEqual(self.schema.get("title"), "openwiz.release-manifest.v1")
        self.assertEqual(
            self.schema.get("$schema"),
            "https://json-schema.org/draft/2020-12/schema",
        )

    def test_doc_example_validates(self):
        self.assertTrue(MANIFEST_DOC_PATH.is_file(), "release-manifest.v1.md missing")
        blocks = extract_json_blocks(MANIFEST_DOC_PATH.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(blocks), 1, "no JSON example in release-manifest.v1.md")
        example = load_strict_json(blocks[0])
        errors = list(self.validator.iter_errors(example))
        self.assertEqual(errors, [], f"example failed validation: {errors}")

    def test_refuses_malformed_manifests(self):
        cases = []

        for field in ("version", "commit", "tree"):
            bad = valid_manifest()
            del bad["wizskills"][field]
            cases.append((f"missing wizskills.{field}", bad))

        for field in ("schema", "kernel_version", "wizskills", "records_contract"):
            bad = valid_manifest()
            del bad[field]
            cases.append((f"missing top-level {field}", bad))

        extra_top = valid_manifest()
        extra_top["extra"] = "unexpected"
        cases.append(("extra top-level field", extra_top))

        extra_ws = valid_manifest()
        extra_ws["wizskills"]["tag"] = "v0.5.0"
        cases.append(("extra wizskills field", extra_ws))

        wrong_schema = valid_manifest()
        wrong_schema["schema"] = "openwiz.release-manifest.v2"
        cases.append(("wrong schema id", wrong_schema))

        bad_kernel = valid_manifest()
        bad_kernel["kernel_version"] = "v0.1.2"
        cases.append(("v-prefixed kernel_version", bad_kernel))

        bad_ws_ver = valid_manifest()
        bad_ws_ver["wizskills"]["version"] = "01.5.0"
        cases.append(("leading-zero wizskills.version", bad_ws_ver))

        bad_commit = valid_manifest()
        bad_commit["wizskills"]["commit"] = "0123456789ABCDEF0123456789abcdef01234567"
        cases.append(("uppercase hex commit", bad_commit))

        nl_commit = valid_manifest()
        nl_commit["wizskills"]["commit"] = "0123456789abcdef0123456789abcdef01234567\n"
        cases.append(("commit with trailing newline", nl_commit))

        nl_tree = valid_manifest()
        nl_tree["wizskills"]["tree"] = "89abcdef0123456789abcdef0123456789abcdef\n"
        cases.append(("tree with trailing newline", nl_tree))

        nl_kernel = valid_manifest()
        nl_kernel["kernel_version"] = "0.1.2\n"
        cases.append(("kernel_version with trailing newline", nl_kernel))

        nl_ws_ver = valid_manifest()
        nl_ws_ver["wizskills"]["version"] = "0.5.0\n"
        cases.append(("wizskills.version with trailing newline", nl_ws_ver))

        zero_minor_ws = valid_manifest()
        zero_minor_ws["wizskills"]["version"] = "0.0.1"
        cases.append(("wizskills.version 0.0.1", zero_minor_ws))

        short_tree = valid_manifest()
        short_tree["wizskills"]["tree"] = "89abcdef"
        cases.append(("short tree hash", short_tree))

        zero_rc = valid_manifest()
        zero_rc["records_contract"] = 0
        cases.append(("records_contract zero", zero_rc))

        str_rc = valid_manifest()
        str_rc["records_contract"] = "v1"
        cases.append(("records_contract string", str_rc))

        bool_rc = valid_manifest()
        bool_rc["records_contract"] = True
        cases.append(("records_contract bool", bool_rc))

        cases.append(("positional array", ["openwiz.release-manifest.v1", "0.1.2"]))

        for label, payload in cases:
            with self.subTest(case=label):
                errors = list(self.validator.iter_errors(payload))
                self.assertTrue(errors, f"schema accepted malformed manifest: {label}")

    def test_strict_reader_refuses_duplicate_keys_and_float_integer(self):
        dup_raw = (
            '{"schema":"openwiz.release-manifest.v1","kernel_version":"0.1.2",'
            '"wizskills":{"version":"0.5.0",'
            '"commit":"0123456789abcdef0123456789abcdef01234567",'
            '"tree":"89abcdef0123456789abcdef0123456789abcdef"},'
            '"records_contract":1,"records_contract":1}'
        )
        with self.assertRaises(ValueError):
            load_strict_json(dup_raw)

        float_raw = (
            '{"schema":"openwiz.release-manifest.v1","kernel_version":"0.1.2",'
            '"wizskills":{"version":"0.5.0",'
            '"commit":"0123456789abcdef0123456789abcdef01234567",'
            '"tree":"89abcdef0123456789abcdef0123456789abcdef"},'
            '"records_contract":1.0}'
        )
        with self.assertRaises(ValueError):
            load_strict_json(float_raw)

    def test_wizskills_version_matches_lock_pattern_and_accepts_prerelease(self):
        wiz_doc = WIZSKILLS_DOC_PATH.read_text(encoding="utf-8")
        match = re.search(r"```wizskills-v1\n(.*?)```", wiz_doc, re.DOTALL)
        self.assertIsNotNone(match, "wizskills-v1 block missing")
        vocab = load_strict_json(match.group(1))
        self.assertEqual(
            self.schema["$defs"].get("wizskills_version", {}).get("pattern"),
            f"^{vocab['version_pattern']}$",
        )
        prerelease = valid_manifest()
        prerelease["wizskills"]["version"] = "0.6.0-rc.1"
        self.assertEqual(list(self.validator.iter_errors(prerelease)), [])
        table = (
            "## OpenWiz\n\n| Setting | Value |\n| --- | --- |\n"
            "| OpenWiz | `0.1.2` |\n| WizSkills | `0.6.0-rc.1` |\n| Records contract | `v1` |\n"
        )
        self.assertEqual(parse_openwiz_table(table)["WizSkills"], "0.6.0-rc.1")


INDEX_HEADING = "## Indexed record forms (v1)"
RECORD_FORMS = (
    "Status note",
    "Decision request",
    "Decision answer",
    "Plan links",
    "Labels",
    "Fleet OpenWiz rows",
    "Fleet record authors",
    "Fleet models",
)


def parse_index_rows(markdown: str) -> list[list[str]]:
    lines = markdown.replace("\r\n", "\n").splitlines()
    try:
        start = lines.index(INDEX_HEADING)
    except ValueError:
        raise ValueError(f"missing {INDEX_HEADING}") from None
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    section = lines[start + 1:end]
    table = []
    for line in section:
        if line.startswith("|"):
            table.append(line)
        elif table:
            break
    if len(table) < 3:
        raise ValueError("index table is missing its header or rows")

    def cells(line: str) -> list[str]:
        if not (line.startswith("|") and line.endswith("|")):
            raise ValueError(f"malformed index row: {line}")
        return [cell.strip() for cell in line[1:-1].split("|")]

    header = cells(table[0])
    if header[:2] != ["Record form", "Own marker / version"]:
        raise ValueError(f"unexpected index header: {header}")
    rows = []
    for line in table[2:]:
        parsed = cells(line)
        if len(parsed) < 5 or not parsed[0]:
            raise ValueError(f"index row has no record form: {line}")
        rows.append(parsed)
    return rows


class RecordsContractTests(unittest.TestCase):
    def test_records_v1_indexes_every_app_record_form_and_rules(self):
        self.assertTrue(RECORDS_DOC_PATH.is_file(), "contracts/records.v1.md missing")
        text = RECORDS_DOC_PATH.read_text(encoding="utf-8")
        rows = parse_index_rows(text)
        self.assertEqual([row[0] for row in rows], list(RECORD_FORMS))
        by_name = {row[0]: row for row in rows}
        for name, row in by_name.items():
            with self.subTest(form=name):
                self.assertTrue(row[1].strip(), f"{name} has an empty marker or version cell")
        self.assertEqual(by_name["Labels"][1], "no own marker (kernel records v1 section 1)")
        self.assertIn("the app is the source of `wayfind:map`", by_name["Labels"][3])
        self.assertEqual(by_name["Plan links"][4], "native `blockedBy` links")
        self.assertIn("writer-side form", by_name["Plan links"][1])
        self.assertEqual(by_name["Fleet OpenWiz rows"][4], "read from #3142")
        self.assertNotIn(
            "docs/adr/0021-app-skills-kernel-ship-as-a-matched-set.md",
            text,
            "records contract still cites the missing ADR path",
        )
        self.assertIn("openwizdev/OpenWiz#3136", text, "records contract does not cite #3136")
        for token in ("openwiz update", "D2", "D3"):
            with self.subTest(token=token):
                self.assertIn(token, text)

    def test_records_v1_index_table_covers_grill_templates_and_models_offered(self):
        lines = RECORDS_DOC_PATH.read_text(encoding="utf-8").splitlines()
        start = next(
            (i for i, line in enumerate(lines) if line.startswith("| Record form |")),
            None,
        )
        self.assertIsNotNone(start, "index table missing")
        rows = {}
        for line in lines[start + 2 :]:
            if not line.startswith("|"):
                break
            cells = [c.strip() for c in line[1:-1].split("|")]
            rows[cells[0]] = cells
        expected = {
            "Grill file": ("# Grill: ", "## Round", "docs/grills/"),
            "Spec and ticket templates": ("## Changelog headline", "kernel/records.v1.md"),
            "Models-offered snapshot": ("openwiz.models-offered.v1", "models-offered.json"),
            "Narrated-spec video comment": (
                "[Watch the narrated spec]",
                "to-spec/SKILL.md",
                "animatic.mjs",
                "queue.js",
                "Steering by comment is off for now",
            ),
        }
        for name, markers in expected.items():
            with self.subTest(row=name):
                self.assertIn(name, rows, f"index table missing row {name!r}")
                joined = " | ".join(rows[name])
                for marker in markers:
                    self.assertIn(marker, joined, f"row {name!r} missing {marker!r}")


class FleetOpenWizRowsTests(unittest.TestCase):
    def test_fleet_contract_has_openwiz_rows_section_and_example(self):
        text = FLEET_DOC_PATH.read_text(encoding="utf-8")
        self.assertTrue(
            "## OpenWiz` rows a repository records" in text,
            "scope line does not name the OpenWiz rows",
        )
        self.assertTrue(
            "**Revision, 2026-11-24:** added `## OpenWiz rows`" in text,
            "no dated revision note for ## OpenWiz rows",
        )
        self.assertNotIn(
            "docs/adr/0021-app-skills-kernel-ship-as-a-matched-set.md",
            text,
            "fleet contract still cites the missing ADR path",
        )
        self.assertIn("openwizdev/OpenWiz#3136", text)
        manifest = MANIFEST_DOC_PATH.read_text(encoding="utf-8")
        self.assertNotIn(
            "docs/adr/0021-app-skills-kernel-ship-as-a-matched-set.md",
            manifest,
            "release manifest still cites the missing ADR path",
        )
        self.assertIn("openwizdev/OpenWiz#3136", manifest)
        match = re.search(r"```md\n(## OpenWiz\n.*?)```", text, re.DOTALL)
        self.assertIsNotNone(match, "no ## OpenWiz markdown example in contracts/fleet.v1.md")
        parsed = parse_openwiz_table(match.group(1))
        self.assertEqual(
            parsed,
            {"OpenWiz": "0.1.2", "WizSkills": "0.5.0", "Records contract": "v1"},
        )

    def test_openwiz_rows_parser_refuses_bad_tables(self):
        bad_tables = [
            (
                "missing Records contract row",
                "## OpenWiz\n\n| Setting | Value |\n| --- | --- |\n| OpenWiz | `0.1.2` |\n| WizSkills | `0.5.0` |\n",
            ),
            (
                "v0 records contract",
                "## OpenWiz\n\n| Setting | Value |\n| --- | --- |\n| OpenWiz | `0.1.2` |\n| WizSkills | `0.5.0` |\n| Records contract | `v0` |\n",
            ),
            (
                "v-prefixed OpenWiz version",
                "## OpenWiz\n\n| Setting | Value |\n| --- | --- |\n| OpenWiz | `v0.1.2` |\n| WizSkills | `0.5.0` |\n| Records contract | `v1` |\n",
            ),
            (
                "reordered rows",
                "## OpenWiz\n\n| Setting | Value |\n| --- | --- |\n| WizSkills | `0.5.0` |\n| OpenWiz | `0.1.2` |\n| Records contract | `v1` |\n",
            ),
            (
                "extra row",
                "## OpenWiz\n\n| Setting | Value |\n| --- | --- |\n| OpenWiz | `0.1.2` |\n| WizSkills | `0.5.0` |\n| Records contract | `v1` |\n| Extra | `1` |\n",
            ),
        ]
        for label, snippet in bad_tables:
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    parse_openwiz_table(snippet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
