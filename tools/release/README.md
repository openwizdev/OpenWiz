# Release tools

`tools/release/release` has three commands. None installs anything; Python 3.11+, Git, and Cargo with rustfmt and clippy must already be present. No third-party Python package.

- `release check` stages and checks one release from the public repository's clean `release-<version>` branch. It never pushes, fetches, tags or publishes.
- `release candidate` prepares, gates and publishes one checked public candidate ([`openwiz.release-candidate.v1`](../../contracts/release-candidate.v1.md)).
- `release publish` publishes an exact checked export on the maintainer's `publish VERSION`.

Under [ADR 0020](../../docs/adr/0020-release-on-demand.md), after the verified cut-over, Jake's ship instruction and exact changelog approval are the only human release steps; every other gate is automatic. Nothing here performs or authorises the cut-over, widens a live kit or clears a hold.

```sh
python3 tools/release/test.py                 # the offline suite (CI); includes entry, publish, backfill and scan fixtures
python3 -B tools/release/test_export_review.py
python3 tools/release/review_mutants.py
python3 -I tools/release/test_package.py
```

## `release check`

```sh
python3 tools/release/release check "$VERSION" --repo "$CHECKOUT" --plan "$PLAN" \
  --literals "$PRIVATE_TERMS" --staging "$NEW_STAGING_DIR" --evidence "$NEW_EVIDENCE_DIR"
```

- The checkout holds the approved `main` commit named by the plan's `public_base`, an ancestor of the release branch. The repository name comes from its single github.com `origin`.
- `--literals` is the approved, complete private named-terms list from the [open development contract](../../contracts/open-development.v1.md#the-privacy-check): UTF-8, one literal term per line. Supply it from outside the tree with its provenance; never guess a sibling checkout. It is never copied or printed.
- Both output folders must be new, separate, outside the checkout, with no symlink in their paths; the tool writes only there.
- It runs the privacy check on the whole release tree and history, then again on the staged tree; it scans every file for credentials, personal and private data, internal references and broken relative links, and checks claims and wording (`review_rules.py`). In a fresh clone of the staged head it runs `cargo build --workspace --release --locked`, `cargo test --workspace --locked`, `cargo fmt --check`, `cargo clippy --workspace --all-targets --locked -- -D warnings`, the historical regressions by name and the binary's `--help`.
- Evidence: `report.md`, `EXPORT-FILES.txt`, `report.json` (`openwiz.release-check.v1`, `status` `pass` or `fail`, `publishable` false while any LIVE-PENDING remains) and the logs. A passing report is not approval to publish.

### The plan (`openwiz.release-plan.v1`)

An allowlist of every tracked file with its hash; unknown keys, unsafe paths, submodules and mismatched hashes fail. `source` equals `path` except the two generated markers.

```json
{
  "schema": "openwiz.release-plan.v1",
  "version": "0.0.99",
  "public_base": "<40 hex>",
  "identity": {"name": "Synthetic Maintainer", "email": "123+synthetic@users.noreply.github.com"},
  "files": [{"path": "README.md", "source": "README.md", "sha256": "<64 hex>"}],
  "claim_reviews": [{"path": "README.md", "sha256": "<same>", "claims": [
    {"text": "Fixture-tested: A synthetic command prints usage.", "status": "fixture-tested", "evidence": "docs/evidence/check.md#fixture"}]}],
  "live_pending": 0,
  "scan_exceptions": []
}
```

- **`claim_reviews`:** one hash-bound review per Markdown file; every prose line has a row. Statuses: `fixture-tested`, `live-observation`, `source-inspection`, `unverified`, `proposal`, `context`. A row may carry the exact reviewed `label`. A live observation needs public evidence: a `docs/evidence/` file with `Live-observation:`, or a reviewed `evidence_documents` entry. The tool checks coverage, hashes and labels, never whether context really is context or evidence supports the meaning: that stays the reviewer's.
- **`scan_exceptions`:** `{path, sha256, rule, value}` allows one exact match in one exact file revision. Rules: `secret`, `secret-hex`, `personal`, `identifier`, `internal`, `url`, `historical`, `invalid-json`, and `release-asset` for each binary archive (`packages/openwiz-<version>-<target>.tar.gz`, value `<version>@<source-commit>@<target>`). Stale, duplicate or unused exceptions fail. Credential URLs pass only on `.invalid`, `.example` or `example.com`; private paths always refuse.
- **Skill aliases:** `.agents/skills/<name>` and `.claude/skills/<name>` rows must be symlinks with `"mode": "120000"` whose target is exactly `../../skills/<name>`. Any other link or a submodule refuses.
- **Regression successors:** `"regressions": [{"id": "0.0.3-R3", "proof": "tests/<target>/<file>.rs", "tests": ["<name>"]}]` names a renamed proof. It runs by exact identity, after a planted-panic run proves Cargo builds that exact body.

### The entry

With an `entry`, the check generates the version's `CHANGELOG.md` section and the public `ROADMAP.md` (from `tools/roadmap/roadmap.py --public`). Their plan rows use `"source": "generated/CHANGELOG.md"` and `"generated/ROADMAP.md"` with their approved hashes.

```json
"entry": {"spec": 4100, "date": "2026-01-02", "tested": "Fixture-tested: ...; live export remains unverified."}
```

For a combined release `entry` is a list, newest first, of `{version, spec, date, tested}`. The spec is the version's parent issue with its `## Changelog headline`; the lines are that milestone's `changes/<ticket>.md` files (moved ClosedWiz lines through `moved.json`), in ticket order, at most five. Each version's heading `## <version> · <date>` appears once, newer than every published one; range headings refuse.

### Published commits

`--historical COMMIT --approved-plan-sha256 SHA --public-repo CLONE` verifies a version already on public `main` instead of staging one. The plan carries `"historical": {"export_head", "changelog_heading", "entry_sha256"}` instead of `entry`, must equal that commit's tree exactly, and runs the same checks. `release publish --backfill` publishes from that report.

## `release candidate`

Each subcommand reads one private state folder, records the outcome in its `record.json` and prints one JSON object: exit 0 `prepared`, `recorded`, `ready`, `published` or `complete`; exit 1 `blocked`, `incomplete`, `uncertain` or `refused`, with every reason. It never waits: run it again on the next event.

```sh
RC="python3 tools/release/release candidate"
$RC notes "$VERSION" --repo "$CLONE" --entry entry.json --out "$NOTES_DIR"
$RC prepare --state "$STATE" --repo "$CLONE" --body body.json --artifacts "$ARTIFACTS" --entry entry.json --classification risk.json
$RC decide --state "$STATE" --changelog "$CHANGELOG_POINTER"
$RC decide --state "$STATE" --ship "$SHIP_POINTER"
$RC gate --state "$STATE" --gate products --receipt r.json --inputs i.json --repo "$CLONE" --artifacts "$ARTIFACTS"
$RC live --state "$STATE" --kit "$KIT" --smoke-state "$SMOKE_STATE" --record "$RECORD_POINTER"
$RC evaluate --state "$STATE" --repo "$CLONE" --artifacts "$ARTIFACTS" --literals "$TERMS"
$RC publish --state "$STATE" --repo "$CLONE" --artifacts "$ARTIFACTS" --literals "$TERMS"
$RC install --state "$STATE" --receipt install.json
$RC status --state "$STATE"
```

Each pointer is the URL of the private-record comment holding that decision. A recorded waiver is read the same way, with `decide --state "$STATE" --waiver "$WAIVER_POINTER"`.

- **Notes** come from `changes/` at the clone's head (or a curated `changes/notes/<name>.md` named with its hashes in `entry.json`); five lines a section, except J6's recorded counts for the combined 0.0.6–0.0.12 release. The output is a proposal.
- **Prepare** seals the candidate body: public repository, fixed anchor, a commit on public `main` or on its protected `release-<version>` branch, versions in order and newer than every tag, exact notes and `CHANGELOG.md`, a complete product inventory and a risk classification. Preparing again saves only a changed entry or classification.
- **Decisions** are read from the private comment itself: unedited, by the owner, starting `Private record: Jake, YYYY-MM-DD`, with one `Release decision: ship <candidate_sha256>` or `Release decision: changelog <notes sha256>` line (`Release decision revoked: <comment id>` revokes it).
- **Gates**, each one constant or function in `candidate.py`: D1 `ci` and `privacy` green at the exact commit; D2 every archive staged and privacy-checked; D3 `cutover` (O17 closed, no hold, immutable releases on, rulesets requiring `ci` and `privacy` with no bypass); D4 `claims` (the notes are exactly what `changes/` generates); D5 kit authority (`Release kit authority: scope <scope_sha256>`); D6 a risk row for every changed path. `products` checks the compiled archives; `live` takes the [live smoke](../live-smoke/README.md) receipt, and each risk classified `yes` needs its own.
- **Publish** re-checks every gate, records each write in `attempt.json` before making it, pushes only the annotated tag, creates the pre-release with the exact notes and assets, and reads it all back. A mismatch is `incomplete`; an interrupted write is `uncertain` until a read-back settles it. It never retries a write.
- **Install** records a matching install receipt; `status` reports elapsed time from the ship decision against the 30-minute target.

## Prebuilt artifacts

The manual `Packages` workflow builds Apple silicon Mac, Intel Mac and Linux x86_64 archives at the exact source commit, each with its `openwiz.build-products.v1` inventory (`build_products.py`, `package.py`), manifest, `SHA256SUMS` and stable `openwiz-<target>.manifest.json` and `.sha256` aliases. It never publishes. A release must carry all three targets' exact files. The installer side is in `contracts/install.v1.md` and `contracts/setup.v1.md`.
