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
# ci/rust-tests.sh on a fake cargo: a failure in a
# preparation step, the fixture release build or a test always fails the
# step, and --only runs exactly the selected tests (#1152 kept these cases).
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
echo "fake cargo: last line"
exit "${CARGO_RC:-0}"
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
# R1 on #1291: a preparation step of the every-target path that fails fails
# the step, and no test runs.
for prep in no-run metadata odd none badname; do
  export FAKE_PREP="$prep"
  rust_tests "every target at once, preparation fails ($prep)" 8 0 0 1
  if [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: preparation fails ($prep): no test ran"; else bad "rust-tests: preparation fails ($prep): tests ran"; fi
done
unset FAKE_PREP
# #1260: a failed release fixture build fails the step with its own status,
# on either path, before any test.
export PREBUILD_RC=7
for mode in 2 8; do
  rust_tests "$mode CPUs, the release fixture fails" "$mode" 0 0 7
  if [ "$got" = 7 ]; then ok "rust-tests: $mode CPUs, the release fixture fails: its own exit 7"; else bad "rust-tests: $mode CPUs, the release fixture fails: exit $got, not 7"; fi
  has "$mode CPUs, the release fixture fails" "rust-tests: the fixture release build exited 7; no test was started"
  if [ "$(cat "$rt/sync/order")" = prebuild ] && [ ! -s "$rt/sync/cargo.calls" ]; then ok "rust-tests: $mode CPUs, the release fixture fails: no test"; else bad "rust-tests: $mode CPUs, the release fixture fails: something ran after it: $(tr '\n' '|' < "$rt/sync/order")"; fi
done
unset PREBUILD_RC
rust_tests "no --alongside, cargo fails" 2 101 0 1
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
export FAKE_META='{"packages":[{"name":"openwiz-core","targets":[{"name":"openwiz_core","kind":["lib"],"test":true}]},{"name":"openwiz-tests","targets":[{"name":"checks","kind":["test"],"test":true},{"name":"proof","kind":["test"],"test":true},{"name":"fleet","kind":["test"],"test":true}]}]}'
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
rust_tests "--only, a target alone" 8 0 0 0 --only "rust:test:fleet"
calls "--only, a target alone" "cargo test -p openwiz-tests --locked --test fleet -- --test-threads=8"
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
unset FAKE_META
[ -z "$saved_event" ] || export GITHUB_EVENT_NAME="$saved_event"
[ -z "$saved_base" ] || export GITHUB_BASE_REF="$saved_base"

if [ "$fails" -ne 0 ]; then echo "$fails failed"; exit 1; fi
echo "all ok"
