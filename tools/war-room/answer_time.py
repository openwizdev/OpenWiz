#!/usr/bin/env python3
"""Offline answer-time projection into the existing War room suite slot.

Inputs are sanitized, source-validated projection facts, not native decisions,
fleet or TL2 records. No source reader, reply parser, storage or clock lives here.
The source owner must establish substantive meaning, linkage, completeness and
artifact binding independently before supplying facts. Syntactic validation is
not proof of provenance. Current native-source limitations use unavailable().
"""
import copy
from datetime import datetime
import importlib.util
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('war_room_suite', Path(__file__).with_name('suite.py'))
suite = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(suite)

KINDS = ('substantive_disposition', 'notification_sent', 'notification_accepted',
         'needs_info_removed', 'status_resolved', 'unknown')
COMPLETENESS = ('complete', 'edited', 'deleted', 'unknown')
REFERENCE = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/'
                       r'(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*')
IDENTITY = re.compile(r'[a-z0-9][a-z0-9._:-]*')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def time(value):
    require(type(value) is str and re.fullmatch(
        r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value), 'invalid UTC time')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')


def identity(value):
    require(type(value) is str and IDENTITY.fullmatch(value) and 'thr_' not in value,
            'invalid sanitized identity')


def reference(value):
    require(value is None or (type(value) is str and REFERENCE.fullmatch(value)),
            'invalid source reference')


def fact(value, keys):
    require(type(value) is dict and set(value) == set(keys), 'unexpected or missing fact fields')
    require(type(value['completeness']) is str and value['completeness'] in COMPLETENESS,
            'invalid completeness')
    reference(value['reference'])
    if value['at'] is not None:
        time(value['at'])


def unavailable():
    """No native endpoint is inferred from status, receipt, or missing history."""
    return {'slot': 'answer_time', 'state': 'unavailable', 'metrics': [], 'prerequisites': [
        'An independently sourced substantive orchestrator disposition linked to each recorded request; decisions v1 open discovery supplies no answer timestamp.',
        'Fleet sent/accepted notifications and needs-info removal do not establish substantive answers; journey v1 contains no answer intervals and history is unknown.',
        'TL2 producer and actual measured builder-question contract, when available; reuse that fact rather than implementing another builder-question timer.',
    ]}


def project(sample_at, *, source, window, observed_at, cohort, requests,
            dispositions=(), expected=None, history='unknown', assembled_at=None,
            timings=()):
    """Return one provider for compose(), without reading any native source.

    The cohort is selected by recorded request time in [since, until); unknown
    starts stay in its explicit denominator. observed_at bounds all endpoints.
    Facts contain metadata only; no body or response text is accepted. `timings`
    may contain existing suite-projected intervals for the SAME facts (e.g. WR3
    after TL2 is available). Their native values/units/source are reused, never
    recalculated. No TL2 native fields, parser or timer are defined here.
    """
    identity(cohort)
    require(type(history) is str and history in ('complete', 'unknown'), 'invalid history coverage')
    require(expected is None or (type(expected) is int and expected >= 0), 'invalid expected coverage')
    require(type(requests) in (list, tuple) and type(dispositions) in (list, tuple)
            and type(timings) in (list, tuple), 'facts must be sequences')
    require(type(window) is dict and set(window) == {'since', 'until', 'timezone'}, 'invalid window')
    since, until, observed = time(window['since']), time(window['until']), time(observed_at)
    require(since < until <= observed, 'invalid source bounds')
    unique, refs = {}, {}
    for request in requests:
        fact(request, ('id', 'at', 'reference', 'completeness', 'ticket'))
        identity(request['id'])
        require(request['ticket'] is None or (type(request['ticket']) is int and request['ticket'] > 0),
                'invalid ticket')
        key, ref = request['id'], request['reference']
        require(key not in unique or unique[key] == request, 'conflicting request identity')
        require(ref is None or ref not in refs or refs[ref] == key, 'duplicate request source identity')
        if request['at'] is not None:
            require(since <= time(request['at']) < until, 'request outside selected cohort')
        unique[key] = request
        if ref is not None:
            refs[ref] = key
    require(expected is None or expected >= len(unique), 'coverage exceeds expected cohort')
    answers, receipts = {}, {}
    for disposition in dispositions:
        fact(disposition, ('request', 'kind', 'at', 'reference', 'completeness'))
        reference(disposition['request'])
        require(type(disposition['kind']) is str and disposition['kind'] in KINDS, 'invalid disposition kind')
        ref = disposition['reference']
        require(ref is None or ref not in receipts or receipts[ref] == disposition,
                'conflicting disposition identity')
        if ref is not None:
            receipts[ref] = disposition
        if disposition['kind'] == 'substantive_disposition' and disposition['request'] in refs:
            key = refs[disposition['request']]
            if disposition not in answers.setdefault(key, []):
                answers[key].append(disposition)

    # This consumes the established suite projection, not any conjectured TL2
    # native structure. Each supplied timing must be validated as its own fact.
    measured = {}
    for timing in timings:
        suite.compose(sample_at, [{'slot': 'answer_time', 'state': 'known',
                                  'prerequisites': [], 'metrics': [dict(timing, group='decisions')]}],
                      assembled_at=assembled_at)
        require(timing['interval'] is not None, 'reused timing needs interval identity')
        key = timing['interval']['id']
        require(key in unique and key not in measured, 'duplicate or unrelated timing')
        measured[key] = timing

    common_gaps = []
    if source is None:
        common_gaps.append('Validated source artifact and exact byte binding are unavailable.')
    if history != 'complete':
        common_gaps.append('Historical completeness is unknown; edited or deleted source history may be missing.')
    if expected is None or expected != len(unique):
        common_gaps.append('Complete expected request-cohort coverage is unavailable.')
    evidence = sorted({r['reference'] for r in unique.values() if r['reference'] is not None})

    def metric(key, label, value, unit, statistic, ids, gaps, *, links=None, interval=None, ticket=None):
        links = evidence if links is None else links
        state = ('unavailable' if source is None or not links else 'partial' if gaps else 'known')
        return {'id': key, 'group': 'decisions', 'label': label, 'state': state,
                'value': None if state == 'unavailable' else value, 'unit': unit,
                'native_unit': unit, 'statistic': statistic, 'window': copy.deepcopy(window),
                'observed_at': observed_at, 'fresh_until': None, 'freshness': 'unknown',
                'source': copy.deepcopy(source), 'evidence': list(links),
                'sample': {'observed': len(ids), 'expected': len(ids), 'identities': list(ids),
                           'numerator': None, 'denominator': None},
                'dimensions': {'direction': None, 'pool': None, 'stage': None,
                               'ticket': ticket, 'cohort': cohort},
                'interval': interval,
                'prerequisites': list(gaps) if state != 'unavailable' else
                    list(dict.fromkeys([*gaps, 'Independent source provenance is unavailable.']))}

    metrics, counts = [], {'answered': 0, 'open-censored': 0, 'unknown-censored': 0}
    for key, request in sorted(unique.items()):
        gaps, start, end = [], None, None
        links = [request['reference']] if request['reference'] is not None else []
        if (request['completeness'] == 'complete' and request['at'] is not None
                and request['reference'] is not None):
            start = request['at']
        else:
            gaps.append('Unchanged recorded request time and independent provenance are required.')
        candidates = answers.get(key, [])
        if len(candidates) == 1:
            answer = candidates[0]
            if (start is not None and answer['completeness'] == 'complete'
                    and answer['at'] is not None and answer['reference'] is not None
                    and answer['reference'] != request['reference']
                    and time(start) <= time(answer['at']) <= observed):
                end = answer['at']
                links.append(answer['reference'])
            else:
                gaps.append('Linked substantive disposition needs independent unchanged provenance and ordered observed times.')
        else:
            gaps.append('One independently sourced linked substantive disposition is required; request remains open or censored.')
        if source is None:
            gaps.append('Validated source artifact and exact byte binding are unavailable.')
            end = None
        status = 'answered' if end is not None else 'open-censored' if start is not None and not candidates else 'unknown-censored'
        counts[status] += 1
        value = ((time(end) - time(start)).total_seconds()
                 if end is not None and key not in measured else None)
        item = metric('interval-' + key, 'Recorded answer interval' if end else status.replace('-', ' ').capitalize(),
                      value, 'seconds', 'observation', [key], gaps, links=links,
                      interval={'id': key, 'started_at': start, 'ended_at': end}, ticket=request['ticket'])
        if key in measured:
            timing = measured[key]
            require(end is not None and timing['interval'] == item['interval']
                    and set(links) <= set(timing['evidence'])
                    and timing['observed_at'] <= observed_at
                    and timing['unit'] in ('seconds', 'minutes', 'hours')
                    and timing['statistic'] == 'observation', 'reused timing is not the same proven interval')
            timing_ticket = timing['dimensions']['ticket']
            require(request['ticket'] is None or timing_ticket is None
                    or request['ticket'] == timing_ticket, 'conflicting timing ticket attribution')
            # Keep native source/value/time/unit/window/sample rather than
            # relabelling a new calculation as TL2's independently measured fact.
            item = copy.deepcopy(timing)
            item.update(id='interval-' + key, group='decisions', label='Recorded answer interval')
        metrics.append(item)
    ids = sorted(unique)
    gaps = list(common_gaps)
    if counts['answered'] != len(ids):
        gaps.append('Open or unknown intervals are censored; they are not completed zero waits.')
    if not ids:
        gaps.append('A nonempty recorded request cohort is required for answer coverage.')
    for key, label in [('answered', 'Proven substantive answers'),
                       ('open-censored', 'Open or censored requests'),
                       ('unknown-censored', 'Unknown or censored intervals')]:
        item = metric(key, label, counts[key], 'count', 'count', ids, common_gaps)
        item['sample']['expected'] = expected
        metrics.append(item)
    item = metric('answer-coverage', 'Answered share of recorded request cohort',
                  counts['answered'] / len(ids) if ids else None,
                  'ratio', 'proportion', ids, gaps)
    item['sample'].update(expected=expected, numerator=counts['answered'], denominator=len(ids))
    metrics.append(item)
    state = ('known' if all(m['state'] == 'known' for m in metrics) else
             'partial' if any(m['state'] != 'unavailable' for m in metrics) else 'unavailable')
    provider = {'slot': 'answer_time', 'state': state, 'metrics': metrics,
                'prerequisites': [] if state == 'known' else list(dict.fromkeys(
                    gap for m in metrics for gap in m['prerequisites']))}
    # Fail closed using the one category/envelope boundary, including source
    # shape, units, identity counts and source/assembly ordering.
    checked = suite.compose(sample_at, [provider], assembled_at=assembled_at)
    return next(p for p in checked['providers'] if p['slot'] == 'answer_time')
