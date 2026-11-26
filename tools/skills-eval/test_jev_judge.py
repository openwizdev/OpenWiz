#!/usr/bin/env python3
import json
import os
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'typesafe'))
import client
import driver
import jev_judge


def recorded(name, probability, confidence):
    other = 'fail' if name == 'pass' else 'pass'
    return {'model': 'jev-1.14.0', 'answers': {'verdict': {
        'type': 'choice', 'choice': name, 'confidence': confidence,
        'probabilities': {name: probability, other: round(1 - probability, 10)}}}}


class Judge(unittest.TestCase):
    def test_a_confident_choice_is_the_verdict_and_the_model_is_not_called(self):
        fake = client.FakeClient(recorded('pass', 0.91, 0.8)['answers'], model='jev-1.14.0')
        called = []
        verdict, stop = driver.judge('Name the file.', 'Changed client.py.', {}, lambda body: called.append(body),
                                     ask=fake)
        self.assertEqual(called, [])
        self.assertIsNone(stop)
        self.assertEqual(verdict['verdict'], 'pass')
        self.assertEqual(verdict['reason'], 'The reply meets the rule.')
        self.assertEqual(verdict['model'], 'jev-1.14.0')
        self.assertEqual(fake.calls[0]['questions']['verdict']['type'], 'choice')

    def test_low_confidence_falls_back_to_the_json_judge(self):
        fake = client.FakeClient(recorded('fail', 0.55, 0.4)['answers'])
        body = {'content': [{'type': 'text', 'text': '{"verdict": "pass", "reason": "It meets the rule."}'}],
                'stop_reason': 'end_turn'}

        def call(payload):
            return body, None, None

        verdict, stop = driver.judge('Name the file.', 'Changed client.py.', {'judge_model': 'synthetic'}, call,
                                     ask=fake)
        self.assertEqual((verdict['verdict'], verdict['model'], stop), ('pass', 'synthetic', None))

    def test_a_client_error_falls_back(self):
        fake = client.FakeClient(error='http')
        body = {'content': [{'type': 'text', 'text': '{"verdict": "fail", "reason": "It does not."}'}],
                'stop_reason': 'end_turn'}
        verdict, _ = driver.judge('rule', 'reply', {'judge_model': 'synthetic'}, lambda payload: (body, None, None),
                                  ask=fake)
        self.assertEqual(verdict['verdict'], 'fail')

    def test_no_client_keeps_the_parser(self):
        text = '{"verdict": "pass", "reason": "It meets the rule."}'
        self.assertEqual(jev_judge.parse_model_text(text)['verdict'], 'pass')
        self.assertIsNone(jev_judge.parse_model_text('not json'))
        self.assertIsNone(jev_judge.from_response(recorded('pass', 0.5, 0.5)))

    def test_unset_key_does_not_ask(self):
        os.environ.pop('TYPESAFE_API_KEY', None)
        self.assertIsNone(jev_judge.try_jev('rule', 'reply'))


class Bench(unittest.TestCase):
    def test_recorded_fixture_counts(self):
        data = json.loads((HERE.parent / 'typesafe' / 'fixtures' / 'judge.json').read_text())
        n, old_hit, shaped_hit = __import__('bench', fromlist=['score_judge']).score_judge(data)
        self.assertEqual((n, old_hit, shaped_hit), (6, 4, 5))


if __name__ == '__main__':
    unittest.main()
