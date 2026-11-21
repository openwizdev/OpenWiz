#!/usr/bin/env python3
import base64
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app

DESCRIPTION = """Print an installation token for GH_TOKEN, minting only when needed (G2, #1402).

Options are mint-token.py's, plus --write and --from-secret. Stdout is the
token alone, so `GH_TOKEN="$(python3 -I refresh-token.py ...)"` works as is;
nothing else is printed on success.

- Without --write the token is read-only. With --write it carries exactly the
  App's profile: Contents, Issues and Pull requests write, the rest read; an
  answer granting anything else (workflows, administration) is refused.
- The key is the PC state's private-key.pem, or with --from-secret the
  Cloudroom secret OPENWIZ_GITHUB_APP_KEY (base64 of the PEM, one line) beside
  OPENWIZ_GITHUB_APP_ID (cloud threads). It reaches OpenSSL only by descriptor.
- A token is reused while more than five minutes of it are left, then a fresh
  one is minted. Each scope (API, installation, repositories, profile, key
  source) has its own cache entry in <state>/tokens/, owner-only (0700
  directory, 0600 files, never a symlink); an unsafe cache is refused.

mint-token.py stays byte-identical to the copy WizSkills' launch-fleet carries;
this tool uses the same guards from app.py and the same installation checks.
"""

REFRESH = 300
TOKEN = re.compile(r"[A-Za-z0-9._~+/-]+=*")
SECRET_KEY, SECRET_ID = "OPENWIZ_GITHUB_APP_KEY", "OPENWIZ_GITHUB_APP_ID"


def parser():
    result = app.arguments(DESCRIPTION)
    result.add_argument("--installation-id", required=True)
    result.add_argument("--repository", action="append", default=[],
                        help="OWNER/NAME (required, repeatable): downscope the token to this selected repository")
    result.add_argument("--write", action="store_true",
                        help="the App's write profile (Contents, Issues, Pull requests) instead of read-only")
    result.add_argument("--from-secret", action="store_true",
                        help="sign with the key in OPENWIZ_GITHUB_APP_KEY and the id in OPENWIZ_GITHUB_APP_ID")
    return result


def secret_jwt(key, app_id):
    now = int(time.time())
    message = app.encode(b'{"alg":"RS256","typ":"JWT"}') + b"." + app.encode(json.dumps(
        {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, separators=(",", ":")).encode())
    read, write = os.pipe()
    try:
        os.write(write, key)
        os.close(write)
        write = None
        signed = subprocess.run(["openssl", "dgst", "-sha256", "-sign", f"/dev/fd/{read}"],
                                input=message, capture_output=True, timeout=10, pass_fds=(read,),
                                env={"PATH": os.environ.get("PATH", os.defpath)})
    finally:
        os.close(read)
        if write is not None:
            os.close(write)
    app.require(signed.returncode == 0)
    return (message + b"." + app.encode(signed.stdout)).decode("ascii")


def credentials(args, secret):
    if args.from_secret:
        app_id = int(app.positive_id(os.environ.get(SECRET_ID, "")))
        app.require(0 < len(secret) <= 8192)
        key = base64.b64decode(secret.encode("ascii"), validate=True)
        app.require(0 < len(key) <= 4096 and key.startswith(b"-----BEGIN "))
        return app_id, secret_jwt(key, app_id)
    directory = app.app_directory(app.state_path(args.state_dir))
    try:
        config = app.parse_json(app.read_file(directory, "app.json", 1024))
        app.require(set(config) == {"app_id"})
        return config["app_id"], app.jwt(directory, config["app_id"])
    finally:
        os.close(directory)


def mint(args, selected, secret):
    profile = app.SERVICE if args.write else app.PERMISSIONS
    body = {"permissions": profile, "repositories": [name.split("/")[1] for name in selected]}
    app.api_base(args.api_base)
    app.manifest()
    setting = app.mode()
    installation = app.positive_id(args.installation_id)
    app_id, jwt = credentials(args, secret)
    status, found = app.get(args.api_base, "/app", jwt)
    app.require(status == 200 and found.get("id") == app_id)
    status, held = app.get(args.api_base, f"/app/installations/{installation}", jwt)
    app.require(status == 200 and held.get("id") == int(installation)
                and held.get("app_id") == app_id
                and held.get("repository_selection") == "selected")
    app.require(app.bound(setting, (found.get("owner") or {}).get("login"),
                          (held.get("account") or {}).get("login"), selected))
    result = app.post(args.api_base, f"/app/installations/{installation}/access_tokens", body, jwt)
    app.require(result.get("permissions") == profile)
    token = result.get("token")
    app.require(isinstance(token, str) and TOKEN.fullmatch(token) is not None)
    expiry = datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00"))
    remaining = (expiry - datetime.now(timezone.utc)).total_seconds()
    app.require(REFRESH < remaining <= 3600 + 300)
    listed = result.get("repositories")
    app.require(result.get("repository_selection") == "selected" and isinstance(listed, list))
    app.require(all(isinstance(r, dict) and isinstance(r.get("full_name"), str) for r in listed))
    app.require(sorted(r["full_name"].lower() for r in listed) == selected)
    return token, int(expiry.timestamp())


def tokens_directory(state):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        app.checked(fd, directory=True)
        try:
            os.mkdir("tokens", mode=0o700, dir_fd=fd)
        except FileExistsError:
            pass
        child = os.open("tokens", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    finally:
        os.close(fd)
    try:
        return app.checked(child, directory=True)
    except Exception:
        os.close(child)
        raise


def cached(directory, name):
    try:
        content = app.read_file(directory, name, 4096)
    except FileNotFoundError:
        return None
    try:
        value = app.parse_json(content)
    except ValueError:
        return None
    token, expiry = value.get("token"), value.get("expires_at")
    if set(value) != {"token", "expires_at"} or not isinstance(token, str) \
            or TOKEN.fullmatch(token) is None or type(expiry) is not int:
        return None
    return token, expiry


def save(directory, name, token, expiry):
    temporary = f".{name}.{os.getpid()}"
    try:
        os.unlink(temporary, dir_fd=directory)
    except FileNotFoundError:
        pass
    app.save_file(directory, temporary, json.dumps({"token": token, "expires_at": expiry}).encode())
    os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)


def main():
    secret = os.environ.pop(SECRET_KEY, "")
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN"):
        os.environ.pop(name, None)
    args = parser().parse_args()
    if not args.repository:
        print("App token refused: --repository is required.", file=sys.stderr)
        sys.exit(1)
    selected = sorted(app.repository(name).lower() for name in args.repository)
    app.require(len(set(selected)) == len(selected) and
                len({name.split("/")[0] for name in selected}) <= 1)
    scope = [args.api_base, args.installation_id, selected, args.write, args.from_secret,
             os.environ.get(SECRET_ID) if args.from_secret else None]
    name = hashlib.sha256(json.dumps(scope).encode()).hexdigest()[:32] + ".json"
    directory = tokens_directory(app.state_path(args.state_dir))
    try:
        lock = os.open(".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            app.checked(lock)
            fcntl.flock(lock, fcntl.LOCK_EX)
            found = cached(directory, name)
            if found is None or not REFRESH < found[1] - time.time() <= 3600 + 300:
                found = mint(args, selected, secret)
                save(directory, name, *found)
        finally:
            os.close(lock)
    finally:
        os.close(directory)
    print(found[0])


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("App token refused: check PC state permissions, App installation and GitHub availability.",
              file=sys.stderr)
        sys.exit(1)
