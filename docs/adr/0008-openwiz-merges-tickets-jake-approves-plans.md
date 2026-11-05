# OpenWiz merges tickets; Jake approves plans

Approving a plan graph is the authority to merge every ticket in it: a ticket merges as soon as its reviewer (a different model family) approves that exact commit and CI is green, with the base unchanged and the merge read back; the reviewer's approval is the merge decision and the loop performs it. Jake's clicks are specs, plan graphs, live runs, releases and publishing. This supersedes the 0.0.0 design's requirement that the user perform merges on GitHub (frozen `release/openwiz/docs/decisions.md`, open decision 15) and the standing approval limited to fixture pull requests of 2026-10-30. Richer decision models are for dot-context SF2, past 0.1.0.

Source: Jake, 2026-10-30: plan approval delegates ticket merges subject to exact-head review, CI and verified merge safeguards ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
