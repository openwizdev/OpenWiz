#!/usr/bin/env python3
"""Check exact GitHub event inputs; the private repository is a no-op."""
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
        if base.strip('0'):
            args += ['--base', base]
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
