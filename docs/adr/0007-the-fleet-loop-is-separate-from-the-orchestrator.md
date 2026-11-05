# The fleet loop runs apart from the orchestrator

The five-minute loop that moves tickets (start reviewers, route findings, merge, unlock, archive) runs in its own fresh thread on each tick, reading its state from GitHub, and wakes an agent only when something is due; the project's orchestrator only grills, plans and talks to Jake. Running the loop inside the orchestrator's thread, as the first fleets did, filled its context with loop work and blocked grilling while the loop ran; in 0.0.6 the loop's mechanical part becomes OpenWiz code.

Source: Jake, 2026-10-30: run fleet maintenance separately from the project conversation ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
