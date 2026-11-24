#!/usr/bin/env python3
import argparse
import datetime
import json
import pathlib
import re
import sys

STEPS = ('preflight', 'install', 'setup check', 'skills copy', 'where', 'repo', 'connect', 'grill',
         'models', 'host setting', 'plan', 'launch', 'build', 'review', 'merge')
WAITS = ('user', 'agent', 'timer', 'ci')
LOG = 'steps.jsonl'
LOG_KEYS = {'at', 'step', 'waits_on', 'failure'}
GITHUB = ('spec.json', 'tickets.json', 'prs.json')
ISSUE_URL = re.compile(r'https://github\.com/([A-Za-z0-9-]+/[A-Za-z0-9._-]+)/issues/([1-9][0-9]*)')
FIELDS = {'spec.json': ('createdAt',), 'tickets.json': ('createdAt', 'url'),
          'prs.json': ('createdAt', 'mergedAt', 'closingIssuesReferences')}


class Bad(Exception):
    pass


def read_text(path):
    if not path.is_file():
        raise Bad(f'{path.name}: missing')
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        raise Bad(f'{path.name}: not UTF-8') from None


def no_repeats(pairs):
    keys = [k for k, _ in pairs]
    repeated = sorted({k for k in keys if keys.count(k) > 1})
    if repeated:
        raise ValueError(f'repeated key {repeated[0]!r}')
    return dict(pairs)


def exact_keys(where, value, required, optional=()):
    if not isinstance(value, dict):
        raise Bad(f'{where}: not a JSON object')
    missing = sorted(set(required) - set(value))
    extra = sorted(set(value) - set(required) - set(optional))
    if missing or extra:
        raise Bad(f'{where}: ' + '; '.join([f'missing {k!r}' for k in missing] + [f'unknown key {k!r}' for k in extra]))


def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.datetime.fromisoformat(value[:-1] + '+00:00' if value.endswith('Z') else value)
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return t.astimezone(datetime.timezone.utc).replace(microsecond=0)


def iso(t):
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')


def clock(seconds):
    if seconds is None:
        return '-'
    sign = '-' if seconds < 0 else ''
    m, s = divmod(abs(seconds), 60)
    return f'{sign}{m}:{s:02d}'


def read_log(path):
    steps = []
    for n, raw in enumerate(read_text(path).splitlines(), 1):
        if not raw.strip():
            continue
        where = f'{path.name} line {n}'
        try:
            line = json.loads(raw, object_pairs_hook=no_repeats)
        except ValueError as e:
            raise Bad(f'{where}: not JSON ({e})') from None
        exact_keys(where, line, LOG_KEYS - {'failure'}, {'failure'})
        at = parse_time(line.get('at'))
        if at is None:
            raise Bad(f'{where}: "at" is not a time with a zone')
        if line.get('step') not in STEPS:
            raise Bad(f'{where}: unknown step {line.get("step")!r}')
        if line.get('waits_on') not in WAITS:
            raise Bad(f'{where}: unknown wait {line.get("waits_on")!r}; one of {", ".join(WAITS)}')
        failure = line.get('failure')
        if 'failure' in line and not (isinstance(failure, str) and failure.strip()):
            raise Bad(f'{where}: "failure" is not text')
        if steps and at < steps[-1]['at']:
            raise Bad(f'{where}: earlier than the line before it')
        steps.append({'at': at, 'step': line['step'], 'waits_on': line['waits_on'], 'failure': failure})
    return steps


def read_json(path):
    text = read_text(path)
    decoder = json.JSONDecoder(object_pairs_hook=no_repeats)

    def value_at(i):
        try:
            return decoder.raw_decode(text, i)
        except json.JSONDecodeError as e:
            raise Bad(f'{path.name} line {e.lineno}: not JSON ({e.msg})') from None
        except ValueError as e:
            raise Bad(f'{path.name} line {line(i)}: not JSON ({e})') from None

    def skip(i):
        while i < len(text) and text[i] in ' \t\r\n':
            i += 1
        return i

    def line(i):
        return text.count('\n', 0, i) + 1

    out, i = [], skip(0)
    if text[i:i + 1] == '[':
        i = skip(i + 1)
        while i < len(text) and text[i] != ']':
            start = i
            value, i = value_at(i)
            out.append((line(start), value))
            i = skip(i)
            if text[i:i + 1] == ',':
                comma, i = i, skip(i + 1)
                if text[i:i + 1] == ']':
                    raise Bad(f'{path.name} line {line(comma)}: not JSON (a comma before ])')
            elif text[i:i + 1] != ']':
                raise Bad(f'{path.name} line {line(i)}: not JSON (expected , or ])')
        if skip(i + 1) != len(text):
            raise Bad(f'{path.name} line {line(skip(i + 1))}: not JSON (extra data)')
        return out
    while i < len(text):
        start = i
        value, i = value_at(i)
        out.append((line(start), value))
        i = skip(i)
    return out


def issue(where, url, number):
    m = ISSUE_URL.fullmatch(url) if isinstance(url, str) else None
    if m is None or int(m.group(2)) != number:
        raise Bad(f'{where}: "url" is not the GitHub issue URL of #{number}')
    return m.group(1).lower(), number


def record(name, n, value):
    where, fields = f'{name} line {n}', FIELDS[name]
    exact_keys(where, value, ('number',) + fields)
    if not isinstance(value.get('number'), int) or isinstance(value.get('number'), bool):
        raise Bad(f'{where}: "number" is not a number')
    out = {'number': value['number']}
    for field in fields:
        if field in ('closingIssuesReferences', 'url'):
            continue
        if field == 'mergedAt' and value.get(field) is None:
            out[field] = None
            continue
        t = parse_time(value.get(field))
        if t is None:
            raise Bad(f'{where}: "{field}" is not a time with a zone')
        out[field] = t
    if 'closingIssuesReferences' in fields:
        refs = value.get('closingIssuesReferences')
        if not isinstance(refs, list) or not all(isinstance(r, dict) and isinstance(r.get('number'), int)
                                                 and not isinstance(r.get('number'), bool) for r in refs):
            raise Bad(f'{where}: "closingIssuesReferences" is not a list of issues')
        out['closes'] = {issue(f'{where}: a closing reference', r.get('url'), r['number']) for r in refs}
    if 'url' in fields:
        out['issue'] = issue(where, value['url'], out['number'])
    return out


def read_github(run_dir, recorded):
    if not recorded:
        present = [name for name in GITHUB if (run_dir / name).exists()]
        if present:
            raise Bad(f'{present[0]}: present; --no-github is only for a run that stopped before the spec')
        return None, [], []
    spec = read_json(run_dir / 'spec.json')
    if len(spec) != 1 or isinstance(spec[0][1], list):
        raise Bad(f'spec.json line {spec[0][0] if spec else 1}: not one JSON object')
    spec = record('spec.json', *spec[0])
    tickets = [record('tickets.json', n, v) for n, v in read_json(run_dir / 'tickets.json')]
    prs = [record('prs.json', n, v) for n, v in read_json(run_dir / 'prs.json')]
    issues = {t['issue'] for t in tickets}
    fleet = [pr for pr in prs if pr['closes'] & issues]
    return spec, tickets, fleet


def report(run_dir, recorded=True):
    steps = read_log(run_dir / LOG)
    spec, tickets, fleet = read_github(run_dir, recorded)
    events = [(spec['createdAt'], f'spec #{spec["number"]} created')] if spec else []
    events += [(t['createdAt'], f'ticket #{t["number"]} created') for t in tickets]
    events += [(pr['createdAt'], f'pull request #{pr["number"]} created') for pr in fleet]
    events += [(pr['mergedAt'], f'pull request #{pr["number"]} merged') for pr in fleet if pr['mergedAt']]
    events.sort(key=lambda e: e[0])

    start = next((s['at'] for s in steps if s['step'] == 'install'), None)
    merged = sorted((pr for pr in fleet if pr['mergedAt']), key=lambda pr: pr['mergedAt'])
    first = merged[0] if merged else None
    reason = None
    if start is None:
        reason = 'no install line in the step log'
    elif spec is None:
        reason = 'the run stopped before the spec was created'
    elif first is None:
        reason = 'no fleet pull request has merged' if fleet else 'no fleet pull request'
    stop = first['mergedAt'] if first else None
    after = [s for s in steps if stop and s['at'] > stop]
    steps = [s for s in steps if not (stop and s['at'] > stop)]
    origin = start or (steps[0]['at'] if steps else None)

    def since(t):
        return None if origin is None else int((t - origin).total_seconds())

    rows = []
    for i, s in enumerate(steps):
        end = steps[i + 1]['at'] if i + 1 < len(steps) else stop
        rows.append({'step': s['step'], 'at': iso(s['at']), 'start_seconds': since(s['at']),
                     'length_seconds': None if end is None else int((end - s['at']).total_seconds()),
                     'waits_on': s['waits_on'], 'failure': s['failure']})
    return {
        'clock_start': iso(start) if start else None,
        'stop': iso(stop) if stop else None,
        'stop_pull_request': first['number'] if first else None,
        'total_seconds': None if reason else since(stop),
        'no_total_reason': reason,
        'timer_waits': [s['step'] for s in steps if s['waits_on'] == 'timer'],
        'after_stop': [{'step': s['step'], 'at': iso(s['at']), 'waits_on': s['waits_on']} for s in after],
        'steps': rows,
        'github': [{'event': name, 'at': iso(t), 'start_seconds': since(t)} for t, name in events],
    }


def table(r):
    out = ['| Step | Start | Length | Waits on | Failure |', '| --- | --- | --- | --- | --- |']
    for s in r['steps']:
        failure = ' '.join((s['failure'] or '-').split()).replace('|', '\\|')
        out.append(f'| {s["step"]} | {clock(s["start_seconds"])} | {clock(s["length_seconds"])} '
                   f'| {s["waits_on"]} | {failure} |')
    out += ['', '| GitHub | At |', '| --- | --- |']
    out += [f'| {e["event"]} | {clock(e["start_seconds"])} |' for e in r['github']]
    start = f'{r["clock_start"]} (the install line)' if r['clock_start'] else 'none'
    stop = f'{r["stop"]} (pull request #{r["stop_pull_request"]} merged)' if r['stop'] else 'none'
    total = clock(r['total_seconds']) if r['no_total_reason'] is None else f'none: {r["no_total_reason"]}'
    out += ['', f'Clock: {start} to {stop}', f'Total: {total}',
            f'Timer waits: {", ".join(r["timer_waits"]) or "none"}']
    if r['after_stop']:
        out.append('Marked after the clock stopped: ' + ', '.join(s['step'] for s in r['after_stop']))
    return '\n'.join(out) + '\n'


def mark(run_dir, step, waits_on, failure, at):
    if step not in STEPS:
        raise Bad(f'unknown step {step!r}; one of: {", ".join(STEPS)}')
    if waits_on not in WAITS:
        raise Bad(f'unknown wait {waits_on!r}; one of: {", ".join(WAITS)}')
    t = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0) if at is None else parse_time(at)
    if t is None:
        raise Bad(f'--at {at!r} is not a time with a zone')
    if failure is not None and not failure.strip():
        raise Bad('--failure is empty')
    line = {'at': iso(t), 'step': step, 'waits_on': waits_on}
    if failure is not None:
        line['failure'] = failure
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(line) + '\n')
    print(f'{iso(t)} {step} (waits on {waits_on})')


def main(argv):
    p = argparse.ArgumentParser(prog='bench.py', description='The first-fleet bench.')
    sub = p.add_subparsers(dest='command', required=True)
    m = sub.add_parser('mark', help="append one timed line to the run's step log")
    m.add_argument('run_dir', type=pathlib.Path)
    m.add_argument('step', help='one of: ' + ', '.join(STEPS))
    m.add_argument('waits_on', help='one of: ' + ', '.join(WAITS))
    m.add_argument('--failure', help='what went wrong in this step')
    m.add_argument('--at', help='the time, ISO 8601 with a zone (default: now)')
    r = sub.add_parser('report', help='print the step table')
    r.add_argument('run_dir', type=pathlib.Path)
    r.add_argument('--json', action='store_true', help='print the same as JSON')
    r.add_argument('--no-github', action='store_true',
                   help='the run stopped before the spec was created: report the marks alone')
    a = p.parse_args(argv)
    try:
        if a.command == 'mark':
            mark(a.run_dir, a.step, a.waits_on, a.failure, a.at)
        else:
            result = report(a.run_dir, recorded=not a.no_github)
            sys.stdout.write(json.dumps(result, indent=2) + '\n' if a.json else table(result))
    except Bad as e:
        print(f'bench: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
