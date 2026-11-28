#!/usr/bin/env python3
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench


class Verdict(unittest.TestCase):
    def test_recorded_counts(self):
        data = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'verdict.json').read_text())
        self.assertEqual(bench.score_verdict(data), (9, 5, 8))


class Sent(unittest.TestCase):
    def test_only_the_word_of_an_eligible_line_is_sent(self):
        import verdict
        sha = 'ab' * 20
        self.assertEqual(verdict.sent_state(f'VERDICT: APPROVED at {sha}'), 'VERDICT: APPROVED')
        self.assertIsNone(verdict.sent_state(f'VERDICT: APPROVE at {sha}'))
        self.assertIsNone(verdict.sent_state('VERDICT: APPROVED at abc1234'))
        self.assertIsNone(verdict.sent_state(f"VERDICT: {'x' * 41} at {sha}"))


if __name__ == '__main__':
    unittest.main()
