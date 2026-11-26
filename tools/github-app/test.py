#!/usr/bin/env python3
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import importlib.util
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
os.environ["OPENWIZ_SYNTHETIC_GITHUB"] = "1"
PERMISSIONS = {name: "read" for name in (
    "metadata", "contents", "issues", "pull_requests", "checks", "actions")}
SERVICE = dict(PERMISSIONS, contents="write", issues="write", pull_requests="write")


ROOT = HERE.parents[1]
FOLLOWING_PATHS = ("loops", "tools/github-app",
                   "tools/roadmap", "docs/ROADMAP.md")
FIXED_TARGET = re.compile(re.escape("jparker2006" + "/" + "ClosedWiz").encode(), re.IGNORECASE)
POINTER = re.compile(rb"https://github\.com/" + FIXED_TARGET.pattern + rb"/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*",
                     re.IGNORECASE)
GENERATED = re.compile(rb"<!-- roadmap:([a-z-]+):begin -->.*?<!-- roadmap:\1:end -->", re.DOTALL)


def fixed_targets(root, paths=FOLLOWING_PATHS):
    hits = []
    for top in paths:
        start = root / top
        files = [start] if start.is_file() else sorted(
            p for p in start.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        for path in files:
            data = path.read_bytes()
            if path == root / "docs/ROADMAP.md":
                data = GENERATED.sub(lambda m: b"\n" * m.group().count(b"\n"), data)
            for number, line in enumerate(data.split(b"\n"), 1):
                if FIXED_TARGET.search(POINTER.sub(b"", line)):
                    hits.append(f"{path.relative_to(root)}:{number}")
    return hits


class RepositoryTargetTests(unittest.TestCase):
    def test_planted_targets_are_found_and_generated_links_are_not(self):
        target = "jparker2006" + "/" + "ClosedWiz"
        with tempfile.TemporaryDirectory(prefix="openwiz-repo-grep-") as directory:
            root = Path(directory)
            for name, text in {
                    "loops/a.json": '{"repo": "%s"}\n' % target.lower(),
                    "tools/roadmap/deep/b.py": "clean\nURL = 'https://github.com/%s'\n" % target,
                    "tools/stall-alarm/README.md": (
                        "synthetic-owner/synthetic-repo only\n"
                        "ruling: https://github.com/%s/issues/9#issuecomment-99\n"
                        "a ticket: https://github.com/%s/issues/9\n" % (target, target)),
                    "docs/ROADMAP.md": (
                        "<!-- roadmap:now-next:begin -->\nhttps://github.com/%s/milestone/1\n"
                        "<!-- roadmap:now-next:end -->\nwritten by hand: %s\n" % (target, target)),
            }.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            self.assertEqual(fixed_targets(root, ("loops", "tools/roadmap", "tools/stall-alarm",
                                                  "docs/ROADMAP.md")),
                             ["loops/a.json:1", "tools/roadmap/deep/b.py:2",
                              "tools/stall-alarm/README.md:3", "docs/ROADMAP.md:4"])

    def test_no_owned_file_names_the_repository_as_a_fixed_target(self):
        self.assertEqual(fixed_targets(ROOT), [])


class ManifestTests(unittest.TestCase):
    def test_template_names_no_repository(self):
        manifest = json.loads((HERE / "manifest.json").read_text())
        self.assertNotIn("url", manifest)
        self.assertEqual(manifest["hook_attributes"], {"active": False})

    def test_manifest_is_exactly_the_service_profile(self):
        manifest = json.loads((HERE / "manifest.json").read_text())
        self.assertEqual(manifest["default_permissions"], SERVICE)
        self.assertEqual(manifest["default_events"], [])
        self.assertIs(manifest["public"], False)


@contextmanager
def fake_github(pem):
    calls = []
    behavior = {"status": 201, "permissions": PERMISSIONS, "converted": SERVICE,
                "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "token": "synthetic-installation-token", "drop": False,
                "installations": {2002: "synthetic-owner"},
                "read_profile": {"repository_selection": "selected", "repositories": [
                    {"full_name": "synthetic-owner/work"}]}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            calls.append((self.path, dict(self.headers), b""))
            found = re.fullmatch(r"/app/installations/([0-9]+)", self.path)
            if self.path == "/app":
                status, result = 200, {"id": 1001, "slug": "synthetic-app",
                                       "owner": {"login": behavior.get("app_owner", "synthetic-owner")},
                                       "permissions": behavior.get("app_permissions", SERVICE)}
            elif self.path == "/app/installations":
                status, result = 200, [{"id": i, "app_id": 1001, "account": {"login": login},
                                        "repository_selection": behavior.get("selection", "selected"),
                                        "permissions": SERVICE}
                                       for i, login in behavior["installations"].items()]
            elif found and int(found.group(1)) in behavior["installations"]:
                status, result = 200, {"id": int(found.group(1)), "app_id": 1001, "account": {
                    "login": behavior["installations"][int(found.group(1))]},
                    "repository_selection": behavior.get("selection", "selected")}
            else:
                status, result = 404, {"message": pem.decode()}
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.path, dict(self.headers), body))
            if self.path == "/app-manifests/synthetic-code/conversions":
                if behavior["drop"]:
                    self.connection.shutdown(2)
                    return
                result = {"id": 1001, "pem": pem.decode(), "slug": "synthetic-app",
                          "owner": {"login": behavior.get("app_owner", "synthetic-owner")},
                          "html_url": "https://github.com/apps/synthetic-app",
                          "permissions": behavior["converted"]}
            elif self.path == "/app/installations/2002/access_tokens":
                result = {"token": behavior["token"],
                          "expires_at": behavior["expires_at"],
                          "permissions": behavior["permissions"]}
                result.update(behavior.get("read_profile", {}))
            else:
                result = {"message": pem.decode()}
            if behavior["status"] != 201:
                result = {"message": pem.decode()}
            self.send_response(behavior["status"])
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_DELETE(self):
            calls.append((self.path, dict(self.headers), b""))
            self.send_response(204)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, behavior
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def mints(calls):
    return [c for c in calls if c[0].endswith("/access_tokens")]


def revoked(calls):
    return [c[1].get("Authorization") for c in calls if c[0] == "/installation/token"]


OWNER_READS = ["/app", "/app/installations/2002"]


class KeyFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="openwiz-app-fixture-")
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.app = self.state / "service/app"
        self.app.mkdir(parents=True, mode=0o700)
        for path in (self.state, self.state / "service"):
            path.chmod(0o700)
        self.key = self.app / "private-key.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt",
                        "rsa_keygen_bits:2048", "-out", str(self.key)],
                       check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.key.chmod(0o600)
        self.pem = self.key.read_bytes()
        self.config = self.app / "app.json"
        self.config.write_text('{"app_id":1001}')
        self.config.chmod(0o600)

    def assert_no_key(self, *outputs):
        # SECURITY: a failure names the output, never prints it; it may hold a runner's secrets.
        needles = [self.pem] + self.pem.splitlines()[1:-1]
        for number, output in enumerate(outputs, 1):
            if isinstance(output, str):
                output = output.encode()
            for needle in needles:
                self.assertFalse(needle in output, f"the key reached output {number}")

    def token(self, endpoint, device_now=None, env=None):
        self.assertTrue((HERE / "mint-token.py").is_file())
        command = ["python3", str(HERE / "mint-token.py")]
        if device_now is not None:
            bootstrap = """
import datetime
from pathlib import Path
import runpy
import sys
from unittest.mock import patch
script, instant, *args = sys.argv[1:]
fixed = datetime.datetime.fromisoformat(instant)
class DeviceClock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)
sys.path.insert(0, str(Path(script).parent))
sys.argv = [script, *args]
with patch("datetime.datetime", DeviceClock), patch("time.time", return_value=fixed.timestamp()):
    runpy.run_path(script, run_name="__main__")
"""
            command = ["python3", "-c", bootstrap, str(HERE / "mint-token.py"), device_now]
        return subprocess.run(command + [
            "--state-dir", str(self.state), "--installation-id", "2002", "--api-base", endpoint,
            "--repository", "synthetic-owner/work"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15,
            env=env or {k: v for k, v in os.environ.items() if not k.startswith("OPENWIZ_GITHUB_APP_")})


class TokenTests(KeyFixture):
    def test_fresh_token_allows_clock_skew_but_expired_or_far_future_refused(self):
        cases = [
            ("2026-01-01T00:59:59Z", 1767229199),
            ("2026-01-01T01:00:00Z", 1767229200),
            ("2026-01-01T01:00:01Z", 1767229201),
            ("2026-01-01T01:00:02Z", 1767229202),
            ("2026-01-01T01:00:05Z", 1767229205),
            ("2026-01-01T01:04:59Z", 1767229499),
            ("2026-01-01T01:05:00Z", 1767229500),
            ("2026-01-01T01:05:01Z", None),
            ("2026-01-01T00:00:00Z", None),
            ("2025-12-31T23:59:59Z", None),
            ("2099-01-01T00:00:00Z", None),
        ]
        with fake_github(self.pem) as (endpoint, calls, behavior):
            for expiry, expected_expiry in cases:
                with self.subTest(expiry=expiry):
                    behavior["expires_at"] = expiry
                    result = self.token(endpoint, device_now="2026-01-01T00:00:00+00:00")
                    if expected_expiry is not None:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout,
                                         f"synthetic-installation-token\n{expected_expiry}\n".encode())
                        self.assertEqual(result.stderr, b"")
                    else:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertEqual(result.stdout, b"")
                        self.assertEqual(result.stderr,
                                         b"App token refused: check PC state permissions, App installation and GitHub availability.\n")
                    self.assert_no_key(result.stdout, result.stderr)
            self.assertEqual(len(mints(calls)), 11)
            self.assert_no_key(repr(calls))

    def test_signs_real_jwt_and_prints_only_read_token(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["expires_at"] = "2026-01-01T01:00:00Z"
            result = self.token(endpoint, device_now="2026-01-01T00:00:00+00:00")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"synthetic-installation-token\n1767229200\n")
        self.assertEqual(result.stderr, b"")
        self.assertEqual([c[0] for c in calls], OWNER_READS + ["/app/installations/2002/access_tokens"])
        path, headers, body = calls[2]
        self.assertEqual(json.loads(body), {"permissions": PERMISSIONS, "repositories": ["work"]})
        jwt = headers["Authorization"].removeprefix("Bearer ")
        header, payload, signature = jwt.split(".")
        decode = lambda part: base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))
        self.assertEqual(json.loads(decode(header)), {"alg": "RS256", "typ": "JWT"})
        claims = json.loads(decode(payload))
        self.assertEqual(claims["iss"], "1001")
        self.assertGreater(claims["exp"], claims["iat"])
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)
        public = Path(self.tmp.name) / "public.pem"
        public.write_bytes(subprocess.run(
            ["openssl", "pkey", "-in", str(self.key), "-pubout"],
            check=True, capture_output=True).stdout)
        sig = Path(self.tmp.name) / "signature"
        sig.write_bytes(decode(signature))
        verified = subprocess.run(["openssl", "dgst", "-sha256", "-verify", str(public),
                                   "-signature", str(sig)],
                                  input=f"{header}.{payload}".encode(), capture_output=True)
        self.assertEqual(verified.returncode, 0)
        self.assert_no_key(result.stdout, result.stderr, repr(calls))
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)

    def test_unsafe_key_or_state_refused_before_network(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            for path, mode in ((self.key, 0o644), (self.app, 0o755),
                               (self.state, 0o755), (self.config, 0o644)):
                with self.subTest(path=path):
                    old = path.stat().st_mode & 0o777
                    path.chmod(mode)
                    result = self.token(endpoint)
                    path.chmod(old)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assert_no_key(result.stderr)
            original = self.key.with_suffix(".original")
            self.key.rename(original)
            self.key.symlink_to(original)
            result = self.token(endpoint)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, [])

    def test_hostile_errors_bad_permissions_expiry_and_token_are_silent(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            original = behavior.copy()
            cases = [{"status": 403}, {"permissions": {"issues": "write"}},
                     {"permissions": {"unknown": "read"}},
                     {"expires_at": "2000-01-01T00:00:00Z"},
                     {"expires_at": "2099-01-01T00:00:00Z"},
                     {"token": self.pem.decode()}, {"token": ""}]
            for change in cases:
                with self.subTest(change=list(change)):
                    behavior.update(original)
                    behavior.update(change)
                    result = self.token(endpoint)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assert_no_key(result.stderr)
            self.assertEqual(len(mints(calls)), len(cases))
        self.assertEqual(sorted(p.name for p in self.app.iterdir()),
                         ["app.json", "private-key.pem"])


class ReadProfileTests(KeyFixture):
    SELECTED = {"repository_selection": "selected", "repositories": [
        {"full_name": "synthetic-owner/other"}, {"full_name": "Synthetic-Owner/Work"}]}

    def read_token(self, endpoint, *repositories, mode=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENWIZ_GITHUB_APP_")}
        if mode is not None:
            env["OPENWIZ_GITHUB_APP_MODE"] = mode
        return subprocess.run(["python3", str(HERE / "mint-token.py"), "--state-dir", str(self.state),
                               "--installation-id", "2002", "--api-base", endpoint,
                               *[a for r in repositories for a in ("--repository", r)]],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, env=env)

    def test_no_repository_refuses_without_any_request(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            result = self.read_token(endpoint)
        self.assertEqual((len(calls), result.returncode, result.stdout, result.stderr),
                         (0, 1, b"", b"App token refused: --repository is required.\n"))

    def test_read_token_names_exact_selection_and_its_expiry(self):
        expiry = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=59)
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior.update(read_profile=self.SELECTED, expires_at=expiry.isoformat())
            result = self.read_token(endpoint, "synthetic-owner/work", "synthetic-owner/other")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().splitlines(),
                         ["synthetic-installation-token", str(int(expiry.timestamp()))])
        self.assertEqual([c[0] for c in calls], OWNER_READS + ["/app/installations/2002/access_tokens"])
        self.assertEqual(json.loads(calls[2][2]),
                         {"permissions": PERMISSIONS, "repositories": ["other", "work"]})

    def test_read_token_refuses_foreign_unselected_expired_or_mixed_owner(self):
        foreign = {"repository_selection": "selected", "repositories": [
            {"full_name": "synthetic-elsewhere/work"}, {"full_name": "synthetic-owner/other"}]}
        cases = [({"read_profile": foreign}, ("synthetic-owner/work", "synthetic-owner/other")),
                 ({"read_profile": {"repository_selection": "all"}}, ("synthetic-owner/work",)),
                 ({"read_profile": self.SELECTED}, ("synthetic-owner/work",)),
                 ({"read_profile": self.SELECTED, "status": 422}, ("synthetic-owner/work", "synthetic-owner/other")),
                 ({"read_profile": self.SELECTED, "expires_at": "2000-01-01T00:00:00Z"},
                  ("synthetic-owner/work", "synthetic-owner/other")),
                 ({"read_profile": self.SELECTED}, ("synthetic-owner/work", "synthetic-elsewhere/other")),
                 ({"read_profile": self.SELECTED}, ("synthetic-owner/work", "synthetic-owner/work"))]
        with fake_github(self.pem) as (endpoint, calls, behavior):
            original = behavior.copy()
            for change, repositories in cases:
                with self.subTest(change=change, repositories=repositories):
                    behavior.clear()
                    behavior.update(original, **change)
                    result = self.read_token(endpoint, *repositories)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(result.stderr,
                                     b"App token refused: check PC state permissions, App installation and GitHub availability.\n")
            self.assertEqual(len(calls) - len(revoked(calls)), 3 * (len(cases) - 2))
            self.assertEqual(len(revoked(calls)), 4, "each token refused after minting is revoked")

    def test_read_token_is_bound_to_the_app_owner_or_the_named_factory_installations(self):
        text = (HERE.parent.parent / "contracts/github-identity.v1.md").read_text()
        pin = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        named = [(i["account"], r) for i in pin["installations"] for r in i["repositories"]]
        cross = next((a, r) for a, r in named if a != named[-1][0])
        owner = named[-1][0]
        cases = [
            (None, "synthetic-owner", "synthetic-owner", "synthetic-owner/work", True),
            (None, "synthetic-elsewhere", "synthetic-owner", "synthetic-owner/work", False),
            ("user", "synthetic-elsewhere", "synthetic-owner", "synthetic-owner/work", False),
            (None, owner, cross[0], cross[1], False),
            ("factory", owner, cross[0], cross[1], True),
            ("factory", owner, owner, named[-1][1], True),
            ("factory", owner, cross[0], cross[0] + "/synthetic-unnamed", False),
            ("factory", owner, "synthetic-owner", "synthetic-owner/work", False),
            ("public", "synthetic-owner", "synthetic-owner", "synthetic-owner/work", False),
            ("", "synthetic-owner", "synthetic-owner", "synthetic-owner/work", False)]
        with fake_github(self.pem) as (endpoint, calls, behavior):
            original = behavior.copy()
            for mode, app_owner, account, repository, minted in cases:
                with self.subTest(mode=mode, app_owner=app_owner, account=account, repository=repository):
                    behavior.clear()
                    behavior.update(original, app_owner=app_owner, installations={2002: account},
                                    read_profile={"repository_selection": "selected",
                                                  "repositories": [{"full_name": repository}]})
                    before = len(mints(calls))
                    result = self.read_token(endpoint, repository, mode=mode)
                    if minted:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.decode().splitlines()[0], "synthetic-installation-token")
                    else:
                        self.assertEqual((result.returncode, result.stdout), (1, b""))
                        self.assertEqual(result.stderr, b"App token refused: check PC state permissions, "
                                                        b"App installation and GitHub availability.\n")
                        self.assertEqual(len(mints(calls)), before)


class GuardTests(KeyFixture):
    def test_manifest_rejects_each_write_and_unknown_permission(self):
        copy = Path(self.tmp.name) / "tools"
        shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns("__pycache__"))
        path = copy / "manifest.json"
        original = json.loads(path.read_text())
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            for name in (*PERMISSIONS, "unknown"):
                with self.subTest(permission=name):
                    value = dict(original, default_permissions=dict(PERMISSIONS, **{name: "write"}))
                    path.write_text(json.dumps(value))
                    result = subprocess.run([
                        "python3", str(copy / "mint-token.py"), "--state-dir", str(self.state),
                        "--installation-id", "2002", "--api-base", endpoint,
                        "--repository", "synthetic-owner/work"],
                        capture_output=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                    self.assert_no_key(result.stderr)
            self.assertEqual(calls, [])

    def test_invalid_local_records_and_key_never_leak(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            for content in (b'{"app_id":1001,"app_id":2002}', b'[1001]',
                            b'{"app_id":true}', b'{"app_id":1001,"extra":null}'):
                self.config.write_bytes(content)
                result = self.token(endpoint)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assert_no_key(result.stderr)
            self.config.write_text('{"app_id":1001}')
            self.key.write_bytes(b'not-a-key-synthetic-secret')
            result = self.token(endpoint)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'not-a-key-synthetic-secret', result.stdout + result.stderr)
            self.assertEqual(calls, [])

    def test_remote_api_overrides_and_redirects_refused(self):
        for endpoint in ("http://example.invalid", "https://example.invalid",
                         "http://localhost:1", "http://127.0.0.1:1/path",
                         "http://user@127.0.0.1:1", "http://127.0.0.1:1#fragment"):
            with self.subTest(endpoint=endpoint):
                result = self.token(endpoint)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["status"] = 302
            result = self.token(endpoint)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, b"")
            self.assertEqual([c[0] for c in calls], OWNER_READS + ["/app/installations/2002/access_tokens"])
            self.assert_no_key(result.stderr)


class HardeningTests(KeyFixture):
    def test_a_loopback_api_base_is_refused_without_the_synthetic_setting(self):
        refused = (b"App token refused: check PC state permissions, App installation and "
                   b"GitHub availability.\n")
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            bare = {k: v for k, v in os.environ.items()
                    if k != "OPENWIZ_SYNTHETIC_GITHUB" and not k.startswith("OPENWIZ_GITHUB_APP_")}
            result = self.token(endpoint, env=bare)
            self.assertEqual((result.returncode, len(calls), result.stdout, result.stderr),
                             (1, 0, b"", refused))
            sent = self.token(endpoint, env=dict(bare, OPENWIZ_SYNTHETIC_GITHUB="1"))
            self.assertEqual(sent.returncode, 0, sent.stderr)
            self.assertTrue(any(headers.get("Authorization", "").startswith("Bearer ")
                                for _path, headers, _body in calls))
        saved = os.environ.pop("OPENWIZ_SYNTHETIC_GITHUB", None)
        try:
            spec = importlib.util.spec_from_file_location("app_610", HERE / "app.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.api_base("https://api.github.com"), "https://api.github.com")
            with self.assertRaises(ValueError):
                module.api_base("http://127.0.0.1:9")
        finally:
            if saved is not None:
                os.environ["OPENWIZ_SYNTHETIC_GITHUB"] = saved

    def test_a_token_refused_after_minting_is_revoked_and_a_good_one_kept(self):
        later = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        for name, change in (("write permissions", {"permissions": SERVICE}), ("too long", {"expires_at": later}),
                             ("other repository", {"read_profile": {"repository_selection": "selected",
                                                                     "repositories": [{"full_name": "synthetic-owner/x"}]}})):
            with self.subTest(name), fake_github(self.pem) as (endpoint, calls, behavior):
                behavior.update(change)
                result = self.token(endpoint)
                self.assertEqual((result.returncode, result.stdout), (1, b""))
                self.assertEqual(revoked(calls), ["Bearer " + behavior["token"]])
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            self.assertEqual(self.token(endpoint).returncode, 0)
            self.assertEqual(revoked(calls), [])

    def with_openssl(self, endpoint, program, env):
        bootstrap = ("import runpy, sys; sys.path.insert(0, sys.argv[1]); import app; app.OPENSSL = sys.argv[2]; "
                     "sys.argv = sys.argv[3:]; runpy.run_path(sys.argv[0], run_name='__main__')")
        return subprocess.run(["python3", "-c", bootstrap, str(HERE), program, str(HERE / "mint-token.py"),
                               "--state-dir", str(self.state), "--installation-id", "2002", "--api-base", endpoint,
                               "--repository", "synthetic-owner/work"], capture_output=True, timeout=15, env=env)

    def test_openssl_runs_by_absolute_path_with_a_fixed_environment_or_not_at_all(self):
        tools, seen = Path(self.tmp.name) / "bin", Path(self.tmp.name) / "seen"
        tools.mkdir()
        (tools / "openssl").write_text(
            f"#!{sys.executable}\nimport json, os, sys\nopen({str(seen)!r}, 'a').write(json.dumps(dict(os.environ)) + '\\n')\n"
            "os.execv('/usr/bin/openssl', ['/usr/bin/openssl', *sys.argv[1:]])\n")
        (tools / "openssl").chmod(0o700)
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENWIZ_GITHUB_APP_")}
        env.update(PATH=f"{tools}:{env['PATH']}", SYNTHETIC_PLANTED="planted")
        with fake_github(self.pem) as (endpoint, _calls, _behavior):
            self.assertEqual(self.token(endpoint, env=env).returncode, 0)
            self.assertFalse(seen.exists(), "openssl was taken from PATH")
            self.assertEqual(self.with_openssl(endpoint, str(tools / "openssl"), env).returncode, 0)
            environment, = [json.loads(line) for line in seen.read_text().splitlines()]
            self.assertFalse({"PATH", "SYNTHETIC_PLANTED"} & set(environment), "openssl inherited the environment")
            missing = self.with_openssl(endpoint, str(tools / "absent"), env)
            self.assertEqual((missing.returncode, missing.stdout), (1, b""))
            self.assertIn(b"App token refused", missing.stderr)
            self.assertEqual(len(seen.read_text().splitlines()), 1)

    def test_an_interrupted_key_write_leaves_no_key_and_never_replaces_one(self):
        self.key.unlink()
        crash = ("import os, sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); import app\n"
                 "directory = app.app_directory(Path(sys.argv[2]))\nos.fsync = lambda fd: os._exit(9)\n"
                 "app.save_file(directory, 'private-key.pem', b'synthetic partial key')\n")
        done = subprocess.run(["python3", "-c", crash, str(HERE), str(self.state)], capture_output=True, timeout=15)
        self.assertEqual(done.returncode, 9, done.stderr)
        self.assertFalse(self.key.exists(), "a crash mid-write left a key at its final name")
        spec = importlib.util.spec_from_file_location("app_609", HERE / "app.py")
        app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app)
        directory = app.app_directory(self.state)
        try:
            app.save_file(directory, "private-key.pem", self.pem)
            with self.assertRaises(FileExistsError):
                app.save_file(directory, "private-key.pem", b"synthetic other key")
        finally:
            os.close(directory)
        self.assertEqual((self.key.read_bytes(), self.key.stat().st_mode & 0o777, self.key.stat().st_nlink),
                         (self.pem, 0o600, 1))


class SetupCheckOwnerBoundary(KeyFixture):
    def check(self, endpoint):
        spec = importlib.util.spec_from_file_location("install_setup_606", HERE.parent / "install/setup/setup.py")
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        return setup.check_app(self.state, {"repository": "synthetic-owner/synthetic-repo"}, None, endpoint)

    def test_the_setup_check_verifies_only_the_app_owners_installation(self):
        soon = (datetime.now(timezone.utc) + timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for owner, verified in (("synthetic-owner", True), ("synthetic-elsewhere", False)):
            with self.subTest(owner=owner), fake_github(self.pem) as (endpoint, calls, behavior):
                behavior.update(app_owner=owner, permissions=SERVICE, expires_at=soon, read_profile={
                    "repository_selection": "selected",
                    "repositories": [{"full_name": "synthetic-owner/synthetic-repo"}]})
                code, ids = self.check(endpoint)
                if verified:
                    self.assertEqual((code, ids), ("app_verified", {"app_id": 1001, "installation_id": 2002}))
                else:
                    self.assertEqual(code, "app_not_installed")
                    self.assertEqual(mints(calls), [])

    def test_the_proof_token_is_revoked_and_must_cover_selected_repositories_only(self):
        soon = (datetime.now(timezone.utc) + timedelta(minutes=50)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for selection, code in (("selected", "app_verified"), ("all", "app_wrong_repository")):
            with self.subTest(selection=selection), fake_github(self.pem) as (endpoint, calls, behavior):
                behavior.update(permissions=SERVICE, expires_at=soon, read_profile={
                    "repository_selection": selection,
                    "repositories": [{"full_name": "synthetic-owner/synthetic-repo"}]})
                self.assertEqual(self.check(endpoint)[0], code)
                self.assertEqual(revoked(calls), ["Bearer " + behavior["token"]])


class Form(HTMLParser):
    def __init__(self):
        super().__init__()
        self.values = {}
        self.action = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.action = attrs["action"]
        if tag == "input":
            self.values[attrs["name"]] = attrs["value"]


class SetupTests(KeyFixture):
    def preview(self, endpoint, repo=("--repo", "synthetic-owner/synthetic-repo"), tool=HERE, extra=(),
                phase="proposed"):
        result = subprocess.run([
            "python3", str(tool / "setup.py"), "--state-dir", str(self.state),
            "--api-base", endpoint, "--port", "0", *repo, *extra], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        operation = json.loads(result.stdout)
        self.assertEqual((operation["kind"], operation["phase"]), ("connect_app", phase))
        return operation

    def setup_state(self):
        return json.loads((self.state / "setup/state.json").read_text())

    def start(self, endpoint, repo=("--repo", "synthetic-owner/synthetic-repo"), tool=HERE, fresh=True):
        if fresh:
            self.key.unlink(missing_ok=True)
            self.config.unlink(missing_ok=True)
            shutil.rmtree(self.state / "setup", ignore_errors=True)
        operation = self.preview(endpoint, repo, tool)
        self.operation = operation["operation_id"]
        process = subprocess.Popen([
            "python3", str(tool / "setup.py"), "--state-dir", str(self.state),
            "--api-base", endpoint, "--port", "0", *repo, "--yes", "--operation", self.operation],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, umask=0)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            self.assertTrue(selector.select(10), "setup did not announce localhost URL")
            line = process.stdout.readline()
        finally:
            selector.close()
        self.assertRegex(line, rb"http://127\.0\.0\.1:[0-9]+/start/[a-zA-Z0-9_-]+")
        url = re.search(rb"http://[^\s]+", line).group().decode()
        with urllib.request.urlopen(url) as response:
            page = response.read()
        form = Form()
        form.feed(page.decode())
        manifest = json.loads(form.values["manifest"]) if "manifest" in form.values else None
        return process, line, page, form, manifest

    def clone(self, origin):
        clone = Path(self.tmp.name) / "clone"
        shutil.rmtree(clone, ignore_errors=True)
        tool = clone / "tools/github-app"
        tool.mkdir(parents=True)
        for name in ("app.py", "setup.py", "manifest.json"):
            shutil.copy(HERE / name, tool / name)
        (clone / "tools/install/setup").mkdir(parents=True)
        shutil.copy(HERE.parent / "install/setup/store.py", clone / "tools/install/setup/store.py")
        subprocess.run(["git", "init", "-q", str(clone)], check=True)
        if origin is not None:
            subprocess.run(["git", "-C", str(clone), "remote", "add", "origin", origin], check=True)
        return tool

    def test_manifest_names_the_repository_setting(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, *_rest, manifest = self.start(endpoint, ("--repo", "synthetic-owner/other-repo"))
            process.kill()
            process.communicate(timeout=10)
        self.assertEqual(manifest["url"], "https://github.com/synthetic-owner/other-repo")
        self.assertEqual(manifest["hook_attributes"],
                         {"url": "https://github.com/synthetic-owner/other-repo", "active": False})
        self.assertEqual(calls, [])

    def test_the_setup_page_has_a_44_pixel_button_a_viewport_and_a_language(self):
        with fake_github(self.pem) as (endpoint, _calls, _behavior):
            process, line, _page, _form, _manifest = self.start(endpoint)
            with urllib.request.urlopen(re.search(rb"http://[^\s]+", line).group().decode()) as response:
                policy, again = response.headers["Content-Security-Policy"], response.read().decode()
            process.kill()
            process.communicate(timeout=10)
        self.assertTrue(again.startswith('<!doctype html><html lang="en"><meta charset="utf-8">'
                                         '<meta name="viewport" content="width=device-width, initial-scale=1">'), again)
        nonce, rules = re.search(r'<style nonce="([A-Za-z0-9_-]{16,})">([^<]*)</style>', again).groups()
        self.assertIn(f"style-src 'nonce-{nonce}'", policy)
        self.assertRegex(rules, r"button\{[^}]*min-height:44px;[^}]*min-width:44px")
        self.assertIn('<button type="submit">Create the App on GitHub</button>', again)

    def test_manifest_follows_the_clone_by_default(self):
        for origin, repo in (
                ("https://github.com/synthetic-owner/clone-repo.git", "synthetic-owner/clone-repo"),
                ("https://github.com/synthetic-owner/clone.repo", "synthetic-owner/clone.repo"),
                ("git@github.com:synthetic-owner/ssh-repo.git", "synthetic-owner/ssh-repo"),
                ("ssh://git@github.com/synthetic-owner/ssh-url", "synthetic-owner/ssh-url")):
            with self.subTest(origin=origin), fake_github(self.pem) as (endpoint, calls, _behavior):
                process, *_rest, manifest = self.start(endpoint, (), self.clone(origin))
                process.kill()
                process.communicate(timeout=10)
                self.assertEqual(manifest["url"], "https://github.com/" + repo)
                self.assertEqual(manifest["hook_attributes"],
                                 {"url": "https://github.com/" + repo, "active": False})
                self.assertEqual(calls, [])

    def test_unknown_repository_is_refused_before_setup_starts(self):
        cases = [("--repo", bad) for bad in ("synthetic-owner", "a/b/c", "synthetic owner/repo",
                                             "https://github.com/synthetic-owner/repo", "../repo")]
        cases += [(None, origin) for origin in (
            None, "https://example.invalid/synthetic-owner/repo.git",
            "https://github.com/synthetic-owner", "https://github.com/synthetic-owner/repo/extra",
            "/srv/synthetic/repo.git")]
        self.key.unlink()
        self.config.unlink()
        for flag, value in cases:
            with self.subTest(flag=flag, value=value), fake_github(self.pem) as (endpoint, calls, _behavior):
                tool = HERE if flag else self.clone(value)
                result = subprocess.run(
                    ["python3", str(tool / "setup.py"), "--state-dir", str(self.state),
                     "--api-base", endpoint, "--port", "0", *([flag, value] if flag else [])],
                    capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(calls, [])
                self.assertFalse(self.key.exists())

    def test_manifest_callback_stores_key_without_disclosing_it(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, line, page, form, manifest = self.start(endpoint)
            self.assertEqual(manifest["default_permissions"], SERVICE)
            self.assertEqual(manifest["setup_url"], manifest["redirect_url"].replace("/callback", "/installed"))
            self.assertTrue(form.action.startswith("https://github.com/settings/apps/new?"))
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            callback = manifest["redirect_url"]
            with self.assertRaises(urllib.error.HTTPError) as bad:
                urllib.request.urlopen(callback + "?code=synthetic-code&state=wrong")
            self.assertEqual(bad.exception.code, 400)
            self.assertEqual(calls, [])
            with urllib.request.urlopen(callback + "?" + urllib.parse.urlencode(
                    {"code": "synthetic-code", "state": state})) as response:
                answer = response.read()
            installed = manifest["setup_url"] + "?" + urllib.parse.urlencode(
                {"installation_id": "2002", "setup_action": "install", "state": state})
            with urllib.request.urlopen(installed) as response:
                answer += response.read()
            stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions",
                                                 "/app/installations/2002"])
        state_file = self.setup_state()
        self.assertEqual(state_file["app"], {"app_id": 1001, "installation_id": 2002})
        self.assertEqual([(o["operation_id"], o["phase"]) for o in state_file["operations"]],
                         [(self.operation, "applied")])
        self.assertEqual(self.key.read_bytes(), self.pem)
        self.assertEqual(self.key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.config.read_text()), {"app_id": 1001})
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertIn(b"https://github.com/apps/synthetic-app/installations/new?state=", stdout)
        self.assert_no_key(line, page, answer, stdout, stderr, repr(calls),
                           (self.state / "setup/state.json").read_bytes())

    def test_installation_on_the_repository_owner_must_also_be_the_app_owner(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["app_owner"] = "synthetic-elsewhere"
            process, line, page, form, manifest = self.start(endpoint)
            self.assertIs(manifest["public"], False)
            self.assertEqual(manifest["name"], "OpenWiz synthetic-owner")
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            with urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                    {"code": "synthetic-code", "state": state})) as response:
                answer = response.read()
            with self.assertRaises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(manifest["setup_url"] + "?" + urllib.parse.urlencode(
                    {"installation_id": "2002", "setup_action": "install", "state": state}))
            self.assertEqual(refused.exception.code, 400)
            process.kill()
            stdout, stderr = process.communicate(timeout=10)
        self.assertIsNone(self.setup_state()["app"])
        self.assertNotIn(b"captured", stdout)
        self.assert_no_key(line, page, answer, stdout, stderr, repr(calls))

    def test_failed_exchange_never_echoes_response_or_writes_key(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["status"] = 403
            process, line, page, form, manifest = self.start(endpoint)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                    {"code": "synthetic-code", "state": state}))
            answer = error.exception.read()
            stdout, stderr = process.communicate(timeout=10)
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(self.key.exists())
        self.assertEqual(len(calls), 1)
        self.assert_no_key(line, page, answer, stdout, stderr, repr(calls))

    def test_conversion_read_only_or_unknown_permissions_never_save_key(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            for granted in (PERMISSIONS, {"issues": "write"}, dict(SERVICE, unknown="read"), {}):
                with self.subTest(permissions=granted):
                    behavior["converted"] = granted
                    process, line, page, form, manifest = self.start(endpoint)
                    state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                            {"code": "synthetic-code", "state": state}))
                    answer = error.exception.read()
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertNotEqual(process.returncode, 0)
                    self.assertFalse(self.key.exists())
                    self.assertFalse(self.config.exists())
                    self.assert_no_key(line, page, answer, stdout, stderr)
            self.assertEqual(len(calls), 4)

    def test_state_inside_bare_repository_is_refused(self):
        bare = Path(self.tmp.name) / "bare.git"
        bare.mkdir()
        (bare / "HEAD").write_text("ref: refs/heads/main\n")
        (bare / "config").write_text("[core]\nrepositoryformatversion = 0\nbare = true\n")
        (bare / "objects").mkdir()
        (bare / "refs").mkdir()
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process = subprocess.Popen([
                "python3", str(HERE / "setup.py"), "--state-dir", str(bare / "state"),
                "--api-base", endpoint, "--port", "0", "--repo", "synthetic-owner/synthetic-repo"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            try:
                self.assertTrue(selector.select(10))
                line = process.stdout.readline()
            finally:
                selector.close()
                if process.poll() is None:
                    process.terminate()
                stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(line, b"", "setup started inside a bare repository")
            self.assertFalse((bare / "state").exists())
            self.assertEqual(calls, [])
            self.assert_no_key(line, stdout, stderr)

    def test_existing_key_is_never_overwritten(self):
        result = subprocess.run(["python3", str(HERE / "setup.py"),
                                 "--state-dir", str(self.state),
                                 "--repo", "synthetic-owner/synthetic-repo"],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing new is registered", " ".join(json.loads(result.stdout)["effects"]))
        self.assertEqual(self.key.read_bytes(), self.pem)
        self.assert_no_key(result.stdout, result.stderr)
        self.config.unlink()
        result = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                 "--repo", "synthetic-owner/synthetic-repo"], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.key.read_bytes(), self.pem)

    def run_yes(self, endpoint, operation, extra=()):
        return subprocess.Popen([
            "python3", str(HERE / "setup.py"), "--state-dir", str(self.state), "--api-base", endpoint,
            "--port", "0", "--repo", "synthetic-owner/synthetic-repo", "--yes", "--operation", operation,
            *extra], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def announced(self, process):
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            self.assertTrue(selector.select(10), "setup did not announce its URL")
            return re.search(rb"http://[^\s]+", process.stdout.readline()).group().decode()
        finally:
            selector.close()

    def test_lost_conversion_reply_is_uncertain_and_never_registered_again(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["drop"] = True
            process, line, page, form, manifest = self.start(endpoint)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                    {"code": "synthetic-code", "state": state}))
            stdout, stderr = process.communicate(timeout=10)
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual([(o["phase"]) for o in self.setup_state()["operations"]], ["uncertain"])
            self.assertFalse(self.key.exists())
            for extra in ((), ("--yes", "--operation", self.operation)):
                result = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                         "--api-base", endpoint, "--port", "0",
                                         "--repo", "synthetic-owner/synthetic-repo", *extra],
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 6, result.stderr)
                self.assertIn(self.operation.encode(), result.stderr)
                self.assertEqual(result.stdout, b"")
            self.assertEqual(len(calls), 1)
            after = self.preview(endpoint, extra=("--after-uncertain", self.operation))
            self.assertNotEqual(after["operation_id"], self.operation)
            self.assertIn(self.operation, " ".join(after["effects"]))
            self.assertEqual([o["phase"] for o in self.setup_state()["operations"]], ["uncertain", "proposed"])
            self.assert_no_key(stdout, stderr, repr(calls))

    def test_interrupted_setup_resumes_without_a_second_registration(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            process, line, page, form, manifest = self.start(endpoint)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                {"code": "synthetic-code", "state": state})).read()
            process.kill()
            process.communicate(timeout=10)
            self.assertEqual(self.setup_state()["operations"][0]["phase"], "uncertain")
            self.assertTrue(self.key.exists())
            again = self.preview(endpoint, phase="uncertain")
            self.assertEqual(again["operation_id"], self.operation)
            resumed = self.run_yes(endpoint, again["operation_id"])
            url = self.announced(resumed)
            with urllib.request.urlopen(url) as response:
                link = re.search(rb'href="([^"]+)"', response.read()).group(1).decode().replace("&amp;", "&")
            self.assertTrue(link.startswith("https://github.com/apps/synthetic-app/installations/new?state="))
            nonce = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)["state"][0]
            base = url.split("/start/")[0]
            for bad in ({"installation_id": "2002", "setup_action": "install", "state": "wrong"},
                        {"installation_id": "9009", "setup_action": "install", "state": nonce},
                        {"installation_id": "2002", "setup_action": "delete", "state": nonce}):
                with self.assertRaises(urllib.error.HTTPError) as refused:
                    urllib.request.urlopen(base + "/installed?" + urllib.parse.urlencode(bad))
                self.assertEqual(refused.exception.code, 400)
            behavior["installations"][3003] = "another-owner"
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(base + "/installed?" + urllib.parse.urlencode(
                    {"installation_id": "3003", "setup_action": "install", "state": nonce}))
            self.assertIsNone(self.setup_state()["app"], "no unverified id is captured")
            urllib.request.urlopen(base + "/installed?" + urllib.parse.urlencode(
                {"installation_id": "2002", "setup_action": "install", "state": nonce})).read()
            stdout, stderr = resumed.communicate(timeout=10)
            self.assertEqual(resumed.returncode, 0, stderr)
        paths = [c[0] for c in calls]
        self.assertEqual(paths.count("/app-manifests/synthetic-code/conversions"), 1, paths)
        self.assertEqual(paths[1], "/app", "the saved App is reconciled with GitHub first")
        state_file = self.setup_state()
        self.assertEqual(state_file["app"], {"app_id": 1001, "installation_id": 2002})
        self.assertEqual([o["phase"] for o in state_file["operations"]], ["applied"])
        self.assert_no_key(stdout, stderr, repr(calls), (self.state / "setup/state.json").read_bytes())

    def lose_registration(self, endpoint, behavior, extra=()):
        behavior["drop"] = True
        operation = self.preview(endpoint, extra=extra)["operation_id"]
        process = self.run_yes(endpoint, operation, extra)
        url = self.announced(process)
        with urllib.request.urlopen(url) as response:
            form = Form()
            form.feed(response.read().decode())
        manifest = json.loads(form.values["manifest"])
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                {"code": "synthetic-code", "state": state}))
        process.communicate(timeout=10)
        return operation

    def test_one_proposal_asks_github_to_register_at_most_once(self):
        self.key.unlink()
        self.config.unlink()
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["drop"] = True
            operation = self.preview(endpoint)["operation_id"]
            first, second = self.run_yes(endpoint, operation), self.run_yes(endpoint, operation)
            pages = []
            for process in (first, second):
                with urllib.request.urlopen(self.announced(process)) as response:
                    form = Form()
                    form.feed(response.read().decode())
                pages.append((json.loads(form.values["manifest"]),
                              urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]))
            for manifest, state in pages:
                with self.assertRaises(urllib.error.HTTPError) as refused:
                    urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                        {"code": "synthetic-code", "state": state}))
                pages[pages.index((manifest, state))] = refused.exception.code
            for process in (first, second):
                process.communicate(timeout=10)
                self.assertNotEqual(process.returncode, 0)
            self.assertEqual(pages[1], 409, "the second claim is refused before any request")
            self.assertEqual([c[0] for c in calls].count("/app-manifests/synthetic-code/conversions"), 1)
            self.assertEqual([o["phase"] for o in self.setup_state()["operations"]], ["uncertain"])

    def test_only_the_newest_uncertain_registration_can_be_acknowledged(self):
        self.key.unlink()
        self.config.unlink()
        with fake_github(self.pem) as (endpoint, calls, behavior):
            first = self.lose_registration(endpoint, behavior)
            second = self.lose_registration(endpoint, behavior, ("--after-uncertain", first))
            self.assertNotEqual(first, second)
            converted = len(calls)
            for extra in (("--after-uncertain", first),
                          ("--after-uncertain", first, "--yes", "--operation", second),
                          ("--after-uncertain", second, "--yes", "--operation", second)):
                result = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                         "--api-base", endpoint, "--port", "0",
                                         "--repo", "synthetic-owner/synthetic-repo", *extra],
                                        capture_output=True, timeout=10)
                self.assertNotEqual(result.returncode, 0, extra)
                self.assertEqual(result.stdout, b"", extra)
            self.assertEqual(len(calls), converted, "no further conversion request")
            third = self.preview(endpoint, extra=("--after-uncertain", second))["operation_id"]
            self.assertNotIn(third, (first, second))
            self.assertEqual([o["phase"] for o in self.setup_state()["operations"]],
                             ["uncertain", "uncertain", "proposed"])

    def test_a_claim_rechecks_the_newest_uncertain_registration_under_the_lock(self):
        self.key.unlink()
        self.config.unlink()
        other = ("--repo", "synthetic-owner/other-repo")
        with fake_github(self.pem) as (endpoint, calls, behavior):
            first = self.lose_registration(endpoint, behavior)
            later = self.preview(endpoint, other, extra=("--after-uncertain", first))["operation_id"]
            waiting = self.run_yes(endpoint, later, ("--after-uncertain", first, *other))
            with urllib.request.urlopen(self.announced(waiting)) as response:
                form = Form()
                form.feed(response.read().decode())
            manifest = json.loads(form.values["manifest"])
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            second = self.lose_registration(endpoint, behavior, ("--after-uncertain", first))
            self.assertEqual(len(calls), 2)
            with self.assertRaises(urllib.error.HTTPError) as refused:
                urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                    {"code": "synthetic-code", "state": state}))
            self.assertEqual(refused.exception.code, 409)
            waiting.communicate(timeout=10)
            self.assertNotEqual(waiting.returncode, 0)
            self.assertEqual(len(calls), 2, "no request after a stale claim")
            phases = {o["operation_id"]: o["phase"] for o in self.setup_state()["operations"]}
            self.assertEqual(phases, {first: "uncertain", second: "uncertain", later: "proposed"})

    def test_an_acknowledged_recovery_keeps_its_identity_after_completing(self):
        self.key.unlink()
        self.config.unlink()
        with fake_github(self.pem) as (endpoint, calls, behavior):
            first = self.lose_registration(endpoint, behavior)
            behavior["drop"] = False
            after = ("--after-uncertain", first)
            recovery = self.preview(endpoint, extra=after)["operation_id"]
            process = self.run_yes(endpoint, recovery, after)
            with urllib.request.urlopen(self.announced(process)) as response:
                form = Form()
                form.feed(response.read().decode())
            manifest = json.loads(form.values["manifest"])
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                {"code": "synthetic-code", "state": state})).read()
            urllib.request.urlopen(manifest["setup_url"] + "?" + urllib.parse.urlencode(
                {"installation_id": "2002", "setup_action": "install", "state": state})).read()
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            done = len(calls)
            retry = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                    "--api-base", endpoint, "--port", "0", "--repo", "synthetic-owner/synthetic-repo",
                                    *after, "--yes", "--operation", recovery], capture_output=True, timeout=10)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)["operation_id"], recovery)
            self.assertEqual(json.loads(retry.stdout)["phase"], "applied")
            self.assertEqual(self.preview(endpoint, extra=after, phase="applied")["operation_id"], recovery)
            self.assertEqual(len(calls), done)

    def test_the_operation_bound_never_drops_an_uncertain_registration(self):
        sys.path.insert(0, str(HERE.parent / "install/setup"))
        import store
        self.key.unlink()
        self.config.unlink()
        with fake_github(self.pem) as (endpoint, calls, behavior):
            lost = self.lose_registration(endpoint, behavior)
            setup = store.Store(str(self.state))
            for n in range(80):
                setup.propose("prepare_project", {"n": n}, ["Synthetic."], "Synthetic.")
            operations = self.setup_state()["operations"]
            self.assertEqual(len(operations), 64)
            self.assertIn((lost, "uncertain"), [(o["operation_id"], o["phase"]) for o in operations])
            result = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                     "--api-base", endpoint, "--port", "0",
                                     "--repo", "synthetic-owner/synthetic-repo"], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 6, result.stderr)
            def fill(value):
                value["operations"] = [dict(o, phase="uncertain", operation_id=f"{n:032x}")
                                       for n, o in enumerate([value["operations"][0]] * 64)]
            setup.update(fill)
            with self.assertRaises(store.Refused):
                setup.propose("prepare_project", {"n": "more"}, ["Synthetic."], "Synthetic.")
            self.assertEqual(len(self.setup_state()["operations"]), 64)

    def test_the_packaged_app_tool_runs_from_an_installed_runtime(self):
        runtime = Path(self.tmp.name) / "installed/current/runtime"
        for source, name in ((HERE / "setup.py", "github-app/setup.py"), (HERE / "app.py", "github-app/app.py"),
                             (HERE / "manifest.json", "github-app/manifest.json"),
                             (HERE.parent / "install/setup/setup.py", "setup/setup.py"),
                             (HERE.parent / "install/setup/store.py", "setup/store.py")):
            (runtime / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, runtime / name)
        self.key.unlink()
        self.config.unlink()
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            result = subprocess.run(["python3", "-I", "-B", str(runtime / "github-app/setup.py"),
                                     "--state-dir", str(self.state), "--api-base", endpoint,
                                     "--repo", "synthetic-owner/synthetic-repo"], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["kind"], "connect_app")
        self.assertEqual(calls, [])

    def test_a_completed_connection_reloads_its_own_result(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, line, page, form, manifest = self.start(endpoint)
            state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
            urllib.request.urlopen(manifest["redirect_url"] + "?" + urllib.parse.urlencode(
                {"code": "synthetic-code", "state": state})).read()
            urllib.request.urlopen(manifest["setup_url"] + "?" + urllib.parse.urlencode(
                {"installation_id": "2002", "setup_action": "install", "state": state})).read()
            process.communicate(timeout=10)
            done = len(calls)
            retry = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                    "--api-base", endpoint, "--port", "0", "--repo", "synthetic-owner/synthetic-repo",
                                    "--yes", "--operation", self.operation], capture_output=True, timeout=10)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)["phase"], "applied")
            self.assertEqual(self.preview(endpoint, phase="applied")["operation_id"], self.operation)
            self.assertEqual(len(calls), done)
            self.assertEqual(len(self.setup_state()["operations"]), 1)


STORE_SCRIPT = """import json, os, sys
value = sys.stdin.read()
# Python sets LC_CTYPE itself in a C locale (PEP 538): that is this process, not the caller.
env = {{k: v for k, v in os.environ.items() if k != "LC_CTYPE"}}
with open({sink!r}, "a") as out:
    out.write(json.dumps({{"argv": sys.argv[1:], "env": env, "stdin": value}}) + "\\n")
fail = open({fail!r}).read().split() if os.path.exists({fail!r}) else []
sys.exit(1 if "*" in fail or sys.argv[1:2] == fail[:1] else 0)
"""
INSTALL_LINK = "https://github.com/apps/synthetic-app/installations/new?state="
ORG = ("--agent-for", "synthetic-org", "--organization")


class NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def fetch(url):
    try:
        with urllib.request.build_opener(NoFollow()).open(url, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


class AgentSetupTests(KeyFixture):
    def setUp(self):
        super().setUp()
        self.key.unlink()
        self.config.unlink()
        root = Path(self.tmp.name)
        self.sink = root / "secret-store.jsonl"
        self.failing = root / "secret-store-fails"
        self.store = root / "fake-secret-store"
        self.store.write_text(f"#!{sys.executable} -I\n" + STORE_SCRIPT.format(sink=str(self.sink),
                                                                               fail=str(self.failing)))
        self.store.chmod(0o700)
        shim = root / "bin"
        shim.mkdir()
        self.openssl_log = root / "openssl-argv.log"
        (shim / "openssl").write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{self.openssl_log}"\n'
                                      'exec /usr/bin/openssl "$@"\n')
        (shim / "openssl").chmod(0o700)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("OPENWIZ_GITHUB_APP_")}
        self.env["PATH"] = f"{shim}:{os.environ['PATH']}"
        self.secret = base64.b64encode(self.pem).decode()
        text = (HERE.parent.parent / "contracts/github-identity.v1.md").read_text()
        self.pin = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))

    def command(self, endpoint, extra=(), account=("--agent-for", "synthetic-owner"), store=True):
        return ["python3", str(getattr(self, "tool", HERE) / "setup.py"), "--state-dir", str(self.state), "--api-base", endpoint,
                "--port", "0", *account, *(("--secret-store", str(self.store)) if store else ()), *extra]

    def stored(self, delivered, app_id="1001"):
        if not delivered:
            return self.env
        env = dict(self.env, OPENWIZ_GITHUB_APP_KEY=self.secret)
        return env if app_id is None else dict(env, OPENWIZ_GITHUB_APP_ID=app_id)

    def agent_run(self, endpoint, extra=(), account=("--agent-for", "synthetic-owner"), env=None, store=True):
        return subprocess.run(self.command(endpoint, extra, account, store), capture_output=True, timeout=10,
                              env=env or self.env)

    def agent_preview(self, endpoint, account=("--agent-for", "synthetic-owner"), env=None, store=True):
        result = self.agent_run(endpoint, (), account, env, store)
        self.assertEqual(result.returncode, 0, result.stderr)
        operation = json.loads(result.stdout)
        self.assertEqual((operation["kind"], operation["phase"]), ("connect_app", "proposed"))
        return operation

    def agent_start(self, endpoint, account=("--agent-for", "synthetic-owner"), env=None, store=True, open=True):
        self.operation = self.agent_preview(endpoint, account, env, store)["operation_id"]
        process = subprocess.Popen(self.command(endpoint, ("--yes", "--operation", self.operation), account, store),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env or self.env)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            self.assertTrue(selector.select(10), "setup did not announce its local URL")
            line = process.stdout.readline()
        finally:
            selector.close()
        url = re.search(rb"http://127\.0\.0\.1:[0-9]+/start/[A-Za-z0-9_-]+", line).group().decode()
        if not open:
            return process, line, url, None, url.split("/start/")[0]
        start = fetch(url)
        form = Form()
        form.feed(start[2].decode())
        return process, line, start, form, url.split("/start/")[0]

    def register(self, endpoint, account=("--agent-for", "synthetic-owner")):
        process, _line, _start, form, base = self.agent_start(endpoint, account)
        state, _answer = self.callback(base, form)
        self.installed(base, state)
        process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0)
        return self.operation

    def records(self):
        if not self.sink.exists():
            return []
        return [json.loads(line) for line in self.sink.read_text().splitlines()]

    def setup_state(self):
        return json.loads((self.state / "setup/state.json").read_text())

    def phases(self):
        return [o["phase"] for o in self.setup_state()["operations"]]

    def recorded_app(self):
        path = self.app / "app.json"
        return json.loads(path.read_text()) if path.exists() else None

    def assert_nothing_left(self, *outputs):
        needles = [self.pem, self.secret.encode(), b"synthetic-code"] + self.pem.splitlines()[1:-1]
        leftovers = [p.read_bytes() for p in Path(self.tmp.name).rglob("*") if p.is_file() and p != self.sink]
        argv = [json.dumps(r["argv"]).encode() for r in self.records()]
        for output in (*outputs, *leftovers, *argv):
            if isinstance(output, str):
                output = output.encode()
            for needle in needles:
                self.assertNotIn(needle, output)
        self.assertFalse(self.key.exists())

    def assert_calls_hold_no_key(self, calls):
        self.assert_no_key(repr(calls))
        self.assertNotIn(self.secret, repr(calls))

    def callback(self, base, form, expect=303):
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(form.action).query)["state"][0]
        status, headers, body = fetch(base + "/callback?" + urllib.parse.urlencode(
            {"code": "synthetic-code", "state": state}))
        self.assertEqual(status, expect, body)
        if expect == 303:
            self.assertEqual(headers["Location"], INSTALL_LINK + urllib.parse.quote(state))
        return state, body + str(headers).encode()

    def installed(self, base, state, expect=200):
        status, headers, body = fetch(base + "/installed?" + urllib.parse.urlencode(
            {"installation_id": "2002", "setup_action": "install", "state": state}))
        self.assertEqual(status, expect, body)
        return body + str(headers).encode()

    def reconcile_start(self, endpoint, account=("--agent-for", "synthetic-owner"), env=None, store=True):
        process, line, (status, headers, page), form, base = self.agent_start(
            endpoint, account, env or self.stored(True), store)
        self.assertEqual((status, form.values), (303, {}))
        self.assertTrue(headers["Location"].startswith(INSTALL_LINK), headers["Location"])
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(headers["Location"]).query)["state"][0]
        return process, line, page, base, state

    def test_agent_page_carries_exactly_the_contract_profile(self):
        app = self.pin["app"]
        long = "synthetic-" + "x" * 29
        for account, target, name, public in (
                (("--agent-for", "synthetic-owner"), "https://github.com/settings/apps/new?state=",
                 "OpenWiz synthetic-owner", False),
                (ORG, "https://github.com/organizations/synthetic-org/settings/apps/new?state=",
                 "OpenWiz synthetic-org", False),
                (("--agent-for", long), "https://github.com/settings/apps/new?state=",
                 "OpenWiz synthetic-xxxxxxx " + hashlib.sha256(long.encode()).hexdigest()[:8], False),
                (("--agent-for", "synthetic-org", "--organization", "--factory"),
                 "https://github.com/organizations/synthetic-org/settings/apps/new?state=",
                 app["name"], app["visibility"] == "public")):
            with self.subTest(account=account), fake_github(self.pem) as (endpoint, calls, _behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                process, line, (status, headers, page), form, base = self.agent_start(endpoint, account)
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(status, 200)
                self.assertTrue(form.action.startswith(target), form.action)
                self.assertLessEqual(len(name), 34)
                home = "https://github.com/" + account[1]
                self.assertEqual(json.loads(form.values["manifest"]), {
                    "name": name, "public": public,
                    "default_permissions": app["permissions"], "default_events": app["events"],
                    "url": home, "hook_attributes": {"url": home, "active": app["webhook"]},
                    "redirect_url": base + "/callback", "setup_url": base + "/installed",
                    "setup_on_update": True})
                nonce = re.search(r"script-src 'nonce-([A-Za-z0-9_-]+)'", headers["Content-Security-Policy"])
                self.assertIn(f'<script nonce="{nonce.group(1)}">document.forms[0].submit()</script>'.encode(),
                              page)
                self.assertIn(self.pin["secret"]["name"].encode(), page)
                self.assertEqual(calls, [])
                self.assertEqual(self.records(), [])
                self.assert_nothing_left(line, page, stdout, stderr)

    def test_agent_conversion_key_goes_only_to_the_secret_seam(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, line, (_status, _headers, page), form, base = self.agent_start(endpoint)
            state, answer = self.callback(base, form)
            answer += self.installed(base, state)
            stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions",
                                                 "/app/installations/2002"])
        self.assertEqual(self.records(), [
            {"argv": ["OPENWIZ_GITHUB_APP_KEY"], "env": {}, "stdin": self.secret + "\n"},
            {"argv": ["OPENWIZ_GITHUB_APP_ID"], "env": {}, "stdin": "1001\n"}])
        self.assertEqual(self.phases(), ["applied"])
        self.assertEqual(self.recorded_app(), {"app_id": 1001})
        self.assertIsNone(self.setup_state()["app"])
        self.assertIn(b"Installation 2002 read back", stdout)
        self.assert_nothing_left(line, page, answer, stdout, stderr)
        self.assert_calls_hold_no_key(calls)

    def test_agent_without_a_store_discards_the_converted_key_cleanly(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, line, (_status, _headers, page), form, base = self.agent_start(endpoint, store=False)
            state, answer = self.callback(base, form)
            answer += self.installed(base, state)
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertIn(b"App ID: 1001.", stdout)
            self.assertIn(b"converted key was discarded", stdout)
            self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions"])
            self.assertEqual(self.records(), [])
            self.assertEqual(self.recorded_app(), {"app_id": 1001})
            self.assertEqual(self.phases(), ["applied"])
            self.assertFalse(self.openssl_log.exists())
            self.assert_nothing_left(line, page, answer, stdout, stderr)
            again, _line, _page, base, state = self.reconcile_start(endpoint, env=self.stored(True, None),
                                                                    store=False)
            self.installed(base, state)
            out, err = again.communicate(timeout=10)
            self.assertEqual(again.returncode, 0, err)
            self.assertEqual([c[0] for c in calls][1:], ["/app", "/app/installations/2002"])
            self.assertEqual(self.records(), [])

    def test_agent_lost_reply_or_failed_key_store_stays_uncertain_and_never_registers_again(self):
        for case in ("lost reply", "key store fails"):
            with self.subTest(case=case), fake_github(self.pem) as (endpoint, calls, behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                (self.app / "app.json").unlink(missing_ok=True)
                self.sink.unlink(missing_ok=True)
                behavior["drop"] = case == "lost reply"
                if case == "key store fails":
                    self.failing.write_text("*")
                process, line, (_status, _headers, page), form, base = self.agent_start(endpoint)
                _state, answer = self.callback(base, form, expect=502)
                stdout, stderr = process.communicate(timeout=10)
                self.failing.unlink(missing_ok=True)
                self.assertNotEqual(process.returncode, 0)
                self.assertEqual(self.phases(), ["uncertain"])
                self.assertEqual(len(self.records()), 0 if case == "lost reply" else 1)
                self.assertEqual(self.recorded_app(), None if case == "lost reply" else {"app_id": 1001})
                blocker = self.operation if case == "lost reply" else "App 1001"
                for extra in ((), ("--yes", "--operation", self.operation)):
                    again = self.agent_run(endpoint, extra)
                    self.assertEqual(again.returncode, 6, again.stderr)
                    self.assertIn(blocker.encode(), again.stderr)
                    self.assertEqual(again.stdout, b"")
                self.assertEqual(len(calls), 1)
                self.assert_nothing_left(line, page, answer, stdout, stderr, again.stderr)

    def test_agent_registration_is_uncertain_before_the_form_is_released(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, line, url, _form, base = self.agent_start(endpoint, open=False)
            self.assertEqual(self.phases(), ["proposed"])
            first = fetch(url)
            self.assertEqual(self.phases(), ["uncertain"])
            again = fetch(url)
            self.assertEqual((first[0], again[0]), (200, 200))
            self.assertEqual(self.phases(), ["uncertain"])
            process.kill()
            process.communicate(timeout=10)
            for extra in ((), ("--yes", "--operation", self.operation)):
                result = self.agent_run(endpoint, extra)
                self.assertEqual(result.returncode, 6, result.stderr)
                self.assertIn(self.operation.encode(), result.stderr)
            self.assertEqual(calls, [])
            shutil.rmtree(self.state / "setup")
            process, line, (_s, _h, page), form, base = self.agent_start(endpoint)
            state, _answer = self.callback(base, form)
            self.callback(base, form, expect=400)
            self.installed(base, state)
            process.communicate(timeout=10)
            self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions",
                                                     "/app/installations/2002"])

    def test_agent_claim_rechecks_the_newest_uncertain_registration_under_the_lock(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            waiting, _line, url, _form, _base = self.agent_start(endpoint, open=False)
            first = self.operation
            behavior["drop"] = True
            other, _line, _start, other_form, other_base = self.agent_start(endpoint, ORG)
            self.callback(other_base, other_form, expect=502)
            other.communicate(timeout=10)
            self.assertEqual(len(calls), 1)
            status, _headers, answer = fetch(url)
            self.assertEqual(status, 409)
            self.assertNotIn(b"manifest", answer)
            stdout, stderr = waiting.communicate(timeout=10)
            self.assertNotEqual(waiting.returncode, 0)
            self.assertEqual(len(calls), 1, "no request after a stale claim")
            phases = {o["operation_id"]: o["phase"] for o in self.setup_state()["operations"]}
            self.assertEqual(phases, {first: "proposed", self.operation: "uncertain"})
            self.assertEqual(self.records(), [])
            self.assert_nothing_left(answer, stdout, stderr)

    def test_agent_registered_app_blocks_any_new_registration(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            self.register(endpoint)
            for account in (ORG, ("--agent-for", "synthetic-owner")):
                for extra in ((), ("--after-uncertain", "0" * 32)):
                    with self.subTest(account=account, extra=extra):
                        result = self.agent_run(endpoint, extra, account)
                        self.assertEqual(result.returncode, 6, result.stderr)
                        self.assertIn(b"App 1001 is already registered", result.stderr)
                        self.assertEqual(result.stdout, b"")
            self.assertEqual(len(calls), 2)
            self.assertEqual(len(self.records()), 2)
            self.assertEqual(self.phases(), ["applied"])
            result = self.agent_run(endpoint, env=self.stored(True, "1002"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(calls), 2)

    def test_agent_id_without_its_key_refuses_registration(self):
        env = dict(self.env, OPENWIZ_GITHUB_APP_ID="1001")
        for account in (("--agent-for", "synthetic-owner"), ORG):
            for store in (True, False):
                with self.subTest(account=account, store=store), fake_github(self.pem) as (endpoint, calls, _b):
                    shutil.rmtree(self.state / "setup", ignore_errors=True)
                    for extra in ((), ("--yes", "--operation", "0" * 32), ("--after-uncertain", "0" * 32)):
                        result = self.agent_run(endpoint, extra, account, env, store)
                        self.assertEqual(result.returncode, 6, result.stderr)
                        self.assertIn(b"App 1001 is delivered without its key", result.stderr)
                        self.assertEqual(result.stdout, b"")
                    self.assertEqual(calls, [])
                    self.assertEqual(self.records(), [])
                    self.assertIsNone(self.recorded_app())
                    self.assertFalse((self.state / "setup/state.json").exists()
                                     and self.setup_state()["operations"])
        with fake_github(self.pem) as (endpoint, calls, _b):
            result = self.agent_run(endpoint, env=dict(self.env, OPENWIZ_GITHUB_APP_ID=self.secret[:64]))
            self.assertEqual(result.returncode, 6, result.stderr)
            self.assertIn(b"App (not an id) is delivered without its key", result.stderr)
            self.assertNotIn(self.secret[:64].encode(), result.stderr)
            self.assertEqual(calls, [])

    def test_agent_second_run_reconciles_instead_of_registering(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            self.register(endpoint)
            outputs = []
            for login, account in (("synthetic-owner", ("--agent-for", "synthetic-owner")),):
                behavior["installations"] = {2002: login}
                process, line, page, base, state = self.reconcile_start(endpoint, account)
                answer = self.installed(base, state)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn(f"Installation 2002 read back: {login}".encode(), stdout)
                outputs += [line, page, answer, stdout, stderr]
        self.assertEqual([c[0] for c in calls][2:], ["/app", "/app/installations/2002"])
        self.assertEqual(len(self.records()), 2)
        self.assertEqual(self.phases(), ["applied"] * 2)
        self.assert_nothing_left(*outputs)
        self.assert_calls_hold_no_key(calls)

    def test_agent_completed_reconciliation_is_checked_again_every_run(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            self.register(endpoint)
            process, _line, _page, base, state = self.reconcile_start(endpoint)
            self.installed(base, state)
            process.communicate(timeout=10)
            done = self.operation
            replay = self.agent_run(endpoint, ("--yes", "--operation", done), env=self.stored(True))
            self.assertNotEqual(replay.returncode, 0)
            self.assertNotIn(b'"applied"', replay.stdout)
            behavior["installations"] = {}
            process, _line, _page, base, state = self.reconcile_start(endpoint)
            self.assertNotEqual(self.operation, done)
            self.installed(base, state, expect=400)
            process.kill()
            process.communicate(timeout=10)
            behavior["app_permissions"] = PERMISSIONS
            operation = self.agent_preview(endpoint, env=self.stored(True))["operation_id"]
            result = self.agent_run(endpoint, ("--yes", "--operation", operation), env=self.stored(True))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"http://127.0.0.1", result.stdout)
        self.assertEqual([c[0] for c in calls][2:], ["/app", "/app/installations/2002", "/app",
                                                     "/app/installations/2002", "/app"])
        self.assertEqual(len(self.records()), 2)

    def test_agent_partial_delivery_is_repaired_without_another_conversion(self):
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            self.failing.write_text("OPENWIZ_GITHUB_APP_ID")
            process, line, (_s, _h, page), form, base = self.agent_start(endpoint)
            _state, answer = self.callback(base, form, expect=502)
            stdout, stderr = process.communicate(timeout=10)
            self.failing.unlink()
            self.assertEqual(self.phases(), ["uncertain"])
            self.assertEqual(self.recorded_app(), {"app_id": 1001})
            self.assertEqual([r["argv"] for r in self.records()], [["OPENWIZ_GITHUB_APP_KEY"],
                                                                   ["OPENWIZ_GITHUB_APP_ID"]])
            process, line2, page2, base, state = self.reconcile_start(endpoint, env=self.stored(True, None))
            answer += self.installed(base, state)
            out, err = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, err)
        self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions", "/app",
                                                 "/app/installations/2002"])
        self.assertEqual(self.records()[2:], [{"argv": ["OPENWIZ_GITHUB_APP_ID"], "env": {}, "stdin": "1001\n"}])
        self.assert_nothing_left(line, page, answer, stdout, stderr, line2, page2, out, err)

    def test_agent_reconcile_refuses_another_app_or_a_changed_profile(self):
        for app_id, granted in (("1002", SERVICE), ("1001", PERMISSIONS), ("1001", dict(SERVICE, admin="write"))):
            with self.subTest(app_id=app_id, granted=granted), fake_github(self.pem) as (endpoint, calls, behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                behavior["app_permissions"] = granted
                env = self.stored(True, app_id)
                operation = self.agent_preview(endpoint, env=env)["operation_id"]
                result = self.agent_run(endpoint, ("--yes", "--operation", operation), env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"http://127.0.0.1", result.stdout)
                self.assertEqual([c[0] for c in calls], ["/app"])
                self.assertEqual(self.records(), [])
                self.assertIsNone(self.recorded_app())
                self.assertEqual(self.phases(), ["proposed"])
                self.assert_nothing_left(result.stdout, result.stderr)

    def test_agent_install_read_back_refuses_another_account_or_all_repositories(self):
        for key, value in (("selection", "all"), ("installations", {2002: "synthetic-other"})):
            with self.subTest(key=key), fake_github(self.pem) as (endpoint, calls, behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                (self.app / "app.json").unlink(missing_ok=True)
                self.sink.unlink(missing_ok=True)
                behavior[key] = value
                process, line, (_status, _headers, page), form, base = self.agent_start(endpoint)
                state, answer = self.callback(base, form)
                answer += self.installed(base, state, expect=400)
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(self.phases(), ["applied"])
                self.assertNotIn(b"read back", stdout)
                self.assert_nothing_left(line, page, answer, stdout, stderr)

    def test_agent_app_created_by_another_account_is_refused_and_never_installed(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["app_owner"] = "synthetic-elsewhere"
            process, line, (_status, _headers, page), form, base = self.agent_start(endpoint)
            _state, answer = self.callback(base, form, expect=403)
            stdout, stderr = process.communicate(timeout=10)
            self.assertNotEqual(process.returncode, 0)
            self.assertNotIn(b"installations/new", answer + stdout)
            self.assertIn(b"synthetic-elsewhere", stderr)
            self.assertEqual(self.records(), [])
            self.assertEqual(self.recorded_app(), {"app_id": 1001})
            self.assertEqual(self.phases(), ["applied"])
            again = self.agent_run(endpoint)
            self.assertEqual(again.returncode, 6, again.stderr)
            self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions"])
            self.assert_nothing_left(line, page, answer, stdout, stderr, again.stderr)
            refused = self.operation
            (self.app / "app.json").unlink()
            fresh = self.agent_preview(endpoint)
            self.assertNotEqual(fresh["operation_id"], refused)
            old = self.agent_run(endpoint, ("--yes", "--operation", refused))
            self.assertNotEqual(old.returncode, 0)
            self.assertEqual(old.stdout, b"")
            behavior["app_owner"] = "synthetic-owner"
            process, line, (status, _headers, page), form, base = self.agent_start(endpoint)
            self.assertEqual(status, 200)
            self.assertTrue(form.action.startswith("https://github.com/settings/apps/new?"), form.action)
            process.kill()
            process.communicate(timeout=10)

    def test_agent_reconcile_is_bound_to_the_owner_unless_the_factory_setting_is_explicit(self):
        named = [i["account"] for i in self.pin["installations"]]
        cases = [
            (("--agent-for", "synthetic-owner"), "synthetic-elsewhere", "synthetic-owner", False),
            (("--agent-for", named[0]), named[-1], named[0], False),
            (("--agent-for", named[0], "--factory"), named[-1], named[0], True),
            (("--agent-for", "synthetic-owner", "--factory"), named[-1], "synthetic-owner", False)]
        for account, owner, installed, read_back in cases:
            with self.subTest(account=account, owner=owner), fake_github(self.pem) as (endpoint, calls, behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                (self.app / "app.json").unlink(missing_ok=True)
                behavior.update(app_owner=owner, installations={2002: installed})
                env = self.stored(True)
                if not read_back:
                    operation = self.agent_preview(endpoint, account, env)["operation_id"]
                    result = self.agent_run(endpoint, ("--yes", "--operation", operation), account, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn(b"http://127.0.0.1", result.stdout)
                    self.assertEqual([c[0] for c in calls], ["/app"])
                    self.assertIsNone(self.recorded_app())
                    self.assertEqual(self.phases(), ["proposed"])
                    self.assert_nothing_left(result.stdout, result.stderr)
                    continue
                process, line, page, base, state = self.reconcile_start(endpoint, account, env)
                self.installed(base, state)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn(f"Installation 2002 read back: {named[0]}".encode(), stdout)

    def test_agent_capability_reports_only_what_this_host_shows(self):
        spec = importlib.util.spec_from_file_location(
            "setup_onboard_check", HERE.parent / "install/tests/setup-onboard-contract/check.py")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        cases = [
            (True, self.stored(False), False, "uncertain", "missing", [], [],
             ["delivery_unverified", "key_download_unknown", "not_live"]),
            (True, self.stored(True), False, "stored", "verified", [], [], ["key_download_unknown", "not_live"]),
            (True, self.stored(True, None), False, "uncertain", "uncertain", [], [],
             ["delivery_unverified", "key_download_unknown", "not_live"]),
            (True, self.stored(True, "1002"), False, "failed", "refused", [], ["secret_store_failed"],
             ["key_download_unknown", "not_live"]),
            (False, self.stored(True), False, "uncertain", "uncertain", [], [],
             ["delivery_unverified", "key_download_unknown", "not_live"]),
            (True, self.stored(True), True, "stored", "verified", ["agent_save_unavailable"], [], ["not_live"])]
        for registered, env, store, outcome, delivery, problems, failures, unproven in cases:
            with self.subTest(registered=registered, store=store, delivered=env.get("OPENWIZ_GITHUB_APP_ID")):
                (self.app / "app.json").unlink(missing_ok=True)
                if registered:
                    (self.app / "app.json").write_text('{"app_id": 1001}')
                    (self.app / "app.json").chmod(0o600)
                result = self.agent_run("http://127.0.0.1:1", ("--capability",), env=env, store=store)
                self.assertEqual(result.returncode, 0, result.stderr)
                document = json.loads(result.stdout)
                report = checker.check(document)
                self.assertEqual((document["outcome"], document["delivery"]["state"]), (outcome, delivery))
                self.assertEqual((report.problems, report.failures, report.unproven),
                                 (problems, failures, unproven))
                self.assertEqual(document["app_registrations"], 1 if registered else 0)
                self.assertEqual(self.records(), [])
                self.assert_nothing_left(result.stdout, result.stderr)

    def test_agent_factory_reconcile_works_from_the_installed_runtime(self):
        runtime = Path(self.tmp.name) / "installed/current/runtime"
        for source, name in ((HERE / "setup.py", "github-app/setup.py"), (HERE / "app.py", "github-app/app.py"),
                             (HERE / "manifest.json", "github-app/manifest.json"),
                             (HERE.parent / "install/setup/store.py", "setup/store.py")):
            (runtime / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, runtime / name)
        self.tool = runtime / "github-app"
        named = [i["account"] for i in self.pin["installations"]]
        for account, read_back in ((named[0], True), ("synthetic-owner", False)):
            with self.subTest(account=account), fake_github(self.pem) as (endpoint, calls, behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                (self.app / "app.json").unlink(missing_ok=True)
                behavior.update(app_owner=named[-1], installations={2002: account})
                flags, env = ("--agent-for", account, "--factory"), self.stored(True)
                if not read_back:
                    operation = self.agent_preview(endpoint, flags, env)["operation_id"]
                    result = self.agent_run(endpoint, ("--yes", "--operation", operation), flags, env)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual([c[0] for c in calls], ["/app"])
                    continue
                process, _line, _page, base, state = self.reconcile_start(endpoint, flags, env)
                self.installed(base, state)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn(f"Installation 2002 read back: {account}".encode(), stdout)

    def test_factory_installations_are_exactly_the_identity_contracts_pin(self):
        sys.path.insert(0, str(HERE))
        import app as tool
        pinned = {i["account"].lower(): {r.lower() for r in i["repositories"]} for i in self.pin["installations"]}
        self.assertEqual(tool.factory_installations(), pinned)

    def test_agent_mode_needs_a_valid_account_and_store(self):
        relative = ("--secret-store", "fake-secret-store")
        cases = [(("--agent-for", bad), True) for bad in ("-bad", "bad-", "a--b", "a/b", "bad name", "x" * 40, "")]
        cases += [(("--organization",), True), (("--agent-for", "synthetic-owner", "--repo", "a/b"), True),
                  (("--agent-for", "synthetic-owner", *relative), False),
                  (("--secret-store", str(HERE / "manifest.json"), "--agent-for", "synthetic-owner"), False)]
        for account, store in cases:
            with self.subTest(account=account, store=store), fake_github(self.pem) as (endpoint, calls, _b):
                result = self.agent_run(endpoint, (), account, store=store)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(calls, [])
                self.assertFalse((self.state / "setup").exists())


CALLER_TOKENS = {name: f"synthetic-caller-{name.lower()}" for name in (
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")}


class AgentTokenTests(KeyFixture):
    REFUSED = b"App token refused: check PC state permissions, App installation and GitHub availability.\n"

    def setUp(self):
        super().setUp()
        self.bin = Path(self.tmp.name) / "bin"
        self.bin.mkdir()
        self.openssl_log = Path(self.tmp.name) / "openssl.log"
        fake = self.bin / "openssl"
        fake.write_text(f'#!/bin/sh\n{{ printf "%s\\n" "$@"; env; }} >> "{self.openssl_log}"\n'
                        f'exec {shutil.which("openssl")} "$@"\n')
        fake.chmod(0o700)
        self.secret = base64.b64encode(self.pem).decode()

    def run_tool(self, script, endpoint, *extra, now=None, env=None, repositories=("synthetic-owner/work",)):
        base = {"PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', os.defpath)}",
                "OPENWIZ_SYNTHETIC_GITHUB": "1",
                **{k: os.environ[k] for k in ("HOME", "LANG") if k in os.environ}, **(env or {})}
        args = ["--state-dir", str(self.state), "--installation-id", "2002", "--api-base", endpoint,
                *[a for r in repositories for a in ("--repository", r)], *extra]
        if now is None:
            command = ["python3", "-I", str(HERE / script), *args]
        else:
            command = ["python3", "-c", """
import datetime, runpy, sys
from pathlib import Path
from unittest.mock import patch
script, instant, *args = sys.argv[1:]
fixed = datetime.datetime.fromtimestamp(float(instant), datetime.timezone.utc)
class DeviceClock(datetime.datetime):
    @classmethod
    def now(cls, tz=None):
        return fixed.astimezone(tz) if tz is not None else fixed.replace(tzinfo=None)
sys.path.insert(0, str(Path(script).parent))
sys.argv = [script, *args]
with patch("datetime.datetime", DeviceClock), patch("time.time", return_value=fixed.timestamp()):
    runpy.run_path(script, run_name="__main__")
""", str(HERE / script), str(now), *args]
        return subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, env=base)

    def assert_hidden(self, token, *outputs):
        log = self.openssl_log.read_bytes() if self.openssl_log.exists() else b""
        self.assert_no_key(log, *outputs)
        for needle in (self.secret.encode(), self.secret[:40].encode(), token.encode()):
            for number, output in enumerate((log, *outputs), 1):
                output = output if isinstance(output, bytes) else output.encode()
                self.assertFalse(needle in output, f"a secret reached output {number}")

    def test_write_token_asks_for_and_accepts_exactly_the_apps_profile(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            original = behavior.copy()
            for granted, ok in ((SERVICE, True), (PERMISSIONS, False),
                                (dict(SERVICE, workflows="write"), False),
                                (dict(SERVICE, administration="write"), False),
                                (dict(SERVICE, contents="read"), False)):
                with self.subTest(granted=granted):
                    behavior.clear()
                    behavior.update(original, permissions=granted)
                    shutil.rmtree(self.state / "tokens", ignore_errors=True)
                    result = self.run_tool("refresh-token.py", endpoint, "--write", env=CALLER_TOKENS)
                    for caller in CALLER_TOKENS.values():
                        self.assert_hidden(caller)
                    if ok:
                        self.assertEqual((result.returncode, result.stdout, result.stderr),
                                         (0, b"synthetic-installation-token\n", b""))
                    else:
                        self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", self.REFUSED))
                    self.assertEqual(json.loads(mints(calls)[-1][2]),
                                     {"permissions": SERVICE, "repositories": ["work"]})
            self.assertEqual(len(mints(calls)), 5)
            self.assert_hidden("synthetic-installation-token", repr(calls))

    def test_secret_key_mints_with_no_key_file_and_never_reaches_the_signer_environment(self):
        shutil.rmtree(self.app)
        secret = {"OPENWIZ_GITHUB_APP_KEY": self.secret, "OPENWIZ_GITHUB_APP_ID": "1001"}
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["permissions"] = SERVICE
            result = self.run_tool("refresh-token.py", endpoint, "--write", "--from-secret", env=secret)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (0, b"synthetic-installation-token\n", b""))
            self.assertEqual([c[0] for c in calls], OWNER_READS + ["/app/installations/2002/access_tokens"])
            self.assertIn(b"/dev/fd/", self.openssl_log.read_bytes())
            self.assert_hidden("synthetic-installation-token", result.stderr, repr(calls))
            before = len(calls)
            for bad in ({}, {"OPENWIZ_GITHUB_APP_KEY": self.secret}, dict(secret, OPENWIZ_GITHUB_APP_ID="01001"),
                        dict(secret, OPENWIZ_GITHUB_APP_KEY="not base64!"),
                        dict(secret, OPENWIZ_GITHUB_APP_KEY=base64.b64encode(b"x" * 5000).decode())):
                with self.subTest(bad=sorted(bad)):
                    shutil.rmtree(self.state / "tokens", ignore_errors=True)
                    result = self.run_tool("refresh-token.py", endpoint, "--write", "--from-secret", env=bad)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", self.REFUSED))
            self.assertEqual(len(calls), before)

    def test_refresh_reuses_a_token_until_five_minutes_are_left_then_mints_anew(self):
        start = 1767225600
        cache = self.state / "tokens"
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior.update(permissions=SERVICE, expires_at="2026-01-01T01:00:00Z", token="synthetic-token-one")
            steps = [(0, "synthetic-token-one", 1), (3299, "synthetic-token-one", 1),
                     (3300, "synthetic-token-two", 2), (3301, "synthetic-token-two", 2)]
            for offset, expected, minted in steps:
                with self.subTest(offset=offset):
                    if offset == 3300:
                        behavior.update(token="synthetic-token-two", expires_at="2026-01-01T01:55:00Z")
                    result = self.run_tool("refresh-token.py", endpoint, "--write", now=start + offset)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (0, expected.encode() + b"\n", b""))
                    self.assertEqual(len(mints(calls)), minted)
            behavior.update(permissions=PERMISSIONS, token="synthetic-token-read")
            result = self.run_tool("refresh-token.py", endpoint, now=start + 3301)
            self.assertEqual((result.returncode, result.stdout), (0, b"synthetic-token-read\n"))
            self.assertEqual(len(mints(calls)), 3)
            behavior.update(permissions=SERVICE, token="synthetic-token-short", expires_at="2026-01-01T02:00:00Z")
            behavior["read_profile"] = {"repository_selection": "selected",
                                        "repositories": [{"full_name": "synthetic-owner/other"}]}
            result = self.run_tool("refresh-token.py", endpoint, "--write", now=start + 6900,
                                   repositories=("synthetic-owner/other",))
            self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", self.REFUSED))
            self.assertEqual(len(mints(calls)), 4)
        self.assertEqual(cache.stat().st_mode & 0o777, 0o700)
        names = sorted(p.name for p in cache.iterdir())
        self.assertEqual(len([n for n in names if n.endswith(".json")]), 2)
        for path in cache.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(b"synthetic-token", path.name.encode())
        self.assert_hidden("synthetic-token-one", repr(calls))
        self.assert_hidden("synthetic-token-two", repr(calls))

    def test_refresh_refuses_an_unsafe_cache_without_using_it(self):
        start = 1767225600
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior.update(permissions=SERVICE, expires_at="2026-01-01T01:00:00Z")
            self.assertEqual(self.run_tool("refresh-token.py", endpoint, "--write", now=start).returncode, 0)
            (path,) = [p for p in (self.state / "tokens").iterdir() if p.name.endswith(".json")]
            for spoil in ("mode", "symlink", "directory"):
                with self.subTest(spoil=spoil):
                    if spoil == "mode":
                        path.chmod(0o644)
                    elif spoil == "symlink":
                        path.chmod(0o600)
                        target = path.with_name("planted")
                        path.rename(target)
                        path.symlink_to(target)
                    else:
                        path.unlink()
                        target.rename(path)
                        path.parent.chmod(0o755)
                    result = self.run_tool("refresh-token.py", endpoint, "--write", now=start + 60)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (1, b"", self.REFUSED))
            self.assertEqual(len(mints(calls)), 1)

    def test_a_failing_check_names_the_output_never_its_content(self):
        with mock.patch.dict(os.environ, {"SYNTHETIC_RUNNER_KEY": "synthetic-runner-value"}), \
                fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["permissions"] = SERVICE
            self.assertEqual(self.run_tool("refresh-token.py", endpoint, "--write").returncode, 0)
        self.assertFalse(self.openssl_log.exists(), "the key file is signed by /usr/bin/openssl, never PATH's (#608)")
        for check in (lambda: self.assert_no_key("synthetic-context " + self.pem.decode()),
                      lambda: self.assert_hidden("synthetic-leaked-token", "synthetic-context synthetic-leaked-token")):
            with self.assertRaises(AssertionError) as caught:
                check()
            self.assertFalse("synthetic-context" in str(caught.exception), "a failure printed the output")


if __name__ == "__main__":
    unittest.main(verbosity=2)
