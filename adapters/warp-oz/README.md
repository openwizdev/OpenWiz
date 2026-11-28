# Warp Oz driver

Login: held by Warp Oz

Effort: passed as `config.harness.reasoning_level` for Codex; Warp Oz can't set it for Claude Code

| Harness | Effort |
| --- | --- |
| `codex` | passed as `config.harness.reasoning_level`: `low`, `medium`, `high` or `xhigh` |
| `claude` | can't (Warp's Claude Code harness documents no reasoning level, and Warp ignores one a harness doesn't support) |

- The key is your own `WARP_API_KEY`, or the keychain entry `openwiz-warp-oz` when that variable is unset.
- OpenWiz never stores it. Remove it from your environment or keychain to revoke it.
- The harness login (Claude Code or Codex) is a secret Warp Oz holds. The run names it, and OpenWiz never passes it.

A [driver v1](../../kernel/driver.v1.md) for [Warp Oz](https://docs.warp.dev) cloud agents: each run is one Warp cloud agent run, and its run id is Warp's run id, a UUID. One Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later.

Every Warp call goes through the kit's key helper, [`hostkey.py`](../../kernel/driver-kit/hostkey.py), for host `warp-oz` (driver v1 N4). The driver sends it only a method, a path and a body. The helper alone reads the key and sends it to Warp's registered address, `https://app.warp.dev`, the origin of the `servers` entry of [Warp's OpenAPI document](https://docs.warp.dev/openapi.json) (`https://app.warp.dev/api/v1`, with a bearer key). The driver never reads, names or passes the key, and never builds a URL.

| Command | Warp call (agent runs API, under `/api/v1`) |
| --- | --- |
| `start` | `POST /api/v1/agent/runs` with `prompt` (the skill's one-line brief, as the template's) and `config`: `harness` (`type` `claude` or `codex`, `model_id` unless `model` is `default`, and `reasoning_level` when `effort` is set), `harness_auth_secrets` (the name of your Warp secret for that harness) and, when set, `environment_id`. It saves the run before it answers. If it can't save it, it cancels the run and says the outcome is unknown. A create whose answer is lost (the connection drops, Warp answers 408 or 5xx, or the helper fails after it may have sent) is also an unknown outcome: the error says to look for the run in Warp and reconcile it before starting again, never to retry. Only a 4xx answer (except 408) or a refusal the helper makes before sending anything says nothing was started |
| `wake` | `POST /api/v1/agent/runs/<run>/followups` with `message` ("You were woken: read the ticket again and carry on"). Warp hands it to the live session, or resumes the same run in a new sandbox. A stopped run takes no wake |
| `stop` | Marks the run stopped, then `POST /api/v1/agent/runs/<run>/cancel`. If Warp refuses (for example 409 while still `PENDING`, or 404 when the current key cannot see the run, which Warp also returns for another user's or team's run), the run stays stopping: no wake, and the next `stop` sends the cancel again. Once Warp has cancelled it (or a follow-up `GET /api/v1/agent/runs/<run>` confirms a terminal state), a later `stop` answers without a call |

- **Effort.** A `start` with an `effort` Warp can't set (any effort for `claude`, or a value outside the table for `codex`) is refused before any call, with the driver v1 text `this host can't set effort: ...`; it never falls back to Warp's default. A `start` without `effort` runs at the harness's default.
- **`harness` and `model`.** `harness` is `claude` (Claude Code) or `codex` (Codex); anything else is refused before any call. `model` is that harness's model id on Warp, or `default` for the harness's own default.
- **Harness login.** Make a Warp secret for the harness (`oz secret create claude api-key <NAME>`, or `codex`), and set its name, not its value, in `OPENWIZ_WARP_CLAUDE_LOGIN` or `OPENWIZ_WARP_CODEX_LOGIN`. `start` refuses without it. The name is 1 to 100 letters, digits, `_`, `.` or `-`.
- **Environment.** Set `OPENWIZ_WARP_ENVIRONMENT` to a Warp cloud environment id to run in it (Warp recommends one that holds the repository); unset, Warp picks its default.
- **The key** is a Warp API key (Settings, Cloud platform, API keys). A 401 or 403 is an error that says so, and never shows Warp's answer.
- **State.** Runs (run id, request) are kept in `$OPENWIZ_WARP_OZ_STATE` (default `~/.local/state/openwiz-warp-oz`, owner-only). A wake or a stop holds the run's lock (`<run>.lock`).

## Tests and the kit

```sh
python3 -I adapters/warp-oz/test_driver.py      # the kit's five checks, key check included, on a synthetic Warp Oz
python3 -I kernel/driver-kit/kit.py --driver adapters/warp-oz/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model default   # the real host
```

`fixtures/fake-warp-oz` is a synthetic Warp Oz on `127.0.0.1`, built from Warp's OpenAPI document and reached through the helper's loopback test override (`OPENWIZ_HOSTKEY_TEST_ORIGIN`). It gives the helper a synthetic key at the kit's test-key path, from its own `FAKE_WARP_OZ_KEY`, which the driver never gets. It never reaches Warp, and plays each run's agent by posting and editing the builder status note in the kit's local tracker. Run as `fake-warp-oz <tracker> <log> <faults>`, it prints its origin, logs each request it gets (method, path, body and `Authorization` header) as one JSON line, scopes runs to the `Authorization` header that created them, and answers a `"<METHOD> <key|create|run|followups|cancel>"` key of the `<faults>` JSON file with that entry's `status` and `body` (or closes the connection after creating when `drop` is true). `fixtures/kit-host.json` is what the kit's own fake host answers during the key check. The kit sees only processes on its own machine: here, the driver and the helper. The run itself runs on Warp, and ends when Warp cancels it.
