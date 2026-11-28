#!/usr/bin/env python3
import argparse
import hmac
import importlib.util
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("openwiz_chrome_agent", HERE / "agent.py")
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)

SCHEMA = agent.SCHEMA
VERSION = "0.1.0"
MAX_BODY = 1024 * 1024
DEMO = HERE.parent / "demo" / "page.html"
SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
EXTENSION_ORIGIN = re.compile(r"chrome-extension://[a-p]{32}$")
TOKEN_CHARS = re.compile(r"[A-Za-z0-9_-]{32,128}")


class RequestError(Exception):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message


class Bridge(ThreadingHTTPServer):
    address_family = socket.AF_INET
    allow_reuse_address = True
    daemon_threads = True


def state_dir_from(value):
    if value:
        return Path(value)
    env = os.environ.get("OPENWIZ_CHROME_STATE")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "openwiz-chrome"


def valid_token(token):
    return isinstance(token, str) and TOKEN_CHARS.fullmatch(token) is not None


def load_token(directory, rotate=False):
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / "token.json"
    if path.exists() and not rotate:
        mode = path.stat().st_mode & 0o777
        if mode != 0o600:
            raise SystemExit("openwiz-chrome: the token file must be mode 600")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            token = data["token"]
        except (OSError, ValueError, KeyError, TypeError):
            raise SystemExit("openwiz-chrome: the token file is not usable")
        if not valid_token(token) or data.get("schema") != SCHEMA:
            raise SystemExit("openwiz-chrome: the token file is not usable")
        return token, False
    token = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"schema": SCHEMA, "token": token}, handle)
        handle.write("\n")
    os.chmod(path, 0o600)
    return token, True


def build_server(host, port, token, agent_argv, agent_timeout, demo_path):
    if host != "127.0.0.1":
        raise ValueError("the bridge binds 127.0.0.1 only")
    if not valid_token(token):
        raise ValueError("the pairing token is not usable")
    httpd = Bridge((host, port), Handler)
    bound = httpd.socket.getsockname()
    if bound[0] != "127.0.0.1":
        httpd.server_close()
        raise ValueError("the bridge did not bind 127.0.0.1")
    httpd.token = token
    httpd.agent_argv = tuple(agent_argv)
    httpd.agent_timeout = agent_timeout
    httpd.demo_path = Path(demo_path)
    httpd.history = {}
    httpd.lock = threading.Lock()
    return httpd


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        return

    def host_ok(self):
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if port == 80:
            allowed |= {"127.0.0.1", "localhost"}
        return host in allowed

    def origin_ok(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        if EXTENSION_ORIGIN.fullmatch(origin):
            return True
        port = self.server.server_address[1]
        allowed = {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}
        if port == 80:
            allowed |= {"http://127.0.0.1", "http://localhost"}
        return origin in allowed

    def echo_origin(self):
        origin = self.headers.get("Origin")
        if origin and self.origin_ok():
            return origin
        return None

    def gate(self):
        if not self.host_ok():
            self.refuse(403, "host_not_allowed", "Host is not loopback.", None)
            return False
        if not self.origin_ok():
            self.refuse(403, "origin_not_allowed", "Origin is not allowed.", None)
            return False
        return True

    def bearer(self):
        header = self.headers.get("Authorization")
        if header is None:
            return None
        prefix = "Bearer "
        if not header.startswith(prefix):
            return None
        token = header[len(prefix):]
        if not token or any(char.isspace() for char in token):
            return None
        return token

    def require_token(self):
        presented = self.bearer()
        origin = self.echo_origin()
        if presented is None:
            self.refuse(401, "missing_token", "Authorization Bearer token is required.", origin)
            return False
        if not hmac.compare_digest(presented.encode(), self.server.token.encode()):
            self.refuse(401, "invalid_token", "The pairing token was refused.", origin)
            return False
        return True

    def only_path(self):
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.query or parsed.fragment:
            self.refuse(400, "invalid_request", "The request has no query string.", self.echo_origin())
            return None
        return parsed.path

    def refuse(self, status, code, message, origin):
        self.send_json(status, {"refusal": {"code": code, "message": message}}, origin)

    def send_json(self, status, payload, origin):
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        origin = self.echo_origin()
        media = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if media != "application/json":
            self.refuse(400, "invalid_request", "Content-Type must be application/json.", origin)
            return None
        length = self.headers.get("Content-Length")
        if length is None:
            self.refuse(411, "length_required", "Content-Length is required.", origin)
            return None
        try:
            size = int(length)
        except ValueError:
            self.refuse(400, "invalid_request", "Content-Length is not a number.", origin)
            return None
        if size < 0 or size > MAX_BODY:
            self.refuse(413, "payload_too_large", "The body is over 1 MiB.", origin)
            return None
        raw = self.rfile.read(size)
        try:
            body = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.refuse(400, "invalid_request", "The body is not a JSON object.", origin)
            return None
        if not isinstance(body, dict):
            self.refuse(400, "invalid_request", "The body is not a JSON object.", origin)
            return None
        return body

    def do_OPTIONS(self):
        if not self.gate():
            return
        origin = self.echo_origin()
        if origin is None:
            self.refuse(403, "origin_not_allowed", "Origin is required for preflight.", None)
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.gate():
            return
        path = self.only_path()
        if path is None:
            return
        if path in ("/demo", "/demo/"):
            self.send_demo()
            return
        if path.startswith("/chrome/v1/"):
            self.refuse(405, "method_not_allowed", "This route accepts POST.", self.echo_origin())
            return
        self.refuse(404, "unknown_route", "That route is not on the bridge.", self.echo_origin())

    def do_HEAD(self):
        self.do_GET()

    def do_PUT(self):
        self.reject_method()

    def do_DELETE(self):
        self.reject_method()

    def reject_method(self):
        if not self.gate():
            return
        if not self.require_token():
            return
        self.refuse(405, "method_not_allowed", "This bridge accepts POST.", self.echo_origin())

    def send_demo(self):
        path = self.server.demo_path
        try:
            body = path.read_bytes()
        except OSError:
            self.refuse(404, "unknown_route", "The demo page is not available.", self.echo_origin())
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.echo_origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.gate():
            return
        if not self.require_token():
            return
        path = self.only_path()
        if path is None:
            return
        origin = self.echo_origin()
        body = self.read_json()
        if body is None:
            return
        try:
            if path == "/chrome/v1/health":
                payload = self.health()
            elif path == "/chrome/v1/agents":
                payload = {"schema": SCHEMA, "agents": self.agent_rows()}
            elif path == "/chrome/v1/chat":
                payload = self.chat(body)
            else:
                self.refuse(404, "unknown_route", "That route is not on the bridge.", origin)
                return
        except RequestError as exc:
            self.refuse(exc.status, exc.code, exc.message, origin)
            return
        self.send_json(200, payload, origin)

    def agent_rows(self):
        rows = [{"id": "page", "name": "Page", "kind": "builtin"}]
        if self.server.agent_argv:
            rows.append({"id": "command", "name": "Command", "kind": "command"})
        return rows

    def health(self):
        return {
            "schema": SCHEMA,
            "status": "ok",
            "version": VERSION,
            "agents": [row["id"] for row in self.agent_rows()],
        }

    def chat(self, body):
        session_id = body.get("session_id")
        if not isinstance(session_id, str) or SESSION.fullmatch(session_id) is None:
            raise RequestError(400, "invalid_request", "session_id is not usable.")
        agent_id = body.get("agent", "page")
        if agent_id not in {row["id"] for row in self.agent_rows()}:
            raise RequestError(404, "unknown_agent", "That agent is not available.")
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise RequestError(400, "invalid_request", "The message is empty.")
        if "\0" in text or len(text.encode("utf-8")) > agent.MAX_TEXT:
            raise RequestError(400, "invalid_request", "The message is not usable.")
        if "page" not in body or body["page"] is None:
            page = None
        else:
            page = agent.normalize_page(body["page"])
            if page is False:
                raise RequestError(400, "invalid_request", "The page is not an object.")
        if agent_id == "page":
            reply, actions = agent.answer(text, page)
        else:
            reply, actions = self.command_turn(session_id, text, page)
        reply = reply.strip()[: agent.MAX_REPLY]
        if not reply:
            raise RequestError(503, "unavailable", "The agent returned an empty reply.")
        with self.server.lock:
            history = self.server.history.setdefault(session_id, [])
            history.append({"role": "user", "text": text})
            history.append({"role": "agent", "text": reply})
            del history[:-8]
        return {
            "schema": SCHEMA,
            "session_id": session_id,
            "agent": agent_id,
            "text": reply,
            "actions": actions,
        }

    def history_for(self, session_id):
        with self.server.lock:
            rows = list(self.server.history.get(session_id, []))
        return rows[-8:]

    def command_turn(self, session_id, text, page):
        payload = {
            "schema": SCHEMA,
            "session_id": session_id,
            "text": text,
            "page": page,
            "history": self.history_for(session_id),
        }
        try:
            proc = subprocess.Popen(
                list(self.server.agent_argv),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError:
            raise RequestError(503, "unavailable", "The command agent could not be started.")
        try:
            out, _err = proc.communicate(json.dumps(payload).encode("utf-8"), timeout=self.server.agent_timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=2)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()
            raise RequestError(503, "unavailable", "The command agent timed out.")
        if proc.returncode != 0 or len(out) > MAX_BODY:
            raise RequestError(503, "unavailable", "The command agent failed.")
        try:
            replied = json.loads(out.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise RequestError(503, "unavailable", "The command agent returned an unusable reply.")
        if not isinstance(replied, dict) or not isinstance(replied.get("text"), str):
            raise RequestError(503, "unavailable", "The command agent returned an unusable reply.")
        actions = agent.sanitize_actions(replied.get("actions"))
        if actions is None:
            raise RequestError(503, "unavailable", "The command agent returned an unusable reply.")
        return replied["text"], actions


def positive_timeout(value):
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("timeout must be a number")
    if number <= 0 or number > 120:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 120 seconds")
    return number


def port_number(value):
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("port must be a number")
    if number < 0 or number > 65535:
        raise argparse.ArgumentTypeError("port must be from 0 to 65535")
    return number


def serve(args):
    directory = state_dir_from(args.state_dir)
    token, _created = load_token(directory)
    argv = []
    if args.agent_command:
        argv = [args.agent_command, *args.agent_arg]
        if any("\0" in part for part in argv):
            raise SystemExit("openwiz-chrome: the command agent is not usable")
        if not Path(args.agent_command).is_file():
            raise SystemExit("openwiz-chrome: the command agent is not a file")
    try:
        httpd = build_server("127.0.0.1", args.port, token, argv, args.agent_timeout, DEMO)
    except OSError:
        raise SystemExit("openwiz-chrome: the port is not available")
    line = {
        "schema": SCHEMA,
        "event": "listening",
        "port": httpd.server_address[1],
        "token": token,
        "agents": [row["id"] for row in ([{"id": "page"}] + ([{"id": "command"}] if argv else []))],
    }
    print(json.dumps(line), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
    return 0


def show_token(args):
    directory = state_dir_from(args.state_dir)
    token, created = load_token(directory, rotate=args.rotate)
    print(json.dumps({"schema": SCHEMA, "token": token, "created": created}))
    return 0


def main(argv):
    parser = argparse.ArgumentParser(prog="openwiz-chrome-bridge")
    commands = parser.add_subparsers(dest="cmd", required=True)
    serving = commands.add_parser("serve")
    serving.add_argument("--port", type=port_number, default=17418)
    serving.add_argument("--state-dir")
    serving.add_argument("--agent-command")
    serving.add_argument("--agent-arg", action="append", default=[])
    serving.add_argument("--agent-timeout", type=positive_timeout, default=30)
    serving.set_defaults(func=serve)
    token = commands.add_parser("token")
    token.add_argument("--state-dir")
    token.add_argument("--rotate", action="store_true")
    token.set_defaults(func=show_token)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
