# OpenWiz service contract, version 1 (`openwiz.service.v1`)

The always-on service and its server went in #1264. What still runs is the private
state it left: the config that `openwiz loop on|off` reads to name the local
operator, and the state directory's safety checks. The schema is
[`service.v1.schema.json`](service.v1.schema.json); only its `config` definition
is still read (`crates/cli/src/state/loops/`). Its status, state and record
definitions describe the retired service, and no code writes them.

## The config

`service/config.json` in the state directory, `openwiz.service-config.v1`.
OpenWiz never writes it, and on a fresh install nothing else does either: the
installer creates only `service/`. The owner writes the file by hand (owner-only,
0600) before using `openwiz loop on|off`; until then both refuse.

Example (synthetic; set `repository`, `project` and `operator` to your own,
`operator` a nonblank, NUL-free name). The tests read this line too:

```json
{"schema": "openwiz.service-config.v1", "repository": {"owner": "synthetic-owner", "name": "synthetic-repo"}, "operator": "synthetic-operator", "project": "prj_syn_0001", "orchestrator_thread": "thr_syn_0001", "service_issue": 901, "github_app": {"app_id": 1001, "installation_id": 2002}, "tick": {"every_s": 300}, "health": {"every_s": 60}, "server": {"port": 7370, "allowed_host": "openwiz.example.com", "probe_timeout_s": 10}}
```

The reader checks the whole document against the schema's `$defs/config`
(required: `schema`, `repository`, `project`, `orchestrator_thread`,
`service_issue`, `github_app`, `tick`, `health`, `server`), refuses duplicate
keys, non-integer spellings and a `server.port` above 65535, and guesses no
value. Then:

| Field | Used for |
| --- | --- |
| `repository` | `owner` and `name`. A loop switch runs only in a checkout whose one `origin` is this repository |
| `project` | The CloudRoom project id a loop switch must name |
| `operator` | The local operator identity a loop switch records as its actor: nonblank and NUL-free, set at install, rechecked from this file on every switch, never inferred from a repository, definition or caller. Absent or invalid, both switch writes refuse |
| `github_app` | `app_id` and `installation_id`: ids, never secrets. The key is a file (below) |
| `orchestrator_thread`, `service_issue`, `tick`, `health`, `server` | Required by the schema; nothing reads them now |
| `loops`, `notifications`, `events`, `decision_repositories` | Optional; validated when present; nothing acts on them now |

## The state directory

`$OPENWIZ_STATE_DIR`, when non-empty, must be absolute and takes precedence.
Otherwise an absolute `$HOME` is required: on macOS the directory is
`~/Library/Application Support/openwiz`; elsewhere `$XDG_STATE_HOME/openwiz` when
`$XDG_STATE_HOME` is absolute, else `~/.local/state/openwiz`. It must be absolute
with no `.` or `..` components, owner-only (0700), and never inside a repository
(`crates/cli/src/state/`).

| Path, under the state directory | Mode | What |
| --- | --- | --- |
| `service/` | 0700, required | The service's directory; never inside a repository of its own |
| `service/config.json` | 0600, required | The config |
| `service/state.json` | 0600, optional | The retired service's memory; read only through its checked descriptor |
| `service/app/` | 0700, optional | The GitHub App's directory; never inside a repository of its own |
| `service/app/private-key.pem` | 0600, optional | The App's private key: read only by the App's signing, never copied, printed or logged |
| `service/clone/`, `service/builds/` | 0700, optional | The retired self-update's clone and builds |

Every check fails closed and names the path: a symlink, a wrong type, another
owner, or any group or other permission refuses. A loop switch reads nothing
until these checks pass.
