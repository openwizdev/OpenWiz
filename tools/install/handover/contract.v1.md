# Installed handover v1

This contract covers #2379, ticket T12 of spec #1093. It defines how a verified
installation hands over to the T9 PC executor and the T10 completion verifier,
and the credit-evidence record that the live ticket #1110 supplies. The module is
[handover.py](handover.py) and the schema is
[contract.v1.schema.json](contract.v1.schema.json). Every object has exactly its
declared keys, each once, with the declared types. Duplicate keys, unknown fields
and non-finite numbers are refused.

The evidence class is synthetic recording proof. Native PC start, owner
authority, a trusted completion reader, live credits and IF10 timing are all
unverified. Their gaps are listed at the end. No successful positive handover or
completion is claimed for a real installation.

## Installed runtime

`resolve(root, state_root=None)` returns the one build that `<root>/current`
selects. The default state root is `<root>/state`, as `install.py` uses. The
selection must meet all of these:

- It is an owner-held symlink to an absolute path.
- That path is a private directory `<state>/service/builds/<40-hex source>`.
- The build's own `install-manifest.json` passes `install.manifest_at`.
- Its source matches the directory name.
- Every installed file matches `install.verify_installed`.

An identical verified copy outside this installation's builds is refused. So are
a missing selection and a tampered asset. There is no source-checkout, `PATH`,
environment or flag fallback. The verifier used is the `install.py` that ships
beside this module.

`modules(runtime)` loads the packaged tools from the resolved build only.
`install.HANDOVER_RUNTIME` lists the files it needs:

- `runtime/setup/store.py`
- `runtime/platform/runtime.py` and `security.py`
- `runtime/pc_activation/activation.py`
- `runtime/completion/checkpoint.py` and its schema
- `runtime/engine/engine.py`
- `runtime/install.py`
- `runtime/handover/handover.py`

This role is additive. Older bundles still install, and the handover refuses
them with `installed handover runtime is missing`. Each packaged tool's `import
store` is bound to that build's store while it loads. A loaded module outside
the build is refused.

## Activation record and login

`status(root, state=None)` reports `openwiz.installed-handover.v1`. Its
`activation` value is one of these:

| Value | When |
| --- | --- |
| `absent` | There is no `setup/pc-activation.json` |
| `unreadable` | Any of: the runtime is unverified or lacks the handover role; the journal is not private, owner-held and singly linked; T9's `journal()` reader refuses it, including duplicate keys; the service config cannot be read |
| `held` | The journal is valid but its outcome is not `applied`, or its binding differs from the current facts below |
| `verified` | T9 recorded `applied` (which needs a confirmed App record read-back), and the binding matches every current fact |

The current facts are:

- the effective owner
- unit `openwiz.service`
- the installation root and state root
- the selected build and its `VERSION SOURCE` runtime
- the SHA-256 of the current `service/config.json` bytes
- the repository, project, App ids and service issue from that config

So changing the config, the owner or the selected build moves a `verified`
record back to `held`. `handover_allowed` is true only when `activation` is
`verified`.

`login` is always `unknown`, as LE1 decided in revision 15. It is reported and
never inferred, and it neither grants nor blocks the handover. `completion` is
`held` and `cloud` is `unresolved`. `next_steps` lists plain next actions.

## PC executor composition

`executor(root, state, provider, clock, runner)` builds T9's packaged `Executor`.
It uses that build's `Store` and `PcManager` and an injected supervisor runner.
The production provider is `Unavailable`: authority, observation, start and
record each refuse. Preview then saves the ordinary proposal, and execute saves
`held` with no supervisor effect and no App record.

Recording providers show these behaviours through the real installed
composition:

- a clean consumer applies once and reads back its exact outcome
- a lost start reply stays uncertain, and restart reconciles it without a second start
- an uncertain App record holds across restart and is never posted again

## Completion verifier

`completion(root, pin, effect, reader=None)` runs the installed T10
`verify_completion` once per effect. It calls the reader freshly, twice. With no
trusted reader it returns `CP1_unreadable`. A missing or unverified runtime also
returns `CP1_unreadable`. No result is cached.

## Credit-evidence handoff to #1110

#1110 supplies one `openwiz.credit-evidence.v1` record
(`$defs.credit_evidence`). It has these parts:

- `candidate`: `version` and `source`. These must equal the candidate being judged.
- `interval`: integer epoch milliseconds, with `started_at` before `ended_at`.
- `usage`: source `cloudroom_usage`, provenance `measured`, `estimated` or `unknown`, `credits` (a finite number of at least 0, or null) and `observed_at`.
- `allowance`: source `cloudroom_plan`, `credits` and `observed_at`. This source is separate from the usage source.

`credit(value, now, candidate)` returns `openwiz.credit-handoff.v1`
(`$defs.credit_handoff`). It uses #2001's cost reader and default policy,
`engine.cost`, unchanged:

- the window is the interval in seconds
- the monthly projection is the observed rate over 30 days, labelled `estimate: 30 days at the observed rate`
- both observations must be at most one hour old and not in the future

`policy_branch` follows these rules:

- **`local`:** `measured` evidence whose projection is more than a tenth of the current free allowance.
- **`cloud`:** `measured` evidence within that tenth.
- **`explicit_choice`:** anything else. That covers estimated, unknown, stale, unsourced, foreign or malformed evidence.

So unknown, estimated or stale evidence cannot establish an affordable Cloud
default. `provider_charges` is always `separate_unavailable`: model-provider
charges are not Cloud Credits.

The offline command is:

```sh
python3 -I tools/install/handover/handover.py credit FILE --now MS --version V --source S
```

It prints the handoff and exits 0 for `cloud` or `local`, and 5 for
`explicit_choice`. It reads one file of at most 4096 bytes and collects nothing.

## Packaging

`tools/release/build_products.py` ships every `HANDOVER_RUNTIME` file from its
exact tracked source. It does this whenever the requested commit's tree tracks
`tools/install/handover/handover.py`. A file merely present in the checkout
decides nothing. Such a commit is refused before any output is written if it
lacks any role file in the checkout, or holds a linked or symlinked one. Commits
that do not track the handover keep their prior assets.

## Packaged startup gate

`crates/service/src/bootstrap.rs` `check()` keeps source deployments on their
prior path. That means no `install-manifest.json` and no `runtime/`. A packaged
build starts only if all of these hold, and it then prints
`installed handover verified; login: unknown`:

- **An installer-valid package.** The build is a private, plain
  `<state>/service/builds/<40-hex source>`. Its own manifest meets the
  installer's `manifest_at` rules: exact keys, the v1 schema, its version, a
  supported target, setup API 1, and the bundle name, hash and size. Every asset
  has a safe, unique, non-overlapping path, the correct mode, and its own
  SHA-256 and size. The installer's 19 required assets are all present. The web
  and runtime build stamps equal this version, source and target. Nothing
  unlisted is installed.
- **This runtime state.** The state directory the service will actually use,
  read with the same `OPENWIZ_STATE_DIR` reader, is exactly this installation's
  plain, private state.
- **T9's applied journal.** `setup/pc-activation.json` is private and meets
  every T9 `journal()` invariant. Exact keys are present, nullable ones
  included. The request, binding and operation shapes, the fixed effects and
  reason, and the safe-integer time bounds all hold. Its request hash and
  operation fingerprint equal T9's canonical fingerprint. It records `applied`
  with a `confirmed` App record.
- **The exact installation.** The binding names the effective owner, unit
  `openwiz.service`, this state root, this build and its `VERSION SOURCE`
  runtime, and the SHA-256 of the current `service/config.json`. That config
  passes the service's strict config reader. Its repository, project, App IDs
  and service issue equal the binding's. The binding root is plain, private and
  owner-held, and its owner-held `current` symlink selects this build.

Anything else refuses with `Activation remains closed: ...; login: unknown`.
There is no flag, environment or config bypass, and the check starts no
process.

## Completion verifier seam

`Control::with_completion_verifier` attaches a verifier to the controlled tick.
`Control::check_completion` calls it afresh for each `spec_summary` and
`all_closed` effect, and returns its result. Without a verifier, the shipped
refusal is unchanged. The service tick composition attaches a fail-closed
verifier. It refuses every summary/close with the fixed reason
`completion verification is unavailable; orchestrator judgment required: no
trusted completion reader is installed`. No Rust-to-Python bridge exists, by
revision 16's decision.

## Proof

These proofs use synthetic values only:

- **`python3 -I tools/install/handover/test_handover.py -v`.** This is the `release:install` case `test_installed_handover`. It drives the real installer, a synthetic bundle from `fixture_bundle.handover_runtime()`, the packaged T9 executor and T10 verifier, recording providers and the real release collector on a synthetic Git repository.
- **`cargo test -p openwiz-tests --test service t12_handover`.** This runs the real built `openwiz-service` from synthetic installed layouts. It also drives the real controlled tick with an in-memory GitHub and a `sh` room-cli fake. Recording verifiers there show that summary and close effects run only after a verifier passes, at each wake.

## Gaps

These remain open and unverified:

- **Positive packaged handover.** No real installation has been activated: no native positive observer and no owner-authority source exist.
- **Positive completion.** No trusted CP1 reader, independent writer role or live-result validator exists. The service composition holds every summary/close.
- **Bridges.** No Rust-to-Python bridges exist, by revision 16's decision: no verifier launcher, and no bridge from T9's `provider.record` to `update::app_record_sink`.
- **Scheduled refusal text.** The scheduled tick's fixed refusal reason is shown by review and by the existing scheduled hold proof. No test asserts the new suffix.
- **#1110's evidence.** Live credit sourcing, allowance verification, measurement and IF10 timing belong to #1110.
- **Cloud activation.** It remains an unresolved #1106 gap.
