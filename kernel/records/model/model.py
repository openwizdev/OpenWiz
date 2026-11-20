#!/usr/bin/env python3
"""Model-check the records v1 claim and lease rules, exhaustively.

Records v1 section 2 takes its claim and lease rules from the status contract
(openwiz:status v1, "Claims"): a note is live while working or asking and edited
within the lease; the oldest live note of a kind holds the claim; a writer
re-reads before each write and stops (the fence) when its own note is stopped
or another live note of its kind holds the claim; a new note that finds an
older live note of its kind after posting steps down to stopped (lost claim).

This model holds one ticket, two builders and one fleet agent, each posting,
editing, releasing (done or stopped) and starting again, with time passing
between any two steps, so a wake can resume late. It visits every reachable
state and checks four safety rules on each:

  P1  never two live holders: a claim write that succeeds leaves its note holding
  P2  a lapsed holder never takes the ticket back from a newer one
  P3  a release is never lost: a stopped note never goes live again, and no write
      decided before a release revives it
  P4  every claim is held, released or lapsed: at most one live note per kind

Run: python3 -I kernel/records/model/model.py [--variant NAME] [--writes atomic|split|fixed]
Exit 0: every rule holds. 1: a rule broke; each broken rule prints with its
shortest trace. 2: bad arguments.
"""
import argparse
from collections import deque
import sys

LEASE = 2            # ticks: a note last edited LEASE ticks ago has lapsed (30 minutes in records v1)
CLAIMING = ('working', 'asking')
RELEASED = ('done', 'stopped')
AGENTS = (('builder 1', 'builder'), ('builder 2', 'builder'), ('fleet', 'fleet'))
MAX_NOTES = 4        # notes posted on the ticket, in all
FIXED_NOTES = 3      # the fixed model's cap: a full search with 4 notes and two wakes runs too long for CI
# Wakes per agent: in the split model builder 1 has a second wake that resumes late.
# The fixed model (#1441) is the split one with the writer's edit read-back.
RUNS = {'atomic': (1, 1, 1), 'split': (2, 1), 'fixed': (2, 1)}

RULES = {
    'P1': 'never two live holders: a claim write succeeded but its note does not hold the claim',
    'P2': 'a lapsed holder took the ticket back from a newer one',
    'P3': 'a release was lost',
    'P4': 'a claim is neither held, released nor lapsed: two live notes of one kind',
}

# Each broken variant drops one rule from the writer; the checker must catch it.
VARIANTS = {
    'no-post-fence': ('P1', 'a new note posts over a live holder and never reads back'),
    'older-only-fence': ('P2', 'the edit fence stops a note only for an older holder, not a newer one'),
    'edit-stopped': ('P3', 'the fence lets an agent edit its stopped note back to live'),
    'asking-not-claiming': ('P4', 'the writer counts only working notes as claiming, not asking ones'),
}


def kind(agent):
    return AGENTS[agent][1]


def live(note):
    return note[1] in CLAIMING and note[2] < LEASE


def holder(notes, k, claiming=CLAIMING):
    """The id of the oldest live note of kind K, which holds its claim, or None."""
    return next((i for i, n in enumerate(notes)
                 if kind(n[0]) == k and n[1] in claiming and n[2] < LEASE), None)


def own(notes, agent):
    """The agent's latest note id, or None."""
    return max((i for i, n in enumerate(notes) if n[0] == agent), default=None)


def put(notes, i, agent, state):
    note = (agent, state, 0 if state in CLAIMING else LEASE)
    return notes[:i] + (note,) + notes[i + 1:]


class Model:
    def __init__(self, variant=None, writes='atomic'):
        self.variant, self.writes = variant, writes
        self.claiming = ('working',) if variant == 'asking-not-claiming' else CLAIMING
        # Kinds never compete, so the split model keeps only the builders, to stay small.
        self.agents = AGENTS if writes == 'atomic' else AGENTS[:2]
        self.max_notes = FIXED_NOTES if writes == 'fixed' else MAX_NOTES

    def initial(self):
        return ((), tuple((None,) * n for n in RUNS[self.writes]))

    def read(self, notes, agent):
        """What a writer's read decides on: its latest note, that note's state, the holder."""
        mine = own(notes, agent)
        return mine, (None if mine is None else notes[mine][1]), holder(notes, kind(agent), self.claiming)

    # The writer, as status.py write does it. VIEW is what its last read showed;
    # NOTES is the ticket now. Returns (notes, pending readback note id) or None
    # when the fence stops it (nothing written).
    def edit(self, view, notes, agent, i, state):
        _, mine_state, h = view
        if mine_state == 'stopped' and self.variant != 'edit-stopped':
            return None
        if h is not None and h != i and not (self.variant == 'older-only-fence' and h > i):
            return None
        if self.writes == 'fixed' and state in CLAIMING:
            # #1441: a claim edit reads back. It keeps what GitHub's edit history shows it
            # replaced, and what its own read showed.
            return put(notes, i, agent, state), ('edited', i, state, notes[i], mine_state)
        return put(notes, i, agent, state), None

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
        """#1441: the fixed writer's read-back after a claim edit: (notes, what it did).

        As status.py write does: a release it never read, which its edit replaced, is put back,
        even when a later edit has changed the note since, unless the note is released again
        (#1463 R1); otherwise a note that no longer reads as written is not its to settle (it
        fails, and the edit that changed it has its own read-back); and it steps down when
        another live note of its kind exists, older or newer."""
        _, i, state, was, mine_state = pending
        if was[1] in RELEASED and was[1] != mine_state and notes[i][1] in CLAIMING:
            return put(notes, i, notes[i][0], was[1]), f'puts the {was[1]} back'
        if notes[i][1] != state:
            return notes, None
        if any(j != i and kind(n[0]) == kind(notes[i][0]) and live(n) for j, n in enumerate(notes)):
            return put(notes, i, notes[i][0], 'stopped'), 'lost claim'
        return notes, 'kept'

    def writes_for(self, view, notes, agent):
        """Every write the agent may try from VIEW: (label, result, note id, target state)."""
        mine, mine_state, _ = view
        for state in CLAIMING + RELEASED:
            if mine is not None:
                yield f'edit note {mine} to {state}', self.edit(view, notes, agent, mine, state), mine, state
        if (mine is None or mine_state == 'stopped') and len(notes) < self.max_notes:
            for state in CLAIMING:
                yield f'post a {state} note', self.post(view, notes, agent, state), len(notes), state

    def steps(self, s):
        """Every step from state S: (label, next state, events to check)."""
        notes, runs = s
        # One writer call takes seconds, far under the lease: time passes only between calls.
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
                    # A failed read-back confirms no claim, but P3 still judges its write (#1463 R1):
                    # the edit that changed the note since has its own read-back for the rest.
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
                for label, result, i, state in self.writes_for(view, notes, agent):
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
                    # A write that reads back is judged once its read-back settles it.
                    events = [] if isinstance(pending, tuple) else [('write', agent, i, state, view, notes, after)]
                    if state in CLAIMING and done is None:
                        events.append(('claimed', agent, i, notes, after))
                    yield f'{who} wake {r + 1}: {label}', (after, with_run(done)), events

    def broken(self, s, events):
        """The rules this step or its state breaks."""
        notes, runs = s
        found = []
        for e in events:
            if e[0] == 'settled':
                # P2 and P3 for a write that reads back: the note it revived is still live once
                # the read-back settled it.
                _, agent, (_, i, state, was, mine_state), after, failed = e
                if live(after[i]):
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
                _, agent, i, state, view, before, after = e
                if state in CLAIMING and i < len(before):
                    was = before[i]
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
    """Visit every reachable state, or stop once every rule has broken.
    Returns (states, {rule: shortest trace}, witnesses)."""
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
# Situations the rules must meet, so a pass is never vacuous.
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
    print(f'ok: {what}: P1 to P4 hold over {states} states')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
