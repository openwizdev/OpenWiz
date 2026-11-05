#!/usr/bin/env python3
"""Pick the tests a change can reach, failing closed (#432, K15).

  python3 -I ci/select/pick.py --map MAP.json [--root DIR] [--head REV]
                               [--units-file FILE] [--no-classify]

Prints one JSON object: `mode` (`selected`, or `full` when everything runs),
`reasons` (for a full run, each in the CI selection record's form,
contracts/ci-selection.v1.md: `ci_change` and `unknown_path` with their
`paths`, `empty_diff`, `failed_diff` and `selector_error` with a `detail`),
`tests` (each test id that runs), `skipped` (each other test, with its
reason) and `why` (for each test that runs, the first thing that selected
it). It always prints an answer: any error is a full run.

The map (map.py) says, for each test, the repository files it was seen to
read or look for (`files`) and the folders it listed (`dirs`), at one
commit (`commit`). The change is every path that differs between that
commit's tree and the tested one (`git diff --no-renames <commit> <head>`),
so a map that has fallen behind only makes more tests run. The rules:

1. No usable map, no tests, a classifier or read that fails: everything.
2. No changed path: everything.
3. A path with a control character, `..` or a leading `/`: everything.
4. A change to CI or the toolchain (CI_CHANGE): everything.
5. A path no CI job reads (classify.sh: STATUS.md, private/, ...): nothing.
6. A modified path: the tests that read it. None read it: nothing (the
   full traced run had it and never opened it).
7. A deleted path: the tests that read it or listed a folder above it. If
   none did, and a file some test reads names it: everything.
8. A new path (or one of any other status): if a file some test reads names
   it, everything; else the tests that looked for it or listed a folder
   above it; if none did, the map doesn't know it: everything.
9. A test the map doesn't know (a new one): always runs. So does ALWAYS.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import units as units_mod  # noqa: E402

MAP_SCHEMA = 'openwiz.ci-select-map.v1'
# The always-run set: the cheap architecture and privacy checks, which read
# nearly every folder (measured: about 7 s in CI).
ALWAYS = ['rust:test:checks']
# CI and the toolchain (the contract's `ci_change`): the workflows and the
# docs-only classifier, the selector and its map, the runner kit and CI's
# scripts, the workspace manifest and every lockfile, and toolchain pins.
# Never under private/, which no job reads (classify.sh).
CI_CHANGE = re.compile(r'(?!private/)(?:\.github/.+|ci/(select|runner)/.+|ci/[^/]+|Cargo\.toml|Cargo\.lock|(.+/)?package-lock\.json'
                       r'|rust-toolchain(\.toml)?|\.nvmrc|\.node-version|\.tool-versions)')
TEST_ID = re.compile(r'(rust:lib|rust:test|web:unit|web:browser):[A-Za-z0-9._-]+')
COMMIT = re.compile(r'[0-9a-f]{40}')
SKIPPED = 'no changed path reaches it'


class MapError(Exception):
    pass


def odd_path(path):
    """A path the selector refuses to reason about."""
    parts = path.split('/')
    return (not path or path.startswith('/') or any(p in ('', '.', '..') for p in parts)
            or any(ord(c) < 32 or ord(c) == 127 for c in path))


def check_map(mp):
    """The map's units, or MapError: exactly its keys, each of its type."""
    if not isinstance(mp, dict):
        raise MapError('the map is not an object')
    if set(mp) != {'schema', 'commit', 'units'}:
        raise MapError(f'the map has keys {sorted(mp)}, not schema, commit and units')
    if mp['schema'] != MAP_SCHEMA:
        raise MapError(f'the map is {mp["schema"]!r}, not {MAP_SCHEMA}')
    if not isinstance(mp['commit'], str) or not COMMIT.fullmatch(mp['commit']):
        raise MapError('the map\'s commit is not a full commit id')
    units = mp['units']
    if not isinstance(units, dict) or not units:
        raise MapError('the map has no tests')
    for uid, u in units.items():
        if not TEST_ID.fullmatch(uid):
            raise MapError(f'the map has an odd test id {uid!r}')
        if not isinstance(u, dict) or not {'files', 'dirs'} <= set(u) <= {'files', 'dirs', 'seconds', 'web_export'}:
            raise MapError(f'{uid}: not files, dirs and optional seconds/web_export')
        if 'web_export' in u and type(u['web_export']) is not bool:
            raise MapError(f'{uid}: web_export is not a boolean')
        if 'seconds' in u and (isinstance(u['seconds'], bool) or not isinstance(u['seconds'], (int, float))
                               or u['seconds'] < 0):
            raise MapError(f'{uid}: seconds is not a time')
        for key in ('files', 'dirs'):
            if not isinstance(u[key], list) or not all(isinstance(p, str) for p in u[key]):
                raise MapError(f'{uid}: {key} is not a list of paths')
            for p in u[key]:
                if odd_path(p) and not (key == 'dirs' and p == '.'):
                    raise MapError(f'{uid}: an odd path {p!r}')
        if not u['files']:
            raise MapError(f'{uid}: reads no file')
    return units


_INDEXED = []


def index_map(mp):
    """check_map's units, and the tests that read each file and list each
    folder, as frozen sets. The last map's index is kept for as long as that
    very object is the one asked about (the every-link check asks thousands
    of times); a map is never changed after it is read."""
    if _INDEXED and _INDEXED[0] is mp:
        return _INDEXED[1]
    known = check_map(mp)
    owners, listers = {}, {}
    for uid, u in known.items():
        for f in u['files']:
            owners.setdefault(f, set()).add(uid)
        for d in u['dirs']:
            listers.setdefault(d, set()).add(uid)
    answer = (known, {k: frozenset(v) for k, v in owners.items()}, {k: frozenset(v) for k, v in listers.items()})
    _INDEXED[:] = [mp, answer]
    return answer


def select(changes, mp, units, read, nobody):
    """changes: [(status, path)], git's A, M or D (anything else counts as
    new). units: the test ids at the head. read(path): the file's bytes at
    the head, or None if it isn't there. nobody(paths): those no CI job
    reads."""
    units = sorted(set(units))

    def answer(mode, reasons, tests, why):
        tests = sorted(tests)
        return {'mode': mode, 'reasons': reasons, 'tests': tests,
                'skipped': [{'test': u, 'reason': SKIPPED} for u in units if u not in tests],
                'why': {u: why[u] for u in tests}}

    def full(code, **extra):
        reason = {'code': code, **extra}
        return answer('full', [reason], units, {u: f'everything runs: {code}' for u in units})

    if not units:
        return full('selector_error', detail='no tests listed')
    try:
        known, owners, listers = index_map(mp)
    except MapError as e:
        return full('selector_error', detail=str(e))
    if not changes:
        return full('empty_diff')

    def above(path):
        hit = set(listers.get('.', ()))
        d = os.path.dirname(path)
        while d:
            hit |= listers.get(d, set())
            d = os.path.dirname(d)
        return hit

    texts = None

    def named(path):
        """Whether a file some test reads names this path's file."""
        nonlocal texts
        if texts is None:
            texts = [t for t in (read(f) for f in sorted(owners)) if t is not None]
        base = os.path.basename(path).encode()
        return any(base in t for t in texts)

    try:
        quiet = set(nobody([p for _, p in changes if not odd_path(p)]))
    except Exception as e:  # the classifier failed: never "nobody reads it"
        return full('selector_error', detail=f'classify.sh failed: {e}')
    picked, why = set(), {}
    unknown, ci = [], []

    def reach(found, how, path):
        for u in sorted(found):
            why.setdefault(u, f'{how} {path}')

    try:
        for status, path in changes:
            if odd_path(path):
                unknown.append(path)
                continue
            if CI_CHANGE.fullmatch(path):
                ci.append(path)
                continue
            if path in quiet:
                continue
            if status == 'M':
                picked |= owners.get(path, set())
                reach(owners.get(path, ()), 'reads', path)
                continue
            readers, walkers = owners.get(path, set()), above(path)
            if status == 'D':
                if readers or walkers:
                    picked |= readers | walkers
                    reach(readers, 'reads', path)
                    reach(walkers, 'lists a folder above', path)
                elif named(path):
                    unknown.append(path)
                continue
            if named(path):
                unknown.append(path)
            elif readers or walkers:
                picked |= readers | walkers
                reach(readers, 'looked for', path)
                reach(walkers, 'lists a folder above', path)
            else:
                unknown.append(path)
    except Exception as e:  # a read that failed: never "nothing names it"
        return full('selector_error', detail=f'reading the head failed: {e}')
    if ci or unknown:
        reasons = []
        if ci:
            reasons.append({'code': 'ci_change', 'paths': sorted(set(ci))})
        if unknown:
            reasons.append({'code': 'unknown_path', 'paths': sorted(set(unknown))})
        return answer('full', reasons, units, {u: 'everything runs: ' + ', '.join(r['code'] for r in reasons)
                                               for u in units})
    picked |= {u for u in units if u not in known}
    for u in units:
        if u not in known:
            why.setdefault(u, 'not in the map yet')
    for u in ALWAYS:
        if u in units:
            picked.add(u)
            why.setdefault(u, 'always runs')
    return answer('selected', [], picked & set(units), why)


def lanes(result):
    """What each CI job runs: `all`, `none`, or its test ids, space-separated.
    Anything but a well-formed selected answer is `all`."""
    every = {'rust': 'all', 'web': 'all'}
    if not isinstance(result, dict) or result.get('mode') != 'selected':
        return every
    tests = result.get('tests')
    if not isinstance(tests, list) or not all(isinstance(t, str) and TEST_ID.fullmatch(t) for t in tests):
        return every
    out = {}
    for lane in ('rust', 'web'):
        mine = sorted(t for t in tests if t.startswith(lane + ':'))
        out[lane] = ' '.join(mine) if mine else 'none'
    return out


def strict_json(text):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise MapError(f'the key {k!r} is there twice')
            out[k] = v
        return out
    return json.loads(text, object_pairs_hook=pairs)


def diff(root, commit, head):
    """[(status, path)] between the two trees, or raises (a failed diff)."""
    out = subprocess.run(['git', '-C', root, 'diff', '--no-renames', '--no-ext-diff', '-z', '--name-status',
                          commit, head, '--'], capture_output=True)
    if out.returncode:
        raise RuntimeError(out.stderr.decode(errors='replace').strip() or f'git diff exited {out.returncode}')
    fields = out.stdout.split(b'\0')
    if fields and fields[-1] == b'':
        fields.pop()
    if len(fields) % 2:
        raise RuntimeError('git diff gave an odd answer')
    return [(fields[i].decode(), fields[i + 1].decode('utf-8', errors='surrogateescape'))
            for i in range(0, len(fields), 2)]


def classify_nobody(root):
    """nobody(paths) through classify.sh: the paths every job skips."""
    script = os.path.join(root, '.github/actions/docs-only/classify.sh')

    def nobody(paths):
        if not paths:
            return set()
        common = None
        for job in ('web-build', 'rust', 'web-test'):
            out = subprocess.run(['sh', script, '--skips', job], input='\n'.join(paths) + '\n',
                                 capture_output=True, text=True, check=True).stdout
            skips = set(out.splitlines())
            common = skips if common is None else common & skips
        return common
    return nobody


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--map', required=True)
    ap.add_argument('--root', default='.')
    ap.add_argument('--head', default='HEAD')
    ap.add_argument('--units-file')
    ap.add_argument('--no-classify', action='store_true', help='tests only: treat every path as one a job reads')
    ap.add_argument('--github-output', help='also append selection=, rust-tests= and web-tests= to this file')
    args = ap.parse_args(argv)
    root = os.path.abspath(args.root)
    try:
        if args.units_file:
            with open(args.units_file) as f:
                units = [line for line in f.read().splitlines() if line]
        else:
            units = sorted(units_mod.list_units(root))
    except Exception as e:
        return {'mode': 'full', 'reasons': [{'code': 'selector_error', 'detail': f'listing the tests failed: {e}'}],
                'tests': [], 'skipped': [], 'why': {}}
    try:
        with open(args.map) as f:
            mp = strict_json(f.read())
    except Exception as e:
        return select([], None, units, None, None) | {
            'reasons': [{'code': 'selector_error', 'detail': f'the map can\'t be read: {e}'}]}
    try:
        changes = diff(root, mp['commit'], args.head) if isinstance(mp, dict) and isinstance(
            mp.get('commit'), str) and COMMIT.fullmatch(mp['commit']) else None
    except Exception as e:
        result = select([], mp, units, None, None)
        if result['reasons'][0]['code'] == 'empty_diff':
            result['reasons'] = [{'code': 'failed_diff', 'detail': str(e)}]
            result['why'] = {u: 'everything runs: failed_diff' for u in result['tests']}
        return result

    def read(path):
        try:
            with open(os.path.join(root, path), 'rb') as f:
                return f.read()
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None
    nobody = (lambda paths: set()) if args.no_classify else classify_nobody(root)
    return select(changes or [], mp, units, read, nobody)


if __name__ == '__main__':
    try:
        result = main(sys.argv[1:])
    except SystemExit:
        raise
    except Exception as e:  # never no answer: a crash runs everything
        result = {'mode': 'full', 'reasons': [{'code': 'selector_error', 'detail': f'the selector crashed: {e}'}],
                  'tests': [], 'skipped': [], 'why': {}}
    print(json.dumps(result, indent=1, sort_keys=True))
    out = next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == '--github-output'), None)
    if out:
        lane = lanes(result)
        mode = 'selected' if result.get('mode') == 'selected' and 'all' not in lane.values() else 'full'
        with open(out, 'a') as f:
            f.write(f'selection={mode}\nrust-tests={lane["rust"]}\nweb-tests={lane["web"]}\n')
