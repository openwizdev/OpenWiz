# P9: releases from their own repository

Fixture evidence only. No live release or remote write is authorized.

- A clean public release branch stages its own complete tree and history, without a separate source repository. `test_open.py` checks the exact head and tree. The old checker replaces that head with a new export commit.
- An empty private file outside the plan fails F1 before staging. A thread identifier outside the plan fails T1. Existing selected-file scans miss both because they discard unlisted files. The first run incorrectly passes both plants; see red.log.
- Existing claims, changelog, historical scans and build orchestration remain covered by the release fixture suites.
- Changelog needs no private checkout: the existing sparse-checkout fixture runs the action tests with private blobs absent.
- Release destinations and generated links follow a synthetic origin; publisher fakes exercise only local repositories.

Policy reads at base a60793be28614531d914dfb41732ec886cc86fcf:
AGENTS.md 2b9ae846b0dd4fcb93625ae1566b448f8de0e28a;
fleet.md 99aaafc6905d691c80ad413370bb4cb1f3a8f3bd;
helpers.md 9a8628b0deabf3ed320b856af2f0117723fab15b.

Helper: scout, changelog and publisher seams, base above, ISSUES; 12 pointers checked, 12 used, 0 ignored/wrong. Archived. Durable snapshot/window saved by check-helpers.sh; `clean #1281: nothing changed but the writes you named (branches 0, comments 2)`.

The single input is now the public release clone. Every tracked path must have
its own same-path ledger row; only CHANGELOG.md/ROADMAP.md may use generated
markers. A staged tree gets the O3 privacy command again. The publisher accepts
ordinary release ancestry, with source/base ancestry checks, and requires the
new privacy check in its report. Historical backfill gates remain.

Helper durable records:
Snapshot and completed window are retained in private helper-check state;
no concrete location is carried in this public proof.

All checklist items relevant to release guards, full reads, counts, isolated
fixture state, hash/mode binding, no-write checks, owned paths and forward seams
were checked. No dependencies or Rust crates changed. The unchanged changelog
sparse-checkout proof covers the no-private-file criterion.
