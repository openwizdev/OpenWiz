# How OpenWiz works

OpenWiz runs a software factory across whichever host you choose — **this computer or a VPS**, **[boat.dev](https://boat.dev)**, or **[CloudRoom](https://cloudroom.dev)** (CloudRoom is optional). Four parts:

- **You** make the decisions in chat with your coding agent (grills, specs, plans, and "needs you" questions) and watch progress on GitHub or in the web app at [openwiz.dev/app](https://openwiz.dev/app/).
- **GitHub is the memory.** A fleet is one approved spec and its tickets; every decision, ticket, status note, pull request, review and CI result is a record on GitHub ([records v1](../kernel/records.v1.md)).
- **The fleet loop routes the work.** On each wake, the fleet orchestrator (`launch-fleet`) reads GitHub, starts builders on ready tickets, sends green pull requests to reviewers, sends findings back to builders, and merges approved work. In CloudRoom it runs as a fleet thread on a CloudRoom Loop; on this computer or boat.dev it runs through the local session runner or an opt-in local heartbeat. The CLI's `openwiz fleet tick --dry-run` and `openwiz fleet due --github-only` are read-only planning and candidate checks (the executing `openwiz fleet tick` was retired in 0.0.17).
- **Drivers run short-lived agents on your chosen host:** one builder per ticket (it builds, tests, opens a pull request, then stops), one independent reviewer per pull request from the other model family when available, and small helpers a builder or reviewer starts for chores. Every host plugs in through the same four-command [driver v1](../kernel/driver.v1.md) interface (`version`, `start`, `wake`, `stop`), with drivers shipped in `adapters/` for local, boat.dev and CloudRoom.

Each fleet wake re-reads everything from GitHub, so nothing is lost if a session or thread stops, and agents exist only while there is work.

**How OpenWiz talks to hosts and GitHub:** to any host through its [driver v1](../kernel/driver.v1.md) adapter (and to CloudRoom only through `room-cli` with the commands in `crates/adapters/cloudroom/src/allowlist.rs`); to GitHub through `gh` and your personal GitHub login or OpenWiz's GitHub App. OpenWiz never touches a login, and the tests run against fakes without touching a real account.

Source: Jake, 2026-11-05: document the factory architecture described here ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
