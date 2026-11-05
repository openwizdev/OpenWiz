#!/usr/bin/env python3
"""Read-only inventory and dry-map validation for #1283; no migration yet.

Only counts, kinds and issue numbers are saved. Titles, bodies and comments
stay in memory and are discarded. Public drafts, privacy checking, graph
mapping and resumable apply are still blocked; see README.md.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

SOURCE = 'jparker2006/ClosedWiz'
DEFAULT_TARGET = 'openwizdev/openwiz'
SPEC = 1257
SCHEMA = 'openwiz.ticket-move.inventory.v1'
HEADER = 'kind\tclosedwiz\topenwiz\n'
KINDS = {'issue', 'pull_request'}


class Refusal(Exception):
    pass


class InventoryChanged(Refusal):
    def __init__(self, numbers, counts=None):
        self.numbers = numbers
        self.counts = counts
        super().__init__('gh: inventory changed during read; numbers=' + json.dumps(numbers) +
                         '; counts=' + json.dumps(counts))


def require(condition, message):
    if not condition:
        raise Refusal(message)


def number(value):
    return type(value) is int and value > 0


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'repeated JSON key')
        result[key] = value
    return result


def parse_json(text):
    return json.loads(text, object_pairs_hook=object_pairs)


def exact(value, keys, place):
    require(type(value) is dict and set(value) == set(keys), place + ': invalid object')


def records(value, place):
    require(type(value) is list, place + ': not a list')
    last = 0
    for row in value:
        exact(row, ['kind', 'number'], place)
        require(type(row['kind']) is str and row['kind'] in KINDS and number(row['number']),
                place + ': invalid kind or number')
        require(row['number'] > last, place + ': duplicate or unsorted number')
        last = row['number']


def counts(scope, moves):
    return {
        'open_issues': sum(r['kind'] == 'issue' for r in scope),
        'open_pull_requests': sum(r['kind'] == 'pull_request' for r in scope),
        'moving_issues': sum(r['kind'] == 'issue' for r in moves),
        'moving_pull_requests': sum(r['kind'] == 'pull_request' for r in moves),
    }


def validate_inventory(inv):
    exact(inv, ['schema', 'source', 'target', 'migration_spec', 'remaining', 'scope',
                'excluded', 'counts', 'moves', 'status'], 'inventory')
    require(inv['schema'] == SCHEMA and inv['source'] == SOURCE and
            type(inv['migration_spec']) is int and inv['migration_spec'] == SPEC and
            inv['status'] == 'inventory_only', 'inventory: unsupported contract')
    target(inv['target'])
    for key in ['remaining', 'excluded']:
        seq = inv[key]
        require(type(seq) is list and all(number(n) for n in seq) and
                seq == sorted(set(seq)), 'inventory: invalid ' + key)
    records(inv['scope'], 'inventory scope')
    records(inv['moves'], 'inventory moves')
    excluded = sorted({r['number'] for r in inv['scope']} & ({SPEC} | set(inv['remaining'])))
    require(inv['excluded'] == excluded, 'inventory: wrong exclusions')
    moves = [r for r in inv['scope'] if r['number'] not in excluded]
    require(inv['moves'] == moves, 'inventory: incomplete move set')
    expected = counts(inv['scope'], moves)
    exact(inv['counts'], expected, 'inventory counts')
    require(all(type(v) is int for v in inv['counts'].values()) and inv['counts'] == expected,
            'inventory: counts differ')


def target(value):
    require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', value)
            and value.lower() != SOURCE.lower(), 'target: expected another OWNER/REPO')


def read(gh, endpoint, pages=False):
    args = [gh, 'api', '--method', 'GET']
    if pages:
        args += ['--paginate', '--slurp']
    args.append('repos/' + SOURCE + endpoint)
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    # Diagnostics may contain private response text; do not echo them.
    require(result.returncode == 0, 'gh: read failed for ' + endpoint.split('?')[0])
    value = parse_json(result.stdout)
    if not pages:
        require(type(value) is dict, 'gh: expected an object')
        return value
    require(type(value) is list and len(value) > 0 and all(type(p) is list for p in value),
            'gh: incomplete paginated read')
    return [row for page in value for row in page]


def read_once(gh):
    repo = read(gh, '')
    issue = read(gh, '/issues/' + str(SPEC))
    expected = repo.get('open_issues_count')
    summary = issue.get('sub_issues_summary')
    require(type(expected) is int and expected >= 0 and type(summary) is dict,
            'gh: missing independent inventory count')
    total = summary.get('total')
    require(type(total) is int and total >= 0, 'gh: missing sub-issue count')
    items = read(gh, '/issues?state=open&per_page=100', pages=True)
    children = read(gh, '/issues/' + str(SPEC) + '/sub_issues?per_page=100', pages=True)
    scope = []
    for item in items:
        require(type(item) is dict and number(item.get('number')), 'gh: invalid issue number')
        scope.append({'kind': 'pull_request' if 'pull_request' in item else 'issue',
                      'number': item['number']})
    scope.sort(key=lambda row: row['number'])
    records(scope, 'gh inventory')
    if len(scope) != expected:
        raise InventoryChanged([], dict(expected=expected, observed=len(scope)))
    remaining = []
    for child in children:
        require(type(child) is dict and number(child.get('number')), 'gh: invalid sub-issue number')
        remaining.append(child['number'])
    require(len(set(remaining)) == len(remaining) == total, 'gh: partial or duplicate sub-issue read')
    return scope, sorted(remaining)


def inventory(gh, public):
    target(public)
    scope, remaining = read_once(gh)
    again_scope, again_remaining = read_once(gh)
    if (scope, remaining) != (again_scope, again_remaining):
        before = {r['number']: r['kind'] for r in scope}
        after = {r['number']: r['kind'] for r in again_scope}
        changed = {n for n in set(before) | set(after) if before.get(n) != after.get(n)}
        changed.update(set(remaining) ^ set(again_remaining))
        raise InventoryChanged(sorted(changed))
    excluded = sorted({row['number'] for row in scope} & ({SPEC} | set(remaining)))
    moves = [row for row in scope if row['number'] not in excluded]
    result = {'schema': SCHEMA, 'source': SOURCE, 'target': public, 'migration_spec': SPEC,
              'remaining': remaining, 'scope': scope, 'excluded': excluded,
              'counts': counts(scope, moves), 'moves': moves, 'status': 'inventory_only'}
    validate_inventory(result)
    return result


def planned_map(inv):
    return HEADER + ''.join(f'{r["kind"]}\t{r["number"]}\tplanned\n' for r in inv['moves'])


def check_map(data, inv):
    validate_inventory(inv)
    require(b'\r' not in data and data.endswith(b'\n'), 'map: expected LF and final newline')
    text = data.decode('utf-8')
    require(text.startswith(HEADER), 'map: invalid header')
    rows = []
    for line in text[len(HEADER):].splitlines():
        cells = line.split('\t')
        require(len(cells) == 3 and cells[0] in KINDS and
                re.fullmatch(r'[1-9][0-9]*', cells[1]) and cells[2] == 'planned',
                'map: invalid dry-run row')
        rows.append({'kind': cells[0], 'number': int(cells[1])})
    records(rows, 'map: rows')
    require(rows == inv['moves'], 'map: missing, unexpected or wrong-kind row')
    require(text == planned_map(inv), 'map: noncanonical encoding')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gh', default='gh', help='gh executable (fake in tests)')
    parser.add_argument('--target', help='intended target; no target is contacted')
    parser.add_argument('--out', type=Path, help='new private output folder')
    parser.add_argument('--check-map', type=Path, help='validate an inventory-only dry map')
    parser.add_argument('--inventory', type=Path, help='inventory.json for --check-map')
    args = parser.parse_args()
    try:
        if args.check_map:
            require(args.inventory and not args.out and not args.target,
                    '--check-map requires only --inventory')
            check_map(args.check_map.read_bytes(), parse_json(args.inventory.read_text()))
            print('pass: inventory-only dry map complete; planned links and public drafts unverified')
        else:
            require(args.out and not args.inventory, '--out is required')
            require(not args.out.exists(), 'output already exists; use a new folder')
            inv = inventory(args.gh, args.target or DEFAULT_TARGET)
            data = planned_map(inv).encode()
            check_map(data, inv)
            args.out.mkdir(parents=True)
            (args.out / 'inventory.json').write_text(json.dumps(inv, indent=2) + '\n', encoding='utf-8')
            (args.out / 'map.dry-run.tsv').write_bytes(data)
            print(json.dumps({'status': inv['status'], 'counts': inv['counts'],
                              'excluded': inv['excluded'], 'public_drafts': 'unverified'}))
    except (Refusal, OSError, ValueError) as error:
        # Do not print an input's contents, gh's response, or file paths.
        message = str(error) if isinstance(error, Refusal) else 'unreadable or invalid input'
        print('refused: ' + message, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
