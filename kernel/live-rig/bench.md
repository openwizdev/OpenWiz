# AFTER bench

Ticket #2508. Measured on merged `main` at `2b0b0d192d9013f223279d507bc7a809540f66da`, which has `kernel/live-rig/rig.py`, `kernel/live-rig/receipt.py`, `kernel/live-rig/hosts/local.json`, `kernel/live-rig/hosts/boat.json`, and `kernel/live-rig/hosts/cloudroom.json`.

The BEFORE column is spec #2474's BEFORE bench, copied into `docs/evidence/2508/before.txt` and not re-measured here. The AFTER column is this commit's host configs, `kernel/live-rig/listings.json`, and the fixture run in `docs/evidence/2508/`.

## Side by side

| Measure | BEFORE | AFTER |
| --- | --- | --- |
| Driver and harness listings that could show `verified` | **3 drivers, 0 harnesses**, from hand runs at heads on 2026-11-20. Copied in `docs/evidence/2508/before.txt`. Not re-counted here. | **1 driver, 0 harnesses.** `local` (`listings.json` id `local`) is the only driver listing whose host config has `cost: none`. `listings.json` has no `<host>/<harness>` key, so harness listings with `cost: none` are 0. Count in `docs/evidence/2508/listings.txt`. |
| Candidate listings | 3 drivers (local, boat.dev, Cloudroom) and the harnesses named on them. Copied in `before.txt`. | **8 driver listings, 0 harness listings.** The eight host configs each have one driver id in `listings.json`. Seven are skipped as `cost` (below). |
| A live check | A person's job. Minutes unmeasured in the spec. Up to 45 minutes at `--wait` 900, then the evidence written by hand. Copied in `before.txt`. Not re-timed here. | One `rig.py` run on `kernel/live-rig/fixtures/hosts`. Record `seconds`: **21** for the 5-of-5 template entry, **0** for each of the other five entries. Process wall clock of that command: **20.916** seconds. Hand steps inside `schedule.json`'s command: **none**. A WizMarket pull request is still outside that command. |
| Re-checks | None. Copied in `before.txt`. | `kernel/live-rig/schedule.json` names a weekly command, `0 3 * * 1` in `UTC`, and that command is only `rig.py`. Whether anything outside this repository runs it is unmeasured (#2509). `receipt.py` is on this commit. This run's `receipt.py` wrote no file. |

## Listings that could show `verified`

A driver listing is counted when `listings.json` maps the host and that host's config has `cost` exactly `none`. A harness listing would be a `listings.json` key `<host>/<harness>` whose host has `cost: none`. In `rig.py`, the kit runs only after every `needs` program is on `PATH`, `cost` is `none`, and every `signed_in` command exits 0. `receipt.py` writes a receipt only for a 5-of-5 record, and only for the driver id or a `<host>/<harness>` id that `listings.json` actually has. This run did not produce a `local` receipt. That gap is below.

| Kind | Host | Listing id | Run | Config |
| --- | --- | --- | --- | --- |
| driver | `local` | `local` | `claude` / `claude-opus-5-5` | `kernel/live-rig/hosts/local.json` |

That run has no `<host>/<harness>` key in `listings.json`. The driver id for the host is `local`. No `local` run record was written here.

**1 driver listing. 0 harness listings.**

### Skipped as `cost`

`check_host` in `kernel/live-rig/rig.py` returns `cost` when `cost` is not `none`. These seven driver listings are outside the count above. The spec says only `none` runs, and changing a host to `none` needs a recorded OK.

| Host | Listing id | `cost` | Runs | Config |
| --- | --- | --- | --- | --- |
| `boat.dev` | `boat-dev` | `unknown` | `claude` / `opus-5-5`, `codex` / `gpt-5.4-mini` | `kernel/live-rig/hosts/boat.json` |
| `Cloudroom` | `cloudroom` | `unknown` | `claude` / `claude-opus-5-5` | `kernel/live-rig/hosts/cloudroom.json` |
| `Hermes` | `hermes` | `paid` | `claude` / `claude-opus-5-5` | `kernel/live-rig/vps/hosts/hermes.json` |
| `Pane` | `pane` | `paid` | `claude` / `claude-opus-5-5` | `kernel/live-rig/vps/hosts/pane.json` |
| `Factory` | `factory` | `paid` | `droid` / `claude-opus-5-5` | `kernel/live-rig/vps/hosts/factory.json` |
| `Conductor` | `conductor` | `paid` | `claude` / `opus-5-5-1m` | `kernel/live-rig/vps/hosts/conductor.json` |
| `Cursor` | `cursor-cloud-agents` | `paid` | `cursor` / `composer-2.5` | `kernel/live-rig/vps/hosts/cursor.json` |

`kernel/live-rig/vps/SIGN-IN.md` says each of those five VPS hosts carries `cost: paid`, and a run of one needs `--allow-cost` on `heads.py`. The weekly command in `schedule.json` is `rig.py`, which has no `--allow-cost`.

### No read-only status command

Every merged host config has a non-empty `signed_in` list: 8 configs, 0 empty (`docs/evidence/2508/listings.txt`). No listing is left out of the `cost: none` count because its status list is empty.

Five `needs` programs are not the program named by any `signed_in` command. That is a separate fact from the `cost` skip. `check_host` does not skip a host for it when another status command is present.

| Host | Program in `needs` | Why the files give no status command for that program |
| --- | --- | --- |
| `local` | `claude` | Spec #2474: a `claude` harness is listed in `needs` only, with no unattended sign-in probe. `local.json` still has the GitHub probe and `cost: none`, so the driver listing stays in the count above. |
| `Hermes` | `hermes` | `kernel/live-rig/vps/SIGN-IN.md`: the config probes GitHub only, and Hermes has no status command whose exit code shows a sign-in. The rig skip for this host is `cost`, because `cost` is `paid`. |
| `Factory` | `droid` | `signed_in` is a `python3` check that the name `FACTORY_API_KEY` is set, then the GitHub probe. `SIGN-IN.md` calls that the status check. The rig skip is `cost` (`paid`). |
| `Conductor` | `curl` | `signed_in` is a `python3` check that the name `CONDUCTOR_API_KEY` is set, then the GitHub probe. `SIGN-IN.md` calls that the status check. The rig skip is `cost` (`paid`). |
| `Cursor` | `curl` | `signed_in` is a `python3` check that the name `CURSOR_API_KEY` is set, then the GitHub probe. `SIGN-IN.md` calls that the status check. The rig skip is `cost` (`paid`). |

`boat`, `gh`, `room-cli`, and `runpane` each appear as a `signed_in` program on the hosts that list them in `needs`.

## Time per live check

Command, with the fixture programs and refusing stubs in `docs/evidence/2508/commands.txt`:

```sh
env -u OPENWIZ_GITHUB_APP_KEY python3 -I kernel/live-rig/rig.py --hosts kernel/live-rig/fixtures/hosts --settings <file outside the checkout> --out <dir outside the checkout>
```

Exit **1**. A kit exited non-zero (the planted and quoting entries). The rig itself ran. Summary lines are `docs/evidence/2508/stdout.txt`.

`seconds` on each run record (`docs/evidence/2508/records/2026-11-26/`, date `2026-11-26`, `driver_commit` and `kit_commit` `2b0b0d192d9013f223279d507bc7a809540f66da`):

| Record | Outcome | `seconds` |
| --- | --- | --- |
| `fixture-template` / `fake-harness` / `Synthetic 1` | `ran`, `kit_exit` 0, stdout is 5 `pass` lines | 21 |
| `fixture-planted` / `fake-harness` / `Synthetic 1` | `ran`, `kit_exit` 1, 0 of 5 | 0 |
| `fixture-quoting` / `fake-harness` / `Synthetic 1` | `ran`, `kit_exit` 1, 0 of 5 | 0 |
| `fixture-cost` / `fake-harness` / `Synthetic 1` | `skipped`, `cost` | 0 |
| `fixture-missing` / `fake-harness` / `Synthetic 1` | `skipped`, `not installed: rig-fixture-not-installed` | 0 |
| `fixture-signed-out` / `fake-harness` / `Synthetic 1` | `skipped`, `not signed in: fake-signed-out` | 0 |

The same command's process wall clock is **20.916** seconds (`docs/evidence/2508/elapsed.txt`). The record field is whole seconds. These two clocks are both measured on this run. No other duration was taken.

Hand steps inside one scheduled run, once `schedule.json`'s command is what runs: **none**. The `command` array is `python3 -I kernel/live-rig/rig.py` with `--hosts`, `--settings`, and `--out` fixed in the file. It asks for no per-run input.

The step still by hand is opening a WizMarket pull request for a receipt. `schedule.json` does not run `receipt.py` or `heads.py`. `kernel/live-rig/README.md` says the rig never writes to GitHub. `heads.py` posts a WizMarket pull request only with `--post`, and one such invocation puts that invocation's receipts on one pull request. This run did not pass `--post`, did not open a pull request, and did not measure how many receipts one pull request would carry.

`receipt.py` on the 5-of-5 record, `--listing fixture-template --run-by example-rig-login`: exit **1**, stdout empty, no file written. Stderr: `receipt.py: the run record model is not a public token` (`docs/evidence/2508/receipt-stderr.txt`). The model on that record is `Synthetic 1`, from `kernel/live-rig/fixtures/hosts/template.json`.

## Gaps

What this cloud run did not measure:

- A real host. No live key was set. Agent CLIs on `PATH` were refusing stubs. The fixture hosts' status commands were `fake-signed-in` and `fake-signed-out`. Boat, Cloudroom, and the five VPS hosts were not invoked. Their `wait` of 900 seconds was not timed.
- Whether a signed-in `local` run reaches 5 of 5, and how many whole seconds that record would store. The 21 seconds above are the fixture template driver with `wait` 8 and `fake-harness`, at this commit.
- `adapters/planted/driver` and `adapters/quoting/driver` are not files at this commit. Those two entries ran the kit, which failed with `No such file or directory` for that relative path (`docs/evidence/2508/stderr.txt`) and stored `seconds` 0. The test suite copies fixture drivers into a throwaway checkout. This measurement did not.
- The BEFORE hand-run counts, heads, and minutes. They are the spec's text in `before.txt`.
- Whether `schedule.json` is installed anywhere outside this repository. Ticket #2509 is the open person ticket that records the first runs.
- A receipt file. `receipt.py` on this run's 5-of-5 record wrote nothing, for the reason above. A receipt for listing `local` from a signed-in run was not produced.
- Harness listing ids. `listings.json` has none. None was added.
