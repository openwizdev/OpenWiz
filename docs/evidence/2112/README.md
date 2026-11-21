# #2112 evidence: the long form of a Links line

Synthetic fixtures for the plan links contract's long-form Links line, written by hand from the contract, never computed by a checker.

| File | What |
| --- | --- |
| `graph.json` | A graph read of `synthetic-owner/synthetic-repo`: #9102 names its blocker in this repository's long form, #9103 in mixed case, and #9104 in another repository's long form |
| `report.json` | The link checker's expected JSON report on it: #9102 real, #9103 file, and one `malformed` refusal for #9104 that names its line |
| `red.log` | Both records validated against `contracts/plan-links.v1.schema.json` at `main`: the report's refusal is refused |
| `green.log` | The same validation after the fix: both records are valid |

OpenWiz carries no link checker, so these records prove the contract's shapes only. The reading rule itself is proved by WizSkills' `skills/to-tickets/check-links.sh` on the same graph read, in its own pull request.
