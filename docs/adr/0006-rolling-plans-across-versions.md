# Plans roll across versions; releases are cut and accepted in order

**Superseded in part by [ADR 0012](0012-plan-as-far-ahead-as-useful.md)** (2026-11-01): planning is no longer limited to one version ahead. The rest stands.

A ticket starts the moment its real blockers merge, whatever version they belong to: the next version is grilled against the current version's planned done state, and its tickets point at the exact tickets they need, one version ahead and no further. Tickets depend on contracts, not implementations, and a changed contract holds its dependents for re-approval (X2). Code reaches `main` as soon as it is reviewed; each version's release branch is cut when its last ticket merges, and live checks run in version order. This replaces "one version at a time" (acceptance lesson 7) for building, and keeps it for accepting and releasing.

Source: Jake, 2026-10-30: dependency readiness controls building across versions, while acceptance and release remain ordered ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
