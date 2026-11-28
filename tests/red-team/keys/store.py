#!/usr/bin/env python3
import http.server
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from loopback import Server, body, guard, reply  # noqa: E402 -- the copy's folder is put on the path first, since -I leaves it off

STORE = os.path.join(HERE, 'store.json')
CANARY = re.compile(r'^openwiz-canary-[a-z0-9]+(?:-[a-z0-9]+)*-not-a-real-key$')
KEY_PATH = '/.openwiz/hostkey-test-key'
OVERRIDE = 'OPENWIZ_HOSTKEY_TEST_ORIGIN'
HELPER = [sys.executable, '-I', os.path.join(HERE, 'loopback.py')]


def load(path=STORE):
    with open(path, encoding='utf-8') as f:
        keys = json.load(f)
    if not isinstance(keys, dict) or not keys \
            or not all(isinstance(key, str) and CANARY.match(key) for key in keys.values()):
        raise ValueError('the key store may hold only canary keys')
    return keys


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def request_seen(self):
        copy = self.server.copy
        sent = body(self)
        if self.command == 'GET' and self.path == KEY_PATH:
            copy.record({'method': 'GET', 'path': self.path, 'gave': 'canary'})
            return reply(self, 200, {'key': copy.key})
        others = [v for k, v in self.headers.items() if k.lower() != 'authorization']
        copy.record({'method': self.command, 'path': self.path,
                     'authorized': self.headers.get('Authorization') == 'Bearer ' + copy.key,
                     'leaked': any(copy.key in text for text in [self.path, sent, *others])})
        reply(self, 200, {})

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = request_seen


class Store(Server):
    def __init__(self, host):
        super().__init__(Handler)
        self.host, self.key = host, load()[host]


def helper_env(origin):
    return {OVERRIDE: origin, 'PATH': '/usr/bin:/bin'}


def helper(origin, request):
    return subprocess.run(HELPER, input=json.dumps(request), capture_output=True, text=True,
                          env=helper_env(origin), timeout=120)


def main(argv):
    hosts = load()
    if len(argv) != 1 or argv[0] not in hosts:
        print('usage: store.py <host>, one of ' + ', '.join(sorted(hosts)), file=sys.stderr)
        return 2
    guard(allow_spawn=False)
    Store(argv[0]).forever({'host': argv[0], 'set': OVERRIDE, 'helper': 'python3 -I tests/red-team/keys/loopback.py'})
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
