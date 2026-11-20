# First-hour recording and fault providers (#2222)

P12 of #2194: the recovery and recording providers for
[first-hour evidence](../README.md#evidence-and-validation). The web page's
fault cases and their recording provider went with the web view (#1264).

| File | What |
| --- | --- |
| `document.ts` | Builds one `recovery` document per case from what the case observed: drafts by the SHA-256 of their exact bytes, pending intents by id and request fingerprint, the provider's counts. `codes()` returns #2200's codes for it. |
| `codes.py` | `check` gives #2200's codes for each document (it loads `../../first-hour-contract/check.py` by path). `owner-cases` runs the owner-state cases through existing tools: `setup_interrupted` through `tools/install/access/access.py` with its recording provider, and `update_rejected` through `tools/install/install.py` on a synthetic bundle. |
| `evidence/` | The red-first run, the mutation runs, and the scoped checks. |

The page's state owners (`Composers`, `Launchers`, a decision slot's storage
and receipt) and the owner-state tools are used through their public
interfaces and are not changed here.

**Scope (J13, 2026-11-13).** Drafts are kept within the same tab (reload) and
across a server restart, through the tab's sessionStorage. After a browser
restart, the owner's records are read back from owner state, and tab-only
drafts come out as `retention_unproven`, never as retained. Keeping drafts
across a browser restart is #2492's job.

**Seams for #2204.** The installed journey reruns these cases. It can swap
`RecordingProvider` for the installed server over the fake `room-cli`, because
the cases only use its `fetch`, `fault`, `restart`, `readBack` and counters.
It also reuses `document.ts`'s `recovery`/`observed`/`codes` and `codes.py
owner-cases` unchanged.

**Proof limits.** Every value is synthetic, and each document is a `recording`:
never a pass, and `candidate_unknown` with no installed candidate. These cases
prove behaviour at the contract seam only. The installed journey, live logins,
real time, security review and how the screens look stay Unverified.
**Named gap: `removal_default`.** Nothing on main removes an installation yet
(contracts/install.v1.md leaves removal to later tickets), so it has no case
here. The orchestrator's ruling on #2222 (2026-11-13) keeps it a named gap, and
#2204 reruns that case once a removal owner exists.
