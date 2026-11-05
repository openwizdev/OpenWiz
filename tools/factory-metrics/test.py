#!/usr/bin/env python3
"""Public CLI proofs for #566. All records and identifiers are synthetic.

2030-01-02: 3 merges (01:15, 02:20, 04:30), 0.125/day-hour.
Gaps: carry-in 00:00-00:10=10; findings on PR31 -> ticket12 record
00:30-01:15=45; CI failure 02:00-02:20=20; merge blocked
03:00-04:30=90; review started 23:50-midnight=10. Total 175.
Hourly idle: 00h 40, 01h 15, 02h 20, 03h 60, 04h 30, 23h 10.
Biggest: ticket14, 90 min. Ordinary comments and unrelated records do not
end gaps. PR31 closes 12 and 15: count its start only once.
Usage: Claude 3000 tokens/6 credits/$3; GPT 6000 tokens/9 credits/$6;
sandbox 6h/$3; hosted Actions 12 min/$0.60 => total $12.60, $4.20/merge.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
SCRIPT = Path(os.environ.get('FACTORY_METRICS_PY', HERE / 'metrics.py')).resolve()
REPO = 'example/factory'
DAY = '2030-01-02'
BASE = 'repos/example/factory'
# Literal, independently specified query contract; only this read is accepted.
QUERY = '''query($owner:String!,$name:String!,$cursor:String){repository(owner:$owner,name:$name){pullRequests(first:100,after:$cursor){nodes{number mergedAt closedAt closingIssuesReferences(first:100){nodes{number repository{nameWithOwner}} pageInfo{hasNextPage endCursor}}} pageInfo{hasNextPage endCursor}}}}'''
LINK_QUERY = '''query($owner:String!,$name:String!,$number:Int!,$cursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){closingIssuesReferences(first:100,after:$cursor){nodes{number repository{nameWithOwner}} pageInfo{hasNextPage endCursor}}}}}'''


def graph_args(cursor=None, number=None):
    args = ['api', 'graphql', '-f', 'query=' + (QUERY if number is None else LINK_QUERY),
            '-f', 'owner=example', '-f', 'name=factory']
    if number is not None:
        args += ['-F', f'number={number}']
    if cursor is not None:
        args += ['-f', 'cursor=' + cursor]
    return args


def rest(path):
    return ['api', '--method', 'GET', path]


def answer(value):
    return {'stdout': json.dumps(value), 'exit': 0}


def connection(nodes, more=False, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}


def pr(n, merged, tickets, closed=None):
    return {'number': n, 'mergedAt': merged, 'closedAt': closed or merged, 'closingIssuesReferences': connection(
        [{'number': t, 'repository': {'nameWithOwner': REPO}} for t in tickets])}


def comment(cid, n, time, body, created=None):
    return {'id': cid, 'issue_url': f'https://api.github.com/repos/{REPO}/issues/{n}',
            'created_at': created or time, 'updated_at': time, 'body': body}


def world():
    prs = [pr(31, '2030-01-02T01:15:00Z', [12, 15]), pr(32, '2030-01-02T02:20:00Z', [13]),
           pr(33, '2030-01-02T04:30:00Z', [14]), pr(34, '2030-01-03T00:00:00Z', []),
           pr(35, None, [])]
    records = [comment(1, 12, '2030-01-01T23:50:00Z', 'launch-fleet: findings sent abc'),
               comment(2, 31, '2030-01-02T00:10:00Z', 'launch-fleet: re-check sent abc'),
               comment(3, 31, '2030-01-02T00:30:00Z', 'launch-fleet: findings sent abc'),
               comment(4, 31, '2030-01-02T00:40:00Z', 'VERDICT: APPROVE'),
               comment(5, 99, '2030-01-02T00:45:00Z', 'launch-fleet: started'),
               comment(6, 12, '2030-01-02T01:15:00Z', 'launch-fleet: re-check sent abc'),
               comment(7, 32, '2030-01-02T02:00:00Z', 'launch-fleet: CI failure sent abc'),
               comment(8, 32, '2030-01-02T02:20:00Z', 'launch-fleet: findings sent abc'),
               comment(9, 13, '2030-01-02T02:20:00Z', 'launch-fleet: archived'),
               comment(10, 33, '2030-01-02T03:00:00Z', 'launch-fleet: merge blocked abc: conflict'),
               comment(11, 14, '2030-01-02T04:30:00Z', 'launch-fleet: merged abc'),
               comment(12, 35, '2030-01-02T23:50:00Z', 'launch-fleet: review started abc, thread synthetic',
                       '2030-01-02T23:45:00Z'),
               comment(13, 35, '2030-01-03T00:10:00Z', 'launch-fleet: review told again abc')]
    # An old creation edited later is sorted at its effective timestamp.
    records.reverse()
    billing = {'timePeriod': {'year': 2030, 'month': 1, 'day': 2}, 'user': 'example',
               'usageItems': [{'product': 'Actions', 'sku': 'actions_linux', 'unitType': 'minutes',
                               'grossQuantity': 12, 'netAmount': 0.6}]}
    return {json.dumps(graph_args()): answer({'data': {'repository': {'pullRequests': connection(prs)}}}),
            json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1')): answer(records),
            json.dumps(rest(BASE)): answer({'owner': {'type': 'User'}}),
            json.dumps(rest('users/example/settings/billing/usage/summary?year=2030&month=1&day=2&repository=example%2Ffactory&product=Actions')): answer(billing)}


def usage():
    def row(key, tokens, credits, usd):
        return {'thread': key, 'tokens': tokens, 'credits': credits, 'usd': usd}
    return {'date': DAY, 'complete': True,
            'claude': [row('synthetic-a', 1000, 2, 1), row('synthetic-b', 2000, 4, 2)],
            'gpt': [row('synthetic-c', 6000, 9, 6)], 'sandbox': {'hours': 6, 'usd': 3}}


class Report(unittest.TestCase):
    def run_cli(self, data=None, usage_data=None, extra=()):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'gh').symlink_to(HERE / 'fake-gh')
        (root / 'world.json').write_text(json.dumps(world() if data is None else data))
        env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                   FAKE_GH_WORLD=str(root / 'world.json'), FAKE_GH_LOG=str(root / 'calls'),
                   GH_TOKEN='synthetic-app-token', PYTHONDONTWRITEBYTECODE='1')
        args = [sys.executable, str(SCRIPT), '--date', DAY, '--repo', REPO, '--out', str(root / 'out')]
        if usage_data is not None:
            (root / 'usage.json').write_text(usage_data if isinstance(usage_data, str) else json.dumps(usage_data))
            args += ['--usage', str(root / 'usage.json')]
        p = subprocess.run(args + list(extra), env=env, text=True, capture_output=True, timeout=15)
        calls = [json.loads(s) for s in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
        report = json.loads((root / 'out/report.json').read_text()) if (root / 'out/report.json').exists() else None
        return p, report, root, calls

    def test_hand_worked_day(self):
        p, r, root, calls = self.run_cli(usage_data=usage())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['merged_prs'], 3)
        self.assertEqual(r['merged_per_hour'], 0.125)
        self.assertEqual([h['merged_prs'] for h in r['hours']], [0, 1, 1, 0, 1] + [0] * 19)
        self.assertEqual(r['idle_minutes'], 175)
        self.assertEqual([h['idle_minutes'] for h in r['hours']], [40, 15, 20, 60, 30] + [0] * 18 + [10])
        self.assertEqual(r['biggest_stall']['tickets'], [14])
        self.assertEqual(r['biggest_stall']['minutes'], 90)
        self.assertEqual(len(r['stalls']), 5)
        self.assertEqual(r['costs']['claude']['tokens'], {'total': 3000, 'per_merged_pr': 1000})
        self.assertEqual(r['costs']['gpt']['credits'], {'total': 9, 'per_merged_pr': 3})
        self.assertEqual(r['costs']['sandbox']['hours'], {'total': 6, 'per_merged_pr': 2})
        self.assertEqual(r['costs']['actions']['minutes'], {'total': 12, 'per_merged_pr': 4})
        self.assertEqual(r['costs']['total_usd'], {'total': 12.6, 'per_merged_pr': 4.2})
        self.assertEqual(len(r['costs']['claude']['threads']), 2)
        saved = ''.join(f.read_text() for f in (root / 'out').iterdir())
        self.assertNotIn('synthetic-a', saved)
        self.assertNotIn('synthetic-app-token', saved)
        self.assertNotIn('thread synthetic', saved)
        self.assertTrue(all(c['token_seen'] for c in calls))
        self.assertEqual(len(calls), 4)
        self.assertEqual({json.dumps(c['args']) for c in calls}, set(world()))
        self.assertIn('175', p.stdout)
        self.assertIn('Historical completeness: unknown', p.stdout)

    def test_chart_values_and_table(self):
        p, r, root, _ = self.run_cli()
        self.assertEqual(p.returncode, 0, p.stderr)
        svg = ET.fromstring((root / 'out/factory.svg').read_text())
        marks = [e for e in svg.iter() if e.tag.endswith('title')]
        titles = [e.text for e in marks]
        self.assertIn('01 UTC: 1 merged PRs', titles)
        self.assertIn('03 UTC: 60 idle minutes', titles)
        self.assertEqual(len(titles), 49)  # chart title plus two bars per hour
        md = (root / 'out/report.md').read_text()
        self.assertIn('| 03 | 0 | 60.00 |', md)
        self.assertIn('unknown', md)

    def test_unreadable_sources_are_unknown(self):
        w = world()
        key = next(k for k in w if 'billing/' in k)
        w[key] = {'exit': 1, 'stdout': ''}
        p, r, root, _ = self.run_cli(w)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNone(r['costs']['actions']['minutes']['total'])
        self.assertIn('gh read failed', r['costs']['actions']['reason'])
        self.assertIsNone(r['costs']['total_usd']['total'])
        self.assertIn('unknown', p.stdout)
        self.assertIn('No daily CloudRoom usage export', r['costs']['claude']['reason'])
        cloud_reason = 'No daily CloudRoom usage export; this cloud CLI has no daily usage/billing endpoint'
        reasons = {'claude': cloud_reason, 'gpt': cloud_reason, 'sandbox': cloud_reason,
                   'actions': 'gh read failed (exit 1)'}
        outputs = {'report.md': (root / 'out/report.md').read_text(), 'stdout': p.stdout}
        for output, text in outputs.items():
            for source, reason in reasons.items():
                with self.subTest(output=output, source=source):
                    self.assertIn(f'{source}: {reason}.', text.splitlines())

    def test_pagination_for_prs_links_and_comments(self):
        w = world()
        first = json.loads(w[json.dumps(graph_args())]['stdout'])
        prs = first['data']['repository']['pullRequests']['nodes']
        prs[0]['closingIssuesReferences'] = connection(prs[0]['closingIssuesReferences']['nodes'][:1], True, 'links-next')
        w[json.dumps(graph_args())] = answer({'data': {'repository': {'pullRequests': connection(prs[:2], True, 'pr-next')}}})
        w[json.dumps(graph_args('pr-next'))] = answer({'data': {'repository': {'pullRequests': connection(prs[2:])}}})
        w[json.dumps(graph_args('links-next', 31))] = answer({'data': {'repository': {'pullRequest': {
            'closingIssuesReferences': connection([{'number': 15, 'repository': {'nameWithOwner': REPO}}])}}}})
        key = json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))
        comments = json.loads(w[key]['stdout'])
        # 100 unique irrelevant ordinary comments fill page 1; important records page 2.
        w[key] = answer([comment(1000+i, 80, '2030-01-01T01:00:00Z', 'ordinary') for i in range(100)])
        w[json.dumps(rest(BASE + '/issues/comments?per_page=100&page=2'))] = answer(comments)
        p, r, _, calls = self.run_cli(w)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['idle_minutes'], 175)
        self.assertEqual(r['merged_prs'], 3)
        self.assertEqual(len(calls), 7)

    def test_unknown_billing_shape_date_scope_or_units(self):
        for bad in [[], {'timePeriod': {'year': 2030}, 'usageItems': []},
                    {'timePeriod': {'year': 2030, 'month': 1, 'day': 2}, 'usageItems': [{'product': 'Other', 'unitType': 'minutes', 'grossQuantity': 5, 'netAmount': 2}]}]:
            with self.subTest(bad=bad):
                w = world()
                w[next(k for k in w if 'billing/' in k)] = answer(bad)
                p, r, _, _ = self.run_cli(w)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIsNone(r['costs']['actions']['minutes']['total'])
                self.assertTrue(r['costs']['actions']['reason'])

    def test_zero_merges_and_no_records(self):
        w = world()
        w[json.dumps(graph_args())] = answer({'data': {'repository': {'pullRequests': connection([])}}})
        w[json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))] = answer([])
        p, r, _, _ = self.run_cli(w, usage_data=usage())
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['idle_minutes'], 0)
        self.assertIsNone(r['biggest_stall'])
        self.assertIsNone(r['costs']['actions']['minutes']['per_merged_pr'])
        self.assertIn('no merged PRs', p.stdout)

    def test_duplicate_and_malformed_records_fail_without_output(self):
        for kind in ['duplicate-pr', 'duplicate-comment', 'bad-time', 'bad-issue-url', 'graphql-errors', 'duplicate-json-key']:
            with self.subTest(kind=kind):
                w = world()
                ck = json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))
                if kind == 'duplicate-pr':
                    value = json.loads(w[json.dumps(graph_args())]['stdout'])
                    value['data']['repository']['pullRequests']['nodes'] *= 2
                    w[json.dumps(graph_args())] = answer(value)
                elif kind == 'graphql-errors':
                    w[json.dumps(graph_args())] = answer({'errors': [{'message': 'synthetic'}], 'data': None})
                elif kind == 'duplicate-json-key':
                    w[ck] = {'stdout': '[{"id":1,"id":2}]', 'exit': 0}
                else:
                    rows = json.loads(w[ck]['stdout'])
                    if kind == 'duplicate-comment':
                        rows.append(rows[0])
                    elif kind == 'bad-time':
                        rows[0]['updated_at'] = 'yesterday'
                    else:
                        rows[0]['issue_url'] = 'https://evil.invalid/issues/35'
                    w[ck] = answer(rows)
                p, r, _, _ = self.run_cli(w)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIsNone(r)

    def test_malformed_usage_is_unknown_not_estimated(self):
        bads = [usage(), usage(), usage(), usage(), '{"date":"x","date":"y"}', '[]']
        bads[0]['date'] = '2030-01-01'
        bads[1]['complete'] = False
        bads[2]['claude'][0]['tokens'] = True
        bads[3]['gpt'][0]['credits'] = -1
        for bad in bads:
            with self.subTest(bad=bad):
                p, r, _, _ = self.run_cli(usage_data=bad)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIsNone(r['costs']['total_usd']['total'])
                self.assertIsNone(r['costs']['claude']['tokens']['total'])
                self.assertTrue(r['costs']['claude']['reason'])

    def test_server_clock_skew_and_overwritten_start_are_explicit(self):
        w = world()
        ck = json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))
        rows = json.loads(w[ck]['stdout'])
        rows.append(comment(500, 90, '2030-01-02T12:00:00Z', 'launch-fleet: archived',
                            '2030-01-02T12:00:01Z'))
        # The surviving failed body supplies no start time; never invent one.
        rows.append(comment(501, 91, '2030-01-02T12:30:00Z', 'launch-fleet: review failed abc',
                            '2030-01-02T10:00:00Z'))
        w[ck] = answer(rows)
        p, r, _, _ = self.run_cli(w)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['idle_minutes'], 175)
        self.assertEqual(r['clock_skew_comments'], 1)
        self.assertIn('unknown', r['historical_completeness'])

    def test_fractional_minutes_sum_without_accumulated_roundoff(self):
        w = world()
        rows = []
        for i, minute in enumerate(['00', '01', '02']):
            rows += [comment(700+i*2, 88, f'2030-01-02T12:{minute}:00Z', 'launch-fleet: findings sent abc'),
                     comment(701+i*2, 88, f'2030-01-02T12:{minute}:01Z', 'launch-fleet: moved')]
        w[json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))] = answer(rows)
        p, r, _, _ = self.run_cli(w)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['idle_minutes'], 0.05)  # 3 seconds / 60

    def test_unreported_unit_and_organization_billing(self):
        w = world()
        u = usage()
        u['claude'][0]['usd'] = None
        w[json.dumps(rest(BASE))] = answer({'owner': {'type': 'Organization'}})
        old = next(k for k in w if 'billing/' in k)
        value = w.pop(old)
        w[old.replace('users/example/', 'organizations/example/')] = value
        p, r, _, _ = self.run_cli(w, usage_data=u)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['costs']['claude']['tokens']['total'], 3000)
        self.assertIsNone(r['costs']['claude']['usd']['total'])
        self.assertIsNone(r['costs']['total_usd']['total'])
        self.assertEqual(r['costs']['actions']['minutes']['total'], 12)

    def test_chart_labels_keep_the_table_precision(self):
        w = world()
        rows = [comment(800, 88, '2030-01-02T12:00:00Z', 'launch-fleet: findings sent abc'),
                comment(801, 88, '2030-01-02T13:00:00Z', 'launch-fleet: moved'),
                comment(802, 89, '2030-01-02T12:00:00Z', 'launch-fleet: findings sent abc'),
                comment(803, 89, '2030-01-02T12:00:01Z', 'launch-fleet: moved')]
        w[json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))] = answer(rows)
        p, r, root, _ = self.run_cli(w)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(r['hours'][12]['idle_minutes'], 60.016667)
        self.assertIn('12 UTC: 60.016667 idle minutes', (root / 'out/factory.svg').read_text())

    def test_billing_day_requires_integer_fields(self):
        w = world()
        key = next(k for k in w if 'billing/' in k)
        data = json.loads(w[key]['stdout'])
        data['timePeriod']['month'] = True  # True == 1 is not an API integer.
        w[key] = answer(data)
        p, r, _, _ = self.run_cli(w)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIsNone(r['costs']['actions']['minutes']['total'])

    def test_r1_completion_caps_recorded_gaps(self):
        # All synthetic; expected minutes and endpoints are hand literals.
        cases = [
            ('PR merge', 40, '2030-01-02T10:00:00Z', '2030-01-02T10:30:00Z', None, 30, '2030-01-02T10:30:00Z'),
            ('PR unmerged close', 40, '2030-01-02T10:00:00Z', None, '2030-01-02T10:45:00Z', 45, '2030-01-02T10:45:00Z'),
            ('ticket linked merge', 20, '2030-01-02T10:00:00Z', '2030-01-02T10:30:00Z', None, 30, '2030-01-02T10:30:00Z'),
            ('stale PR start', 40, '2030-01-02T11:00:00Z', '2030-01-02T10:30:00Z', None, 0, None),
            ('stale closed PR start', 40, '2030-01-02T11:00:00Z', None, '2030-01-02T10:30:00Z', 0, None),
            ('stale ticket start', 20, '2030-01-02T11:00:00Z', '2030-01-02T10:30:00Z', None, 0, None),
            ('unmerged close leaves ticket open', 20, '2030-01-02T10:00:00Z', None, '2030-01-02T10:30:00Z', 90, '2030-01-02T11:30:00Z'),
            ('carry-in merge', 40, '2030-01-01T23:50:00Z', '2030-01-02T00:10:00Z', None, 10, '2030-01-02T00:10:00Z'),
        ]
        for name, source, start, merged, closed, minutes, until in cases:
            with self.subTest(case=name):
                w = world()
                w[json.dumps(graph_args())] = answer({'data': {'repository': {'pullRequests': connection([pr(40, merged, [20, 21], closed)])}}})
                rows = [comment(900, source, start, 'launch-fleet: review started abc'),
                        comment(901, 20, '2030-01-02T11:30:00Z', 'launch-fleet: archived')]
                w[json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))] = answer(rows)
                p, r, _, _ = self.run_cli(w)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(r['idle_minutes'], minutes)
                if until:
                    self.assertEqual(r['biggest_stall']['until'], until)
                    self.assertFalse(r['biggest_stall']['open_at_midnight'])
                    self.assertEqual(len(r['stalls']), 1)
                else:
                    self.assertEqual(r['stalls'], [])
                    self.assertIsNone(r['biggest_stall'])

    def test_r1_invalid_or_missing_closure_is_refused(self):
        for mode, value in [('missing', None), ('bad', False), ('bad', 0), ('bad', {}), ('bad', 'yesterday')]:
            with self.subTest(mode=mode, value=value):
                w = world()
                key = json.dumps(graph_args())
                data = json.loads(w[key]['stdout'])
                entry = data['data']['repository']['pullRequests']['nodes'][0]
                if mode == 'missing':
                    del entry['closedAt']
                else:
                    entry['closedAt'] = value
                w[key] = answer(data)
                p, r, _, _ = self.run_cli(w)
                self.assertEqual(p.returncode, 1, p.stderr)
                self.assertIsNone(r)

    def test_r1_open_tail_stops_at_midnight_before_merge(self):
        for merged, open_tail in [('2030-01-03T01:00:00Z', True), ('2030-01-03T00:00:00Z', False)]:
            with self.subTest(merged=merged):
                w = world()
                w[json.dumps(graph_args())] = answer({'data': {'repository': {'pullRequests': connection([
                    pr(40, merged, [20])])}}})
                w[json.dumps(rest(BASE + '/issues/comments?per_page=100&page=1'))] = answer([
                    comment(900, 40, '2030-01-02T23:50:00Z', 'launch-fleet: review started abc')])
                p, r, _, _ = self.run_cli(w)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(r['idle_minutes'], 10)
                self.assertEqual(r['biggest_stall']['open_at_midnight'], open_tail)
                self.assertEqual(r['biggest_stall']['until'], '2030-01-03T00:00:00Z')

    def test_r2_storage_charges_keep_minutes_and_usd(self):
        for product, unit in [('Actions', 'minutes'), ('actions', 'MINUTES'), ('ACTIONS', 'Minutes')]:
            with self.subTest(product=product, unit=unit):
                w = world()
                key = next(k for k in w if 'billing/' in k)
                value = json.loads(w[key]['stdout'])
                value['usageItems'][0].update(product=product, unitType=unit)
                value['usageItems'].append({'product': product, 'unitType': 'GigabyteHours',
                                            'grossQuantity': 100, 'netAmount': 0.9})
                w[key] = answer(value)
                p, r, root, _ = self.run_cli(w, usage_data=usage())
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(r['costs']['actions']['minutes'], {'total': 12, 'per_merged_pr': 4})
                self.assertEqual(r['costs']['actions']['usd'], {'total': 1.5, 'per_merged_pr': 0.5})
                self.assertEqual(r['costs']['total_usd'], {'total': 13.5, 'per_merged_pr': 4.5})
                self.assertIn('USD includes storage', r['costs']['actions']['reason'])
                self.assertIn('USD includes storage', p.stdout)
                self.assertIn('USD includes storage', (root / 'out/report.md').read_text())

    def test_r2_malformed_units_or_products_remain_unknown(self):
        for field, value in [('unitType', None), ('unitType', 12), ('unitType', ''),
                             ('product', 'Other'), ('product', None), ('grossQuantity', True)]:
            with self.subTest(field=field, value=value):
                w = world()
                key = next(k for k in w if 'billing/' in k)
                data = json.loads(w[key]['stdout'])
                data['usageItems'][0][field] = value
                w[key] = answer(data)
                p, r, _, _ = self.run_cli(w)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertIsNone(r['costs']['actions']['minutes']['total'])
                self.assertIsNone(r['costs']['actions']['usd']['total'])

    def test_bad_cli_reads_nothing(self):
        for args in [('--date', '2030-02-30'), ('--repo', '../bad'), ('--date', '2030-1-2')]:
            p, r, _, calls = self.run_cli(extra=args)
            self.assertEqual(p.returncode, 2)
            self.assertEqual(calls, [])
            self.assertIsNone(r)


if __name__ == '__main__':
    unittest.main(verbosity=2)
