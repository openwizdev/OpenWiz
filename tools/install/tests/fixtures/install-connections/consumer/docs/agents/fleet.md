# Fleet settings

Synthetic settings, as the setup skill's template writes them.

## Builder

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | synthetic-model | `--model synthetic-model` |
| Effort | High | `--reasoning-level high` |

Source: synthetic owner, 2026-11-06.

## Reviewer

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | synthetic-reviewer | `--model synthetic-reviewer` |
| Effort | High | `--reasoning-level high` |

Source: synthetic owner, 2026-11-06.

## Test commands

| # | Folder | Command | CI check |
| --- | --- | --- | --- |
| 1 | root | `make test` | `test` |

Source: the synthetic consumer's CI workflow.

## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `test` | 1 | `main` |

Source: the synthetic consumer's CI workflow.

## Standing merge rules

None yet: every merge waits for the user.

Source: synthetic owner, 2026-11-06.
