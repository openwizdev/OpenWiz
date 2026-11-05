# R1-R4 correction proofs

Review: PR 1871, comment 6706092688, at ea86c60557918532adf9a441a73f40b3ee1fc97d.
All four findings accepted. origin/main was merged first at 750350e4315aadf5cfa30b3855dcf7be6d9fffe4. No rebase or force push.

- R1: `ReviewFixes.test_r1_complete_public_development_tree` keeps public status,
  app guidance, design docs, release evidence, the exact grills README and both
  harnesses' skill files/aliases. Private classes still fail. Hash/mode binding,
  complete-tree equality and exact safe alias targets remain. The stale public
  document refusals were removed from the old negative fixture.
- R2: `ReleaseCheck.test_git_attributes_cannot_change_reported_export_bytes`
  uses same-path tracked attributes, a raw CRLF indexed blob and a source-only
  info/attributes override. Its clean source reaches staging and fails the
  byte-binding guard. Removing only that guard fails this owning test, even
  though the later dirty-clone guard also refuses the changed bytes. Renamed
  sources retain a separate refusal proof.
- R3: both O3 calls receive the checked head as history input, without a caller
  supplied base that could skip new history. Fixed production root/anchor policy
  checks all newly reachable trees, messages and commit identities. Dedicated
  fixtures prove a deleted private ancestor, foreign root, invalid source author
  and invalid generated-entry author refuse. Removing history input fails the
  generated-entry identity proof.
- R4: only validated complete pointer/cross-link occurrences bypass URL/internal
  reference scanning. Numbers and matching labels are checked. Arbitrary or
  malformed private links, private file URLs, suffixes and a second occurrence
  of an otherwise valid URL still refuse, including with hash-bound reviews.

`review-red.log` was committed before the implementation. R2's restored proof
and the focused guard-deletion output are in `review-r2-mutant-red.log`; its
runner verifies that the owning tests fail for the intended reason. The
additional Claude alias refusal is in `review-r1-alias-red.log`. Log trailing
whitespace is normalized; no diagnostic content is removed.

Synthetic history testing uses disposable copies of the release/O3 commands.
Only the copies substitute synthetic Git root/anchor constants. Older tip-scan
fixtures anchor at their independently constructed parent; dedicated history
fixtures keep their original pristine anchor across the planted commits.
Production has no policy override or environment bypass. Cargo/npm/node/gh
remain recording fakes; these proofs run no product or browser suites.

Coordination: #1843 comment 6706580848 scopes these corrections to check.py,
scans.py, their tests and documentation. Its entry grouping/preparation work is
preserved. No new helper or reviewer was started; attribution clearance remains
as recorded by ops. No live, release, tag, publishing or release-* write.
