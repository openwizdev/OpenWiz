# Synthetic one-tap publish fixtures

Each row names the key for one case in both [valid.json](valid.json) and
[broken.json](broken.json). Each broken case changes one observation from
its valid pair.

`command`, `kind`, `path`, `check` and optional `receipt.path` describe
the invocation. `check_state` is the preflight result, including unreadable
input. `receipt.checks_passed` counts passes in the kit receipt for this
artifact and `receipt.current` records whether that evidence is current.
`skill_check_passed` records whether the skill's own gate passed.

`preview.files` enumerates the proposed files and records whether each
appeared in the preview. `preview.account` names the login shown for the pull
request. A null preview means there was no offer. `answer` is the reply
without the line terminator, or null for EOF or no question. `attempts` counts
post attempts. `stdout` contains one entry per physical output line, with each
line already parsed as JSON. `recorded` is the caller's result when the step
is absent. The runtime consumers supply and test these observations.

| Pair | Broken observation |
| --- | --- |
| `isolated-command` | Python runs without isolation. |
| `kind` | The kind is outside the supported set. |
| `folder-argument` | The artifact folder argument is missing. |
| `check-argument` | The check report argument is missing. |
| `receipt-argument` | The supplied receipt has no path argument. |
| `single-call` | The flow invokes the step twice. |
| `passing-check` | The step posts despite a failed check. |
| `private-before-offer` | The step offers and posts files containing a private repository reference. |
| `single-result-line` | The step emits two result lines. |
| `result-schema` | The result uses a different schema version. |
| `result-outcome` | The result uses an unknown outcome. |
| `posted-url` | A posted result has no pull request URL. |
| `market-url` | The URL points outside WizMarket. |
| `posted-status` | A posted result has an unsupported listing status. |
| `posted-exit` | A posted result exits 3. |
| `preview-files` | The preview leaves out a proposed file. |
| `preview-account` | The preview leaves out the publisher account. |
| `preview-before-question` | The question precedes the preview. |
| `plain-yes` | The step posts after “yes please”. |
| `at-most-one-post` | One offer makes two post attempts. |
| `declined-exit` | A declined result exits 0. |
| `declined-no-post` | The step attempts a post after a decline. |
| `declined-no-url` | A declined result contains a pull request URL. |
| `declined-eof` | An exact yes is treated as a decline. |
| `refused-exit` | A refused result exits 0. |
| `refused-reason` | A refused result omits its reason. |
| `single-line-reason` | A refusal reason spans two lines. |
| `refused-no-post` | The step attempts a post despite a failed check. |
| `private-repository` | A private repository refusal is paired with a clear scan. |
| `private-account` | A private account refusal is paired with a clear scan. |
| `private-path` | A private path refusal is paired with a clear scan. |
| `never-retry` | The step retries a post it could not confirm. |
| `unreadable-exit` | Unreadable input exits 1. |
| `unreadable-stdout` | Unreadable input emits a result line. |
| `verified-driver` | A verified driver has no receipt. |
| `verified-harness` | A verified harness receipt has only four passes. |
| `current-receipt` | A verified driver uses a stale receipt. |
| `verified-skill` | A verified skill lacks a passing skill check. |
| `listed-loop` | A loop is marked verified. |
| `listed-without-receipt` | A listed driver is changed to verified without a receipt. |
| `status-follows-proof` | A driver with qualifying proof is marked listed. |
| `unavailable-no-call` | The caller invokes the missing step. |
| `unavailable-no-offer` | The caller offers to publish with the step missing. |
| `unavailable-record` | The caller records a decline when the step is missing. |

Run `cargo test --locked -p openwiz-tests --test checks market_publish`.
The [red run](red-run.txt) captures the test rejecting the permissive schema.
