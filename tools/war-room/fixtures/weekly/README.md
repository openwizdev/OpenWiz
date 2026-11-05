# WR7 weekly report proof inputs

`test_weekly.py` generates every history in memory: one record per five-minute
boundary over two synthetic weeks, each with a WR3-shaped `stage_waits`
provider. Waits, limits, links, hashes, paths and ticket numbers are synthetic
assumptions; one case also reads WR3's real projection of TL2's demonstration
fixture. `changes.json` holds two synthetic recorded changes, one outside both
weeks. Nothing here is a live observation.

`red-first.log` is the failing-first run, before `weekly.py` existed;
`green.log` is the same proof passing at the hand-back commit.
