# OpenWiz 0.1.1 Linux rehearsal

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
