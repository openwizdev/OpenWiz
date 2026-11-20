#!/usr/bin/env python3
"""A recording stand-in for `gh api --include` (and setup.py's plain `gh api PATH`)
over a synthetic GitHub world.

Test-only: copied into a scratch bin directory as `gh`. The world is JSON at
$FAKE_GH_WORLD (else `../world.json` beside its bin directory); every call is appended to its `log` (method, path), so tests
count provider effects. `faults` rows `{method, path, mode, times}` plant
`lose` (the effect happens, the reply is lost), `drop` (no effect, no reply),
`taken` (someone else makes it first with the row's `body` fields, then the
call gets 422) or a status number (refused, no effect). Synthetic values only.
"""
import base64
import json
import os
import sys
import urllib.parse

# The installed CLI forwards no test variable, so the fake also finds the
# world beside its own bin directory.
WORLD = os.environ.get('FAKE_GH_WORLD') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                                         'world.json')


INCLUDE = True


def reply(status, body=None):
    if not INCLUDE:  # setup.py's plain `gh api PATH` read: the body only
        sys.stdout.write(json.dumps(body))
        return 0 if status < 400 else 1
    reason = {200: 'OK', 201: 'Created', 404: 'Not Found'}.get(status, 'Status')
    sys.stdout.write(f'HTTP/2.0 {status} {reason}\r\nContent-Type: application/json\r\n\r\n')
    if body is not None:
        sys.stdout.write(json.dumps(body))
    return 0 if status < 400 else 1


def main(argv):
    global INCLUDE
    if len(argv) == 2 and argv[0] == 'api':
        INCLUDE, argv = False, ['api', '--include', '-X', 'GET', argv[1]]
    assert argv[:4] == ['api', '--include', '-X', argv[3]], argv
    method, target = argv[3], argv[4]
    body = json.loads(sys.stdin.read()) if argv[5:] == ['--input', '-'] else None
    assert argv[5:] in ([], ['--input', '-']), argv
    with open(WORLD) as handle:
        world = json.load(handle)
    world['log'].append([method, target])
    fault = next((f for f in world['faults'] if f['method'] == method and target.startswith(f['path'])
                  and f['times'] > 0), None)
    if fault is not None:
        fault['times'] -= 1
    if fault is not None and fault['mode'] == 'taken':
        handle_call(world, method, target, dict(body, **fault.get('body', {})))
        save(world)
        return reply(422, {'message': 'already_exists'})
    if fault is not None and fault['mode'] != 'lose':
        save(world)
        if fault['mode'] == 'drop':
            sys.stderr.write('connection reset\n')
            return 1
        return reply(fault['mode'], {'message': 'synthetic refusal'})
    status, value = handle_call(world, method, target, body)
    save(world)
    if fault is not None:  # lose: the effect stands, its reply never arrives
        sys.stderr.write('connection reset\n')
        return 1
    return reply(status, value)


def save(world):
    with open(WORLD + '.tmp', 'w') as handle:
        json.dump(world, handle)
    os.replace(WORLD + '.tmp', WORLD)


def repo_view(r):
    keys = ('full_name', 'private', 'visibility', 'default_branch', 'permissions', 'owner', 'description', 'homepage')
    return {k: r[k] for k in keys if k in r}


def handle_call(world, method, target, body):
    parts = urllib.parse.urlsplit(target)
    path = [urllib.parse.unquote(p) for p in parts.path.split('/')]
    query = dict(urllib.parse.parse_qsl(parts.query))
    repos = world['repos']
    if method == 'GET' and path == ['user']:
        return 200, world['user']
    if method == 'POST' and (path == ['user', 'repos'] or path[:1] == ['orgs']):
        owner = world['user']['login'] if path[0] == 'user' else path[1]
        key = f"{owner}/{body['name']}".lower()
        if key in repos:
            return 422, {'message': 'name already exists'}
        repos[key] = {'full_name': f"{owner}/{body['name']}", 'private': body['private'],
                      'visibility': 'private' if body['private'] else 'public', 'default_branch': 'main',
                      'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'},
                      'description': body.get('description'), 'homepage': None,
                      'labels': [], 'pulls': [], 'branches': {'main': {}} if body.get('auto' '_init') else {}}
        return 201, repo_view(repos[key])
    if path[0] != 'repos' or len(path) < 3:
        return 404, {'message': 'Not Found'}
    key = f'{path[1]}/{path[2]}'.lower()
    repo = repos.get(key)
    if repo is None or repo.get('hidden'):
        return 404, {'message': 'Not Found'}
    rest = path[3:]
    if not rest:
        if method == 'GET':
            return 200, repo_view(repo)
        if method == 'PATCH':
            repo.update(body)
            return 200, repo_view(repo)
    if rest[:1] == ['labels']:
        details = repo.setdefault('label_details', {})  # name -> colour and description, as created
        if method == 'GET' and len(rest) == 2:
            if rest[1] not in repo['labels']:
                return 404, {'message': 'Not Found'}
            return 200, dict(details.get(rest[1], {}), name=rest[1])
        if method == 'POST' and len(rest) == 1:
            if body['name'] in repo['labels']:
                return 422, {'message': 'already_exists'}
            repo['labels'].append(body['name'])
            details[body['name']] = {k: body[k] for k in ('color', 'description') if k in body}
            return 201, dict(details[body['name']], name=body['name'])
    if rest[:1] == ['pulls']:
        if method == 'GET':
            head = query.get('head', '').split(':', 1)[-1]
            return 200, [{'number': p['number'], 'state': p['state'], 'merged_at': p.get('merged_at'),
                          'head': {'ref': p['head']}} for p in repo['pulls'] if p['head'] == head]
        if method == 'POST':
            if any(p['head'] == body['head'] and p['state'] == 'open' for p in repo['pulls']):
                return 422, {'message': 'A pull request already exists'}
            number = 1 + max([p['number'] for p in repo['pulls']] + [0])
            repo['pulls'].append({'number': number, 'state': 'open', 'head': body['head'], 'base': body['base'],
                                  'title': body['title'], 'body': body['body']})
            return 201, {'number': number, 'state': 'open'}
    if rest[:3] == ['git', 'ref', 'heads']:
        branch = '/'.join(rest[3:])
        if branch in repo['branches']:
            return 200, {'object': {'sha': 'f' * 40}}
        return 404, {'message': 'Not Found'}
    if rest[:2] == ['git', 'refs'] and method == 'POST':
        branch = body['ref'].removeprefix('refs/heads/')
        if branch in repo['branches']:
            return 422, {'message': 'Reference already exists'}
        repo['branches'][branch] = dict(repo['branches'][repo['default_branch']])
        return 201, {'ref': body['ref']}
    if rest[:1] == ['contents']:
        file = '/'.join(rest[1:])
        branch = repo['branches'].get(query.get('ref') or body and body.get('branch') or repo['default_branch'])
        if branch is None:
            return 404, {'message': 'No commit found for the ref'}
        if method == 'GET':
            if file not in branch:
                return 404, {'message': 'Not Found'}
            return 200, {'encoding': 'base64', 'content': base64.b64encode(branch[file].encode()).decode()}
        if method == 'PUT':
            if file in branch:
                return 422, {'message': 'sha wasn\'t supplied'}
            branch[file] = base64.b64decode(body['content']).decode()
            return 201, {'content': {'path': file}}
    return 404, {'message': 'Not Found'}


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
