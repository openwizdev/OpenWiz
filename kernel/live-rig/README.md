# Live-check rig

Runs the [driver v1 kit](../driver-kit/README.md) against real hosts, on a schedule, wherever a signed-in tool already exists on the machine. Each run of the kit leaves a run record; a host that can't run is skipped, and its record says why. The design is spec #2474. **Platforms:** Linux and macOS, Python 3.9 or later, standard library only.

## Hard limits

- It never signs in, installs anything, spends money or starts a paid run: a host whose tool is missing, isn't signed in, or whose run might cost money is skipped.
- It never reads, adds or prints an environment value, and never passes a key: each status command and the kit get the caller's environment unchanged.
- The rig itself never writes to GitHub: it and the kit only read, through the signed-in `gh` (the kit reads the throwaway ticket; the rig reads the signed-in login). The agent the driver starts posts its one status note on the throwaway ticket the settings name, and edits it when woken, as the kit's start and wake checks require.
- It reads only the kit's stdout and exit code. The kit's stderr goes straight to the rig's, and the rig writes the kit's whole stdout to its own stderr for the person; the run record keeps only the check lines described below. Status commands get no stdin and their output is discarded.
- Status commands run only from reviewed code: `--hosts` must be a folder inside the clean checkout, reached through no symlink inside the checkout, and every host config in it must be a regular file git tracks (never a symlink), so a command comes only from a merged host config. Each host ticket's review checks that its commands are read-only; the rig itself cannot tell a read-only command from one that signs in or writes.

## Run it

From the root of a clean checkout (a run record names its commit, so uncommitted changes refuse):

```sh
python3 -I kernel/live-rig/rig.py --hosts kernel/live-rig/hosts --settings <file> --out <dir> [--host <name>]
    [--drivers <folder> | --release <folder> --host <name>]
PATH=<stubs>:$PATH env -u OPENWIZ_GITHUB_APP_KEY python3 -I kernel/live-rig/test_rig.py   # its own tests, on fixtures
```

`<stubs>` is a fresh `mktemp -d` folder holding a refusing stub (it prints a refusal to stderr and exits 1) for each agent CLI: claude, codex, cursor-agent, agent, pi, opencode, copilot, goose, gemini, kimi, qwen, cline, kilo, crush, vibe, auggie, kiro-cli, junie, amp, agy, oz, sculpt, hermes, acpx and droid. CI's step makes the same folder and runs every `kernel/live-rig/test_*.py` and `kernel/live-rig/*/test_*.py` this way.

- `--settings`: a local JSON file outside the repository, `{"repo": "<owner>/<name>", "ticket": <n>}`, naming the throwaway repository and ticket the kit uses ([the kit's throwaway ticket](../driver-kit/README.md#the-throwaway-ticket)).
- `--out`: a folder outside the checkout. It holds the lock (`rig.lock`), so two runs never overlap: a second one prints `rig.py: another run holds the lock` and exits 0.
- `--hosts` names a folder inside the checkout whose `*.json` files git tracks. Only those files are host configs. The rig ignores other files, such as a host's `test_<host>.py`. The path must be traversable as written, including each step before a `..`. A failed prefix lookup, a path outside the checkout or through a symlink inside it, an untracked config, or a config that is a symlink causes exit 2. Two `runs` entries that would write the same run record, ignoring case (a case-insensitive disk would merge them), cause exit 2 too, as do two host names that differ only in case.

- `--drivers` names a drivers folder laid out as the [driver package contract](../../contracts/driver-package.v1.md#drivers-folder-and-updates) fixes, `<name>/driver` with its data beside it, such as the install's `"$OPENWIZ_ADAPTERS"` (the rig reads no environment value itself, so pass it on the command line). Each host's driver is then `<folder>/<name>/driver`, where `<name>` is the host part of its `driver` field, instead of the checkout's `adapters/<name>/driver`. This is how a driver that moved out of the kernel is live-checked.
- `--release` names one unpacked driver release (the release archive's root files `driver`, `schema.json` and `README.md`, with no wrapper folder) and needs `--host`; that host's driver is then `<folder>/driver`. It cannot be combined with `--drivers`.
- A driver found through `--drivers` or `--release` must be a regular file, and neither it nor its folder may be a symlink (an installed driver never is); otherwise the rig exits 2 before any run. The rig runs it as the install would, from outside the checkout, so it is trusted as the install's checks left it, not as reviewed code. Run records still name the checkout's `HEAD` as `driver_commit`.

For each host the rig checks every `needs` program, then `cost`, then every `signed_in` command. If all checks pass (and, with `--drivers`, the folder holds its driver), it runs the kit once per `runs` entry.
`python3 -I kernel/driver-kit/kit.py --driver <driver> --repo <repo> --ticket <n> --harness <h> --model <m> --wait <w>`.
It prints one line per entry, `ran <host> <harness>: <k> of 5` or `skipped <host> <harness>: <why>`, where `<why>` is `not installed: <program>`, `not signed in: <program>`, `cost` or, with `--drivers`, `not installed: driver <name>` (the folder holds no `<name>/driver`). Exit 0: every entry ran or was skipped. 1: a kit exited 1 or 2. 2: the rig could not run; it says why on stderr, `rig.py: <why>`.

[`schedule.json`](schedule.json) is the weekly run (Monday 03:00), with the exact command, run from the checkout's root with the settings and records in a sibling folder. It runs on the PC only, never in the cloud.

## Host config

`hosts/<host>.json`, one per host, with exactly the keys of spec #2474's Implementation Decisions. `driver` is always `adapters/<name>/driver`: it names the driver `<name>`, found in the checkout by default or in the folder `--drivers` or `--release` gives, so every existing config keeps working:

```json
{"host": "boat.dev", "driver": "adapters/boat/driver", "needs": ["boat"], "signed_in": [["boat", "status"]],
 "cost": "none", "runs": [{"harness": "claude", "model": "Opus 5.5"}], "wait": 900}
```

`signed_in` commands are read-only (never one that signs in, opens a browser, prompts or prints a credential), each must exit 0 within 30 seconds, and a timeout counts as not signed in; each host's pull request cites its command's source. Only `cost: none` runs; `paid` and `unknown` are skipped, and changing a host to `none` needs Jake's recorded OK. `wait` is at most 900. The example above is a shape, not a real host's config.

Other tools import the host checks from `rig.py` without running it: `load_host(path)` returns one host config, parsed and checked (a bad one raises `rig.Refused`), and `check_host(config)` returns `None` when the host may run, or its exact skip reason (`not installed: <program>`, `not signed in: <program>` or `cost`).

## Run record

`<out>/<YYYY-MM-DD>/<host>-<harness>-<model>.json`, one per `runs` entry, with exactly: `host`, `harness`, `model`, `date` (UTC), `driver_commit` and `kit_commit` (the checkout's 40-hex `HEAD`), `outcome` (`ran` or `skipped`), `skipped` (the reason or `null`), `kit_exit` (integer or `null`), `stdout` (the kit's check lines, or `null`) and `seconds` (whole seconds). `stdout` keeps only the kit's check lines (`pass` or `fail`, then `version`, `start`, `wake`, `stop` or `token`, then `: `), in the kit's order. A line whose text after that prefix matches the kit's credential shapes, holds anything but plain ASCII letters, digits, spaces and `.,;:'()-` (so any `/`, `\`, `~`, `=`, `@`, other symbol, non-ASCII letter or control character), or holds the settings' repository, its owner or its name, or the signed-in `gh` login, is kept as `<pass|fail> <check>: withheld`; when the login can't be read, every line is. The receipt writer reads these records, and needs only the clean `pass` lines.

## Fixtures

- `fixtures/hosts/`: fixture host configs: one on `adapters/template/driver` that runs 5 of 5, one with a missing program, one whose status command fails, one with `cost: unknown`, one on a planted driver, and one whose driver quotes the checkout's path and the repository. The tests copy them into a throwaway git checkout and commit them, so they are tracked there.
- `fixtures/rig/`: the tests' fakes. `gh` answers the rig's login read and the kit's two GraphQL reads (from the kit's fake harness's tracker file), so the kit runs with the rig's exact command line and never reaches GitHub; `fake-signed-in` and `fake-signed-out` are status commands; `planted-driver` becomes `adapters/planted/driver` in the tests' throwaway checkout, the kit's `wake-does-nothing` planted driver, and `quoting-driver` becomes `adapters/quoting/driver`, whose refused start quotes both. Every test puts its own refusing stubs for the agent CLIs first on `PATH` before it runs or imports `rig.py`, so a fixture mistake can never start a real one. The test process is its runs' child subreaper, and its teardown ends only its own descendant processes, found through `/proc/<pid>/stat`, never another process's environment.
