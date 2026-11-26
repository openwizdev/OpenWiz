#!/usr/bin/env python3
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench
import client
import turn_end


class _Yes:
    def system_one(self, state, questions, model=client.MODEL):
        return {'model': model, 'answers': {'limit': {'type': 'noul', 'noul': 0.95}}}


class TurnEnd(unittest.TestCase):
    def test_recorded_counts(self):
        data = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'turn_end.json').read_text())
        self.assertEqual(bench.score_turn_end(data), (6, 4, 5))

    def test_no_key_is_false(self):
        os.environ.pop('TYPESAFE_API_KEY', None)
        self.assertFalse(turn_end.usage_limit('Claude usage limit reached'))

    def test_fake_client_is_true(self):
        self.assertTrue(turn_end.usage_limit('Claude usage limit reached', _Yes()))


if __name__ == '__main__':
    unittest.main()
