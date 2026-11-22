# 0.1.1 release gates, as `release candidate` runs them (main at `ae10e283`)

`evaluate` runs all 18 publish preconditions and collects every reason. `publish` runs them again before the tag and before the release (`tools/release/README.md`).

| # | Gate | Function | What it needs for 0.1.1 |
| --- | --- | --- | --- |
| 1 | Sealed candidate unchanged | `reasons_for` | `prepare` once on `release-0.1.1` with body, artifacts, entry and risk; no later edit |
| 2 | Source | `check_source`, `release_source`, `release_protection` | the commit on protected `release-0.1.1`, ruleset readable, tree as sealed |
| 3 | Versions | `check_versions` | `0.1.1` newer than `v0.1.0` |
| 4 | Notes and `CHANGELOG.md` | `check_notes` | `changes/notes/0.1.1.md` and `CHANGELOG.md` on the branch, both equal to the approved bytes, with v0.1.0's changelog unchanged below |
| 5 | Decisions | `resolve_decision` | the owner's unedited private comments `Release decision: changelog <notes sha256>` and `Release decision: ship <candidate sha256>` |
| 6 | D3 cut-over | `cutover_reasons` | O17 closed, no hold, immutable releases on, `main` rulesets requiring `ci` and `privacy` with no bypass |
| 7 | D1 and D2 | `required_check`, `scan_artifacts` | `ci` and `privacy` green at the exact commit (full runs); every archive staged and privacy-scanned with the named literals |
| 8 | D4 claims | `claims_reasons` | the notes are what the curated entry yields at the commit |
| 9 | D5 kit authority | `kit_reasons` | the owner's `Release kit authority: scope <scope sha256>` for the 0.1.1 kit |
| 10 | D6 risk | `risk_reasons` | one row per path changed since `v0.1.0`; `new` (`crates/core/src/new_thread/options.rs`) and `app_permissions` (`tools/github-app/**`) are `yes` |
| 11 | Products | `gate_reasons` | the `products` receipt for the compiled archives |
| 12 | Waiver | `current_waiver` | none expected |
| 13 | Live | `live_reasons` | a live smoke receipt from the combined kit, plus `new` and `app_permissions` receipts, on the candidate's Linux archive |
| 14 | Date | `date_reasons` | the `## 0.1.1 · <date>` heading equals the publish day in UTC |
| 15 | Assets | `check_artifacts` | all 13 files: 3 archives, manifests, aliases, `SHA256SUMS`, inventory |
| 16 | Immutable releases | `immutable_reasons` | on |
| 17 | Tag | `tag_reasons` | `v0.1.1` absent |
| 18 | Tagger | `tagger` | the candidate commit's author is a plain name with a `<id>+<login>@users.noreply.github.com` email |

After publish, `install` takes the stranger's `releases/latest` route. It stays `blocked` (`install_latest_unresolved`) while v0.1.1 is a pre-release: `publish` always creates a pre-release, so "Latest is v0.1.1" needs the pre-release flag cleared after the read-back, as v0.1.0's was. Planned: after `publish` reads back `published`, clear the flag (`gh release edit v0.1.1 --prerelease=false --latest`), read back `releases/latest` as v0.1.1 named `OpenWiz 0.1.1`, then run `install` for each target.

The agent rehearsal ([rehearsal.md](rehearsal.md)) is #2265's ship condition. It isn't a release-tool gate, and it doesn't satisfy row 13.
