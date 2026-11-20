# Grok Bot as orchestrator: the recorded run (B1)

Ticket #1396 (KN9 of spec #1365). The proof is one live run: Grok Bot, as orchestrator with only OpenWiz's skills, the owner's GitHub login and a driver, takes one tiny real spec on a demo repository from grill to merged pull requests, starting builders through the local driver. This folder holds that run's sanitized evidence and the tools that make it. Nothing in OpenWiz is changed or special-cased for Grok Bot.

**Status:** the run has not happened yet; it is held until after 2026-11-21. Until `run.md` and `checks.txt` are here, this folder proves only that the sanitizer works on synthetic records.

## Layout

| Path | What |
| --- | --- |
| `sanitize.py` | `fetch` reads the demo repository's records into a private file; `build` turns them into `run.md` and names any stage the run missed |
| `test_sanitize.py`, `fixtures/raw.json` | The sanitizer's proofs, on synthetic records with planted private text |
| `evidence/red.txt`, `evidence/red-r1.txt`, `evidence/red-r2.txt`, `evidence/green.txt` | The sanitizer's failing-first runs (its first slice, the plan approval forms, then CRLF notes, loose `pr` values and changed raw shapes) and its passing run |
| `run.md` | After the run: the sanitized timeline of every issue and pull request on the demo repository |
| `checks.txt` | After the run: the stage line, the privacy check and the no-special-case check, each with its exit code |
| `collect.sh` | Writes `run.md` and `checks.txt`, and fails on any unexpected result |
| `runbook.md` | The demo repository plan and the owner's exact steps |

```sh
python3 -I kernel/proofs/grok-bot/test_sanitize.py
```

## What `run.md` keeps

Only record forms, from the demo repository's record authors (its `docs/agents/fleet.md` row): status notes (agent, state, harness, model, skills, step, pull request), `VERDICT:` headers, `launch-fleet:` first lines, the machine plan approval header with its `Grill confirmed:` pointer, `Checks:` and `Fingerprint:` lines, human plan approval and spec confirmation headers without the name or words (with their `Private record:` pointer), and merges with their heads. Every other body, including the grill's answers, review findings and anyone else's comments, is dropped to `comment, body dropped`. A note or title holding a thread id, machine path, credential shape, email address or quote mark is withheld whole. The stages it checks are: spec (an issue labelled `spec`), grill pointer (a `Grill confirmed:` line), plan approved, started, builder, reviewer, approved, merged.

## The owner's run

[runbook.md](runbook.md) is the demo repository plan and Jake's exact steps, from a 10-minute check of Grok Bot's computer to handing the run back. Every sign-in, every spend and every grill answer is his; no agent of this ticket handles a credential.

## Collect

From the root of an OpenWiz checkout, with `gh` signed in, once the run is done:

```sh
sh kernel/proofs/grok-bot/collect.sh <owner>/<demo> <absolute private file outside the checkout>
```

It fetches the records into the private file (mode 600), builds `run.md`, and writes `checks.txt` with three checks and their exit codes: the stages (expected 0), the privacy check on this folder (expected 0) and `git grep -i grok` over `adapters/`, the kernel contracts, both kits and `crates/` (expected 1: no driver, contract, kit or crate knows Grok Bot). It exits 1 if any check differs. `evidence/collect-dry.txt` shows it failing on an empty synthetic repository.
