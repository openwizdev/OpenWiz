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
or authenticated Tailscale must be independently verified before ready. A tunnel
process is insufficient. No quick tunnel. Keep loopback binding, HTTPS host,
origin, callback, content-type, request-id and once-only write guards. Denied,
expired and foreign requests cannot reach an effect. Setup does not fabricate
spec confirmation or plan approval, and install permission never starts work.

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
