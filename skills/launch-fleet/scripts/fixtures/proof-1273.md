# #1273 / P4 fixture evidence

Baseline: `b1f8894c7ce485852c6562c195a7cb61d0a391c5`. Authority: #1257 revision 2 and `contracts/open-development.v1.md`. This proves fixture behavior only; no live fleet, publication or cut-over was run.

| Claim | Proof |
| --- | --- |
| Public writers carry no thread id | The skill's complete record table, huntr's captured approval bodies, and the load driver's scan on every new or edited fixture comment |
| Public starts, claims, checks, resumes and reviews remain routable | `test-records.py` through fake gh and CloudRoom; helper-check process tests; review-relay process tests |
| Re-checks preserve their original reviewer; give-up closes the span across commits | Public fixture tests with and without the private map; legacy quiet-review and re-check cases |
| Ambiguous, missing and conflicting identities never receive a message | Public title/branch, helper exclusion and private-map disagreement fixtures; relay ambiguity cases |
| The nine replacement forms match the contract exactly | `PublicRecords.test_record_table_uses_the_contract_public_forms_word_for_word` |
| Approvals point to a real private comment without copying its words | huntr gate captures the two-line public body and refuses missing, malformed or unreadable pointers |

Red was committed before implementation. `red-1273.txt` records the old table, missing relay target and missing approval pointer. Its first routing attempts used an incorrectly executable fake gh transport and are **not valid routing evidence**. `red-1273-routing.txt`, committed separately before implementation, corrects that transport and runs the original fleet script: seven intended routing failures across six cases. Subsequent public fixture checks pass.

Two read-only shared scouts examined the baseline. Fleet scout: 15 pointers used, none ignored or wrong. Other-writers scout: 8 used, 2 outside this ticket's implementation left unchanged (approval validation owned by O6; fleet-settings wording owned by O7), none wrong. Both reports were checked against source; both helpers were archived before the no-push check. Snapshot and completed window retained in private helper-check state. Result: `clean #1273: nothing changed but the writes you named (branches 0, comments 2)`.

Policy blobs read: AGENTS `2b9ae846b0dd4fcb93625ae1566b448f8de0e28a`; fleet `99aaafc6905d691c80ad413370bb4cb1f3a8f3bd`; helpers `9a8628b0deabf3ed320b856af2f0117723fab15b`.

Local checks are scoped to changed behavior, with formatting. No Rust crate source changed, so no crate needs clippy. The full workspace, browser suites, full 100-ticket load and complete fleet matrix are left to CI. A superseded full fleet attempt was stopped after a harness-placement correction; selected public and legacy record cases are the local hand-back evidence.

The named `docs/grills/2026-11-05-ci-100x.md` is absent from the baseline. The complete spec, approval and comments and the merged contract supply the implemented decisions. Actual CloudRoom discovery shapes and live behavior remain unverified.

The legacy re-check fixture now puts its initial review start at 10:30, before its 11:00 re-check. Its earlier shape reversed those creation timestamps; review spans intentionally follow creation time, not edit time or arbitrary input order.

## CI correction: run 42358500132

The Rust job at `7c755a117055ad26cacc6aeba2a57f0bc24fb35e` failed in 15 fleet fixture cases. The scoped runner `python3 skills/launch-fleet/scripts/fixtures/reproduce-1273-ci.py` selects their original assertions and required setup cases directly from `test.sh`: 20 cases total. Before the fix it reproduced exactly 15 failures; that run and the selector were committed before the corrections in `red-1273-ci.txt`.

The fixes are fixture-only: carry the existing `records.py` beside all four executable copies of `fleet.sh`; count the added repository-privacy question in six literal totals; correct three sorted archive expectations after the synthetic-id rename; and put the original review start before its told-again notification. The reviewer-span guard, archive membership, cache assertions, budget limits, case count and production scripts are unchanged.

One additional shared read-only CI scout examined the failed head: 20 supported items, 18 used and 2 intentionally unchanged copy sites checked, none wrong. The builder verified the cited source and log blocks. The helper was archived before a clean no-push check: `clean #1273: nothing changed but the writes you named (branches 1, comments 5, pull request #1848)`. Snapshot and completed window retained in private helper-check state. It used Codex Sol 6.1 High under the current helper instruction.

After the correction: **20 cases, 0 failed**, saved in `green-1273-ci.txt`. `cargo fmt --check`, shell syntax, and the selector's Python syntax pass. No Rust crate is changed by this correction, so no crate-specific clippy command applies. No full workspace or browser suite was run locally; CI remains the merge gate.

## O10 template consumer integration

Ops request 6705158258 and O10 comments 6704788396 / 6704845994 identify the producer/consumer seam. O10 source pin: `7f8b75e65652c16ac37324ba90e5bf3398431b43`, tree `43d2ae52fc7cc94dbbe0f8b6235568d927313dcc`. No O10-owned file is changed by O5.

`python3 skills/launch-fleet/scripts/fixtures/test-o10-triage.py --o10-revision 7f8b75e65652c16ac37324ba90e5bf3398431b43` extracts that producer/collector into an isolated temporary tree beside O5's actual fixture code. It selects the two existing batch cases without copying their assertions. The record captured from the successful approved-subset case becomes the positive input of O10's existing F1 shape table and eight focused collector inputs. The entire chain uses fake gh and synthetic records.

The defect was an under-checked fixture: the fleet's prefix recognition could admit records with unfilled public-template placeholders. A new fixture guard first failed on the producer's `<decision>` / `<pointer>` fields; red output is in `red-1273-o10.txt` and was committed before fixing the substitutions. The fixture now fills a paraphrased synthetic decision and a contract-valid synthetic private-comment pointer. The legacy substitution remains for today's private template.

Green output in `green-1273-o10.txt` proves the empty frontier without per-issue approval, exactly the approved #16/#17 subset, the first-line public header, immediately following private pointer, blank line and AI marker. O10's existing F1 cases and eight actual-record cases keep pasted approvals, absent/malformed/file/leading-zero pointers, missing markers and unrelated later markers as triage work. This proves recognition of its own response; it grants no approval, live authority or activation. Full CI still gates the merge.

The legacy batch subset case also passes through `TEST_ONLY`, and `cargo fmt --check`, shell syntax and the integration runner's Python syntax pass. No Rust crate changed, so no crate-specific clippy command applies. No workspace/browser suite was run.

A shared read-only Codex Sol 6.1 High diff auditor inspected the seam at `3a087242946aaa2d4b6e8e9156cc879771d65503` against `298e99c59f06682b4335667317d7c58ad46b854c`, including the pinned O10 sources: PASS, 12 pointers verified and used, none ignored or wrong; no independent execution or live claim. The helper was archived before the no-push check. Result: `clean #1273: nothing changed but the writes you named (branches 1, comments 7, pull request #1848)`. Snapshot and completed window retained in private helper-check state.

## Review R1 / R2, after merging main

R1's red evidence is the reviewed fallback paragraph: it prescribes `builder fallback due, thread <id>, branch <branch>`, updating the public checked-start with the replacement identity, and appending `Replacement: <id>`. Manual review against the public-form contract demonstrates the contradiction. The fix must use branch-only public records and keep identities/handover lineage private; this prose change needs a direct read of the operative paragraph, not an implementation-mirroring source assertion.

R2 claim: an archive failure followed by editing a start claim to given-up must still list that retired reviewer for ticket-closure archival, while re-checks reach only its replacement. Existing span tests assert non-contact but never ticket closure after editing away the original start. New process-boundary cases in `test-records.py` use synthetic gh/CloudRoom, immutable claim mappings with overwritten commit aliases, same-head and later-head replacements, discovery present/absent, and compatibility with an older commit-only map. The pre-fix output is saved in `red-1273-review.txt`.

Review-fix helper: one shared read-only Codex Sol 6.1 High diff auditor at `d2169db2638979d3f614a6ddd26eed7d35a0732c`; two verified pointers used, none ignored/wrong. Confirmed R1's paragraph and found that an edited replacement start could inherit an earlier retired span's identity. The lead reproduced that gap through `Fleet.test_replacement_edited_to_given_up_keeps_its_own_archive_identity`; `red-1273-review-replacement.txt` precedes the correction. All three same-head reviewers must remain separately archivable; only the latest may receive a re-check.

Helper archived; no-push check: `clean #1273: nothing changed but the writes you named (branches 1, comments 10, pull request #1848)`. Snapshot and completed window retained in private helper-check state. Helper used pinned source reads only; no independent runtime or live claim.

Review green: `PYTHONDONTWRITEBYTECODE=1 python3 skills/launch-fleet/scripts/test-records.py` passed all 14 tests after the edited-replacement boundary correction. The saved final output is `green-1273-review.txt`. Same-head/later-head replacements, edited start at a later commit, legacy commit-only maps, absent discovery, two retired reviewers and stale told-again records are covered through synthetic process boundaries. Immutable start-claim keys recover edited span boundaries; archive metadata is consumed only by closed-ticket cleanup.

Seven existing exact-name legacy cases passed: quiet reviewer -> fresh; quiet re-check -> fresh; fresh reviewer re-checks next head; failed reviewer's told-again excluded; closed ticket archives builder/reviewer; failed reviewer still archived at closure; takeover after give-up. The first five were observed in the original scoped command; the last two have saved output in the green log. One mistyped `TEST_ONLY` selector selected zero cases and correctly failed the harness; the corrected full case name passed. No production failure was hidden by that selection error. `cargo fmt --check`, shell/Python syntax and `git diff --check` passed. This round touched no Rust crate source, so no clippy run applies. No full workspace/browser suites, live fleet operation, publication or CI watcher ran.

R1 manual check: the operative fallback paragraph prescribes only `launch-fleet: builder fallback due, branch <branch>` and `launch-fleet: start checked, branch <branch>`; old/replacement identities and handover lineage remain exclusively private. The general routing instructions retain immutable start-claim mappings even after give-up. Main was merged first at `5ff0a10fb443008da593fc3ec3228b3347cb271c`; policy blob IDs remained unchanged. All new writes are within O5-owned paths; changes imported from main retain their owners' work. CI at this new head remains pending, with full checks delegated to the PC.
