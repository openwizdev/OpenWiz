#!/usr/bin/env python3
"""P8/P11 map foundation at the command boundary, synthetic gh only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PLAN = HERE / 'plan.py'
FAKE = HERE / 'fake-gh'


def fixture():
    return {
        'issues': [
            {'number': 9001}, {'number': 9002}, {'number': 9003},
            {'number': 1257}, {'number': 1283},
        ],
        'pulls': [{'number': 9010}],
        'remaining': [1283],
    }


class PlanContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.world = self.root / 'world.json'
        self.log = self.root / 'gh.jsonl'
        self.env = dict(os.environ, OPEN_TICKETS_WORLD=str(self.world),
                        OPEN_TICKETS_LOG=str(self.log))
        self.world.write_text(json.dumps(fixture()))

    def run_plan(self, *args, ok=True):
        r = subprocess.run([sys.executable, '-I', str(PLAN), *map(str, args)],
                           env=self.env, text=True, capture_output=True)
        self.assertEqual(r.returncode == 0, ok, r.stderr or r.stdout)
        return r

    def generate(self):
        out = self.root / 'out'
        self.run_plan('--gh', FAKE, '--target', 'synthetic-org/openwiz', '--out', out)
        return out

    def test_p8_p11_read_only_complete_inventory_and_planned_mapping(self):
        out = self.generate()
        self.assertEqual((out / 'map.dry-run.tsv').read_text(),
                         'kind\tclosedwiz\topenwiz\n'
                         'issue\t9001\tplanned\nissue\t9002\tplanned\n'
                         'issue\t9003\tplanned\npull_request\t9010\tplanned\n')
        inventory = json.loads((out / 'inventory.json').read_text())
        self.assertEqual(inventory['excluded'], [1257, 1283])
        self.assertEqual(inventory['counts'], {'open_issues': 5, 'open_pull_requests': 1,
                                              'moving_issues': 3, 'moving_pull_requests': 1})
        self.run_plan('--check-map', out / 'map.dry-run.tsv',
                      '--inventory', out / 'inventory.json')
        # The fake refuses every command outside its read-only surface.
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        self.assertEqual(len(calls), 8)
        self.assertTrue(all(c[:2] == ['api', '--method'] and c[2] == 'GET' for c in calls))

    def test_p11_missing_duplicate_and_malformed_rows_refused(self):
        out = self.generate()
        clean = (out / 'map.dry-run.tsv').read_text()
        cases = {
            'missing': clean.replace('issue\t9002\tplanned\n', ''),
            'duplicate': clean + 'issue\t9002\tplanned\n',
            'wrong-kind': clean.replace('pull_request\t9010', 'issue\t9010'),
            'real-number-in-dry-run': clean.replace('9010\tplanned', '9010\t4010'),
            'leading-zero': clean.replace('9002\tplanned', '09002\tplanned'),
            'unsorted': clean.replace('9001\tplanned\nissue\t9002', '9002\tplanned\nissue\t9001'),
            'crlf': clean.replace('\n', '\r\n'),
            'no-final-newline': clean.rstrip('\n'),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                bad = self.root / (name + '.tsv')
                bad.write_bytes(content.encode())
                r = self.run_plan('--check-map', bad, '--inventory', out / 'inventory.json', ok=False)
                self.assertIn('map:', r.stderr)

    def test_failed_partial_and_duplicate_reads_refuse_without_artifacts(self):
        for mode in ['failed', 'partial', 'duplicate', 'bad-number', 'truncated', 'changed', 'partial-children']:
            with self.subTest(mode=mode):
                self.log.unlink(missing_ok=True)
                world = fixture()
                world['mode'] = mode
                self.world.write_text(json.dumps(world))
                out = self.root / mode
                self.run_plan('--gh', FAKE, '--target', 'synthetic-org/openwiz',
                              '--out', out, ok=False)
                self.assertFalse(out.exists())

    def test_final_api_target_is_default_and_apply_still_refuses(self):
        out = self.root / 'default-target'
        self.run_plan('--gh', FAKE, '--out', out)
        self.assertEqual(json.loads((out / 'inventory.json').read_text())['target'], 'openwizdev/openwiz')
        before = self.log.read_bytes()
        self.run_plan('--gh', FAKE, '--target', 'synthetic-org/openwiz',
                      '--out', self.root / 'apply', '--apply', ok=False)
        self.assertEqual(self.log.read_bytes(), before)

    def test_inventory_tampering_refused(self):
        out = self.generate()
        path = out / 'inventory.json'
        original = json.loads(path.read_text())
        cases = []
        missing = copy.deepcopy(original)
        missing['moves'].pop()
        cases.append(missing)
        duplicate = copy.deepcopy(original)
        duplicate['moves'].append(duplicate['moves'][0])
        cases.append(duplicate)
        extra = copy.deepcopy(original)
        extra['ignored'] = True
        cases.append(extra)
        for value in cases:
            path.write_text(json.dumps(value))
            self.run_plan('--check-map', out / 'map.dry-run.tsv', '--inventory', path, ok=False)


if __name__ == '__main__':
    unittest.main()
