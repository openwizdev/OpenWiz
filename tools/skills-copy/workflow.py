#!/usr/bin/env python3
"""Admit only a skill-changing push to openwizdev/openwiz main."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

EXTRAS = ('export-review', 'live-quick-check', 'live-spike')


def changed_skill(path):
    return path.startswith(('skills/', 'wizdev/skills/')) or any(
        path.startswith('.claude/skills/' + name + '/') for name in EXTRAS)


def enabled(source):
    if (os.environ.get('GITHUB_REPOSITORY') != 'openwizdev/openwiz'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'
            or os.environ.get('GITHUB_EVENT_NAME') != 'push'):
        return False
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text(encoding='utf-8'))
    if event['repository']['full_name'] != 'openwizdev/openwiz' or event['deleted'] is not False:
        return False
    before, after = event['before'], event['after']
    if not all(isinstance(v, str) and re.fullmatch('[0-9a-f]{40}', v) for v in (before, after)):
        raise ValueError('Invalid push revisions')

    def git(*args):
        return subprocess.run(['git', '-C', str(source), *args], capture_output=True,
                              check=True, env=dict(os.environ, GIT_NO_REPLACE_OBJECTS='1')).stdout

    if git('rev-parse', 'HEAD').decode().strip() != after:
        raise ValueError('Checkout is not the event head')
    if before == '0' * 40:
        paths = git('ls-tree', '-rz', '--name-only', after)
    else:
        git('merge-base', '--is-ancestor', before, after)
        paths = git('diff', '--name-only', '--no-renames', '-z', before, after)
    return any(changed_skill(path.decode('utf-8')) for path in paths.split(b'\0') if path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        admitted = enabled(args.source)
        if os.environ.get('GITHUB_OUTPUT'):
            with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                output.write('enabled=' + str(admitted).lower() + '\n')
        print(json.dumps({'enabled': admitted}))
        return 0
    except (KeyError, OSError, ValueError, TypeError, subprocess.CalledProcessError):
        print('skills-copy workflow: refused unreadable event or history', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
