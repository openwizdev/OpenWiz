#!/usr/bin/env python3
import base64
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
SCHEMA = json.loads((FIXTURES.parents[1] / "token-service.v1.schema.json").read_text())
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("contract_fixtures", FIXTURES / "test_fixtures.py")
CONTRACT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(CONTRACT)


def openssl(*args, data=b"", fds=()):
    return subprocess.run(["/usr/bin/openssl", *args], input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, check=True, pass_fds=fds).stdout


class Asker:
    def __init__(self, *algorithm):
        algorithm = algorithm or ("RSA", "-pkeyopt", "rsa_keygen_bits:3072")
        self.private = openssl("genpkey", "-algorithm", *algorithm)
        self.key = openssl("pkey", "-pubout", data=self.private).decode()

    def open(self, sealed):
        data, token = base64.b64decode(sealed, validate=True), b""
        for at in range(0, len(data), 384):
            reader, writer = os.pipe()
            os.write(writer, self.private)
            os.close(writer)
            token += openssl("pkeyutl", "-decrypt", "-inkey", f"/dev/fd/{reader}", "-pkeyopt", "rsa_padding_mode:oaep",
                             "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256",
                             data=data[at:at + 384], fds=(reader,))
            os.close(reader)
        return token.decode()


ASKER = Asker()
REQUESTS = CONTRACT.filled(json.loads((FIXTURES / "requests.json").read_text()), ASKER.key)
NOW = REQUESTS["now"]
CASE = {case["name"]: case["request"] for case in REQUESTS["cases"]}
WRITE = CASE["a good write request gets the App's profile for one repository"]
SMALL = CASE["repository names match the installation in any case"]
INSTALLATION = 2002
CLOCK = ("import runpy, sys, time\n"
         "clock = sys.argv[1]; time.time = lambda: float(open(clock).read())\n"
         "sys.argv = sys.argv[2:]\n"
         "runpy.run_path(sys.argv[0], run_name='__main__')\n")
AUDIT = ("import json, os, stat, sys\n"
         "log = open(sys.argv.pop(1), 'a')\n"
         "def hook(event, args):\n"
         "    if event == 'subprocess.Popen':\n"
         "        pipes = [stat.S_ISFIFO(os.stat(a).st_mode) for a in args[1] if a.startswith('/dev/fd/')]\n"
         "        env = dict(os.environ) if args[3] is None else args[3]\n"
         "        log.write(json.dumps([args[1], env, pipes]) + '\\n'); log.flush()\n"
         "    if event == 'open' and isinstance(args[0], (str, bytes)) and args[2] & 3:\n"
         "        log.write(json.dumps(['OPENED', str(args[0])]) + '\\n'); log.flush()\n"
         "sys.addaudithook(hook)\n") + CLOCK


SYNC = ("import errno, fcntl, json, os, sys\n"
        "fault, log, seen = (os.environ[k] for k in ('SYNC_FAULT', 'SYNC_LOG', 'SYNC_SEEN'))\n"
        "clock = sys.argv[1]\n"
        "real_fsync, real_write = os.fsync, os.write\n"
        "def ours(fd):\n"
        "    try:\n"
        "        held, path = os.fstat(fd), os.stat(log)\n"
        "    except OSError:\n"
        "        return False\n"
        "    return (held.st_dev, held.st_ino) == (path.st_dev, path.st_ino)\n"
        "def fsync(fd):\n"
        "    if ours(fd):\n"
        "        if fault == 'fail':\n"
        "            raise OSError(errno.EIO, 'synthetic sync failure')\n"
        "        probe = os.open(log, os.O_RDONLY)\n"
        "        try:\n"
        "            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "            held = False\n"
        "        except BlockingIOError:\n"
        "            held = True\n"
        "        finally:\n"
        "            os.close(probe)\n"
        "        with open(log) as text, open(seen, 'a') as out:\n"
        "            out.write(json.dumps([held, text.read()]) + '\\n')\n"
        "        with open(clock) as now, open(clock + '.next', 'w') as later:\n"
        "            later.write(str(float(now.read()) + 12))\n"
        "        os.replace(clock + '.next', clock)\n"
        "    return real_fsync(fd)\n"
        "def write(fd, data):\n"
        "    if fault == 'short' and ours(fd) and b'\"expiry\"' in data:\n"
        "        return real_write(fd, data[:len(data) // 2])\n"
        "    return real_write(fd, data)\n"
        "os.fsync, os.write = fsync, write\n") + CLOCK
EXPIRY = next(case for case in REQUESTS["cases"] if case.get("github") == "expiry")


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

    def mint(self, endpoint, request, env=None, audit=None, script=None):
        text = request if isinstance(request, str) else json.dumps(request)
        self.clock.write_text(str(NOW))
        environment = {k: v for k, v in os.environ.items() if k != "OPENWIZ_GITHUB_APP_MODE"}
        environment["OPENWIZ_SYNTHETIC_GITHUB"] = "1"
        program = script or (AUDIT if audit else CLOCK)
        prefix = [str(audit)] if audit else []
        return subprocess.run(["python3", "-I", "-c", program, *prefix,
                               str(self.clock), str(SERVICE), "mint",
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
                fake["token"] = case.get("token", "synthetic-refused-token")
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
                got = json.loads(done.stdout)
                if message["kind"] == "answer":
                    self.assert_valid(got)
                    self.assertEqual(ASKER.open(got["sealed_token"]), case["token"])
                    got["sealed_token"] = message["sealed_token"]
                self.assertEqual(got, message)
                self.assertEqual(len(self.logged()), number, "one log line per request")
                self.assertEqual(self.logged()[-1], case["out"]["log"])
                self.assert_valid(self.logged()[-1])
                minted = [c for c in calls if c[0] == "POST"]
                if message["kind"] == "answer":
                    self.assertEqual(minted[0][2], {"repositories": [r.split("/")[1] for r in case["request"]["repositories"]],
                                                    "permissions": case["request"]["permissions"]})
                self.assert_nothing_exposed(fake["token"], done.stdout, done.stderr)
                if message.get("refusal") in ("usage", "one-owner", "not-installed", "permission"):
                    self.assertEqual(minted, [], "no token is minted for a refused request")
                if message.get("refusal") in ("usage", "one-owner"):
                    self.assertEqual(calls, [], "no GitHub call for a request refused on its face")

    def test_every_message_the_schema_refuses_is_a_usage_refusal_with_no_github_call(self):
        invalid = CONTRACT.filled(json.loads((FIXTURES / "invalid.json").read_text()), ASKER.key)["cases"]
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

    def sync_mint(self, url, fault, request):
        seen = Path(self.tmp.name) / "seen"
        seen.unlink(missing_ok=True)
        done = self.mint(url, request, script=SYNC,
                         env={"SYNC_FAULT": fault, "SYNC_LOG": str(self.log), "SYNC_SEEN": str(seen)})
        return done, [json.loads(line) for line in seen.read_text().splitlines()] if seen.exists() else []

    def test_a_sync_after_the_append_that_uses_up_the_allowance_leaves_one_expiry_line(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, calls, fake):
            fake["expires_at"] = NOW + 311
            done, seen = self.sync_mint(url, "slow", EXPIRY["request"])
            self.assertEqual((done.returncode, json.loads(done.stdout)), (5, EXPIRY["out"]["message"]))
            self.assertEqual([json.loads(text)["outcome"] for text in seen[0][1].splitlines()], ["minted"])
            self.assertEqual([held for held, _ in seen], [True, True], "the log stays locked until its last sync")
            self.assertEqual(self.logged(), [EXPIRY["out"]["log"]])
            self.assert_valid(self.logged()[0])
            self.assertEqual(revoked(calls), ["Bearer synthetic-token"])
            fake["expires_at"] = NOW + 360
            done, _seen = self.sync_mint(url, "slow", EXPIRY["request"])
            self.assertEqual(done.returncode, 0)
            self.assertEqual([line["outcome"] for line in self.logged()], ["expiry", "minted"])
            self.assertEqual(revoked(calls), ["Bearer synthetic-token"])

    def test_a_failed_audit_sync_revokes_the_minted_token_and_leaves_no_line(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, calls, _fake):
            done, _seen = self.sync_mint(url, "fail", EXPIRY["request"])
            self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (1, "unavailable"))
            self.assertEqual(revoked(calls), ["Bearer synthetic-token"])
            self.assertEqual(self.log.read_text(), "")
            self.assert_nothing_exposed("synthetic-token", done.stdout, done.stderr)

    def test_a_short_write_of_the_expiry_line_leaves_one_valid_unavailable_line(self):
        with fake_github(self.pem, REQUESTS["installed"]) as (url, calls, fake):
            fake["expires_at"] = NOW + 311
            done, _seen = self.sync_mint(url, "short", EXPIRY["request"])
            self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (1, "unavailable"))
            self.assertEqual(self.logged(), [dict(EXPIRY["out"]["log"], outcome="unavailable")])
            self.assert_valid(self.logged()[0])
            self.assertEqual(revoked(calls), ["Bearer synthetic-token"])


class SealingTests(ServiceFixture):
    def test_a_token_of_any_length_github_gives_is_sealed_or_revoked(self):
        # comment-ok: catches: a service that seals one RSA-OAEP block only, so GitHub's 520-character tokens
        # are never minted, or one that hands over or keeps a live token it could not seal.
        with fake_github(self.pem, REQUESTS["installed"]) as (url, calls, fake):
            for length in (40, 318, 319, 520, 8 * 318):
                with self.subTest(length):
                    fake["token"] = ("ghs-" + "a1_.b-" * 500)[:length]
                    done = self.mint(url, SMALL)
                    self.assertEqual((done.returncode, done.stderr), (0, ""))
                    self.assertEqual(ASKER.open(json.loads(done.stdout)["sealed_token"]), fake["token"])
                    self.assert_nothing_exposed(fake["token"], done.stdout)
            self.assertEqual(revoked(calls), [])
            fake["token"] = "a" * (8 * 318 + 1)
            done = self.mint(url, SMALL)
            self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal")), (1, "unavailable"))
            self.assertEqual(revoked(calls), ["Bearer " + fake["token"]])
            self.assertEqual(self.logged()[-1]["outcome"], "unavailable")
            self.assert_nothing_exposed(fake["token"], done.stdout, done.stderr)

    def test_a_bad_answer_key_is_a_usage_refusal_and_mints_nothing(self):
        # comment-ok: catches: a token minted, then sealed to a key that is absent, weak or not the helper's kind.
        rsa = lambda *options: Asker("RSA", *options).key
        keys = {"missing": None, "empty": "", "not text": 7, "malformed": "not a key", "a private key": ASKER.private.decode(),
                "cut short": ASKER.key[:-40], "junk after": ASKER.key + "x", "a second key": ASKER.key * 2, "a blank line after": ASKER.key + "\n",
                "CRLF": ASKER.key.replace("\n", "\r\n"),
                "broken base64": ASKER.key.replace("A", "!"), "2048": rsa("-pkeyopt", "rsa_keygen_bits:2048"),
                "4096": CONTRACT.public_key(4096), "3071": CONTRACT.public_key(3072).replace("/", "B", 1),
                "exponent 1": CONTRACT.public_key(exponent=1),
                "exponent 3": rsa("-pkeyopt", "rsa_keygen_bits:3072", "-pkeyopt", "rsa_keygen_pubexp:3"),
                "EC": Asker("EC", "-pkeyopt", "ec_paramgen_curve:P-256").key, "Ed25519": Asker("ED25519").key,
                "RSA-PSS": Asker("RSA-PSS", "-pkeyopt", "rsa_keygen_bits:3072").key}
        with fake_github(self.pem, REQUESTS["installed"]) as (url, calls, _fake):
            for name, key in keys.items():
                with self.subTest(name):
                    request = dict(SMALL, answer_key=key)
                    if key is None:
                        del request["answer_key"]
                    self.assertNotEqual(CONTRACT.errors(request, SCHEMA, SCHEMA), [], "the schema refuses it too")
                    done = self.mint(url, request)
                    self.assertEqual((done.returncode, json.loads(done.stdout).get("refusal"), done.stderr),
                                     (2, "usage", ""))
                    self.assertEqual(calls, [])
                    self.assertEqual(set(self.logged()[-1]), {"schema", "kind", "at", "requester", "outcome"})
            self.assertEqual(self.mint(url, SMALL).returncode, 0, "the good key still mints")

    def test_the_token_and_the_answer_key_reach_openssl_only_through_pipes(self):
        # comment-ok: catches: a token or key on openssl's command line, in its environment or in a temporary file.
        log = Path(self.tmp.name) / "audit.jsonl"
        with fake_github(self.pem, REQUESTS["installed"]) as (url, _calls, fake):
            fake["token"] = "synthetic-token-" + "x1" * 252
            self.assertEqual(self.mint(url, SMALL, audit=log).returncode, 0)
        rows = [json.loads(line) for line in log.read_text().splitlines()]
        started = [row for row in rows if row[0] != "OPENED"]
        sealed = [row for row in started if "-encrypt" in row[0]]
        self.assertEqual([(row[0][0], row[1], row[2]) for row in sealed], [("/usr/bin/openssl", {}, [True])] * 2)
        for needle in (fake["token"], *ASKER.key.splitlines()[1:-1]):
            self.assertNotIn(needle, json.dumps(started))
        self.assertEqual({row[1] for row in rows if row[0] == "OPENED"}, {"mint-log.jsonl"}, "no other file is written")


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
        self.assertEqual(ASKER.open(json.loads(done.stdout)["sealed_token"]), "synthetic-secret-token")
        self.assert_nothing_exposed("synthetic-secret-token", done.stdout, done.stderr)
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
