#!/usr/bin/env python3
"""#1252 daily backfill and headline metrics on synthetic API records."""
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

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result

fixture = module('fixtures', HERE/'test.py')
factory_fixture = module('factory_fixtures', HERE/'test_factory.py')


def cli(*args, env=None):
    return subprocess.run([sys.executable, '-I', str(HERE/'bench.py'), *map(str, args)],
                          capture_output=True, text=True, env=dict(os.environ, **(env or {})), timeout=45)


class DailyMetrics(unittest.TestCase):
    def test_backfill_all_full_pst_days_once_and_resume_without_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root/'bin'
            bindir.mkdir()
            shutil.copy(HERE/'fixtures/gh', bindir/'gh')
            world = {}
            # Two independent fixed-PST days, even though July has daylight saving.
            for day, rid in [('01', 701), ('02', 702)]:
                since, until = f'2030-07-{day}T08:00:00Z', f'2030-07-{int(day)+1:02d}T08:00:00Z'
                created, start, end = f'2030-07-{day}T09:00:00Z', f'2030-07-{day}T09:05:00Z', f'2030-07-{day}T09:07:00Z'
                run = fixture.gh_run(rid, 'pull_request', 'success', created)
                job = fixture.gh_job('rust', start, start, end, 'synthetic-runner',
                                     [fixture.gh_step('Run cargo test --workspace', start, end)])
                if day == '02':
                    middle = f'2030-07-{day}T09:06:00Z'
                    job['steps'][0]['completed_at'] = middle
                    job['steps'].append(fixture.gh_step('Run cargo test -p openwiz-tests --test web-api a8_web_page::', middle, end))
                records = {
                    f'api repos/{{owner}}/{{repo}}/actions/workflows/ci.yml/runs?created={since}..{until}&status=completed&per_page=100&page=1': {'total_count': 1, 'workflow_runs': [run]},
                    fixture.jobs_call(rid, 1): {'total_count': 1, 'jobs': [job]},
                    fixture.run_call(rid): run,
                    fixture.pulls_call(1): []}
                if day == '01':
                    cancelled = fixture.gh_run(703, 'pull_request', 'cancelled', created)
                    records[next(key for key in records if '/workflows/ci.yml/runs?' in key)] = {
                        'total_count': 2, 'workflow_runs': [run, cancelled]}
                    inconsistent = fixture.gh_job('web-build', start, start, created, 'synthetic-runner',
                        [fixture.gh_step('Set up job', created, created)], 'success')
                    records[fixture.jobs_call(703, 1)] = {'total_count': 1, 'jobs': [inconsistent]}
                    records[fixture.run_call(703)] = cancelled
                records.update(factory_fixture.quiet_day(since, until))
                world.update({key: {'stdout': json.dumps(value), 'exit': 0} for key, value in records.items()})
            (root/'world.json').write_text(json.dumps(world))
            (root/'calls.log').write_text('')
            env = {'PATH': str(bindir)+os.pathsep+os.environ['PATH'], 'FAKE_GH_WORLD': str(root/'world.json'),
                   'FAKE_GH_LOG': str(root/'calls.log')}
            out = root/'days'
            args = ['backfill', '--start-day', '2030-07-01', '--now', '2030-07-03T18:00:00Z',
                    '--out', out, '--robots', '5']
            r = cli(*args, env=env)
            self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
            self.assertEqual(sorted(p.name for p in out.iterdir()), ['2030-07-01', '2030-07-02'])
            calls = (root/'calls.log').read_text()
            # collect's 6 and 4 reads, and the factory's 33 a day (#1359): history, main's
            # runs, and the run lists of 30 look-back days and the day.
            self.assertEqual(len(calls.splitlines()), 76)
            for day in ('01', '02'):
                point = json.loads((out/f'2030-07-{day}'/'point.json').read_text())
                self.assertEqual(point['hours'], 24)
                if day == '01':
                    self.assertIsNone(point['cost']['window_usd'])
                    self.assertEqual(point['cost']['unknown_jobs'], 1)
                self.assertEqual(point['code_runs']['queued_to_done']['median'], 7)
                self.assertEqual(point['code_runs']['prs_per_hour'], 150)
                self.assertEqual(point['code_runs']['categories']['rust'], 2)
                self.assertEqual(point['latency_basis'], 'workflow created to last job completed')
            r = cli(*args, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((root/'calls.log').read_text(), calls)
            cached = out/'2030-07-01'/'point.json'
            cached_point = json.loads(cached.read_text())
            cached.write_text(json.dumps(dict(cached_point, robots=4)))
            r = cli(*args, env=env)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn('cached point differs', r.stderr)
            self.assertEqual((root/'calls.log').read_text(), calls)
            # A day measured before the factory benches gets only their reads.
            cached.write_text(json.dumps({k: v for k, v in cached_point.items() if k != 'factory'}))
            r = cli(*args, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            added = (root/'calls.log').read_text()[len(calls):].splitlines()
            self.assertEqual(len(added), 33)
            self.assertIn('api graphql ', added[0])
            self.assertEqual(json.loads(cached.read_text())['factory']['merged_prs'], 0)
            cached_point = json.loads(cached.read_text())
            dashboard = root/'dashboard'
            r = cli('dashboard', out/'2030-07-02', out/'2030-07-01', '--out', dashboard)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = (dashboard/'README.md').read_text()
            self.assertEqual(md.splitlines()[2], '![Daily CI metrics](daily-metrics.svg)')
            svg = (dashboard/'daily-metrics.svg').read_text()
            # #1331 (Jake's pick B): tonight's goal is the only line, when in range; all six goals are named.
            for text in ('2030-07-01', '2030-07-02', 'Minutes per PR', 'PRs an hour of capacity',
                         '>goals: tonight 10, this week 3, north star 1 min<', '<title>Tonight: 25 PRs/hour</title>',
                         '>then this week 80, north star 500 PRs/hour<'):
                self.assertIn(text, svg)
            self.assertLess(svg.index('2030-07-01'), svg.index('2030-07-02'))
            self.assertEqual(svg.count('class="metric-point"'), 4)
            # Hand-worked fixture: 7 min data -> axis end 8 (7 x 1.08 = 7.56), so the 10 min goal is
            # a note, not a line. Capacity 150 -> axis end 200 (150 x 1.08 = 162); plot y=228..408
            # puts tonight's 25 at 408 - 180 x 25/200 = 385.5.
            goals = svg.split('class="goal-line"')[1:]
            self.assertEqual(len(goals), 1)
            self.assertIn('y1="385.5"', goals[0].split('</line>', 1)[0])
            self.assertNotIn('Tonight: 15', svg)

    def test_daily_chart_keeps_an_empty_day_as_a_gap_and_deduplicates_days(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            windows = []
            for day in (1, 2, 3):
                w = root/str(day)
                shutil.copytree(HERE/'fixtures/window', w)
                r = cli('measure', w, '--robots', '5', '--label', f'2030-07-{day:02d} PST')
                self.assertEqual(r.returncode, 0, r.stderr)
                point = json.loads((w/'point.json').read_text())
                point.update(since=f'2030-07-{day:02d}T08:00:00Z', until=f'2030-07-{day+1:02d}T08:00:00Z',
                             hours=24, latency_basis='workflow created to last job completed')
                if day == 2:
                    point['code_runs'] = None
                (w/'point.json').write_text(json.dumps(point))
                windows.append(w)
            duplicate = root/'checkpoint'
            shutil.copytree(windows[0], duplicate)
            p = json.loads((duplicate/'point.json').read_text())
            p['label'] = 'checkpoint at same daily bounds'
            (duplicate/'point.json').write_text(json.dumps(p))
            out = root/'dashboard'
            r = cli('dashboard', windows[2], duplicate, windows[1], windows[0], '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            svg = (out/'daily-metrics.svg').read_text()
            self.assertEqual(svg.count('class="metric-point"'), 4)
            self.assertEqual(svg.count('class="goal-line"'), 1) # tonight's capacity goal; minutes goals are a note (#1331)
            self.assertEqual(svg.count('>unknown</text>'), 10) # old points also have unknown cost heroes/labels
            self.assertEqual(svg.count('<polyline'), 4) # two separate one-point segments per panel
            self.assertNotIn('checkpoint at same daily bounds', svg)

    def test_successful_run_anomaly_is_refused_even_with_timing_gaps_enabled(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)/'window'
            shutil.copytree(HERE/'fixtures/window', w)
            rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
            rows[0]['completed_at'] = '2030-01-01T00:00:59Z'
            (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            r = cli('measure', w, '--robots', '5', '--label', 'synthetic success anomaly', '--allow-timing-gaps')
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn('ends before it starts', r.stderr)
            self.assertFalse((w/'point.json').exists())

    def test_refuse_partial_day_and_bad_day_before_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root/'bin'
            bindir.mkdir()
            shutil.copy(HERE/'fixtures/gh', bindir/'gh')
            (root/'world.json').write_text('{}')
            (root/'calls.log').write_text('')
            env = {'PATH': str(bindir)+os.pathsep+os.environ['PATH'], 'FAKE_GH_WORLD': str(root/'world.json'),
                   'FAKE_GH_LOG': str(root/'calls.log')}
            for start, through in [('2030-01-01', '2030-01-03'), ('bad', '2030-01-02')]:
                r = cli('backfill', '--start-day', start, '--through-day', through,
                        '--now', '2030-01-03T18:00:00Z', '--robots', '5', '--out', Path(tmp)/'days', env=env)
                self.assertNotEqual(r.returncode, 0)
                self.assertFalse((Path(tmp)/'days').exists())
                self.assertEqual((root/'calls.log').read_text(), '')


if __name__ == '__main__':
    unittest.main(verbosity=2)
