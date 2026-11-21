#!/usr/bin/env python3
import base64
import hashlib
import importlib.util
import json
import os
import shutil
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections.abc import Mapping
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


class NameOnly(Mapping):
    def __init__(self, values):
        self.values, self.read = values, []

    def __getitem__(self, key):
        self.read.append(key)
        return self.values[key]

    def __contains__(self, key):
        return key in self.values

    def __iter__(self):
        return iter(self.values)

    def __len__(self):
        return len(self.values)


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
        environment = NameOnly(dict(self.env, OPENWIZ_GITHUB_APP_KEY="synthetic-legacy-key-sentinel"))
        for command in (["start", *REQ], ["run", *REQ, "--", "gh", "pr", "list"]):
            with self.subTest(command[0]), mock.patch.object(helper.os, "environ", environment):
                self.assertEqual(helper.main(command), 2)
        self.assertNotIn("OPENWIZ_GITHUB_APP_KEY", environment.read, "the legacy value is never fetched")
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


if __name__ == "__main__":
    unittest.main()
