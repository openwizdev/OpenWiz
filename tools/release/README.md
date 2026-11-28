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

The check saves both generated files under `<staging>/generated/`, a hash mismatch refusal names the actual SHA-256, and `report.md` lists both files' hashes, so the approver can hash and review those exact bytes.

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
$RC install --state "$STATE" --target "$TARGET"
$RC status --state "$STATE"
```

Each pointer is the URL of the private-record comment holding that decision. A recorded waiver is read the same way, with `decide --state "$STATE" --waiver "$WAIVER_POINTER"`.

- **Notes** come from `changes/` at the clone's head (or a curated `changes/notes/<name>.md` named with its hashes in `entry.json`); five lines a section, except J6's recorded counts for the combined 0.0.6–0.0.12 release. The output is a proposal.
- **Prepare** seals the candidate body: public repository, fixed anchor, a commit on public `main` or on its protected `release-<version>` branch, versions in order and newer than every tag, exact notes and `CHANGELOG.md`, a complete product inventory and a risk classification. Preparing again saves only a changed entry or classification.
- **Decisions** are read from the private comment itself: unedited, by the owner, starting `Private record: Jake, YYYY-MM-DD`, with one `Release decision: ship <candidate_sha256>` or `Release decision: changelog <notes sha256>` line (`Release decision revoked: <comment id>` revokes it).
- **Gates**, each one constant or function in `candidate.py`: D1 `ci` and `privacy` green at the exact commit; D2 every archive staged and privacy-checked; D3 `cutover` (O17 closed, no hold, immutable releases on, rulesets requiring `ci` and `privacy` with no bypass); D4 `claims` (the notes are exactly what `changes/` generates); D5 kit authority (`Release kit authority: scope <scope_sha256>`); D6 a risk row for every changed path. `products` checks the compiled archives; `live` takes the [live smoke](../live-smoke/README.md) receipt, and each risk classified `yes` needs its own.
- **Evaluate** runs every check `publish` makes before its first write, with the same functions and reasons, so `ready` means `publish` would pass them now (#2127). The table lists them in `publish`'s order. When an early repository is configured (`--early-repo OWNER/NAME` or `EARLY_REPOSITORY` in `candidate.py`, default off) and every gate passes, `evaluate` publishes the same notes and artifact bytes as a GitHub pre-release tagged `v<version>-rc.<n>` (`--rc`, default `1`) with `--prerelease --latest=false`, checks the tag is absent (or already holds the exact same bytes), records `early-attempt.json` before writing so an uncertain write is inspected rather than retried blindly, reads back every remote byte, and saves the early publish timestamp in `evidence/early-publish.json`.
- **Publish** re-checks every gate, records each write in `attempt.json` before making it, pushes only the annotated tag, creates the pre-release with the exact notes and assets, and reads it all back. A mismatch is `incomplete`; an interrupted write is `uncertain` until a read-back settles it. It never retries a write. When `evidence/early-publish.json` records a completed early publish for the release version, `publish` reports the elapsed lead time in its output and `evidence/readback.json`, noting plainly when it is under 72 hours without blocking publication.
- **Release name** comes from `PUBLIC_NAMES` in `candidate.py` (J264: `0.1.0` is `OpenWiz 0.01`), else `OpenWiz <version>`; the publish write and its read-back both use it, while the tag and its message stay semver.
- **Install** takes a stranger's real route, never `gh release download <tag>`: it runs the installer's own `download`, `install` and `status` (`tools/install/install`, the commands the install skill runs) for one `--target` into a new, empty folder, fetching only the URLs a stranger's agent fetches (`releases/latest/download/openwiz-<target>.sha256` and `.manifest.json`, then the archive the manifest names). It records the result only when `latest` resolves to this candidate's version and commit, the downloaded manifest and archive are the candidate's bytes, and the clean install verifies. GitHub's `latest` skips pre-releases and drafts, so while the release is a pre-release the check is `blocked` by what the `latest` route returns: a 404 on the first request, the target's `latest/download/openwiz-<target>.sha256`, gives `install_latest_unresolved`, and another release's version gives `install_latest_not_candidate`; a 404 on any later asset (the manifest, the archive or `SHA256SUMS`) is a download refusal, `install_download_refused`, as is any other download refusal; a refused install or status is `install_refused`, and other bytes are `install_mismatch`. Each attempt writes its outcome, every URL with its HTTP status and each installer output to its own new file, `evidence/install-<target>/<n>.json`, which appears only whole: the bytes are written and synced to a private temporary file, then hard-linked under the next unused number; a retry or an overlapping check for another target never replaces or drops another attempt's file, and there is no shared index to lose. The record's install entry stays the last passed attempt. `status` lists each checked target's latest attempt, with its hash, as `install_attempts`, and reads `incomplete` while any of them is blocked. It proves the published files install on that route from a clean folder; it runs no binary and installs no skills into an agent, so it proves nothing about the target machine, sign-in or setup. `status` reports elapsed time from the ship decision against the 30-minute target.

### Publish preconditions

`publish` runs rows 1 to 17 before it pushes the tag and again before it creates the release (then accepting its own tag in row 17), and row 18 before the tag. `evaluate` runs all 19, collecting every reason. `publish` collects the UTC date reason of row 14 with the shared gate reasons of rows 1 to 13, then stops at the first later failure.

| # | Precondition | Function in `candidate.py` | Reasons |
| --- | --- | --- | --- |
| 1 | The sealed candidate is unchanged | `reasons_for` | `candidate_changed` |
| 2 | Public source at the anchor, on `main` or its protected `release-<version>` branch, with the sealed tree | `check_source`, `release_source`, `release_protection` | `private_source`, `unrelated_history`, `not_on_public_main`, `not_on_release_branch`, `release_branch_wrong_version`, `release_branch_unreadable`, `release_branch_unprotected`, `release_ruleset_unreadable`, `tree_mismatch` |
| 3 | Versions in order and newer than every published tag | `check_versions` | `invalid_versions`, `version_order` |
| 4 | The exact notes and `CHANGELOG.md` | `check_notes` | `changelog_*`, `section_changed`, `invalid_changelog` |
| 5 | Ship and changelog decisions recorded and current | `resolve_decision` | `ship_*`, `changelog_*` |
| 6 | D3 cutover: O17 closed, no hold, immutable releases on, `main` rulesets requiring `ci` and `privacy` with no bypass | `cutover_reasons` | `cutover_unverified` |
| 7 | D1 required checks `ci` and `privacy` green at the commit; D2 staged archives privacy-checked | `required_check`, `scan_artifacts` | `ci_*`, `privacy_*` |
| 8 | D4 notes are what `changes/` generates | `claims_reasons` | `claims_*` |
| 9 | D5 kit authority | `kit_reasons` | `kit_authority_*` |
| 10 | D6 a risk row for every changed path | `risk_reasons` | `risk_classification_*` |
| 11 | The products gate receipt | `gate_reasons` | `products_*` |
| 12 | Any waiver still recorded | `current_waiver` | `waiver_*` |
| 13 | A live receipt for the smoke and each `yes` risk | `live_reasons` | `smoke_*`, `<risk>_*` such as `send_live_missing` |
| 14 | Every notes section dated the publication day in UTC | `date_reasons` | `changelog_date` |
| 15 | Asset bytes, hashes, links and manifests match the candidate | `check_artifacts` | `artifacts_incomplete`, `invalid_artifacts`, `artifacts_unreadable`, `artifact_changed`, `artifact_links`, `artifact_manifest`, `artifact_archive` |
| 16 | Immutable releases on | `immutable_reasons` | `immutable_releases_off` |
| 17 | The tag absent (or, before the release, exactly the tag this attempt pushed) | `tag_reasons` | `tag_exists` |
| 18 | The tagger: the candidate commit's author name matches `[A-Za-z .-]+` and its email `<digits>+<login>@users.noreply.github.com` | `tagger` | `tagger_identity` |
| 19 | The install rehearsal of every target in `TARGETS` passed on the candidate's sealed archives | `rehearsal_reasons` | `rehearsal_missing`, `rehearsal_failed`, `rehearsal_untrusted`, `rehearsal_stale`, `rehearsal_unreadable` |

Row 19 is checked once by `evaluate` and once by `publish`, after row 18 and before the tag. It applies `required_check`'s trust rules to the latest non-skipped run of `.github/workflows/packages.yml` at the candidate commit: its `rehearsal` check run is from the `github-actions` app and completed `success`. For every target in `TARGETS`, that run's newest unexpired `openwiz-rehearsal-<version>-<target>` artifact must have a `sha256:` digest that matches its zip, and must hold one [`openwiz.rehearsal.v1`](../../contracts/rehearsal.v1.md) receipt reading `pass`, with `version`, `source` and `archive_sha256` equal to the candidate's release version, commit and sealed archive row. On a pass it writes `evidence/rehearsal.json` in the state folder. The rehearse jobs keep receipts for 7 days (`retention-days: 7`, shorter than the repository's 90-day default). An expired receipt reads `rehearsal_missing`; the fix is a fresh Packages run on the candidate commit. That run must build the same archive bytes, or the receipt reads `rehearsal_stale` and the candidate must be prepared again.

Before these, `publish` alone reads its own record: a complete publication returns `published`, a recorded incomplete one refuses `publication_incomplete`, and an interrupted attempt is settled by read-back instead of re-checked. No separate check looks for an existing release: one can only be created on the tag, which row 17 requires absent.

## Prebuilt artifacts

The manual `Packages` workflow builds Apple silicon Mac, Intel Mac, Linux x86_64 and Linux arm64 archives at the exact source commit, each with its `openwiz.build-products.v1` inventory (`build_products.py`, `package.py`), manifest, `SHA256SUMS` and stable `openwiz-<target>.manifest.json` and `.sha256` aliases. It never publishes. A release must carry all four targets' exact files. The installer side is in `contracts/install.v1.md` and `contracts/setup.v1.md`.
