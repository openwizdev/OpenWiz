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


if __name__ == '__main__':
    unittest.main()
