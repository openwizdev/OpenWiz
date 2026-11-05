#!/usr/bin/env python3
"""Connect OpenWiz's GitHub App on this host (#1105): register it through GitHub's
manifest flow, save its key, and capture its installation on selected repositories.

Without --yes: records the proposed `connect_app` operation in the setup state
and prints its effects and id; no network and no local server. With
--yes --operation ID: runs the loopback flow for exactly that proposal.
Registration happens at most once: the operation is uncertain before GitHub is
asked to convert, a saved App is reconciled with GitHub instead of registered
again, and an uncertain registration without a saved key is never repeated.

With --agent-for LOGIN [--organization] (GI4, #2546): the agent mode prepares the
one App for that account or organisation instead. Its public id is recorded here
first, so it is registered once. GitHub's converted key goes only to the
Cloudroom secret OPENWIZ_GITHUB_APP_KEY through --secret-store, or, with no store,
is discarded (J27); no copy stays on this host. With that secret delivered, the
App is reconciled with GitHub on every run, never registered again, and only its
install is offered and read back.
"""
import base64
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.parse

HERE = Path(__file__).resolve().parent
# Its own helpers even under `python3 -I`, and the setup store: `../setup` in an
# installed runtime/, `../install/setup` in the repository (#1105).
sys.path[:0] = [str(HERE), str(HERE.parent / "setup"), str(HERE.parent / "install" / "setup")]
import app  # noqa: E402
import store  # noqa: E402  (the durable setup operation store)

INSTALL = re.compile(r"[1-9][0-9]{0,15}")
# A GitHub login: letters, digits and single inner hyphens, at most 39.
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}")
# contracts/github-identity.v1.md: the secret and the App id beside it.
SECRET, APP_ID = "OPENWIZ_GITHUB_APP_KEY", "OPENWIZ_GITHUB_APP_ID"


def effects(repo, saved, after):
    found = (["Reuse the App already saved on this host; nothing new is registered."] if saved else [
        "Register a public GitHub App named OpenWiz with Metadata read, Contents, Issues and "
        "Pull requests write, Checks and Actions read; no webhook.",
        "Save its private key owner-only in this host's OpenWiz state; it is never shown."])
    if after:
        found.append(f"Proceed although operation {after} may have registered an App you have checked on GitHub.")
    return found + [f"Open GitHub to install the App on only the repositories you select, including {repo}.",
                    "Record the App and installation ids. Readiness is checked separately."]


def newest_uncertain(value, besides=None):
    """The newest uncertain App registration, host or agent: it may exist on GitHub."""
    found = [o["operation_id"] for o in value["operations"] if o["kind"] == "connect_app"
             and o["phase"] == "uncertain" and o["operation_id"] != besides]
    return found[-1] if found else None


def refuse_uncertain(newest):
    print("App connection refused: an earlier registration is uncertain. Check GitHub's App settings "
          f"for it (operation {newest}), then preview with --after-uncertain {newest}." if newest else
          "App connection refused: --after-uncertain names no uncertain registration.", file=sys.stderr)
    sys.exit(6)


def still_newest(operation, after):
    """Re-check R3: under the claim's own lock, the acknowledged newest uncertain
    registration must still be the newest; a registration that became uncertain
    after this was authorized blocks the claim."""
    def check(value):
        if newest_uncertain(value, operation["operation_id"]) != after:
            raise store.Refused("a newer registration became uncertain; reconcile it first")
    return check


def saved_app(directory):
    try:
        config = app.parse_json(app.read_file(directory, "app.json", 1024))
    except FileNotFoundError:
        return None
    app.require(set(config) == {"app_id"} and type(config["app_id"]) is int and config["app_id"] > 0)
    return config["app_id"]


def agent_effects(account, organization, app_id, store):
    where = ("the organisation " if organization else "the account ") + account
    found = ([f"Reconcile App {app_id} with GitHub from the Cloudroom secret {SECRET}; nothing new is "
              "registered."] if app_id else [
        f"Prepare a public GitHub App named OpenWiz for {where}, with Metadata read, Contents, Issues and "
        "Pull requests write, Checks and Actions read; no webhook.",
        f"Record its public App id in this host's OpenWiz state before anything else."
        + (f" Store its private key only in the Cloudroom secret {SECRET} and its id as {APP_ID}."
           if store else " Discard GitHub's converted key: no store was named (J27).")])
    return found + [f"Offer GitHub's install page for only the repositories you select on {account}.",
                    "Read the installation back from GitHub."]


def sign(pem, app_id):
    """An App JWT from a key held only in memory: openssl reads it from a pipe,
    never an argument or a file."""
    app.require(type(app_id) is int and app_id > 0 and 0 < len(pem) <= 16384)
    read, write = os.pipe()
    try:
        with os.fdopen(write, "wb") as pipe:
            pipe.write(pem)  # within the pipe's buffer: 16 KiB at most
        now = int(time.time())
        message = (app.encode(b'{"alg":"RS256","typ":"JWT"}') + b"." + app.encode(json.dumps(
            {"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, separators=(",", ":")).encode()))
        signature = app.openssl(["dgst", "-sha256", "-sign", f"/dev/fd/{read}"], message, pass_fds=(read,))
        return (message + b"." + app.encode(signature)).decode("ascii")
    finally:
        os.close(read)


def store_secret(program, name, value):
    """The one secret seam. Assumption A1: Cloudroom's agent-side store takes
    the secret's NAME as its only argument and its value on stdin. It runs with
    no environment, and nothing it prints is shown."""
    result = subprocess.run([str(program), name], input=value, capture_output=True, timeout=60, env={}, cwd="/")
    app.require(result.returncode == 0)


def delivered(registered):
    """(App id, key, id delivered) as Cloudroom delivers the secret, or None
    without a key. A key alone takes its id from the registration recorded here
    (a partial delivery); a delivered id must agree with that record."""
    key, ident = os.environ.get(SECRET), os.environ.get(APP_ID)
    if key is None:
        return None
    app_id = int(app.positive_id(ident)) if ident is not None else registered
    app.require(app_id is not None and registered in (None, app_id))
    pem = base64.b64decode(key.encode("ascii"), validate=True)
    app.require(0 < len(pem) <= 16384)
    return app_id, pem, ident is not None


def reply(handler, status, text, script=None, location=None):
    """A no-store page. SCRIPT is the nonce of its one inline script; LOCATION
    sends the browser on (303) so the person's only clicks are GitHub's."""
    data = text.encode()
    policy = ("default-src 'none'; form-action https://github.com; base-uri 'none'; frame-ancestors 'none'"
              + (f"; script-src 'nonce-{script}'" if script else ""))
    handler.send_response(status)
    for name, value in (("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(data))),
                        ("Cache-Control", "no-store"), ("Referrer-Policy", "no-referrer"),
                        ("X-Content-Type-Options", "nosniff"), ("Content-Security-Policy", policy),
                        *((("Location", location),) if location else ())):
        handler.send_header(name, value)
    handler.end_headers()
    handler.wfile.write(data)


def agent(args):
    """GI4's agent mode: one App, its public id recorded here, its key only in
    the Cloudroom secret (or, with no store, discarded)."""
    account = args.agent_for
    app.require(LOGIN.fullmatch(account) is not None and args.repo is None)
    program = None
    if args.secret_store is not None:
        program = Path(args.secret_store)
        app.require(program.is_absolute() and program.is_file() and os.access(program, os.X_OK))
    home = "https://github.com/" + account
    # GitHub's manifest schema requires url whenever hook_attributes is present.
    template = dict(app.manifest(), url=home, hook_attributes={"url": home, "active": False})
    state = app.state_path(args.state_dir)
    directory = app.app_directory(state, create=True)
    try:
        agent_run(args, account, program, template, store.Store(str(state)), directory)
    finally:
        os.close(directory)


def agent_run(args, account, program, template, setup, directory):
    # Review R2: the one registered App's public id, recorded before its key is
    # provisioned. While it exists, nothing is ever registered again, for any account.
    registered = saved_app(directory)
    if os.environ.get(SECRET) is None and os.environ.get(APP_ID) is not None:
        # Review R6: a delivered id names an existing App (a fresh sandbox, J27's
        # path): never offer Create; wait for its key.
        shown = os.environ[APP_ID] if INSTALL.fullmatch(os.environ[APP_ID]) else "(not an id)"  # never echo a value
        print(f"App connection refused: App {shown} is delivered without its key. Deliver "
              f"the Cloudroom secret {SECRET} to reconcile it; if the key is lost, generate a new one on GitHub "
              "as docs/agents/github-app.md says.", file=sys.stderr)
        sys.exit(6)
    existing = delivered(registered)
    current = setup.read()
    if existing is None and registered is not None:
        print(f"App connection refused: App {registered} is already registered. Deliver its key as the "
              f"Cloudroom secret {SECRET} to reconcile it; if the key is lost, generate a new one on GitHub "
              "as docs/agents/github-app.md says.", file=sys.stderr)
        sys.exit(6)
    newest = newest_uncertain(current)
    if existing is None and args.after_uncertain != newest:
        refuse_uncertain(newest)
    reconcile = existing is not None
    request = {"agent_for": account.lower(), "organization": args.organization, "permissions": app.SERVICE,
               "reconcile": existing[0] if reconcile else None, "store": program is not None,
               "after": None if reconcile else args.after_uncertain}
    # Review R1: a registration, once applied, stands; a reconciliation never
    # does, so every run reads GitHub again and offers the install again.
    stands = (lambda value: False) if reconcile else (lambda value: True)
    if not args.yes:
        operation = setup.propose("connect_app", request, agent_effects(
            account, args.organization, request["reconcile"], program is not None),
            "Proposed: confirm with --yes --operation.", stands)
        print(json.dumps(operation, sort_keys=True))
        return
    app.require(args.operation is not None)
    operation = setup.authorized(current, args.operation, "connect_app", request, stands)
    if operation["phase"] == "applied":
        print(json.dumps(operation, sort_keys=True))
        return
    app.require(operation["phase"] == "proposed" or (operation["phase"] == "uncertain" and reconcile))
    nonce = secrets.token_urlsafe(32)
    outcome = {"done": False, "success": False, "slug": None, "app_id": None, "pem": None,
               "claimed": False, "converted": False, "registered": False}
    if reconcile:
        app_id, pem, id_delivered = existing
        status, found = app.get(args.api_base, "/app", sign(pem, app_id))
        # Signed with the delivered key, so it is this App; LOGIN may be another
        # account it installs on (the one App installs on both accounts).
        app.require(status == 200 and found.get("id") == app_id and isinstance(found.get("slug"), str))
        app.service_permissions(found.get("permissions"))
        if registered is None:
            app.save_file(directory, "app.json", json.dumps({"app_id": app_id}).encode())
        if not id_delivered and program is not None:
            # Review R5: a partial delivery is repaired with the public id only;
            # the delivered key is never converted, stored or replaced again.
            store_secret(program, APP_ID, f"{app_id}\n".encode())
        outcome.update(slug=found["slug"], app_id=app_id, pem=pem)
    if args.organization:
        target = f"https://github.com/organizations/{account}/settings/apps/new?"
    else:
        target = "https://github.com/settings/apps/new?"

    def install_link():
        app.require(re.fullmatch(r"[a-z0-9-]{1,64}", outcome["slug"] or "") is not None)
        return (f"https://github.com/apps/{outcome['slug']}/installations/new?"
                + urllib.parse.urlencode({"state": nonce}))

    def install_page(handler, lead):
        # Straight on to GitHub's install page: the person's second click is GitHub's Install.
        reply(handler, 303, f'<!doctype html><title>OpenWiz GitHub App</title><p>{lead} '
              f'<a href="{html.escape(install_link(), quote=True)}">Install it</a> on {html.escape(account)}, '
              'selecting only the repositories you were given.</p>', location=install_link())

    def unregistered(value):
        # Under the claim's lock: still no App recorded here, and no newer uncertain registration.
        still_newest(operation, request["after"])(value)
        if saved_app(directory) is not None:
            raise store.Refused("an App is already registered here; reconcile it")

    class Handler(BaseHTTPRequestHandler):
        # Request paths carry GitHub's temporary code: never log them.
        def log_message(self, *_args):
            pass

        def do_GET(self):
            try:
                self.handle_get()
            except Exception:
                outcome["done"] = True
                reply(self, 502, "App setup failed. No credentials are displayed. Check the terminal.")

        def handle_get(self):
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                reply(self, 400, "Invalid local request.")
                return
            parts = urllib.parse.urlsplit(self.path)
            base = f"http://127.0.0.1:{self.server.server_port}"
            if parts.path == f"/start/{nonce}" and not parts.query:
                if outcome["app_id"] is not None:
                    install_page(self, f"The App is registered and its key is in the Cloudroom secret {SECRET}.")
                    return
                if not outcome["claimed"]:
                    # Review R4: GitHub creates the App at Create, before any callback,
                    # so the registration is uncertain before the form is released.
                    try:
                        setup.settle(operation["operation_id"], "uncertain",
                                     "The creation form was released; the App may exist on GitHub.",
                                     also=unregistered, claim=True)
                    except store.Refused:
                        outcome["done"] = True
                        reply(self, 409, "This registration cannot start now: it was already started, an App "
                              "is registered, or a newer registration is uncertain. Nothing was sent to GitHub.")
                        return
                    outcome["claimed"] = True
                value = dict(template, redirect_url=f"{base}/callback", setup_url=f"{base}/installed",
                             setup_on_update=True)
                action = target + urllib.parse.urlencode({"state": nonce})
                script = secrets.token_urlsafe(16)
                # The form submits itself, so the person's first click is GitHub's Create.
                reply(self, 200, '<!doctype html><title>OpenWiz GitHub App</title><h1>OpenWiz GitHub App</h1>'
                      f'<p>Create it for {html.escape(account)} with Metadata read, Contents, Issues and Pull '
                      'requests write, Checks and Actions read. Its private key goes only to the Cloudroom '
                      f'secret {SECRET}; it is never shown.</p>'
                      f'<form method="post" action="{html.escape(action, quote=True)}">'
                      f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(value), quote=True)}">'
                      '<noscript><button type="submit">Continue to GitHub</button></noscript></form>'
                      f'<script nonce="{script}">document.forms[0].submit()</script>', script=script)
                return
            try:
                query = urllib.parse.parse_qs(parts.query, strict_parsing=True)
            except ValueError:
                query = {}
            if parts.path == "/installed":
                self.installed(query)
                return
            if (parts.path != "/callback" or not outcome["claimed"] or outcome["converted"]
                    or set(query) != {"code", "state"} or len(query["state"]) != 1 or len(query["code"]) != 1
                    or not secrets.compare_digest(query["state"][0], nonce)
                    or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", query["code"][0]) is None):
                reply(self, 400, "Invalid setup callback.")
                return
            # This instance's own claim converts once; a lost reply or a failed
            # store leaves the registration uncertain, never repeated.
            outcome.update(converted=True, done=True)
            result = app.post(args.api_base, "/app-manifests/" + query["code"][0] + "/conversions")
            app.service_permissions(result.get("permissions"))
            new_id, slug = result["id"], result.get("slug")
            app.require(type(new_id) is int and new_id > 0)
            app.require(isinstance(slug, str) and re.fullmatch(r"[a-z0-9-]{1,64}", slug) is not None)
            # The public identity first (review R5), so a partial delivery is repairable.
            app.save_file(directory, "app.json", json.dumps({"app_id": new_id}).encode())
            pem = None
            if program is not None:
                pem = result["pem"].encode("ascii")
                app.require(0 < len(pem) <= 16384)
                app.openssl(["rsa", "-check", "-noout"], pem)
                store_secret(program, SECRET, base64.b64encode(pem) + b"\n")
                store_secret(program, APP_ID, f"{new_id}\n".encode())
                kept = f"its key is in the Cloudroom secret {SECRET}"
            else:
                kept = (f"its converted key was discarded; generate a private key on GitHub and paste it once "
                        f"into Cloudroom's prompt for {SECRET}")
            result = None
            setup.settle(operation["operation_id"], "applied", f"App registered; {kept}. Install it next.")
            outcome.update(app_id=new_id, slug=slug, pem=pem, registered=True, done=False,
                           success=program is None)
            print(f"App ID: {new_id}. Registered; {kept}. Install: {install_link()}", flush=True)
            install_page(self, "Created.")

        def installed(self, query):
            if (outcome["app_id"] is None or set(query) - {"installation_id", "setup_action", "state"}
                    or any(len(v) != 1 for v in query.values())
                    or not secrets.compare_digest(query.get("state", [""])[0], nonce)
                    or INSTALL.fullmatch(query.get("installation_id", [""])[0]) is None
                    or query.get("setup_action", [""])[0] not in ("install", "update")):
                reply(self, 400, "Invalid installation callback.")
                return
            if outcome["pem"] is None:
                # No key here (J27): the next run, with the pasted key, reads it back.
                outcome["done"] = True
                print("Installed on GitHub; it is read back once the key is in the Cloudroom secret.", flush=True)
                reply(self, 200, '<!doctype html><title>App installed</title><p>Installed. Return to the agent '
                      'to paste the App key into Cloudroom.</p>')
                return
            installation = int(query["installation_id"][0])
            # Read back: this App's installation, on the named account, selected repositories only.
            status, found = app.get(args.api_base, f"/app/installations/{installation}",
                                    sign(outcome["pem"], outcome["app_id"]))
            login = ((found or {}).get("account") or {}).get("login")
            if (status != 200 or found.get("id") != installation or found.get("app_id") != outcome["app_id"]
                    or not isinstance(login, str) or login.lower() != account.lower()
                    or found.get("repository_selection") != "selected"):
                reply(self, 400, "That installation is not this App's on the named account with selected "
                      "repositories only.")
                return
            if not outcome["registered"]:
                setup.settle(operation["operation_id"], "applied",
                             "App reconciled and its installation read back.")
            outcome.update(done=True, success=True)
            print(f"Installation {installation} read back: {account}, selected repositories only.", flush=True)
            reply(self, 200, '<!doctype html><title>App installed</title><p>Installed. Return to the agent.</p>')

    with HTTPServer(("127.0.0.1", args.port), Handler) as server:
        server.timeout = 1
        print(f"Open on this host: http://127.0.0.1:{server.server_port}/start/{nonce}", flush=True)
        deadline = time.monotonic() + 600
        while not outcome["done"] and time.monotonic() < deadline:
            server.handle_request()
    app.require(outcome["success"])


def main():
    parser = app.arguments(__doc__)
    parser.add_argument("--port", type=int, default=8765, help="loopback port (default 8765); keep it for reconnects")
    parser.add_argument("--repo", help="OWNER/NAME to select (default: this clone's GitHub origin)")
    parser.add_argument("--yes", action="store_true", help="carry out the previewed operation")
    parser.add_argument("--operation", help="the operation id the preview printed")
    parser.add_argument("--after-uncertain", help="a prior uncertain operation you checked on GitHub")
    parser.add_argument("--agent-for", metavar="LOGIN", help="agent mode: prepare the App for this account")
    parser.add_argument("--organization", action="store_true", help="with --agent-for: LOGIN is an organisation")
    parser.add_argument("--secret-store", metavar="PATH",
                        help="with --agent-for: the absolute secret store program (assumption A1); without it, the key is discarded")
    args = parser.parse_args()
    app.api_base(args.api_base)
    if args.agent_for is not None:
        agent(args)
        return
    app.require(not args.organization and args.secret_store is None)
    repo = app.repository(args.repo)
    template = app.manifest(repo)
    setup = store.Store(str(app.state_path(args.state_dir)))
    directory = app.app_directory(app.state_path(args.state_dir), create=True)
    try:
        app_id = saved_app(directory)
        if app_id is None:
            app.absent(directory, "private-key.pem")
        current = setup.read()
        # An uncertain registration without a saved App may exist on GitHub:
        # never register again until the owner names the newest one as checked
        # (review R3: an older acknowledgment never covers a later attempt).
        newest = newest_uncertain(current)
        if app_id is None and args.after_uncertain != newest:
            refuse_uncertain(newest)
        # Review R8: the request's identity stays the same across its own
        # completion; an applied connection stands while an installation is
        # recorded (the check clears it after a removal or revocation).
        # Re-check R8: the acknowledgment given is part of the identity whether
        # or not an App has been saved since, so a completed recovery reloads.
        request = {"repository": repo, "permissions": app.SERVICE, "after": args.after_uncertain}

        def connected(value):
            return value["app"] is not None and value["app"]["installation_id"] is not None
        if not args.yes:
            operation = setup.propose("connect_app", request, effects(repo, app_id is not None, request["after"]),
                                      "Proposed: confirm with --yes --operation.", connected)
            print(json.dumps(operation, sort_keys=True))
            return
        app.require(args.operation is not None)
        operation = setup.authorized(current, args.operation, "connect_app", request, connected)
        if operation["phase"] == "applied":
            print(json.dumps(operation, sort_keys=True))
            return
        app.require(operation["phase"] in ("proposed", "uncertain"))
        owner = repo.split("/")[0].lower()
        nonce = secrets.token_urlsafe(32)
        outcome = {"done": False, "success": False, "slug": None, "app_id": app_id}
        if app_id is not None:
            # Reconcile the exact resource before anything else.
            status, found = app.get(args.api_base, "/app", app.jwt(directory, app_id))
            app.require(status == 200 and found.get("id") == app_id and isinstance(found.get("slug"), str))
            outcome["slug"] = found["slug"]

        def install_link():
            app.require(re.fullmatch(r"[a-z0-9-]{1,64}", outcome["slug"] or "") is not None)
            return (f"https://github.com/apps/{outcome['slug']}/installations/new?"
                    + urllib.parse.urlencode({"state": nonce}))

        class Handler(BaseHTTPRequestHandler):
            # Includes request paths: GitHub's temporary code must never be logged.
            def log_message(self, *_args):
                pass

            def reply(self, status, text):
                data = text.encode()
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Content-Security-Policy",
                                 "default-src 'none'; form-action https://github.com; base-uri 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                try:
                    self.handle_get()
                except Exception:
                    outcome["done"] = True
                    self.reply(502, "App setup failed. No credentials are displayed. Check the terminal.")

            def handle_get(self):
                if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                    self.reply(400, "Invalid local request.")
                    return
                parts = urllib.parse.urlsplit(self.path)
                base = f"http://127.0.0.1:{self.server.server_port}"
                if parts.path == f"/start/{nonce}" and not parts.query:
                    if outcome["app_id"] is not None:
                        self.reply(200, '<!doctype html><title>OpenWiz GitHub App</title>'
                                   '<p>The App is already saved on this host. '
                                   f'<a href="{html.escape(install_link(), quote=True)}">Install it</a> '
                                   'on only the repositories you select.</p>')
                        return
                    value = dict(template, redirect_url=f"{base}/callback",
                                 setup_url=f"{base}/installed", setup_on_update=True)
                    action = "https://github.com/settings/apps/new?" + urllib.parse.urlencode({"state": nonce})
                    self.reply(200, '<!doctype html><title>OpenWiz GitHub App</title>'
                               '<h1>OpenWiz GitHub App</h1>'
                               '<p>Create it with Metadata read, Contents, Issues and Pull requests write, '
                               'Checks and Actions read, then install it on only the repositories you select. '
                               'The private key stays in this host’s OpenWiz state directory.</p>'
                               f'<form method="post" action="{html.escape(action, quote=True)}">'
                               f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(value), quote=True)}">'
                               '<button type="submit">Create the App on GitHub</button></form>')
                    return
                try:
                    query = urllib.parse.parse_qs(parts.query, strict_parsing=True)
                except ValueError:
                    query = {}
                if parts.path == "/installed":
                    self.installed(query)
                    return
                if (parts.path != "/callback" or outcome["app_id"] is not None or set(query) != {"code", "state"}
                        or len(query["state"]) != 1 or len(query["code"]) != 1
                        or not secrets.compare_digest(query["state"][0], nonce)
                        or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", query["code"][0]) is None):
                    self.reply(400, "Invalid setup callback.")
                    return
                # Write-ahead, and the one claim (review R3): only a proposed
                # operation may ask GitHub to create an App, exactly once. If the
                # reply is lost, the App may exist on GitHub.
                outcome["done"] = True
                try:
                    setup.settle(operation["operation_id"], "uncertain",
                                 "Registration was requested; waiting for GitHub's answer and the installation.",
                                 also=still_newest(operation, request["after"]), claim=True)
                except store.Refused:
                    self.reply(409, "This registration cannot be requested now: it was already requested, or a newer "
                               "registration is uncertain. Nothing was sent to GitHub.")
                    return
                result = app.post(args.api_base, "/app-manifests/" + query["code"][0] + "/conversions")
                app.service_permissions(result.get("permissions"))
                new_id = result["id"]
                app.require(type(new_id) is int and new_id > 0)
                slug = result.get("slug")
                app.require(isinstance(slug, str) and re.fullmatch(r"[a-z0-9-]{1,64}", slug) is not None)
                pem = result["pem"].encode("ascii")
                app.require(0 < len(pem) <= 16384)
                app.openssl(["rsa", "-check", "-noout"], pem)
                # Never overwrite. A partial save leaves the key on this host for recovery.
                app.save_file(directory, "private-key.pem", pem)
                app.save_file(directory, "app.json", json.dumps({"app_id": new_id}).encode())
                os.fsync(directory)
                outcome.update(app_id=new_id, slug=slug, done=False)
                print(f"App ID: {new_id}. Install: {install_link()}", flush=True)
                self.reply(200, '<!doctype html><title>App saved</title><p>Key saved on this host. '
                           f'<a href="{html.escape(install_link(), quote=True)}">Install the App</a> '
                           'on only the repositories you select.</p>')

            def installed(self, query):
                # GitHub's setup URL: installation_id and setup_action, with our state.
                if (outcome["app_id"] is None or set(query) - {"installation_id", "setup_action", "state"}
                        or any(len(v) != 1 for v in query.values())
                        or not secrets.compare_digest(query.get("state", [""])[0], nonce)
                        or INSTALL.fullmatch(query.get("installation_id", [""])[0]) is None
                        or query.get("setup_action", [""])[0] not in ("install", "update")):
                    self.reply(400, "Invalid installation callback.")
                    return
                installation = int(query["installation_id"][0])
                # The id is captured only when GitHub confirms it is this App's,
                # for the selected repository's owner.
                status, found = app.get(args.api_base, f"/app/installations/{installation}",
                                        app.jwt(directory, outcome["app_id"]))
                login = ((found or {}).get("account") or {}).get("login")
                if (status != 200 or found.get("id") != installation or found.get("app_id") != outcome["app_id"]
                        or not isinstance(login, str) or login.lower() != owner):
                    self.reply(400, "That installation does not belong to this App and repository owner.")
                    return
                ids = {"app_id": outcome["app_id"], "installation_id": installation}

                def record(value):
                    if value["app"] != ids:
                        value["app"] = ids
                        value["revision"] += 1
                setup.settle(operation["operation_id"], "applied",
                             "App installed; run the setup check to verify its repositories and permissions.",
                             also=record)
                outcome.update(done=True, success=True)
                print(f"Installation {installation} captured. Run the setup check.", flush=True)
                self.reply(200, '<!doctype html><title>App installed</title><p>Installed. '
                           'Return to OpenWiz setup and run the check.</p>')

        with HTTPServer(("127.0.0.1", args.port), Handler) as server:
            server.timeout = 1
            print(f"Open on this host: http://127.0.0.1:{server.server_port}/start/{nonce}", flush=True)
            deadline = time.monotonic() + 600
            while not outcome["done"] and time.monotonic() < deadline:
                server.handle_request()
        app.require(outcome["success"])
    finally:
        os.close(directory)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        print("App setup refused: check state permissions and GitHub availability. Existing keys are never overwritten.",
              file=sys.stderr)
        sys.exit(1)
