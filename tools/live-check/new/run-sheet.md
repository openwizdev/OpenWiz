> Historical run-sheet format retained from the reviewed kit. This is not a new live authorization. See ../README.md for the November 5 lessons and remaining gaps. Version plans belong to #241.

# OpenWiz 0.0.4: the live check, run sheet

**Private. Never exported. Nothing here has run live.** The kit is proven on the fake `room-cli` only ([README](README.md)). It follows the §L defaults approved by Jake on 2026-10-30 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)), with two updates: **ADR 0015 moves the full check to a Local thread on the PC hub**; **L-11 is superseded by ADR 0009**: Jake approved scoped daytime checks alongside normal work on 2026-10-31 ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)). The check runs while Jake keeps using CloudRoom. The Mac is a browser screen only where named below; it hosts none of this run. **Nothing is created, sent or uploaded without Jake's go-ahead for this run.**

**When (L-1, release isolation):** after 0.0.3's live check (#10) passes, against an exact **`release-0.0.4`** head with every 0.0.4 ticket and receipt-reader fix #571/#583. The prepared baseline is `a724d38372bc7334f5c941628f93626f87cd5907`; re-read the branch at launch and record the actual `<H>`. The kit comes separately from its reviewed `main` commit `<K>`. **Never use current `main` binaries or contracts:** they have moved on, including bundled-CLI lookup, which bypasses this kit's PATH seam.

**Known S15 wording gap at that baseline:** `crates/core/src/new_thread/effects.rs` still says "your Mac must stay awake until the start is confirmed" (`mac_stays_awake`). The PC procedure cannot make that statement true. Record it as a wording gap, never as observed PC behaviour; recommend a separate product wording fix/review before accepting S15, then pin the new release head and recheck. This kit changes no product code or contracts.

**PC discovery basis:** ADR 0015, `private/machines.md`, and [#10's PC evidence](https://github.com/jparker2006/ClosedWiz/tree/c687079d6a7d62eb3169de4493321fc13fd3f52a/private/evidence/openwiz-0.0.3/ticket-3/pc). E6 there confirmed the PC; #13's endpoint slot is E7. That run used a stable wrapper for the app's bundled CLI, verified binary hashes, release contracts, and fresh throwaway threads. Its observed tell receipts inform S4 here; spawn and attachment receipts still need observation. CloudRoom is now v141 (Jake's context); record the version at launch, **never gate on it**. Nothing in this preparation is a new PC observation or permission to run.

**PC go recorded:** [Jake's approval on #13, 2026-11-04](https://github.com/jparker2006/ClosedWiz/issues/13#issuecomment-6628083588) accepts the PC checklist as recommended, including **both setup creates**, their SETUP text and the total cost below. It delegates project selection and cleanup to the orchestrator. Order: after #10's acceptance, this kit's review and merge, and #983 on `release-0.0.4`. Bind the approval to `<H>` and `<K>` locally before starting. Everything before J1 may run without Jake; J1 onward waits for him. A changed scope needs a new go.

**In one line:** the orchestrator selects the existing projects; the PC runner makes the two approved setup targets at A4.1, records their cost, and runs the CLI and web parts under the approved swap. Jake does J1–J6 on his phone, PC Chrome and Mac Safari. The runner wraps up and swaps back; the orchestrator archives the test threads.

**Who does what**
- **Jake, about 20 minutes in all:**
  - see the orchestrator's selected **P-A** and **P-N**, and the runner's fresh T-A/T-B targets, before J1; their ids stay on the PC;
  - transfer three synthetic files to Files on his iPhone (any method he chooses);
  - the recorded PC approval covers the cost line below, including setup;
  - the same approval covers the confirmed server swap and restore plan;
  - J1 to J6 on his phone, PC Chrome and Mac Safari, answering the runner in chat;
  - cleanup is delegated to the orchestrator: up to 6 test threads (2 setup + up to 4 check-created).
- **The runner:** a **Local thread on the PC**, running commands there directly, and relaying Jake's steps in chat. No `room-cli mac run --write`, Mac PATH prefix or Mac push. A Cloud preparation thread may use `room-cli mac run` only for read-only PC hostname/path/file-presence checks; no writes or live account calls during prep.
- **X1** (`new-kit.py`) runs and checks every step. It never says "pass": each step is `as_expected`, `not_as_expected: …` or `incomplete: …`, and **the first step that is not as expected stops the run.**
- **X2** (`x2-shim.py`) is first on `PATH` for every `openwiz` and for X1's `openwiz-server`. It counts every `thread spawn` and `thread tell`, lets through only the current step's one approved write (the project or thread, the harness, model and effort or the mode, the text's SHA-256, and each attached file's flag, SHA-256 and size, read at the moment of the call), once, and refuses everything else.

## How a check this short stays as strong while Jake works (ADR 0009)

**1. Every write and every write check touches only the test's own targets.**
- **P-A**, one project the orchestrator picks under Jake's recorded approval: an existing standard project with a GitHub remote **and no work in flight** (X1 stops before any create if one of its threads isn't quiet). The check creates make at most 4 new threads there, after A4.1's 2 setup creates.
- **T-A** (Local, codex on the PC) and **T-B** (Cloud, codex), **two fresh throwaway test threads**, for the two attachment sends. Do not reuse #10's threads: old event history can collide with cumulative landing checks. The **PC runner creates both at A4.1**, under Jake's recorded PC approval, in P-A **before X1 takes its baseline**, then waits for both idle with no queue. These are outside X2's L-8 ledger: their 2-create/2-first-turn cost is recorded separately in `$L/setup-cost.json`, with the receipts kept locally. No real work targets.
- Jake doesn't use P-A, T-A or T-B during the check.
- X2 lets a write through only if it names the step's target **by id** and carries exactly the step's settings, text and file bytes.
- Where each text landed is checked **by content**: on T-A and T-B from their first event, and on every thread P-A gained, from its oldest 100 events (L-9). The check is **cumulative**: every approved text, against everything the steps so far made, after every sequence, every late wait and at the end. **P-A must gain exactly one thread per create, each made by a step and carrying exactly that create's text.**
- The records, the op ids and the staged copies live in the check's own state directory.

**2. The bracket judges only "cold" sessions** (0.0.3's rule, unchanged). Each group is one bracket, reusing 0.0.1's quick check:
- **Judged:** **P-A's own sessions only** (the test project) that were quiet when the run started **and** not updated in the 48 hours before it, fixed at the start, each compared with its own row at the start on every field (and on pending interaction, queued work and activity). At least 20 are needed, or nothing is created. *(Jake, #13, 2026-11-05: brackets judge only the test's own threads and project while the factory runs; [private record](https://github.com/jparker2006/ClosedWiz/issues/13#issuecomment-6650598367).)*
- **Reported, never judged:** **every session outside the test's own threads and P-A** (Jake's, the factory's), sessions that appear during the run, the runner's and the orchestrator's threads, and the test's own threads (they have their own checks). Their changes are counted in each bracket's `not_judged_changed`, never a stop.

| Jake's concurrent use **cannot** confuse | Jake's concurrent use **can** … and then |
| --- | --- |
| Which project or thread a write reached: X2 checks the id, and Jake's CloudRoom never goes through X2 | Change sessions he is using. They are not judged; their changes are counted only |
| How many threads P-A gained, and what each carries: P-A has no work in flight, and Jake doesn't use it | **Start a thread in P-A.** It is one no step made: the run stops. **A false alarm, never a false pass.** Jake tells the runner |
| Where a text landed: by content, on the test's own targets | **Reopen a cold session in P-A** (older than 48 h): the run stops as a change in the test project. A false alarm, never a false pass. A session outside P-A is reported, never judged |
| Outcomes, op ids, records and staged copies: the check's own state directory | **Use OpenWiz's web page during the swap** (about 40 minutes): reads are fine; a create, send or upload that reaches X2 is refused, nothing reaches CloudRoom, but the run stops. So during the swap the web page writes only when the runner asks |
| Redispatches: X2 counts every write from the test's processes, including the quiet and late waits | Slow `room-cli` down. A read that times out makes the step **incomplete**, never passed |

**3. Faults act only on the test's own processes** (L-6).
- **The CLI killed mid-create** (C4) is an `openwiz` that X1 started: X2 makes the real `spawn`, holds its answer, and X1 kills that `openwiz`. It **may create one thread** (L-3's fourth).
- **The server killed mid-create** (W4) is X1's own 0.0.4 server, under the swap supervisor, killed by its handle during X2's hold **before** the call: nothing is created.
- **The phone's network cut mid-upload** (J4) is Jake's phone.
- `cloudflared`, Jake's running server and every other process are never signalled. The swap stops Jake's running server only after checking it is exactly the confirmed launch (command line, binary sha256, the one listening on 7370), and restores it on any exit. **One owner (#152's R2, the orchestrator's design):** the **guard** is X1's server's parent. It starts the server itself, stops it, confirms its exit (`waitpid`), and only then restores Jake's server. The supervisor never holds the server; it only asks the guard, over a pipe, and if the supervisor dies (the pipe closes) the guard ends the swap and restores. The server reads the guard's pipe too, so it never outlives the guard. **If the guard itself is killed**, X1's server stops with it and the state says `guard-died`: Jake's server is then restored by hand, as HANDOFF says.
- **Not run (L-6: no):** cutting the PC's network, stopping the tunnel, and the PC asleep after Created. **Gaps by decision.**

## The cost (L-8), for Jake's OK

From [`plan.json`](scripts/plan.json):
- **At most 4 new Cloud threads in P-A** (4 sandboxes, 4 Cloud agents from the plan): N-1 (CLI, claude-code), N-2 (CLI, codex), N-4 (CLI, killed mid-create: 0 or 1 thread), N-3 (web, one image).
- **2 attachment sends:** A-1 to T-B (CLI: a small PNG and a text file) and A-2 to T-A (web: a JPEG of exactly 10 MiB).
- **Setup, explicitly approved on #13 (2026-11-04; [private record](https://github.com/jparker2006/ClosedWiz/issues/13#issuecomment-6628083588)):** 2 throwaway threads (1 Local, 1 Cloud), each with the first prompt Jake approved. Approved **SETUP**: `OpenWiz acceptance setup: reply with the word ok, then stop.` (no trailing newline; SHA-256 `8a092a53be4a64e4677dcf31b6b512dff12deb6e910a8db2eeba620ad6032483`), used once per target. The runner uses it exactly twice at A4.1; `$L/setup-cost.json` records these two creates and first turns separately from L-8. That adds 2 first turns and 1 Cloud agent/sandbox: **at most 6 created threads in all (5 Cloud, 1 Local), 2 sends, 8 short turns**, before any recovery. A recovery needing replacement test threads needs its own explicit cost approval.
- **6 check turns:** each new thread's first prompt (4) and the two sends; each asks for "ok" or the files' SHA-256, then to stop. L-8 approved "about 8".
- **The file copies CloudRoom keeps** (B-1): each attached file is copied into CloudRoom's data folder on the PC and the thread's storage; the model provider may receive it. All 4 files sent are synthetic.
- **Every model is the catalogue's first for its harness, at its lowest effort**, picked by `new-kit.py settings` from that day's `openwiz models` (Jake sees them by name on his own screen at A6, and may name others: `settings --set codex=<model>/<effort>`).
- **The orchestrator archives up to 6 test threads (2 setup + up to 4 check-created) in CloudRoom afterwards**, as Jake explicitly delegated on #13. OpenWiz has no archive control.
- **The 4 check creates and 2 sends are the whole L-8 approval, across every sitting** (#168's R8). They live in the approval's file, `$A`, outside every sitting's work directory: X2 charges every write there, a fresh sitting inherits only what's left, and a recovery never renews them. **Only Jake amending L-8 raises them** (Recovery, below).
- **Go already recorded:** Jake's recorded PC approval of 2026-11-04 covers setup plus the check totals above; bind it to the actual heads and selections locally.

| Placeholder | Filled at launch (rechecked then: lesson 6) |
| --- | --- |
| `<H>` | the exact `release-0.0.4` head under test, including #583, after #10 passes |
| `<K>` | the commit with this kit, as Sol reviewed it |
| `<SHA-OW>`, `<SHA-SV>` | sha256 of `openwiz` and `openwiz-server`, built for the PC at `<H>` |
| `<ROOM-PC>` | absolute path to #10's stable wrapper for the PC app's bundled CLI; record wrapper and resolved bundle hashes locally, and recheck file presence after app updates. Never an unverified PATH executable |
| `<HOST>` | the public hostname. It stays on the PC, and is never committed or printed |
| `<RUNNER>`, `<ORCH>` | the runner's and the orchestrator's own thread ids. They stay on the PC |
| `<RESTORE-CMD>`, `<SHA-OLD>`, `<RESTORE-LOG>` | **the confirmed launch of the server Jake runs at the time** (0.0.3's, if he kept it after #10, else 0.0.2's): its command line as a JSON array of absolute paths, its binary's sha256, and the absolute path of the log it writes to. The runner reads them from the running server (`ps -o args=`, `sha256sum`) and checks them against HANDOFF before setup |

Shell names used below: `L="$HOME/openwiz-live-0.0.4"`, `K="$L/kit/tools/live-check/new/scripts"`, `O="$HOME/openwiz-0.0.4"`, `W="$L/w"`, `F="$L/files"`, and `A="$HOME/.openwiz-approvals/openwiz-0.0.4-L-8.json"`, **the approval's file** (#168's R8): outside every work directory and outside `$L`, so starting over never loses it.

---

## Screen A. Setup (runner about 15 minutes; Jake about 3 minutes)

| # | Who | What | Expected | Stop if |
| --- | --- | --- | --- | --- |
| A1 | Runner | Confirm the Local thread is on the intended PC (`hostname -s`, `uname -s`); check `<ROOM-PC>` and its resolved `/tmp/.mount_*/resources/app.asar.unpacked/node_modules/bb-app/host-daemon/dist/room-cli` exist. After the live-read go, record `<ROOM-PC> --version` | PC identity matches Jake's confirmation (E7, #10 E6); Linux; CloudRoom/CLI versions recorded, **never a gate** (#37); Python 3, `lsof`, `ps` and Rust available | endpoint differs, wrapper stale, a tool missing: stop; no automatic install |
| A2 | Runner | After setup approval, a fresh `release-0.0.4` checkout at `$O`, pinned to `<H>`; `cargo build --release --locked`; `sha256sum` of both binaries. Build the web export off-PC at the **same `<H>`**, on Node 24.22.1 (`npm ci --ignore-scripts && npm run build`), then verify its archive hash and per-file manifest on the PC into `$O/web-out` (#10 pattern; do not install Node on the PC) | head `<H>`; record `<SHA-OW>` and `<SHA-SV>`; manifest OK; fixture-only `kit-tests.sh` green on this release source (command below) | build fails, head differs |
| A3 | Runner | `mkdir -p "$L/kit"` (**not** a git repository). Locally extract from reviewed `<K>` these 6 files, keeping their paths under `kit/`: `private/evidence/openwiz-0.0.4/ticket-13/{texts.tsv,scripts/new-kit.py,scripts/x2-shim.py,scripts/plan.json}` and `private/evidence/openwiz-0.0.1/ticket-3/scripts/{quick-check.py,observe.py}`. Then write `$L/jake-targets.sh` (below) | each `sha256sum` equals `<K>`'s | a hash differs |
| A4 | Runner | **The files (L-7):** `/usr/bin/python3 "$K/new-kit.py" files --out "$F"` | the 6 files, each with its approved SHA-256 ([files.md](files.md)); `"all_approved": true` | exit 10 |
| A4.1 | **PC runner**, under the orchestrator | **Make T-A and T-B**, exactly once each, with the commands below. The orchestrator selects quiet existing P-A; Jake's recorded PC approval is the explicit go for these two creates and SETUP. Record their cost in `$L/setup-cost.json` before dispatch; keep receipts on the PC, wait for both idle/empty queue, and supply their fresh ids to A5 | 1 Local codex target on the PC + 1 Cloud codex target in P-A; 2 first turns; no project create; both idle before the baseline | a setting is not offered, unexpected outcome, missing receipt or uncertain create: stop, retain its charge, no retry |
| A5 | Runner; **Jake** transfers files before J1 | **L-2:** in the PC Terminal: `sh ~/openwiz-live-0.0.4/jake-targets.sh`, and paste the selected P-A id and A4.1's fresh T-A/T-B ids when asked. Show Jake P-A and P-N before J1. **Transfer** `syn-small.png`, `syn-10mib.jpg` and `syn-photo.heic` from the PC's `~/openwiz-live-0.0.4/files` to his iPhone (save to Files). For J3, Jake also transfers `syn-over.png`, `syn-photo.heic` and `syn-script.svg` to his Mac as browser input only | `targets.env`, mode 600 | — |
| A6 | Runner | **The approval, once** (`approval init`: the first sitting only, never again), then **setup** naming it, then **settings** (below). The orchestrator checks `new-kit.py map --work "$W" --show` locally: P-A's name, T-A's and T-B's titles, and the models picked. Record the selections under the approved scope and show Jake before J1 | `approval init`: 4 creates and 2 sends, nothing charged. `"setup": "ready"`; both sha256 values and the head match; `path_guard` is X2 and `read_guard` proves one successful models read through X2; `budget` equals the approval's `remaining` (4 and 2 in the first sitting). `settings`: both harnesses picked, an unoffered combination, the image harnesses and P-N found; the orchestrator selects P-N under the recorded approval; ids stay local | exit 10, `unoffered_found` false, or no image harness. `no_remote_project_found` false (no standard project without a remote, as on the PC on 2026-11-05) does not stop: C1-R2 is then skipped as a recorded gap, never run against another project (the orchestrator, #13) |
| A7 | Runner | **Lesson 6:** `new-kit.py recheck --work "$W"` (`thread spawn --help` and `thread tell --help`, kept on the PC; structure only). Then `new-kit.py map --work "$W"` | every flag OpenWiz passes still listed; T-A Local, T-B Cloud, both idle and visible; P-A quiet. No id or title printed | a flag missing: **stop and re-plan** |

**Fixture rehearsal (no account calls):** from a checkout of the reviewed kit `<K>`, point the suite at the separate release checkout `$O` so it builds that source, reads that source's contracts and uses its receipt fixtures:

```sh
CARGO_BUILD_JOBS=2 KIT_SOURCE_ROOT="$O" KIT_TARGET="$L/fixture-target" \
  sh tools/live-check/new/scripts/test/kit-tests.sh
```

This uses explicit fakes only. `KIT_SOURCE_ROOT` is required. Before any build or binary runs, the suite requires the reviewed PATH-based CLI/server wiring (hashes from the prepared release baseline); bundled lookup, missing files and unknown wiring stop it. A release change to that wiring needs a fresh review of the fixture seam. `setup` also proves one successful `openwiz models` read through X2 before enabling any write budget; a missing, wrong or failed read leaves writes disabled. Do not add workspace or browser suites to this rehearsal (Jake's credits rule).

**A4.1, the two approved setup creates (PC runner only, not run during preparation):**

The orchestrator selects P-A before these calls. Confirm `<PC-MACHINE-ID>` is the native PC machine, and fill the exact offered codex models/lowest efforts for that machine and Cloud from the bounded catalogue reads (`<ROOM-PC> provider models codex --machine <PC-MACHINE-ID> --json` and `<ROOM-PC> cloud status --json`). Recheck `thread spawn --help` once before either create; if these printed flags differ, stop. The command shapes come from the recorded [spawn help](../spike/shapes.md#thread-spawn---help), not an observed create. No defaults or substitutions.

Record `$L/setup-cost.json` locally, before dispatch: approval URL/date and the exact words from its private record, `<H>`/`<K>`, P-A and PC identity, SETUP's hash, each exact setting, and **two reserved creates/first turns (1 Local + 1 Cloud)**. Give T-B one stable `<SETUP-TB-REQUEST-ID>` there before calling it. Then run each command once; keep both raw receipts at mode 600 on the PC. Mark each charge dispatched, refused-before-call if proven, or uncertain; uncertainty stays charged. A missing acknowledgement means stop, never rerun either command.

```sh
( set -eu; umask 077
  L="$HOME/openwiz-live-0.0.4"
  SETUP='OpenWiz acceptance setup: reply with the word ok, then stop.'
  unset ROOM_THREAD_ID ROOM_PROJECT_ID
  for setup_var in $(env | sed -n 's/^\(BB_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$setup_var"; done
  '<ROOM-PC>' thread spawn --project '<P-A>' --machine '<PC-MACHINE-ID>' \
    --provider codex --model '<LOCAL-CODEX-MODEL>' --reasoning-level '<LOCAL-CODEX-EFFORT>' \
    --json --prompt "$SETUP" > "$L/setup-TA.receipt.json"
)
```

Validate T-A's receipt, reported placement/settings and charge before continuing. On any unexpected or uncertain result, stop here. Then make T-B once:

```sh
( set -eu; umask 077
  L="$HOME/openwiz-live-0.0.4"
  SETUP='OpenWiz acceptance setup: reply with the word ok, then stop.'
  unset ROOM_THREAD_ID ROOM_PROJECT_ID
  for setup_var in $(env | sed -n 's/^\(BB_[A-Za-z0-9_]*\)=.*/\1/p'); do unset "$setup_var"; done
  '<ROOM-PC>' thread spawn --project '<P-A>' --machine cloud \
    --provider codex --model '<CLOUD-CODEX-MODEL>' --reasoning-level '<CLOUD-CODEX-EFFORT>' \
    --request-id '<SETUP-TB-REQUEST-ID>' --json --prompt "$SETUP" > "$L/setup-TB.receipt.json"
)
```

Check both ids locally with `<ROOM-PC> thread show <id> --json`: both in P-A, codex, exact requested settings, T-A on the PC Local machine and T-B Cloud. Wait with bounded reads for both idle and queue empty; stop if either fails to settle within 15 minutes. Record the two setup outcomes and cost in `$L/setup-cost.json`, then enter the ids at A5. X1's baseline comes afterwards. The check's 4-create/2-send allowance remains in `$A`; setup never renews it. Replacement setup threads need new cost approval.

**A3's `jake-targets.sh`** (the ids appear only on Jake's own screen):

```sh
umask 077; f="$HOME/openwiz-live-0.0.4/targets.env"
printf 'P-A project id: '; read -r p; printf 'T-A id (fresh PC Local): '; read -r a; printf 'T-B id (fresh Cloud): '; read -r b
printf 'PA=%s\nTA=%s\nTB=%s\n' "$p" "$a" "$b" > "$f"; echo saved
```

**A6, setup and settings:**

```sh
( set -eu; export PATH="$HOME/.cargo/bin:$PATH"; L="$HOME/openwiz-live-0.0.4"
  K="$L/kit/tools/live-check/new/scripts"; O="$HOME/openwiz-0.0.4"
  A="$HOME/.openwiz-approvals/openwiz-0.0.4-L-8.json"
  /usr/bin/python3 "$K/new-kit.py" approval init --approval "$A"   # the first sitting only: never again for L-8
  /usr/bin/python3 "$K/new-kit.py" setup --work "$L/w" --approval "$A" --room-cli '<ROOM-PC>' \
    --openwiz "$O/target/release/openwiz" --server "$O/target/release/openwiz-server" \
    --targets "$L/targets.env" --files "$L/files" --contracts "$O/contracts" --checkout "$O" --expect-head '<H>' \
    --port 7370 --host '<HOST>' --web-root "$O/web-out" \
    --restore-cmd '<RESTORE-CMD>' --restore-log '<RESTORE-LOG>' --restore-sha256 '<SHA-OLD>' \
    --expect-sha256 '<SHA-OW>' --expect-server-sha256 '<SHA-SV>'
  /usr/bin/python3 "$K/new-kit.py" settings --work "$L/w" )
```

`settings` reads `openwiz models` once, through X2 (no write allowed), and one `project list`. It keeps, in the work directory only: each harness's model and effort, an **unoffered** combination for R-1 (one harness with a model only the other offers), the harnesses whose catalogue takes images, and **P-N**, a standard project without a remote, for R-2 (refused with zero calls; nothing touches it). If none exists, nothing is created to stand in for one (the approval allows existing projects only): `run` skips C1-R2 with the verdict `skipped: …`, and R-2 stays a fixture-only gap (the orchestrator, #13, 2026-11-05).

---

## Screen B. The CLI part (runner; about an hour; Jake keeps working, and doesn't touch P-A, T-A or T-B)

```sh
( export PATH="$HOME/.cargo/bin:$PATH"; L="$HOME/openwiz-live-0.0.4"
  K="$L/kit/tools/live-check/new/scripts"
  nohup /usr/bin/python3 "$K/new-kit.py" run --work "$L/w" --groups C0,C1,C2,C3,C4,C5 \
    --exclude-id '<RUNNER>' --exclude-id '<ORCH>' --forbid "$(id -un)" --forbid "$(hostname -s)" \
    > "$L/cli.out" 2> "$L/cli.err" < /dev/null & echo started )
```

The runner checks `tail -3 "$L/cli.err"` every 15 minutes or so: one line per step, giving the step and its verdict, with no id. **Defaults:** a 60 s settle after each sequence (until T-A, T-B and every new thread are idle with no queued message), a 180 s late wait after each group, polls every 5 s, 6 samples from the judged sessions, warm hours 48, at least 20 judged, and a 15-minute limit for a thread to become idle.

| Group | What X1 runs (X2 allows exactly the write named, or none) | Expected | Claims |
| --- | --- | --- | --- |
| **C0** | `openwiz models`; `openwiz new` for N-1 **without** `--yes` (the preview); `new --status` of an unknown op id | exit 0 (offered), 12 (ready, with the effect lines), 11 (no record). **0 writes.** Every report valid against `contracts/` | S4 (catalogue), S15 (effects stated) |
| **C1** | **L-4, the zero-call refusals:** R-1 an unoffered combination; R-2 P-N (no GitHub remote); R-3 `new --attach syn-over.png` (10 MiB + 1 byte); R-4 `send T-B --attach syn-photo.heic`; R-5 `send T-B --steer --attach syn-small.png` | exit 5 `refused` (`model_not_offered` or the effort's or harness's), 5 `refused` (`project_no_github_remote`), 5 (`image_too_large`), 5 (`unsupported_heif`), 2 (Steer can't carry attachments). **0 writes, nothing staged, no new thread** | S3, L-4, AL2, AL8 |
| **C2** | **N-1:** `openwiz new --project-id <P-A> --harness claude-code --model … --effort … --op-id … --yes --json -- '<N1>'` (**the dash prompt**). Then the same op id again, and `new --status` | exit 0 `created`, **1 spawn**; P-A gains exactly that thread; `thread show`: provider, model and effort **as requested**, Cloud, in P-A; its stages read until idle (S5); N-1 arrives **exactly**, with no attachment key. The rerun: `replayed`, **0 writes**, the same thread. Status: created, 0 writes | S1, S2, S5, S8, S11 |
| **C3** | **N-2:** two `openwiz new` at once, one op id, codex, **the file-path prompt** (a double submit). Then that op id with N-6's text, and with another effort | exactly **1 spawn**; one run exits 0, the other 7 (in progress) or 0 (replayed); P-A gains one thread; N-2 arrives exactly. The reuses: exit 8, `differs` text, then effort; **0 writes; N-6 never arrives** | S1, S2, S8, S11 |
| **C4** | **N-4, the CLI killed mid-create** (L-6): X2 makes the spawn and holds its answer 20 s; X1 kills that `openwiz`. Then `new --status`, a rerun of the op id, and a quiet settle and late wait | 1 spawn; P-A gains **0 or 1** thread, never 2 (if 1: its settings and N-4's text checked). Status: exit 6 `uncertain`, observations 0 or 1. The rerun: exit 6, **0 writes** (no redispatch). The waits: 0 writes | S6, S7 |
| **C5** | **A-1:** `openwiz send <T-B> --attach syn-notes.txt --attach syn-small.png --json -- '<A1>'` (queue) | exit 0, sent or queued; **1 tell**, with the text file as `--file` then the PNG as `--image`, each file's SHA-256 and size checked by X2 at the call; A-1 lands on T-B once; no staged copy left (AL7). The agent's report of both files' SHA-256 is **recorded, and decides nothing** (L-5; see below) | AL1, AL7 |

When it ends, the runner scans `cli.out` again (for ids, `<HOST>`, the account name), commits it as `live-cli.json`, and tells Jake **"CLI part as expected"** or **"stopped at <step>: <why>"**, in plain words.

---

## Screen C. The swap, and the web route part (runner; about 20 minutes)

**C1. The swap** (the Local runner acts under Jake's recorded PC approval, which explicitly covers swap start/end and the confirmed restore plan; a different plan needs a new go). For about 40 minutes, until screen E, his site runs 0.0.4 under X1. Reads work as before; writes happen only when the runner or a J step asks.
1. `new-kit.py swap --work "$W" start --minutes 90`.
   - **Expected:** `"swap": "up"`, `"old_was_running": true`.
   - **It refuses (exit 10) and signals nothing** if what listens on 7370 is not exactly the confirmed launch.
2. Check: local health on 7370 is 200 (now X1's 0.0.4), and the public hostname without a login gives 302.
3. **If anything goes wrong from here on,** the guard restores the confirmed launch by itself: on `end`, on the deadline, or when the supervisor dies. To end early: `new-kit.py swap --work "$W" end`. **If the guard is killed** (`"swap": "guard-died"`), X1's server has stopped with it: restore Jake's server by hand as HANDOFF says.

**C2. The web route** (runner): `new-kit.py run --work "$W" --groups W1,W2,W3,W4 --exclude-id '<RUNNER>' --exclude-id '<ORCH>' --forbid …`, in the background, as on screen B. X1 makes each request **exactly as the page does** (the same headers, bodies and op-id forms), to the port the tunnel serves.

| Group | What X1 does | Expected | Claims |
| --- | --- | --- | --- |
| W1 | The read routes the launcher and tray use: cloud options, the attachment list, the inventory, the new-thread preview (N-3's settings), N-1's status | every answer **HTTP 200 and valid against its contract** (types and nesting: #152's R6), for P-A, N-1's thread and the test threads. **0 writes** | S14 (fixture-only claim: read routes), S4 |
| W2 | R-1 through the create route (unoffered); R-5 through the send route (Steer with a staged PNG, then removed); the tray's uploads of `syn-over.png`, `syn-photo.heic` and `syn-script.svg` (removed again); **L-10's probes** on the create and upload routes, and **one unauthenticated create through the public hostname** | `refused` (200), 400; `failed: image_too_large`, `failed: unsupported_heif`, `ready` then removed; 421, 403, 403, 403, 403, 415 (create), 421, 403, 415 (upload); public: an **otherwise valid, page-shaped create with no login** gets **302, 401 or 403 from Access**, and **never reaches the app** (no OpenWiz headers or error body in the answer, no create in X1's server's log; #168's R7). **0 writes; nothing staged; no new thread** | S3, S9, L-10, AL2, AL8, AL10 |
| W3 | The network cut mid-upload, at the server: half of `syn-10mib.jpg`, then the connection goes | nothing staged; nothing half-written left; the list route valid. **0 writes** | AL3 (the server's half) |
| W4 | **The server killed mid-create** (L-6): N-5's create (codex), X2 holding 10 s **before** the call; the supervisor kills X1's server by its handle. Then the server starts again (a start dispatches nothing), a quiet settle, the status route, and the same body again | the page sees no answer (uncertain); X2 `aborted_parent_gone`, **0 calls ever**; status `uncertain`; the repeat `uncertain`, 0 writes; **N-5 never arrives; P-A gains nothing** | S6, S7 |

---

## Screen D. Jake's hands-on (about 15 minutes; the runner relays)

The runner starts `new-kit.py run --work "$W" --groups J1,J2,J3,J4,J5,J6 …` in the background, then tells Jake each step in chat (X1's `PRESS` lines, with the text to paste and, for J1, the harness, model and effort to pick). **Jake answers in chat, and the runner writes each answer to `$W/run/answer-<step>-<key>.txt`.** X1 waits for it (15 minutes at most per answer).

| Step | Jake | He answers | Expected | Claims |
| --- | --- | --- | --- | --- |
| **J1** (N-3) | **iPhone, Safari, Wi-Fi off (cellular).** New thread on P-A's heading; pick the settings the runner gives; attach `syn-small.png` from Files (the picker); paste N-3; **Start thread** | what the launcher showed; whether the details opened; and, in his own words, how the launcher looks and feels | **1 spawn** with the PNG as `--image` (its SHA-256 checked at the call); `created`; P-A gains that thread; its settings as requested; N-3 arrives exactly; the agent's report of the PNG's SHA-256 recorded (deciding nothing). Then X1 repeats Jake's request twice at once (a double press, a reload): **replayed, 0 writes**; and `openwiz new --status` of the web's op id: created, the same thread | S1, S2, S5, S8, S10, S12, S13, AL1 |
| **J2** (A-2) | **PC, Chrome.** Open T-A; drag `syn-10mib.jpg` from the files folder into the tray; wait for ready; paste A-2; **Send** | what the composer showed | **1 tell** to T-A with the JPEG (exactly 10 MiB) as `--image`; sent or queued; A-2 lands on T-A once; the agent's report recorded (deciding nothing); no staged copy left | AL1, AL2, AL7, S13 |
| **J3** | **Mac, Safari (browser screen only; the server stays on the PC).** Open T-B; drag `syn-over.png`, `syn-photo.heic` and `syn-script.svg` into the tray; look; remove all three; send nothing | over: refused; HEIC: refused; SVG: a plain file glyph (never rendered) | **0 writes**; nothing left staged | AL2, AL10, AL11 |
| **J4** | **iPhone, Safari.** Open T-B; paste U-1; attach `syn-10mib.jpg`, and **turn on Airplane Mode while it uploads**; wait; Airplane off; remove it; close the draft | the tray showed it failed, Send disabled, the text kept (`failed-kept`) | **0 writes**; nothing left staged; U-1 never arrives | AL3, AL5 |
| **J5** | **iPhone, Chrome.** Open the launcher on P-A; switch harness, model and effort; close it. *Optional:* pick a HEIC photo from his library in the tray, note what happens, remove it | `works`; HEIC photo: refused, converted, or skip (recorded: what iPhone does with HEIC) | **0 writes**; nothing left staged | S13 |
| **J6** | His acceptance of the launcher and the tray, **in his own words** to the runner | `accept` or `changes` for each | recorded at this head. **Either `changes` fails the UI gate** (exit 10; #168's R5): his words go to the design loop, and the release waits | S12, AL10, AL11 |

**If a setting or the text doesn't match** (a paste with an extra space, another model picked), X2 refuses the write: nothing is created or sent. **But that refusal taints the sitting** (below): X1 arms no write in it again, and every report of it ends not as expected. The runner tells Jake, and **recovers** (below): a fresh sitting under the same approval, for the groups still to run. What P-A already gained stays there and is never made again.

**Not covered on a phone:** Blink on Android (an allowed gap, L-12).

---

## Screen E. Wrap-up (runner; about 10 minutes)

1. **S10, parity:** `new-kit.py parity --work "$W"`: created (C2's N-1 from the CLI, J1's N-3 from the web) and refused (C1's R-1, W2's R-1): the same outcome and the same record shape (with `attachments` set aside: only N-3 carries one). No call.
2. **S4, receipts:** `new-kit.py receipts --work "$W"`: every captured `spawn` receipt has the structure of #11's fixture (`spawn-receipt-created.json`), and every tell receipt the **PC-observed structure** from #10 (sent: `threadId`, `ok`, `delivery`, `mode`; queued: those plus `queuedMessage`, including its observed nested keys/types; busy queue permits an agent sender id or a user/null sender; steer-queued has no `hardQueue`). Fixtures come from `<H>` alongside its contracts, including #583. Every receipt counts; a missing kind is drift (exit 10), and **drift blocks the claims that use it.**
3. **The swap back:** `new-kit.py swap --work "$W" end`. Expected: `"swap": "restored"`. Check health and the 302 as in C1. Then `new-kit.py map --work "$W" --after`: T-A and T-B idle, P-A's count.
4. **The staged copies:** `openwiz attachment ls --json` with `OPENWIZ_STATE_DIR="$W/state"`: nothing left from an accepted send or create (AL7); nothing ever staged by J3, J4 or J5.
5. **The approval's totals, last:** `new-kit.py approval show --approval "$A"`: at most 4 creates and 2 sends charged across every sitting, each by step and sitting, and what's left. Recorded in the run's log.
6. **The orchestrator archives up to 6 test threads**, under Jake's recorded cleanup approval: T-A and T-B (setup included), N-1, N-2, N-3, and N-4 if it made one. Keep uncertain charges and approval state; OpenWiz has no archive control.

## One sitting (#168's R1 and R3)

The whole check is **one sitting**, in one work directory:
- **Its write budget is fixed at setup, enabled only after the X2 read proof:** what's left under the approval (**4 creates and 2 sends** in the first sitting: L-3, L-5), in X2's ledger. X2 records each write there, by its plan step, under the same lock X1 arms and disarms with. A step whose write was already made **can never be armed again**, in any later run: a re-entry stops. A call that never reached `room-cli` gives its place back.
- **Its judged set is fixed by its first run** (screen B): the cold sessions, their rows, the samples and P-A's threads. Every later run (screens C and D) is judged against those, and checks them first: a judged session that changed between screens stops the run.
- **Any refusal taints the whole sitting** (#168's R6, the orchestrator's final rule). Every call X2 refuses, of any kind (a write, or anything off OpenWiz's allowlist), at any time (in a step, between steps or screens, during `settings`, at the very end), is written into X2's ledger as a taint, under its lock. **Every outcome is decided last**, as each report is published, from that ledger under the same lock: a tainted sitting is never as expected (exit 10), and the report names the refusals (step, kind, reason; never a value). X1 arms no write in a tainted sitting, and X2 admits none. **There is no acknowledged state: only a fresh sitting (a new setup) clears it.**
- **A held write is judged again after its hold,** under X2's lock, on everything it was judged on first: its step, its expiry, its target, settings or mode, text and each file's bytes, **and the ledger as it is then**: a sitting tainted during the hold (a refusal of any other call), or a ledger that can't be read, aborts it too (#168's R6, Jake's (a)). If anything no longer holds, it is aborted before `room-cli`, its place in the budget goes back, and a taint stays (#168's R2, round 2).
- **Anything that stopped the run** needs a fresh sitting for the groups still to run: the recovery below.

## One approval, every sitting (#168's R8, Jake's (a))

L-8's allowance, **at most 4 creates and 2 sends in all**, is the approval's, not a sitting's:
- **The approval's file** (`$A`) is made once (`approval init`, at the first A6) and named by every setup. It holds the total, every sitting (its number and work directory), and **every write charged under it**, by step and sitting. It is never remade: a lost or unreadable file stops every setup and every arm. Stop and ask Jake (a new file would forget what was used).
- **X2 charges each write there**, under the approval's own lock inside its writes.lock: it refuses a step whose write was made under the approval, in any sitting, and any write once the total is charged. **A charge goes back only when zero calls are proven** (a hold aborted before `room-cli`). Every other charge stays, **uncertain ones included** (X2 killed during a hold, say).
- **X1 arms no write** whose step was made under the approval, or once the approval's allowance is used up.
- **A fresh setup inherits only what's left:** its budget is the approval's remaining allowance; asking for more stops it.
- **Only Jake amending the approval raises the total**, in his own words: `new-kit.py approval amend --approval "$A" --creates N --sends M --jake-said '<his words>'`. They stay in the file; the runner quotes them in the run's log.

## Recovery: a fresh sitting under the same approval

In this order, every time:
1. **The cumulative totals first:** `/usr/bin/python3 "$K/new-kit.py" approval show --approval "$A"`. The runner writes them into the run's log before anything else: the total, what is charged (made, and uncertain), **what's left**, and every made write by step and sitting.
2. **The groups still to run:** only those with no write in `made`. **A completed create or send is never repeated** (X1 refuses to arm it; X2 refuses it too): its evidence stays in the sitting that made it, whose work directory the approval's file names (on the PC only). What that group hadn't checked yet stays incomplete; Jake decides.
3. **A new setup**, in a new work directory (`$L/w2`, `$L/w3`, …), with the same `--approval "$A"` and targets. Its report's `budget` and `approval.remaining` must equal step 1's what's left. **It carries the earlier sittings' landing** (#13, 2026-11-05): every earlier sitting's expected texts and new threads, and P-A's threads at the first sitting's start, merged into its run directory (`carried.json` names them), so the texts already on T-A, T-B and the new threads are expected, not a stop. A sitting that charged a write but whose records can't be read stops the setup.
4. **The groups still to run**, in that sitting. If what's left can't cover them, the run stops before arming: more needs Jake to amend the approval (above).
5. **At the wrap-up,** S10 (parity) and S4 (receipts) read the sitting they run in: run them in each sitting that made writes. A pair split across sittings (N-1's and N-3's records, say) is reported incomplete, never as expected.

## What stops the run (all parts)

Every report X1 prints is first scanned for every session's id and title, every project's id, name and remote, every machine's id and name, the targets' and new threads' titles, the model names, the hostname, the account name and every path of the work directory. **Every non-empty string counts, however short,** and the scan walks every decoded key and string value (#152's R4). A hit prints nothing: the report stays on the PC only. **Every command exits 10 when its outcome is not as expected.**

- **P-A gains a thread no step made, two threads for one create, or a thread in another project:** S1. **The release is blocked.**
- **A setting that differs from the request** (`thread show`'s provider, model or effort), **or a substituted one:** S2 or S3. **The release is blocked.**
- **X2 refuses any call** (another target, setting, text or file, a redispatch, a write in a quiet or late wait or between steps, or a call off the allowlist): the sitting is tainted, and S3, S6, S7 or S8 fails with it. **The release is blocked.**
- **A text in the wrong place, twice, altered, or with an attachment key it was sent without:** S11, AL1.
- **The agent's report of the files' SHA-256 (AL1) decides nothing** (L-5: "recorded as just that"; #168's R4, round 2). The kit records where 64-hex strings appear after the prompt (event type and field, never a value), and a verdict about **the agent's reply only**: `matches`, `differs` or `absent`, **only if the reply's shape is named at setup** (`--agent-reply TYPE:FIELD`, once it is observed); otherwise `unattributed`. Upload, system or tool metadata never stands in. **The evidence that intact bytes left the PC is X2's own check** of each file's SHA-256 and size at the call. Sol and Jake read the agent's report as just that.
- **A judged (cold) session changes, or a sample gains an event:** S1. **The release is blocked** unless Jake says it was him; then the groups still to run go to a fresh sitting (the recovery above), and nothing already made is made again.
- **A write already made under the approval, or past its allowance:** X1 stops before arming it, and X2 refuses it (the sitting tainted). It is never repeated; more needs Jake to amend the approval.
- **An answer that breaks its contract** (any report or route, checked against `contracts/` at `<H>`): S4.
- **Incomplete:** for example, fewer than 20 judged sessions in P-A, a thread not idle within 15 minutes, an unreadable field, a missing answer. The claim stays unproved, never passed.

## Separate quick Mac check (ADR 0015)

When Jake is at the Mac, get his go to install this exact release and run only `openwiz ls` and `openwiz show` read-only. Record head, versions and result with the release. This is separate from the full PC run; the Mac-asleep, Mac CLI-location and machine-enrolment checks stay Mac-only. J3 also needs his Mac as a Safari screen: if unavailable, stop that step and ask Jake to accept a stated desktop-Safari gap, never silently pass it.

## Afterwards (runner)

- Scan every report again for ids, the hostname, the account name, titles and model names. Then commit `live-cli.json`, `live-web.json`, `live-jake.json`, `parity.json` and `receipt-structure.json` under `private/evidence/openwiz-0.0.4/ticket-13/live/`. Commit nothing else from `$L`. Keep the work directories until Jake has read the reports, then delete them. **Keep `$A`** until 0.0.4's live check is accepted or Jake closes L-8; it is never committed. Retain `$L/setup-cost.json` and the setup receipts while any setup charge is uncertain; neither is committed.
- For each claim, record its result, its evidence class (live observation; the agent's SHA-256 report is recorded as the agent's report), the exact head and tree, and its gaps. Jake's design acceptance is his own words from J1 and J6. Then Sol reviews the exact candidate, and the release draft is prepared (#13).
- **Allowed gaps (L-12), stated now:** request-ID survival after a deletion; asynchronous delivery failures, unless one happens; Blink on the phone; the retry (A-3: there is none); a harness without attachment support, if none exists; the PC asleep after Created; a second identity (L-10). **Not run by decision (L-6):** the PC's network cut and the tunnel stopped.
