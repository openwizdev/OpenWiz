import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine
import inject

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contracts/fixtures/ghost/recall-cases.json").read_text(encoding="utf-8"))
PAGE = (Path(__file__).resolve().parent / "fixtures/composer.html").read_text(encoding="utf-8")
TOKEN = "syn"
SESSION = "ses-syn-1"
CHARS = {
    ("typed_through", 1): 1,
    ("typed_through", 2): 1,
    ("word_accept_and_accept_all", 1): 2,
    ("word_accept_and_accept_all", 2): 4,
    ("word_accept_and_accept_all", 3): 5,
}
ZERO = {"shown", "dismissed", "typed_over"}


def fixture_table():
    table = {}
    for case in CASES["cases"]:
        for step in case["steps"]:
            if not step["expected_request"]:
                continue
            prefix, ghost = step["expected_text"], step["expected_ghost"]
            if prefix in table and table[prefix] != ghost:
                raise AssertionError("fixture prefixes disagree")
            table[prefix] = ghost
    table["syn"] = " thetic"
    table["slow"] = " NO"
    table["slowx"] = " yes"
    table["bad-shape"] = "nope"
    return table


class EngineServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.token = TOKEN
        self.table = fixture_table()
        self.ids = {}
        self.completes = []
        self.events = []
        self.slow_waiting = threading.Event()
        self.release_slow = threading.Event()
        self.slow_answered = threading.Event()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def do_GET(self):
        if self.path.startswith("/ghost/"):
            self._raw(404, b"")
            return
        self._raw(200, PAGE.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in (f"127.0.0.1:{port}", "127.0.0.1"):
            self._refuse(403, "host_not_allowed", "Host is not loopback.")
            return
        if "Origin" in self.headers:
            self._refuse(403, "origin_not_allowed", "Origin is not on the ghost.v1 allowlist.")
            return
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer " + self.server.token:
            code = "missing_token" if not auth.startswith("Bearer ") else "invalid_token"
            self._refuse(401, code, "Pairing token was refused.")
            return
        route = self.path.removeprefix("/ghost/v1/")
        if route not in ("complete", "feedback"):
            self._refuse(404, "unknown_route", "Route is not a ghost.v1 route.")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > engine.MAX_BODY:
            self._refuse(413, "payload_too_large", "Request body exceeds 1 MiB.")
            return
        raw = self.rfile.read(length)
        try:
            def unique(pairs):
                keys = [key for key, _ in pairs]
                if len(keys) != len(set(keys)):
                    raise ValueError("duplicate")
                return dict(pairs)
            body = json.loads(raw.decode(), object_pairs_hook=unique)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            self._refuse(400, "invalid_request", "Body is not one JSON object.")
            return
        if route == "complete":
            self._complete(body)
        else:
            self._feedback(body)

    def _complete(self, body):
        if not isinstance(body, dict) or set(body) != {"session_id", "surface", "prefix", "seq"}:
            self._refuse(400, "invalid_request", "Body is not a complete request.")
            return
        if body["surface"] != "t3-code" or not isinstance(body["prefix"], str):
            self._refuse(400, "invalid_request", "Body is not a complete request.")
            return
        if type(body["seq"]) is not int or body["seq"] < 0:
            self._refuse(400, "invalid_request", "Body is not a complete request.")
            return
        prefix = body["prefix"]
        self.server.completes.append({
            "prefix": prefix, "surface": body["surface"], "seq": body["seq"],
            "session_id": body["session_id"], "origin": self.headers.get("Origin"),
        })
        if prefix == "slow":
            self.server.slow_waiting.set()
            if not self.server.release_slow.wait(5):
                self._refuse(503, "unavailable", "The held reply was not released.")
                return
            self.server.slow_answered.set()
        if prefix == "dup":
            raw = (
                b'{"schema":"openwiz.ghost.v1","schema":"openwiz.ghost.v1","seq":'
                + str(body["seq"]).encode() + b',"suggestion":null}'
            )
            self._raw(200, raw)
            return
        ghost = self.server.table.get(prefix)
        suggestion = None
        if ghost:
            if prefix not in self.server.ids:
                self.server.ids[prefix] = f"sug-syn-{len(self.server.ids) + 1}"
            suggestion = {
                "id": self.server.ids[prefix], "text": ghost, "full_text": prefix + ghost,
                "tier": "recall", "confidence": 0.91, "latency_ms": 1,
            }
            if prefix == "bad-shape":
                suggestion["full_text"] = "wrong"
        self._json(200, {"schema": "openwiz.ghost.v1", "seq": body["seq"], "suggestion": suggestion})

    def _feedback(self, body):
        if not isinstance(body, dict) or body.get("schema") != "openwiz.ghost.v1":
            self._refuse(400, "invalid_request", "Body is not an event.")
            return
        self.server.events.append(body)
        self._json(200, {"schema": "openwiz.ghost.v1", "recorded": True, "logged": False})

    def _refuse(self, status, code, message):
        self._json(status, {"refusal": {"code": code, "message": message}})

    def _json(self, status, obj):
        self._raw(status, json.dumps(obj, separators=(",", ":")).encode())

    def _raw(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GuardTests(unittest.TestCase):
    def test_non_loopback_host_is_refused_before_connect(self):
        for host in ("example.com", "0.0.0.0", "localhost"):
            with self.assertRaises(ValueError):
                engine.call(host, 9, TOKEN, "complete", {"prefix": "J1"})

    def test_unknown_route_is_refused_before_connect(self):
        with self.assertRaises(ValueError):
            engine.build_url("127.0.0.1", 17417, "pair")

    def test_duplicate_key_is_refused(self):
        server = EngineServer()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaises(engine.EngineError):
                engine.call("127.0.0.1", server.server_address[1], TOKEN, "complete", {
                    "session_id": SESSION, "surface": "t3-code", "prefix": "dup", "seq": 1,
                })
        finally:
            server.shutdown()
            server.server_close()

    def test_proxy_env_is_not_used_for_loopback(self):
        server = EngineServer()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        old = {name: os.environ.get(name) for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY")}
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
        os.environ["http_proxy"] = "http://127.0.0.1:9"
        os.environ["ALL_PROXY"] = "http://127.0.0.1:9"
        try:
            body = engine.call("127.0.0.1", server.server_address[1], TOKEN, "complete", {
                "session_id": SESSION, "surface": "t3-code", "prefix": "zzq", "seq": 1,
            })
            self.assertIsNone(body["suggestion"])
            self.assertEqual(server.completes[0]["origin"], None)
        finally:
            for name, value in old.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            server.shutdown()
            server.server_close()

    def test_bad_route_payload_does_not_call_the_engine(self):
        called = []
        result = inject.handle_payload({"route": "pair", "body": {}}, lambda route, body: called.append(route))
        self.assertFalse(result["ok"])
        self.assertEqual(called, [])


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        cls.debug_port = sock.getsockname()[1]
        sock.close()
        cls.chrome = subprocess.Popen([
            "google-chrome", "--headless=new", f"--remote-debugging-port={cls.debug_port}",
            f"--user-data-dir={cls.tmp.name}", "--no-first-run", "--no-default-browser-check",
            "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
            "--remote-allow-origins=*", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 15
        cls.ws = None
        while time.monotonic() < deadline and cls.ws is None:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cls.debug_port}/json/list", timeout=0.5) as res:
                    pages = json.loads(res.read().decode())
                cls.ws = next(item["webSocketDebuggerUrl"] for item in pages if item.get("type") == "page")
            except (OSError, json.JSONDecodeError, KeyError, StopIteration):
                time.sleep(0.1)
        if cls.ws is None:
            cls.chrome.kill()
            raise RuntimeError("chrome did not open a page")

    @classmethod
    def tearDownClass(cls):
        cls.chrome.terminate()
        cls.chrome.wait(timeout=5)
        cls.tmp.cleanup()

    def setUp(self):
        self.server = EngineServer()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        port = self.server.server_address[1]
        self.page = inject.Page(self.ws, "127.0.0.1", port, TOKEN, SESSION, 80)
        self.page.cdp.call("Page.enable")
        self.n = 0
        self.reload()

    def reload(self):
        self.n += 1
        port = self.server.server_address[1]
        marker = f"n={self.n}"
        self.page.cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/?{marker}"})
        self.wait_until(lambda: marker in (self.eval("String(location.search)") or "")
                        and self.eval("document.readyState") == "complete"
                        and self.eval("document.querySelector('[data-testid=\"composer-editor\"]')") is not None
                        and self.eval("document.documentElement.dataset.openwizGhost") != "on")
        self.page.boot()
        self.wait_until(lambda: self.eval("document.documentElement.dataset.openwizGhost") == "on")
        self.server.completes.clear()
        self.server.events.clear()

    def tearDown(self):
        self.page.close()
        self.server.shutdown()
        self.server.server_close()

    def eval(self, expression):
        result = self.page.cdp.call("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
        })
        if result.get("exceptionDetails"):
            raise AssertionError("page evaluation failed")
        return result.get("result", {}).get("value")

    def wait_until(self, pred, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if pred():
                return
            time.sleep(0.02)
        raise AssertionError("timed out waiting for the composer")

    def settled(self):
        return int(self.eval("document.documentElement.dataset.openwizSettled || '0'"))

    def composer(self):
        return self.eval(
            "(function(){var e=document.querySelector('[data-testid=\"composer-editor\"]');"
            "var r=document.createRange();r.selectNodeContents(e);return r.toString();})()")

    def ghost(self):
        return self.eval(
            "(function(){var h=document.getElementById('openwiz-ghost-host');"
            "var s=h&&h.shadowRoot&&h.shadowRoot.querySelector('[data-ghost]');"
            "return s&&s.textContent?s.textContent:null;})()")

    def insert(self, text):
        ok = self.eval(
            "(function(t){var e=document.querySelector('[data-testid=\"composer-editor\"]');"
            "e.focus();return document.execCommand('insertText', false, t);})(" + json.dumps(text) + ")")
        self.assertTrue(ok)

    def key(self, name, code, modifiers=0):
        self.eval("document.querySelector('[data-testid=\"composer-editor\"]').focus()")
        for kind in ("keyDown", "keyUp"):
            self.page.cdp.call("Input.dispatchKeyEvent", {
                "type": kind, "key": name, "code": name, "windowsVirtualKeyCode": code,
                "nativeVirtualKeyCode": code, "modifiers": modifiers,
            })

    def act(self, step):
        before = self.settled()
        action = step["action"]
        if action == "type":
            self.insert(step["input"])
        elif action == "accept_word":
            self.key("ArrowRight", 39)
        elif action == "accept_all":
            self.key("Tab", 9)
        elif action == "dismiss":
            self.key("Escape", 27)
        else:
            raise AssertionError("unknown action")
        self.wait_until(lambda: self.settled() > before)

    def test_golden_recall_cases_show_in_the_composer(self):
        recorded = []
        for case in CASES["cases"]:
            self.reload()
            for index, step in enumerate(case["steps"]):
                reqs, evs = len(self.server.completes), len(self.server.events)
                self.act(step)
                self.assertEqual(self.composer(), step["expected_text"], case["name"])
                self.assertEqual(self.ghost(), step["expected_ghost"], case["name"])
                new_reqs = self.server.completes[reqs:]
                if step["expected_request"]:
                    self.assertEqual(len(new_reqs), 1, case["name"])
                    self.assertEqual(new_reqs[0]["prefix"], step["expected_text"])
                    self.assertEqual(new_reqs[0]["surface"], "t3-code")
                    self.assertEqual(new_reqs[0]["session_id"], SESSION)
                    self.assertIsNone(new_reqs[0]["origin"])
                else:
                    self.assertEqual(new_reqs, [], case["name"])
                new_evs = self.server.events[evs:]
                self.assertEqual([item["outcome"] for item in new_evs], step["expected_events"], case["name"])
                for item in new_evs:
                    if item["outcome"] in ZERO:
                        self.assertEqual(item["chars_accepted"], 0, case["name"])
                    else:
                        self.assertEqual(item["chars_accepted"], CHARS[(case["name"], index)], case["name"])
                    self.assertEqual(item["surface"], "t3-code")
                recorded.append({
                    "case": case["name"], "text": self.composer(), "ghost": self.ghost(),
                    "requests": len(new_reqs), "outcomes": [item["outcome"] for item in new_evs],
                })
        print("recorded " + json.dumps(recorded, separators=(",", ":")))

    def test_server_text_is_what_shows(self):
        self.insert("syn")
        self.wait_until(lambda: self.ghost() == " thetic")
        self.assertEqual(self.composer(), "syn")
        self.assertEqual(len(self.server.completes), 1)

    def test_stale_reply_is_dropped(self):
        self.insert("slow")
        self.wait_until(lambda: self.server.slow_waiting.is_set())
        self.insert("x")
        self.wait_until(lambda: any(item["prefix"] == "slowx" for item in self.server.completes))
        self.server.release_slow.set()
        self.wait_until(lambda: self.eval("document.documentElement.dataset.openwizDropped") not in (None, ""))
        self.assertEqual(self.ghost(), " yes")
        self.assertEqual(self.composer(), "slowx")

    def test_bad_suggestion_shape_shows_nothing(self):
        before = self.settled()
        self.insert("bad-shape")
        self.wait_until(lambda: self.settled() > before)
        self.assertEqual(self.composer(), "bad-shape")
        self.assertIsNone(self.ghost())

    def test_duplicate_response_key_shows_nothing(self):
        before = self.settled()
        self.insert("dup")
        self.wait_until(lambda: self.settled() > before)
        self.assertIsNone(self.ghost())
        self.assertEqual(self.composer(), "dup")

    def test_tab_without_a_ghost_moves_focus(self):
        self.eval("document.querySelector('[data-testid=\"composer-editor\"]').focus()")
        self.key("Tab", 9)
        self.wait_until(lambda: self.eval("document.activeElement && document.activeElement.id") == "after")

    def test_shift_tab_is_not_taken(self):
        before = self.settled()
        self.insert("J1")
        self.wait_until(lambda: self.settled() > before and self.ghost() == " all recs")
        self.key("Tab", 9, modifiers=8)
        self.wait_until(lambda: self.eval("document.activeElement && document.activeElement.id") == "before")
        self.assertEqual(self.composer(), "J1")

    def test_enter_does_not_accept(self):
        before = self.settled()
        self.insert("J1")
        self.wait_until(lambda: self.settled() > before and self.ghost() == " all recs")
        self.eval("window.__enterPrevented = null;"
                  "document.querySelector('[data-testid=\"composer-editor\"]').addEventListener('keydown',"
                  "function(e){ if (e.key === 'Enter') window.__enterPrevented = e.defaultPrevented; });")
        self.key("Enter", 13)
        self.wait_until(lambda: self.eval("window.__enterPrevented") is False)
        self.assertNotIn("all recs", self.composer())
        self.assertNotIn("accepted_all", [item["outcome"] for item in self.server.events])

    def test_composing_tab_is_not_taken(self):
        before = self.settled()
        self.insert("J1")
        self.wait_until(lambda: self.settled() > before and self.ghost() == " all recs")
        prevented = self.eval(
            "(function(){var e=document.querySelector('[data-testid=\"composer-editor\"]');"
            "var ev=new KeyboardEvent('keydown',{key:'Tab',bubbles:true,cancelable:true,isComposing:true});"
            "e.dispatchEvent(ev);return ev.defaultPrevented;})()")
        self.assertIs(prevented, False)
        self.assertEqual(self.composer(), "J1")
        self.assertEqual(self.ghost(), " all recs")

    def test_word_accept_keeps_the_leading_space(self):
        before = self.settled()
        self.insert("J1")
        self.wait_until(lambda: self.settled() > before and self.ghost() == " all recs")
        before = self.settled()
        self.key("ArrowRight", 39)
        self.wait_until(lambda: self.settled() > before)
        self.assertEqual(self.composer(), "J1 all ")
        self.assertEqual(self.ghost(), "recs")
        self.assertEqual(self.server.events[-1]["outcome"], "accepted_word")
        self.assertEqual(self.server.events[-1]["chars_accepted"], 5)

    def test_tap_accepts_a_word_and_long_press_accepts_all(self):
        before = self.settled()
        self.insert("approve #4")
        self.wait_until(lambda: self.settled() > before and self.ghost() == "2 and merge")
        before = self.settled()
        self.eval(
            "(function(){var s=document.getElementById('openwiz-ghost-host').shadowRoot"
            ".querySelector('[data-ghost]');"
            "s.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1,pointerType:'touch'}));"
            "s.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1,pointerType:'touch'}));})()")
        self.wait_until(lambda: self.settled() > before)
        self.assertEqual(self.composer(), "approve #42 ")
        self.assertEqual(self.ghost(), "and merge")
        self.reload()
        before = self.settled()
        self.insert("J1")
        self.wait_until(lambda: self.settled() > before and self.ghost() == " all recs")
        shown = self.settled()
        self.eval(
            "(function(){var s=document.getElementById('openwiz-ghost-host').shadowRoot"
            ".querySelector('[data-ghost]');"
            "s.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:2,pointerType:'touch'}));})()")
        self.wait_until(lambda: self.settled() > shown and self.composer() == "J1 all recs")
        self.assertIsNone(self.ghost())
        self.assertEqual(self.server.events[-1]["outcome"], "accepted_all")


if __name__ == "__main__":
    unittest.main()
