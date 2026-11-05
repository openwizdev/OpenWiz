# PC activation v1

The bounded executor is `activation.Executor(setup, manager, provider, clock)`.
Its public calls are `preview()` and `execute(request_json)`. The pinned request
and companion journal use `contract.v1.schema.json`. This interface is delivered
for #2379's installed integration under the approved #1093 revision 13.

The evidence class is synthetic recording proof. Native PC start, protected
credential provisioning, logout/reboot and installed acceptance remain
Unverified. Cloud activation and secret transport retain their separate owners.
LE1, MD11-M, SRC1, live, account, spending, publication and acceptance gates
retain their recorded owners. T12 must establish its ownership allocation and
consume the login contract before composing an installed activation path.

## Resource and authority

The selected resource is the PC owner's systemd user unit `openwiz.service`.
The effect is `/usr/bin/systemctl --user enable --now openwiz.service`.
`platform.runtime.PcManager` reuses `Manager`'s verified installation inspection,
private platform lock, definition publication, FragmentPath check and optional
user-unit link. Its runner must be explicitly injected. T9 exposes no executable
command, installed activation route, environment bypass or default native runner.

Enable/start holds the existing verified installer's `install.lock` through
dispatch, then revalidates the complete pinned binding under the platform effect
lock. A concurrent installer cannot replace `current` in that interval. A build
or config changed before either lock is acquired refuses the saved operation.

The definition is published under `<state>/service/platform/openwiz.service`.
Its exact bytes are produced by the existing Linux manager using the verified
installed service and selected repository environment. An existing unit with a
foreign FragmentPath or different definition is refused. The operation grants
no administrative linger action. Owner authorization for linger remains with
the later live kit.

Every request pins all of the following fields.

- `schema` is `openwiz.pc-activation.v1`, `host` is `pc`, and `action` is
  `enable_start`.
- `operation_id` is 32 lowercase hex digits from the saved setup operation.
- `revision` is the exact setup revision.
- `binding` has exactly `owner_uid`, `unit`, `root`, `state_root`, `repository`,
  `project`, `runtime`, `build`, `config_sha256`, `unit_sha256`, `app_id`,
  `installation_id` and `service_issue`.
- `request_hash` is the existing setup fingerprint of kind `activate_engine`
  and request `{"binding": BINDING, "revision": REVISION}`. The fingerprint uses
  sorted-key compact JSON inside `{"kind": KIND, "request": REQUEST}` and SHA-256.

The build is the 40 lowercase hex source from the verified installed manifest.
Runtime is its exact `VERSION SOURCE` pin. Owner is the effective user id.
Config hash covers the actual private service configuration bytes. Unit hash
covers the complete manager definition bytes. Root/state paths are absolute
ASCII paths of at most 1024 characters with no empty, dot or dot-dot component.
Repository, project, App ids and service issue match the selected setup state
and actual service config. The schema specifies the remaining structural
bounds. The reader additionally enforces hashes, build/runtime equality and
journal relationships. Duplicate keys, positional objects, wrong types,
unknown fields and non-finite numbers are refused.

`provider.authority(request, challenge, now)` must return exactly `request`,
`challenge`, `at` and `authorized`. The first two echo the exact validated
request and fresh challenge, `at` equals the current integer millisecond clock,
and `authorized` must be boolean true. The provider must freshly verify current
scoped owner authority and every independent prerequisite at that call. Request
possession or saved config alone grants no authority. The clock is explicitly
supplied by the composition and must be positive and monotonic relative to the
journal. No hardcoded expiration policy or inferred login signal is introduced.

## Protected App state

The existing protected GitHub App setup writes the key exclusively into
`<state>/service/app/private-key.pem` outside Git. The state, service and App
directories must be owned by the effective user with mode 0700. The key must be
an owner-held, singly linked regular file with mode 0600 and the existing
signer's size bound. Metadata checks reuse `platform/security.py`'s
no-follow, descriptor-relative boundary. T9 opens metadata descriptors and
reads zero key bytes. The existing signer retains key-byte access and tokens
remain in memory. Existing App ids are pinned from setup and service config.

No operator key import, credential argument, personal-token fallback or secret
provider body is accepted. The protected registration/installation flow remains
`tools/github-app/setup.py` with its saved `connect_app` operation. T9 consumes
that flow's protected state and performs no registration or token exchange.

## Journal and locking

`Store.activation_transaction` extends the existing `setup/.lock` transaction.
The lock is an owned, singly linked regular file with mode 0600, opened with
no-follow semantics and checked against its named inode after acquisition.
Preview stores an ordinary six-field `activate_engine` operation and a companion
`setup/pc-activation.json` journal. Existing setup readers consume the ordinary
operation. The companion carries the stricter activation fields under this
contract without widening their accepted operation shape.

The companion has exactly `schema`, `request`, `operation`, `created_at`,
`updated_at`, `started_at`, `record_at`, `record_state` and `outcome`. Its schema
is `openwiz.pc-activation.v1.journal`. The operation id/fingerprint match the
request. Times are integer epoch milliseconds under 2^53. Start and record
times begin null and fall within creation/update times once populated.
The operation's public effect and reason are fixed product strings.

The complete transaction holds the same setup lock through current-state reads,
claim persistence, supervisor observation/effect and record delivery. Every
replacement uses a private temporary file, file sync, rename and directory sync.
The companion is the effect fence and is synced before its ordinary setup
projection. A crash between these two replacements leaves the stronger claim
in the companion. A later transaction may repair that projection only after
finding its exact existing operation. Missing or conflicting operation identity
refuses further effects. Interrupted preview can leave a proposal in the
companion and no generic projection, which requires explicit reconciliation.
An unavailable or malformed journal is never treated as a completed activation.

Preview reuses the same journal/request for the same current selection. A
changed selection is refused for reconciliation. All activation ids are kept
under the existing bounded operation-retention rules. Concurrent callers serialize
on the same operation and clean wakes reopen that journal.

## Observation and start recovery

`provider.observe(request, challenge, now)` returns exactly `request`,
`challenge`, `at`, `state` and `lock`. Identity, challenge and clock obey the
same strict rules as authority. `state` is `healthy`, `not_applied` or `unknown`.
`lock` is `held`, `free` or `unknown`.

The provider must observe the actual resource's persisted operation binding,
owner, unit, selected repository/project/runtime/build/config, current service
health and exact `service/run.lock` holder together. Decorating a name-only or
build-only status response with the requested fields cannot establish this
observation. The existing service status alone lacks these bindings. A native
positive observer remains T12's integration responsibility. Until available,
that composition must hold activation.

`healthy` plus `held` requires fresh proof that this exact saved operation's
resource is currently healthy under its matching owner lock. A service that
predates any saved start holds. `not_applied` plus `free` requires positive proof
that this operation never took effect and cannot still complete. Absent status,
an inactive unit, an unavailable lock, stale health or a stopped service alone
cannot establish non-application.

| Saved state and fresh evidence | Result |
| --- | --- |
| Proposed plus proved non-application and current exact authority | Sync uncertain operation/start time, then invoke one enable/start |
| Lost reply, exception or interrupted effect | Keep uncertain, return held |
| Uncertain plus exact healthy resource and matching lock | Set applied without another start |
| Uncertain plus unknown, conflicting, stale or unreadable evidence | Keep uncertain and hold |
| Uncertain plus positively proved non-application and matching authority | Reuse the saved operation for a fresh attempt |
| Applied plus matching healthy resource | Preserve applied effect, continue its pending App record |
| Applied plus unavailable or changed resource | Preserve the known effect and hold further work |

Success replies alone never establish applied. A fresh observation must confirm
the resource. Storage failure before claim persistence performs zero supervisor
effects. A crash after claim persistence requires exact reconciliation even if
no start was dispatched. Provider diagnostics become fixed product reasons.

## Existing App sink handoff

`provider.record(service_issue, body)` is the adapter for the existing
`crates/service/src/update.rs::app_record_sink`. T12 owns that cross-language
composition. It must bind the sink to the exact request repository, issue and
App identity. A T9 recording provider supplies these outcomes offline.

- `confirmed` maps only to the sink's success after the exact returned comment
  URL/body read-back.
- `unsent` maps only to `RecordError::Unsent`, proving no comment was sent.
- `uncertain` maps to `RecordError::Uncertain` or any unavailable outcome.

The record body is compact sorted-key JSON with exactly `schema`
(`openwiz.pc-activation.v1.record`), `operation_id`, `request_hash`, `build`,
`outcome` (`applied`) and `at` (the saved start time). It contains synthetic-safe
technical identity and hashes, with zero local paths or credential bytes.
Before delivery the journal durably claims `record_state=uncertain` and its
record time. Only a definitely-unsent outcome restores retryability. Retrying
uses the exact same body and operation. An uncertain result or crash is held
across restart without another delivery. Reconciliation of that held delivery
requires the existing exact App read-back authority before any later action.

`operation.phase` preserves the known effect independently of record transport.
`outcome=applied` requires the resource currently healthy and the record confirmed.
`outcome=held` preserves uncertain effects or unavailable prerequisites.
`outcome=proposed` belongs to preview. A confirmed record is never reposted.

## Recording proof and downstream seam

`python3 -I tools/install/pc_activation/test_activation.py -v` drives the real
Store and Linux Manager against synthetic verified bundles, private temporary
state and recording supervisor/status/App providers. The registered
`release:install` wrapper runs it as a required subprocess and propagates failure.
The schema/reader refusal table uses the repository's existing schema checker.

Synthetic assumptions include exact-operation status/lock attestations and
current authority records supplied by recording providers. They establish the
executor contract and recovery behavior. Live observation retains its separate
evidence class and gates. The executor adds no scheduler registration, timer,
CloudRoom invocation, Cloud activation, update-channel selection or global
capacity/spending policy. T12 consumes this interface through its separately
owned installed handover.
