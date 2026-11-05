#!/bin/sh
# The War room's hourly publish (WR9), like the board's: its own tests first,
# then one tick, render and publish to the branch `war-room`. A failed test,
# read or render publishes nothing, so `war-room` keeps its last good state and time.
#   sh tools/war-room/publish.sh REMOTE [--source-root DIR --selection FILE]
#   sh tools/war-room/publish.sh REMOTE --gather OWNER/REPO RUN_URL
# --gather (WR10) first gathers the real sources, reading only (gather.py), into a
# private temporary root and selection, and publishes with them. A privacy hit in
# a gathered source refuses the gather, so nothing is published.
set -eu
HERE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
usage='usage: publish.sh REMOTE [--source-root DIR --selection FILE | --gather OWNER/REPO RUN_URL]'
[ "$#" -ge 1 ] || { echo "$usage" >&2; exit 2; }
remote="$1"
shift
python3 -I "$HERE/test_publish.py"
if [ "${1:-}" = --gather ]; then
  [ "$#" -eq 3 ] || { echo "$usage" >&2; exit 2; }
  python3 -I "$HERE/test_gather.py"
  sources="$(mktemp -d)"
  trap 'rm -rf "$sources"' EXIT
  python3 -I "$HERE/gather.py" --remote "$remote" --repo "$2" --run-url "$3" --out "$sources/gathered"
  set -- --source-root "$sources/gathered/root" --selection "$sources/gathered/selection.json"
fi
python3 -I "$HERE/publish.py" publish --remote "$remote" --at "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$@"
