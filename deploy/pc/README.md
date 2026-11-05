# PC service setup (T11)

This is the one-time setup Jake runs on the Linux PC during T11, after approving
that live step. The builder has not installed or activated anything on the PC.
The unit, scheduler, HTTP API and status are fixture-proven; an actual kill and
reboot remain T11's live checks.

The service runs as the owner's user, embeds the existing `openwiz-server`
library, and listens on 127.0.0.1 only. It serves the running build's `web/` and
uses the existing HTTP routes, Host checks and write guards. The service itself
registers the pull-only updater (T6); the fleet tick is T4b and health checks
and loops arrive in their own tickets. Other registered jobs are retained.
The synthetic job exists only in the test example.

## Build the approved commit

In the approved checkout, with the tool versions and checks in AGENTS.md:

```sh
CIRCLE_NODE_TOTAL=2 npm --prefix apps/web ci --ignore-scripts
CIRCLE_NODE_TOTAL=2 npm --prefix apps/web run build
cargo build --release -p openwiz-service
```

Build identity comes from this checkout's Git HEAD, including worktree and
packed-ref layouts, without starting Git from the build script. If building an
export without Git metadata, set `OPENWIZ_SERVICE_BUILD` to the actual full
lowercase commit **at build time**. Without a known commit the program can print
help and query status, but refuses to start a service. This value is not a
runtime override.

## Stage a fresh installation

Run as the owner, outside the checkout for state. These commands use the unit's
fixed state path and refuse to overwrite an existing build, install link,
config or user unit:

```sh
(
set -eu
umask 077
service_commit="$(git rev-parse HEAD)"
service_state_dir="$HOME/.local/state/openwiz"
service_build_dir="$service_state_dir/service/builds/$service_commit"
service_install_dir="$HOME/.local/lib/openwiz"
test ! -e "$service_build_dir"
test ! -L "$service_build_dir"
test ! -e "$service_install_dir/current"
test ! -L "$service_install_dir/current"
test ! -e "$service_install_dir/source"
test ! -L "$service_install_dir/source"
test ! -e "$service_state_dir/service/config.json"
test ! -L "$service_state_dir/service/config.json"
test ! -e "$HOME/.config/systemd/user/openwiz.service"
test ! -L "$HOME/.config/systemd/user/openwiz.service"
install -d -m 700 "$service_state_dir" "$service_state_dir/service" \
  "$service_state_dir/service/app" "$service_state_dir/service/builds" \
  "$service_install_dir" "$HOME/.config/systemd/user"
install -d -m 700 "$service_build_dir" "$service_build_dir/web"
install -m 700 target/release/openwiz-service "$service_build_dir/openwiz-service"
cp -R apps/web/out/. "$service_build_dir/web/"
find "$service_build_dir/web" -type d -exec chmod 700 '{}' +
find "$service_build_dir/web" -type f -exec chmod 600 '{}' +
install -m 600 deploy/pc/config.example.json "$service_state_dir/service/config.json"
install -m 600 deploy/pc/openwiz.service "$HOME/.config/systemd/user/openwiz.service"
ln -s "$service_build_dir" "$service_install_dir/current"
ln -s "$(pwd -P)" "$service_install_dir/source"
)
```

If any preflight `test` fails, the subshell stops; keep the existing deployment.
The `source` link keeps the approved checkout as the unit's working directory,
so the existing GitHub API readers resolve the repository exactly as the
standalone server does. Keep this checkout available and make its repository
match the config; the web root remains the running build's `web/`, not the
checkout. The updater uses its own private clone, described below.

Fill `service/config.json` with the real repository, project, orchestrator,
service issue and App ids during T11. The example contains synthetic ids and
uses `allowed_host: null`, so the public write routes remain unavailable. Any
public host, tunnel or Access setup still needs the existing live approval.
The App's key, when T7 needs it, is `service/app/private-key.pem`, mode 0600;
never put it in the config. The service checks its metadata and never reads it.

## Enable the user service, then check it

```sh
(
set -eu
loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now openwiz.service
service_ready=0
service_attempt=0
while [ "$service_attempt" -lt 30 ]; do
  service_attempt=$((service_attempt + 1))
  if OPENWIZ_STATE_DIR="$HOME/.local/state/openwiz" \
    "$HOME/.local/lib/openwiz/current/openwiz-service" status --json 2>/dev/null; then
    service_ready=1
    break
  fi
  sleep 1
done
test "$service_ready" -eq 1
)
```

The unit uses `Type=simple`, so activation can return before the status socket
is ready. The block waits for a successful status response, for at most thirty
attempts one second apart, and fails if the service never answers. Check the
user unit's journal if that happens. Every status attempt is read-only.

[Lingering](https://www.freedesktop.org/software/systemd/man/latest/loginctl.html#enable-linger%20%5BUSER%E2%80%A6%5D)
starts the user manager at boot and keeps it after logout. If changing it needs
administrative authorization, Jake completes that step at the PC. Enabling the
unit installs it under the user's `default.target`.

`status` (with or without `--json`) reads `service/status.sock`; it never treats
saved state as proof that a service is running. With no answer it exits 1,
prints `openwiz-service: service is not answering` on stderr and prints no JSON.
The socket and `service/run.lock` are owner-only singleton metadata. Only the
process holding the lock can replace a stale socket after a crash. A second
service refuses to start.

Missing state starts with empty tick history/incidents, `next_incident: 1`, and
null last-pass/update fields. Malformed existing state or unsafe paths refuse
startup. A saved running tick becomes `stopped`; an unfinished saved fix becomes
`interrupted`, with no tool call. State replacement uses a private temporary
file, file sync, rename and directory sync. Status itself writes no file.

## Pull-only self-update (T6)

Activation remains T11. Installing files, printing help or querying status starts
no updater. Once the service is running, its first update check is due after
300 seconds, and checks repeat on that cadence without overlapping. T7 supplies
the shared App record client through `update::install_records`; until that client
is installed, the job makes no fetch or build call. Records never fall back to a
personal GitHub account. Other tickets retain their own job registrations.

The updater fetches only the configured repository's `main` into
`service/clone/`, verifies its origin and full commit, and refuses a candidate
that is not descended from the running build. It never pushes. A candidate gets
its own `service/builds/<commit>/source/` checkout and target directory. The full
ordered acceptance set in `docs/agents/fleet.md` runs there, one Cargo command
at a time. A failed gate keeps the old build and records its failed step; the
same failed commit is not repeatedly rebuilt. Tool diagnostics are discarded,
and records use fixed service reasons rather than repository or tool output.
The main ref is read before fetching the candidate, so a failed fetch can name
the known commit in its record. A discovery failure before any candidate is
known produces a diagnostic without inventing a commit id.

Only a passing candidate is staged as `service/builds/<commit>/openwiz-service`
and `web/`. Programs and directories are 0700 and web files are 0600. The staged
program's `--update-build` must report the exact fetched commit; this command
prints only compiled identity and starts no service or job.

`service/update.lock` serializes attempts. The durable, bounded, strictly read
`service/update-pending.json` is owner-only and atomically replaced and synced.
It names the attempt's time, old and candidate commits, attempt phase and whether
its one record has been claimed. It never contains a key, token or tool output.

The known-good `current` selection remains in place during the handover. The
running process exits through the existing unit's `Restart=always` policy. On
the next start the old program resumes the saved attempt and executes the staged
candidate in the same supervised process, retaining the repository working
directory, inherited service diagnostics and runtime environment. Gate children
instead receive only the tool environment allowlist; service state and unrelated
variables are never inherited by candidate tests. The candidate checks its compiled identity and exact executable path,
starts the existing HTTP/status runtime and checks its health response before
atomically selecting itself and recording `switched`. It opens no update port
or inbound update route. An exited or unconfirmed candidate leaves the old
selection available to the unit; the old program restores its state and records
`kept/switch` on restart. A candidate-start watchdog bounds an unconfirmed startup
to 30 seconds. The existing unit, not an updater-issued restart command, performs
every restart.

The disposable candidate checkout, its Cargo target and npm dependencies are
removed after either a completed stage or a failed gate. Once a switch is
confirmed, only the running build and its previous build are retained. Cleanup
never follows an obsolete checkout's symlinks outside its directory.

Each completed attempt saves the contract's last update and makes one App
record on `service_issue`. The record callback distinguishes definitely-unsent
requests from uncertain delivery. A definitely-unsent request remains pending
and retries on the next scheduled update check, without rebuilding or changing
the saved attempt. Recovery also delivers a ready record that has not yet been
claimed. An uncertain delivery retains its private journal and blocks later
attempts, with a diagnostic in the service journal; it is never blindly posted
again. `openwiz-service status --json` includes the optional `update_record`
object while a saved attempt has a pending record: `retrying` for an unsent
request, `uncertain` for unconfirmed delivery, with a product-owned reason. The
field disappears after confirmed delivery; saved attempt and record formats do
not change. During T11, resolve any uncertain comment
against the service issue before manually clearing its pending journal. Never
clear a pending journal merely to retry a write whose result is unknown.

The fixture processes prove passing and failing gates, startup confirmation and
rollback. GitHub authentication, activation, systemd restarts and PC behavior
still require T11's live check. No builder has activated this service.

## T11's kill and reboot check

After Jake approves each step, check a kill and one reboot on this unit; record
the before/after status and API health. `Restart=always` restarts an exited
process after five seconds, without a start-rate cutoff. The unit stops its
whole control group. An explicit `systemctl --user stop openwiz.service` leaves
it stopped; `systemctl --user start openwiz.service` starts it again.
These are [systemd's restart semantics](https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html#Restart=),
not a claim that a restart or reboot has been observed on the PC.

Do not run the kill/reboot check from a builder sandbox or against any other
process. No PC, CloudRoom, Mac, GitHub or public-network behavior is proven by
the fixture suite.

## Recording PC activation preparation for 0.0.13

The bounded activation interface is defined in
[`pc_activation/contract.v1.md`](../../tools/install/pc_activation/contract.v1.md).
It selects the owner's `openwiz.service` and the documented enable/start
operation. The installed Linux manager publishes its private definition in
`<state>/service/platform/openwiz.service`, verifies the exact FragmentPath and
links it only when absent. A foreign or conflicting existing unit holds the
operation for reconciliation.

The protected setup operation pins owner, unit definition, installed build,
config, repository, project, runtime, App ids and its request hash in an
owner-only companion journal under the existing setup lock. The existing
protected App setup supplies `<state>/service/app/private-key.pem` with 0700
directories and a 0600 key. Activation checks metadata through the existing
signer boundary and reads zero key bytes.

Lost start replies remain uncertain until fresh status and the exact run-lock
holder prove the same saved resource healthy. The current build-only status
response cannot supply that complete binding. T12 owns the native observation
and installed handover after its separate ownership and login gates. Its App
record adapter must reuse the existing sink's exact comment read-back and
unsent/uncertain distinction. The recording tests establish these interface
rules on synthetic providers. Native activation, linger, logout/reboot and
installed acceptance retain their separate live gates.

This preparation exposes no installed activation command. The existing service
scheduler supplies its registered tick and updater when separately activated.
Cloud activation and Cloud secret transport retain their unresolved capability
and approval requirements.
