#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FLEET_GH = Path(__file__).resolve().parents[4] / 'skills/launch-fleet/scripts/fixtures/gh.py'
INIT_GH = Path(__file__).resolve().parents[1] / 'init/fake_gh.py'
FIELDS = {'nameWithOwner', 'isPrivate', 'defaultBranchRef'}


def repository(owner, name, branches):
    return {'full_name': '%s/%s' % (owner, name), 'private': True, 'visibility': 'private',
            'default_branch': 'main', 'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'},
            'description': None, 'homepage': None, 'labels': [], 'pulls': [], 'branches': branches}


def demo(argv):
    path = os.environ['FAKE_GH_REPOS']
    state = json.loads(Path(path).read_text())
    with open(os.environ['FAKE_GH_CREATE_LOG'], 'a') as log:
        log.write(json.dumps(argv) + '\n')
    if state.get('signed_out'):
        sys.stderr.write('To get started with GitHub CLI, please run: gh auth login\n')
        return 1
    name = argv[2]
    found = state['repos'].get(name.lower())
    if argv[1] == 'view' and state.get('view_fails', 0) > 0:
        state['view_fails'] -= 1
        Path(path).write_text(json.dumps(state))
        sys.stderr.write('synthetic network error\n')
        return 1
    if argv[1] == 'view':
        fields = argv[4].split(',') if argv[3:4] == ['--json'] and len(argv) == 5 else []
        if not fields or set(fields) - FIELDS or found is None or found.get('hidden'):
            sys.stderr.write("GraphQL: Could not resolve to a Repository with the name '%s'.\n" % name)
            return 1
        has = found['default_branch'] in found['branches']
        known = {'nameWithOwner': found['full_name'], 'isPrivate': found['private'],
                 'defaultBranchRef': {'name': found['default_branch'] if has else ''}}
        print(json.dumps({f: known[f] for f in fields}))
        return 0
    readme = argv[3:] == ['--private', '--add-readme']
    if not (readme or argv[3:] == ['--private']) or found is not None or state.get('create') == 'fail':
        sys.stderr.write('synthetic create refused\n')
        return 1
    owner, short = name.split('/')
    state['repos'][name.lower()] = repository(owner, short, {'main': {'README.md': '# %s\n' % short}} if readme else {})
    state['log'].append(['POST', 'user/repos'])
    state['view_fails'] = state.get('fail_after_create', 0)
    Path(path).write_text(json.dumps(state))
    if state.get('create') == 'lost':
        return 1
    print('https://github.com/%s' % name)
    return 0


def main(argv):
    if argv == ['api', 'user', '--jq', '.login']:
        state = json.loads(Path(os.environ['FAKE_GH_REPOS']).read_text())
        if state.get('signed_out'):
            sys.stderr.write('To get started with GitHub CLI, please run: gh auth login\n')
            return 1
        print(state['user']['login'])
        return 0
    if argv[:2] == ['repo', 'create'] or (argv[:2] == ['repo', 'view'] and len(argv) > 2 and not argv[2].startswith('-')):
        return demo(argv)
    if argv[:3] == ['api', '--include', '-X']:
        env = dict(os.environ, FAKE_GH_WORLD=os.environ['FAKE_GH_REPOS'])
        return subprocess.run([sys.executable, '-I', '-S', str(INIT_GH), *argv], env=env).returncode
    if argv[:2] == ['api', '--paginate'] and len(argv) == 5 and argv[3] == '--jq':
        match = re.fullmatch(r'repos/([^/]+/[^/]+)/issues/([0-9]+)/comments\?per_page=100', argv[2])
        world = json.loads(Path(os.environ['FAKE_GH_WORLD']).read_text())
        if not match or match[1] != world['repo'] or os.environ.get('FAKE_GH_COMMENTS_FAIL'):
            sys.stderr.write('synthetic: HTTP 404\n')
            return 1
        issue = [i for i in world['issues'] if i['number'] == int(match[2])]
        page = [{'body': c['body'], 'user': {'login': c.get('author', 'synthetic-factory[bot]')}
                 if c.get('author', 'synthetic-factory[bot]') is not None else None}
                for c in (issue[0]['comments'] if issue else [])]
        return subprocess.run(['jq', '-r', argv[4]], input=json.dumps(page), text=True).returncode
    os.execv(sys.executable, [sys.executable, '-I', '-S', str(FLEET_GH), *argv])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
