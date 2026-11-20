# Queue and API overload guard

`alarm.py` reads one bounded snapshot of the CI queue and the GitHub API budgets and says whether a non-essential fleet action may start. It makes no network call and cancels nothing. `supply.py` writes that snapshot from the war room collector's `queue` fact ([collector.v1.md](../collector/collector.v1.md)).

```sh
python3 -I tools/ci-overload/supply.py --repository OWNER/NAME --output /abs/private/observation.json
python3 -I tools/ci-overload/alarm.py --repository OWNER/NAME \
  --input /abs/private/observation.json --state /abs/private/pause.json --action merge-batch
python3 -I tools/ci-overload/test.py                  # offline proofs; `Supplier`, `Fleet Scheduled` run slices
```

`alarm.py` prints one JSON decision: exit 0 admits, 1 refuses, 2 is a bad invocation. `supply.py` exits 0 when it wrote an observation, 1 when it couldn't (the guard then refuses as unknown), 2 on a bad invocation. `fixtures/healthy.json` is an example input; it must be at most 60 seconds old (`--max-age`), complete across every page of required jobs, and at most 2 MiB and 10,000 jobs.

## Decisions

| Observation | Decision |
| --- | --- |
| Oldest required queued job waits 300 s or more | alarm, pause |
| REST or GraphQL remaining below 10% of its limit, or an active secondary backoff | alarm, pause |
| Oldest wait 900 s or more, or a pool exhausted | escalation due, pause |
| Missing, stale, partial or invalid input or state | unknown, pause |

While paused, `merge-batch`, `automatic-refresh` and `nonessential-poll` are refused; `completion` and `reconciliation` stay allowed so admitted work can finish. `fleet.sh overload` runs the supplier first when `LAUNCH_FLEET_OVERLOAD_SUPPLY` names it.

The pause is durable: keep one private state path per repository, never in a temporary folder, and keep its `<state>.pending/` journal beside it. A later healthy snapshot never clears it. **There is no resume command:** ask Jake before clearing a pause, and never delete or replace the state to do it. `escalation: due_not_sent` means only that an escalation is due; this tool sends nothing.
