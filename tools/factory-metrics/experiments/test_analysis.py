#!/usr/bin/env python3
"""Independent arithmetic and all-assigned analysis proofs; synthetic only.

The owning claims, plausible regressions and absent prior coverage are listed
in offline/proof-plan.md. Literal expected values are independent calculations.
"""
import copy
from datetime import timedelta
import importlib.util
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent

def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

A=load('analysis',HERE/'analysis.py')
T=load('fixtures',HERE/'test_controls.py')
E,C=T.E,T.C
HORIZON='2030-02-01T00:00:00Z'


def cohort(n=3, *, candidate_defects=False):
    d,j=T.fixture()
    p=d['preregistration']
    p['primary']=dict(statistic='restricted-mean-hours-v1 tau=24',test='bounded-mean-hoeffding-v1',
        unfinished='right-censor-at-horizon; closed-unmerged=tau; all-assigned',
        missing='unknown-effect; censoring-bounds; parity-is-not-random')
    p['guards']['rounds']['test']='welch-independent-rounds-v1'
    p['guards']['defects']['test']='bonferroni-wilson-risk-difference-v1'
    template=copy.deepcopy(j['tickets'][0]);j['tickets']=[];j['pull_requests']=[]
    d['journey']['measurements']=[];d['assignments']=[]
    counter=1000
    def event(kind,at,**rest):
        nonlocal counter
        counter+=1
        source=f's{counter}'
        j['sources'][source]=f'https://github.com/example/factory/pull/4900#issuecomment-{counter}'
        return dict(id=f'e{counter}',kind=kind,at=at,source=source,completeness='complete',**rest)
    for i in range(2*n):
        ticket=4300+i;pr=4400+i;arm='candidate' if ticket%2 else 'old'
        start='2030-01-05T02:00:00Z'
        hours=(4 if arm=='candidate' else 10)+2*((i//2)%3)
        merged=(C.time(start)+timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
        t=copy.deepcopy(template);t.update(ticket=ticket,pull_requests=[pr],events=[
            event('ticket','2030-01-04T00:00:00Z'),event('builder_start','2030-01-05T01:00:00Z')])
        j['tickets'].append(t)
        rounds=[event('verdict','2030-01-05T03:00:00Z',verdict='APPROVE',head='c'*40,
                      independent=True,duplicate_of=None) for _ in range(1+(i//2)%3)]
        j['pull_requests'].append(dict(number=pr,tickets=[ticket],state='merged',
            revisions=dict(base='d'*40,head='c'*40,merge='e'*40),experiment=None,
            events=[event('pr_opened',start),*rounds,event('merge',merged,commit='e'*40)],findings=[]))
        defects=[]
        if candidate_defects and arm=='candidate':
            defects=[dict(key='D1',kind='later-defect-fix',at=merged,attribution='attributable',source='s3')]
        d['journey']['measurements'].append(dict(pr=pr,
            first_push=dict(status='observed',at=start,kind='builder-push-receipt',source='s1',coverage='partial'),
            merge=dict(status='verified',at=merged,commit='e'*40,source='s2',read_at=merged),
            rounds=[e['id'] for e in rounds],helpers=[],
            defects=dict(status='mature',observed_until='2030-01-10T00:00:00Z',events=defects,resolutions=[])))
        d['assignments'].append(dict(ticket=ticket,arm=arm,assigned_at=T.AT,work_started_at=None,
            revision=copy.deepcopy(d['experiment']['arms'][arm]['revision']),
            preregistration_hash=C.preregistration_digest(p)))
    d['journey']['journey_hash']=C.digest(j)
    C.validate(d,j)
    return d,j


class Arithmetic(unittest.TestCase):
    def test_literal_power_and_guard_driven_minimum(self):
        d,_=T.fixture();p=d['preregistration'];before=copy.deepcopy(p)
        plan=A.power_plan(p['power'],p['guards'])
        self.assertEqual(plan['time_n_per_arm'],36)
        self.assertEqual(plan['min_n_per_arm'],72)
        self.assertAlmostEqual(plan['z_alpha'],1.959963984540054)
        self.assertAlmostEqual(plan['z_power'],0.8416212335729143)
        self.assertEqual(p,before)
        for key,value in [('baseline_sd_hours',0),('effect_hours',0),('alpha',True),('power',float('nan'))]:
            bad=copy.deepcopy(p['power']);bad[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError): A.power_plan(bad,p['guards'])

    def test_literal_welch_effect_and_zero_variance_is_unknown(self):
        # Means 2,3; sample variances 1,1; SE=sqrt(2/3); df=4;
        # t(.975,4)=2.7764451051977987; delta=1, 50%.
        effect=A.mean_effect([1,2,3],[2,3,4],.05)
        self.assertEqual([effect[k] for k in ('old','candidate','delta','percent')],[2,3,1,50])
        self.assertAlmostEqual(effect['interval'][0],-1.26695793552752,places=8)
        self.assertAlmostEqual(effect['interval'][1],3.26695793552752,places=8)
        for old,candidate in [([],[]),([1],[2]),([1,1],[1,1])]:
            self.assertIsNone(A.mean_effect(old,candidate,.05)['interval'])

    def test_zero_events_are_not_zero_uncertainty(self):
        # Bonferroni component z(.9875)=2.2414027276049467.
        # Wilson zero-event upper = z^2/(10+z^2), risk-diff is +/-upper.
        effect=A.risk_effect((0,10),(0,10),.05)
        self.assertEqual((effect['delta'],effect['percent']),(0,None))
        self.assertAlmostEqual(effect['interval'][1],.33439325382780844,places=8)
        self.assertAlmostEqual(effect['interval'][0],-.33439325382780844,places=8)
        self.assertIsNone(A.risk_effect((0,0),(0,0),.05)['interval'])
        with self.assertRaises(ValueError): A.risk_effect((2,1),(0,1),.05)

    def test_censoring_bounds_include_unfinished_not_completion_only(self):
        effect,limits=A.bounded_effect([(10,10),(20,24)],[(4,4),(6,24)],24,.05)
        self.assertEqual((effect['old'],effect['candidate'],effect['delta']),(17,14,-3))
        self.assertEqual(limits,dict(old=[15,17],candidate=[5,14],delta=[-12,-1]))
        self.assertEqual(effect['interval'],[-24,24])
        with self.assertRaises(ValueError): A.bounded_effect([(25,25)],[(1,1)],24,.05)


class FixedAnalysis(unittest.TestCase):
    def test_fixed_horizon_fast_harm_and_tiny_zero_event_samples(self):
        for n,harm in [(1,False),(3,False),(72,False),(72,True)]:
            with self.subTest(n=n,harm=harm):
                d,j=cohort(n,candidate_defects=harm)
                with self.assertRaisesRegex(ValueError,'horizon|efficacy'):
                    A.analyze(d,j,at='2030-01-06T00:00:00Z')
                out,detail=A.analyze(d,j,at=HORIZON)
                r=out['result'];C.validate(out,j)
                self.assertEqual(r['verdict'],'harm' if harm else 'inconclusive')
                self.assertEqual(r['samples']['old'],dict(assigned=n,merged=n,open=0,closed_unmerged=0,
                                                        unknown_timing=0,mature_defects=n))
                self.assertEqual(r['effects']['time']['delta'],-6)
                self.assertTrue(detail['limitations'])
                self.assertIsNone(d['result'])

    def test_open_closed_missing_and_immature_stay_in_intent_to_treat(self):
        d,j=cohort(3)
        for i,state in [(0,'open'),(1,'closed')]:
            t=j['tickets'][i];pr=j['pull_requests'][i];m=d['journey']['measurements'][i]
            t['state']=pr['state']=state;pr['revisions']['merge']=None
            pr['events']=[e for e in pr['events'] if e['kind']!='merge']
            m['merge']=dict(status='unmerged',at=None,commit=None,source=None,read_at=None)
            m['defects']=dict(status='unknown',observed_until=None,events=[],resolutions=[])
        m=d['journey']['measurements'][2]
        m['first_push']=dict(status='unknown',at=None,kind=None,source=None,coverage='unknown')
        m=d['journey']['measurements'][3]
        m['defects'].update(status='unmatured',observed_until=m['merge']['at'])
        d['journey']['journey_hash']=C.digest(j)
        out,detail=A.analyze(d,j,at=HORIZON);r=out['result']
        self.assertEqual(r['verdict'],'inconclusive')
        self.assertEqual(r['samples']['old'],dict(assigned=3,merged=2,open=1,closed_unmerged=0,
                                                unknown_timing=1,mature_defects=2))
        self.assertEqual(r['samples']['candidate'],dict(assigned=3,merged=2,open=1,closed_unmerged=0,
                                                unknown_timing=0,mature_defects=1))
        self.assertIsNone(r['effects']['time']['interval'])
        self.assertIsNone(r['effects']['defects']['interval'])
        self.assertEqual(detail['censoring']['candidate']['current_closed_unmerged'],1)

    def test_delayed_current_closure_preserves_horizon_censoring(self):
        d,j=cohort(3)
        pr=j['pull_requests'][0];m=d['journey']['measurements'][0]
        j['tickets'][0]['state']=pr['state']='open'
        pr['revisions']['merge']=None
        pr['events']=[e for e in pr['events'] if e['kind']!='merge']
        m['merge']=dict(status='unmerged',at=None,commit=None,source=None,read_at=None)
        m['first_push']['at']='2030-01-31T23:00:00Z'
        m['defects']=dict(status='unknown',observed_until=None,events=[],resolutions=[])
        d['journey']['journey_hash']=C.digest(j)
        after=copy.deepcopy(d);next_j=copy.deepcopy(j)
        next_j['tickets'][0]['state']=next_j['pull_requests'][0]['state']='closed'
        after['journey']['journey_hash']=C.digest(next_j)
        E.transition(d,after,j,next_j)
        results=[]
        for current,bound_journey,current_closed in [(d,j,0),(after,next_j,1)]:
            with self.subTest(current_closed=current_closed):
                out,detail=A.analyze(current,bound_journey,at='2030-02-03T00:00:00Z')
                results.append(out['result']['effects']['time']['interval'])
                sample=out['result']['samples']['old']
                self.assertEqual((sample['assigned'],sample['merged'],sample['open'],
                                  sample['closed_unmerged'],sample['unknown_timing']),(3,2,1,0,0))
                self.assertAlmostEqual(detail['sensitivity']['old'][0],9)
                self.assertAlmostEqual(detail['sensitivity']['old'][1],50/3)
                self.assertEqual(detail['censoring']['old']['right_censored'],1)
                self.assertEqual(detail['censoring']['old'].get('current_closed_unmerged'),current_closed)
                self.assertEqual(out['result']['verdict'],'inconclusive')
        self.assertEqual(results[0],results[1])

    def test_precise_positive_control_and_material_confounding(self):
        # Keep the frozen .05 defect-width requirement. 4,000 per arm supplies
        # precision; a tiny cohort must not pass by relaxing that requirement.
        d,j=cohort(4000)
        for i,(pr,m) in enumerate(zip(j['pull_requests'],d['journey']['measurements'])):
            if i%2:
                first=m['rounds'][0]
                pr['events']=[e for e in pr['events'] if e['id']!=first]
                m['rounds']=m['rounds'][1:]
            elif i%4==0:
                m['defects']['events']=[dict(key='D1',kind='later-defect-fix',
                    at=m['merge']['at'],attribution='attributable',source='s3')]
        d['journey']['journey_hash']=C.digest(j)
        out,_=A.analyze(d,j,at=HORIZON)
        self.assertEqual(out['result']['verdict'],'improved')
        for guard in ('rounds','defects'):
            interval=out['result']['effects'][guard]['interval']
            self.assertLess(interval[1],0)
            self.assertLessEqual(interval[1]-interval[0],d['preregistration']['guards'][guard]['max_interval_width'])
        d['deviations'].append(dict(ticket=4300,kind='overlap',material=True,source='s1',actual_revision=None))
        out,_=A.analyze(d,j,at=HORIZON)
        self.assertEqual(out['result']['verdict'],'inconclusive')

    def test_stop_retains_harm_even_before_fixed_analysis(self):
        d,j=cohort(3,candidate_defects=True)
        d['journey']['measurements'][1]['defects']['events'][0]['kind']='main-red'
        out,_=A.analyze(d,j,at='2030-01-07T00:00:00Z')
        self.assertEqual((out['result']['status'],out['result']['verdict']),('stopped','harm'))

    def test_expiring_low_round_pr_cannot_hide_harm_on_later_event(self):
        d,j=cohort(2);p=d['preregistration']
        p['stopping'].update(window_hours=24,minimum_exposed=1)
        for a in d['assignments']: a['preregistration_hash']=C.preregistration_digest(p)
        pr=j['pull_requests'][3];m=d['journey']['measurements'][3]
        reviews=[e for e in pr['events'] if C.J.rounds_of(e)]
        for e in reviews: e['at']='2030-01-06T02:00:00Z'
        extra=copy.deepcopy(reviews[-1]);extra.update(id='e99999',source='s99999')
        j['sources']['s99999']='https://github.com/example/factory/pull/4403#issuecomment-99999'
        pr['events'].append(extra);m['rounds'].append('e99999')
        for e in pr['events']:
            if e['kind']=='merge': e['at']='2030-01-06T04:00:00Z'
        m['merge'].update(at='2030-01-06T04:00:00Z',read_at='2030-01-06T04:00:00Z')
        d['journey']['journey_hash']=C.digest(j)
        self.assertEqual(E.rounds_window(d,j,'candidate',at='2030-01-06T02:00:00Z'),(2,2))
        self.assertEqual(E.rounds_window(d,j,'candidate',at='2030-01-06T04:00:00Z'),(1,3))
        out=E.advance(d,j,copy.deepcopy(d),j,at='2030-01-08T00:00:00Z')
        self.assertIsNotNone(out['result'])
        self.assertEqual([(s['kind'],s['arm'],s['at'],s['observed']) for s in out['result']['stops']],
                         [('doubled-rounds','candidate','2030-01-06T03:00:00Z',3)])

    def test_post_horizon_merge_keeps_known_right_censoring(self):
        d,j=cohort(3);pr=j['pull_requests'][0];m=d['journey']['measurements'][0]
        for e in pr['events']:
            if e['kind']=='merge': e['at']='2030-02-02T00:00:00Z'
        m['merge'].update(at='2030-02-02T00:00:00Z',read_at='2030-02-02T00:00:00Z')
        m['defects']['observed_until']='2030-02-05T00:00:00Z'
        d['journey']['journey_hash']=C.digest(j)
        out,detail=A.analyze(d,j,at='2030-02-05T00:00:00Z')
        self.assertEqual(out['result']['samples']['old']['unknown_timing'],0)
        self.assertEqual(out['result']['samples']['old']['open'],1)
        self.assertEqual(detail['censoring']['old']['right_censored'],1)
        self.assertIsNotNone(out['result']['effects']['time']['interval'])
        self.assertEqual(out['result']['verdict'],'inconclusive')

    def test_unsupported_frozen_method_refuses(self):
        d,j=cohort()
        d['preregistration']['primary']['test']='another-method'
        for a in d['assignments']: a['preregistration_hash']=C.preregistration_digest(d['preregistration'])
        with self.assertRaisesRegex(ValueError,'unsupported'):
            A.analyze(d,j,at=HORIZON)


if __name__=='__main__': unittest.main()
