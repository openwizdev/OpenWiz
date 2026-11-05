#!/usr/bin/env python3
"""Complete read-only source/dry-run preparation; never applies or publishes."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan import Refusal, InventoryChanged, require, inventory, planned_map, check_map, parse_json, number, exact
from graph import READY, acyclic
from source import (Source, closure, validate_closure_record, validate_merge_proofs,
                    excluded_targets, validate_excluded_targets, read_batch)
from text import transform, check_text, compile_aliases, SOURCE, THREAD


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class SnapshotChanged(Refusal):
    def __init__(self, changes):
        self.changes = changes
        super().__init__('source: changed during collection; ' + json.dumps(changes))


def collect_source(gh, inv, records):
    source = Source(gh)
    nodes = read_batch(lambda row: source.node(row['number'], row['kind']), inv['moves'], parallel=True)
    for node in nodes:
        if node['item']['state'] != 'open':
            raise SnapshotChanged(dict(nodes=[dict(number=node['item']['number'], fields=['item.state'])],
                                       proof_sections=[], inventory_changed=True, inventory_counts=None))
    moving = set(source.nodes)
    merges, closures, approvals = {}, {}, {}
    refs = {ref for n in moving for ref in source.nodes[n]['item']['blockers']}
    refs.update(source.nodes[n]['item']['parent'] for n in moving if source.nodes[n]['item']['parent'] is not None)
    read_batch(source.node, sorted(refs), parallel=True)
    acyclic({n: [v for v in source.nodes[n]['item']['blockers'] if v in moving] for n in moving}, 'source blockers')
    acyclic({n: ([] if source.nodes[n]['item']['parent'] not in moving else [source.nodes[n]['item']['parent']])
             for n in moving}, 'source parents')
    closed = sorted({b for n in moving for b in source.nodes[n]['item']['blockers']
                     if source.nodes[b]['item']['state'] == 'closed'})

    def read_closure(blocker):
        try:
            return blocker, closure(gh, blocker, records)
        except Refusal as error:
            raise Refusal(f'source: blocker #{blocker}: {error}') from None

    for blocker, proof in read_batch(read_closure, closed, parallel=True):
        if proof['state'] == 'merged':
            merges[str(blocker)] = proof['proofs']
        else:
            closures[str(blocker)] = proof
    approvals = source.approved_graphs(moving, preparation=True)
    exclusions = excluded_targets(source, inv)
    require(set(records) == set(closures), 'source: unused or missing closure binding')
    return source, merges, closures, approvals, exclusions


def moved_template(n, kind):
    path = 'pull' if kind == 'pull_request' else 'issues'
    slot = '${openwiz:' + str(n) + '}'
    return f'moved to [OpenWiz #{slot}](https://github.com/openwizdev/openwiz/{path}/{slot})'


def operations(inv, source, merges, closures, checker, literals, exclusions, aliases=None):
    moving = {r['number'] for r in inv['moves']}
    result = []
    for row in inv['moves']:
        n, kind = row['number'], row['kind']
        node = source.nodes[n]
        item = node['item']
        path = 'pull' if kind == 'pull_request' else 'issues'
        origin = f'was [ClosedWiz #{n}]({SOURCE}/{path}/{n})'
        operation = dict(closedwiz=n, kind=kind, original_comment=moved_template(n, kind),
                         was=origin, new=None, refusal=None)
        try:
            require(item['parent'] is None or item['parent'] in moving,
                    'source: parent is outside move scope')
            blockers = []
            merged_blockers, completed, dropped, held = [], [], [], []
            for blocker in item['blockers']:
                if str(blocker) in merges:
                    merged_blockers.append(blocker)
                elif str(blocker) in closures:
                    (completed if closures[str(blocker)]['state'] == 'completed' else dropped).append(blocker)
                elif str(blocker) in exclusions and source.nodes[blocker]['item']['state'] == 'open':
                    held.append(dict(closedwiz=blocker, url=exclusions[str(blocker)]['url'], state='open', status='HELD'))
                else:
                    require(blocker in moving, 'source: blocker is outside move scope')
                    blockers.append({'closedwiz': blocker})
            # A numbered pointer here is a preflight placeholder, never a published pointer.
            pointer = f'{SOURCE}/{path}/{n}#issuecomment-1'
            body, quotes = transform(node['body'], pointer, n, kind, sorted(merged_blockers),
                                     closing_map={row['number']: 'planned' for row in inv['moves'] if row['kind'] == 'issue'},
                                     completed={v: closures[str(v)]['comment'] for v in completed}, merge_proofs=merges,
                                     private_targets={int(v): p['url'] for v, p in exclusions.items()},
                                     body_aliases=aliases, held=held)
            labels = sorted(set(item['labels']) - READY)
            check_text(item['title'], body + '\n' + '\n'.join(labels) + '\n' + (item['milestone'] or ''), checker, literals)
            operation['new'] = dict(title=item['title'], body=body, labels=labels,
                milestone=None if item['milestone'] is None else {'title': item['milestone'], 'number': 'planned'},
                parent=None if item['parent'] is None else {'closedwiz': item['parent']}, blockers=blockers,
                merged_blockers=sorted(merged_blockers), completed_blockers=sorted(completed),
                dropped_blockers=sorted(dropped), held_prerequisites=held,
                private_record={'required': bool(quotes), 'quote_count': len(quotes),
                'pointer_is_placeholder': bool(quotes)},
                patch=None if kind == 'issue' else {'status': 'requires_reviewed_O14_artifact', 'range_sha256': digest(node['range'])})
        except Refusal as error:
            # The checker reports rule/place only; never include source snippets or raw input.
            operation['refusal'] = str(error)
        result.append(operation)
    return result


def check_operations(inv, data, rows, checker, literals, provenance):
    check_map(data, inv)
    require(type(rows) is list and all(type(row) is dict for row in rows), 'dry-run: invalid operations')
    require([(r.get('kind'), r.get('closedwiz')) for r in rows] ==
            [(r['kind'], r['number']) for r in inv['moves']], 'dry-run: missing or duplicate operation')
    moving = {row['number']: row['kind'] for row in inv['moves']}
    graphs, parents = {}, {}

    def reference(value):
        exact(value, ['closedwiz'], 'dry-run reference')
        n = value['closedwiz']
        require(number(n) and moving.get(n) == 'issue', 'dry-run: unknown graph reference')
        return n

    for row in rows:
        exact(row, ['closedwiz', 'kind', 'original_comment', 'was', 'new', 'refusal'], 'dry-run operation')
        n, kind = row['closedwiz'], row['kind']
        path = 'pull' if kind == 'pull_request' else 'issues'
        was = f'was [ClosedWiz #{n}]({SOURCE}/{path}/{n})'
        require(row.get('original_comment') == moved_template(n, kind) and row.get('was') == was,
                'dry-run: planned cross-link missing')
        require(row.get('refusal') is None and type(row.get('new')) is dict, 'dry-run: refused operation')
        new = row['new']
        exact(new, ['title', 'body', 'labels', 'milestone', 'parent', 'blockers', 'merged_blockers',
                    'completed_blockers', 'dropped_blockers', 'held_prerequisites',
                    'private_record', 'patch'], 'dry-run new item')
        require(type(new['title']) is str and new['title'].strip() and type(new['body']) is str and
                new['body'].endswith('\n\n' + was) and new['body'].splitlines().count(was) == 1 and
                not THREAD.search(new['body']), 'dry-run: planned title/body/origin differs')
        labels = new['labels']
        require(type(labels) is list and all(type(v) is str and v.strip() for v in labels) and
                labels == sorted(set(labels)) and not READY.intersection(labels), 'dry-run: labels/readiness differ')
        milestone = new['milestone']
        if milestone is not None:
            exact(milestone, ['title', 'number'], 'dry-run milestone')
            require(type(milestone['title']) is str and milestone['title'].strip() and
                    milestone['number'] == 'planned', 'dry-run: invalid milestone')
        parent = None if new['parent'] is None else reference(new['parent'])
        require(type(new['blockers']) is list, 'dry-run: invalid blockers')
        blockers = [reference(ref) for ref in new['blockers']]
        require(blockers == sorted(set(blockers)) and n not in blockers and parent != n and
                (kind == 'issue' or (parent is None and not blockers)), 'dry-run: invalid graph')
        parents[n] = [] if parent is None else [parent]
        graphs[n] = blockers
        completed = new['merged_blockers']
        require(type(completed) is list and all(number(v) and str(v) in provenance['merges'] for v in completed) and
                completed == sorted(set(completed)) and not set(completed).intersection(moving),
                'dry-run: merged blockers lack provenance')
        for v in completed:
            for proof in provenance['merges'][str(v)]:
                pr = proof['pull_request']
                require(f'[closing PR #{pr}]({SOURCE}/pull/{pr})' in new['body'],
                        'dry-run: closing PR proof note missing')
        for key, state in [('completed_blockers', 'completed'), ('dropped_blockers', 'not_planned')]:
            values = new[key]
            require(type(values) is list and all(number(v) and str(v) in provenance['closures'] and
                    provenance['closures'][str(v)]['state'] == state for v in values) and
                    values == sorted(set(values)) and not set(values).intersection(moving),
                    'dry-run: closed blockers lack disposition provenance')
        for v in new['completed_blockers']:
            c = provenance['closures'][str(v)]['comment']
            require(f'[ClosedWiz #{v}]({SOURCE}/issues/{v}) ' +
                    f'([completion record]({SOURCE}/issues/{v}#issuecomment-{c}))' in new['body'],
                    'dry-run: completion proof note missing')
        held = new['held_prerequisites']
        require(type(held) is list, 'dry-run: invalid held prerequisites')
        held_numbers = []
        for value in held:
            exact(value, ['closedwiz', 'url', 'state', 'status'], 'dry-run held prerequisite')
            v = value['closedwiz']
            require(number(v) and str(v) in provenance['excluded_targets'] and v not in moving and
                    value['url'] == provenance['excluded_targets'][str(v)]['url'] and
                    value['state'] == 'open' and value['status'] == 'HELD',
                    'dry-run: held prerequisite lacks excluded provenance')
            held_numbers.append(v)
            require(f"[ClosedWiz #{v}]({value['url']}) (state: open)" in new['body'] and
                    'HELD private prerequisites: ' in new['body'], 'dry-run: held prerequisite note missing')
        require(held_numbers == sorted(set(held_numbers)) and (kind == 'issue' or not held),
                'dry-run: invalid held prerequisite identities')
        record = new['private_record']
        exact(record, ['required', 'quote_count', 'pointer_is_placeholder'], 'dry-run private record')
        require(type(record['quote_count']) is int and record['quote_count'] >= 0 and
                type(record['required']) is bool and record['required'] == bool(record['quote_count']) and
                type(record['pointer_is_placeholder']) is bool and
                record['pointer_is_placeholder'] == record['required'], 'dry-run: invalid private-record plan')
        patch = new['patch']
        if kind == 'pull_request':
            exact(patch, ['status', 'range_sha256'], 'dry-run PR patch')
            require(patch['status'] == 'requires_reviewed_O14_artifact' and digest_string(patch['range_sha256']),
                    'dry-run: missing public-patch plan')
        else:
            require(patch is None, 'dry-run: issue has a patch')
        check_text(new['title'], new['body'] + '\n' + '\n'.join(labels) + '\n' +
                   (milestone['title'] if milestone else ''), checker, literals)
    acyclic(graphs, 'dry-run blockers')
    acyclic(parents, 'dry-run parents')


def digest_string(value):
    return type(value) is str and re.fullmatch('[0-9a-f]{64}', value) is not None


def check_saved(args):
    inv = parse_json((args.out / 'inventory.json').read_text(encoding='utf-8'))
    data = (args.out / 'map.dry-run.tsv').read_bytes()
    rows = parse_json((args.out / 'operations.json').read_text(encoding='utf-8'))
    provenance = parse_json((args.out / 'provenance.json').read_text(encoding='utf-8'))
    report = parse_json((args.out / 'report.json').read_text(encoding='utf-8'))
    check_map(data, inv)
    exact(provenance, ['merges', 'closures', 'approvals', 'excluded_targets', 'source_nodes', 'source_sha256',
                       'body_aliases'], 'dry-run provenance')
    compile_aliases(provenance['body_aliases'], args.literals)
    for key in ['merges', 'closures', 'approvals', 'excluded_targets', 'source_nodes']:
        require(type(provenance[key]) is dict and all(re.fullmatch('[1-9][0-9]*', n) for n in provenance[key]),
                'dry-run: invalid provenance identities')
    nodes = provenance['source_nodes']
    require(all(digest_string(v) for v in nodes.values()) and digest_string(provenance['source_sha256']),
            'dry-run: invalid source digests')
    require({str(row['number']) for row in inv['moves']} <= set(nodes), 'dry-run: missing source provenance')
    require(set(provenance['excluded_targets']) == {str(n) for n in inv['excluded']},
            'dry-run: missing excluded-target provenance')
    validate_excluded_targets(provenance['excluded_targets'], inv['excluded'], nodes)
    for n, proofs in provenance['merges'].items():
        require(n in nodes, 'dry-run: missing merge provenance')
        validate_merge_proofs(proofs)
    for n, proof in provenance['closures'].items():
        exact(proof, ['state', 'comment', 'sha256', 'superseded_by'], 'dry-run closure proof')
        validate_closure_record({k: v for k, v in proof.items() if k != 'state'})
        require(n in nodes and n not in provenance['merges'] and type(proof['state']) is str and
                proof['state'] in {'completed', 'not_planned'} and
                ((proof['superseded_by'] is None) == (proof['state'] == 'completed')) and
                proof['superseded_by'] != int(n), 'dry-run: invalid closure disposition')
    for n, approval in provenance['approvals'].items():
        exact(approval, ['comment', 'fingerprint', 'current_fingerprint', 'status'], 'dry-run original approval')
        require(n in nodes and number(approval['comment']) and digest_string(approval['fingerprint']) and
                digest_string(approval['current_fingerprint']) and
                approval['status'] == ('approval current' if approval['fingerprint'] == approval['current_fingerprint']
                                       else 'approval stale'),
                'dry-run: invalid approval provenance')
    exact(report, ['schema', 'status', 'counts', 'source_nodes', 'refused', 'source_sha256',
                   'operations_sha256', 'inventory_sha256', 'map_sha256', 'provenance_sha256',
                   'target_contacted', 'public_writes', 'patch_preparation', 'dropped_blockers', 'stale_approvals',
                   'held_prerequisites', 'read_attempts'], 'dry-run report')
    history = report['read_attempts']
    exact(history, ['limit', 'used', 'refusals'], 'dry-run read attempts')
    require(type(history['limit']) is int and 1 <= history['limit'] <= 3 and
            type(history['used']) is int and 1 <= history['used'] <= history['limit'] and
            type(history['refusals']) is list and len(history['refusals']) == history['used'] - 1,
            'dry-run: invalid read attempt history')
    for attempt, drift in enumerate(history['refusals'], 1):
        exact(drift, ['attempt', 'nodes', 'proof_sections', 'inventory_changed', 'inventory_counts'], 'dry-run drift')
        require(type(drift['attempt']) is int and drift['attempt'] == attempt and
                type(drift['nodes']) is list and type(drift['proof_sections']) is list and
                all(type(v) is str and v in {'merges', 'closures', 'approvals', 'excluded_targets'}
                    for v in drift['proof_sections']) and type(drift['inventory_changed']) is bool and
                (drift['nodes'] or drift['proof_sections'] or drift['inventory_changed']),
                'dry-run: invalid read attempt history')
        if drift['inventory_counts'] is not None:
            counts = drift['inventory_counts']
            exact(counts, ['expected', 'observed'], 'dry-run inventory counts')
            require(all(type(v) is int and v >= 0 for v in counts.values()) and
                    counts['expected'] != counts['observed'] and drift['inventory_changed'],
                    'dry-run: invalid read attempt history')
        for node in drift['nodes']:
            exact(node, ['number', 'fields'], 'dry-run drift node')
            require(number(node['number']) and type(node['fields']) is list and node['fields'] and
                    all(type(v) is str and v in {'membership', 'body', 'children', 'range', 'range.observed_base',
                        'range.source_base', 'range.source_head', 'item', 'item.number', 'item.kind', 'item.title',
                        'item.labels', 'item.milestone', 'item.parent', 'item.blockers', 'item.state'}
                        for v in node['fields']), 'dry-run: invalid read attempt history')
    require(report['schema'] == 'openwiz.ticket-dry-run.v1' and report['status'] == 'planned' and
            report['counts'] == inv['counts'] and report['refused'] == [] and
            type(report['source_nodes']) is int and report['source_nodes'] == len(nodes) and
            report['source_sha256'] == provenance['source_sha256'] and
            report['operations_sha256'] == digest(rows) and report['inventory_sha256'] == digest(inv) and
            report['map_sha256'] == hashlib.sha256(data).hexdigest() and
            report['provenance_sha256'] == digest(provenance) and report['target_contacted'] is False and
            type(report['public_writes']) is int and report['public_writes'] == 0 and
            report['patch_preparation'] == 'separate reviewed O14 artifacts required',
            'dry-run: report, operations, map or provenance binding differs')
    check_operations(inv, data, rows, args.checker, args.literals, provenance)
    require(report['dropped_blockers'] == dropped_report(rows, provenance['closures']),
            'dry-run: dropped blocker report differs')
    require(report['stale_approvals'] == stale_report(provenance['approvals']),
            'dry-run: stale approval report differs')
    require(report['held_prerequisites'] == held_report(rows), 'dry-run: held prerequisite report differs')


def held_report(rows):
    held = {}
    for row in rows:
        for value in row['new']['held_prerequisites'] if row['new'] else []:
            held.setdefault(value['closedwiz'], dict(value, dependents=[]))['dependents'].append(row['closedwiz'])
    return [held[n] for n in sorted(held)]


def stale_report(approvals):
    return [dict(closedwiz=int(n), comment=proof['comment'], approved_fingerprint=proof['fingerprint'],
                 current_fingerprint=proof['current_fingerprint'], status='approval stale')
            for n, proof in sorted(approvals.items(), key=lambda pair: int(pair[0]))
            if proof['status'] == 'approval stale']


def dropped_report(rows, closures):
    return [dict(closedwiz=int(n), dependents=[row['closedwiz'] for row in rows
                if row['new'] and int(n) in row['new']['dropped_blockers']],
                record=f"{SOURCE}/issues/{n}#issuecomment-{proof['comment']}",
                superseded_by=proof['superseded_by'])
            for n, proof in sorted(closures.items(), key=lambda pair: int(pair[0])) if proof['state'] == 'not_planned']


def read_pair(gh, target, records):
    inv = inventory(gh, target)
    first, merges, closures, approvals, exclusions = collect_source(gh, inv, records)
    second, again_merges, again_closures, again_approvals, again_exclusions = collect_source(gh, inv, records)
    final_inventory = inventory(gh, target)
    changed = []
    for n in sorted(set(first.nodes) | set(second.nodes)):
        a, b = first.nodes.get(n), second.nodes.get(n)
        if a != b:
            fields = ['membership'] if a is None or b is None else [
                key for key in ['body', 'children'] if a[key] != b[key]]
            if a is not None and b is not None:
                for key in ['range', 'item']:
                    if a[key] != b[key]:
                        fields.extend([key] if a[key] is None or b[key] is None else
                                      [key + '.' + field for field in sorted(set(a[key]) | set(b[key]))
                                       if a[key].get(field) != b[key].get(field)])
            changed.append(dict(number=n, fields=fields))
    proof_changes = [name for name, before, after in [('merges', merges, again_merges),
        ('closures', closures, again_closures), ('approvals', approvals, again_approvals),
        ('excluded_targets', exclusions, again_exclusions)] if before != after]
    if changed or proof_changes or inv != final_inventory:
        raise SnapshotChanged(dict(nodes=changed, proof_sections=proof_changes,
                                   inventory_changed=inv != final_inventory, inventory_counts=None))
    return inv, first, merges, closures, approvals, exclusions


def build(args):
    require(not args.out.exists(), 'output already exists; use a new folder')
    # Check mandatory O3/list before collecting any source data.
    check_text('Preflight', 'Synthetic preflight.', args.checker, args.literals)
    policy = None if args.body_aliases is None else parse_json(args.body_aliases.read_text(encoding='utf-8'))
    aliases = compile_aliases(policy, args.literals)
    records = {} if args.closure_records is None else parse_json(args.closure_records.read_text(encoding='utf-8'))
    require(type(records) is dict and all(re.fullmatch('[1-9][0-9]*', n) for n in records),
            'source: invalid closure bindings')
    history = dict(limit=args.snapshot_attempts, used=0, refusals=[])
    for attempt in range(1, args.snapshot_attempts + 1):
        history['used'] = attempt
        try:
            inv, first, merges, closures, approvals, exclusions = read_pair(args.gh, args.target, records)
            break
        except (SnapshotChanged, InventoryChanged) as error:
            changes = (dict(nodes=[dict(number=n, fields=['membership']) for n in error.numbers],
                            proof_sections=[], inventory_changed=True, inventory_counts=error.counts)
                       if isinstance(error, InventoryChanged) else error.changes)
            history['refusals'].append(dict(attempt=attempt, **changes))
    else:
        raise Refusal('source: changed during collection after ' + str(args.snapshot_attempts) +
                      ' attempts; ' + json.dumps(history))
    rows = operations(inv, first, merges, closures, args.checker, args.literals, exclusions, aliases)
    data = planned_map(inv).encode()
    check_map(data, inv)
    refused = [row['closedwiz'] for row in rows if row['refusal'] is not None]
    report = dict(schema='openwiz.ticket-dry-run.v1', status='refused' if refused else 'planned',
                  counts=inv['counts'], source_nodes=len(first.nodes), refused=refused,
                  source_sha256=digest(first.nodes), operations_sha256=digest(rows),
                  inventory_sha256=digest(inv), map_sha256=hashlib.sha256(data).hexdigest(),
                  target_contacted=False, public_writes=0, patch_preparation='separate reviewed O14 artifacts required',
                  dropped_blockers=dropped_report(rows, closures), stale_approvals=stale_report(approvals),
                  held_prerequisites=held_report(rows), read_attempts=history)
    provenance = dict(merges=merges, closures=closures, approvals=approvals, excluded_targets=exclusions, body_aliases=policy,
                      source_sha256=digest(first.nodes),
                      source_nodes={str(n): digest(node) for n, node in sorted(first.nodes.items())})
    report['provenance_sha256'] = digest(provenance)
    args.out.mkdir(mode=0o700, parents=True)
    for name, value in [('inventory.json', inv), ('operations.json', rows), ('provenance.json', provenance), ('report.json', report)]:
        path = args.out / name
        path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
        os.chmod(path, 0o600)
    (args.out / 'map.dry-run.tsv').write_bytes(data)
    os.chmod(args.out / 'map.dry-run.tsv', 0o600)
    check_saved(args)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gh', default='gh')
    p.add_argument('--target', default='openwizdev/openwiz')
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--checker', type=Path, required=True)
    p.add_argument('--literals', type=Path, required=True)
    p.add_argument('--check', action='store_true', help='check saved local operations/map; makes no GitHub call')
    p.add_argument('--closure-records', type=Path, help='private explicit comment/hash bindings for non-merge closures')
    p.add_argument('--body-aliases', type=Path, help='explicit body-only dry-run alias policy')
    p.add_argument('--snapshot-attempts', type=int, choices=[1, 2, 3], default=3,
                   help='bounded two-snapshot attempts on observed source drift; no sleeps')
    args = p.parse_args()
    try:
        if args.check:
            check_saved(args)
            print('pass: complete planned map and both links; placeholders are not publication authority')
        else:
            print(json.dumps(build(args)))
    except (Refusal, OSError, ValueError) as error:
        print('refused: ' + (str(error) if isinstance(error, Refusal) else 'unreadable or invalid input'), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
