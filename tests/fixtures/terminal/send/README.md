# Synthetic terminal send cases

CP6 lives in the ordinarily registered `tests/terminal/send.rs`. Its recording
HTTP cases derive schema-valid bodies from T3's `tests/terminal/actions/` and
substitute only this attempt's synthetic target/id/hash/byte count. The actual
server cases use the existing `room-cli-0.43.1/send/scenario.json`, an absolute
fake-room-cli, private state, and no credentials.

synthetic_assumptions: all caller states, draft text, identities, timestamps,
mode/target mismatches, disconnects and guard refusals are constructed test
cases. They assert no live endpoint behavior or live acceptance. Rendered
screens are synthetic; no private/live files are test inputs.
