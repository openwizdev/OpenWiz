# WR3 stage-wait proof inputs

`test_stage_waits.py` reads TL2's own sanitized demonstration outputs from
`tools/factory-metrics/fixtures/stage-waits/` (`journeys.json`,
`stage-waits.json`); TL2 owns them. The tests copy them into a temporary root and
write synthetic `limits.conf` files there. The settings evidence link
(`example/factory`, commit `ccc…`) is a synthetic assumption, not a real source.
No value here is a live observation.

`red-first.log` is the failing-first run, before `stage_waits.py` existed;
`green.log` is the same proof passing at the hand-back commit.

Review 1: `review-1-red.log` is the run of the R1–R4 proofs before their fix
(most cases fail on the new `cohort_since`/`settings_read_at` selection inputs;
each break is also shown by the review's own reproduction). `review-1-green.log`
is the same proof passing. The R1 and R4 variants are made by editing TL2's
fixture in memory, rebinding its journey hash and passing TL2's own validator;
the shared PR (4401 closing 4301 and 4303) is a synthetic assumption.
