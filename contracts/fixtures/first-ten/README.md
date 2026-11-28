# First-ten fixtures

All records and times are synthetic. Each value in `valid.json` or `broken.json`
is one complete JSON document for the schema. `cases.json` names the valid record
for each broken record and the schema rule the broken record must fail.

| Rule | Valid | Broken |
| --- | --- | --- |
| `install-line-started-source` | `under-600s` | `install-line-started-source` |
| `setup-done-source` | `under-600s` | `setup-done-source` |
| `harness-signed-in-source` | `under-600s` | `harness-signed-in-source` |
| `grill-confirmed-source` | `under-600s` | `grill-confirmed-source` |
| `plan-approved-source` | `under-600s` | `plan-approved-source` |
| `first-pull-request-opened-source` | `under-600s` | `first-pull-request-opened-source` |
| `first-pull-request-merged-source` | `under-600s` | `first-pull-request-merged-source` |
| `schema-version` | `under-600s` | `schema-version` |
| `os-name` | `macos-receipt` | `os-name` |
| `os-version` | `under-600s` | `os-version` |
| `candidate-version` | `under-600s` | `candidate-version` |
| `start-time` | `install-started` | `start-time` |
| `step-time` | `under-600s` | `step-time` |
| `total-time` | `under-600s` | `total-time` |
| `pass-at-600s` | `at-600s` | `pass-at-600s` |
| `pass-over-600s` | `over-600s` | `pass-over-600s` |
| `fail-under-600s` | `under-600s` | `fail-under-600s` |
| `missing-middle-step` | `under-600s` | `missing-middle-step` |
| `missing-merge-step` | `under-600s` | `missing-merge-step` |
| `quick-grill-budget` | `under-600s` | `quick-grill-budget` |
| `tiny-fleet-count` | `under-600s` | `tiny-fleet-count` |
| `tiny-fleet-size` | `under-600s` | `tiny-fleet-size` |
| `approved-fleet-required` | `plan-recorded` | `approved-fleet-required` |
| `timing-prefix` | `plan-recorded` | `timing-prefix` |
| `timing-is-not-a-receipt` | `install-started` | `timing-is-not-a-receipt` |
| `timing-keeps-private-paths-out-of-json` | `install-started` | `timing-keeps-private-paths-out-of-json` |
| `passing-step-outside-window` | `under-600s` | `passing-step-outside-window` |

Replay with Python and an existing installation of `jsonschema`.

```sh
python3 -I contracts/fixtures/first-ten/test_fixtures.py
```

The amount of time this test takes has no bearing on the ten-minute promise.
The fixtures exercise JSON contents. The timer and tracker verify actual
ownership and permissions on disk and use the timestamps from their sources.
