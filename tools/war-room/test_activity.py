#!/usr/bin/env python3
"""WR8 raw fake-source -> suite proofs; standard library, no live reads."""
import copy
import importlib.util
import json
import os
import sys

sys.dont_write_bytecode = True
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


A = module('activity', HERE / 'activity.py')
S = module('suite', HERE / 'suite.py')
B, M = A.B, A.M
AT = '2030-01-02T12:30:00Z'
REPO = 'synthetic-owner/work'
ROOT = 'repos/' + REPO
RUNS = ROOT + '/actions/workflows/ci.yml/runs?per_page=100&page=1'
JOBS = ROOT + '/actions/runs/71/jobs?per_page=100&page=1'
RUN = ROOT + '/actions/runs/71'
POOLS = ('ubuntu-24.04', 'ubuntu-slim')


def conn(nodes, more=False, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}


def ticket(number, title='Feature', milestone='0.0.9', labels=()):
    return {'number': number, 'title': title,
            'milestone': None if milestone is None else {'title': milestone},
            'labels': conn([{'name': name} for name in labels])}


def job(number, status, labels, **extra):
    return {'id': number, 'run_id': 71, 'run_attempt': 1, 'status': status,
            'labels': labels, 'runner_name': None, 'steps': [],
            'created_at': '2030-01-02T11:00:00Z', 'started_at': None,
            'completed_at': None, **extra}


def fixture():
    run = {'id': 71, 'run_attempt': 1, 'status': 'in_progress', 'conclusion': None,
           'created_at': '2030-01-02T10:00:00Z'}
    prs = []
    for n, merged, links in [(81, '12:05', [91, 92]), (82, '12:10', [93]),
                              (83, '11:10', [94])]:
        prs.append({'number': n, 'mergedAt': '2030-01-02T' + merged + ':00Z',
                    'closedAt': '2030-01-02T' + merged + ':00Z',
                    'closingIssuesReferences': conn([
                        {'number': t, 'repository': {'nameWithOwner': REPO}} for t in links])})
    answers = {RUNS: {'total_count': 1, 'workflow_runs': [run]}, RUN: run,
               JOBS: {'total_count': 3, 'jobs': [
                   job(101, 'in_progress', ['ubuntu-24.04']),
                   job(102, 'queued', ['ubuntu-24.04']),
                   job(103, 'queued', ['ubuntu-slim'])]},
               'graph:prs:': {'data': {'repository': {'pullRequests': conn(prs)}}}}
    for t in [ticket(91), ticket(92), ticket(93, title='Proposal: harden'),
              ticket(94, milestone=None)]:
        answers['graph:' + str(t['number']) + ':'] = {'data': {'repository': {'issue': t}}}
    return answers


class ActivityTests(unittest.TestCase):
    def project(self, data=None, **overrides):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / 'gh').symlink_to(HERE / 'fixtures/activity/fake_gh.py')
            path = tmp / 'source.json'
            path.write_text(json.dumps(fixture() if data is None else data))
            with patch.dict(os.environ, {'PATH': str(tmp) + os.pathsep + os.environ['PATH'],
                                         'WR8_FIXTURE': str(path)}):
                args = dict(repo=REPO, read_started_at='2030-01-02T12:29:00Z',
                            source_path='fixtures/activity/observation.json',
                            ci_read=B.gh, pr_read=M.collect_prs,
                            ticket_read=M.graphql, pools=POOLS)
                args.update(overrides)
                at = args.pop('at', AT)
                provider, wire = A.project(at, **args)
                self.wire = wire
                captured = tmp / args['source_path']
                captured.parent.mkdir(parents=True, exist_ok=True)
                captured.write_bytes(wire)
                import hashlib
                for metric in provider['metrics']:
                    self.assertEqual(metric['source']['sha256'], hashlib.sha256(captured.read_bytes()).hexdigest())
        record = S.compose(at, [provider])
        S.validate(record)
        return {m['id']: m for m in record['providers'][0]['metrics']}

    def test_complete_sources_counts_and_current_metadata(self):
        metrics = self.project()
        for key, value in {'ci-running-ubuntu-24.04': 1, 'ci-queued-ubuntu-24.04': 1,
                           'ci-running-ubuntu-slim': 0, 'ci-queued-ubuntu-slim': 1,
                           'merged-hour-forward': 1, 'merged-hour-backwards': 1,
                           'merged-hour-sideways': 0, 'merged-day-sideways': 1}.items():
            with self.subTest(key=key):
                self.assertEqual((metrics[key]['state'], metrics[key]['value']), ('known', value))
                self.assertEqual(metrics[key]['observed_at'], AT)
                self.assertEqual(metrics[key]['freshness'], 'unknown')
                self.assertEqual(len(metrics[key]['source']['sha256']), 64)
        self.assertIn('current ticket metadata', metrics['merged-day-forward']['label'])
        self.assertEqual(metrics['merged-hour-forward']['sample']['identities'], ['pr-81'])
        self.assertEqual(metrics['merged-hour-forward']['window']['since'], '2030-01-02T12:00:00Z')
        self.assertEqual(metrics['merged-day-forward']['window']['since'], '2030-01-02T00:00:00Z')

    def test_selected_pools_preserve_recognized_source_coverage(self):
        # R1: selection filters metrics, not the complete source classification.
        # The all-pools proof misses this bug because every known pool is selected.
        cases = [
            ('ubuntu-24.04', ['ubuntu-slim'], 'known', (1, 1)),
            ('ubuntu-slim', ['ubuntu-slim'], 'known', (0, 1)),
            ('ubuntu-24.04', None, 'partial', (None, None)),
            ('ubuntu-24.04', ['synthetic-unclassified'], 'partial', (None, None)),
            ('ubuntu-24.04', list(POOLS), 'partial', (None, None)),
        ]
        for selected, source_labels, state, expected in cases:
            with self.subTest(selected=selected, source_labels=source_labels):
                data = fixture()
                data[JOBS]['jobs'][2]['labels'] = source_labels
                metrics = self.project(data, pools=(selected,))
                for status, value in zip(('running', 'queued'), expected):
                    metric = metrics[f'ci-{status}-{selected}']
                    self.assertEqual((metric['state'], metric['value']), (state, value))
                    self.assertEqual(metric['dimensions']['pool'], selected)
                    if state == 'known':
                        self.assertEqual(metric['prerequisites'], [])
                    else:
                        self.assertTrue(metric['prerequisites'])
                omitted = 'ubuntu-slim' if selected == 'ubuntu-24.04' else 'ubuntu-24.04'
                self.assertNotIn(f'ci-running-{omitted}', metrics)
                self.assertNotIn(f'ci-queued-{omitted}', metrics)

    def test_ci_gaps_cannot_invent_complete_counts(self):
        for case in ('partial', 'duplicate-run', 'duplicate-job', 'attempt', 'job-attempt',
                     'status', 'missing-labels', 'conflicting-labels', 'unknown-label'):
            data = fixture()
            if case == 'partial':
                data[JOBS]['total_count'] = 4
                data[JOBS.replace('&page=1', '&page=2')] = {'total_count': 4, 'jobs': []}
            elif case == 'duplicate-run':
                data[RUNS]['workflow_runs'] *= 2
                data[RUNS]['total_count'] = 2
            elif case == 'duplicate-job':
                data[JOBS]['jobs'][1] = copy.deepcopy(data[JOBS]['jobs'][0])
            elif case == 'attempt':
                data[RUN] = {**data[RUN], 'run_attempt': 2}
            elif case == 'job-attempt':
                data[JOBS]['jobs'][1]['run_attempt'] = 2
            elif case == 'status':
                data[JOBS]['jobs'][1]['status'] = 'waiting'
            elif case == 'missing-labels':
                del data[JOBS]['jobs'][1]['labels']
            elif case == 'conflicting-labels':
                data[JOBS]['jobs'][1]['labels'] = list(POOLS)
            else:
                data[JOBS]['jobs'][1]['labels'] = ['Linux', 'X64', 'unknown-pool']
            with self.subTest(case=case):
                metrics = self.project(data)
                for key in ('ci-running-ubuntu-24.04', 'ci-queued-ubuntu-24.04'):
                    self.assertIsNone(metrics[key]['value'])
                    self.assertNotEqual(metrics[key]['state'], 'known')
                    self.assertTrue(metrics[key]['prerequisites'])
                self.assertEqual(metrics['merged-hour-forward']['value'], 1)

    def test_paginated_jobs_and_closing_metadata(self):
        data = fixture()
        data[JOBS]['jobs'], tail = data[JOBS]['jobs'][:1], data[JOBS]['jobs'][1:]
        data[JOBS.replace('&page=1', '&page=2')] = {'total_count': 3, 'jobs': tail}
        issue = data['graph:91:']['data']['repository']['issue']
        issue['labels'] = conn([{'name': 'feature-first'}], True, 'next-labels')
        data['graph:91:next-labels'] = {'data': {'repository': {'issue': {
            **issue, 'labels': conn([{'name': 'feature'}])}}}}
        metrics = self.project(data)
        self.assertEqual(metrics['ci-queued-ubuntu-slim']['value'], 1)
        self.assertEqual(metrics['merged-hour-forward']['value'], 1)

    def test_direction_unknowns_and_duplicates(self):
        for case in ('ambiguous', 'unlinked', 'missing', 'partial-labels', 'duplicate-pr', 'duplicate-link'):
            data = fixture()
            if case == 'ambiguous':
                data['graph:92:']['data']['repository']['issue']['milestone'] = None
            elif case == 'unlinked':
                data['graph:prs:']['data']['repository']['pullRequests']['nodes'][0]['closingIssuesReferences'] = conn([])
            elif case == 'missing':
                data['graph:91:']['data']['repository']['issue'] = None
            elif case == 'partial-labels':
                data['graph:91:']['data']['repository']['issue']['labels'] = conn([], True, 'unread')
            elif case == 'duplicate-pr':
                data['graph:prs:']['data']['repository']['pullRequests']['nodes'] *= 2
            else:
                links = data['graph:prs:']['data']['repository']['pullRequests']['nodes'][0]['closingIssuesReferences']['nodes']
                links.append(copy.deepcopy(links[0]))
            with self.subTest(case=case):
                metrics = self.project(data)
                self.assertIsNone(metrics['merged-hour-forward']['value'])
                self.assertNotEqual(metrics['merged-hour-forward']['state'], 'known')
                self.assertEqual(metrics['ci-running-ubuntu-24.04']['value'], 1)

    def test_cost_estimate_preserves_scope_prices_and_rounding(self):
        data = fixture()
        data[RUNS]['workflow_runs'][0] = {**data[RUN], 'status': 'completed', 'conclusion': 'success'}
        data[RUN] = data[RUNS]['workflow_runs'][0]
        data[JOBS] = {'total_count': 1, 'jobs': [job(104, 'completed', ['ubuntu-slim'],
            runner_name='synthetic-runner', started_at='2030-01-02T11:00:00Z',
            completed_at='2030-01-02T11:01:01Z')]}
        metrics = self.project(data)
        cost = metrics['ci-cost-today-estimate']
        self.assertEqual(cost['value'], 0.004)
        self.assertEqual(cost['state'], 'partial')
        self.assertIn('latest completed', cost['label'])
        self.assertTrue(any('2026-' in p for p in cost['prerequisites']))
        self.assertIsNone(metrics['ci-cost-today-billing']['value'])
        data[JOBS]['jobs'][0]['labels'].append('unsupported-synthetic-selector')
        metrics = self.project(data)
        self.assertIsNone(metrics['ci-cost-today-estimate']['value'])


    def test_ci_reader_is_bound_to_selected_repository(self):
        other = 'synthetic-second/work'
        data = {key.replace(ROOT, 'repos/' + other): value for key, value in fixture().items()}
        metrics = self.project(data, repo=other)
        self.assertEqual(metrics['ci-running-ubuntu-24.04']['value'], 1)

    def test_source_bundle_drops_untrusted_labels(self):
        data = fixture()
        data[JOBS]['jobs'][1]['labels'].append('sensitive-synthetic-label')
        self.project(data)
        self.assertNotIn(b'sensitive-synthetic-label', self.wire)

    def test_calendar_boundary_remains_valid_without_an_elapsed_window(self):
        metrics = self.project(at='2030-01-02T00:00:00Z',
                               read_started_at='2030-01-01T23:59:00Z')
        self.assertEqual(metrics['merged-hour-forward']['state'], 'unavailable')
        self.assertIsNone(metrics['merged-hour-forward']['window'])

    def test_completed_job_in_active_run_is_not_in_completed_run_cost_cohort(self):
        data = fixture()
        data[JOBS]['jobs'][0] = job(104, 'completed', ['ubuntu-slim'],
            runner_name='synthetic-runner', started_at='2030-01-02T11:00:00Z',
            completed_at='2030-01-02T11:01:01Z')
        metrics = self.project(data)
        self.assertEqual(metrics['ci-cost-today-estimate']['sample']['identities'], [])

    def test_missing_milestone_title_is_not_sideways(self):
        data = fixture()
        data['graph:94:']['data']['repository']['issue']['milestone'] = {}
        metrics = self.project(data)
        self.assertIsNone(metrics['merged-day-sideways']['value'])

    def test_unread_old_ticket_metadata_does_not_hide_today(self):
        data = fixture()
        pr = copy.deepcopy(data['graph:prs:']['data']['repository']['pullRequests']['nodes'][0])
        pr.update(number=80, mergedAt='2030-01-01T12:00:00Z')
        pr['closingIssuesReferences'] = conn([{'number': 90, 'repository': {'nameWithOwner': REPO}}])
        data['graph:prs:']['data']['repository']['pullRequests']['nodes'].append(pr)
        metrics = self.project(data)
        self.assertEqual(metrics['merged-hour-forward']['value'], 1)

    def test_unselected_pool_capability_stays_visible(self):
        metrics = self.project(pools=())
        self.assertEqual(metrics['ci-pools']['state'], 'unavailable')
        self.assertTrue(metrics['ci-pools']['prerequisites'])

    def test_unconfigured_sources_are_explicitly_grey(self):
        metrics = self.project(ci_read=None, pr_read=None, ticket_read=None)
        self.assertTrue(metrics)
        self.assertTrue(all(m['state'] == 'unavailable' and m['value'] is None for m in metrics.values()))


if __name__ == '__main__':
    unittest.main()
