# Version plans (#241)

Private, Python 3.9 standard library. These are the first version plans for
spec #239 K2. Nothing here is exported or authorizes a live run.

- `0.0.3.json`: send's 17 groups / 47 steps, 23 tells.
- `0.0.4.json`: creation/attachments' 16 groups / 37 steps, 4 spawns and 2 tells.

Each file retains its toolkit legacy plan's exact steps, stable IDs, faults,
claims, text labels and expectations, with an explicit `budget`. The reviewed
synthetic texts remain `../send/texts.tsv` and `../new/texts.tsv`; the drivers
verify their exact approved hashes. The data still contains the historical
`claude-code` **fake fixture provider**; no Claude agent is started.

The toolkit already accepts these files through `setup --plan FILE --texts FILE`.
New's sitting budget maps to `--budget-creates` / `--budget-sends`; send's maps
to its existing external allowance manifest. In the offline runner below these
values come from the plan. Live approvals, reconciliation and recovery remain
the inherited run sheets' separate requirements. Changing this data never grants
permission, renews an allowance or completes a live acceptance claim.

## Offline proof

Use LT1's reviewed PATH-based source and three fixture prerequisite binaries
(see `../README.md`); do not substitute main's bundled production launchers.
No Rust build happens inside the plan runner. From the repository root:

```sh
export KIT_SOURCE_ROOT=/absolute/reviewed-release-checkout
export KIT_TARGET="$KIT_SOURCE_ROOT/target"
export PYTHONDONTWRITEBYTECODE=1
python3 tools/live-check/plans/test_plans.py
python3 tools/live-check/plans/dry-run.py --profile send --log /tmp/lt2-send.log
python3 tools/live-check/plans/dry-run.py --profile new --log /tmp/lt2-new.log
```

Run one integration dry run at a time. The send run takes about four minutes;
the new run takes about two. These use fake account fixtures and private temp
state, plus loopback fixture servers, whose inherited cleanup stops only owned
processes. Jake's answers and device/network actions are simulated. None prove
live behaviour, real radios, browsers or Jake's acceptance.

`dry-run.py` invokes the inherited full run-sheet harness, preserving its calls,
exit checks, landing, faults, privacy, allowance and restoration assertions.
It selects the new data with `--plan` in a temporary copy of the shell harness;
new's contracts and the checkout identity checks use the same historical source
as the fixture binaries. The actual kit entrypoint remains importable by the
existing hands-on simulator. It changes no toolkit source. The original count assertions remain independent
checks against the legacy regression plans.

The `*.recorded.json` fixtures project the independently recorded dry runs:
source paths and SHA-256 identify their provenance. They retain every ordered
step/action, exact call/attempt count, verdict and stable observed result.
Elapsed milliseconds, intermediate busy samples (`stages`) and runtime report
paths are excluded; those vary by host or scheduling. Step output-presence
fields (`report: none`) remain part of the comparison. The two named race steps
compare permitted
exit histograms and valid outcomes rather than child order/first-child selection,
while retaining exact process counts, calls, attempts and final landing.
The inherited tests still
check stages/landings against each plan's expectations. The send baseline is the
later **P1/P1b split** recording, including the corrected C8 queued receipt;
earlier recordings predate those reviewed changes. No private evidence file is
needed at runtime, so CI pruning cannot silently drop a proof.

The runner rejects changed budgets or ordered steps before executing fixtures,
and binds complete group/step bodies to the reviewed legacy-plan SHA-256. Targets,
texts, claims, faults and expectations cannot drift under an unchanged step ID.
It then compares actual results to that independent recording. `--plan FILE` accepts
a candidate for negative checks; a changed budget/step exits 1 with a specific
diagnostic. Same-ID target, expectation and fault changes also fail. Duplicate
JSON keys and non-integer budgets are refused. The unit suite exercises these
mutations for both versions and
proves a zero-exit/empty, missing, duplicate, extra-call or changed-outcome
report cannot pass the comparison. A child failure exits 1, never success.

#242 can invoke these commands when wiring CI; no workflow is changed here.
