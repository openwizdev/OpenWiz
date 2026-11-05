#!/usr/bin/env python3
"""The Rust tests split across runners (#1266, X8 of spec #1256).

The Rust lane's selected tests (the CI selection record's `rust:lib:` and
`rust:test:` ids, contracts/ci-selection.v1.md) are built once and then run
by N shards. This decides each shard's share and checks afterwards that
every selected test ran exactly once.

    python3 -I ci/shard/shard.py plan PLAN --shards N --times TSV
    python3 -I ci/shard/shard.py share PLAN --shards N --shard K --times TSV
    python3 -I ci/shard/shard.py check PLAN [RAN...]
    python3 -I ci/shard/shard.py times LOG...

`plan` reads the plan (refused unless the contract accepts it, by the
escape finder's reader, the one X5's writer uses) and prints the split as
JSON: `{"seconds", "unmeasured", "shards": [{"shard", "tests", "seconds"}]}`:
at most N shards (ci.yml's matrix size for the runner kind, a setting per
runner kind there) and the number of tests, and of those the fewest that
finish as soon as the most would. `share` prints shard K's tests, one a
line: nothing for a member past the shards needed, or a skipped lane.
Longest first, each test goes to the least loaded shard (ties: the lower shard, then the
id), by its time in TSV; a test with no time counts as the longest measured
one, and is named in `unmeasured`. A skipped Rust lane has no shards.

`check` reads the plan and each shard's record of what it ran (one id a
line) and passes only if every selected Rust test ran exactly once and
nothing else ran. Missing, doubled or unselected ids fail, each named.

`times` reads CI's Rust logs (the rust job's, traced `== trace: <id>` or
`== rust-tests: <target>` sections, and the `crates` section by package:
each library's line starts its package) and prints each test's time as TSV:
the sum of its libtest `finished in` totals in one log, the median over the
logs. A log that times no Rust test, or a test twice, is refused.

Exit 0: done. 1: a plan, record, times file or log refused (on stderr;
nothing on stdout). 2: a bad command line. Python 3 standard library only;
it reads only the files it is given.
"""
import argparse
import json
from collections import Counter
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parent.parent.parent
sys.dont_write_bytecode = True  # read-only: no __pycache__ beside escapes.py
sys.path.insert(0, str(ROOT / 'ci' / 'escapes'))
import escapes  # noqa: E402  the contract's reader (rules 1-9 and the schema)

RUST_ID = re.compile(r'rust:(?:lib|test):[A-Za-z0-9._:-]+')
SECONDS = re.compile(r'\d+(?:\.\d+)?')
STAMP = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z ')
HEADER = re.compile(r'(?:rust-tests-frame:[0-9a-f]{64} )?== (?:trace|rust-tests): (.*)')
TARGET = re.compile(r'[a-z0-9-]+')
RESULT = re.compile(r'test result: .*\bfinished in (\d+(?:\.\d+)?)s')
# In the `crates` section, a package's library starts its tests; its doc
# tests come at the end, by the library's name.
LIBRARY = re.compile(r'\s*Running unittests src/lib\.rs \(target/debug/deps/([a-z0-9_]+)-[0-9a-f]+\)')
DOCTESTS = re.compile(r'\s*Doc-tests ([a-z0-9_]+)')


class Refused(Exception):
    pass


def read(path):
    try:
        return Path(path).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as e:
        raise Refused(f'{path}: {e}') from e


def rust_tests(path):
    """The plan's selected Rust tests, once the contract accepts it."""
    text = read(path)
    errors = escapes.refusals(text)
    if errors:
        raise Refused(f'{path}: ' + '; '.join(errors))
    lane = escapes.strict_json(text)['lanes']['rust']
    return lane['tests'] if lane['decision'] == 'run' else []


def times(path):
    """Each Rust test's time in centiseconds, from a TSV of `id<TAB>seconds`."""
    out, text = {}, read(path)
    if text and not text.endswith('\n'):
        raise Refused(f'{path}: its last line does not end in a newline')
    for n, line in enumerate(text.split('\n')[:-1], 1):
        if line.startswith('#'):
            continue
        fields = line.split('\t')
        if len(fields) != 2 or not RUST_ID.fullmatch(fields[0]) or not SECONDS.fullmatch(fields[1]):
            raise Refused(f'{path}: line {n} is not "<rust id>\\t<seconds>": {line!r}')
        if fields[0] in out:
            raise Refused(f'{path}: {fields[0]} is timed twice')
        out[fields[0]] = round(float(fields[1]) * 100)
    if not out:
        raise Refused(f'{path}: times nothing')
    return out


def lpt(items, n):
    """Longest first, each to the least loaded of n shards."""
    shards, loads = [[] for _ in range(n)], [0] * n
    for cs, test in items:
        k = min(range(n), key=lambda j: (loads[j], j))
        shards[k].append(test)
        loads[k] += cs
    return shards, loads


def split(tests, timed, most):
    longest = max(timed.values())
    unmeasured = sorted(t for t in tests if t not in timed)
    items = sorted(((timed.get(t, longest), t) for t in tests), key=lambda x: (-x[0], x[1]))
    k = min(most, len(tests))
    tries = [lpt(items, n) for n in range(1, k + 1)]
    best = min((max(loads) for _, loads in tries), default=0)
    shards, loads = next(((s, l) for s, l in tries if max(l) == best), ([], []))
    return {
        'seconds': best / 100,
        'unmeasured': unmeasured,
        'shards': [{'shard': i, 'tests': s, 'seconds': l / 100} for i, (s, l) in enumerate(zip(shards, loads), 1)],
    }


def check(tests, records):
    """Each problem with what the shards ran: empty when each test ran once."""
    ran = Counter()
    for path in records:
        text = read(path)
        lines = text.split('\n')
        if lines[-1] != '' or any(not RUST_ID.fullmatch(t) for t in lines[:-1]):
            raise Refused(f'{path}: not one Rust test id a line')
        ran.update(lines[:-1])
    out = [f'{t}: never ran' for t in tests if ran[t] == 0]
    out += [f'{t}: ran {ran[t]} times' for t in tests if ran[t] > 1]
    out += [f'{t}: ran, but the plan did not select it' for t in sorted(set(ran) - set(tests))]
    return out


def log_times(path):
    """One log's time for each Rust test it ran, in seconds."""
    out, current, seen, crates = {}, None, set(), False
    for line in read(path).splitlines():
        line = STAMP.sub('', line, count=1).rstrip()
        head = HEADER.fullmatch(line)
        if head:
            name = head.group(1)
            crates = name == 'crates'
            current = name if RUST_ID.fullmatch(name) else \
                f'rust:test:{name}' if TARGET.fullmatch(name) and not crates else None
            if current in seen:
                raise Refused(f'{path}: {current} is in it twice')
            if current:
                seen.add(current)
            continue
        lib = crates and (LIBRARY.fullmatch(line) or DOCTESTS.fullmatch(line))
        if lib:
            current = 'rust:lib:' + lib.group(1).replace('_', '-')
            continue
        result = RESULT.match(line)
        if result and current:
            out[current] = out.get(current, 0.0) + float(result.group(1))
    if not out:
        raise Refused(f'{path}: times no Rust test')
    return out


def median_times(logs):
    each = {}
    for path in logs:
        for test, s in log_times(path).items():
            each.setdefault(test, []).append(s)
    return ''.join(f'{t}\t{statistics.median(each[t]):.2f}\n' for t in sorted(each))


def count(text):
    if not text.isdigit() or not 1 <= int(text) <= 64:
        raise argparse.ArgumentTypeError(f'not a whole number from 1 to 64: {text!r}')
    return int(text)


def main(argv):
    p = argparse.ArgumentParser(prog='ci/shard/shard.py')
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('plan')
    a.add_argument('plan')
    a.add_argument('--shards', required=True, type=count)
    a.add_argument('--times', required=True)
    b = sub.add_parser('share')
    b.add_argument('plan')
    b.add_argument('--shards', required=True, type=count)
    b.add_argument('--shard', required=True, type=count)
    b.add_argument('--times', required=True)
    c = sub.add_parser('check')
    c.add_argument('plan')
    c.add_argument('ran', nargs='*')
    t = sub.add_parser('times')
    t.add_argument('logs', nargs='+')
    args = p.parse_args(argv)
    try:
        if args.command in ('plan', 'share'):
            if args.command == 'share' and args.shard > args.shards:
                p.error(f'--shard {args.shard} is past --shards {args.shards}')
            out = split(rust_tests(args.plan), times(args.times), args.shards)
            if args.command == 'plan':
                print(json.dumps(out, indent=1))
            elif args.shard <= len(out['shards']):
                sys.stdout.write(''.join(t + '\n' for t in out['shards'][args.shard - 1]['tests']))
        elif args.command == 'check':
            tests = rust_tests(args.plan)
            problems = check(tests, args.ran)
            if problems:
                print('\n'.join(f'shard check: {x}' for x in problems), file=sys.stderr)
                return 1
            print(f'shard check: every one of the {len(tests)} selected Rust tests ran exactly once,'
                  f' across {len(args.ran)} shards')
        else:
            sys.stdout.write(median_times(args.logs))
    except Refused as e:
        print(f'shard: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
