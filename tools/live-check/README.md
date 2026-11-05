# Private live-check toolkit (#240)

Python 3.9 standard library. Nothing here is exported. Running a fixture suite
proves fixture behaviour only. Running either driver against a real endpoint
still needs the version's explicit live approval; this ticket runs nothing live.

`core.py` holds the shared guard-owned server swap/restore protocol, process
identity checks, fixed-baseline comparisons, decoded privacy walk and schema
checkers. `observer/` is the unchanged reviewed quick-check/observer dependency,
relocated once so the toolkit does not depend on CI-retained private evidence.
Both drivers import this one implementation. Reports include its SHA-256.

| Profile | Entrypoint | Policy deliberately kept separate |
| --- | --- | --- |
| Send (0.0.3) | `send/scripts/send-kit.py` | Three fixed test threads; `tell.lock`, append-only sitting ledger; external allowance directory and charge journal. Missing history is unknown usage. |
| Create/attachments (0.0.4) | `new/scripts/new-kit.py` | P-A, T-A/T-B and created threads; `writes.lock`, generation ledger; external approval JSON, per-kind charges and budgets. |

Both retain consumed-step accounting across sittings, expiry, post-hold
revalidation, permanent refusal taint, zero-call-only charge release, cumulative
landing checks and publication under the admission lock. No union of read or
write permissions is introduced. The common supervisor receives the explicit
driver path for child re-entry; the guard owns and reaps its own server before
restoration. Its pipe wrapper stops the server if the guard dies. **Guard death
still requires manual restoration of the confirmed old launch.** The shared
restore records the restored process identity and uses PID-specific temp files.

The two schema checkers intentionally preserve the profiles' reviewed contracts:
`schema_error` is send's first-error subset; `Schemas` is new's broader checker
that refuses unknown keywords. Send's legacy contract snapshot is kept under
`test/contracts/`; new uses its explicit `--contracts` directory. Neither parser
is claimed to implement arbitrary JSON Schema.

## Version plans and run sheets

The checked-in `send/scripts/plan.json`, `new/scripts/plan.json` and texts are
**legacy regression fixtures**, not the new version plans. #241 owns `plans/`;
it can pass its data through the existing `setup --plan FILE --texts FILE`
interfaces, keeping the reviewed text-hash checks, stable step IDs, budgets,
faults and claims. New's approval init/show/amend and setup budget flags remain
available. No #241 plan or #274 remote transport is implemented here.

The retained `send/run-sheet.md` and `new/run-sheet.md` demonstrate the reviewed
run-sheet format: approval and cost, setup, CLI groups, guarded swap and web
groups, hands-on answers, restoration, reconciliation and a per-claim wrap-up.
Treat their relative historical evidence links as references to the original
kits under `private/evidence/openwiz-0.0.{3,4}/`, not as new observations.

Use this format for each version:

1. Identify its approved plan, exact code/binary hashes, programs, test targets,
   expected calls and remaining authorization-wide allowance.
2. For each step name the actor, command, expected outcome and stop condition.
   Record the evidence class: fixture, live observation or independent review.
3. Keep the judged set and baseline fixed for the sitting. Record concurrent
   activity separately under that profile's rule; never demote a judged row.
4. Stop on drift, refusal taint, expiry, malformed answer or unknown accounting.
   Disarm and restore before recovery. Retain every sitting and the same
   external authorization; reconcile charges before resuming unconsumed steps.
5. Scan decoded reports before exporting them. Finish with exact call counts,
   restoration evidence and every claim's result and remaining gaps.

## Offline checks

The inherited harnesses must use the reviewed **PATH-based** release source
`660c1692f3343cec36883abd57b5c88237ac5f44` (November 5 live release). Its five
launcher/source hashes match the reviewed `a724d383` guard exactly. Main's production binaries bypass
PATH and cannot be substituted. Both harnesses check the five original source
hashes before any build or binary, even when `KIT_NO_BUILD=1`. New setup also
proves exactly one successful `models` read through X2 before enabling writes.

From the repository root, in an isolated checkout with its own build directory:

```sh
export KIT_SOURCE_ROOT=/absolute/reviewed-release-checkout
export KIT_TARGET="$KIT_SOURCE_ROOT/target"
export CARGO_BUILD_JOBS=2
# Build only the three fixture prerequisites, once:
cargo build --manifest-path "$KIT_SOURCE_ROOT/Cargo.toml" --release --locked \
  -p openwiz-cli -p openwiz-server -p openwiz-tests
export KIT_NO_BUILD=1
export PYTHONDONTWRITEBYTECODE=1
python3 tools/live-check/test_core.py
python3 tools/live-check/test_mutants.py
python3 tools/live-check/audit.py
sh tools/live-check/send/scripts/test/c8-tests.sh
sh tools/live-check/send/scripts/test/kit-tests.sh
sh tools/live-check/send/scripts/test/sol-tests.sh
sh tools/live-check/new/scripts/test/kit-tests.sh
python3 tools/live-check/mutants.py --logs /absolute/evidence/mutants --jobs 1
```

Shell, `ps`, `lsof`, and Linux `/proc` for the new suite's ownership reaper are
required. No browser suite, account or Mac is involved. Run one suite at a time.
The mutation runner copies the entire toolkit into each disposable tree and
never changes working sources or binaries. All 51 send and 54 new mutants move
with it. Each must apply exactly once and fail its named cases with only listed
knock-ons; unexpected greens, missing named failures and runner errors fail it.
`--resume` reuses successful cases only for the exact toolkit snapshot and source
head, with a matching SHA-256 of their complete log. A fresh attempt revokes the
prior result before starting; failures are recorded as failures. Missing,
damaged or older metadata without a log digest requires execution again.
`--profile send|new` and `--only name,name` support affected rechecks; unknown
names are refused. The old `red-runs.sh` entrypoints delegate to it and require `RED_LOGS` outside the toolkit. The optional
legacy dry-run drivers also remain; #241 owns matching new-plan dry runs.

C8's old #642 historical diff test described a queued-only plan that later live
observations superseded. Its relocated entrypoint now checks the current exact
accepted/accepted or queued/queued pairs and refuses every mixed pair; the old
historical proof remains unchanged in its original evidence directory.

#242 wires these entrypoints into CI; this ticket changes no workflow. The full
workspace and browser suites run only in CI, per the standing credits rule.

## November 5 lessons and limits

D240 revision 2 relies on merged #1061 and #1116, not formal acceptance:

- Receipt and provider behaviour drifted; report and stop on unsupported shapes.
  The spawn receipt's extra `runtime` field remains a recorded live gap. This
  extraction does not silently accept it or alter product receipt readers.
- An early phone press taints the sitting. All held writes must recheck that
  taint before dispatch; a new sitting inherits remaining authorization only.
- New's judging is confined to quiet cold sessions in P-A, fixed for the whole
  sitting. Factory changes elsewhere are counted but not judged. Send retains
  its existing cold-session rule; L13 needed a quiet window on the PC.
- New carries landing expectations and new-thread records from earlier sittings,
  including a refresh at run entry. This does not complete unfinished checks.
- Cross-sitting parity/receipt aggregation, real network cuts/radios, broader
  Safari coverage, R-2 without P-N and Jake's J6 acceptance remain unproved.
  Agent/device emulation does not supply Jake's acceptance.
- Lost authorization records require reconciliation with Jake, never silently
  renewing the allowance. Recorded partial results stay incomplete.

Provenance and current commands/results are in
`private/evidence/infra-live/lt1/`. No new dependency or Rust crate is changed.
