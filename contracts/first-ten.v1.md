# First ten v1

`openwiz.first-ten.v1` records the time from the install line to the first
merged pull request from the user's first fleet. The [JSON schema](first-ten.v1.schema.json)
covers a local `timing` record and a completed `receipt`. The
[synthetic fixtures](fixtures/first-ten/README.md) exercise both forms.
Readers take one UTF-8 JSON object with unique keys and finite numbers.

## Steps and clocks

| Step key | Source value | Event to record |
| --- | --- | --- |
| `install_line_started` | `installer_log` | The installer's log entry for the start of the install line. |
| `setup_done` | `onboarding_state` | Onboarding records setup complete. |
| `harness_signed_in` | `onboarding_state` | Onboarding records sign-in verified for the selected harness. |
| `grill_confirmed` | `onboarding_state` | Onboarding records the user's confirmation of the grill summary. |
| `plan_approved` | `onboarding_state` | Onboarding records that the first fleet's plan is approved. |
| `first_pull_request_opened` | `github_created_at` | GitHub's `createdAt` for the earliest opened pull request from that fleet. |
| `first_pull_request_merged` | `github_merged_at` | GitHub's `mergedAt` for the earliest merged pull request from that fleet. |

Each step carries its `source` and its time. The install step gives UTC Unix
milliseconds as `at_unix_ms`. The next five give `elapsed_ms` since that start.
The merge step gives `total_ms`, which is both its offset and the receipt total.
A step's UTC time is the start plus its offset. Convert source times to
milliseconds at their recorded precision and subtract the original install
time. The clock includes waits and resumes.

The writer verifies the source and keeps the first recorded time when a mark
is repeated. The two GitHub events can come from different pull requests.
Use the actual GitHub timestamps and exclude setup pull requests and work
outside the first fleet. Record the steps in table order. Offsets must be
nondecreasing and may be equal. A missing source or an earlier timestamp
leaves the run incomplete. Readers check this order in addition to validating
the schema, which cannot compare offsets across fields.

## Budgets

The quick grill targets about **120 seconds of the user's time**, from the
first quick question through confirmation. Surface that budget in the grill
as `quick_grill_budget_seconds: 120`. This is a target, while the full run
clock includes every wait. The approved tiny fleet has one to three tickets,
each size `S`. Store one `S` per ticket in `ticket_sizes` with the plan mark.

## Timing file

The timer writes `first-ten/timing.json` under the
[OpenWiz state directory](service.v1.md#the-state-directory). It uses the
existing absolute `OPENWIZ_STATE_DIR` override or the platform default.
The state directory and `first-ten/` are owner-only (0700). The file is a
regular file owned by the current user with mode 0600. The path stays outside
every repository. Check these properties on disk and refuse symlinks and
unsafe locations. Write complete snapshots atomically with the same ownership
and permissions. The default tracker view is unavailable when the file is
missing or unreadable.

The file has `kind: "timing"` and holds the contiguous prefix of observed
steps, starting with the install event. Add OS and candidate metadata when
known and the ticket sizes by plan approval. The first-run tracker reads
this snapshot to show the recorded steps and the clock against ten minutes.
PR step times in the snapshot come from GitHub. The file carries timing
facts only, with no credentials, account or repository identifiers, or paths.

## Receipt

A completed JSON receipt has `kind: "receipt"`, `os.name` (`macos` or
`linux`), `os.version`, `candidate_version`, the budget and ticket sizes,
all seven steps and `status`. The version fields are single tokens. The
result is `pass` when `total_ms < 600000` and `fail` at or above 600000.
A missing step, malformed or unreadable receipt, or inconsistent time
cannot count as a pass. A release needs passing receipts for the same
candidate on clean macOS and Linux. The fixture named `under-600s`
in [valid.json](fixtures/first-ten/valid.json) shows the full JSON form.

The timer prints the JSON and a plain-text line for the user to post. The
line uses the fields below in order, separated by a single space. Ticket
sizes are comma-separated. The first time is UTC Unix milliseconds, all the
other times are offsets in milliseconds, and the merge offset is the total.
Times are unsigned decimal integers. The step names imply the source values
in the table. The release gate can reconstruct the JSON fields from the line.

```text
openwiz.first-ten.v1 os=linux os_version=99.1 candidate_version=0.2.0-rc.1 quick_grill_budget_seconds=120 ticket_sizes=S,S,S install_line_started=1800000000000 setup_done=45000 harness_signed_in=90000 grill_confirmed=210000 plan_approved=240000 first_pull_request_opened=400000 first_pull_request_merged=599999 status=pass
```
