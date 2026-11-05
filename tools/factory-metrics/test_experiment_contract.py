#!/usr/bin/env python3
"""EB5 public Python/CLI contract proofs; all values and provenance synthetic.

Owning claims and plausible bugs are in the EB5 proof plan. Fixtures are literal
worked examples, not output from the implementation. Existing v1 journey and
CF4 proofs cannot detect the new timing, assignment, replay and live contracts.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIX = HERE / 'fixtures/bottlenecks-contract'
REPLAY = HERE.parent / 'skills-eval/replay/contract-fixtures'
spec = importlib.util.spec_from_file_location('experiment_contract', HERE / 'experiment_contract.py')
C = importlib.util.module_from_spec(spec)
spec.loader.exec_module(C)


def read(path):
    return json.loads(path.read_text())


class Contract(unittest.TestCase):
    def setUp(self):
        self.journey = read(HERE / 'fixtures/journey/journeys.json')
        self.doc = read(FIX / 'accepted.json')

    def check(self, doc=None):
        C.validate(self.doc if doc is None else doc, self.journey)

    def refuse(self, message):
        with self.assertRaisesRegex(ValueError, message):
            self.check()

    def replay(self, name='paired.json'):
        self.doc['replay'] = read(REPLAY / name)
        self.doc['preregistration']=None
        self.doc['stages']['research']={'status':'pass','artifact_hash':'f'*64,'source':'s1','at':'2030-01-03T09:00:00Z'}

    def assigned(self):
        self.replay()
        for ticket in self.journey['tickets']:
            if ticket['ticket']==4102:
                for event in ticket['events']:
                    if event['kind']=='builder_start': event['at']='2030-01-06T00:00:00Z'
        self.doc['journey']['journey_hash']=C.digest(self.journey)
        p = read(FIX/'preregistration.json')
        self.doc['preregistration']=p
        p['replay_hash']=C.digest(self.doc['replay'])
        p['registered_at'] = '2030-01-04T01:00:00Z'
        p['method_review']['at'] = '2030-01-04T02:00:00Z'
        p['live_approval'] = {'status':'granted', 'at':'2030-01-04T03:00:00Z', 'source':'s5'}
        self.doc['assignments'] = [{'ticket':4102, 'arm':'old', 'assigned_at':'2030-01-05T00:00:00Z',
            'work_started_at':None, 'revision':{'commit':'a'*40, 'tree':'a'*40},
            'preregistration_hash':C.preregistration_digest(p)}]
        for stage,at in [('research','2030-01-03T09:00:00Z'),('cf4','2030-01-03T13:00:00Z'),('replay','2030-01-04T00:30:00Z')]:
            self.doc['stages'][stage] = {'status':'pass', 'artifact_hash':'f'*64, 'source':'s1', 'at':at}

    def test_literal_conforming_and_historical_compatibility(self):
        self.check()
        self.check(read(FIX / 'unrun.json'))
        C.validate_journey(self.journey)
        extension = C.migrate_journey(self.journey)
        self.assertEqual(extension['schema'], 'closedwiz.journey.outcomes.v1')
        self.assertEqual([m['pr'] for m in extension['measurements']], [4201, 4202])
        for measurement in extension['measurements']:
            self.assertEqual(measurement['first_push']['status'], 'unknown')
            self.assertIsNone(measurement['first_push']['at'])
            self.assertEqual(measurement['defects']['status'], 'unknown')
        self.assertEqual(extension['measurements'][0]['rounds'], ['e13','e17','e22'])
        self.doc['journey'] = extension
        self.check()

    def test_timing_round_and_defect_refusals(self):
        for path, value, reason in [
            (('first_push','kind'), 'pr-created', 'push'),
            (('first_push','at'), None, 'time'),
            (('first_push','coverage'), 'complete-history', 'coverage'),
            (('rounds',), ['e13','e17','e19','e22'], 'round'),
            (('rounds',), ['e13','e17','e18','e22'], 'round'),
            (('helpers',), ['e13'], 'helper'),
            (('defects','status'), 'mature', 'matur'),
            (('merge','commit'), 'f'*40, 'merge'),
        ]:
            with self.subTest(path=path,value=value):
                self.setUp(); m=self.doc['journey']['measurements'][0]; target=m
                for k in path[:-1]: target=target[k]
                target[path[-1]]=value; self.refuse(reason)
        self.setUp();self.doc['journey']['measurements'][1]['first_push']['at']='2030-01-01T00:00:00Z'
        self.refuse('unknown')
        self.setUp();self.doc['journey']['measurements'].pop();self.refuse('coverage')
        self.setUp();self.doc['journey']['journey_hash']='0'*64;self.refuse('journey')

    def test_strict_revision_cf4_and_units(self):
        for change, reason in [
            (lambda d:d.update(extra=True),'fields'),
            (lambda d:d['experiment'].update(repo=[]),'repo'),
            (lambda d:d['experiment']['arms']['candidate']['revision'].update(commit='moving-main'),'commit'),
            (lambda d:d['experiment']['arms']['candidate']['cf4'].update(cases_hash='f'*64),'compatible'),
            (lambda d:d['cf4_runs']['candidate'][0].update(passed=59),'CF4'),
            (lambda d:d['experiment']['arms']['candidate']['cf4'].update(repeats=True),'integer'),
            (lambda d:d['usage'][0].update(unit='dollars'),'unit'),
            (lambda d:d['usage'][1].update(value=0),'unknown'),
            (lambda d:d['usage'][2].update(scope='old'),'shared'),
            (lambda d:d['usage'][0].update(value=float('nan')),'finite'),
        ]:
            with self.subTest(reason=reason):
                self.setUp(); change(self.doc)
                # A new digest is not authority to change the frozen record, but
                # isolates inner shape checks from the envelope checksum check.
                self.doc['experiment_hash']=C.digest(self.doc['experiment']) if reason!='finite' else self.doc['experiment_hash']
                self.refuse(reason)

    def test_replay_pairs_and_blinding(self):
        self.replay();self.check()
        self.replay('partial.json');self.check()
        for change, reason in [
            (lambda r:r['cohort'][0]['context']['materials'][0].update(kind='answer-key'),'material'),
            (lambda r:r['cohort'][0]['context']['materials'][0].update(at='2030-01-05T00:00:00Z'),'later'),
            (lambda r:r['cohort'][0]['arms']['candidate'].update(context_hash='f'*64),'context'),
            (lambda r:r['cohort'][0]['arms']['candidate'].update(context_key='old-fresh-1'),'fresh'),
            (lambda r:r['cohort'][0]['arms']['old']['adjudications'][0]['findings'].append({'id':'F1','severity':'high','outcome':'catch'}),'duplicate'),
            (lambda r:r['cohort'][0]['arms']['old']['adjudications'][0]['findings'][0].update(outcome='false_positive'),'known'),
            (lambda r:r['cohort'][0]['arms']['old']['adjudications'][0]['findings'][0].update(severity='low'),'severity'),
            (lambda r:r['cohort'][0]['arms']['old']['adjudications'][0]['findings'].pop(1),'missing'),
            (lambda r:r['cohort'][0]['arms']['candidate'].update(status='error'),'result'),
            (lambda r:r['cohort'][0].update(head=None),'commit'),
            (lambda r:r['rubric'].update(adjudication='arm-aware'),'rubric'),
            (lambda r:r['avoided_rounds'].update(evidence_class='observed'),'estimate'),
        ]:
            with self.subTest(reason=reason):
                self.setUp();self.replay();change(self.doc['replay']);self.refuse(reason)
        self.setUp();self.replay('partial.json');self.doc['replay']['selection']='candidate';self.refuse('partial')

    def test_preregistration_and_admission_contract(self):
        self.assigned();self.check()
        for change,reason in [
            (lambda d:d['preregistration']['primary'].update(test=''),'nonempty'),
            (lambda d:d['preregistration']['power'].update(time_n_per_arm=15),'power'),
            (lambda d:d['preregistration']['power'].update(min_n_per_arm=36),'guard'),
            (lambda d:d['preregistration']['power'].update(z_alpha=1),'critical'),
            (lambda d:d['preregistration']['stopping'].update(efficacy_peeking=True),'peeking'),
            (lambda d:d['preregistration'].update(method_review=None),'review'),
            (lambda d:d['assignments'][0].update(arm='candidate'),'parity'),
            (lambda d:d['assignments'][0].update(work_started_at='2030-01-03T00:00:00Z'),'before'),
            (lambda d:d['assignments'][0].update(preregistration_hash='0'*64),'preregistration'),
            (lambda d:d['stages']['research'].update(status='not_run',artifact_hash=None,source=None,at=None),'predecessor'),
            (lambda d:d['preregistration']['live_approval'].update(status='not_granted',at=None,source=None),'approval'),
        ]:
            with self.subTest(reason=reason):
                self.setUp();self.assigned();change(self.doc);self.refuse(reason)

    def test_immutable_checkpoint(self):
        self.assigned();before=copy.deepcopy(self.doc)
        self.doc['deviations']=[{'ticket':4102,'kind':'overlap','material':True,'source':'s1','actual_revision':None}]
        C.validate_transition(before,self.doc,self.journey)
        self.doc['assignments'][0]['assigned_at']='2030-01-05T01:00:00Z'
        with self.assertRaisesRegex(ValueError,'immutable'):
            C.validate_transition(before,self.doc,self.journey)

    def test_unavailable_operations_are_explicit(self):
        for operation in ('collect','research','paid_eval','run_replay','launch_live','activate','publish'):
            with self.subTest(operation=operation), self.assertRaisesRegex(C.UnavailableOperation,'unavailable'):
                C.execute(operation,self.doc)

    def result(self):
        self.assigned()
        self.doc['result']=read(FIX/'unfinished-result.json')
        self.doc['result']['preregistration_hash']=C.preregistration_digest(self.doc['preregistration'])

    def test_unfinished_results_and_both_stops(self):
        self.result();self.check()
        self.doc['result'].update(status='complete',verdict='improved');self.refuse('underpowered')
        self.result();self.doc['result']['samples']['old']['assigned']=0;self.refuse('denominator')
        self.result();self.doc['result']['effects']['time']={'unit':'hours','old':18,'candidate':12,
            'delta':-6,'percent':-33.333333333333336,'interval':[-8,-4]}
        self.check()  # A promising time estimate with missing guards stays inconclusive.
        self.doc['result']['effects']['time']['percent']=-50;self.refuse('percentage')
        self.result();self.doc['result']['at']='2030-01-10T00:00:00Z';self.refuse('horizon')
        self.result();r=self.doc['result'];r.update(status='stopped',verdict='harm',at='2030-01-10T00:00:00Z')
        r['stops']=[{'kind':'main-red','arm':'old','at':'2030-01-09T00:00:00Z','source':'s3','exposed':1,'observed':1}]
        self.check()
        r['verdict']='improved';self.refuse('harm')
        # A second synthetic eligible ticket supplies the exact doubled-round boundary.
        self.result();t=copy.deepcopy(self.journey['tickets'][1]);t.update(ticket=4104,events=[])
        t['gaps']=['no ready label','no builder start record','no pull request','no merge']
        self.journey['tickets'].append(t);self.doc['journey']['journey_hash']=C.digest(self.journey)
        a=copy.deepcopy(self.doc['assignments'][0]);a['ticket']=4104;self.doc['assignments'].append(a)
        r=self.doc['result'];r['samples']['old'].update(assigned=2,open=2,unknown_timing=2)
        r.update(status='stopped',verdict='harm',at='2030-01-10T00:00:00Z')
        r['stops']=[{'kind':'doubled-rounds','arm':'old','at':'2030-01-09T00:00:00Z','source':'s3','exposed':2,'observed':3}]
        self.check()
        r['stops'][0]['observed']=2.99;self.refuse('boundary')

    def test_usage_coverage_and_immutable_evidence(self):
        self.doc['usage']=[u for u in self.doc['usage'] if not (u['scope']=='total' and u['unit']=='credits')]
        self.refuse('coverage')
        self.setUp();before=copy.deepcopy(self.doc)
        self.doc['sources']['s1']='https://github.com/example/factory/issues/4901'
        with self.assertRaisesRegex(ValueError,'immutable'):
            C.validate_transition(before,self.doc,self.journey)

    def test_live_approval_does_not_mutate_frozen_protocol(self):
        self.assigned();before=copy.deepcopy(self.doc);before['assignments']=[]
        before['preregistration']['live_approval']={'status':'not_granted','at':None,'source':None}
        C.validate_transition(before,self.doc,self.journey)
        changed=copy.deepcopy(self.doc);changed['preregistration']['eligibility']='Changed after assignment'
        changed['assignments'][0]['preregistration_hash']=C.preregistration_digest(changed['preregistration'])
        with self.assertRaisesRegex(ValueError,'immutable'):
            C.validate_transition(self.doc,changed,self.journey)

    def test_complete_result_decision_bounds(self):
        # Public result seam: summaries with literal independent arithmetic.
        # A validator that always refuses improvement or accepts wide guards is
        # wrong; tiny/unfinished fixtures alone miss both failures.
        self.assigned();p=self.doc['preregistration'];p['guards']['defects']['max_interval_width']=0.2
        self.doc['assignments']=[{'arm':arm} for arm in ('old','candidate') for _ in range(72)]
        result=read(FIX/'unfinished-result.json');result['preregistration_hash']=C.preregistration_digest(p)
        result.update(status='complete',verdict='improved')
        result['samples']={a:{'assigned':72,'merged':72,'open':0,'closed_unmerged':0,'unknown_timing':0,'mature_defects':72} for a in ('old','candidate')}
        result['effects']={
            'time':{'unit':'hours','old':18,'candidate':12,'delta':-6,'percent':-33.333333333333336,'interval':[-8,-4]},
            'rounds':{'unit':'rounds','old':2,'candidate':1,'delta':-1,'percent':-50,'interval':[-1.1,-0.9]},
            'defects':{'unit':'proportion','old':0.1,'candidate':0,'delta':-0.1,'percent':-100,'interval':[-0.18,-0.02]}}
        C.validate_result(result,self.doc)
        result['status']='inconclusive'
        with self.assertRaisesRegex(ValueError,'status'):
            C.validate_result(result,self.doc)
        result['status']='complete'
        result['effects']['defects']['interval']=[-0.3,0.01]
        with self.assertRaisesRegex(ValueError,'uncertain'):
            C.validate_result(result,self.doc)
        result['verdict']='inconclusive';C.validate_result(result,self.doc)
        result['effects']['rounds'].update(candidate=3,delta=1,percent=50,interval=[0.9,1.1])
        result['verdict']='harm';C.validate_result(result,self.doc)

    def test_historical_partial_push_cannot_establish_first(self):
        self.doc['journey']['measurements'][0]['first_push']['kind']='push-event'
        self.refuse('complete push')

    def test_clean_control_no_result_and_unresolved_pairs(self):
        self.replay();r=self.doc['replay'];row=r['cohort'][0]
        row['known']=[]
        for arm in row['arms'].values(): arm['adjudications'][0]['findings']=[]
        self.check()  # Both arms correctly report no findings on a clean control.
        for arm in row['arms'].values(): arm.update(status='not_run',report_hash=None,reported_at=None,finished_at=None,adjudications=[])
        r['started_at']=None;r['completed_at']=None
        r['selection']='pending';r['avoided_rounds']['value']=None;self.check()
        self.replay();row=self.doc['replay']['cohort'][0]
        row['arms']['old']['adjudications'][0]['findings'][0]['outcome']='unadjudicated'
        self.doc['replay']['selection']='pending';self.doc['replay']['completed_at']=None;self.check()
        self.doc['replay']['selection']='candidate';self.refuse('unadjudicated')

    def test_review_bindings_and_detectable_answer_leak(self):
        # Findings 1/2/8: stale approval, detectable sealed bytes, and predecessor
        # dates can cross the contract boundary despite nonempty attestations.
        self.assigned();e=self.doc['experiment'];e['tag']='synthetic-other-candidate'
        self.doc['experiment_hash']=C.digest(e);self.refuse('experiment')
        self.setUp();self.replay();c=self.doc['replay']['cohort'][0]['context']
        c['materials'][0]['hash']=c['sealed_key_hash'];self.refuse('sealed')
        self.setUp();self.assigned();p=self.doc['preregistration']
        p['registered_at']='2030-01-01T09:00:00Z';p['method_review']['at']='2030-01-01T10:00:00Z';p['live_approval']['at']='2030-01-01T11:00:00Z'
        self.doc['assignments'][0].update(assigned_at='2030-01-03T00:00:00Z',preregistration_hash=C.preregistration_digest(p))
        self.refuse('predecessor')

    def test_cf4_evidence_and_blinded_adjudication_can_append(self):
        # Findings 3/4: completion must preserve frozen inputs without making
        # unrun evidence or unresolved review scores permanent.
        before=copy.deepcopy(self.doc);before['cf4_runs']={a:[] for a in ('old','candidate')}
        C.validate_transition(before,self.doc,self.journey)
        self.replay();r=self.doc['replay'];r['selection']='pending';r['completed_at']=None
        arm=r['cohort'][0]['arms']['old'];arm['adjudications'][0]['findings'][0]['outcome']='unadjudicated'
        before=copy.deepcopy(self.doc)
        adjudication=copy.deepcopy(arm['adjudications'][0]);adjudication['at']='2030-01-04T00:25:00Z';adjudication['findings'][0]['outcome']='catch'
        arm['adjudications'].append(adjudication);r['selection']='candidate';r['completed_at']='2030-01-04T00:30:00Z'
        C.validate_transition(before,self.doc,self.journey)
        arm['report_hash']='f'*64
        with self.assertRaisesRegex(ValueError,'immutable'):
            C.validate_transition(before,self.doc,self.journey)

    def test_refresh_preserves_first_push_and_completed_evidence(self):
        # Findings 5/6/7: refreshed collection is allowed; established push,
        # terminal harm and completed artifact identity cannot disappear.
        after=copy.deepcopy(self.doc);after_journey=copy.deepcopy(self.journey);after_journey['duplicates']+=1
        after['journey']['journey_hash']=C.digest(after_journey)
        C.validate_transition(self.doc,after,self.journey,after_journey)
        after['journey']['measurements'][0]['first_push']['at']='2030-01-02T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'first push'):
            C.validate_transition(self.doc,after,self.journey,after_journey)
        self.setUp();self.result();self.doc['result'].update(status='stopped',verdict='harm',at='2030-01-10T00:00:00Z')
        self.doc['result']['stops']=[{'kind':'main-red','arm':'old','at':'2030-01-09T00:00:00Z','source':'s3','exposed':1,'observed':1}]
        before=copy.deepcopy(self.doc);self.doc['result']=None
        with self.assertRaisesRegex(ValueError,'terminal'):
            C.validate_transition(before,self.doc,self.journey)
        self.doc=copy.deepcopy(before);self.doc['stages']['replay']['artifact_hash']='e'*64
        with self.assertRaisesRegex(ValueError,'completed stage'):
            C.validate_transition(before,self.doc,self.journey)

    def test_strict_numeric_joins_and_positive_fractional_windows(self):
        # Findings 10/12: JSON floats must not alias integer identities. Positive
        # fractional hours remain valid; this contract invents no one-hour floor.
        self.doc['journey']['measurements'][0]['pr']=4201.0;self.refuse('integer')
        self.setUp();self.assigned();self.doc['deviations']=[{'ticket':4102.0,'kind':'overlap','material':True,'source':'s1','actual_revision':None}]
        self.refuse('integer')
        self.setUp();self.doc['experiment']['defect_policy']['followup_hours']=0.5
        self.doc['experiment_hash']=C.digest(self.doc['experiment'])
        self.doc['journey']['measurements'][0]['defects']={'status':'unknown','observed_until':None,'events':[],'resolutions':[]}
        self.check()
        self.assigned();self.doc['preregistration']['experiment_hash']=self.doc['experiment_hash']
        self.doc['preregistration']['stopping']['window_hours']=0.5
        self.doc['assignments'][0]['preregistration_hash']=C.preregistration_digest(self.doc['preregistration'])
        self.check()

    def test_work_start_observation_can_fill_once(self):
        # Recheck 1: recording actual work must not rewrite the pre-work arm,
        # timestamp, revision or protocol binding. Earlier tests only froze ids.
        self.assigned();before=copy.deepcopy(self.doc)
        self.doc['assignments'][0]['work_started_at']='2030-01-06T00:00:00Z'
        self.check()
        C.validate_transition(before,self.doc,self.journey)
        before=copy.deepcopy(self.doc);self.doc['assignments'][0]['work_started_at']='2030-01-06T01:00:00Z'
        with self.assertRaisesRegex(ValueError,'immutable'):
            C.validate_transition(before,self.doc,self.journey)

    def test_adjudication_waits_for_both_reviews(self):
        # Recheck 3: an arm's own completed report is insufficient for blinded
        # scoring; scoring first can expose answers to the other live reviewer.
        self.replay();row=self.doc['replay']['cohort'][0]
        row['arms']['candidate']['reported_at']='2030-01-04T00:25:00Z'
        row['arms']['candidate']['finished_at']='2030-01-04T00:25:00Z'
        row['arms']['candidate']['adjudications'][0]['at']='2030-01-04T00:26:00Z'
        self.refuse('paired')

    def test_failed_research_refuses_replay(self):
        # Recheck 4: an explicit failed predecessor must not be ignored merely
        # because compatible CF4 artifacts exist. Live admission tested this,
        # but the earlier replay boundary did not.
        self.replay();self.doc['stages']['research']={'status':'fail','artifact_hash':'f'*64,'source':'s1','at':'2030-01-03T00:00:00Z'}
        self.refuse('research')

    def test_unknown_attribution_resolves_without_rewriting_observation(self):
        # Recheck 2: later causal evidence may settle unknown attribution;
        # raw observation, canonical key and prior decisions must survive.
        before=copy.deepcopy(self.doc)
        defects=self.doc['journey']['measurements'][0]['defects']
        defects['resolutions'].append(read(FIX/'attribution-resolution.json'))
        C.validate_transition(before,self.doc,self.journey)
        self.assertEqual(defects['events'][0]['attribution'],'unknown')
        self.assertEqual(C.defect_attributions(defects),{'D1':'attributable'})
        before=copy.deepcopy(self.doc);defects['resolutions'][0]['source']='s5'
        with self.assertRaisesRegex(ValueError,'resolution'):
            C.validate_transition(before,self.doc,self.journey)
        self.doc=copy.deepcopy(before);defects=self.doc['journey']['measurements'][0]['defects']
        defects['resolutions'].append(copy.deepcopy(defects['resolutions'][0]));self.refuse('duplicate')

    def test_partial_pair_waits_for_terminal_attempts(self):
        # Error/uncertain/explicit-not-run disposal is part of the same scoring
        # barrier. A complete arm cannot expose a key to a still-pending arm.
        self.replay('partial.json');arm=self.doc['replay']['cohort'][0]['arms']['candidate']
        arm['finished_at']='2030-01-04T00:25:00Z';self.refuse('paired')
        self.doc['replay']['cohort'][0]['arms']['old']['adjudications'][0]['at']='2030-01-04T00:26:00Z'
        self.check()
        arm['finished_at']=None;self.refuse('finished')

    def test_r1_refresh_cannot_erase_known_builder_start(self):
        # R1: old journey evidence must survive even before an assignment exists;
        # the earlier assignment-field test does not protect upstream history.
        for mutation in ('move','remove','replace-source'):
            with self.subTest(mutation=mutation):
                self.setUp();before=copy.deepcopy(self.doc);old_journey=copy.deepcopy(self.journey)
                self.assigned()  # Independent later-start world: Jan 6, assignment Jan 5.
                ticket=next(t for t in self.journey['tickets'] if t['ticket']==4102)
                start=next(e for e in ticket['events'] if e['kind']=='builder_start')
                if mutation=='remove':
                    ticket['events'].remove(start)
                    ticket['gaps']=['no builder start record','no pull request','no merge']
                elif mutation=='replace-source':
                    self.doc['assignments']=[]
                    start['at']='2030-01-01T12:00:00Z'
                    self.journey['sources'][start['source']]='https://github.com/example/factory/issues/4102#issuecomment-5999'
                self.doc['journey']['journey_hash']=C.digest(self.journey)
                self.check()  # Each refreshed endpoint conforms in isolation.
                with self.assertRaisesRegex(ValueError,'builder start'):
                    C.validate_transition(before,self.doc,old_journey,self.journey)

    def test_r1_start_identity_survives_local_id_and_source_key_changes(self):
        before=copy.deepcopy(self.doc);old_journey=copy.deepcopy(self.journey)
        ticket=next(t for t in self.journey['tickets'] if t['ticket']==4102)
        start=next(e for e in ticket['events'] if e['kind']=='builder_start')
        url=self.journey['sources'].pop(start['source'])
        self.journey['sources']['s90']=url;start.update(id='e90',source='s90')
        self.doc['journey']['journey_hash']=C.digest(self.journey)
        C.validate_transition(before,self.doc,old_journey,self.journey)

    def test_cli_strict_read_no_side_effects(self):
        cmd=[sys.executable,'-I',str(HERE/'experiment_contract.py'),'check',str(FIX/'accepted.json'),
             '--journey',str(HERE/'fixtures/journey/journeys.json')]
        p=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        for raw in ['{"schema":1,"schema":2}', '{"schema":NaN}', '[]']:
            with self.subTest(raw=raw),tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'bad.json';path.write_text(raw)
                bad=cmd.copy();bad[4]=str(path)
                p=subprocess.run(bad,capture_output=True,text=True)
                self.assertEqual(p.returncode,1,p.stderr)
                self.assertEqual(list(Path(folder).iterdir()),[path])


if __name__=='__main__':
    unittest.main()
