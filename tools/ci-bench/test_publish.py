#!/usr/bin/env python3
"""Publication contract on a local bare repository, with synthetic points."""
import copy
import importlib.util
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bench_fixtures', HERE/'test.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
spec = importlib.util.spec_from_file_location('factory_fixtures', HERE/'test_factory.py')
factory_fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(factory_fixture)


def command(*args, cwd=None):
    r = subprocess.run(list(map(str, args)), cwd=cwd, capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr + r.stdout)
    return r.stdout.strip()


class Publish(unittest.TestCase):
    def test_publish_repeats_preserve_history_and_never_touch_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            remote, seed = root/'remote.git', root/'seed'
            command('git', 'init', '--bare', remote)
            command('git', 'init', '-b', 'main', seed)
            command('git', 'config', 'user.name', 'Synthetic test', cwd=seed)
            command('git', 'config', 'user.email', 'test@example.invalid', cwd=seed)
            (seed/'keep.txt').write_text('Main must remain exactly this commit.\n')
            command('git', 'add', '.', cwd=seed)
            command('git', 'commit', '-m', 'Synthetic base', cwd=seed)
            command('git', 'remote', 'add', 'origin', remote, cwd=seed)
            command('git', 'push', 'origin', 'main', cwd=seed)
            main = command('git', 'rev-parse', 'main', cwd=seed)
            windows = []
            for day in ('01', '02'):
                w = root/day
                shutil.copytree(HERE/'fixtures/window', w)
                command(sys.executable, '-I', HERE/'bench.py', 'measure', w, '--robots', '2', '--label', 'day '+day)
                p = json.loads((w/'point.json').read_text())
                p['since'], p['until'] = f'2030-01-{day}T08:00:00Z', f'2030-01-{int(day)+1:02d}T08:00:00Z'
                (w/'point.json').write_text(json.dumps(p))
                windows.append(w)
                if day == '01':
                    command(sys.executable, '-I', HERE/'publish.py', '--source', w, '--repo', seed)
            command(sys.executable, '-I', HERE/'publish.py', '--source', *windows, '--repo', seed)
            first = command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks')
            command(sys.executable, '-I', HERE/'publish.py', '--source', windows[-1], '--repo', seed)
            self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks'), first)
            self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'main'), main)
            paths = command('git', '--git-dir', remote, 'ls-tree', '-r', '--name-only', 'ci-benchmarks').splitlines()
            self.assertEqual(len([p for p in paths if p.startswith('windows/')]), 2)
            self.assertEqual(set(p for p in paths if not p.startswith('windows/')),
                             {'README.md', 'bench.md', 'baseline/point.json', 'prs-per-hour.svg',
                              'robot-minutes.svg', 'time-split.svg', 'minutes-per-pr.svg', 'daily-metrics.svg',
                              'factory-throughput.svg', 'factory-reviews.svg', 'factory-main.svg',
                              'factory-runner-wait.svg', 'buckets.md', 'buckets-6h.svg', 'buckets-1h.svg', 'journey-trends.md', 'journey-reviews.svg', 'journey-findings.svg'})
            self.assertFalse(any('jobs' in p or 'merged.json' in p or 'keep.txt' in p for p in paths))
            md = command('git', '--git-dir', remote, 'show', 'ci-benchmarks:README.md')
            self.assertLess(md.index('| day 01 | 2030'), md.index('| day 02 | 2030'))
            self.assertIn('| day 02 | 5.75', md)
            # A surprising data-branch file must stop a later publication.
            command('git', 'fetch', 'origin', 'ci-benchmarks', cwd=seed)
            command('git', 'checkout', '-b', 'ci-benchmarks', 'FETCH_HEAD', cwd=seed)
            (seed/'unexpected.txt').write_text('do not publish around this')
            command('git', 'add', '.', cwd=seed)
            command('git', 'commit', '-m', 'Plant unexpected data file', cwd=seed)
            command('git', 'push', 'origin', 'ci-benchmarks', cwd=seed)
            before = command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks')
            r = subprocess.run([sys.executable, '-I', str(HERE/'publish.py'), '--source', str(windows[0]),
                                '--repo', str(seed)], capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn('unexpected files', r.stderr)
            self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks'), before)
            self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'main'), main)

    # R6: unresolved PRs cannot also enter the known-mature denominator.
    # Earlier malformed-input cases tested rate arithmetic, but never this
    # contradictory coverage at measure/import and actual publication reads.
    def test_unknown_attribution_refuses_known_denominator_and_preserves_output(self):
        spec = importlib.util.spec_from_file_location('r6_trends', HERE/'trends.py')
        trends = importlib.util.module_from_spec(spec); spec.loader.exec_module(trends)
        source = HERE.parent/'factory-metrics/fixtures/journey'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); remote, seed, window = root/'remote.git', root/'seed', root/'window'
            command('git', 'init', '--bare', remote)
            command('git', 'init', '-b', 'main', seed)
            command('git', 'config', 'user.name', 'Synthetic R6', cwd=seed)
            command('git', 'config', 'user.email', 'r6@example.invalid', cwd=seed)
            (seed/'keep.txt').write_text('synthetic main stays unchanged\n')
            command('git', 'add', '.', cwd=seed)
            command('git', 'commit', '-m', 'Synthetic R6 base', cwd=seed)
            command('git', 'remote', 'add', 'origin', remote, cwd=seed)
            command('git', 'push', 'origin', 'main', cwd=seed)
            main = command('git', '--git-dir', remote, 'rev-parse', 'main')
            shutil.copytree(HERE/'fixtures/window', window)
            bounds = {'since':'2030-01-01T00:00:00Z','until':'2030-01-03T08:00:00Z'}
            (window/'window.json').write_text(json.dumps(bounds))
            report = trends.report(json.loads((source/'journeys.json').read_text()),
                bounds['since'], bounds['until'], outcomes=json.loads((source/'outcomes.json').read_text()))
            self.assertEqual(report['outcomes']['merged']['prs'],2)
            (window/'journey-report.json').write_text(json.dumps(report))
            measure = [sys.executable, '-I', str(HERE/'bench.py'), 'measure', str(window),
                       '--robots', '2', '--label', 'synthetic R6']
            command(*measure)
            original = (window/'point.json').read_bytes()
            baseline = root/'baseline'; baseline.mkdir()
            base = json.loads(original); base.pop('journey')
            (baseline/'point.json').write_text(json.dumps(base))
            publish = [sys.executable, '-I', str(HERE/'publish.py'), '--source', str(window),
                       '--repo', str(seed), '--baseline', str(baseline)]
            command(*publish)
            for name, unknown, known, affected, events, rate, expected in [
                ('producer control',1,1,1,1,1,0),
                ('all attribution unresolved',2,0,0,0,None,0),
                ('known zero with disjoint unresolved PR',1,1,0,0,0,0),
                ('unresolved PRs counted as known zero',2,1,0,0,0,1),
                ('zero denominator needs null',2,0,0,0,0,1),
            ]:
                candidate = copy.deepcopy(report)
                for cohort in ('all','merged'):
                    candidate['outcomes'][cohort]['defects'].update(unknown_attribution=unknown,
                        known_mature_prs=known, affected_mature_prs=affected,
                        attributable_events=events, rate=rate)
                (window/'journey-report.json').write_text(json.dumps(candidate))
                (window/'point.json').write_bytes(original)
                with self.subTest(case=name, boundary='measure/import'):
                    result = subprocess.run(measure,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode,expected,result.stderr)
                    if expected:
                        self.assertEqual((window/'point.json').read_bytes(),original)
                        self.assertIn('defect',result.stderr)
                # Supply the imported aggregate directly to the publication
                # reader as well; do not rely on measure accepting a bad file.
                point = json.loads(original); point['journey'] = candidate
                (window/'point.json').write_text(json.dumps(point))
                before = command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks')
                with self.subTest(case=name, boundary='publish/point'):
                    result = subprocess.run(publish,capture_output=True,text=True,timeout=30)
                    self.assertEqual(result.returncode,expected,result.stderr)
                    if expected:
                        self.assertIn('defect',result.stderr)
                        self.assertEqual(command('git','--git-dir',remote,'rev-parse','ci-benchmarks'),before)
                    self.assertEqual(command('git','--git-dir',remote,'rev-parse','main'),main)

    def test_publish_job_grants_the_collectors_pull_request_read_permission(self):
        workflow = (HERE.parents[1]/'.github/workflows/ci-bench.yml').read_text()
        publish = workflow.split('\n  publish:\n', 1)[1]
        block = publish.split('\n    permissions:\n', 1)[1].split('\n    concurrency:', 1)[0]
        grants = re.findall(r'^      ([a-z-]+): ([a-z]+)$', block, re.M)
        # issues: read for the factory benches' ticket timelines (#1359).
        self.assertEqual(sorted(grants), [('actions', 'read'), ('contents', 'write'), ('issues', 'read'),
                                          ('pull-requests', 'read')])

    def test_daily_script_publishes_unknown_cost_for_cancelled_run_timing_gap(self):
        self.daily(factory_fails=False)

    def test_daily_script_still_publishes_ci_when_the_factory_reads_fail(self):
        # E.g. a token without issues: read (#1359): the day's CI numbers are
        # published and its factory benches stay unknown, never 0.
        self.daily(factory_fails=True)

    def test_required_journey_read_failure_preserves_last_publication(self):
        self.daily(factory_fails=False, journey_fails=True)

    def daily(self, factory_fails, journey_fails=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, remote = root/'checkout', root/'remote.git'
            command('git', 'init', '--bare', remote)
            command('git', 'init', '-b', 'main', repo)
            command('git', 'config', 'user.name', 'Synthetic daily proof', cwd=repo)
            command('git', 'config', 'user.email', 'daily@example.invalid', cwd=repo)
            (repo/'keep.txt').write_text('synthetic main must stay unchanged\n')
            command('git', 'add', '.', cwd=repo)
            command('git', 'commit', '-m', 'Synthetic main', cwd=repo)
            command('git', 'remote', 'add', 'origin', remote, cwd=repo)
            command('git', 'push', 'origin', 'main', cwd=repo)
            main = command('git', 'rev-parse', 'main', cwd=repo)
            tools = repo/'tools/ci-bench'
            tools.mkdir(parents=True)
            for name in ('bench.py', 'steps.tsv', 'prices.tsv', 'daily.sh', 'publish.py', 'trends.py'):
                shutil.copy(HERE/name, tools/name)
            shutil.copytree(HERE.parent/'factory-metrics', repo/'tools/factory-metrics')
            baseline = repo/'private/evidence/infra-ci-scale/bench/baseline'
            baseline.mkdir(parents=True)
            (baseline/'point.json').write_text(json.dumps(fixture.WINDOW_POINT))
            since, until = '2030-07-01T08:00:00Z', '2030-07-02T08:00:00Z'
            created, start, end = '2030-07-01T09:00:00Z', '2030-07-01T09:05:00Z', '2030-07-01T09:07:00Z'
            good = fixture.gh_run(701, 'pull_request', 'success', created)
            cancelled = fixture.gh_run(703, 'pull_request', 'cancelled', created)
            jobs = [fixture.gh_job('rust', start, start, end, 'synthetic-runner',
                                  [fixture.gh_step('Run cargo test --workspace', start, end)]),
                    fixture.gh_job('web-build', start, start, created, 'synthetic-runner',
                                   [fixture.gh_step('Set up job', created, created)])]
            answers = {f'api repos/{{owner}}/{{repo}}/actions/workflows/ci.yml/runs?created={since}..{until}&status=completed&per_page=100&page=1':
                       {'total_count': 2, 'workflow_runs': [good, cancelled]}, fixture.pulls_call(1): []}
            answers.update(factory_fixture.quiet_day(since, until))
            for run, job in zip((good, cancelled), jobs):
                answers[fixture.jobs_call(run['id'], 1)] = {'total_count': 1, 'jobs': [job]}
                answers[fixture.run_call(run['id'])] = run
            # Selector escapes (#1264): no full run on main that day, so 0.
            # main's runs a day at a time, as test.py's Escapes do.
            escapes = fixture.main_lists(since, until)
            for call in escapes:
                answers[call] = {'total_count': 0, 'workflow_runs': []}
            world = {k: {'stdout': json.dumps(v), 'exit': 0} for k, v in answers.items()}
            world['repo view --json nameWithOwner'] = {'stdout': json.dumps({'nameWithOwner': 'example/factory'}), 'exit': 0}
            m = factory_fixture.module('metrics_for_fixture', HERE.parent/'factory-metrics/metrics.py')
            inventory_call = ' '.join(['api', 'graphql', '-f', 'query='+m.QUERY, '-f', 'owner=example', '-f', 'name=factory'])
            world[inventory_call] = {'stdout': json.dumps({'data': {'repository': {'pullRequests': {
                'nodes': [], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}), 'exit': 0}
            if journey_fails:
                world[inventory_call] = {'stdout': '', 'exit': 1}
                seed = root/'seed'; shutil.copytree(HERE/'fixtures/window', seed)
                command(sys.executable, '-I', HERE/'bench.py', 'measure', seed, '--robots', '5', '--label', 'last good')
                command(sys.executable, '-I', HERE/'publish.py', '--source', seed, '--repo', repo)
                previous = command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks')
            if factory_fails:
                world[factory_fixture.gql_call()] = {'stdout': '', 'exit': 1}
                world[escapes[0]] = {'stdout': '', 'exit': 1}
            (root/'world.json').write_text(json.dumps(world))
            bindir = root/'bin'
            bindir.mkdir()
            shutil.copy(HERE/'fixtures/gh', bindir/'gh')
            log = root/'calls.log'
            log.write_text('')
            env = dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ['PATH'],
                       FAKE_GH_WORLD=str(root/'world.json'), FAKE_GH_LOG=str(log),
                       BENCH_SINCE=since, BENCH_UNTIL=until, BENCH_LABEL='2030-07-01 PST', BENCH_ROBOTS='5')
            r = subprocess.run(['sh', str(tools/'daily.sh')], cwd=repo, env=env,
                               capture_output=True, text=True, timeout=30)
            if journey_fails:
                self.assertEqual(r.returncode, 1, r.stdout+r.stderr)
                self.assertIn('trends: gh read failed', r.stderr)
                self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'ci-benchmarks'), previous)
                self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'main'), main)
                return
            self.assertEqual(r.returncode, 0, r.stdout+r.stderr)
            md = command('git', '--git-dir', remote, 'show', 'ci-benchmarks:README.md')
            if factory_fails:
                self.assertIn('factory benches unknown', r.stderr)
                self.assertIn('selector escapes unknown', r.stderr)
                self.assertEqual(len(log.read_text().splitlines()), 8)
                self.assertIn('| 2030-07-01 PST | 0 | unknown | unknown | unknown | unknown | unknown | unknown | unknown | unknown |', md)
            else:
                self.assertEqual(len(log.read_text().splitlines()), 39 + 31 + 3)
                # A day with no merges, no push to main and (in the factory's
                # run lists) no run: counts known, the rest unknown, never 0.
                self.assertIn('| 2030-07-01 PST | 0 | unknown | unknown | unknown | unknown | unknown |'
                              ' 0 (0 flaky, 0 runner/network, 0 after a pass, 0 after a cancel, 0 unknown) | unknown | unknown |', md)
            day = [line for line in md.splitlines() if line.startswith(f'| 2030-07-01 PST | {since} ')]
            self.assertEqual(len(day), 1)
            self.assertTrue(day[0].endswith(' | unknown |' if factory_fails else ' | 0 |'), day[0])
            paths = command('git', '--git-dir', remote, 'ls-tree', '-r', '--name-only', 'ci-benchmarks').splitlines()
            points = [p for p in paths if p.startswith('windows/') and p.endswith('/point.json')]
            self.assertEqual(len(points), 1)
            point = json.loads(command('git', '--git-dir', remote, 'show', 'ci-benchmarks:'+points[0]))
            self.assertIsNone(point['cost']['window_usd'])
            self.assertEqual(point['cost']['unknown_jobs'], 1)
            self.assertEqual(point['code_runs']['queued_to_done']['median'], 7)
            self.assertEqual(point['code_runs']['prs_per_hour'], 150)
            self.assertIn('unknown duration (1 unsuccessful-run jobs)', command('git', '--git-dir', remote, 'show', 'ci-benchmarks:README.md'))
            self.assertEqual(command('git', '--git-dir', remote, 'rev-parse', 'main'), main)

    def test_publication_workflow_has_read_only_tests_and_one_main_only_writer(self):
        workflow = (HERE.parents[1]/'.github/workflows/ci-bench.yml').read_text()
        self.assertIn('contents: read', workflow)
        self.assertEqual(workflow.count('contents: write'), 1)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("github.event_name != 'pull_request'", workflow)
        self.assertIn("cron: '17 8 * * *'", workflow)
        self.assertIn('test_dashboard.py', workflow)
        self.assertIn('test_publish.py', workflow)
        self.assertIn('python3 -I tools/ci-bench/test_factory.py', workflow)
        self.assertIn('python3 -I tools/ci-bench/test_trends.py', workflow)
        self.assertIn('python3 -I tools/factory-metrics/test_journey.py', workflow)
        self.assertIn('test.py', workflow)
        self.assertNotIn('pull_request_target:', workflow)
        self.assertNotIn('secrets.', workflow)


if __name__ == '__main__':
    unittest.main(verbosity=2)
