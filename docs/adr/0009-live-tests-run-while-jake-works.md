# Live tests run while Jake works, scoped to their own threads

Live tests no longer wait for an overnight window, and Jake keeps using CloudRoom and his Mac throughout. The overnight rule came from 0.0.1, whose check compared every thread before and after; tests now stay as strong by scoping: every write and check touches only the test's own threads and processes, the read-safety check judges only threads quiet before the run and excludes Jake's activity, and Jake's part is a few short steps. Each version is published as soon as its live test passes.

Source: Jake, 2026-10-31: scoped live tests may run alongside normal owner activity without an overnight pause ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
