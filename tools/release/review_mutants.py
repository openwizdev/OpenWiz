#!/usr/bin/env python3
"""Prove the R3/R4/R7 corrections detect narrowly targeted breaks in temporary copies."""
import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
PASS = '            self.report["status"] = "pass"\n'
FILES = '        files = sorted(self.report["files"],key=lambda i:i["path"])\n'
MANIFEST = '        (a.evidence/"EXPORT-FILES.txt").write_text(hashes)\n'
LIVE = ('                    require("Live-observation:" in docs[evidence] and evidence.startswith("docs/evidence/"),\n'
        '                            "0.0.1-R1: live capability needs published live evidence")\n')
UNPUBLISHED = ('                    require(not re.search(r"not published|unpublished|LIVE-PENDING",item["text"]),\n'
               '                            "0.0.1-R1: live capability has unpublished evidence")\n')
MUTANTS = {
    "R4-report-omission": ("check.py",FILES,FILES.rstrip()+"[:-1]\n",
                           "test_clean_tree_report_hashes_and_no_publication_or_input_write", "report file coverage"),
    "R4-report-duplicate": ("check.py",FILES,FILES+'        files += files[:1]\n',
                            "test_clean_tree_report_hashes_and_no_publication_or_input_write", "report file coverage"),
    "R4-manifest-omission": ("check.py",MANIFEST,
                             '        (a.evidence/"EXPORT-FILES.txt").write_text("".join(hashes.splitlines(keepends=True)[:-1]))\n',
                             "test_clean_tree_report_hashes_and_no_publication_or_input_write", "export manifest"),
    "R4-manifest-duplicate": ("check.py",MANIFEST,
                              '        (a.evidence/"EXPORT-FILES.txt").write_text(hashes+hashes)\n',
                              "test_clean_tree_report_hashes_and_no_publication_or_input_write", "export manifest"),
    "R4-manifest-hash": ("check.py",MANIFEST,
                         '        (a.evidence/"EXPORT-FILES.txt").write_text("0"*64+hashes[64:])\n',
                         "test_clean_tree_report_hashes_and_no_publication_or_input_write", "export manifest"),
    "R3-home": ("check.py",PASS,
                '            (Path.home()/"release-mutant-wrote-here").write_text("Synthetic mutant\\n")\n'+PASS,
                "test_clean_tree_report_hashes_and_no_publication_or_input_write", "outside staging and evidence"),
    "R3-tmp": ("check.py",PASS,
               '            (Path(os.environ["TMPDIR"])/"release-mutant-wrote-here").write_text("Synthetic mutant\\n")\n'+PASS,
               "test_clean_tree_report_hashes_and_no_publication_or_input_write", "outside staging and evidence"),
    "R3-plan": ("check.py",PASS,
                '            with self.args.plan.open("a") as stream:\n                stream.write(" ")\n'+PASS,
                "test_clean_tree_report_hashes_and_no_publication_or_input_write", "outside staging and evidence"),
    "R7-unpublished": ("scans.py",UNPUBLISHED,'                    pass\n',
                       "test_unpublished_claim_guard_has_public_live_evidence", "0 != 1"),
    "R7-evidence": ("scans.py",LIVE,'                    pass\n',
                    "test_historical_wording_and_claim_plants", "0 != 1"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only",choices=list(MUTANTS),nargs="+")
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location("release_proofs",ROOT/"tools/release/test.py")
    proofs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proofs)
    failed = 0
    for name in args.only or MUTANTS:
        filename,anchor,replacement,test,reason = MUTANTS[name]
        with tempfile.TemporaryDirectory(prefix="release-review-mutant-") as tmp:
            scratch = Path(tmp)
            runner = scratch/"runner"
            shutil.copytree(ROOT/"tools/release",runner,ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT/"tools/privacy-check",scratch/"privacy-check",ignore=shutil.ignore_patterns("__pycache__"))
            source = runner/filename
            text = source.read_text()
            if text.count(anchor) != 1:
                print(f"{name}: INVALID (mutation anchor is not unique)")
                failed += 1
                continue
            source.write_text(text.replace(anchor,replacement,1))
            home = scratch/"home"
            temp = scratch/"tmp"
            home.mkdir()
            temp.mkdir()
            # The original test also runs safely: its unobserved HOME/TMPDIR
            # writes go into this disposable sandbox, never the actual home.
            with patch.dict(os.environ,{"HOME":str(home),"TMPDIR":str(temp)}), patch.object(proofs,"CLI",runner/"release"):
                result = unittest.TestResult()
                proofs.ReleaseCheck(test).run(result)
            killed = len(result.failures) == 1 and not result.errors and reason in result.failures[0][1]
            print(f"{name}: {'KILLED' if killed else 'NOT KILLED'} (failures={len(result.failures)}, errors={len(result.errors)})")
            if not killed:
                failed += 1
                for _,error in result.errors:
                    print(error)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
