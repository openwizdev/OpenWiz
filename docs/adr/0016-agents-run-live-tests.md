# Agents run the live tests; Jake dogfoods

Agents run each version's live test on throwaway test threads, under one standing approval for that version instead of approval per step. Phone and web steps use a headless browser emulating a phone, including network cuts; real-device checks become optional. The release bar is CI plus an agent-run live smoke test. Jake dogfoods and reports bugs as he goes; publishing still needs his word.

From now on a version's live test runs end to end without Jake: his approval of the version's live test is the standing OK for every step in its kit, and no step waits for his go. Steps that were his hands (Safari on a phone, cellular, Airplane Mode, the Mac as a screen) run in a headless Chromium emulating that device and network; what that can't prove (WebKit, real radios) is recorded as a gap, never claimed. His own look-and-feel verdicts become dogfood notes, not gates.

Unchanged: live writes only to the test's own throwaway threads, within the kit's counts; the `room-cli` allowlist; fail closed; no automatic retry; publishing and anything to a public place need Jake's word; the Mac-only checks stay on the Mac.

This supersedes the per-step live approval requirement in [ADR 0015](0015-live-tests-on-the-pc.md) and the per-step go rules in the `live-quick-check` skill and the version kits. [ADR 0009](0009-live-tests-run-while-jake-works.md) still applies.

Source: Jake, 2026-11-05: agents perform approved live kits end to end, with owner feedback as dogfood notes and publishing separately gated ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
