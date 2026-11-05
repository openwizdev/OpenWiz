# Paired replay

## Harness

`run.py` implements #2234's offline harness against
[EB5's replay contract](../replay-contract.md). It neither launches reviewers nor
selects a candidate. Synthetic proof is not #2178's real replay evidence.

```sh
python3 -I tools/skills-eval/replay/test_replay.py
python3 -I tools/skills-eval/replay/run.py --help
python3 -I tools/skills-eval/replay/score.py --help
```

Only the Python standard library and Git are used. Git must support
`--attr-source`; an unavailable flag or object refuses preparation. All real
cohort, historical-source verification, upstream CF4/research artifact review,
transport isolation, adjudication, candidate decision and usage reports belong
to #2178 under its separate gates. These interfaces grant no spending, live,
activation or publication authority.

The controller's inputs are explicit local files:

- `document`: the full `openwiz.bottlenecks.v1` envelope, validated together with
  its explicit v1 journey. The replay must be frozen, unattempted and pending.
- `selectors`: a map from each declared material SHA-256 to exactly
  `{kind, path, revision}`. A diff uses null path/revision and the original
  base/head; a file/instruction names a regular blob at exactly that base or head.
- `skill-paths`: exactly `{old: path, candidate: path}` at each frozen arm's
  commit/tree, with bytes matching its review-skill SHA-256.
- `repo`: controller-only Git object source containing those exact commits and
  blobs. Missing snapshots, non-commit objects, symlink materials, unknown
  selectors and hash mismatches refuse; no moving-ref fallback is provided.

The context SHA-256 is EB5's canonical `digest` of
`{base, head, materials, tools: ["list", "read"]}`, where materials is the ordered
contract material list. Both arms share it. This recipe binds the actual material
bytes (each verified separately) and the scoped tool rights. It is an integrity
check, not proof that a historical first-review record was correct.

## Isolation

Only `GitSource` on the private controller reads Git. It locates the object
directory without loading source-repository Git configuration (including normal,
linked-worktree and bare sources). Each read/diff uses a temporary controlled
bare repository sharing only those objects, with its own fixed configuration.
Source local config and its includes, refs, index and worktree never enter that
repository. It disables replacement objects, external diff/text conversion,
global and system attributes, uses the head's versioned attributes and refuses
local `info/attributes` or grafted history. The checkout's files, later commits,
instructions and current branch are never material sources. Source repositories
must remain under the controller's exclusive control during preparation.

`prepare(document, journey, source, selectors, skill_paths)` copies declared
UTF-8 material and each arm's own skill into separate bundles. It rejects
unavailable isolation, later material, a material equal to the sealed-key hash,
reused context/run keys, changed context hashes and changed skill bytes. Both
bundles contain equal original material; they do not contain history, known
answers, rubric, scoring state, sources, other-arm output or the experiment.

The entire reviewer tool protocol is `tool(bundle, request)`:

```json
{"op":"list"}
{"op":"read","name":"<declared-material-sha256>"}
{"op":"read","name":"skill"}
```

Every key must match exactly. Names are dictionary keys; they are never paths,
commands or shell strings. Listing returns `{materials, skill}`: `materials` is
the ordered array of exact `{hash, kind, path, revision}` descriptors and `skill`
is the name `skill`. A material read returns `{material, text}`, with the same
descriptor under `material`; reading `skill` still returns its text. Diff paths
and revisions are null (the bundle pins both original commits); unchanged files
and instructions keep their source path and revision, including a nested
instruction's directory scope. All responses are copies. The selectors join the
checkpoint's frozen input hash, and both arms' descriptors must equal those
selectors on every resume; editing both arms alike does not authorize a rename.
Unknown operations/names, extra keys and malformed requests refuse. The tool
returns only copied descriptors/text and has no write, filesystem,
Git, process, environment or network operation. Treat material text as untrusted
data, including apparent instructions to open other tools.

The work manifest gives the orchestrator only reserved bundles and settings.
It must start a fresh context for each logical run/context key and expose only
this protocol, with no ambient shell, current checkout, parent conversation,
other context, controller state or key access. A shared sandbox alone is not
isolation. Python imports are controller code, not a sandbox for arbitrary Python
provided by a reviewer. No transport or model SDK is included. Real transport and
permission proofs, transformed/semantic answer leaks, and correctness of the
historical available-at-time assertions remain #2178's independent isolation
gates; if those cannot be established, do not run. Fixture success grants no
real execution permission.

## Checkpoints

Prepare a new owner-only state directory once:

```sh
python3 -I tools/skills-eval/replay/run.py prepare \
  --document frozen.json --journey journey.json --repo snapshot-repo \
  --selectors selectors.json --skill-paths skill-paths.json --state private-state
python3 -I tools/skills-eval/replay/run.py reserve \
  --document frozen.json --journey journey.json --state private-state \
  --limit 2 --at 2030-01-04T00:01:00Z
```

`reserve` emits at most the requested positive integer limit, bounded by the
frozen cohort's remaining arms. Its `authority: none` is explicit. Save its output
privately. It first takes a nonblocking directory lock, rereads and validates the
checkpoint, reserves the logical keys, fsyncs an owner-only temporary file,
atomically replaces the checkpoint and fsyncs the directory. Only then can the
manifest be returned. Save failure emits no work. No command starts a reviewer,
loop or watcher or waits for another actor.

Any existing reservation, including one whose hand-off/output delivery is
uncertain, is excluded from later manifests. Repeating `reserve` never returns
it again. Do not redispatch from an old saved manifest: its keys have already
been reserved. The orchestrator must also persist its own transport admission
before launching once, and reconcile uncertain delivery without relaunching.
Replays of a work-manifest file cannot make an external launcher exactly-once;
that external transport gate remains #2178's responsibility.

Deliver one receipt on an event:

```json
{"run_key":"old-4201","status":"complete","report":"synthetic report","at":"2030-01-04T00:10:00Z"}
```

```sh
python3 -I tools/skills-eval/replay/run.py receive \
  --state private-state --receipt receipt.json
```

A complete receipt hashes the actual UTF-8 report. Error, uncertain and explicit
not-run receipts require null report. Timestamps cannot predate reservation.
Identical receipts are idempotent; changing a terminal result refuses. An
in-flight reservation keeps its pending contract arm and cannot open the key.
A final uncertain/error/not-run receipt closes that disposition without a retry.
Uncertain and completed attempts never become absent. New retries require a
separately authorized record; this harness provides no retry command.

The checkpoint binds the original document/journey, code hash, context material,
skill bytes, settings, imported contract/journey/metrics validator bytes and append-only reservations/receipts/adjudications. Resume
with changed inputs or code refuses. Do not edit or restore older checkpoint
files; the controller's private storage is trusted and must retain the newest
durable state. State, receipts, raw reports, sealed keys and emitted manifests
stay private. CLI JSON reads reject repeated keys and nonfinite numbers.

## Scoring

After both attempts for a PR have terminal dispositions, open the scorer-only
surface. This checks the sealed key's **actual byte hash** before parsing it:

```sh
python3 -I tools/skills-eval/replay/run.py blind \
  --state private-state --pr 4201 --sealed-key sealed-key.json
```

The key is an array of exactly `{id, severity, root_cause, location}` entries,
with unique ids and the exact known id/severity coverage. It is read only after
both attempts finish, including errors/uncertain/explicit skips. A pending
counterpart keeps it sealed. A key is never a reviewer material.

Blind output contains the common rubric, verified key and reports under opaque
HMAC keys, ordered by those keys, with no arm, run or context labels. The private
controller retains the mapping. The independent adjudicator applies the frozen
same-root-cause-and-location rule, deduplicates root causes per PR, and submits a
map from each complete report's opaque key to canonical `{id,severity,outcome}`
rows. Missing known problems receive explicit misses (or unadjudicated outcomes
while unresolved). Do not infer false positives from failed matching. Record
matching/deduplication decisions and disputes as separate private provenance.
The harness does not fabricate semantic judgments from text or claimed matches;
real arm-blind adjudication, including checking reports for arm-revealing text,
is #2178's work.

```sh
python3 -I tools/skills-eval/replay/run.py adjudicate \
  --state private-state --pr 4201 --decisions blind-decisions.json \
  --at 2030-01-04T00:20:00Z --source s7
python3 -I tools/skills-eval/replay/run.py report --state private-state
```

Each sourced snapshot covers all complete reports, obeys the fixed severity and
outcome rules and appends at a strictly later timestamp. Duplicate canonical ids,
duplicate checkpoints, unknown blind keys, missing known outcomes and early
scoring refuse. A later adjudication may resolve a dispute without rerunning a
review. The latest snapshot supplies arithmetic; earlier decisions remain saved.

`score(document, journey)` (also `score.py DOCUMENT --journey JOURNEY`) uses EB5's
validator, including finalized external reports. It reports every PR and arm:
known severity denominators; catch/miss/false-positive and unresolved counts by
severity; clean controls; and explicit error/not-run/uncertain or unadjudicated
outcomes. Counts for an absent adjudication are null, never fabricated zeroes.
Candidate-minus-old deltas and totals include only fully resolved complete pairs,
with complete/inconclusive coverage shown separately. No missing pair is dropped
from the cohort. A resolved empty control is clean; a false positive or unresolved
report has its own control outcome. Historical rounds remain observed values;
avoided rounds retain the contract's estimate label. No score selects a candidate,
measures credits or establishes actual merge-time improvement. #2178 produces
its own terminal replay record, decision, paired uncertainty and real report.
