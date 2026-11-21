# Factory driver

Login: held by Factory

A [driver v1](../../kernel/driver.v1.md) that runs each builder as [Factory](https://factory.ai)'s Droid, through your own signed-in `droid` CLI in headless mode (`droid exec`). Built from [`adapters/template/`](../template/README.md): one Python file, standard library only. **Platforms:** Linux only, Python 3.9 or later (it keeps each turn's processes with `/proc` and a subreaper; it does not run on macOS). Runs are saved in `$OPENWIZ_FACTORY_STATE` (default `~/.local/state/openwiz-factory`; a relative path is taken from where the driver runs). Every file and folder there is owner-only, and `start` and `wake` refuse a state folder that isn't yours alone (`chmod 700` it, or pick a new one). When the folder or a run's saved files are links or aren't yours alone, nothing saved there is trusted, so nobody else can point the driver at processes it never started: `wake` refuses, and `stop` ends only the run's own turn supervisors, found by their command line among your own processes, with everything under them. If it finds none, or can't end them, it exits 1 and names the folder; end the run's processes by hand.

| Command | What it does |
| --- | --- |
| `start` | Makes the run's own empty workspace, `$OPENWIZ_FACTORY_STATE/work/<run>`, and runs `droid exec --cwd <workspace> -m <model> --auto medium -o json "<prompt>"`: a new Droid session on the ticket and skill. It answers once the turn has started. |
| `wake` | While the last turn's `droid exec` still runs, nothing: that agent is awake and reads the ticket itself. Otherwise `droid exec ... -s <session_id> "<prompt>"`, with the `session_id` from the first turn's JSON result: the same Droid session, with its memory, edits its own status note. A run whose first turn ended before a session began (Droid not signed in, say) is refused, never woken as a new session. |
| `stop` | Ends every local process the turns started. Each `droid exec` ends after its turn, and Factory keeps no run of its own to stop. |

Each turn runs under its own supervisor (`driver --turn`), so `stop` reaches every process the turn started, whatever its session or environment. The driver keeps nothing Droid prints: it reads only the `session_id` from the turn's JSON result and saves just that, owner-only, as `<run>.<turn>.session`. Droid's other output and its errors are dropped. A wake and a stop on one run take turns under its lock; the driver saves a run before it starts anything for it, and a turn it could not save is ended, with an error that says the outcome is unknown.

- **`harness`:** on Factory the agent is always Droid, so `harness` must be `droid`; any other is refused before anything runs. `model` is passed to `-m` unchanged: any [Factory model ID](https://docs.factory.com/cli/droid-exec/overview), or a custom model you set up in Factory yourself.
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

`fixtures/bin/droid` is a synthetic `droid` CLI, shaped on Factory's `droid exec` docs: `-o json` prints one result line with a `session_id`, and `-s <id>` continues that session. It never reaches Factory. `evidence/red.txt` is the kit failing against the copied template; `evidence/green.txt` is the same tests passing.
