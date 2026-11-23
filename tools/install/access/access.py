#!/usr/bin/env python3
import argparse
import base64
from datetime import datetime, timezone
from http.client import HTTPException
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets as random
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'setup'))
import store

DESCRIPTION = """Verify an owner-configured phone route; never create or activate one.

configure --plan PRIVATE_JSON [--yes --operation ID --secrets PRIVATE_JSON]
status --operation ID
reconcile --plan PRIVATE_JSON --revision ORIGINAL_REVISION --yes
          --operation ID --secrets PRIVATE_JSON

Preview durably records configure_access and its exact request fingerprint.
Confirmation makes read-only provider checks and records independent readiness.
Repeated confirmation reconciles the same resource; it cannot send/create work.
Secrets are read from owner-only files, never arguments, output or shared state.
Python 3.9+, standard library; Cloudflare uses the setup prerequisite
/usr/bin/openssl; Tailscale verification also needs its local CLI at a
fixed system location (never PATH).

Plan JSON has exactly schema="openwiz.access-plan.v1", provider, host (fixed
lowercase HTTPS DNS name), port (loopback integer), owner (email), plus:
  cloudflare: account (32 hex), tunnel and application (UUID), team (slug).
  tailscale: tailnet, device (stable node id), foreign (different email).
Credential JSON has exactly api_token plus owner, expired, foreign JWT cookies
for Cloudflare, or api_token alone for Tailscale. Keep both files private 0600,
outside repositories. No credential value belongs in an argument or prompt.
Cloudflare requires a remotely managed named tunnel, exact loopback ingress,
owner-only all-path Access and origin audience validation. Tailscale requires
private HTTPS Serve, Funnel off, current device approval/expiry and one explicit
owner-only IPv4:443 ACL; current-policy validation tests owner accept/foreign
deny, never a hypothetical replacement policy. Unsupported shapes stay unknown
or refused. Native network enforcement remains a separately authorized check.
"""

HOUR_MS = 3_600_000
MAX_BYTES = 4 * 1024 * 1024
EMAIL = re.compile(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}')
UUID = re.compile(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')
TOKEN = re.compile(r'[A-Za-z0-9._~+/-]{1,16384}=*')
TAILSCALE = ('/usr/bin/tailscale', '/usr/sbin/tailscale', '/usr/local/bin/tailscale', '/opt/homebrew/bin/tailscale',
             '/Applications/Tailscale.app/Contents/MacOS/Tailscale')
CHECK = re.compile('Check ([0-9]{1,16}): ')


class Unverified(Exception):
    def __init__(self, code='access_unavailable'):
        self.code = code


def need(condition, code='access_refused'):
    if not condition:
        raise Unverified(code)


def decode(data):
    return json.loads(data, object_pairs_hook=store.unique)


def private_json(name):
    path = Path(name)
    store.require(path.is_absolute(), 'configuration file must be absolute')
    store.state_path(str(path.parent))
    store.private_directory(path.parent, False)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        store.require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                      and info.st_mode & 0o077 == 0 and info.st_nlink == 1
                      and info.st_size <= MAX_BYTES, 'configuration file is unsafe')
        data = handle.read(MAX_BYTES + 1)
    store.require(len(data) <= MAX_BYTES, 'configuration file is too large')
    return decode(data)


def plan(value):
    store.require(type(value) is dict, 'invalid access plan')
    common = {'schema', 'provider', 'host', 'port', 'owner'}
    extra = {'cloudflare': {'account', 'tunnel', 'application', 'team'},
             'tailscale': {'tailnet', 'device', 'foreign'}}
    provider = value.get('provider')
    store.require(isinstance(provider, str) and provider in extra and set(value) == common | extra[provider]
                  and value['schema'] == 'openwiz.access-plan.v1', 'invalid access plan shape')
    host = value['host']
    store.require(isinstance(host, str) and len(host) <= 253 and host == host.lower()
                  and re.fullmatch(r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}', host)
                  and not any(host == end or host.endswith('.' + end) for end in
                              ('localhost', 'localhost.localdomain', 'trycloudflare.com')),
                  'use one fixed HTTPS DNS hostname, never a quick tunnel or loopback')
    store.require(type(value['port']) is int and 1 <= value['port'] <= 65535, 'invalid loopback port')
    store.require(isinstance(value['owner'], str) and len(value['owner']) <= 254
                  and EMAIL.fullmatch(value['owner']), 'invalid owner identity')
    if provider == 'cloudflare':
        store.require(isinstance(value['account'], str) and re.fullmatch('[0-9a-f]{32}', value['account'])
                      and all(isinstance(value[k], str) and UUID.fullmatch(value[k]) for k in ('tunnel', 'application'))
                      and isinstance(value['team'], str) and re.fullmatch('[a-z0-9-]{1,63}', value['team']),
                      'invalid Cloudflare resource identity')
    else:
        store.require(host.endswith('.ts.net') and isinstance(value['device'], str)
                      and re.fullmatch('[A-Za-z0-9_-]{1,128}', value['device'])
                      and isinstance(value['tailnet'], str) and re.fullmatch('[A-Za-z0-9@._-]{1,254}', value['tailnet'])
                      and isinstance(value['foreign'], str) and len(value['foreign']) <= 254
                      and EMAIL.fullmatch(value['foreign']) and value['foreign'] != value['owner'],
                      'invalid Tailscale resource identity')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Http:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method, url, headers, body=None):
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = response.read(MAX_BYTES + 1)
            need(len(data) <= MAX_BYTES, 'access_unavailable')
            declared = response.headers.get('Content-Length')
            need(declared is None or (re.fullmatch('[0-9]{1,16}', declared) is not None
                                      and int(declared) == len(data)), 'access_unavailable')
            return response.code, data


def api(http, url, token):
    status, body = http.request('GET', url, {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    need(status not in (401, 403), 'access_expired')
    need(status == 200, 'access_unavailable')
    return decode(body)


def owner_report(body, witness):
    value = decode(body)
    need(type(value) is dict and value.get('schema') == 'openwiz.setup.v1', 'access_unavailable')
    operations = value.get('operations')
    need(type(operations) is list, 'access_unavailable')
    matches = [o for o in operations if type(o) is dict and o.get('operation_id') == witness['operation_id']]
    need(len(matches) == 1 and all(matches[0].get(k) == v for k, v in witness.items()), 'access_unavailable')


def unbase64(value):
    need(isinstance(value, str) and re.fullmatch('[A-Za-z0-9_-]{1,16384}', value), 'access_unavailable')
    raw = base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))
    need(base64.urlsafe_b64encode(raw).decode().rstrip('=') == value, 'access_unavailable')
    return raw


def rsa_key(key):
    need(key.get('kty') == 'RSA' and key.get('alg') == 'RS256' and key.get('use') == 'sig'
         and key.get('e') == 'AQAB', 'access_unavailable')
    modulus = unbase64(key['n'])
    need(len(modulus) in (256, 384, 512) and modulus[0] & 128 and modulus[-1] & 1, 'access_unavailable')
    def der(tag, data):
        size = len(data)
        length = bytes([size]) if size < 128 else b'\x82' + size.to_bytes(2, 'big')
        return bytes([tag]) + length + data
    encoded = der(48, der(2, b'\x00' + modulus) + der(2, b'\x01\x00\x01'))
    return b'-----BEGIN RSA PUBLIC KEY-----\n' + base64.encodebytes(encoded) + b'-----END RSA PUBLIC KEY-----\n'


def cloudflare_contexts(http, p, secrets, audience, now):
    issuer = 'https://' + p['team'] + '.cloudflareaccess.com'
    status, body = http.request('GET', issuer + '/cdn-cgi/access/certs', {})
    need(status == 200, 'access_unavailable')
    keys = decode(body)['keys']
    need(type(keys) is list and 1 <= len(keys) <= 16, 'access_unavailable')
    expiries = {}
    for label in ('owner', 'expired', 'foreign'):
        pieces = secrets[label].split('.')
        need(len(pieces) == 3, 'access_unavailable')
        header = decode(unbase64(pieces[0]))
        need(type(header) is dict and set(header) <= {'alg', 'kid', 'typ'} and header.get('alg') == 'RS256'
             and isinstance(header.get('kid'), str) and 1 <= len(header['kid']) <= 128
             and header.get('typ', 'JWT') == 'JWT', 'access_unavailable')
        matching = [key for key in keys if type(key) is dict and key.get('kid') == header['kid']]
        need(len(matching) == 1, 'access_unavailable')
        public = rsa_key(matching[0])
        signature = unbase64(pieces[2])
        need(len(signature) in (256, 384, 512), 'access_unavailable')
        with tempfile.TemporaryDirectory(prefix='openwiz-access-signature-') as directory:
            key_path, signature_path = Path(directory) / 'public.pem', Path(directory) / 'signature'
            key_path.write_bytes(public)
            signature_path.write_bytes(signature)
            checked = subprocess.run(['/usr/bin/openssl', 'dgst', '-sha256', '-verify', str(key_path),
                                      '-signature', str(signature_path)],
                                     input=(pieces[0] + '.' + pieces[1]).encode('ascii'),
                                     capture_output=True, timeout=10, env={})
        need(checked.returncode == 0, 'access_unavailable')
        claims = decode(unbase64(pieces[1]))
        need(type(claims) is dict and type(claims.get('exp')) is int and claims.get('iss') == issuer
             and claims.get('aud') == [audience] and claims.get('type') == 'app', 'access_unavailable')
        for key in ('nbf', 'iat'):
            need(key not in claims or (type(claims[key]) is int and claims[key] <= now), 'access_unavailable')
        email = claims.get('email')
        need(isinstance(email, str) and EMAIL.fullmatch(email), 'access_unavailable')
        need((email != p['owner']) if label == 'foreign' else (email == p['owner']), 'access_unavailable')
        expiries[label] = claims['exp']
    need(expiries['owner'] > now, 'access_expired')
    need(expiries['foreign'] > now and expiries['expired'] <= now, 'access_unavailable')
    return expiries


def cloudflare(http, p, secrets, now, witness):
    need(set(secrets) == {'api_token', 'owner', 'expired', 'foreign'}, 'access_unavailable')
    base = 'https://api.cloudflare.com/client/v4/accounts/' + p['account']

    def read(path, account=True):
        root = base if account else 'https://api.cloudflare.com/client/v4'
        answer = api(http, root + path, secrets['api_token'])
        need(type(answer) is dict and answer.get('success') is True and 'result' in answer,
             'access_unavailable')
        result = answer['result']
        if type(result) is list:
            info = answer.get('result_info')
            need(type(info) is dict and type(info.get('total_count')) is int
                 and info['total_count'] == len(result) and type(info.get('page')) is int and info['page'] == 1,
                 'access_unavailable')
        return result

    def inspect():
        zones = read('/zones?account.id=' + p['account'], account=False)
        need(type(zones) is list, 'access_unavailable')
        covering = [z for z in zones if type(z) is dict and isinstance(z.get('name'), str)
                    and (p['host'] == z['name'] or p['host'].endswith('.' + z['name']))]
        need(len(covering) == 1, 'access_unavailable')
        zone = covering[0]
        need(zone['account']['id'] == p['account'] and zone.get('status') == 'active'
             and zone.get('type') == 'full' and isinstance(zone.get('id'), str)
             and re.fullmatch('[0-9a-f]{32}', zone['id']), 'access_unavailable')
        records = read('/zones/' + zone['id'] + '/dns_records?name=' + p['host'], account=False)
        need(type(records) is list and len(records) == 1, 'access_unavailable')
        record = records[0]
        need(record['name'] == p['host'] and record['type'] == 'CNAME' and record['proxied'] is True
             and record['content'] == p['tunnel'] + '.cfargotunnel.com', 'access_unavailable')
        tunnel = read('/cfd_tunnel/' + p['tunnel'])
        need(tunnel['id'] == p['tunnel'] and tunnel.get('deleted_at') is None
             and tunnel.get('config_src') == 'cloudflare' and store.text(tunnel.get('name'))
             and tunnel.get('status') == 'healthy')
        apps = read('/access/apps')
        need(type(apps) is list, 'access_unavailable')
        covering = []
        for candidate in apps:
            if candidate.get('type') in ('saas', 'bookmark'):
                continue
            domains = candidate.get('self_hosted_domains') or [candidate['domain']]
            need(type(domains) is list and all(isinstance(d, str) for d in domains), 'access_unavailable')
            for domain in domains:
                name = domain.split('/', 1)[0].lower()
                plain = name[2:] if name.startswith('*.') else name
                need(re.fullmatch(r'[a-z0-9.-]+', plain) is not None, 'access_unavailable')
                if name == p['host'] or (name.startswith('*.') and p['host'].endswith(name[1:])):
                    covering.append(candidate['id'])
                    break
        need(covering == [p['application']])
        app = read('/access/apps/' + p['application'])
        need(app['id'] == p['application'] and app['type'] == 'self_hosted' and app['domain'] == p['host']
             and (app.get('self_hosted_domains') in (None, [p['host']]))
             and isinstance(app.get('aud'), str) and re.fullmatch('[a-zA-Z0-9_-]{1,128}', app['aud']))
        policies = read('/access/apps/' + p['application'] + '/policies')
        need(type(policies) is list and len(policies) == 1)
        policy = policies[0]
        need(policy['decision'] == 'allow' and policy['include'] == [{'email': {'email': p['owner']}}]
             and policy.get('exclude', []) == [] and policy.get('require', []) == [])
        configured = read('/cfd_tunnel/' + p['tunnel'] + '/configurations')
        config = configured['config']
        version = configured.get('version')
        need(configured.get('account_id') == p['account'] and configured.get('tunnel_id') == p['tunnel']
             and configured.get('source') == 'cloudflare' and type(version) is int
             and 0 <= version < 2 ** 53, 'access_unavailable')
        expected = [{'hostname': p['host'], 'service': f"http://127.0.0.1:{p['port']}",
                     'originRequest': {'access': {'required': True, 'teamName': p['team'], 'audTag': [app['aud']]}}},
                    {'service': 'http_status:404'}]
        need(config == {'ingress': expected}
             and config['ingress'][0]['originRequest']['access']['required'] is True)
        clients = read('/cfd_tunnel/' + p['tunnel'] + '/connections')
        need(type(clients) is list and clients, 'access_unavailable')
        identities = []
        for client in clients:
            need(type(client) is dict and isinstance(client.get('id'), str) and UUID.fullmatch(client['id'])
                 and type(client.get('config_version')) is int and client['config_version'] == version,
                 'access_unavailable')
            identities.append(client['id'])
            connections = client.get('conns')
            need(type(connections) is list and connections, 'access_unavailable')
            for connection in connections:
                need(connection['client_id'] == client['id'] and connection.get('is_pending_reconnect') is False,
                     'access_unavailable')
        need(len(set(identities)) == len(identities), 'access_unavailable')
        return (tunnel['id'], app['aud'], policy, config, zone, record, version, sorted(identities))

    before = inspect()
    expiries = cloudflare_contexts(http, p, secrets, before[1], now)
    paths = ['/api/v1/setup', '/api/v1/sessions/access-probe/messages', '/api/v1/projects/access-probe/threads']
    for label in ('anonymous', 'expired', 'foreign', 'owner'):
        headers = {'X-Requested-With': 'XMLHttpRequest'}
        if label != 'anonymous':
            headers['Cookie'] = 'CF_Authorization=' + secrets[label]
        for path in paths if label != 'owner' else paths[:1]:
            status, body = http.request('GET', 'https://' + p['host'] + path, headers)
            if label == 'owner':
                need(status == 200, 'access_expired' if status in (401, 403) else 'access_unavailable')
                owner_report(body, witness)
            else:
                need(status in (401, 403))
                need(b'openwiz.' not in body and b'"error"' not in body)
    need(inspect() == before, 'access_unavailable')
    need(expiries['foreign'] > time.time(), 'access_unavailable')
    need(expiries['owner'] > time.time(), 'access_expired')
    return expiries['owner']


def local_tailscale(kind):
    executable = next((path for path in TAILSCALE if os.path.isfile(path) and os.access(path, os.X_OK)), None)
    need(executable is not None, 'access_unavailable')
    args = ['status', '--json'] if kind == 'status' else ['serve', 'status', '--json']
    reply = subprocess.run([executable, *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                           env={'PATH': '/usr/bin:/bin'})
    need(reply.returncode == 0 and len(reply.stdout) <= MAX_BYTES, 'access_unavailable')
    return decode(reply.stdout)


def date_seconds(value):
    need(isinstance(value, str), 'access_unavailable')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(parsed.tzinfo is not None, 'access_unavailable')
    return parsed.astimezone(timezone.utc).timestamp()


def tailscale(http, p, secrets, now, local, witness):
    need(set(secrets) == {'api_token'}, 'access_unavailable')
    base = 'https://api.tailscale.com/api/v2/'
    tailnet = urllib.parse.quote(p['tailnet'], safe='')

    def inspect():
        status = local('status')
        node = status['Self']
        need(status['BackendState'] == 'Running' and node['ID'] == p['device']
             and node['DNSName'].rstrip('.') == p['host'] and node['Online'] is True
             and node.get('Expired', False) is False, 'access_expired')
        device = api(http, base + 'device/' + p['device'], secrets['api_token'])
        need(device['nodeId'] == p['device'] and device['name'] == p['host']
             and device['user'] == p['owner'] and device['authorized'] is True, 'access_refused')
        expiry = date_seconds(device['expires'])
        need(expiry > now, 'access_expired')
        addresses = device['addresses']
        need(type(addresses) is list and addresses, 'access_unavailable')
        ip = str(ipaddress.ip_address(addresses[0]))
        need(ipaddress.ip_address(ip) in ipaddress.ip_network('100.64.0.0/10'))
        serve = local('serve')
        expected = {'TCP': {'443': {'HTTPS': True}},
                    'Web': {p['host'] + ':443': {'Handlers': {'/': {'Proxy': f"http://127.0.0.1:{p['port']}"}}}}}
        need(type(serve) is dict and set(serve) <= {'TCP', 'Web', 'AllowFunnel'}
             and {k: v for k, v in serve.items() if k != 'AllowFunnel'} == expected
             and serve['TCP']['443']['HTTPS'] is True
             and (serve.get('AllowFunnel', {}) == {} or (set(serve['AllowFunnel']) == {p['host'] + ':443'}
                   and serve['AllowFunnel'][p['host'] + ':443'] is False)))
        policy = api(http, base + 'tailnet/' + tailnet + '/acl', secrets['api_token'])
        need(type(policy) is dict and set(policy) <= {'acls', 'tests'}
             and policy.get('acls') == [{'action': 'accept', 'src': [p['owner']], 'dst': [ip + ':443']}])
        return (ip, expiry, serve, policy)

    before = inspect()
    tests = [{'src': p['owner'], 'accept': [before[0] + ':443']},
             {'src': p['foreign'], 'deny': [before[0] + ':443']}]
    status, body = http.request('POST', base + 'tailnet/' + tailnet + '/acl/validate',
                                {'Authorization': 'Bearer ' + secrets['api_token'], 'Content-Type': 'application/json'},
                                json.dumps(tests).encode())
    need(status == 200 and body == b'')
    status, body = http.request('GET', 'https://' + p['host'] + '/api/v1/setup', {})
    need(status == 200, 'access_unavailable')
    owner_report(body, witness)
    need(inspect() == before, 'access_unavailable')
    return before[1]


def verify(http, p, secret_path, now, local, witness):
    try:
        secrets = private_json(secret_path)
        need(type(secrets) is dict and all(isinstance(v, str) and TOKEN.fullmatch(v) for v in secrets.values()),
             'access_unavailable')
        expiry = (cloudflare(http, p, secrets, now, witness) if p['provider'] == 'cloudflare'
                  else tailscale(http, p, secrets, now, local, witness))
        at = int(min(now, expiry - HOUR_MS / 1000) * 1000)
        return 'access_' + p['provider'] + '_verified', at
    except Unverified as error:
        return error.code, int(now * 1000)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError, HTTPException,
            store.Refused, subprocess.SubprocessError):
        return 'access_unavailable', int(now * 1000)


def observed(operations):
    tagged = [o for o in operations if o['kind'] == 'configure_access' and CHECK.match(o['reason'])]
    return tagged[0] if len(tagged) == 1 else None


def untag(operations):
    for operation in operations:
        found = CHECK.match(operation['reason'])
        if operation['kind'] == 'configure_access' and found:
            rest = operation['reason'][found.end():]
            operation['reason'] = rest[:1].upper() + rest[1:]


def execute(argv=None, *, http=None, local=local_tailscale):
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('configure', 'reconcile', 'status'):
        command = commands.add_parser(name)
        command.add_argument('--state-dir')
        command.add_argument('--operation')
    for name in ('configure', 'reconcile'):
        command = commands.choices[name]
        command.add_argument('--plan', required=True)
        command.add_argument('--secrets')
        command.add_argument('--yes', action='store_true')
    commands.choices['reconcile'].add_argument('--revision', required=True, type=int)
    args = parser.parse_args(argv)
    setup = store.Store(args.state_dir)
    if args.command == 'status':
        value = setup.read()
        operation = next((o for o in value['operations'] if o['operation_id'] == args.operation
                          and o['kind'] == 'configure_access'), None)
        store.require(operation is not None, 'unknown access operation')
        bound = observed(value['operations']) is operation
        return {'operation': operation, 'observation': value['observations'].get('remote_access') if bound else None}
    selected = plan(private_json(args.plan))
    before = setup.read()
    context_revision = before['revision']
    revision = args.revision if args.command == 'reconcile' else context_revision
    store.require(type(revision) is int and 0 <= revision < 2 ** 53, 'invalid selection revision')
    store.require(args.command != 'reconcile' or args.yes, 'reconciliation needs current explicit confirmation')
    request = {'plan': selected, 'revision': revision}
    effects = [f"Verify the {selected['provider']} route for HTTPS host {selected['host']}.",
               'Check owner-only policy, current authorization and refusal before phone readiness.',
               'Record the result in this host\'s private setup state.',
               'No tunnel, DNS, policy, engine or account is created or activated; no work is sent.']
    digest = store.fingerprint('configure_access', request)

    def selected_request(value):
        active = [o for o in value['operations'] if o['kind'] == 'configure_access' and o['phase'] != 'proposed']
        return not active or active[-1]['fingerprint'] == digest

    def pending(value):
        store.require(not any(o['kind'] == 'configure_access' and o['phase'] == 'uncertain'
                              and o['fingerprint'] != digest for o in value['operations']),
                      'reconcile the uncertain access operation before changing routes')

    if not args.yes:
        def propose(value):
            store.require(value['revision'] == revision, 'setup selection changed; preview again')
            pending(value)
            for operation in reversed(value['operations']):
                if operation['kind'] == 'configure_access' and operation['fingerprint'] == digest:
                    if operation['phase'] in ('proposed', 'uncertain') or (operation['phase'] == 'applied' and selected_request(value)):
                        return dict(operation)
            operation = {'operation_id': random.token_hex(16), 'kind': 'configure_access', 'phase': 'proposed',
                         'fingerprint': digest, 'effects': effects, 'reason': 'Proposed: confirm with --yes --operation.'}
            value['operations'] = store.retained(value['operations'], (value.get('engine') or {}).get('operation_id')) + [operation]
            return dict(operation)
        operation = setup.update(propose)
        return {'operation': operation, 'observation': None, 'selection_revision': revision}
    store.require(args.operation is not None and args.secrets is not None, 'confirmation needs operation id and private secrets file')
    generation = setup.start_check()

    def claim(value):
        if value['checks']['started'] != generation or value['checks']['committed'] >= generation:
            raise store.Superseded()
        store.require(value['revision'] == context_revision, 'setup selection changed; preview again')
        pending(value)
        operation = setup.authorized(value, args.operation, 'configure_access', request, selected_request)
        if operation['phase'] == 'proposed':
            operation['phase'] = 'uncertain'
        untag(value['operations'])
        operation['reason'] = (f'Check {generation}: verification code ' + random.token_hex(16)
                               + '. Check this operation after an interrupted verification.')
        value['observations']['remote_access'] = {'code': 'access_checking', 'revision': revision,
                                                'at': int(time.time() * 1000)}
        return {key: operation[key] for key in ('operation_id', 'kind', 'fingerprint', 'phase', 'reason')}
    witness = setup.update(claim)
    code, at = verify(http or Http(), selected, args.secrets, time.time(), local, witness)

    def finish(value):
        if value['revision'] != context_revision or value['checks']['started'] != generation:
            raise store.Superseded()
        value['checks']['committed'] = generation
        operation = setup.authorized(value, args.operation, 'configure_access', request)
        observation = {'code': code, 'revision': revision, 'at': at}
        value['observations']['remote_access'] = observation
        if code in ('access_cloudflare_verified', 'access_tailscale_verified'):
            operation['phase'] = 'applied'
            reason = 'Route checked. Readiness still requires current independent evidence.'
        else:
            reason = ('Previous verification is recorded; current access needs attention.'
                      if operation['phase'] == 'applied'
                      else 'Verification remains uncertain; recheck this exact route before changing it.')
        operation['reason'] = f'Check {generation}: {reason}'
        return {'operation': dict(operation), 'observation': observation}
    return setup.update(finish)


if __name__ == '__main__':
    try:
        print(json.dumps(execute(), sort_keys=True))
    except store.Superseded:
        print('openwiz-access: superseded; a newer check or selection took precedence', file=sys.stderr)
        sys.exit(7)
    except (store.Refused, OSError, ValueError, TypeError):
        print('openwiz-access: refused; check the private plan, operation and state, then preview again', file=sys.stderr)
        sys.exit(5)
