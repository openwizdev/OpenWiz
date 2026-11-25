#!/usr/bin/env python3
"""Offline security and execution proofs for tools/github-app/mint-workflow.yml (#3235)."""
import base64
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TEMPLATE = HERE / "mint-workflow.yml"
WORKFLOWS = ROOT / ".github" / "workflows"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
EXPR_RE = re.compile(r"\$\{\{.*?\}\}")


def pinned_openwiz_actions():
    """Return {action_name: set(shas)} already pinned across OpenWiz's own workflows."""
    pinned = {}
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for line in path.read_text().splitlines():
            m = USES_RE.match(line)
            if not m or "@" not in m.group(1):
                continue
            action, ref = m.group(1).split("@", 1)
            if SHA40.fullmatch(ref):
                pinned.setdefault(action, set()).add(ref)
    return pinned


def extract_run_blocks(text):
    """Extract every `run:` command (inline or block scalar) from a workflow YAML."""
    lines = text.splitlines()
    blocks, i = [], 0
    while i < len(lines):
        m = re.match(r"^(\s*)(?:-\s*)?run:\s*(.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        rest = m.group(2).strip()
        if rest in ("|", "|-", "|+", ">", ">-", ">+"):
            body, i = [], i + 1
            while i < len(lines):
                line = lines[i]
                if line.strip() and (len(line) - len(line.lstrip(" "))) <= indent:
                    break
                body.append(line)
                i += 1
            non_empty = [len(l) - len(l.lstrip(" ")) for l in body if l.strip()]
            cut = min(non_empty) if non_empty else 0
            blocks.append("\n".join(l[cut:] if len(l) >= cut else "" for l in body))
        else:
            blocks.append(rest)
            i += 1
    return blocks


def check_template(text, allowed_actions):
    """Return a list of security violations in a mint-workflow.yml text."""
    errors = []
    lines = text.splitlines()
    # 1. Top-level `on:` must contain only `workflow_dispatch`.
    on_idx = next((i for i, l in enumerate(lines) if re.match(r"^on:\s*$", l)), None)
    if on_idx is None:
        errors.append("missing top-level on: block")
    else:
        triggers = []
        for l in lines[on_idx + 1:]:
            if l.strip() and not l.startswith(" "):
                break
            m = re.match(r"^  ([A-Za-z0-9_-]+):\s*", l)
            if m:
                triggers.append(m.group(1))
        if triggers != ["workflow_dispatch"]:
            errors.append(f"triggers must be workflow_dispatch only, got {triggers!r}")
    # 2. Key job must name environment: token-service and guard github.ref == 'refs/heads/main'.
    if not re.search(r"(?m)^\s{4}environment:\s*token-service\s*$", text):
        errors.append("missing job environment: token-service")
    if not re.search(r"(?m)^\s{4}if:\s*(?:\$\{\{\s*)?github\.ref\s*==\s*'refs/heads/main'(?:\s*\}\})?\s*$", text):
        errors.append("missing job-level refs/heads/main guard")
    # 3. OpenWiz checkout must pin a 40-hex commit SHA (never a branch).
    checkout_ok = False
    for i, l in enumerate(lines):
        if re.match(r"^\s+repository:\s*openwizdev/OpenWiz\s*$", l):
            indent = len(l) - len(l.lstrip(" "))
            for nxt in lines[i + 1:]:
                if nxt.strip() and (len(nxt) - len(nxt.lstrip(" "))) < indent:
                    break
                m = re.match(r"^\s+ref:\s*([A-Za-z0-9._/-]+)\s*(?:#.*)?$", nxt)
                if m and SHA40.fullmatch(m.group(1)):
                    checkout_ok = True
                    break
    if not checkout_ok:
        errors.append("openwizdev/OpenWiz checkout must pin a 40-hex commit sha")
    # 4. Every `uses:` must be actions/checkout or actions/upload-artifact at an OpenWiz-pinned SHA.
    allowed_names = {"actions/checkout", "actions/upload-artifact"}
    uses_found = []
    for l in lines:
        m = USES_RE.match(l)
        if not m:
            continue
        spec = m.group(1)
        uses_found.append(spec)
        if "@" not in spec:
            errors.append(f"unpinned uses: {spec}")
            continue
        action, ref = spec.split("@", 1)
        if action not in allowed_names:
            errors.append(f"disallowed action: {action}")
        elif not SHA40.fullmatch(ref) or ref not in allowed_actions.get(action, set()):
            errors.append(f"action sha not pinned in OpenWiz workflows: {spec}")
    if not uses_found:
        errors.append("no uses: steps found")
    # 5. No `${{ }}` expression (especially inputs) inside any `run:` block.
    run_blocks = extract_run_blocks(text)
    if not run_blocks:
        errors.append("no run: block found")
    for block in run_blocks:
        if EXPR_RE.search(block):
            errors.append("expression ${{ }} found inside a run: block")
    # 6. Artifact upload retention-days: 1.
    if not re.search(r"(?m)^\s+retention-days:\s*1\s*$", text):
        errors.append("missing artifact retention-days: 1")
    return errors


class MintWorkflowTemplate(unittest.TestCase):
    def test_template_passes_all_security_guards(self):
        # catches: missing workflow template, non-dispatch trigger, missing token-service env,
        # unpinned OpenWiz checkout, ${{ inputs }} in run:, or unpinned/foreign action uses.
        self.assertTrue(TEMPLATE.is_file(), "tools/github-app/mint-workflow.yml is missing")
        errors = check_template(TEMPLATE.read_text(), pinned_openwiz_actions())
        self.assertEqual(errors, [], f"template failed guards: {errors}")

    def test_template_guard_catches_every_planted_violation(self):
        # catches: a template guard that passes even when a security invariant is broken.
        self.assertTrue(TEMPLATE.is_file(), "tools/github-app/mint-workflow.yml is missing")
        good = TEMPLATE.read_text()
        allowed = pinned_openwiz_actions()
        mutations = {
            "branch trigger": good.replace("  workflow_dispatch:", "  push:\n    branches: [main]\n  workflow_dispatch:", 1),
            "wrong env": good.replace("    environment: token-service", "    environment: other", 1),
            "no main guard": re.sub(r"(?m)^\s{4}if:.*refs/heads/main.*$", "", good),
            "branch checkout": re.sub(r"(?m)^(\s+ref:\s*)[0-9a-f]{40}", r"\1main", good),
            "input in run": good + "\n      - run: echo ${{ inputs.request }}\n",
            "foreign action": good + "\n      - uses: actions/setup-python@0000000000000000000000000000000000000000\n",
            "unpinned action": re.sub(r"actions/checkout@[0-9a-f]{40}", "actions/checkout@v7", good),
        }
        for name, bad in mutations.items():
            with self.subTest(name):
                self.assertNotEqual(check_template(bad, allowed), [], f"guard missed {name}")


class MintWorkflowExecution(unittest.TestCase):
    def test_workflow_run_seals_token_via_pipe_and_logs_only_mint_fields(self):
        # catches: a workflow script that writes the App key to disk, leaks the plaintext token
        # to stdout/stderr/summary/artifact, accepts non-main refs, or fails to seal per #3085.
        self.assertTrue(TEMPLATE.is_file(), "tools/github-app/mint-workflow.yml is missing")
        spec = importlib.util.spec_from_file_location("test_token_service", HERE / "test_token_service.py")
        ts = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ts)
        helper_spec = importlib.util.spec_from_file_location("agent_token", HERE / "agent-token.py")
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)

        blocks = extract_run_blocks(TEMPLATE.read_text())
        self.assertTrue(blocks, "no run: block in template")
        script = max(blocks, key=len)
        private_key, answer_key = helper.one_time_key()
        self.assertIsNotNone(private_key)
        app_pem = ts.throwaway_key()
        request = {
            "schema": "openwiz.token-service.v1",
            "kind": "request",
            "requester": "builder-3235",
            "answer_key": answer_key,
            "repositories": ["synthetic-owner/work"],
            "permissions": {"metadata": "read", "contents": "write", "issues": "write",
                            "pull_requests": "write", "checks": "read", "actions": "read"},
        }
        with tempfile.TemporaryDirectory(prefix="mint-wf-") as tmp:
            work = Path(tmp)
            os.symlink(ROOT, work / "openwiz")
            summary = work / "summary.md"
            summary.write_text("")
            with ts.fake_github(app_pem, ["synthetic-owner/work"]) as (url, calls, _fake):
                base_env = {
                    "PATH": os.environ.get("PATH", os.defpath),
                    "GITHUB_REF": "refs/heads/feature",
                    "GITHUB_STEP_SUMMARY": str(summary),
                    "OPENWIZ_REQUEST": json.dumps(request),
                    "OPENWIZ_NONCE": "a" * 32,
                    "OPENWIZ_GITHUB_APP_KEY": base64.b64encode(app_pem).decode("ascii"),
                    "OPENWIZ_GITHUB_APP_ID": "1001",
                    "OPENWIZ_GITHUB_APP_MODE": "user",
                    "OPENWIZ_GITHUB_API_BASE": url,
                }
                # Non-main ref must be refused before any GitHub call.
                bad = subprocess.run(["sh", "-eu", "-c", script], cwd=work, env=base_env,
                                     capture_output=True, text=True, timeout=30)
                self.assertNotEqual(bad.returncode, 0, "non-main ref must fail")
                self.assertEqual(calls, [], "non-main ref must make no GitHub call")
                self.assertFalse((work / "out" / "answer.json").exists())

                # Main ref mints and seals, writes only mint-log fields to summary, never writes key.
                good = subprocess.run(["sh", "-eu", "-c", script], cwd=work,
                                      env=dict(base_env, GITHUB_REF="refs/heads/main"),
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(good.returncode, 0, good.stderr)
                answer_path = work / "out" / "answer.json"
                self.assertTrue(answer_path.is_file(), "missing out/answer.json")
                self.assertEqual(sorted(p.name for p in (work / "out").iterdir()), ["answer.json"])
                answer_text = answer_path.read_text()
                answer = json.loads(answer_text)
                self.assertEqual(answer["kind"], "answer")
                self.assertNotIn("token", answer)
                token = helper.opened(answer["sealed_token"], private_key)
                self.assertIsNotNone(token)
                summary_text = summary.read_text()
                for blob in (good.stdout, good.stderr, summary_text, answer_text):
                    self.assertNotIn(token, blob)
                    self.assertNotIn("PRIVATE KEY", blob)
                # Summary carries mint-log fields only.
                self.assertIn("builder-3235", summary_text)
                self.assertIn("minted", summary_text)
                self.assertNotIn("sealed_token", summary_text)
                self.assertEqual(list(work.rglob("private-key.pem")), [])


if __name__ == "__main__":
    unittest.main()
