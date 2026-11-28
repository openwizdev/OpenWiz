#!/usr/bin/env python3
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
JOURNEY = HERE / 'journey.py'
FIXTURES = HERE / 'fixtures'
BENCH_DOC = HERE.parent.parent / 'docs' / 'bench.md'
REPO = 'example/openwiz-bench-20261128t100000z'


class Journey(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.bench = self.tmp / 'bench.md'

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_fixture(self, name, *extra):
        run_dir = self.tmp / name
        shutil.copytree(FIXTURES / name, run_dir)
        if (run_dir / 'bench.md').exists():
            shutil.copy(run_dir / 'bench.md', self.bench)
        r = subprocess.run([sys.executable, '-I', str(JOURNEY), '--dry-run', str(run_dir),
                            '--owner', 'example', '--agent', 'fake-agent --print',
                            '--wizsite', '/wizsite', '--bench-file', str(self.bench), *extra],
                           capture_output=True, text=True, timeout=60)
        ran = [json.loads(line) for line in (run_dir / 'ran.jsonl').read_text().splitlines()] \
            if (run_dir / 'ran.jsonl').exists() else []
        return r, ran, run_dir

    def rows(self):
        return [line for line in self.bench.read_text().splitlines() if line.startswith('| Real-user |')]

    def test_one_command_prints_the_time_and_the_checker_result_and_lands_the_row(self):
        r, ran, run_dir = self.run_fixture('merged')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, (run_dir / 'expected.txt').read_text())
        self.assertEqual(self.rows(), ['| Real-user | none | 23:30 | 5/5 pages agree | 2026-11-28 |'])
        self.assertTrue(self.bench.read_text().startswith('# Bench\n'))
        self.assertNotIn('dummy-token', r.stdout + r.stderr)

    def test_the_journey_runs_in_order_and_ends_by_deleting_the_repository(self):
        _, ran, _ = self.run_fixture('merged')
        argv = [c['argv'] for c in ran]
        self.assertEqual([a[:3] for a in argv[:2]], [['gh', 'repo', 'create'], ['gh', 'repo', 'clone']])
        self.assertEqual(argv[0][3:], [REPO, '--public', '--add-readme'])
        self.assertEqual(argv[2][:2], ['fake-agent', '--print'])
        self.assertIn('Install OpenWiz from github.com/openwizdev/OpenWiz', argv[2][-1])
        self.assertIn(REPO, argv[2][-1])
        self.assertIn(['node', '/wizsite/scripts/live-check.mjs', '--repo', REPO, '--prod', '--json'], argv)
        self.assertEqual(argv[-1], ['gh', 'repo', 'delete', REPO, '--yes'])
        checker = next(c for c in ran if c['argv'][0] == 'node')
        self.assertEqual(checker['env'], ['GH_TOKEN'])

    def test_a_refused_delete_archives_and_a_failed_page_fails_the_run(self):
        r, ran, run_dir = self.run_fixture('archived')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout, (run_dir / 'expected.txt').read_text())
        self.assertEqual([c['argv'][:3] for c in ran[-2:]],
                         [['gh', 'repo', 'delete'], ['gh', 'repo', 'archive']])

    def test_the_row_replaces_only_its_own_line_and_carries_now_into_before(self):
        self.run_fixture('archived')
        text = self.bench.read_text()
        self.assertEqual(self.rows(), ['| Real-user | 23:30 | 85:05 | 4/5 pages agree | 2026-11-28 |'])
        self.assertIn('| Bench | Before | Now | Pages | Run |', text)
        self.bench.write_text(text + '| Other | 1 | 2 | - | 2026-11-01 |\n')
        self.run_fixture('merged', '--timeout', '3600')
        self.assertEqual(self.rows(), ['| Real-user | 85:05 | 23:30 | 5/5 pages agree | 2026-11-28 |'])
        self.assertIn('| Other | 1 | 2 | - | 2026-11-01 |', self.bench.read_text())

    def test_no_merge_within_the_timeout_still_checks_and_removes_the_repository(self):
        r, ran, run_dir = self.run_fixture('unmerged', '--timeout', '1800', '--poll', '600')
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout, (run_dir / 'expected.txt').read_text())
        self.assertEqual(ran[-1]['argv'], ['gh', 'repo', 'delete', REPO, '--yes'])

    def test_a_failure_mid_journey_still_removes_the_repository(self):
        run_dir = self.tmp / 'broken'
        shutil.copytree(FIXTURES / 'merged', self.tmp / 'broken')
        calls = json.loads((run_dir / 'calls.json').read_text())
        calls['rules'] = [r for r in calls['rules'] if r['argv'][0] != 'node']
        (run_dir / 'calls.json').write_text(json.dumps(calls))
        r = subprocess.run([sys.executable, '-I', str(JOURNEY), '--dry-run', str(run_dir),
                            '--owner', 'example', '--agent', 'fake-agent', '--wizsite', '/wizsite',
                            '--bench-file', str(self.bench)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 2)
        self.assertIn('no fixture answer for: node', r.stderr)
        self.assertIn('Repository removed: deleted', r.stdout)
        self.assertFalse(self.bench.exists())

    def test_a_failed_create_touches_nothing_else(self):
        run_dir = self.tmp / 'nocreate'
        shutil.copytree(FIXTURES / 'merged', run_dir)
        calls = json.loads((run_dir / 'calls.json').read_text())
        calls['rules'][0].update(code=1, stdout='', stderr='name already exists\n')
        (run_dir / 'calls.json').write_text(json.dumps(calls))
        r = subprocess.run([sys.executable, '-I', str(JOURNEY), '--dry-run', str(run_dir),
                            '--owner', 'example', '--agent', 'fake-agent', '--wizsite', '/wizsite',
                            '--bench-file', str(self.bench)], capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn('could not create the repository: name already exists', r.stderr)
        ran = (run_dir / 'ran.jsonl').read_text().splitlines()
        self.assertEqual(len(ran), 1)
        self.assertFalse(self.bench.exists())


class Doc(unittest.TestCase):
    def test_docs_bench_has_exactly_one_real_user_row(self):
        lines = BENCH_DOC.read_text().splitlines()
        self.assertIn('| Bench | Before | Now | Pages | Run |', lines)
        self.assertEqual(len([line for line in lines if line.startswith('| Real-user |')]), 1)


if __name__ == '__main__':
    unittest.main()
