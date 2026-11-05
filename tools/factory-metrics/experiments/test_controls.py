#!/usr/bin/env python3
"""Synthetic public-seam proofs. Claims and missed bugs: offline/proof-plan.md."""
import copy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('controls', HERE / 'controls.py')
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
C = E.C
SAFE = dict(holds_clear=True, independent_review_required=True,
            required_ci=True, verified_merge_required=True)
AT = '2030-01-05T00:00:00Z'


def read(path):
    return json.loads(path.read_text())


def fixture():
    """Reuse EB5's literal shapes, shifting outcomes after the planned assignment."""
    j = read(HERE.parent / 'fixtures/journey/journeys.json')
    d = read(HERE.parent / 'fixtures/bottlenecks-contract/accepted.json')
    for t in j['tickets']:
        for e in t['events']:
            if e['kind'] == 'builder_start':
                e['at'] = '2030-01-05T01:00:00Z'
    for p in j['pull_requests']:
        for e in p['events']:
            if e['at']:
                e['at'] = (C.time(e['at']) + timedelta(days=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
    for m in d['journey']['measurements']:
        for row in (m['first_push'], m['merge'], m['defects']):
            for k in ('at', 'read_at', 'observed_until'):
                if row.get(k): row[k] = (C.time(row[k])+timedelta(days=4)).strftime('%Y-%m-%dT%H:%M:%SZ')
        for e in m['defects']['events']:
            e['at'] = '2030-01-07T05:00:00Z'
    d['journey']['journey_hash'] = C.digest(j)
    d['replay'] = read(HERE.parents[1] / 'skills-eval/replay/contract-fixtures/paired.json')
    for stage, at in [('research','2030-01-03T09:00:00Z'),
                      ('cf4','2030-01-03T13:00:00Z'),('replay','2030-01-04T00:30:00Z')]:
        d['stages'][stage] = dict(status='pass', artifact_hash='f'*64, source='s1', at=at)
    p = read(HERE.parent / 'fixtures/bottlenecks-contract/preregistration.json')
    p['replay_hash'] = C.digest(d['replay'])
    p['live_approval'] = dict(status='granted', at='2030-01-04T03:00:00Z', source='s5')
    d['preregistration'] = p
    C.validate(d, j)
    return d, j


class Assignment(unittest.TestCase):
    def test_prework_parity_idempotence_and_frozen_revision(self):
        d, j = fixture()
        before = copy.deepcopy(d)
        for ticket, arm, rev in [(4101, 'candidate', 'b'), (4102, 'old', 'a')]:
            d = E.assign(d, j, ticket, at=AT, eligible=True, safeguards=SAFE)
            a = d['assignments'][-1]
            self.assertEqual((a['ticket'], a['arm'], a['assigned_at'], a['work_started_at']),
                             (ticket, arm, AT, None))
            self.assertEqual(a['revision'], dict(commit=rev*40, tree=rev*40))
        self.assertEqual(before['assignments'], [])
        self.assertEqual(E.assign(d, j, 4101, at=AT, eligible=True, safeguards=SAFE), d)
        C.validate_transition(before, d, j)
        with self.assertRaisesRegex(ValueError, 'immutable|reassign'):
            E.assign(d, j, 4101, at='2030-01-05T00:30:00Z', eligible=True, safeguards=SAFE)

    def test_known_first_push_also_prevents_late_assignment(self):
        d,j=fixture()
        j['tickets'][0]['events']=[e for e in j['tickets'][0]['events'] if e['kind']!='builder_start']
        d['journey']['journey_hash']=C.digest(j)
        d['journey']['measurements'][0]['first_push']['at']='2030-01-04T12:00:00Z'
        with self.assertRaisesRegex(ValueError,'work|push'):
            E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE)

    def test_completed_live_stage_blocks_assignment_even_without_result(self):
        for status in ('not_run','partial','pass','fail','stopped','inconclusive'):
            d,j=fixture()
            if status!='not_run':
                d['stages']['live']=dict(status=status,artifact_hash='f'*64,
                                        source='s1',at='2030-01-04T04:00:00Z')
            C.validate(d,j)
            if status in ('not_run','partial'):
                E.launch_check(d,j,at=AT,safeguards=SAFE)
                after=E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE)
                E.transition(d,after,j,j)
                self.assertEqual(len(after['assignments']),1)
                continue
            baseline,bj=fixture()
            after=E.assign(baseline,bj,4101,at=AT,eligible=True,safeguards=SAFE)
            after['stages']['live']=copy.deepcopy(d['stages']['live'])
            for api,check in [
                ('launch',lambda:E.launch_check(d,j,at=AT,safeguards=SAFE)),
                ('assign',lambda:E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE)),
                ('transition',lambda:E.transition(d,after,j,j))]:
                with self.subTest(status=status,api=api), self.assertRaisesRegex(ValueError,'terminal|live stage'):
                    check()

    def test_missing_predecessors_approval_eligibility_and_policy_refuse(self):
        for change in [lambda d: d.update(preregistration=None),
                       lambda d: d.update(replay=None),
                       lambda d: d['cf4_runs']['old'].clear(),
                       lambda d: d['preregistration']['live_approval'].update(status='not_granted',at=None,source=None),
                       lambda d: d['stages']['research'].update(status='fail')]:
            with self.subTest(change=change):
                d,j = fixture(); change(d)
                with self.assertRaises(ValueError):
                    E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE)
        for key in SAFE:
            d,j = fixture(); bad = dict(SAFE, **{key:False})
            with self.subTest(key=key), self.assertRaises(ValueError):
                E.assign(d,j,4101,at=AT,eligible=True,safeguards=bad)
        d,j=fixture()
        for eligible,at in [(False,AT),(True,'2030-01-05T02:00:00Z')]:
            with self.subTest(eligible=eligible,at=at), self.assertRaises(ValueError):
                E.assign(d,j,4101,at=at,eligible=eligible,safeguards=SAFE)



class Events(unittest.TestCase):
    def assigned(self):
        d,j = fixture()
        return E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE),j

    def test_round_window_boundary_exposure_helpers_and_resume(self):
        d,j=self.assigned()
        # Literal fixture: candidate PR has exactly 3 independent verdicts;
        # a fourth verdict is a duplicate, and a fifth is a helper.
        d['preregistration']['stopping']['minimum_exposed']=1
        d['assignments'][0]['preregistration_hash']=C.preregistration_digest(d['preregistration'])
        times=[e['at'] for e in j['pull_requests'][0]['events'] if C.J.rounds_of(e)]
        at=max(times)
        before=copy.deepcopy(d)
        d=E.advance(d,j,copy.deepcopy(d),j,at=at)
        self.assertEqual(d['result']['verdict'],'harm')
        self.assertEqual(d['result']['stops'],[dict(kind='doubled-rounds', arm='candidate',
            at=at, source=d['result']['stops'][0]['source'], exposed=1, observed=3)])
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'checkpoint.json'
            E.save_checkpoint(path,d,j)
            restored,rj=E.load_checkpoint(path)
            self.assertEqual(restored,d)
            repeated=E.advance(restored,rj,copy.deepcopy(restored),j,at=at)
            self.assertEqual(repeated,d)
            with self.assertRaisesRegex(ValueError,'terminal|resumption'):
                E.assign(restored,j,4102,at=at,eligible=True,safeguards=SAFE)
            with self.assertRaisesRegex(ValueError,'changed|exists|expected'):
                E.save_checkpoint(path,before,j)
        # The left edge is excluded, right edge included. Exactly one full
        # window after the last verdict, the window contains no rounds.
        edge=(C.time(at)+timedelta(hours=168)).strftime('%Y-%m-%dT%H:%M:%SZ')
        self.assertEqual(E.rounds_window(before,j,'candidate',at=edge),(0,None))
        self.assertEqual(E.advance(before,j,copy.deepcopy(before),j,at=edge)['result']['stops'][0]['at'],at)
        for reference,minimum in [(1.5001,1),(1.5,2)]:
            d,j=self.assigned();p=d['preregistration'];p['stopping'].update(
                rounds_reference=reference,minimum_exposed=minimum)
            d['assignments'][0]['preregistration_hash']=C.preregistration_digest(p)
            self.assertIsNone(E.advance(d,j,copy.deepcopy(d),j,at=at)['result'])

    def test_repeated_source_observation_cannot_inflate_rounds(self):
        d,j=self.assigned()
        pr=j['pull_requests'][0]
        first=next(e for e in pr['events'] if C.J.rounds_of(e) and e['verdict']=='APPROVE')
        repeated=copy.deepcopy(first);repeated['id']='e9999'
        pr['events'].append(repeated)
        d['journey']['measurements'][0]['rounds'].append('e9999')
        d['journey']['journey_hash']=C.digest(j)
        C.validate(d,j)
        at=max(e['at'] for e in pr['events'] if C.J.rounds_of(e))
        self.assertEqual(E.rounds_window(d,j,'candidate',at=at),(1,3))

    def test_cross_pr_source_reuse_refuses_in_both_pr_orders(self):
        for reverse in (False,True):
            for conflict in (False,True):
                d,j=fixture()
                d['preregistration']['stopping']['minimum_exposed']=1
                j['tickets'][0]['pull_requests'].append(4202)
                j['pull_requests'][1]['tickets'].append(4101)
                d['journey']['journey_hash']=C.digest(j)
                d=E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE)
                at=max(e['at'] for pr in j['pull_requests'] for e in E.independent_rounds(pr,j))
                self.assertEqual(E.rounds_window(d,j,'candidate',at=at),(1,3))
                self.assertEqual(E.advance(d,j,copy.deepcopy(d),j,at=at)['result']['verdict'],'harm')
                after=copy.deepcopy(d);next_j=copy.deepcopy(j)
                event=copy.deepcopy(next(e for e in next_j['pull_requests'][0]['events']
                                         if C.J.rounds_of(e) and e['verdict']=='APPROVE'))
                event.update(id='e9999',source='s9999')
                next_j['sources']['s9999']=j['sources'][next(e for e in j['pull_requests'][0]['events']
                    if C.J.rounds_of(e) and e['verdict']=='APPROVE')['source']]
                if conflict: event['head']='f'*40
                next_j['pull_requests'][1]['events'].append(event)
                after['journey']['measurements'][1]['rounds'].append(event['id'])
                if reverse:
                    next_j['pull_requests'].reverse()
                    after['journey']['measurements'].reverse()
                after['journey']['journey_hash']=C.digest(next_j)
                C.validate(after,next_j)
                for api,check in [
                    ('transition',lambda:E.transition(d,after,j,next_j)),
                    ('window',lambda:E.rounds_window(after,next_j,'candidate',at=at)),
                    ('advance',lambda:E.advance(d,j,after,next_j,at=at)),
                    ('launch',lambda:E.launch_check(after,next_j,at=at,safeguards=SAFE)),
                    ('assign',lambda:E.assign(after,next_j,4102,at=AT,eligible=True,safeguards=SAFE))]:
                    with self.subTest(reverse=reverse,conflict=conflict,api=api), self.assertRaisesRegex(ValueError,'source'):
                        check()

    def test_multiple_prs_do_not_inflate_exposed_ticket_count(self):
        d,j=self.assigned()
        j['tickets'][0]['pull_requests'].append(4202)
        j['pull_requests'][1]['tickets'].append(4101)
        event=copy.deepcopy(next(e for e in j['pull_requests'][0]['events']
                                 if C.J.rounds_of(e) and e['verdict']=='APPROVE'))
        event.update(id='e9998',source='s9998')
        j['sources']['s9998']='https://github.com/example/factory/pull/4202#issuecomment-9998'
        j['pull_requests'][1]['events'].append(event)
        d['journey']['measurements'][1]['rounds'].append('e9998')
        d['journey']['journey_hash']=C.digest(j)
        C.validate(d,j)
        self.assertEqual(E.rounds_window(d,j,'candidate',at=event['at']),(1,2))

    def test_attributed_main_red_and_delayed_resolution_are_separate_stop(self):
        for attribution,resolved,stop in [('unattributed',False,False),('unknown',False,False),
                                          ('attributable',False,True),('unknown',True,True)]:
            with self.subTest(attribution=attribution,resolved=resolved):
                d,j=self.assigned();m=d['journey']['measurements'][0]
                m['defects']['events'][0].update(kind='main-red',attribution=attribution)
                if resolved:
                    m['defects']['resolutions']=[dict(key='D1',at='2030-01-08T00:00:00Z',
                        attribution='attributable',source='s4')]
                at='2030-01-08T00:00:00Z'
                out=E.advance(d,j,copy.deepcopy(d),j,at=at)
                if stop:
                    self.assertEqual([(s['kind'],s['observed']) for s in out['result']['stops']],
                                     [('main-red',1)])
                    self.assertEqual(out['result']['stops'][0]['at'],
                                     at if resolved else '2030-01-07T05:00:00Z')
                else: self.assertIsNone(out['result'])

    def test_retained_revisions_deviations_and_old_starts(self):
        d,j=self.assigned();after=copy.deepcopy(d)
        after['deviations'].append(dict(ticket=4101,kind='revision-change',material=True,
            source='s1',actual_revision=dict(commit='c'*40,tree='c'*40)))
        after['deviations'].append(dict(ticket=4101,kind='overlap',material=True,
            source='s2',actual_revision=None))
        out=E.advance(d,j,after,j,at='2030-01-07T00:00:00Z')
        self.assertEqual(out['assignments'][0]['revision'],dict(commit='b'*40,tree='b'*40))
        self.assertEqual(out['assignments'][0]['work_started_at'],'2030-01-05T01:00:00Z')
        self.assertEqual(out['deviations'],after['deviations'])
        bad=copy.deepcopy(out);bad['deviations'].pop()
        with self.assertRaisesRegex(ValueError,'immutable'):
            E.advance(out,j,bad,j,at='2030-01-07T01:00:00Z')
        bad=copy.deepcopy(out);bad['assignments'][0]['revision']['commit']='d'*40
        with self.assertRaises(ValueError): E.advance(out,j,bad,j,at='2030-01-07T01:00:00Z')

    def test_established_outcome_cannot_move_to_the_other_arm(self):
        d,j=self.assigned()
        d=E.assign(d,j,4102,at=AT,eligible=True,safeguards=SAFE)
        after=copy.deepcopy(d);next_j=copy.deepcopy(j)
        next_j['tickets'][0]['pull_requests']=[]
        next_j['tickets'][1]['pull_requests']=[4201]
        next_j['pull_requests'][0]['tickets']=[4102]
        after['journey']['journey_hash']=C.digest(next_j)
        with self.assertRaisesRegex(ValueError,'exposure|association'):
            E.advance(d,j,after,next_j,at='2030-01-08T00:00:00Z')

    def test_new_early_push_is_retained_with_material_protocol_deviation(self):
        d,j=fixture()
        push=copy.deepcopy(d['journey']['measurements'][0]['first_push'])
        d['journey']['measurements'][0]['first_push']=dict(status='unknown',at=None,
            kind=None,source=None,coverage='unknown')
        d=E.assign(d,j,4101,at=AT,eligible=True,safeguards=SAFE)
        after=copy.deepcopy(d);push['at']='2030-01-04T12:00:00Z'
        after['journey']['measurements'][0]['first_push']=push
        out=E.advance(d,j,after,j,at='2030-01-08T00:00:00Z')
        self.assertEqual(out['deviations'],[dict(ticket=4101,kind='other',material=True,
                                              source='s1',actual_revision=None)])
        self.assertEqual(out['assignments'][0]['assigned_at'],AT)
        self.assertEqual(out['journey']['measurements'][0]['first_push'],push)
        again=E.advance(out,j,copy.deepcopy(out),j,at='2030-01-08T01:00:00Z')
        self.assertEqual(again['deviations'],out['deviations'])

    def test_precheck_is_bound_and_never_independent_approval(self):
        d,j=self.assigned()
        record=read(HERE.parents[1]/'skills-eval/precheck/contract-fixtures/complete.json')
        request=record['request'];request['change']='skill'
        request['experiment']=dict(tag=d['experiment']['tag'],experiment_hash=d['experiment_hash'],
                                   arm='candidate',cf4_refs=d['preregistration']['cf4_refs'])
        record['result']['request_hash']=C.digest(request)
        self.assertEqual(E.handback_check(d,j,record,request,at='2030-01-05T00:30:00Z',
                                         safeguards=SAFE),'ready')
        bad=copy.deepcopy(record);bad['result']=None
        self.assertEqual(E.handback_check(d,j,bad,request,at=AT,safeguards=SAFE),'blocked-missing')
        bad=copy.deepcopy(request);bad['binding']['head']='f'*40
        self.assertEqual(E.handback_check(d,j,record,bad,at=AT,safeguards=SAFE),'blocked-stale')
        bad=copy.deepcopy(record);bad['request']['experiment']['arm']='old'
        with self.assertRaises(ValueError):
            E.handback_check(d,j,bad,bad['request'],at=AT,safeguards=SAFE)
        bad=copy.deepcopy(record);bad['result']['independent']=True
        with self.assertRaises(ValueError): E.handback_check(d,j,bad,request,at=AT,safeguards=SAFE)
        self.assertEqual(d['journey']['measurements'][0]['rounds'],['e13','e17','e22'])


if __name__ == '__main__':
    unittest.main()
