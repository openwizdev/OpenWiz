# Release check

`release check` stages and checks one release from its public repository’s own
clean `release-<version>` branch. The separate private-to-public export retires.
It never pushes, fetches, tags or creates a GitHub Release. Plans with an `entry` section read GitHub through `gh`;
plans without an entry do not call it. Python 3.11+ (the privacy command and
regression-successor manifest checks require it), git, Cargo with rustfmt and
clippy, and (for a web export) npm, Node and Chromium must already be installed.
No third-party Python packages are used.

```sh
python3 tools/release/release check 0.0.99 \
  --repo /path/to/accepted-release-checkout \
  --plan /path/to/approved-plan.json \
  --literals /path/to/private-named-terms.txt \
  --staging /path/to/new-staging-directory \
  --evidence /path/to/new-evidence-directory
```

The checkout must already contain the approved `main` commit named by
`public_base`, and that commit must be an ancestor of the release branch.
Both output directories must be new, disjoint, outside the input repository,
with existing parents and no symlink in their paths. The checker writes only
inside those outputs. It never updates or copies from another repository.

The repository name is read from the clone’s single `origin` URL (HTTPS or SSH
on github.com, without credentials). Generated release links, roadmap tag
reads and the separately gated publisher all use that name. The staged clone
retains that canonical destination. No repository address is built in, so a
fresh clone after a repository move needs no tool edit. A missing, ambiguous
or unsupported origin refuses.

Before staging, the checker runs `tools/privacy-check/check.py --repo <clone>
--git-tree <release-head> --head <release-head> --literals <operator-input>
--require-literals` on the **entire immutable tree**, including files
absent from the plan. The same command checks the staged tree after scans.
An unreadable tool/input, refusal or 60-second timeout stops the check. This
requires the explicitly supplied private named-terms file for both invocations;
a whole `private/` checkout is unnecessary, but public source alone is insufficient.
The log reports that named literals were used.
Both invocations also enforce O3’s fixed public root/anchor, newly reachable
commit trees (even files deleted later), commit messages and identities. PR text
remains checked by public CI/pre-push; release staging cannot delegate history
privacy to hooks that publication disables.

### Required private input

For ordinary and historical/backfill checks, `--literals PATH` must name the
approved complete O3 named-terms source identified in the
[open development contract](../../contracts/open-development.v1.md#the-privacy-check).
The operator supplies that private file with verified source/provenance evidence;
never guess a private sibling checkout or substitute an unverified/incomplete list.
A known unverified/incomplete source, or unavailable provenance, stops the run for
clarification. The RG input decision is recorded in the
[private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6766913072).

Missing, empty, unreadable or malformed input refuses before output directories
are created. The form is UTF-8, one nonblank term per line, without NUL bytes;
terms are literal text, not regex expressions. As in O3, whitespace inside a
nonblank line is retained. Syntax checks and synthetic fixtures cannot establish
completeness or detect omitted unknown names; no completeness mechanism is added.
The release scanner retains case-insensitive literal-substring refusals, while
both O3 checks retain their existing case-sensitive named-term rule and all
history/tree/identity checks. Exact scan exceptions do not exempt O3's rules.

Keep the input outside the public release tree. It is read privately, never
copied to staging, evidence or a public tree, and its values are not printed in
diagnostics. Input validation, source privacy refusal and the existing output
rules do not authorize a live check, release, publication or incomplete evidence.

## Candidate contract and successor policy

The future public-source release interface is
[`openwiz.release-candidate.v1`](../../contracts/release-candidate.v1.md), with its
[schema](../../contracts/release-candidate.v1.schema.json) and
[synthetic examples](../../tests/fixtures/release/candidate/README.md). RL2 consumes
actual decisions and gate receipts; RL3 produces bounded live receipts; RL4
verifies compiled products; RL5 supplies actual release/install/timing evidence.
The contract binds one checked public commit/build, ordered version sections,
exact notes/artifact bytes, original ship time and all evidence inputs. It does
not implement a new command or turn a legacy report/approval flag into authority.

[ADR 0020](../../docs/adr/0020-release-on-demand.md) supersedes the export-specific
parts of ADR 0019 for this path after verified O17 cut-over: Jake's ship instruction
and exact changelog approval are the only human release actions. CI, privacy/claims,
verified products, combined agent smoke and applicable send/new/App-permission/
spending live results remain required automatic gates. The combined smoke must
exercise every included version's promise end to end on the checked build; a
partial user flow cannot satisfy that promise. No export-plan/final-diff,
standalone Sol-export, mandatory hands-on/device or per-step publish approval.
Ordinary development review and merge rules remain. Existing semantic claim
checks, artifact privacy dispositions and honest tested/unproved wording remain;
they must not silently reintroduce a human export approval.

Preparation is allowed earlier, but these instructions neither perform nor
authorize O16/O17, clear holds, widen approved live kits/spending/App grants,
activate policy or publish. The private-copy path stays stopped except named O16
work. Source history, frozen historical documents, version order, immutable
releases and unsafe-retry refusals remain. Historical backfill is separately gated.
The older plan/report, export-review and approval references below describe
existing tool interfaces and historical checks; they do not add human release
steps to the successor policy. RL2 must consume the candidate contract before
that path is usable. Only a real final acceptance run can prove live gates or
ship-to-install timing.

## The checked public candidate command (#1843)

`release candidate` is that consumer. Each subcommand reads one private state
directory, does what the current evidence allows, records the outcome in its
`record.json` (an `openwiz.release-candidate.v1` record) and prints one JSON
object: exit 0 with `prepared`, `recorded`, `ready`, `published` or `complete`;
exit 1 with `blocked`, `incomplete`, `uncertain` or `refused` and every reason.
It never waits: the next event (an approval, a finished CI run or live smoke)
runs it again. Preparation may run before cut-over; the shipping path stays
gated on verified O17, and these fixtures are not that run.

```sh
release candidate notes 0.0.12 --repo CLONE --entry entry.json --out NOTES   # proposed notes, CHANGELOG.md, sources
release candidate prepare --state S --repo CLONE --body body.json --artifacts DIR --entry entry.json --classification risk.json
release candidate decide --state S --changelog <private comment pointer>     # may precede ship
release candidate decide --state S --ship <private comment pointer>
release candidate gate --state S --gate products --receipt r.json --inputs i.json --repo CLONE --artifacts DIR
release candidate live --state S --kit KIT --smoke-state RUN --record <private comment pointer>
release candidate evaluate --state S --repo CLONE --artifacts DIR --literals TERMS
release candidate publish --state S --repo CLONE --artifacts DIR --literals TERMS
release candidate install --state S --receipt install.json
release candidate status --state S
```

**Notes.** `entry.json` is `{"versions": <the entry form above>, "excluded":
[{"path", "sha256", "reason"}]}`. Sections come from `changes/` at the clone's
HEAD, newest first, every original entry verbatim, one per bullet, in numeric
ticket order. The cap is five lines per section, except J6's recorded counts
for the settled combined release (0.0.12 back to 0.0.6 together only): 0.0.6
up to 17, 0.0.8 up to 7, 0.0.9 up to 11, 0.0.11 up to 6 and 0.0.12 up to 6.
In that combined release every section's footer links to the one published
`v0.0.12` release (J14); every other release keeps its own tag. A version with
a confirmed headline and no entries renders its dated heading and headline
alone (HL1, generic). A source without a version milestone
refuses unless its exact path and bytes are listed as a recorded exclusion
that is still unversioned. The output is a proposal, not an approval.

**Moved numbers (RL6, #739).** [`moved.json`](moved.json) lists every
changelog line moved from ClosedWiz by its old ClosedWiz number, with its
moved bytes' SHA-256 and the OpenWiz ticket that carries it (the ticket whose
body says `was ClosedWiz #N`), or `null` when that ticket did not move.
`changes/closedwiz-<N>.md` (#735) is always old ClosedWiz N; a plain
`changes/<N>.md` is old ClosedWiz N while N is in the map and no prefixed
rename exists, and otherwise OpenWiz ticket N. A moved line takes its
milestone from its OpenWiz ticket, which must still say `was ClosedWiz #N`; it
never takes the milestone of the unrelated OpenWiz ticket N. A prefixed number
missing from the map refuses, and so does a moved line whose ticket did not
move, unless it is a recorded exclusion. A plain `changes/<N>.md` whose bytes
differ from the moved line's refuses: rename the moved line first, or record
its new bytes in the map. Files under `changes/notes/` are not changelog lines.

**History (RL6).** With no published tag yet, `CHANGELOG.md` builds on the
fixed public anchor's `CHANGELOG.md` (its preamble and the 0.0.0-0.0.5
entries), so nothing older is dropped; once a tag exists, it builds on that
tag's changelog, whose entries never change.

**Curated notes (RL6, J77, VS9).** In place of the generated sentences,
`entry.json` can be `{"curated": "changes/notes/<name>.md", "curated_sha256",
"notes_sha256", "included": [<released versions, newest first>]}`. The curated
file is the whole changelog: the commit's `CHANGELOG.md` must equal it byte for
byte, and with a published tag it must be that tag's changelog plus newer
sections only. The release notes are its leading `included` sections, cut
before the next version heading, trailing newlines stripped, then one LF.
`curated_sha256` must be the file's approved bytes and `notes_sha256` the cut
notes' approved bytes; any other byte refuses. The changelog decision binds
`notes_sha256` (the contract's `changelog.sha256`). The command checks
structure, never wording: `# Changelog` and at most one plain paragraph, then
sections newest first, each `## <version> · <date>`, a bold headline,
`**What's new for you**` with 2 to 4 lines (none carrying a fixture caveat), one
footer line with the honest caveat, `**Under the hood**` with 1 to 5 lines, and
optionally one closing link line. Links are inline only and go only to
`https://github.com/openwizdev/OpenWiz`, and a release link names only this
release's tag or a published one. Published sections are not re-checked. At
publication every section date of the notes must be the UTC publication day:
otherwise `publish` refuses `changelog_date` before each still-unattempted write
(the tag push, and release creation when resuming after it) and never edits
the approved dates. D4 (`claims`) then holds when the notes are exactly that
cut at the candidate commit.

**Prepare** seals the agent-assembled candidate body. It refuses a non-public
repository or origin, an anchor other than the fixed public anchor, a commit
that is not on the public remote's own `main` (`not_on_public_main`) or on its
protected `release-<version>` branch (#964), a tree mismatch, versions out
of order or not newer than every published `v*` tag, malformed or range
headings, changed section/notes bytes or placeholders, and a commit
`CHANGELOG.md` that is not exactly the newest published tag's changelog plus
these notes. It also refuses an incomplete or changed product/artifact
inventory, broken alias, checksum or `SHA256SUMS` links, a manifest failing
the install contract and a missing risk classification. A changed candidate
keeps the original ship time and decision records, drops every
candidate-bound receipt and refuses once a publication write has started.

A commit not on public `main` is accepted only at or below the head of the
public `release-<version>` branch named for exactly the candidate's version,
and only while D3's ruleset read (default-branch resolution, include and
exclude patterns) finds that branch covered by active rulesets that require
`ci` and `privacy`, have no bypass actors, and block force-pushes and deletion.
Prepare, evaluate and publish each refuse `release_branch_wrong_version` (the
commit is only on another version's branch), `not_on_release_branch` (the
branch exists but does not reach the commit), `release_branch_unprotected`,
`release_branch_unreadable` (the branch fetch failed) and
`release_ruleset_unreadable` (an unreadable or unevaluable ruleset).
Preparing the same candidate again (the same `candidate_sha256`) saves any
`entry.json` or `classification.json` that changed, after the same
validation, and reports `"unchanged": false`; an identical repeat reports
`"unchanged": true` and writes nothing. A changed entry drops only the
`claims` receipt; the decisions, original ship time and every other gate
stay. Once a publication write has started (`attempt.json` exists), a changed
input refuses `publication_started` and nothing is written.

**Decisions** are read from the private comment itself, never from a caller.
The comment is unedited, by the repository owner, starts
`Private record: Jake, YYYY-MM-DD` and holds one
`Release decision: ship <candidate_sha256>` or
`Release decision: changelog <notes sha256>` line. A later
`Release decision revoked: <comment id>` in the same issue revokes it.
`record_sha256` and `decided_at` come from the comment. Identical notes keep
their approval across a rebuild; a changed candidate needs a ship binding that
matches it.

**Gates.** The command establishes `cutover`, `ci`, `privacy` and `claims` from
its own reads at every gated effect; no caller receipt or comment counts for them
(`gate` refuses those four). Each rule below is one of the PR's named assumptions
(D1–D6), kept as one constant or function in `candidate.py`:

- **D1, `ci` and `privacy`:** GitHub Actions check runs at the exact public commit,
  belonging to the latest run of the trusted workflow file (`.github/workflows/ci.yml`,
  `.github/workflows/privacy.yml`) at that commit, all `success`. A run whose own
  check of that name was only skipped (a main push's `main-light` run) is not
  evidence and is ignored; with no other run, the gate is missing.
- **D2, artifact privacy:** every archive is staged through the installer's own checks,
  then the existing O3 checker scans the staged runtime and web files with the
  operator's private `--literals` file. Any finding refuses.
- **D3, `cutover`:** O17 (#1285) closed as completed, with no `held` label on it or on
  O16 (#1284). The public repository is public and not archived, with immutable
  releases on. Every active branch ruleset that applies to the repository's default
  branch (an `include` match and no `exclude` match; `*` stays within one segment) has
  no bypass actors, and together they require `ci` and `privacy`. Any other condition
  or pattern form refuses.
- **D4, `claims`:** the notes are byte-for-byte what `entry.json` generates from
  `changes/` at the candidate commit, or its approved curated file's cut (RL6).
- **D5, kit authority:** `kit.authority` is an unedited, unrevoked
  `Private record: Jake, YYYY-MM-DD` comment with one
  `Release kit authority: scope <scope_sha256>` line naming the kit's exact scope.
- **D6, risk classification:** `--classification` lists every path changed since the
  newest published tag (or the public anchor), each with yes/no for send, new,
  app_permissions and spending. A partial record refuses. A path matching a
  category's reviewed pattern can never be `no` for it. A category is `no` only if
  every row says `no`. Spending has no pattern yet.

`products` takes RL4's native-query and web-build receipts and the runtime
selection as inputs. The command then runs RL4's verifiers over each staged archive
and requires their rows to equal the candidate's. `live` runs RL3's
`tools/live-smoke/receipt.py` producer on the approved kit and run state, and
`evaluate` applies its `accept`. Fixture, dry-run, stale or uncertain results never
pass, and each risk classified `yes` needs its own live receipt, except that a recorded one-release waiver (APP-1 (a), Jake, 2026-11-15) may stand in for the `app_permissions` receipt of 0.0.12 only: `decide --waiver <pointer>` reads an unedited, unrevoked `Private record: Jake, YYYY-MM-DD` comment holding exactly one `Release waiver: app_permissions v0.0.12` line (`Release waiver revoked: <comment id>` revokes it), and the result and record show that gate as `waived`, never passed. Typical blocked
results:

```json
{"reasons": ["ship_missing", "ci_failed", "smoke_not_live", "spending_live_missing"], "status": "blocked"}
```

**Publish** re-evaluates every gate (and again immediately before the release write,
excluding only its own verified tag), checks that immutable releases are on,
that the tag is absent and that the artifacts are unchanged. It records each
intended write in `attempt.json` before making it. It makes the annotated tag
locally first and saves that tag object in `attempt.json` (`tag_object`), then
pushes only that tag (never `main`) and creates the pre-release with the exact
notes and every asset. Read-back covers the release identity, the notes (the
exact approved UTF-8 bytes, with no newline or whitespace normalization), the
pre-release and immutable flags, the asset list and the downloaded bytes, and
the tag: both its peeled commit and the intended annotated tag object saved in
`tag_object`. A mismatch records `incomplete` and is never retried. A read-back
that cannot be read records `incomplete` with `immutable` and `prerelease`
false (unverified, never true by absence). A resumed run whose write was
interrupted is `uncertain` unless a matching read-back settles it; it never
repeats the write. Only the tag object saved in `tag_object` settles an
interrupted tag push. A settled tag with an unattempted release continues
through those checks to one recorded release write.

**Install and timing.** `install` accepts a normal install/update receipt
matching a published target's manifest and archive, then records
`finished_at`. `status` reports `original_ship_at` (the ship decision's own
time, kept across resumes and rebuilds), preparation start, the phases
(changelog wait, checks, publish, install) and the elapsed time against the
30-minute target. These proofs use fixtures; only #285's live run measures it.

## Plan contract: openwiz.release-plan.v1

The plan is the explicit per-file allowlist, not a directory glob. A maintainer
reviews it and the public text before running the command. Unknown or duplicate
JSON keys, unsafe paths, symlinks, submodules and mismatched hashes fail.

```json
{
  "schema": "openwiz.release-plan.v1",
  "version": "0.0.99",
  "public_base": "<40 lowercase hexadecimal characters>",
  "identity": {
    "name": "Synthetic Maintainer",
    "email": "123+synthetic@users.noreply.github.com"
  },
  "files": [
    {
      "path": "README.md",
      "source": "README.md",
      "sha256": "<64 lowercase hexadecimal characters>"
    }
  ],
  "claim_reviews": [
    {
      "path": "README.md",
      "sha256": "<same file hash>",
      "claims": [
        {
          "text": "Fixture-tested: A synthetic command prints usage.",
          "status": "fixture-tested",
          "evidence": "docs/evidence/check.md#fixture"
        }
      ]
    }
  ],
  "live_pending": 0,
  "scan_exceptions": []
}
```

This is a shape example, not a runnable plan: every referenced file, including
Cargo.toml, Cargo.lock, CHANGELOG.md and the public evidence document, must have
its own allowlist row. Every tracked file must appear: the plan is a review
ledger for the complete release tree, not a selection to copy. `source` equals
`path`, except the two generated markers below. Renaming a source into a
public destination refuses. Bytes, executable modes and approved aliases stay
bound to their hashes. Attribute normalization that changes staged bytes refuses.

## Optional entry and public roadmap

An approved plan can add exactly this section (all values here are synthetic):

```json
"entry": {
  "spec": 4100,
  "date": "2026-01-02",
  "tested": "Fixture-tested: Synthetic export fixtures pass; live export remains unverified."
}
```

A combined release (several versions published at once) still gets one entry
per version. `entry` is then a list, newest first, starting at the checked
version, each item `{"version", "spec", "date", "tested"}`. Each version's
entry comes from its own spec and its own milestone's `changes/` lines. The
entries are inserted together, and every one must be newer than every
published entry. Each version's dated heading must occur exactly once. A
combined range heading (`## A–B`) is refused everywhere.

The spec number identifies the agreed `## Changelog headline` section on GitHub.
It must be a parent issue in the requested version's milestone, with one public
headline sentence. The date is an explicit, valid ISO date, approved with the
plan; neither the checker nor the publisher chooses or rewrites it. `tested`
is the approved single public sentence saying what was tested and what remains
unproven. These inputs are reviewed text, not evidence of live behaviour.

Two allowlist rows become generated files. Keep their exact expected SHA-256s
and hash-bound `claim_reviews` in the plan as for every other public file:

```json
{"path": "CHANGELOG.md", "source": "generated/CHANGELOG.md", "sha256": "<64 lowercase hex>"}
{"path": "ROADMAP.md", "source": "generated/ROADMAP.md", "sha256": "<64 lowercase hex>"}
```

These two `source` values are markers, not tracked source paths. Their reviewed
bytes must be approved in advance; a generated hash mismatch fails the check.
Other rows still name exact tracked blobs. Capability labels and public evidence
remain required: a labelled multi-line claim-review block can cover the entry's
headline and bullets. The independent export reviewer still checks meaning and
whether roadmap prose describes plans rather than shipped capabilities.

The checker reads tracked `changes/<ticket>.md` at the clean release head and
looks up each ticket's milestone through read-only `gh api` calls; a moved
line is looked up through its OpenWiz ticket in `moved.json` (RL6). Missing or
non-version milestones, pull requests, malformed selected files and unknown
input shapes fail. Different-version lines are excluded. Selected lines follow
`changes/README.md`, ordered by numeric ticket number; no sentence is rewritten.
Five lines pass; a sixth fails and names every selected file, for the maintainer
to merge or drop in the source rather than silently truncating the entry.

The entry has this shape:

```text
## 0.0.99 · 2026-01-02

<the spec's headline>

- <the first ticket's sentence>
- <the second ticket's sentence>

<the approved tested/unproven sentence>

[Full release on GitHub](https://github.com/example-owner/example-release/releases/tag/v0.0.99)
```

It is inserted before the approved public base's older entries. Their bytes and
the preamble are preserved, including whitespace and line endings. A version
already present, even with identical content, refuses; a version older than an
existing entry also refuses. An initial public tree without a changelog gets
`# Changelog` followed by its first entry. Unknown published version headings
are refused rather than guessed.

R1's `tools/roadmap/roadmap.py --root <release checkout> --public <staging file>`
writes the public ROADMAP.md. Only exit 0 is accepted: missing milestone lines,
private wording or a failed read stops release check. The source roadmap and
STATUS.md are untouched. Both generated files are committed before R5's normal
scans and fresh-clone checks, with their actual hashes in `report.json` and
their draft text in `report.md`. The JSON report schema and check IDs are
unchanged. Publication consumes that exact checked date, head, tree and bytes;
the public repository is never written here.

Without `entry`, the legacy plan and publication-date-placeholder gate are
unchanged. A legacy check is not evidence that its placeholder can be published.

`claim_reviews` has exactly one hash-bound review per Markdown file. Every prose
line outside headings and code blocks must have a disposition in one of its
rows. A capability row starts with its public label and names public evidence,
relative to the export root (a fragment is allowed). Labels are `fixture-tested`,
`live-observation`, `source-inspection`, `unverified`, `proposal`, or `context`.
A `context` row identifies non-capability prose and can have empty evidence;
its text must still occur verbatim. Live observations require a public
`docs/evidence/` document containing the `Live-observation:` label. Labels are
case-insensitive; the ledger's status value is lowercase.

The command verifies coverage, hashes, labels, evidence paths and the known bad
claims in [findings.md](findings.md). **It does not decide that prose classified
as context really is context, or that evidence supports a claim's meaning.**
That semantic decision stays with the independent export reviewer. A passing
report records this gap and does not authorize publication.

`scan_exceptions`, when needed for a scanner's own synthetic plants, contains
`path`, `sha256`, `rule`, and `value`. Each allows only that exact matched value
for that rule in that exact reviewed revision of one file. Missing, changed,
duplicate or unused exceptions fail. Rules are `secret`, `secret-hex`,
`personal`, `identifier`, `internal`, `url`, `historical` and `invalid-json`. A `url` exception approves one
otherwise unlisted HTTP(S) URL: for example an SVG namespace, schema URL,
package-lock funding URL or a documented format template. Its value is the exact
URL after HTML/percent/JSON decoding, bound to the same path and file hash as the
other exceptions. Both the privacy scan and link validation apply that approval.
Credential URLs require an exact `url` exception even on a reserved host.
An exact `url` exception may also approve a username-only URL (no password,
not even an empty one) on any host, for example a published list of inputs
that must be rejected.
An exception may approve a synthetic credential plant only under `.invalid`,
`.example`, or the exact host `example.com`. A password on every other host
remains a refusal. Non-HTTP(S) schemes and the decoded private patterns
`closedwiz`, `/private/`, `/Users/` and `/home/` always refuse, including on a
reserved host. Other privacy checks still apply to the file.

A `historical` exception approves one exact text match from a known wording
rule, in one exact file revision. For example, the reviewed interface sentence
"It never wakes, launches, resumes or messages" needs value `It never wakes`
(the exact D3 match), with that file's path and SHA-256. The exception does not
skip the rest of the file, date checks, claim labels or evidence validation.
The D3 rule distinguishes the original unqualified claim from uncertainty such
as "not proof that a read can never wake a session or mark it read". Historical
exceptions share the other rules' stale, duplicate, exact-value and unused
checks; an unconsumed exception fails before the report can pass.
An `invalid-json` exception, with the file's own path as its value, approves
one deliberately malformed `.json` fixture (for example a truncated response)
at that exact hash. It skips only the decoded-JSON pass. Every rule still scans
the raw text.
O2 decision pointers and cross-links are admitted only in their complete
forms: `[private record](<exact comment URL>)`, a `Private record: <URL>` line,
a standalone pointer, or a standalone `was [ClosedWiz #N](<matching issue/PR>)`
/ `moved to [OpenWiz #N](<matching issue/PR>)` line. Positive numbers have no
leading zeroes; labels and target numbers must agree. Only those validated
occurrences are exempt from URL/internal-reference refusal. A second identical
URL elsewhere is still scanned. Arbitrary private file URLs, malformed pointers,
nonmatching labels and adjacent private text refuse. Pointer existence/content
remain independent-review responsibilities; this offline scan makes no live read.

Exceptions need the same file-by-file privacy review as the export. They never
skip reading a file. Unknown/changed binary assets are refused; an unchanged
binary already in the public base is read and hash-compared.

## Public paths and skill aliases

Every tracked path needs an explicit hash-bound plan row. O2’s public classes
include root status/guidance, app guidance, design documents, workflow code,
skills and public release evidence. Only `private/` and grills other than
exactly `docs/grills/README.md` are private by class. Environment files and
build/cache artifacts remain refused. Public class membership never exempts
content from the privacy, secret, claim or byte/mode checks.

Every row's `source` must name its own release path (including `AGENTS.md`);
only the two generated entry markers differ. Nothing is renamed out of a
private source or silently dropped from the complete release tree.

Git mode 120000 is preserved only for an approved `.agents/skills/<name>` or
`.claude/skills/<name>` alias row:

```json
{"path": ".agents/skills/grill", "source": ".agents/skills/grill",
 "sha256": "<SHA-256 of the raw bytes ../../skills/grill>", "mode": "120000"}
```

A link is never dereferenced. Its raw target bytes must be exactly
`../../skills/<name>`, and `skills/<name>/` must itself be exported. Absolute,
escaping, cyclic, dangling, trailing-slash and differently named targets are
refused, and so is a link without `"mode": "120000"` in its row. Every
`.agents/skills/<name>` or `.claude/skills/<name>` row must be such a link: a regular file at an alias
path is refused by the checker in both modes and by the publisher. A link
anywhere else is refused, and so is every submodule. Staging writes a real
symlink. The committed and read-back mode and blob are checked against the
row. The same rules let a later release start from a public base that already
contains aliases. Rows may carry `mode` for any file; when present it must
match the source.

## Historical verification of a published commit (#1191)

Some public versions were published before this tool could stage them. For
these, `release check` can verify an exact public commit that is already
reachable from public `main`, instead of staging a new one:

```sh
python3 tools/release/release check 0.0.5 --historical <full public commit> \
  --approved-plan-sha256 <SHA-256 of the approved plan file> \
  --public-repo /path/to/read-only-public-clone --plan /path/to/approved-plan.json \
  --literals /path/to/private-named-terms.txt \
  --staging /path/to/new-staging-directory --evidence /path/to/new-evidence-directory
```

The plan carries a `historical` section instead of `entry` (the two are
exclusive):

```json
"historical": {
  "export_head": "<the same full commit>",
  "changelog_heading": "## 0.0.5 · 2026-11-05",
  "entry_sha256": "<SHA-256 of that exact published entry>"
}
```

- **Approval.** The plan bytes must hash to `--approved-plan-sha256`, the hash
  approved with the plan. A changed plan refuses; nothing approves it silently.
- **The published commit is its own source.** Every row's `source` equals its
  `path`, and every row carries its approved `mode`. The plan must equal the
  commit's tree: path, mode and SHA-256 for each entry. Nothing is restaged over
  it, so an already-published file such as RELEASING.md keeps its published
  blob. Frozen `release/openwiz/` is untouched.
- **History.** The commit must be reachable from the public clone's `main`, and
  `public_base` (the approved base provenance) must be its ancestor. An
  existing `v<version>` tag refuses. The public clone is only read.
- **Changelog.** No entry is generated and no ROADMAP is added. Exactly one
  dated `## <version> · <date>` heading must exist. It must equal the approved
  heading, and the entry's exact bytes (heading to the next heading, trailing
  blank lines dropped) must match `entry_sha256`. Combined range headings
  (`## A–B`) and placeholders refuse, everywhere.
- **The same checks.** Privacy, historical wording, links, claims, regression
  proofs and the full fresh-clone build and tests run exactly as for a staged
  export. The fresh clone is of the historical commit itself.
- **Report.** `openwiz.release-check.v1` with the added `open-development-privacy` check id. `export_head`
  and `source_head` are the historical commit itself, never a new same-tree
  commit. `historical.public_main` records public `main` at check time. Only a
  passing report can be publishable.

## Reviewed label forms and public live-evidence summaries (#1191)

A Markdown claim row may carry `label`: the exact reviewed label text that
opens the claim (after at most a list marker), for example
`"label": "**Live observation — LIVE-0.0.4:**"`. Normalized (asterisks
dropped, spaces as hyphens, lowercase), the label must name the row's status
(`fixture-test` is accepted for `fixture-tested`). `"label": ""` marks a
reviewed unlabelled public line. Public text need not carry test labels; its
status, evidence and live-evidence checks still apply. A context row carries no
label. Rows without `label` keep the plain `Status:` prefix rule.

A live observation's evidence must still be public. Either it is under
`docs/evidence/` with the `Live-observation:` label, or it is a declared,
reviewed public summary:

```json
"evidence_documents": [
  {"path": "docs/testing.md", "sha256": "<its exact hash>",
   "status": "live-observation", "label": "<a label form it really contains>"}
]
```

A declaration must match the document's bytes, contain its label, and be cited
by at least one live claim. A missing, stale, duplicate or unused declaration
refuses. Whether the summary supports each claim's meaning remains the export
reviewer's semantic decision.

## Staging, checks and evidence

The staging directory contains two separate repositories:

```text
public release branch (descends from approved main)
  └─ staging/export, same head and tree
       └─ optional reviewed changelog/roadmap commit
            └─ staging/fresh, a clone of that exact checked head
```

Without generated files, staging preserves the release branch’s exact head.
With an entry, only the generated changelog and roadmap change, in one ordinary
commit whose parent is the release head, using the plan’s no-reply identity.
The allowlist must equal the entire staged tree; every file is read in full.
The existing release scans still cover
credentials, secret-shaped hex, personal paths/email/hosts, private ids/links,
internal references and decoded JSON strings. The public base's license must
remain unchanged; known later-version paths are refused on early release lines. Relative Markdown, reference,
image and HTML links and fragments must resolve. Links inside a closed fenced
code block are not links (an unclosed fence, or a backtick line such as
```` ```x``` ```` that is inline code, hides nothing). A relative link to an
exported folder resolves; a fragment on it does not. Unknown URL hosts fail closed.

In the fresh clone, the commands run sequentially:

1. For a web tree: `npm ci --ignore-scripts`, `npm run build`,
   `npm run typecheck`, `npm run check` in `apps/web`.
2. `cargo build --workspace --release --locked`,
   `cargo test --workspace --locked`, `cargo fmt --check`,
   `cargo clippy --workspace --all-targets --locked -- -D warnings`.
3. For a web tree: `npm test` in `apps/web`.
4. Applicable historical public regressions by name (nonzero exact counts),
   then the release binary's `--help`, checking trailing whitespace.

A plan may name an approved successor for a renamed regression proof:
`"regressions": [{"id": "0.0.3-R3", "proof": "tests/<target>/<file>.rs",
"tests": ["<test name>"]}]`. The id must be a table id with named Rust tests.
Each successor test must be a `#[test]` function in the proof file, and that
file must be a module its target's `main.rs` declares. Comments and string
literals are blanked first (an unterminated one refuses). Then every top-level
form of `main.rs` and of the proof file must be on an allowlist:
- attributes;
- `mod`, `use`, `fn`, `const`, `static`, `struct`, `enum`, `impl`, `type` and
  `trait` items, optionally with `pub(...)`, `unsafe`, `async`, `extern` or
  `const fn`.

Any item-level macro (`name!`, `macro_rules!`, `include!`), `extern crate`,
stray token or dangling attribute refuses, because a macro could generate or
redirect the very items being checked. Macros inside item bodies are not
inspected. The module must be declared exactly once, as a plain `mod
<module>;` with no attribute, so a `#[path]` or `cfg_attr` override, an
inline module or an ambiguous `<module>/` folder refuses. Each test must be the
proof file's one top-level `fn` of its name and carry `#[test]`; two of the name
refuse, since `cfg` could choose which one runs. The inspected `main.rs` must be
the file Cargo builds, read from the manifests: exactly one exported manifest
names `openwiz-tests`, its folder is listed by name in the root workspace's
`members`, it sets `autotests = false`, and exactly one `[[test]]` of the
target's name carries only `name` and `path`, resolving to
`tests/<target>/main.rs`. A redirected path, a missing or repeated entry,
`harness`, auto-discovery, a glob member or an unreadable manifest refuses.
This is lexical, not a Rust compiler or Cargo: a form outside the allowlist
refuses rather than passes. It runs by its full
identity, `cargo test -p openwiz-tests --test <target> -- --exact
<module>::<test>`, never as a substring filter, and must pass exactly once.

Before that run, the compiler binds the approved body (R3, Jake's ruling (a)
on #1191). In a scratch clone of the export, with its own target directory,
the approved test's `{ ... }` body becomes `{ panic!("<random nonce>"); }`. The
same `--exact` identity must then exit nonzero with `test result: FAILED. 0
passed; 1 failed;` and print the nonce. A macro, build script or Cargo config
that swaps or drops the approved body cannot print it, so the check refuses.
Any other failure refuses too, and so does an approved `#[should_panic]` test,
whose nonce panic passes. The scratch clone is then removed; its output stays
in the evidence as `<id>-<identity>-nonce.log`. The residue is a deliberately
selective macro that keeps only nonce-shaped bodies, which export review sees.
Every applicable table id is still
covered, by its default or by its successor. Unknown, duplicate or unused
successors refuse; nothing is retired silently.

A missing tool, timeout, nonzero exit, empty/filtered-out test run or tracked
file changed by checks fails. Cargo and npm caches, HOME, temporary files and
build output are under staging. Rustup reads the installed toolchain; the tool
does not install one. Project build/test programs are trusted code, not an OS
sandbox; the recording-fake proof covers the command's own writes and calls.

The evidence directory contains `report.md` (one-page summary with expandable
full hashes), `EXPORT-FILES.txt`, `report.json` and command logs. Failure after
output creation also writes a failing report. Outputs are never reused, so an
old passing report cannot be silently reused by a new check.

`report.json` uses `openwiz.release-check.v1`. Its publication handoff fields are
`version`, `source_head`, `public_base`, `export_head`, `export_tree`,
`plan_sha256`, and `files` (`path`, `sha256`, git `mode`). `status` is exactly
`pass` or `fail`; `checks` records each completed check's id/status and a reason
on failure. A failed stage may have no export head and only partial files.
`live_pending` is counted from the tree, never copied from the plan, and must
match the declared count. `publishable` is false while any LIVE-PENDING remains.
Even when it is true, R7 must independently verify Jake's approval, head, tree,
files and the absence of pending placeholders before publishing. This report
never substitutes for that gate.

## Proofs

```sh
python3 tools/release/test.py          # includes P9, entry, publish, backfill and scan fixtures
python3 tools/release/review_mutants.py
```

`test_backfill.py` covers #1191: product rows and aliases, refused paths and
links, historical verification and its refusals, the approved existing entry,
reviewed labels and live summaries, and `publish --backfill` from a real
historical report.

These use synthetic release/public repositories, a real git wrapped by a
recording fake, and fake Cargo/npm/node/gh. Historical product regressions are
public exported tests, rerun by name; this suite simulates their results to
prove orchestration and refusal. It does not re-prove the product fixes.
The clean-tree proof sets HOME and TMPDIR inside its scratch tree and compares
that entire tree, including the plan, before and after the command. Only staging,
evidence and the recording fake's calls.jsonl are excluded. `review_mutants.py`
uses disposable copies to verify that separate HOME/TMPDIR/plan writes and
removing either live-evidence guard each make their targeted proof fail.
The clean fixture has also been built and tested with real Cargo; its report
and logs are under `private/evidence/infra-plan-ship/r5/clean/`.

## Export wording and comment regressions

`release check` runs `review_rules.py` during historical-wording validation.
It rejects the recorded 0.0.5 release-state, private-hash, command-result,
historical-guide and dependency-row slips, plus broad comment-scrub residue:
review/correction rounds and contextual finding/reviewer ids, pointers to
private/evidence material, spaces before punctuation/orphan punctuation, and
prose words glued to code/media extensions. Shape-bound check placeholders
are refused while ordinary health/fleet comments containing "the check" pass.
Extension/dotfile mentions (including `not .ts or .tsx`) and indented shell
commands retain their punctuation. Markdown also rejects an opening
parenthesis immediately followed by separator punctuation.

The comment scanner handles inline, block and adjacent comment lines while
excluding runtime strings, raw strings, templates and shell heredoc payloads.
Code spans retain literal filenames and syntax. Generic rules have planted
failing fixtures, wording variants and positive controls under
`tests/fixtures/release/export-review/`. Private commit tokens in README/testing
must resolve in the public base's history, including older public ancestors.

Run `python3 -B tools/release/test_export_review.py` for these regressions.
The existing `python3 tools/release/test.py` CI entrypoint includes them too.
These tests use synthetic inputs and no product suites or live calls. The
patterns guard known classes; independent semantic export review, the claim
ledger and maintainer approval remain required. The checker never publishes.

## Prebuilt artifacts (0.0.13)

The manual `Packages` workflow assembles artifacts only for Apple silicon Mac,
Intel Mac and Linux x86_64. It never publishes, tags or pushes. Each native job
builds the same three programs and web export at its exact source commit, checks
the embedded service commit and native executable architecture, copies the
tracked skill runtime, and writes a complete `openwiz.build-products.v1`
inventory. `build_products.py` records every asset's path, size, mode and SHA-256;
`package.py` refuses changed, missing, extra or linked products before assembly.
The reviewed version is applied to the workspace package version for the three
program builds; protocol/envelope versions stay independent. Matching build
stamps in web/ and runtime/ bind the same version, source and target; a manifest
cannot relabel those bytes as another version.

A target artifact contains its versioned tar.gz, manifest, SHA256SUMS, and stable
`openwiz-<target>.manifest.json` / `openwiz-<target>.sha256` aliases for pull-only
update discovery. The aliases contain the same reviewed manifest bytes. Release
publication must include all three targets' exact reviewed files on the matching
`v<version>` release. Partial publication is not a successful release. The
workflow itself provides no publication authority or signed publisher identity.

New binary release archives require one exact `scan_exceptions` review with
rule `release-asset`, path `packages/openwiz-<version>-<target>.tar.gz`, SHA-256
bound to those reviewed bytes, and value `<version>@<source-commit>@<target>`.
The version must match the release being checked and the target must be one of
the three declared install targets. Duplicate, stale, unused and differently
named reviews fail. This is an explicit independent export review of the entire
archive, including its runtime/text and compiled programs, not a privacy scan
of opaque bytes. Unknown binaries still fail. The review and checked file list
bind publication to the same bytes, like the existing licensed font boundary.

Offline proofs (also registered in normal CI):

```sh
python3 -I tools/install/test_install.py
python3 -I tools/install/test_pull.py
python3 -I tools/release/test_package.py
python3 tools/release/test.py
```

The installer and fixed published-release transport are documented in
`contracts/install.v1.md`; resumable independent setup/effect interfaces are in
`contracts/setup.v1.md`. These fixtures prove integrity, refusal and staging,
not native execution, account readiness, publisher identity or live elapsed time.
