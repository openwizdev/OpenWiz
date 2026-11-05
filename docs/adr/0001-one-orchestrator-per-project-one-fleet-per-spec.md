# One orchestrator per project, one fleet per spec

Each project has exactly one orchestrator, and it runs one fleet per spec, any number at once. We considered "a fleet is an orchestrator thread and everything it spawned", which CloudRoom's parent chain shows for free; but with one orchestrator per project every fleet shares that parent, so an agent's fleet is found through its work instead: agent → branch → pull request → ticket → spec.

Source: Jake, 2026-10-30: each project has one orchestrator, with a separate fleet for each spec ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
