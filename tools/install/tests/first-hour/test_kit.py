#!/usr/bin/env python3
"""The first-hour live kit's offline proofs (#2204): its steps, eligibility and result validation.

Synthetic records only: every pointer, commit, digest and repository is
invented. These prove the kit's shape and rules, never a live run. The
documents start from #2200's synthetic `recording-complete` example
(tests/fixtures/first-hour/README.md); each expectation is written by hand
from first-hour-live-kit.md and contracts/first-hour.v1.md.
"""
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
_spec = importlib.util.spec_from_file_location('first_hour_kit', HERE / 'kit.py')
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)

POINTER = 'https://github.com/jparker2006/ClosedWiz/issues/1#issuecomment-%d'
FINGERPRINT = '3' * 64


def producer(ticket, merged=True):
    return {'ticket': ticket, 'pr': ticket + 1000, 'merge_commit': '4' * 40, 'approved_head': '5' * 40,
            'merged_at_head': merged}


def record(cloudroom=(9001,)):
    """An eligibility record; by default every gate has a verified producer (9001 is synthetic)."""
    return {'schema': 'openwiz.first-hour-kit-eligibility.v1',
            'graph': {'revision': 13, 'fingerprint': FINGERPRINT, 'approval': POINTER % 10},
            'gates': {'cloudroom_setup': [producer(t) for t in cloudroom], 'paid_offer': [producer(2293)],
                      'feedback': [producer(2292)]},
            'authority': {s: POINTER % (20 + i) for i, s in enumerate(kit.SCOPES)}}


def example():
    text = (ROOT / 'tests/fixtures/first-hour/README.md').read_text()
    return json.loads(re.search(r'```json\n(.*?)\n```', text, re.S).group(1))['examples']['recording-complete']['document']


def live():
    """The synthetic example as a live record would carry it: a pointer, no assumptions, every gate settled."""
    doc = copy.deepcopy(example())
    doc.update(proof_class='live', synthetic_assumptions=[], private_record=POINTER % 30, verdict='unverified')
    doc['gates'] = {'cloudroom_setup': {'decision_ticket': 2201, 'state': 'settled', 'producers': [9001]},
                    'paid_offer': {'decision_ticket': 2202, 'state': 'settled', 'producers': [2293]},
                    'feedback': {'decision_ticket': 2203, 'state': 'settled', 'producers': [2292]}}
    return doc


def binding(doc):
    starts = sum(1 for o in doc['operations'] if o['kind'] == 'start_agent')
    return {'schema': 'openwiz.first-hour-kit-binding.v1', 'candidate': doc['candidate']['known'],
            'host': {'target': doc['candidate']['known']['target'], 'fresh_account': True},
            'scope': {'repository': doc['repository']['known']['full_name'],
                      'app_repositories': [doc['repository']['known']['full_name']]},
            'counts': {'builders': starts, 'reviewers': 1, 'merges': 1, 'feedback_issues': 1, 'shares': 1},
            'recorded': {'waits': len(doc['waits']), 'help': len(doc['help'])},
            'graph': {'revision': 13, 'fingerprint': FINGERPRINT}}


class Steps(unittest.TestCase):
    def test_the_kit_is_bounded_and_extends_the_existing_one(self):
        rows = kit.steps()
        self.assertEqual([r[0] for r in rows], ['H%d' % i for i in range(1, 16)])
        names = [r[1] for r in rows]
        for needed in ('instruction', 'connections', 'refused-connection', 'idea', 'confirmations', 'fleet',
                       'interruption', 'review-and-ci', 'merge', 'free-only', 'feedback-and-share', 'cleanup'):
            self.assertIn(needed, names)
        self.assertEqual({r[1]: r[3] for r in rows if r[3]},
                         {'cloudroom': 'cloudroom_setup', 'free-only': 'paid_offer', 'feedback-and-share': 'feedback'})
        text = kit.KIT.read_text()
        self.assertIn('grants no live, account, feedback-send, spending, cut-over, ship or publishing authority', text)
        self.assertIn('[0.0.13 live kit](live-kit.md)', text)
        # Both timing targets, independently: the hour's clock and #1110's unchanged ten-minute definition.
        self.assertIn('from H2 (the public instruction opened) to H12', text)
        self.assertIn("[live-kit.md](live-kit.md)'s definition, unchanged", text)
        self.assertIn('neither is derived from the other', text)

    def test_the_dry_run_has_no_effect_and_names_what_refuses_final_execution(self):
        out = io.StringIO()
        self.assertEqual(kit.dry_run(record(cloudroom=()), out), 0)
        lines = out.getvalue().splitlines()
        self.assertEqual(len([l for l in lines if l.startswith('H')]), 15)
        self.assertTrue(all('no effect in a dry run' in l for l in lines if l.startswith('H')))
        self.assertIn('H4 cloudroom (write) at +240000 ms: ineligible: gate cloudroom_setup has no verified producer; '
                      'no effect in a dry run', lines)
        self.assertIn('H14 feedback-and-share (write) at +840000 ms: would run (feedback: producers #2292); '
                      'no effect in a dry run', lines)
        self.assertIn('Final execution refused: Gate cloudroom_setup (#2201) has no producer in the approved graph: '
                      'ineligible until one is added and merged.', lines)
        out = io.StringIO()
        kit.dry_run(None, out)
        self.assertIn('Final execution refused: No eligibility record was given.', out.getvalue())


class Eligibility(unittest.TestCase):
    def test_todays_gates_refuse_until_the_setup_producer_merges(self):
        self.assertEqual(kit.eligibility(record(cloudroom=())),
                         ['Gate cloudroom_setup (#2201) has no producer in the approved graph: ineligible until one '
                          'is added and merged.'])
        self.assertEqual(kit.eligibility(record()), [])

    def test_a_closed_producer_missing_authority_or_graph_refuses(self):
        r = record()
        r['gates']['feedback'] = [producer(2292, merged=False)]
        self.assertEqual(kit.eligibility(r), ['Gate feedback producer #2292 has no verified merge at its approved head '
                                              '(a closed issue is not one).'])
        r = record()
        r['authority']['spending'] = None
        self.assertEqual(kit.eligibility(r), ['No recorded spending authority for these exact steps and counts.'])
        r = record()
        r['graph']['approval'] = 'https://example.invalid/approval'
        self.assertEqual(kit.eligibility(r), ['The approved #2194 graph revision, fingerprint and approval pointer '
                                              'are missing or malformed.'])
        self.assertEqual(kit.eligibility({'schema': 'openwiz.first-hour-kit-eligibility.v1'}),
                         ['The eligibility record must be openwiz.first-hour-kit-eligibility.v1 with exactly its fields.'])


class Validate(unittest.TestCase):
    def run_kit(self, doc, bind=None, rec=None):
        return kit.validate(json.dumps(doc), bind or binding(live()), rec or record())

    def test_a_bound_live_result_is_valid_and_keeps_its_codes(self):
        refusals, codes = self.run_kit(live())
        self.assertEqual(refusals, [])
        self.assertEqual(codes, {'problems': [], 'failures': [], 'unproven': []})

    def test_synthetic_proof_is_never_a_live_observation(self):
        doc = example()
        refusals, codes = self.run_kit(doc)
        self.assertIn('A recording document is synthetic proof, not a live observation.', refusals)
        self.assertIn('not_live', codes['unproven'])

    def test_each_binding_rule_refuses(self):
        cases = []
        doc = live(); doc['candidate']['known']['source'] = '6' * 40
        cases.append((doc, 'The result is for another candidate than the bound one.'))
        doc = live(); doc['repository']['known']['full_name'] = 'syn-owner/another'
        cases.append((doc, 'The result is for another repository than the bound one.'))
        doc = live(); doc['operations'].append(dict(next(o for o in doc['operations'] if o['kind'] == 'merge'),
                                                    operation_id='7' * 32))
        cases.append((doc, 'The run merged more than the bound merges.'))
        doc = live(); doc['waits'] = doc['waits'][1:]
        cases.append((doc, 'The result does not keep every wait and help the run recorded.'))
        doc = live(); doc['gates']['feedback']['producers'] = [9999]
        cases.append((doc, 'Gate feedback does not match the verified producers.'))
        doc = live(); doc['findings'] = [{'id': 'F1', 'severity': 'low', 'work_loss': False, 'owner': None,
                                          'summary': 'Synthetic note from someone@example.com', 'disposition': 'open'}]
        cases.append((doc, 'The result holds something that looks like an account, id, token, email or path.'))
        for doc, expected in cases:
            with self.subTest(expected):
                refusals, _ = self.run_kit(doc, binding(live()))
                self.assertEqual(refusals, [expected])

    def test_private_looking_values_refuse_however_the_json_spells_them(self):
        # R1: the same decoded evidence, written with JSON escapes, must refuse like its literal spelling.
        expected = ['The result holds something that looks like an account, id, token, email or path.']
        spellings = {'literal': lambda t: t,
                     'escaped': lambda t: t.replace('@', r'\u0040').replace('/', r'\/'),
                     'h-escaped': lambda t: t.replace('h', r'\u0068')}
        for value in ('someone@example.com', '/home/synthetic-user/evidence', 'thr_syn0001'):
            doc = live()
            doc['findings'] = [{'id': 'F1', 'severity': 'low', 'work_loss': False, 'owner': None,
                                'summary': 'Synthetic note: ' + value, 'disposition': 'open'}]
            for name, spell in spellings.items():
                with self.subTest(value=value, spelling=name):
                    text = spell(json.dumps(doc))
                    self.assertEqual(json.loads(text), doc, 'the same decoded document')
                    refusals, _ = kit.validate(text, binding(live()), record())
                    self.assertEqual(refusals, expected)

    def test_a_malformed_binding_another_graph_or_a_refused_document_refuses(self):
        bad = binding(live()); bad['counts']['feedback_issues'] = 2
        self.assertEqual(self.run_kit(live(), bad)[0], ['The counts are malformed or exceed one feedback issue and one share.'])
        other = binding(live()); other['graph']['revision'] = 12
        self.assertEqual(self.run_kit(live(), other)[0], ['The binding names another graph revision than the eligibility record.'])
        doc = live(); doc['schema'] = 'openwiz.first-hour.v0'
        refusals, codes = self.run_kit(doc)
        self.assertEqual((refusals, codes['problems']), (["#2200's checks refuse the result: schema"], ['schema']))
        doc = live(); doc['clock']['ended_at_ms']['known'] = doc['clock']['started_at_ms']['known'] + 3600001
        refusals, codes = self.run_kit(doc)
        self.assertEqual(codes['failures'], ['hour_missed'])
        self.assertIn('failure_not_reported', codes['problems'], 'a missed hour must be reported as a fail')


if __name__ == '__main__':
    unittest.main()
