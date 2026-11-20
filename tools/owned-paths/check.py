#!/usr/bin/env python3
"""Fail a pull request that edits files outside its ticket's owned paths (#1418).

  check.py --pr N [--repo OWNER/NAME]           a pull request's changed files, as CI checks them
  check.py --ticket N [--base REF] [--repo ...] this branch's changes (committed and not) against REF

A file is covered by its linked tickets' `## Owned paths` bullets for this repository
(shared ones too), by the fleet's standing supporting-edit rule in docs/agents/fleet.md,
or by an `F4 supporting edit granted` comment from a record author (docs/agents/fleet.md's
`## GitHub identity` table) on the ticket or the pull request that names it in backticks.
Owned paths are parsed as build-ticket's `ticket.py` parses them. A path ending in `/`, or
naming a folder, covers what is under it; `*` matches within one folder and `**` across.

Tickets are linked by GitHub's closing references and by `Closes`/`Fixes`/`Resolves`/
`Part of` followed by `#N`, `owner/name#N` or the issue's URL; only this repository's
issues are checked. No linked ticket, or none with an `## Owned paths` section: a note.

Reads GitHub only through `gh api graphql`, and fleet.md from the base, never the head.
Exit 0 every file covered (or nothing to check), 1 a file outside (named, with the ticket),
2 an input it cannot read.
"""
import json
import os
import re
import subprocess
import sys

REPO_NAME = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?')
GRANT = re.compile(r'F4 supporting edits? granted', re.I)
LINK = re.compile(r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|part of)\b:?\s+'
                  r'(?:https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)/issues/(\d+)\b'
                  r'|([A-Za-z0-9-]+/[A-Za-z0-9_.-]+)?#(\d+)\b)', re.I)
FLEET = 'docs/agents/fleet.md'

PR_QUERY = '''query($owner: String!, $name: String!, $number: Int!, $files: String, $comments: String) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    body baseRefOid
    closingIssuesReferences(first: 50) { nodes { number repository { nameWithOwner } } }
    files(first: 100, after: $files) { pageInfo { hasNextPage endCursor } nodes { path } }
    comments(first: 100, after: $comments) { pageInfo { hasNextPage endCursor }
      nodes { author { __typename login } body } } } } }'''
ISSUE_QUERY = '''query($owner: String!, $name: String!, $number: Int!, $comments: String) {
  repository(owner: $owner, name: $name) { issueOrPullRequest(number: $number) {
    __typename ... on Issue { body comments(first: 100, after: $comments) {
      pageInfo { hasNextPage endCursor } nodes { author { __typename login } body } } } } } }'''
BLOB_QUERY = '''query($owner: String!, $name: String!, $expression: String!) {
  repository(owner: $owner, name: $name) { object(expression: $expression) { ... on Blob { text } } } }'''


class Unreadable(Exception):
    pass


def run(argv, what):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        raise Unreadable(f'cannot read {what}')
    if r.returncode:
        raise Unreadable(f'cannot read {what}')
    return r.stdout


def graphql(query, what, **variables):
    argv = ['gh', 'api', 'graphql', '-f', f'query={query}']
    for k, v in variables.items():
        if v is not None:
            argv += ['-F' if isinstance(v, int) else '-f', f'{k}={v}']
    try:
        data = json.loads(run(argv, what))
        return data['data']['repository']
    except (ValueError, KeyError, TypeError):
        raise Unreadable(f'cannot read {what}: unexpected shape')


# --- parsing: build-ticket's ticket.py rules (section, owned_bullets, covers) ---

def section(text, heading):
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            inside = line[3:].strip().lower() == heading
            continue
        if inside:
            lines.append(line)
    return lines


def has_section(text, heading):
    return any(l.startswith('## ') and l[3:].strip().lower() == heading for l in text.splitlines())


def is_path(token):
    return (token and token.strip() == token and ' ' not in token and not token.startswith('/')
            and '..' not in token.split('/') and '<' not in token)


def owned_paths(body, repo):
    """(paths, unparsed bullets) of `## Owned paths` bound to repo, as ticket.py's owned_bullets."""
    paths, unparsed = [], []
    for line in section(body, 'owned paths'):
        if not line.startswith('- '):
            continue
        text = line[2:].strip()
        tokens = list(re.finditer(r'`([^`]*)`', text))
        repos = {m.group(1).lower() for m in tokens
                 if REPO_NAME.fullmatch(m.group(1)) and text[:m.start()].endswith('in ')}
        found = [m.group(1) for m in tokens if m.group(1).lower() not in repos and is_path(m.group(1))]
        if len(repos) > 1:
            found = []
        if (next(iter(repos)) if repos else repo) != repo:
            continue
        paths += found
        if not found:
            unparsed.append(text)
    return paths, unparsed


def covers(rule, path):
    rule = rule[2:] if rule.startswith('./') else rule
    if any(c in rule for c in '*?['):
        pattern = ''
        for part in re.split(r'(\*\*/?|\*|\?)', rule.rstrip('/')):
            pattern += {'**/': '(?:.*/)?', '**': '.*', '*': '[^/]*', '?': '[^/]'}.get(part, re.escape(part))
        return re.fullmatch(pattern + r'(?:/.*)?', path) is not None
    rule = rule.rstrip('/')
    return path == rule or path.startswith(rule + '/')


# --- records: who may grant, what the standing rule allows, what each grant names ---

def record_authors(fleet):
    rows = [l for l in section(fleet, 'github identity') if re.match(r'\|\s*Record authors\s*\|', l)]
    if len(rows) != 1:
        return set()
    cell = rows[0].split('|')[2].strip()
    names = [x.strip() for x in cell.split(',')] if cell else []
    names = [x[1:-1] if len(x) > 1 and x[0] == x[-1] == '`' else '' for x in names]
    return {x.lower() for x in names} if names and all(LOGIN.fullmatch(x) for x in names) else set()


def standing(fleet, tickets):
    """The standing rule's numbered kinds' backticked paths, `<ticket>` read as each ticket."""
    out = []
    for line in section(fleet, 'supporting edits'):
        if re.match(r'\d+\. ', line):
            for token in re.findall(r'`([^`]*)`', line):
                for n in tickets:
                    p = token.replace('<ticket>', str(n))
                    if is_path(p) and p not in out:
                        out.append(p)
    return out


def author(comment):
    a = comment.get('author') or {}
    login = str(a.get('login') or '').lower()
    return {login, login + '[bot]'} if a.get('__typename') == 'Bot' else {login}


def grant_paths(body, repo):
    """Backticked paths after the grant marker, if the grant names no repository or this one.

    A backticked `owner/name` after `in ` is a repository, as in ticket.py, unless it looks
    like a file (a dot in its last part) under another owner: `in `ci/lanes.tsv`` is a path.
    """
    m = GRANT.search(body)
    if not m:
        return []
    text = body[m.end():]
    owner = repo.split('/')[0]
    repos, paths = set(), []
    for t in re.finditer(r'`([^`]*)`', text):
        token = t.group(1)
        if (REPO_NAME.fullmatch(token) and text[:t.start()].endswith('in ')
                and (token.split('/')[0].lower() == owner or '.' not in token.split('/')[1])):
            repos.add(token.lower())
        elif is_path(token):
            paths.append(token)
    return paths if not repos or repo in repos else []


# --- links and verdict ---

def linked(repo, body, closing):
    mine, other = [], []
    refs = [(n['repository']['nameWithOwner'], n['number']) for n in closing]
    for m in LINK.finditer(body or ''):
        refs.append((m.group(1) or m.group(3) or repo, int(m.group(2) or m.group(4))))
    for r, n in refs:
        (mine if r.lower() == repo else other).append((r, n))
    seen = []
    return [n for _, n in mine if not (n in seen or seen.append(n))], sorted(set(other))


def judge(repo, files, tickets, other_refs, fleet, pr_comments, pr_label, shown):
    """tickets: {N: {'body', 'comments'}} of this repository. Prints the verdict, returns the exit."""
    for r, n in other_refs:
        print(f'owned-paths: note: {r}#{n} is not a ticket in {shown}: not checked here')
    if not tickets:
        print(f'owned-paths: note: {pr_label} links no ticket in {shown}: nothing to check')
        return 0
    for n, t in tickets.items():
        if not has_section(t['body'], 'owned paths'):
            print(f'owned-paths: note: #{n} has no ## Owned paths section: nothing to check')
    tickets = {n: t for n, t in tickets.items() if has_section(t['body'], 'owned paths')}
    if not tickets:
        return 0
    owned, unparsed = [], []
    for t in tickets.values():
        p, u = owned_paths(t['body'], repo)
        owned += p
        unparsed += u
    trusted = record_authors(fleet)
    if not trusted:
        print(f'owned-paths: note: no record authors in {FLEET} at the base: no grant is trusted')
    granted = [p for c in [c for t in tickets.values() for c in t['comments']] + pr_comments
               if author(c) & trusted for p in grant_paths(c.get('body') or '', repo)]
    rule = standing(fleet, tickets)
    names = ', '.join(f'#{n}' for n in tickets)
    outside = 0
    for path in files:
        if any(covers(r, path) for r in owned):
            print(f'owned: {path}')
        elif any(covers(r, path) for r in rule):
            print(f'standing: {path}')
        elif any(covers(r, path) for r in granted):
            print(f'granted: {path}')
        else:
            print(f'OUT: {path} (ticket {names})')
            outside += 1
    if outside:
        for text in unparsed:
            print(f'owned-paths: note: this owned bullet names no path to check: {text}')
        print(f'owned-paths: {outside} file(s) outside the owned paths and grants of ticket {names}: '
              f'move them out, or ask on the ticket for an F4 supporting edit grant naming each path')
        return 1
    print(f'owned-paths: ok: {len(files)} file(s) inside the owned paths and grants of ticket {names}')
    return 0


# --- reads ---

def read_pr(repo, n):
    owner, name = repo.split('/')
    files, comments, cursors, done = [], [], {'files': None, 'comments': None}, set()
    while True:
        try:
            pr = graphql(PR_QUERY, f'pull request #{n}', owner=owner, name=name, number=n, **cursors)['pullRequest']
            base, body, closing = pr['baseRefOid'], pr['body'], pr['closingIssuesReferences']['nodes']
            for key, into, value in (('files', files, lambda x: x['path']), ('comments', comments, lambda x: x)):
                if key in done:
                    continue
                conn = pr[key]
                into += [value(x) for x in conn['nodes']]
                if conn['pageInfo']['hasNextPage']:
                    cursors[key] = conn['pageInfo']['endCursor']
                else:
                    done.add(key)
        except (KeyError, TypeError):
            raise Unreadable(f'cannot read pull request #{n}: unexpected shape')
        if len(done) == 2:
            return body or '', closing, files, comments, base


def read_ticket(repo, n):
    owner, name = repo.split('/')
    comments, after = [], None
    while True:
        node = graphql(ISSUE_QUERY, f'ticket #{n}', owner=owner, name=name, number=n, comments=after)
        node = (node or {}).get('issueOrPullRequest')
        if not isinstance(node, dict) or node.get('__typename') != 'Issue':
            return None
        try:
            comments += node['comments']['nodes']
            if not node['comments']['pageInfo']['hasNextPage']:
                return {'body': node['body'] or '', 'comments': comments}
            after = node['comments']['pageInfo']['endCursor']
        except (KeyError, TypeError):
            raise Unreadable(f'cannot read ticket #{n}: unexpected shape')


def read_fleet_remote(repo, base):
    owner, name = repo.split('/')
    node = graphql(BLOB_QUERY, f'{FLEET} at the base', owner=owner, name=name, expression=f'{base}:{FLEET}')
    text = ((node or {}).get('object') or {}).get('text')
    return text if isinstance(text, str) else ''


def changed(base):
    """This branch's changed paths against base, committed and not, both sides of a rename."""
    run(['git', 'rev-parse', '--verify', '--quiet', base + '^{commit}'], f'base {base}')
    paths = set()
    fields = run(['git', 'diff', '--name-status', '-z', '--find-renames', f'{base}...HEAD'], 'the diff').split('\0')
    i = 0
    while i < len(fields) and fields[i]:
        count = 2 if fields[i][:1] in ('R', 'C') else 1
        paths.update(fields[i + 1:i + 1 + count])
        i += 1 + count
    fields = run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'], 'git status').split('\0')
    i = 0
    while i < len(fields) and fields[i]:
        paths.add(fields[i][3:])
        if fields[i][:1] in ('R', 'C') or fields[i][1:2] in ('R', 'C'):
            i += 1
            paths.add(fields[i])
        i += 1
    return sorted(p for p in paths if p)


def main(argv):
    flags, i = {}, 0
    while i < len(argv):
        if argv[i] in ('--pr', '--ticket', '--repo', '--base') and i + 1 < len(argv) and argv[i] not in flags:
            flags[argv[i]], i = argv[i + 1], i + 2
        else:
            print(__doc__.split('\n\n')[1], file=sys.stderr)
            return 2
    shown = flags.get('--repo') or os.environ.get('GITHUB_REPOSITORY') or 'openwizdev/OpenWiz'
    repo = shown.lower()
    try:
        if not REPO_NAME.fullmatch(repo) or ('--pr' in flags) == ('--ticket' in flags):
            raise Unreadable('give exactly one of --pr N or --ticket N, and --repo OWNER/NAME')
        if '--pr' in flags:
            n = int(flags['--pr'])
            body, closing, files, pr_comments, base = read_pr(repo, n)
            numbers, other = linked(repo, body, closing)
            fleet = read_fleet_remote(repo, base)
            label = f'pull request #{n}'
        else:
            numbers, other, pr_comments = [int(flags['--ticket'])], [], []
            base = flags.get('--base', 'origin/main')
            files = changed(base)
            try:
                fleet = run(['git', 'show', f'{base}:{FLEET}'], f'{FLEET} at {base}')
            except Unreadable:
                fleet = ''
            label = 'this branch'
        tickets = {}
        for t in numbers:
            node = read_ticket(repo, t)
            if node is None:
                print(f'owned-paths: note: #{t} is not an issue: not checked')
            else:
                tickets[t] = node
        return judge(repo, sorted(set(files)), tickets, other, fleet, pr_comments, label, shown)
    except ValueError:
        print('owned-paths: --pr and --ticket take a number', file=sys.stderr)
        return 2
    except Unreadable as e:
        print(f'owned-paths: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
