# Driver template

Login: stays on your machine

The smallest [driver v1](../../kernel/driver.v1.md): one Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later. It passes the [kit](../../kernel/driver-kit/README.md). Each turn of a run is a local process: `start` runs the first turn, `wake` runs another once the last one has ended, and `stop` ends every process the run's turns started. Runs are saved in `$OPENWIZ_TEMPLATE_STATE` (default `~/.local/state/openwiz-template`), each one before its first turn starts.

## Make your own in an hour

1. Copy this folder to `adapters/<host>/`. Rename `template` in `VERSION`, and the state folder's name.
2. **`command`**: the command line your harness runs a turn with, using its own signed-in login. It must never add a login or a token. The template calls the program named by `harness` with `--model` and `-p`; map your harness names here.
3. **`launch`, `running` and `end`**: how your host starts a turn, tells whether it still runs, and ends the run. For a remote host, call its own signed-in tool here, and return what `running` and `end` need. Keep the four rules they hold:
   - **`stop` ends everything.** Each turn runs under its own supervisor (`driver --turn`), a Linux child subreaper, so every process the turn starts stays under it, whatever session or environment it moves to. macOS has no subreaper: there the supervisor leads its own session and process group, looks at `ps`'s process table (pid, parent, group, state and start time, never an environment) every 0.2 seconds, and records in the run's state folder every process in its group or under it, by pid and start time. The harness writes to the turn's own output file in the state folder, which every process it starts inherits; about once a second, and before the supervisor exits, `lsof` names the processes holding that file open for writing, and the supervisor records them too. `end` signals all of those, and every process under them. A process that leaves the group, closes or redirects its output (as a daemon does), and is orphaned between two looks is out of reach on macOS. `end` signals all of them, even after the harness itself has exited, and answers only once every supervisor has exited, which it does when none of its processes is left. It ends them even when it can't save that the run is stopped, and then says so.
   - **One agent at a time.** A `wake` or a `stop` holds the run's lock from reading the run to saving it, and `wake` starts no turn while the last one runs: that agent is awake and reads the ticket itself.
   - **No run, no agent.** `start` and `wake` each save before they launch anything. A run is not wakeable until its first turn is saved. If a save fails after a launch, the driver ends that turn and says the outcome is unknown, never "retry".
4. Add `many-at-once` or `own-sandbox` to `can` only when your host does that.
5. Run the kit against it on a throwaway ticket, on its real host, and put the output on the pull request.

Keep `schema.json` byte for byte the kit's `kernel/driver-kit/schema.json`: the kit checks it.

Its own tests: `python3 -I adapters/template/test_driver.py`.

```sh
echo '{"repository":"example/site","ticket":7,"skill":"build-ticket","harness":"claude","model":"opus"}' \
  | adapters/template/driver start          # {"run": "run-0123456789ab"}
adapters/template/driver schema             # every command's JSON Schema
```
