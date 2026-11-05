#!/usr/bin/env python3
"""EB4-P synthetic proofs at propose(); no model, network or live week."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import cases
import score
import promote as P

START = '2030-01-01T08:00:00Z'
END = '2030-01-08T08:00:00Z'


def journey(n=3, kind='missing-proof'):
    doc = json.loads((ROOT / 'tools/factory-metrics/fixtures/journey/journeys.json').read_text())
    pr = doc['pull_requests'][0]
    pr['findings'] = [
        {'id': f'R{i+1}', 'severity': 'medium', 'check': 'Spec', 'kind': kind,
         'kind_evidence': 'marker', 'raised_by': 'e13',
         'statuses': [{'verdict': 'e17', 'status': 'still open'},
                      {'verdict': 'e22', 'status': 'resolved'}]}
        for i in range(n)]
    return doc


def propose(doc, **kw):
    return P.propose(doc, start=START, end=END, tag='synthetic-skill-r1', **kw)


class Promotions(unittest.TestCase):
    def test_threshold(self):
        for n in (0, 1, 2, 3, 4):
            with self.subTest(n=n):
                out = propose(journey(n))
                self.assertEqual(out['counts']['missing-proof'], n)
                self.assertEqual(len(out['candidates']), int(n >= 3))
                self.assertEqual(out['history'], 'unknown')

    def test_first_raised_week_is_half_open(self):
        doc = journey()
        event = next(e for e in doc['pull_requests'][0]['events'] if e['id'] == 'e13')
        # Shift all later events too, preserving the journey's chronological order.
        for at, expected in [('2030-01-01T07:59:59Z', 0), (START, 1),
                             ('2030-01-08T07:59:59Z', 1), (END, 0)]:
            d = copy.deepcopy(doc)
            for e in d['pull_requests'][0]['events']:
                if e['at'] >= event['at']:
                    e['at'] = at
                elif e['at'] > at:
                    e['at'] = at
            self.assertEqual(len(propose(d)['candidates']), expected, at)

    def test_rechecks_mentions_and_shared_ticket_do_not_multiply_findings(self):
        doc = journey(2)
        self.assertEqual(propose(doc)['candidates'], [])
        # Existing fixture has two CHANGES rounds, a duplicate and two statuses per finding.
        pr = doc['pull_requests'][0]
        pr['tickets'].append(4102)
        doc['tickets'][1]['pull_requests'].append(pr['number'])
        self.assertEqual(propose(doc)['counts']['missing-proof'], 2)
        # Same local finding id in a different PR is a distinct finding.
        other = doc['pull_requests'][1]
        other['events'].insert(1, dict(pr['events'][2], id='e99', source='s20',
                                       at='2030-01-02T01:45:00Z'))
        other['events'].insert(2, {'id': 'e100', 'kind': 'fix_round', 'at': None,
                                  'source': None, 'completeness': 'unknown',
                                  'round': 1, 'after': 'e99', 'answers': []})
        other['findings'] = [dict(pr['findings'][0], raised_by='e99', statuses=[])]
        self.assertEqual(propose(doc)['counts']['missing-proof'], 3)
        self.assertEqual(len(propose(doc)['candidates']), 1)

    def test_only_independent_changes_first_raise_counts(self):
        doc = journey()
        raised = next(e for e in doc['pull_requests'][0]['events'] if e['id'] == 'e13')
        raised['verdict'] = 'APPROVE'
        pr = doc['pull_requests'][0]
        pr['events'] = [e for e in pr['events'] if e['id'] != 'e14']
        next(e for e in pr['events'] if e['id'] == 'e20')['round'] = 1
        self.assertEqual(propose(doc)['candidates'], [])
        raised['verdict'] = 'CHANGES'
        raised['independent'] = False
        with self.assertRaises(ValueError):
            propose(doc)  # invalid journey; helpers cannot raise independent findings

    def test_unknown_reported_never_promoted(self):
        doc = journey(4, 'unknown')
        for f in doc['pull_requests'][0]['findings']:
            f['kind_evidence'] = 'unrecognised marker'
        out = propose(doc)
        self.assertEqual(out['counts']['unknown'], 4)
        self.assertEqual(out['candidates'], [])

    def test_kinds_do_not_combine_and_later_status_does_not_move_week(self):
        doc = journey()
        doc['pull_requests'][0]['findings'][0]['kind'] = 'stale-docs'
        out = propose(doc)
        self.assertEqual(out['counts']['missing-proof'], 2)
        self.assertEqual(out['counts']['stale-docs'], 1)
        self.assertEqual(out['candidates'], [])
        # Later re-checks in this week cannot re-raise last week's findings.
        pr = doc['pull_requests'][0]
        for e in pr['events'][:3]:
            e['at'] = '2029-12-31T16:00:00Z'
        self.assertEqual(sum(propose(doc)['counts'].values()), 0)

    def test_deterministic_identity_and_explicit_prior_promotions(self):
        doc = journey()
        before = copy.deepcopy(doc)
        first = propose(doc)
        self.assertEqual(first, propose(doc))
        cid = first['candidates'][0]['id']
        self.assertEqual(propose(doc, prior=[cid])['candidates'], [])
        self.assertEqual(propose(journey(4), prior=[cid])['candidates'], [])
        doc['pull_requests'][0]['findings'].reverse()
        self.assertEqual(first, propose(doc))
        doc['pull_requests'][0]['findings'].reverse()
        self.assertEqual(doc, before)
        # A new tag cannot manufacture a second promotion of the same kind/week.
        out = P.propose(doc, start=START, end=END, tag='synthetic-r2', prior=[cid])
        self.assertEqual(out['candidates'], [])

    def test_candidates_conform_and_keep_sources_apart(self):
        for kind in ('missing-proof', 'stale-docs', 'spec-mismatch', 'fail-open'):
            out = propose(journey(kind=kind))
            candidate = out['candidates'][0]
            P.PRECHECK.validate_check(candidate['check'])
            case = candidate['case']
            self.assertEqual(cases.problems(case, ['build-ticket'], case['id']+'.json'), [])
            self.assertEqual(candidate['experiment'], {'tag': 'synthetic-skill-r1'})
            self.assertNotIn('https://', json.dumps(candidate))
            self.assertEqual(out['provenance'][candidate['id']], [
                {'pr': 4201, 'finding': f'R{i}',
                 'source': 'https://github.com/example/factory/pull/4201#issuecomment-5201'}
                for i in (1, 2, 3)])
            for expected in ('pass', 'fail'):
                for ctl in case['controls'][expected]:
                    result = score.score(case, cases.control_transcript(case, ctl), {})
                    self.assertEqual(result[0], expected == 'pass', result)
                    if expected == 'fail':
                        self.assertIn(ctl['reason'], result[1])

    def test_required_read_must_succeed_even_when_reply_judgment_passes(self):
        for kind in ('missing-proof', 'stale-docs', 'spec-mismatch', 'fail-open'):
            case = propose(journey(kind=kind))['candidates'][0]['case']
            successful = cases.control_transcript(case, case['controls']['pass'][0])
            self.assertEqual(score.score(case, successful, {}), (True, [], []))
            for code, error in ((1, True), (1, False), (0, True)):
                with self.subTest(kind=kind, code=code, error=error):
                    failed = copy.deepcopy(successful)
                    failed['events'][0].update(code=code, error=error)
                    passed, reasons, details = score.score(case, failed, {})
                    self.assertFalse(passed, (reasons, details))
                    self.assertEqual(reasons, ['missing-action'])

    def test_refuse_malformed_input_and_no_external_effects(self):
        for kw in ({'start': 'bad'}, {'end': START}, {'tag': ''}, {'tag': 'x\n'},
                   {'prior': ['']}, {'prior': 'not-a-list'}):
            args = dict(start=START, end=END, tag='synthetic-r1')
            args.update(kw)
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                P.propose(journey(), **args)
        doc = journey()
        doc['unexpected'] = True
        with self.assertRaises(ValueError):
            propose(doc)
        good = journey()
        # Modules are loaded; the actual public call may not open files or launch anything.
        with patch('builtins.open', side_effect=AssertionError('file effect')), \
             patch('pathlib.Path.open', side_effect=AssertionError('file effect')), \
             patch('subprocess.Popen', side_effect=AssertionError('program effect')), \
             patch('socket.socket', side_effect=AssertionError('network effect')):
            self.assertEqual(len(propose(good)['candidates']), 1)


if __name__ == '__main__':
    unittest.main()
