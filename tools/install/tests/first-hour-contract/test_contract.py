#!/usr/bin/env python3
"""#2200 (PR1-PR7, contract proof only): contracts/first-hour.v1 refuses what it says it refuses.

Every expected code comes from tests/fixtures/first-hour/README.md, written by hand from
the contract's rules. These are synthetic examples: they prove interface consistency,
never an install, a login, a review, CI, a merge or the hour.
"""
import copy
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check = _load('first_hour_check', HERE / 'check.py')
CONTRACT = (ROOT / 'contracts/first-hour.v1.md').read_text()
FENCE = re.compile(r'^```json\n(.*?)\n^```$', re.S | re.M)
BLOCKS = FENCE.findall((ROOT / 'tests/fixtures/first-hour/README.md').read_text())
assert len(BLOCKS) == 1, 'the fixture README holds exactly one JSON map'
FIXTURES = check.strict_json(BLOCKS[0])
EXAMPLES = FIXTURES['examples']
VARIANTS = FIXTURES['variants']
BASE = 'recording-complete'
# A synthetic pointer in the open-development contract's good form. In memory only.
POINTER = 'https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001'
# Variants of the base that change nothing a live pass depends on, once the record is live.
CLEAN_ON_LIVE = {'fixture-claims-pass', 'synthetic-labelled-live', 'unlabelled-recording',
                 'reconciled-retry', 'fixed-blocker', 'ten-minute-missed-is-not-a-first-hour-failure',
                 'gate-settled-without-producers', 'gate-producers-while-unresolved',
                 'exactly-one-hour', 'ten-minute-met-at-the-limit',
                 'later-recovery-reconciles-intent', 'zero-call-proposal-result'}


def _at(doc, path):
    for key in path:
        doc = doc[key]
    return doc


def apply(doc, variant):
    doc = copy.deepcopy(doc)
    for path, value in variant.get('set', []):
        _at(doc, path[:-1])[path[-1]] = copy.deepcopy(value)
    for path, value in variant.get('append', []):
        _at(doc, path).append(copy.deepcopy(value))
    for path in variant.get('delete', []):
        del _at(doc, path[:-1])[path[-1]]
    return doc


def live(doc):
    """The base made live in memory: never a fixture, a record or evidence of anything."""
    doc = copy.deepcopy(doc)
    doc.update(proof_class='live', synthetic_assumptions=[], private_record=POINTER, verdict='pass')
    for n, name in enumerate(('cloudroom_setup', 'paid_offer', 'feedback')):
        doc['gates'][name].update(state='settled', producers=[9101 + n])
    return doc


def report(doc):
    r = check.check(doc)
    return {'problems': r.problems, 'failures': r.failures, 'unproven': r.unproven}


class FirstHourContract(unittest.TestCase):
    def test_each_example_gives_exactly_its_codes(self):
        for name, example in EXAMPLES.items():
            with self.subTest(name):
                self.assertEqual(report(example['document']), example['expect'])

    def test_each_variant_gives_exactly_its_codes(self):
        self.assertGreaterEqual(len(VARIANTS), 40)
        for name, variant in VARIANTS.items():
            with self.subTest(name):
                base = EXAMPLES[variant['from']]['document']
                changed = apply(base, variant)
                self.assertNotEqual(changed, base, 'a variant must change its example')
                self.assertEqual(report(changed), variant['expect'])

    def test_a_complete_live_record_is_the_only_pass(self):
        # Proves the checks can accept: a refuse-everything checker fails here.
        self.assertEqual(report(live(EXAMPLES[BASE]['document'])),
                         {'problems': [], 'failures': [], 'unproven': []})

    def test_no_failure_or_unproven_evidence_passes_even_when_live(self):
        for name, variant in VARIANTS.items():
            if variant['from'] != BASE:
                continue
            with self.subTest(name):
                doc = apply(live(EXAMPLES[BASE]['document']), variant)
                doc['verdict'] = 'pass'
                problems = check.check(doc).problems
                if name in CLEAN_ON_LIVE:
                    self.assertEqual(problems, [])
                else:
                    self.assertNotEqual(problems, [], 'a live pass was accepted')

    def test_a_strict_reader_refuses_duplicate_keys_and_fractions(self):
        text = json.dumps(EXAMPLES[BASE]['document'])
        self.assertEqual(check.check_text(text).problems, [])
        for bad in (text.replace('{"schema": "openwiz.first-hour.v1",', '{"schema": "openwiz.first-hour.v1", "schema": "openwiz.first-hour.v1",', 1),
                    text.replace('"effect_count": 1', '"effect_count": 1.0', 1),
                    text[:-1], 'NaN'):
            with self.subTest(bad[-40:]):
                self.assertNotEqual(bad, text)
                self.assertEqual(check.check_text(bad).problems, ['not_strict_json'])
        self.assertEqual(check.check_text('[]').problems, ['schema'])

    def test_recovery_missing_evidence_never_becomes_a_live_pass(self):
        # The public result boundary must also refuse incomplete standalone
        # recovery records, not merely a whole attempt containing them.
        for name, variant in VARIANTS.items():
            if variant['from'] == BASE:
                continue
            with self.subTest(name):
                doc = apply(EXAMPLES[variant['from']]['document'], variant)
                doc.update(proof_class='live', synthetic_assumptions=[],
                           private_record=POINTER, verdict='pass',
                           candidate=EXAMPLES[BASE]['document']['candidate'])
                if name in ('zero-call-proposal-recovery', 'recovery-claims-pass'):
                    self.assertEqual(report(doc), {'problems': [], 'failures': [], 'unproven': []})
                else:
                    self.assertNotEqual(check.check(doc).problems, [], 'incomplete recovery passed')

    def test_zero_call_proposed_and_refused_recoveries_remain_valid(self):
        # A saved proposal or pre-call refusal needs no invented provider call,
        # in either inventory and in either observed recovery phase.
        base = apply(EXAMPLES['recovery-lost-reply']['document'],
                     VARIANTS['zero-call-proposal-recovery'])
        for before in ('proposed', 'refused'):
            for after in ('proposed', 'refused'):
                for embedded in (False, True):
                    with self.subTest(before=before, after=after, embedded=embedded):
                        doc = copy.deepcopy(base)
                        op = doc['case']['operations'][0]
                        op.update(phase_before=before, phase_after=after)
                        if embedded:
                            case = doc['case']
                            op['kind'] = 'send'
                            doc = live(EXAMPLES[BASE]['document'])
                            doc['interruptions'] = [case]
                            doc['operations'][1].update(phase=after, attempts=0,
                                                        effect_count=0, reconciliation='none')
                        else:
                            doc.update(proof_class='live', synthetic_assumptions=[],
                                       private_record=POINTER, verdict='pass',
                                       candidate=EXAMPLES[BASE]['document']['candidate'])
                        self.assertEqual(report(doc),
                                         {'problems': [], 'failures': [], 'unproven': []})

    def test_the_contract_lists_every_code_the_checks_give(self):
        rows = re.findall(r'^\| `([a-z_]+)(?::[^`]*)?` \| (problem|failure|unproven) \|', CONTRACT, re.M)
        table = dict(rows)
        self.assertEqual(len(table), len(rows), 'a code listed twice')
        given = {'not_strict_json': 'problem'}  # check_text's, proven above
        docs = [e['document'] for e in EXAMPLES.values()]
        docs += [apply(EXAMPLES[v['from']]['document'], v) for v in VARIANTS.values()]
        for doc in docs:
            r = check.check(doc)
            for kind, codes in (('problem', r.problems), ('failure', r.failures), ('unproven', r.unproven)):
                given.update((c.split(':')[0], kind) for c in codes)
        self.assertEqual(given, table)

    def test_the_contract_stage_table_is_the_checks_order_and_evidence(self):
        rows = re.findall(r'^\| (\d+) \| `([a-z_]+)` \| `([a-z_]+)`', CONTRACT, re.M)
        self.assertEqual([int(n) for n, _, _ in rows], list(range(1, 11)))
        self.assertEqual([(s, b) for _, s, b in rows], list(check.ESTABLISH.items()))


GATE_ROW = re.compile(r'^\| `(cloudroom_setup|paid_offer|feedback)` \| (.+) \| (.+) \|$', re.M)
SETTLED = 'offer-settled-by-free-only-producer'


class FreeOnlyOfferGate(unittest.TestCase):
    """#2293 (PR6, gate portion only): the legacy `paid_offer` gate and its schema stay;
    the free-only decision (#2202) and its one producer (#2293) settle it. No paid trial
    receipt is needed or invented. Synthetic records: this proves no free use or merge."""

    def test_the_contract_keeps_three_gates_and_names_the_free_only_producer(self):
        rows = {name: (decision, today) for name, decision, today in GATE_ROW.findall(CONTRACT)}
        self.assertEqual(list(rows), ['cloudroom_setup', 'paid_offer', 'feedback'])
        decision, today = rows['paid_offer']
        self.assertTrue(decision.startswith('#2202: the free-only friends-first release'), decision)
        self.assertIn('[public-offer.v1](public-offer.v1.md)', decision)
        self.assertIn('Its one approved producer is #2293', decision)
        self.assertIn('settles no paid benefit, payment arrangement or trial', decision)
        self.assertEqual(today, "`unresolved` until #2293's verified merge; then `settled`, with producers `[2293]`")
        self.assertEqual(rows['cloudroom_setup'][1], '`unresolved`', 'the setup gate is unchanged')

    def test_only_the_free_only_producer_settles_the_offer_gate_and_never_alone(self):
        doc = apply(EXAMPLES['recording-feedback-settled']['document'], VARIANTS[SETTLED])
        self.assertEqual(doc['gates']['paid_offer'], {'decision_ticket': 2202, 'state': 'settled', 'producers': [2293]})
        doc.update(proof_class='live', synthetic_assumptions=[], private_record=POINTER, verdict='pass')
        # The unchanged setup gate still refuses success.
        self.assertEqual(report(doc), {'problems': ['unproven_pass'], 'failures': [],
                                       'unproven': ['gate_unresolved:cloudroom_setup']})
        doc['gates']['cloudroom_setup'].update(state='settled', producers=[9101])
        self.assertEqual(report(doc), {'problems': [], 'failures': [], 'unproven': []})
        # Missing or unresolved producer evidence refuses success again.
        for state, producers, problems in (('unresolved', [], ['unproven_pass']),
                                           ('settled', [], ['gate_producers:paid_offer', 'unproven_pass']),
                                           ('unresolved', [2293], ['gate_producers:paid_offer', 'unproven_pass'])):
            with self.subTest(state=state, producers=producers):
                gap = copy.deepcopy(doc)
                gap['gates']['paid_offer'].update(state=state, producers=producers)
                self.assertEqual(report(gap), {'problems': problems, 'failures': [],
                                               'unproven': ['gate_unresolved:paid_offer']})


if __name__ == '__main__':
    unittest.main()
