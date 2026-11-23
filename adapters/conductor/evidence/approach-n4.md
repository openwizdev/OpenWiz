# Approach note: porting the Conductor driver to the key helper (driver v1 N4)

Frozen head before the port: `921a7829db30e4684b477772fca6696e17a2b056`. Ruling: port it (#1987, 2026-11-23).

## Approach

1. Merge `origin/main` into the branch (no rebase). It brings N4 (#2395), `kernel/driver-kit/hostkey.py`, `hosts.json` and the kit's key check. Copy `kernel/driver-kit/schema.json` byte for byte to `adapters/conductor/schema.json`.
2. Replace the driver's `api()` (curl with `--variable %<key variable>`) with one `ask()` that runs `python3 -I kernel/driver-kit/hostkey.py` and sends it only `host: conductor`, a method, a path and a body on stdin. Delete the API address constant, the key-variable check (`signed_in`) and the curl version check. The driver never names, reads or receives the key, and never picks the address.
3. Add one `conductor` row to `kernel/driver-kit/hosts.json`: origin `https://api.conductor.build`, the user's variable, keychain entry `openwiz-conductor`, bearer header. This is the planner's grant on #1992, listed as a supporting edit.
4. The README's login line stays `Login: held by Conductor`. One line under it names the variable and the keychain entry together, as N4's cloud form asks. Nothing else in the folder names the variable.
5. Keep the unknown-outcome rule: a start whose answer is lost is never retried. A helper refusal counts as "nothing was started" only when the helper refused before it sent anything (the same list of fixed texts as the Devin driver). Anything else after a start is an unknown outcome.
6. Replace the fake `curl` with the kit's loopback fake host (`OPENWIZ_HOSTKEY_TEST_ORIGIN`). The helper gets its test key from the fake, so no real key and no real Conductor are ever involved.

## Where a key could still leak

- **Arguments.** The driver runs the helper with fixed arguments (`-I` and its path). The key is never on any command line, and the request goes on stdin. The helper refuses a request that holds the key.
- **Environment.** If the user exported the variable, the driver inherits it, and the helper inherits it from the driver. That is how N4 reads it. The driver never reads it, copies it into a variable it builds, or passes it to any other child. The helper is its only child. The kit runs the driver without the variable and fails it if the canary shows up anywhere but the helper's header.
- **Output.** The driver prints only its own fixed texts, plus the helper's `error`/`next`, which the helper gates so they never contain the key. Conductor's answer goes back through the helper, which refuses an answer that holds the key. The driver never prints Conductor's raw body; it prints only `userMessage`/`code`, cut to 100 characters.
- **Logs.** There is no curl and no trace any more, and the driver keeps no logs. Tests log only synthetic values.
- **Files.** Run state stores the request and Conductor's ids, never a key. No file in `adapters/conductor/` names the variable outside the README's one key line. The test reads the variable's name from `hosts.json`.
- **Address.** Only `hosts.json` holds the origin. The driver sends paths only, and the helper refuses a path that would leave the registered address.
- **Residual.** The helper process holds the key while it runs, and hostile code running as the same user can read it. This is the kit README's stated limit.

## What tests can and can't prove

- Can: on a loopback fake, start, wake and stop reach Conductor's paths only through the helper. The key is the fake's canary, it appears only in the helper's `Authorization` header, and the driver runs without the variable. The driver's folder never names the variable (the kit's key check). The red test fails on the old driver, which needs the variable and calls curl itself.
- Can't: that the real Conductor API accepts the bearer key at `https://api.conductor.build`; that the keychain lookup works on a real Mac or Linux desktop; that Conductor never echoes a key; that same-user hostile code can't attach to the helper. The first two need the new live run (#1993) at the new head. The last is review.
