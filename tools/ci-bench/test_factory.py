#!/usr/bin/env python3
"""#1359 factory benches on a synthetic GitHub (fake gh) and hand-worked numbers.

F1 `factory` reads exactly the calls below and writes factory.json; `measure`
turns it into point.json's `factory` record. F2 a day with no merges and no
known main state stays unknown, never 0. F3 untrusted reads are refused.
F4 the dashboard shows the four benches, unknown days included.
Every expected value is worked out by hand in the comments, never the way
bench.py computes it.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SINCE, UNTIL = '2030-01-01T08:00:00Z', '2030-01-02T08:00:00Z'
SHA = 'a' * 40


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


bench = module('bench_for_calls', HERE/'bench.py')
BASE = 'repos/{owner}/{repo}'


def cli(*args, env=None):
    return subprocess.run([sys.executable, '-I', str(HERE/'bench.py'), *map(str, args)],
                          capture_output=True, text=True, env=dict(os.environ, **(env or {})), timeout=60)


def gql_call(cursor=None):
    call = f'api graphql -F owner={{owner}} -F repo={{repo}} -f query={bench.HISTORY_QUERY}'
    return call + (f' -f cursor={cursor}' if cursor else '')


def main_runs_call():
    return (f'api {BASE}/actions/workflows/ci.yml/runs?event=push&branch=main'
            f'&created=2029-12-31T08:00:00Z..{UNTIL}&per_page=100&page=1')


def chunk_calls(since, until):
    """The attempts' run lists: each of the 30 look-back days (GitHub reruns a
    run up to 30 days after it), then the window."""
    start = bench.secs(since) - 30 * 86400
    edges = [bench.utc_text(start + 86400 * i) for i in range(31)] + [until]
    return [f'api {BASE}/actions/workflows/ci.yml/runs?created={a}..{b}&per_page=100&page=1'
            for a, b in zip(edges, edges[1:])]


def quiet_day(since, until):
    """The factory reads of a day with no merges, no push to main and no run,
    for the other suites' fake GitHubs: history, main's runs, run lists."""
    start = bench.utc_text(bench.secs(since) - 86400)
    empty = {'total_count': 0, 'workflow_runs': []}
    out = {gql_call(): page([], False, None),
           f'api {BASE}/actions/workflows/ci.yml/runs?event=push&branch=main&created={start}..{until}&per_page=100&page=1':
           empty}
    out.update({call: empty for call in chunk_calls(since, until)})
    return out


def attempt_call(run, k):
    return f'api {BASE}/actions/runs/{run}/attempts/{k}'


def attempt_jobs_call(run, k):
    return f'api {BASE}/actions/runs/{run}/attempts/{k}/jobs?per_page=100&page=1'


def log_call(job):
    return f'api --allow-escape-sequences {BASE}/actions/jobs/{job}/logs'


def comment(body, at):
    return {'body': body, 'createdAt': at}


def conn(nodes, more=False):
    return {'pageInfo': {'hasNextPage': more}, 'nodes': nodes}


def issue(number, labels=(), comments=(), repo='o/r', more_labels=False, more_comments=False):
    return {'number': number, 'repository': {'nameWithOwner': repo},
            'timelineItems': conn([{'createdAt': at, 'label': {'name': name}} for name, at in labels], more_labels),
            'comments': conn(list(comments), more_comments)}


def pr(number, merged, updated, comments=(), issues=(), more_comments=False):
    return {'number': number, 'mergedAt': merged, 'updatedAt': updated,
            'comments': conn(list(comments), more_comments), 'closingIssuesReferences': conn(list(issues))}


def page(nodes, more, cursor):
    return {'data': {'repository': {'nameWithOwner': 'o/r', 'pullRequests': {
        'pageInfo': {'hasNextPage': more, 'endCursor': cursor}, 'nodes': nodes}}}}


def run(rid, created, conclusion, attempt=1, status='completed', event='push', branch='main', started=None,
        updated=None):
    return {'id': rid, 'event': event, 'head_branch': branch, 'status': status, 'conclusion': conclusion,
            'created_at': created, 'run_attempt': attempt, 'run_started_at': started or created,
            'updated_at': updated or started or created}


def jobs(*rows):
    """(id, conclusion, completed[, created, started, runner, attempt]): a
    job created and started when it completed, on a runner, in attempt 1,
    unless said; runner None means it never got one."""
    out = []
    for row in rows:
        jid, concl, done, created, started, runner, attempt = (tuple(row) + (None, None, 'r', 1)[len(row) - 3:])
        created = created or done
        out.append({'id': jid, 'name': 'job', 'conclusion': concl, 'completed_at': done, 'created_at': created,
                    'started_at': started or created, 'runner_name': runner, 'run_attempt': attempt,
                    'steps': [{'name': 'Set up job'}] if runner else []})
    return {'total_count': len(out), 'jobs': out}


D1, D2 = '2030-01-01T', '2030-01-02T'

# Merged history, newest update first. Page 1:
#   PR 11 merged 10:00. Comments: chatter, then CHANGES 09:00, APPROVE 09:30:
#     two review rounds, first not APPROVE. Ticket 21: needs-info at 05:00,
#     ready-for-agent first at 06:00 (and again at 07:00): ready 4 h before.
#   PR 12 merged 14:00. APPROVE. Ticket 22 never labelled ready; its approval
#     record at 12:00: 2 h. It also closes ticket 21, already counted at its
#     first closing merge (PR 11), in that bucket only.
#   PR 13 merged 20:00. No verdict (unreviewed), no ticket (unlinked).
#   PR 14 merged the day before, updated inside: not in the day, and no stop.
# Page 2 (cursor c1):
#   PR 15 merged 07:00 the next morning, still inside the PST day. APPROVE,
#     but its comments run past one page: its first verdict counts, its
#     rounds don't. Ticket 23 is another repository's (ignored); ticket 24
#     ready-for-agent at 2030-01-01T07:00Z: 24 h.
#   PR 17 merged 22:00. Its comments run past one page without a verdict:
#     review unknown. Ticket 25 has no ready label and no approval: unknown.
#   PR 16 last updated before the day: no later page is read.
# Ready to merged: 4, 2, 24 h; median 4, p90 (nearest rank, 3rd of 3) 24;
#   1 unknown ticket; 1 unlinked PR (13).
# First review: reviewed 11, 12, 15; first APPROVE 12 and 15: 2 of 3 =
#   0.6667; rounds over the 2 complete (11, 12): (2 + 1) / 2 = 1.5;
#   unreviewed 1 (13); unknown 1 (17).
HISTORY = [
    page([pr(11, D1+'10:00:00Z', D1+'12:00:00Z',
             [comment('Green head: x', D1+'08:00:00Z'), comment(f'VERDICT: CHANGES at {SHA}\n\nR1', D1+'09:00:00Z'),
              comment('R1 fixed', D1+'09:10:00Z'), comment(f'VERDICT: APPROVE at {SHA}', D1+'09:30:00Z')],
             [issue(21, [('needs-info', D1+'05:00:00Z'), ('ready-for-agent', D1+'06:00:00Z'),
                         ('ready-for-agent', D1+'07:00:00Z')])]),
          pr(12, D1+'14:00:00Z', D1+'11:59:00Z', [comment(f'VERDICT: APPROVE at {SHA}', D1+'13:00:00Z')],
             [issue(22, [], [comment('Plan note', D1+'11:00:00Z'),
                             comment('**Approved on its own by Robin, 2030-01-01:** "yes"', D1+'12:00:00Z')]),
              issue(21, [('ready-for-agent', D1+'06:00:00Z')])]),
          pr(13, D1+'20:00:00Z', D1+'11:00:00Z'),
          pr(14, '2029-12-31T20:00:00Z', D1+'09:00:00Z', [comment(f'VERDICT: APPROVE at {SHA}', D1+'08:00:00Z')])],
         True, 'c1'),
    page([pr(15, D2+'07:00:00Z', D1+'08:30:00Z', [comment(f'VERDICT: APPROVE at {SHA}', D2+'06:00:00Z')],
             [issue(23, [('ready-for-agent', D1+'06:30:00Z')], repo='other/r'),
              issue(24, [('ready-for-agent', D1+'07:00:00Z')])], more_comments=True),
          pr(17, D1+'22:00:00Z', D1+'08:10:00Z', [comment('chatter', D1+'21:00:00Z')], [issue(25)], more_comments=True),
          pr(16, '2029-12-31T10:00:00Z', '2029-12-31T23:00:00Z')],
         True, 'c2'),
]

# Main's push runs, created from a day before the day. Newest first:
#   306 created next day 07:40, still running: no verdict, no reads.
#   305 created next day 07:00, failed, done 07:50: red 07:50 to 08:00, 10 min.
#   304 created 10:00, attempt 1 failed at 10:30 (main already red), attempt 2
#     passed at 11:30: green from 11:30.
#   303 created 09:10, cancelled: no verdict, no reads.
#   302 created 09:00, failed, done 09:40: red from 09:40.
#   307 created 08:30, failed, done 12:00: older than 304, so main stays green.
#   301 created 07:00 (before the day), passed at 07:30: main is green at the
#     day's start, so the look-back stops here.
#   300 created 05:00: never read.
# Red: 09:40 to 11:30 = 110 min, plus 10 min = 120 min; none unknown.
MAIN = {'total_count': 8, 'workflow_runs': [
    run(300, D1+'05:00:00Z', 'success'), run(306, D2+'07:40:00Z', None, status='in_progress'),
    run(305, D2+'07:00:00Z', 'failure'), run(304, D1+'10:00:00Z', 'success', attempt=2),
    run(303, D1+'09:10:00Z', 'cancelled'), run(302, D1+'09:00:00Z', 'failure'),
    run(307, D1+'08:30:00Z', 'failure'), run(301, D1+'07:00:00Z', 'success')]}

# Every ci.yml run created from 30 days before the day (GitHub reruns a run
# up to 30 days after it), read a day at a time. Look-back runs matter only
# if updated inside the day:
#   501 created Dec 20, 12 days before, attempt 1 cancelled; attempt 2
#     starts 13:00: a rerun of the day (after a cancel). Its jobs: 5011 (Dec
#     20, out of the day); 5012 created 13:00, started 13:30: waits 30; a job
#     carried over from attempt 1 (not attempt 2's): not counted.
#   502 created Dec 31 20:00, one attempt, still running at 08:00: its job
#     5022 created 08:10, started 08:40, waits 30 in the day; 5021 is Dec 31's.
#   503 last updated Dec 31: never read.
# The day's runs (main's 302 to 307 among them), by when they start:
#   307 08:30 (3071, 0), 302 09:00 (3021, 0), 305 next day 07:00 (3051, 0):
#     done, but not in jobs.jsonl (collect ran before they finished): their
#     jobs are read (here already, for main).
#   303 09:10: its one attempt is in jobs.jsonl (3031, waited 2): reused.
#   306 07:40 still running: its job 3061 created 07:40, started 07:45: 5.
#   304 attempt 1 10:00 failed with a failing Rust test (job 3041 waited 2;
#     3042 skipped, no runner); attempt 2 at 11:00 passed (3043, 0): flaky.
#   401 attempt 1 15:00 failed, its log can't resolve github.com (4011
#     waited 5): runner/network; attempt 2 15:20 cancelled (4012 never got a
#     runner); attempt 3 15:40 (4013, 1): after a cancel.
#   402 attempt 1 16:00, log expired (4021 waited 10); attempt 2 16:30
#     (4022, 2): unknown.
#   403 attempt 1 17:00 passed, collected in jobs.jsonl as the run's latest
#     (4031 waited 1): reused; attempt 2 17:30, rerun since (4032, 0): read.
#     After a pass.
#   405 attempt 1 18:00: a failed Rust test (4051, waited 0) and npm's
#     ENOSPC (4052, waited 3); attempt 2 18:30 passed (4053, 5): not every
#     failure is a test, so unknown.
#   404 attempt 1 23:00 (4041 waited 20); attempt 2 starts next day 09:00,
#     after the day: not this day's rerun, and its job (4042) is next day's.
# Reruns 7: flaky 1, runner/network 1, after a pass 1, after a cancel 2 (401,
#   501), unknown 2 (402, 405), out of 18 attempts started in the day: 307,
#   302, 303, 304 x2, 501's 2nd, 401 x3, 402 x2, 403 x2, 405 x2, 404's 1st,
#   305, 306.
# Runner wait, every attempt's own jobs created in the day, once each: 0 x6
#   (3071, 3021, 3043, 4032, 4051, 3051), 1 x2 (4013, 4031), 2 x3 (3031, 3041,
#   4022), 3 (4052), 5 x3 (4011, 4053, 3061), 10, 20, 30 x2 (5012, 5022): 19
#   jobs, median (10th) 2, p90 (18th) 30. jobs.jsonl's own runs (101 to 106,
#   fixture CI runs) are no run of the factory's lists, so they add none.
B = 'pull_request'
LOOKBACK_RUNS = {'total_count': 1, 'workflow_runs': [
    run(501, '2029-12-20T10:00:00Z', 'success', attempt=2, event=B, branch='b', started=D1+'13:00:00Z',
        updated=D1+'13:40:00Z')]}
LOOKBACK_LAST = {'total_count': 2, 'workflow_runs': [
    run(502, '2029-12-31T20:00:00Z', None, status='in_progress', event=B, branch='b', updated=D1+'08:30:00Z'),
    run(503, '2029-12-31T21:00:00Z', 'success', event=B, branch='b', updated='2029-12-31T21:30:00Z')]}
DAY_RUNS = {'total_count': 13, 'workflow_runs': [
    run(306, D2+'07:40:00Z', None, status='in_progress'), run(305, D2+'07:00:00Z', 'failure'),
    run(404, D1+'23:00:00Z', 'success', attempt=2, event=B, branch='b', started=D2+'09:00:00Z'),
    run(405, D1+'18:00:00Z', 'success', attempt=2, event=B, branch='b', started=D1+'18:30:00Z'),
    run(403, D1+'17:00:00Z', 'success', attempt=2, event=B, branch='b', started=D1+'17:30:00Z'),
    run(402, D1+'16:00:00Z', 'failure', attempt=2, event=B, branch='b', started=D1+'16:30:00Z'),
    run(401, D1+'15:00:00Z', 'success', attempt=3, event=B, branch='b', started=D1+'15:40:00Z'),
    run(304, D1+'10:00:00Z', 'success', attempt=2, started=D1+'11:00:00Z', updated=D1+'11:30:00Z'),
    run(303, D1+'09:10:00Z', 'cancelled'), run(302, D1+'09:00:00Z', 'failure'), run(307, D1+'08:30:00Z', 'failure')]}
DAY_RUNS['total_count'] = len(DAY_RUNS['workflow_runs'])


def answers():
    chunks = chunk_calls(SINCE, UNTIL)
    empty = {'total_count': 0, 'workflow_runs': []}
    a = [(gql_call(), HISTORY[0]), (gql_call('c1'), HISTORY[1]), (main_runs_call(), MAIN),
         (attempt_jobs_call(305, 1), jobs((3051, 'failure', D2+'07:50:00Z'))),
         (attempt_call(304, 1), run(304, D1+'10:00:00Z', 'failure')),
         (attempt_jobs_call(304, 1), jobs((3041, 'failure', D1+'10:30:00Z', D1+'10:00:00Z', D1+'10:02:00Z'),
                                          (3042, 'skipped', D1+'10:20:00Z', None, None, None))),
         (attempt_jobs_call(304, 2), jobs((3043, 'success', D1+'11:30:00Z', None, None, 'r', 2))),
         (attempt_jobs_call(302, 1), jobs((3021, 'failure', D1+'09:40:00Z'))),
         (attempt_jobs_call(307, 1), jobs((3071, 'failure', D1+'12:00:00Z'))),
         (attempt_jobs_call(301, 1), jobs((3011, 'success', D1+'07:30:00Z')))]
    a += [(call, empty) for call in chunks[:18]]
    a += [(chunks[18], LOOKBACK_RUNS)]
    a += [(call, empty) for call in chunks[19:29]]
    a += [(chunks[29], LOOKBACK_LAST), (chunks[30], DAY_RUNS)]
    a += [(attempt_call(501, 1), run(501, '2029-12-20T10:00:00Z', 'cancelled', event=B, branch='b')),
          (attempt_jobs_call(501, 1), jobs((5011, 'cancelled', '2029-12-20T10:05:00Z'))),
          (attempt_jobs_call(501, 2), jobs((5012, 'success', D1+'13:50:00Z', D1+'13:00:00Z', D1+'13:30:00Z', 'r', 2),
                                           (5013, 'success', D1+'13:40:00Z', D1+'13:00:00Z', D1+'12:00:00Z', 'r', 1))),
          (attempt_jobs_call(502, 1), jobs((5021, 'success', '2029-12-31T20:30:00Z', '2029-12-31T20:05:00Z',
                                            '2029-12-31T20:06:00Z'),
                                           (5022, None, None, D1+'08:10:00Z', D1+'08:40:00Z'))),
          (log_call(3041), '2030-01-01T10:29:00.0Z test result: FAILED. 41 passed; 1 failed\n'),
          (attempt_call(401, 1), run(401, D1+'15:00:00Z', 'failure', event=B, branch='b')),
          (attempt_call(401, 2), run(401, D1+'15:00:00Z', 'cancelled', attempt=2, event=B, branch='b',
                                     started=D1+'15:20:00Z')),
          (attempt_jobs_call(401, 1), jobs((4011, 'failure', D1+'15:10:00Z', D1+'15:00:00Z', D1+'15:05:00Z'))),
          (log_call(4011), 'x fatal: unable to access: Could not resolve host: github.com\n'),
          (attempt_jobs_call(401, 2), jobs((4012, 'cancelled', D1+'15:21:00Z', D1+'15:20:00Z', None, None, 2))),
          (attempt_call(402, 1), run(402, D1+'16:00:00Z', 'failure', event=B, branch='b')),
          (attempt_jobs_call(402, 1), jobs((4021, 'failure', D1+'16:20:00Z', D1+'16:00:00Z', D1+'16:10:00Z'))),
          (log_call(4021), None),
          (attempt_call(403, 1), run(403, D1+'17:00:00Z', 'success', event=B, branch='b')),
          (attempt_jobs_call(403, 1), jobs((4031, 'success', D1+'17:10:00Z', D1+'17:00:00Z', D1+'17:01:00Z'))),
          (attempt_call(405, 1), run(405, D1+'18:00:00Z', 'failure', event=B, branch='b')),
          (attempt_jobs_call(405, 1), jobs((4051, 'failure', D1+'18:10:00Z', D1+'18:00:00Z', D1+'18:00:00Z'),
                                           (4052, 'failure', D1+'18:10:00Z', D1+'18:00:00Z', D1+'18:03:00Z'))),
          (log_call(4051), 'x test result: FAILED. 9 passed; 1 failed\n'),
          (log_call(4052), 'x npm ERR! code ENOSPC\n'),
          (attempt_call(404, 1), run(404, D1+'23:00:00Z', 'success', event=B, branch='b')),
          (attempt_jobs_call(404, 1), jobs((4041, 'success', D1+'23:40:00Z', D1+'23:00:00Z', D1+'23:20:00Z'))),
          (attempt_jobs_call(306, 1), jobs((3061, None, None, D2+'07:40:00Z', D2+'07:45:00Z'))),
          (attempt_jobs_call(401, 3), jobs((4013, 'success', D1+'15:50:00Z', D1+'15:40:00Z', D1+'15:41:00Z', 'r', 3))),
          (attempt_jobs_call(402, 2), jobs((4022, 'failure', D1+'16:50:00Z', D1+'16:30:00Z', D1+'16:32:00Z', 'r', 2))),
          (attempt_jobs_call(403, 2), jobs((4032, 'success', D1+'17:40:00Z', D1+'17:30:00Z', D1+'17:30:00Z', 'r', 2),
                                           (4031, 'success', D1+'17:10:00Z', D1+'17:00:00Z', D1+'17:01:00Z', 'r', 1))),
          (attempt_jobs_call(405, 2), jobs((4053, 'success', D1+'18:40:00Z', D1+'18:30:00Z', D1+'18:35:00Z', 'r', 2))),
          (attempt_jobs_call(404, 2), jobs((4042, 'success', D2+'09:30:00Z', D2+'09:00:00Z', D2+'09:01:00Z', 'r', 2)))]
    return a


def world(changes=None):
    w = {}
    for call, value in answers():
        w[call] = ({'stdout': '', 'exit': 1} if value is None else
                   {'stdout': value if isinstance(value, str) else json.dumps(value), 'exit': 0})
    for call, value in (changes or {}).items():
        w[call] = value
    return w


FACTORY = {
    'merged_prs': 5,
    'ready_to_merged_hours': {'tickets': 3, 'median': 4.0, 'p90': 24.0, 'unknown_tickets': 1, 'unlinked_prs': 1},
    'first_review': {'reviewed_prs': 3, 'first_approve': 2, 'share': 0.6667, 'rounds_per_pr': 1.5, 'rounds_prs': 2,
                     'unreviewed_prs': 1, 'unknown_prs': 1},
    # Verdicts finished in the day: 302, 304 twice, 307, 305.
    'main_red': {'red_minutes': 120.0, 'unknown_minutes': 0.0, 'untimed_verdicts': 0, 'verdicts': 5},
    'reruns': {'total': 7, 'flaky': 1, 'runner_network': 1, 'after_pass': 1, 'after_cancel': 2, 'unknown': 2,
               'attempts': 18},
    'runner_wait_minutes': {'jobs': 19, 'median': 2.0, 'p90': 30.0},
}


class Fake:
    def __init__(self, tmp, the_world):
        self.root = Path(tmp)
        bindir = self.root/'bin'
        bindir.mkdir()
        shutil.copy(HERE/'fixtures/gh', bindir/'gh')
        (self.root/'world.json').write_text(json.dumps(the_world))
        (self.root/'calls.log').write_text('')
        self.env = {'PATH': str(bindir)+os.pathsep+os.environ['PATH'], 'FAKE_GH_WORLD': str(self.root/'world.json'),
                    'FAKE_GH_LOG': str(self.root/'calls.log')}

    def calls(self):
        return (self.root/'calls.log').read_text().splitlines()


def shifted(text, hours):
    """fixtures/window's jobs moved later by whole hours: same durations."""
    def move(t):
        return None if t is None else bench.utc_text(bench.secs(t) + 3600 * hours)
    rows = []
    for line in text.splitlines():
        job = json.loads(line)
        for k in ('created_at', 'started_at', 'completed_at', 'run_created_at'):
            if k in job:
                job[k] = move(job[k])
        for step in job['steps']:
            step['started_at'], step['completed_at'] = move(step['started_at']), move(step['completed_at'])
        rows.append(json.dumps(job) + '\n')
    return ''.join(rows)


def collected(run_id, event, run_concl, job_id, created, started, done):
    """A jobs.jsonl record as collect writes it now: with the job's id, its
    own attempt and the attempt collected (here, attempt 1)."""
    return json.dumps({'completed_at': done, 'conclusion': 'success', 'created_at': created, 'event': event,
                       'name': 'job', 'run': run_id, 'run_concl': run_concl, 'runner_name': 'r',
                       'started_at': started, 'steps': [{'completed_at': started, 'conclusion': 'success',
                                                         'name': 'Set up job', 'started_at': started}],
                       'id': job_id, 'run_attempt': 1, 'collected_attempt': 1}) + '\n'


def day_dir(root, merged=(11, 12, 13, 15, 17)):
    """A collected PST day: fixtures/window's jobs moved 10 h later (runs
    101 to 106 created 10:00 to 11:40), runs 303 and 403 as collected at
    their first attempt, and its merged PRs."""
    d = Path(root)/'day'
    d.mkdir()
    (d/'window.json').write_text(json.dumps({'since': SINCE, 'until': UNTIL}))
    (d/'jobs.jsonl').write_text(shifted((HERE/'fixtures/window/jobs.jsonl').read_text(), 10)
                                + collected(303, 'push', 'cancelled', 3031, D1+'09:10:00Z', D1+'09:12:00Z', D1+'09:13:00Z')
                                + collected(403, B, 'success', 4031, D1+'17:00:00Z', D1+'17:01:00Z', D1+'17:10:00Z'))
    times = {11: D1+'10:00:00Z', 12: D1+'14:00:00Z', 13: D1+'20:00:00Z', 15: D2+'07:00:00Z', 17: D1+'22:00:00Z'}
    (d/'merged.json').write_text(json.dumps([{'merged_at': times[n], 'number': n} for n in merged]))
    return d


class Collect(unittest.TestCase):
    def test_f1_reads_exactly_these_calls_and_measures_the_four_benches(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Fake(tmp, world())
            d = day_dir(tmp)
            r = cli('factory', '--since', SINCE, '--until', UNTIL, '--out', d, env=fake.env)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            # History, main, the 31 run lists, then run by run (oldest
            # first): 501, 502, then the day's. Every attempt's jobs are read
            # unless already read (for main: 302, 304, 305, 307) or in
            # jobs.jsonl as collected (303's and 403's first); 503 is never read.
            expected = [call for call, _ in answers()][:41]
            expected += [attempt_call(501, 1), attempt_jobs_call(501, 1), attempt_jobs_call(501, 2),
                         attempt_jobs_call(502, 1), log_call(3041),
                         attempt_call(401, 1), attempt_call(401, 2), attempt_jobs_call(401, 1), log_call(4011),
                         attempt_jobs_call(401, 2), attempt_jobs_call(401, 3),
                         attempt_call(402, 1), attempt_jobs_call(402, 1), log_call(4021), attempt_jobs_call(402, 2),
                         attempt_call(403, 1), attempt_jobs_call(403, 2),
                         attempt_call(405, 1), attempt_jobs_call(405, 1), log_call(4051), log_call(4052),
                         attempt_jobs_call(405, 2),
                         attempt_call(404, 1), attempt_jobs_call(404, 1), attempt_jobs_call(404, 2),
                         attempt_jobs_call(306, 1)]
            self.assertEqual(fake.calls(), expected)
            saved = (d/'factory.json').read_text()
            for private in ('VERDICT', 'Approved', 'chatter', 'Could not resolve', 'test result', 'ENOSPC'):
                self.assertNotIn(private, saved)
            r = cli('measure', d, '--robots', '5', '--label', '2030-01-01 PST')
            self.assertEqual(r.returncode, 0, r.stderr)
            point = json.loads((d/'point.json').read_text())
            self.assertEqual(point['factory'], FACTORY)
            self.assertEqual(point['merged_prs'], 5)

    def test_f3_untrusted_reads_are_refused(self):
        bad = {
            'a GraphQL error': {gql_call(): {'stdout': json.dumps({'errors': [{'message': 'x'}], 'data': None}), 'exit': 0}},
            'a repeated cursor': {gql_call('c1'): {'stdout': json.dumps(
                {'data': {'repository': {'nameWithOwner': 'o/r', 'pullRequests': {
                    'pageInfo': {'hasNextPage': True, 'endCursor': 'c1'},
                    'nodes': [pr(18, D1+'09:00:00Z', D1+'09:00:00Z')]}}}}), 'exit': 0}},
            'a PR listed twice': {gql_call('c1'): {'stdout': json.dumps(page(
                [pr(11, D1+'10:00:00Z', D1+'10:00:00Z'), pr(16, '2029-12-31T10:00:00Z', '2029-12-31T23:00:00Z')],
                False, None)), 'exit': 0}},
            'a failed read': {main_runs_call(): {'stdout': '', 'exit': 1}},
            'a job with no completion in a finished attempt': {attempt_jobs_call(302, 1): {'stdout': json.dumps(
                jobs((3021, 'failure', None))), 'exit': 0}},
            'an attempt read as another run': {attempt_call(304, 1): {'stdout': json.dumps(
                run(999, D1+'10:00:00Z', 'failure')), 'exit': 0}},
            'a main run of another branch': {main_runs_call(): {'stdout': json.dumps(
                {'total_count': 1, 'workflow_runs': [run(302, D1+'09:00:00Z', 'failure', branch='other')]}), 'exit': 0}},
        }
        for name, change in bad.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                fake = Fake(tmp, world(change))
                d = day_dir(tmp)
                r = cli('factory', '--since', SINCE, '--until', UNTIL, '--out', d, env=fake.env)
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn('bench: ', r.stderr)
                self.assertFalse((d/'factory.json').exists())

    def test_f3b_measure_refuses_a_history_that_disagrees_with_merged_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Fake(tmp, world())
            d = day_dir(tmp, merged=(11, 12, 13, 15))
            r = cli('factory', '--since', SINCE, '--until', UNTIL, '--out', d, env=fake.env)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = cli('measure', d, '--robots', '5', '--label', '2030-01-01 PST')
            self.assertEqual(r.returncode, 1)
            self.assertIn('merged PRs differ', r.stderr)
            self.assertFalse((d/'point.json').exists())
            facts = json.loads((d/'factory.json').read_text())
            facts['surprise'] = 1
            (d/'factory.json').write_text(json.dumps(facts))
            other = Path(tmp)/'other'
            other.mkdir()
            d2 = day_dir(other)
            shutil.copy(d/'factory.json', d2/'factory.json')
            r = cli('measure', d2, '--robots', '5', '--label', '2030-01-01 PST')
            self.assertEqual(r.returncode, 1)
            self.assertIn('factory.json', r.stderr)

    def test_f3c_bad_command_lines_make_no_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Fake(tmp, {})
            for args in (['--since', UNTIL, '--until', SINCE, '--out', tmp], ['--since', 'x', '--until', UNTIL, '--out', tmp]):
                r = cli('factory', *args, env=fake.env)
                self.assertEqual(r.returncode, 2, r.stderr)
            self.assertEqual(fake.calls(), [])


def empty_factory():
    return {'since': SINCE, 'until': UNTIL, 'prs': [], 'main': {'observations': [], 'carry_in': False, 'untimed': 0},
            'reruns': [], 'attempts': [], 'jobs': []}


class Unknown(unittest.TestCase):
    def test_f2_no_merges_and_no_main_state_stay_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = day_dir(tmp, merged=())
            (d/'jobs.jsonl').write_text('')
            (d/'factory.json').write_text(json.dumps(empty_factory()))
            r = cli('measure', d, '--robots', '5', '--label', '2030-01-01 PST', '--allow-empty')
            self.assertEqual(r.returncode, 0, r.stderr)
            f = json.loads((d/'point.json').read_text())['factory']
            self.assertEqual(f, {
                'merged_prs': 0,
                'ready_to_merged_hours': {'tickets': 0, 'median': None, 'p90': None, 'unknown_tickets': 0,
                                          'unlinked_prs': 0},
                'first_review': {'reviewed_prs': 0, 'first_approve': 0, 'share': None, 'rounds_per_pr': None,
                                 'rounds_prs': 0, 'unreviewed_prs': 0, 'unknown_prs': 0},
                # Nothing known all day: 24 h unknown, red minutes unknown.
                'main_red': {'red_minutes': None, 'unknown_minutes': 1440.0, 'untimed_verdicts': 0, 'verdicts': 0},
                'reruns': {'total': 0, 'flaky': 0, 'runner_network': 0, 'after_pass': 0, 'after_cancel': 0, 'unknown': 0,
                           'attempts': 0},
                'runner_wait_minutes': {'jobs': 0, 'median': None, 'p90': None}})

    def test_f2b_main_known_only_from_its_first_verdict(self):
        # No state at 08:00; a red verdict at 09:00 and a green at 10:30:
        # 60 min unknown, so the red minutes are unknown, not 90.
        with tempfile.TemporaryDirectory() as tmp:
            d = day_dir(tmp, merged=())
            facts = empty_factory()
            facts['main']['observations'] = [
                {'run': 1, 'attempt': 1, 'created_at': D1+'08:30:00Z', 'finished_at': D1+'09:00:00Z', 'verdict': 'red'},
                {'run': 2, 'attempt': 1, 'created_at': D1+'09:30:00Z', 'finished_at': D1+'10:30:00Z', 'verdict': 'green'}]
            (d/'factory.json').write_text(json.dumps(facts))
            r = cli('measure', d, '--robots', '5', '--label', '2030-01-01 PST')
            self.assertEqual(r.returncode, 0, r.stderr)
            red = json.loads((d/'point.json').read_text())['factory']['main_red']
            self.assertEqual(red, {'red_minutes': None, 'unknown_minutes': 60.0, 'untimed_verdicts': 0, 'verdicts': 2})


def pick(f, *paths):
    return {'.'.join(p): (f[p[0]][p[1]] if len(p) == 2 else f[p[0]]) for p in paths}


BUCKET_FIELDS = [('merged_prs',), ('ready_to_merged_hours', 'tickets'), ('ready_to_merged_hours', 'median'),
                 ('first_review', 'reviewed_prs'), ('first_review', 'share'), ('first_review', 'rounds_per_pr'),
                 ('main_red', 'red_minutes'), ('main_red', 'verdicts'), ('reruns', 'total'), ('reruns', 'attempts'),
                 ('runner_wait_minutes', 'jobs'), ('runner_wait_minutes', 'median'), ('first_review', 'rounds_prs')]


class Buckets(unittest.TestCase):
    def test_b1_ci_buckets_of_a_window_with_their_sample_sizes(self):
        # fixtures/window, 00:00 to 02:00, 2 robots. Hour 1: code run 101
        # (robot time 780 s = 13 min: 2 x 60 / 13 = 9.2308 an hour; queued
        # to done 10 min) and PR 7 merged. Hour 2: code run 104 (180 s = 3
        # min: 40 an hour; 1.5 min) and PRs 9 and 12. The 6-hour bucket is
        # clipped to the window's end, so it is the whole window: 2 runs,
        # 15 an hour, median 5.75, 3 merged. No factory.json: no factory.
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)/'w'
            shutil.copytree(HERE/'fixtures/window', w)
            r = cli('measure', w, '--robots', '2', '--label', 'synthetic window')
            self.assertEqual(r.returncode, 0, r.stderr)
            b = json.loads((w/'point.json').read_text())['buckets']
            self.assertEqual(b, {
                '1h': [{'start': '2030-01-01T00:00:00Z', 'end': '2030-01-01T01:00:00Z',
                        'ci': {'code_runs': 1, 'minutes_per_pr': 10.0, 'prs_per_hour': 9.2308, 'merged_prs': 1}},
                       {'start': '2030-01-01T01:00:00Z', 'end': '2030-01-01T02:00:00Z',
                        'ci': {'code_runs': 1, 'minutes_per_pr': 1.5, 'prs_per_hour': 40.0, 'merged_prs': 2}}],
                '6h': [{'start': '2030-01-01T00:00:00Z', 'end': '2030-01-01T02:00:00Z',
                        'ci': {'code_runs': 2, 'minutes_per_pr': 5.75, 'prs_per_hour': 15.0, 'merged_prs': 3}}]})

    def test_b2_factory_buckets_of_a_day(self):
        # The F1 day, 6-hour buckets from 08:00Z (00:00 PST):
        #   08-14: PR 11 merged (ticket 21, 4 h; first verdict CHANGES, 2
        #     rounds); main green from 301, red 09:40 to 11:30 = 110 min, 4
        #     verdicts (302, 304 twice, 307); reruns 304 (11:00) and 501
        #     (13:00) of 6 attempts (307, 302, 303, 304 x2, 501's 2nd); code
        #     runs 101 and 104 (5 robots: 37.5 an hour, median 5.75); waits
        #     0, 0, 0, 2, 2, 30, 30 (3071, 3021, 3043, 3031, 3041, 5012, 5022):
        #     7, median 2, p90 (7th) 30.
        #   14-20: PR 12 (ticket 22, 2 h; ticket 21 stays with PR 11; APPROVE,
        #     1 round); main green, 0 min, 0 verdicts; reruns 401 x2, 402, 403,
        #     405 of 9 attempts; waits 5, 1, 10, 2, 1, 0, 0, 3, 5: 9, median 2.
        #   20-02: PRs 13 (unlinked) and 17 (ticket unknown, review
        #     unknown): no ticket, no review; main 0 min; 404's first attempt;
        #     its job waited 20.
        #   02-08: PR 15 (ticket 24, 24 h; APPROVE, rounds unknown); 305 red at
        #     07:50: 10 min, 1 verdict; attempts 305 and 306; 3051 waited 0
        #     and 3061 5: median 2.5.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Fake(tmp, world())
            d = day_dir(tmp)
            self.assertEqual(cli('factory', '--since', SINCE, '--until', UNTIL, '--out', d, env=fake.env).returncode, 0)
            r = cli('measure', d, '--robots', '5', '--label', '2030-01-01 PST')
            self.assertEqual(r.returncode, 0, r.stderr)
            b = json.loads((d/'point.json').read_text())['buckets']
            self.assertEqual(len(b['1h']), 24)
            self.assertEqual([x['start'][11:16] for x in b['6h']], ['08:00', '14:00', '20:00', '02:00'])
            self.assertEqual(b['6h'][-1]['end'], UNTIL)
            got = [pick(x['factory'], *BUCKET_FIELDS) for x in b['6h']]
            keys = ['.'.join(p) for p in BUCKET_FIELDS]
            want = [dict(zip(keys, v)) for v in [
                (1, 1, 4.0, 1, 0.0, 2.0, 110.0, 4, 2, 6, 7, 2.0, 1),
                (1, 1, 2.0, 1, 1.0, 1.0, 0.0, 0, 5, 9, 9, 2.0, 1),
                (2, 0, None, 0, None, None, 0.0, 0, 0, 1, 1, 20.0, 0),
                (1, 1, 24.0, 1, 1.0, None, 10.0, 1, 0, 2, 2, 2.5, 0)]]
            self.assertEqual(got, want)
            self.assertEqual([x['ci'] for x in b['6h']], [
                {'code_runs': 2, 'minutes_per_pr': 5.75, 'prs_per_hour': 37.5, 'merged_prs': 1},
                {'code_runs': 0, 'minutes_per_pr': None, 'prs_per_hour': None, 'merged_prs': 1},
                {'code_runs': 0, 'minutes_per_pr': None, 'prs_per_hour': None, 'merged_prs': 2},
                {'code_runs': 0, 'minutes_per_pr': None, 'prs_per_hour': None, 'merged_prs': 1}])
            # Hour 10:00-11:00: run 101 (13 robot-min: 23.0769 an hour) and PR
            # 11. Hour 11:00-12:00: run 104 (3 min: 100 an hour); main red
            # until 304's green attempt at 11:30: 30 min, 1 verdict.
            h10, h11 = b['1h'][2], b['1h'][3]
            self.assertEqual(h10['ci'], {'code_runs': 1, 'minutes_per_pr': 10.0, 'prs_per_hour': 23.0769, 'merged_prs': 1})
            self.assertEqual(h11['ci'], {'code_runs': 1, 'minutes_per_pr': 1.5, 'prs_per_hour': 100.0, 'merged_prs': 0})
            self.assertEqual(h11['factory']['main_red'], {'red_minutes': 30.0, 'unknown_minutes': 0.0,
                                                          'untimed_verdicts': 0, 'verdicts': 1})
            # Every bucket's counts add up to the day's.
            day = json.loads((d/'point.json').read_text())['factory']
            for size in ('1h', '6h'):
                self.assertEqual(sum(x['factory']['merged_prs'] for x in b[size]), day['merged_prs'])
                self.assertEqual(sum(x['factory']['reruns']['total'] for x in b[size]), day['reruns']['total'])
                self.assertEqual(sum(x['factory']['reruns']['attempts'] for x in b[size]), 18)
                self.assertEqual(sum(x['factory']['runner_wait_minutes']['jobs'] for x in b[size]), 19)
                # Each ticket counts once, in its first closing merge's bucket.
                self.assertEqual(sum(x['factory']['ready_to_merged_hours']['tickets'] for x in b[size]), 3)
                self.assertEqual(sum(x['factory']['main_red']['red_minutes'] for x in b[size]), 120.0)


class Dashboard(unittest.TestCase):
    def test_f4_dashboard_shows_the_four_benches_and_unknown_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = Fake(tmp, world())
            d = day_dir(tmp)
            self.assertEqual(cli('factory', '--since', SINCE, '--until', UNTIL, '--out', d, env=fake.env).returncode, 0)
            self.assertEqual(cli('measure', d, '--robots', '5', '--label', '2030-01-01 PST').returncode, 0)
            # fixtures/window's jobs predate run creation times: mark the
            # point as a full day's, as collect's records would.
            p = json.loads((d/'point.json').read_text())
            p['latency_basis'] = 'workflow created to last job completed'
            (d/'point.json').write_text(json.dumps(p))
            # The next day was measured before #1359: no factory record.
            old = Path(tmp)/'old'
            shutil.copytree(d, old)
            p = json.loads((old/'point.json').read_text())
            del p['factory'], p['buckets']
            p.update(since=UNTIL, until='2030-01-03T08:00:00Z', label='2030-01-02 PST')
            (old/'point.json').write_text(json.dumps(p))
            out = Path(tmp)/'dash'
            r = cli('dashboard', old, d, '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = (out/'README.md').read_text()
            self.assertIn('## Factory benches', md)
            factory_rows = md.split('## Factory benches', 1)[1].split('\n## ', 1)[0]
            self.assertIn('| 2030-01-01 PST | 5 | 4.00 | 24.00 | 67% (2 of 3) | 1.50 | 120 | 7 (1 flaky, 1 runner/network, 1 after a pass, 2 after a cancel, 2 unknown) | 2.00 | 30.00 |',
                          factory_rows)
            self.assertIn('| 2030-01-02 PST | 5 | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |',
                          factory_rows)
            for name, words in {'factory-throughput.svg': ('Merged PRs per day', 'Hours from ticket ready to merged'),
                                'factory-reviews.svg': ('First-review approvals', 'Review rounds per reviewed merged PR'),
                                'factory-main.svg': ('Minutes main was red', 'CI reruns per day'),
                                'factory-runner-wait.svg': ('Runner wait per job',)}.items():
                svg = (out/name).read_text()
                self.assertIn(f']({name})', md)
                for w in words:
                    self.assertIn(w, svg)
                self.assertIn('>unknown</text>', svg)
                self.assertIn('2030-01-01', svg)
                self.assertNotIn('#11', svg)
            self.assertIn('<title>2030-01-01: 120 min red</title>', (out/'factory-main.svg').read_text())
            # Buckets: every bench, each value with its sample size (BN2).
            self.assertIn('[1-hour and 6-hour buckets](buckets.md)', md)
            page = (out/'buckets.md').read_text()
            six = page.split('## 6-hour buckets', 1)[1].split('## 1-hour buckets', 1)[0]
            # R9: the introduction names the reruns' sample as the cells do.
            intro = page.split('## 6-hour buckets', 1)[0]
            self.assertIn('attempts started in the bucket (reruns)', intro)
            self.assertNotIn('runs (reruns)', intro.replace('attempts started in the bucket (reruns)', ''))
            # Columns: CI min/PR, PRs/hour, merged, ready median and p90,
            # first-review approvals, rounds, main red, reruns, wait median
            # and p90 (B2's buckets; p90s: 08-14 waits' 7th of 7 is 30).
            self.assertIn('| 2030-01-01 00:00–06:00 PST | 5.75 (n=2) | 37.50 (n=2) | 1 | 4.00 (n=1) | 4.00 (n=1) |'
                          ' 0% (n=1) | 2.00 (n=1) | 110 (n=4) | 2 (n=6 attempts) | 2.00 (n=7) | 30.00 (n=7) |', six)
            self.assertIn('| 2030-01-01 12:00–18:00 PST | unknown (n=0) | unknown (n=0) | 2 | unknown (n=0) | unknown (n=0) |'
                          ' unknown (n=0) | unknown (n=0) | 0 (n=0) | 0 (n=1 attempts) | 20.00 (n=1) | 20.00 (n=1) |', six)
            # PR 15's rounds are unknown: n counts only complete histories.
            self.assertIn('| 2030-01-01 18:00–24:00 PST | unknown (n=0) | unknown (n=0) | 1 | 24.00 (n=1) | 24.00 (n=1) |'
                          ' 100% (n=1) | unknown (n=0) | 10 (n=1) | 0 (n=2 attempts) | 2.50 (n=2) | 5.00 (n=2) |', six)
            # The pre-#1359 day has no buckets: every cell unknown.
            self.assertIn('| 2030-01-02 PST | ' + ' | '.join(['unknown'] * 11) + ' |', six)
            one = page.split('## 1-hour buckets', 1)[1]
            self.assertEqual(one.count('| 2030-01-01 '), 24)
            self.assertIn('| 2030-01-01 02:00–03:00 PST | 10.00 (n=1) | 23.08 (n=1) | 1 |', one)
            for name in ('buckets-6h.svg', 'buckets-1h.svg'):
                svg = (out/name).read_text()
                self.assertIn(f']({name})', md + page)
                for w in ('Minutes per PR', 'PRs an hour of capacity', 'Merged PRs', 'Ready to merged, median hours',
                          'Ready to merged, p90 hours', 'First-review approvals', 'Main red', 'CI reruns',
                          'Runner wait, median minutes', 'Runner wait, p90 minutes'):
                    self.assertIn(w, svg)
                self.assertIn('n=', svg)
            self.assertIn('class="thin"', (out/'buckets-6h.svg').read_text())
            # The latest day has no buckets: its hours are unknown, not
            # another day's.
            one_svg = (out/'buckets-1h.svg').read_text()
            self.assertIn('Every bench in 1-hour buckets: 2030-01-02 PST', one_svg)
            self.assertIn('<title>2030-01-02 00:00–01:00 PST: unknown', one_svg)
            self.assertNotIn('<title>2030-01-01 ', one_svg)
            # A day without buckets between two with them breaks the lines.
            later = Path(tmp)/'later'
            shutil.copytree(d, later)
            p = json.loads((later/'point.json').read_text())
            two_days = 2 * 86400
            for rows in p['buckets'].values():
                for row in rows:
                    row['start'] = bench.utc_text(bench.secs(row['start']) + two_days)
                    row['end'] = bench.utc_text(bench.secs(row['end']) + two_days)
            p.update(since='2030-01-03T08:00:00Z', until='2030-01-04T08:00:00Z', label='2030-01-03 PST')
            (later/'point.json').write_text(json.dumps(p))
            out2 = Path(tmp)/'dash2'
            self.assertEqual(cli('dashboard', old, d, later, '--out', out2).returncode, 0)
            six_svg = (out2/'buckets-6h.svg').read_text()
            for hours in ('00:00–06:00', '06:00–12:00', '12:00–18:00', '18:00–24:00'):
                self.assertIn(f'<title>2030-01-02 {hours} PST: unknown', six_svg)
            # Merged PRs are known in every bucketed hour: each panel's
            # line breaks at Jan 2, so no segment spans it.
            merged = six_svg.split('>Merged PRs<', 1)[1].split('>Ready to merged', 1)[0]
            self.assertEqual(merged.count('<polyline'), 2)
            # No thread ids, PR numbers or comment text reach the branch.
            for f in out.iterdir():
                text = f.read_text()
                for private in ('VERDICT: APPROVE at', 'VERDICT: CHANGES at', SHA, 'Approved on its own', 'thr_',
                                'PR 11', '#11', 'Could not resolve', 'chatter'):
                    self.assertNotIn(private, text, f.name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
