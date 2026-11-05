#!/usr/bin/env python3
"""R7: replay the owning port proof; optional schema-only historical scaffold.

--baseline b2fd29b0 runs isolated historical bytes, changing ONLY acceptance of
the new optional JSON key. Exit 1 is the demonstrated wrong-service/write red;
--head uses the unmodified current guard and must exit 0. No live endpoints.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import tempfile
import traceback
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--baseline')
    mode.add_argument('--head', action='store_true')
    parser.add_argument('--patch-out', type=Path)
    args = parser.parse_args()
    current = HERE / 'smoke.py'
    with tempfile.TemporaryDirectory(prefix='r7-schema-only-') as directory:
        runner = current
        source_sha = hashlib.sha256(current.read_bytes()).hexdigest()
        if args.baseline:
            original = subprocess.check_output(
                ['git', '-C', str(ROOT), 'show', f'{args.baseline}:tools/live-smoke/smoke.py'], text=True)
            old = "set(kit) not in (base, base | {'source'})"
            new = "set(kit) not in (base, base | {'source'}, base | {'default_terminal_port'}, base | {'source', 'default_terminal_port'})"
            assert original.count(old) == 1, 'exact historical schema required'
            scaffold = original.replace(old, new, 1)
            assert scaffold.count('default_terminal_port') == 2, 'schema-only change, no port guard'
            runner = Path(directory) / 'smoke.py'
            runner.write_text(scaffold)
            source_sha = hashlib.sha256(original.encode()).hexdigest()
            if args.patch_out:
                args.patch_out.write_text(''.join(difflib.unified_diff(
                    original.splitlines(True), scaffold.splitlines(True),
                    fromfile=f'{args.baseline}/smoke.py', tofile='schema-only/smoke.py')))
        review = runpy.run_path(str(HERE / 'test_review.py'))['Review']
        case = review('test_r5_nondefault_port_refuses_before_any_effect')
        case.setUp()
        try:
            globals_ = case.run_tool.__func__.__globals__
            with patch.dict(globals_, {'RUNNER': runner}):
                try:
                    case.test_r5_nondefault_port_refuses_before_any_effect()
                except AssertionError:
                    if not args.baseline:
                        raise
                    # A parser error or an always-pass stub is NOT this red:
                    # the historical process must pass and dispatch a real marker.
                    result = case.wrong_port_result
                    doc = json.loads(result.stdout)
                    assert result.returncode == 0 and doc['verdict'] == 'pass'
                    assert (case.root / 'wrong-service-effect').read_text() == 'dispatched'
                    assert ['status'] in case.wrong_port_calls
                    assert ['terminal'] in case.wrong_port_calls
                    traceback.print_exc()
                    print(json.dumps({'case': 'R7', 'baseline': args.baseline,
                        'source_sha256': source_sha, 'schema_only_scaffold': True,
                        'accepted_wrong_service': True, 'effect_dispatched': True}), flush=True)
                    return 1
                if args.baseline:
                    raise AssertionError('baseline unexpectedly satisfies the port guard')
                print(json.dumps({'case': 'R7', 'head': True, 'source_sha256': source_sha,
                                  'port_cases': 'pass'}))
                return 0
        finally:
            case.tearDown()
            case.doCleanups()


if __name__ == '__main__':
    raise SystemExit(main())
