#!/usr/bin/env python3
import argparse
import os
from pathlib import Path
import re
import sys
import tempfile

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'collector'))
import collect_ci

DESCRIPTION = """MT6 (#825): the overload guard's supplier. One on-demand collector read, written as the guard's input."""


def write(path, data):
    fd, pending = tempfile.mkstemp(prefix='.observation-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='supply.py', description=DESCRIPTION)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository) or not args.output.is_absolute():
        parser.error('invalid repository or a relative output path')
    try:
        args.output.unlink(missing_ok=True)
    except OSError:
        print('supply: the previous observation could not be removed', file=sys.stderr)
        return 1
    try:
        fact = collect_ci.read(args.repository, ['queue'])['ci']['queue']
    except (collect_ci.Refused, ValueError):
        print('supply: the collector refused the queue read', file=sys.stderr)
        return 1
    if fact['value'] is None:
        print('supply: the collector\'s queue fact is unavailable', file=sys.stderr)
        return 1
    try:
        write(args.output, collect_ci.wire(fact['value']['observation']))
    except OSError:
        print('supply: the observation could not be written', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
