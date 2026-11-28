#!/usr/bin/env python3
ABOUT = """A synthetic Sprites gateway for the GitHub connector, for the tests of the driver's `openwiz-push` helper.

`python3 -I gateway.py <bare repository> <owner/name> <log file>` serves GitHub's REST Git Database API
(https://docs.github.com/en/rest/git) for that one repository on 127.0.0.1, prints its port on one line, and runs
until it is ended. The repository's objects and refs stand in for GitHub's, written with git's own plumbing, so every
sha is the one GitHub would compute for the same object. It answers: GET git/ref/heads/<branch>, GET
git/commits/<sha>, POST git/blobs, git/trees (with base_tree, and entries whose sha is null delete a path),
git/commits and git/refs, and PATCH git/refs/heads/<branch>, which refuses with 422 an update that is not a fast
forward unless force is true. Like GitHub, it writes commit dates in UTC, so a commit made in another time zone gets
another sha; with FAKE_GATEWAY_TRIM_MESSAGES set, it also drops the newlines that end a commit message, so every
commit gets another sha. As the real gateway does, it attaches the credential itself: a request that carries an Authorization
header is refused with 400. Each request is appended to the log file as one JSON object: method, path, header
names and the body's force value."""
import base64, http.server, json, os, re, subprocess, sys, tempfile
from datetime import datetime, timezone

BARE, REPO, LOG = sys.argv[1], sys.argv[2], sys.argv[3]
SHA = r'[0-9a-f]{40}'
BRANCH = r'[A-Za-z0-9._/-]+'


def git(*args, data=None, env=None):
    p = subprocess.run(['git', '--git-dir', BARE] + list(args), input=data, capture_output=True,
                       env=dict(os.environ, **(env or {})))
    return p.returncode, p.stdout.decode().strip()


def utc(date):
    return datetime.fromisoformat(date.replace('Z', '+00:00')).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def ref_of(branch):
    code, sha = git('rev-parse', '--verify', '-q', 'refs/heads/' + branch)
    return sha if code == 0 else None


def tree(body):
    index = tempfile.mktemp()
    env = {'GIT_INDEX_FILE': index}
    try:
        if body.get('base_tree'):
            if git('read-tree', body['base_tree'], env=env)[0]:
                return 422, {'message': 'Invalid base_tree'}
        else:
            git('read-tree', '--empty', env=env)
        rows = []
        for item in body['tree']:
            if item.get('sha') is None:
                rows.append('0 %s\t%s\n' % ('0' * 40, item['path']))
                continue
            if item['type'] == 'blob' and git('cat-file', '-e', item['sha'])[0]:
                return 422, {'message': 'Invalid tree info'}
            rows.append('%s %s\t%s\n' % (item['mode'], item['sha'], item['path']))
        if git('update-index', '--index-info', data=''.join(rows).encode(), env=env)[0]:
            return 422, {'message': 'Invalid tree info'}
        return 201, {'sha': git('write-tree', env=env)[1]}
    finally:
        if os.path.exists(index):
            os.remove(index)


def commit(body):
    args = ['commit-tree', body['tree']]
    for parent in body['parents']:
        args += ['-p', parent]
    env = {}
    for role, key in (('author', 'AUTHOR'), ('committer', 'COMMITTER')):
        who = body[role]
        env.update({'GIT_%s_NAME' % key: who['name'], 'GIT_%s_EMAIL' % key: who['email'],
                    'GIT_%s_DATE' % key: utc(who['date'])})
    message = body['message'].rstrip('\n') if os.environ.get('FAKE_GATEWAY_TRIM_MESSAGES') else body['message']
    code, sha = git(*args, data=message.encode(), env=env)
    return (201, {'sha': sha}) if code == 0 else (422, {'message': 'Invalid commit'})


class Gateway(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, method):
        length = int(self.headers.get('Content-Length') or 0)
        body = json.loads(self.rfile.read(length) or b'null')
        with open(LOG, 'a') as f:
            f.write(json.dumps({'method': method, 'path': self.path, 'headers': sorted(self.headers.keys()),
                                'force': body.get('force') if isinstance(body, dict) else None}) + '\n')
        if 'Authorization' in self.headers:
            return self.answer(400, {'message': 'the gateway attaches the credential; send no Authorization header'})
        prefix = '/repos/%s/git/' % REPO
        if not self.path.startswith(prefix):
            return self.answer(404, {'message': 'Not Found'})
        rest = self.path[len(prefix):]
        if method == 'GET' and re.fullmatch('ref/heads/' + BRANCH, rest):
            sha = ref_of(rest[len('ref/heads/'):])
            return self.answer(200, {'ref': 'refs/' + rest[4:], 'object': {'sha': sha, 'type': 'commit'}}) if sha \
                else self.answer(404, {'message': 'Not Found'})
        if method == 'GET' and re.fullmatch('commits/' + SHA, rest):
            sha = rest[len('commits/'):]
            if git('cat-file', '-t', sha)[1] != 'commit':
                return self.answer(404, {'message': 'Not Found'})
            return self.answer(200, {'sha': sha, 'tree': {'sha': git('rev-parse', sha + '^{tree}')[1]}})
        if method == 'POST' and rest == 'blobs':
            if body.get('encoding') != 'base64':
                return self.answer(422, {'message': 'encoding must be base64 here'})
            code, sha = git('hash-object', '-w', '--stdin', data=base64.b64decode(body['content']))
            return self.answer(201, {'sha': sha})
        if method == 'POST' and rest == 'trees':
            return self.answer(*tree(body))
        if method == 'POST' and rest == 'commits':
            return self.answer(*commit(body))
        if method == 'POST' and rest == 'refs':
            if not re.fullmatch('refs/heads/' + BRANCH, body.get('ref', '')) or ref_of(body['ref'][11:]):
                return self.answer(422, {'message': 'Reference already exists'})
            if git('update-ref', body['ref'], body['sha'], '0' * 40)[0]:
                return self.answer(422, {'message': 'Object does not exist'})
            return self.answer(201, {'ref': body['ref'], 'object': {'sha': body['sha']}})
        if method == 'PATCH' and re.fullmatch('refs/heads/' + BRANCH, rest):
            old = ref_of(rest[len('refs/heads/'):])
            if old is None:
                return self.answer(422, {'message': 'Reference does not exist'})
            if not body.get('force') and git('merge-base', '--is-ancestor', old, body['sha'])[0]:
                return self.answer(422, {'message': 'Update is not a fast forward'})
            git('update-ref', rest, body['sha'], old)
            return self.answer(200, {'ref': rest, 'object': {'sha': body['sha']}})
        return self.answer(404, {'message': 'Not Found'})

    def do_GET(self):
        self.handle_any('GET')

    def do_POST(self):
        self.handle_any('POST')

    def do_PATCH(self):
        self.handle_any('PATCH')


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
print(server.server_address[1], flush=True)
server.serve_forever()
