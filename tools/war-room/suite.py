#!/usr/bin/env python3
"""One finite, offline composition/check seam. Python standard library only."""
import argparse
import copy
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def _finite(value):
    if type(value) is float:
        require(math.isfinite(value), 'nonfinite number')
    elif type(value) is dict:
        for item in value.values():
            _finite(item)
    elif type(value) is list:
        for item in value:
            _finite(item)


def _decode(wire):
    def reject(_):
        raise ValueError('nonfinite JSON constant')
    result = json.loads(wire, object_pairs_hook=_pairs, parse_constant=reject)
    _finite(result)  # Also refuses overflow such as 1e999.
    return result


SCHEMA = _decode((HERE / 'record.schema.json').read_text(encoding='utf-8'))
PROVIDERS = SCHEMA['x-providers']
GROUPS = SCHEMA['properties']['groups']['const']


def _shape(value, rule):
    """Evaluate only the structural JSON Schema vocabulary used by this file.

    No package, remote reference or format resolver. Cross-record rules below
    are deliberately separate from JSON Schema's structural guarantees.
    """
    if '$ref' in rule:
        return _shape(value, SCHEMA['$defs'][rule['$ref'].removeprefix('#/$defs/')])
    if 'anyOf' in rule:
        for alternative in rule['anyOf']:
            try:
                _shape(value, alternative)
                return
            except ValueError:
                pass
        raise ValueError('invalid nullable field')
    if 'const' in rule:
        require(type(value) is type(rule['const']) and value == rule['const'], 'invalid constant/order')
    if 'enum' in rule:
        require(type(value) is str and value in rule['enum'], 'invalid enum')
    kind = rule.get('type')
    if kind is None:
        return
    types = {'object': (dict,), 'array': (list,), 'string': (str,),
             'integer': (int,), 'number': (int, float), 'null': (type(None),)}
    require(type(value) in types[kind], 'invalid field type')
    if kind == 'object':
        require(set(rule['required']) <= set(value) <= set(rule['properties']), 'unexpected or missing fields')
        for key, item in value.items():
            _shape(item, rule['properties'][key])
    elif kind == 'array':
        require(len(value) >= rule.get('minItems', 0), 'missing array entries')
        require('maxItems' not in rule or len(value) <= rule['maxItems'], 'extra array entries')
        if rule.get('uniqueItems'):
            require(len({json.dumps(v, sort_keys=True) for v in value}) == len(value), 'duplicate array entry')
        for item in value:
            _shape(item, rule['items'])
    elif kind == 'string':
        require(len(value) >= rule.get('minLength', 0), 'empty text')
        require('pattern' not in rule or re.search(rule['pattern'], value) is not None, 'invalid text form')
    elif kind in ('integer', 'number'):
        require(value >= rule.get('minimum', 0), 'number below bound')


def _time(value):
    require(type(value) is str and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z', value), 'invalid UTC time')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')
    except ValueError as error:
        raise ValueError('invalid UTC calendar time') from error


def _metric(metric, groups, assembled):
    state, value, sample = metric['state'], metric['value'], metric['sample']
    require(metric['group'] in groups, 'metric in wrong provider group')
    require(metric['unit'] == metric['native_unit'], 'unit conflict; suite performs no conversion')
    require(sample['observed'] == len(sample['identities']), 'sample identity coverage mismatch')
    if sample['expected'] is not None:
        require(sample['observed'] <= sample['expected'], 'sample coverage exceeds cohort')
    if state == 'known':
        require(value is not None and not metric['prerequisites'], 'known value missing or has prerequisites')
        require(sample['expected'] == sample['observed'], 'known value needs complete coverage')
    else:
        require(bool(metric['prerequisites']), 'incomplete metric needs prerequisites')
        require(state != 'unavailable' or value is None, 'unavailable value must be null')
    if value is not None or state == 'known':
        require(metric['observed_at'] is not None and metric['window'] is not None
                and metric['source'] is not None and bool(metric['evidence']), 'value needs source evidence/window/time')
    observed = _time(metric['observed_at']) if metric['observed_at'] is not None else None
    require(observed is None or observed <= assembled, 'observation after assembly')
    window = metric['window']
    if window is not None:
        since, until = _time(window['since']), _time(window['until'])
        require(since < until, 'reversed or empty source window')
        require(observed is not None and until <= observed, 'window beyond source observation')
    if metric['fresh_until'] is None:
        require(metric['freshness'] == 'unknown', 'freshness requires source validity bound')
    else:
        bound = _time(metric['fresh_until'])
        require(observed is not None and observed <= bound, 'invalid source validity bound')
        require(metric['freshness'] == ('stale' if assembled > bound else 'fresh'), 'freshness mismatch')
    statistic, unit = metric['statistic'], metric['unit']
    rounding = metric.get('rounding', 'exact')
    if statistic in ('ratio', 'proportion'):
        require(unit in ('ratio', 'percent', 'usd_per_merged_pr'), 'ratio unit conflict')
        require(statistic != 'proportion' or unit != 'usd_per_merged_pr', 'proportion unit conflict')
        require(rounding == 'exact' or (rounding == 'half_up_0' and unit == 'percent')
                or (rounding == 'half_up_1' and unit == 'ratio'), 'rounding unit conflict')
        numerator, denominator = sample['numerator'], sample['denominator']
        require((numerator is None) == (denominator is None), 'incomplete ratio basis')
        if numerator is not None:
            require(denominator == sample['observed'], 'ratio denominator/coverage conflict')
            if unit != 'usd_per_merged_pr':
                require(type(numerator) is int, 'ratio numerator must be a count')
            if statistic == 'proportion' or unit == 'percent':
                require(numerator <= denominator, 'proportion numerator exceeds cohort')
        if value is not None:
            require(denominator is not None and denominator > 0, 'ratio needs nonzero denominator')
            multiplier = 100 if unit == 'percent' else 1
            if rounding == 'exact':
                expected = numerator / denominator * multiplier
                require(math.isclose(value, expected, rel_tol=1e-12, abs_tol=0), 'ratio arithmetic mismatch')
            else:
                # Native board values use nonnegative integer counts. Compute
                # half-up from the exact remainder, without float/tie drift.
                scale = 10 if rounding == 'half_up_1' else 1
                whole, remainder = divmod(numerator * multiplier * scale, denominator)
                expected = (whole + (2 * remainder >= denominator)) / scale
                require(value == expected, 'rounded ratio arithmetic mismatch')
    else:
        require('rounding' not in metric, 'rounding only applies to ratios/proportions')
        require(sample['numerator'] is None and sample['denominator'] is None, 'unexpected ratio basis')
        require(unit not in ('ratio', 'percent', 'usd_per_merged_pr'), 'ratio unit needs ratio statistic')
    if statistic == 'count':
        require(unit in ('count', 'tokens') and (value is None or type(value) is int), 'count unit/type conflict')
    if statistic in ('median', 'p90') and value is not None:
        require(sample['observed'] > 0, 'empty distribution')
    interval = metric['interval']
    if interval is not None:
        start = _time(interval['started_at']) if interval['started_at'] is not None else None
        end = _time(interval['ended_at']) if interval['ended_at'] is not None else None
        require((start is None and end is None) or observed is not None, 'interval endpoints need source observation')
        require(start is None or start <= observed, 'interval begins after source observation')
        require(end is None or (start is not None and start <= end <= observed), 'reversed/unobserved interval')
        require(state != 'known' or (start is not None and end is not None), 'open interval cannot be known complete')


def validate(record):
    """Check the entire snapshot; return None, or raise ValueError. No writes."""
    _finite(record)
    _shape(record, SCHEMA)
    sample, assembled = _time(record['sample_at']), _time(record['assembled_at'])
    require(sample.minute % 5 == 0 and sample.second == 0, 'sample must be a five-minute UTC boundary')
    require(record['sample_id'] == record['sample_at'], 'sample identity mismatch')
    require(assembled >= sample, 'assembly before sample boundary')
    require([p['slot'] for p in record['providers']] == [p['slot'] for p in PROVIDERS], 'provider inventory/order mismatch')
    for provider, definition in zip(record['providers'], PROVIDERS):
        ids = [m['id'] for m in provider['metrics']]
        require(len(ids) == len(set(ids)), 'duplicate metric identity')
        state, metrics = provider['state'], provider['metrics']
        if state == 'known':
            require(bool(metrics) and not provider['prerequisites'] and all(m['state'] == 'known' for m in metrics), 'known provider lacks complete metrics')
        elif state == 'partial':
            require(bool(provider['prerequisites']) and any(
                m['state'] != 'unavailable' and m['source'] is not None
                and m['observed_at'] is not None and bool(m['evidence'])
                for m in metrics), 'partial provider lacks observations/prerequisites')
        else:
            require(bool(provider['prerequisites']) and all(m['state'] == 'unavailable' for m in metrics), 'unavailable provider contains known metrics')
        for metric in metrics:
            _metric(metric, definition['groups'], assembled)


def loads(wire):
    """Strict wire reader plus full contract validation."""
    record = _decode(wire)
    validate(record)
    return record


def load(path):
    return loads(Path(path).read_text(encoding='utf-8'))


def compose(sample_at, providers=(), *, assembled_at=None):
    """Compose already projected records; missing providers are visible stubs.

    This never invokes a provider, collects a source, computes a bench, saves a
    sample, or changes source timestamps. Invalid supplied data fails closed.
    """
    supplied = {}
    for provider in providers:
        _finite(provider)
        _shape(provider, SCHEMA['$defs']['provider'])
        require(provider['slot'] not in supplied, 'duplicate provider')
        supplied[provider['slot']] = copy.deepcopy(provider)
    record = {'schema': 'openwiz.war-room.v1', 'sample_id': sample_at,
              'sample_at': sample_at, 'assembled_at': sample_at if assembled_at is None else assembled_at,
              'groups': copy.deepcopy(GROUPS), 'providers': []}
    for definition in PROVIDERS:
        record['providers'].append(supplied.get(definition['slot'], {
            'slot': definition['slot'], 'state': 'unavailable',
            'prerequisites': copy.deepcopy(definition['prerequisites']), 'metrics': []}))
    validate(record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    check = commands.add_parser('check', help='validate an explicit local snapshot; - reads stdin')
    check.add_argument('path')
    compose_parser = commands.add_parser('compose', help='compose local projected provider records; no source reads')
    compose_parser.add_argument('--at', required=True)
    compose_parser.add_argument('--assembled-at')
    compose_parser.add_argument('--providers', help='local JSON array of already projected records')
    args = parser.parse_args()
    try:
        if args.command == 'check':
            record = loads(sys.stdin.read()) if args.path == '-' else load(args.path)
        else:
            providers = _decode(Path(args.providers).read_text(encoding='utf-8')) if args.providers else []
            require(type(providers) is list, 'providers must be an array')
            record = compose(args.at, providers, assembled_at=args.assembled_at)
        print(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False))
        return 0
    except (ValueError, OSError, UnicodeError, RecursionError):
        # Never echo source data, file paths, raw upstream errors or private text.
        print('suite: invalid or unreadable local record', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
