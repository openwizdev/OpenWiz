"""The cross-field checks of contracts/first-hour.v1.md (#2200).

`check(document)` and `check_text(text)` return a Report of three sorted lists of codes:
problems (the document is refused), failures (the attempt failed) and unproven (not
proven yet). The contract's code table names every code. Stdlib only; the schema subset
validator is tools/skills-eval/records.py's. A seam for #2204, #2222 and #2207's result
validation: they load this file by path and report its codes.
"""
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location('first_hour_records', ROOT / 'tools/skills-eval/records.py')
records = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records)
strict_json = records.strict_json
SCHEMA = strict_json((ROOT / 'contracts/first-hour.v1.schema.json').read_text())

# The contract's stage table: each stage, in order, and the one basis that establishes it.
ESTABLISH = {
    'public_instruction': 'instruction_opened',
    'install': 'install_result',
    'connections': 'setup_component_verified',
    'idea': 'idea_saved',
    'spec_confirmation': 'decision_saved',
    'plan_approval': 'decision_saved',
    'fleet': 'agents_running',
    'review': 'review_approve_exact_head',
    'ci': 'ci_green_exact_head',
    'merge': 'merge_read_back',
}
SEAT_BASIS = 'harness_run_observed'
LIMIT_MS = 3600000
TEN_MINUTES_MS = 600000
PREPARED = ('prepared_plan', 'private_instruction')


class Report:
    def __init__(self, problems=(), failures=(), unproven=()):
        self.problems = sorted(set(problems))
        self.failures = sorted(set(failures))
        self.unproven = sorted(set(unproven))


def check_text(text):
    try:
        doc = strict_json(text)
    except ValueError:
        return Report(['not_strict_json'])
    return check(doc)


def check(doc):
    if records.schema_errors(doc, SCHEMA, SCHEMA):
        return Report(['schema'])
    p, f, u = [], [], []
    live = doc['proof_class'] == 'live'
    if not live:
        u.append('not_live')
    if live and doc['synthetic_assumptions']:
        p.append('synthetic_live')
    if not live and not doc['synthetic_assumptions']:
        p.append('synthetic_unlabelled')
    if live and doc['private_record'] is None:
        p.append('live_without_private_record')
    if 'unknown' in doc['candidate']:
        u.append('candidate_unknown')
    if doc['kind'] == 'result':
        _result(doc, p, f, u)
    else:
        _case(doc['case'], 'case', True, p, f, u)
    if f and doc['verdict'] != 'fail':
        p.append('failure_not_reported')
    if doc['verdict'] == 'pass':
        if not live:
            p.append('non_live_pass')
        if u:
            p.append('unproven_pass')
    return Report(p, f, u)


def _known(fact):
    return fact.get('known')


def _result(doc, p, f, u):
    if 'unknown' in doc['repository']:
        u.append('repository_unknown')
    start, end = _known(doc['clock']['started_at_ms']), _known(doc['clock']['ended_at_ms'])
    timed = start is not None and end is not None
    if not timed:
        u.append('clock_unknown')
    elif end < start:
        p.append('clock_order')
        timed = False
    elif end - start > LIMIT_MS:
        f.append('hour_missed')

    def inside(t):
        return not timed or start <= t <= end

    def established(name, state, evidence, basis):
        strong = [e for e in evidence if e['basis'] == basis]
        if state != 'verified':
            return
        if not strong:
            p.append(f'stage_weak_evidence:{name}' if basis != SEAT_BASIS else f'seat_weak_evidence:{name}')
        elif not any(inside(e['at_ms']) for e in strong):
            p.append(f'stale_evidence:{name}')

    stages = doc['stages']
    if [s['id'] for s in stages] != list(ESTABLISH):
        p.append('stage_order')
    for s in stages:
        established(s['id'], s['state'], s['evidence'], ESTABLISH[s['id']])
        if s['state'] in ('failed', 'refused'):
            f.append(f"stage_failed:{s['id']}")
        elif s['state'] != 'verified':
            u.append(f"stage_unverified:{s['id']}")
    for role in ('builder', 'reviewer'):
        seat = doc[role]
        established(role, seat['usable'], seat['evidence'], SEAT_BASIS)
        if seat['usable'] != 'verified':
            u.append(f'seat_unusable:{role}')
    if doc['builder']['harness'] == doc['reviewer']['harness']:
        u.append('reviewer_not_independent')
    for i, w in enumerate(doc['waits']):
        if w['ended_at_ms'] < w['started_at_ms'] or not (inside(w['started_at_ms']) and inside(w['ended_at_ms'])):
            p.append(f'outside_clock:wait:{i}')
    for i, h in enumerate(doc['help']):
        if not inside(h['at_ms']):
            p.append(f'outside_clock:help:{i}')
        if h['source'] in PREPARED:
            u.append('prepared_help')
    final = _index(doc['operations'], lambda op: (op['operation_id'],),
                   'duplicate_operation:operations', p)
    retained = _index(doc['retained_work'], lambda w: (w['kind'], w['id']),
                      'duplicate_work:retained_work', p)
    if final is not None:
        for op in final.values():
            _operation(op, None, op['phase'], p, f)
            if op['phase'] == 'uncertain':
                u.append(f"operation_uncertain:{op['operation_id']}")
    history, immutable = {}, {}
    for i, case in enumerate(doc['interruptions']):
        checked = _case(case, str(i), False, p, f, u)
        if checked is None:
            continue  # Ambiguous inventories have already refused the record.
        before, after, operations = checked
        _immutable_work(before, immutable, p)
        _immutable_work(after, immutable, p)
        for key, op in operations.items():
            history[key] = _advance(history.get(key), op, op['phase_after'], p, f)
    if retained is not None:
        _immutable_work(retained, immutable, p)
    if final is not None:
        for key, previous in history.items():
            if key not in final:
                u.append(f'final_operation_missing:{key[0]}')
                unresolved = previous[2]
            else:
                _, _, unresolved = _advance(previous, final[key], final[key]['phase'], p, f)
            if unresolved:
                u.append(f'operation_uncertain:{key[0]}')
    for finding in doc['findings']:
        if (finding['severity'] == 'blocker' or finding['work_loss']) and finding['disposition'] != 'fixed':
            f.append(f"open_blocking_finding:{finding['id']}")
    for gap in doc['gaps']:
        if gap['claim'] in ('PR1', 'PR4'):
            u.append(f"gap:{gap['claim']}")
    for name, gate in doc['gates'].items():
        settled = gate['state'] == 'settled'
        if settled != bool(gate['producers']):
            p.append(f'gate_producers:{name}')
        if not (settled and gate['producers']):
            u.append(f'gate_unresolved:{name}')
    ten = doc['ten_minute_fleet']
    elapsed = ten['elapsed_ms']
    if not {'met': elapsed is not None and elapsed <= TEN_MINUTES_MS,
            'missed': elapsed is not None and elapsed > TEN_MINUTES_MS,
            'unmeasured': elapsed is None}[ten['state']]:
        p.append('ten_minute_inconsistent')


def _operation(op, before, after, p, f):
    """One operation's effects: `before` is None for the end-of-attempt list."""
    oid = op['operation_id']
    if op['effect_count'] > 1:
        f.append(f'duplicate_effect:{oid}')
    if op['attempts'] > 1 and op['reconciliation'] != 'provider_read_back':
        f.append(f'blind_retry:{oid}')
    if before == 'uncertain' and after != 'uncertain' and op['reconciliation'] != 'provider_read_back':
        f.append(f'uncertainty_erased:{oid}')
    if (after == 'applied') != (op['effect_count'] >= 1) and after != 'uncertain':
        p.append(f'phase_effect_mismatch:{oid}')
    if op['attempts'] == 0 and any(phase in ('applied', 'uncertain')
                                   for phase in (before, after)):
        p.append(f'phase_attempt_mismatch:{oid}')


def _index(items, key, code, p):
    """Do not select an arbitrary winner from ambiguous identity evidence."""
    result, duplicates = {}, set()
    for item in items:
        identity = key(item)
        if identity in result:
            duplicates.add(identity)
        else:
            result[identity] = item
    for identity in sorted(duplicates):
        p.append(code + ':' + ':'.join(identity))
    return None if duplicates else result


def _immutable_work(inventory, seen, p):
    for key, work in inventory.items():
        if work['kind'] not in ('commit', 'pending_operation'):
            continue
        if key in seen and seen[key] != work['content']:
            p.append('work_history_mismatch:' + ':'.join(key))
        else:
            seen[key] = work['content']


def _advance(previous, op, phase, p, f):
    """Join one intent's successive observations, then its final ledger row."""
    unresolved = op.get('phase_before') == 'uncertain'
    if previous is not None:
        prior, prior_phase, unresolved = previous
        if (op['kind'] != prior['kind'] or op['effect_count'] < prior['effect_count']
                or op['attempts'] < prior['attempts']
                or ('phase_before' in op and op['phase_before'] != prior_phase)):
            p.append(f"operation_history_mismatch:{op['operation_id']}")
    if unresolved and phase != 'uncertain':
        if op['reconciliation'] == 'provider_read_back':
            unresolved = False
        else:
            f.append(f"uncertainty_erased:{op['operation_id']}")
    return op, phase, unresolved or phase == 'uncertain'


def _case(case, label, standalone, p, f, u):
    before = _index(case['before'], lambda w: (w['kind'], w['id']),
                    f'duplicate_work:{label}:before', p)
    after = _index(case['after'], lambda w: (w['kind'], w['id']),
                   f'duplicate_work:{label}:after', p)
    operations = _index(case['operations'], lambda op: (op['operation_id'],),
                        f'duplicate_operation:{label}', p)
    if before is None or after is None or operations is None:
        return None
    if not before:
        u.append(f'recovery_work_missing:{label}')
    if not operations and case['interruption'] in ('setup_interrupted', 'lost_reply', 'repeat_approval'):
        u.append(f'recovery_operations_missing:{label}')
    for key, w in before.items():
        if w['kind'] == 'pending_operation' and (w['id'],) not in operations:
            u.append(f"recovery_operation_missing:{label}:{w['id']}")
        kept = after.get(key)
        if kept is None or kept['content'] != w['content']:
            f.append(f"work_lost:{w['kind']}:{w['id']}")
        elif case['interruption'] == 'browser_restart' and kept['basis'] == 'tab_session_storage':
            u.append(f"retention_unproven:{w['kind']}:{w['id']}")
    effects, uncertain = 0, False
    for op in operations.values():
        if ('pending_operation', op['operation_id']) not in before:
            u.append(f"recovery_intent_missing:{label}:{op['operation_id']}")
        _operation(op, op['phase_before'], op['phase_after'], p, f)
        effects += op['effect_count']
        if op['phase_after'] == 'uncertain':
            uncertain = True
            if standalone:
                u.append(f"operation_uncertain:{op['operation_id']}")
    shown = 'yes' if effects else 'unknown' if uncertain else 'no'
    if case['explanation']['took_effect'] != shown:
        p.append(f'explanation_inconsistent:{label}')
    return before, after, operations
