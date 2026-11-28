# Driver template

Login: stays on your machine
Effort: passed as each harness's own flag, for the harnesses and levels in the table below; any other harness or level is refused

| Harness | Effort |
| --- | --- |
| `fake-harness` | `--effort <level>`, for low, medium, high, xhigh and max |
| `pi` | can't (pi sets its level with `--thinking`, not `--effort`, and the template maps no flag for it) |
| any other harness | can't (the template has checked no other harness's own `--help`) |

The smallest [driver v1](../../kernel/driver.v1.md): one Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later. It passes the [kit](../../kernel/driver-kit/README.md). Each turn of a run is a local process: `start` runs the first turn, `wake` runs another once the last one has ended, and `stop` ends every process the run's turns started (on macOS, every one it can find: see `stop` below). Runs are saved in `$OPENWIZ_TEMPLATE_STATE` (default `~/.local/state/openwiz-template`), each one before its first turn starts.

## Make your own in an hour

1. Copy this folder to `adapters/<host>/`. Rename `template` in `VERSION`, and the state folder's name.
2. **`command`**: the command line your harness runs a turn with, using its own signed-in login. It must never add a login or a token. The template calls the program named by `harness` with `--model`, its effort flag from `EFFORTS` (when the start carries an effort) and `-p`; map your harness names here. The template's `command` refuses to start any harness unless `OPENWIZ_TEMPLATE_LIVE=1` is set, which only a live check sets on purpose, and while a driver still holds that `command` (or any older template's launch line) the kit runs it only with a `--harness` from the kit's or this folder's `fixtures/`, behind no-op stubs for agent CLIs such as `claude` and `codex` first on its `PATH`: an unedited copy never starts a real harness.
3. **Effort** ([driver v1, Effort](../../kernel/driver.v1.md#effort)): the template lists `effort` in `can`, and `EFFORTS` declares each harness it passes effort to, with that harness's own flag and the levels it takes. It ships one row, its own test harness `fake-harness`, passed as `--effort <level>`. A start whose harness has no row, or whose level isn't in that row, is refused with `CANT_SET_EFFORT`, the contract's exact `next`, before anything is saved or started: so `pi`, which takes `--thinking` rather than `--effort`, is refused, never sent a flag it ignores. A start without `effort` passes none, so the harness runs at its own default. Add a row only for a harness whose own `--help` you have checked, with its exact flag and levels, never a nearby value, and keep the table above to exactly the rows in `EFFORTS`, with `can't (<why>)` for the rest.
   - **When your host can't set effort for any harness**, switch to the can't form: drop `effort` from `can` in `VERSION` (the driver then refuses the field as input, D1, exactly as for any unknown field), and replace the line under `Login:` and its table with `Effort: the host can't set it (<why>)`.
4. **`launch`, `running` and `end`**: how your host starts a turn, tells whether it still runs, and ends the run. For a remote host, call its own signed-in tool here, and return what `running` and `end` need. Keep the three rules they hold:
   - **`stop` ends everything it keeps.** Each turn runs under its own supervisor (`driver --turn`), a Linux child subreaper, so every process the turn starts stays under it, whatever session or environment it moves to. macOS has no subreaper: there the supervisor leads its own session and process group, looks at `ps`'s process table (pid, parent, group, state and start time, never an environment) every 0.2 seconds, and records in the run's state folder every process in its group or under it, by pid and start time. The harness writes to the turn's own output file in the state folder, which every process it starts inherits; about once a second, and before the supervisor exits, `lsof` names the processes holding that file open for writing, and the supervisor records them too. `end` signals all of those, and every process under them. A process that leaves the group, closes or redirects its output (as a daemon does), and is orphaned between two looks is out of reach on macOS. If `lsof` can't run, or fails other than by finding nothing, macOS uses only the turn groups and the recorded processes: a detached worker that was never recorded can survive, even while it holds the output open, and `stop` says on stderr that it could not check the run's output file. `end` signals all of them, even after the harness itself has exited, and answers only once every supervisor has exited, which it does when none of its processes is left. It ends them even when it can't save that the run is stopped, and then says so.
   - **One agent at a time.** A `wake` or a `stop` holds the run's lock from reading the run to saving it, and `wake` starts no turn while the last one runs: that agent is awake and reads the ticket itself.
   - **No run, no agent.** `start` and `wake` each save before they launch anything. A run is not wakeable until its first turn is saved. If a save fails after a launch, the driver ends that turn and says the outcome is unknown, never "retry".
5. Add `many-at-once` or `own-sandbox` to `can` only when your host does that.
6. Run the kit against it on a throwaway ticket, on its real host, and put the output on the pull request.

A new driver touches no shared file: CI runs every `test_*.py` in its folder, and fails without a `test_driver.py`. Add `release.json` only if the driver should ship: exactly `{"extra_files": [...]}`, naming any tracked regular files it ships beyond `driver` and `schema.json` (else `[]`).

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests: `python3 -I adapters/template/test_driver.py`. They run with `PATH` set to `fixtures/` and a folder of only the few system tools they use, never your own `PATH`, and stop with an error if a harness name such as `claude` or `codex` resolves anywhere outside `fixtures/`, even elsewhere in the repository: a real harness on your machine is never launched by a test. Keep that in the tests of a driver you copy from here, for every driver and kit run they make.

```sh
echo '{"repository":"example/site","ticket":7,"skill":"build-ticket","harness":"claude","model":"opus"}' \
  | adapters/template/driver start          # {"error": "the template starts no harness unless OPENWIZ_TEMPLATE_LIVE=1 is set", "next": "write your own command for your harness, or set OPENWIZ_TEMPLATE_LIVE=1 on purpose for a live check"}
adapters/template/driver schema             # every command's JSON Schema
```
