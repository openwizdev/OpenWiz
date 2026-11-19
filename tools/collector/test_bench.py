#!/usr/bin/env python3
"""FF1 (#1331): the before bench, on one synthetic cohort worked by hand.

The bench's reads are replaced by synthetic answers in the collector's own
shapes (the merges and flow facts, the CI3 fact with its window file, and
record-author comments). Every expected number below is worked by hand from
those answers, never by the bench's own code. Each test names the bug it
catches.
"""
import io
import itertools
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bench  # noqa: E402

REPO = 'synthetic-owner/synthetic-repo'
SINCE, UNTIL = '2026-01-10T00:00:00Z', '2026-01-11T00:00:00Z'
A, B, C = 'a' * 40, 'b' * 40, 'c' * 40
IDS = itertools.count(1)


def t(hhmm):
    return f'2026-01-10T{hhmm}:00Z'


def run(job, start, end, status='completed'):
    return {'id': next(IDS), 'event': 'pull_request', 'created_at': start, 'updated_at': end or start,
            'status': status, 'conclusion': 'success' if status == 'completed' else None,
            'attempts': [{'attempt': 1, 'jobs': [{
                'id': next(IDS), 'name': job, 'conclusion': 'success' if end else None,
                'created_at': start, 'started_at': start, 'completed_at': end, 'runner_name': 'synthetic-runner',
                'steps': [], 'run_attempt': 1}]}]}


def head(pr, sha, start, ci, privacy, status='completed'):
    return {'pr': pr, 'sha': sha, 'pushed_at': start, 'start': start, 'fork': False,
            'runs': {'ci.yml': run('ci', *ci, status), 'privacy.yml': run('privacy', *privacy)}}


def comment(at, body):
    return {'at': at, 'body': body}


class Reads:
    """Synthetic answers. Ticket 11 is read whole; ticket 12's PR comments can't be read; the flow
    fact couldn't read ticket 13 at all; PR 24 merged into another base and is outside the cohort."""

    def __init__(self, ci3_state='partial'):
        self.asked, self.ci3_state = [], ci3_state

    def merges(self, since, until):
        self.asked.append(('merges', since, until))
        prs = [(21, '06:00', 'main', [11]), (22, '05:00', 'main', [12]), (23, '07:00', 'main', [13]),
               (24, '08:00', 'release-1', [14])]
        return {'state': 'known', 'value': {'pull_requests': [
            {'number': n, 'merged_at': t(at), 'base': base, 'tickets': ts, 'direction': 'forward'}
            for n, at, base, ts in prs]}}

    def flow(self, tickets, since, until):
        self.asked.append(('flow', tuple(tickets)))
        rows = [{'ticket': 11, 'pull_requests': [21], 'state': 'merged', 'claimed_at': t('00:00'),
                 'merged_at': t('06:00'), 'review_rounds': 2},
                {'ticket': 12, 'pull_requests': [22], 'state': 'merged', 'claimed_at': t('01:00'),
                 'merged_at': t('05:00'), 'review_rounds': 1},
                {'ticket': 13, 'pull_requests': [], 'state': 'unknown', 'claimed_at': None,
                 'merged_at': None, 'review_rounds': None}]
        return {'state': 'partial', 'prerequisites': ['Some GitHub timing or review records were unavailable.'],
                'value': {'tickets': [r for r in rows if r['ticket'] in tickets], 'specs': []}}

    def ci3(self, since, until):
        self.asked.append(('ci3', since, until))
        if self.ci3_state == 'unavailable':
            return {'state': 'unavailable', 'value': None, 'prerequisites': ['CI3 unavailable.']}, None
        window = {'heads': [head(21, A, t('01:00'), (t('01:05'), t('01:20')), (t('01:02'), t('01:12'))),
                            head(21, B, t('03:00'), (t('03:10'), t('03:50')), (t('03:02'), t('03:07'))),
                            head(22, C, t('02:00'), (t('02:05'), None), (t('02:01'), t('02:04')), 'in_progress')]}
        record = {'result': {'p50_minutes': 20.0, 'p95_minutes': 50.0, 'timed': 2}, 'missing': [
            {'pr': 22, 'head': C, 'reason': 'ci: unfinished'}]}
        return {'state': 'partial', 'value': record, 'prerequisites': ['1 PR heads have no result yet.']}, window

    def comments(self, kind, n):
        self.asked.append(('comments', kind, n))
        if (kind, n) == ('pullRequest', 22):
            raise bench.Unreadable('synthetic: the comment pages could not be read')
        return {('issue', 11): [comment(t('00:00'), 'launch-fleet: starting'),
                                comment(t('06:20'), 'launch-fleet: archived')],
                ('issue', 12): [comment(t('01:00'), 'launch-fleet: starting')],
                ('pullRequest', 21): [
                    comment(t('01:30'), f'launch-fleet: review started {A}'),
                    comment(t('02:00'), f'VERDICT: CHANGES at {A}\nFull review by the other family.'),
                    comment(t('02:10'), f'launch-fleet: builder told {A}'),
                    comment(t('03:40'), f'launch-fleet: re-check sent {B}'),
                    comment(t('04:00'), f'VERDICT: APPROVE at {B}\nRe-check of R1.'),
                    comment(t('04:30'), f'launch-fleet: merge queued {B}: VERDICT: APPROVE at {B}')]}[kind, n]


class Measures(unittest.TestCase):
    def test_a_read_whole_ticket_splits_its_hours_and_waits_exactly(self):
        # catches: a stage put in the wrong bucket (rework counted as builder, the queue dropped), CI
        # still counted after the review began, the split not adding up to claim-to-merge, a wait
        # measured to the wrong next action, and CI minutes per head summed or maxed over the wrong jobs.
        doc = bench.measure(bench.gather(REPO, SINCE, UNTIL, Reads()))
        row = next(r for r in doc['tickets'] if r['ticket'] == 11)
        # 00:00 claim, 01:00 head A, 01:20 its CI, 01:30 review, 02:00 CHANGES; 03:00 head B, review at
        # 03:40 before its CI ended at 03:50, 04:00 APPROVE, 04:30 queued, 06:00 merged.
        self.assertEqual(row['hours'], {'builder': 1.0, 'ci': 2.5, 'wake': 0.67, 'review': 0.83, 'rework': 1.0,
                                        'total': 6.0})
        self.assertEqual(row['review_rounds'], 2)
        self.assertEqual(row['waits_minutes'], {'ci_finished': [10.0, 40.0], 'review_posted': [10.0, 30.0],
                                                'merge': [20.0]})
        heads = {h['head']: h for h in doc['heads']}
        self.assertEqual((heads[A]['slowest_job_minutes'], heads[A]['runner_minutes']), (15.0, 25.0))
        self.assertEqual((heads[B]['slowest_job_minutes'], heads[B]['runner_minutes']), (40.0, 45.0))
        self.assertEqual(doc['ci']['time_to_result'], {'p50_minutes': 20.0, 'p95_minutes': 50.0, 'timed': 2})

    def test_an_unreadable_ticket_or_head_is_unknown_never_zero(self):
        # catches: an unread ticket, an unfinished head or a missing CI3 read entering the numbers as 0,
        # which would pull every median down and make the before numbers look faster than they were.
        doc = bench.measure(bench.gather(REPO, SINCE, UNTIL, Reads()))
        rows = {r['ticket']: r for r in doc['tickets']}
        self.assertEqual(sorted(rows), [11, 12, 13])  # PR 24's ticket merged into another base
        for n in (12, 13):
            self.assertIsNone(rows[n]['hours'])
            self.assertIsNone(rows[n]['waits_minutes'])
            self.assertTrue(rows[n]['unknown'])
        self.assertEqual(rows[12]['review_rounds'], 1)  # the flow fact read it; only the comments failed
        self.assertIsNone(rows[13]['review_rounds'])
        s = doc['summary']
        self.assertEqual(s['hours']['builder'], {'known': 1, 'unknown': 2, 'p50': 1.0, 'p75': 1.0, 'max': 1.0,
                                                 'sum': 1.0})
        self.assertEqual(s['review_rounds'], {'known': 2, 'unknown': 1, 'p50': 1, 'p75': 2, 'max': 2, 'sum': 3})
        self.assertEqual(s['ci_per_head']['slowest_job_minutes'],
                         {'known': 2, 'unknown': 1, 'p50': 15.0, 'p75': 40.0, 'max': 40.0, 'sum': 55.0})
        self.assertEqual(s['waits_minutes']['merge'], {'known': 1, 'unknown': 2, 'p50': 20.0, 'p75': 20.0,
                                                       'max': 20.0, 'sum': 20.0})
        blind = bench.measure(bench.gather(REPO, SINCE, UNTIL, Reads(ci3_state='unavailable')))
        self.assertEqual(blind['heads'], [])
        self.assertIsNone(blind['ci']['time_to_result'])
        self.assertEqual(blind['summary']['ci_per_head']['runner_minutes']['known'], 0)
        self.assertIsNone(blind['summary']['ci_per_head']['runner_minutes']['p50'])
        self.assertIsNone(next(r for r in blind['tickets'] if r['ticket'] == 11)['hours'])


class Command(unittest.TestCase):
    def test_it_prints_and_saves_the_measures_with_the_window_and_rules(self):
        # catches: a bench that prints numbers it doesn't save, or saves them without the window and
        # the rules that make a later after-run comparable; and the CI read starting after the
        # cohort's earliest claim, which would drop its first heads.
        with tempfile.TemporaryDirectory() as tmp:
            out, reads = Path(tmp) / 'before.json', Reads()
            with redirect_stdout(io.StringIO()) as printed:
                code = bench.main(['--repo', REPO, '--since', SINCE, '--until', UNTIL, '--label', 'BEFORE',
                                   '--out', str(out)], reads=reads)
            self.assertEqual(code, 0)
            saved = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(saved['schema'], bench.SCHEMA)
        self.assertEqual((saved.get('label'), saved.get('window')), ('BEFORE', {'since': SINCE, 'until': UNTIL,
                                                                        'timezone': 'UTC'}))
        self.assertEqual(saved['ci']['window'], {'since': t('00:00'), 'until': UNTIL, 'timezone': 'UTC'})
        self.assertEqual(saved['rules'], list(bench.RULES))
        text = printed.getvalue()
        for needle in (SINCE, UNTIL, 'unknown', 'builder', 'review rounds', 'slowest job'):
            self.assertIn(needle, text)
        self.assertIn(('ci3', t('00:00'), UNTIL), reads.asked)

    def test_a_bad_command_line_exits_2_before_any_read(self):
        # catches: a half window or an unsettled one still spending GitHub reads.
        for args in (['--repo', REPO, '--since', SINCE, '--out', 'x.json'],
                     ['--repo', REPO, '--since', UNTIL, '--until', SINCE, '--out', 'x.json'],
                     ['--repo', 'not a repository', '--since', SINCE, '--until', UNTIL, '--out', 'x.json'],
                     ['--repo', REPO, '--since', SINCE, '--until', '2999-01-01T00:00:00Z', '--out', 'x.json']):
            reads = Reads()
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as exit_:
                bench.main(args, reads=reads)
            self.assertEqual((exit_.exception.code, reads.asked), (2, []), args)


if __name__ == '__main__':
    unittest.main()
