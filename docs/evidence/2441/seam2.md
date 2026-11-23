# Seam 2 (#2441): the real job, dispatched on this branch

Packages, `workflow_dispatch`, version `0.0.99`. It builds and uploads artifacts only and publishes nothing.

| Run | Commit | rehearse-linux | rehearsal | Receipt |
| --- | --- | --- | --- | --- |
| [Red](https://github.com/openwizdev/OpenWiz/actions/runs/45081547061) | 74dfea5a, the planted break (one flipped byte in the downloaded archive) | failure at `Rehearse the install`: `step install: fail: exit 5, not 0`, installer reason `archive checksum mismatch` | failure | `fail`, steps `preflight` pass, `install` fail |
| [Green](https://github.com/openwizdev/OpenWiz/actions/runs/45082038020) | 84e2cbbe | success, all six steps `pass` | success | `pass`, six steps |

The green receipt's `archive_sha256` (`3a3a0a7f57bc9bc4f8ea3b76acb0ef3d51d1b24693b925e60683c47aba154415`) equals `sha256sum` of the run's own `packages/openwiz-0.0.99-x86_64-unknown-linux-gnu.tar.gz` and its `SHA256SUMS` line. Its `manifest_sha256` (`47caf2c27a68bcaccb01685519eb55b578fad63bf82f28497844aea9627e868f`) equals the uploaded `openwiz-x86_64-unknown-linux-gnu.manifest.json`. `source` is 84e2cbbef6efd2b6aa1e11df6efb7c3c993343c8.

The planted break was removed by the revert commit e771d81f, with no force-push. Two other dispatches on this branch were cancelled before finishing: a duplicate at the planted commit, and the run at a0f15ac9, which a later commit superseded.
