# Bounded ops acceptance kit (#2190, OB8)

The prepared kit for spec #2185's agent-run acceptance and its offline result
validator. Python 3 standard library only.

```sh
python3 -I tools/ops-live/acceptance.py kit tools/ops-live/kit.json        # 0 consistent, 1 refused, 2 usage/unreadable
python3 -I tools/ops-live/acceptance.py results tools/ops-live/kit.json <results.json>
python3 -I tools/ops-live/test_acceptance.py                               # the red/green proofs, synthetic
```

Both commands read only the named files: no network, GitHub, `room-cli`,
thread or write. **A pass is not permission and not a result.** This folder
authorizes no live, machine, write, activation, spending or merge step.

## The kit (`kit.json`)

`status` is `prepared`. Its `controls` sub-object is #2219's
`ops-live-kit-controls/1` document, checked unchanged by `controls/kit.py`:
candidate heads, rule and contract blobs, limits, permission classes, stop,
restoration and cleanup. Around it the kit pins host roles, Cloud exposure,
permitted effects (ops-dispatch v1 actions only; `merge` only with a merge
grant), claims P1–P8 and the eight measures.

The pinned head, blobs and limits are the proposal at preparation time. The
approval that admits the final kit decides each value; the live agent re-pins
the current heads and blobs before seeking it.

**The #2244 assumption lives in one place:** `discovery_2244`. Until #2244's
findings are recorded there (`record` set to their private-record pointer, and
each of `lost_start_lookup`, `independent_wakes`, `reviewer_own_output` set
from `unknown` to `observed` or `absent`), the live gate stays closed and
P3, P4, P5 and P7 cannot pass. `absent` keeps them refused too.

**The live gate** (`kit` command, AC1) stays closed while any needed permission
is not granted, any grant's record is not read back (`read_back.<class>` holds
the digest of the read-back record) or #2244 is Unknown. A kit marked
`authorized` with a closed gate is refused. An open gate is open on paper only:
every record is re-read immediately before any step.

## Results (`ops-live-results/1`, AC2)

One strict JSON object, every key required:

| Key | Shape |
| --- | --- |
| `format`, `kit` | `ops-live-results/1`; the SHA-256 of the exact kit file |
| `live` | `true` only for a run under an `authorized` kit |
| `window` | `{start, end}` in milliseconds, within the kit's duration |
| `threads` | `{alias, role, start, end}`; role is a kit host role, `end` null means never ended |
| `operations` | `{operation_key, intent_id, action, start, end, completion, ack}`; ops-dispatch v1 actions and completion states; `ack` null or `{operation_key, intent_id, recipient, evidence}` |
| `fencing` | `{boundary: effect, advisory or unknown, evidence}` |
| `reviewer_output` | `{access: verified, absent or unknown, evidence}` |
| `cleanup` | `{step, state: done or accounted, evidence}` for every kit restoration and cleanup step |
| `claims` | P1–P8 in order: `{claim, status: pass, fail, partial or unverified, evidence}` |
| `measures` | Each of the kit's measures: `{value, denominator}`; null value only when named in `gaps` |
| `gaps` | Plain technical strings |

Evidence entries are ops-dispatch v1's `{evidence_class, source, digest}`: a
`fixture:` source for fixtures, a private-record comment pointer otherwise.

It refuses, among others:

- **Fabricated concurrency:** more threads or operations active at once, or in
  total, than the kit allows; spans outside the run window, ending before they
  start or counted twice; a window longer than the duration.
- **Missing acknowledgements:** a completed builder start, review start or
  delivery without the recipient's observed ACK of the same operation key and
  intent; P4 passing without an acknowledged delivery.
- **Advisory-only fencing:** P5 passing without an observed `effect` boundary,
  or with a duplicate completed effect.
- **Absent reviewer-output access:** P7 passing, or any completed merge,
  without observed `verified` access.
- **Incomplete cleanup:** a kit step missing, repeated, pending or without
  evidence; a thread that never ended.
- **False live passes:** a pass without `live`, without observed evidence
  (fixture or review alone), while #2244 is Unknown, against another kit, or
  with a duplicate count or measure that its records contradict. Completed
  effects outside `permitted_effects` are refused.

A consistent result is not acceptance: each pass still needs its observed
evidence read back and independently reviewed. Exact outputs stay in private
evidence; public records carry the claim/evidence/gap matrix only.

## Not here

The kit's control bounds are #2219's (`controls/`). The live run, its records,
read-backs and restoration are later steps of #2190, gated as above.
