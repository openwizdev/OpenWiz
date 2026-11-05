# WR5 synthetic proof

All fixture data is synthetic. `pairs.json` is test input to the in-memory
projection, **not** a native source schema or a new persistent answer store.
The test pins its actual bytes by SHA-256 in the existing suite source field.

Claims and independent evidence:

- WR8 known/open/unknown: 11:00 to 11:07 is 420 seconds; one of three requests
  has a substantive answer, so coverage is 1/3 with denominator three.
- Duplicate requests/receipts count once; a receipt, notification acceptance,
  label removal or resolved status has no substantive endpoint.
- Missing provenance, edited/deleted history, an unlinked disposition, reversed
  time and an event beyond the source observation cannot yield known latency.
- Missing expected coverage/history remains explicit. An empty cohort has no
  answer fraction. Native wider-source capability and TL2 availability are
  prerequisites, not invented fields or a second builder-question timer.

The owning proof runs the adapter through `suite.compose` and the strict suite
wire round trip. Existing generic suite validation cannot establish that the
category chose a substantive endpoint or retained its incomplete denominator.
Live intervals, source completeness, access and operation remain Unverified.

R1 first correction proof extends the existing timing-reuse boundary case: a
request attributed to synthetic ticket 4001 cannot reuse an otherwise matching
timing attributed to ticket 4999. Matching tickets and null (unknown) ticket
attribution retain the existing native timing value/unit. `review-r1-red.log`
records the contradictory-ticket case accepted before the correction.
