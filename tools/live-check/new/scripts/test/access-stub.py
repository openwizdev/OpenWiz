#!/usr/bin/env python3
"""Test-only stand-in for Cloudflare Access in front of the public hostname (L-10).
SYNTHETIC ONLY. It never forwards anything: every request without a login gets what
Access gives one (documented, not observed here: sheet A-6): 401 to a request carrying
X-Requested-With (a page's own sub-request), else a 302 to a synthetic login page.
Neither answer carries OpenWiz's headers or error body.

    access-stub.py <port> [<forward port>]

With a forward port it stands for a leaky edge instead: it passes every request to
127.0.0.1:<forward port>, without its Origin header, and returns the answer as it came.
"""
import http.client
import http.server
import sys

FORWARD = int(sys.argv[2]) if len(sys.argv) > 2 else None


class H(http.server.BaseHTTPRequestHandler):
    def answer(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else None
        if FORWARD:
            c = http.client.HTTPConnection("127.0.0.1", FORWARD, timeout=30)
            c.putrequest(self.command, self.path, skip_host=True, skip_accept_encoding=True)
            for k, v in self.headers.items():
                if k.lower() != "origin":
                    c.putheader(k, v)
            c.endheaders(body)
            r = c.getresponse()
            data = r.read()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in ("connection", "content-length"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if self.headers.get("X-Requested-With"):
            body = b"<html><body>Synthetic Access: sign in first</body></html>"
            self.send_response(401)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(302)
        self.send_header("Location", "https://synthetic-team.example.invalid/cdn-cgi/access/login/synthetic")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_PUT = do_DELETE = answer

    def log_message(self, *a):
        pass


http.server.HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
