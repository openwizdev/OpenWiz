#!/usr/bin/env python3
"""Small integration with the repository's real fixture dispatch and Rust fake.

This proves the runner reaches the real bundle/adapter boundary, not live
feature acceptance. The synthetic workflow's other labels exercise sequencing.
No browser, product daemon or live endpoint is used.
"""
from contextlib import contextmanager
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CLAIMS = ['fleet', 'swarms', 'service', 'loops', 'cockpit', 'decisions',
          'terminal', 'json', 'send', 'new', 'app', 'read_safety']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def world(cli, fake):
    with tempfile.TemporaryDirectory(prefix='live-smoke-fixture-') as directory:
        root = Path(directory)
        root.chmod(0o700)
        room = root / 'room-cli'
        room.symlink_to(fake)
        # A complete, synthetic, empty inventory removes unrelated source gaps;
        # the existing normal fixtures supply project/machine/version reads.
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
        # Prove a bundle/source refusal gates the workflow using the same
        # production dispatcher and an allowlisted but failing fake response.
        scenario['responses'].insert(0, {'argv': ['thread', 'list', '--json'], 'stdout': '', 'exit_code': 1})
        scenario_file.write_text(json.dumps(scenario))
        failed = subprocess.run(argv + ['--fixture'], capture_output=True, text=True, timeout=30)
        assert failed.returncode == 3, failed.stdout
        assert json.loads(failed.stdout)['reason'] == 'bundle_preflight'
        print(json.dumps({'fixture_dispatch': 'pass', 'dry_run': 'not_run',
                          'guard_refusal': 'pass', 'live': 'not_run', 'initial_fake_reads': len(calls)}))



def bind(value, inputs):
    if isinstance(value, str) and value.startswith('@'):
        return inputs[value[1:]]
    if isinstance(value, list):
        return [bind(v, inputs) for v in value]
    if isinstance(value, dict):
        return {k: bind(v, inputs) for k, v in value.items()}
    return value


def standard_step(name, inputs):
    template = json.loads((HERE / 'combined.template.json').read_text())
    return bind(next(s for s in template['steps'] if s['id'] == name), inputs)


def receipt_case(cli, fake, case):
    with world(cli, fake) as (root, kit, scenario, scenario_file):
        replies = []
        inputs = {'openwiz': str(cli), 'send_thread': 'thr_syn_0001',
                  'send_op': 'op-smoke-message', 'project': 'prj_syn_0001',
                  'harness': 'codex', 'model': 'syn-codex-model-01',
                  'effort': 'high', 'new_op': 'op-smoke-new',
                  'new_preview_checks': [{'path': '/schema', 'equals': 'openwiz.new-thread-preview.v1'},
                                         {'path': '/verdict/kind', 'equals': 'ready'}]}
        if case == 'ready-preview':
            project_file = ROOT / 'tests/fixtures/room-cli-0.43.1/normal/project-list.json'
            projects = json.loads(project_file.read_text())
            # Same synthetic GitHub project shape as tests/new-thread/fake.rs;
            # all values invented, never a live target.
            projects[0]['gitRemoteUrl'] = 'https://github.com/synthetic-owner/synthetic-repo.git'
            replies = [
                {'argv': ['project', 'list', '--json', '--include-personal'], 'stdout': json.dumps(projects)},
                {'argv': ['cloud', 'status', '--json'], 'stdout_file': str(ROOT / 'tests/fixtures/room-cli-v127/new-thread/cloud-status.json')}]
            step = standard_step('new_preview', inputs)
        else:
            filename = 'tell-cloud-queue-observed.json' if case == 'queued-send' else 'tell-sent.json'
            replies = [{'argv': ['thread', 'tell', 'thr_syn_0001', '--mode', 'queue', '--json', '--'],
                        'any_text': True, 'stdout_file': str(ROOT / 'tests/fixtures/room-cli-0.43.1/send' / filename)}]
            step = standard_step('send_once', inputs)
        scenario['synthetic_assumptions'].append('Smoke-case project settings and operation ids are synthetic; receipts reuse the documented existing fixtures.')
        scenario['responses'] = replies + scenario['responses']
        scenario_file.write_text(json.dumps(scenario))
        kit['steps'].insert(0, step)
        path = root / 'kit.json'
        path.write_text(json.dumps(kit))
        argv = [sys.executable, '-I', str(HERE / 'smoke.py'), '--kit', str(path),
                '--state', str(root / 'checkpoint'), '--fixture']
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)['verdict'] == 'pass'
        calls = [json.loads(line) for line in (root / 'invocations.log').read_text().splitlines()]
        tells = sum(c[:2] == ['thread', 'tell'] for c in calls)
        spawns = sum(c[:2] == ['thread', 'spawn'] for c in calls)
        assert spawns == 0
        assert tells == (0 if case == 'ready-preview' else 1)
        # Resume never repeats the successful message/preview.
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        after = [json.loads(line) for line in (root / 'invocations.log').read_text().splitlines()]
        assert sum(c[:2] == ['thread', 'tell'] for c in after) == tells
        if case == 'ready-preview':
            assert not (root / 'product-state/new-threads').exists()
        print(json.dumps({'case': case, 'result': 'pass', 'tells': tells, 'spawns': spawns, 'live': 'not_run'}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--fake', required=True, type=Path)
    parser.add_argument('--case', choices=['integration', 'ready-preview', 'accepted-send', 'queued-send'], default='integration')
    args = parser.parse_args()
    cli, fake = args.cli.resolve(), args.fake.resolve()
    if args.case == 'integration':
        integration(cli, fake)
    else:
        receipt_case(cli, fake, args.case)


if __name__ == '__main__':
    main()
