# KN8: Hermes as orchestrator on a maintained repository

Proof B1 of spec #1365 for Hermes: Hermes, with our skills and the owner's GitHub sign-in, takes one small real change in a maintained OpenWiz organization repository from grill to a merged pull request, starting its builder through the local driver ([`adapters/local/`](../../../adapters/local/README.md)). This folder holds the plan, the owner's steps, the evidence template and the sanitizer. The recorded run's evidence lands in `run/` after the run.

**Status: prepared, not run.** The live run is held until the owner is back (orchestrator ruling, [private record](https://github.com/jparker2006/ClosedWiz/issues/3065)). Nothing here claims the run happened.

## The plan

| Part | Choice |
| --- | --- |
| Repository | `openwizdev/WizSkills`: maintained, public, in the organization, CI `check`, standing merge rule pinned to the reviewed head |
| Change | One small WizSkills change that the owner picks in Hermes's grill: one ticket, size S, inside one skill's folder |
| Orchestrator | Hermes, with the OpenWiz skills installed, on the owner's own computer or VPS |
| Builder | Claude Code, `claude-opus-5-5`, Medium effort, started by `launch-fleet` through the local driver |
| Reviewer | Codex, Sol 6.2, Medium effort (J165): the other family, no helper agents |
| Merge | The cross-repository route: a recorded claim on the pull request, `check` green at the exact head, the other-family APPROVE at that head, `PUT .../merge` with `sha` set to that head, then read back |
| Identity | GitHub actions use the owner's own `gh` sign-in (or the owner's OpenWiz App, per G1). The driver and this folder never handle a credential |

## What the owner does

Each step happens on the owner's own machine. Only the owner signs in.

1. **Sign in.** Sign in to Hermes's model provider, to `gh` (`gh auth status` shows the owner), to `claude` and to `codex`. Check that `claude -p 'say ok'` and `codex exec 'say ok'` each answer.
2. **Get the skills.** Clone `openwizdev/openwiz` and `openwizdev/WizSkills`. In the WizSkills checkout, run `hermes skills trust` so Hermes loads the repository's own `.agents/skills/`. Then check that `hermes skills list`, run there, shows `grill`, `launch-fleet`, `build-ticket` and `review-ticket`, plus the planning skill those name.
3. **Choose the host for WizSkills.** On a branch of WizSkills, add `docs/agents/host.md` with the single line `Host: local`. Add one row to `docs/agents/fleet.md`: `| Harness permission mode | `<mode>` |`, using a `claude --permission-mode` value you accept for builders on WizSkills. Merge that change the usual way. `launch-fleet` reads both from `main`.
4. **Approve the mode on this machine.** Write `$OPENWIZ_LOCAL_STATE/approvals.json` (default `~/.local/state/openwiz-local/`), mode 600, as `{"openwizdev/WizSkills": {"claude": "<the same mode>"}}`.
5. **Check the driver.** Optionally, run the driver kit on a throwaway ticket first, as the local driver's README says. `adapters/local/driver version` must answer.
6. **Set the fleet's environment** in the shell that starts Hermes: `OPENWIZ_ADAPTERS=<openwiz checkout>/adapters`, `LAUNCH_FLEET_STATE` and `LAUNCH_FLEET_RUNS` (absolute paths outside any checkout), and `LAUNCH_FLEET_HARNESS=hermes`, `LAUNCH_FLEET_MODEL=<Hermes's model>`, `LAUNCH_FLEET_SKILLS=<skill@version list>`.
7. **Start Hermes in the WizSkills checkout** with one plain request: *"Grill me on one small WizSkills change, plan it into one ticket, and launch its fleet with the local host: builder Claude Code Opus 5.5 Medium, reviewer Codex Sol 6.2 Medium."* Answer the grill. Confirm the spec and approve the one-ticket plan when Hermes asks.
8. **Let it run.** Hermes starts the builder through `host.py start`, which calls the local driver. When CI is green, Hermes starts the reviewer and merges at the reviewed head. Keep the machine awake until the merge, and step in only when Hermes asks.
9. **Collect the raw records** into one folder outside every checkout: Hermes's session export, `LAUNCH_FLEET_RUNS`, each run's log from `$OPENWIZ_LOCAL_STATE`, and `gh` exports of the ticket, the pull request (with comments, reviews and checks) and the merge read-back. Leave out the grill's exact words: the private record keeps them.
10. **Hand over.** Tell the builder of #1373 where the raw folder is. The builder sanitizes it and opens the pull request.

**Open point for the owner.** `launch-fleet` still starts reviewers with `room-cli` (builders.md, "Hosts"). So either Hermes's machine has a signed-in `room-cli`, or the owner rules how the Codex reviewer starts for this run.

## Making the evidence

```sh
python3 -I kernel/proofs/hermes/sanitize.py <raw folder> /tmp/kn8-run --literals <private literals file>
```

The sanitizer replaces thread ids, driver run ids (numbered in order), home paths, credential shapes, non-noreply email addresses and every line of the private literals list (the owner's names, hosts and anything else private). Then it runs the privacy check with that list required. On a refusal it deletes its output, and the raw folder is fixed by hand. The builder then copies the result into `run/`, fills [`RUN.md`](RUN.md) and reads every file before committing. The sanitizer is a floor, not a review.

```sh
python3 -I kernel/proofs/hermes/test_sanitize.py
```
