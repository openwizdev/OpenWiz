import contextlib, json, os, shutil, socket, subprocess, sys, tempfile, threading, time, unittest, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cdp, engine, inject

DIR = Path(__file__).resolve().parent
ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contracts/fixtures/ghost/recall-cases.json").read_text(encoding="utf-8"))
PAGE = (DIR / "fixtures/composer.html").read_text(encoding="utf-8")
TOKEN, SESSION = "syn", "ses-syn-1"
CHARS = {("typed_through", 1): 1, ("typed_through", 2): 1, ("word_accept_and_accept_all", 1): 2,
         ("word_accept_and_accept_all", 2): 4, ("word_accept_and_accept_all", 3): 5}
ZERO = {"shown", "dismissed", "typed_over"}
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
GHOST_JS = "document.getElementById('openwiz-ghost-host')?.shadowRoot?.querySelector('[data-ghost]')?.textContent || null"
COMP_JS = "(function(s){var e=document.querySelector(s);if(!e)return null;var r=document.createRange();r.selectNodeContents(e);return r.toString();})"
INS_JS = "(function(t){var e=document.querySelector('[data-testid=\"composer-editor\"]');e.focus();return document.execCommand('insertText',false,t);})"


def chrome_bin():
    for name in ("google-chrome", "chromium", "chromium-browser"):
        if found := shutil.which(name): return found
    raise RuntimeError("no chrome binary found")


def list_targets(debug_port):
    with OPENER.open(f"http://127.0.0.1:{debug_port}/json/list", timeout=2) as res:
        return json.loads(res.read().decode())


@contextlib.contextmanager
def chrome_session(extra_args=(), start_url="about:blank"):
    tmp = tempfile.TemporaryDirectory()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); debug_port = sock.getsockname()[1]
    proc = subprocess.Popen([
        chrome_bin(), "--headless=new", f"--remote-debugging-port={debug_port}", f"--user-data-dir={tmp.name}",
        "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--no-sandbox",
        "--disable-dev-shm-usage", "--remote-allow-origins=*", *extra_args, start_url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        wait_until(lambda: any(item.get("type") == "page" for item in _safe_targets(debug_port)), timeout=15)
        yield debug_port
    finally:
        proc.terminate(); proc.wait(timeout=5); tmp.cleanup()


def _safe_targets(debug_port):
    try: return list_targets(debug_port)
    except (OSError, json.JSONDecodeError, KeyError): return []


def wait_until(pred, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred(): return
        time.sleep(0.02)
    raise AssertionError("timed out waiting for the composer")


def cdp_eval(conn, expression):
    result = conn.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
    if result.get("exceptionDetails"): raise AssertionError("page evaluation failed")
    return result.get("result", {}).get("value")


def dispatch_key(conn, name, code, modifiers=0):
    for kind in ("keyDown", "keyUp"):
        conn.call("Input.dispatchKeyEvent", {"type": kind, "key": name, "code": name,
                  "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code, "modifiers": modifiers})


def fixture_table():
    table = {}
    for case in CASES["cases"]:
        for step in case["steps"]:
            if not step["expected_request"]: continue
            prefix, ghost = step["expected_text"], step["expected_ghost"]
            if prefix in table and table[prefix] != ghost: raise AssertionError("fixture prefixes disagree")
            table[prefix] = ghost
    table.update({"syn": " thetic", "slow": " NO", "slowx": " yes", "bad-shape": "nope"})
    return table


class EngineServer(ThreadingHTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.token, self.table, self.ids = TOKEN, fixture_table(), {}
        self.completes, self.events, self.refusals, self.hold_feedback = [], [], [], False
        self.slow_waiting, self.release_slow, self.slow_answered = (threading.Event() for _ in range(3))
        self.feedback_waiting, self.release_feedback = threading.Event(), threading.Event()


@contextlib.contextmanager
def running_server(cls=EngineServer):
    server = cls()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try: yield server
    finally: server.shutdown(); server.server_close()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    log_message = lambda self, fmt, *args: None

    def do_GET(self):
        self._raw(404, b"") if self.path.startswith("/ghost/") else self._raw(200, PAGE.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in (f"127.0.0.1:{port}", "127.0.0.1"):
            return self._refuse(403, "host_not_allowed", "Host is not loopback.")
        if "Origin" in self.headers:
            return self._refuse(403, "origin_not_allowed", "Origin is not on the ghost.v1 allowlist.")
        auth = self.headers.get("Authorization", "")
        if auth != "Bearer " + self.server.token:
            return self._refuse(401, "missing_token" if not auth.startswith("Bearer ") else "invalid_token", "Pairing token was refused.")
        route = self.path.removeprefix("/ghost/v1/")
        if route not in ("complete", "feedback"):
            return self._refuse(404, "unknown_route", "Route is not a ghost.v1 route.")
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > engine.MAX_BODY:
            return self._refuse(413, "payload_too_large", "Request body exceeds 1 MiB.")
        try:
            def unique(pairs):
                if len(pairs) != len({k for k, _ in pairs}):
                    raise ValueError("duplicate")
                return dict(pairs)
            body = json.loads(self.rfile.read(length).decode(), object_pairs_hook=unique)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return self._refuse(400, "invalid_request", "Body is not one JSON object.")
        self._complete(body) if route == "complete" else self._feedback(body)

    def _complete(self, body):
        if (not isinstance(body, dict) or set(body) != {"session_id", "surface", "prefix", "seq"}
                or body["surface"] != "t3-code" or not isinstance(body["prefix"], str)
                or type(body["seq"]) is not int or body["seq"] < 0):
            return self._refuse(400, "invalid_request", "Body is not a complete request.")
        prefix = body["prefix"]
        self.server.completes.append({"prefix": prefix, "surface": body["surface"], "seq": body["seq"],
                                      "session_id": body["session_id"], "origin": self.headers.get("Origin")})
        if prefix == "slow":
            self.server.slow_waiting.set()
            if not self.server.release_slow.wait(5):
                return self._refuse(503, "unavailable", "The held reply was not released.")
            self.server.slow_answered.set()
        if prefix == "dup":
            raw = b'{"schema":"openwiz.ghost.v1","schema":"openwiz.ghost.v1","seq":' + str(body["seq"]).encode() + b',"suggestion":null}'
            return self._raw(200, raw)
        ghost, suggestion = self.server.table.get(prefix), None
        if ghost:
            sid = self.server.ids.setdefault(prefix, f"sug-syn-{len(self.server.ids) + 1}")
            suggestion = {"id": sid, "text": ghost, "full_text": "wrong" if prefix == "bad-shape" else prefix + ghost,
                          "tier": "recall", "confidence": 0.91, "latency_ms": 1}
        self._json(200, {"schema": "openwiz.ghost.v1", "seq": body["seq"], "suggestion": suggestion})

    def _feedback(self, body):
        if not isinstance(body, dict) or body.get("schema") != "openwiz.ghost.v1":
            return self._refuse(400, "invalid_request", "Body is not an event.")
        if self.server.hold_feedback and body.get("outcome") == "dismissed":
            self.server.feedback_waiting.set()
            self.server.release_feedback.wait(5)
        self.server.events.append(body)
        self._json(200, {"schema": "openwiz.ghost.v1", "recorded": True, "logged": False})

    def _refuse(self, status, code, message):
        self.server.refusals.append((status, code, self.headers.get("Origin")))
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
    def test_host_route_payload_and_target_guards(self):
        for host in ("example.com", "0.0.0.0", "localhost"):
            with self.assertRaises(ValueError):
                engine.call(host, 9, TOKEN, "complete", {"prefix": "J1"})
        with self.assertRaises(ValueError):
            engine.build_url("127.0.0.1", 17417, "pair")
        called = []
        result = inject.handle_payload({"route": "pair", "body": {}}, lambda route, body: called.append(route))
        self.assertEqual((result["ok"], called), (False, []))
        self.assertTrue(inject.target_matches("http://127.0.0.1:3773/app/chat?x=1", "http://127.0.0.1:3773/app"))
        for bad in ("http://127.0.0.1:3773/app2", "http://127.0.0.1:3774/app", "https://evil.example/app", "about:blank"):
            self.assertFalse(inject.target_matches(bad, "http://127.0.0.1:3773/app"))

    def test_duplicate_key_and_proxy_env(self):
        with running_server() as server:
            with self.assertRaises(engine.EngineError):
                engine.call("127.0.0.1", server.server_address[1], TOKEN, "complete",
                            {"session_id": SESSION, "surface": "t3-code", "prefix": "dup", "seq": 1})
            old = {k: os.environ.get(k) for k in ("HTTP_PROXY", "http_proxy", "ALL_PROXY")}
            os.environ.update({k: "http://127.0.0.1:9" for k in old})
            try:
                body = engine.call("127.0.0.1", server.server_address[1], TOKEN, "complete",
                                   {"session_id": SESSION, "surface": "t3-code", "prefix": "zzq", "seq": 1})
                self.assertEqual((body["suggestion"], server.completes[-1]["origin"]), (None, None))
            finally:
                for k, v in old.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)

    def test_redirects_are_refused_and_token_never_follows(self):
        leaked, code_box = [], [302]

        class Sink(BaseHTTPRequestHandler):
            log_message = lambda self, *a: None
            def do_GET(self):
                leaked.append((self.command, self.headers.get("Authorization")))
                self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"{}")
            do_POST = do_GET

        with running_server(lambda: ThreadingHTTPServer(("127.0.0.1", 0), Sink)) as sink:
            loc = f"http://127.0.0.1:{sink.server_address[1]}/steal"

            class Redir(BaseHTTPRequestHandler):
                log_message = lambda self, *a: None
                def do_POST(self):
                    self.send_response(code_box[0]); self.send_header("Location", loc); self.send_header("Content-Length", "0"); self.end_headers()

            with running_server(lambda: ThreadingHTTPServer(("127.0.0.1", 0), Redir)) as redir:
                for status in (301, 302, 303, 307, 308):
                    code_box[0] = status
                    with self.subTest(status=status), self.assertRaises(engine.EngineError) as caught:
                        engine.call("127.0.0.1", redir.server_address[1], TOKEN, "complete",
                                    {"session_id": SESSION, "surface": "t3-code", "prefix": "J1", "seq": 1})
                    self.assertEqual((caught.exception.status, leaked), (status, []))


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.debug_port = cls.stack.enter_context(chrome_session())
        cls.ws = next(t["webSocketDebuggerUrl"] for t in list_targets(cls.debug_port) if t.get("type") == "page")

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self.server = EngineServer()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        port = self.server.server_address[1]
        self.page = inject.Page(self.ws, "127.0.0.1", port, TOKEN, SESSION, 80, f"http://127.0.0.1:{port}/")
        self.page.boot()
        self.n = 0
        self.reload()

    def reload(self):
        self.n += 1
        marker = f"n={self.n}"
        self.page.cdp.call("Page.navigate", {"url": f"http://127.0.0.1:{self.server.server_address[1]}/?{marker}"})
        wait_until(lambda: marker in (self.eval("String(location.search)") or "")
                   and self.eval("document.readyState") == "complete"
                   and self.eval("document.querySelector('[data-testid=\"composer-editor\"]')") is not None
                   and self.eval("document.documentElement.dataset.openwizGhost") == "on")
        for items in (self.server.completes, self.server.events, self.server.refusals):
            items.clear()
        self.server.hold_feedback = False
        self.server.feedback_waiting.clear(); self.server.release_feedback.clear()

    def tearDown(self):
        self.page.close(); self.server.shutdown(); self.server.server_close()

    def eval(self, expr): return cdp_eval(self.page.cdp, expr)
    def settled(self): return int(self.eval("document.documentElement.dataset.openwizSettled || '0'"))
    def composer(self, sel='[data-testid="composer-editor"]'): return self.eval(f"{COMP_JS}({json.dumps(sel)})")
    def ghost(self): return self.eval(GHOST_JS)
    def insert(self, text): self.assertTrue(self.eval(f"{INS_JS}({json.dumps(text)})"))

    def key(self, name, code, modifiers=0, focus=True):
        if focus:
            self.eval("document.querySelector('[data-testid=\"composer-editor\"]').focus()")
        dispatch_key(self.page.cdp, name, code, modifiers)

    def show(self, prefix, expected):
        before = self.settled()
        self.insert(prefix)
        wait_until(lambda: self.settled() > before and self.ghost() == expected)

    def act(self, step):
        before, action = self.settled(), step["action"]
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
        wait_until(lambda: self.settled() > before)

    def test_golden_recall_cases_show_in_the_composer(self):
        recorded = []
        for case in CASES["cases"]:
            self.reload()
            for index, step in enumerate(case["steps"]):
                reqs, evs = len(self.server.completes), len(self.server.events)
                self.act(step)
                self.assertEqual((self.composer(), self.ghost()), (step["expected_text"], step["expected_ghost"]), case["name"])
                new_reqs = self.server.completes[reqs:]
                if step["expected_request"]:
                    self.assertEqual(len(new_reqs), 1, case["name"])
                    self.assertEqual((new_reqs[0]["prefix"], new_reqs[0]["surface"], new_reqs[0]["session_id"], new_reqs[0]["origin"]),
                                     (step["expected_text"], "t3-code", SESSION, None))
                else:
                    self.assertEqual(new_reqs, [], case["name"])
                new_evs = self.server.events[evs:]
                self.assertEqual([item["outcome"] for item in new_evs], step["expected_events"], case["name"])
                for item in new_evs:
                    expected_chars = 0 if item["outcome"] in ZERO else CHARS[(case["name"], index)]
                    self.assertEqual((item["chars_accepted"], item["surface"]), (expected_chars, "t3-code"), case["name"])
                recorded.append({"case": case["name"], "text": self.composer(), "ghost": self.ghost(),
                                 "requests": len(new_reqs), "outcomes": [item["outcome"] for item in new_evs]})
        print("recorded " + json.dumps(recorded, separators=(",", ":")))

    def test_server_text_is_what_shows(self):
        self.insert("syn"); wait_until(lambda: self.ghost() == " thetic")
        self.assertEqual((self.composer(), len(self.server.completes)), ("syn", 1))

    def test_stale_reply_is_dropped(self):
        self.insert("slow"); wait_until(self.server.slow_waiting.is_set)
        self.insert("x"); wait_until(lambda: any(item["prefix"] == "slowx" for item in self.server.completes))
        self.server.release_slow.set()
        wait_until(lambda: self.eval("document.documentElement.dataset.openwizDropped") not in (None, ""))
        self.assertEqual((self.ghost(), self.composer()), (" yes", "slowx"))

    def test_bad_and_duplicate_responses_show_nothing(self):
        for prefix in ("bad-shape", "dup"):
            self.reload()
            before = self.settled(); self.insert(prefix); wait_until(lambda: self.settled() > before)
            self.assertEqual((self.composer(), self.ghost()), (prefix, None))

    def test_tab_shift_tab_enter_and_composing_rules(self):
        self.eval("document.querySelector('#editor').focus()"); self.key("Tab", 9)
        wait_until(lambda: self.eval("document.activeElement && document.activeElement.id") == "after")
        self.reload(); self.show("J1", " all recs"); self.key("Tab", 9, modifiers=8)
        wait_until(lambda: self.eval("document.activeElement && document.activeElement.id") == "before")
        self.assertEqual(self.composer(), "J1")
        self.reload(); self.show("J1", " all recs")
        self.eval("window.__enterPrevented=null;document.querySelector('#editor').addEventListener('keydown',"
                  "function(e){if(e.key==='Enter')window.__enterPrevented=e.defaultPrevented;});")
        self.key("Enter", 13); wait_until(lambda: self.eval("window.__enterPrevented") is False)
        self.assertNotIn("all recs", self.composer())
        self.assertNotIn("accepted_all", [item["outcome"] for item in self.server.events])
        self.reload(); self.show("J1", " all recs")
        prevented = self.eval("(function(){var e=document.querySelector('#editor'),ev=new KeyboardEvent('keydown',"
                              "{key:'Tab',bubbles:true,cancelable:true,isComposing:true});e.dispatchEvent(ev);return ev.defaultPrevented;})()")
        self.assertEqual((prevented, self.composer(), self.ghost()), (False, "J1", " all recs"))

    def test_word_accept_keeps_the_leading_space(self):
        self.show("J1", " all recs")
        before = self.settled(); self.key("ArrowRight", 39); wait_until(lambda: self.settled() > before)
        self.assertEqual((self.composer(), self.ghost(), self.server.events[-1]["outcome"],
                          self.server.events[-1]["chars_accepted"]), ("J1 all ", "recs", "accepted_word", 5))

    def test_tap_accepts_a_word_and_long_press_accepts_all(self):
        self.show("approve #4", "2 and merge")
        before = self.settled()
        self.eval("(function(){var s=document.getElementById('openwiz-ghost-host').shadowRoot.querySelector('[data-ghost]');"
                  "s.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:1,pointerType:'touch'}));"
                  "s.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:1,pointerType:'touch'}));})()")
        wait_until(lambda: self.settled() > before)
        self.assertEqual((self.composer(), self.ghost()), ("approve #42 ", "and merge"))
        self.reload(); self.show("J1", " all recs"); shown = self.settled()
        self.eval("document.getElementById('openwiz-ghost-host').shadowRoot.querySelector('[data-ghost]')"
                  ".dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:2,pointerType:'touch'}))")
        wait_until(lambda: self.settled() > shown and self.composer() == "J1 all recs")
        self.assertEqual((self.ghost(), self.server.events[-1]["outcome"]), (None, "accepted_all"))

    def test_selection_and_composer_changes_invalidate_ghost(self):
        self.show("J1", " all recs")
        self.eval("(function(){var e=document.querySelector('#editor'),r=document.createRange(),s=getSelection();"
                  "r.selectNodeContents(e);s.removeAllRanges();s.addRange(r);})()")
        wait_until(lambda: self.ghost() is None)
        self.key("Tab", 9, focus=False)
        wait_until(lambda: self.eval("document.activeElement && document.activeElement.id") == "after")
        self.assertEqual(self.composer(), "J1")
        self.reload(); self.show("J1", " all recs")
        self.eval("(function(){var e=document.querySelector('#editor'),r=document.createRange(),s=getSelection();"
                  "r.setStart(e.firstChild,1);r.collapse(true);s.removeAllRanges();s.addRange(r);})()")
        wait_until(lambda: self.ghost() is None); self.key("Tab", 9, focus=False)
        self.assertEqual(self.composer(), "J1")
        self.reload()
        self.eval("(function(){var d=document.createElement('div');d.id='editor2';d.contentEditable='true';"
                  "d.setAttribute('data-testid','composer-editor');document.body.appendChild(d);})()")
        self.show("J1", " all recs"); self.eval("document.getElementById('editor2').focus()")
        wait_until(lambda: self.ghost() is None); self.key("Tab", 9, focus=False)
        self.assertEqual((self.composer("#editor"), self.composer("#editor2")), ("J1", ""))

    def test_esc_clears_before_feedback_and_resumes_after_trailing_space(self):
        self.show("J1", " all recs")
        self.server.hold_feedback = True
        self.key("Escape", 27); wait_until(self.server.feedback_waiting.is_set)
        self.assertIsNone(self.ghost())
        self.key("Tab", 9, focus=False); self.server.release_feedback.set()
        wait_until(lambda: any(item["outcome"] == "dismissed" for item in self.server.events))
        self.assertEqual(self.composer(), "J1")
        self.assertNotIn("accepted_all", [item["outcome"] for item in self.server.events])
        self.reload(); self.show("approve #4", "2 and merge")
        before = self.settled(); self.key("ArrowRight", 39)
        wait_until(lambda: self.settled() > before and self.composer() == "approve #42 ")
        before = self.settled(); self.key("Escape", 27); wait_until(lambda: self.settled() > before and self.ghost() is None)
        reqs = len(self.server.completes)
        for text, delta in ((" ", 0), ("x", 1)):
            before = self.settled(); self.insert(text); wait_until(lambda: self.settled() > before)
            self.assertEqual(len(self.server.completes), reqs + delta)
        self.assertEqual(self.server.completes[-1]["prefix"], "approve #42  x")
        self.reload(); self.show("J1", " all recs")
        before = self.settled(); self.key("Escape", 27); wait_until(lambda: self.settled() > before and self.ghost() is None)
        reqs = len(self.server.completes)
        for text, delta in (("a", 0), (" ", 0), ("b", 1)):
            before = self.settled(); self.insert(text); wait_until(lambda: self.settled() > before)
            self.assertEqual(len(self.server.completes), reqs + delta)
        self.assertEqual(self.server.completes[-1]["prefix"], "J1a b")


class InjectorTests(unittest.TestCase):
    def test_serve_reloads_isolates_bridge_and_skips_other_targets(self):
        with running_server() as server:
            port = server.server_address[1]
            app_url, other_url = f"http://127.0.0.1:{port}/app", f"http://127.0.0.1:{port}/other"
            with chrome_session(start_url=app_url) as debug_port:
                stop = threading.Event()
                worker = threading.Thread(target=inject.serve, args=(debug_port, port, TOKEN, SESSION, app_url),
                                          kwargs={"poll_interval": 0.1, "stop_event": stop}, daemon=True)
                worker.start()
                app_cdp = other_cdp = None
                try:
                    wait_until(lambda: any(t.get("url") == app_url for t in list_targets(debug_port)))
                    app_cdp = cdp.Cdp(next(t["webSocketDebuggerUrl"] for t in list_targets(debug_port) if t.get("url") == app_url))
                    app_cdp.call("Page.enable")
                    other_id = app_cdp.call("Target.createTarget", {"url": other_url})["targetId"]
                    wait_until(lambda: any(t.get("id") == other_id and t.get("url") == other_url for t in list_targets(debug_port)))
                    other_cdp = cdp.Cdp(next(t["webSocketDebuggerUrl"] for t in list_targets(debug_port) if t.get("id") == other_id))
                    wait_until(lambda: cdp_eval(app_cdp, "document.documentElement.dataset.openwizGhost") == "on")
                    self.assertEqual(cdp_eval(app_cdp, "[typeof openwizGhostBinding, typeof __openwizGhostCall]"), ["undefined", "undefined"])
                    cdp_eval(app_cdp, f"{INS_JS}('J1')"); wait_until(lambda: cdp_eval(app_cdp, GHOST_JS) == " all recs")
                    app_cdp.call("Page.reload")
                    wait_until(lambda: cdp_eval(app_cdp, f"{COMP_JS}('#editor')") == ""
                               and cdp_eval(app_cdp, "document.documentElement.dataset.openwizGhost") == "on")
                    cdp_eval(app_cdp, f"{INS_JS}('J1')"); wait_until(lambda: cdp_eval(app_cdp, GHOST_JS) == " all recs")
                    before = len(server.completes)
                    self.assertNotEqual(cdp_eval(other_cdp, "document.documentElement.dataset.openwizGhost"), "on")
                    self.assertEqual(cdp_eval(other_cdp, "typeof openwizGhostBinding"), "undefined")
                    cdp_eval(other_cdp, f"{INS_JS}('J1')"); time.sleep(0.3)
                    self.assertEqual(len(server.completes), before)
                    app_cdp.call("Page.navigate", {"url": other_url})
                    wait_until(lambda: cdp_eval(app_cdp, "location.pathname === '/other' && document.readyState === 'complete'"))
                    cdp_eval(app_cdp, f"{INS_JS}('J1')"); time.sleep(0.3)
                    self.assertEqual(len(server.completes), before)
                finally:
                    stop.set(); worker.join(timeout=3)
                    for conn in (app_cdp, other_cdp):
                        if conn: conn.close()


class ExtensionTests(unittest.TestCase):
    def test_unpacked_extension_options_transport_and_refusals(self):
        with running_server() as server:
            port, ext = server.server_address[1], str(DIR)
            with chrome_session((f"--disable-extensions-except={ext}", f"--load-extension={ext}")) as debug_port:
                wait_until(lambda: any(t.get("type") == "service_worker" and t.get("url", "").startswith("chrome-extension://")
                                       for t in list_targets(debug_port)), timeout=10)
                targets = list_targets(debug_port)
                ext_id = next(t["url"] for t in targets if t.get("type") == "service_worker"
                              and t.get("url", "").startswith("chrome-extension://")).split("/")[2]
                conn = cdp.Cdp(next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page"))
                try:
                    conn.call("Page.enable")
                    def save_options(tok, prt, want):
                        conn.call("Page.navigate", {"url": f"chrome-extension://{ext_id}/options.html"})
                        wait_until(lambda: cdp_eval(conn, "location.pathname === '/options.html' && document.readyState === 'complete'"))
                        cdp_eval(conn, f"document.querySelector('#token').value={json.dumps(tok)};"
                                 f"document.querySelector('#port').value={json.dumps(str(prt))};document.querySelector('form').requestSubmit()")
                        wait_until(lambda: cdp_eval(conn, "document.querySelector('#status').textContent") == want)
                    save_options("", 17417, "A pairing token is required.")
                    save_options(TOKEN, 99999, "Port must be from 1 to 65535.")
                    save_options(TOKEN, port, "Saved on this browser.")
                    conn.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/?ext=1"})
                    wait_until(lambda: cdp_eval(conn, "document.documentElement.dataset.openwizGhost") == "on")
                    cdp_eval(conn, f"{INS_JS}('J1')"); wait_until(lambda: cdp_eval(conn, GHOST_JS) == " all recs")
                    self.assertIsNone(server.completes[-1]["origin"])
                    dispatch_key(conn, "Tab", 9); wait_until(lambda: cdp_eval(conn, f"{COMP_JS}('#editor')") == "J1 all recs")
                    cdp_eval(conn, f"fetch('http://127.0.0.1:{port}/ghost/v1/complete',{{method:'POST',"
                             f"headers:{{'Content-Type':'application/json','Authorization':'Bearer {TOKEN}'}},body:'{{}}'}}).catch(()=>{{}})")
                    wait_until(lambda: any(s == 403 and c == "origin_not_allowed" for s, c, _ in server.refusals))
                    save_options("wrong", port, "Saved on this browser.")
                    conn.call("Page.navigate", {"url": f"http://127.0.0.1:{port}/?ext=2"})
                    wait_until(lambda: cdp_eval(conn, "document.documentElement.dataset.openwizGhost") == "on")
                    cdp_eval(conn, f"{INS_JS}('J1')")
                    wait_until(lambda: any(s == 401 and c == "invalid_token" for s, c, _ in server.refusals))
                    self.assertIsNone(cdp_eval(conn, GHOST_JS))
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
