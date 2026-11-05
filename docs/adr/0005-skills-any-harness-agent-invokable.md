# Our skills are written once and any agent, in any harness, can invoke them

Each skill lives once, in `skills/<name>/SKILL.md` (with `agents/openai.yaml` for Codex), installs through one plugin manifest for Claude Code, Codex and Copilot, and is reachable inside the repository through committed `.claude/skills/` and `.agents/skills/` links; any other agent is told to read the file and follow it. This deliberately departs from Matt Pocock's skills, which we adapt but which mark flow skills user-only (`disable-model-invocation`): an orchestrator must be able to call them itself, or fleets can't run unattended.

Source: Jake, 2026-10-30: agents may invoke skills across harnesses ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
