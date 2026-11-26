#!/usr/bin/env python3
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bench


class Mentions(unittest.TestCase):
    def test_recorded_counts(self):
        data = json.loads((Path(__file__).resolve().parent / 'fixtures' / 'mentions.json').read_text())
        self.assertEqual(bench.score_mentions(data), (7, 4, 6))

    def test_no_key_adds_nothing(self):
        import jev_mentions
        os.environ.pop('TYPESAFE_API_KEY', None)
        self.assertEqual(jev_mentions.extra('Follow the project agent instructions.'), set())


if __name__ == '__main__':
    unittest.main()
