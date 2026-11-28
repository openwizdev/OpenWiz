# Choose a loop runner

Keep one WizLoops file and choose a runner for the host where you want it to
run. Check that the host supports the file's schedule, check and secret
requirements before you opt in. T3, cron, systemd and GitHub Actions are planned
for 0.2.0 and each requires an explicit choice. Using a Cloudroom project
selects the existing Cloudroom behavior.

| Runner | Availability | What the host runs | What you choose |
| --- | --- | --- | --- |
| Cloudroom | Shipped | A Cloudroom loop in a Cloudroom project | Choose the project whose scheduler should run the loop. |
| T3 | Planned for 0.2.0 | A scheduled task on a T3 server | Choose T3 if the server can represent your trigger and has the provider you need. |
| cron | Planned for 0.2.0 | A crontab entry for your user on macOS or Linux | Choose cron for a recurring schedule and name an agent starter. |
| systemd | Planned for 0.2.0 | A systemd user timer and service on Linux | Choose systemd for an exactly representable calendar schedule or a one-shot timer and name an agent starter. |
| GitHub Actions | Planned for 0.2.0 | A scheduled workflow in your GitHub repository | Choose repository CI and a UTC cron schedule. If the file names another time zone, explicitly opt in to UTC so the cron hours are interpreted in UTC. |

## When a check is quiet

A quiet check prints nothing. Cloudroom runs the check as a script and
starts no agent on a quiet run. The planned cron and systemd runners run the
check without starting an agent and launch one only if it prints something.
When you apply a loop with either runner, specify an explicit starter, either
T3 or a named local harness. Apply refuses a missing starter. The planned
GitHub Actions workflow also runs the check before deciding whether to run its
agent step.

A quiet T3 run still opens a session. The session runs the check first and
ends with a `quiet` OK line if the check prints nothing. T3's `succeeded`
status tells you the task was dispatched. Check the session's result to find
out whether the check or agent finished.

## What the runner can manage

The marker `[wizloop:<id>]` identifies the managed loop. Look for it at the end
of a loop, task or workflow name, or in the scheduler's comment or metadata
for cron and systemd. Objects without a valid marker are unmanaged and left
alone. Cloudroom can also mark an existing loop when you explicitly adopt it
by binding it to a loop file.

If a setting cannot run exactly, the runner reports a refusal code and field.
For example, `t3-cron` identifies a cron trigger T3 cannot represent,
`systemd-calendar` identifies a schedule without an exact systemd calendar
form, and `actions-timezone` identifies a non-UTC schedule without explicit
consent to use UTC. Cloudroom reports `cf-check-timeout` on `check.timeout`
when the requested timeout differs from its fixed 60 seconds.

Put secret names in the file's `secrets` field and keep secret values on the
host. Runners refuse grants they cannot reproduce exactly. For example,
`t3-secrets` refuses a named subset because T3 tasks inherit the host
environment. Use `"all"` only if that is the access you intend. GitHub
Actions uses named repository secrets and refuses `"all"` and `".env"` with
`actions-secrets`.

[Shipped Cloudroom adapter rules](https://github.com/openwizdev/OpenWiz/blob/v0.1.0/contracts/wizloops-cloudroom.v1.md) · [0.2.0 runner spec #3503](https://github.com/openwizdev/OpenWiz/issues/3503)
