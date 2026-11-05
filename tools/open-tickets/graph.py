#!/usr/bin/env python3
"""Graph-only preparation; public text and applied migration remain unverified."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plan import Refusal, exact, number, parse_json, require, target, DEFAULT_TARGET  # noqa: E402

READY = {'ready-for-agent', 'ready-for-human'}
FIELDS = ['number', 'kind', 'title', 'labels', 'milestone', 'parent', 'blockers', 'state']


def text(value):
    return type(value) is str and bool(value.strip())


def unique_numbers(values, place):
    require(type(values) is list and all(number(n) for n in values), place + ': invalid numbers')
    require(len(set(values)) == len(values), place + ': repeated number')


def acyclic(edges, place):
    # Kahn's algorithm avoids depending on Python's recursion limit.
    pending = {n: set(dependencies) for n, dependencies in edges.items()}
    reverse = {n: set() for n in pending}
    for n, deps in pending.items():
        for dep in deps:
            reverse[dep].add(n)
    ready = [n for n, deps in pending.items() if not deps]
    visited = 0
    while ready:
        n = ready.pop()
        visited += 1
        for other in reverse[n]:
            pending[other].remove(n)
            if not pending[other]:
                ready.append(other)
    require(visited == len(pending), place + ': cycle')


def validate_snapshot(snapshot):
    exact(snapshot, ['items', 'milestones', 'exclude'], 'snapshot')
    unique_numbers(snapshot['exclude'], 'snapshot exclusions')
    require(type(snapshot['items']) is list and type(snapshot['milestones']) is list,
            'snapshot: invalid lists')
    items = {}
    for item in snapshot['items']:
        exact(item, FIELDS, 'snapshot item')
        n = item['number']
        require(number(n) and n not in items, 'snapshot: invalid or duplicate number')
        require(type(item['kind']) is str and item['kind'] in {'issue', 'pull_request'} and
                type(item['state']) is str and item['state'] in {'open', 'closed', 'merged', 'completed', 'not_planned'},
                'snapshot: invalid kind or state')
        require(text(item['title']) and (item['milestone'] is None or text(item['milestone'])),
                'snapshot: missing title or milestone')
        labels = item['labels']
        require(type(labels) is list and all(text(label) for label in labels) and
                len(set(labels)) == len(labels), 'snapshot: invalid labels')
        require(item['parent'] is None or (number(item['parent']) and item['parent'] != n),
                'snapshot: invalid parent')
        unique_numbers(item['blockers'], 'snapshot blockers')
        require(n not in item['blockers'], 'snapshot: self blocker')
        require(item['kind'] == 'issue' or (item['parent'] is None and not item['blockers']),
                'snapshot: pull request cannot have issue graph links')
        items[n] = item
    milestones, numbers = {}, set()
    for milestone in snapshot['milestones']:
        exact(milestone, ['title', 'number'], 'snapshot milestone')
        require(text(milestone['title']) and number(milestone['number']) and
                milestone['title'] not in milestones and milestone['number'] not in numbers,
                'snapshot: ambiguous milestone')
        milestones[milestone['title']] = milestone
        numbers.add(milestone['number'])
    for item in items.values():
        refs = item['blockers'] + ([] if item['parent'] is None else [item['parent']])
        require(all(n in items and items[n]['kind'] == 'issue' for n in refs),
                'snapshot: unknown graph reference')
    acyclic({n: i['blockers'] for n, i in items.items()}, 'snapshot blockers')
    acyclic({n: [] if i['parent'] is None else [i['parent']] for n, i in items.items()},
            'snapshot parents')
    return items, milestones


def read_map(data, items, excluded):
    require(b'\r' not in data and data.endswith(b'\n'), 'map: expected LF with final newline')
    lines = data.decode('utf-8').split('\n')
    require(lines[0] == 'kind\tclosedwiz\topenwiz', 'map: invalid header')
    mapping, values, previous = {}, set(), 0
    for line in lines[1:-1]:
        cells = line.split('\t')
        require(len(cells) == 3 and cells[0] in {'issue', 'pull_request'} and
                re.fullmatch(r'[1-9][0-9]*', cells[1]) and
                (cells[2] == 'planned' or re.fullmatch(r'[1-9][0-9]*', cells[2])),
                'map: invalid row')
        old = int(cells[1])
        require(old > previous and old in items and items[old]['kind'] == cells[0],
                'map: duplicate, unsorted or unknown source')
        previous = old
        new = 'planned' if cells[2] == 'planned' else int(cells[2])
        require(new == 'planned' or new not in values, 'map: duplicate destination')
        values.add(new)
        mapping[old] = new
    expected = {n for n, item in items.items() if item['state'] == 'open' and n not in excluded}
    require(set(mapping) == expected, 'map: missing or unexpected row')
    require('planned' not in values or values == {'planned'}, 'map: mixed planned and real numbers')
    return mapping


def prepare(snapshot, data, public):
    target(public)
    items, milestones = validate_snapshot(snapshot)
    mapping = read_map(data, items, snapshot['exclude'])

    def ref(n):
        require(n in mapping, 'graph: open parent or blocker has no destination')
        return {'closedwiz': n} if mapping[n] == 'planned' else mapping[n]

    moves = []
    for n in sorted(mapping):
        item = items[n]
        milestone = None
        if item['milestone'] is not None:
            require(item['milestone'] in milestones, 'graph: milestone absent from destination')
            milestone = milestones[item['milestone']]
        open_blockers, merged, completed, dropped = [], [], [], []
        for blocker in sorted(item['blockers']):
            state = items[blocker]['state']
            require(state != 'closed', 'graph: closed blocker lacks verified merge')
            if state == 'merged':
                merged.append(blocker)
            elif state == 'completed':
                completed.append(blocker)
            elif state == 'not_planned':
                dropped.append(blocker)
            else:
                open_blockers.append(ref(blocker))
        moves.append({'closedwiz': n, 'openwiz': mapping[n], 'kind': item['kind'],
                      'title': item['title'], 'labels': sorted(set(item['labels']) - READY),
                      'milestone': milestone,
                      'parent': None if item['parent'] is None else ref(item['parent']),
                      'blockers': open_blockers, 'merged_blockers': merged,
                      'completed_blockers': completed, 'dropped_blockers': dropped})
    return {'status': 'graph_only', 'target': public, 'moves': moves}



def label_names(labels, place):
    require(type(labels) is list and all(type(label) is dict and text(label.get('name')) for label in labels),
            place + ': invalid labels')
    names = sorted(label['name'] for label in labels)
    require(len(set(names)) == len(names), place + ': repeated label')
    return names


def milestone_value(value, place):
    if value is None:
        return None
    require(type(value) is dict and text(value.get('title')) and number(value.get('number')),
            place + ': invalid milestone')
    return {'title': value['title'], 'number': value['number']}


def issue_number(node, repo, place):
    require(type(node) is dict and number(node.get('number')) and type(node.get('url')) is str,
            place + ': missing relationship identity')
    expected = f"https://github.com/{repo}/issues/{node['number']}"
    require(node['url'].casefold() == expected.casefold(), place + ': foreign relationship')
    return node['number']


def parent_number(value, repo, place):
    return None if value is None else issue_number(value, repo, place)


def blocker_numbers(value, repo, place):
    exact(value, ['nodes', 'totalCount'], place)
    require(type(value['nodes']) is list and type(value['totalCount']) is int and
            value['totalCount'] == len(value['nodes']), place + ': incomplete blockers')
    ns = [issue_number(node, repo, place) for node in value['nodes']]
    unique_numbers(ns, place)
    return sorted(ns)


def verify(plan, gh):
    require(all(number(row['openwiz']) for row in plan['moves']),
            'read-back: real destination numbers required')
    for row in plan['moves']:
        fields = 'number,title,labels,milestone'
        command = 'pr' if row['kind'] == 'pull_request' else 'issue'
        if command == 'issue':
            fields += ',parent,blockedBy'
        result = subprocess.run([gh, command, 'view', str(row['openwiz']), '--repo', plan['target'],
                                 '--json', fields], capture_output=True, text=True, check=False)
        require(result.returncode == 0, 'read-back: gh read failed')
        actual = parse_json(result.stdout)
        exact(actual, fields.split(','), 'read-back')
        names = label_names(actual['labels'], 'read-back')
        milestone = milestone_value(actual['milestone'], 'read-back')
        require(number(actual['number']) and actual['number'] == row['openwiz'] and
                actual['title'] == row['title'] and names == row['labels'] and
                milestone == row['milestone'], 'read-back: title, labels or milestone differ')
        if command == 'pr':
            continue
        require(parent_number(actual['parent'], plan['target'], 'read-back') == row['parent'],
                'read-back: parent differs')
        require(blocker_numbers(actual['blockedBy'], plan['target'], 'read-back') == sorted(row['blockers']),
                'read-back: blockers differ')



def reapproval(plan, snapshot, spec, bodies):
    require(type(bodies) is dict and all(re.fullmatch(r'[1-9][0-9]*', key) and
            type(body) is str for key, body in bodies.items()), 'reapproval: invalid bodies')
    items, _ = validate_snapshot(snapshot)
    moves = {row['closedwiz']: row for row in plan['moves']}
    require(spec in moves and moves[spec]['kind'] == 'issue', 'reapproval: spec is not moving')
    children = [row for n, row in moves.items() if items[n]['parent'] == spec]
    require(all(str(n) in bodies for n in [spec] + [row['closedwiz'] for row in children]),
            'reapproval: missing public body')
    require(all(not any(c in row['title'] for c in '|\r\n') for row in children),
            'reapproval: title cannot be represented in the approval table')
    if any(not number(row['openwiz']) for row in [moves[spec]] + children):
        return {'status': 'awaiting_destination_numbers', 'fingerprint': None, 'revision': None,
                'table': None}
    children.sort(key=lambda row: row['openwiz'])

    def body_hash(n):
        # revision.sh hashes the body plus gh --jq's final LF, with ticked boxes unticked.
        normalized = re.sub(r'^([ \t]*[-*+][ \t]+)\[[xX]\](?=[ \t\r]|$)',
                            r'\1[ ]', bodies[str(n)] + '\n', flags=re.MULTILINE)
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    revision = 'plan-graph revision v2\n'
    revision += f"spec #{moves[spec]['openwiz']} body sha256 {body_hash(spec)}\n"
    table = '| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n'
    for row in children:
        blockers = ' '.join('#' + str(n) for n in sorted(row['blockers'])) or 'none'
        revision += (f"ticket #{row['openwiz']} blocked-by {blockers} body sha256 "
                     f"{body_hash(row['closedwiz'])} title {row['title']}\n")
        table += f"| #{row['openwiz']} | {row['title']} | {blockers} | held |\n"
    return {'status': 'requires_reapproval', 'fingerprint': hashlib.sha256(revision.encode()).hexdigest(),
            'revision': revision, 'table': table}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--map', required=True, type=Path)
    parser.add_argument('--target', default=DEFAULT_TARGET)
    output = parser.add_mutually_exclusive_group(required=True)
    output.add_argument('--out', type=Path)
    output.add_argument('--verify', action='store_true')
    parser.add_argument('--gh', default='gh')
    parser.add_argument('--reapproval', type=int)
    parser.add_argument('--bodies', type=Path)
    args = parser.parse_args()
    try:
        plan = prepare(parse_json(args.snapshot.read_text(encoding='utf-8')), args.map.read_bytes(), args.target)
        if args.reapproval:
            require(args.bodies, 'reapproval: --bodies is required')
            plan['reapproval'] = reapproval(plan, parse_json(args.snapshot.read_text(encoding='utf-8')),
                                           args.reapproval, parse_json(args.bodies.read_text(encoding='utf-8')))
        else:
            require(not args.bodies, 'reapproval: --bodies requires --reapproval')
        if args.verify:
            verify(plan, args.gh)
            print('pass: graph metadata read-back; public bodies, links and applied migration unverified')
        else:
            # Metadata may still contain private text. This is a local private draft only.
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(json.dumps(plan, indent=2) + '\n')
            print('graph_only: private metadata draft; no public write or privacy pass')
    except (Refusal, OSError, ValueError) as error:
        reason = str(error) if isinstance(error, Refusal) else 'unreadable or invalid input'
        print('refused: ' + reason, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
