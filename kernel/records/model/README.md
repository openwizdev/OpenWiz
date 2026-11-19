# Records v1 claim and lease model

An exhaustive model check of the claim and lease rules that [records v1](../../records.v1.md) takes from the status contract (section 2, `openwiz:status v1`, "Claims"). It's Python 3.11 or later, standard library only, and reads nothing outside this folder.

```sh
python3 -I kernel/records/model/model.py                       # the current rules: exit 0
python3 -I kernel/records/model/model.py --variant <name>      # a broken variant: exit 1, with a trace
python3 -I kernel/records/model/model.py --writes split        # the pinned writer's read-then-write order
python3 -I kernel/records/model/test_model.py                  # the model's own tests
```

Exit 0: every rule holds over every reachable state. 1: a rule broke. Each broken rule prints as `broken <rule>: <what>`, followed by its shortest trace. A pass that never reached one of the situations the rules exist for prints `vacuous: never reached: <situation>` and exits 1. 2: bad arguments.

## What it models

One ticket, two builders and one fleet agent. Each agent posts a note, edits it to `working`, `asking`, `done` or `stopped`, and posts a new note after it stops. Time passes in ticks, and a note last edited `LEASE` (2) ticks ago has lapsed, which stands for records v1's 30 minutes. Time can pass between any two writer calls, so any wake can resume late. The writer follows the contract and `status.py write` at the commit records v1 pins:

- **Live:** a `working` or `asking` note edited less than the lease ago.
- **Holder:** the oldest live note of a kind. Kinds never compete.
- **Fence:** an edit stops when the agent's own note is `stopped`, or another live note of its kind holds the claim, older or newer.
- **Post:** a new `working` or `asking` note stops when a live note of its kind holds the claim. After posting, it reads back, and it steps down to `stopped` when an older live note of its kind appeared meanwhile.

## The rules it checks

| Rule | Holds when |
| --- | --- |
| P1 | Never two live holders: a claim write that succeeds leaves its own note holding the claim |
| P2 | A lapsed holder never takes the ticket back from a newer one: no write turns a lapsed note live while a newer note of its kind is live |
| P3 | A release is never lost: a `stopped` note never goes live again, and no write decided before a release (`done` or `stopped`) revives it |
| P4 | Every claim is held, released or lapsed: between writes, at most one note of each kind is live |

These situations must all be reached, or the pass is vacuous: a lapsed note beside a newer holder, a builder and the fleet holding at once, an agent's second note holding, an `asking` note holding, and a `done` note beside a holder.

## Two write orders

- **`atomic`** (the default) is the rules as records v1 states them. Each write re-reads the ticket and writes in one step. Every rule holds.
- **`split`** is the order the pinned `status.py write` actually runs. It reads the ticket in one call and writes in another, and other writers can act in between. Builder 1 also gets a second wake that can overlap its first. This mode stops once every rule has a counterexample. P1, P2 and P4 break with one wake per agent: a lapsed note re-reads, a newer note claims and reads back, and the lapsed note's edit still lands. P3 breaks only when two wakes of one agent overlap. This finding is reported on spec #1365. The rules are unchanged.

## Broken variants

Each variant drops one rule from the writer, and the check must fail on the rule it guards:

| Variant | Drops | Breaks |
| --- | --- | --- |
| `no-post-fence` | A new note's check for a live holder, and its read-back | P1 |
| `older-only-fence` | The fence against a newer holder: only an older one stops an edit | P2 |
| `edit-stopped` | The fence on a `stopped` note | P3 |
| `asking-not-claiming` | `asking` as a claim: only `working` notes count | P4 |

[`evidence/`](evidence/) holds the red run, which is the model with no fence at all, and the green run of the tests and every mode.
