# Changelog

All OpenWiz versions, newest first. How versions work: [RELEASING.md](https://github.com/openwizdev/OpenWiz/blob/main/RELEASING.md).

## 0.1.1 · 2026-11-22

**OpenWiz 0.1.1: OpenWiz no longer needs CloudRoom: install it and run your first fleet on your own computer, with the Claude Code or Codex you're already signed in to**

**What's new for you**

- After the install, your agent asks once where your agents should run: this computer, with the Claude Code or Codex you are signed in to, boat.dev, or CloudRoom, which is installed and signed in to only if you pick it.
- On this computer, your first fleet's builders and reviewers start with your own login; a reviewer comes from the other model family when you have both, and a same-family review is marked as one.
- A scheduled job you approve once wakes your fleet every 10 minutes, "run the fleet now" ticks it at once, and one command each shows, pauses or removes it.
- `openwiz models show`, `list` and `set` pick the models your orchestrator, builders and reviewers use, from what your installed Claude Code and Codex offer, with no CloudRoom needed.

Tested on synthetic fixtures, with fake harnesses, schedulers and GitHub only: nothing in this release has been checked live yet, including a stranger's install and first fleet on a clean machine with no CloudRoom, Claude Code or Codex, and a Mac.

**Under the hood**

- The installer finds the newest release when the latest is a pre-release, names each failure, checks glibc on Linux, repairs a damaged build and checks updates against `SHA256SUMS`, and a new `install remove` deletes only what it made.
- `install skills` installs per agent and per skill, keeps your own same-named skill, and no longer reports `installed` when no agent folder exists.
- The boat.dev, local and Cloudroom drivers refuse a start field that looks like a credential and no longer repeat their host's error text, and on macOS they find and stop a run without reading any other process's environment.
- The boat.dev driver fails a start at once when its first turn hits a usage limit or an expired login, or when the account cannot push to the repository, and every driver's README says where your login lives.
- `install preflight` calls CloudRoom optional, so an Intel Mac installs and runs agents on this computer or on boat.dev.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.1.1)

## 0.1.0 · 2026-11-21

**OpenWiz 0.01: see your factory in the app, and run builders where you choose**

**What's new for you**

- Sign in with GitHub at openwiz.dev/app to see what needs you, every spec's live ticket graph and the agents at work, on a laptop or a phone.
- Choose where your builders run, from Linux or macOS, with one `Host:` line in `docs/agents/host.md`: the computer or VPS you are on, with the `claude` or `codex` you already signed into, Cloudroom threads, or boat.dev cloud sandboxes.
- Installing puts OpenWiz's skills into the agents you already use (Claude Code, Codex, Cursor, OpenCode and Grok) and leaves your own skills untouched; they are now WizSkills 0.2.1, 18 shorter skills.
- The `send`, `new` and `attachment` commands, the local web view and its server and service are gone: OpenWiz is now the command, the drivers and the skills, and the app lives on the web.

Live-checked against real hosts: the boat.dev driver passed all five driver-kit checks live from both Linux and a Mac, the local and Cloudroom drivers passed them on Linux with no login or token in their output, and a boat.dev builder woke again after its turn had ended; the owner checked the app on a laptop, and its tab bar on a phone is still to be confirmed; the local and template drivers were not run on a Mac, the kit's macOS process listing has a known edge, logged as [#2039](https://github.com/openwizdev/OpenWiz/issues/2039), on macOS, stop lists the user's own processes to find its run, logged as [#2044](https://github.com/openwizdev/OpenWiz/issues/2044), a macOS package install was not checked live, and the skills install and `openwiz init` are tested on synthetic home folders and a synthetic GitHub only.

**Under the hood**

- Anyone can plug a place that runs agents into OpenWiz with a small driver: `kernel/driver.v1.md` defines its four commands, `adapters/template/` is a minimal one to copy, and a five-check test kit shows whether a driver passes.
- Records v1 publishes the rules any tool follows to keep a project's work on GitHub, with a kit that reports each record breaking them.
- The release package carries the three host drivers and the driver kit; the kit never copies a credential into its output, and the template driver leaves no agent running.
- `install skills` no longer deletes a file of yours at its staging or backup path, and no longer refuses every agent when `~/.config` is a link.
- `openwiz init` reports a label only when GitHub shows it, and an install made before the removals still passes `install status` and updates.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.1.0)

## 0.0.17 · 2026-11-21

**Keep your loops as files, with no always-on engine to run**

**What's new for you**

- Keep your Cloudroom loops as files: `openwiz loop validate` checks them, `openwiz loop export` writes your loops out, `openwiz loop plan` shows the exact changes, and `openwiz loop apply` makes one loop match its file and reads it back.
- The always-on engine is gone: no scheduled fleet tick, health checks and takeover, push notifications or engine step in Setup; your fleets run as fleet threads with their own loops.

Checked live in the 0.0.17 candidate's own smoke test, run by agents on Linux: a fresh install of that candidate, its service starting and serving the web view, `openwiz help --agent`, `ls --json` and `show --json`, one send to a throwaway thread, and one new thread in a throwaway project; the loop commands are tested on synthetic fixtures and [one read-only replay of real loops](https://github.com/openwizdev/OpenWiz/blob/release-0.0.17/docs/evidence/794/README.md), `openwiz loop apply` was never run live, and nothing was checked on a Mac.

**Under the hood**

- `openwiz engine preview`, `activate` and `status` and the executing `openwiz fleet tick` are removed; `fleet tick --dry-run` and `fleet due --github-only` still read and plan.
- The package no longer ships the engine preparation, activation and handover runtimes.
- `openwiz loop export` never writes a webhook address or a secret value, and reports each loop it cannot represent instead of dropping it.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.1.0)

## 0.0.16 · 2026-11-21

**One install instruction, on to your first fleet**

**What's new for you**

- The install instruction continues in one path: GitHub sign-in in your browser, your own private OpenWiz App or an explicit skip, your factory's private brain, then onboarding to a first fleet.
- `openwiz init` places your private brain by your repository's visibility: in the repository when it is private, or in a linked private companion when it is public, proposed through one pull request.
- The visual terminal app is removed: `openwiz ui` says so, and `openwiz` with no arguments prints the help.

Tested on [recordings and synthetic fixtures](https://github.com/openwizdev/OpenWiz/blob/release-0.0.17/docs/evidence/openwiz-0.0.16/recording.md) only; a real sign-in, a real App registration and a fresh machine's first merged pull request are still unverified.

**Under the hood**

- Your own GitHub App is registered private, and its tokens are minted only for repositories on the account that owns it.
- Onboarding accepts fleet records only from configured authors, and creates the demo repository only after GitHub sign-in is verified, with a first commit on its default branch.
- Updates no longer fail to stage when another process briefly holds the new program open.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.1.0)

## 0.0.12 · 2026-11-16

**Scripts and agents can drive OpenWiz**

**What's new for you**

- Run `openwiz help --agent` to get every command, option and result format in one list. It reads nothing and changes nothing.
- Add `--json` to any command for one clean result, and a clear error when something goes wrong.

Live-checked in this release's smoke test, run by agents: installing this release, `openwiz help --agent`, `ls --json` and `show --json`, one send to a throwaway thread, and one new thread in a throwaway project. Everything else here is tested on synthetic fixtures only; the terminal app was never live-checked on a Mac.

**Under the hood**

- Every `--json` command prints exactly one document, its result or a structured error, and the command list is a written contract.
- Fleet candidate checks can return JSON too.
- A visual terminal app (`openwiz ui`) was built in this version and is being retired.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.11 · 2026-11-16

**Make every decision in one place, and see the whole plan**

**What's new for you**

- A Decisions page: answer grill questions, confirm specs and approve plans. Each answer goes to your orchestrator as one message.
- Anything live, release or publishing asks you twice before it goes.
- A Plan page shows each version's tickets by state, what holds up the most work, and what any ticket waits on.

Tested on synthetic fixtures only; a whole day of real decisions on these pages is still unverified.

**Under the hood**

- A plan API reports ticket states, dependencies and the critical chain, and marks reads that failed instead of hiding them.
- The planning skills now ask for decisions in a fixed, structured form.
- Each answer is sent with the question and revision it answers, and its text is kept exactly.
- Malformed decision requests are reported, not dropped.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.10 · 2026-11-16

**A cockpit for your phone and PC**

**What's new for you**

- A Cockpit page: what needs you, oldest first, and every running agent by project and fleet.
- Answer an item right there when its exact proposal is known, after a preview and a confirm. Risky ones ask twice.
- A command bar to move around fast: `ls`, `cd`, `next`, `blockers`, or an item's number.
- Each item shows its question, a link, when it was asked and how risky it is.

Tested on synthetic fixtures only; the cockpit on a real phone and PC is still unverified.

**Under the hood**

- The local server answers the whole cockpit in one read-only request, and marks any part it couldn't read or that is stale, instead of showing it empty.
- `openwiz fleet` shows the same details as the page.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.9 · 2026-11-16

**All your loops in one place**

**What's new for you**

- A Loops page on your PC lists every scheduled job: next run, last run and cost over the last day, problems first.
- Switch any loop off or on. It records who did it and when, and stays that way after a restart.
- No 100-loop limit: tests plan 200 loops within the shared limits.
- OpenWiz tells you when a loop check is missed or stuck, and stays quiet until that changes.

Tested on synthetic fixtures only; a whole day of real loops run from the phone is still unverified.

**Under the hood**

- The service runs loop checks itself, and never retries an agent start whose result is unclear.
- Review and CI follow-ups go to the agent already on that work, through durable records; GitHub webhook events are routed once each.
- A loop runs only when its exact definition is approved and it has its own capacity limits; other service work carries on.
- Loop health is watched separately from the scheduler.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.8 · 2026-11-16

**OpenWiz keeps running on your PC**

**What's new for you**

- `openwiz-service` runs on your PC: it serves the web page, runs scheduled jobs and reports its own status.
- It checks its own health and recovers its loops, fleet runs and the web server when they fail.
- It updates itself from tested builds, and goes back to the last good one if a new one won't start.

Tested on synthetic fixtures only; a whole day with the Mac shut is still unverified.

**Under the hood**

- A GitHub App gives the service tokens scoped to each repository, renewed and shared across its jobs; the private key stays in owner-only storage.
- The service runs the fleet tick on a schedule and records how each run ended.
- The tick picks builders by ticket label and reviewers from the other model family, with one fallback that keeps the branch when a Claude usage limit stops a builder.
- A service update can resend a record that never went out.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.7 · 2026-11-16

**Helpers for builders and reviewers, and a "where are we?" report**

**What's new for you**

- Builders and reviewers can bring in helpers for side jobs, while the lead keeps every decision.
- Ask "where are we?" and get one screen of current work, open decisions and the next move.
- New skills to map an unclear project (wayfind), research with cited sources (research), and track down a hard bug before fixing it (diagnose).

Helper swarms ran for real and "where are we?" was used for real; whether helpers make work faster or cheaper is still unproven.

**Under the hood**

- A written guide sets how many helpers to use and which ones.
- A check catches a helper that pushes code; helpers never push.
- The skills check now covers the new skills.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.6 · 2026-11-16

**Fleets run inside OpenWiz**

**What's new for you**

- `openwiz fleet tick` moves your fleets forward: it works out what is due and does it.
- `openwiz fleet due --github-only` tells a loop whether there may be work for it.
- See your fleets with `openwiz fleets` and on the web page's fleets screen.

Tested on synthetic fixtures only; a real fleet run by OpenWiz itself, followed on a phone, is still unverified.

**Under the hood**

- Fleet views refuse conflicting GitHub facts and show "unknown" instead of guessing progress or who is building.
- Larger fleet lists finish within the time budget: merge history is read in batches.
- Inventory commands report a failed write, and send previews refuse thread details with repeated keys.
- On a PC, OpenWiz finds the running CloudRoom app, and asks you to restart CloudRoom if an update leaves two copies running.
- Keyboard focus stays put while pages load and fleets refresh.

[Full release on GitHub](https://github.com/openwizdev/OpenWiz/releases/tag/v0.0.12)

## 0.0.5 · 2026-11-05

**Fleets of agents build for you**

**What's new for you**

- Eight skills for coding agents: they grill you on an idea, plan it into tickets, then build, review and merge each one.
- Use them in Claude Code as a plugin, or in Codex straight from the repo.
- Nothing merges without an independent review of the exact code and green CI.

Tested with the skills' static checks, and live: a real fleet used these skills to build 0.0.6.

**Under the hood**

- The skills are plain Markdown files any agent can follow; GitHub keeps the specs, tickets, reviews and decisions.
- Each ticket gets one builder, and each pull request a reviewer from a different model family.
- A static check in CI keeps the skill set, links and plugin manifest in step.

## 0.0.4 · 2026-11-05

**Start new threads, with files**

**What's new for you**

- `openwiz new` starts a Cloud thread in one of your projects. It shows exactly what it will do first, and creates it only with `--yes`.
- Attach files and images to a new thread or a queued message, from the terminal or the web page.
- One thread per create: if the result is unclear, it tells you instead of trying again.

Tested on fixtures; the live check of new threads and attachments is still open.

**Under the hood**

- New threads reuse the same local store and text rules as sending, with no new dependencies.
- New write routes follow the same security rules as sending.

## 0.0.3 · 2026-11-05

**Message your threads**

**What's new for you**

- `openwiz send` sends one message to a thread, as Queue or Steer.
- Or send from the web page on your phone.
- If a send's result is unclear, OpenWiz says so instead of sending twice.

Tested on fixtures and in a live check on test threads; it was accepted with some gaps still recorded.

**Under the hood**

- The terminal and the web page share one record of each send.
- A read-only preview works out what a send will do before you press it.

## 0.0.2 · 2026-10-30

**Your threads on your phone**

**What's new for you**

- A private web page served from your own computer: your threads by project, with status and age. Tap one for details.
- Open it from anywhere through a Cloudflare Tunnel, with a login only your email can use.
- It only reads, and it tells you when data is stale or you're signed out.

Tested on fixtures, and the owner-only login was checked live; the full check on a Mac and a phone is still open.

**Under the hood**

- A local Rust server serves the API and a Next.js web app.
- Cloudflare Access checks your login, and the tunnel checks it again at your computer.

## 0.0.1 · 2026-10-30

**Your CloudRoom threads in the terminal**

**What's new for you**

- `openwiz ls` lists your threads with status, project and age; `-l` adds a recap, model and effort.
- `openwiz show <id>` shows one thread and its final output.
- `--json` for scripts. It only reads: it never changes a thread.

Tested on fixtures and in a live check on a real Mac.

**Under the hood**

- A Rust command-line tool that reads through your existing, signed-in `room-cli`.
- The `room-cli` version is recorded, never required.

## 0.0.0 · 2026-10-22

**The design, before any code**

**What's new for you**

- The plan for OpenWiz: what it does, how it is built and how it is released. No code yet.
- Published first as OpenFleet, and renamed OpenWiz before 0.0.1.

Nothing to test yet: this version is documents only.

**Under the hood**

- With the rename, the stack was chosen: one Rust core owns state, permissions and coordination; the CLI is Rust and the web client is Next.js and TypeScript, in one repository.
- Architecture diagrams, release rules and a draft protocol spec (PACP v0.1).
- Licensed under Apache 2.0.
