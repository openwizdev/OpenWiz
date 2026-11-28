#!/usr/bin/env python3
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.request
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import counts

HERE = Path(__file__).resolve().parent
TOKEN = 'synthetic-token-value'


def release(tag, assets, draft=False, prerelease=False, **extra):
    row = {'tag_name': tag, 'draft': draft, 'prerelease': prerelease, 'assets': assets}
    row.update(extra)
    return row


def asset(name, count):
    return {'name': name, 'download_count': count, 'browser_download_url': 'https://example.invalid/a'}


LINUX = 'openwiz-0.1.0-x86_64-unknown-linux-gnu.tar.gz'
MAC = 'openwiz-0.1.0-aarch64-apple-darwin.tar.gz'
SHA = 'openwiz-x86_64-unknown-linux-gnu.sha256'


class Summarize(unittest.TestCase):
    def test_packages_are_archives_and_drafts_stay_out(self):
        report = counts.summarize([
            release('v0.1.0', [asset(SHA, 4), asset(LINUX, 10), asset('SHA256SUMS', 2), asset(MAC, 3)]),
            release('v0.0.12', [asset('openwiz-0.0.12-x86_64-unknown-linux-gnu.tar.gz', 8)], prerelease=True),
            release('v0.0.9', [asset('openwiz-0.0.9-x86_64-unknown-linux-gnu.tar.gz', 100)], draft=True),
        ])
        self.assertEqual(report['schema'], counts.SCHEMA)
        self.assertEqual(report['repository'], 'openwizdev/OpenWiz')
        self.assertEqual(report['package_downloads'], 21)
        self.assertEqual(report['asset_downloads'], 27)
        self.assertEqual(report['drafts_omitted'], 1)
        self.assertEqual([row['tag'] for row in report['releases']], ['v0.1.0', 'v0.0.12'])
        self.assertTrue(report['releases'][1]['prerelease'])
        self.assertEqual(report['releases'][0]['assets'][0]['name'], MAC)
        self.assertTrue(report['releases'][0]['assets'][0]['package'])
        self.assertFalse(report['releases'][0]['assets'][-1]['package'])
        self.assertEqual(report['not_collected'], list(counts.NOT_COLLECTED))

    def test_empty_list_is_zero(self):
        report = counts.summarize([])
        self.assertEqual(report['package_downloads'], 0)
        self.assertEqual(report['asset_downloads'], 0)
        self.assertEqual(report['releases'], [])

    def test_refuses_bad_counts_tags_and_repeats(self):
        good = [asset(LINUX, 1)]
        for releases in (
            [release('v0.1.0', [{'name': LINUX, 'download_count': True}])],
            [release('v0.1.0', [asset(LINUX, -1)])],
            [release('latest', good)],
            [release('v0.1.0', good), release('v0.1.0', good)],
            [release('v0.1.0', [asset(LINUX, 1), asset(LINUX, 2)])],
            [release('v0.1.0', [{'name': '../archive.tar.gz', 'download_count': 1}])],
            [{'tag_name': 'v0.1.0', 'draft': 0, 'prerelease': False, 'assets': []}],
            {'tag_name': 'v0.1.0'},
        ):
            with self.assertRaises(counts.Refused):
                counts.summarize(releases)

    def test_checksum_names_are_not_packages(self):
        report = counts.summarize([release('v0.1.0', [
            asset('openwiz-0.1.0-x86_64-unknown-linux-gnu.manifest.json', 9),
            asset('bundle.tar.gz', 5),
        ])])
        self.assertEqual(report['package_downloads'], 0)
        self.assertEqual(report['asset_downloads'], 14)


class Pages(unittest.TestCase):
    def test_stops_on_a_short_page_and_rejects_a_full_run(self):
        full = [release('v0.0.%d' % n, []) for n in range(counts.PER_PAGE)]
        seen = []

        def fetch(page):
            seen.append(page)
            if page == 1:
                return 200, json.dumps(full).encode()
            return 200, json.dumps([release('v1.0.0', [])]).encode()

        found = counts.read_pages(fetch)
        self.assertEqual(seen, [1, 2])
        self.assertEqual(len(found), counts.PER_PAGE + 1)

        def never_ends(page):
            return 200, json.dumps(full).encode()

        with self.assertRaises(counts.Refused):
            counts.read_pages(never_ends)

    def test_http_error_and_huge_body(self):
        with self.assertRaises(counts.Refused) as error:
            counts.read_pages(lambda page: (503, b''))
        self.assertIn('HTTP 503', str(error.exception))
        with self.assertRaises(counts.Refused):
            counts.read_pages(lambda page: (200, b'{' * (counts.BODY_LIMIT + 1)))
        with self.assertRaises(counts.Refused):
            counts.read_pages(lambda page: (200, b'{'))


class Endpoint(unittest.TestCase):
    def test_only_the_releases_list(self):
        counts.require_api_url(counts.page_url(1))
        counts.require_api_url(counts.page_url(counts.PAGE_LIMIT))
        for url in (
            'http://api.github.com/repos/openwizdev/OpenWiz/releases?per_page=100&page=1',
            'https://github.com/openwizdev/OpenWiz/releases?per_page=100&page=1',
            'https://api.github.com/repos/openwizdev/OpenWiz/releases/1?per_page=100&page=1',
            'https://api.github.com/repos/openwizdev/WizSite/releases?per_page=100&page=1',
            'https://api.github.com/repos/openwizdev/OpenWiz/releases?page=1&per_page=100',
            'https://' + 'user:secret@' + 'api.github.com/repos/openwizdev/OpenWiz/releases?per_page=100&page=1',
            counts.page_url(1) + '&extra=1',
        ):
            with self.assertRaises(counts.Refused):
                counts.require_api_url(url)

    def test_redirect_handler_checks_the_target(self):
        handler = counts.Redirects()
        with self.assertRaises(counts.Refused):
            handler.redirect_request(None, None, 302, 'found', {}, 'https://example.invalid/releases')


class Transport(unittest.TestCase):
    def test_failure_hides_the_token_and_sends_it_only_as_a_header(self):
        seen = []

        class Opener:
            def open(self, request, timeout):
                seen.append((request.full_url, request.get_header('Authorization'), timeout))
                raise urllib.error.URLError(TOKEN)

        with self.assertRaises(counts.Refused) as error:
            counts.open_release(Opener(), 1, TOKEN)
        self.assertEqual(str(error.exception), 'GitHub releases read failed')
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertEqual(seen[0][0], counts.page_url(1))
        self.assertEqual(seen[0][1], 'Bearer ' + TOKEN)

        class Missing(urllib.error.HTTPError):
            def __init__(self):
                super().__init__(counts.page_url(1), 404, 'missing', {}, io.BytesIO(b'secret'))

        class Http:
            def open(self, request, timeout):
                raise Missing()

        self.assertEqual(counts.open_release(Http(), 2, None), (404, b''))
        self.assertNotIn('Authorization', counts.request_headers(None))


class Command(unittest.TestCase):
    def run_cli(self, *args, releases=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'releases.json'
            if releases is not None:
                path.write_text(json.dumps(releases))
                args = ('--releases', str(path), *args)
            return subprocess.run(
                [sys.executable, '-I', str(HERE / 'counts.py'), *args],
                capture_output=True, text=True)

    def test_text_and_json_from_a_file(self):
        rows = [release('v0.1.0', [asset(LINUX, 2), asset(SHA, 1)])]
        text = self.run_cli(releases=rows)
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn('package_downloads: 2\n', text.stdout)
        self.assertIn('asset_downloads: 3\n', text.stdout)
        self.assertIn('v0.1.0  packages 2  assets 3\n', text.stdout)
        self.assertIn('  package  2  ' + LINUX + '\n', text.stdout)
        self.assertIn('  asset  1  ' + SHA + '\n', text.stdout)
        self.assertIn('Not collected: git clones;', text.stdout)
        parsed = self.run_cli('--json', releases=rows)
        self.assertEqual(parsed.returncode, 0, parsed.stderr)
        report = json.loads(parsed.stdout)
        self.assertEqual(report['package_downloads'], 2)
        self.assertEqual(report['releases'][0]['assets'][0]['package'], True)

    def test_usage_and_unreadable_file(self):
        usage = self.run_cli('--nope')
        self.assertEqual(usage.returncode, 2)
        self.assertTrue(usage.stderr.startswith('counts.py:'))
        missing = subprocess.run(
            [sys.executable, '-I', str(HERE / 'counts.py'), '--releases', '/missing/releases.json'],
            capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stderr, 'counts.py: could not read releases\n')

    def test_injected_fetch_can_fail_without_printing_a_token(self):
        held = io.StringIO()
        with contextlib.redirect_stderr(held):
            code = counts.main([], env={'GITHUB_TOKEN': TOKEN}, fetch=lambda page: (401, b''))
        self.assertEqual(code, 1)
        self.assertNotIn(TOKEN, held.getvalue())
        self.assertIn('HTTP 401', held.getvalue())


if __name__ == '__main__':
    unittest.main()
