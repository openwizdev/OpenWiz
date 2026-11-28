# Hot-update v1 fixtures

Every row maps to a pair in [cases.json](cases.json). Its `valid` and
`broken` values are full synthetic documents. `path` and `keyword` identify
the expected schema refusal. Run the proof from the checkout root with
Python's Draft 2020-12 `jsonschema` validator available.

```sh
python3 -I contracts/fixtures/hot-update/test_fixtures.py
```

| Pair | Rule |
| --- | --- |
| `schema-version` | The schema identifier must be v1. |
| `manifest-kernel` | The manifest recognizes `kernel` and refuses an unknown kind. |
| `manifest-skills` | The manifest recognizes `skills` and refuses an unknown kind. |
| `manifest-driver` | The manifest recognizes `driver` and refuses an unknown kind. |
| `manifest-market-item` | The manifest recognizes `market-item` and refuses an unknown kind. |
| `manifest-id` | A component ID is a portable slug. |
| `manifest-version` | A component version has three numeric parts without a tag prefix. |
| `manifest-sha256` | The SHA-256 uses 64 lowercase hex digits. |
| `installed-owner-only` | The installed set is owner-only. |
| `installed-current` | An installed component records its current version. |
| `installed-last-good` | An installed component records its last good version. |
| `installed-history` | History retains at most five entries. |
| `swap-stage` | Staging beside the old version comes first. |
| `swap-verify` | SHA-256 verification precedes selection. |
| `swap-atomic` | Selection uses one atomic switch. |
| `swap-check` | The health check follows the switch. |
| `swap-mark-good` | A passing check ends by marking the candidate good. |
| `swap-roll-back` | A failed check ends with rollback. |
| `swap-timeout` | A timeout ends with rollback. |
| `rollback-window` | The rollback window is five minutes. |
| `health-kernel` | A `kernel` health check runs `self-check`. |
| `health-skills` | A `skills` health check runs `lock-verify`. |
| `health-driver` | A `driver` health check runs `driver-check`. |
| `health-market-item` | A `market-item` health check runs `listing-check`. |
| `health-result` | A health check records pass, failure or timeout. |
| `rollback-health` | A failed health check triggers rollback. |
| `rollback-pulled` | A pulled running version triggers rollback. |
| `pulled-list` | The release record carries a pulled list. |
| `pulled-last-good` | A pulled release names the last good successor. |
| `pulled-reason` | A pull records a live-check failure or the regression threshold. |
| `launch-at-start` | A launch resolves its versions once at start. |
| `launch-exact-version` | Running launches retain exact versions across swaps. |
| `updates-default` | An unset owner preference defaults to asking. |
| `updates-ask` | Explicit `ask` requires confirmation. |
| `updates-auto-patches` | `auto-patches` permits a verified patch automatically. |
| `updates-minor` | A minor always asks, even in `auto-patches`. |
| `updates-major` | A major version also requires confirmation. |
| `updates-auto-rollback` | `auto-patches` permits a pulled-release return automatically. |
| `updates-ask-rollback` | `ask` requires confirmation for a pulled-release return. |
