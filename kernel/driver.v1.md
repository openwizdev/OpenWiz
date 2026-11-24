# OpenWiz drivers, version 1 (`openwiz:driver v1`)

A driver is how a place that runs agents (a laptop, a VPS, a cloud sandbox) plugs into OpenWiz. It is one small program, in any language, kept in OpenWiz as `adapters/<host>/driver`. It starts, wakes and stops agents there; the agents then keep their own records on GitHub under [records v1](records.v1.md). The interface is versioned: a later version adds commands or fields beside these and never changes a v1 rule's meaning.

**Supported platforms:** each driver's README names the platforms it runs on; the kit and the local, boat.dev and template drivers run on Linux and macOS, with Python 3.9 or later.

Its schemas are [`driver-kit/schema.json`](driver-kit/schema.json). Its test kit is [`driver-kit/`](driver-kit/README.md). A copyable minimal driver is [`adapters/template/`](../adapters/template/README.md).

## 1. Commands

The driver is called as `driver <command>`. A command that takes input reads one JSON object on stdin; every command prints one JSON object on stdout.

| Command | Input | Answer |
| --- | --- | --- |
| `version` | none | `driver` (its name), `records` (the records versions it supports, such as `openwiz:records v1`) and `can` (`start`, `wake` and `stop`, plus any of `many-at-once`, `own-sandbox` and `effort`) |
| `schema` | none | The whole of `schema.json`, unchanged: one JSON Schema for each command's input and answer, and one for errors |
| `start` | `repository` (`owner/name`), `ticket` (its number), `skill`, `harness`, `model`, and optionally `effort` | `run`: the new run's id |
| `wake` | `run` | `run`, `woke: true` |
| `stop` | `run` | `run`, `stopped: true` |

- **D1. Exact shapes.** Every input and answer is exactly its schema: each field once, no other field. A driver refuses an input that isn't.
- **D2. Plain names.** Fields are plain words. A run id is the driver's own string (1 to 100 letters, digits, `.`, `_`, `:` or `-`), and means nothing to anyone else.
- **D3. Errors say what to do.** On any refusal or failure the driver exits 1 and prints `{"error": "<what went wrong>", "next": "<what to do next>"}`, each one line of 1 to 300 characters, so an agent can act on it without docs. Exit 0 means the answer is the command's answer. No other exit code.
- **D4. Start runs one agent on one ticket.** The agent runs `skill` with `harness` and `model` on `repository#ticket`, and keeps one status note there ([records v1, section 2](records.v1.md#2-the-status-note)). `start` answers once the run exists; the note follows. The `model` may be provider-qualified, as `/`-separated segments such as `kimi-code/kimi-for-coding` or `openrouter/anthropic/claude-sonnet-4.6`, up to 100 characters, as `schema.json` gives.
- **D5. Wake reaches the same run.** The run's agent takes up its ticket again and edits its own status note; it posts no second one. A wake after `stop`, or for an unknown run, is an error.
- **D6. Stop ends the run.** Everything the run started on the host ends. Stopping a stopped run answers again.

### Effort

A start can carry the effort the user set for the role, as it carries the model.

- **`effort` in `start`.** An optional `start` input field: one plain word, `^[a-z][a-z0-9-]{0,19}$`, as the user wrote it in lower case (for example `low`, `medium`, `high`, `xhigh`, `max`). The other five fields stay required as they are.
- **`effort` in `can`.** `version`'s `can` may list `effort`. A caller sends `effort` only to a driver whose `can` lists it. A driver that doesn't list it is never sent the field, and still refuses it under D1, exactly as today.
- **`version`'s answer is unchanged except for that `can` entry.** It carries no effort note: every answer matches its schema exactly (D1). A driver says it can't set effort in exactly three ways:
  - `effort` is absent from its `can` list;
  - a plain `Effort:` line in its README;
  - the D3 refusal below.
- **The refusal text.** A driver that can't set the effort it was sent, for the start's harness, refuses (D3) with `next` exactly: `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. Its `error` names the harness and the effort word.
- **E1. Passed or refused.** A driver whose `can` lists `effort` runs the host at exactly the start's effort, for every harness and value its README lists as passed. Its README names the exact flag or setting. For any other harness or value, it refuses with the refusal text above and starts nothing. It never substitutes a nearby value and never falls back to a default.
- **E2. No effort, host default.** A `start` without `effort` runs at the host's default effort. That is the case where the user set none.
- **E3. It says so.** Right under its login line ([section 2](#the-login-line)), every driver's README has one `Effort:` line: `Effort: passed as <flag or setting>` or `Effort: the host can't set it (<why>)`. When it differs by harness, a short table of harness, flag or `can't (<why>)` follows. A driver that can't set effort for any harness leaves `effort` out of `can`. It is never sent the field, and refuses it under D1 as today.
- **E4. Callers never drop it.** When the user set an effort for a role, a caller sends it only to a driver whose `can` lists `effort`. Through any other driver, it starts nothing. A refusal with the refusal text above also starts nothing. A caller never retries without the effort.

## 2. Logins

OpenWiz never touches a login.

- **N1.** No input carries a login, token, key or password, and a driver refuses a field it doesn't know (D1).
- **N2.** A driver uses the host's and the harness's own signed-in tools. It never reads a credential to pass it on: not in an argument, not into another variable of an environment, not in its output. An environment the agent inherits unchanged from the person who runs the driver is theirs, not the driver's.
- **N3.** It holds no GitHub App key, and no token beyond its own run (GitHub identity G1).
- **N4.** A host that can be driven only through an API that takes the user's key is reached only through the kit's key helper, `kernel/driver-kit/hostkey.py`. The helper alone reads the key, from the user's system keychain or from the environment variable the user set, and sends it only over HTTPS to the address registered for that host in `kernel/driver-kit/hosts.json`. The driver never names, reads, receives or prints the key, and never chooses the address. OpenWiz never stores a key.

### The login line

Each driver's `README.md` opens, right under its title, with one line saying where the user's login lives. It is exactly one of two forms:

- `Login: stays on your machine`: a local driver. The host's own signed-in tools run on the user's machine, and the login never leaves it.
- `Login: held by <host>`: a cloud driver, where `<host>` is the host's name. The user signs in to the host, and the host holds that login. When the host takes an API key, the README also names the environment variable the user may set for it and the keychain entry the helper reads (N4).

The line only says where the login lives; N1 to N3 apply to every driver unchanged.

## 3. The kit's five checks

A driver merges into `adapters/` when it passes all five on its real host, with the run shown on its pull request, and a review.

| Check | The kit passes it when |
| --- | --- |
| start | `start` answers a run id, and a new live builder status note from a record author, naming the skill, appears on the throwaway ticket |
| wake | `wake` answers, and that same note is edited, with no second builder note |
| stop | `stop` answers, a wake after it is refused with an error, and no process the run started on this machine still runs |
| version | `version` names the kernel's records version, and `schema` prints `schema.json` unchanged |
| token | No credential appears in the driver's output, on the command line of a process it started, or in such a process's environment under a variable the kit didn't give it; and `start` refuses a `token` field |

The `start` check also covers effort:

- **A driver whose `can` lists `effort`:** the kit's start carries `effort` (`--effort <v>`, default `medium`). The effort part of `start` passes on either of two outcomes. Host receipt: that value reaches the host, in the command line or environment of a process the run started or, for a key-host driver, in the request log of its loopback fake host. Or the documented refusal: that start is refused with `next` exactly `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`, with no run, and the README's `Effort:` line or table says that harness can't.
- **A driver without `effort` in `can`:** a start with `effort` must be refused (D1) with no run, and its README must have the `Effort:` line saying the host can't set it.

Every answer and error is checked against `schema.json`. The kit knows a credential by its shape (as the [status contract](https://github.com/openwizdev/WizSkills/blob/a2993f47b8fd3d7853ee45e6c21feea708c70c02/contracts/agent-status.v1.md#what-it-never-holds) lists them) or as the value of a secret in the kit's own environment. It watches the processes a driver starts on the machine it runs on; what a driver does inside a remote host is that driver's review.
