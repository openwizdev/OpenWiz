# CI routing v1 (`openwiz.ci-routing.v1`)

CI1 of spec #3524, its contract-first ticket (#3525). This contract fixes how
the org's CI picks its runner: the two org variables every Linux job reads,
the exact `runs-on` expressions, the states `normal` and `all-jog`, the rule
that switches between them, the record of each switch, and the authority the
routing tool needs. CI2 (#3526) builds the routing tool, `tools/ci-route/`.
CI2b (#3834) builds the workflow lint. CI3 to CI5 (#3527, #3528, #3529) move
the workflows onto the expressions. CI6 (#3530) runs the tool on a schedule.
They build to this contract.

**This contract grants nothing.** It sets no variable, reads no usage, edits
no workflow and posts nothing. A fixture or test that passes here proves the
contract is consistent, never that any of it is live. The live read and the
first `--apply` are the owner's (CI8, #3532).

## The pin

The JSON block below is the machine-readable pin.
`contracts/fixtures/ci-routing/test_fixtures.py` checks it against the prose
and the fixtures. The prose explains it. Where they disagree, the contract is
wrong and must be fixed.

```json
{
  "schema": "openwiz.ci-routing.v1",
  "organization": "openwizdev",
  "jog_label": "jog-4vcpu",
  "variables": {
    "OPENWIZ_RUNS_ON": {
      "repositories": "public",
      "fallback": "ubuntu-24.04",
      "visibility": "all",
      "runs_on": "${{ vars.OPENWIZ_RUNS_ON || 'ubuntu-24.04' }}"
    },
    "OPENWIZ_PRIVATE_RUNS_ON": {
      "repositories": "private",
      "fallback": "jog-4vcpu",
      "visibility": "private",
      "runs_on": "${{ vars.OPENWIZ_PRIVATE_RUNS_ON || 'jog-4vcpu' }}"
    }
  },
  "hosted_only": {
    "systems": ["macos", "windows"],
    "while_all_jog": "waiting on the limit, not failed"
  },
  "states": {
    "normal": {"OPENWIZ_RUNS_ON": "ubuntu-24.04", "OPENWIZ_PRIVATE_RUNS_ON": "jog-4vcpu"},
    "all-jog": {"OPENWIZ_RUNS_ON": "jog-4vcpu", "OPENWIZ_PRIVATE_RUNS_ON": "jog-4vcpu"}
  },
  "rule": {
    "to_all_jog": {
      "any_of": ["minutes", "spending", "queue"],
      "minutes": "used >= included, included > 0",
      "spending": "limit_cents > 0 and spent_cents >= limit_cents",
      "queue": {
        "runner": "github-hosted",
        "at_least_seconds": 900,
        "limit_reasons": ["minutes", "spending", "concurrency"]
      }
    },
    "to_normal": {
      "period": "UTC calendar month, reset at 00:00:00Z on the 1st",
      "after_reset": "the read's period is later than the month of the newest switch to all-jog",
      "room": "no limit signal"
    },
    "unreadable": {
      "causes": ["gh-error", "scope", "malformed", "stale"],
      "state": "unchanged",
      "record": null
    },
    "unknown_variables": {"state": "unchanged", "record": null},
    "reasons": {
      "minutes": "included minutes used up",
      "spending": "spending limit reached",
      "queue": "jobs queued for a limit",
      "reset": "billing period reset with room",
      "forced": "forced by the owner"
    }
  },
  "record": {
    "form": "<UTC> ci-routing <from> -> <to>: <reason>",
    "pattern": "^(?P<at>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z) ci-routing (?P<from>normal|all-jog) -> (?P<to>normal|all-jog): (?P<reason>[a-z][a-z ]+[a-z])$",
    "state_file": "<state>/ci-route/switches.log",
    "tracking_issue": {
      "repository": "openwizdev/OpenWiz",
      "title": "CI routing: switch record",
      "state": "open",
      "created_by": "the owner",
      "none_or_several": "post nothing and say so"
    }
  },
  "authority": {
    "grant": "the owner's, before any read or write",
    "gh": "the owner's own signed-in gh",
    "scope": "admin:org",
    "owner_step": "gh auth refresh -h github.com -s admin:org",
    "refuses_when_set": ["GH_TOKEN", "GITHUB_TOKEN", "GITHUB_ACTIONS"],
    "app_token": false,
    "edits_workflows": false,
    "default": "--dry-run",
    "writes_only_with": "--apply",
    "writes": ["gh variable set --org", "one comment on the tracking issue"]
  }
}
```

## The variables

Two org-level Actions variables on `openwizdev` choose every Linux runner:

| Variable | Read by | Visibility | Fallback |
| --- | --- | --- | --- |
| `OPENWIZ_RUNS_ON` | Linux jobs in public repositories | `all` | `ubuntu-24.04` |
| `OPENWIZ_PRIVATE_RUNS_ON` | Linux jobs in private repositories | `private` | `jog-4vcpu` |

Each Linux job's `runs-on` is exactly one of these lines, with the fallback
written in the workflow, so a missing or empty variable still gives a runner:

```yaml
runs-on: ${{ vars.OPENWIZ_RUNS_ON || 'ubuntu-24.04' }}
runs-on: ${{ vars.OPENWIZ_PRIVATE_RUNS_ON || 'jog-4vcpu' }}
```

A public repository's Linux job uses the first and a private repository's the
second. No Linux job hard-codes a runner label or reads another variable.
`jog-4vcpu` is the Jog label. Changing it is a new version of this contract.

**macOS and Windows jobs keep their GitHub-hosted runners**, written in the
workflow as today: Jog is Linux. They read neither variable. While the state
is `all-jog`, the routing tool's report names them as waiting on the limit,
not failed, and a reviewer reads them the same way.

## The states

The state is read from the two variables, an unset or empty variable reading
as its fallback:

| State | `OPENWIZ_RUNS_ON` | `OPENWIZ_PRIVATE_RUNS_ON` | Means |
| --- | --- | --- | --- |
| `normal` | `ubuntu-24.04` | `jog-4vcpu` | Public repositories on GitHub Actions, private ones on Jog |
| `all-jog` | `jog-4vcpu` | `jog-4vcpu` | Every Linux job on Jog |

Any other pair of values is no state: the tool changes nothing, records
nothing and says the variables are unknown. The owner sets a state by hand
with `--apply --force <state>`, recorded with the reason `forced by the owner`.
A switch writes both variables, `OPENWIZ_RUNS_ON` with `--visibility all` and
`OPENWIZ_PRIVATE_RUNS_ON` with `--visibility private`.

## The switch rule

Each run makes one usage read of the org's Actions billing and its queued jobs,
then decides.

**From `normal` to `all-jog`** when the read shows any one limit signal, in this
order:

1. **Minutes:** the included minutes are used up: `used >= included`, with
   `included > 0`. Minutes are whole minutes as the billing read reports them.
2. **Spending:** the spending limit is reached: `limit_cents > 0` and
   `spent_cents >= limit_cents`, in whole US cents. A limit of `0` or no
   limit is never this signal; with a `0` limit, the minutes signal covers it.
3. **Queue:** at least one job waiting for a GitHub-hosted runner has been
   queued for 900 seconds (15 minutes) or longer, and the read gives its
   reason as `minutes`, `spending` or `concurrency`. A job queued 899 seconds,
   or for any other reason, is not this signal.

The record's reason is the first signal that holds.

**From `all-jog` back to `normal`** only when both hold:

- **The billing period has reset.** A billing period is a UTC calendar month,
  reset at 00:00:00Z on the 1st. The read's period, `YYYY-MM`, is later than
  the month of the newest `-> all-jog` line in the state file. With no such
  line, the reset counts as past.
- **The read shows room:** none of the three limit signals holds.

Inside the period the switch happened in, `all-jog` stays even when the read
shows room. After a reset, a read that still shows a limit keeps `all-jog`.
In `normal`, a read with no limit signal keeps `normal`.

**An unreadable read never changes the state.** The read is unreadable when
`gh` fails (`gh-error`), the owner's `gh` lacks the `admin:org` scope
(`scope`), the answer is not the expected shape (`malformed`), or its period
is not the UTC month of the run (`stale`). The tool sets no variable, writes no
record, says which cause it met and that the state stays, and exits as a
failure. When no billing endpoint answers for the org's plan, the read
carries no minutes and no spending figures and the queue signal alone decides;
that read is readable, and the tool says it read the queue only.

## The switch record

Each switch, and only a switch, writes one line:

```text
<UTC> ci-routing <from> -> <to>: <reason>
```

`<UTC>` is the run's time as `YYYY-MM-DDTHH:MM:SSZ`. `<from>` and `<to>` are
the two different states. `<reason>` is one of the pin's fixed sentences:
`included minutes used up`, `spending limit reached`, `jobs queued for a limit`,
`billing period reset with room` or `forced by the owner`. The reason carries
no usage figures, account names or amounts, so the line is safe in public.
For example:

```text
2026-12-14T09:30:00Z ci-routing normal -> all-jog: included minutes used up
```

The line is appended to the tool's state file, `<state>/ci-route/switches.log`
in the owner's OpenWiz state directory, and posted as one comment on the one
tracking issue: the open issue in `openwizdev/OpenWiz` titled exactly
`CI routing: switch record`. The owner opens that issue; the tool never
creates one. When there is none, or more than one, the tool posts nothing,
keeps the line in the state file and says so. The line is written only after
both variables are set.

## Authority

The routing tool runs only on the owner's grant, given before it makes any read
or write. It reads usage and sets variables through the owner's
own signed-in `gh`, with the `admin:org` scope the owner grants with
`gh auth refresh -h github.com -s admin:org`. A missing scope is the `scope`
cause and the tool prints that step. It never uses the factory's App token or
any token handed to it: it refuses when `GH_TOKEN` or `GITHUB_TOKEN` is set,
and when `GITHUB_ACTIONS` is set, since it never runs as a GitHub Actions job.

`--dry-run` is the default and prints what it would do. Only `--apply` writes,
and its only writes are `gh variable set --org openwizdev` for the two
variables and the one comment on the tracking issue. The tool
never edits a workflow, opens a pull request or changes a runner label:
switching is one variable change, not a workflow edit.

## Fixtures

`contracts/fixtures/ci-routing/` holds one case per file. Each gives the time
of the run (`now`), the variables and switch lines before it (`before`), the
usage read (`read`, or `{"ok": false, "cause": ...}`) and the expected state,
variables and record line (`expect`, `record` null for no switch). The cases
cover `normal` to `all-jog` on each limit signal, `all-jog` back to `normal`
after a reset, `all-jog` staying inside its period and after a reset that
still shows a limit, `normal` staying with room, a read of the queue only,
unknown variables, and an unreadable read in each state. `red-run.txt` is the
run before this contract existed. CI2's fake `gh` answers in this read shape.

## Gaps

Whether Jog runs public repositories' jobs is unverified; Jog documents its
runners for private repositories. The live check (CI8, #3532) shows a public
repository's check on Jog before the rule is relied on. Which billing endpoint
answers for the org's plan is CI2's first step.
