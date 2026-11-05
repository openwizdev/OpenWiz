#!/usr/bin/env python3
"""Ticket journeys (#1384): one sanitized record per ticket, grill to merge.

Standard library + gh; GitHub reads only. The contract is journey-contract.md
beside this file. It reuses metrics.py's strict reader, pagination checks, PR
inventory and daily usage reader rather than a second collector.
"""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import re
import subprocess
import sys
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # A read-only tool writes nothing into the clone.
_spec = importlib.util.spec_from_file_location('factory_metrics', HERE / 'metrics.py')
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)
ReadError, require, obj, array, integer = M.ReadError, M.require, M.obj, M.array, M.integer

SCHEMA = 'closedwiz.journey.v1'
ISSUE = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){issue(number:$number){number url createdAt closedAt body parent{number} comments(first:100,after:$cursor){nodes{databaseId url createdAt updatedAt body} pageInfo{hasNextPage endCursor}}}}}'''
LABELS = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){issue(number:$number){timelineItems(itemTypes:[LABELED_EVENT],first:100,after:$cursor){nodes{... on LabeledEvent{createdAt label{name}}} pageInfo{hasNextPage endCursor}}}}}'''
PULL = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){number url createdAt mergedAt closedAt headRefName baseRefOid headRefOid mergeCommit{oid} body comments(first:100,after:$cursor){nodes{databaseId url createdAt updatedAt body} pageInfo{hasNextPage endCursor}}}}}'''
READY = 'ready-for-agent'
KINDS = ('missing-proof', 'stale-docs', 'spec-mismatch', 'fail-open', 'unknown')
GAPS = ('no ready label', 'no builder start record', 'no pull request', 'no merge', 'no spec', 'no grill path',
        'no plan graph approval')
USAGE = [(p, u) for p in ('claude', 'gpt') for u in ('tokens', 'credits', 'usd')]
COMMIT = re.compile(r'[0-9a-f]{40}')
GRILL = re.compile(r'docs/grills/[A-Za-z0-9._-]+\.md')
STARTED = re.compile(
    r'launch-fleet: (?:(?:started|start checked), thread\b|started$|start checked, branch \S+$)')
THREAD = re.compile(r'\bthr_[A-Za-z0-9_]+')
VERDICT_START = re.compile(r'VERDICT: (APPROVE|CHANGES)\b')
VERDICT_EXACT = re.compile(r'VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})')
FINDING = re.compile(r'- \*\*(R[1-9][0-9]*) \[(high|medium|low)\]\*\* (.*)')
NEW = re.compile(r'`[^`]+` \((Standards|Spec|Sweep)\) ')
STATUS = {'resolved at': 'resolved', 'withdrawn': 'withdrawn', 'still open after': 'still open',
          'disputed, kept': 'disputed, kept', 'follow-up': 'follow-up'}
KIND = re.compile(r'(?<!\S)Kind: ([^\s.]*)')
ANSWER = re.compile(r'(?:- )?(R[1-9][0-9]*) (fixed at [0-9a-f]{7,40}|disputed)\b')
TAG = re.compile(r'Experiment: ([a-z0-9][a-z0-9.-]{0,63})')
CF4 = re.compile(r'CF4: settings ([0-9a-f]{64}) cases ([0-9a-f]{64}) code ([0-9a-f]{64}) revision ([0-9a-f]{40})')


def first_line(body, after=0):
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    return lines[after] if len(lines) > after else ''


def text(value):
    require(type(value) is str, 'expected a string')
    return value


def when(value, null=False):
    if value is None and null:
        return None
    return M.iso(M.timestamp(value))


def field(value, key):
    """A required field, which may be null: never read a missing one as null."""
    require(key in value, f'missing field {key}')
    return value[key]


def commit(value):
    require(type(value) is str and COMMIT.fullmatch(value), 'invalid commit')
    return value


def number(value):
    """An exact count or amount from a validated export: int when whole."""
    value = Decimal(value) if not isinstance(value, Decimal) else value
    return int(value) if value == value.to_integral_value() else float(value)


class Collector:
    def __init__(self, repo):
        self.repo, self.duplicates, self.sources, self.next_id = repo, 0, {}, 0
        self.completed = {}  # (run, attempt): its completion time, for stage waits only

    def link(self, value):
        prefix = f'https://github.com/{self.repo}/'
        require(type(value) is str and value.lower().startswith(prefix.lower()) and
                re.fullmatch(r'[\x21-\x7e]+', value), 'invalid source link')
        return value

    def source(self, url):
        if url not in self.sources:
            self.sources[url] = f's{len(self.sources) + 1}'
        return self.sources[url]

    def unique(self, seen, key, value):
        """An identical repeat is one item; the same key with other content fails."""
        if key in seen:
            require(seen[key] == value, 'the same item twice with different content')
            self.duplicates += 1
            return False
        seen[key] = value
        return True

    def pages(self, document, n, path, key):
        top, items, seen, cursors, cursor = None, [], {}, set(), None
        while True:
            node = M.graphql(self.repo, document, cursor, n)
            for step in path[:-1]:
                node = obj(node.get(step))
            # Every page must describe the same object as the first, field for field.
            fields = {k: v for k, v in node.items() if k != path[-1]}
            require(top is None or fields == {k: v for k, v in top.items() if k != path[-1]},
                    'a later page describes another object')
            top = top or node
            nodes, following = M.connection(node.get(path[-1]))
            for value in nodes:
                value = obj(value)
                if self.unique(seen, key(value), value):
                    items.append(value)
            if following is None:
                return top, items
            require(following not in cursors, 'repeated cursor')
            cursors.add(following)
            cursor = following

    def comments(self, nodes):
        out = []
        for c in nodes:
            created, updated = when(c.get('createdAt')), when(c.get('updatedAt'))
            out.append({'url': self.link(c.get('url')), 'at': created, 'edited': updated != created,
                        'updated': updated, 'body': text(c.get('body'))})
        return out

    def issue(self, n):
        top, nodes = self.pages(ISSUE, n, ('issue', 'comments'), lambda c: integer(c.get('databaseId')))
        require(top.get('number') == n, 'an answer for another issue')
        parent = field(top, 'parent')
        return {'url': self.link(top.get('url')), 'created': when(top.get('createdAt')),
                'closed': when(field(top, 'closedAt'), True), 'body': text(top.get('body')),
                'spec': None if parent is None else integer(obj(parent).get('number')),
                'comments': self.comments(nodes)}

    def ready(self, n):
        _, events = self.pages(LABELS, n, ('issue', 'timelineItems'), lambda e: json.dumps(e, sort_keys=True, default=str))
        times = []
        for e in events:
            label = text(obj(e.get('label')).get('name'))
            at = when(e.get('createdAt'))
            if label == READY:
                times.append(at)
        return min(times, default=None)

    def pull(self, n):
        top, nodes = self.pages(PULL, n, ('pullRequest', 'comments'), lambda c: integer(c.get('databaseId')))
        require(top.get('number') == n, 'an answer for another pull request')
        merged = when(field(top, 'mergedAt'), True)
        branch = text(top.get('headRefName'))
        require(bool(branch), 'empty branch')
        oid = field(top, 'mergeCommit')
        merge = commit(obj(oid).get('oid')) if merged is not None and oid is not None else None
        return {'number': n, 'url': self.link(top.get('url')), 'created': when(top.get('createdAt')), 'merged': merged,
                'closed': when(field(top, 'closedAt'), True), 'branch': branch, 'base': commit(top.get('baseRefOid')),
                'head': commit(top.get('headRefOid')), 'merge': merge, 'body': text(top.get('body')),
                'comments': self.comments(nodes)}

    def attempt(self, row, rid, k):
        require(integer(row.get('id')) == rid and integer(row.get('run_attempt')) == k, 'an answer for another attempt')
        status = text(row.get('status'))
        self.completed[(rid, k)] = row.get('updated_at') if status == 'completed' else None
        conclusion = field(row, 'conclusion')
        if status == 'completed':
            text(conclusion)
        else:
            conclusion = None
        return {'kind': 'ci_attempt', 'at': when(row.get('run_started_at')), 'url': self.link(row.get('html_url')),
                'run': rid, 'attempt': k, 'head': commit(row.get('head_sha')), 'rerun': k > 1, 'conclusion': conclusion}

    def ci(self, pr):
        seen, page, total = {}, 1, None
        while True:
            path = (f'repos/{self.repo}/actions/workflows/ci.yml/runs?branch={quote(pr["branch"], safe="")}'
                    f'&event=pull_request&per_page=100&page={page}')
            value = obj(M.rest(path))
            count = value.get('total_count')
            require(type(count) is int and count >= 0 and total in (None, count), 'invalid or changed run count')
            total = count
            rows, before = array(value.get('workflow_runs')), len(seen)
            for row in rows:
                row = obj(row)
                self.unique(seen, integer(row.get('id')), row)
            require(page == 1 or len(seen) > before, 'a repeated page of runs')
            require(len(seen) <= total, 'more runs than the count')
            if len(seen) == total:
                break
            require(len(rows) == 100, 'a short page of runs')
            page += 1
        attempts = []
        for rid, row in sorted(seen.items()):
            require(row.get('head_branch') == pr['branch'] and row.get('event') == 'pull_request',
                    'a run of another branch or event')
            linked = {integer(obj(x).get('number')) for x in array(field(row, 'pull_requests'))}
            created = when(row.get('created_at'))
            if linked and pr['number'] not in linked:
                continue  # GitHub ties this run to another PR.
            if not linked and (created < pr['created'] or (pr['closed'] is not None and created > pr['closed'])):
                continue  # Another PR on the same branch, before or after this one.
            latest = integer(row.get('run_attempt'))
            for k in range(1, latest):
                attempts.append(self.attempt(obj(M.rest(f'repos/{self.repo}/actions/runs/{rid}/attempts/{k}')), rid, k))
            attempts.append(self.attempt(row, rid, latest))
        return attempts


def experiment(body):
    lines = [line.strip() for line in body.splitlines()]
    tags = [line for line in lines if line.startswith('Experiment:')]
    cf4s = [line for line in lines if line.startswith('CF4:')]
    if len(tags) != 1 or not TAG.fullmatch(tags[0]):
        return None
    m = CF4.fullmatch(cf4s[0]) if len(cf4s) == 1 else None
    cf4 = None if m is None else {'settings_hash': m[1], 'cases_hash': m[2], 'code_hash': m[3], 'revision': m[4]}
    return {'tag': TAG.fullmatch(tags[0])[1], 'cf4': cf4}


def kind_of(rest):
    marks = KIND.findall(rest)
    if not marks:
        return 'unknown', 'no marker'
    if len(marks) == 1 and marks[0] in KINDS:
        return marks[0], 'marker'
    return 'unknown', 'unrecognised marker'


def pr_events(c, pr, attempts):
    """The PR's events in time order; references hold event objects until ids exist."""
    events = [{'kind': 'pr_opened', 'at': pr['created'], 'url': pr['url'], 'edited': False}]
    events += [{**a, 'edited': False} for a in attempts]
    verdicts, answers = [], []
    for com in pr['comments']:
        line = first_line(com['body'])
        start = VERDICT_START.match(line)
        if not start:
            for raw in com['body'].splitlines():
                m = ANSWER.match(raw.strip())
                if m:
                    answers.append((com, m[1], 'fixed' if m[2].startswith('fixed') else 'disputed'))
            continue
        exact = VERDICT_EXACT.fullmatch(line)
        independent = bool(exact) and first_line(com['body'], 1).startswith(('Full review by ', 'Re-check '))
        verdicts.append({'kind': 'verdict', 'at': com['at'], 'url': com['url'], 'edited': com['edited'],
                         'verdict': start[1], 'head': exact[2] if exact else None, 'independent': independent,
                         'duplicate_of': None, 'body': com['body']})
    rounds, keys = [], {}
    for v in sorted(verdicts, key=lambda v: v['at']):
        if v['independent']:
            key = (v['verdict'], v['head'], v['body'])
            if key in keys:
                v['duplicate_of'] = keys[key]
            else:
                keys[key] = v
                rounds.append(v)
    events += verdicts
    fixes = []
    for i, v in enumerate(rounds):
        if v['verdict'] != 'CHANGES':
            continue
        end = rounds[i + 1]['at'] if i + 1 < len(rounds) else None
        mine, seen = [], set()
        for com, finding, answer in answers:
            if com['at'] > v['at'] and (end is None or com['at'] < end) and (finding, answer) not in seen:
                seen.add((finding, answer))
                mine.append((com, {'finding': finding, 'answer': answer}))
        first = mine[0][0] if mine else None
        fixes.append({'kind': 'fix_round', 'at': first and first['at'], 'url': first and first['url'],
                      'edited': any(com['edited'] for com, _ in mine), 'sort': v['at'],
                      'round': len(fixes) + 1, 'after': v, 'answers': [a for _, a in mine]})
    events += fixes
    if pr['merged'] is not None:
        events.append({'kind': 'merge', 'at': pr['merged'], 'url': pr['url'], 'edited': False, 'commit': pr['merge']})
    order = {id(e): i for i, e in enumerate(events)}
    events.sort(key=lambda e: (e['at'] or e.get('sort') or '', order[id(e)]))
    findings = {}
    for v in rounds:
        for raw in v['body'].splitlines():
            m = FINDING.fullmatch(raw.strip())
            if not m:
                continue
            fid, severity, rest = m[1], m[2], m[3]
            new = NEW.match(rest)
            if new and fid not in findings:
                kind, evidence = kind_of(rest)
                findings[fid] = {'id': fid, 'severity': severity, 'check': new[1], 'kind': kind,
                                 'kind_evidence': evidence, 'raised_by': v, 'statuses': []}
            elif fid in findings:
                status = next((STATUS[s] for s in STATUS if rest.startswith(s)), None)
                if status:
                    findings[fid]['statuses'].append({'verdict': v, 'status': status})
    return events, list(findings.values())


def finish(c, events):
    """Ids, sources and completeness; drops the collection-only keys."""
    for e in events:
        c.next_id += 1
        e['id'] = f'e{c.next_id}'
    out = []
    for e in events:
        source = None if e.get('url') is None else c.source(e['url'])
        completeness = 'unknown' if e['at'] is None else 'edited' if e['edited'] else 'complete'
        item = {'id': e['id'], 'kind': e['kind'], 'at': e['at'], 'source': source, 'completeness': completeness}
        for k, v in e.items():
            if k not in ('id', 'kind', 'at', 'url', 'edited', 'sort', 'body'):
                item[k] = v['id'] if isinstance(v, dict) and 'kind' in v else v
        out.append(item)
    return out


def records(comments):
    """Threads named in launch-fleet records; used in memory only."""
    found = set()
    for com in comments:
        if first_line(com['body']).startswith('launch-fleet:'):
            found.update(THREAD.findall(com['body']))
    return found


def days(events):
    times = sorted(e['at'] for e in events if e['at'] is not None)
    if not times:
        return set()
    day, last, out = M.timestamp(times[0]).date(), M.timestamp(times[-1]).date(), set()
    while day <= last:
        out.add(day.isoformat())
        day += timedelta(days=1)
    return out


def usage_entries(span, valid, tied):
    out = []
    covered = span & set(valid)
    for provider, unit in USAGE:
        rows = [row for date, prov, row in tied if prov == provider and date in covered]
        if not covered:
            status, value = 'absent', None
        elif not rows:
            status, value = 'unattributed', None
        elif any(row[unit] is None for row in rows):
            status, value = 'unknown', None
        else:
            status, value = 'known', number(sum(Decimal(str(row[unit])) for row in rows))
        out.append({'provider': provider, 'unit': unit, 'status': status, 'value': value,
                    'missing_days': sorted(span - set(valid)), 'attribution': 'thread-record'})
    return out


def collect(repo, tickets, usage_paths, outcome_export=None, policy=None, previous=None, stage_export=None,
            read_at=None):
    c = Collector(repo)
    inventory = M.collect_prs(repo)
    closing = {t: sorted(n for n, p in inventory.items() if t in p['tickets']) for t in tickets}
    issues = {t: c.issue(t) for t in tickets}
    ready = {t: c.ready(t) for t in tickets}
    specs = {s: c.issue(s) for s in sorted({i['spec'] for i in issues.values() if i['spec'] is not None})}
    pulls = {n: c.pull(n) for n in sorted({n for ns in closing.values() for n in ns})}
    owners = {}

    def own(threads, owner):
        for t in threads:
            owners.setdefault(t, set()).add(owner)
    doc_specs, doc_tickets, doc_prs, spans = [], [], [], {}
    for s, spec in specs.items():
        events = [{'kind': 'grill', 'at': None, 'url': spec['url'], 'edited': False, 'path': p}
                  for p in dict.fromkeys(GRILL.findall(spec['body']))]
        events.append({'kind': 'spec', 'at': spec['created'], 'url': spec['url'], 'edited': False})
        for com in spec['comments']:
            line = first_line(com['body'])
            if line.startswith('**Plan graph approved'):
                rev = re.search(r'\brevision ([1-9][0-9]*)\b', line)
                events.append({'kind': 'plan_graph', 'at': com['at'], 'url': com['url'], 'edited': com['edited'],
                               'revision': int(rev[1]) if rev else None})
        own(records(spec['comments']), ('spec', s))
        doc_specs.append({'spec': s, 'events': finish(c, events), 'usage': None})
        spans[('spec', s)] = days(doc_specs[-1]['events'])
    for t in tickets:
        i = issues[t]
        events = [{'kind': 'ticket', 'at': i['created'], 'url': i['url'], 'edited': False}]
        if ready[t]:
            events.append({'kind': 'ready', 'at': ready[t], 'url': i['url'], 'edited': False})
        for com in i['comments']:
            if STARTED.match(first_line(com['body'])):
                events.append({'kind': 'builder_start', 'at': com['at'], 'url': com['url'], 'edited': com['edited']})
        own(records(i['comments']), ('ticket', t))
        events.sort(key=lambda e: e['at'])
        merged = any(pulls[n]['merged'] for n in closing[t])
        spec_events = next((s['events'] for s in doc_specs if s['spec'] == i['spec']), [])
        missing = {'no ready label': not ready[t],
                   'no builder start record': not any(e['kind'] == 'builder_start' for e in events),
                   'no pull request': not closing[t], 'no merge': not merged, 'no spec': i['spec'] is None,
                   'no grill path': not any(e['kind'] == 'grill' for e in spec_events),
                   'no plan graph approval': not any(e['kind'] == 'plan_graph' for e in spec_events)}
        doc_tickets.append({'ticket': t, 'spec': i['spec'],
                            'state': 'merged' if merged else 'closed' if i['closed'] else 'open',
                            'pull_requests': closing[t], 'events': finish(c, events),
                            'gaps': [g for g in GAPS if missing[g]], 'usage': None})
    run_owner = {}
    for n, pr in pulls.items():
        attempts = c.ci(pr)
        for a in attempts:
            require(run_owner.setdefault(a['run'], n) == n, 'a run matches two pull requests')
        events, findings = pr_events(c, pr, attempts)
        for t in inventory[n]['tickets']:
            own(records(pr['comments']), ('ticket', t))
        events = finish(c, events)
        for f in findings:
            f['raised_by'] = f['raised_by']['id']
            f['statuses'] = [{'verdict': s['verdict']['id'], 'status': s['status']} for s in f['statuses']]
        doc_prs.append({'number': n, 'tickets': inventory[n]['tickets'],
                        'state': 'merged' if pr['merged'] else 'closed' if pr['closed'] else 'open',
                        'revisions': {'base': pr['base'], 'head': pr['head'], 'merge': pr['merge']},
                        'experiment': experiment(pr['body']), 'events': events, 'findings': findings})
    pr_by = {p['number']: p for p in doc_prs}
    for t in doc_tickets:
        spans[('ticket', t['ticket'])] = days(t['events'] + [e for n in t['pull_requests'] for e in pr_by[n]['events']])
    valid, daily, tied = [], [], {}
    for path in usage_paths:
        try:
            data = M.read_usage(path)
        except ReadError:
            daily.append({'date': None, 'merged_prs': None, 'totals': None})
            continue
        date = data['date']
        require(date not in valid, 'two usage exports for one day')
        valid.append(date)
        merges = sum(1 for p in inventory.values() if p['merged'] is not None and p['merged'].date().isoformat() == date)
        totals = {}
        for provider, units in M.USAGE_UNITS.items():
            rows = data[provider] if provider != 'sandbox' else [data['sandbox']]
            totals[provider] = {u: M.amount(sum(Decimal(str(r[u])) for r in rows) if all(r[u] is not None for r in rows)
                                            else None, merges) for u in units}
            for row in rows if provider != 'sandbox' else []:
                who = owners.get(row['thread'], set())
                if len(who) == 1:  # Tied to exactly one ticket or spec, never shared or guessed.
                    tied.setdefault(next(iter(who)), []).append((date, provider, row))
        daily.append({'date': date, 'merged_prs': merges, 'totals': totals})
    for entry, key in [(s, ('spec', s['spec'])) for s in doc_specs] + [(t, ('ticket', t['ticket'])) for t in doc_tickets]:
        entry['usage'] = usage_entries(spans[key], valid, tied.get(key, []))
    doc = {'schema': SCHEMA, 'repo': repo, 'history': 'unknown', 'duplicates': c.duplicates, 'specs': doc_specs,
           'tickets': doc_tickets, 'pull_requests': doc_prs, 'daily_usage': daily,
           'sources': {key: url for url, key in c.sources.items()}}
    if outcome_export is not None:
        outcome_export.update(collect_outcomes(doc, pulls, inventory, policy, previous))
    if stage_export is not None:
        stage_export.update(collect_stage_waits(c, doc, issues, specs, pulls, inventory, read_at))
    return doc


# --- The contract's validator ---------------------------------------------

BASE_KEYS = ('id', 'kind', 'at', 'source', 'completeness')
EVENT_KEYS = {'grill': ('path',), 'spec': (), 'plan_graph': ('revision',), 'ticket': (), 'ready': (),
              'builder_start': (), 'pr_opened': (), 'ci_attempt': ('run', 'attempt', 'head', 'rerun', 'conclusion'),
              'verdict': ('verdict', 'head', 'independent', 'duplicate_of'), 'fix_round': ('round', 'after', 'answers'),
              'merge': ('commit',)}
WHERE = {'spec': {'grill', 'spec', 'plan_graph'}, 'ticket': {'ticket', 'ready', 'builder_start'},
         'pr': {'pr_opened', 'ci_attempt', 'verdict', 'fix_round', 'merge'}}


def exact(value, keys, where):
    require(type(value) is dict and list(value) == list(keys), f'{where}: unexpected, missing or reordered fields')


def count(value, low=1):
    require(type(value) is int and value >= low, 'expected an integer')
    return value


def amount(value):
    require(type(value) in (int, float, Decimal) and value >= 0, 'expected a nonnegative number')


def maybe_commit(value):
    if value is not None:
        commit(value)


def day(value):
    require(type(value) is str and re.fullmatch(r'\d{4}-\d\d-\d\d', value), 'invalid date')
    M.day_arg(value)


def validate(doc):
    exact(doc, ('schema', 'repo', 'history', 'duplicates', 'specs', 'tickets', 'pull_requests', 'daily_usage',
                'sources'), 'document')
    require(doc['schema'] == SCHEMA, 'not a closedwiz.journey.v1 document')
    require(doc['history'] == 'unknown', 'historical completeness is always unknown')
    M.repo_arg(text(doc['repo']))
    count(doc['duplicates'], 0)
    sources = obj(doc['sources'])
    for key, url in sources.items():
        require(re.fullmatch(r's[1-9][0-9]*', key) and type(url) is str and
                url.lower().startswith(f'https://github.com/{doc["repo"].lower()}/'), 'invalid source')
    require(not THREAD.search(json.dumps(doc, default=str)), 'a thread identifier is saved')
    ids = set()

    def events(items, where):
        out = {}
        for e in array(items):
            kind = obj(e).get('kind')
            require(kind in WHERE[where], f'event kind {kind!r} is not allowed here')
            exact(e, BASE_KEYS + EVENT_KEYS[kind], f'{kind} event')
            require(type(e['id']) is str and re.fullmatch(r'e[1-9][0-9]*', e['id']) and e['id'] not in ids,
                    'invalid or repeated event id')
            ids.add(e['id'])
            if e['at'] is not None:
                when(e['at'])
            require(e['source'] is None or e['source'] in sources, 'unknown source')
            require(e['completeness'] in ('complete', 'edited', 'unknown'), 'invalid completeness')
            require((e['at'] is None) == (e['completeness'] == 'unknown'), 'completeness disagrees with time')
            # Only a grill and an unanswered fix round have no time; only the latter has no source.
            unanswered = kind == 'fix_round' and array(e['answers']) == []
            require(e['at'] is not None or kind == 'grill' or unanswered, f'a {kind} event needs its time')
            require(e['source'] is not None or unanswered, f'a {kind} event needs its source')
            if kind == 'grill':
                require(type(e['path']) is str and GRILL.fullmatch(e['path']), 'invalid grill path')
            elif kind == 'plan_graph':
                require(e['revision'] is None or count(e['revision']), 'invalid revision')
            elif kind == 'ci_attempt':
                count(e['run'])
                count(e['attempt'])
                commit(e['head'])
                require(e['rerun'] is (e['attempt'] > 1), 'rerun disagrees with attempt')
                require(e['conclusion'] is None or type(e['conclusion']) is str, 'invalid conclusion')
            elif kind == 'verdict':
                require(e['verdict'] in ('APPROVE', 'CHANGES') and type(e['independent']) is bool, 'invalid verdict')
                maybe_commit(e['head'])
                require(not e['independent'] or e['head'] is not None, 'an independent verdict names its head')
                d = e['duplicate_of']
                require(d is None or (e['independent'] and d in out and out[d]['kind'] == 'verdict' and
                                      out[d]['independent'] and out[d]['duplicate_of'] is None and
                                      (out[d]['verdict'], out[d]['head']) == (e['verdict'], e['head'])),
                        'invalid duplicate verdict')
            elif kind == 'fix_round':
                count(e['round'])
                a = out.get(e['after'])
                require(a is not None and rounds_of(a) and a['verdict'] == 'CHANGES', 'a fix round follows a CHANGES round')
                for answer in array(e['answers']):
                    exact(answer, ('finding', 'answer'), 'answer')
                    require(type(answer['finding']) is str and re.fullmatch(r'R[1-9][0-9]*', answer['finding']) and
                            answer['answer'] in ('fixed', 'disputed'), 'invalid answer')
            elif kind == 'merge':
                maybe_commit(e['commit'])
            out[e['id']] = e
        return out

    def usage(items):
        items = array(items)
        require(len(items) == len(USAGE), 'usage lists every provider and unit')
        for (provider, unit), u in zip(USAGE, items):
            exact(u, ('provider', 'unit', 'status', 'value', 'missing_days', 'attribution'), 'usage')
            require((u['provider'], u['unit']) == (provider, unit), 'usage out of order')
            require(u['status'] in ('known', 'unknown', 'unattributed', 'absent'), 'invalid usage status')
            if u['status'] == 'known':
                amount(u['value'])
            else:
                require(u['value'] is None, 'only a known usage has a value')
            for d in array(u['missing_days']):
                day(d)
            require(u['missing_days'] == sorted(set(u['missing_days'])), 'missing days unsorted or repeated')
            require(u['attribution'] == 'thread-record', 'attribution is only by thread record')

    specs = set()
    for s in array(doc['specs']):
        exact(s, ('spec', 'events', 'usage'), 'spec')
        require(count(s['spec']) not in specs, 'a spec twice')
        specs.add(s['spec'])
        events(s['events'], 'spec')
        usage(s['usage'])
    prs, attempts, run_owner = {}, set(), {}
    for p in array(doc['pull_requests']):
        exact(p, ('number', 'tickets', 'state', 'revisions', 'experiment', 'events', 'findings'), 'pull request')
        count(p['number'])
        require(p['number'] not in prs, 'a pull request twice')
        prs[p['number']] = p
        require(bool(array(p['tickets'])) and all(count(t) for t in p['tickets']), 'invalid tickets')
        require(p['state'] in ('merged', 'closed', 'open'), 'invalid state')
        exact(p['revisions'], ('base', 'head', 'merge'), 'revisions')
        commit(p['revisions']['base'])
        commit(p['revisions']['head'])
        maybe_commit(p['revisions']['merge'])
        require(p['revisions']['merge'] is None or p['state'] == 'merged', 'only a merged PR has a merge commit')
        x = p['experiment']
        if x is not None:
            exact(x, ('tag', 'cf4'), 'experiment')
            require(type(x['tag']) is str and TAG.fullmatch('Experiment: ' + x['tag']), 'invalid tag')
            if x['cf4'] is not None:
                exact(x['cf4'], ('settings_hash', 'cases_hash', 'code_hash', 'revision'), 'cf4')
                for k in ('settings_hash', 'cases_hash', 'code_hash'):
                    require(type(x['cf4'][k]) is str and re.fullmatch(r'[0-9a-f]{64}', x['cf4'][k]), 'invalid hash')
                commit(x['cf4']['revision'])
        evs = events(p['events'], 'pr')
        changes = [e for e in evs.values() if rounds_of(e) and e['verdict'] == 'CHANGES']
        fixes = [e for e in evs.values() if e['kind'] == 'fix_round']
        require([(f['after'], f['round']) for f in fixes] == [(c['id'], k) for k, c in enumerate(changes, 1)],
                'one fix round follows each CHANGES round, numbered in order')
        for e in evs.values():
            if e['kind'] == 'ci_attempt':
                require((e['run'], e['attempt']) not in attempts, 'a run attempt twice')
                attempts.add((e['run'], e['attempt']))
                require(run_owner.setdefault(e['run'], p['number']) == p['number'], 'one run on two pull requests')
        found = set()
        for f in array(p['findings']):
            exact(f, ('id', 'severity', 'check', 'kind', 'kind_evidence', 'raised_by', 'statuses'), 'finding')
            require(type(f['id']) is str and re.fullmatch(r'R[1-9][0-9]*', f['id']) and f['id'] not in found,
                    'invalid or repeated finding')
            found.add(f['id'])
            require(f['severity'] in ('high', 'medium', 'low') and f['check'] in ('Standards', 'Spec', 'Sweep'),
                    'invalid severity or check')
            require(f['kind'] in KINDS and f['kind_evidence'] in ('marker', 'no marker', 'unrecognised marker'),
                    'invalid kind')
            require(f['kind_evidence'] == 'marker' or f['kind'] == 'unknown', 'a kind needs its marker')
            require(f['raised_by'] in evs and rounds_of(evs[f['raised_by']]), 'a finding is raised by a review round')
            for st in array(f['statuses']):
                exact(st, ('verdict', 'status'), 'status')
                require(st['verdict'] in evs and rounds_of(evs[st['verdict']]) and st['status'] in STATUS.values(),
                        'invalid finding status')
    tickets, listed = set(), {}
    for t in array(doc['tickets']):
        exact(t, ('ticket', 'spec', 'state', 'pull_requests', 'events', 'gaps', 'usage'), 'ticket')
        require(count(t['ticket']) not in tickets, 'a ticket twice')
        tickets.add(t['ticket'])
        require(t['spec'] is None or t['spec'] in specs, 'a ticket names a spec the document lacks')
        require(t['spec'] is None or count(t['spec']), 'invalid spec')
        require(t['state'] in ('merged', 'closed', 'open'), 'invalid state')
        require(len(set(array(t['pull_requests']))) == len(t['pull_requests']), 'a ticket names a PR twice')
        for n in t['pull_requests']:
            require(n in prs and t['ticket'] in prs[n]['tickets'], 'a ticket names a PR that does not close it')
        listed[t['ticket']] = set(t['pull_requests'])
        events(t['events'], 'ticket')
        require(array(t['gaps']) == [g for g in GAPS if g in t['gaps']], 'invalid gaps')
        usage(t['usage'])
    for n, p in prs.items():
        for t in p['tickets']:
            require(t not in listed or n in listed[t], 'a collected ticket omits a PR that closes it')
    for d in array(doc['daily_usage']):
        exact(d, ('date', 'merged_prs', 'totals'), 'daily usage')
        if d['date'] is None:
            require(d['merged_prs'] is None and d['totals'] is None, 'an invalid export has no values')
            continue
        day(d['date'])
        count(d['merged_prs'], 0)
        exact(d['totals'], tuple(M.USAGE_UNITS), 'totals')
        for provider, units in M.USAGE_UNITS.items():
            exact(d['totals'][provider], units, 'totals')
            for u in units:
                v = d['totals'][provider][u]
                exact(v, ('total', 'per_merged_pr'), 'amount')
                for x in v.values():
                    require(x is None or amount(x) is None, 'invalid amount')
                require(v['per_merged_pr'] is None or (v['total'] is not None and d['merged_prs'] > 0),
                        'a ratio needs a total and merges')


def rounds_of(e):
    return e['kind'] == 'verdict' and e['independent'] and e['duplicate_of'] is None


# --- EB5 sidecar collection; v1 and CF4 remain unchanged ---------------------

def outcome_contract():
    spec = importlib.util.spec_from_file_location('eb_outcome_contract', HERE/'experiment_contract.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_outcome_export(export, doc):
    validate(doc)
    E = outcome_contract()
    M.exact(export, ('journey', 'sources', 'defect_policy'))
    require(not THREAD.search(json.dumps(export, default=float, allow_nan=False)), 'operational identity forbidden')
    sources, policy = obj(export['sources']), export['defect_policy']
    for key, url in sources.items():
        require(re.fullmatch(r's[1-9][0-9]*', key) and type(url) is str and
                re.fullmatch(r'https://github\.com/'+re.escape(doc['repo'])+
                             r'/(issues|pull|actions/runs)/[1-9][0-9]*(?:[\w/#?=.-]*)', url),
                'invalid outcome source')
    if policy is not None:
        M.exact(policy, ('rule', 'followup_hours', 'deduplication', 'unknown_attribution'))
        require(policy['rule'] == 'explicit-causal-fix-link-v1' and
                policy['deduplication'] == 'root-cause-per-merge' and
                policy['unknown_attribution'] == 'retain-unknown', 'unsupported defect policy')
        require(type(policy['followup_hours']) in (int, float, Decimal) and
                0 < policy['followup_hours'] < float('inf'), 'invalid follow-up hours')
    try:
        E.validate_outcomes(export['journey'], json.loads(json.dumps(doc, default=float, allow_nan=False)),
                            json.loads(json.dumps(policy, default=float, allow_nan=False)), sources)
    except (ValueError, KeyError, TypeError) as e:
        raise ReadError('invalid outcome sidecar: '+str(e)) from e

    if policy is None:
        require(all(m['defects'] == {'status':'unknown','observed_until':None,'events':[], 'resolutions':[]}
                    for m in array(export['journey']['measurements'])), 'defects need a frozen policy')


def main_red_attempt(repo, url, at):
    """Verify a pinned attempt, or the earliest surviving failed run attempt.

    The current conclusion and start belong to the latest attempt. Run creation
    is shared identity, not failure time; bind occurrence to the selected start.
    """
    base = f'https://github.com/{repo}/actions/runs/'
    match = re.fullmatch(re.escape(base)+r'([1-9][0-9]*)(?:/attempts/([1-9][0-9]*))?', url)
    require(match is not None, 'main-red needs a workflow run or attempt')
    rid = int(match[1])
    path = f'repos/{repo}/actions/runs/{rid}'
    current = obj(M.rest(path))
    latest = integer(current.get('run_attempt'))
    created = when(current.get('created_at'))
    latest_started = when(current.get('run_started_at'))

    def failure(row, attempt):
        require(integer(row.get('id')) == rid and integer(row.get('run_attempt')) == attempt and
                row.get('head_branch') == 'main' and row.get('event') == 'push' and
                row.get('path') == '.github/workflows/ci.yml' and when(row.get('created_at')) == created,
                'not the cited main CI run/attempt')
        started = when(row.get('run_started_at'))
        require(created <= started <= latest_started, 'inconsistent main CI attempt timing')
        conclusion = field(row, 'conclusion')
        require((conclusion is None and attempt == latest) or
                (type(conclusion) is str and bool(conclusion)), 'invalid or incomplete attempt conclusion')
        return started, conclusion in ('failure', 'timed_out')

    failure(current, latest)  # Check the run binding even when selecting history.
    attempts = range(1, latest+1)
    if match[2] is not None:
        pinned = int(match[2])
        require(pinned <= latest, 'cited attempt exceeds the observed run')
        attempts = (pinned,)
    previous_started = created
    for attempt in attempts:
        row = current if attempt == latest else obj(M.rest(f'{path}/attempts/{attempt}'))
        started, failed = failure(row, attempt)
        require(previous_started <= started, 'inconsistent main CI attempt chronology')
        previous_started = started
        if failed:
            require(started == at, 'main-red occurrence differs from selected attempt start')
            return f'{base}{rid}/attempts/{attempt}'
    raise ReadError('not the cited main-red failure')


def collect_outcomes(doc, pulls, inventory, policy=None, previous=None):
    """Parse sourced receipts/causal observations from existing PR comments.

    Follow-up coverage is an explicit sourced attestation, never inferred from
    successful reads or the absence of a known defect. No experiment is assigned.
    """
    E = outcome_contract()
    doc = json.loads(json.dumps(doc, default=float, allow_nan=False))
    policy = json.loads(json.dumps(policy, default=float, allow_nan=False))
    result = {'journey': E.migrate_journey(doc), 'sources': {}, 'defect_policy': policy}
    old = {}
    if previous is not None:
        prior_doc, prior = previous
        validate(prior_doc); validate_outcome_export(prior, prior_doc)
        prior_policy = json.loads(json.dumps(prior['defect_policy'], default=float, allow_nan=False))
        require(prior_doc['repo'] == doc['repo'] and prior_policy == policy,
                'previous repository/policy changed')
        require({t['ticket'] for t in prior_doc['tickets']} <= {t['ticket'] for t in doc['tickets']},
                'known ticket removed')
        old = {m['pr']: m for m in prior['journey']['measurements']}
        require(set(old) <= set(pulls), 'known PR removed')
        result['sources'].update(prior['sources'])
    def source(url):
        for key, value in result['sources'].items():
            if value == url: return key
        key = f's{len(result["sources"])+1}'
        while key in result['sources']: key = f's{int(key[1:])+1}'
        result['sources'][key] = url
        return key
    for row in result['journey']['measurements']:
        pr = pulls[row['pr']]
        retained = old.get(row['pr'])
        if retained:
            for key in ('first_push', 'merge', 'defects'):
                row[key] = json.loads(json.dumps(retained[key]))
        candidates = []
        for com in pr['comments']:
            if com['edited']: continue  # an edit cannot attest the original push
            match = re.fullmatch(r'First successful push: ([0-9a-f]{40}) at (\S+)', com['body'].strip())
            if match:
                at = when(match[2])
                require(at <= com['at'], 'push receipt precedes its claimed push')
                candidates.append((at, com['url']))
        times = {at for at, _ in candidates}
        # Multiple distinct first-push assertions are ambiguous, not a minimum.
        if row['first_push']['status'] == 'observed':
            require(not times or times == {row['first_push']['at']}, 'established first push changed')
        elif len(times) == 1:
            at, url = min(candidates)
            row['first_push'] = {'status':'observed','at':at,'kind':'builder-push-receipt',
                                 'source':source(url),'coverage':'partial'}
        if pr['merged'] and pr['merge'] and pr['merged'] <= M.iso(datetime.now(timezone.utc).replace(microsecond=0)):
            if row['merge']['status'] == 'verified':
                require((row['merge']['at'], row['merge']['commit']) == (pr['merged'], pr['merge']),
                        'verified merge changed')
            else:
                row['merge'] = {'status':'verified','at':pr['merged'],'commit':pr['merge'],
                                'source':source(pr['url']),
                                'read_at':M.iso(datetime.now(timezone.utc).replace(microsecond=0))}
        elif pr['merged'] is None:
            require(row['merge']['status'] != 'verified', 'verified merge disappeared')
            row['merge']['status'] = 'unmerged'
        if policy is None: continue
        defects = row['defects']
        by_key = {e['key']:e for e in defects['events']}
        established = set(by_key)
        causal_sources = {key:{result['sources'][e['source']]} for key,e in by_key.items()}
        resolved = {e['key']:e for e in defects['resolutions']}
        until = defects['observed_until']
        comments = sorted(pr['comments'], key=lambda c:(c['at'], c['url']))
        for com in comments:
            prefix = next((p for p in ('EB defect: ', 'EB attribution: ', 'EB follow-up: ')
                           if com['body'].startswith(p)), None)
            if prefix is None: continue
            require(not com['edited'], 'edited outcome evidence')
            value = obj(M.load(com['body'][len(prefix):].strip()))
            require(value.get('policy') == E.digest(policy), 'outcome policy mismatch')
            if prefix == 'EB follow-up: ':
                M.exact(value, ('policy','observed_until'))
                at = when(value['observed_until'])
                require(at <= com['at'], 'future follow-up attestation')
                until = max(until or at, at)
                source(com['url'])
                continue
            M.exact(value, ('policy','root','at','attribution','evidence') +
                    (('kind','caused_by') if prefix == 'EB defect: ' else ()))
            integer(value['root']); at = when(value['at'])
            require(at <= com['at'], 'future outcome observation')
            key = f'issue-{value["root"]}'
            if prefix == 'EB defect: ':
                require(row['merge']['status'] == 'verified', 'defect without verified merge')
                if not (row['merge']['at'] <= at <= M.iso(M.timestamp(row['merge']['at'])+
                        timedelta(hours=float(policy['followup_hours'])))):
                    continue
            # A causal record is distinct from the cited run/fix. Verify both.
            url = value['evidence']
            c = Collector(doc['repo']); c.link(url)
            if prefix == 'EB defect: ':
                require(value['caused_by'] == row['pr'] and type(value['caused_by']) is int,
                        'defect causal link mismatch')
                if value['kind'] == 'main-red':
                    source(main_red_attempt(doc['repo'], url, at))
                else:
                    require(value['kind'] == 'later-defect-fix' and
                            url == f'https://github.com/{doc["repo"]}/issues/{value["root"]}',
                            'later fix needs its root issue')
                    require(any(value['root'] in p['tickets'] and p['merged'] is not None and
                                M.iso(p['merged']) == at for p in inventory.values()), 'later fix has no verified merge')
                source(url)
                causal_sources.setdefault(key, set()).add(com['url'])
                event = {'key':key,'kind':value['kind'],'at':at,'attribution':value['attribution'],
                         'source':source(com['url'])}
                if key not in by_key:
                    by_key[key] = event; defects['events'].append(event)
                else:
                    original = by_key[key]
                    require(not (key in established and original['kind'] != 'main-red' and
                                 event['kind'] == 'main-red'),
                            'new main-red evidence cannot replace an established root; contract owner disposition required')
                    require(original['attribution'] == event['attribution'],
                            'attribution changes need a separate resolution')
                    # Before the first export, retain the main-red harm signal
                    # even when its later fix was reported first. Published
                    # observations remain immutable on every resumed read.
                    def rank(e):
                        return (e['kind'] != 'main-red', e['at'], result['sources'][e['source']])
                    if key not in established and rank(event) < rank(original):
                        original.clear()
                        original.update(event)
            else:
                require(key in by_key, 'resolution without observation')
                # Either verified observation can establish the same root's
                # causal link; canonicalizing its kind cannot erase that link.
                require(url in causal_sources[key], 'resolution source mismatch')
                event = {'key':key,'at':at,'attribution':value['attribution'],'source':source(com['url'])}
                require(key not in resolved or resolved[key] == event, 'attribution resolution changed')
                if key not in resolved:
                    resolved[key] = event; defects['resolutions'].append(event)
        if until is not None:
            require(row['merge']['status'] == 'verified', 'follow-up without verified merge')
            defects['observed_until'] = until
            defects['status'] = ('mature' if M.timestamp(until) >= M.timestamp(row['merge']['at'])+
                                  timedelta(hours=float(policy['followup_hours'])) else 'unmatured')
    validate_outcome_export(result, doc)
    return result


def outcome_rows(doc, export):
    """Per-PR seam for EB8; no averaging or exclusion of unfinished work."""
    validate_outcome_export(export, doc)
    E = outcome_contract()
    rows = []
    tickets = {t['ticket']:t for t in doc['tickets']}
    for m, p in zip(export['journey']['measurements'], doc['pull_requests']):
        push, merge = m['first_push'], m['merge']
        hours = None
        if push['status'] == 'observed' and merge['status'] == 'verified':
            hours = round((M.timestamp(merge['at'])-M.timestamp(push['at'])).total_seconds()/3600, 6)
        start_hours = None
        starts = [e['at'] for n in p['tickets'] if n in tickets for e in tickets[n]['events']
                  if e['kind']=='builder_start']
        if starts and merge['status']=='verified' and max(starts)<=merge['at']:
            start_hours = round((M.timestamp(merge['at'])-M.timestamp(min(starts))).total_seconds()/3600,6)
        attrs = E.defect_attributions(m['defects'])
        rows.append({'pr':p['number'],'state':p['state'],'tickets':p['tickets'],
                     'first_push_to_merged_hours':hours, 'builder_start_to_merged_hours':start_hours,
                     'independent_rounds':len(m['rounds']) if m['rounds'] else None,
                     'defect_followup':m['defects']['status'],
                     'defects':{k:sum(a == k for a in attrs.values()) for k in ('attributable','unattributed','unknown')}})
    return rows


# --- TL2 stage waits (#2337): an explicit sidecar; v1, CF4 and EB5 unchanged ---

STAGE_SCHEMA, STAGE_BENCH = 'closedwiz.journey.stage-waits.v1', 'closedwiz.journey.stage-bench.v1'
STAGE_LABELS = ('query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name)'
                '{issue(number:$number){number timelineItems(itemTypes:[LABELED_EVENT,UNLABELED_EVENT],first:100,'
                'after:$cursor){nodes{__typename ... on LabeledEvent{createdAt label{name}} ... on UnlabeledEvent'
                '{createdAt label{name}}} pageInfo{hasNextPage endCursor}}}}}')
GATES = ('query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name)'
         '{issue(number:$number){number labels(first:100){nodes{name} pageInfo{hasNextPage endCursor}} '
         'blockedBy(first:100,after:$cursor){nodes{number url state closedAt} pageInfo{hasNextPage endCursor}}}}}')
# fleet-tick's frontier labels: ready-for-agent on, none of the rest.
CLOSING_LABELS = ('needs-info', 'needs-triage', 'ready-for-human', 'wontfix', 'held')
STATES = ('ended', 'open', 'unknown', 'gated', 'stale')
RESULTS = ('missed', 'not missed', 'pending', 'unknown', 'gated', 'stale')
STAGE_GAPS = ('label history incomplete', 'head history incomplete', 'no plan approval', 'approval not current',
              'blocker merge unverified',
              'start record outside its gate', 'edited record', 'reviewer start unconfirmed', 'disputed without fix',
              'no linked disposition', 'no green completion time', 'ci order unknown', 'no end record',
              'no longer current', 'held')
REVIEW_RECORD = re.compile(r'launch-fleet: (review starting|review started|re-check sent) ([0-9a-f]{7,40})\b')
FIXED = re.compile(r'(?:- )?(R[1-9][0-9]*) fixed at ([0-9a-f]{7,40})\b')
DISPUTED = re.compile(r'(?:- )?R[1-9][0-9]* disputed\b')
DEFERRAL = re.compile(r'investigation continues|still investigating|no decision|pending|deferred', re.I)
REVISION = HERE.parent.parent / 'skills' / 'plan-graph' / 'revision.sh'
FINGERPRINT = re.compile(r'^Fingerprint: `([0-9a-f]{64})`$', re.M)
CORRECTED = ('resolved at', 'withdrawn', 'follow-up')  # a finding listed this way needs no fix
ZERO = '0' * 40
PR_STAGES = ('reviewer_start', 'fix_after_changes', 'merge')


def limits_module():
    spec = importlib.util.spec_from_file_location('factory_limits', HERE / 'limits.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def journey_hash(doc):
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(',', ':'), default=float,
                                     allow_nan=False).encode()).hexdigest()


def comment_id(url):
    return int(url.rsplit('#issuecomment-', 1)[1])


def interval_key(stage, owner, head, origin, start):
    """Identity from immutable evidence: later history never renames an interval."""
    parts = [stage, owner] + ([head] if head else []) + ([f'c{origin}'] if origin is not None else [])
    if stage in ('reviewer_start', 'merge'):
        parts.append(start['at'] if start else '-')
    return ':'.join(parts)


def run_clock(holds, start, end, read_at):
    """(state, clock_from, gaps) after holds: the clock restarts at each release inside the interval."""
    if any(h is None for h in holds):
        return 'unknown', None, ['label history incomplete']
    stop, latest = (end['at'], end['latest']) if end else (read_at, read_at)
    began = start['at']
    for on, off in (span for spans in holds for span in spans):
        if on <= latest and (off is None or off > stop):
            if on > stop or (off is not None and off <= latest):
                return 'unknown', None, ['edited record']  # A hold inside an end's uncertainty.
            return 'gated', None, ['held']
        if off is not None and began < off <= stop:
            began = off
    return ('ended' if end else 'open'), began, []


def intersect(a, b):
    """Overlap of two lists of (start, end|None, source) windows; the later start keeps its source."""
    out = []
    for s1, e1, src1 in a:
        for s2, e2, src2 in b:
            start, src = (s1, src1) if s1 >= s2 else (s2, src2)
            end = min((e for e in (e1, e2) if e is not None), default=None)
            if end is None or start < end:
                out.append((start, end, src))
    return sorted(out)


def current_fingerprint(repo, spec):
    """plan-graph's own revision.sh (read-only gh reads), hashed as its approvals record; None if unreadable."""
    try:
        p = subprocess.run(['sh', str(REVISION), str(spec)], capture_output=True, timeout=120,
                           env={**os.environ, 'GH_REPO': repo})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return hashlib.sha256(p.stdout).hexdigest() if p.returncode == 0 and p.stdout else None


def substantive(ruling, question_url):
    """A ruling that answers: no deferral marker, and words beyond its prefix, link and status lines."""
    text = ruling['body'].replace(question_url, ' ').replace(f'#issuecomment-{comment_id(question_url)}', ' ')
    text = re.sub(r'^Disposition:.*$', ' ', text, flags=re.M).replace('Orchestrator ruling', ' ', 1)
    return not DEFERRAL.search(ruling['body']) and re.search(r'[A-Za-z0-9]{2,}', re.sub(r'\bon\b', ' ', text))


def stage_reads(c, n):
    """A ticket's gate-label history, current labels and native blockers, every page."""
    top, items = c.pages(STAGE_LABELS, n, ('issue', 'timelineItems'), lambda e: json.dumps(e, sort_keys=True))
    require(top.get('number') == n, 'an answer for another issue')
    history = []
    for e in items:
        require(e.get('__typename') in ('LabeledEvent', 'UnlabeledEvent'), 'invalid label event')
        label = field(e, 'label')
        history.append((when(e.get('createdAt')), e['__typename'] == 'LabeledEvent',
                        None if label is None else text(obj(label).get('name'))))
    top, blockers = c.pages(GATES, n, ('issue', 'blockedBy'), lambda b: integer(b.get('number')))
    require(top.get('number') == n, 'an answer for another issue')
    nodes, more = M.connection(top.get('labels'))
    require(more is None, 'more labels than one page')
    current = {text(obj(x).get('name')) for x in nodes}
    out = []
    for b in blockers:
        closed = when(field(b, 'closedAt'), True)
        require(b.get('state') in ('OPEN', 'CLOSED') and (b['state'] == 'CLOSED') == (closed is not None),
                'invalid blocker state')
        c.link(b.get('url'))
        out.append((integer(b['number']), closed))
    return history, current, out


def head_windows(c, branch, head):
    """Each head's spans as the branch tip, from the repository's push activity; None if the chain breaks."""
    ref = 'refs/heads/' + branch
    rows = array(M.rest(f'repos/{c.repo}/activity?ref={quote(ref, safe="")}&per_page=100'))
    if not rows or len(rows) >= 100:
        return None  # No activity, or more than one page: the head history is not complete.
    events = []
    for r in rows:
        r = obj(r)
        require(r.get('ref') == ref, 'activity of another ref')
        events.append((when(r.get('timestamp')), integer(r.get('id')), commit(r.get('before')), commit(r.get('after'))))
    windows, current = [], ZERO
    for at, _, before, after in sorted(events):
        if before != current:
            return None  # A missing push: the chain from the branch's creation is broken.
        if windows and windows[-1][1] is None:
            windows[-1][1] = at
        if after != ZERO:
            windows.append([after, None, at])
        current = after
    if not windows or windows[-1][0] != head:
        return None
    return [(sha, start, end) for sha, end, start in windows]


def gate_windows(history, current, conditions, url):
    """Windows when every start gate was open; None if the label history can't be trusted."""
    on, changes = set(), []
    for at, add, name in sorted(history, key=lambda h: h[0]):
        if name is None:
            return None  # A deleted label: which gate it was is unknown.
        if name != READY and name not in CLOSING_LABELS:
            continue
        if (name in on) == add:
            return None  # Added twice or removed while off: an event is missing.
        (on.add if add else on.discard)(name)
        changes.append((at, frozenset(on)))
    if on != current & {READY, *CLOSING_LABELS}:
        return None  # The replay must end at the labels GitHub shows now.
    missing = sorted({gap for at, _, gap in conditions if at is None and gap}, key=STAGE_GAPS.index)
    shut = any(at is None for at, _, _ in conditions)
    known = [(at, src) for at, src, _ in conditions if at is not None]
    points = sorted({at for at, _ in changes} | {at for at, _ in known})
    windows, labels, opened = [], frozenset(), None
    for t in points:
        labels = next((s for at, s in reversed(changes) if at <= t), frozenset())
        is_open = (not shut and READY in labels and not labels & set(CLOSING_LABELS) and
                   all(at <= t for at, _ in known))
        if is_open and opened is None:
            opened = (t, next((src for at, src in known if at == t), url))
        elif not is_open and opened is not None:
            windows.append((opened[0], t, opened[1]))
            opened = None
    if opened is not None:
        windows.append((opened[0], None, opened[1]))

    def spans(name):
        out, start = [], None
        for at, state in changes:
            if name in state and start is None:
                start = at
            elif name not in state and start is not None:
                out.append((start, at))
                start = None
        return out + ([(start, None)] if start is not None else [])
    return {'windows': windows, 'holds': spans('held'), 'needs_info': spans('needs-info'), 'labels': on,
            'missing': missing, 'shut': shut}


def green_windows(attempts, completed, links):
    """Per head: spans while the latest started CI attempt on it had succeeded."""
    out, unreadable = {}, {}  # head: why its green time can't be shown
    for head in {e['head'] for e in attempts}:
        mine = []
        for e in attempts:
            if e['head'] != head:
                continue
            try:
                done = when(completed.get((e['run'], e['attempt'])))
            except ReadError:
                done = None
            if e['conclusion'] == 'success' and (done is None or done < e['at']):
                unreadable.setdefault(head, 'no green completion time')
                done = None
            mine.append((e['at'], e['run'], e['attempt'], done, e))
        windows, opened = [], None
        for t in sorted({x[0] for x in mine} | {x[3] for x in mine if x[3] is not None}):
            started = [x for x in mine if x[0] <= t]
            last = max(x[0] for x in started)
            tied = {x[1] for x in started if x[0] == last}
            latest = max(x for x in started if x[0] == last)  # A superseded attempt's late result never counts.
            # Runs started in the same recorded second can't be ordered: neither may open green.
            if len(tied) > 1 and any(x[4]['conclusion'] == 'success' for x in started if x[0] == last):
                unreadable.setdefault(head, 'ci order unknown')
            ok = (len(tied) == 1 and latest[4]['conclusion'] == 'success' and latest[3] is not None and
                  latest[3] <= t)
            if ok and opened is None:
                opened = (t, links[latest[4]['source']])
            elif not ok and opened is not None:
                windows.append((opened[0], t, opened[1]))
                opened = None
        out[head] = windows + ([(opened[0], None, opened[1])] if opened else [])
    return out, unreadable


def collect_stage_waits(c, doc, issues, specs, pulls, inventory, read_at):
    """Sourced stage intervals; the settings are applied later, by bench."""
    sources, out, gate, revisions = {}, [], {}, {}
    doc_sources = doc['sources']

    def source(url):
        if url not in sources:
            sources[url] = f's{len(sources) + 1}'
        return sources[url]

    def point(at, url, latest=None):
        return {'at': at, 'url': url, 'latest': latest or at}

    def cp(x):
        return point(x['at'], x['url'], x['updated'])

    def ev(e):
        return point(e['at'], doc_sources[e['source']])

    times = [e['at'] for part in ('specs', 'tickets', 'pull_requests') for x in doc[part] for e in x['events']
             if e['at'] is not None]
    for t in doc['tickets']:
        n = t['ticket']
        history, current, blockers = stage_reads(c, n)
        times += [at for at, _, _ in history]
        # The spec's latest plan approval: unedited, naming this ticket, and recording the fingerprint of
        # plan-graph's current revision. Anything else is Unknown, never an older or a guessed approval.
        latest = max((x for x in (specs[t['spec']]['comments'] if t['spec'] in specs else [])
                      if first_line(x['body']).startswith('**Plan graph approved')), key=lambda x: x['at'], default=None)
        if latest is None or latest['edited'] or not re.search(rf'#{n}(?![0-9])', latest['body']):
            conditions = [(None, None, 'no plan approval')]
        else:
            if t['spec'] not in revisions:
                revisions[t['spec']] = current_fingerprint(doc['repo'], t['spec'])
            recorded = FINGERPRINT.search(latest['body'])
            matches = recorded is not None and revisions[t['spec']] == recorded[1]
            conditions = [(latest['at'], latest['url'], None) if matches else (None, None, 'approval not current')]
        for b, closed in blockers:  # Done once closed and a PR closing it merged: closed alone is not enough.
            merged = sorted((M.iso(p['merged']), k) for k, p in inventory.items() if b in p['tickets'] and p['merged'])
            if closed is None:
                conditions.append((None, None, None))  # Still open: the gate is shut, nothing is missing.
            elif merged:
                conditions.append((max(closed, merged[0][0]), f'https://github.com/{doc["repo"]}/pull/{merged[0][1]}',
                                   None))
            else:
                conditions.append((None, None, 'blocker merge unverified'))
        gate[n] = gate_windows(history, current, conditions, issues[n]['url'])
    heads = {}
    for p in doc['pull_requests']:
        heads[p['number']] = head_windows(c, pulls[p['number']]['branch'], p['revisions']['head'])
        times += [w[1] for w in heads[p['number']] or []]
    for done in c.completed.values():
        try:
            times.append(when(done))
        except ReadError:
            pass  # An unreadable completion is no green time; it is never guessed.
    require(all(t <= read_at for t in times), 'a record is later than the read time')

    def add(stage, owner, tickets, pr, head, origin, start, end, state=None, gaps=(), folded=0, support=()):
        clock = None
        if state is None:
            state, clock, gaps = run_clock([gate[t] and gate[t]['holds'] for t in tickets], start, end, read_at)
        out.append({'key': interval_key(stage, owner, head, origin, start), 'stage': stage, 'tickets': tickets,
                    'pull_request': pr, 'head': head, 'origin': origin, 'start': start, 'clock_from': clock,
                    'end': end, 'support': list(support), 'state': state, 'folded': folded, 'gaps': list(gaps)})

    for t in doc['tickets']:
        n, owner, comments, g = t['ticket'], f't{t["ticket"]}', issues[t['ticket']]['comments'], gate[t['ticket']]
        starts = sorted((x for x in comments if STARTED.match(first_line(x['body']))), key=lambda x: x['at'])
        first, fold = (cp(starts[0]) if starts else None), max(len(starts) - 1, 0)

        def builder(*args, **kw):
            add('builder_start', owner, [n], None, None, None, *args, folded=fold, **kw)
        if g is None:
            builder(None, first, 'unknown', ('label history incomplete',))
        elif first:
            w = next((w for w in g['windows'] if w[0] <= first['at'] and (w[1] is None or first['at'] < w[1])), None)
            if w and w[1] is not None and first['latest'] >= w[1]:
                builder(None, first, 'unknown', ('edited record',))  # It may have appeared after the gate shut.
            elif w:
                builder(point(w[0], w[2]), first)
            else:
                builder(None, first, 'unknown', g['missing'] or ('start record outside its gate',))
        elif t['state'] != 'open':
            builder(None, None, 'unknown', ('no end record',))
        elif g['windows'] and g['windows'][-1][1] is None:
            builder(point(g['windows'][-1][0], g['windows'][-1][2]), None)
        elif (READY in g['labels'] or ('held' in g['labels'] and g['windows'])) and \
                not g['labels'] & set(CLOSING_LABELS) - {'held'}:
            # A hold may remove ready-for-agent as it adds held: a wait that had opened is still gated.
            if g['missing']:
                builder(None, None, 'unknown', g['missing'])
            elif 'held' in g['labels'] and not g['shut']:
                builder(None, None, 'gated', ('held',))
        questions = sorted((x for x in comments if first_line(x['body']).startswith('Builder question:')),
                           key=lambda x: x['at'])
        rulings = [x for x in comments if first_line(x['body']).startswith('Orchestrator ruling')]
        until = ''
        for qn in questions:
            if until is None or qn['at'] < until:
                out[-1]['folded'] += 1
                continue

            def question(*args, **kw):
                add('builder_question_answer', owner, [n], None, None, comment_id(qn['url']), *args, **kw)
            if g is None:
                until = None
                question(None, None, 'unknown', ('label history incomplete',))
                continue
            off = next((b for a, b in g['needs_info'] if b is not None and b > qn['at']), None)
            until = off
            if qn['edited']:
                question(None, None, 'unknown', ('edited record',))
            elif off is None:
                waiting = t['state'] == 'open' and 'needs-info' in g['labels']
                question(cp(qn), None, *(() if waiting else ('unknown', ('no end record',))))
            else:  # A recorded disposition that cites this question, before needs-info is removed.
                r = min((x for x in rulings if qn['at'] < x['at'] <= off and substantive(x, qn['url']) and
                         (qn['url'] in x['body'] or f'#issuecomment-{comment_id(qn["url"])}' in x['body'])),
                        key=lambda x: x['at'], default=None)
                if r and r['updated'] > off:
                    question(cp(qn), None, 'unknown', ('edited record',))
                elif r:
                    question(cp(qn), cp(r))
                else:
                    question(cp(qn), None, 'unknown', ('no linked disposition',))

    for p in doc['pull_requests']:
        n, owner, raw, hw = p['number'], f'p{p["number"]}', pulls[p['number']], heads[p['number']]
        mine = [t for t in p['tickets'] if t in gate]
        attempts = [e for e in p['events'] if e['kind'] == 'ci_attempt']
        greens, unreadable = green_windows(attempts, c.completed, doc_sources)
        by_url = {x['url']: x for x in raw['comments']}

        def current(head):
            return [(start, end, f'https://github.com/{doc["repo"]}/commit/{sha}')
                    for sha, start, end in hw or [] if sha == head]

        def pr_add(stage, head, origin, *args, **kw):
            add(stage, owner, mine, n, head, origin, *args, **kw)
        records = sorted(((x['at'], m[1], m[2], x) for x in raw['comments']
                          for m in [REVIEW_RECORD.match(first_line(x['body']))] if m), key=lambda r: r[0])
        for h in sorted(set(greens) | set(unreadable), key=lambda h: min(e['at'] for e in attempts if e['head'] == h)):
            if not greens[h] and h not in unreadable:
                continue  # Never green: no review is due.
            if hw is None:
                pr_add('reviewer_start', h, None, None, None, 'unknown', ('head history incomplete',))
                continue
            confirmed = [r for r in records if h.startswith(r[2]) and r[1] != 'review starting']
            claims = [r for r in records if h.startswith(r[2]) and r[1] == 'review starting']
            windows = intersect(current(h), greens[h])
            if not windows:
                pr_add('reviewer_start', h, None, None, None, 'unknown' if h in unreadable else 'stale',
                       (unreadable[h],) if h in unreadable else ('no longer current',))
                continue
            def within(r, start, end):
                return start <= r[0] and (end is None or r[0] < end)
            outside = [r for r in confirmed if not any(within(r, s_, e_) for s_, e_, _ in windows)]
            early, ended_at = (outside[0] if outside else None), None
            for start, end, src in windows:
                inside = [r for r in records if h.startswith(r[2]) and within(r, start, end)]
                rec = next((r for r in inside if r in confirmed), None)
                w = point(start, src)
                if rec:  # Each window is settled by its own confirmation.
                    if end is not None and rec[3]['updated'] >= end:  # Its text may postdate the window.
                        pr_add('reviewer_start', h, None, w, None, 'unknown', ('edited record',))
                    else:
                        pr_add('reviewer_start', h, None, w, cp(rec[3]), folded=len(confirmed) + len(claims) - 1)
                    ended_at = start
                    break
                if early and early[0] < start:
                    continue  # A start already recorded outside the gate: no new wait to time here.
                if any(r in claims for r in inside):  # Uncertain here; a later window may still confirm.
                    pr_add('reviewer_start', h, None, w, None, 'unknown', ('reviewer start unconfirmed',))
                    if not confirmed:
                        break
                elif end is not None:
                    pr_add('reviewer_start', h, None, w, None, 'stale', ('no longer current',))
                elif p['state'] == 'open':
                    pr_add('reviewer_start', h, None, w, None)
                else:
                    pr_add('reviewer_start', h, None, w, None, 'unknown', ('no end record',))
            if early and (ended_at is None or early[0] < ended_at):
                pr_add('reviewer_start', h, None, None, cp(early[3]), 'unknown', ('start record outside its gate',))
        rounds = [e for e in p['events'] if rounds_of(e)]
        answers, disputes = [], []
        for x in raw['comments']:
            for line in x['body'].splitlines():
                m = FIXED.match(line.strip())
                if m:
                    answers.append((x, m[1], m[2]))
                elif DISPUTED.match(line.strip()):
                    disputes.append(x['at'])
        until = ''
        for v in (e for e in rounds if e['verdict'] == 'CHANGES'):
            if until is None or v['at'] < until:
                out[-1]['folded'] += 1
                continue
            vid = comment_id(doc_sources[v['source']])

            def fix(*args, **kw):
                pr_add('fix_after_changes', v['head'], vid, *args, **kw)
            if hw is None:
                until = None
                fix(None, None, 'unknown', ('head history incomplete',))
                continue
            needed = set()  # The round's open high and medium findings: the fixes it asks for.
            for line in by_url[doc_sources[v['source']]]['body'].splitlines():
                m = FINDING.fullmatch(line.strip())
                if m and m[2] in ('high', 'medium') and not m[3].startswith(CORRECTED):
                    needed.add(m[1])
            found, edited = [], False
            for x, finding, sha in answers:
                for head, start, _ in hw:
                    if (finding in needed and head.startswith(sha) and head != v['head'] and
                            v['at'] < start <= x['at']):
                        if x['edited']:
                            edited = True
                        else:
                            found.append((start, head, x))
            found.sort(key=lambda f: (f[0], f[2]['at']))
            until = found[0][0] if found else None
            if v['completeness'] == 'edited':
                fix(None, None, 'unknown', ('edited record',))
            elif found:
                start, head, x = found[0]
                fix(ev(v), point(start, f'https://github.com/{doc["repo"]}/commit/{head}'), support=[x['url']])
            elif edited:
                fix(ev(v), None, 'unknown', ('edited record',))
            elif any(at > v['at'] for at in disputes):
                fix(ev(v), None, 'unknown', ('disputed without fix',))
            elif p['state'] == 'open':
                fix(ev(v), None)
            else:
                fix(ev(v), None, 'unknown', ('no end record',))
        valid = []  # [head, from, to, approval, folded]: an APPROVE holds until a later CHANGES.
        for v in rounds:
            if valid and valid[-1][2] is None and (v['verdict'] == 'CHANGES' or v['head'] != valid[-1][0]):
                valid[-1][2] = v['at']
            if v['verdict'] == 'APPROVE':
                if valid and valid[-1][2] is None:
                    valid[-1][4] += 1
                else:
                    valid.append([v['head'], v['at'], None, v, 0])
        merge = next((e for e in p['events'] if e['kind'] == 'merge'), None)
        merged_at = merge['at'] if merge and p['revisions']['head'] else None
        for h, since, to, v, fold in valid:
            vid = comment_id(doc_sources[v['source']])

            def merging(*args, **kw):
                pr_add('merge', h, vid, *args, folded=fold, **kw)
            if v['completeness'] == 'edited':
                merging(None, None, 'unknown', ('edited record',))
                continue
            if hw is None:
                merging(None, None, 'unknown', ('head history incomplete',))
                continue
            windows = intersect(intersect([(since, to, doc_sources[v['source']])], current(h)), greens.get(h, []))
            at_merge = merged_at if merged_at and h == p['revisions']['head'] else None
            if not windows:
                merging(None, None, 'unknown' if h in unreadable else 'stale',
                        (unreadable[h],) if h in unreadable else ('no longer current',))
                continue
            closed = False
            for start, end, src in windows:
                w = point(start, src)
                if at_merge and start <= at_merge and (end is None or at_merge <= end):
                    merging(w, ev(merge))
                    closed = True
                elif at_merge and at_merge < start:
                    break
                elif end is not None or p['state'] == 'closed':
                    merging(w, None, 'stale', ('no longer current',))
                elif p['state'] == 'open':
                    merging(w, None)
                else:
                    merging(w, None, 'unknown', ('no end record',))
            if at_merge and since <= at_merge and not closed:
                merging(None, ev(merge), 'unknown', ('start record outside its gate',))

    def publish(p):
        if p is None:
            return None
        return {'at': p['at'], 'latest': p['latest'], 'source': source(p['url'])}
    intervals = [{**i, 'start': publish(i['start']), 'end': publish(i['end']),
                  'support': [source(u) for u in i['support']]} for i in out]
    holds = {str(n): (None if g is None else [list(h) for h in g['holds']]) for n, g in gate.items()}
    return {'schema': STAGE_SCHEMA, 'repo': doc['repo'], 'journey_hash': journey_hash(doc), 'read_at': read_at,
            'history': 'unknown', 'holds': holds, 'intervals': intervals,
            'sources': {k: u for u, k in sources.items()}}


INTERVAL_KEYS = ('key', 'stage', 'tickets', 'pull_request', 'head', 'origin', 'start', 'clock_from', 'end', 'support',
                 'state', 'folded', 'gaps')


def validate_stage_waits(side, doc):
    validate(doc)
    stages = limits_module().STAGES
    exact(side, ('schema', 'repo', 'journey_hash', 'read_at', 'history', 'holds', 'intervals', 'sources'),
          'stage waits')
    require(side['schema'] == STAGE_SCHEMA and side['repo'] == doc['repo'] and side['history'] == 'unknown',
            'not a stage-wait sidecar of this repository')
    require(side['journey_hash'] == journey_hash(doc), 'the sidecar is bound to another journey')
    read_at = when(side['read_at'])
    require(not THREAD.search(json.dumps(side, default=str)), 'a thread identifier is saved')
    sources = obj(side['sources'])
    for key, url in sources.items():
        require(re.fullmatch(r's[1-9][0-9]*', key) and type(url) is str and
                url.lower().startswith(f'https://github.com/{doc["repo"].lower()}/') and
                re.fullmatch(r'[\x21-\x7e]+', url), 'invalid source')
    tickets = {t['ticket'] for t in doc['tickets']}
    prs = {p['number']: p for p in doc['pull_requests']}
    holds = obj(side['holds'])
    require(set(holds) == {str(t) for t in tickets}, 'holds name every collected ticket')
    for spans in holds.values():
        for span in array(spans) if spans is not None else []:
            require(type(span) is list and len(span) == 2 and when(span[0]) <= read_at and
                    (span[1] is None or span[0] < when(span[1]) <= read_at), 'invalid hold')
    keys, measured = set(), []
    for i in array(side['intervals']):
        exact(i, INTERVAL_KEYS, 'interval')
        require(i['stage'] in stages and i['state'] in STATES, 'invalid stage or state')
        require(bool(array(i['tickets'])) and all(type(t) is int and t in tickets for t in i['tickets']),
                'an interval names an uncollected ticket')
        pr = i['pull_request']
        require((pr is None) == (i['stage'] not in PR_STAGES) and (pr is None or pr in prs), 'a stage on the wrong record')
        require(pr is None or i['tickets'] == [t for t in prs[pr]['tickets'] if t in tickets], 'wrong tickets')
        require(pr is not None or len(i['tickets']) == 1, 'a ticket stage names one ticket')
        maybe_commit(i['head'])
        require((i['head'] is None) == (pr is None), 'a PR stage names its head')
        require(i['origin'] is None or count(i['origin']), 'invalid origin')
        require((i['origin'] is not None) == (i['stage'] in ('builder_question_answer', 'fix_after_changes', 'merge')),
                'an origin names the initiating comment')
        count(i['folded'], 0)
        gaps = array(i['gaps'])
        require(all(g in STAGE_GAPS for g in gaps) and len(set(gaps)) == len(gaps), 'invalid gaps')
        for name in ('start', 'end'):
            p = i[name]
            if p is not None:
                exact(p, ('at', 'latest', 'source'), 'stage point')
                require(when(p['at']) <= when(p['latest']) <= read_at and p['source'] in sources, 'invalid stage point')
        require(all(s in sources for s in array(i['support'])), 'unknown support')
        owner = f'p{pr}' if pr is not None else f't{i["tickets"][0]}'
        require(i['key'] == interval_key(i['stage'], owner, i['head'], i['origin'], i['start']) and
                i['key'] not in keys, 'an interval key is not its evidence, or repeats')
        keys.add(i['key'])
        bind_interval(i, doc, sources)
        state = i['state']
        if state in ('ended', 'open') or (state == 'gated' and i['start'] is not None):
            require(i['start'] is not None, 'a measured interval needs its start')
            ticket_holds = [holds[str(t)] for t in i['tickets']]
            expected = run_clock(ticket_holds, i['start'], i['end'], side['read_at'])
            require(expected == (state, i['clock_from'], gaps), 'the clock disagrees with its holds')
            if state != 'gated':
                measured.append((i['stage'], owner, i['head'], i['start']['at'], i['end']['at'] if i['end'] else None))
        else:
            require(i['clock_from'] is None and gaps != [], 'an unmeasured interval names its gap')
            require(state != 'gated' or gaps == ['held'], 'a gated interval is held')
            require(state != 'stale' or gaps == ['no longer current'], 'a stale interval is no longer current')
        require(state != 'ended' or i['end'] is not None, 'an ended interval has its end')
    for a in measured:
        for b in measured:
            if a is not b and a[:3] == b[:3]:
                require((a[4] is not None and a[4] <= b[3]) or (b[4] is not None and b[4] <= a[3]),
                        'two intervals overlap')
    require(sum(m[0] == 'builder_start' for m in measured) <= len(tickets), 'one builder interval per ticket')


def bind_interval(i, doc, sources):
    """Every head, origin and endpoint must be one the hashed journey shows for this record."""
    links, web = doc['sources'], f'https://github.com/{doc["repo"]}/'

    def link(name):
        return sources[i[name]['source']] if i[name] else None

    def same_time(name, event):
        """An endpoint naming a journey event carries that event's own time."""
        require(i[name] is None or (i[name]['at'] == event['at'] and
                                    (event['completeness'] == 'edited' or i[name]['latest'] == event['at'])),
                f'an interval {name} time differs from its journey event')
    pr = i['pull_request']
    if pr is None:
        t = next(t for t in doc['tickets'] if t['ticket'] == i['tickets'][0])
        mine = {e['kind']: [] for e in t['events']}
        for e in t['events']:
            mine[e['kind']].append(links[e['source']])
        issue_url = mine['ticket'][0]
        if i['stage'] == 'builder_start':
            require(link('end') in (None, *mine.get('builder_start', [])), 'a builder end the journey lacks')
            if i['end']:
                same_time('end', next(e for e in t['events'] if e['kind'] == 'builder_start' and
                                      links[e['source']] == link('end')))
            spec = f'{web}issues/{t["spec"]}#issuecomment-'
            require(link('start') is None or link('start') == issue_url or link('start').startswith(spec) or
                    re.fullmatch(re.escape(web) + r'pull/[1-9][0-9]*', link('start')), 'a builder start of another record')
        else:
            require(link('start') in (None, f'{issue_url}#issuecomment-{i["origin"]}'), 'a question of another record')
            require(link('end') is None or link('end').startswith(issue_url + '#issuecomment-'),
                    'an answer on another record')
        return
    p = next(p for p in doc['pull_requests'] if p['number'] == pr)
    head, commit_link = i['head'], f'{web}commit/{i["head"]}'
    attempts = [e for e in p['events'] if e['kind'] == 'ci_attempt']
    seen = {e['head'] for e in attempts} | {e['head'] for e in p['events'] if e['kind'] == 'verdict' and e['head']}
    require(head in seen | {p['revisions']['head']}, 'a head the journey never saw')
    runs = {links[e['source']] for e in attempts if e['head'] == head}
    for name in ('start', 'end'):  # A green time follows that head's run starting.
        if link(name) in runs:
            require(i[name]['at'] >= min(e['at'] for e in attempts if links[e['source']] == link(name)),
                    f'an interval {name} before its CI run')
    comments = f'{web}pull/{pr}#issuecomment-'
    origin = next((e for e in p['events'] if rounds_of(e) and links[e['source']] == f'{comments}{i["origin"]}'), None)
    if i['stage'] == 'reviewer_start':
        require(link('start') in (None, commit_link, *runs), 'a reviewer start of another head')
        require(link('end') is None or link('end').startswith(comments), 'a reviewer record of another PR')
        return
    want = 'APPROVE' if i['stage'] == 'merge' else 'CHANGES'
    require(origin is not None and origin['verdict'] == want and origin['head'] == head, 'an origin the journey lacks')
    if i['stage'] == 'merge':
        merges = [links[e['source']] for e in p['events'] if e['kind'] == 'merge']
        require(link('start') in (None, commit_link, links[origin['source']], *runs), 'a merge wait of another head')
        require(link('end') in (None, *merges), 'a merge the journey lacks')
        if link('start') == links[origin['source']]:
            same_time('start', origin)
        if i['end']:
            same_time('end', next(e for e in p['events'] if e['kind'] == 'merge'))
    else:
        require(link('start') in (None, links[origin['source']]), 'a fix wait of another round')
        same_time('start', origin)
        fixed = {f'{web}commit/{h}' for h in seen | {p['revisions']['head']} if h != head}
        require(link('end') in (None, *fixed), 'a fix at a head the journey never saw')
        require(all(sources[x].startswith(comments) for x in i['support']), 'support from another PR')


def stage_bench(side, settings):
    """Facts for finite ops tooling; a miss here authorizes no effect."""
    minutes = settings['minutes']
    waits, stages = [], {s: {'intervals': 0, 'results': {r: 0 for r in RESULTS}} for s in minutes}
    read_at = M.timestamp(side['read_at'])
    for i in side['intervals']:
        limit, wait, span, result, gaps = minutes[i['stage']], None, None, i['state'], list(i['gaps'])
        if i['state'] in ('ended', 'open'):
            clock = M.timestamp(i['clock_from'])
            lo, hi = ((M.timestamp(i['end']['at']) - clock).total_seconds(),
                      (M.timestamp(i['end']['latest']) - clock).total_seconds()) if i['end'] else \
                ((read_at - clock).total_seconds(),) * 2
            span = [round(lo / 60, 2), round(hi / 60, 2)]
            wait = span[0] if lo == hi else None
            if lo > limit * 60:
                result = 'missed'
            elif hi <= limit * 60:
                result = 'not missed' if i['end'] else 'pending'
            else:  # An edited end straddles the goal: when it happened is not known closely enough.
                result, gaps = 'unknown', gaps + ['edited record']
        stages[i['stage']]['intervals'] += 1
        stages[i['stage']]['results'][result] += 1
        waits.append({'key': i['key'], 'stage': i['stage'], 'tickets': i['tickets'],
                      'pull_request': i['pull_request'], 'wait_minutes': wait, 'wait_range_minutes': span,
                      'limit_minutes': limit, 'result': result, 'start': i['start'] and i['start']['source'],
                      'end': i['end'] and i['end']['source'], 'support': i['support'], 'folded': i['folded'],
                      'gaps': gaps})
    rows = [{'stage': s, 'limit_minutes': minutes[s], 'intervals': stages[s]['intervals'],
             'measured': sum(stages[s]['results'][r] for r in ('missed', 'not missed', 'pending')),
             'results': stages[s]['results']} for s in limits_module().STAGES]
    return {'schema': STAGE_BENCH, 'settings': settings, 'read_at': side['read_at'], 'authority': 'none',
            'stages': rows, 'waits': waits, 'misses': [w['key'] for w in waits if w['result'] == 'missed'],
            'sources': side['sources']}


# --- Consumers --------------------------------------------------------------

def bench(doc):
    prs = {p['number']: p for p in doc['pull_requests']}
    rows = []
    for t in doc['tickets']:
        mine = [prs[n] for n in t['pull_requests']]
        evs = [e for p in mine for e in p['events']]
        rounds = sorted((e for e in evs if rounds_of(e)), key=lambda e: e['at'])
        ready = next((e['at'] for e in t['events'] if e['kind'] == 'ready'), None)
        merges = sorted(e['at'] for e in evs if e['kind'] == 'merge')
        hours = None
        if ready and merges:
            hours = round((M.timestamp(merges[0]) - M.timestamp(ready)).total_seconds() / 3600, 6)
        findings = {k: 0 for k in KINDS}
        for p in mine:
            for f in p['findings']:
                findings[f['kind']] += 1
        rows.append({'ticket': t['ticket'], 'state': t['state'], 'pull_requests': t['pull_requests'],
                     'rounds': len(rounds), 'first_time_approval': rounds[0]['verdict'] == 'APPROVE' if rounds else None,
                     'fix_rounds': sum(e['kind'] == 'fix_round' for e in evs),
                     'ci_attempts': sum(e['kind'] == 'ci_attempt' for e in evs),
                     'reruns': sum(e['kind'] == 'ci_attempt' and e['rerun'] for e in evs),
                     'ready_to_merged_hours': hours, 'findings': findings,
                     'usage': {f"{u['provider']}/{u['unit']}": u['status'] for u in t['usage']}, 'gaps': t['gaps']})
    return {'schema': 'closedwiz.journey.bench.v1', 'tickets': rows}


def cf4(doc):
    findings, provenance, by_kind = [], {}, {k: 0 for k in KINDS}
    for p in sorted(doc['pull_requests'], key=lambda p: p['number']):
        evs = {e['id']: e for e in p['events']}
        for f in p['findings']:
            key = f'F{len(findings) + 1}'
            raised = evs[f['raised_by']]
            findings.append({'key': key, 'kind': f['kind'], 'severity': f['severity'], 'check': f['check'],
                             'at': raised['at']})
            provenance[key] = doc['sources'][raised['source']]
            by_kind[f['kind']] += 1
    return {'schema': 'closedwiz.journey.findings.v1', 'findings': findings, 'by_kind': by_kind,
            'provenance': provenance}


def ticket_arg(value):
    if not re.fullmatch(r'[1-9][0-9]{0,9}', value):
        raise argparse.ArgumentTypeError('ticket must be a positive issue number')
    return int(value)


def time_arg(value):
    try:
        return M.iso(M.timestamp(value))
    except ReadError:
        raise argparse.ArgumentTypeError('time must be UTC YYYY-MM-DDTHH:MM:SSZ')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    c = sub.add_parser('collect', help='read GitHub and write DIR/journeys.json')
    c.add_argument('--repo', type=M.repo_arg, required=True, help='OWNER/REPO')
    c.add_argument('--ticket', type=ticket_arg, action='append', required=True, help='a ticket to collect (repeat)')
    c.add_argument('--usage', type=Path, action='append', default=[], help="a daily usage export (metrics.py's README)")
    c.add_argument('--out', type=Path, required=True, help='a new directory')
    c.add_argument('--with-outcomes', action='store_true', help='also write the explicit EB5 sidecar')
    c.add_argument('--defect-policy', type=Path, help='predeclared EB5 defect policy')
    c.add_argument('--previous', type=Path, help='previous collect directory to preserve established evidence')
    c.add_argument('--stage-waits', action='store_true', help='also write the TL2 stage-wait sidecar')
    c.add_argument('--as-of', type=time_arg, help='the read time for open stage intervals (default: now)')
    for name in ('check', 'bench', 'cf4'):
        command = sub.add_parser(name)
        command.add_argument('file', type=Path)
        if name == 'bench': command.add_argument('--outcomes', type=Path)
        if name in ('check', 'bench'):
            command.add_argument('--stage-waits', type=Path, help='a stage-wait sidecar of this journey file')
        if name == 'bench':
            command.add_argument('--settings', type=Path, default=HERE / 'limits.conf', help='stage-limit settings')
    args = parser.parse_args()
    if args.command == 'collect' and len(set(args.ticket)) != len(args.ticket):
        parser.error('a ticket is named twice')
    if args.command == 'collect' and args.as_of and not args.stage_waits:
        parser.error('--as-of needs --stage-waits')
    try:
        if args.command == 'collect':
            require(not args.out.exists(), 'output directory already exists; choose a new directory')
            policy = M.load(args.defect_policy.read_text()) if args.defect_policy else None
            previous = ((M.load((args.previous/'journeys.json').read_text()),
                         M.load((args.previous/'outcomes.json').read_text())) if args.previous else None)
            outcomes = {} if args.with_outcomes or args.defect_policy or args.previous else None
            stages = {} if args.stage_waits else None
            read_at = args.as_of or M.iso(datetime.now(timezone.utc).replace(microsecond=0))
            doc = collect(args.repo, sorted(args.ticket), args.usage, outcomes, policy, previous, stages, read_at)
            validate(json.loads(json.dumps(doc)))  # The collector's own output must conform.
            if stages is not None:
                validate_stage_waits(stages, json.loads(json.dumps(doc)))
            args.out.mkdir(parents=True)
            (args.out / 'journeys.json').write_text(json.dumps(doc, indent=2) + '\n')
            if stages is not None:
                (args.out / 'stage-waits.json').write_text(json.dumps(stages, indent=2) + '\n')
            if outcomes is not None:
                (args.out / 'outcomes.json').write_text(json.dumps(outcomes, indent=2, default=float) + '\n')
            return 0
        try:
            doc = M.load(args.file.read_text())
        except (OSError, UnicodeError):
            raise ReadError('cannot read the journey file')
        validate(doc)
        side = M.load(args.stage_waits.read_text()) if getattr(args, 'stage_waits', None) else None
        if side is not None:
            validate_stage_waits(side, doc)
        if args.command != 'check':
            result = bench(doc) if args.command == 'bench' else cf4(doc)
            if args.command == 'bench' and args.outcomes:
                result['outcomes'] = outcome_rows(doc, M.load(args.outcomes.read_text()))
            if side is not None:
                result['stage_waits'] = stage_bench(side, limits_module().read(args.settings))
            print(json.dumps(result, indent=2, default=float))
        return 0
    except (ReadError, OSError, ValueError, argparse.ArgumentTypeError) as e:
        print(f'journey: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
