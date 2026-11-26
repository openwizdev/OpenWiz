#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SKILLS = Path(__file__).resolve().parents[4] / 'skills'
FLEET_GH = SKILLS / 'launch-fleet/scripts/fixtures/gh.py'
INSTALL_GH = SKILLS / 'install/tests/fixtures/fake_gh.py'
INIT_GH = Path(__file__).resolve().parents[1] / 'init/fake_gh.py'


def main(argv):
    if (argv == ['api', 'user', '--jq', '.login']
            or argv[:2] == ['repo', 'view'] and len(argv) > 2 and not argv[2].startswith('-')
            or argv[:3] == ['api', '-X', 'POST'] and len(argv) > 3 and argv[3] == 'user/repos'
            or argv[:2] == ['api', 'graphql'] and any(arg.startswith('path=') for arg in argv[3::2])):
        os.execv(sys.executable, [sys.executable, '-I', '-S', str(INSTALL_GH), *argv])
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
