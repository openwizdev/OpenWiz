# Daily factory numbers

`metrics.py` reports one completed UTC day of a repository's factory: merges per hour, recorded idle agent-minutes, the biggest stall and costs. It writes only aggregates (`report.json`, `report.md`, `factory.svg`) to a new output directory and never writes to GitHub or runs `room-cli`. Python 3 standard library and `gh` (the App's token in `GH_TOKEN` when available; never on the command line).

```sh
python3 tools/collector/metrics.py --date 2026-11-01 --repo OWNER/REPO --out /tmp/factory-2026-11-01 [--usage DAILY.json]
python3 tools/collector/test_metrics.py        # proofs on a fake gh; FACTORY_METRICS_PY=variant.py for a negative check
```

Exit 0 reported (some costs may be unknown), 1 untrustworthy records or I/O failure, 2 bad arguments.

## What the numbers mean

- **Merged PRs:** every PR merged in the UTC day, on any base branch, in 24 hourly buckets.
- **Recorded idle agent-minutes:** a `launch-fleet:` record starting `findings sent`, `CI failure sent`, `merge blocked` or `review started` opens a gap; the next fleet record on that PR or its closing tickets, or the PR's merge or closure, ends it. Gaps are clipped to the day and add across tickets, so an hour can exceed 60. Ordinary comments, commits and CI results are not records.
- **Biggest recorded stall:** the longest single gap within the day; `stalls` in the JSON keeps them all.
- **Costs:** the day's reported usage by provider and unit, and each known total divided by that day's merges (not an attribution of work to PRs). Units are never added or converted; the USD total is unknown unless every part reports USD. Actions costs are GitHub's reported billing minutes and net USD for the day, unknown if billing can't be read.

History is incomplete by nature: edits, deleted comments and changed links can't be recovered, so never present idle time as complete. Any failed or partial GitHub read refuses the report rather than dropping records.

`--usage` takes an optional daily CloudRoom export in this tool's own format (`complete: true` asserts it covers every factory thread and sandbox hour that day; a unit missing on any thread makes that provider's total unknown):

```json
{"date": "2030-01-02", "complete": true,
 "claude": [{"thread": "synthetic-a", "tokens": 1000, "credits": 2, "usd": 1}],
 "gpt": [{"thread": "synthetic-c", "tokens": 6000, "credits": 9, "usd": 6}],
 "sandbox": {"hours": 6, "usd": 3}}
```

## First-successful-push receipt

Before the first push, choose a private durable `receipt_file` outside the checkout and record its path in private resumable state. Immediately after the first push succeeds, capture its time and head once; a failed push records nothing.

<!-- EB6 capture -->
```sh
git push origin HEAD &&
push_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) &&
push_head=$(git rev-parse HEAD) &&
printf 'First successful push: %s at %s\n' "$push_head" "$push_at" > "$receipt_file"
```

Never replace that receipt on later pushes or fixes. After opening the PR, set `pr` to its number, post the file and read the comment back; before retrying a failed post, read the PR's comments and reuse an identical receipt. Never rebuild a lost receipt from other timestamps: it stays unknown.

<!-- EB6 receipt -->
```sh
gh pr comment "$pr" --body-file "$receipt_file"
```

## Ticket journeys, outcomes and stage waits

`journey.py` collects one sanitized record per ticket, from grill to merge; its rules are in [journey-contract.md](journey-contract.md).

```sh
python3 -I tools/collector/test_journey.py
python3 -I tools/collector/journey.py collect --repo OWNER/REPO --ticket N [--with-outcomes] [--stage-waits] [--previous DIR] [--defect-policy FILE] --out DIR
python3 -I tools/collector/journey.py bench DIR/journeys.json [--outcomes DIR/outcomes.json] [--stage-waits DIR/stage-waits.json] [--settings LIMITS.conf]
```

- `--with-outcomes` adds `outcomes.json` (per-PR outcomes, first-push receipts and defects). `--previous DIR` resumes and never drops an established observation.
- `--defect-policy FILE` declares the defect rule (`rule: explicit-causal-fix-link-v1`, positive `followup_hours`, `deduplication: root-cause-per-merge`, `unknown_attribution: retain-unknown`); without one, defects are unknown, never zero. A curator records defects as one-line comments on the causing PR, below (`policy` is the policy's digest, `root` the defect issue). The collector verifies each cited CI run attempt or merged fix but can't establish cause: `attributable` needs the source's explicit judgment, else record `unknown` and resolve it later with an `EB attribution:` line.

```text
EB defect: {"policy":"<64 hex>","root":4901,"at":"2030-01-02T07:00:00Z","attribution":"unknown","evidence":"https://github.com/example/factory/actions/runs/7901","kind":"main-red","caused_by":4201}
EB defect: {"policy":"<64 hex>","root":4901,"at":"2030-01-02T09:00:00Z","attribution":"unknown","evidence":"https://github.com/example/factory/issues/4901","kind":"later-defect-fix","caused_by":4201}
EB attribution: {"policy":"<64 hex>","root":4901,"at":"2030-01-06T06:00:00Z","attribution":"attributable","evidence":"https://github.com/example/factory/pull/4201#issuecomment-8901"}
EB follow-up: {"policy":"<64 hex>","observed_until":"2030-01-04T06:00:00Z"}
```

- `--stage-waits` writes `stage-waits.json`; `bench --stage-waits` reads each wait against [limits.conf](limits.conf) as missed, not missed, pending or unknown. Edit `limits.conf` and re-run `bench` to see new goals without collecting again.

```sh
python3 -I tools/collector/limits.py [--settings FILE]     # the five stage limits in force, in minutes
python3 -I tools/collector/test_limits.py
```

[limits-contract.md](limits-contract.md) has the settings grammar; any bad setting refuses the whole read. A missed limit authorises no action.
