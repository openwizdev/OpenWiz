#!/usr/bin/env python3
import base64
import fcntl
import hashlib
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
TOKEN, TOKEN2 = "synthetic-agent-token-1", "synthetic-agent-token-2"
REQ = ("--requester", "builder-1", "--repository", REPO)
NOTE = PIN["fallback"]["note"]
WITHHELD = "openwiz: openwiz[bot] token withheld from git"
URL = f"https://github.com/{REPO}"

FAKE = r'''
import hashlib, json, os, stat, sys, time
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
sys.stdout.write(answer.get("stdout", ""))
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
    body = {"schema": "openwiz.token-service.v1", "kind": "answer", "token": token,
            "expires_at": int(time.time()) + left, "repositories": list(repositories),
            "permissions": permissions or WRITE}
    return {"exit": 0, "stdout": json.dumps(body) + "\n"}


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
            private = path.parent == self.private and path.name.startswith("token-")
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
        twice = {"exit": 0, "stdout": answer()["stdout"].replace('"kind"', '"token": "x", "kind"')}
        bad_exit = dict(refusal("permission"), exit=0)
        injected = answer(token="synthetic\nusername=x")
        failed_answer = dict(answer(), exit=5)
        for reason, item in [*cases.items(), ("bad-answer", wider), ("bad-answer", short),
                             ("bad-answer", long), ("bad-answer", twice), ("bad-answer", bad_exit),
                             ("bad-answer", injected), ("bad-answer", failed_answer)]:
            with self.subTest(reason=reason, item=item["stdout"][:60]):
                self.log.unlink(missing_ok=True)
                self.answers(item)
                result = self.start()
                self.assertEqual(result.returncode, 0)
                self.assert_fallback(result, reason)
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


if __name__ == "__main__":
    unittest.main()
