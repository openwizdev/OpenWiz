# Infra work has no version

Work that isn't a product feature (CI, tests, test helpers, the fleet skills' fixes) doesn't wait for a version and doesn't become one: it merges when it's reviewed and ships with whichever version is released next. A small change is an issue the user approves on its own (the `triage` skill); a bigger one is an infra spec, grilled, planned and approved like any spec, with its own fleet running in parallel with the product versions. Versions stay what the product can do, each with its live check and release (ADR 0006).

Source: Jake, 2026-10-31: infrastructure work uses its own approval flow without becoming a product version ([private record](https://github.com/jparker2006/ClosedWiz/issues/1276#issuecomment-6704797460)).
