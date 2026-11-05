#!/usr/bin/env python3
"""WZ-P3/WZ-P4 for launch-fleet (#2634): the skills copy's dry run, reduced to one skill.

python3 -I tools/fleet-load/standalone/dry_run_report.py [--commit REV]

Runs `tools/skills-copy/copy.py`'s dry run (no destination, no network write) on
REV (default HEAD) and prints launch-fleet's standalone and privacy results:
rule, file and line only. Exits 0 only when both pass for launch-fleet.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SKILL = 'launch-fleet'


def main(argv):
    commit = 'HEAD'
    if argv[:1] == ['--commit'] and len(argv) == 2:
        commit = argv[1]
    elif argv:
        print('usage: dry_run_report.py [--commit REV]', file=sys.stderr)
        return 2
    run = subprocess.run([sys.executable, '-I', str(ROOT / 'tools/skills-copy/copy.py'), '--version', '0.1.0',
                          '--source', str(ROOT), '--commit', commit], cwd=ROOT, text=True, capture_output=True)
    try:
        report = json.loads(run.stdout)
    except ValueError:
        print('dry run produced no report (exit %d)' % run.returncode, file=sys.stderr)
        return 1
    standalone = report.get('standalone', {}).get('skills', {}).get(SKILL, [])
    privacy = [line for line in report.get('privacy', {}).get('result', '').splitlines()
               if '"skills/%s/' % SKILL in line]
    print('commit', report.get('commit'))
    print('%s standalone: %s' % (SKILL, 'pass' if not standalone else 'refused (%d findings)' % len(standalone)))
    for finding in standalone:
        print(' ', finding['rule'], finding['file'], finding['line'])
    print('%s privacy: %s' % (SKILL, 'pass' if not privacy else 'refused (%d findings)' % len(privacy)))
    for line in privacy:
        print(' ', line)
    return 1 if standalone or privacy else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
