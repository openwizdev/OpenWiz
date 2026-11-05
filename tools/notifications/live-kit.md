# 0.0.15 notification live kit — prepared offline, not yet approved

T7 #2039 prepares this kit and tests it on fixtures. **T8 #2040 runs it**, and
only after Jake's version-level live-kit OK (ADR 0016) is saved on #2040 and
read back. Before that OK, only the offline commands below may run. Graph,
ticket or label approval grants no live step. This kit buys nothing, adds no
dependency or credential, widens no access, creates no fleet, and merges, tags
or publishes nothing. If any of those is needed, stop and return for an
explicit decision.

## Prerequisites (any missing one stops the run before step 1)

- **T2 #2033's observed delivery binding is merged** and the installed
  candidate's delivery adapter uses it. Until then the installed adapter
  reports `unsupported`, step 1 stops, and PA8 stays Unverified.
- **The exact installed candidate**: version `0.0.15`, plus the head and tree it
  was built from, read from `openwiz-service --build-identity` and checked against
  private install records. A version string alone proves no commit.
- **An existing isolated test installation** of that candidate: its own state
  directory, so its own notification preferences and subscription, and never
  the owner's normal installation. The plan names it (`installation`) and binds
  three existing private records: `provenance` (the install record naming its
  state directory, distinct from the normal installation's), `local_status`
  (where step 1 saves its root-scoped local status) and `origin_route` (the
  access routing record that maps `origin` to that engine host's loopback
  `port`). If any link is missing or does not match, or the installation is
  normal, shared or uncertain, stop before any write and revise the kit. Never
  provision one.
- **Designated throwaway resources**, named in the private plan and reused, never
  provisioned: one decision subject (an issue in the test installation's
  repository); one health source that the existing recovery policy has
  escalated or will escalate; one optional category whose source the contract
  lists as available; one answer thread, which must be the test installation's
  configured answer target; one stock project, with the exact test ticket in it
  and the exact ready label that step 13 removes; one browser context, and one
  supported phone if one is available. If one is unavailable, stop and revise
  the kit. Never create a replacement.
- **The test installation's current choices**, read once and kept privately:
  notification `enabled` and `categories`, their generation, and the
  subscription state. Cleanup writes back the same `enabled` and `categories`.
  The generation only moves forward, so it is never rolled back.
- **A private effect log** of this run's own confirmed effects: each comment it
  created, whether it created the test subscription, whether it removed the
  stock label, and the generation and values that its last successful
  preference write returned. Status reads never change this log.

## The plan and the binding

Copy this template into an owner-only directory **outside Git** and replace
whole JSON values. Real hosts, accounts, resource names and evidence stay
private. The nulls are there to make the template refuse until it is filled in.

```live-kit-plan
{
  "schema": "openwiz.notification-live-kit-plan.v1",
  "candidate": {"version": "0.0.15", "head": null, "tree": null},
  "engine_host": null,
  "origin": null,
  "delivery_binding": null,
  "installation": {
    "kind": null, "state_owner": null, "port": null,
    "provenance": null, "local_status": null, "origin_route": null
  },
  "resources": {
    "decision_subject": null, "incident_source": null,
    "optional_category": null, "answer_thread": null,
    "stock_project": null, "stock_ticket": null, "stock_label": null,
    "browser_context": null
  },
  "phone": {"availability": "unknown", "device": null, "gap": null},
  "caps": {
    "notification_submissions": 4, "github_records": 1, "github_comments": 4,
    "cloudroom_sends": 1, "cloudroom_starts": 0, "test_answers": 1,
    "engine_restarts": 1, "cleanup_actions": 6, "elapsed_seconds": 1800
  },
  "bounds": {"api_reads": 40, "request_s": 10, "response_bytes": 65536, "retries": 0},
  "forbidden_effects": {
    "normal_preference_changes": 0, "merges": 0, "tags": 0, "purchases": 0,
    "publications": 0, "access_changes": 0, "blind_retries": 0
  },
  "privacy": "owner-only-sanitized",
  "stop": "first-refusal-no-retry",
  "result_schema": "openwiz.notification-live-result.v1"
}
```

`origin` is the authenticated HTTPS cockpit origin, exactly `https://host`
(optionally with a port), of the test installation. `installation.kind` must be
`isolated-test`; `state_owner` names its private state directory's owner record,
`port` its loopback port, and `provenance`, `local_status` and `origin_route`
the private records step 1 checks. `decision_subject` and `stock_ticket` are exact
`owner/repo#number` references, and `stock_label` is the exact label step 13
removes and cleanup restores. `delivery_binding` names T2's merged binding record.
`phone.availability` is `available`, with a device and a null gap, or
`unavailable`, with a null device and a gap. `unknown` refuses. The caps above
are the approved maximums, and a plan with different caps refuses.

Run only these **offline** commands from the checkout:

```sh
python3 -I tools/notifications/test_live_kit.py
python3 -I tools/notifications/test_live_kit.py --check-kit /private/run/live-kit-plan.json
```

`--check-kit` reads only the named plan and this file. It contacts nothing and
runs nothing. Exit 2 means refused, with no input echoed. Exit 0 prints
`offline_valid_for_review`, the plan's canonical SHA-256, `live_authority:
false`, `phone_display: Unverified`, and the **binding**: the candidate, this
file's SHA-256 (`kit_sha256`) and the caps. Save the binding privately. Jake's
OK must name the kit commit, `kit_sha256`, the plan digest and the candidate.
Any change to any of them needs a new OK. After the run,
`--validate RESULT --binding BINDING` (#2231) checks the result record against
that binding.

## Steps after the OK — T8 #2040 only

Run each step once, in order. Every count goes in the private step log, and
together they never exceed the caps. API reads use the discovery kit's reviewed
HTTPS curl argv (`discovery-kit.md`): GET only, 10 s and 64 KiB per response,
no redirects or retries. They go only to the routes named here and count
toward `api_reads`. To wait for an engine pass, re-read status at most once per
configured pass interval, within `elapsed_seconds`. Never use a watcher or a
loop with no limit.

| # | Step | Expected, and the stop rule |
| --- | --- | --- |
| 1 | On the engine host, run `openwiz-service status --json` with `OPENWIZ_STATE_DIR` set to the state directory that `provenance` names, and save it as `local_status`. Check that its `server.port` is the plan's `port` and its build is the candidate head, and that `origin_route` maps `origin` to that host and port. Then read `/api/v1/health` and `/api/v1/notifications/status` through `origin` | Every link matches. If any is missing or differs, or status is `unsupported`, `unavailable` or a permission state, stop before any write |
| 2 | In the named browser context, use the cockpit's **Enable** action once: one permission prompt and one test subscription. Leave default categories | Status becomes `ready`, with zero submissions. Ready means the prerequisites were checked, not phone receipt |
| 3 | Post one structured test decision request (`contracts/decisions.v1.md`) on the decision subject. Close the cockpit | Exactly **1 submission**; dispatch `accepted` |
| 4 | Phone, if available, before anything changes the step-3 request: with the cockpit still closed, see the step-3 alert displayed in the background, then tap it | The bound current decision card opens. Record display and tap separately, and an unavailable phone as its own gap. Emulation, an open-page toast or accepted dispatch never counts |
| 5 | Wait until the existing recovery policy escalates the designated health source. The kit adds no recovery action | **1 submission**. A failed run or an active repair stays quiet |
| 6 | Let the sources be read again for 2 passes, then restart the engine **once** | **0 new submissions**: repeats and the restart stay grouped |
| 7 | With default categories, let one routine event occur on the stock project (for example a test ticket label read) | **0 submissions**: routine progress stays quiet |
| 8 | Turn on only the named optional category, as a test choice. Let one event occur | **1 submission**. If its source is unavailable, record the gap: 0 submissions, no substitute |
| 9 | Open the step-3 alert through authenticated access in the browser context | The exact current decision card opens. Zero sends, starts or merges |
| 10 | Post one changed proposal on the same subject (a new request id), and mark the step-3 request `superseded` (2 comment writes). Open the old step-3 alert again | **1 submission** for the new proposal. The old reference shows "changed" or "resolved" and cannot answer |
| 11 | Answer the new proposal **once** from its card, with explicit confirmation, to the answer thread. Tap twice, then reload. Then mark that request `resolved` (1 comment write) and open its alert | **1 CloudRoom send** and its receipt are read back. A duplicate cannot send. The resolved alert cannot answer |
| 12 | Revoke the test permission or subscription; let one eligible observation occur; reconnect with Enable once | While revoked, 0 submissions and status `permission_revoked`. After reconnect, no replay of anything earlier |
| 13 | Check that the plan's stock ticket is open, in the stock project and has the stock label. Read the cockpit stock, remove that label from that ticket (1 record change) and read again | Shows ready stock, then running dry or low stock. Stale or partial reads keep their age and gaps. If the ticket or label does not match, skip the change and record the gap |

Stop at the first refusal, mismatch, uncertain outcome or exceeded count. Do not
retry, provision anything, or try another endpoint or account. Keep any partial
evidence and go straight to cleanup.

## Cleanup (at most 6 actions)

Each action is taken only for an effect the effect log records as confirmed,
and only taken actions count toward `cleanup_actions`. Do them in this order:

1. If this run confirmed removing the plan's stock label in step 13, put that
   label back on the plan's stock ticket. A skipped, absent or uncertain
   removal gets no label write.
2. If this run created the step-10 comment, delete it.
3. If this run created the step-3 comment, delete it.
4. If this run created the test subscription, remove it
   (`DELETE /api/v1/notifications/subscription`).
5. If this run wrote preferences, first read them. They must equal exactly the
   generation and values that this run's last successful preference write returned.
   Then write back the saved `enabled` and `categories` once, with a fresh
   operation id and that generation as the expected generation. Read the
   result: it must equal the saved values at that generation plus one.
6. If this run opened tooling, close only that tooling.

If the current preferences differ in any way from that recorded write, someone
else changed them. Stop without writing, and record cleanup as incomplete. A
refused or uncertain cleanup action, or an uncertain earlier effect, is also
incomplete; never retry it or guess. Start nothing and leave no watcher.
Remove only test-owned resources; never touch any other subscription, record
or work.

## Evidence

Keep raw evidence owner-only (directory 0700, files 0600), outside public Git.
Never record cookies, auth headers, subscription endpoints or keys, decision
wording or thread ids. Write the sanitized result in the
`openwiz.notification-live-result.v1` shape (`live-kit-result.schema.json`) and
check it with `--validate` against the saved binding. A missing phone or
native Mac observation, or incomplete cleanup, is a named gap. It is never a
pass, and never a new manual gate. Delivery that was submitted or accepted
does not prove the phone displayed it. The release's native Mac check stays as
it is. ADR 0018 lets this check run before earlier versions publish, while
publishing stays in version order and needs its own authority.
