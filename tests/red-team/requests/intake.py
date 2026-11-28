#!/usr/bin/env python3
import http.server
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'keys'))

from loopback import Server, body, guard, reply  # noqa: E402 -- the keys folder goes on the path first; -I leaves it off

REQUESTS = os.path.join(HERE, 'requests.json')
ONE = re.compile(r'/requests/([0-9]+)')


def load(path=REQUESTS):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def served(request):
    return {k: v for k, v in request.items() if k != 'carries'}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        copy, one = self.server.copy, ONE.fullmatch(self.path)
        if self.path == '/requests':
            return reply(self, 200, [served(r) for r in copy.requests])
        if self.path == '/actions':
            return reply(self, 200, copy.log)
        found = [served(r) for r in copy.requests if one and r['id'] == int(one.group(1))]
        if found:
            return reply(self, 200, found[0])
        reply(self, 404, {'error': 'no such request'})

    def write_seen(self):
        sent = body(self)
        try:
            sent = json.loads(sent) if sent else None
        except ValueError:
            pass
        self.server.copy.record({'method': self.command, 'path': self.path, 'body': sent})
        reply(self, 202, {'recorded': True})

    do_POST = do_PUT = do_PATCH = do_DELETE = write_seen


class Intake(Server):
    def __init__(self, path=REQUESTS):
        super().__init__(Handler)
        self.requests = load(path)

def main(argv):
    if argv:
        print('usage: intake.py', file=sys.stderr)
        return 2
    guard(allow_spawn=False)
    Intake().forever({'requests': '/requests', 'actions': '/actions'})
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
