#!/usr/bin/env python3
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import unittest

HERE = Path(__file__).resolve().parent
SELECTOR, SERVICE = HERE / "app-select.py", HERE / "token-service.py"
SENTENCE = ("App selector refused: set OPENWIZ_APP_SELECT_CONFIG (default ~/.config/openwiz/app-select.json) "
            "to a file you own with no group or other permission bits, naming one App state as \"state_dir\", "
            "or \"routes\" that map every requested repository to the same App state.\n")
PIN = json.loads(re.search(r"```json\n(.*?)\n```", (HERE.parents[1] / "contracts/token-service.v1.md").read_text(),
                          re.S).group(1))
APPS = {"a": (1001, 2001, {"synthetic-owner/alpha", "synthetic-owner/shared"}),
        "b": (1002, 2002, {"synthetic-owner/beta", "synthetic-owner/shared"})}
HOOK = ("import json, runpy, sys\n"
        "out = open(sys.argv[1], 'a')\n"
        "def hook(event, args):\n"
        "    if event in ('subprocess.Popen', 'os.exec', 'os.posix_spawn'):\n"
        "        out.write(json.dumps([str(a) for a in args[1]]) + '\\n'); out.flush()\n"
        "    if event == 'urllib.Request' or event == 'open' and str(args[0]).endswith('private-key.pem'):\n"
        "        out.write(json.dumps(['SELECTOR', event]) + '\\n'); out.flush()\n"
        "sys.addaudithook(hook)\n"
        "sys.argv = sys.argv[2:]\n"
        "runpy.run_path(sys.argv[0], run_name='__main__')\n")


def request(*repositories):
    return {"schema": "openwiz.token-service.v1", "kind": "request", "requester": "builder-2661",
            "repositories": list(repositories), "permissions": {"metadata": "read"}}


@contextmanager
def fake_github():
    calls = []
    by_installation = {installation: app_id for app_id, installation, _ in APPS.values()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def caller(self):
            payload = self.headers.get("Authorization", "").split(".")[1]
            return int(json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))["iss"])

        def reply(self, status, result):
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

        def do_GET(self):
            app_id = self.caller()
            calls.append(("GET", self.path, app_id))
            found = re.fullmatch(r"/repos/([^/]+/[^/]+)/installation", self.path)
            held = {(i, inst) for i, inst, repos in APPS.values() if found and found[1].lower() in repos}
            if self.path == "/app":
                return self.reply(200, {"id": app_id, "owner": {"login": "synthetic-owner"}})
            for i, installation in held:
                if i == app_id:
                    return self.reply(200, {"id": installation, "app_id": app_id, "repository_selection": "selected",
                                            "account": {"login": "synthetic-owner"}})
            self.reply(404, {"message": "Not Found"})

        def do_POST(self):
            app_id = self.caller()
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            calls.append(("POST", self.path, app_id))
            installation = int(self.path.split("/")[3])
            if by_installation.get(installation) != app_id:
                return self.reply(404, {"message": "Not Found"})
            at = datetime.fromtimestamp(time.time() + 3600, timezone.utc).isoformat().replace("+00:00", "Z")
            self.reply(201, {"token": f"synthetic-token-{app_id}", "expires_at": at, "permissions": body["permissions"],
                             "repository_selection": "selected",
                             "repositories": [{"full_name": "synthetic-owner/" + n} for n in body["repositories"]]})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class SelectorTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="openwiz-app-select-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root.chmod(0o700)
        self.states, self.keys = {}, []
        for name, (app_id, _installation, _repos) in APPS.items():
            state = self.root / f"state-{name}"
            (state / "service/app").mkdir(parents=True, mode=0o700)
            for path in (state, state / "service"):
                path.chmod(0o700)
            key = state / "service/app/private-key.pem"
            subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048",
                            "-out", str(key)], check=True, capture_output=True)
            key.chmod(0o600)
            (state / "service/app/app.json").write_text(json.dumps({"app_id": app_id}))
            (state / "service/app/app.json").chmod(0o600)
            subprocess.run(["python3", "-I", str(SERVICE), "start", "--state-dir", str(state)],
                           check=True, capture_output=True)
            self.states[name] = state
            self.keys.append(key)
        self.default = self.root / "default-state"
        self.config = self.root / "config/app-select.json"
        self.config.parent.mkdir(mode=0o700)
        self.argv_log = self.root / "argv.jsonl"
        self.outputs = []

    def configure(self, value, mode=0o600):
        self.config.write_text(value if isinstance(value, str) else json.dumps(value))
        self.config.chmod(mode)

    def select(self, url, message):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENWIZ_")}
        env.update(OPENWIZ_APP_SELECT_CONFIG=str(self.config), OPENWIZ_STATE_DIR=str(self.default))
        done = subprocess.run(["python3", "-I", "-c", HOOK, str(self.argv_log), str(SELECTOR), "mint",
                               "--api-base", url], input=json.dumps(message), capture_output=True, text=True,
                              timeout=60, env=env)
        self.outputs += [done.stdout, done.stderr]
        return done

    def started(self):
        if not self.argv_log.exists():
            return []
        return [json.loads(line) for line in self.argv_log.read_text().splitlines()]

    def selector_touches(self):
        return [argv for argv in self.started() if argv[0] == "SELECTOR"]

    def service_calls(self):
        return [argv for argv in self.started() if str(SERVICE) in argv]

    def logged(self, name):
        log = self.states[name] / "service/token-service/mint-log.jsonl"
        return log.read_text().splitlines() if log.exists() else []

    def assert_minted_by(self, done, url, name):
        app_id, installation, _ = APPS[name]
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(json.loads(done.stdout)["token"], f"synthetic-token-{app_id}")
        self.assertEqual(self.service_calls()[-1][-5:],
                         ["mint", "--state-dir", str(self.states[name]), "--api-base", url])

    def assert_refused(self, done, calls, exit_code, refusal, sentence=SENTENCE):
        pinned = PIN["refusals"][refusal]
        self.assertEqual(pinned["exit"], exit_code)
        answer = {"schema": PIN["schema"], "kind": "refusal", "refusal": refusal, "message": pinned["message"]}
        self.assertEqual((done.returncode, done.stdout, done.stderr), (exit_code, json.dumps(answer) + "\n", sentence))
        self.assertEqual([c for c in calls if c[0] == "POST"], [], "no token endpoint call")
        self.assertEqual(self.service_calls(), [], "no service call")
        self.assertEqual((self.logged("a"), self.logged("b")), ([], []))

    def tearDown(self):
        secrets = [line for key in self.keys for line in key.read_bytes().splitlines()[1:-1]]
        secrets += [f"synthetic-token-{app_id}".encode() for app_id, _, _ in APPS.values()]
        places = [("stderr", o.encode()) for o in self.outputs[1::2]]
        places += [("stdout", o.encode()) for o in self.outputs[0::2] if '"kind": "answer"' not in o]
        places += [(str(p), p.read_bytes()) for p in self.root.rglob("*") if p.is_file() and p not in self.keys]
        for place, content in places:
            for secret in secrets:
                self.assertNotIn(secret, content, f"a secret reached {place}")
        self.assertFalse(self.default.exists(), "the default state stays untouched")
        self.assertEqual(self.selector_touches(), [], "the selector opens no key and asks GitHub nothing")

    def routes(self, *pairs):
        return {"routes": [{"repository": r, "state_dir": str(self.states[n])} for r, n in pairs]}

    def test_the_route_map_reaches_the_mapped_app(self):
        self.configure(self.routes(("synthetic-owner/beta", "b"), ("synthetic-owner/*", "a")), mode=0o400)
        with fake_github() as (url, calls):
            self.assert_minted_by(self.select(url, request("synthetic-owner/beta")), url, "b")
            self.assert_minted_by(self.select(url, request("Synthetic-Owner/Alpha", "synthetic-owner/shared")),
                                  url, "a")
            self.assertEqual([c[2] for c in calls if c[0] == "POST"], [1002, 1001])
        self.assertEqual((len(self.logged("a")), len(self.logged("b"))), (1, 1))

    def test_named_uses_exactly_the_named_app(self):
        self.configure({"state_dir": str(self.states["b"])})
        with fake_github() as (url, calls):
            self.assert_minted_by(self.select(url, request("synthetic-owner/shared")), url, "b")
            self.assertEqual({c[2] for c in calls}, {1002}, "the other App is never asked")
        self.assertEqual((len(self.logged("a")), len(self.logged("b"))), (0, 1))

    def test_an_unmatched_or_split_route_refuses_and_mints_nothing(self):
        self.configure(self.routes(("synthetic-owner/beta", "b"), ("synthetic-owner/*", "a")))
        with fake_github() as (url, calls):
            self.assert_refused(self.select(url, request("synthetic-owner/alpha", "synthetic-owner/beta")),
                                calls, 1, "unavailable")
            self.configure(self.routes(("synthetic-owner/alpha", "a")))
            self.assert_refused(self.select(url, request("synthetic-owner/beta")), calls, 3, "not-installed")
            self.assert_refused(self.select(url, request("synthetic-owner/alpha", "synthetic-owner/beta")),
                                calls, 3, "not-installed")
            self.assertEqual(calls, [], "no GitHub call at all")

    def test_every_mode_refuses_an_invalid_request_before_any_service_call(self):
        bad = [(request("synthetic-owner/alpha", "other-owner/alpha"), "one-owner"),
               ({**request("synthetic-owner/alpha"), "extra": 1}, "usage"), (request(), "usage")]
        for config in ({"state_dir": str(self.states["a"])},
                       self.routes(("synthetic-owner/*", "a"), ("other-owner/*", "a"))):
            self.configure(config)
            for message, refusal in bad:
                with self.subTest(config=list(config), refusal=refusal), fake_github() as (url, calls):
                    self.assert_refused(self.select(url, message), calls, 2, refusal, sentence="")
                    self.assertEqual(calls, [], "no GitHub call at all")

    def test_a_missing_unsafe_or_unclear_config_refuses_before_any_call(self):
        a, b = str(self.states["a"]), str(self.states["b"])
        cases = [("missing", None, 0o600), ("group-readable", {"state_dir": a}, 0o640),
                 ("both keys", {"state_dir": a, "routes": []}, 0o600), ("not JSON", "{", 0o600),
                 ("resolved mode is gone", {"candidates": [a, b]}, 0o600), ("no routes", {"routes": []}, 0o600),
                 ("a route's extra key", {"routes": [{"repository": "synthetic-owner/*", "state_dir": a,
                                                      "app_id": 1}]}, 0o600),
                 ("a route's missing state", {"routes": [{"repository": "synthetic-owner/*",
                                                          "state_dir": str(self.root / "absent")}]}, 0o600),
                 *[(f"pattern {p}", {"routes": [{"repository": p, "state_dir": a}]}, 0o600)
                   for p in ("*", "*/alpha", "synthetic-owner/al*", "synthetic-owner", "synthetic-owner/*/x")],
                 ("repeated key", '{"state_dir": "%s", "state_dir": "%s"}' % (a, b), 0o600),
                 ("relative", {"state_dir": "state-a"}, 0o600), ("no candidates", {"candidates": []}, 0o600),
                 ("named state missing", {"state_dir": str(self.root / "absent")}, 0o600)]
        for name, value, mode in cases:
            with self.subTest(name), fake_github() as (url, calls):
                self.argv_log.unlink(missing_ok=True)
                for state in self.states.values():
                    (state / "service/token-service/mint-log.jsonl").unlink(missing_ok=True)
                if self.config.exists() or self.config.is_symlink():
                    self.config.unlink()
                if value is not None:
                    self.configure(value, mode)
                self.assert_refused(self.select(url, request("synthetic-owner/alpha")), calls, 1, "unavailable")
                self.assertEqual(calls, [], "no GitHub call at all")
        with self.subTest("symlink"), fake_github() as (url, calls):
            target = self.root / "config/elsewhere.json"
            target.write_text(json.dumps({"state_dir": a}))
            target.chmod(0o600)
            self.config.unlink()
            self.config.symlink_to(target)
            self.assert_refused(self.select(url, request("synthetic-owner/alpha")), calls, 1, "unavailable")


if __name__ == "__main__":
    unittest.main()
