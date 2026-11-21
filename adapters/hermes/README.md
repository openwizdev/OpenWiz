# Hermes driver

Login: stays on your machine

A [driver v1](../../kernel/driver.v1.md) that runs each builder in [Hermes](https://hermes-agent.nousresearch.com) (Nous Research's `hermes-agent`) on this machine, through your own `hermes` CLI. One Python file, standard library only. **Platforms:** Linux only, Python 3.9 or later (it keeps each turn's processes with `/proc` and a subreaper; it does not run on macOS yet). Built from [`adapters/template/`](../template/README.md). Runs are saved in `$OPENWIZ_HERMES_STATE` (default `~/.local/state/openwiz-hermes`), owner-only.

| Command | What it does in Hermes |
| --- | --- |
| `start` | `hermes chat --oneshot --format stream-json --source tool` with the ticket and skill as its query, under the driver's own supervisor. It answers once Hermes' first `system` `init` line names the session, and saves that `session_id` with the run. The supervisor reads Hermes' output only for that id and discards the rest: no transcript is written to disk. If no session is reported within 60 seconds, or the turn ends without one, it ends the turn and refuses. |
| `wake` | The same command with `--resume <session_id>`: the same Hermes session and transcript, so the agent edits its own status note. If the last turn still runs, the wake is saved and its supervisor runs that resumed turn as soon as the last one ends, so a wake is never dropped (several wakes during one turn give one resumed turn). A wake after `stop` is refused. |
| `stop` | Sends the turn's processes SIGINT, Hermes' Ctrl-C, so the turn is interrupted and settles cancelled (its `result` ends `exit_code: 130`). Whatever still runs after 10 seconds it ends with SIGTERM and then SIGKILL, every process the run's turns started, through the template's supervisor. |

The driver uses Hermes' CLI, not its API server. The API server needs `API_SERVER_KEY` on every request, and a driver never reads a credential (driver v1, N2). The choice is recorded on #1988.

## How `harness` and `model` map

Hermes is its own agent. It reaches Claude Code and Codex only through its bundled skills, which shell out to those CLIs.

| `harness` | What the driver passes |
| --- | --- |
| `claude` | `-s claude-code`, and the query asks Hermes to run the `claude` CLI with `model` and have it run `skill` |
| `codex` | `-s codex`, and the query asks Hermes to run the `codex` CLI with `model` and have it run `skill` |
| `hermes` | `-m <model>`: Hermes itself is the agent, on that model |

Any other `harness` is refused. What this can't control:

- For `claude` and `codex`, `model` and `skill` reach the inner CLI only as words in Hermes' prompt. Hermes runs on its own configured model, and the inner CLI's flags, effort and permissions are whatever Hermes' skill chooses.
- `stop` interrupts and ends what runs on this machine under the turn. If your Hermes setup hands a turn to its gateway or to a remote terminal backend, ending it there is Hermes' job, and the live check shows whether it does.
- The driver adds no `--yolo`. Hermes' own approval settings decide whether the agent may run commands without asking, and a turn with no terminal can't answer a prompt.

## Before the first run (yours to do)

The driver never touches a login (driver v1, N1 to N3). It never reads `~/.hermes`, and passes no key, token or password anywhere. Hermes gets only these names from your environment: `HOME`, `USER`, `LOGNAME`, `SHELL`, `PATH`, `LANG`, `LANGUAGE`, the locale settings by their exact names (`LC_ALL`, `LC_CTYPE`, `LC_COLLATE`, `LC_MESSAGES`, `LC_MONETARY`, `LC_NUMERIC`, `LC_TIME`, `LC_ADDRESS`, `LC_IDENTIFICATION`, `LC_MEASUREMENT`, `LC_NAME`, `LC_PAPER`, `LC_TELEPHONE`; any other `LC_` name stays behind), `TZ`, `TERM`, `TMPDIR`, `HERMES_HOME`, the `XDG_*` folders, `SSH_AUTH_SOCK` (the path of your SSH agent's socket, so `git push` over SSH works; no key is in it) and the kit's `OPENWIZ_KIT_RUN` mark, plus the driver's `OPENWIZ_RUN`. Anything else you have exported, such as a token, stays behind: Hermes, `gh`, `git`, `claude` and `codex` use their own signed-in configuration.

1. Install Hermes and set up its model and provider yourself (`hermes setup`).
2. For `claude` or `codex`, install and sign in to that CLI yourself, and enable Hermes' bundled `claude-code` or `codex` skill.
3. Sign in to `gh` yourself, so the agent can post its status note.

## The kit

Check a checkout with the fixture tests. They run the kit's five checks on the synthetic `hermes` in `fixtures/bin/` and a local tracker, with PATH limited to that folder, `/usr/bin` and `/bin`, so no real Hermes, Claude Code or Codex is reached and nothing is spent:

```sh
python3 -I adapters/hermes/test_driver.py
```

**The live check is a separate step, for a person only.** It runs the kit against the `hermes` on your PATH: real model turns that cost money and post on a real throwaway ticket. Run it only on purpose, on a throwaway repository and ticket you made for it (see [the kit's README](../../kernel/driver-kit/README.md)):

```text
python3 -I kernel/driver-kit/kit.py --driver adapters/hermes/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness claude --model <model>
```

`fixtures/bin/hermes` is a synthetic `hermes` CLI. Its arguments and JSON lines follow Hermes' CLI reference. They were not observed on a live install. `evidence/red*.txt` are the failing-first runs and `evidence/green.txt` is the passing run.
