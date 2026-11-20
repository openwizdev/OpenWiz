# Driver v1 test kit

Runs the five checks of [driver v1](../driver.v1.md) against one driver, on one throwaway ticket. **Platforms:** Linux and macOS, Python 3.9 or later, standard library only (it watches `/proc` on Linux, and `ps` on macOS). It never writes to GitHub: the agent the driver starts writes its own status note.

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/<host>/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness <h> --model <m> [--skill build-ticket] [--wait 900]
python3 -I kernel/driver-kit/test_kit.py     # the kit's own tests: the template passes, each planted driver fails
```

It prints one line per check, in the order version, start, wake, stop, token: `pass <check>: <what>` or `fail <check>: <why>`. Exit 0: all five pass. 1: a check failed. 2: the kit could not run; it says why on stderr, `kit.py: <why>`. Wake and stop run only after start passes.

## The throwaway ticket

Make a throwaway repository with a `docs/agents/fleet.md` whose `Record authors` row names the account your agents post as, and one open ticket in it. The kit reads the ticket's comments through a signed-in `gh` (GraphQL only), every 10 seconds, for up to `--wait` seconds per step. Close the ticket when you're done; the kit leaves it as it is.

`--tracker <file>` reads the ticket from a local file instead of GitHub, for the kit's own tests: a JSON object with exactly `record_authors` (logins) and `comments` (each exactly `id`, `author`, `updated_at` and `body`).

## What it doesn't see

It knows a credential by the status contract's credential rules or as the value of a secret in its own environment. It never shows a driver answer that holds one, in its text or once decoded: that answer fails with a fixed diagnostic.

It sees the processes a driver starts on this machine (each carries the kit's `OPENWIZ_KIT_RUN` mark in its environment), not what a remote host runs. A driver that clears its children's environment hides them from the token and stop checks: its review must check that by reading its code.

On macOS, with no `/proc`, the kit lists processes with `ps -A`, and reads each one's environment with `ps -E`. Where `ps` shows a process's environment, the mark finds it as on Linux. Where it shows none, the kit finds the run's processes by process group instead: a process belongs to the run when it is in a group where the kit has seen a marked process, never the kit's own group. On macOS a process's environment is the words `ps -E` prints after its command line, so the token check reads it word by word.

## Fixtures

- `fixtures/no-proc/`: runs Python as on macOS, on Linux: no `/proc`, no `prctl` and no pidfd, `sys.platform` `darwin`, and a `ps` that takes macOS's `-E`. The drivers' and the kit's tests put it first on `PATH` to run the macOS path (#2010).
- `fixtures/fake-harness`: a synthetic harness. It posts one builder note into the tracker named by `KIT_TRACKER`, edits it when woken, then waits to be stopped.
- `fixtures/planted/<name>`: the template with one planted break each. `test_kit.py` names the exact lines each must print.
- `evidence/`: the red run and the green run; `red-1586.txt`, `red-1586-r1.txt` and `green-1586.txt` are those of the credential fixes.
