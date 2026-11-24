# OpenWiz release manifest contract, version 1 (`openwiz.release-manifest.v1`)

Every OpenWiz release carries one manifest, `release-manifest.json`, at the repository root and attached as a GitHub release asset of the same name. It pins the three parts that ship as one matched set: the kernel version, the WizSkills pin (equal to `wizskills.lock`), and the records-contract version they write. The JSON schema is [`release-manifest.v1.schema.json`](release-manifest.v1.schema.json); this file adds the equality and strict reading rules a schema cannot express.

**Contract first** (#3138, MS0 of spec #3137). Downstream consumers: MS3 (#3141) generates `release-manifest.json`, checks it against `wizskills.lock` in CI, and attaches it to each GitHub release; MS5 (#3143) reads the current and previous manifests in WizSite CI to download the matching WizSkills golden archives; MS6 (#3144) gates each release candidate on that golden job.

Authority: ADR 0021 (`docs/adr/0021-app-skills-kernel-ship-as-a-matched-set.md`). Jake, 2026-11-24: approved D1-D3 for 0.1.2 ([private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7139385706)).

## Fields

| Field | Type | Rule |
| --- | --- | --- |
| `schema` | string | Always `openwiz.release-manifest.v1`. |
| `kernel_version` | string | Kernel semver `MAJOR.MINOR.PATCH` matching `^(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)\.(0\|[1-9][0-9]*)$`. No leading `v`, no leading zeroes. |
| `wizskills` | object | Exact keys `version`, `commit`, `tree`, equal to `wizskills.lock`. |
| `wizskills.version` | string | WizSkills semver `MAJOR.MINOR.PATCH`, same pattern as `kernel_version`. |
| `wizskills.commit` | string | 40 lowercase hexadecimal characters (`^[0-9a-f]{40}$`), the pinned WizSkills commit. |
| `wizskills.tree` | string | 40 lowercase hexadecimal characters (`^[0-9a-f]{40}$`), the pinned WizSkills Git tree. |
| `records_contract` | integer | Positive whole number (`>= 1`), matching the records-contract version under [records v1](records.v1.md) (D3). For v1, `1`. |

## Rules the schema cannot express

1. **Equal to `wizskills.lock`.** The `wizskills` object's `version`, `commit` and `tree` must equal the repository's `wizskills.lock` on all three fields. Any mismatch fails CI (#3141).
2. **Strict UTF-8 JSON.** Read as one JSON object with exactly the schema's keys, each once, at both the top level and `wizskills`. A missing key, extra key, duplicate key or positional array is refused.
3. **Exact integer.** `records_contract` is a JSON integer (`1`, never `"1"`, `"v1"`, `1.0`, `true` or `0`).
4. **Fail closed.** An unknown `schema` value, missing field or malformed value is refused; no reader guesses a missing pin or defaults `records_contract`.
5. **Release asset.** Each GitHub release attaches `release-manifest.json` verbatim from the tagged commit.

## Example

All hashes below are synthetic.

```json
{
  "schema": "openwiz.release-manifest.v1",
  "kernel_version": "0.1.2",
  "wizskills": {
    "version": "0.5.0",
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "tree": "89abcdef0123456789abcdef0123456789abcdef"
  },
  "records_contract": 1
}
```
