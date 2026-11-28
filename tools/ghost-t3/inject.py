import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp
import engine

ROOT = Path(__file__).resolve().parent
SIDECAR = (ROOT / "sidecar.js").read_text(encoding="utf-8")
BRIDGE = """
globalThis.__openwizGhostPending = new Map();
globalThis.__openwizGhostCall = (route, body) => new Promise((resolve) => {
  const id = String(globalThis.__openwizGhostPending.size + 1) + ":" + String(Date.now());
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
    def __init__(self, ws_url, engine_host, engine_port, token, session, long_press_ms):
        self.cdp = cdp.Cdp(ws_url)
        self.engine_host = engine_host
        self.engine_port = engine_port
        self.token = token
        self.session = session
        self.long_press_ms = long_press_ms
        self.cdp.on_event(self._event)

    def call_engine(self, route, body):
        return engine.call(self.engine_host, self.engine_port, self.token, route, body)

    def _event(self, message):
        if message.get("method") != "Runtime.bindingCalled":
            return
        params = message.get("params") or {}
        if params.get("name") != "openwizGhostBinding":
            return
        raw = params.get("payload")
        if not isinstance(raw, str) or len(raw) > engine.MAX_BODY:
            return
        threading.Thread(target=self._answer, args=(raw,), daemon=True).start()

    def _answer(self, raw):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        result = handle_payload(payload, self.call_engine)
        ident = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(ident, str):
            return
        expression = "globalThis.__openwizGhostResult(%s, %s)" % (json.dumps(ident), json.dumps(result))
        try:
            self.cdp.call("Runtime.evaluate", {"expression": expression})
        except (OSError, TimeoutError, RuntimeError):
            return

    def boot(self):
        try:
            self.cdp.call("Runtime.enable")
            self.cdp.call("Runtime.addBinding", {"name": "openwizGhostBinding"})
        except RuntimeError:
            pass
        self.cdp.call("Runtime.evaluate", {"expression": page_source(self.session, self.long_press_ms)})

    def close(self):
        self.cdp.close()


def attach(ws_url, *, engine_port, token, session, long_press_ms=500, engine_host="127.0.0.1"):
    page = Page(ws_url, engine_host, engine_port, token, session, long_press_ms)
    page.boot()
    return page


def _targets(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as response:
        data = json.loads(response.read().decode())
    if not isinstance(data, list):
        raise RuntimeError("debug list refused")
    return [item for item in data if isinstance(item, dict) and item.get("type") == "page"]


def serve(debug_port, engine_port, token, session):
    seen = {}
    while True:
        try:
            targets = _targets(debug_port)
        except (OSError, json.JSONDecodeError, RuntimeError, ValueError):
            time.sleep(0.5)
            continue
        for target in targets:
            ident = target.get("id")
            ws = target.get("webSocketDebuggerUrl")
            if not isinstance(ident, str) or not isinstance(ws, str) or ident in seen:
                continue
            try:
                seen[ident] = attach(ws, engine_port=engine_port, token=token, session=session)
            except (OSError, TimeoutError, RuntimeError, ValueError):
                continue
        time.sleep(0.5)


def main(argv):
    parser = argparse.ArgumentParser(description="Inject OpenWiz ghost text into T3 Code.")
    parser.add_argument("--debug-port", type=int, required=True)
    parser.add_argument("--engine-port", type=int, required=True)
    parser.add_argument("--token-file", required=True)
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
    print("inject: attached to the debugging port")
    serve(args.debug_port, args.engine_port, token, args.session)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
