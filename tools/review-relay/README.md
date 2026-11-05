# Review relay (#559)

`relay.py` is the temporary review/CI door until 0.0.9's events reach their
owner. It reads GitHub over REST and tells the recorded builder one short
line per event. It never writes GitHub, starts an agent, or merges anything.
The fleet's check-in remains the safety net.

Needs Python 3 (standard library only), an authenticated `gh`, and the full
local CloudRoom `room-cli` on `PATH`. No dependency is added.

```sh
python3 tools/review-relay/test.py  # fakes only; no account or CloudRoom calls

# Live delivery: the orchestrator enables this only on the approved endpoint.
python3 tools/review-relay/relay.py --repo OWNER/REPO \
  --state-dir "$HOME/.local/state/openwiz/review-relay/OWNER/REPO"
```

Success prints nothing, including when it delivered messages. A failed read
or send prints one short reason on stdout and exits 1; raw command output,
tokens, comment bodies and thread content are never printed. Checks stop at
50 seconds, with each child command limited to 10 seconds or the remaining
time. Independent PR reads use at most eight workers. The ready-ticket list
is read in bulk, and overlapping requests for the same REST page share one
response within a check. This bounds a forty-PR, single-page fixture fleet
to 243 GitHub calls (including repository privacy discovery) on either a cold or warm check; ETags alone do not reduce
the call count. A failed check checkpoints successful reads before alerting,
without delivering any event. The fleet's check-in remains the safety net.

## What it follows

- Open PRs with same-repository closing-keyword references in their bodies,
  such as `Closes #41`, `Fixes OWNER/REPO#41`, or
  `Resolves https://github.com/OWNER/REPO/issues/41`. An ordinary mention
  does not qualify. Manual GitHub links without a closing line are outside
  this seam and remain with fleet check-in.
- Open tickets labelled `ready-for-agent`, without `held`, approved on their
  own by the `**Approved on its own by ...:**` record, or listed as
  `ready-for-agent` in their parent's latest `**Plan graph approved by ...`.
  It routes to existing builders; it does not start work or recompute the
  launch gate's plan fingerprint.
- Exactly one `launch-fleet: started, thread ...` or
  `launch-fleet: start checked, thread ..., branch ...` record on the ticket.
  Multiple records, an archive record, an unknown thread, or an archived
  thread are skipped without delivery markers. Hidden active threads are
  included. No builder is guessed.
- `VERDICT: APPROVE|CHANGES at <full current head>` issue comments or
  submitted reviews; findings comments headed `Findings` or `R<number>`;
  other nonempty submitted reviews and inline comments at the current head.
  Blank reviews, pending reviews and explicit old-head feedback are skipped.
- Completed Actions runs at the current head: `success`, `failure`,
  `timed_out`, `action_required` and `startup_failure`. In-progress,
  cancelled, skipped and neutral runs do not announce a red or green result.
  Reruns are separate events, keyed by run id and attempt.

First run delivers existing qualifying events too. Subsequent runs tell
only events without a marker; a comment's changed body is a new event.
All GitHub pages and the thread list must be read successfully before any
tell. One failed or partial read sends nothing from that check. GitHub reads
use ETags and `If-None-Match` when supplied, follow cached pagination on a
304. GitHub's numeric `repositories/<id>/...` links advertise a next page;
the relay constructs that page on the original `repos/OWNER/REPO/...` route,
checking the host, route, page increment and unchanged query filters. It never
follows the advertised destination. A page with no ETag is read normally.
Comments, native reviews and approval records are revalidated each check:
the parent issue's timestamp is not used to skip possible edits. The
[REST guidance](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api)
and [Actions run fields](https://docs.github.com/en/rest/actions/workflow-runs)
describe these transport seams; fixture tests prove the relay's behaviour.

`REVIEW_RELAY_GH_TOKEN`, if nonempty, overrides `GH_TOKEN` for the read-only
GitHub App installation token. Otherwise `gh` uses its normal environment
or saved login. Minting and renewing the App token belong to its existing
owner; this script never asks for, saves or logs a credential.

## State and delivery

Use one absolute state directory per repository, outside any checkout. It
must be owner-only (0700); the atomic state files are 0600. It holds cached
GitHub responses and delivery markers: keep it private and never commit it.
A process lock makes an overlapping check exit quietly. Corrupt state is
an error, never an empty history. Keep the state when updating the code.

Each event/builder marker is saved and fsynced **before** the tell. A failed
or interrupted tell has an uncertain outcome and is not retried: the fleet's
check-in handles it. A crash between marking and sending may miss a fast
notification. This is at-most-once delivery, not a transaction with
CloudRoom. Deleting state replays events, so do not delete it as a retry.

## Install and stop the minute check

The orchestrator creates this loop after the script is merged, on the
operator-designated builder-owning PC hub, using its full local CloudRoom CLI.
Install the script-only check from a Local thread on that hub. A cloud
thread's restricted `room-cli` reaches only its own children and cannot
serve this role directly. Neither deployment nor a live tell was performed
by the fixture proofs. This is the deployment seam confirmed on #559.

On that hub, make a private `review-relay-check.sh` outside the checkout.
Replace the example checkout path and CLI directories below with the hub's
locally supplied absolute paths, and set the repository before installing.
Keep those deployment values private:

```sh
#!/bin/sh
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
cd "$HOME/projects/example" || { echo 'review-relay: checkout unavailable.'; exit 1; }
exec python3 tools/review-relay/relay.py --repo OWNER/REPO \
  --state-dir "$HOME/.local/state/openwiz/review-relay/OWNER/REPO"
```

Create the local script check from that project's orchestrator, using its
actual project id and CLI (verify with `room-cli automation --help`):

```sh
room-cli automation create --project PROJECT_ID --name 'Review relay' \
  --cron '* * * * *' --timezone UTC --script-file "$HOME/review-relay-check.sh"
room-cli automation list --project PROJECT_ID
```

A script-only local loop runs the script every minute with no agent; read a
failure line in Loops → Review. The hub must stay awake. Keep the fleet's
check-in running as the safety net; do not retry an uncertain tell or delete
relay state to recover a missed notification.

Stop the local loop with `room-cli automation pause LOOP_ID --project PROJECT_ID`;
remove it with `room-cli automation delete LOOP_ID --project PROJECT_ID --yes`.
List first to identify the relay's
loop only. Keep its state so resuming does not replay notifications. These
commands are installation instructions, not evidence that a loop is active.

Public `started` and `start checked, branch …` records resolve through the fleet's shared `skills/launch-fleet/scripts/records.py` reader. Exactly one `#N: ` title and matching checked branch is required, or a private `LAUNCH_FLEET_STATE` map bound to this repository. Ambiguous or conflicting identities never receive a message. Keep this tool beside the skills tree. Legacy thread-bearing records are accepted only after a positive repository-privacy read; an unreadable privacy read means public.
