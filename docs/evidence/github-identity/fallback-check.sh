#!/bin/sh
# GI7 R2 (#2549): run launch-fleet's documented App-token block (the one after
# `<!-- GI7 identity -->` in skills/launch-fleet/SKILL.md) with a fake
# `openwiz`, and check it never changes the shell's own GH_TOKEN, set or
# unset, while `app` and `app_git` carry the App token only when one was
# minted. Offline; every value is synthetic. Run: sh docs/evidence/github-identity/fallback-check.sh
set -eu
here=$(cd "$(dirname "$0")/../../.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/bin"
awk '/^  <!-- GI7 identity -->$/ {on = 1; next}
  on && /^  ```sh$/ {body = 1; next}
  body && /^  ```$/ {exit}
  body {sub(/^  /, ""); print}' "$here/skills/launch-fleet/SKILL.md" \
  | sed 's#<owner>/<repo>#synthetic-owner/synthetic-repo#' > "$work/block.sh"
grep -q 'openwiz github token' "$work/block.sh" || { echo 'FAIL: no documented block' >&2; exit 1; }
{
  printf '#!/bin/sh\n[ "${FAKE_MINT:-}" = ok ] || { echo "openwiz: github token: refused" >&2; exit 5; }\n'
  printf 'echo synthetic-app-token-2549\n'
} > "$work/bin/openwiz"
chmod +x "$work/bin/openwiz"
# case: GH_TOKEN before, FAKE_MINT, what `app` gives gh, what `app_git` gives git, stderr lines
check() {
  out=$(cd "$work" && PATH="$work/bin:$PATH" FAKE_MINT=$2 sh -c '
    [ "$1" = unset ] && unset GH_TOKEN || GH_TOKEN=$1
    [ "$1" = unset ] || export GH_TOKEN
    . ./block.sh
    printf "shell=%s app=%s " "${GH_TOKEN-unset}" "$(app sh -c "printf %s \"\${GH_TOKEN-unset}\"")"
    printf "protocol=https\nhost=github.com\n\n" | GIT_TERMINAL_PROMPT=0 GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 app_git credential fill 2> /dev/null \
      | sed -n "s/^password=//p" | tr -d "\n"' sh "$1" 2> "$work/err") || true
  want="shell=$3 app=$4 $5"
  [ "$out" = "$want" ] || { echo "FAIL $1/$2: got '$out', want '$want'" >&2; exit 1; }
  [ "$(grep -c '' "$work/err")" = "$6" ] || { echo "FAIL $1/$2: stderr $(cat "$work/err")" >&2; exit 1; }
  echo "ok   GH_TOKEN $1, mint $2: $want"
}
check synthetic-user-token fail synthetic-user-token synthetic-user-token '' 1
check unset fail unset unset '' 1
check synthetic-user-token ok synthetic-user-token synthetic-app-token-2549 synthetic-app-token-2549 0
check unset ok unset synthetic-app-token-2549 synthetic-app-token-2549 0
