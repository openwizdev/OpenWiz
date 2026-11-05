#!/usr/bin/env python3
"""X5's fail-closed required-check boundary.

Usage: gate.py ci-selection.json outcomes.json
Outcomes are normalized job conclusions keyed by plan lane (skill:<folder>
for matrix members and build:web_export for the export). The workflow must
supply each actual conclusion, never infer success from a missing job.
"""
import os
from pathlib import Path
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'ci/escapes'))
import escapes  # noqa: E402


def read_plan(path):
    raw = Path(path).read_text(encoding='utf-8')
    errors = escapes.lint(escapes.schema()) or escapes.refusals(raw)
    if errors:
        raise ValueError('invalid plan: ' + '; '.join(errors))
    return escapes.strict_json(raw)


def expected(plan):
    lanes = plan['lanes']
    return {
        'changes': True,
        **{name: lanes[name]['decision'] == 'run' for name in ('always', 'rust', 'web', 'site')},
        **{'skill:' + lane['skill']: lane['decision'] == 'run' for lane in lanes['skills']},
        'build:web_export': plan['builds']['web_export']['decision'] == 'run',
    }


def check(plan, outcomes, context):
    for field, variable in (('id', 'GITHUB_RUN_ID'), ('attempt', 'GITHUB_RUN_ATTEMPT'),
                            ('event', 'GITHUB_EVENT_NAME')):
        if context.get(variable) != str(plan['run'][field]):
            raise ValueError(f'plan does not belong to this run: {variable}')
    if not isinstance(outcomes, dict):
        raise ValueError('lane outcomes must be an object')
    wanted = expected(plan)
    errors = [f'unknown lane: {name}' for name in outcomes.keys() - wanted.keys()]
    for name, runs in wanted.items():
        status = outcomes.get(name)
        if runs:
            if status != 'success':
                errors.append(f'{name}: expected success, got {status!r}')
        elif name in outcomes and status != 'skipped':
            errors.append(f'{name}: plan skipped this lane, got {status!r}')
    if errors:
        raise ValueError('; '.join(errors))


def main(argv):
    try:
        if len(argv) != 2:
            raise ValueError('usage: gate.py ci-selection.json outcomes.json')
        plan = read_plan(argv[0])
        outcomes = escapes.strict_json(Path(argv[1]).read_text(encoding='utf-8'))
        check(plan, outcomes, os.environ)
    except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
        print(f'ci: {error}', file=sys.stderr)
        return 1
    print('ci: every planned lane passed')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
