#!/usr/bin/env python3
"""A fake fetch server on 127.0.0.1: good and tampered synthetic driver packages.

Each package in packages.json has the bytes it was pinned on (`body`) and,
unless it is the good one, the bytes the server actually sends (`served`).
The index gives every package's pin; it never says which one is tampered.
`/redirect/<path>` answers with a redirect to an off-host name that never
resolves (`fetch.invalid`), for checking that a client refuses to follow it.
Every request is logged; nothing is ever written.
"""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent


def load(file=HERE / 'packages.json'):
    return json.loads(Path(file).read_text(encoding='utf-8'))


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def verify(data, pinned):
    return hmac.compare_digest(sha256(data), pinned)


class Copy:
    """One running copy: `url`, `address`, `log`, and `stop()`."""

    def __init__(self, handler):
        self.log = []
        copy = self

        class Handler(handler):
            def log_message(self, *args):
                pass

            def record(self):
                copy.log.append({'method': self.command, 'path': self.path})

        Handler.copy = copy
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.address = self.server.server_address[:2]
        self.url = 'http://%s:%d/' % self.address
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class Respond(BaseHTTPRequestHandler):
    def send(self, status, body=b'', kind='application/octet-stream', headers=()):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        for name, value in headers:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value, status=200):
        self.send(status, json.dumps(value, indent=2).encode() + b'\n', 'application/json')


class FetchHandler(Respond):
    def do_GET(self):
        self.record()
        packages = {p['path']: p for p in index(self.packages)}
        path = self.path.lstrip('/')
        if path == 'index.json':
            return self.send_json({'packages': index(self.packages)})
        if path.startswith('redirect/') and path[len('redirect/'):] in packages:
            return self.send(302, headers=[('Location', 'http://fetch.invalid/' + path[len('redirect/'):])])
        for package in self.packages:
            if package_path(package) == path:
                return self.send(200, package.get('served', package['body']).encode())
        self.send(404)

    def refuse(self):
        self.record()
        self.send(405)

    do_POST = do_PUT = do_PATCH = do_DELETE = refuse


def package_path(package):
    return 'packages/%s-%s.drv' % (package['name'], package['version'])


def index(packages):
    return [{'name': p['name'], 'version': p['version'], 'path': package_path(p),
             'sha256': sha256(p['body'].encode())} for p in packages]


def start(file=HERE / 'packages.json'):
    class Handler(FetchHandler):
        packages = load(file)['packages']
    return Copy(Handler)


if __name__ == '__main__':
    import loopback  # noqa: F401
    copy = start()
    print('fetcher copy at ' + copy.url, flush=True)
    copy.thread.join()
