# Agent GitHub reads v1 (`openwiz.agent-github-reads.v1`)

C1 of #2291, approved revision 1 (#2308). This is a contract and synthetic
conformance proof. It delivers no runtime reader, installation, deployment,
credential migration, live observation or new authority. C8 (#2315) implements
it offline; C9 (#2316) is Jake's installation; C10 (#2317) migrates explicitly
inventoried readers; C13 (#2320) supplies separately authorized live evidence.
The setup and open-development contracts remain authoritative.

## Existing seam and its limit

The participating reads already cross script boundaries:
`skills/launch-fleet/scripts/fleet.sh` (`rest`, `rest_pages`, `gql`) and
`skills/where-are-we/scripts/read-github.py` (the `gh` read collector).
The former already keeps a sandbox-local conditional REST cache. Existing
`tools/install/setup/store.py` uses an owner-only file, an exclusive file lock
and atomic replacement; `tools/github-app/app.py` supplies protected state and
installation-token guards. These are the supported **same-owner filesystem**
and script invocation seams. C8 may reuse them at its owned `read.py` boundary;
C10 preserves the callers' output, queries, allowlists and authority checks.

All participating processes must reach the **same** owner-controlled state
and installation lock on the same host. Use a separate protected read-cache
namespace under that existing state, outside Git. A directory of the same name
in another sandbox is not shared state. A per-agent cache, copied lock, token
or quota file does not establish sharing. C8 must prove sharing with separate
processes and verify that locking/atomic publication work before admitting it.
This contract does not claim that Cloud sandboxes share a filesystem.

An unavailable shared state, remote caller requiring a new transport, daemon,
server, machine, permission or other architecture is a **stop for Jake**, with
a Builder question on the ticket. No cross-host mechanism is selected here.
An unavailable seam refuses; it never silently becomes independent caches.

## Read authentication and permission checklist for C9

- Jake explicitly authorizes the App installation and exact selected
  repositories. Installation or live rollout is not authorized by this file.
- Reuse the existing OpenWiz App and protected provisioning. The product App's
  profile in `contracts/setup.v1.md` stays unchanged. Downscope **read tokens**
  to Metadata, Contents, Issues, Pull requests, Checks and Actions, each `read`,
  the exact existing `tools/github-app/app.py:PERMISSIONS` profile. No new App
  permission, webhook, account/organisation scope or permission upgrade.
- Select repositories explicitly; independently verify canonical identity,
  installation ownership, selected scope, granted permissions, suspension,
  revocation and expiry. Public visibility does not waive the installation
  requirement. Missing or uncertain evidence refuses readiness/migration.
- The token must be a short-lived **installation** access token. App JWTs are
  for the existing token mint only. App user tokens, personal tokens, `gh`
  login and silent user-quota fallback are refused by the migrated read path.
  Preserve the existing mint guard: no expired token, and no remaining lifetime
  beyond one hour plus its existing five-minute clock-skew tolerance.
- Reuse `tools/github-app/mint-token.py` under C8's scoped changes. Capture its
  token output privately in memory/a pipe; never let it reach a terminal or
  log. Keep keys in the existing `<state>/service/app` protection, owner-only
  directories (0700), regular single-link files (0600), verified owner and no
  symlink traversal, following `app.py`. Provision, rotate and revoke only by
  existing protected secret handling. A cache never stores a token or key.
- Keep tokens/keys out of prompts, process arguments, URLs, diagnostics,
  fixtures and Git. HTTP Authorization is set internally; provider error
  bodies and exceptions must not be echoed. Response payloads remain private
  owner state and are not telemetry. Closed schema records hold no credentials.
- Writes and Git push retain their existing distinct authority/credentials.
  Only already-allowlisted reads are accepted. REST mutations and GraphQL
  mutations are refused; token minting is solely the existing auth operation,
  not an arbitrary POST accepted by the reader. A query containing a mutation
  or unknown operation is not a read merely because it uses GraphQL.
- C9 records authorized scope, protected provisioning, expiry/revocation and
  cost evidence with private-record pointers. App/read costs belong to the
  same $60 whole monthly CI bill, including plan/runner/storage costs; stricter
  budgets remain. Unknown cost authorizes no purchase. A requested installation
  or success-looking setup screen is not C9's verified completion receipt.

## Complete requests and cache identity

`agent-github-reads.v1.schema.json` defines closed `record` and `current` shapes.
Integers are never booleans or strings. Duplicate/unknown keys, nonfinite
numbers, unknown enums and embedded credential fields refuse. Times are UTC
Unix seconds supplied by controlled fixtures here; runtime clocks and evidence
must be independently verified. The only supported API host is `api.github.com`;
no caller URL, redirects or credentials in an endpoint are accepted.

A request binds canonical lowercase repository, API (`rest`/`graphql`),
read-only operation and **complete-request** `request_sha256`. C8 computes it
from the actual allowlisted request, never trusts a caller's claimed hash.
The hash input must unambiguously encode host, canonical repository, HTTP
method, full endpoint/path, all ordered/repeated query parameters, exact
GraphQL document and operation name/variables, body, Accept/API-version and
other response-affecting headers, and pagination policy/limits. Conditional
ETags are cache metadata, not different logical requests. Never hash a token
into a public record. Changing any response-affecting input changes identity.
`purpose` distinguishes display from authority use, even for identical data.

A cache key contains the host, installation id, selected repository set,
canonical requested repository, **effective permission set**, authorization
`generation` and complete request. A permission change, repository removal,
suspension/revocation or uncertain scope invalidates old entries and in-flight
publication, even if an ETag is unchanged. Recheck authorization under the
installation lock before publishing or returning. Token renewal does not
change quota or bless an old authorization generation. Missing/expired/revoked
credentials refuse before any cached private data is returned.

For simultaneous identical requests with matching authorization and freshness
requirements, hold/recheck the shared in-flight state and coalesce to one
upstream logical read (possibly multiple HTTP pages). Readers that arrive too
late for that read's challenge cannot use it for authority. Failed/crashed
leaders cannot leave an entry marked complete. Publish the complete result
atomically only after validation; partial files, errors and incomplete page
sets never replace a valid entry or extend its freshness.

## Pagination, conditional reads and freshness

Every expected REST Link page and every GraphQL connection's pageInfo/cursor
chain must be complete. Missing/repeated/foreign links or cursors, changed
scope, truncation, bounds/timeouts, HTTP errors, GraphQL `errors` even with
HTTP 200, or unknown nested-page completeness produce an explicit gap, never
an empty success. Follow only allowlisted same-host, same-repository pages;
all pages and retries consume the same installation budget. Immutable-content
caching still requires a verified exact revision and permissions.

`current` is an **independently supplied** binding, not extracted from the
result. It names the current request, observed current authorization, `now`,
`read_started_at` challenge and the caller's required `max_age_s`. This
contract invents no universal TTL. Zero max age requires validation now. An
unknown clock/age or expiry refuses. The validator checks consistency only;
it cannot authenticate that the supplied binding actually came from GitHub.

- `fresh: current` requires complete authenticated successful data, a current
  active selected-repository installation, matching request/scope, verified
  times and admission evidence. For **authority** (approval, currentness,
  review, start or merge), both authorization observations and the upstream
  read must meet the caller's independent challenge. No cache-only hit qualifies.
- `display: cache` may return complete, still-authorized data within the explicit
  display freshness bound without spending a new request. It remains labelled
  cache and never becomes authority evidence. Age is measured from the last
  valid validation, not from cache access. Expired credentials still refuse.
- REST 304 is usable only for the exact complete cached representation, matching
  ETag, same authorization generation and an authenticated conditional read
  within the challenge. Revalidate **every page**; one 304 cannot cover missing
  pages, changed query, changed permissions or other current approval inputs.
  `fetched_at` retains original body time; `validated_at` records successful
  validation. Neither a 304 nor these fields alone grants approval authority.
- `refused` names a fixed reason (shape, binding, credential, sharing,
  incomplete, freshness, conditional, authority-needs-current-read or budget).
  No raw token, URL, query, response body or exception is printed.

The existing approval fingerprint, exact-head review, independent holds,
required checks and merge admission/readback still apply. A conforming read is
one input to those checks, never approval or merge evidence by itself.

## Shared quota, pacing and refusal

The **budget/lock key is host + installation**, deliberately independent of
agent, token, repository and cache partitions. One installation has shared
REST and GraphQL primary pools; the pools have different units (REST requests
and GraphQL points). More callers, repositories, tokens and entries create no
additional allowance. Limits come from verified observations, not a hardcoded
plan promise. All participating consumers reserve under the same installation
lock, including concurrent callers with different requests/permission scopes.

Each pool records limit, remaining, outstanding reserved cost, reset time and
observation time; unknown is null. Reserve conservative per-request/page/query
cost before admission and reconcile actual response costs/headers without
double-spending outstanding work. Coalesced callers do not each reserve the
same upstream work. Unobserved traffic must remain a gap, never extra capacity.
Unknown/stale/contradictory pools prevent an unbounded read. A bounded budget
probe must itself be paced/accounted; it is not a personal-token fallback.

`deferred: budget-unknown` covers unknown/stale pools or a reset deadline reached
without a new verified observation. Passing reset time never refills a local
counter. `deferred: primary-budget` covers either pool's remaining <= reserved.
`deferred: backoff` covers a future pacing or secondary-limit deadline. Expired
credentials cannot be renewed into a new budget. Existing stricter holds and
C3's overload policy remain separate; this contract supplies no resume policy.

Honour Retry-After, primary reset headers and shared secondary backoff even
when primary remaining is positive. With no usable secondary retry evidence,
use GitHub's minimum delay and increasing bounded backoff; do not spin/retry
indefinitely. Persist the latest conservative deadline/reservations across
processes and restart. A new token/process cannot clear it. Return a deferred
outcome for the scheduler rather than keeping an agent awake. Tests use a
controlled clock; no live exhaustion or destructive edge case is permitted.

## Offline proof and later seams

The checkout validator, its release registration and its synthetic fixtures are
historical evidence (#1150). The shared reader now lives in WizSkills at
`skills/launch-fleet/scripts/carried/read.py`. C9 uses the checklist, C10 uses the
request/result/freshness interface, and C13 uses the same distinctions when
assessing live sharing. Independent interface review of the exact head remains
required. Synthetic conformance does not verify runtime permissions, credential
protection, concurrency or account.

Provider semantics checked against GitHub's primary documentation on 2026-11-10:
[installation authentication](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation),
[REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api),
[GraphQL rate limits](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api),
and [conditional reads/backoff](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api).
These references explain provider behavior; the approved plan supplies scope.
