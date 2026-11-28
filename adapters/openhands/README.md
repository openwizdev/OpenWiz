# OpenHands Cloud driver

Login: held by OpenHands Cloud

Effort: the host can't set it (OpenHands Cloud can't set effort per run; set it on your saved ACP profile)

The key is your `OPENHANDS_API_KEY`, or the keychain entry `openwiz-openhands`; only the kit's key helper reads it.

- OpenWiz never stores the key. To revoke OpenWiz's access, remove it from your environment or your keychain (or delete it in OpenHands Cloud's API keys settings).
- The harness login (Claude Code or Codex) is a secret held by OpenHands Cloud. The agent profile the run uses names it in its `secret_refs`; OpenWiz never passes it.

A [driver v1](../../kernel/driver.v1.md) for [OpenHands Cloud](https://app.all-hands.dev). **Platforms:** Linux and macOS, Python 3.9 or later, standard library only. Every call to OpenHands Cloud goes through the [key helper](../../kernel/driver-kit/README.md#key-hosts) (driver v1 N4), as host `openhands` of `kernel/driver-kit/hosts.json`: the driver sends only a method, a path and a body, never a key or an address.

- **`start`** picks your agent profile for the run, creates an app conversation (`POST /api/v1/app-conversations`) with the ticket's prompt, and answers its id as the run. Save an ACP profile in OpenHands Cloud (Settings, Agent profiles) with the exact `acp_server` and `acp_model` and its harness login as a secret. Use `claude-code` for Claude Code and `codex` for Codex. `start` accepts a validated start task or confirms the same conversation by id after an ambiguous create response.
- **`wake`** waits a bounded time for a conversation still starting, resumes its sandbox if paused (`POST /api/v1/sandboxes/<id>/resume`), then sends the follow-up (`POST /api/v1/app-conversations/<id>/send-message`). If the sandbox changes state before the send, the driver refreshes the conversation and resumes a confirmed pause within the retry window. It answers after OpenHands Cloud confirms delivery.
- **`stop`** waits for a conversation still starting, pauses its sandbox (`POST /api/v1/sandboxes/<id>/pause`) and deletes the conversation (`DELETE /api/v1/app-conversations/<id>`). A pause or delete answered 404 counts only once a fresh lookup confirms the sandbox paused or the conversation gone. Stopping a run OpenHands no longer has answers again; a wake after it is refused.
- **Untrusted answers.** The driver checks each host answer it acts on against OpenHands Cloud's documented shape: a conversation lookup must name the run itself, with a documented sandbox status; a start task must have a documented status; each action must answer `success: true`. Anything else, including an unreadable answer, is refused with the run id: never read as success, as stopped or as absent.

OpenHands Cloud holds every run. Before a create, the driver stores the candidate run id and a hash of the start request in `~/.local/state/openwiz/openhands` (or `OPENWIZ_OPENHANDS_STATE`). A retry on the same machine checks that id without sending a second create. When `start` confirms the run or `stop` confirms it ended, the driver clears the local receipt. If OpenHands Cloud confirms there is neither a conversation nor a pending start for an unresolved id, remove only that id's `<run>.pending` receipt before starting again.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Run the loopback suite with `python3 -I adapters/openhands/test_driver.py`. `OPENWIZ_OPENHANDS_POLL` sets the interval between lookups in seconds (default 3), and `OPENWIZ_OPENHANDS_WAIT` sets the wait window (default 90 seconds). The release package includes this README and `fixtures/kit-host.json` for the kit's key check. Run the kit on the real host with `python3 -I kernel/driver-kit/kit.py --driver adapters/openhands/driver --repo <owner>/<throwaway> --ticket <n> --harness claude-code --model <your profile's acp_model>`. The key-check fixture uses the model supplied to the kit.
