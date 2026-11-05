#!/bin/sh
# One collect/measure/publish path for scheduled and labelled on-demand runs.
# Explicit window requires all three BENCH_SINCE, BENCH_UNTIL, BENCH_LABEL.
set -eu
HERE="$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)"
robots="${BENCH_ROBOTS:-5}"
if [ -z "${BENCH_SINCE:-}${BENCH_UNTIL:-}${BENCH_LABEL:-}" ]; then
  bounds="$(python3 -I "$HERE/bench.py" day-window)"
  since="${bounds% *}"
  until="${bounds#* }"
  label="${since%%T*} PST"
else
  : "${BENCH_SINCE:?an explicit window needs BENCH_SINCE}"
  : "${BENCH_UNTIL:?an explicit window needs BENCH_UNTIL}"
  : "${BENCH_LABEL:?an explicit window needs BENCH_LABEL}"
  since="$BENCH_SINCE"
  until="$BENCH_UNTIL"
  label="$BENCH_LABEL"
fi
# Validate everything before a network read. Values remain arguments; no eval.
python3 -I "$HERE/bench.py" validate-window --since "$since" --until "$until" --robots "$robots" --label "$label"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT HUP INT TERM
python3 -I "$HERE/bench.py" collect --since "$since" --until "$until" --out "$work/window"
# The factory benches (#1359) never cost the day's CI numbers: if their reads
# fail (e.g. a token without issues: read), the day's factory benches stay
# unknown and the CI point is still measured and published.
if ! python3 -I "$HERE/bench.py" factory --since "$since" --until "$until" --out "$work/window"; then
  echo 'daily: factory benches unknown for this day; publishing the CI numbers' >&2
fi
# EB2's journey read is required when factory history is available. A partial
# journey cannot replace the last publication. Keep #1359's optional-factory
# behavior: without factory.json the new journey record is also unknown.
if [ -f "$work/window/factory.json" ]; then
  python3 -I "$HERE/trends.py" collect "$work/window"
fi
# Selector escapes (#1264): the same; a failed read leaves the day's count
# unknown, never 0.
if ! python3 -I "$HERE/bench.py" escapes --since "$since" --until "$until" --out "$work/window"; then
  echo 'daily: selector escapes unknown for this day; publishing the CI numbers' >&2
fi
python3 -I "$HERE/bench.py" measure "$work/window" --robots "$robots" --label "$label" --allow-empty --allow-timing-gaps
python3 -I "$HERE/publish.py" --source "$work/window"
