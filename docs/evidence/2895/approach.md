# #2895 approach: a keychain-only key on the VPS Cursor and Conductor configs

Ticket LR16 of spec #2474. Owned: `kernel/live-rig/vps/hosts/cursor.json`, `kernel/live-rig/vps/hosts/conductor.json`, `kernel/live-rig/vps/test_hosts.py`. Relies on `kernel/driver-kit/hostkey.py` (read only, never edited).

## What the helper and drivers say

- `kernel/driver-kit/hostkey.py` reads a host's key from its variable, and only when that is empty, from the keychain: `/usr/bin/secret-tool lookup service <entry>` on Linux, `/usr/bin/security find-generic-password -w -s <entry>` on macOS. Both print the value. The helper has no existence check; `test_hostkey.py` fakes the lookup and tests no existence check either.
- Cursor (PR #2021, host `cursor-cloud`): variable `CURSOR_API_KEY`, keychain entry `openwiz-cursor-cloud`.
- Conductor (PR #2020, host `conductor`): variable `CONDUCTOR_API_KEY`, keychain entry `openwiz-conductor`.
- Neither driver's README documents an existence check that reads no value and raises no prompt.

## Is there a provably prompt-free existence check?

- **Linux:** no. `secret-tool lookup` prints the value. `secret-tool search` prints the secret of unlocked items and can unlock with `--unlock`. A raw Secret Service `SearchItems` call over D-Bus has no prompt in its signature, but whether a provider shows its own UI on a search is up to the provider, and the call can start a provider through D-Bus activation. Nothing guarantees it. The VPS is also headless, and its bootstrap installs no keyring at all.
- **macOS:** no. `security find-generic-password -s <entry>` without `-w` prints attributes only, but the `security` tool has no switch that forbids user interaction, so a locked keychain can bring up its unlock dialog.

So, as the ticket says, neither platform gets an approximation. On both, a key kept only in the keychain records `skipped: not signed in: python3` for these two hosts. The reason is written in each config's probe (a `why` string inside the probe's own code, since a host config allows no other keys) and here.

## Approach

1. The probe stays the variable check by name only: it iterates `os.environ`'s names and compares each to the one name. It never subscripts, `.get`s or tests `in os.environ` (a mapping's `in` reads the value), never imports anything but `os` and `sys`, and starts no process.
2. Each probe carries one `why` string naming its keychain entry and this file, so the config itself says why a keychain-only key skips.
3. `needs` (curl) is unchanged: `tools.json` and the bootstrap pin curl for these hosts, and they are not this ticket's paths. Listed as a gap.

## Threats

- **Reading a secret by mistake:** the probe touches no value, by an AST check of its code: names compared only, no subscript, `.get`, `getenv`, `in`, `values`, `items`, `environb`, no import but `os`/`sys`, no `subprocess`.
- **An OS keychain or keyring prompt:** the probe calls no keychain tool. Proven twice: by the AST check (no process, no absolute tool path) and by a rig run with fake `secret-tool`, `security`, `gdbus`, `busctl`, `dbus-send` and `kwallet-query` first on PATH that log any call and exit 0 (as if the entry existed). The log must stay empty and the host must skip.
- **A value in output or logs:** rig runs plant a synthetic value in the variable; it must not appear in stdout, stderr or any record (the existing check, kept).
- **Residual, not fixed here:** a variable that is set but empty passes the name-only probe; at run time (only under a person's `--allow-cost`, since both hosts are paid) the helper would then fall back to its own keychain lookup, which can prompt. Checking emptiness would read the value, which the ticket forbids. Listed as a gap for the lead.

## What tests can and can't prove

- Can: the probe's code reads no value and starts no process; a keychain-only key skips without any keychain tool being called; a key in neither place skips; a key in the variable passes; no planted value reaches output; the config names why.
- Can't: what a real Secret Service provider or a real macOS keychain does, which is why the design calls neither. No real keychain, host or agent CLI is touched by any test: all 37 agent CLIs get refusing stubs first on PATH, and keychain tools are fakes.
