#!/usr/bin/env python3
"""Proofs for the local CRM. Synthetic records only. No network."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from openwiz_crm.errors import CrmError
from openwiz_crm.store import Store

CLI = [sys.executable, "-I", str(ROOT / "crm.py")]
MCP = [sys.executable, "-I", str(ROOT / "mcp.py")]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store.open(Path(self.tmp.name) / "crm.sqlite")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_schema_starts_with_standard_objects(self):
        names = [obj["api_name"] for obj in self.store.schema()["objects"]]
        self.assertEqual(names, ["person", "company", "deal", "activity"])
        person = self.store.schema()["objects"][0]
        self.assertEqual(person["kind"], "standard")
        self.assertTrue(person["fields"][0]["required"])
        self.assertEqual(person["fields"][0]["origin"], "standard")

    def test_create_requires_name_and_rejects_unknown_fields(self):
        with self.assertRaises(CrmError) as missing:
            self.store.create_record("person", {}, "agent")
        self.assertEqual(missing.exception.code, "validation")
        with self.assertRaises(CrmError) as unknown:
            self.store.create_record("person", {"name": "Ada", "nope": "x"}, "agent")
        self.assertEqual(unknown.exception.code, "unknown_field")

    def test_custom_field_round_trip_and_search(self):
        self.store.add_field("person", "github", "GitHub", "text")
        created = self.store.create_record(
            "person", {"name": "Ada", "email": "ada@example.com", "github": "ada"}, "agent",
        )
        self.store.create_record("person", {"name": "Grace", "github": "grace"}, "agent")
        found = self.store.search("person", where={"github": "ada"})
        self.assertEqual([row["id"] for row in found["records"]], [created["id"]])
        queried = self.store.search("person", query="Ada@example.com")
        self.assertEqual(queried["records"][0]["fields"]["email"], "ada@example.com")

    def test_update_keeps_other_fields_and_records_history(self):
        self.store.add_field("person", "active", "Active", "boolean")
        created = self.store.create_record(
            "person", {"name": "Ada", "email": "ada@example.com", "active": True}, "agent",
        )
        updated = self.store.update_record(
            "person", created["id"], {"role": "contributor"}, ["active"], "agent",
        )
        self.assertEqual(updated["fields"]["email"], "ada@example.com")
        self.assertEqual(updated["fields"]["role"], "contributor")
        self.assertNotIn("active", updated["fields"])
        context = self.store.context(created["id"])
        self.assertEqual(context["changes"][0]["op"], "update")
        self.assertEqual(context["changes"][0]["actor"], "agent")
        with self.assertRaises(CrmError) as stale:
            self.store.update_record(
                "person", created["id"], {"role": "partner"}, [], "agent",
                if_revision=created["revision"],
            )
        self.assertEqual(stale.exception.code, "conflict")
        current = self.store.get_record(created["id"])
        self.store.update_record(
            "person", created["id"], {"role": "partner"}, [], "agent",
            if_revision=current["revision"],
        )

    def test_select_number_and_custom_object(self):
        with self.assertRaises(CrmError):
            self.store.create_record("deal", {"name": "Outside", "stage": "nope"}, "agent")
        deal = self.store.create_record(
            "deal", {"name": "Outside repo", "stage": "qualifying", "amount": "12.0"}, "agent",
        )
        self.assertEqual(deal["fields"]["amount"], 12)
        self.store.add_object("listing", "Listing")
        self.store.add_field(
            "listing", "status", "Status", "select", options=["open", "closed"],
        )
        listing = self.store.create_record("listing", {"status": "open"}, "agent")
        self.assertEqual(listing["object"], "listing")
        with self.assertRaises(CrmError) as required:
            self.store.add_field("listing", "city", "City", "text", required=True)
        self.assertEqual(required.exception.code, "validation")

    def test_association_context_and_activity_rollback(self):
        person = self.store.create_record(
            "person", {"name": "Ada", "email": "ada@example.com"}, "agent",
        )
        company = self.store.create_record(
            "company", {"name": "Example", "domain": "example.com"}, "agent",
        )
        link = self.store.associate(person["id"], company["id"], "works_at", "agent")
        self.assertEqual(link["label"], "works_at")
        with self.assertRaises(CrmError) as duplicate:
            self.store.associate(person["id"], company["id"], "works_at", "agent")
        self.assertEqual(duplicate.exception.code, "conflict")
        with self.assertRaises(CrmError):
            self.store.log_activity(
                "github", "Opened a pull request", [person["id"], "rec_missing"], "agent",
                happened_at="2026-11-25T00:00:00Z", source="test",
            )
        self.assertEqual(self.store.search("activity")["records"], [])
        logged = self.store.log_activity(
            "github", "Opened a pull request", [person["id"], company["id"]], "agent",
            body="Synthetic pull request.", happened_at="2026-11-25T00:00:00Z", source="github",
        )
        context = self.store.context(person["id"])
        labels = sorted(item["label"] for item in context["links"])
        self.assertEqual(labels, ["about", "works_at"])
        activity = next(item for item in context["links"] if item["label"] == "about")
        self.assertEqual(activity["direction"], "in")
        self.assertEqual(activity["record"]["id"], logged["record"]["id"])
        company_context = self.store.context(company["id"])
        self.assertIn("about", [item["label"] for item in company_context["links"]])

    def test_delete_hides_search_and_blocks_update(self):
        created = self.store.create_record("person", {"name": "Ada"}, "agent")
        deleted = self.store.delete_record("person", created["id"], "agent")
        self.assertIsNotNone(deleted["deleted_at"])
        self.assertEqual(self.store.search("person", query="Ada")["records"], [])
        self.assertEqual(self.store.get_record(created["id"])["deleted_at"], deleted["deleted_at"])
        with self.assertRaises(CrmError) as update:
            self.store.update_record("person", created["id"], {"role": "x"}, [], "agent")
        self.assertEqual(update.exception.code, "not_found")

    def test_object_mismatch_and_external_ref(self):
        person = self.store.create_record("person", {"name": "Ada"}, "agent")
        with self.assertRaises(CrmError) as mismatch:
            self.store.update_record("company", person["id"], {"name": "Other"}, [], "agent")
        self.assertEqual(mismatch.exception.code, "object_mismatch")
        bound = self.store.bind_ref("salesforce", "Account", "001EXAMPLE", person["id"])
        self.assertEqual(bound["id"], person["id"])
        again = self.store.bind_ref("salesforce", "Account", "001EXAMPLE", person["id"])
        self.assertEqual(again, bound)
        self.assertEqual(
            self.store.find_ref("salesforce", "Account", "001EXAMPLE")["id"], person["id"],
        )
        company = self.store.create_record("company", {"name": "Example"}, "agent")
        same_number = self.store.bind_ref("hubspot", "0-2", "1001", company["id"])
        self.store.bind_ref("hubspot", "0-1", "1001", person["id"])
        self.assertNotEqual(same_number["id"], person["id"])
        other = self.store.create_record("person", {"name": "Grace"}, "agent")
        with self.assertRaises(CrmError) as conflict:
            self.store.bind_ref("salesforce", "Account", "001EXAMPLE", other["id"])
        self.assertEqual(conflict.exception.code, "conflict")

    def test_search_limit_truncates(self):
        for index in range(3):
            self.store.create_record("person", {"name": "Person " + str(index)}, "agent")
        page = self.store.search("person", limit=2)
        self.assertEqual(len(page["records"]), 2)
        self.assertTrue(page["truncated"])


class SurfaceTest(unittest.TestCase):
    def test_cli_create_search_and_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "crm.sqlite")
            created = self.cli(db, [
                "record-create", "--object", "company",
                "--set", "name=Example", "--set", "domain=example.com",
            ])
            company = created["result"]["id"]
            person = self.cli(db, [
                "record-create", "--object", "person",
                "--set", "name=Ada", "--set", "email=ada@example.com",
            ])["result"]["id"]
            self.cli(db, ["associate", "--from", person, "--to", company, "--label", "works_at"])
            self.cli(db, [
                "activity-log", "--kind", "email", "--summary", "Introduced the product",
                "--link", person, "--happened-at", "2026-11-25",
            ])
            found = self.cli(db, ["record-search", "--object", "person", "--query", "ada"])
            self.assertEqual(found["result"]["records"][0]["id"], person)
            context = self.cli(db, ["context", "--id", person])
            self.assertEqual(len(context["result"]["links"]), 2)
            missing = self.cli(db, ["record-get", "--id", "rec_missing"], expect=1)
            self.assertEqual(missing["error"]["code"], "not_found")

    def test_mcp_lists_tools_and_creates_a_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "crm.sqlite")
            lines = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                }},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                    "name": "crm_record_create",
                    "arguments": {"object": "person", "fields": {"name": "Ada"}},
                }},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                    "name": "crm_record_search",
                    "arguments": {"object": "person", "query": "Ada"},
                }},
            ]
            payload = "".join(json.dumps(line) + "\n" for line in lines)
            result = subprocess.run(
                MCP, input=payload, text=True, capture_output=True,
                env={"OPENWIZ_CRM_DB": db}, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            messages = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            self.assertEqual([message["id"] for message in messages], [1, 2, 3, 4])
            self.assertEqual(messages[0]["result"]["serverInfo"]["name"], "openwiz-crm")
            names = [tool["name"] for tool in messages[1]["result"]["tools"]]
            self.assertIn("crm_record_context", names)
            created = json.loads(messages[2]["result"]["content"][0]["text"])
            self.assertTrue(created["ok"])
            found = json.loads(messages[3]["result"]["content"][0]["text"])
            self.assertEqual(found["result"]["records"][0]["fields"]["name"], "Ada")

    def test_package_does_not_reference_a_network_client(self):
        banned = ("urllib", "http.client", "import socket", "requests", "httpx")
        for path in (ROOT / "openwiz_crm").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for name in banned:
                self.assertNotIn(name, text, path.name)

    def cli(self, db, args, expect=0):
        result = subprocess.run(
            CLI + ["--db", db, *args], text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, expect, result.stderr + result.stdout)
        self.assertEqual(result.stderr, "")
        return json.loads(result.stdout)


if __name__ == "__main__":
    raise SystemExit(0 if unittest.main(verbosity=1, exit=False).result.wasSuccessful() else 1)
