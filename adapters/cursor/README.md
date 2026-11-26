# Cursor cloud agents driver

Login: held by Cursor

Effort: the host can't set it (the driver uses the Cloud Agents API's model ID and sends no separate effort setting). A start that carries `effort` is refused before contacting Cursor.

- The key is your own `CURSOR_API_KEY`, or the keychain entry `openwiz-cursor-cloud` when that variable is unset.
- OpenWiz never stores it. Removing it from your environment or keychain only stops OpenWiz using it here; the key stays valid at Cursor until you revoke it in Cursor's dashboard (API Keys). If it may have leaked, revoke it there.

A [driver v1](../../kernel/driver.v1.md) that runs each builder as one [Cursor cloud agent](https://cursor.com/docs/cloud-agent), on its own Cursor-hosted machine, through Cursor's Cloud Agents API (v1, public beta). One Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later. Runs are saved in `$OPENWIZ_CURSOR_STATE` (default `~/.local/state/openwiz-cursor`), owner-only: the folder is mode 0700, and each run file is created mode 0600 and then renamed into place.

Every Cursor call goes through the kit's key helper, [`hostkey.py`](../../kernel/driver-kit/hostkey.py), for host `cursor-cloud` (driver v1 N4). The driver sends it only a method, a path and a body. The helper alone reads the key and sends it to Cursor's registered address (`https://api.cursor.com`, in [`hosts.json`](../../kernel/driver-kit/hosts.json)). The driver never reads, names or passes the key, and never builds a URL.

| Command | What it does on Cursor |
| --- | --- |
| `start` | Saves the run with a new agent id (`bc-<uuid>`) and its flags only, then `POST /v1/agents` with that `agentId`, the repository, the model and a prompt. The prompt names the ticket and the skill, and has the agent fetch the WizSkills release OpenWiz pins (`wizskills.lock`) and check its commit and tree before it follows the skill: Cursor's machine has none of your own skills. It answers once Cursor has created the agent, and only then saves the repository, ticket and skill a wake needs. If the helper or Cursor refuses the create, the run's files are removed. If Cursor gives no answer, the driver archives the agent by the id it saved and says the outcome is unknown. If Cursor shows no such agent yet, a late create isn't ruled out: the driver says so, and a later `stop` of that run archives the agent once Cursor shows it. The same holds when the helper refuses that cleanup. |
| `wake` | While the agent's run is active, nothing: that agent is awake and reads the ticket itself. Otherwise `POST /v1/agents/{id}/runs`: a follow-up run on the same agent, with its conversation and workspace, which edits its own status note. A server error (HTTP 5xx) is transient: wake the same run again. A wake after `stop`, or on an archived agent, is refused. |
| `stop` | Cancels the agent's latest run (`POST .../runs/{runId}/cancel`), then archives the agent (`POST /v1/agents/{id}/archive`). It never deletes an agent: archiving can be undone at cursor.com/agents. If Cursor already shows the agent archived, stop leaves it so and does not archive it again. If Cursor doesn't confirm both, the answer says so and names the agent. |

**The skills pin.** From a checkout, the prompt names the WizSkills release in `wizskills.lock`. From an install, which has no lock, it names the OpenWiz commit in the runtime's `openwiz-build.txt`, and the agent reads `wizskills.lock` at that commit before fetching the release and checking its commit and tree.

**Cursor runs its own agent.** `harness` must be `cursor`: Cursor cloud agents run only Cursor's agent, not Claude Code or Codex, and the driver refuses any other harness. `model` is passed as Cursor's `model.id` unchanged, including a provider-qualified id such as `openrouter/anthropic/claude-sonnet-4.6`, up to 100 characters, as driver v1's schema allows. Cursor lists the ones you can use (`GET /v1/models`).

**Never two agents, never one left running.** Cursor runs one run per agent at a time, so a wake during an active run starts nothing. The driver saves the agent's id before it creates the agent, so a stop always reaches it. A wake, a stop and a start hold the run's lock, so they take turns. A stop marks the run stopped before it calls Cursor. If it can't save that, it still cancels and archives the agent, and a later wake is refused because Cursor shows the agent archived.

`version` adds `many-at-once` and `own-sandbox` to `can`: every run is its own agent on its own machine.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N4). Cursor's own CLI can't start, wake or stop cloud agents, so the driver calls Cursor's API through the key helper, which reads your key itself. If the helper finds no key, or refuses for any other reason before it sends anything, the driver says so and nothing is sent to Cursor.

1. Have a Cursor plan that includes cloud agents, and connect GitHub to Cursor (Cursor's Cloud Agents setup), so the agent can clone, push and comment as Cursor's GitHub app or your account.
2. Make a Cursor API key at cursor.com/dashboard (API Keys), and keep it where the key line above says: your own environment variable, or your system keychain (macOS Keychain, or the Secret Service on Linux) under that entry; the helper reads it with your system's own keychain tool.
3. Make sure your throwaway repository's `docs/agents/fleet.md` names, as a record author, the account Cursor's agent comments as.

Cursor bills cloud agents at its model rates, against your plan.

## Fixture tests (offline)

```sh
python3 -I adapters/cursor/test_driver.py      # on a synthetic Cursor; nothing reaches the network
```

Each test builds its environment from scratch, with PATH limited to one folder holding only `python3`, so no real CLI is reachable, and points the key helper at the fake Cursor on `127.0.0.1`. Cleanup ends only the fake agent runs the tests logged themselves. Where `/proc` is missing, as on macOS, those checks use `ps` instead.

## The live check (on a real Cursor account; spends money)

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/cursor/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness cursor --model <model>
```

`fixtures/fake-cursor` is a synthetic Cursor cloud agents API on `127.0.0.1`, reached through the helper's loopback test override (`OPENWIZ_HOSTKEY_TEST_ORIGIN`). Under it the helper takes a synthetic key from the fake's `GET /.openwiz/hostkey-test-key`, and the driver never holds it. It never reaches Cursor. Run as `fake-cursor <state> <log> <faults> <key file>`, it prints its origin, logs each other request (method, path, body and `Authorization` header) as one JSON line, and follows the routes and answers of Cursor's endpoint reference: `POST /v1/agents` answers `{agent, run}`, `GET /v1/agents/{id}` gives `status` (`ACTIVE`, `IDLE` or `ARCHIVED`) and `latestRunId`, and a follow-up during an active run is `409 agent_busy`. A `"<METHOD> <path suffix>"` key of the `<faults>` file answers that status instead, or drops the connection after acting (`lost`) or before (`pending`). Its runs are `fixtures/fake-agent`, which posts or edits one builder note. The code Cursor answers to a follow-up on an archived agent is a guess; the driver refuses any code it doesn't expect. `fixtures/kit-host.json` is what the kit's own fake host answers during its key check.
