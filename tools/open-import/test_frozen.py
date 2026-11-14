#!/usr/bin/env python3
"""Frozen old code check proofs: real Git, synthetic repositories, no network."""
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FROZEN = HERE / 'frozen.py'
LIST = 'tools/open-import/paths.json'
SINCE = '2026-01-02'  # a synthetic switch date

# Synthetic carriage list: a folder pattern, docs/*, exact paths (as the real list
# carries docs/grills/README.md) and keep entries.
RULES = {'source': ['src/**', 'docs/*', 'docs/grills/README.md', 'tools/open-import/**', 'NOTICE'],
         'keep': ['README.md', 'LICENSE']}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class Repo:
    def __init__(self, root):
        self.root = root
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic')
        self.git('config', 'user.email', 'synthetic@example.invalid')

    def git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True, env=env).stdout.strip()

    def write(self, name, text='synthetic\n'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message='change'):
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')


class Frozen(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='frozen-check-')
        self.addCleanup(folder.cleanup)
        self.repo = Repo(Path(folder.name))
        self.repo.write(LIST, json.dumps(RULES, indent=2) + '\n')
        for name in ('src/main.rs', 'src/old.rs', 'docs/guide.md', 'NOTICE', 'README.md',
                     'tools/ci-overflow/switch.py', 'private/orchestration/state.md',
                     'legacy/unlisted.txt'):
            self.repo.write(name)
        self.base = self.repo.commit('synthetic main')
        self.repo.git('checkout', '-q', '-b', 'change')

    def run_check(self, since=SINCE, base=None, head='HEAD', repo=None, title=None, queue=None):
        env = {k: v for k, v in os.environ.items() if k not in ('FROZEN_SINCE', 'PR_TITLE', 'QUEUE_REF')}
        for key, value in (('FROZEN_SINCE', since), ('PR_TITLE', title), ('QUEUE_REF', queue)):
            if value is not None:
                env[key] = value
        return subprocess.run([sys.executable, '-I', str(FROZEN), '--repo', str(repo or self.repo.root),
                               '--base=' + (base or self.base), '--head=' + head],
                              capture_output=True, text=True, env=env)

    def named(self, result, code):
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        start = lines.index('Touched frozen paths:') + 1
        end = lines.index('', start)
        return lines[start:end]

    def refused(self, result):
        paths = self.named(result, 1)
        self.assertIn('Product work goes to openwizdev/openwiz', result.stdout)
        return paths

    # AC1: after activation, a carried path fails, named exactly.
    def test_touching_a_carried_path_fails_naming_exactly_it(self):
        self.repo.write('src/main.rs', 'modified\n')
        self.repo.write('private/evidence/run.log')
        self.repo.commit()
        self.assertEqual(self.refused(self.run_check()), ['src/main.rs'])

    def test_several_touched_paths_are_all_named_and_nothing_else(self):
        self.repo.write('src/new.rs')  # added, carried
        self.repo.write('docs/guide.md', 'modified\n')  # modified, carried
        self.repo.git('rm', '-q', 'src/old.rs')  # deleted, carried
        self.repo.write('tools/ci-overflow/switch.py', 'modified\n')  # retiring
        self.repo.write('ci/runner/start.sh')  # retiring, added
        for name in ('private/orchestration/state.md', 'docs/grills/0001-synthetic.md',
                     'legacy/unlisted.txt', 'README.md', 'LICENSE'):
            self.repo.write(name, 'changed\n')
        self.repo.commit()
        self.assertEqual(self.refused(self.run_check()),
                         ['ci/runner/start.sh', 'docs/guide.md', 'src/new.rs', 'src/old.rs',
                          'tools/ci-overflow/switch.py'])

    def test_a_rename_out_of_the_frozen_tree_names_its_old_path(self):
        self.repo.git('mv', 'src/old.rs', 'private/old.rs')
        self.repo.commit()
        self.assertEqual(self.refused(self.run_check()), ['src/old.rs'])

    # AC2: private records, grills, orchestration and evidence pass.
    def test_private_grill_orchestration_and_evidence_paths_pass(self):
        self.repo.write('private/orchestration/state.md', 'changed\n')
        self.repo.write('private/evidence/open-development/cut-over/step.md')
        self.repo.write('docs/grills/0002-synthetic.md')
        self.repo.commit()
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('frozen check: on since 2026-01-02; no frozen path touched (3 touched)', result.stdout)

    def test_paths_only_main_changed_are_not_judged(self):
        self.repo.git('checkout', '-q', 'main')
        self.repo.write('src/main.rs', 'main moved\n')
        main = self.repo.commit('main moves')
        self.repo.git('checkout', '-q', 'change')
        self.repo.write('private/notes.md')
        self.repo.commit()
        # The branch still has main's old src/main.rs; it did not touch it.
        result = self.run_check(base=main)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    # AC2: #1287's deletion pull request passes as the named exception.
    QUEUE = 'refs/heads/gh-readonly-queue/main/pr-1287-' + 'a' * 40

    def delete_old_tree(self):
        self.repo.git('rm', '-q', '-r', 'src', 'docs/guide.md', 'tools/ci-overflow')
        self.repo.write('private/orchestration/state.md', 'trimmed\n')

    def test_the_deletion_pr_of_1287_passes_by_title_or_queue_ref(self):
        self.delete_old_tree()
        self.repo.commit()
        for title, queue in (('#1287: ClosedWiz becomes the small private repository', None),
                             (None, self.QUEUE), ('', self.QUEUE)):
            with self.subTest(title=title, queue=queue):
                result = self.run_check(title=title, queue=queue)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("frozen check: on since 2026-01-02; #1287's deletion of the old tree, "
                              'the one named exception: 4 frozen paths deleted', result.stdout)

    def test_the_same_deletion_from_any_other_pr_fails(self):
        self.delete_old_tree()
        self.repo.commit()
        for title, queue in ((None, None), ('#1288: something else', None), ('#12870: near miss', None),
                             (' #1287: leading space', None), ('Delete #1287: not first', None),
                             (None, 'refs/heads/gh-readonly-queue/main/pr-12870-' + 'a' * 40),
                             (None, 'refs/heads/gh-readonly-queue/main/pr-1287-' + 'a' * 39),
                             (None, 'refs/heads/pr-1287-' + 'a' * 40)):
            with self.subTest(title=title, queue=queue):
                self.assertEqual(self.refused(self.run_check(title=title, queue=queue)),
                                 ['docs/guide.md', 'src/main.rs', 'src/old.rs', 'tools/ci-overflow/switch.py'])

    def test_an_added_or_modified_frozen_path_fails_even_in_1287s_pr(self):
        self.delete_old_tree()
        self.repo.write('NOTICE', 'modified\n')
        self.repo.write('src/kept.rs')
        self.repo.commit()
        for title, queue in (('#1287: trim', None), (None, self.QUEUE)):
            with self.subTest(title=title, queue=queue):
                result = self.run_check(title=title, queue=queue)
                self.assertEqual(self.refused(result), ['NOTICE', 'src/kept.rs'])
                self.assertIn("#1287's exception covers deleted frozen paths only", result.stdout)

    # AC3: before activation it reports and passes.
    def test_before_activation_it_reports_and_passes(self):
        self.repo.write('src/main.rs', 'modified\n')
        self.repo.write('tools/ci-overflow/switch.py', 'modified\n')
        self.repo.commit()
        for since in (None, ''):
            with self.subTest(since=since):
                result = self.run_check(since=since)
                self.assertEqual(self.named(result, 0), ['src/main.rs', 'tools/ci-overflow/switch.py'])
                self.assertIn('frozen check: off (no switch recorded); would refuse 2 paths', result.stdout)

    def test_an_invalid_activation_value_fails_closed(self):
        self.repo.write('private/notes.md')
        self.repo.commit()
        for since in ('yes', '2026-13-01', '2026-1-2', ' 2026-01-02', '2026-01-02\n', 'null',
                      '\uff12\uff10\uff12\uff16-01-02', '\u0662\u0660\u0662\u0666-01-02'):
            with self.subTest(since=since):
                result = self.run_check(since=since)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('frozen check error', result.stderr)

    def test_unreadable_base_head_or_list_fails_closed(self):
        self.repo.write('src/main.rs', 'modified\n')
        head = self.repo.commit()
        for since in (SINCE, None):
            for base, h in (('0' * 40, head), (self.base, '0' * 40), ('no-such-ref', head),
                            ('--output=/dev/null', head)):
                with self.subTest(since=since, base=base, head=h):
                    result = self.run_check(since=since, base=base, head=h)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('frozen check error', result.stderr)
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(self.run_check(repo=Path(empty)).returncode, 2)

    def test_the_list_is_read_at_the_base_so_a_change_cannot_unfreeze_itself(self):
        self.repo.write(LIST, json.dumps({**RULES, 'source': ['docs/*']}) + '\n')
        self.repo.write('src/main.rs', 'modified\n')
        self.repo.commit()
        self.assertEqual(self.refused(self.run_check()), ['src/main.rs', LIST])
        self.repo.git('checkout', '-q', 'main')
        self.repo.write(LIST, '{not json')
        bad = self.repo.commit('unreadable list on main')
        self.assertEqual(self.run_check(base=bad).returncode, 2)


class Workflow(unittest.TestCase):
    """R1: frozen.yml's own steps, run on a synthetic layout of its checkouts.

    A '#1287:'-titled PR edits (not deletes) a frozen path and replaces the
    checker with one that always passes. The workflow must still refuse it."""
    WORKFLOW = HERE.parents[1] / '.github/workflows/frozen.yml'
    TOOLS = ('import.py', 'guard.py', 'frozen.py')
    TAMPER = "def main():\n    return 0\n\n\ndef _replaced():\n"

    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='frozen-workflow-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        (self.root / 'origin').mkdir()
        self.repo = Repo(self.root / 'origin')
        self.repo.write(LIST, json.dumps({'source': ['crates/**', 'tools/open-import/**'], 'keep': []}) + '\n')
        for name in self.TOOLS:
            self.repo.write('tools/open-import/' + name, (HERE / name).read_text())
        self.repo.write('crates/core/src/lib.rs')
        self.base = self.repo.commit('synthetic main')
        self.repo.git('checkout', '-q', '-b', 'change')
        self.repo.write('crates/core/src/lib.rs', 'modified\n')
        checker = self.repo.root / 'tools/open-import/frozen.py'
        checker.write_text(checker.read_text().replace('def main():\n', self.TAMPER, 1))
        self.head = self.repo.commit('#1287: synthetic trim')

    def steps(self):
        jobs = self.WORKFLOW.read_text().split('\njobs:\n', 1)[1]
        return [step for step in re.split(r'^      - ', jobs, flags=re.M)[1:]]

    def checkout(self, step, workspace):
        # Resolve the declared PR-event expression, including a literal main.
        # An omitted ref defaults to the change as it would land.
        ref = re.search(r'^          ref: \$\{\{ (.+) \}\}$', step, re.M)
        values = {'github.event.pull_request.base.sha': self.base,
                  'github.event.pull_request.head.sha': self.head,
                  'github.event.merge_group.base_sha': None,
                  'github.event.merge_group.head_sha': None, "'main'": 'main'}
        commit = next((values[v] for v in ref[1].split(' || ') if values[v]), None) if ref else self.head
        path = re.search(r'^          path: (.+)$', step, re.M)
        target = workspace / path[1] if path else workspace
        subprocess.run(['git', 'clone', '-q', '--no-checkout', str(self.repo.root), str(target)], check=True)
        subprocess.run(['git', '-C', str(target), 'checkout', '-q', commit], check=True)

    def test_a_1287_pr_cannot_pass_an_edit_by_replacing_the_checker(self):
        # The planted checker itself passes the edit: the bug when it is run.
        planted = subprocess.run([sys.executable, '-I', str(self.repo.root / 'tools/open-import/frozen.py'),
                                  '--repo', str(self.repo.root), '--base=' + self.base, '--head=HEAD'],
                                 capture_output=True, text=True, env={**os.environ, 'FROZEN_SINCE': SINCE})
        self.assertEqual(planted.returncode, 0, planted.stdout + planted.stderr)
        result = self.run_workflow()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        listed = result.stdout.split('Touched frozen paths:\n', 1)[1].split('\n\n', 1)[0].splitlines()
        self.assertEqual(listed, ['crates/core/src/lib.rs', 'tools/open-import/frozen.py'])
        self.assertIn("#1287's exception covers deleted frozen paths only", result.stdout)

    def test_an_older_pr_uses_current_main_tools_but_only_its_own_diff(self):
        self.repo.git('checkout', '-q', 'main')
        for name in self.TOOLS:
            self.repo.git('rm', 'tools/open-import/' + name)
        self.base = self.repo.commit('synthetic base before trusted tools existed')
        for name in self.TOOLS:
            self.repo.write('tools/open-import/' + name, (HERE / name).read_text())
        self.repo.write('crates/core/src/main_only.rs')
        self.repo.commit('synthetic main adds tools and unrelated frozen code')
        self.repo.git('checkout', '-q', '-b', 'older-pr', self.base)
        self.repo.write('private/notes.md')
        self.head = self.repo.commit('synthetic private-only PR')
        result = self.run_workflow()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('no frozen path touched (1 touched)', result.stdout)

    def run_workflow(self):
        workspace = self.root / 'workspace'
        workspace.mkdir()
        env = {**{k: v for k, v in os.environ.items() if not k.startswith('GIT_')},
               'BASE_SHA': self.base, 'HEAD_SHA': self.head, 'FROZEN_SINCE': SINCE,
               'PR_TITLE': '#1287: synthetic trim', 'QUEUE_REF': ''}
        steps = self.steps()
        checkouts = [s for s in steps if s.startswith('uses: actions/checkout@')]
        # The workspace root first: the other checkouts are nested in it.
        for step in sorted(checkouts, key=lambda s: 'path:' in s):
            self.checkout(step, workspace)
        result = None
        for step in steps:
            script = re.search(r'^        run: (?:\|\n((?:          .*\n?)+)|(.+)$)', step, re.M)
            if not script:
                continue
            lines = (script[1] or script[2]).splitlines()
            # Its own proofs are this file; run everything else as written.
            body = '\n'.join(l.strip() for l in lines if 'test_frozen.py' not in l)
            result = subprocess.run(['bash', '-e', '-c', body], cwd=workspace, env=env,
                                    capture_output=True, text=True)
            self.assertIn(result.returncode, (0, 1), result.stdout + result.stderr)
        return result


class SameAsImporter(unittest.TestCase):
    # Synthetic fixture paths with independently known answers: frozen when the
    # importer carries them or they retire; private records and others pass.
    CASES = (
        ('src/main.rs', True), ('docs/guide.md', True), ('NOTICE', True),
        ('tools/open-import/import.py', True), ('docs/grills/README.md', True),
        ('tools/ci-overflow/a.py', True), ('tools/pc-capacity/b.sh', True),
        ('ci/runner/start.sh', True),
        ('README.md', False), ('LICENSE', False), ('private', False), ('private/x/y.md', False),
        ('private/orchestration/HANDOFF.md', False), ('private/evidence/run.log', False),
        ('docs/grills/0001-synthetic.md', False), ('ci/runner/cache.sh', False),
        ('docs/deep/page.md', False), ('srcx/main.rs', False), ('NOTICE.txt', False),
    )

    def setUp(self):
        self.frozen = module('open_import_frozen', FROZEN)

    def test_frozen_equals_carried_or_retiring(self):
        for name, expected in self.CASES:
            with self.subTest(name=name):
                self.assertIs(self.frozen.frozen(name, RULES), expected)

    def test_it_follows_the_importers_rules_rather_than_a_copy(self):
        importer = self.frozen.importer
        with patch.object(importer, 'carries', lambda name, rules: name == 'srcx/main.rs'):
            self.assertIs(self.frozen.frozen('srcx/main.rs', RULES), True)
            self.assertIs(self.frozen.frozen('src/main.rs', RULES), False)
        with patch.object(importer, 'private_or_retired', lambda name: name == 'legacy/x.sh'):
            self.assertIs(self.frozen.frozen('legacy/x.sh', RULES), True)
            self.assertIs(self.frozen.frozen('tools/ci-overflow/a.py', RULES), False)


if __name__ == '__main__':
    unittest.main()
