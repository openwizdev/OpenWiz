#!/usr/bin/env python3
"""Synthetic fixtures only. Run: python3 tools/github-app/test.py."""
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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

HERE = Path(__file__).resolve().parent
PERMISSIONS = {name: "read" for name in (
    "metadata", "contents", "issues", "pull_requests", "checks", "actions")}
# The service App profile the App is registered with (#1105).
SERVICE = dict(PERMISSIONS, contents="write", issues="write", pull_requests="write")


class LiveCheckDocumentationTests(unittest.TestCase):
    def test_mint_refusal_preserves_parent_shell_and_skips_read(self):
        doc = (HERE.parents[1] / "docs/github-app.md").read_text()
        live_check = doc.split("After Jake authorizes the live check, on the PC:", 1)[1]
        script = live_check.split("```sh\n", 1)[1].split("```", 1)[0]
        with tempfile.TemporaryDirectory(prefix="openwiz-app-doc-") as directory:
            root = Path(directory)
            mint = root / "python3"
            mint.write_text('''#!/bin/sh
if [ "$SYNTHETIC_MINT_OUTCOME" = success ]; then
    printf 'synthetic-installation-token\\n1767229200\\n'
else
    printf 'synthetic mint refused\\n' >&2
    exit 1
fi
''')
            gh = root / "gh"
            gh.write_text('''#!/bin/sh
printf '%s\\n' "$GH_TOKEN" "$@" >> "$SYNTHETIC_CALL_LOG"
printf 'synthetic rate limit\\n'
''')
            mint.chmod(0o700)
            gh.chmod(0o700)
            call_log = root / "calls"
            parent = script + '''
printf 'parent survived: %s|%s|%s\\n' "$?" "$APP_TOKEN" "$GH_TOKEN"
'''
            for outcome, status in (("refused", 1), ("success", 0)):
                with self.subTest(outcome=outcome):
                    result = subprocess.run(
                        ["/bin/sh", "-c", parent], cwd=root,
                        env={"PATH": str(root), "APP_TOKEN": "synthetic-parent-app",
                             "GH_TOKEN": "synthetic-parent-gh",
                             "SYNTHETIC_MINT_OUTCOME": outcome,
                             "SYNTHETIC_CALL_LOG": str(call_log)},
                        capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    expected_parent = (f"parent survived: {status}|"
                                       "synthetic-parent-app|synthetic-parent-gh\n")
                    if outcome == "refused":
                        self.assertEqual(result.stdout, expected_parent)
                        self.assertEqual(result.stderr, "synthetic mint refused\n")
                        self.assertFalse(call_log.exists())
                    else:
                        self.assertEqual(result.stdout,
                                         "synthetic rate limit\n" + expected_parent)
                        self.assertEqual(result.stderr, "")
                        self.assertEqual(call_log.read_text().splitlines(), [
                            "synthetic-installation-token", "api", "rate_limit", "--jq",
                            ".resources.core | {limit, remaining}"])


ROOT = HERE.parents[1]
# #1279's owned paths: each loop and tool here follows the repository it runs
# in (its clone, or one setting), so none may name ClosedWiz's as a fixed
# target. This file is the one test CI runs in those paths, so the check is here.
FOLLOWING_PATHS = ("loops", "tools/stall-alarm", "tools/github-app",
                   "tools/factory-metrics", "tools/roadmap", "docs/ROADMAP.md")
# Built in pieces so this file is not a hit itself.
FIXED_TARGET = re.compile(re.escape("jparker2006" + "/" + "ClosedWiz").encode(), re.IGNORECASE)
# A pointer to the private record (a ClosedWiz issue comment, as #1257 has it)
# names a record, not a target.
POINTER = re.compile(rb"https://github\.com/" + FIXED_TARGET.pattern + rb"/issues/[1-9][0-9]*#issuecomment-[1-9][0-9]*",
                     re.IGNORECASE)
# tools/roadmap writes these regions from the milestones GitHub returns for
# the clone it runs in: their links follow the repository when regenerated.
GENERATED = re.compile(rb"<!-- roadmap:([a-z-]+):begin -->.*?<!-- roadmap:\1:end -->", re.DOTALL)


def fixed_targets(root, paths=FOLLOWING_PATHS):
    """Each `path:line` under PATHS that names ClosedWiz's repository."""
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
        # setup.py adds the repository it runs for: its --repo, or its clone's origin.
        manifest = json.loads((HERE / "manifest.json").read_text())
        self.assertNotIn("url", manifest)
        self.assertEqual(manifest["hook_attributes"], {"active": False})

    def test_manifest_is_exactly_the_service_profile(self):
        manifest = json.loads((HERE / "manifest.json").read_text())
        self.assertEqual(manifest["default_permissions"], SERVICE)
        self.assertEqual(manifest["default_events"], [])
        # Revision 3 of spec #2537: one public App installs on both accounts (GI4, #2546).
        self.assertIs(manifest["public"], True)


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
                # GI4 (#2546): the agent mode reconciles the App's owner and profile.
                status, result = 200, {"id": 1001, "slug": "synthetic-app",
                                       "permissions": behavior.get("app_permissions", SERVICE)}
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
                    # A lost reply: GitHub may have created the App.
                    self.connection.shutdown(2)
                    return
                result = {"id": 1001, "pem": pem.decode(), "slug": "synthetic-app",
                          "html_url": "https://github.com/apps/synthetic-app",
                          "permissions": behavior["converted"]}
            elif self.path == "/app/installations/2002/access_tokens":
                result = {"token": behavior["token"],
                          "expires_at": behavior["expires_at"],
                          "permissions": behavior["permissions"]}
                # C8: a read token downscoped to selected repositories names them.
                result.update(behavior.get("read_profile", {}))
            else:
                result = {"message": pem.decode()}
            if behavior["status"] != 201:
                result = {"message": pem.decode()}
            self.send_response(behavior["status"])
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, behavior
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


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
        # Include the full PEM and each body line, not just its banner.
        needles = [self.pem] + self.pem.splitlines()[1:-1]
        for output in outputs:
            if isinstance(output, str):
                output = output.encode()
            for needle in needles:
                self.assertNotIn(needle, output)

    def token(self, endpoint, device_now=None):
        self.assertTrue((HERE / "mint-token.py").is_file())
        command = ["python3", str(HERE / "mint-token.py")]
        if device_now is not None:
            # Run the real CLI with a controlled device clock, never a wall-clock race.
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
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)


class TokenTests(KeyFixture):
    def test_fresh_token_allows_clock_skew_but_expired_or_far_future_refused(self):
        # Known UTC literals: one-hour token + up to five minutes of device drift.
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
            self.assertEqual(len(calls), 11)
            self.assert_no_key(repr(calls))

    def test_signs_real_jwt_and_prints_only_read_token(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            behavior["expires_at"] = "2026-01-01T01:00:00Z"
            result = self.token(endpoint, device_now="2026-01-01T00:00:00+00:00")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"synthetic-installation-token\n1767229200\n")
        self.assertEqual(result.stderr, b"")
        self.assertEqual(len(calls), 1)
        path, headers, body = calls[0]
        self.assertEqual(path, "/app/installations/2002/access_tokens")
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
            self.assertEqual(len(calls), len(cases))
        self.assertEqual(sorted(p.name for p in self.app.iterdir()),
                         ["app.json", "private-key.pem"])


class ReadProfileTests(KeyFixture):
    """C8 (#2315): agent read tokens, downscoped to the selected repositories."""
    SELECTED = {"repository_selection": "selected", "repositories": [
        {"full_name": "synthetic-owner/other"}, {"full_name": "Synthetic-Owner/Work"}]}

    def read_token(self, endpoint, *repositories):
        return subprocess.run(["python3", str(HERE / "mint-token.py"), "--state-dir", str(self.state),
                               "--installation-id", "2002", "--api-base", endpoint,
                               *[a for r in repositories for a in ("--repository", r)]],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)

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
        self.assertEqual(json.loads(calls[0][2]),
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
            # Mixed owners and duplicates refuse before any call.
            self.assertEqual(len(calls), len(cases) - 2)


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
            self.assertEqual(len(calls), 1)
            self.assert_no_key(result.stderr)


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
        """A copy of the tool in a synthetic clone whose origin is ORIGIN (None: no origin)."""
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
        # With no key saved, only the repository can stop setup before it announces its page.
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
            # Exit or an announced URL distinguishes refusal from starting setup.
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
        self.config.unlink()  # a key without app.json: a partial save stays untouched
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
            # Retry, reload or a new preview: refused before any server or call.
            for extra in ((), ("--yes", "--operation", self.operation)):
                result = subprocess.run(["python3", str(HERE / "setup.py"), "--state-dir", str(self.state),
                                         "--api-base", endpoint, "--port", "0",
                                         "--repo", "synthetic-owner/synthetic-repo", *extra],
                                        capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 6, result.stderr)
                self.assertIn(self.operation.encode(), result.stderr)
                self.assertEqual(result.stdout, b"")
            self.assertEqual(len(calls), 1)
            # Only the owner's explicit check of GitHub allows a new proposal;
            # the uncertain record stays.
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
            process.kill()  # interrupted before the installation callback
            process.communicate(timeout=10)
            self.assertEqual(self.setup_state()["operations"][0]["phase"], "uncertain")
            self.assertTrue(self.key.exists())
            # Review R8: the same request reloads the same operation, which now
            # reconciles the saved App instead of registering one.
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
        """Confirms a proposal whose conversion reply is lost: returns its id."""
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
        # Review R3: two confirmations of one proposal; only the first claim converts.
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
        # Review R3: acknowledging A never covers a later lost attempt B.
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
        # Review R3 (re-check): C acknowledged only A and was authorized; B then
        # became uncertain. C's claim must see B and send nothing.
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
        # Review R8 (re-check): B (after uncertain A) completes; its retry and
        # reload with the same acknowledgment return B's applied result.
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
        # Review R4: later proposals evict settled or proposed records, never uncertain ones.
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
            # With only uncertain records left, nothing new is proposed.
            def fill(value):
                value["operations"] = [dict(o, phase="uncertain", operation_id=f"{n:032x}")
                                       for n, o in enumerate([value["operations"][0]] * 64)]
            setup.update(fill)
            with self.assertRaises(store.Refused):
                setup.propose("prepare_project", {"n": "more"}, ["Synthetic."], "Synthetic.")
            self.assertEqual(len(self.setup_state()["operations"]), 64)

    def test_the_packaged_app_tool_runs_from_an_installed_runtime(self):
        # #1105 R9: the collector's runtime/ layout, outside any repository.
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
        # Review R8: retry and reload of a completed connection reuse its id and do nothing.
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



# GI4 (#2546): a stand-in for Cloudroom's agent-side secret store (assumption
# A1). It records its arguments, environment and stdin, the only place the key
# may go, in a file outside the state directory. It fails a write whose name is
# in the fail file ("*": every write).
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
    """(status, headers, body) of one local request; a redirect is never followed,
    so no test reaches GitHub."""
    try:
        with urllib.request.build_opener(NoFollow()).open(url, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.headers, error.read()


class AgentSetupTests(KeyFixture):
    """GI4 (#2546): the agent mode prepares the one App for a named account and
    puts the converted key only into the Cloudroom secret seam."""

    def setUp(self):
        super().setUp()
        # The agent mode never uses the host's saved App: start with none.
        self.key.unlink()
        self.config.unlink()
        root = Path(self.tmp.name)
        self.sink = root / "secret-store.jsonl"
        self.failing = root / "secret-store-fails"
        self.store = root / "fake-secret-store"
        self.store.write_text(f"#!{sys.executable} -I\n" + STORE_SCRIPT.format(sink=str(self.sink),
                                                                               fail=str(self.failing)))
        self.store.chmod(0o700)
        # Every openssl the setup runs logs its arguments: the key never rides in one.
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
        return ["python3", str(HERE / "setup.py"), "--state-dir", str(self.state), "--api-base", endpoint,
                "--port", "0", *account, *(("--secret-store", str(self.store)) if store else ()), *extra]

    def stored(self, delivered, app_id="1001"):
        """The environment, with the secret as Cloudroom delivers it when DELIVERED
        (APP_ID None: the key alone, a partial delivery)."""
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
        """Preview, confirm, and (with OPEN) open the announced page: (process, line, start, form, base)."""
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
        """A completed registration and installation, with the store."""
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
        """No key, base64 key or conversion code in any output, argument or file
        left behind: only the secret store's own record holds the key."""
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
        # The code rides only in GitHub's own conversion path; no key in any request.
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
        """A delivered-key run: (process, line, page, base, install state)."""
        process, line, (status, headers, page), form, base = self.agent_start(
            endpoint, account, env or self.stored(True), store)
        self.assertEqual((status, form.values), (303, {}))
        self.assertTrue(headers["Location"].startswith(INSTALL_LINK), headers["Location"])
        state = urllib.parse.parse_qs(urllib.parse.urlsplit(headers["Location"]).query)["state"][0]
        return process, line, page, base, state

    def test_agent_page_carries_exactly_the_contract_profile(self):
        app = self.pin["app"]
        for account, target in (
                (("--agent-for", "synthetic-owner"), "https://github.com/settings/apps/new?state="),
                (ORG, "https://github.com/organizations/synthetic-org/settings/apps/new?state=")):
            with self.subTest(account=account), fake_github(self.pem) as (endpoint, calls, _behavior):
                shutil.rmtree(self.state / "setup", ignore_errors=True)
                process, line, (status, headers, page), form, base = self.agent_start(endpoint, account)
                process.kill()
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(status, 200)
                self.assertTrue(form.action.startswith(target), form.action)
                home = "https://github.com/" + account[1]
                self.assertEqual(json.loads(form.values["manifest"]), {
                    "name": app["name"], "public": app["visibility"] == "public",
                    "default_permissions": app["permissions"], "default_events": app["events"],
                    "url": home, "hook_attributes": {"url": home, "active": app["webhook"]},
                    "redirect_url": base + "/callback", "setup_url": base + "/installed",
                    "setup_on_update": True})
                # The page goes on to GitHub by itself: Create on GitHub is the first click.
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
        # The key, base64 on one line, and the public App id: nothing else, no environment.
        self.assertEqual(self.records(), [
            {"argv": ["OPENWIZ_GITHUB_APP_KEY"], "env": {}, "stdin": self.secret + "\n"},
            {"argv": ["OPENWIZ_GITHUB_APP_ID"], "env": {}, "stdin": "1001\n"}])
        self.assertEqual(self.phases(), ["applied"])
        self.assertEqual(self.recorded_app(), {"app_id": 1001})  # the public id, recorded here
        self.assertIsNone(self.setup_state()["app"])  # the host's App record stays the host's
        self.assertIn(b"Installation 2002 read back", stdout)
        self.assert_nothing_left(line, page, answer, stdout, stderr)
        self.assert_calls_hold_no_key(calls)

    def test_agent_without_a_store_discards_the_converted_key_cleanly(self):
        # J27 (a): with no agent-side store, the key is discarded and the person
        # pastes a fresh one from GitHub; the App id stays recorded.
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
            self.assertFalse(self.openssl_log.exists())  # the discarded key was never handled
            self.assert_nothing_left(line, page, answer, stdout, stderr)
            # The pasted key alone (no id delivered) reconciles the same App: no Create, no store.
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
                # A lost reply: nothing recorded, the operation blocks. A stored-nothing App: its id blocks.
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
        # Review R4: GitHub creates the App at Create, before any callback.
        with fake_github(self.pem) as (endpoint, calls, _behavior):
            process, line, url, _form, base = self.agent_start(endpoint, open=False)
            self.assertEqual(self.phases(), ["proposed"])
            first = fetch(url)
            self.assertEqual(self.phases(), ["uncertain"])
            again = fetch(url)  # a reload serves the same claim, never a second one
            self.assertEqual((first[0], again[0]), (200, 200))
            self.assertEqual(self.phases(), ["uncertain"])
            process.kill()  # stopped after Create, before the callback
            process.communicate(timeout=10)
            for extra in ((), ("--yes", "--operation", self.operation)):
                result = self.agent_run(endpoint, extra)
                self.assertEqual(result.returncode, 6, result.stderr)
                self.assertIn(self.operation.encode(), result.stderr)
            self.assertEqual(calls, [])
            # One running instance converts once: a second callback is refused.
            shutil.rmtree(self.state / "setup")
            process, line, (_s, _h, page), form, base = self.agent_start(endpoint)
            state, _answer = self.callback(base, form)
            self.callback(base, form, expect=400)
            self.installed(base, state)
            process.communicate(timeout=10)
            self.assertEqual([c[0] for c in calls], ["/app-manifests/synthetic-code/conversions",
                                                     "/app/installations/2002"])

    def test_agent_claim_rechecks_the_newest_uncertain_registration_under_the_lock(self):
        # Authorized while nothing was uncertain; another registration then became
        # uncertain. This claim must see it and release no form.
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
        # Review R2: one App. Another account, without the key delivered, never gets Create.
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
            # A delivered id that is not the recorded App's is refused before any call.
            result = self.agent_run(endpoint, env=self.stored(True, "1002"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(len(calls), 2)

    def test_agent_id_without_its_key_refuses_registration(self):
        # Review R6: an App id delivered without its key names an existing App (a fresh
        # sandbox on the J27 path): refuse until the key arrives; never offer Create.
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
        # A misplaced value in the id variable is refused without being echoed.
        with fake_github(self.pem) as (endpoint, calls, _b):
            result = self.agent_run(endpoint, env=dict(self.env, OPENWIZ_GITHUB_APP_ID=self.secret[:64]))
            self.assertEqual(result.returncode, 6, result.stderr)
            self.assertIn(b"App (not an id) is delivered without its key", result.stderr)
            self.assertNotIn(self.secret[:64].encode(), result.stderr)
            self.assertEqual(calls, [])

    def test_agent_second_run_reconciles_instead_of_registering(self):
        with fake_github(self.pem) as (endpoint, calls, behavior):
            self.register(endpoint)
            # With the secret delivered, the one App is reconciled and only its install is
            # offered, on this account or another one it installs on.
            outputs = []
            for login, account in (("synthetic-owner", ("--agent-for", "synthetic-owner")),
                                   ("synthetic-org", ORG)):
                behavior["installations"] = {2002: login}
                process, line, page, base, state = self.reconcile_start(endpoint, account)
                answer = self.installed(base, state)
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn(f"Installation 2002 read back: {login}".encode(), stdout)
                outputs += [line, page, answer, stdout, stderr]
        self.assertEqual([c[0] for c in calls][2:], ["/app", "/app/installations/2002"] * 2)
        self.assertEqual(len(self.records()), 2)  # the store was not called again
        self.assertEqual(self.phases(), ["applied"] * 3)
        self.assert_nothing_left(*outputs)
        self.assert_calls_hold_no_key(calls)

    def test_agent_completed_reconciliation_is_checked_again_every_run(self):
        # Review R1: after an uninstall the install is offered again; after a profile change, refused.
        with fake_github(self.pem) as (endpoint, calls, behavior):
            self.register(endpoint)
            process, _line, _page, base, state = self.reconcile_start(endpoint)
            self.installed(base, state)
            process.communicate(timeout=10)
            done = self.operation
            # The completed operation is not replayed as done: it must be previewed again.
            replay = self.agent_run(endpoint, ("--yes", "--operation", done), env=self.stored(True))
            self.assertNotEqual(replay.returncode, 0)
            self.assertNotIn(b'"applied"', replay.stdout)
            behavior["installations"] = {}  # uninstalled on GitHub
            process, _line, _page, base, state = self.reconcile_start(endpoint)
            self.assertNotEqual(self.operation, done)
            self.installed(base, state, expect=400)
            process.kill()
            process.communicate(timeout=10)
            behavior["app_permissions"] = PERMISSIONS  # the profile changed on GitHub
            operation = self.agent_preview(endpoint, env=self.stored(True))["operation_id"]
            result = self.agent_run(endpoint, ("--yes", "--operation", operation), env=self.stored(True))
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"http://127.0.0.1", result.stdout)
        self.assertEqual([c[0] for c in calls][2:], ["/app", "/app/installations/2002", "/app",
                                                     "/app/installations/2002", "/app"])
        self.assertEqual(len(self.records()), 2)

    def test_agent_partial_delivery_is_repaired_without_another_conversion(self):
        # Review R5: the key was stored, the id write failed (or setup stopped between them).
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
            # The delivered key alone: authenticated, the id is written, the key never again.
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
                self.assertEqual(self.phases(), ["applied"])  # registered and stored; not installed
                self.assertNotIn(b"read back", stdout)
                self.assert_nothing_left(line, page, answer, stdout, stderr)

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


sys.path.insert(0, str(HERE))  # GI3 (#2545): the identity contract's fixture test runs with release:github-app
from test_identity_contract import *  # noqa: E402,F401,F403

if __name__ == "__main__":
    unittest.main(verbosity=2)
