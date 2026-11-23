import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
import time
from urllib.parse import urlsplit

OWNER = 'owner@example.invalid'
FOREIGN = 'foreign@example.invalid'


# SECURITY: this is RFC 7515's public, deliberately compromised RSA example key (appendix A.2,
# https://www.rfc-editor.org/rfc/rfc7515#appendix-A.2); never use it with a real account.
N = ('ofgWCuLjybRlzo0tZWJjNiuSfb4p4fAkd_wWJcyQoTbji9k0l8W26mPddx'
     'HmfHQp-Vaw-4qPCJrcS2mJPMEzP1Pt0Bm4d4QlL-yRT-SFd2lZS-pCgNMs'
     'D1W_YpRPEwOWvG6b32690r2jZ47soMZo9wGzjb_7OMg0LOL-bSf63kpaSH'
     'SXndS5z5rexMdbBYUsLA9e-KXBdQOS-UTo7WTBEMa2R2CapHg665xsmtdV'
     'MTBQY4uDZlxvb3qCo5ZwKh9kG4LT6_I5IhlJH7aGhyxXFvUK-DWNmoudF8'
     'NAco9_h9iaGNj8q2ethFkMLs91kzk2PAcDTW9gb54h4FRWyuXpoQ')
D = ('Eq5xpGnNCivDflJsRQBXHx1hdR1k6Ulwe2JZD50LpXyWPEAeP88vLNO97I'
     'jlA7_GQ5sLKMgvfTeXZx9SE-7YwVol2NXOoAJe46sui395IW_GO-pWJ1O0'
     'BkTGoVEn2bKVRUCgu-GjBVaYLU6f3l9kJfFNS3E0QbVdxzubSu3Mkqzjkn'
     '439X0M_V51gfpRLI9JYanrC4D4qAdGcopV_0ZHHzQlBjudU2QvXt4ehNYT'
     'CBr6XCLQUShb1juUO1ZdiYoFaFQT5Tw8bGUl_x_jTj3ccPDVZFD9pIuhLh'
     'BOneufuBiB4cS98l2SR_RQyGWSeWjnczT0QU91p1DhOVRuOopznQ')
JWK = {'kid': 'rfc7515-example', 'kty': 'RSA', 'alg': 'RS256', 'use': 'sig', 'n': N, 'e': 'AQAB'}


def b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip('=')


def jwt(email, expiry, **overrides):
    claims = {'email': email, 'exp': int(expiry), 'iss': 'https://synthetic-team.cloudflareaccess.com',
              'aud': ['SyntheticAudience'], 'type': 'app'}
    claims.update(overrides)
    message = (b64(b'{"alg":"RS256","kid":"rfc7515-example","typ":"JWT"}') + '.'
               + b64(json.dumps(claims).encode())).encode()
    digest = bytes.fromhex('3031300d060960864801650304020105000420') + hashlib.sha256(message).digest()
    encoded = b'\x00\x01' + b'\xff' * (256 - len(digest) - 3) + b'\x00' + digest
    number = lambda value: int.from_bytes(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)), 'big')
    signature = pow(int.from_bytes(encoded, 'big'), number(D), number(N)).to_bytes(256, 'big')
    return message.decode() + '.' + b64(signature)


def selected(provider='cloudflare'):
    common = {'schema': 'openwiz.access-plan.v1', 'provider': provider, 'host': 'openwiz.synthetic.invalid',
              'port': 7370, 'owner': OWNER}
    if provider == 'cloudflare':
        common.update(account='1' * 32, tunnel='22222222-2222-2222-2222-222222222222',
                      application='33333333-3333-3333-3333-333333333333', team='synthetic-team')
    else:
        common.update(host='engine.synthetic.ts.net', tailnet='synthetic.invalid', device='nSynthetic', foreign=FOREIGN)
    return common


def credentials(provider='cloudflare'):
    now = time.time()
    value = {'api_token': 'SyntheticAccessCredential'}
    if provider == 'cloudflare':
        value.update(owner=jwt(OWNER, now + 7200), expired=jwt(OWNER, now - 3600), foreign=jwt(FOREIGN, now + 7200))
    return value


class Recording:
    def __init__(self, p, secrets):
        self.p, self.secrets = p, secrets
        self.calls = []
        self.offline = False
        self.leak = set()
        self.interrupt = False
        self.after_probe = None
        self.keys = [deepcopy(JWK)]
        self.tunnel = {'id': p.get('tunnel'), 'name': 'synthetic-named', 'status': 'healthy',
                       'deleted_at': None, 'config_src': 'cloudflare'}
        self.app = {'id': p.get('application'), 'type': 'self_hosted', 'domain': p['host'], 'aud': 'SyntheticAudience'}
        self.apps = [self.app]
        self.policies = [{'decision': 'allow', 'include': [{'email': {'email': p['owner']}}], 'exclude': [], 'require': []}]
        self.config = {'ingress': [{'hostname': p['host'], 'service': f"http://127.0.0.1:{p['port']}",
                                   'originRequest': {'access': {'required': True, 'teamName': p.get('team'),
                                                               'audTag': ['SyntheticAudience']}}},
                                  {'service': 'http_status:404'}]}
        self.config_version = 7
        self.zones = [{'id': '4' * 32, 'name': 'synthetic.invalid', 'status': 'active', 'type': 'full',
                       'account': {'id': p.get('account')}}]
        self.dns = [{'id': '5' * 32, 'name': p['host'], 'type': 'CNAME', 'proxied': True,
                     'content': p.get('tunnel', '') + '.cfargotunnel.com'}]
        self.clients = [{'id': '66666666-6666-6666-6666-666666666666', 'config_version': 7,
                         'conns': [{'id': '77777777-7777-7777-7777-777777777777',
                                    'client_id': '66666666-6666-6666-6666-666666666666',
                                    'is_pending_reconnect': False}]}]
        self.device = {'nodeId': p.get('device'), 'name': p['host'], 'user': p['owner'], 'authorized': True,
                       'expires': datetime.fromtimestamp(time.time() + 7200, timezone.utc).isoformat(),
                       'addresses': ['100.100.100.10']}
        self.serve = {'TCP': {'443': {'HTTPS': True}},
                      'Web': {p['host'] + ':443': {'Handlers': {'/': {'Proxy': f"http://127.0.0.1:{p['port']}"}}}},
                      'AllowFunnel': {p['host'] + ':443': False}}
        self.status = {'BackendState': 'Running', 'Self': {'ID': p.get('device'), 'DNSName': p['host'] + '.',
                                                        'Online': True, 'Expired': False}}
        self.acl = {'acls': [{'action': 'accept', 'src': [p['owner']], 'dst': ['100.100.100.10:443']}]}
        self.validation_body = b''
        self.owner_report = lambda: {'schema': 'openwiz.setup.v1'}

    def local(self, kind):
        self.calls.append(('local-read', kind))
        if self.offline:
            raise OSError('synthetic offline')
        return deepcopy(self.status if kind == 'status' else self.serve)

    def request(self, method, url, headers, body=None):
        parsed = urlsplit(url)
        self.calls.append((method, parsed.netloc, parsed.path))
        if self.offline:
            raise OSError('synthetic offline')
        if self.interrupt:
            raise SystemExit('synthetic process stop before reply')
        def reply(value):
            return 200, json.dumps(value).encode()
        if parsed.netloc == self.p.get('team', '') + '.cloudflareaccess.com':
            assert method == 'GET' and parsed.path == '/cdn-cgi/access/certs' and not headers
            return reply({'keys': self.keys})
        if parsed.netloc == 'api.cloudflare.com':
            assert method == 'GET', 'fixture refuses any Cloudflare mutation'
            assert headers['Authorization'] == 'Bearer ' + self.secrets['api_token']
            if parsed.path.endswith('/zones'):
                assert parsed.query == 'account.id=' + self.p['account']
                value = self.zones
            elif parsed.path.endswith('/dns_records'):
                assert parsed.path == '/client/v4/zones/' + '4' * 32 + '/dns_records'
                assert parsed.query == 'name=' + self.p['host']
                value = self.dns
            elif parsed.path.endswith('/connections'):
                value = self.clients
            elif parsed.path.endswith('/configurations'):
                value = {'config': self.config, 'version': self.config_version, 'account_id': self.p.get('account'),
                         'tunnel_id': self.p.get('tunnel'), 'source': 'cloudflare'}
            elif parsed.path.endswith('/policies'):
                value = self.policies
            elif parsed.path.endswith('/access/apps'):
                value = self.apps
            elif '/access/apps/' in parsed.path:
                value = self.app
            elif '/cfd_tunnel/' in parsed.path:
                value = self.tunnel
            else:
                raise AssertionError('unknown Cloudflare read')
            envelope = {'success': True, 'result': value}
            if type(value) is list:
                envelope['result_info'] = {'total_count': len(value), 'page': 1}
            return reply(envelope)
        if parsed.netloc == 'api.tailscale.com':
            assert headers['Authorization'] == 'Bearer ' + self.secrets['api_token']
            if parsed.path.endswith('/validate'):
                assert method == 'POST'
                tests = json.loads(body)
                assert type(tests) is list, 'current-policy tests must be an array'
                for test in tests:
                    rules = self.acl['acls']
                    allowed = any(test['src'] in rule['src'] or '*' in rule['src'] for rule in rules)
                    if (test.get('accept') and not allowed) or (test.get('deny') and allowed):
                        return 400, b'Synthetic policy test failed'
                return 200, self.validation_body
            assert method == 'GET', 'fixture refuses any Tailscale mutation'
            return reply(self.acl if parsed.path.endswith('/acl') else self.device)
        assert parsed.netloc == self.p['host'] and method == 'GET', 'fixture refuses all work writes'
        if self.p['provider'] == 'tailscale':
            result = reply(self.owner_report())
        else:
            cookie = headers.get('Cookie', '')
            identity = next((key for key in ('owner', 'expired', 'foreign')
                             if cookie == 'CF_Authorization=' + self.secrets[key]), 'anonymous')
            result = reply(self.owner_report()) if identity == 'owner' or identity in self.leak else (403, b'Synthetic Access denial')
        if self.after_probe:
            callback, self.after_probe = self.after_probe, None
            callback()
        return result
