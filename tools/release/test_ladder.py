"""Offline proofs for the release ladder CLI."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


LADDER = Path(__file__).with_name("ladder.py")
CUTOFF = "2026-01-05T12:00:00Z"
RECENT = "2026-01-05T12:01:00Z"
OLD = "2026-01-05T11:59:59Z"
FIXTURE_GH = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

calls = sys.argv[1:]
with Path(os.environ["LADDER_CALLS"]).open("a") as log:
    log.write(json.dumps(calls) + "\\n")
routes = json.loads(Path(os.environ["LADDER_ROUTES"]).read_text())
key = " ".join(calls)
if key not in routes:
    sys.exit("unexpected GitHub request")
print(json.dumps(routes[key]))
"""


class LadderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.file = self.root / "ladder.json"
        self.entries = [
            {"version": "0.1.0", "state": "released", "published_at": CUTOFF,
             "merges": [], "published_changelog": ["You can view your inventory."]},
            {"version": "0.1.1", "state": "planned", "merges": []},
            {"version": "0.1.2", "state": "planned", "merges": []},
        ]
        self.write_ladder()
        fake_gh = self.root / "gh"
        fake_gh.write_text(FIXTURE_GH, encoding="utf-8")
        fake_gh.chmod(0o755)
        self.calls = self.root / "calls"
        self.routes = self.root / "routes.json"
        self.env = dict(os.environ, PATH=f"{self.root}{os.pathsep}{os.environ['PATH']}",
                        LADDER_CALLS=str(self.calls), LADDER_ROUTES=str(self.routes))
        self.routes.write_text("{}", encoding="utf-8")

    def write_ladder(self):
        self.file.write_text(json.dumps(self.entries), encoding="utf-8")

    def invoke(self, command, *args, seed=False):
        options = [] if seed else ["--file", str(self.file)]
        return subprocess.run([sys.executable, "-I", str(LADDER), command, *options, *args],
                              cwd=self.root, env=self.env, capture_output=True, text=True,
                              timeout=30)

    def assert_refused(self, result, message):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True, timeout=10).stdout.strip()

    def commit(self, ticket=None, note=None):
        if ticket is not None:
            path = self.root / "changes" / f"{ticket}.md"
            path.parent.mkdir(exist_ok=True)
            path.write_text(note, encoding="utf-8")
            self.git("add", str(path))
        self.git("commit", "--quiet", "--allow-empty", "-m", "Synthetic change")
        return self.git("rev-parse", "HEAD")

    def github_history(self, main, first_page, second_page=()):
        prefix = "api repos/openwizdev/OpenWiz/"
        pulls = "pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100&page="
        routes = {
            prefix + "git/ref/heads/main": {"ref": "refs/heads/main",
                                           "object": {"type": "commit", "sha": main}},
            prefix + pulls + "1": first_page,
            prefix + pulls + "2": list(second_page),
        }
        self.routes.write_text(json.dumps(routes), encoding="utf-8")

    def pull(self, number, commit, merged_at=RECENT, base="main", updated_at=RECENT):
        return {"number": number, "merged_at": merged_at, "updated_at": updated_at,
                "state": "closed", "base": {"ref": base}, "merge_commit_sha": commit,
                "head": {"sha": f"{number:040x}"}}

    def history(self):
        self.git("init", "--quiet", "--initial-branch=main")
        self.git("config", "user.name", "Synthetic Builder")
        self.git("config", "user.email", "builder@example.com")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", os.devnull)
        before = self.commit(4100, "kind: added\n\nYou can open the inventory.\n")
        self.git("switch", "--quiet", "-c", "other")
        unrelated = self.commit(4199, "kind: added\n\nYou can export a draft.\n")
        self.git("switch", "--quiet", "main")
        first = self.commit(4101, "kind: fixed\n\nThe inventory keeps saved rows.\n")
        second = self.commit()
        self.git("switch", "--quiet", "-c", "unpublished")
        self.commit(4101, "kind: added\n\nYou can see a draft row.\n")
        return before, unrelated, first, second

    def test_propose_reads_only_verified_main_merges_after_publication(self):
        """Catches closed, off-main, unreachable and already released PRs entering the batch."""
        before, unrelated, first, second = self.history()
        self.github_history(second, [
            self.pull(8100, before, merged_at=OLD),
            self.pull(8105, second, base="other"),
            self.pull(8102, second),
            self.pull(8104, second, merged_at=None),
            self.pull(8103, unrelated),
            self.pull(8101, first),
            self.pull(8106, before, merged_at=CUTOFF),
        ])
        original = self.file.read_bytes()
        git_state = self.git("show-ref")
        result = self.invoke("propose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "version": "0.1.1", "state": "candidate", "merges": [
                {"pr": 8101, "merge_commit": first, "head": f"{8101:040x}",
                 "changelog": [{"ticket": 4101, "kind": "fixed",
                                "sentence": "The inventory keeps saved rows."}]},
                {"pr": 8102, "merge_commit": second, "head": f"{8102:040x}", "changelog": []},
            ],
        })
        self.assertEqual(self.file.read_bytes(), original)
        self.assertEqual(self.git("show-ref"), git_state)

    def test_propose_uses_the_last_released_patch_and_walks_pages(self):
        """Catches a stale release cutoff or dropped PRs after GitHub's first page."""
        before, _, first, second = self.history()
        self.entries[1].update(state="released", published_at=RECENT, published_changelog=[])
        self.write_ladder()
        later = "2026-01-06T12:00:00Z"
        first_page = [self.pull(n, before, merged_at=None, updated_at=later) for n in range(8200, 8298)]
        first_page += [self.pull(8101, first, updated_at=later),
                       self.pull(8100, before, merged_at=OLD, updated_at=later)]
        self.github_history(second, first_page, [self.pull(8102, second, later, updated_at=later)])
        result = self.invoke("propose", "--version", "0.1.2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {
            "version": "0.1.2", "state": "candidate", "merges": [
                {"pr": 8102, "merge_commit": second, "head": f"{8102:040x}", "changelog": []},
            ],
        })

    def test_propose_refuses_minor_major_and_skipped_versions_before_reading_github(self):
        """Catches a proposal that crosses the owner's version boundary or skips the next patch."""
        for version in ("0.2.0", "1.1.1", "0.1.0", "0.1.2", "0.01.1"):
            with self.subTest(version=version):
                self.assert_refused(self.invoke("propose", "--version", version), "version")
        self.assertFalse(self.calls.exists())

    def test_propose_refuses_unreadable_main_and_malformed_changelog(self):
        """Catches partial proposals from a missing snapshot or an invalid ticket line."""
        _, _, first, _ = self.history()
        unknown_sha = "a" * 40
        self.github_history(unknown_sha, [])
        self.assert_refused(self.invoke("propose"), "git rev-list")
        self.git("switch", "--quiet", "main")
        invalid = self.commit(4102, "kind: improved\n\nYou can export the inventory.\n")
        self.github_history(invalid, [self.pull(8101, first), self.pull(8102, invalid)])
        self.assert_refused(self.invoke("propose"), "changes/4102.md")

    def test_check_refuses_unordered_and_unknown_states(self):
        """Catches sorting on read or silently accepting an invented state."""
        for field, value, message in (("version", "0.1.3", "order"), ("state", "draft", "state")):
            with self.subTest(field=field):
                original = self.entries[1][field]
                self.entries[1][field] = value
                self.write_ladder()
                self.assert_refused(self.invoke("check"), message)
                self.entries[1][field] = original

    def test_check_accepts_fixture_and_the_published_seed(self):
        """Catches a shipped seed that cannot be opened through the normal entry point."""
        for seed in (False, True):
            with self.subTest(seed=seed):
                result = self.invoke("check", seed=seed)
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.calls.exists())


if __name__ == "__main__":
    unittest.main()
