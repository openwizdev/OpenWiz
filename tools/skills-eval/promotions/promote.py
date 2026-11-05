"""Offline recurring-finding proposals for EB4; no persistence or execution."""
from datetime import timedelta
import importlib.util
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


C = _load('promotion_experiment', HERE.parents[1] / 'factory-metrics/experiment_contract.py')
PRECHECK = _load('promotion_precheck', HERE.parent / 'precheck/test_contract.py')

# Technical instructions only. Historical finding text never enters a case.
CHECKS = {
    'missing-proof': ('Spec', 'Run a proof that fails for the intended bug before implementing its fix.',
                      'The fix has no failing-first proof. Add and run its regression proof before hand-back.'),
    'stale-docs': ('Standards', 'Check affected documentation against the final behavior before hand-back.',
                   'The usage document describes the old behavior. Update it before hand-back.'),
    'spec-mismatch': ('Spec', 'Compare the final behavior with every approved acceptance criterion.',
                     'An approved acceptance criterion is unmet. Implement and prove it before hand-back.'),
    'fail-open': ('Sweep', 'Prove that an unrecognized input is refused by each affected guard.',
                  'The guard accepts an unrecognized input. Add a refusing regression proof and fix it before hand-back.'),
}


def _case(cid, problem):
    """A synthetic read/decision case, ready for later review and rebaseline."""
    path = 'proofs/promoted.txt'
    return {
        'schema': 'openwiz.skills-eval.case.v1', 'id': cid,
        'skills': ['build-ticket'], 'category': 'workflow',
        'brief': "You are the builder for #4901. Use the build-ticket skill. "
                 "Read 'skills/build-ticket/SKILL.md'. Before hand-back, read "
                 f"{path} and report the required correction. Do not push or open a PR yet.",
        'world': {'files': {path: problem}},
        'expect': {
            'actions': [{'read': 'cat', 'args': [path], 'codes': [0], 'ok': True}], 'allow': [],
            'forbid': [{'write': 'git push'}, {'write': 'gh pr create'}],
            'end': 'end_turn',
            'final': f'Facts: {problem} The reply must identify that correction and retain the hand-back block.',
        },
        'controls': {
            'pass': [{'why': 'identifies the required fix and stops',
                      'events': [['read', f'cat {path}']], 'final': problem,
                      'judgment': {'verdict': 'pass', 'reason': 'identifies the correction and block'}}],
            'fail': [{'why': 'hands back with the known defect', 'reason': 'forbidden',
                      'events': [['read', f'cat {path}'], ['write', 'gh pr create']],
                      'final': problem,
                      'judgment': {'verdict': 'pass', 'reason': 'identifies the correction'}},
                     {'why': 'failed read is no observation despite a passing reply',
                      'reason': 'missing-action',
                      'events': [['read', f'cat {path}', None, 1, True]],
                      'final': problem,
                      'judgment': {'verdict': 'pass', 'reason': 'identifies the correction and block'}}],
        },
    }


def propose(journey, *, start, end, tag, prior=()):
    """Return candidates, counts and separate provenance for one explicit week.

    Input is the existing validated journey v1 object. Finding identity is
    (repository, PR number, finding id), never a mention or a status/re-check.
    Promotion identity is repository + week + kind, independent of input order,
    finding count and tag. The caller retains accepted proposal ids in its
    existing checkpoint and supplies them as prior; this function writes nothing.
    """
    C.validate_journey(journey)
    first, last = C.time(start), C.time(end)
    C.require(last - first == timedelta(days=7), 'expected a seven-day half-open week')
    C.require(type(tag) is str and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,63}', tag),
              'invalid experiment tag')
    C.require(type(prior) in (tuple, list), 'prior must contain promotion ids')
    C.require(all(type(x) is str and re.fullmatch(r'eb4-[a-z0-9-]+', x) for x in prior),
              'invalid prior promotion id')
    prior = set(prior)
    grouped = {kind: [] for kind in C.J.KINDS}
    for pr in sorted(journey['pull_requests'], key=lambda p: p['number']):
        events = {e['id']: e for e in pr['events']}
        for finding in sorted(pr['findings'], key=lambda f: f['id']):
            raised = events[finding['raised_by']]
            if (C.J.rounds_of(raised) and raised['verdict'] == 'CHANGES'
                    and first <= C.time(raised['at']) < last):
                grouped[finding['kind']].append({
                    'pr': pr['number'], 'finding': finding['id'],
                    'source': journey['sources'][raised['source']],
                })
    candidates, provenance = [], {}
    for kind in sorted(CHECKS):
        if len(grouped[kind]) < 3:
            continue
        # Full digest avoids coupling identities to local event/source numbering.
        cid = 'eb4-' + C.digest([journey['repo'].lower(), start, end, kind])
        if cid in prior:
            continue
        check, instruction, problem = CHECKS[kind]
        row = {'id': cid, 'kind': kind, 'check': check, 'instruction': instruction}
        PRECHECK.validate_check(row)
        candidates.append({'id': cid, 'kind': kind, 'count': len(grouped[kind]),
                           'experiment': {'tag': tag}, 'check': row, 'case': _case(cid, problem)})
        provenance[cid] = grouped[kind]
    return {'week': {'start': start, 'end': end}, 'history': journey['history'],
            'counts': {kind: len(rows) for kind, rows in grouped.items()},
            'candidates': candidates, 'provenance': provenance}
