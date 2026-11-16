# Combined agent live smoke (#1844)

**Every fleet tick runs only as a saved, audited plan.** Review R2 showed that
preview/output checks cannot restrict the tick: it recovers and replans before
effects. The runner therefore never launches `openwiz fleet tick --json` itself.
It establishes #2216's restriction (`restriction.py`) over #1892's
`--expect-plan`: the installed catalogue must offer it, one dry-run preview must
pass the step's `actions_in` audit, and the tick then executes that saved plan or
refuses before any effect, including recovery. If the restriction cannot be
established the step refuses (`restriction_unavailable`, `invalid_plan`,
`out_of_scope`, `unsafe_plan_dir`, `plan_exists`) and consumes nothing.
Fixture/dry-run success cannot publish the combined release.

**Prepared, not run live.** ADR 0019, approved on #1844, makes one combined
agent smoke the pre-publish gate. This tool executes a reviewed run sheet;
fixture success or a dry run is not a live pass. It never publishes, tags,
installs, activates a service, changes permissions or pushes a release branch.
No dependency is added. Python 3 on Linux, the accepted prebuilt programs and
existing PC kit are used; browser steps use the project's approved
`playwright-core` and the installed Chromium.

Start from PR #1765's `private/evidence/release-prep/common-live-check.md` and
version plans, `.claude/skills/live-quick-check/SKILL.md`, ADRs 0016/0019, and
`docs/live-checks/0.0.12.md`. ADR 0019 supersedes the old per-version/human gates;
ADR 0016 supplies throwaway-only writes and phone emulation. Keep the existing
AC6 scratch fleet's approval, targets, state and counts. Do not reuse a real
orchestrator, start another scheduler or run a manual tick beside the service.

## The standard sheet: SHIP-3's scope (#772)

`combined.template.json` is cut to exactly what the first public release's
live smoke checks (SHIP-3, Jake, 2026-11-15; private record ClosedWiz #325,
comment 6902037613). It declares `"claims": ["install", "json", "send", "new"]`
and has these ten steps, nothing else:

| Claim | Steps | What they check |
| --- | --- | --- |
| `install` | `install_status` | The build the normal route (`tools/install/install install`) selected: `install status` reports `installed`, the `packaged` channel and the candidate's version, source, target and build |
| `json` | `catalogue`, `inventory`, `show` | `openwiz help --agent` is the accepted catalogue; `openwiz ls --json` is a complete inventory; `openwiz show <throwaway> --json` reads that session |
| `send` | `send_preview`, `send_once`, `send_lookup` | One message to one throwaway thread, previewed, sent once and read back by its op id |
| `new` | `new_preview`, `new_once`, `new_status` | One new Cloud thread in one throwaway project, previewed, created once and read back by its op id |

A receipt from this kit covers only these steps. Anything a version's notes
claim beyond them (the fleet, the service, Cockpit, Loops, Decisions, the
phone reply, the terminal app, App permissions, read safety controls) is
**not** live-tested by it; the kit's `release.coverage` names promises only for
these steps, and its `release.gaps` lists the rest.

The runner keeps its general capabilities (the fleet-tick restriction, the
reviewed browser/cleanup probes) for kits without a `claims` declaration, which
mean #1844's full combined set. The sections below on those describe the runner,
not this sheet.

## Prepare once, offline

The install happens first, through the normal route, into throwaway
`--root`/`--state-root` folders from the candidate's verified packages; the kit
then pins that build's `openwiz` (`<build>/openwiz`) by its candidate hash.
The Local PC agent supplies the kit's private inputs, **outside Git**, under an
owner-only run directory. `inputs.py` assembles them: each `--records` file is
an owner-only JSON object of named values copied from the existing private
records; records merge, and one name with two different values refuses
(`conflicting_record`). It writes one new owner-only inputs file outside any Git
checkout and prints only counts. `prepare.py` replaces an entire JSON string
`@name` with that named input value (including arrays/objects). No shell
expansion or string interpolation. It reads the inputs file only by an absolute
path, owner-only (mode 0600 or tighter, `inputs_not_owner_only`) and outside
any checkout as the OS resolves the path, symlinked folders before any `..` (`inside_checkout`, also for the kit); a `..` past the deepest existing folder refuses (`unsafe_path`). A missing or unused input
name refuses and prints only the names (`missing_input`, `unused_input`); a
GitHub token or private key anywhere in the inputs refuses
(`credential_in_inputs`). It prints the kit digest and the `release.scope`
digest the sealed candidate must carry (`scope_sha256`). The agent checks the
bound argv, scope, exact comparisons and write counts against its existing
version-level standing OK, then records the printed kit digest with that
approval. This is the digest of canonical JSON, not the digest of the
pretty-printed file.

```sh
umask 077
python3 -I tools/live-smoke/inputs.py --records /private/records/a.json --records /private/records/b.json --out /private/run/inputs.json
python3 -I tools/live-smoke/prepare.py --inputs /private/run/inputs.json --out /private/run/kit.json
python3 -I tools/live-smoke/smoke.py --kit /private/run/kit.json --state /private/run/checkpoint --dry-run --candidate /private/run/candidate.json
```

`--dry-run` validates the whole sheet, pinned files and source checkout; with
`--candidate` it also checks that candidate carries this kit and scope
(`candidate_mismatch`). It runs no product/probe command or API and creates no
checkpoint; live-mode provenance verification uses local read-only Git
commands. Every declared claim is `not_run`; the output is a structure-only
plan report. Preparation refuses to overwrite a kit. Never put tokens in
inputs/kit or argv. This sheet has no App-permission step, so it needs no
`OPENWIZ_SMOKE_APP_TOKEN`; token values in the kit environment are refused.

**Never 7370 (#772).** On the PC, 7370 is my.openwiz.dev's server. Any step
that reaches 7370 (`--port 7370`, the HTTP probe's port, a browser config
origin), the old `default_terminal_port` key, or a launch that falls back to the
default port (bare `openwiz`, `openwiz ui` without `--port`, bare
`openwiz-terminal`) refuses before any step (`reserved_port`).

The 27 inputs, all from existing records, never guessed:

| Binding | Source |
| --- | --- |
| `mode` | `live` on PC; `fixture` only for synthetic proof |
| `cwd`, `env` | An owner-only working folder outside any checkout, and the stable absolute `OPENWIZ_STATE_DIR` of the throwaway install (`install_state`); isolate it from normal work |
| `python`, `openwiz`, `install_entry` | Absolute programs: the runner's Python, the installed `<install_build>/openwiz`, and the clean checkout's `tools/install/install` |
| `install_root`, `install_state`, `install_build` | The normal route's `--root` and `--state-root`, and the `build` its `install` printed |
| `release_version`, `release_source`, `release_target` | The candidate's version, source commit and target, from its sealed body |
| `artifacts` | Every program/script absolute path to its previously verified SHA-256: `openwiz` (the candidate's product hash), Python, `tools/install/install`, and `smoke.py` and `restriction.py` themselves; never build during the run |
| `source` | `{ "checkout": "/accepted/source", "head": "<40 hex>" }`; clean accepted source, independently matched to the candidate |
| `expected_catalogue_commands` | The accepted CLI catalogue's `commands`, from the candidate's source, not from the program under test |
| `send_thread`, `project` | Already approved throwaway thread and throwaway project |
| `send_op`, `new_op`, `harness`, `model`, `effort` | Fresh recorded operation ids and choices actually offered by cloud-options; never reuse an uncertain attempt |
| `send_preview_checks`, `send_lookup_checks`, `new_preview_checks`, `new_status_checks` | Exact expected target/settings/effects and recorded acceptance/creation plus separately observed start; no paused-queue/duplicate acknowledgement implicit in this kit |
| `release` | The release section for candidate-bound receipts (below): `scope` (`targets`, `writes` `{"send": 1, "new": 1}`, `app_permissions` `[]`, `spending_cents` 0), the candidate `products` its pinned programs are, `coverage` rows naming only these steps, `risk` step lists and `gaps` naming everything above that this kit does not check |

## Run and resume: the same one command

After the live kit's version-level standing OK and read-only endpoint discovery,
the Local PC agent runs (the builder of #1844 does **not** run it):

```sh
python3 -I tools/live-smoke/smoke.py --kit /private/run/kit.json --state /private/run/checkpoint --execute APPROVED_KIT_SHA256 --candidate /private/run/candidate.json
```

`--candidate` binds the run, before its first step, to one sealed release
candidate whose `kit.sha256` and `kit.scope_sha256` are this kit's and its
scope's (`candidate_mismatch` otherwise). Every resume must give the same
candidate (`candidate_changed`): a rebuilt candidate needs a new run in a new
state directory. A run without it can resume but yields no receipts
(`unbound_run`).

In live mode a fleet-claim write is only the canonical tick or the whole
reviewed invocation of one of this folder's probes: a real `node` program
(ELF, not a script) running `browser.mjs` with one config argument, or the
runner's own Python running `-I cleanup.py --gh <ELF program> --repo R
--ticket T --action unlabel|close`. A wrapper, even one whose arguments name a
reviewed probe, is refused before any step. Each tick step needs an `actions_in` audit
at exactly `/actions`, and no audit may name another path. With a `release`
section, every write attempt, repeats and uncertain attempts included, counts
against `release.scope.writes` for its claim; the next would-be attempt over
that bound returns `write_limit` before any preview or effect.

Beside the checkpoint the runner appends `journal.jsonl`: owner-only,
fsynced, hash-chained lines recording the start (kit, candidate, mode, source
head, runner and restriction hashes), each attempt, each step outcome with its
exit code, output digest and bounded observations (per check: a value digest,
the listed string, or the audited actions; never raw output), each repeat and
the finish. Every transition is journaled first and then applied by one
function to the checkpoint, which is only its cache. On resume the checkpoint
must equal the journal's replay, or lag it by the one event an interruption
left unapplied, which is then adopted and never redone; anything else is
`invalid_state`. Replay refuses events the runner could not have written:
out of order, a pass with another exit than the step's, or observations that
fail the step's own checks.

Exit 0 with `evidence: live` and every claim `pass` is a live smoke pass at the
pinned build; only a receipt (below) carries it to the release command. Exit 1 is
a known wrong comparison, exit 2 a refused input/artifact, exit 3
incomplete/event/uncertain or an unestablished restriction. All three nonzero
exits block the smoke gate. Execution verifies hashes/source and runs the actual
`openwiz ls --json` source path before any step. Help/version output does not
check the bundle.
A failing/missing/ambiguous PC bundle (#118) yields `bundle_preflight`; no step
or write runs. Fixing the installed bundle lets the same command start. There
is **no RL1 override here**: only the product's reviewed, conditional exception,
if separately implemented, can make its own guard pass. A version string is
never a gate. Fixture environment variables are refused for a live kit.

The fixture progression has two bounded fleet blocks. Each executes one tick
then returns `next_event`. End the turn; the existing tick/orchestrator event
resumes the same command. The first block stops at two strict merges with T3
awaiting its phone reply. Then the approved phone reply runs once, its delivery
is read back, and individually checkpointed `cleanup.py` invocations perform
`gh issue edit T3 --remove-label needs-info` and `gh issue close T3`, each with a
separate verified readback. Nested gh readback uses file-backed stdout capped
before decode by the runner limit and any tighter inherited file limit; stderr
is discarded. Oversized/failed readback leaves that cleanup attempt uncertain
and never replays its write. Only then can the second block tick to final summary
and spec closure. Reply/cleanup are outside both repeat blocks and never replay.
A failed/unknown cleanup prevents all final ticks.

Both blocks share AC6's 60-tick/three-hour cap. Incomplete progress returns at
once; on another event readback is checked before another tick. Each tick
re-establishes the restriction: a fresh preview, the scope audit, an exclusive
owner-only plan file in the state directory, then `fleet tick --expect-plan
<plan> --json` once; the plan file is removed after the launch. The `attempting`
checkpoint is saved between the two. A product refusal, a report other than the
saved plan or any action outcome but `done` consumes the attempt
(`uncertain_write`) and is never relaunched. A plan file left by an interrupted
run refuses every later tick (`plan_exists`) rather than being reused. No sleep,
watcher or CI polling loop.

A write's `attempting` checkpoint is fsynced **before** dispatch. Interruption,
timeout, bad output or unknown result permanently consumes that attempt; resume
returns `uncertain_write` and does not send/create/tick again. The orchestrator
reconciles via existing lookup/status/strict readback; never delete/edit the
checkpoint to retry a write. Known completed steps are skipped. A changed kit or
artifact refuses resume; a failed comparison stays failed. Every command requires Linux child-subreaper support, `/proc` child ownership
and pidfds before launch. Children cannot gain privileges through exec. Timeout/exit cleanup adopts and kills all owned
children across `setsid`, then reaps them before returning. It uses only this
runner's child tree and pidfd identities, never a global process-name kill.
Containment unavailable/failure stops incomplete; process groups alone cannot
contain the existing PTY driver. State is owner-only,
locked, atomically replaced and fsynced, with only claim states, counts, times,
and hashes of needed comparison facts. Raw stdout/stderr/transcripts, ids,
private paths, prompts and credentials never enter reports/checkpoints.

## Browser and terminal observations

Runner capability for combined kits; the SHIP-3 sheet has no browser or terminal step.

`browser.mjs` takes one pinned private JSON config: `checkout`, `chromium`,
`origin` (`http://127.0.0.1:PORT/` only), `viewport` (desktop or 390x844 phone),
`allowed_requests` (exact `[method, path]` pairs), `max_writes` (0 or 1), optional
`allowed_host` (the server's configured host), and `steps`. Each step has `kind`
and either a CSS `selector` or exact accessible `role`/`name`. Kinds: `click`,
`fill`/`press` with `value`, `visible`, `text`, `attribute` with `attribute`,
`count`, `viewport` with `value`, and `offline` with a boolean `value`.
Visible/text/attribute/count append observations to `facts`; the run sheet
compares the **exact** resulting array. It also compares zero errors and the
exact write count. Unknown requests abort before dispatch; no external pages,
screenshots or saved browser profile. Chromium/context always close. The local
Host/Origin emulation is recorded as a gap for real TLS/radios/WebKit.

- Loops: desktop Views → Loops; wait for the reviewed loaded row selector, expand
  healthy rows, compare every row/order/value to independent definitions/records.
  Resize to phone; compare retained rows. Read-only config has `max_writes: 0`.
- Cockpit: Views → Cockpit; compare exact Needs you and agent/project rows, inspect
  one approved target/preview, cancel, verify no POST. Phone viewport retains
  the grouping and honest gaps. Read-only config has `max_writes: 0`.
- Decisions: navigate to Decisions; inspect the designated current ordinary
  synthetic request, exact wording/target/effects, fill one harmless reply,
  preview and confirm **once**. Allow exactly that target's messages POST;
  `max_writes: 1`. Read back delivery and the orchestrator's saved source record
  on a later event (`await`), never resend to make it resolve. Do not exercise a
  live/release/publish approval. Optional network-cut observations consume no
  extra write and uncertainty stops the run.

PTY input is the existing driver's JSON list (`wait`, `send`, `resize`), **no
`sleep`**. Explicit `ui --port` visits Home, `s`, Enter/detail, Esc, `f`, detail,
Esc, small/back resize, `q`. The default no-argument entry would reach 7370 and
is not a kit step (above).
Wait for actual named visible states with bounded timeouts; compare every step,
exit 0 and `restored: true`. No typed send/new in these read-only PTY parts.
The AC6 kit consumes its already approved one phone-composer reply, followed by
its two individually checkpointed GitHub cleanup operations. Separately the
0.0.12 kit consumes its two sends (decision answer + CLI message) and one CLI
create. The combined sheet therefore schedules three sends across these two
existing kits, one create, AC6's scoped fleet actions and its existing T3 cleanup;
no kit gains an extra attempt or retries. The message guard accepts both healthy
`accepted` and `queued` reports with the same target/op/mode/replay checks; it
never sends again to turn Queue into acceptance. Ready new-preview expects exit
12 and creates nothing. A separate extension that
moves send/create into the TUI must replace those same steps/budget, not add them.

## Candidate-bound receipts

`receipt.py` turns the checkpoint into the
[release candidate](../../contracts/release-candidate.v1.md) contract's `smoke`
and risk gate receipts. It reads files only: it runs no step, grants nothing and
retries nothing.

```sh
python3 -I tools/live-smoke/receipt.py produce --kit /private/run/kit.json --state /private/run/checkpoint --candidate /private/run/candidate.json --record <safe-reference>
python3 -I tools/live-smoke/receipt.py check --gate smoke --receipts receipts.json --candidate /private/run/candidate.json --kit /private/run/kit.json --state /private/run/checkpoint
```

`produce` refuses unless the kit digest and its `release.scope` digest are the
candidate's `kit.sha256` and `kit.scope_sha256`, each declared candidate product
payload is a pinned kit artifact, and `release.coverage` has exactly one row of
bounded steps per live included (version, promise): one whose version's notes
section has a line starting `Live-checked` (#18). Every other included promise is
carried in each receipt's `gaps` as `Not live-checked in this release: <version>
<promise>`, never as covered and never dropped; a kit row for such a version
refuses `not_live_covered`, and an included version with no notes section
`coverage_mismatch`. Notes are split only on LF, their approved line ending;
notes holding any other line or paragraph break (CR, NEL, U+2028, U+2029 and the
other breaks `str.splitlines()` honours) refuse `invalid_notes` (#915 R1). `produce` also refuses a run bound to another
candidate (`candidate_changed`) or to none (`unbound_run`), a missing journal
(`evidence_missing`), and a journal whose chain, start record or replay does not
yield the checkpoint's step states and consumed writes exactly
(`evidence_mismatch`), or consumed writes over the scope (`scope_exceeded`). A
receipt binds the candidate, artifact inventory and kit digests, its complete
inputs digest (step states, coverage, tested products, scope, consumed writes,
journal digest, `expect-plan` restriction) and, as its evidence hash, the
journal's digest under the given reference. `produce` also prints the
`preserve` line (`openwiz.live-smoke-evidence.v1 journal=… candidate=… kit=…`)
to post in the run's private record once it finishes, with that record's
comment pointer as `--record`. Times come
from the checkpoint. Fixture kits give `fixture` receipts and an unrun state a
`dry-run` receipt; unfinished, failed or consumed-uncertain steps give
`incomplete`, `fail` or `uncertain`. Every receipt keeps the kit's `gaps` and the
fixed PC-only gap: a PC run is never a Mac or real-device observation.

Risk: each of `send`, `new`, `app_permissions` and `spending` classified `yes`
needs steps of its own claim (`send`/`new` with a write, `app`; this kit has no
spending check, so a spending change refuses `risk_missing`); `unknown` refuses
`risk_unknown`; `no` yields no receipt. `scope` is exact: throwaway `targets`,
`writes` per claim (the kit's write steps may not exceed them), the
`app_permissions` the existing grant already holds (`name:read|write`, no
wildcard) and a bounded integer `spending_cents`. The receipt only records that
scope; approval or a ship instruction never widens it.

`check` accepts only a `live`, `pass` receipt with a finish time, bound to this
exact sealed candidate, artifacts, kit and scope, whose inputs digest matches,
whose coverage is every live promise passing (or, for a risk, its covered promises)
and which keeps every gap, including each not-live gap. It then reads the evidence itself: the receipt must be
exactly what the approved kit, checkpoint and journal produce now, so a
relabelled or edited receipt, or evidence that no longer shows the pass,
refuses. Finally it resolves the record independently (the command line reads
the private comment through `gh api`; a synthetic record never resolves): the
record must carry this journal's `preserve` line and be created at or after the
run finished, or `evidence_unresolved`. A local journal its owner could rewrite
is therefore never enough alone; the independently timestamped record is.
Otherwise it names the reason: `missing`, `invalid_receipts`, `not_live`,
`not_pass`, `stale`, `inputs_mismatch`, `coverage_mismatch`, `gaps_missing`,
`evidence_mismatch`, `evidence_unresolved`, `risk_unknown` or a `produce` refusal. The release command (RL2) applies the same reading; live
receipts come only from the final release ticket's real run.

## Evidence and local proof

The command prints one structure-only JSON report: per-promise pass/fail/
incomplete/not_run, kit hash, passed-step count and fixed reason enums. Preserve
it with source/build/script provenance under the approved run's evidence path;
scan the final report against locally collected private identifiers before
committing. Fixture mode always says `evidence: fixture`; a dry run never passes
the live gate. Keep existing accepted W3, real-device and Mac-specific gaps
explicit; a PC run never becomes a Mac observation. Under ADR 0020, after
verified cut-over, publishing needs only Jake's ship instruction and exact
changelog approval; this smoke and its receipts are automatic agent gates and
add no per-step human approval. Before cut-over nothing here publishes.

```sh
python3 -I tools/live-smoke/test_smoke.py
# Optional integration, only with these prebuilt synthetic fixture programs:
python3 -I tools/live-smoke/test_fixture.py --cli target/debug/examples/openwiz --fake target/debug/fake-room-cli
python3 -I tools/live-smoke/test_fixture.py --cli target/debug/examples/openwiz --fake target/debug/fake-room-cli --case ready-preview
python3 -I tools/live-smoke/test_fixture.py --cli target/debug/examples/openwiz --fake target/debug/fake-room-cli --case queued-send
python3 -I tools/live-smoke/test_review.py
python3 -I tools/live-smoke/test_kit.py          # #772: declared claims, owner-only inputs, 7370 refusal
python3 -I tools/live-smoke/test_receipt.py      # also registered in tools/release/test.py (CI)
python3 -I tools/live-smoke/test_restriction.py  # #2216's; registered there too
node --check tools/live-smoke/browser.mjs
cargo fmt --check
```

No Rust crate changes and no clippy target. No full workspace/browser suite,
watcher, live call, publish, tag or release-branch push belongs to this ticket.
