# A driver whose start runs a short-lived child

Login: stays on your machine
Effort: passed as `--effort <level>`, by harness:

| Harness | Effort |
| --- | --- |
| `claude` | `--effort <level>` |
| `fake-harness` | can't (it has no effort option) |

The kit's own fixture: it refuses effort for `fake-harness` with the refusal text. Its main start runs a child holding a credential on its command line, which exits before start answers.
