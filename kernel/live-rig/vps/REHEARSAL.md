# Rehearsal of the VPS session

Ticket LR9 (#2583) of spec #2474. A fresh child in its own throwaway cloud sandbox runs [SIGN-IN.md](SIGN-IN.md) end to end on fakes, so Jake's session on the VPS is not the first run. No real sign-in, key, spend, agent turn or GitHub post happens here. The transcript, the stub script (`stubs.sh`), the fixture setup (`fixtures.sh <clone> <fixture folder> <home>`) and the session shell (`session-env.sh`) are in [`docs/evidence/2583/`](../../../docs/evidence/2583/); in them `$FX`, `$STUBS`, `$HOME` and `$SRC` stand for the run's temp folders and clone.

## Run 1: from the PR heads, 2026-11-23

One local branch from `main` (`a36cb1ea05209e92f9e6b01857ae59408c998ac6`), with these heads merged in, in this order:

| PR | Ticket | Head |
| --- | --- | --- |
| #2572 | #2477 runner | `bb91163a8868cd9123b53bed7e52b8f57391bd9c` |
| #2641 | #2507 receipt writer | `a1ae40f44306f83b1ede476a7d33172727930444` |
| #2646 | #2580 bootstrap | `94d3c4cc2e2bf36b1d5b777312bf3165aee326b9` |
| #2656 | #2581 sign-in page | `b8ccb13fc6c10bb272b42e1259e7d2dfb6e6344d` |
| #2682 | #2582 heads.py | `07b00a4a95314504748403ab1734d538bbf989dd` (in review; a fix round was starting) |

The drivers ran from their build heads, which the fixture tickets name as frozen heads: Hermes #2017 `a823bb6f37e7`, Conductor #2020 `921a7829db30`, Cursor #2021 `e7ec81005d2d`, Factory #2022 `aa83e218c459`, Pane #2029 `cd0e1aff8c8f`.

| Step | Jake types | What ran here instead | Time |
| --- | --- | --- | --- |
| 0. Guard | nothing | 37 refusing stubs for every agent CLI the fleet's drivers or harness rows can start, first on `PATH` from a private temp folder (`stubs.sh`) | 0 s |
| 1. Bootstrap, dry run | `kernel/live-rig/vps/bootstrap.sh --dry-run` | the same, with `HOME` a fresh empty folder: 6 to install, 2 already there | 1 s |
| 1. Bootstrap | `kernel/live-rig/vps/bootstrap.sh` | the same, for real: installed curl 8.23.0, gh 2.105.0, hermes 0.23.3, runpane 2.4.246, pane 2.4.246, droid 1.17.2 into `$HOME/.local` | 79 s |
| 1b. Stubs back | nothing | stubs put back in front of `$HOME/.local/bin`; a second bootstrap run installed nothing (8 already there) | 1 s |
| 2. Throwaway repository and ticket | the kit's throwaway-ticket setup | a fixture settings file `{"repo": "example/site", "ticket": 7}` and a fixture tracker | 20 s with step 4 |
| 3. Claude Code | the official install, `/login`, `claude auth status`, `runpane agents doctor ...` | not rehearsed: `claude` stays a refusing stub (no agent CLI ever runs) | 0 s |
| 4. Sign in | `gh auth login`, each host's row, export the three key names | a fixture `gh` whose `auth status` answers signed in; the drivers' own fake `hermes`, `droid`, `runpane`; `CONDUCTOR_API_KEY`, `CURSOR_API_KEY`, `FACTORY_API_KEY` set to dummy values. Every status probe in `hosts/*.json` passed | (above) |
| 5. One command | the page's `heads.py ... --allow-cost` x5 `--post` | the page's command exactly, from the clean checkout, with each driver's `fixtures/bin` fake and the fixture `gh` first on `PATH`, and `origin` a fixture git remote holding only the five build heads | 24 s |

**Total session: 4 min 48 s** (01:10:46 to 01:15:34 UTC), with no hand sign-ins and fake turns. On the VPS, add the sign-ins by hand and the real turns: each host's kit waits up to its config's `wait` (900 s) for each of start, wake and stop.

**Result:** every host reached `ran <host>: 5 of 5`: Hermes, Conductor, Cursor, Factory and Pane. `--post` reached only the fixture `gh`: one comment per build PR and one WizMarket pull request with five receipts, all answered by the fake. No stub refused anything, so nothing reached for a real agent CLI. No run record holds a path, the login or the settings' repository.

### What failed, and where it goes

Each problem goes to its owning ticket's PR; nothing is fixed here.

1. **#2572 (#2477) conflicts with `main`** in `.github/workflows/ci.yml`: `main`'s `tools/bench/first-fleet/test_bench.py` line (#2343) sits where the rig's CI step goes. This run kept both.
2. **#2656 (#2581): `vps/test_hosts.py` fails 31 cases once #2572's head is in**, with `rig.py: [Errno 2] No such file or directory: '<temp>/checkout/kernel/driver-kit/kit.py'`. It passes on its own head, which stacks an older `rig.py`; the newer one reads `kernel/driver-kit/kit.py`, which the test's temporary checkout doesn't copy.
3. **#2682 (#2582): two `test_heads.py` cases fail once #2641's head is in**: `refused fixture-five: no receipt: receipt.py: the run record model is not a public token`. The fixture host's model is `Synthetic 1` (a space), which #2641's newer `receipt.py` refuses. It passes on its own head, which stacks an older `receipt.py`.
4. **#2646 (#2580): an existing `~/.local/bin/droid` is replaced without a word**, while an existing `hermes` is kept. With a `droid` that names another version already there, `--dry-run` says `would install droid 1.17.2` and gives no `existing one is kept` or `replaces` note. On a VPS where Jake ran Factory's own installer first, the bootstrap swaps his `droid` silently.
5. **#2656 (#2581): the Factory row says to install Droid by its quickstart**, after the bootstrap (step 1) already installed the pinned `droid` 1.17.2. Following the row reinstalls `droid` from Factory's installer at whatever version it ships that day, so the run is no longer on the pinned version. The Pane row's "Install Pane" is the same, but a reinstall is harmless there.

### Notes for the rehearsal itself

- The receipts name `kit: openwizdev/OpenWiz@<the local stacked merge>`, a commit only this sandbox has. The re-run from `main` will name a real `main` commit.
- Conductor's and Cursor's drivers each ship their own fake `curl`, and one `PATH` holds one `curl`, so the fixture setup routes by API address (`fixtures.sh`). The real session uses one real `curl`, so this is fixture glue, not a product problem.
- This sandbox's real home already held agent launchers in `~/.local/bin`, so the whole session ran with `HOME` a fresh folder. That is also what a fresh VPS looks like.

## Run 2: from `main`

Not yet: it runs once #2580, #2581 and #2582 merge, with #2689 and #2696 in, and records that commit here.
