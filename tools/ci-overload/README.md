# Queue and API overload guard

`alarm.py` reads one bounded snapshot of the CI queue and the GitHub API budgets and says whether a non-essential fleet action may start. It makes no network call and cancels nothing. `supply.py` writes that snapshot from one `gh api` read of the repository's active `ci.yml` and `privacy.yml` runs, their jobs and both rate-limit pools (`read_queue.py`, #2882). A job page, run, attempt, status or start it can't establish makes the snapshot incomplete; a run listing or rate-limit read that fails writes nothing. Every read keeps its response headers (`gh api --include`) and one GraphQL `rateLimit` query checks that pool too. A `Retry-After` header or a secondary-limit answer (a 429, a 403 saying so or with no REST left, a GraphQL `RATE_LIMITED` error) stops the read and sets that pool's `retry_after` to the real deadline: now plus `Retry-After`, the primary reset, or GitHub's one-minute minimum. A `RATE_LIMITED` reply counts even though gh exits 1 on it, and a backoff reply's own `x-ratelimit-*` headers become that pool's budget, so its deadline outlives a reset the first `rate_limit` read predates. `retry_after` is 0 only when no response carried a signal; a response without readable headers, a `Retry-After` that isn't seconds, a GraphQL answer without a whole `rateLimit.remaining`, a run or job id repeated within one listing, or a pass longer than the guard's 60-second window (it stops reading there) makes the snapshot incomplete.

```sh
python3 -I tools/ci-overload/supply.py --repository OWNER/NAME --output /abs/private/observation.json
python3 -I tools/ci-overload/alarm.py --repository OWNER/NAME \
  --input /abs/private/observation.json --state /abs/private/pause.json --action merge-batch
python3 -I tools/ci-overload/test.py                  # offline proofs; `Fleet`, `Scheduled` need the installed skills
python3 -I tools/ci-overload/test_supply.py           # the supplier from a clean copy, on a fake gh
```

`alarm.py` prints one JSON decision: exit 0 admits, 1 refuses, 2 is a bad invocation. `supply.py` exits 0 when it wrote an observation, 1 when it couldn't (the guard then refuses as unknown), 2 on a bad invocation. `fixtures/healthy.json` is an example input; it must be at most 60 seconds old (`--max-age`), complete across every page of required jobs, and at most 2 MiB and 10,000 jobs.

## Decisions

| Observation | Decision |
| --- | --- |
| Oldest required queued job waits 300 s or more | alarm, pause |
| REST or GraphQL remaining below 10% of its limit, or an active secondary backoff | alarm, pause |
| Oldest wait 900 s or more, or a pool exhausted | escalation due, pause |
| Missing input file | unknown (refuses this call; does not latch durable pause) |
| Stale, partial or invalid input or state | unknown, pause |

While paused, `merge-batch`, `automatic-refresh` and `nonessential-poll` are refused; `completion` and `reconciliation` stay allowed so admitted work can finish. `fleet.sh overload` runs `LAUNCH_FLEET_OVERLOAD_SUPPLY` when set; when neither it nor `LAUNCH_FLEET_OVERLOAD_INPUT` is set, the guard gets no input and refuses new work as unknown.

The pause is durable: keep one private state path per repository, never in a temporary folder, and keep its `<state>.pending/` journal beside it. A later healthy snapshot never clears it (there is **no automatic resumption**). Once the operator confirms the overload is resolved, clear the durable pause and its pending journal under the state lock with `python3 -I tools/ci-overload/alarm.py --repository OWNER/NAME --state /abs/private/pause.json --action resume` (or `fleet.sh overload resume`), rather than deleting files manually. `escalation: due_not_sent` means only that an escalation is due; this tool sends nothing.
