# Using OpenWiz from a terminal (0.0.12)

OpenWiz has two terminal interfaces. **Agents and scripts** use explicit commands with `--json`; **people** use the visual terminal app. Both are thin clients: nothing here adds a CloudRoom operation or a safety limit.

## For agents: explicit commands

- `openwiz help --agent` prints one compact JSON catalogue of every shipped command, flag, effect, result schema and exit code ([`contracts/cli.v1.md`](../contracts/cli.v1.md)). It reads no source and writes no state.
- Every command takes `--json` and then prints exactly one document on stdout, its existing report or an `openwiz.cli-error.v1` error. Exit codes are fixed per command in the catalogue.
- Explicit commands never open the visual app, prompt or wait for a terminal. A piped `openwiz` with no arguments is a usage error (exit 2).

## For people: the visual terminal app

`openwiz` with no arguments, in a terminal, opens Home. `openwiz ui` opens the same Home explicitly.

```sh
openwiz                          # interactive terminal only: Home
openwiz ui                       # the same, on the default port 7370
openwiz ui --port 7371           # a server started with --port 7371
openwiz ui --json                # capability document; opens nothing
```

- **It needs a running local server.** The app reads the already running `openwiz-server` on `127.0.0.1` through its existing routes; it never starts, installs or embeds a server, and never runs `room-cli` or `gh` itself. If the server is not running, each part of Home says it is unavailable.
- **It is a separate program.** `openwiz` runs only `openwiz-terminal` from its own directory (no shell, no `PATH` search). If that file is missing, `openwiz ui` says so and exits 1.
- **Writes need the owner's host name.** Guarded requests use only `--allowed-host NAME`, or the owner's `OPENWIZ_SERVER_ALLOWED_HOST`, the same name the server was started with. Without one the sidebar shows `writes: off (no host)` and every read still works.

### Screens

| Screen | Shows | Reads |
| --- | --- | --- |
| **Home** | Numbered **Needs you** first (decision records, then fleet-only held/needs-info facts), then fleets at a glance, then live sessions | `GET /api/v1/decisions`, `GET /api/v1/fleets`, `GET /api/v1/inventory` |
| **Sessions** | Every session, most recently updated first; Enter opens one: status, provider, project, reported model/effort, recap, final output | `GET /api/v1/inventory`, `GET /api/v1/sessions/{id}` |
| **Fleets** | Each fleet's merged progress and Needs you count; Enter opens one: tickets grouped by state, gaps | `GET /api/v1/fleets`, `GET /api/v1/fleets/{spec}` |

Each part shows its own coverage (`complete`, or `partial · N gaps`), how long ago its source was read, `stale` when it has not been refreshed in time, and the last refresh's failure beside the last good snapshot. **"Nothing needs you" is shown only when decisions and fleets are both complete and fresh.** A fleet label (held, needs info) carries no answerable proposal and says so.

### Keys

| Key | Does |
| --- | --- |
| `h` `s` `f`, Tab | Home, Sessions, Fleets |
| `1`–`9` | On Home: open that exact Needs you item. Selecting never answers |
| ↑ ↓ or `j` `k` | Select a Needs you item, session or fleet (kept in view); scroll a detail by a row |
| PageUp, PageDown | Scroll the screen, or an open action's pane, by a page (wrapped lines count) |
| Enter, Esc | Open the selected item; back |
| `r` | Refresh now (through the same bounded reads) |
| `q`, Ctrl-C | Quit; the terminal is restored |
| `a` `m` `n` | Answer, message, new thread: see below |

A grill round's unanswered questions are separate Needs you items, each with its own context and recommendation; answered ones are not shown. Each part's age is its source's own (for decisions, the oldest required source), counted on from when it was read; an unknown source age is never shown as fresh.

Reads refresh on their own: sessions every 10 seconds, a session every 15, fleets and decisions every 60, with the existing backoff after failures. At most one read of each kind and two in all are in flight.

The app uses the app's Observatory look in terminal cells: gold only for Needs you, purple for live and selected, and every state as a word and a shape. With `NO_COLOR` it uses no colour; without a UTF-8 locale it uses ASCII shapes.

### Actions

Answering a Needs you item, sending a message and starting a Cloud thread are separate parts, each shipped only when complete and proved. Until a part ships, its key says it is **unavailable in this build** and nothing is sent. Each part's own guide:

- Answer a Needs you item: [cli-parts/answer.md](cli-parts/answer.md)
- Send a message: [cli-parts/send.md](cli-parts/send.md)
- Start a Cloud thread: [cli-parts/new-thread.md](cli-parts/new-thread.md)

`openwiz ui --json` lists in `actions` only the actions this build implements.

In an open action, its title and exact target stay at the top while the rest scrolls (PageUp, PageDown). Ctrl-S confirms only while that target is shown whole, and a held key never confirms. Where the terminal reports key releases, confirming again needs Ctrl-S released and pressed again; otherwise confirmations alternate Ctrl-S, Ctrl-Y, Ctrl-S…, which one held key can never produce. Pasted text (bracketed paste is on while the app runs) goes into the focused field as it is, and never confirms. A very long line (over 16,384 characters) is drawn as consecutive pieces; nothing is cut, and requests keep every byte.

### Limits

- Fixture tests prove this behaviour; they prove nothing live. The live check is [live-checks/0.0.12.md](live-checks/0.0.12.md).
- An outside `SIGTERM` or `SIGKILL` ends the app without restoring the terminal (no signal library is used); `reset` repairs it. Ctrl-C, `q` and handled failures restore it.
