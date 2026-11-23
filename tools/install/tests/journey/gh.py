#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import sys

INIT_GH = Path(__file__).resolve().parents[1] / 'init/fake_gh.py'


def main(argv):
    if len(argv) == 2 and argv[0] == 'api' and re.fullmatch(r'repos/[^/]+/[^/]+/issues/[0-9]+', argv[1]):
        world = json.loads(Path(os.environ['FAKE_GH_WORLD']).read_text())
        owner, name, _, number = argv[1].split('/')[1:]
        found = world.get('issues', {}).get('%s/%s#%s' % (owner, name, number))
        if found is None:
            sys.stderr.write('synthetic: HTTP 404\n')
            return 1
        print(json.dumps(found))
        return 0
    os.execv(sys.executable, [sys.executable, '-I', str(INIT_GH), *argv])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
