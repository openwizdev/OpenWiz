# CloudRoom setup fixtures

Synthetic only. Version `gui-v9001`, the installer bytes, the account id and
email, and the sign-in nonce are invented; no file here was downloaded.

| File | Shape it follows (observed 2026-11-13, see `contracts/public-cloudroom-setup.v1.md`) |
| --- | --- |
| `setup.md` | CloudRoom's agent install guide, `https://www.cloudroom.dev/setup.md`: one GitHub release link per platform |
| `release.json` | GitHub REST `GET /repos/davidondrej/cloudroom/releases/tags/<tag>`: only the keys the tool reads |
| `SHA256SUMS.txt` | The release's own `SHA256SUMS.txt` asset: `<sha256>  <name>` lines |
| `Cloudroom-v9001-*` | Stand-ins for the installer assets: plain text, never run |
| `cloud-*.json` | `room-cli cloud status --json` (`CloudroomStatus`) and `room-cli cloud sign-in --json` (`{url}`), synthetic values |

Synthetic assumptions: `release.json` omits every key the tool does not read;
the `cloud-*.json` files carry only a subset of `CloudroomStatus`'s fields.
