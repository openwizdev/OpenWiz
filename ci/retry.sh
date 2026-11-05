#!/bin/sh
# Retry (#1309): run a step that reads the network up to ATTEMPTS times
# (1 to 9), RETRY_WAIT seconds (default 5) times the attempt number apart,
# and exit with the last attempt's status. Only for a read whose rerun is
# safe: the docs-only action's PR read, npm ci (it starts from an empty
# node_modules). Never for a test: a retried test hides a flake. A usage
# error runs nothing and exits 2. sh .github/actions/docs-only/test.sh
# checks it.
#   sh ci/retry.sh ATTEMPTS -- COMMAND [ARG...]
set -u
usage() { echo "usage: retry.sh ATTEMPTS(1-9) -- COMMAND [ARG...]" >&2; exit 2; }
[ "$#" -ge 3 ] || usage
case "$1" in [1-9]) attempts="$1" ;; *) usage ;; esac
[ "$2" = -- ] || usage
shift 2
wait="${RETRY_WAIT:-5}"
case "$wait" in '' | *[!0-9]*) usage ;; esac
i=1
while :; do
  "$@" && exit 0
  status=$?
  if [ "$i" -ge "$attempts" ]; then
    echo "retry: $1: attempt $i of $attempts failed (exit $status); giving up" >&2
    exit "$status"
  fi
  echo "retry: $1: attempt $i of $attempts failed (exit $status); again in $((wait * i)) s" >&2
  sleep "$((wait * i))"
  i=$((i + 1))
done
