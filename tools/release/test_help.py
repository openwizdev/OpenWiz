import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]

HELP = [
    ('tools/ci-overload/alarm.py', ['--help'], 'stdout', 0, 'One bounded CS5 observation/admission decision.'),
    ('tools/github-app/mint-token.py', ['--help'], 'stdout', 0, 'Mint one read-only installation token'),
    ('tools/github-app/refresh-token.py', ['--help'], 'stdout', 0, 'Print an installation token for'),
    ('tools/github-app/setup.py', ['--help'], 'stdout', 0, "Connect OpenWiz's GitHub App on"),
    ('tools/install/access/access.py', ['--help'], 'stdout', 0, 'Verify an owner-configured phone route;'),
    ('tools/install/cloudroom/cloudroom.py', ['--help'], 'stdout', 0, "OpenWiz setup's CloudRoom step: install,"),
    ('tools/install/install', ['--help'], 'stdout', 0, "OpenWiz's install entry (#1109): the"),
    ('tools/install/install.py', ['--help'], 'stdout', 0, 'Verified, offline package installation. Python'),
    ('tools/install/pull.py', ['--help'], 'stdout', 0, 'Fixed published-release transport. No source'),
    ('tools/install/setup/github_login.py', ['--help'], 'stdout', 0, 'OpenWiz setup: GitHub browser sign-in'),
    ('tools/install/setup/setup.py', ['--help'], 'stdout', 0, 'OpenWiz setup: prepare one project'),
    ('tools/live-smoke/cleanup.py', ['--help'], 'stdout', 0, 'One approved T3 cleanup write,'),
    ('tools/live-smoke/inputs.py', ['--help'], 'stdout', 0, "Assemble the kit's owner-only inputs"),
    ('tools/live-smoke/prepare.py', ['--help'], 'stdout', 0, 'Bind the combined run sheet'),
    ('tools/live-smoke/receipt.py', ['--help'], 'stdout', 0, 'Candidate-bound smoke and risk receipts'),
    ('tools/live-smoke/smoke.py', ['--help'], 'stdout', 0, 'Bounded, resumable combined live-smoke run'),
    ('tools/live-smoke/test_fixture.py', ['--help'], 'stdout', 0, "Small integration with the repository's"),
    ('tools/open-import/import.py', ['--help'], 'stdout', 0, 'Prepare an ordinary public commit'),
    ('tools/owned-paths/check.py', ['--unknown'], 'stderr', 2, 'check.py --pr N [--repo OWNER/NAME]'),
    ('tools/privacy-check/check.py', ['--help'], 'stdout', 0, 'Read-only privacy check for openwiz.open-development.v1.'),
    ('tools/privacy-check/hook.py', ['--help'], 'stdout', 0, 'Pre-push adapter: guard network destinations'),
    ('tools/release/candidate.py', ['--help'], 'stdout', 0, 'Prepare, evaluate and publish one'),
    ('tools/release/release', ['--help'], 'stdout', 0, 'Check and stage a public'),
    ('tools/release/package.py', ['--help'], 'stdout', 0, 'Assemble artifacts only from an'),
    ('tools/release/publish.py', ['--help'], 'stdout', 0, 'Publish an exact checked export,'),
    ('tools/release/review_guard_mutants.py', ['--help'], 'stdout', 0, 'Remove one release guard per'),
    ('tools/release/review_mutants.py', ['--help'], 'stdout', 0, 'Prove the R3/R4/R7 corrections detect'),
    ('tools/roadmap/roadmap.py', ['--help'], 'stdout', 0, "Reads GitHub's milestones over REST"),
    ('tools/skills-eval/eval.py', ['--help'], 'stdout', 0, 'Skills eval command line (contract.md).'),
    ('tools/skills-eval/parallel.py', ['--help'], 'stdout', 0, 'Resume a frozen results set'),
    ('tools/wizskills/check_contracts.py', ['--help'], 'stdout', 0, 'Check each carried contract in'),
    ('tools/wizskills/install.py', ['--help'], 'stdout', 0, 'Install the WizSkills release pinned'),
]


class Help(unittest.TestCase):
    def test_each_tool_prints_its_description(self):
        env = dict(os.environ, COLUMNS='200')
        for path, args, stream, code, words in HELP:
            with self.subTest(path=path):
                run = subprocess.run([sys.executable, str(ROOT / path), *args], cwd=ROOT, env=env,
                                     capture_output=True, text=True, timeout=60)
                self.assertEqual(run.returncode, code, run.stderr[-2000:])
                self.assertIn(words, ' '.join(getattr(run, stream).split()))


if __name__ == '__main__':
    unittest.main()
