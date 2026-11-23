# Approach note: porting the Cursor driver to the key helper (driver v1 N4)

Frozen head before the port: `e7ec81005d2d39d8cfe018acd631f543debcf7e9`. The planner ruled on #1987 (2026-11-23): port it.

## The approach

1. Merge `origin/main` in (never rebase). Copy `kernel/driver-kit/schema.json` byte for byte to `adapters/cursor/schema.json`.
2. Every Cursor call becomes one run of `python3 -I kernel/driver-kit/hostkey.py` with `{"host": "cursor", "method", "path", "body"}` on stdin, as the Devin driver does. The driver sends only a host name, a method, a path below `/v1` and a body. It reads back `status` and `body`, or the helper's error.
3. Remove the curl path: no `curl`, no `--variable`, no version check, no check that the key variable is set, no `API` address constant. The driver never names the key's variable or keychain entry, and reads no environment beyond its state folder.
4. One row in `kernel/driver-kit/hosts.json` for host `cursor`: origin `https://api.cursor.com` (the address only, no path), with the registry's required variable, keychain entry (`openwiz-cursor`) and bearer header. This is the planner's grant on #1994, listed as a supporting edit.
5. The README's login line keeps `Login: held by Cursor`; one line under it names the variable and the keychain entry together (the only place in the folder that may name them), and the key wording says the helper alone reads the key.
6. Tests: the fake `curl` goes. A loopback fake Cursor (`fixtures/fake-cursor`) serves Cursor's routes and the helper's test key, reached through `OPENWIZ_HOSTKEY_TEST_ORIGIN`. `fixtures/kit-host.json` gives the kit's own fake host Cursor-shaped answers for its key check. The test file takes the variable's name from `hosts.json`, never spelling it.
7. Old evidence files that spell the variable (the curl-era red and green logs) are removed from the folder: the kit's file check scans every file of it. They stay in git history at `e7ec8100`.

## Where a key could still leak, and what stops it

- **Arguments:** the helper is run as `python3 -I hostkey.py` with no other argument; the key is never on any command line.
- **Environment:** the driver builds no environment for the helper; it inherits the user's. The driver never reads or copies the variable. Under the test override the helper reads only the fake host's test key.
- **Input to the helper:** only host, method, path, body; the helper refuses a request that holds the key.
- **Output:** the driver echoes only the helper's fixed error texts and Cursor's error code word (`[a-z_]{1,40}`), capped at 300 characters; the helper refuses to pass on an answer that holds the key.
- **Logs and files:** the state file holds the request, the agent id and flags only. No file of the driver's folder names the variable or calls a keychain tool (the kit's file check).

## What tests can prove, and what they can't

- Can: the kit's five checks on the fake Cursor, including its key check (the canary reaches the fake host only in the helper's header on start, wake and stop, and no driver file names the variable); every call goes through the helper with the expected method and path; the driver's source reads no key and names no address; refusals, lost answers and stop paths behave as before.
- Can't: that `api.cursor.com` answers as the fake does, that the keychain lookup works on a user's machine, or that Cursor's agent follows the prompt. That needs the new live run (#1995) at the new head.
