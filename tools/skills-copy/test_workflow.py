#!/usr/bin/env python3
"""Exercise the automation admission boundary on synthetic Git events."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('copy_fixtures', HERE / 'test_copy.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class GateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.CopyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.before = self.fixture.git(self.fixture.source, 'rev-parse', 'HEAD').stdout.strip()

    def gate(self, path, repository='openwizdev/openwiz', ref='refs/heads/main', event_name='push', malformed=False):
        self.fixture.write(path, 'synthetic changed file\n')
        after = self.fixture.commit()
        event = self.fixture.root / 'event.json'
        event.write_text('{' if malformed else json.dumps({
            'before': self.before, 'after': after, 'deleted': False,
            'repository': {'full_name': repository}}))
        p = subprocess.run([sys.executable, '-I', str(HERE / 'workflow.py'), '--source', str(self.fixture.source)],
                           env=dict(self.fixture.env, GITHUB_EVENT_PATH=str(event),
                                    GITHUB_REPOSITORY=repository, GITHUB_REF=ref, GITHUB_EVENT_NAME=event_name),
                           capture_output=True, text=True)
        self.before = after
        return p

    def test_event_and_changed_paths(self):
        cases = [
            ('skills/alpha/new.txt', {}, True),
            ('wizdev/skills/board/new.txt', {}, True),
            ('.claude/skills/live-spike/new.txt', {}, True),
            ('unrelated/file.txt', {}, False),
            ('.claude/skills/unreviewed/new.txt', {}, False),
            ('skills/alpha/private-event.txt', {'repository': 'jparker2006/ClosedWiz'}, False),
            ('skills/alpha/fork-event.txt', {'repository': 'synthetic/fork'}, False),
            ('skills/alpha/branch-event.txt', {'ref': 'refs/heads/feature'}, False),
            ('skills/alpha/pr-event.txt', {'event_name': 'pull_request'}, False),
        ]
        for path, args, enabled in cases:
            with self.subTest(path=path):
                p = self.gate(path, **args)
                self.assertEqual(p.returncode, 0, p.stderr)
                self.assertEqual(json.loads(p.stdout)['enabled'], enabled)
        p = self.gate('skills/alpha/bad-event.txt', malformed=True)
        self.assertNotEqual(p.returncode, 0)

    def test_workflow_runner_and_gate_before_credentials(self):
        # Workflow files are a publication contract: inspect actual parsed runner
        # policy and operative YAML keys, not arbitrary words in a source grep.
        workflow = HERE.parents[1] / '.github/workflows/skills-copy.yml'
        self.assertTrue(workflow.is_file())
        parser_spec = importlib.util.spec_from_file_location('workflow_policy', HERE.parent / 'privacy-check/workflow.py')
        policy = importlib.util.module_from_spec(parser_spec)
        parser_spec.loader.exec_module(policy)
        self.assertFalse(policy.refused_jobs(workflow.read_text()))
        text = workflow.read_text()
        parsed = policy.parse(text)
        self.assertEqual(parsed['on']['push']['paths'], [
            'skills/**', 'wizdev/skills/**', '.claude/skills/export-review/**',
            '.claude/skills/live-quick-check/**', '.claude/skills/live-spike/**'])
        self.assertEqual(parsed['jobs']['copy']['runs-on'], 'ubuntu-24.04')
        self.assertIn("if: ${{ github.repository == 'openwizdev/openwiz' && github.ref == 'refs/heads/main' && github.event_name == 'push' }}", text)
        self.assertIn('branches: [main]', text)
        self.assertIn('permissions:\n  contents: read', text)
        self.assertIn('cancel-in-progress: false', text)
        self.assertLess(text.index('tools/skills-copy/workflow.py'), text.index('ssh-key:'))
        self.assertEqual(text.count("if: steps.gate.outputs.enabled == 'true'"), 2)
        self.assertNotIn('workflow_dispatch:', text)
        self.assertNotIn('pull_request', text.replace("github.event_name == 'push'", ''))


if __name__ == '__main__':
    unittest.main(defaultTest='GateTests')
