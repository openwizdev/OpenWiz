#!/bin/sh
# O15 synthetic CLI proofs only. Never contacts live GitHub or needs private literals.
set -eu
[ "$#" -le 2 ] || { echo 'usage: sh tools/open-tickets/test.sh [O3-check.py [O14-import.py]]' >&2; exit 2; }
tickets_here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tickets_checker=${1:-$tickets_here/../privacy-check/check.py}
[ -r "$tickets_checker" ] && [ -r "$(dirname -- "$tickets_checker")/workflow.py" ] || {
  echo 'open-tickets: required O3 checker or sibling is unavailable' >&2
  exit 2
}
python3 -I "$tickets_here/test_plan.py"
python3 -I "$tickets_here/test_graph.py"
python3 -I "$tickets_here/test_text.py" --checker "$tickets_checker"
python3 -I "$tickets_here/test_move.py" --checker "$tickets_checker"
tickets_importer=${2:-$tickets_here/../open-import/import.py}
[ -r "$tickets_importer" ] && [ -r "$(dirname -- "$tickets_importer")/paths.json" ] || {
  echo 'open-tickets: required reviewed O14 importer/list is unavailable' >&2
  exit 2
}
python3 -I "$tickets_here/test_carriage.py" --checker "$tickets_checker" --importer "$tickets_importer"
python3 -I "$tickets_here/test_collect.py" --checker "$tickets_checker"
