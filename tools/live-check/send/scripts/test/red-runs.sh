#!/bin/sh
# The red runs (see red-runs.py and red-mutants.json). SYNTHETIC ONLY. From the repository root:
#   sh private/evidence/openwiz-0.0.3/ticket-3/scripts/test/red-runs.sh
exec python3 "$(dirname "$0")/red-runs.py"
