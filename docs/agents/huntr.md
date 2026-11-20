# huntr settings

Contract: Jake, 2026-11-01: risk-tier approval ([ADR 0014](../adr/0014-huntr-approves-by-risk-tier.md), #554) supersedes the earlier named-kind approval, pace and file-blocking rules ([private record](https://github.com/jparker2006/ClosedWiz/issues/1275#issuecomment-6704671951)). Jake, 2026-11-06: HC1/HV1 set the cap and priorities; PA2, PS1 and PS2 extend the priorities and security-hunter exception ([private record](https://github.com/jparker2006/ClosedWiz/issues/1457#issuecomment-6682983368), [private record](https://github.com/jparker2006/ClosedWiz/issues/1457#issuecomment-6683012198), [private record](https://github.com/jparker2006/ClosedWiz/issues/1457#issuecomment-6683177156)). These settings belong to the project, beside `fleet.md`; installed skills read the consuming project's settings. Huntr files work on OpenWiz in the repository selected from its clone or explicit setting; ClosedWiz holds private decision words, security reproducers and operational records. Public reports use the contract's pointer form and never expose thread ids or private content.

| Tier | Work | Proof |
| --- | --- | --- |
| 0 | Report only: audits and findings, no change | Named audit/report command; no changed files or lines |
| 1 | Tests and docs: nothing the product runs changes, including missing tests and missing/stale docs | Spec/coverage or docs check at a public seam |
| 2 | Same behaviour, better inside: cleanups, faster code, faster tests, clearer errors | Every existing test passes unchanged; any speed claim also has a before-and-after measurement on the same machine |
| 3 | Behaviour fixes: bugs, flaky tests, security holes in our own code, accessibility faults | A failing test first, then the same test passing |

Tier 0 ends with the report to the orchestrator, not a ready-for-agent handoff or a change builder. Findings requiring changes are separate tier 1–3 candidates with their own proof and gate decision. The orchestrator handles the report issue's disposition.

**Maximum approved tier:** `max_tier` in the JSON below, today **3** (inclusive, 0–3). Kind is a description, not a four-name allowlist. Features, contracts, dependencies and the never-list stay proposals. A kind fitting no tier cleanly becomes a **kind proposal**: kind, proposed tier, proof and three real examples, sent through the orchestrator to Jake for approval once; his approval is recorded as a comment on the switch issue whose first line starts `huntr kind approved:` and names the kind and its tier, and that comment is the durable record step 1 reads on every hunt; morning reports list new kind proposals. Never force uncertain work into a tier.

**Security:** security fixes are **proposals**, with no huntr approval or ready-for-agent handoff, until the merge loop enforces two independent exact-head approvals. A declaration or an approval comment cannot supply that enforcement. Send them to the orchestrator with `needs-triage`, no `huntr` label and no exploit details. They are classified in tier 3 and still need **two independent reviewers** and exact-head approvals before merge. File without exploit details until the verified merge, including comments, logs, fixtures and PR text. Keep the failing test private until then; the issue names a safe proof command and its evidence location without disclosing the exploit. No issue or PR approval overrides this extra review gate.

**Speed:** tier 2 needs before-and-after measurements on the **same machine**; no measurement, no speed approval. Faster tests retain assertions and still fail on a controlled planted break. Sol checks the evidence, and the reviewer checks the final change and unchanged existing tests.

One problem per ticket; **200 changed lines maximum per pull request**, counted as additions + deletions across the whole PR diff, including tests and evidence. A multi-ticket batch shares one 200-line cap, not 200 lines per ticket. Shared batch evidence counts once in that PR's total; it is not excluded or divided among tickets. The pre-build declaration is an estimate. The reviewer checks actual scope, tier, proof and line count and requests changes beyond them.

Before merging, split an oversized batch into separately reviewable PRs, each within the 200-line cap and approved scope, with its own required proof. For a mutation-coverage batch, each PR carries its own red-first mutation proof and passing baseline. Count each PR's complete diff against its base, including its evidence; do not split only the accounting while leaving one oversized PR.

Keep full-suite logs in CI or retained private storage outside the PR diff. Commit a compact command/result summary and a retrievable log reference; for a separately retained log, include its SHA-256 hash. Any summary or other evidence committed in the PR still counts toward its cap. Do not remove and re-add already merged tests or evidence merely to split a historical batch.

**Never:** the room-cli allowlist, approved limits, `release/openwiz/`, contracts/schema, dependencies/toolchain, CI workflows/actions/runner kit, skills and their registrations, `docs/agents/`, ADRs, grills, `AGENTS.md`, specs' issues, or paths owned by tickets being built or carrying an unresolved builder-start claim. Standalone issues only; no spec/plan edits. Features, side specs, live work, releases, publishing and spending require proposals and separate approval. Inside these limits be safe but liberal.

**Pace:** every 30 minutes; at most 50 open huntr work tickets. Approved fleets first. Two consecutive empty hunts pause until the next calendar day in the project's established timezone. Unavailable sources remain gaps, not empty hunts.

**Priority order (HV1, PA2, PS1, PS2):** the controller applies this order both when choosing hunting slices and when deciding which candidates to file first:

1. Factory, CI and throughput bugs, including slow tests over 10 seconds as measured speed fixes with the tier-2 proof above. Agent-misleading contradictions are explicitly priority 1. Merge-conflict hotspots and tangles (UC a) also belong here, as proposals only.
2. Correctness bugs in released features (0.0.1–0.0.5), including user-visible error messages, web accessibility and public-docs truth for the public OpenWiz README, AGENTS.md and CHANGELOG against what those versions actually do. Product performance is also here as tier 2: `openwiz ls`/`show`/`fleets` latency, server response times, web bundle size and load, and memory, each with same-machine before/after measurements and the tier-2 proof above.
3. Privacy leaks in anything Open development will export, including thread IDs, personal paths, real names and live content.
4. Flaky tests.
5. Missing tests: refusal-path tests first, since a fail-closed path without a proving test is the highest-value test gap; then other missing tests on recently changed code.
6. Other docs and wording last, only when they would mislead an agent.

Priority does not override the never-list, tier proofs or proposal and security holds. Until C2 (#1189) merges, skip fixes to `skills/*/SKILL.md` and `contracts/*` unless necessary: merges there put relying tickets on hold. Necessary fixes still require separate approval under the never-list.

| Role | Provider | Model | Effort |
| --- | --- | --- | --- |
| One controller per hunt | `codex` | `gpt-6.1-sol` | `xhigh` |
| Wide hunting and reruns | `codex` | `gpt-6.1-terra` | `high` |
| Change builder | `codex` | `gpt-6.1-sol` | `high` |

Source: Jake, 2026-11-10: HN2 replaces HN1; wide hunting and reruns use Codex Terra 6.1 High. The controller remains Codex Sol 6.1 XHigh and change builders remain Codex Sol 6.1 High ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6768723249)).

The Sol 6.1 XHigh controller judges and independently proves every finding before the gate. Split the codebase into areas and send one Terra 6.1 High hunter per area and category checklist slice: a dozen or more as the areas and categories require, with no artificial cap (ADR 0002). Record the area/category matrix and each slice's result or blocked gap; real resource capacity controls simultaneous heavy work, not total coverage. No silent model fallback. **Security-hunter exception (PS1):** when Codex is blocked by the provider's safety filter, run the security slice on Claude Opus 5.5 High hunters (`claude-code`, `claude-opus-5-5`, `high`) and record the exception. Security rules above remain unchanged: proposals only, quiet filing and two independent reviewers with exact-head approvals. Builders/reviewers use the existing fleet lifecycle, with an explicit Sol High builder assignment for huntr. A separate reviewer uses fleet settings and exact-head approval; all required CI and a verified merge remain mandatory.

**Switch:** issue #394. Use a comment whose first line is `huntr: on` or `huntr: off`, optionally followed by a spaced dash and reason (`huntr: on — resumed`). The newest first line starting `huntr:` decides; an unrecognized line such as `huntr: on hold` is off. Absent/unreadable state is off. “stop huntr” tells the orchestrator to post `huntr: off`. Off stops new hunts and approvals; existing builders continue.

**Approval form (only the gate may post it):**

```text
**Approved on its own by huntr, <date>, tier <tier>, kind <kind>:** under Jake's standing approval (ADR 0014).
Private record: <pointer to the ClosedWiz comment holding the standing approval>
```

The orchestrator tells Jake for now: found, approved, proposed, skipped, with ticket links and honest built/reviewed/landed states. Every eligible finding has the `huntr` label, tier, kind and named proof command. Proposals have `needs-triage`, no `huntr` label and no approval. Once OpenWiz runs loops, it runs huntr and its cockpit gets a panel; no product version number until then.

## Controller lease (#1685)

One controller at a time holds the **lease** on #394 by its **self-generated run ID**, never a thread ID. Generate it once at start, save it in the resumable state and keep it across wakes and retries. A fresh controller uses a new ID, with inherited run references kept separately; it never adopts a live holder's ID. Nothing requires `ROOM_THREAD_ID`, a harness ID, a self-identity lookup or listing threads. From the consuming repository root, `node <installed-huntr>/scripts/lease.mjs`:

- `id` prints a local UTC timestamp plus 12 random bytes as `huntr-YYYYMMDDTHHMMSSZ-<24 hex digits>`; it reads no GitHub or Cloudroom endpoint. Save this value as `<run>` before claiming.
- `claim <run>` posts `huntr lease: claim <run> for 45m`, reads every comment page back and replays the lease lines in comment order: a claim takes a free or expired lease, a renewal counts only from the live holder, a release frees it. The earlier claim wins a race and the later one exits 2 (`lost to`). A live lease held by another run refuses before posting.
- `renew <run> <index-file>` posts a checkpoint result's index under `huntr lease: renew <run> for 45m` and extends the lease; `release <run> <index-file>` posts the final result's index under `huntr lease: release <run>` and frees it. Neither posts for a controller that no longer holds the lease.
- `due <run> scheduled|hunter` reads only and prints whether this wake must post a checkpoint: always for a scheduled wake delivered to the same controller, for a hunter's completion only once the last result is 30 minutes old. It exits 2 for a run that does not hold the lease.
- `record <run> <index-file>` posts an index as it is, without a lease line, reads it back and leaves the lease unchanged: the final record of an off switch before any claim, or a lost lease's handoff. Its first line may not start with `huntr`, so it never reads as a switch, lease or kind-approval line.
- `status` prints the live holder, or null, and writes nothing.

A lease lasts **45 minutes** from its last claim or renewal, measured in GitHub's comment times (server time); only the precheck before a post reads the local clock. The 30-minute checkpoint keeps a working controller's lease; a controller that stops loses it within 45 minutes, and the next scheduled wake resumes from the durable record. Lease lines start `huntr lease:`, never `huntr:`, so they never change the switch. Older `claim`/`renew` comments containing `thread <thread>` still replay, keyed by their run ID, so an upgrade preserves an existing live lease. New commands take no thread argument and reject thread IDs as run IDs. A failed read or unconfirmed write exits 2: read `status` before retrying. Exit 2 always means: do not act as the controller.

**Reporting (#1734): #394 is the only report channel** back to the orchestrator, for checkpoints, final results, tier-0 audits, proposals and blockers. Finish by verifying every part and index and archiving the controller; no direct thread message or second delivery. A refused fresh controller posts nothing and archives, without forwarding a wake. If no completion or scheduled wake reaches the holder, a 30-minute result is unverified; the lease still expires after 45 minutes without renewal. Never poll, sleep or keep a watcher for a wake.

**First reconciliation (#1734):** This legacy migration rule applies only to the existing private ClosedWiz hunt, before cut-over; it is not new work on OpenWiz. Once #394 holds a verified record marking these eight abandoned, later hunts skip this step. Otherwise, before dispatch on the next hunt, read the inherited h1 checkpoint on #394 and mark all **eight hunters pending disposition** **abandoned**, with their slice, prior run reference and reason: "h1 ended without a verified final disposition; coverage is incomplete and ownership is released for a fresh hunt." Preserve their reports and unfiled candidates as unverified gaps. Post and verify the partial record with `renew` before those slices become eligible again. Missing entries or an unconfirmed record stop dispatch. Subsequent wakes retain the verified dispositions and never abandon a new owner. This is next-hunt work, not a claim that a builder has disposed of live hunters.

**Hunter provisioning:** each brief from `scripts/hunters.mjs brief` carries the pin and `scripts/provision.sh`, which the hunter runs itself: its own sandbox's `gh` login, its project copy or a fresh clone, `git fetch origin <pin>` and a detached checkout. A copy with uncommitted changes (staged, unstaged or untracked) is refused at `source` before and after the checkout, and never cleaned. It prints one line, `huntr hunter: ready <slice> at <pin>` or `huntr hunter: BLOCKED <slice> at <step>: <reason>` (steps `auth`, `source`, `clone`, `fetch`, `checkout`, `source-pin`). `scripts/hunters.mjs collect` counts a slice only for a report whose first line is `huntr hunter: report <slice> at <pin>`.

**Dry run:** `node --test <installed-huntr>/scripts/controller.test.mjs` generates run IDs without a thread identity, claims/refuses/expires/releases the lease, and runs a provisioning failure line, a partial result, a final result, a hunter wake just before a scheduled one, and an off switch's lease-less record on a fake GitHub and a fake hunter set, with no live reads or writes.

## Slice manifests (#696)

Each area/category slice keeps its latest compact manifest and result in the durable hunt record on #394. New cloud threads cannot rely on a previous sandbox's local files. Read the latest record including failed/incomplete attempts: never fall back to an older PASS over a newer failure. Preserve a reused PASS and its original run reference when recording a skip. A lost, malformed or unreadable record means run again and name the gap.

From a clean consuming repository root, use `node <installed-huntr>/scripts/manifest.mjs`:

1. `snapshot /tmp/plan.json > /tmp/snapshot.json` before the hunter reads. The plan has exactly `slice` (stable area/category), `source_only` (boolean), `questions` (the full checklist/proof brief), and `paths` with nonempty `source`, `test` and `policy` arrays. Paths are exact repository-relative files or directories ending in `/`; directory membership is hashed too, so additions/deletions invalidate reuse. Include all governing instructions, huntr/fleet/helper settings, relevant specs/contracts and test support, plus all source/test files the slice depends on. Record extra reads; if not covered, expand the plan and rerun before claiming reusable coverage.
2. `check /tmp/plan.json /tmp/previous.json` before dispatch. It prints a JSON `decision` of `skip` only for an identical plan, source/test/policy `files_sha256`, checker and clean PASS with no findings/gaps. The digest covers every file's kind, path, blob hash and executable mode, including directory membership. Unrelated commits alone do not invalidate reuse. Every other result prints `run`; an invalid plan/command can exit 2 and never authorizes a skip. The check writes no state.
3. After the hunter and controller have checked all inputs, `complete /tmp/snapshot.json /tmp/result.json > /tmp/completed.json`. The result has exactly `status` (`PASS`, `ISSUES` or `BLOCKED`), `findings` and `gaps` (arrays of safe technical strings). Completion refuses a changed/dirty checkout instead of assigning new hashes to unread work. Persist the compact completed JSON, with its owner, run reference, result and any gaps, using the numbered record procedure below. If completion fails, persist the incomplete snapshot and blocker; do not retain the prior PASS as the latest result.

Version 2 stores `files_sha256`, not the full file list. It is SHA-256 of the UTF-8 JSON array of entries, without extra whitespace: kinds in source/test/policy order, paths in lexical order within each kind, each entry's keys in `kind`, `path`, `blob`, `mode` order. The pinned Git base and plan can reconstruct that list; full listings may stay in local hunter evidence but are never needed from a vanished sandbox. Version 1 records refuse reuse and run again.

**Bounded numbered records:** GitHub comment bodies must stay within **65,536 characters**. Do not paste unbounded manifests, plans or ledgers into one comment. Serialize the complete hunt state (run identity, coverage, compact manifests/results, skips, ledger, ownership and pacing) to `/tmp/run-record.json`, then:

1. `pack /tmp/run-record.json > /tmp/parts.json` prints `sha256` and numbered `comments`. Each comment holds at most 65,536 UTF-8 bytes (also within the character limit), with part number/count and digest. The helper base64-encodes JSON to preserve Unicode and escaping across parts; it writes no GitHub state.
2. Post each prepared body serially on #394 with `gh issue comment 394 --body-file <part-file>`. Retain each returned comment ID and URL. **Read back every part** through `gh api repos/<owner>/<repo>/issues/comments/<id>` and compare its exact `body` to the prepared body. On an uncertain post, search #394's paginated comments by digest and part number, reconcile an existing exact match before retrying, and never treat missing/duplicate/changed parts as saved.
3. Collect the actual read-back bodies as a JSON array in `/tmp/readback.json`; `unpack /tmp/readback.json <expected-sha256> > /tmp/verified.json` requires every distinct part and the digest from `/tmp/parts.json`, then reconstructs the exact record. Missing, duplicate, malformed or altered parts refuse. Check the reconstructed run identity and state before proceeding.
4. Post a short main **index with links** to every part, the run identity, expected digest and part count. Keep the index within the same limit; if links alone would exceed it, use numbered area indexes with bounded bodies and link them from the root index. Read back all indexes, verify every link/ID/count/digest, and only then archive the controller. A fresh hunt finds the latest root index on #394, reads all linked parts/indexes, verifies with `unpack` and resumes that state; it never depends on local files. A partial write remains an unfinished handoff to reconcile, not a completed run.

Example plan (synthetic paths; use the consuming project's actual inputs):

```text
{"slice":"core/correctness","source_only":true,"questions":"Check synthetic bounds; run the named fixture proof.","paths":{"source":["crates/core/src/"],"test":["tests/proof/"],"policy":["AGENTS.md","docs/agents/huntr.md","skills/huntr/SKILL.md"]}}
```

Every slice records its reads/result, but reuse begins with deterministic source-only slices (the token audit's boundary). Set `source_only: false` for any changing external input, CI/review/issue/session monitoring, live checks, measurements or flaky trials; they always run even if repository blobs match. Hashes never prove fresh monitoring, a live result or absence of flakes. Keep switch/cap/start-claim reads and the six source watermarks fresh. A skipped slice is explicitly reused coverage, never a newly run hunter; report its identity, reason and original clean result on #394. Do not count missing monitoring as an empty successful hunt or alter the two-empty/day/night rules.

The controller archives all hunters, writes and reads back its #394 index and every numbered part, then runs `room-cli thread archive --self`. This includes off, paused, empty and blocked hunts; retain the controller only while an unsaved handoff is being reconciled. Fresh scheduled controllers resume from the durable record, preserving ownership and pacing.

## Hunting checklist (#598)

Check beyond reported bugs and recent conversations. These are questions to investigate, not permission to change a protected path or a product promise. Each item names its change tier and a proof to run at a public seam with synthetic inputs. Record the exact command, environment and result; an inspection lead without its proof stays unverified. Every finding still goes through classification, the gate and review: the never-list, one problem, 200 added+deleted lines and 50-open cap hold. Tier 2 also requires every existing test passing unchanged; every speed claim needs same-machine before/after measurements. Tier 3 needs a failing test first. Contract changes remain proposals; security keeps the two-reviewer hold and quiet filing above.

### Speed

- **Tier 2**: Can sequential work or waiting overlap safely, and are thread counts appropriate? **Proof:** Benchmark identical synthetic workloads before/after on the same machine, recording concurrency and unchanged results.
- **Tier 2**: Can extra passes, repeated file reads, I/O or network calls be reduced through batching or streaming? **Proof:** Count calls/reads on fixtures and measure same-machine before/after time and peak memory with identical results.
- **Tier 2**: Can allocations, copies or data structures improve, or can work exit early? **Proof:** Profile allocations and benchmark boundary fixtures before/after on the same machine, checking identical outputs.
- **Tier 2**: Can caching, startup, build time or test time improve, including slow tests and needless rebuilds? **Proof:** Measure cold/warm startup, incremental rebuilds or the same tests before/after on the same machine; retain assertions and show faster tests still fail on a controlled planted break.

### Size

- **Tier 2**: Is dead code or an unused export, flag, option or file removable without changing a public promise? **Proof:** Trace callers with `rg`, compile and run unchanged existing tests; removal of a promised command/option is a proposal.
- **Tier 2**: Can duplicate code or an oversized function become smaller without changing behaviour? **Proof:** Compare line counts and run existing public-seam fixtures unchanged for all callers.
- **Tier 2**: Are generated or vendored files committed unnecessarily? **Proof:** Rebuild and run unchanged tests from a clean synthetic checkout without those files; propose work touching dependencies, the never-list or unsupported paths.

### Correctness

- **Tier 3**: Can unchecked errors, panics or unwraps on input break a public operation? **Proof:** A synthetic malformed-input or injected-error regression fails first and passes after the fix.
- **Tier 3**: Are off-by-one cases, bounds and input validation at the edges correct? **Proof:** Run failing-first public-seam fixtures at zero, the exact boundary and one beyond it, with literal expected results.
- **Tier 3**: Can a timeout wait forever or a retry run without a cap? **Proof:** A bounded fault-injection test fails first on the missing termination or excess calls, then passes; approved-limit changes remain proposals.
- **Tier 3**: Can races, shared state or leaked files, processes or threads change outcomes? **Proof:** Use controlled interleavings or repeated failure-path fixtures that fail first on wrong results or exact resource counts, then pass.

### Security and privacy

- **Tier 3**: Can secrets or tokens reach logs, errors or files, or private data enter fixtures or exports? **Proof:** A private failing-first test plants synthetic canaries and checks every relevant output; file only a safe command and evidence location until verified merge.
- **Tier 3**: Can command/path injection or unsafe file permissions cross a trust boundary? **Proof:** Private synthetic-input and permission tests fail first at the public seam, then pass; withhold exploit details until verified merge.
- **Tier 3**: Does code trust unvalidated input from tools? **Proof:** A private failing-first test supplies malformed tool responses and verifies safe refusal; keep the reproducer private until verified merge.

All three remain proposals until the merge loop enforces two independent exact-head approvals; checklist classification grants no approval or ordinary builder handoff.

### Contracts and docs

- **Tier 1**: Do docs disagree with actual commands? **Proof:** Run the documented command against safe fixtures and assert its literal output against the documentation.
- **Tier 2**: Does help text or error text in code disagree with actual commands? **Proof:** Run the documented command against safe fixtures and assert its literal output against the documentation. Every existing test passes unchanged.
- **Tier 1**: Is a command or file missing documentation? **Proof:** Trace the public command/file and run a docs/coverage check showing the missing explanation and the corrected example.
- **Tier 1**: Do contracts or schemas drift from the code? **Proof:** Run the same literal good/bad fixtures through the contract/schema and public implementation and compare verdicts; any contract/schema edit is a proposal under the never-list.

### Tests

The tier follows the change, not this category: coverage/assertions are tier 1, speed changes tier 2 and flaky-test fixes tier 3 (ADR 0014, HW4–HW5; ruling on #598). Every test removal or consolidation in this category follows the test-audit rules below (coverage within 2 percentage points, every removed kill retained, protected tests only consolidated).

- **Tier 1**: Are claims untested, tests asserting nothing, or duplicate tests obscuring coverage? **Proof:** Trace spec claims to public-seam tests and show each added or retained assertion fails on a controlled planted break; removing or merging a duplicate follows the test-audit rules below.
- **Tier 3**: Are tests flaky under controlled reruns? **Proof:** Reproduce passing and failing runs with synthetic inputs, record failures/trials, then keep the failing-first regression and passing reruns; never weaken assertions or hide failures with retries.
- **Tier 2**: Can slow tests wait less or avoid duplicate work? **Proof:** Keep existing assertions unchanged, show the test still fails on a controlled planted break and measure the same tests before/after on the same machine.

#### Test audit (`test-audit`)

Flag junk tests with TA2's rules (#1689) and the test authoring gate in `skills/build-ticket` (TA1, #1688). These findings remove or consolidate tests only, so they are tier 1: no product code changes.

- **Tier 1**: Does a test prove nothing its retained neighbours don't: a self-comparison, a copied inventory, a source grep with no user-facing contract, a call-shape assertion, a mock that supplies the asserted behaviour, an expected value computed by the code under test, or a near-copy of a table case? **Proof:** On one pinned source and a fixed denominator, line coverage of the affected target stays within 2 percentage points, and every mutant a removed test kills is also killed by a retained test after the whole change. Missing, timed-out or build-failed results prove no kill, and unmeasured coverage blocks the cut.
- **Tier 1**: Can near-copies merge into one table or shared-fixture owner? **Proof:** The same guard: coverage within 2 percentage points, and every mutant a removed test kills is also killed by a retained test; every original scenario stays a named row that still fails on a controlled planted break.
- **Never deleted, only consolidated:** proof cases (P, M, N, AP, A, V and the checks), contract tests (API, schema, allowlist, security, release, storage, ordering) and the pending list's tests. Static or slow is not disposable. A baseline failure is a bug to report, never a test to delete. A CI-time saving is claimed only with the tier-2 same-machine before/after measurement.

### Developer experience

- **Tier 2**: Can an unclear error or a log missing context explain the same failure better? **Proof:** Exercise synthetic failure fixtures and verify useful safe context while existing behaviour tests pass unchanged; changed product promises remain proposals.
- **Tier 2**: Can a confusing internal name become clearer? **Proof:** Trace references with `rg`, compile and run unchanged existing tests; public command or contract renames remain proposals.

### Web UI

- **Tier 3**: Are there accessibility faults in labels, contrast, focus or 44-point targets, or layout breaks at 390 px? **Proof:** A failing-first browser fixture checks the affected state, keyboard/focus, accessibility scan or target geometry at the required viewport; record before/after renders.
- **Tier 2**: Can needless re-renders or polling be reduced without changing behaviour? **Proof:** Count renders/requests in controlled browser fixtures, run existing tests unchanged and measure same-machine before/after for any speed claim; changed approved timing limits remain proposals.
- **Tier 2**: Can bundle size shrink without changing behaviour? **Proof:** Compare clean-build byte counts and run existing browser tests unchanged; measure on the same machine if claiming faster loads. A UI fault discovered in either optimization needs tier-3 failing-first proof.

## Gate contract

Clarified on #396 (issuecomment-6557090156), with the cap raised by HC1 on #1457: count **all** other open `huntr` issues, excluding the candidate and switch #394; forty-nine allow the fiftieth, fifty refuse. Proposals carry no `huntr` label. Only tickets **being built** protect paths: their comments have the fleet's public `launch-fleet: starting`, `launch-fleet: started` or `launch-fleet: start checked, branch <branch>` as the first nonblank line. Private-repository readers also accept legacy `launch-fleet: started, thread <id>` and `launch-fleet: start checked, thread <id>, branch <branch>`; public writers use only the thread-free forms. Approval alone and refused/failed/withdrawn claims do not block files. An unresolved `starting` claim does block its files: the spawn may already be running while its result is unconfirmed. Preserve scope additions recorded in comments for started or start-claimed tickets, for every recorded start. Unstarted approved tickets do not block; when their builders start, they merge `main` in before working to pick up landed huntr fixes (HW3). A new start seen in the second snapshot blocks approval too. Unreadable or ambiguous scope refuses approval. The gate checks recorded intent; Sol checks the reproducer and the reviewer checks the actual diff.

From the consuming repository root, run `node <installed-huntr>/scripts/approve.mjs <issue-number>`. It needs the existing Node runtime and signed-in `gh`; `GH_REPO=owner/name` selects the repository, otherwise `gh repo view` selects it. Exit 0 means the one approval comment was posted; exit 2 means refusal or an unconfirmed write, with a reason on stderr. No refusal posts anything. A failed comment request can have an uncertain remote outcome: read the issue before retrying. The gate refuses any existing standalone approval rather than posting twice. It does not label, build, modify an issue body or execute the issue's proof command.

The JSON block below is the machine-readable policy, read by the gate. Prefixes protect whole directories or the named source files containing approved limits. Basename rules apply at every depth, including new dependency/toolchain files; schema suffixes apply everywhere. A protected prefix always wins over a tier. To introduce another limit-bearing file, update these settings under Jake's approval before huntr can own it. The PR reviewer must also refuse any change to an approved limit outside this catalog: paths cannot prove semantic scope.

Exact candidate files use ASCII repository-relative paths: no glob, directory, empty/dot/parent component, duplicate or ambiguous path. Existing tickets' formal scope is read from `## Owned paths` and `**Owned paths:**` declarations. Outside fences, any line (including a heading) mentioning owned paths or scope contributes its backticked paths and the contiguous bulleted or ordered list directly below it. A blank line or intervening prose ends that list; fenced examples never contribute paths. Read the path tokens and ignore surrounding prose/annotations. A directory-qualified glob protects the directory prefix before its first `*`; a bare filename protects matching names at any depth, and a bare name glob protects matching name prefixes at any depth, including their descendants. A directory token also protects children when its trailing slash was omitted. Obvious unformatted paths are conservatively protected too. For legacy standalone issue bodies without a scope declaration, conservatively protect their path-like tokens. Questions and status notes are conservative hints: named paths add protection, while pathless questions and non-widening status notes do not refuse. A non-legacy hint whose first line, with bold markers removed, does not end in `?` and asserts that owned paths or scope were added, widened, expanded or now include paths must yield a readable path token; otherwise refuse. They are not strict declarations. An explicit `none (a person's ticket)` declaration is a known empty scope. Otherwise refuse a formal declaration when it yields no path token, and refuse a being-built ticket with no readable scope. Scope additions are unioned. Candidate comment additions pass the same tier/never-list checks as its body. The issue is re-read before posting; an edited candidate or newly failing guard refuses approval. Tier 0 declares `none` and zero changed lines. Tier 1 files must be in the test/support or docs groups; tiers 2–3 may also use the code group. Tests/support allows fixtures of any extension; code uses source suffixes; docs use the docs prefix or a root Markdown file. A root Markdown file is documentation, subject to the never-list.


```json
{
  "version": 2,
  "label": "huntr",
  "switch_issue": 394,
  "max_changed_lines": 200,
  "open_cap": 50,
  "groups": {
    "code": {
      "prefixes": [
        "crates/core/src/",
        "crates/cli/src/",
        "crates/adapters/cloudroom/src/",
        "crates/adapters/github/src/"
      ],
      "suffixes": [
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".mjs",
        ".cjs"
      ],
      "root_suffixes": []
    },
    "tests": {
      "prefixes": [
        "tests/"
      ],
      "suffixes": [],
      "root_suffixes": []
    },
    "docs": {
      "prefixes": [
        "docs/"
      ],
      "suffixes": [],
      "root_suffixes": [
        ".md"
      ]
    }
  },
  "never_prefixes": [
    "crates/adapters/cloudroom/src/allowlist.rs",
    "crates/core/src/limits.rs",
    "crates/core/src/attachment.rs",
    "crates/core/src/messaging/mod.rs",
    "crates/core/src/messaging/reconcile.rs",
    "crates/core/src/new_thread/mod.rs",
    "crates/core/src/new_thread/start.rs",
    "crates/core/src/fleet/tickets.rs",
    "crates/core/src/fleet/fleets.rs",
    "crates/adapters/cloudroom/src/process.rs",
    "crates/adapters/github/src/process.rs",
    "crates/adapters/github/src/fleets.rs",
    "crates/adapters/github/src/writes.rs",
    "release/openwiz/",
    "contracts/",
    ".github/workflows/",
    ".github/actions/",
    "ci/runner/",
    ".githooks/",
    "skills/",
    ".claude/",
    ".agents/",
    ".claude-plugin/",
    "tests/checks/skills.rs",
    "docs/agents/",
    "docs/adr/",
    "docs/grills/"
  ],
  "never_names": [
    "AGENTS.md",
    "CLAUDE.md",
    "Cargo.toml",
    "Cargo.lock",
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "pnpm-workspace.yaml",
    "bun.lock",
    "bun.lockb",
    "deno.json",
    "deno.jsonc",
    "deno.lock",
    "pyproject.toml",
    "poetry.lock",
    "uv.lock",
    "Pipfile",
    "Pipfile.lock",
    "go.mod",
    "go.sum",
    "Gemfile",
    "Gemfile.lock",
    "composer.json",
    "composer.lock",
    "rust-toolchain",
    "rust-toolchain.toml",
    ".nvmrc",
    ".node-version",
    ".npmrc",
    "tsconfig.json"
  ],
  "never_name_prefixes": [
    "requirements",
    ".env",
    "next.config."
  ],
  "never_components": [
    ".git",
    ".cargo"
  ],
  "never_suffixes": [
    ".schema.json"
  ],
  "max_tier": 3,
  "tiers": {
    "0": [],
    "1": [
      "tests",
      "docs"
    ],
    "2": [
      "code",
      "tests",
      "docs"
    ],
    "3": [
      "code",
      "tests",
      "docs"
    ]
  }
}
```

## Finding issue form

Use these operative sections exactly once. Replace the synthetic values, keep the 200-line ceiling and the full never-list declaration. Add the affected commit, safe failing output, acceptance criteria and public-seam proof afterward. A blank or comment-only proof block is refused. The command is evidence already reproduced by Sol, not something the gate runs. Product promises must declare `No new features, contracts or dependencies.`; any change to those needs a proposal. Proof class is exactly `report` (0), `coverage-or-docs` (1), `unchanged-existing-tests` (2), or `failing-test-first` (3). Kind stays descriptive and grants no permission. For tier 2, Proof names the full existing test set passing unchanged; for tier 3 it names the failing-first test (a flake also records failures/trials and passing reruns). Speed proof is `none` when no speed is claimed; otherwise it is exactly `Machine: <one machine>`, `Before: <measurement>`, `After: <measurement>`, a blank line and a nonempty `sh` command fence for the reproducible comparison. Security fix must be `no` for automatic approval. A security declaration, including `yes; two reviewers; exploit details withheld until merge`, is refused until the merge loop enforces two exact-head approvals; file it as a proposal instead. The gate checks these declarations, not test results, speed semantics or concealed exploit content; Sol and the reviewers verify those facts. The problem field is one paragraph for one problem; its semantic scope is checked by Sol and the reviewer.

````markdown
## Tier

3

## Kind

bug fix

## Product promises

No new features, contracts or dependencies.

## Proof class

failing-test-first

## Problem

One synthetic ordering defect.

## Proof

```sh
synthetic-repro --fixture ordering
```

## Speed proof

none

## Security fix

no

## Owned paths

- `crates/core/src/ops.rs`
- `tests/proof/p01_list.rs`

## Size

120 / 200 changed lines (added + deleted)

## Never-list

The never-list in docs/agents/huntr.md applies in full.
````

Approval reads are a complete snapshot, not a GitHub transaction. Run approval commands serially from the hunt's single controller, reconciling duplicate wakes and uncertain writes. Truncated labels/comments, inconsistent counts, unknown scope and API errors refuse, never pass as empty. Issue pages and every issue, parent and switch comment connection, plus issue labels, are paginated to the end; each count must match before the gate trusts the read. No live gate approval or hunt is claimed by #396's fixtures.

## Confirmed grill trace (#554)

| Summary line | Operative rule |
| --- | --- |
| 1 / HW4 | Four risk tiers in the table; kind is descriptive |
| 2 / HW4 | JSON `max_tier: 3`; features/contracts/dependencies/never-list remain proposals |
| 3 / HW1, HW4, HW5 | Tier proof column; unchanged existing tests for 2, failing-first test for 3 |
| 4 / HW5 | Security paragraph: proposal hold until two-reviewer merge enforcement, plus quiet filing; Speed paragraph: same-machine before/after |
| 5 / HW6 | Kind proposals with kind/tier/proof/three real examples, through orchestrator to Jake once; the approval is recorded as a `huntr kind approved:` comment on the switch issue naming the kind and its tier, read by step 1 on every hunt; morning report |
| 6 / HW2, HC1 (#1457) | Pace paragraph and JSON `open_cap: 50`; 30-minute wakes, day and night |
| 7 / HW3 | Gate contract: started builders and unresolved start claims protect files; unstarted builders merge main on start |
