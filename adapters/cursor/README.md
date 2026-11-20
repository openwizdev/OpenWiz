Login: held by Cursor

# Cursor cloud agents driver

A [driver v1](../../kernel/driver.v1.md) that runs each builder as one [Cursor cloud agent](https://cursor.com/docs/cloud-agent), on its own Cursor-hosted machine, through Cursor's Cloud Agents API (v1, public beta). One Python file, standard library only. Runs are saved in `$OPENWIZ_CURSOR_STATE` (default `~/.local/state/openwiz-cursor`), owner-only.

| Command | What it does on Cursor |
| --- | --- |
| `start` | Saves the run with a new agent id (`bc-<uuid>`), then `POST /v1/agents` with that `agentId`, the repository, the model and a prompt. The prompt names the ticket and the skill, and has the agent fetch the WizSkills release OpenWiz pins (`wizskills.lock`) and check its commit and tree before it follows the skill: Cursor's machine has none of your own skills. It answers once Cursor has created the agent. If Cursor gives no answer, the driver archives the agent by the id it saved and says the outcome is unknown. |
| `wake` | While the agent's run is active, nothing: that agent is awake and reads the ticket itself. Otherwise `POST /v1/agents/{id}/runs`: a follow-up run on the same agent, with its conversation and workspace, which edits its own status note. A wake after `stop`, or on an archived agent, is refused. |
| `stop` | Cancels the agent's latest run (`POST .../runs/{runId}/cancel`), then archives the agent (`POST /v1/agents/{id}/archive`). It never deletes an agent: archiving can be undone at cursor.com/agents. If Cursor doesn't confirm both, the answer says so and names the agent. |

**Cursor runs its own agent.** `harness` must be `cursor`: Cursor cloud agents run only Cursor's agent, not Claude Code or Codex, and the driver refuses any other harness. `model` is passed as Cursor's `model.id` unchanged; Cursor lists the ones you can use (`GET /v1/models`).

**Never two agents, never one left running.** Cursor runs one run per agent at a time, so a wake during an active run starts nothing. The driver saves the agent's id before it creates the agent, so a stop always reaches it. A wake, a stop and a start hold the run's lock, so they take turns. A stop marks the run stopped before it calls Cursor. If it can't save that, it still cancels and archives the agent, and a later wake is refused because Cursor shows the agent archived.

`version` adds `many-at-once` and `own-sandbox` to `can`: every run is its own agent on its own machine.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N3). Cursor's own CLI can't start, wake or stop cloud agents, so the driver calls Cursor's API with your own `curl`, run as `curl --variable %CURSOR_API_KEY --expand-oauth2-bearer '{{CURSOR_API_KEY}}' ...`. curl reads the key itself from the `CURSOR_API_KEY` environment variable you run the driver with, and sends it as `Authorization: Bearer`. The driver never reads, holds, passes or prints the key: it is in no argument, no environment the driver builds, and no output.

1. Have a Cursor plan that includes cloud agents, and connect GitHub to Cursor (Cursor's Cloud Agents setup), so the agent can clone, push and comment as Cursor's GitHub app or your account.
2. Install curl 8.3 or later (`curl --version`): older curl has no `--variable`, and the driver refuses it before sending anything.
3. Make a Cursor API key at cursor.com/dashboard (API Keys), and set it yourself as `CURSOR_API_KEY` in the environment you run the driver from. If it is unset or empty, the driver says so and sends nothing.
4. Make sure your throwaway repository's `docs/agents/fleet.md` names, as a record author, the account Cursor's agent comments as.

Cursor bills cloud agents at its model rates, against your plan.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/cursor/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness cursor --model <model>
python3 -I adapters/cursor/test_driver.py      # the fixture tests, on a synthetic Cursor
```

`fixtures/bin/curl` is a synthetic Cursor cloud agents API behind a fake `curl`. It takes only the call the driver makes (`--version`, then the call with `--variable %CURSOR_API_KEY`), refuses any other argument, fails as real curl does when `CURSOR_API_KEY` is unset or empty, and follows the routes and answers of Cursor's endpoint reference: `POST /v1/agents` answers `{agent, run}`, `GET /v1/agents/{id}` gives `status` (`ACTIVE`, `IDLE` or `ARCHIVED`) and `latestRunId`, and a follow-up during an active run is `409 agent_busy`. Its run is `fixtures/fake-agent`, which posts or edits one builder note. The code Cursor answers to a follow-up on an archived agent is a guess; the driver refuses any code it doesn't expect.
