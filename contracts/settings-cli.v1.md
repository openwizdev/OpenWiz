# Settings command contract v1

`openwiz.settings-cli.v1` fixes the command interface for the home settings
file described by `contracts/settings.v1.md`. That contract owns the stored
fields and rules. The launcher, Wiz skills and board server call this command
for reads and writes. Their tests can use the
[answer fixtures](fixtures/settings-cli/valid/) in place of the command.

## Forms

| Invocation | Meaning |
| --- | --- |
| `openwiz settings show [<path>] [--json]` | Read the home settings file, or one value at the given path. |
| `openwiz settings set <path> <value> --by <settings tab\|Wiz chat> [--json]` | Set one value after validating the proposed settings. |
| `openwiz settings undo [<n>] --by <settings tab\|Wiz chat> [--json]` | Restore the settings from `n` versions back as a new version. The default is 1. |
| `openwiz settings history [--json]` | List the retained earlier versions, newest first. |
| `openwiz settings restore [--force] [--json]` | Rebuild the local file from the home repository's `openwiz/settings` branch. Replacing an existing file requires `--force`. |
| `openwiz settings fill [--json]` | Create the first file from the harnesses and accounts signed in on the home machine. Refuse if a file exists. |

A path is a dot-separated sequence of member names from the settings file.
Examples include `roles.reviewer.model`, `accounts.<label>.reserved` and
`keys.<NAME>.set_at`. Use `\.` for a literal dot and `\\` for a literal backslash
in a member name.
A show path that selects no field is a usage error. A set path may add a
member to a keyed object when the settings contract permits it.
A `set` value is one argument. A complete JSON value keeps its JSON type,
and other text is taken as a string. Use `--by 'settings tab'` or
`--by 'Wiz chat'` as a single option value. Only the owner's Settings tab
or Wiz acting on the owner's request may initiate a settings change.
Undo takes a positive integer and refuses when the requested version is
outside the retained history. An undo can itself be undone.

## Answers

With `--json`, a settings answer is one document on stdout followed by a
newline. It carries `schema: "openwiz.settings-cli.v1"`, `kind`, and exactly
the fields listed below. See the [JSON Schema](settings-cli.v1.schema.json).

| Kind | Fields | Exit |
| --- | --- | --- |
| `show` | `settings`, the whole settings object with the key metadata described below. | 0 |
| `show_path` | `path` and its JSON `value`. | 0 |
| `changed` | The saved `version` and `changes`, an array of objects with `path`, `old` and `new`. Used by set, undo and fill. A field absent on either side is represented by JSON null on that side. | 0 |
| `restored` | `version` from the restored file. | 0 |
| `history` | `entries`, at most 10 objects with `version`, `changed_at`, `changed_by` and `paths` changed in that version. | 0 |
| `missing` | No extra fields. The requested settings file is absent. | 3 |
| `refused` | `reason`, a nonempty single line. The file is byte for byte unchanged. | 5 |

Versions are positive integers. Timestamps use UTC with a trailing `Z`,
at seconds precision. Each key row is keyed by name and shows only `store`,
`entry` (the store's entry name), `opt_in`, `on`, `set_at` and
`last_used_at`. For `show`, `last_used_at` is the latest UTC use time for
that key in the home's key-use log, or `never` when it has no recorded use.
The same projection applies when a path selects the key map, a row or
one of its fields. `last_used_at` is read-only and stays out of the file.

Every answer, including nested settings, path values, changes, history and
diagnostics, must be free of key values and tokens. Show key names and their
allowed metadata only. Sanitize errors before rendering them and do not echo
a rejected value or raw input. The schema checks the answer envelope and the
projected key rows in a whole-file show. The stored contents and the meaning
and safety of path values come from the settings contract and the producer.

## Text and exits

In text mode, show prints the settings or selected value as JSON without the
answer envelope. History prints one entry as compact JSON per line in the
same order as `entries`. Restore prints `version <N>`. Set, undo and fill
print one line per change, then `version <N>`.

```text
changed <path>: <old> -> <new>
version <N>
```

Render the old and new values as compact JSON so that a change takes one
line. A refusal is one line on stderr. Missing-file and read errors also
give a one-line reason on stderr in text mode.

The numeric exits follow [CLI v1](cli.v1.md#fixed-exits-and-existing-results).

| Exit | Meaning |
| --- | --- |
| 0 | Done. |
| 1 | Settings file unreadable or invalid, with a one-line reason. |
| 2 | Usage. |
| 3 | No settings file for the requested read or restore. Never substitute defaults. |
| 5 | Change refused. The file stays byte for byte unchanged. |

With `--json`, exits 1 and 2 use the shared `openwiz.cli-error.v1` document
with `read_failed` and `usage`, respectively.
