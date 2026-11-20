"""PS2: public command tests, synthetic GitHub responses only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
HEAD = "a" * 40
BASE = "b" * 40
PRODUCT = {"filename": "crates/core/src/example.rs", "status": "modified"}
LINE = {"filename": "changes/4101.md", "status": "added"}


class Check(unittest.TestCase):
    def run_check(self, files=None, labels=None, event="pull_request", mutate=None,
                  pages=None, head=HEAD):
        files = [PRODUCT] if files is None else files
        pr = {"head": {"sha": HEAD}, "base": {"sha": BASE},
              "labels": [{"name": name} for name in (labels or [])],
              "changed_files": len(files)}
        replies = [{"data": pr}, {"data": pages if pages is not None else [files]},
                   {"data": copy.deepcopy(pr)}]
        if mutate:
            mutate(replies)
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "replies").write_text(json.dumps(replies))
            fake = folder / "gh"
            fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
folder = pathlib.Path(os.environ["FAKE_DIR"])
log = folder / "calls"
calls = log.read_text().splitlines() if log.exists() else []
with log.open("a") as out:
    out.write(json.dumps(sys.argv[1:]) + "\\n")
reply = json.loads((folder / "replies").read_text())[len(calls)]
print(reply.get("raw", json.dumps(reply.get("data"))))
sys.exit(reply.get("exit", 0))
''')
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{folder}:{os.environ['PATH']}",
                       FAKE_DIR=directory, EVENT=event, REPO="synthetic/project",
                       PR="4102", EVENT_HEAD=head)
            result = subprocess.run([sys.executable, "-I", str(HERE / "check.py")],
                                    env=env, capture_output=True, text=True)
            calls = folder / "calls"
            recorded = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
        return result, recorded

    def assert_case(self, expected, **kwargs):
        result, calls = self.run_check(**kwargs)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertIn("changelog:", result.stdout + result.stderr)
        return calls

    def test_product_needs_line(self):
        for filename in [PRODUCT["filename"], "crates/cli/src/main.rs",
                         "contracts/fleet.v1.md", "Cargo.toml", "Cargo.lock",
                         "skills/example/SKILL.md", ".claude-plugin/plugin.json",
                         "new-product/src/main.rs"]:
            for status in ["added", "modified", "removed"]:
                with self.subTest(filename=filename, status=status):
                    self.assert_case(1, files=[{"filename": filename, "status": status}])

    def test_line_or_exact_label_or_nonproduct_passes(self):
        for status in ["added", "modified"]:
            with self.subTest(status=status):
                self.assert_case(0, files=[PRODUCT, dict(LINE, status=status)])
        self.assert_case(0, labels=["no-changelog"])
        for label in ["No-changelog", "no-changelog-extra", " no-changelog"]:
            self.assert_case(1, labels=[label])
        for path in ["docs/example.md", "tests/proof/example.rs", "STATUS.md",
                     ".github/workflows/example.yml",
                     "private/evidence/example.log", "changes/README.md",
                     "tools/release/example.py", "ci/runner/example.sh"]:
            self.assert_case(0, files=[{"filename": path, "status": "modified"}])

    def test_fleet_skills_with_line_or_exact_label_pass(self):
        for filename in ["skills/example/SKILL.md", ".claude-plugin/plugin.json"]:
            with self.subTest(filename=filename):
                changed = {"filename": filename, "status": "modified"}
                self.assert_case(0, files=[changed, LINE])
                self.assert_case(0, files=[changed], labels=["no-changelog"])

    def test_invalid_or_removed_line_does_not_count(self):
        for path in ["changes/0.md", "changes/04101.md", "changes/README.md",
                     "changes/4101.MD", "changes/nested/4101.md", "changes/４１０１.md"]:
            self.assert_case(1, files=[PRODUCT, dict(LINE, filename=path)])
        self.assert_case(1, files=[PRODUCT, dict(LINE, status="removed")])

    def test_both_sides_of_rename(self):
        self.assert_case(1, files=[{"filename": "docs/old.rs", "status": "renamed",
                                    "previous_filename": PRODUCT["filename"]}])
        self.assert_case(1, files=[dict(PRODUCT, status="renamed",
                                     previous_filename="docs/old.rs")])
        self.assert_case(0, files=[PRODUCT, dict(LINE, status="renamed",
                                               previous_filename="changes/4100.md")])

    def test_paginated_complete_reads_and_no_writes(self):
        calls = self.assert_case(0, files=[PRODUCT, LINE], pages=[[PRODUCT], [LINE]])
        self.assertEqual(calls, [
            ["api", "repos/synthetic/project/pulls/4102"],
            ["api", "--paginate", "--slurp", "repos/synthetic/project/pulls/4102/files?per_page=100"],
            ["api", "repos/synthetic/project/pulls/4102"],
        ])

    def test_merge_group_needs_no_pr_or_api(self):
        self.assertEqual(self.assert_case(0, event="merge_group", head=""), [])
        self.assert_case(1, event="unknown")

    def test_live_labels_and_head_cannot_change_mid_read(self):
        self.assert_case(1, head="c" * 40, files=[PRODUCT, LINE])
        for mutation in [lambda r: r[2]["data"]["labels"].append({"name": "no-changelog"}),
                         lambda r: r[2]["data"]["head"].update(sha="c" * 40),
                         lambda r: r[2]["data"]["base"].update(sha="d" * 40)]:
            self.assert_case(1, files=[PRODUCT, LINE], mutate=mutation)

    def test_incomplete_file_list_never_passes_even_with_label(self):
        def truncate(replies):
            for index in (0, 2):
                replies[index]["data"]["changed_files"] = 2

        self.assert_case(1, files=[PRODUCT], labels=["no-changelog"], mutate=truncate)

    def test_bad_or_incomplete_api_never_passes_even_with_label(self):
        mutations = [
            lambda r: r[0].update(exit=1),
            lambda r: r[1].update(exit=1),
            lambda r: r[2].update(exit=1),
            lambda r: r[0].update(raw='{"labels":[],"labels":[]}'),
            lambda r: r[1].update(raw="not json"),
            lambda r: r[0]["data"].update(labels="no-changelog"),
            lambda r: r[0]["data"].update(changed_files=True),
            lambda r: r[0]["data"].update(changed_files=3001),
            lambda r: r[1].update(data=[[]]),
            lambda r: r[1].update(data=[[PRODUCT, PRODUCT]]),
            lambda r: r[1].update(data={"message": "failure"}),
            lambda r: r[1].update(data=[[dict(PRODUCT, status="unknown")]]),
            lambda r: r[1].update(data=[[dict(PRODUCT, filename="../docs/file")]]),
            lambda r: r[1].update(data=[[dict(PRODUCT, status="renamed")]]),
        ]
        for index, mutation in enumerate(mutations):
            with self.subTest(index=index):
                self.assert_case(1, labels=["no-changelog"], mutate=mutation)

    def test_workflow_wakes_on_label_changes_and_merge_groups(self):
        workflow = (HERE.parents[1] / "workflows/changelog.yml").read_text()
        # Check the operative trigger block, never a word in a comment.
        triggers = workflow.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("  pull_request:\n", triggers)
        self.assertIn("    types: [opened, synchronize, reopened, labeled, unlabeled, ready_for_review, edited]", triggers)
        self.assertIn("  merge_group:\n    types: [checks_requested]", triggers)
        self.assertNotIn("paths:", triggers)
        self.assertNotIn("pull_request_target", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("python3 -I .github/actions/changelog/test_check.py", workflow)
        self.assertIn("uses: ./.github/actions/changelog", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
