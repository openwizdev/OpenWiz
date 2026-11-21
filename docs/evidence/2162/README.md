# #2162 evidence

- `red.log`: `tools/install/tests/installer/test_root_safety.py` at the red commit, before the fix: 8 failures, each at the missing behaviour (install accepts a root or state root holding other files; `install remove` is a usage error). Temporary paths are replaced with placeholders.
- `green.log`: the same proof after the fix, all 8 tests passing.
- `red-lock.log`: the lock proof added for the planner's ruling, before the fix: `install remove` previews instead of refusing while `install.lock` is held.
- `red-r1.log`: review R1, before the fix. With `<state>/service` linked to another folder, `install remove --yes` reports `removed` and deletes that folder's `config.json` and `app/`.
