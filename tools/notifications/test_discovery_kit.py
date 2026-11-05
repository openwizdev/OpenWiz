#!/usr/bin/env python3
"""Offline discovery-plan validation and its tests. This file executes no plan."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PATHS = (
    "/api/v1/health", "/api/v1/setup", "/api/v1/notifications/status",
    "/sw.js", "/manifest.webmanifest",
)
BOUNDS = {"elapsed_s": 300, "request_s": 10, "response_bytes": 65536,
          "requests": 5, "browser_reads": 1, "retries": 0}
EFFECTS = dict.fromkeys(("permission_prompts", "subscriptions", "notifications",
                        "cloudroom_sends", "cloudroom_starts", "restarts",
                        "purchases", "access_changes", "credential_changes"), 0)


class Refusal(ValueError):
    pass


def require(condition):
    if not condition:
        raise Refusal("incomplete or out-of-scope discovery plan")


def exact_object(value, keys):
    require(type(value) is dict and set(value) == set(keys))


def known(value):
    require(type(value) is str and 0 < len(value) <= 512)
    require(value.isascii() and value == value.strip())
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value))
    require(value.lower() not in {"unknown", "unverified", "todo", "tbd", "none"})
    require(not any(c in value for c in "<>"))


def absolute_file(value):
    known(value)
    require(value.startswith("/") and not value.startswith("//"))
    require(all(part not in {"", ".", ".."} for part in value.split("/")[1:]))
    require("=" not in value)  # curl --cookie must select a file, not literal cookies


def validate_plan(plan):
    """Check structure only. Never resolve hosts, inspect paths or run commands."""
    exact_object(plan, ("schema", "version", "candidate", "engine_host", "account",
                        "origin", "curl", "cookie_file", "bounds", "effects",
                        "reads", "browser", "privacy", "stop"))
    require(plan["schema"] == "openwiz.notification-discovery-plan.v1")
    require(plan["version"] == "0.0.15")
    exact_object(plan["candidate"], ("version", "head", "tree"))
    require(plan["candidate"]["version"] == "0.0.15")
    for key in ("head", "tree"):
        value = plan["candidate"][key]
        require(type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value))
    for key in ("engine_host", "account"):
        known(plan[key])
    absolute_file(plan["curl"])
    known(plan["origin"])
    # J16 (#2507): an exact literal loopback HTTP origin with a port, on the
    # engine host itself, carries no cookie. Matched as a string only: no
    # resolution, and no other host spelling or http:// origin is admissible.
    loopback = re.fullmatch(r"http://(?:127\.0\.0\.1|\[::1\]):([1-9][0-9]{0,4})",
                            plan["origin"])
    if loopback:
        require(int(loopback.group(1)) <= 65535)
        require(plan["cookie_file"] is None)
    else:
        absolute_file(plan["cookie_file"])
        origin = urlsplit(plan["origin"])
        require(origin.scheme == "https" and origin.hostname is not None)
        require(origin.username is None and origin.password is None)
        require(not origin.path and not origin.query and not origin.fragment)
        # Match an exact HTTPS origin; exclude empty ?, #, encoded hosts and ports
        # which URL parsers otherwise normalize or silently discard.
        require(re.fullmatch(r"https://[a-z0-9]+(?:[.-][a-z0-9]+)*(?::[1-9][0-9]{0,4})?",
                             plan["origin"]) is not None)
        require(origin.port is None or origin.port <= 65535)
    for field, expected in (("bounds", BOUNDS), ("effects", EFFECTS)):
        exact_object(plan[field], expected)
        for key, value in expected.items():
            require(type(plan[field][key]) is int and plan[field][key] == value)
    require(type(plan["reads"]) is list and plan["reads"] == list(PATHS))
    require(plan["privacy"] == "owner-only-no-raw-output")
    require(plan["stop"] == "first-refusal-no-retry")
    browser = plan["browser"]
    exact_object(browser, ("availability", "host", "account", "context", "gap"))
    require(browser["availability"] in ("available", "unavailable"))
    if browser["availability"] == "available":
        for key in ("host", "account", "context"):
            known(browser[key])
        require(browser["gap"] is None)
    else:
        require(all(browser[key] is None for key in ("host", "account", "context")))
        known(browser["gap"])
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True).encode()).hexdigest()
    return {"status": "offline_valid_for_review", "live_authority": False,
            "plan_sha256": digest, "requests": 5,
            "browser_reads": int(browser["availability"] == "available"),
            "phone_display": "Unverified"}


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Refusal("duplicate key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs)


def fixture():
    """Synthetic only; these endpoints/accounts are never contacted."""
    return {
        "schema": "openwiz.notification-discovery-plan.v1", "version": "0.0.15",
        "candidate": {"version": "0.0.15", "head": "a" * 40, "tree": "b" * 40},
        "engine_host": "synthetic-engine", "account": "synthetic-owner",
        "origin": "https://cockpit.example.invalid", "curl": "/usr/bin/curl",
        "cookie_file": "/private/synthetic/access.cookies",
        "bounds": {"elapsed_s": 300, "request_s": 10, "response_bytes": 65536,
                   "requests": 5, "browser_reads": 1, "retries": 0},
        "effects": {"permission_prompts": 0, "subscriptions": 0, "notifications": 0,
                    "cloudroom_sends": 0, "cloudroom_starts": 0, "restarts": 0,
                    "purchases": 0, "access_changes": 0, "credential_changes": 0},
        "reads": ["/api/v1/health", "/api/v1/setup", "/api/v1/notifications/status",
                  "/sw.js", "/manifest.webmanifest"],
        "browser": {"availability": "available", "host": "synthetic-phone",
                    "account": "synthetic-owner", "context": "synthetic-tab",
                    "gap": None},
        "privacy": "owner-only-no-raw-output", "stop": "first-refusal-no-retry",
    }


def loopback_fixture(origin="http://127.0.0.1:7370"):
    """Synthetic loopback form (J16); nothing is contacted or resolved."""
    plan = fixture()
    plan["origin"] = origin
    plan["cookie_file"] = None
    return plan


# Today's reviewed HTTPS argv, copied from the kit as #2228 merged it. #2507
# must leave these bytes unchanged.
HTTPS_ARGV = """[curl, "--disable", "--silent", "--show-error", "--request", "GET",
 "--proto", "=https", "--max-redirs", "0", "--connect-timeout", "5",
 "--max-time", "10", "--max-filesize", "65536",
 "--write-out", "%{stderr}status=%{http_code} type=%{content_type} bytes=%{size_download}\\n",
 "--cookie", cookie_file, "--url", origin + route]"""


class DiscoveryKitTests(unittest.TestCase):
    # PA5/PA8 kit integrity: an incomplete or widened plan must not reach review
    # as a bounded plan. No previous notification discovery-kit test exists.
    def test_complete_plan_validates_without_network_process_or_write(self):
        with patch.object(socket, "socket", side_effect=AssertionError("network")), \
             patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
             patch.object(Path, "write_text", side_effect=AssertionError("write")):
            result = validate_plan(fixture())
        self.assertEqual(result["status"], "offline_valid_for_review")
        self.assertEqual(result["live_authority"], False)
        self.assertEqual(result["requests"], 5)
        self.assertEqual(result["browser_reads"], 1)
        self.assertRegex(result["plan_sha256"], r"^[0-9a-f]{64}$")

    def test_unknown_missing_extra_and_wrong_types_refuse(self):
        cases = []
        for key in fixture():
            missing = fixture()
            del missing[key]
            cases.append(missing)
        for key in ("engine_host", "account", "origin", "curl", "cookie_file"):
            for bad in (None, "", "unknown", "<fill-me>", True):
                plan = fixture()
                plan[key] = bad
                cases.append(plan)
        for field in ("candidate", "bounds", "effects", "browser"):
            for bad in (None, [], {**fixture()[field], "extra": 1}):
                plan = fixture()
                plan[field] = bad
                cases.append(plan)
        for field, values in (("bounds", fixture()["bounds"]),
                              ("effects", fixture()["effects"])):
            for key in values:
                for bad in (True, None, -1, values[key] + 1):
                    plan = fixture()
                    plan[field][key] = bad
                    cases.append(plan)
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(Refusal):
                validate_plan(plan)

    def test_only_the_declared_read_commands_are_admissible(self):
        for key, value in (
            ("origin", "http://cockpit.example.invalid"),
            ("origin", "https://user:secret@example.invalid"),
            ("origin", "https://cockpit.example.invalid/redirect?token=secret"),
            ("origin", "https://cockpit.example.invalid#fragment"),
            ("origin", "https://cockpit.example.invalid\n--insecure"),
            ("curl", "curl"), ("cookie_file", "secret=value"),
            ("reads", ["/api/v1/inventory"]),
            ("reads", [*fixture()["reads"], "/api/v1/sessions/synthetic/messages"]),
            ("reads", [*fixture()["reads"][:-1], "/sw.js?redirect=elsewhere"]),
            ("privacy", "public-logs"), ("stop", "retry"),
            ("version", "0.0.99"),
        ):
            plan = fixture()
            plan[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(Refusal):
                validate_plan(plan)
        plan = fixture()
        plan["command"] = ["room-cli", "thread", "spawn"]
        with self.assertRaises(Refusal):
            validate_plan(plan)

    # J16 (#2507): the five reads may run over the engine host's own loopback
    # address. Only an exact literal loopback HTTP origin with a port, and no
    # cookie file, is admissible; everything else that is plain HTTP refuses.
    def test_exact_loopback_http_origin_without_cookie_validates_offline(self):
        for origin in ("http://127.0.0.1:7370", "http://[::1]:7370",
                       "http://127.0.0.1:1", "http://[::1]:65535"):
            plan = loopback_fixture(origin)
            with self.subTest(origin=origin), \
                 patch.object(socket, "socket", side_effect=AssertionError("network")), \
                 patch.object(socket, "getaddrinfo", side_effect=AssertionError("resolve")), \
                 patch.object(subprocess, "Popen", side_effect=AssertionError("process")), \
                 patch.object(Path, "read_text", side_effect=AssertionError("read")):
                result = validate_plan(plan)
                self.assertEqual(result["status"], "offline_valid_for_review")
                self.assertEqual(result["live_authority"], False)
                self.assertEqual(result["requests"], 5)
                self.assertEqual(result["phone_display"], "Unverified")

    def test_loopback_form_refuses_any_other_http_origin_or_a_cookie(self):
        refused = (
            "http://cockpit.example.invalid", "http://cockpit.example.invalid:7370",
            "http://192.0.2.10:7370", "http://127.0.0.2:7370", "http://0.0.0.0:7370",
            "http://localhost:7370", "http://LOCALHOST:7370", "http://engine:7370",
            "http://127.0.0.1", "http://[::1]", "http://127.0.0.1:", "http://[::1]:",
            "http://127.0.0.1:0", "http://127.0.0.1:07370", "http://127.0.0.1:65536",
            "http://127.0.0.1:99999", "http://127.0.0.1:7370/", "http://127.0.0.1:7370/api",
            "http://[::1]:7370/", "http://127.0.0.1:7370?", "http://127.0.0.1:7370?a=b",
            "http://127.0.0.1:7370#", "http://[::1]:7370#x",
            "http://user@127.0.0.1:7370", "http://user:secret@[::1]:7370",
            "http://@127.0.0.1:7370",
            "http://%31%32%37.0.0.1:7370", "http://127.0.0.1%2e:7370",
            "http://2130706433:7370", "http://0x7f.0.0.1:7370", "http://127.1:7370",
            "http://0177.0.0.1:7370", "http://127.000.000.001:7370",
            "http://[0:0:0:0:0:0:0:1]:7370", "http://[::ffff:127.0.0.1]:7370",
            "http://[::1%25lo]:7370", "http://[::1]:7370\n--insecure",
            "http://127.0.0.1.:7370", "HTTP://127.0.0.1:7370", "http:127.0.0.1:7370",
            "http:/127.0.0.1:7370", "http:///127.0.0.1:7370", "http://127.0.0.1:+7370",
            "http://127.0.0.1:7370 ", "ws://127.0.0.1:7370", "http://[::1]7370",
        )
        for origin in refused:
            with self.subTest(origin=origin), self.assertRaises(Refusal):
                validate_plan(loopback_fixture(origin))
        for origin in ("http://127.0.0.1:7370", "http://[::1]:7370"):
            for cookie in ("/private/synthetic/access.cookies", "", "secret=value", True):
                plan = loopback_fixture(origin)
                plan["cookie_file"] = cookie
                with self.subTest(origin=origin, cookie=cookie), self.assertRaises(Refusal):
                    validate_plan(plan)
            plan = loopback_fixture(origin)
            del plan["cookie_file"]
            with self.subTest(origin=origin, cookie="missing"), self.assertRaises(Refusal):
                validate_plan(plan)

    def test_https_form_still_requires_its_cookie_file(self):
        self.assertEqual(validate_plan(fixture())["status"], "offline_valid_for_review")
        plan = fixture()
        plan["cookie_file"] = None
        with self.assertRaises(Refusal):
            validate_plan(plan)

    def test_kit_spells_out_both_reviewed_argv_forms_exactly(self):
        text = (HERE / "discovery-kit.md").read_text()
        blocks = text.split("```text\n")[1:]
        https = [b.split("\n```")[0] for b in blocks if '"=https"' in b.split("\n```")[0]]
        http = [b.split("\n```")[0] for b in blocks if '"=http"' in b.split("\n```")[0]]
        self.assertEqual(https, [HTTPS_ARGV])
        # The loopback argv is the HTTPS argv with only =https -> =http and the
        # cookie pair removed: every other flag and bound is the same bytes.
        self.assertEqual(len(http), 1)
        self.assertEqual(http[0], HTTPS_ARGV.replace('"=https"', '"=http"')
                         .replace('"--cookie", cookie_file, ', ""))
        self.assertNotIn("--cookie", http[0])
        self.assertIn('"--url", origin + route]', http[0])

    def test_browser_unavailable_is_an_explicit_gap_never_a_phone_pass(self):
        plan = fixture()
        plan["browser"] = {"availability": "unavailable", "host": None,
                           "account": None, "context": None,
                           "gap": "No approved supported phone context available."}
        result = validate_plan(plan)
        self.assertEqual(result["browser_reads"], 0)
        self.assertEqual(result["phone_display"], "Unverified")
        for field, value in (("availability", "unknown"), ("gap", None)):
            bad = copy.deepcopy(plan)
            bad["browser"][field] = value
            with self.assertRaises(Refusal):
                validate_plan(bad)
        plan = fixture()
        plan["browser"]["expression"] = "Notification.requestPermission()"
        with self.assertRaises(Refusal):
            validate_plan(plan)

    def test_candidate_and_every_plan_byte_are_bound_to_review_digest(self):
        plan = fixture()
        digest = validate_plan(plan)["plan_sha256"]
        plan["candidate"]["head"] = "c" * 40
        self.assertNotEqual(validate_plan(plan)["plan_sha256"], digest)
        for key, value in (("head", None), ("tree", "unknown"), ("version", "other")):
            bad = fixture()
            bad["candidate"][key] = value
            with self.assertRaises(Refusal):
                validate_plan(bad)

    def test_duplicate_json_keys_refuse(self):
        with self.assertRaises(Refusal):
            decode('{"account":"synthetic","account":"other"}')
        with self.assertRaises(Refusal):
            decode('{"bounds":{"requests":5,"requests":500}}')

    def test_cli_refuses_without_echoing_private_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text('{"account":"synthetic-private-marker"}')
            result = subprocess.run(
                ["python3", "-I", str(Path(__file__).resolve()), "--check", str(path)],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {"status": "refused", "live_authority": False})
        self.assertEqual(result.stderr, "")

    def test_shipped_template_refuses_until_private_inputs_are_known(self):
        text = (HERE / "discovery-kit.md").read_text()
        raw = text.split("```discovery-plan\n")[1].split("\n```")[0]
        with self.assertRaises(Refusal):
            validate_plan(decode(raw))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_plan(decode(args.check.read_text()))
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"status": "refused", "live_authority": False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        raise SystemExit(main())
    unittest.main()
