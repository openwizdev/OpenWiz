#!/usr/bin/env python3
"""Run CI's selected skill suites (#433). Unknown or empty selection runs all.

python3 -I .github/actions/docs-only/skills.py 'triage where-are-we'   # or all / none
The order of the full run is the existing CI order. No shell interpolation.
"""
import subprocess
import sys

SUITES = {
    # The launch-fleet lane runs the inbox suite from the pinned WizSkills release.
    'launch-fleet': [['python3', '-I', 'skills/launch-fleet/scripts/test-inbox.py']],
}
# #743: suites CI runs as their own job, split across members by
# ci/shard/lanes.py; the skills job's matrix runs the rest.
SHARDED = ('launch-fleet',)


def valid(value):
    if value in ('all', 'none'):
        return True
    names = value.split(' ')
    return bool(names) and len(set(names)) == len(names) and all(n in SUITES for n in names)


def selected(value):
    if not valid(value) or value == 'all':
        return list(SUITES)
    return [] if value == 'none' else [n for n in SUITES if n in value.split(' ')]


def run(value):
    names = selected(value)
    print('skill selection: ' + (' '.join(names) if names else 'none'), flush=True)
    for name in names:
        for command in SUITES[name]:
            code = subprocess.run(command).returncode
            if code:
                return code if code > 0 else 1
    return 0


if __name__ == '__main__':
    sys.exit(run(sys.argv[1] if len(sys.argv) == 2 else 'all'))
