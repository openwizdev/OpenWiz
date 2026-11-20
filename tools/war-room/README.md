# War room

The factory's dashboard: every five minutes a sample of every bench is saved to the `war-room` branch, and every hour a small static site and two pictures are drawn from the latest sample and published there. Records follow the collector's [v1](../collector/contract.md) and [v2](../collector/contract.v2.md) contracts. Python 3 standard library; the build-time charts need Node 24 and the locked Observable Plot ([dependencies.md](dependencies.md)); pictures and browser proofs need Chromium.

```sh
npm ci --ignore-scripts --prefix tools/war-room     # once, for the charts (node_modules/ is ignored)
python3 -I tools/war-room/publish.py preview --out /tmp/war-room --at 2030-01-02T12:03:00Z   # a synthetic page
python3 -I tools/war-room/test_publish.py           # each piece's proof is below; war-room-proof.yml runs most on pull requests
```

Fixtures prove the code offline; live collection, publication and the phone view are unverified until the orchestrator activates them.

## The pieces

| File | What | Proof |
| --- | --- | --- |
| `gather.py` | Reads every live source once (board history and credits, current CI, journeys, rework, cost, stage waits, health) into a private source root and a pinned selection. A failed source greys only its own card; any privacy hit refuses the whole gather | `test_gather.py` |
| `sources.py` | `select(root, selections, at)`: reads only explicit local files pinned by SHA-256, with their observed time and GitHub evidence; also the board readers | `test_page_history.py` |
| `main.py`, `history.py` | One tick: floor the time to five minutes, compose every slot, save the sample create-if-absent (identical repeats are no-ops, different payloads refuse), render | `test_page_history.py` |
| `page.py`, `benchmarks.json` | The site: home (every bench, worst first) and Speed, Health, Cost, Quality, Skills pages; no script. `benchmarks.json` gives every bench and chart exactly one home figure, or the page refuses | `test_site.py`, `test_page_design.py` |
| `charts/` | Build-time SVG figures; see [charts/contract.md](charts/contract.md) | `test_charts.py` |
| `rework.py`, `answer_time.py`, `cost.py`, `review_loops.py` | Project validated sources into their provider slots; unknown stays grey, never zero | `test_rework.py`, `test_answer_time.py`, `test_cost.py`, `test_review_loops.py` |
| `weekly.py` | Compares two adjacent seven-day stage cohorts from history; prints only | `test_weekly.py` |
| `web/serve.py` | Serves the published site privately on loopback; see [web/contract.md](web/contract.md) | `test_web.py` |
| `budgets.py`, `budgets.tsv` | CI job timeouts from measured run times | `test_budgets.py` |
| `assets/` | The headings font and its provenance | |

```sh
python3 -I tools/war-room/gather.py --remote "$REMOTE" --repo "$OWNER_REPO" --run-url "$RUN_URL" --out "$NEW_DIR"
python3 -I tools/war-room/main.py --at "$UTC" --source-root "$SOURCES" --selection "$SELECTION" --history "$HISTORY" --page "$PAGE"
python3 -I tools/war-room/charts/build.py --history "$HISTORY" --at "$UTC" --out "$CHART_DIR"
python3 -I tools/war-room/weekly.py --history "$HISTORY" --at "$UTC"
python3 -I tools/war-room/review_loops.py check-report tools/war-room/fixtures/review-loops/report-ok.md
python3 -I tools/war-room/review_loops.py --help        # bench, check-report, compare and project
```

`gather.py` also takes `--data-remote URL` (read the `board` branch from another repository, read-only, depth 1; `--repo` still names every `gh` read), `--pool LABEL` (repeatable), `--stage DIR`, `--journeys FILE` with `--cohort FILE`, and `--answer-time FILE`. `charts/build.py` also takes `--source-root` and `--selection`. `weekly.py` also takes `--changes FILE` and `--format json` or `markdown`.

## Publish

`.github/workflows/war-room.yml` runs on GitHub-hosted `ubuntu-24.04`. A pull request runs `preview` only. A dispatched or scheduled run from `main` runs `publish.sh`, which runs `test_publish.py`, gathers, and `publish.py publish`: one tick, the six pages, `war-room.html`, `war-room.png` (1440 px), `war-room-phone.png` (390 px at 2x) and a `README.md`, privacy-scanned and pushed without force to `refs/heads/war-room` only. A failed test, read, render, scan or push publishes nothing, so the branch keeps its last good site. Samples on the branch are never changed or removed.

**Off by default.** It publishes only while the repository variable `WAR_ROOM_PUBLISH` is `on`. The orchestrator activates it, and the two script-only loops, which print nothing unless a run fails:

```sh
gh variable set WAR_ROOM_PUBLISH --body on --repo jparker2006/ClosedWiz      # --body off to stop
room-cli loop create --name 'War room collect' --cron '*/5 * * * *' --timezone UTC --new-thread \
  --script 'python3 -I tools/war-room/publish.py collect --remote https://github.com/jparker2006/ClosedWiz.git --gather jparker2006/ClosedWiz https://github.com/openwizdev/openwiz/issues/626 >/dev/null 2>&1 || echo "War room collection failed"' \
  --prompt 'The War room five-minute collection failed. Read the error, report it, change nothing.'
room-cli loop create --name 'War room hourly' --cron '37 * * * *' --timezone UTC --new-thread \
  --script 'gh workflow run war-room.yml --repo jparker2006/ClosedWiz --ref main >/dev/null 2>&1 || echo "War room dispatch failed"' \
  --prompt 'The War room hourly dispatch failed. Read the error, report it, change nothing.'
```

Give each loop only its credential (`--secrets`): the collector needs contents write on `war-room` and actions, issues and pull-requests read; the hourly loop only dispatches. A backup cron (`37 */6 * * *`) keeps the page within six hours. Each publish is about a minute of hosted Linux time and adds the pictures to the branch history.

To check a live collection, over three boundaries `git log --format=%cI --name-only refs/heads/war-room -- samples` should show one new sample each, none rewritten.

## Serving

```sh
python3 -I tools/war-room/web/serve.py fetch --remote https://github.com/OWNER/PRIVATE.git --into DIR   # hourly, after the publish
python3 -I tools/war-room/web/serve.py serve --root DIR --port PORT                                    # always on, loopback only
```

It answers only `GET` and `HEAD` for the six routes on `127.0.0.1`, behind the existing tunnel and Access login; `fetch` keeps the last good site unless the new one is complete. Switching a host to it waits for the orchestrator's go-ahead.

## CI time budgets

Each marked CI job has a timeout per mode (normal, traced, planted) in `budgets.tsv`: `ceil(1.5 × p95 / 60)` minutes with a five-minute floor, from at least five eligible runs. Refresh from real runs, keeping the downloads out of Git:

```sh
python3 -I tools/war-room/budgets.py collect --workflow ci.yml --runs 150 --since UTC --out /tmp/budget-window
python3 -I tools/war-room/budgets.py collect --workflow privacy.yml --runs 150 --since UTC --out /tmp/budget-window
python3 -I tools/war-room/budgets.py table /tmp/budget-window --out /tmp/budgets.tsv [--derive rust=rust-export web=web-export] [--unmeasured JOB:planted=MINUTES]
python3 -I tools/war-room/budgets.py check
```

`table` writes each planted row's samples to `<table-stem>.samples.json`; keep it beside the table. With fewer than five samples, generation fails unless `--unmeasured` records the authorised limit: under the [C8 ruling](https://github.com/openwizdev/OpenWiz/issues/1097#issuecomment-6967769682) undersampled planted rows keep 90 minutes, marked unmeasured.
