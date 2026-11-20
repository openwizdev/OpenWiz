# Verified install v1

`openwiz.install.v1` describes exactly one version/source/target bundle. Supported
targets are `aarch64-apple-darwin`, `x86_64-apple-darwin` and
`x86_64-unknown-linux-gnu`. A target describes the built programs, not the host
running an offline verifier. Native execution on each host needs live evidence.
The manifest's setup API must be 1. Unknown/duplicate fields, assets and archive
members fail closed. Version is one `0.<minor>.<patch>` pre-release; source is a
full lowercase Git commit. The program and the skill runtime share this
identity and the same build job. Review binds the exact complete asset list and hashes.

The consumer needs Python 3.9+, a supported OS/architecture and disk space;
no Rust, Cargo, Node or npm. `tools/install/install.py` accepts explicit
`--manifest FILE --manifest-sha256 SHA256 --archive FILE --target TARGET
--root PRIVATE_INSTALL [--state-root PRIVATE_STATE]`. The manifest checksum
comes from the release's checked SHA256SUMS, through the same reviewed download
channel. A checksum establishes integrity, **not a signed publisher identity**.
There is no trust-on-first-use publisher signature or implicit publication.
The installer is offline; transport must retrieve the published exact assets.

Compressed archive SHA-256 and byte length are checked before archive parsing.
Every member is a unique regular file, with an exact manifest path, size, mode
and content hash. No extraction API, symlink, hard link, device, directory entry,
PAX extension, absolute path, empty/dot/dot-dot segment or unlisted file is
accepted. Only the named program `openwiz` and files under runtime/ are
allowed. Only to verify the build already selected (status, skills and the
update's version check), a complete pre-AP11 layout, with the `openwiz-service`
and `openwiz-server` programs, web/ and its stamp, is also read.
Every asset is hash-checked before activation, including repeated
installs. The manifest lists every file (not directory globs). Runtime includes
setup, grill, plan-graph and launch-fleet skills and their script resources.

The root and state directory must be absolute, owned, private directories with
no symlink ancestors. New directories use 0700; data 0600; programs and shell
runtime scripts 0700. Existing settings and credentials are never replaced.
An existing update channel is never silently migrated. A packaged install
explicitly records `openwiz.update-channel.v1`, channel `packaged`, in
`<root>/channel.json`; absent metadata keeps existing source installs unchanged.

A nonblocking owner-only install lock serializes installation. Immutable builds
live under `<state>/service/builds/<source>/`, with the program beside
runtime/, plus their exact install-manifest.json. Default private state for an
explicit root is `<root>/state`; agents must explicitly pass the established
platform state directory. Standard installation
root is `$HOME/.local/lib/openwiz`; its parent must already exist.
An owned `current` link selects an absolute build path in that state directory.
A foreign selection is refused. Staging, fsync, atomic rename, then atomic link
replacement preserve last-good selection on pre-activation failure. An interrupted
staging directory is inert. Repetition verifies/reuses an identical complete
build; a different manifest for the same source is refused. Previous builds and
all owner work remain. `--stage-only` verifies/stages without selecting a build
or changing channel metadata.

Install result JSON names version, source, target, private build/state paths
and activation state. These local paths are not remote records. Installation
does not imply CloudRoom, App, harness, project, engine or remote readiness. No inventory read, account operation,
engine activation, publication or fleet start is part of installation.

Removal must stop only this installation's runtime, and preserve owner work by
default. Local removal is not remote credential revocation. Guided removal and
native platform management belong to the later setup/runtime tickets.

`runtime/openwiz-build.txt` is a required asset. Its exact UTF-8 bytes are
`openwiz.package.v1\n<VERSION>\n<SOURCE>\n<TARGET>\n`; its size and hash must
match these manifest fields before extraction. This prevents reusing an
already-reviewed runtime payload under another identity.
The native artifact job applies the reviewed release version to the workspace
package version for the program, preserving protocol versions, and checks the
program's compiled source and its native executable architecture.

For the future public-source release path, the [release candidate contract](release-candidate.v1.md#minimum-product-identity-rl4) adds a producer-side compiled-product identity interface: the CLI embeds and exposes its version/source/target without effects, and runtime bytes are checked against the tracked source selection. Cross-target collectors verify the embedded identity and architecture against hash-bound native build receipts without executing incompatible programs. A packaging stamp or requested version alone is insufficient. This does not change `openwiz.install.v1`, its assets/stamps, offline integrity checks, update channel or activation rules; implementation and live verification remain separate work.

## Harness skills (#1361)

`tools/install/install skills --root ROOT [--state-root STATE]` puts the
selected build's skills where the user's agent finds them. It reads only the
build `status` verifies: every file under its `runtime/skills/`, with its
installed mode. It copies each skill folder into one canonical folder,
`<ROOT>/skills/`, and then into each harness below that is present. A harness is
present when its folder is a real directory this user owns. An absent harness
is reported `absent` with what to do next, and nothing is created for it.

| Harness | Present when this is a directory | Skills copy |
| --- | --- | --- |
| `claude-code` | `~/.claude` | `~/.claude/skills/<skill>/` |
| `codex` | `~/.codex` (or `$CODEX_HOME` when set) | `~/.codex/skills/<skill>/` |
| `cursor` | `~/.cursor` | `~/.cursor/skills/<skill>/` |
| `opencode` | `~/.config/opencode` | `~/.config/opencode/skills/<skill>/` |
| `grok` | `~/.grok` | `~/.grok/skills/<skill>/` |

Each copy is marked with an `.openwiz-skill` file and is replaced only when
that mark is there. A same-named skill without it is the user's own and is
never touched. Before any write, the step checks every destination. A link, a
folder that isn't the user's, or an unmarked same-named skill refuses the
whole step (exit 5) and changes nothing. A repeated run gives the same files.
Other skills in those folders, and skills a newer build no longer ships, stay.
The result is one `openwiz.skills-install.v1` JSON object: version, source,
canonical folder, skill names and one row per harness (`installed`, `absent`
or `refused`, its folder and a plain `next`).

The step needs no Rust, Cargo, Node or npm. It doesn't put anything on `PATH`.
The installed command is the build's own `openwiz`, beside its `runtime/`,
reached through `<ROOT>/current/openwiz`. Its `init` uses the packaged setup
runtime and the user's `gh` login to set up the repository's `openwiz` label
and brain records ([cli.v1](cli.v1.md)).
