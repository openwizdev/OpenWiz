# Live smoke

`smoke.py` is the one live-check runner: it executes a reviewed kit of steps against an installed candidate build and writes a checkpoint and journal; `receipt.py` turns them into the [release candidate](../../contracts/release-candidate.v1.md) contract's `smoke` and risk receipts. A fixture run or dry run is never a live pass. It never publishes, tags, installs a service, changes permissions or pushes. Python 3 on Linux, the candidate's prebuilt programs and the PC kit; no new dependency.

```sh
python3 -I tools/live-smoke/test_smoke.py       # offline proofs; also test_kit.py, test_review.py, test_receipt.py
python3 -I tools/live-smoke/test_fixture.py --cli target/debug/examples/openwiz --fake target/debug/fake-room-cli
```

`test_fixture.py` needs those two prebuilt fixture programs; `--case ready-preview` or `--case queued-send` runs one case.

## The standard sheet

`combined.template.json` declares `"claims": ["install", "json", "new", "send", "app"]` and these twelve steps only:

| Claim | Steps | Checks |
| --- | --- | --- |
| `install` | `install_status` | The normal install route's build: `installed`, `packaged`, and the candidate's version, source, target and build |
| `json` | `catalogue`, `inventory`, `show` | `openwiz help --agent` is the accepted catalogue; `openwiz ls --json` is complete; `openwiz show <throwaway> --json` reads it |
| `new` | `new_preview`, `new_once`, `new_status`, then the teardown `driver_stop`, `stop_status` | The pinned Cloudroom driver (KN4) answers `version`; `start` runs once (up to 130 seconds) on the throwaway repository, ticket and project; `room-cli thread show <thread> --json` reads its one thread back, live, in that project. The teardown stops every run in the run's own `OPENWIZ_CLOUDROOM_STATE` (up to 130 seconds) and reads each thread back archived |
| `send` | `send_once`, `send_ack` | The driver's `wake` once, to the run `new_once` started, then its wake message read back once from that thread's chat (`room-cli thread log`) within 60 seconds |
| `app` | `app_repositories` | `gh api /installation/repositories` with the App token: exactly one repository, the approved one |

The wrapper's `status` reads `thread show --json` and takes a thread as archived when it has `archived: true` (Cloud) or a numeric `archivedAt` (Local, inside `{"thread": {...}}`); `ack` reads `thread log` as text on purpose, counting the wake message.

Every driver step runs through one inline wrapper (the pinned `@python`), which refuses before any dispatch unless `OPENWIZ_CLOUDROOM_STATE` is set, `ROOM_PROJECT_ID` is unset or the approved `project`, and `room-cli` on PATH, with the pinned `room_cli`'s folder put first, is that pinned file (the driver then uses it too). `new_preview`, a read before any write, refuses unless that driver folder holds no run and `cwd` no earlier `driver-run.json` or `driver-claim.json`, so a reused folder ends the run before any attempt is journaled; `start` checks again and, while it holds that shared folder, refuses with `same_request` when the folder already has a run for this request that this start did not create. Otherwise it writes `driver-claim.json` (the exact request) before it asks the driver, and then records there only the run ids that appeared for that request during that start. Teardown steps run after any ending once a write was tried, and after they run no other step does; they stop and read back only the runs `driver-claim.json` names (or, if the wrapper was cut off before recording them, the folder's runs with exactly that request), so with no claim they stop nothing. **Recovery, from the start attempt on:** run the same `--execute` command again; it re-runs only an unfinished teardown. If that still does not pass, read `driver-claim.json` in the run's `cwd`: no file means the start never reached the driver, so nothing is stopped. Otherwise, for each run id it lists (or, with no `runs` list, each `run-*.json` in the run's `OPENWIZ_CLOUDROOM_STATE` whose saved `request` equals the claim's), send `{"run": "<that id>"}` to the driver's `stop`, which reaches a thread it never saved by its title, then check `room-cli thread list --json --include-archived` shows that run's thread archived (`archivedAt` set on a Local `room-cli`, `archived` on the Cloud one). Never stop any other run in that folder. PC hands records each of these in the run's private record.

Nothing else a version claims is live-tested by it; the kit's `release.gaps` must list the rest. A kit with no `claims` runs the runner's general features: fleet read-back blocks (reads and an `await` until the fleet's own work shows) and the reviewed `cleanup.py` probe.

## Prepare, offline

Install the candidate first through the normal route into throwaway `--root` and `--state-root` folders. Then, with `umask 077`, outside every Git checkout:

```sh
python3 -I tools/live-smoke/inputs.py --records /private/records/a.json [--records ...] --out /private/run/inputs.json
python3 -I tools/live-smoke/prepare.py --inputs /private/run/inputs.json --out /private/run/kit.json
python3 -I tools/live-smoke/smoke.py --kit /private/run/kit.json --state /private/run/checkpoint --dry-run --candidate /private/run/candidate.json
```

`inputs.py` merges owner-only JSON records of named values copied from existing private records (two values for one name refuse). `prepare.py` replaces each whole JSON string `@name` in the template with that value and prints the kit digest and `scope_sha256`; record the kit digest with the version's standing OK. `--dry-run` checks the whole sheet, the pinned files and that the candidate carries this kit and scope, and runs nothing. Never put a token in the inputs, kit or argv.

The inputs, all from existing records, never guessed: `mode` (`live`, or `fixture` for proofs); `cwd` (an owner-only folder outside any checkout; the driver steps keep their run id in `driver-run.json` there, so each run needs a fresh one); `env` (the throwaway install's `OPENWIZ_STATE_DIR` and a new, empty, owner-only `OPENWIZ_CLOUDROOM_STATE` for this run alone; run it from a Cloudroom thread of the throwaway project, or with `ROOM_PROJECT_ID` unset); `python`, `openwiz`, `install_entry`, `driver` (the merged Cloudroom driver), `room_cli` (a file named `room-cli`) and `gh` (absolute programs); `install_root`, `install_state`, `install_build`; `release_version`, `release_source`, `release_target`; `artifacts` (every program's path to its verified SHA-256, `smoke.py` included); `source` (clean checkout and head); `expected_catalogue_commands` (from the candidate's source); `send_thread` (the approved throwaway thread `show` reads), `project`, `driver_repository` and `driver_ticket` (the approved throwaway project, repository and ticket), and `driver_skill`, `harness` and `model` for the one start; `app_repository` (the one repository the App's installation may reach); and the release section's `release_targets`, `release_products`, `release_gaps` and the `promise_install`, `promise_drivers` and `promise_app` names from the curated notes. The template fixes the rest of the release section: `writes` `{"send": 1, "new": 1}`, no `app_permissions`, `spending_cents` 0, and every `risk` step in a `coverage` row. `new_once` alone waits up to 130 seconds, past the driver's 100 for `room-cli`; every other step keeps the kit's `timeout_seconds` (at most 70), and only a write step may set its own.

It refuses, before any step: port 7370 or a launch that would default to it (`reserved_port`: my.openwiz.dev's server on the PC); `openwiz fleet tick` in any form or `openwiz engine` (`retired_command`); fixture environment variables or tokens in a live kit.

## Run and resume

The Local PC agent, after the version's standing OK, runs and re-runs the same command:

```sh
python3 -I tools/live-smoke/smoke.py --kit /private/run/kit.json --state /private/run/checkpoint --execute APPROVED_KIT_SHA256 --candidate /private/run/candidate.json
```

Every resume must give the same candidate; a rebuilt candidate needs a new state directory, and a run without `--candidate` yields no receipts. A write's attempt is saved before it is sent, so any interruption consumes it: resume reports `uncertain_write` and never sends again. Reconcile it by lookup or status; never edit the checkpoint to retry. Writes beyond `release.scope.writes` refuse (`write_limit`). A fleet block ends the turn at its `event` (`next_event`) and resumes on the fleet's own event, capped at 60 sittings and three hours (`fleet_limit`).

Exit 0 with `evidence: live` and every claim `pass` is a live pass. 1 is a wrong comparison, 2 a refused input or artifact (including a bad PC bundle, `bundle_preflight`), 3 incomplete, uncertain or at the cap; each blocks the gate. The report holds only claim states, counts, hashes and fixed reasons, never raw output, ids, paths or credentials.

## Receipts

```sh
python3 -I tools/live-smoke/receipt.py produce --kit KIT --state CHECKPOINT --candidate CANDIDATE --record "$RECORD_POINTER"   # the run's private-record comment URL
python3 -I tools/live-smoke/receipt.py check --gate smoke --receipts receipts.json --candidate CANDIDATE --kit KIT --state CHECKPOINT
```

`produce` binds the candidate, artifacts, kit, scope and the hash-chained `journal.jsonl`, and prints a `preserve` line to post in the run's private record. Coverage must have one row per included promise whose notes say `Live-checked`; every other promise goes into `gaps` as not live-checked. `check` accepts only a `live` `pass` receipt for this exact candidate that the evidence reproduces now and whose private record carries the `preserve` line, created after the run; anything else names its reason (`stale`, `not_live`, `coverage_mismatch`, `evidence_unresolved` and so on). A PC run is never a Mac or real-device observation.
