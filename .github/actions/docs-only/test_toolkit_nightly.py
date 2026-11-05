"""Exercise nightly shell failure propagation/retention with small command fixtures.

This executes the workflow's literal shell without Cargo, integration kits or
mutations. It proves orchestration only; real nightly toolkit execution is CI's.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[3]


def nightly_script():
    ci = (ROOT / '.github/workflows/ci.yml').read_text()
    name = '      - name: The live-check toolkit (nightly fixtures and mutants)\n'
    block = ci.split(name)[1].split('      - name: Keep the nightly toolkit evidence')[0]
    return textwrap.dedent(re.search(r'^        run: \|\n((?:          .*\n|\n)+)', block, re.M)[1])


class Nightly(unittest.TestCase):
    def run_fixture(self, fail):
        with tempfile.TemporaryDirectory(prefix='toolkit-nightly-proof-') as tmp:
            root = Path(tmp)
            source = root / 'live-check-source'
            source.mkdir()
            (source / 'Cargo.lock').write_text('synthetic')
            bindir = root / 'bin'
            bindir.mkdir()
            fixtures = {
                'git': '''#!/bin/sh
case "$*" in *'remote') exit 0 ;; esac
printf '%040d\\n' 1
''',
                'cargo': '#!/bin/sh\necho synthetic-build\n',
                'lsof': '#!/bin/sh\nexit 0\n',
                'sh': '''#!/bin/sh
if [ "$FAIL_AT" = suite ]; then echo synthetic-suite-failure >&2; exit 23; fi
echo synthetic-suite-passed
''',
                'python3': '''#!/bin/sh
case "$1" in
  *test_mutants.py) echo synthetic-unit-passed ;;
  *dry-run.py)
    while [ "$1" != --log ]; do shift; done
    echo synthetic-plan-result > "$2"
    echo synthetic-plan-passed ;;
  *mutants.py)
    shift
    while [ "$1" != --logs ]; do shift; done
    out="$2"
    mkdir -p "$out"
    echo synthetic-mutant-detail > "$out/synthetic.log"
    if [ "$FAIL_AT" = mutant ]; then
      echo '{"ok":false}' > "$out/synthetic.json"
      echo synthetic-mutant-failure >&2; exit 29
    fi
    echo '{"ok":true}' > "$out/synthetic.json"
    echo synthetic-required-red > "$out/summary.txt"
    echo synthetic-mutant-passed ;;
  *) exit 97 ;;
esac
''',
            }
            for name, content in fixtures.items():
                path = bindir / name
                path.write_text(content)
                path.chmod(0o700)
            env = dict(os.environ, PATH=str(bindir)+os.pathsep+os.environ['PATH'],
                       RUNNER_TEMP=str(root), FAIL_AT=fail)
            result = subprocess.run(['bash', '--noprofile', '--norc', '-e', '-o',
                                     'pipefail', '-c', nightly_script()],
                                    cwd=root, env=env, capture_output=True, text=True)
            evidence = root / 'live-check-evidence'
            expected = {'': 0, 'suite': 23, 'mutant': 29}[fail]
            self.assertEqual(result.returncode, expected, result.stdout+result.stderr)
            self.assertEqual(json.loads((evidence/'result.json').read_text()), {'exit': expected})
            self.assertFalse(source.exists())
            self.assertEqual(list(root.glob('live-check.*')), [])
            full = (evidence/'full.log').read_text()
            self.assertIn('synthetic-build', full)
            if fail:
                self.assertIn('synthetic-'+fail+'-failure', full)
            if fail == 'suite':
                self.assertFalse((evidence/'plan-send.log').exists())
                self.assertNotIn('synthetic-mutant-passed', full)
            else:
                for profile in ('send', 'new'):
                    self.assertEqual((evidence/('plan-'+profile+'.log')).read_text(),
                                     'synthetic-plan-result\n')
                self.assertEqual((evidence/'mutants/synthetic.log').read_text(),
                                 'synthetic-mutant-detail\n')
            if not fail:
                self.assertEqual((evidence/'mutants/summary.txt').read_text(),
                                 'synthetic-required-red\n')

    def test_success_keeps_complete_fixture_logs_and_removes_source(self):
        self.run_fixture('')

    def test_suite_failure_stops_and_is_retained(self):
        self.run_fixture('suite')

    def test_mutation_failure_is_retained_and_cannot_pass(self):
        self.run_fixture('mutant')


if __name__ == '__main__':
    unittest.main()
