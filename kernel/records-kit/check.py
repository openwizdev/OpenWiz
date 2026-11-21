#!/usr/bin/env python3
import argparse
import calendar
import json
import re
import sys
import time

sys.dont_write_bytecode = True
TRACKER = 'openwiz:records-kit tracker v1'
TIME = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$')
REASONS = {'open': (None,), 'closed': (None, 'completed', 'not_planned', 'duplicate')}


class Unreadable(Exception):
    pass


def _refuse(why):
    raise Unreadable(why)


def _object(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys):
        _refuse('%s needs exactly the keys %s' % (where, ', '.join(keys)))
    return value


def _int(value, where):
    if type(value) is not int or value < 1:
        _refuse('%s is not a positive whole number' % where)
    return value


def _seconds(t):
    return calendar.timegm(time.strptime(t, '%Y-%m-%dT%H:%M:%SZ'))


def _time(value, where):
    _str(value, where, TIME)
    try:
        _seconds(value)
    except ValueError:
        _refuse('%s is not a real time' % where)
    return value


def _str(value, where, pattern=None):
    if not isinstance(value, str) or (pattern and not pattern.match(value)):
        _refuse('%s is not a valid string' % where)
    return value


def _list(value, where):
    if not isinstance(value, list):
        _refuse('%s is not a list' % where)
    return value


def read_tracker(data):
    _object(data, ('tracker', 'repo', 'now', 'record_authors', 'issues'), 'the tracker')
    if data['tracker'] != TRACKER:
        _refuse('tracker is not %r' % TRACKER)
    _str(data['repo'], 'repo', re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'))
    _time(data['now'], 'now')
    for a in _list(data['record_authors'], 'record_authors'):
        _str(a, 'a record author')
    seen = set()
    for issue in _list(data['issues'], 'issues'):
        _object(issue, ('number', 'labels', 'parent', 'blocked_by', 'body', 'comments'), 'an issue')
        n = _int(issue['number'], 'an issue number')
        if n in seen:
            _refuse('issue #%d is listed twice' % n)
        seen.add(n)
        for label in _list(issue['labels'], '#%d labels' % n):
            _str(label, '#%d label' % n)
        if issue['parent'] is not None:
            _int(issue['parent'], '#%d parent' % n)
        _str(issue['body'], '#%d body' % n)
        for b in _list(issue['blocked_by'], '#%d blocked_by' % n):
            _object(b, ('number', 'state', 'state_reason'), '#%d blocker' % n)
            _int(b['number'], '#%d blocker number' % n)
            if b['state'] not in REASONS or b['state_reason'] not in REASONS[b['state']]:
                _refuse('#%d blocker #%s has an unknown state' % (n, b['number']))
        for c in _list(issue['comments'], '#%d comments' % n):
            _object(c, ('id', 'author', 'updated_at', 'body'), '#%d comment' % n)
            _int(c['id'], '#%d comment id' % n)
            _str(c['author'], '#%d comment author' % n)
            _time(c['updated_at'], '#%d comment time' % n)
            _str(c['body'], '#%d comment body' % n)
    return data


def _no_repeats(pairs):
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        _refuse('a key is repeated')
    return dict(pairs)


def load_fixture(path):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f, object_pairs_hook=_no_repeats)
    except (OSError, ValueError) as e:
        _refuse('cannot read %s: %s' % (path, e))


AGENT_STATE_LABELS = ('building', 'in-review', 'in review', 'needs-you', 'needs you',
                      'in-progress', 'in progress', 'merged')
READY = ('ready-for-agent', 'ready-for-human')
MARKER = '<!-- openwiz:status v1 -->'
NOTE_KEYS = ('agent', 'state', 'harness', 'model', 'skills', 'step', 'time', 'pr', 'preview')
NOTE_REQUIRED = NOTE_KEYS[:7]
TEXT = r'^[^\x00-\x1f\x7f"\u201c\u201d>][^\x00-\x1f\x7f"\u201c\u201d]{0,%d}$'
SKILL = r'[a-z0-9]+(-[a-z0-9]+)*@[0-9]+\.[0-9]+\.[0-9]+'
NOTE_VALUES = {
    'agent': re.compile(r'^(builder|reviewer|fleet)$'),
    'state': re.compile(r'^(working|asking|done|stopped|stopped \([^()\x00-\x1f\x7f"\u201c\u201d]{1,100}\))$'),
    'harness': re.compile(TEXT % 59),
    'model': re.compile(TEXT % 59),
    'skills': re.compile(r'^(?=.{1,300}$)%s(, %s)*$' % (SKILL, SKILL)),
    'step': re.compile(TEXT % 299),
    'time': TIME,
    'pr': re.compile(r'^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*$'),
    'preview': re.compile(r'^(?=.{1,300}$)https://(?![^/:]*\.(?:local|internal|lan|localhost)(?:[:/]|$))'
                          r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::[0-9]{1,5})?(?:/[^\s"<>?#@\\]*)?$'),
}
LINK = re.compile(r'^- #([1-9][0-9]*) (real|file):')
LIVE_SECONDS = 30 * 60
SPEC_SECTIONS = ('Problem Statement', 'Solution', 'Changelog headline', 'User Stories',
                 'Implementation Decisions', 'Testing Decisions', 'Proof', 'Out of Scope',
                 'Further Notes')
TICKET_SECTIONS = ('Parent', 'What to build', 'Owned paths', 'Links', 'Acceptance criteria', 'Proof')
RELIES = '**Relies on:**'


def read_note(body):
    lines = body.replace('\r\n', '\n').split('\n')
    while lines and lines[-1] == '':
        lines.pop()
    fields, at = {}, 0
    for line in lines[1:]:
        key, sep, value = line.partition(': ')
        if not sep or not value or key not in NOTE_KEYS[at:]:
            return None
        at = NOTE_KEYS.index(key) + 1
        fields[key] = value
    if any(k not in fields for k in NOTE_REQUIRED):
        return None
    if any(not NOTE_VALUES[k].match(v) for k, v in fields.items()):
        return None
    return fields


def read_lines(body):
    out, fence, comment = [], None, False
    for line in body.replace('\r\n', '\n').split('\n'):
        line = line.rstrip(' \t')
        out.append((line, fence is None and not comment))
        trim = line.lstrip()
        if fence is not None:
            if re.match(r'^%s{%d,}\s*$' % (re.escape(fence[0]), len(fence)), trim):
                fence = None
            continue
        if not comment:
            fence = (re.match(r'^(`{3,}|~{3,})', trim) or [None])[0]
            if fence is not None:
                continue
        at = 0
        while True:
            at = line.find('-->' if comment else '<!--', at)
            if at < 0:
                break
            at += 3 if comment else 4
            comment = not comment
    return out


def links(lines, blockers):
    heads = [at for at, (line, shown) in enumerate(lines) if shown and line == '## Links']
    if len(heads) > 1:
        return ['malformed section: more than one ## Links section']
    section = []
    for line, _ in lines[heads[0] + 1:] if heads else []:
        if re.match(r'^(#{1,6} |#{1,6}$)', line):
            break
        if line:
            section.append(line)
    if heads and not section:
        return ['malformed section: no lines']
    if any(line != 'none' and not LINK.match(line) for line in section):
        return ['malformed section: a line is not a link line or none']
    if len(section) > 1 and 'none' in section:
        return ['malformed section: none must be the only line']
    named = [int(LINK.match(line).group(1)) for line in section if line != 'none']
    found = []
    for b in sorted({b['number'] for b in blockers}):
        if named.count(b) == 0:
            found.append('#%d has no reason line' % b)
        elif named.count(b) > 1:
            found.append('#%d has more than one line' % b)
    return found


def breaks(tracker):
    issues = {i['number']: i for i in tracker['issues']}
    parents = {i['parent'] for i in tracker['issues'] if i['parent'] is not None}
    authors = {a.lower() for a in tracker['record_authors']}
    now = _seconds(tracker['now'])
    found = []
    for i in tracker['issues']:
        n, labels = i['number'], {label.lower() for label in i['labels']}
        say = lambda rule, what: found.append('#%d %s: %s' % (n, rule, what))
        for label in i['labels']:
            if label.lower() in AGENT_STATE_LABELS:
                say('L1', 'label %s says what an agent is doing; read it from GitHub' % label)
        if 'held' in labels:
            for ready in READY:
                if ready in labels:
                    say('L2', 'held beside %s' % ready)
        ticket = i['parent'] is not None
        if ticket and 'spec' in labels:
            say('L3', 'a ticket carries spec')
        if ticket and i['parent'] in issues and \
                'spec' not in {label.lower() for label in issues[i['parent']]['labels']}:
            say('L3', 'its spec #%d lacks spec' % i['parent'])
        live = {}
        for c in i['comments']:
            if c['author'].lower() not in authors or c['body'].split('\n', 1)[0].rstrip('\r') != MARKER:
                continue
            note = read_note(c['body'])
            if note is None:
                say('S2', 'note %d does not read as openwiz:status v1' % c['id'])
            elif note['state'] in ('working', 'asking') and now - _seconds(c['updated_at']) < LIVE_SECONDS:
                live.setdefault(note['agent'], []).append(c['id'])
        for agent in sorted(live):
            if len(live[agent]) > 1:
                ids = sorted(live[agent])
                say('S1', '%d live %s notes: %s' % (len(ids), agent, ', '.join(map(str, ids))))
        read = read_lines(i['body'])
        lines = [line for line, shown in read if shown]
        if ticket:
            kind, need = 'ticket', ['## ' + s for s in TICKET_SECTIONS] + [RELIES]
            if 'ready-for-human' in labels:
                need.append('## Done by')
        elif 'spec' in labels or n in parents:
            kind, need = 'spec', ['## ' + s for s in SPEC_SECTIONS]
        else:
            kind, need = None, []
        for part in need:
            if part == RELIES:
                present = any(line.startswith(RELIES) for line in lines)
            else:
                present = part in lines
            if not present:
                say('T1', '%s lacks %s' % (kind, part))
        if ticket:
            for what in links(read, i['blocked_by']):
                say('B1', what)
        for b in i['blocked_by']:
            if b['state'] == 'closed' and b['state_reason'] != 'completed':
                say('B2', 'blocker #%d is closed as %s, not completed' % (b['number'], b['state_reason'] or 'unknown'))
    return found


ISSUES = """query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, after: $after) {
      pageInfo { hasNextPage endCursor }
      nodes { number body parent { number }
        labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
        blockedBy(first: 100) { pageInfo { hasNextPage } nodes { number state stateReason } }
        comments(first: 100) { pageInfo { hasNextPage endCursor } nodes { %s } } } } } }"""
COMMENTS = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) { issue(number: $number) {
    comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { %s } } } } }"""
COMMENT = 'databaseId updatedAt body author { __typename login }'


def _gh(*args):
    import subprocess
    try:
        p = subprocess.run(('gh',) + args, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        _refuse('gh failed: %s' % e)
    if p.returncode != 0:
        _refuse('gh failed: %s' % (p.stderr.strip().splitlines() or ['exit %d' % p.returncode])[-1])
    return p.stdout


def _graphql(query, **variables):
    args = ['api', 'graphql', '-f', 'query=' + query]
    for k, v in variables.items():
        if v is not None:
            args += ['-F' if isinstance(v, int) else '-f', '%s=%s' % (k, v)]
    try:
        data = json.loads(_gh(*args), object_pairs_hook=_no_repeats)
        return data['data']['repository']
    except (ValueError, KeyError, TypeError):
        _refuse('GitHub gave an unreadable answer')


def _comment(c):
    a = c['author'] or {'__typename': 'User', 'login': 'ghost'}
    login = a['login'] + ('[bot]' if a['__typename'] == 'Bot' else '')
    return {'id': c['databaseId'], 'author': login, 'updated_at': c['updatedAt'], 'body': c['body']}


def record_authors(repo):
    text = _gh('api', 'repos/%s/contents/docs/agents/fleet.md' % repo, '-H', 'Accept: application/vnd.github.raw')
    rows = [line for line in text.splitlines() if re.match(r'^\| Record authors \|', line)]
    names = re.findall(r'`([^`]+)`', rows[0]) if len(rows) == 1 else []
    if not names:
        _refuse('no single Record authors row in docs/agents/fleet.md')
    return names


def read_repo(repo):
    owner, _, name = repo.partition('/')
    tracker = {'tracker': TRACKER, 'repo': repo, 'now': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'record_authors': record_authors(repo), 'issues': []}
    after = None
    while True:
        try:
            page = _graphql(ISSUES % COMMENT, owner=owner, name=name, after=after)['issues']
            for i in page['nodes']:
                if i['labels']['pageInfo']['hasNextPage'] or i['blockedBy']['pageInfo']['hasNextPage']:
                    _refuse('#%d has more labels or blockers than one page' % i['number'])
                comments, more = i['comments']['nodes'], i['comments']['pageInfo']
                while more['hasNextPage']:
                    got = _graphql(COMMENTS % COMMENT, owner=owner, name=name, number=i['number'],
                                   after=more['endCursor'])['issue']['comments']
                    comments, more = comments + got['nodes'], got['pageInfo']
                tracker['issues'].append({
                    'number': i['number'], 'labels': [label['name'] for label in i['labels']['nodes']],
                    'parent': i['parent']['number'] if i['parent'] else None,
                    'blocked_by': [{'number': b['number'], 'state': b['state'].lower(),
                                    'state_reason': (b['stateReason'] or '').lower() or None
                                    if b['state'] == 'CLOSED' else None}
                                   for b in i['blockedBy']['nodes']],
                    'body': i['body'], 'comments': [_comment(c) for c in comments]})
        except (KeyError, TypeError, AttributeError):
            _refuse('GitHub gave an unreadable answer')
        if not page['pageInfo']['hasNextPage']:
            return tracker
        after = page['pageInfo']['endCursor']


def main(argv):
    ap = argparse.ArgumentParser(prog='check.py')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--fixture')
    src.add_argument('--repo')
    args = ap.parse_args(argv)
    try:
        if args.fixture:
            tracker = read_tracker(load_fixture(args.fixture))
        else:
            tracker = read_tracker(read_repo(args.repo))
    except Unreadable as e:
        print('check.py: %s' % e, file=sys.stderr)
        return 2
    found = breaks(tracker)
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
