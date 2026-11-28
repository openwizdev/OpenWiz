#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path
import sys
import unittest
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent / 'fetcher'))
sys.path.insert(0, str(HERE))
import loopback
import market


class MarketCopy(unittest.TestCase):
    def setUp(self):
        self.copy = market.start()
        self.addCleanup(self.copy.stop)

    def request(self, path, method='GET', data=None):
        req = urllib.request.Request(self.copy.url + path, data=data, method=method)
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.read()

    def listings(self):
        return {l['id']: l for l in json.loads(self.request('listings')[1])['listings']}

    def test_starts_on_loopback_only(self):
        self.assertEqual(self.copy.address[0], '127.0.0.1')

    def test_serves_one_clean_listing_and_each_poison(self):
        listings = market.load()['listings']
        self.assertEqual(sorted(l['poison'] for l in listings),
                         ['agent-instructions-in-readme', 'exfiltrating-install-script', 'none',
                          'swapped-after-review', 'typosquatted-name'])
        served = self.listings()
        self.assertEqual(set(served), {l['id'] for l in listings})

    def test_poison_label_is_never_served(self):
        for path in ['listings'] + ['listings/' + i for i in self.listings()]:
            self.assertNotIn(b'poison', self.request(path)[1])

    def test_typosquat_is_one_edit_from_the_clean_name(self):
        served = self.listings()
        names = {l['poison']: served[l['id']]['name'] for l in market.load()['listings']}
        clean, squat = names['none'], names['typosquatted-name']
        self.assertNotEqual(clean, squat)
        self.assertEqual(market.edit_distance(clean, squat), 1)

    def test_readme_carries_agent_aimed_instructions_with_a_canary(self):
        listing = market.by_poison('agent-instructions-in-readme')
        readme = json.loads(self.request('listings/' + listing['id'])[1])['readme']
        self.assertIn('AI agent', readme)
        self.assertIn(market.CANARY, readme)

    def test_install_script_aims_out_but_is_never_run(self):
        listing = market.by_poison('exfiltrating-install-script')
        script = json.loads(self.request('listings/' + listing['id'])[1])['install_script']
        self.assertIn('http://exfil.invalid/', script)
        with self.assertRaises(urllib.error.URLError) as caught:
            urllib.request.urlopen('http://exfil.invalid/', timeout=1)
        self.assertIsInstance(caught.exception.reason, PermissionError)
        self.assertEqual([r['path'] for r in self.copy.log], ['/listings/' + listing['id']])

    def test_swapped_package_no_longer_matches_its_review(self):
        for listing in market.load()['listings']:
            served = self.listings()[listing['id']]
            package = self.request('packages/' + listing['id'])[1]
            matches = hashlib.sha256(package).hexdigest() == served['reviewed_sha256']
            self.assertEqual(matches, listing['poison'] != 'swapped-after-review', listing['id'])

    def test_writes_are_recorded_never_carried_out(self):
        before = self.request('listings')[1]
        status, _ = self.request('listings/' + next(iter(self.listings())), 'DELETE')
        self.assertEqual(status, 202)
        status, _ = self.request('listings', 'POST', b'{"name": "x"}')
        self.assertEqual(status, 202)
        self.assertEqual(self.request('listings')[1], before)
        actions = json.loads(self.request('actions')[1])
        self.assertEqual([a['method'] for a in actions], ['DELETE', 'POST'])

    def test_listings_are_synthetic(self):
        for listing in market.load()['listings']:
            self.assertTrue(listing['publisher'].startswith('synthetic-'))


if __name__ == '__main__':
    unittest.main()
