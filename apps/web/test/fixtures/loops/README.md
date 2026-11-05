# Loops fixtures (#549)

Synthetic `openwiz.loops-view.v1` responses (contracts/web-api.v1.md, "Loops view") for the page proofs `test/browser/lp-*.test.mjs`. Every id, name, owner, reason and amount is invented; times start at `1800000000000` (2027-01-15 08:00:00 UTC), and the read, and the proofs' paused clock, is `1800004800000` (09:20:00 UTC).

- `target.json`: the approved design target's scene (the approved loops brief), in the server's order: three loops that need a look (a failed check, an unsure agent start with unknown cost, a timed-out event check), then five healthy ones (two quiet, one that started an agent, a reminder not run yet, and one switched off).
- `empty.json`: a read with no loops defined.

`loops.mjs` serves them, answers and records the switch routes, and derives the other variants in the proofs.

**synthetic_assumptions:** the whole shape is new with #549 and was not observed live; reasons are invented executor wording.
