import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile


INVENTORY = Path(__file__).resolve().with_name('agent-clis.json')
REQUIRED_TOOLS = {'gh', 'git', 'python3', 'sh'}


def cli_names():
    try:
        names = json.loads(INVENTORY.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('cannot read the agent CLI inventory') from None
    if (not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]*', name) for name in names)
            or len(set(names)) != len(names) or REQUIRED_TOOLS.intersection(names)):
        raise ValueError('invalid agent CLI inventory')
    return names


def stub_path(path=None):
    names = cli_names()
    if path is None:
        path = os.environ.get('PATH', os.defpath)
    directory = tempfile.mkdtemp(prefix='openwiz-agent-stubs-')
    try:
        if os.pathsep in directory:
            raise ValueError('the stub directory cannot be represented on PATH')
        for name in names:
            stub = Path(directory) / name
            stub.write_text(f"#!/bin/sh\nprintf '%s\\n' '{name}: refused, tests never start an agent CLI' >&2\nexit 1\n",
                            encoding='utf-8')
            stub.chmod(0o700)
    except (OSError, ValueError):
        shutil.rmtree(directory)
        raise
    return os.pathsep.join((directory, path))


def main():
    parser = argparse.ArgumentParser(description='Print a PATH guarded by refusing agent CLI stubs.')
    parser.add_argument('--print-path', action='store_true', required=True)
    parser.parse_args()
    try:
        path = stub_path()
    except OSError:
        print('cannot create the agent CLI stubs', file=sys.stderr)
        return 1
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == '__main__':
    sys.exit(main())
