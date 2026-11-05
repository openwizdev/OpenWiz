#!/usr/bin/env python3
"""#1481 (OB6) relay adapter: read ops inbox records through the relay's collector.

Read-only. It reuses relay.py's Reader (REST pagination, route checks, ETags)
and comment validation unchanged, and OB3's strict record reader. It never
writes GitHub, tells a thread or starts anything. See inbox.md.

python3 -I tools/review-relay/inbox.py --repo OWNER/REPO --kind pull_request --number N
"""
import argparse
from datetime import datetime
import importlib.util
import json
import re
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay = _load(HERE / 'relay.py', 'review_relay')
effects = _load(HERE.parents[1] / 'skills/launch-fleet/scripts/effects.py', 'ops_effects_for_relay')
OPENER = re.compile(r'^[ \t]*```json[^\n]*\n', re.MULTILINE)
CLOSER = re.compile(r'^[ \t]*```', re.MULTILINE)
SCHEMA = 'openwiz.ops-dispatch.v1'


def _blocks(body):
    """Each json fence's content, at any indentation, running to the end of the
    comment when its closing delimiter is missing."""
    for opener in OPENER.finditer(body):
        closer = CLOSER.search(body, opener.end())
        yield body[opener.end():closer.start() if closer else len(body)]


def _affected(block):
    """An ops record candidate: its decoded schema is the ops schema, or, when it
    does not decode, its text names the ops schema once JSON escapes are undone.
    A duplicate key does not decode (#2479), as in the strict reader: otherwise a
    later duplicate "schema" would hide the record instead of leaving a gap."""
    try:
        value = json.loads(block, object_pairs_hook=effects._pairs)
        return type(value) is dict and value.get('schema') == SCHEMA
    except ValueError:
        text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), block)
        return 'ops-dispatch' in text
_relay_cache_body = relay.cache_body


def _cache_body(path, value):
    """The relay keeps only the comment fields it reads; inbox records also bind
    each comment's creation time. This widens only this module's own private
    copy of relay.py; the relay itself, its state and its fields are unchanged."""
    kept = _relay_cache_body(path, value)
    if '/comments' in path.split('?', 1)[0] and type(value) is list and type(kept) is list:
        for row, item in zip(value, kept):
            if type(row) is dict and type(item) is dict and 'created_at' in row:
                item['created_at'] = row['created_at']
    return kept


relay.cache_body = _cache_body


def _ms(stamp):
    relay.require(type(stamp) is str and stamp.endswith('Z'), 'unexpected comment time')
    return int(datetime.fromisoformat(stamp[:-1] + '+00:00').timestamp() * 1000)


def read(reader, kind, number, cursor):
    """One complete read of a conversation's ops records.

    Returns {complete, cursor, records, gaps}. Any failed or partial page keeps
    the caller's cursor and returns no records: absence is never inferred. A
    comment naming the ops schema whose record does not decode, binds another
    container or disagrees with the comment's own creation time is a gap, and
    any gap makes the whole read incomplete. Other JSON is not an ops record.
    On a complete read the cursor is the latest comment read, {created_at ms, comment id}.
    """
    try:
        rows = relay.comments(reader.pages(f'issues/{number}/comments'))
        stamps = [_ms(row.get('created_at')) for row in rows]
    except relay.Fail as error:
        return {'complete': False, 'cursor': cursor, 'records': [], 'gaps': [f'read failed: {error}']}
    records, gaps = [], []
    for row, at in zip(rows, stamps):
        # R4: a json fence (any indentation, closed or not) whose decoded schema is
        # the ops schema, or which fails to decode yet names it, is a candidate;
        # it must then pass the strict reader. Other JSON and prose are not.
        if not any(_affected(block) for block in _blocks(row['body'])):
            continue
        try:
            record = effects.read_comment(row['body'], (reader.repo, kind, number))
            if record['created_at'] != at:
                raise ValueError('record time disagrees with its comment')
            records.append(record)
        except ValueError as error:
            gaps.append(f'comment {row["id"]}: {error}')
    if gaps:
        # R4: an unreadable or misbound ops record could be an uncertainty or
        # completion; the history is incomplete, so nothing is returned.
        return {'complete': False, 'cursor': cursor, 'records': [], 'gaps': gaps}
    end = max(((at, row['id']) for row, at in zip(rows, stamps)), default=None)
    return {'complete': True, 'cursor': {'created_at': end[0], 'comment': end[1]} if end else cursor,
            'records': records, 'gaps': gaps}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--repo', required=True)
    parser.add_argument('--kind', choices=('issue', 'pull_request'), required=True)
    parser.add_argument('--number', type=int, required=True)
    args = parser.parse_args()
    result = read(relay.Reader(args.repo, {'cache': {}}), args.kind, args.number,
                  {'created_at': 0, 'comment': 0})
    json.dump(result, sys.stdout, sort_keys=True)
    print()
    return 0 if result['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
