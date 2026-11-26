#!/usr/bin/env python3
USAGE = """
  check.py --base REV --merge REV (--description-file FILE | --pr N|QUEUE-REF --repo OWNER/NAME)
  check.py --total REV                 print the total and always pass (pushes to main)
Exit 0 passes, 1 fails, 2 is unreadable input."""

import argparse
import json
import re
import subprocess
import sys
import time

CATEGORIES = [
    ('tests+fixtures', r'(^|/)(tests?|fixtures?|__tests__|testdata)/|(_test|\.test|\.spec)\.|(^|/)test_[^/]*$'),
    ('ci', r'^\.github/|^ci/'), ('tools', r'^tools/|^scripts/'), ('contracts', r'^contracts/'),
    ('skills', r'^skills/'), ('docs', r'\.md$|^docs/'), ('lockfiles', r'(\.lock|lock\.json|lock\.yaml)$')]
ORDER = [name for name, _ in CATEGORIES] + ['product']
LOCKFILE = dict(CATEGORIES)['lockfiles']
CEILING_FILE = 'line-budget.json'
POINTER = r'https://github\.com/jparker2006/ClosedWiz/(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*'
EXCEPTION, CEILING = 'Line budget exception:', 'Line budget ceiling:'
QUERY = '''query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) { body } } }'''


class Unreadable(Exception):
    pass


def git(repo, *args, data=None):
    r = subprocess.run(['git', '-C', repo, *args], input=data, capture_output=True)
    if r.returncode:
        raise Unreadable(f'cannot read git {" ".join(args)}')
    return r.stdout


def category(path):
    return next((name for name, rule in CATEGORIES if re.search(rule, path)), 'product')


def count(repo, rev):
    git(repo, 'rev-parse', '--verify', '--quiet', f'{rev}^{{commit}}')
    blobs = []
    for entry in git(repo, 'ls-tree', '-r', '-z', '--full-tree', rev).split(b'\0')[:-1]:
        meta, path = entry.split(b'\t', 1)
        mode, _, sha = meta.split()
        if mode in (b'100644', b'100755'):
            blobs.append((path.decode('utf-8', 'surrogateescape'), sha))
    out = git(repo, 'cat-file', '--batch', data=b''.join(sha + b'\n' for _, sha in blobs))
    lines, ceiling, at = dict.fromkeys(ORDER + ['locked'], 0), None, 0
    for path, _ in blobs:
        eol = out.index(b'\n', at)
        size = int(out[at:eol].split()[2])
        body, at = out[eol + 1:eol + 1 + size], eol + 2 + size
        if path == CEILING_FILE:
            ceiling = body
        if b'\0' not in body:
            n = body.count(b'\n') + (not body.endswith(b'\n') if body else 0)
            lines[category(path)] += n
            lines['locked'] += n if re.search(LOCKFILE, path) else 0
    return lines, ceiling


def unique(pairs):
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('a repeated key')
    return dict(pairs)


def read_ceiling(raw):
    try:
        data = json.loads(raw, object_pairs_hook=unique)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict) or set(data) != {'ceiling'} or type(data['ceiling']) is not int \
            or data['ceiling'] <= 0:
        raise Unreadable(f'{CEILING_FILE} must be exactly {{"ceiling": <positive number>}}')
    return data['ceiling']


def pointer_lines(description, prefix):
    found = [line for line in description.splitlines() if line.startswith(prefix)]
    bad = [line for line in found if not re.fullmatch(re.escape(prefix) + ' ' + POINTER, line)]
    return len(found) > len(bad), bad


def pr_number(text):
    m = re.fullmatch(r'[1-9][0-9]*', text) or re.search(r'/pr-([1-9][0-9]*)-[0-9a-f]+$', text)
    return int(m.group(m.lastindex or 0)) if m else None


def read_description(repo_name, pr):
    number = pr_number(pr)
    owner, _, name = repo_name.partition('/')
    if number is None or not name:
        raise Unreadable(f'cannot name the pull request from {pr!r}')
    argv = ['gh', 'api', 'graphql', '-f', f'query={QUERY}', '-f', f'owner={owner}',
            '-f', f'name={name}', '-F', f'number={number}']
    r = subprocess.run(argv, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)['data']['repository']['pullRequest']['body'] or ''
    except (ValueError, KeyError, TypeError):
        raise Unreadable(f'cannot read pull request #{number}\'s description')


def report(base, merge, ceiling, seconds):
    print(f'line-budget: counted in {seconds:.2f}s')
    print(f'  {"category":<15} {"base":>8} {"merge":>8} {"change":>7}')
    for name in ORDER + ['total']:
        b, m = (sum(c[n] for n in ORDER) if name == 'total' else c[name] for c in (base, merge))
        print(f'  {name:<15} {b:>8} {m:>8} {m - b:>+7}')
    b, m = (sum(c[n] for n in ORDER) - c['locked'] for c in (base, merge))
    print(f'line-budget: total, lockfiles excluded: {m} of {ceiling}; base {b}, change {m - b:+}')
    return b, m


def judge(base, merge, ceiling, totals, ceiling_changed, description):
    base_total, total = totals
    errors = []
    excepted, bad = pointer_lines(description, EXCEPTION)
    errors += [f'malformed exception line: {s!r}; the form is "{EXCEPTION} <pointer>"' for s in bad]
    recorded, bad = pointer_lines(description, CEILING)
    errors += [f'malformed ceiling line: {s!r}; the form is "{CEILING} <pointer>"' for s in bad]
    if ceiling_changed and not recorded:
        errors.append(f'{CEILING_FILE} changed; the description needs a "{CEILING} <pointer>" line')
    if base_total > ceiling:
        print(f'line-budget: base is {base_total - ceiling} lines over the ceiling. '
              'The budget is report-only while the base is over.')
    elif total > ceiling and not excepted:
        grew = ', '.join(f'{n} {merge[n] - base[n]:+}' for n in ORDER
                         if n != 'lockfiles' and merge[n] > base[n]) or 'none'
        errors.append(f'{total} lines is {total - ceiling} over the ceiling of {ceiling}; grew: {grew}.'
                      f' Cut lines, or add "{EXCEPTION} <pointer>" naming the owner\'s decision')
    elif total > ceiling:
        print('line-budget: over the ceiling under a recorded exception; the reviewer checks its pointer')
    for e in errors:
        print(f'line-budget: {e}', file=sys.stderr)
    return 1 if errors else 0


def main(argv):
    p = argparse.ArgumentParser(usage=USAGE)
    p.add_argument('--repo-dir', default='.')
    p.add_argument('--total')
    p.add_argument('--base')
    p.add_argument('--merge')
    p.add_argument('--description-file')
    p.add_argument('--pr')
    p.add_argument('--repo')
    a = p.parse_args(argv)
    try:
        start = time.monotonic()
        if a.total:
            counts, raw = count(a.repo_dir, a.total)
            report(counts, counts, read_ceiling(raw), time.monotonic() - start)
            return 0
        if not (a.base and a.merge) or (a.description_file is None) == (a.pr is None):
            raise Unreadable('give --base, --merge and one of --description-file or --pr')
        (base, base_raw), (merge, raw) = count(a.repo_dir, a.base), count(a.repo_dir, a.merge)
        ceiling = read_ceiling(raw)
        totals = report(base, merge, ceiling, time.monotonic() - start)
        if a.description_file is not None:
            with open(a.description_file, encoding='utf-8') as f:
                description = f.read()
        else:
            description = read_description(a.repo or '', a.pr)
        return judge(base, merge, ceiling, totals, base_raw != raw, description)
    except (Unreadable, OSError, UnicodeDecodeError) as e:
        print(f'line-budget: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
