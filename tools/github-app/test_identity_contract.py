#!/usr/bin/env python3
"""GI-P4 (#2545): the GitHub identity contract's fixture test. Offline, synthetic.

Run: python3 -I tools/github-app/test_identity_contract.py

The contract's one ```json block is its machine-readable pin. Its App profile
must equal the registered manifest's, and its read profile must equal the
agent GitHub reads contract's schema constant. Neither the contract nor its
fixtures may hold a key, a token or a real numeric id.
"""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "contracts/github-identity.v1.md"
FIXTURES = ROOT / "contracts/fixtures/github-identity"
MANIFEST = ROOT / "tools/github-app/manifest.json"
READS_SCHEMA = ROOT / "contracts/agent-github-reads.v1.schema.json"


def strict(text):
    def once(pairs):
        keys = [key for key, _ in pairs]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate key")
        return dict(pairs)
    return json.loads(text, object_pairs_hook=once)


def pin():
    blocks = re.findall(r"^```json\n(.*?)^```$", CONTRACT.read_text(), re.M | re.S)
    if len(blocks) != 1:
        raise AssertionError(f"the contract needs exactly one json pin, found {len(blocks)}")
    return strict(blocks[0])


def read_constants(node):
    """Every `permissions` const in the reads schema: the read profile it pins."""
    found = []
    if isinstance(node, dict):
        if isinstance(node.get("permissions"), dict) and "const" in node["permissions"]:
            found.append(node["permissions"]["const"])
        for value in node.values():
            found += read_constants(value)
    elif isinstance(node, list):
        for value in node:
            found += read_constants(value)
    return found


# Credential shapes that must never appear: PEM blocks, GitHub token prefixes,
# a JWT, or a dotenv-style assignment of the secret. Ids: any number of five
# or more digits is treated as a possibly real App, installation or user id.
CREDENTIALS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\b(?:ghs|ghp|gho|ghu|ghr)_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.",
    r"OPENWIZ_GITHUB_APP_KEY=\S",
)]
LONG_NUMBER = re.compile(r"(?<![\w.#/-])\d{5,}(?![\w.-])")


class ContractPin(unittest.TestCase):
    def setUp(self):
        self.pin = pin()

    def test_schema_and_no_authority(self):
        self.assertEqual(self.pin["schema"], "openwiz.github-identity.v1")
        self.assertEqual(self.pin["authority"], {
            "installation": False, "credential": False, "live": False})

    def test_app_profile_is_the_registered_manifest(self):
        manifest = strict(MANIFEST.read_text())
        app = self.pin["app"]
        self.assertEqual(app["permissions"], manifest["default_permissions"])
        self.assertEqual(app["events"], manifest["default_events"])
        self.assertEqual(app["events"], [])
        self.assertIs(app["webhook"], False)
        self.assertEqual(manifest["hook_attributes"], {"active": False})
        self.assertEqual(app["count"], 1)

    def test_one_app_across_accounts_is_public(self):
        # R1 (#2558): a private App installs only on its owner's account, so one
        # App installed on more than one account must be public. The manifest's
        # "public": false is GI4's line (#2546): this checks the pin, not it.
        accounts = {i["account"] for i in self.pin["installations"]}
        self.assertGreater(len(accounts), 1)
        self.assertEqual(self.pin["app"]["visibility"], "public")
        self.assertEqual(self.pin["app"]["token_minting"], "owner key only")

    def test_read_profile_is_the_reads_contract(self):
        constants = read_constants(strict(READS_SCHEMA.read_text()))
        self.assertTrue(constants, "the reads schema pins no read profile")
        for constant in constants:
            self.assertEqual(self.pin["read_permissions"], constant)
        self.assertEqual(set(self.pin["read_permissions"].values()), {"read"})
        # Downscoping only: the read profile names the App's permissions, read.
        self.assertEqual(set(self.pin["read_permissions"]), set(self.pin["app"]["permissions"]))

    def test_installations_select_repositories_only(self):
        # No repository literal here: tools/github-app names no fixed target
        # (#1279, test.py). The names are the contract's, checked by review.
        installations = self.pin["installations"]
        self.assertEqual(len(installations), 2)
        self.assertEqual(len({i["account"] for i in installations}), 2)
        for installation in installations:
            self.assertEqual(set(installation), {"account", "repository_selection", "repositories"})
            self.assertEqual(installation["repository_selection"], "selected")
            self.assertTrue(installation["repositories"])
            for repository in installation["repositories"]:
                self.assertEqual(repository.split("/")[0], installation["account"])

    def test_installations_match_the_contract_table(self):
        section = CONTRACT.read_text().split("## The installations", 1)[1].split("\n## ", 1)[0]
        rows = re.findall(r"^\| `([^`]+)` \([^)]*\) \| (.+) \|$", section, re.M)
        table = {account: sorted(re.findall(r"`([^`]+)`", repos)) for account, repos in rows}
        self.assertEqual(table, {i["account"]: sorted(i["repositories"])
                                 for i in self.pin["installations"]})

    def test_token_command_guards(self):
        token = self.pin["token_command"]
        self.assertEqual(token["stdout"], "token")
        self.assertEqual(token["auth"], "installation")
        self.assertIs(token["stores"], False)
        # The adapter's existing guards (crates/adapters/github/src/app.rs):
        # refresh 300 s before expiry; refuse a lifetime over an hour plus skew.
        self.assertEqual((token["min_remaining_s"], token["max_lifetime_s"]), (300, 3900))
        self.assertEqual(token["argv"][:5], ["openwiz", "github", "token", "--repository", "<owner/name>"])
        self.assertEqual(self.pin["secret"]["name"], "OPENWIZ_GITHUB_APP_KEY")
        self.assertEqual(self.pin["secret"]["holds"], ["private_key"])
        self.assertEqual(token["read_flag_permissions"], "read_permissions")
        self.assertEqual(token["exits"], {"0": "token printed", "1": "context or read failure",
                                          "2": "usage", "3": "repository not installed",
                                          "5": "refused"})


class Fixtures(unittest.TestCase):
    """Synthetic fixtures for GI4, GI5 and GI7 agree with the pin."""

    def setUp(self):
        self.pin = pin()
        self.files = sorted(p for p in FIXTURES.rglob("*") if p.is_file())

    def test_fixtures_exist_and_parse(self):
        names = {p.name for p in self.files}
        self.assertTrue({"token-exchange.json", "commit-identity.json", "secret.json"} <= names)
        for path in self.files:
            if path.suffix == ".json":
                strict(path.read_text())

    def test_token_exchange_requests_exact_profiles(self):
        cases = strict((FIXTURES / "token-exchange.json").read_text())["cases"]
        profiles = {"write": self.pin["app"]["permissions"], "read": self.pin["read_permissions"]}
        self.assertEqual({c["mode"] for c in cases}, {"write", "read"})
        for case in cases:
            request = case["request"]
            self.assertEqual(request["permissions"], profiles[case["mode"]])
            self.assertEqual(len(request["repositories"]), 1)
            self.assertNotIn("/", request["repositories"][0])

    def test_token_exchange_outcomes_follow_the_guards(self):
        # R2 (#2558, #2569): answers and expected outputs obey the contract.
        exchange = strict((FIXTURES / "token-exchange.json").read_text())
        guards = self.pin["token_command"]
        exits = set()
        for case in exchange["cases"]:
            request, answer = case["request"], case["answer"]
            owner = case["argv"][4].split("/")[0]
            left = answer["expires_at"] - exchange["now"]
            good = (answer["permissions"] == request["permissions"]
                    and answer["repository_selection"] == "selected"
                    and answer["repositories"] == [{"full_name": f"{owner}/{request['repositories'][0]}"}]
                    and guards["min_remaining_s"] < left <= guards["max_lifetime_s"])
            exits.add(case["exit"])
            if case["exit"] == 0:
                self.assertTrue(good, case)
                self.assertEqual(case["stdout"], answer["token"] + "\n")
                self.assertEqual(case["stderr"], f"expires_at {answer['expires_at']}\n")
            else:
                self.assertEqual(case["exit"], 5)
                self.assertFalse(good, case)
                self.assertEqual(case["stdout"], "")
                self.assertIn(answer["token"], case["stderr_has_no"])
        self.assertEqual(exits, {0, 5})

    def test_secret_fixture_names_the_secret(self):
        secret = strict((FIXTURES / "secret.json").read_text())
        self.assertEqual(secret["name"], self.pin["secret"]["name"])
        self.assertEqual(secret["holds"], ["private_key"])

    def test_commit_identity_uses_the_noreply_email(self):
        case = strict((FIXTURES / "commit-identity.json").read_text())
        user = case["github_user"]
        email = f"{user['id']}+{user['login']}@users.noreply.github.com"
        self.assertEqual(case["author"], {"name": user["login"], "email": email})
        self.assertEqual(case["committer"], case["author"])


class NoSecretsOrRealIds(unittest.TestCase):
    def test_contract_and_fixtures_hold_no_credential_or_real_id(self):
        for path in [CONTRACT] + sorted(p for p in FIXTURES.rglob("*") if p.is_file()):
            text = path.read_text()
            for pattern in CREDENTIALS:
                self.assertIsNone(pattern.search(text), f"{path.name}: {pattern.pattern}")
            self.assertEqual(LONG_NUMBER.findall(text), [], path.name)

    def test_the_scan_catches_what_it_claims(self):
        planted = ["-----BEGIN RSA PRIVATE KEY-----", "ghs_" + "A" * 36,
                   "github_pat_" + "B" * 30, "eyJ" + "a" * 12 + "." + "b" * 12 + ".c",
                   "OPENWIZ_GITHUB_APP_KEY=abc"]
        for text in planted:
            self.assertTrue(any(p.search(text) for p in CREDENTIALS), text)
        self.assertEqual(LONG_NUMBER.findall("app 1234567 and #2545 and 3900 s"), ["1234567"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
