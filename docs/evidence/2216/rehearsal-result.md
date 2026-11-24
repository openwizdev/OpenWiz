# OpenWiz 0.1.1 Linux rehearsal

## November 24, fourth run

Private Git access from a fresh Linux home passed at 18:05 UTC. The confirmation check compared the pushed file bytes with GitHub's blob at the immutable commit. The installed decision helper read that same commit on each head check and resolved the request at 18:06 UTC. Both Linux checksums passed. The installer activated the expected build at 18:07 UTC, and the local project and model settings passed readback by 18:09 UTC.

At 18:10 UTC the installed ticket-plan approval command exited 2 with `approve: unreadable input: cannot read the checkpoint forms from contracts/checkpoints.v1.md`. The shell checker looks up the document relative to its installed script. The document existed in the source checkout and was absent from the expected installed location. The heartbeat, builder, review and merge were unreached.

Teardown finished at 18:11 UTC. The private repository was archived with zero open issues and pull requests. The final environment check passed and the native crontab matched its saved baseline.

## November 24, third run

The candidate, Packages run and installer inputs were the same as in the first November 24 run. Authenticated Git access to the fresh private repository passed before the rehearsal began. The Linux archive and manifest passed verification at 12:20 UTC. The installer activated the expected build four seconds later. The local project, personal GitHub identity and harness passed setup at 12:24 UTC. The confirmation request was verified at 12:25 UTC.

After the user confirmed the one-file design, the reply was saved and read back, and the updated record was pushed. At 12:57 UTC the installed confirmation helper exited 2 with `refused: exact reply is not saved`. A later GitHub read showed the exact reply at the pushed PR head. The failed invocation did not record the SHA it read. The request remained open, and the heartbeat, build, review and merge were unreached.

Teardown finished at 12:58 UTC. The private repository was archived with zero open issues or pull requests. The environment passed the final clean check and the native crontab matched its original contents.

## November 24, second run

The rerun used the same November 24 inputs listed below. The fresh Linux home passed the clean check. The private repository was created 5 seconds later, and the helper verified both Linux files after another 3 seconds. The installer activated the expected build and the CLI reported its sealed source. The local model list offered Claude Code.

Cloning the private repository then exited 128 because Git could not obtain a GitHub username. The rehearsal environment had an authenticated GitHub CLI but omitted its Git credential helper. A read-only Git lookup succeeded after registering that helper during diagnosis. The run stopped before first-fleet setup. The heartbeat, builder, review and merge were unreached.

Teardown finished 28 seconds after the clone failure. The final environment check passed, the private repository was archived with zero open issues or pull requests, and the crontab matched the saved baseline.

## November 24, first run

**Failed at first-fleet setup.** The corrected helper verified both Linux files. OpenWiz 0.1.1 installed and activated at the sealed source revision. GitHub's REST quota then ran out before the first fleet started.

| Input | Value |
| --- | --- |
| Candidate source | `7d84a578e94e8cdb338d80769d1e82e0cd1f067a` |
| Packages run | `45301203909` |
| Linux archive SHA-256 | `7893292759f06c29ecd5f508e6212a62e0e6e1f3d1776d8fa982baa96cf7a972` |
| WizSkills | `9ef6e13ff38c565b553a906d8e013e4eaef22f09` |
| Rehearsal helper | `e1b505a394aa2e93ff56683d4ce51d2bfce15cc0` |

| Step | Result and elapsed wall time |
| --- | --- |
| Initial checks and disposable repository | Clean environment verified. Created a private repository about 5 seconds later. |
| Staging | Verified the manifest and the archive in about 3 seconds. |
| Installation | Activated the sealed build in about 4 seconds. |
| Local setup | Listed a local Claude Code model, verified the personal GitHub login and merged the project settings. After about 2 minutes 36 seconds, setup reported that CloudRoom was unnecessary but could no longer read the GitHub identity or project. First-fleet continuation exited 5. A direct GitHub read returned HTTP 403 and the core quota showed zero requests remaining. |
| Heartbeat, builder, reviewer, merge, final clean check | Unreached. |
| Teardown | Closed the setup issue, archived the private repository and verified zero open issues and pull requests. The host crontab matched its original contents. Teardown checks finished about 3 minutes after the stop. |

## November 23

The November 23 rehearsal stopped at candidate staging, before install. The clean Linux first-fleet gate is open.

| Input | Value |
| --- | --- |
| Candidate source | `76e3292439fa69791ca839fbfa774889dd04837f` |
| Packages run | `45117811766` |
| Linux archive SHA-256 | `0992dd3ac4b26e7dced0e891f6926c39f9fdd97cc7c47a2764c0ab4501111c1a` |
| WizSkills | `9ef6e13ff38c565b553a906d8e013e4eaef22f09` |
| Rehearsal helper revision | `04b9b0ad39d5e3cfea99cb601bec1cda848d127c` |

| Check | Outcome |
| --- | --- |
| Initial clean check | Passed on x86-64 Linux with a fresh home. The host used Cronie. |
| Throwaway repository | Created private. Machine checks and creation took about 0.4 minutes combined. |
| Candidate staging | Failed after about 0.1 minutes. The helper selected a macOS checksum file from the same Packages run. Its Linux filter returned no checksum rows. The archive independently matched the sealed Linux digest. |
| Install and setup with the local host selected | Unreached |
| Heartbeat preview, installation and tick | Unreached |
| First pull request built, reviewed and merged | Unreached |
| Final clean check after fleet work | Unreached |
| Teardown | Archived the empty repository and verified the original crontab, about 0.5 minutes after failure. No agent had started. |

The initial terminal recorder consumed subsequent shell input during the first machine check. The remaining machine checks were run explicitly with their input closed. No product command ran in that recording.
