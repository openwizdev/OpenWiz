#!/usr/bin/env python3
"""Paired canonical-adjudication arithmetic, with missing/unresolved rows retained.

Semantic matching and root-cause/location deduplication are independently
arm-blinded judgments, not guesses by this arithmetic. The EB5 validator enforces
canonical-id uniqueness, known severity, chronology and the fixed common rubric.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('score_contract', HERE.parents[1] / 'factory-metrics/experiment_contract.py')
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)
OUTCOMES = ('catch', 'miss', 'false_positive', 'unmatched', 'unadjudicated')


def counts(findings):
    return {outcome: sum(f['outcome'] == outcome for f in findings) for outcome in OUTCOMES}


def score(document, journey):
    C.validate(document, journey)
    replay = document['replay']; C.require(replay is not None, 'missing replay')
    rows = []
    for row in replay['cohort']:
        arms, clean = {}, {}
        known = {severity: sum(f['severity'] == severity for f in row['known']) for severity in C.RUBRIC['severity']}
        for name in C.ARMS:
            arm = row['arms'][name]
            findings = arm['adjudications'][-1]['findings'] if arm['adjudications'] else None
            resolved = findings is not None and not any(f['outcome'] in ('unmatched', 'unadjudicated') for f in findings)
            arms[name] = {'status': arm['status'], 'resolution': 'resolved' if resolved else 'unadjudicated',
                          'counts': None if findings is None else counts(findings),
                          'severity': None if findings is None else {
                              s: counts([f for f in findings if f['severity'] == s]) for s in C.RUBRIC['severity']}}
            if row['known']: clean[name] = 'not_control'
            elif not resolved: clean[name] = 'unresolved'
            else: clean[name] = 'false_positive' if arms[name]['counts']['false_positive'] else 'clean'
        paired = all(a['status'] == 'complete' and a['resolution'] == 'resolved' for a in arms.values())
        delta = {k: arms['candidate']['counts'][k] - arms['old']['counts'][k]
                 for k in ('catch', 'miss', 'false_positive')} if paired else None
        rows.append({'pr': row['pr'], 'pair': 'complete' if paired else 'inconclusive', 'known': known,
                     'arms': arms, 'clean_control': clean, 'delta': delta,
                     'historical_rounds': row['history']['independent_rounds']})
    complete = [r for r in rows if r['pair'] == 'complete']
    return {'schema': 'openwiz.replay.scores.v1', 'evidence_class': 'fixture-or-replay-only',
            'rows': rows, 'coverage': {'cohort': len(rows), 'complete_pairs': len(complete),
                                     'inconclusive_pairs': len(rows) - len(complete)},
            'paired': {'n': len(complete), 'totals': {k: sum(r['delta'][k] for r in complete)
                       for k in ('catch', 'miss', 'false_positive')} if complete else None},
            'avoided_rounds': replay['avoided_rounds'],
            'gaps': ['Replay does not establish actual merge-time improvement.',
                     'Real isolation, adjudication provenance and upstream evidence require independent review.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('document'); parser.add_argument('--journey', required=True)
    args = parser.parse_args()
    try: print(json.dumps(score(C.read(args.document), C.read(args.journey)), allow_nan=False))
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(f'refused: {error}', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
