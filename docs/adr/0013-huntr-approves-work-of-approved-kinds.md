# huntr approves work of the kinds Jake approved once

Until now nothing was built without Jake approving its spec or plan graph (ADR 0008), apart from the overnight run's small fixes. As an interim policy, Jake approves kinds of work once instead of each ticket: huntr approves bug fixes, flaky tests, missing tests and stale docs by itself, within a never-list and a size cap, acting liberally within those safety bounds, and everything bigger (cleanups, features, side specs) still comes to Jake as a proposal; it never decides what to build, which keeps the 0.1.0 design's restriction on decision models choosing work intact.

Source: Jake, 2026-11-01: delegate bounded routine work to huntr and bring larger work back as proposals ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
