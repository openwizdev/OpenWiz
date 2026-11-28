#!/usr/bin/env python3
import importlib.util, json, stat, subprocess, sys, tempfile, threading, unittest, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = importlib.util.spec_from_file_location("openwiz_chrome_bridge", HERE / "bridge.py")
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)

ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
PAGE = {"url": "http://127.0.0.1/demo", "title": "OpenWiz demo", "selection": "lantern",
        "text": "The synthetic lantern hangs above the desk. It is only a fixture."}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.token, _created = bridge.load_token(Path(self.tmp.name))
        self.httpd = bridge.build_server("127.0.0.1", 0, self.token, [], 2, ROOT / "demo" / "page.html")
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, token=None, origin=None, host=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        hdrs = {"Content-Type": "application/json"} if body is not None else {}
        if token is not None:
            hdrs["Authorization"] = token if token.startswith("Bearer ") or token == "nope" else f"Bearer {token}"
        if origin:
            hdrs["Origin"] = origin
        if host:
            hdrs["Host"] = host
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, res.read(), res.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def post(self, route, body, **kwargs):
        status, raw, headers = self.request("POST", f"/chrome/v1/{route}", body, token=kwargs.pop("token", self.token), **kwargs)
        try:
            return status, json.loads(raw.decode()), headers
        except ValueError:
            return status, None, headers

    def test_bind_is_loopback_and_token_file_is_private(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")
        with self.assertRaises(ValueError):
            bridge.build_server("0.0.0.0", 0, self.token, [], 1, ROOT / "demo" / "page.html")
        self.assertEqual((Path(self.tmp.name) / "token.json").stat().st_mode & 0o777, 0o600)

    def test_health_requires_a_token_and_rejects_other_hosts_and_origins(self):
        status, payload, _ = self.post("health", {})
        self.assertEqual((status, payload["schema"], payload["agents"]), (200, "openwiz.chrome.v1", ["page"]))
        status, payload, _ = self.post("health", {}, token="Bearer nope")
        self.assertEqual((status, payload["refusal"]["code"]), (401, "invalid_token"))
        _, raw, _ = self.request("POST", "/chrome/v1/health", {})
        self.assertEqual(json.loads(raw)["refusal"]["code"], "missing_token")
        for bad_host in ("evil.example", "127.0.0.1", "localhost"):
            status, payload, _headers = self.post("health", {}, host=bad_host)
            self.assertEqual((status, payload["refusal"]["code"]), (403, "host_not_allowed"))
        for bad_origin in ("https://example.com", "http://127.0.0.1", "http://localhost"):
            status, payload, _headers = self.post("health", {}, origin=bad_origin)
            self.assertEqual((status, payload["refusal"]["code"]), (403, "origin_not_allowed"))
        for ok_origin in (ORIGIN, f"http://127.0.0.1:{self.port}"):
            status, payload, headers = self.post("health", {}, origin=ok_origin)
            self.assertEqual((status, headers["Access-Control-Allow-Origin"]), (200, ok_origin))

    def test_preflight_and_unknown_routes(self):
        status, raw, headers = self.request("OPTIONS", "/chrome/v1/chat", origin=ORIGIN)
        self.assertEqual((status, headers["Access-Control-Allow-Headers"]), (204, "Authorization, Content-Type"))
        status, raw, _headers = self.request("OPTIONS", "/chrome/v1/chat", origin="https://example.com")
        self.assertEqual(json.loads(raw)["refusal"]["code"], "origin_not_allowed")
        status, payload, _headers = self.post("missing", {})
        self.assertEqual(payload["refusal"]["code"], "unknown_route")
        status, raw, _headers = self.request("GET", "/chrome/v1/health")
        self.assertEqual(json.loads(raw)["refusal"]["code"], "method_not_allowed")
        status, raw, _headers = self.request(
            "POST", "/chrome/v1/chat", token=self.token,
            headers={"Content-Type": "application/json", "Content-Length": str(1024 * 1024 + 8)},
        )
        self.assertEqual((status, json.loads(raw)["refusal"]["code"]), (413, "payload_too_large"))

    def test_page_questions_use_the_attached_page_and_clicks_stay_proposals(self):
        marker = HERE / "not-a-browser"
        self.assertFalse(marker.exists())
        status, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "What is the title of this page?", "page": PAGE})
        self.assertEqual((status, payload["text"], payload["actions"]), (200, "The title is OpenWiz demo.", []))
        _, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "What does this page say about lanterns?", "page": PAGE})
        self.assertIn("synthetic lantern", payload["text"])
        _, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "What does this page say about lanterns?", "page": {**PAGE, "text": "OPENWIZ\n\nSynthetic desk\n\nThe synthetic lantern hangs above the desk."}})
        self.assertEqual(payload["text"], "On OpenWiz demo: The synthetic lantern hangs above the desk.")
        _, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "What is selected?", "page": PAGE})
        self.assertIn("lantern", payload["text"])
        _, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "Click Demo", "page": PAGE})
        self.assertEqual((payload["actions"][0]["op"], payload["actions"][0]["text"]), ("click", "Demo"))
        self.assertIn("grant", payload["text"])
        self.assertFalse(marker.exists())
        _, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "open javascript:alert(1)", "page": PAGE})
        self.assertEqual(payload["actions"], [])
        _, payload, _ = self.post("chat", {"session_id": "sess-1", "agent": "page", "text": "open https://example.com/docs"})
        self.assertEqual((payload["actions"][0]["op"], payload["actions"][0]["url"]), ("navigate", "https://example.com/docs"))

    def test_demo_page_is_local_and_has_no_token(self):
        status, raw, _ = self.request("GET", "/demo")
        text = raw.decode()
        self.assertEqual(status, 200)
        self.assertIn("synthetic lantern", text)
        self.assertNotIn(self.token, text)
        _, raw, _ = self.request("GET", "/demo", origin="https://example.com")
        self.assertEqual(json.loads(raw)["refusal"]["code"], "origin_not_allowed")

    def test_manifest_permissions_are_the_ones_the_panel_needs(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["manifest_version"], 3)
        self.assertEqual(set(manifest["permissions"]), {"sidePanel", "storage", "scripting", "tabs", "activeTab"})
        self.assertEqual(manifest["host_permissions"], ["http://127.0.0.1/*"])
        self.assertEqual(set(manifest["optional_host_permissions"]), {"http://*/*", "https://*/*"})
        self.assertNotIn("content_scripts", manifest)
        self.assertNotIn("<all_urls>", json.dumps(manifest["permissions"]))
        for name in ("sidepanel.html", "sidepanel.js", "sidepanel.css", "background.js", "content.js", "policy.mjs"):
            self.assertTrue((ROOT / name).is_file(), name)
        for size in (16, 32, 48, 128):
            self.assertTrue((ROOT / "icons" / f"icon{size}.png").is_file())


class CommandAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.token, _ = bridge.load_token(root / "state")
        self.log = root / "calls"
        script = root / "agent.py"
        script.write_text(
            f"import json,sys\nfrom pathlib import Path\nPath({str(self.log)!r}).write_text('called', encoding='utf-8')\n"
            "req=json.load(sys.stdin)\nactions=[{'op':'eval','description':'no'},"
            "{'op':'navigate','url':'javascript:alert(1)','description':'no'},{'op':'click','text':'Demo','description':'Click Demo'},"
            "{'op':'type','value':'hi','description':'Type hi'},{'op':'read','description':'Read'},{'op':'click','text':'Extra','description':'Extra'}]\n"
            "json.dump({'text':'cmd '+req['text'],'actions':actions}, sys.stdout)\n", encoding="utf-8",
        )
        self.httpd = bridge.build_server("127.0.0.1", 0, self.token, [sys.executable, str(script)], 2, ROOT / "demo" / "page.html")
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def post(self, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/chrome/v1/chat", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            return json.load(res)

    def test_command_reply_is_sanitized_and_page_agent_does_not_run_it(self):
        page = self.post({"session_id": "sess-2", "agent": "page", "text": "hello"})
        self.assertFalse(self.log.exists())
        self.assertIn("page agent", page["text"])
        replied = self.post({"session_id": "sess-2", "agent": "command", "text": "hello"})
        self.assertEqual((self.log.read_text(encoding="utf-8"), replied["text"]), ("called", "cmd hello"))
        self.assertEqual([item["op"] for item in replied["actions"]], ["click", "type", "read"])
        self.assertNotIn("javascript:", json.dumps(replied))

    def test_command_timeout_is_a_refusal(self):
        self.httpd.agent_argv = (sys.executable, "-c", "import time; time.sleep(30)")
        self.httpd.agent_timeout = 0.3
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post({"session_id": "sess-2", "agent": "command", "text": "hello"})
        self.assertEqual((caught.exception.code, json.load(caught.exception)["refusal"]["code"]), (503, "unavailable"))


class CliTests(unittest.TestCase):
    def test_serve_prints_a_token_and_answers_health(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.Popen(
                [sys.executable, "-I", str(HERE / "bridge.py"), "serve", "--port", "0", "--state-dir", tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            line = proc.stdout.readline()

            def stop():
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                proc.stdout.close()
                proc.stderr.close()

            self.addCleanup(stop)
            payload = json.loads(line)
            self.assertEqual(payload["event"], "listening")
            self.assertTrue(payload["token"])
            self.assertEqual(stat.S_IMODE((Path(tmp) / "token.json").stat().st_mode), 0o600)
            req = urllib.request.Request(
                f"http://127.0.0.1:{payload['port']}/chrome/v1/health", data=b"{}",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {payload['token']}"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as res:
                self.assertEqual(json.load(res)["status"], "ok")
            proc.send_signal(15)
            proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
