# OpenWiz loops

One JSON definition per loop, kept here on the project's default branch.
The service reads them using the [`loops.v1` contract](../contracts/loops.v1.md)
and [schema](../contracts/loops.v1.schema.json). Names and IDs are distinct:
`name` is for display; `id` is stable and unique within the project.

To propose a loop, an agent writes a definition and opens a pull request.
Jake confirms it once, including its trigger, authority and off switch;
then it can merge and run. A schema pass does not supply that approval.
The first migrations run in shadow beside the existing CloudRoom loop;
only the old loop acts until their records agree for a day; then the new one takes over.
New kinds of loop are grilled separately.

[`example.json`](example.json) is wholly synthetic, disabled and in shadow.
Its check prints no bytes, its project/model/approval are placeholders,
and it authorizes no live action. It illustrates an interval schedule,
a time-limited argument-vector check, an explicit agent configuration,
recorded authority and a budget. Replace placeholders only in a separately
approved real definition. A successful check with empty stdout never wakes
an agent.

Definitions contain no secrets, personal context or live session content.
Run history and check findings are runtime data, never committed under
this folder. Records live in the service's private state directory.
The durable per-loop off/on switch is managed by OpenWiz's `loop off` and
`loop on` surfaces (L6), rather than changing a CloudRoom loop. Switching
off prevents new work; already-created threads are reported honestly.

Conformance proof: `cargo test -p openwiz-tests --test checks loops_schema`.
This folder and that proof do not implement scheduling or prove live runs.

## Switching repository

No definition here names a repository: a definition runs in the checked-out
project, and its `action.project` is the CloudRoom project. The loops and
tools below read the repository from the clone they run in, or from one
setting. Moving them to another repository (as at the move to the public
repository, spec #1257) is a fresh clone or that setting, never an edit:

| Loop or tool | Its repository comes from | To switch it |
| --- | --- | --- |
| A definition in this folder | The CloudRoom project's checkout | Point the CloudRoom project at the new repository; nothing here changes |
| The stall alarm (`tools/stall-alarm/`, a Local script-only loop) | Its `--repo OWNER/NAME`, baked into the loop's stored script | Rebuild the script with the new `--repo` and a new state file (a state file kept for another repository is refused), then replace the loop's stored script, as its README says |
| Factory metrics (`tools/factory-metrics/`, no loop installed) | Its `--repo OWNER/NAME`, on every run | Pass the new repository |
| The roadmap (`tools/roadmap/`) | The clone it runs in (`gh` reads `git remote`); release tags from `--public-repo` (default `jparker2006/OpenWiz`) | Run it in a clone of the new repository; its generated links then name that repository when the pages are regenerated. Pass `--public-repo` only if the tags move elsewhere |
| The read-only GitHub App's setup (`tools/github-app/setup.py`) | Its `--repo OWNER/NAME`, or else the clone's GitHub `origin` | Run it from a clone of the new repository, or pass `--repo`. An App already made keeps its homepage until it is edited in GitHub's App settings; install it on the new repository there too. `mint-token.py` names no repository |
| The orchestrator's board renderer (private, kept with the private records) | Its `--repo OWNER/NAME`, whose default is the private repository | Pass `--repo` with the public repository for development; keep the default for a view of the private record. Changing its checkout alone does not switch it |
| The CloudRoom loops that name the repository (the merge sweep, the orchestrator watch, the polish waves, the standby check) | Their prompts, and the scripts they run from a clone | Name the new repository in each prompt, and run each script from a clone of it. Their prompts and scripts are private, so the cut-over runbook (#1284) lists each one with its read-back |

Not switched here, and listed in the cut-over runbook instead: the CI
specs' tools (`tools/ci-bench/`, `tools/pc-capacity/`, `tools/ci-overflow/`
and the runner kit in `ci/runner/`). `python3 tools/github-app/test.py`
checks that no file in this folder, those four tools or `docs/ROADMAP.md`
names a fixed repository (#1279).
