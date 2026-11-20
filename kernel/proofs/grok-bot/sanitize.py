"""Turn a recorded run's GitHub records into public evidence, keeping only record forms.

  sanitize.py fetch --repo <owner>/<name> --out <raw.json outside the checkout>
  sanitize.py build <raw.json> --out kernel/proofs/grok-bot/run.md

`fetch` reads the demo repository through the person's signed-in `gh` (REST only) and writes
everything, unsanitized, to a private file. `build` keeps a whitelist: status notes from record
authors, `VERDICT:` headers, `launch-fleet:` first lines, plan approval and spec confirmation
headers without the name or words, with their pointer, checks and fingerprint lines, and merges. Every other body is dropped. It then prints
which stages the run reached; exit 1 names the missing ones. Standard library only.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

MARKER = '<!-- openwiz:status v1 -->'
FIELDS = ('agent', 'state', 'harness', 'model', 'skills', 'step', 'time', 'pr')
PRIVATE = re.compile(
    r'thr_[A-Za-z0-9]|(?<![\w.:/])/[\w.-]+/[\w.-]+|~/|\$\{?HOME|%USERPROFILE%|[A-Za-z]:\\|\\\\|file:'
    r'|\b(?:proj|prj|mch|usr|acct|auto|cr)_[A-Za-z0-9]|\b(?:token|key|secret|password|sig)\s*[=:]'
    r'|Bearer\s|\bgh[a-z]_|github_pat_|AKIA|xox[a-z]-|\bsk-|["“”]|^>|[\w.+-]+@[\w-]+\.[A-Za-z]{2,}', re.I)
URL = r'https://github\.com/[\w.-]+/[\w.-]+/(?:issues|pull)/\d+#issuecomment-\d+'
VERDICT = re.compile(r'VERDICT: (?:APPROVE|CHANGES) at [0-9a-f]{40}')
MACHINE = re.compile(r'\*\*(Machine plan approval, \d{4}-\d\d-\d\d, revision \d+:)\*\* '
                     r'(links, relies, sizes, width and owned paths passed\.)')
HUMAN = re.compile(r'\*\*(Plan graph approved|Spec confirmed) by [^,*]+, (\d{4}-\d\d-\d\d)(, revision \d+)?:\*\*')
KEPT = re.compile(rf'(?:Grill confirmed|Private record): {URL}|Checks: [\w ,;:]+\.|Fingerprint: `[0-9a-f]{{64}}`')
STAGES = ('spec', 'grill pointer', 'plan approved', 'started', 'builder', 'reviewer', 'approved', 'merged')


def clean(text):
    return text if text and not PRIVATE.search(text) else None


def note(body):
    lines = body.split('\n')
    pairs = [line.partition(': ') for line in lines[1:] if line.strip()]
    fields = {k: v for k, _, v in pairs}
    if len(fields) != len(pairs) or not set(fields) <= set(FIELDS) or not set(FIELDS[:7]) <= set(fields):
        return 'status note withheld: unreadable', None
    if not all(clean(v) or k == 'pr' and v.startswith('https://github.com/') for k, v in fields.items()):
        return 'status note withheld: private value', None
    text = f"{fields['agent']} {fields['state']}, {fields['harness']}, {fields['model']}, {fields['skills']}: {fields['step']}"
    return text + (f" ({fields['pr']})" if 'pr' in fields else ''), fields['agent']


def record(body, author, authors, seen):
    """One public line for a comment, and the stage it shows."""
    first = body.strip().split('\n', 1)[0].strip()
    if author.lower() not in authors:
        return 'comment, body dropped'
    if first == MARKER:
        text, agent = note(body.strip())
        if agent in ('builder', 'reviewer'):
            seen.add(agent)
        return text
    if VERDICT.fullmatch(first):
        seen.update({'reviewer'} | ({'approved'} if 'APPROVE' in first else set()))
        return first
    if first.startswith('launch-fleet: ') and clean(first):
        if first.startswith('launch-fleet: started'):
            seen.add('started')
        return first
    if m := MACHINE.fullmatch(first):
        text = f'{m[1]} {m[2]}'
    elif m := HUMAN.match(first):
        text = f'{m[1].lower()}, {m[2]}{m[3] or ""}'
    else:
        return 'comment, body dropped'
    if m[0].startswith(('**Machine', '**Plan')):
        seen.add('plan approved')
    kept = [line.strip() for line in body.split('\n')[1:] if KEPT.fullmatch(line.strip())]
    if any(line.startswith('Grill confirmed: ') for line in kept):
        seen.add('grill pointer')
    return '\n'.join([text] + [f'  - {line}' for line in kept])


def build(raw):
    authors = {a.lower() for a in raw['record_authors']}
    seen, out = set(), [f"# Recorded run on {raw['repo']}", '']
    for item in sorted(raw['items'], key=lambda i: i['number']):
        title = clean(item['title']) or 'title withheld'
        state = item['state'] + (f", {item['state_reason']}" if item.get('state_reason') else '')
        labels = ', '.join(sorted(item['labels']))
        out.append(f"## {'PR' if item['pr'] else 'Issue'} #{item['number']}: {title}")
        out.append(f"{state}; labels: {labels or 'none'}")
        if 'spec' in item['labels']:
            seen.add('spec')
        if item.get('merged_at'):
            seen.add('merged')
            out.append(f"- merged at {item['merged_at']} as {item['merge_sha']} (head {item['head_sha']})")
        events = [(c['time'], c['id'], c['author'], c['body']) for c in item['comments']]
        events += [(r['time'], r['id'], r['author'], r['body'] or '') for r in item.get('reviews', [])]
        for time, _, author, body in sorted(events):
            who = author if author.lower() in authors else 'someone else'
            out.append(f'- {time} {who}: {record(body, author, authors, seen)}')
        out.append('')
    missing = [s for s in STAGES if s not in seen]
    return '\n'.join(out), missing


def gh(path):
    done = subprocess.run(['gh', 'api', '--paginate', '--slurp', path], capture_output=True, text=True, check=True)
    pages = json.loads(done.stdout)
    return [x for page in pages for x in (page if isinstance(page, list) else [page])]


def fetch(repo):
    import base64
    fleet = base64.b64decode(gh(f'repos/{repo}/contents/docs/agents/fleet.md')[0]['content']).decode()
    row = next(line for line in fleet.splitlines() if line.startswith('| Record authors |'))
    authors = re.findall(r'`([^`]+)`', row.split('|')[2])
    items = []
    for issue in gh(f'repos/{repo}/issues?state=all&per_page=100'):
        n, pr = issue['number'], 'pull_request' in issue
        item = {'number': n, 'pr': pr, 'title': issue['title'], 'state': issue['state'],
                'state_reason': issue.get('state_reason'), 'labels': [x['name'] for x in issue['labels']],
                'body': issue['body'] or '', 'merged_at': None, 'merge_sha': None, 'head_sha': None, 'reviews': [],
                'comments': [{'id': c['id'], 'author': c['user']['login'], 'time': c['created_at'], 'body': c['body']}
                             for c in gh(f'repos/{repo}/issues/{n}/comments?per_page=100')]}
        if pr:
            p = gh(f'repos/{repo}/pulls/{n}')[0]
            item.update(merged_at=p['merged_at'], merge_sha=p['merge_commit_sha'] if p['merged_at'] else None,
                        head_sha=p['head']['sha'])
            item['reviews'] = [{'id': r['id'], 'author': r['user']['login'], 'time': r['submitted_at'], 'body': r['body']}
                               for r in gh(f'repos/{repo}/pulls/{n}/reviews?per_page=100')]
        items.append(item)
    return {'repo': repo, 'record_authors': authors, 'items': items}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    f = sub.add_parser('fetch')
    f.add_argument('--repo', required=True)
    f.add_argument('--out', type=Path, required=True)
    b = sub.add_parser('build')
    b.add_argument('raw', type=Path)
    b.add_argument('--out', type=Path, required=True)
    args = p.parse_args(argv)
    if args.command == 'fetch':
        args.out.write_text(json.dumps(fetch(args.repo), indent=1))
        print(f'fetched {args.repo} to {args.out}; keep it private')
        return 0
    text, missing = build(json.loads(args.raw.read_text()))
    args.out.write_text(text)
    print('stages: ok' if not missing else 'stages missing: ' + ', '.join(missing))
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
