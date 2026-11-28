#!/usr/bin/env python3
import argparse
import http.client
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True

REPO = 'openwizdev/OpenWiz'
API_HOST = 'api.github.com'
API_PATH = '/repos/openwizdev/OpenWiz/releases'
PER_PAGE = 100
PAGE_LIMIT = 20
BODY_LIMIT = 8_000_000
SCHEMA = 'openwiz.download-counts.v1'
PACKAGE = re.compile(r'^openwiz-[0-9]+\.[0-9]+\.[0-9]+-[a-z0-9_]+-[a-z0-9_-]+\.tar\.gz$')
TAG = re.compile(r'^v[0-9]+\.[0-9]+\.[0-9]+$')
ASSET = re.compile(r'^[A-Za-z0-9_.-]+$')
NOT_COLLECTED = (
    'git clones',
    'GitHub source zip and tar links',
    'site visits',
    'package-registry installs',
    'client events',
    'user, device, or network identifiers',
)


class Refused(Exception):
    pass


class Usage(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Usage(message)


def require(ok, message):
    if not ok:
        raise Refused(message)


def version_key(tag):
    return tuple(int(part) for part in tag[1:].split('.'))


def page_url(page):
    require(type(page) is int and 1 <= page <= PAGE_LIMIT, 'releases page out of range')
    return 'https://%s%s?per_page=%d&page=%d' % (API_HOST, API_PATH, PER_PAGE, page)


def require_api_url(url):
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname == API_HOST and parsed.path == API_PATH
            and parsed.port is None and not parsed.username and not parsed.password
            and not parsed.fragment, 'unapproved releases endpoint')
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    require(len(query) == 2 and query[0] == ('per_page', str(PER_PAGE)) and query[1][0] == 'page',
            'unapproved releases endpoint')
    page = query[1][1]
    require(page.isdigit() and not (len(page) > 1 and page.startswith('0'))
            and 1 <= int(page) <= PAGE_LIMIT, 'unapproved releases endpoint')
    require(url == page_url(int(page)), 'unapproved releases endpoint')


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, url):
        require_api_url(url)
        return super().redirect_request(req, fp, code, msg, headers, url)


def count_of(value):
    require(type(value) is int and value >= 0, 'invalid download_count')
    return value


def asset_row(item):
    require(isinstance(item, dict), 'invalid release asset')
    name = item.get('name')
    require(isinstance(name, str) and ASSET.fullmatch(name), 'invalid release asset name')
    return {'name': name, 'download_count': count_of(item.get('download_count')),
            'package': PACKAGE.fullmatch(name) is not None}


def release_row(item):
    require(isinstance(item, dict), 'invalid release')
    tag = item.get('tag_name')
    require(isinstance(tag, str) and TAG.fullmatch(tag), 'invalid release tag')
    draft, prerelease = item.get('draft'), item.get('prerelease')
    require(type(draft) is bool and type(prerelease) is bool, 'invalid release flags')
    assets_in = item.get('assets')
    require(isinstance(assets_in, list), 'invalid release assets')
    assets = [asset_row(asset) for asset in assets_in]
    require(len({asset['name'] for asset in assets}) == len(assets), 'repeated release asset')
    assets.sort(key=lambda asset: (not asset['package'], asset['name']))
    return {
        'tag': tag,
        'prerelease': prerelease,
        'draft': draft,
        'package_downloads': sum(asset['download_count'] for asset in assets if asset['package']),
        'asset_downloads': sum(asset['download_count'] for asset in assets),
        'assets': assets,
    }


def summarize(releases):
    require(isinstance(releases, list), 'releases response is not a list')
    rows = [release_row(item) for item in releases]
    require(len({row['tag'] for row in rows}) == len(rows), 'repeated release tag')
    omitted = sum(1 for row in rows if row['draft'])
    published = [{key: value for key, value in row.items() if key != 'draft'}
                 for row in rows if not row['draft']]
    published.sort(key=lambda row: version_key(row['tag']), reverse=True)
    return {
        'schema': SCHEMA,
        'repository': REPO,
        'source': 'github-release-asset-download-count',
        'package_downloads': sum(row['package_downloads'] for row in published),
        'asset_downloads': sum(row['asset_downloads'] for row in published),
        'drafts_omitted': omitted,
        'collected': 'download_count on each GitHub release asset',
        'not_collected': list(NOT_COLLECTED),
        'releases': published,
    }


def decode_releases(body):
    require(isinstance(body, (bytes, bytearray)) and len(body) <= BODY_LIMIT, 'releases response is too large')
    try:
        return json.loads(bytes(body).decode('utf-8'))
    except (UnicodeError, ValueError):
        raise Refused('releases response is not JSON')


def read_pages(fetch):
    found = []
    for page in range(1, PAGE_LIMIT + 1):
        status, body = fetch(page)
        require(type(status) is int, 'invalid releases status')
        if status != 200:
            raise Refused('GitHub releases read returned HTTP %d' % status)
        batch = decode_releases(body)
        require(isinstance(batch, list), 'releases response is not a list')
        found.extend(batch)
        if len(batch) < PER_PAGE:
            return found
    raise Refused('GitHub releases list did not end within %d pages' % PAGE_LIMIT)


def token_from_env(env):
    for key in ('GITHUB_TOKEN', 'GH_TOKEN'):
        value = env.get(key)
        if value:
            require('\n' not in value and '\r' not in value and '\x00' not in value, 'invalid GitHub token')
            return value
    return None


def request_headers(token):
    headers = {'User-Agent': 'OpenWiz-download-counts', 'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    return headers


def open_release(opener, page, token):
    url = page_url(page)
    require_api_url(url)
    request = urllib.request.Request(url, headers=request_headers(token))
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, response.read(BODY_LIMIT + 1)
    except urllib.error.HTTPError as error:
        error.close()
        return error.code, b''
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError):
        raise Refused('GitHub releases read failed')


def http_fetch(page, token):
    return open_release(urllib.request.build_opener(Redirects()), page, token)


def load_file(path):
    data = decode_releases(Path(path).read_bytes())
    require(isinstance(data, list), 'releases response is not a list')
    return data


def render(report):
    lines = [
        'OpenWiz download counts',
        'repository: ' + report['repository'],
        'source: GitHub release asset download_count',
        'package_downloads: %d' % report['package_downloads'],
        'asset_downloads: %d' % report['asset_downloads'],
        'drafts_omitted: %d' % report['drafts_omitted'],
        '',
    ]
    for release in report['releases']:
        mark = ' prerelease' if release['prerelease'] else ''
        lines.append('%s%s  packages %d  assets %d' % (
            release['tag'], mark, release['package_downloads'], release['asset_downloads']))
        for asset in release['assets']:
            kind = 'package' if asset['package'] else 'asset'
            lines.append('  %s  %d  %s' % (kind, asset['download_count'], asset['name']))
    lines.extend([
        '',
        'Collected: download_count on each GitHub release asset. package_downloads sums',
        'the .tar.gz archives (one per install of one target). asset_downloads also',
        'counts the checksum and manifest files fetched with that archive, and any',
        'release check that downloaded them.',
        'Not collected: ' + '; '.join(report['not_collected']) + '.',
    ])
    return '\n'.join(lines) + '\n'


def main(argv=None, env=None, fetch=None):
    parser = Parser(prog='counts.py')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--releases')
    try:
        args = parser.parse_args(argv)
    except Usage as error:
        print('counts.py: %s' % error, file=sys.stderr)
        return 2
    try:
        if args.releases:
            releases = load_file(args.releases)
        else:
            chosen = fetch
            if chosen is None:
                token = token_from_env(os.environ if env is None else env)
                chosen = lambda page: http_fetch(page, token)
            releases = read_pages(chosen)
        report = summarize(releases)
    except Refused as error:
        print('counts.py: %s' % error, file=sys.stderr)
        return 1
    except OSError:
        print('counts.py: could not read releases', file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        sys.stdout.write(render(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
