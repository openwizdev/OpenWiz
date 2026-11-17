# #1044 / #1060: a concurrent fork keeps the staged program busy

Only synthetic fixtures are used.

## Cause

`crates/service/src/update.rs::copy_file` opens, writes and fsyncs the staged
`openwiz-service` in the multithreaded service process. A child forked by
another thread during that window inherits the writable descriptor and keeps it
after the parent closes its copy (close-on-exec only acts at the child's exec).
The identity check's exec of the staged program then fails with `ETXTBSY`, and
a good merge is reported as `kept` at step `build`.

## Failing-first proof

`tests/service/t6_update.rs::a_concurrent_fork_cannot_keep_the_staged_program_busy`.
The gates are fakes; Git and the identity exec are real. A watcher thread stands
in for the concurrent fork: when it sees a writable descriptor for the staged
program in this process, it reopens it for writing and holds it until the
attempt ends. The candidate program is padded to 64 MiB, so its copy lasts long
enough for the watcher to see it. Nothing in the product or the gates is timed,
retried or slowed.

```sh
cargo test -p openwiz-service --test t6-update -- --exact a_concurrent_fork_cannot_keep_the_staged_program_busy
```

### Red, before the fix (base fe405cf)

10 of 10 runs failed at the claim's assertion (1 to 12 s each). One run:

```text

running 1 test
test a_concurrent_fork_cannot_keep_the_staged_program_busy ... FAILED

failures:

---- a_concurrent_fork_cannot_keep_the_staged_program_busy stdout ----

thread 'a_concurrent_fork_cannot_keep_the_staged_program_busy' panicked at crates/service/../../tests/service/t6_update.rs:977:5:
a good merge was not staged (writer inherited by a concurrent fork: true): Object {"at": Number(1000), "from": String("50d985238987d6fa6504aa3884ea06db4a88015c"), "outcome": Object {"reason": String("candidate build or acceptance command failed"), "state": String("kept"), "step": String("build")}, "to": String("530ac7ac76c1c2421335ffcebb68cede5f3553e2")}
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace
failed fixture: <synthetic-fixture>


failures:
    a_concurrent_fork_cannot_keep_the_staged_program_busy

test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 46 filtered out; finished in 1.07s
```

`strace -f -e trace=execve` on the same run shows the cause:

```text
execve("<synthetic-fixture>/state/service/builds/530ac7ac76c1c2421335ffcebb68cede5f3553e2/openwiz-service", [..., "--update-build"], ...) = -1 ETXTBSY (Text file busy)
```

## Earlier evidence (#1046's builder, carried from #1060's handoff)

An `LD_PRELOAD` probe forked a child at the parent's close of the staged writer
and kept that exact descriptor open. With it, the keeper
`a_passing_main_merge_is_staged_but_not_reported_as_running` failed at
`assert!(f.updater(&old).check(&state, 1000).unwrap())`. A same-artifact
control showed exec refused with `ETXTBSY` while the inherited writer was held,
and the same staged candidate running with the matching compiled identity once
it closed. The full probe and control are in #1060's comments.
