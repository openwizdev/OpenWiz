# Factory stage-limit settings, v1

TL1 (#2336, spec #2185 revision 4) pins the shared settings/reader seam.
The five goals follow the confirmed time-limit decision of 2026-11-10
([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6765875416)).
All examples below are synthetic. This contract neither enables effects nor
changes the ops record/claim protocol.

## Settings

`limits.conf` is the editable source; the reader has no built-in fallback values.
Every read requires exactly one assignment for each of these five stage keys:

| Key | Default minutes | Goal begins |
| --- | ---: | --- |
| `builder_start` | 10 | Ticket unblocks with all actual start gates satisfied |
| `reviewer_start` | 5 | Required CI is green at the eligible current head |
| `merge` | 5 | Valid approval at the eligible current head |
| `fix_after_changes` | 30 | CHANGES requiring a resulting fix |
| `builder_question_answer` | 15 | Builder question requiring a substantive disposition |

The file is ASCII text, with LF, CRLF or CR newlines and an optional final
newline. Blank lines and whole-line `#` comments are allowed. Spaces and tabs
may surround an assignment and its `=`. Order is immaterial. Each value is a
positive decimal integer spelled `[1-9][0-9]*`, in minutes. Zero, signs,
leading zeros, fractions, exponent notation, booleans, empty values, inline
comments, non-ASCII text and other control characters are invalid. No value
means unlimited or disabled; there is no sixth CI/conflict stage.

Synthetic valid edit (builder goal changed to 12 minutes):

```text
builder_start=12
reviewer_start=5
merge=5
fix_after_changes=30
builder_question_answer=15
```

Missing, duplicate (even with the same value), unknown or malformed settings
invalidate the entire file. An absent/unreadable file or decoding failure also
refuses the entire read. Nothing substitutes defaults or returns partial goals.

## Reader and reported settings

`limits.py` uses only Python's standard library. Python consumers load it using
the existing metrics tooling's `importlib.util.spec_from_file_location` pattern
and call `read(path)` with a string or `Path`. It reads only that file and
returns a fresh JSON-compatible dictionary on success. I/O failures raise
`OSError`; invalid content/decoding raises `ValueError`. Consumers must propagate
refusal, never treat it as an unlimited interval or an empty benchmark.

The CLI is `python3 -I tools/factory-metrics/limits.py [--settings PATH]`.
Without `--settings`, it reads the `limits.conf` beside the script, regardless
of the working directory. An explicit path selects only that file; it is never
merged with defaults. Success exits 0 and prints exactly one JSON object:

```json
{"schema":"closedwiz.factory-limits.v1","minutes":{"builder_start":12,"reviewer_start":5,"merge":5,"fix_after_changes":30,"builder_question_answer":15}}
```

Those are the exact object keys and stage keys; values are integer minutes.
Object order is not significant. The CLI sorts keys and emits a trailing
newline. File/content errors exit 1, leave stdout empty and emit only
`limits: invalid settings` on stderr. Bad CLI arguments exit 2. The reader and
CLI write no files, call no service and start no process beyond the CLI itself.

## Consumer boundary and proof

#2337 extends the existing journey benchmark to consume this result and include
the exact loaded settings in its output. #1480/#1481/#2338/#2339 consume the same
settings and sourced waits through their existing ops seams. Consumers read one
snapshot per calculation and carry its values into the result; an edited file
affects the next read. TL1 reports the settings, not observed waits or misses.
Endpoint evidence, thresholds, held intervals, Unknown history, distinct misses
and benchmark denominators belong to #2337. Settings confer no action,
replacement, merge, review, access or spending authority; all gates remain.

`python3 -I tools/factory-metrics/test_limits.py` proves the five literal defaults,
a real file edit reflected through Python and CLI, benign formatting and
fail-closed boundaries with synthetic files. It makes no live or enforcement
claim. Independent review checks the five goals against the confirmed decision.
