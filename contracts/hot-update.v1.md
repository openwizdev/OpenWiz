# OpenWiz hot-update v1

`openwiz.hot-update.v1` defines how the kernel, skills, drivers and market items
are selected, checked and rolled back. Each JSON object has
`schema: "openwiz.hot-update.v1"` and a `record` that selects its shape in
the [schema](hot-update.v1.schema.json). The [synthetic fixture pairs](fixtures/hot-update/README.md)
exercise those shapes. Readers accept strict UTF-8 JSON and refuse duplicate
keys, unknown fields and malformed records. Consumers check file ownership,
actual bytes, timing and agreement between records at their respective seams.

## Component manifest

A `component-manifest` binds `kind` (`kernel`, `skills`, `driver` or
`market-item`), a stable `id`, a `version` and the `sha256` of the exact
component payload bytes as distributed, before unpacking. For `skills`, one
component is one skill. IDs are lowercase ASCII letters and digits with optional
single hyphens between groups. Versions are stable `MAJOR.MINOR.PATCH` strings
without leading zeroes or a tag prefix. SHA-256 is 64 lowercase hex digits.
A version of a given `(kind, id)` identifies immutable bytes for the selected
platform. Refuse a changed digest for the same identity, version and platform.
Get the manifest through the verified release check for the selected platform
and apply any package-specific checks, including the kernel install checks.
The digest establishes the integrity of the bytes.

## Installed set

Keep `installed-set.json` under the private installer state directory.
It holds one `installed-set` record with `access: "owner-only"` and a
`components` array keyed by unique `(kind, id)` pairs. The owner must own
the directory and record, with mode `0700` and `0600`, respectively.
Refuse foreign or linked state; check ownership and modes on disk. The record
and its private paths stay on the owner's machine.

Each row's `current` is the selected version, and `last_good` is the checked
fallback. On initial import from a verified installed build, both can name
the same version. Before a forward swap, preserve the currently healthy version
in `last_good`. A passing candidate becomes the healthy `current` and retains
that previous version as `last_good`. A rollback sets `current` to the restored
version and leaves a verified, unpulled version in `last_good`. Keep up to five
completed outcomes per component in `history`, newest
first, with the candidate or pulled `version` and `result` (`good`,
`health-failed` including timeouts, or `pulled`).

## Swap and rollback window

The kernel swaps the installer's existing `<ROOT>/current` link from the [install contract](install.v1.md).
Create a temporary link to the staged build and rename it over `current`.
For other kinds, switch the component's active selection with one rename on
the same filesystem; each managed harness copy of a skill uses one rename.
Retain the old version. Skip and report locally modified components and
preserve the owner's files, settings and driver configuration.

Serialize selection and installed-set writes with the installer lock. Recheck
the selected version and fallback under the lock. Write the installed set by
atomic replacement. If interrupted between selector and record writes, check
the selector against the verified builds and the saved fallback before allowing
another update or reporting success. Treat an unconfirmed candidate as needing
health verification or restoration.

The completed `swap` record identifies the candidate by `kind`, `id` and
`version` and records its `steps` in this order.

1. `stage-beside` creates a separate version beside the old one.
2. `verify-sha256` checks the payload against the verified manifest. A mismatch
   stops here and preserves the old selection.
3. `switch-atomically` selects the verified build with one atomic replacement.
4. `health-check` runs the probe on that exact build and records `health_result`.
5. `mark-good` records a pass, or `roll-back` restores the fallback on failure
   or timeout using the same atomic selection operation.

`rollback_window_minutes` is **5**. Measure from the selection switch for a
health-triggered rollback and from authorization for a pulled-release return.
Bound the health probe so restoration can finish inside the same five minutes.
On failed restoration, stop, report the observed selection and preserve the
fallback and running launches.

## Health checks

A `health-check` identifies the exact `kind`, `id` and `version` exercised.
Its `probe` and passing condition depend on the kind.

| Kind | Probe | Passing condition |
| --- | --- | --- |
| `kernel` | `self-check` | Run the selected build's `openwiz --build-identity`. It exits zero and its reported version, source and target match the verified install bundle. |
| `skills` | `lock-verify` | Verify the selected skill in every managed copy against the expected contents from the release's pinned skill tree. Every managed copy matches. |
| `driver` | `driver-check` | Run the selected driver's `check` command. It exits zero after validating its package and schema and confirming it can load without launching a driver session. |
| `market-item` | `listing-check` | Validate the selected item's listing and its declared artifacts against the verified package. The listing parses, its ID and version match, and all declared artifacts are present and verified. |

Record `result: "passed"` only if the whole check passes. Record `failed` on
an error, nonzero exit or mismatch, and `timeout` when the time limit expires.
These probes use the selected immutable build and make no changes to user data.

## Rollback triggers and pulled releases

A `rollback` identifies the component and its two component versions (`from`
and `to`). `trigger: "health-failed"` covers failure and timeout. It
automatically reverses the just-attempted swap to that component's
`last_good`, including when the original swap required confirmation.

The verified channel release record, `hot-update.json`, has
`record: "release-record"` and top-level `latest` and `pulled` fields.
`latest` is the selected release version. Each `pulled` entry gives the
unique pulled release `version`, its last good successor release
`last_good`, and the `reason` (`live-check-failed` or
`regression-threshold`). An empty list is explicit. When changing latest
after a pull, the producer makes the list available through the same verified
update check, independent of any single version's immutable artifacts.

A match with the release selected for future launches gives
`trigger: "pulled"`. Check the verified successor release and use its
component manifests to resolve each rollback's `to` version. Refuse a
successor that is unknown, equal to the pulled release or itself pulled.
Apply the owner's update policy to the pulled-release return. If that return
fails its health check, report a failed restoration. Only an unpulled,
verified build can be selected for recovery.

## Running fleets

At launch start, resolve every needed component to one immutable version under
the same selection lock, then hold those versions for the launch's lifetime.
A `launch-pins` record has `resolution: "at-start"` and lists the unique
`(kind, id, version)` selections under `components`. The launch uses the
resolved build paths for subsequent work, including lazily loaded skills,
drivers and market items. A swap or rollback changes selection for future
launches. Keep versions used by existing launches available until they finish.

## Update setting

The default is `ask`. Only the owner may choose `auto-patches` in the
`updates` setting. A missing setting is equivalent to `ask`. Each
`update-decision` records the optional `updates`, a verified `change` and
the resulting `confirmation` (`required` or `automatic`).

Determine `change` by comparing the selected and verified offered release
versions numerically. A higher patch in the same major and minor is a
`patch`; a higher minor in the same major is a `minor`; a higher major is a
`major`. A verified match in the pulled list takes the `pulled-rollback`
path. With `ask`, every new installation or pulled-release return waits for
the owner's yes. With `auto-patches`, verified patches and pulled-release
returns can proceed automatically. A minor version always asks and installs
with a restart. A major version also requires confirmation.
