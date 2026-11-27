# OpenWiz driver package v1

`openwiz.driver-package.v1` fixes the release and install seam for drivers
outside the kernel (#2993, spec #3027). It does not change
[driver v1](../kernel/driver.v1.md), [verified install v1](install.v1.md),
or WizMarket listing v1. The examples and archives in
[fixtures/driver-package](fixtures/driver-package/) are synthetic.

## Repository and release

Keep the executable `driver` at the repository root, alongside
`schema.json` and `README.md`. Keep tests and their synthetic inputs in
the repository (the template uses `test_driver.py` and `fixtures/`). The
root `kit-commit` file contains the full lowercase 40-hex OpenWiz commit
and one terminating LF. Use that kit for CI and live runs: copy the
repository's driver files into `drivers/<name>/` of a checkout of that
commit and run that checkout's kit, so that the driver finds the
[kit files](#kit-files) as it does when installed. The repository's
`schema.json` is byte-identical to that commit's
`kernel/driver-kit/schema.json`. CI and the release producer check it
against those exact bytes, not a reserialized JSON object. The kit commit says
which kit the author tested with. It never selects or fetches a kit: an
installed driver always uses the installed build's, and the two commits
may differ.

The README has one plain `Login: <where the login lives>` line and the
`Effort:` line required by driver v1. It also declares
`Driver: <name>` and `Abilities: <comma-separated can entries>` on single
lines. The producer checks the name and abilities against the driver's
`version` answer in its own fixture run. The installer can then read these
declarations as data from the checked archive rather than running a driver
just to describe it.

Tag the exact release commit `v<major>.<minor>.<patch>`. Components are
decimal, with no leading zero except zero itself; JSON versions omit the
`v`. A GitHub release at that tag has these assets:

| Asset | Contents |
| --- | --- |
| `driver.tar.gz` | Gzip-compressed USTAR containing only the regular root files `driver`, `schema.json`, `README.md`. No wrapper folder. |
| `manifest.json` | `driver`, `version`, `driver_contract` (exactly `openwiz:driver v1`), `kit_commit`, and `files` (one record per payload file, each with `path`, octal-string `mode`, and lowercase hex `sha256` of uncompressed file bytes). |
| `SHA256SUMS` | Lowercase SHA-256, two ASCII spaces, asset basename and LF, one line each for `driver.tar.gz` then `manifest.json`. |
| `receipt.txt` | Added only after the real host passes the kit on the exact released commit. |

Do not ship tests, fixtures, credentials, the kit checkout or repository
metadata. Archive modes are exactly `0700` for `driver` and `0600` for
the two data files. The checksums file helps check release assets; it is
not a publisher signature or a substitute for the pinned archive hash.

The receipt is the [WizMarket listing v1 receipt][listing-v1], byte for byte
(including 14 LF-terminated lines, the redacted `<note>` fields and
`Result: 5 of 5 pass`). Its `# driver:` value is
`<package.repository>@<package.commit>`, and its `# kit:` value is
`openwizdev/OpenWiz@<package.kit_commit>`. The verified listing points
to the reviewed copy in WizMarket. A fixture run is not a live receipt.

## Records

The [schema](driver-package.v1.schema.json) defines five closed JSON
records under `$defs`: `manifest`, `package`, `key_host`, `pin` and
`approval`. A consumer uses the named definition for its seam. Reject
duplicate keys on decoding, unknown fields, unknown contract versions and
missing required data. The schema checks shapes; equality across records,
URL binding, byte checks, uniqueness by name and receipt validity are
consumer checks.

A WizMarket v2 driver or harness listing has a `package` block:
`driver` is the driver's v1 name (not necessarily the WizMarket listing
id), `repository` is its GitHub `owner/repo`, `version` is its unprefixed
release version, `commit` is the full lowercase Git commit,
`asset_url` is the exact archive URL, `sha256` is the archive digest,
and `kit_commit` is the full kit commit. The asset URL must be exactly
`https://github.com/<repository>/releases/download/v<version>/driver.tar.gz`
using the block's own repository and version, with no query or fragment.
The release tag must resolve to `commit` (peel an annotated tag); do
not resolve a branch or a latest-release URL instead. A listing's
`publisher`, `status` and `proof` come from the same listing snapshot.
A verified listing needs a reviewed receipt bound to that exact repository,
commit and kit commit; a stale receipt cannot confer verified status.

An optional `key_host` has `origin` (a bare HTTPS origin with a DNS
hostname and no userinfo, port, trailing slash, path, query or fragment),
`variable` (the environment variable name), and `keychain` (the keychain
entry name). These are names and an address, never a key value. Check
shape now; the block stays inactive until the owner's key-host rule lands
in the key helper (#3005). It does not authorize a credential read, change
the kernel's registry or make a network request in v1. When that rule
lands it must bind these names and origin to the user's yes and refuse a
variable or keychain entry already used by another host.

## Find, check, ask, install

1. Resolve the host name in order: the installed build's core driver;
   that build's first-party pin; then the matching v2 WizMarket listing
   at one recorded WizMarket `main` commit. Use that commit for all
   listing and receipt reads; never mix snapshots or silently fall
   through after a higher-priority match fails its checks. A missing or
   ambiguous listing does not install.
2. For a fetch, check the release binding, then retrieve only the pinned
   archive and its metadata from the exact release over HTTPS. Obtain
   the two metadata URLs by replacing the final asset basename with
   `manifest.json` or `SHA256SUMS`. Follow only the GitHub release
   download path and GitHub-operated release asset endpoints; refuse an
   off-GitHub redirect, a downgrade or credentials in a URL at every hop.
   Check the compressed archive SHA-256 against the pin or listing
   **before** parsing it. Check the sidecar hashes and compare manifest
   driver, version and kit commit to the pin or listing. Sidecar claims
   alone confer no trust: the payload is bound by the independently
   pinned archive checksum.
3. Apply the strict [install archive rules](install.v1.md): accept only
   unique regular USTAR members, one per exact manifest path, with exact
   modes and byte hashes. Refuse links (hard or symbolic), directories,
   devices, sparse entries, extensions (including PAX and GNU long
   names), malformed archives, unsafe paths (absolute paths, backslashes,
   or empty, dot or dot-dot segments), extra or missing files. Do not
   use a tar extraction API. Check file bytes against the manifest and
   check `schema.json` byte for byte against the kit schema of the build
   the driver is installed into, whatever its `kit_commit`: the build that
   carries the pin, or the selected build for a listing. Never use a schema
   reported by the downloaded program, and fetch none. On a difference,
   refuse; the next step is `openwiz update`, or a driver release made
   with this build's kit. Read the README only as plain untrusted text;
   its driver name must match the selected name and the manifest. Refuse
   mismatches.
4. The user's pick is the yes for core and first-party pins. For a
   verified listing, display one confirmation: name, publisher, version,
   login line, abilities and receipt date. For a listed driver, show
   that it has not passed the kit, and require its own explicit yes
   after the warning. A default, an absent answer or an agent's answer
   is never the user's yes. None of the fetched code runs before the
   checks and the yes. After yes, in private staging laid out with its kit
   files as the install is, require the driver's v1 `version` answer to
   agree with its declared name and abilities before installing it. Do not
   install or save an approval on refusal.
5. Install the verified driver and data only after success. Save one
   approval per fetched driver with exactly its `repository`,
   `publisher`, `version` and archive `sha256`. A refusal says what
   went wrong and what to do next, using the driver v1 error shape.

## Kit files

Drivers load kit files by a path relative to their own folder
(`../../kernel/driver-kit/kit.py` and the like). The kit is not in a
package, so the install gives every driver these files, each copied from
`runtime/<path>` of the selected build to `<install-root>/<path>` and
checked against that build's manifest:

| File | What a driver may do with it |
| --- | --- |
| `kernel/driver-kit/kit.py` | Load it and call `holds_credential(text)`, the credential check |
| `kernel/driver-kit/schema.json` | Nothing: the installer checks a package's `schema.json` against it |
| `kernel/records-kit/check.py` | Nothing: `kit.py` loads it |
| `kernel/driver-kit/hostkey.py` | Run it as driver v1's N4 key helper, for a host in its registry |
| `kernel/driver-kit/hosts.json` | Nothing: `hostkey.py` reads it as the kernel's registry |
| `wizskills.lock` | Read the WizSkills release OpenWiz pins |
| `openwiz-build.txt` | Read the build's version, source and target |

A packaged driver may rely on these uses, on the files of its own folder,
and on no other OpenWiz file. Every build under this contract keeps them,
so a driver keeps working on a later build. Directories are `0700` and files `0600`,
owned by the user and never links. Do not use a driver's own copy in their
place, and take none from `kit_commit` or the network. A build without one
of these files cannot fill the folder: refuse and keep the last good build.

## Drivers folder and updates

The install owns one `<install-root>/drivers` folder, selected via
`OPENWIZ_ADAPTERS`. A driver is at `<name>/driver` with its data beside
it. The folder and its directories are owner-only (`0700`); programs
are `0700`, data and approvals `0600`. Do not follow symlink ancestors
or write into foreign-owned directories. Core drivers are copied from
the verified build and checked against its manifest. Rebuild only from
verified build files and fetched packages that match saved approvals or
first-party pins; do not treat existing loose files as a source of trust.
Stage before replacing the selected contents. The drivers folder and the
[kit files](#kit-files) are rebuilt together, from the build being
selected: a driver never runs beside another build's kit files, and a
failure keeps the last good build with its own drivers and kit files.
Rebuilding an approved, unchanged package repeats every check except the
`schema.json` comparison, which it passed when it was added or last moved:
a later kit schema only adds to driver v1, so it must not remove a working
driver. Keep existing settings, Roster and host names.

On update an approved listing driver can move to a newer version without
another yes only when the repository and publisher are unchanged and the
candidate is verified; give a one-line notice. Check everything again and
replace the saved approval only on success. A changed repository,
publisher, lost verified status, or changed bytes under the same version
must not inherit approval: ask again under the candidate's yes rule.
No change needs no prompt. If a host in use was bundled and the next
build stops bundling it, fetch and check it from the next build's
first-party pin before selecting that build. If the pin is absent or
the fetch, check or staging fails, keep the last good build and its
driver selected and report the next step.

## First-party pins

A kernel release carries `pins.json`, a `pin` record with
`contract: "openwiz.driver-package.v1"` and a `pins` array (possibly
empty). Each entry contains `package`, `publisher`, and `evidence`.
Driver names must be unique. These are reviewed, kernel-owned pins, not
automatically promoted listings. The release gate checks the pinned
hashes against the exact assets, and each package's `schema.json` against
the release's own kit schema. Admit a pin only with one of:

- `evidence.receipt`: a reviewed verified WizMarket receipt URL at a
  full WizMarket commit, for the exact package repository, commit and
  kit commit. Verify that the listing at that commit is verified and
  names this receipt and package.
- `evidence.bundled_version`: the preceding kernel release's unprefixed
  version. Its verified build must have bundled that driver. Compare the
  driver and its runtime data byte for byte against the verified previous
  bundle; a repack may add release metadata, but must not change the
  driver's runtime bytes. This is a carry-over, not a claim of a live pass.

[listing-v1]: https://github.com/openwizdev/WizMarket/blob/main/contracts/listing.v1.md
