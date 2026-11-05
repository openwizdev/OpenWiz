# Agent GitHub reads

`read.py` (C8, #2315) implements [the agent read contract](../../contracts/agent-github-reads.v1.md)
offline: one installation-authenticated GitHub read, shared and cached across
the processes of one owner on one host, and paced against the installation's
one budget. `test_contract.py` (C1) is the contract's synthetic validator.

Nothing here installs an App, holds a credential, or reads GitHub by itself.
Using it live needs C9's authorized installation; migrating agents to it is C10.

## Use

```sh
python3 -I tools/github-reads/read.py rest OWNER/NAME 'repos/OWNER/NAME/issues/1/comments?per_page=100' \
    --purpose display --max-age 300
printf '%s' "$QUERY" | python3 -I tools/github-reads/read.py graphql OWNER/NAME \
    --variables '{"owner":"OWNER","name":"NAME"}' --purpose authority --max-age 60 --challenge "$TICK_START"
```

- **stdout** is the complete response: one body per REST page (every `Link`
  page, `--single-page` for the first only), or the GraphQL body. Nothing on
  any refusal.
- **stderr** is one line: `fresh: current`, `display: cache`,
  `refused: <reason>` or `deferred: <reason> until=<unix seconds>`.
  Reasons are the contract's fixed words. Exit 0 fresh/display, 1 refused or
  deferred, 2 invalid invocation. Tokens, keys, URLs, queries and provider
  bodies are never printed.
- `--purpose authority` (approval, currentness, review, start, merge) is only
  ever answered by an upstream read, or a REST 304 revalidation of every page,
  started at or after `--challenge` (default: this call's start), with the
  authorization also verified since then. A completed cache hit never answers it. A caller may
  reuse only the result
  of a qualifying leader it actually joined while that read was in flight.
  A later challenge waits for the existing leader, then validates separately.
- `--purpose display` may answer from the shared cache within `--max-age`,
  measured from the last validation, labelled `display: cache`. Authorization
  and budget observations must also meet the age bound, at admission and
  completion. Zero age refuses when that bound cannot be met.
- `deferred` is for the caller's scheduler: wait until the time given. Never
  spin; never fall back to `gh` or a personal token.

## What it accepts

Only `GET` under `repos/<REPO>/` (no host, scheme, credentials or `..`), with
`application/vnd.github+json` or `application/vnd.github.raw+json`; and one
GraphQL `query` with no string literal (values go in `--variables`; `owner`
and `name`, when given, must name REPO). Mutations, subscriptions, other
methods, endpoints and repositories outside the selection refuse before any
call. REST pages follow only same-host links for the exact original resource
path, preserving every non-pagination query parameter, including page size,
filters and ordering. Only `page`, `before` and `after` may change.
Numeric `repositories/<id>` links refuse because this seam has no independently
verified canonical numeric repository identity. A 304 merges current Link
metadata into the cached page chain; changed ETags refuse as conditional.

GraphQL uses a bounded selection grammar. It supports aliases, scalar arguments
and variables, single-object fields (`repository`, `viewer`, `user`,
`organization`, `node`, `issue`, `pullRequest`, `commit`, `author`, `committer`,
`actor`, `milestone`, `rateLimit`), and connections with exactly one `first` or
`last` bound from 1 to 100. Each connection must select `pageInfo` with both
`hasNextPage` and `hasPreviousPage`, including when aliased, and both must be
false in the response. Nested connections follow the same rule. Fragments,
directives, input objects, defaults and unrecognized composite selections
refuse as incomplete, before any call. GraphQL `errors`, missing selected
fields or incomplete/unknown pagination also refuse.

## Shared state and authentication

Under the App's existing state (`<state>/service/`, the `--state-dir` /
`OPENWIZ_STATE_DIR` rules of `tools/github-app`), the owner-only
`github-reads/` directory holds:

| File | What |
| --- | --- |
| `installation.json` | Written once at C9: `{"installation_id": N, "repositories": ["owner/name", ...]}` (lowercase, one owner, 0600) |
| `installation-N.lock` | The one exclusive lock for host + installation |
| `installation-N.json` | Authorization generation, both budget pools, reservations, in-flight reads, backoff and pacing deadlines; no token |
| `entry-<sha256>.json` | One complete, validated response, keyed by installation, selection, repository, permissions, generation and the complete request |

Every invocation, including followers and display-cache hits, independently
verifies authorization by minting a short-lived installation token with
`tools/github-app/mint-token.py --repository ...` (the read-only profile,
downscoped to the selection), kept in memory only. A failed or changed grant
starts a new generation, so no older entry can answer it. Missing, expired,
revoked, suspended or foreign credentials refuse before any cached body is
returned. Mint results bind to the authorization generation observed before
they start; a newer denial or uncertainty supersedes an older successful mint.
Observation age includes time spent waiting to publish under the lock.

Budget: a pool must have been observed (`/rate_limit`, then every response's
rate headers) before a read is admitted; each page reserves its cost under the
lock. GraphQL reserves one plus the maximum number of connection nodes in
the supported selection tree, multiplying nested bounds and counting aliases
separately. This deliberately exceeds [GitHub's normalized connection-cost
calculation](https://docs.github.com/en/graphql/overview/rate-limits-and-query-limits-for-the-graphql-api#predicting-the-point-value-of-a-query).
Rate headers reconcile actual remaining quota; missing headers debit the full
bound. A dead caller or a lost response also debits its uncertain reservation.
Unconfirmed debits remain separate from the provider observation floor across
reset changes, expired deadlines and invalid observations. A delayed header or
probe naming a new window cannot establish when another request spent quota.
Invalid evidence makes the observation unusable while retaining its debits
and charging the invalid response's own unresolved request cost.
This reader has no independent reconciliation of uncertain spending windows,
so it conservatively retains those debits indefinitely, which can underuse
quota or keep reads deferred across resets. A freshness refusal after an
upstream request does not refund its cost.
Budget probes persist an attempt count and a 60-second retry deadline before
HTTP, including on failed/malformed responses or process loss. Reset passing
never refills a pool; it makes it unknown until observed
again. `Retry-After`, a zero primary pool and secondary limits set shared
deadlines (60 s minimum, doubling to an hour) that a new process or token
cannot clear. Below a tenth of a pool, reads are spread until its reset.

## Proof

`python3 -I tools/github-reads/test_read.py` runs a recording GitHub on
loopback and separate caller processes; CI runs it as `release:ci2-shared-reads`.
Red runs are `fixtures/reads/red-read.txt`, `red-review.txt` and
`red-review-admission.txt` and `red-review-probe.txt` in that same folder. R1–R10 regressions exercise the
reader CLI and recording transport, including separate processes, not live
GitHub. `red-review-round2.txt` and `red-review-round2-auth.txt` record the
concurrent authorization, mixed settlement and resource/filter-switch gaps;
`green-review-round2.txt` records the affected reader suite after correction.
`red-review-final-r3.txt`, `red-review-final-r3-probe.txt` and
`red-review-final-r3-invalid.txt` record the final
R3 regressions: REST/GraphQL callers admitted before reset with reordered
new-window responses, headerless/lost responses, same-window and fully
accounted controls, and invalid-observation recovery through a new-window
probe. `green-review-final-r3.txt` records scoped results.
Fixture evidence only: it proves
no live installation, sharing or quota behaviour (C13).

## Limits

- One host: callers must share this filesystem and process table. Another
  sandbox or machine is not shared state; it refuses or needs Jake's decision.
- Each invocation mints its own token, including followers and cache hits.
  Data coalescing does not remove this independent authorization check.
- GraphQL connections are not paged here: a query must return complete
  connections, or it refuses.
