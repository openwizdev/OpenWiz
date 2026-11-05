#!/usr/bin/env python3
"""RL0 review-loops bench proofs (spec #2454), synthetic and offline only.

Seam 1: recorded journey, EB6 outcome, finding-classification and watchdog
inputs in; the four measures out, each with n, Unknown and coverage; plus the
report check and the BEFORE/AFTER comparison.

Plausible breaks these catch: a PR closing two tickets or a reposted verdict
counted twice; a PR with no review or no push receipt read as zero; an
immature PR entering the defect rate; a blocking finding with no user path or
risk line passing the report check; a polish finding refused for lacking one.

Worked cohort (EB6's own journey fixture, tools/factory-metrics/fixtures/journey):
PR 4201 has independent rounds at heads aaaa, bbbb and cccc (bbbb reposted
once, cccc also has a helper verdict), a receipt 18 h before merge, opened
16 h before merge, a mature attributable defect, and findings R1 high, R2
medium, R3 low, R4 medium. PR 4202 has no review, a receipt 6 h and opening
0.5 h before merge, and an immature defect. PR 4204 is in the cohort but not
in the journey. So: rounds n 1 (mean 3), Unknown 2; push n 2 (mean 12,
median 12, p90 18), Unknown 1; opened n 2 (mean 8.25, p90 16); findings 3
blocking-grade, 2 classified (1 yes), share 0.5, Unknown 1; defects 1 mature,
1 immature, 1 unknown follow-up, rate 1/1.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('rl_review_loops', HERE / 'review_loops.py')
R = importlib.util.module_from_spec(spec)
spec.loader.exec_module(R)
FIX = HERE / 'fixtures/review-loops'
EB6 = HERE.parent / 'factory-metrics/fixtures/journey'
DOC = json.loads((EB6 / 'journeys.json').read_text())
EB6_EXPORT = json.loads((EB6 / 'outcomes.json').read_text())  # EB6's own fixture, on a 48-hour policy
FROZEN = {'rule': 'explicit-causal-fix-link-v1', 'followup_hours': 72, 'deduplication': 'root-cause-per-merge',
          'unknown_attribution': 'retain-unknown'}  # the contract's frozen policy, typed independently


def frozen(export):
    """EB6's sidecar on the contract's 72-hour policy: 4201's follow-up read until merge + 72 h."""
    export = copy.deepcopy(export)
    export['defect_policy'] = dict(FROZEN)
    export['journey']['measurements'][0]['defects']['observed_until'] = '2030-01-05T06:00:00Z'
    return export


EXPORT = frozen(EB6_EXPORT)
COHORT = json.loads((FIX / 'cohort.json').read_text())
FINDINGS = json.loads((FIX / 'findings.json').read_text())
WATCHDOG = (FIX / 'watchdog.jsonl').read_text()
C = R.J.outcome_contract()


def wire(doc, export):
    """Rebind the outcome sidecar to the mutated journey, as collection does."""
    export = copy.deepcopy(export)
    export['journey']['journey_hash'] = C.digest(json.loads(json.dumps(doc)))
    for m, p in zip(export['journey']['measurements'], doc['pull_requests']):
        m['rounds'] = [e['id'] for e in p['events'] if R.J.rounds_of(e)]
    return json.dumps(doc).encode(), json.dumps(export).encode()


def run(doc=DOC, export=EXPORT, cohort=COHORT, findings=None, watchdog=None, reports=None):
    if findings is None:  # the worked classifications, for the PRs still in the cohort
        findings = dict(FINDINGS, findings=[f for f in FINDINGS['findings'] if f['pr'] in cohort['prs']])
    j, o = wire(doc, export)
    return R.bench(cohort, j, o, findings, watchdog, reports)


def pr(doc, n):
    return next(p for p in doc['pull_requests'] if p['number'] == n)


class Measures(unittest.TestCase):
    def test_worked_cohort_arithmetic_unknown_and_coverage(self):
        b = run()
        self.assertEqual('closedwiz.review-loops.bench.v1', b['schema'])
        self.assertEqual([4201, 4202, 4204], b['cohort']['prs'])
        self.assertEqual(3, b['cohort']['size'])
        self.assertEqual([{'pr': 4204, 'why': 'not in the journey'}], b['cohort']['missing'])
        m = b['measures']
        self.assertEqual(dict(n=1, unknown=2, total=3, mean=3.0, median=3.0, p90=3.0, coverage=0.333333),
                         m['review_rounds'])
        self.assertEqual(dict(n=2, unknown=1, mean=12.0, median=12.0, p90=18.0, coverage=0.666667),
                         m['first_push_to_merge_hours'])
        self.assertEqual(dict(n=2, unknown=1, mean=8.25, median=8.25, p90=16.0, coverage=0.666667),
                         m['pr_opened_to_merge_hours'])
        self.assertEqual(dict(findings=3, classified=2, unknown=1, user_path=1, no_user_path=1,
                              share=0.5, coverage=0.666667, basis=['judgment'], reports=None), m['real_user_path'])
        d = m['escaped_defects']
        self.assertEqual((1, 1, 1), (d['mature'], d['immature'], d['unknown_followup']))
        self.assertEqual((1, 1, 1.0), (d['known_mature_prs'], d['affected_mature_prs'], d['rate']))
        self.assertEqual(FROZEN, d['policy'])
        self.assertIsNone(m['watchdog'])

    def test_shared_pr_counts_once(self):
        doc = copy.deepcopy(DOC)
        pr(doc, 4201)['tickets'] = [4101, 4102]
        t = next(t for t in doc['tickets'] if t['ticket'] == 4102)
        t['state'], t['pull_requests'] = 'merged', [4201]
        t['gaps'] = [g for g in t['gaps'] if g not in ('no pull request', 'no merge')]
        R.J.validate(json.loads(json.dumps(doc)))
        b = run(doc)
        self.assertEqual(run()['measures'], b['measures'])
        self.assertEqual(3, b['cohort']['size'])
        cohort = dict(COHORT, prs=[4201, 4201, 4202])
        with self.assertRaises(ValueError):
            run(cohort=cohort)

    def test_repeated_and_same_head_verdicts_count_once(self):
        doc = copy.deepcopy(DOC)
        events = pr(doc, 4201)['events']
        at = next(i for i, e in enumerate(events) if e['id'] == 'e18')
        events.insert(at + 1, dict(events[at], id='e99', verdict='APPROVE', at='2030-01-01T20:30:00Z',
                                   duplicate_of=None))
        R.J.validate(json.loads(json.dumps(doc)))
        self.assertEqual(4, sum(R.J.rounds_of(e) for e in events))
        self.assertEqual(3, run(doc)['measures']['review_rounds']['mean'])

    def test_unreviewed_pr_is_unknown_not_zero(self):
        cohort = dict(COHORT, prs=[4202])
        r = run(cohort=cohort)['measures']['review_rounds']
        self.assertEqual((0, 1, None, None), (r['n'], r['unknown'], r['mean'], r['median']))

    def test_missing_receipt_is_unknown(self):
        export = copy.deepcopy(EXPORT)
        export['journey']['measurements'][0]['first_push'] = {
            'status': 'unknown', 'at': None, 'kind': None, 'source': None, 'coverage': 'unknown'}
        export['sources'].pop('s1')
        p = run(export=export)['measures']['first_push_to_merge_hours']
        self.assertEqual((1, 2, 6.0), (p['n'], p['unknown'], p['median']))

    def test_only_the_frozen_defect_policy_is_admitted(self):
        # R3: EB6 artifacts collected on another follow-up window count PRs mature too early.
        for hours in (48, 24, 96):
            export = copy.deepcopy(EXPORT)
            export['defect_policy']['followup_hours'] = hours
            if hours == 48:
                export = copy.deepcopy(EB6_EXPORT)
            with self.assertRaisesRegex(ValueError, 'frozen defect policy'):
                run(export=export)

    def test_immature_prs_stay_out_of_the_defect_rate(self):
        cohort = dict(COHORT, prs=[4202])
        d = run(cohort=cohort)['measures']['escaped_defects']
        self.assertEqual((0, 1, 0, None), (d['mature'], d['immature'], d['known_mature_prs'], d['rate']))

    def test_post_merge_or_edited_reviews_are_not_rounds(self):
        doc = copy.deepcopy(DOC)
        for e in pr(doc, 4201)['events']:
            if e['kind'] == 'verdict':
                e['completeness'] = 'edited'
        r = run(doc, findings=dict(FINDINGS, findings=[]))['measures']
        self.assertEqual((0, 3), (r['review_rounds']['n'], r['review_rounds']['unknown']))
        self.assertEqual(0, r['real_user_path']['findings'])
        self.assertIsNone(r['real_user_path']['share'])


class Classifications(unittest.TestCase):
    def refused(self, mutate):
        findings = copy.deepcopy(FINDINGS)
        mutate(findings['findings'])
        with self.assertRaises(ValueError):
            run(findings=findings)

    def test_every_classification_names_a_journey_finding_and_its_report(self):
        self.refused(lambda f: f.append(dict(f[0], finding='R9')))
        self.refused(lambda f: f.append(dict(f[0], finding='R3', severity='low')))
        self.refused(lambda f: f.append(dict(f[0])))
        self.refused(lambda f: f[0].update(report='https://github.com/example/factory/pull/4201#issuecomment-5204'))
        self.refused(lambda f: f[0].update(severity='medium'))
        self.refused(lambda f: f[0].update(user_path='yes'))
        self.refused(lambda f: f[0].update(extra=1))
        self.refused(lambda f: f[0].update(why='see ' + 'thr' + '_abc123def'))

    # R2: AFTER's blocking findings are inventoried from the reports of admitted rounds, never
    # from the classifications themselves. 4201's admitted rounds are e13 (aaaa), e17 (bbbb) and
    # e22 (cccc); e18 reposts e17 and e19 is a helper's.
    E17 = ((FIX / 'report-ok.md').read_text().replace('4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08', 'b' * 40)
           .replace('R1', 'R5').replace('R2', 'R6').replace('R3', 'R7'))
    E17_LINK = 'https://github.com/example/factory/pull/4201#issuecomment-5204'

    def reports(self, rounds=('e13', 'e17', 'e22')):
        text = {'e13': 'VERDICT: CHANGES at ' + 'a' * 40 + '\n\n- **R1 [high]** `a.rs:1` (Spec) Old grade.\n',
                'e17': self.E17,
                'e22': 'VERDICT: APPROVE at ' + 'c' * 40 + "\n\nNext: none open. It merges by the project's merge rules.\n"}
        return {'schema': 'closedwiz.review-loops.reports.v1', 'cohort': COHORT['name'],
                'reports': [{'pr': 4201, 'round': r, 'text': text[r]} for r in rounds]}

    def lines(self, ids=('R5', 'R6')):
        rows = R.findings_from_report(self.E17, 4201, self.E17_LINK)
        return dict(FINDINGS, findings=FINDINGS['findings'] + [r for r in rows if r['finding'] in ids])

    def test_line_basis_counts_the_reports_blocking_findings(self):
        u = run(findings=self.lines(), reports=self.reports())['measures']['real_user_path']
        self.assertEqual((5, 4, 1, 2, 0.5, 0.8, ['judgment', 'line']),
                         (u['findings'], u['classified'], u['unknown'], u['user_path'], u['share'], u['coverage'],
                          u['basis']))
        self.assertEqual({'rounds': 3, 'read': 3, 'missing': 0}, u['reports'])

    def test_a_missing_line_classification_stays_unknown(self):
        u = run(findings=self.lines(('R5',)), reports=self.reports())['measures']['real_user_path']
        self.assertEqual((5, 3, 2, 2, 0.666667, 0.6), (u['findings'], u['classified'], u['unknown'], u['user_path'],
                                                     u['share'], u['coverage']))

    def test_a_missing_report_makes_the_share_unavailable(self):
        u = run(findings=FINDINGS, reports=self.reports(('e13', 'e22')))['measures']['real_user_path']
        self.assertEqual({'rounds': 3, 'read': 2, 'missing': 1}, u['reports'])
        self.assertEqual((None, None), (u['share'], u['coverage']))
        none = run(findings=FINDINGS, reports=self.reports())['measures']['real_user_path']
        self.assertEqual((5, 2, 3, 0.4), (none['findings'], none['classified'], none['unknown'], none['coverage']))

    def test_line_classifications_need_an_inventoried_finding(self):
        with self.assertRaises(ValueError):  # no report inventory at all
            run(findings=self.lines())
        with self.assertRaises(ValueError):  # e17's report not supplied
            run(findings=self.lines(), reports=self.reports(('e13', 'e22')))
        unreviewed = dict(FINDINGS, findings=FINDINGS['findings'] + R.findings_from_report(
            self.E17, 4202, 'https://github.com/example/factory/pull/4202#issuecomment-5209'))
        with self.assertRaises(ValueError):  # 4202 has no admitted review round
            run(findings=unreviewed, reports=self.reports())
        wrong = self.lines()
        wrong['findings'][-1] = dict(wrong['findings'][-1], user_path=True)  # R6 has a Risk: line only
        with self.assertRaises(ValueError):
            run(findings=wrong, reports=self.reports())

    def test_reports_bind_to_admitted_rounds_only(self):
        def refused(mutate):
            r = self.reports()
            mutate(r['reports'])
            with self.assertRaises(ValueError):
                run(findings=FINDINGS, reports=r)
        refused(lambda rows: rows.append(dict(rows[1], round='e18')))  # a reposted verdict
        refused(lambda rows: rows.append(dict(rows[1], round='e19')))  # a helper's verdict
        refused(lambda rows: rows.append(dict(rows[1])))  # the same round twice
        refused(lambda rows: rows[1].update(pr=4202))  # an unreviewed PR
        refused(lambda rows: rows[1].update(text=rows[1]['text'].replace('b' * 40, 'c' * 40)))  # another head
        refused(lambda rows: rows[1].update(text=rows[1]['text'].replace('CHANGES', 'APPROVE', 1)))  # other verdict
        refused(lambda rows: rows[1].update(extra=1))


class Watchdog(unittest.TestCase):
    def test_counts_each_flag_restart_and_ask(self):
        w = run(watchdog=WATCHDOG)['measures']['watchdog']
        self.assertEqual({'events': 5, 'heads': 2,
                          'flag': {'no-review-start': 2, 'no-verdict': 1},
                          'restart': {'no-review-start': 1, 'no-verdict': 0},
                          'ask': {'no-review-start': 0, 'no-verdict': 1}, 'outside_cohort': 0}, w)
        empty = run(watchdog='')['measures']['watchdog']
        self.assertEqual(0, empty['events'])

    def test_malformed_event_refuses(self):
        for bad in ('{"schema":"x"}', WATCHDOG.replace('"no-verdict"', '"stalled"', 1),
                    WATCHDOG.replace('"ask"', '"restart-twice"'), WATCHDOG.replace('cccccccc', 'ccc', 1),
                    WATCHDOG.splitlines()[0].replace('10:00:00Z', '10:30:00Z')):
            with self.assertRaises(ValueError):
                run(watchdog=bad)


class Reports(unittest.TestCase):
    OK = (FIX / 'report-ok.md').read_text()

    def problems(self, text):
        return R.check_report(text)

    def test_contract_examples_pass(self):
        self.assertEqual([], self.problems(self.OK))
        approve = ('VERDICT: APPROVE at 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d\n\n'
                   '- **R1 [blocking]** resolved at 9e8d7c6: the export now refuses.\n'
                   '- **R2 [blocking]** withdrawn: the header is never logged.\n'
                   '- **R3 [polish]** Polish issue: #4302.\n\n'
                   "Next: none open. It merges by the project's merge rules.\n")
        self.assertEqual([], self.problems(approve))
        still = approve.replace('APPROVE', 'CHANGES').replace(
            'resolved at 9e8d7c6: the export now refuses.', 'still open after 1 rounds: it still overwrites.').replace(
            "Next: none open. It merges by the project's merge rules.",
            'Next: the orchestrator decides R1: fix once more, or log and merge.')
        self.assertEqual([], self.problems(still))
        final = still.replace('Next: the orchestrator decides R1: fix once more, or log and merge.',
                              'Next: the orchestrator logs R1 and merges, or asks Jake for a security, privacy, '
                              'live, spending or publishing call.')
        self.assertEqual([], self.problems(final))

    def test_blocking_finding_needs_user_path_or_risk(self):
        bare = self.OK.replace('  User path: a cook exports twice in one day; the second export silently '
                               'replaces the first, and the first is lost.\n', '')
        self.assertEqual(['R1: a blocking finding needs a User path: or Risk: line'], self.problems(bare))
        vague = self.OK.replace('Risk: privacy:', 'Risk: style:')
        self.assertEqual(['R2: a blocking finding needs a User path: or Risk: line'], self.problems(vague))

    def test_polish_finding_needs_no_user_path_but_its_issue(self):
        self.assertNotIn('R3', ' '.join(self.problems(self.OK)))
        self.assertEqual(['R3: a polish finding needs its Polish issue: #<n>'],
                         self.problems(self.OK.replace(' Polish issue: #4302.', '')))

    def test_verdict_and_next_follow_the_open_blockers(self):
        self.assertIn('the verdict is CHANGES only while a blocking finding is open',
                      self.problems(self.OK.replace('VERDICT: CHANGES', 'VERDICT: APPROVE')))
        self.assertIn('Next: names no contract state for the open blocking findings',
                      self.problems(self.OK.replace('R1 and R2 once', 'R1 once')))
        self.assertIn('Next: names no contract state for the open blocking findings',
                      self.problems(self.OK.replace('Next: the builder fixes or disputes R1 and R2 once, then one re-check.',
                                                    "Next: none open. It merges by the project's merge rules.")))
        self.assertIn('no Next: line', self.problems(self.OK.split('\nNext:')[0]))
        self.assertIn('no VERDICT line', self.problems(self.OK.replace('VERDICT:', 'Verdict:')))

    def test_todays_worked_example_is_refused(self):
        self.assertEqual(['R1: old grade high; use blocking or polish',
                          'R2: old grade medium; use blocking or polish',
                          'R4: old grade low; use blocking or polish',
                          'Next: names no contract state for the open blocking findings'],
                         self.problems((FIX / 'report-today.md').read_text()))

    def test_cli_exit_codes(self):
        ok = subprocess.run([sys.executable, '-I', HERE / 'review_loops.py', 'check-report', FIX / 'report-ok.md'],
                            capture_output=True, text=True)
        self.assertEqual((0, 'report ok\n', ''), (ok.returncode, ok.stdout, ok.stderr))
        bad = subprocess.run([sys.executable, '-I', HERE / 'review_loops.py', 'check-report', FIX / 'report-today.md'],
                             capture_output=True, text=True)
        self.assertEqual(1, bad.returncode)
        self.assertIn('R1: old grade high', bad.stderr)


class ContractExamples(unittest.TestCase):
    """The contract's own synthetic examples are what the tool accepts, so the two cannot drift."""
    TEXT = (HERE.parent.parent / 'contracts/review-loops.v1.md').read_text()

    def blocks(self, kind):
        return [b.strip() for b in re.findall(rf'```{kind}\n(.*?)\n *```', self.TEXT, re.S)]

    def test_every_record_example_is_accepted(self):
        records = {}
        for b in self.blocks('json'):
            value = json.loads(b)
            records.setdefault(value.get('schema', 'policy'), value)
        self.assertEqual({'policy', R.COHORT, R.FINDINGS, R.REPORTS, R.ESCAPES, R.WATCHDOG}, set(records))
        self.assertEqual(FROZEN, records['policy'])
        inventory = dict(records[R.REPORTS], cohort=COHORT['name'])  # bound to the worked journey's e17
        u = run(findings=FINDINGS, reports=inventory)['measures']['real_user_path']
        self.assertEqual(({'rounds': 3, 'read': 1, 'missing': 2}, 4), (u['reports'], u['findings']))
        cohort = R.read_cohort(records[R.COHORT])
        self.assertEqual(1, len(R.read_findings(records[R.FINDINGS], cohort)))
        self.assertEqual(1, len(R.read_watchdog(json.dumps(records[R.WATCHDOG]))))
        before = run()
        self.assertEqual('triggered', R.compare(before, before, records[R.ESCAPES])['rollback']['result'])

    def test_every_report_line_example_passes_the_check(self):
        md = self.blocks('md')
        lines = [b for b in md if b.startswith('- **R')]
        self.assertEqual(3, len(lines))
        report = ('VERDICT: CHANGES at 4b1f0c9e2d7a5b3c8f6e1d0a9b2c4e7f5a3d1c08\n\n' + '\n'.join(lines) +
                  '\n\nNext: the builder fixes or disputes R1 and R2 once, then one re-check.\n')
        self.assertEqual([], R.check_report(report))
        table = dict(re.findall(r'^\| `([a-z]+)` \|[^|]*\| `(Next: [^`]*)` \|$', self.TEXT, re.M))
        self.assertEqual(set(R.NEXT), set(table))
        for state, line in table.items():
            self.assertRegex(line, '^' + R.NEXT[state] + '$')
        for first in ('Reviewer question:', 'Orchestrator answer:'):
            block = next(b for b in md if b.startswith(first))
            self.assertRegex(block.splitlines()[0], rf'^{first} #[1-9][0-9]* at [0-9a-f]{{40}}$')


class Compare(unittest.TestCase):
    def test_target_and_rollback(self):
        before = run()
        c = R.compare(before, before)
        self.assertEqual('closedwiz.review-loops.compare.v1', c['schema'])
        self.assertEqual(('not met', 3.0, 1.5), (c['target']['result'], c['target']['after_mean'], c['target']['rounds_per_pr']))
        self.assertEqual('not triggered', c['rollback']['result'])
        names = [row['measure'] for row in c['rows']]
        self.assertEqual(['review_rounds', 'first_push_to_merge_hours', 'pr_opened_to_merge_hours',
                          'real_user_path', 'escaped_defects', 'watchdog'], names)
        self.assertEqual((1, 2, 0.333333), tuple(c['rows'][0]['after'][k] for k in ('n', 'unknown', 'coverage')))
        doc = copy.deepcopy(DOC)
        for e in pr(doc, 4201)['events']:
            if e['kind'] == 'verdict' and e['id'] in ('e17', 'e18'):
                e['head'] = 'a' * 40
        self.assertEqual('not met', R.compare(before, run(doc))['target']['result'])  # 2 rounds
        for e in pr(doc, 4201)['events']:
            if e['kind'] == 'verdict' and e['id'] == 'e22':
                e['head'] = 'a' * 40
        self.assertEqual(('met', 1.0), (lambda t: (t['result'], t['after_mean']))(R.compare(before, run(doc))['target']))
        unreviewed = run(cohort=dict(COHORT, prs=[4202]))
        self.assertEqual('unknown', R.compare(before, unreviewed)['target']['result'])

    def test_rollback_trigger(self):
        before = run()
        export = copy.deepcopy(EXPORT)
        export['journey']['measurements'][0]['defects']['events'][0]['attribution'] = 'unattributed'
        lower = run(export=export)
        self.assertEqual(0.0, lower['measures']['escaped_defects']['rate'])
        self.assertEqual('triggered', R.compare(lower, before)['rollback']['result'])
        self.assertEqual('not triggered', R.compare(before, lower)['rollback']['result'])
        immature = run(cohort=dict(COHORT, prs=[4202]))
        self.assertEqual('unknown', R.compare(before, immature)['rollback']['result'])
        escapes = {'schema': 'closedwiz.review-loops.safety-escapes.v1', 'escapes': [
            {'pr': 4202, 'finding': 'R3', 'risk': 'privacy',
             'defect': 'https://github.com/example/factory/issues/4901'}]}
        self.assertEqual('triggered', R.compare(before, lower, escapes)['rollback']['result'])
        self.assertEqual('triggered', R.compare(before, immature, escapes)['rollback']['result'])
        with self.assertRaises(ValueError):
            R.compare(before, lower, dict(escapes, escapes=[dict(escapes['escapes'][0], risk='style')]))

    def test_a_changed_defect_policy_refuses_the_comparison(self):
        # The policy is frozen once for BEFORE and reused unchanged for AFTER, on both sides.
        before = run()
        for side in (0, 1):
            pair = [copy.deepcopy(before), copy.deepcopy(before)]
            pair[side]['measures']['escaped_defects']['policy']['followup_hours'] = 48
            with self.assertRaisesRegex(ValueError, 'frozen defect policy'):
                R.compare(*pair)
        both = copy.deepcopy(before)
        both['measures']['escaped_defects']['policy']['followup_hours'] = 48
        with self.assertRaisesRegex(ValueError, 'frozen defect policy'):
            R.compare(both, both)


class Publish(unittest.TestCase):
    def test_providers_fit_the_existing_rework_and_eb6_slots(self):
        # The suite's evidence links accept a run, not a run attempt URL, so
        # WR6's projection refuses EB6's attempt-pinned CI sources: cite runs.
        doc = copy.deepcopy(DOC)
        doc['sources'] = {k: re.sub(r'/attempts/[0-9]+$', '', v) for k, v in doc['sources'].items()}
        j, o = wire(doc, EXPORT)
        b = R.bench(COHORT, j, o, FINDINGS, None)
        providers = R.project(b, j, source_path='private/evidence/review-loops/before/journeys.json',
                              bench_path='private/evidence/review-loops/before/bench.json',
                              observed_at='2030-01-05T00:00:00Z',
                              evidence=['https://github.com/example/factory/issues/4100'])
        self.assertEqual(['rework', 'eb6'], [p['slot'] for p in providers])
        record = R.S.compose('2030-01-05T00:00:00Z', providers)
        R.SRC.safe_record(record)
        m = {(p['slot'], x['id']): x for p in record['providers'] for x in p['metrics']}
        rounds = m[('rework', 'rounds-per-pr')]
        self.assertEqual((3.0, 3, 1, 3), (rounds['value'], rounds['sample']['numerator'],
                                          rounds['sample']['denominator'], rounds['sample']['expected']))
        self.assertEqual(['pr-4201'], rounds['sample']['identities'])
        self.assertEqual(0.5, m[('rework', 'real-user-path-share')]['value'])
        self.assertEqual(12.0, m[('eb6', 'first-push-to-merge-hours-median')]['value'])
        self.assertEqual(16.0, m[('eb6', 'pr-opened-to-merge-hours-p90')]['value'])
        self.assertEqual(1.0, m[('eb6', 'escaped-defect-rate')]['value'])
        self.assertEqual(1, m[('eb6', 'immature-prs')]['value'])
        # WR6's own metrics survive unchanged beside the new ones.
        self.assertIn(('rework', 'reviewed-coverage'), m)
        for x in m.values():
            self.assertNotEqual('known', x['state'])

    def test_a_one_in_three_defect_rate_projects_exactly(self):
        # R1: three mature PRs, one with an attributable defect; 1/3 has no six-decimal form.
        journey = (HERE / 'fixtures/rework/journeys.json').read_bytes()
        outcomes = (FIX / 'rework-outcomes.json').read_bytes()
        cohort = {'schema': 'closedwiz.review-loops.cohort.v1', 'name': 'rework', 'since': '2030-01-02T08:00:00Z',
                  'until': '2030-01-03T08:00:00Z', 'base': 'main', 'read_at': '2030-01-06T00:00:00Z',
                  'prs': [4201, 4202, 4203]}
        b = R.bench(cohort, journey, outcomes, {'schema': 'closedwiz.review-loops.findings.v1', 'cohort': 'rework',
                                                'findings': []})
        self.assertEqual((3, 1), (b['measures']['escaped_defects']['known_mature_prs'],
                                  b['measures']['escaped_defects']['affected_mature_prs']))
        providers = R.project(b, journey, source_path='private/evidence/review-loops/before/journeys.json',
                              bench_path='private/evidence/review-loops/before/bench.json',
                              observed_at='2030-01-06T00:00:00Z',
                              evidence=['https://github.com/example/factory/issues/4100'])
        rate = next(x for p in providers for x in p['metrics'] if x['id'] == 'escaped-defect-rate')
        self.assertEqual((1 / 3, 1, 3), (rate['value'], rate['sample']['numerator'], rate['sample']['denominator']))

    def test_bench_cli_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            t = Path(temp)
            j, o = wire(DOC, EXPORT)
            (t / 'journeys.json').write_bytes(j)
            (t / 'outcomes.json').write_bytes(o)
            r = subprocess.run([sys.executable, '-I', HERE / 'review_loops.py', 'bench', '--cohort', FIX / 'cohort.json',
                                '--journey', t / 'journeys.json', '--outcomes', t / 'outcomes.json',
                                '--findings', FIX / 'findings.json'], capture_output=True, text=True)
            self.assertEqual((0, ''), (r.returncode, r.stderr))
            out = json.loads(r.stdout)
            self.assertEqual(run(), out)
            self.assertEqual(hashlib.sha256(j).hexdigest(), out['inputs']['journey'])
            (t / 'outcomes.json').write_text(json.dumps({'journey': 1, 'sources': {}, 'defect_policy': FROZEN}))
            r = subprocess.run([sys.executable, '-I', HERE / 'review_loops.py', 'bench', '--cohort', FIX / 'cohort.json',
                                '--journey', t / 'journeys.json', '--outcomes', t / 'outcomes.json',
                                '--findings', FIX / 'findings.json'], capture_output=True, text=True)
            self.assertEqual((1, '', 'refused: invalid review-loops input\n'), (r.returncode, r.stdout, r.stderr))


if __name__ == '__main__':
    unittest.main()
