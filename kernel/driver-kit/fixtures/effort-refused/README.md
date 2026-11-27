# A driver that refuses effort

Login: stays on your machine
Effort: passed as `--effort <level>`, by harness:

| Harness | Effort |
| --- | --- |
| `claude` | `--effort <level>` |
| `fake-harness` | can't (it has no effort option) |

The kit's own fixture: it lists effort in `can`, and refuses it for `fake-harness` with the refusal text.
