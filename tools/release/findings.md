# Past export findings and their checks

Sources are the export evidence branches. They summarize the original review;
the original reviewer messages were not found. No live content is used by these
fixtures. All plants are synthetic. D1–D4 are recorded draft corrections, and
identity is a recorded maintainer decision; they are included along with the
numbered review findings so none of those slips is lost.

| Finding | Primary record | Check and planted fixture |
| --- | --- | --- |
| 0.0.1 R1: service claims with unpublished evidence | `origin/export/openwiz-0.0.1-evidence:private/evidence/openwiz-0.0.1/export/README.md`, Round 2, finding 1 | The recorded-style live claim, without added unpublished wording, fails `0.0.1-R1` when public live evidence is absent; a separate fixture with public live evidence proves the unpublished-wording guard |
| 0.0.1 R2: unreleased instead of the date placeholder | Same, finding 2 | Missing/repeated exact version heading or date placeholder fails `0.0.1-R2` |
| 0.0.1 R3: extra ls -l read supplies provider and purpose too | Same, finding 3; round-1 README at `82dab95` | The recorded misleading sentence fails `0.0.1-R3` |
| 0.0.1 D1: ls lists every thread | Same branch, `claim-check.md`, Round 3, row 1 | Recorded unqualified wording fails `0.0.1-D1` |
| 0.0.1 D2: --json on every command | Same, row 4 | Recorded wording fails `0.0.1-D2` |
| 0.0.1 D3: reads never wake or mark read | Same, row 5 | Recorded unqualified wording fails `0.0.1-D3`; reviewed uncertainty wording passes. A hash-bound `historical` exception may approve an exact wording match, without bypassing claim evidence |
| 0.0.1 D4: compatibility with any future room-cli | Same, row 6 | Recorded compatibility wording fails `0.0.1-D4` |
| No-reply author and committer | Same branch, README, Round 2, identity decision | A personal-style email fails the plan; both commit identities are set explicitly |
| 0.0.3 R1: sends inherit the reads' tested version | `origin/export/openwiz-0.0.3-evidence:private/evidence/openwiz-0.0.3/export/README.md`, Round 2; #200 | Require and execute the public `a_send_at_the_reads_tested_version_is_not_live_tested_for_sending` proof; missing, failed or zero-test result fails `0.0.3-R1-fresh` |
| 0.0.3 R1 continued: replay/lookup inherit old records' tested label | Same, Round 3; #294 | Require and execute `a_record_that_says_tested_never_replays_or_looks_up_as_tested`; missing, failed or zero-test result fails `0.0.3-R1-replay` |
| 0.0.3 R2: ordinary terminal send shows effects before dispatch | Same, Round 2, R2; `1e4b061` fixes CHANGELOG.md and docs/decisions.md | The recorded CHANGELOG sentence and both decisions.md phrases fail `0.0.3-R2`; the fixed page-scoped wording passes |
| 0.0.3 R3: environment scrub lacks public proof | Same, Round 2, R3; `tests/messaging/environment.rs` at export `68fd4dd` | Both named read/send context proofs are required and each must run exactly once. A missing public test, either failure, or a zero-test result fails `0.0.3-R3` |
| 0.0.3 R4: saved draft shows a false changed mark | Same, Round 2, R4; #162, #199 | Require and run `w8-no-false-changed.test.mjs`, exactly four passing browser tests; missing/failed/zero tests fail `0.0.3-R4` |
| 0.0.3 R5: trailing space in help | Same, Round 2, R5; `01b60d2` | Run the built binary's help and refuse trailing whitespace (`0.0.3-R5`) |
| 0.0.3 R6: evidence says 35 pending placeholders, tree has 36 | Same, Round 3, R6 | Plant 36 with declared 35: `0.0.3-R6`; declared 36 passes and the report independently prints 36, with publication disabled |

The wording checks recognize the recorded slips, not arbitrary paraphrases.
The complete hash-bound claim ledger and independent semantic export review
remain required. Functional checks use public tests rather than grepping
implementation details. Their named contracts are intentionally strict: a
renamed test must be reviewed and updated here before it can pass.

## 0.0.5 combined export review

Primary review: ClosedWiz #276 comment 6654038593, export ff5f9510.
`review_rules.py` runs from normal `release check` historical-wording validation
before build or publication. `test_export_review.py` uses synthetic
files under `tests/fixtures/release/export-review/` and the historical checker;
the original checker accepted the three M1/M2/L4 specimens (recorded red run).

| Finding | Check / synthetic specimen |
| --- | --- |
| M1 publish-state text that will become false | `0.0.5-M1`: staged/approval-pending wording in the four public release docs; `m1/README.md` |
| M2 unresolvable private commit hashes | `0.0.5-M2`: README/testing hash tokens must resolve to the public base's history; `m2/README.md` |
| L1 invented head-specific command result | `0.0.5-L1`: exact misleading result-record wording; `l1/README.md` |
| L2 historical setup links point at the rewritten guide | `0.0.5-L2`: a setup promise must not target the current rewritten access page; `l2/README.md` |
| L3 stale tool/browser rows | `0.0.5-L3`: recorded obsolete v127-only / no-Safari wording; `l3/README.md` |
| L4 scrub placeholders and private/excluded pointers | `0.0.5-L4`: code-comment placeholders and the recorded dangling references; `l4/README.md` plus four synthetic pointer cases |

These recognize the recorded failures, not arbitrary unsupported prose.
M3 (quick Mac check) and L5 (deletion of old public reports) remain maintainer
decisions. Automated wording checks do not replace independent review or those decisions.

## 0.0.5 comment re-review

Primary re-review: ClosedWiz #276 comment 6654663452, export 029f795a.
L4-r extends the L4 guard by class, rather than by a list of exact sentences:

| Class | Generic check / planted fixture |
| --- | --- |
| Review history | Correction/review rounds and contextual finding/reviewer identifiers in comments; `comment-history/README.md` |
| Private/evidence pointers | Evidence notes/reports/README references, private/internal paths and ticket-specific procedures in comments, including adjacent comment lines; `comment-evidence/README.md` |
| Scrub punctuation | Space before comma/period/colon/semicolon and orphan punctuation in comments; `comment-punctuation/README.md` |
| Glued extension | A prose connector/name word joined directly to a code/media extension; real file names and explicit code spans are retained; `comment-extension/README.md` |
| Malformed prose parenthesis | Parenthesis followed immediately by separator punctuation in Markdown; `prose-punctuation/README.md` |

The comment scanner excludes strings/raw strings, template payloads and shell
heredocs, checks inline and block comments, and leaves legitimate private state
directory descriptions and proof ids alone. Variant plants exercise unseen
round labels, finding ids, pointer wording, punctuation and extensions; positive
controls preserve runtime literals and actual file names. All fixtures are
synthetic. These checks supplement the exact-head semantic review.
