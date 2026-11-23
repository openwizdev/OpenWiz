#!/usr/bin/env python3
import argparse
from collections import deque
import sys

LEASE = 2
CLAIMING = ('working', 'asking')
RELEASED = ('done', 'stopped')
AGENTS = (('builder 1', 'builder'), ('builder 2', 'builder'), ('fleet', 'fleet'))
MAX_NOTES = 4
FIXED_NOTES = 3
RUNS = {'atomic': (1, 1, 1), 'split': (2, 1), 'fixed': (2, 1)}

RULES = {
    'P1': 'never two live holders: a claim write succeeded but its note does not hold the claim',
    'P2': 'a lapsed holder took the ticket back from a newer one',
    'P3': 'a release was lost',
    'P4': 'a claim is neither held, released nor lapsed: two live notes of one kind',
    'P5': 'a heartbeat reopened a final note: a done or stopped note went live',
}

VARIANTS = {
    'no-post-fence': ('P1', 'a new note posts over a live holder and never reads back'),
    'older-only-fence': ('P2', 'the edit fence stops a note only for an older holder, not a newer one'),
    'edit-stopped': ('P3', 'the fence lets an agent edit its stopped note back to live'),
    'asking-not-claiming': ('P4', 'the writer counts only working notes as claiming, not asking ones'),
    'heartbeat-reopens': ('P5', 'a heartbeat writes working on every beat, whatever its read showed'),
}


def kind(agent):
    return AGENTS[agent][1]


def live(note):
    return note[1] in CLAIMING and note[2] < LEASE


def holder(notes, k, claiming=CLAIMING):
    return next((i for i, n in enumerate(notes)
                 if kind(n[0]) == k and n[1] in claiming and n[2] < LEASE), None)


def own(notes, agent):
    return max((i for i, n in enumerate(notes) if n[0] == agent), default=None)


def put(notes, i, agent, state):
    note = (agent, state, 0 if state in CLAIMING else LEASE)
    return notes[:i] + (note,) + notes[i + 1:]


class Model:
    def __init__(self, variant=None, writes='atomic'):
        self.variant, self.writes = variant, writes
        self.claiming = ('working',) if variant == 'asking-not-claiming' else CLAIMING
        self.agents = AGENTS if writes == 'atomic' else AGENTS[:2]
        self.max_notes = FIXED_NOTES if writes == 'fixed' else MAX_NOTES

    def initial(self):
        return ((), tuple((None,) * n for n in RUNS[self.writes]))

    def read(self, notes, agent):
        mine = own(notes, agent)
        return mine, (None if mine is None else notes[mine][1]), holder(notes, kind(agent), self.claiming)

    def edit(self, view, notes, agent, i, state, beat=False):
        _, mine_state, h = view
        if mine_state == 'stopped' and self.variant != 'edit-stopped':
            return None
        if h is not None and h != i and not (self.variant == 'older-only-fence' and h > i):
            return None
        if self.writes == 'fixed' and state in CLAIMING:
            return put(notes, i, agent, state), ('edited', i, state, notes[i], mine_state, beat)
        return put(notes, i, agent, state), None

    def heartbeat(self, view, notes, agent, i):
        state = 'working' if self.variant == 'heartbeat-reopens' else view[1]
        if state not in CLAIMING:
            return None
        return self.edit(view, notes, agent, i, state, beat=True)

    def post(self, view, notes, agent, state):
        if self.variant != 'no-post-fence' and view[2] is not None:
            return None
        notes = notes + ((agent, state, 0),)
        return notes, (None if self.variant == 'no-post-fence' else len(notes) - 1)

    def readback(self, notes, i):
        h = holder(notes, kind(notes[i][0]), self.claiming)
        if h is not None and h < i:
            return put(notes, i, notes[i][0], 'stopped'), 'lost claim'
        return notes, 'kept'

    def readback_edit(self, notes, pending):
        _, i, state, was, mine_state, _ = pending
        if was[1] in RELEASED and was[1] != mine_state and notes[i][1] in CLAIMING:
            return put(notes, i, notes[i][0], was[1]), f'puts the {was[1]} back'
        if notes[i][1] != state:
            return notes, None
        if any(j != i and kind(n[0]) == kind(notes[i][0]) and live(n) for j, n in enumerate(notes)):
            return put(notes, i, notes[i][0], 'stopped'), 'lost claim'
        return notes, 'kept'

    def writes_for(self, view, notes, agent):
        mine, mine_state, _ = view
        for state in CLAIMING + RELEASED:
            if mine is not None:
                yield f'edit note {mine} to {state}', self.edit(view, notes, agent, mine, state), mine, state, False
        if mine is not None:
            beat = self.heartbeat(view, notes, agent, mine)
            if beat is not None:
                yield f'heartbeat note {mine}', beat, mine, beat[0][mine][1], True
        if (mine is None or mine_state == 'stopped') and len(notes) < self.max_notes:
            for state in CLAIMING:
                yield f'post a {state} note', self.post(view, notes, agent, state), len(notes), state, False

    def steps(self, s):
        notes, runs = s
        idle = all(run is None for rs in runs for run in rs)
        if idle and any(n[1] in CLAIMING and n[2] < LEASE for n in notes):
            yield 'time passes', (tuple((a, st, min(age + 1, LEASE)) for a, st, age in notes), runs), []
        for agent, agent_runs in enumerate(runs):
            who = self.agents[agent][0]
            for r, run in enumerate(agent_runs):
                def with_run(new):
                    rs = list(agent_runs)
                    rs[r] = new
                    return tuple(tuple(rs) if a == agent else x for a, x in enumerate(runs))
                if self.writes == 'atomic':
                    view = self.read(notes, agent)
                elif run is None:
                    yield (f'{who} wake {r + 1} reads the ticket',
                           (notes, with_run(('read', self.read(notes, agent)))), [])
                    continue
                elif run[0] == 'read':
                    view = run[1]
                elif run[0] == 'edited':
                    after, how = self.readback_edit(notes, run[1])
                    events = [('settled', agent, run[1], after, how is None)] + (
                        [] if how is None else [('claimed', agent, run[1][1], notes, after)])
                    yield (f'{who} wake {r + 1} reads back note {run[1][1]}: {how or "not as written, fails"}',
                           (after, with_run(None)), events)
                    continue
                else:
                    after, how = self.readback(notes, run[1])
                    yield (f'{who} wake {r + 1} reads back note {run[1]}: {how}', (after, with_run(None)),
                           [('claimed', agent, run[1], notes, after)])
                    continue
                for label, result, i, state, beat in self.writes_for(view, notes, agent):
                    if result is None:
                        continue
                    after, pending = result
                    done = None
                    if pending is not None and self.writes == 'atomic':
                        after, how = self.readback(after, pending)
                        label += f', reads back: {how}'
                    elif isinstance(pending, tuple):
                        done = ('edited', pending)
                    elif pending is not None:
                        done = ('posted', pending)
                    events = [] if isinstance(pending, tuple) else [('write', agent, i, state, view, notes, after, beat)]
                    if state in CLAIMING and done is None:
                        events.append(('claimed', agent, i, notes, after))
                    yield f'{who} wake {r + 1}: {label}', (after, with_run(done)), events

    def broken(self, s, events):
        notes, runs = s
        found = []
        for e in events:
            if e[0] == 'settled':
                _, agent, (_, i, state, was, mine_state, beat), after, failed = e
                if live(after[i]):
                    if beat and was[1] in RELEASED:
                        found.append('P5')
                    if not failed and was[1] in CLAIMING and was[2] >= LEASE and any(
                            j > i and kind(n[0]) == kind(agent) and live(n) for j, n in enumerate(after)):
                        found.append('P2')
                    if was[1] == 'stopped' or (was[1] in RELEASED and mine_state not in RELEASED):
                        found.append('P3')
            elif e[0] == 'claimed':
                _, agent, i, before, after = e
                if after[i][1] in CLAIMING and holder(after, kind(agent)) != i:
                    found.append('P1')
            else:
                _, agent, i, state, view, before, after, beat = e
                if state in CLAIMING and i < len(before):
                    was = before[i]
                    if beat and was[1] in RELEASED and live(after[i]):
                        found.append('P5')
                    if was[1] in CLAIMING and was[2] >= LEASE and any(
                            j > i and kind(n[0]) == kind(agent) and live(n) for j, n in enumerate(before)):
                        found.append('P2')
                    if was[1] == 'stopped' or (was[1] in RELEASED and view[1] not in RELEASED):
                        found.append('P3')
        if not any(run is not None and run[0] in ('posted', 'edited') for rs in runs for run in rs):
            for k in {k for _, k in AGENTS}:
                if sum(1 for n in notes if kind(n[0]) == k and live(n)) > 1:
                    found.append('P4')
        return found


def check(model):
    start = model.initial()
    parent = {start: None}
    queue = deque([start])
    broken = {}
    seen = set()
    while queue and len(broken) < len(RULES):
        s = queue.popleft()
        seen.update(witnesses(s[0]))
        for label, nxt, events in model.steps(s):
            for rule in model.broken(nxt, events):
                if rule not in broken:
                    broken[rule] = trace(parent, s) + [label]
            if nxt not in parent:
                parent[nxt] = (s, label)
                queue.append(nxt)
    return len(parent), broken, seen


def trace(parent, s):
    labels = []
    while parent[s] is not None:
        s, label = parent[s]
        labels.append(label)
    return labels[::-1]


FLEET_WITNESS = 'a builder and the fleet hold at once'
WITNESSES = {
    'lapsed beside a newer holder': lambda n, h: any(
        x[1] in CLAIMING and not live(x) and h.get(kind(x[0]), -1) > i for i, x in enumerate(n)),
    FLEET_WITNESS: lambda n, h: 'builder' in h and 'fleet' in h,
    'a second note of one agent holds': lambda n, h: any(
        i in h.values() and any(y[0] == x[0] for y in n[:i]) for i, x in enumerate(n)),
    'an asking note holds': lambda n, h: any(n[i][1] == 'asking' for i in h.values()),
    'a done note beside a holder': lambda n, h: any(
        x[1] == 'done' and kind(x[0]) in h for x in n),
}


def witnesses(notes):
    h = {k: holder(notes, k) for _, k in AGENTS}
    h = {k: v for k, v in h.items() if v is not None}
    return {name for name, met in WITNESSES.items() if met(notes, h)}


def main(argv):
    p = argparse.ArgumentParser(description='Model-check the records v1 claim and lease rules.')
    p.add_argument('--variant', choices=sorted(VARIANTS), help='check a broken variant of the writer')
    p.add_argument('--writes', choices=sorted(RUNS), default='atomic',
                   help='atomic: each write re-reads in the same step (the rules as stated); '
                        'split: the pinned writer reads, then writes, with two wakes per agent; '
                        'fixed: split, with the #1441 writer reading back after each edit')
    args = p.parse_args(argv)
    model = Model(args.variant, args.writes)
    states, broken, seen = check(model)
    what = f'{args.writes} writes' + (f', variant {args.variant}' if args.variant else ', current rules')
    expected = set(WITNESSES) if len(model.agents) == len(AGENTS) else set(WITNESSES) - {FLEET_WITNESS}
    missed = sorted(expected - seen)
    for name in missed:
        print(f'vacuous: never reached: {name}')
    for rule in sorted(broken):
        print(f'broken {rule}: {RULES[rule]}')
        for n, label in enumerate(broken[rule], 1):
            print(f'  {n}. {label}')
    if broken or missed:
        return 1
    print(f'ok: {what}: P1 to P5 hold over {states} states')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
