#!/usr/bin/env python3
"""Offline reference reader/proofs for C6. Never calls GitHub or admits work.

Claim CS3: only exact, complete combined work covers the stated batch.
The old plan gate checks lane results, but does not bind batch membership,
current attempts, external checks or a candidate's complete work inventory.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / '.github/actions/docs-only'))
import gate

FIXTURES = Path(__file__).resolve().parent / 'fixtures/contract'


def coverage_refusals(raw, context):
    """Offline reference seam for #2314/#2319, never evidence authenticity.

    Context is independently observed, complete and current at the candidate;
    deriving it from this document defeats the contract. No I/O except the
    checked-in schemas is performed here.
    """
    try:
        schema = gate.escapes.strict_json((ROOT / 'contracts/ci-main-batch.v1.schema.json').read_text())
        errors = gate.escapes.lint(schema)
        if errors:
            return errors
        document = gate.escapes.strict_json(raw)
        errors = gate.escapes.errors_of(schema, schema, document, '$')
        errors += gate.escapes.errors_of(schema, schema['$defs']['context'], context, '$context')
        if errors:
            return errors
        batch, execution = document['batch'], document['execution']
        if batch != context['batch'] or execution != context['execution']:
            return ['batch or current execution differs from independently observed context']
        if context['previous_head'] != batch['base']:
            return ['batch overlaps or leaves a gap after the covered checkpoint']
        parent = batch['base']
        for member in batch['members']:
            if member['parent'] != parent or member['merge'] == parent:
                return ['membership is not a contiguous ordered main range']
            parent = member['merge']
        if parent != batch['head'] or batch['base'] == batch['head']:
            return ['membership does not end at the combined head']
        for key in ('pull_request', 'head', 'merge'):
            if len({m[key] for m in batch['members']}) != len(batch['members']):
                return ['ambiguous duplicate member ' + key]
        if any(sha == '0'*40 for sha in [batch['base'], batch['head'],
               *[m[k] for m in batch['members'] for k in ('head', 'merge', 'parent')]]):
            return ['zero commit is not an immutable identity']
        boundaries = {batch['base'], *[m['merge'] for m in batch['members'][:-1]]}
        if execution['event_base'] not in boundaries:
            return ['execution event base is not a batch boundary before the tested head']
        errors = gate.escapes.refusals(document['plan'])
        if errors:
            return errors
        plan = gate.escapes.strict_json(document['plan'])
        run = plan['run']
        if (plan['selection']['mode'] != 'full' or run['base_branch'] != 'main'
                or any(run[k] != execution[k] for k in ('id', 'attempt', 'event'))
                or run['base'] != execution['event_base'] or run['head'] != batch['head']):
            return ['plan is not full work for the exact combined main execution']
        lanes = plan['lanes']
        inventory = [t for lane in [lanes[k] for k in ('always','rust','web','site')]
                     + lanes['skills'] for t in lane['tests']]
        if sorted(inventory) != sorted(context['inventory']):
            return ['full plan omits or adds work against the independent candidate inventory']
        expected = {k: lanes[k]['tests'] for k in ('always','rust','web')}
        for kind in ('site','release'):
            tests = [t for t in lanes['site']['tests'] if t.startswith(kind+':')]
            if tests:
                expected[kind] = tests
        expected.update({'skill:'+s['skill']: s['tests'] for s in lanes['skills']})
        expected.update({'build:web_export': [], 'prerequisite:toolkit': []})
        digest = hashlib.sha256(document['plan'].encode('utf-8')).hexdigest()
        wanted = {k: dict(lane=k, tests=v, plan_sha256=digest, run=run) for k,v in expected.items()}
        receipts = document['receipts']
        if len(receipts) != len(wanted) or {r['lane'] for r in receipts} != set(wanted):
            return ['missing, duplicate or foreign full-work receipt']
        for receipt in receipts:
            actual = dict(receipt, tests=sorted(receipt['tests']))
            if actual != dict(wanted[receipt['lane']], tests=sorted(wanted[receipt['lane']]['tests'])):
                return ['receipt does not bind exact plan, run, attempt and tests']
        outcomes = document['outcomes']
        if (len(outcomes) != len(expected)+1 or {o['name'] for o in outcomes} != {'changes', *expected}
                or any(o['result'] != 'success' for o in outcomes)):
            return ['missing, duplicate, non-success or foreign combined-work result']
        checks = document['checks']
        check_ids = {c['name']: c for c in context['required_checks']}
        if (len(check_ids) != len(context['required_checks']) or 'ci' not in check_ids
                or len(checks) != len(context['required_checks'])
                or {c['name'] for c in checks} != set(check_ids)
                or any(c['result'] != 'success' or c['head'] != batch['head'] for c in checks)):
            return ['missing, duplicate, non-success or foreign required check']
        if any(any(c[k] != check_ids[c['name']][k] for k in ('id', 'attempt')) for c in checks):
            return ['required check does not bind its independently observed current run/attempt']
        ci = next(c for c in checks if c['name'] == 'ci')
        if any(ci[k] != execution[k] for k in ('id', 'attempt')):
            return ['required ci is not the exact current combined execution']
        return []
    except (OSError, ValueError, TypeError, KeyError, RecursionError, gate.escapes.Fail) as error:
        return ['unreadable coverage: ' + str(error)]


class Contract(unittest.TestCase):
    def setUp(self):
        self.record = json.loads((FIXTURES / 'complete.json').read_text())
        self.context = json.loads((FIXTURES / 'expected.json').read_text())

    def refusals(self, document=None, context=None):
        return coverage_refusals(json.dumps(self.record if document is None else document),
                                 self.context if context is None else context)

    def refused(self, document, clue):
        self.assertTrue(self.refusals(document), clue)

    def replan(self, document, change):
        # Keep receipts consistent when planting missed work in the plan;
        # only the independent inventory can expose this bug.
        plan = json.loads(document['plan']); change(plan)
        document['plan'] = json.dumps(plan)
        for receipt in document['receipts']:
            receipt['plan_sha256'] = hashlib.sha256(document['plan'].encode()).hexdigest()
            receipt['run'] = copy.deepcopy(plan['run'])
        return document

    def test_exact_combined_batch_passes_without_granting_switch_authority(self):
        self.assertEqual(self.refusals(), [])

    def test_superseded_pending_push_retains_the_uncovered_checkpoint(self):
        # CS3/R1: checkpoint A, missing A->B result, then full B->C run.
        # The two-member A->C batch must remain coverable without a B receipt.
        record = json.loads((FIXTURES / 'superseded-pending.json').read_text())
        context = json.loads((FIXTURES / 'superseded-pending-expected.json').read_text())
        self.assertEqual(self.refusals(record, context), [])
        shortened = copy.deepcopy(record)
        shortened['batch']['base'] = '2'*40
        shortened['batch']['members'].pop(0)
        context['batch'] = copy.deepcopy(shortened['batch'])
        self.assertIn('batch overlaps or leaves a gap after the covered checkpoint',
                      self.refusals(shortened, context))

    def test_event_base_must_be_an_authenticated_in_range_boundary(self):
        # Keep plan and receipts coherent: a foreign event base must not be
        # accepted just because the observer or plan supplied that same value.
        for base in ('4'*40, '3'*40, 'a'*40, '0'*40):
            with self.subTest(base=base):
                record = self.replan(copy.deepcopy(self.record),
                                     lambda p: p['run'].update(base=base))
                context = copy.deepcopy(self.context)
                record['execution']['event_base'] = base
                context['execution']['event_base'] = base
                self.assertEqual(self.refusals(record, context),
                    ['execution event base is not a batch boundary before the tested head'])

    def test_event_base_cannot_be_inferred_from_plan_or_another_event(self):
        record = json.loads((FIXTURES / 'superseded-pending.json').read_text())
        context = json.loads((FIXTURES / 'superseded-pending-expected.json').read_text())
        forged = copy.deepcopy(record)
        forged['execution']['event_base'] = '1'*40
        self.assertEqual(self.refusals(forged, context),
            ['batch or current execution differs from independently observed context'])
        forged = self.replan(copy.deepcopy(record), lambda p: p['run'].update(base='1'*40))
        self.assertEqual(self.refusals(forged, context),
            ['plan is not full work for the exact combined main execution'])
        for value in (None, True, 2, ''):
            with self.subTest(event_base=value):
                forged = copy.deepcopy(record); forged['execution']['event_base'] = value
                observed = copy.deepcopy(context); observed['execution']['event_base'] = value
                self.assertTrue(self.refusals(forged, observed), 'unknown event association refuses')
        missing = copy.deepcopy(record); del missing['execution']['event_base']
        self.assertTrue(self.refusals(missing, context), 'missing event association refuses')
        missing = copy.deepcopy(context); del missing['execution']['event_base']
        self.assertTrue(self.refusals(record, missing), 'missing independent event association refuses')

    def test_wrong_identity_membership_or_overlap_refuses(self):
        changes = [
            lambda d: d['batch'].update(repository='synthetic/foreign'),
            lambda d: d['batch'].update(head='4'*40),
            lambda d: d['batch'].update(base='4'*40),
            lambda d: d['batch']['members'].pop(),
            lambda d: d['batch']['members'].reverse(),
            lambda d: d['batch']['members'].append(copy.deepcopy(d['batch']['members'][0])),
            lambda d: d['batch']['members'][0].update(head='c'*40),
            lambda d: d['batch']['members'][1].update(parent='1'*40),
        ]
        for number, change in enumerate(changes):
            with self.subTest(case=number):
                d = copy.deepcopy(self.record); change(d)
                self.refused(d, 'foreign or ambiguous batch must refuse')
        context = copy.deepcopy(self.context); context['previous_head'] = '4'*40
        self.assertTrue(self.refusals(context=context), 'overlap with covered checkpoint')

    def test_membership_must_be_contiguous_even_when_context_agrees(self):
        for change in (lambda b: b['members'][1].update(parent=b['base']),
                       lambda b: b['members'][1].update(pull_request=9001),
                       lambda b: b.update(head='4'*40),
                       lambda b: b['members'][0].update(head='0'*40)):
            d = copy.deepcopy(self.record); change(d['batch'])
            context = copy.deepcopy(self.context); context['batch'] = copy.deepcopy(d['batch'])
            self.assertTrue(self.refusals(d, context), 'an internally impossible observed range refuses')

    def test_consistent_new_attempt_and_supported_event_can_pass(self):
        for event, attempt in [('push', 2), ('merge_group', 1)]:
            d = copy.deepcopy(self.record); context = copy.deepcopy(self.context)
            for x in (d, context):
                x['execution'].update(event=event, attempt=attempt)
            def update(plan):
                plan['run'].update(event=event, attempt=attempt)
                plan['store']['artifact'] = 'ci-selection-'+str(attempt)
                plan['selection']['reasons'] = [{'code':'push_main' if event=='push' else 'merge_group'}]
                if attempt > 1: plan['selection']['reasons'].append({'code':'rerun'})
            self.replan(d, update)
            d['checks'][0]['attempt'] = attempt
            context['required_checks'][0]['attempt'] = attempt
            self.assertEqual(self.refusals(d, context), [])

    def test_newest_green_is_not_a_current_attempt_receipt(self):
        for field, value in [('id', 9000102), ('attempt', 2), ('event', 'merge_group')]:
            with self.subTest(field=field):
                d = copy.deepcopy(self.record); d['execution'][field] = value
                self.refused(d, 'another run or attempt must refuse')
                context = copy.deepcopy(self.context); context['execution'][field] = value
                self.assertTrue(self.refusals(context=context), 'older green cannot replace pending current run')
        for field, value in [('head', '4'*40), ('base', '4'*40), ('id', 9000102), ('attempt', 2)]:
            with self.subTest(plan_field=field):
                d = self.replan(copy.deepcopy(self.record), lambda p: p['run'].update({field:value}))
                self.refused(d, 'plan must bind tested batch and current execution')

    def test_each_combined_receipt_and_result_is_mandatory(self):
        for index in range(len(self.record['receipts'])):
            with self.subTest(missing=index):
                d = copy.deepcopy(self.record); d['receipts'].pop(index)
                self.refused(d, 'missing full-work receipt')
        for index in range(len(self.record['outcomes'])):
            for state in ('failure', 'cancelled', 'skipped', 'pending', 'unknown'):
                with self.subTest(index=index, state=state):
                    d = copy.deepcopy(self.record); d['outcomes'][index]['result'] = state
                    self.refused(d, 'non-success combined work')
        for field, value in [('plan_sha256', 'f'*64), ('tests', []), ('run', {})]:
            d = copy.deepcopy(self.record); d['receipts'][0][field] = value
            self.refused(d, 'receipt must bind exact plan/run/tests')
        for key in ('outcomes', 'receipts', 'checks'):
            d = copy.deepcopy(self.record); d[key].append(copy.deepcopy(d[key][0]))
            self.refused(d, 'duplicate result is ambiguous')

    def test_planted_missed_work_cannot_shrink_full_inventory(self):
        for lane in ('always', 'rust', 'web', 'site'):
            with self.subTest(lane=lane):
                d = copy.deepcopy(self.record)
                omitted = json.loads(d['plan'])['lanes'][lane]['tests'][-1]
                self.replan(d, lambda p: p['lanes'][lane]['tests'].remove(omitted))
                for receipt in d['receipts']:
                    if omitted in receipt['tests']: receipt['tests'].remove(omitted)
                self.refused(d, 'a self-consistent but incomplete full plan must refuse')
        d = self.replan(copy.deepcopy(self.record), lambda p: p.update(selection={'mode':'selected'}))
        self.refused(d, 'selected PR greens are never a combined full run')

    def test_safety_privacy_and_required_checks_cannot_be_omitted(self):
        for index in range(len(self.record['checks'])):
            for kind in ('missing', 'failed', 'foreign', 'old-attempt'):
                with self.subTest(index=index, kind=kind):
                    d = copy.deepcopy(self.record)
                    if kind=='missing': d['checks'].pop(index)
                    elif kind=='failed': d['checks'][index]['result']='failure'
                    elif kind=='foreign': d['checks'][index]['head']='4'*40
                    else:
                        # Only ci belongs to the combined CI run; privacy
                        # has its own independently observed attempt.
                        d['checks'][index]['attempt']=0
                    self.refused(d, 'every required check binds its successful head')
        for field in ('id', 'attempt'):
            d = copy.deepcopy(self.record); d['checks'][0][field] += 1
            self.refused(d, 'ci must bind exact current execution')

    def test_separate_required_workflow_cannot_reuse_a_noncurrent_green(self):
        d = copy.deepcopy(self.record)
        privacy = next(c for c in d['checks'] if c['name']=='privacy')
        privacy['attempt'] = 2
        self.refused(d, 'privacy must bind its own independently observed current attempt')
        privacy['attempt'] = 1
        privacy['id'] += 1
        self.refused(d, 'a foreign privacy run cannot stand for the observed one')

    def test_untrusted_shapes_and_claimed_switch_authority_refuse(self):
        for field, value in [('schema','future'), ('switch_authorized', True), ('mode','active')]:
            d = copy.deepcopy(self.record); d[field]=value
            self.refused(d, 'schema is closed; fixtures grant no activation')
        raw = json.dumps(self.record)
        for bad in (raw.replace('"attempt": 1', '"attempt": true', 1),
                    raw[:-1]+', "schema": "openwiz.ci-main-batch.v1"}', 'null', '{'):
            self.assertTrue(coverage_refusals(bad, self.context))


if __name__ == '__main__':
    unittest.main()
