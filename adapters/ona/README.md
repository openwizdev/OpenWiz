# Ona driver

Login: held by Ona

Effort: passed as Ona's Codex `codexSettings.reasoningEffort` in `StartAgent`: `low`, `medium`, `high`, `xhigh` (Ona's `EXTRA_HIGH`), `max` and `ultra`; any other effort is refused, and nothing runs

The key is your `ONA_API_KEY`, or the keychain entry `openwiz-ona`; only the kit's key helper reads it.

- OpenWiz never stores the key. To revoke OpenWiz's access, remove it from your environment or your keychain (or delete the token in Ona's settings).
- The harness login (Codex) is held by Ona: Codex runs on Ona's runner with the model access your organization set up there (Ona's LLM integration); OpenWiz never passes it.

A [driver v1](../../kernel/driver.v1.md) for [Ona](https://ona.com) (formerly Gitpod). **Platforms:** Linux and macOS, Python 3.9 or later, standard library only. Every call to Ona goes through the [key helper](../../kernel/driver-kit/README.md#key-hosts) (driver v1 N4), as host `ona` of `kernel/driver-kit/hosts.json`: the driver sends only a method, a path and a body, never a key or an address. Ona's API is Connect RPC: every call is a JSON `POST` to `/api/gitpod.v1.<Service>/<Method>`.

- **Harness:** `codex` only. Ona's public API runs one third-party harness, its Codex agent (agent id `00000000-0000-0000-0000-000000007800`). Any other harness is refused before any call. The model is one of Ona's Codex models, written as Ona's dashboard names it (`gpt-6.1-sol`, `gpt-6-sol`, `gpt-5.5` and so on: Ona's `CODEX_OPEN_AI_MODEL_` names in lower case, with `-` or `.` between words).
- **`start`** starts Codex (`AgentService/StartAgent`) on `https://github.com/<repository>` as its context, with the model (and the effort, when the start carries one) in `codexSettings`, then sends the ticket's prompt to it (`AgentService/SendToAgentExecution`): `StartAgent` takes no prompt. It answers Ona's agent execution id as the run. When the prompt can't be sent, its error names the run, so `driver stop` can end it.
- **`wake`** reads the run (`AgentService/GetAgentExecution`) and sends the follow-up to that same execution (`SendToAgentExecution`). A run whose turn has finished waits for input (`PHASE_WAITING_FOR_INPUT`), and a run still busy queues the message for its next turn. A stopped run (`PHASE_STOPPED`) or one Ona answers `404 not_found` for is refused.
- **`stop`** stops the execution (`AgentService/StopAgentExecution`) and every environment the run's agent created (`EnvironmentService/StopEnvironment`, for each of its `usedEnvironments` marked `createdByAgent`). It stops them and never deletes them, so their work stays until you delete them in Ona. Stopping a stopped run, or one Ona answers `404 not_found` for, answers again. An environment counts as stopped when `StopEnvironment` succeeds, answers `404 not_found`, or `GetEnvironment` shows it stopping, stopped or deleted.
- **Unreadable answers fail closed.** Any other status, a body that isn't a JSON object, a run with another id or a phase Ona doesn't document (`PHASE_PENDING`, `PHASE_RUNNING`, `PHASE_WAITING_FOR_INPUT`, `PHASE_STOPPED`), or environments listed off their shape is a D3 error that names the run, before wake or stop sends anything. A write is done only on `200` with a JSON object.

The driver keeps no state of its own: Ona holds every run.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests, on a fake Ona (`fixtures/fake_ona.py`, built from Ona's API reference) reached through the helper's loopback test override: `python3 -I adapters/ona/test_driver.py`. On the real host: `python3 -I kernel/driver-kit/kit.py --driver adapters/ona/driver --repo <owner>/<throwaway> --ticket <n> --harness codex --model gpt-6.1-sol`.
