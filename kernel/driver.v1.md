# OpenWiz drivers, version 1 (`openwiz:driver v1`)

A driver is how a place that runs agents (a laptop, a VPS, a cloud sandbox) plugs into OpenWiz. It is one small program, in any language, kept in OpenWiz as `adapters/<host>/driver`. It starts, wakes and stops agents there; the agents then keep their own records on GitHub under [records v1](records.v1.md). The interface is versioned: a later version adds commands or fields beside these and never changes a v1 rule's meaning.

Its schemas are [`driver-kit/schema.json`](driver-kit/schema.json). Its test kit is [`driver-kit/`](driver-kit/README.md). A copyable minimal driver is [`adapters/template/`](../adapters/template/README.md).

## 1. Commands

The driver is called as `driver <command>`. A command that takes input reads one JSON object on stdin; every command prints one JSON object on stdout.

| Command | Input | Answer |
| --- | --- | --- |
| `version` | none | `driver` (its name), `records` (the records versions it supports, such as `openwiz:records v1`) and `can` (`start`, `wake` and `stop`, plus any of `many-at-once` and `own-sandbox`) |
| `schema` | none | The whole of `schema.json`, unchanged: one JSON Schema for each command's input and answer, and one for errors |
| `start` | `repository` (`owner/name`), `ticket` (its number), `skill`, `harness`, `model` | `run`: the new run's id |
| `wake` | `run` | `run`, `woke: true` |
| `stop` | `run` | `run`, `stopped: true` |

- **D1. Exact shapes.** Every input and answer is exactly its schema: each field once, no other field. A driver refuses an input that isn't.
- **D2. Plain names.** Fields are plain words. A run id is the driver's own string (1 to 100 letters, digits, `.`, `_`, `:` or `-`), and means nothing to anyone else.
- **D3. Errors say what to do.** On any refusal or failure the driver exits 1 and prints `{"error": "<what went wrong>", "next": "<what to do next>"}`, each one line of 1 to 300 characters, so an agent can act on it without docs. Exit 0 means the answer is the command's answer. No other exit code.
- **D4. Start runs one agent on one ticket.** The agent runs `skill` with `harness` and `model` on `repository#ticket`, and keeps one status note there ([records v1, section 2](records.v1.md#2-the-status-note)). `start` answers once the run exists; the note follows.
- **D5. Wake reaches the same run.** The run's agent takes up its ticket again and edits its own status note; it posts no second one. A wake after `stop`, or for an unknown run, is an error.
- **D6. Stop ends the run.** Everything the run started on the host ends. Stopping a stopped run answers again.

## 2. Logins

OpenWiz never touches a login.

- **N1.** No input carries a login, token, key or password, and a driver refuses a field it doesn't know (D1).
- **N2.** A driver uses the host's and the harness's own signed-in tools. It never reads a credential to pass it on: not in an argument, not into another variable of an environment, not in its output. An environment the agent inherits unchanged from the person who runs the driver is theirs, not the driver's.
- **N3.** It holds no GitHub App key, and no token beyond its own run (GitHub identity G1).

## 3. The kit's five checks

A driver merges into `adapters/` when it passes all five on its real host, with the run shown on its pull request, and a review.

| Check | The kit passes it when |
| --- | --- |
| start | `start` answers a run id, and a new live builder status note from a record author, naming the skill, appears on the throwaway ticket |
| wake | `wake` answers, and that same note is edited, with no second builder note |
| stop | `stop` answers, a wake after it is refused with an error, and no process the run started on this machine still runs |
| version | `version` names the kernel's records version, and `schema` prints `schema.json` unchanged |
| token | No credential appears in the driver's output, on the command line of a process it started, or in such a process's environment under a variable the kit didn't give it; and `start` refuses a `token` field |

Every answer and error is checked against `schema.json`. The kit knows a credential by its shape (as the [status contract](https://github.com/openwizdev/WizSkills/blob/a2993f47b8fd3d7853ee45e6c21feea708c70c02/contracts/agent-status.v1.md#what-it-never-holds) lists them) or as the value of a secret in the kit's own environment. It watches the processes a driver starts on the machine it runs on; what a driver does inside a remote host is that driver's review.
