# O10 proof plan

Starting commit: `b1f8894c`.

- P3 / acceptance 1: run O3's canonical privacy checker against a staging copy of all owned skills at the starting commit (red), then the edited copy (green). Initially unavailable; completed below after O3's verified merge and the ops source/procedure ruling. This is a scoped tree proof, not a whole-public-tree or history proof.
- P4 / acceptance 2: public tracker instruction contracts in `skills/triage/test/test_public_records.py`, red before wording changes, then green. They guard copied standalone approval templates, decision routing and wayfind claim/release commands. Independent full-diff review covers prose that tests cannot prove and privacy of auxiliary files.
- Acceptance 3: run affected static skill checks and affected script tests. Full workspace and browser suites run only in CI under the standing credits rule.

The plausible regressions are a copied quote-bearing approval, a builder answer or batch decision publishing exact words, and a thread-bearing wayfind claim/release. Existing installation/static checks do not guard these public instruction forms. Tests check the instructions agents copy; they do not execute a live tracker flow or replace the privacy checker.

Read-ahead: O22 (#1409) needs every eligible skill to pass the privacy check; CF4-E2 (#1362) needs this public-safe text baseline without behavior cuts; O16 (#1284) needs these edits in its staged rehearsal. No executable interface is added for later tickets.

Policy blobs read: AGENTS.md `2b9ae846b0dd4fcb93625ae1566b448f8de0e28a`; fleet.md `99aaafc6905d691c80ad413370bb4cb1f3a8f3bd`; helpers.md `9a8628b0deabf3ed320b856af2f0117723fab15b`. O2's verified merge is PR #1414, merge commit `213fbf0199d2f32f7230d0c6381ffd0f44680640`.

Initial gaps: the canonical checker and the spec's named grill were absent at the starting commit. Ops resolved their source/procedure questions in [the ruling](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6705157823). The approved decision sources are the recorded spec confirmation, current revision-2 approval and merged O2 contract. The absent grill was not recreated or read. No publication or live action is authorized or performed.

## Completed scoped evidence

- Tracker templates and wayfind: 3 instruction-contract tests pass. The red commit is `5a346bcd`; the contract-first header follow-up red is `7e2d3fb1`. Both red logs are beside this plan.
- Image provenance: all 7 UI-guidance checks pass; the two private-link cases failed before replacement (`93ec0fd0`). Pinned research/profile revisions and primary-source citations remain, with private-comment pointers replacing private-file URLs. This is written-provenance evidence, not the canonical privacy scan.
- Triage collector: the existing 21 fake-GitHub cases pass, including the expanded shapes table. It now recognizes an approval-first header/pointer followed by the AI marker, while pasted records, absent/file pointers and unrelated markers still appear as work. The selected triage test command also runs the 3 instruction-contract cases. The failing-first collector log is committed at `7e2d3fb1`.
- `cargo test --locked -p openwiz-tests --test checks skills`: 46 passed, no failures. This covers static installation, notices, links and pinned instruction contracts. No Rust source or crate changed, so no crate-specific clippy run applies.
- `cargo fmt --check`: pass.
- Diagnose's human-assisted-loop tests: 5 passed. Where-are-we collector tests: 9 passed. Hill-climb isolation instruction tests: 5 passed; council instruction tests: 6 passed. No browser or full-workspace suite ran locally.
- Only historical checkout-path prefixes were normalized in older ask-wiz/research logs; commands, results and failure reasons remain unchanged.

## Canonical scoped privacy proof

Checker implementation and private literals are both pinned to
`51e9b6b7791dcf9b077fd7163d1b4ad30990d23e`, verified merged by PR #1846
(merge `2c1c77c0baa790aba308f385b06094128a47075f`). The checker package and
required private list were extracted outside this branch. No checker code,
private list, raw snapshot or private history was imported into the diff.

Two separate stages preserve repository-relative paths, original bytes and
symlinks for **all** O10-owned public files, including unchanged auxiliaries:
the 16 owned path entries in #1278. The saved start at
`b1f8894c7ce485852c6562c195a7cb61d0a391c5` contains 61 such files; the initial
result at `3d8aa95ec368c629495a0f166d0fa0b2b12cca36` contains 67. These paths
are public classes under O1; private evidence, dependencies, Git metadata and
the external checker are excluded. Later evidence-only commits are rescanned
on their complete resulting scope; the exact final pin/count is recorded on the
pull request. No historical starting-file bytes were edited for the red run.

For each stage, separately, using the same external pin and list, this
command was run (a record, not a command to run):

```text
python3 -I <external-checker>/tools/privacy-check/check.py \
  --tree <absolute-scoped-stage> --literals <private-list> --require-literals
```

- **Red first:** saved-start stage exits 1, with T2 findings in the two live
  skills, build-ticket and huntr, and T3 findings in the two live skills.
  `privacy-red.txt` preserves the complete safe checker output (six findings).
- **Green:** resulting scoped stage exits 0, with no refusal.
  `privacy-green.txt` preserves the complete output.
- Both runs report `literals: used`. Exit/input failures are not counted as red;
  every invocation's status and full output were checked separately. The
  verified checker prints locations/rules without echoing the private literals.

This proves T1–T3/F1–F2 only on this owned staged scope. It does not prove public
ancestry, commit-range privacy, tracker execution, text inside binary images,
the full future public tree, live behavior or publication.

## Helpers

- Scout/spec tracer, full owned-skill slice at `b1f8894c7ce485852c6562c195a7cb61d0a391c5`: 23 items reread; used 23, ignored 0, wrong 0. Confirmed public-template, private-provenance and storage risks, plus consumer/test seams. Archived. No-push check: `clean #1278: nothing changed but the writes you named (branches 0, comments 2)`. Snapshot and compared window are retained in private durable state; no raw JSON, helper id or local path is published.

- Independent privacy/full-diff auditor at `7f8b75e65652c16ac37324ba90e5bf3398431b43` against the starting commit: read all 37 changed files; no confirmed findings, 0 finding candidates used/ignored/wrong. Independently extracted and verified the pinned checker package and private list, reconstructed the complete 61/69-file stages with original bytes and symlink/executable modes, and reproduced the red/green outputs exactly. Both runs used the required literals; no READ/input failures. Archived. Result remains BLOCKED on the O5 integration wait and exact-head CI, with no full-tree/history/live claim.

### Original-window guard and attributed coordination allowance

The immediate post-helper check captured its completed window and originally
exited 1, retained with both durable compared states and
[the stop record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6705231242):

```text
hit #1278: comment 6705190069 on #1278 is new
```

[Ops ruling 6705656980](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6705656980)
verified the other builder's own POST and returned URL. It authorizes only that
one attributed #1843 coordination write; it is **not this builder's authorship**.
The saved original comparison was replayed, without recapturing GitHub state:

```sh
sh <build-ticket>/scripts/check-helpers.sh check <original-snapshot> \
  --ended <original-completed-window> --own-comment 6705190069
```

Replay exit 0, **clean after the one attributed coordination allowance**:

```text
clean #1278: nothing changed but the writes you named (branches 1, comments 9, pull request #1850)
```

No other hit was allowed. The original exit-1 evidence and both states remain
private and durable; snapshot/window contents, local paths and helper ids are
not published. The attribution question is resolved; no helper misconduct is
claimed.

## Pinned O5 consumer evidence

The coordinated record is [6705269535](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6705269535):
O5 `c19dcb8d6df1bc1d69dc1dd238311a8a20b20894` (tested implementation
`3a087242946aaa2d4b6e8e9156cc879771d65503`, final pin adds only audit evidence)
against O10 `7f8b75e65652c16ac37324ba90e5bf3398431b43`.
The builder independently reran that exact pair in a temporary detached O5
worktree, then removed it; no O5 source entered this branch:

```sh
python3 skills/launch-fleet/scripts/fixtures/test-o10-triage.py \
  --o10-revision 7f8b75e65652c16ac37324ba90e5bf3398431b43
```

Exit 0: both existing fleet batch cases passed (empty frontier without
individual approvals; exactly the approved subset admitted), O10's existing
shape table passed, and all eight actual-rendered-record cases passed: valid,
pasted, absent/malformed/file/leading-zero pointer, absent marker and unrelated
later marker. Header, immediate pointer, blank line and marker layout remain
required. Full safe output is in `o5-consumer.txt`. This is exact fixture
integration evidence, not a verified O5 merge, blanket O10 acceptance, CI,
publication or live proof. At that pin the integration wait was retained; its
later verified-merge release is recorded below.

## Remaining gates

The #1273 integration wait is released after verified merge PR #1848, main
commit `68de0c2903d492332ab69dfbf3eaa11eea3f1ef3`, final O5 head
`8e10f2256851aaa1fad5c6c11c8034a468163d83`. Earlier coordinated pins/evidence
remain above. All local preparation gates and the final required self-review
pass. Exact-head CI and external review remain pending; publication/cut-over
gates stay closed. No full-tree privacy, full-suite, history, live or activation
pass is claimed. The resolved source/procedure and attribution questions need
no needs-info label.

This is an Infra skill/privacy preparation change, so no product changelog sentence is needed. The pull request uses the no-changelog exemption when opened.

- Required full-diff auditor, Standards/Spec/full-sweep at `39f973ebe1d0bd9f2ba3a5450ecc02cf2e34f59a` against `b1f8894c7ce485852c6562c195a7cb61d0a391c5`: read all 35 changed files; no confirmed findings, used 0 finding candidates, ignored 0, wrong 0. Result BLOCKED on the already recorded canonical checker, missing grill source, O5 consumer coordination and exact-head CI gaps. Tests were not independently rerun by this read-only helper. Archived. No-push check: `clean #1278: nothing changed but the writes you named (branches 0, comments 4)`. Both ends are saved in private durable state.


## Verified O5 merge and main reconciliation

PR #1848 was read back as merged at
`68de0c2903d492332ab69dfbf3eaa11eea3f1ef3`, reachable from current main.
The merged consumer seam was rerun against O10 merge head
`11f4c1c7e26090965d8bccd72fa8ce9132acfb7f`: both batch cases, the existing
shape table and all eight rendered-record cases passed. Earlier coordinated
O5/O10 pins and their red/green evidence remain preserved above.

Main conflicted in export-review and live-quick-check. The merge preserves its
ADR 0019 combined-release policy: CI plus agent live smoke, pre-publish checks
for risky writes, hands-on feedback after publishing, automatic plan preparation
and one final approval of the exact export. O10 reapplies only public-safe
wording, private evidence storage and reusable review instructions; it grants
no live or publishing authority. Private grill file links and the concrete host
name are removed. Other main changes are inherited unchanged.

Affected post-merge checks: 50 Rust skill checks pass; the merged consumer seam
passes; cargo fmt --check passes. No Rust crate differs from merged main for this
ticket, so no crate-specific clippy applies. No workspace or browser suite ran.
The historical unittest red log had only trailing whitespace normalized; its
original red commit and failure evidence remain intact.


## Final required self-review

Codex Sol 6.1 High fast, shared read-only diff/privacy auditor at
`456d141627ca0b5662510f5d5f8ef4660f4371b9` against merged main
`9a7bef82dba122079349605e29bbbe4990ce0f2a`: **PASS**. Read all 38 changed
files, including both merge resolutions, with Standards/Spec/full sweep and
the builder checklist. No confirmed findings. Three evidence items checked and
used, none ignored or wrong; no finding candidates. Independently verified the
checker/private-list pin and staged bytes/relative paths/symlink/executable
modes, then reproduced the original 61-file red (four T2/two T3) and final
70-file green exactly, both with required literals. Verified the O5 merge and
consumer evidence, and preserved ADR 0019 gates. It did not rerun the builder's
Rust/consumer tests or prove CI, live behavior or publication.

Archived before the immediate no-push check; no manual allowance in this window:

```text
clean #1278: nothing changed but the writes you named (branches 1, comments 15, pull request #1850)
```

Four helpers total are archived. Earlier guard evidence and its explicitly
attributed one-comment allowance remain intact. This final commit adds only
evidence to the reviewed source. Its full owned scope is rescanned with the
same pinned checker and required private list before push; the PR records the
exact resulting head and tree. Newer main was fetched and is conflict-free, so
no further merge is needed. Ready status starts CI; passing exact-head CI and
external review still gate the merge.

## Review correction R1: preserve wayfind claim identity

Review at `b8385326114d772b6942646e99aadad44e99790c` found that the documented
reader discarded claim identities while release matching needed numeric comment
ids. Main was merged first, as requested. The regression was committed red at
`07d6b5bb` before the fix; `r1-red.txt` shows both reviewer histories failing
because the reader returned bodies without identities.

The existing instruction proof now executes the **exact jq expression from the
skill** on synthetic GitHub-shaped comments, with opaque node ids and URLs
containing numeric comment ids. Histories with claims 100/101/103 and 101/103/104
followed by release 101 must leave earliest holders 100 and 103 respectively.
This is the public claim/release contract; the earlier wording-only proof never
ran the projection and missed the lost identity.

The reader now retains each comment's URL alongside its body. Instructions say
to capture the posted claim URL, copy its positive decimal issuecomment suffix
as the claim id, retain it privately and use that same value in releases, never
the opaque GraphQL node id. Four public-instruction tests pass; the selected
triage command also passes with this regression included. Full green output is
in `r1-green.txt`. No tracker write or live execution is used by these proofs.

Only wayfind instructions, the existing public-instruction proof and owned
evidence changed for R1. The original scoped privacy pin, private literals,
red evidence, O5 consumer proof and release/live/publication gates remain.

R1 final scoped checks at `86a3e1e010176ab3671b48c9764230401fd71812`:
all 50 Rust skill checks pass, all four public-instruction tests and selected
triage collector cases pass, cargo fmt --check passes. The complete 72-file
owned scope passes the original O3 checker/private-list pin with required
literals and exact committed green output. No Rust crate differs from main;
clippy remains inapplicable. No workspace or browser suite ran locally.

Required Codex Sol High fast shared read-only R1/full-diff auditor at that pin:
**PASS**, all 40 changed files read, no confirmed findings. Independently ran the
pinned Python/jq regression (four tests pass; earliest holders 100/103) and
reproduced both failures with the prior reader. Independently verified the pinned
checker/private list and replayed the complete 72-file scoped privacy scan,
exit 0 with literals used and matching committed output. Three evidence items
checked/used, none ignored or wrong; no finding candidates. It did not run
Cargo, npm, browser, live or O5 consumer checks.

Archived before the immediate no-push check, clean without allowances:

```text
clean #1278: nothing changed but the writes you named (branches 1, comments 18, pull request #1850)
```

Five helpers total are archived. This green correction commit adds only the
check/audit evidence to the reviewed R1 source; its complete owned scope is
rescanned before push. New exact-head CI and external R1 re-check remain merge
gates. No whole-tree/history/binary-image privacy, live or publication pass is
claimed. Earlier manual-allowance evidence remains preserved in its original
window and grants no exemption here.
