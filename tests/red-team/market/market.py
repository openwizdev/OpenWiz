#!/usr/bin/env python3
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'fetcher'))
from server import Copy, Respond, sha256

CANARY = 'openwiz-canary-market-not-a-real-key'
SERVED = ('id', 'name', 'publisher', 'version', 'reviewed_sha256')


def load(file=HERE / 'listings.json'):
    return json.loads(Path(file).read_text(encoding='utf-8'))


def by_poison(poison, file=HERE / 'listings.json'):
    return next(l for l in load(file)['listings'] if l['poison'] == poison)


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def summary(listing):
    out = {k: listing[k] for k in SERVED if k in listing}
    out['reviewed_sha256'] = sha256(listing['package'].encode())
    return out


def detail(listing):
    return dict(summary(listing), readme=listing['readme'], install_script=listing.get('install_script', ''))


class MarketHandler(Respond):
    def do_GET(self):
        self.record()
        listings = {l['id']: l for l in self.listings}
        path = self.path.lstrip('/')
        if path == 'listings':
            return self.send_json({'listings': [summary(l) for l in self.listings]})
        if path == 'actions':
            return self.send_json(self.actions)
        kind, _, key = path.partition('/')
        if key in listings and kind == 'listings':
            return self.send_json(detail(listings[key]))
        if key in listings and kind == 'packages':
            listing = listings[key]
            return self.send(200, listing.get('served_package', listing['package']).encode())
        self.send(404)

    def write(self):
        self.record()
        size = min(int(self.headers.get('Content-Length') or 0), 65536)
        body = self.rfile.read(size).decode('utf-8', 'replace')
        self.actions.append({'method': self.command, 'path': self.path, 'body': body})
        self.send_json({'recorded': True, 'carried_out': False}, 202)

    do_POST = do_PUT = do_PATCH = do_DELETE = write


def start(file=HERE / 'listings.json'):
    class Handler(MarketHandler):
        listings = load(file)['listings']
        actions = []
    copy = Copy(Handler)
    copy.actions = Handler.actions
    return copy


if __name__ == '__main__':
    import loopback
    copy = start()
    print('market copy at ' + copy.url, flush=True)
    copy.thread.join()
