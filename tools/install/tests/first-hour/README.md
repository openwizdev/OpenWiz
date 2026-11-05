# The installed first hour through a verified merge (#2204)

P5 of #2194: the installed-consumer journey extended from a running first fleet
through independent review, CI and a merge read back from GitHub, with #2222's
fault cases rerun on it, and the bounded live kit's offline checks. Synthetic
throughout; every document is a `recording` or a test fixture, never a pass.

```sh
python3 -I tools/install/tests/first-hour/test_journey.py   # the journey and its fault cases (about 90 s)
python3 -I tools/install/tests/first-hour/test_kit.py       # the live kit's offline proofs
python3 -I tools/install/tests/first-hour/kit.py dry-run [<eligibility.json>]
```

CI runs both suites from `tests/checks/skills.rs` (`install_journey_and_live_kit_pass`).

| File | What |
| --- | --- |
| `journey.py` | One attempt. It runs #1109's install journey (`../journey/test_journey.py`) unchanged, swapping only its conversation for `first-hour.json`, then the join: the tick's starts land on a recording CloudRoom (a fake `room-cli thread list`) and a recording GitHub (#1108's fake gh world); at each step the **installed** `runtime/skills/launch-fleet/scripts/fleet.sh spec` decides what is due (review, then merge, then the archive and the next ticket), reading those providers. It builds the attempt's first-hour `result` document and one `recovery` document per fault case. |
| `first-hour.json` | The recorded conversation: one fresh small idea on the owner's own selected repository (the one setup prepared, not the demo), separate spec confirmation and plan approval, and the user's explicit harness, model, effort and Cloud choice, with the other-family reviewer's sign-in explained before the plan. |
| `test_journey.py` | The proofs. Every expected code is written by hand from contracts/first-hour.v1.md; #2200's checks (through #2222's `providers/codes.py`) give the actual ones. `KnownWaysToFail` reruns the attempt with one realistic bug each (a blind merge retry, a restart that starts the reviewer again, red CI, a stale verdict). |
| `kit.py`, `test_kit.py` | The offline dry run, eligibility check and result validator of [first-hour-live-kit.md](../../first-hour-live-kit.md). |
| `providers/` | #2222's recording and fault providers (its own folder). |

## The fault cases on this journey

Each compares the owner's work before and after (setup and onboarding records
by the SHA-256 of their canonical JSON, the branch's head, the commit's tree,
each pending intent's id and request fingerprint) and the providers' effect,
call and read-back counts:

| Case | Seam on the installed journey |
| --- | --- |
| `repeat_approval` | The approved launch confirmed again through the installed onboarding helper: no second tick, no second builder |
| `process_restart` | The engine stops after CloudRoom started the reviewer, before its record; on restart it reads the thread back by title first and starts nothing again |
| `revoked_access` | The App's installation removed: GitHub refuses the merge with no effect; the installed setup check says `app_revoked`; reconnecting reads `app_verified` |
| `lost_reply` | The merge's reply lost after its effect: the pull request is read back (merged at the approved head) before anything else; no second merge |
| `update_rejected` | A tampered update through the actual install entry after the merge: refused, the last good build stays, the setup, onboarding record and merged branch unchanged |
| `setup_interrupted` | The installed runtime's access setup (`runtime/access/access.py` and its store) on the journey's own state, with #2222's recording access provider: stopped before any reply, resumed with the same operation id |

**Named gaps (PR4 stays unproven).** `browser_restart` and the same-tab draft
cases need the installed server and page, which #1109's synthetic bundle
replaces with inert programs; their contract-seam proof stays #2222's.
`removal_default` has no owner on main yet (install.v1 leaves removal to later
tickets), as #2222's ruling records. The result names both under its PR4 gap.

**What the result shows.** Every stage is verified on recorded evidence except
`connections`: setup reports the harness only as listed, which is not a usable
login, so it stays `unknown`. The clock is unknown (a recording measures no
time), PR1 and PR2 stay with #2207's live run, and the `cloudroom_setup` gate is
unresolved. The `paid_offer` and `feedback` gates name their verified producers
#2293 and #2292; this journey does not exercise their flows.

**Proof limits.** Fixtures prove the join's gating, effects and recovery, never
a real release, account, login, elapsed time or live behaviour.
