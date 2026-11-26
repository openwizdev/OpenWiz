#!/usr/bin/env python3
USAGE = """The token service (GA2, #1841): mint one-hour openwiz[bot] installation tokens
on the owner's machine, under contracts/token-service.v1.md.

  token-service.py start   let agents mint (a fresh install is stopped); the App
                           setting (OPENWIZ_GITHUB_APP_MODE) given here holds
                           for every mint until the next start
  token-service.py stop    refuse every mint, like an unreachable service
  token-service.py mint    read one request on stdin, write one answer or
                           refusal as one JSON line on stdout

It listens on no port: agents run `mint` through the owner's machine pairing or
locally. Every answer holds its token only sealed (RSA-OAEP) to the request's one-time
answer_key. Only this tool reads the App's key, <state>/service/app/private-key.pem,
and only to sign the App's JWT; the key and every token stay off the command
line, standard error and the mint log. The mint log is
<state>/service/token-service/mint-log.jsonl, owner-only, one line per request
and never a token. mint-token.py stays byte-identical to the copy WizSkills'
launch-fleet carries: this tool uses the same guards from app.py.
"""
import base64
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app  # noqa: E402 -- the documented `python3 -I` drops this folder from sys.path

SCHEMA = "openwiz.token-service.v1"
REFUSALS = {
    "usage": (2, "the request is not one valid token-service request."),
    "one-owner": (2, "the repositories must share one owner."),
    "not-installed": (3, "a repository is not in the App's installation."),
    "permission": (5, "a permission is outside the App's."),
    "github": (5, "GitHub refused the exchange or granted a different scope."),
    "expiry": (5, "the minted token failed the expiry guards."),
    "unavailable": (1, "the service cannot read its App state or reach GitHub."),
}
LEVEL = {"read": 0, "write": 1}
REQUESTER = re.compile(r"[a-z][a-z0-9-]{0,63}")
PERMISSION = re.compile(r"[a-z][a-z_]*")
TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
ANSWER_KEY = re.compile(r"-{5}BEGIN PUBLIC KEY-{5}\nMIIBojANBgkqhkiG9w0BAQEFAAOCAY8AMIIBigKCAYEA"
                        r"[g-z0-9+/][A-Za-z0-9+/]{19}\n(?:[A-Za-z0-9+/]{64}\n){7}"
                        r"[A-Za-z0-9+/]{43}[BDFHJLNPRTVXZbdfhjlnprtvxz13579/]AgMBAAE=\n-{5}END PUBLIC KEY-{5}\n")
OAEP = ("-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256", "-pkeyopt", "rsa_mgf1_md:sha256")
BLOCK_HOLDS, BLOCK, MOST_BLOCKS = 318, 384, 8
REFRESH, LONGEST, HANDOVER = 300, 3900, 10
REQUEST_LIMIT = 64 * 1024
FOLDER, STARTED, LOG = "token-service", "started", "mint-log.jsonl"
STOPPED = "Token service stopped: the owner has not started it."


class Refused(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def check(condition, code):
    if not condition:
        raise Refused(code)


def request_of(data):
    try:
        check(len(data) <= REQUEST_LIMIT, "usage")
        value = app.parse_json(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise Refused("usage") from None
    check(set(value) == {"schema", "kind", "requester", "answer_key", "repositories", "permissions"}, "usage")
    check(value["schema"] == SCHEMA and value["kind"] == "request", "usage")
    requester, repositories, permissions = value["requester"], value["repositories"], value["permissions"]
    check(isinstance(requester, str) and REQUESTER.fullmatch(requester) is not None, "usage")
    check(isinstance(value["answer_key"], str) and ANSWER_KEY.fullmatch(value["answer_key"]) is not None, "usage")
    check(isinstance(repositories, list) and repositories, "usage")
    for name in repositories:
        check(isinstance(name, str) and app.REPOSITORY.fullmatch(name) is not None
              and name.split("/")[1] not in (".", ".."), "usage")
    check(len({name.lower() for name in repositories}) == len(repositories), "usage")
    check(isinstance(permissions, dict) and permissions, "usage")
    for name, level in permissions.items():
        check(PERMISSION.fullmatch(name) is not None and isinstance(level, str) and level in LEVEL, "usage")
    return value


def folder(state, create=False):
    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        app.checked(fd, directory=True)
        for component in ("service", FOLDER):
            if create:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            app.checked(fd, directory=True)
        return fd
    except Exception:
        os.close(fd)
        raise


def started(directory):
    try:
        value = app.parse_json(app.read_file(directory, STARTED, 64))
    except (OSError, ValueError):
        return None
    mode = value.get("mode")
    return mode if set(value) == {"mode"} and mode in ("user", "factory") else None


def seal(token, answer_key):
    data, sealed = token.encode("ascii"), b""
    app.require(0 < len(data) <= MOST_BLOCKS * BLOCK_HOLDS)
    for at in range(0, len(data), BLOCK_HOLDS):
        reader, writer = os.pipe()
        try:
            with os.fdopen(writer, "wb") as pipe:
                pipe.write(answer_key.encode("ascii"))
            block = app.openssl(["pkeyutl", "-encrypt", "-pubin", "-inkey", f"/dev/fd/{reader}", *OAEP],
                                data[at:at + BLOCK_HOLDS], pass_fds=(reader,))
        finally:
            os.close(reader)
        app.require(len(block) == BLOCK)
        sealed += block
    return base64.b64encode(sealed).decode("ascii")


def mint(api, request, setting):
    repositories, permissions = request["repositories"], request["permissions"]
    owners = {name.split("/")[0].lower() for name in repositories}
    check(len(owners) == 1, "one-owner")
    try:
        directory = app.app_directory(app.state_path(api["state"]))
        try:
            config = app.parse_json(app.read_file(directory, "app.json", 1024))
            app.require(set(config) == {"app_id"})
            jwt = app.jwt(directory, config["app_id"])
        finally:
            os.close(directory)
    except Exception:
        raise Refused("unavailable") from None
    try:
        status, found = app.get(api["base"], "/app", jwt)
        check(status == 200 and found.get("id") == config["app_id"], "github")
        held = set()
        for name in repositories:
            path = "/repos/" + urllib.parse.quote(name, safe="/") + "/installation"
            status, installation = app.get(api["base"], path, jwt)
            check(status in (200, 404), "github")
            check(status == 200 and installation.get("app_id") == config["app_id"]
                  and installation.get("repository_selection") == "selected"
                  and type(installation.get("id")) is int and installation["id"] > 0, "not-installed")
            check(app.bound(setting, (found.get("owner") or {}).get("login"),
                            (installation.get("account") or {}).get("login"), [name]), "not-installed")
            held.add(installation["id"])
        check(len(held) == 1, "not-installed")
        for name, level in permissions.items():
            check(name in app.SERVICE and LEVEL[level] <= LEVEL[app.SERVICE[name]], "permission")
        result = app.post(api["base"], f"/app/installations/{held.pop()}/access_tokens",
                          {"repositories": [name.split("/")[1] for name in repositories],
                           "permissions": permissions}, jwt)
    except Refused:
        raise
    except urllib.error.HTTPError:
        raise Refused("github") from None
    except OSError:
        raise Refused("unavailable") from None
    except Exception:
        raise Refused("github") from None
    token, listed = result.get("token"), result.get("repositories")
    try:
        check(result.get("permissions") == permissions and result.get("repository_selection") == "selected", "github")
        check(isinstance(listed, list) and all(isinstance(r, dict) and isinstance(r.get("full_name"), str)
                                               for r in listed), "github")
        check(sorted(r["full_name"].lower() for r in listed) == sorted(n.lower() for n in repositories), "github")
        check(isinstance(token, str) and TOKEN.fullmatch(token) is not None, "github")
        try:
            expires_at = int(datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00")).timestamp())
        except Exception:
            raise Refused("github") from None
        try:
            sealed = seal(token, request["answer_key"])
        except Exception:
            raise Refused("unavailable") from None
        check(fresh(expires_at), "expiry")
    except Refused:
        app.revoke(api["base"], token)
        raise
    return sealed, expires_at, token


def fresh(expires_at):
    return REFRESH + HANDOVER < expires_at - time.time() <= LONGEST


def serve(api, log, data, setting):
    now = time.time()
    line = {"schema": SCHEMA, "kind": "mint-log", "at": int(now), "requester": "-"}
    token = None
    try:
        request = request_of(data)
        line.update(requester=request["requester"], repositories=request["repositories"])
        sealed, expires_at, token = mint(api, request, setting)
        line.update(permissions=request["permissions"], outcome="minted", expires_at=expires_at)
        message = {"schema": SCHEMA, "kind": "answer", "sealed_token": sealed, "expires_at": expires_at,
                   "repositories": request["repositories"], "permissions": request["permissions"]}
    except Refused as refused:
        token = None
        line["outcome"] = refused.code
        message = refusal(refused.code)
    except Exception:
        token = None
        line["outcome"] = "unavailable"
        message = refusal("unavailable")

    def too_old():
        nonlocal message, token
        if token is None or fresh(expires_at):
            return False
        app.revoke(api["base"], token)
        token = None
        line["outcome"] = "expiry"
        message = refusal("expiry")
        return True

    os.fsync(log)
    too_old()
    entry = (json.dumps(line) + "\n").encode()
    app.require(os.write(log, entry) == len(entry))
    os.fsync(log)
    if too_old():
        entry = (json.dumps(line) + "\n").encode()
        app.require(os.write(log, entry) == len(entry))
        os.fsync(log)
    return message, REFUSALS[message["refusal"]][0] if message["kind"] == "refusal" else 0


def refusal(code):
    return {"schema": SCHEMA, "kind": "refusal", "refusal": code, "message": "Token refused: " + REFUSALS[code][1]}


def main():
    parser = app.arguments(USAGE)
    parser.add_argument("command", choices=("mint", "start", "stop"))
    args = parser.parse_args()
    if args.command != "mint":
        directory = folder(app.state_path(args.state_dir), create=True)
        try:
            if args.command == "start":
                try:
                    setting = app.mode()
                except ValueError:
                    print("Token service not started: OPENWIZ_GITHUB_APP_MODE must be unset, user or factory.",
                          file=sys.stderr)
                    return 1
                temporary = f".{STARTED}.{os.getpid()}"
                try:
                    os.unlink(temporary, dir_fd=directory)
                except FileNotFoundError:
                    pass
                app.save_file(directory, temporary, json.dumps({"mode": setting}).encode())
                os.replace(temporary, STARTED, src_dir_fd=directory, dst_dir_fd=directory)
            else:
                try:
                    os.unlink(STARTED, dir_fd=directory)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory)
        print(f"Token service started ({setting} App setting)." if args.command == "start"
              else "Token service stopped.")
        return 0
    try:
        directory = folder(app.state_path(args.state_dir))
    except FileNotFoundError:
        directory = None
    except Exception:
        return answer(refusal("unavailable"), 1)
    try:
        setting = None if directory is None else started(directory)
        if setting is None:
            print(STOPPED, file=sys.stderr)
            return 1
        try:
            log = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        except OSError:
            return answer(refusal("unavailable"), 1)
        try:
            app.checked(log)
            api = {"state": args.state_dir, "base": app.api_base(args.api_base)}
            return answer(*serve(api, log, sys.stdin.buffer.read(REQUEST_LIMIT + 1), setting))
        finally:
            os.close(log)
    finally:
        if directory is not None:
            os.close(directory)


def answer(message, code):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # SECURITY: never a traceback: it could carry a request, a path or a provider body.
        sys.exit(answer(refusal("unavailable"), 1))
