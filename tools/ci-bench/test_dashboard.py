#!/usr/bin/env python3
"""#1252: public CLI proofs on synthetic data; no network or dependencies."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('bench', HERE / 'bench.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def cli(*args, cwd=None):
    return subprocess.run([sys.executable, '-I', str(HERE / 'bench.py'), *map(str, args)],
                          capture_output=True, text=True, cwd=cwd, timeout=30)


class Dashboard(unittest.TestCase):
    def test_steps_cover_workflow_and_reject_planted_drift(self):
        r = cli('check-steps')
        self.assertEqual(r.returncode, 0, r.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            workflow = Path(tmp) / 'ci.yml'
            workflow.write_text((HERE.parents[1] / '.github/workflows/ci.yml').read_text()
                                + '\n      - name: A newly planted unknown CI step\n        run: true\n')
            r = cli('check-steps', '--workflow', workflow)
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertIn('A newly planted unknown CI step', r.stderr)

    def window(self, root, unknown=False):
        root.mkdir()
        (root / 'window.json').write_text(json.dumps({'since': '2030-01-01T08:00:00Z',
                                                    'until': '2030-01-02T08:00:00Z'}))
        (root / 'merged.json').write_text('[]')
        rows = []
        # Two successful code runs: 1 PC minute + 2 GitHub minutes.
        # A failed run adds 2 GitHub minutes to the day's cost, not per-code cost.
        for rid, start, end, labels, outcome in [
            (1, '00', '01', ['self-hosted', 'Linux', 'X64'], 'success'),
            (2, '02', '04', ['ubuntu-24.04'], 'success'),
            (3, '05', '07', ['ubuntu-24.04'], 'failure')]:
            a, b = '2030-01-01T09:'+start+':00Z', '2030-01-01T09:'+end+':00Z'
            rows.append(dict(run=rid, event='pull_request', name='rust', run_concl=outcome,
                             conclusion=outcome, created_at=a, started_at=a, completed_at=b,
                             runner_name='synthetic', runner_labels=(['mystery'] if unknown and rid == 2 else labels),
                             steps=[dict(name='Run cargo test --workspace', conclusion=outcome,
                                         started_at=a, completed_at=b)]))
        (root / 'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        return root

    def test_site_affected_step_is_covered_and_counted_as_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workflow = root/'ci.yml'
            workflow.write_text('jobs:\n  web-test:\n    steps:\n'
                                '      - name: Whether the site can be affected\n        run: true\n')
            r = cli('check-steps', '--workflow', workflow)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout.strip(), 'covered 1 CI steps')
            w = self.window(root/'window')
            rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
            rows[1]['name'] = 'web-test'
            rows[1]['steps'][0]['completed_at'] = '2030-01-01T09:03:00Z'
            rows[1]['steps'].append(dict(name='Whether the site can be affected', conclusion='success',
                started_at='2030-01-01T09:03:00Z', completed_at='2030-01-01T09:04:00Z'))
            (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            r = cli('measure', w, '--robots', '5', '--label', 'synthetic site selection')
            self.assertEqual(r.returncode, 0, r.stderr)
            code = json.loads((w/'point.json').read_text())['code_runs']
            # Successful runs: 1 min Rust + (1 min Rust, 1 min setup), /2.
            self.assertEqual(code['robot_minutes_per_run'], 1.5)
            self.assertEqual(code['categories']['setup'], 0.5)
            self.assertEqual(code['categories']['rust'], 1)
            self.assertEqual(code['split']['running'], 1)

    def test_web_root_and_cache_volume_steps_count_as_setup(self):
        for step_name in ('One device for the web roots', 'The cache volume', 'Mount the cargo-rust cache volume'):
            with self.subTest(step=step_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                w = self.window(root/'window')
                rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
                rows[1]['name'] = 'web-test'
                rows[1]['steps'][0]['completed_at'] = rows[1]['steps'][0]['started_at']
                rows[1]['steps'].append(dict(name=step_name, conclusion='success',
                    started_at='2030-01-01T09:02:00Z', completed_at='2030-01-01T09:04:00Z'))
                (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
                r = cli('measure', w, '--robots', '5', '--label', 'synthetic web setup')
                self.assertEqual(r.returncode, 0, r.stderr)
                code = json.loads((w/'point.json').read_text())['code_runs']
                # Two runs: one minute Rust plus two minutes setup, divided by 2.
                self.assertEqual(code['robot_minutes_per_run'], 1.5)
                self.assertEqual(code['categories']['setup'], 1)
                self.assertEqual(code['categories']['rust'], 0.5)
                self.assertEqual(code['split']['running'], 0.5)

    def test_costs_are_hand_worked_and_unknown_stays_unknown(self):
        for unknown in (False, True):
            with self.subTest(unknown=unknown), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                w = self.window(root / 'day', unknown)
                prices = root / 'prices.tsv'
                prices.write_text('runner_kind\tcompute_usd_per_minute\tplatform_usd_per_minute\tsource_url\tverified_on\n'
                                  'self-hosted\t0\t0.002\thttps://example.invalid/pc\t2030-01-01\n'
                                  'github-hosted\t0.006\t0\thttps://example.invalid/gh\t2030-01-01\n')
                r = cli('measure', w, '--robots', '5', '--label', 'day', '--prices', prices)
                self.assertEqual(r.returncode, 0, r.stderr)
                cost = json.loads((w/'point.json').read_text())['cost']
                self.assertEqual(cost['window_usd'], None if unknown else 0.026)
                self.assertEqual(cost['per_code_run_usd'], None if unknown else 0.007)
                self.assertEqual(cost['runner_minutes']['github-hosted'], 2 if unknown else 4)
                self.assertEqual(cost['runner_minutes']['self-hosted'], 1)
                if unknown:
                    self.assertEqual(cost['runner_minutes']['unknown'], 2)
                    self.assertEqual(cost['unknown_minutes'], 2)

    def jog_window(self, root, label='jog-16vcpu', merged=(101, 102)):
        w = self.window(root)
        rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
        for row in rows:
            row['runner_labels'] = ['Linux', 'X64', label]
            row['run_created_at'] = row['created_at']
        rows[2]['completed_at'] = rows[2]['steps'][0]['completed_at'] = '2030-01-01T09:05:30Z'
        (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
        (w/'merged.json').write_text(json.dumps([
            {'number': n, 'merged_at': '2030-01-01T10:00:00Z'} for n in merged]))
        return w

    def test_jog_published_prices_and_second_billing(self):
        for label, total, per_run in [('jog-4vcpu', 0.0084, 0.0036),
                                      ('jog-8vcpu', 0.0154, 0.0066),
                                      ('jog-16vcpu', 0.0308, 0.0132)]:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                w = self.jog_window(Path(tmp)/'day', label)
                r = cli('measure', w, '--robots', '5', '--label', 'synthetic Jog day')
                self.assertEqual(r.returncode, 0, r.stderr)
                cost = json.loads((w/'point.json').read_text())['cost']
                print(f"{label}: window USD={cost['window_usd']!r}; expected {total}")
                self.assertEqual(cost['window_usd'], total)
                self.assertEqual(cost['per_code_run_usd'], per_run)
                self.assertEqual(cost['billed_minutes'], {label: 3.5})
                price = next(row for row in cost['prices'] if row['runner_kind'] == label)
                self.assertEqual(price['source_url'], 'https://usejog.com/docs/pricing/')
                self.assertEqual(price['verified_on'], '2026-11-14')

    def test_fractional_jog_billed_minutes_display_rounded_stored_exact(self):
        # #2839: per-second Jog billing makes billed minutes fractional; the
        # dashboard rounds the cell to 4 places, the point keeps the exact sum.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self.jog_window(root/'day', 'jog-8vcpu')
            rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
            rows[2]['completed_at'] = rows[2]['steps'][0]['completed_at'] = '2030-01-01T09:05:37Z'
            (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            r = cli('measure', w, '--robots', '5', '--label', 'synthetic Jog day')
            self.assertEqual(r.returncode, 0, r.stderr)
            cost = json.loads((w/'point.json').read_text())['cost']
            # 1 + 2 + 37/60 minutes, unrounded; $0.0044/min * 217/60 = $0.015913.
            self.assertEqual(cost['billed_minutes'], {'jog-8vcpu': 1 + 2 + 37/60})
            self.assertEqual(cost['window_usd'], 0.015913)
            out = root/'dashboard'
            r = cli('dashboard', w, '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            readme = (out/'README.md').read_text()
            self.assertIn('| synthetic Jog day | jog-8vcpu | 3.6167 | 3.6167 | $0.0159 |', readme)
            self.assertNotIn('3.6166666666666667', readme)

    def test_unpriced_or_ambiguous_jog_never_falls_back_to_free_self_hosted(self):
        for label in ('jog-unknown', 'jog-max-16vcpu', 'jog-4vcpu'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                w = self.jog_window(Path(tmp)/'day', label)
                rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
                for row in rows:
                    row['runner_labels'].append('self-hosted')
                    if label == 'jog-4vcpu':
                        row['runner_labels'].append('jog-16vcpu')
                (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
                r = cli('measure', w, '--robots', '5', '--label', 'synthetic unknown Jog')
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIsNone(json.loads((w/'point.json').read_text())['cost']['window_usd'])

    def jog_days(self, root):
        windows = []
        # Day 2 has 3 merged PRs but 2 successful code runs, so the two USD denominators differ.
        for day, label, merged in [(1, 'jog-8vcpu', (101, 102)), (2, 'jog-16vcpu', (101, 102, 103))]:
            w = self.jog_window(root/str(day), label, merged)
            if day == 2:
                for name in ('window.json', 'jobs.jsonl', 'merged.json'):
                    path = w/name
                    path.write_text(path.read_text().replace('2030-01-02', '2030-01-03')
                                    .replace('2030-01-01', '2030-01-02'))
            r = cli('measure', w, '--robots', '5', '--label', f'2030-01-0{day} PST')
            self.assertEqual(r.returncode, 0, r.stderr)
            windows.append(w)
        return windows

    def test_cost_headlines_and_daily_deltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            windows = self.jog_days(root)
            out = root/'dashboard'
            r = cli('dashboard', *windows, '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            # Hand-worked: day 1 $0.0154 / 2 merged = $0.0077; day 2 $0.0308 / 3 merged = $0.010267,
            # shown $0.0103 (its 2 code runs would give $0.0154); change +$0.002567, shown +$0.0026.
            # USD/code run: $0.0066, then $0.0132; change +$0.0066.
            # Window cost: $0.0154, then $0.0308; change +$0.0154.
            for name in ('README.md', 'bench.md'):
                md = (out/name).read_text()
                self.assertIn('| Window | Minutes per PR (median) | PRs/hour capacity | Window cost | USD/merged PR | USD/code run |', md)
                self.assertIn('| 2030-01-02 PST | 1.50 | 200.00 | $0.0308 | $0.0103 | $0.0132 |', md)
                self.assertIn('| Day-over-day (latest full PST day) | +0.00 | +0.00 | +$0.0154 | +$0.0026 | +$0.0066 |', md)
            svg = (out/'daily-metrics.svg').read_text()
            for text in ('USD per merged PR', 'USD per code run', '2030-01-01: $0.0077', '2030-01-02: $0.0103',
                         'day-over-day +$0.0026', '2030-01-01: $0.0066', '2030-01-02: $0.0132', 'day-over-day +$0.0066'):
                self.assertIn(text, svg)
            self.assertIn('| 2030-01-02 PST | jog-16vcpu | 3.5000 | 3.5000 | $0.0308 |',
                          (out/'README.md').read_text())

    def test_cost_daily_change_does_not_bridge_unknown_or_missing_days(self):
        for missing in ('cost', 'merges', 'day', 'price'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                windows = self.jog_days(root)
                path = windows[1]/'point.json'
                point = json.loads(path.read_text())
                if missing == 'cost':
                    point.pop('cost')  # historical points remain readable
                elif missing == 'price':
                    point['cost']['window_usd'] = point['cost']['per_code_run_usd'] = None
                elif missing == 'merges':
                    point['merged_prs'] = 0
                    point['merged_per_hour'] = 0
                else:
                    point.update(since='2030-01-03T08:00:00Z', until='2030-01-04T08:00:00Z',
                                 label='2030-01-03 PST')
                path.write_text(json.dumps(point))
                out = root/'dashboard'
                r = cli('dashboard', *windows, '--out', out)
                self.assertEqual(r.returncode, 0, r.stderr)
                svg = (out/'daily-metrics.svg').read_text()
                self.assertNotIn('+$0.0026', svg)
                if missing != 'merges':
                    self.assertNotIn('+$0.0066', svg)
                self.assertIn('day-over-day unknown', svg)
                if missing != 'day':
                    self.assertRegex(svg, r'class="cost-hero"[^>]*>unknown</text>')

    def test_dashboard_readme_and_four_charts_on_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self.window(root/'day', True)
            self.assertEqual(cli('measure', w, '--robots', '5', '--label', '2030-01-01 PST').returncode, 0)
            out = root/'dashboard'
            r = cli('dashboard', w, '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            md = (out/'README.md').read_text()
            for text in ['2026-11-01 baseline', '2030-01-01 PST', 'Tonight', 'This week', 'North star',
                         '< 10', '25+', '< 3', '80+', '< 1', '500+', 'unknown', '1.50']:
                self.assertIn(text, md)
            self.assertIn('| Tonight | < 10 | 25+ | — | — |', md)
            self.assertNotIn('| Tonight | < 15 |', md)
            for name in ['prs-per-hour.svg', 'robot-minutes.svg', 'time-split.svg', 'minutes-per-pr.svg']:
                self.assertIn(']('+name+')', md)
                self.assertIn('<svg', (out/name).read_text())


    def test_empty_day_is_a_gap_with_cost_never_zero_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self.window(root/'empty')
            rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
            for row in rows:
                row['run_concl'] = row['conclusion'] = 'failure'
                row['steps'][0]['conclusion'] = 'failure'
            (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            r = cli('measure', w, '--robots', '5', '--label', 'empty day', '--allow-empty')
            self.assertEqual(r.returncode, 0, r.stderr)
            point = json.loads((w/'point.json').read_text())
            self.assertIsNone(point['code_runs'])
            self.assertIsNone(point['cost']['per_code_run_usd'])
            self.assertEqual(point['cost']['window_usd'], 0.024)
            out = root/'dashboard'
            r = cli('dashboard', w, '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('| empty day | unknown | unknown | $0.0240 | unknown | unknown |', (out/'README.md').read_text())
            self.assertIn('no successful code runs', (out/'README.md').read_text())
            self.assertNotIn('empty day', (out/'minutes-per-pr.svg').read_text())

    def test_unknown_price_and_invalid_price_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self.window(root/'day')
            prices = root/'prices.tsv'
            header = 'runner_kind\tcompute_usd_per_minute\tplatform_usd_per_minute\tsource_url\tverified_on\n'
            prices.write_text(header+'github-hosted\tunknown\t0.002\thttps://example.invalid/rate\t2030-01-01\n')
            r = cli('measure', w, '--robots', '5', '--label', 'unknown price', '--prices', prices)
            self.assertEqual(r.returncode, 0, r.stderr)
            cost = json.loads((w/'point.json').read_text())['cost']
            self.assertIsNone(cost['window_usd'])
            self.assertIsNone(cost['per_code_run_usd'])
            self.assertEqual(cost['unknown_minutes'], 5)
            for bad in ('NaN', '-1', 'invalid'):
                (w/'point.json').unlink(missing_ok=True)
                prices.write_text(header+f'github-hosted\t{bad}\t0\thttps://example.invalid/rate\t2030-01-01\n')
                r = cli('measure', w, '--robots', '5', '--label', 'bad', '--prices', prices)
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertFalse((w/'point.json').exists())

    def test_each_hosted_job_rounds_up_and_steps_have_right_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            w = self.window(root/'day')
            rows = [json.loads(line) for line in (w/'jobs.jsonl').read_text().splitlines()]
            rows[1]['completed_at'] = rows[1]['steps'][0]['completed_at'] = '2030-01-01T09:04:01Z'
            a = rows[0]['steps'][0]
            a['completed_at'] = a['started_at'] # keep the successful code-run marker, no extra time
            for name, start, end in [('Python for the offline installer and release proofs', '00:00', '00:20'),
                                     ('Image skill browser dependencies', '00:20', '00:40'),
                                     ('The setup contract reader', '00:40', '01:00')]:
                rows[0]['steps'].append(dict(name=name, conclusion='success',
                    started_at='2030-01-01T09:'+start+'Z', completed_at='2030-01-01T09:'+end+'Z'))
            (w/'jobs.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            r = cli('measure', w, '--robots', '5', '--label', '<script>|newline\nlabel')
            self.assertEqual(r.returncode, 0, r.stderr)
            point = json.loads((w/'point.json').read_text())
            self.assertEqual(point['cost']['window_usd'], 0.030)
            self.assertEqual(point['cost']['per_code_run_usd'], 0.009)
            self.assertEqual(point['cost']['billed_minutes']['github-hosted'], 5)
            self.assertEqual(point['code_runs']['categories']['setup'], 0.3333)
            self.assertEqual(point['code_runs']['categories']['skills'], 0.1667)
            out = root/'out'
            r = cli('dashboard', w, '--out', out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('&lt;script&gt;\\|newline label', (out/'README.md').read_text())
            self.assertNotIn('<script>', (out/'minutes-per-pr.svg').read_text())

    def test_default_baseline_from_another_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = cli('chart', '--out', Path(tmp)/'charts', cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)

    def test_pst_day_boundaries(self):
        # Fixed PST is UTC-08:00 even in summer; no DST-day ambiguity.
        self.assertEqual(bench.pst_window('2030-07-02T07:59:00Z'),
                         ('2030-06-30T08:00:00Z', '2030-07-01T08:00:00Z'))
        self.assertEqual(bench.pst_window('2030-07-02T08:00:00Z'),
                         ('2030-07-01T08:00:00Z', '2030-07-02T08:00:00Z'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
