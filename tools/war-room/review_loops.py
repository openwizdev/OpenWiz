#!/usr/bin/env python3
"""RL0 review-loops bench (spec #2454), as contracts/review-loops.v1.md pins it.

Reads already collected inputs only and starts nothing: no GitHub read, no
clock, no write except the files `project` is told to write.

  bench --cohort F --journey F --outcomes F --findings F [--reports F] [--watchdog F]
  check-report FILE
  compare BEFORE AFTER [--safety-escapes F]
  project BENCH --journey F --source-path P --bench-path P --observed-at T --evidence URL --out DIR

Rounds come from the journey verdict reader (`rounds_of`) with WR6's rework
admission; push timing and defects from EB6's outcome rows and
`outcome_cohort`. No verdict text is parsed again; only `check-report` and
`findings_from_report` read report text, for the contract's new lines.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import suite as S  # noqa: E402
import sources as SRC  # noqa: E402


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


T = _module('review_loops_trends', HERE.parent / 'ci-bench/trends.py')
J = T.J
W = _module('review_loops_rework', HERE / 'rework.py')

BENCH = 'closedwiz.review-loops.bench.v1'
COHORT = 'closedwiz.review-loops.cohort.v1'
FINDINGS = 'closedwiz.review-loops.findings.v1'
WATCHDOG = 'closedwiz.review-loops.watchdog.v1'
ESCAPES = 'closedwiz.review-loops.safety-escapes.v1'
REPORTS = 'closedwiz.review-loops.reports.v1'
# The contract's frozen EB6 defect policy: BEFORE and AFTER both use exactly this.
DEFECT_POLICY = {'rule': 'explicit-causal-fix-link-v1', 'followup_hours': 72,
                 'deduplication': 'root-cause-per-merge', 'unknown_attribution': 'retain-unknown'}
COMPARE = 'closedwiz.review-loops.compare.v1'
TARGET = 1.5
KINDS = ('no-review-start', 'no-verdict')
ACTIONS = ('flag', 'restart', 'ask')
RISKS = ('security', 'privacy', 'data loss')
HEAD = re.compile(r'[0-9a-f]{40}')
NAME = re.compile(r'[a-z0-9][a-z0-9-]{0,79}')
COMMENT = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:pull|issues)/[1-9][0-9]*'
                     r'(?:#(?:issuecomment|pullrequestreview)-[1-9][0-9]*)?')
PRIVATE = re.compile(r'(?i)\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}|authorization\s*:|bearer\s+'
                     r'|-----BEGIN .*PRIVATE KEY|\bthr_[A-Za-z0-9_-]+')
MEASURES = ('review_rounds', 'first_push_to_merge_hours', 'pr_opened_to_merge_hours',
            'real_user_path', 'escaped_defects', 'watchdog')


class Refused(ValueError):
    """A refusal whose message is fixed text, safe to print."""


def require(ok, message):
    if not ok:
        raise Refused(message)


def sha(data):
    return hashlib.sha256(data if type(data) is bytes else data.encode()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def dumps(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n'


def exact(value, keys, what):
    require(type(value) is dict and set(value) == set(keys), f'invalid {what} fields')


def coverage(n, of):
    return round(n / of, 6) if of else None


def spread(values, unknown, size):
    d = T.distribution(values, unknown)
    return {'n': d['n'], 'unknown': d['unknown'], 'mean': d['mean'], 'median': d['median'], 'p90': d['p90'],
            'coverage': coverage(d['n'], size)}


# --- inputs -----------------------------------------------------------------

def read_cohort(c):
    exact(c, ('schema', 'name', 'since', 'until', 'base', 'read_at', 'prs'), 'cohort')
    require(c['schema'] == COHORT, 'unknown cohort schema')
    require(type(c['name']) is str and NAME.fullmatch(c['name']), 'invalid cohort name')
    require(c['base'] == 'main', 'the cohort base is main')
    since, until, read = S._time(c['since']), S._time(c['until']), S._time(c['read_at'])
    require(since < until <= read, 'invalid cohort window')
    prs = c['prs']
    require(type(prs) is list and all(type(n) is int and n > 0 for n in prs), 'invalid cohort PRs')
    require(prs == sorted(set(prs)), 'cohort PRs must be sorted and unique')
    return c


def read_findings(f, cohort):
    exact(f, ('schema', 'cohort', 'findings'), 'findings')
    require(f['schema'] == FINDINGS and f['cohort'] == cohort['name'], 'findings for another cohort')
    require(type(f['findings']) is list, 'invalid findings list')
    rows, seen = [], set()
    for row in f['findings']:
        exact(row, ('pr', 'finding', 'severity', 'report', 'basis', 'user_path', 'why'), 'finding')
        require(type(row['pr']) is int and row['pr'] in cohort['prs'], 'finding outside the cohort')
        require(type(row['finding']) is str and re.fullmatch(r'R[1-9][0-9]*', row['finding']), 'invalid finding id')
        require(row['severity'] in ('high', 'medium', 'blocking'), 'not a blocking-grade finding')
        require(type(row['report']) is str and COMMENT.fullmatch(row['report']), 'invalid report link')
        require(row['basis'] in ('judgment', 'line'), 'invalid basis')
        require((row['basis'] == 'line') == (row['severity'] == 'blocking'), 'basis and grade disagree')
        require(type(row['user_path']) is bool, 'user_path is a boolean')
        require(type(row['why']) is str and 0 < len(row['why']) <= 300 and '\n' not in row['why']
                and not PRIVATE.search(row['why']), 'invalid why')
        key = (row['pr'], row['finding'])
        require(key not in seen, 'a finding classified twice')
        seen.add(key)
        rows.append(row)
    return rows


def read_watchdog(text):
    events = []
    for line in text.splitlines():
        if not line.strip():
            continue
        e = S._decode(line)
        exact(e, ('schema', 'at', 'pr', 'head', 'kind', 'action', 'since'), 'watchdog event')
        require(e['schema'] == WATCHDOG, 'unknown watchdog schema')
        require(S._time(e['since']) <= S._time(e['at']), 'watchdog clock after its action')
        require(type(e['pr']) is int and e['pr'] > 0, 'invalid watchdog PR')
        require(type(e['head']) is str and HEAD.fullmatch(e['head']), 'invalid watchdog head')
        require(e['kind'] in KINDS and e['action'] in ACTIONS, 'invalid watchdog kind or action')
        events.append(e)
    return events


def read_reports(reports, cohort, admitted_by_pr, sources, expected):
    """AFTER's inventory of new blocking findings, from the reports of admitted rounds.

    Each report binds to one admitted (independent, nonduplicate, unedited,
    pre-merge) journey round by PR, round id, verdict and head; its link is that
    round's source. Returns the round counts (None without reports) and
    {(pr, finding): (report link, has a User path: line)}.
    """
    if reports is None:
        return None, {}
    exact(reports, ('schema', 'cohort', 'reports'), 'reports')
    require(reports['schema'] == REPORTS and reports['cohort'] == cohort['name'], 'reports for another cohort')
    require(type(reports['reports']) is list, 'invalid reports list')
    read, lines = set(), {}
    for row in reports['reports']:
        exact(row, ('pr', 'round', 'text'), 'report')
        event = (admitted_by_pr.get(row['pr'], {}).get(row['round'])
                 if type(row['pr']) is int and type(row['round']) is str else None)
        require(event is not None, 'a report for a round that is not an admitted review round')
        require((row['pr'], row['round']) not in read, 'a round reported twice')
        read.add((row['pr'], row['round']))
        require(type(row['text']) is str, 'invalid report text')
        first = next((x.strip() for x in row['text'].splitlines() if x.strip()), '')
        verdict = VERDICT.fullmatch(first)
        require(verdict is not None and verdict[1] == event['verdict'] and verdict[2] == event['head'],
                "the report's VERDICT line differs from its round")
        for f in parse_report(row['text'])['findings']:
            if f['grade'] == 'blocking' and f['new']:
                key = (row['pr'], f['id'])
                require(key not in lines and key not in expected, 'a blocking finding id repeated')
                lines[key] = (sources[event['source']], f['user_path'])
    rounds = sum(len(v) for v in admitted_by_pr.values())
    return {'rounds': rounds, 'read': len(read), 'missing': rounds - len(read)}, lines


# --- the bench --------------------------------------------------------------

def bench(cohort, journey, outcomes, findings, watchdog=None, reports=None):
    """Return the sanitized aggregate for one cohort (contract: Bench output).

    cohort/findings are decoded records; journey/outcomes are the exact bytes
    collected; watchdog is the event log's text, or None where none applies.
    """
    try:
        return _bench(cohort, journey, outcomes, findings, watchdog, reports)
    except Refused:
        raise
    except (J.ReadError, ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
        # Source parser messages can carry source text: never pass them on.
        raise ValueError('invalid review-loops input') from error


def _bench(cohort, journey, outcomes, findings, watchdog, reports):
    c = read_cohort(cohort)
    require(type(journey) is bytes and type(outcomes) is bytes, 'expected artifact bytes')
    doc, export = J.M.load(journey), J.M.load(outcomes)
    require(type(export) is dict and export.get('defect_policy') == DEFECT_POLICY,
            "not the contract's frozen defect policy")
    J.validate_outcome_export(export, doc)  # validates the journey too
    rows_in = read_findings(findings, c)
    size = len(c['prs'])
    prs = {p['number']: p for p in doc['pull_requests']}
    outcome = {r['pr']: r for r in J.outcome_rows(doc, export)}
    present, missing = [], []
    rounds, unknown_rounds, pushes, opened = [], [], [], []
    ids = {k: [] for k in ('review_rounds', 'first_push', 'pr_opened', 'findings_classified',
                           'known_mature', 'immature', 'unknown_followup')}
    expected = {}
    admitted_by_pr = {}
    for n in c['prs']:
        p = prs.get(n)
        if p is None:
            missing.append({'pr': n, 'why': 'not in the journey'})
            continue
        merges = [e for e in p['events'] if e['kind'] == 'merge']
        if (p['state'] != 'merged' or len(merges) != 1 or merges[0]['completeness'] != 'complete'
                or not c['since'] <= merges[0]['at'] < c['until']
                or merges[0]['commit'] is None or merges[0]['commit'] != p['revisions']['merge']):
            missing.append({'pr': n, 'why': 'no verified merge in the window'})
            continue
        present.append(p)
        merged_at = merges[0]['at']
        # WR6's admission: independent, nonduplicate, unedited, before the merge.
        admitted = [e for e in p['events'] if J.rounds_of(e) and e['completeness'] == 'complete'
                    and e['at'] <= merged_at]
        admitted_by_pr[n] = {e['id']: e for e in admitted}
        if admitted:
            rounds.append(len({e['head'] for e in admitted}))
            ids['review_rounds'].append(n)
        r = outcome[n]
        if r['first_push_to_merged_hours'] is not None:
            pushes.append(r['first_push_to_merged_hours'])
            ids['first_push'].append(n)
        start = [e['at'] for e in p['events'] if e['kind'] == 'pr_opened' and e['at'] is not None]
        if start and start[0] <= merged_at:
            opened.append(round((S._time(merged_at) - S._time(start[0])).total_seconds() / 3600, 6))
            ids['pr_opened'].append(n)
        status = r['defect_followup']
        if status == 'mature' and r['defects']['unknown'] == 0:
            ids['known_mature'].append(n)
        elif status == 'unmatured':
            ids['immature'].append(n)
        elif status == 'unknown':
            ids['unknown_followup'].append(n)
        by_id = {e['id']: e for e in admitted}
        for f in p['findings']:
            if f['severity'] in ('high', 'medium') and f['raised_by'] in by_id:
                expected[(n, f['id'])] = (f['severity'], doc['sources'][by_id[f['raised_by']]['source']])
    inventory, lines = read_reports(reports, c, admitted_by_pr, doc['sources'], expected)
    yes = no = 0
    bases = set()
    for row in rows_in:
        key = (row['pr'], row['finding'])
        if row['basis'] == 'judgment':
            require(key in expected, 'classification for a finding the journey does not show')
            require(expected[key] == (row['severity'], row['report']), 'classification severity or report differs')
        else:
            require(key in lines, 'a line classification needs its finding in a supplied report')
            require(lines[key] == (row['report'], row['user_path']), 'line classification differs from its report')
        bases.add(row['basis'])
        yes += row['user_path']
        no += not row['user_path']
        ids['findings_classified'].append(f'{row["pr"]}:{row["finding"]}')
    total = len(expected) + len(lines)
    classified = yes + no
    complete = not (inventory and inventory['missing'])  # every admitted round's report read, when supplied
    defects = T.outcome_cohort(doc, export, present)['defects']
    watch = None
    if watchdog is not None:
        events = read_watchdog(watchdog)
        inside = [e for e in events if e['pr'] in c['prs']]
        watch = {'events': len(inside), 'heads': len({(e['pr'], e['head']) for e in inside}),
                 'outside_cohort': len(events) - len(inside)}
        for action in ACTIONS:
            watch[action] = {k: sum(e['action'] == action and e['kind'] == k for e in inside) for k in KINDS}
    review = spread(rounds, size - len(rounds), size)
    review['total'] = sum(rounds)
    result = {
        'schema': BENCH,
        'cohort': {'name': c['name'], 'since': c['since'], 'until': c['until'], 'base': c['base'],
                   'read_at': c['read_at'], 'prs': c['prs'], 'size': size, 'missing': missing},
        'inputs': {'cohort': sha(canonical(cohort)), 'journey': sha(journey), 'outcomes': sha(outcomes),
                   'findings': sha(canonical(findings)), 'watchdog': None if watchdog is None else sha(watchdog),
                   'reports': None if reports is None else sha(canonical(reports))},
        'measures': {
            'review_rounds': review,
            'first_push_to_merge_hours': spread(pushes, size - len(pushes), size),
            'pr_opened_to_merge_hours': spread(opened, size - len(opened), size),
            'real_user_path': {'findings': total, 'classified': classified, 'unknown': total - classified,
                               'user_path': yes, 'no_user_path': no,
                               'share': round(yes / classified, 6) if classified and complete else None,
                               'coverage': coverage(classified, total) if complete else None,
                               'basis': sorted(bases), 'reports': inventory},
            'escaped_defects': {'mature': defects['mature'], 'immature': defects['unmatured'],
                                'unknown_followup': defects['unknown_followup'] + len(missing),
                                'unknown_attribution': defects['unknown_attribution'],
                                'known_mature_prs': defects['known_mature_prs'],
                                'affected_mature_prs': defects['affected_mature_prs'],
                                'attributable_events': defects['attributable_events'],
                                'rate': defects['rate'], 'coverage': coverage(defects['known_mature_prs'], size),
                                'policy': export['defect_policy']},
            'watchdog': watch,
        },
        'identities': ids,
    }
    return json.loads(json.dumps(result, default=float))


# --- review reports ---------------------------------------------------------

FINDING = re.compile(r'- \*\*(R[1-9][0-9]*) \[([a-z]+)\]\*\* (.*)')
STATUSES = ('resolved at', 'withdrawn', 'still open after', 'disputed, kept', 'follow-up',
            'Polish issue:', 'logged as polish')
OPEN = ('still open after', 'disputed, kept')
USER = re.compile(r'User path: \S.*')
RISK = re.compile(r'Risk: (security|privacy|data loss): \S.*')
POLISH = re.compile(r'Polish issue: #[1-9][0-9]*\b')
VERDICT = re.compile(r'VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})')
IDS = r'R[1-9][0-9]*(?:(?:, R[1-9][0-9]*)* and R[1-9][0-9]*)?'
NEXT = {'builder': rf'Next: the builder fixes or disputes ({IDS}) once, then one re-check\.',
        'orchestrator': rf'Next: the orchestrator decides ({IDS}): fix once more, or log and merge\.',
        'final': rf'Next: the orchestrator logs ({IDS}) and merges, or asks Jake for a security, privacy, '
                 r'live, spending or publishing call\.',
        'merge': r"Next: none open\. It merges by the project's merge rules\."}
GRADES = {'blocking': 'blocking', 'polish': 'polish', 'high': 'blocking', 'medium': 'blocking', 'low': 'polish'}


def parse_report(text):
    """The report's verdict, findings and Next: line, in the contract's terms."""
    lines = text.splitlines()
    first = next((x.strip() for x in lines if x.strip()), '')
    verdict = VERDICT.fullmatch(first)
    findings = []
    for i, raw in enumerate(lines):
        m = FINDING.fullmatch(raw.strip())
        if not m:
            continue
        more = []
        for nxt in lines[i + 1:]:
            if not nxt.strip() or not nxt[:1].isspace():
                break
            more.append(nxt.strip())
        rest = m[3]
        status = next((s for s in STATUSES if rest.startswith(s)), None)
        user = any(USER.fullmatch(x) for x in more)
        risk = next((RISK.fullmatch(x)[1] for x in more if RISK.fullmatch(x)), None)
        findings.append({'id': m[1], 'grade': m[2], 'class': GRADES.get(m[2]), 'new': bool(J.NEW.match(rest)),
                         'status': status, 'user_path': user, 'risk': risk,
                         'polish': bool(POLISH.search(' '.join([rest] + more)))})
    nexts = [x.strip() for x in lines if x.strip().startswith('Next:')]
    return {'verdict': verdict[1] if verdict else None, 'findings': findings,
            'next': nexts[-1] if nexts else None}


def open_blocking(report):
    return [f['id'] for f in report['findings'] if f['class'] == 'blocking' and
            (f['new'] or f['status'] in OPEN)]


def check_report(text):
    """Every way the report breaks the contract's lines; empty when it passes."""
    r = parse_report(text)
    problems, seen = [], set()
    for f in r['findings']:
        if f['id'] in seen:
            problems.append(f'{f["id"]}: repeated id')
        seen.add(f['id'])
        if f['class'] is None:
            problems.append(f'{f["id"]}: unknown grade {f["grade"]}')
        elif f['grade'] not in ('blocking', 'polish'):
            problems.append(f'{f["id"]}: old grade {f["grade"]}; use blocking or polish')
        elif not f['new'] and f['status'] is None:
            problems.append(f'{f["id"]}: neither a new finding nor a status')
        elif f['new'] and f['class'] == 'blocking' and not (f['user_path'] or f['risk']):
            problems.append(f'{f["id"]}: a blocking finding needs a User path: or Risk: line')
        elif f['new'] and f['class'] == 'polish' and not f['polish']:
            problems.append(f'{f["id"]}: a polish finding needs its Polish issue: #<n>')
    if r['verdict'] is None:
        problems.append('no VERDICT line')
    opened = open_blocking(r)
    if r['verdict'] is not None and (r['verdict'] == 'CHANGES') != bool(opened):
        problems.append('the verdict is CHANGES only while a blocking finding is open')
    if r['next'] is None:
        problems.append('no Next: line')
    else:
        ok = False
        for state, pattern in NEXT.items():
            m = re.fullmatch(pattern, r['next'])
            if m and state == 'merge':
                ok = not opened
            elif m:
                ok = set(re.findall(r'R[1-9][0-9]*', m[1])) == set(opened)
            if m:
                break
        if not ok:
            problems.append('Next: names no contract state for the open blocking findings')
    return problems


def findings_from_report(text, pr, report):
    """AFTER's line-basis classification rows for one report's new blocking findings."""
    rows = []
    for f in parse_report(text)['findings']:
        if f['grade'] == 'blocking' and f['new']:
            why = ('User path line' if f['user_path'] else
                   f'Risk line: {f["risk"]}' if f['risk'] else 'no User path or Risk line')
            rows.append({'pr': pr, 'finding': f['id'], 'severity': 'blocking', 'report': report,
                         'basis': 'line', 'user_path': f['user_path'], 'why': why})
    return rows


# --- BEFORE against AFTER ---------------------------------------------------

def _summary(name, m):
    if m is None:
        return None
    if name == 'real_user_path':
        return {'n': m['classified'], 'unknown': m['unknown'], 'coverage': m['coverage'], 'value': m['share']}
    if name == 'escaped_defects':
        return {'n': m['known_mature_prs'], 'unknown': m['immature'] + m['unknown_followup'] + m['unknown_attribution'],
                'coverage': m['coverage'], 'value': m['rate']}
    if name == 'watchdog':
        return dict(m)
    return {'n': m['n'], 'unknown': m['unknown'], 'coverage': m['coverage'], 'value': m['mean'],
            'median': m['median'], 'p90': m['p90']}


def compare(before, after, escapes=None):
    for b in (before, after):
        exact(b, ('schema', 'cohort', 'inputs', 'measures', 'identities'), 'bench output')
        require(b['schema'] == BENCH and set(b['measures']) == set(MEASURES), 'not a review-loops bench output')
    require(all(b['measures']['escaped_defects']['policy'] == DEFECT_POLICY for b in (before, after)),
            "a bench output not on the contract's frozen defect policy")
    found = []
    if escapes is not None:
        exact(escapes, ('schema', 'escapes'), 'safety escapes')
        require(escapes['schema'] == ESCAPES and type(escapes['escapes']) is list, 'unknown safety-escape schema')
        for e in escapes['escapes']:
            exact(e, ('pr', 'finding', 'risk', 'defect'), 'safety escape')
            require(type(e['pr']) is int and e['pr'] in after['cohort']['prs'], 'escape outside the AFTER cohort')
            require(type(e['finding']) is str and re.fullmatch(r'R[1-9][0-9]*', e['finding']), 'invalid finding id')
            require(e['risk'] in RISKS, 'an escape names security, privacy or data loss')
            require(type(e['defect']) is str and SRC.LINK.fullmatch(e['defect']), 'invalid defect link')
            found.append(e)
    rows = [{'measure': k, 'before': _summary(k, before['measures'][k]), 'after': _summary(k, after['measures'][k])}
            for k in MEASURES]
    mean = after['measures']['review_rounds']['mean']
    target = {'rounds_per_pr': TARGET, 'before_mean': before['measures']['review_rounds']['mean'],
              'after_mean': mean, 'result': 'unknown' if mean is None else 'met' if mean <= TARGET else 'not met'}
    b_rate = before['measures']['escaped_defects']['rate']
    a_rate = after['measures']['escaped_defects']['rate']
    if found or (b_rate is not None and a_rate is not None and a_rate > b_rate):
        result = 'triggered'
    elif b_rate is None or a_rate is None:
        result = 'unknown'
    else:
        result = 'not triggered'
    return {'schema': COMPARE,
            'before': {'name': before['cohort']['name'], 'size': before['cohort']['size']},
            'after': {'name': after['cohort']['name'], 'size': after['cohort']['size']},
            'rows': rows, 'target': target,
            'rollback': {'result': result, 'before_rate': b_rate, 'after_rate': a_rate, 'safety_escapes': len(found)}}


# --- war-room projection ----------------------------------------------------

def project(b, journey, *, source_path, bench_path, observed_at, evidence):
    """Return the rework and eb6 providers carrying the bench's aggregates.

    rework keeps WR6's own projection of the same journey and gains the
    rounds-per-PR and real-user-path metrics; eb6 gains push timing and defects.
    """
    c, m, ids = b['cohort'], b['measures'], b['identities']
    rework = W.project(journey, source_path=source_path, cohort=c['name'], merged_prs=c['prs'],
                       since=c['since'], until=c['until'], observed_at=observed_at)
    pst = c['since'].endswith('T08:00:00Z') and c['until'].endswith('T08:00:00Z')
    window = {'since': c['since'], 'until': c['until'], 'timezone': 'PST-fixed-UTC-08:00' if pst else 'UTC'}
    source = {'path': bench_path, 'schema': BENCH, 'sha256': sha(dumps(b))}
    gaps = ['Journey v1 historical completeness is unknown; surviving GitHub records cannot prove absent reviews, receipts or defects.']
    gaps += [f'PR {x["pr"]}: {x["why"]}; it stays in the cohort denominator.' for x in c['missing']]

    def metric(identity, group, label, value, unit, statistic, prs, numerator=None, denominator=None,
               expected=None, notes=()):
        names = [f'pr-{n}' if type(n) is int else 'pr-' + n.replace(':', '-').lower() for n in prs]
        return {'id': identity, 'group': group, 'label': label,
                'state': 'partial' if value is not None else 'unavailable', 'value': value,
                'unit': unit, 'native_unit': unit, 'statistic': statistic, 'window': window,
                'observed_at': observed_at, 'fresh_until': None, 'freshness': 'unknown',
                'source': source, 'evidence': list(evidence),
                'sample': {'observed': len(names), 'expected': len(c['prs']) if expected is None else expected,
                           'identities': names, 'numerator': numerator, 'denominator': denominator},
                'dimensions': {'direction': None, 'pool': None, 'stage': None, 'ticket': None, 'cohort': c['name']},
                'interval': None, 'prerequisites': list(gaps) + list(notes)}

    r, u = m['review_rounds'], m['real_user_path']
    basis = ('BEFORE share is a recorded per-finding judgment with its report link, not a User path line.'
             if 'judgment' in u['basis'] else 'Share is read from User path lines.')
    rework['metrics'] += [
        metric('rounds-per-pr', 'board', 'Review rounds per PR (distinct heads), mean over reviewed PRs; unreviewed are Unknown',
               r['total'] / r['n'] if r['n'] else None, 'ratio', 'ratio', ids['review_rounds'],
               r['total'], r['n']),
        metric('rounds-per-pr-median', 'board', 'Review rounds per PR, median over reviewed PRs',
               r['median'], 'count', 'median', ids['review_rounds']),
        metric('rounds-per-pr-p90', 'board', 'Review rounds per PR, p90 over reviewed PRs',
               r['p90'], 'count', 'p90', ids['review_rounds']),
        metric('real-user-path-share', 'board', 'Blocking-grade findings naming a concrete real-user path, of those classified',
               u['user_path'] / u['classified'] if u['share'] is not None else None, 'ratio', 'proportion',
               ids['findings_classified'], *((u['user_path'], u['classified']) if u['share'] is not None else (None, None)),
               expected=u['findings'], notes=(basis,)),
    ]
    rework['prerequisites'] = list(dict.fromkeys(rework['prerequisites'] + gaps + [basis]))
    p, o, d = m['first_push_to_merge_hours'], m['pr_opened_to_merge_hours'], m['escaped_defects']
    immature = 'Escaped defects: immature PRs and unknown follow-up stay out of the rate until the frozen follow-up window has passed.'
    eb6 = [
        metric('first-push-to-merge-hours-median', 'stage_waits', 'First push to merge, hours, median; no receipt is Unknown',
               p['median'], 'hours', 'median', ids['first_push']),
        metric('first-push-to-merge-hours-p90', 'stage_waits', 'First push to merge, hours, p90; no receipt is Unknown',
               p['p90'], 'hours', 'p90', ids['first_push']),
        metric('pr-opened-to-merge-hours-median', 'stage_waits', 'PR opened to merge, hours, median; not push timing',
               o['median'], 'hours', 'median', ids['pr_opened']),
        metric('pr-opened-to-merge-hours-p90', 'stage_waits', 'PR opened to merge, hours, p90; not push timing',
               o['p90'], 'hours', 'p90', ids['pr_opened']),
        metric('escaped-defect-rate', 'stage_waits', 'Mature PRs with an attributable escaped defect, of mature PRs',
               d['affected_mature_prs'] / d['known_mature_prs'] if d['known_mature_prs'] else None, 'ratio',
               'proportion', ids['known_mature'],
               d['affected_mature_prs'], d['known_mature_prs'], notes=(immature,)),
        metric('immature-prs', 'stage_waits', 'Cohort PRs whose defect follow-up has not matured',
               d['immature'], 'count', 'count', ids['immature']),
        metric('unknown-followup-prs', 'stage_waits', 'Cohort PRs with unknown defect follow-up or missing',
               d['unknown_followup'], 'count', 'count', ids['unknown_followup'] + [x['pr'] for x in c['missing']]),
    ]
    eb6_provider = {'slot': 'eb6', 'state': 'partial' if any(x['value'] is not None for x in eb6) else 'unavailable',
                    'prerequisites': list(dict.fromkeys(gaps + [immature])), 'metrics': eb6}
    S.compose(S._time(observed_at).replace(minute=S._time(observed_at).minute // 5 * 5, second=0)
              .strftime('%Y-%m-%dT%H:%M:%SZ'), [rework, eb6_provider], assembled_at=observed_at)
    return [rework, eb6_provider]


# --- command line -----------------------------------------------------------

def _json(path):
    return S._decode(Path(path).read_text(encoding='utf-8'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('bench')
    for name in ('cohort', 'journey', 'outcomes', 'findings'):
        b.add_argument('--' + name, type=Path, required=True)
    b.add_argument('--reports', type=Path)
    b.add_argument('--watchdog', type=Path)
    r = sub.add_parser('check-report')
    r.add_argument('report', type=Path)
    c = sub.add_parser('compare')
    c.add_argument('before', type=Path)
    c.add_argument('after', type=Path)
    c.add_argument('--safety-escapes', type=Path)
    p = sub.add_parser('project')
    p.add_argument('bench', type=Path)
    p.add_argument('--journey', type=Path, required=True)
    p.add_argument('--source-path', required=True)
    p.add_argument('--bench-path', required=True)
    p.add_argument('--observed-at', required=True)
    p.add_argument('--evidence', action='append', required=True)
    p.add_argument('--out', type=Path, required=True)
    a = parser.parse_args(argv)
    try:
        if a.command == 'check-report':
            problems = check_report(a.report.read_text(encoding='utf-8'))
            for problem in problems:
                print(problem, file=sys.stderr)
            if problems:
                return 1
            print('report ok')
        elif a.command == 'bench':
            out = bench(_json(a.cohort), a.journey.read_bytes(), a.outcomes.read_bytes(), _json(a.findings),
                        a.watchdog.read_text(encoding='utf-8') if a.watchdog else None,
                        _json(a.reports) if a.reports else None)
            sys.stdout.write(dumps(out))
        elif a.command == 'compare':
            out = compare(_json(a.before), _json(a.after), _json(a.safety_escapes) if a.safety_escapes else None)
            sys.stdout.write(dumps(out))
        else:
            data = a.bench.read_bytes()
            b = S._decode(data.decode('utf-8'))
            require(dumps(b).encode() == data, 'bench file is not the bench output')
            providers = project(b, a.journey.read_bytes(), source_path=a.source_path, bench_path=a.bench_path,
                                observed_at=a.observed_at, evidence=a.evidence)
            a.out.mkdir(parents=True, exist_ok=True)
            selection = []
            for provider in providers:
                name = f'{provider["slot"]}.json'
                text = dumps(provider)
                (a.out / name).write_text(text, encoding='utf-8')
                selection.append({'kind': 'projected', 'slot': provider['slot'], 'path': name, 'sha256': sha(text),
                                  'observed_at': a.observed_at, 'evidence': list(a.evidence)})
            (a.out / 'selection.json').write_text(dumps(selection), encoding='utf-8')
            print(f'projected {len(providers)} providers into {a.out}')
    except Refused as error:
        print(f'refused: {error}', file=sys.stderr)
        return 1
    except (OSError, ValueError, UnicodeError):
        print('refused: invalid review-loops input', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
