#!/usr/bin/env python3
"""The installed first hour through a verified merge, and its fault cases (#2204, PR1 seam and PR4).

One attempt (journey.py) runs #1109's installed journey unchanged with a fresh
idea on the owner's own repository, then the fleet, independent review, CI and
merge, decided by the installed launch-fleet frontier on recording GitHub and
CloudRoom providers. #2222's fault cases rerun at this journey's seams. Every
expected code below is written by hand from contracts/first-hour.v1.md; #2200's
checks give the actual ones. A recording is never a pass: these prove
behaviour on fixtures, never a live first hour, a usable login or real time.
"""
import importlib.util
import json
from pathlib import Path
import re
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('first_hour_journey', HERE / 'journey.py')
journey = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(journey)

RECORDING = ['candidate_unknown', 'not_live']
# The attempt's honest unproven list: a recording with no clock, a harness only listed by setup,
# the live hour and the browser/removal seams named as gaps, and the setup gate still unresolved.
RESULT_UNPROVEN = sorted(['not_live', 'clock_unknown', 'stage_unverified:connections', 'gap:PR1', 'gap:PR4',
                          'gate_unresolved:cloudroom_setup'])
CASES = ['repeat_approval', 'process_restart', 'revoked_access', 'lost_reply', 'update_rejected', 'setup_interrupted']
PR, TICKET = journey.Attempt.PR, 921


def clean(unproven=RECORDING):
    return {'problems': [], 'failures': [], 'unproven': sorted(unproven)}


class InstalledFirstHour(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.holder = unittest.TestCase()
        cls.attempt = journey.Attempt(cls.holder)

    @classmethod
    def tearDownClass(cls):
        cls.holder.doCleanups()

    def test_a_fresh_idea_on_the_owners_repository_reaches_a_verified_merge(self):
        a = self.attempt
        doc = a.result
        self.assertEqual(journey.codes(doc), clean(RESULT_UNPROVEN), json.dumps(doc, indent=1))
        self.assertEqual(doc['repository'], {'known': {'full_name': 'synthetic-owner/synthetic-consumer', 'selected_by_owner': True}})
        states = {s['id']: s['state'] for s in doc['stages']}
        self.assertEqual(states, {'public_instruction': 'verified', 'install': 'verified', 'connections': 'unknown',
                                  'idea': 'verified', 'spec_confirmation': 'verified', 'plan_approval': 'verified',
                                  'fleet': 'verified', 'review': 'verified', 'ci': 'verified', 'merge': 'verified'})
        # The installed frontier asked for each step, read from the recording GitHub and CloudRoom.
        self.assertIn('review #%d for #%d at %s: first review' % (PR, TICKET, a.head), a.review_due)
        self.assertIn('merge #%d for #%d at %s: APPROVE and CI green' % (PR, TICKET, a.head), a.merge_due)
        self.assertEqual(a.merged['state'], 'MERGED')
        self.assertEqual(a.merged['head'], a.head, 'merged at the approved head, read back')
        # After the verified merge the frontier archives its agents and starts the ticket it unblocked.
        self.assertTrue(any(l.startswith('archive #%d: closed' % TICKET) for l in a.after_merge), a.after_merge)
        self.assertIn('start #924: L4: exit nonzero on a broken link (spec #920)', a.after_merge)
        self.assertFalse(any(l.startswith(('start #921', 'review #', 'merge #')) for l in a.after_merge))
        self.assertEqual(a.github.effects, {a.merge_op: 1}, 'one merge effect')

    def test_choices_confirmations_and_seats_are_the_users_and_independent(self):
        a = self.attempt
        doc = a.result
        choices = json.loads(a.j.state.read_text())['choices']
        self.assertEqual(choices, {'harness': 'codex', 'model': 'syn-codex-model-01', 'effort': 'high', 'agents': 'cloud'})
        self.assertEqual({k: doc['builder'][k] for k in ('harness', 'model', 'effort', 'location', 'usable')},
                         {'harness': 'codex', 'model': 'syn-codex-model-01', 'effort': 'high', 'location': 'cloud', 'usable': 'verified'})
        self.assertEqual({k: doc['reviewer'][k] for k in ('harness', 'usable')}, {'harness': 'claude_code', 'usable': 'verified'})
        self.assertEqual([t['harness'] for t in a.reviewer_threads], ['claude-code'], 'the other family reviewed')
        self.assertEqual(doc['reviewer']['extra_prerequisites'] != [], True)
        said = ' '.join(t.get('agent', '') for t in journey.CONVERSATION['turns'] if t['step'] == 'agents')
        self.assertIn('Claude Code sign-in for its reviewer', said, 'the extra account is explained before the plan')
        # Two separate saved decisions: the spec confirmation comes before the plan and its approval.
        comments = a.j.world['issues'][0]['comments']
        self.assertEqual([c['body'].split(' by ')[0] for c in comments], ['**Spec confirmed', '**Plan graph approved'])
        self.assertLess(comments[0]['id'], comments[1]['id'])
        turns = journey.CONVERSATION['turns']
        self.assertEqual([t['step'] for t in turns if 'plan' in t or t.get('approve')], ['plan', 'plan'])
        self.assertLess(next(i for i, t in enumerate(turns) if t.get('confirms') == 'spec'),
                        next(i for i, t in enumerate(turns) if 'plan' in t))

    def test_no_prepared_plan_inventory_readiness_or_agent_count_stands_in(self):
        a = self.attempt
        # The plan is this conversation's: none of its ticket titles ship in the installed skills.
        installed = ''.join(p.read_text(errors='replace') for p in (a.build / 'runtime/skills').rglob('*') if p.is_file())
        for t in a.j.tickets:
            self.assertNotIn(t['title'].split(': ', 1)[1], installed)
        stages = {s['id']: s for s in a.result['stages']}
        self.assertEqual([e['basis'] for e in stages['connections']['evidence']], ['harness_listed'])
        self.assertNotEqual(stages['connections']['state'], 'verified', 'a listed harness is not a usable login')
        # Swapping the merge's read-back for the running grid or a closed pull request is refused by the checks.
        for basis in ('agents_running', 'pr_closed'):
            doc = json.loads(json.dumps(a.result))
            merge = next(s for s in doc['stages'] if s['id'] == 'merge')
            merge['evidence'] = [dict(merge['evidence'][0], basis=basis)]
            self.assertEqual(journey.codes(doc)['problems'], ['stage_weak_evidence:merge'], basis)

    def test_each_fault_case_keeps_the_work_with_no_duplicate_effect_or_blind_retry(self):
        a = self.attempt
        self.assertEqual([c['case']['interruption'] for c in a.cases], CASES)
        for doc in a.cases:
            with self.subTest(doc['case']['interruption']):
                self.assertEqual(journey.codes(doc), clean(), json.dumps(doc, indent=1))
        self.assertEqual(a.notes['repeat_launch'][0], 0)
        self.assertIn('already started once', a.notes['repeat_launch'][1])
        self.assertEqual(len(a.j.logged('fleet.tick')), 1, 'the repeat ran no second tick')
        self.assertEqual(len(a.reviewer_threads), 1, 'one reviewer after the restart')
        self.assertEqual(a.notes['revoked'][0], 'refused: the App can no longer write to this repository')
        self.assertEqual(a.notes['revoked'][1], 'app_revoked', 'setup tells the owner the App was removed')
        self.assertEqual(a.notes['reconnected'], 'app_verified')
        self.assertEqual(a.github.calls[a.merge_op], 2, 'the refused call, then one merge after the read-back')
        self.assertEqual(a.notes['update'], {'outcome': 'refused', 'last_good_selected': True, 'update_build_absent': True})
        self.assertEqual(a.notes['setup_interrupted'], {'calls_before_apply': 0, 'lost_reply_returned': False,
                                                        'same_operation_id': True, 'resumed_phase': 'applied',
                                                        'provider_writes': 0})

    def test_the_result_joins_every_case_to_its_final_operations(self):
        doc = self.attempt.result
        self.assertEqual([c['interruption'] for c in doc['interruptions']], CASES)
        kinds = sorted(o['kind'] for o in doc['operations'])
        self.assertEqual(kinds, ['activate_engine', 'configure_access', 'merge', 'prepare_project'] + ['start_agent'] * 4)
        # Every intent that took effect did so once; the engine's preview stays proposed with no call or effect.
        self.assertEqual(sorted((o['kind'], o['phase'], o['effect_count']) for o in doc['operations']),
                         sorted([('activate_engine', 'proposed', 0), ('configure_access', 'applied', 1), ('merge', 'applied', 1),
                                 ('prepare_project', 'applied', 1)] + [('start_agent', 'applied', 1)] * 4))
        # Dropping a touched intent from the final inventory is caught, not hidden.
        dropped = json.loads(json.dumps(doc))
        dropped['operations'] = [o for o in dropped['operations'] if o['kind'] != 'merge']
        self.assertIn('final_operation_missing:' + self.attempt.merge_op, journey.codes(dropped)['unproven'])


class KnownWaysToFail(unittest.TestCase):
    """Each realistic bug on the journey's path changes the codes: the comparisons have teeth."""

    def attempt(self, **mutate):
        return journey.Attempt(self, mutate)

    def test_a_blind_merge_retry_merges_twice_and_fails(self):
        a = self.attempt(blind_merge_retry=True)
        got = journey.codes(a.result)
        self.assertIn('blind_retry:' + a.merge_op, got['failures'])
        self.assertIn('failure_not_reported', got['problems'])
        lost = next(c for c in a.cases if c['case']['interruption'] == 'lost_reply')
        self.assertIn('blind_retry:' + a.merge_op, journey.codes(lost)['failures'])

    def test_a_restart_that_starts_again_duplicates_the_reviewer_and_blocks_the_merge(self):
        a = self.attempt(blind_restart=True)
        case = next(c for c in a.cases if c['case']['interruption'] == 'process_restart')
        got = journey.codes(case)['failures']
        self.assertIn('duplicate_effect:' + a.review_op, got)
        self.assertIn('uncertainty_erased:' + a.review_op, got)
        # Two reviewer threads for one head: the frontier refuses to guess, so nothing merges.
        self.assertTrue(any(l.startswith('look #%d: two threads match' % PR) for l in a.merge_due), a.merge_due)
        self.assertEqual(a.github.calls, {})

    def test_red_ci_or_a_stale_verdict_never_reaches_a_merge(self):
        for mutate, stage in (({'ci_red': True}, 'ci'), ({'stale_verdict': True}, 'review')):
            with self.subTest(mutate):
                a = self.attempt(**mutate)
                self.assertFalse(any(l.startswith('merge #') for l in a.merge_due + a.review_due), a.merge_due)
                self.assertEqual(a.github.calls, {}, 'no merge call')
                got = journey.codes(a.result)
                self.assertIn('stage_unverified:merge', got['unproven'])
                if stage == 'ci':
                    self.assertIn('stage_failed:ci', got['failures'])
                else:
                    self.assertIn('stage_unverified:review', got['unproven'])


if __name__ == '__main__':
    unittest.main()
