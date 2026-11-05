#!/usr/bin/env python3
"""Offline C11 kit contract checks, also loaded by the C7 CI entrypoint.

The kit is preparation. Missing bindings and an accidentally executable live
mutation would misrepresent its authority; C6's data tests cannot catch that.
"""
from pathlib import Path
import re
import unittest

KIT = Path(__file__).with_name('batch-kit.md')
REQUIRED = ('Implementation candidate', 'Independent review', 'Authorization record',
            'Repository and resources', 'Base and combined head', 'Ordered members',
            'Current run and attempt', 'Checkpoint provenance', 'Trusted inventory',
            'Required checks', 'Maximum batches', 'Maximum members', 'Maximum pages',
            'Maximum reads', 'Time window', 'Separate nightly receipt',
            'Private raw archive', 'C4 measurement', 'Stop conditions', 'Rollback')


def kit_refusals(text):
    rows = re.findall(r'^\| ([^|]+?) \| (.+) \|$', text, re.M)
    names = [name for name, _ in rows]
    errors = ['missing or duplicate binding: '+name for name in REQUIRED if names.count(name) != 1]
    for phrase in ('PREPARATION ONLY', 'C11 authorization before live reads',
                   'per-push full runs remain', 'nightly full runs remain',
                   'no switch authority', 'No forced production failures',
                   'No real API or billing exhaustion'):
        if phrase not in text:
            errors.append('missing authority boundary: '+phrase)
    # Only finite local capture/reconcile/proof commands belong in this kit.
    for block in re.findall(r'```(?:sh|bash)\n(.*?)```', text, re.S):
        for line in block.splitlines():
            if line.strip() and not line.startswith('#') and not line.startswith('python3 -I '):
                errors.append('non-allowlisted executable kit line')
    return errors


class BatchKit(unittest.TestCase):
    def test_preparation_has_every_candidate_and_authority_binding(self):
        self.assertEqual(kit_refusals(KIT.read_text()), [])

    def test_missing_binding_or_live_mutation_is_detected(self):
        text = KIT.read_text()
        for field in REQUIRED:
            with self.subTest(field=field):
                without = '\n'.join(line for line in text.splitlines() if not line.startswith('| '+field+' |'))
                self.assertIn('missing or duplicate binding: '+field, kit_refusals(without))
        self.assertIn('non-allowlisted executable kit line',
            kit_refusals(text+'\n```sh\ngh api --method DELETE repos/synthetic/example/actions/runs/9001\n```'))


if __name__ == '__main__':
    unittest.main()
