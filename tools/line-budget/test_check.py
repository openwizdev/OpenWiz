#!/usr/bin/env python3
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

CHECK = Path(__file__).resolve().parent / 'check.py'
POINTER = 'https://github.com/jparker2006/ClosedWiz/issues/4101#issuecomment-4102'
REFERENCE = r"""git ls-files -z | xargs -0 grep -Ic '' 2>/dev/null | awk -F: '
{ p=$1; n=$2; c="product"
  if (p ~ /(^|\/)(tests?|fixtures?|__tests__|testdata)\// || p ~ /(_test|\.test|\.spec)\./ || p ~ /(^|\/)test_[^\/]*$/) c="tests+fixtures"
  else if (p ~ /^\.github\// || p ~ /^ci\//) c="ci"
  else if (p ~ /^tools\// || p ~ /^scripts\//) c="tools"
  else if (p ~ /^contracts\//) c="contracts"
  else if (p ~ /^skills\//) c="skills"
  else if (p ~ /\.md$/ || p ~ /^docs\//) c="docs"
  else if (p ~ /(\.lock|lock\.json|lock\.yaml)$/) c="lockfiles"
  L[c]+=n; F[c]++; T+=n; TF++ }
END { for (c in L) printf "%s\t%d\t%d\n", c, L[c], F[c]; printf "TOTAL\t%d\t%d\n", T, TF }' | sort"""
ROW = re.compile(r'^  (\S+) +(\d+) +(\d+) +[+-]?\d+$', re.M)


class Repo:
    def __init__(self, test):
        tmp = tempfile.TemporaryDirectory()
        test.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Synthetic')
        self.git('config', 'user.email', 'synthetic@example.com')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def write(self, path, data):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data.encode() if isinstance(data, str) else data)

    def commit(self, files=(), remove=()):
        for path, data in dict(files).items():
            self.write(path, data)
        for path in remove:
            self.git('rm', '-q', path)
        self.git('add', '-A')
        self.git('commit', '-q', '--allow-empty', '-m', 'synthetic')
        return self.git('rev-parse', 'HEAD')

    def check(self, *args, description=None):
        argv = [sys.executable, '-I', str(CHECK), '--repo-dir', str(self.root), *args]
        if description is not None:
            path = self.root.parent / f'{self.root.name}.description'
            path.write_text(description)
            argv += ['--description-file', str(path)]
        return subprocess.run(argv, capture_output=True, text=True)


def lines(n, end='\n'):
    return ''.join(f'line {i}\n' for i in range(n - 1)) + 'last' + end


class Counter(unittest.TestCase):
    def test_matches_the_reference_pipeline(self):
        repo = Repo(self)
        head = repo.commit({
            'line-budget.json': '{"ceiling": 250000}\n', 'crates/a/src/lib.rs': lines(5, ''),
            'crates/a/tests/it.rs': lines(3), 'kernel/fixtures/x.json': '\n\n\n',
            'web/__tests__/a.js': lines(2), 'web/b.test.ts': lines(4), 'web/c.spec.js': lines(1),
            'tools/x/test_y.py': lines(6), 'k/z_test.go': lines(2), 'testdata/a.txt': lines(1),
            '.github/workflows/w.yml': lines(7), 'ci/run.sh': lines(2), 'tools/t.py': lines(9),
            'scripts/s.sh': lines(3), 'contracts/c.md': lines(4), 'skills/s/SKILL.md': lines(5),
            'README.md': lines(6), 'docs/a.txt': lines(2), 'Cargo.lock': lines(11),
            'web/package-lock.json': lines(8), 'web/pnpm-lock.yaml': lines(3), 'empty.txt': '',
            'image.png': b'\x89PNG\n\x00\n\n', 'notes/latin.txt': b'caf\xe9\nok\n'})
        out = subprocess.run(['sh', '-c', REFERENCE], cwd=repo.root, check=True,
                             capture_output=True, text=True).stdout
        want = {c: int(n) for c, n, _ in (row.split('\t') for row in out.splitlines()) if int(n)}
        total = want.pop('TOTAL')
        r = repo.check('--base', head, '--merge', head, description='')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        got = {c: int(m) for c, _, m in ROW.findall(r.stdout) if int(m)}
        self.assertEqual(got.pop('total', None), total)
        self.assertEqual(got, want)
        self.assertIn(f'lockfiles excluded: {total - want["lockfiles"]}', r.stdout)


class Ceiling(unittest.TestCase):
    def setUp(self):
        self.repo = Repo(self)
        self.base = self.repo.commit({'line-budget.json': '{"ceiling": 20}\n', 'src/a.rs': lines(10)})

    def merge(self, extra, **files):
        self.repo.git('checkout', '-q', '--detach', self.base)
        return self.repo.commit({'src/b.rs': lines(extra), **files})

    def run_check(self, merge, description=''):
        return self.repo.check('--base', self.base, '--merge', merge, description=description)

    def test_under_and_at_pass_over_fails_naming_the_numbers(self):
        for extra, code in ((8, 0), (9, 0), (10, 1)):
            r = self.run_check(self.merge(extra))
            self.assertEqual(r.returncode, code, (extra, r.stdout, r.stderr))
        self.assertIn('21 lines is 1 over the ceiling of 20; grew: product +10', r.stdout + r.stderr)

    def test_budget_enforcement_resumes_when_base_reaches_the_ceiling(self):
        for base_total, expected in ((21, 0), (20, 1), (19, 1)):
            with self.subTest(base_total=base_total):
                self.repo.git('checkout', '-q', '--detach', self.base)
                base = self.repo.commit({'src/a.rs': lines(base_total - 1), 'Cargo.lock': lines(500)})
                merge = self.repo.commit({'src/a.rs': lines(21)})
                r = self.repo.check('--base', base, '--merge', merge, description='')
                self.assertEqual(r.returncode, expected, r.stdout + r.stderr)
                self.assertIn(f'22 of 20; base {base_total}, change +{22 - base_total}', r.stdout)
                if expected:
                    self.assertIn('22 lines is 2 over the ceiling of 20', r.stderr)
                else:
                    self.assertIn('report-only', r.stdout)
                    self.assertEqual(r.stderr, '')
                    malformed = self.repo.check('--base', base, '--merge', merge,
                                                description='Line budget exception: pending')
                    self.assertEqual(malformed.returncode, 1)
                    self.assertIn('malformed exception line', malformed.stderr)

    def test_lockfiles_binaries_and_symlinks_do_not_count(self):
        merge = self.merge(9, **{'Cargo.lock': lines(500), 'blob.bin': b'\x00' + b'\n' * 500,
                                 'docs/pnpm-lock.yaml': lines(3), 'tests/package-lock.json': lines(4)})
        (self.repo.root / 'link.rs').symlink_to('src/a.rs')
        merge = self.repo.commit()
        r = self.run_check(merge)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r'(?m)^  lockfiles +0 +500 +\+500$')

    def test_exception_lines(self):
        over, under = self.merge(10), self.merge(1)
        cases = [(over, f'Why.\r\nLine budget exception: {POINTER}\r\n', 0),
                 (over, f'Line budget exception: {POINTER.replace("issues", "pull")}', 0),
                 (over, 'No exception here.', 1),
                 (over, f'See: Line budget exception: {POINTER}', 1),
                 (under, f'Line budget exception: {POINTER}', 0)]
        for bad in (POINTER.replace('4101', '04101'), POINTER.replace('https', 'http'),
                    POINTER.replace('jparker2006/ClosedWiz', 'synthetic/Other'),
                    POINTER + ' please', POINTER.replace('-4102', '-0'), 'pending'):
            cases += [(over, f'Line budget exception: {bad}', 1), (under, f'Line budget exception: {bad}', 1)]
        cases += [(over, f'line budget exception: {POINTER}', 1), (over, f'    Line budget exception: {POINTER}', 1),
                  (over, f'Line budget exception: {POINTER} ', 1), (under, 'Line budget exceptions are rare.', 0),
                  (under, f'Line budget exception {POINTER}', 0), (under, f'  Line budget exception: {POINTER}x', 0)]
        for merge, description, code in cases:
            r = self.run_check(merge, description)
            self.assertEqual(r.returncode, code, (description, r.stdout, r.stderr))

    def test_a_ceiling_change_needs_its_pointer(self):
        merge = self.merge(1, **{'line-budget.json': '{"ceiling": 30}\n'})
        self.assertEqual(self.run_check(merge).returncode, 1)
        self.assertEqual(self.run_check(merge, f'Line budget ceiling: {POINTER}x').returncode, 1)
        self.assertEqual(self.run_check(merge, f'    Line budget ceiling: {POINTER}').returncode, 1)
        self.assertEqual(self.run_check(merge, f'Line budget ceiling: {POINTER}').returncode, 0)

    def test_unreadable_input_exits_2(self):
        self.assertEqual(self.run_check('no-such-rev').returncode, 2)
        for text in ('{"ceiling": "many"}', '{"ceiling": 30, "ceiling": 40}', '{"ceiling": true}', '[30]'):
            bad = self.merge(1, **{'line-budget.json': text})
            self.assertEqual(self.run_check(bad, f'Line budget ceiling: {POINTER}').returncode, 2, text)

    def test_total_always_passes(self):
        r = self.repo.check('--total', self.merge(10))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('total, lockfiles excluded: 21 of 20', r.stdout)

    def test_queue_ref_names_its_pull_request(self):
        sys.path.insert(0, str(CHECK.parent))
        from check import pr_number
        self.assertEqual(pr_number('refs/heads/gh-readonly-queue/main/pr-4101-' + 'a' * 40), 4101)
        self.assertEqual(pr_number('4102'), 4102)
        self.assertIsNone(pr_number('refs/heads/main'))


if __name__ == '__main__':
    unittest.main()
