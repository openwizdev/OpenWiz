#!/usr/bin/env python3
"""Finite offline projection of validated journey facts into the WR6 suite slot.

No native verdict parsing, source collection, eval execution or recovery effects.
The source always has unknown historical coverage; values are observed lower
bounds, never complete-history correction rates or first-pass success claims.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def _module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


S = _module('rework_suite', HERE / 'suite.py')
J = _module('rework_journey', HERE.parent / 'factory-metrics/journey.py')


def project(wire, *, source_path, cohort, merged_prs, since, until, observed_at):
    """Return a page-ready provider, binding exact journey bytes to a named cohort.

    merged_prs is the explicit expected PR inventory, independent of the artifact.
    Missing records/merges stay gaps. source_path is a sanitized artifact reference;
    its hash binds the bytes, not a claim about the source's historical truth.
    Caller supplies the actual read bound; assembly cannot refresh it.
    """
    try:
        return _project(wire, source_path, cohort, merged_prs, since, until, observed_at)
    except (J.ReadError, ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
        # Never expose source bytes, paths, labels or parser values on refusal.
        raise ValueError('invalid rework input') from error


def _project(wire, source_path, cohort, merged_prs, since, until, observed_at):
    S.require(type(wire) is bytes, 'expected artifact bytes')
    doc = J.M.load(wire)
    J.validate(doc)  # The existing source owner admits facts; never reparse reports.
    S.require(type(cohort) is str and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', cohort), 'invalid cohort')
    S.require(type(source_path) is str and not J.THREAD.search(source_path), 'invalid source reference')
    S.require(type(merged_prs) is list and all(type(n) is int and n > 0 for n in merged_prs), 'invalid PR inventory')
    S.require(len(merged_prs) == len(set(merged_prs)), 'duplicate cohort PR')
    start, end, observed = S._time(since), S._time(until), S._time(observed_at)
    S.require(start < end <= observed, 'invalid source bounds')
    prs = {p['number']: p for p in doc['pull_requests']}
    gaps = ['Journey v1 historical completeness is unknown; retained records cannot prove absent or deleted reviews, fixes or CI attempts.']
    merged, reviewed, changed, rounds, fixes, answered, reruns, evidence = [], [], [], 0, 0, 0, 0, set()
    for n in sorted(merged_prs):
        p = prs.get(n)
        merges = [] if p is None else [e for e in p['events'] if e['kind'] == 'merge']
        if (p is None or p['state'] != 'merged' or len(merges) != 1
                or merges[0]['completeness'] != 'complete'
                or not since <= merges[0]['at'] < until
                or merges[0]['commit'] is None or merges[0]['commit'] != p['revisions']['merge']):
            gaps.append(f'PR {n}: need one unedited, commit-bound merge in the selected source window.')
            continue
        merge = merges[0]
        merged.append(f'pr-{n}')
        evidence.add(doc['sources'][merge['source']])
        independent = [e for e in p['events'] if J.rounds_of(e)]
        admitted = [e for e in independent if e['completeness'] == 'complete' and e['at'] <= merge['at']]
        if len(admitted) != len(independent):
            gaps.append(f'PR {n}: edited or post-merge review records need unedited source evidence.')
        if not admitted:
            gaps.append(f'PR {n}: no evidenced independent review; unreviewed is not first-pass success.')
        else:
            reviewed.append(f'pr-{n}')
        changes = {e['id'] for e in admitted if e['verdict'] == 'CHANGES'}
        if changes:
            changed.append(n)
        rounds += len(admitted)
        for e in admitted:
            evidence.add(doc['sources'][e['source']])
        for e in p['events']:
            if e['kind'] == 'fix_round' and e['after'] in changes:
                # journey.validate guarantees exactly one (PR, round) per CHANGES.
                fixes += 1
                if e['answers'] and e['completeness'] == 'complete' and e['at'] <= merge['at']:
                    answered += 1
                    evidence.add(doc['sources'][e['source']])
                else:
                    gaps.append(f'PR {n} fix round {e["round"]}: unanswered or edited/unprovable answer; resolution is unknown.')
        attempts = [e for e in p['events'] if e['kind'] == 'ci_attempt']
        if not attempts:
            gaps.append(f'PR {n}: no retained CI attempts; complete CI rework needs source history.')
        admitted_attempts = [e for e in attempts if e['completeness'] == 'complete' and e['at'] <= merge['at']]
        for e in admitted_attempts:
            # Source validation owns global (run, attempt) uniqueness.
            reruns += int(e['rerun'])
            evidence.add(doc['sources'][e['source']])
        if len(admitted_attempts) != len(attempts):
            gaps.append(f'PR {n}: edited or post-merge CI attempt needs source evidence.')
    if not merged_prs:
        gaps.append('No merged-PR cohort denominator; provide an explicit merged-PR inventory.')
    available = bool(merged)
    state = 'partial' if available else 'unavailable'
    source = {'path': source_path, 'schema': doc['schema'], 'sha256': hashlib.sha256(wire).hexdigest()}

    def metric(identity, label, value, identities=merged, numerator=None, denominator=None):
        usable = bool(identities)
        return {'id': identity, 'group': 'board', 'label': label,
                'state': 'partial' if usable else 'unavailable', 'value': value if usable else None,
                'unit': 'ratio' if denominator is not None else 'count',
                'native_unit': 'ratio' if denominator is not None else 'count',
                'statistic': 'proportion' if denominator is not None else 'count',
                'window': {'since': since, 'until': until, 'timezone': 'UTC'},
                'observed_at': observed_at, 'fresh_until': None, 'freshness': 'unknown',
                'source': source, 'evidence': sorted(evidence),
                'sample': {'observed': len(identities), 'expected': len(merged_prs), 'identities': identities,
                           'numerator': numerator, 'denominator': denominator},
                'dimensions': {'direction': None, 'pool': None, 'stage': None, 'ticket': None, 'cohort': cohort},
                'interval': None, 'prerequisites': list(gaps)}

    metrics = [
        metric('merged-prs', 'Evidenced merged PRs in the named cohort', len(merged)),
        metric('reviewed-coverage', 'Observed merged PRs with evidenced independent review; history unknown',
               len(reviewed)/len(merged) if merged else None, numerator=len(reviewed), denominator=len(merged)),
        metric('review-changes-share', 'Evidenced CHANGES share among observed reviewed PRs; history unknown',
               len(changed)/len(reviewed) if reviewed else None, identities=reviewed,
               numerator=len(changed), denominator=len(reviewed)),
        metric('review-rounds', 'Evidenced independent nonduplicate review rounds; lower bound', rounds),
        metric('fix-rounds', 'Recorded fix rounds, including unanswered rounds; lower bound', fixes),
        metric('answered-fix-rounds', 'Fix rounds with recorded unedited answers, not resolutions; lower bound', answered),
        metric('ci-reruns', 'Recorded CI rework: rerun attempts, separate from review corrections; lower bound', reruns),
    ]
    provider = {'slot': 'rework', 'state': state, 'prerequisites': gaps, 'metrics': metrics}
    # Reuse the complete suite admission boundary, including source/denominator rules.
    sample = observed.replace(minute=observed.minute//5*5, second=0).strftime('%Y-%m-%dT%H:%M:%SZ')
    S.compose(sample, [provider], assembled_at=observed_at)
    return provider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('journey')
    parser.add_argument('--source-path', required=True)
    parser.add_argument('--cohort', required=True)
    parser.add_argument('--pr', action='append', type=int, default=[])
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', required=True)
    parser.add_argument('--observed-at', required=True)
    args = parser.parse_args()
    try:
        provider = project(Path(args.journey).read_bytes(), source_path=args.source_path, cohort=args.cohort,
                           merged_prs=args.pr, since=args.since, until=args.until, observed_at=args.observed_at)
        print(json.dumps(provider, allow_nan=False))
    except (OSError, ValueError):
        print('refused: invalid rework input', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
