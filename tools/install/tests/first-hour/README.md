# The installed first hour, through a verified merge

The installed-consumer journey from a fresh install to the first merge read back from GitHub, on recording CloudRoom and GitHub providers, with its fault cases and the live kit's offline checks. Synthetic throughout: every document is a `recording` or a fixture, never a pass.

```sh
python3 -I tools/install/tests/first-hour/test_journey.py       # the journey and its fault cases (about 90 s)
python3 -I tools/install/tests/first-hour/test_kit.py           # the live kit's offline proofs
python3 -I tools/install/tests/first-hour/kit.py dry-run [ELIGIBILITY.json]
python3 -I tools/install/tests/first-hour/test_first_merge.py   # the 0.0.16 receipt (about 2 min)
python3 -I tools/install/tests/first-hour/first_merge_kit.py dry-run [ELIGIBILITY.json [BINDING.json]]
```

CI runs them through `tests/checks/skills.rs` (`install_journey_and_live_kit_pass`, `setup_onboard_journey_passes`).

| File | What |
| --- | --- |
| `journey.py` | One attempt: the install journey with `first-hour.json`'s conversation, then the installed `fleet.sh spec` deciding each step (review, merge, archive, next ticket) on the recording providers. It writes one `result` and one `recovery` per fault case, and the 0.0.16 `first_merge_receipt` |
| `first-hour.json` | The recorded conversation: one small idea on the owner's own repository, spec and plan approvals, the user's harness, model and Cloud choices |
| `test_journey.py` | The proofs; expected codes are written by hand. `KnownWaysToFail` replays realistic bugs: a blind merge retry, a restarted reviewer, red CI, a stale verdict |
| `kit.py`, `first_merge_kit.py` | Dry run, eligibility check and result or receipt validator for [first-hour-live-kit.md](../../first-hour-live-kit.md) and its 0.0.16 extension |
| `providers/` | The recording and fault providers |

## Evidence and validation

Documents are strict `openwiz.first-hour.v1` JSON, checked by the [schema](../first-hour-contract/first-hour.schema.json) and [cross-field checks](../first-hour-contract/check.py); see the [synthetic examples](../../../../tests/fixtures/first-hour/README.md). The clock runs from opening the install instruction to GitHub's read-back of the first merge, at most 3,600,000 ms. Its three gates are `cloudroom_setup`, `paid_offer` (the offer is free-only, settled by #2293) and `feedback` (settled by #2292).

## Fault cases

Each compares the owner's work and the providers' effect and read-back counts before and after.

| Case | What happens |
| --- | --- |
| `repeat_approval` | The launch is approved twice: no second tick or builder |
| `process_restart` | The fleet stops after starting the reviewer; on restart it reads the thread back and starts nothing again |
| `revoked_access` | The App is removed: the merge is refused with no effect, setup says `app_revoked` |
| `lost_reply` | The merge's reply is lost after it merged: it reads the pull request back and doesn't merge again |
| `update_rejected` | A tampered update is refused and the last good build stays |
| `setup_interrupted` | Access setup stops before a reply and resumes with the same operation id |

Not proven here: `browser_restart` and draft cases (no installed page) and `removal_default` (no owner yet). The clock and the `connections` stage stay unknown, since a recording measures no time and a listed harness isn't a login. Fixtures never prove a real release, account or elapsed time.
