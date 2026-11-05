#!/usr/bin/env python3
"""Test-only stand-in for X1's 0.0.4 server during the swap's startup tests (#152, Sol R2,
round 2). SYNTHETIC ONLY. Takes openwiz-server's arguments, binds --port at once (so
the port is taken, as a real server's would be), and answers /api/v1/health 200 --
or 503 to everything when a file named `bad` sits next to it at start (a server that
never becomes healthy)."""
import http.server
import os
import sys

port = int(sys.argv[sys.argv.index("--port") + 1])
bad = os.path.exists(os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), "bad"))


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        ok = not bad and self.path == "/api/v1/health"
        self.send_response(200 if ok else 503)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
