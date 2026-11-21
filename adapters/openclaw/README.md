# OpenClaw driver

Login: stays on your machine

A [driver v1](../../kernel/driver.v1.md) that runs builders on this machine through [`acpx`](https://github.com/openclaw/acpx), OpenClaw's own headless command-line client for the Agent Client Protocol (MIT). It never uses the OpenClaw gateway: the gateway refuses remote agent starts by default, and this driver never asks you to loosen that. One Python file, standard library only, built on [`adapters/template/`](../template/README.md). **Platforms:** Linux only (kernel 5.3 or later), Python 3.9 or later: it keeps each acpx call's processes with a child subreaper, `/proc` and process file descriptors, so it does not run on macOS. Runs are saved in `$OPENWIZ_OPENCLAW_STATE` (default `~/.local/state/openwiz-openclaw`), owner-only.

| Command | What it does with `acpx` |
| --- | --- |
| `start` | Makes the run's own empty folder, `work/<run>` in the state folder, and opens one named session there: `acpx --cwd <folder> --agent <adapter> --model <model> --auth-policy fail --permission-policy <policy> --non-interactive-permissions deny sessions new --name <run>`. Then it queues the first prompt, the ticket and skill, with `acpx ... --ttl 60 prompt -s <run> --no-wait <prompt>`, and answers only once acpx has acknowledged it (exit 0); acpx's queue owner then runs the turn. If the session can't be opened (a missing sign-in, say) or acpx refuses the prompt, the driver ends what it started and refuses. |
| `wake` | Queues one follow-up prompt in the same session, and answers only once acpx has acknowledged it. acpx runs a session's prompts one after another, so a wake during a turn runs after it, in the same agent, with its memory, which edits its own status note: never a second agent. A stopped run is never woken, and a refused follow-up is an error. |
| `stop` | `acpx ... cancel -s <run>`, then `acpx ... sessions close <run>`, then it ends every process the run's acpx calls started, acpx's queue owner included, so nothing is left. Stopping again answers again. The run's folder stays, in case it holds unpushed work; delete it when you are done. |

Every call names the harness's adapter itself, as `--agent 'env HOME=<your home> <adapter>'`, where `<adapter>` is acpx 0.22.0's own built-in command for that harness (`AGENTS` in `driver`), and runs acpx with `HOME` set to the driver's own `home` folder in the state folder. So acpx never loads your `~/.acpx/config.json`: no `agents` entry there can swap the adapter, and no `auth` value there reaches the agent. The driver never opens that file either. `env` gives the adapter your own `HOME` back, so it finds your own harness sign-in. A `.acpxrc.json` in the run's folder can't swap the adapter either, since `--agent` wins over any configured agent.

Each acpx call runs under its own supervisor (`driver --turn`, a Linux child subreaper, as in the template), so `stop` reaches every process the call started, whatever its session or environment. acpx's output is never kept: it goes nowhere, and an error gives only acpx's exit code. A wake and a stop hold the run's lock throughout. The driver saves a run before it starts anything for it, and if a save fails after a prompt began, it ends that prompt and says the outcome is unknown, never to retry.

## What the driver refuses

- A `harness` outside the list below, without repeating the value.
- Any field shaped like a login or token (a `token=` or `Bearer` value, or a known key shape such as `ghp_…` or `sk-…`), before it saves or starts anything.

## Permissions

Unattended tool use goes through a permission policy, never `--approve-all`. The policy approves the tool kinds a builder needs (`read`, `search`, `edit`, `move`, `execute`, `think`, `fetch`), denies `delete` and `switch_mode`, and denies anything else; with `--non-interactive-permissions deny` acpx never waits on a question nobody can answer. Approving `execute` lets the agent run commands in its folder, as a builder must (git, tests); read the policy in `driver` (`POLICY`) before your first run.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N3): it adds no key, token or password to any call, and every acpx call inherits your environment, plus `OPENWIZ_RUN`, with `HOME` set to the driver's own folder for acpx and set back to yours for the adapter. With `--auth-policy fail`, a harness that isn't signed in fails the start instead of prompting.

1. Install Node.js 22.13 or later and `acpx` (`npm install -g acpx`).
2. Sign in to the harness yourself, on this machine: `claude` or `codex` as usual. acpx starts that harness's ACP adapter, which uses your own sign-in.
3. Sign in to `gh` yourself, and install the skills your agents use, as for any local builder.
4. `harness` is `claude`, `codex`, `droid` or `opencode`, run with acpx 0.22.0's built-in adapter for it (`npx` fetches the Claude, Codex and OpenCode adapters). Any other name is refused: the driver names each adapter itself, its `openclaw` agent goes through the gateway, and acpx tunes `gemini`, `copilot` and `cursor` by their command's name, which the `env` wrapper hides. `model` is passed to `--model` unchanged.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/openclaw/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
python3 -I adapters/openclaw/test_driver.py   # the fixture tests, on a synthetic acpx
```

`fixtures/bin/acpx` is a synthetic `acpx`. Its command shapes follow `acpx --help` of acpx 0.22.0, and it resolves the agent as acpx 0.22.0 does (`--agent`, then an `agents` entry in `~/.acpx/config.json` or `.acpxrc.json`, then the built-in), logging which command and which `auth` names each call would have used, and like acpx 0.22.0's `--no-wait`, a prompt hands its turn to a separate queue owner and exits once queued (its own source, `sendSession`). Every call prints a synthetic diagnostic, so the tests can show none is kept. The tests find their processes by ancestry, as a child subreaper, never by reading another process's environment; and `evidence/acpx-shapes.txt` shows the real acpx 0.22.0 running each call the driver makes, with a stand-in agent. The tests run with a `PATH` that holds only the fake, `python3` and `sleep`, so no real harness or acpx ever runs. `schema.json` is byte for byte the kit's `kernel/driver-kit/schema.json`.
