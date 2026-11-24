# #2787 approach note

Ticket LR15 of spec #2474: the receipt writer's follow-ups R1, R5 and R6 from #2718's re-check at `c758ea3`.

## Approach

- **R1.** `receipt.py` stops reading host configs from the worktree. It resolves `HEAD` once to a commit id (`git rev-parse --verify HEAD^{commit}`), lists that commit's tree for `kernel/live-rig/hosts/` and `kernel/live-rig/vps/hosts/` with `git ls-tree -z <commit>`, keeps only direct `*.json` entries of mode `100644` or `100755` and type `blob`, reads each by object id with `git cat-file blob <oid>`, parses the bytes with rig.py's duplicate-key hook and validates them with rig.py's host validation (`_valid`), so the trusted triples come from parsed blobs only. Every git call runs with `GIT_*` dropped from the environment, `--no-replace-objects`, `core.fsmonitor=false`, and only after `git rev-parse --show-toplevel` equals this checkout's root. The token, credential and private-id/UUID scans run first, unchanged.
- **R5.** Decoding a host config blob catches `RecursionError` (and `ValueError`, `UnicodeDecodeError`) and maps it to the fixed line `a tracked host config is not a valid host config`: exit 1, one stderr line, no stdout, nothing written.
- **R6.** The VPS integration test drops its inline copies of the five configs. The fixture checkout takes them from this repository's tracked `HEAD` blobs under `kernel/live-rig/vps/hosts/`, and the test asserts every `runs` entry of every such config yields a receipt whose eight header lines are exactly the expected ones. Small synthetic configs stay for the refusal cases.

## Threats

| Trick | Effect before | After |
| --- | --- | --- |
| `git update-index --assume-unchanged` on a tracked config, then a worktree edit | `git diff HEAD` hides the edit; the edited worktree file supplies a new trusted triple | the worktree is never read; only `HEAD`'s blob counts |
| `git update-index --skip-worktree` on a tracked config, then a worktree edit | same as above | same as above |
| a staged-but-uncommitted config (index only) | refused (diff shows it) | refused: the index is never read |
| a replaced object (`git replace <config blob> <other blob>`) | refused, since the diff then shows a change | `--no-replace-objects`: the original blob is read, so the replacement can't add a triple |
| an alternate `GIT_DIR`, `GIT_WORK_TREE`, `GIT_INDEX_FILE`, `GIT_OBJECT_DIRECTORY` or `GIT_ALTERNATE_OBJECT_DIRECTORIES` from the environment | dropped (`GIT_*` removed) | still dropped, and the top level must be this checkout |
| an outer repository that tracks this checkout as a subfolder | refused (top level differs) | still refused |
| a tracked symlink config, or a subfolder under a host folder | skipped | skipped: mode `120000` and type `tree` entries are not configs |
| a 1,500-level nested tracked config | `RecursionError` traceback with local paths | one fixed line, exit 1 |

## What the tests can and can't prove

- **Can:** in a synthetic fixture repository, each trick above (assume-unchanged, skip-worktree, staged-only, `git replace`, `GIT_DIR`/`GIT_WORK_TREE` from the environment, a too-deep config) can't make the receipt writer accept a triple outside `HEAD`'s committed blobs, and a committed config still can. The VPS test proves each tracked VPS config's runs entries make receipts with exact headers at the commit the test runs at.
- **Can't:** `HEAD` is the trust root. A local commit that adds a config is trusted, as before; the receipt does not tie `HEAD` to `driver_commit` or to `origin/main`, and review of that commit is outside this tool. An operator who rewrites `.git` itself (object files, `HEAD`, the repository config) controls what git returns; no in-process check fixes that. SHA-1 collisions in an alternate object store are out of scope. Tests run fixtures only, never a real host, with refusing stubs for 37 agent CLIs first on `PATH`.
