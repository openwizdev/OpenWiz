# Skills eval: the weekly loop

CF4 (spec #1358) keeps one eval of every shipped skill (`tools/skills-eval/`,
contract in `tools/skills-eval/contract.md`). After the first pass, one weekly
CloudRoom loop adds that week's real mistakes as synthetic cases, routes fixes
for the skills they catch, re-tries cuts and records token counts.

## Weekly scheduling, checkpoints and runbook

- **Schedule:** one fresh-thread CloudRoom loop, Mondays 15:00 UTC, created
  from `python3 -I tools/skills-eval/weekly/run.py loop-definition`. The
  orchestrator registers it once after #1363's verified merge and reads the
  schedule back. Never a second loop, a watcher, a polling loop or a sleep.
- **Checkpoints:** durable week/source checkpoints and an action ledger in
  `private/evidence/skills-eval/e3/state/`. A failed or partial read keeps
  the last success; a repeat is a no-op; an uncertain action is never resent.
- **Authority:** none new. The loop routes actions to the orchestrator; work
  lands through ordinary tickets, builders, exact-head reviews, CI and verified
  merges. It honours the credit-aware start rule (builder work deferred, kept
  pending) and starts no replay or live arm before its predecessors pass.
- **Runbook:** [tools/skills-eval/weekly/README.md](../../tools/skills-eval/weekly/README.md#weekly-runbook-1363):
  each tick's steps, stop/resume/review and current gaps.
