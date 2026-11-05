#!/usr/bin/env python3
"""Offline EB8-O controls. No dispatch, collection, activation or spending."""
import copy
from datetime import timedelta
import json
import os
import tempfile
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('eb5', HERE.parent / 'experiment_contract.py')
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


SAFEGUARDS = 'holds_clear independent_review_required required_ci verified_merge_required'
ASSIGNABLE_LIVE = ('not_run', 'partial')


def policy(safeguards):
    C.fields(safeguards, SAFEGUARDS, 'mandatory safeguards')
    C.require(all(v is True for v in safeguards.values()), 'policy safeguards required')


def launch_check(bundle, journey, *, at, safeguards):
    """Offline fact check only. Never authorizes or performs a live launch."""
    policy(safeguards)
    validate(bundle, journey)
    p = bundle['preregistration']
    C.require(p is not None, 'missing preregistration')
    C.require(p['live_approval']['status'] == 'granted', 'missing separate live approval')
    C.require(C.time(p['live_approval']['at']) <= C.time(at) < C.time(p['horizon']),
              'outside approved assignment interval')
    C.require(bundle['result'] is None, 'terminal result: resumption requires separate authority')
    C.require(bundle['stages']['live']['status'] in ASSIGNABLE_LIVE,
              'terminal live stage: resumption requires separate authority')
    C.require(not safety_stops(copy.deepcopy(bundle), journey, at=at), 'unprocessed harm: launch refused')


def assign(bundle, journey, ticket, *, at, eligible, safeguards):
    """Return a new EB5 bundle, retaining the immutable pre-work assignment."""
    launch_check(bundle, journey, at=at, safeguards=safeguards)
    C.integer(ticket, 1)
    C.require(eligible is True, 'ticket not positively eligible')
    prior = next((a for a in bundle['assignments'] if a['ticket'] == ticket), None)
    if prior is not None:
        C.require(prior['assigned_at'] == at, 'immutable assignment: cannot reassign')
        return copy.deepcopy(bundle)
    linked = {pr['number'] for pr in journey['pull_requests'] if ticket in pr['tickets']}
    known_work = [m['first_push']['at'] for m in bundle['journey']['measurements']
                  if m['pr'] in linked and m['first_push']['status'] == 'observed']
    known_work += [e['at'] for pr in journey['pull_requests'] if pr['number'] in linked
                   for e in pr['events'] if C.J.rounds_of(e) or e['kind'] == 'merge']
    C.require(all(C.time(at) <= C.time(when) for when in known_work), 'assignment after known work/push')
    after = copy.deepcopy(bundle)
    arm = 'candidate' if ticket % 2 else 'old'
    after['assignments'].append(dict(ticket=ticket, arm=arm, assigned_at=at,
        work_started_at=None, revision=copy.deepcopy(bundle['experiment']['arms'][arm]['revision']),
        preregistration_hash=C.preregistration_digest(bundle['preregistration'])))
    C.validate_transition(bundle, after, journey)
    return after



def _source(bundle, url):
    for key, known in bundle['sources'].items():
        if known == url:
            return key
    key = f"s{max((int(k[1:]) for k in bundle['sources']), default=0)+1}"
    bundle['sources'][key] = url
    return key


def canonical_rounds(journey):
    """Validate source ownership across every PR before returning any counts."""
    owners, rounds = {}, {}
    for pr in journey['pull_requests']:
        unique = {}
        for event in pr['events']:
            if event['kind'] != 'verdict':
                continue
            source = journey['sources'][event['source']]
            semantic = (pr['number'], event['at'], event['head'], event['verdict'],
                        event['independent'], event['duplicate_of'] is not None)
            C.require(source not in owners or owners[source] == semantic,
                      'conflicting verdict source ownership or meaning')
            owners[source] = semantic
            if C.J.rounds_of(event):
                unique.setdefault(source, event)
        rounds[pr['number']] = list(unique.values())
    return rounds


def validate(bundle, journey):
    C.validate(bundle, journey)
    canonical_rounds(journey)


def independent_rounds(pr, journey):
    """Identical deliveries count once, with globally validated source ownership."""
    return iter(canonical_rounds(journey)[pr['number']])


def rounds_window(bundle, journey, arm, *, at):
    """Active assigned tickets and mean rounds per active PR in (at-window,at]."""
    rounds = canonical_rounds(journey)
    now = C.time(at)
    left = now - timedelta(hours=bundle['preregistration']['stopping']['window_hours'])
    assignments = {a['ticket']: a for a in bundle['assignments'] if a['arm'] == arm}
    counts, exposed_tickets = [], set()
    for pr in journey['pull_requests']:
        eligible = [assignments[t] for t in pr['tickets'] if t in assignments]
        if not eligible:
            continue
        count = sum(C.J.rounds_of(e) and left < C.time(e['at']) <= now
                    and any(C.time(a['assigned_at']) <= C.time(e['at']) for a in eligible)
                    for e in rounds[pr['number']])
        if count:
            counts.append(count)
            for a in eligible:
                if any(left < C.time(e['at']) <= now and C.time(a['assigned_at']) <= C.time(e['at'])
                       for e in rounds[pr['number']]):
                    exposed_tickets.add(a['ticket'])
    return len(exposed_tickets), sum(counts)/len(counts) if counts else None


def safety_stops(bundle, journey, *, at):
    """Replay event times, retaining the first stop of each kind/arm, even late."""
    validate(bundle, journey)
    now = C.time(at)
    p = bundle['preregistration']
    C.require(p is not None, 'safety requires preregistration')
    rounds = canonical_rounds(journey)
    assignments = {a['ticket']: a for a in bundle['assignments']}
    prs = {pr['number']: pr for pr in journey['pull_requests']}
    stops = []
    for arm in C.ARMS:
        arm_stops = []
        for m in bundle['journey']['measurements']:
            exposed = [assignments[t] for t in prs[m['pr']]['tickets']
                       if t in assignments and assignments[t]['arm'] == arm]
            if not exposed:
                continue
            for event in m['defects']['events']:
                if event['kind'] != 'main-red':
                    continue
                observation = event
                if event['attribution'] == 'unknown':
                    observation = next((r for r in m['defects']['resolutions']
                                        if r['key'] == event['key']), event)
                if observation['attribution'] != 'attributable':
                    continue
                when = observation['at']
                affected = [a for a in exposed if C.time(a['assigned_at']) <= C.time(event['at'])]
                if C.time(when) <= now and affected:
                    arm_stops.append(dict(kind='main-red', arm=arm, at=when,
                        source=observation['source'], exposed=len(affected), observed=1))
        # Evaluate every incoming verdict time, not just the latest clock value.
        # Repeated delivery and snapshot-local ids therefore add no extra rounds.
        verdicts = {e['at']: e for pr in journey['pull_requests']
                    if any(t in assignments and assignments[t]['arm'] == arm for t in pr['tickets'])
                    for e in rounds[pr['number']] if C.time(e['at']) <= now}
        # Expiry can raise the active-PR mean by removing a low-round PR.
        # These are calculation boundaries, not scheduled wakeups or a timer.
        for event in list(verdicts.values()):
            expiry = C.time(event['at']) + timedelta(hours=p['stopping']['window_hours'])
            if expiry.microsecond:
                expiry = expiry.replace(microsecond=0) + timedelta(seconds=1)
            if expiry <= now:
                verdicts.setdefault(expiry.strftime('%Y-%m-%dT%H:%M:%SZ'), event)
        verdicts = [(when, verdicts[when]) for when in sorted(verdicts)]
        rule = p['stopping']
        for when, event in verdicts:
            exposed, mean = rounds_window(bundle, journey, arm, at=when)
            if exposed >= rule['minimum_exposed'] and mean >= 2*rule['rounds_reference']:
                arm_stops.append(dict(kind='doubled-rounds', arm=arm, at=when,
                    source=_source(bundle, journey['sources'][event['source']]),
                    exposed=exposed, observed=mean))
                break
        for kind in ('main-red', 'doubled-rounds'):
            matching = [s for s in arm_stops if s['kind'] == kind]
            if matching:
                stops.append(min(matching, key=lambda s: s['at']))
    return sorted(stops, key=lambda s: (s['at'], s['arm'], s['kind']))


def _retained_rounds(journey):
    # Compare stable source URLs and semantic fields, never local event ids.
    return {(pr['number'], journey['sources'][e['source']], e['at'], e['head'], e['verdict'])
            for pr in journey['pull_requests'] for e in pr['events'] if C.J.rounds_of(e)}


def transition(before, after, before_journey, journey):
    C.validate_transition(before, after, before_journey, journey)
    canonical_rounds(before_journey)
    canonical_rounds(journey)
    if any(d['stages']['live']['status'] not in ASSIGNABLE_LIVE for d in (before, after)):
        C.require(len(after['assignments']) == len(before['assignments']),
                  'terminal live stage: no new assignments')
    assigned = {a['ticket'] for a in before['assignments']}
    current_prs = {pr['number']: pr for pr in journey['pull_requests']}
    for pr in before_journey['pull_requests']:
        C.require(set(pr['tickets']) & assigned == set(current_prs[pr['number']]['tickets']) & assigned,
                  'established assignment/PR exposure association changed')
    C.require(_retained_rounds(before_journey) <= _retained_rounds(journey),
              'known independent rounds removed or rewritten')
    if before['result'] is not None:
        C.require(after['assignments'] == before['assignments'], 'terminal result: no resumption')


def samples(bundle, journey, *, at):
    """Reconcile every assigned unit; ambiguous/shared PRs keep unknown estimates."""
    now = C.time(at)
    tickets = {t['ticket']: t for t in journey['tickets']}
    measurements = {m['pr']: m for m in bundle['journey']['measurements']}
    result, rows = {}, {arm: [] for arm in C.ARMS}
    for arm in C.ARMS:
        sample = dict(assigned=0, merged=0, open=0, closed_unmerged=0, unknown_timing=0, mature_defects=0)
        for a in bundle['assignments']:
            if a['arm'] != arm:
                continue
            C.require(C.time(a['assigned_at']) <= now, 'analysis before assignment')
            sample['assigned'] += 1
            t = tickets[a['ticket']]
            linked = [measurements[n] for n in t['pull_requests']]
            merged = [m for m in linked if m['merge']['status'] == 'verified' and C.time(m['merge']['at']) <= now]
            unverified_merge = t['state'] == 'merged' and (not linked or any(m['merge']['status'] == 'unknown' for m in linked))
            # v1 has current state, not a sourced closure time. Nonmerges
            # remain right censored at this cutoff, including current closures.
            category = 'merged' if merged or unverified_merge else 'open'
            sample[category] += 1
            m = linked[0] if len(linked) == 1 else None
            push = m['first_push'] if m else None
            known = (push is not None and push['status'] == 'observed' and C.time(push['at']) <= now
                     and not unverified_merge)
            sample['unknown_timing'] += not known
            mature = bool(merged and m and m['defects']['status'] == 'mature'
                          and C.time(m['merge']['at'])+timedelta(hours=bundle['experiment']['defect_policy']['followup_hours']) <= now)
            sample['mature_defects'] += mature
            rows[arm].append(dict(assignment=a, ticket=t, measurement=m, category=category,
                                  timing_known=known, mature=mature,
                                  current_closed_unmerged=t['state'] == 'closed' and category != 'merged'))
        result[arm] = sample
    return result, rows


def unknown_effect(unit):
    return dict(unit=unit, old=None, candidate=None, delta=None, percent=None, interval=None)


def advance(before, before_journey, after, journey, *, at):
    """Consume injected EB facts; fill starts, append deviations and persist harm."""
    transition(before, after, before_journey, journey)
    C.require(before['assignments'] == after['assignments'], 'use assign for new assignments')
    C.require(before['result'] == after['result'], 'cannot inject an analysis or stop summary')
    out = copy.deepcopy(after)
    tickets = {t['ticket']: t for t in journey['tickets']}
    measurements = {m['pr']: m for m in out['journey']['measurements']}
    for a in out['assignments']:
        linked = tickets[a['ticket']]['pull_requests']
        for m in (measurements[pr] for pr in linked):
            push = m['first_push']
            if m['pr'] in linked and push['status'] == 'observed' and C.time(push['at']) < C.time(a['assigned_at']):
                deviation = dict(ticket=a['ticket'], kind='other', material=True,
                                 source=push['source'], actual_revision=None)
                if deviation not in out['deviations']:
                    out['deviations'].append(deviation)
    if before['result'] is not None:
        transition(before, out, before_journey, journey)
        return out
    for a in out['assignments']:
        known = [e['at'] for e in tickets[a['ticket']]['events']
                 if e['kind'] == 'builder_start' and C.time(e['at']) <= C.time(at)]
        if known and a['work_started_at'] is None:
            a['work_started_at'] = min(known)
    stops = safety_stops(out, journey, at=at)
    if stops:
        sample, _ = samples(out, journey, at=at)
        out['result'] = dict(at=at, preregistration_hash=C.preregistration_digest(out['preregistration']),
            status='stopped', verdict='harm', samples=sample,
            effects={name: unknown_effect(unit) for name, unit in
                     (('time','hours'),('rounds','rounds'),('defects','proportion'))}, stops=stops)
    transition(before, out, before_journey, journey)
    return out


def save_checkpoint(path, bundle, journey, *, expected=None):
    """Atomically persist the existing bundle plus its explicit bound journey.

    expected is the digest of the prior {bundle,journey} pair, not a moving file
    timestamp. A lock excludes competing writers; a crash leaves the lock for
    explicit inspection instead of authorizing a silent retry.
    """
    validate(bundle, journey)
    path = Path(path)
    C.require(not path.is_symlink(), 'symlink checkpoint refused')
    lock = path.with_name(path.name+'.lock')
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    temporary = None
    try:
        os.close(fd)
        if path.exists():
            previous = C.read(path)
            C.require(expected is not None and C.digest(previous) == expected, 'checkpoint changed: expected digest required')
            C.fields(previous, 'bundle journey', 'checkpoint')
            transition(previous['bundle'], bundle, previous['journey'], journey)
        else:
            C.require(expected is None, 'expected checkpoint missing')
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.'+path.name, delete=False) as f:
            temporary = Path(f.name)
            json.dump(dict(bundle=bundle, journey=journey), f, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
        temporary = None
        dirfd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.unlink()


def load_checkpoint(path):
    data = C.read(Path(path))
    C.fields(data, 'bundle journey', 'checkpoint')
    validate(data['bundle'], data['journey'])
    return data['bundle'], data['journey']


def handback_check(bundle, journey, record, current, *, at, safeguards):
    """Offline precheck assessment; never an independent verdict or permission."""
    policy(safeguards)
    validate(bundle, journey)
    spec = importlib.util.spec_from_file_location('precheck', HERE.parents[1] / 'skills-eval/precheck/test_contract.py')
    precheck = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(precheck)
    precheck.validate_request(current)
    ref = current['experiment']
    a = next((a for a in bundle['assignments'] if a['ticket'] == current['binding']['ticket']), None)
    C.require(a is not None and ref is not None, 'missing experiment assignment binding')
    C.require(ref['arm'] == a['arm'] and ref['cf4_refs'] == bundle['preregistration']['cf4_refs'],
              'precheck assignment/protocol mismatch')
    return precheck.assess(record, current, bundle, journey, at=at)
