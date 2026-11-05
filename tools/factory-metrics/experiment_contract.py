#!/usr/bin/env python3
"""EB5 shared contracts, not collectors, scoring engines or execution authority.

Only stdlib and the existing journey validator. check reads its two explicit
files and writes nothing. Callers must verify referenced evidence independently.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
from statistics import NormalDist
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('eb_journey', HERE / 'journey.py')
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)
ARMS = ('old', 'candidate')
RUBRIC = {'matching':'same-root-cause-and-location', 'deduplication':'root-cause-per-pr',
          'severity':['high','medium','low'], 'unmatched':'unadjudicated-until-blind-review',
          'adjudication':'arm-blind', 'missing_pair':'retain-inconclusive'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def fields(value, keys, where):
    require(type(value) is dict and set(value) == set(keys.split()), f'{where}: unexpected or missing fields')


def text(value, where):
    require(type(value) is str and bool(value.strip()), f'{where}: expected nonempty text')


def integer(value, low=0):
    require(type(value) is int and value >= low, 'expected an integer')


def number(value, low=0):
    require(type(value) in (int, float) and math.isfinite(value), 'expected a finite number')
    require(value >= low, 'number below bound')


def array(value, where):
    require(type(value) is list, f'{where}: expected array')
    return value


def choice(value, choices, where):
    require(value in choices, f'invalid {where}')


def hex_value(value, n, where):
    require(type(value) is str and re.fullmatch('[0-9a-f]{'+str(n)+'}', value), f'invalid {where}')


def time(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value), 'invalid time')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError('invalid time') from e


def revision(value):
    fields(value, 'commit tree', 'revision')
    hex_value(value['commit'], 40, 'commit'); hex_value(value['tree'], 40, 'tree')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def preregistration_digest(protocol):
    # Approval attests the protocol; it is not part of the frozen protocol.
    return digest({k:v for k,v in protocol.items() if k!='live_approval'})


def source(key, sources):
    require(type(key) is str and key in sources, 'missing source evidence')


def validate_journey(value):
    """Preserve v1's own strict validator; no alternate legacy parser."""
    try:
        J.validate(value)
    except J.ReadError as e:
        raise ValueError(str(e)) from e


def migrate_journey(journey):
    """Explicit v1 sidecar migration. Never manufacture timing or verification."""
    validate_journey(journey)
    rows = []
    for p in journey['pull_requests']:
        rows.append({'pr':p['number'],
            'first_push':{'status':'unknown','at':None,'kind':None,'source':None,'coverage':'unknown'},
            'merge':{'status':'unknown','at':None,'commit':None,'source':None,'read_at':None},
            'rounds':[e['id'] for e in p['events'] if J.rounds_of(e)],
            'helpers':[e['id'] for e in p['events'] if e['kind']=='verdict' and not e['independent']],
            'defects':{'status':'unknown','observed_until':None,'events':[],'resolutions':[]}})
    return {'schema':'closedwiz.journey.outcomes.v1','journey_hash':digest(journey),'measurements':rows}


def _builder_starts(journey):
    """Earliest known start by ticket and stable provenance, not local ids."""
    starts={}
    for ticket in journey['tickets']:
        for event in ticket['events']:
            if event['kind']=='builder_start':
                key=(ticket['ticket'],journey['sources'][event['source']])
                at=time(event['at'])
                starts[key]=min(starts.get(key,at),at)
    return starts


def _assignment_before_builder_starts(assignment, starts):
    known=[at for (ticket,_),at in starts.items() if ticket==assignment['ticket']]
    if assignment['work_started_at'] is not None: known.append(time(assignment['work_started_at']))
    require(all(time(assignment['assigned_at'])<=at for at in known),
            'assignment must be before known builder start')


def validate_outcomes(outcomes, journey, policy, sources):
    fields(outcomes, 'schema journey_hash measurements', 'journey outcomes')
    require(outcomes['schema']=='closedwiz.journey.outcomes.v1' and outcomes['journey_hash']==digest(journey),
            'journey version/hash mismatch')
    prs = {p['number']:p for p in journey['pull_requests']}
    rows = array(outcomes['measurements'], 'measurements')
    for row in rows:
        fields(row, 'pr first_push merge rounds helpers defects', 'measurement')
        integer(row['pr'],1)
    require([m.get('pr') for m in rows if type(m) is dict] == list(prs), 'measurement coverage/order mismatch')
    for m in rows:
        fields(m, 'pr first_push merge rounds helpers defects', 'measurement')
        p = prs[m['pr']]
        push, merge, defects = m['first_push'], m['merge'], m['defects']
        fields(push, 'status at kind source coverage', 'first push')
        choice(push['status'], ('observed','unknown'), 'push status')
        choice(push['coverage'], ('complete','partial','unknown'), 'push coverage')
        if push['status']=='unknown':
            require(all(push[k] is None for k in ('at','kind','source')) and push['coverage']=='unknown',
                    'unknown first push must remain unknown')
        else:
            time(push['at']); source(push['source'], sources)
            choice(push['kind'], ('builder-push-receipt','push-event'), 'first push evidence')
            require(push['coverage']!='unknown', 'observed push needs coverage')
            require(push['kind']!='push-event' or push['coverage']=='complete', 'historical first push needs complete push coverage')
        fields(merge, 'status at commit source read_at', 'merge')
        choice(merge['status'], ('verified','unknown','unmerged'), 'merge status')
        if merge['status']=='verified':
            source(merge['source'], sources); hex_value(merge['commit'],40,'merge commit')
            require(p['state']=='merged' and p['revisions']['merge']==merge['commit'], 'merge revision/state mismatch')
            events=[e for e in p['events'] if e['kind']=='merge']
            require(len(events)==1 and merge['at']==events[0]['at'], 'merge time mismatch')
            require(time(merge['read_at'])>=time(merge['at']), 'merge read before merge')
            if push['status']=='observed':
                require(time(push['at'])<=time(merge['at']), 'push after merge')
        else:
            require(all(merge[k] is None for k in ('at','commit','source','read_at')), 'unknown/unmerged merge has invented evidence')
            require(merge['status']!='unmerged' or p['state']!='merged', 'unmerged contradicts journey')
        require(m['rounds']==[e['id'] for e in p['events'] if J.rounds_of(e)], 'independent round separation mismatch')
        require(m['helpers']==[e['id'] for e in p['events'] if e['kind']=='verdict' and not e['independent']],
                'helper separation mismatch')
        fields(defects, 'status observed_until events resolutions', 'defects')
        choice(defects['status'], ('unknown','unmatured','mature'), 'defect maturity')
        events=array(defects['events'],'defects')
        if defects['status']=='unknown':
            require(defects['observed_until'] is None, 'unknown follow-up must stay unknown')
        else:
            require(merge['status']=='verified', 'maturity needs verified merge')
            until=time(defects['observed_until']); start=time(merge['at'])
            require(until>=start,'follow-up before merge')
            mature=until>=start+timedelta(hours=policy['followup_hours'])
            require((defects['status']=='mature')==mature, 'defect maturity contradicts frozen window')
        keys=set()
        for e in events:
            fields(e, 'key kind at attribution source', 'defect event')
            text(e['key'],'defect key');require(e['key'] not in keys,'duplicate defect');keys.add(e['key'])
            choice(e['kind'], ('main-red','later-defect-fix'), 'defect kind')
            choice(e['attribution'], ('attributable','unattributed','unknown'), 'defect attribution')
            source(e['source'],sources);time(e['at'])
            require(merge['status']=='verified' and time(e['at'])>=time(merge['at']), 'defect needs post-merge evidence')
            if defects['observed_until'] is not None:
                require(time(e['at'])<=time(defects['observed_until']), 'defect after observed coverage')
            require(time(e['at'])<=time(merge['at'])+timedelta(hours=policy['followup_hours']), 'defect outside frozen window')

        observations={event['key']:event for event in events};resolved=set()
        for resolution in array(defects['resolutions'],'attribution resolutions'):
            fields(resolution,'key at attribution source','attribution resolution')
            text(resolution['key'],'resolution key');key=resolution['key']
            require(key in observations,'resolution needs original defect')
            require(key not in resolved,'duplicate attribution resolution');resolved.add(key)
            require(observations[key]['attribution']=='unknown','resolution requires unknown original attribution')
            choice(resolution['attribution'],('attributable','unattributed'),'resolved attribution')
            require(time(resolution['at'])>=time(observations[key]['at']),'resolution before observation')
            source(resolution['source'],sources)


def defect_attributions(defects):
    """Project validated observations and their sourced, append-only resolutions."""
    result={event['key']:event['attribution'] for event in defects['events']}
    result.update((row['key'],row['attribution']) for row in defects['resolutions'])
    return result


def validate_experiment(e, sources):
    fields(e, 'tag repo frozen_at arms defect_policy settings_hash change_kind replay_settings', 'experiment')
    require(type(e['tag']) is str and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,63}',e['tag']), 'invalid experiment tag')
    require(type(e['repo']) is str and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',e['repo']), 'invalid repo')
    time(e['frozen_at']);fields(e['arms'],'old candidate','arms')
    choice(e['change_kind'],('skill','model','brief'),'experiment change kind')
    settings=e['replay_settings']
    fields(settings,'provider model effort service_tier tools context','replay settings')
    require(settings['provider']=='codex' and settings['service_tier']=='default' and
            settings['tools']=='read-only-scoped' and settings['context']=='first-review-only-v1',
            'invalid replay settings')
    text(settings['model'],'replay model');choice(settings['effort'],('high','xhigh'),'replay effort')
    require(e['settings_hash']==digest(settings),'replay settings hash mismatch')
    for a in ARMS:
        arm=e['arms'][a];fields(arm,'revision build_hash review_hash cf4 brief_hash','arm');revision(arm['revision'])
        for k in ('build_hash','review_hash','brief_hash'): hex_value(arm[k],64,'skill hash')
        cf=arm['cf4']
        fields(cf,'manifest_hash settings_hash cases_hash code_hash schema_hash revision repeats case_count','CF4 reference')
        for k in ('manifest_hash','settings_hash','cases_hash','code_hash','schema_hash'): hex_value(cf[k],64,'CF4 hash')
        revision(cf['revision']);require(cf['revision']==arm['revision'],'CF4 revision mismatch')
        for k in ('repeats','case_count'): integer(cf[k],1)
    old,new=(e['arms'][a]['cf4'] for a in ARMS)
    require(all(old[k]==new[k] for k in ('settings_hash','cases_hash','code_hash','schema_hash','repeats','case_count')),
            'incompatible CF4 comparison; fresh baseline required')
    policy=e['defect_policy'];fields(policy,'rule followup_hours deduplication unknown_attribution','defect policy')
    text(policy['rule'],'attribution rule');number(policy['followup_hours']);require(policy['followup_hours']>0,'positive follow-up required')
    require(policy['deduplication']=='root-cause-per-merge' and policy['unknown_attribution']=='retain-unknown',
            'invalid defect policy')


def validate_cf4_runs(runs, experiment, sources):
    fields(runs,'old candidate','CF4 runs')
    for arm in ARMS:
        seen=set();cf=experiment['arms'][arm]['cf4'];last=None
        for run in array(runs[arm],'CF4 runs'):
            fields(run,'key status runs passed score_hash at source','CF4 run')
            text(run['key'],'CF4 run key');require(run['key'] not in seen,'duplicate CF4 run');seen.add(run['key'])
            choice(run['status'],('pass','fail','error'),'CF4 run status')
            for key in ('runs','passed'): integer(run[key])
            require(run['passed']<=run['runs']<=cf['repeats']*cf['case_count'],'invalid CF4 run counts')
            if run['status']=='pass':
                require(run['passed']==run['runs']==cf['repeats']*cf['case_count'],'CF4 pass requires every run')
            hex_value(run['score_hash'],64,'CF4 score hash');source(run['source'],sources)
            at=time(run['at']);require(last is None or at>=last,'CF4 run order');last=at


def cf4_passes(refs, runs):
    fields(refs,'old candidate','CF4 references')
    selected=[]
    for arm in ARMS:
        text(refs[arm],'CF4 reference')
        matches=[r for r in runs[arm] if r['key']==refs[arm] and r['status']=='pass']
        require(len(matches)==1,'missing passed CF4 predecessor')
        selected.append(matches[0])
    return selected


def validate_findings(findings, known):
    observed=set();resolved=True
    for f in array(findings,'paired findings'):
        fields(f,'id severity outcome','paired finding');text(f['id'],'finding id')
        require(f['id'] not in observed,'duplicate scoring');observed.add(f['id'])
        choice(f['severity'],RUBRIC['severity'],'severity')
        choice(f['outcome'],('catch','miss','false_positive','unmatched','unadjudicated'),'finding outcome')
        if f['id'] in known:
            require(f['severity']==known[f['id']],'known finding severity mismatch')
            require(f['outcome'] in ('catch','miss','unadjudicated'),'known finding cannot be false positive/unmatched')
        else:
            require(f['outcome'] in ('false_positive','unmatched','unadjudicated'),'catch/miss needs known finding')
        if f['outcome'] in ('unmatched','unadjudicated'): resolved=False
    require(set(known)<=observed,'missing known finding outcome')
    return resolved


def validate_replay(r, e, sources):
    fields(r, 'frozen_at started_at completed_at cf4_refs selection_rules exclusions rubric rubric_hash cohort selection avoided_rounds', 'replay')
    require(time(r['frozen_at'])>=time(e['frozen_at']),'replay before experiment freeze')
    if r['started_at'] is not None: require(time(r['started_at'])>=time(r['frozen_at']),'replay start before freeze')
    if r['completed_at'] is not None:
        require(time(r['completed_at'])>=time(r['started_at'] or r['frozen_at']),'replay completion before start')
    fields(r['cf4_refs'],'old candidate','replay CF4 refs')
    for ref in r['cf4_refs'].values(): text(ref,'CF4 reference')
    text(r['selection_rules'],'cohort selection')
    require(r['rubric']==RUBRIC and r['rubric_hash']==digest(r['rubric']), 'rubric mismatch')
    excluded=set()
    for x in array(r['exclusions'],'exclusions'):
        fields(x,'pr reason','exclusion');integer(x['pr'],1);text(x['reason'],'exclusion reason')
        require(x['pr'] not in excluded,'duplicate exclusion');excluded.add(x['pr'])
    seen, contexts, runs=set(),set(),set();complete=True;attempted=False
    for row in array(r['cohort'],'cohort'):
        fields(row,'pr first_review_at base head context_hash context known arms history','replay row')
        integer(row['pr'],1);require(row['pr'] not in seen|excluded,'duplicate/excluded PR');seen.add(row['pr'])
        hex_value(row['base'],40,'base commit');hex_value(row['head'],40,'head commit')
        require(time(row['first_review_at'])<=time(r['frozen_at']),'snapshot after freeze')
        history=row['history'];fields(history,'merge_commit merged_at source independent_rounds defects','replay history')
        hex_value(history['merge_commit'],40,'historical merge commit');source(history['source'],sources)
        require(time(row['first_review_at'])<=time(history['merged_at'])<=time(r['frozen_at']),'historical merge chronology')
        if history['independent_rounds'] is not None: integer(history['independent_rounds'])
        defects=history['defects'];fields(defects,'status count observed_until','historical defects')
        choice(defects['status'],('unknown','unmatured','mature'),'historical defect status')
        if defects['status']=='unknown': require(defects['count'] is None and defects['observed_until'] is None,'unknown historical defects')
        else:
            integer(defects['count']);until=time(defects['observed_until']);start=time(history['merged_at'])
            require(start<=until<=time(r['frozen_at']),'historical follow-up coverage')
            require((defects['status']=='mature')==(until>=start+timedelta(hours=e['defect_policy']['followup_hours'])),'historical defect maturity')
        hex_value(row['context_hash'],64,'context hash')
        c=row['context'];fields(c,'isolation materials sealed_key_hash','context')
        choice(c['isolation'],('verified','unavailable'),'isolation');hex_value(c['sealed_key_hash'],64,'sealed key hash')
        materials=array(c['materials'],'materials');require(bool(materials),'missing context material')
        for m in materials:
            fields(m,'kind at hash','material')
            choice(m['kind'],('original-diff','original-file','original-instructions'),'context material')
            require(time(m['at'])<=time(row['first_review_at']),'later material in first-review context')
            hex_value(m['hash'],64,'material hash');require(m['hash']!=c['sealed_key_hash'],'sealed answer key leaked into material')
        known={}
        for f in array(row['known'],'known findings'):
            fields(f,'id severity','known finding');text(f['id'],'finding id')
            choice(f['severity'],RUBRIC['severity'],'severity');require(f['id'] not in known,'duplicate known finding')
            known[f['id']]=f['severity']
        fields(row['arms'],'old candidate','replay arms')
        for arm in row['arms'].values():
            fields(arm,'status run_key context_key settings_hash skill_hash context_hash report_hash reported_at finished_at adjudications','replay arm')
        finished_times=[None if arm['finished_at'] is None else time(arm['finished_at'])
                        for arm in row['arms'].values()]
        for a in ARMS:
            arm=row['arms'][a]
            fields(arm,'status run_key context_key settings_hash skill_hash context_hash report_hash reported_at finished_at adjudications','replay arm')
            choice(arm['status'],('complete','not_run','error','uncertain'),'replay result status')
            require(arm['settings_hash']==e['settings_hash'] and arm['skill_hash']==e['arms'][a]['review_hash'],
                    'replay revision/settings mismatch')
            require(arm['context_hash']==row['context_hash'],'unequal replay context')
            for key,registry in (('run_key',runs),('context_key',contexts)):
                text(arm[key],key);require(arm[key] not in registry,'replay requires fresh contexts/runs');registry.add(arm[key])
            require(c['isolation']=='verified' or arm['status']=='not_run','unavailable isolation must not run')
            attempted |= arm['status']!='not_run'
            require(arm['finished_at'] is not None or arm['status']=='not_run','attempt missing finished time')
            if arm['finished_at'] is not None:
                require(time(arm['finished_at'])>=time(r['started_at'] or r['frozen_at']),'attempt finished before start/freeze')
                if r['completed_at'] is not None:
                    require(time(arm['finished_at'])<=time(r['completed_at']),'attempt finished after replay completion')
            adjudications=array(arm['adjudications'],'adjudications')
            if arm['status']!='complete':
                complete=False
                require(not adjudications and arm['report_hash'] is None and arm['reported_at'] is None,'incomplete replay result has scores')
                continue
            hex_value(arm['report_hash'],64,'review report hash')
            require(r['started_at'] is not None and time(r['started_at'])<=time(arm['reported_at'])<=time(arm['finished_at']),'review outside attempt interval')
            last=time(arm['reported_at']);resolved=False
            for adjudication in adjudications:
                fields(adjudication,'at source findings','adjudication')
                require(all(finished is not None and time(adjudication['at'])>=finished for finished in finished_times),
                        'paired attempts must be finished before adjudication')
                require(time(adjudication['at'])>=last,'adjudication before review/previous checkpoint');last=time(adjudication['at'])
                source(adjudication['source'],sources)
                resolved=validate_findings(adjudication['findings'],known)
            if r['completed_at'] is not None: require(last<=time(r['completed_at']),'adjudication after completion')
            complete &= resolved
    require(bool(seen),'empty replay cohort')
    require(not attempted or r['started_at'] is not None,'attempted replay missing start')
    choice(r['selection'],('old','candidate','none','pending'),'replay selection')
    require(complete or r['selection'] in ('none','pending'),'partial/unadjudicated replay cannot select candidate')
    require(r['selection'] not in ARMS or r['completed_at'] is not None,'selection needs completed replay')
    estimate=r['avoided_rounds'];fields(estimate,'value evidence_class','avoided rounds')
    require(estimate['evidence_class']=='estimate','avoided rounds is only an estimate')
    if estimate['value'] is not None: number(estimate['value'])


def validate_preregistration(p, e, sources):
    fields(p, 'registered_at eligibility primary power guards horizon confidence stopping method_review live_approval experiment_hash cf4_refs replay_hash', 'preregistration')
    require(time(p['registered_at'])>=time(e['frozen_at']),'preregistration before freeze')
    require(p['experiment_hash']==digest(e),'preregistration experiment binding mismatch')
    fields(p['cf4_refs'],'old candidate','protocol CF4 refs')
    for ref in p['cf4_refs'].values(): text(ref,'CF4 reference')
    hex_value(p['replay_hash'],64,'protocol replay hash')
    text(p['eligibility'],'eligibility')
    fields(p['primary'],'statistic test unfinished missing','primary analysis')
    for value in p['primary'].values(): text(value,'primary choice')
    power=p['power']
    fields(power,'method alpha power effect_hours baseline_sd_hours baseline_n baseline_unknown baseline_source z_alpha z_power time_n_per_arm min_n_per_arm assumptions','power')
    require(power['method']=='normal-mean-planning-v1','unsupported power method')
    for k in ('alpha','power'): number(power[k]);require(0<power[k]<1,'invalid power probability')
    for k in ('effect_hours','baseline_sd_hours'): number(power[k]);require(power[k]>0,'positive power input required')
    integer(power['baseline_n'],2);integer(power['baseline_unknown']);source(power['baseline_source'],sources)
    text(power['assumptions'],'power assumptions')
    for key,prob in (('z_alpha',1-power['alpha']/2),('z_power',power['power'])):
        number(power[key]);require(math.isclose(power[key],NormalDist().inv_cdf(prob),rel_tol=1e-9),'power critical value mismatch')
    planned=math.ceil(2*(power['z_alpha']+power['z_power'])**2*power['baseline_sd_hours']**2/power['effect_hours']**2)
    integer(power['time_n_per_arm'],1);require(power['time_n_per_arm']==planned,'power sample arithmetic mismatch')
    integer(power['min_n_per_arm'],1);fields(p['guards'],'rounds defects','guards')
    minima=[planned]
    for guard in p['guards'].values():
        fields(guard,'test margin max_interval_width min_n_per_arm','guard')
        text(guard['test'],'guard test');require(type(guard['margin']) in (int,float) and guard['margin']==0,'guard must not worsen')
        number(guard['max_interval_width']);require(guard['max_interval_width']>0,'positive guard precision required')
        integer(guard['min_n_per_arm'],2);minima.append(guard['min_n_per_arm'])
    require(power['min_n_per_arm']>=max(minima),'sample below time/guard minimum')
    require(time(p['horizon'])>time(p['registered_at']),'invalid analysis horizon')
    number(p['confidence']);require(math.isclose(p['confidence'],1-power['alpha']),'confidence/alpha mismatch')
    stop=p['stopping']
    fields(stop,'main_red rounds_multiplier rounds_reference reference_source window_hours minimum_exposed efficacy_peeking','stopping')
    require(stop['main_red']=='any-attributable-event' and type(stop['rounds_multiplier']) is int and stop['rounds_multiplier']==2,
            'safety stop contract changed')
    number(stop['rounds_reference']);require(stop['rounds_reference']>0,'positive rounds reference required')
    source(stop['reference_source'],sources);number(stop['window_hours']);require(stop['window_hours']>0,'positive stopping window required');integer(stop['minimum_exposed'],1)
    require(stop['efficacy_peeking'] is False,'efficacy peeking forbidden')
    review=p['method_review'];require(type(review) is dict,'missing method review')
    fields(review,'at source','method review');source(review['source'],sources)
    require(time(p['registered_at'])<=time(review['at'])<time(p['horizon']),'method review chronology')
    approval=p['live_approval'];fields(approval,'status at source','live approval')
    choice(approval['status'],('granted','not_granted'),'approval status')
    if approval['status']=='granted':
        source(approval['source'],sources);require(time(approval['at'])>=time(review['at']),'approval before method review')
    else: require(approval['at'] is None and approval['source'] is None,'ungranted approval has evidence')


def validate_usage(rows, sources):
    seen=set()
    for row in array(rows,'usage'):
        fields(row,'scope provider unit status value coverage attribution source gaps','usage')
        choice(row['scope'],('old','candidate','total'),'usage scope')
        choice(row['provider'],('codex','cloudroom','openrouter'),'usage provider')
        choice(row['unit'],('tokens','credits','usd','sandbox_hours'),'usage unit')
        valid_units={'codex':('tokens',), 'cloudroom':('credits','usd','sandbox_hours'), 'openrouter':('tokens','usd')}
        require(row['unit'] in valid_units[row['provider']],'provider/unit mismatch')
        gaps=array(row['gaps'],'usage gaps')
        require(all(type(g) is str and g in ('missing-export','shared-sandbox','no-attribution','not-run') for g in gaps)
                and len(set(gaps))==len(gaps),'invalid usage gaps')
        key=(row['scope'],row['provider'],row['unit']);require(key not in seen,'duplicate usage');seen.add(key)
        choice(row['status'],('known','unknown','unattributed','absent'),'usage status')
        choice(row['coverage'],('complete','partial','none'),'usage coverage')
        choice(row['attribution'],('direct','shared','unavailable'),'usage attribution')
        require(row['scope']=='total' or row['attribution']!='shared','shared cost cannot be divided between arms')
        require(row['unit']!='sandbox_hours' or row['scope']=='total','sandbox usage is total only')
        require((row['coverage']=='complete')==(not gaps),'usage coverage needs explicit gaps')
        if row['status']=='known':
            number(row['value']);source(row['source'],sources)
            require(row['coverage']!='none' and row['attribution']!='unavailable','known usage needs attribution and coverage')
            if row['unit']=='tokens': integer(row['value'])
        else:
            require(row['value'] is None,'unknown usage must not become zero')
            if row['source'] is not None: source(row['source'],sources)
        if row['status']=='absent': require(row['coverage']=='none','absent coverage mismatch')
    required={(scope,provider,unit) for scope in (*ARMS,'total') for provider,unit in (('codex','tokens'),('cloudroom','credits'))}
    for _,provider,unit in seen:
        if unit!='sandbox_hours': required.update((scope,provider,unit) for scope in (*ARMS,'total'))
    require(required<=seen,'usage coverage must include both arms and total, unknown rows included')
    # Totals can include unattributed usage, but never understate observed arms.
    totals={(p,u):r for r in rows if r['scope']=='total' for p,u in [(r['provider'],r['unit'])]}
    for key,total in totals.items():
        known=[r['value'] for r in rows if r['scope'] in ARMS and (r['provider'],r['unit'])==key and r['status']=='known']
        if total['status']=='known': require(total['value']>=sum(known),'usage total below observed arms')


def validate(doc, journey):
    fields(doc, 'schema experiment experiment_hash cf4_runs journey assignments deviations stages replay preregistration result usage sources', 'document')
    require(doc['schema']=='openwiz.bottlenecks.v1','unsupported contract version')
    sources=doc['sources'];require(type(sources) is dict,'invalid sources')
    e=doc['experiment'];require(type(e) is dict,'invalid experiment')
    require(type(e.get('repo')) is str,'invalid repo')
    for key,url in sources.items():
        require(re.fullmatch(r's[1-9][0-9]*',key) and type(url) is str and
                re.fullmatch(r'https://github\.com/'+re.escape(e.get('repo',''))+r'/(issues|pull|actions/runs)/[1-9][0-9]*(?:[\w/#?=.-]*)',url),
                'invalid provenance source')
    require(not re.search(r'\bthr_[A-Za-z0-9]',json.dumps(doc)),'operational identity forbidden')
    validate_experiment(e,sources)
    require(doc['experiment_hash']==digest(e),'experiment revision binding mismatch')
    validate_cf4_runs(doc['cf4_runs'],e,sources)
    validate_journey(journey);require(journey['repo']==e['repo'],'journey repository mismatch')
    validate_outcomes(doc['journey'],journey,e['defect_policy'],sources)
    fields(doc['stages'],'research cf4 replay live','stages')
    for stage in doc['stages'].values():
        fields(stage,'status artifact_hash source at','stage')
        choice(stage['status'],('not_run','partial','pass','fail','stopped','inconclusive'),'stage status')
        if stage['status']=='not_run':
            require(stage['artifact_hash'] is None and stage['source'] is None and stage['at'] is None,'unrun stage has result')
        else: hex_value(stage['artifact_hash'],64,'stage artifact');source(stage['source'],sources);time(stage['at'])
    if doc['replay'] is not None:
        r=doc['replay'];validate_replay(r,e,sources)
        if r['started_at'] is not None or r['completed_at'] is not None:
            research=doc['stages']['research']
            require(research['status']=='pass' and time(research['at'])<=time(r['started_at'] or r['completed_at']),
                    'replay requires passed research predecessor before start/completion')
            runs=cf4_passes(r['cf4_refs'],doc['cf4_runs'])
            require(all(time(run['at'])<=time(r['started_at'] or r['completed_at']) for run in runs),'replay before CF4 predecessor')
    p=doc['preregistration']
    if p is not None:
        validate_preregistration(p,e,sources)
        r=doc['replay'];require(r is not None and r['selection']=='candidate' and r['completed_at'] is not None,'protocol needs selected replay predecessor')
        require(p['replay_hash']==digest(r),'protocol replay binding mismatch')
        runs=cf4_passes(p['cf4_refs'],doc['cf4_runs'])
        require(p['cf4_refs']==r['cf4_refs'],'protocol/replay CF4 predecessor mismatch')
        require(all(doc['stages'][stage]['status']=='pass' and time(doc['stages'][stage]['at'])<=time(p['registered_at'])
                    for stage in ('research','cf4','replay')) and time(r['completed_at'])<=time(p['registered_at'])
                and all(time(run['at'])<=time(p['registered_at']) for run in runs),'protocol before completed predecessor')
    tickets={t['ticket']:t for t in journey['tickets']};assigned=set()
    starts=_builder_starts(journey)
    for a in array(doc['assignments'],'assignments'):
        fields(a,'ticket arm assigned_at work_started_at revision preregistration_hash','assignment')
        integer(a['ticket'],1);require(a['ticket'] in tickets and a['ticket'] not in assigned,'invalid/duplicate assignment join');assigned.add(a['ticket'])
        require(a['arm']==('candidate' if a['ticket']%2 else 'old'),'assignment parity mismatch')
        revision(a['revision']);require(a['revision']==e['arms'][a['arm']]['revision'],'assignment revision mismatch')
        require(p is not None and p['live_approval']['status']=='granted','live assignment requires separate approval')
        require(all(doc['stages'][s]['status']=='pass' for s in ('research','cf4','replay')) and
                doc['replay'] is not None and doc['replay']['selection']=='candidate','missing passed predecessor evidence')
        require(a['preregistration_hash']==preregistration_digest(p),'assignment preregistration binding mismatch')
        require(time(a['assigned_at'])>=time(p['live_approval']['at']),'assignment before approval')
        _assignment_before_builder_starts(a,starts)
        require(time(a['assigned_at'])<time(p['horizon']),'assignment beyond horizon')
    for d in array(doc['deviations'],'deviations'):
        fields(d,'ticket kind material source actual_revision','deviation');integer(d['ticket'],1);require(d['ticket'] in assigned,'deviation assignment join')
        choice(d['kind'],('revision-change','overlap','other'),'deviation kind')
        if d['kind']=='revision-change': revision(d['actual_revision'])
        else: require(d['actual_revision'] is None,'unexpected deviation revision')
        require(type(d['material']) is bool,'material must be boolean');source(d['source'],sources)
    validate_usage(doc['usage'],sources)
    if doc['result'] is not None: validate_result(doc['result'],doc)


def validate_result(result, doc):
    # Shape and arithmetic only. EB8 owns the estimator, intervals and live engine.
    fields(result,'at preregistration_hash status verdict samples effects stops','live result')
    p=doc['preregistration'];require(p is not None,'result needs preregistration')
    require(result['preregistration_hash']==preregistration_digest(p),'result preregistration mismatch')
    choice(result['status'],('complete','stopped','inconclusive'),'result status')
    choice(result['verdict'],('improved','harm','inconclusive'),'result verdict')
    require(result['status']!='inconclusive' or result['verdict']=='inconclusive','inconclusive status requires inconclusive verdict')
    fields(result['samples'],'old candidate','samples');eligible=True
    for arm in ARMS:
        s=result['samples'][arm];fields(s,'assigned merged open closed_unmerged unknown_timing mature_defects','sample')
        for v in s.values(): integer(v)
        require(s['assigned']==sum(a['arm']==arm for a in doc['assignments']),'sample assignment denominator mismatch')
        require(s['assigned']==s['merged']+s['open']+s['closed_unmerged'],'unfinished work missing')
        require(s['unknown_timing']<=s['assigned'] and s['mature_defects']<=s['merged'],'invalid sample coverage')
        eligible &= s['assigned']>=p['power']['min_n_per_arm'] and s['unknown_timing']==0 and s['mature_defects']==s['merged']
    fields(result['effects'],'time rounds defects','effects');safe=True;faster=False;harm=False
    for name,unit in (('time','hours'),('rounds','rounds'),('defects','proportion')):
        effect=result['effects'][name]
        fields(effect,'unit old candidate delta percent interval','effect')
        require(effect['unit']==unit,'invalid effect unit')
        vals=[effect[k] for k in ('old','candidate','delta','percent','interval')]
        if all(v is None for v in vals): eligible=False;continue
        number(effect['old']);number(effect['candidate'])
        for k in ('delta','percent'):
            if k=='percent' and effect['old']==0: require(effect[k] is None,'zero baseline percentage must be unknown');continue
            require(type(effect[k]) in (int,float) and math.isfinite(effect[k]),'finite effect required')
        require(math.isclose(effect['delta'],effect['candidate']-effect['old'],abs_tol=1e-9),'effect arithmetic mismatch')
        if effect['old']!=0: require(math.isclose(effect['percent'],100*effect['delta']/effect['old'],abs_tol=1e-9),'percentage mismatch')
        interval=array(effect['interval'],'interval');require(len(interval)==2,'interval requires two bounds')
        require(all(type(v) in (int,float) and math.isfinite(v) for v in interval) and interval[0]<=effect['delta']<=interval[1],'invalid interval')
        if name=='defects': require(max(effect['old'],effect['candidate'])<=1,'invalid defect rate')
        if name=='time': faster=interval[1]<0
        else:
            g=p['guards'][name];safe &= interval[1]<=g['margin'] and interval[1]-interval[0]<=g['max_interval_width']
            harm |= interval[0]>0
    stops=array(result['stops'],'stops')
    for stop in stops:
        fields(stop,'kind arm at source exposed observed','safety stop')
        choice(stop['kind'],('main-red','doubled-rounds'),'stop kind');choice(stop['arm'],ARMS,'stop arm');source(stop['source'],doc['sources'])
        require(time(p['registered_at'])<=time(stop['at'])<=time(result['at']),'stop chronology');integer(stop['exposed'],1);number(stop['observed'])
        exposed=sum(a['arm']==stop['arm'] and time(a['assigned_at'])<=time(stop['at']) for a in doc['assignments'])
        require(stop['exposed']<=exposed,'stop exposure exceeds assignments')
        if stop['kind']=='main-red': require(stop['observed']>=1,'main-red stop needs attributable harm')
        else: require(stop['exposed']>=p['stopping']['minimum_exposed'] and stop['observed']>=2*p['stopping']['rounds_reference'],'doubled-round safety boundary mismatch')
    if stops:
        require(result['status']=='stopped' and result['verdict']=='harm','safety stop records harm')
    else:
        require(result['status']!='stopped','stopped result missing safety evidence')
        require(time(result['at'])>=time(p['horizon']),'no efficacy analysis before fixed horizon')
        material=any(d['material'] for d in doc['deviations'])
        expected='harm' if harm else ('improved' if eligible and safe and faster and not material else 'inconclusive')
        require(result['verdict']==expected,'uncertain/immature/underpowered result cannot claim improvement')


def validate_transition(before, after, before_journey, after_journey=None):
    """Check frozen inputs and append-only evidence across explicit snapshots."""
    if after_journey is None: after_journey=before_journey
    validate(before,before_journey);validate(after,after_journey)
    previous_starts,current_starts=_builder_starts(before_journey),_builder_starts(after_journey)
    require(all(key in current_starts and current_starts[key]<=at for key,at in previous_starts.items()),
            'known builder start evidence removed, replaced or moved forward')
    for assignment in after['assignments']:
        _assignment_before_builder_starts(assignment,previous_starts)
    for k in ('experiment','experiment_hash'):
        require(before[k]==after[k],f'immutable {k} changed; start a new experiment')
    if before['preregistration'] is not None:
        require(after['preregistration'] is not None and
                preregistration_digest(before['preregistration'])==preregistration_digest(after['preregistration']),
                'immutable preregistration changed')
        if before['preregistration']['live_approval']['status']=='granted':
            require(before['preregistration']['live_approval']==after['preregistration']['live_approval'],'immutable live approval changed')
    require(all(after['sources'].get(k)==v for k,v in before['sources'].items()),'immutable source evidence changed')
    require(len(after['assignments'])>=len(before['assignments']),'immutable assignments removed')
    for prior,current in zip(before['assignments'],after['assignments']):
        require(all(current[k]==v for k,v in prior.items() if k!='work_started_at'),'immutable assignment identity changed')
        if prior['work_started_at'] is not None:
            require(current['work_started_at']==prior['work_started_at'],'immutable work-start observation changed')
    require(after['deviations'][:len(before['deviations'])]==before['deviations'],'immutable deviations changed')
    for arm in ARMS:
        old,new=before['cf4_runs'][arm],after['cf4_runs'][arm]
        require(new[:len(old)]==old,'immutable CF4 run evidence changed')
    old_measurements={m['pr']:m for m in before['journey']['measurements']}
    new_measurements={m['pr']:m for m in after['journey']['measurements']}
    require(set(old_measurements)<=set(new_measurements),'known journey PR removed')
    require({t['ticket'] for t in before_journey['tickets']}<={t['ticket'] for t in after_journey['tickets']},'known journey ticket removed')
    for pr,old in old_measurements.items():
        new=new_measurements[pr]
        if old['first_push']['status']=='observed': require(old['first_push']==new['first_push'],'established first push changed')
        if old['merge']['status']=='verified': require(old['merge']==new['merge'],'verified merge changed')
        require(new['defects']['events'][:len(old['defects']['events'])]==old['defects']['events'],'known defect evidence changed')
        previous=old['defects']['resolutions']
        require(new['defects']['resolutions'][:len(previous)]==previous,'immutable attribution resolution changed')
        if old['defects']['observed_until'] is not None:
            require(new['defects']['observed_until'] is not None and time(new['defects']['observed_until'])>=time(old['defects']['observed_until']),'defect coverage regressed')
    for name,stage in before['stages'].items():
        if stage['status'] in ('pass','fail','stopped','inconclusive'):
            require(after['stages'][name]==stage,'completed stage evidence changed')
    if before['result'] is not None: require(before['result']==after['result'],'terminal result/harm cannot be erased or changed')
    if before['replay'] is not None:
        old,new=before['replay'],after['replay'];require(new is not None,'immutable replay removed')
        for k in ('frozen_at','selection_rules','exclusions','rubric','rubric_hash','cf4_refs'):
            require(old[k]==new[k],'immutable replay freeze changed')
        if old['started_at'] is not None: require(new['started_at']==old['started_at'],'immutable replay start changed')
        if old['completed_at'] is not None: require(new==old,'completed replay evidence changed')
        require(len(old['cohort'])==len(new['cohort']),'immutable replay cohort changed')
        for a,b in zip(old['cohort'],new['cohort']):
            for k in ('pr','first_review_at','base','head','context_hash','context','known','history'):
                require(a[k]==b[k],'immutable replay snapshot changed')
            for arm in ARMS:
                prior,current=a['arms'][arm],b['arms'][arm]
                keys=('run_key','context_key','settings_hash','skill_hash','context_hash')
                if prior['status']!='not_run' or prior['finished_at'] is not None:
                    keys+=('status','report_hash','reported_at','finished_at')
                require(all(prior[k]==current[k] for k in keys),'immutable replay report/run binding changed; no silent retry')
                previous=prior['adjudications']
                require(current['adjudications'][:len(previous)]==previous,'immutable adjudication history changed')


class UnavailableOperation(RuntimeError):
    pass


def execute(operation, *args, **kwargs):
    """Named seam for downstream owners; even valid input grants no authority."""
    raise UnavailableOperation(f'{operation}: unavailable in EB5 contract-only implementation')


def read(path):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'duplicate JSON key');out[k]=v
        return out
    def constant(_): raise ValueError('nonfinite JSON number')
    return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=constant)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=('check','collect','research','paid_eval','run_replay','launch_live','activate','publish'))
    parser.add_argument('record');parser.add_argument('--journey',required=True)
    args=parser.parse_args()
    try:
        if args.operation!='check': execute(args.operation)
        validate(read(args.record),read(args.journey))
    except (OSError,ValueError,UnavailableOperation,OverflowError) as e:
        print(str(e),file=sys.stderr);return 1
    print('conforms: shapes only; execution unavailable')
    return 0


if __name__=='__main__':
    sys.exit(main())
