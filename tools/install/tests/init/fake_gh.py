#!/usr/bin/env python3
import base64
import json
import os
import sys
import urllib.parse

WORLD = os.environ.get('FAKE_GH_WORLD') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                                                         'world.json')


INCLUDE = True


def reply(status, body=None):
    if not INCLUDE:
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
    if fault is not None:
        sys.stderr.write('connection reset\n')
        return 1
    return reply(status, value)


def save(world):
    with open(WORLD + '.tmp', 'w') as handle:
        json.dump(world, handle)
    os.replace(WORLD + '.tmp', WORLD)


def repo_view(r):
    keys = ('id', 'full_name', 'private', 'visibility', 'default_branch', 'permissions', 'owner', 'description', 'homepage')
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
        repos[key] = {'id': 100 + len(repos), 'full_name': f"{owner}/{body['name']}", 'private': body['private'],
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
        details = repo.setdefault('label_details', {})
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
    if rest[:1] == ['pulls'] and len(rest) > 1:
        pull = next((p for p in repo['pulls'] if str(p['number']) == rest[1]), None)
        if pull is None:
            return 404, {'message': 'Not Found'}
        base = pull.get('base', repo['default_branch'])
        if method == 'GET' and len(rest) == 2:
            return 200, {'number': pull['number'], 'state': pull['state'], 'merged_at': pull.get('merged_at'),
                         'head': {'ref': pull['head'], 'sha': pull.get('sha', 'f' * 40)}, 'base': {'ref': base}}
        if method == 'PUT' and rest[2:] == ['merge']:
            if pull['state'] != 'open':
                return 405, {'message': 'Pull Request is not mergeable'}
            if body.get('sha') != pull.get('sha', 'f' * 40):
                return 409, {'message': 'Head branch was modified'}
            repo['branches'][base].update(repo['branches'][pull['head']])
            pull.update(state='closed', merged_at='2026-01-01T00:00:00Z')
            return 200, {'merged': True, 'sha': 'e' * 40, 'message': 'Pull Request successfully merged'}
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
                                  'title': body['title'], 'body': body['body'], 'sha': 'f' * 40})
            return 201, {'number': number, 'state': 'open', 'head': {'ref': body['head'], 'sha': 'f' * 40}}
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
