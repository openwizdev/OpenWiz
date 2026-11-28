import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


HERE = Path(__file__).resolve().parent
LINT = HERE / 'lint_workflows.py'
FIXTURES = HERE / 'lint-fixtures'


class WorkflowLintTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def use_fixture(self, name):
        shutil.copyfile(FIXTURES / name, self.directory / name)

    def lint(self):
        return subprocess.run(
            [sys.executable, '-I', str(LINT), str(self.directory)],
            capture_output=True, text=True,
        )

    def test_reports_each_offending_job(self):
        self.use_fixture('failing.yml')
        self.use_fixture('passing.yaml')
        result = self.lint()
        self.assertEqual(
            result.returncode, 1,
            f'Hard-coded Linux runner passed the lint (stderr: {result.stderr!r})',
        )
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.stdout.splitlines(), [
            'failing.yml: hardcoded: runs-on: ubuntu-24.04',
            'failing.yml: self-hosted: runs-on: ["self-hosted", "linux"]',
            'failing.yml: jog: runs-on: jog-4vcpu',
            "failing.yml: wrong-fallback: runs-on: ${{ vars.OPENWIZ_RUNS_ON || 'ubuntu-latest' }}",
            'failing.yml: unknown: runs-on: ${{ inputs.runner }}',
            'failing.yml: dynamic-matrix: runs-on: ${{ matrix.runner }}',
            'failing.yml: mixed-matrix: runs-on: ${{ matrix.runner }}',
            'failing.yml: incomplete-matrix: runs-on: ${{ matrix.runner }}',
            'failing.yml: unresolved-include: runs-on: ${{ matrix.runner }}',
        ])

    def test_passes_compliant_workflows(self):
        self.use_fixture('passing.yaml')
        result = self.lint()
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def test_reports_unreadable_workflow(self):
        (self.directory / 'unreadable.yml').write_text('jobs: {broken\n', encoding='utf-8')
        result = self.lint()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertIn('unreadable.yml:', result.stdout)
        self.assertEqual(result.stderr, '')

    def test_opens_workflows_only_for_reading(self):
        self.use_fixture('passing.yaml')
        directory = self.directory
        opened = []

        def audit(event, args):
            if event != 'open' or not isinstance(args[0], (str, bytes)):
                return
            filename, mode, flags = args
            path = Path(os.fsdecode(filename))
            if path.parent == directory and path.suffix in {'.yml', '.yaml'}:
                opened.append(str(path))
                self.assertIn(mode, ('r', 'rb'))
                self.assertEqual(flags & (os.O_ACCMODE | os.O_CREAT | os.O_TRUNC | os.O_APPEND), os.O_RDONLY)

        # An audit hook lasts until process exit. Run this assertion in a child.
        if os.environ.get('LINT_WORKFLOW_READ_TEST'):
            sys.addaudithook(audit)
            sys.path.insert(0, str(HERE))
            from lint_workflows import main

            self.assertEqual(main([str(directory)]), 0)
            self.assertEqual(opened, [str(directory / 'passing.yaml')])
        else:
            result = subprocess.run(
                [sys.executable, '-I', __file__, 'WorkflowLintTests.test_opens_workflows_only_for_reading'],
                env={**os.environ, 'LINT_WORKFLOW_READ_TEST': '1'},
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
