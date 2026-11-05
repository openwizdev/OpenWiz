#!/usr/bin/env python3
"""Strict v1 aggregate report reader/comparator. Python standard library only."""
import argparse
import hashlib
import json
import math
from pathlib import Path

SCHEMA = 'openwiz.scale-50.v1'


def decode(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError('non-JSON number: ' + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def read(path):
    result = decode(Path(path).read_text())
    validate(result)
    return result


def obj(value, keys):
    if type(value) is not dict or set(value) != set(keys.split()):
        raise ValueError('expected exactly: ' + keys)


def number(value, field):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(field + ': expected finite nonnegative number')


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('expected nonnegative integer')


def strings(value):
    if type(value) is not list or any(type(v) is not str or not v for v in value):
        raise ValueError('expected string list')


def texts(value):
    if any(type(v) is not str or not v for v in value.values()):
        raise ValueError('expected identity strings')


def distribution(value, field):
    obj(value, 'p50 p95 samples')
    number(value['p50'], field + '.p50'); number(value['p95'], field + '.p95'); integer(value['samples'])
    if not value['samples'] or value['p50'] > value['p95']:
        raise ValueError('invalid distribution')


def model_digest(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_model(value, allow_unknown=False):
    if value is None and allow_unknown:
        return
    obj(value, 'sha256 files')
    files = value['files']
    if type(files) is not dict or not files:
        raise ValueError('measurement_model files required')
    for path, digest in files.items():
        if type(path) is not str or not path or not path.isascii() or path.startswith('/') or '\\' in path or any(part in ('', '.', '..') for part in path.split('/')):
            raise ValueError('invalid measurement_model path')
        if type(digest) is not str or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('invalid measurement_model source digest')
    if value['sha256'] != model_digest(files):
        raise ValueError('measurement_model digest mismatch')


def validate(r):
    obj(r, 'schema evidence_class state workload measurement_model candidate bounds coverage window metrics budgets gaps')
    if r['schema'] != SCHEMA or r['evidence_class'] not in ('fixture', 'live') or r['state'] not in ('complete', 'partial', 'unknown'):
        raise ValueError('unknown schema, evidence class or state')
    strings(r['gaps'])
    if r['state'] != 'complete' and not r['gaps']:
        raise ValueError('partial/unknown requires gaps')
    obj(r['workload'], 'id sha256 tickets specs arrival role_policy')
    texts({k: r['workload'][k] for k in ('id', 'sha256', 'arrival', 'role_policy')})
    integer(r['workload']['tickets']); integer(r['workload']['specs'])
    if len(r['workload']['sha256']) != 64 or any(c not in '0123456789abcdef' for c in r['workload']['sha256']):
        raise ValueError('invalid workload hash')
    validate_model(r['measurement_model'], allow_unknown=r['state'] != 'complete')
    obj(r['candidate'], 'revision tools config')
    texts(r['candidate'])
    obj(r['bounds'], 'max_wall_s virtual_duration_s quiet_s merge_s max_active rest_limit graphql_limit')
    for v in r['bounds'].values(): integer(v)
    if type(r['coverage']) is not list or not r['coverage']:
        raise ValueError('coverage required')
    for c in r['coverage']:
        obj(c, 'route mode tickets gaps')
        texts({k: c[k] for k in ('route', 'mode')}); integer(c['tickets']); strings(c['gaps'])
    obj(r['window'], 'start_s end_s active_intervals')
    integer(r['window']['start_s']); integer(r['window']['end_s'])
    if r['window']['end_s'] <= r['window']['start_s']:
        raise ValueError('empty window')
    if type(r['window']['active_intervals']) is not list:
        raise ValueError('interval list required')
    last = r['window']['start_s']
    for i in r['window']['active_intervals']:
        obj(i, 'start_s end_s builders reviewers')
        for v in i.values(): integer(v)
        if i['start_s'] < last or i['end_s'] <= i['start_s'] or i['end_s'] > r['window']['end_s'] or i['builders'] + i['reviewers'] > r['bounds']['max_active']:
            raise ValueError('invalid active interval')
        last = i['end_s']
    if r['state'] == 'complete' and not any(
        i['builders'] + i['reviewers'] == r['bounds']['max_active']
        and i['builders'] > 0 and i['reviewers'] > 0
        for i in r['window']['active_intervals']
    ):
        raise ValueError('complete report requires mixed-role concurrency evidence')
    obj(r['metrics'], 'tick_ms starts event_action_s review_queue_s recheck_delay_s merge_delay_s ci_wait_s review_backlog_peak recheck_backlog_peak verified_merges merges_per_hour completed requests_per_ticket graphql_cost_per_ticket accepted_starts_per_minute http_per_tick')
    for key in ('tick_ms', 'event_action_s', 'review_queue_s', 'recheck_delay_s', 'merge_delay_s', 'ci_wait_s'):
        value = r['metrics'][key]
        if value is None and r['state'] != 'complete':
            continue
        distribution(value, 'metrics.' + key)
    obj(r['metrics']['starts'], 'attempted accepted uncertain refused')
    for v in r['metrics']['starts'].values(): integer(v)
    s = r['metrics']['starts']
    if s['attempted'] != s['accepted'] + s['uncertain'] + s['refused']:
        raise ValueError('start outcomes do not reconcile')
    for key in ('review_backlog_peak', 'recheck_backlog_peak', 'verified_merges', 'completed'):
        integer(r['metrics'][key])
    obj(r['metrics']['http_per_tick'], 'rest_requests graphql_requests graphql_cost')
    for key, value in r['metrics']['http_per_tick'].items():
        if value is None and r['state'] != 'complete': continue
        distribution(value, 'metrics.http_per_tick.' + key)
    for key in ('merges_per_hour', 'requests_per_ticket', 'graphql_cost_per_ticket', 'accepted_starts_per_minute'):
        number(r['metrics'][key], 'metrics.' + key)
    obj(r['budgets'], 'rest graphql live_limits')
    if r['budgets']['live_limits'] not in ('unknown', 'observed'):
        raise ValueError('invalid live limit state')
    if r['budgets']['live_limits'] != 'unknown' and r['evidence_class'] == 'fixture':
        raise ValueError('fixtures cannot observe live limits')
    for kind, keys in [('rest', 'requests shared_requests limit remaining reset_s'), ('graphql', 'requests cost shared_cost limit remaining reset_s')]:
        b = r['budgets'][kind]; obj(b, keys)
        for v in b.values():
            if v is None and r['state'] != 'complete': continue
            integer(v)
        if b['remaining'] is not None and b['limit'] is not None and b['remaining'] > b['limit']:
            raise ValueError('remaining exceeds allowance')
    return r


def compare(baseline, candidate):
    for r in (baseline, candidate):
        validate(r)
        if r['state'] != 'complete':
            raise ValueError('comparison requires complete measurements')
    for key in ('schema', 'workload', 'measurement_model', 'bounds', 'coverage', 'evidence_class'):
        if baseline[key] != candidate[key]:
            raise ValueError('incomparable ' + key)
    if baseline['window']['end_s'] - baseline['window']['start_s'] != candidate['window']['end_s'] - candidate['window']['start_s']:
        raise ValueError('incomparable observation duration')
    return dict(tick_p95_ms_delta=candidate['metrics']['tick_ms']['p95'] - baseline['metrics']['tick_ms']['p95'],
                rest_requests_delta=candidate['budgets']['rest']['requests'] - baseline['budgets']['rest']['requests'],
                graphql_cost_delta=candidate['budgets']['graphql']['cost'] - baseline['budgets']['graphql']['cost'],
                candidate_changes={k: [baseline['candidate'][k], candidate['candidate'][k]] for k in baseline['candidate'] if baseline['candidate'][k] != candidate['candidate'][k]})


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('report', type=Path)
    p.add_argument('--compare', type=Path)
    a = p.parse_args()
    r = read(a.report)
    print(json.dumps(compare(r, read(a.compare)) if a.compare else r, indent=2, sort_keys=True))
