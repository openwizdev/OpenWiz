#!/bin/sh
# The rust job's tests (#429, spec #330, K12): exactly the tests
# `cargo test --workspace` runs, but every test target at once instead of one
# after another. On a pull request it skips the few main-only proofs
# named below (#1253). They mostly wait (servers, fakes, child processes, the
# 15-second timeout proofs), so the step lasts about as long as its longest
# target, not the sum: 133.9 to 44.5 s, peak about 320 MiB extra
# (private/evidence/infra-ci-scale/rust-tests/REPORT.md).
#
# It builds every test first (`--no-run`), then starts at once: the unit and
# doc tests of every other crate, in one cargo call, and one cargo call for
# each openwiz-tests target, read from `cargo metadata`, so a new target is
# never missed. 8 test threads each, web-api 24: it mostly waits, and its
# reader retries an interrupted read (tests/web-api/http.rs). Each call
# writes its own log; once all have finished, each log is printed whole, one
# after another, then one line per call and the peak memory. Any failure, or
# a call that leaves no exit status, fails the step.
#
# Only where it has room: at least 4 CPUs by `nproc`, and a container whose
# limits (cgroup v2, at its own level and every level above) allow at least 4
# CPUs (`cpu.max`) and 6 GiB (`memory.max`), or set none. On GitHub's 2-CPU
# runners the targets at once took 706 s against about 250 s one after
# another; on constrained runners where `nproc` exceeds the CPU limit,
# the tests' own release builds ran out of memory (#429, ruling A,
# 2026-11-05). Otherwise, or if a limit can't be read or understood, it runs
# `cargo test --workspace --locked` once instead, with 8 test threads (#1260),
# and exits with its status.
#
# With `--alongside NAME COMMAND...` (#1251), it also runs COMMAND, from the
# start to the end, beside the Rust tests (the rust job's skills' tests, so
# the step lasts as long as the longer of the two, not their sum). Its output
# goes to its own log, printed whole under `== rust-tests: NAME` once both
# have finished, then a line saying whether it passed. Either failing fails
# the step.
#
# With `--only IDS` (#432, K15), it runs only the tests the selector picked
# (ci/select/), by the CI selection record's ids, space-separated:
# `rust:lib:<package>` runs `cargo test -p <package>` (every test of that
# crate) and `rust:test:<target>` one openwiz-tests target. Every target at
# once: one crates call for just the selected packages (none if none), and
# one call per selected target. One command: one call for the packages and
# one for the targets, one after the other. An id of another kind, an empty
# list or a target cargo metadata doesn't list fails before any test runs.
# Where every target may run at once, --only builds just the selected
# packages and targets first, not the whole workspace: a shard of the Rust
# lane (#1266, ci/shard/) builds only its own share.
# Without --only, every test runs, as above.
#
# `--can-run-at-once` (#432) runs nothing: it applies the rule above (4 CPUs
# by nproc, and limits that allow 4 CPUs and 6 GiB or set none) and exits 0
# when every target may run at once, else prints why and exits 1. CI asks it
# before tracing the tests, which runs them at once too.
#
# Run from the repository's root:
#   sh ci/rust-tests.sh [--only IDS] [--alongside NAME COMMAND...]
#   sh ci/rust-tests.sh --can-run-at-once
# By hand, `cargo test --workspace` runs the same tests (AGENTS.md).
set -eu
usage() { echo "usage: sh ci/rust-tests.sh [--only IDS] [--alongside NAME COMMAND...]" >&2; exit 2; }
only= only_set= at_once_check=
if [ "$#:${1:-}" = 1:--can-run-at-once ]; then
  at_once_check=1
  shift
fi
if [ "${1:-}" = --only ]; then
  [ "$#" -ge 2 ] || usage
  only="$2" only_set=1
  shift 2
fi
# The selection: each id once, of a Rust kind, with a plain name; the
# packages and the targets apart.
sel_pkgs= sel_targets=
if [ -n "$only_set" ]; then
  [ -n "$only" ] || usage
  case "$only" in *"  "* | " "* | *" " | *'
'*) usage ;; esac
  for id in $only; do
    case "$id" in
      rust:lib:?*) name="${id#rust:lib:}" ;;
      rust:test:?*) name="${id#rust:test:}" ;;
      *) usage ;;
    esac
    case "$name" in *[!A-Za-z0-9._-]*) usage ;; esac
    case "$id" in
      rust:lib:*) sel_pkgs="$sel_pkgs $name" ;;
      *) sel_targets="$sel_targets $name" ;;
    esac
  done
fi
along_name=
case "$#:${1:-}" in
  0:) ;;
  *:--alongside)
    [ "$#" -ge 3 ] || usage
    along_name="$2"
    case "$along_name" in '' | *'
'*) usage ;; esac
    shift 2
    ;;
  *) usage ;;
esac
# Tests only: a fake /sys/fs/cgroup and /proc/self/cgroup under this folder.
root="${RUST_TESTS_ROOT:-}"
cg="$root/sys/fs/cgroup"
# num VALUE: a plain whole number the shell's arithmetic can hold.
num() {
  case "$1" in '' | *[!0-9]* | ???????????????????*) return 1 ;; esac
}
# Why the container's limits rule out the targets at once, or nothing.
limits() {
  [ -f "$cg/cgroup.controllers" ] || { echo "no cgroup v2 at /sys/fs/cgroup"; return; }
  rel="$(sed -n 's/^0:://p' "$root/proc/self/cgroup" 2> /dev/null)" || rel=
  case "$rel" in
    /*) ;;
    *) echo "no cgroup v2 path in /proc/self/cgroup"; return ;;
  esac
  case "$rel/" in */../* | */./*) echo "an odd cgroup path '$rel'"; return ;; esac
  case "$rel" in *//*) echo "an odd cgroup path '$rel'"; return ;; esac
  [ "$rel" != / ] || rel=
  dir="$cg$rel"
  [ -d "$dir" ] || { echo "cgroup '$rel' isn't under /sys/fs/cgroup"; return; }
  set -f
  while :; do
    at="${dir#"$cg"}"
    if [ -e "$dir/cpu.max" ]; then
      v="$(cat "$dir/cpu.max" 2> /dev/null)" || { echo "${at}/cpu.max can't be read"; return; }
      # shellcheck disable=SC2086 # its two fields
      set -- $v
      if [ $# != 2 ] || ! num "$2" || [ "$2" = 0 ] || { [ "$1" != max ] && ! num "$1"; }; then
        echo "${at}/cpu.max is '$v'"
        return
      fi
      [ "$1" = max ] || [ "$1" -ge $((4 * $2)) ] || { echo "${at}/cpu.max allows $1/$2 CPUs, fewer than 4"; return; }
    fi
    if [ -e "$dir/memory.max" ]; then
      v="$(cat "$dir/memory.max" 2> /dev/null)" || { echo "${at}/memory.max can't be read"; return; }
      [ "$v" = max ] || num "$v" || { echo "${at}/memory.max is '$v'"; return; }
      [ "$v" = max ] || [ "$v" -ge 6442450944 ] || { echo "${at}/memory.max is $((v / 1048576)) MiB, under 6 GiB"; return; }
    fi
    [ "$dir" != "$cg" ] || break
    dir="${dir%/*}"
  done
}
# Why the targets can't all run at once here, or nothing.
room() {
  cpus="$(nproc 2> /dev/null || true)"
  if ! num "$cpus"; then
    echo "nproc gave no CPU count ('$cpus')"
  elif [ "$cpus" -lt 4 ]; then
    echo "$cpus CPUs by nproc, fewer than 4"
  else
    limits || echo "the container's limits couldn't be read"
  fi
}
if [ -n "$at_once_check" ]; then
  why="$(room)" || why="the room couldn't be read"
  if [ -z "$why" ]; then echo "rust-tests: every target may run at once here"; exit 0; fi
  echo "rust-tests: not every target at once here: $why"
  exit 1
fi
out="$(mktemp -d)"
sampler=
cleanup() {
  [ -z "$sampler" ] || kill "$sampler" 2> /dev/null || true
  rm -rf "$out"
}
trap cleanup EXIT
# A signal stops every test this started too: the whole process group.
trap 'cleanup; trap - EXIT HUP INT TERM; kill 0' HUP INT TERM

# Private framing for the escape finder. Never export this nonce or pass it
# to a command under test. Payloads can print our public labels, but cannot
# authenticate a control line. A leading newline keeps unterminated output
# from swallowing the next boundary. Missing/foreign frames fail closed.
unset rust_tests_nonce
rust_tests_nonce="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
case "$rust_tests_nonce" in '' | *[!0-9a-f]*) exit 1 ;; esac
[ "${#rust_tests_nonce}" -eq 64 ] || exit 1
frame() { printf '\nrust-tests-frame:%s %s\n' "$rust_tests_nonce" "$*"; }
frame begin

# Peak memory, for the record (#429): the cgroup's anonymous memory, sampled
# every 0.2 s from here to the end (so the builds too, either way), above
# where it started. Not every runner has it to read; then it says so.
stat="$cg/memory.stat"
anon() { awk '$1 == "anon" { print $2; exit }' "$stat" 2> /dev/null; }
start="$(anon || true)"
case "$start" in
  '' | *[!0-9]*) start= ;;
  *)
    echo "$start" > "$out/peak"
    (
      peak="$start"
      while :; do
        now="$(anon || true)"
        case "$now" in '' | *[!0-9]*) ;; *) [ "$now" -le "$peak" ] || { peak="$now"; echo "$peak" > "$out/peak"; } ;; esac
        sleep 0.2
      done
    ) &
    sampler=$!
    ;;
esac

# The fixture release `openwiz` several test binaries run (P10's, and the
# subprocess proofs'), built once here before any test starts, on either
# path (#1260): each test's own `cargo build --release` of it is then a
# no-op, so no test binary's time includes the build. It comes before the
# other suite starts, so a failed build starts no test at all. Its memory is
# in the peak below. Its lines are plain output, not control frames.
echo "rust-tests: the fixture release openwiz, built once before the tests"
prebuild_began="$(date +%s)"
rc=0
cargo build --release --locked -p openwiz-tests --example openwiz || rc=$?
if [ "$rc" != 0 ]; then
  echo "rust-tests: the fixture release build exited $rc; no test was started" >&2
  exit "$rc"
fi
echo "rust-tests: the fixture release build took $(($(date +%s) - prebuild_began)) s"

# The other suite (#1251), started now so it runs beside every Rust build
# and test below, and counts in the peak memory.
along=
if [ -n "$along_name" ]; then
  frame "rust-tests: $along_name, beside the Rust tests: $*"
  (
    s="$(date +%s)"
    if "$@" > "$out/alongside.log" 2>&1; then echo 0; else echo "$?"; fi > "$out/alongside.rc"
    echo $(($(date +%s) - s)) > "$out/alongside.took"
  ) &
  along=$!
fi
# finish RC: wait for the other suite, print its log whole under its label
# and its line, then the peak memory, and exit: RC, or 1 if it failed.
finish() {
  rc="$1"
  if [ -n "$along" ]; then
    wait "$along" || true
    frame "== rust-tests: $along_name"
    # A log that can't be read fails the step (R3 on #1291): it is not the
    # whole log the step promises, whatever the suite's own status.
    cat "$out/alongside.log" || { frame "rust-tests: $along_name: its log can't be read"; [ "$rc" != 0 ] || rc=1; }
    status="$(cat "$out/alongside.rc" 2> /dev/null || true)"
    frame "rust-tests: $along_name took $(cat "$out/alongside.took" 2> /dev/null || echo '?') s"
    if [ "$status" = 0 ]; then
      frame "rust-tests: $along_name: ok"
    else
      frame "rust-tests: $along_name: FAILED (exit ${status:-unknown})"
      [ "$rc" != 0 ] || rc=1
    fi
  fi
  peak_line
  frame end
  exit "$rc"
}

# The peak memory line, both ways (#429: AC2 records it on every run).
peak_line() {
  if [ -n "$start" ] && peak="$(cat "$out/peak")"; then
    frame "rust-tests: peak memory $(((peak - start) / 1048576)) MiB above the start (the cgroup's anon memory, sampled every 0.2 s)"
  else
    frame "rust-tests: peak memory not measured ($stat has no anon line to read)"
  fi
}
# Main-only proofs (#1253): each runs the whole fixed update gate (fmt,
# clippy, build, test and a release build) on a fresh clone of a synthetic
# product, 40 to 112 s each on constrained runners, about 300 s of t6_update's 372
# (private/evidence/ci-hotspot-t6-update/). Only a pull request to main skips
# them, by exact name; every push to main, the nightly run, a merge group, a
# pull request to release-*, any other event and a run by hand run every
# test. Every cargo test call gets the same skips, both ways (#1410:
# ci/test_rust_tests.py). A renamed one just runs on pull requests again.
main_only="a_candidate_that_exits_without_readiness_rolls_back_to_the_running_old_build
a_failing_merge_is_kept_and_recorded_once_without_retrying_the_gate
a_passing_main_merge_is_staged_but_not_reported_as_running
a_real_candidate_must_confirm_readiness_before_selection_or_switched"
skip=
if [ "${GITHUB_EVENT_NAME:-}" = pull_request ] && [ "${GITHUB_BASE_REF:-}" = main ]; then
  skip=--exact
  for t in $main_only; do skip="$skip --skip $t"; done
  echo "rust-tests: a pull request to main: skipping the main-only proofs, which main pushes and the nightly run run:"
  echo "$main_only" | sed 's/^/rust-tests:   /'
fi
why="$(room)" || why="the container's limits couldn't be read"
cpus="$(nproc 2> /dev/null || true)"
[ -z "$only_set" ] || echo "rust-tests: the selected tests only (#432): $only"
if [ -n "$why" ] && [ -n "$only_set" ]; then
  echo "rust-tests: one command each for the selected packages and targets: $why"
  rc=0
  began="$(date +%s)"
  if [ -n "$sel_pkgs" ]; then
    echo "== rust-tests: the selected packages:$sel_pkgs"
    # shellcheck disable=SC2086 # the packages and the skip arguments, split
    cargo test --locked $(for p in $sel_pkgs; do printf -- '-p %s ' "$p"; done) -- $skip || rc=$?
  fi
  if [ -n "$sel_targets" ]; then
    echo "== rust-tests: the selected targets:$sel_targets"
    t_rc=0
    # shellcheck disable=SC2086 # the targets and the skip arguments, split
    cargo test --locked -p openwiz-tests $(for t in $sel_targets; do printf -- '--test %s ' "$t"; done) -- $skip || t_rc=$?
    [ "$rc" != 0 ] || rc="$t_rc"
  fi
  echo "rust-tests: the selected tests exited $rc after $(($(date +%s) - began)) s"
  finish "$rc"
fi
if [ -n "$why" ]; then
  frame "rust-tests: one command, cargo test --workspace: $why"
  frame "== rust-tests: cargo test --workspace"
  rc=0
  began="$(date +%s)"
  # The test binaries still run one after another, but each with 8 test
  # threads instead of one per CPU (#1260, Q3): their cases mostly wait on
  # child processes, polls and fsyncs, so on constrained runners 8 at once
  # finish about twice as fast; the at-once path below already gives each
  # target 8. The mode line above keeps its words (ci/escapes reads them).
  # shellcheck disable=SC2086 # the skip arguments, split
  cargo test --workspace --locked -- --test-threads=8 $skip || rc=$?
  frame "rust-tests: cargo test --workspace exited $rc after $(($(date +%s) - began)) s"
  finish "$rc"
fi
frame "rust-tests: every target at once: $cpus CPUs by nproc, and the container allows 4 CPUs and 6 GiB or more"
threads=8
web_api_threads=24
# From here on a failure goes through finish (R1 on #1291), so the skills'
# tests started above are still waited for and their log printed.
prep() { echo "rust-tests: $*" >&2; finish 1; }
if [ -n "$only_set" ]; then
  # A shard (#1266), or a selected run, builds only its own tests: the
  # selected packages, then the selected targets, as the one-command path
  # runs them.
  if [ -n "$sel_pkgs" ]; then
    # shellcheck disable=SC2046 # the packages, split
    cargo test --locked $(for p in $sel_pkgs; do printf -- '-p %s ' "$p"; done) --no-run || prep "building the selected packages' tests failed"
  fi
  if [ -n "$sel_targets" ]; then
    # shellcheck disable=SC2046 # the targets, split
    cargo test --locked -p openwiz-tests $(for t in $sel_targets; do printf -- '--test %s ' "$t"; done) --no-run || prep "building the selected targets failed"
  fi
else
  cargo test --workspace --no-run --locked || prep "building the tests failed"
fi
cargo metadata --no-deps --format-version 1 --locked > "$out/metadata.json" || prep "cargo metadata failed"
# openwiz-tests holds only integration tests; any other target of it that
# tests would run is one this script doesn't know (fail closed).
odd="$(jq -r '.packages[] | select(.name == "openwiz-tests") | .targets[] | select(.test and .kind != ["test"]) | .name' "$out/metadata.json")" || prep "cargo metadata's answer can't be read"
[ -z "$odd" ] || prep "openwiz-tests has a target this script doesn't run: $odd"
targets="$(jq -r '.packages[] | select(.name == "openwiz-tests") | .targets[] | select(.test and .kind == ["test"]) | .name' "$out/metadata.json")" || prep "cargo metadata's answer can't be read"
[ -n "$targets" ] || prep "no openwiz-tests targets in cargo metadata"
for t in $targets; do
  case "$t" in
    crates | *[!a-z0-9-]*) prep "unexpected target name '$t'" ;;
  esac
done
# --only (#432): the selected targets, each one cargo lists.
if [ -n "$only_set" ]; then
  for t in $sel_targets; do
    printf '%s\n' $targets | grep -qxF "$t" || prep "the selected target '$t' is not an openwiz-tests target"
  done
  targets="$sel_targets"
fi

# run NAME COMMAND...: in the background, its output to NAME.log and its exit
# status to NAME.rc.
pids=
run() {
  name="$1"
  shift
  (if "$@" > "$out/$name.log" 2>&1; then echo 0; else echo "$?"; fi > "$out/$name.rc") &
  pids="$pids $!"
}
began="$(date +%s)"
calls_run=
if [ -z "$only_set" ]; then
  # shellcheck disable=SC2086 # the skip arguments, split
  run crates cargo test --workspace --exclude openwiz-tests --locked -- --test-threads="$threads" $skip
  calls_run=crates
elif [ -n "$sel_pkgs" ]; then
  # shellcheck disable=SC2046,SC2086 # the packages and the skip arguments, split
  run crates cargo test --locked $(for p in $sel_pkgs; do printf -- '-p %s ' "$p"; done) -- --test-threads="$threads" $skip
  calls_run=crates
fi
for t in $targets; do
  n="$threads"
  [ "$t" != web-api ] || n="$web_api_threads"
  # shellcheck disable=SC2086 # the skip arguments, split (#1410)
  run "$t" cargo test -p openwiz-tests --locked --test "$t" -- --test-threads="$n" $skip
done
for p in $pids; do wait "$p" || true; done
took=$(($(date +%s) - began))

rc=0
for name in $calls_run $targets; do
  frame "== rust-tests: $name"
  cat "$out/$name.log" || { frame "rust-tests: $name: its log can't be read"; rc=1; }
done
for name in $calls_run $targets; do
  status="$(cat "$out/$name.rc" 2> /dev/null || true)"
  if [ "$status" = 0 ]; then
    frame "rust-tests: $name: ok"
  else
    frame "rust-tests: $name: FAILED (exit ${status:-unknown})"
    rc=1
  fi
done
frame "rust-tests: every target at once took ${took} s"
finish "$rc"
