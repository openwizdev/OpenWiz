# Verified install v1

`openwiz.install.v1` describes exactly one version/source/target bundle. Supported
targets are `aarch64-apple-darwin`, `x86_64-apple-darwin` and
`x86_64-unknown-linux-gnu`. A target describes the built programs, not the host
running an offline verifier. Native execution on each host needs live evidence.
The manifest's setup API must be 1. Unknown/duplicate fields, assets and archive
members fail closed. Version is one `0.<minor>.<patch>` pre-release; source is a
full lowercase Git commit. Programs, web and skill runtime share this identity
and the same build job. Review binds the exact complete asset list and hashes.

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
accepted. Only the three named programs and files under web/ and runtime/ are
allowed. Every asset is hash-checked before activation, including repeated
installs. The manifest lists every file (not directory globs). Runtime includes
setup, grill, plan-graph and launch-fleet skills and their script resources.

The root and state directory must be absolute, owned, private directories with
no symlink ancestors. New directories use 0700; data 0600; programs and shell
runtime scripts 0700. Existing settings and credentials are never replaced.
An existing update channel is never silently migrated. A packaged install
explicitly records `openwiz.update-channel.v1`, channel `packaged`, in
`<root>/channel.json`; absent metadata keeps existing source installs unchanged.

A nonblocking owner-only install lock serializes installation. Immutable builds
live under `<state>/service/builds/<source>/`, with programs beside web/ and
runtime/, plus their exact install-manifest.json. Default private state for an
explicit root is `<root>/state`; agents installing the standard service must
explicitly pass its established platform state directory. Standard installation
root is `$HOME/.local/lib/openwiz`; its parent must already exist.
An owned `current` link selects an absolute build path in that state directory.
A foreign selection is refused. Staging, fsync, atomic rename, then atomic link
replacement preserve last-good selection on pre-activation failure. An interrupted
staging directory is inert. Repetition verifies/reuses an identical complete
build; a different manifest for the same source is refused. Previous builds and
all owner work remain. `--stage-only` verifies/stages without selecting a build
or changing channel metadata; the service's durable handover owns activation.

Install result JSON names version, source, target, private build/state paths,
activation state and the loopback setup URL. These local paths are not remote
records. Opening setup starts only the installed server on loopback with that
build's web export. Setup does not imply service, CloudRoom, App, harness,
project, engine or remote readiness. No inventory read, account operation,
engine activation, publication or fleet start is part of installation.

Removal must stop only this installation's runtime, and preserve owner work by
default. Local removal is not remote credential revocation. Guided removal and
native platform management belong to the later setup/runtime tickets.

`--serve` keeps the installed standalone server in the foreground on loopback;
`--open` also opens its setup URL in the system browser. `--port` defaults to
7370. The launcher verifies the served setup bytes match the selected build
before opening the browser. A failed bind or missing setup is a failure, never
proof another process's page belongs to this install. Stopping the launcher
stops only its own server child. Neither flag is allowed with `--stage-only`.
Launching this unconfigured setup does not start the service scheduler or engine.

Both `web/openwiz-build.txt` and `runtime/openwiz-build.txt` are required assets.
Their exact UTF-8 bytes are `openwiz.package.v1\n<VERSION>\n<SOURCE>\n<TARGET>\n`;
their sizes and hashes must match these manifest fields before extraction. This
prevents reusing an already-reviewed web/runtime payload under another identity.
The native artifact job applies the reviewed release version to the workspace
package version for all three programs, preserving protocol versions, and checks
the service's compiled source plus each program's native executable architecture.

For the future public-source release path, the [release candidate contract](release-candidate.v1.md#minimum-product-identity-rl4) adds a producer-side compiled-product identity interface: CLI, server and service embed and expose their version/source/target without effects; web identity is generated during export and runtime bytes are checked against the tracked source selection. Cross-target collectors verify the embedded identity and architecture against hash-bound native build receipts without executing incompatible programs. A packaging stamp or requested version alone is insufficient. This does not change `openwiz.install.v1`, its assets/stamps, offline integrity checks, update channel or activation rules; implementation and live verification remain separate work.
