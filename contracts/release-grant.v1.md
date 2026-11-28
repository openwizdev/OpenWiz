# OpenWiz release grant v1 (`openwiz.release-grant.v1`)

The owner records the standing release grant in the [fleet's Approval rules](../docs/agents/fleet.md#approval-rules). Only the owner can add or change that grant. Without the recorded grant, automatic patch shipping and automatic pulls are both refused.

## Record

In the single top-level `## Approval rules` section, use the existing `Rule` and `Approver` table. Add the applicable rows using the exact rule text and the owner name Jake. Each action can appear once. This example uses a synthetic date, decision and pointer.

```markdown
| Rule | Approver |
| --- | --- |
| Standing release grant: ship a 0.x.y patch after 0.2.0 launches when every release gate is green | Jake |
| Standing release grant: pull a broken release from latest | Jake |

Jake, 2035-01-02: Approved the standing release grants listed in this table ([private record](https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001)).
```

Place the decision on its own line, as the first text after a blank line below the table. Use a valid calendar date in `YYYY-MM-DD` form and one comment URL in the [public pointer form](open-development.v1.md#the-pointer). The reader checks the pointer's syntax offline. The owner records the actual decision in the linked comment.

Every `0.x.0` stays the owner's ship call. A row that purports to grant shipping a minor release is invalid. The patch row covers stable `0.x.y` releases with `y > 0` after `0.2.0` launches. Shipping still requires exact-head approval from the other model family, green CI, proof from a clean machine, and the changelog. The pull row covers taking a broken release off latest when live checks fail or public regression reports meet the owner's threshold. It grants no authority to ship a release.

## Reader

Run `python3 -I tools/release/grant.py check patch|pull [--fleet <path>]`. The default fleet file is `docs/agents/fleet.md` in the reader's checkout. The reader uses the first table immediately below the unique Approval rules heading. Code examples, HTML comments and literal HTML blocks cannot supply the heading, rows or decision.

The reader exits 0 and reports the recorded grant on stdout when the requested row and decision are valid. It exits 1 and prints a reason on stderr for an absent grant, malformed or duplicate standing grant row, missing or invalid decision or pointer, or failed read. A malformed standing grant row invalidates the whole record. The phrase `Standing release grant` is reserved for these rows. The reader checks the standing record alone. Callers check the candidate version, launch status, release gates and breakage before acting. The reader writes no files and makes no network calls.

See the [synthetic fixtures](fixtures/release-grant/README.md) for examples and expected outcomes.
