# Release candidate v1

`openwiz.release-candidate.v1` is the shared future interface for one checked
public build. The [schema](release-candidate.v1.schema.json) checks structure;
the rules below check meaning and authority. Passing either is not permission
to run live checks or publish. Preparation can precede cut-over. The shipping
path requires verified O17 completion after O16, without clearing either
step's prerequisites, holds or separate authorization. Development remains in
ClosedWiz until that cut-over. No private history is a release source.

Consumers: RL2's release command evaluates decisions, gates and publication;
RL3's bounded kit produces live receipts; RL4's collector verifies product
identity; RL5 supplies actual release and timing evidence. These are interfaces,
not implemented capabilities or evidence that any live check passed.

## Shape, bytes and identity

Read strict UTF-8 JSON: one object, no duplicate keys at any depth, unknown
fields, nonfinite numbers or coercion. Integers are exact nonnegative Unix UTC
seconds. Reject unsafe filenames, duplicate identities and malformed values.
No local paths, targets, credentials or raw decision words belong in a public
record. Evidence references are safe technical references or verified private
comment pointers; raw evidence and routing stay private.

`candidate` is immutable. `candidate_sha256` is SHA-256 of its canonical JSON:
UTF-8, object keys sorted lexicographically, no insignificant whitespace,
non-ASCII characters emitted literally, no slash escaping, and no final newline.
All strings must be Unicode scalar values. There are no floating point fields.
Arrays keep their order. This is Python's `json.dumps(value, sort_keys=True,
separators=(',', ':'), ensure_ascii=False).encode('utf-8')` on a strictly parsed
value. Every hash is lowercase hexadecimal. Git identities are full 40-character
commits/trees. Hashes establish byte integrity, not a signed publisher identity.

| Candidate field | Required meaning |
| --- | --- |
| `source` | Exactly `openwizdev/OpenWiz`, selected commit and tree, descending from the contract's fixed public anchor through its own history. Read the remote identity, tree and ancestry; a matching tree copied from private history is insufficient. |
| `build_id` | SHA-256 of the immutable build-provenance record identifying the clean source job(s), commands and exact complete product inventories; not an arbitrary label chosen while packaging. |
| `release_version` | Highest included version; the tag is `v<release_version>`. |
| `included_versions` | Unique versions, newest first by numeric minor/patch, each newer than all already published versions. Each retains one dated changelog section and a nonempty list of unique promise IDs used by the smoke kit. Single-version patches use the same shape. |
| `changelog` | Exact approved release-note UTF-8 bytes, their byte count and SHA-256. No newline, date, whitespace or normalization changes after approval. |
| `products` | Exactly cli, server, service, web and runtime for each of the three install targets, sorted by target then product. Identities, complete payload hashes and build receipts must agree with this source, release version and target. |
| `artifacts` | Complete remote asset inventory sorted by unique filename; each exact length, hash, role and target. See below. |
| `kit` | Exact kit digest, scope/allowlist/count/spending-input digest and verified existing private authority pointer. These do not create authority. |
| `risk` | Explicit send, new, app_permissions and spending classification, each yes/no/unknown with a reason based on the complete change since the last publication. Missing, unknown, unreadable or unsupported classification refuses; an unexplained no is not an exemption. |

For changelog section hashing, a section begins at its `## <version> · <date>`
heading and ends immediately before the next version heading (or EOF), with
trailing LF bytes removed. Hash the remaining UTF-8 bytes. Every included
version has exactly one matching heading/section; no combined range heading,
placeholder, duplicate, omitted promise or silently truncated entry. The exact
notes retain each section; existing published entries remain immutable. The
settled 0.0.6–0.0.12 release keeps all seven sections in this order.

For packaged releases, require all three targets from [install v1](install.v1.md).
Each has `openwiz-<version>-<target>.tar.gz` (archive), the matching versioned
`.manifest.json` (manifest), `openwiz-<target>.manifest.json` (manifest_alias)
and `openwiz-<target>.sha256` (manifest_checksum). One global `SHA256SUMS`
(checksums, target null) combines the targets' archive/manifest checksums without
renaming either; it does not hash itself. All other artifacts have their exact
target. Alias manifest bytes equal the versioned manifest. The alias checksum
names and hashes that alias; global checksums cover every archive and versioned
manifest exactly once. Verify complete archive members and manifest assets using
the existing install contract; bind the checksum/alias files' own hashes in this
inventory too. Unknown, missing, extra or changed assets refuse. This does not
alter the installer, update transport or their integrity rules.

## Minimum product identity (RL4)

`product_identity` is exactly `{schema: "openwiz.product.v1", product, version,
source, target}`. Product is cli/server/service/web/runtime. Version is the
candidate release version; source is its public commit; target is an install
target. All five products must originate from the clean checked source build,
not from a requested label, architecture test or newly written package stamp.

The three compiled programs embed one ASCII prefix `OPENWIZ_PRODUCT_V1:` followed
by the canonical identity JSON and LF, produced during compilation. CLI, server
and service expose `--build-identity`: print that identity as one JSON object
and exit successfully without reading state/accounts, calling room-cli, binding
a port or starting a scheduler/service. The service library retains the same
compiled identity for its executable. Absence, ambiguity, malformed identity,
wrong product/version/source/target or executable architecture refuses.

A native build job queries its programs and binds the results to their exact
file hashes and source/build provenance. An offline collector on another target
**does not execute incompatible programs**: verify executable format and target,
read the unique embedded record, and match its payload hash to the trusted
native build job's query receipt. `embedded-record` records this method;
`native-query` records native execution. Neither an appended marker nor an
unverified caller-supplied job receipt establishes compiled provenance.

The web export contains `web/openwiz-product.json`, generated during the actual
export with this identity. Match every exported file against that same build
job's inventory (`web-build`), rather than adding a marker to an old export.
The runtime's files/modes are compared to the selected public Git tree's complete
tracked skill/runtime selection (`tracked-tree`); the receipt identifies that
selection and any reviewed deterministic build transformations. Hash each
web/runtime payload as canonical JSON of its complete path-sorted inventory of
`{path, mode, bytes, sha256}` rows, using install-relative paths. Native payload
hashes are the program file hashes. Build receipts bind these hashes, source,
version, target and method. Keep the existing `openwiz-build.txt` package stamps
and install manifest unchanged; stamps are additional integrity checks, not
compiled source evidence. No verifier may trust a requested stamp as provenance.

## Two actual decisions (P1)

`decisions.ship` and `decisions.changelog` are nullable during preparation;
both must be verified before publication. Each names an existing private
issue/PR comment holding Jake's actual decision, its exact raw record SHA-256,
original decision time, and binding. Read the comment and its author, scope,
current revision and revocation/supersession state; verify it actually records
Jake's instruction. A resolver saying unavailable, a fabricated pointer, a
copied resolved status or `--approval` supplied by a caller is never evidence.
Public records give only a decision summary, date and verified pointer.

Ship binds `candidate_sha256`. Changelog approval binds `changelog.sha256` and
may precede ship. They may be in one actual comment, but each decision and its
scope must be established. Store the original ship record/time durably before
an effect. Revalidate that both decisions apply to the selected candidate;
never synthesize or silently broaden an instruction to another build. A changed
candidate requires a matching ship binding grounded in the actual instruction;
if its scope is unclear, refuse. Identical notes may retain their changelog
approval across a rebuild if that actual decision still applies. There is no
third human release approval: no export-plan, final-diff, standalone Sol-export,
mandatory device/hands-on or per-step publishing prompt. Ordinary development
plan approval, review and required CI remain.

## Gate receipts and live interface (P2–P5)

Every gate slot is present, nullable while incomplete. Require passing current
cutover, ci, privacy, claims, products and smoke receipts. Risk gates send, new,
app_permissions and spending require live pass receipts whenever classified yes;
no permits null, unknown refuses. Do not trust the presence of a receipt or a
pass string: resolve and read its immutable evidence, verify its hash and inputs,
and independently establish that the producer and result are appropriate.
An unreadable, partial, missing, stale, failed or uncertain result blocks.

Each receipt binds `candidate_sha256`, the canonical `artifacts` array digest,
its own `inputs_sha256`, start/finish times, evidence reference/hash, coverage
and explicit gaps. `kit_sha256` is required and equals the candidate kit for
smoke/risk receipts; it is null for the other gates. A pass has a non-null finish
at or after start. Receipt inputs are canonical JSON of the complete gate inputs:

| Gate | Inputs beyond candidate identity; required evidence class |
| --- | --- |
| cutover | O17 verified completion, O16/prerequisite evidence, moved mapping, unresolved holds, public history/routing and immutable-release/required-check settings read-backs; source-inspection |
| ci | Trusted workflow/run/attempt, selected plan and complete required-check receipts at this exact public commit/build; ci |
| privacy | Full public source/history, complete artifact contents, scanner/rules revision and scope; source-inspection or ci |
| claims | Exact notes and all shipped claims, evidence ledger, tested/unproved meaning and unresolved findings; source-inspection or ci |
| products | Clean source build provenance, native query receipts and complete product/archive/manifest inventories; ci |
| smoke | Kit and scope digest, end-to-end exercise of every included version/promise on the combined candidate, tested product hashes, restriction inputs and bounded observations; live |
| each required risk | The classification diff/reason, matching bounded kit steps, existing grant/allowlist/count/spending authority and results for that category; live |

`coverage` in smoke is exactly one row for every included (version, promise)
whose approved notes section carries a live-checked line (a line starting
`Live-checked`), all pass, with no extra/duplicate/omitted rows. Every other
included version is carried in the receipt's `gaps` as one named not-live gap
per (version, promise), `Not live-checked in this release: <version> <promise>`,
never as a coverage row, and none is omitted (#18). A smoke coverage row passes only
when its live evidence proves the complete user flow for that promise was
exercised end to end on the combined candidate. A partial check cannot satisfy
the row. The receipt's inputs identify the bounded kit steps and observations
that establish that complete flow; a promise label or pass flag alone is not
evidence. A risk receipt covers the promises
its relevant kit steps exercise; its inputs identify the risk category and
bounded steps. A shared run can produce several gate receipts, each with that
gate's own input binding. Fixture and dry-run receipts are useful diagnostics
but never satisfy a live gate. Known device, Mac and real-radio gaps stay explicit;
a gap that leaves a required promise unproved blocks that gate.

Reuse [fleet tick's reviewed-plan restriction](fleet-tick.v1.md#reviewed-plan-execution-revision-1892):
compare the complete ordered dry-run document before effects with `--expect-plan`;
refuse pending-start recovery before it can run. A post-effect scope check is
insufficient. The kit never widens App grants, room-cli allowlist calls,
throwaway targets, counts, spending or approved host scope. No unsafe automatic
retry. Read-only discovery remains bounded by its separate recorded authority.

## Invalidation and resume

| Change | Required invalidation |
| --- | --- |
| Candidate field, selected source/build, products, risk inputs or artifact bytes | Recompute candidate digest; all old candidate-bound receipts and ship binding stop applying. Establish matching authority from the original instruction or report the block. |
| Notes bytes/date/sections | Changelog approval and claims receipt, plus the candidate-bound evidence above. |
| Kit/scope/authority | Smoke/risk receipts, plus changed candidate binding; never expand permissions. |
| Gate tool/rules/check plan/evidence revision or current external settings/holds | That gate's receipt even if candidate bytes did not change; re-resolve dependencies before the next effect. |
| Publication/read-back discrepancy | Incomplete/uncertain outcome; never mark complete or retry a potentially consumed write blindly. |

Content equality alone cannot establish current authority or absence of a new
hold/revocation. Check current inputs immediately before each gated effect.
Pre-ship preparation receipts count only when their identity, inputs and
continued validity are established. Do not invalidate unrelated evidence solely
because time passed, or use an earlier pass to override a newer failure.

Persist the attempt identity and intended effect before a write. Resume reuses
completed steps and consumed attempts, rechecks current gates and compares remote
state. An uncertain effect remains uncertain until its own read-back settles it;
a later refusal does not make it safe to repeat. Return blocked/incomplete with
a reason when progress needs an event. Never wait with a watcher, poll loop or
sleep for CI, review, approval or another agent.

## Publication, install and timer (P5–P7)

`publication` records the attempt and remote read-backs: annotated tag object
and peeled public commit, exact approved notes hash, complete remote asset
inventory digest, immutable and pre-release state, evidence and verification
time. Complete requires all expected bytes read back and matched, immutable
true and pre-release true for 0.0.x. Re-read settings without inventing a new
human approval. Never bypass protected-main/merge procedures, force-push, move
a published tag or rewrite published notes. Historical backfill is separately
gated, outside this next-release contract. Partial/uncertain publication is
incomplete even if some downloads already exist.

`install` records an agent's normal install/update route on an already approved
test machine: version/source/target plus matching manifest/archive hashes, time
and private evidence. Verify the selected installed programs/web/runtime agree
with that product identity, not just a downloaded filename or version string.
There is no new installer, activation or machine authority in this contract.
Publication success alone is not ship-to-install completion.

`timing.original_ship_at` equals the actual ship decision time. It is null only
before ship; retain it across resumes and changed candidate attempts for the
same release instruction. Never replace it with a check completion, new attempt
or process start. `preparation_started_at` is separate. Phases record actual
intervals (overlap is allowed), including all post-ship changelog wait, queue,
build/check, publishing and install time; their sum is not the elapsed clock.
`finished_at` is null until publication and matching install are verified; then
it equals install verification time, at or after remote verification and ship.
Elapsed is finish minus original ship, including all waits. Strictly less than
1800 seconds meets P6; 1800 or more is a recorded miss. Missing/failed/blocked
runs remain incomplete. One light actual observation proves only that route
and machine; fixtures and emulated devices never prove delivery or real timing.

## Contract proof, not live acceptance

[Examples and proof map](../tests/fixtures/release/candidate/README.md) cover
P1–P7, including structurally valid refusals. Schema validation does not resolve
pointers, check hashes against external bytes, compare fields, order versions,
prove ancestry, verify native execution or establish permissions. Consumers must
implement those checks at the existing release/collector/kit seams, red first.
The final live ticket alone can supply live receipts and the timing observation.
