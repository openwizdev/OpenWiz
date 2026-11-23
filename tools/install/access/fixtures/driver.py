#!/usr/bin/env python3
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
import urllib.request
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from provider import Recording, jwt

parser = argparse.ArgumentParser()
parser.add_argument('--runtime', required=True)
parser.add_argument('--state', required=True)
parser.add_argument('--plan', required=True)
parser.add_argument('--secrets', required=True)
parser.add_argument('--operation')
parser.add_argument('--edge')
parser.add_argument('--mode', default='normal')
args = parser.parse_args()
spec = importlib.util.spec_from_file_location('installed_access', Path(args.runtime) / 'access/access.py')
access = importlib.util.module_from_spec(spec)
spec.loader.exec_module(access)
p = json.loads(Path(args.plan).read_text())
secrets = json.loads(Path(args.secrets).read_text())


class Wire(Recording):
    def request(self, method, url, headers, body=None):
        if args.edge and urlsplit(url).hostname == p['host']:
            edge = urlsplit(args.edge)
            assert edge.scheme == 'http' and edge.hostname == '127.0.0.1' and not edge.username
            self.calls.append((method, p['host'], urlsplit(url).path))
            if p['provider'] == 'tailscale':
                headers = {**headers, 'Cookie': 'CF_Authorization=' + jwt(p['owner'], time.time() + 7200)}
            request = urllib.request.Request(args.edge + urlsplit(url).path, data=body,
                                             headers={**headers, 'Host': p['host']}, method=method)
            try:
                response = urllib.request.urlopen(request, timeout=5)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.code, response.read()
        if args.mode == 'expired':
            return 401, b'Synthetic expired authorization'
        return super().request(method, url, headers, body)


recording = Wire(p, secrets)
recording.owner_report = lambda: {'schema': 'openwiz.setup.v1', 'operations': access.store.Store(args.state).read()['operations']}
recording.offline = args.mode == 'offline'
recording.interrupt = args.mode == 'interrupt'
if args.mode == 'foreign' and p['provider'] == 'tailscale':
    recording.acl['acls'][0]['src'] = ['*']
if args.mode == 'expired' and p['provider'] == 'tailscale':
    recording.status['Self']['Expired'] = True
command = ['configure', '--state-dir', args.state, '--plan', args.plan]
if args.operation:
    command += ['--yes', '--operation', args.operation, '--secrets', args.secrets]
try:
    print(json.dumps(access.execute(command, http=recording, local=recording.local)))
finally:
    with (Path(args.state).parent / 'provider-calls.jsonl').open('a') as log:
        log.write(json.dumps(recording.calls) + '\n')
