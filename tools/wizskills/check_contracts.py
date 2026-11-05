#!/usr/bin/env python3
"""Check each carried contract in `.wizskills/` equals ClosedWiz's own, byte for byte.

Contract: contracts/wizskills.v1.md. The list is the contract's normative
`carried_contracts`, never a directory walk; a missing copy fails. Exit 0 when
every copy is identical, 1 naming each file that differs or is missing, 3 when
the contract cannot be read.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
DEST = '.wizskills'
CONTRACT = 'contracts/wizskills.v1.md'


def carried(root):
    text = (root / CONTRACT).read_text(encoding='utf-8')
    blocks = re.findall(r'^```wizskills-v1\n(.*?)^```', text, re.M | re.S)
    if len(blocks) != 1:
        raise ValueError
    names = json.loads(blocks[0])['carried_contracts']
    if not names or not all(isinstance(n, str) and n.startswith('contracts/') for n in names):
        raise ValueError
    return names


def read(path):
    """A regular file's bytes, or None when missing, a link or not a file."""
    if path.is_symlink() or not path.is_file():
        return None
    return path.read_bytes()


def problems(root):
    found = []
    for rel in carried(root):
        ours, theirs = read(root / rel), read(root / DEST / rel)
        if ours is None:
            found.append(f'wizskills: contract source missing: {rel}')
        elif theirs is None:
            found.append(f'wizskills: installed contract copy missing: {DEST}/{rel}')
        elif ours != theirs:
            found.append(f'wizskills: contract copy differs: {rel}')
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[2]),
                        help='the ClosedWiz checkout (default: this one)')
    args = parser.parse_args(argv)
    try:
        found = problems(Path(args.root).resolve())
    except (OSError, ValueError, KeyError, UnicodeError):
        print(f'wizskills: cannot read the carried list in {CONTRACT}', file=sys.stderr)
        return 3
    for line in found:
        print(line, file=sys.stderr)
    if found:
        return 1
    print('wizskills: carried contracts identical')
    return 0


if __name__ == '__main__':
    sys.exit(main())
