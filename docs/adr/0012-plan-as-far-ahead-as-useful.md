# Plan as far ahead as useful; releases stay in order

Any version may be grilled, specced and planned whenever it is useful, however far ahead of the version being built: its tickets point at the exact tickets they need in earlier versions, a changed contract holds them for re-approval, and a changed plan starts nothing until Jake approves it again. Only versions being built or grilled get numbers; Later ideas stay unnumbered until their grill starts (P1). Code still reaches `main` as soon as it is reviewed, and release branches, live checks and releases still go in version order. This supersedes ADR 0006's limit of one version ahead; the rest of ADR 0006 stands.

Source: Jake, 2026-11-01: plan as far ahead as useful while retaining dependency, approval and release-order safeguards ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
