# The Rust tests split across runners (#1266, X8 of spec #1256)

The Rust lane's selected tests, by the [CI selection record's](../../contracts/ci-selection.v1.md) ids (`rust:lib:<package>`, `rust:test:<target>`), build once and run as N shards. `shard.py` decides each shard's share from the plan and checks afterwards that every selected test ran exactly once.

```sh
python3 -I ci/shard/shard.py plan PLAN --shards N --times ci/shard/times.tsv
python3 -I ci/shard/shard.py share PLAN --shards N --shard K --times ci/shard/times.tsv
python3 -I ci/shard/shard.py check PLAN [RAN...]
python3 -I ci/shard/shard.py times LOG...
python3 -I ci/shard/test.py
```

| Command | Reads | Gives |
| --- | --- | --- |
| `plan` | The plan (refused unless the contract accepts it, by `ci/escapes/escapes.py`'s reader, the one X5's writer checks with), the most shards and the times | JSON on stdout: `seconds` (the longest shard's estimate), `unmeasured` (the selected tests with no time) and `shards`, each `{"shard", "tests", "seconds"}`, its tests longest first. A skipped Rust lane has none |
| `share` | The same, and a member's number | That member's tests, one a line; nothing for a member past the shards needed or a skipped lane |
| `check` | The plan, and each shard's record of the ids it ran, one a line | Exit 0 only when every selected Rust test ran exactly once and nothing else ran; otherwise exit 1, naming each test that never ran, ran more than once, or ran without being selected |
| `times` | The rust job's logs from CI | `times.tsv`'s rows: each test's libtest `finished in` totals summed in a log, the median over the logs |

**How many shards.** A setting per runner kind (the orchestrator on #1266, 2026-11-08), in `ci.yml`: the `rust` and `rust-export` jobs' matrix maps each `runs-on` label to its members, and a label it doesn't name gets one, so a paid runner (Namespace) never fans out; a traced or planted run keeps one, as those run the whole lane through `run.py`. GitHub fixes a matrix before its jobs start, so the setting lives there, not in a file a job reads. Each member asks `share` for its tests (N is the matrix's size); of up to N, the balancer uses the fewest shards that finish as soon as the most would, and a member past those runs nothing.

**In CI.** Each member runs `The Rust shard` (its share), then its tests: with one member, `run.py execute` as before; otherwise `ci/rust-tests.sh --only <its share>`. Only after they pass, `Record passed lane` keeps its share as `rust-ran-<attempt>-<member>`. The first member alone builds and lints and saves the caches. The `ci` job then runs `Every Rust test ran exactly once`: `check` over every member's record, and only then the Rust lane's receipt (`run.py stamp`), so a failed, cancelled or missing member, or a test in two shards or none, fails `ci`. Each member builds its own share from the cache `main` saves: no pull request writes anything another job reads.

**Balancing.** Longest first, each test to the least loaded shard (ties: the lower shard; equal times: by id). A test `times.tsv` doesn't time counts as its longest one and is named in `unmeasured`, so a new binary is never guessed short.

**The times.** `times.tsv` is the median over the 5 latest untraced green runs that ran every Rust test at once (its header names them and how they were picked). `times` reads traced `== trace: <id>` sections, `== rust-tests: <target>` sections, and the `crates` section by package (each library's `Running unittests src/lib.rs` line starts its package's tests; its `Doc-tests` come at the end). A log that times no Rust test, or one test twice, is refused. Refresh it with `times` over newer logs; `test.py` fails while any Rust test the tree has is unmeasured.

**Exit codes.** 0 done; 1 a plan, record, times file or log refused (why on stderr, nothing on stdout); 2 a bad command line.
