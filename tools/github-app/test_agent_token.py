#!/usr/bin/env python3
import base64
import fcntl
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
import socketserver
import ssl
import stat
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
HELPER = HERE / "agent-token.py"
FIXTURES = ROOT / "contracts" / "fixtures" / "token-service"
PIN = json.loads((ROOT / "contracts" / "token-service.v1.md").read_text()
                 .split("```json\n", 1)[1].split("\n```", 1)[0])
SERVICE = "/synthetic/openwiz/tools/github-app/token-service.py"
REPO = "synthetic-owner/work"
WRITE = {"metadata": "read", "contents": "write", "issues": "write",
         "pull_requests": "write", "checks": "read", "actions": "read"}
READ = {name: "read" for name in WRITE}
sys.dont_write_bytecode = True
service_spec = importlib.util.spec_from_file_location("test_token_service", HERE / "test_token_service.py")
SERVICE_TESTS = importlib.util.module_from_spec(service_spec)
service_spec.loader.exec_module(SERVICE_TESTS)
TOKEN, TOKEN2 = "synthetic-agent-token-1", "synthetic-agent-token-2"
REQ = ("--requester", "builder-1", "--repository", REPO)
NOTE = PIN["fallback"]["note"]
WITHHELD = "openwiz: openwiz[bot] token withheld from git"
URL = f"https://github.com/{REPO}"

FAKE = r'''
import base64, hashlib, json, os, stat, subprocess, sys, time


def seal(token, key):
    sealed = b""
    for at in range(0, len(token), 318):
        reader, writer = os.pipe()
        os.write(writer, key.encode())
        os.close(writer)
        sealed += subprocess.run(
            ["/usr/bin/openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", f"/dev/fd/{reader}",
             "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256"],
            input=token[at:at + 318].encode(), stdout=subprocess.PIPE, check=True, pass_fds=(reader,)).stdout
        os.close(reader)
    return base64.b64encode(sealed).decode()


name, args = sys.argv[1], sys.argv[2:]
stdin = sys.stdin.read() if name != "gh" else ""
token = os.environ.get("GH_TOKEN")
entry = {"name": name, "args": args, "stdin": stdin,
         "stdout_pipe": stat.S_ISFIFO(os.fstat(1).st_mode),
         "gh_token": hashlib.sha256(token.encode()).hexdigest() if token else None,
         "gh_config": os.environ.get("GH_CONFIG_DIR"),
         "gh_children": [os.environ.get(k) for k in ("GH_EDITOR", "GH_BROWSER", "GH_PAGER")]}
log = os.environ["FAKE_LOG"]
with open(log, "a") as f:
    f.write(json.dumps(entry) + "\n")
if name == "gh":
    sys.exit(0)
calls = [json.loads(line) for line in open(log) if json.loads(line)["name"] != "gh"]
answers = json.load(open(os.environ["FAKE_ANSWERS"]))
answer = answers[min(len(calls), len(answers)) - 1]
time.sleep(answer.get("sleep", 0))
out = answer.get("stdout", "")
if "seal" in answer:
    out = out.replace("<sealed token>", seal(answer["seal"], answer.get("to") or json.loads(stdin)["answer_key"]))
with open(log + ".out", "a") as f:
    f.write(out)
sys.stdout.write(out)
sys.stderr.write(answer.get("stderr", ""))
sys.exit(answer["exit"])
'''


class FakeGitHub(socketserver.ThreadingTCPServer):
    daemon_threads = allow_reuse_address = True

    def __init__(self, folder):
        cert, key = folder / "cert.pem", folder / "key.pem"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-subj", "/CN=github.com", "-keyout", str(key), "-out", str(cert)],
                       check=True, capture_output=True)
        self.tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.tls.load_cert_chain(cert, key)
        self.seen = []
        super().__init__(("127.0.0.1", 0), Tunnel)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def git(self):
        return ["git", "-c", f"http.proxy=http://127.0.0.1:{self.server_address[1]}",
                "-c", "http.sslVerify=false", "ls-remote", URL]


class Tunnel(socketserver.StreamRequestHandler):
    def handle(self):
        if not self.rfile.readline().startswith(b"CONNECT github.com:443 "):
            return
        while self.rfile.readline() not in (b"\r\n", b""):
            pass
        self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        stream = self.server.tls.wrap_socket(self.request, server_side=True).makefile("rwb")
        while stream.readline():
            auth = ""
            while (line := stream.readline()) not in (b"\r\n", b""):
                key, _, value = line.decode().partition(":")
                auth = value.strip() if key.lower() == "authorization" else auth
            if auth.startswith("Basic "):
                self.server.seen.append(sha(base64.b64decode(auth[6:]).decode()))
                stream.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 0\r\n\r\n")
            else:
                stream.write(b'HTTP/1.1 401 Unauthorized\r\nWWW-Authenticate: Basic realm="x"\r\n'
                             b"Content-Length: 0\r\n\r\n")
            stream.flush()


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def answer(token=TOKEN, left=3600, repositories=(REPO,), permissions=None):
    body = {"schema": "openwiz.token-service.v1", "kind": "answer", "sealed_token": "<sealed token>",
            "expires_at": int(time.time()) + left, "repositories": list(repositories),
            "permissions": permissions or WRITE}
    return {"exit": 0, "stdout": json.dumps(body) + "\n", "seal": token}


def refusal(code):
    body = {"schema": "openwiz.token-service.v1", "kind": "refusal", "refusal": code,
            "message": PIN["refusals"][code]["message"]}
    return {"exit": PIN["refusals"][code]["exit"], "stdout": json.dumps(body) + "\n"}


def standard_environ(values, watched):
    read = []

    def decode_value(raw):
        if raw == watched:
            read.append(True)
        return raw.decode()

    data = {key.encode(): value.encode() for key, value in values.items()}
    return os._Environ(data, str.encode, bytes.decode, str.encode, decode_value), read


def load_helper():
    spec = importlib.util.spec_from_file_location("agent_token", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTRACT, SCHEMA = SERVICE_TESTS.CONTRACT, SERVICE_TESTS.SCHEMA


class Helper(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="agent-token-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.root / "fake.py").write_text(FAKE)
        for name in ("room-cli", "python3", "gh"):
            shim = self.bin / name
            shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{self.root}/fake.py" {name} "$@"\n')
            shim.chmod(0o755)
        self.log = self.root / "calls.log"
        self.private = self.root / "private"
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
                    "FAKE_LOG": str(self.log), "FAKE_ANSWERS": str(self.root / "answers.json"),
                    "OPENWIZ_AGENT_TOKEN_DIR": str(self.private),
                    "OPENWIZ_TOKEN_SERVICE": SERVICE, "OPENWIZ_TOKEN_SERVICE_ROUTE": "pairing",
                    "OPENWIZ_TOKEN_SERVICE_READBACK": "passed"}
        self.revoke_api = FakeAPI()
        self.addCleanup(self.revoke_api.server_close)
        self.addCleanup(self.revoke_api.shutdown)
        self.env["OPENWIZ_GITHUB_API_BASE"] = self.revoke_api.base()

    def answers(self, *items):
        (self.root / "answers.json").write_text(json.dumps(list(items)))

    def helper(self, *args, stdin="", **env):
        full = dict(self.env)
        full.update(env)
        for key in [k for k, v in full.items() if v is None]:
            del full[key]
        return subprocess.run([sys.executable, "-I", str(HELPER), *args], input=stdin,
                              capture_output=True, text=True, env=full, timeout=30)

    def start(self, *extra, **env):
        return self.helper("start", "--requester", "builder-1", "--repository", REPO, *extra, **env)

    def calls(self, name=None):
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [r for r in rows if name is None or r["name"] == name]

    def service_calls(self):
        return [c for c in self.calls() if c["name"] != "gh"]

    def one_call(self):
        calls = self.service_calls()
        self.assertEqual(len(calls), 1, "exactly one service call")
        return calls[0]

    def held(self):
        self.assertTrue(self.token_file().is_file(), "the private token file holds the token")
        return json.loads(self.token_file().read_text())

    def token_file(self):
        files = sorted(self.private.glob("token-*.json")) if self.private.is_dir() else []
        self.assertLessEqual(len(files), 1, "one request, one cache file")
        return files[0] if files else self.private / "token-none.json"

    def assert_never_exposed(self, *results, tokens=(TOKEN, TOKEN2)):
        for result in results:
            for token in tokens:
                self.assertNotIn(token, result.stdout + result.stderr)
        for call in self.calls():
            for token in tokens:
                self.assertNotIn(token, " ".join(call["args"]) + call["stdin"])
        for path in self.root.rglob("*"):
            private = path.parent == self.private and path.name.startswith(("token-", "kept-"))
            if path.is_file() and not private and path.name != "answers.json":
                for token in tokens:
                    self.assertNotIn(token.encode(), path.read_bytes(), path)

    def github(self):
        server = FakeGitHub(self.root)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def assert_fallback(self, result, reason):
        self.assertEqual(result.stderr, NOTE.replace("<reason>", reason) + "\n")
        self.assertFalse(self.token_file().exists())
        self.assertEqual(list(self.private.glob("run-*")) if self.private.is_dir() else [], [])


class Refresh(unittest.TestCase):
    def test_the_contract_refresh_boundary(self):
        helper = load_helper()
        for case in json.loads((FIXTURES / "refresh.json").read_text())["cases"]:
            with self.subTest(case["name"]):
                self.assertEqual(helper.needs_refresh(case["now"], case["expires_at"]), case["refresh"])


class MintedToken(Helper):
    def test_gh_and_git_use_the_minted_token(self):
        self.answers(answer())
        started = self.start()
        self.assertEqual((started.returncode, started.stdout, started.stderr), (0, "", ""))
        self.assertEqual(self.held()["token"], TOKEN)
        self.assertEqual(self.token_file().stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.private.stat().st_mode & 0o777, 0o700)
        ran = self.helper("run", *REQ, "--", "gh", "issue", "view", "1")
        self.assertEqual((ran.returncode, ran.stderr), (0, ""))
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN))
        (self.home / ".gitconfig").write_text("[credential]\n\thelper = store\n")
        github = self.github()
        git = self.helper("run", *REQ, "--", *github.git())
        self.assertEqual(git.returncode, 0, git.stderr)
        self.assertEqual(set(github.seen), {sha(f"x-access-token:{TOKEN}")})
        self.assertFalse((self.home / ".git-credentials").exists())
        self.assertEqual(len(self.service_calls()), 1, "a fresh token is reused, not minted again")
        self.assertEqual(list(self.private.glob("run-*")), [], "each run removes its snapshot")
        self.assertEqual(list(self.private.glob("exec-*")), [], "and its git exec folder")
        self.assert_never_exposed(started, ran, git)

    def test_the_request_names_repositories_and_permissions_only(self):
        self.answers(answer(permissions=READ))
        self.start("--read")
        request = json.loads(self.one_call()["stdin"])
        key = request.pop("answer_key", "")
        self.assertEqual(CONTRACT.errors(key, SCHEMA["$defs"]["answer_key"], SCHEMA), [])
        self.assertEqual(request, {"schema": "openwiz.token-service.v1", "kind": "request",
                                   "requester": "builder-1", "repositories": [REPO], "permissions": READ})

    def test_refreshes_with_five_minutes_left_before_the_next_use(self):
        self.answers(answer(), answer(token=TOKEN2))
        self.start()
        held = self.held()
        held["expires_at"] = int(time.time()) + 200
        self.token_file().write_text(json.dumps(held))
        ran = self.helper("run", *REQ, "--", "gh", "pr", "list")
        self.assertEqual((ran.returncode, ran.stderr), (0, ""))
        self.assertEqual(len(self.service_calls()), 2)
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN2))
        self.assert_never_exposed(ran)

    def test_token_crosses_the_pairing_only_as_piped_stdout_of_one_call(self):
        self.answers(answer())
        started = self.start()
        call = self.one_call()
        self.assertEqual([call["name"], *call["args"]], PIN["reach"]["routes"]["pairing"][:4]
                         + [f"python3 -I '{SERVICE}' mint"])
        self.assertTrue(call["stdout_pipe"], "the answer is read from a pipe, never a terminal")
        self.assertIsNone(call["gh_token"], "the pairing call's environment holds no token")
        self.assert_never_exposed(started)
        for readback in (None, "", "inconclusive", "failed", "Passed"):
            with self.subTest(readback=readback):
                self.log.unlink(missing_ok=True)
                off = self.start(OPENWIZ_TOKEN_SERVICE_READBACK=readback)
                self.assertEqual(self.calls(), [], "no pairing call while the read-back has not passed")
                self.assert_fallback(off, "pairing-off")

    def test_a_local_thread_runs_the_service_itself(self):
        self.answers(answer())
        self.start(OPENWIZ_TOKEN_SERVICE_ROUTE="local", OPENWIZ_TOKEN_SERVICE_READBACK=None)
        call = self.one_call()
        self.assertEqual([call["name"], *call["args"]], ["python3", "-I", SERVICE, "mint"])
        self.assertTrue(call["stdout_pipe"])

    def test_a_private_place_inside_a_git_tree_is_refused(self):
        self.answers(answer())
        tree = self.root / "work"
        (tree / ".git").mkdir(parents=True)
        refused = self.start(OPENWIZ_AGENT_TOKEN_DIR=str(tree / "private"))
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(self.calls(), [])
        self.assertFalse((tree / "private" / "token.json").exists())
        self.private.mkdir(mode=0o755)
        self.private.chmod(0o755)
        loose = self.start()
        self.assertEqual((loose.returncode, self.calls()), (2, []), "a directory others can read is refused")


AUDIT = r"""
import json, os, runpy, stat, subprocess, sys
root, sys.argv = sys.argv[1], sys.argv[2:]
started, pipes, outside, leaks, lines, busy = [], [], [], [], [], []
real = subprocess.run


def run(args, **kwargs):
    done = real(args, **kwargs)
    if "genpkey" in args:
        lines.extend(line.decode() for line in done.stdout.splitlines() if b"-----" not in line)
    return done


def hook(event, args):
    if busy:
        return
    busy.append(True)
    if event == "subprocess.Popen":
        started.append(json.dumps([args[1], dict(os.environ) if args[3] is None else args[3]]))
        pipes.extend(stat.S_ISFIFO(os.stat(a).st_mode) for a in args[1] if str(a).startswith("/dev/fd/"))
    if event == "open" and isinstance(args[2], int) and args[2] & 3 and str(args[0]).startswith("/"):
        outside.extend([] if str(args[0]).startswith((root, "/dev/null")) else [str(args[0])])
    if event in ("subprocess.Popen", "os.remove", "os.rename"):
        for folder, _, names in os.walk(root):
            for name in names:
                with open(os.path.join(folder, name), errors="replace") as file:
                    text = file.read()
                leaks.extend(name for line in lines if line in text)
    busy.pop()


subprocess.run = run
sys.addaudithook(hook)
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
except SystemExit as done:
    code = done.code
started.append(json.dumps(dict(os.environ)))
leaks += ["argv or environment" for line in lines for text in started if line in text or "PRIVATE KEY" in text]
keys = [text for text in started if "genpkey" in text]
print(json.dumps([code, len(lines) > 30, len(keys), pipes, outside, leaks]))
"""


class Sealed(Helper):
    def service(self):
        fixture = SERVICE_TESTS.ServiceFixture()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        github = SERVICE_TESTS.fake_github(fixture.pem, [REPO])
        url, _calls, fake = github.__enter__()
        self.addCleanup(github.__exit__, None, None, None)
        fake["expires_at"] = int(time.time()) + 3600
        wrapped = self.root / "wrapped.py"
        wrapped.write_text(f"import runpy, sys\nsys.argv = {[str(SERVICE_TESTS.SERVICE), 'mint', '--state-dir', str(fixture.state), '--api-base', url]!r}\n"
                           "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        (self.bin / "python3").unlink()
        self.pairing = self.root / "pairing.log"
        (self.root / "pair.py").write_text(
            "import subprocess, sys\nrequest = sys.stdin.buffer.read()\n"
            "assert sys.argv[1:4] == ['mac', 'run', '--stdin'] and len(sys.argv) == 5\n"
            "done = subprocess.run(['sh', '-c', sys.argv[4]], input=request, capture_output=True)\n"
            f"open({str(self.pairing)!r}, 'ab').write(request + done.stdout + done.stderr)\n"
            "sys.stdout.buffer.write(done.stdout)\nsys.exit(done.returncode)\n")
        (self.bin / "room-cli").write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{self.root}/pair.py" "$@"\n')
        self.env["OPENWIZ_TOKEN_SERVICE"] = str(wrapped)
        return fixture, fake

    def test_the_opened_token_is_githubs_on_both_routes_and_only_there(self):
        # comment-ok: catches: a service and helper that seal and open differently, and a plaintext token in
        # an output, a kept pairing record or the mint log.
        fixture, fake = self.service()
        for route in ("local", "pairing"):
            for token in (TOKEN, "ghs-" + "a1_.b-" * 86):
                with self.subTest(route=route, length=len(token)):
                    shutil.rmtree(self.private, True)
                    fake["token"] = token
                    done = self.start(OPENWIZ_TOKEN_SERVICE_ROUTE=route)
                    self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
                    self.assertEqual(self.held()["token"], token)
                    self.assert_never_exposed(done, tokens=(token,))
                    fixture.assert_nothing_exposed(token, done.stdout)
        record = [json.loads(line) for line in self.pairing.read_text().splitlines()]
        self.assertEqual([row["kind"] for row in record], ["request", "answer"] * 2)
        self.assertNotIn("token", record[1])
        self.assertEqual(len({row["answer_key"] for row in record[::2]}), 2, "each request has its own key")

    def test_the_private_key_is_only_ever_in_memory_and_a_pipe(self):
        # comment-ok: catches: a one-time private key on a command line, in an environment or in any file, even briefly.
        self.answers(answer(token="synthetic-" + "x1" * 255))
        done = subprocess.run([sys.executable, "-I", "-c", AUDIT, str(self.root), str(HELPER), "start", *REQ],
                              capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.stderr, "")
        self.assertEqual(json.loads(done.stdout), [0, True, 1, [True, True], [], []])

    def test_a_helper_that_cannot_make_its_key_asks_nothing(self):
        # comment-ok: catches: a request sent with no key, or a traceback in place of the one fallback note.
        helper = load_helper()
        helper.OPENSSL = str(self.root / "absent")
        wanted = {"requester": "builder-1", "repositories": [REPO], "permissions": WRITE}
        argv = [str(self.bin / "room-cli"), "mac"]
        self.assertEqual(helper.mint(argv, wanted, self.env), ("unreachable", None, None))
        self.assertEqual(self.calls(), [])


class Fallback(Helper):
    def test_unreachable_service_falls_back_with_one_note(self):
        self.answers({"exit": 1, "stdout": "", "stderr": "synthetic: owner's machine unavailable"})
        started = self.start()
        self.assertEqual(started.returncode, 0)
        self.assert_fallback(started, "unreachable")
        ran = self.helper("run", *REQ, "--", "gh", "issue", "view", "1", GH_TOKEN="synthetic-owner-login")
        self.assertEqual(ran.returncode, 0)
        self.assert_fallback(ran, "unreachable")
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha("synthetic-owner-login"))
        self.assertNotIn("synthetic: owner", started.stderr, "service text never reaches the agent's stderr")

    def test_a_failed_refresh_leaves_no_service_credential(self):
        self.answers(answer(), {"exit": 1, "stdout": ""})
        self.start()
        held = self.held()
        held["expires_at"] = int(time.time()) + 100
        self.token_file().write_text(json.dumps(held))
        outer = str(self.private / ("run-" + "0" * 32 + ".json"))
        ran = self.helper("run", *REQ, "--", "gh", "pr", "list", GH_TOKEN=TOKEN,
                          OPENWIZ_AGENT_TOKEN_RUN=outer)
        self.assert_fallback(ran, "unreachable")
        self.assertIsNone(self.calls("gh")[-1]["gh_token"], "the held App token is not handed on")
        self.assertIsNone(self.service_calls()[-1]["gh_token"], "nor passed to the service call")
        git = self.helper("run", *REQ, "--", "git", "credential", "fill",
                          stdin="protocol=https\nhost=github.com\n\n")
        self.assertNotIn(TOKEN, git.stdout)

    def test_each_fixture_fallback_reason(self):
        cases = {
            "not-installed": refusal("not-installed"),
            "unavailable": refusal("unavailable"),
            "permission": refusal("permission"),
            "bad-answer": {"exit": 0, "stdout": "garbled"},
        }
        wider = answer(repositories=(REPO, "synthetic-owner/other"))
        short = answer(left=200)
        long = answer(left=4000)
        twice = {"exit": 0, "stdout": answer()["stdout"].replace('"kind"', '"sealed_token": "x", "kind"')}
        plain = {"exit": 0, "stdout": answer()["stdout"].replace("sealed_token", "token").replace("<sealed token>", TOKEN)}
        beside = dict(answer(), stdout=answer()["stdout"].replace('"kind"', '"token": "x", "kind"'))
        other_key = dict(answer(), to=SERVICE_TESTS.ASKER.key)
        unsealed = [dict(answer(), stdout=answer()["stdout"].replace("<sealed token>", value))
                    for value in (TOKEN, "", "A" * 512, "A" * 511 + "!", "<sealed token>" * 9, "<sealed token>" * 2)]
        listed = dict(answer(), stdout=answer()["stdout"].replace('"<sealed token>"', '["<sealed token>"]'))
        bad_exit = dict(refusal("permission"), exit=0)
        injected = answer(token="synthetic\nusername=x")
        failed_answer = dict(answer(), exit=5)
        for reason, item in [*cases.items(), ("bad-answer", wider), ("bad-answer", short),
                             ("bad-answer", long), ("bad-answer", twice), ("bad-answer", bad_exit),
                             ("bad-answer", injected), ("bad-answer", failed_answer), ("bad-answer", plain),
                             ("bad-answer", beside), ("bad-answer", other_key), ("bad-answer", answer(token="a" * 318 * 9)), ("bad-answer", listed),
                             *[("bad-answer", item) for item in unsealed]]:
            with self.subTest(reason=reason, item=item["stdout"][:60]):
                self.log.unlink(missing_ok=True)
                self.answers(item)
                result = self.start()
                self.assertEqual(result.returncode, 0)
                self.assert_fallback(result, reason)
                if item in (plain, unsealed[0]):
                    self.assertIn(TOKEN, Path(f"{self.log}.out").read_text())
                    Path(f"{self.log}.out").unlink()
                self.assert_never_exposed(result)
        reasons = {c["reason"] for c in json.loads((FIXTURES / "fallback.json").read_text())["cases"]
                   if "reason" in c}
        self.assertLessEqual(reasons, set(PIN["fallback"]["reasons"]))

    def test_a_path_that_cannot_be_quoted_is_never_run(self):
        for path in ("/synthetic/it's.py", "/synthetic/a\nb.py", "relative/token-service.py"):
            with self.subTest(path=path):
                result = self.start(OPENWIZ_TOKEN_SERVICE=path)
                self.assertEqual(self.calls(), [])
                self.assert_fallback(result, "unreachable")

    def test_a_service_that_does_not_answer_in_time(self):
        helper = load_helper()
        self.answers({"exit": 0, "stdout": "", "sleep": 5})
        helper.TIMEOUT_S = 1
        started = time.monotonic()
        reason = helper.ask([str(self.bin / "room-cli"), "x"], b"{}", self.env)[0]
        self.assertEqual(reason, "unreachable")
        self.assertLess(time.monotonic() - started, 4)

    def test_no_service_configured_is_exactly_as_today(self):
        result = self.start(OPENWIZ_TOKEN_SERVICE=None)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))
        ran = self.helper("run", *REQ, "--", "gh", "api", "user", OPENWIZ_TOKEN_SERVICE=None,
                          GH_TOKEN="synthetic-owner-login")
        self.assertEqual((ran.returncode, ran.stderr), (0, ""))
        self.assertEqual(self.service_calls(), [])
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha("synthetic-owner-login"))
        self.assertFalse(self.private.exists())


class Review(Helper):
    REQ = REQ

    def shell(self, script, *extra, **env):
        env = dict({"PY": sys.executable, "H": str(HELPER)}, **env)
        return self.helper("run", *self.REQ, "--", "sh", "-c", script, *extra, **env)

    def test_r1_credential_answers_only_inside_git_exchange(self):
        self.answers(answer())
        self.start()
        direct = self.helper("credential", "get", stdin="protocol=https\nhost=github.com\n\n")
        self.assertEqual((direct.stdout, direct.stderr), ("", ""))
        by_hand = self.shell('printf "protocol=https\\nhost=github.com\\n\\n" | '
                             '"$PY" -I "$H" credential --snapshot "$OPENWIZ_AGENT_TOKEN_RUN" get | cat')
        self.assertNotIn(TOKEN, by_hand.stdout + by_hand.stderr)

    def test_r2_a_symlinked_ancestor_into_a_git_tree_is_refused(self):
        self.answers(answer())
        tree = self.root / "work"
        (tree / ".git").mkdir(parents=True)
        (tree / "sub").mkdir()
        (self.root / "link").symlink_to(tree / "sub")
        refused = self.start(OPENWIZ_AGENT_TOKEN_DIR=str(self.root / "link" / "private"))
        self.assertEqual((refused.returncode, self.calls()), (2, []))
        self.assertFalse((tree / "sub" / "private").exists())

    def test_r1_a_git_credential_command_never_prints_the_token(self):
        self.answers(answer())
        self.start()
        fill = self.helper("run", *self.REQ, "--", "git", "credential", "fill",
                           stdin="protocol=https\nhost=github.com\n\n")
        piped = self.shell('printf "protocol=https\nhost=github.com\n\n" | git credential fill | cat')
        self.assert_never_exposed(fill, piped)
        self.assertNotEqual(fill.returncode, 0)
        self.assertEqual(fill.stderr.count(WITHHELD), 1, "one note")

    def test_r2_an_ancestor_swapped_before_the_open_never_redirects_the_token(self):
        helper = load_helper()
        tree = self.root / "work"
        (tree / ".git").mkdir(parents=True)
        (tree / "private").mkdir(mode=0o700)
        safe = self.root / "safe"
        (safe / "private").mkdir(parents=True, mode=0o700)
        safe.chmod(0o700)
        real_open = os.open

        def swap_then_open(path, *args, **kwargs):
            if os.path.basename(path) == "private" and not safe.is_symlink():
                safe.rename(self.root / "moved")
                safe.symlink_to(tree)
            return real_open(path, *args, **kwargs)

        with mock.patch.object(helper.os, "open", swap_then_open):
            try:
                private = helper.Private(dict(self.env, OPENWIZ_AGENT_TOKEN_DIR=str(safe / "private")), True)
                private.write("token-x.json", {"token": TOKEN})
            except helper.Refused:
                pass
        self.assertTrue(safe.is_symlink(), "the swap happened")
        self.assertEqual(list((tree / "private").iterdir()), [])

    def test_r2_an_ancestor_others_can_change_is_refused(self):
        self.answers(answer())
        shared = self.root / "shared"
        shared.mkdir()
        shared.chmod(0o777)
        refused = self.start(OPENWIZ_AGENT_TOKEN_DIR=str(shared / "private"))
        self.assertEqual((refused.returncode, self.calls()), (2, []))
        self.assertFalse((shared / "private").exists())

    def test_r2_an_ancestor_its_group_can_change_is_refused(self):
        self.answers(answer())
        shared = self.root / "group"
        shared.mkdir()
        shared.chmod(0o770)
        os.chown(shared, -1, os.getgid())
        refused = self.start(OPENWIZ_AGENT_TOKEN_DIR=str(shared / "private"))
        self.assertEqual((refused.returncode, self.calls()), (2, []))
        self.assertFalse((shared / "private").exists())

    def test_r7_a_replaced_helper_list_or_header_never_authenticates_git(self):
        self.answers(answer())
        self.start()
        owner = "!f() { echo username=synthetic-owner; echo password=synthetic-owner-login; }; f"
        header = "Authorization: Basic " + base64.b64encode(b"synthetic-owner:synthetic-owner-login").decode()
        for config in (("credential.helper=", f"credential.helper={owner}"),
                       ("credential.https://github.com.helper=", f"credential.https://github.com.helper={owner}"),
                       (f"http.extraHeader={header}",)):
            with self.subTest(config=config[-1][:40]):
                github = self.github()
                options = [arg for item in config for arg in ("-c", item)]
                ran = self.helper("run", *self.REQ, "--", "git", *options, *github.git()[1:])
                self.assertEqual(github.seen, [], "git signs in as no one: not the owner, not the App")
                self.assertNotEqual(ran.returncode, 0)
                self.assertEqual(ran.stderr.count(WITHHELD), 1, "one note")

    def test_r8_git_http_tracing_never_shows_the_token(self):
        self.answers(answer())
        self.start()
        github = self.github()
        trace = self.root / "curl-trace.txt"
        ran = self.helper("run", *self.REQ, "--", *github.git(), GIT_TRACE_CURL=str(trace),
                          GIT_CURL_VERBOSE="1", GIT_TRACE_REDACT="0")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(set(github.seen), {sha(f"x-access-token:{TOKEN}")})
        encoded = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()
        self.assert_never_exposed(ran, tokens=(TOKEN, encoded))

    def test_r7_an_unguarded_git_never_signs_in_as_the_owner(self):
        self.answers(answer())
        self.start()
        owner = "!f() { echo username=synthetic-owner; echo password=synthetic-owner-login; }; f"
        replaced = ["-c", "credential.helper=", "-c", f"credential.helper={owner}"]
        real = subprocess.run(["git", "--exec-path"], capture_output=True, text=True,
                              env=self.env).stdout.strip()
        broken = self.root / "broken"
        broken.mkdir()
        (broken / "git").write_text('#!/bin/sh\n[ "$1" = --exec-path ] && exit 1\nexec /usr/bin/git "$@"\n')
        (broken / "git").chmod(0o755)
        github = self.github()
        cases = {
            "lookup fails": dict(args=["git", *replaced, *github.git()[1:]], PATH=f"{broken}:{self.env['PATH']}"),
            "--exec-path": dict(args=["git", f"--exec-path={real}", *replaced, *github.git()[1:]]),
            "GIT_EXEC_PATH": dict(args=["env", f"GIT_EXEC_PATH={real}", "git", *replaced, *github.git()[1:]]),
            "unset": dict(args=["env", "-u", "GIT_EXEC_PATH", "git", *replaced, *github.git()[1:]]),
        }
        for name, case in cases.items():
            with self.subTest(name):
                args = case.pop("args")
                ran = self.helper("run", *self.REQ, "--", *args, **case)
                self.assertEqual(github.seen, [], "git signs in as no one: not the owner, not the App")
                self.assertNotEqual(ran.returncode, 0)
                self.assertEqual(ran.stderr.count("openwiz:"), 1, "one note")
                self.assert_never_exposed(ran)

    def test_r9_git_process_tracing_never_shows_the_token(self):
        self.answers(answer())
        self.start()
        github = self.github()
        trace = self.root / "trace2.json"
        ran = self.helper("run", *self.REQ, "--", "git", "-c", "trace2.envVars=GH_TOKEN",
                          *github.git()[1:], GIT_TRACE2_EVENT=str(trace), GIT_TRACE2_ENV_VARS="GH_TOKEN")
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertTrue(trace.is_file(), "git traced")
        self.assertEqual(set(github.seen), {sha(f"x-access-token:{TOKEN}")})
        self.assert_never_exposed(ran)

    def test_r10_ssh_never_signs_git_in_as_the_owner(self):
        self.answers(answer())
        self.start()
        ssh_log = self.root / "owner-ssh.log"
        fake_ssh = self.root / "owner-ssh"
        fake_ssh.write_text(f'#!/bin/sh\necho "$@" >> "{ssh_log}"\nexit 1\n')
        fake_ssh.chmod(0o755)
        (self.home / ".gitconfig").write_text(
            f'[url "ssh://git@github.com/"]\n\tinsteadOf = https://github.com/\n'
            f'[core]\n\tsshCommand = {fake_ssh}\n')
        ext = f"ext::{fake_ssh} git@github.com %S {REPO}"
        cases = {
            "insteadOf": (["git", "ls-remote", URL], 1),
            "scp-like remote": (["git", "ls-remote", f"git@github.com:{REPO}"], 1),
            "command-line sshCommand": (["git", "-c", f"core.sshCommand={fake_ssh}", "ls-remote",
                                         f"ssh://git@github.com/{REPO}"], 1),
            "GIT_SSH_COMMAND changed": (["env", f"GIT_SSH_COMMAND={fake_ssh}", "git", "ls-remote",
                                         f"git@github.com:{REPO}"], 1),
            "ext transport": (["git", "-c", "protocol.ext.allow=always", "ls-remote", ext], 0),
            "GIT_ALLOW_PROTOCOL widened": (["env", "GIT_ALLOW_PROTOCOL=ext", "git", "-c",
                                            "protocol.ext.allow=always", "ls-remote", ext], 1),
        }
        for name, (args, notes) in cases.items():
            with self.subTest(name):
                ssh_log.unlink(missing_ok=True)
                ran = self.helper("run", *self.REQ, "--", *args)
                self.assertFalse(ssh_log.exists(), "the owner's ssh never starts")
                self.assertNotEqual(ran.returncode, 0)
                self.assertEqual(ran.stderr.count(WITHHELD), notes, ran.stderr)
                self.assert_never_exposed(ran)

    def test_r11_a_legacy_app_key_is_refused_by_name(self):
        self.answers(answer())
        sentinel = "synthetic-legacy-key-sentinel"
        started = self.start(OPENWIZ_GITHUB_APP_KEY=sentinel)
        ran = self.shell('[ -n "${OPENWIZ_GITHUB_APP_KEY+x}" ] && echo key-present', OPENWIZ_GITHUB_APP_KEY=sentinel)
        for result in (started, ran):
            self.assertEqual(result.returncode, 2)
            self.assertIn("OPENWIZ_GITHUB_APP_KEY", result.stderr)
            self.assertNotIn(sentinel, result.stdout + result.stderr)
        self.assertNotIn("key-present", ran.stdout)
        self.assertEqual(self.calls(), [], "no service call and no command")

    def test_r12_only_gh_gets_the_app_token(self):
        self.answers(answer())
        self.start()
        printed = self.helper("run", *self.REQ, "--", "env")
        self.assertEqual(printed.returncode, 0, printed.stderr)
        self.assert_never_exposed(printed)
        via_shell = self.shell("gh pr list")
        self.assertEqual(via_shell.returncode, 0, via_shell.stderr)
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN), "gh, found on PATH, gets it")
        direct = self.helper("run", *self.REQ, "--", str(self.bin / "gh"), "pr", "list")
        self.assertIsNone(self.calls("gh")[-2]["gh_config"], "the stand-in restores the owner's gh config")
        self.assertIsNone(self.calls("gh")[-1]["gh_token"], "a gh the run did not start gets nothing")
        lost = self.calls("gh")[-1]["gh_config"]
        self.assertTrue(lost.startswith(str(self.private)) and not os.path.exists(lost),
                        "nor the owner's gh login, so it fails visibly")
        self.assert_never_exposed(via_shell, direct)

    def test_r11_the_legacy_app_key_value_is_never_read(self):
        helper = load_helper()
        sentinel = "synthetic-legacy-key-sentinel"
        environment, read = standard_environ(dict(self.env, OPENWIZ_GITHUB_APP_KEY=sentinel), sentinel.encode())
        for command in (["start", *REQ], ["run", *REQ, "--", "gh", "pr", "list"]):
            with self.subTest(command[0]), mock.patch.object(helper.os, "environ", environment):
                self.assertEqual(helper.main(command), 2)
        self.assertEqual(read, [], "the legacy value is never fetched")
        self.assertEqual(self.calls(), [])

    def test_r12_gh_gets_the_token_only_for_its_allowed_commands(self):
        self.answers(answer())
        self.start()
        denied = (["auth", "token"], ["auth", "status", "--show-token"], ["config", "get", "editor"],
                  ["alias", "set", "co", "!sh -c env"], ["co"], ["extension", "exec", "synthetic"],
                  ["synthetic-extension"], [])
        for args in denied:
            with self.subTest(args):
                self.log.unlink(missing_ok=True)
                ran = self.helper("run", *self.REQ, "--", "gh", *args)
                self.assertEqual([c["gh_token"] for c in self.calls("gh")], [], "authenticated gh never starts")
                self.assertNotEqual(ran.returncode, 0)
                self.assertEqual(ran.stderr.count("openwiz: openwiz[bot] token withheld from gh"), 1)
        owner = {"GH_EDITOR": "synthetic-owner-editor", "GH_BROWSER": "synthetic-owner-browser",
                 "GH_PAGER": "synthetic-owner-pager"}
        allowed = self.helper("run", *self.REQ, "--", "gh", "pr", "view", "1", **owner)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        call = self.calls("gh")[-1]
        self.assertEqual(call["gh_token"], sha(TOKEN))
        editor, browser, pager = call["gh_children"]
        self.assertEqual(pager, "cat", "no pager child gets the token")
        for child in (editor, browser):
            self.assertTrue(child.startswith(str(self.private)), "editor and browser are the run's refusal")

    def test_r12_only_the_gh_the_run_chose_gets_the_token(self):
        self.answers(answer())
        self.start()
        rogue = self.root / "rogue"
        rogue.mkdir()
        flag = self.root / "rogue-had-token"
        (rogue / "gh").write_text(f'#!/bin/sh\n[ -n "${{GH_TOKEN-}}" ] && : > "{flag}"\nexit 0\n')
        (rogue / "gh").chmod(0o755)
        cases = {
            "another path": f'"$PY" -I "$H" gh "{rogue}/gh" "$GIT_EXEC_PATH/openwiz-gh-child" pr list',
            "another refusal": f'"$PY" -I "$H" gh "{self.bin}/gh" "{rogue}/openwiz-gh-child" pr list',
            "swapped binary": f'mv "{self.bin}/gh" "{self.bin}/gh.real" && cp "{rogue}/gh" "{self.bin}/gh" && gh pr list;'
                              f' s=$?; mv -f "{self.bin}/gh.real" "{self.bin}/gh"; exit $s',
        }
        reasons = {"another path": "not the gh this run chose", "another refusal": "not the gh this run chose",
                   "swapped binary": "the gh this run chose was changed"}
        for name, script in cases.items():
            with self.subTest(name):
                flag.unlink(missing_ok=True)
                ran = self.shell(script)
                self.assertFalse(flag.exists(), "no other executable gets the token")
                self.assertNotEqual(ran.returncode, 0)
                self.assertEqual(ran.stderr.count("openwiz:"), 1, ran.stderr)
                self.assertIn(reasons[name], ran.stderr)
                self.assert_never_exposed(ran)
        bound = self.shell("gh pr list")
        self.assertEqual((bound.returncode, self.calls("gh")[-1]["gh_token"]), (0, sha(TOKEN)))

    def test_r12_a_gh_swapped_between_its_check_and_its_exec_never_gets_the_token(self):
        helper = load_helper()
        real = self.bin / "gh"
        checked = real.read_text()
        rogue = "#!/bin/sh\n# synthetic rogue gh\nexit 0\n"
        name = "run-" + "0" * 32 + ".json"
        private = helper.Private(self.env, create=True)
        private.write(name, {"token": TOKEN, "expires_at": int(time.time()) + 3600})
        refuse = str(self.private / "exec-synthetic" / helper.GH_REFUSE)
        env = dict(self.env, **{helper.RUN_MARK: str(self.private / name)})
        load = helper.snapshot_token

        def load_then_swap(*args, **kwargs):
            held = load(*args, **kwargs)
            swapped = self.bin / "gh.swap"
            swapped.write_text(rogue)
            swapped.chmod(0o755)
            os.replace(swapped, real)
            return held

        for platform in ("linux", "darwin"):
            with self.subTest(platform):
                real.write_text(checked)
                real.chmod(0o755)
                self.bin.chmod(0o755 if platform == "linux" else 0o775)
                private.write(helper.gh_binding(name), {"gh": str(real), "refuse": refuse,
                                                        "identity": helper.gh_identity(str(real))})
                ran = []

                def exec_boundary(path, args, child):
                    target = f"/proc/self/fd/{path}" if isinstance(path, int) else path
                    ran.append((Path(target).read_text(), child.get("GH_TOKEN")))
                    raise OSError("synthetic exec boundary")

                with mock.patch.object(helper, "snapshot_token", load_then_swap), \
                        mock.patch.object(helper.sys, "platform", platform), \
                        mock.patch.object(helper.os, "execve", exec_boundary), \
                        mock.patch.object(helper.sys, "stderr") as stderr:
                    try:
                        code = helper.gh([str(real), refuse, "pr", "list"], dict(env))
                    except helper.Refused:
                        code = "exec intercepted"
                self.assertNotIn((rogue, TOKEN), ran, "a gh swapped in after the check gets the token")
                if platform == "linux":
                    self.assertEqual((code, ran), ("exec intercepted", [(checked, TOKEN)]),
                                     "the checked gh runs from the file that was checked")
                else:
                    said = "".join(call.args[0] for call in stderr.write.call_args_list)
                    self.assertEqual((code, ran), (128, []), "no exec where the checked file can't be run")
                    self.assertIn("a folder above gh is not owner-only", said)

    def test_r1_gh_checks_intermediate_symlink_targets_before_path_exec(self):
        helper = load_helper()
        name = "run-" + "0" * 32 + ".json"
        private = helper.Private(self.env, create=True)
        self.addCleanup(os.close, private.fd)
        private.write(name, {"token": TOKEN, "expires_at": int(time.time()) + 3600})
        refuse = str(self.private / "exec-synthetic" / helper.GH_REFUSE)
        env = dict(self.env, **{helper.RUN_MARK: str(self.private / name)})

        with tempfile.TemporaryDirectory(dir=Path.home().resolve()) as folder:
            root = Path(folder)
            intermediate = root / "intermediate"
            intermediate.mkdir()
            intermediate.chmod(0o775)
            target = root / "target"
            target.mkdir(mode=0o755)
            real = target / "gh"
            real.write_text("#!/bin/sh\nexit 0\n")
            real.chmod(0o755)
            (intermediate / "next").symlink_to("../target", target_is_directory=True)
            (root / "entry").symlink_to(intermediate / "next", target_is_directory=True)
            chosen = str(root / "entry" / "gh")
            private.write(helper.gh_binding(name), {"gh": chosen, "refuse": refuse,
                                                    "identity": helper.gh_identity(str(real))})
            args = [chosen, refuse, "pr", "list"]
            with mock.patch.object(helper.sys, "platform", "darwin"), \
                    mock.patch.object(helper.os, "execve") as run, \
                    mock.patch.object(helper.sys, "stderr") as stderr:
                code = helper.gh(args, dict(env))
                self.assertEqual((code, run.call_count), (128, 0), "unsafe intermediate directory must block exec")
                self.assertIn("a folder above gh is not owner-only", stderr.write.call_args.args[0])

                intermediate.chmod(0o755)
                helper.gh(args, dict(env))
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0], str(real))
                self.assertEqual(run.call_args.args[2]["GH_TOKEN"], TOKEN)

    def test_r13_a_reply_that_crosses_the_refresh_boundary_in_flight_is_refused(self):
        self.answers(dict(answer(left=302), sleep=3))
        started = self.start()
        self.assert_fallback(started, "bad-answer")

    def test_r7_a_later_owner_helper_never_authenticates_git(self):
        self.answers(answer())
        self.start()
        github = self.github()
        owner = "!f() { echo username=synthetic-owner; echo password=synthetic-owner-login; }; f"
        ran = self.helper("run", *self.REQ, "--", "git", "-c", f"credential.helper={owner}", *github.git()[1:])
        self.assertEqual(github.seen, [], "git signs in as no one: not the owner, not the App")
        self.assertNotEqual(ran.returncode, 0)
        self.assertEqual(ran.stderr.count(WITHHELD), 1, "one note")
        self.assert_never_exposed(ran)

    def test_r3_two_agents_on_one_account_keep_their_own_scopes(self):
        self.answers(answer(), answer(token=TOKEN2, permissions=READ))
        self.start()
        self.helper("start", "--requester", "reviewer-2", "--repository", REPO, "--read")
        first = self.helper("run", *self.REQ, "--", "gh", "pr", "list")
        second = self.helper("run", "--requester", "reviewer-2", "--repository", REPO, "--read",
                             "--", "gh", "pr", "view", "1")
        self.assertEqual([c["gh_token"] for c in self.calls("gh")], [sha(TOKEN), sha(TOKEN2)])
        self.assertEqual(len(self.service_calls()), 2)
        self.assert_never_exposed(first, second)

    def test_r4_a_command_scope_helper_never_gets_the_token(self):
        self.answers(answer())
        self.start()
        fill = self.helper("run", *self.REQ, "--", "git", "-c", "credential.helper=store",
                           "credential", "fill", stdin="protocol=https\nhost=github.com\n\n")
        self.helper("run", *self.REQ, "--", "git", "-c", "credential.helper=store",
                    "credential", "approve", stdin=fill.stdout + "\n")
        self.assertNotIn(TOKEN, fill.stdout)
        self.assertFalse((self.home / ".git-credentials").exists())

    def test_r6_a_failed_start_inside_a_run_hands_no_app_token_on(self):
        self.answers(answer())
        req = " ".join(self.REQ)
        ran = self.shell(f'OPENWIZ_TOKEN_SERVICE_READBACK=failed "$PY" -I "$H" start {req}; '
                         f'OPENWIZ_TOKEN_SERVICE_READBACK=failed "$PY" -I "$H" run {req} -- gh pr list')
        self.assertEqual([c["gh_token"] for c in self.calls("gh")], [None])
        self.assertEqual(ran.stderr, (NOTE.replace("<reason>", "pairing-off") + "\n") * 2)




NOT_REVOKED = "openwiz: openwiz[bot] token not revoked ({}); the token is kept for a later revoke\n"
NO_TOKEN = "openwiz: openwiz[bot] token not revoked (no token found)\n"


class FakeAPI(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, status=204, location=None):
        self.status, self.location, self.watch, self.seen, self.during = status, location, None, [], None
        super().__init__(("127.0.0.1", 0), FakeAPIHandler)
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def base(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class FakeAPIHandler(http.server.BaseHTTPRequestHandler):
    def answer(self):
        auth = self.headers.get("Authorization") or ""
        watch = self.server.watch
        folder = watch if watch and watch.is_dir() else watch and watch.parent
        held = folder and any(auth[7:].encode() in p.read_bytes() for p in folder.glob("*")
                              if p.is_file() and os.access(p, os.R_OK))
        self.server.seen.append({"method": self.command, "path": self.path,
                                 "auth": sha(auth) if auth else None, "held": bool(held)})
        if self.server.during:
            self.server.during()
        self.send_response(self.server.status)
        if self.server.location:
            self.send_header("Location", self.server.location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_DELETE = do_CONNECT = answer

    def log_message(self, *args):
        pass


class Revoke(Helper):
    def api(self, **kwargs):
        server = FakeAPI(**kwargs)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def minted(self):
        self.answers(answer())
        self.assertEqual(self.start().returncode, 0)
        return self.token_file()

    def revoke(self, api, **env):
        return self.helper("revoke", *REQ, OPENWIZ_GITHUB_API_BASE=api.base(), **env)

    def assert_revoked_once(self, api, token=TOKEN):
        self.assertEqual(api.seen, [{"method": "DELETE", "path": "/installation/token",
                                     "auth": sha(f"Bearer {token}"), "held": True}])

    def test_revoke_makes_its_own_https_call_when_gh_is_refused_or_absent(self):
        # comment-ok: catches: a revoke routed through gh, its guard or a shim, which fails open when gh
        # refuses (GA5's crossing) or is not installed.
        refusing = self.root / "refusing"
        refusing.mkdir()
        (refusing / "gh").write_text("#!/bin/sh\necho synthetic-gh-refused >&2\nexit 1\n")
        (refusing / "gh").chmod(0o755)
        no_gh = self.root / "no-gh"
        no_gh.mkdir()
        for name, path in (("gh refused", f"{refusing}:{self.bin}:/usr/bin:/bin"),
                           ("gh absent", f"{no_gh}:/usr/bin:/bin")):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                self.log.unlink(missing_ok=True)
                held = self.minted()
                api = self.api()
                api.watch = held
                done = self.revoke(api, PATH=path)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
                self.assert_revoked_once(api)
                self.assertEqual(self.calls("gh"), [], "revoke never runs gh")
                self.assertFalse(held.exists(), "a revoked token is removed")
                self.assert_never_exposed(done)

    def test_revoke_inside_a_run_whose_folder_is_partly_gone_or_unreadable(self):
        # comment-ok: catches: a revoke that needs the cache file, the exec folder or a folder listing,
        # so it fails once the run's folder is partly deleted or its cache file is unreadable.
        breaks = {"cache file gone": 'rm -f "$CACHE"',
                  "cache file unreadable": 'chmod 000 "$CACHE"',
                  "cache file not JSON": 'printf "{" > "$CACHE"',
                  "exec folder and gh binding gone": 'rm -rf "$PRIV"/exec-* "$PRIV"/gh-*'}
        for name, damage in breaks.items():
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                held = self.minted()
                api = self.api()
                api.watch = self.private
                script = f'{damage}; exec "$PY" -I "$H" revoke {" ".join(REQ)}'
                done = self.helper("run", *REQ, "--", "/bin/sh", "-c", script,
                                   OPENWIZ_GITHUB_API_BASE=api.base(), CACHE=str(held),
                                   PRIV=str(self.private), PY=sys.executable, H=str(HELPER))
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""), name)
                self.assert_revoked_once(api)
                self.assertEqual(list(self.private.glob("run-*")) if self.private.exists() else [], [])
                self.assert_never_exposed(done)

    def test_revoke_finds_the_token_in_a_moved_folder(self):
        # comment-ok: catches: a revoke that trusts the path this run recorded, so it finds nothing
        # after the folder was moved and the token stays live.
        self.minted()
        moved = self.root / "moved"
        self.private.rename(moved)
        api = self.api()
        api.watch = moved
        stale = str(self.private / ("run-" + "0" * 32 + ".json"))
        done = self.revoke(api, OPENWIZ_AGENT_TOKEN_DIR=str(moved), OPENWIZ_AGENT_TOKEN_RUN=stale)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
        self.assert_revoked_once(api)
        self.assertEqual(list(moved.iterdir()), [], "no token is left, and the folder stays for later mints")
        self.assert_never_exposed(done)

    def test_removing_the_token_folder_revokes_first(self):
        # comment-ok: catches: removing a token file or folder before GitHub confirmed the revoke,
        # which leaves a live token nobody holds.
        held = self.minted()
        other = self.private / "token-other.json"
        other.write_text(json.dumps({"token": TOKEN2, "expires_at": int(time.time()) + 3600}))
        other.chmod(0o600)
        api = self.api()
        api.watch = held
        done = self.revoke(api)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assert_revoked_once(api)
        self.assertFalse(held.exists())
        self.assertEqual(json.loads(other.read_text())["token"], TOKEN2,
                         "another request's token is never removed or revoked")
        self.assertTrue(self.private.is_dir(), "a folder still holding a token stays")
        other.unlink()
        api.seen.clear()
        again = self.revoke(api)
        self.assertEqual((again.returncode, again.stderr), (1, NO_TOKEN))
        self.assertEqual(api.seen, [])

    def test_a_failed_revoke_keeps_the_token_and_says_so_in_one_line(self):
        # comment-ok: catches: a revoke that deletes the only copy of a live token when GitHub refuses,
        # redirects or cannot be reached, or that reports success, several lines or the token.
        cases = {"refused 401": ({"status": 401}, "GitHub refused"),
                 "refused 404": ({"status": 404}, "GitHub refused"),
                 "server error": ({"status": 500}, "GitHub refused"),
                 "not a 204": ({"status": 200}, "GitHub refused"),
                 "redirect": ({"status": 307}, "GitHub refused")}
        elsewhere = self.api()
        for name, (kwargs, reason) in cases.items():
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                held = self.minted()
                before = held.read_bytes()
                if kwargs["status"] == 307:
                    kwargs["location"] = elsewhere.base() + "/installation/token"
                api = self.api(**kwargs)
                api.watch = held
                done = self.revoke(api)
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (1, "", NOT_REVOKED.format(reason)))
                self.assert_revoked_once(api)
                kept = [path.read_bytes() for path in self.private.glob("kept-*")]
                self.assertEqual(kept, [before], "the only copy of a live token is kept, never deleted")
                self.assertEqual(elsewhere.seen, [], "a redirect is never followed")
                self.assert_never_exposed(done)
        with self.subTest("unreachable"):
            api = self.api()
            base = api.base()
            api.shutdown()
            api.server_close()
            done = self.helper("revoke", *REQ, OPENWIZ_GITHUB_API_BASE=base)
            self.assertEqual((done.returncode, done.stdout, done.stderr),
                             (1, "", NOT_REVOKED.format("GitHub unreachable")))
            self.assertEqual([path.read_bytes() for path in self.private.glob("kept-*")], [before])
            self.assert_never_exposed(done)

    def test_no_token_found_gives_one_fixed_line_and_calls_nobody(self):
        # comment-ok: catches: a revoke that exits zero, prints more than one line, or calls GitHub
        # when it holds no current token.
        api = self.api()
        expired = {"token": TOKEN, "expires_at": int(time.time()) - 10}
        setups = {"no folder": lambda: None,
                  "empty folder": lambda: self.private.mkdir(mode=0o700),
                  "expired token": lambda: (self.minted().write_text(json.dumps(expired))),
                  "not a token": lambda: (self.minted().write_text(json.dumps({"token": "a b"})))}
        for name, setup in setups.items():
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                setup()
                done = self.revoke(api)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (1, "", NO_TOKEN))
                self.assertEqual(api.seen, [])
                self.assert_never_exposed(done)

    def test_revoke_names_the_failed_private_folder_check(self):
        held = self.minted()
        before = sha(held.read_text())
        self.private.chmod(0o755)
        link = self.root / "linked"
        link.symlink_to(self.private)
        unsafe_parent = self.root / "shared"
        unsafe_parent.mkdir()
        (unsafe_parent / "private").mkdir(mode=0o700)
        unsafe_parent.chmod(0o777)
        worktree = self.root / "worktree"
        (worktree / ".git").mkdir(parents=True)
        (worktree / "private").mkdir(mode=0o700)
        cases = (
            (self.private, "the private token directory must be a 0700 directory you own"),
            (link, "the private token directory must be a real directory, through no symlink"),
            (unsafe_parent / "private",
             "the private token directory must sit in folders only you or root can change"),
            (worktree / "private", "the private token directory must be outside every Git working tree"),
            (Path("relative-private"), "the private token directory must be an absolute path"),
        )
        api = self.api()
        for folder, guidance in cases:
            with self.subTest(guidance=guidance):
                done = self.revoke(api, OPENWIZ_AGENT_TOKEN_DIR=str(folder))
                self.assert_never_exposed(done)
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (1, "", f"openwiz: openwiz[bot] token not revoked ({guidance})\n"),
                                 "catches: revoke calls an unsafe token folder empty")
                self.assertEqual(api.seen, [])
                self.assertEqual(list(self.private.iterdir()), [held])
                self.assertEqual(sha(held.read_text()), before)

    def test_revoke_https_goes_only_to_the_configured_api_base(self):
        # comment-ok: catches: a revoke that follows a proxy setting or an arbitrary base, sending the
        # token to a host other than GitHub's API.
        held = self.minted()
        before = held.read_bytes()
        proxy = self.api()
        for base in ("https://api.github.com.example", "http://api.github.com",
                     "http://127.0.0.2:8080", "http://localhost:8080", "http://127.0.0.1:8080/x",
                     "http://user@127.0.0.1:8080", "https://api.github.com/", ""):
            with self.subTest(base=base):
                done = self.helper("revoke", *REQ, OPENWIZ_GITHUB_API_BASE=base)
                self.assertEqual((done.returncode, done.stdout, done.stderr),
                                 (1, "", NOT_REVOKED.format("not the GitHub API")))
                self.assertEqual(held.read_bytes(), before)
        api = self.api()
        api.watch = held
        done = self.revoke(api, HTTP_PROXY=proxy.base(), http_proxy=proxy.base(),
                           HTTPS_PROXY=proxy.base(), https_proxy=proxy.base(), ALL_PROXY=proxy.base())
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(proxy.seen, [], "no proxy sees the request")
        self.assert_revoked_once(api)
        self.assert_never_exposed(done)



class FallbackRevoke(Helper):
    api, minted, revoke, assert_revoked_once = (
        Revoke.api, Revoke.minted, Revoke.revoke, Revoke.assert_revoked_once)

    def expiring(self, left=100):
        held_file = self.minted()
        held = json.loads(held_file.read_text())
        held["expires_at"] = int(time.time()) + left
        held_file.write_text(json.dumps(held))
        return held_file

    def run_gh(self, **env):
        return self.helper("run", *REQ, "--", "gh", "pr", "list", **env)

    def test_a_fallback_revokes_a_live_token_before_deleting_it(self):
        # comment-ok: catches: a fallback that deletes the only copy of a still-live token without
        # revoking it, leaving a token nobody holds until it expires.
        for name, reason, act in (
                ("a failed refresh", "unreachable", lambda api: self.run_gh(
                    OPENWIZ_GITHUB_API_BASE=api.base())),
                ("the pairing turned off", "pairing-off", lambda api: self.start(
                    OPENWIZ_GITHUB_API_BASE=api.base(), OPENWIZ_TOKEN_SERVICE_READBACK="failed"))):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                self.log.unlink(missing_ok=True)
                held = self.expiring()
                self.answers(answer(), {"exit": 1, "stdout": ""})
                api = self.api()
                api.watch = held
                done = act(api)
                self.assert_fallback(done, reason)
                self.assert_revoked_once(api)
                self.assertEqual([c["gh_token"] for c in self.calls("gh")], [None] * len(self.calls("gh")))
                self.assert_never_exposed(done)
        with self.subTest("an expired token needs no revoke"):
            shutil.rmtree(self.private, True)
            self.expiring(left=-10)
            self.answers(answer(), {"exit": 1, "stdout": ""})
            api = self.api()
            done = self.run_gh(OPENWIZ_GITHUB_API_BASE=api.base())
            self.assert_fallback(done, "unreachable")
            self.assertEqual(api.seen, [], "a dead token is deleted without a call")

    def test_a_fallback_whose_revoke_fails_keeps_the_token_file(self):
        # comment-ok: catches: a fallback that deletes a live token whose revoke failed, or that writes
        # more than the one fallback note.
        closed = FakeAPI()
        closed_base = closed.base()
        closed.shutdown()
        closed.server_close()
        for name, base in (("GitHub refuses", None), ("GitHub unreachable", closed_base),
                           ("not the GitHub API", "http://example.invalid")):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                self.log.unlink(missing_ok=True)
                held = self.expiring()
                self.answers(answer(), {"exit": 1, "stdout": ""})
                before = json.loads(held.read_text())
                refusing = self.api(status=401)
                refusing.watch = held
                done = self.run_gh(OPENWIZ_GITHUB_API_BASE=base or refusing.base())
                self.assertEqual((done.returncode, done.stderr),
                                 (0, NOTE.replace("<reason>", "unreachable") + "\n"))
                self.assertFalse(held.exists(), "out of the cache, so it is never handed out")
                kept = self.side_files()
                self.assertEqual([json.loads(path.read_text()) for path in kept], [before],
                                 "the token file is kept whole for a later revoke")
                self.assertEqual(kept[0].stat().st_mode & 0o777, 0o600)
                self.assertEqual(refusing.seen and [len(refusing.seen)], [1] if base is None else [])
                self.assertEqual([c["gh_token"] for c in self.calls("gh")], [None])
                api = self.api()
                api.watch = held
                later = self.revoke(api)
                self.assertEqual((later.returncode, later.stderr), (0, ""))
                self.assert_revoked_once(api)
                self.assertEqual(self.side_files(), [])
                self.assert_never_exposed(done, later)

    def test_a_kept_expiring_token_is_never_handed_out_again(self):
        # comment-ok: catches: a token kept after a failed revoke being handed to the next run's gh, its
        # git or the caller, because the refresh boundary is skipped for a kept file.
        self.expiring()
        self.answers(answer(), {"exit": 1, "stdout": ""})
        refusing = self.api(status=401)
        self.env["OPENWIZ_GITHUB_API_BASE"] = refusing.base()
        self.run_gh()
        self.assertEqual([live_token_in(path) for path in self.side_files()], [TOKEN], "the token was kept")
        github = self.github()
        outputs = [self.run_gh(), self.helper("run", *REQ, "--", *github.git()),
                   self.helper("run", *REQ, "--", "git", "credential", "fill",
                               stdin="protocol=https\nhost=github.com\n\n"),
                   self.start()]
        self.assertEqual([live_token_in(path) for path in self.side_files()], [TOKEN],
                         "still kept after every fallback")
        self.assertEqual([c["gh_token"] for c in self.calls("gh")], [None, None])
        self.assertNotIn(sha(f"x-access-token:{TOKEN}"), github.seen)
        for result in outputs[:1] + outputs[3:]:
            self.assertEqual(result.stderr, NOTE.replace("<reason>", "unreachable") + "\n")
        self.assertEqual(len(self.service_calls()), 1 + 1 + len(outputs),
                         "each use asks for a fresh token instead of using the kept one")
        self.assert_never_exposed(*outputs)


    def test_a_kept_fresh_token_is_never_reused_when_the_route_returns(self):
        # comment-ok: catches: a fresh token kept after a failed fallback revoke (the pairing turned off)
        # being handed out again once the route is back, because its file still names its scope.
        held = self.minted()
        refusing = self.api(status=401)
        self.env["OPENWIZ_GITHUB_API_BASE"] = refusing.base()
        off = self.start(OPENWIZ_TOKEN_SERVICE_READBACK="failed")
        self.assertEqual(off.stderr, NOTE.replace("<reason>", "pairing-off") + "\n")
        self.assertEqual([live_token_in(path) for path in self.side_files()], [TOKEN],
                         "the token is kept for a later revoke")
        self.answers(answer(), answer(token=TOKEN2))
        back = self.run_gh()
        self.assertEqual((back.returncode, back.stderr), (0, ""))
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN2), "a fresh mint, not the kept token")
        self.assertEqual(len(self.service_calls()), 2)
        self.assert_never_exposed(off, back)

    def kept_token(self):
        held = self.minted()
        refusing = self.api(status=401)
        off = self.start(OPENWIZ_TOKEN_SERVICE_READBACK="failed", OPENWIZ_GITHUB_API_BASE=refusing.base())
        self.assertEqual(off.stderr, NOTE.replace("<reason>", "pairing-off") + "\n")
        self.assertEqual([live_token_in(path) for path in self.side_files()], [TOKEN])
        return held

    def side_files(self):
        return sorted(self.private.glob("kept-*")) if self.private.is_dir() else []

    def test_a_new_mint_revokes_a_kept_token_before_replacing_it(self):
        # comment-ok: catches: a new mint that overwrites a kept token's file without revoking it, so the
        # kept token stays live and nobody holds it.
        held = self.kept_token()
        api = self.api()
        api.watch = held
        self.answers(answer(token=TOKEN2))
        back = self.run_gh(OPENWIZ_GITHUB_API_BASE=api.base())
        self.assertEqual((back.returncode, back.stderr), (0, ""))
        self.assert_revoked_once(api, TOKEN)
        self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN2))
        self.assertEqual(self.held()["token"], TOKEN2)
        self.assertEqual(self.side_files(), [])
        self.assert_never_exposed(back)

    def test_a_new_mint_keeps_a_kept_token_beside_it_when_the_revoke_fails(self):
        # comment-ok: catches: a new mint that overwrites a kept token whose revoke failed, or hands that
        # kept token to gh, git or the caller once it sits beside the new one.
        self.kept_token()
        refusing = self.api(status=401)
        self.env["OPENWIZ_GITHUB_API_BASE"] = refusing.base()
        self.answers(answer(token=TOKEN2))
        outputs = [self.run_gh()]
        self.assertEqual((outputs[0].returncode, outputs[0].stderr), (0, ""))
        self.assertEqual(self.held()["token"], TOKEN2, "the new token is the request's cache")
        sides = self.side_files()
        self.assertEqual(len(sides), 1, "the kept token sits beside the new one")
        self.assertEqual(json.loads(sides[0].read_text())["token"], TOKEN)
        self.assertEqual(sides[0].stat().st_mode & 0o777, 0o600)
        github = self.github()
        outputs += [self.run_gh(), self.helper("run", *REQ, "--", *github.git()), self.start()]
        self.assertEqual([c["gh_token"] for c in self.calls("gh")], [sha(TOKEN2)] * 2)
        self.assertEqual(set(github.seen), {sha(f"x-access-token:{TOKEN2}")})
        self.assertEqual(len(self.side_files()), 1, "later uses neither drop nor copy it")
        api = self.api()
        done = self.revoke(api)
        self.assertEqual((done.returncode, done.stderr), (0, ""))
        self.assertEqual(sorted(seen["auth"] for seen in api.seen),
                         sorted([sha(f"Bearer {TOKEN}"), sha(f"Bearer {TOKEN2}")]))
        self.assertEqual({seen["method"] for seen in api.seen}, {"DELETE"})
        self.assertEqual(self.side_files(), [])
        self.assertFalse(self.token_file().exists())
        self.assert_never_exposed(*outputs, done)


class RevokeReview(Helper):
    api, minted, revoke, assert_revoked_once = (
        Revoke.api, Revoke.minted, Revoke.revoke, Revoke.assert_revoked_once)
    expiring, run_gh, side_files = FallbackRevoke.expiring, FallbackRevoke.run_gh, FallbackRevoke.side_files

    def inside_run(self, script, api, **env):
        return self.helper("run", *REQ, "--", "/bin/sh", "-c", script, OPENWIZ_GITHUB_API_BASE=api.base(),
                           PRIV=str(self.private), PY=sys.executable, H=str(HELPER),
                           CACHE=str(self.token_file()), **env)

    def bytes_kept(self):
        for path in self.private.iterdir():
            path.chmod(0o600)
        return [path.read_bytes() for path in sorted(self.private.iterdir())]

    def test_r1_an_unreadable_or_corrupt_cache_file_is_never_deleted_or_replaced(self):
        # comment-ok: catches: a fallback or mint that deletes or overwrites a cache file it cannot read,
        # treating a failed read like a confirmed expiry, so a live token nobody can revoke is lost.
        for name, damage in (("unreadable", lambda path: path.chmod(0)),
                             ("corrupt", lambda path: path.write_bytes(path.read_bytes()[:-1]))):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                self.log.unlink(missing_ok=True)
                held = self.minted()
                damage(held)
                self.answers(answer(), {"exit": 1, "stdout": ""}, answer(token=TOKEN2))
                off = self.run_gh()
                self.assertEqual(off.stderr, NOTE.replace("<reason>", "unreachable") + "\n")
                back = self.run_gh()
                self.assertEqual((back.returncode, back.stderr), (0, ""))
                self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN2))
                kept = self.bytes_kept()
                self.assertEqual(len(kept), 2, "the unreadable file is kept beside the new token")
                self.assertTrue(any(TOKEN.encode() in b for b in kept), "with the old token's bytes")
                self.assertEqual(self.revoke_api.seen, [])

    def test_r2_a_refresh_revokes_the_token_it_replaces_unless_a_run_still_holds_it(self):
        # comment-ok: catches: a refresh that drops a still-live token with no DELETE and no copy, or that
        # revokes a token another run still uses, or that drops it when its revoke fails.
        for name, status in (("revoked", 204), ("kept when the revoke fails", 401)):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                self.log.unlink(missing_ok=True)
                self.expiring()
                self.answers(answer(), answer(token=TOKEN2))
                api = self.api(status=status)
                api.watch = self.private
                ran = self.run_gh(OPENWIZ_GITHUB_API_BASE=api.base())
                self.assertEqual((ran.returncode, ran.stderr), (0, ""))
                self.assertEqual(self.calls("gh")[-1]["gh_token"], sha(TOKEN2))
                self.assert_revoked_once(api, TOKEN)
                self.assertEqual([live_token_in(p) for p in self.side_files()], [] if status == 204 else [TOKEN])
        with self.subTest("another run still holds it"):
            shutil.rmtree(self.private, True)
            self.log.unlink(missing_ok=True)
            self.minted()
            self.answers(answer(), answer(token=TOKEN2))
            api = self.api()
            api.watch = self.private
            shorten = ('"$PY" -c \'import json,sys,time;p=sys.argv[1];d=json.load(open(p));'
                       'd["expires_at"]=int(time.time())+100;json.dump(d,open(p,"w"))\' "$CACHE"')
            script = f'{shorten}; "$PY" -I "$H" run {" ".join(REQ)} -- gh pr list; gh pr list'
            done = self.inside_run(script, api)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            self.assertEqual([c["gh_token"] for c in self.calls("gh")], [sha(TOKEN2), sha(TOKEN)],
                             "the outer run keeps its token while it runs")
            self.assert_revoked_once(api, TOKEN)
            self.assertEqual(self.side_files(), [])
            self.assert_never_exposed(done)

    def test_r3_a_mint_during_a_revoke_keeps_the_new_token(self):
        # comment-ok: catches: a revoke that deletes whatever the cache file holds after its DELETE, so a
        # token minted meanwhile is deleted unrevoked.
        self.expiring()
        self.answers(answer(), answer(token=TOKEN2))
        api = self.api()
        started = []
        api.during = lambda: started.append(self.start(OPENWIZ_GITHUB_API_BASE=api.base()))
        done = self.revoke(api)
        self.assertEqual((done.returncode, done.stderr, started[0].returncode), (0, "", 0))
        self.assertEqual(api.seen[0]["auth"], sha(f"Bearer {TOKEN}"))
        self.assertEqual(self.held()["token"], TOKEN2, "the new token is still held")
        self.assert_never_exposed(done, *started)

    def test_r4_revoke_finds_this_runs_token_after_the_folder_moved_or_went(self):
        # comment-ok: catches: a revoke that skips this run's snapshot because its recorded path is stale,
        # or that needs the folder at all, so a moved or deleted folder leaves a live token.
        for name, damage in (("moved", 'chmod 000 "$CACHE"; mv "$PRIV" "$MOVED"; OPENWIZ_AGENT_TOKEN_REVOKE='),
                             ("gone", 'rm -rf "$PRIV"')):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                shutil.rmtree(self.root / "moved", True)
                self.minted()
                api = self.api()
                script = (f'{damage}; OPENWIZ_AGENT_TOKEN_DIR="$MOVED" "$PY" -I "$H" revoke {" ".join(REQ)}')
                done = self.inside_run(script, api, MOVED=str(self.root / "moved"))
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, "", ""))
                self.assertEqual([(s["method"], s["auth"]) for s in api.seen],
                                 [("DELETE", sha(f"Bearer {TOKEN}"))])

    def test_r5_revoke_inside_a_run_never_revokes_another_requests_token(self):
        # comment-ok: catches: a revoke that takes this run's snapshot for any request, so revoking B
        # from inside A's run revokes A's token.
        self.minted()
        api = self.api()
        other = " ".join(REQ[:3] + ("synthetic-owner/other",))
        done = self.inside_run(f'"$PY" -I "$H" revoke {other}', api)
        self.assertEqual((done.returncode, done.stderr), (1, NO_TOKEN))
        self.assertEqual(api.seen, [])
        self.assertEqual(self.held()["token"], TOKEN)

    def test_r6_a_kept_token_is_never_handed_out_again(self):
        # comment-ok: catches: a token kept after a failed fallback or explicit revoke still reaching an
        # active run's gh, or a new run through the cache.
        self.minted()
        refusing = self.api(status=401)
        inner = f'OPENWIZ_TOKEN_SERVICE_READBACK=failed "$PY" -I "$H" start {" ".join(REQ)}; gh pr list'
        done = self.inside_run(inner, refusing)
        self.assertEqual(done.returncode, 128)
        self.assertEqual(self.calls("gh"), [], "the active run's gh gets no kept token")
        self.assertEqual([live_token_in(p) for p in self.side_files()], [TOKEN])
        shutil.rmtree(self.private, True)
        self.log.unlink()
        self.minted()
        failed = self.revoke(refusing)
        self.assertEqual(failed.returncode, 1)
        self.answers(answer(), answer(token=TOKEN2))
        ran = self.run_gh()
        self.assertEqual([c["gh_token"] for c in self.calls("gh")], [sha(TOKEN2)], "a new run mints afresh")
        self.assert_never_exposed(done, failed, ran)

    def test_r7_a_malformed_api_base_gives_the_one_fixed_line(self):
        # comment-ok: catches: a URL parsing error escaping the base check as a traceback in revoke or a
        # fallback.
        held = self.minted()
        done = self.helper("revoke", *REQ, OPENWIZ_GITHUB_API_BASE="http://[127.0.0.1")
        self.assertEqual((done.returncode, done.stderr), (1, NOT_REVOKED.format("not the GitHub API")))
        self.answers(answer(), {"exit": 1, "stdout": ""})
        off = self.start(OPENWIZ_TOKEN_SERVICE_READBACK="failed", OPENWIZ_GITHUB_API_BASE="http://[127.0.0.1")
        self.assertEqual((off.returncode, off.stderr), (0, NOTE.replace("<reason>", "pairing-off") + "\n"))
        self.assertEqual([live_token_in(p) for p in [held, *self.side_files()] if p.exists()], [TOKEN])


PROBE = r"""
import os, stat
held = sockets = 0
for fd in map(int, os.listdir("/proc/self/fd")):
    try:
        sockets += fd > 2 and stat.S_ISSOCK(os.fstat(fd).st_mode)
        held += fd > 2 and b'"token"' in os.pread(fd, 1 << 16, 0)
    except OSError:
        pass
print(held, sockets)
"""


class FinalRound(Helper):
    api, minted, revoke = Revoke.api, Revoke.minted, Revoke.revoke
    expiring, run_gh, side_files = FallbackRevoke.expiring, FallbackRevoke.run_gh, FallbackRevoke.side_files
    inside_run = RevokeReview.inside_run

    def deletes(self, api):
        return [(seen["method"], seen["auth"]) for seen in api.seen]

    def test_r4_a_failed_revoke_after_the_folder_went_leaves_a_retry_copy(self):
        # comment-ok: catches: a run whose folder was deleted ending with its token live and no copy left,
        # after an in-run revoke GitHub refused or with no revoke at all, so a later revoke finds nothing.
        for name, script, code in (
                ("in-run revoke refused", f'rm -rf "$PRIV"; "$PY" -I "$H" revoke {" ".join(REQ)}', 1),
                ("no revoke before the run ends", 'rm -rf "$PRIV"', 0),
                ("revoke refused, then the folder went",
                 f'"$PY" -I "$H" revoke {" ".join(REQ)}; rm -rf "$PRIV"; exit 1', 1)):
            with self.subTest(name):
                shutil.rmtree(self.private, True)
                self.minted()
                refusing = self.api(status=401)
                done = self.inside_run(script, refusing)
                stderr = NOT_REVOKED.format("GitHub refused") if code else ""
                self.assertEqual((done.returncode, done.stdout, done.stderr), (code, "", stderr))
                self.assertEqual(self.deletes(refusing), [("DELETE", sha(f"Bearer {TOKEN}"))] * (1 + (
                    name == "revoke refused, then the folder went")), "the run end retries a copy it rebuilt")
                api = self.api()
                later = self.revoke(api)
                self.assertEqual((later.returncode, later.stderr), (0, ""), "a retry copy survives the run")
                self.assertEqual(self.deletes(api), [("DELETE", sha(f"Bearer {TOKEN}"))])
                self.assert_never_exposed(done, later)

    def test_r6_a_fallback_retires_an_unreadable_entry_for_every_active_run(self):
        # comment-ok: catches: an active run's gh still getting the token after a fallback kept the
        # request's unreadable cache entry, because retirement was read from the damaged bytes.
        self.minted()
        refusing = self.api(status=401)
        inner = (f'chmod 000 "$CACHE"; OPENWIZ_TOKEN_SERVICE_READBACK=failed "$PY" -I "$H" start {" ".join(REQ)}'
                 '; gh pr list')
        done = self.inside_run(inner, refusing)
        self.assertEqual(done.returncode, 128)
        self.assertEqual(self.calls("gh"), [], "the active run's gh gets no retired token")
        self.assertEqual(self.deletes(refusing), [("DELETE", sha(f"Bearer {TOKEN}"))])
        self.assert_never_exposed(done)

    def gated(self):
        gated, gate = self.root / "gated", self.root / "gate"
        gated.mkdir(exist_ok=True)
        (gated / "room-cli").write_text(f'#!/bin/sh\n: > "{gate}.started"\n'
                                        f'while [ ! -e "{gate}" ]; do sleep 0.05; done\n'
                                        f'exec "{self.bin}/room-cli" "$@"\n')
        (gated / "room-cli").chmod(0o755)
        full = dict(self.env, PATH=f"{gated}:{self.env['PATH']}")
        minting = subprocess.Popen([sys.executable, "-I", str(HELPER), "start", *REQ], env=full,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(minting.kill)
        deadline = time.monotonic() + 20
        while not Path(f"{gate}.started").exists():
            self.assertLess(time.monotonic(), deadline, "the mint reached the service")
            time.sleep(0.05)
        return minting, gate

    def test_r8_a_mint_in_flight_stores_or_revokes_its_answer(self):
        # comment-ok: catches: a revoke removing the token folder under an in-flight mint, or a mint that
        # cannot store its answer leaving the fresh token live with no copy and no DELETE.
        with self.subTest("a revoke during the mint"):
            self.expiring()
            self.answers(answer(), answer(token=TOKEN2))
            minting, gate = self.gated()
            api = self.api()
            done = self.revoke(api)
            self.assertEqual((done.returncode, done.stderr), (0, ""))
            gate.touch()
            out, err = minting.communicate(timeout=30)
            self.assertEqual((minting.returncode, out, err), (0, "", ""))
            self.assertEqual(self.held()["token"], TOKEN2, "the fresh token is stored")
            self.assertEqual(self.private.stat().st_mode & 0o777, 0o700)
        with self.subTest("the folder deleted during the mint"):
            shutil.rmtree(self.private, True)
            for left in ("gate", "gate.started"):
                (self.root / left).unlink()
            self.log.unlink()
            self.expiring()
            self.answers(answer(), answer(token=TOKEN2))
            minting, gate = self.gated()
            shutil.rmtree(self.private)
            gate.touch()
            out, err = minting.communicate(timeout=30)
            self.assertEqual((minting.returncode, out, len(err.splitlines())), (2, "", 1), err)
            self.assertEqual(self.deletes(self.revoke_api), [("DELETE", sha(f"Bearer {TOKEN2}"))],
                             "the fresh token it could not store is revoked")
            self.assertNotIn(TOKEN2, err)

    def test_a_mint_that_loses_its_folder_keeps_its_token_for_a_later_revoke(self):
        # comment-ok: catches: a mint whose folder was deleted in flight and whose emergency DELETE GitHub
        # refused leaving the fresh token live with no copy, so no later revoke or mint can find it; or the
        # copy being written through a symlink planted where the folder was.
        went = "openwiz: agent-token: the private token directory went away, so the new token was "
        fresh = [("DELETE", sha(f"Bearer {TOKEN2}"))]
        for later, status, said in (
                ("revoke", 401, "not revoked (GitHub refused); the token is kept for a later revoke\n"),
                ("mint", 401, "not revoked (GitHub refused); the token is kept for a later revoke\n"),
                ("nothing", 204, "revoked\n"),
                ("a symlink in its place", 401, "not revoked (GitHub refused): suspend the installation\n")):
            with self.subTest(later=later):
                elsewhere, planted = self.root / "elsewhere", later == "a symlink in its place"
                shutil.rmtree(self.private, True)
                for left in ("gate", "gate.started", "calls.log"):
                    (self.root / left).unlink(missing_ok=True)
                self.answers(answer(token=TOKEN2), answer())
                first, copies = self.api(status=status), []
                first.during = lambda: copies.append(len(self.side_files()))
                self.env["OPENWIZ_GITHUB_API_BASE"] = first.base()
                minting, gate = self.gated()
                shutil.rmtree(self.private)
                if planted:
                    elsewhere.mkdir(mode=0o700)
                    self.private.symlink_to(elsewhere)
                    self.addCleanup(self.private.unlink)
                gate.touch()
                out, err = minting.communicate(timeout=30)
                self.assertEqual((minting.returncode, out), (2, ""))
                self.assertEqual(copies, [0 if planted else 1],
                                 "the copy is saved before the emergency DELETE is sent, never through a symlink")
                self.assertEqual(self.deletes(first), fresh)
                self.assertEqual(err, went + said)
                sides = self.side_files()
                self.assertEqual(len(sides), status != 204 and not planted, "kept until GitHub answers 204")
                self.assertEqual(list(elsewhere.glob("*")), [], "nothing is written where the symlink points")
                self.assertFalse(self.token_file().exists(), "the refused mint leaves no usable cache")
                done = [types.SimpleNamespace(stdout=out, stderr=err)]
                if sides:
                    self.assertEqual(json.loads(sides[0].read_text())["token"], TOKEN2)
                    self.assertEqual((sides[0].stat().st_mode & 0o777, self.private.stat().st_mode & 0o777),
                                     (0o600, 0o700), "owner-only copy in an owner-only folder")
                    api = self.api()
                    self.env["OPENWIZ_GITHUB_API_BASE"] = api.base()
                    done.append(self.start() if later == "mint" else self.revoke(api))
                    self.assertEqual((done[1].returncode, done[1].stderr), (0, ""))
                    self.assertEqual(self.deletes(api), fresh, f"a later {later} finds and revokes it")
                    self.assertEqual(self.side_files(), [])
                    self.assertEqual(self.token_file().exists(), later == "mint")
                self.assert_never_exposed(*done)

    def test_a_refused_emergency_delete_reports_kept_only_when_a_copy_is_findable(self):
        # comment-ok: catches: a refused emergency DELETE reporting the token kept from a save made before
        # the call, after the folder or its copy was removed while the DELETE was pending, so a later
        # revoke finds nothing while the owner is told a retry is possible.
        went = "openwiz: agent-token: the private token directory went away, so the new token was not revoked "
        fresh = [("DELETE", sha(f"Bearer {TOKEN2}"))]
        elsewhere = self.root / "elsewhere"

        def unsafe():
            shutil.rmtree(self.private)
            elsewhere.mkdir(mode=0o700)
            self.private.symlink_to(elsewhere)

        for pending, gone, kept in (
                ("the folder removed", lambda: shutil.rmtree(self.private), True),
                ("the copy removed", lambda: [path.unlink() for path in self.side_files()], True),
                ("a symlink in the folder's place", unsafe, False)):
            with self.subTest(pending=pending):
                if self.private.is_symlink():
                    self.private.unlink()
                shutil.rmtree(self.private, True)
                for left in ("gate", "gate.started", "calls.log"):
                    (self.root / left).unlink(missing_ok=True)
                self.answers(answer(token=TOKEN2), answer())
                refusing = self.api(status=401)
                refusing.during = gone
                self.env["OPENWIZ_GITHUB_API_BASE"] = refusing.base()
                minting, gate = self.gated()
                shutil.rmtree(self.private)
                gate.touch()
                out, err = minting.communicate(timeout=30)
                self.assertEqual((minting.returncode, out), (2, ""))
                self.assertEqual(self.deletes(refusing), fresh)
                self.assertEqual(err, went + ("(GitHub refused); the token is kept for a later revoke\n" if kept
                                              else "(GitHub refused): suspend the installation\n"))
                self.assertEqual(list(elsewhere.glob("*")), [], "nothing is written where the symlink points")
                done = [types.SimpleNamespace(stdout=out, stderr=err)]
                if kept:
                    sides = self.side_files()
                    self.assertEqual([json.loads(side.read_text())["token"] for side in sides], [TOKEN2])
                    self.assertEqual((sides[0].stat().st_mode & 0o777, self.private.stat().st_mode & 0o777),
                                     (0o600, 0o700), "owner-only copy in an owner-only folder")
                    api = self.api()
                    done.append(self.revoke(api))
                    self.assertEqual((done[1].returncode, done[1].stderr), (0, ""))
                    self.assertEqual(self.deletes(api), fresh, "a later revoke finds and revokes it")
                    self.assertEqual(self.side_files(), [])
                self.assert_never_exposed(*done)
        self.private.unlink()

    @unittest.skipUnless(os.path.isdir("/proc/self/fd"), "needs /proc/self/fd")
    def test_r9_no_child_inherits_a_readable_credential_handle(self):
        # comment-ok: catches: a run handing its children an open, readable copy of the token, which a
        # nested fallback child running as the owner keeps after the token is retired.
        self.minted()
        (self.root / "probe.py").write_text(PROBE)
        nested = (f'"$PY" -I "$PROBE"; OPENWIZ_TOKEN_SERVICE_READBACK=failed "$PY" -I "$H" run {" ".join(REQ)}'
                  ' -- "$PY" -I "$PROBE"')
        done = self.inside_run(nested, self.api(), PROBE=str(self.root / "probe.py"))
        self.assertEqual((done.returncode, done.stdout), (0, "0 1\n0 0\n"),
                         "no fd that reads as a token; only the run's revoke socket, never in a fallback child")
        self.assert_never_exposed(done)


class SnapshotByName(Helper):
    api, minted, inside_run, deletes = Revoke.api, Revoke.minted, RevokeReview.inside_run, FinalRound.deletes

    def test_a_fallback_retires_an_unreadable_run_snapshot_by_name(self):
        # comment-ok: catches: a fallback that skips a run snapshot it cannot read, leaving it under its
        # active name, so once it is readable again after GitHub refused the revoke the run's gh gets the token.
        self.minted()
        refusing = self.api(status=401)
        inner = (f'chmod 000 "$OPENWIZ_AGENT_TOKEN_RUN"; OPENWIZ_TOKEN_SERVICE_READBACK=failed "$PY" -I "$H" '
                 f'start {" ".join(REQ)}; chmod 600 "$OPENWIZ_AGENT_TOKEN_RUN" 2>/dev/null; gh pr list')
        done = self.inside_run(inner, refusing)
        self.assertEqual(self.deletes(refusing), [("DELETE", sha(f"Bearer {TOKEN}"))])
        self.assertEqual((done.returncode, self.calls("gh")), (128, []), "the retired snapshot is never served")
        self.assertEqual(list(self.private.glob("run-*")), [])
        self.assert_never_exposed(done)

    WANTED = {"requester": "builder-1", "repositories": [REPO], "permissions": WRITE}

    def loaded(self):
        helper = load_helper()
        private = helper.Private(self.env, create=True)
        self.addCleanup(os.close, private.fd)
        cache = helper.cache_name(self.WANTED)
        self.assertEqual(cache, self.token_file().name, "the test and the helper name one request")
        return helper, private, cache

    def test_a_snapshot_write_never_replaces_a_snapshot_already_at_its_name(self):
        # comment-ok: catches: a snapshot write that replaces a file already at its name, so a run whose
        # saved path a later run's name collides with is handed that later run's token.
        for branch in ("cached", "minted"):
            with self.subTest(branch):
                shutil.rmtree(self.private, True)
                self.minted()
                helper, private, cache = self.loaded()
                name = helper.snapshot_prefix(cache) + "0" * 16 + ".json"
                helper.token_for(private, self.WANTED, self.env, snapshot=name)
                first = hashlib.sha256((self.private / name).read_bytes()).hexdigest()
                if branch == "cached":
                    (self.private / cache).write_text(json.dumps(
                        {"token": TOKEN2, "expires_at": int(time.time()) + 3600, **self.WANTED}))
                else:
                    (self.private / cache).unlink()
                    self.answers(answer(token=TOKEN2))
                refused = False
                try:
                    helper.token_for(private, self.WANTED, self.env, snapshot=name)
                except (helper.Refused, FileExistsError):
                    refused = True
                self.assertEqual((refused, hashlib.sha256((self.private / name).read_bytes()).hexdigest()),
                                 (True, first),
                                 "the second write is refused and the first snapshot is unchanged")

    def test_a_later_run_never_takes_the_name_a_live_run_had_retired(self):
        # comment-ok: catches: a later run taking the snapshot name a still-running run saved, once a
        # fallback retired it, so the first run's saved path serves the later run's token.
        self.minted()
        helper = load_helper()
        refusing = self.api(status=401)
        env = dict(self.env, OPENWIZ_GITHUB_API_BASE=refusing.base())
        real, forced, seen = helper.secrets.token_hex, ["ab" * 8], {}

        def token_hex(size):
            return forced.pop() if forced and size == 8 else real(size)

        def later_child(command, child, **kwargs):
            seen["later"] = child.get(helper.RUN_MARK)
            reason, token = helper.snapshot_token(seen["first"][helper.RUN_MARK], seen["first"],
                                                  check=lambda snapshot, env: None)
            seen["served"] = (reason, token and sha(token))
            return 0

        def first_child(command, child, **kwargs):
            seen["first"] = dict(child)
            helper.start(list(REQ), dict(env, OPENWIZ_TOKEN_SERVICE_READBACK="failed"))
            self.answers(answer(token=TOKEN2))
            forced.append("ab" * 8)
            with mock.patch.object(helper, "execute", later_child):
                return helper.run([*REQ, "--", "true"], dict(env))

        with mock.patch.object(helper.secrets, "token_hex", token_hex), \
                mock.patch.object(helper, "execute", first_child), \
                mock.patch.object(helper.sys, "stderr"):
            self.assertEqual(helper.run([*REQ, "--", "true"], dict(env)), 0)
        first = seen["first"][helper.RUN_MARK]
        self.assertTrue(first.endswith("ab" * 8 + ".json"), "the first run took the forced name")
        self.assertEqual(seen["served"], ("no current token", None),
                         "the first run's saved path serves nothing after its snapshot was retired")
        self.assertTrue(seen["later"] and seen["later"] != first, "the later run got a name of its own")
        self.assertEqual(sorted(p.name for p in self.private.iterdir() if not p.name.startswith(("token-", "kept-"))),
                         [], "each run removes its snapshot and its reservation")

    def test_a_later_run_never_takes_the_path_of_a_retired_snapshot_named_before_the_upgrade(self):
        # comment-ok: catches: an upgraded run whose snapshot name has the shape a pre-upgrade run's
        # random name had, so once pre-upgrade code retires a still-running legacy run's snapshot
        # without claiming a slot, a later run can draw that same name and serve its token there.
        for retired_by in ("upgraded fallback", "pre-upgrade retire"):
            with self.subTest(retired_by):
                shutil.rmtree(self.private, True)
                cache = self.minted()
                helper, private, cache_file = self.loaded()
                legacy = self.private / ("run-" + cache.name[len("token-"):][:16] + "ab" * 8 + ".json")
                legacy.write_text(json.dumps({"token": TOKEN, "expires_at": int(time.time()) + 3600,
                                              "request": cache.name}))
                legacy.chmod(0o600)
                if retired_by == "upgraded fallback":
                    refusing = self.api(status=401)
                    self.helper("start", *REQ, OPENWIZ_TOKEN_SERVICE_READBACK="failed",
                                OPENWIZ_GITHUB_API_BASE=refusing.base())
                else:
                    with helper.locked(private):
                        helper.drop(private, cache_file, cache_file, retire=True)
                        helper.drop(private, legacy.name, cache_file, retire=True)
                    self.assertEqual(list(self.private.glob("slot-*")), [], "pre-upgrade retire claims no slot")
                self.assertFalse(legacy.exists(), "the legacy snapshot was retired")
                self.answers(answer(token=TOKEN2))
                real, seen = helper.secrets.token_hex, {}

                def later_child(command, child, **kwargs):
                    seen["later"] = child.get(helper.RUN_MARK)
                    reason, token = helper.snapshot_token(
                        str(legacy), dict(self.env, **{helper.RUN_MARK: str(legacy)}),
                        check=lambda snapshot, env: None)
                    seen["served"] = (legacy.exists(), reason, token and sha(token))
                    return 0

                with mock.patch.object(helper.secrets, "token_hex", lambda size: "ab" * 8 if size == 8 else real(size)), \
                        mock.patch.object(helper, "execute", later_child), \
                        mock.patch.object(helper.sys, "stderr"):
                    self.assertEqual(helper.run([*REQ, "--", "true"], dict(self.env)), 0)
                self.assertTrue(seen["later"], "the later run was handed a snapshot")
                self.assertEqual((seen["later"] != str(legacy), seen["served"]),
                                 (True, (False, "no current token", None)),
                                 "the legacy run's retired path stays empty and serves nothing while a later run runs")

    def test_a_run_that_cannot_reserve_a_free_name_is_refused(self):
        # comment-ok: catches: a run that goes on under a name another run still holds once every
        # name it draws is taken, instead of stopping with no token handed over.
        self.minted()
        helper, private, cache = self.loaded()
        with mock.patch.object(helper.secrets, "token_hex", lambda size: "cd" * size):
            name = helper.reserve(private, cache)
            with self.assertRaises(helper.Refused):
                helper.reserve(private, cache)
        self.assertEqual([p.name for p in self.private.glob("slot-*")], [helper.slot_name(name)])

    def test_a_fallback_or_revoke_retires_a_readable_snapshot_named_before_the_upgrade(self):
        # comment-ok: catches: a fallback or revoke that selects snapshots by name alone, so a run started
        # before the upgrade, whose snapshot has a random name, keeps serving a token that was retired.
        for route in ("fallback", "revoke"):
            with self.subTest(route):
                shutil.rmtree(self.private, True)
                cache = self.minted()
                until = int(time.time()) + 3600
                legacy = self.private / ("run-" + "f0" * 16 + ".json")
                other = self.private / ("run-" + "0f" * 16 + ".json")
                legacy.write_text(json.dumps({"token": TOKEN, "expires_at": until, "request": cache.name}))
                other.write_text(json.dumps({"token": "synthetic-agent-token-3", "expires_at": until,
                                             "request": "token-" + "0" * 32 + ".json"}))
                legacy.chmod(0o600)
                other.chmod(0o600)
                refusing = self.api(status=401)
                args = ("start", *REQ) if route == "fallback" else ("revoke", *REQ)
                done = self.helper(*args, OPENWIZ_TOKEN_SERVICE_READBACK="failed",
                                   OPENWIZ_GITHUB_API_BASE=refusing.base())
                self.assertEqual(self.deletes(refusing), [("DELETE", sha(f"Bearer {TOKEN}"))])
                self.assertEqual(sorted(p.name for p in self.private.glob("run-*")), [other.name],
                                 "the request's legacy snapshot is retired, and another request's is left")
                api = self.api()
                later = self.helper("revoke", *REQ, OPENWIZ_GITHUB_API_BASE=api.base())
                self.assertEqual((later.returncode, later.stderr), (0, ""), "the kept copy is still revocable")
                self.assertEqual(self.deletes(api), [("DELETE", sha(f"Bearer {TOKEN}"))])
                self.assert_never_exposed(done, later)

    def test_a_read_that_fails_never_leaves_a_retired_name_active(self):
        # comment-ok: catches: a retirement that reads a snapshot or the cache entry before it removes
        # active names, so one read-time I/O error escapes and every active name stays in place.
        for route in ("fallback", "revoke"):
            for bad in ("run-", "token-"):
                with self.subTest(route=route, unreadable=bad):
                    shutil.rmtree(self.private, True)
                    self.minted()
                    helper, private, cache = self.loaded()
                    name = helper.snapshot_prefix(cache) + "0" * 16 + ".json"
                    helper.token_for(private, self.WANTED, self.env, snapshot=name)
                    broken = os.stat(self.private / (name if bad == "run-" else cache)).st_ino
                    read = helper.Private.read

                    def failing(folder, entry, broken=broken, read=read):
                        try:
                            found = os.stat(entry, dir_fd=folder.fd).st_ino
                        except OSError:
                            found = None
                        if found == broken:
                            raise OSError(5, "synthetic read failure")
                        return read(folder, entry)

                    refusing = self.api(status=401)
                    env = dict(self.env, OPENWIZ_GITHUB_API_BASE=refusing.base(),
                               OPENWIZ_TOKEN_SERVICE_READBACK="failed")
                    escaped = None
                    with mock.patch.object(helper.Private, "read", failing), \
                            mock.patch.object(helper.sys, "stderr"):
                        try:
                            if route == "fallback":
                                helper.token_for(private, self.WANTED, env)
                            else:
                                helper.revoke_request(private, refusing.base(), cache)
                        except OSError as error:
                            escaped = error.errno
                    active = sorted(p.name for p in self.private.iterdir()
                                    if p.name.startswith(("token-", "run-")))
                    self.assertEqual((escaped, active), (None, []), "no error escapes and no active name is left")
                    self.assertEqual(self.deletes(refusing), [("DELETE", sha(f"Bearer {TOKEN}"))])

    def test_a_pre_upgrade_helper_still_retires_an_upgraded_run_snapshot(self):
        # comment-ok: catches: revoke trusting a pre-upgrade run channel's answer alone, so an
        # upgraded run's disjoint-shaped snapshot (readable or mode 000) stays active after GitHub
        # refuses the revoke.
        for mode in (0o600, 0):
            with self.subTest(mode=oct(mode)):
                shutil.rmtree(self.private, True)
                self.minted()
                helper, private, cache_file = self.loaded()
                name = helper.reserve(private, cache_file)
                helper.token_for(private, self.WANTED, self.env, snapshot=name)
                snapshot = self.private / name
                snapshot.chmod(mode)
                refusing = self.api(status=401)
                env = dict(self.env, OPENWIZ_GITHUB_API_BASE=refusing.base())
                with mock.patch.object(helper, "ask_run", return_value="GitHub refused"), \
                        mock.patch.object(helper.sys, "stderr"):
                    self.assertEqual(helper.revoke(list(REQ), env), 1)
                if snapshot.exists():
                    snapshot.chmod(0o600)
                reason, served = helper.snapshot_token(
                    str(snapshot), dict(env, **{helper.RUN_MARK: str(snapshot)}),
                    check=lambda path, env: None)
                self.assertEqual((snapshot.exists(), reason, served and sha(served)),
                                 (False, "no current token", None),
                                 "upgraded revoke retires the snapshot even after an old run channel answered")
                if mode == 0o600:
                    api = self.api()
                    later = self.helper("revoke", *REQ, OPENWIZ_GITHUB_API_BASE=api.base())
                    self.assertEqual((later.returncode, later.stderr), (0, ""), "the kept copy is still revocable")
                    self.assertEqual(self.deletes(api), [("DELETE", sha(f"Bearer {TOKEN}"))])
                    self.assert_never_exposed(later)


def live_token_in(path):
    return json.loads(path.read_text()).get("token") if path.exists() else None


OTHER = 1001 if os.getuid() != 1001 else 1002


class SystemGh(Helper):
    def setUp(self):
        super().setUp()
        self.helper_module = helper = load_helper()
        folder = tempfile.TemporaryDirectory(dir=Path.home().resolve())
        self.addCleanup(folder.cleanup)
        self.system = Path(folder.name) / "usr-local-bin"
        self.system.mkdir(mode=0o755)
        self.real = self.system / "gh"
        self.checked = "#!/bin/sh\n# synthetic system gh\nexit 0\n"
        self.real.write_text(self.checked)
        self.real.chmod(0o755)
        self.mine = Path(folder.name) / "mine"
        self.mine.mkdir(mode=0o755)
        (self.mine / "gh").symlink_to(self.real)
        self.name = "run-" + "0" * 32 + ".json"
        private = helper.Private(self.env, create=True)
        self.addCleanup(os.close, private.fd)
        private.write(self.name, {"token": TOKEN, "expires_at": int(time.time()) + 3600})
        self.private_dir = private
        self.refuse = str(self.private / "exec-synthetic" / helper.GH_REFUSE)
        self.run_env = dict(self.env, **{helper.RUN_MARK: str(self.private / self.name)})

    def table(self, **changes):
        rows, folder = {str(self.real): (OTHER, 0o755)}, str(self.system)
        while True:
            rows[folder] = (0, 0o755)
            if folder == "/":
                break
            folder = os.path.dirname(folder)
        rows[str(self.mine)] = (0, 0o755)
        names = {"gh": str(self.real), "folder": str(self.system), "above": str(self.system.parent),
                 "link folder": str(self.mine)}
        for key, row in changes.items():
            rows[names[key]] = row
        return rows

    def faked(self, rows, before_lstat=None):
        real_stat, real_lstat = os.stat, os.lstat

        def fake(original):
            def call(target, *args, **kwargs):
                if before_lstat and original is real_lstat:
                    before_lstat(target)
                info = original(target, *args, **kwargs)
                name = (os.readlink(f"/proc/self/fd/{target}") if isinstance(target, int)
                        else os.path.realpath(target) if original is real_stat
                        else os.path.normpath(os.fspath(target)))
                if name not in rows:
                    return info
                uid, mode = rows[name]
                fields = {key: getattr(info, key) for key in dir(info) if key.startswith("st_")}
                fields.update(st_uid=uid, st_mode=stat.S_IFMT(info.st_mode) | mode)
                return types.SimpleNamespace(**fields)
            return call

        helper = self.helper_module
        return mock.patch.multiple(helper.os, stat=fake(real_stat), lstat=fake(real_lstat))

    def identity_of(self, rows, chosen=None):
        with self.faked(rows):
            return self.helper_module.gh_identity(chosen or str(self.real))

    def bind(self, rows, **binding):
        identity = self.identity_of(rows)
        self.private_dir.write(self.helper_module.gh_binding(self.name),
                               dict({"gh": str(self.real), "refuse": self.refuse, "identity": identity}, **binding))
        return identity

    def rewrite_in_place(self, text):
        before = os.stat(self.real)
        text = text.ljust(before.st_size, "#")[:before.st_size]
        with open(self.real, "r+") as handle:
            handle.write(text)
        os.utime(self.real, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = os.stat(self.real)
        self.assertEqual([after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns],
                         [before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns],
                         "the same file, the same size and time: only its bytes changed")
        return text

    def run_gh(self, rows, chosen=None, during=None, before_seal=None, at_seal=None):
        helper, ran, looked_up = self.helper_module, [], []
        load, seal = helper.snapshot_token, helper.sealed_gh
        seals = types.SimpleNamespace(**{k: getattr(fcntl, k) for k in dir(fcntl) if k.isupper()})

        def seal_call(fd, command, *args):
            if at_seal and command == getattr(fcntl, "F_ADD_SEALS", 1033):
                at_seal(fd)
            return fcntl.fcntl(fd, command, *args)

        seals.fcntl = seal_call

        def seal_after(*args):
            if before_seal:
                before_seal()
            return seal(*args)

        def load_then(*args, **kwargs):
            looked_up.append(True)
            held = load(*args, **kwargs)
            if during:
                during()
            return held

        def exec_boundary(path, args, child):
            token = child.get("GH_TOKEN")
            ran.append((path, Path(path).read_text(), list(args), token == TOKEN))
            try:
                self.seals = fcntl.fcntl(int(path.rsplit("/", 1)[1]), getattr(fcntl, "F_GET_SEALS", 1034))
            except (OSError, ValueError):
                self.seals = None
            raise OSError("synthetic exec boundary")

        with self.faked(rows), mock.patch.object(helper, "snapshot_token", load_then), \
                mock.patch.object(helper, "sealed_gh", seal_after), mock.patch.object(helper, "fcntl", seals), \
                mock.patch.object(helper.sys, "platform", "linux"), \
                mock.patch.object(helper.os, "execve", exec_boundary), \
                mock.patch.object(helper.sys, "stderr") as stderr, mock.patch.object(helper.sys, "stdout") as stdout:
            try:
                code = helper.gh([chosen or str(self.real), self.refuse, "pr", "list"], dict(self.run_env))
            except helper.Refused:
                code = "exec intercepted"
        said = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.printed = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assert_no_token(said + self.printed, "the token is never written out")
        for path, content, args, _ in ran:
            self.assertFalse(TOKEN in path or TOKEN in content or TOKEN in " ".join(args),
                             "the token is never in gh's path, file or argument list")
        return code, ran, said, looked_up

    def assert_no_token(self, text, what):
        self.assertFalse(TOKEN in text, what)

    def leaks(self, *streams):
        found = [f"stream {n}" for n, text in enumerate(streams) if TOKEN in text]
        for root in (self.root, self.system.parent):
            for path in root.rglob("*"):
                if path.is_file() and self.private not in path.parents and TOKEN.encode() in path.read_bytes():
                    found.append(path.name)
        return found

    def assert_withheld(self, code, ran, said, looked_up, reason, looked=True):
        self.assertEqual((code, ran), (128, []), "no gh runs with the token")
        self.assertEqual(said, f"openwiz: openwiz[bot] token withheld from gh ({reason}); "
                               "gh stops rather than use another account\n")
        if not looked:
            self.assertEqual(looked_up, [], "a refused gh never reaches the token lookup")

    def assert_ran_checked(self, code, ran, said, looked_up):
        self.assertEqual(code, "exec intercepted", said)
        self.assertEqual(len(ran), 1)
        path, content, args, token = ran[0]
        self.assertTrue(path.startswith("/proc/self/fd/"), "gh runs through a pinned fd")
        self.assertEqual((content, args, token), (self.checked, [str(self.real), "pr", "list"], True))
        every = 1 | 2 | 4 | 8
        self.assertEqual((self.seals or 0) & every, every, "what runs is a copy no one can change")

    def test_a_system_gh_owned_by_another_user_gets_the_token_through_its_pinned_fd(self):
        # comment-ok: catches: the owner rule refusing a gh the agent can't modify or replace, so no
        # cloud agent gets a token
        rows = self.table()
        self.assertIsNotNone(self.bind(rows), "a system gh the agent can't change is accepted")
        self.assert_ran_checked(*self.run_gh(rows))

    def test_a_system_gh_anyone_but_its_owner_could_change_or_replace_is_refused(self):
        # comment-ok: catches: the widened owner rule accepting a gh writable by a group or others, or under
        # a folder the agent owns or anyone else could write, so its entries can be replaced
        self.assertIsNotNone(self.bind(self.table()), "the baseline system gh is accepted")
        me = os.getuid()
        refused = {
            "gh writable by its group": {"gh": (OTHER, 0o775)},
            "gh writable by others": {"gh": (OTHER, 0o757)},
            "gh's folder yours, owner-only": {"folder": (me, 0o755)},
            "gh's folder yours and group-writable": {"folder": (me, 0o775)},
            "a folder above yours, owner-only": {"above": (me, 0o755)},
            "a folder above yours and writable by others": {"above": (me, 0o757)},
            "a root folder above, group-writable": {"above": (0, 0o775)},
            "a root folder above, writable by others": {"above": (0, 0o777)},
            "a sticky shared folder": {"folder": (0, 0o1777)},
            "gh's folder owned by another user": {"folder": (OTHER, 0o755)},
        }
        for case, changes in refused.items():
            with self.subTest(case):
                rows = self.table(**changes)
                self.assertIsNone(self.identity_of(rows), "the run binds no such gh")
                self.bind(self.table())
                self.assert_withheld(*self.run_gh(rows), "the gh this run chose was changed", looked=False)

    def test_a_system_gh_reached_through_a_symlink_in_your_folder_is_refused(self):
        # comment-ok: catches: the folder walk trusting a symlink in a folder the agent owns, which the agent
        # can point at another file
        chosen = str(self.mine / "gh")
        self.assertIsNotNone(self.identity_of(self.table(), chosen), "through root's folders it is accepted")
        self.assertIsNone(self.identity_of(self.table(**{"link folder": (os.getuid(), 0o755)}), chosen),
                          "the run binds no gh reached through your folder")

    def test_a_refused_gh_never_matches_a_missing_identity(self):
        # comment-ok: catches: a binding with a null or missing identity matching a gh whose own check
        # failed, so a refused gh reaches the token lookup
        rows = self.table(gh=(OTHER, 0o777))
        for case, binding in {"null": {"identity": None}, "missing": {}}.items():
            with self.subTest(case):
                self.private_dir.write(self.helper_module.gh_binding(self.name),
                                       dict({"gh": str(self.real), "refuse": self.refuse}, **binding))
                self.assert_withheld(*self.run_gh(rows), "the gh this run chose was changed", looked=False)

    def test_a_system_gh_still_gets_nothing_by_a_caller_selected_path(self):
        # comment-ok: catches: the widened owner rule letting a caller hand the token to another system-owned file
        self.assertIsNotNone(self.bind(self.table()))
        other = self.system / "gh-other"
        other.write_text("#!/bin/sh\n# synthetic other system program\nexit 0\n")
        other.chmod(0o755)
        rows = dict(self.table(), **{str(other): (OTHER, 0o755)})
        self.assert_withheld(*self.run_gh(rows, chosen=str(other)), "not the gh this run chose", looked=False)

    def test_a_system_gh_swapped_between_its_check_and_its_exec_never_gets_the_token(self):
        # comment-ok: catches: the widened owner rule bypassing R12's pinned exec, so a swapped-in file
        # gets the token
        self.assertIsNotNone(self.bind(self.table()))

        def swap():
            swapped = self.system / "gh.swap"
            swapped.write_text("#!/bin/sh\n# synthetic rogue gh\nexit 0\n")
            swapped.chmod(0o755)
            os.replace(swapped, self.real)

        self.assert_ran_checked(*self.run_gh(self.table(), during=swap))

    def test_a_system_gh_its_owner_rewrites_after_the_run_chose_it_gets_nothing(self):
        # comment-ok: catches: the fd pinning the file but not its bytes, so gh's owner rewrites it in place,
        # with the same size and time, and the rewrite gets the token
        self.assertIsNotNone(self.bind(self.table()))
        self.rewrite_in_place("#!/bin/sh\n# synthetic rewritten gh\nexit 0\n")
        self.assert_withheld(*self.run_gh(self.table()), "the gh this run chose was changed", looked=False)

    def test_a_system_gh_its_owner_rewrites_between_its_check_and_its_exec_runs_only_as_checked(self):
        # comment-ok: catches: the run executing the system gh's file itself, so its owner rewrites it in
        # place after the check and the rewrite gets the token
        self.assertIsNotNone(self.bind(self.table()))
        rewritten = []
        self.assert_ran_checked(*self.run_gh(self.table(), during=lambda: rewritten.append(
            self.rewrite_in_place("#!/bin/sh\n# synthetic rewritten gh\nexit 0\n"))))
        self.assertEqual(len(rewritten), 1)
        self.assertNotEqual(self.real.read_text(), self.checked, "the file really changed before the exec")

    def test_a_system_gh_its_owner_rewrites_while_it_is_copied_gets_nothing(self):
        # comment-ok: catches: the sealed copy trusted without its own digest check, so a rewrite between
        # the fd's check and the copy gets the token
        self.assertIsNotNone(self.bind(self.table()))
        rewrite = lambda: self.rewrite_in_place("#!/bin/sh\n# synthetic rewritten gh\nexit 0\n")
        self.assert_withheld(*self.run_gh(self.table(), before_seal=rewrite), "the gh this run chose was changed",
                             looked=False)

    def test_a_system_gh_whose_copy_is_written_before_it_is_sealed_gets_nothing(self):
        # comment-ok: catches: the digest taken from the bytes read, not from the sealed copy, so a same-user
        # process holding a writable fd to the copy rewrites it before the seals and the rewrite gets the token
        self.assertIsNotNone(self.bind(self.table()))
        rogue = "#!/bin/sh\n# synthetic rogue gh\nexit 0\n".ljust(len(self.checked), "#")[:len(self.checked)]
        written = []

        def write_copy(fd):
            with open(f"/proc/self/fd/{fd}", "r+b") as other_writer:
                other_writer.write(rogue.encode())
            written.append(os.pread(fd, len(self.checked) + 1, 0).decode())

        self.assert_withheld(*self.run_gh(self.table(), at_seal=write_copy), "the gh this run chose was changed",
                             looked=False)
        self.assertEqual(written, [rogue], "the copy really held other bytes when it was sealed")

    def test_a_system_gh_whose_copy_reports_a_missing_seal_gets_nothing(self):
        # comment-ok: catches: skipping or weakening the seal read-back so a copy reported incompletely sealed reaches the token lookup
        helper = self.helper_module
        rows = self.table()
        self.assertIsNotNone(self.bind(rows))
        real_seal, real_fcntl = helper.sealed_gh, fcntl.fcntl
        get_seals = getattr(fcntl, "F_GET_SEALS", 1034)
        seal_bits = (("seal", 1), ("shrink", 2), ("grow", 4), ("write", 8))
        all_seals = 1 | 2 | 4 | 8

        for missing, bit in (*seal_bits, ("none", 0)):
            with self.subTest(missing=missing):
                read_back = []

                def report_seals(fd, command, *args):
                    result = real_fcntl(fd, command, *args)
                    if command == get_seals:
                        read_back.append(result & all_seals)
                        return result & ~bit
                    return result

                def seal_with_report(*args):
                    with mock.patch.object(helper.fcntl, "fcntl", report_seals):
                        return real_seal(*args)

                with mock.patch.object(helper, "sealed_gh", seal_with_report):
                    outcome = self.run_gh(rows)
                if bit:
                    self.assert_withheld(*outcome, "the gh this run chose was changed", looked=False)
                else:
                    self.assert_ran_checked(*outcome)
                self.assertEqual(read_back, [all_seals], "one read-back of a fully sealed copy")

    def test_the_token_reaches_no_output_log_or_file_outside_the_private_directory(self):
        # comment-ok: catches: a leak check that can't see a seeded leak, or a token that a run writes to stdout,
        # stderr, the call log or a file outside the private directory
        for seed in (self.root / "seeded.log", self.system.parent / "seeded.txt"):
            seed.write_text(f"seeded {TOKEN}\n")
            self.assertEqual(self.leaks(), [seed.name], "the check sees a seeded file")
            seed.unlink()
        self.assertEqual(self.leaks("clean", f"seeded {TOKEN}"), ["stream 1"], "the check sees a seeded stream")
        self.assertIsNotNone(self.bind(self.table()))
        code, ran, said, looked_up = self.run_gh(self.table())
        self.assert_ran_checked(code, ran, said, looked_up)
        self.assertEqual(self.leaks(said, self.printed), [], "no output, log or outside file holds the token")

    def test_a_failed_assertion_never_prints_the_token(self):
        # comment-ok: catches: a guard assertion whose failure message quotes the text it searched, printing
        # the token into the test log
        with self.assertRaises(AssertionError) as caught:
            self.assert_no_token(f"seeded {TOKEN}", "seeded leak")
        self.assertFalse(TOKEN in str(caught.exception), "the failure names the leak, not the token")

    def test_a_sealed_gh_the_system_will_not_execute_names_the_memfd_restriction(self):
        # comment-ok: catches: a kernel or sandbox that blocks executable memfds failing as a bare "cannot run
        # gh", so nobody learns why a system gh never runs
        helper = self.helper_module
        copy = os.memfd_create("openwiz-gh", os.MFD_CLOEXEC)
        self.addCleanup(os.close, copy)
        refused = mock.Mock(side_effect=PermissionError(13, "synthetic noexec memfd"))
        with mock.patch.object(helper.sys, "platform", "linux"), mock.patch.object(helper.os, "execve", refused):
            try:
                helper.exec_gh(copy, str(self.real), [str(self.real), "pr", "list"], {})
                caught = None
            except Exception as error:
                caught = error
        self.assertIsInstance(caught, helper.Refused, "the exec refusal is the helper's own diagnostic")
        self.assertIn("executable memfds", str(caught))
        self.assertEqual(refused.call_args.args[0], f"/proc/self/fd/{copy}")

    def test_a_system_gh_moved_while_its_folders_are_checked_is_refused(self):
        # comment-ok: catches: the folder walk from an open fd vouching for another file now at the fd's path
        fd = os.open(self.real, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        moved = []

        def move(target):
            if os.fspath(target) == str(self.real) and not moved:
                moved.append(True)
                replacement = self.system / "gh.swap"
                replacement.write_text(self.checked)
                replacement.chmod(0o755)
                os.rename(self.real, self.system / "gh.old")
                os.replace(replacement, self.real)

        rows = dict(self.table(), **{str(self.system / "gh.old"): (OTHER, 0o755)})
        with self.faked(rows, before_lstat=move):
            self.assertIsNone(self.helper_module.gh_identity(fd), "an fd whose path now holds another file")
        self.assertEqual(moved, [True])

    def test_a_system_gh_is_refused_where_procfs_cannot_pin_it(self):
        # comment-ok: catches: a system gh accepted on macOS or another system, where the run executes it by
        # its path and can't seal it
        with mock.patch.object(self.helper_module.sys, "platform", "darwin"):
            self.assertIsNone(self.identity_of(self.table()), "the run binds no system gh off Linux")
        self.assertIsNotNone(self.identity_of(self.table()), "on Linux it is accepted")


class ActionsRoute(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="agent-actions-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.private = self.root / "private"
        self.private.mkdir(mode=0o700)
        self.helper = load_helper()
        self.wanted = {"requester": "builder-3235", "repositories": [REPO], "permissions": WRITE}

    def start_fake(self, mode="ok"):
        import io
        import urllib.parse
        import zipfile

        state = {"mode": mode, "dispatches": [], "deleted": [], "redirect_auth": [],
                 "artifacts": [], "logs": [], "rate_hits": 0, "poll_count": 0, "run_pages": []}
        owner_repo = "synthetic-owner/private-ops"
        other_pub = self.helper.one_time_key()[1] if mode == "unopenable" else None

        def seal_to(token, key):
            sealed = b""
            for at in range(0, len(token), 318):
                r, w = os.pipe()
                os.write(w, key.encode())
                os.close(w)
                sealed += subprocess.run(
                    ["/usr/bin/openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", f"/dev/fd/{r}",
                     "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
                     "-pkeyopt", "rsa_mgf1_md:sha256"],
                    input=token[at:at + 318].encode(), stdout=subprocess.PIPE, check=True, pass_fds=(r,)).stdout
                os.close(r)
            return base64.b64encode(sealed).decode()

        def make_zip(payload, filename="answer.json"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr(filename, payload)
            return buf.getvalue()

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send_json(self, code, body, headers=None):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode())
                if state["mode"] == "backoff" and state["rate_hits"] == 0:
                    state["rate_hits"] += 1
                    self.send_json(429, {"message": "rate limited"}, {"Retry-After": "0"})
                    return
                state["dispatches"].append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
                req = json.loads(body["inputs"]["request"])
                state["nonce"] = body["inputs"]["nonce"]
                state["logs"].append(json.dumps({"requester": req["requester"], "outcome": "minted"}))
                if state["mode"] == "tampered-zip":
                    raw = b"not-a-zip"
                elif state["mode"] == "tampered-body":
                    raw = make_zip(json.dumps({"schema": "openwiz.token-service.v1", "kind": "answer",
                                               "sealed_token": "A" * 512, "expires_at": int(time.time()) + 3600,
                                               "repositories": ["other/repo"], "permissions": WRITE}))
                elif state["mode"] == "refusal":
                    raw = make_zip(json.dumps({"schema": "openwiz.token-service.v1", "kind": "refusal",
                                               "refusal": "not-installed",
                                               "message": PIN["refusals"]["not-installed"]["message"]}))
                else:
                    key = other_pub if state["mode"] == "unopenable" else req["answer_key"]
                    raw = make_zip(json.dumps({"schema": "openwiz.token-service.v1", "kind": "answer",
                                               "sealed_token": seal_to(TOKEN, key),
                                               "expires_at": int(time.time()) + 3600,
                                               "repositories": [REPO], "permissions": WRITE}))
                state["zip"] = raw
                state["artifacts"].append(raw)
                self.send_response(204)
                self.end_headers()

            def do_GET(self):
                if state["mode"] == "backoff" and state["rate_hits"] == 1:
                    state["rate_hits"] += 1
                    self.send_json(403, {"message": "secondary rate limit"}, {"Retry-After": "0"})
                    return
                if self.path.startswith(f"/repos/{owner_repo}/actions/workflows/mint-workflow.yml/runs"):
                    if state["mode"] == "missing-run":
                        self.send_json(200, {"workflow_runs": []})
                        return
                    status = "in_progress" if state["mode"] == "timeout" else "completed"
                    conclusion = "failure" if state["mode"] == "failed-run" else ("success" if status == "completed" else None)
                    run = {
                        "id": 501, "name": "OpenWiz Token Service",
                        "display_title": f"openwiz-mint-{state['nonce']}",
                        "head_branch": "main", "event": "workflow_dispatch",
                        "status": status, "conclusion": conclusion,
                    }
                    query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    size = int(query.get("per_page", ["30"])[0])
                    page = int(query.get("page", ["1"])[0])
                    state["run_pages"].append(page)
                    runs = [run]
                    if state["mode"] == "later-page":
                        runs = [dict(run, id=i, display_title=f"synthetic-later-run-{i}")
                                for i in range(502, 512)] + runs
                    first = (page - 1) * size
                    self.send_json(200, {"total_count": len(runs), "workflow_runs": runs[first:first + size]})
                    return
                if self.path == f"/repos/{owner_repo}/actions/runs/501":
                    state["poll_count"] += 1
                    self.send_json(200, {"id": 501, "status": "in_progress", "conclusion": None})
                    return
                if self.path == f"/repos/{owner_repo}/actions/runs/501/artifacts":
                    items = [] if state["mode"] == "missing-artifact" else [
                        {"id": 701, "name": state["nonce"], "expired": False}]
                    self.send_json(200, {"artifacts": items})
                    return
                if self.path == f"/repos/{owner_repo}/actions/artifacts/701/zip":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_address[1]}/download/701")
                    self.end_headers()
                    return
                if self.path == "/download/701":
                    state["redirect_auth"].append(self.headers.get("Authorization"))
                    data = state["zip"]
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(404)
                self.end_headers()

            def do_DELETE(self):
                if self.path == f"/repos/{owner_repo}/actions/artifacts/701":
                    state["delete_attempted"] = True
                    if state["mode"] == "delete-failed":
                        self.send_error(500)
                        return
                    state["deleted"].append(701)
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(404)
                self.end_headers()

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.helper = self.helper
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        base = f"http://127.0.0.1:{server.server_address[1]}"
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "OPENWIZ_AGENT_TOKEN_DIR": str(self.private),
            "OPENWIZ_TOKEN_SERVICE_ROUTE": "actions",
            "OPENWIZ_TOKEN_SERVICE_REPOSITORY": owner_repo,
            "OPENWIZ_GITHUB_API_BASE": base,
            "GH_TOKEN": "synthetic-owner-account-token",
        }
        return env, state

    def test_actions_round_trip_and_deletes_artifact(self):
        # comment-ok: catches: matching the workflow name instead of the run title, wrong-host credentials,
        # wrong dispatch ref, auth on redirect, or an artifact left behind after download.
        env, state = self.start_fake("ok")
        gh = self.root / "gh"
        gh.write_text("#!/bin/sh\n"
                      'case "$3:$4" in\n'
                      "  --hostname:github.com) echo synthetic-owner-account-token ;;\n"
                      "  *) echo synthetic-enterprise-account-token ;;\n"
                      "esac\n")
        gh.chmod(0o700)
        env.update(PATH=f"{self.root}{os.pathsep}{env['PATH']}", GH_HOST="enterprise.example.invalid")
        env.pop("GH_TOKEN")
        private = self.helper.Private(env, create=True)
        self.addCleanup(os.close, private.fd)
        token, expires_at = self.helper.token_for(private, self.wanted, env)
        self.assertEqual(token, TOKEN)
        self.assertGreater(expires_at, int(time.time()) + 300)
        self.assertEqual(len(state["dispatches"]), 1)
        self.assertEqual(state["dispatches"][0]["body"]["ref"], "main")
        self.assertEqual(state["dispatches"][0]["auth"], "Bearer synthetic-owner-account-token")
        self.assertEqual(state["deleted"], [701], "artifact must be deleted after download")
        self.assertEqual(state["redirect_auth"], [None], "Authorization must not cross artifact redirect")

    def test_actions_finds_a_mint_after_ten_newer_runs(self):
        # comment-ok: catches: polling only the first page when a successful mint is on page two.
        env, state = self.start_fake("later-page")
        private = self.helper.Private(env, create=True)
        self.addCleanup(os.close, private.fd)
        with mock.patch.object(self.helper, "ACTIONS_TIMEOUT_S", 2), \
                mock.patch.object(self.helper, "ACTIONS_POLL_S", 0.01):
            token, _ = self.helper.token_for(private, self.wanted, env)
        self.assertEqual(token, TOKEN)
        self.assertEqual(state["run_pages"], [1, 2])
        self.assertEqual(state["deleted"], [701])

    def test_actions_falls_back_after_download_and_extraction_errors(self):
        # comment-ok: catches: protocol and decompression errors escaping the fallback and artifact cleanup.
        import http.client
        import zipfile
        import zlib

        read = http.client.HTTPResponse.read

        def interrupted(response, *args, **kwargs):
            if response.getheader("Content-Type") == "application/zip":
                raise http.client.IncompleteRead(b"", 1)
            return read(response, *args, **kwargs)

        for target, method, fault, reason in (
            (http.client.HTTPResponse, "read", {"new": interrupted}, "unreachable"),
            (zipfile.ZipExtFile, "read", {"side_effect": zlib.error("synthetic decode failure")}, "bad-answer"),
        ):
            with self.subTest(reason=reason):
                env, state = self.start_fake("ok")
                private = self.helper.Private(env, create=True)
                self.addCleanup(os.close, private.fd)
                err = []
                with mock.patch.object(target, method, **fault), \
                        mock.patch.object(self.helper.sys, "stderr", types.SimpleNamespace(write=err.append)):
                    try:
                        result = self.helper.token_for(private, self.wanted, env)
                    except (http.client.IncompleteRead, zlib.error):
                        self.fail(f"{reason} escaped the Actions fallback")
                self.assertEqual(result, (None, None))
                self.assertEqual("".join(err), NOTE.replace("<reason>", reason) + "\n")
                self.assertEqual(state["deleted"], [701])

    def test_actions_failures_fall_back_with_right_reason(self):
        # comment-ok: catches: wrong fallback or a returned token after a missing/failed run, timeout,
        # failed deletion, missing/tampered artifact, unopenable answer, or contract refusal.
        cases = [
            ("missing-run", "unreachable", []),
            ("timeout", "unreachable", []),
            ("failed-run", "unreachable", []),
            ("missing-artifact", "unreachable", []),
            ("delete-failed", "unreachable", []),
            ("tampered-zip", "bad-answer", [701]),
            ("tampered-body", "bad-answer", [701]),
            ("unopenable", "bad-answer", [701]),
            ("refusal", "not-installed", [701]),
        ]
        for mode, expected_reason, expected_deleted in cases:
            with self.subTest(mode):
                env, state = self.start_fake(mode)
                env["OPENWIZ_AGENT_TOKEN_DIR"] = str(self.private / mode)
                private = self.helper.Private(env, create=True)
                self.addCleanup(os.close, private.fd)
                err = []
                with mock.patch.object(self.helper, "ACTIONS_TIMEOUT_S",
                                       0.08 if mode in ("missing-run", "timeout") else 2), \
                        mock.patch.object(self.helper, "ACTIONS_POLL_S", 0.01), \
                        mock.patch.object(self.helper.sys, "stderr",
                                          types.SimpleNamespace(write=err.append)):
                    token, expires_at = self.helper.token_for(private, self.wanted, env)
                self.assertEqual((token, expires_at), (None, None))
                self.assertEqual("".join(err), NOTE.replace("<reason>", expected_reason) + "\n")
                self.assertEqual(state["deleted"], expected_deleted)
                if mode == "delete-failed":
                    self.assertEqual((state["redirect_auth"], state["delete_attempted"]), ([None], True))

    def test_actions_backs_off_on_403_and_429(self):
        # comment-ok: catches: failing immediately on GitHub 403/429 instead of backing off and retrying.
        env, state = self.start_fake("backoff")
        private = self.helper.Private(env, create=True)
        self.addCleanup(os.close, private.fd)
        with mock.patch.object(self.helper, "ACTIONS_POLL_S", 0.01):
            token, _ = self.helper.token_for(private, self.wanted, env)
        self.assertEqual(token, TOKEN)
        self.assertEqual(state["rate_hits"], 2)
        self.assertEqual(state["deleted"], [701])

    def test_actions_never_exposes_plaintext_token(self):
        # comment-ok: catches: plaintext token appearing in dispatch inputs, fake run logs, artifact zip, or helper output.
        env, state = self.start_fake("ok")
        done = subprocess.run([sys.executable, "-I", str(HELPER), "start", *REQ],
                              env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        for blob in (json.dumps(state["dispatches"]), "\n".join(state["logs"]),
                     done.stdout, done.stderr):
            self.assertNotIn(TOKEN, blob)
        for raw in state["artifacts"]:
            self.assertNotIn(TOKEN.encode(), raw)


if __name__ == "__main__":
    unittest.main()
