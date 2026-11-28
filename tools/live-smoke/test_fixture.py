#!/usr/bin/env python3
from contextlib import contextmanager, redirect_stderr
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest

DESCRIPTION = """Small integration with the repository's real fixture dispatch and Rust fake.

This proves the runner reaches the real bundle/adapter boundary, not live
feature acceptance. The synthetic workflow's other labels exercise sequencing.
No browser, product daemon or live endpoint is used.
"""

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CLAIMS = ['fleet', 'swarms', 'service', 'loops', 'cockpit', 'decisions',
          'json', 'send', 'new', 'app', 'read_safety']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def world(cli, fake):
    with tempfile.TemporaryDirectory(prefix='live-smoke-fixture-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        room = root / 'room-cli'
        room.symlink_to(fake)
        scenario = json.loads((ROOT / 'tests/fixtures/room-cli-0.43.1/normal/scenario.json').read_text())
        fixture_root = ROOT / 'tests/fixtures/room-cli-0.43.1/normal'
        for response in scenario['responses']:
            if response['argv'][0:2] == ['thread', 'list']:
                response.pop('stdout_file', None)
                response['stdout'] = '[]'
            elif 'stdout_file' in response:
                response['stdout_file'] = str(fixture_root / response['stdout_file'])
        scenario_file = root / 'scenario.json'
        scenario_file.write_text(json.dumps(scenario))
        (root / 'fake-room-cli.scenario').write_text(str(scenario_file))
        kit = {'schema': 'openwiz.live-smoke-kit.v1', 'mode': 'fixture',
               'cwd': str(root), 'openwiz': str(cli),
               'artifacts': {str(cli): sha(cli), str(fake): sha(fake), str(room): sha(fake)},
               'env': {'OPENWIZ_FIXTURE_PROGRAM': str(room), 'OPENWIZ_STATE_DIR': str(root / 'product-state')},
               'timeout_seconds': 10, 'steps': []}
        for claim in CLAIMS:
            kit['steps'].append({'id': claim, 'claim': claim,
                'kind': 'write' if claim in ('fleet', 'send', 'new') else 'read',
                'argv': [str(cli), 'help', '--agent'], 'exit': 0,
                'checks': [{'path': '/schema', 'equals': 'openwiz.cli.v1'},
                           {'path': '/kind', 'equals': 'catalogue'}]})
        kit['steps'].append({'id': 'inventory_actual', 'claim': 'json', 'kind': 'read',
            'argv': [str(cli), 'ls', '--json'], 'exit': 0,
            'checks': [{'path': '/data/sessions', 'equals': []}]})
        yield root, kit, scenario, scenario_file


def integration(cli, fake):
    with world(cli, fake) as (root, kit, scenario, scenario_file):
        path = root / 'kit.json'
        path.write_text(json.dumps(kit))
        argv = [sys.executable, '-I', str(HERE / 'smoke.py'), '--kit', str(path),
                '--state', str(root / 'checkpoint')]
        dry = subprocess.run(argv + ['--dry-run'], capture_output=True, text=True, timeout=30)
        assert dry.returncode == 0 and json.loads(dry.stdout)['verdict'] == 'not_run'
        assert not (root / 'invocations.log').exists(), 'dry run must execute no fake'
        result = subprocess.run(argv + ['--fixture'], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        doc = json.loads(result.stdout)
        assert doc['evidence'] == 'fixture' and doc['verdict'] == 'pass'
        assert doc['claims'] == {c: 'pass' for c in CLAIMS}
        calls = [json.loads(line) for line in (root / 'invocations.log').read_text().splitlines()]
        assert len(calls) == 8, len(calls)
        assert calls.count(['thread', 'list', '--json']) == 2
        assert not any(c[:2] in (['thread', 'tell'], ['thread', 'spawn']) for c in calls)
        scenario['responses'].insert(0, {'argv': ['thread', 'list', '--json'], 'stdout': '', 'exit_code': 1})
        scenario_file.write_text(json.dumps(scenario))
        failed = subprocess.run(argv + ['--fixture'], capture_output=True, text=True, timeout=30)
        assert failed.returncode == 3, failed.stdout
        assert json.loads(failed.stdout)['reason'] == 'bundle_preflight'
        print(json.dumps({'fixture_dispatch': 'pass', 'dry_run': 'not_run',
                          'guard_refusal': 'pass', 'live': 'not_run', 'initial_fake_reads': len(calls)}))



KEEPER = 'test_smoke.Sheet.test_driver_steps_start_wake_and_stop_one_run_through_the_runner'
RETIRED_RECEIPT_CASES = {
    'ready-preview': KEEPER,
    'accepted-send': KEEPER,
    'queued-send': KEEPER,
}


CLI_OPTIONS = frozenset(('-h', '--help', '--cli', '--fake', '--case'))


def argument_parser():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--fake', required=True, type=Path)
    parser.add_argument('--case', choices=['integration'], default='integration')
    return parser


def is_cli_argv(argv):
    for token in argv:
        if token == '--':
            break
        if token.partition('=')[0] in CLI_OPTIONS:
            return True
    return False


class RetiredReceiptCases(unittest.TestCase):
    def test_receipt_case_is_gone(self):
        self.assertEqual([name for name in globals() if name == 'receipt_case'], [])

    def test_retired_receipt_cases_are_refused_and_name_their_keeper(self):
        parser = argument_parser()
        sink = io.StringIO()
        for case, keeper in RETIRED_RECEIPT_CASES.items():
            with self.subTest(case=case):
                with redirect_stderr(sink):
                    with self.assertRaises(SystemExit) as caught:
                        parser.parse_args(['--cli', 'synthetic-cli', '--fake', 'synthetic-fake', '--case', case])
                self.assertEqual(caught.exception.code, 2)
                self.assertEqual(keeper, KEEPER)
        self.assertEqual(parser.parse_args(['--cli', 'synthetic-cli', '--fake', 'synthetic-fake']).case, 'integration')
        self.assertTrue(callable(integration))
        method = KEEPER.rpartition('.')[2]
        sheet = runpy.run_path(str(HERE / 'test_smoke.py'))['Sheet']
        self.assertTrue(callable(getattr(sheet, method)))

    def test_cli_argument_forms_route_through_argparse(self):
        script = str(Path(__file__).resolve())
        argparse_errors = [
            (['--cli=synthetic-cli', '--fake=synthetic-fake', '--case=ready-preview'],
             "invalid choice: 'ready-preview'"),
            (['--cli=synthetic-cli', '--case', 'integration'],
             'the following arguments are required: --fake'),
            (['--fake=synthetic-fake', '--case=integration'],
             'the following arguments are required: --cli'),
        ]
        for argv, expected in argparse_errors:
            with self.subTest(argv=argv):
                run = subprocess.run([sys.executable, '-I', script, *argv],
                                     capture_output=True, text=True, timeout=30)
                self.assertEqual(run.returncode, 2)
                self.assertIn(expected, run.stderr)
                self.assertNotIn('unrecognized arguments', run.stderr)

        with tempfile.TemporaryDirectory(prefix='live-smoke-cli-dispatch-') as tmp:
            cli = str(Path(tmp) / 'missing-cli')
            fake = str(Path(tmp) / 'missing-fake')
            for argv in (
                [f'--cli={cli}', f'--fake={fake}', '--case', 'integration'],
                [f'--cli={cli}', f'--fake={fake}', '--case=integration'],
            ):
                with self.subTest(argv=argv):
                    run = subprocess.run([sys.executable, '-I', script, *argv],
                                         capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(run.returncode, 2, run.stderr)
                    self.assertNotIn('unrecognized arguments', run.stderr)
                    self.assertIn('FileNotFoundError', run.stderr)

    def test_dispatch_routes_cli_and_unittest_invocations(self):
        expected = (Path('synthetic-cli').resolve(), Path('synthetic-fake').resolve())
        for argv in (
            ['--cli', 'synthetic-cli', '--fake', 'synthetic-fake'],
            ['--cli=synthetic-cli', '--fake=synthetic-fake', '--case', 'integration'],
            ['--cli=synthetic-cli', '--fake=synthetic-fake', '--case=integration'],
            ['--fake=synthetic-fake', '--cli=synthetic-cli'],
        ):
            with self.subTest(cli_argv=argv):
                calls, tests = [], []
                dispatch(argv, run_integration=lambda c, f: calls.append((c, f)),
                         run_tests=lambda: tests.append(True))
                self.assertEqual(calls, [expected])
                self.assertEqual(tests, [])

        for argv in ([], ['-v'], ['--failfast'], ['--catch'], ['RetiredReceiptCases']):
            with self.subTest(unittest_argv=argv):
                calls, tests = [], []
                dispatch(argv, run_integration=lambda c, f: calls.append((c, f)),
                         run_tests=lambda: tests.append(True))
                self.assertEqual(calls, [])
                self.assertEqual(tests, [True])


def main(argv=None, run_integration=None):
    args = argument_parser().parse_args(argv)
    runner = integration if run_integration is None else run_integration
    runner(args.cli.resolve(), args.fake.resolve())


def dispatch(argv=None, *, run_integration=None, run_tests=None):
    args = sys.argv[1:] if argv is None else list(argv)
    if is_cli_argv(args):
        main(args, run_integration=run_integration)
    else:
        (unittest.main if run_tests is None else run_tests)()


if __name__ == '__main__':
    dispatch()
