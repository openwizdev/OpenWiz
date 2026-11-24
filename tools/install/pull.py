#!/usr/bin/env python3
import argparse
import http.client
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from install import (CHANNELS, EARLY_VERSION_RE, Refused, TARGETS, VERSION_RE,
                     install, manifest_at, private, require, sha, unique)

DESCRIPTION = """Fixed published-release transport. No source checkout, build, push or shell."""

BASE = 'https://github.com/openwizdev/OpenWiz/releases/'
FEED = 'https://github.com/openwizdev/OpenWiz/releases.atom'
TAG_LINK = re.compile(r'href="https://github\.com/openwizdev/OpenWiz/releases/tag/v(0\.[0-9]+\.[0-9]+)"')
PRO_REPO = 'openwizpro/WizPro'
PRO_URL = 'https://openwiz.dev/pro/'
RC_TAG_RE = re.compile(r'^v(0\.[0-9]+\.[0-9]+-rc\.[0-9]+)$')
SEMVER_RE = re.compile(r'^(0)\.([0-9]+)\.([0-9]+)(?:-rc\.([0-9]+))?$')
ASSET_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')


class NotFound(Refused):
    pass


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == 'https' and parsed.hostname in
                ('github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com')
                and not parsed.username and not parsed.password, 'unapproved artifact redirect')
        return super().redirect_request(req, fp, code, msg, headers, url)


def fetch_bytes(url, limit):
    require(url.startswith(BASE) or url == FEED, 'unapproved release endpoint')
    opener = urllib.request.build_opener(Redirects())
    try:
        with opener.open(urllib.request.Request(url, headers={'User-Agent': 'OpenWiz-package-v1'}), timeout=60) as response:
            data = response.read(limit + 1)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NotFound('release asset 404 at ' + url)
        raise Refused('release asset HTTP %d at %s' % (error.code, url))
    except http.client.HTTPException:
        raise Refused('interrupted transfer at ' + url)
    except OSError as error:
        raise Refused('network error at %s: %s' % (url, getattr(error, 'reason', None) or error))
    require(len(data) <= limit, 'artifact exceeds its declared byte bound at ' + url)
    return data


def semver_key(version):
    match = SEMVER_RE.fullmatch(version)
    require(match, 'invalid release version')
    major, minor, patch = int(match[1]), int(match[2]), int(match[3])
    return (major, minor, patch, 1, 0) if match[4] is None else (major, minor, patch, 0, int(match[4]))


def is_prerelease(version):
    return '-rc.' in version


def read_channel(root):
    channel = Path(root) / 'channel.json'
    if not channel.exists() and not channel.is_symlink():
        return None
    private(channel, False)
    raw = channel.read_bytes()
    for name, expected in CHANNELS.items():
        if raw == expected:
            return name
    raise Refused('unknown update channel')


def gh_binary(which=shutil.which):
    path = which('gh')
    require(path, "early builds require the GitHub CLI (gh); install gh and run 'gh auth login'")
    return path


def gh_auth_check(gh_bin):
    try:
        proc = subprocess.run([gh_bin, 'auth', 'token'], stdin=subprocess.DEVNULL, capture_output=True,
                              text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        raise Refused("GitHub CLI (gh) is not logged in; run 'gh auth login' to sign in") from None
    logged_in = proc.returncode == 0 and bool(proc.stdout.strip())
    require(logged_in, "GitHub CLI (gh) is not logged in; run 'gh auth login' to sign in")


def _refuse_gh_error(proc, fallback):
    text = (proc.stderr or '') + '\n' + (proc.stdout or '')
    lower = text.lower()
    if '404' in text or 'not found' in lower:
        raise NotFound(f'no access to {PRO_REPO} (HTTP 404); early builds need OpenWiz Pro: {PRO_URL}')
    if '401' in text or 'bad credentials' in lower or 'not logged in' in lower or 'gh auth login' in lower:
        raise Refused("GitHub CLI (gh) is not logged in; run 'gh auth login' to sign in")
    raise Refused(fallback)


def pro_releases(gh_bin):
    gh_auth_check(gh_bin)
    try:
        proc = subprocess.run([gh_bin, 'api', f'repos/{PRO_REPO}/releases'], stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        raise Refused(f'could not read early releases from {PRO_REPO}') from None
    if proc.returncode != 0:
        _refuse_gh_error(proc, f'could not read early releases from {PRO_REPO}')
    try:
        entries = json.loads(proc.stdout)
    except ValueError:
        raise Refused(f'invalid release listing from {PRO_REPO}') from None
    require(isinstance(entries, list), f'invalid release listing from {PRO_REPO}')
    versions = []
    for item in entries:
        if not isinstance(item, dict) or item.get('draft') or item.get('prerelease') is not True:
            continue
        tag = item.get('tag_name')
        match = RC_TAG_RE.fullmatch(tag) if isinstance(tag, str) else None
        if match:
            versions.append(match[1])
    return versions


def fetch_pro_asset(tag, filename, limit, gh_bin):
    require(RC_TAG_RE.fullmatch(tag), 'invalid early release tag')
    require(ASSET_NAME_RE.fullmatch(filename), 'invalid release asset name')
    with tempfile.TemporaryDirectory(prefix='openwiz-early-') as temporary:
        dest = Path(temporary) / filename
        try:
            proc = subprocess.run(
                [gh_bin, 'release', 'download', tag, '--repo', PRO_REPO, '--pattern', filename, '--output', str(dest)],
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            raise Refused(f'early release download failed for {filename} in {PRO_REPO}') from None
        if proc.returncode != 0:
            _refuse_gh_error(proc, f'early release download failed for {filename} in {PRO_REPO}')
        require(dest.is_file() and not dest.is_symlink(), f'missing downloaded asset {filename}')
        require(dest.stat().st_size <= limit, f'artifact exceeds its declared byte bound at {PRO_REPO}/{tag}/{filename}')
        return dest.read_bytes()


def pro_fetcher(tag, gh_bin):
    return lambda name, limit: fetch_pro_asset(tag, name, limit, gh_bin)


def load(raw, checksum, target, selected=False, allow_prerelease=False):
    with tempfile.TemporaryDirectory(prefix='openwiz-package-manifest-') as temporary:
        file = Path(temporary) / 'manifest.json'
        file.write_bytes(raw)
        return manifest_at(file, checksum, target, selected, allow_prerelease=allow_prerelease)[0]


def published(target, fetch=fetch_bytes, version=None):
    require(target in TARGETS, 'unsupported package target')
    if version is None:
        try:
            return manifest_from(BASE + 'latest/download/', target, fetch)
        except NotFound as missing:
            tags = TAG_LINK.findall(fetch(FEED, 1024 * 1024).decode('utf-8', 'replace'))
            require(tags, '%s; no published release tag found at %s' % (missing, FEED))
            version = max(tags, key=lambda tag: tuple(map(int, tag.split('.'))))
    require(re.fullmatch(r'0\.[0-9]+\.[0-9]+', version), 'invalid release version')
    found = manifest_from(BASE + 'download/v' + version + '/', target, fetch)
    require(found[2]['version'] == version, 'published version does not match its tag v' + version)
    return found


def published_early(target, fetch=fetch_bytes, version=None, which=shutil.which):
    require(target in TARGETS, 'unsupported package target')
    gh_bin = gh_binary(which)
    rc_versions = pro_releases(gh_bin)
    if version is not None:
        if is_prerelease(version):
            tag = 'v' + version
            require(RC_TAG_RE.fullmatch(tag), 'invalid release version')
            require(version in rc_versions, f'early release {tag} not found in {PRO_REPO}')
            early_fetch = pro_fetcher(tag, gh_bin)
            found = manifest_from('', target, early_fetch, allow_prerelease=True)
            require(found[2]['version'] == version, 'published version does not match its tag ' + tag)
            return found, 'early', early_fetch
        return published(target, fetch, version), 'public', fetch
    best_early = max(rc_versions, key=semver_key) if rc_versions else None
    try:
        public_found = published(target, fetch)
    except NotFound:
        if best_early is None:
            raise
        public_found = None
    if best_early is not None and (public_found is None or semver_key(best_early) > semver_key(public_found[2]['version'])):
        tag = 'v' + best_early
        early_fetch = pro_fetcher(tag, gh_bin)
        found = manifest_from('', target, early_fetch, allow_prerelease=True)
        require(found[2]['version'] == best_early, 'published version does not match its tag ' + tag)
        return found, 'early', early_fetch
    require(public_found is not None, f'no published or early release found for {target}')
    return public_found, 'public', fetch


def manifest_from(prefix, target, fetch, allow_prerelease=False):
    name = 'openwiz-' + target
    sums = fetch(prefix + name + '.sha256', 256)
    match = re.fullmatch(rb'([0-9a-f]{64})  ' + re.escape((name + '.manifest.json').encode()) + rb'\n', sums)
    require(match, 'invalid published manifest checksum')
    checksum = match[1].decode('ascii')
    raw = fetch(prefix + name + '.manifest.json', 4 * 1024 * 1024)
    return sums, raw, load(raw, checksum, target, allow_prerelease=allow_prerelease), checksum


def discover(target, fetch=fetch_bytes, channel=None, root=None, which=shutil.which):
    if channel is None:
        channel = (read_channel(root) or 'packaged') if root else 'packaged'
    require(channel in CHANNELS, 'unsupported update channel')
    if channel == 'early':
        found, origin, _ = published_early(target, fetch=fetch, which=which)
        manifest, checksum = found[2:]
        return {'schema': 'openwiz.package-candidate.v1', 'version': manifest['version'],
                'source': manifest['source'], 'target': target, 'manifest_sha256': checksum,
                'channel': 'early', 'origin': origin}
    manifest, checksum = published(target, fetch)[2:]
    return {'schema': 'openwiz.package-candidate.v1', 'version': manifest['version'],
            'source': manifest['source'], 'target': target, 'manifest_sha256': checksum}


def stage(target, version, source, checksum, root, state_root, fetch=fetch_bytes, which=shutil.which):
    root, state_root = Path(root), Path(state_root)
    private(root)
    private(state_root / 'service')
    root_channel = read_channel(root) or 'packaged'
    is_early = root_channel == 'early'
    version_re = EARLY_VERSION_RE if is_early else VERSION_RE
    require(target in TARGETS and version_re.fullmatch(version), 'invalid version/target')
    current = root / 'current'
    require(current.is_symlink(), 'missing packaged current selection')
    selected = current.readlink()
    require(selected.is_absolute() and selected.parent == state_root / 'service/builds', 'foreign selection')
    private(selected)
    private(selected / 'install-manifest.json', False)
    old_raw = (selected / 'install-manifest.json').read_bytes()
    old = load(old_raw, sha(old_raw), target, selected=True)
    require(semver_key(version) > semver_key(old['version']), 'published version must advance')
    name = f'openwiz-{version}-{target}.manifest.json'
    if is_early and is_prerelease(version):
        gh_bin = gh_binary(which)
        gh_auth_check(gh_bin)
        asset_fetch = pro_fetcher('v' + version, gh_bin)
        prefix = ''
    else:
        asset_fetch = fetch
        prefix = BASE + 'download/v' + version + '/'
    raw = asset_fetch(prefix + name, 4 * 1024 * 1024)
    manifest = load(raw, checksum, target, allow_prerelease=is_early)
    require(manifest['version'] == version and manifest['source'] == source, 'published identity changed')
    bundle = asset_fetch(prefix + manifest['archive'], manifest['archive_bytes'])
    listed = {}
    for line in asset_fetch(prefix + 'SHA256SUMS', 64 * 1024).decode('ascii', 'replace').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        require(match and match[2] not in listed, 'invalid SHA256SUMS line')
        listed[match[2]] = match[1]
    for file, data in ((name, raw), (manifest['archive'], bundle)):
        require(file in listed, 'SHA256SUMS does not list ' + file)
        require(listed[file] == sha(data), 'SHA256SUMS does not match ' + file)
    with tempfile.TemporaryDirectory(prefix='.package-download-', dir=state_root / 'service') as temporary:
        directory = Path(temporary)
        manifest_file = directory / 'manifest.json'
        archive = directory / 'bundle.tar.gz'
        manifest_file.write_bytes(raw)
        manifest_file.chmod(0o600)
        archive.write_bytes(bundle)
        archive.chmod(0o600)
        return install(manifest_file, archive, checksum, root, target, state_root=state_root, stage_only=True,
                       channel=root_channel)


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    commands = parser.add_subparsers(dest='action', required=True)
    discover_parser = commands.add_parser('discover')
    discover_parser.add_argument('target', choices=TARGETS)
    discover_parser.add_argument('--channel', choices=tuple(CHANNELS))
    discover_parser.add_argument('--root')
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
