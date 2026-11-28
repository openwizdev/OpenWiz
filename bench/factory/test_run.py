#!/usr/bin/env python3

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


FACTORY_DIR = Path(__file__).resolve().parent
REPO_ROOT = FACTORY_DIR.parent.parent
RUN_SCRIPT = FACTORY_DIR / "run.py"
SCHEMA_PATH = REPO_ROOT / "contracts" / "factory-bench.v1.schema.json"


FAKE_GH_SOURCE = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

args = sys.argv[1:]
log_path = Path(os.environ["FAKE_GH_LOG"])
with log_path.open("a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")

state_path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_path.read_text(encoding="utf-8"))

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

if len(args) >= 2 and args[0] == "repo" and args[1] == "create":
    repo = args[2]
    source_idx = args.index("--source") + 1 if "--source" in args else None
    source_dir = args[source_idx] if source_idx is not None else None
    state.setdefault("created_repos", []).append({
        "repo": repo,
        "private": "--private" in args,
        "source_exists": bool(source_dir and Path(source_dir).is_dir()),
        "push": "--push" in args,
    })
    save()
    print(f"https://example.com/{repo}")
    sys.exit(0)

if len(args) >= 2 and args[0] == "issue" and args[1] == "create":
    repo = args[args.index("-R") + 1]
    title = args[args.index("--title") + 1]
    body = args[args.index("--body") + 1]
    tickets = state.setdefault("created_issues", [])
    number = len(tickets) + 1
    url = f"https://example.com/{repo}/issues/{number}"
    tickets.append({"repo": repo, "title": title, "body": body, "url": url})
    save()
    print(url)
    sys.exit(0)

if len(args) >= 2 and args[0] == "pr" and args[1] == "list":
    repo = args[args.index("-R") + 1]
    prs = state.get("prs_by_repo", {}).get(repo, [])
    print(json.dumps(prs))
    sys.exit(0)

if len(args) >= 2 and args[0] == "issue" and args[1] == "list":
    repo = args[args.index("-R") + 1]
    issues = state.get("issues_by_repo", {}).get(repo, [])
    print(json.dumps(issues))
    sys.exit(0)

if len(args) >= 2 and args[0] == "repo" and args[1] == "clone":
    repo = args[2]
    dest = Path(args[3])
    fixture_tree = state.get("trees_by_repo", {}).get(repo)
    if not fixture_tree:
        sys.stderr.write(f"missing fixture tree for {repo}\n")
        sys.exit(1)
    shutil.copytree(fixture_tree, dest)
    sys.exit(0)

if len(args) >= 2 and args[0] == "repo" and args[1] == "delete":
    repo = args[2]
    if repo in state.get("refuse_delete", []):
        sys.stderr.write("delete refused by policy\n")
        sys.exit(1)
    state.setdefault("deleted_repos", []).append(repo)
    save()
    sys.exit(0)

if len(args) >= 2 and args[0] == "repo" and args[1] == "archive":
    repo = args[2]
    state.setdefault("archived_repos", []).append(repo)
    save()
    sys.exit(0)

sys.stderr.write(f"unexpected fake gh call: {args}\n")
sys.exit(99)
"""


def build_fixture_workspace(tmp: Path):
    bench_dir = tmp / "bench"
    bench_dir.mkdir()
    tasks = []
    specs = [
        ("alpha-pass", "Pass the alpha fixture.", "python3 judge.py", 10, 5, 400),
        ("beta-fail", "Fix the beta fixture.", "python3 judge.py", 10, 8, 600),
        ("gamma-unmerged", "Implement the gamma fixture.", "python3 judge.py", 10, 12, 1000),
    ]
    for task_id, instruction, judge_cmd, timeout, wall_min, tokens in specs:
        start_dir = bench_dir / "tasks" / task_id / "start"
        start_dir.mkdir(parents=True)
        (start_dir / "README.md").write_text(f"# {task_id}\n", encoding="utf-8")
        tasks.append({
            "id": task_id,
            "source": {
                "product": "Synthetic Bench",
                "repository": "https://example.com/synthetic/bench",
                "commit": "1" * 40,
                "licence": "MIT",
            },
            "instruction": instruction,
            "start": f"tasks/{task_id}/start",
            "judge": {"run": judge_cmd, "timeout": timeout},
            "caps": {"wall_minutes": wall_min, "tokens": tokens},
        })

    task_set = {
        "schema": "openwiz.factory-bench.v1",
        "name": "Synthetic factory bench",
        "tasks": tasks,
    }
    tasks_file = bench_dir / "tasks.v1.json"
    tasks_file.write_text(json.dumps(task_set, indent=2), encoding="utf-8")

    trees = {}
    pass_tree = tmp / "tree-alpha"
    pass_tree.mkdir()
    (pass_tree / "judge.py").write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    trees["synthetic-owner/openwiz-bench-0.2.0-alpha-pass"] = str(pass_tree)

    fail_tree = tmp / "tree-beta"
    fail_tree.mkdir()
    (fail_tree / "judge.py").write_text("import sys; sys.exit(1)\n", encoding="utf-8")
    trees["synthetic-owner/openwiz-bench-0.2.0-beta-fail"] = str(fail_tree)

    return bench_dir, tasks_file, task_set, trees


class FactoryBenchRunnerTests(unittest.TestCase):
    def run_cli(self, tmp: Path, args, state_data):
        bin_dir = tmp / "bin"
        bin_dir.mkdir(exist_ok=True)
        fake_gh = bin_dir / "gh"
        fake_gh.write_text(FAKE_GH_SOURCE, encoding="utf-8")
        fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)

        log_path = tmp / "gh.log"
        if log_path.exists():
            log_path.unlink()
        state_path = tmp / "state.json"
        state_path.write_text(json.dumps(state_data), encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["FAKE_GH_LOG"] = str(log_path)
        env["FAKE_GH_STATE"] = str(state_path)
        env.pop("GH_TOKEN", None)
        env.pop("GITHUB_TOKEN", None)

        proc = subprocess.run(
            [sys.executable, "-I", str(RUN_SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        calls = (
            [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
            if log_path.exists()
            else []
        )
        state = json.loads(state_path.read_text(encoding="utf-8"))
        return proc, calls, state

    def test_prepare_without_yes_creates_nothing_and_prints_estimate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _, tasks_file, _, _ = build_fixture_workspace(tmp)
            proc, calls, state = self.run_cli(
                tmp,
                ["prepare", "0.2.0", "--owner", "synthetic-owner", "--tasks", str(tasks_file)],
                {},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(calls, [], f"prepare without --yes must not call gh: {calls}")
            self.assertEqual(state.get("created_repos", []), [])
            self.assertIn("disposable_repositories: 3", proc.stdout)
            self.assertIn("estimated_wall_minutes: 25", proc.stdout)
            self.assertIn("estimated_tokens: 2000", proc.stdout)

    def test_prepare_with_yes_creates_private_repos_and_tickets_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            _, tasks_file, _, _ = build_fixture_workspace(tmp)
            proc, calls, state = self.run_cli(
                tmp,
                ["prepare", "0.2.0", "--owner", "synthetic-owner", "--tasks", str(tasks_file), "--yes"],
                {},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            repos = state.get("created_repos", [])
            issues = state.get("created_issues", [])
            self.assertEqual(len(repos), 3)
            self.assertEqual(len(issues), 3)
            self.assertEqual(
                [r["repo"] for r in repos],
                [
                    "synthetic-owner/openwiz-bench-0.2.0-alpha-pass",
                    "synthetic-owner/openwiz-bench-0.2.0-beta-fail",
                    "synthetic-owner/openwiz-bench-0.2.0-gamma-unmerged",
                ],
            )
            for repo in repos:
                self.assertTrue(repo["private"])
                self.assertTrue(repo["source_exists"])
                self.assertTrue(repo["push"])
            for issue in issues:
                self.assertIn("python3 judge.py", issue["body"])
            self.assertIn("Pass the alpha fixture.", issues[0]["body"])
            for argv in calls:
                self.assertIn(tuple(argv[:2]), {("repo", "create"), ("issue", "create")})

    def test_score_judges_merged_marks_unmerged_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            bench_dir, tasks_file, task_set, trees = build_fixture_workspace(tmp)
            results_dir = bench_dir / "results"
            candidate_commit = "a" * 40

            state_data = {
                "trees_by_repo": trees,
                "refuse_delete": ["synthetic-owner/openwiz-bench-0.2.0-beta-fail"],
                "issues_by_repo": {
                    "synthetic-owner/openwiz-bench-0.2.0-alpha-pass": [
                        {"number": 1, "createdAt": "2030-01-02T10:00:00Z"}
                    ],
                    "synthetic-owner/openwiz-bench-0.2.0-beta-fail": [
                        {"number": 1, "createdAt": "2030-01-02T10:00:00Z"}
                    ],
                    "synthetic-owner/openwiz-bench-0.2.0-gamma-unmerged": [
                        {"number": 1, "createdAt": "2030-01-02T10:00:00Z"}
                    ],
                },
                "prs_by_repo": {
                    "synthetic-owner/openwiz-bench-0.2.0-alpha-pass": [
                        {
                            "number": 2,
                            "url": "https://example.com/synthetic-owner/openwiz-bench-0.2.0-alpha-pass/pull/2",
                            "createdAt": "2030-01-02T10:01:00Z",
                            "mergedAt": "2030-01-02T10:03:00Z",
                        }
                    ],
                    "synthetic-owner/openwiz-bench-0.2.0-beta-fail": [
                        {
                            "number": 2,
                            "url": "https://example.com/synthetic-owner/openwiz-bench-0.2.0-beta-fail/pull/2",
                            "createdAt": "2030-01-02T10:01:00Z",
                            "mergedAt": "2030-01-02T10:04:00Z",
                        }
                    ],
                    "synthetic-owner/openwiz-bench-0.2.0-gamma-unmerged": [],
                },
            }

            proc, _, state = self.run_cli(
                tmp,
                [
                    "score",
                    "0.2.0",
                    "--owner",
                    "synthetic-owner",
                    "--commit",
                    candidate_commit,
                    "--tasks",
                    str(tasks_file),
                    "--results-dir",
                    str(results_dir),
                ],
                state_data,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            result_file = results_dir / "0.2.0.json"
            self.assertTrue(result_file.is_file())
            result = json.loads(result_file.read_text(encoding="utf-8"))

            expected_hash = hashlib.sha256(
                json.dumps(task_set, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            self.assertEqual(result["schema"], "openwiz.factory-bench.v1")
            self.assertEqual(result["version"], "0.2.0")
            self.assertEqual(result["commit"], candidate_commit)
            self.assertEqual(result["hash"], expected_hash)

            by_id = {entry["id"]: entry for entry in result["tasks"]}
            self.assertEqual(set(by_id.keys()), {"alpha-pass", "beta-fail", "gamma-unmerged"})
            self.assertEqual(by_id["alpha-pass"]["result"], "pass")
            self.assertEqual(by_id["alpha-pass"]["wall_minutes"], 3.0)
            self.assertEqual(
                by_id["alpha-pass"]["link"],
                "https://example.com/synthetic-owner/openwiz-bench-0.2.0-alpha-pass/pull/2",
            )
            self.assertEqual(by_id["beta-fail"]["result"], "fail")
            self.assertEqual(by_id["gamma-unmerged"]["result"], "unproved: not merged")
            self.assertIsNone(by_id["gamma-unmerged"]["link"])

            self.assertEqual(
                set(state.get("deleted_repos", [])),
                {
                    "synthetic-owner/openwiz-bench-0.2.0-alpha-pass",
                    "synthetic-owner/openwiz-bench-0.2.0-gamma-unmerged",
                },
            )
            self.assertEqual(
                state.get("archived_repos", []),
                ["synthetic-owner/openwiz-bench-0.2.0-beta-fail"],
            )
            self.assertIn("cleanup: synthetic-owner/openwiz-bench-0.2.0-alpha-pass deleted", proc.stdout)
            self.assertIn("cleanup: synthetic-owner/openwiz-bench-0.2.0-beta-fail archived", proc.stdout)
            self.assertIn("cleanup: synthetic-owner/openwiz-bench-0.2.0-gamma-unmerged deleted", proc.stdout)

            self.assertEqual(set(result.keys()), {"schema", "version", "commit", "hash", "tasks"})
            for entry in result["tasks"]:
                self.assertEqual(
                    set(entry.keys()),
                    {"id", "result", "wall_minutes", "tokens", "attempts", "link"},
                )


if __name__ == "__main__":
    unittest.main()
