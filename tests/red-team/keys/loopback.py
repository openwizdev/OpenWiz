#!/usr/bin/env python3
import json
import os
import runpy
import sys

HOSTKEY = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))), 'kernel', 'driver-kit', 'hostkey.py')
LOOPBACK = ('127.0.0.1', '::1', 'localhost')
SPAWN = ('subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.exec', 'os.spawn', 'os.fork')


class Offline(RuntimeError):
    pass


def _name(value):
    return value.decode('ascii', 'replace') if isinstance(value, bytes) else value


def _hook(allow_spawn):
    def hook(event, args):
        if event == 'socket.getaddrinfo' and _name(args[0]) not in LOOPBACK:
            raise Offline('the copy resolves only localhost')
        if event in ('socket.connect', 'socket.sendto') and isinstance(args[1], tuple) \
                and _name(args[1][0]) not in LOOPBACK:
            raise Offline('the copy reaches only localhost')
        if not allow_spawn and event in SPAWN:
            raise Offline('the copy starts no other program')
    return hook


def guard(allow_spawn=True):
    sys.addaudithook(_hook(allow_spawn))


def body(handler):
    return handler.rfile.read(min(int(handler.headers.get('Content-Length') or 0), 1 << 20)).decode('utf-8', 'replace')


def reply(handler, status, value):
    data = json.dumps(value).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class Server:
    def __init__(self, handler):
        self.handler, self.log, self.echo = handler, [], False

    def record(self, entry):
        self.log.append(entry)
        if self.echo:
            print(json.dumps(entry), flush=True)

    def __enter__(self):
        import http.server
        import threading
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), self.handler)
        self.server.copy = self
        self.origin = 'http://127.0.0.1:%d' % self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def forever(self, banner):
        self.echo = True
        with self:
            print(json.dumps({**banner, 'origin': self.origin}), flush=True)
            try:
                self.thread.join()
            except KeyboardInterrupt:
                pass


def main(argv):
    script = argv[0] if argv else HOSTKEY
    guard(allow_spawn=False)
    sys.argv = [script]
    runpy.run_path(script, run_name='__main__')


if __name__ == '__main__':
    main(sys.argv[1:])
