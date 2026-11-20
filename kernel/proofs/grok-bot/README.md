# Grok Bot as orchestrator: the recorded run (B1)

Ticket #1396 (KN9 of spec #1365). The proof is one live run: Grok Bot, as orchestrator with only OpenWiz's skills, the owner's GitHub login and a driver, takes one tiny real spec on a demo repository from grill to merged pull requests, starting builders through the local driver. This folder holds that run's sanitized evidence and the tools that make it. Nothing in OpenWiz is changed or special-cased for Grok Bot.

**Status:** the run has not happened yet. Until `run.md` and `checks.txt` are here, this folder proves only that the sanitizer works on synthetic records.

## Layout

| Path | What |
| --- | --- |
| `sanitize.py` | `fetch` reads the demo repository's records into a private file; `build` turns them into `run.md` and names any stage the run missed |
| `test_sanitize.py`, `fixtures/raw.json` | The sanitizer's proofs, on synthetic records with planted private text |
| `evidence/red.txt`, `evidence/green.txt` | The sanitizer's failing-first run and its passing run |
| `run.md` | After the run: the sanitized timeline of every issue and pull request on the demo repository |
| `checks.txt` | After the run: the stage line, the privacy check and the no-special-case check, each with its exit code |

```sh
python3 -I kernel/proofs/grok-bot/test_sanitize.py
```

## What `run.md` keeps

Only record forms, from the demo repository's record authors (its `docs/agents/fleet.md` row): status notes (agent, state, harness, model, skills, step, pull request), `VERDICT:` headers, `launch-fleet:` first lines, plan approval headers without the name or words, private-record pointers in an issue body, and merges with their heads. Every other body, including the grill's answers, review findings and anyone else's comments, is dropped to `comment, body dropped`. A note or title holding a thread id, machine path, credential shape, email address or quote mark is withheld whole. The stages it checks are: spec, grill pointer, plan approved, started, builder, reviewer, approved, merged.

## The owner's run

Every sign-in, every spend and every grill answer is the owner's. No agent of this ticket handles a credential.

1. **Demo repository.** The owner creates it, public, and runs the `setup` skill there: `docs/agents/fleet.md` with a `Record authors` row naming the login Grok Bot acts as, its `Harness permission mode` row, and `docs/agents/host.md` with `Host: local`. A private records repository for the grill and the run map, as the skills expect.
2. **The builder machine.** Where the local driver runs: `claude`, `codex` and `gh` signed in by the owner; `$OPENWIZ_LOCAL_STATE/approvals.json` holding the same mode for the demo repository; an OpenWiz checkout for `$OPENWIZ_ADAPTERS`. Check it with the driver kit on a throwaway ticket first ([adapters/local/README.md](../../../adapters/local/README.md)).
3. **Grok Bot.** Signed in by the owner, with GitHub connected to the demo repository only, and the skills cloned from the pinned WizSkills release in `wizskills.lock` (0.2.0, which has `launch-fleet`'s `host.py`), never edited.
4. **The run.** The owner asks Grok Bot to use `grill` on one tiny idea and answers it; then `to-spec`, `to-tickets` (its plan checks and approval) and `launch-fleet`, which starts each builder with `host.py start` and its reviewer, until every ticket's pull request has merged.
5. **Collect.** Anyone with read access, from an OpenWiz checkout:

   ```sh
   python3 -I kernel/proofs/grok-bot/sanitize.py fetch --repo <owner>/<demo> --out <private file outside the checkout>
   python3 -I kernel/proofs/grok-bot/sanitize.py build <private file> --out kernel/proofs/grok-bot/run.md
   python3 -I tools/privacy-check/check.py --tree kernel/proofs/grok-bot
   git grep -n -i grok -- adapters kernel/driver.v1.md kernel/records.v1.md kernel/driver-kit kernel/records-kit crates
   ```

   Save each command's output and exit code in `checks.txt`. The last must print nothing: no driver, contract, kit or crate knows Grok Bot.
