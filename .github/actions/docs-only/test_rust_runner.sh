#!/bin/sh
# Existing Rust runner proofs, moved intact from test.sh. Synthetic Cargo only.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$HERE/../../.."
fails=0
ok() { echo "ok   $*"; }
bad() { echo "FAIL $*"; fails=$((fails + 1)); }
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
# ci/rust-tests.sh --alongside (#1251): the rust job's two suites at once.
# A fake cargo and a fake skills suite each wait (up to 10 s) for the other
# to start, so each log says whether they really ran together. Either one
# failing fails the step; both logs come out whole, each under its label;
# without --alongside it runs the Rust tests alone, as before.
rt="$tmp/rust-tests"
mkdir -p "$rt/bin" "$rt/cg/sys/fs/cgroup/ci" "$rt/cg/proc/self"
: > "$rt/cg/sys/fs/cgroup/cgroup.controllers"
echo '0::/ci' > "$rt/cg/proc/self/cgroup"
cat > "$rt/bin/nproc" <<'EOF'
#!/bin/sh
echo "$FAKE_NPROC"
EOF
cat > "$rt/bin/cargo" <<'EOF'
#!/bin/sh
# #1260: the fixture release build, before anything else; logged apart, with
# its own outcome (PREBUILD_RC). Every call's kind goes to the order log.
case "$*" in
  "build --release --locked -p openwiz-tests --example openwiz")
    echo prebuild >> "$SYNC/order"
    echo "fake cargo: the release fixture built"
    exit "${PREBUILD_RC:-0}" ;;
esac
# FAKE_PREP breaks one preparation step of the every-target path (#1251, R1).
t='{"name":"checks","kind":["test"],"test":true}'
case "${FAKE_PREP:-}" in
  odd) t="$t"',{"name":"speed","kind":["bench"],"test":true}' ;;
  none) t= ;;
  badname) t='{"name":"Bad_Name","kind":["test"],"test":true}' ;;
esac
case "$*" in
  "metadata "*)
    [ "${FAKE_PREP:-}" != metadata ] || { echo "fake cargo: metadata failed" >&2; exit 1; }
    # FAKE_META (#432): a whole workspace's answer, for the selected runs.
    [ -z "${FAKE_META:-}" ] || { echo "$FAKE_META"; exit 0; }
    echo '{"packages":[{"name":"openwiz-tests","targets":['"$t"']}]}'; exit 0 ;;
  *--no-run*)
    [ "${FAKE_PREP:-}" != no-run ] || { echo "fake cargo: the build failed" >&2; exit 101; }
    exit 0 ;;
esac
echo "cargo $*" >> "$SYNC/cargo.calls"
echo test >> "$SYNC/order"
# R3 on #1291: the checks target's log is gone by the time it is read.
case "${FAKE_RM_LOG:-}:$*" in cargo:*"--test checks"*) rm -f "$(readlink /proc/$$/fd/1)" ;; esac
: > "$SYNC/cargo.up"
i=0
[ -z "${FAKE_NOWAIT:-}" ] || i=100
while [ ! -e "$SYNC/along.up" ] && [ "$i" -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
if [ -e "$SYNC/along.up" ]; then echo "fake cargo: ran beside the other suite"; else echo "fake cargo: ran alone"; fi
echo "fake cargo: last line"
exit "${CARGO_RC:-0}"
EOF
cat > "$rt/along.sh" <<'EOF'
: > "$SYNC/along.up"
echo along >> "$SYNC/order"
# R3 on #1291: its log is gone by the time it is read.
[ "${FAKE_RM_LOG:-}" != skills ] || rm -f "$(readlink /proc/$$/fd/1)"
i=0
while [ ! -e "$SYNC/cargo.up" ] && [ "$i" -lt 100 ]; do sleep 0.1; i=$((i + 1)); done
if [ -e "$SYNC/cargo.up" ]; then echo "fake skills: ran beside the other suite"; else echo "fake skills: ran alone"; fi
echo "fake skills: last line"
exit "${ALONG_RC:-0}"
EOF
chmod +x "$rt/bin/nproc" "$rt/bin/cargo"
# rust_tests NAME NPROC CARGO_RC ALONG_RC WANT_EXIT [ARGS...]: run it and
# keep its output in $rt/out.
rust_tests() {
  name="$1" n="$2" crc="$3" arc="$4" want="$5"; shift 5
  rm -rf "$rt/sync" && mkdir "$rt/sync"
  (cd "$ROOT" && PATH="$rt/bin:$PATH" FAKE_NPROC="$n" SYNC="$rt/sync" CARGO_RC="$crc" ALONG_RC="$arc" RUST_TESTS_ROOT="$rt/cg" sh ci/rust-tests.sh "$@" > "$rt/out" 2>&1)
  got=$?
  # These checks cover suite execution and human labels; the escape finder
  # separately proves the nonce framing on the unmodified output.
  sed -E 's/^rust-tests-frame:[0-9a-f]{64} //' "$rt/out" > "$rt/labels"
  mv "$rt/labels" "$rt/out"
  if { [ "$want" = 0 ] && [ "$got" = 0 ]; } || { [ "$want" != 0 ] && [ "$got" != 0 ]; }; then ok "rust-tests: $name: exit $got"; else bad "rust-tests: $name: exit $got, want $([ "$want" = 0 ] && echo 0 || echo non-zero)"; fi
}
# has NAME TEXT...: each line is in the output, exactly once.
has() {
  name="$1"; shift
  for line in "$@"; do
    c="$(grep -cxF "$line" "$rt/out")"
    if [ "$c" = 1 ]; then ok "rust-tests: $name: '$line'"; else bad "rust-tests: $name: '$line' $c times: $(tr '\n' '|' < "$rt/out" | cut -c1-600)"; fi
  done
}
# labelled NAME LABEL LINE: LINE comes after its LABEL line, in that suite's
# own section (no other label between them).
labelled() {
  if awk -v label="$2" -v line="$3" '
    /^== rust-tests: / { cur = $0 }
    $0 == line { found = (cur == label) }
    END { exit !found }' "$rt/out"; then ok "rust-tests: $1: '$3' under '$2'"; else bad "rust-tests: $1: '$3' is not under '$2'"; fi
}
# prebuilt NAME: the release fixture was built once, before any test or
# the other suite started (#1260).
prebuilt() {
  if [ "$(grep -cx prebuild "$rt/sync/order" 2> /dev/null)" = 1 ] && [ "$(head -n 1 "$rt/sync/order")" = prebuild ]; then ok "rust-tests: $1: the release fixture first, once"; else bad "rust-tests: $1: not the release fixture first, once: $(tr '\n' '|' < "$rt/sync/order" 2> /dev/null)"; fi
}
SKILLS_LABEL="== rust-tests: the skills' tests"
for mode in 2 8; do
  case "$mode" in 2) m="one command" ;; 8) m="every target at once" ;; esac
  for case in "both pass:0:0:0" "cargo fails:101:0:1" "the skills fail:0:3:1" "both fail:101:3:1"; do
    IFS=: read -r cname crc arc want <<EOF
$case
EOF
    rust_tests "$m, $cname" "$mode" "$crc" "$arc" "$want" --alongside "the skills' tests" sh "$rt/along.sh"
    prebuilt "$m, $cname"
    has "$m, $cname" "fake skills: ran beside the other suite" "fake skills: last line" "$SKILLS_LABEL"
    labelled "$m, $cname" "$SKILLS_LABEL" "fake skills: last line"
    if grep -qxF "fake cargo: ran alone" "$rt/out" || ! grep -qxF "fake cargo: ran beside the other suite" "$rt/out"; then bad "rust-tests: $m, $cname: cargo did not run beside the skills"; else ok "rust-tests: $m, $cname: cargo ran beside the skills"; fi
    if [ "$arc" = 0 ]; then has "$m, $cname" "rust-tests: the skills' tests: ok"; else has "$m, $cname" "rust-tests: the skills' tests: FAILED (exit $arc)"; fi
    if [ "$(grep -cE "^rust-tests: the skills' tests took [0-9]+ s$" "$rt/out")" = 1 ]; then ok "rust-tests: $m, $cname: the skills' time"; else bad "rust-tests: $m, $cname: no one line with the skills' time"; fi
  done
done
# R1 on #1291: a preparation step of the every-target path that fails after
# the skills started still waits for them, prints their log whole under its
# label with its line, and fails the step. The skills here wait 10 s for a
# cargo that never comes, so they end well after the failure.
for prep in no-run metadata odd none badname; do
  export FAKE_PREP="$prep"
  rust_tests "every target at once, preparation fails ($prep)" 8 0 0 1 --alongside "the skills' tests" sh "$rt/along.sh"
  has "preparation fails ($prep)" "$SKILLS_LABEL" "fake skills: last line" "rust-tests: the skills' tests: ok"
  labelled "preparation fails ($prep)" "$SKILLS_LABEL" "fake skills: last line"
  if [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: preparation fails ($prep): no test ran"; else bad "rust-tests: preparation fails ($prep): tests ran"; fi
done
unset FAKE_PREP
# #1260: a failed release fixture build fails the step with its own status,
# on either path, before any test and before the other suite starts.
export PREBUILD_RC=7
for mode in 2 8; do
  rust_tests "$mode CPUs, the release fixture fails" "$mode" 0 0 7 --alongside "the skills' tests" sh "$rt/along.sh"
  if [ "$got" = 7 ]; then ok "rust-tests: $mode CPUs, the release fixture fails: its own exit 7"; else bad "rust-tests: $mode CPUs, the release fixture fails: exit $got, not 7"; fi
  has "$mode CPUs, the release fixture fails" "rust-tests: the fixture release build exited 7; no test was started"
  if [ "$(cat "$rt/sync/order")" = prebuild ] && [ ! -e "$rt/sync/along.up" ] && [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: $mode CPUs, the release fixture fails: no test, no other suite"; else bad "rust-tests: $mode CPUs, the release fixture fails: something ran after it: $(tr '\n' '|' < "$rt/sync/order")"; fi
done
unset PREBUILD_RC
# #1260, Q3: the one-command path runs 8 test threads, before any skips.
rust_tests "one command, 8 test threads" 2 0 0 0
if [ "$(grep -c '^cargo test --workspace --locked -- --test-threads=8\( \|$\)' "$rt/sync/cargo.calls")" = 1 ] && [ "$(wc -l < "$rt/sync/cargo.calls")" -eq 1 ]; then ok "rust-tests: one command: --test-threads=8 first"; else bad "rust-tests: one command: not --test-threads=8 first: $(tr '\n' '|' < "$rt/sync/cargo.calls")"; fi
prebuilt "one command, 8 test threads"
# R3 on #1291: a log that can't be read fails the step, whatever the suites'
# own statuses, and the other suite's log still comes out whole.
export FAKE_RM_LOG=skills
for mode in 2 8; do
  rust_tests "$mode CPUs, the skills' log can't be read" "$mode" 0 0 1 --alongside "the skills' tests" sh "$rt/along.sh"
  has "$mode CPUs, the skills' log can't be read" "rust-tests: the skills' tests: its log can't be read"
  # One fake Rust call one way, two (crates, checks) the other: each whole.
  c="$(grep -cxF "fake cargo: last line" "$rt/out")"
  if [ "$c" = "$([ "$mode" = 2 ] && echo 1 || echo 2)" ]; then ok "rust-tests: $mode CPUs, the skills' log can't be read: the Rust logs whole"; else bad "rust-tests: $mode CPUs, the skills' log can't be read: 'fake cargo: last line' $c times"; fi
done
export FAKE_RM_LOG=cargo
rust_tests "a Rust target's log can't be read" 8 0 0 1 --alongside "the skills' tests" sh "$rt/along.sh"
has "a Rust target's log can't be read" "rust-tests: checks: its log can't be read" "fake skills: last line" "rust-tests: the skills' tests: ok"
labelled "a Rust target's log can't be read" "$SKILLS_LABEL" "fake skills: last line"
unset FAKE_RM_LOG
rust_tests "one command, no --alongside: the Rust tests alone" 2 0 0 0
has "no --alongside" "fake cargo: ran alone" "fake cargo: last line"
if grep -q "skills" "$rt/out"; then bad "rust-tests: no --alongside: it mentions the skills"; else ok "rust-tests: no --alongside: no second suite"; fi
rust_tests "no --alongside, cargo fails" 2 101 0 1
rust_tests "an --alongside command that isn't there fails" 2 0 0 1 --alongside "the skills' tests" "$rt/nothing-here"
has "a missing command" "rust-tests: the skills' tests: FAILED (exit 127)"
rust_tests "--alongside with no command is refused" 2 0 0 1 --alongside "the skills' tests"
rust_tests "an unknown argument is refused" 2 0 0 1 --along "x" true
if [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: a refused command line runs no cargo"; else bad "rust-tests: a refused command line ran cargo"; fi

# ci/rust-tests.sh --only IDS (#432): the selected Rust tests only, by the
# CI selection record's ids. Every target at once runs a crates call for
# just the selected packages (none if none is selected) and one call per
# selected target; one command runs one call for the packages and one for
# the targets. An id of another kind, an empty list, or a target cargo
# doesn't list fails before any test runs. Without --only, nothing changes
# (the cases above).
# Outside a pull request's run: CI's own event would add the main-only skips.
saved_event="${GITHUB_EVENT_NAME-}" saved_base="${GITHUB_BASE_REF-}"
unset GITHUB_EVENT_NAME GITHUB_BASE_REF
export FAKE_NOWAIT=1
export FAKE_META='{"packages":[{"name":"openwiz-core","targets":[{"name":"openwiz_core","kind":["lib"],"test":true}]},{"name":"openwiz-tests","targets":[{"name":"checks","kind":["test"],"test":true},{"name":"proof","kind":["test"],"test":true},{"name":"web-api","kind":["test"],"test":true}]}]}'
# calls NAME WANT...: exactly these cargo test calls, in any order.
calls() {
  name="$1"; shift
  want="$(printf '%s\n' "$@" | sort)"
  got="$(sort "$rt/sync/cargo.calls" 2> /dev/null)"
  if [ "$got" = "$want" ]; then ok "rust-tests: $name: the calls"; else bad "rust-tests: $name: calls [$(echo "$got" | tr '\n' '|')], want [$(echo "$want" | tr '\n' '|')]"; fi
}
rust_tests "--only, every target at once" 8 0 0 0 --only "rust:lib:openwiz-core rust:test:checks"
calls "--only, every target at once" "cargo test --locked -p openwiz-core -- --test-threads=8" \
  "cargo test -p openwiz-tests --locked --test checks -- --test-threads=8"
has "--only, every target at once" "rust-tests: the selected tests only (#432): rust:lib:openwiz-core rust:test:checks" "rust-tests: crates: ok" "rust-tests: checks: ok"
rust_tests "--only, a target alone" 8 0 0 0 --only "rust:test:web-api"
calls "--only, a target alone" "cargo test -p openwiz-tests --locked --test web-api -- --test-threads=24"
rust_tests "--only, with the skills beside" 8 0 0 0 --only "rust:test:checks" --alongside "the skills' tests" sh "$rt/along.sh"
has "--only, with the skills beside" "rust-tests: the skills' tests: ok" "rust-tests: checks: ok"
rust_tests "--only, one command" 2 0 0 0 --only "rust:lib:openwiz-core rust:test:checks rust:test:proof"
calls "--only, one command" "cargo test --locked -p openwiz-core --" \
  "cargo test --locked -p openwiz-tests --test checks --test proof --"
rust_tests "--only, one command, a target fails" 2 101 0 1 --only "rust:test:checks"
rust_tests "--only, a target cargo doesn't list" 8 0 0 1 --only "rust:test:checks rust:test:nope"
if [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: --only, an unknown target: no test ran"; else bad "rust-tests: --only, an unknown target: tests ran"; fi
for bad_only in "" "web:unit:api" "rust:test:" "rust:lib:a/b" "all" "rust:test:checks  rust:test:proof"; do
  rust_tests "--only '$bad_only' is refused" 2 0 0 1 --only "$bad_only"
  if [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: --only '$bad_only': no cargo"; else bad "rust-tests: --only '$bad_only': cargo ran"; fi
done
unset FAKE_NOWAIT FAKE_META
# --can-run-at-once (#432, review R3 on #1579): the at-once rule alone,
# for the tracer; it runs no cargo.
rust_tests "--can-run-at-once, 8 CPUs, no limits" 8 0 0 0 --can-run-at-once
has "--can-run-at-once, 8 CPUs" "rust-tests: every target may run at once here"
rust_tests "--can-run-at-once, 2 CPUs" 2 0 0 1 --can-run-at-once
has "--can-run-at-once, 2 CPUs" "rust-tests: not every target at once here: 2 CPUs by nproc, fewer than 4"
echo "200000 100000" > "$rt/cg/sys/fs/cgroup/ci/cpu.max"
rust_tests "--can-run-at-once, a 2-CPU limit" 8 0 0 1 --can-run-at-once
echo "max 100000" > "$rt/cg/sys/fs/cgroup/ci/cpu.max"
echo "1073741824" > "$rt/cg/sys/fs/cgroup/ci/memory.max"
rust_tests "--can-run-at-once, a 1 GiB limit" 8 0 0 1 --can-run-at-once
echo "nonsense" > "$rt/cg/sys/fs/cgroup/ci/memory.max"
rust_tests "--can-run-at-once, a limit it can't read" 8 0 0 1 --can-run-at-once
rm -f "$rt/cg/sys/fs/cgroup/ci/cpu.max" "$rt/cg/sys/fs/cgroup/ci/memory.max"
if [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: --can-run-at-once runs no cargo"; else bad "rust-tests: --can-run-at-once ran cargo"; fi
rust_tests "--can-run-at-once with another argument is refused" 8 0 0 1 --can-run-at-once --only rust:test:checks
[ -z "$saved_event" ] || export GITHUB_EVENT_NAME="$saved_event"
[ -z "$saved_base" ] || export GITHUB_BASE_REF="$saved_base"

if [ "$fails" -ne 0 ]; then echo "$fails failed"; exit 1; fi
echo "all ok"
