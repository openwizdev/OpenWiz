# Resumable setup v1

Setup is independent of installation. `openwiz.setup.v1` is the owner's
read-only setup report: `ready`, the ordered `components` array, `engine`,
`cost` and `operations`. Producing it creates no state, calls no
CloudRoom/GitHub executable and activates nothing. No OpenWiz route serves it
since #1264; `tools/install/setup/` checks the components and saves their
results, and `tools/install/access/` reads the report's operations.

Each component has `id`, `state`, `reason` and `next`. The fixed independent ids
are `cloudroom`, `harness`, `personal_github`, `github_app`, `project` and
`remote_access`. Setup has no engine step (0.0.17, #873): there is no `engine`
component, and a reader refuses a report that carries one. States are `verified`, `missing`, `refused`, `unknown`.
Only positive, current evidence for the selected repository/host establishes
verified. Saved config, successful inventory reads and artifact download alone
never do. A refusal is distinct from a missing connection; unavailable evidence
is unknown. Reasons and next steps are public plain text, never credential or
provider response dumps. Overall ready requires every component except
`remote_access` to be independently verified; phone readiness remains explicit
and is never inferred from local readiness. T1's unconfigured slice returns
ready false and missing/unknown prerequisites. Later connection tickets supply
real observations, through explicit composition rather than fixture env flags.

The top-level `engine` field stays for saved state written before 0.0.17. It
reports an old saved selection, or `unselected`, and never gates ready. The
rest of this paragraph describes that retired engine. Engine is `unselected`, `cloud` or `local`. Cloud engine and fleet agents have
separate location choices. A Cloud engine is one durable CloudRoom Loop invoking
the packaged mechanical tick; an idle or unapproved plan starts no builders.
Local supervision and signing must be supported and verified on the chosen OS.
Sleeping local hosts stop new orchestration; existing Cloud agents continue.

Cost has `provenance` (`measured`, `estimated`, `unknown`), `credits`,
`window_s`, `monthly_projection`, `free_allowance`, and `reason`. Numeric fields
are nullable nonnegative numbers, window is positive when measured; unknown
keeps all numeric fields null. An allowance is verified current evidence, not a
hardcoded pricing promise. Above about one tenth of the free allowance, measured
Cloud idle-engine cost defaults a free owner to Local; no measurement requires
an explicit choice, never a claimed affordable Cloud default. Provider model
charges remain separate. T1 returns unknown cost and unselected engine.

Operations are durable setup effects, separate from readiness. Each has
`operation_id` (32 lowercase hex), `kind` (`connect_app`, `prepare_project`,
`activate_engine`, `configure_access`), `phase` (`proposed`, `applied`,
`refused`, `uncertain`), `fingerprint` (64 lowercase hex), `effects` (plain
public descriptions), and `reason`. Unknown/duplicate keys fail. Persist id,
request fingerprint and proposal before any effect; apply only a matching,
current explicit authorization. Retry/reload reuses the id. A lost reply is
uncertain and must be reconciled against the provider's exact resource before
another call. Never infer applied from process launch or erase uncertainty with
a later refusal. This contract authorizes no write route.

App state uses OpenWiz's established App, selected repositories only,
Metadata read, Contents/Issues/Pull requests write, Checks/Actions read; no
personal-token fallback. Reused CloudRoom login, harness/model availability and
personal GitHub push identity are checked independently. Keys remain in
owner-only state on the owner's machine, through protected
secret provisioning for Cloud, never prompts/args/URLs/logs/repository files.

Remote access defaults unknown. Named Cloudflare Tunnel plus owner-only Access
or authenticated Tailscale must be independently verified before remote access
is reported verified. A tunnel process is insufficient. No quick tunnel. Keep
loopback binding, HTTPS host, origin, callback, content-type, request-id and
once-only write guards. Denied, expired and foreign requests cannot reach an
effect. Setup does not fabricate spec confirmation or plan approval, and
install permission never starts work.

## 0.0.16 expansion: selected identity and brain (#632)

[setup-onboard.v1](setup-onboard.v1.md) pins the shapes; this section is the
compatible change to `openwiz.setup.v1`. The schema name, component ids, states,
read-only rule and operation rules are unchanged.

- **Two optional response fields.** `identity` is `selected` (`app`,
  `personal_login`, `unselected`), `app_choice` (`create`, `reuse`, `skip`,
  `undecided`) and `acting_login` (the personal login acting, or `null`).
  `personal_login` needs `app_choice: skip` and names its login. `brain` is
  `null` or `location` (`in_repository`, `companion`), `brain_repository` and
  `folder` (`.openwiz/brain`). Both carry public identifiers only.
- **Revised ready rule.** Ready still requires every other prerequisite
  verified (no engine since 0.0.17, #873). It requires `github_app` verified unless `identity`
  says the owner explicitly selected the personal login and skipped the App;
  then `github_app` stays truthfully `missing` (reason: skipped) and the
  `personal_github` login's positive account and repository checks establish
  the identity part. An App failure, revocation or unknown identity never
  selects that path; only the owner's explicit skip does.
- **Old producers and saved state.** A response without `identity` keeps the
  original App-required rule exactly. Saved setup state (`openwiz.setup-state.v1`)
  gains the optional `identity` and `brain` fields, as `engine` did; a state
  omitting them stays valid and reads as no selection (the App-required rule)
  and no brain reference (today's project settings and repository discovery,
  unchanged). Project settings keep their exact nine keys.
- **Old and new readers.** Readers are strict, so a reader that predates these
  fields refuses a response carrying either field as unreadable, rather than
  ignoring it; it never shows a partial or upgraded state. A producer emits
  them only in a package whose reader accepts them. A new reader accepts both
  the old and the new form and applies the rule that form selects.
- **No effect.** The report still creates nothing and calls no
  CloudRoom or GitHub executable; sign-in, skip and init are separate,
  disclosed, authorized operations.

## 0.1.1: the chosen host (#2217)

Spec #2216 makes CloudRoom one place agents can run, not a requirement. This
section is the compatible change to `openwiz.setup.v1`, to `setup.py
prepare` and `check`, and to the offered list `openwiz models --json` prints.
Fixtures: `tools/install/tests/setup-onboard-contract/fixtures/hosts.json`;
`test_contract.py`'s `Hosts` cases read them. Readers: NC2 (#2219, setup),
NC3 (#2220, `openwiz models`) and NC5 (#2222, the first fleet).

**The host.** The host is where the project's agents run: `cloud`
(CloudRoom), `local` (this computer, through OpenWiz's local driver), `boat`
(boat.dev) or another driver's name. A name is lowercase letters and digits
in parts joined by single hyphens, at most 40 characters. Another host's
name is its driver's name, the same as the project's `Host: <name>` line in
`docs/agents/host.md`. CloudRoom is always `cloud`, whether launch-fleet
starts its agents with `room-cli` (no `Host:` line) or through the
`cloudroom` driver, so setup refuses `cloudroom` as a host name.

**The cloud host is unchanged.** With the host `cloud`, and in every report,
saved project and check output from before 0.1.1, which name no host, every
rule, code, `next` line and output above stays exactly as it is today. Ready
needs `cloudroom` verified. No component reads `cloudroom_not_needed`.

### The report

- **`host`:** an optional field naming the host. Without it, the report is a
  `cloud` report.
- **Another host's `cloudroom` component** is `state: unknown` with `reason:
  cloudroom_not_needed`. Setup never reads CloudRoom for it, so the state is
  unknown, and it never blocks ready. Ready needs every component except
  `cloudroom` and `remote_access` independently verified, with the App rule
  of the 0.0.16 expansion unchanged.
- **Another host's `project`** is verified from GitHub alone: the repository
  exists, the signed-in account can write to it, and the service issue, the
  fleet settings and the brain pass as today. No CloudRoom project or answer
  thread is read.
- **Another host's `harness`** is verified when the chosen harness's program
  is installed (`claude` for `claude-code`, `codex` for `codex`) and the
  saved choice follows the Models table's ids rule below. Setup checks the
  installed program even when the model is outside the local offered list.

The schema refuses a `cloud` report (or one without `host`) that is ready
without `cloudroom` verified, a `cloud` report with `cloudroom_not_needed`,
and another host's report whose `cloudroom` component is anything else.

### `prepare`

`setup.py prepare` takes `--host NAME`, `cloud` when left out.

- **`cloud`:** `--host cloud` and no `--host` are the same: today's required
  flags, effects, saved settings and output, byte for byte. The saved
  project keeps its exact nine keys and no `host` key.
- **Another host** needs no `--project` or `--answer-thread`, and refuses
  either one, so no CloudRoom id is ever saved for it. The saved project has
  ten keys: the nine, with `project` and `answer_thread` both `null`, and
  `host`. The preview's effects drop the answer-thread line, and its first
  line is `Select OWNER/NAME for your first fleet, with agents on HOST.`;
  every other line is as today.

The schema's `$defs/prepared_project` pins both shapes. The setup store's
value and credential checks apply to both: a trimmed operator of at most 100
characters with no control character, a repository name other than `.` or
`..`, a service issue below 2^53 and agent settings holding no credential
shape. The schema expresses each of these but the credential check.

### `check`

`setup.py check` reads the host from the saved project. For `cloud` its
`openwiz.setup-check.v1` output is today's, byte for byte. For another host
it calls no `room-cli` and no `openwiz` command that reads CloudRoom, and
its output gains `"host": "<name>"`. Its codes:

| Component | Codes |
| --- | --- |
| `cloudroom` | `cloudroom_not_needed` only. Its `next` line is `None: your agents run on HOST, not CloudRoom, so CloudRoom is not needed.` |
| `harness` | `harness_listed` (verified: program installed and choice settable, including unlisted models), `harness_unselected`, `harness_not_installed` (the program is not on `PATH`), `harness_unavailable` (the saved choice fails the ids rule or names an unsupported harness), `harness_unreadable` |
| `project` | today's codes except `project_answer_refused`, plus `project_no_write` (refused: the signed-in account can't write to the repository) |
| `personal_github`, `github_app` | today's codes |

A `next` line for another host never names a CloudRoom step.

### The local offered list

The read is `openwiz models --json --host <cloud|local|boat|driver name>`.
An explicit `--host` wins, including before `prepare` saves a project.
Without the flag, use the host from the saved project if it has one, else
`cloud`. A host other than `cloud` selects the local source and makes no
CloudRoom call, even when CloudRoom is available. With `cloud`, the read
uses the existing CloudRoom catalogue.

`openwiz models set` (including `follows-builder`) and `openwiz models show`
accept the same `--host NAME` flag and use the same host precedence.
`show` continues to read the configured roles from `fleet.md` without a
catalogue read or a write. `set ... follows-builder` keeps its existing
read and write behaviour.

First-fleet (NC5) passes the user's chosen host explicitly when reading
models or calling `set` or `show` before `prepare`; setup (NC2) passes the
saved host when asking the models CLI for choices. The models CLI (NC3)
applies the selector in each form. The schema's `$defs/models_host_selection`
pairs the explicit and saved host inputs with the response's source marker.
It describes the selection rule, and the response itself keeps the options
shape below.

`openwiz models --json` (`openwiz.cloud-options.v1`, the
[`options`](new-thread.v1.schema.json) shape) can be read without CloudRoom:

- **`source: "local"`** marks it. A list without `source` is CloudRoom's
  catalogue from one `cloud status` read, exactly as today; a CloudRoom
  read never carries the field.
- **`harnesses`** has one entry for each harness whose program is installed
  on this computer: `claude-code` (provider `claude-code`, program `claude`)
  and `codex` (provider `codex`, program `codex`), each with OpenWiz's
  current choices (J255: `claude-opus-5-5` and `gpt-6.2-sol`, effort
  `medium`). `attachments` and `steer` are `null`, `unavailable` is empty.
- **Nothing installed:** `state` is `no_options` with reason
  `harnesses_not_reported`, and `harnesses` is empty.
- **`label`** is `Installed local harnesses with OpenWiz's current choices`
  for the local source. CloudRoom keeps `as reported by CloudRoom; it may answer from a saved copy`.
  Readers use `source` to distinguish them.

For the local source, `openwiz models set <role> <provider> <model> <effort>`
accepts any settable model id for an installed harness, including ids
outside J255. The [Models table ids rule](models.v1.md#the-models-table)
still applies to the provider, model and effort. For a successful local
set of a model outside the offered list, `openwiz models set --json` adds
`"listed": false` to the top level of the
[`set_report`](models.v1.schema.json#/$defs/set_report), on both
`changed` and `unchanged`. Other reports omit the field. The offered list
continues to show the current choices. For `cloud`, `set` still requires
that the provider, model and effort appear together in the CloudRoom
catalogue.
