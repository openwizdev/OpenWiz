#!/bin/sh
# Collect the recorded run's evidence into kernel/proofs/grok-bot/run.md and checks.txt.
#   sh kernel/proofs/grok-bot/collect.sh <owner>/<demo> <private raw file outside the checkout>
# Run from the root of an OpenWiz checkout, with gh signed in. Exit 0 only when every check
# gives its expected result: all stages reached, the privacy check clean, and no Grok Bot
# special case in OpenWiz's drivers, kernel contracts, kits or crates.
set -u
umask 077
[ $# -eq 2 ] || { echo "usage: collect.sh <owner>/<demo> <private raw file>" >&2; exit 2; }
repo=$1 raw=$2 dir=kernel/proofs/grok-bot
case $raw in /*) ;; *) echo "collect.sh: the raw file must be an absolute path outside the checkout" >&2; exit 2 ;; esac
case $raw in "$(pwd)"/*) echo "collect.sh: the raw file must be outside the checkout" >&2; exit 2 ;; esac
[ -f "$dir/sanitize.py" ] || { echo "collect.sh: run from the root of an OpenWiz checkout" >&2; exit 2; }
python3 -I "$dir/sanitize.py" fetch --repo "$repo" --out "$raw" >/dev/null || { echo "collect.sh: fetch failed" >&2; exit 1; }
chmod 600 "$raw"

failed=0
check() { # check <name> <expected exit> <command...>
    name=$1 want=$2; shift 2
    out=$("$@" 2>&1); got=$?
    shown=$(printf '%s' "$*" | sed "s|$raw|<private raw file>|g")
    { echo "## $name"; echo "\$ $shown"; [ -n "$out" ] && echo "$out"; echo "exit $got (expected $want)"; echo; } >>"$dir/checks.txt"
    [ "$got" -eq "$want" ] || { echo "collect.sh: $name: exit $got, expected $want" >&2; failed=1; }
}
: >"$dir/checks.txt"
check stages 0 python3 -I "$dir/sanitize.py" build "$raw" --out "$dir/run.md"
check privacy 0 python3 -I tools/privacy-check/check.py --tree "$dir"
check no-special-case 1 git grep -n -i grok -- adapters kernel/driver.v1.md kernel/records.v1.md kernel/driver-kit kernel/records-kit crates
exit $failed
