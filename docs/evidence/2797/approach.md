# Revoke folder safety diagnostics

Use the existing private-folder checks in standalone revoke. Report the fixed guidance for the check that refused access on stderr and exit 1. An absent folder continues to mean there was no token to find. The in-run revoke path remains first.

## Threats

- An owner could mistake a folder safety refusal for confirmation that no live token remains.
- A diagnostic could disclose a token, the supplied folder path, or raw filesystem errors.
- Continuing after a refusal could contact GitHub, move or delete the cache, or follow an unsafe path.

## Proof

Move the loose-folder case from the existing no-token test into a dedicated CLI regression. With a synthetic cached token and loopback GitHub fake, assert the exact stderr line, empty stdout, exit 1, no API request, and unchanged cache. Exercise the other folder checks with synthetic paths and retain the existing missing-folder and in-run proofs. The old code should fail at the diagnostic assertion. These tests establish local CLI behavior on fixtures. Live GitHub, pairing retention, and GA5 readback are outside this proof.
