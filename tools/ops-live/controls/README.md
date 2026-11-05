# Offline kit controls (#2219, OB8a)

Validates the control bounds of #2190's bounded acceptance kit, offline,
before anyone seeks live permission. Python 3 standard library only.

```sh
python3 -I tools/ops-live/controls/kit.py check <kit.json>   # 0 pinned, 1 refused, 2 usage/unreadable
python3 -I tools/ops-live/controls/test_kit.py               # the red/green proofs, on synthetic kits
```

It reads one file and nothing else: no network, GitHub, `room-cli`, thread or
write. **A pass is not permission and not a result.** It says only that the
document pins its bounds; every live, machine, write, merge, activation and
spending gate stays where it is, and a pass closes no P1–P8 claim.

## What it refuses

A kit is refused (every refusal printed, exit 1) unless it pins all of:

| Key | Bound |
| --- | --- |
| `format` | Exactly `ops-live-kit-controls/1` |
| `candidates.heads` | One or more `{repository, branch, commit}`: `owner/name` (the name not `.` or `..`), a plain branch name (no `..`, no part starting with `.` or `-` or ending in `.` or `.lock`), a full 40-hex lowercase commit other than all zeroes; no repository and branch twice |
| `candidates.revisions` | `{kind, path, blob}`, with at least one `rule` and one `contract`: a repository-relative path (no empty, `.`, `..` or `.git` part) and its full 40-hex lowercase blob other than all zeroes; no path twice |
| `limits.threads`, `limits.operations` | Positive integer `active` and `total`, `active` no more than `total` |
| `limits.duration_minutes` | A positive integer |
| `permissions` | Each of `machine`, `live`, `write`, `merge`, `activation`, `spending`, exactly; no other class. Each states `needed` and `granted` (true or false) and `record` |
| `permissions.<class>.record` | `null` unless `granted`; a grant needs a private-record comment pointer (`https://github.com/jparker2006/ClosedWiz/issues/<N>#issuecomment-<C>` or `/pull/…`, positive numbers without leading zeroes). A record without a grant is refused too |
| `stop.conditions`, `stop.reconciliation`, `restoration`, `cleanup` | Non-empty lists of distinct, non-empty printable ASCII steps |

The reader is strict: one JSON object, no repeated key, no `NaN`/`Infinity` or integer too long to read,
no unknown key at any level, booleans never counted as numbers.

**Evidence it cannot validate is refused,** not skipped: a top-level
`fencing`, `access`, `reviewer_output`, `acknowledgements` or `results` key.
Their shapes come from #2187's contract and are validated by #2190.

A pass prints which needed classes are still not granted, and which grants
name a record. The pointer's form is checked; the record itself is **not read
back** here. #2190 reads every record back before any live effect.

## Not here

No endpoint, operation, evidence or result schema, contract adapter, host
roles, Cloud exposure or permitted-effect list: those are #2187's and #2190's.
The example kit in `fixtures/kit.json` is synthetic; its pointer names no real
comment.

No maximum is set for counts or duration, and a grant for a class marked not
needed is not refused: no approved cap or rule says so. The approval that
admits the final kit decides each value.

## Seam for #2190

`kit.py` exposes `read(text)` (strict JSON, raises `Refused`), `check(doc)`
(every refusal as `"<path>: <reason>"`, empty on a pass) and `summary(doc)`
(the pass lines). #2190 keeps the kit controls as their own document, or a
sub-object it passes to `check`, alongside its own sections; it never needs
an edit here to add them.
