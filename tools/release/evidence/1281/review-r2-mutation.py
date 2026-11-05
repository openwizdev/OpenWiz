"""Focused byte/history guard deletions must fail their owning fixture proofs."""
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'tools/release'))
import test as proofs

import test_review

mutants = [
    ("R2 byte binding", proofs.ReleaseCheck, 'test_git_attributes_cannot_change_reported_export_bytes',
     '            require(sha(blob(self.export,checked_tree,item["path"])) == item["sha256"],"committed export hash differs")',
     '            pass', "committed export hash differs' not found"),
    ("R3 history", test_review.ReviewEntries, 'test_r3_generated_entry_commit_identity_is_checked',
     '"--git-tree",head,"--head",head', '"--git-tree",head', '0 != 1')]
failed = 0
for name,case,test,guard,replacement,expected in mutants:
    with tempfile.TemporaryDirectory(prefix='release-review-mutant-') as temp:
        runner = Path(temp)/'release'
        shutil.copytree(ROOT/'tools/release',runner,ignore=shutil.ignore_patterns('__pycache__','evidence'))
        source = runner/'check.py'
        text = source.read_text()
        assert text.count(guard) == 1
        source.write_text(text.replace(guard,replacement))
        with patch.object(proofs,'CLI',runner/'release'):
            result = unittest.TestResult()
            case(test).run(result)
        for _,trace in result.failures + result.errors:
            print(trace)
        killed = len(result.failures) == 1 and not result.errors and expected in result.failures[0][1]
        print(name + ' mutant: ' + ('KILLED' if killed else 'SURVIVED'))
        failed += not killed
sys.exit(bool(failed))
