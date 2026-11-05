#!/usr/bin/env python3
"""Explicit local-file offline controls. No launch/admission/activation command."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('offline_analysis', HERE / 'analysis.py')
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)
E, C = A.E, A.C


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('init', 'check', 'assign', 'advance', 'analyze'):
        sub = commands.add_parser(name)
        sub.add_argument('--checkpoint', required=True, type=Path)
        if name in ('init', 'advance'):
            sub.add_argument('--bundle', required=True, type=Path)
            sub.add_argument('--journey', required=True, type=Path)
        if name in ('assign', 'advance', 'analyze'):
            sub.add_argument('--at', required=True)
        if name == 'assign':
            sub.add_argument('--ticket', required=True, type=int)
            sub.add_argument('--facts', required=True, type=Path)
    args = parser.parse_args()
    try:
        detail = None
        if args.command == 'init':
            bundle, journey = C.read(args.bundle), C.read(args.journey)
            E.save_checkpoint(args.checkpoint, bundle, journey)
        else:
            bundle, journey = E.load_checkpoint(args.checkpoint)
            expected = C.digest(dict(bundle=bundle, journey=journey))
            if args.command == 'assign':
                facts = C.read(args.facts)
                C.fields(facts, 'eligible safeguards', 'injected assignment facts')
                bundle = E.assign(bundle, journey, args.ticket, at=args.at, **facts)
            elif args.command == 'advance':
                after, next_journey = C.read(args.bundle), C.read(args.journey)
                bundle = E.advance(bundle, journey, after, next_journey, at=args.at)
                journey = next_journey
            elif args.command == 'analyze':
                bundle, detail = A.analyze(bundle, journey, at=args.at)
            if args.command != 'check':
                E.save_checkpoint(args.checkpoint, bundle, journey, expected=expected)
        print(json.dumps(dict(evidence_class='offline-only', result=bundle['result'], diagnostics=detail), allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'offline controls refused: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
