# The ssh driver

Login: stays on your machine
Effort: the host can't set it (the remote program's arguments are the operator's OPENWIZ_SSH_ARGS template; this driver adds no effort flag)

A [driver v1](../../kernel/driver.v1.md) that runs one harness CLI on a VPS over `ssh`. One Python file, standard library only. **Platforms:** Linux and macOS, Python 3.9 or later.

Set `OPENWIZ_SSH_TARGET` to `user@host`. The remote command runs `env OPENWIZ_SSH_RUN=<run> <harness> <arguments>` after sending a per-turn remote-start acknowledgment. The driver does not start a local shell: it runs `ssh` with one quoted argument after `--`, so the login shell `sshd` uses keeps each argument whole. `BatchMode` is set, agent forwarding is cleared, and no PTY is requested. `start` saves the destination with the run and `wake` and `stop` keep using it even if `OPENWIZ_SSH_TARGET` changes later. Both `start` and `wake` wait for the remote-start acknowledgment and return a sanitized error when `ssh` exits early or times out. The default arguments are `--model`, the model, `-p` and the brief. Set `OPENWIZ_SSH_ARGS` to a JSON array to run another CLI. `{prompt}`, `{model}` and `{session}` each fill one whole argument, and `{prompt}` is required once.

A value of an environment variable whose name contains `KEY`, `TOKEN`, `SECRET` or `PASSWORD`, when it is at least 8 characters, is never placed on that command line. The driver adds no login field. Each run writes its own `ssh` config: the operator's config, then the system config, then a final `SendEnv` clear, so the user's settings win and the local environment is not forwarded. Sign in on the VPS.

`stop` asks the run's saved Linux VPS to end every process whose NUL-delimited `/proc/<pid>/environ` carries the exact `OPENWIZ_SSH_RUN` entry (not a line inside another variable's value), with an `ssh` config in a temporary folder that it removes, so this still works when the state folder can't be written. It then signals the recorded `ssh` only when its start time still matches, and on Linux every other local process of the run that still carries `OPENWIZ_SSH_RUN`. The start time is read even when `ssh` has already exited, so a reused pid is not signalled and does not block a wake. A wake that cannot save the new `ssh` ends it. A wake while that `ssh` is still running, or while its start time cannot be read, starts no second one.

Wake for a fleet on this host is the existing heartbeat (cron or a systemd user timer) or an outside always-on runner. This driver does not call room-cli.

Runs are saved under `$OPENWIZ_SSH_STATE` (default `~/.local/state/openwiz-ssh`). If that folder can't be written, the command answers with a driver error, not a traceback.

```sh
python3 -I adapters/ssh/test_driver.py
```
