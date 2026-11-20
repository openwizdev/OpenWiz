#!/usr/bin/env python3
"""P5 for #1264 (AP11): the approved table's rows checked against a tree.

  python3 -I docs/evidence/1264/check_rows.py [REV]   # default: HEAD

Every **delete** row's path is absent at REV; every **fold** row's path is
absent and its named new home is present; every **keep** row's path is still
there. Exit 0 when every row holds, else 1 with one line per broken row.
Reads the table at REV itself, so it checks the tree against the rows that
were approved, never a copy.
"""
import re
import subprocess
import sys

REV = sys.argv[1] if len(sys.argv) > 1 else 'HEAD'
TABLE = 'docs/cleanup/app-table.md'
# The fold rows' named homes ("same names" rows keep their file name).
HOMES = {
    'apps/web/test/fixtures/install-access/': 'tools/install/access/fixtures/',
    'apps/web/test/fixtures/install-connections/': 'tools/install/tests/fixtures/install-connections/',
    'crates/store/src/lib.rs': 'crates/cli/src/state/mod.rs',
    'crates/store/src/loops/': 'crates/cli/src/state/loops/',
    'crates/store/src/starts.rs': 'crates/cli/src/state/starts.rs',
    'crates/store/tests/state_dir.rs': 'crates/cli/tests/state_dir.rs',
    'tests/service/t2_locate.rs': 'tests/proof/t2_locate.rs',
    'tests/service/t7_transport.rs': 'crates/adapters/github/src/app_transport_tests.rs',
}


def tree(rev):
    out = subprocess.run(['git', 'ls-tree', '-r', '--name-only', rev], check=True,
                         capture_output=True, text=True).stdout
    return set(out.splitlines())


def home(path):
    for old, new in HOMES.items():
        if path == old:
            return new
        if old.endswith('/') and path.startswith(old):
            return new + path[len(old):]
    return None


def main():
    table = subprocess.run(['git', 'show', f'{REV}:{TABLE}'], check=True, capture_output=True,
                           text=True).stdout
    rows = re.findall(r'^\| `([^`]+)` \|.*\*\*(delete|fold|keep)\*\*', table, re.M)
    files = tree(REV)
    broken, counts = [], {'delete': 0, 'fold': 0, 'keep': 0}
    for path, kind in rows:
        counts[kind] += 1
        if kind == 'delete' and path in files:
            broken.append(f'delete row still present: {path}')
        elif kind == 'fold':
            new = home(path)
            if new is None:
                broken.append(f'fold row with no known home: {path}')
            elif path in files or new not in files:
                broken.append(f'fold row not at its home: {path} -> {new}')
        elif kind == 'keep' and path not in files:
            broken.append(f'keep row missing: {path}')
    print(f'rows: {counts["delete"]} delete, {counts["fold"]} fold, {counts["keep"]} keep')
    for line in broken:
        print(line)
    print('broken rows:', len(broken))
    return 1 if broken else 0


if __name__ == '__main__':
    sys.exit(main())
