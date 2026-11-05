#!/bin/sh
# The pre-push hook's fixture test (#174, spec #172 claim I6). Run from anywhere:
#   sh .githooks/test.sh
# Part A: the hook's choices (which checks, on which commit, when it stops a
# push), with a fake cargo and npm, on a synthetic repository.
# Part B: real mistakes, with the real tools, on a clone of this checkout's
# HEAD. It needs cargo (with rustfmt and clippy) on PATH and apps/web's
# node_modules (npm ci --ignore-scripts in apps/web).
# Every push goes to a bare repository in a temporary folder, and the hook
# keeps its cache there too (XDG_CACHE_HOME); nothing leaves this machine. PRE_PUSH_HOOK=<file> tests another hook instead of
# .githooks/pre-push (a broken copy must fail this test).
set -u
fixtures_only=0
case "${1:-}" in
  '') ;;
  --fixtures-only) fixtures_only=1 ;;
  *) echo "usage: sh .githooks/test.sh [--fixtures-only]" >&2; exit 2 ;;
esac
[ "$#" -le 1 ] || exit 2
HERE="$(cd "$(dirname "$0")" && pwd -P)"
ROOT="$(cd "$HERE/.." && pwd -P)"
HOOK="${PRE_PUSH_HOOK:-$HERE/pre-push}"
fails=0
tmp="$(cd "$(mktemp -d)" && pwd -P)"
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL $*"; fails=$((fails + 1)); }
pass() { echo "ok   $*"; }
[ -f "$HOOK" ] || fail "no hook at $HOOK"

export XDG_CACHE_HOME="$tmp/cache"

# Git, isolated from this machine's own settings, with a synthetic identity.
export GIT_CONFIG_NOSYSTEM=1 GIT_CONFIG_GLOBAL="$tmp/gitconfig"
git config --file "$GIT_CONFIG_GLOBAL" user.name synthetic
git config --file "$GIT_CONFIG_GLOBAL" user.email synthetic@example.invalid
git config --file "$GIT_CONFIG_GLOBAL" init.defaultBranch main
git config --file "$GIT_CONFIG_GLOBAL" advice.detachedHead false

RUST_CHECKS='cargo fmt --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test -p openwiz-tests --test checks
sh .github/actions/docs-only/test.sh'
WEB_CHECKS='npm run typecheck
npm run check'
ALL_CHECKS="$RUST_CHECKS
$WEB_CHECKS"

# snap REPO: everything a push must leave as it was: HEAD, the branches and
# tags, the index, the stashes, the local config and every file in the work tree.
snap() {
  git -C "$1" rev-parse HEAD
  git -C "$1" for-each-ref --format='%(refname) %(objectname)' refs/heads refs/tags refs/stash
  git -C "$1" ls-files --stage
  git -C "$1" config --local --list
  (cd "$1" && find . -path ./.git -prune -o \( -type f -o -type l \) -exec cksum {} + | LC_ALL=C sort)
}

# result OUTPUT: the hook's result lines, "ok <check>" or "FAIL <check>".
result() {
  grep -E '^pre-push: (ok|FAIL) ' "$1" | sed -E 's/^pre-push: (ok|FAIL) +(.*)  \([0-9]+ s\)$/\1 \2/'
}

# ---------------------------------------------------------------- Part A
A="$tmp/a"
w="$A/work"
CALLS="$A/calls"
export CALLS
mkdir -p "$A/bin" "$A/hooks" "$A/tools"
cp -R "$ROOT/tools/privacy-check" "$A/tools/privacy-check"
[ -f "$HOOK" ] && cp "$HOOK" "$A/hooks/pre-push" && chmod +x "$A/hooks/pre-push"

# The fakes log each call, note any way back into the repository, and fail
# when the checked tree's FAILS file names the call. They can also hold a
# push at one step, to force two pushes to interleave: HOLD=<f> holds it at
# cargo fmt, PAUSE_RM=<f> at the hook's rm of its lock, and PAUSE_LN=<f> at
# its ln of the takeover mark. A held push writes <f>.hook (its hook's PID,
# for HOLD), then <f>.in, and waits (up to 60 s) for <f>.go.
REAL_RM="$(command -v rm)" REAL_LN="$(command -v ln)"
export REAL_RM REAL_LN
cat > "$A/bin/hold.sh" <<'FAKE'
hold() {
  : > "$1.in"
  i=0
  while [ ! -e "$1.go" ]; do sleep 0.1; i=$((i + 1)); [ "$i" -lt 600 ] || exit 3; done
}
FAKE
cat > "$A/bin/rm" <<'FAKE'
#!/bin/sh
. "$(dirname "$0")/hold.sh"
if [ -n "${PAUSE_RM:-}" ]; then for a in "$@"; do case "$a" in */lock) hold "$PAUSE_RM" ;; esac; done; fi
exec "$REAL_RM" "$@"
FAKE
cat > "$A/bin/ln" <<'FAKE'
#!/bin/sh
. "$(dirname "$0")/hold.sh"
if [ -n "${PAUSE_LN:-}" ]; then for a in "$@"; do case "$a" in */reclaim) hold "$PAUSE_LN" ;; esac; done; fi
exec "$REAL_LN" "$@"
FAKE
cat > "$A/bin/cargo" <<'FAKE'
#!/bin/sh
if [ "$1" = fmt ] && [ -n "${HOLD:-}" ]; then
  . "$(dirname "$0")/hold.sh"
  p=$PPID hook=""
  while [ "${p:-1}" -gt 1 ]; do # the hook is the last of the hooks/pre-push processes above this one (its subshells share its name)
    case "$(ps -o args= -p "$p" 2> /dev/null)" in
      *hooks/pre-push*) hook="$p" ;;
      *) [ -z "$hook" ] || break ;;
    esac
    p="$(ps -o ppid= -p "$p" 2> /dev/null | tr -d ' ')"
  done
  echo "$hook" > "$HOLD.hook"
  hold "$HOLD"
fi
echo "cargo $*" >> "$CALLS"
[ -z "${GIT_DIR:-}${GIT_WORK_TREE:-}${GIT_INDEX_FILE:-}" ] || echo "leak: git variables reach cargo" >> "$CALLS"
git rev-parse --git-dir > /dev/null 2>&1 && echo "leak: cargo can see a repository" >> "$CALLS"
if grep -qxF "cargo $*" FAILS 2> /dev/null; then echo "planted failure: cargo $*"; exit 1; fi
FAKE
cat > "$A/bin/npm" <<'FAKE'
#!/bin/sh
echo "npm $*" >> "$CALLS"
[ -z "${GIT_DIR:-}${GIT_WORK_TREE:-}${GIT_INDEX_FILE:-}" ] || echo "leak: git variables reach npm" >> "$CALLS"
if grep -qxF "npm $*" ../../FAILS 2> /dev/null; then echo "planted failure: npm $*"; exit 1; fi
FAKE
chmod +x "$A/bin/cargo" "$A/bin/npm" "$A/bin/rm" "$A/bin/ln"

mkdir -p "$w/crates" "$w/apps/web/src" "$w/contracts" "$w/docs" "$w/.github/actions/docs-only"
git init -q "$w"
git init -q --bare "$A/remote.git"
git init -q --bare "$A/other.git"
echo synthetic > "$w/crates/a.rs"
echo synthetic > "$w/apps/web/src/x.ts"
echo synthetic > "$w/contracts/c.json"
echo synthetic > "$w/docs/d.md"
printf '%s\n' '/apps/web/node_modules/' > "$w/.gitignore"
cat > "$w/.github/actions/docs-only/test.sh" <<'FAKE'
echo "sh .github/actions/docs-only/test.sh" >> "$CALLS"
if grep -qxF "sh .github/actions/docs-only/test.sh" FAILS 2> /dev/null; then echo "planted failure: docs-only"; exit 1; fi
FAKE
git -C "$w" add -A
git -C "$w" commit -qm base
mkdir "$w/apps/web/node_modules"
git -C "$w" config core.hooksPath "$A/hooks"
git -C "$w" remote add r "$A/remote.git"
git -C "$w" remote add s "$A/other.git"
git -C "$w" push -q --no-verify r main
git -C "$w" remote set-head r main > /dev/null

# change PATH TEXT: append TEXT to PATH in the work repo and commit it.
change() { echo "$2" >> "$w/$1"; git -C "$w" add -- "$1"; git -C "$w" commit -qm "$1"; }

# push CASE WANT_EXIT WANT_CALLS ARGS...: run git push ARGS in the work
# repository with the fakes first on PATH (and $PUSH_ENV's variables). Checks
# its exit, the exact calls the fakes saw, in order (any "leak:" line fails
# it), and that the repository was left as it was.
push() {
  name="$1"; want_exit="$2"; want_calls="$3"; shift 3
  : > "$CALLS"
  snap "$w" > "$A/before"
  env ${PUSH_ENV:-} PATH="$A/bin:$PATH" git -C "$w" push "$@" > "$A/out" 2>&1
  got_exit=$?
  snap "$w" > "$A/after"
  got_calls="$(cat "$CALLS")"
  bad=""
  [ "$got_exit" = "$want_exit" ] || bad="$bad exit $got_exit (want $want_exit);"
  [ "$got_calls" = "$want_calls" ] || bad="$bad calls [$(echo "$got_calls" | tr '\n' '|')] (want [$(echo "$want_calls" | tr '\n' '|')]);"
  cmp -s "$A/before" "$A/after" || bad="$bad the repository changed;"
  if [ -z "$bad" ]; then pass "$name"; else fail "$name:$bad"; sed 's/^/     | /' "$A/out"; fi
}

# remote_is CASE REPO REF WANT: REF in the bare REPO is WANT ("none": absent).
remote_is() {
  got="$(git -C "$2" rev-parse --verify --quiet "$3" || echo none)"
  if [ "$got" = "$4" ]; then pass "$1: $3 is $4"; else fail "$1: $3 is $got, want $4"; fi
}

# has CASE LINE: the last push's output holds exactly this line, once.
has() {
  n="$(grep -cxF "$2" "$A/out")"
  if [ "$n" = 1 ]; then pass "$1: says \"$2\""; else fail "$1: says \"$2\" $n times, want once"; fi
}

git -C "$w" checkout -q -b a1
change docs/d.md "a doc change"
push "A1 a new branch that changes only a doc runs the Rust and repository checks, not the web ones" 0 "$RUST_CHECKS" r a1
remote_is A1 "$A/remote.git" refs/heads/a1 "$(git -C "$w" rev-parse HEAD)"

change apps/web/src/x.ts "a web change"
push "A2 a web change, on a branch the remote has, runs every check" 0 "$ALL_CHECKS" r a1

change contracts/c.json "a contract change"
push "A3 a contracts change runs the web checks too" 0 "$ALL_CHECKS" r a1

push "A4 a new branch with no change runs no check" 0 "" r main:refs/heads/a4
remote_is A4 "$A/remote.git" refs/heads/a4 "$(git -C "$w" rev-parse main)"

push "A5 deleting a branch runs no check" 0 "" r :refs/heads/a4
remote_is A5 "$A/remote.git" refs/heads/a4 none

old="$(git -C "$w" rev-parse a1)"
change crates/a.rs "a Rust change"
change FAILS "cargo clippy --workspace --all-targets -- -D warnings"
push "A6 a failing check stops the push, and every other check still runs" 1 "$RUST_CHECKS" r a1
remote_is A6 "$A/remote.git" refs/heads/a1 "$old"
result "$A/out" > "$A/result"
if [ "$(cat "$A/result")" = "ok cargo fmt --check
FAIL cargo clippy --workspace --all-targets -- -D warnings
ok cargo test -p openwiz-tests --test checks
ok sh .github/actions/docs-only/test.sh" ]; then pass "A6: one FAIL line, for clippy, and three ok lines"; else fail "A6: result lines [$(tr '\n' '|' < "$A/result")]"; fi
grep -qxF "    planted failure: cargo clippy --workspace --all-targets -- -D warnings" "$A/out" && pass "A6: shows the failed check's output" || fail "A6: the failed check's output is missing"
git -C "$w" reset -q --hard "$old"

change apps/web/src/x.ts "a second web change"
change FAILS "npm run check"
rm "$w/FAILS"
push "A7 the pushed commit is checked: a fix left in the working tree doesn't let it through" 1 "$ALL_CHECKS" r a1
remote_is A7 "$A/remote.git" refs/heads/a1 "$old"
git -C "$w" reset -q --hard "$old"

change docs/d.md "a second doc change"
echo "cargo fmt --check" > "$w/FAILS"
echo "uncommitted" >> "$w/crates/a.rs"
push "A8 a mistake only in the working tree doesn't stop a clean commit" 0 "$RUST_CHECKS" r a1
remote_is A8 "$A/remote.git" refs/heads/a1 "$(git -C "$w" rev-parse HEAD)"
rm "$w/FAILS"
git -C "$w" checkout -q -- crates/a.rs

push "A9 with no base to compare against, every check runs" 0 "$ALL_CHECKS" s a1
remote_is A9 "$A/other.git" refs/heads/a1 "$(git -C "$w" rev-parse HEAD)"

git -C "$w" checkout -q -b a10ok main
change docs/d.md "a clean doc change"
git -C "$w" checkout -q -b a10bad main
change docs/d.md "a doc change with a failing check"
change FAILS "sh .github/actions/docs-only/test.sh"
: > "$CALLS"
PATH="$A/bin:$PATH" git -C "$w" push r a10ok a10bad > "$A/out" 2>&1
got_exit=$?
got_calls="$(LC_ALL=C sort "$CALLS")"
want_calls="$(printf '%s\n%s\n' "$RUST_CHECKS" "$RUST_CHECKS" | LC_ALL=C sort)"
if [ "$got_exit" = 1 ] && [ "$got_calls" = "$want_calls" ]; then pass "A10 two branches in one push are both checked, and one failure stops both"; else fail "A10: exit $got_exit, calls [$(echo "$got_calls" | tr '\n' '|')]"; sed 's/^/     | /' "$A/out"; fi
remote_is A10 "$A/remote.git" refs/heads/a10ok none
remote_is A10 "$A/remote.git" refs/heads/a10bad none

git -C "$w" checkout -q a1
change apps/web/src/x.ts "a web change with no node_modules"
mv "$w/apps/web/node_modules" "$A/node_modules.away"
push "A11 a web push without apps/web/node_modules is stopped before any check" 1 "" r a1
has A11 "pre-push: apps/web/node_modules is missing: run npm ci --ignore-scripts in apps/web, then push again"
mv "$A/node_modules.away" "$w/apps/web/node_modules"

# Locks: pushes from one clone share its copy, so only one may check at a
# time. These cases force two pushes to interleave, with the fakes' holds.
set -- "$XDG_CACHE_HOME/closedwiz-pre-push/"*
[ "$#" = 1 ] && [ -d "$1" ] || fail "A12: want one cache folder for the work repository, got: $*"
cachedir="$1"
lock="$cachedir/lock"

# await FILE: wait, up to 60 s, until FILE exists.
await() {
  i=0
  while [ ! -e "$1" ] && [ ! -L "$1" ]; do sleep 0.1; i=$((i + 1)); [ "$i" -lt 600 ] || return 1; done
}
# branch NAME: a new branch from main with one doc change; back on a1 after.
branch() {
  git -C "$w" checkout -q -b "$1" main
  change docs/d.md "a doc change on $1"
  git -C "$w" checkout -q a1
}
# bg ID REF [VAR=VALUE...]: push REF in the background with the fakes and
# these variables; its calls, output and exit go to $A/ID.calls, .out, .exit.
bg() {
  id="$1"; ref="$2"; shift 2
  : > "$A/$id.calls"
  (env CALLS="$A/$id.calls" "$@" PATH="$A/bin:$PATH" git -C "$w" push r "$ref" > "$A/$id.out" 2>&1; echo $? > "$A/$id.exit") &
}
# finish CASE ID WANT_EXIT WANT_CALLS: wait for push ID, then check its exit
# and its exact calls.
finish() {
  name="$1"; id="$2"; want_exit="$3"; want_calls="$4"
  if ! await "$A/$id.exit"; then fail "$name: the push never ended"; return; fi
  got_exit="$(cat "$A/$id.exit")"
  got_calls="$(cat "$A/$id.calls")"
  bad=""
  [ "$got_exit" = "$want_exit" ] || bad="$bad exit $got_exit (want $want_exit);"
  [ "$got_calls" = "$want_calls" ] || bad="$bad calls [$(echo "$got_calls" | tr '\n' '|')] (want [$(echo "$want_calls" | tr '\n' '|')]);"
  if [ -z "$bad" ]; then pass "$name"; else fail "$name:$bad"; sed 's/^/     | /' "$A/$id.out"; fi
}
# says CASE ID PATTERN: push ID's output has exactly one line matching
# PATTERN, an extended regular expression, whole.
says() {
  n="$(grep -cE "^$3\$" "$A/$2.out")"
  if [ "$n" = 1 ]; then pass "$1: says \"$3\""; else fail "$1: says \"$3\" $n times, want once"; fi
}
# stale ID: leave a stale lock: hold a push at its first check, kill its hook
# (SIGKILL, so it can't release the lock), then let the held fake go.
stale() {
  branch "$1"
  bg "$1" "$1" HOLD="$A/$1"
  if ! await "$A/$1.in"; then fail "$1: the push meant to leave a stale lock never reached its check"; return; fi
  kill -9 "$(cat "$A/$1.hook")"
  : > "$A/$1.go"
  await "$A/$1.exit" || fail "$1: the killed push never ended"
  { [ -e "$lock" ] || [ -L "$lock" ]; } || fail "$1: the killed push left no lock"
}
# unlocked CASE: no lock is left behind.
unlocked() {
  if [ -e "$lock" ] || [ -L "$lock" ]; then fail "$1: a lock is left"; else pass "$1: no lock is left"; fi
}

branch l12a
branch l12b
bg l12a l12a HOLD="$A/h12"
await "$A/h12.in" || fail "A12: the first push never reached its check"
bg l12b l12b
finish "A12 a push while another from this clone is being checked is stopped before any check" l12b 1 ""
says A12 l12b "pre-push: another push is being checked in this clone \(pid $(cat "$A/h12.hook")\): push again when it ends"
: > "$A/h12.go"
finish "A12: the first push then finishes" l12a 0 "$RUST_CHECKS"
remote_is A12 "$A/remote.git" refs/heads/l12a "$(git -C "$w" rev-parse l12a)"
remote_is A12 "$A/remote.git" refs/heads/l12b none
unlocked A12

stale l13x
push "A13 a lock left by a killed push is taken over" 0 "$ALL_CHECKS" r a1
unlocked A13

change docs/d.md "a doc change pushed with git variables set"
PUSH_ENV="GIT_DIR=$w/.git GIT_WORK_TREE=$w"
push "A14 git variables the push was given never reach a check" 0 "$RUST_CHECKS" r a1
PUSH_ENV=""

change docs/d.md "a doc change with the cache inside the working tree"
PUSH_ENV="XDG_CACHE_HOME=$w/cache"
push "A15 a cache folder inside the working tree is refused" 1 "" r a1
PUSH_ENV=""
has A15 "pre-push: the cache folder $w/cache/closedwiz-pre-push/$(printf '%s' "$w/.git" | cksum | cut -d ' ' -f 1) is inside the working tree: set XDG_CACHE_HOME elsewhere"

git init -q "$A/home"
change docs/d.md "a doc change with the cache inside another repository"
PUSH_ENV="XDG_CACHE_HOME=$A/home/cache"
push "A16 a cache folder inside another repository (a home folder kept in git) is hidden from the checks" 0 "$RUST_CHECKS" r a1
PUSH_ENV=""

change docs/d.md "a doc change to push past the locks below"
mkdir "$lock"
push "A17 a lock with no PID (an empty folder) is never taken over" 1 "" r a1
has A17 "pre-push: the lock $lock has no PID it can read: if no push is running in this clone, delete it and push again"
[ -d "$lock" ] && [ ! -L "$lock" ] && pass "A17: the empty folder is still there" || fail "A17: the empty folder was removed"
rmdir "$lock"
ln -s not-a-pid "$lock"
push "A18 a lock whose PID can't be read is never taken over" 1 "" r a1
has A18 "pre-push: the lock $lock has no PID it can read: if no push is running in this clone, delete it and push again"
[ "$(readlink "$lock")" = not-a-pid ] && pass "A18: that lock is still there" || fail "A18: that lock was removed"
rm -f "$lock"

stale l19x
branch l19a
branch l19b
bg l19a l19a PAUSE_LN="$A/n19"
await "$A/n19.in" || fail "A19: the first push never reached its takeover"
bg l19b l19b HOLD="$A/h19"
await "$A/h19.in" || fail "A19: the second push never took the stale lock over"
: > "$A/n19.go"
finish "A19 two pushes find one stale lock: the one held before its takeover then finds the lock taken, and is stopped" l19a 1 ""
says A19 l19a "pre-push: another push took the lock in this clone: push again when it ends"
: > "$A/h19.go"
finish "A19: the push that took the lock over finishes" l19b 0 "$RUST_CHECKS"
remote_is A19 "$A/remote.git" refs/heads/l19a none
unlocked A19

stale l20x
branch l20a
branch l20b
bg l20a l20a PAUSE_RM="$A/r20"
await "$A/r20.in" || fail "A20: the first push never reached its takeover"
bg l20b l20b
finish "A20 a push arriving while another takes over a stale lock is stopped before any check" l20b 1 ""
says A20 l20b "pre-push: another push \(pid [0-9]+\) is taking over a stale lock in this clone: push again in a moment"
: > "$A/r20.go"
finish "A20: the push taking over finishes" l20a 0 "$RUST_CHECKS"
remote_is A20 "$A/remote.git" refs/heads/l20b none
unlocked A20

bg a21 a1 HOLD="$A/h21"
await "$A/h21.in" || fail "A21: the push never reached its check"
rm -rf "$lock"
ln -s "$$" "$lock"
: > "$A/h21.go"
finish "A21 a push whose lock was replaced by another live push's still finishes" a21 0 "$RUST_CHECKS"
[ "$(readlink "$lock")" = "$$" ] && pass "A21: it leaves the other push's lock alone" || fail "A21: it removed the other push's lock"
rm -f "$lock"

stale l22x
sh -c 'exit 0' &
dead=$!
wait "$dead"
ln -s "$dead" "$cachedir/reclaim"
branch l22
push "A22 a takeover mark left by a push that ended stops the push, and says how to clear it" 1 "" r l22
has A22 "pre-push: a stale $cachedir/reclaim is in the way: if no push is running in this clone, delete it and push again"
rm -f "$cachedir/reclaim"
push "A22: once it is deleted, the stale lock is taken over" 0 "$RUST_CHECKS" r l22
unlocked A22

# ---------------------------------------------------------------- Part B
B="$tmp/b"
c="$B/work"
if [ "$fixtures_only" = 1 ]; then
  pass "Part B skipped: fixture-only mode"
elif ! command -v cargo > /dev/null; then
  fail "Part B needs cargo on PATH"
elif [ ! -d "$ROOT/apps/web/node_modules" ]; then
  fail "Part B needs $ROOT/apps/web/node_modules: npm ci --ignore-scripts in apps/web"
else
  # One commit holding this checkout's HEAD tree (a partial clone can't push
  # its whole history), with the hook under test.
  mkdir -p "$c"
  git init -q "$c"
  git -C "$ROOT" archive HEAD | tar -x -C "$c"
  mkdir -p "$c/.githooks"
  [ -f "$HOOK" ] && cp "$HOOK" "$c/.githooks/pre-push" && chmod +x "$c/.githooks/pre-push"
  mkdir -p "$c/tools/privacy-check"
  cp "$ROOT/tools/privacy-check/"*.py "$c/tools/privacy-check/"
  git -C "$c" add -A
  git -C "$c" commit -qm "this checkout's HEAD, with the hook under test"
  # The one install command, as AGENTS.md gives it.
  (cd "$c" && git config core.hooksPath .githooks)
  ln -s "$ROOT/apps/web/node_modules" "$c/apps/web/node_modules"
  git init -q --bare "$B/remote.git"
  git -C "$c" remote add r "$B/remote.git"
  git -C "$c" push -q --no-verify r HEAD:refs/heads/main || fail "Part B: the first push, with no hook, failed"
  git -C "$c" remote set-head r main > /dev/null || fail "Part B: no r/main"

  # real CASE WANT_EXIT WANT_RESULT: commit what the case staged, on a new
  # branch from main, and push it. Checks the exit, the hook's exact result
  # lines and the remote branch.
  n=0
  real() {
    name="$1"; want_exit="$2"; want_result="$3"
    n=$((n + 1))
    git -C "$c" commit -qm "$name"
    git -C "$c" push r "HEAD:refs/heads/b$n" > "$B/out" 2>&1
    got_exit=$?
    got_result="$(result "$B/out")"
    if [ "$want_exit" = 0 ]; then want_ref="$(git -C "$c" rev-parse HEAD)"; else want_ref=none; fi
    got_ref="$(git -C "$B/remote.git" rev-parse --verify --quiet "refs/heads/b$n" || echo none)"
    took="$(sed -nE 's/^pre-push: .* in ([0-9]+ s)$/\1/p' "$B/out")"
    bad=""
    [ "$got_exit" = "$want_exit" ] || bad="$bad exit $got_exit (want $want_exit);"
    [ "$got_result" = "$want_result" ] || bad="$bad result [$(echo "$got_result" | tr '\n' '|')] (want [$(echo "$want_result" | tr '\n' '|')]);"
    [ "$got_ref" = "$want_ref" ] || bad="$bad remote b$n is $got_ref (want $want_ref);"
    if [ -z "$bad" ]; then pass "$name (the hook took ${took:-?})"; else fail "$name:$bad"; fi
    sed 's/^/     | /' "$B/out"
    git -C "$c" checkout -q -f -B case r/main
  }
  git -C "$c" checkout -q -B case r/main
  lib="crates/core/src/lib.rs"

  echo "// A planted comment (synthetic)." >> "$c/$lib"
  git -C "$c" add "$lib"
  real "B1 a clean Rust change goes through" 0 "$(echo "$RUST_CHECKS" | sed 's/^/ok /')"

  echo "pub fn planted_format()->u8{1}" >> "$c/$lib"
  git -C "$c" add "$lib"
  real "B2 a Rust format mistake stops the push" 1 "FAIL cargo fmt --check
ok cargo clippy --workspace --all-targets -- -D warnings
ok cargo test -p openwiz-tests --test checks
ok sh .github/actions/docs-only/test.sh"

  printf '%s\n' "" "pub fn planted_lint(v: &[u8]) -> bool {" "    v.len() == 0" "}" >> "$c/$lib"
  git -C "$c" add "$lib"
  real "B3 a clippy warning stops the push" 1 "ok cargo fmt --check
FAIL cargo clippy --workspace --all-targets -- -D warnings
ok cargo test -p openwiz-tests --test checks
ok sh .github/actions/docs-only/test.sh"

  mkdir -p "$c/skills/planted"
  printf '%s\n' "---" "name: planted" "description: A planted ninth skill (synthetic)." "---" "" "# Planted" > "$c/skills/planted/SKILL.md"
  git -C "$c" add skills/planted/SKILL.md
  real "B4 a static check's mistake (a ninth skill) stops a skills-only push" 1 "ok cargo fmt --check
ok cargo clippy --workspace --all-targets -- -D warnings
FAIL cargo test -p openwiz-tests --test checks
ok sh .github/actions/docs-only/test.sh"

  printf '%s\n' "" "pub mod planted;" >> "$c/$lib"
  git -C "$c" add "$lib"
  printf '%s\n' "pub fn planted() {}" > "$c/crates/core/src/planted.rs"
  real "B5 a new file left out of the commit stops the push, though the working tree has it" 1 "FAIL cargo fmt --check
FAIL cargo clippy --workspace --all-targets -- -D warnings
FAIL cargo test -p openwiz-tests --test checks
ok sh .github/actions/docs-only/test.sh"
  rm -f "$c/crates/core/src/planted.rs"

  echo '// Reads "private/planted.md" (synthetic).' >> "$c/tests/checks/main.rs"
  git -C "$c" add tests/checks/main.rs
  real "B6 a test reading a private file CI deletes stops the push" 1 "ok cargo fmt --check
ok cargo clippy --workspace --all-targets -- -D warnings
ok cargo test -p openwiz-tests --test checks
FAIL sh .github/actions/docs-only/test.sh"

  echo "export const planted: number = 'synthetic';" > "$c/apps/web/src/planted.ts"
  git -C "$c" add apps/web/src/planted.ts
  real "B7 a web type error stops the push" 1 "$(echo "$RUST_CHECKS" | sed 's/^/ok /')
FAIL npm run typecheck
ok npm run check"

  echo "export const planted = (s: string): unknown => eval(s);" > "$c/apps/web/src/planted.ts"
  git -C "$c" add apps/web/src/planted.ts
  real "B8 a web static check's mistake (eval) stops the push" 1 "$(echo "$RUST_CHECKS" | sed 's/^/ok /')
ok npm run typecheck
FAIL npm run check"

  echo "// A planted comment (synthetic)." >> "$c/apps/web/src/api.ts"
  git -C "$c" add apps/web/src/api.ts
  real "B9 a clean web change goes through" 0 "$(echo "$ALL_CHECKS" | sed 's/^/ok /')"

  echo "// A second planted comment (synthetic)." >> "$c/$lib"
  git -C "$c" add "$lib"
  real "B10 a second clean Rust change goes through" 0 "$(echo "$RUST_CHECKS" | sed 's/^/ok /')"

  # Tools look for their settings in the folders above the one they run in:
  # the copy must not be inside the working tree.
  echo "max_width = 40" > "$c/rustfmt.toml"
  echo "// A third planted comment (synthetic)." >> "$c/$lib"
  git -C "$c" add "$lib"
  real "B11 a setting left uncommitted in the working tree (rustfmt.toml) doesn't change the result" 0 "$(echo "$RUST_CHECKS" | sed 's/^/ok /')"
  rm -f "$c/rustfmt.toml"
fi

if [ "$fails" = 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
