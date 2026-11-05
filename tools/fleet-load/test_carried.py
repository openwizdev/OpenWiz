#!/usr/bin/env python3
"""WZ4 (#2634): launch-fleet's carried helpers stay byte-identical to their ClosedWiz sources.

python3 -I tools/fleet-load/test_carried.py

The skill carries copies (scripts/carried/, scripts/github-app/ and one fixture)
so it stands alone in WizSkills; ClosedWiz keeps the sources under tools/.
Any difference fails, naming the copy. Missing is failure.
"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
CARRIED = 'skills/launch-fleet/scripts/carried/'
# The exact list: copy -> source. A file appearing in carried/ but not here fails too.
PAIRS = {
    'alarm.py': 'tools/ci-overload/alarm.py',
    'healthy.json': 'tools/ci-overload/fixtures/healthy.json',
    'read.py': 'tools/github-reads/read.py',
    'limits.py': 'tools/factory-metrics/limits.py',
    'limits.conf': 'tools/factory-metrics/limits.conf',
    # read.py finds these through its own parents[1]: scripts/github-app/ beside carried/.
    '../github-app/app.py': 'tools/github-app/app.py',
    '../github-app/mint-token.py': 'tools/github-app/mint-token.py',
    '../github-app/manifest.json': 'tools/github-app/manifest.json',
    # A fixture copy: TL2's sanitized stage bench, read by three of the skill's proofs.
    '../../test/ops-inbox/stage-waits-bench.json': 'tools/factory-metrics/fixtures/stage-waits/bench.json',
}


def drift(root, pairs=PAIRS):
    """Each copy (repository-relative) that is missing, unreadable, different or unlisted."""
    found = []
    for copy, source in pairs.items():
        copy_path = (root / CARRIED / copy).resolve()
        name = str(copy_path.relative_to(root.resolve()))
        try:
            same = copy_path.read_bytes() == (root / source).read_bytes()
        except OSError:
            same = False
        if not same:
            found.append(name)
    listed = {(root / CARRIED / copy).resolve() for copy in pairs}
    # Every folder holding only carried copies: anything else in it is unlisted.
    folders = {path.parent for path in listed if path.parent.name in ('carried', 'github-app')}
    for folder in sorted(folders):
        for path in sorted(folder.iterdir()) if folder.is_dir() else ():
            if path.resolve() not in listed and path.name != '__pycache__':  # Python's own cache
                found.append(str(path.resolve().relative_to(root.resolve())))
    return found


class Carried(unittest.TestCase):
    def test_every_carried_copy_matches_its_source(self):
        self.assertEqual(drift(ROOT), [])

    def test_a_changed_missing_or_unlisted_copy_is_named(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            pairs = {'a.py': 'tools/a/a.py', 'b.conf': 'tools/b/b.conf', 'c.json': 'tools/c/c.json'}
            for copy, source in pairs.items():
                for path in (root / CARRIED / copy, root / source):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'synthetic\n')
            self.assertEqual(drift(root, pairs), [])
            (root / CARRIED / 'a.py').write_bytes(b'synthetic \n')
            (root / CARRIED / 'b.conf').unlink()
            (root / CARRIED / 'extra.py').write_bytes(b'synthetic\n')
            self.assertEqual(drift(root, pairs), [CARRIED + 'a.py', CARRIED + 'b.conf', CARRIED + 'extra.py'])


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    unittest.main()
