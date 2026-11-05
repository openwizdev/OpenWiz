# Resumable setup v1

Setup is independent of installation. `GET /api/v1/setup` is read-only and has
no body or query. It creates no state, calls no CloudRoom/GitHub executable,
and cannot activate an engine. It returns `openwiz.setup.v1`: `ready`, the
ordered `components` array, `engine`, `cost` and `operations`.

Each component has `id`, `state`, `reason` and `next`. The fixed independent ids
are `cloudroom`, `harness`, `personal_github`, `github_app`, `project`, `engine`
and `remote_access`. States are `verified`, `missing`, `refused`, `unknown`.
Only positive, current evidence for the selected repository/host establishes
verified. Saved config, successful inventory reads and artifact download alone
never do. A refusal is distinct from a missing connection; unavailable evidence
is unknown. Reasons and next steps are public plain text, never credential or
provider response dumps. Overall ready requires every prerequisite for the
selected engine to be independently verified; phone readiness remains explicit
and is never inferred from local readiness. T1's unconfigured slice returns
ready false and missing/unknown prerequisites. Later connection tickets supply
real observations, through explicit composition rather than fixture env flags.

Engine is `unselected`, `cloud` or `local`. Cloud engine and fleet agents have
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
a later refusal. This contract alone authorizes no write route: T1 exposes none.

App state uses OpenWiz's established service App, selected repositories only,
Metadata read, Contents/Issues/Pull requests write, Checks/Actions read; no
personal-token fallback. Reused CloudRoom login, harness/model availability and
personal GitHub push identity are checked independently. Keys remain in
owner-only state on the explicitly selected engine host, through protected
secret provisioning for Cloud, never prompts/args/URLs/logs/repository files.

Remote access defaults unknown. Named Cloudflare Tunnel plus owner-only Access
or authenticated Tailscale must be independently verified before ready. A tunnel
process is insufficient. No quick tunnel. Keep loopback binding, HTTPS host,
origin, callback, content-type, request-id and once-only write guards. Denied,
expired and foreign requests cannot reach an effect. Setup does not fabricate
spec confirmation or plan approval, and install permission never starts work.
