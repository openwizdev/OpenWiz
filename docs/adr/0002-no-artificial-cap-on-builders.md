# No artificial cap on builders

OpenWiz sets no limit on how many builders run at once, per fleet or overall; the point is 100+ builders across many fleets. The only limits are real ones (CloudRoom refusing a start, CI or review capacity), and OpenWiz reports them honestly and queues, never failing silently. We had proposed a cap of 5 per fleet and 15 overall to bound cost; Jake rejected it.

Source: Jake, 2026-10-30: builder concurrency has no artificial ceiling ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
