# Capy driver

Login: held by Capy

Effort: passed as the run's Capy `reasoningMode`; an effort the run's model doesn't offer is refused with driver v1's effort refusal, and nothing starts

The key is your `CAPY_API_KEY`, or the keychain entry `openwiz-capy`; only the kit's key helper reads it.

- OpenWiz never stores the key. To revoke OpenWiz's access, remove it from your environment or your keychain (or revoke it in Capy's Settings, API).
- The harness login (Claude Code or Codex) is a secret held by Capy: the subscription you connect in Capy's Settings, Models. The run names it by its model; OpenWiz never passes it.
- **What a run bills:** model tokens go to the first connection in your Capy order that serves the run's model, so a connected Claude Code or Codex subscription pays for them, and with none, your Capy credits do. The run's machine time uses your plan's included machine minutes first, then your Capy balance, separately from model tokens ([Capy's Models & pricing page](https://docs.capy.ai/models-and-pricing)).

A [driver v1](../../kernel/driver.v1.md) for [Capy](https://capy.ai). **Platforms:** Linux and macOS, Python 3.9 or later, standard library only. Every call to Capy goes through the [key helper](../../kernel/driver-kit/README.md#key-hosts) (driver v1 N4), as host `capy` of `kernel/driver-kit/hosts.json`: the driver sends only a method, a path and a body, never a key or an address.

- **`start`** runs the ticket in the Capy project `CAPY_PROJECT_ID` names, when you set it (a project id from Capy's Settings, Projects & setup; not a credential), or else in the one project that lists the repository (`GET /api/v1/projects`). With neither, or with more than one project listing it, it refuses and names `CAPY_PROJECT_ID`; it never guesses a project. It creates a thread there (`POST /api/v1/threads`) with the ticket's prompt and the model `anthropic/<model>` for `claude` or `claude-code`, or `openai/<model>` for `codex`, and answers the thread's id as the run. A create whose answer is lost is sent once more with the same `requestId`, which Capy turns into the same thread. An effort outside Capy's `reasoningMode` values (`none`, `instant`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`) is refused with driver v1's effort refusal before any call. When Capy refuses the model, the driver reads your models (`GET /api/v1/models`) to say why, and says it is unsure when that list is unreadable.
- **`wake`** reads the thread (`GET /api/v1/threads/<id>`) and steers a follow-up into it (`POST /api/v1/threads/<id>/message`). A message would unarchive a stopped thread, so a wake of an archived one is refused before anything is sent.
- **`stop`** interrupts the thread (`POST /api/v1/threads/<id>/interrupt`), then archives it (`POST /api/v1/threads/<id>/archive`). Stopping an archived thread answers again.

The driver keeps no state of its own: Capy holds every run. It reads each Capy answer only in the shape [Capy's OpenAPI document](https://docs.capy.ai/openapi.json) gives it (every required field, no unlisted one, the thread's own id, its documented status and a Boolean `archived`). Any other answer is refused, and the error names the run when one may exist: a run is unknown only on Capy's own `ThreadNotFound` for that id, a wake or a stop succeeds only on Capy's receipt for each write, a project is picked only from a readable project list, and a start answers only a thread for the project it sent (or none named).

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests, Linux only (their cleanup reads `/proc`), on a fake Capy (`fixtures/fake_capy.py`, built from Capy's OpenAPI document) reached through the helper's loopback test override: `python3 -I adapters/capy/test_driver.py` (they set `OPENWIZ_CAPY_POLL`, the seconds before a lost create is sent again, default 3). On the real host, with `CAPY_PROJECT_ID` set (the kit's key check runs `start` against a fake host that can't list your repository): `CAPY_PROJECT_ID=<your project id> python3 -I kernel/driver-kit/kit.py --driver adapters/capy/driver --repo <owner>/<throwaway> --ticket <n> --harness claude-code --model <a Claude model id, such as claude-opus-5-5>`.
