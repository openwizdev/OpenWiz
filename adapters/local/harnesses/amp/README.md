# Amp (local runs)

Login: Amp's own saved account on this machine, from `amp login` (see `amp account list`), or AMP_API_KEY that you set yourself to an access token from your Amp settings; the driver never reads, sets or passes a login

A harness row for the [local driver](../../README.md), in the shape of the [harness-row contract](../../harness-row.md). It runs the [Amp CLI](https://ampcode.com/docs/cli) in execute mode on this machine only; orbs (`-ox`) and runners (`--executor runner:<id>`) are out of scope. Every command line below was read from Amp CLI `0.0.1795392057-g03d1fb` (npm `@ampcode/cli-linux-x64`, checksum checked), its docs and its own `--help` text, read as text on 2026-11-23: nothing was installed, run or signed in to.

**Stop does not end an Amp background subagent.** A background subagent (a Task call with `mode: "async"`) runs in the thread on Amp's servers, not on this machine, and Amp has no command to cancel one. Stop ends every local process of the run, but a background subagent the agent started can keep running on Amp's servers after stop ([why](#the-census-check-does-stop-end-amps-background-subagents)).

Effort: `--effort <level>`, with the model from `--model`, at start only

- **Start:** `amp -x <prompt> --stream-json --no-archive-after-execute --model <model> <mode's arguments> <effort's arguments>`. The model is Amp's `provider/name` id, such as `openai/gpt-6-astra` ([Model Selector](https://ampcode.com/docs/model-selector#effort)).
- **Wake (same run):** `amp threads continue <thread id> -x <prompt> --stream-json <mode's arguments>`. The thread keeps its own model and effort.
- **Session:** reported. Amp names the thread `T-…`, and every stream-json message carries it as `session_id`, the `init` message first ([Streaming JSON](https://ampcode.com/docs/cli/streaming-json)); the row reads `session_id` from the first JSON line that has it.
- **Why `--no-archive-after-execute`:** `amp -x` archives the thread it creates when the command finishes, and an archived thread "is archived and cannot be continued" (the CLI's own message, which points to `--no-archive-after-execute`). Its `--help`: "When used with --execute on a new thread or with the review command, leave the thread unarchived after the command finishes." Without it, the census's start command would make every wake fail; `test_row.py` shows that with the fake.
- **Env:** `AMP_SKIP_UPDATE_CHECK=1`, so a turn never installs an Amp update in the background. Amp "automatically checks and installs new versions in the background" ([Getting Started](https://ampcode.com/docs/cli#update)); the variable "overrides this setting and disables all update checks" ([Configuration](https://ampcode.com/docs/cli/settings), `amp.updates.mode`).
- **Stop:** the driver's own stop, which ends the run's process tree. See the census check below.
- **Permission modes:** `allow-all` passes `--dangerously-allow-all`; `default` passes nothing, so Amp's own permission rules decide, and execute mode refuses a tool those rules would ask about ("tool is not allowed to run in execute mode. Rerun with --dangerously-allow-all to bypass", the CLI's own message). Approve one of these for `amp` as for a built-in harness.

## Effort

The row passes the user's effort to Amp, in the contract's first form. Each effort value maps to `--effort <the same value>`, for Amp's seven levels `none`, `minimal`, `low`, `medium`, `high`, `xhigh` and `max` (the level list in the CLI's own source). Sources:

1. [Model Selector](https://ampcode.com/docs/model-selector#effort): "`--effort` (or `effort`) sets its effort; without it, the thread runs at the model's default effort. This works ... in execute mode (`-x`)", with the example `amp -x "Review this repository" --model openai/gpt-6-astra --effort xhigh`; and "In execute mode, `--effort` needs a model. Amp rejects an effort the model does not support." Amp never drops a level silently, so the row may claim it.
2. The CLI's `--help`: "Set the reasoning effort for a new thread on a model (from --model, or a model passed to --mode); omit for the model's default". Its errors: "The --effort flag requires a model, such as --model openai/gpt-6-astra --effort high." and "The --effort flag is only supported when creating a new thread." So `{effort}` is in `start` only, after `--model {model}`.

A start with an effort Amp has no level for is refused by the driver with its D3 error and starts nothing.

## The census check: does stop end Amp's background subagents?

**Every local process, yes; the subagent itself, no: it runs on Amp's servers, and stop cannot end it.**

What the sources say:

1. [Streaming JSON](https://ampcode.com/docs/cli/streaming-json): "Background subagents keep running when the Amp process that started them exits. When you continue the thread with `amp threads continue`, the `init` message lists the ones still running in `subagents`." The message schema adds, for `init`: "Background subagents still running when this process attached to the thread, for example ones an earlier process started before it was killed". A background subagent is a Task call with `mode: "async"`.
2. [Threads](https://ampcode.com/docs/threads): "Where the agent runs is separate from where you look at it: a thread can run in an orb, on a runner, or in a local CLI session." The CLI's own source names the thread a server-side "thread actor" and the local `amp` process its executor: its errors include "The thread's executor is not connected; start it and retry." and "No executor connected for filesystem requests".
3. The CLI's shell tool runs commands on the executor, and its kill tool ends "the process and its children" (its own tool text): a command is a local process under the turn's `amp`.

So a background subagent is not a local process. Its model turns go on in the thread on Amp's servers after the `amp` process is gone; its local work (files, shell commands) needs the thread's executor, which is the turn's `amp` process, and the driver's stop ends that process with its whole tree. Nothing local outlives stop: the fake's background subagent, double-forked out of the turn's process group, must have ended after stop, and the runner checks it (`daemon`).

What stop does not do: end the server-side subagent. No Amp command does that. `amp threads` has `archive`, `delete`, `label`, `rename`, `share` and the rest, but no stop or cancel; the Threads page says only that archiving "removes the thread from your active lists", and that "Snoozing does not stop the agent". So the stop field from #2538, `amp threads archive {session}`, has no source that it stops a running subagent. Amp documents no flag or setting that turns background subagents off either: neither the [Configuration](https://ampcode.com/docs/cli/settings) page nor the CLI's `--help` has one.

The ruling on openwizdev/OpenWiz#2529: the row ships with this said plainly, and the live check (#2550) records whether any background subagent appeared in the run and what happened to it after stop.

## Not installed, not signed in

- `amp` not on `PATH`: the driver's D3 error `harness amp is not installed here`, whose `next` says to install amp and sign in to it yourself. Amp's installer is `curl -fsSL https://ampcode.com/install.sh | bash` ([Getting Started](https://ampcode.com/docs/cli#install)).
- Not signed in: the row's `signed_out` patterns match Amp's own messages, such as "No API key found. Run `amp login` first.", so `start` fails with the driver's D3 error `the harness is not signed in`, whose `next` names `amp login`. For a script or CI, set `AMP_API_KEY` to an access token from your Amp settings (it starts `sgamp_`); the CLI refuses the short-lived session token that `amp login` saves ([Execute Mode](https://ampcode.com/docs/cli/execute-mode#non-interactive-environments)). A set `AMP_API_KEY` "takes precedence over saved accounts" ([Getting Started](https://ampcode.com/docs/cli#manage-cli-accounts)). The driver never reads, sets or passes either.

## Tests

```sh
python3 -I adapters/local/test_harnesses.py    # finds this row; the contract, the kit's five checks with ./fake, the session, env, background-subagent, signed-out and effort checks, then test_row.py
```

`fake` is a synthetic `amp`: it allows only the two command lines above (exit 2 on any other). Like amp, it archives a thread started without `--no-archive-after-execute`, and continuing that thread then fails, prints its thread id in a stream-json `init` message, starts a background subagent outside the turn's process group, and, with `AMP_FAKE_SIGNED_OUT=1`, answers as a signed-out amp does. It takes any model, because the runner's model is `synthetic-1`; the real CLI needs `provider/name`. `test_row.py` checks not installed, not signed in, each mode's exact start and wake, each effort level at start and never at wake, that a start without `--no-archive-after-execute` makes the wake fail, and the command lines the fake refuses.

Live check: #2550
