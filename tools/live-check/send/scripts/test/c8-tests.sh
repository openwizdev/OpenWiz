#!/bin/sh
# #642's narrow declarative proof; no room-cli or live endpoint.
set -eu
PYTHONDONTWRITEBYTECODE=1 python3 "$(dirname "$0")/../../c8-642/test_c8.py"
