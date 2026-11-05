#!/bin/sh
# WZ4 (#2634): ClosedWiz's fleet load checks, moved out of launch-fleet, in one
# command for CI (WZ12 wires it in). Run from the repository root; needs Python,
# sh, jq, cargo and node, as the load tests always did.
set -eu
cd "$(dirname "$0")/../.."
python3 -I tools/fleet-load/test_carried.py
# #1456: the finite pass runner keeps the original router failures visible
# (formerly run by launch-fleet's test-loop.sh).
python3 -I tools/review-relay/test_router.py
python3 -I tools/fleet-load/test_seams.py
python3 -I tools/fleet-load/test.py
