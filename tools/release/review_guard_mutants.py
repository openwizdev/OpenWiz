#!/usr/bin/env python3
import argparse
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True

DESCRIPTION = """Remove one release guard per disposable copy and require its outside-in proof to fail."""
MUTANTS = {
    "named-regression": ("scans.py",
        '            require(re.search(r"\\bfn\\s+"+re.escape(test)+r"\\s*\\(",check.texts[proof]),f"{name}: missing named regression")',
        '            pass', "test_named_regressions_cannot_be_missing_from_existing_proof_files",
        "test_public_regressions_run_and_refuse_planted_failures"),
    "browser-count": ("check.py",
        '                    require(re.search(rb"# tests 4\\b",out) and re.search(rb"# pass 4\\b",out),\n'
        '                            f"{name}: expected four passing browser regressions")',
        '                    pass', "test_browser_regression_requires_four_tests_and_four_passes",
        "test_public_regressions_run_and_refuse_planted_failures"),
    "unused-exception": ("scans.py",
        '    require(check.used_exceptions == set(range(len(exceptions))),"unused scan exception")',
        '    pass', "test_reviewed_url_exceptions_refuse_stale_duplicate_or_unused_entries",
        "test_reviewed_url_exceptions_refuse_stale_duplicate_or_unused_entries"),
    "duplicate-exception": ("scans.py",
        '        require(not any(exception == e for e in exceptions[:index]), "duplicate scan exception")',
        '        pass', "test_reviewed_url_exceptions_refuse_stale_duplicate_or_unused_entries",
        "test_reviewed_url_exceptions_refuse_stale_duplicate_or_unused_entries"),
    "allowlist-tree": ("check.py",
        '        require(set(committed) == paths,"allowlist does not equal export tree")',
        '        pass', "test_export_refuses_an_extra_committed_file", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
    "committed-mode": ("check.py",
        '            require(committed[item["path"]][0] == item["mode"],"committed export mode differs")',
        '            pass', "test_export_refuses_changed_committed_mode", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
    "changed-license": ("check.py",
        '            require(license_item and license_item["sha256"] == sha(blob(a.public_repo,plan["public_base"],"LICENSE")),\n'
        '                    "public license must be retained unmodified")',
        '            require(license_item, "public license must be retained unmodified")', "test_public_license_cannot_be_changed", "test_public_license_cannot_be_removed_or_changed"),
    "early-messaging": ("check.py",
        '            require("/messaging/" not in path and not path.endswith("/messaging.rs"),\n'
        '                    "later-version messaging code in a read-only release")',
        '            pass', "test_messaging_is_refused_before_version_0_0_3", "test_later_version_code_and_removed_public_license_are_refused"),
    "dirty-fresh-clone": ("check.py",
        '        require(not git(self.fresh,"status","--porcelain","--untracked-files=no"), "fresh clone changed tracked files")',
        '        pass', "test_fresh_clone_refuses_a_build_that_changes_tracked_files", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
    "existing-output": ("check.py",
        '            require(not p.exists() and not p.is_symlink(), "output directory already exists")',
        '            pass', "test_existing_outputs_are_refused_before_any_write", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
    "output-in-input": ("check.py",
        '            require(not p.is_relative_to(a.repo) and not p.is_relative_to(a.public_repo), "output overlaps input repository")',
        '            pass', "test_outputs_inside_input_repositories_are_refused_before_any_write", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
    "locked-build": ("check.py", '["build","--workspace","--release","--locked"]',
        '["build","--workspace","--release"]', "test_cargo_build_and_clippy_are_locked", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
    "locked-clippy": ("check.py", '["clippy","--workspace","--all-targets","--locked","--","-D","warnings"]',
        '["clippy","--workspace","--all-targets","--","-D","warnings"]', "test_cargo_build_and_clippy_are_locked", "test_clean_tree_report_hashes_and_no_publication_or_input_write"),
}
for index,name in enumerate((
        "a_send_at_the_reads_tested_version_is_not_live_tested_for_sending",
        "a_record_that_says_tested_never_replays_or_looks_up_as_tested",
        "every_read_runs_without_the_thread_context",
        "every_call_of_a_send_runs_without_the_thread_context"),1):
    MUTANTS[f"locked-regression-{index}"] = (
        "check.py", '["cargo","test","--locked","-p","openwiz-tests","--test",target,test]',
        f'["cargo","test"]+([] if test == {name!r} else ["--locked"])'
        '+["-p","openwiz-tests","--test",target,test]',
        "test_named_regression_cargo_calls_are_locked", "test_public_regressions_run_and_refuse_planted_failures")


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument("--baseline",action="store_true",help="Use the pre-ticket proof closest to each missing case")
    parser.add_argument("--only",choices=list(MUTANTS),nargs="+")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("release_proofs",args.root/"tools/release/test.py")
    proofs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proofs)
    failed = 0
    for name in args.only or MUTANTS:
        filename,anchor,replacement,test,baseline = MUTANTS[name]
        test = baseline if args.baseline else test
        if test not in proofs.ReleaseCheck.__dict__:
            print(f"{name}: INVALID (missing proof {test})",flush=True)
            failed += 1
            continue
        with tempfile.TemporaryDirectory(prefix="release-614-mutant-") as tmp:
            runner = Path(tmp)/"runner"
            shutil.copytree(args.root/"tools/release",runner,ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(args.root/"tools/privacy-check",Path(tmp)/"privacy-check",ignore=shutil.ignore_patterns("__pycache__"))
            source = runner/filename
            text = source.read_text()
            if text.count(anchor) != 1:
                print(f"{name}: INVALID (mutation anchor is not unique)",flush=True)
                failed += 1
                continue
            source.write_text(text.replace(anchor,replacement,1))
            with patch.object(proofs,"CLI",runner/"release"):
                result = unittest.TestResult()
                proofs.ReleaseCheck(test).run(result)
            killed = bool(result.failures) and not result.errors and all(
                "AssertionError:" in error for _,error in result.failures)
            print(f"{name}: {'KILLED' if killed else 'SURVIVED'} by {test} "
                  f"(failures={len(result.failures)}, errors={len(result.errors)})",flush=True)
            if not killed:
                failed += 1
                for _,error in result.errors:
                    print(error,flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
