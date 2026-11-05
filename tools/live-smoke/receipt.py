#!/usr/bin/env python3
"""Candidate-bound smoke and risk receipts from a runner checkpoint (#1844, RL3).

`produce` reads the approved kit, the runner's owner-only checkpoint and one
`openwiz.release-candidate.v1` document, and prints the contract's `smoke`
and risk gate receipts (contracts/release-candidate.v1.md, "Gate receipts and
live interface"), with each receipt's complete inputs. `check` is the live-gate
reading the release command applies: only a live, finished, passing receipt
bound to this exact candidate, artifacts, approved kit and scope passes.

The kit's `release` section declares, inside the approved kit digest:
`scope` (throwaway targets, write-step counts per claim, the App permissions
the existing grant already has, a spending cap in cents), the candidate
`products` the kit's pinned programs are, `coverage` (the bounded steps that
exercise each included version's promise end to end), `risk` (the steps that
check send, new, App permissions and spending) and known `gaps`. Nothing here
grants, widens or runs anything: it reads files and hashes. Standard library only.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys

_SPEC = importlib.util.spec_from_file_location(
    'live_smoke_runner', Path(__file__).resolve().with_name('smoke.py'))
smoke = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(smoke)

SCHEMA = 'openwiz.live-smoke-receipts.v1'
PRESERVE = 'openwiz.live-smoke-evidence.v1'
RISKS = ('send', 'new', 'app_permissions', 'spending')
RECEIPT = {'candidate_sha256', 'inputs_sha256', 'artifacts_sha256', 'kit_sha256', 'evidence_class',
           'status', 'started_at', 'finished_at', 'evidence', 'coverage', 'gaps'}
GATES = ('smoke',) + RISKS
# The kit claim whose steps can check each risk. This kit has no spending
# check, so a candidate that changes spending refuses as `risk_missing`.
RISK_CLAIM = {'send': 'send', 'new': 'new', 'app_permissions': 'app', 'spending': None}
PRODUCTS = ('cli', 'server', 'service', 'web', 'runtime')
TARGETS = ('aarch64-apple-darwin', 'x86_64-apple-darwin', 'x86_64-unknown-linux-gnu')
PC_GAP = 'Agent-run PC smoke only: no Mac, real-device, real-radio or WebKit observation.'
NOT_LIVE_GAP = 'Fixture or dry-run evidence: diagnostic only, never a live result.'
RECORD = re.compile(r'(https://github\.com/jparker2006/ClosedWiz/(issues|pull)/[1-9][0-9]*'
                    r'#issuecomment-[1-9][0-9]*|[a-z][a-z0-9-]{0,31}:[A-Za-z0-9._-]{1,128})')


class Refusal(Exception):
    pass


def sha(value):
    """The contract's canonical JSON digest."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False).encode('utf-8')).hexdigest()


def _names(value, empty=False):
    return (type(value) is list and (empty or value) and len(value) == len(set(map(repr, value)))
            and all(type(v) is str and v for v in value))


def release_section(kit):
    """The kit's own declared release scope, coverage and risk steps."""
    section = kit.get('release')
    if type(section) is not dict or set(section) != {'scope', 'products', 'coverage', 'risk', 'gaps'}:
        raise Refusal('invalid_release')
    scope = section['scope']
    if (type(scope) is not dict or set(scope) != {'targets', 'writes', 'app_permissions', 'spending_cents'}
            or not _names(scope['targets']) or not _names(scope['app_permissions'], empty=True)
            or any(not re.fullmatch('[a-z][a-z_]*:(read|write)', p) for p in scope['app_permissions'])
            or type(scope['writes']) is not dict
            or any(c not in smoke.CLAIMS or not smoke.integer(n, 0, 1000) for c, n in scope['writes'].items())
            or not smoke.integer(scope['spending_cents'], 0, 10**8)):
        raise Refusal('invalid_scope')
    steps = {s['id']: s for s in kit['steps'] if s['kind'] != 'event'}
    products, coverage = section['products'], section['coverage']
    if (type(products) is not list or not products
            or any(type(p) is not dict or set(p) != {'product', 'target'} or p['product'] not in PRODUCTS
                   or p['target'] not in TARGETS for p in products)
            or len({(p['product'], p['target']) for p in products}) != len(products)
            or type(coverage) is not list or not coverage
            or any(type(r) is not dict or set(r) != {'version', 'promise', 'steps'}
                   or type(r['version']) is not str or not re.fullmatch(r'0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', r['version'])
                   or type(r['promise']) is not str or not r['promise']
                   or not _names(r['steps']) or not set(r['steps']) <= steps.keys() for r in coverage)
            or len({(r['version'], r['promise']) for r in coverage}) != len(coverage)
            or not _names(section['gaps'])):
        raise Refusal('invalid_release')
    risk = section['risk']
    if type(risk) is not dict or set(risk) != set(RISKS):
        raise Refusal('invalid_release')
    for category, ids in risk.items():
        if not _names(ids, empty=True) or not set(ids) <= steps.keys():
            raise Refusal('invalid_release')
        chosen = [steps[i] for i in ids]
        if (any(s['claim'] != RISK_CLAIM[category] for s in chosen)
                or (chosen and category in ('send', 'new') and not any(s['kind'] == 'write' for s in chosen))):
            raise Refusal('risk_mismatch')
    for claim in smoke.CLAIMS:
        if sum(s['kind'] == 'write' and s['claim'] == claim for s in kit['steps']) > scope['writes'].get(claim, 0):
            raise Refusal('scope_exceeded')
    return section


def _status(states, finished):
    if 'fail' in states:
        return 'fail'
    if 'attempting' in states:
        return 'uncertain'
    return 'pass' if all(s == 'pass' for s in states) and finished else 'incomplete'


def _sealed(candidate):
    if (type(candidate) is not dict or candidate.get('schema') != 'openwiz.release-candidate.v1'
            or type(candidate.get('candidate')) is not dict
            or sha(candidate['candidate']) != candidate.get('candidate_sha256')):
        return False
    return True


def evidence(state_dir, kit, state):
    """Replay the run's hash-chained journal; it must yield the checkpoint exactly.

    The replay (smoke.replay) refuses an out-of-order lifecycle, a pass whose
    exit is not the step's expected exit, and a pass whose recorded bounded
    observations fail the step's own checks. A checkpoint is resume state; alone
    it never shows a run happened. Returns the journal digest and consumed writes.
    """
    try:
        raw, events = smoke.read_journal(Path(state_dir))
        replayed = smoke.replay(kit, events)
    except FileNotFoundError as error:
        raise Refusal('evidence_missing') from error
    except smoke.Refusal as error:
        raise Refusal('evidence_mismatch') from error
    start = events[0]
    if (start['kit'] != smoke.digest(kit) or start['mode'] != kit['mode']
            or start['source'] != (kit['source']['head'] if 'source' in kit else None)):
        raise Refusal('evidence_mismatch')
    if kit['mode'] == 'live' and (start['runner'] != kit['artifacts'].get(str(Path(smoke.__file__).resolve()))
                                  or start['restriction'] != kit['artifacts'].get(str(smoke.RESTRICTION))):
        raise Refusal('evidence_mismatch')
    if replayed != state:
        raise Refusal('evidence_mismatch')
    return hashlib.sha256(raw).hexdigest(), dict(replayed['writes'])


def preserved_line(journal_sha, candidate_sha, kit_sha):
    """The one line the run's private record must carry, after the run finished."""
    return f'{PRESERVE} journal={journal_sha} candidate={candidate_sha} kit={kit_sha}'


def produce(kit_path, state_dir, candidate, record):
    """The smoke receipt and every required risk receipt, or a refusal."""
    if type(record) is not str or not RECORD.fullmatch(record):
        raise Refusal('invalid_record')
    if not _sealed(candidate):
        raise Refusal('invalid_candidate')
    body = candidate['candidate']
    try:
        kit = smoke.load_kit(Path(kit_path))
        smoke.verify_artifacts(kit)
    except smoke.Refusal as error:
        raise Refusal(str(error)) from error
    section = release_section(kit)
    if smoke.digest(kit) != body['kit']['sha256']:
        raise Refusal('kit_mismatch')
    if sha(section['scope']) != body['kit']['scope_sha256']:
        raise Refusal('scope_mismatch')
    tested = []
    pinned = set(kit['artifacts'].values())
    for item in section['products']:
        match = [p for p in body['products']
                 if p['identity']['product'] == item['product'] and p['identity']['target'] == item['target']]
        if len(match) != 1 or match[0]['payload_sha256'] not in pinned:
            raise Refusal('product_mismatch')
        tested.append(dict(item, payload_sha256=match[0]['payload_sha256']))
    promises = [(v['version'], p) for v in body['included_versions'] for p in v['promises']]
    rows = {(r['version'], r['promise']): r['steps'] for r in section['coverage']}
    if sorted(promises) != sorted(rows) or len(set(promises)) != len(promises):
        raise Refusal('coverage_mismatch')
    for category in RISKS:
        required = body['risk'][category]['required']
        if required not in ('yes', 'no'):
            raise Refusal('risk_unknown')
        if required == 'yes' and not section['risk'][category]:
            raise Refusal('risk_missing')

    state_dir = Path(state_dir)
    try:
        ran = (state_dir / 'checkpoint.json').exists()
        state = smoke.load_state(state_dir, kit) if ran else smoke.initial(kit)
    except smoke.Refusal as error:
        raise Refusal(str(error)) from error
    evidence_class = kit['mode'] if ran else 'dry-run'
    if ran:
        # Receipts exist only for the candidate this run was bound to.
        if state['candidate'] is None:
            raise Refusal('unbound_run')
        if state['candidate'] != candidate['candidate_sha256']:
            raise Refusal('candidate_changed')
        journal_sha, consumed = evidence(state_dir, kit, state)
    else:
        journal_sha, consumed = None, {}
    if any(n > section['scope']['writes'].get(c, 0) for c, n in consumed.items()):
        raise Refusal('scope_exceeded')
    # A write attempted without a known result stays uncertain, never incomplete.
    states = {s['id']: 'attempting' if s['kind'] == 'write' and item['state'] == 'incomplete' else item['state']
              for s, item in zip(kit['steps'], state['steps']) if s['kind'] != 'event'}
    whole = _status(list(states.values()), state['times']['finished'])
    finished = state['times']['finished'] if whole == 'pass' else None
    verdict = whole if whole in ('pass', 'fail') else 'incomplete'
    run_report = smoke.report(kit, state, verdict, state['reason'] if ran else 'dry_run')
    gaps = section['gaps'] + [PC_GAP] + ([] if evidence_class == 'live' else [NOT_LIVE_GAP])
    base = {'candidate_sha256': candidate['candidate_sha256'], 'artifacts_sha256': sha(body['artifacts']),
            'kit_sha256': smoke.digest(kit), 'scope_sha256': sha(section['scope']),
            'evidence_class': evidence_class, 'tested_products': tested, 'report_sha256': sha(run_report),
            'restriction': 'expect-plan', 'gaps': section['gaps'],
            'journal_sha256': journal_sha, 'writes_consumed': consumed,
            'steps': [{'id': s['id'], 'claim': s['claim'], 'kind': s['kind'], 'state': item['state']}
                      for s, item in zip(kit['steps'], state['steps'])],
            'coverage': [{'version': v, 'promise': p, 'steps': rows[(v, p)]} for v, p in promises]}

    def receipt(gate, inputs, ids, covered):
        status = _status([states[i] for i in ids], state['times']['finished'])
        return {'candidate_sha256': candidate['candidate_sha256'], 'inputs_sha256': sha(inputs),
                'artifacts_sha256': base['artifacts_sha256'], 'kit_sha256': base['kit_sha256'],
                'evidence_class': evidence_class, 'status': status,
                'started_at': state['times']['started'], 'finished_at': finished if status == 'pass' else None,
                'evidence': {'record': record, 'sha256': journal_sha or sha(run_report)},
                'coverage': [{'version': v, 'promise': p,
                              'outcome': _status([states[i] for i in rows[(v, p)]], state['times']['finished'])}
                             for v, p in covered],
                'gaps': gaps}

    gates, inputs = {}, {}
    inputs['smoke'] = dict(base, gate='smoke')
    gates['smoke'] = receipt('smoke', inputs['smoke'], list(states), promises)
    for category in RISKS:
        ids = section['risk'][category]
        if body['risk'][category]['required'] == 'no':
            gates[category] = inputs[category] = None
            continue
        inputs[category] = dict(base, gate=category, risk_steps=ids,
                                classification=body['risk'][category])
        covered = [(v, p) for v, p in promises if set(rows[(v, p)]) & set(ids)]
        gates[category] = receipt(category, inputs[category], ids, covered)
    return {'schema': SCHEMA, 'candidate_sha256': candidate['candidate_sha256'],
            'gates': gates, 'inputs': inputs,
            'preserve': preserved_line(journal_sha, candidate['candidate_sha256'], base['kit_sha256'])
            if journal_sha else None}


def accept(gate, doc, candidate, kit_path, state_dir, resolve=None):
    """Return only when `gate`'s receipt satisfies a live gate for `candidate`.

    The receipt's own fields are never enough: it must be exactly what its
    evidence (the approved kit, checkpoint and journal) produces today, and
    `resolve(record)` must independently return the preserved private record
    (`{'body': str, 'created_at': int}`), created at or after the run finished
    and carrying this journal's digest line. No resolver: refused.
    """
    if gate not in GATES:
        raise Refusal('unknown_gate')
    if not _sealed(candidate):
        raise Refusal('stale')
    if (type(doc) is not dict or doc.get('schema') != SCHEMA or type(doc.get('gates')) is not dict
            or type(doc.get('inputs')) is not dict):
        raise Refusal('invalid_receipts')
    body = candidate['candidate']
    if gate != 'smoke' and body['risk'][gate]['required'] not in ('yes', 'no'):
        raise Refusal('risk_unknown')
    found, inputs = doc['gates'].get(gate), doc['inputs'].get(gate)
    if found is None or type(inputs) is not dict:
        raise Refusal('missing')
    if type(found) is not dict or set(found) != RECEIPT or type(found['evidence']) is not dict:
        raise Refusal('invalid_receipts')
    if found.get('evidence_class') != 'live':
        raise Refusal('not_live')
    if (found.get('status') != 'pass' or type(found.get('finished_at')) is not int
            or type(found.get('started_at')) is not int or found['finished_at'] < found['started_at']):
        raise Refusal('not_pass')
    if (found.get('candidate_sha256') != candidate['candidate_sha256']
            or found.get('artifacts_sha256') != sha(body['artifacts'])
            or found.get('kit_sha256') != body['kit']['sha256']):
        raise Refusal('stale')
    if sha(inputs) != found.get('inputs_sha256'):
        raise Refusal('inputs_mismatch')
    payloads = {(p['identity']['product'], p['identity']['target']): p['payload_sha256'] for p in body['products']}
    if (inputs.get('gate') != gate or inputs.get('evidence_class') != 'live'
            or inputs.get('candidate_sha256') != candidate['candidate_sha256']
            or inputs.get('artifacts_sha256') != found['artifacts_sha256']
            or inputs.get('kit_sha256') != body['kit']['sha256']
            or inputs.get('scope_sha256') != body['kit']['scope_sha256']
            or inputs.get('restriction') != 'expect-plan'
            or type(inputs.get('tested_products')) is not list or not inputs['tested_products']
            or any(type(p) is not dict or payloads.get((p.get('product'), p.get('target'))) != p.get('payload_sha256')
                   for p in inputs['tested_products'])
            or (gate != 'smoke' and inputs.get('classification') != body['risk'][gate])):
        raise Refusal('stale')
    promises = [{'version': v['version'], 'promise': p} for v in body['included_versions'] for p in v['promises']]
    if gate == 'smoke':
        expected = promises
    else:
        risk_steps = set(inputs.get('risk_steps') or [])
        expected = [{'version': r['version'], 'promise': r['promise']} for r in inputs.get('coverage', [])
                    if set(r['steps']) & risk_steps]
        if not risk_steps or not expected or any(row not in promises for row in expected):
            raise Refusal('coverage_mismatch')
    if found.get('coverage') != [dict(row, outcome='pass') for row in expected]:
        raise Refusal('coverage_mismatch')
    gaps = found.get('gaps')
    if (type(gaps) is not list or type(inputs.get('gaps')) is not list or not inputs['gaps']
            or not set(inputs['gaps']) | {PC_GAP} <= set(gaps)):
        raise Refusal('gaps_missing')
    if kit_path is None or state_dir is None:
        raise Refusal('evidence_mismatch')
    again = produce(kit_path, state_dir, candidate, found['evidence'].get('record'))
    if again['gates'][gate] != found or again['inputs'][gate] != inputs:
        raise Refusal('evidence_mismatch')
    if resolve is None:
        raise Refusal('evidence_unresolved')
    try:
        preserved = resolve(found['evidence']['record'])
    except (Refusal, OSError, ValueError, KeyError, TypeError) as error:
        raise Refusal('evidence_unresolved') from error
    if (type(preserved) is not dict or type(preserved.get('body')) is not str
            or type(preserved.get('created_at')) is not int
            or again['preserve'] not in preserved['body'].splitlines()
            or preserved['created_at'] < found['finished_at']):
        raise Refusal('evidence_unresolved')


def github_record(record):
    """Resolve a private-record comment pointer through gh (read-only)."""
    import datetime
    import subprocess
    match = re.fullmatch(r'https://github\.com/jparker2006/ClosedWiz/(?:issues|pull)/[1-9][0-9]*'
                         r'#issuecomment-([1-9][0-9]*)', record)
    if not match:
        raise Refusal('evidence_unresolved')
    done = subprocess.run(['gh', 'api', f'repos/jparker2006/ClosedWiz/issues/comments/{match[1]}'],
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    if done.returncode != 0:
        raise Refusal('evidence_unresolved')
    comment = smoke.decode(done.stdout)
    created = datetime.datetime.strptime(comment['created_at'], '%Y-%m-%dT%H:%M:%SZ')
    return {'body': comment['body'],
            'created_at': int(created.replace(tzinfo=datetime.timezone.utc).timestamp())}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='action', required=True)
    make = sub.add_parser('produce')
    make.add_argument('--kit', required=True, type=Path)
    make.add_argument('--state', required=True, type=Path)
    make.add_argument('--candidate', required=True, type=Path)
    make.add_argument('--record', required=True)
    check = sub.add_parser('check')
    check.add_argument('--gate', required=True)
    check.add_argument('--receipts', required=True, type=Path)
    check.add_argument('--candidate', required=True, type=Path)
    check.add_argument('--kit', required=True, type=Path)
    check.add_argument('--state', required=True, type=Path)
    args = parser.parse_args()
    try:
        candidate = smoke.decode(args.candidate.read_bytes())
        if args.action == 'produce':
            print(json.dumps(produce(args.kit, args.state, candidate, args.record), sort_keys=True))
            return 0
        accept(args.gate, smoke.decode(args.receipts.read_bytes()), candidate, args.kit, args.state,
               github_record)
        print(json.dumps({'gate': args.gate, 'accepted': True}, sort_keys=True))
        return 0
    except (Refusal, smoke.Refusal) as error:
        reason = str(error)
    except (OSError, TypeError, ValueError, KeyError, AttributeError):
        # Never interpolate an exception: it may contain private paths.
        reason = 'invalid_input'
    if args.action == 'check' and reason != 'invalid_input':
        print(json.dumps({'gate': args.gate, 'accepted': False, 'reason': reason}, sort_keys=True))
        return 1
    print(json.dumps({'schema': SCHEMA, 'refused': reason}, sort_keys=True))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
