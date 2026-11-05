#!/usr/bin/env python3
"""Planted edits on real files (#432, K15, acceptance): every test the
selector skips for an edit is run anyway, with the edit in place, and must
pass. Runs in CI (it runs a lane's every test once per edit), on the run of
a pull request that changes this file.

  python3 -I ci/select/planted.py rust|web OUT.jsonl [--jobs N]

For each CASE (a real file, a behaviour-changing edit): the selector picks
the tests for that one modified path from the committed map
(ci/select/map.json); then, with the edit in place, every test of the lane
runs, picked or not. A skipped test that fails is a reader the map hid: the
case fails, and so does this command (exit 1). A picked test that fails is
the edit caught. An edit no test of either lane catches proves nothing
(`void`); the two lanes' lines together say which.

An edit to the web export's inputs (apps/web, not its tests) is built into
apps/web/out the way the job's out/ came: in a copy of apps/web beside it,
whose out/ replaces out/'s contents for that case, and the original
contents are put back after. Each file is put back after its case, whatever
happens.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import pick  # noqa: E402
import trace  # noqa: E402

# (path, old, new, catchers): `old` is in the file exactly once; `catchers`
# names the lanes whose picked tests must catch the edit (at least one), as
# run 42330800061 recorded (private/evidence/infra-ci-scale/k15/README.md).
# A named lane that catches nothing fails: an edit no test sees proves no skip.
CASES = [
    ('tests/fixtures/envelopes/ls-long-complete.json', '"schema": "openwiz.inventory.v1",',
     '"schema": "openwiz.inventory.v9",', ('rust', 'web')),
    ('crates/adapters/github/src/fleets.rs', 'fn allows(argv: &[&str]) -> bool {\n    match argv {',
     'fn allows(argv: &[&str]) -> bool {\n    if !argv.is_empty() {\n        return true;\n    }\n    match argv {',
     ('rust',)),
    ('apps/web/src/poller.ts', 'const delay = settled.ok ? this.o.intervalMs :',
     'const delay = settled.ok ? this.o.intervalMs * 2 :', ('web',)),
    ('contracts/attachment.v1.schema.json', '"minLength": 1,\n      "maxLength": 64,', '"minLength": 1,\n      "maxLength": 65,',
     ('rust',)),
    ('crates/server/src/web.rs', '("css", "text/css; charset=utf-8"),', '("css", "text/plain; charset=utf-8"),',
     ('rust', 'web')),
]
EXPORT_INPUT = ('apps/web/',)
NOT_EXPORT = ('apps/web/test/', 'apps/web/out/', 'apps/web/node_modules/')


def verdict(picked, results):
    """{'caught_by', 'hidden'}: the picked and the skipped tests that failed."""
    failed = {u for u, rc in results.items() if rc != 0}
    return {'caught_by': sorted(failed & picked), 'hidden': sorted(failed - picked)}


def apply(root, path, old, new):
    full = os.path.join(root, path)
    with open(full, 'rb') as f:
        original = f.read()
    text = original.decode()
    if text.count(old) != 1:
        raise SystemExit(f'planted: {old!r} is in {path} {text.count(old)} times, not once')
    with open(full, 'w') as f:
        f.write(text.replace(old, new))
    return original


def build_export(root):
    """Build apps/web's export, edit included, into apps/web/out's contents."""
    copy = os.path.join(root, 'apps/.planted-web')
    shutil.rmtree(copy, ignore_errors=True)
    shutil.copytree(os.path.join(root, 'apps/web'), copy, symlinks=True,
                    ignore=shutil.ignore_patterns('node_modules', 'out', '.next', 'test-results'))
    os.symlink(os.path.join(root, 'apps/web/node_modules'), os.path.join(copy, 'node_modules'))
    try:
        subprocess.run(['npm', 'run', 'build'], cwd=copy, check=True, stdout=subprocess.DEVNULL)
        replace_contents(os.path.join(copy, 'out'), os.path.join(root, 'apps/web/out'))
    finally:
        shutil.rmtree(copy, ignore_errors=True)


def replace_contents(src, dst):
    for name in os.listdir(dst):
        p = os.path.join(dst, name)
        shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.unlink(p)
    for name in os.listdir(src):
        s, d = os.path.join(src, name), os.path.join(dst, name)
        shutil.copytree(s, d, symlinks=True) if os.path.isdir(s) else shutil.copy2(s, d)


def record(out, row):
    """Append one case's row to OUT, making its folder if a fallback left none (#1579 R9)."""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, 'a') as f:
        f.write(json.dumps(row, sort_keys=True) + '\n')


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('lane', choices=['rust', 'web'])
    ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=4)
    args = ap.parse_args(argv)
    root = os.getcwd()
    with open(os.path.join(HERE, 'map.json')) as f:
        mp = pick.strict_json(f.read())
    todo = trace.commands(args.lane, root, 8)
    every = sorted(set(todo) | set(mp['units']))
    out_dir = os.path.join(root, 'apps/web/out')
    keep_out = os.path.join(root, 'apps/.planted-out')
    failed = False
    if args.lane == 'web':
        subprocess.run(['node', '-e', "import('./test/support/rust.mjs').then((m) => m.buildBinaries())"],
                       cwd=os.path.join(root, 'apps/web'), check=True)
    for path, old, new, catchers in CASES:
        if not catchers or not set(catchers) <= {'rust', 'web'}:
            raise SystemExit(f'planted: {path}: no lanes named to catch it')
        sel = pick.select([('M', path)], mp, every, lambda p: None, lambda ps: set())
        picked = set(sel['tests'])
        export = path.startswith(EXPORT_INPUT) and not path.startswith(NOT_EXPORT)
        original = apply(root, path, old, new)
        try:
            if export:
                shutil.rmtree(keep_out, ignore_errors=True)
                shutil.copytree(out_dir, keep_out, symlinks=True)
                build_export(root)
            logs = os.path.join(root, 'target/planted-logs')
            os.makedirs(logs, exist_ok=True)

            def one(uid):
                argv_, cwd = todo[uid]
                return uid, trace.plain_run(argv_, cwd, dict(os.environ), os.path.join(logs, uid.replace(':', '_')))[0]
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                results = dict(pool.map(one, sorted(todo)))
        finally:
            with open(os.path.join(root, path), 'wb') as f:
                f.write(original)
            if export:
                replace_contents(keep_out, out_dir)
                shutil.rmtree(keep_out, ignore_errors=True)
        v = verdict(picked & set(todo), results)
        row = {'lane': args.lane, 'path': path, 'edit': [old, new], 'selection': sel['mode'],
               'picked': sorted(picked & set(todo)), 'skipped': sorted(set(todo) - picked), **v,
               'catchers': list(catchers),
               'verdict': 'FAIL: a skipped test failed' if v['hidden'] else
               ('caught' if v['caught_by'] else
                'FAIL: this lane must catch it, and none of its picked tests did' if args.lane in catchers else
                'not caught in this lane')}
        failed |= bool(v['hidden']) or (args.lane in catchers and not v['caught_by'])
        print('planted: ' + json.dumps(row, sort_keys=True), flush=True)
        record(args.out, row)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
