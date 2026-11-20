# KN8 recorded run (template)

Fill each field from the sanitized records in `run/`. Use only public forms: decisions, dates, numbers and pointers. Exact words and thread ids stay on the private record. Leave `not run` in every field until the run happens.

| Field | Value |
| --- | --- |
| Date (UTC) | not run |
| Repository | `openwizdev/WizSkills` |
| Orchestrator | Hermes `<version>`, model `<model>`, skills `<skill@version, ...>` |
| Host | `local` (`docs/agents/host.md` at `<commit>`), permission mode `<mode>` |
| Grill | private record: `<pointer>` (decisions only, here) |
| Spec and ticket | `openwizdev/WizSkills#<spec>`, `#<ticket>` |
| Plan approval | `<pointer to the owner's approval record>` |
| Builder start | `launch-fleet: started` comment `<link>`; driver `start` answered `run-000000000001` |
| Builder | Claude Code `claude-opus-5-5` Medium; status note `<link>` |
| Pull request | `openwizdev/WizSkills#<PR>`, head `<sha>` |
| Recorded claim | `<link>` |
| CI | `check` green at `<sha>`: `<run link>` |
| Review | Codex Sol 6.2 Medium, `VERDICT: APPROVE at <sha>`: `<link>` |
| Merge | `PUT .../merge` with `sha=<sha>`; read back as merged, merge commit `<sha>` |
| Owner steps | the numbered steps of README.md that were taken, and any step that was not |
| Interventions | each time the owner stepped in, and why (public form) |

## Acceptance

- [ ] A recorded end-to-end run on a maintained repository, ending in a merged pull request that passed review and CI: the rows above, each with its link.
- [ ] Nothing private in the evidence: `sanitize.py` exited 0 with literals required, `tools/privacy-check/check.py --tree kernel/proofs/hermes --literals <list> --require-literals` exits 0, and a person has read every file in `run/`.
