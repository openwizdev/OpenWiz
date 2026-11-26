# OpenHands Cloud driver

Login: held by OpenHands Cloud

Effort: the host can't set it (OpenHands Cloud can't set effort per run; set it on your saved ACP profile)

The key is your `OPENHANDS_API_KEY`, or the keychain entry `openwiz-openhands`; only the kit's key helper reads it.

- OpenWiz never stores the key. To revoke OpenWiz's access, remove it from your environment or your keychain (or delete it in OpenHands Cloud's API keys settings).
- The harness login (Claude Code or Codex) is a secret held by OpenHands Cloud. The agent profile the run uses names it in its `secret_refs`; OpenWiz never passes it.

A [driver v1](../../kernel/driver.v1.md) for [OpenHands Cloud](https://app.all-hands.dev). **Platforms:** Linux and macOS, Python 3.9 or later, standard library only. Every call to OpenHands Cloud goes through the [key helper](../../kernel/driver-kit/README.md#key-hosts) (driver v1 N4), as host `openhands` of `kernel/driver-kit/hosts.json`: the driver sends only a method, a path and a body, never a key or an address.

- **`start`** picks your agent profile for the run, creates an app conversation (`POST /api/v1/app-conversations`) with the ticket's prompt, and answers its id as the run. The profile is the ACP agent profile whose `acp_server` is the harness (`claude` or `claude-code` for Claude Code, `codex` for Codex) and whose `acp_model` is exactly the requested model; with none, `start` refuses and creates nothing, never falling back to a profile with another or no `acp_model`. You save these profiles yourself in OpenHands Cloud (Settings, Agent profiles), one per harness and model, each with its harness login saved as an OpenHands secret. `start` answers only on a start task in OpenHands Cloud's documented shape; any other answer refuses with the run id, so `driver stop` can end a run that may exist.
- **`wake`** waits a bounded time for a conversation still starting, resumes the run's sandbox when it is paused (`POST /api/v1/sandboxes/<id>/resume`), then sends the follow-up (`POST /api/v1/app-conversations/<id>/send-message`). It answers only after OpenHands Cloud confirms the send; a conversation still starting after the wait is refused with a retry.
- **`stop`** waits for a conversation still starting, pauses its sandbox (`POST /api/v1/sandboxes/<id>/pause`) and deletes the conversation (`DELETE /api/v1/app-conversations/<id>`). A pause or delete answered 404 counts only once a fresh lookup confirms the sandbox paused or the conversation gone. Stopping a run OpenHands no longer has answers again; a wake after it is refused.
- **Untrusted answers.** The driver checks each host answer it acts on against OpenHands Cloud's documented shape: a conversation lookup must name the run itself, with a documented sandbox status; a start task must have a documented status; each action must answer `success: true`. Anything else, including an unreadable answer, is refused with the run id: never read as success, as stopped or as absent.

The driver keeps no state of its own: OpenHands Cloud holds every run.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests, on a fake OpenHands Cloud (`fixtures/fake_openhands.py`, built from the host's OpenAPI document) reached through the helper's loopback test override: `python3 -I adapters/openhands/test_driver.py` (they set `OPENWIZ_OPENHANDS_POLL`, the seconds between looks at a starting conversation, default 3, and `OPENWIZ_OPENHANDS_WAIT`, the seconds `wake` and `stop` wait for it, default 90). On the real host: `python3 -I kernel/driver-kit/kit.py --driver adapters/openhands/driver --repo <owner>/<throwaway> --ticket <n> --harness claude-code --model <your profile's acp_model>`. The kit's key check runs on `fixtures/kit-host.json`, whose profiles name the models `Synthetic 1` and `Synthetic 2`.
