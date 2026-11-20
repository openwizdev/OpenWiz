# Conductor driver

Login: held by Conductor

A [driver v1](../../kernel/driver.v1.md) that runs each builder in its own [Conductor](https://www.conductor.build) cloud workspace, through Conductor's API (beta, `https://api.conductor.build/v0`). One Python file, standard library only, plus `curl` 8.3 or later. **Platforms:** Linux and macOS, Python 3.9 or later. Runs are saved in `$OPENWIZ_CONDUCTOR_STATE` (default `~/.local/state/openwiz-conductor`), owner-only.

| Command | What it does on Conductor |
| --- | --- |
| `start` | `POST /v0/workspaces` with `repositoryUrl` (`https://github.com/<repository>`), `name` (`openwiz-<run>`, which also names the branch), `agent` (the `harness`), `model` and the first message: the ticket and the skill. It answers once Conductor has made the workspace and its session. **Never retried:** every start makes a new workspace, so when the answer is lost the driver says the outcome is unknown and names the workspace to look for. |
| `wake` | `POST /v0/sessions/<session>/messages`: the same agent, in the same session, reads its ticket again and edits its own status note. Sent while the agent works, Conductor steers the message into the running turn, so there is never a second agent. |
| `stop` | `POST /v0/sessions/<session>/cancel`, then `POST /v0/workspaces/<workspace>/archive`, which stops the workspace's machine (Conductor can restore it later). If Conductor doesn't confirm the archive, the run stays stopped and the answer names the workspace to archive yourself. |

`harness` is one of Conductor's agents: `claude`, `codex` or `cursor`. `model` is one of Conductor's model ids for that agent (such as `opus-5-5-1m` or `gpt-6.2-sol`; the OpenAPI document at `/v0/openapi.json` lists them), passed on unchanged. `version` adds `many-at-once` and `own-sandbox` to `can`: every run gets its own cloud workspace.

## Where your logins live

- **Your Claude, Codex or Cursor login is held by Conductor.** Conductor Cloud runs the agent with the subscription token or API key you added to Conductor (Settings, Agents); the driver never sees it.
- **Your Conductor API key stays in your environment.** Every call is `curl --disable --variable %CONDUCTOR_API_KEY --expand-oauth2-bearer '{{CONDUCTOR_API_KEY}}' ...`: curl reads the key from the environment it inherits and sends it only to Conductor. The driver checks only that the name `CONDUCTOR_API_KEY` is in the environment, and never reads, prints or passes on its value (driver v1, N1 to N3).

## Before the first run (yours to do)

1. A Conductor Pro account with Conductor Cloud, its GitHub App on your repositories, and each repository you run on added to your organization's Cloud Computer.
2. In Conductor, add the subscription or API key of each agent you use (Settings, Agents), and install the WizSkills skills your fleet runs on the Cloud Computer, so the agent can follow its skill and post its status note.
3. `curl` 8.3 or later (for `--variable`). Before each command the driver runs `curl --version` and refuses an older curl by name, such as `curl 7.88.1 is too old`, before it calls Conductor.
4. Create a Conductor API key (the [API docs](https://www.conductor.build/docs/api) say where) and export it as `CONDUCTOR_API_KEY` in the shell that runs the driver.

Conductor bills nothing for model usage: each agent's own account does. Each workspace runs until it is stopped, sleeps or is archived.

## The kit

The fixture tests use only the synthetic Conductor. They touch no real host and cost nothing:

```sh
python3 -I adapters/conductor/test_driver.py      # the kit's five checks and the driver's tests, on a synthetic Conductor
```

**The live check is separate, and it costs money.** Running the kit straight on the driver starts a real Conductor cloud workspace and an agent turn billed to your agent's account. Run it only as the live check (#1993), on a throwaway repository and ticket:

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/conductor/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>   # live: real workspace, real cost
```

The tests run the kit in a wrapper that lets it read only the processes of its own run (it is their subreaper), so it never reads another process's environment on the machine. They build each environment from scratch, with `PATH` limited to `fixtures/bin` and `python3`.

`fixtures/bin/curl` is a synthetic Conductor behind a synthetic `curl`: it takes only the driver's one call shape, and its request and answer shapes follow Conductor's API reference and OpenAPI document (read 2026-11-20). Nothing in it was observed on a live account; the live check records that. It keeps its state in the file `FAKE_CONDUCTOR_STATE` and logs each call's arguments to `FAKE_CONDUCTOR_LOG`, and refuses any call that doesn't start with `--disable` (so curl reads no config file that could trace the key or retry a start); its agent posts and edits one builder note in the local tracker `KIT_TRACKER`; `FAKE_CONDUCTOR_FAIL=<METHOD> <route>=<status>` plants a refusal, and `FAKE_CONDUCTOR_LOSE=<METHOD> <route>` does the call, then loses its answer.
