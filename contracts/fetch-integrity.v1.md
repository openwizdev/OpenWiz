# OpenWiz fetch integrity v1

`openwiz.fetch-integrity.v1` covers OpenWiz-controlled fetches of code and data
for installation or execution, including the install bootstrap, updates and
fetches delegated to a package manager. It covers the two install routes
planned for WizPlugins and WizMarket. Ordinary API reads, GitHub work records,
downloads the owner performs independently, and development and release
test tooling are outside this contract.

## Run after check

Every listed path must finish all integrity checks before any fetched code or data is run or installed.
Until then, fetch into inert staging and read only what the verifier needs.
On an integrity failure, stop the path and keep the last working selection.
A retry must verify the payload it will use. The approval and activation rules
of each installer still apply.

## Fetch paths

The checks below are requirements. The refusal column gives the exact
integrity message for each path. It names the entry point and the file that
cannot be used, even when the check that failed was on a companion file.
Angle brackets in these messages are literal, including for versioned files.
Never include fetched bytes, hashes, remote error text or untrusted filenames
in an integrity refusal. An existing structured error can carry the line as
its message.

| Fetch path | What it verifies | Fixed refusal line |
| --- | --- | --- |
| Install bootstrap | [Install instructions](../docs/install.md) fetch the checkout that supplies `tools/install/install`. Before using the checkout, verify its exact commit and tree against an independently known pin. A release tag or branch alone supplies no independent pin. | `fetch integrity refused: Install bootstrap: tools/install/install` |
| Install line | [`tools/install/install`](../tools/install/install) checks the target manifest against its `.sha256` sidecar and verifies that `SHA256SUMS` names the exact manifest and archive and matches both their digests. It checks the archive SHA-256 and length against the manifest and checks every member's path, mode, length and hash under [verified install v1](install.v1.md). The public and opt-in early downloads use the same checks. | `fetch integrity refused: Install line: openwiz-<version>-<target>.tar.gz` |
| Packaged update | [`tools/install/pull.py`](../tools/install/pull.py) binds the staged manifest to the discovered candidate's SHA-256 and release version, source and target. It checks the exact manifest and archive entries in `SHA256SUMS` and uses the verified installer to check the archive and its members. This applies on both packaged and early channels. | `fetch integrity refused: Packaged update: openwiz-<version>-<target>.tar.gz` |
| Driver fetcher | The [driver package contract](driver-package.v1.md#find-check-ask-install) and #2995 bind the release tag, commit and HTTPS asset to a first-party pin or a listing from one recorded market commit. Check the pinned archive SHA-256 before parsing, verify `SHA256SUMS` and `manifest.json`, then verify the archive members, driver name and `schema.json` as the package contract requires. | `fetch integrity refused: Driver fetcher: driver.tar.gz` |
| WizSkills install | [`tools/wizskills/install.py`](../tools/wizskills/install.py) checks the annotated tag's release record and target against the version, pinned commit and tree in `wizskills.lock`. It takes the executable `install.sh` from that tree, uses the checked local Git objects for installation and verifies the resulting checkout before use. | `fetch integrity refused: WizSkills install: install.sh` |
| Boat skill install | [`adapters/boat/driver`](../adapters/boat/driver) checks that the sandbox's fetched tag resolves to the commit in `wizskills.lock` and that the commit's tree matches the lock. It takes `install.sh` from that commit, uses the local objects for installation and checks the installed commit and tree before linking skills. | `fetch integrity refused: Boat skill install: install.sh` |
| Sprites skill install | [`adapters/sprites/driver`](../adapters/sprites/driver) uses the same `wizskills.lock` commit and tree checks for the tag and installed checkout, with the checked local objects as the source of `install.sh` and its install. | `fetch integrity refused: Sprites skill install: install.sh` |
| Sprites harness install | The npm install in [`adapters/sprites/driver`](../adapters/sprites/driver) needs a pinned version and expected digest for each fetched package, including dependencies. Verify each downloaded tarball against its pin before installation or lifecycle scripts. | `fetch integrity refused: Sprites harness install: <package>.tgz` |
| CloudRoom install | [`tools/install/cloudroom/cloudroom.py`](../tools/install/cloudroom/cloudroom.py) binds the platform asset to the selected release. It checks the published length and SHA-256 of `SHA256SUMS.txt`, cross-checks its asset entry against the release metadata, then compares the staged download's length and SHA-256 with the approved asset before mounting the disk image or placing the AppImage. | `fetch integrity refused: CloudRoom install: download.part` |
| MeMo training | The launcher generated by [`tools/memo/memo.py`](../tools/memo/memo.py) checks the upstream repository, pinned commit, clean checkout and required files before launching training. A model the trainer fetches also needs a pinned revision and a digest check of its fetched files before loading. | `fetch integrity refused: MeMo training: sft_lora_pipeline.py` |
| Plugin install | SE4 (#3460), including WizBar marketplace installs and the T3 board fetch, must resolve each plugin to an exact commit and verify the fetched tree against the tree checksum from the trusted plugin entry. A version range cannot satisfy the pin. | `fetch integrity refused: Plugin install: marketplace/<plugin>.json` |
| Market one-tap install | The WizMarket tap enters the WizSkills driver install route (#3972). It uses the driver fetcher with the same listing snapshot and pinned release, archive checksum, manifest, driver name and `schema.json` checks. A failed check stops the fetch step before key setup, live checks or activation. | `fetch integrity refused: Market one-tap install: driver.tar.gz` |

## Evidence

SE3b (#3965) owns the tamper proof for the install line, driver fetcher and
WizSkills install. It uses local fixtures with a changed archive byte, a
swapped manifest or a checksum file that names another file. Each refusal must
match the line for its entry and leave the fixture's run marker absent. SE4
(#3460) owns the plugin pin and tamper proof. The one-tap fetch step (#3972)
owns its refusal and stop proof.

This contract records the checks and messages for those consumers. In the
current code, the install bootstrap selects a Git ref, Sprites installs
harnesses by package name, and the MeMo launcher selects a model by name.
Their independent pins and associated checks are gaps. The new refusal
lines are the interface for implementation and proof work.
