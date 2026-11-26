# A planted driver

Login: stays on your machine
Effort: passed as `--effort <level>`, by harness:

| Harness | Effort |
| --- | --- |
| `claude` | `--effort <level>` |
| `fake-harness` | can't (synthetic) |

The kit's fixture: its README says `fake-harness` can't take effort, yet it takes a start with effort for it.
