# Install rehearsal receipt v1

`openwiz.rehearsal.v1` is the receipt of one clean-machine install rehearsal (spec #2437): one
target's archive, built by one Packages run, installed the way a stranger's agent would install it
by `tools/rehearsal/rehearse.py`. Each rehearse job of that run writes one receipt as
`rehearsal.json` and uploads it as the artifact `openwiz-rehearsal-<version>-<target>`, where
`<version>` is the run's `version` input and `<target>` the receipt's `target`.

## Fields

One JSON object with exactly these keys, each once:

| Key | Value |
| --- | --- |
| `schema` | `"openwiz.rehearsal.v1"` |
| `version` | The version the run built, `0.<minor>.<patch>`; the version the rehearsal required, not the one the package claims |
| `source` | The run's source commit, 40 lowercase hex; the commit the rehearsal required |
| `target` | One of `aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-unknown-linux-gnu` |
| `archive_sha256` | The SHA-256, 64 lowercase hex, of the exact archive file rehearsed (`openwiz-<version>-<target>.tar.gz` in the run's `packages/` folder), or `null` when that folder held no single archive for the target |
| `manifest_sha256` | The SHA-256 of `openwiz-<target>.manifest.json` in the same folder, or `null` when it is missing |
| `status` | `"pass"` or `"fail"` |
| `steps` | An array of `{"name", "status"}` objects, each with exactly those two keys, `status` `"pass"` or `"fail"` |

The steps are named, in this order: `preflight`, `install`, `build_identity`, `setup`, `skills`,
`first_fleet_dry_run`. The runner stops at the first failed step, so `steps` is a prefix of that
order whose entries all pass except possibly the last.

- **`pass`** means `steps` holds all six names, in order, each `"pass"`.
- **`fail`** means a step failed: `steps` is not empty and its last entry is the one `"fail"`.

A receipt whose shape differs from this, a `pass` without all six passing steps, or a `fail`
without exactly one failed step, last, is unreadable, never a pass. A rehearsal that cannot
start (a usage or environment refusal) writes no receipt; its job fails and the receipt is
missing.

## What a pass proves

On a clean machine of that target, with no Rust, Cargo, Node or npm and no `room-cli`, in an
environment with no token, App key or CloudRoom variable, following the install skill pinned by
the candidate's `wizskills.lock` on its no-CloudRoom path ("This computer", Claude Code): the
installer's preflight passed with `room-cli` missing; `install install --assets` verified and
activated exactly these bytes as `version`, `source` and `target`; the installed program's
build identity read the same three; setup under the local host read `cloudroom_not_needed` and the
fake account; the skills reached a fresh Claude Code skills folder; and the first-fleet dry run's
previews and reads made no GitHub write and called no build tool. GitHub and the harness are
fakes. A pass never proves a real account, repository, harness, fleet or published release.

## The job

A rehearse job exits non-zero on `fail` and still uploads its receipt. The run's aggregate
check run `rehearsal` succeeds only when every rehearse job succeeds. The jobs read no secret,
hold `contents: read` only, check out with `persist-credentials: false` and pass no `GITHUB_TOKEN`,
`GH_TOKEN` or App variable to the rehearsal, which refuses to start when one is set.

## Example

Synthetic values:

```json
{
  "schema": "openwiz.rehearsal.v1",
  "version": "0.0.99",
  "source": "1111111111111111111111111111111111111111",
  "target": "x86_64-unknown-linux-gnu",
  "archive_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
  "manifest_sha256": "3333333333333333333333333333333333333333333333333333333333333333",
  "status": "pass",
  "steps": [
    {"name": "preflight", "status": "pass"},
    {"name": "install", "status": "pass"},
    {"name": "build_identity", "status": "pass"},
    {"name": "setup", "status": "pass"},
    {"name": "skills", "status": "pass"},
    {"name": "first_fleet_dry_run", "status": "pass"}
  ]
}
```
