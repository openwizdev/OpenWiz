#!/bin/sh
set -eu
scope=--workspace
case "$#:${1:-}" in
  0:) ;;
  1:--targets-only) scope="-p openwiz-tests" ;;
  *) echo "usage: sh ci/rust-tests.sh [--targets-only]" >&2; exit 2 ;;
esac
root="${RUST_TESTS_ROOT:-}"
cg="$root/sys/fs/cgroup"
num() {
  case "$1" in '' | *[!0-9]* | ???????????????????*) return 1 ;; esac
}
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
out="$(mktemp -d)"
sampler=
cleanup() {
  [ -z "$sampler" ] || kill "$sampler" 2> /dev/null || true
  rm -rf "$out"
}
trap cleanup EXIT
trap 'cleanup; trap - EXIT HUP INT TERM; kill 0' HUP INT TERM

# SECURITY: never export this nonce or pass it to a command under test; a
# payload can print our public labels but cannot authenticate a control line.
unset rust_tests_nonce
rust_tests_nonce="$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')"
case "$rust_tests_nonce" in '' | *[!0-9a-f]*) exit 1 ;; esac
[ "${#rust_tests_nonce}" -eq 64 ] || exit 1
frame() { printf '\nrust-tests-frame:%s %s\n' "$rust_tests_nonce" "$*"; }
frame begin

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

echo "rust-tests: the fixture release openwiz, built once before the tests"
prebuild_began="$(date +%s)"
rc=0
cargo build --release --locked -p openwiz-tests --example openwiz || rc=$?
if [ "$rc" != 0 ]; then
  echo "rust-tests: the fixture release build exited $rc; no test was started" >&2
  exit "$rc"
fi
echo "rust-tests: the fixture release build took $(($(date +%s) - prebuild_began)) s"

finish() {
  rc="$1"
  peak_line
  frame end
  exit "$rc"
}

peak_line() {
  if [ -n "$start" ] && peak="$(cat "$out/peak")"; then
    frame "rust-tests: peak memory $(((peak - start) / 1048576)) MiB above the start (the cgroup's anon memory, sampled every 0.2 s)"
  else
    frame "rust-tests: peak memory not measured ($stat has no anon line to read)"
  fi
}
main_only="a_candidate_that_exits_without_readiness_rolls_back_to_the_running_old_build
a_failing_merge_is_kept_and_recorded_once_without_retrying_the_gate
a_passing_main_merge_is_staged_but_not_reported_as_running
a_real_candidate_must_confirm_readiness_before_selection_or_switched"
skip=
if [ "${GITHUB_EVENT_NAME:-}" = pull_request ] && [ "${GITHUB_BASE_REF:-}" = main ]; then
  skip=--exact
  for t in $main_only; do skip="$skip --skip $t"; done
  echo "rust-tests: a pull request to main: skipping the main-only proofs, which merge groups and main pushes run:"
  echo "$main_only" | sed 's/^/rust-tests:   /'
fi
why="$(room)" || why="the container's limits couldn't be read"
cpus="$(nproc 2> /dev/null || true)"
if [ -n "$why" ]; then
  frame "rust-tests: one command, cargo test --workspace: $why"
  frame "== rust-tests: cargo test $scope"
  rc=0
  began="$(date +%s)"
  # shellcheck disable=SC2086 # the skip arguments, split
  cargo test $scope --locked -- --test-threads=8 $skip || rc=$?
  frame "rust-tests: cargo test $scope exited $rc after $(($(date +%s) - began)) s"
  finish "$rc"
fi
frame "rust-tests: every target at once: $cpus CPUs by nproc, and the container allows 4 CPUs and 6 GiB or more"
threads=8
prep() { echo "rust-tests: $*" >&2; finish 1; }
# shellcheck disable=SC2086 # the scope, split
cargo test $scope --no-run --locked || prep "building the tests failed"
cargo metadata --no-deps --format-version 1 --locked > "$out/metadata.json" || prep "cargo metadata failed"
odd="$(jq -r '.packages[] | select(.name == "openwiz-tests") | .targets[] | select(.test and .kind != ["test"]) | .name' "$out/metadata.json")" || prep "cargo metadata's answer can't be read"
[ -z "$odd" ] || prep "openwiz-tests has a target this script doesn't run: $odd"
targets="$(jq -r '.packages[] | select(.name == "openwiz-tests") | .targets[] | select(.test and .kind == ["test"]) | .name' "$out/metadata.json")" || prep "cargo metadata's answer can't be read"
[ -n "$targets" ] || prep "no openwiz-tests targets in cargo metadata"
for t in $targets; do
  case "$t" in
    crates | *[!a-z0-9-]*) prep "unexpected target name '$t'" ;;
  esac
done

pids=
run() {
  name="$1"
  shift
  (if "$@" > "$out/$name.log" 2>&1; then echo 0; else echo "$?"; fi > "$out/$name.rc") &
  pids="$pids $!"
}
began="$(date +%s)"
calls_run=
if [ "$scope" = --workspace ]; then
  # shellcheck disable=SC2086 # the skip arguments, split
  run crates cargo test --workspace --exclude openwiz-tests --locked -- --test-threads="$threads" $skip
  calls_run=crates
fi
for t in $targets; do
  # shellcheck disable=SC2086 # the skip arguments, split (#1410)
  run "$t" cargo test -p openwiz-tests --locked --test "$t" -- --test-threads="$threads" $skip
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
