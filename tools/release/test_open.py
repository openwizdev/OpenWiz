#!/usr/bin/env python3
"""P9: release a public branch in isolation; never reach a real remote."""
import json
import shutil
import sys
import unittest

sys.dont_write_bytecode = True
import test as base


class OpenRelease(base.ReleaseCheck):
    def setUp(self):
        super().setUp()
        shutil.rmtree(self.repo)
        self.repo = self.public
        self.git(self.repo, 'remote', 'add', 'origin', 'https://github.com/example-owner/example-release.git')
        self.git(self.repo, 'checkout', '-qb', 'release-' + base.VERSION)
        base.copy_fixture(self.repo)
        self.commit(self.repo)
        self.replan()

    def check(self, version=base.VERSION, **env):
        return super().check(version=version, **env)

    def test_release_branch_is_the_checked_tree_without_closedwiz_input(self):
        head = self.git(self.repo, 'rev-parse', 'HEAD').stdout.strip()
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads((self.evidence / 'report.json').read_text())
        self.assertEqual(report['source_head'], head)
        self.assertEqual(report['export_head'], head)
        self.assertEqual(report['export_tree'], self.git(self.repo, 'rev-parse', 'HEAD^{tree}').stdout.strip())
        self.assertEqual(self.git(self.stage / 'export', 'rev-parse', 'HEAD').stdout.strip(), head)

    def test_private_file_unlisted_by_plan_fails_before_staging(self):
        path = self.repo / 'private/planted.txt'
        path.parent.mkdir()
        path.write_text('')
        self.commit(self.repo)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('F1', (self.evidence / 'open-development-privacy.log').read_text())
        self.assertFalse((self.stage / 'export').exists())

    def test_named_terms_refuse_unlisted_source_and_exact_staged_commit(self):
        # Healthy source and staged trees pass with an explicit private input.
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        from check import Check, Refused
        from types import SimpleNamespace
        check = Check(SimpleNamespace(version=base.VERSION, repo=self.repo, historical=None,
                                      evidence=self.evidence, literals=self.literals))
        # Expand the private test input to an independently known literal that
        # exists in the already-staged fixture; do not change its commit/tree.
        self.literals.write_text("synthetic-private-name\nFixture-tested\n")
        staged_head = self.git(self.stage/"export", "rev-parse", "HEAD").stdout.strip()
        with self.assertRaisesRegex(Refused, "privacy checker failed"):
            check.open_privacy(self.stage/"export", staged_head, "staged-private.log")
        self.assertIn("T3 ", (self.evidence/"staged-private.log").read_text())
        self.assertNotIn("Fixture-tested", (self.evidence/"staged-private.log").read_text())
        self.outputs_clear()
        self.literals.write_text("synthetic-private-name\nsynthetic.private+name\n")
        (self.repo/"unlisted.txt").write_text("prefix-synthetic-private-name-suffix\n")
        self.commit(self.repo)
        # The tool itself may live under a private operator path. Its failure
        # must not echo a named term from that path into release diagnostics.
        private_tools = self.root/"synthetic-private-name"
        self.cli.parent.parent.rename(private_tools)
        self.cli = private_tools/"release/release"
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("T3 ", (self.evidence/"open-development-privacy.log").read_text())
        self.assertNotIn("synthetic-private-name", result.stdout+result.stderr)
        self.assertNotIn("synthetic-private-name", (self.evidence/"report.json").read_text())
        self.assertFalse((self.stage/"export").exists())

    def test_private_tool_startup_diagnostics_are_not_saved(self):
        # R2: exercise the real Python startup error under a private tool path,
        # plus unexpected traceback/stdout/stderr from the copied O3 program.
        private_tools = self.root/"synthetic-private-name"
        self.cli.parent.parent.rename(private_tools)
        self.cli = private_tools/"release/release"
        tool = private_tools/"privacy-check/check.py"
        original = tool.read_bytes()
        for script in (None,
                       "raise RuntimeError('synthetic-private-name')\n",
                       "print('synthetic-private-name')\n",
                       "import sys\nprint('literals: used')\nprint('synthetic-private-name', file=sys.stderr)\n"):
            with self.subTest(script=script):
                self.outputs_clear()
                if script is None:
                    tool.unlink()
                else:
                    tool.write_text(script)
                result = self.check()
                self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
                self.assertEqual(result.stderr, "release check refused: open-development-privacy: privacy checker failed\n")
                self.assertNotIn("synthetic-private-name", result.stdout+result.stderr)
                self.assertEqual((self.evidence/"open-development-privacy.log").read_text(),
                                 "READ privacy-checker:1\n")
                for path in self.evidence.rglob("*"):
                    if path.is_file():
                        self.assertNotIn(b"synthetic-private-name", path.read_bytes())
                self.assertEqual(json.loads((self.evidence/"report.json").read_text())["status"], "fail")
                self.assertFalse((self.stage/"export").exists())
        self.outputs_clear()
        tool.write_bytes(original)
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("synthetic-private-name", result.stdout+result.stderr)
        for name in ("open-development-privacy.log", "staged-privacy.log"):
            self.assertEqual((self.evidence/name).read_text(), "literals: used\n")

    def test_record_form_unlisted_by_plan_is_refused(self):
        (self.repo / 'planted.txt').write_text('Started thr_' + 'plantedrelease1.\n')
        self.commit(self.repo)
        result = self.check()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('T1', (self.evidence / 'open-development-privacy.log').read_text())
        self.assertFalse((self.stage / 'export').exists())

    def test_public_development_files_keep_their_paths_and_destination(self):
        files = {"AGENTS.md": "# Agents\n\nContext: Synthetic public guide.\n",
                 "docs/adr/0001-example.md": "# Decision\n\nContext: Synthetic public decision.\n",
                 ".github/workflows/example.yml": "name: example\non: push\njobs:\n  check:\n    runs-on: ubuntu-24.04\n    steps:\n      - run: echo synthetic\n"}
        self.git(self.repo,"remote","set-url","origin","git@github.com:example-next/moved-release.git")
        for path,text in files.items():
            dest = self.repo/path
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(text)
        self.commit(self.repo)
        self.replan()
        result = self.check()
        self.assertEqual(result.returncode,0,result.stderr)
        for path,text in files.items():
            self.assertEqual((self.stage/"export"/path).read_text(),text)
        self.assertEqual(self.git(self.stage/"export","remote","get-url","origin").stdout.strip(),
                         "https://github.com/example-next/moved-release.git")

    def test_unlisted_clean_file_cannot_be_dropped_from_the_release(self):
        (self.repo/"unlisted.txt").write_text("Synthetic public content.\n")
        self.commit(self.repo)
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn("allowlist does not equal release tree",result.stderr)
        self.assertFalse((self.stage/"export").exists())

    def test_separate_source_copy_and_renamed_sources_are_refused(self):
        result = base.run([sys.executable,self.cli,"check",base.VERSION,"--repo",self.repo,
                           "--public-repo",self.bin,"--plan",self.plan,"--staging",self.stage,
                           "--evidence",self.evidence,"--literals",self.literals],env=self.env)
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn("export has retired",result.stderr)
        self.assertFalse(self.stage.exists())
        self.data["files"][0]["source"] = "public/README.md"
        self.save_plan()
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn("release rows must name their own tracked path",result.stderr)

    def test_missing_ambiguous_and_unsafe_origins_fail_closed(self):
        for origin in (None,"https://github.com.evil.invalid/example-owner/example-release.git",
                       "https://user:synthetic" + "@github.com/example-owner/example-release.git",
                       "../other-repo"):
            with self.subTest(origin=origin):
                self.outputs_clear()
                self.git(self.repo,"config","--unset-all","remote.origin.url")
                if origin is not None:
                    self.git(self.repo,"config","--add","remote.origin.url",origin)
                result = self.check()
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertIn("stage:",result.stderr)
                if origin is None:
                    self.git(self.repo,"config","--add","remote.origin.url","https://github.com/example-owner/example-release.git")
        self.outputs_clear()
        self.git(self.repo,"config","--add","remote.origin.url","https://github.com/example-owner/example-release.git")
        result = self.check()
        self.assertEqual(result.returncode,1,result.stderr)
        self.assertIn("one origin URL",result.stderr)

    def test_owned_paths_have_no_fixed_previous_repository_target(self):
        previous = "jparker2006" + "/OpenWiz"
        for folder in (base.ROOT/"tools/release",base.ROOT/".github/actions/changelog"):
            for path in folder.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    self.assertNotIn(previous,path.read_text(),str(path))
        self.assertNotIn(previous,(base.ROOT/".github/workflows/changelog.yml").read_text())


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(OpenRelease(name) for name in OpenRelease.__dict__ if name.startswith('test_'))


if __name__ == '__main__':
    # Inherited release scanner proofs are owned by test.py, run only P9 here.
    suite = unittest.TestSuite(OpenRelease(name) for name in OpenRelease.__dict__ if name.startswith('test_'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
