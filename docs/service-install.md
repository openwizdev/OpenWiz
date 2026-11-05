# Private local runtime

The packaged runtime uses the existing `openwiz-service`, its private state,
embedded loopback server, status socket and durable update recovery. It adds no
engine or scheduler. Connections and engine activation remain separate setup
steps requiring their own checks and authority.

| Host | Supervisor | Native evidence |
| --- | --- | --- |
| macOS Apple silicon | User launchd agent | Unverified until T8 |
| macOS Intel | User launchd agent | Unverified until T8 |
| Linux x86_64 | User systemd service | Unverified until T8 |

These selections, refusals and command forms are tested on synthetic bundles
with recording tools. Artifact download, cross-compilation and Linux fixtures do
not establish native readiness. No supervisor is invoked by installation alone.

After verified installation and authorized setup of `service/config.json`, use
the selected build's runtime manager. Pass the same absolute private state path
used by installation; the established defaults are
`$HOME/Library/Application Support/openwiz` on macOS and
`${XDG_STATE_HOME:-$HOME/.local/state}/openwiz` on Linux.

```sh
python3 "$install_root/current/runtime/platform/runtime.py" start \
  --root "$install_root" --state-root "$state_root"
python3 "$install_root/current/runtime/platform/runtime.py" status \
  --root "$install_root" --state-root "$state_root"
python3 "$install_root/current/runtime/platform/runtime.py" restart \
  --root "$install_root" --state-root "$state_root"
```

Python 3.9+ is already an installation prerequisite. macOS App signing uses that
interpreter; Linux retains its existing native descriptor signer. Both use
`/usr/bin/openssl`; token exchange retains the fixed `/usr/bin/curl` transport.
macOS uses only absolute `/usr/bin/python3 -I` with a cleared environment and no
PATH, fallback or production override. The reviewed helper is compiled into the
adapter. A missing fixed interpreter refuses signing; it does not establish readiness. Both key walks use no-follow,
descriptor-relative opens and validate each private directory and the single-link
key descriptor. macOS passes the pinned descriptor to OpenSSL; Linux opens the
pinned parent descriptor through `/proc`. Neither reopens the original key path
for signing, nor puts key material in arguments. The macOS helper replaces
itself with OpenSSL; Linux invokes the signer directly, so the deadline controls
the actual signer on both paths. App keys stay on the selected engine host.
This does not authorize a live App connection or provisioning.

The manager checks the selected build's complete manifest and installed hashes,
host target, source, private ownership, ancestor symlinks, repository exclusion
and single-link config before calling a supervisor. Unit names bind the exact
installation and state paths. Definitions live under private
`service/platform/`; a nonblocking installation-specific management lock
serializes start and restart. Repeating start reconciles the existing unit.
Interrupted definition writes leave only inert temporary files. A conflicting
existing definition is refused, never overwritten. Linux retains the existing
user systemd supervision pattern; packaged units have installation-specific
names and never replace the development deployment's `openwiz.service`.
macOS requires the owner's GUI login domain; Linux requires the owner's user
systemd session. An unavailable supervisor is a failure, not readiness.

The manager's status lookup creates no persistent state and starts no runtime.
On macOS, Rust private-state inspection briefly creates an empty, exclusively
opened 0600 file in the selected 0700 state directory, reads its descriptor
owner uid and removes that exact file (Jake's #1102 ruling). Ancestor symlinks,
repositories, public or foreign state and probe failures are refused. Linux
keeps its `/proc/self` owner query. P8(a) still permits only `/bin/df` in the
store; no identity subprocess is used. `awake` requires the
selected service to answer its own private IPC query with its matching build;
a saved state file or an active supervisor is insufficient. `orchestrating`
is true only when that reply reports a running tick. Missing IPC is
`offline_or_unknown`: a local status tool cannot distinguish a sleeping host
from an unreachable service. An observed supervisor failure is `failed`.
Sleeping stops new Local orchestration; already running Cloud agents may
continue. Runtime availability does not establish an activated engine.

Restart targets only this installation's named job. A failed launch or refused
private path preserves installed builds, config, keys and owner work. This tool
does not remove data, revoke remote credentials, change the update channel,
open a tunnel, activate an engine or start agents.

## Internal package transport

The packaged updater uses the selected build's `runtime/pull.py` (packaged
from `tools/install/pull.py`) for published artifacts. This is an internal
transport seam, not a manual upgrade or runtime activation procedure. Its
existing positional forms are shown here with synthetic placeholders only:

```text
python3 <selected-build>/runtime/pull.py discover <target>
python3 <selected-build>/runtime/pull.py stage <target> <version> <source> <checksum> <root> <state_root>
```

`target` is `aarch64-apple-darwin`, `x86_64-apple-darwin` or
`x86_64-unknown-linux-gnu`. `discover` reads the fixed OpenWiz GitHub release
endpoint's latest target manifest and checksum, validates them and emits JSON:
`schema: openwiz.package-candidate.v1`, `version`, `source`, `target` and
`manifest_sha256`. Discovery neither stages nor selects a build.

`stage` takes that candidate's version, source commit and manifest SHA-256
(`checksum`), plus the absolute installation `root` and private `state_root`.
It requires an existing packaged current selection and a version newer than
that selection. It downloads the versioned manifest and archive from the fixed
release endpoint, checks the candidate identity, verifies compressed integrity
before archive parsing and verifies every installed asset. The verified build
is staged under `<state_root>/service/builds/<source>`; `current` keeps its
existing selection. Its JSON has schema `openwiz.install-result.v1`, with `version`,
`source`, `target`, `build`, `state_root`, `setup_url` and `activated: false`.
Here `activated` refers to installation selection, not engine readiness;
the returned setup URL does not mean a server was started.

Unsupported targets, non-advancing versions, changed identities, invalid
checksums/artifacts and unsafe private paths are refused. Handled transport or
verification failures exit 1 and print this stderr message:
`package pull: refused; last-good build retained`.
Staging starts no runtime or supervisor; runtime and engine
activation remain separately authorized. These semantics have synthetic
fixture evidence only; native readiness and live transport remain unverified.
