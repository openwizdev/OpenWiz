# Crush (`crush`) harness row

Login: Crush's own sign-in, from crush login (Hyper, Copilot, OpenAI or Grok) or a provider key you set yourself; Crush keeps it in its config and ~/.local/share/crush/crush.json, and the driver never reads or passes it

Effort: `--reasoning-effort`, for low, medium and high

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs Charm's [crush](https://github.com/charmbracelet/crush) with `crush run`, the non-interactive command. Nothing here was installed or signed in to. No test starts the real `crush` program: the runner puts a no-op stub named `crush` on `PATH`, and this folder's `fake` goes ahead of it.

## The commands

- **Start:** `crush run --quiet --verbose --model <model> -y [--reasoning-effort <level>] -- <prompt>`
- **Wake (same run):** `crush run --quiet --verbose --session <id> --model <model> -y [--reasoning-effort <level>] -- <prompt>`
- **Model on wake:** the wake names the start's model again. Without `--model`, a continued session takes its model from the session's last assistant message, and only when that provider and model are still available ([`app.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/app/app.go) `RunNonInteractive` and `restoreModelFromSession`). A first turn that failed before any reply leaves nothing to restore, so the wake would run the default model. An explicit `--model` skips that restore.
- **Session:** reported. With `--verbose`, crush logs `Created session for non-interactive run` and `session_id` ([`app.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/app/app.go) `RunNonInteractive`, and the same line in [`run.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/run.go) on the server path). The row reads that id. It does not use `--continue` or `crush session last`, which name the newest session in a data directory other runs can share.
- **Mode:** `yolo` passes `-y` once. That skips permission prompts and keeps the block list for dangerous commands ([`root.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/root.go), the `--yolo` count flag). `-yy` is not a mode of this row.
- **Env:** `CRUSH_CLIENT_SERVER=0`, so a turn stays in-process. When that variable is unset, crush follows `options.experimental.client_server` and can attach to a server that is already running ([`root.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/root.go) `clientServerEnabled`). That server is not in the run's process tree, so stop would not end it. `daemon` is `none`.
- **Stop:** the driver's own stop, which ends the run's process tree. A one-shot `crush run` does not leave a detached server behind ([`run.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/run.go)).
- **Not signed in:** with no provider, `crush run` returns `no providers configured - please run 'crush' to set up a provider interactively` ([`run.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/run.go)). `start` then fails with `the harness is not signed in`, and its `next` names `crush login`.
- **The fake:** exits 2 unless the line is one of the two above, with `CRUSH_CLIENT_SERVER=0`, and also exits 2 when a key is placed on the command line: a key flag, or any argument the driver kit's credential check flags, a bare key included.

## Effort

The row passes `--reasoning-effort` for the three levels the command lists: `low`, `medium` and `high`. The flag's own text says levels depend on the model and that an unsupported value is rejected with the accepted values listed, not dropped ([`run.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/run.go) `reasoning-effort`, and `overrideReasoningEffort`). `{effort}` is on start and on wake, because the same flag applies when a session is continued. A start whose effort is not one of those three is refused and starts nothing.

## Where the login lives

`crush login` signs in to Hyper, GitHub Copilot, OpenAI or Grok ([`login.go`](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/internal/cmd/login.go)). Other providers take a key you set yourself, in the model picker or in the environment Crush reads ([README](https://github.com/charmbracelet/crush/blob/e596bad90522445cbf473fae3d4baa0bfc9a9fb3/README.md), API Keys). Crush's config is `~/.config/crush/crushrc` (or `XDG_CONFIG_HOME`), and its JSON state is `~/.local/share/crush/crush.json`. The row has no field for a key, and the driver never reads or passes one.
