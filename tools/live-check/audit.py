#!/usr/bin/env python3
"""Offline compatibility and export-allowlist checks for the private toolkit."""
import ast
import json
from pathlib import Path, PurePosixPath
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def audit(root=ROOT):
    for path in (root / "tools/live-check").rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 9))
    paths = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z", "*.json"]).split(b"\0")
    count = 0
    for name in paths:
        if not name:
            continue
        path = root / name.decode()
        # Some tracked test fixtures intentionally are invalid JSON.
        try:
            doc = json.loads(path.read_text())
        except (ValueError, UnicodeError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != "openwiz.release-plan.v1":
            continue
        count += 1
        for row in doc["files"]:
            for key in ("source", "path"):
                parts = PurePosixPath(row[key]).parts
                if any(parts[i:i + 2] == ("tools", "live-check") for i in range(len(parts) - 1)):
                    raise ValueError("toolkit in export allowlist: " + name.decode())
    if count == 0:
        raise ValueError("no export allowlist read: audit is incomplete")
    return count


if __name__ == "__main__":
    count = audit()
    print("Python 3.9 grammar: all toolkit Python files pass")
    print("Privacy: toolkit absent from all %d committed release-plan allowlists" % count)
