"""K3: approved initial preparation with real filtered Git; synthetic inputs only."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[3]
REVIEWED = "660c1692f3343cec36883abd57b5c88237ac5f44"


def run(*args, cwd, check=True, env=None):
    return subprocess.run(args, cwd=cwd, check=check, capture_output=True, text=True,
                          env=dict(os.environ, GIT_TERMINAL_PROMPT="0",
                                   PYTHONDONTWRITEBYTECODE="1", **(env or {})), timeout=20)


def step(name, job):
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    block = re.search(r'^  '+job+r':\n.*?(?=^  [a-z][a-z0-9-]*:\n|\Z)', workflow, re.M|re.S)[0]
    matches = [b for b in re.split(r"(?=^      - )", block, flags=re.M)
               if ("\n        name: " + name + "\n") in b
               or b.startswith("      - name: " + name + "\n")]
    if len(matches) != 1:
        raise AssertionError("expected one initial preparation step: " + name)
    return matches[0]


def script(name, job):
    match = re.search(r"^        run: \|\n((?:          .*\n|\n)+)", step(name, job), re.M)
    if not match:
        raise AssertionError("missing preparation shell: " + name)
    return textwrap.dedent(match[1])


class Preparation:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lt3-preparation-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.remote = self.root / "remote"
        self.remote.mkdir()
        run("git", "init", "-q", cwd=self.remote)
        for key in ("uploadpack.allowFilter", "uploadpack.allowAnySHA1InWant"):
            run("git", "config", key, "true", cwd=self.remote)
        files = {
            "Cargo.toml": "# Synthetic fixture workspace\n",
            "Cargo.lock": "# Synthetic fixture lock\n",
            "crates/cli/src/main.rs": "// Synthetic historical fixture source.\n",
            "tests/fixture.txt": "Synthetic fixture tests\n",
            "contracts/fixture.json": '{"synthetic_assumptions": ["contract sentinel"]}',
            "apps/web/fixture.txt": "Synthetic web fixture\n",
            "private/synthetic/secret.json": '{"synthetic_assumptions": ["excluded private sentinel"]}',
            "other.txt": "Synthetic excluded root file\n"}
        for name, contents in files.items():
            path = self.remote / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents)
        run("git", "add", ".", cwd=self.remote)
        self.commit(self.remote)
        self.old = run("git", "rev-parse", "HEAD", cwd=self.remote).stdout.strip()
        self.private_blob = run("git", "rev-parse", "HEAD:private/synthetic/secret.json",
                                cwd=self.remote).stdout.strip()
        (self.remote / "crates/cli/src/main.rs").write_text("// Synthetic current source.\n")
        run("git", "add", ".", cwd=self.remote)
        self.commit(self.remote)
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        run("git", "init", "-q", cwd=self.workspace)
        self.temp = self.root / "runner-temp"
        self.temp.mkdir()
        self.env = {"GITHUB_WORKSPACE": str(self.workspace), "RUNNER_TEMP": str(self.temp)}
        self.shell(script("Private live-check fixture destination", self.JOB), check=True)
        checkout = step("The reviewed live-check fixture source", self.JOB)
        # These are security/input contracts from the ruling, not an inferred
        # file inventory. The synthetic Git ref substitutes only for this pin.
        for line in ("ref: " + REVIEWED, "persist-credentials: false", "fetch-depth: 1",
                     "filter: blob:none", "sparse-checkout-cone-mode: false",
                     "path: .lt3-fixture-source"):
            self.assertIn("          " + line + "\n", checkout)
        self.assertIn("uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1\n", checkout)
        patterns = re.search(r"^          sparse-checkout: \|\n((?:            .*\n)+)", checkout, re.M)
        self.assertIsNotNone(patterns)
        sparse = "\n".join(line[12:] for line in patterns[1].splitlines()) + "\n"
        self.assertEqual(sparse, "/Cargo.toml\n/Cargo.lock\n/crates/\n/tests/\n/contracts/\n/apps/web/\n")
        self.stage = self.workspace / ".lt3-fixture-source"
        run("git", "init", "-q", cwd=self.stage)
        run("git", "remote", "add", "origin", self.remote.as_uri(), cwd=self.stage)
        run("git", "fetch", "-q", "--depth=1", "--filter=blob:none", "origin", self.old, cwd=self.stage)
        run("git", "config", "core.sparseCheckout", "true", cwd=self.stage)
        (self.stage / ".git/info/sparse-checkout").write_text(sparse)
        run("git", "checkout", "-q", "--detach", self.old, cwd=self.stage)
        # As in the repository's established CI fixture: checkout's auth window
        # is closed before the preparation shell/tests. No later fetch can work.
        run("git", "remote", "set-url", "origin", (self.root / "offline").as_uri(), cwd=self.stage)
        seal = script("Seal the live-check fixture source", self.JOB)
        self.assertEqual(seal.count(REVIEWED), 1)
        self.seal = seal.replace(REVIEWED, self.old)

    def commit(self, repo):
        run("git", "-c", "user.name=Synthetic Fixture", "-c",
            "user.email=synthetic@example.invalid", "commit", "-q", "--allow-empty",
            "-m", "synthetic fixture", cwd=repo)

    def shell(self, body, check=False):
        return run("bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", body,
                   cwd=self.workspace, env=self.env, check=check)

    def test_prepared_historical_inputs_work_without_a_remote_or_private_blob(self):
        result = self.shell(self.seal)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.temp / "live-check-source"
        self.assertEqual((source / "crates/cli/src/main.rs").read_text(),
                         "// Synthetic historical fixture source.\n")
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o700)
        self.assertEqual(run("git", "remote", cwd=source).stdout, "")
        self.assertFalse((source / "private").exists())
        self.assertFalse((source / "other.txt").exists())
        self.assertNotEqual(run("git", "cat-file", "-e", self.private_blob,
                                cwd=source, check=False).returncode, 0)

    def test_every_missing_prerequisite_fails_before_the_source_is_published(self):
        for name in ("Cargo.toml", "Cargo.lock", "crates", "tests", "contracts", "apps/web"):
            with self.subTest(name=name):
                path = self.stage / name
                hidden = self.root / "hidden"
                path.rename(hidden)
                try:
                    result = self.shell(self.seal)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("missing live-check fixture prerequisite: " + name, result.stderr)
                    self.assertFalse((self.temp / "live-check-source").exists())
                finally:
                    hidden.rename(path)

    def test_sparse_incapable_git_is_refused_before_checkout(self):
        fake = self.root / "fake-bin"
        fake.mkdir()
        program = fake / "git"
        for index, version in enumerate(("git version 1.8.0", "git version 2.24.9", "git version 2.27.9", "synthetic unknown version", "git version 2.28.0\nunexpected", "git version 2.28.0\runexpected")):
            with self.subTest(version=version):
                program.write_text("#!/bin/sh\nprintf '%s\\n' '" + version + "'\n")
                program.chmod(0o700)
                workspace = self.root / ("rejected-workspace-" + str(index))
                result = run("bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                             script("Private live-check fixture destination", self.JOB), cwd=self.workspace,
                             env={**self.env, "GITHUB_WORKSPACE": str(workspace),
                                  "PATH": str(fake) + os.pathsep + os.environ["PATH"]}, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("sparse-capable Git", result.stderr)
                self.assertFalse((workspace / ".lt3-fixture-source").exists())

    def test_residual_credentials_block_tests_without_exposing_values(self):
        canary = "SYNTHETIC_CREDENTIAL_CANARY"
        cases = ("orphan-file", "source-header", "main-header", "source-include",
                 "main-include", "worktree-header", "bad-worktree-config")
        for kind in cases:
            with self.subTest(kind=kind):
                case = self.root / kind
                workspace = case / "workspace"
                workspace.mkdir(parents=True)
                run("git", "init", "-q", cwd=workspace)
                source = workspace / ".lt3-fixture-source"
                shutil.copytree(self.stage, source)
                temp = case / "runner-temp"
                temp.mkdir()
                auth_file = temp / "git-credentials-00000000-0000-0000-0000-000000000000.config"
                if kind == "orphan-file":
                    auth_file.write_text("# synthetic_assumptions: cleanup failed\n" + canary)
                elif kind.startswith("worktree") or kind == "bad-worktree-config":
                    config = source / ".git/config.worktree"
                    if kind == "bad-worktree-config":
                        config.write_text("[invalid synthetic config")
                    else:
                        run("git", "config", "--file", str(config),
                            "http.https://example.invalid/.extraheader", canary, cwd=source)
                else:
                    repo = workspace if kind.startswith("main-") else source
                    if kind.endswith("header"):
                        run("git", "config", "--local",
                            "http.https://example.invalid/.extraheader", canary, cwd=repo)
                    else:
                        run("git", "config", "--local",
                            "includeIf.gitdir:" + str(repo / ".git") + ".path",
                            str(auth_file), cwd=repo)
                result = run("bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c",
                             self.seal, cwd=workspace,
                             env={"GITHUB_WORKSPACE": str(workspace), "RUNNER_TEMP": str(temp)},
                             check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("checkout credential cleanup", result.stderr)
                self.assertNotIn(canary, result.stdout + result.stderr)
                self.assertFalse((temp / "live-check-source").exists())

    def test_a_different_revision_is_refused(self):
        self.commit(self.stage)
        result = self.shell(self.seal)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("live-check fixture source revision mismatch", result.stderr)
        self.assertFalse((self.temp / "live-check-source").exists())


class NightlyPreparation(Preparation, unittest.TestCase):
    JOB = 'toolkit-nightly'


class Placements(unittest.TestCase):
    def test_actual_checkout_guard_refuses_other_placements_pins_and_gates(self):
        here=ROOT/'.github/actions/docs-only'
        source=(ROOT/'.github/workflows/ci.yml').read_text()
        proof=(here/'test.sh').read_text()
        guard=proof[proof.index('WORKFLOW="$ROOT/.github/workflows/ci.yml"'):proof.index('# The patterns as CI uses them:')]
        fixture=step('The reviewed live-check fixture source','toolkit-nightly')
        cases=[('control',source,True),
            ('missing',source.replace(fixture,'',1),False),
            ('wrong-pin',source.replace(REVIEWED,'f'*40),False),
            ('wrong-pattern',source.replace(fixture,fixture.replace('/Cargo.toml','/private/'),1),False),
            ('extra-placement',source.replace('  always:\n','  always:\n'+fixture,1),False)]
        for name,workflow,wants in cases:
            with self.subTest(case=name),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);(root/'.github/workflows').mkdir(parents=True)
                (root/'.github/workflows/ci.yml').write_text(workflow)
                command='fails=0\nok() { :; }\nbad() { echo "$*"; fails=$((fails + 1)); }\n'+guard+'\ntest "$fails" = 0\n'
                result=run('sh','-uc',command,cwd=root,check=False,env={'ROOT':str(root),'HERE':str(here)})
                self.assertEqual(result.returncode==0,wants,result.stdout+result.stderr)
                if not wants:
                    self.assertIn('LT3 fixture checkout',result.stdout)


if __name__ == "__main__":
    unittest.main()
