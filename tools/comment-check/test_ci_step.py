#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SELF = Path(__file__).resolve().relative_to(ROOT).as_posix()
WORKFLOW = ROOT / '.github' / 'workflows' / 'ci.yml'
STEP = '      - name: The comment check (#1817)'
CARRIED = ['tools/comment-check/check.py', 'tools/comment-check/test_check.py',
           'contracts/comments.v1.md', 'contracts/comments.v1.schema.json', 'contracts/fixtures/comments']


def step_script():
    lines = WORKFLOW.read_text().splitlines()
    if lines.count(STEP) != 1:
        return ''
    body = lines[lines.index(STEP) + 1:]
    if body[0] != '        run: |':
        raise AssertionError(f'the step runs a block script: {body[0]!r}')
    script = []
    for line in body[1:]:
        if line and not line.startswith('          '):
            break
        if SELF not in line:
            script.append(line[10:])
    return '\n'.join(script) + '\n'


def git(cwd, *args):
    return subprocess.run(['git', '-C', str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


class PullRequest:
    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.origin, self.checkout = Path(tmp.name, 'origin'), Path(tmp.name, 'checkout')
        git(tmp.name, 'init', '-q', '-b', 'main', str(self.origin))
        for key, value in (('user.name', 'Synthetic'), ('user.email', 'synthetic@example.com'),
                           ('uploadpack.allowAnySHA1InWant', 'true')):
            git(self.origin, 'config', key, value)
        for path in CARRIED:
            source, target = ROOT / path, self.origin / path
            target.parent.mkdir(parents=True, exist_ok=True)
            (shutil.copytree if source.is_dir() else shutil.copyfile)(source, target)
        self.commit('src/old.py', '# an old comment stays\nvalue = 1\n')
        git(self.origin, 'checkout', '-q', '-b', 'pr')

    def commit(self, path, text):
        target = self.origin / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        git(self.origin, 'add', '-A')
        git(self.origin, 'commit', '-q', '-m', path)

    def run_step(self, main_moves=False):
        if main_moves:
            git(self.origin, 'checkout', '-q', 'main')
            self.commit('src/main_side.py', '# a narration comment main added after the branch\n')
        git(self.origin, 'checkout', '-q', 'main')
        git(self.origin, 'checkout', '-q', '--detach')
        git(self.origin, 'merge', '-q', '--no-ff', '-m', 'Merge pr into main', 'pr')
        merge = git(self.origin, 'rev-parse', 'HEAD')
        git(self.origin, 'checkout', '-q', 'pr')
        git(self.origin.parent, 'init', '-q', str(self.checkout))
        git(self.checkout, 'remote', 'add', 'origin', self.origin.as_uri())
        git(self.checkout, 'fetch', '-q', '--no-tags', '--depth=1', 'origin', merge)
        git(self.checkout, 'checkout', '-q', '--detach', merge)
        env = dict(os.environ, GITHUB_SHA=merge)
        return subprocess.run(['bash', '--noprofile', '--norc', '-eo', 'pipefail', '-c', step_script()],
                              cwd=self.checkout, env=env, capture_output=True, text=True)


class CommentCheckStep(unittest.TestCase):
    def test_a_pull_request_adding_a_disallowed_comment_fails(self):
        pr = PullRequest(self)
        pr.commit('src/new.py', 'value = 2\n# explains why value is two\n')
        run = pr.run_step()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assertEqual([line.split(': ')[0] for line in run.stdout.splitlines()], ['src/new.py:2'])

    def test_a_reasoned_escape_tag_passes(self):
        pr = PullRequest(self)
        pr.commit('src/new.py', 'value = 2\n# comment-ok: the vendor API rejects 1, see its changelog\n')
        run = pr.run_step()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((run.stdout, run.stderr.splitlines()[-1:]), ('', ['comment-check: ok']))

    def test_comments_main_added_are_not_the_pull_requests(self):
        pr = PullRequest(self)
        pr.commit('src/new.py', 'value = 2\n')
        run = pr.run_step(main_moves=True)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((run.stdout, run.stderr.splitlines()[-1:]), ('', ['comment-check: ok']))

    def test_a_hash_quoted_inside_a_command_substitution_passes(self):
        pr = PullRequest(self)
        pr.commit('src/label.sh', '#!/bin/sh\nlabel="$(printf \'%s\' "Issue #123")"\necho "$label"\n')
        run = pr.run_step()
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual((run.stdout, run.stderr.splitlines()[-1:]), ('', ['comment-check: ok']))


if __name__ == '__main__':
    unittest.main()
