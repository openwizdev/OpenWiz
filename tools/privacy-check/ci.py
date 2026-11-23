#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError()
        result[key] = value
    return result


def resolves(ref):
    try:
        check.commit('.', ref)
        return True
    except check.Unreadable:
        return False


def pull_request_range(branch, base):
    if isinstance(branch, str) and re.fullmatch(r'[A-Za-z0-9_-]+(?:[./][A-Za-z0-9_-]+)*', branch):
        upstream = 'refs/remotes/origin/' + branch
        if resolves(upstream):
            return ['--upstream', upstream]
    if resolves(base):
        print('range: from the event base commit')
        return ['--base', base]
    print('range: no base branch or base commit, scanning from the public anchor')
    return []


def main():
    if os.environ.get('GITHUB_REPOSITORY', '').lower() == 'jparker2006/closedwiz':
        print('private repository: no public scan')
        return 0
    try:
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'), object_pairs_hook=unique_object)
        kind = os.environ['GITHUB_EVENT_NAME']
        title = body = ''
        if kind == 'pull_request':
            pr = event['pull_request']
            base, head = pr['base']['sha'], pr['head']['sha']
            title, body = pr['title'], pr['body']
            if body is None:
                body = ''
        elif kind == 'push':
            base, head = event['before'], event['after']
            if event.get('deleted') is True and head == '0' * 40:
                print('deleted ref: no commits published')
                return 0
        elif kind == 'merge_group':
            base, head = event['merge_group']['base_sha'], event['merge_group']['head_sha']
        else:
            raise ValueError()
        if not all(isinstance(x, str) and re.fullmatch(r'[0-9a-f]{40}', x) for x in (base, head)):
            raise ValueError()
        if not isinstance(title, str) or not isinstance(body, str):
            raise ValueError()
        args = ['--repo', '.', '--git-tree', head, '--head', head]
        if kind == 'pull_request':
            args += pull_request_range(pr['base'].get('ref'), base)
        elif base.strip('0'):
            args += ['--base', base]
        elif kind == 'push' and isinstance(event.get('ref'), str) and event['ref'] != 'refs/heads/main':
            args += ['--upstream', 'refs/remotes/origin/main']
        with tempfile.TemporaryDirectory() as folder:
            for name, text in (('title', title), ('body', body)):
                path = Path(folder) / name
                path.write_text(text, encoding='utf-8')
                args += ['--' + name + '-file', str(path)]
            return check.main(args)
    except (KeyError, TypeError, ValueError, OSError):
        print('READ event:1')
        return 1


if __name__ == '__main__':
    sys.exit(main())
