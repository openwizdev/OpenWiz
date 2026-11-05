# huntr approves work by risk tier, up to a tier Jake sets

ADR 0013 let huntr approve four named kinds; names don't scale to the many kinds of work an agent should do unasked. Work is sorted instead by what could go wrong: (0) report only, (1) tests and docs, (2) same behaviour, better inside, (3) behaviour fixes, each with its proof; huntr approves up to the tier Jake sets (today 3), and features, contracts, dependencies and the never-list stay proposals. New kinds come to Jake once as proposals.

Source: Jake, 2026-11-01: use risk tiers and a user-set ceiling for huntr, with new kinds proposed for approval once ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
