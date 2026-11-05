# Skill A/B: offline controls and analysis

EB8-O (#2235), under spec #1383. These sections describe offline synthetic
controls only. #2179 owns the real inputs, frozen protocol, method review,
admission/assignment integration and live result. No real protocol or experiment
is supplied here. Implementation approval, a passing fixture, a conforming hash
or an injected approval fact grants no live, paid-eval, spending, activation,
release, publishing or merge authority. Existing holds, independent exact-head
review, required CI and verified merges remain mandatory.

## Offline controls

`tools/factory-metrics/experiments/controls.py` consumes explicit validated EB5
bundles and bound journey v1 snapshots. It reuses their formats, frozen hashes,
CF4 references and append-only transition validator; it collects nothing and
starts nothing. The EB5 execution stubs remain unavailable. Its public seams:

- `launch_check(bundle, journey, at=..., safeguards=...)` checks injected facts
  only: passed research/compatible CF4/candidate-selecting replay, reviewed
  preregistration and its separate live approval, before the fixed horizon.
  Explicit true facts must preserve holds, independent review, required CI and
  verified merge. Missing or unknown facts refuse; there is no override flag.
- `assign(..., ticket, at=..., eligible=True, safeguards=...)` returns a new EB5
  bundle. Odd gets candidate, even gets old, with the frozen arm revision and
  protocol hash. It refuses known earlier builder work, first push, independent
  verdict or merge. An exact repeated request returns the same assignment;
  changing its timestamp or revision is not a retry. Assignment is saved before
  any future consumer may start work. Actual revision changes and overlaps append
  to `deviations`; they never rewrite intended exposure or remove an assignment.
  Established assignment-to-PR associations cannot silently move between arms.
  A newly discovered first push predating assignment is retained with a material
  `other` deviation citing that receipt, deduplicated on resume.
- `advance(before, before_journey, after, journey, at=...)` consumes injected
  event snapshots, checks immutable history, fills a previously unknown work
  start once, and calculates harm. It accepts new observations/deviations, not
  caller-written assignment or result summaries. Local event/source ids may
  renumber; retained independent verdicts compare by PR, source URL and meaning.
- `handback_check(..., record, current, at=..., safeguards=...)` joins the
  precheck to the assigned arm and protocol's exact CF4 result keys, then calls
  the existing precheck assessor on independently supplied current facts. Missing,
  failed, stale, finding-bearing or unclean results block. `ready` means only
  offline conformance; it is never an independent approval or review round.

All references and gate facts are assertions supplied by the fixture/caller.
#2179 must verify actual pinned bytes, source coverage, permissions and approvals
through the existing CF4/replay/precheck seams before any live use. This tool
adds no fleet-skill hook, evaluator, loop, watcher or approval policy.

## Offline harm stops

`advance` evaluates incoming canonical journey facts at their event times. It
also evaluates rolling-window expiry boundaries on each event/resume, so a delayed delivery cannot hide a
harmful interval that has since expired. Helpers and `duplicate_of` verdicts
never count. Before aggregation or checkpoint acceptance, every verdict source
URL is bound to one owning PR and its semantic fields across the whole journey.
Cross-PR reuse or conflicting meaning refuses regardless of PR order. Identical
deliveries within the owning PR count once. Distinct independent reports at the
same head count separately.

The offline convention for doubled rounds is the mean count of independent
verdicts per distinct assigned PR with at least one independent verdict in
`(event_time - window_hours, event_time]`. The exposure threshold counts distinct assigned tickets represented by those
active PRs, not individual verdicts, inactive assignments or helpers. Multiple
PRs for one ticket cannot inflate exposure. A shared PR is
one PR observation. Assignment must precede the counted event. The reference,
window, minimum exposure and inclusive `mean >= 2 * rounds_reference` boundary
come from the frozen protocol. Fractional-second expiries round up to the next
representable UTC second. This exact convention needs to be included in
#2179's reviewed protocol; shape-valid prose alone does not settle a real design.
Ambiguous ticket/PR units require resolution before use.

An attributable canonical `main-red` event stops its exposed arm regardless of
rounds. Timing alone is insufficient attribution. Unknown/unattributed events
do not become zero defects; a later sourced attribution resolution triggers the
stop when the attribution becomes known. Repeated deliveries retain one first
stop per kind/arm. Both kinds can be retained in one checkpoint.

Harm produces EB5's terminal `stopped`/`harm` result, with source, exposure and
observed value; unestimated effects remain null. It cannot be erased on restart.
This implementation refuses further assignments after a terminal result or a
completed live stage (`pass`, `fail`, `stopped`, `inconclusive`), including when
that stage has no result summary. Only `not_run` or `partial` can admit another
assignment under the other gates. Checkpoint transitions cannot append an
assignment to a completed stage. There is no resumption command. Existing authority must decide any later resumption;
a repeated request is not that authority. Favorable interim effects never cause
an efficacy stop. A non-stopped analysis before the horizon refuses.

## Offline checkpoint commands

Run the tool explicitly on synthetic local files:

```sh
python3 -I tools/factory-metrics/experiments/run.py init \
  --bundle SYNTHETIC_BUNDLE.json --journey SYNTHETIC_JOURNEY.json \
  --checkpoint SYNTHETIC_CHECKPOINT.json
python3 -I tools/factory-metrics/experiments/run.py assign \
  --checkpoint SYNTHETIC_CHECKPOINT.json --ticket 4301 \
  --facts SYNTHETIC_FACTS.json --at 2030-01-05T00:00:00Z
python3 -I tools/factory-metrics/experiments/run.py advance \
  --checkpoint SYNTHETIC_CHECKPOINT.json --bundle NEXT_SYNTHETIC_BUNDLE.json \
  --journey NEXT_SYNTHETIC_JOURNEY.json --at 2030-01-06T00:00:00Z
python3 -I tools/factory-metrics/experiments/run.py analyze \
  --checkpoint SYNTHETIC_CHECKPOINT.json --at 2030-02-01T00:00:00Z
```

Assignment facts contain exactly `eligible` and `safeguards`; safeguards contains
exactly `holds_clear`, `independent_review_required`, `required_ci` and
`verified_merge_required`, each true. These are injected offline facts, never a
substitute for the ordinary admission process. `check --checkpoint FILE` only
reads. There is no launch, activation, dispatch, retry or spending command.

The local checkpoint wraps only `{bundle, journey}`, preserving journey v1's
key order and explicit hash binding. `save_checkpoint` writes an owner-only
temporary file, fsyncs it, replaces atomically and fsyncs its directory. An
exclusive lock and expected prior pair digest refuse stale/competing writes.
A crash can leave a lock: inspect it explicitly rather than clearing it by
elapsed time or silently repeating work. Duplicate JSON keys/nonfinite numbers
refuse. A failed validation leaves the old checkpoint intact. Keep operational
identities and machine/evidence routing separately in private resumable state.

## Offline fixed-horizon analysis

`analysis.power_plan(power, guards)` reproduces EB5's equal-variance normal
planning approximation: `ceil(2*(z_alpha+z_power)^2*SD_hours^2/effect_hours^2)`.
The minimum is at least the largest time, rounds and defects minimum. With
alpha .05, power .8, SD 3 hours and effect 2 hours, time n is 36; the unchanged
EB5 guard example raises it to 72. The guard minima are independently reviewed
inputs, not estimates from the time SD. Missing baseline/guard support still
blocks #2179. This approximation is not a power guarantee for bounded/censored
time, a rare-event guard, deterministic allocation or correlated tickets.

`analysis.analyze(bundle, journey, at=...)` returns a new EB5 bundle plus
explanatory diagnostics. Every assigned ticket remains in its arm. It derives
horizon sample counts, timing unknowns and defect maturity from the journey,
rather than trusting a supplied summary. The current state field does not prove
closure by the horizon. Because journey v1 has no sourced closure timestamp,
nonmerged tickets remain in the `open` (right-censored) horizon bucket, including
current closures; `closed_unmerged` counts no evidenced horizon closures. This
means unavailable closure evidence, not proof that no closures occurred.
Diagnostics label `closure_by_horizon: unavailable` and separately count
`current_closed_unmerged`, retaining all assignments and current closure facts. Defects need complete frozen
follow-up and known attribution for every merged unit; any unfinished unit,
unknown attribution or immature coverage leaves that risk comparison unknown.

The supported method names are exact frozen values in EB5's existing text
fields. No new experiment/result schema is introduced:

| Field | Supported value |
| --- | --- |
| `primary.statistic` | `restricted-mean-hours-v1 tau=24` (positive finite numeric tau, in hours) |
| `primary.test` | `bounded-mean-hoeffding-v1` |
| `primary.unfinished` | `right-censor-at-horizon; closed-unmerged=tau; all-assigned` |
| `primary.missing` | `unknown-effect; censoring-bounds; parity-is-not-random` |
| `guards.rounds.test` | `welch-independent-rounds-v1` |
| `guards.defects.test` | `bonferroni-wilson-risk-difference-v1` |

These names describe implemented offline choices, not a reviewed live protocol.
Existing EB5 example prose remains unchanged; an unsupported method refuses,
and an approved protocol must never be relabelled to make this engine accept it.
#2179's independent method review must settle suitability and all assumptions
before approval. A different method needs its own reviewed implementation.

The time estimand is the mean of `min(first-push-to-merge hours, tau)`. A verified
merge supplies an exact bounded observation. For an open PR right censored at
the horizon, its value lies between `min(age since first push, tau)` and tau.
The frozen closed-unmerged-at-tau rule requires sourced evidence of closure by
the horizon. That evidence is unavailable in the current v1 format, so current
closure alone never collapses the bound to exact tau: it retains the same right
censoring bounds as unfinished work. Exact tau is still known if the observed
censoring age reaches the restriction. A future source-backed horizon-state
interface remains separately reviewed work; this implementation adds no field to
the shared contracts and claims no closure-time evidence. Diagnostics report the
corresponding arm-mean and difference bounds. The point values are
explicit upper-bound imputations, not observed uncensored means or Kaplan-Meier
estimates. The interval spans every compatible completion, expanded on each
side by `tau*sqrt(log(2/alpha)*(1/n_old+1/n_candidate)/2)` and bounded to
`[-tau,tau]`. Missing timing leaves the whole time effect unknown; no PR/commit
date is substituted. Shared or multiple PR units yield unknown effects instead
of an independence claim. This is intentionally conservative partial
identification, with no censoring-independence assumption. The concentration
bound still requires independent bounded ticket outcomes. See
[Hoeffding's original report, theorem 2](https://repository.lib.ncsu.edu/bitstreams/d0e6ed15-3e1c-432f-8419-e55ffb6f3171/download).

Round effects compare all observed independent per-ticket counts through the
horizon using a Welch-Satterthwaite t interval. Fewer than two observations per
arm or zero estimated variance yield unknown uncertainty, not exact safety.
The t CDF uses the incomplete beta function with convergence checks; it never
falls back to a normal critical value. Normal-sample and independence assumptions
need review, especially for small or skewed round counts. Formula:
[NIST difference-of-means intervals](https://www.itl.nist.gov/div898/handbook/prc/section3/prc312.htm).

Defect effects are the proportion of units with any attributable canonical root
cause in the frozen follow-up window. Repeated manifestations of a root cause
do not increase risk. Component Wilson intervals use `z(1-alpha/4)`; subtracting
the old upper from candidate lower and old lower from candidate upper gives the
Bonferroni risk-difference interval. This is approximate binomial coverage,
not an exact rare-event guarantee; zero events retain nonzero uncertainty.
Formula: [NIST proportion intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).

All effects retain actual units, candidate-minus-old differences, percentages
(null at zero baseline) and intervals. Improvement requires the existing EB5
rule unchanged: sufficient n, known timing, mature merged follow-up, time upper
bound below zero, both guard upper bounds at most zero and widths within their
frozen bounds, and no material deviation/confounder. A positive guard lower
bound records harm. Otherwise the outcome is inconclusive. Lack of significant
harm alone proves no safety. All diagnostics retain parity/comparability and
statistical limitations; no synthetic result claims real improvement.

## Offline verification

```sh
python3 -I tools/factory-metrics/experiments/test_controls.py
python3 -I tools/factory-metrics/experiments/test_analysis.py
python3 -I tools/factory-metrics/experiments/test_checkpoint.py
```

The proofs reuse EB5/precheck fixtures unchanged, keep failing-first evidence,
and include hand-worked planning/interval examples and a large synthetic
positive control that meets the original precision limits. No live baseline,
paid eval, real assignment, candidate, replay dispatch or activation occurs.
