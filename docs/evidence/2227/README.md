# #2227 evidence: the README and install guide say CloudRoom is optional

`check_docs.py` is this ticket's proof. From the repository root:

```sh
python3 -I docs/evidence/2227/check_docs.py
```

It reads `README.md` and `docs/install.md` and prints one line per failure:

1. **Nothing says CloudRoom is required:** no "needs CloudRoom", "requires CloudRoom", "CloudRoom is required", "You need CloudRoom", "done only when CloudRoom" or "sets up through it".
2. **CloudRoom's install is conditional:** every line that runs `cloudroom.py install` says "only if you pick" CloudRoom, and no "Before you start" bullet lists CloudRoom without saying it is optional.
3. **The three hosts, this computer first:** each file has a line that names this computer, boat.dev and CloudRoom in that order and says "CloudRoom is optional".
4. **0.1.0 and 0.1.1 told apart:** each file has a sentence saying that on 0.1.0 the automatic fleet runs in CloudRoom, and one saying 0.1.1 runs it on this computer.
5. **The release path (review R1):** each file has a section headed with 0.1.0; outside it, no `maint/0.2` link. The install guide derives the skill from `wizskills.lock`, clones `--branch <tag>`, expects build identity `0.1.1`, and has no `maint/0.2` overwrite step outside the 0.1.0 section. A hardcoded WizSkills `v0.4.0` pin or a `--branch v0.1.1` clone fails.
6. **Intel Mac (R2):** no line says an Intel Mac installs only from 0.1.1.
7. **The heartbeat (R3):** nothing says it "wakes the fleet every ten minutes"; the guide says it checks every ten minutes and wakes only when work is due, that boat.dev fleets use it too, lists `jq`, and says a same-family review is marked.
8. **Removal (R4):** the guide's "Remove it" names `heartbeat.py pause`, `heartbeat.py remove` and `install remove`, and nothing says there is no remove command.
9. **boat.dev credentials (R5):** the guide's boat.dev prerequisites name its dashboard, GitHub write access and the Claude Code or Codex key.
10. **0.1.0 selected explicitly (re-check R1):** the guide's 0.1.0 section names the `releases/download/v0.1.0/` files and `install install --assets`, and the README's 0.1.0 section links to it.
11. **Where the orchestrator runs (re-check R3):** nothing says this computer runs the orchestrator for boat.dev; a sentence says it starts in a boat.dev sandbox there; "run the fleet now" is qualified for a paused job.
12. **Only OpenWiz's skill folders (R6):** "Remove it" never says to delete the listed skill folders, and says to keep each listed folder itself.

Exit 0 when all hold, 1 otherwise. It reads only.

- `red.txt`: the run at `main` before the fix (exit 1).
- `green.txt`: the run after the fix (exit 0).
- `red-recheck.txt`: the run at the re-checked head `35b8c5f6`, after checks 10 to 12 were added, before the fix (exit 1).
- `red-review.txt`: the run at the reviewed head `eba812af`, after checks 5 to 9 were added, before the fix (exit 1).
