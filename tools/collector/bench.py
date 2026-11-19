#!/usr/bin/env python3
"""FF1 (#1331, spec #1329): the faster factory's bench, before and after.

    bench.py --repo OWNER/NAME --since UTC --until UTC --out FILE [--label BEFORE]

Runs the collector over a stated window of merged tickets and prints, and saves
to FILE, the hours per ticket split into builder, CI, waiting for a wake,
review and rework; review rounds per ticket; CI minutes per PR head (slowest
job and total); and the wait from each event (CI finished, review posted,
merge) to the fleet's next action. RULES below are saved with the numbers, so
the after run is measured the same way. Unknown stays unknown, never zero.

Reads, all through the collector: the `merges` and `flow` facts
(collect_factory.py), the `ci3` fact and its kept window (collect_ci.py) and
record-author comments (collect_factory's flow reader). Exit 0 with the
numbers, 1 when the cohort can't be read (nothing written), 2 on a bad
command line, before any read. Python 3 standard library only, and gh.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collector_runtime  # noqa: E402
import collect_ci as CI  # noqa: E402
import collect_factory as CF  # noqa: E402

C3 = CI.C3
J = CF.J
SCHEMA = 'openwiz.faster-factory.bench.v1'
BASE = 'main'
CATEGORIES = ('builder', 'ci', 'wake', 'review', 'rework')
EVENTS = ('ci_finished', 'review_posted', 'merge')
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
TIME = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')
RECORD = 'launch-fleet:'
RULES = (
    'Cohort: every pull request merged into main in [since, until), and the tickets it closes today. Pull '
    'requests into other bases are left out; a merged one with no closing ticket is listed as unlinked.',
    "Claim, merge and review rounds are the collector's flow fact (#1165): the first builder start record "
    'to the last linked merge, and the independent verdicts.',
    'Hours are split from claim to merge, round by round, for a ticket with exactly one pull request: builder '
    "(claim to the first reviewed head's push), CI (a reviewed head's push to its CI result, cut off at the "
    'review request), wake (CI result to the recorded review request), review (request to verdict) and rework '
    '(a verdict to the next reviewed head\'s push). After the final APPROVE: wake to the merge-queued record, '
    'then CI (the merge queue) to the merge. The five add up to claim-to-merge exactly.',
    "CI per head is CI3's window (ci3.v1) from the cohort's earliest claim, or since if earlier, to until: for "
    "each head of a cohort pull request, its slowest job and its total runner minutes (CI3's job-time rules) "
    "and its time to result. The time to a pull request's result is CI3's own record, carried.",
    "Waits run from each event (a reviewed head's CI result, an independent verdict, the merge) to the next "
    'fleet record (a launch-fleet: comment by a record author) on the ticket or its pull request, at or after it.',
    'Unknown is never zero: a ticket, head or wait that cannot be read or paired is null, with its reason, and '
    'left out of every percentile and sum; each summary counts what was known and what was unknown (for '
    'waits, every unpaired event plus every ticket whose comments could not be read).',
    "Percentiles are nearest rank (CI3's rule). Hours have 2 decimals, minutes 1.",
)


class Refused(Exception):
    """The cohort itself can't be read: no numbers at all."""


class Unreadable(Exception):
    """One source can't be read: what depends on it is unknown."""


class Gap(Exception):
    """A ticket's timeline can't be paired: its split is unknown."""


def at(text):
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def iso(moment):
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def now():
    return iso(datetime.now(timezone.utc))


def seconds(start, end):
    return (at(end) - at(start)).total_seconds()


class GitHub:
    """The collector's reads for one repository."""

    def __init__(self, repo):
        self.repo, self.authors = repo, None

    def merges(self, since, until):
        return CF.read(self.repo, ['merges'], since=since, until=until)['factory']['merges']

    def flow(self, tickets, since, until):
        return CF.read(self.repo, ['flow'], since=since, until=until, tickets=list(tickets))['factory']['flow']

    def ci3(self, since, until):
        fact = CI.read(self.repo, ['ci3'], since=since, until=until)['ci']['ci3']
        if fact['value'] is None:
            return fact, None
        try:
            return fact, C3.read_window(CI.store() / fact['source']['path'])
        except (C3.Fail, OSError):
            return {**fact, 'state': 'unavailable', 'prerequisites': ["CI3's kept window could not be read."]}, None

    def comments(self, kind, n):
        try:
            self.authors = self.authors or CF.flow_authors()
            query = CF.FLOW_ISSUE if kind == 'issue' else CF.FLOW_PULL
            _, found = CF.flow_subject(J.Collector(self.repo), query, kind, n, self.authors)
        except (CF.M.ReadError, OSError, ValueError, TypeError, KeyError) as error:
            raise Unreadable(f'the {kind} comments could not be read') from error
        return [{'at': c['at'], 'body': c['body']} for c in found]


def gather(repo, since, until, reads):
    """Every read the bench makes, once. Refused when the cohort itself can't be read."""
    merges = reads.merges(since, until)
    if merges['state'] != 'known':
        raise Refused("the window's merges could not be read, so there is no cohort")
    prs = [p for p in merges['value']['pull_requests'] if p['base'] == BASE]
    tickets = sorted({t for p in prs for t in p['tickets']})
    flow = reads.flow(tickets, since, until) if tickets else None
    rows = {r['ticket']: r for r in (flow['value']['tickets'] if flow and flow['value'] else [])}
    claims = [rows[t]['claimed_at'] for t in tickets if t in rows and rows[t]['claimed_at']]
    ci_since = min([since, *claims])
    ci3, window = reads.ci3(ci_since, until)
    cohort = {p['number'] for p in prs}
    linked = {p for r in rows.values() for p in r['pull_requests']}
    comments, reasons = {}, {}
    for t in tickets:
        row = rows.get(t)
        if row is None or row['state'] != 'merged' or not row['claimed_at'] or not row['merged_at']:
            reasons[t] = "the flow fact could not read this ticket's claim or merge"
        elif len(row['pull_requests']) != 1:
            reasons[t] = 'more than one pull request: the hours are not split'
        else:
            try:
                comments[t] = (reads.comments('issue', t) + reads.comments('pullRequest', row['pull_requests'][0]))
            except Unreadable as error:
                reasons[t] = str(error)
    return {'repository': repo, 'window': {'since': since, 'until': until, 'timezone': 'UTC'},
            'ci_window': {'since': ci_since, 'until': until, 'timezone': 'UTC'},
            'merged_prs': sorted(cohort), 'unlinked_prs': sorted(p['number'] for p in prs if not p['tickets']),
            'tickets': tickets, 'flow': flow, 'rows': rows, 'ci3': ci3,
            'heads': None if window is None else [h for h in window['heads'] if h['pr'] in cohort | linked],
            'comments': comments, 'reasons': reasons, 'read_at': now()}


def head_row(h, table):
    row = {'pr': h['pr'], 'head': h['sha'], 'start': h['start'], 'result_at': None, 'outcome': None,
           'time_to_result_minutes': None, 'slowest_job_minutes': None, 'runner_minutes': None, 'unknown': None}
    try:
        got, why = C3.result(h, h['start'], table) if h['sha'] else (None, 'push time unknown')
    except C3.Fail:
        got, why = None, 'its runs could not be paired'
    if got is None:
        return {**row, 'unknown': why}
    jobs = [j for run in h['runs'].values() if run for a in run['attempts'] for j in C3.owned(a)]
    end = datetime.fromtimestamp(at(h['start']).timestamp() + got['seconds'], timezone.utc)
    return {**row, 'result_at': iso(end),
            'outcome': got['outcome'], 'time_to_result_minutes': round(got['seconds'] / 60, 1),
            'slowest_job_minutes': round(max((C3.job_secs(j) for j in jobs), default=0) / 60, 1),
            'runner_minutes': round(C3.runner_seconds([h]) / 60, 1)}


def verdicts_of(comments, merge):
    """Independent verdicts up to the merge, once each: (at, verdict, head)."""
    out, seen = [], set()
    for c in sorted(comments, key=lambda c: c['at']):
        identity = CF.flow_verdict_identity(c['body'])
        m = identity and identity[1] and J.VERDICT_EXACT.fullmatch(identity[0])
        if m and c['at'] <= merge and c['body'] not in seen:
            seen.add(c['body'])
            out.append((c['at'], m[1], m[2]))
    return out


def split(claim, merge, verdicts, records, heads):
    """Seconds per category from claim to merge; Gap when a round can't be paired."""
    if not verdicts:
        raise Gap('no independent verdict before the merge')
    parts, prev = [], claim
    for i, (when, _, head) in enumerate(verdicts):
        request = min((t for t, line in records if (m := CF.FLOW_REVIEW_START.fullmatch(line))
                       and m[1] == head and prev <= t <= when), default=None)
        if request is None:
            raise Gap('a verdict without its recorded review request')
        h = heads.get(head)
        if h is None or h['result_at'] is None:
            raise Gap('a reviewed head without a CI result')
        push = min(max(h['start'], prev), request)
        result = min(max(h['result_at'], push), request)
        parts += [('builder' if i == 0 else 'rework', prev, push), ('ci', push, result), ('wake', result, request),
                  ('review', request, when)]
        prev = when
    if verdicts[-1][1] != 'APPROVE':
        raise Gap('merged without a final APPROVE')
    queued = min((t for t, line in records if (m := CF.FLOW_QUEUE.fullmatch(line))
                  and m[1] == verdicts[-1][2] and prev <= t <= merge), default=None)
    if queued is None:
        raise Gap('no merge-queued record between the APPROVE and the merge')
    parts += [('wake', prev, queued), ('ci', queued, merge)]
    totals = dict.fromkeys(CATEGORIES, 0)
    for name, start, end in parts:
        totals[name] += seconds(start, end)
    return totals


def waits(merge, verdicts, records, heads):
    def after(event):
        if event is None:
            return None
        nxt = min((t for t, _ in records if t >= event), default=None)
        return None if nxt is None else round(seconds(event, nxt) / 60, 1)
    reviewed = list(dict.fromkeys(head for _, _, head in verdicts))
    return {'ci_finished': [after(heads[h]['result_at'] if h in heads else None) for h in reviewed],
            'review_posted': [after(when) for when, _, _ in verdicts], 'merge': [after(merge)]}


def ticket_row(n, g, heads):
    row = g['rows'].get(n) or {}
    out = {'ticket': n, 'pull_requests': row.get('pull_requests'), 'claimed_at': row.get('claimed_at'),
           'merged_at': row.get('merged_at'), 'review_rounds': row.get('review_rounds'), 'hours': None,
           'waits_minutes': None, 'unknown': []}
    if out['review_rounds'] is None:
        out['unknown'].append('review rounds: the flow fact could not establish them')
    if n in g['reasons']:
        out['unknown'].append(g['reasons'][n])
        return out
    claim, merge, comments = row['claimed_at'], row['merged_at'], g['comments'][n]
    records = sorted((c['at'], J.first_line(c['body'])) for c in comments
                     if J.first_line(c['body']).startswith(RECORD))
    verdicts = verdicts_of(comments, merge)
    out['waits_minutes'] = waits(merge, verdicts, records, heads)
    try:
        parts = split(claim, merge, verdicts, records, heads)
        out['hours'] = {k: round(v / 3600, 2) for k, v in parts.items()}
        out['hours']['total'] = round(seconds(claim, merge) / 3600, 2)
    except Gap as gap:
        out['unknown'].append(f'hours: {gap}')
    return out


def dist(values, unknown):
    known = [v for v in values if v is not None]
    rank = lambda p: C3.rank(sorted(known), p)  # noqa: E731
    total = sum(known)
    return {'known': len(known), 'unknown': unknown + len(values) - len(known), 'p50': rank(0.5), 'p75': rank(0.75),
            'max': max(known, default=None), 'sum': round(total, 2) if known and type(total) is float else
            (total if known else None)}


def measure(g, label=None):
    """The bench document: deterministic over what gather read."""
    table = C3.bench.read_table(C3.bench.STEPS)
    heads = [head_row(h, table) for h in g['heads'] or []]
    by_sha = {h['head']: h for h in heads if h['head']}
    rows = [ticket_row(n, g, by_sha) for n in g['tickets']]
    timed = [r for r in rows if r['hours'] is not None]
    untimed = len(rows) - len(timed)
    ci3 = g['ci3']
    flow = g['flow'] or {'state': 'unavailable', 'prerequisites': ['No ticket to read.']}
    return {
        'schema': SCHEMA, 'label': label, 'repository': g['repository'], 'window': g['window'],
        'read_at': g['read_at'], 'rules': list(RULES),
        'cohort': {'merged_prs': g['merged_prs'], 'unlinked_prs': g['unlinked_prs'], 'tickets': g['tickets']},
        'flow': {'state': flow['state'], 'prerequisites': flow['prerequisites']},
        'tickets': rows, 'heads': heads,
        'ci': {'window': g['ci_window'], 'state': ci3['state'], 'prerequisites': ci3['prerequisites'],
               'time_to_result': ci3['value']['result'] if ci3['value'] else None},
        'summary': {
            'hours': {k: dist([r['hours'][k] for r in timed], untimed) for k in (*CATEGORIES, 'total')},
            'review_rounds': dist([r['review_rounds'] for r in rows], 0),
            'ci_per_head': {k: dist([h[k] for h in heads], 0)
                            for k in ('slowest_job_minutes', 'runner_minutes', 'time_to_result_minutes')},
            'waits_minutes': {e: dist([w for r in rows if r['waits_minutes'] for w in r['waits_minutes'][e]],
                                      sum(1 for r in rows if r['waits_minutes'] is None)) for e in EVENTS},
        },
    }


def text(doc):
    s = doc['summary']
    w = doc['window']

    def line(name, d, unit):
        if not d['known']:
            return f'  {name:<26} unknown ({d["unknown"]} unknown)'
        return (f'  {name:<26} p50 {d["p50"]} {unit}, p75 {d["p75"]}, max {d["max"]}, sum {d["sum"]}'
                f'  ({d["known"]} known, {d["unknown"]} unknown)')
    ttr = doc['ci']['time_to_result']
    out = [f'Faster-factory bench {doc["label"] or ""} for {doc["repository"]}, [{w["since"]}, {w["until"]})',
           f'  {len(doc["cohort"]["merged_prs"])} PRs merged into main, {len(doc["tickets"])} tickets, '
           f'{len(doc["cohort"]["unlinked_prs"])} unlinked PRs; flow fact {doc["flow"]["state"]}, '
           f'CI3 {doc["ci"]["state"]}',
           'Hours per ticket:']
    out += [line(k, s['hours'][k], 'h') for k in (*CATEGORIES, 'total')]
    out += ['Review rounds:', line('review rounds', s['review_rounds'], 'rounds'), 'CI per PR head:',
            line('slowest job', s['ci_per_head']['slowest_job_minutes'], 'min'),
            line('runner minutes', s['ci_per_head']['runner_minutes'], 'min'),
            line('time to result', s['ci_per_head']['time_to_result_minutes'], 'min'),
            '  CI3 time to a PR\'s result: ' + (f'p50 {ttr["p50_minutes"]} min, p95 {ttr["p95_minutes"]} min'
                                                 if ttr else 'unknown'),
            'Wait to the fleet\'s next action, after:']
    out += [line(e.replace('_', ' '), s['waits_minutes'][e], 'min') for e in EVENTS]
    unknown = [f'  #{r["ticket"]}: {"; ".join(r["unknown"])}' for r in doc['tickets'] if r['unknown']]
    return '\n'.join(out + (['Unknown:'] + unknown if unknown else [])) + '\n'


def main(argv=None, reads=None):
    parser = argparse.ArgumentParser(prog='bench.py', description=__doc__.split('\n\n')[0])
    parser.add_argument('--repo', required=True)
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--label')
    args = parser.parse_args(argv)
    if not REPO.fullmatch(args.repo):
        parser.error('--repo must be OWNER/NAME')
    if not (TIME.fullmatch(args.since) and TIME.fullmatch(args.until) and args.since < args.until <= now()):
        parser.error('--since and --until are UTC times, since before until, and until already past')
    try:
        doc = measure(gather(args.repo, args.since, args.until, reads or GitHub(args.repo)), args.label)
        data = json.dumps(doc, indent=1, sort_keys=True) + '\n'
        collector_runtime.scan_bytes(data.encode())
    except (Refused, collector_runtime.Fail, CF.Refused, CI.Refused) as error:
        print(f'bench: {error}', file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(data, encoding='utf-8')
    sys.stdout.write(text(doc))
    return 0


if __name__ == '__main__':
    sys.exit(main())
