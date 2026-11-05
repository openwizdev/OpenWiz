#!/usr/bin/env python3
"""Per-PR carriage guard proofs: real Git, synthetic repositories, no network."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
GUARD = HERE / 'guard.py'
LIST = 'tools/open-import/paths.json'

# Synthetic carriage list: a folder pattern, an exact path and one keep entry.
RULES = {'source': ['src/**', 'docs/*', 'tools/open-import/**', 'NOTICE'],
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

    def rules(self, rules):
        self.write(LIST, json.dumps(rules, indent=2) + '\n')

    def commit(self, message='change'):
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', message)
        return self.git('rev-parse', 'HEAD')


class Guard(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='carriage-guard-')
        self.addCleanup(folder.cleanup)
        self.repo = Repo(Path(folder.name))
        self.repo.rules(RULES)
        for name in ('src/main.rs', 'docs/guide.md', 'README.md', 'NOTICE',
                     'legacy/unlisted.txt', 'src/old.rs'):
            self.repo.write(name)
        self.base = self.repo.commit('synthetic main')
        self.repo.git('checkout', '-q', '-b', 'change')

    def run_guard(self, base=None, head='HEAD', repo=None):
        return subprocess.run([sys.executable, '-I', str(GUARD), '--repo', str(repo or self.repo.root),
                               '--base=' + (base or self.base), '--head=' + head],
                              capture_output=True, text=True)

    def refused(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        lines = result.stdout.splitlines()
        start = lines.index('Unclassified added paths:') + 1
        end = lines.index('', start)
        # Both ways to classify, each named in the refusal.
        self.assertIn("a matching `source` entry in tools/open-import/paths.json", result.stdout)
        self.assertIn('as <folder>/**', result.stdout)
        self.assertIn('an existing private class (for example private/)', result.stdout)
        self.assertIn('private/retiring classes in tools/open-import/import.py', result.stdout)
        return lines[start:end]

    def test_unclassified_path_fails_naming_exactly_it(self):
        self.repo.write('newtool/run.py')
        self.repo.write('src/lib.rs')
        self.repo.commit()
        self.assertEqual(self.refused(self.run_guard()), ['newtool/run.py'])

    def test_several_unclassified_paths_are_all_named_and_nothing_else(self):
        for name in ('newtool/run.py', 'zeta.txt', 'docs/deep/page.md', 'src/lib.rs',
                     'private/notes.md', 'README.md.bak'):
            self.repo.write(name)
        self.repo.commit()
        self.assertEqual(self.refused(self.run_guard()),
                         ['README.md.bak', 'docs/deep/page.md', 'newtool/run.py', 'zeta.txt'])

    def test_passes_once_the_same_change_lists_the_path(self):
        self.repo.write('newtool/run.py')
        self.repo.write('newtool/test_run.py')
        self.repo.commit()
        self.assertEqual(self.refused(self.run_guard()), ['newtool/run.py', 'newtool/test_run.py'])
        self.repo.rules({**RULES, 'source': RULES['source'] + ['newtool/**']})
        self.repo.commit('classify newtool')
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('all 2 added paths are classified', result.stdout)

    def test_exact_source_entry_classifies_one_path(self):
        self.repo.write('CHANGES.txt')
        self.repo.rules({**RULES, 'source': RULES['source'] + ['CHANGES.txt']})
        self.repo.commit()
        self.assertEqual(self.run_guard().returncode, 0)

    def test_private_and_retiring_classes_pass(self):
        for name in ('private/evidence/run.log', 'docs/grills/0001-synthetic.md',
                     'tools/pc-capacity/probe.sh', 'tools/ci-overflow/switch.py',
                     'ci/runner/start.sh'):
            self.repo.write(name)
        self.repo.commit()
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_keep_deleted_modified_and_existing_paths_pass(self):
        self.repo.git('rm', '-q', 'README.md', 'src/old.rs')  # deleted
        self.repo.write('LICENSE')  # added, matches keep
        self.repo.write('legacy/unlisted.txt', 'modified\n')  # unlisted, already on main
        self.repo.write('src/main.rs', 'modified\n')
        self.repo.commit()
        result = self.run_guard()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('all 1 added paths are classified', result.stdout)

    def test_rename_counts_at_its_new_name(self):
        (self.repo.root / 'outside').mkdir()
        self.repo.git('mv', 'src/old.rs', 'outside/old.rs')
        self.repo.git('mv', 'legacy/unlisted.txt', 'src/listed.txt')
        self.repo.commit('rename')
        self.assertEqual(self.refused(self.run_guard()), ['outside/old.rs'])

    def test_paths_already_on_main_are_not_rejudged(self):
        # Main moves on: it adds one unlisted path and deletes another after
        # the branch point. The change merges main and adds nothing itself.
        self.repo.git('checkout', '-q', 'main')
        self.repo.write('legacy/second.txt')
        self.repo.commit('main adds')
        self.repo.git('checkout', '-q', 'change')
        self.repo.write('src/feature.rs')
        self.repo.commit()
        self.repo.git('checkout', '-q', 'main')
        self.repo.git('rm', '-q', 'legacy/unlisted.txt')
        main = self.repo.commit('main deletes')
        self.repo.git('checkout', '-q', 'change')
        self.repo.git('merge', '-q', '--no-edit', 'main~1')
        # Head still holds legacy/unlisted.txt, deleted on main since the
        # branch point; it was on main, so it is not judged as added.
        result = self.run_guard(base=main)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('all 1 added paths are classified', result.stdout)

    def test_unreadable_base_head_or_list_fails_closed(self):
        self.repo.write('src/lib.rs')
        head = self.repo.commit()
        for base, h in (('0' * 40, head), (self.base, '0' * 40), ('no-such-ref', head),
                        ('--output=/dev/null', head)):
            result = self.run_guard(base=base, head=h)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('carriage guard error', result.stderr)
        for bad in ('{not json', '[]', '{"source": ["src/**"]}', '{"source": "src/**", "keep": []}',
                    '{"source": ["src/**", 7], "keep": []}', '{"source": [], "keep": [], "extra": []}'):
            self.repo.write(LIST, bad)
            self.repo.commit('bad list')
            result = self.run_guard()
            self.assertEqual(result.returncode, 2, bad + result.stdout + result.stderr)
            self.assertIn('carriage guard error', result.stderr)
        self.repo.git('rm', '-q', LIST)
        self.repo.commit('no list')
        self.assertEqual(self.run_guard().returncode, 2)
        with tempfile.TemporaryDirectory() as empty:
            self.assertEqual(self.run_guard(repo=Path(empty)).returncode, 2)


class SameAsImporter(unittest.TestCase):
    # Synthetic fixture paths with independently known classes.
    CASES = (
        ('src/main.rs', 'public'), ('docs/guide.md', 'public'), ('NOTICE', 'public'),
        ('README.md', 'keep'), ('LICENSE', 'keep'), ('private', 'private'), ('private/x/y.md', 'private'),
        ('docs/grills/0001-synthetic.md', 'private'), ('docs/grills/README.md', None),
        ('tools/ci-overflow/a.py', 'private'), ('tools/pc-capacity/b.sh', 'private'),
        ('ci/runner/start.sh', 'private'), ('ci/runner/cache.sh', None),
        ('docs/deep/page.md', None), ('srcx/main.rs', None), ('NOTICE.txt', None),
    )

    def setUp(self):
        self.importer = module('open_import_importer', HERE / 'import.py')
        self.guard = module('open_import_guard', GUARD)

    def test_classification_equals_the_importers(self):
        for name, expected in self.CASES:
            with self.subTest(name=name):
                self.assertEqual(self.guard.classify(name, RULES), expected)
                importer = ('public' if self.importer.carries(name, RULES) else
                            'private' if self.importer.private_or_retired(name) else
                            'keep' if name in RULES['keep'] else None)
                self.assertEqual(importer, expected)

    def test_guard_follows_the_importers_rules_rather_than_a_copy(self):
        importer = self.guard.importer
        with patch.object(importer, 'private_or_retired', lambda name: name == 'src/main.rs'):
            self.assertEqual(self.guard.classify('src/main.rs', RULES), 'private')
            self.assertIsNone(self.guard.classify('private/x/y.md', RULES))
        with patch.object(importer, 'carries', lambda name, rules: name == 'srcx/main.rs'):
            self.assertEqual(self.guard.classify('srcx/main.rs', RULES), 'public')


if __name__ == '__main__':
    unittest.main()
