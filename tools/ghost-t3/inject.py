import argparse
import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp
import engine

ROOT = Path(__file__).resolve().parent
SIDECAR = (ROOT / "sidecar.js").read_text(encoding="utf-8")
WORLD_NAME = "openwiz-ghost-isolated"
BRIDGE = """
globalThis.__openwizGhostPending = new Map();
globalThis.__openwizGhostNextId = 0;
globalThis.__openwizGhostCall = (route, body) => new Promise((resolve) => {
  globalThis.__openwizGhostNextId += 1;
  const id = String(globalThis.__openwizGhostNextId) + ":" + String(Date.now());
  globalThis.__openwizGhostPending.set(id, resolve);
  globalThis.openwizGhostBinding(JSON.stringify({ id: id, route: route, body: body }));
});
globalThis.__openwizGhostResult = (id, payload) => {
  const resolve = globalThis.__openwizGhostPending.get(id);
  globalThis.__openwizGhostPending.delete(id);
  if (resolve) resolve(payload);
};
"""


def page_source(session, long_press_ms):
    return (
        "globalThis.__openwizGhostSession = " + json.dumps(session) + ";\n"
        "globalThis.__openwizGhostLongPressMs = " + json.dumps(long_press_ms) + ";\n"
        + BRIDGE + "\n" + SIDECAR
    )


def normalize_target_url(target_url):
    if not isinstance(target_url, str) or not target_url:
        raise ValueError("target_url")
    parsed = urllib.parse.urlsplit(target_url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("target_url")
    scheme = parsed.scheme.lower()
    if scheme in ("http", "https"):
        if not parsed.hostname:
            raise ValueError("target_url")
        port = parsed.port or (443 if scheme == "https" else 80)
        return (scheme, parsed.hostname.lower(), port, parsed.path or "/")
    if scheme == "file":
        if parsed.netloc or not parsed.path.startswith("/"):
            raise ValueError("target_url")
        return ("file", "", None, parsed.path)
    raise ValueError("target_url")


def target_matches(page_url, target_url):
    if not isinstance(page_url, str) or not page_url:
        return False
    try:
        want_scheme, want_host, want_port, want_path = normalize_target_url(target_url)
        parsed = urllib.parse.urlsplit(page_url)
        if parsed.username is not None or parsed.password is not None:
            return False
        scheme = parsed.scheme.lower()
        if scheme != want_scheme:
            return False
        if scheme in ("http", "https"):
            if not parsed.hostname:
                return False
            port = parsed.port or (443 if scheme == "https" else 80)
            if parsed.hostname.lower() != want_host or port != want_port:
                return False
        elif parsed.netloc:
            return False
    except ValueError:
        return False
    page_path = parsed.path or "/"
    if want_path == "/":
        return True
    prefix = want_path.rstrip("/")
    return page_path == prefix or page_path.startswith(prefix + "/")


def handle_payload(payload, call):
    if not isinstance(payload, dict):
        return {"ok": False, "status": 400}
    route, body = payload.get("route"), payload.get("body")
    if route not in engine.ROUTES or not isinstance(body, dict) or isinstance(body, list):
        return {"ok": False, "status": 400}
    try:
        return {"ok": True, "body": call(route, body)}
    except engine.EngineError as error:
        return {"ok": False, "status": error.status}


class Page:
    def __init__(self, ws_url, engine_host, engine_port, token, session, long_press_ms, target_url):
        normalize_target_url(target_url)
        self.cdp = cdp.Cdp(ws_url)
        self.engine_host = engine_host
        self.engine_port = engine_port
        self.token = token
        self.session = session
        self.long_press_ms = long_press_ms
        self.target_url = target_url
        self._lock = threading.Lock()
        self._install_lock = threading.Lock()
        self._main_frame_id = None
        self._frame_url = ""
        self._context_id = None
        self._installed_loader = None
        self._binding_ready = False
        self.cdp.on_event(self._event)

    def alive(self):
        return not self.cdp._closed

    def call_engine(self, route, body):
        return engine.call(self.engine_host, self.engine_port, self.token, route, body)

    def _event(self, message):
        method = message.get("method")
        params = message.get("params") or {}
        if method == "Runtime.executionContextsCleared":
            with self._lock:
                self._context_id = None
                self._installed_loader = None
            return
        if method == "Runtime.executionContextDestroyed":
            destroyed = params.get("executionContextId")
            with self._lock:
                if destroyed == self._context_id:
                    self._context_id = None
                    self._installed_loader = None
            return
        if method == "Page.frameNavigated":
            frame = params.get("frame") or {}
            if frame.get("parentId"):
                return
            url = frame.get("url") or ""
            with self._lock:
                self._main_frame_id = frame.get("id")
                self._frame_url = url
                self._context_id = None
                self._installed_loader = None
            return
        if method == "Page.navigatedWithinDocument":
            frame_id = params.get("frameId")
            url = params.get("url") or ""
            with self._lock:
                if frame_id == self._main_frame_id:
                    self._frame_url = url
                    if not target_matches(url, self.target_url):
                        self._context_id = None
                        self._installed_loader = None
            return
        if method in ("Page.domContentEventFired", "Page.loadEventFired"):
            with self._lock:
                needs = self._context_id is None and target_matches(self._frame_url, self.target_url)
            if needs:
                threading.Thread(target=self._reinstall, daemon=True).start()
            return
        if method != "Runtime.bindingCalled" or params.get("name") != "openwizGhostBinding":
            return
        ctx_id = params.get("executionContextId")
        with self._lock:
            allowed = (
                self._context_id is not None
                and ctx_id == self._context_id
                and target_matches(self._frame_url, self.target_url)
            )
        if not allowed:
            return
        raw = params.get("payload")
        if not isinstance(raw, str) or len(raw) > engine.MAX_BODY:
            return
        threading.Thread(target=self._answer, args=(ctx_id, raw), daemon=True).start()

    def _reinstall(self):
        try:
            self.sync()
        except (OSError, TimeoutError, RuntimeError, ValueError):
            return

    def _answer(self, ctx_id, raw):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        result = handle_payload(payload, self.call_engine)
        ident = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(ident, str):
            return
        with self._lock:
            if self._context_id != ctx_id or not target_matches(self._frame_url, self.target_url):
                return
        expression = "globalThis.__openwizGhostResult(%s, %s)" % (json.dumps(ident), json.dumps(result))
        try:
            self.cdp.call("Runtime.evaluate", {"expression": expression, "contextId": ctx_id})
        except (OSError, TimeoutError, RuntimeError):
            return

    def boot(self):
        with self._install_lock:
            if not self._binding_ready:
                self.cdp.call("Page.enable")
                self.cdp.call("Runtime.enable")
                self.cdp.call("Runtime.addBinding", {
                    "name": "openwizGhostBinding",
                    "executionContextName": WORLD_NAME,
                })
                self._binding_ready = True
            self._install_locked()

    def sync(self):
        with self._install_lock:
            return self._install_locked()

    def _install_locked(self):
        tree = self.cdp.call("Page.getFrameTree")
        frame = (tree.get("frameTree") or {}).get("frame") or {}
        frame_id = frame.get("id")
        url = frame.get("url") or ""
        loader = frame.get("loaderId")
        if not isinstance(frame_id, str) or not target_matches(url, self.target_url):
            with self._lock:
                self._main_frame_id = frame_id if isinstance(frame_id, str) else None
                self._frame_url = url
                self._context_id = None
                self._installed_loader = None
            return False
        with self._lock:
            if self._context_id is not None and self._installed_loader == loader:
                return True
        world = self.cdp.call("Page.createIsolatedWorld", {
            "frameId": frame_id,
            "worldName": WORLD_NAME,
            "grantUniveralAccess": False,
        })
        ctx_id = world.get("executionContextId")
        if type(ctx_id) is not int:
            return False
        with self._lock:
            self._main_frame_id = frame_id
            self._frame_url = url
            self._context_id = ctx_id
            self._installed_loader = loader
        reply = self.cdp.call("Runtime.evaluate", {
            "expression": page_source(self.session, self.long_press_ms),
            "contextId": ctx_id,
        })
        if reply.get("exceptionDetails"):
            with self._lock:
                if self._context_id == ctx_id:
                    self._context_id = None
                    self._installed_loader = None
            return False
        return True

    def close(self):
        self.cdp.close()


def attach(ws_url, *, engine_port, token, session, target_url, long_press_ms=500, engine_host="127.0.0.1"):
    page = Page(ws_url, engine_host, engine_port, token, session, long_press_ms, target_url)
    page.boot()
    return page


def _targets(port, target_url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, list):
        raise RuntimeError("debug list refused")
    return [
        item for item in data
        if isinstance(item, dict)
        and item.get("type") == "page"
        and target_matches(item.get("url"), target_url)
    ]


def serve(debug_port, engine_port, token, session, target_url, *,
          long_press_ms=500, poll_interval=0.5, stop_event=None):
    normalize_target_url(target_url)
    seen = {}
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                targets = _targets(debug_port, target_url)
            except (OSError, json.JSONDecodeError, RuntimeError, ValueError):
                if stop_event is not None:
                    if stop_event.wait(poll_interval):
                        break
                else:
                    time.sleep(poll_interval)
                continue
            live_ids = set()
            for target in targets:
                ident = target.get("id")
                ws = target.get("webSocketDebuggerUrl")
                if not isinstance(ident, str) or not isinstance(ws, str):
                    continue
                live_ids.add(ident)
                page = seen.get(ident)
                if page is not None and page.alive():
                    try:
                        page.sync()
                    except (OSError, TimeoutError, RuntimeError, ValueError):
                        page.close()
                        seen.pop(ident, None)
                    continue
                if page is not None:
                    page.close()
                    seen.pop(ident, None)
                try:
                    seen[ident] = attach(
                        ws, engine_port=engine_port, token=token, session=session,
                        target_url=target_url, long_press_ms=long_press_ms,
                    )
                except (OSError, TimeoutError, RuntimeError, ValueError):
                    continue
            for stale in list(seen):
                if stale not in live_ids:
                    seen.pop(stale).close()
            if stop_event is not None:
                if stop_event.wait(poll_interval):
                    break
            else:
                time.sleep(poll_interval)
    finally:
        for page in seen.values():
            page.close()


def main(argv):
    parser = argparse.ArgumentParser(description="Inject OpenWiz ghost text into T3 Code.")
    parser.add_argument("--debug-port", type=int, required=True)
    parser.add_argument("--engine-port", type=int, required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument("--session", default="ses-syn-desktop")
    args = parser.parse_args(argv)
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    if token == "" or "\n" in token or args.session == "":
        print("inject: token file or session is empty", file=sys.stderr)
        return 2
    try:
        engine.build_url("127.0.0.1", args.engine_port, "complete")
    except ValueError:
        print("inject: engine port is not a loopback port", file=sys.stderr)
        return 2
    try:
        normalize_target_url(args.target_url)
    except ValueError:
        print("inject: target URL is invalid", file=sys.stderr)
        return 2
    print("inject: attached to the debugging port")
    serve(args.debug_port, args.engine_port, token, args.session, args.target_url)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
