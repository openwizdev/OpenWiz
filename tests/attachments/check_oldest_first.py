#!/usr/bin/env python3
"""#933: run alone in an isolated worktree; restores every scratch mutation."""

import argparse
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--logs", type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be positive")
    previous_mask = os.umask(0o077)
    try:
        os.makedirs(args.logs, mode=0o700, exist_ok=True)
    finally:
        os.umask(previous_mask)
    root = Path(__file__).resolve().parents[2]
    source = root / "crates/store/src/attachments.rs"
    saved = source.read_bytes()
    original = saved.decode()
    ready_key = "                (attachment.ready_at, attachment.attachment.id.clone())"
    sort = "        ready.sort_by_key(key);"
    assert original.count(ready_key) == original.count(sort) == 1
    command = [
        "cargo", "test", "--locked", "-p", "openwiz-tests", "--test", "attachments",
        "ap08_removal_expiry::ls_lists_ready_attachments_oldest_first",
        "--", "--exact", "--nocapture", "--test-threads=1",
    ]
    env = dict(os.environ)
    env.setdefault("CARGO_BUILD_JOBS", "2")
    cases = [
        ("baseline", original, False),
        ("id-only", original.replace(ready_key, "                (Timestamp(0), attachment.attachment.id.clone())"), True),
        ("unsorted", original.replace(sort, ""), True),
        ("reversed", original.replace(sort, sort + "\n        ready.reverse();"), True),
        ("restored", original, False),
    ]
    try:
        for name, text, mutant in cases:
            source.write_text(text)
            for run in range(1, args.runs + 1):
                result = subprocess.run(command, cwd=root, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, check=False)
                log = args.logs / f"{name}-{run:02}.log"
                log.write_text(result.stdout)
                expected = 101 if mutant else 0
                assert result.returncode == expected, (
                    f"{name} run {run}: expected exit {expected}, got {result.returncode}; {log}"
                )
                assert "running 1 test\n" in result.stdout, f"test did not run: {log}"
                if mutant:
                    assert (
                        "assertion `left == right` failed" in result.stdout
                        and "fixture must list oldest first" in result.stdout
                    ), f"mutant failed for the wrong reason: {log}"
                    assert "test result: FAILED. 0 passed; 1 failed;" in result.stdout, log
            print(f"{name}: {args.runs}/{args.runs} expected {'failures' if mutant else 'passes'}", flush=True)
    finally:
        source.write_bytes(saved)


if __name__ == "__main__":
    main()
