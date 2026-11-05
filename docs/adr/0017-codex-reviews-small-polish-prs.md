# Codex reviews Codex on small polish PRs

Codex may review Codex on small, low-risk PRs, with a different model reviewing: Terra reviews Sol, without Claude. The polish triage's 143 picks for building are approved together, and its 62 picks for dropping are dropped. Prefer OpenAI models for this work.

A PR whose ticket has the `polish` label and whose whole diff is under 200 changed lines gets a Codex reviewer: Codex, `gpt-6.1-terra`, High, fast mode, when its builder is Codex Sol. Anything bigger, and anything touching a live-test kit, release or export work, security, contracts or CI workflows, keeps a Claude reviewer from the other family, as `docs/agents/fleet.md` says.

Approved polish tickets are released about 20 at a time (label `polish-queued` until their wave), and waves stop while Cloud Credits are under 12,000, to keep room for the release path.

This narrows the other-family rule in [the fleet settings](../agents/fleet.md#reviewer) for these PRs only.

Source: Jake, 2026-11-05: approve the small-polish reviewer exception and the recorded triage dispositions ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
