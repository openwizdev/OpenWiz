#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
READER = ROOT / "tools/release/grant.py"
FIXTURES = ROOT / "contracts/fixtures/release-grant"
GRANTED = (0, "standing release grant recorded")
ABSENT = (1, "no standing release grant")
INVALID = (1, "malformed standing release grant row")
MINOR = (1, "every 0.x.0 stays the owner's ship call")
NO_POINTER = (1, "missing or invalid standing release grant decision or private-record pointer")


def check(action, fleet=None, *, launcher=None, cwd=None, reader=READER):
    command = [sys.executable, "-I"]
    command.extend([str(reader)] if launcher is None else ["-c", launcher, str(reader)])
    command.extend(["check", action])
    if fleet is not None:
        command.extend(["--fleet", str(fleet)])
    return subprocess.run(command, capture_output=True, text=True, cwd=cwd)


class GrantTest(unittest.TestCase):
    def assert_result(self, result, action, expected):
        status, reason = expected
        self.assertEqual(result.returncode, status, f"{action}: expected {reason}")
        if status == 0:
            self.assertEqual(result.stdout, f"{action}: {reason}\n")
            self.assertEqual(result.stderr, "")
        else:
            self.assertEqual(result.stderr, f"{action}: {reason}\n")
            self.assertEqual(result.stdout, "")

    def test_fixtures(self):
        for fixture, patch, pull in (
            ("no-grant", ABSENT, ABSENT),
            ("patch-and-pull", GRANTED, GRANTED),
            ("patch-only", GRANTED, ABSENT),
            ("minor", MINOR, MINOR),
            ("missing-pointer", NO_POINTER, NO_POINTER),
        ):
            for action, expected in (("patch", patch), ("pull", pull)):
                with self.subTest(fixture=fixture, action=action):
                    self.assert_result(check(action, FIXTURES / f"{fixture}.md"), action, expected)

    def test_default_fleet_is_relative_to_the_reader(self):
        with tempfile.TemporaryDirectory() as scratch:
            checkout = Path(scratch)
            reader = checkout / "tools/release/grant.py"
            fleet = checkout / "docs/agents/fleet.md"
            for path, source in ((reader, READER), (fleet, FIXTURES / "patch-only.md")):
                path.parent.mkdir(parents=True)
                shutil.copyfile(source, path)
            for action, expected in (("patch", GRANTED), ("pull", ABSENT)):
                with self.subTest(action=action):
                    self.assert_result(check(action, cwd=FIXTURES, reader=reader), action, expected)

    def test_failed_reads(self):
        with tempfile.TemporaryDirectory() as scratch:
            invalid = Path(scratch) / "invalid.md"
            invalid.write_bytes(b"\xff")
            missing = Path(scratch) / "missing.md"
            for path in (invalid, missing, Path(scratch)):
                with self.subTest(input=path.name):
                    self.assert_result(check("patch", path), "patch", (1, "cannot read fleet file"))

    def test_malformed_rows_close_the_gate(self):
        grant = (FIXTURES / "patch-and-pull.md").read_text(encoding="utf-8")
        row = next(line for line in grant.splitlines() if "ship a 0.x.y" in line)
        for broken in (row.replace("Jake", "Synthetic"), row.replace("every", "one"),
                       row[:-1], row + "\n" + row,
                       row + "\n" + row.replace("Standing", "**Standing").replace(" | Jake", "** | Jake"),
                       row.replace("0.x.y", "0.2.0").replace("patch", "release")):
            with self.subTest(row=broken):
                self.check_text(grant.replace(row, broken), INVALID)

    def test_decision_must_be_under_the_table_and_from_the_owner(self):
        grant = (FIXTURES / "patch-and-pull.md").read_text(encoding="utf-8")
        for broken in (grant.replace("Jake, 2035", "Synthetic, 2035"),
                       grant.replace("01-02:", "02-30:"),
                       grant.replace("#issuecomment-", "#discussion-"),
                       grant.replace("\nJake,", "\n## Other rules\n\nJake,")):
            with self.subTest(record=broken.splitlines()[-1]):
                self.check_text(broken, NO_POINTER)

    def test_unrelated_or_hidden_sections_do_not_grant(self):
        grant = (FIXTURES / "patch-and-pull.md").read_text(encoding="utf-8")
        for document in (grant.replace("Approval rules", "Other rules"),
                         f"```markdown\n{grant}```\n", f"<!--\n{grant}-->\n", f"<pre>\n{grant}</pre>\n"):
            with self.subTest(document=document.splitlines()[0]):
                self.check_text(document, ABSENT)

    def check_text(self, document, expected):
        with tempfile.TemporaryDirectory() as scratch:
            fleet = Path(scratch) / "fleet.md"
            fleet.write_text(document, encoding="utf-8")
            for action in ("patch", "pull"):
                self.assert_result(check(action, fleet), action, expected)

    def test_reader_does_not_write_or_use_the_network(self):
        launcher = """
import os
import runpy
import sys

sys.argv.pop(0)
sys.dont_write_bytecode = True
violations = []

def guard(event, args):
    write_open = event == "open" and args[2] & (
        os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    )
    os_mutation = event.startswith("os.") and event not in {"os.listdir", "os.scandir"}
    if write_open or os_mutation or event.startswith(("socket.", "subprocess.", "ctypes.")):
        violations.append(event)
        raise RuntimeError(f"unexpected I/O: {event}")

sys.addaudithook(guard)
try:
    runpy.run_path(sys.argv[0], run_name="__main__")
finally:
    if violations:
        raise RuntimeError(f"unexpected I/O: {violations}")
"""
        for fixture, expected in (("patch-and-pull", GRANTED), ("missing-pointer", NO_POINTER)):
            for action in ("patch", "pull"):
                with self.subTest(fixture=fixture, action=action):
                    self.assert_result(check(action, FIXTURES / f"{fixture}.md", launcher=launcher),
                                       action, expected)


if __name__ == "__main__":
    unittest.main()
