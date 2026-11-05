# WR2 proof plan

All inputs, dates, hashes, paths, links and identifiers in these proofs are
synthetic assumptions. No fixture establishes a live source, private access,
scheduled operation or an executed EB6/EB7/EB8/EB9 experiment.

| Claim | Observable proof | Plausible defect existing WR1 tests miss |
| --- | --- | --- |
| WR1/WR3/WR8 | `test_finite_invocation` reads selected existing artifacts, saves one complete suite and renders six ordered groups | A page uses values that were never saved; WR1 only composes records |
| WR2 | `test_ticks_restart_and_partial_source` and `test_immutable_atomic_history` | A duplicate tick overwrites history, an older tick regresses latest, or a partial read refreshes old evidence |
| WR4 | `test_generic_page_and_missing_slots` | Missing categories disappear or become zero; WR1 checks records but does not render them |
| WR5/WR6 | `test_privacy_and_escaping` and native adapter readback | Source payload or active HTML/links enter saved output; WR1 requires consumers to sanitize/escape |
| WR1/WR3 | Render `synthetic.html` in Chromium and retain `synthetic.png` | HTML structure passes but the actual page is unreadable |

History's public read seam for WR7 #2351 is `history.read_all(root)` returning
validated, chronologically sorted complete suite records. Missing boundaries
stay absent; callers can count gaps without fabricated samples.

The original checkpoint and red logs are historical and retained unchanged.
Ops disposition 6781074763 authorizes source-linked partial/null board/decision
points. `red-point-projection.log` precedes those adapters; the board's existing
synthetic graph contains six approved tickets (the initial draft's four-ticket
expectation was corrected to match that fixture). The point tests also prove
that private request wording, request keys, board titles and target identifiers
do not enter the saved record or HTML. No source value is replaced by zero.
