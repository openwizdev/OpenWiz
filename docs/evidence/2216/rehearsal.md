# 0.1.1 agent rehearsal: a stranger's install and first fleet on a clean Linux machine, no CloudRoom

The agent half of #2226, run by #2265's release agent on the sealed 0.1.1 candidate before anything publishes. It proves P7's Linux and Claude Code row only: no Mac, no Codex, and not a person's own run.

## Inputs (from the sealed candidate, posted on #2265)

- `CANDIDATE_COMMIT`: the `release-0.1.1` commit the candidate seals.
- `PACKAGES_RUN`: the Packages run that built the candidate's archives at that commit.
- `LINUX_SHA256`: the candidate's `openwiz-0.1.1-x86_64-unknown-linux-gnu.tar.gz` hash.
- `WIZSKILLS_COMMIT`: the commit in the candidate's `wizskills.lock` (NC8's WizSkills 0.4.0).

## Rules

- **LV1:** one new private throwaway repository and its own tickets only. Archive it at the end (the signed-in token has no delete scope). Touch no other repository, project or thread.
- Never run `openwiz github token` in any form, not even with `--help`, and never run `agent-token.py` or any helper that reads `OPENWIZ_GITHUB_APP_KEY`. Skip the GitHub App in the first fleet: the personal login acts, and setup says so.
- Run every install, setup and fleet command through `rehearsal.sh run`, so it gets the clean environment: an allowlisted `PATH` with no `room-cli` or other CloudRoom program, and no CloudRoom or App variable.
- Raw output stays in `$RH` and in the private record. Only the pass/fail summary below goes on GitHub. Don't write any thread id, path under `/home`, or session text into it.
- Don't wait with `sleep` or a shell loop. To wait for the fleet, say "run the fleet now" (`heartbeat.py run`), or use a Monitor with an until-condition.
- If any step fails, stop, run the teardown, and report the failing step and its exact output.

## Recording (the demo, kept private)

Every `rehearsal.sh run` and `say` is recorded with its real timing under `$RH/demo/`. Put a `say` caption before each moment the demo shows, in these exact words:
- `say "A stranger pastes into Claude Code: Install OpenWiz from github.com/openwizdev/OpenWiz"` (before step 4);
- `say "Where should your agents run? This computer"` (step 5);
- `say "The first fleet starts on this computer"` (step 6);
- `say "A builder opens the pull request; a reviewer reviews it; it merges"` (step 8).

Show the pull request's review verdict and merge with `rehearsal.sh run gh pr view <N> --repo <throwaway> --json state,mergedAt,reviews`. Never print a key or token, and name no repository but the throwaway one. If the run fails, keep the recording and caption where it stopped. The recording, raw and cut, goes only to the private record.

## Steps

1. **Machine.** `rehearsal.sh machine`, then `rehearsal.sh check` must print `clean: ...`. Record `uname -a`, `ldd --version` and `claude --version` from `rehearsal.sh run`. Deviation from a stock machine, stated: this sandbox image has no cron and no systemd user manager, so `machine` installs Debian's `cron` and starts it.
2. **Throwaway repository.** `rehearsal.sh repo` creates `<owner>/openwiz-rehearsal-011-<stamp>`, private.
3. **Candidate files.** `rehearsal.sh candidate "$PACKAGES_RUN"` must print `OK` for every Linux file. The archive's sha256 must equal `LINUX_SHA256`.
4. **The stranger's line.** Treat this as the message a stranger pastes into Claude Code: "Install OpenWiz from github.com/openwizdev/OpenWiz". Follow the install skill at `WIZSKILLS_COMMIT` exactly, as its user's agent would. There are exactly two substitutions, because the candidate isn't published yet:
   - the preflight clone is `git clone --branch release-0.1.1` checked out at `CANDIDATE_COMMIT`, not the release tag;
   - step 2 is the documented fallback `install install --assets "$RH/assets" --target x86_64-unknown-linux-gnu --root <new root>`, not `download`.
   The skill's own folder is a clone of WizSkills at `WIZSKILLS_COMMIT`. Record each command's JSON outcome.
5. **"This computer".** Answer the host question with "This computer", harness Claude Code. Take the model from `openwiz models list` (local source). Preflight must not stop on `room-cli: missing`. `setup.py check` must read `cloudroom: not_needed`.
6. **First fleet.** On the throwaway repository: skip the App. Answer the permission-mode question with the narrowest mode that lets a builder commit and push, and record the pick. Merge the `Host: local` setting pull request. The idea is one tiny ticket: "Add `HELLO.md` saying hello from OpenWiz". Keep the grill short and approve the plan.
7. **Heartbeat with its yes.** Read `heartbeat.py install`'s exact preview, then run it again with `--yes`. `heartbeat.py status` must show the job. `crontab -l` must show one OpenWiz line. Then "run the fleet now" once.
8. **Built, reviewed, merged.** The builder opens a pull request for the ticket. A reviewer starts through the local driver with `review-ticket`. With Claude Code only, the verdict is marked "same-family review". The pull request merges and the ticket closes. Tick by hand as needed.
9. **Teardown.** `rehearsal.sh teardown <spec number>`: remove the heartbeat, check that no builder or reviewer is still running, close open tickets, and archive the repository.

## Pass

All of these must hold, each with its recorded output:

- `check` was clean before step 4 and after step 8;
- the install verified the candidate's archive hash and reported `0.1.1` from `CANDIDATE_COMMIT`;
- no step asked for CloudRoom, and no output mentions a `room-cli` call;
- the setup check was ready with `cloudroom: not_needed`;
- the heartbeat installed only after its yes, and ticked;
- the tiny ticket's pull request was built, reviewed (same-family, marked) and merged;
- after teardown, the heartbeat is gone, no agent process is left and the repository is archived.

## Result

`rehearsal-result.md` beside this file records the inputs, each pass line as pass or fail, the elapsed time per step and any deviation. The raw logs go to the private record.
