#!/usr/bin/env python3
"""Run CI's selected skill suites (#433). Unknown or empty selection runs all.

python3 -I ci/select/skills.py 'triage where-are-we'   # or all / none
The order of the full run is the existing CI order. No shell interpolation.
"""
import subprocess
import sys

SUITES = {
    'triage': [['python3', '-I', 'skills/triage/test/test_find_work.py']],
    'where-are-we': [['python3', '-I', 'skills/where-are-we/test/test_read_github.py']],
    'hill-climb': [['python3', '-I', '-m', 'unittest', 'discover', '-s', 'skills/hill-climb/tests']],
    'image': [['python3', '-I', '-m', 'unittest', 'discover', '-s', 'skills/image/tests']],
    'plan-graph': [['python3', '-I', 'skills/plan-graph/scripts/test_check_approval.py'],
                   ['sh', 'skills/plan-graph/test/test-revision.sh']],
    'launch-fleet': [['sh', 'skills/launch-fleet/scripts/test.sh'],
                     ['python3', '-I', 'skills/launch-fleet/test/ops-protocol/test_protocol.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-effects.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-grants.py'],
                     ['python3', '-I', 'skills/launch-fleet/scripts/test-inbox.py'],
                     ['python3', '-I', 'tools/review-relay/test_inbox.py']],
}


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
