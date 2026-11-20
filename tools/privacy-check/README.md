# Privacy check

`check.py` is the read-only check of the [open development contract](../../contracts/open-development.v1.md)'s privacy rules. It never pushes, stages, fetches or writes. Python 3.11+ and Git only.

```sh
# a staged public directory (importers must pass --require-literals)
python3 -I tools/privacy-check/check.py --tree /tmp/staged-public --literals LIST --require-literals
# Git objects and a commit range, plus proposed pull request text, without checkout
python3 -I tools/privacy-check/check.py --repo PATH --git-tree HEAD --base origin/main --head HEAD \
  --title-file TITLE --body-file BODY
# proposed issue or pull request text alone
python3 -I tools/privacy-check/check.py --title-file TITLE --body-file BODY --literals LIST --require-literals
# offline proofs
python3 -I tools/privacy-check/test_check.py
sh .githooks/test.sh --fixtures-only
```

Inputs combine in one run. Exit 0 is no refusal, 1 a refusal, 2 bad arguments. Each refusal names its contract rule, input and line, never the matched text. A missing, empty or unreadable literals list refuses under `--require-literals`; each result says whether literals were used. Without `--base`, history is checked from the contract's public anchor; `--upstream REF` narrows it to the commits after the merge-base with an already published REF. Every commit's message, identities and tree are checked, so deleting a private file at the tip doesn't clear history.

Workflows are read as a safe YAML subset; anything it doesn't recognise refuses, and every job needs an allowlisted runner.

## Where it runs

- **CI:** the `privacy` check in `.github/workflows/privacy.yml`, on every pull request, merge group and push to `main` of the public repository.
- **Pre-push:** `git config core.hooksPath .githooks`; set `OPENWIZ_PRIVACY_LITERALS` to the literals file. The hook scans from the push destination's `main`, fetched from that URL when needed.
- **Importer, release and ticket mover** call it before they publish; they own what they carry.

It can't see named literals without the private list, and images, unquoted personal facts and quotations stay a reviewer's job.
