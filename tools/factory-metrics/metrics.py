#!/usr/bin/env python3
"""Daily factory metrics (#566). Standard library + gh; remote reads only."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html import escape
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

QUERY = '''query($owner:String!,$name:String!,$cursor:String){repository(owner:$owner,name:$name){pullRequests(first:100,after:$cursor){nodes{number mergedAt closedAt closingIssuesReferences(first:100){nodes{number repository{nameWithOwner}} pageInfo{hasNextPage endCursor}}} pageInfo{hasNextPage endCursor}}}}'''
LINK_QUERY = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){closingIssuesReferences(first:100,after:$cursor){nodes{number repository{nameWithOwner}} pageInfo{hasNextPage endCursor}}}}}'''
START = re.compile(r'^(findings sent|CI failure sent|merge blocked|review started)(?:\s|$)')
TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')


class ReadError(Exception):
    pass


def require(ok, reason):
    if not ok:
        raise ReadError(reason)


def load(text):
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'JSON repeats a key')
            out[k] = v
        return out

    def constant(_):
        raise ReadError('JSON contains a non-finite number')

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_float=Decimal, parse_constant=constant)
    except (ValueError, UnicodeError):
        raise ReadError('invalid JSON')


def obj(value):
    require(type(value) is dict, 'expected an object')
    return value


def array(value):
    require(type(value) is list, 'expected an array')
    return value


def integer(value):
    require(type(value) is int and value > 0, 'expected a positive integer')
    return value


def numeric(value):
    require(type(value) in (int, Decimal) and value >= 0, 'expected a nonnegative number')
    return value


def exact(value, keys):
    require(set(obj(value)) == set(keys), 'unexpected or missing fields')


def timestamp(value):
    require(type(value) is str and TIME.fullmatch(value), 'invalid UTC timestamp')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        raise ReadError('invalid UTC timestamp')


def iso(value):
    return value.strftime('%Y-%m-%dT%H:%M:%SZ')


def gh(*args):
    # No caller can pass a free-form command. REST paths and query documents
    # below are fixed; environment (including an App's GH_TOKEN) is inherited.
    try:
        p = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        raise ReadError('gh unavailable, timed out, or returned invalid text')
    # Never print raw stderr, response bodies or authentication data.
    status = re.search(r'HTTP ([1-5][0-9]{2})', p.stderr)
    detail = f', HTTP {status[1]}' if status else ''
    require(p.returncode == 0, f'gh read failed (exit {p.returncode}{detail})')
    return load(p.stdout)


def rest(path):
    return gh('api', '--method', 'GET', path)


def graphql(repo, document, cursor=None, number=None):
    """One fixed query document's answer for REPO; never a mutation."""
    owner, name = repo.split('/')
    args = ['api', 'graphql', '-f', 'query=' + document, '-f', 'owner=' + owner, '-f', 'name=' + name]
    if number is not None:
        args += ['-F', f'number={number}']
    if cursor is not None:
        args += ['-f', 'cursor=' + cursor]
    value = obj(gh(*args))
    require(not value.get('errors'), 'GraphQL reported errors')
    return obj(obj(value.get('data')).get('repository'))


def graph(repo, cursor=None, number=None):
    return graphql(repo, QUERY if number is None else LINK_QUERY, cursor, number)


def connection(value):
    value = obj(value)
    nodes = array(value.get('nodes'))
    info = obj(value.get('pageInfo'))
    more, cursor = info.get('hasNextPage'), info.get('endCursor')
    require(type(more) is bool, 'invalid pageInfo')
    require(not more or (type(cursor) is str and bool(cursor) and bool(nodes)), 'incomplete page')
    return nodes, cursor if more else None


def collect_prs(repo):
    prs, cursor, cursors = {}, None, set()
    while True:
        nodes, following = connection(graph(repo, cursor).get('pullRequests'))
        for value in nodes:
            pr = obj(value)
            n = integer(pr.get('number'))
            require(n not in prs, 'duplicate PR')
            require('mergedAt' in pr and 'closedAt' in pr, 'missing merge/closure timestamp')
            merged = None if pr['mergedAt'] is None else timestamp(pr['mergedAt'])
            closed = None if pr['closedAt'] is None else timestamp(pr['closedAt'])
            links, link_cursor = connection(pr.get('closingIssuesReferences'))
            seen_links, link_cursors, tickets = set(), set(), []
            while True:
                for value in links:
                    issue = obj(value)
                    t = integer(issue.get('number'))
                    name = obj(issue.get('repository')).get('nameWithOwner')
                    require(type(name) is str, 'invalid linked repository')
                    key = (name.lower(), t)
                    require(key not in seen_links, 'duplicate linked issue')
                    seen_links.add(key)
                    if name.lower() == repo.lower():
                        tickets.append(t)
                if link_cursor is None:
                    break
                require(link_cursor not in link_cursors, 'repeated link cursor')
                link_cursors.add(link_cursor)
                links, link_cursor = connection(obj(graph(repo, link_cursor, n).get('pullRequest')).get('closingIssuesReferences'))
            prs[n] = {'merged': merged, 'closed': closed, 'tickets': sorted(tickets)}
        if following is None:
            return prs
        require(following not in cursors, 'repeated PR cursor')
        cursors.add(following)
        cursor = following



# WR8 only. Existing daily/journey query documents and reads remain unchanged.
DIRECTION_QUERY = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){issue(number:$number){number title milestone{title} labels(first:100,after:$cursor){nodes{name} pageInfo{hasNextPage endCursor}}}}}'''


def activity_directions(repo, prs, *, read):
    """Join validated collect_prs facts to current closing-ticket metadata.

    Uses the board's Polish -> version milestone -> side group precedence.
    This labels CURRENT metadata, never a historical ticket classification.
    Each PR gets one direction only when all same-repository links agree.
    """
    tickets, result = {}, []
    for number, pr in prs.items():
        integer(number)
        if pr['merged'] is None:
            continue
        directions = set()
        for t in pr['tickets']:
            if t not in tickets:
                cursor, cursors, labels, first = None, set(), set(), None
                while True:
                    issue = obj(read(repo, DIRECTION_QUERY, cursor, t).get('issue'))
                    require(integer(issue.get('number')) == t, 'direction ticket mismatch')
                    title, milestone = issue.get('title'), issue.get('milestone')
                    require(type(title) is str and 'milestone' in issue, 'missing direction metadata')
                    ms = None if milestone is None else obj(milestone).get('title')
                    require(milestone is None or (type(ms) is str and bool(ms)), 'invalid direction milestone')
                    shape = (title, ms)
                    require(first is None or first == shape, 'direction metadata changed between pages')
                    first = shape
                    nodes, following = connection(issue.get('labels'))
                    for node in nodes:
                        label = obj(node).get('name')
                        require(type(label) is str and label not in labels, 'invalid or duplicate direction label')
                        labels.add(label)
                    if following is None:
                        break
                    require(following not in cursors, 'repeated direction cursor')
                    cursors.add(following)
                    cursor = following
                polish = 'polish' in labels or title.startswith('Proposal:') or 'follow-up' in title
                tickets[t] = 'backwards' if polish else 'forward' if (ms or '').startswith('0.') else 'sideways'
            directions.add(tickets[t])
        result.append({'number': number, 'merged_at': iso(pr['merged']),
                       'direction': next(iter(directions)) if len(directions) == 1 else None,
                       'tickets': [{'number': t, 'direction': tickets[t]} for t in pr['tickets']]})
    return sorted(result, key=lambda p: p['number'])


def collect_records(repo, prs):
    records, seen, edited, skewed, page = [], set(), 0, 0, 1
    prefix = f'https://api.github.com/repos/{repo}/issues/'
    # All surviving comments, including predecessors before midnight. No
    # since filter: it filters updates and cannot establish the predecessor.
    while True:
        rows = array(rest(f'repos/{repo}/issues/comments?per_page=100&page={page}'))
        for value in rows:
            c = obj(value)
            cid = integer(c.get('id'))
            require(cid not in seen, 'duplicate comment')
            seen.add(cid)
            url = c.get('issue_url')
            require(type(url) is str and url.lower().startswith(prefix.lower()) and
                    re.fullmatch(r'[1-9][0-9]*', url[len(prefix):]), 'invalid comment issue URL')
            n = int(url[len(prefix):])
            created, at = timestamp(c.get('created_at')), timestamp(c.get('updated_at'))
            body = c.get('body')
            require(type(body) is str, 'invalid comment body')
            first = next((line.strip() for line in body.splitlines() if line.strip()), '')
            if not first.startswith('launch-fleet:'):
                continue
            skewed += at < created
            at = max(at, created)  # Never place a record before its comment existed.
            record = first[len('launch-fleet:'):].strip()
            if not record:
                continue
            tickets = prs[n]['tickets'] if n in prs else [n]
            # PRs with no same-repository closing issue remain explicitly
            # unlinked. They still get measured against their own comments.
            targets = {n, *tickets}
            match = START.match(record)
            records.append({'id': cid, 'at': at, 'targets': targets, 'tickets': tickets,
                            'pr': n if n in prs else None, 'kind': match[1] if match else None})
            edited += at != created
        if len(rows) < 100:
            return sorted(records, key=lambda r: (r['at'], r['id'])), edited, skewed
        page += 1


def measure(day, prs, records, edited, skewed):
    end = day + timedelta(days=1)
    hours = [{'hour': h, 'merged_prs': 0, 'idle_minutes': 0} for h in range(24)]
    merged = [p for p in prs.values() if p['merged'] is not None and day <= p['merged'] < end]
    for p in merged:
        hours[p['merged'].hour]['merged_prs'] += 1
    # A merged PR finishes each linked ticket; closing an unmerged PR does not.
    ticket_merges = {}
    for pr in prs.values():
        if pr['merged'] is not None:
            for ticket in pr['tickets']:
                ticket_merges[ticket] = min(ticket_merges.get(ticket, pr['merged']), pr['merged'])
    # Look backwards to find each event's next record on ANY of its targets.
    # A shared multi-ticket event appears once, not once per linked ticket.
    next_at, stalls, total_seconds = {}, [], 0
    for r in reversed(records):
        ends = [next_at[t] for t in r['targets'] if t in next_at]
        if r['pr'] is not None:
            pr = prs[r['pr']]
            ends.extend(at for at in (pr['merged'], pr['closed']) if at is not None)
        else:
            ends.extend(ticket_merges[t] for t in r['tickets'] if t in ticket_merges)
        following = min(ends, default=end)
        if r['kind'] and r['at'] < end:
            a, b = max(day, r['at']), min(end, following)
            if b > a:
                seconds = (b - a).total_seconds()
                total_seconds += seconds
                minutes = seconds / 60
                stalls.append({'tickets': r['tickets'], 'pull_request': r['pr'], 'kind': r['kind'],
                               'from': iso(a), 'until': iso(b), 'minutes': round(minutes, 6),
                               'open_at_midnight': not ends or following > end})
                for h in hours:
                    lo = day + timedelta(hours=h['hour'])
                    hi = lo + timedelta(hours=1)
                    h['idle_minutes'] += max(0, (min(b, hi) - max(a, lo)).total_seconds()) / 60
        for target in r['targets']:
            next_at[target] = r['at']
    stalls.sort(key=lambda s: (-s['minutes'], s['from'], s['tickets']))
    for h in hours:
        h['idle_minutes'] = round(h['idle_minutes'], 6)
    return {'schema': 'closedwiz.factory-metrics.v1', 'date': day.strftime('%Y-%m-%d'),
            'merged_prs': len(merged), 'merged_per_hour': round(len(merged) / 24, 6), 'hours': hours,
            'idle_minutes': round(total_seconds / 60, 6),
            'biggest_stall': stalls[0] if stalls else None, 'stalls': stalls,
            'historical_completeness': 'unknown: edited/deleted records have no recoverable history in this read',
            'edited_fleet_comments': edited, 'clock_skew_comments': skewed}


def amount(value, count):
    return {'total': None if value is None else round(float(value), 6),
            'per_merged_pr': None if value is None or not count else round(float(value) / count, 6)}


def unknown(units, reason, count):
    return {**{unit: amount(None, count) for unit in units}, 'reason': reason}


USAGE_UNITS = {'claude': ('tokens', 'credits', 'usd'), 'gpt': ('tokens', 'credits', 'usd'),
               'sandbox': ('hours', 'usd')}


def read_usage(path, date=None):
    """A validated daily CloudRoom usage export (README schema), for DATE or,
    without one, for the UTC day it names. Raises ReadError with the reason."""
    require(path is not None, 'No daily CloudRoom usage export; this cloud CLI has no daily usage/billing endpoint')
    try:
        data = obj(load(path.read_text()))
    except (OSError, UnicodeError):
        raise ReadError('Cannot read daily CloudRoom usage export')
    exact(data, ('date', 'complete', 'claude', 'gpt', 'sandbox'))
    if date is None:
        require(type(data['date']) is str, 'CloudRoom export is not complete for this UTC day')
        try:
            day_arg(data['date'])
        except argparse.ArgumentTypeError:
            raise ReadError('CloudRoom export is not complete for this UTC day')
        date = data['date']
    require(data['date'] == date and data['complete'] is True, 'CloudRoom export is not complete for this UTC day')
    for provider in ('claude', 'gpt'):
        seen = set()
        for row in array(data[provider]):
            exact(row, ('thread', 'tokens', 'credits', 'usd'))
            key = row['thread']
            require(type(key) is str and bool(key) and key not in seen, 'invalid or duplicate usage thread')
            seen.add(key)
            for unit in USAGE_UNITS[provider]:
                if row[unit] is not None:
                    numeric(row[unit])
                    if unit == 'tokens':
                        require(type(row[unit]) is int, 'tokens must be an integer')
    exact(data['sandbox'], ('hours', 'usd'))
    for unit in USAGE_UNITS['sandbox']:
        if data['sandbox'][unit] is not None:
            numeric(data['sandbox'][unit])
    return data


def cloud_costs(path, date, count):
    units = USAGE_UNITS
    try:
        data = read_usage(path, date)
        result = {}
        for provider in ('claude', 'gpt'):
            rows, threads = data[provider], []
            for i, row in enumerate(rows):
                # Never persist a real session identifier, even from an export.
                threads.append({'thread': f'{provider}-{i+1:03}', **{u: row[u] for u in units[provider]}})
            values = {}
            for unit in units[provider]:
                total = sum(row[unit] for row in rows) if all(row[unit] is not None for row in rows) else None
                values[unit] = amount(total, count)
            result[provider] = {**values, 'threads': threads, 'reason': 'Unreported units are unknown'}
        result['sandbox'] = {'reason': 'Unreported units are unknown'}
        for unit in units['sandbox']:
            result['sandbox'][unit] = amount(data['sandbox'][unit], count)
        return result
    except ReadError as e:
        return {source: unknown(us, str(e), count) for source, us in units.items()}


def actions_costs(repo, day, count):
    try:
        owner_type = obj(obj(rest('repos/' + repo)).get('owner')).get('type')
        require(owner_type in ('User', 'Organization'), 'unknown billing owner type')
        root = 'users' if owner_type == 'User' else 'organizations'
        path = f'{root}/{repo.split("/")[0]}/settings/billing/usage/summary?year={day.year}&month={day.month}&day={day.day}&repository={quote(repo, safe="")}&product=Actions'
        data = obj(rest(path))
        period = obj(data.get('timePeriod'))
        exact(period, ('year', 'month', 'day'))
        require(all(type(v) is int for v in period.values()), 'billing period fields must be integers')
        require(period == {'year': day.year, 'month': day.month, 'day': day.day},
                'billing response does not confirm the requested day')
        minutes = usd = Decimal(0)
        for value in array(data.get('usageItems')):
            row = obj(value)
            product, unit = row.get('product'), row.get('unitType')
            require(type(product) is str and product.casefold() == 'actions', 'unrecognized Actions billing product')
            require(type(unit) is str and bool(unit.strip()), 'invalid Actions billing unit')
            quantity = numeric(row.get('grossQuantity'))
            if unit.casefold() == 'minutes':
                minutes += quantity
            usd += numeric(row.get('netAmount'))
        return {'minutes': amount(minutes, count), 'usd': amount(usd, count),
                'reason': 'GitHub daily billing summary: reported hosted minutes; net USD includes storage and other Actions charges; self-hosted PC runners free'}
    except ReadError as e:
        return unknown(('minutes', 'usd'), str(e), count)


def fnum(value):
    return 'unknown' if value is None else f'{value:,.2f}'


def report_text(report):
    stall = report['biggest_stall']
    lines = [f'# Factory — {report["date"]} UTC', '',
             f'PRs merged: {report["merged_prs"]} ({report["merged_per_hour"]:.3f} per hour over 24 hours).',
             f'Recorded idle agent-minutes: {report["idle_minutes"]:.2f}.',
             'Historical completeness: unknown — surviving fleet comments only; edited/deleted history is unavailable.',
             'Gaps measure missing fleet records, including work in progress; they do not prove an agent was idle.',
             f'Timestamp anomalies: {report["clock_skew_comments"]} fleet comments have an update before creation; these use creation time.', '']
    if stall:
        name = ', '.join(f'#{t}' for t in stall['tickets']) or f'unlinked PR #{stall["pull_request"]}'
        lines += [f'Biggest recorded stall: {name}, {stall["minutes"]:.2f} minutes ({stall["kind"]}, {stall["from"]} to {stall["until"]}).', '']
    else:
        lines += ['Biggest recorded stall: none.', '']
    if not report['merged_prs']:
        lines += ['Cost per merged PR: unknown (no merged PRs).', '']
    lines += ['Costs are source-reported units, not inferred prices. Per merged PR divides the whole day\'s usage by its merges; it is not attribution to those PRs.', '',
              '| Source / unit | Day total | Per merged PR |', '| --- | ---: | ---: |']
    for source in ('claude', 'gpt', 'sandbox', 'actions'):
        units = ('tokens', 'credits', 'usd') if source in ('claude', 'gpt') else ('hours', 'usd') if source == 'sandbox' else ('minutes', 'usd')
        for unit in units:
            value = report['costs'][source][unit]
            lines.append(f'| {source} / {unit} | {fnum(value["total"])} | {fnum(value["per_merged_pr"])} |')
    total = report['costs']['total_usd']
    lines += [f'| Factory / USD | {fnum(total["total"])} | {fnum(total["per_merged_pr"])} |', '']
    for source in ('claude', 'gpt', 'sandbox', 'actions'):
        lines.append(f'{source}: {report["costs"][source]["reason"]}.')
        for thread in report['costs'][source].get('threads', []):
            lines.append(f'- {thread["thread"]}: {fnum(thread["tokens"])} tokens; {fnum(thread["credits"])} credits; {fnum(thread["usd"])} USD.')
    lines += ['', '![Hourly factory metrics](factory.svg)', '',
              '| Hour UTC | Merged PRs | Recorded idle minutes |', '| --- | ---: | ---: |']
    for h in report['hours']:
        lines.append(f'| {h["hour"]:02} | {h["merged_prs"]} | {h["idle_minutes"]:.2f} |')
    lines += ['', 'Records are ordered by the later of creation and last update, then comment ID. Each of the four start kinds ends at the next fleet record on its PR or any same-repository closing ticket, capped at its PR merge/closure or, for a ticket record, the merge of a PR that closes it. Open tails stop at midnight. Cross-hour gaps are split; a multi-ticket start is counted once.',
              'GitHub billing can lag. Unknown components keep the factory USD total unknown. No money is derived from tokens, credits or hours.', '']
    return '\n'.join(lines)


def precise(value):
    return f'{value:.6f}'.rstrip('0').rstrip('.')


def chart(report):
    # Two separate aligned panels avoid a misleading shared scale. Different
    # labels and positions remain legible without colour; exact values on marks.
    colors = ('#0072B2', '#D55E00')
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="1240" height="920" viewBox="0 0 1240 920" role="img" aria-labelledby="title desc">',
             f'<title id="title">Factory metrics — {report["date"]} UTC</title>',
             '<desc id="desc">24 hourly rows: merged PRs beside recorded idle minutes. Independent scales. Exact values labelled; table in report.md.</desc>',
             '<rect width="1240" height="920" fill="#fff"/>',
             '<g font-family="sans-serif" fill="#172333">',
             f'<text x="40" y="45" font-size="26">Factory • {report["date"]} UTC</text>',
             '<text x="40" y="77" font-size="16">Recorded gaps only • historical completeness unknown</text>']
    for column, (key, label, color) in enumerate(zip(('merged_prs', 'idle_minutes'), ('merged PRs', 'idle minutes'), colors)):
        left = 100 + column * 600
        maximum = max(1, max(h[key] for h in report['hours']))
        lines.append(f'<text x="{left}" y="113" font-size="20">{escape(label)} / hour (scale 0–{precise(maximum)})</text>')
        for h in report['hours']:
            y, value = 140 + h['hour'] * 30, h[key]
            width = value / maximum * 410
            title = f'{h["hour"]:02} UTC: {precise(value)} {label}'
            lines += [f'<text x="{left-55}" y="{y+15}" font-size="14">{h["hour"]:02}:00</text>',
                      f'<rect x="{left}" y="{y}" width="{width:.3f}" height="20" fill="{color}"><title>{title}</title></rect>',
                      f'<text x="{left+width+8:.3f}" y="{y+15}" font-size="14">{precise(value)}</text>']
    lines += ['<text x="40" y="895" font-size="14">Idle minutes may exceed 60 per hour: simultaneous gaps on different tickets add together.</text>', '</g></svg>']
    return '\n'.join(lines) + '\n'


def day_arg(text):
    try:
        if not re.fullmatch(r'\d{4}-\d\d-\d\d', text):
            raise ValueError()
        return datetime.strptime(text, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        raise argparse.ArgumentTypeError('date must be YYYY-MM-DD')


def repo_arg(text):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_][A-Za-z0-9_.-]*', text):
        raise argparse.ArgumentTypeError('repo must be OWNER/REPO')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', type=day_arg, required=True, help='UTC day, YYYY-MM-DD')
    parser.add_argument('--repo', type=repo_arg, required=True, help='OWNER/REPO')
    parser.add_argument('--out', type=Path, required=True, help='new directory for aggregate report and chart')
    parser.add_argument('--usage', type=Path, help='optional complete daily CloudRoom usage export (README schema)')
    args = parser.parse_args()
    try:
        require(not args.out.exists(), 'output directory already exists; choose a new directory')
        prs = collect_prs(args.repo)
        records, edited, skewed = collect_records(args.repo, prs)
        report = measure(args.date, prs, records, edited, skewed)
        count = report['merged_prs']
        costs = cloud_costs(args.usage, report['date'], count)
        costs['actions'] = actions_costs(args.repo, args.date, count)
        dollars = [costs[s]['usd']['total'] for s in ('claude', 'gpt', 'sandbox', 'actions')]
        costs['total_usd'] = amount(sum(Decimal(str(d)) for d in dollars), count) if all(d is not None for d in dollars) else amount(None, count)
        report['costs'] = costs
        md, svg = report_text(report), chart(report)
        # Output is a local artifact, never raw responses or thread identifiers.
        encoded = json.dumps(report, indent=2, default=float) + '\n'
        args.out.mkdir(parents=True)
        (args.out / 'report.json').write_text(encoded)
        (args.out / 'report.md').write_text(md)
        (args.out / 'factory.svg').write_text(svg)
        print(md)
        return 0
    except (ReadError, OSError) as e:
        print(f'factory-metrics: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
