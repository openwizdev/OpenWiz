# ClosedWiz

## What this is

ClosedWiz is OpenWiz's **private repository**: it holds the private records and nothing else that is live. **No product code is built in ClosedWiz.** OpenWiz is developed in the public repository [`openwizdev/openwiz`](https://github.com/openwizdev/openwiz): every product change, ticket, pull request, test run and release happens there. For everything about building, read [OpenWiz's own `AGENTS.md`](https://github.com/openwizdev/openwiz/blob/main/AGENTS.md).

What lives here, as the [open development contract](https://github.com/openwizdev/openwiz/blob/main/contracts/open-development.v1.md) defines it:

- **Grills:** the decisions in the user's own words (`docs/grills/`), and the private record comments that public forms point to (`Private record: OpenWiz #<N>` issues).
- **Evidence:** live and private evidence (`private/evidence/`), referenced from OpenWiz only by private-record pointers.
- **Orchestration records:** handoffs, the cut-over runbook and its records, loop definitions and their state (`private/orchestration/`, `loops/`).
- **Their tools:** the scripts that read, check or publish those records privately: the record scripts beside their evidence, and the board and the war room (`.github/workflows/board.yml`, `.github/workflows/war-room.yml` and the tools they run), which keep publishing privately from here.

## The frozen copy

Everything else in this tree (the crates, the apps, the tests, the contracts, the skills, the other workflows and the other tools) is a **frozen copy** of the code as it was at the cut-over. It is kept for history and as a reference until it is deleted (#1287). Never edit it, never build or test it here, and never treat it as current: the live version is on `openwizdev/openwiz`. A fix you find while reading it goes to OpenWiz as an issue there.

## Always true

- **Private, forever.** ClosedWiz is never made public, deleted, rewritten, force-pushed or transferred. Every commit, issue and pull request stays as the private record; changes are ordinary commits and new comments only.
- **Records, not work.** Open no product ticket or product pull request here. Private-record issues and comments target this repository explicitly (`--repo jparker2006/ClosedWiz`).
- **Public words stay public-safe.** Exact decision words, thread ids, machine details and live evidence stay here. Anything written on OpenWiz uses the contract's public forms and points here with a private-record link.
- **Install the pre-push hook,** once per clone: `git config core.hooksPath .githooks`. It still runs the frozen copy's fast checks on each push; until #1287 trims the tree, those are the only builds that run here.
