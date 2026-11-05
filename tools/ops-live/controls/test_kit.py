#!/usr/bin/env python3
"""#2219 (OB8a): offline kit-control validation on synthetic kits only.

Claim: a kit is refused unless it pins its candidate heads and rule/contract
revisions, thread and operation counts, duration, every permission class, stop
and reconciliation, restoration and cleanup; a grant needs a private-record
pointer; evidence this validator cannot read is refused. Every expected
refusal below is a literal, not computed by the validator.
"""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "kit.json"
spec = importlib.util.spec_from_file_location("kit", HERE / "kit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


def base():
    return json.loads(FIXTURE.read_text())


def drop(*path):
    def mutate(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
    return mutate


def put(value, *path):
    def mutate(doc):
        node = doc
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    return mutate


def each(*mutations):
    def mutate(doc):
        for mutation in mutations:
            mutation(doc)
    return mutate


HEX_A = "a" * 40
POINTER = "https://github.com/jparker2006/ClosedWiz/issues/4001#issuecomment-9002"

# (case, mutation, exact refusals)
REFUSALS = [
    # Candidate heads and rule/contract revisions.
    ("no candidates", drop("candidates"), ["candidates: missing"]),
    ("no heads", drop("candidates", "heads"), ["candidates.heads: missing"]),
    ("empty heads", put([], "candidates", "heads"), ["candidates.heads: empty"]),
    ("head without commit", drop("candidates", "heads", 0, "commit"),
     ["candidates.heads[0].commit: missing"]),
    ("short commit", put("1111111", "candidates", "heads", 0, "commit"),
     ["candidates.heads[0].commit: not a full lowercase object id"]),
    ("branch name only", put("main", "candidates", "heads", 0, "commit"),
     ["candidates.heads[0].commit: not a full lowercase object id"]),
    ("uppercase commit", put("A" * 40, "candidates", "heads", 0, "commit"),
     ["candidates.heads[0].commit: not a full lowercase object id"]),
    ("head without repository", drop("candidates", "heads", 0, "repository"),
     ["candidates.heads[0].repository: missing"]),
    ("bad repository", put("example-repo", "candidates", "heads", 0, "repository"),
     ["candidates.heads[0].repository: not owner/name"]),
    ("dotdot repository", put("example-owner/..", "candidates", "heads", 0, "repository"),
     ["candidates.heads[0].repository: not owner/name"]),
    ("dot repository", put("example-owner/.", "candidates", "heads", 0, "repository"),
     ["candidates.heads[0].repository: not owner/name"]),
    ("zero commit", put("0" * 40, "candidates", "heads", 0, "commit"),
     ["candidates.heads[0].commit: not a full lowercase object id"]),
    ("branch ending in a dot", put("room/4001.", "candidates", "heads", 0, "branch"),
     ["candidates.heads[0].branch: not a plain branch name"]),
    ("head without branch", drop("candidates", "heads", 0, "branch"),
     ["candidates.heads[0].branch: missing"]),
    ("dotdot branch", put("room/../main", "candidates", "heads", 0, "branch"),
     ["candidates.heads[0].branch: not a plain branch name"]),
    ("same branch twice", lambda d: d["candidates"]["heads"].append(
        dict(d["candidates"]["heads"][0], commit=HEX_A)),
     ["candidates.heads[1]: duplicate repository and branch"]),
    ("no revisions", drop("candidates", "revisions"), ["candidates.revisions: missing"]),
    ("empty revisions", put([], "candidates", "revisions"), ["candidates.revisions: empty"]),
    ("no rule revision", lambda d: d["candidates"]["revisions"].pop(0),
     ["candidates.revisions: no rule revision"]),
    ("no contract revision", lambda d: d["candidates"]["revisions"].pop(1),
     ["candidates.revisions: no contract revision"]),
    ("revision without blob", drop("candidates", "revisions", 1, "blob"),
     ["candidates.revisions[1].blob: missing"]),
    ("revision blob not an id", put("v1", "candidates", "revisions", 1, "blob"),
     ["candidates.revisions[1].blob: not a full lowercase object id"]),
    ("unknown revision kind", put("policy", "candidates", "revisions", 0, "kind"),
     ["candidates.revisions[0].kind: not rule or contract",
      "candidates.revisions: no rule revision"]),
    ("absolute revision path", put("/etc/fleet.md", "candidates", "revisions", 0, "path"),
     ["candidates.revisions[0].path: not a repository-relative path"]),
    ("dot revision path", put("docs/./fleet.md", "candidates", "revisions", 0, "path"),
     ["candidates.revisions[0].path: not a repository-relative path"]),
    ("zero blob", put("0" * 40, "candidates", "revisions", 1, "blob"),
     ["candidates.revisions[1].blob: not a full lowercase object id"]),
    ("git directory path", put(".git/config", "candidates", "revisions", 0, "path"),
     ["candidates.revisions[0].path: not a repository-relative path"]),
    ("nested git directory path", put("docs/.Git/hooks", "candidates", "revisions", 0, "path"),
     ["candidates.revisions[0].path: not a repository-relative path"]),
    ("same path twice", lambda d: d["candidates"]["revisions"].append(
        dict(d["candidates"]["revisions"][1], blob=HEX_A)),
     ["candidates.revisions[2]: duplicate path"]),
    # Thread and operation counts, and duration.
    ("no limits", drop("limits"), ["limits: missing"]),
    ("no thread limits", drop("limits", "threads"), ["limits.threads: missing"]),
    ("no active threads", drop("limits", "threads", "active"),
     ["limits.threads.active: missing"]),
    ("no total threads", drop("limits", "threads", "total"),
     ["limits.threads.total: missing"]),
    ("no operation limits", drop("limits", "operations"), ["limits.operations: missing"]),
    ("no active operations", drop("limits", "operations", "active"),
     ["limits.operations.active: missing"]),
    ("no total operations", drop("limits", "operations", "total"),
     ["limits.operations.total: missing"]),
    ("no duration", drop("limits", "duration_minutes"), ["limits.duration_minutes: missing"]),
    ("zero duration", put(0, "limits", "duration_minutes"),
     ["limits.duration_minutes: not a positive integer"]),
    ("unbounded threads", put(None, "limits", "threads", "total"),
     ["limits.threads.total: not a positive integer"]),
    ("negative operations", put(-1, "limits", "operations", "active"),
     ["limits.operations.active: not a positive integer"]),
    ("fractional duration", put(1.5, "limits", "duration_minutes"),
     ["limits.duration_minutes: not a positive integer"]),
    ("boolean count", put(True, "limits", "threads", "active"),
     ["limits.threads.active: not a positive integer"]),
    ("string count", put("3", "limits", "threads", "active"),
     ["limits.threads.active: not a positive integer"]),
    ("active above total threads", put(7, "limits", "threads", "active"),
     ["limits.threads: active exceeds total"]),
    ("active above total operations", put(41, "limits", "operations", "active"),
     ["limits.operations: active exceeds total"]),
    # Permission classes.
    ("no permissions", drop("permissions"), ["permissions: missing"]),
    ("no machine class", drop("permissions", "machine"), ["permissions.machine: missing"]),
    ("no live class", drop("permissions", "live"), ["permissions.live: missing"]),
    ("no write class", drop("permissions", "write"), ["permissions.write: missing"]),
    ("no merge class", drop("permissions", "merge"), ["permissions.merge: missing"]),
    ("no activation class", drop("permissions", "activation"),
     ["permissions.activation: missing"]),
    ("no spending class", drop("permissions", "spending"), ["permissions.spending: missing"]),
    ("invented class", put({"needed": True, "granted": False, "record": None},
                           "permissions", "broker"),
     ["permissions.broker: unknown permission class"]),
    ("needed unstated", drop("permissions", "live", "needed"),
     ["permissions.live.needed: missing"]),
    ("needed as text", put("yes", "permissions", "live", "needed"),
     ["permissions.live.needed: not true or false"]),
    ("granted without record", put(True, "permissions", "live", "granted"),
     ["permissions.live: granted without a record"]),
    ("record dropped from grant", put(None, "permissions", "spending", "record"),
     ["permissions.spending: granted without a record"]),
    ("record key missing", drop("permissions", "spending", "record"),
     ["permissions.spending.record: missing"]),
    ("grant with chat text", put("Jake said yes", "permissions", "spending", "record"),
     ["permissions.spending.record: not a private-record comment pointer"]),
    ("grant with public pointer",
     put("https://github.com/openwizdev/openwiz/issues/4001#issuecomment-9002",
         "permissions", "spending", "record"),
     ["permissions.spending.record: not a private-record comment pointer"]),
    ("grant with issue link only",
     put("https://github.com/jparker2006/ClosedWiz/issues/4001",
         "permissions", "spending", "record"),
     ["permissions.spending.record: not a private-record comment pointer"]),
    ("grant with leading zero",
     put("https://github.com/jparker2006/ClosedWiz/issues/04001#issuecomment-9002",
         "permissions", "spending", "record"),
     ["permissions.spending.record: not a private-record comment pointer"]),
    ("record without grant", put(POINTER, "permissions", "live", "record"),
     ["permissions.live: record without a grant"]),
    ("granted as text", put("true", "permissions", "spending", "granted"),
     ["permissions.spending.granted: not true or false"]),
    # Stop/reconciliation, restoration and cleanup.
    ("no stop", drop("stop"), ["stop: missing"]),
    ("no stop conditions", drop("stop", "conditions"), ["stop.conditions: missing"]),
    ("empty stop conditions", put([], "stop", "conditions"), ["stop.conditions: empty"]),
    ("no reconciliation", drop("stop", "reconciliation"), ["stop.reconciliation: missing"]),
    ("empty reconciliation", put([], "stop", "reconciliation"),
     ["stop.reconciliation: empty"]),
    ("no restoration", drop("restoration"), ["restoration: missing"]),
    ("empty restoration", put([], "restoration"), ["restoration: empty"]),
    ("blank restoration step", put(["  "], "restoration"),
     ["restoration[0]: not a non-empty printable ASCII string"]),
    ("no cleanup", drop("cleanup"), ["cleanup: missing"]),
    ("empty cleanup", put([], "cleanup"), ["cleanup: empty"]),
    ("cleanup as text", put("archive everything", "cleanup"), ["cleanup: not a list"]),
    ("repeated cleanup step", lambda d: d["cleanup"].append(d["cleanup"][0]),
     ["cleanup[2]: duplicate"]),
    ("non-ASCII step", put(["archive   threads"], "cleanup"),
     ["cleanup[0]: not a non-empty printable ASCII string"]),
    # Evidence this validator cannot validate, and unknown shapes.
    ("fence evidence", put({"generation": 2}, "fencing"),
     ["fencing: evidence this validator cannot validate"]),
    ("access evidence", put(["read ok"], "access"),
     ["access: evidence this validator cannot validate"]),
    ("reviewer output", put("VERDICT: APPROVE", "reviewer_output"),
     ["reviewer_output: evidence this validator cannot validate"]),
    ("acknowledgements", put([], "acknowledgements"),
     ["acknowledgements: evidence this validator cannot validate"]),
    ("results", put({"P1": "pass"}, "results"),
     ["results: evidence this validator cannot validate"]),
    ("unknown top-level key", put(True, "approved"), ["approved: unknown key"]),
    ("unknown nested key", put("fenced", "permissions", "merge", "evidence"),
     ["permissions.merge.evidence: unknown key"]),
    ("no format", drop("format"), ["format: missing"]),
    ("other format", put("ops-live-kit-controls/2", "format"),
     ["format: not ops-live-kit-controls/1"]),
    # Several missing bounds are all reported, each once.
    ("several bounds missing",
     each(drop("limits", "duration_minutes"), drop("cleanup"), drop("permissions", "merge")),
     ["limits.duration_minutes: missing", "permissions.merge: missing", "cleanup: missing"]),
]


class KitControls(unittest.TestCase):
    def test_complete_synthetic_kit_passes(self):
        self.assertEqual(kit.check(base()), [])

    def test_each_missing_or_unpinned_control_is_refused_exactly(self):
        for case, mutate, expected in REFUSALS:
            with self.subTest(case=case):
                doc = copy.deepcopy(base())
                mutate(doc)
                self.assertEqual(kit.check(doc), expected)

    def test_non_object_kits_are_refused(self):
        for value in ([], "kit", 1, None):
            with self.subTest(value=value):
                self.assertEqual(kit.check(value), ["kit: not an object"])

    def test_reader_refuses_duplicate_keys_and_non_json_numbers(self):
        for text, reason in (
            ('{"format": "ops-live-kit-controls/1", "format": "x"}', 'duplicate key "format"'),
            ('{"limits": {"duration_minutes": NaN}}', "not JSON"),
            ('{"limits": {"duration_minutes": Infinity}}', "not JSON"),
            ("{", "not JSON"),
            ('{"limits": {"duration_minutes": ' + "1" * 5000 + "}}", "not JSON"),
        ):
            with self.subTest(text=text):
                with self.assertRaises(kit.Refused) as raised:
                    kit.read(text)
                self.assertEqual(str(raised.exception), reason)


class Command(unittest.TestCase):
    def run_kit(self, *args):
        return subprocess.run([sys.executable, "-I", str(HERE / "kit.py"), *args],
                              capture_output=True, text=True, timeout=30)

    def write(self, directory, text):
        path = Path(directory) / "candidate.json"
        path.write_text(text)
        return str(path)

    def test_complete_kit_exits_zero_and_names_what_is_still_needed(self):
        result = self.run_kit("check", str(FIXTURE))
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), [
            "pass: kit controls pinned (offline only; no live claim)",
            "needed, not granted: machine, live, write",
            "granted, record not read back: spending",
        ])

    def test_refused_kit_exits_one_with_every_refusal(self):
        doc = base()
        del doc["stop"]["reconciliation"]
        doc["permissions"]["live"]["granted"] = True
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_kit("check", self.write(directory, json.dumps(doc)))
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertEqual(result.stderr.splitlines(), [
            "refused: permissions.live: granted without a record",
            "refused: stop.reconciliation: missing",
        ])

    def test_unreadable_json_exits_one(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_kit("check", self.write(directory, '{"cleanup": [], "cleanup": []}'))
        self.assertEqual((result.returncode, result.stdout), (1, ""))
        self.assertEqual(result.stderr.splitlines(), ['refused: duplicate key "cleanup"'])

    def test_missing_file_and_bad_usage_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = self.run_kit("check", str(Path(directory) / "absent.json"))
        self.assertEqual((missing.returncode, missing.stdout), (2, ""))
        self.assertEqual(missing.stderr.splitlines(), ["error: cannot read the kit file"])
        for args in ((), ("check",), ("run", str(FIXTURE)), ("check", str(FIXTURE), "extra")):
            with self.subTest(args=args):
                usage = self.run_kit(*args)
                self.assertEqual((usage.returncode, usage.stdout), (2, ""))
                self.assertEqual(usage.stderr.splitlines(), ["usage: kit.py check <kit.json>"])


if __name__ == "__main__":
    unittest.main()
