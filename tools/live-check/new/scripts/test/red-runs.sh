#!/bin/sh
# The red runs (see red-runs.py and red-mutants.json). SYNTHETIC ONLY. From the repository root:
#   sh private/evidence/openwiz-0.0.4/ticket-13/scripts/test/red-runs.sh
exec python3 "$(dirname "$0")/red-runs.py"
