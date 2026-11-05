#!/usr/bin/env python3
"""EB2 public CLI proofs; synthetic EB1 journeys and independent arithmetic."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.dont_write_bytecode = True
FIXTURE = ROOT/'tools/factory-metrics/fixtures/journey/journeys.json'
SINCE, UNTIL = '2030-01-01T08:00:00Z', '2030-01-02T08:00:00Z'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); return mod


def cf4_score(commit='a'*40, passed=True, stop='end_turn'):
    return {'schema': 'openwiz.skills-eval.score.v1', 'settings_hash': '2'*64,
            'cases_hash': '3'*64, 'code_hash': '4'*64, 'schema_hash': '5'*64,
            'revision': {'commit': commit, 'tree': 'b'*40}, 'suite_pass': passed,
            'runs': 1, 'passed': int(passed), 'cost_usd': 0,
            'rows': [{'case': 'synthetic', 'repeat': 1, 'pass': passed,
                      'reasons': [] if passed else ['forbidden' if stop == 'end_turn' else 'incomplete'],
                      'details': [], 'cost_usd': 0, 'stop': stop}]}


def run(*args, env=None):
    return subprocess.run([sys.executable, '-I', str(HERE/'trends.py'), *map(str, args)],
                          capture_output=True, text=True, timeout=30, env=env)


class Trends(unittest.TestCase):
    def report(self, doc=None, since=SINCE, until=UNTIL, scores=()):
        with tempfile.TemporaryDirectory() as temp:
            src, out = Path(temp)/'journeys.json', Path(temp)/'report.json'
            src.write_text(json.dumps(doc or json.loads(FIXTURE.read_text())))
            args = []
            for i, score in enumerate(scores):
                path = Path(temp)/f'score-{i}.json'; path.write_text(json.dumps(score))
                args += ['--cf4-score', path]
            result = run('report', src, '--since', since, '--until', until, '--out', out, *args)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(out.read_text())

    # P5: old tests cannot catch PR-created substituted for sourced push, or
    # a maturity/attribution gap presented as a known zero-defect baseline.
    def test_outcome_coverage_variability_and_legacy_compatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)/'report.json'
            result = run('report', FIXTURE, '--outcomes', FIXTURE.parent/'outcomes.json',
                         '--since', SINCE, '--until', UNTIL, '--out', out)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(out.read_text())
        for key, value in self.report().items():
            self.assertEqual(report[key], value)
        o = report['outcomes']
        t = o['merged']['first_push_to_merged_hours']
        self.assertEqual((t['n'], t['unknown'], t['mean'], t['median'], t['p90']), (2,0,12,12,18))
        self.assertAlmostEqual(t['sample_sd'], 8.485281, places=6)
        self.assertEqual(o['merged']['independent_rounds']['n'], 1)
        self.assertEqual(o['merged']['independent_rounds']['mean'], 3)
        g = o['merged']['defects']
        self.assertEqual((g['mature'],g['unmatured'],g['unknown_followup'],g['unknown_attribution']), (1,1,0,1))
        self.assertEqual((g['known_mature_prs'],g['affected_mature_prs'],g['rate']), (1,1,1))
        self.assertEqual(g['attributable_events'], 1)
        self.assertEqual(o['tickets'], {'total':3,'merged':2,'open':1,'closed':0,'without_pr':1})
        self.assertEqual(o['closed']['prs'], 0)
        text = json.dumps(o)
        for forbidden in ('https://','4201','4101','sources','e13','issue-4901'):
            self.assertNotIn(forbidden, text)
        # These sufficient statistics pool sample variability; daily medians do not.
        T = module('outcome_pool', HERE/'trends.py')
        pooled = T.period([{'since':SINCE,'until':UNTIL,'journey':report}], SINCE, UNTIL)['outcomes']
        self.assertEqual(pooled['merged']['first_push_to_merged_hours'], t)

    def test_assigned_unfinished_work_and_source_binding(self):
        cases=module('eb5_assigned_case',ROOT/'tools/factory-metrics/test_experiment_contract.py')
        case=cases.Contract();case.setUp();case.assigned();case.check()
        with tempfile.TemporaryDirectory() as temp:
            w=Path(temp)
            export={'journey':case.doc['journey'],'sources':case.doc['sources'],
                    'defect_policy':case.doc['experiment']['defect_policy']}
            (w/'journeys.json').write_text(json.dumps(case.journey))
            (w/'outcomes.json').write_text(json.dumps(export))
            (w/'experiment.json').write_text(json.dumps(case.doc))
            args=('report',w/'journeys.json','--outcomes',w/'outcomes.json','--experiment',w/'experiment.json',
                  '--since',SINCE,'--until',UNTIL,'--out',w/'report.json')
            r=run(*args);self.assertEqual(r.returncode,0,r.stderr)
            report=json.loads((w/'report.json').read_text())
            a=report['outcomes']['assigned']['old']
            self.assertEqual((a['tickets'],a['open'],a['closed'],a['merged'],a['without_pr']), (1,1,0,0,1))
            self.assertEqual(a['outcomes']['prs'],0)
            self.assertEqual(report['outcomes']['assigned']['candidate']['tickets'],0)
            self.assertIn('assigned 1, merged 0, open 1',self.dashboard_report(report))
            # Sidecar IDs cannot bind to different source URLs in its experiment.
            good=(w/'report.json').read_text()
            case.doc['sources']['s1']='https://github.com/example/factory/issues/4900#issuecomment-9999'
            (w/'experiment.json').write_text(json.dumps(case.doc))
            r=run(*args);self.assertEqual(r.returncode,1,r.stderr)
            self.assertEqual((w/'report.json').read_text(),good)

    def test_failed_outcome_reads_preserve_last_report_and_publication_boundary(self):
        T=module('eb6_validation',HERE/'trends.py')
        for name,mutate in [
            ('malformed sidecar',lambda x:x.update(journey=[],defect_policy=None)),
            ('operational identity',lambda x:x['journey']['measurements'][0]['defects']['events'][0].update(key='thr_syntheticdefect')),
            ('stale hash',lambda x:x['journey'].update(journey_hash='0'*64)),
            ('helper round',lambda x:x['journey']['measurements'][0]['rounds'].append('e19')),
            ('missing measurement',lambda x:x['journey']['measurements'].pop()),
            ('unknown attribution matured falsely',lambda x:x['journey']['measurements'][1]['defects'].update(status='mature')),
            ('foreign evidence',lambda x:x['sources'].update(s1='https://example.invalid/private')),
        ]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as temp:
                w=Path(temp); side=json.loads((FIXTURE.parent/'outcomes.json').read_text());mutate(side)
                (w/'outcomes.json').write_text(json.dumps(side));(w/'report.json').write_text('last good')
                r=run('report',FIXTURE,'--outcomes',w/'outcomes.json','--since',SINCE,'--until',UNTIL,'--out',w/'report.json')
                self.assertEqual(r.returncode,1,r.stderr)
                self.assertEqual((w/'report.json').read_text(),'last good')
                self.assertTrue(r.stderr.startswith('trends: '),r.stderr)
        report=T.report(json.loads(FIXTURE.read_text()),SINCE,UNTIL,
                        outcomes=json.loads((FIXTURE.parent/'outcomes.json').read_text()))
        md=self.dashboard_report(report)
        for value in ('First push → verified merge','8.48528','affected/known mature','immature','root-cause-per-merge'):
            self.assertIn(value,md)
        # The same reader validates data before both rendering and publication.
        for mutate in (lambda o:o.update(sources={}),
                       lambda o:o['merged']['first_push_to_merged_hours'].update(mean=99),
                       lambda o:o['merged']['defects'].update(rate=0)):
            bad=copy.deepcopy(report);mutate(bad['outcomes'])
            with self.assertRaises(T.J.ReadError):T.validate(bad)

    def test_unfinished_closed_and_no_merge_outcomes_remain_unknown(self):
        T=module('eb6_unfinished',HERE/'trends.py')
        for state in ('open','closed'):
            with self.subTest(state=state):
                d=json.loads(FIXTURE.read_text())
                for p in d['pull_requests']:
                    p['state']=state;p['revisions']['merge']=None
                    p['events']=[e for e in p['events'] if e['kind']!='merge']
                for t in d['tickets']:
                    if t['pull_requests']:t['state']=state
                side={'journey':T.J.outcome_contract().migrate_journey(d),'sources':{},'defect_policy':None}
                r=T.report(d,SINCE,UNTIL,outcomes=side);T.validate(r)
                self.assertEqual(r['cohorts']['merged']['prs'],0)
                o=r['outcomes'];self.assertEqual(o['all']['prs'],2)
                self.assertEqual(o[state]['prs'],2)
                self.assertEqual(o[state]['first_push_to_merged_hours']['unknown'],2)
                self.assertIsNone(o['merged']['first_push_to_merged_hours']['mean'])
                self.assertIsNone(o['all']['defects']['rate'])
                self.assertEqual(o['tickets']['without_pr'],1)
                self.assertEqual(o['all']['defects']['unknown_followup'],2)

    def test_cohorts_rounds_findings_and_latency(self):
        r = self.report()
        self.assertEqual(r['cohorts']['merged'], {
            'prs': 2, 'reviewed': 1, 'unreviewed': 1, 'first_approve': 0,
            'rounds': 3, 'approval_share': 0, 'rounds_per_pr': 3})
        self.assertEqual(r['cohorts']['reviewed']['prs'], 1)
        self.assertEqual(r['cohorts']['open']['prs'], 0)
        self.assertEqual(r['ready_to_merged_hours'], {'tickets': 1, 'unknown': 1, 'median': 19, 'p90': 19})
        self.assertEqual(r['findings'], {'missing-proof': 0, 'stale-docs': 1, 'spec-mismatch': 0,
                                         'fail-open': 1, 'unknown': 2})
        self.assertEqual(r['coverage']['history'], 'unknown')
        self.assertEqual(r['coverage']['unlinked_open_tickets'], 1)
        # Publication-safe: no ticket/PR numbers, provenance URLs or event ids.
        text = json.dumps(r)
        for private in ('4101', '4201', 'https://', 'thr_', 'raised_by', 'sources'):
            self.assertNotIn(private, text)

        # One ticket can have several closing PRs; the whole document owns
        # its first merge, even outside the window or the factory's selection.
        trends = module('first_closing_merge', HERE/'trends.py')
        cases = [
            ('before window', '2029-12-31T12:00:00Z', None, 0, None),
            ('earlier merge', '2030-01-01T12:00:00Z', None, 1, 1),
            ('later merge', '2030-01-02T07:00:00Z', None, 1, 19),
            ('tie lower selected', '2030-01-02T06:00:00Z', {4201, 4202}, 1, 19),
            ('tie lower excluded', '2030-01-02T06:00:00Z', {4202, 4203}, 0, None),
            ('earlier excluded', '2030-01-01T12:00:00Z', {4201, 4202}, 0, None),
            ('not merged', None, None, 1, 19),
        ]
        for name, at, selected, count, hours in cases:
            for reverse in (False, True):
                with self.subTest(first_merge=name, reverse=reverse):
                    d = json.loads(FIXTURE.read_text())
                    extra = copy.deepcopy(d['pull_requests'][0])
                    extra.update(number=4203, experiment=None, findings=[])
                    extra['events'] = [dict(extra['events'][-1], id='e100', at=at)] if at else []
                    if at is None:
                        extra['state'] = 'open'; extra['revisions']['merge'] = None
                    d['pull_requests'].append(extra)
                    d['tickets'][0]['pull_requests'].append(4203)
                    if reverse: d['pull_requests'].reverse()
                    # collect() passes its factory PR selection to report().
                    result = (self.report(d) if selected is None else
                              trends.report(d, SINCE, UNTIL, merged_prs=selected))
                    self.assertEqual(result['ready_to_merged_hours'], {
                        'tickets': count, 'unknown': 1, 'median': hours, 'p90': hours})

    def test_zero_merges_and_unknown_costs(self):
        r = self.report(since=UNTIL, until='2030-01-03T08:00:00Z')
        self.assertEqual(r['cohorts']['merged']['prs'], 0)
        self.assertIsNone(r['cohorts']['merged']['approval_share'])
        self.assertIsNone(r['attributed_credits']['claude']['per_merged_pr'])
        r = self.report()
        c = r['attributed_credits']['claude']
        self.assertEqual(c['known_ticket_lower_bound'], 7)
        self.assertEqual(c['known_tickets'], 1)
        self.assertEqual(c['unknown_tickets'], 1)
        self.assertIsNone(c['per_merged_pr'])  # Missing attribution cannot be zero.
        self.assertIsNone(r['attributed_credits']['gpt']['per_merged_pr'])
        self.assertEqual(r['daily_usage_ratios'][0]['date'], '2030-01-01')
        # Two fully attributed merged tickets: Claude (7+5)/2 = 6,
        # GPT (2+4)/2 = 3; a second case proves reported zeros stay numeric.
        for zero_gpt in (False, True):
            with self.subTest(zero_gpt=zero_gpt):
                d = json.loads(FIXTURE.read_text())
                for ticket, claude, gpt in [(d['tickets'][0], 7, 2), (d['tickets'][2], 5, 4)]:
                    for u in ticket['usage']:
                        if u['unit'] == 'credits':
                            u.update(status='known', value=claude if u['provider'] == 'claude' else 0 if zero_gpt else gpt,
                                     missing_days=[])
                full = self.report(d)['attributed_credits']
                self.assertEqual(full['claude']['per_merged_pr'], 6)
                self.assertEqual(full['gpt']['per_merged_pr'], 0 if zero_gpt else 3)
                self.assertEqual(full['claude']['known_ticket_lower_bound'], 12)
                self.assertEqual(full['claude']['unknown_tickets'], 0)

    def test_experiment_revisions_and_absent_paid_evidence(self):
        e = self.report()['experiments'][0]
        self.assertEqual(e['tag'], 'build-ticket-r2')
        self.assertEqual(e['revisions']['base'], 'd'*40)
        self.assertEqual(e['cf4']['settings_hash'], '2'*64)
        self.assertEqual(e['cf4']['cases_hash'], '3'*64)
        self.assertEqual(e['cf4_status'], 'not recorded')
        self.assertIsNone(e['result_hash'])
        self.assertEqual(e['merged_at'], '2030-01-02T06:00:00Z')

    def test_invalid_or_partial_journey_never_replaces_report(self):
        for mutate in (lambda d: d.pop('history'), lambda d: d['pull_requests'].append(d['pull_requests'][0])):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temp:
                d = json.loads(FIXTURE.read_text()); mutate(d)
                src, out = Path(temp)/'in.json', Path(temp)/'out.json'
                src.write_text(json.dumps(d)); out.write_text('last good')
                r = run('report', src, '--since', SINCE, '--until', UNTIL, '--out', out)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual(out.read_text(), 'last good')

    def test_open_cohort_is_current_snapshot_and_shared_pr_counted_once(self):
        d = json.loads(FIXTURE.read_text())
        p = d['pull_requests'][1]
        p['state'] = 'open'; p['revisions']['merge'] = None
        p['events'] = p['events'][:1]
        d['tickets'][2]['state'] = 'open'
        r = self.report(d)
        self.assertEqual(r['cohorts']['merged']['prs'], 1)
        self.assertEqual(r['cohorts']['open']['prs'], 1)
        self.assertEqual(r['cohorts']['open']['unreviewed'], 1)
        self.assertIn('current', r['coverage']['open_basis'])

    def test_empty_doc_has_known_counts_unknown_ratios(self):
        d = json.loads(FIXTURE.read_text())
        for k in ('specs', 'tickets', 'pull_requests', 'daily_usage'): d[k] = []
        d['sources'] = {}
        r = self.report(d)
        self.assertEqual(r['cohorts']['merged']['prs'], 0)
        self.assertIsNone(r['ready_to_merged_hours']['median'])
        self.assertEqual(sum(r['findings'].values()), 0)


    def test_fake_gh_collects_shared_journeys_and_fails_without_replacing_good_report(self):
        f = module('journey_fixture', ROOT/'tools/factory-metrics/test_journey.py')
        with tempfile.TemporaryDirectory() as temp:
            w = Path(temp); (w/'gh').symlink_to(ROOT/'tools/factory-metrics/fake-gh')
            world = f.world()
            # Factory sees only its first closing-link page; EB1's inventory has all links.
            inventory = json.loads(world[f.q(f.PRS)]['stdout'])
            inventory['data']['repository']['pullRequests']['nodes'][0]['closingIssuesReferences']['nodes'].append(
                {'number': 4102, 'repository': {'nameWithOwner': f.REPO}})
            world[f.q(f.PRS)] = f.answer(inventory)
            (w/'world.json').write_text(json.dumps(world))
            (w/'factory.json').write_text(json.dumps({'since': SINCE, 'until': UNTIL,
                'prs': [{'number': n, 'merged_at': at, 'verdicts': [], 'verdicts_complete': True,
                         'tickets_complete': True, 'tickets': [{'number': t, 'ready_at': None, 'ready': 'none'}]}
                        for n, t, at in [(4201, 4101, '2030-01-02T06:00:00Z'), (4202, 4103, '2030-01-02T02:00:00Z')]],
                'main': {'observations': [], 'carry_in': False, 'untimed': 0}, 'reruns': [], 'attempts': [], 'jobs': []}))
            env = dict(os.environ, PATH=str(w)+os.pathsep+os.environ['PATH'],
                       FAKE_GH_WORLD=str(w/'world.json'), FAKE_GH_LOG=str(w/'calls'))
            r = run('collect', '--repo', 'example/factory', w, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = w/'journey-report.json'; good = out.read_text()
            self.assertEqual(json.loads(good)['cohorts']['merged']['rounds'], 3)
            self.assertEqual(json.loads(good)['ready_to_merged_hours']['tickets'], 2)
            world[f.q(f.ISSUE, 4101)] = {'stdout': '', 'exit': 1}
            (w/'world.json').write_text(json.dumps(world))
            r = run('collect', '--repo', 'example/factory', w, env=env)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertEqual(out.read_text(), good)

    def test_recorded_cf4_results_distinguish_pass_fail_unfinished(self):
        eval_dir = ROOT/'tools/skills-eval'
        sys.path.insert(0, str(eval_dir))
        try:
            scorer = module('cf4_scorer', eval_dir/'score.py')
        finally:
            sys.path.remove(str(eval_dir))
        # The real scorer calls an empty final reply incomplete even after end_turn.
        passed, reasons, details = scorer.score({'expect': {'actions': []}},
            {'events': [], 'stop': 'end_turn', 'final': ''}, {})
        self.assertEqual((passed, reasons), (False, ['incomplete']))
        empty_final = cf4_score(passed=False)
        empty_final['rows'][0].update({'pass': passed, 'reasons': reasons, 'details': details})
        cases = [('passing', cf4_score()), ('failed', cf4_score(passed=False)),
                 ('unfinished', cf4_score(passed=False, stop='cap')), ('unfinished', empty_final)]
        for i, (state, score) in enumerate(cases):
            with self.subTest(state=state, case=i), tempfile.TemporaryDirectory() as temp:
                w = Path(temp)
                (w/'score.json').write_text(json.dumps(score))
                r = run('report', FIXTURE, '--since', SINCE, '--until', UNTIL, '--out', w/'out.json',
                        '--cf4-score', w/'score.json')
                self.assertEqual(r.returncode, 0, r.stderr)
                e = json.loads((w/'out.json').read_text())['experiments'][0]
                self.assertEqual(e['cf4_status'], state)
                self.assertEqual(len(e['result_hash']), 64)

    def test_dashboard_trends_weekly_windows_and_sanitized_publication_boundary(self):
        from datetime import datetime, timedelta
        fixture = module('bench_fixture', HERE/'test.py')
        base = copy.deepcopy(fixture.WINDOW_POINT)
        with tempfile.TemporaryDirectory() as temp:
            w = Path(temp); days = []
            for i in range(15):
                d = w/str(i); d.mkdir(); days.append(d)
                a = datetime(2030, 1, 1, 8) + timedelta(days=i); b = a+timedelta(days=1)
                p = copy.deepcopy(base)
                p.update(since=a.strftime('%Y-%m-%dT%H:%M:%SZ'), until=b.strftime('%Y-%m-%dT%H:%M:%SZ'),
                         hours=24, label=f'{a.date()} PST', latency_basis='workflow created to last job completed')
                t = self.report(); t['since'], t['until'] = p['since'], p['until']
                t['cohorts']['merged'] = {'prs': 2, 'reviewed': 2, 'unreviewed': 0,
                    'first_approve': 1 if i < 8 else 2, 'rounds': 4 if i < 8 else 2,
                    'approval_share': .5 if i < 8 else 1, 'rounds_per_pr': 2 if i < 8 else 1}
                t['experiments'] = t['experiments'] if i == 7 else []
                if i == 7: t['experiments'][0]['merged_at'] = '2030-01-08T12:00:00Z'
                p['journey'] = t
                (d/'point.json').write_text(json.dumps(p))
            cmd = [sys.executable, '-I', str(HERE/'bench.py'), 'dashboard', *map(str, days), '--out', str(w/'charts')]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = (w/'charts/journey-trends.md').read_text()
            for text in ('2026-11-06', '65/89', '64/75', '1/14', 'build-ticket-r2',
                         'Week over week', 'Before/after', '14/14', '7/14', 'not recorded',
                         'not causation', 'settings', 'cases', 'unknown'):
                self.assertIn(text, md)
            experiment_section = md.split('## Before/after tagged experiments', 1)[1]
            self.assertEqual([line for line in experiment_section.splitlines() if line.startswith('| Before |')], [
                '| Before | 2030-01-01T08:00:00Z – 2030-01-08T08:00:00Z | 7/7 | 14 | 7/14 (0.5) | 2 (rounds=28, n=14) | 0 |'])
            self.assertEqual([line for line in experiment_section.splitlines() if line.startswith('| After |')], [
                '| After | 2030-01-09T08:00:00Z – 2030-01-16T08:00:00Z | 7/7 | 14 | 14/14 (1) | 1 (rounds=14, n=14) | 0 |'])
            self.assertIn('journey-trends.md', (w/'charts/README.md').read_text())
            import xml.etree.ElementTree as ET
            svg = ET.fromstring((w/'charts/journey-reviews.svg').read_text())
            self.assertEqual(svg.attrib['fill'], '#f0f6fc')
            lines = svg.findall('{http://www.w3.org/2000/svg}line')
            self.assertEqual(len(lines), 2)  # Only each panel's zero line; no grid or axis numbers.
            self.assertFalse(any(e.attrib.get('x') == '55' for e in svg.iter()))
            # Inject an unpublished raw field: strict point reader must refuse.
            p['journey']['sources'] = {'s1': 'https://example.invalid/private'}
            (days[-1]/'point.json').write_text(json.dumps(p))
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 1, r.stderr)


    def test_unknown_pr_events_include_unanswered_fix_rounds(self):
        d = json.loads(FIXTURE.read_text())
        e = next(e for e in d['pull_requests'][0]['events'] if e['kind'] == 'fix_round')
        e.update(at=None, source=None, completeness='unknown', answers=[])
        self.assertEqual(self.report(d)['coverage']['unknown_events'], 1)

    def test_uncollected_closing_ticket_counts_as_unknown_latency_and_credit(self):
        d = json.loads(FIXTURE.read_text())
        d['pull_requests'][0]['tickets'].append(4998)
        r = self.report(d)
        self.assertEqual(r['ready_to_merged_hours']['unknown'], 2)
        self.assertEqual(r['attributed_credits']['claude']['unknown_tickets'], 2)

    def test_cf4_bad_rows_fail_closed_without_replacing_good_report(self):
        good = cf4_score()
        mutations = {
            'missing identity': lambda s: s['rows'][0].pop('case'),
            'missing repeat': lambda s: s['rows'][0].pop('repeat'),
            'repeat zero': lambda s: s['rows'][0].update(repeat=0),
            'repeat boolean': lambda s: s['rows'][0].update(repeat=True),
            'skipped first repeat': lambda s: s['rows'][0].update(repeat=2),
            'extra field': lambda s: s['rows'][0].update(untrusted='text'),
            'invalid case': lambda s: s['rows'][0].update(case='../private'),
            'inconsistent reason': lambda s: s['rows'][0].update(reasons=['incomplete']),
            'duplicate case/repeat': lambda s: (s['rows'].append(copy.deepcopy(s['rows'][0])), s.update(runs=2, passed=2)),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                w = Path(temp); score = copy.deepcopy(good); mutate(score)
                (w/'score.json').write_text(json.dumps(score)); (w/'out.json').write_text('last good')
                r = run('report', FIXTURE, '--since', SINCE, '--until', UNTIL, '--out', w/'out.json',
                        '--cf4-score', w/'score.json')
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertEqual((w/'out.json').read_text(), 'last good')

    def dashboard_report(self, report, hours=24, label='2030-01-01 PST'):
        fixture = module('bench_fixture', HERE/'test.py')
        with tempfile.TemporaryDirectory() as temp:
            w = Path(temp); p = copy.deepcopy(fixture.WINDOW_POINT)
            p.update(since=report['since'], until=report['until'], label=label, hours=hours,
                     latency_basis='workflow created to last job completed', journey=report)
            (w/'point.json').write_text(json.dumps(p))
            r = subprocess.run([sys.executable, '-I', str(HERE/'bench.py'), 'dashboard', str(w),
                                '--out', str(w/'out')], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            return (w/'out/journey-trends.md').read_text()

    def test_baseline_scores_survive_without_a_second_tagged_experiment(self):
        for changed in (None, 'cases_hash', 'settings_hash', 'code_hash', 'schema_hash'):
            with self.subTest(changed=changed):
                baseline = cf4_score(commit='d'*40)
                if changed: baseline[changed] = '9'*64
                r = self.report(scores=[cf4_score(), baseline])
                e = r['experiments'][0]
                self.assertEqual(len(e['baselines']), 1)
                self.assertEqual(e['baselines'][0]['cf4']['revision'], 'd'*40)
                md = self.dashboard_report(r)
                self.assertIn('Baseline revision `'+('d'*40)+'`', md)
                self.assertIn('Compatible CF4 baseline: '+('unknown' if changed else 'recorded'), md)
                if changed: self.assertIn('fresh baseline', md)

    def test_partial_checkpoint_keeps_experiments_outside_weekly_day_arithmetic(self):
        r = self.report(until='2030-01-02T07:00:00Z')
        md = self.dashboard_report(r, hours=23, label='synthetic checkpoint')
        self.assertIn('build-ticket-r2', md)
        self.assertIn('synthetic checkpoint', md)
        self.assertIn('No daily observations.', md)
        self.assertIn('Before/after', md)
        self.assertIn('| Before |', md)
        self.assertIn('| After |', md)
        self.assertIn('| 0/7 | 0 | 0/0 (unknown)', md)



    def test_missing_publication_day_breaks_both_journey_charts_without_counting_as_observed(self):
        import xml.etree.ElementTree as ET
        fixture = module('bench_fixture', HERE/'test.py')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); days = []
            for day, end in [('01', '02'), ('03', '04')]:
                w = root/day; w.mkdir(); days.append(w)
                p = copy.deepcopy(fixture.WINDOW_POINT)
                r = self.report()
                p.update(since=f'2030-01-{day}T08:00:00Z', until=f'2030-01-{end}T08:00:00Z',
                         label=f'2030-01-{day} PST', hours=24,
                         latency_basis='workflow created to last job completed', journey=r)
                r['since'], r['until'] = p['since'], p['until']
                (w/'point.json').write_text(json.dumps(p))
            result = subprocess.run([sys.executable, '-I', str(HERE/'bench.py'), 'dashboard',
                                     *map(str, days), '--out', str(root/'out')], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            ns = '{http://www.w3.org/2000/svg}'
            for name, panels in [('journey-reviews.svg', 2), ('journey-findings.svg', 5)]:
                with self.subTest(chart=name):
                    svg = ET.fromstring((root/'out'/name).read_text())
                    texts = [e.text for e in svg.iter(ns+'text')]
                    self.assertEqual(texts.count('2030-01-02'), panels)
                    gap_labels = [e for e in svg.iter(ns+'text')
                                  if e.text == 'unknown' and e.attrib.get('text-anchor') == 'middle']
                    self.assertEqual(len(gap_labels), panels)  # Excludes the unknown-kind panel title/legend.
                    segments = svg.findall(ns+'polyline')
                    self.assertEqual(len(segments), panels*2)
                    self.assertTrue(all(len(e.attrib['points'].split()) == 1 for e in segments))
            md = (root/'out/journey-trends.md').read_text()
            latest = next(line for line in md.splitlines() if line.startswith('| Latest week |'))
            self.assertIn('| 2/7 | 4 |', latest)  # Only the two actual publication days, four merged PRs.


if __name__ == '__main__': unittest.main()
