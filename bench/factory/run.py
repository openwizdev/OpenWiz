#!/usr/bin/env python3

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile


SCHEMA = "openwiz.factory-bench.v1"
PERMISSIVE_LICENCES = frozenset({"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"})
VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9.+-]*$")
OWNER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")
TASK_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
URL_RE = re.compile(r"^https://[^/\s@?#]+/[^\s?#]+$")

FACTORY_DIR = Path(__file__).resolve().parent
DEFAULT_TASKS = FACTORY_DIR / "tasks.v1.json"
DEFAULT_RESULTS_DIR = FACTORY_DIR / "results"


def unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def is_pos_int(value):
    return type(value) is int and value >= 1


def load_task_set(tasks_path: Path):
    raw = tasks_path.read_text(encoding="utf-8")
    data = json.loads(raw, object_pairs_hook=unique_pairs)
    if not isinstance(data, dict) or set(data.keys()) != {"schema", "name", "tasks"}:
        raise ValueError("task set must contain exactly schema, name, and tasks")
    if data["schema"] != SCHEMA:
        raise ValueError(f"unexpected schema: {data['schema']!r}")
    if not isinstance(data["name"], str) or not data["name"]:
        raise ValueError("task set name must be a non-empty string")
    tasks = data["tasks"]
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("task set tasks must be a non-empty array")

    base_dir = tasks_path.resolve().parent
    seen_ids = set()
    for task in tasks:
        if not isinstance(task, dict) or set(task.keys()) != {
            "id",
            "source",
            "instruction",
            "start",
            "judge",
            "caps",
        }:
            raise ValueError("task object has missing or extra fields")
        task_id = task["id"]
        if not isinstance(task_id, str) or not TASK_ID_RE.fullmatch(task_id):
            raise ValueError(f"invalid task id: {task_id!r}")
        if task_id in seen_ids:
            raise ValueError(f"duplicate task id: {task_id!r}")
        seen_ids.add(task_id)

        source = task["source"]
        if not isinstance(source, dict) or set(source.keys()) != {
            "product",
            "repository",
            "commit",
            "licence",
        }:
            raise ValueError(f"task {task_id}: invalid source object")
        if not isinstance(source["product"], str) or not source["product"]:
            raise ValueError(f"task {task_id}: invalid source.product")
        if not isinstance(source["repository"], str) or not URL_RE.fullmatch(source["repository"]):
            raise ValueError(f"task {task_id}: invalid source.repository")
        if not isinstance(source["commit"], str) or not COMMIT_RE.fullmatch(source["commit"]):
            raise ValueError(f"task {task_id}: invalid source.commit")
        if source["licence"] not in PERMISSIVE_LICENCES:
            raise ValueError(f"task {task_id}: licence not in permissive list")

        if not isinstance(task["instruction"], str) or not task["instruction"]:
            raise ValueError(f"task {task_id}: invalid instruction")
        start = task["start"]
        if not isinstance(start, str) or not start:
            raise ValueError(f"task {task_id}: invalid start path")
        start_dir = (base_dir / start).resolve()
        try:
            start_dir.relative_to(base_dir)
        except ValueError as exc:
            raise ValueError(f"task {task_id}: start path escapes task-set directory") from exc
        if not start_dir.is_dir():
            raise ValueError(f"task {task_id}: start directory does not exist: {start}")

        judge = task["judge"]
        if not isinstance(judge, dict) or set(judge.keys()) != {"run", "timeout"}:
            raise ValueError(f"task {task_id}: invalid judge object")
        if not isinstance(judge["run"], str) or not judge["run"]:
            raise ValueError(f"task {task_id}: invalid judge.run")
        if not is_pos_int(judge["timeout"]):
            raise ValueError(f"task {task_id}: invalid judge.timeout")

        caps = task["caps"]
        if not isinstance(caps, dict) or set(caps.keys()) != {"wall_minutes", "tokens"}:
            raise ValueError(f"task {task_id}: invalid caps object")
        if not is_pos_int(caps["wall_minutes"]) or not is_pos_int(caps["tokens"]):
            raise ValueError(f"task {task_id}: invalid caps values")

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    return data, digest, base_dir


def disposable_repo(owner: str, version: str, task_id: str) -> str:
    return f"{owner}/openwiz-bench-{version}-{task_id}"


def run_cmd(argv, cwd=None, timeout=120):
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def parse_utc(value):
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def resolve_commit(commit_arg):
    if commit_arg is not None:
        if not COMMIT_RE.fullmatch(commit_arg):
            raise ValueError(f"invalid --commit: expected 40 lowercase hex chars, got {commit_arg!r}")
        return commit_arg
    proc = run_cmd(["git", "rev-parse", "HEAD"], cwd=FACTORY_DIR.parent.parent)
    sha = proc.stdout.strip()
    if proc.returncode != 0 or not COMMIT_RE.fullmatch(sha):
        raise ValueError("could not resolve candidate git commit; pass --commit <40-hex>")
    return sha


def stage_starting_repo(start_dir: Path, stage_dir: Path, task_id: str):
    shutil.copytree(start_dir, stage_dir)
    for cmd in (
        ["git", "init", "-b", "main"],
        ["git", "config", "user.name", "openwiz-bench"],
        ["git", "config", "user.email", "openwiz-bench@users.noreply.github.com"],
        ["git", "add", "."],
        ["git", "commit", "-m", f"Initial starting files for {task_id}"],
    ):
        proc = run_cmd(cmd, cwd=stage_dir)
        if proc.returncode != 0:
            raise RuntimeError(f"git staging failed ({' '.join(cmd)}): {proc.stderr.strip()}")


def format_ticket_body(task):
    return (
        "## Instruction\n\n"
        f"{task['instruction']}\n\n"
        "## Acceptance criteria\n\n"
        f"- [ ] Judge exits 0: `{task['judge']['run']}` (timeout {task['judge']['timeout']}s)\n\n"
        "## Caps\n\n"
        f"- wall_minutes: {task['caps']['wall_minutes']}\n"
        f"- tokens: {task['caps']['tokens']}\n"
    )


def cmd_prepare(args):
    task_set, _, base_dir = load_task_set(Path(args.tasks))
    tasks = task_set["tasks"]
    total_wall = sum(t["caps"]["wall_minutes"] for t in tasks)
    total_tokens = sum(t["caps"]["tokens"] for t in tasks)

    print(f"disposable_repositories: {len(tasks)}")
    print(f"estimated_wall_minutes: {total_wall}")
    print(f"estimated_tokens: {total_tokens}")
    for task in tasks:
        print(f"planned: {disposable_repo(args.owner, args.version, task['id'])}")

    if not args.yes:
        print("dry-run: pass --yes to create these private repositories and tickets.")
        return 0

    for task in tasks:
        repo = disposable_repo(args.owner, args.version, task["id"])
        start_dir = (base_dir / task["start"]).resolve()
        with tempfile.TemporaryDirectory() as tmpdir:
            stage_dir = Path(tmpdir) / "repo"
            stage_starting_repo(start_dir, stage_dir, task["id"])
            create = run_cmd(
                ["gh", "repo", "create", repo, "--private", "--source", str(stage_dir), "--push"]
            )
            if create.returncode != 0:
                print(f"error: failed to create {repo}: {create.stderr.strip()}", file=sys.stderr)
                return 1
        issue = run_cmd(
            [
                "gh",
                "issue",
                "create",
                "-R",
                repo,
                "--title",
                f"{task['id']}: {task['instruction'].splitlines()[0][:72]}",
                "--body",
                format_ticket_body(task),
            ]
        )
        if issue.returncode != 0:
            print(f"error: failed to create ticket in {repo}: {issue.stderr.strip()}", file=sys.stderr)
            return 1
        ticket_url = issue.stdout.strip().splitlines()[-1] if issue.stdout.strip() else "unknown"
        print(f"created: {repo} ticket {ticket_url}")
    return 0


def read_json_list(argv):
    proc = run_cmd(argv)
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def cleanup_disposable_repo(repo: str):
    deleted = run_cmd(["gh", "repo", "delete", repo, "--yes"])
    if deleted.returncode == 0:
        print(f"cleanup: {repo} deleted")
        return "deleted"
    archived = run_cmd(["gh", "repo", "archive", repo, "--yes"])
    if archived.returncode == 0:
        print(f"cleanup: {repo} archived")
        return "archived"
    print(f"cleanup: {repo} failed")
    return "failed"


def run_judge(judge_cmd: str, timeout: int, tree_dir: Path) -> str:
    argv = shlex.split(judge_cmd)
    if not argv:
        return "unproved: empty judge command"
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in {"GH_TOKEN", "GITHUB_TOKEN", "OPENWIZ_GITHUB_APP_KEY"}
    }
    try:
        proc = subprocess.run(
            argv,
            cwd=tree_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"unproved: judge timed out after {timeout}s"
    except OSError:
        return "unproved: judge could not start"
    return "pass" if proc.returncode == 0 else "fail"


def score_task(task, repo: str):
    prs = read_json_list(
        [
            "gh",
            "pr",
            "list",
            "-R",
            repo,
            "--state",
            "merged",
            "--limit",
            "20",
            "--json",
            "number,url,createdAt,mergedAt",
        ]
    )
    issues = read_json_list(
        [
            "gh",
            "issue",
            "list",
            "-R",
            repo,
            "--state",
            "all",
            "--limit",
            "20",
            "--json",
            "number,createdAt",
        ]
    )
    if prs is None or not prs:
        return {
            "id": task["id"],
            "result": "unproved: not merged",
            "wall_minutes": 0,
            "tokens": 0,
            "attempts": 0,
            "link": None,
        }

    prs_with_time = []
    for pr in prs:
        merged_dt = parse_utc(pr.get("mergedAt"))
        if merged_dt is not None and isinstance(pr.get("url"), str) and URL_RE.fullmatch(pr["url"]):
            prs_with_time.append((merged_dt, pr))
    if not prs_with_time:
        return {
            "id": task["id"],
            "result": "unproved: not merged",
            "wall_minutes": 0,
            "tokens": 0,
            "attempts": len(prs),
            "link": None,
        }

    prs_with_time.sort(key=lambda item: item[0])
    merged_dt, chosen_pr = prs_with_time[-1]

    start_dt = None
    if issues:
        issue_times = [parse_utc(item.get("createdAt")) for item in issues]
        issue_times = [dt for dt in issue_times if dt is not None]
        if issue_times:
            start_dt = min(issue_times)
    if start_dt is None:
        start_dt = parse_utc(chosen_pr.get("createdAt"))

    wall_minutes = 0.0
    if start_dt is not None and merged_dt >= start_dt:
        wall_minutes = round((merged_dt - start_dt).total_seconds() / 60.0, 2)

    if wall_minutes > task["caps"]["wall_minutes"]:
        return {
            "id": task["id"],
            "result": "unproved: not merged",
            "wall_minutes": wall_minutes,
            "tokens": 0,
            "attempts": len(prs),
            "link": None,
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        checkout_dir = Path(tmpdir) / "tree"
        cloned = run_cmd(["gh", "repo", "clone", repo, str(checkout_dir)])
        if cloned.returncode != 0:
            verdict = "unproved: clone failed"
        else:
            verdict = run_judge(task["judge"]["run"], task["judge"]["timeout"], checkout_dir)

    return {
        "id": task["id"],
        "result": verdict,
        "wall_minutes": wall_minutes,
        "tokens": 0,
        "attempts": len(prs),
        "link": chosen_pr["url"],
    }


def cmd_score(args):
    task_set, task_set_hash, _ = load_task_set(Path(args.tasks))
    candidate_commit = resolve_commit(args.commit)
    task_results = []

    for task in task_set["tasks"]:
        repo = disposable_repo(args.owner, args.version, task["id"])
        entry = score_task(task, repo)
        task_results.append(entry)
        cleanup_disposable_repo(repo)

    result = {
        "schema": SCHEMA,
        "version": args.version,
        "commit": candidate_commit,
        "hash": task_set_hash,
        "tasks": task_results,
    }
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    out_path = results_dir / f"{args.version}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    passes = sum(1 for item in task_results if item["result"] == "pass")
    print(f"wrote: {out_path}")
    print(f"score: {passes}/{len(task_results)}")
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Prepare disposable factory-bench tickets and score merged results."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prep = sub.add_parser("prepare", help="Estimate and optionally create disposable repos and tickets.")
    prep.add_argument("version", help="Candidate release version (e.g. 0.2.0).")
    prep.add_argument("--owner", required=True, help="GitHub account or organization for disposable repos.")
    prep.add_argument("--yes", action="store_true", help="Actually create private disposable repos and tickets.")
    prep.add_argument("--tasks", default=str(DEFAULT_TASKS), help="Path to tasks.v1.json.")

    score = sub.add_parser("score", help="Judge merged PRs, write results/<version>.json, and clean up.")
    score.add_argument("version", help="Candidate release version (e.g. 0.2.0).")
    score.add_argument("--owner", required=True, help="GitHub account or organization holding disposable repos.")
    score.add_argument("--commit", default=None, help="Candidate 40-char git commit (defaults to HEAD).")
    score.add_argument("--tasks", default=str(DEFAULT_TASKS), help="Path to tasks.v1.json.")
    score.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help="Directory for <version>.json.")

    args = parser.parse_args(argv)
    if not VERSION_RE.fullmatch(args.version):
        parser.error(f"invalid version: {args.version!r}")
    if not OWNER_RE.fullmatch(args.owner):
        parser.error(f"invalid --owner: {args.owner!r}")
    return args


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "prepare":
        return cmd_prepare(args)
    if args.command == "score":
        return cmd_score(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
