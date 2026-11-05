#!/usr/bin/env python3
"""Fixed published-release transport. No source checkout, build, push or shell."""
import argparse
import json
from pathlib import Path
import re
import sys
import tempfile
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from install import Refused, TARGETS, install, manifest_at, private, require, sha, unique

BASE = 'https://github.com/openwizdev/openwiz/releases/'


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname in
                ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
                and not parsed.username and not parsed.password, 'unapproved artifact redirect')
        return super().redirect_request(req, fp, code, msg, headers, url)


def fetch_bytes(url, limit):
    require(url.startswith(BASE), 'unapproved release endpoint')
    opener = urllib.request.build_opener(Redirects())
    with opener.open(urllib.request.Request(url, headers={'User-Agent': 'OpenWiz-package-v1'}), timeout=60) as response:
        data = response.read(limit + 1)
        require(len(data) <= limit, 'artifact exceeds its declared byte bound')
        return data


def load(raw, checksum, target):
    with tempfile.TemporaryDirectory(prefix='openwiz-package-manifest-') as temporary:
        file = Path(temporary) / 'manifest.json'
        file.write_bytes(raw)
        return manifest_at(file, checksum, target)[0]


def discover(target, fetch=fetch_bytes):
    require(target in TARGETS, 'unsupported package target')
    name = 'openwiz-' + target
    sums = fetch(BASE + 'latest/download/' + name + '.sha256', 256)
    match = re.fullmatch(rb'([0-9a-f]{64})  ' + re.escape((name + '.manifest.json').encode()) + rb'\n', sums)
    require(match, 'invalid published manifest checksum')
    checksum = match[1].decode('ascii')
    raw = fetch(BASE + 'latest/download/' + name + '.manifest.json', 4 * 1024 * 1024)
    manifest = load(raw, checksum, target)
    return {'schema': 'openwiz.package-candidate.v1', 'version': manifest['version'],
            'source': manifest['source'], 'target': target, 'manifest_sha256': checksum}


def stage(target, version, source, checksum, root, state_root, fetch=fetch_bytes):
    require(target in TARGETS and re.fullmatch(r'0\.[0-9]+\.[0-9]+', version), 'invalid version/target')
    root, state_root = Path(root), Path(state_root)
    private(root)
    private(state_root / 'service')
    current = root / 'current'
    require(current.is_symlink(), 'missing packaged current selection')
    selected = current.readlink()
    require(selected.is_absolute() and selected.parent == state_root / 'service/builds', 'foreign selection')
    private(selected)
    private(selected / 'install-manifest.json', False)
    old_raw = (selected / 'install-manifest.json').read_bytes()
    old = load(old_raw, sha(old_raw), target)
    require(tuple(map(int, version.split('.'))) > tuple(map(int, old['version'].split('.'))), 'published version must advance')
    name = f'openwiz-{version}-{target}.manifest.json'
    prefix = BASE + 'download/v' + version + '/'
    raw = fetch(prefix + name, 4 * 1024 * 1024)
    manifest = load(raw, checksum, target)
    require(manifest['version'] == version and manifest['source'] == source, 'published identity changed')
    # Files are stored privately; the installer verifies compressed integrity
    # before parsing and every asset before staging. Nothing selects current.
    with tempfile.TemporaryDirectory(prefix='.package-download-', dir=state_root / 'service') as temporary:
        directory = Path(temporary)
        manifest_file = directory / 'manifest.json'
        archive = directory / 'bundle.tar.gz'
        manifest_file.write_bytes(raw)
        manifest_file.chmod(0o600)
        archive.write_bytes(fetch(prefix + manifest['archive'], manifest['archive_bytes']))
        archive.chmod(0o600)
        return install(manifest_file, archive, checksum, root, target, state_root=state_root, stage_only=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    discover_parser = commands.add_parser('discover')
    discover_parser.add_argument('target', choices=TARGETS)
    stage_parser = commands.add_parser('stage')
    for key in ('target', 'version', 'source', 'checksum', 'root', 'state_root'):
        stage_parser.add_argument(key)
    args = vars(parser.parse_args())
    action = args.pop('action')
    try:
        value = discover(**args) if action == 'discover' else stage(**args)
        print(json.dumps(value, separators=(',', ':')))
        return 0
    except (Refused, OSError, ValueError, TypeError, KeyError):
        print('package pull: refused; last-good build retained', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
