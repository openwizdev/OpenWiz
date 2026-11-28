# Usage v1 (`openwiz.usage.v1`)

A lane is one harness account on one driver or one host plan. A successful
driver `usage` reply and the merged usage JSON use the same response object,
`{"schema":"openwiz.usage.v1","lanes":[...]}`. An empty `lanes` array means there
are no lanes to report. Each lane id appears at most once in a response. The
[JSON Schema](usage.v1.schema.json) checks a response or a single history record
through its `response` and `lane` definitions.

## Lane readings

| Field | Meaning |
| --- | --- |
| `lane` | Stable `<driver>:<harness or plan>:<account label>` id, such as `local:claude:demo`. Use the owner-chosen label from [settings v1 `accounts`](settings.v1.md#fields) for harnesses. For a host plan, use `plan` and a stable public plan label such as `demo`. |
| `label` | The public display label. For a harness, use the owner's account label. |
| `driver` | Driver name, equal to the first segment of `lane`. |
| `source` | Name of the meter command, such as `boat limits`. Use the reader's command name for a result it synthesizes without a meter reply. |
| `status` | `signed-in`, `signed-out`, or `unavailable`. |
| `reason`, `message` | Required reason and optional fixed message for `unavailable`, from the table below. |
| `windows` | Each entry has a public `label`, a numeric `used_percent` from 0 through 100 inclusive and a `resets_at` time or null if the meter gives no reset. A partial read lists only measured windows. |
| `checked_at` | Time the lane was checked. This applies to all its windows. |
| `left` | Optional remaining host plan balance as `{"amount":5400,"unit":"seconds"}`. The amount is nonnegative and the unit is `seconds`, `credits` or `dollars`. |
| `target`, `margin`, `pace` | Reader-provided budget fields, defined below. |

Times use UTC at whole-second precision (`YYYY-MM-DDTHH:MM:SSZ`). A
`signed-in` lane has at least one measured window. A `signed-out` lane has
a known signed-out state. An `unavailable` lane could not be read. Both
have empty `windows` and omit `left` and `pace`. A zero is an actual meter
reading.

| Reason | Fixed message | When to use it |
| --- | --- | --- |
| `no-usage-command` | the driver has no usage command | The driver gives its usual unknown-command error. |
| `no-meter` | this harness has no meter command | There is no program-readable meter for the lane. |
| `probe-failed` | probe failed | A meter call fails, times out or gives unreadable output. |
| `driver-off` | driver off | Settings turn off the driver. The reader supplies this result without running the driver. |

Every object is closed. Emit public labels and known command names only. Keep
emails, account ids and keys, organisation ids, credentials, arguments carrying
private data, config paths and raw tool output out of lane readings and history.
The schema rejects unknown fields, including identifier fields at any depth,
and common private-value shapes in text. Producers must use settings labels
and their own known public strings, since an arbitrary identifier can look
like a label. Readers also check the lane id against its driver and known
account, and require unique lane ids and unique window labels within a lane.

## Budget and pace

The reader gets a lane's budget from [settings v1 `budgets`](settings.v1.md#fields).
It copies the budget's `amount`, `unit` and `by` into `target`. Drivers report
meters. The reader attaches `target` and `margin` for a budgeted lane and
omits all three budget fields for an unbudgeted lane. Use a margin of 5
percentage points for `percent` or 5% of the target amount in its own
unit for `seconds`, `credits` or `dollars`.

Use the time the lane's current target was set and the latest comparable usage
history reading at or before that time. Find the setting time from the settings
version that introduced or last changed the target, using the current settings
and its retained revisions. For a percentage target, the baseline is the
window's measured share and the endpoint is the target share. Match the
baseline and current windows by label and known reset. Use the earliest
matching reset at or after `by`, breaking ties by label, provided both
readings precede that reset. For an amount
target, require a comparable plan period and `left` in the target unit. Use
the decrease in remaining balance as spend since the baseline, with zero
spend at the start and the target amount at the deadline. A reset or a known
change in the plan balance unrelated to spend makes the readings incomparable.

The expected spend is the straight line from the baseline at the setting time
to the endpoint at `by`. For a reading at or after `by`, use the endpoint.
Compare observed minus expected spend in the target's unit. At either margin
edge or anywhere in between the lane is `on pace`. A difference above the
upper edge is `ahead`. A difference below the lower edge is `behind`. For
example, a baseline of 20% halfway to a 60% target gives an expected 40%.
35% and 45% are on pace, 34.99% is behind, and 45.01% is ahead.

If the target start time is unknown or is at or after `by`, or there is no
comparable reading, omit `pace` and keep `target` and `margin`. Pace guides
new launches and never stops running work.

## History

`openwiz usage --record` appends to `.openwiz/usage/history.v1.jsonl` in the
home checkout. Each newline-terminated JSON record is one lane reading in the
same shape, with `checked_at`. Multiple readings of a lane may occur on separate
lines. Keep records for 14 days by `checked_at`, dropping those older than 14
days when recording. Without `--record` the reader writes nothing.

Synthetic cases are under [`fixtures/usage/`](fixtures/usage/). Run the proof
with `python3 -I contracts/fixtures/usage/test_fixtures.py`.
