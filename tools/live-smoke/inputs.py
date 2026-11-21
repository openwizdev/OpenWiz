#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
import runpy

DESCRIPTION = """Assemble the kit's owner-only inputs file on the PC, offline (#772).

Each --records file is an owner-only JSON object of named inputs that the Local
PC agent copied from the existing private records (never from Git). Records
merge; one name with two different values refuses. The result is one new
owner-only file outside any checkout, for prepare.py, which checks the names.
It prints only counts, never a value.
"""

HERE = Path(__file__).resolve().parent
prepare = runpy.run_path(str(HERE / 'prepare.py'))
Refused = prepare['Refused']


def assemble(records, out):
    out = prepare['private_output'](out)
    if out.exists() or out.is_symlink():
        raise Refused('exists')
    merged = {}
    for path in records:
        for name, value in prepare['read_private'](path, 'records_not_owner_only').items():
            if name in merged and merged[name] != value:
                raise Refused('conflicting_record')
            merged[name] = value
    with prepare['write_exclusive'](out, json.dumps(merged, indent=2, sort_keys=True) + '\n'):
        pass
    return {'assembled': True, 'names': len(merged), 'records': len(records)}


def main():
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument('--records', action='append', required=True, type=Path,
                        help='absolute owner-only records file (repeatable)')
    parser.add_argument('--out', required=True, type=Path, help='absolute new inputs file, outside any checkout')
    args = parser.parse_args()
    try:
        print(json.dumps(assemble(args.records, args.out)))
        return 0
    except Refused as error:
        print(json.dumps({'assembled': False, 'reason': error.doc['reason']}))
    except (OSError, ValueError, TypeError, prepare['smoke']['Refusal']):
        print(json.dumps({'assembled': False, 'reason': 'invalid_input'}))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
