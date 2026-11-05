# OpenWiz CI selection record, version 1 (`openwiz.ci-selection.v1`)

One plan per CI run: which lanes run, which tests each runs, and why everything else was skipped. A first `changes` job writes it once; every lane reads it, and nothing re-decides. Its schema is [ci-selection.v1.schema.json](ci-selection.v1.schema.json); its fixtures are in [`ci/selection/`](../ci/selection/README.md), and `tests/checks/ci_selection.rs` checks them against the schema and the rules below.

**Contract only** (#1405, X0 of spec #1256). X5 (#1262) writes the record (from the docs-only classifier and K15/K16's selector, #432 and #433), and its lanes and its `ci` check read it; X6 (#1264) reads merged pull requests' plans to find selector escapes; X8 (#1266) splits the Rust lane's tests across runners. How the record is filled is X5's. The fixtures prove the record's shape, never a live run.

Authority: spec #1256, "One plan per run" and "Selection (CX2 (a))", from the confirmed grill `docs/grills/2026-11-05-ci-100x.md` (CX2 (a): "each PR runs only what it can affect, plus a small always-run set; full suite after every merge on `main` and nightly").

## Words

| Word | Meaning here |
| --- | --- |
| **Plan** | One CI selection record: the decision for one attempt of one CI run. |
| **Lane** | A group of tests CI runs as one job. There are five kinds: `always`, `rust`, `web`, `site`, and one lane per skill suite. How X8 splits the `rust` lane into shards is X8's; shards are not in the record. |
| **Test** | One unit a lane runs or skips, named by its [test id](#test-ids). |
| **Full run** | A plan whose `selection.mode` is `full`: every lane runs every test, and the plan says which event or doubt selected everything. |
| **Selected run** | A plan whose `selection.mode` is `selected`: a ready pull request's first attempt against `main`, opened, pushed to or reopened, where each lane runs only what the change can affect. |
| **Build** | A step that makes something lanes read, run or skipped once for the whole plan. Today only the web export (`apps/web/out`). |
| **Skip** | A lane, or a test inside a running lane, that the plan does not run. Every skip has a reason. |

## The record

| Field | What |
| --- | --- |
| `schema` | Always `openwiz.ci-selection.v1` |
| `run.id` | The CI run's id (`github.run_id`), an integer from 1 |
| `run.attempt` | The run's attempt (`github.run_attempt`), from 1. A later attempt is a rerun |
| `run.event` | `pull_request`, `push`, `schedule` or `merge_group`: the events CI runs on today. A new event is a contract change |
| `run.action` | A pull request run's activity type: `opened`, `synchronize`, `reopened` or `ready_for_review`; `null` on every other event. A draft pull request (`converted_to_draft`, or any run while it is a draft) gets no plan: its `changes` job fails, as every job does for a draft today |
| `run.base_branch` | The branch the change goes into: the pull request's base, or the pushed, scheduled or merge group's branch: `main`, or a `release-*` branch |
| `run.base` | The base commit, 40 lower-case hex digits: a pull request's base (`pull_request.base.sha`), a push's `before`, a merge group's `base_sha`; `null` when there is none (the nightly run, or a push whose `before` is all zeros) |
| `run.head` | The change's own commit: a pull request's head (`pull_request.head.sha`, not the merge ref CI tests), or the pushed, scheduled or merge group's commit |
| `run.pull_request` | The pull request's number on a `pull_request` run; `null` on every other event |
| `diff` | The [changed paths](#the-diff) the plan read |
| `selection` | `{"mode": "selected"}`, or `{"mode": "full", "reasons": [...]}` with every [reason](#full-runs) that applies, at least one, each code once |
| `builds` | Each [build](#builds), run or skip |
| `lanes` | Every lane, each [run or skip](#lanes) |
| `store` | Where the run keeps this plan: [the artifact and the file](#where-a-run-keeps-its-plan) |

## The diff

`diff.state` is one of:

| State | Means | Other fields |
| --- | --- | --- |
| `read` | The changed paths were read | `paths`: every changed path, repository-relative, each once, at least one |
| `empty` | The diff was read and had no path | none |
| `failed` | The diff could not be read, or held a path the record can't carry (a control character) | `error`: what failed, in a line |
| `not_read` | The plan didn't need it: a run that selects everything whatever changed (an event, a rerun, a release branch, ready for review), or whose event can't be trusted (`stale_event`) | none |

A selected run always has `read`. An empty or failed diff is never "nothing affected": it selects everything.

## Full runs

A full run runs every lane and every test, and names each reason in `selection.reasons`:

| Code | Means | Other fields |
| --- | --- | --- |
| `push_main` | A push to `main` | none |
| `nightly` | The nightly run on `main` | none |
| `rerun` | Any attempt after the first | none |
| `release_branch` | A run into a `release-*` branch | none |
| `merge_group` | A merge group (should a merge queue ever be on) | none |
| `ready_for_review` | A pull request just marked ready for review (`run.action` is `ready_for_review`), as `decide.sh` runs everything for it today | none |
| `unknown_path` | A changed path the selector's map doesn't know | `paths`: those paths |
| `ci_change` | A change to CI or the toolchain (the workflows, the classifier, the selector or its map, the runner kit, `Cargo.toml`, `Cargo.lock`, lockfiles), as the selector defines it | `paths`: those paths |
| `empty_diff` | The diff was read and is empty | none |
| `failed_diff` | The diff could not be read | none (`diff.error` says why) |
| `stale_event` | The event's base or head is not the pull request's live one (a retarget, a push since), or its base is not in the clone, as `decide.sh` checks today | `detail`: what didn't match, in a line |
| `selector_error` | The selector failed, or gave an empty or unreadable answer | `detail`: what failed, in a line |

The first six are events, the last six are doubts. A new code is a contract change.

## Builds

`builds` has exactly these keys:

| Key | The build |
| --- | --- |
| `web_export` | The web app's static export (`apps/web/out`), which some tests read. It runs when any selected test reads it; a lane that runs such a test waits for it |

A build is `{"decision": "run"}` or `{"decision": "skip", "reason": "<why>"}`. In a full run every build runs. Which tests read the export is the selector's map's.

## Lanes

`lanes` has exactly these keys:

| Key | The lane | Its test ids |
| --- | --- | --- |
| `always` | The always-run set: format, the classifier's and selector's own tests, the cheap architecture and privacy checks. Runs in every plan, every test, nothing skipped | `always:<name>` |
| `rust` | The Rust tests | `rust:lib:<package>`, `rust:test:<target>` |
| `web` | The web app's tests | `web:unit:<name>`, `web:browser:<name>` |
| `site` | The site and release lane: the public site's build and tests, and the release tests | `site:<name>`, `release:<name>` |
| `skills` | One lane per skill suite, as a list, each naming its `skill` once; every skill suite CI knows is listed in every plan | `skill:<skill>`, or `skill:<skill>:<part>` |

A lane is one of:

- **Run:** `{"decision": "run", "tests": [...], "skipped": [...]}`. `tests` names every test the lane runs, at least one, each once. `skipped` names each test of the lane the plan doesn't run, with its reason: `{"test": "<id>", "reason": "<why>"}`. A test is never in both.
- **Skip:** `{"decision": "skip", "reason": "<why>"}`. The whole lane is skipped, with its reason.

A skill lane carries `"skill": "<folder name under skills/>"` as well. In a full run every lane is a run with `"skipped": []`; the `always` lane is always so.

A reason is one line of plain text (1 to 500 characters, no control characters) a reviewer can read, such as "no changed path reaches it". X5's run summary is made from these reasons.

### Test ids

A test id is `<kind>:<name>`, the unit ids of K15's test-selection research (#432, branch `research/ci-test-selection`), so the selector's map, the plan and the escape finder use one name for each test:

| Id | One test is |
| --- | --- |
| `rust:lib:<package>` | A Cargo package's library tests (`cargo test -p <package> --lib`) |
| `rust:test:<target>` | One integration test binary, by its `[[test]]` name (`cargo test -p <its package> --test <target>`). The id names no package: `[[test]]` names are unique across the workspace today, and a clash would need a new version. X8 gives each to exactly one shard |
| `web:unit:<name>` | One of the web app's unit test files, by its name without the folder or extension |
| `web:browser:<name>` | One of the web app's browser test files, the same way |
| `site:<name>`, `release:<name>` | One step of the site and release lane |
| `skill:<skill>`, `skill:<skill>:<part>` | A skill's whole suite, or one part of it |
| `always:<name>` | One check of the always-run set |

A name is letters, digits and `_ . - :`. Which names exist is the selector's map's; the record only carries them.

## Where a run keeps its plan

The `changes` job uploads the plan as a GitHub Actions artifact of its own run:

- **The artifact** is named `ci-selection-<attempt>`, for the run's attempt (`ci-selection-1`, then `ci-selection-2` on a rerun), so each attempt keeps its own plan and none overwrites another.
- **The file** in it is `ci-selection.json`: the record, as UTF-8 JSON.
- **It is kept 30 days** (`retention-days: 30`), long enough for the escape finder to read every pull request merged since the last green full run.
- **The record names both** in `store`: `{"artifact": "ci-selection-<run.attempt>", "file": "ci-selection.json"}`.

**Reading a merged pull request's plan** (X6), for pull request `<n>` and its head `<h>` at its merge:

1. **The runs:** list the CI workflow's (`.github/workflows/ci.yml`) `pull_request` runs whose head commit is `<h>` **and** whose associated pull requests (GitHub's `pull_requests` list for the run) include `<n>`. Two pull requests can share a head commit, so a run of another pull request never counts. Read the association of every such workflow run at `<h>` first: if any one's `pull_requests` is missing, `null` or otherwise unreadable, that run might be `<n>`'s, so the answer is **unknown**, before any run is chosen and even when another run of `<n>` has a plan. A readable list that leaves `<n>` out, an empty one included, excludes that run. No run of `<n>` is unknown too.
2. **The run and attempt:** take the newest of those runs (the highest run id) and its last attempt. Never fall back to an older run or attempt.
3. **The plan:** download that attempt's `ci-selection-<attempt>` artifact and read `ci-selection.json`.
4. **Bind it:** the plan holds only if the contract accepts it and its `run.pull_request` is `<n>`, its `run.head` is `<h>`, its `run.id` and `run.attempt` are the run and attempt chosen in step 2, and its `store.artifact` is the artifact's name. So a first attempt's plan carried in a rerun's artifact, or another run's plan, never stands for this one.

A plan that is missing, expired, unreadable, refused by this contract, or fails step 4 is **unknown**: never "nothing skipped". The read cases in [`ci/selection/reads/`](../ci/selection/README.md#reads) give each answer this lookup must give, on synthetic runs; `tests/checks/ci_selection.rs` runs this lookup on them, and X6's reader must give the same answers. A test that plan skipped, and that fails on `main`, is an escape; the link the map missed runs from one of the plan's `diff.paths` to that test (a selected run always read its diff).

## Rules beyond the schema

A record is valid only when it matches the schema **and** keeps every rule here; `tests/checks/ci_selection.rs` checks both, and a reader must check both too.

1. **Read exactly.** An object has exactly its keys, each once: a repeated key is refused, never one copy kept.
2. **The store names its attempt:** `store.artifact` is `ci-selection-<run.attempt>`.
3. **The run's fields fit its event:** `run.pull_request` is a number and `run.action` an action exactly when `run.event` is `pull_request` (both `null` otherwise); a `pull_request` run has a `run.base`; `run.base` is never all zeros; `run.base_branch` is `main` or starts with `release-`.
4. **Every event that selects everything says so,** and a reason names only what happened:
   - `push_main` exactly when `run.event` is `push`, and a push's `run.base_branch` is `main` (CI runs on pushes to `main` only);
   - `nightly` exactly when `run.event` is `schedule`;
   - `merge_group` exactly when `run.event` is `merge_group`;
   - `rerun` exactly when `run.attempt` is above 1;
   - `ready_for_review` exactly when `run.action` is `ready_for_review`;
   - `release_branch` exactly when `run.base_branch` starts with `release-`.
5. **Doubts match the diff:** `empty_diff` exactly when `diff.state` is `empty`; `failed_diff` exactly when it is `failed`; `unknown_path` and `ci_change` only with a `read` diff, and each of their paths is one of `diff.paths`; a `not_read` diff only with a reason that needs no diff (`push_main`, `nightly`, `merge_group`, `rerun`, `release_branch`, `ready_for_review` or `stale_event`).
6. **Each test once:** no test id is twice in one plan, across every lane's `tests` and `skipped`.
7. **Each test in its own lane:** each id has its lane's form from [the test ids](#test-ids) (`rust:lib:` or `rust:test:` in `rust`, `skill:<that skill>` in that skill's lane, and so on), with a non-empty name.
8. **Each skill once:** no two skill lanes name the same `skill`.
9. **Each reason once:** no reason code is in `selection.reasons` twice.

The schema already makes a selected run a first-attempt `pull_request` into `main` (opened, pushed to or reopened) with a `read` diff, keeps every lane and build of a full run running with nothing skipped, and keeps the `always` lane running in every plan.

## Versioning

Adding, renaming or removing a field, a lane, a reason code, an event or a test id kind is a new version, approved like any contract change. A reader checks `schema` before anything else.
