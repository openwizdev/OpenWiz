#!/usr/bin/env python3
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import unittest

HERE = Path(__file__).resolve().parent
SERVICE = HERE / "token-service.py"
FIXTURES = HERE.parents[1] / "contracts/fixtures/token-service"
REQUESTS = json.loads((FIXTURES / "requests.json").read_text())
SCHEMA = json.loads((FIXTURES.parents[1] / "token-service.v1.schema.json").read_text())
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("contract_fixtures", FIXTURES / "test_fixtures.py")
CONTRACT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CONTRACT)
NOW = REQUESTS["now"]
CASE = {case["name"]: case["request"] for case in REQUESTS["cases"]}
WRITE = CASE["a good write request gets the App's profile for one repository"]
SMALL = CASE["repository names match the installation in any case"]
INSTALLATION = 2002
CLOCK = ("import runpy, sys, time\n"
         "clock = sys.argv[1]; time.time = lambda: float(open(clock).read())\n"
         "sys.argv = sys.argv[2:]\n"
         "runpy.run_path(sys.argv[0], run_name='__main__')\n")


def revoked(calls):
    return [c[2] for c in calls if c[:2] == ("DELETE", "/installation/token")]


@contextmanager
def fake_github(pem, installed):
    calls = []
    behavior = {"token": "synthetic-token", "expires_at": NOW + 3600, "status": 201, "grant": {},
                "app_owner": "synthetic-owner", "account": "synthetic-owner", "clock": None, "elapse": 0}
    owners = {name.lower() for name in installed}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, result):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_GET(self):
            calls.append(("GET", self.path, None))
            found = re.fullmatch(r"/repos/([^/]+)/([^/]+)/installation", self.path)
            if self.path == "/app":
                self.reply(200, {"id": 1001, "owner": {"login": behavior["app_owner"]}})
            elif found and f"{found[1]}/{found[2]}".lower() in owners:
                self.reply(200, {"id": INSTALLATION, "app_id": 1001, "account": {"login": behavior["account"]},
                                 "repository_selection": "selected"})
            else:
                self.reply(404, {"message": pem.decode()})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            calls.append(("POST", self.path, body))
            if self.path != f"/app/installations/{INSTALLATION}/access_tokens" or behavior["status"] != 201:
                return self.reply(behavior["status"] if behavior["status"] != 201 else 404, {"message": pem.decode()})
            if behavior["clock"]:
                behavior["clock"].write_text(str(NOW + behavior["elapse"]))
            at = datetime.fromtimestamp(behavior["expires_at"], timezone.utc).isoformat().replace("+00:00", "Z")
            result = {"token": behavior["token"], "expires_at": at, "permissions": body["permissions"],
                      "repository_selection": "selected",
                      "repositories": [{"full_name": behavior["account"] + "/" + n.lower()} for n in body["repositories"]]}
            result.update(behavior["grant"])
            self.reply(201, result)

        def do_DELETE(self):
            calls.append(("DELETE", self.path, self.headers.get("Authorization")))
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


def closed_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="openwiz-token-service-")
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "state"
        self.app = self.state / "service/app"
        self.app.mkdir(parents=True, mode=0o700)
        for path in (self.state, self.state / "service"):
            path.chmod(0o700)
        self.key = self.app / "private-key.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                        "-out", str(self.key)], check=True, capture_output=True)
        self.key.chmod(0o600)
        self.pem = self.key.read_bytes()
        (self.app / "app.json").write_text('{"app_id":1001}')
        (self.app / "app.json").chmod(0o600)
        self.log = self.state / "service/token-service/mint-log.jsonl"
        self.clock = Path(self.tmp.name) / "clock"
        self.assertEqual(self.control("start").returncode, 0)

    def control(self, command, env=None):
        return subprocess.run(["python3", "-I", str(SERVICE), command, "--state-dir", str(self.state)],
                              capture_output=True, text=True, timeout=60, env=dict(os.environ, **(env or {})))

    def mint(self, endpoint, request, env=None):
        text = request if isinstance(request, str) else json.dumps(request)
        self.clock.write_text(str(NOW))
        environment = {k: v for k, v in os.environ.items() if k != "OPENWIZ_GITHUB_APP_MODE"}
        return subprocess.run(["python3", "-I", "-c", CLOCK, str(self.clock), str(SERVICE), "mint",
                               "--state-dir", str(self.state), "--api-base", endpoint],
                              input=text, capture_output=True, text=True, timeout=60,
                              env=dict(environment, **(env or {})))

    def logged(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_valid(self, message):
        self.assertEqual(CONTRACT.errors(message, SCHEMA, SCHEMA), [], message)

    def assert_nothing_exposed(self, token, *outputs):
        needles = [token.encode(), *self.pem.splitlines()[1:-1]]
        places = [(f"output {n}", o.encode()) for n, o in enumerate(outputs, 1)]
        places += [(str(p.relative_to(self.state)), p.read_bytes()) for p in self.state.rglob("*")
                   if p.is_file() and p != self.key]
        for place, content in places:
            for needle in needles:
                self.assertFalse(needle in content, f"a secret reached {place}")


class RequestFixtureTests(ServiceFixture):
    def test_every_request_fixture_gets_its_answer_exit_and_log_line(self):
        for number, case in enumerate(REQUESTS["cases"], 1):
            with self.subTest(case["name"]), fake_github(self.pem, REQUESTS["installed"]) as (url, calls, fake):
                message = case["out"]["message"]
                fake["token"] = message.get("token", "synthetic-refused-token")
                fake["expires_at"] = message.get("expires_at", NOW + 3600)
                endpoint = url
                if case.get("github") == "github":
                    fake["status"] = 403
                elif case.get("github") == "expiry":
                    fake["expires_at"] = NOW + 300
                elif case.get("github") == "unavailable":
                    endpoint = closed_port()
                done = self.mint(endpoint, case["request"])
                self.assertEqual((done.returncode, done.stderr), (case["out"]["exit"], ""))
                self.assertEqual(done.stdout.count("\n"), 1, "one JSON line")
                self.assertEqual(json.loads(done.stdout), message)
                self.assertEqual(len(self.logged()), number, "one log line per request")
                self.assertEqual(self.logged()[-1], case["out"]["log"])
                self.assert_valid(self.logged()[-1])
                minted = [c for c in calls if c[0] == "POST"]
                if message["kind"] == "answer":
                    self.assertEqual(minted[0][2], {"repositories": [r.split("/")[1] for r in case["request"]["repositories"]],
                                                    "permissions": case["request"]["permissions"]})
                else:
                    self.assert_nothing_exposed(fake["token"], done.stdout, done.stderr)
                if message.get("refusal") in ("usage", "one-owner", "not-installed", "permission"):
                    self.assertEqual(minted, [], "no token is minted for a refused request")
                if message.get("refusal") in ("usage", "one-owner"):
                    self.assertEqual(calls, [], "no GitHub call for a request refused on its face")

    def test_every_message_the_schema_refuses_is_a_usage_refusal_with_no_github_call(self):
        invalid = json.loads((FIXTURES / "invalid.json").read_text())["cases"]
        twice = dict(SMALL, repositories=["synthetic-owner/work", "Synthetic-Owner/Work"])
        for name, message in [(c["name"], c["message"]) for c in invalid] + [("repeated in another case", twice)]:
            with self.subTest(name), fake_github(self.pem, REQUESTS["installed"]) as (url, calls, _fake):
                done = self.mint(url, message)
                self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (2, "usage"))
                self.assertEqual(calls, [])

    def test_a_grant_wider_or_other_than_the_request_is_refused(self):
        for grant in ({"permissions": {"metadata": "read", "workflows": "write"}},
                      {"repositories": [{"full_name": "synthetic-owner/work"}, {"full_name": "synthetic-owner/tools"}]},
                      {"repository_selection": "all"}, {"expires_at": "not a time"},
                      {"token": "synthetic token with spaces"}):
            with self.subTest(grant), fake_github(self.pem, REQUESTS["installed"]) as (url, calls, fake):
                fake["grant"] = grant
                done = self.mint(url, SMALL)
                self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (5, "github"))
                self.assertEqual(revoked(calls), [] if "token" in grant else ["Bearer " + fake["token"]])
                self.assertEqual(self.logged()[-1]["outcome"], "github")
                self.assert_nothing_exposed("synthetic-token", done.stdout, done.stderr)

    def test_a_token_expiring_beyond_the_contracts_bound_is_refused(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, _calls, fake):
            fake["expires_at"] = NOW + 3901
            done = self.mint(url, SMALL)
            self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (5, "expiry"))
            fake["expires_at"] = NOW + 3900
            self.assertEqual(self.mint(url, SMALL).returncode, 0)


    def test_a_token_is_checked_for_time_left_at_handover_not_at_request(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, _calls, fake):
            fake.update(clock=self.clock, elapse=15)
            fake["expires_at"] = NOW + 310
            done = self.mint(url, SMALL)
            self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (5, "expiry"))
            self.assertEqual(self.logged()[-1]["outcome"], "expiry")
            fake["expires_at"] = NOW + 15 + 311
            self.assertEqual(self.mint(url, SMALL).returncode, 0)


class FactoryTests(ServiceFixture):
    def test_the_factory_setting_given_at_start_holds_for_every_mint(self):
        text = (HERE.parents[1] / "contracts/github-identity.v1.md").read_text()
        pin = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S).group(1))
        account, repository = pin["installations"][-1]["account"], pin["installations"][-1]["repositories"][0]
        request = dict(SMALL, repositories=[repository])
        with fake_github(self.pem, request["repositories"]) as (url, _calls, fake):
            fake.update(app_owner="synthetic-elsewhere", account=account)
            self.assertEqual(self.control("start", {"OPENWIZ_GITHUB_APP_MODE": "factory"}).returncode, 0)
            self.assertEqual(self.mint(url, request).returncode, 0, "factory set at start, none at mint")
            self.assertEqual(self.control("start", {"OPENWIZ_GITHUB_APP_MODE": "user"}).returncode, 0)
            done = self.mint(url, request, {"OPENWIZ_GITHUB_APP_MODE": "factory"})
            self.assertEqual(json.loads(done.stdout).get("refusal"), "not-installed", "start's setting wins")
            self.assertEqual(self.control("start", {"OPENWIZ_GITHUB_APP_MODE": "public"}).returncode, 1)


class NeverExposedTests(ServiceFixture):
    def test_the_log_and_state_hold_no_token_and_the_key_and_log_stay_owner_only(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, _calls, fake):
            fake["token"] = "synthetic-secret-token"
            done = self.mint(url, WRITE)
        self.assertEqual(json.loads(done.stdout)["token"], "synthetic-secret-token")
        self.assert_nothing_exposed("synthetic-secret-token", done.stderr)
        self.assertEqual(stat.S_IMODE(self.key.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.log.parent.stat().st_mode), 0o700)

    def test_an_unsafe_key_or_log_is_unavailable_before_any_github_call(self):
        cases = [("key", lambda: self.key.chmod(0o640)),
                 ("log", lambda: self.log.chmod(0o644)),
                 ("log link", lambda: (self.log.unlink(), self.log.symlink_to(self.state / "elsewhere")))]
        for name, spoil in cases:
            with self.subTest(name), fake_github(self.pem, REQUESTS["installed"]) as (url, calls, _fake):
                self.key.chmod(0o600)
                self.log.parent.mkdir(mode=0o700, exist_ok=True)
                if self.log.is_symlink():
                    self.log.unlink()
                self.log.touch(mode=0o600)
                self.log.chmod(0o600)
                spoil()
                done = self.mint(url, WRITE)
                self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal"), done.stderr),
                                 (1, "unavailable", ""))
                self.assertEqual([c for c in calls if c[0] == "POST"], [])
                self.assert_nothing_exposed("synthetic-token", done.stdout)
                self.assertFalse((self.state / "elsewhere").exists())


class StartStopTests(ServiceFixture):
    def test_a_stopped_service_answers_like_an_unreachable_one_and_start_resumes(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, calls, _fake):
            self.assertEqual(self.control("stop").returncode, 0)
            done = self.mint(url, WRITE)
            self.assertEqual((done.returncode, done.stdout), (1, ""))
            self.assertEqual(done.stderr, "Token service stopped: the owner has not started it.\n")
            self.assertEqual(calls, [])
            self.assertEqual(self.control("start").returncode, 0)
            self.assertEqual(self.mint(url, WRITE).returncode, 0)

    def test_a_service_never_started_is_stopped(self):
        (self.state / "service/token-service/started").unlink()
        done = self.mint(closed_port(), WRITE)
        self.assertEqual((done.returncode, done.stdout), (1, ""))


class RunbookTests(unittest.TestCase):
    def test_every_link_into_the_legacy_secret_route_lands_on_the_ga2_warning(self):
        doc = (HERE.parents[1] / "docs/github-app.md").read_text()
        self.assertIn("## The token service (GA2)\n", doc)
        linked = set(re.findall(r"\]\(#([a-z0-9-]+)\)", doc))
        sections = re.split(r"(?m)^## ", doc)[1:]
        legacy = [s for s in sections if "--from-secret" in s or "OPENWIZ_GITHUB_APP_KEY" in s]
        self.assertTrue(legacy)
        for section in legacy:
            heading, _, body = section.partition("\n")
            anchor = re.sub(r"[^a-z0-9 -]", "", heading.lower()).replace(" ", "-")
            if anchor == "the-token-service-ga2" or anchor not in linked:
                continue
            first = body.strip().split("\n\n")[0]
            self.assertIn("(#the-token-service-ga2)", first, heading)
            self.assertIn("legacy", first.lower(), heading)


if __name__ == "__main__":
    unittest.main()
