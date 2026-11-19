#!/usr/bin/env python3
"""KN10: the records v1 claim and lease rules hold in the model, and each broken variant fails.

Run: python3 -I kernel/records/model/test_model.py
"""
import os
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model  # noqa: E402


def run(*args):
    p = subprocess.run([sys.executable, '-I', os.path.join(HERE, 'model.py'), *args],
                       capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout.splitlines(), p.stderr


# Each variant breaks the rule it drops, and exactly these rules in all.
BREAKS = {
    'no-post-fence': {'P1', 'P4'},
    'older-only-fence': {'P2', 'P4'},
    'edit-stopped': {'P3'},
    'asking-not-claiming': {'P1', 'P2', 'P4'},
}


def broken(lines):
    return {line.split()[1].rstrip(':') for line in lines if line.startswith('broken ')}


class CurrentRules(unittest.TestCase):
    def test_every_rule_holds_over_every_reachable_state(self):
        code, out, err = run()
        self.assertEqual((code, err), (0, ''), out)
        self.assertEqual(len(out), 1, out)
        self.assertRegex(out[0], r'^ok: atomic writes, current rules: P1 to P4 hold over \d+ states$')


class BrokenVariants(unittest.TestCase):
    def test_each_variant_breaks_the_rule_it_drops(self):
        self.assertEqual(sorted(rule for rule, _ in model.VARIANTS.values()), sorted(model.RULES))
        self.assertEqual(set(BREAKS), set(model.VARIANTS))
        for variant, (rule, _) in model.VARIANTS.items():
            with self.subTest(variant=variant):
                code, out, err = run('--variant', variant)
                self.assertEqual((code, err), (1, ''), out)
                self.assertIn(rule, BREAKS[variant])
                self.assertEqual(broken(out), BREAKS[variant], out)
                self.assertFalse(any(line.startswith('vacuous') for line in out), out)
                # A counterexample is a numbered trace, not just a verdict.
                self.assertTrue(any(line.startswith('  1. ') for line in out), out)


class SplitWrites(unittest.TestCase):
    def test_the_pinned_writers_read_then_write_order_loses_the_fence(self):
        # Reported on #1365: a lapsed note's re-read and its edit are two calls, so a newer
        # note can claim between them and the lapsed one still takes the ticket back.
        code, out, err = run('--writes', 'split')
        self.assertEqual((code, err), (1, ''), out)
        self.assertEqual(broken(out), {'P1', 'P2', 'P3', 'P4'}, out)

    def test_the_lost_release_needs_two_overlapping_wakes(self):
        saved = model.RUNS['split']
        try:
            model.RUNS['split'] = (1, 1)
            _, single, _ = model.check(model.Model(None, 'split'))
        finally:
            model.RUNS['split'] = saved
        _, overlapping, _ = model.check(model.Model(None, 'split'))
        self.assertEqual(set(single), {'P1', 'P2', 'P4'})
        self.assertEqual(set(overlapping), {'P1', 'P2', 'P3', 'P4'})


class NotVacuous(unittest.TestCase):
    def test_the_current_rules_meet_every_witness(self):
        _, found, seen = model.check(model.Model())
        self.assertEqual(found, {})
        self.assertEqual(seen, set(model.WITNESSES))

    def test_a_model_where_time_never_passes_misses_the_lapse_witness(self):
        class Frozen(model.Model):
            def steps(self, s):
                return (step for step in super().steps(s) if step[0] != 'time passes')
        _, found, seen = model.check(Frozen())
        self.assertEqual(found, {})
        self.assertNotIn('lapsed beside a newer holder', seen)


if __name__ == '__main__':
    unittest.main(verbosity=2)
