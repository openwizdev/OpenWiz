#!/usr/bin/env python3
"""The selector's CI side (#432, K15): where a map may come from, what each
job is told, and which runs trace their tests to make the next map.

  python3 -I ci/select/job.py traces --event E --ref R [--base B --head H]   # trace= and planted=
  python3 -I ci/select/job.py sign MAP.json OUT.jwt
  python3 -I ci/select/job.py select --plain FILE --map-dir DIR --repo OWNER/REPO
                                     --github-output FILE [--summary FILE]

**Where a map comes from.** A push to `main` and the nightly run trace their
tests (trace.py) and build a map (map.py). That run then asks GitHub for an
OIDC token (`id-token: write`, which ci.yml already has for cache.sh) whose
audience is bound to the map's SHA-256 (`sign`), and keeps both in GitHub's
cache. GitHub signs the token: the repository, ref, event, workflow and
commit of the run that asked. `select` uses a map only if that signature is
GitHub's (its published keys), for exactly this map, from a `push`,
`schedule` or `workflow_dispatch` (#783) run of this repository's
`.github/workflows/ci.yml` on `refs/heads/main`, at the map's own commit, and that commit is an ancestor
of the tested one. A pull request's run can ask for a token too, but GitHub
signs its ref (`refs/pull/N/merge`) and event, so nothing it keeps passes.

**What each job is told.** Only on decide.sh's plain case (DECIDE_PLAIN):
the selector's answer (pick.py), whose change is every path between the
map's commit and the tested one, so the drift on `main` since the trace
counts as changed. Anything else, missing, untrusted, unreadable or failing
is a full run: `selection=full`, every lane `all`. The answer goes to
GITHUB_OUTPUT as `selection`, `rust-tests` and `web-tests` (test ids, `all`
or `none`), K16's step/skill requirements (steps.py), and `web-files`
(the web tests' files under apps/web, for run-browser.mjs --only).

**Which runs trace.** A push to `main` and the nightly run, and a pull
request that changes the tracer itself (its own proof run, which selects
everything anyway: ci/select/ is a CI change).
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pick  # noqa: E402
import units as units_mod  # noqa: E402
import steps  # noqa: E402
import skills  # noqa: E402

ISSUER = 'https://token.actions.githubusercontent.com'
JWKS_URL = ISSUER + '/.well-known/jwks'
WORKFLOW = '.github/workflows/ci.yml'
MAIN = 'refs/heads/main'
TRUSTED_EVENTS = ('push', 'schedule', 'workflow_dispatch')
AUDIENCE = 'closedwiz-ci-select-map-'
# PKCS #1 v1.5's DigestInfo prefix for SHA-256 (RFC 8017, section 9.2).
DIGEST_INFO = bytes.fromhex('3031300d060960864801650304020105000420')
MIN_BITS = 2048
TRACER = {'ci/select/trace.py', 'ci/select/resolve.py', 'ci/select/map.py', 'ci/select/units.py'}
B64 = re.compile(r'[A-Za-z0-9_-]+')
FULL = {'selection': 'full', 'rust-tests': 'all', 'web-tests': 'all', 'web-files': 'all',
        'skill-tests': 'all', **dict.fromkeys(steps.FLAGS, 'true')}


class Untrusted(Exception):
    pass


def audience(data):
    """The OIDC audience that binds a token to exactly these map bytes."""
    return AUDIENCE + hashlib.sha256(data).hexdigest()


def b64decode(part):
    if not isinstance(part, str) or not B64.fullmatch(part):
        raise Untrusted('a token part is not base64url')
    try:
        return base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))
    except ValueError as e:
        raise Untrusted(f'a token part is not base64url: {e}') from e


def rsa_verify(n, e, message, signature):
    """RS256 (RSASSA-PKCS1-v1_5 with SHA-256): whether `signature` is n's."""
    if n.bit_length() < MIN_BITS:
        raise Untrusted(f'a {n.bit_length()}-bit key, under {MIN_BITS}')
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, 'big')
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, 'big')
    digest = DIGEST_INFO + hashlib.sha256(message).digest()
    want = b'\x00\x01' + b'\xff' * (k - 3 - len(digest)) + b'\x00' + digest
    return hmac.compare_digest(em, want)


def strict(raw):
    try:
        return pick.strict_json(raw.decode('utf-8'))
    except Exception as e:
        raise Untrusted(f'not one plain JSON object: {e}') from e


def verify(data, token, keys, repo, now=None):
    """The token's claims, if it proves these map bytes came from a push or
    the nightly run of ci.yml on this repository's main; else Untrusted."""
    parts = token.split('.') if isinstance(token, str) else []
    if len(parts) != 3:
        raise Untrusted('not a three-part token')
    header, body, sig = parts
    head = strict(b64decode(header))
    if not isinstance(head, dict) or head.get('alg') != 'RS256' or not isinstance(head.get('kid'), str):
        raise Untrusted('not an RS256 token with a key id')
    found = [k for k in (keys or {}).get('keys', []) if isinstance(k, dict) and k.get('kid') == head['kid']
             and k.get('kty') == 'RSA']
    if len(found) != 1:
        raise Untrusted(f'the issuer lists no one key {head["kid"]!r}')
    n = int.from_bytes(b64decode(found[0].get('n')), 'big')
    e = int.from_bytes(b64decode(found[0].get('e')), 'big')
    if not rsa_verify(n, e, f'{header}.{body}'.encode(), b64decode(sig)):
        raise Untrusted('the signature is not the issuer\'s')
    c = strict(b64decode(body))
    if not isinstance(c, dict):
        raise Untrusted('the claims are not an object')
    try:
        mp = pick.strict_json(data.decode('utf-8'))
        commit = mp['commit']
    except Exception as e:
        raise Untrusted(f'the map can\'t be read: {e}') from e
    want = {'iss': ISSUER, 'aud': audience(data), 'repository': repo, 'ref': MAIN, 'ref_type': 'branch',
            'workflow_ref': f'{repo}/{WORKFLOW}@{MAIN}', 'sha': commit}
    for key, value in want.items():
        if c.get(key) != value:
            raise Untrusted(f'{key} is {c.get(key)!r}, not {value!r}')
    if c.get('event_name') not in TRUSTED_EVENTS:
        raise Untrusted(f'event_name is {c.get("event_name")!r}, not a push, the nightly run or a manual dispatch')
    iat = c.get('iat')
    if isinstance(iat, bool) or not isinstance(iat, int) or iat > (now or time.time()) + 300:
        raise Untrusted('issued at no plain time, or in the future')
    return c


def fetch_jwks():
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(JWKS_URL, timeout=20) as r:
                return strict(r.read())
        except Exception as e:  # retried, then a full run
            last = e
            time.sleep(2 * (attempt + 1))
    raise OSError(f'GitHub\'s OIDC keys can\'t be read: {last}')


def traces(event, ref, paths):
    if event in TRUSTED_EVENTS:
        return ref == MAIN
    return event == 'pull_request' and any(p in TRACER for p in paths)


def plants(event, paths, has_map=True):
    """Whether this run plants planted.py's edits: a pull request that
    changes it, once a committed map (ci/select/map.json) exists to plant
    them against."""
    return event == 'pull_request' and 'ci/select/planted.py' in paths and has_map


def select(plain, map_dir, root, repo, keys, github_output, units_file=None, classify=True, summary=None,
           fetch_keys=fetch_jwks):
    answer = {**FULL, 'detail': ''}
    try:
        answer.update(_select(plain, map_dir, root, repo, keys, units_file, classify, fetch_keys))
    except Exception as e:  # anything unexpected: a full run
        answer['detail'] = f'the selector failed: {e}'
    with open(github_output, 'a') as f:
        for key in FULL:
            f.write(f'{key}={answer[key]}\n')
    line = (f'test selection: {answer["selection"]}: {answer["detail"]}\n'
            f'rust: {answer["rust-tests"]}\nweb: {answer["web-tests"]}\nskills: {answer["skill-tests"]}\n'
            + ''.join(f'{k}: {answer[k]}\n' for k in steps.FLAGS))
    sys.stderr.write(line)
    if summary:
        with open(summary, 'a') as f:
            f.write('### Test selection (#432)\n\n```text\n' + line + '```\n')
    return answer


def _select(plain, map_dir, root, repo, keys, units_file, classify, fetch_keys):
    def full(why):
        return {'detail': why}
    try:
        with open(plain) as f:
            is_plain = f.read().strip() == 'plain'
    except FileNotFoundError:
        is_plain = False
    if not is_plain:
        return full('not the plain case: decide.sh runs everything for this run')
    map_path, token_path = os.path.join(map_dir, 'map.json'), os.path.join(map_dir, 'map.jwt')
    if not (os.path.isfile(map_path) and os.path.isfile(token_path)):
        return full('no map from main (map.json and map.jwt) in the cache')
    with open(map_path, 'rb') as f:
        data = f.read()
    with open(token_path) as f:
        token = f.read().strip()
    try:
        claims = verify(data, token, keys if keys is not None else fetch_keys(), repo)
    except Untrusted as e:
        return full(f'an untrusted map: {e}')
    commit = claims['sha']
    ancestor = subprocess.run(['git', '-C', root, 'merge-base', '--is-ancestor', commit, 'HEAD'],
                              capture_output=True)
    if ancestor.returncode != 0:
        return full(f'the map\'s commit {commit} is not an ancestor of the tested commit')
    args = ['--map', map_path, '--root', root]
    if units_file:
        args += ['--units-file', units_file]
    if not classify:
        args.append('--no-classify')
    result = pick.main(args)
    lane = pick.lanes(result)
    reasons = '; '.join(json.dumps(r, sort_keys=True) for r in result.get('reasons', []))
    if result.get('mode') != 'selected' or 'all' in lane.values():
        return full(f'the selector runs everything: {reasons or "no answer"}')
    files = 'none'
    if lane['web'] != 'none':
        paths = units_mod.web_units(root)
        files = ' '.join(sorted(paths[t] for t in lane['web'].split()))
    mp = pick.strict_json(data.decode('utf-8'))
    step_plan = steps.plan(result['tests'], pick.diff(root, commit, 'HEAD'), pick.check_map(mp), root, classify)
    run = len(result['tests'])
    return {**step_plan, 'selection': 'selected', 'rust-tests': lane['rust'], 'web-tests': lane['web'], 'web-files': files,
            'detail': f'map of {commit} (run {claims.get("run_id")}, {claims["event_name"]}); '
                      f'{run} tests run, {len(result["skipped"])} skipped'}


def validate(path):
    """Read one complete output bundle; any uncertainty restores the full run.
    This is the action boundary, including duplicate/missing keys and values.
    """
    try:
        with open(path) as f:
            pairs = [line.rstrip('\n').split('=', 1) for line in f]
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError('duplicate output')
            out[key] = value
        if set(out) != set(FULL):
            raise ValueError('missing or unknown output')
        if out['selection'] == 'full':
            if out != FULL:
                raise ValueError('partial full run')
        elif out['selection'] == 'selected':
            for key in steps.FLAGS:
                if out[key] not in ('true', 'false'):
                    raise ValueError('not a boolean')
            if not skills.valid(out['skill-tests']) or out['skill-tests'] == 'all':
                raise ValueError('unknown skill selection')
            for lane in ('rust', 'web'):
                value = out[lane + '-tests']
                if value == 'none':
                    continue
                ids = value.split(' ')
                if len(ids) != len(set(ids)) or not all(pick.TEST_ID.fullmatch(t) and t.startswith(lane + ':') for t in ids):
                    raise ValueError('unknown test selection')
            files = out['web-files']
            if out['web-tests'] == 'none':
                if files != 'none':
                    raise ValueError('files for no web test')
            else:
                ids = sorted(out['web-tests'].split(' '))
                paths = files.split(' ')
                if len(paths) != len(set(paths)) or any(pick.odd_path(p) for p in paths) or not all(re.fullmatch(
                        r'test/(unit/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.test\.ts|'
                        r'browser/(?:[A-Za-z0-9._-]+/)*[A-Za-z0-9._-]+\.test\.mjs)', p) for p in paths):
                    raise ValueError('unknown web files')
                file_ids = sorted('web:' + ('unit:' if p.startswith('test/unit/') else 'browser:') +
                                  os.path.basename(p).split('.test.')[0] for p in paths)
                if ids != file_ids:
                    raise ValueError('web ids and files differ')
            if (out['export-rust'] == 'true' or out['export-web'] == 'true') and out['build-web'] != 'true':
                raise ValueError('an export consumer needs its producer')
            if out['image-skills'] != ('true' if 'image' in skills.selected(out['skill-tests']) else 'false'):
                raise ValueError('image suite needs its dependencies')
        else:
            raise ValueError('unknown selection mode')
        return out
    except Exception:
        return dict(FULL)


def sign(map_path, out):
    """Ask GitHub for this job's OIDC token, bound to the map's bytes."""
    url, bearer = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL'), os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
    if not url or not bearer:
        raise SystemExit('job: no OIDC token to ask GitHub for: ci.yml needs permissions: id-token: write')
    with open(map_path, 'rb') as f:
        aud = audience(f.read())
    req = urllib.request.Request(url + '&audience=' + urllib.parse.quote(aud, safe=''),
                                 headers={'Authorization': 'bearer ' + bearer})
    with urllib.request.urlopen(req, timeout=30) as r:
        value = strict(r.read()).get('value')
    if not isinstance(value, str) or value.count('.') != 2:
        raise SystemExit('job: GitHub gave no token')
    with open(out, 'w') as f:
        f.write(value + '\n')
    print(f'job: the map is signed for {aud}')


def main(argv):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    t = sub.add_parser('traces')
    t.add_argument('--event', required=True)
    t.add_argument('--ref', required=True)
    t.add_argument('--base', default='')
    t.add_argument('--head', default='')
    v = sub.add_parser('validate')
    v.add_argument('path')
    s = sub.add_parser('sign')
    s.add_argument('map')
    s.add_argument('out')
    c = sub.add_parser('select')
    c.add_argument('--plain', required=True)
    c.add_argument('--map-dir', required=True)
    c.add_argument('--repo', required=True)
    c.add_argument('--github-output', required=True)
    c.add_argument('--summary')
    args = ap.parse_args(argv)
    if args.cmd == 'traces':
        paths = []
        if args.event == 'pull_request':
            out = subprocess.run(['git', 'diff', '--no-renames', '--name-only', f'{args.base}...{args.head}'],
                                 capture_output=True, text=True)
            # A diff that can't be read changes no tracer: the run doesn't trace.
            paths = out.stdout.splitlines() if out.returncode == 0 else []
        print(f'trace={"true" if traces(args.event, args.ref, paths) else "false"}')
        has_map = os.path.isfile(os.path.join(HERE, 'map.json'))
        print(f'planted={"true" if plants(args.event, paths, has_map) else "false"}')
    elif args.cmd == 'validate':
        for key, value in validate(args.path).items():
            print(f'{key}={value}')
    elif args.cmd == 'sign':
        sign(args.map, args.out)
    else:
        select(plain=args.plain, map_dir=args.map_dir, root='.', repo=args.repo, keys=None,
               github_output=args.github_output, summary=args.summary)


if __name__ == '__main__':
    main(sys.argv[1:])
