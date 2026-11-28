import json
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROUTES = frozenset({"complete", "feedback"})
MAX_BODY = 1024 * 1024


class EngineError(Exception):
    def __init__(self, status, code):
        super().__init__(code or "engine refused")
        self.status = status
        self.code = code or "engine refused"


def _unique(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def build_url(host, port, route):
    if host != "127.0.0.1":
        raise ValueError("host")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port")
    if route not in ROUTES:
        raise ValueError("route")
    return f"http://127.0.0.1:{port}/ghost/v1/{route}"


def call(host, port, token, route, body):
    url = build_url(host, port, route)
    if not isinstance(token, str) or token == "":
        raise ValueError("token")
    if not isinstance(body, dict):
        raise ValueError("body")
    raw = json.dumps(body, separators=(",", ":")).encode()
    if len(raw) > MAX_BODY:
        raise ValueError("payload")
    request = Request(url, data=raw, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Authorization", "Bearer " + token)
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            status, payload = response.status, response.read(MAX_BODY + 1)
    except HTTPError as error:
        status, payload = error.code, error.read(MAX_BODY + 1)
    except (URLError, OSError) as error:
        raise EngineError(0, "unavailable") from error
    if len(payload) > MAX_BODY:
        raise EngineError(status, "payload_too_large")
    try:
        parsed = json.loads(payload.decode(), object_pairs_hook=_unique)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise EngineError(status, "invalid_request") from error
    if status != 200:
        code = "engine refused"
        if isinstance(parsed, dict):
            refusal = parsed.get("refusal")
            if isinstance(refusal, dict) and isinstance(refusal.get("code"), str):
                code = refusal["code"]
        raise EngineError(status, code)
    if not isinstance(parsed, dict):
        raise EngineError(status, "invalid_request")
    return parsed
