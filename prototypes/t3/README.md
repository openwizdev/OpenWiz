# T3 driver lifecycle prototype

Login: stays on your machine
Effort: the host can't set it (the T3 0.1.11 CLI accepts model options but cannot discover or verify the exact executed effort)

This disposable driver implements the [v1 protocol](../../kernel/driver.v1.md) against a local fixture. It requires Python 3.9 or later on macOS or Linux and an existing private temporary directory. The only transport it can launch is the sibling `fixture.py`, using its own Python interpreter. The fixture models an agent, its work, and a ticket's builder note in JSON files. It uses no login, T3 server, agent CLI, network, private T3 storage, or GitHub.

The fixture maps `example/site` to project `prj_syn-openwiz` with a checkout under the disposable directory, and maps `codex` with `gpt-6.2-sol` to provider instance `instance-syn-codex`. A start uses the project root, the host's default effort, and a stable title of the form `#7: example/site builder (<run>)`. The driver returns its own per-run identifier. An explicit effort for the mapped pair gets the v1 refusal before the driver opens state or dispatches anything. A production caller with a configured effort must wait for support, under E4.

## T3 0.1.11 evidence and fixture behavior

- Checked the installed `t3` only with `--version`, `--help`, `thread --help`, `thread start --help`, `thread send --help`, `provider --help`, and `project --help`. The release tag points to `59651c1761f6c63e9b6056839067066968e6a406`. [Upstream release](https://github.com/pingdotgg/t3code/releases/tag/v0.1.11)
- The fixture parses the supported argument forms `t3 thread start --json --title TITLE --provider INSTANCE --model MODEL PROJECT -` and `t3 thread send --json THREAD -`, with the prompts on stdin. Start sends a project ID, omits the worktree flag, and expects a receipt containing `threadId`, `projectId` and `runId`. A null run ID can describe a thread without a verified run. The start receipt itself carries neither the selected checkout nor the executed model or effort. A live check must confirm those separately. [Start and workspace options in the tagged source](https://github.com/pingdotgg/t3code/blob/v0.1.11/apps/server/src/cli/thread.ts#L703-L756) · [Start dispatch and JSON](https://github.com/pingdotgg/t3code/blob/v0.1.11/apps/server/src/cli/thread.ts#L817-L891)
- Send uses queue mode. A busy thread keeps its active turn and queues the follow-up. An idle thread starts a turn immediately. The reply identifies the thread, message, and turn with a status and delivery disposition. It acknowledges delivery or queuing. The tracker checks whether the turn later edits the original note. [Send dispatch and JSON](https://github.com/pingdotgg/t3code/blob/v0.1.11/apps/server/src/cli/thread.ts#L894-L933) · [Receipt schema](https://github.com/pingdotgg/t3code/blob/v0.1.11/packages/contracts/src/orchestratorMcp.ts#L568-L577)
- The installed CLI has no thread stop or archive verb. Tagged server source has an MCP interrupt tool with a stop option that requests a stop and addresses delegated tasks. Its receipt can say `interrupt_requested`. A production driver still needs a supported, approved host entry point and independent proof that the provider, subprocesses, and delegated work ended. The CLI parity issue moved to a discussion. [CLI commands](https://github.com/pingdotgg/t3code/blob/v0.1.11/apps/server/src/cli/thread.ts#L989-L997) · [Server stop behavior](https://github.com/pingdotgg/t3code/blob/v0.1.11/apps/server/src/mcp/OrchestratorMcpService.ts#L3721-L3770) · [Parity discussion](https://github.com/pingdotgg/t3code/discussions/33855)
- `terminate-fixture` and `advance-fixture` are local fixture controls. The fixture clears queued turns and modeled work, including delegated work, while retaining the thread and ticket note. T3’s stop holds queued work. A live proof must verify that held messages cannot restart the stopped run. An incomplete receipt keeps wakes fenced and permits a stop retry. Tests verify an unrelated thread and note survive. The fixture uses no long-lived provider or child processes.

The driver serializes lifecycle requests in each disposable directory. Before dispatch, it records attempts that could have side effects. An ambiguous start fences that ticket, and an ambiguous send fences further wakes while stop stays available for a known thread. Each acknowledged wake sends one message to the original thread. V1 carries no caller request ID, so an unresolved send requires inspection before another wake. It leaves an unresolved start for inspection in the disposable state.

## Reproduce the local checks

Run these commands from the repository root.

```sh
python3 -I prototypes/t3/test_driver.py -v
prototypes/t3/driver version
prototypes/t3/driver schema | cmp - kernel/driver-kit/schema.json
```

Run the existing kit against a newly created fake tracker. Automatic advance lets the kit observe the queued turn edit the note without a separate fixture control call.

```sh
(
  export TMPDIR="${TMPDIR:-/tmp}"
  OPENWIZ_T3_FIXTURE_DIR=$(mktemp -d "${TMPDIR%/}/openwiz-t3-fixture-XXXXXX") || exit 1
  export OPENWIZ_T3_FIXTURE_DIR
  trap 'rm -rf -- "$OPENWIZ_T3_FIXTURE_DIR"' EXIT
  export OPENWIZ_T3_FIXTURE_AUTO_ADVANCE=1
  export PATH="$(dirname "$(command -v python3)"):/usr/bin:/bin"
  python3 -I prototypes/t3/fixture.py init-tracker 7 || exit
  python3 -I kernel/driver-kit/kit.py --driver prototypes/t3/driver \
    --repo example/site --ticket 7 --harness codex --model gpt-6.2-sol \
    --skill build-ticket --effort medium --wait 5 \
    --tracker "$OPENWIZ_T3_FIXTURE_DIR/tracker-7.json"
)
```

Before implementation, `python3 -I prototypes/t3/test_driver.py Lifecycle.test_executable_lifecycle` ran one test and exited 1 at the first start, with the assertion `expected an executable driver for start; prototypes/t3/driver is missing`. It passed after implementation. The focused suite also exercises concurrent requests, an idle wake, malformed state, credential-shaped fields, and stopping after the checkout disappears. On macOS arm64, the fake-tracker kit passed version, start, wake, stop, and token. The macOS observer saw marked fixture processes. The provider and delegated work were simulated.

## Later authorized host proof

After spec and child-ticket approval, establish the supported host command and evidence for per-thread stop, descendant cleanup, and exact effort. Confirm the mapped project, checkout, provider instance and model on the selected build before dispatch. Use the host's own signed-in CLI and harness without handling credentials. For the approved Mac smoke, use a separate T3 data directory, isolated checkout and one approved throwaway ticket. Check the visible thread and executed settings, wake it while busy, and verify the original note changes. Verify queue disposition and termination of the provider, process and child work, keep the thread inspectable, and check another thread survives. Archive only if the approved design calls for it.

Run the [five-check kit](../../kernel/driver-kit/README.md) on that candidate and authorized ticket, with its record author and supported model and effort. Set the values below to those approved for the smoke. The kit reads GitHub and the live agent writes its own note.

```sh
python3 -I kernel/driver-kit/kit.py --driver "$APPROVED_DRIVER" \
  --repo "$SMOKE_REPOSITORY" --ticket "$SMOKE_TICKET" \
  --harness "$SMOKE_HARNESS" --model "$SMOKE_MODEL" \
  --skill build-ticket --effort "$SMOKE_EFFORT" --wait 900
```

Use the same live procedure on the approved deployment host and record the exact driver and host builds and cleanup. macOS requires the process observer to see a marked run process for stop and token to pass. A kit outside the host needs separate host-side evidence of termination.
