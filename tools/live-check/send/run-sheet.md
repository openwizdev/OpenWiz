> Historical run-sheet format retained from the reviewed kit. This is not a new live authorization. See ../README.md for the November 5 lessons and remaining gaps. Version plans belong to #241.

# OpenWiz 0.0.3: the live test, run sheet

**Private. Never exported. Nothing here has run live.** The kit is proven on the fake `room-cli` only ([README](README.md)). It follows the section 4 defaults approved by Jake on 2026-10-30 ([private record](https://github.com/jparker2006/ClosedWiz/issues/2302#issuecomment-6765739196)), with one change.

**The change, approved by Jake on 2026-10-31:** scoped checks run alongside normal work and publishing, without an overnight window ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
- **The test now runs in the daytime, while Jake keeps using CloudRoom and his Mac.** There is no overnight window and no "don't use CloudRoom" rule.
- That supersedes **L-12** and `acceptance-lessons.md` **rule 8**, as recorded on `main` (ADR 0009).
- **L-11 is unchanged:** there is no second identity, and that stays an allowed gap.
- **Nothing is sent without Jake's go-ahead for this run.**

**In one line:** Jake makes three test threads (about 3 minutes). The runner runs the CLI part (about 2½ hours, while Jake works). Jake OKs the server swap. The runner runs the web route part (about 30 minutes). Jake does about 10 minutes on his phone. The runner wraps up and swaps back.

**Who does what**
- **Jake, about 15 minutes in all:**
  - make T-A, T-B and T-C, and paste their ids into one prompt on the Mac;
  - say "go" with the cost;
  - say "swap ok";
  - do three sends on his phone, answering the runner in chat.
- **The runner:** a Cloud thread. It works through `room-cli mac run --write`, starting every command with the `PATH` prefix from `acceptance-lessons.md`, and relays the phone steps to Jake in chat.
- **X1** (`send-kit.py`) runs and checks every step. It never says "pass": each step is `as_expected`, `not_as_expected: …` or `incomplete: …`, and **the first step that is not as expected stops the run.**
- **X2** (`x2-shim.py`) is first on `PATH` for every `openwiz` and for X1's `openwiz-server`. It counts every `thread tell`, lets through only the current step's approved test thread, mode and text hash (once), and refuses everything else. **A tell it holds before the call is authorised again after the hold** (Sol R12): if X1 disarmed or re-armed the step, or the step expired, during the hold, X2 calls nothing, logs `aborted_revoked` and exits 98, and X1 counts that as a failed step.

## How a test this short stays as strong while Jake works

**1. Every send and every send check touches only T-A, T-B and T-C.** These are new, empty threads made for the test. Jake never uses them himself.
- X2 lets a call through only if it names the step's test thread **by id**.
- Each text is a unique synthetic string, so where it landed is checked by content, on the test threads. The check is **cumulative**: all 22 texts on all three threads, counted from each thread's first event against everything the steps so far sent. It runs after every sequence, again after every late wait, and at the end of every run, so a duplicate that arrives later is still caught.
- The send records live in the test's own state directory.

**2. The bracket judges only "cold" sessions.** Each group is one bracket, which reuses 0.0.1's quick check: every session's list fields are compared, plus sampled sessions' events.
- **Judged:** sessions that were quiet when the run started **and** not updated in the 48 hours before it.
- **Reported, never judged:**
  - sessions Jake used in those 48 hours, or that were active;
  - sessions that appear during the run (his new threads, or a Loop's);
  - the runner's and the orchestrator's threads.
- **The judged set is fixed at the start of the sitting**, by the first run command (`run/sitting.json`), and every later run command (the web part, the phone part) uses the same set and the same baseline. It is counted in the report (the rule, how many are judged, how many are not). No id is printed, and no session can move into it later.
- **Each judged session is compared with its own row at the start, every time:** on the quick check's fields **and** on what decides quiet or active (pending interaction, queued work, activity). So a judged session that turns active is a failure, and can never be exempted afterwards.
- **Fewer than 20 judged sessions stops the run before any send.**
- **L13** passes the same rule to 0.0.1's quick check as `--exclude-id`. The test threads are judged there too, since they are quiet by then and the page reads them.

| Jake's concurrent use **cannot** confuse | Jake's concurrent use **can** … and then |
| --- | --- |
| Which thread a send reached. X2 checks the id, and Jake's CloudRoom never goes through X2 | Change sessions he is using. They are not judged; their changes are counted only |
| Where a text landed: by content, on the test threads | **Reopen a cold session** (older than 48 h). That stops the run as a change outside the test threads: **a false alarm, never a false pass.** Jake tells the runner. **The group cannot simply rerun:** its sends are charged to L-8's allowance (below); resending them needs Jake to amend L-8 |
| Outcomes, op ids and send records: the test's own state directory | **Send from OpenWiz's web page during the swap.** X2 refuses it, so nothing reaches any thread, but it stops the run. So during the swap (about 45 minutes), the web page only sends when the runner asks |
| Resends and redispatches. X2 counts every call from the test's processes, including the quiet and late waits | Slow `room-cli` down under heavy use. A read that times out makes the step **incomplete**, never passed |

**3. Faults act only on the test's own processes.**
- The killed CLI is an `openwiz` that X1 started.
- **For the web part, one approved `--write` step swaps Jake's site to 0.0.3.** Two small processes run it: a **guard**, which is the only parent and owner of X1's server, and a **supervisor**, which only makes requests to the guard over a pipe (take over, F4, F6, start again, end):
  - **Stopping 0.0.2:** the guard stops 0.0.2's server only after checking it is exactly the confirmed launch: the same command line, the binary's sha256, and that it is the one listening on 7370. Otherwise it stops and signals nothing.
  - **Running 0.0.3:** the guard runs X1's 0.0.3 server on `127.0.0.1:7370`, where Jake's `cloudflared` already sends the site, with X2 on its `PATH`. `cloudflared` is never touched.
    - The guard spawns a tiny **wrapper** as its own child, which starts the server only on the guard's "go".
    - The wrapper reads a pipe from the guard. On F4 or F6 it stops the server; **on the pipe's EOF (the guard died) it stops the server too, so the server can never outlive the guard.**
  - **How the guard stops the server:** it asks the wrapper, waits for it to exit, confirms that with `waitpid`, and only then restarts the confirmed 0.0.2 launch. It never signals a remembered PID.
  - **When the swap ends:** on `swap end`, the deadline (default 90 minutes), a signal or an error, the supervisor asks the guard to end. **If the supervisor dies or overruns, the guard does the same by itself:** it acts on its pipe's EOF, never on a status file. A crash or health timeout during any start, restarts after F4 and F6 included, also ends in the same restore.
  - **If the guard itself is killed,** X1's server dies with it, the supervisor records `guard-died`, and 0.0.2 is restarted by hand, as HANDOFF says.
  - Every armed send also **expires**, so a step left armed by a crash lets nothing through.
- **The faults during the swap:**
  - **F4** stops X1's server, and **F6** kills it. Both go through the supervisor, by its handle on its own child.
  - **F7** is Jake's phone in Airplane Mode.
- **Simplified (Sol, round 1): no relay, and no F5.** #10's L6 asks for "cutting the network" among others, and **F7 still covers that**: the browser loses the answer while the server finishes the send. F5 (the tunnel stopped) was one more process on Jake's Mac for the same evidence. L-6 approved F5, but no claim depends on it alone.

**4. Kept from the decided sheet:**
- structure-only evidence;
- **the dash text M13 first, alone** (C1; L-3), with any surprise there stopping the run;
- stop on any surprise;
- the texts and their hashes (L-5);
- the faults (L-6);
- no paused-queue test (L-7);
- the observer reads (L-10).

**The cost (L-8), from [`plan.json`](scripts/plan.json):**
- **23 messages reach `room-cli`:** 13 from the CLI, 7 from X1 through the web route, and 3 from Jake's phone.
- **They make 22 turns:** 17 short ones and 5 of about two minutes (M02, M04, M11, M07, M09). M12 starts no turn, and M18 and M20 are held back by design.
- L-8 initially approved about 20 messages; the reviewed historical sheet records Jake's approval of 23 ([private record](https://github.com/jparker2006/ClosedWiz/issues/2302#issuecomment-6765739196)). This preservation of the recorded allowance grants no new run or allowance reset.

| Placeholder | Filled at launch (rechecked then: lesson 6) |
| --- | --- |
| `<H>` | the head under test (L-2): `release-0.0.3`, with the U5 ticket and #9 (#91, the route; #92, the composer, merged at `85598b5`) |
| `<K>` | the commit with this kit, as Sol reviewed it |
| `<SHA-OW>`, `<SHA-SV>` | sha256 of `openwiz` and `openwiz-server`, built on the Mac at `<H>` |
| `<HOST>` | the public hostname. It stays on the Mac, and is never committed or printed |
| `<RUNNER>`, `<ORCH>` | the runner's and the orchestrator's own thread ids. They stay on the Mac |
| `<RESTORE-CMD>`, `<SHA-02>` | **the confirmed 0.0.2 launch:** HANDOFF's command line as a JSON array with operator-supplied absolute server-binary and web-root paths (for example `["<ABSOLUTE-SERVER-BINARY>", "--port", "7370", "--allowed-host", "<HOST>", "--web-root", "<ABSOLUTE-WEB-ROOT>"]`), and its binary's sha256. The runner reads both from the running server (`ps -o args=`, `shasum -a 256`) and checks them against HANDOFF before setup. HANDOFF and 0.0.2's live-check note give different sha256 values, so the runner confirms which is current |

Shell names used below: `L="$HOME/openwiz-live-0.0.3"`, `K="$L/kit/tools/live-check/send/scripts"`, `O="$HOME/openwiz-0.0.3"`, `W="$L/w"`.

---

## Screen A. Setup (runner about 15 minutes; Jake about 3 minutes)

| # | Who | What | Expected | Stop if |
| --- | --- | --- | --- | --- |
| A1 | Runner | **L-1:** `sw_vers -productName; room-cli --version` | `macOS`; the version is recorded, never a gate | not macOS |
| A2 | Runner | **L-2:** a fresh checkout of `<H>` at `$O`; `cargo build --release --locked`; `shasum -a 256` of both binaries. Bring `web-out` with its manifest, as for 0.0.2 | head `<H>`; record `<SHA-OW>` and `<SHA-SV>`; manifest OK | build fails, head differs |
| A3 | Runner | `mkdir -p "$L/kit"` (**not** a git repository). `room-cli mac push` these 8 files, keeping their paths under `kit/`: `private/evidence/openwiz-0.0.3/ticket-3/{texts.tsv,scripts/send-kit.py,scripts/x2-shim.py,scripts/plan.json}`, `private/evidence/openwiz-0.0.1/ticket-3/scripts/{quick-check.py,observe.py}` and `contracts/{inventory.v1.schema.json,messaging.v1.schema.json}` (L13 checks the page's answers against them). Then write `$L/jake-threads.sh` (below) | each `shasum -a 256` equals `<K>`'s | a hash differs |
| A4 | **Jake** | **L-4, L-5:** make 3 new, empty threads: **T-A** Local, with a harness that has steering (for example Codex); **T-B** Cloud, the same harness; **T-C** Cloud, Claude Code (no steering). Set each so it runs `sleep 120` with no permission prompt. Then, in Terminal: `sh ~/openwiz-live-0.0.3/jake-threads.sh`, and paste the three ids when asked. He sends nothing. He tells the runner **"threads made, go, 23 ok"** | `threads.env`, mode 600 | — |
| A5 | Runner | **Setup** (below) | `"setup": "ready"`; both sha256 values and the head match; `path_guard` is X2 | exit 10 |
| A6 | Runner | `send-kit.py map --work "$W"` | T-A `Local`, T-B and T-C `Cloud`; all idle, 0 events, visible. No id or title printed | any line wrong |
| A7 | Runner | **L-3:** `send-kit.py recheck --work "$W"` (`thread tell --help`, kept on the Mac; structure only) | `shows_double_dash` recorded. **C1 sends M13 alone, first, either way;** if `--` isn't confirmed, a surprise there stops the run | — |

*Alternative to A4, only if Jake prefers:* on his "go", the runner makes the threads itself with `room-cli thread spawn`. That's a `--write` outside the standing approval: its flags are taken from `thread spawn --help` at launch, and if spawning needs a first message, that text needs Jake's OK too. **The default is A4: Jake makes them.**

**A3's `jake-threads.sh`** (the ids appear only on Jake's own screen):

```sh
umask 077; f="$HOME/openwiz-live-0.0.3/threads.env"
printf 'T-A id (Local, steering): '; read -r a; printf 'T-B id (Cloud, steering): '; read -r b
printf 'T-C id (Cloud, Claude Code): '; read -r c; printf 'TA=%s\nTB=%s\nTC=%s\n' "$a" "$b" "$c" > "$f"; echo saved
```

**A5, setup:**

```sh
( set -eu; export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"; L="$HOME/openwiz-live-0.0.3"
  K="$L/kit/tools/live-check/send/scripts"; O="$HOME/openwiz-0.0.3"
  /usr/bin/python3 "$K/send-kit.py" setup --work "$L/w" --room-cli "$(command -v room-cli)" \
    --openwiz "$O/target/release/openwiz" --server "$O/target/release/openwiz-server" \
    --threads "$L/threads.env" --port 7370 --host '<HOST>' --web-root "$O/web-out" \
    --restore-cmd '<RESTORE-CMD>' --restore-log "$HOME/openwiz-0.0.2/server.log" --restore-sha256 '<SHA-02>' \
    --expect-sha256 '<SHA-OW>' --expect-server-sha256 '<SHA-SV>' --checkout "$O" --expect-head '<H>' \
    --allowance "$HOME/openwiz-0.0.3-allowance" )
```

**L-8's allowance (Sol's R8 on #168).** `--allowance` is the same directory for every sitting, outside every `$W`, and never deleted. It holds L-8's total (23 sends: every call the plan makes) and every send charged in any sitting. `setup` prints `allowance: total, used, remaining`; a first sitting shows 23, 0, 23.
- X2 charges a tell when it admits it, and returns the charge only when it proves no call was made (a zero-call abort). A call whose outcome is uncertain stays charged.
- A step already charged, in this sitting or an earlier one, is never sent again: X1 stops before any send, and X2 refuses it by itself. Groups that need more than what is left stop the same way.
- Only Jake amending L-8 raises the total (setup refuses an allowance whose total isn't the plan's 23; a higher one needs a reviewed kit change).
- **The directory's two files go together (Sol R14).** The first `setup` makes `allowance.json` (the total) and `charges.log` (every charge), empty, together. From then on a missing or unreadable `charges.log` (or one without its `allowance.json`) is **unknown usage, never zero**: `setup` stops before making a sitting, `run` stops before any send, X2 refuses every tell by itself, a report published then fails (`allowance: unknown`), and nothing recreates the journal. **Stop and ask Jake to reconcile.** How the history is restored is his call (for example, the journal put back whole from a copy); a fresh `setup` then shows the inherited totals again, and the runner checks them against the earlier sittings' reports before any go-ahead. Never delete it or start a new `--allowance` directory to get past the stop: that would forget charged sends.

---

## Screen B. The CLI part (runner; about 2½ hours; Jake keeps working, and doesn't touch T-A, T-B or T-C)

```sh
( export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"; L="$HOME/openwiz-live-0.0.3"
  K="$L/kit/tools/live-check/send/scripts"
  nohup /usr/bin/python3 "$K/send-kit.py" run --work "$L/w" --groups C1,C2,C3,C4,C5,C6,C7,C8 \
    --exclude-id '<RUNNER>' --exclude-id '<ORCH>' --forbid "$(id -un)" --forbid "$(hostname -s)" \
    > "$L/cli.out" 2> "$L/cli.err" < /dev/null & echo started )
```

The runner checks `tail -3 "$L/cli.err"` every 20 minutes or so: one line per step, giving the step and its verdict, with no id. **Defaults:**
- a 120 s settle after each sequence (until every test thread is idle with no queue row);
- a 300 s late wait after each group;
- a 5 s busy check;
- polls every 2 s;
- 6 samples, from the judged (cold) sessions;
- warm hours 48, and at least 20 judged sessions.

| Group | Sends (→ thread, mode) | Expected | Claims |
| --- | --- | --- | --- |
| **C1** | **M13, the dash text, alone, first** (L-3) → T-A, Queue | exit 0, `accepted`, `starts_turn`, 1 call. M13 arrives on T-A **exactly**, once | L-3, L11, L1, L4 |
| C2 | M01 → idle T-A. Then M02 (sleep 120) → T-A, and once it has been busy 5 s, M03 → T-A, Queue | M01 `accepted`. M03 `queued`, `thread_busy`, 1 queue row, and it arrives after M02's turn | L2a, L2b, L4, L1 |
| C3 | M04 (sleep 120) → T-A; busy 5 s; M05 → T-A, **Steer** | `accepted` or `queued` (both honest), `asks_to_steer`, 1 call, arrives once | L2c, L1 |
| C4 | M14, the file-path text → T-A | `accepted`. It arrives exactly, with no attachment key | L11, L1 |
| C5 | **F2:** M16 → T-B. X2 holds the receipt 20 s, past `openwiz`'s 15 s timeout. Then the same op id again, then a new op id | exit 6 `uncertain` `timed_out`, text kept. Rerun `replayed`, 0 calls. New op id: exit 9, 0 calls. M16 arrives once | L6, L1 |
| C6 | **F3a:** M17 → T-A, and X1 kills its `openwiz` after the call. **F3b:** M18 → T-A, and X1 kills it during X2's 10 s hold before the call. After each: a settle and late wait with no call, the record, and a rerun of the same op id | F3a: `dispatching`, then `recovered`, uncertain, 0 calls; M17 arrives once. F3b: X2 `aborted_parent_gone`, 0 calls, **M18 never arrives** | L6, L7, L1 |
| C7 | M19 → T-A and its rerun. Its op id reused with M20's text, with T-B, and with Steer. Then **4 processes at once** on one op id with M21, then a replay | Rerun `replayed`. The three reuses: exit 8, `differs` text / target / mode, 0 calls, **M20 never arrives**. Race: exactly 1 call, the others exit 7 or replay. M21 arrives once | L8, L7, L1 |
| C8 | M11 (sleep 120) → T-C; busy 5 s; M12 → T-C, **Steer** | exit 0, requested mode `steer`, `asks_to_steer`, 1 call, **M12 arrives once**, and the outcome exactly as `room-cli` reported it: either `accepted`/`accepted` (sent: `room-cli` v141 in [#10's sitting 2](https://github.com/jparker2006/ClosedWiz/issues/10#issuecomment-6632877163), `{threadId, ok, delivery: sent, mode: steer}`) or `queued`/`queued` (0.43.1). [#10's PC probe](https://github.com/jparker2006/ClosedWiz/issues/10#issuecomment-6573992095) observed `waitingOn: null`; [receipt evidence at c687079](https://github.com/jparker2006/ClosedWiz/blob/c687079/private/evidence/openwiz-0.0.3/ticket-3/pc/receipt-probe.json). L3's unsupported-rejection claim stays unproved. The executable rerun waits for #571 and the separate harness/L4 follow-up. | L3, L4, L1 |

When it ends, the runner scans `cli.out` again (for `thr_`, `<HOST>` and the account name), commits it as `live-cli.json`, and tells Jake **"CLI part as expected"** or **"stopped at <step>: <why>"**, in plain words.

---

## Screen C. The swap, and the web route part (runner; about 30 minutes, plus the phone part)

**C1. The swap** (the one `--write` step Jake OKs: he says **"swap ok"**). For about 45 minutes, until screen E, his site runs 0.0.3 under X1. Reads work as before; sends happen only when the runner asks.
1. `send-kit.py swap --work "$W" start --minutes 90`.
   - **Expected:** `"swap": "up"`, `"old_was_running": true`.
   - **It refuses (exit 10) and signals nothing** if what listens on 7370 is not exactly the confirmed 0.0.2 launch.
2. Check: local health on 7370 is 200 (now X1's 0.0.3), and the public hostname without a login gives 302.
3. **If anything goes wrong from here on**, the guard restores 0.0.2 by itself (asked by the supervisor, or alone if the supervisor died), by the deadline at the latest.
   - **To end early:** `send-kit.py swap --work "$W" end`.
   - **If the guard was killed** (state `guard-died`), X1's server is already gone with it: restore 0.0.2 by hand, as HANDOFF says.

**C2. The web route** (runner): `send-kit.py run --work "$W" --groups W1,W2,W3,W4,W5,W6,W7 --exclude-id '<RUNNER>' --exclude-id '<ORCH>' --forbid …`, in the background, as on screen B. X1 makes each send **exactly as the composer does** (the same headers, body and op-id form), to the port the tunnel serves, so the server sees what the tunnel delivers. The composer's own screen is tested on screen D.

| Group | What X1 does | Expected | Claims |
| --- | --- | --- | --- |
| W1 | M07 (sleep 120) → T-B, Send; then, while busy, M08 → T-B, Queue | M07 sent; M08 `queued`, arrives after the turn | L2b, L10 |
| W2 | M09 (sleep 120) → T-B; then, while busy, M10 → T-B, **Steer** | `accepted` or `queued`, the requested mode kept apart | L2c, L10 |
| W3 | M14, the file-path text → T-A, Send | sent; M14 arrives **exactly** once | L11 |
| W4 | **F4:** M01 → T-A; the supervisor stops **its** server after the call, waits a settle with no call, and starts it again; then Try again (same op id) | `dispatching` until Try again, then recovered, uncertain, **0 calls**; M01 arrives once | L6, L7 |
| W5 | **F6:** M20 → T-A; the supervisor kills **its** server during X2's hold before the call, waits, and starts it again (**a start dispatches nothing**); then Try again | uncertain, 0 calls ever, **M20 never arrives** | L7 |
| W6 | M21 → T-A, the request sent twice (a double press). During X2's 6 s hold, the CLI runs with the **same op id**. Then a replay | the CLI exits **7**; the second request's own answer is a replay; exactly **1** call; M21 arrives once; the replay is `replayed`, with 0 calls | L8 |
| W7 | 6 probes with M25 to the site's port (loopback `Host`; no or foreign `Origin`; cross-site; no `X-OpenWiz-Send`; a form content type), and one unauthenticated request to `https://<HOST>` | 421, 403, 403, 403, 403, 415; the public one gives **302, 401 or 403** (Access); **0 tell attempts, and M25 never arrives** | L9 |

*W7, optional (Jake, 1 minute at the Mac):* the runner asks in chat. Jake opens `$W/run/cross-site-probe.html` in Safari and presses its two buttons, or answers "skip". **Skipped, a cross-site attempt from a signed-in browser is a gap.** It is covered only by the server's checks above and by Access.

---

## Screen D. Jake's phone (about 10 minutes; the runner relays)

The runner starts `send-kit.py run --work "$W" --groups P1,P1b …` in the background (P1 is P1-M06; P1b is the rest, so it can run in a later sitting if P1-M06 was already sent: #10, sitting 4), then tells Jake each step in chat. **Jake answers in chat, and the runner writes each answer to `$W/run/answer-<step>.txt`.** X1 waits for it (15 minutes at most per answer).

| Step | Jake, on his iPhone | He answers | Expected | Claims |
| --- | --- | --- | --- | --- |
| P1-M06 | **Safari, Wi-Fi off (cellular).** Open T-B, put in M06 (the runner pastes it in chat), **read the line under the button** ("starts a turn; may wake it"), press **Send** | what the composer shows; and, in his own words, how the composer looks and feels (**N-2, the design acceptance**) | **sent**, 1 call, M06 arrives once on T-B | L2a, L5, L10, L12 |
| P1-M15 | **Safari, on Wi-Fi.** T-B → M15 → **Send**, then **at once turn on Airplane Mode**. Leave it on until the composer shows an outcome, then turn it off | what it shows | **uncertain** (never "not sent"). If it says sent, the network went off too late: F7 is "not produced", recorded, not a failure | L6 (F7), L12 |
| P1-check | Back online: press **Check again** on that send | what it shows now | **sent**, 0 calls | L6 |
| P1-M13 | **Chrome.** T-A → M13 (the dash text) → **Send** | what it shows | **sent**; M13 arrives exactly | L11, L12 |

**Not covered on a phone:** Blink on Android (an allowed gap), and the composer in a desktop browser. The desktop's requests are covered by screen C. Jake may add one desktop press by hand if he wants it.

---

## Screen E. Wrap-up (runner; about 10 minutes)

1. **L10, parity:** `send-kit.py parity --work "$W"`. For idle send (C2 / P1), queue on busy (C2 / W1) and steer on busy (C3 / W2), the CLI and the web give the same delivery class and the same record structure. No call.
2. **L13, reads stay safe:** 0.0.1's quick check, unchanged, while X1 makes the page's reads every 2 s (the inventory, T-A's session, its composer preview). **Every answer is checked against its contract schema file** (`contracts/inventory.v1.schema.json` for the inventory and the session, `contracts/messaging.v1.schema.json` for the preview): every required field, type, constant and allowed value, nested ones included. It must also be HTTP 200 and name **T-A as the target**: in the inventory, as the session, and as the preview's target.

A route that answers wrongly fails L13, and one that never answers validly leaves it incomplete. Jake's own page, if he has it open, adds more reads. The command:

   ```sh
   /usr/bin/python3 "$K/send-kit.py" l13 --work "$W" -- --room-cli "$(command -v room-cli)" \
     --openwiz "$O/target/release/openwiz" --expect-sha256 '<SHA-OW>' --checkout "$O" --expect-head '<H>' \
     --run-dir "$L/qc" --exclude-id '<RUNNER>' --exclude-id '<ORCH>' --forbid "$(id -un)" --forbid "$(hostname -s)"
   ```

   Expected: the quick check gives `pass`, judging the cold sessions and the test threads. The recent ones are excluded by the 48 h rule, and counted. X2 counts the page's reads inside the window, and sees 0 tells.
3. **L4:** `send-kit.py receipts --work "$W"` gives each receipt kind's key names and types, against the keys observed in #10's probe.
   - Every receipt counts.
   - A sent receipt and a queued (thread-busy) receipt must both have been produced. A queued steer without steering (`queued:not-reported`) is checked when produced (0.43.1), but not required: `room-cli` v141 sends that steer instead. Each kind must have exactly the keys observed in [#10's PC probe](https://github.com/jparker2006/ClosedWiz/issues/10#issuecomment-6573992095). 0.43.1 queues an unsupported steer instead of rejecting it, so no rejection is required; one that appears is still checked.
   - Any drift, or a missing kind, blocks the claims that use it (exit 10).
4. **The swap back:** `send-kit.py swap --work "$W" end`. The supervisor stops X1's server and starts the confirmed 0.0.2 launch. Expected: `"swap": "restored"`. Check health and the 302 as in C1. (Keeping 0.0.3 instead is Jake's call after the run, as a separate step.) Then `send-kit.py map --work "$W"`: every test thread idle, with no queue row. Jake may archive the test threads.

## What stops the run (all parts)

Every report X1 prints is first scanned for every session's id **and title**, every project and machine name, the test threads' titles, the hostname and the account name.
- **Every non-empty string counts, however short.** A two-letter title is forbidden too; short ones match as whole tokens.
- **The scan walks every decoded key and string value of the report,** so quotes, backslashes and non-ASCII are compared as they are, not as JSON escapes them.
- A false stop on a short title is accepted; a leak is not. A hit prints nothing: the report stays on the Mac only. Every command exits 10 when its outcome is not as expected, parity and receipts included.

- **A message in the wrong thread, twice, altered, or with an attachment key:** L1 / L8 / L11. **The release is blocked** for L1 and L8.
- **X2 refuses a call** (a resend, another thread, mode or text, or any call off OpenWiz's allowlist), **or there is any call in a quiet or late wait, or a send between steps:** L6 / L7 / L8, and **the release is blocked.** (A refused call never reaches `room-cli`, so nothing reaches a thread.)
  - **Any refusal taints the whole sitting (Sol R13; the orchestrator's rule).** X2 writes every refusal (a tell or any other call) and every revoked hold to the sitting ledger, `x2/sitting.log`, under its lock. There is no baseline and no watermark: a refusal before the first run, between two parts, during a preparation command, or during a run's final snapshot counts the same.
  - **Every outcome is decided when the report is published:** the last thing before X1 writes it and exits, X1 reads the ledger under the same lock. Tainted means `not_as_expected` and exit 10, for `run`, `map`, `recheck`, `l13`, `parity`, `receipts` and `swap`.
  - `run` and the preparation commands also refuse to start in a tainted sitting ("nothing was done"), so nothing more is sent. `swap end` still runs, so 0.0.2 is always restored; its report still fails.
  - **Only a fresh sitting clears it:** a new `setup` (a new `$W`, the same `--allowance`) and new test threads, after Jake's go-ahead.
  - **Before that go-ahead, the runner shows Jake the cumulative totals:** what each earlier sitting sent and what is left, from the new `setup`'s `allowance` line and the earlier reports. Jake okays the groups still to run, which must fit what is left. Earlier sittings' reports stay the evidence for the steps they completed, which are not repeated.
- **X2 aborts a held tell** (`aborted_revoked`: its step was disarmed, re-armed or expired during the hold; `aborted_tainted`: the sitting was tainted, or its ledger unreadable, during the hold): that step is not as expected, nothing was called, and the send goes back to the allowance.
- **An outcome other than the step's expected one** (for example, the requested mode shown as the delivery, or "not sent" after the request reached the core): that claim is blocked.
- **A judged (cold) session changes, or a sample gains an event:** L1. **The release is blocked** unless Jake says it was him; a rerun of that group's sends then needs Jake to amend L-8, since they are charged.
- **Incomplete:** for example, fewer than 20 judged sessions, a test thread not idle within 10 minutes, an unreadable field, or a missing answer. The claim stays unproved, never passed.

## Afterwards (runner)

- Scan every report again for ids, the hostname, the account name and titles. Then commit `live-cli.json`, `live-web.json`, `live-phone.json`, `parity.json`, `l13.json` and `receipt-structure.json` under this folder. Commit nothing else from `$L`. Keep the run directory until Jake has read the reports, then delete it.
- For each claim, record its result, its evidence class (live observation), the exact head and tree, and its gaps. Jake's design acceptance is his own words from P1. Then Sol reviews the exact candidate (#10).
- **Known gaps, stated now:**
  - no second identity (L-11);
  - no paused-queue test (L-7);
  - no Wi-Fi cut on the Mac (F1, L-6);
  - F5 (the tunnel stopped) is not run: F7 covers L6's network cut;
  - the composer's screen is tested on the phone only, unless Jake adds a desktop press;
  - the cross-site browser attempt only if Jake does W7's optional minute;
  - Blink on a phone;
  - unapproved event labels (B6), so "joined the running turn" is `unknown`;
  - under `room-cli`, a lost acknowledgement stays uncertain.
