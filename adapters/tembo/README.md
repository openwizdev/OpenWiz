# Tembo driver

Login: held by Tembo

Effort: passed as Tembo's `reasoningLevel` session setting (inside `agentOptions`), for Codex only:

| Harness | Effort |
| --- | --- |
| `codex` | `reasoningLevel`, for low, medium, high and xhigh, inside the session's `agentOptions` |
| `claude-code` | can't (Tembo documents no reasoning levels for Claude Code) |
| `claude` | can't (the same Claude Code agent as `claude-code`) |

Any other harness or value is refused with driver v1's effort refusal, and nothing runs.

The key is your `TEMBO_API_KEY`, or the keychain entry `openwiz-tembo`; only the kit's key helper reads it.

- OpenWiz never stores the key. To revoke OpenWiz's access, remove it from your environment or your keychain (or delete it in Tembo's Settings, API Keys).
- The harness login (Claude Code or Codex) is a secret held by Tembo: the subscription or provider key you connected in Tembo's Settings. The run names its harness and model in its `agent` value; OpenWiz never passes the login.

A [driver v1](../../kernel/driver.v1.md) for [Tembo](https://www.tembo.io). **Platforms:** Linux and macOS, Python 3.9 or later, standard library only. Every call to Tembo goes through the [key helper](../../kernel/driver-kit/README.md#key-hosts) (driver v1 N4), as host `tembo` of `kernel/driver-kit/hosts.json` (Tembo's API at `https://api.tembo.io`): the driver sends only a method, a path and a body, never a key or an address.

- **`start`** finds the ticket's repository among those connected to Tembo (`GET /v1/repositories`, following each page's `nextCursor`, by its exact owner and name on a `github` provider with its `https://github.com/<owner>/<name>` address; it refuses a repository Tembo lists twice), then creates a session (`POST /v1/sessions`) with the ticket's prompt, that repository, `queueRightAway`, and the `agent` value `claudeCode:<model>` for Claude Code (`claude-code` or `claude`) or `codex:<model>` for Codex, where the model is Tembo's model id (such as `claude-opus-5-5`). The driver picks the session's id, and that id is the run.
- **`wake`** reads the session (`GET /v1/sessions/<id>`) and queues one follow-up message on it (`POST /v1/messages`, `deliveryMode` `queue`).
- **`stop`** interrupts the session and cancels its queued messages (`POST /v1/sessions/<id>/stop?cancelQueued=true`), then deletes it (`DELETE /v1/sessions/<id>`), which archives it and stops its VM. Stopping an archived or unknown run answers again; a wake after it is refused.

The driver keeps no state of its own: Tembo holds every run.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests, on a fake Tembo (`fixtures/fake_tembo.py`, built from the host's API reference) reached through the helper's loopback test override: `python3 -I adapters/tembo/test_driver.py`. On the real host: `python3 -I kernel/driver-kit/kit.py --driver adapters/tembo/driver --repo <owner>/<throwaway> --ticket <n> --harness claude-code --model <a Tembo model id>`.
