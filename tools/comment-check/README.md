# Comment check (#1816)

The checker for the [comments contract](../../contracts/comments.v1.md): CI fails a pull request that adds a comment outside the allowed kinds, and the count mode gives each cut its BEFORE and AFTER comment lines.

```sh
python3 -I tools/comment-check/check.py diff --base origin/main                  # this branch's added lines, as CI checks them
python3 -I tools/comment-check/check.py count --before origin/main crates/core/  # BEFORE and AFTER for one area
python3 -I tools/comment-check/test_check.py                                     # its proofs, on contracts/fixtures/comments/
python3 -I tools/comment-check/test_ci_step.py                                   # ci.yml's comment-check step, replayed on a synthetic pull request
```

Standard-library Python, one file, no dependencies. Other repositories carry `check.py` and the contract byte-identical; change them here first.
