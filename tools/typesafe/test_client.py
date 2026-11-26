#!/usr/bin/env python3
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import client


KEY = 'synthetic-typesafe-key'


class Client(unittest.TestCase):
    def test_missing_key_builds_nothing(self):
        with mock.patch.dict(os.environ, {'TYPESAFE_API_KEY': ''}, clear=False):
            os.environ.pop('TYPESAFE_API_KEY', None)
            self.assertIsNone(client.from_env())

    def test_post_body_matches_the_documented_request(self):
        seen = {}

        def post(url, body, headers, timeout):
            seen.update(url=url, body=body, headers=headers, timeout=timeout)
            answer = {'model': 'jev-1.14.0', 'answers': {'q': {'type': 'noul', 'noul': 0.5}},
                      'usage': {'input_tokens': 3, 'output_tokens': 1}}
            return 200, json.dumps(answer).encode()

        http = client.HttpClient(KEY, post=post)
        response = http.system_one('hello', {'q': {'type': 'noul', 'instructions': 'Is it so?'}})
        self.assertEqual(seen['url'], 'https://api.typesafe.ai/v1/systemone')
        self.assertEqual(seen['headers']['Authorization'], 'Bearer ' + KEY)
        self.assertEqual(seen['timeout'], 10)
        sent = json.loads(seen['body'])
        self.assertEqual(sent['model'], 'jev-1.14.0')
        self.assertEqual(sent['state'], 'hello')
        self.assertEqual(sent['questions']['q']['type'], 'noul')
        self.assertEqual(client.noul(response, 'q'), 0.5)
        self.assertNotIn(KEY, repr(http))

    def test_http_error_hides_the_key(self):
        def post(url, body, headers, timeout):
            raise urllib_error()

        http = client.HttpClient(KEY, post=post)
        with self.assertRaises(client.TypeSafeError) as caught:
            http.system_one('hello', {'q': {'type': 'noul', 'instructions': 'Is it so?'}})
        self.assertNotIn(KEY, str(caught.exception))
        self.assertEqual(str(caught.exception), 'network')

    def test_status_error_is_http_and_hides_the_body(self):
        def post(url, body, headers, timeout):
            return 401, KEY.encode()

        http = client.HttpClient(KEY, post=post)
        with self.assertRaises(client.TypeSafeError) as caught:
            http.system_one('hello', {'q': {'type': 'noul', 'instructions': 'Is it so?'}})
        self.assertEqual(str(caught.exception), 'http')
        self.assertNotIn(KEY, str(caught.exception))

    def test_long_state_is_cut_before_it_is_sent(self):
        seen = {}

        def post(url, body, headers, timeout):
            seen['body'] = body
            return 200, b'{"answers": {"q": {"type": "noul", "noul": 0}}}'

        client.HttpClient(KEY, post=post).system_one('x' * (client.MAX_STATE_CHARS + 5),
                                                     {'q': {'type': 'noul', 'instructions': 'Is it so?'}})
        self.assertEqual(len(json.loads(seen['body'])['state']), client.MAX_STATE_CHARS)

    def test_fake_records_the_call_and_does_not_need_a_key(self):
        fake = client.FakeClient({'q': {'type': 'noul', 'noul': 0.2}})
        fake.system_one('s', {'q': {'type': 'noul', 'instructions': 'Is it so?'}})
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(client.noul(fake.system_one('s', {'q': {}}), 'q'), 0.2)

    def test_choice_reads_probability_and_confidence(self):
        response = {'answers': {'verdict': {
            'type': 'choice', 'choice': 'pass', 'confidence': 0.8,
            'probabilities': {'pass': 0.7, 'fail': 0.3}}}}
        self.assertEqual(client.choice(response, 'verdict'), ('pass', 0.7, 0.8))

    def test_ask_script_with_no_key_prints_nothing(self):
        import subprocess
        script = Path(__file__).resolve().parent / 'ask.py'
        env = {k: v for k, v in os.environ.items() if k != 'TYPESAFE_API_KEY'}
        ran = subprocess.run([sys.executable, '-I', str(script)], input=b'{}', capture_output=True, env=env)
        self.assertEqual(ran.returncode, 1)
        self.assertEqual(ran.stdout, b'')
        self.assertEqual(ran.stderr, b'')
        self.assertNotIn(b'Bearer', ran.stdout + ran.stderr)


def urllib_error():
    import urllib.error
    return urllib.error.URLError('synthetic failure')


if __name__ == '__main__':
    unittest.main()
