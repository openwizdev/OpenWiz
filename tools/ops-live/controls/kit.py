#!/usr/bin/env python3
"""Offline kit-control validator for #2190's bounded acceptance kit (#2219, OB8a).

python3 -I tools/ops-live/controls/kit.py check <kit.json>

Reads one synthetic or prepared kit-controls document and refuses it unless it
pins every bound below. Exit 0: pinned; 1: refused (every refusal on stderr);
2: usage or an unreadable file. It reads only that file: no network, no
GitHub, no room-cli, no write. A pass is never permission to run anything and
never a live result.

It defines no endpoint, operation, evidence or result shape: those come from
#2187's contract and #2190's adapters. Evidence it cannot validate (fencing,
access, reviewer output, acknowledgements, results) is refused, as is any key
it does not know. Standard library only.
"""
import json
from pathlib import Path
import re
import sys

FORMAT = "ops-live-kit-controls/1"
# The existing permission classes a kit must state, in this order.
CLASSES = ("machine", "live", "write", "merge", "activation", "spending")
# Evidence that belongs to #2187's contract and #2190's result validation.
UNVALIDATED = ("fencing", "access", "reviewer_output", "acknowledgements", "results")
TOP = ("format", "candidates", "limits", "permissions", "stop", "restoration", "cleanup")

OBJECT_ID = re.compile(r"[0-9a-f]{40}")
REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/(?!\.\.?$)[A-Za-z0-9._-]+")
PART = re.compile(r"[A-Za-z0-9._-]+")
# A private-record comment pointer (docs/agents/issue-tracker.md).
POINTER = re.compile(
    r"https://github\.com/jparker2006/ClosedWiz/(?:issues|pull)/[1-9][0-9]*"
    r"#issuecomment-[1-9][0-9]*")
MISSING = object()
USAGE = "usage: kit.py check <kit.json>"


class Refused(ValueError):
    """The kit's text is not one strict JSON document."""


def read(text):
    """Strict JSON: no repeated key, no NaN or Infinity."""
    def pairs(items):
        seen = {}
        for key, value in items:
            if key in seen:
                raise Refused(f'duplicate key "{key}"')
            seen[key] = value
        return seen

    def constant(name):
        raise Refused("not JSON")

    try:
        return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except Refused:
        raise
    except (ValueError, RecursionError):  # also an integer too long to convert
        raise Refused("not JSON") from None


def check(doc):
    """Return every refusal as "<path>: <reason>"; an empty list is a pass."""
    if not isinstance(doc, dict):
        return ["kit: not an object"]
    out = []
    for key in doc:
        if key in UNVALIDATED:
            out.append(f"{key}: evidence this validator cannot validate")
        elif key not in TOP:
            out.append(f"{key}: unknown key")
    value = doc.get("format", MISSING)
    if value is MISSING:
        out.append("format: missing")
    elif value != FORMAT:
        out.append(f"format: not {FORMAT}")
    _candidates(doc, out)
    _limits(doc, out)
    _permissions(doc, out)
    stop = _section(doc, "stop", "stop", ("conditions", "reconciliation"), out)
    if stop is not None:
        _steps(stop, "conditions", "stop.conditions", out)
        _steps(stop, "reconciliation", "stop.reconciliation", out)
    _steps(doc, "restoration", "restoration", out)
    _steps(doc, "cleanup", "cleanup", out)
    return out


def summary(doc):
    """The pass lines for a kit check() accepted."""
    needed = [c for c in CLASSES if doc["permissions"][c]["needed"]
              and not doc["permissions"][c]["granted"]]
    granted = [c for c in CLASSES if doc["permissions"][c]["granted"]]
    return [
        "pass: kit controls pinned (offline only; no live claim)",
        "needed, not granted: " + (", ".join(needed) or "none"),
        "granted, record not read back: " + (", ".join(granted) or "none"),
    ]


def _section(parent, key, path, keys, out, unknown="unknown key"):
    value = parent.get(key, MISSING)
    if value is MISSING:
        out.append(f"{path}: missing")
        return None
    if not isinstance(value, dict):
        out.append(f"{path}: not an object")
        return None
    for name in value:
        if name not in keys:
            out.append(f"{path}.{name}: {unknown}")
    return value


def _list(parent, key, path, out):
    value = parent.get(key, MISSING)
    if value is MISSING:
        out.append(f"{path}: missing")
        return []
    if not isinstance(value, list):
        out.append(f"{path}: not a list")
        return []
    if not value:
        out.append(f"{path}: empty")
    return value


def _printable(value):
    return isinstance(value, str) and value.strip() != "" and all(
        " " <= ch <= "~" for ch in value)


def _string(parent, key, path, out, valid, reason):
    value = parent.get(key, MISSING)
    if value is MISSING:
        out.append(f"{path}.{key}: missing")
    elif not _printable(value):
        out.append(f"{path}.{key}: not a non-empty printable ASCII string")
    elif not valid(value):
        out.append(f"{path}.{key}: {reason}")
    else:
        return value
    return None


def _object_id(value):
    # The all-zero id names no object.
    return OBJECT_ID.fullmatch(value) is not None and value != "0" * 40


def _branch(value):
    return ".." not in value and all(
        PART.fullmatch(part) and not part.startswith((".", "-"))
        and not part.endswith((".", ".lock")) for part in value.split("/"))


def _relative(value):
    return all(PART.fullmatch(part) and part not in (".", "..") and part.lower() != ".git"
               for part in value.split("/"))


def _candidates(doc, out):
    candidates = _section(doc, "candidates", "candidates", ("heads", "revisions"), out)
    if candidates is None:
        return
    seen = set()
    for i, head in enumerate(_list(candidates, "heads", "candidates.heads", out)):
        path = f"candidates.heads[{i}]"
        if not isinstance(head, dict):
            out.append(f"{path}: not an object")
            continue
        for name in head:
            if name not in ("repository", "branch", "commit"):
                out.append(f"{path}.{name}: unknown key")
        repository = _string(head, "repository", path, out,
                             lambda v: REPOSITORY.fullmatch(v) is not None, "not owner/name")
        branch = _string(head, "branch", path, out, _branch, "not a plain branch name")
        _string(head, "commit", path, out, _object_id, "not a full lowercase object id")
        if repository and branch:
            if (repository, branch) in seen:
                out.append(f"{path}: duplicate repository and branch")
            seen.add((repository, branch))
    revisions = _list(candidates, "revisions", "candidates.revisions", out)
    kinds, paths = set(), set()
    for i, revision in enumerate(revisions):
        path = f"candidates.revisions[{i}]"
        if not isinstance(revision, dict):
            out.append(f"{path}: not an object")
            continue
        for name in revision:
            if name not in ("kind", "path", "blob"):
                out.append(f"{path}.{name}: unknown key")
        kind = _string(revision, "kind", path, out,
                       lambda v: v in ("rule", "contract"), "not rule or contract")
        if kind:
            kinds.add(kind)
        file = _string(revision, "path", path, out, _relative,
                       "not a repository-relative path")
        _string(revision, "blob", path, out, _object_id, "not a full lowercase object id")
        if file:
            if file in paths:
                out.append(f"{path}: duplicate path")
            paths.add(file)
    if revisions:
        for kind in ("rule", "contract"):
            if kind not in kinds:
                out.append(f"candidates.revisions: no {kind} revision")


def _count(parent, key, path, out):
    value = parent.get(key, MISSING)
    if value is MISSING:
        out.append(f"{path}.{key}: missing")
    elif type(value) is not int or value < 1:
        out.append(f"{path}.{key}: not a positive integer")
    else:
        return value
    return None


def _limits(doc, out):
    limits = _section(doc, "limits", "limits",
                      ("threads", "operations", "duration_minutes"), out)
    if limits is None:
        return
    for name in ("threads", "operations"):
        path = f"limits.{name}"
        bound = _section(limits, name, path, ("active", "total"), out)
        if bound is None:
            continue
        active = _count(bound, "active", path, out)
        total = _count(bound, "total", path, out)
        if active and total and active > total:
            out.append(f"{path}: active exceeds total")
    _count(limits, "duration_minutes", "limits", out)


def _flag(parent, key, path, out):
    value = parent.get(key, MISSING)
    if value is MISSING:
        out.append(f"{path}.{key}: missing")
    elif type(value) is not bool:
        out.append(f"{path}.{key}: not true or false")
    else:
        return value
    return None


def _permissions(doc, out):
    permissions = _section(doc, "permissions", "permissions", CLASSES, out,
                           unknown="unknown permission class")
    if permissions is None:
        return
    for name in CLASSES:
        path = f"permissions.{name}"
        entry = _section(permissions, name, path, ("needed", "granted", "record"), out)
        if entry is None:
            continue
        _flag(entry, "needed", path, out)
        granted = _flag(entry, "granted", path, out)
        record = entry.get("record", MISSING)
        if record is MISSING:
            out.append(f"{path}.record: missing")
        elif record is None:
            if granted is True:
                out.append(f"{path}: granted without a record")
        elif not isinstance(record, str) or POINTER.fullmatch(record) is None:
            out.append(f"{path}.record: not a private-record comment pointer")
        elif granted is False:
            out.append(f"{path}: record without a grant")


def _steps(parent, key, path, out):
    seen = set()
    for i, step in enumerate(_list(parent, key, path, out)):
        if not _printable(step):
            out.append(f"{path}[{i}]: not a non-empty printable ASCII string")
        elif step in seen:
            out.append(f"{path}[{i}]: duplicate")
        else:
            seen.add(step)


def main(argv):
    if len(argv) != 2 or argv[0] != "check":
        print(USAGE, file=sys.stderr)
        return 2
    try:
        data = Path(argv[1]).read_bytes()
    except OSError:
        print("error: cannot read the kit file", file=sys.stderr)
        return 2
    try:
        doc = read(data.decode("utf-8"))
    except UnicodeDecodeError:
        refusals = ["not JSON"]
    except Refused as refused:
        refusals = [str(refused)]
    else:
        refusals = check(doc)
    if refusals:
        for refusal in refusals:
            print(f"refused: {refusal}", file=sys.stderr)
        return 1
    print("\n".join(summary(doc)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
