# Public CloudRoom setup v1 (`openwiz.cloudroom-setup.v1`)

Setup's CloudRoom step installs CloudRoom for a new user, or reuses the
installation and login they already have. It has one CloudRoom sign-in screen
and a short powered-by line (ticket #2201, spec #2194). Source: Jake,
2026-11-13: OpenWiz bundles CloudRoom's installation, with one CloudRoom sign-in
screen and a short powered-by CloudRoom line ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6847807740)).

This contract is proven on fixtures and recording fakes only. A real download,
installation or sign-in is observed only in #2207's bounded live run; until
then every claim here about real CloudRoom behaviour is Unverified.

It changes neither [setup.v1](setup.v1.md) nor its schema. The step reports
through setup's existing `cloudroom` component and its four states, and adds no
setup write route. The install operation is the tool's own record (below),
not one of setup's `operations`.

## Supported CloudRoom interfaces

Each interface below was read on 2026-11-13 (CloudRoom `gui-v152`, source
`davidondrej/cloudroom` at `850947f5b2c24c5d8aa62843bfb889145c742cb4`).

| Interface | What it gives | Source |
| --- | --- | --- |
| Install guide, `https://www.cloudroom.dev/setup.md` | One GitHub release link per platform: macOS Apple Silicon `.dmg`, Linux x64 `.AppImage`, Windows x64 `.exe`. "Use only the installer links on this page." "Never ask for passwords, tokens, or API keys." CloudRoom creates `~/.local/bin/room-cli` the first time it opens | Listed under "Install" in `https://www.cloudroom.dev/llms.txt` |
| GitHub release, `GET https://api.github.com/repos/davidondrej/cloudroom/releases/tags/<tag>` | Each asset's `digest` (`sha256:<hex>`), `size` and `browser_download_url`; `draft`, `prerelease` | GitHub REST API |
| The release's `SHA256SUMS.txt` asset | `<sha256>  <file>` per installer | The release notes: "SHA-256 checksums are in `SHA256SUMS.txt`" |
| `room-cli cloud status --json` | `CloudroomStatus`: `account` (`{id, email}` or `null`), `signedOut` ("True only when the saved connection confirms no signed-in Cloudroom account"), `signingIn`, `selfHosted` | CloudRoom's room-cli command index (`gui/plugins/cloudroom-guide/skills/room-cli/references/command-index.md`), `gui/apps/cli/src/commands/cloudroom.ts`, `gui/packages/sdk/src/areas/cloudroom.ts` |
| `room-cli cloud sign-in --json` | `{url}`: the browser link to CloudRoom's own sign-in | Same files |
| `room-cli status --json` (cloud thread) | `{"thread": {"id", "projectId", "archived", ...}}`: confirms the host is an active CloudRoom cloud thread (`/usr/local/bin/room-cli`, where the desktop `cloud` subcommand does not exist) | CloudRoom cloud thread CLI (`room-cli --help`, `room-cli status --json`) |
| `https://www.cloudroom.dev/download` | CloudRoom's own download page (it asks the visitor to sign in first) | `https://www.cloudroom.dev/docs/get-started.md` |
| `codesign --verify --deep --strict -R <requirement>` (macOS) | Apple's signature check of the installed app, with a designated requirement: a Developer ID Application certificate whose leaf `subject.OU` is CloudRoom's team `4AJ9HF33Z5`; any other team's valid signature fails | The release notes: "Signed and notarized by Apple"; the team from the Developer ID certificate in release `gui-v153`'s `Cloudroom-v153-arm64.zip`, matching its `SHA256SUMS.txt` |

## Targets

| OpenWiz host | Target | Installer | Destination |
| --- | --- | --- | --- |
| macOS, `arm64` | `macos-arm64` | `Cloudroom-v<N>-arm64.dmg` | `/Applications/Cloudroom.app` |
| Linux, `x86_64` | `linux-x64` | `Cloudroom-v<N>-x86_64.AppImage` | `~/Applications/Cloudroom.AppImage` |
| Anything else, including macOS `x86_64` | none | none | none |

CloudRoom publishes no installer for macOS on Intel or for Linux on ARM.
OpenWiz does not run on Windows. On a host without a target, the tool installs
nothing and says so (`cloudroom_unsupported`). Asked to install, it opens
CloudRoom's download page once instead.

**CloudRoom cloud thread host:** When running on Linux inside a CloudRoom cloud
thread (no desktop `~/.local/bin/room-cli`, `/usr/local/bin/room-cli` exists,
and `/usr/local/bin/room-cli status --json` returns an active `thread` object
with valid `id` and `projectId` and `archived` not true), the host is accepted
as an already-authenticated CloudRoom host on any architecture (`aarch64` or
`x86_64`). `status`, `install` and `sign-in` return `cloudroom_login_verified`
without downloading, installing, running desktop `room-cli cloud` checks,
checking FUSE or display variables, or opening a browser. The returned `id` and
`projectId` values are never printed, saved or shown. If `status --json` fails,
times out, is invalid or archived, detection fails closed and falls back to the
normal target check (`cloudroom_not_installed` or `cloudroom_unsupported`).

## Installer source and integrity check

The tool reads CloudRoom's install guide and accepts exactly one link for the
target, matching
`https://github.com/davidondrej/cloudroom/releases/download/gui-v<N>/Cloudroom-v<N>-<arch>.<kind>`.
The guide's tag and file must name the same `<N>`. Then it reads that tag's
GitHub release. The release must be published (`draft` and `prerelease` both
`false`). The installer and `SHA256SUMS.txt` each appear exactly once, each
with a `sha256:` digest, a positive size of at most 1 GiB, and the download URL
the guide named. The downloaded `SHA256SUMS.txt` must match its own digest and
size. Its one line for the installer must equal the installer's digest.

If any of this fails, no source is accepted (`cloudroom_source_unchecked`). The
tool proposes nothing, downloads nothing and installs nothing. Asked to
install, it opens CloudRoom's download page once instead.

The installer is downloaded into the owner-only record folder. It is installed
only if its size and SHA-256 equal the accepted ones. On a mismatch it is
deleted and nothing is installed (`cloudroom_checksum_mismatch`). Every read is
HTTPS, through no proxy, to `www.cloudroom.dev`, `api.github.com`, `github.com`
or GitHub's release-asset hosts only.

## The install operation

`tools/install/cloudroom/cloudroom.py install` is the only write. It follows
setup's discipline for operations:

1. **Preview** (`install`). Reuse is checked first: an existing installation
   proposes nothing. Otherwise the tool accepts a source, then saves one
   operation before any effect. The operation has an `operation_id` (32
   lowercase hex), `kind` `install_cloudroom`, `phase` `proposed`, a
   `fingerprint` (SHA-256 of the canonical request), the `request` (`target`,
   `tag`, `name`, `url`, `sha256`, `bytes`, `destination`) and its plain
   `effects`. A repeated preview of the same request reuses the id.
2. **Confirm** (`install --yes --operation ID`). The tool installs only that
   saved request, and only if nothing is installed by then. Before downloading
   it saves `phase` `installing` with its process id and start time. Then it
   downloads, checks and places the installer, never over an existing file or
   app. macOS mounts the image read-only and copies `Cloudroom.app` into a
   staging folder beside the destination (always detaching). The staged copy
   must pass `codesign`. Then it is published with a rename that never
   replaces anything (`renamex_np` with `RENAME_EXCL`). An app that appears
   meanwhile, even while mounting or just before publishing, is left exactly
   as it is, and the attempt fails. Linux copies the AppImage, makes it
   executable and hard-links it into place, which also never replaces.
   `applied` requires the installed copy to verify: the AppImage's SHA-256
   equals the request's, or the published app passes `codesign`. Launching
   CloudRoom never counts as applied, and installing launches nothing.
3. **Decline** (`install --no --operation ID`). The proposal becomes
   `refused`, `declined`. Nothing is installed, and that id can no longer be
   confirmed.

| Phase | Means |
| --- | --- |
| `proposed` | Saved, awaiting an explicit yes |
| `installing` | An attempt started. If its process is no longer alive, or 30 minutes have passed, it reads as uncertain |
| `applied` | CloudRoom's checked copy is installed and verified |
| `failed` | The download or the install did not complete, or the copy did not verify |
| `refused` | Declined, a checksum mismatch, or an installation appeared first (`existing`): nothing was installed |
| `uncertain` | No answer came back from the copy step (a lost reply), or the attempt's process was lost |

**A retry reuses the operation.** A preview returns a saved uncertain,
interrupted or failed operation itself, never a reuse answer or a new id. An uncertain, interrupted or failed operation
is reconciled against the actual installation before any further attempt. A
verifying copy makes it `applied`. A missing copy lets the same id try again.
A copy that does not verify is never copied over: an uncertain operation stays
uncertain, and a failure stays failed. A later refusal or failure never lowers
uncertainty. An uncertain operation cannot be declined.

The record is `<state>/cloudroom/install.json` (`openwiz.cloudroom-install.v1`:
exactly `schema` and `operation`). Its folder is owner-only (`0700`) and the
file is `0600`. It is written atomically under an exclusive lock and read with
exact keys, refusing a duplicate key. On first use, the state folder, any missing ancestors and the record's folder
are created one at a time, and the parent holding each new folder is synced.
A folder left behind by a failed sync is not taken as durable. Every attempt
syncs the record's folder again, and the parent holding each folder in the
state chain the user owns, stopping at the first folder someone else owns.
Each save syncs the file, then its folder, before returning. All of this
happens before any effect, and a failed sync stops the step there. `<state>` is setup's state directory.
Reads (`status`, setup's check) write nothing.

## Reuse

These count as an existing installation: `~/.local/bin/room-cli`; on macOS,
`/Applications/Cloudroom.app` or `~/Applications/Cloudroom.app`. On Linux an
AppImage counts only at the checked install location,
`~/Applications/Cloudroom.AppImage`, and only while it is the copy the checked
install produced and verified: the saved operation is `applied`, and the file
there is regular (not a link), executable and has that operation's SHA-256. No
other AppImage counts, anywhere: not another name in `~/Applications`, not a
renamed copy of the installer, not a `~/Downloads` copy, executable or not. It
is never reused or launched, and the checked install may still go to its own
destination. Anything else at `~/Applications/Cloudroom.AppImage`, including a
checked copy that has since changed, blocks the install
(`cloudroom_destination_blocked`). It is never overwritten or made executable,
and sign-in refuses until the user fixes it. A blocked destination takes
precedence over reuse and login, even with `~/.local/bin/room-cli` present:
status, preview and confirmation report it, and nothing runs the launcher. A
pending operation is still reconciled first. The launcher alone counts only
while nothing is at that path. An
existing installation is reused as it is: nothing is downloaded, reinstalled,
replaced or downgraded, and no operation is proposed. A copy left behind by
this tool's own failed or uncertain attempt is not reused: it shows that
attempt's state until it is reconciled.

## Sign-in handoff and login evidence

**Login evidence** comes only from `room-cli cloud status --json`, run from
`~/.local/bin/room-cli`, with no other arguments and nothing on standard input.
Verified needs all of these: an exact `account` object with exactly non-empty
`id` and `email` strings; `signingIn` exactly `false`; and `signedOut` and
`selfHosted` absent or `false`. `account: null` with `signedOut: true` is
missing. Anything else is unknown: a timeout, an error, an unparsable answer,
a duplicate key, still signing in, or contradictory fields. A reachable
inventory or a listed harness is never login evidence. The account values are
never printed, saved or shown.

**Sign-in** (`sign-in`) opens CloudRoom's own sign-in once, then reads the login
back:

- On Linux it first checks, before any `room-cli` call: a desktop session
  (`DISPLAY` or `WAYLAND_DISPLAY` set), and FUSE (`/dev/fuse`, a `fusermount`,
  and `libfuse.so.2` when the checked AppImage's runtime loads it). Whatever is
  missing is refused as its own reason with its next step, and nothing runs or
  opens.
- A current verified login is reused. Nothing opens, so there is no second
  sign-in.
- If CloudRoom has opened before (its launcher exists), the tool runs
  `room-cli cloud sign-in --json` once. It opens the returned link once with
  `/usr/bin/open` (macOS) or `/usr/bin/xdg-open` (Linux), and only if the link
  is `https` on `www.cloudroom.dev` or `cloudroom.dev` (no port, user or
  whitespace). The link is never printed or saved.
- If CloudRoom has never opened here, the tool opens the CloudRoom app once.
  CloudRoom's own first-run setup starts with its sign-in.
- The opener or app is watched for a short start window (3 seconds). If it
  exits with an error within it, `opened` is `null`. At most 64 KiB of its
  output is read in that window. Later output is drained and discarded, and
  never written to a file. The app keeps running.
- When the sign-in gives no usable link, times out or fails to open, the
  tool never prints the program's output. Standard error gets the exit status
  (or the timeout), then a fixed sentence for each known error phrase found
  exactly in the output (FUSE, a missing desktop session or system library,
  the sandbox helper, no browser, and the network errors `ENOTFOUND`,
  `ECONNREFUSED` and `ETIMEDOUT`), then the command the user can run to see
  the full output themselves. That command never holds the sign-in link.

OpenWiz never asks for, receives, stores or logs a CloudRoom password or token.
The tool has no option for one and reads nothing from standard input.

## States, codes and reasons

Setup's check (`tools/install/setup/setup.py check`) stores the tool's one code
as the `cloudroom` observation and maps it to its next step in
`tools/install/setup/setup.py` (the local server that previously mapped it left
in #1264). A code is current for an hour and for the current selection, as for
every component; old evidence is unknown.

| Code | State | Meaning |
| --- | --- | --- |
| `cloudroom_not_installed` | missing | Nothing installed; a target exists |
| `cloudroom_installing` | unknown | An install is running |
| `cloudroom_installed` | unknown | Installed by setup; CloudRoom has not opened yet, so no login was read |
| `cloudroom_reused` | unknown | An existing installation is reused; CloudRoom has not opened yet |
| `cloudroom_install_failed` | unknown | The install failed: never installed |
| `cloudroom_install_uncertain` | unknown | Lost reply or lost process: reconcile first |
| `cloudroom_install_declined` | refused | The user declined: nothing installed |
| `cloudroom_checksum_mismatch` | refused | The installer did not match its published checksum: nothing installed |
| `cloudroom_unsupported` | refused | No checkable installer for this platform: nothing installed |
| `cloudroom_destination_blocked` | refused | Something other than the checked install's verified copy occupies the Linux destination: nothing installed or changed |
| `cloudroom_login_missing` | missing | Installed; CloudRoom reports no signed-in account |
| `cloudroom_login_unknown` | unknown | Installed; no current login evidence |
| `cloudroom_login_verified` | verified | Installed; CloudRoom reports a signed-in account now |

The login codes apply once CloudRoom is installed or reused and its launcher
exists. Install codes take precedence. `cloudroom_source_unchecked` is a tool
answer only: setup's check never stores it, and the step keeps showing not
installed. A runtime without the tool keeps the earlier read
(`cloudroom_reachable`, `cloudroom_missing`, `cloudroom_unreadable`,
`cloudroom_partial`), all of which stay unknown or missing. Unknown, failed and
uncertain are never shown as installed or signed in. Each row's reason and next
step are fixed public text.

## The sign-in screen and the powered-by line

The local setup web page left in #1264; `tools/install/setup/setup.py check`
reports `results.cloudroom` and `next.cloudroom` under `openwiz.setup-check.v1`.
Sign-in still happens once, in CloudRoom's own window (`tools/install/cloudroom/cloudroom.py sign-in`),
and OpenWiz never asks for, sees or stores a CloudRoom password or token. It
reports signed in only for `cloudroom_login_verified`.

**Powered-by line:** when a surface displays the CloudRoom step, its powered-by
line is exactly `Powered by CloudRoom`, plain text, no logo or link, once on the
CloudRoom step only.

## The tool's command line (seam for #1109 and #2207)

`python3 -I <build>/runtime/cloudroom/cloudroom.py status | install [--yes | --no] [--operation ID] | sign-in [--state-dir DIR]`.
It prints one JSON object: `{"schema": "openwiz.cloudroom-setup.v1", "code": <code>, "operation": <operation or null>, "opened": null | "sign_in" | "app" | "download_page"}`.
`sign-in` may also write fixed diagnostic lines to standard error: the exit
status, `openwiz-cloudroom: <program> reported: <fixed sentence>` for each known
error, and `openwiz-cloudroom: to see its full output, run: <command>`. Standard output stays exactly that four-key
object. A refusal exits 5 with `openwiz-cloudroom: refused: <reason>` on standard
error and nothing on standard output. A missing desktop session or missing FUSE
on Linux is such a refusal, and its reason ends with `Next:` and the step. The packaged runtime ships the tool as `runtime/cloudroom/cloudroom.py`
(mode `0600`), and the installer requires it. #1109 wires these commands into
the install line and skill. #2207 runs them for real.

## The two `room-cli` calls (allowlist pin)

Jake approved exactly two `room-cli` calls for this tool (J30, 2026-11-13,
recorded on #2201). They are pinned here and in
`crates/adapters/cloudroom/src/allowlist.rs` as `SETUP_LAUNCHER` and
`SETUP_CALLS`:

| Call | Run from | Purpose |
| --- | --- | --- |
| `room-cli cloud status --json` | `~/.local/bin/room-cli` | The login read |
| `room-cli cloud sign-in --json` | `~/.local/bin/room-cli` | CloudRoom's own sign-in link |

The tool's one builder, `room_cli`, refuses every other argument list before
running anything, and `PATH` is never searched. Its tests bind the tool's calls
to the allowlist entries and show that every install, reuse, login and sign-in
path runs only these two. Nothing else in the allowlist changes. The Rust
adapter never runs these calls.
