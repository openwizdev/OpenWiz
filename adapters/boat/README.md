# boat.dev driver

A [driver v1](../../kernel/driver.v1.md) that runs each builder in its own [boat.dev](https://boat.dev) cloud sandbox, through your own signed-in `boat` CLI. One Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later (on Linux it keeps each turn's processes with `/proc` and a subreaper; on macOS with each turn's process group and `ps`). Runs are saved in `$OPENWIZ_BOAT_STATE` (default `~/.local/state/openwiz-boat`), owner-only.

| Command | What it does on boat.dev |
| --- | --- |
| `start` | `boat new --name openwiz-<run>`. Then one `boat exec` installs the WizSkills release OpenWiz pins (`wizskills.lock`) in the sandbox. It fetches only that tag, once, into a local repository, and checks its commit and tree against the lock. It takes that commit's own `install.sh` by its full sha and runs it with the release URL pointed at the local repository, so nothing more is fetched. It checks that the installed release is exactly the pinned commit and tree, and links each skill into `~/.claude/skills/` and `~/.agents/skills/` without replacing any existing entry. Then `boat prompt <sandbox> --new --provider <harness> --model <model>` with the ticket and skill. It answers once boat has queued the agent's turn. If the install or the prompt fails, it stops the new sandbox before refusing. |
| `wake` | While the last turn's `boat prompt` still runs, nothing: that agent is awake and reads the ticket itself. Otherwise, only while `boat info` shows the sandbox running, `boat prompt <sandbox> --resume <conversation>`: the same agent, with its memory, edits its own status note. A stopped sandbox is never resumed: after a stop, or after boat's auto-stop (an hour without a running prompt), the run stays stopped and needs a new `start`. |
| `stop` | Ends every local process the turns started, `boat interrupt`s the agent and `boat stop`s the sandbox. The disk stays for at least 14 days at no compute cost; `boat delete <sandbox>` removes it for good. |

Each turn is a local `boat prompt` under its own supervisor (a subreaper), so the driver can answer at once, and `stop` reaches every process the turn started, whatever its session or environment. The turn's output goes to an owner-only log beside the run's state, deleted on `stop`.

**Never two agents, never one left running.** A wake and a stop hold the run's lock throughout, so they take turns. The driver saves a run before it starts anything for it. A run stays `starting` until its first turn is saved: a wake refuses it, and a stop still reaches its sandbox. If a save fails after a turn began, the driver ends that turn (and, for a start, stops the sandbox) and says the outcome is unknown, never to do it again. A stop that can't save still ends everything, then says so. It first marks the run as stopping on the run's existing lock file, both by its content and by its mtime, which its owner can set even when the file can't be written. Neither needs a new file in the folder. Until a stop succeeds, a wake refuses a run with either mark, or with no lock file, even once the folder can be written again. When no mark can be written at all (a read-only filesystem), the wake still refuses, because boat shows the sandbox stopped. Every stop of a sandbox runs `boat stop`, whatever local signalling, `boat info` or the state save did, and each failure is reported. If boat can't confirm the sandbox stopped, the answer says so and names the `boat stop` command to run. After an error the driver didn't expect, a start ends its turn and stops the sandbox, and a wake ends its new turn and interrupts its conversation, before the driver answers with the error.

`version` adds `many-at-once` and `own-sandbox` to `can`: every run gets its own sandbox, and a boat plan runs many at once.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N3): it calls `boat` with your environment unchanged, and passes no key, token or password anywhere.

1. Install the `boat` CLI (`curl -fsSL https://boat.dev/install | sh`) and sign in to it yourself.
2. In boat's dashboard, connect GitHub (so the agent's `gh` and `git push` work in the sandbox, as your agents' account) and the key or subscription for each harness you use (Agents & Proxying).
3. `harness` is one of boat's providers: `claude`, `codex`, `pi`, `opencode`, `prime`, `kimi` or `mistral`. `model` is passed to `--model` unchanged.

boat bills per second while a sandbox runs, against your plan.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/boat/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
python3 -I adapters/boat/test_driver.py      # the fixture tests, on a synthetic boat CLI
```

`fixtures/bin/boat` is a synthetic `boat` CLI. Its JSON Lines follow boat's CLI reference and the owner's live kit run (boat CLI 1.0.103): `boat prompt --json` nests the conversation id under `data` (`{"data": {"conversationId": ...}, "event": "queued"}`), and `boat info --json` carries a top-level `state`. The live runs are in `evidence/live-*.txt`.
