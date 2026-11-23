# Harness rows, version 1

A **harness row** is how one more agent CLI runs on the [local driver](README.md). It is a small data file in its own folder, not a copied driver. The driver keeps doing everything else the same way: the clone, the approvals, the supervisor, and the stop that ends the whole process tree. `claude` and `codex` stay built in and unchanged.

## 1. The row

A row is `adapters/local/harnesses/<harness>/row.json`, read with standard-library JSON, never run as code. It is one JSON object with each key once, with exactly these fields, plus the two optional ones below:

| Field | What it holds |
| --- | --- |
| `harness` | The start field's value, equal to its folder name. Never `claude` or `codex`: no row may use a built-in name |
| `program` | The command found on `PATH`: letters, digits, `.`, `_` or `-`, no `/` |
| `start`, `wake` | Argument lists. Each placeholder fills a whole argument: `{prompt}`, `{model}`, `{session}`, `{mode}` and `{effort}` |
| `session` | How the driver knows the session id: `{"chosen": "uuid"}`, `{"json": [<key path>]}` or `{"pattern": "<regex with one group>"}` |
| `modes` | Each mode value the owner may approve, mapped to the fixed arguments it adds where `{mode}` is |
| `env` | Fixed, non-credential variables the turn gets, such as a CLI's local-backend switch |
| `effort` | An effort map, or `"none: <one line why, naming the primary source>"` (section 4) |
| `login` | One line saying where the CLI's own login lives |
| `daemon` | `none`, or one line naming the background process the CLI may start and how stop ends it |
| `signed_out` (optional) | A list of fixed, case-insensitive patterns, specific to this CLI, that mean it isn't signed in; each is matched anywhere in a line of the turn's output, a JSON line included |
| `login_command` (optional; required with `signed_out`) | The exact command the user runs to sign in, such as `example-cli login`. `login` keeps its meaning: where the login lives |

- **Placeholders.** A placeholder fills a whole argument, never part of one (`--model={model}` breaks the row), and appears at most once in a list. `{prompt}`, `{model}` and `{session}` each become one argument. `{mode}` splices the approved mode's fixed arguments, and `{effort}` the requested effort's (section 4). A fixed argument holds no placeholder.
- **Start** holds `{prompt}`, `{model}` and `{mode}`. **Wake** holds `{prompt}`, `{mode}` and `{session}`: wake must hold `{session}`. Start holds `{session}` only when the session is chosen.
- **Session ids** match `[A-Za-z0-9._:-]{1,100}` and must not look like a credential by the kit's check (`holds_credential` in `kernel/driver-kit/kit.py`).
  - `{"chosen": "uuid"}`: the driver makes a UUID before the first turn, saves it, and passes it at start and at every wake.
  - `{"json": [<key path>]}`: the first JSON line of the run's output that has that path of object keys.
  - `{"pattern": "<regex>"}`: the regex's one group, on the first line of the run's output that it matches.
  - A reported id (`json` or `pattern`) is read from the run's log once the turn has printed it, then saved. When it isn't there yet, wake refuses with a D3 error and starts nothing.
- **Modes:** each key is a mode value (a letter, then up to 39 letters, digits, `_` or `-`), each value a list of fixed arguments (it may be empty). The owner approves one mode per repository and harness, as for a built-in, and the driver passes only that mode's arguments.
- **Signed out:** each `signed_out` pattern is one line, compiles as a regular expression, holds no placeholder and nothing credential-shaped. No pattern is a program: the driver only matches it. A row's pattern matches anywhere in a line of the turn's output, case-insensitively, inside a JSON line too; the driver's own sign-in diagnostics keep their line-start rule. `login_command` is one line of up to 200 characters, with no placeholder and nothing credential-shaped; the driver never runs it.
- **Env:** each name is capitals, digits and `_`, starting with a capital and not with `OPENWIZ_`; each value is one line that passes the kit's `holds_credential`, alone and as `NAME=value`. The driver adds `env` to the turn's environment.

## 2. The row folder

`adapters/local/harnesses/<harness>/` holds:

- `row.json`, the row;
- `fake`, the row's fake CLI: an executable that parses its own CLI's command line, exits 2 on any command line the real CLI's documentation doesn't allow, and calls [`fixtures/fake_cli.py`](fixtures/fake_cli.py) for the rest (section 6);
- `README.md`: a `# ` title, then on the next line `Login: <the row's login>`; one line `Effort: <the exact flag or setting>`, or exactly `Effort: none` for a row that can't set effort (the line driver v1's effort change, EF4 of #2471, points at); the commands; and the census check resolved from primary sources, with links;
- an optional `test_row.py`, which the runner also runs;
- `evidence/`, the row's red and green runs.

A row ticket owns only its folder. No row edits the driver, this file, the local README, CI or the release lists: the runner discovers rows, and CI runs only the runner.

## 3. What the driver does with a row

- It loads a row only for the harness that a start names, and only when that harness isn't built in. A row that is missing, has a repeated key or breaks this contract is a D3 error that names the row file, never its contents, and starts nothing. The "use one of" error lists the built-ins plus the row folders.
- The row's `program` must be on `PATH`, and the approved mode must be one of its `modes`; otherwise `start` refuses and starts nothing.
- A turn gets the row's `env` added to its environment, and only the approved mode's arguments.
- When a first turn that ended at once printed a line its row's `signed_out` matches (or one of the driver's own sign-in diagnostics), `start` fails, even when the turn exited 0, with `the harness is not signed in`, a D3 error, and its `next` names the row's `login_command`, never a generic failure.
- What stays the same: stop (it ends the whole process tree), the approvals, the fleet.md `Harness permission mode` row, the first-turn watch and the credential check.

## 4. Effort (J318)

A user must always be able to set effort. Each row takes exactly one of two forms:

- **It passes the user's effort to the CLI:** an `effort` object maps each effort value the user may set (an effort id: letters, digits, `.`, `_` or `-`, up to 40) to either a non-empty list of fixed arguments it adds where `{effort}` sits, or `{"env": {"<NAME>": "<value>"}}`, the fixed `env` setting it makes. It names the exact flag or setting. An effort flag that needs another flag with it, such as a model, keeps both in the same argument list.
- **The host can't set effort:** `"effort": "none: <one line why, naming the primary source>"`.

Both `row.json` and the row's README say which form it is. `{effort}` may appear in `start` only, or in both `start` and `wake`, because some CLIs refuse an effort flag on resume; it appears only when some effort value adds arguments. A row must not claim an effort value that its CLI silently ignores for some models: it declares `none` instead.

When a start carries an effort, the effort reaches the CLI. When the row's effort is `none`, or doesn't list that value, the start is a D3 refusal that starts nothing, and its `next` is exactly:

`this host can't set effort: remove the effort for this harness in your Models table or Roster to run it at the host's default`

A start with an effort never falls back to a default. Built-in `claude` and `codex` refuse an effort the same way until their flags are added.

**Hooks for driver v1's `effort` start field (#2471).** That ticket adds the field to driver v1, the schema and `version`'s `can` list (the local driver lists `effort` there, because `claude` and `codex` take it); `version` carries no per-row note, since its schema is fixed, and each row's README `Effort:` line says what the row takes. Until then the driver is wired below the field: `command(state, woken)` turns a run's row and request into the turn's command line and environment, `effort_of(harness, row, effort)` gives an effort's arguments and environment or the refusal above, and `start` reads `request.get('effort')` before it saves anything. Turning the field on is adding `effort` to the driver's `START` fields. Its field name and values are matched once its contract is posted.

## 5. The kit check for rows

`python3 -I adapters/local/test_harnesses.py` checks every folder in `adapters/local/harnesses/` (and, first, its own planted rows); `--rows <dir>` checks the folders in `<dir>` only. For each row it:

1. checks `row.json` against this contract, with the driver's own loader, and that the driver refuses a row that breaks it;
2. checks the folder: `fake` is executable, and the README's `Login:` and `Effort:` lines;
3. puts no-op stubs for the known agent CLIs on `PATH`, with only the row's `fake` ahead of them, so no real agent CLI ever runs;
4. runs `kernel/driver-kit/kit.py --tracker` against the driver, with the row's `fake` on `PATH` under `program` and the fake `gh`, and needs the kit's five pass lines;
5. needs the wake turn to have got the same session id as the start turn;
6. needs the turn to have got each `env` value;
7. needs the background process, when the row declares one, to have ended after stop, and none when it declares `none`;
8. for a row with `signed_out`, needs a first turn whose fake prints its signed-out line to fail `start` with `the harness is not signed in` and a `next` naming the row's `login_command`;
9. for each listed effort value, needs a start carrying it to put its arguments on the fake's command line or its setting in the fake's environment; and needs a start with an effort the row can't take to refuse with the `next` above and start nothing;
10. runs the row's `test_row.py`, if there is one.

It prints one line per row: `pass <row>: ...`, or `fail <row>: <rule>: <reason>`, where the rule is `row.json <field>` for a contract rule, or `folder`, `kit`, `session`, `env`, `daemon`, `signed_out`, `effort` or `test_row.py`. A folder with no `row.json` gives `fail <row>: row.json is missing`. The kit's files are not changed.

## 6. The fake library

[`fixtures/fake_cli.py`](fixtures/fake_cli.py). A row's `fake` parses its command line, then calls `fake_cli.turn(prompt, model, session, announce, daemon, signed_out)`. The library posts and edits the builder note in `KIT_TRACKER`, detaches a worker that waits to be stopped, records each turn's session id, arguments and the row's environment, prints the session id with `announce` when the row reports it, prints `signed_out`, its CLI's signed-out line, and exits with `signed_out_exit` (1 unless the row's CLI exits 0) when the runner asks (`FAKE_CLI_SIGNED_OUT`), and, when told to, starts a double-forked background process that stands in for a CLI's service.

## 7. The merge gate

As driver v1 section 3 sets it for any new host, a row merges only after its live check records 5 of 5 at the row pull request's approved head: a person signs in to that CLI on their own machine and runs the kit against the local driver with that harness, on one throwaway ticket.
