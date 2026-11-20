#!/usr/bin/env python3
"""#803: the contracts later groups rely on in measure.py, on synthetic input.

Run: python3 -I tools/test-value/test_measure.py
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("measure", HERE / "measure.py")
measure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(measure)

ROOT = "/work/repo"
PACKAGES = [
    ("openwiz-core", f"{ROOT}/crates/core"),
    ("openwiz-cli", f"{ROOT}/crates/cli"),
    ("openwiz-tests", f"{ROOT}/tests"),
]


def file_entry(path, covered, count):
    return {"filename": path, "summary": {"lines": {"count": count, "covered": covered}}}


def report(*files):
    return {"type": "llvm.coverage.json.export", "data": [{"files": list(files)}]}


class CoverageByCrate(unittest.TestCase):
    # catches: test code counted as covered product code, so moving a test
    # from tests/ into crates/<crate>/tests/ (TV4 onward) changes the number.
    def test_counts_only_product_sources_per_crate(self):
        got = measure.coverage_by_crate(report(
            file_entry(f"{ROOT}/crates/core/src/lib.rs", 30, 40),
            file_entry(f"{ROOT}/crates/core/src/send/mod.rs", 5, 20),
            file_entry(f"{ROOT}/crates/core/tests/moved.rs", 90, 90),
            file_entry(f"{ROOT}/crates/cli/src/lib.rs", 0, 12),
            file_entry(f"{ROOT}/crates/cli/examples/demo.rs", 7, 7),
            file_entry(f"{ROOT}/tests/fleet/main.rs", 50, 50),
            file_entry(f"{ROOT}/tests/fake-room-cli/main.rs", 60, 80),
            file_entry("/outside/cargo-registry/src/serde/lib.rs", 3, 9),
        ), PACKAGES)
        self.assertEqual(got, {"openwiz-core": [35, 60], "openwiz-cli": [0, 12]})


class TestCounts(unittest.TestCase):
    # catches: a target with several test binaries or result lines measured
    # by its first line only, or a red run saved as a baseline.
    def test_sums_every_result_line(self):
        out = (
            "running 3 tests\n"
            "test result: ok. 2 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out; finished in 0.10s\n"
            "running 4 tests\n"
            "test result: ok. 4 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 2.00s\n"
        )
        self.assertEqual(measure.parse_counts(out), {"passed": 6, "ignored": 1})

    def test_refuses_a_failed_or_missing_run(self):
        failed = "test result: FAILED. 3 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 1.00s\n"
        for out in (failed, "error: could not compile `openwiz-tests`\n"):
            with self.subTest(out=out), self.assertRaises(measure.MeasureError):
                measure.parse_counts(out)


def result(toolchain, coverage, tests=10):
    return {"schema": measure.SCHEMA, "toolchain": toolchain, "targets": ["openwiz-tests:fleet"],
            "tests": {"passed": tests, "ignored": 0}, "size": {"files": 2, "bytes": 100, "lines": 9},
            "coverage": coverage, "seconds": 1.0}


class Compare(unittest.TestCase):
    TOOLS = {"rustc": "rustc 1.99.1", "cargo-llvm-cov": "cargo-llvm-cov 0.9.1"}

    # catches: a before measured on another toolchain read as a coverage change.
    def test_refuses_different_toolchains(self):
        other = dict(self.TOOLS, rustc="rustc 1.98.0")
        with self.assertRaises(measure.MeasureError):
            measure.compare(result(self.TOOLS, {}), result(other, {}))

    # catches: a coverage drop in one crate hidden by a gain in another, or a
    # crate that disappears from the after report not reported as a drop.
    def test_names_every_crate_that_lost_covered_lines(self):
        lines = measure.compare(
            result(self.TOOLS, {"openwiz-core": [35, 60], "openwiz-adapter-github": [4, 12], "openwiz-cli": [8, 10]}),
            result(self.TOOLS, {"openwiz-core": [40, 60], "openwiz-adapter-github": [3, 12]}, tests=7))
        self.assertIn("drops: openwiz-adapter-github, openwiz-cli", lines)
        self.assertIn("tests: 10 -> 7 (-3)", lines)


def write(root, rel, text):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return str(path)


def depinfo(binary, *deps):
    return f"{binary}: " + " ".join(d.replace(" ", "\\ ") for d in deps) + "\n" + "".join(f"\n{d}:\n" for d in deps)


class Size(unittest.TestCase):
    ENTRY = "mod cases;\n"            # 11 bytes, 1 line
    CASES = "#[test] fn kept() {}\n"  # 21 bytes, 1 line

    # catches: a group that moves its retained tests into a crate's named
    # target (crates/<crate>/tests/<name>.rs plus its modules) reported as
    # smaller, because only the entrypoint of a non-main.rs target counted.
    def test_a_moved_target_keeps_its_size(self):
        with tempfile.TemporaryDirectory() as root:
            before = depinfo(f"{root}/target/debug/deps/fleet-1",
                             write(root, "tests/fleet/main.rs", self.ENTRY),
                             write(root, "tests/fleet/cases.rs", self.CASES))
            write(root, "tests/fleet/README.md", "notes, not a source\n")
            after = depinfo(f"{root}/target/debug/deps/fleet_detail-2",
                            write(root, "crates/cli/tests/fleet_detail.rs", self.ENTRY),
                            write(root, "crates/cli/tests/fleet_detail/cases.rs", self.CASES))
            want = {"files": 2, "bytes": 32, "lines": 2}
            self.assertEqual(measure.size(measure.sources([before], root)), want)
            self.assertEqual(measure.size(measure.sources([after], root)), want)

    # catches: a support module two targets of one group share counted twice,
    # and generated, dependency or non-Rust inputs counted as the group's.
    def test_a_group_counts_each_own_rust_source_once(self):
        with tempfile.TemporaryDirectory() as root:
            # rustc names this tree's files relative to the workspace root,
            # with the `..` of a #[path] module left in (as tests/ does).
            write(root, "tests/support/mod.rs", "pub fn x() {}\n")
            shared, shared_too = "tests/a b/../support/mod.rs", "tests/c/../support/mod.rs"
            spaced = str(Path(write(root, "tests/a b/main.rs", "mod support;\n")).relative_to(root))
            other = write(root, "tests/c/main.rs", "mod support;\n")
            fixture = write(root, "tests/fixtures/case.json", "{}\n")
            built = write(root, "target/debug/build/out/gen.rs", "\n")
            outside = "/elsewhere/registry/serde/src/lib.rs"
            got = measure.sources([depinfo(f"{root}/target/debug/deps/a-1", spaced, shared, fixture, built, outside),
                                   depinfo(f"{root}/target/debug/deps/c-2", other, shared_too)], root)
            self.assertEqual([str(Path(p).relative_to(root)) for p in got],
                             ["tests/a b/main.rs", "tests/c/main.rs", "tests/support/mod.rs"])

    def test_refuses_a_dep_info_without_sources(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(measure.MeasureError):
            measure.sources([depinfo(f"{root}/target/debug/deps/a-1")], root)


class Profiles(unittest.TestCase):
    # catches: raw profiles of instrumented children that a test starts with
    # a cleared environment (so they land in its working folder) deleted
    # instead of merged, which drops their real coverage (service startup);
    # or a profile that was there before the run taken or removed.
    def test_moves_only_new_profiles_into_the_report_folder(self):
        with tempfile.TemporaryDirectory() as root:
            subprocess.run(["git", "init", "-q", root], check=True)
            old = write(root, "old.profraw", "before the run")
            before = measure.stray_profiles(Path(root))
            write(root, "tests/default_1_42.profraw", "child profile")
            dest = Path(root) / "target/test-value-cov"
            dest.mkdir(parents=True)
            self.assertEqual(measure.collect_profiles(Path(root), before, dest), 1)
            self.assertEqual([p.name for p in dest.iterdir()], ["default_1_42.profraw"])
            self.assertEqual((dest / "default_1_42.profraw").read_text(), "child profile")
            self.assertFalse((Path(root) / "tests/default_1_42.profraw").exists())
            self.assertEqual(Path(old).read_text(), "before the run")


if __name__ == "__main__":
    unittest.main()
