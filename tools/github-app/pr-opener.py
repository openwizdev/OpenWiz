#!/usr/bin/env python3
import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

PR_PERMISSIONS = {"pull_requests": "write", "contents": "read", "metadata": "read"}
TOKEN_RE = re.compile(r"[A-Za-z0-9._~+/-]{1,16384}=*")
SEGMENT_RE = re.compile(r"[A-Za-z0-9._-]+")
MAX_BODY = 65536
MAX_TITLE = 256
MAX_RESPONSE = 1024 * 1024
REFUSED = "PR opener refused: check ref, inputs, App credentials and GitHub availability."


def validate_head(head):
    app.require(isinstance(head, str) and head.startswith("room/") and 5 < len(head) <= 255)
    app.require(head.isascii() and ".." not in head and not head.endswith(".lock"))
    parts = head.split("/")
    app.require(parts[0] == "room" and len(parts) >= 2)
    for part in parts[1:]:
        app.require(SEGMENT_RE.fullmatch(part) is not None)
        app.require(part not in (".", "..") and not part.startswith(".") and not part.endswith(".")
                    and not part.endswith(".lock"))
    return head


def validate_title(title):
    app.require(isinstance(title, str) and 0 < len(title.strip()) <= MAX_TITLE)
    app.require("\n" not in title and "\r" not in title and "\x00" not in title)
    return title


def validate_body(body):
    app.require(isinstance(body, str) and len(body) <= MAX_BODY and "\x00" not in body)
    return body


def validate_draft(raw):
    if raw in ("", "false"):
        return False
    if raw == "true":
        return True
    raise ValueError("invalid draft flag")


def decode_pem(secret_b64):
    cleaned = secret_b64.rstrip("\r\n")
    app.require(0 < len(cleaned) <= 24576 and cleaned.isascii())
    key_pem = base64.b64decode(cleaned.encode("ascii"), validate=True)
    app.require(0 < len(key_pem) <= 16384 and key_pem.startswith(b"-----BEGIN ") and b"PRIVATE KEY-----" in key_pem)
    return key_pem


def request_json(base, method, path, token, body=None, expect_status=200):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "OpenWiz-PR-opener",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + token,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(app.api_base(base) + path, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(app.NoRedirect(), urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=15) as resp:
        app.require(resp.status == expect_status)
        raw = resp.read(MAX_RESPONSE + 1)
        app.require(len(raw) <= MAX_RESPONSE)
        return json.loads(raw.decode("utf-8"), object_pairs_hook=app.object_once)


def revoke_token(base, token):
    if not isinstance(token, str) or TOKEN_RE.fullmatch(token) is None:
        return
    req = urllib.request.Request(
        app.api_base(base) + "/installation/token",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OpenWiz-PR-opener",
            "X-GitHub-Api-Version": "2022-11-28",
            "Authorization": "Bearer " + token,
        },
        method="DELETE",
    )
    opener = urllib.request.build_opener(app.NoRedirect(), urllib.request.ProxyHandler({}))
    try:
        opener.open(req, timeout=15).close()
    except Exception:
        pass


def write_summary(line):
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if not summary:
        return
    with open(summary, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def main(argv=None):
    secret_b64 = os.environ.pop("OPENWIZ_GITHUB_APP_KEY", "")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        os.environ.pop(name, None)

    parser = argparse.ArgumentParser(description="Open one pull request as the OpenWiz GitHub App.")
    parser.add_argument("--api-base", default="https://api.github.com")
    args = parser.parse_args(argv)
    base = app.api_base(args.api_base)

    ref = os.environ.get("GITHUB_REF", "")
    pr_ref = os.environ.get("OPENWIZ_PR_REF", ref)
    app.require(ref == "refs/heads/main" and pr_ref == "refs/heads/main")

    repo_raw = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("OPENWIZ_PR_REPOSITORY") or ""
    repo_alt = os.environ.get("OPENWIZ_PR_REPOSITORY") or repo_raw
    repo = app.repository(repo_raw)
    app.require(app.repository(repo_alt).lower() == repo.lower())
    owner, repo_name = repo.split("/", 1)

    head = validate_head(os.environ.get("OPENWIZ_PR_HEAD", ""))
    title = validate_title(os.environ.get("OPENWIZ_PR_TITLE", ""))
    body = validate_body(os.environ.get("OPENWIZ_PR_BODY", ""))
    draft = validate_draft(os.environ.get("OPENWIZ_PR_DRAFT", ""))
    app_id = int(app.positive_id(os.environ.get("OPENWIZ_GITHUB_APP_ID", "")))
    key_pem = decode_pem(secret_b64)

    app_jwt = app.jwt_from_pem(key_pem, app_id)
    found = request_json(base, "GET", "/app", app_jwt, expect_status=200)
    app.require(isinstance(found, dict) and found.get("id") == app_id)

    inst_path = f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo_name, safe='')}/installation"
    inst = request_json(base, "GET", inst_path, app_jwt, expect_status=200)
    app.require(
        isinstance(inst, dict)
        and inst.get("app_id") == app_id
        and inst.get("repository_selection") == "selected"
        and inst.get("suspended_at") is None
        and type(inst.get("id")) is int and inst["id"] > 0
        and (inst.get("account") or {}).get("login", "").lower() == owner.lower()
    )

    minted = request_json(
        base,
        "POST",
        f"/app/installations/{inst['id']}/access_tokens",
        app_jwt,
        body={"repositories": [repo_name], "permissions": PR_PERMISSIONS},
        expect_status=201,
    )
    app.require(isinstance(minted, dict))
    token = minted.get("token")
    try:
        app.require(isinstance(token, str) and TOKEN_RE.fullmatch(token) is not None)
        app.require(minted.get("permissions") == PR_PERMISSIONS)
        app.require(minted.get("repository_selection") == "selected")
        listed = minted.get("repositories")
        app.require(
            isinstance(listed, list)
            and len(listed) == 1
            and isinstance(listed[0], dict)
            and isinstance(listed[0].get("full_name"), str)
            and listed[0]["full_name"].lower() == repo.lower()
        )
        expiry = datetime.fromisoformat(minted["expires_at"].replace("Z", "+00:00"))
        remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
        app.require(0 < remaining <= 3900)

        ref_path = (
            f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo_name, safe='')}"
            f"/git/ref/heads/{urllib.parse.quote(head, safe='/')}"
        )
        ref_obj = request_json(base, "GET", ref_path, token, expect_status=200)
        app.require(isinstance(ref_obj, dict) and ref_obj.get("ref") == f"refs/heads/{head}")

        query = urllib.parse.urlencode({"state": "open", "head": f"{owner}:{head}", "base": "main"})
        pulls_path = f"/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo_name, safe='')}/pulls"
        existing = request_json(base, "GET", f"{pulls_path}?{query}", token, expect_status=200)
        app.require(isinstance(existing, list))
        match = next(
            (
                pr for pr in existing
                if isinstance(pr, dict)
                and (pr.get("head") or {}).get("ref") == head
                and (pr.get("base") or {}).get("ref") == "main"
                and type(pr.get("number")) is int and pr["number"] > 0
            ),
            None,
        )
        if match is not None:
            line = f"Pull request #{match['number']} already exists."
        else:
            created = request_json(
                base,
                "POST",
                pulls_path,
                token,
                body={"title": title, "head": head, "base": "main", "body": body, "draft": draft},
                expect_status=201,
            )
            app.require(isinstance(created, dict) and type(created.get("number")) is int and created["number"] > 0)
            line = f"Pull request #{created['number']} created."
        print(line)
        write_summary(line)
    finally:
        revoke_token(base, token)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print(REFUSED, file=sys.stderr)
        sys.exit(1)
