# First-hour live kit: install instruction to the first verified merge

The bounded extension of the [0.0.13 live kit](live-kit.md) that #2207 runs for spec #2194's first hour (PR1, and PR2, PR4, PR5 and PR7's live parts). **Preparing it performs nothing live.** This file grants no live, account, feedback-send, spending, cut-over, ship or publishing authority by being merged. The 0.0.13 kit, its steps and its ten-minute target stay as they are; this kit adds its own steps and reuses that kit's timer only through its own record.

The kit's offline dry run, eligibility check and result validator are `tests/first-hour/kit.py` beside this file:

```sh
python3 -I tools/install/tests/first-hour/kit.py dry-run [<eligibility.json>]
python3 -I tools/install/tests/first-hour/kit.py eligibility <eligibility.json>
python3 -I tools/install/tests/first-hour/kit.py validate <result.json> --binding <binding.json> --eligibility <eligibility.json>
```

A passing dry run or validation proves the kit's shape and its rules, never a live result, an elapsed time or a usable login. The installed recording journey (`tests/first-hour/test_journey.py`) is synthetic proof of the same path; it is never a live observation.

## Eligibility

Final execution is refused until `kit.py eligibility` passes on a record of the current state. It refuses, naming each reason:

- **The graph:** the approved #2194 revision and its fingerprint, with the private-record pointer of its approval. A missing or unreadable approval refuses.
- **Every gate's producers:** each of the three first-hour gates (`cloudroom_setup` #2201, `paid_offer` #2202, `feedback` #2203) needs its exact producer tickets in the approved graph and each producer's verified merge (pull request, merge commit and approved head read back as merged), never a closed issue. Today `paid_offer` has #2293 and `feedback` has #2292; `cloudroom_setup` has no producer in the graph, so **this kit is ineligible** until its producer ticket is added under plan-graph's change control and merged. The kit never stands in for it.
- **Authority:** a private-record pointer for each scope the run uses: `live` (the run on the installed candidate), `account` (the owner-authorized repository, App and test-owned threads), `feedback_send` (one synthetic issue on the agreed destination) and `spending` (Cloud Credits within the bound). A missing scope refuses; standing authority must be checked against these exact steps and counts.
- **The candidate:** one checked candidate, bound below, with its green fixture integration and this kit's passing dry run read back first.

The record is one `openwiz.first-hour-kit-eligibility.v1` JSON object: `graph` (`revision`, `fingerprint`, `approval` pointer), `gates` (for each of the three gates, its producers, each `ticket`, `pr`, `merge_commit`, `approved_head` and `merged_at_head`) and `authority` (a pointer for each of `live`, `account`, `feedback_send` and `spending`).

## Binding

One `openwiz.first-hour-kit-binding.v1` JSON object, written before step H1 and never edited after:

- `candidate`: `version`, `source`, `target`, `manifest_sha256`, exactly first-hour.v1's candidate;
- `host`: `target` (one declared target, equal to the candidate's) and `fresh_account: true` (a disposable user account or machine with no prior OpenWiz state);
- `scope`: `repository` (`owner/name`, the owner-authorized repository, chosen by the owner, never the installer's demo) and `app_repositories` (exactly that repository);
- `counts`: the most of each effect the run may make: `builders`, `reviewers`, `merges`, `feedback_issues`, `shares` (each a nonnegative integer; `feedback_issues` and `shares` at most 1);
- `recorded`: `waits` and `help`, how many of each the run's log holds, so the result keeps every one;
- `graph`: `revision` and `fingerprint` of the approved #2194 graph.

The validator refuses a malformed binding, and a result for any other candidate, target or repository.

## Steps

Each step is bounded. `read` steps change nothing; `write` steps act only on the bound repository and test-owned resources; `spend` steps may use Cloud Credits within the bound. Stop at the first step whose bound would be exceeded, or whose producer is missing, and record a gap. A step that needs a gate is ineligible until that gate's producers are in the approved graph with verified merges (#2201's `cloudroom_setup` has none yet; #2202's `paid_offer` names #2293; #2203's `feedback` names #2292); the kit never implements it.

| Step | Name | Effect | Needs | Bound |
| --- | --- | --- | --- | --- |
| H1 | discovery | read | none | Read-only discovery of the host, the candidate's release, CloudRoom and the bound repository; record what exists |
| H2 | instruction | read | none | Open the public install instruction once on the fresh account; the first-hour clock starts here |
| H3 | install | write | none | Install the bound candidate once through the public instruction; no prior OpenWiz state |
| H4 | cloudroom | write | cloudroom_setup | CloudRoom's bundled install or reuse and its one sign-in screen; ineligible until its producer merges |
| H5 | connections | write | none | Connect the App to the bound repository only; record each component's setup.v1 evidence; a listed harness is not a usable login |
| H6 | refused-connection | read | none | One refused connection (a repository outside the App's selection), its message and that nothing took effect |
| H7 | idea | write | none | One genuinely fresh small idea on the bound repository: no prepared plan, no private operator steps |
| H8 | confirmations | write | none | The spec confirmation and the exact-plan approval, each saved separately and read back |
| H9 | fleet | spend | none | The approved frontier only, at most `counts.builders` builders, with the harness, model, effort and location the owner chose |
| H10 | interruption | write | none | One interruption and resumption on the run's own work (a reload, a lost reply or a restart); compare drafts, identities, branch and commit content and pending records before and after |
| H11 | review-and-ci | spend | none | One independent other-family review and the required CI on the first pull request's exact head; at most `counts.reviewers` reviewers |
| H12 | merge | write | none | The first merge through the standing merge rules, read back from GitHub at the approved head; the first-hour clock stops here; at most `counts.merges` |
| H13 | free-only | read | paid_offer | The installed copy says OpenWiz is free now and paid plans come later, with no paid offer or payment code |
| H14 | feedback-and-share | write | feedback | One explicitly approved synthetic feedback issue through the user's own login after its exact preview, and one share of public content only; at most `counts.feedback_issues` and `counts.shares` |
| H15 | cleanup | write | none | Stop only the kit's own threads and disposable resources; keep the evidence |

## Timing

Two independent targets, recorded separately; neither is derived from the other, and a second attempt never replaces the first:

- **The first hour (PR1):** first-hour.v1's clock, from H2 (the public instruction opened) to H12 (GitHub's merge time of the first verified merge, read back). Everything between counts; waits and help are recorded, never subtracted. Over `3600000` ms is a missed hour.
- **The first running fleet (#1110's target):** [live-kit.md](live-kit.md)'s definition, unchanged, recorded as the result's `ten_minute_fleet` (`owner: 1110`): `met`, `missed` or `unmeasured`. It never decides the hour.

## Result

One first-hour.v1 `result` document (`proof_class: live`, no synthetic assumptions, a private-record pointer to the raw evidence), checked against the binding:

- #2200's checks give its codes: any problem refuses it; any failure makes it a `fail`, reported as one.
- A `fixture` or `recording` document is refused as a live observation: it is synthetic proof, labelled as such.
- Its candidate, target and repository match the binding; its operations stay within `counts` (each effect at most once); its `waits` and `help` hold exactly the counts the binding recorded; and each gate's state and producers match the eligibility record's verified producers.
- Values are sanitized technical text only: no account names, thread or project ids, tokens, emails, machine paths or transcripts. The validator refuses anything that looks like one. Raw evidence stays private, reached by the pointer.
