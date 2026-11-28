# Factory driver

Login: held by Factory

Effort: passed as `--reasoning-effort <level>` to `droid exec`, on the start's turn and every wake's, for each level `droid exec --help` lists as supported for the start's model. Any other harness, model or level is refused with driver v1's refusal text before anything is saved or started; a start without an effort runs at Droid's default.

A [driver v1](../../kernel/driver.v1.md) that runs each builder as [Factory](https://factory.ai)'s Droid, through your own signed-in `droid` CLI in headless mode (`droid exec`). Built from [`adapters/template/`](../template/README.md): one Python file, standard library only. **Platforms:** Linux only, Python 3.9 or later (it keeps each turn's processes with `/proc` and a subreaper; it does not run on macOS). Runs are saved in `$OPENWIZ_FACTORY_STATE` (default `~/.local/state/openwiz-factory`; a relative path is taken from where the driver runs). Every file and folder there is owner-only, and `start` and `wake` refuse a state folder that isn't yours alone (`chmod 700` it, or pick a new one). When the folder or a run's saved files are links or aren't yours alone, nothing saved there is trusted, so nobody else can point the driver at processes it never started: `wake` and `stop` both refuse and end nothing, and the error names the folder. Each turn's supervisor runs apart from the `driver stop` that comes later, so the driver has no other proof of which processes are the run's; end them by hand.

| Command | What it does |
| --- | --- |
| `start` | Makes the run's own empty workspace, `$OPENWIZ_FACTORY_STATE/work/<run>`, and runs `droid exec --cwd <workspace> -m <model> [--reasoning-effort <level>] --auto medium -o json "<prompt>"`: a new Droid session on the ticket and skill. A start with `effort` first reads `droid exec --help` and passes `--reasoning-effort` only when Droid lists that level as supported for the model; otherwise it refuses with driver v1's refusal text before anything is saved or started. If `droid exec --help` cannot be read, it refuses in its own words, also before anything starts. It answers once the turn has started. |
| `wake` | While the last turn's `droid exec` still runs, nothing: that agent is awake and reads the ticket itself. Otherwise `droid exec ... -s <session_id> "<prompt>"`, repeating `--reasoning-effort` when the start carried one, with the `session_id` from the first turn's JSON result: the same Droid session, with its memory, edits its own status note. A run whose first turn ended before a session began (Droid not signed in, say) is refused, never woken as a new session. |
| `stop` | Ends every local process the turns started. Each `droid exec` ends after its turn, and Factory keeps no run of its own to stop. |

Each turn runs under its own supervisor (`driver --turn`), so `stop` reaches every process the turn started, whatever its session or environment. The driver keeps nothing Droid prints: it reads only the `session_id` from the turn's JSON result and saves just that, owner-only, as `<run>.<turn>.session`. Droid's other output and its errors are dropped. A wake and a stop on one run take turns under its lock; the driver saves a run before it starts anything for it, and a turn it could not save is ended, with an error that says the outcome is unknown.

- **`harness`:** on Factory the agent is always Droid, so `harness` must be `droid`; any other is refused before anything runs. `model` is passed to `-m` unchanged: any [Factory model ID](https://docs.factory.com/cli/droid-exec/overview), or a custom model you set up in Factory yourself.
- **Effort:** [Droid Exec](https://docs.factory.com/droid-exec/overview) takes `-r, --reasoning-effort <level>` (`-r` on `droid exec` is that flag; in the interactive CLI `-r` is `--resume`, so the driver sends only the long flag). Valid levels depend on the model ([Available Models](https://docs.factory.com/models), [Settings](https://docs.factory.com/droid-cli/settings)), and `droid exec --help` prints each built-in model's supported values under `Available Models:` and `Model details:`. Before saving or starting a run that carries `effort`, the driver reads `droid exec --help` and passes `--reasoning-effort <level>` only when the start's model is listed there with `supports reasoning: Yes` and `<level>` in its `supported` list. A model whose `Model details:` line says `supports reasoning: No` (such as `auto`), an unlisted model, a `custom:` model (Droid Exec says the flag does not apply to custom models), an unsupported level for the model, or any harness other than `droid` is refused before anything is saved or started, with `next` exactly `this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`. If `droid` is missing or `droid exec --help` fails or cannot be parsed, the driver refuses in its own words (never repeating Droid's output) and starts nothing. A start with no effort does not run `droid exec --help` and passes no flag, so Droid uses the model's own default, including for `custom:` models and `auto`. A wake repeats the start's flag.
- **Autonomy:** `--auto medium`, so Droid can edit, build, test, commit, push and open pull requests, never force-push or use sudo. The driver never uses `--skip-permissions-unsafe`.
- **Login:** the driver never reads, passes or prints a login (driver v1, N1 to N3). `droid` uses your own Factory sign-in, and `gh` and `git` in the turn use yours; each turn inherits your environment unchanged; the driver builds no copy of it and adds nothing.
- **Workspace:** each run's workspace stays after `stop`, in case it holds unpushed work; delete it when you are done.

## Before the first run (yours to do)

1. Install Factory's `droid` CLI and sign in to Factory yourself, as its docs say. For headless `droid exec`, Factory's docs have you set your Factory API key as `FACTORY_API_KEY` in your own environment. Each turn inherits it unchanged; the driver never reads, copies or prints it.
2. Sign in to `gh` so the agent can read and comment on the ticket and push its branch.
3. Make the skills your fleet runs available to Droid.

Factory bills each turn against your Factory plan.

## The kit

```sh
python3 -I kernel/driver-kit/kit.py --driver adapters/factory/driver \
  --repo <owner>/<throwaway> --ticket <n> --harness droid --model <model>
python3 -I adapters/factory/test_driver.py      # the fixture tests, on a synthetic droid CLI
```

`fixtures/bin/droid` is a synthetic `droid` CLI, shaped on Factory's `droid exec` docs and `droid 1.21.1`: `exec --help` prints `fixtures/exec-help.txt` (or `fixtures/exec-help-1.21.1.txt`, recorded from `droid 1.21.1`), `exec` enforces each model's supported reasoning levels, `-o json` prints one result line with a `session_id`, and `-s <id>` continues that session. It never reaches Factory. `evidence/red.txt` is the kit failing against the copied template; `evidence/green.txt` is the same tests passing.
