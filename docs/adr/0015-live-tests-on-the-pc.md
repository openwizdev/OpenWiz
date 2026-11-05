# Full live tests on the PC, with a quick Mac check per release

OpenWiz must work on both machines; a test proves only the machine it runs on.

Full live tests run on the PC (the always-on CloudRoom hub), from a Local thread there. Jake approves each live step from any device; use throwaway test threads only.

Each release also gets a quick Mac check: a few minutes when Jake is at the Mac (install that version, `openwiz ls` and `openwiz show` read-only, nothing written), recorded with the release.

The Mac-only checks stay on the Mac: the Mac's fixed `room-cli` location, adding the Mac to the PC's CloudRoom, and the Mac shut for a day.

The standing approval for read-only discovery spikes covers the PC as well as the Mac.

This supersedes only the Mac-only live-test and discovery-spike directions in `AGENTS.md`, the private acceptance and machine records, the `live-quick-check` and `live-spike` skills, and the 0.0.8 live-tests amendment. Existing write approvals, spike limits and privacy rules stay in force. [ADR 0009](0009-live-tests-run-while-jake-works.md) still applies: tests run while Jake works, scoped to their own threads and processes.

Source: Jake, 2026-11-01: use the PC for full live tests and retain a short Mac check for each release ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
