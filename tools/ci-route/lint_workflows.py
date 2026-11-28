
import argparse
import json
from pathlib import Path
import re
import runpy


PARSER = Path(__file__).resolve().parents[1] / 'privacy-check' / 'workflow.py'
parse_workflow = runpy.run_path(str(PARSER))['parse']

ROUTED = {
    "${{ vars.OPENWIZ_RUNS_ON || 'ubuntu-24.04' }}",
    "${{ vars.OPENWIZ_PRIVATE_RUNS_ON || 'jog-4vcpu' }}",
}
HOSTED = re.compile(
    r'(?:macos-(?:latest|[0-9]+)(?:-(?:intel|large|xlarge))?'
    r'|windows-(?:latest|[0-9]+)(?:-(?:arm|vs[0-9]+))?)'
)
MATRIX_RUNNER = re.compile(r'\$\{\{\s*matrix\.([A-Za-z_][A-Za-z0-9_-]*)\s*\}\}')


def allowed_runner(value):
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
        return isinstance(value, str) and HOSTED.fullmatch(value) is not None
    return isinstance(value, str) and (value in ROUTED or HOSTED.fullmatch(value) is not None)


def matrix_runners(job, key):
    strategy = job.get('strategy')
    matrix = strategy.get('matrix') if isinstance(strategy, dict) else None
    if not isinstance(matrix, dict):
        return []

    axes = {name: values for name, values in matrix.items() if name not in {'include', 'exclude'}}
    if any(not isinstance(values, list) or not values for values in axes.values()):
        return []
    if axes and key not in axes:
        return []

    runners = list(axes.get(key, []))
    include = matrix.get('include', [])
    exclude = matrix.get('exclude', [])
    if not isinstance(include, list) or not isinstance(exclude, list):
        return []
    if any(not isinstance(row, dict) for row in exclude):
        return []
    for row in include:
        if not isinstance(row, dict):
            return []
        if key in row:
            runners.append(row[key])
        elif not axes or exclude or any(
            name in row and row[name] not in values for name, values in axes.items()
        ):
            return []
    return runners


def compliant(value, job):
    match = MATRIX_RUNNER.fullmatch(value) if isinstance(value, str) else None
    if match:
        runners = matrix_runners(job, match[1])
        return bool(runners) and all(allowed_runner(runner) for runner in runners)
    return allowed_runner(value)


def single_line(value):
    return value if isinstance(value, str) and value.isprintable() else json.dumps(value)


def problems(path):
    try:
        workflow = parse_workflow(path.read_text(encoding='utf-8'))
        jobs = workflow.get('jobs')
        if not isinstance(jobs, dict) or not jobs:
            raise ValueError('expected a jobs mapping')
    except (OSError, ValueError, RecursionError):
        yield f'{single_line(path.name)}: unreadable workflow'
        return

    for name, job in jobs.items():
        value = job.get('runs-on') if isinstance(job, dict) else None
        if isinstance(job, dict):
            if 'runs-on' not in job and isinstance(job.get('uses'), str):
                continue
            if compliant(value, job):
                continue
        yield f'{single_line(path.name)}: {single_line(name)}: runs-on: {single_line(value)}'


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check workflow runners against openwiz.ci-routing.v1.")
    parser.add_argument('workflows', type=Path, help='path to a .github/workflows directory')
    args = parser.parse_args(argv)
    try:
        files = sorted(
            path for path in args.workflows.iterdir()
            if path.suffix in {'.yml', '.yaml'} and not path.is_dir()
        )
    except OSError as exc:
        print(f'{args.workflows}: {exc.strerror}')
        return 1

    failed = False
    for path in files:
        for problem in problems(path):
            print(problem)
            failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
