#!/usr/bin/env python3
"""WR2 external behavior: finite local artifacts only, no scheduler or network."""
import copy
import hashlib
import importlib.util
import json
import multiprocessing
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import suite


def module(name):
    spec = importlib.util.spec_from_file_location('wr2_' + name, HERE / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


AT = '2030-01-02T12:00:00Z'
NEXT = '2030-01-02T12:10:00Z'
LINK = 'https://github.com/synthetic-owner/work/issues/4001'


def provider():
    return suite.load(HERE / 'fixtures/contract/known.json')['providers'][0]


def publication_worker(root, role, connection):
    """Coordinate actual tick processes at publication, retaining native locks."""
    import fcntl
    main = module('main')
    target = Path(root) / 'page.html'
    original_replace = main.os.replace
    original_latest = main.history.latest
    original_flock = fcntl.flock
    announced = False

    def announce_selection(history_root):
        nonlocal announced
        if role == 'newer' and not announced:
            connection.send('unlocked-selection')
            announced = True
        return original_latest(history_root)

    def announce_lock(fd, operation):
        nonlocal announced
        if role == 'newer' and operation == fcntl.LOCK_EX and not announced:
            connection.send('lock-attempt')
            announced = True
        return original_flock(fd, operation)

    def paused_replace(source, destination):
        if role == 'older' and Path(destination) == target:
            connection.send('older-ready')
            if not connection.poll(15) or connection.recv() != 'release':
                raise RuntimeError('synthetic publication release missing')
        return original_replace(source, destination)

    try:
        with patch.object(main.os, 'replace', paused_replace), \
             patch.object(main.history, 'latest', announce_selection), \
             patch.object(fcntl, 'flock', announce_lock):
            main.tick(AT if role == 'older' else NEXT, root, target, lambda *_: [])
        connection.send('done')
    except BaseException as error:
        connection.send(('error', type(error).__name__))
    finally:
        connection.close()


class PageHistory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_immutable_atomic_history(self):
        h = module('history')
        record = suite.compose(AT, [provider()])
        self.assertTrue(h.save(self.root, record))
        self.assertFalse(h.save(self.root, copy.deepcopy(record)))
        other = copy.deepcopy(record)
        other['providers'][0]['metrics'][0]['value'] = 2
        with self.assertRaises(ValueError):
            h.save(self.root, other)
        older = suite.compose('2030-01-02T11:55:00Z')
        h.save(self.root, older)
        self.assertEqual(h.latest(self.root), record)
        self.assertEqual([r['sample_at'] for r in h.read_all(self.root)],
                         ['2030-01-02T11:55:00Z', AT])
        # A crash before atomic installation must expose no partial sample.
        with patch.object(h.os, 'link', side_effect=OSError('synthetic interruption')):
            with self.assertRaises(OSError):
                h.save(self.root, suite.compose(NEXT))
        self.assertEqual(len(h.read_all(self.root)), 2)
        self.assertEqual(h.latest(self.root), record)
        self.assertEqual((self.root / 'samples').stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600
                            for p in (self.root / 'samples').glob('*.json')))

    def test_overlapping_processes_publish_latest_sample(self):
        # R1. An old replacement held while a new tick samples must leave the
        # final page at 12:10. Serial and immutable-write tests miss this race.
        context = multiprocessing.get_context('fork')
        old_parent, old_child = context.Pipe()
        new_parent, new_child = context.Pipe()
        older = context.Process(target=publication_worker, args=(str(self.root), 'older', old_child))
        newer = context.Process(target=publication_worker, args=(str(self.root), 'newer', new_child))
        def receive(connection):
            self.assertTrue(connection.poll(15), 'publication process did not reach its barrier')
            return connection.recv()
        try:
            older.start()
            self.assertEqual(receive(old_parent), 'older-ready')
            newer.start()
            barrier = receive(new_parent)
            self.assertIn(barrier, ('unlocked-selection', 'lock-attempt'))
            # Before the fix, let the unprotected new replacement complete
            # first. With the fix, its native flock blocks until release.
            if barrier == 'unlocked-selection':
                self.assertEqual(receive(new_parent), 'done')
            old_parent.send('release')
            self.assertEqual(receive(old_parent), 'done')
            if barrier == 'lock-attempt':
                self.assertEqual(receive(new_parent), 'done')
            older.join(15)
            newer.join(15)
            self.assertEqual((older.exitcode, newer.exitcode), (0, 0))
            latest = module('history').latest(self.root)
            self.assertEqual(latest['sample_at'], NEXT)
            self.assertEqual((self.root / 'page.html').read_text(), module('page').render(latest))
        finally:
            for process in (older, newer):
                if process.pid is not None:
                    if process.is_alive():
                        process.terminate()
                    process.join(15)
            for connection in (old_parent, old_child, new_parent, new_child):
                connection.close()

    def test_ticks_restart_and_partial_source(self):
        main, h, sources = module('main'), module('history'), module('sources')
        page = self.root / 'page.html'
        first = main.tick('2030-01-02T12:02:59Z', self.root, page,
                          lambda at, previous: [provider()])
        self.assertEqual(first['sample_at'], AT)
        with patch('builtins.print'):
            again = main.tick('2030-01-02T12:04:59Z', self.root, page,
                              lambda *_: self.fail('duplicate tick reads sources'))
        self.assertEqual(again, first)
        # A process restart sees the immutable sample, without an in-memory timer.
        main = module('main')
        def failed(at, previous):
            return sources.select(self.root, [{'kind': 'projected', 'slot': 'activity',
                'path': 'missing.json', 'sha256': '0' * 64,
                'observed_at': AT, 'evidence': [LINK]}], at, previous)
        second = main.tick(NEXT, self.root, page, failed)
        metric = second['providers'][0]['metrics'][0]
        self.assertEqual(metric['value'], 3)
        self.assertEqual(metric['observed_at'], AT)
        self.assertEqual(metric['freshness'], 'stale')
        self.assertEqual(metric['state'], 'partial')
        self.assertTrue(metric['prerequisites'])
        self.assertEqual(len(h.read_all(self.root)), 2)  # 12:05 remains a gap.
        main.tick('2030-01-02T11:55:10Z', self.root, page, lambda *_: [])
        self.assertEqual(h.latest(self.root)['sample_at'], NEXT)
        self.assertIn(NEXT, page.read_text())
        self.assertIn('stale', page.read_text())

    def test_generic_page_and_missing_slots(self):
        page = module('page')
        record = suite.compose(AT, [provider()])
        html = page.render(record)
        positions = [html.index('id="' + group + '"') for group in suite.GROUPS]
        self.assertEqual(positions, sorted(positions))
        for slot in ('cost', 'answer_time', 'rework', 'stage_waits', 'credits',
                     'claude_usage', 'eb6', 'eb7', 'eb8', 'eb9'):
            self.assertIn('data-slot="' + slot + '"', html)
        self.assertIn('unavailable', html)
        self.assertIn('no replay run is claimed', html)
        self.assertIn('http-equiv="refresh" content="300"', html)
        self.assertNotIn('<form', html)
        self.assertNotIn('<script', html)
        self.assertIn('3 count', html)
        self.assertIn('2030-01-02T11:00:00Z', html)
        self.assertIn('synthetic.activity.v1', html)
        self.assertIn('fresh through', html)

    def test_privacy_and_escaping(self):
        page, h = module('page'), module('history')
        record = suite.compose(AT, [provider()])
        metric = record['providers'][0]['metrics'][0]
        metric['label'] = '<img src=x onerror=alert(1)> & "quoted"'
        html = page.render(record)
        self.assertIn('&lt;img', html)
        self.assertNotIn('<img', html)
        for bad in ('javascript:alert(1)', 'https://evil.example/track'):
            metric['evidence'] = [bad]
            with self.assertRaises(ValueError):
                page.render(record)
        metric['evidence'] = [LINK]
        for private in ('thr_' + 'planted987', 'ghp_' + 'a' * 36,
                        'Authorization: Bearer planted', '/home/' + 'planted/private'):
            metric['label'] = private
            with self.assertRaises(ValueError):
                h.save(self.root, record)
        self.assertEqual(h.read_all(self.root), [])

    def test_finite_invocation(self):
        # Use the existing CI point reader; the worked literals describe capacity,
        # not current running/queued CI or direction-classified merges.
        point = {'schema': 'closedwiz.ci-bench.v1', 'label': 'synthetic window',
                 'since': '2030-01-01T08:00:00Z', 'until': '2030-01-02T08:00:00Z',
                 'hours': 24, 'robots': 5, 'runs': 4, 'jobs': 8, 'merged_prs': 3,
                 'merged_per_hour': 0.125, 'code_runs': None, 'legacy': None}
        raw = json.dumps(point)
        (self.root / 'point.json').write_text(raw)
        selection = [{'kind': 'ci_bench', 'slot': 'ci_bench', 'path': 'point.json',
                      'sha256': hashlib.sha256(raw.encode()).hexdigest(),
                      'observed_at': AT, 'evidence': [LINK]}]
        (self.root / 'selection.json').write_text(json.dumps(selection))
        result = subprocess.run([sys.executable, '-I', str(HERE / 'main.py'),
            '--at', AT, '--source-root', str(self.root), '--selection',
            str(self.root / 'selection.json'), '--history', str(self.root / 'saved'),
            '--page', str(self.root / 'private.html')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = module('history').latest(self.root / 'saved')
        metrics = next(p for p in saved['providers'] if p['slot'] == 'ci_bench')['metrics']
        self.assertEqual(next(m['value'] for m in metrics if m['id'] == 'merged'), 3)
        self.assertTrue(all(m['source']['sha256'] == selection[0]['sha256'] for m in metrics))
        self.assertIn('completed window', (self.root / 'private.html').read_text())
        self.assertIn('direction', (self.root / 'private.html').read_text())
        # Edited bytes cannot be treated as the pinned artifact.
        (self.root / 'point.json').write_text(raw + ' ')
        selected = module('sources').select(self.root, selection, AT)
        self.assertEqual(selected[0]['state'], 'unavailable')
        self.assertEqual(selected[0]['metrics'], [])

    def select_native(self, kind, raw):
        sources = module('sources')
        wire = raw if isinstance(raw, str) else json.dumps(raw)
        filename = kind + '.json'
        (self.root / filename).write_text(wire)
        selection = {'kind': kind, 'slot': sources.SLOTS[kind], 'path': filename,
                     'sha256': hashlib.sha256(wire.encode()).hexdigest(),
                     'observed_at': AT, 'evidence': [LINK]}
        projected = sources.select(self.root, [selection], AT)[0]
        suite.compose(AT, [projected])
        return projected

    def test_ci_native_units_and_cost_gap(self):
        # Existing points store queued_to_done in minutes. A seconds label is
        # a sixtyfold misstatement. The empty-cohort CLI case cannot catch it.
        c = {'rule': 'synthetic successful code runs', 'runs': 2, 'robot_seconds': 240,
             'robot_minutes_per_run': 2, 'prs_per_hour': 150,
             'categories': dict.fromkeys(('web', 'setup', 'rust', 'build', 'skills'), 0),
             'split': {'waiting': 1, 'setup': 1, 'running': 1},
             'queued_to_done': {'median': 7, 'p90': 9, 'max': 9}}
        p = {'schema': 'closedwiz.ci-bench.v1', 'label': 'synthetic',
             'since': '2030-01-01T08:00:00Z', 'until': '2030-01-02T08:00:00Z',
             'hours': 24, 'robots': 5, 'runs': 2, 'jobs': 4, 'merged_prs': 3,
             'merged_per_hour': 0.125, 'code_runs': c, 'legacy': None,
             'cost': {'runner_minutes': {}, 'billed_minutes': {}, 'window_usd': None,
                      'per_code_run_usd': None, 'unknown_minutes': 2, 'prices': []}}
        projected = self.select_native('ci_bench', p)
        metrics = {m['id']: m for m in projected['metrics']}
        self.assertEqual(metrics['queued-to-done-median']['value'], 7)
        self.assertEqual(metrics['queued-to-done-median']['unit'], 'minutes')
        self.assertEqual(metrics['capacity']['value'], 150)
        self.assertIsNone(metrics['list-cost']['value'])
        self.assertEqual(metrics['list-cost']['state'], 'partial')

    def test_existing_daily_usage_credits_and_journey(self):
        # Keys and private payload in unused native fields never become series
        # labels or identities. Native readers validate; projections select facts.
        usage = {'date': '2030-01-01', 'complete': True,
                 'claude': [{'thread': 'private-usage-key', 'tokens': 1000, 'credits': 2, 'usd': 1},
                            {'thread': 'another-key', 'tokens': 2000, 'credits': 4, 'usd': None}],
                 'gpt': [], 'sandbox': {'hours': 6, 'usd': 3}}
        projected = self.select_native('claude_usage', usage)
        values = {m['unit']: m['value'] for m in projected['metrics']}
        self.assertEqual(values, {'tokens': 3000, 'credits': 6, 'usd': None})
        self.assertNotIn('private-usage-key', json.dumps(projected))
        rows = [{'at': '2030-01-02T10:00:00Z', 'credits': 10, 'credits_limit': 100,
                 'extra_credits': 50, 'extra_credits_total': 100},
                {'at': '2030-01-02T11:00:00Z', 'credits': 15, 'credits_limit': 100,
                 'extra_credits': 48, 'extra_credits_total': 100}]
        projected = self.select_native('credits', '\n'.join(json.dumps(r) for r in rows))
        self.assertEqual(projected['metrics'][0]['value'], 7)
        self.assertEqual(projected['state'], 'partial')
        self.assertEqual(projected['metrics'][0]['window']['timezone'], 'PST-fixed-UTC-08:00')
        doc = json.loads((HERE.parent / 'factory-metrics/fixtures/journey/journeys.json').read_text())
        projected = self.select_native('journey', doc)
        self.assertTrue(any(m['value'] == 19 for m in projected['metrics']))
        self.assertTrue(all(m['group'] == 'stage_waits' and m['state'] == 'partial'
                            for m in projected['metrics']))

    def test_credit_interval_identities_survive_backfill(self):
        # R2. A native interval keeps its identity when older samples arrive.
        # The original two-row arithmetic proof only checks the credit amount.
        def balance(hour, credits, extra):
            return {'at': '2030-01-02T' + hour + ':00:00Z', 'credits': credits,
                    'credits_limit': 100, 'extra_credits': extra, 'extra_credits_total': 100}
        before = balance('09', 8, 50)
        start, end = balance('10', 10, 50), balance('11', 15, 48)
        def project(rows):
            return self.select_native('credits', '\n'.join(json.dumps(row) for row in rows))['metrics']
        initial = project([start, end])[0]
        backfilled = project([before, start, end])
        preserved = next(m for m in backfilled if m['window'] == initial['window'])
        self.assertEqual(initial['value'], 7)
        self.assertEqual([m['value'] for m in backfilled], [2, 7])
        for key in ('id', 'dimensions', 'sample'):
            self.assertEqual(preserved[key], initial[key])
        seed = {'at': start['at'], 'extra_credits': 50, 'only': 'extra_credits'}
        extra_only = project([seed, end])[0]
        self.assertEqual(extra_only['value'], 2)
        self.assertNotEqual(extra_only['id'], initial['id'])
        self.assertNotEqual(extra_only['sample']['identities'], initial['sample']['identities'])

    def test_source_omission_keeps_last_evidence(self):
        # Changing selection is not evidence of an empty provider. Existing
        # missing-file proof misses complete omission of a formerly selected slot.
        sources = module('sources')
        previous = suite.compose(AT, [provider()])
        result = sources.select(self.root, [], NEXT, previous)
        activity = next(p for p in result if p['slot'] == 'activity')
        self.assertEqual(activity['metrics'][0]['value'], 3)
        self.assertEqual(activity['metrics'][0]['freshness'], 'stale')
        self.assertEqual(activity['state'], 'partial')

    def test_page_failure_restart_and_readback(self):
        main, h = module('main'), module('history')
        target = self.root / 'private.html'
        with patch.object(main.os, 'replace', side_effect=OSError('synthetic interrupted page')):
            with self.assertRaises(OSError):
                main.tick(AT, self.root, target, lambda *_: [provider()])
        self.assertEqual(len(h.read_all(self.root)), 1)
        self.assertFalse(target.exists())
        main.tick(AT, self.root, target, lambda *_: self.fail('restart must reuse saved sample'))
        self.assertEqual(target.read_text(), module('page').render(h.latest(self.root)))

    def test_differing_concurrent_samples_refuse(self):
        from concurrent.futures import ThreadPoolExecutor
        h = module('history')
        def save(_):
            return h.save(self.root, suite.compose(AT, [provider()]))
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(save, range(2)))
        self.assertEqual(sorted(outcomes), [False, True])
        self.assertEqual(len(h.read_all(self.root)), 1)

    def test_factory_daily_usage_is_separate_from_pr_attribution(self):
        # A saved daily report already has usage totals. Omitting them loses
        # existing evidence; the separate owner-export test does not cover this.
        M = module('sources').native('tools/factory-metrics/metrics.py')
        p = M.measure(M.day_arg('2030-01-01'), {}, [], 0, 0)
        p['costs'] = M.cloud_costs(None, p['date'], 0)
        p['costs']['actions'] = M.unknown(('minutes', 'usd'), 'synthetic unavailable', 0)
        p['costs']['total_usd'] = M.amount(None, 0)
        p['costs']['claude'] = {'tokens': {'total': 3000, 'per_merged_pr': None},
                                'credits': {'total': 6, 'per_merged_pr': None},
                                'usd': {'total': None, 'per_merged_pr': None},
                                'threads': [{'thread': 'private-key-do-not-copy', 'tokens': 3000, 'credits': 6, 'usd': None}],
                                'reason': 'private diagnostic do not copy'}
        projected = self.select_native('factory_metrics', p)
        metrics = {m['id']: m for m in projected['metrics']}
        self.assertEqual(metrics['claude-credits']['value'], 6)
        self.assertIsNone(metrics['claude-usd']['value'])
        self.assertEqual(metrics['claude-usd']['state'], 'partial')
        self.assertIn('day usage', metrics['claude-credits']['label'])
        self.assertNotIn('private-key', json.dumps(projected))
        self.assertNotIn('private diagnostic', json.dumps(projected))

    def test_selection_and_history_fail_closed(self):
        sources, h = module('sources'), module('history')
        for selection in ({}, [{'kind': 'made-up'}],
                          [{'kind': 'projected', 'slot': 'activity', 'path': '../escape',
                            'sha256': 'a' * 64, 'observed_at': AT, 'evidence': [LINK]}]):
            with self.assertRaises(ValueError):
                sources.select(self.root, selection, AT)
        h.save(self.root, suite.compose(AT))
        path = next((self.root / 'samples').glob('*.json'))
        path.write_text('{"sample_id":')
        with self.assertRaises(ValueError):
            h.latest(self.root)

    def test_factory_artifact_refuses_undeclared_fields(self):
        # This output has no standalone native validator. The projection must
        # reject unknown fields rather than silently accepting a changed schema.
        M = module('sources').native('tools/factory-metrics/metrics.py')
        p = M.measure(M.day_arg('2030-01-01'), {}, [], 0, 0)
        p['costs'] = M.cloud_costs(None, p['date'], 0)
        p['costs']['actions'] = M.unknown(('minutes', 'usd'), 'synthetic unavailable', 0)
        p['costs']['total_usd'] = M.amount(None, 0)
        p['undeclared'] = 42
        projected = self.select_native('factory_metrics', p)
        self.assertEqual(projected['state'], 'unavailable')
        self.assertEqual(projected['metrics'], [])

    def test_approved_board_point_projection(self):
        # A board point has no native interval. The approved partial/null seam
        # must retain its source/time and ticket state without inventing counts.
        graph = json.loads((HERE.parents[1] / 'skills/plan-graph/test/links/clean-wide/graph.json').read_text())
        graph['read_at'] = AT
        graph['tickets'][0]['title'] = 'private title must be dropped'
        p = self.select_native('board_graph', graph)
        self.assertEqual(p['state'], 'partial')
        self.assertEqual(len([m for m in p['metrics'] if m['dimensions']['ticket']]), 6)
        self.assertTrue(all(m['value'] is None and m['window'] is None and
                            m['observed_at'] == AT and m['source'] and m['prerequisites']
                            for m in p['metrics']))
        self.assertNotIn('private title', json.dumps(p))
        row = {'schema': 'openwiz.plan-links.v1', 'kind': 'history', 'sample': 'run',
               'at': '2030-01-02T11:00:00Z', 'day': '2030-01-02', 'repo': 'synthetic-owner/work',
               'open_approved': 4, 'can_start': 1, 'startable_percent': 25,
               'file_links': 0, 'unlabelled_links': 0, 'ready_stock': 1,
               'builders_running': 1, 'fed_ratio': 1.0, 'low_stock': True}
        p = self.select_native('board_history', json.dumps(row))
        self.assertEqual(p['state'], 'partial')
        self.assertEqual({m['observed_at'] for m in p['metrics']}, {'2030-01-02T11:00:00Z'})
        self.assertTrue(all(m['value'] is None for m in p['metrics']))

    def test_approved_pending_decision_projection(self):
        from datetime import datetime, timezone
        doc = json.loads((HERE.parents[1] / 'tests/terminal/bodies/decisions.json').read_text())
        epoch = int(datetime(2030, 1, 2, 12, tzinfo=timezone.utc).timestamp()) * 1000
        doc['snapshot_at'] = epoch
        doc['freshness']['snapshot_at']['known'] = epoch
        doc['orchestrator']['freshness']['snapshot_at']['known'] = epoch
        doc['orchestrator']['target']['known'] = 'thr_' + 'planted987'
        doc['items'][0]['request']['summary'] = ['private question must be dropped']
        p = self.select_native('decisions', doc)
        self.assertEqual(p['state'], 'partial')
        self.assertEqual(len(p['metrics']), 1)
        m = p['metrics'][0]
        self.assertIsNone(m['value'])
        self.assertIsNone(m['window'])
        self.assertEqual(m['observed_at'], AT)
        self.assertIn('spec_confirmation', m['label'])
        self.assertIn('https://github.com/synthetic-owner/synthetic-repo/issues/9001#issuecomment-7001', m['evidence'])
        self.assertNotIn('private question', json.dumps(p))
        self.assertNotIn('planted987', json.dumps(p))
        saved = module('main').tick(AT, self.root / 'saved', self.root / 'page.html', lambda *_: [p])
        self.assertEqual(module('history').latest(self.root / 'saved'), saved)
        html = (self.root / 'page.html').read_text()
        self.assertIn('spec_confirmation', html)
        self.assertIn('point observation', html)
        self.assertNotIn('private question', html)
        self.assertNotIn('planted987', html)
        doc['items'].append(copy.deepcopy(doc['items'][0]))
        self.assertEqual(self.select_native('decisions', doc)['state'], 'unavailable')

    def test_recorded_eval_readiness_retains_source(self):
        score = {'schema': 'openwiz.skills-eval.score.v1', 'settings_hash': '2'*64,
                 'cases_hash': '3'*64, 'code_hash': '4'*64, 'schema_hash': '5'*64,
                 'revision': {'commit': 'a'*40, 'tree': 'b'*40}, 'suite_pass': True,
                 'runs': 1, 'passed': 1, 'cost_usd': 0,
                 'rows': [{'case': 'synthetic', 'repeat': 1, 'pass': True,
                           'reasons': [], 'details': [], 'cost_usd': 0, 'stop': 'end_turn'}]}
        p = self.select_native('skills_eval', score)
        self.assertEqual(p['state'], 'partial')
        self.assertEqual(p['metrics'][0]['observed_at'], AT)
        self.assertIn('passing', p['metrics'][0]['label'])
        self.assertIsNone(p['metrics'][0]['value'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
