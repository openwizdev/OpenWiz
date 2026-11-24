#!/usr/bin/env python3
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WORKFLOW = ROOT / ".github/workflows/pr-opener.yml"
SCRIPT = HERE / "pr-opener.py"
EXACT_PERMS = {"pull_requests": "write", "contents": "read"}
SHA_USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")


def pinned_repo_actions(root):
    pinned = set()
    for folder in (root / ".github/workflows", root / ".github/actions"):
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.yml")):
            if path.resolve() == WORKFLOW.resolve():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                m = SHA_USES.match(line)
                if m and not m.group(1).startswith("./"):
                    pinned.add(m.group(1))
    return pinned


def check_workflow_text(text, pinned):
    errors = []
    lines = text.splitlines()
    on_block, job_blocks = [], {}
    in_on, in_jobs, cur_job = False, False, None
    for line in lines:
        if re.match(r"^on:\s*$", line):
            in_on, in_jobs, cur_job = True, False, None
            continue
        if re.match(r"^jobs:\s*$", line):
            in_on, in_jobs, cur_job = False, True, None
            continue
        if re.match(r"^[A-Za-z0-9_-]+:", line):
            in_on, in_jobs, cur_job = False, False, None
            continue
        if in_on:
            on_block.append(line)
        elif in_jobs:
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
            if m:
                cur_job = m.group(1)
                job_blocks[cur_job] = []
            elif cur_job is not None:
                job_blocks[cur_job].append(line)

    triggers = [m.group(1) for line in on_block if (m := re.match(r"^  ([a-z_]+):", line))]
    if not triggers or any(t in ("push", "pull_request", "pull_request_target") for t in triggers):
        errors.append("trigger must not be push or pull_request")
    if not any(t in ("workflow_dispatch", "workflow_run") for t in triggers):
        errors.append("trigger must be workflow_dispatch or workflow_run")

    key_jobs = [name for name, jlines in job_blocks.items() if "OPENWIZ_GITHUB_APP_KEY" in "\n".join(jlines)]
    if not key_jobs:
        errors.append("no job references OPENWIZ_GITHUB_APP_KEY")
    for name in key_jobs:
        jtext = "\n".join(job_blocks[name])
        if not re.search(r"^    environment:\s*app-pr-opener\s*$", jtext, re.M):
            errors.append(f"job {name} missing environment: app-pr-opener")
        if not re.search(r"^    if:\s*\$\{\{\s*github\.ref\s*==\s*'refs/heads/main'\s*\}\}\s*$", jtext, re.M):
            errors.append(f"job {name} missing refs/heads/main guard")
        if re.search(r"ref:\s*\$\{\{\s*inputs\.", jtext):
            errors.append(f"job {name} checks out an untrusted input ref")

    in_run, run_indent = False, 0
    for lineno, line in enumerate(lines, 1):
        if in_run:
            if line.strip() and (len(line) - len(line.lstrip(" "))) <= run_indent:
                in_run = False
            else:
                if "${{" in line:
                    errors.append(f"line {lineno}: expression inside run: block")
                continue
        m = re.match(r"^(\s*)(?:-\s+)?run:\s*(.*)$", line)
        if m:
            rest = m.group(2).strip()
            if rest in ("|", "|-", ">", ">-"):
                in_run, run_indent = True, len(m.group(1))
            elif "${{" in rest:
                errors.append(f"line {lineno}: expression inside inline run:")

    uses_found = []
    for lineno, line in enumerate(lines, 1):
        m = SHA_USES.match(line)
        if m:
            ref = m.group(1)
            uses_found.append(ref)
            if ref.startswith("./"):
                continue
            if not re.search(r"@[0-9a-f]{40}$", ref) or ref not in pinned:
                errors.append(f"line {lineno}: unpinned or unknown action {ref}")
    if not uses_found:
        errors.append("no uses: step found")
    return errors


def make_throwaway_key():
    proc = subprocess.run(["/usr/bin/openssl", "genrsa", "2048"], capture_output=True, timeout=30)
    assert proc.returncode == 0
    return proc.stdout


@contextmanager
def fake_github():
    calls = []
    state = {
        "token": "ghs_SyntheticPrOpenerToken000000000001",
        "permissions": dict(EXACT_PERMS),
        "repository_selection": "selected",
        "repositories": [{"full_name": "synthetic-owner/work"}],
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "branch_exists": True,
        "existing_prs": [],
        "create_status": 201,
        "create_body": {"number": 42, "html_url": "https://github.com/synthetic-owner/work/pull/42"},
        "hostile_error": None,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def _send(self, code, payload=None):
            data = b"" if payload is None else json.dumps(payload).encode()
            self.send_response(code)
            if payload is not None:
                self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)

        def do_GET(self):
            calls.append(("GET", self.path, dict(self.headers), None))
            if self.path == "/app":
                self._send(200, {"id": 1001, "owner": {"login": "synthetic-owner"}})
            elif self.path == "/repos/synthetic-owner/work/installation":
                self._send(200, {
                    "id": 2002,
                    "app_id": 1001,
                    "account": {"login": "synthetic-owner"},
                    "repository_selection": "selected",
                    "suspended_at": None,
                })
            elif self.path.startswith("/repos/synthetic-owner/work/git/ref/heads/"):
                if state["branch_exists"]:
                    head = self.path.split("/git/ref/heads/", 1)[1]
                    self._send(200, {"ref": f"refs/heads/{head}"})
                else:
                    self._send(404, {"message": state["hostile_error"] or "Not Found"})
            elif self.path.startswith("/repos/synthetic-owner/work/pulls?"):
                self._send(200, state["existing_prs"])
            else:
                self._send(404, {"message": "Not Found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode())
            calls.append(("POST", self.path, dict(self.headers), body))
            if self.path == "/app/installations/2002/access_tokens":
                self._send(201, {
                    "token": state["token"],
                    "expires_at": state["expires_at"],
                    "permissions": state["permissions"],
                    "repository_selection": state["repository_selection"],
                    "repositories": state["repositories"],
                })
            elif self.path == "/repos/synthetic-owner/work/pulls":
                if state["create_status"] == 201:
                    self._send(201, state["create_body"])
                else:
                    self._send(state["create_status"], {"message": state["hostile_error"] or "Validation Failed"})
            else:
                self._send(404, {"message": "Not Found"})

        def do_DELETE(self):
            calls.append(("DELETE", self.path, dict(self.headers), None))
            if self.path == "/installation/token":
                self._send(204, None)
            else:
                self._send(404, {"message": "Not Found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", calls, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class PrOpenerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pem = make_throwaway_key()
        cls.b64 = base64.b64encode(cls.pem).decode("ascii")

    def _base_env(self, overrides=None, summary_path=None):
        env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_REPOSITORY": "synthetic-owner/work",
            "OPENWIZ_PR_REF": "refs/heads/main",
            "OPENWIZ_PR_REPOSITORY": "synthetic-owner/work",
            "OPENWIZ_GITHUB_APP_ID": "1001",
            "OPENWIZ_GITHUB_APP_KEY": self.b64,
            "OPENWIZ_PR_HEAD": "room/demo-branch",
            "OPENWIZ_PR_TITLE": "#3194: synthetic PR",
            "OPENWIZ_PR_BODY": "Closes #3194\n",
            "OPENWIZ_PR_DRAFT": "false",
        }
        if summary_path is not None:
            env["GITHUB_STEP_SUMMARY"] = str(summary_path)
        if overrides:
            env.update(overrides)
        return env

    def run_opener(self, api_base, overrides=None, summary_path=None):
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--api-base", api_base],
            env=self._base_env(overrides, summary_path),
            capture_output=True, text=True, timeout=20,
        )

    def test_mint_requests_single_repo_exact_permissions_and_opens_pr(self):
        # SECURITY: catches: minting wider permissions or multiple repos, or failing to open PR and revoke token
        with tempfile.TemporaryDirectory(prefix="openwiz-pr-opener-") as tmp, fake_github() as (api, calls, state):
            summary = Path(tmp) / "summary.md"
            proc = self.run_opener(api, {"OPENWIZ_PR_DRAFT": "true"}, summary_path=summary)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            mints = [c for c in calls if c[0] == "POST" and c[1].endswith("/access_tokens")]
            self.assertEqual(len(mints), 1)
            self.assertEqual(mints[0][3], {"repositories": ["work"], "permissions": EXACT_PERMS})
            pulls = [c for c in calls if c[0] == "POST" and c[1] == "/repos/synthetic-owner/work/pulls"]
            self.assertEqual(len(pulls), 1)
            self.assertEqual(pulls[0][3], {
                "title": "#3194: synthetic PR",
                "head": "room/demo-branch",
                "base": "main",
                "body": "Closes #3194\n",
                "draft": True,
            })
            revokes = [c for c in calls if c[0] == "DELETE" and c[1] == "/installation/token"]
            self.assertEqual(len(revokes), 1)
            self.assertEqual(revokes[0][2].get("Authorization"), "Bearer " + state["token"])
            self.assertIn("#42", summary.read_text(encoding="utf-8"))

    def test_existing_pr_for_head_is_left_alone_and_token_revoked(self):
        # SECURITY: catches: opening a duplicate pull request or failing to revoke token when PR already exists
        with tempfile.TemporaryDirectory(prefix="openwiz-pr-opener-") as tmp, fake_github() as (api, calls, state):
            state["existing_prs"] = [{"number": 77, "head": {"ref": "room/demo-branch"}, "base": {"ref": "main"}}]
            summary = Path(tmp) / "summary.md"
            proc = self.run_opener(api, summary_path=summary)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual([c for c in calls if c[0] == "POST" and c[1].endswith("/pulls")], [])
            self.assertEqual(len([c for c in calls if c[0] == "DELETE" and c[1] == "/installation/token"]), 1)
            self.assertIn("#77", summary.read_text(encoding="utf-8"))

    def test_wider_grant_or_wrong_repo_stops_and_revokes(self):
        # SECURITY: catches: accepting a wider permission grant or extra repository instead of stopping and revoking
        bad_grants = [
            {"permissions": dict(EXACT_PERMS, issues="write")},
            {"permissions": dict(EXACT_PERMS, contents="write")},
            {"permissions": dict(EXACT_PERMS, metadata="read")},
            {"repositories": [{"full_name": "synthetic-owner/work"}, {"full_name": "synthetic-owner/other"}]},
            {"repository_selection": "all"},
        ]
        for patch in bad_grants:
            with fake_github() as (api, calls, state):
                state.update(patch)
                proc = self.run_opener(api)
                self.assertNotEqual(proc.returncode, 0, f"should refuse {patch}")
                self.assertEqual([c for c in calls if c[0] == "POST" and c[1].endswith("/pulls")], [])
                revokes = [c for c in calls if c[0] == "DELETE" and c[1] == "/installation/token"]
                self.assertEqual(len(revokes), 1, f"must revoke on {patch}")

    def test_token_revoked_on_missing_branch_and_pr_failure(self):
        # SECURITY: catches: leaving a live installation token unrevoked when branch lookup or PR creation fails
        for patch in ({"branch_exists": False}, {"create_status": 422}):
            with fake_github() as (api, calls, state):
                state.update(patch)
                proc = self.run_opener(api)
                self.assertNotEqual(proc.returncode, 0)
                revokes = [c for c in calls if c[0] == "DELETE" and c[1] == "/installation/token"]
                self.assertEqual(len(revokes), 1)
                self.assertEqual(revokes[0][2].get("Authorization"), "Bearer " + state["token"])

    def test_no_token_or_key_in_output_args_or_files(self):
        # SECURITY: catches: leaking the App key, JWT, or installation token to stdout, stderr, files, or PATH openssl
        with tempfile.TemporaryDirectory(prefix="openwiz-pr-opener-") as tmp, fake_github() as (api, calls, state):
            fake_bin = Path(tmp) / "bin"
            fake_bin.mkdir()
            spy_log = Path(tmp) / "openssl.log"
            spy = fake_bin / "openssl"
            spy.write_text(f"#!/bin/sh\necho \"$@\" >> {spy_log}\nexit 99\n", encoding="utf-8")
            spy.chmod(0o755)
            summary = Path(tmp) / "summary.md"
            path_env = f"{fake_bin}:{os.environ.get('PATH', os.defpath)}"
            state["hostile_error"] = "HOSTILE_SENTINEL_999"
            for create_status in (201, 422):
                state["create_status"] = create_status
                proc = self.run_opener(api, {"PATH": path_env}, summary_path=summary)
                combined = proc.stdout + "\n" + proc.stderr + "\n" + (summary.read_text(encoding="utf-8") if summary.exists() else "")
                for secret in (state["token"], self.b64, self.pem.decode("ascii"), "BEGIN RSA PRIVATE KEY", "BEGIN PRIVATE KEY", "HOSTILE_SENTINEL_999"):
                    self.assertNotIn(secret, combined)
                self.assertFalse(spy_log.exists(), "must use /usr/bin/openssl, never PATH openssl")
            files = sorted(p.name for p in Path(tmp).iterdir())
            self.assertEqual(files, ["bin", "summary.md"])

    def test_ref_and_input_guards_fail_closed_before_network(self):
        # SECURITY: catches: running on a non-main ref or accepting an invalid head, title, or draft
        bad_cases = [
            {"GITHUB_REF": "refs/heads/room/evil", "OPENWIZ_PR_REF": "refs/heads/room/evil"},
            {"OPENWIZ_PR_REF": "refs/heads/room/evil"},
            {"OPENWIZ_PR_HEAD": "main"},
            {"OPENWIZ_PR_HEAD": "room/"},
            {"OPENWIZ_PR_HEAD": "room/../main"},
            {"OPENWIZ_PR_HEAD": "room/a..b"},
            {"OPENWIZ_PR_HEAD": "room/bad.lock"},
            {"OPENWIZ_PR_HEAD": "room/has space"},
            {"OPENWIZ_PR_TITLE": "   "},
            {"OPENWIZ_PR_TITLE": "line1\nline2"},
            {"OPENWIZ_PR_DRAFT": "yes"},
        ]
        for overrides in bad_cases:
            with fake_github() as (api, calls, _state):
                proc = self.run_opener(api, overrides)
                self.assertEqual(proc.returncode, 1, f"should refuse {overrides}")
                self.assertIn("PR opener refused", proc.stderr)
                self.assertEqual(calls, [], f"must not call network for {overrides}")

    def test_no_secret_in_subprocess_args_or_env(self):
        # SECURITY: catches: passing the App key or installation token in a child process argument or environment
        import importlib.util
        spec = importlib.util.spec_from_file_location("pr_opener_under_test", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        real_run = subprocess.run
        seen = []

        def spy_run(cmd, *args, **kwargs):
            seen.append((list(cmd), dict(kwargs.get("env") or {})))
            return real_run(cmd, *args, **kwargs)

        with fake_github() as (api, _calls, state), \
                unittest.mock.patch("subprocess.run", side_effect=spy_run), \
                unittest.mock.patch.dict(os.environ, self._base_env({"OPENWIZ_PR_BODY": ""}), clear=True):
            mod.main(["--api-base", api])
        self.assertEqual(len(seen), 1)
        cmd, child_env = seen[0]
        self.assertEqual(cmd[0], "/usr/bin/openssl")
        self.assertEqual(child_env, {})
        self.assertTrue(any(arg.startswith("/dev/fd/") for arg in cmd))
        joined = " ".join(cmd)
        for secret in (state["token"], self.b64, self.pem.decode("ascii"), "BEGIN "):
            self.assertNotIn(secret, joined)

    def test_workflow_guard_passes_and_catches_planted_breaks(self):
        # SECURITY: catches: workflow regressions in trigger, environment, main-ref guard, run: interpolation, or unpinned uses:
        pinned = pinned_repo_actions(ROOT)
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertEqual(check_workflow_text(text, pinned), [])
        breaks = [
            text.replace("workflow_dispatch:", "push:\n  workflow_dispatch:"),
            text.replace("workflow_dispatch:", "pull_request:\n  workflow_dispatch:"),
            text.replace("environment: app-pr-opener", "environment: other"),
            text.replace("if: ${{ github.ref == 'refs/heads/main' }}", "if: ${{ true }}"),
            text.replace("python3 -I tools/github-app/pr-opener.py", "echo ${{ inputs.title }}"),
            re.sub(r"actions/checkout@[0-9a-f]{40}", "actions/checkout@v7", text),
            re.sub(r"actions/checkout@[0-9a-f]{40}", "actions/checkout@" + "0" * 40, text),
        ]
        for idx, broken in enumerate(breaks):
            self.assertNotEqual(check_workflow_text(broken, pinned), [], f"planted break #{idx} must be caught")


if __name__ == "__main__":
    unittest.main(verbosity=2)
