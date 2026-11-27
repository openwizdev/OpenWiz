# Capy driver

Login: held by Capy

Effort: passed as `reasoningMode` for none, instant, minimal, low, medium, high, xhigh, and max.

The key is your `CAPY_API_KEY`, or the keychain entry `openwiz-capy`; only the kit's key helper reads it.

- OpenWiz never stores the key. To revoke OpenWiz's access, remove it from your environment or your keychain (or revoke it in Capy's Settings, API).
- The harness login (Claude Code or Codex) is a secret held by Capy: the subscription you connect in Capy's Settings, Models. The run names it by its model; OpenWiz never passes it.
- **What a run bills:** model tokens go to the first connection in your Capy order that serves the run's model, so a connected Claude Code or Codex subscription pays for them, and with none, your Capy credits do. The run's machine time uses your plan's included machine minutes first, then your Capy balance, separately from model tokens ([Capy's Models & pricing page](https://docs.capy.ai/models-and-pricing)).

A [driver v1](../../kernel/driver.v1.md) for [Capy](https://capy.ai). **Platforms:** Linux and macOS, Python 3.9 or later, standard library only. Every call to Capy goes through the [key helper](../../kernel/driver-kit/README.md#key-hosts) (driver v1 N4), as host `capy` of `kernel/driver-kit/hosts.json`: the driver sends only a method, a path and a body, never a key or an address.

- **`start`** runs the ticket in the Capy project `CAPY_PROJECT_ID` names, when you set it (a project id from Capy's Settings, Projects & setup; not a credential), or else in the one project that lists the repository (`GET /api/v1/projects`). With neither, or with more than one project listing it, it refuses and names `CAPY_PROJECT_ID`; it never guesses a project. It creates a thread there (`POST /api/v1/threads`) with the ticket's prompt and the model `anthropic/<model>` for `claude` or `claude-code`, or `openai/<model>` for `codex`, and answers the thread's id as the run. A model already named `anthropic/…` (or `openai/…` for `codex`) is sent as it is; one named for the other provider is refused before any call. Project lookup, create and its retry share a 110-second budget. If a create's answer is lost, the driver retries once within that budget with the same `requestId`, which Capy turns into the same thread. If the driver still cannot confirm the result, it tells you that a thread may have started and which title to check in Capy. A create Capy rate-limits (429) is retried once if the requested wait is at most 30 seconds and fits the budget. If the retry is also rate-limited, the refusal gives the new wait time when Capy supplies one. A start the key helper refused before sending anything (no key, say) answers the helper's own advice. An effort outside Capy's `reasoningMode` values (`none`, `instant`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) is refused with driver v1's effort refusal before any call. When Capy refuses the model, the driver reads your models (`GET /api/v1/models`) to say why, and says it is unsure when that list is unreadable.
- **`wake`** reads the thread (`GET /api/v1/threads/<id>`) and steers a follow-up into it (`POST /api/v1/threads/<id>/message`). A message would unarchive a stopped thread, so a wake of an archived one is refused before anything is sent.
- **`stop`** interrupts the thread (`POST /api/v1/threads/<id>/interrupt`), then archives it (`POST /api/v1/threads/<id>/archive`). Stopping an archived thread answers again.
- Start records the controller for each run in `OPENWIZ_CAPY_STATE` (default `~/.local/state/openwiz/capy`). Use that controller and state folder for all wakes and stops. They take turns on the run's lock. An installation without that record refuses to wake or stop an active run. Keep the state folder on one controller. If the record is missing, manage the run in Capy.

Capy holds every run. The local controller files are empty. The driver reads each Capy answer only in the shape [Capy's OpenAPI document](https://docs.capy.ai/openapi.json) gives it (every required field, the thread's own id, its documented status and a Boolean `archived`; a field Capy adds later is ignored). Any other answer is refused, and the error names the run when one may exist: a run is unknown only on Capy's own `ThreadNotFound` for that id, a wake or a stop succeeds only on Capy's receipt for each write, a project is picked only from a readable project list, and a start answers only a thread for the exact project it sent.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests, Linux only (their cleanup reads `/proc`), on a fake Capy (`fixtures/fake_capy.py`, built from Capy's OpenAPI document) reached through the helper's loopback test override: `python3 -I adapters/capy/test_driver.py` (they set `OPENWIZ_CAPY_POLL`, the seconds before a lost create is sent again, default 3).

For the real-host kit run, choose an effort the selected model offers in Capy's Settings, Models. Set `CAPY_PROJECT_ID` because the kit's key check runs `start` against a fake host that cannot list your repository.

`CAPY_PROJECT_ID=<your project id> python3 -I kernel/driver-kit/kit.py --driver adapters/capy/driver --repo <owner>/<throwaway> --ticket <n> --harness claude-code --model <a Claude model id, such as claude-opus-5-5> --effort <effort offered by that model>`.
