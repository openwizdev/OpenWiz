#!/usr/bin/env python3
"""Collection/checkpoint core proofs only; fake sources and outcomes, no API key."""
import contextlib
import copy
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(1, str(HERE.parent))
import collect as C
import run as W
import cases as E1

WEEK = '2030-01-07'
NEXT = '2030-01-14'
SKILLS = ['build-ticket']


def candidate(cid='i9001-weekly-mistake'):
    return {'schema': 'openwiz.skills-eval.case.v1', 'id': cid,
            'skills': SKILLS, 'category': 'incident',
            'brief': 'Read skills/build-ticket/SKILL.md. A synthetic check is pending.',
            'world': {}, 'expect': {'actions': [], 'allow': [],
                'forbid': [{'run': 'sleep'}], 'end': 'end_turn',
                'final': 'Facts: checks are pending. End the turn.'},
            'controls': {'pass': [{'why': 'Ends the turn.', 'events': [],
                'judgment': {'verdict': 'pass', 'reason': 'Waits.'}}],
                'fail': [{'why': 'Waits awake.', 'events': [['read', 'sleep 300']],
                          'reason': 'forbidden'}]}}


def record(n=9001, day='2030-01-08', body='synthetic mistake', *, source='issue_comments'):
    location, anchor = {'issue_comments': ('issues', 'issuecomment-'),
                        'review_comments': ('pull', 'discussion_r'),
                        'reviews': ('pull', 'pullrequestreview-')}[source]
    return {'id': n, 'updated_at': day + 'T12:00:00Z', 'body': body,
            'url': f'https://github.com/example/work/{location}/4901#{anchor}{n}'}


class FakeSources:
    def __init__(self, pages=None):
        self.pages = pages or {}
        self.calls = []

    def read(self, source, week, page):
        self.calls.append((source, week, page))
        value = self.pages.get((source, page), {'items': [], 'next_page': None})
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


def synthesize(item):
    if item['body'] == 'ordinary synthetic progress':
        return None
    return {'incident': 'pending-check-watcher', 'case': candidate()}


def outcome(cases_hash, ids=('i9001-weekly-mistake',)):
    score = {'schema': 'openwiz.skills-eval.score.v1',
        'settings_hash': '17e0d9c946d62dc16dc35faed810091019da4c0bd5a5e21e3ac9ba82d2b5491c',
        'cases_hash': cases_hash, 'code_hash': 'b' * 64, 'schema_hash': 'c' * 64,
        'revision': {'commit': 'd' * 40, 'tree': 'e' * 40},
        'suite_pass': True, 'runs': len(ids) * 2, 'passed': len(ids) * 2,
        'cost_usd': 0, 'rows': [{'case': cid, 'repeat': rep, 'pass': True,
            'reasons': [], 'details': [], 'cost_usd': 0, 'stop': 'end_turn'}
            for cid in ids for rep in (1, 2)]}
    return {'mode': 'fake', 'settings': {'repeats': 2}, 'baseline': copy.deepcopy(score), 'result': score,
        'results_set': 'synthetic-results/week', 'token_report': 'synthetic-tokens/week.json'}


class CollectionCore(unittest.TestCase):
    def test_collect_all_sources_pages_and_deduplicate(self):
        source = FakeSources({('issue_comments', 1): {'items': [record()], 'next_page': 2},
            ('issue_comments', 2): {'items': [record(), record(9002)], 'next_page': None},
            ('reviews', 1): {'items': [record(9003, source='reviews')], 'next_page': None},
            ('review_comments', 1): {'items': [record(9004, body='ordinary synthetic progress', source='review_comments')],
                                      'next_page': None}})
        result = C.collect(WEEK, source.read, synthesize, SKILLS)
        self.assertEqual(result['cases'], {'i9001-weekly-mistake': candidate()})
        self.assertEqual(result['incidents'], {'pending-check-watcher': 'i9001-weekly-mistake'})
        self.assertEqual(result['provenance']['i9001-weekly-mistake']['links'],
                         [record()['url'], record(9002)['url'], record(9003, source='reviews')['url']])
        self.assertEqual(len(source.calls), 4)
        self.assertEqual(set(result['sources']), set(C.SOURCES))
        self.assertNotIn('https://', json.dumps(result['cases']))
        self.assertEqual(E1.problems(candidate(), SKILLS), [])

    def test_week_boundaries_and_irrelevant_comments(self):
        source = FakeSources({('issue_comments', 1): {'items': [
            record(day='2030-01-06'), record(9002, day=NEXT),
            record(9003, body='ordinary synthetic progress')], 'next_page': None}})
        self.assertEqual(C.collect(WEEK, source.read, synthesize, SKILLS)['cases'], {})
        # A moving page can return conflicting copies on opposite week sides.
        for days in (('2030-01-08', NEXT), (NEXT, '2030-01-08')):
            source = FakeSources({('issue_comments', 1): {
                'items': [record(day=days[0])], 'next_page': 2},
                ('issue_comments', 2): {'items': [record(day=days[1])], 'next_page': None}})
            with self.subTest(days=days), self.assertRaises(ValueError):
                C.collect(WEEK, source.read, synthesize, SKILLS)

    def test_source_links_bind_kind_and_identity(self):
        valid = {
            'issue_comments': ['https://github.com/example/work/issues/4901#issuecomment-9001',
                               'https://github.com/example/work/pull/4901#issuecomment-9001'],
            'review_comments': ['https://github.com/example/work/pull/4901#discussion_r9001'],
            'reviews': ['https://github.com/example/work/pull/4901#pullrequestreview-9001']}
        for source, urls in valid.items():
            for url in urls:
                item = dict(record(), url=url)
                pages = FakeSources({(source, 1): {'items': [item], 'next_page': None}})
                result = C.collect(WEEK, pages.read, synthesize, SKILLS)
                self.assertEqual(result['provenance']['i9001-weekly-mistake']['links'], [url])
            bad_urls = [url.replace('9001', '9999') for url in urls]
            bad_urls += [url for other, links in valid.items() if other != source for url in links]
            if source != 'issue_comments':
                bad_urls.append(urls[0].replace('/pull/', '/issues/'))
            for url in bad_urls:
                pages = FakeSources({(source, 1): {'items': [dict(record(), url=url)], 'next_page': None}})
                with self.subTest(source=source, url=url), self.assertRaises(ValueError):
                    C.collect(WEEK, pages.read, synthesize, SKILLS)

    def test_refuses_unsafe_or_conflicting_candidate(self):
        for change in ('url', 'invalid', 'conflict'):
            def bad(item):
                c = candidate()
                if change == 'url':
                    c['brief'] += ' ' + item['url']
                if change == 'invalid':
                    c['controls']['fail'] = []
                if change == 'conflict' and item['id'] == 9002:
                    c['brief'] += ' Different behavior.'
                return {'incident': 'one-incident', 'case': c}
            with self.subTest(change=change), self.assertRaises(ValueError):
                C.collect(WEEK, FakeSources({('issue_comments', 1): {
                    'items': [record(), record(9002)], 'next_page': None}}).read, bad, SKILLS)


class CheckpointCore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.cases = self.root / 'base-cases'
        self.cases.mkdir()
        self.provenance = None
        self.source = FakeSources({('issue_comments', 1): {'items': [record()], 'next_page': None}})

    def tick(self, week=WEEK, **kw):
        return W.tick(self.state, week, cases_dir=self.cases, skills=SKILLS,
                      provenance=self.provenance, read_page=self.source.read, synthesize=synthesize, **kw)

    def prepared(self):
        r = self.tick()
        self.assertEqual(r['status'], 'prepared')
        return r

    def finish(self):
        r = self.prepared()
        return self.tick(evidence=outcome(r['cases_hash']))

    def saved(self):
        return json.loads((self.state / 'state.json').read_text())

    def test_checkpoint_and_injected_results(self):
        snapshot = self.cases / 'i9002-snapshot.json'
        original_bytes = (json.dumps(candidate('i9002-snapshot'), indent=1) + '\n').replace('\n', '\r\n').encode('utf-8')
        snapshot.write_bytes(original_bytes)
        self.provenance = {'schema': 'openwiz.skills-eval.provenance.v1',
            'cases': {'i9002-snapshot': {'links': ['https://github.com/example/work/issues/4902']}},
            'checkpoints': []}
        prepared = self.prepared()
        # E1 hashes the original bytes, independently of the weekly state reader.
        exported = self.root / 'export'
        exported.mkdir()
        (exported / snapshot.name).write_bytes(original_bytes)
        new_case = self.saved()['pending']['files']['i9001-weekly-mistake.json']
        (exported / 'i9001-weekly-mistake.json').write_bytes(new_case.encode('utf-8'))
        expected_hash = E1.cases_hash(exported)
        self.assertEqual(prepared['cases_hash'], expected_hash)
        state_before = (self.state / 'state.json').read_bytes()
        snapshot.write_bytes(original_bytes.replace(b'\r\n', b'\n'))
        self.assertEqual(self.tick()['status'], 'gap')
        self.assertEqual((self.state / 'state.json').read_bytes(), state_before)
        snapshot.write_bytes(original_bytes)
        r = self.tick(evidence=outcome(expected_hash, ('i9001-weekly-mistake', 'i9002-snapshot')))
        self.assertEqual(r['status'], 'complete')
        s = self.saved()
        cp = s['provenance']['checkpoints'][0]
        self.assertEqual(cp, {'week': WEEK, 'case_ids': ['i9001-weekly-mistake'],
            'cases_hash': r['cases_hash'], 'results_set': 'synthetic-results/week',
            'token_report': 'synthetic-tokens/week.json'})
        self.assertEqual(s['successful_week'], WEEK)
        self.assertEqual(s['source_checkpoints'], s['pending']['collection']['sources'])
        self.assertIsNone(r['saving'])
        self.assertEqual(r['evidence_class'], 'fixture test')
        # E1's exact sorted filename/byte hashing, not a parallel JSON hash.
        self.assertEqual(s['case_files'][snapshot.name].encode('utf-8'), original_bytes)
        for name, text in s['case_files'].items():
            (exported / name).write_bytes(text.encode('utf-8'))
        self.assertEqual(r['cases_hash'], E1.cases_hash(exported))
        self.assertEqual(self.tick(), r)

    def test_defaults_do_nothing(self):
        self.assertEqual(W.tick(self.state, WEEK)['status'], 'not run')
        self.assertFalse(self.state.exists())

    def test_unchanged_week(self):
        self.finish()
        self.source = FakeSources()
        result = self.tick(NEXT)
        self.assertEqual(result['status'], 'unchanged')
        self.assertEqual(result['case_ids'], [])
        self.assertIsNone(result['saving'])
        self.assertEqual(len(self.saved()['provenance']['checkpoints']), 2)
        self.assertEqual(self.saved()['successful_week'], NEXT)

    def test_duplicate_incident_next_week(self):
        self.finish()
        self.source = FakeSources({('reviews', 1): {'items': [record(9010, NEXT, source='reviews')], 'next_page': None}})
        r = self.tick(NEXT)
        self.assertEqual(r['status'], 'unchanged')
        self.assertEqual(r['case_ids'], [])
        self.assertEqual(len(self.saved()['case_files']), 1)
        self.assertIn(record(9010, NEXT, source='reviews')['url'],
                      self.saved()['provenance']['cases']['i9001-weekly-mistake']['links'])
        c = candidate()
        (self.cases / (c['id'] + '.json')).write_text(self.saved()['case_files'][c['id'] + '.json'])
        self.provenance = {'schema': 'openwiz.skills-eval.provenance.v1',
            'cases': {c['id']: {'links': [record()['url']]}}, 'checkpoints': []}
        self.source = FakeSources()
        self.assertEqual(self.tick('2030-01-21')['status'], 'unchanged')
        self.assertEqual(self.saved()['provenance']['cases'][c['id']]['links'],
                         [record()['url'], record(9010, NEXT, source='reviews')['url']])

    def test_failed_or_incomplete_read_preserves_success(self):
        self.finish()
        original = self.saved()
        for bad in (OSError('private payload must not be persisted'),
                    {'items': [], 'next_page': 2}, {'items': []},
                    {'items': 'truncated', 'next_page': None},
                    {'items': [record(9009, NEXT)], 'next_page': 3},
                    {'items': [record(9009, '2030-01-21')], 'next_page': None},
                    {'items': [record(9010, NEXT)], 'next_page': 4}):
            with self.subTest(bad=type(bad).__name__):
                self.source = FakeSources({('issue_comments', 1): {
                    'items': [record(9009, NEXT)], 'next_page': 2}, ('issue_comments', 2): bad})
                r = self.tick(NEXT)
                self.assertEqual(r['status'], 'gap')
                self.assertIsNone(r['saving'])
                self.assertEqual(self.saved(), original)
                self.assertNotIn('private payload', json.dumps(r))

    def test_crash_resume(self):
        prepared = self.prepared()
        calls = len(self.source.calls)
        # Durable preparation survives a crash before committing completion.
        with mock.patch.object(W, 'write_json', side_effect=OSError('synthetic crash')):
            with self.assertRaises(OSError):
                self.tick(evidence=outcome(prepared['cases_hash']))
        self.assertIsNone(self.saved()['successful_week'])
        result = self.tick(evidence=outcome(prepared['cases_hash']))
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(len(self.source.calls), calls)
        self.assertEqual(len(self.saved()['provenance']['checkpoints']), 1)
        self.assertEqual(self.tick(), result)

    def test_changed_cases_refuses_old_baseline(self):
        old = self.finish()['cases_hash']
        c = candidate('i9002-new-case')
        (self.cases / (c['id'] + '.json')).write_text(json.dumps(c) + '\n')
        self.provenance = {'schema': 'openwiz.skills-eval.provenance.v1',
            'cases': {c['id']: {'links': ['https://github.com/example/work/issues/4920']}},
            'checkpoints': []}
        self.source = FakeSources()
        prepared = self.tick(NEXT)
        self.assertEqual(prepared['status'], 'prepared')
        self.assertNotEqual(prepared['cases_hash'], old)
        bad = outcome(prepared['cases_hash'], ('i9001-weekly-mistake', 'i9002-new-case'))
        bad['baseline']['cases_hash'] = old
        self.assertEqual(self.tick(NEXT, evidence=bad)['status'], 'gap')
        self.assertEqual(self.saved()['successful_week'], WEEK)
        good = outcome(prepared['cases_hash'], ('i9001-weekly-mistake', 'i9002-new-case'))
        done = self.tick(NEXT, evidence=good)
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(done['case_ids'], ['i9002-new-case'])
        self.assertEqual(set(self.saved()['provenance']['cases']),
                         {'i9001-weekly-mistake', 'i9002-new-case'})

    def test_invalid_outcomes(self):
        p = self.prepared()
        for change in ('failed', 'missing', 'duplicate', 'hash', 'repeat', 'real', 'unknown'):
            e = outcome(p['cases_hash'])
            if change == 'failed': e['result']['suite_pass'] = False
            if change == 'missing': e['result']['rows'].pop()
            if change == 'duplicate': e['result']['rows'][1] = e['result']['rows'][0]
            if change == 'hash': e['result']['settings_hash'] = 'f' * 64
            if change == 'repeat': e['result']['rows'][1]['repeat'] = True
            if change == 'real': e['mode'] = 'live'
            if change == 'unknown': e['experiment_stage'] = 'invented'
            with self.subTest(change=change):
                self.assertEqual(self.tick(evidence=e)['status'], 'gap')
                self.assertIsNone(self.saved()['successful_week'])

    def test_frozen_repeats_and_completion_receipts(self):
        p = self.prepared()
        for change in ('one-repeat', 'stop', 'reasons'):
            e = outcome(p['cases_hash'])
            if change == 'one-repeat':
                for key in ('baseline', 'result'):
                    e[key]['rows'] = e[key]['rows'][:1]
                    e[key]['runs'] = e[key]['passed'] = 1
            if change == 'stop': e['result']['rows'][0]['stop'] = 'error'
            if change == 'reasons': e['result']['rows'][0]['reasons'] = ['incomplete']
            with self.subTest(change=change):
                self.assertEqual(self.tick(evidence=e)['status'], 'gap')
                self.assertIsNone(self.saved()['successful_week'])

    def test_invalid_success_receipt(self):
        self.finish()
        s = self.saved()
        s['provenance']['checkpoints'] = []
        (self.state / 'state.json').write_text(json.dumps(s))
        self.assertEqual(self.tick()['status'], 'gap')

    def test_invalid_state_and_concurrent_run_are_refused(self):
        self.prepared()
        import fcntl
        with (self.state / 'lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.tick()['status'], 'gap')
        (self.state / 'state.json').write_text('{"schema":"bad","schema":"duplicate"}')
        self.assertEqual(self.tick()['status'], 'gap')

    def test_no_process_or_network(self):
        with mock.patch.object(socket, 'socket', side_effect=AssertionError('network')), \
                mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('process')):
            self.finish()



# ---- #1363 integration proofs: the one weekly process around #2236's core. ----

def failing(score, cid='i9001-weekly-mistake'):
    """A synthetic old-skill baseline whose new case fails every repeat."""
    score = copy.deepcopy(score)
    for row in score['rows']:
        if row['case'] == cid:
            row.update({'pass': False, 'reasons': ['missing-action']})
    score['passed'] = sum(r['pass'] for r in score['rows'])
    score['suite_pass'] = False
    return score


def stage(status, n=1):
    if status == 'not_run':
        return {'status': 'not_run', 'artifact_hash': None, 'source': None, 'at': None}
    return {'status': status, 'artifact_hash': f'{n:064x}', 'source': 's1',
            'at': f'2030-01-0{n}T12:00:00Z'}


def experiment(tag='cf4-syn-a', h='a' * 64, **stages):
    names = ('research', 'cf4', 'replay', 'live')
    return {'tag': tag, 'experiment_hash': h,
            'stages': {k: stage(stages.get(k, 'not_run'), i + 1) for i, k in enumerate(names)},
            'sources': {'s1': 'https://github.com/example/work/issues/4950'}}


class Gate:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        answer = self.answers.pop(0) if self.answers else 'allowed'
        if isinstance(answer, Exception):
            raise answer
        return answer


class Router:
    def __init__(self, fail=()):
        self.sent, self.fail = [], set(fail)

    def __call__(self, action):
        if action['key'] in self.fail:
            raise OSError('synthetic lost reply')
        self.sent.append(copy.deepcopy(action))


class Issue:
    """A fake GitHub issue's comments: a complete read and a post that can lose its reply."""

    def __init__(self, lose_reply=False, read_fails=False):
        self.comments, self.lose_reply, self.read_fails = [], lose_reply, read_fails

    def read(self):
        if self.read_fails:
            raise OSError('synthetic unreadable comments')
        return copy.deepcopy(self.comments)

    def post(self, body):
        n = 6800000001 + len(self.comments) if not self.comments else max(c['id'] for c in self.comments) + 1
        self.comments.append({'id': n, 'body': body})
        if self.lose_reply:
            raise OSError('synthetic lost reply')
        return str(n)


class WeeklyFixture(unittest.TestCase):
    """Shared state for the weekly-process proofs; holds no test of its own."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / 'state'
        self.cases = self.root / 'cases'
        self.cases.mkdir()
        self.source = FakeSources({('issue_comments', 1): {'items': [record()], 'next_page': None}})
        self.route = Router()

    def week(self, week=WEEK, *, gate=None, **kw):
        return W.weekly(self.state, week, cases_dir=self.cases, provenance=None, skills=SKILLS,
                        read_page=self.source.read, synthesize=synthesize,
                        start_gate=gate or Gate([]), route=self.route, **kw)

    def ledger(self):
        return json.loads((self.state / 'weekly.json').read_text())

    def to_complete(self):
        prepared = self.week()
        ev = outcome(prepared['cases_hash'])
        ev['baseline'] = failing(ev['baseline'])
        done = self.week(evidence=ev)
        self.assertEqual(done['status'], 'complete')
        return done, ev


class WeeklyProcess(WeeklyFixture):
    """Claims C1-C8 in private/evidence/skills-eval/e3/proof-plan.md."""

    # C6: failed eval routes fixes and never a cut; fixes precede the passing result.
    def test_failed_baseline_routes_fix_not_cut(self):
        prepared = self.week()
        ev = outcome(prepared['cases_hash'])
        baseline = {'settings': ev['settings'], 'score': failing(ev['baseline'])}
        r = self.week(baseline=baseline, cuts={'build-ticket': ev['result']})
        self.assertEqual(r['status'], 'needs fixes')
        self.assertEqual(r['actions'], {f'{WEEK}:fix:build-ticket': 'routed'})
        self.assertEqual([a['kind'] for a in self.route.sent], ['fix'])
        self.assertIn('cuts wait for a passing result at this cases hash', r['gaps'])
        self.assertIsNone(self.ledger()['weeks'][WEEK].get('cuts'))
        self.assertIsNone(json.loads((self.state / 'state.json').read_text())['successful_week'])

    # C6: a failed cut is rejected and recorded; a passing cut routes one ticket.
    def test_cut_results_after_complete_week(self):
        done, ev = self.to_complete()
        bad = failing(ev['result'])
        r = self.week(cuts={'build-ticket': bad})
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['rejected_cuts'], ['build-ticket'])
        self.assertNotIn(f'{WEEK}:cut:build-ticket', r['actions'])
        r = self.week(cuts={'build-ticket': ev['result']})
        self.assertEqual(r['rejected_cuts'], ['build-ticket'])
        self.assertEqual(r['actions'][f'{WEEK}:cut:build-ticket'], 'routed')
        # A cut scored on other cases is never compared with this week's eval.
        other = copy.deepcopy(ev['result'])
        other['cases_hash'] = 'f' * 64
        self.assertEqual(self.week(cuts={'build-ticket': other})['status'], 'gap')

    # C7: blocked starts stay pending, never done, and route once when allowed.
    def test_deferred_start_preserved_then_routed_once(self):
        prepared = self.week()
        ev = outcome(prepared['cases_hash'])
        baseline = {'settings': ev['settings'], 'score': failing(ev['baseline'])}
        for answer in ('deferred', 'unknown', OSError('unreadable credit state')):
            r = self.week(baseline=baseline, gate=Gate([answer]))
            self.assertEqual(r['actions'], {f'{WEEK}:fix:build-ticket': 'deferred'})
            self.assertTrue(any('credit-aware start rule' in g for g in r['gaps']))
            self.assertEqual(self.route.sent, [])
        self.assertEqual(self.week(baseline=baseline)['actions'][f'{WEEK}:fix:build-ticket'], 'routed')
        self.week(baseline=baseline)
        self.assertEqual(len(self.route.sent), 1)

    # C4: resume never repeats an action, including one whose outcome is unknown.
    def test_resume_without_duplicate_actions(self):
        prepared = self.week()
        ev = outcome(prepared['cases_hash'])
        baseline = {'settings': ev['settings'], 'score': failing(ev['baseline'])}
        # A crash before the ledger durably records routing sends nothing.
        with mock.patch.object(W, 'write_json', side_effect=OSError('synthetic crash')):
            with self.assertRaises(OSError):
                self.week(baseline=baseline)
        self.assertEqual(self.route.sent, [])
        self.route = Router(fail={f'{WEEK}:fix:build-ticket'})
        r = self.week(baseline=baseline)
        self.assertEqual(r['actions'][f'{WEEK}:fix:build-ticket'], 'unresolved')
        self.route = Router()
        r = self.week(baseline=baseline)
        self.assertEqual(r['actions'][f'{WEEK}:fix:build-ticket'], 'unresolved')
        self.assertEqual(self.route.sent, [])
        self.assertTrue(any('verify on GitHub' in g for g in r['gaps']))

    # C1/C5: owner stage references are retained; missing outcomes are unobserved.
    def test_stage_references_retained_and_unobserved(self):
        r = self.week(experiments=[experiment(research='pass')])
        self.assertEqual(r['stages']['cf4-syn-a'], {'research': 'pass', 'cf4': 'unobserved',
                                                    'replay': 'unobserved', 'live': 'unobserved'})
        self.assertEqual(r['tokens'], 'unobserved')
        # A later tick without a summary keeps the earlier references.
        r = self.week()
        self.assertEqual(r['stages']['cf4-syn-a']['research'], 'pass')
        self.assertEqual(self.ledger()['experiments']['cf4-syn-a']['stages']['research'], stage('pass', 1))
        self.assertNotIn('https://', json.dumps(r))

    # C2: no replay/live proposal from an incomplete or failed predecessor.
    def test_premature_promotion_refused(self):
        r = self.week(experiments=[experiment(research='fail', cf4='pass')])
        self.assertIn('cf4-syn-a: replay blocked: research is fail', r['blocked'])
        self.assertIn('cf4-syn-a: live blocked: research is fail', r['blocked'])
        self.assertEqual([a for a in r['actions'] if 'ready' in a], [])
        bad = experiment('cf4-syn-b', 'b' * 64, research='pass', cf4='partial', replay='pass')
        before = self.ledger()
        self.assertEqual(self.week(experiments=[bad])['status'], 'gap')
        self.assertEqual(self.ledger(), before)
        ok = experiment('cf4-syn-c', 'c' * 64, research='pass', cf4='pass')
        r = self.week(experiments=[ok])
        self.assertEqual(r['actions']['cf4-syn-c:replay-ready'], 'routed')
        self.assertIn('cf4-syn-c: live blocked: replay is unobserved', r['blocked'])
        self.assertEqual([a['kind'] for a in self.route.sent], ['stage-ready'])

    # C3: a running arm is frozen; a new candidate is a new experiment.
    def test_frozen_arm_mutation_refused(self):
        self.week(experiments=[experiment(research='pass')])
        before = self.ledger()
        for changed in (experiment(h='d' * 64, research='pass'),
                        experiment(research='fail'), experiment()):
            with self.subTest(changed=changed['experiment_hash'][:1] + changed['stages']['research']['status']):
                self.assertEqual(self.week(experiments=[changed])['status'], 'gap')
                self.assertEqual(self.ledger(), before)
        r = self.week(experiments=[experiment(research='pass', cf4='partial')])
        self.assertEqual(r['stages']['cf4-syn-a']['cf4'], 'partial')
        before = self.ledger()
        self.assertEqual(self.week(experiments=[experiment(research='pass')])['status'], 'gap')
        self.assertEqual(self.ledger(), before)

    # C6: an unchanged week re-tries cuts on the carried-forward result, never old fixes.
    def test_unchanged_week_retries_cuts_without_old_fixes(self):
        done, ev = self.to_complete()
        self.assertEqual(done['actions'], {f'{WEEK}:fix:build-ticket': 'routed'})
        self.source = FakeSources()
        r = self.week(NEXT, cuts={'build-ticket': ev['result']})
        self.assertEqual(r['status'], 'unchanged')
        self.assertEqual(r['actions'], {f'{NEXT}:cut:build-ticket': 'routed'})
        self.assertEqual([a['kind'] for a in self.route.sent], ['fix', 'cut'])

    def test_invalid_stage_summary_refused(self):
        for change in ('status', 'source', 'hash', 'id'):
            e = experiment(research='pass')
            if change == 'status': e['stages']['research']['status'] = 'done'
            if change == 'source': e['stages']['research']['source'] = 's9'
            if change == 'hash': e['stages']['research']['artifact_hash'] = None
            if change == 'id': e['tag'] = 'thr_synthabc'
            with self.subTest(change=change):
                self.assertEqual(self.week(experiments=[e])['status'], 'gap')
        self.assertFalse((self.state / 'weekly.json').exists())

    # C8: one dry-run week, sanitized, fake tools only, eval -> fix -> cut evidence.
    def test_dry_run_report(self):
        out = self.root / 'out'
        with mock.patch.object(socket, 'socket', side_effect=AssertionError('network')), \
                mock.patch.object(subprocess, 'Popen', side_effect=AssertionError('process')):
            report = W.dry_run(out)
        self.assertEqual(report['status'], 'complete')
        self.assertEqual(report['evidence_class'], 'fixture test')
        self.assertIsNone(report['saving'])
        kinds = [k.split(':')[1] for k in report['actions'] if k.count(':') == 2]
        self.assertEqual(sorted(kinds), ['cut', 'fix'])
        self.assertEqual(report['rejected_cuts'], ['review-ticket'])
        text = (out / 'report.md').read_text()
        for word in ('Cases added', 'Gaps', 'Tokens', 'Revisions', 'Pass/fail', 'unobserved'):
            self.assertIn(word, text)
        for leak in ('https://', 'thr_', 'synthetic mistake'):
            self.assertNotIn(leak, text + (out / 'report.json').read_text())
        self.assertEqual(json.loads((out / 'report.json').read_text()), report)

    def test_cli_dry_run_and_loop_definition(self):
        out = self.root / 'cli'
        env = {'PATH': '/usr/bin:/bin'}
        done = subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), 'dry-run', '--out', str(out)],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout, (out / 'report.md').read_text())
        prompt = self.root / 'prompt.txt'
        done = subprocess.run([sys.executable, '-I', str(HERE / 'run.py'), 'loop-definition',
                               '--prompt-file', str(prompt)], capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(json.loads(done.stdout), W.loop_argv(prompt))
        self.assertEqual(prompt.read_text(), W.LOOP['prompt'] + '\n')

    def test_render_refuses_identifiers(self):
        report = W.dry_run(self.root / 'out')
        report['gaps'].append('see thr_synthabc')
        with self.assertRaises(ValueError):
            W.render(report)


class ReviewRound1(WeeklyFixture):
    """PR review round 1 (R1-R5): proofs written before their fixes."""

    def test_r1_deferred_work_retried_without_fresh_inputs(self):
        # Cross-week: a cut deferred in W routes once in an unchanged W+1 with no cut input.
        done, ev = self.to_complete()
        r = self.week(cuts={'build-ticket': ev['result']}, gate=Gate(['deferred']))
        self.assertEqual(r['actions'][f'{WEEK}:cut:build-ticket'], 'deferred')
        self.source = FakeSources()
        r = self.week(NEXT)
        self.assertEqual(r['status'], 'unchanged')
        self.assertEqual(r['actions'], {f'{WEEK}:cut:build-ticket': 'routed'})
        self.week(NEXT)
        self.assertEqual([a['key'] for a in self.route.sent],
                         [f'{WEEK}:fix:build-ticket', f'{WEEK}:cut:build-ticket'])

    def test_r1_same_week_resume_without_baseline(self):
        prepared = self.week()
        ev = outcome(prepared['cases_hash'])
        baseline = {'settings': ev['settings'], 'score': failing(ev['baseline'])}
        self.assertEqual(self.week(baseline=baseline, gate=Gate(['deferred']))['actions'],
                         {f'{WEEK}:fix:build-ticket': 'deferred'})
        gate = Gate([])
        r = self.week(gate=gate)
        self.assertEqual(r['actions'], {f'{WEEK}:fix:build-ticket': 'routed'})
        self.assertEqual(gate.calls, 1)
        self.week()
        self.assertEqual(len(self.route.sent), 1)
        # Unresolved or routed effects are never retried blindly.
        self.assertEqual(self.ledger()['actions'][f'{WEEK}:fix:build-ticket']['status'], 'routed')

    def test_r2_cut_needs_comparable_code_and_schema(self):
        done, ev = self.to_complete()
        for key in ('code_hash', 'schema_hash'):
            cut = copy.deepcopy(ev['result'])
            cut[key] = 'f' * 64
            with self.subTest(key=key):
                before = self.ledger()
                self.assertEqual(self.week(cuts={'build-ticket': cut})['status'], 'gap')
                self.assertEqual(self.ledger(), before)
                self.assertIsNone(self.ledger()['weeks'][WEEK]['cuts'])
        self.assertEqual([a['kind'] for a in self.route.sent], ['fix'])

    def test_r4_queued_handoff_survives_and_needs_confirmation(self):
        self.route = lambda action: 'queued'
        ok = experiment('cf4-syn-c', 'c' * 64, research='pass', cf4='pass')
        r = self.week(experiments=[ok])
        self.assertEqual(r['actions'], {'cf4-syn-c:replay-ready': 'queued'})
        self.assertTrue(any('awaiting handoff' in g for g in r['gaps']))
        calls = []
        self.route = calls.append
        r = self.week()  # a fresh sandbox keeps only state.json and weekly.json
        self.assertEqual(r['actions'], {'cf4-syn-c:replay-ready': 'queued'})
        self.assertEqual(calls, [])
        self.assertEqual(W.pending(self.state), [{'key': 'cf4-syn-c:replay-ready', 'kind': 'stage-ready',
                                                  'tag': 'cf4-syn-c', 'stage': 'replay', 'status': 'queued'}])
        issue = Issue()
        self.assertEqual(W.handoff(self.state, 'cf4-syn-c:replay-ready', issue.read, issue.post), '6800000001')
        self.assertEqual(self.ledger()['actions']['cf4-syn-c:replay-ready']['receipt'], '6800000001')
        self.assertEqual(self.week()['actions'], {'cf4-syn-c:replay-ready': 'routed'})
        self.assertEqual(W.pending(self.state), [])
        for key in ('cf4-syn-c:replay-ready', 'unknown-key'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                W.handoff(self.state, key, issue.read, issue.post)
        self.assertEqual(len(issue.comments), 1)

    def queued(self):
        self.route = lambda action: 'queued'
        self.week(experiments=[experiment('cf4-syn-c', 'c' * 64, research='pass', cf4='pass')])
        return 'cf4-syn-c:replay-ready'

    def test_r11_lost_reply_never_posts_twice(self):
        key = self.queued()
        issue = Issue(lose_reply=True)
        with self.assertRaises(OSError):
            W.handoff(self.state, key, issue.read, issue.post)
        self.assertEqual(len(issue.comments), 1)  # GitHub kept the comment; the reply was lost
        self.assertEqual(self.ledger()['actions'][key]['status'], 'unresolved')
        # A fresh sandbox finds the marker on GitHub and records it; no second post.
        issue.lose_reply = False
        self.assertEqual(W.handoff(self.state, key, issue.read, issue.post), '6800000001')
        self.assertEqual(len(issue.comments), 1)
        self.assertEqual(self.ledger()['actions'][key]['status'], 'routed')

    def test_r11_unreadable_source_posts_nothing(self):
        key = self.queued()
        issue = Issue(read_fails=True)
        for status in ('queued', 'unresolved'):
            self.ledger_status(key, status)
            with self.subTest(status=status), self.assertRaises(ValueError):
                W.handoff(self.state, key, issue.read, issue.post)
            self.assertEqual(issue.comments, [])
            self.assertEqual(self.ledger()['actions'][key]['status'], status)

    def test_r11_marker_binds_the_exact_key(self):
        key = self.queued()
        issue = Issue()
        # A quote of the marker, or another key's marker, is not this handoff.
        issue.comments += [{'id': 6800000901, 'body': 'see\n' + W.MARK + key},
                           {'id': 6800000902, 'body': W.MARK + key + '-other\n'}]
        self.assertEqual(W.handoff(self.state, key, issue.read, issue.post), '6800000903')
        self.assertIn(W.MARK + key + ' ', issue.comments[-1]['body'])
        self.assertNotRegex(issue.comments[-1]['body'], r'https?://|thr_')

    # R13 (diagnosis #325 6850323481): the marker binds the key AND the payload's sha256.
    def r13_issue(self, key, *bodies):
        issue = Issue()
        issue.comments += [{'id': 6800000901 + i, 'body': b} for i, b in enumerate(bodies)]
        return issue

    def test_r13_same_key_same_hash_is_the_earlier_handoff(self):
        key = self.queued()
        action = self.ledger()['actions'][key]
        genuine = W.handoff_body(action)
        # Even after someone prepends a progress line, the exact marker and payload still match.
        issue = self.r13_issue(key, 'progress: synthetic note\n' + genuine)
        self.assertEqual(W.handoff(self.state, key, issue.read, issue.post), '6800000901')
        self.assertEqual(len(issue.comments), 1)

    def test_r13_same_key_other_hash_or_bare_marker_posts_new(self):
        for status in ('queued', 'unresolved'):
            with self.subTest(status=status):
                self.state = self.root / ('state-' + status)  # an independent ledger per case
                key = self.queued()
                self.ledger_status(key, status)
                stale = W.MARK + key + ' ' + 'f' * 64 + '\n\npayload: {"kind":"stage-ready"}\n'
                copied = W.MARK + key + ' ' + W.payload_hash(self.ledger()['actions'][key]) + '\n'  # no payload
                rehashed = (W.MARK + key + ' ' + 'e' * 64 + '\npayload: ' +
                            W.payload(self.ledger()['actions'][key]) + '\n')  # current payload, wrong hash
                issue = self.r13_issue(key, W.MARK + key + '\n', stale, copied, rehashed)
                receipt = W.handoff(self.state, key, issue.read, issue.post)
                self.assertEqual(receipt, '6800000905')
                self.assertEqual(len(issue.comments), 5)
                self.assertEqual((self.ledger()['actions'][key]['status'], self.ledger()['actions'][key]['receipt']),
                                 ('routed', '6800000905'))

    def test_r13_unreadable_issue_posts_nothing_and_says_uncertain(self):
        key = self.queued()
        issue = Issue(read_fails=True)
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            W.handoff(self.state, key, issue.read, issue.post)
        self.assertEqual(issue.comments, [])
        self.assertEqual(self.ledger()['actions'][key]['status'], 'queued')

    def test_r13_lost_reply_then_edited_source_still_one_comment(self):
        key = self.queued()
        issue = Issue(lose_reply=True)
        with self.assertRaises(OSError):
            W.handoff(self.state, key, issue.read, issue.post)
        issue.lose_reply = False
        issue.comments[0]['body'] = 'progress: synthetic note\n' + issue.comments[0]['body']
        self.assertEqual(W.handoff(self.state, key, issue.read, issue.post), '6800000001')
        self.assertEqual(len(issue.comments), 1)

    def ledger_status(self, key, status):
        ledger = self.ledger()
        ledger['actions'][key]['status'] = status
        (self.state / 'weekly.json').write_text(json.dumps(ledger))

    def test_r5_measured_baseline_routes_fixes(self):
        prepared = self.week()
        ev = outcome(prepared['cases_hash'])
        score = failing(ev['baseline'])
        score['cost_usd'] = 0.42
        for row in score['rows']:
            row['cost_usd'] = 0.105
        r = self.week(baseline={'mode': 'measured', 'settings': ev['settings'], 'score': score})
        self.assertEqual(r['actions'], {f'{WEEK}:fix:build-ticket': 'routed'})
        self.assertEqual(r['eval']['baseline'], '0/2 (measured run)')
        # Measured cost is never accepted as fake, and nothing is relabelled.
        self.assertEqual(self.week(baseline={'settings': ev['settings'], 'score': score})['status'], 'gap')
        for bad in (-1, float('nan'), True):
            worse = copy.deepcopy(score)
            worse['cost_usd'] = bad
            with self.subTest(cost=bad):
                self.assertEqual(self.week(baseline={'mode': 'measured', 'settings': ev['settings'],
                                                     'score': worse})['status'], 'gap')
        # J29: a week completes on measured evidence, labelled as measured.
        done = self.week(evidence=measured(ev))
        self.assertEqual(done['status'], 'complete')
        self.assertEqual(done['evidence_class'], 'measured run')
        self.assertEqual(done['actions'], {f'{WEEK}:fix:build-ticket': 'routed'})
        cut = measured(ev)['result']
        self.assertEqual(self.week(cuts={'build-ticket': cut})['actions'][f'{WEEK}:cut:build-ticket'], 'routed')
        self.assertIn('measured run', W.render(done))



def measured(ev):
    """A synthetic measured envelope: the same rows with real recorded costs."""
    ev = copy.deepcopy(ev)
    ev['mode'] = 'measured'
    for key in ('baseline', 'result'):
        ev[key]['cost_usd'] = 0.42
        for row in ev[key]['rows']:
            row['cost_usd'] = 0.105
    return ev


class MeasuredCore(unittest.TestCase):
    """J29: #2236's core completes and resumes on measured evidence; fake stays zero-cost."""

    # The core's fixture only, without re-running its tests.
    setUp, tick, prepared, saved = (CheckpointCore.setUp, CheckpointCore.tick,
                                    CheckpointCore.prepared, CheckpointCore.saved)

    def test_measured_week_completes_resumes_and_carries_its_class(self):
        p = self.prepared()
        r = self.tick(evidence=measured(outcome(p['cases_hash'])))
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['evidence_class'], 'measured run')
        self.assertEqual(self.saved()['last_evidence']['mode'], 'measured')
        self.assertEqual(self.tick(), r)  # resume re-validates the saved measured receipt
        self.source = FakeSources()
        nxt = self.tick(NEXT)
        self.assertEqual(nxt['status'], 'unchanged')
        self.assertEqual(nxt['evidence_class'], 'measured run')

    def test_fixture_class_and_cost_rules_unchanged(self):
        p = self.prepared()
        costly = measured(outcome(p['cases_hash']))
        costly['mode'] = 'fake'
        self.assertEqual(self.tick(evidence=costly)['status'], 'gap')
        for bad in (-0.01, float('nan'), float('inf'), True, '0.1', None):
            for where in ('score', 'row'):
                e = measured(outcome(p['cases_hash']))
                if where == 'score':
                    e['result']['cost_usd'] = bad
                else:
                    e['result']['rows'][0]['cost_usd'] = bad
                with self.subTest(cost=bad, where=where):
                    self.assertEqual(self.tick(evidence=e)['status'], 'gap')
                    self.assertIsNone(self.saved()['successful_week'])
        r = self.tick(evidence=outcome(p['cases_hash']))
        self.assertEqual((r['status'], r['evidence_class']), ('complete', 'fixture test'))


class ReportArtifacts(unittest.TestCase):
    """R3: the CLI refuses an identifier before either artifact is written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        literals = self.root / 'literals.txt'
        literals.write_text('synthetic-review-literal\n')
        patcher = mock.patch.dict('os.environ', {'OPENWIZ_PRIVACY_LITERALS': str(literals)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tick(self, out, tokenizer):
        drafts, tokens = self.root / 'drafts.json', self.root / 'tokens.json'
        drafts.write_text('{}')
        tokens.write_text(json.dumps({'tokenizer': tokenizer, 'skills': {'build-ticket': {'before': 1, 'after': 1}}}))
        with mock.patch.object(W, 'run_gh', lambda argv: (0, '[[]]')), \
                contextlib.redirect_stdout(io.StringIO()):
            return W.main(['tick', '--repo', 'example/work', '--week', WEEK, '--state', str(self.root / 'state'),
                           '--drafts', str(drafts), '--report', str(out), '--tokens', str(tokens)])

    def test_r3_refusal_writes_nothing(self):
        fresh = self.root / 'fresh'
        with self.assertRaises(ValueError):
            self.tick(fresh, 'thr_synthleak')
        self.assertFalse((fresh / 'report.json').exists() or (fresh / 'report.md').exists())
        existing = self.root / 'existing'
        self.assertEqual(self.tick(existing, 'synthetic-tokenizer'), 0)
        before = {n: (existing / n).read_bytes() for n in ('report.json', 'report.md')}
        self.assertIn('synthetic-tokenizer', json.loads(before['report.json'])['tokens']['tokenizer'])
        with self.assertRaises(ValueError):
            self.tick(existing, 'thr_synthleak')
        self.assertEqual({n: (existing / n).read_bytes() for n in before}, before)


class GitHubReader(unittest.TestCase):
    """C10: the real read_page adapter, through an injected fake gh runner."""

    def runner(self, answers):
        calls = []

        def run(argv):
            calls.append(argv)
            for prefix, answer in answers:
                if argv[2].startswith(prefix):
                    return answer
            return 0, '[[]]'
        return run, calls

    def test_reads_every_page_and_normalizes(self):
        ic = [{'id': 9001, 'updated_at': '2030-01-08T12:00:00Z', 'body': 'b', 'extra': 1,
               'html_url': 'https://github.com/example/work/issues/4901#issuecomment-9001'}]
        rc = dict(ic[0], id=9002, html_url='https://github.com/example/work/pull/4901#discussion_r9002')
        pulls = [[{'number': 4901, 'updated_at': '2030-01-09T00:00:00Z'}],
                 [{'number': 4902, 'updated_at': '2029-12-01T00:00:00Z'}]]
        reviews = [[{'id': 9003, 'submitted_at': '2030-01-08T13:00:00Z', 'body': '', 'state': 'APPROVED',
                     'html_url': 'https://github.com/example/work/pull/4901#pullrequestreview-9003'},
                    {'id': 9004, 'submitted_at': None, 'body': '', 'state': 'PENDING',
                     'html_url': 'https://github.com/example/work/pull/4901#pullrequestreview-9004'}]]
        run, calls = self.runner([('repos/example/work/issues/comments', (0, json.dumps([ic, []]))),
                                  ('repos/example/work/pulls/comments', (0, json.dumps([[rc]]))),
                                  ('repos/example/work/pulls/4901/reviews', (0, json.dumps(reviews))),
                                  ('repos/example/work/pulls?', (0, json.dumps(pulls)))])
        read = W.gh_reader('example/work', run)
        page = read('issue_comments', WEEK, 1)
        self.assertEqual(page, {'items': [{'id': 9001, 'updated_at': '2030-01-08T12:00:00Z', 'body': 'b',
                                           'url': ic[0]['html_url']}], 'next_page': None})
        self.assertIn('since=2030-01-07T00:00:00Z', calls[0][2])
        self.assertEqual(calls[0][:2] + calls[0][3:], ['gh', 'api', '--paginate', '--slurp'])
        result = C.collect(WEEK, read, lambda item: None, SKILLS)
        self.assertEqual(result['sources']['reviews']['records'].keys(), {'9003'})
        self.assertFalse(any('pulls/4902/reviews' in c[2] for c in calls))

    def test_failed_or_malformed_reads_refuse(self):
        for answer in ((1, '[[]]'), (0, 'not json'), (0, '[{"id": 1}]'), (0, '[[{"id": 1}]]'), (0, '{}')):
            run, _ = self.runner([('repos/example/work/issues/comments', answer)])
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                C.collect(WEEK, W.gh_reader('example/work', run), lambda item: None, SKILLS)
        for repo in ('example', '../work/x', 'a/b/c'):
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                W.gh_reader(repo, lambda argv: (0, '[[]]'))


    def test_issue_adapter_reads_before_posting(self):
        calls = []
        marked = W.MARK + 'k1\n\nbody'

        def run(argv, pages=None):
            calls.append(argv)
            if '--method' in argv:
                return 0, json.dumps({'id': 6800000011, 'html_url': 'ignored'})
            return 0, json.dumps(pages)
        for pages, posted in (([[{'id': 6800000005, 'body': marked, 'user': {}}], []], False),
                              ([[{'id': 6800000006, 'body': 'other'}]], True)):
            calls.clear()
            read, post = W.gh_issue('example/work', '4950', lambda argv: run(argv, pages))
            self.assertEqual(calls, [])
            comments = read()
            self.assertEqual(calls[0], ['gh', 'api', 'repos/example/work/issues/4950/comments?per_page=100',
                                        '--paginate', '--slurp'])
            self.assertEqual(any(c['body'].split('\n', 1)[0] == W.MARK + 'k1' for c in comments), not posted)
        self.assertEqual(post('b'), '6800000011')
        self.assertEqual(calls[-1], ['gh', 'api', '--method', 'POST', 'repos/example/work/issues/4950/comments',
                                     '-f', 'body=b'])
        for answer in ((1, '[[]]'), (0, '[{"id": 1}]'), (0, '[[1]]'), (0, 'nope')):
            read, _ = W.gh_issue('example/work', '4950', lambda argv: answer)
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                read()
        for issue in ('0', '49x', 4950):
            with self.subTest(issue=issue), self.assertRaises(ValueError):
                W.gh_issue('example/work', issue, run)


class LoopDefinition(unittest.TestCase):
    """C9: one weekly CloudRoom loop definition; registration is the orchestrator's."""

    def test_definition(self):
        argv = W.loop_argv('PROMPT_FILE')
        self.assertEqual(argv[:3], ['room-cli', 'loop', 'create'])
        self.assertEqual(argv.count('--cron'), 1)
        cron = argv[argv.index('--cron') + 1].split()
        self.assertEqual(len(cron), 5)
        self.assertEqual(cron[2:4], ['*', '*'])
        self.assertRegex(cron[4], r'^[0-6]$')
        self.assertIn('--new-thread', argv)
        self.assertEqual(argv[argv.index('--secrets') + 1], 'none')
        for forbidden in ('--webhook', '--same-thread', '--in', '--at', '--script'):
            self.assertNotIn(forbidden, argv)
        prompt = W.LOOP['prompt']
        for phrase in ('dry-run', 'credit-aware start rule', 'End the turn', 'no watcher',
                       'tools/skills-eval/weekly/README.md'):
            self.assertIn(phrase, prompt)
        self.assertNotRegex(json.dumps(W.LOOP), r'thr_|prj_|loop_[a-z0-9]|https?://')


if __name__ == '__main__':
    unittest.main()
