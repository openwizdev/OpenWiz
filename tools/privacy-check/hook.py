#!/usr/bin/env python3
"""Pre-push adapter: guard network destinations except the private repository."""
import argparse
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import check


def private_or_local(url):
    # Local fixture/removable-disk remotes cannot publish to a network service.
    if url.startswith(('/', './', '../', 'file://')):
        return True
    if '://' in url:
        value = urlsplit(url)
        host, path = value.hostname, value.path
    else:
        match = re.fullmatch(r'(?:[^/@:]+@)?([^/:]+):(.+)', url)
        if not match:
            # Plain paths without a colon are also Git's local transport.
            return bool(url) and ':' not in url
        host, path = match.groups()
    path = path.strip('/').removesuffix('.git').lower()
    return host and host.lower() == 'github.com' and path == 'jparker2006/closedwiz'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--head', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--literals', type=Path, default=os.environ.get('OPENWIZ_PRIVACY_LITERALS'))
    args = parser.parse_args(argv)
    if private_or_local(args.url):
        return 0
    command = ['--repo', str(args.repo), '--git-tree', args.head, '--head', args.head]
    if args.base.strip('0'):
        command += ['--base', args.base]
    if args.literals is not None:
        command += ['--literals', str(args.literals), '--require-literals']
    return check.main(command)


if __name__ == '__main__':
    sys.exit(main())
