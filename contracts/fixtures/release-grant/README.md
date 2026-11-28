# Release grant fixtures

These records use synthetic grant text, dates and private-record pointers. `no-grant.md` reproduces the current non-grant Approval rules table.

| Fixture | Patch exit and reason | Pull exit and reason |
| --- | --- | --- |
| `no-grant.md` | 1, no standing release grant | 1, no standing release grant |
| `patch-and-pull.md` | 0, standing release grant recorded | 0, standing release grant recorded |
| `patch-only.md` | 0, standing release grant recorded | 1, no standing release grant |
| `minor.md` | 1, every 0.x.0 stays the owner's ship call | 1, every 0.x.0 stays the owner's ship call |
| `missing-pointer.md` | 1, missing or invalid standing release grant decision or private-record pointer | 1, missing or invalid standing release grant decision or private-record pointer |

Run `python3 -I tools/release/test_grant.py` from the repository root.
