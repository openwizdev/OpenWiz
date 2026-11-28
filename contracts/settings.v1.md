# Settings contract, version 1 (`openwiz.settings.v1`)

Spec #3375 (settings: one file, a Settings tab, and telling Wiz), ticket
ST1 (#3376). This contract fixes the one settings file of a factory: where
it lives, who writes it, which file decides when it exists, every section
and field, and the rules a file must keep.
[`settings.v1.schema.json`](settings.v1.schema.json) pins the shape;
[`fixtures/settings/`](fixtures/settings/) holds one fixture per rule, and
every reader and writer runs them and must agree on each reading and
refusal.

Writer: `openwiz settings` (#3377, with `fill` from #3382). Readers:
`openwiz models` (#3378), the launcher (#3379), the settings skill (#3380),
the Settings tab (#3381), and the hosts (#3426), budgets (#3492), keys
(#3420) and feed (#3408) specs, which own what their sections do; this
contract owns only the fields.

It builds on [`models.v1`](models.v1.md) (ids, families and the follow,
fixer and cross-family rules, cited here and never restated differently),
[`roster.v1`](roster.v1.md) and [`token-service.v1`](token-service.v1.md),
and changes none of them beyond one paragraph in `models.v1.md` that points
here.

**This contract grants nothing.** It authorizes no install, key, start,
live read or write. A fixture that passes proves the contract is
consistent, never that any of it is live. Every example is synthetic:
labels like `work` and `personal`, no real account.

## Where the file lives

- **The file:** `.openwiz/settings.json` in the owner's home project
  checkout on the home machine (the home is the Wiz home spec's, #3433).
  It is one UTF-8 JSON object; a repeated key refuses the whole file.
- **The backup:** each write is one commit of that file, alone, on the
  home repository's `openwiz/settings` branch, never the default branch, so
  no branch rule is bypassed. Pushing that branch is the home loop's job;
  `openwiz settings restore` rebuilds the file from it on a new home
  machine.

## Who writes

Only `openwiz settings` writes the file, and only on the owner's tap in the
Settings tab on the owner's own T3 devices or on the owner's own words to
Wiz in the Wiz chat; `fill` writes a new file on first open. All other
agents only read it, through `openwiz settings show --json`: no agent,
skill, loop or driver writes the file or asks another program to. An agent that thinks a
setting should change posts the feed contract's `openwiz:setting-proposal v1`
comment (#3410); it shows as a Needs-you card, and only the owner's yes
makes Wiz apply it.

Every write checks the whole new file against this contract and, when the
contract refuses it, writes nothing. A write is atomic (write, fsync,
rename) under one lock; it adds 1 to `version`, sets `changed_at` and
`changed_by`, and moves the file it replaced, without its `schema` and
`history`, onto the end of `history`, dropping the oldest beyond 10.

**New launches only.** A launcher reads the settings once per launch and
records the `version` it used on the start record (#3379). A running job
never re-reads them; a wake keeps the run's recorded choice.

## Which file decides

When the home settings file exists, every reader takes each role's choice
from its `roles` section. A project with no home settings file reads the
`## Models` table of its `docs/agents/fleet.md` exactly as
[models v1](models.v1.md#the-models-table) says. The hosts spec says the
same for `docs/agents/host.md`.

## Fields

`<role>` is `orchestrator`, `builder`, `fixer`, `reviewer` or
`small_builder`; `<label>`, `<key>`, `<driver>`, `<channel>`, `<lane>` and
`<project>` are object keys. "Owner" means `openwiz settings` on the
owner's tap or words; "Itself" means `openwiz settings` on every write.

| Field | Type | New file | Written by |
| --- | --- | --- | --- |
| `schema` | `openwiz.settings.v1` | `openwiz.settings.v1` | `fill` |
| `roles` | object of the five roles, all required | filled | Owner, `fill` |
| `roles.orchestrator` | a choice, or `not set` | from what is signed in, else `not set` | Owner, `fill` |
| `roles.builder` | a choice, or `not set` | from what is signed in, else `not set` | Owner, `fill` |
| `roles.fixer` | a choice, `follows builder` or `not set` | `follows builder`, else `not set` | Owner, `fill` |
| `roles.reviewer` | a choice, `waits` or `not set` | the other family, else `waits`, else `not set` | Owner, `fill` |
| `roles.small_builder` | a choice, `follows builder` or `not set` | `follows builder`, else `not set` | Owner, `fill` |
| `roles.<role>.harness` | models v1 provider id | the signed-in harness | Owner, `fill` |
| `roles.<role>.model` | models v1 model id | the harness's own current model | Owner, `fill` |
| `roles.<role>.effort` | models v1 effort id | the harness's own current effort | Owner, `fill` |
| `roles.<role>.account` | account label | a signed-in account | Owner, `fill` |
| `roles.<role>.fallback` | ordered list of `harness`, `model`, `effort`, `account`, no repeat | `[]` | Owner |
| `accounts` | object keyed by `<label>` | one per signed-in account | Owner, `fill` |
| `accounts.<label>.harness` | models v1 provider id | as signed in | `fill`, Owner |
| `accounts.<label>.host` | driver name | where it is signed in | `fill`, Owner |
| `accounts.<label>.reserved` | boolean | `false` | Owner |
| `accounts.<label>.profile` | optional: `variable` and `folder`, both | the harness's own, when it has one | `fill`, Owner |
| `accounts.<label>.profile.variable` | an upper-case environment variable name | as the harness names it | `fill`, Owner |
| `accounts.<label>.profile.folder` | a `~/` path | as the harness keeps it | `fill`, Owner |
| `hosts` | object | as below | Owner |
| `hosts.home.<role>` | driver name, for `orchestrator`, `builder` and `reviewer` | `local` | Owner |
| `hosts.overflow` | null, or `serves` and `host` | null | Owner |
| `hosts.overflow.serves` | exactly `builder` | absent | Owner |
| `hosts.overflow.host` | driver name | absent | Owner |
| `hosts.max_agents` | integer from 1, or null for no spill | null | Owner |
| `hosts.projects.<project>` | `owner/name` key; an ordered list of driver names, no repeat | `{}` | Owner |
| `drivers.<driver>` | boolean, one per installed driver; `local` required | only `local` is `true` | Owner, `fill` |
| `budgets.<lane>` | `amount`, `unit` and `by`; the lane id is the budgets spec's `<driver>:<harness or plan>:<label>` | `{}` | Owner |
| `budgets.<lane>.amount` | number above 0; at most 100 for `percent` | absent | Owner |
| `budgets.<lane>.unit` | `percent`, `credits`, `seconds` or `dollars` | absent | Owner |
| `budgets.<lane>.by` | UTC time | absent | Owner |
| `keys.<key>` | key name, as a label; `store`, `entry`, `opt_in`, `on` and `set_at`; never a value | one row per key the installed drivers name, not set | `fill`, Owner |
| `keys.<key>.store` | `token-service-key`, `boat-env`, `macos-keychain`, `linux-secret-service`, `env-file` or `cloudroom-secret` | as the key names it | `fill`, Owner |
| `keys.<key>.entry` | the store's entry name | as the key names it | `fill`, Owner |
| `keys.<key>.opt_in` | boolean | as the key names it | `fill` |
| `keys.<key>.on` | boolean; always `true` when `opt_in` is `false` | `false` when `opt_in` | Owner |
| `keys.<key>.set_at` | UTC time, or null when not set | null | Owner, by the keys flow |
| `channels.t3` | exactly `true`: T3 is the cockpit | `true` | none: fixed in v1 |
| `channels.<channel>` | boolean, one per other channel | `false` | Owner |
| `telemetry` | boolean | `false` | Owner |
| `updates` | exactly `ask` | `ask` | none: fixed in v1 |
| `version` | integer from 1 | `1` | Itself |
| `changed_at` | UTC time | the fill's time | Itself |
| `changed_by` | `settings tab`, `Wiz chat` or `fill` | `fill` | Itself |
| `history` | up to 10 earlier versions, oldest first | `[]` | Itself |

A UTC time is `YYYY-MM-DDTHH:MM:SSZ`. A driver name is a host as
[records v1, section 6](../kernel/records.v1.md#6-the-host-setting) names
one. No other section or field is allowed anywhere.

## The sections

**`roles`.** A choice is one `harness`, `model` and `effort`, with the ids
of [models v1's one id rule](models.v1.md#the-models-table), and the
`account` it runs on. `fallback` is the role's ordered next choices when its
choice hits a usage limit; the budgets spec owns the switching. The words:
`not set` (nothing signed in could fill the role), `follows builder` (the
models v1 follow rule) and `waits` (the reviewer, when the only signed-in
family is the builder's, so reviews wait as the cross-family rule says).

**`accounts`.** One harness account the owner uses on a host, keyed by a
label the owner picks: 1 to 32 letters, digits, `-` or `_`, never an email,
account id or token, so the schema refuses an `@`. A harness that supports
more than one account per machine names its own profile folder variable
and folder (for example `CLAUDE_CONFIG_DIR` and `~/.claude-work`). A
profile folder is never a credential, and OpenWiz never reads inside it.
The folder is written from `~/` so the file names no user's home.

**`hosts`.** A home host for the `orchestrator`, `builder` and `reviewer`
roles (the small builder and the fixer take the builder's), one `overflow`
host that serves builders only, the home's `max_agents`, and `projects`, an
ordered host list that replaces every role's list for that project's agents
and changes nothing else. The hosts spec owns the behaviour.

**`drivers`.** Which installed drivers are turned on. Only `local` is on in
a new file.

**`budgets`.** Per lane, a target "spend `amount` `unit` by `by`". The
budgets spec owns lanes and pacing.

**`keys`.** Each key the factory uses, by name: its `store`, the store's
`entry` name (the one its listing names, for example `openwiz-devin`),
`opt_in`, `on` and `set_at`. Never a value: a key's value lives only in its
store. The keys spec owns the flows that fill them.

**`channels`.** How the owner is told things. T3 is the cockpit; every
other channel is opt-in and off in a new file.

**`telemetry`** is off unless the owner opts in. **`updates`** is `ask`:
Wiz offers a verified release and updates only on the owner's yes.

**`version`, `changed_at`, `changed_by`, `history`.** Each earlier version
in `history` is that whole file but for its `schema` and `history`, so
`undo` can put it back.

## The rules

Each rule has its fixtures, named in [`invalid/expect.json`](fixtures/settings/invalid/expect.json)
with the rule, the field it is refused at and whether the schema or the
check after it refuses. Each invalid fixture is a valid one with one
section changed.

1. **Cross-family.** [Models v1's cross-family rule](models.v1.md#the-cross-family-rule)
   picks a reviewer of the other family than the builder's. A file whose
   `reviewer` choice, or any entry of its fallback, is of the `builder`
   choice's known family is refused, with exactly (for `Claude`, or `GPT`):

   ```text
   The Reviewer can't be a Claude model while the Builder is one: reviews must be cross-family (ADR 0008).
   ```

   Work built on a builder's fallback is reviewed as models v1 says, from
   that run's own family. Fixtures: `reviewer-builder-family.json`,
   `reviewer-fallback-builder-family.json`.
2. **Follow.** Only `fixer` and `small_builder` may be `follows builder`,
   as [models v1's follow rule](models.v1.md#the-follow-rule) says.
   Fixtures: `reviewer-follows.json`; `new-file.json` (both follow).
3. **Fixer.** [Models v1's fixer rule](models.v1.md#the-fixer-rule) picks
   each fix round, unchanged: a `fixer` choice may be of any family.
   Fixture: `full.json` (the fixer's own choice).
4. **Reserved accounts.** A role's choice and each of its fallback entries
   name an account in `accounts`, of the same harness, that is not
   `reserved`. Fixtures: `reserved-in-role.json`, `reserved-in-fallback.json`.
5. **No key value.** No key or token value appears anywhere: every free
   string, key names included, refuses the schema's `no_key` shapes, and a
   key row has no `value` field. Fixtures: `key-shaped-value.json`,
   `unknown-field.json`.
6. **Labels.** Account and key names follow the label rule above. Fixture:
   `at-in-label.json`.
7. **History.** `history` holds exactly the versions just before
   `version`, oldest first, never more than 10. Fixtures:
   `eleven-history.json`, `history-gap.json`; `ten-history.json` is valid.
8. **Nothing unknown.** An unknown section or field is refused. Fixtures:
   `unknown-section.json`, `unknown-field.json`.
9. **Overflow serves builders.** `hosts.overflow.serves` is `builder`.
   Fixture: `overflow-for-reviewers.json`.
10. **Turned-on hosts.** Every home, overflow and project host is a driver
    turned on in `drivers`. Fixture: `host-driver-off.json`.

The schema refuses rules 1, 2, 5, 6, 8, 9 and the count in 7. Rules 4, 10
and the order in 7 compare one section with another, which JSON Schema
can't, so every reader checks them after the schema; the fixture test's
`rule_errors` is the reference. The rules hold for each earlier version in
`history` too.

## A new file

`fill` writes a new file from what is signed in on the home machine
(#3382). Every new file has these values:

```json
{
  "schema": "openwiz.settings.v1",
  "hosts": {"home": {"orchestrator": "local", "builder": "local", "reviewer": "local"}, "overflow": null, "max_agents": null, "projects": {}},
  "budgets": {},
  "telemetry": false,
  "updates": "ask",
  "version": 1,
  "changed_by": "fill",
  "history": []
}
```

and also: only `local` turned on among the installed drivers, only `t3`
on among the channels, every opt-in key off, no account reserved, and each
role from a signed-in harness or `not set`, the reviewer of the other family
or `waits`. Nothing nobody signed in to is ever picked. Fixtures:
`new-file.json` (two families), `new-file-one-family.json` (the reviewer
waits), `new-file-nothing-signed-in.json`.

## The key-use log

The home's key-use log is `key-use.log` in the home checkout's `.openwiz/home` folder.
Each line is exactly `<key name> <UTC time>`, one per use of a key,
appended by the key helper and the token service (the keys spec); it never
holds a value. `last_used_at` is not stored in the settings file:
`openwiz settings show` reads each key's `last_used_at` as the latest time
on its lines, or null with none. Fixtures: `key-use.log` reads as
`last-used.json`.

## The fixtures

```sh
python3 -I contracts/fixtures/settings/test_fixtures.py
```

It runs the schema over `valid/` (each accepted) and `invalid/` (each
refused at its field, for its rule), checks the new-file values above, the
Fields table against the schema, the key-use log and that nothing real
appears. Its red run is in `evidence/red.txt`.

## Gaps

- The fixtures prove the contract agrees with its schema and rules; they
  prove no reader or writer. Each one's own tests must run them.
- `set`'s other refusals (an unknown harness, a model the harness doesn't
  offer, a driver that isn't installed) need the live offer and install
  lists, so they are `openwiz settings`' checks (#3377), not this file's.
- Families are models v1's: a harness of unknown family is never refused
  as a reviewer, and its reviews wait as models v1 says.
