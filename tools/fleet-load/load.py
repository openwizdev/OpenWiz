#!/usr/bin/env python3
"""FA3: deterministic skill follower at fleet.sh's fake-command seam.

No network, dependencies, sleeps or agents. The installed Rust tick is outside
the legacy profile. --fleet permits a candidate script without touching production.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import threading
from collections import Counter
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SCRIPTS = HERE / '../../skills/launch-fleet/scripts'
START = 1793534400  # Synthetic 2026-11-01 12:00 UTC.
TICK = 600
SPECS = [100, 200, 300, 400, 500]
TICKETS = list(range(1001, 1101))


def extension(name):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


NOTIFICATIONS = {'findings', 'CI failed', 're-check', 'check review'}


def instruction(line):
    match = re.match(r'(review|re-check|findings|CI failed|check review|merge) #([0-9]+) for #([0-9]+) at ([0-9a-f]{40})(?=: |$)', line)
    assert match, f'invalid head-bound instruction: {line}'
    action, pull, ticket, head = match.groups()
    return action, int(pull), int(ticket), head


def notification(action, pull, ticket, head):
    return f'{action} #{pull} for #{ticket} at {head}'


def saved_probes(cache, spec):
    """The probe endpoints of GI1's saved unchanged-spec entry (#2543), or None without one."""
    try:
        entry = json.loads((cache / f'unchanged-spec-{spec}.json').read_text())
        return [p['endpoint'] for p in json.loads(entry['body'])['probes']]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def backoff_gate(calls, saved):
    """S4: a back-off tick makes exactly one question, its first GraphQL read, last.

    GI1 (#2543) may probe before it: then exactly the saved entry's endpoints, each
    once, plus only the later pages their responses linked to, in that order. No other
    read, no repeat, no write. Without a saved entry (or one fleet.sh did not use),
    the GraphQL read is the only call.
    """
    if not calls or calls[-1]['tool'] != 'gh' or calls[-1]['args'][:2] != ['api', 'graphql']:
        return False
    probes = calls[:-1]
    if not probes:
        return True
    if not saved:
        return False
    first, linked = [], set()
    for c in probes:
        args = c['args']
        if (c['tool'] != 'gh' or args[:4] != ['api', '--include', '-H', args[3]] or not args[3].startswith('Accept: ')
                or len(args) not in (5, 7) or (len(args) == 7 and (args[4] != '-H' or not args[5].startswith('If-None-Match: ')))):
            return False
        endpoint = args[-1]
        if endpoint in linked:
            linked.discard(endpoint)  # a later page: a previous response's next link named it
        elif endpoint.startswith('repositories/'):
            return False  # a later page no earlier response linked to
        else:
            first.append(endpoint)
        if c.get('next'):
            linked.add(c['next'])
    return sorted(first) == sorted(saved) and len(set(saved)) == len(saved)


class Workload:
    def __init__(self, root, fleet, scaled=False):
        self.scaled = scaled
        self.root, self.fleet = Path(root), str(fleet)
        self.path = self.root / 'world.json'
        self.events = self.root / 'events.jsonl'
        self.now = START
        self.deadline = time.monotonic() + 600
        self.ticks = []
        self.tasks = []
        self.builders = {}
        self.reviewers = {}
        self.review_starts = {}
        self.quiet = []
        self.wakes = []
        self.env = dict(os.environ)
        # Do not let ambient fixture fault injection alter this workload.
        for key in list(self.env):
            if key.startswith(('FAKE_GH_', 'LAUNCH_FLEET_', 'LOAD_')):
                del self.env[key]
        bindir = self.root / 'bin'
        bindir.mkdir()
        for command in ('gh', 'room-cli'):
            wrapper = bindir / command
            wrapper.write_text('#!/bin/sh\nexec ' + shlex.join([sys.executable, '-I', str(HERE / 'fake.py'), command]) + ' "$@"\n')
            wrapper.chmod(0o700)
        if scaled:
            self.env['LOAD_SCALE'] = '1'
        self.env.update(PATH=f'{bindir}:{self.env["PATH"]}', GH_REPO='synthetic-owner/synthetic-repo',
                        FAKE_GH_WORLD=str(self.path), FAKE_GH_LOG=str(self.root / 'gh.log'),
                        LAUNCH_FLEET_CACHE=str(self.root / 'cache'), LAUNCH_FLEET_STATE=str(self.root / 'private-routing.json'),
                        LAUNCH_FLEET_REVISION=str((SCRIPTS / 'fixtures/revision.sh').resolve()),
                        LOAD_EVENTS=str(self.events), LOAD_FLEET='setup', LAUNCH_FLEET_NOW=str(self.now))
        settings = json.loads((SCRIPTS / 'fixtures/check.json').read_text())['files']
        self.world = dict(repo='synthetic-owner/synthetic-repo', default='main', files=settings,
                          issues=[], pulls=[], refs=[], _threads={}, _next=10000)
        for spec in SPECS:
            members = TICKETS[(spec // 100 - 1) * 20:spec // 100 * 20]
            rows = []
            for number in members:
                blockers = [number - 1] if number == members[-1] else []
                self.world['issues'].append(dict(number=number, title=f'Synthetic ticket {number}',
                    state='OPEN', parent=spec, labels=['ready-for-agent'], blockedBy=blockers,
                    body=f'## Owned paths\n\n`synthetic/{number}/`\n\n## Relies on\n\nnothing\n', comments=[]))
                rows.append(f'| #{number} | Synthetic ticket {number} | {"#" + str(number - 1) if blockers else "none"} | ready-for-agent |')
            body = ('**Plan graph approved by Robin, 2026-11-01, revision 1:** "approve"\n\n'
                    '| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n'
                    + '\n'.join(rows) + '\n\nFingerprint: `@@FP@@`')
            self.world['issues'].append(dict(number=spec, title=f'Synthetic spec {spec}', state='OPEN',
                parent=None, labels=[], blockedBy=[], body='Synthetic spec; no live check.', comments=[
                    dict(id=spec, at=stamp(START - 7200), body=body),
                    dict(id=spec + 1, at=stamp(START - 3600),
                         body=f'launch-fleet: fleet active, loop loop_fake{spec}')]))
        self.save()
        for spec in SPECS:
            revision = self.command(['sh', str(SCRIPTS / 'fixtures/revision.sh'), str(spec)])
            self.item(spec)['comments'][0]['body'] = self.item(spec)['comments'][0]['body'].replace('@@FP@@', digest(revision))
        self.save()

    def item(self, number):
        return next(x for x in self.world['issues'] + self.world['pulls'] if x['number'] == number)

    def save(self):
        routes = {f'builder:{n}': value[0] for n, value in self.builders.items()}
        routes.update({f'review:{n + 1000}:{self.review_starts[n]}': thread for n, thread in self.reviewers.items()})
        (self.root / 'private-routing.json').write_text(json.dumps({'repo': 'synthetic-owner/synthetic-repo', 'threads': routes}))
        self.path.write_text(json.dumps(self.world))

    def timeout(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('FA3 exceeded its ten-minute workload bound')
        return min(60, remaining)

    def command(self, args):
        self.save()
        result = subprocess.run(args, env=self.env, text=True, capture_output=True, timeout=self.timeout())
        self.world = json.loads(self.path.read_text())
        assert result.returncode == 0, f'command failed {args[:3]}: {result.stderr[:2000]}'
        return result.stdout

    def note(self, number, body):
        assert not re.search(r'\bthr_[A-Za-z0-9]', body), 'P4 thread in a public record'
        return int(self.command(['gh', 'issue', 'comment', str(number), '--body', body]))

    def edit(self, ident, body):
        assert not re.search(r'\bthr_[A-Za-z0-9]', body), 'P4 thread in an edited public record'
        self.command(['gh', 'api', '--method', 'PATCH',
            f'repos/synthetic-owner/synthetic-repo/issues/comments/{ident}', '-f', f'body={body}'])

    def room(self, *args):
        return self.command(['room-cli', 'thread', *map(str, args)])

    def later(self, minutes, action, number, head=None):
        self.tasks.append((self.now + minutes * 60, self.env['LOAD_FLEET'], action, number, head))

    def agent(self, role, number, prompt=None):
        args = ['spawn', '--parent-self', '--project', 'synthetic-project', '--title', (f'#{number}: Synthetic' if role == 'builder' else f'Review #{number + 1000} at {self.item(number + 1000)["head"][:8]}')]
        if prompt is not None:
            args += ['--prompt', prompt]
        response = self.room(*args)
        return json.loads(response)['id']

    def checks(self, failed=False):
        return [dict(name=name, status='COMPLETED', conclusion='FAILURE' if failed else 'SUCCESS', run=stamp(self.now))
                for name in ('build', 'test')]

    def advance(self):
        due = [task for task in self.tasks if task[0] <= self.now]
        self.tasks = [task for task in self.tasks if task[0] > self.now]
        for when, caller, action, number, head in due:
            self.env['LOAD_FLEET'] = caller
            agent = None
            if self.scaled:
                thread = self.reviewers[number] if action == 'verdict' else self.builders[number][0]
                agent = self.world['_threads'][thread]
                if agent['execution'] == 'queued':
                    self.tasks.append((when, caller, action, number, head))
                    continue
                assert agent['execution'] == 'running', 'scheduled synthetic work is not running'
            if action == 'open':
                self.world['refs'].append(f'room/{number}-synthetic')
                self.world['pulls'].append(dict(number=number + 1000, state='OPEN', draft=False, base='main',
                    head=digest(f'{number}:initial')[:40], committed=stamp(self.now), headline=f'#{number}: green',
                    closes=[number], rollup='SUCCESS', checks=self.checks(number % 10 == 5),
                    mergedAt=None, updatedAt=stamp(self.now), comments=[],
                    files=[dict(filename=f'synthetic/{number}/code.rs', status='modified')]))
            elif action == 'verdict':
                pull = self.item(number + 1000)
                verdict = 'CHANGES' if number % 5 == 3 and not any(c['body'].startswith('VERDICT: CHANGES') for c in pull['comments']) else 'APPROVE'
                assert isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}', head), 'review task has no assigned head'
                self.note(pull['number'], f'VERDICT: {verdict} at {head}')
            elif action == 'fix':
                pull = self.item(number + 1000)
                pull.update(head=digest(f'{number}:fixed')[:40], committed=stamp(self.now), checks=self.checks())
            elif action == 'ci':
                self.item(number + 1000)['checks'] = self.checks()
            else:
                raise AssertionError(action)
            if self.scaled:
                self.record('transition', action=action, ticket=number, head=head,
                            verdict=verdict if action == 'verdict' else None)
                agent = self.world['_threads'][thread]
                agent['execution'] = 'idle'
                self.record('execution-end', thread=thread, role=agent['role'], ticket=number)
        if self.scaled:
            running = sum(a['execution'] == 'running' for a in self.world['_threads'].values())
            for thread, agent in self.world['_threads'].items():
                if agent['execution'] != 'queued' or running == 50:
                    continue
                agent['execution'] = 'running'
                running += 1
                self.record('execution-start', thread=thread, role=agent['role'], ticket=agent['ticket'])
                # A newly admitted job occupies a positive execution interval.
                updated = []
                for when, caller, action, number, head in self.tasks:
                    owner = self.reviewers.get(number) if action == 'verdict' else self.builders.get(number, (None,))[0]
                    if owner == thread:
                        duration = 2400 if action == 'open' and number % 20 == 1 else 600
                        when = self.now + duration
                    updated.append((when, caller, action, number, head))
                self.tasks = updated
        self.save()

    def target(self, line):
        match = re.search(r'\bthread (thr_[A-Za-z0-9_]+)', line)
        assert match, f'S1 owner: due line has no thread target: {line}'
        return match[1]

    def dispatch(self, line):
        # Only observed script lines may cause fleet actions. Unknown due work
        # fails instead of silently disappearing from the load test.
        kind, number = re.match(r'([A-Za-z -]+) #([0-9]+)', line).groups()
        number = int(number)
        if kind in NOTIFICATIONS or kind in ('review', 'merge'):
            _, number, ticket, head = instruction(line)
        if kind == 'start':
            claim = self.note(number, 'launch-fleet: starting')
            thread = self.agent('builder', number)
            self.builders[number] = (thread, claim)
            self.edit(claim, 'launch-fleet: started')
            quiet = number % 20 == 1
            if quiet:
                self.quiet.append(dict(role='builder', ticket=number, thread=thread, since=self.now))
            self.later(40 if quiet else 10, 'open', number)
        elif kind == 'check start':
            _, claim = self.builders[number]
            thread = self.target(line)
            self.room('output', thread)
            if 'no branch 30 minutes' not in line:
                self.edit(claim, f'launch-fleet: start checked, branch room/{number}-synthetic')
        elif kind in ('review', 're-check'):
            claim = self.note(number, f'launch-fleet: review starting {head}')
            if kind == 'review':
                thread = self.agent('reviewer', ticket, notification(kind, number, ticket, head))
                self.reviewers[ticket] = thread
                self.review_starts[ticket] = head
            else:
                thread = self.target(line)
                self.room('tell', thread, notification(kind, number, ticket, head))
            self.edit(claim, f'launch-fleet: {"review started" if kind == "review" else "re-check sent"} {head}')
            if ticket % 20 == 2 and kind == 'review':
                self.quiet.append(dict(role='reviewer', ticket=ticket, thread=thread, since=self.now))
            else:
                self.later(10, 'verdict', ticket, head)
        elif kind in ('findings', 'CI failed'):
            self.room('tell', self.target(line), notification(kind, number, ticket, head))
            self.note(number, f'launch-fleet: {"findings sent" if kind == "findings" else "CI failure sent"} {head}')
            self.later(10, 'fix' if kind == 'findings' else 'ci', ticket)
        elif kind == 'check review':
            thread = self.target(line)
            self.room('output', thread)
            self.room('tell', thread, notification(kind, number, ticket, head))
            self.note(number, f'launch-fleet: review told again {head}')
            self.later(10, 'verdict', ticket, head)
        elif kind == 'merge':
            self.command(['gh', 'pr', 'merge', str(number), '--merge', '--match-head-commit', head])
            if self.scaled:
                self.env['LOAD_READBACK'] = '1'
                try:
                    result = json.loads(self.command(['gh', 'api', f'repos/{self.world["repo"]}/pulls/{number}']))
                    assert result['merged'] and result['head']['sha'] == head, 'S6 unverified merge'
                finally:
                    self.env.pop('LOAD_READBACK')
        elif kind == 'spec done':
            self.note(number, 'launch-fleet: spec summary: synthetic fixture completed; no live check required')
        elif kind == 'close spec':
            self.command(['gh', 'issue', 'close', str(number)])
        elif kind == 'archive':
            for thread in line.split('; archive ', 1)[1].split(', '):
                self.room('archive', thread)
            self.note(number, 'launch-fleet: archived')
        else:
            raise AssertionError(f'unhandled due line: {line}')

    def tick(self, spec, low=False):
        self.env.update(LOAD_FLEET=f'thr_synfleet{spec}', LAUNCH_FLEET_NOW=str(self.now))
        self.env['FAKE_GH_REMAINING'] = '1249' if low else '5000'
        self.save()
        # fleet.sh keeps its cache per repository: $LAUNCH_FLEET_CACHE/<owner>/<name>.
        saved = saved_probes(Path(self.env['LAUNCH_FLEET_CACHE']) / self.world['repo'], spec) if low else None
        before = len(self.read_events())
        began = time.monotonic()
        result = subprocess.run(['sh', self.fleet, 'spec', str(spec)], env=self.env,
                                text=True, capture_output=True, timeout=self.timeout())
        wall_ms = round((time.monotonic() - began) * 1000, 3)
        assert result.returncode == 0, f'fleet spec {spec}: {result.stderr}'
        self.world = json.loads(self.path.read_text())
        calls = self.read_events()[before:]
        if low:
            assert not result.stdout and re.fullmatch(r'fleet.sh: backing off: [^\n]+\n', result.stderr), result
            assert backoff_gate(calls, saved), \
                'S4 back-off made extra calls'
            points = calls[-1]['cost']
        else:
            match = re.fullmatch(r'fleet.sh: used ([0-9]+) GitHub points in ([0-9]+) questions, [0-9]+ unchanged; (?:5000 of 5000 left|no GraphQL read)\n', result.stderr)
            assert match, result.stderr
            points, questions = map(int, match.groups())
            assert questions == len(calls), f'S4 question accounting: {questions} != {len(calls)}'
            assert points == sum(c['cost'] for c in calls), 'S4 point accounting'
        self.ticks.append(dict(now=self.now, spec=spec, points=points, questions=len(calls), low=low,
                               lines=result.stdout.splitlines(), first=before, beyond=before + len(calls),
                               wall_ms=wall_ms))
        for line in result.stdout.splitlines():
            self.dispatch(line)

    def wake(self):
        self.save()
        # GI2 (#2544): a wake naming a ticket of a spec with a fleet thread defers
        # to that fleet with exactly one line, its own loop's run, and nothing else.
        spec = self.item(1004)['parent']
        owned = f'wake fleet #{spec}: room-cli loop run loop_fake{spec}\n'
        gate = threading.Barrier(2)
        def reader(index):
            env = dict(self.env, LOAD_FLEET='event-wake', FAKE_GH_REMAINING='5000',
                       LAUNCH_FLEET_CACHE=str(self.root / f'wake-cache-{index}'))
            gate.wait(timeout=5)
            began = time.monotonic()
            result = subprocess.run(['sh', self.fleet, 'wake', '1004'], env=env,
                                    text=True, capture_output=True, timeout=self.timeout())
            ended = time.monotonic()
            assert result.returncode == 0 and result.stdout == owned, f'event wake bypassed fleet ownership: {result}'
            return dict(start=began, end=ended)
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(reader, range(2)))
        assert max(i['start'] for i in outcomes) < min(i['end'] for i in outcomes), 'concurrent wake readers did not overlap'
        self.wakes.append(dict(now=self.now, intervals=outcomes))

    def record(self, kind, **fields):
        with self.events.open('a') as log:
            log.write(json.dumps(dict(tool='workload', kind=kind, now=self.now, **fields)) + '\n')

    def read_events(self):
        return [json.loads(line) for line in self.events.read_text().splitlines()] if self.events.exists() else []

    def run(self):
        # Bounded virtual schedule: nine 10-minute ticks expose replay
        # errors and quiet agents without wall-clock waiting.
        installed = extension('installed').run(self.world) if self.scaled else None
        identity = extension('scale').identity(self.fleet, installed) if self.scaled else None
        if self.scaled:
            self.item(1004)['labels'].append('held')
            self.record('hold', ticket=1004, held=True)
        for tick in range(30 if self.scaled else 9):
            self.now = START + tick * TICK
            self.env['LAUNCH_FLEET_NOW'] = str(self.now)
            if self.scaled and tick == 1:
                self.item(1004)['labels'].remove('held')
                self.record('hold', ticket=1004, held=False)
            self.advance()
            if self.scaled and tick in (0, 3):
                self.wake()
            if self.scaled:
                # Independent shared consumers, with no associated CLI call.
                with self.events.open('a') as log:
                    log.write(json.dumps(dict(tool='shared', kind='http', now=self.now,
                        http=[dict(api='rest', page=1, cost=0, rows=1), dict(api='graphql', page=1, cost=2, rows=1)],
                        http_expected=2, paginated=False)) + '\n')
            for spec in SPECS:
                if self.item(spec)['state'] == 'OPEN':
                    self.tick(spec, low=tick == 2)
        return dict(tickets=TICKETS, specs=SPECS, events=self.read_events(), ticks=self.ticks,
                    quiet=self.quiet, final=self.world, installed=installed, identity=identity, wakes=self.wakes,
                    config=identity['candidate']['config'] if self.scaled else 'legacy',
                    candidate=identity['candidate']['revision'] if self.scaled else digest(Path(self.fleet).read_text()))


def run(fleet=None, scaled=False):
    with tempfile.TemporaryDirectory(prefix='fa3-') as root:
        return Workload(root, fleet or SCRIPTS / 'fleet.sh', scaled=scaled).run()


def verify(report):
    events, tickets = report['events'], report['tickets']
    assert tickets == TICKETS and report['specs'] == SPECS, 'S2 workload identity changed'
    spawns = [e for e in events if e['kind'] == 'spawn']
    builders = [e for e in spawns if e['role'] == 'builder']
    counts = Counter(e['ticket'] for e in builders)
    assert all(n == 1 for n in counts.values()), 'S2 duplicate builder start'
    assert set(counts) == set(tickets) and len(tickets) == 100, f'S2 missed: expected 100 builder starts, got {len(counts)}'
    assert all(n == 1 for n in Counter((e['role'], e['ticket']) for e in spawns).values()), 'S2 duplicate agent start'
    reviewers = [e for e in spawns if e['role'] == 'reviewer']
    assert Counter(e['ticket'] for e in reviewers) == Counter({n: 1 for n in tickets}), 'S2 missed reviewer'
    parents = {x['number']: x['parent'] for x in report['final']['issues'] if x['number'] in tickets}
    for e in spawns:
        assert e['fleet'] == f'thr_synfleet{parents[e["ticket"]]}', 'S1 owner: ticket started by another fleet'
    threads = {(e['role'], e['ticket']): e['thread'] for e in spawns}
    expected_notifications = Counter()
    for tick in report['ticks']:
        for line in tick.get('lines', []):
            action = line.split(' #', 1)[0]
            if action in ('findings', 'CI failed', 're-check', 'check review', 'check start'):
                number = int(re.search(r'(?:for #|check start #)([0-9]+)', line)[1])
                target = re.search(r'\bthread (thr_[A-Za-z0-9_]+)', line)
                role = 'reviewer' if action in ('re-check', 'check review') else 'builder'
                assert target and target[1] == threads[(role, number)], 'S1 target: due line names the wrong agent'
                if action in NOTIFICATIONS:
                    request = instruction(line)
                    expected_notifications[(*request, f'thr_synfleet{tick["spec"]}', target[1], tick['now'])] += 1
    owners = {e['thread']: e['fleet'] for e in spawns}
    assert len(owners) == len(spawns), 'S2 duplicate agent identity'
    for e in events:
        if e['kind'] in ('tell', 'output', 'archive'):
            assert owners.get(e['thread']) == e['fleet'], 'S1 owner: action belongs to another fleet'
    for quiet in report['quiet']:
        notices = [e['now'] for e in events if e['kind'] == 'output' and e['thread'] == quiet['thread']
                   and e['now'] >= quiet['since']]
        assert notices and min(notices) <= quiet['since'] + 1800, f'S3 quiet {quiet["role"]}: not noticed within 30 minutes'
    assert Counter(q['role'] for q in report['quiet']) == {'builder': 5, 'reviewer': 5}, 'S3 missing planted stalls'
    for tick in report['ticks']:
        calls = events[tick['first']:tick['beyond']]
        assert all(e['tool'] == 'gh' and e['kind'] == 'command' for e in calls), 'S4 budget: invalid read interval'
        assert tick['questions'] == len(calls), 'S4 budget: question accounting'
        assert tick['points'] == sum(e['cost'] for e in calls), 'S4 budget: cost accounting'
        hour = sum(t['points'] for t in report['ticks'] if tick['now'] - 3600 < t['now'] <= tick['now'])
        assert hour <= 1250, f'S4 budget: {hour} points/hour > 1250'
    merges = Counter(e['ticket'] for e in events if e['kind'] == 'merge')
    assert merges == Counter({n: 1 for n in tickets}), 'S2 missed merge or duplicate merge'
    merged_at = {e['ticket']: e['now'] for e in events if e['kind'] == 'merge'}
    completed = set()
    for e in events:
        if e['kind'] == 'merge':
            assert e['ci_green'] and e['approved'], 'S2 unsafe merge: missing CI or approval'
            completed.add(e['ticket'])
        elif e['kind'] == 'archive':
            ticket = next(s['ticket'] for s in spawns if s['thread'] == e['thread'])
            assert ticket in completed and e['now'] >= merged_at[ticket], 'S1 archive: agent archived before completion'
    archives = Counter(e['thread'] for e in events if e['kind'] == 'archive')
    assert archives == Counter({e['thread']: 1 for e in spawns}), 'S1 archive: finished agent missing or archived twice'
    assert len([e for e in spawns if e['role'] == 'reviewer']) == 100, 'S2 missed reviewer'
    spawned = {e['thread']: e for e in spawns}
    actual_notifications = Counter()
    tells = []
    for e in events:
        if e['kind'] != 'tell':
            continue
        args = e['args']
        assert e['tool'] == 'room-cli' and len(args) == 4 and args[:2] == ['thread', 'tell'] and args[2] == e['thread'], 'S1 notification: command/event recipient mismatch'
        source = spawned[e['thread']]
        assert (e['role'], e['ticket']) == (source['role'], source['ticket']), 'S1 notification: command/event agent mismatch'
        request = instruction(args[3])
        action, pull, ticket, head = request
        role = 'reviewer' if action in ('re-check', 'check review') else 'builder'
        assert action in NOTIFICATIONS and args[3] == notification(*request), 'S1 notification: invalid message'
        assert (source['role'], source['ticket']) == (role, ticket), 'S1 notification: wrong agent for requested ticket/role'
        actual_notifications[(*request, e['fleet'], e['thread'], e['now'])] += 1
        tells.append(args[3])
    assert actual_notifications == expected_notifications, 'S1 notification: missing, duplicate or mismatched action/PR/ticket/head/fleet/recipient'

    assert sum(s.startswith('findings ') for s in tells) == 20, 'S1 findings missing'
    assert sum(s.startswith('re-check ') for s in tells) == 20, 'S1 re-checks missing'
    assert sum(s.startswith('CI failed ') for s in tells) == 10, 'S1 CI notifications missing'
    assert len([t for t in report['ticks'] if t['low']]) == 5, 'S4 low allowance missing'
    assert all(x['state'] == 'CLOSED' for x in report['final']['issues']), 'S2 unfinished tickets/specs'
    # Blocked last ticket of each spec must wait for its predecessor's merge.
    for n in range(1020, 1101, 20):
        started = next(e['now'] for e in builders if e['ticket'] == n)
        merged = next(e['now'] for e in events if e['kind'] == 'merge' and e['ticket'] == n - 1)
        assert started > merged, 'S2 started before blocker merged'


def plant(report, fault):
    events = report['events']
    if fault == 'duplicate':
        events.append(dict(next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'builder')))
    elif fault.startswith('quiet-'):
        role = fault.removeprefix('quiet-')
        thread = next(q['thread'] for q in report['quiet'] if q['role'] == role)
        report['events'] = [e for e in events if not (e['kind'] == 'output' and e['thread'] == thread)]
    elif fault == 'budget':
        tick = report['ticks'][0]
        events[tick['first']]['cost'] += 1251
        tick['points'] += 1251
    elif fault == 'missed':
        first = next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'builder')
        events.remove(first)
    elif fault == 'owner':
        next(e for e in events if e['kind'] == 'tell')['fleet'] = 'thr_synforeign'
    elif fault == 'target':
        tick = next(t for t in report['ticks'] if any(s.startswith('findings ') for s in t['lines']))
        line = next(s for s in tick['lines'] if s.startswith('findings '))
        ticket = int(re.search(r'for #([0-9]+)', line)[1])
        original = next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'builder' and e['ticket'] == ticket)
        wrong = next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'builder' and e['fleet'] == original['fleet'] and e['ticket'] != ticket)
        tick['lines'][tick['lines'].index(line)] = line.replace(original['thread'], wrong['thread'])
    elif fault in ('actual-findings-target', 'actual-recheck-role'):
        prefix = 'findings ' if fault == 'actual-findings-target' else 're-check '
        tell = next(e for e in events if e['kind'] == 'tell' and e['args'][3].startswith(prefix))
        if fault == 'actual-findings-target':
            wrong = next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'builder'
                         and e['fleet'] == tell['fleet'] and e['ticket'] != tell['ticket'])
        else:
            wrong = next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'builder'
                         and e['ticket'] == tell['ticket'])
        tell.update(thread=wrong['thread'], role=wrong['role'], ticket=wrong['ticket'], fleet=wrong['fleet'])
        tell['args'][2] = wrong['thread']
    elif fault == 'same-tick-archive':
        archive = next(e for e in events if e['kind'] == 'archive')
        ticket = next(e['ticket'] for e in events if e['kind'] == 'spawn' and e['thread'] == archive['thread'])
        merge = next(e for e in events if e['kind'] == 'merge' and e['ticket'] == ticket)
        archive['now'] = merge['now']
        a, m = events.index(archive), events.index(merge)
        events[m], events[a] = events[a], events[m]
    elif fault == 'point-cost':
        events[report['ticks'][0]['first']]['cost'] += 1251
    elif fault == 'start-owner':
        thread = next(e['thread'] for e in events if e['kind'] == 'spawn')
        for e in events:
            if e.get('thread') == thread:
                e['fleet'] = 'thr_synforeign'
    elif fault == 'review-label':
        next(e for e in events if e['kind'] == 'spawn' and e['role'] == 'reviewer')['ticket'] = 9999
    elif fault == 'early-archive':
        next(e for e in events if e['kind'] == 'archive')['now'] = START
    elif fault == 'unsafe-merge':
        next(e for e in events if e['kind'] == 'merge')['ci_green'] = False
    elif fault == 'archive':
        # Preserve offsets into the observed command stream while omitting
        # the archive effect; otherwise accounting fails before S1 can run.
        next(e for e in events if e['kind'] == 'archive')['kind'] = 'archive-omitted'
    else:
        raise ValueError(fault)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fleet', type=Path, default=SCRIPTS / 'fleet.sh')
    parser.add_argument('--verify-report', type=Path, help='check an existing trace without rerunning the workload')
    parser.add_argument('--report', type=Path, help='write the observed trace for downstream workload extensions')
    parser.add_argument('--plant', choices=['duplicate', 'quiet-builder', 'quiet-reviewer', 'budget', 'missed', 'owner', 'archive', 'point-cost', 'start-owner', 'review-label', 'early-archive', 'unsafe-merge', 'target', 'actual-findings-target', 'actual-recheck-role', 'same-tick-archive'])
    args = parser.parse_args()
    before = time.monotonic()
    report = json.loads(args.verify_report.read_text()) if args.verify_report else run(args.fleet)
    if args.plant:
        plant(report, args.plant)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    verify(report)
    print(f'PASS: 100 tickets, 5 specs, {len(report["ticks"])} spec ticks; '
          f'{sum(t["questions"] for t in report["ticks"])} counted GitHub questions; '
          f'{time.monotonic() - before:.1f}s (synthetic only)')


if __name__ == '__main__':
    main()
