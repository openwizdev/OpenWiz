#!/usr/bin/env python3
# SECURITY: the one place a host API key is ever read (driver v1 N4). The key is never printed, logged, cached or put
# on a command line, and no error text, answer or child process's arguments or environment carries it: every error
# is a fixed text naming only registry names, never a value the driver sent or the host answered.
import json
import os
import re
import subprocess
import sys
import urllib.parse

TLS_ENVIRONMENT = ('OPENSSL_', 'SSL_', 'SSLKEYLOGFILE')
NATIVE_TLS = ('_ssl', '_hashlib')


def scrub_tls_environment():
    for name in [n for n in os.environ if n.startswith(TLS_ENVIRONMENT)]:
        del os.environ[name]


# SECURITY: native TLS reads OPENSSL_CONF and friends when it loads, so they go before anything can import ssl.
scrub_tls_environment()

HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, 'hosts.json')
OVERRIDE = 'OPENWIZ_HOSTKEY_TEST_ORIGIN'
KEY_PATH = '/.openwiz/hostkey-test-key'
TOOLS = {'linux': ['/usr/bin/secret-tool', 'lookup', 'service'],
         'darwin': ['/usr/bin/security', 'find-generic-password', '-w', '-s']}
TOOL_ENVIRONMENT = {'linux': ('HOME', 'LANG', 'DBUS_SESSION_BUS_ADDRESS', 'XDG_RUNTIME_DIR'), 'darwin': ('HOME', 'LANG')}
METHODS = ('GET', 'POST', 'DELETE')
FIELDS = ('origin', 'variable', 'keychain', 'header')
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
ENTRY = {'origin': re.compile(r'https://[a-z0-9]+(?:-[a-z0-9]+)*(?:\.[a-z0-9]+(?:-[a-z0-9]+)*)+'),
         'variable': re.compile(r'[A-Z][A-Z0-9_]{0,63}'),
         'keychain': re.compile(r'[a-z0-9]+(?:[.-][a-z0-9]+)*'),
         'header': re.compile(r'authorization-bearer')}
TEST_ORIGIN = re.compile(r'http://127\.0\.0\.1:([1-9][0-9]{0,4})')
PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=/?%-]*")
KEY = re.compile(r'[A-Za-z0-9._~+/=-]{16,4096}')
KEY_FORMAT = 'a key of 16 to 4096 letters, digits or ._~+/=-'
LIMIT = 1 << 20
SCHEMA = 'send exactly host, method, path and an optional body, as kernel/driver-kit/README.md shows'
_key = []
FALLBACK = {'error': 'the answer held the key, so the helper did not print it', 'next': 'report it to OpenWiz'}
LAST_RESORT = {'error': 'refused', 'next': 'retry'}
SILENT = ''
UNREACHABLE = 'the helper could not reach the host, or its answer was unreadable'


class Refused(Exception):
    pass


def _unique(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise Refused('a key is repeated in the input', 'send each key once')
    return dict(pairs)


def _no_constant(name):
    raise ValueError(name)


def registry(path=REGISTRY):
    bad = Refused('kernel/driver-kit/hosts.json is not a valid registry', 'restore it from OpenWiz')
    try:
        with open(path, 'rb') as f:
            hosts = json.loads(f.read().decode('utf-8'), object_pairs_hook=_unique, parse_constant=_no_constant)
    except (OSError, ValueError, RecursionError, Refused):
        raise bad
    if not isinstance(hosts, dict) or not hosts:
        raise bad
    for name, entry in hosts.items():
        if not (len(name) <= 40 and NAME.fullmatch(name)) or not isinstance(entry, dict) or set(entry) != set(FIELDS):
            raise bad
        if not all(isinstance(entry[k], str) and ENTRY[k].fullmatch(entry[k]) for k in FIELDS):
            raise bad
    return hosts


def path_fault(path):
    if not isinstance(path, str):
        return 'path is not a string'
    if not path.startswith('/'):
        return 'path is not absolute'
    if len(path) > 2048:
        return 'path is longer than 2048 characters'
    decoded = urllib.parse.unquote(path, errors='strict') if '%' in path and _escapes_ok(path) else path
    for text in (path, decoded):
        if any(ord(c) < 0x20 or ord(c) == 0x7f for c in text):
            return 'path has a control character'
        for part, what in (('//', '// (a host)'), ('..', '..'), ('\\', 'a backslash'), ('@', '@ (user info)'),
                           ('#', '#'), (':', 'a scheme or a port')):
            if part in text:
                return 'path has ' + what
    if not PATH.fullmatch(path):
        return 'path has a character outside letters, digits and -._~!$&\'()*+,;=/?%'
    if not _escapes_ok(path):
        return 'path has a percent sign that is not a %XX escape'
    if '%' in decoded:
        return 'path is percent-encoded twice'
    if any(ord(c) > 0x7e for c in decoded):
        return 'path has an escape outside printable ASCII'
    return None


def _escapes_ok(path):
    try:
        urllib.parse.unquote(path, errors='strict')
    except UnicodeDecodeError:
        return False
    return not re.search(r'%(?![0-9A-Fa-f]{2})', path)


def read_request(text, hosts):
    try:
        req = json.loads(text, object_pairs_hook=_unique, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        raise Refused('the input is not one JSON object', SCHEMA)
    if not isinstance(req, dict) or not {'host', 'method', 'path'} <= set(req) <= {'host', 'method', 'path', 'body'}:
        raise Refused('the input needs exactly host, method, path and an optional body', SCHEMA)
    if not isinstance(req['host'], str):
        raise Refused('host is not a string', SCHEMA)
    if req['host'] not in hosts:
        raise Refused('host is not in kernel/driver-kit/hosts.json',
                      'use a registered host name; adding a host is a reviewed change to hosts.json')
    if req['method'] not in METHODS or not isinstance(req['method'], str):
        raise Refused('method is not GET, POST or DELETE', SCHEMA)
    why = path_fault(req['path'])
    if why:
        raise Refused(why, 'send only the path below the host, such as /v1/things, never an address')
    if 'body' in req and not isinstance(req['body'], dict):
        raise Refused('body is not an object', SCHEMA)
    return req


def test_origin(environ):
    if OVERRIDE not in environ:
        return None
    m = TEST_ORIGIN.fullmatch(environ[OVERRIDE])
    if not m or int(m.group(1)) > 65535:
        raise Refused('OPENWIZ_HOSTKEY_TEST_ORIGIN is not http://127.0.0.1:<port>, so the helper will not run',
                      'unset it: it is only for the kit\'s tests, which point it at a loopback fake host')
    return environ[OVERRIDE]


def find_key(entry, environ):
    variable, keychain = entry['variable'], entry['keychain']
    names = '%s or the keychain entry %s' % (variable, keychain)
    if OVERRIDE in environ:
        # SECURITY: under the loopback override the key comes only from the kit's fake host, never a production
        # source, and never through the driver's environment.
        key, where = fetch_test_key(test_origin(environ)), 'the kit\'s fake host'
        if not key:
            raise Refused('the kit\'s fake host gave no test key; under %s the helper never reads %s'
                          % (OVERRIDE, names), 'unset %s: it is only for the kit\'s tests' % OVERRIDE)
    else:
        key, where = environ.get(variable, ''), variable
        if not key:
            key, where = _keychain(keychain, environ), keychain
        if not key:
            raise Refused('no key in either %s' % names, 'set %s, or add the key to your keychain as %s; OpenWiz '
                          'never stores it' % (variable, keychain))
    _key.append(key)
    if not KEY.fullmatch(key):
        raise Refused('the key in %s is not %s' % (where, KEY_FORMAT), 'store the key alone, as the host gave it, '
                      'in %s' % names)
    return key


def fetch_test_key(origin):
    import http.client
    host, _, port = origin.partition('://')[2].partition(':')
    try:
        conn = http.client.HTTPConnection(host, int(port), timeout=60)
        try:
            conn.request('GET', KEY_PATH, headers={'User-Agent': 'openwiz-hostkey/1'})
            answer = conn.getresponse()
            status, raw = answer.status, answer.read(LIMIT + 1)
        finally:
            conn.close()
    except (OSError, http.client.HTTPException, ValueError):
        raise Refused(UNREACHABLE, 'check your network and the host\'s status, then retry')
    try:
        value = json.loads(raw.decode('utf-8'), parse_constant=_no_constant) if status == 200 else None
    except (ValueError, RecursionError):
        return ''
    if not isinstance(value, dict) or set(value) != {'key'} or not isinstance(value['key'], str):
        return ''
    return value['key']


def _keychain(entry, environ):
    platform = 'darwin' if sys.platform == 'darwin' else 'linux' if sys.platform.startswith('linux') else None
    if platform is None:
        return ''
    env = {k: environ[k] for k in TOOL_ENVIRONMENT[platform] if k in environ}
    env['PATH'] = '/usr/bin:/bin'
    try:
        p = subprocess.run(TOOLS[platform] + [entry], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, env=env, timeout=60)
        out = p.stdout.decode('utf-8')
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return ''
    if p.returncode:
        return ''
    return out[:-1] if out.endswith('\n') else out


def send(origin, method, path, body, key):
    import http.client
    import ssl
    scheme, _, hostport = origin.partition('://')
    host, _, port = hostport.partition(':')
    headers = {'Authorization': 'Bearer ' + key, 'Accept': 'application/json', 'User-Agent': 'openwiz-hostkey/1'}
    data = None
    try:
        if body is not None:
            data = json.dumps(body, allow_nan=False).encode('utf-8')
            headers['Content-Type'] = 'application/json'
        if scheme == 'https':
            scrub_tls_environment()
            conn = http.client.HTTPSConnection(host, int(port or 443), timeout=60,
                                               context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(host, int(port), timeout=60)
        try:
            conn.request(method, path, body=data, headers=headers)
            answer = conn.getresponse()
            status, raw = answer.status, answer.read(LIMIT + 1)
        finally:
            conn.close()
    except ssl.SSLError:
        raise Refused('TLS verification of the host failed', 'check the host\'s address and your system\'s '
                      'certificates; the helper trusts only the system defaults')
    except (OSError, http.client.HTTPException, ValueError, RecursionError):
        raise Refused(UNREACHABLE,
                      'check your network and the host\'s status, then retry')
    if len(raw) > LIMIT:
        raise Refused('the host answered more than 1 MiB', 'ask the host for a smaller answer')
    return status, raw


def _strings(value):
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            stack += list(v) + list(v.values())
        elif isinstance(v, list):
            stack += v


def answer(status, raw, key):
    try:
        body = json.loads(raw.decode('utf-8'), parse_constant=_no_constant) if raw else None
        json.dumps(body, allow_nan=False)
    except (ValueError, RecursionError):
        body = None
    if key.encode('utf-8') in raw or any(key in s for s in _strings(body)):
        raise Refused('the host\'s answer held the key, so the helper did not pass it on',
                      'check the host: it should never send a key back')
    return {'status': status, 'body': body}


def screen(req, key):
    sent = [req['path'], urllib.parse.unquote(req['path'])]
    if 'body' in req:
        try:
            dumped = json.dumps(req['body'], allow_nan=False)
        except (ValueError, RecursionError):
            raise Refused('the input is not one JSON object', SCHEMA)
        sent += [dumped] + list(_strings(req['body']))
    if any(key in text for text in sent):
        raise Refused('the request holds the key, so the helper did not send it',
                      'send the request without the key; the helper adds it to the header itself')


def render(out, keys):
    for answer, code in ((out, None), (FALLBACK, 1), (LAST_RESORT, 1)):
        text = json.dumps(answer)
        if not any(k in s for k in keys for s in [text] + list(_strings(answer))):
            return text, code
    return SILENT, 1


def run(stdin, environ):
    if not sys.flags.isolated:
        raise Refused('the helper runs only in Python\'s isolated mode', 'run it as python3 -I '
                      'kernel/driver-kit/hostkey.py')
    if any(m in sys.modules for m in NATIVE_TLS):
        raise Refused('native TLS loaded before the helper cleared its environment', 'report it to OpenWiz')
    override = test_origin(environ)
    hosts = registry()
    data = stdin.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise Refused('the input is larger than 1 MiB', SCHEMA)
    try:
        text = data.decode('utf-8')
    except UnicodeDecodeError:
        raise Refused('the input is not one JSON object', SCHEMA)
    req = read_request(text, hosts)
    entry = hosts[req['host']]
    origin = override or entry['origin']
    target = urllib.parse.urlsplit(origin + req['path'])
    if (target.scheme, target.netloc) != tuple(urllib.parse.urlsplit(origin)[:2]):
        raise Refused('path would leave the registered address', 'send only the path below the host')
    key = find_key(entry, environ)
    screen(req, key)
    status, raw = send(origin, req['method'], req['path'], req.get('body'), key)
    return answer(status, raw, key)


def main():
    os.dup2(os.open(os.devnull, os.O_WRONLY), 2)
    try:
        out, code = run(sys.stdin.buffer, os.environ), 0
    except Refused as e:
        out, code = {'error': e.args[0], 'next': e.args[1]}, 1
    except BaseException as e:
        out, code = {'error': 'the key helper failed: ' + type(e).__name__, 'next': 'report it to OpenWiz'}, 1
    text, gated = render(out, _key)
    code = gated or code
    sys.stdout.write(text + '\n' if text else text)
    sys.stdout.flush()
    sys.exit(code)


if __name__ == '__main__':
    main()
