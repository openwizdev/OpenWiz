#!/usr/bin/env python3
import http.client
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'keys'))

import intake  # noqa: E402 -- the copies' folders are put on the path first, since -I leaves them off
import loopback  # noqa: E402 -- the copies' folders are put on the path first, since -I leaves them off

ASKS = {'key': re.compile(r'\bkeys?\b', re.I), 'merge': re.compile(r'\bmerge\b', re.I),
        'rule': re.compile(r'\brules?\b', re.I), 'private': re.compile(r'\bprivate\b', re.I)}


def call(origin, method, path, body=None):
    host, port = origin.removeprefix('http://').split(':')
    conn = http.client.HTTPConnection(host, int(port), timeout=10)
    try:
        conn.request(method, path, body=None if body is None else json.dumps(body),
                     headers={'Content-Type': 'application/json'})
        answer = conn.getresponse()
        return answer.status, json.loads(answer.read())
    finally:
        conn.close()


class RequestIntake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        loopback.guard()

    def test_starts_on_loopback_only(self):
        with intake.Intake() as i:
            self.assertRegex(i.origin, r'^http://127\.0\.0\.1:[0-9]+$')
            self.assertEqual(i.server.server_address[0], '127.0.0.1')

    def test_serves_every_request_as_written_without_its_label(self):
        requests = intake.load()
        with intake.Intake() as i:
            status, served = call(i.origin, 'GET', '/requests')
            self.assertEqual(status, 200)
            self.assertEqual(served, [{k: v for k, v in r.items() if k != 'carries'} for r in requests])
            self.assertEqual(call(i.origin, 'GET', '/requests/2'), (200, served[1]))
            self.assertEqual(call(i.origin, 'GET', '/requests/99')[0], 404)

    def test_each_injection_is_carried_and_the_clean_request_carries_none(self):
        requests = intake.load()
        self.assertEqual(sorted(r['carries'] for r in requests), sorted(['none', *ASKS]))
        for r in requests:
            text = r['title'] + ' ' + r['body']
            asked = {kind for kind, ask in ASKS.items() if ask.search(text)}
            self.assertEqual(asked, set() if r['carries'] == 'none' else {r['carries']}, r['id'])

    def test_requests_are_synthetic(self):
        for r in intake.load():
            self.assertEqual(set(r), {'id', 'login', 'tier', 'title', 'body', 'carries'})
            self.assertRegex(r['login'], r'^synthetic-subscriber-[0-9]+$')
            self.assertNotRegex(r['body'], r'@|https?://|[A-Za-z0-9_-]{24,}')

    def test_writes_are_recorded_never_performed(self):
        with intake.Intake() as i:
            self.assertEqual(call(i.origin, 'POST', '/requests/3/merge', {'by': 'triage'}), (202, {'recorded': True}))
            self.assertEqual(call(i.origin, 'GET', '/actions'),
                             (200, [{'method': 'POST', 'path': '/requests/3/merge', 'body': {'by': 'triage'}}]))
            self.assertEqual(i.log, [{'method': 'POST', 'path': '/requests/3/merge', 'body': {'by': 'triage'}}])

    def test_copy_names_no_address_beyond_localhost(self):
        for name in sorted(os.listdir(HERE)):
            if name.endswith(('.py', '.json')) and not name.startswith('test_'):
                with open(os.path.join(HERE, name), encoding='utf-8') as f:
                    for url in re.findall(r'https?://[^\s\'"]*', f.read()):
                        self.assertRegex(url, r'^http://127\.0\.0\.1:', name)


if __name__ == '__main__':
    unittest.main()
