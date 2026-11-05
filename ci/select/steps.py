#!/usr/bin/env python3
"""K16 step requirements from the same trusted map and diff as test selection.

Old maps without export metadata, and unmapped tests, need the export until a
new trace proves otherwise. Non-plain runs and errors use FULL in job.py.
"""
import os
import subprocess

from skills import SUITES

FLAGS = ('build-web', 'lint-rust', 'export-rust', 'export-web', 'build-site', 'image-skills')


def plan(tests, changes, known, root, classify=True):
    paths = [p for _, p in changes]
    folders = {p.split('/')[1] for p in paths if p.startswith('skills/') and len(p.split('/')) > 2}
    skill_tests = sorted(folders & set(SUITES))

    def needs_export(test):
        unit = known.get(test, {})
        if unit.get('web_export', True):
            return True
        # A negative trace describes the old inputs. A changed source/fixture
        # or a new entry in a listed folder can introduce an export read.
        for status, path in changes:
            if path in unit['files']:
                return True
            if status != 'M' and any(d == '.' or path.startswith(d + '/') for d in unit['dirs']):
                return True
        return False

    def export(lane):
        return any(needs_export(t) for t in tests if t.startswith(lane + ':'))

    rust_export, web_export = export('rust'), export('web')
    # The build type-checks tests too; any app input change still checks it.
    web_build = rust_export or web_export or any(p.startswith('apps/web/') for p in paths)
    rust_lint = any(p.endswith('.rs') or p.startswith('crates/') or p in ('Cargo.toml', 'Cargo.lock', 'tests/Cargo.toml')
                    for p in paths)
    if classify:
        proc = subprocess.run(['sh', os.path.join(root, '.github/actions/docs-only/classify.sh')],
                              input='\n'.join(paths) + '\n', capture_output=True, text=True, check=True,
                              env=dict(os.environ, CLASSIFY_STEP='site'))
        if proc.stdout.strip() not in ('none', 'web-build', 'web-build web-test'):
            raise ValueError('no site decision from classify.sh')
        site_build = 'web-test' in proc.stdout.split()
    else:
        site_build = any(p.startswith(('apps/site/', 'tools/release/')) for p in paths)
    values = (web_build, rust_lint, rust_export, web_export, site_build, 'image' in skill_tests)
    return {**{k: 'true' if v else 'false' for k, v in zip(FLAGS, values)},
            'skill-tests': ' '.join(skill_tests) if skill_tests else 'none'}
