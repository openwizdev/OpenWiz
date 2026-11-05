# C1 proof plan (#2308)

Synthetic inputs only. No fixture is a live read, credential, installation,
shared-process execution, approval or merge receipt.

| Claim | Observable contract / plausible bug / existing gap | Proof |
| --- | --- | --- |
| C1-auth | Only active selected-repository installation read credentials; user-token fallback or a per-agent budget would bypass CS5. No agent-read contract exists. | schema/auth refusal table; independent current binding |
| C1-cache | Host, installation, repository, permissions, generation and complete request isolate results. A cache hit, partial pagination or 304 could otherwise bless stale authority. | changed-binding, partial/error, age, conditional and authority cases |
| C1-secret | Records contain no credential fields; protected owner-only state and distinct write authority are required. | closed schema and planted credential fields; interface review of the provisioning checklist |
| C1-budget | Both primary pools and secondary/pacing deadlines are installation-wide. Reset is not a new allowance without an observation. | exhausted/unknown/reset/backoff/reservation cases |
| C1-share | Concurrent identical readers share one upstream result only within the existing owner filesystem seam; unavailable sharing refuses. | simultaneous synthetic receipt and unavailable-seam cases; actual multiprocess proof belongs to C8 |
| C1-CI | Existing full and affected release plans must execute this validator and propagate failure. A test file alone would be undiscovered. | Plans.test_ci2_read_contract_is_in_full_and_affected_plans; Execution.test_ci2_read_contract_executes_and_propagates_failure |

Before changing a test, retain its claim above. Expected outcomes are literal
contract decisions, independent of the validator. No runtime helper, App setup,
credential migration or live shared-cache claim is delivered here.

Dependencies: Python standard library and the existing ci/escapes schema reader;
no new dependency. Independent exact-head interface review remains required.

R1 first correction, C1-cache: conditional 304 freshness belongs to REST only.
The prior table proved REST 304 and GraphQL 200 separately but missed their
GraphQL/304 combination. The added `graphql conditional 304 refused` case must
return `refused: conditional`; the existing two positive cases must stay fresh.
The failing-first run is `red-r1-graphql304.txt`; all inputs remain synthetic.

R2 first correction, C1-auth/cache: selected repositories bind as a set, with
no canonical list order. The prior table refused changed repository sets but
missed equal multi-repository sets listed in different orders. The added
`repository set order does not change binding` case must remain `fresh: current`;
the existing changed-set case must still refuse `binding`. The failing-first
run is `red-r2-repository-order.txt`; all inputs remain synthetic.
