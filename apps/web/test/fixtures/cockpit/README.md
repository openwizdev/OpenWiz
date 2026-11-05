# Cockpit fixtures (#536)

Synthetic `openwiz.cockpit.v1` responses for the page proofs `test/browser/ck-*.test.mjs`. Every id, name, title, model and wording is invented; times start at `1800000000000` (2027-01-15 08:00:00 UTC), the proofs' paused clock.

- `target.json`: the design target's scene (partial): an answerable item, a risky `publish` item, an item with unknown wording, age and risk, an unassigned item, three projects (one unreadable), five placed agents and one not placed.
- `empty.json`: a complete, fresh, empty universe of two projects: the only shape that may say "Nothing needs you".

**synthetic_assumptions:** known wording, risk, waiting ages and the `publish` kind are future shapes (cockpit.v1's decision A): today's fleet sources emit none of them. `cockpit.mjs` derives the stale and partial variants from these files.
