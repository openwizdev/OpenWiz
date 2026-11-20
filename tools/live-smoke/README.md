# Live smoke

`smoke.py` is the one live-check runner: it executes a reviewed kit of steps against an installed candidate build and writes a checkpoint and journal; `receipt.py` turns them into the [release candidate](../../contracts/release-candidate.v1.md) contract's `smoke` and risk receipts. A fixture run or dry run is never a live pass. It never publishes, tags, installs a service, changes permissions or pushes. Python 3 on Linux, the candidate's prebuilt programs and the PC kit; no new dependency.

```sh
python3 -I tools/live-smoke/test_smoke.py       # offline proofs; also test_kit.py, test_review.py, test_receipt.py
python3 -I tools/live-smoke/test_fixture.py --cli target/debug/examples/openwiz --fake target/debug/fake-room-cli
```

`test_fixture.py` needs those two prebuilt fixture programs; `--case ready-preview` or `--case queued-send` runs one case.

## The standard sheet

`combined.template.json` declares `"claims": ["install", "json", "send", "new"]` and these ten steps only:

| Claim | Steps | Checks |
| --- | --- | --- |
| `install` | `install_status` | The normal install route's build: `installed`, `packaged`, and the candidate's version, source, target and build |
| `json` | `catalogue`, `inventory`, `show` | `openwiz help --agent` is the accepted catalogue; `openwiz ls --json` is complete; `openwiz show <throwaway> --json` reads it |
| `send` | `send_preview`, `send_once`, `send_lookup` | One message to one throwaway thread, previewed, sent once, read back by op id |
| `new` | `new_preview`, `new_once`, `new_status` | One new Cloud thread in one throwaway project, previewed, created once, read back by op id |

Nothing else a version claims is live-tested by it; the kit's `release.gaps` must list the rest. A kit with no `claims` runs the runner's general features: fleet read-back blocks (reads and an `await` until the fleet's own work shows) and the reviewed `cleanup.py` probe.

## Prepare, offline

Install the candidate first through the normal route into throwaway `--root` and `--state-root` folders. Then, with `umask 077`, outside every Git checkout:

```sh
python3 -I tools/live-smoke/inputs.py --records /private/records/a.json [--records ...] --out /private/run/inputs.json
python3 -I tools/live-smoke/prepare.py --inputs /private/run/inputs.json --out /private/run/kit.json
python3 -I tools/live-smoke/smoke.py --kit /private/run/kit.json --state /private/run/checkpoint --dry-run --candidate /private/run/candidate.json
```

`inputs.py` merges owner-only JSON records of named values copied from existing private records (two values for one name refuse). `prepare.py` replaces each whole JSON string `@name` in the template with that value and prints the kit digest and `scope_sha256`; record the kit digest with the version's standing OK. `--dry-run` checks the whole sheet, the pinned files and that the candidate carries this kit and scope, and runs nothing. Never put a token in the inputs, kit or argv.

The inputs, all from existing records, never guessed: `mode` (`live`, or `fixture` for proofs); `cwd` and `env` (an owner-only folder outside any checkout, and the throwaway install's `OPENWIZ_STATE_DIR`); `python`, `openwiz`, `install_entry` (absolute programs); `install_root`, `install_state`, `install_build`; `release_version`, `release_source`, `release_target`; `artifacts` (every program's path to its verified SHA-256, `smoke.py` included); `source` (clean checkout and head); `expected_catalogue_commands` (from the candidate's source); `send_thread` and `project` (approved throwaways); fresh `send_op` and `new_op`, and the `harness`, `model` and `effort` cloud-options offers; the four `*_checks` objects; and `release` (`scope` with `writes` `{"send": 1, "new": 1}`, no `app_permissions`, `spending_cents` 0; `products`; `coverage` naming only these steps; `risk`; `gaps`).

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
