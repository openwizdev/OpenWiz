# WR8 proof plan

All inputs are synthetic assumptions, including API pages, identities, dates,
labels and price evidence. No live capability or observation is established.

- Current CI: complete stable run/job pages with exact requested pool labels
  produce literal running/queued counts through `suite.compose`. Existing
  completed-window tests cannot cover current jobs (their timestamps are null).
- Coverage: partial pages, duplicate run/job identities, changed attempts,
  unknown statuses and missing/conflicting pool labels must keep totals Unknown.
  A missing runner never establishes a queue or pool. Raw source facts, not
  precomputed counts, drive these cases.
- Throughput: existing factory PR/closing-link reads plus current ticket
  metadata produce hour/day directional counts. Multi-ticket PRs count once;
  conflicting/missing direction remains Unknown. Board polish precedence and
  all-base-branch factory scope are retained. Existing daily metrics lack this
  join and would miss PR-title classification or duplicate-direction bugs.
- Cost: reuse list-rate rounding/prices only for completed latest-attempt CI
  jobs created today. Keep its partial-day scope and price dates; no billing,
  all-in allocation or running/rerun cost is invented.
- Compatibility: existing CI collector/cost/factory/journey proofs stay green;
  additive helpers do not change their queries, files or historical results.

Owning boundary: `test_activity.py`, injected reads and fake gh -> activity
provider -> `suite.compose` / `validate`. Red output is committed before code.

## Review R1, first correction attempt

Observable contract: selecting a subset of exact supported pools filters the
emitted metrics while complete recognized source classifications remain intact.
The stock source gives ubuntu-24.04 running/queued = 1/1, or ubuntu-slim = 0/1.
Missing, unsupported or conflicting labels on another active job still make
selected totals Unknown. Existing all-pool cases cannot expose the selection
bug because none of their recognized source pools is omitted.

Owning proof: `test_selected_pools_preserve_recognized_source_coverage`, raw
fake-gh pages through suite composition/validation. R2 remains #2384 and is
outside this correction. Original red evidence is retained unchanged.
