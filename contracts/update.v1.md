# OpenWiz update v1

`openwiz update --check` reads the latest published OpenWiz release on GitHub
without signing in. It checks the release for the installed program's target.
`--check --json` returns one report conforming to [the update v1 schema](update.v1.schema.json).
The check is read-only. The command starts no timer, service or scheduled job.

## Report

All five fields appear once in a single UTF-8 JSON object. Readers refuse
duplicate keys, unknown fields and values outside the schema.

| Field | Meaning |
| --- | --- |
| `current` | Installed version as `0.MINOR.PATCH`, without the `v` tag prefix or leading zeroes in either component. |
| `latest` | Version of the release being checked, in the same form as `current`. Use `null` when verification fails and no candidate version can be determined. |
| `verified` | Whether the tagged release, package manifest and checksums passed verification. |
| `reason` | `null` for a verified newer release, `not-newer` for a verified release at or below `current`, or a failure reason when `verified` is `false`. |
| `changelog_line` | The first sentence of the verified release's published changelog on one line, with any heading or list marker omitted. Use `null` when `verified` is `false`. |

Compare version components numerically. An offer requires `verified: true` and
`latest` greater than `current`. Report an equal or older verified release as
`not-newer` and withhold the offer. Report every unverified release with its
failure reason and withhold the offer.

| Failure reason | When to use it |
| --- | --- |
| `release-record-missing` | GitHub has no published release record for the candidate. |
| `release-record-invalid` | The record has no valid release tag, disagrees with the chosen tag, or lacks a usable changelog sentence. |
| `manifest-invalid` | The target manifest is absent or malformed, conflicts with the selected version or target, or does not describe the verified archive contents. |
| `checksum-invalid` | A required checksum is absent, malformed or disagrees with the downloaded bytes. |
| `release-unavailable` | A read failure prevents verification. |

## Verification

The release record is the public GitHub release for the exact `v<latest>` tag
in `openwizdev/OpenWiz`. Use the same published tag the
[install line](../AGENTS.md#install-openwiz) resolves and use that tag for every
read of the release's notes and assets. The manifest's version must match the
tag and its target must match the installed program's target.

Apply the package checks from [verified install v1](install.v1.md) and
[`tools/install/install`](../tools/install/install). The target's `.sha256`
must match the manifest bytes, the strict manifest must validate, and the
archive must match the manifest's size and hash. The manifest and archive must
also match their entries in `SHA256SUMS`. Apply the install contract's exact
archive member checks in read-only mode. A missing or failed check gives an
unverified report. These checks establish integrity of the bytes from the
published release channel.

## Owner confirmation

Installation requires the owner's explicit yes through `openwiz update --yes`.
Consent is for the exact version and verified package identity from the last
check. `--yes` must re-read and reverify the selected release and refuse if
there is no prior verified newer selection, if the version or verified package
changed, or if verification now fails. A fresh lookup during `--yes` cannot
supply the prior selection. Pass only the confirmed version and verified bytes
to the installer. Without `--yes`, the command changes nothing and explains
how to confirm an available update.

The install must keep every installed driver and leave the settings file
byte-for-byte untouched. If it cannot preserve both, it must refuse the update.

## Fixture proof

`python3 -I -B contracts/fixtures/update/test_fixtures.py` checks the five
synthetic report cases and rejects extra fields, invalid values and missing
failure reasons. The command's release verification and installation behavior
are proved by the subsequent CLI tickets.
