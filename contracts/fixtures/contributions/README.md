# Contributions contract fixtures

The keys in [valid.json](valid.json) and [broken.json](broken.json) pair
synthetic records for the same rule. Every broken record changes one value or
omits one required field.

| Rule | Valid | Broken |
| --- | --- | --- |
| `public-scope` | The pull request targets a public repository in scope. | The repository is outside public scope. |
| `outside-author` | The author is outside the record authors. | A record author opened the pull request. |
| `non-fleet-branch` | The head is a contributor's branch. | The head is a fleet branch. |
| `intake-record` | Intake names the pull request, its full head, opening time and assigned family. | Intake omits the assigned family. |
| `hour-from-opening` | The first review lands at 3,600 seconds from opening. | The review lands at 3,601 seconds. |
| `hour-from-latest-push` | The window starts at the latest push after a review. | The window starts at an earlier push. |
| `miss-record` | A window over an hour has a miss record. | The miss record is absent. |
| `finding-fact` | The finding gives a specific fact. | The finding omits the fact. |
| `finding-command` | The finding gives a concrete next command. | The command contains only spaces. |
| `approval-verdict` | The second agent gives an APPROVE. | The verdict is CHANGES. |
| `approval-head` | The approval names a full head SHA. | The approval names an abbreviated SHA. |
| `approval-family` | The second agent belongs to the other model family. | Both agents belong to the same family. |
| `contributors-row` | The row identifies the contributor and their first and latest merged pull requests. | The latest pull request is absent. |
| `changelog-thanks` | The line ends by thanking the contributor by login. | The line omits the thanks. |
| `perk-on-merge` | The grant identifies a merged pull request as its credit key. | The pull request is unmerged. |
| `perk-credit-count` | The grant carries the owner-set count of free requests. | The credit count is negative. |

From the repository root, run with a Python environment that already provides
`jsonschema` with Draft 2020-12 support.

```sh
python3 -I contracts/fixtures/contributions/test_fixtures.py
```
